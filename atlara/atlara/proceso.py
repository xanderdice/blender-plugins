# SPDX-License-Identifier: GPL-3.0-or-later
"""El proceso de atlaseado, troceado en pasos.

Se parte en tres tiempos para que el operador pueda ir informando del
avance y dejarse cancelar con Escape:

    preparar()  reparte el atlas, mueve las UV y crea las imagenes
    paso()      hornea un canal de un objeto. Se llama N veces
    rematar()   pinta los colores planos, mezcla, guarda y cuelga el
                material

Y si el usuario cancela a medias, `tirar()` deja la escena como estaba:
lo unico que se ha tocado hasta ese momento son capas UV *nuevas* y las
imagenes del atlas, y las dos cosas se pueden quitar. Las
transformaciones y los pivotes se aplican en `rematar()`, ya al final, y
por eso una cancelacion no deja el trabajo a medio hacer.
"""

from __future__ import annotations

import math

import bpy
import numpy as np

from . import horneado, materiales, nucleo, uvs

ENTRADAS_BSDF = {
    'BASE': ("Base Color",),
    'METAL': ("Metallic",),
    'RUGOSIDAD': ("Roughness",),
    'ALFA': ("Alpha",),
    'NORMAL': ("Normal",),
    'EMISION': ("Emission Color", "Emission"),
    'FUERZA': ("Emission Strength",),
}

SUELTOS = ('BASE', 'NORMAL', 'EMISION')
COMBINABLES = ('METAL', 'RUGOSIDAD', 'AO')


# --------------------------------------------------------------- analisis

def avisos_de(fichas) -> list:
    """Lo que hay que contarle al usuario sobre sus materiales."""
    salida = []
    raros = sorted(f['nombre'] for f in fichas.values()
                   if not f['entendido'] and f['nombre'])
    if raros:
        salida.append(
            "No entiendo el shader de %s: se usa su color del visor. "
            "Conecta un Principled BSDF a la salida para que salga bien"
            % ", ".join(raros[:4]))
    mezclados = sorted(f['nombre'] for f in fichas.values()
                       if f.get('mezclado') and f['nombre'])
    if mezclados:
        salida.append(
            "%s mezcla varios shaders: se hornea el que manda segun el "
            "Fac, no la mezcla" % ", ".join(mezclados[:4]))
    return salida


def fichas_de(objetos) -> dict:
    """Radiografia de cada material distinto de la seleccion."""
    fichas = {}
    for obj in objetos:
        for ranura in obj.material_slots:
            mat = ranura.material
            clave = mat.name if mat is not None else ""
            if clave not in fichas:
                fichas[clave] = materiales.leer(mat)
        if not obj.material_slots and "" not in fichas:
            fichas[""] = materiales.leer(None)
    return fichas


def canales_pedidos(ajustes, fichas) -> list:
    """Que canales hay que hornear, mirando lo que piden los materiales."""
    usados = set()
    for ficha in fichas.values():
        usados |= ficha['usa']

    opcionales = (
        ('METAL', ajustes.usar_metal),
        ('RUGOSIDAD', ajustes.usar_rugosidad),
        ('NORMAL', ajustes.usar_normal),
        ('EMISION', ajustes.usar_emision),
        ('ALFA', ajustes.usar_alfa),
    )
    canales = ['BASE']
    for canal, encendido in opcionales:
        if encendido and (not ajustes.auto_canales or canal in usados):
            canales.append(canal)
    if ajustes.usar_ao:
        canales.append('AO')

    if ajustes.empaquetado != 'SIN' and any(c in canales
                                            for c in COMBINABLES):
        # Si ya se va a fabricar el mapa combinado, mas vale hornear los
        # dos canales que el usuario tenga encendidos: dejar uno fijo se
        # nota mucho mas que el rato que cuesta hornearlo.
        for canal, encendido in opcionales[:2]:
            if encendido and canal not in canales:
                canales.append(canal)
    return canales


def texeles_de(fichas) -> float:
    """Texeles que hacen falta por canal, no la suma de todos los mapas.

    Un material con color base, normal, metalico y rugosidad de 1024 no
    necesita 4 megatexeles de atlas: necesita 1024x1024 en *cada* imagen
    del atlas, porque cada canal va a la suya. Por eso cuenta el mapa mas
    grande de cada material y no la suma.
    """
    total = 0.0
    for ficha in fichas.values():
        mayor = 0
        for img in ficha['imagenes']:
            if img.size[0] and img.size[1]:
                mayor = max(mayor, img.size[0] * img.size[1])
        total += float(mayor)
    return total


def resolucion_de(ajustes, texeles, planos, texturizados) -> int:
    if ajustes.resolucion != '0':
        return int(ajustes.resolucion)
    if not texturizados:
        lado = nucleo.siguiente_potencia(
            int((max(planos, 1) * ajustes.celda_plana ** 2) ** 0.5) + 1)
        return max(64, min(1024, lado))
    return nucleo.resolucion_sugerida(texeles)


def margen_de(ajustes, lado, trozos=1) -> int:
    """Texeles de relleno alrededor de cada parcela.

    No depende solo de la resolucion sino tambien de cuantas parcelas
    hay, porque lo que importa es el margen *relativo al tamano de la
    parcela*: el lado tipico es lado/raiz(N), y con la treintaidosava
    parte de eso los mipmaps ya no mezclan parcelas vecinas en los
    niveles que se ven. Con margen fijo, mil islas en un atlas de 2048 se
    comerian casi la mitad del atlas en puro relleno.
    """
    if not ajustes.margen_auto:
        return int(ajustes.margen)
    ancho_parcela = lado / math.sqrt(max(1, int(trozos)))
    return max(2, min(32, int(round(ancho_parcela / 32.0))))


# ----------------------------------------------------------- los pedazos

class Trozo:
    """Una parcela del atlas y todo lo que la comparte.

    Casi siempre lleva un solo miembro: las caras de un material dentro
    de un objeto, o una isla suelta. Pero cuando varios trozos hornean
    exactamente el mismo contenido —el mismo material leido sobre el
    mismo pedazo de sus UV de origen— se juntan aqui y se llevan UNA
    sola parcela entre todos, en vez de una copia cada uno.
    """

    __slots__ = ("miembros", "medidas", "rect", "clave", "densidad")

    def __init__(self, estado, polis, bucles, medidas, rect, clave=""):
        self.miembros = [(estado, polis, bucles)]
        self.medidas = medidas
        self.rect = rect
        self.clave = clave
        self.densidad = 0.0

    @property
    def estado(self):
        return self.miembros[0][0]

    @property
    def compartido(self) -> bool:
        return len(self.miembros) > 1

    def caja(self):
        m = self.medidas
        return (m['x0'], m['y0'], m['x1'], m['y1'])

    def area_caja(self) -> float:
        m = self.medidas
        return (max(m['x1'] - m['x0'], 1e-9)
                * max(m['y1'] - m['y0'], 1e-9))

    def absorber(self, otro) -> None:
        """Se queda con el otro trozo: misma parcela para los dos."""
        self.miembros.extend(otro.miembros)
        mio, suyo = self.medidas, otro.medidas
        self.medidas = {
            'x0': min(mio['x0'], suyo['x0']),
            'y0': min(mio['y0'], suyo['y0']),
            'x1': max(mio['x1'], suyo['x1']),
            'y1': max(mio['y1'], suyo['y1']),
            # El area util de una parcela compartida es la de UN
            # ejemplar, no la suma: el contenido esta una sola vez.
            'areauv': max(mio['areauv'], suyo['areauv']),
            'area3d': max(mio['area3d'], suyo['area3d']),
        }
        self.densidad = max(self.densidad, otro.densidad)


class Estado:
    """Los datos de un objeto mientras se le construye el atlas."""

    __slots__ = ("obj", "mesh", "capa", "uv", "datos", "area3d", "areauv",
                 "fuente", "hornear", "capa_previa", "creada")

    def __init__(self, obj, capa, fuente, creada):
        self.obj = obj
        self.mesh = obj.data
        self.capa = capa
        self.fuente = fuente
        self.creada = creada
        self.hornear = False
        self.uv = uvs.leer(self.mesh, capa)
        self.datos = uvs.indices(self.mesh)
        self.area3d = uvs.areas_mundo(self.mesh, obj.matrix_world, self.datos)
        self.areauv = uvs.areas_uv(self.uv, self.datos)

    @property
    def material(self):
        return self.datos['material']


def material_de(obj, indice):
    ranuras = obj.material_slots
    if not ranuras:
        return None
    return ranuras[min(int(indice), len(ranuras) - 1)].material


def recoger(estado, fichas, ajustes, celdas_por_material, avisos,
            agrupacion) -> list:
    """Parte el objeto en trozos y aparta los materiales planos."""
    trozos = []
    material = estado.material
    indices = np.unique(material) if len(material) else []
    for indice in indices:
        polis = np.where(material == indice)[0]
        if not len(polis):
            continue
        mat = material_de(estado.obj, indice)
        clave = mat.name if mat is not None else ""
        ficha = fichas.get(clave) or materiales.leer(mat)

        if ficha['plano'] and not ajustes.usar_ao:
            celdas_por_material.setdefault(clave, []).append((estado, polis))
            continue

        estado.hornear = True
        lado = materiales.lado_mayor(mat)
        if agrupacion == 'ISLA':
            reparto = uvs.islas(estado.uv, polis, estado.datos)
            if len(reparto) > uvs.LIMITE_ISLAS:
                avisos.append("%s tiene %d islas: se reparte por material"
                              % (estado.obj.name, len(reparto)))
                reparto = [polis]
        else:
            reparto = [polis]

        clave = clave_de_reuso(mat, ficha, ajustes)
        for parte in reparto:
            parte = np.asarray(parte, dtype=np.int64)
            bucles = uvs.bucles_de(estado.datos, parte)
            if not len(bucles):
                continue
            if ajustes.orientar and not clave:
                # Enderezar gira cada trozo por su cuenta, y eso
                # descoloca dos trozos que venian del mismo sitio. Los
                # candidatos a compartir parcela no se tocan.
                uvs.orientar(estado.uv, bucles)
            medidas = uvs.medir(estado.uv, bucles, estado.area3d,
                                estado.areauv, parte)
            rect = uvs.tamano(medidas, ajustes.densidad, lado)
            trozo = Trozo(estado, parte, bucles, medidas, rect, clave)
            if medidas['areauv'] > 1e-12:
                trozo.densidad = (medidas['area3d']
                                  / medidas['areauv']) ** 0.5
            trozos.append(trozo)
    return trozos


def clave_de_reuso(mat, ficha, ajustes) -> str:
    """Con que otros trozos podria compartir parcela, o "" si con ninguno.

    Dos conjuntos de caras hornean lo mismo si leen el mismo material
    sobre el mismo pedazo de UV. Eso deja fuera:

      - los materiales cuyo resultado depende del objeto o de su
        geometria (color de vertice, Object Info, posicion...), porque
        entonces cada objeto hornea algo distinto;
      - la oclusion ambiental, que es geometrica por definicion.
    """
    if not ajustes.reutilizar or mat is None:
        return ""
    if ajustes.usar_ao:
        return ""
    if not ficha.get('entendido'):
        return ""
    if ficha.get('geometrico'):
        return ""
    return mat.name


def firma_de_contenido(estado, indice, polis, mat, ficha, ajustes):
    """Que hornea este pedazo. Dos pedazos con la misma firma dan lo mismo.

    Se calcula ANTES de mover nada, sobre las UV de origen: es el
    material mas el rectangulo de textura que lee. Si el material
    depende del objeto, no hay firma que valga y cada uno va por su
    cuenta.
    """
    clave = clave_de_reuso(mat, ficha, ajustes)
    if not clave:
        return ('unico', id(estado), int(indice))
    bucles = uvs.bucles_de(estado.datos, polis)
    if not len(bucles):
        return ('unico', id(estado), int(indice))
    u = estado.uv[bucles, 0]
    v = estado.uv[bucles, 1]
    return (clave, round(float(u.min()), 4), round(float(v.min()), 4),
            round(float(u.max()), 4), round(float(v.max()), 4))


def firmas_por_material(estados, fichas, ajustes) -> dict:
    """Firma de contenido de cada (objeto, ranura de material)."""
    salida = {}
    for estado in estados:
        material = estado.material
        if not len(material):
            continue
        for indice in np.unique(material):
            polis = np.where(material == indice)[0]
            if not len(polis):
                continue
            mat = material_de(estado.obj, indice)
            ficha = fichas.get(mat.name if mat is not None else "")
            if ficha is None:
                ficha = materiales.leer(mat)
            salida[(id(estado), int(indice))] = firma_de_contenido(
                estado, indice, polis, mat, ficha, ajustes)
    return salida


def compartir(trozos, ajustes, avisos) -> list:
    """Junta los trozos que hornean lo mismo en una sola parcela.

    El criterio para fundir dos parcelas es que no salga mas caro:
    solo se juntan si la caja que las envuelve a las dos no ocupa mas
    que las dos por separado. Asi, dos objetos con las UV encima se
    funden (la union es la misma caja, se ahorra una entera) y dos que
    usan esquinas opuestas de la textura no, porque la union seria un
    caserron medio vacio.
    """
    if not ajustes.reutilizar:
        return trozos

    por_clave = {}
    sueltos = []
    for trozo in trozos:
        if trozo.clave:
            por_clave.setdefault(trozo.clave, []).append(trozo)
        else:
            sueltos.append(trozo)

    salida = list(sueltos)
    ahorrados = 0
    for clave, grupo in por_clave.items():
        grupo.sort(key=lambda t: -t.area_caja())
        cumulos = []
        for trozo in grupo:
            for cumulo in cumulos:
                if cabe_junto(cumulo, trozo):
                    cumulo.absorber(trozo)
                    ahorrados += 1
                    break
            else:
                cumulos.append(trozo)
        salida.extend(cumulos)

    if ahorrados:
        avisos.append("Reutilizadas %d parcelas repetidas: ese sitio se "
                      "reparte entre las demas" % ahorrados)
    return salida


def cabe_junto(uno, otro, holgura=1.02) -> bool:
    """Fundir estas dos parcelas, sale a cuenta?"""
    ax0, ay0, ax1, ay1 = uno.caja()
    bx0, by0, bx1, by1 = otro.caja()
    union = (max(ax1, bx1) - min(ax0, bx0)) * (max(ay1, by1) - min(ay0, by0))
    return union <= (uno.area_caja() + otro.area_caja()) * holgura


# ------------------------------------------------------- material final

def _entrada(bsdf, canal):
    for nombre in ENTRADAS_BSDF.get(canal, ()):
        socket = bsdf.inputs.get(nombre)
        if socket is not None:
            return socket
    return None


def construir_material(nombre, mapas, capa_uv=""):
    """El material final: un Principled con los mapas del atlas.

    Las texturas se enganchan a `capa_uv` con un nodo UV Map en vez de
    dejarlas a merced de la capa activa. Sin eso, en cuanto el objeto
    conserva mas de una capa UV, basta con que alguien cambie cual es la
    activa para que el atlas se lea con las coordenadas equivocadas.
    """
    mat = bpy.data.materials.new(nombre)
    if mat.node_tree is None:
        mat.use_nodes = True
    arbol = mat.node_tree
    arbol.nodes.clear()

    salida = arbol.nodes.new('ShaderNodeOutputMaterial')
    salida.location = (520.0, 0.0)
    bsdf = arbol.nodes.new('ShaderNodeBsdfPrincipled')
    bsdf.location = (140.0, 0.0)
    arbol.links.new(bsdf.outputs["BSDF"], salida.inputs["Surface"])

    mapa_uv = None
    if capa_uv:
        mapa_uv = arbol.nodes.new('ShaderNodeUVMap')
        mapa_uv.uv_map = capa_uv
        mapa_uv.location = (-760.0, -40.0)
        mapa_uv.label = capa_uv

    def textura(imagen, y, datos):
        nodo = arbol.nodes.new('ShaderNodeTexImage')
        nodo.image = imagen
        nodo.location = (-520.0, y)
        nodo.label = imagen.name
        if datos:
            nodo.image.colorspace_settings.name = 'Non-Color'
        if mapa_uv is not None:
            arbol.links.new(mapa_uv.outputs["UV"], nodo.inputs["Vector"])
        return nodo

    base = mapas.get('BASE')
    if base is not None:
        nodo = textura(base, 320.0, False)
        arbol.links.new(nodo.outputs["Color"], _entrada(bsdf, 'BASE'))
        if mapas.get('_alfa'):
            alfa = _entrada(bsdf, 'ALFA')
            if alfa is not None:
                arbol.links.new(nodo.outputs["Alpha"], alfa)
            if hasattr(mat, "surface_render_method"):
                mat.surface_render_method = 'BLENDED'
            elif hasattr(mat, "blend_method"):
                mat.blend_method = 'BLEND'

    combinado = mapas.get('ORM') or mapas.get('MASCARA')
    if combinado is not None:
        nodo = textura(combinado, 40.0, True)
        separar = arbol.nodes.new('ShaderNodeSeparateColor')
        separar.location = (-220.0, 40.0)
        arbol.links.new(nodo.outputs["Color"], separar.inputs["Color"])
        if mapas.get('MASCARA') is not None:
            arbol.links.new(separar.outputs["Red"], _entrada(bsdf, 'METAL'))
            resta = arbol.nodes.new('ShaderNodeMath')
            resta.operation = 'SUBTRACT'
            resta.location = (-220.0, -140.0)
            resta.inputs[0].default_value = 1.0
            arbol.links.new(nodo.outputs["Alpha"], resta.inputs[1])
            arbol.links.new(resta.outputs["Value"],
                            _entrada(bsdf, 'RUGOSIDAD'))
        else:
            arbol.links.new(separar.outputs["Green"],
                            _entrada(bsdf, 'RUGOSIDAD'))
            arbol.links.new(separar.outputs["Blue"], _entrada(bsdf, 'METAL'))
    else:
        if mapas.get('METAL') is not None:
            nodo = textura(mapas['METAL'], 40.0, True)
            arbol.links.new(nodo.outputs["Color"], _entrada(bsdf, 'METAL'))
        if mapas.get('RUGOSIDAD') is not None:
            nodo = textura(mapas['RUGOSIDAD'], -160.0, True)
            arbol.links.new(nodo.outputs["Color"],
                            _entrada(bsdf, 'RUGOSIDAD'))

    normal = mapas.get('NORMAL')
    if normal is not None:
        nodo = textura(normal, -360.0, True)
        mapa = arbol.nodes.new('ShaderNodeNormalMap')
        mapa.location = (-220.0, -360.0)
        arbol.links.new(nodo.outputs["Color"], mapa.inputs["Color"])
        arbol.links.new(mapa.outputs["Normal"], _entrada(bsdf, 'NORMAL'))

    emision = mapas.get('EMISION')
    if emision is not None:
        nodo = textura(emision, -560.0, False)
        socket = _entrada(bsdf, 'EMISION')
        if socket is not None:
            arbol.links.new(nodo.outputs["Color"], socket)
        fuerza = _entrada(bsdf, 'FUERZA')
        if fuerza is not None:
            fuerza.default_value = 1.0
    return mat


def asignar(objetos, mat) -> None:
    for obj in objetos:
        obj.data.materials.clear()
        obj.data.materials.append(mat)
        indices = np.zeros(len(obj.data.polygons), dtype=np.int32)
        obj.data.polygons.foreach_set("material_index", indices)
        obj.data.update()


# -------------------------------------------------------------- proceso

class Proceso:
    """Un atlas, de principio a fin, en pasos que se pueden interrumpir."""

    def __init__(self, objetos, ajustes, sufijo="", avisos=None):
        self.objetos = objetos
        self.ajustes = ajustes
        self.sufijo = sufijo
        self.avisos = avisos if avisos is not None else []

        self.estados = []
        self.trozos = []
        self.celdas = {}
        self.fichas = {}
        self.canales = []
        self.imagenes = {}
        self.renombradas = []
        self.trabajos = []
        self.indice = 0
        self.lado = 0
        self.margen = 0
        self.reparto = None
        self.util = 0.0
        self.agrupacion_usada = ""
        self._celdas_crudas = {}
        self.prefijo = ""
        self.previo = None
        self.seleccion = None
        self.activo = None
        self.error = ""

    # ------------------------------------------------------- preparacion

    def preparar(self, context) -> str:
        ajustes = self.ajustes
        # Sin esto, matrix_world puede venir del ultimo refresco y las
        # areas de mundo salen con la escala vieja.
        context.view_layer.update()
        self.fichas = fichas_de(self.objetos)
        self.avisos.extend(avisos_de(self.fichas))
        self.canales = canales_pedidos(ajustes, self.fichas)
        self.prefijo = (ajustes.prefijo or "Atlas") + self.sufijo

        for obj in self.objetos:
            estado = self._abrir(obj)
            if estado is not None:
                self.estados.append(estado)
        if not self.estados:
            self.error = "No quedo ningun objeto que procesar"
            return self.error

        self.lado = resolucion_de(
            ajustes, texeles_de(self.fichas), len(self.fichas),
            sum(1 for f in self.fichas.values() if not f['plano']))

        if not self._repartir(context, ajustes.agrupacion):
            return self.error

        self._crear_imagenes()
        self._encolar()
        self.previo = horneado.preparar_escena(context, self.margen, 1)
        self.seleccion = list(context.selected_objects)
        self.activo = context.active_object
        return ""

    def _abrir(self, obj):
        ajustes = self.ajustes
        if not obj.data.polygons:
            self.avisos.append("%s no tiene caras: se salta" % obj.name)
            return None
        if not obj.data.uv_layers or ajustes.reproyectar:
            if not uvs.desplegar(obj, ajustes.angulo):
                self.avisos.append("%s: no se pudo desplegar la UV"
                                   % obj.name)
                if not obj.data.uv_layers:
                    return None
        previa = uvs.capa_origen(obj.data)
        nombre_previo = previa.name if previa is not None else ""
        if ajustes.capas_uv == 'UNA' and len(obj.data.uv_layers) > 1:
            self.avisos.append(
                "%s tenia %d mapas UV y se queda con uno: si alguno era el "
                "lightmap, pon los canales UV en 'Atlas primero, y guardar "
                "las viejas'" % (obj.name, len(obj.data.uv_layers)))
        capa, fuente = uvs.preparar_capa(obj)
        if capa is None:
            self.avisos.append("%s: no caben mas capas UV (maximo 8)"
                               % obj.name)
            return None
        return Estado(obj, capa, fuente, nombre_previo)

    def _foto(self):
        """Guarda todo lo que un reparto deja tocado, para poder volver."""
        return {
            'uv': {id(e): e.uv.copy() for e in self.estados},
            'hornear': {id(e): e.hornear for e in self.estados},
            'reparto': self.reparto, 'trozos': self.trozos,
            'celdas': dict(self.celdas), 'crudas': self._celdas_crudas,
            'agrupacion': self.agrupacion_usada, 'margen': self.margen,
            'util': self.util,
        }

    def _volver(self, foto) -> None:
        for estado in self.estados:
            estado.uv = foto['uv'][id(estado)]
            estado.hornear = foto['hornear'][id(estado)]
            uvs.escribir(estado.mesh, estado.capa, estado.uv)
        self.reparto = foto['reparto']
        self.trozos = foto['trozos']
        self.celdas = foto['celdas']
        self._celdas_crudas = foto['crudas']
        self.agrupacion_usada = foto['agrupacion']
        self.margen = foto['margen']
        self.util = foto['util']

    def _repartir(self, context, agrupacion) -> bool:
        """Elige quien reparte el atlas.

        En automatico se reparte de las dos maneras y gana la que deja
        mas texeles utiles. Hace falta probar las dos porque ninguna gana
        siempre: medido, el empaquetador por forma va de empatar a dar un
        64% mas de texeles segun la escena, y cuando empata se ha llevado
        quince segundos para nada.
        """
        modo = self.ajustes.empaquetador
        if modo == 'CAJA':
            return self._repartir_por_cajas(agrupacion)

        if modo == 'FORMA':
            fallo = self._repartir_por_forma(context)
            if not fallo:
                return True
            self.avisos.append(
                "No se pudo empaquetar por la forma (%s): se reparte por "
                "caja envolvente" % fallo)
            return self._repartir_por_cajas(agrupacion)

        # Automatico: primero el de cajas, que es el barato.
        partida = {id(e): e.uv.copy() for e in self.estados}
        if not self._repartir_por_cajas(agrupacion):
            self.error = ""
            for estado in self.estados:
                estado.uv = partida[id(estado)].copy()
            return not self._repartir_por_forma(context) or self._fallar()
        cajas = self._foto()

        for estado in self.estados:
            estado.uv = partida[id(estado)].copy()
            uvs.escribir(estado.mesh, estado.capa, estado.uv)
        self.celdas = {}
        fallo = self._repartir_por_forma(context)
        if fallo or self.util <= cajas['util']:
            self._volver(cajas)
        return True

    def _fallar(self) -> bool:
        self.error = self.error or ("No cabe en %d px. Sube la resolucion "
                                    "o baja el margen" % self.lado)
        return False

    def _separar_planos(self):
        """Aparta los materiales de un solo color del resto.

        Devuelve (celdas_por_material, caras_con_textura_por_estado).
        """
        celdas, texturizadas = {}, {}
        for estado in self.estados:
            estado.hornear = False
            material = estado.material
            con_textura = []
            for indice in (np.unique(material) if len(material) else []):
                polis = np.where(material == indice)[0]
                if not len(polis):
                    continue
                mat = material_de(estado.obj, indice)
                clave = mat.name if mat is not None else ""
                ficha = self.fichas.get(clave) or materiales.leer(mat)
                if ficha['plano'] and not self.ajustes.usar_ao:
                    celdas.setdefault(clave, []).append((estado, polis))
                else:
                    estado.hornear = True
                    con_textura.append(polis)
            texturizadas[id(estado)] = (
                np.concatenate(con_textura) if con_textura
                else np.zeros(0, dtype=np.int64))
        return celdas, texturizadas

    def _repartir_por_forma(self, context) -> str:
        """Reparte delegando en el empaquetador por contorno de Blender.

        Las celdas de los materiales planos se colocan aqui, a mano, en
        su franja, y sus caras se dejan sin seleccionar: el packer de
        Blender solo mueve lo que esta seleccionado, asi que no las
        desparrama por el atlas.
        """
        celdas_crudas, texturizadas = self._separar_planos()
        # Las firmas se sacan AHORA, con las UV todavia en su sitio de
        # origen: despues de empaquetar ya no se sabe quien era copia de
        # quien.
        firmas = firmas_por_material(self.estados, self.fichas, self.ajustes)
        islas = 0
        for estado in self.estados:
            polis = texturizadas[id(estado)]
            if len(polis):
                islas += len(uvs.islas(estado.uv, polis, estado.datos))
        self.margen = margen_de(self.ajustes, self.lado, max(1, islas))

        franja, celdas = nucleo.franja_planos(
            len(celdas_crudas), self.ajustes.celda_plana, self.lado,
            self.lado)
        if celdas_crudas and not celdas:
            return "no caben las celdas de color"

        for indice, (clave, partes) in enumerate(celdas_crudas.items()):
            celda = celdas[indice]
            self.celdas[clave] = celda
            for estado, polis in partes:
                uvs.colocar_plano(estado.uv, estado.datos, polis, celda,
                                  self.lado, self.lado)
        for estado in self.estados:
            uvs.escribir(estado.mesh, estado.capa, estado.uv)

        con_textura = [e for e in self.estados if len(texturizadas[id(e)])]
        if con_textura:
            marcadas = {}
            for estado in self.estados:
                marcadas[id(estado)] = uvs.seleccion_caras(estado.mesh)
                uvs.marcar_caras(estado.mesh, texturizadas[id(estado)],
                                 estado.datos)
            if self.ajustes.densidad == 'TEXEL':
                self._escalar_por_textura(texturizadas)
            nombres = {id(e): e.capa.name for e in self.estados}
            fallo = uvs.empaquetar_por_forma(
                context, [e.obj for e in self.estados],
                forma=self.ajustes.forma,
                margen=uvs.margen_seguro(self.margen, self.lado, islas),
                uniforme=(self.ajustes.densidad == 'UNIFORME'),
                girar=self.ajustes.rotar)
            # Pasar por modo edicion rehace las capas UV: las referencias
            # que teniamos apuntan a datos vacios y hay que volver a
            # pedirlas por nombre.
            for estado in self.estados:
                capa = estado.mesh.uv_layers.get(nombres[id(estado)])
                if capa is not None:
                    estado.capa = capa
                uvs.devolver_caras(estado.mesh, marcadas[id(estado)])
            if fallo:
                return fallo
            # La franja de colores va arriba, asi que lo empaquetado se
            # aplasta lo justo para caber debajo. Es un aplastamiento de
            # un dos por ciento tipico: se pierde menos que dejando el
            # hueco sin usar.
            factor = (self.lado - franja) / float(self.lado)
            for estado in self.estados:
                estado.uv = uvs.leer(estado.mesh, estado.capa)
                if factor < 1.0:
                    uvs.encoger(estado.uv,
                                uvs.bucles_de(estado.datos,
                                              texturizadas[id(estado)]),
                                1.0, factor)
                    uvs.escribir(estado.mesh, estado.capa, estado.uv)

        # Aqui esta el detalle que decide si el automatico elige bien:
        # si se suman las areas de todos los trozos, cinco copias del
        # mismo dibujo puntuan cinco veces y el reparto que DUPLICA gana
        # al que comparte. Se cuenta una sola vez por contenido.
        util = float(sum(c[2] * c[2] for c in self.celdas.values()))
        grupos = {}
        for estado in self.estados:
            polis = texturizadas[id(estado)]
            if not len(polis):
                continue
            areas = uvs.areas_uv(estado.uv, estado.datos)
            material = estado.material
            for indice in np.unique(material[polis]):
                suyas = polis[material[polis] == indice]
                if not len(suyas):
                    continue
                firma = firmas.get((id(estado), int(indice)),
                                   ('unico', id(estado), int(indice)))
                area = float(areas[suyas].sum())
                grupos[firma] = max(grupos.get(firma, 0.0), area)
        util += sum(grupos.values()) * self.lado * self.lado
        self.util = util / float(self.lado * self.lado)
        self.trozos = []
        self._celdas_crudas = celdas_crudas
        self.agrupacion_usada = 'FORMA'
        self.reparto = {
            'ocupacion': self.util, 'escala': 0.0, 'celdas': celdas,
            'tam': [], 'colocaciones': [],
        }
        return ""

    def _escalar_por_textura(self, texturizadas) -> None:
        """Agranda cada trozo en proporcion a su textura de origen.

        El empaquetador de Blender respeta el tamano relativo de las
        islas, asi que basta con dejarlas escaladas como queremos antes
        de llamarlo: una isla que venia de una textura 4K se queda
        cuatro veces mas grande que una que venia de 1K, y el atlas le
        reserva cuatro veces mas texeles.
        """
        for estado in self.estados:
            if not len(texturizadas[id(estado)]):
                continue
            material = estado.material
            tocado = False
            for indice in np.unique(material[texturizadas[id(estado)]]):
                polis = np.where(material == indice)[0]
                mat = material_de(estado.obj, indice)
                lado = float(materiales.lado_mayor(mat))
                if lado <= 0.0 or abs(lado - 1.0) < 1e-9:
                    continue
                bucles = uvs.bucles_de(estado.datos, polis)
                if len(bucles):
                    estado.uv[bucles] *= lado
                    tocado = True
            if tocado:
                uvs.escribir(estado.mesh, estado.capa, estado.uv)

    def _repartir_por_cajas(self, agrupacion) -> bool:
        """Reparte el atlas. En AUTO prueba las dos formas y gana la mejor.

        El criterio no es cuanto atlas se llena, que enganaria: trocear
        en islas mete mas margenes y llena mas sin dar mas nitidez. Lo
        que se compara es la escala que sale de la biseccion, que es
        justamente los texeles por unidad de mundo que va a tener el
        resultado. Mas escala, mas definicion.
        """
        opciones = ('ISLA', 'GRUPO') if agrupacion == 'AUTO' else (agrupacion,)
        originales = {id(e): e.uv.copy() for e in self.estados}
        mejor = None
        for opcion in opciones:
            celdas, trozos = {}, []
            for estado in self.estados:
                estado.uv = originales[id(estado)].copy()
                estado.hornear = False
                trozos.extend(recoger(estado, self.fichas, self.ajustes,
                                      celdas, self.avisos, opcion))
            trozos = compartir(trozos, self.ajustes, self.avisos)
            margen = margen_de(self.ajustes, self.lado, len(trozos))
            reparto = nucleo.repartir(
                [t.rect for t in trozos], len(celdas), self.lado, self.lado,
                margen, self.ajustes.celda_plana, self.ajustes.rotar)
            if reparto is None:
                continue
            candidato = {
                'reparto': reparto, 'trozos': trozos, 'celdas': celdas,
                'opcion': opcion, 'escala': reparto['escala'],
                'margen': margen,
                'uv': {id(e): e.uv for e in self.estados},
                'hornear': {id(e): e.hornear for e in self.estados},
            }
            if mejor is None or candidato['escala'] > mejor['escala']:
                mejor = candidato
        if mejor is None:
            self.error = ("No cabe en %d px. Sube la resolucion o baja el "
                          "margen" % self.lado)
            return False

        for estado in self.estados:
            estado.uv = mejor['uv'][id(estado)]
            estado.hornear = mejor['hornear'][id(estado)]
        self.reparto = mejor['reparto']
        self.margen = mejor['margen']
        self.trozos = mejor['trozos']
        self.agrupacion_usada = mejor['opcion']
        self._celdas_crudas = mejor['celdas']
        self._mover_uvs()
        return True

    def _mover_uvs(self) -> None:
        margen = self.margen
        util = 0.0
        for i, trozo in enumerate(self.trozos):
            x, y, girado = self.reparto['colocaciones'][i]
            ancho_t, alto_t = self.reparto['tam'][i]
            ancho_c = ancho_t - 2 * margen
            alto_c = alto_t - 2 * margen
            if girado:
                caja = (x, y, alto_c, ancho_c, True)
            else:
                caja = (x, y, ancho_c, alto_c, False)
            for estado, _polis, bucles in trozo.miembros:
                uvs.colocar(estado.uv, bucles, trozo.medidas, caja,
                            self.lado, self.lado, margen)
            util += self._texeles_utiles(trozo, caja)

        for indice, (clave, partes) in enumerate(self._celdas_crudas.items()):
            celda = self.reparto['celdas'][indice]
            self.celdas[clave] = celda
            util += float(celda[2] * celda[2])
            for estado, polis in partes:
                uvs.colocar_plano(estado.uv, estado.datos, polis, celda,
                                  self.lado, self.lado)
        self.util = util / float(self.lado * self.lado)

        for estado in self.estados:
            uvs.escribir(estado.mesh, estado.capa, estado.uv)

    @staticmethod
    def _texeles_utiles(trozo, caja) -> float:
        """Texeles que el trozo cubre DE VERDAD, no los de su caja.

        Es la vara honesta de medir el aprovechamiento: una isla en L
        llena su rectangulo a medias, y contar el rectangulo daria un
        numero bonito que no se corresponde con la nitidez que se ve.
        """
        medidas = trozo.medidas
        ex = max(medidas['x1'] - medidas['x0'], 1e-9)
        ey = max(medidas['y1'] - medidas['y0'], 1e-9)
        ancho_c, alto_c = caja[2], caja[3]
        if caja[4]:
            factor = (ancho_c / ey) * (alto_c / ex)
        else:
            factor = (ancho_c / ex) * (alto_c / ey)
        return medidas['areauv'] * factor

    def _crear_imagenes(self) -> None:
        for canal in self.canales:
            sufijo = "Alpha" if canal == 'ALFA' \
                else horneado.SUFIJOS.get(canal, canal)
            imagen, vieja = horneado.nueva_imagen(
                "%s_%s" % (self.prefijo, sufijo), self.lado, self.lado,
                canal, alfa=(canal == 'BASE'))
            self.imagenes[canal] = imagen
            if vieja is not None:
                self.renombradas.append(vieja)

    def _encolar(self) -> None:
        for canal in self.canales:
            for estado in self.estados:
                if estado.hornear or canal == 'AO':
                    self.trabajos.append((canal, estado))

    # -------------------------------------------------------------- pasos

    @property
    def total(self) -> int:
        return len(self.trabajos)

    @property
    def terminado(self) -> bool:
        return self.indice >= len(self.trabajos)

    def etiqueta(self) -> str:
        if self.terminado:
            return "rematando"
        canal, estado = self.trabajos[self.indice]
        return "%s de %s" % (materiales.NOMBRE_CANAL.get(canal, canal),
                             estado.obj.name)

    def paso(self, context) -> bool:
        """Hornea un canal de un objeto. Devuelve si quedan mas."""
        if self.terminado:
            return False
        canal, estado = self.trabajos[self.indice]
        self.indice += 1

        if hasattr(context.scene, "cycles"):
            context.scene.cycles.samples = \
                self.ajustes.ao_muestras if canal == 'AO' else 1

        apagados = horneado.apagar_los_demas(context, estado.obj) \
            if canal == 'AO' else []
        visto = horneado.visible(estado.obj)
        try:
            fallo = horneado.hornear_objeto(
                context, estado.obj, canal, self.imagenes[canal],
                estado.capa.name, estado.fuente, self.ajustes.voltear_verde)
        finally:
            horneado.restaurar_visible(estado.obj, visto)
            horneado.encender_los_demas(apagados)
        if fallo:
            self.avisos.append(fallo)
        return not self.terminado

    # ------------------------------------------------------------- remate

    def rematar(self, context) -> dict:
        self._devolver_escena(context)
        self._pintar_planos()
        mapas = self._componer()
        capa_uv = self._ordenar_capas()
        mat = construir_material(self.prefijo, mapas, capa_uv)
        asignar([e.obj for e in self.estados], mat)
        return {
            'material': mat.name,
            'resolucion': self.lado,
            'margen': self.margen,
            'ocupacion': self.reparto['ocupacion'],
            'util': self.util,
            'trozos': len(self.trozos),
            'celdas': len(self.celdas),
            'agrupacion': self.agrupacion_usada,
            'canales': [c for c in self.canales if c != 'ALFA'],
            'objetos': len(self.estados),
            'capas_uv': capa_uv,
            'mapas': sorted(k for k in mapas if not k.startswith("_")),
        }

    def _ordenar_capas(self) -> str:
        """Deja las capas UV como toca y devuelve el nombre de la del atlas.

        Con 'CONSERVAR' se guardan las UV originales, pero el atlas tiene
        que quedarse el PRIMERO: los exportadores mandan al canal 0 la
        primera capa de la lista, y ese es el canal que lee el material
        en cualquier motor.
        """
        solo_atlas = self.ajustes.capas_uv == 'UNA'
        nombre = uvs.CAPA_FINAL if solo_atlas else uvs.CAPA
        for estado in self.estados:
            uvs.quitar_fuente(estado.obj)
            if solo_atlas:
                uvs.dejar_una(estado.obj)
            elif not uvs.poner_primera(estado.obj, uvs.CAPA):
                self.avisos.append(
                    "%s: no se pudo dejar el atlas como primer canal UV"
                    % estado.obj.name)
        return nombre

    def _pintar_planos(self) -> None:
        for canal, imagen in self.imagenes.items():
            lista = []
            for clave, celda in self.celdas.items():
                ficha = self.fichas.get(clave)
                if ficha is None:
                    continue
                if canal == 'AO':
                    color = (1.0, 1.0, 1.0, 1.0)
                else:
                    color = ficha['valores'].get(
                        canal, materiales.POR_DEFECTO.get(canal))
                if canal in ('METAL', 'RUGOSIDAD', 'ALFA'):
                    color = (color[0], color[0], color[0], 1.0)
                elif canal == 'BASE':
                    color = (color[0], color[1], color[2], 1.0)
                lista.append((celda, color))
            horneado.pintar_celdas(imagen, lista)

    def _componer(self) -> dict:
        mapas = {}
        temporales = []
        imagenes = self.imagenes
        if imagenes.get('ALFA') is not None \
                and imagenes.get('BASE') is not None:
            horneado.meter_alfa(imagenes['BASE'], imagenes['ALFA'])
            mapas['_alfa'] = True
            temporales.append(imagenes.pop('ALFA'))

        hay = any(c in imagenes for c in COMBINABLES)
        if self.ajustes.empaquetado != 'SIN' and hay:
            clave = 'MASCARA' if self.ajustes.empaquetado == 'MASCARA' \
                else 'ORM'
            mapas[clave] = horneado.mezclar(
                "%s_%s" % (self.prefijo, horneado.SUFIJOS[clave]),
                self.lado, self.lado, imagenes, clave)
            for canal in COMBINABLES:
                if canal in imagenes:
                    temporales.append(imagenes.pop(canal))

        for canal, imagen in imagenes.items():
            if canal in SUELTOS or canal in COMBINABLES:
                mapas[canal] = imagen

        carpeta = self.ajustes.carpeta \
            if self.ajustes.guardado == 'DISCO' else ""
        for clave, imagen in mapas.items():
            if not clave.startswith("_"):
                horneado.guardar(imagen, carpeta,
                                 self.ajustes.formato,
                                 self.ajustes.calidad, clave)
        horneado.tirar_imagenes(temporales)
        return mapas

    def _devolver_escena(self, context) -> None:
        if self.previo is not None:
            horneado.restaurar_escena(context, self.previo)
            self.previo = None
        if self.seleccion is None:
            return
        for obj in list(context.selected_objects):
            obj.select_set(False)
        for obj in self.seleccion:
            try:
                obj.select_set(True)
            except ReferenceError:
                pass
        if self.activo is not None:
            try:
                context.view_layer.objects.active = self.activo
            except ReferenceError:
                pass
        self.seleccion = None

    # -------------------------------------------------------- cancelacion

    def tirar_todo(self, context) -> None:
        """Deshace lo hecho: quita las capas UV nuevas y las imagenes."""
        self._devolver_escena(context)
        horneado.tirar_imagenes(list(self.imagenes.values()))
        self.imagenes = {}
        for vieja, nombre in self.renombradas:
            try:
                vieja.name = nombre
            except (ReferenceError, RuntimeError):
                pass
        self.renombradas = []
        for estado in self.estados:
            try:
                uvs.deshacer_capa(estado.obj, estado.creada)
            except (ReferenceError, RuntimeError):
                pass
        self.estados = []


# ----------------------------------------------------------------- tanda

class Tanda:
    """Uno o varios atlas seguidos, avanzando de paso en paso.

    En modo "un atlas para todo" hay un solo lote. En "un atlas por
    objeto" hay uno por objeto, y se preparan de uno en uno para no
    tener veinte juegos de imagenes abiertos a la vez.
    """

    def __init__(self, lotes, ajustes):
        self.lotes = lotes
        self.ajustes = ajustes
        self.indice = 0
        self.actual = None
        self.resultados = []
        self.avisos = []
        self.error = ""

    @property
    def terminado(self) -> bool:
        return self.actual is None and self.indice >= len(self.lotes)

    def fraccion(self) -> float:
        if not self.lotes:
            return 1.0
        trozo = 1.0 / len(self.lotes)
        hecho = self.indice * trozo
        if self.actual is not None and self.actual.total:
            hecho += trozo * self.actual.indice / float(self.actual.total)
        return min(1.0, max(0.0, hecho))

    def etiqueta(self) -> str:
        if self.terminado:
            return "terminando"
        partes = []
        if len(self.lotes) > 1:
            partes.append("objeto %d/%d" % (self.indice + 1, len(self.lotes)))
        if self.actual is None:
            # El reparto por forma es una sola llamada al packer de
            # Blender, que puede tirarse quince segundos sin dar senales.
            # Mas vale decirlo que parecer colgado.
            partes.append("repartiendo el atlas"
                          if self.ajustes.empaquetador == 'CAJA'
                          else "repartiendo el atlas (puede tardar)")
        else:
            partes.append("%s  (%d/%d)" % (self.actual.etiqueta(),
                                           self.actual.indice + 1,
                                           max(1, self.actual.total)))
        return " · ".join(partes)

    def avanzar(self, context) -> bool:
        """Da un paso de trabajo. Devuelve False si hay que parar."""
        if self.terminado:
            return False
        if self.actual is None:
            sufijo, objetos = self.lotes[self.indice]
            self.actual = Proceso(objetos, self.ajustes, sufijo, self.avisos)
            self.error = self.actual.preparar(context)
            if self.error:
                return False
            return True
        if not self.actual.terminado:
            self.actual.paso(context)
            return True
        self.resultados.append(self.actual.rematar(context))
        self.actual = None
        self.indice += 1
        return True

    def tirar_todo(self, context) -> None:
        if self.actual is not None:
            self.actual.tirar_todo(context)
            self.actual = None
