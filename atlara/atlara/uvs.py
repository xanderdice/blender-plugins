# SPDX-License-Identifier: GPL-3.0-or-later
"""Todo lo que toca coordenadas UV.

Se trabaja sobre los bucles de la malla (mesh.loops) con numpy en vez de
con bmesh: es bastante mas rapido y aqui no hace falta topologia, solo
mover coordenadas de sitio. Las areas, las islas y el giro a caja minima
estan vectorizados; en una malla de medio millon de caras la diferencia
con un bucle de Python es de minutos a segundos.

Vocabulario:

  trozo : el pedazo de UV que viaja junto al atlas. O todas las caras de
          un material dentro de un objeto, o una isla suelta.
  celda : el cuadradito que se lleva un material plano, sin textura.
"""

from __future__ import annotations

import math

import bpy
import numpy as np

CAPA = "Atlas"
CAPA_FINAL = "UVMap"
FUENTE = "Atlas.origen"
LIMITE_ISLAS = 6000
TOPE_CASCO = 20000


# ------------------------------------------------------------- capas UV

def capa_origen(mesh):
    if not mesh.uv_layers:
        return None
    for capa in mesh.uv_layers:
        if capa.active_render:
            return capa
    return mesh.uv_layers[0]


def preparar_capa(obj, nombre=CAPA):
    """Crea la capa del atlas copiando la original.

    Devuelve (capa_del_atlas, nombre_de_la_capa_de_origen). La de origen
    es la que leen las texturas durante el horneado, asi que nunca puede
    ser la misma que se esta moviendo.
    """
    mesh = obj.data
    origen = capa_origen(mesh)
    if origen is None or len(mesh.uv_layers) >= 8:
        return None, ""

    mesh.uv_layers.active = origen
    if origen.name == nombre:
        # Ya se atlaseo antes: se guarda una copia intacta como fuente.
        vieja = mesh.uv_layers.get(FUENTE)
        if vieja is not None:
            mesh.uv_layers.remove(vieja)
            mesh.uv_layers.active = mesh.uv_layers[nombre]
        fuente = mesh.uv_layers.new(name=FUENTE, do_init=True)
        capa = mesh.uv_layers[nombre]
        nombre_origen = fuente.name if fuente is not None else nombre
    else:
        vieja = mesh.uv_layers.get(nombre)
        if vieja is not None:
            mesh.uv_layers.remove(vieja)
            origen = capa_origen(mesh)
            mesh.uv_layers.active = origen
        nombre_origen = origen.name
        capa = mesh.uv_layers.new(name=nombre, do_init=True)

    if capa is None:
        return None, nombre_origen
    capa.active_render = True
    mesh.uv_layers.active = capa
    return capa, nombre_origen


def quitar_fuente(obj) -> None:
    """Tira la copia de trabajo que se hizo al re-atlasear."""
    capa = obj.data.uv_layers.get(FUENTE)
    if capa is not None:
        obj.data.uv_layers.remove(capa)


def deshacer_capa(obj, nombre_previo="") -> None:
    """Deja las capas UV como estaban antes de empezar.

    Si el objeto ya venia atlaseado, la capa "Atlas" se sobreescribio,
    pero "Atlas.origen" guarda una copia intacta: se devuelve desde ahi.
    """
    mesh = obj.data
    atlas = mesh.uv_layers.get(CAPA)
    fuente = mesh.uv_layers.get(FUENTE)
    if nombre_previo == CAPA and atlas is not None and fuente is not None:
        escribir(mesh, atlas, leer(mesh, fuente))
        mesh.uv_layers.remove(fuente)
    else:
        if atlas is not None and nombre_previo != CAPA:
            mesh.uv_layers.remove(atlas)
        if fuente is not None:
            fuente = mesh.uv_layers.get(FUENTE)
            if fuente is not None:
                mesh.uv_layers.remove(fuente)
    previa = mesh.uv_layers.get(nombre_previo)
    if previa is not None:
        previa.active_render = True
        mesh.uv_layers.active = previa


def poner_primera(obj, nombre) -> bool:
    """Deja esa capa UV la primera de la lista.

    Importa mas de lo que parece: los exportadores se guian por el ORDEN
    de mesh.uv_layers, no por cual es la activa ni por active_render.
    Medido exportando a glTF: con la capa del atlas en segundo lugar,
    TEXCOORD_0 se lleva las UV viejas y el atlas se ve mal en el motor.

    Blender no tiene forma de mover una capa de sitio, asi que se leen
    todas, se borran y se vuelven a crear en el orden que toca.
    """
    mesh = obj.data
    if not mesh.uv_layers or mesh.uv_layers[0].name == nombre:
        return True
    if mesh.uv_layers.get(nombre) is None:
        return False
    guardado = [(c.name, leer(mesh, c).copy(), c.active_render)
                for c in mesh.uv_layers]
    activa = mesh.uv_layers.active
    nombre_activa = activa.name if activa is not None else nombre
    guardado.sort(key=lambda g: g[0] != nombre)
    while mesh.uv_layers:
        mesh.uv_layers.remove(mesh.uv_layers[0])
    for nom, datos, render in guardado:
        capa = mesh.uv_layers.new(name=nom, do_init=False)
        if capa is None:
            return False
        escribir(mesh, capa, datos)
        if render:
            capa.active_render = True
    vuelta = mesh.uv_layers.get(nombre_activa)
    if vuelta is not None:
        mesh.uv_layers.active = vuelta
    return True


def dejar_una(obj, nombre_atlas=CAPA, nombre_final=CAPA_FINAL) -> None:
    """Borra el resto de capas UV y renombra la del atlas."""
    mesh = obj.data
    if mesh.uv_layers.get(nombre_atlas) is None:
        return
    for otra in [c for c in mesh.uv_layers if c.name != nombre_atlas]:
        mesh.uv_layers.remove(otra)
    capa = mesh.uv_layers.get(nombre_atlas)
    if capa is not None:
        capa.name = nombre_final
        capa.active_render = True
        mesh.uv_layers.active = capa


def leer(mesh, capa):
    datos = np.empty(len(mesh.loops) * 2, dtype=np.float32)
    capa.data.foreach_get("uv", datos)
    return datos.reshape(-1, 2)


def escribir(mesh, capa, uv) -> None:
    capa.data.foreach_set("uv", uv.reshape(-1).astype(np.float32))
    mesh.update()


def desplegar(obj, angulo=1.15, margen=0.02) -> bool:
    """Smart UV Project para los objetos que llegan sin ninguna UV."""
    anterior = bpy.context.view_layer.objects.active
    seleccion = list(bpy.context.selected_objects)
    try:
        for o in seleccion:
            o.select_set(False)
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        if not obj.data.uv_layers:
            obj.data.uv_layers.new(name=CAPA)
        # Smart UV Project escribe en la capa activa de EDICION, pero el
        # atlas se construye leyendo la activa de RENDER. Si no se hacen
        # coincidir, reproyectar machaca una capa cualquiera (el lightmap,
        # por ejemplo) y deja intacta la que de verdad se va a usar.
        origen = capa_origen(obj.data)
        if origen is not None:
            obj.data.uv_layers.active = origen
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_all(action='SELECT')
        bpy.ops.uv.smart_project(angle_limit=angulo, island_margin=margen,
                                 correct_aspect=True, scale_to_bounds=False)
        bpy.ops.object.mode_set(mode='OBJECT')
        return True
    except RuntimeError:
        try:
            if obj.mode != 'OBJECT':
                bpy.ops.object.mode_set(mode='OBJECT')
        except RuntimeError:
            pass
        return False
    finally:
        for o in bpy.context.selected_objects:
            o.select_set(False)
        for o in seleccion:
            try:
                o.select_set(True)
            except ReferenceError:
                pass
        if anterior is not None:
            bpy.context.view_layer.objects.active = anterior


# -------------------------------------------------------------- medidas

def indices(mesh) -> dict:
    """Los arrays de la malla que se usan una y otra vez.

    `siguiente` da, para cada bucle, el siguiente bucle de su misma cara,
    cerrando el ciclo. Con el se calculan areas y perimetros de golpe,
    sin recorrer poligonos en Python.
    """
    n = len(mesh.polygons)
    m = len(mesh.loops)
    inicio = np.empty(n, dtype=np.int32)
    total = np.empty(n, dtype=np.int32)
    material = np.empty(n, dtype=np.int32)
    mesh.polygons.foreach_get("loop_start", inicio)
    mesh.polygons.foreach_get("loop_total", total)
    mesh.polygons.foreach_get("material_index", material)
    vert = np.empty(m, dtype=np.int32)
    mesh.loops.foreach_get("vertex_index", vert)

    inicio = inicio.astype(np.int64)
    total = total.astype(np.int64)
    siguiente = np.arange(1, m + 1, dtype=np.int64)
    if n:
        siguiente[inicio + total - 1] = inicio
    if m:
        siguiente = np.clip(siguiente, 0, m - 1)
    poli = np.repeat(np.arange(n, dtype=np.int64), total) if n \
        else np.zeros(0, dtype=np.int64)
    return {
        'inicio': inicio, 'total': total, 'material': material,
        'vert': vert, 'siguiente': siguiente, 'poli': poli,
        'caras': n, 'bucles': m,
    }


def areas_uv(uv, datos):
    """Area de cada poligono en el espacio UV (formula del zapato)."""
    n = datos['caras']
    if not n or not datos['bucles']:
        return np.zeros(n, dtype=np.float64)
    s = datos['siguiente']
    u = uv[:, 0].astype(np.float64)
    v = uv[:, 1].astype(np.float64)
    cruz = u * v[s] - u[s] * v
    return 0.5 * np.abs(np.bincount(datos['poli'], weights=cruz,
                                    minlength=n))


def areas_mundo(mesh, matriz, datos):
    """Area de cada poligono ya en el mundo, sin aplicar la transformacion.

    Hace falta para repartir el atlas con la misma densidad de texel en
    toda la seleccion. Se calcula asi, y no aplicando escala antes de
    tiempo, para que cancelar a media faena no deje objetos tocados.
    """
    n = datos['caras']
    if not n or not datos['bucles']:
        return np.zeros(n, dtype=np.float64)
    co = np.empty(len(mesh.vertices) * 3, dtype=np.float64)
    mesh.vertices.foreach_get("co", co)
    lineal = np.array([list(fila) for fila in matriz.to_3x3()],
                      dtype=np.float64)
    co = co.reshape(-1, 3) @ lineal.T
    p = co[datos['vert']]
    q = p[datos['siguiente']]
    c = np.cross(p, q)
    sx = np.bincount(datos['poli'], weights=c[:, 0], minlength=n)
    sy = np.bincount(datos['poli'], weights=c[:, 1], minlength=n)
    sz = np.bincount(datos['poli'], weights=c[:, 2], minlength=n)
    return 0.5 * np.sqrt(sx * sx + sy * sy + sz * sz)


def bucles_de(datos, polis):
    """Indices de todos los bucles de esas caras."""
    polis = np.asarray(polis, dtype=np.int64)
    if not len(polis):
        return np.zeros(0, dtype=np.int64)
    total = datos['total'][polis]
    inicio = datos['inicio'][polis]
    repes = np.repeat(inicio, total)
    corridas = np.arange(len(repes), dtype=np.int64)
    saltos = np.concatenate(([0], np.cumsum(total)[:-1]))
    corridas -= np.repeat(saltos, total)
    return repes + corridas


def islas(uv, polis, datos):
    """Islas UV entre esas caras. Une por vertice y UV coincidentes."""
    polis = np.asarray(polis, dtype=np.int64)
    if len(polis) <= 1:
        return [polis]
    bucles = bucles_de(datos, polis)
    clave = np.stack([
        datos['vert'][bucles].astype(np.int64),
        np.round(uv[bucles, 0].astype(np.float64) * 1e5).astype(np.int64),
        np.round(uv[bucles, 1].astype(np.float64) * 1e5).astype(np.int64),
    ], axis=1)
    _unicos, grupo = np.unique(clave, axis=0, return_inverse=True)
    grupo = np.asarray(grupo).reshape(-1)

    cara = datos['poli'][bucles]
    orden = np.argsort(grupo, kind='stable')
    g = grupo[orden]
    c = cara[orden]
    mismo = g[1:] == g[:-1]
    izq = c[:-1][mismo]
    der = c[1:][mismo]

    padre = {int(p): int(p) for p in polis}

    def raiz(x):
        while padre[x] != x:
            padre[x] = padre[padre[x]]
            x = padre[x]
        return x

    for a, b in zip(izq.tolist(), der.tolist()):
        ra, rb = raiz(a), raiz(b)
        if ra != rb:
            padre[ra] = rb

    reparto = {}
    for p in polis.tolist():
        reparto.setdefault(raiz(p), []).append(p)
    return [np.asarray(v, dtype=np.int64) for v in reparto.values()]


def medir(uv, bucles, areas3d, areasuv, polis):
    u = uv[bucles, 0]
    v = uv[bucles, 1]
    return {
        'x0': float(u.min()), 'x1': float(u.max()),
        'y0': float(v.min()), 'y1': float(v.max()),
        'area3d': float(np.sum(areas3d[polis])),
        'areauv': float(np.sum(areasuv[polis])),
    }


def tamano(medidas, densidad, lado_textura=1024):
    """Ancho y alto del trozo en las unidades que usa el empaquetador."""
    ancho = max(medidas['x1'] - medidas['x0'], 1e-6)
    alto = max(medidas['y1'] - medidas['y0'], 1e-6)
    if densidad == 'ORIGINAL':
        return ancho, alto
    if densidad == 'TEXEL':
        return ancho * lado_textura, alto * lado_textura
    # UNIFORME: misma densidad de texel en toda la seleccion.
    if medidas['areauv'] <= 1e-12 or medidas['area3d'] <= 1e-12:
        return ancho, alto
    factor = (medidas['area3d'] / medidas['areauv']) ** 0.5
    return ancho * factor, alto * factor


# ------------------------------------------------- giro a la caja minima

def _adelgazar(pts):
    """Tira los puntos que seguro no pintan nada en el casco.

    Heuristica de Akl-Toussaint: se cogen los ocho extremos (en x, en y y
    en las dos diagonales), y todo lo que caiga dentro de ese octogono no
    puede estar en el casco. El descarte es vectorizado y deja la cadena
    monotona, que es un bucle de Python, con una fraccion de los puntos.
    """
    if len(pts) < 64:
        return pts
    x, y = pts[:, 0], pts[:, 1]
    suma, resta = x + y, x - y
    extremos = np.unique([
        np.argmin(x), np.argmax(x), np.argmin(y), np.argmax(y),
        np.argmin(suma), np.argmax(suma),
        np.argmin(resta), np.argmax(resta),
    ])
    poli = pts[extremos]
    if len(poli) < 3:
        return pts
    centro = poli.mean(axis=0)
    poli = poli[np.argsort(np.arctan2(poli[:, 1] - centro[1],
                                      poli[:, 0] - centro[0]))]
    dentro = np.ones(len(pts), dtype=bool)
    for i in range(len(poli)):
        a = poli[i]
        b = poli[(i + 1) % len(poli)]
        cruz = ((b[0] - a[0]) * (pts[:, 1] - a[1])
                - (b[1] - a[1]) * (pts[:, 0] - a[0]))
        dentro &= cruz > 1e-12
        if not dentro.any():
            break
    sobreviven = pts[~dentro]
    return sobreviven if len(sobreviven) >= 3 else pts


def casco(pts):
    """Casco convexo 2D por cadena monotona."""
    pts = _adelgazar(pts)
    if len(pts) > TOPE_CASCO:
        paso = int(np.ceil(len(pts) / float(TOPE_CASCO)))
        pts = pts[::paso]
    orden = np.lexsort((pts[:, 1], pts[:, 0]))
    p = pts[orden]
    if len(p) < 3:
        return p

    def media(puntos):
        salida = []
        for q in puntos:
            while len(salida) >= 2:
                a, b = salida[-2], salida[-1]
                if (b[0] - a[0]) * (q[1] - a[1]) \
                        - (b[1] - a[1]) * (q[0] - a[0]) > 1e-12:
                    break
                salida.pop()
            salida.append(q)
        return salida

    abajo = media(list(p))
    arriba = media(list(p[::-1]))
    borde = abajo[:-1] + arriba[:-1]
    return np.asarray(borde) if len(borde) >= 3 else p


def angulo_caja_minima(pts) -> float:
    """Angulo que hay que girar para que la caja envolvente sea minima.

    Calipers giratorios sobre el casco: la caja de area minima siempre
    tiene un lado apoyado en una arista del casco, asi que basta probar
    las aristas.
    """
    h = casco(pts)
    if len(h) < 3:
        return 0.0
    d = np.roll(h, -1, axis=0) - h
    largo = np.hypot(d[:, 0], d[:, 1])
    buenas = largo > 1e-9
    if not np.any(buenas):
        return 0.0
    d = d[buenas] / largo[buenas][:, None]
    x = h @ d.T
    y = h @ np.stack([-d[:, 1], d[:, 0]], axis=1).T
    area = (x.max(axis=0) - x.min(axis=0)) * (y.max(axis=0) - y.min(axis=0))
    i = int(np.argmin(area))
    return math.atan2(d[i, 1], d[i, 0])


def orientar(uv, bucles) -> float:
    """Gira el trozo sobre su centro para que ocupe el menor rectangulo."""
    pts = uv[bucles].astype(np.float64)
    if len(pts) < 3:
        return 0.0
    angulo = angulo_caja_minima(pts)
    if abs(angulo) < 1e-6 or abs(abs(angulo) - math.pi) < 1e-6:
        return 0.0
    centro = (pts.min(axis=0) + pts.max(axis=0)) * 0.5
    c, s = math.cos(-angulo), math.sin(-angulo)
    rel = pts - centro
    uv[bucles, 0] = (rel[:, 0] * c - rel[:, 1] * s + centro[0]).astype(
        np.float32)
    uv[bucles, 1] = (rel[:, 0] * s + rel[:, 1] * c + centro[1]).astype(
        np.float32)
    return angulo



# --------------------------------------- empaquetado por la forma real

def seleccion_caras(mesh):
    """Copia de que caras estan seleccionadas, para devolverla luego."""
    sel = np.empty(len(mesh.polygons), dtype=bool)
    mesh.polygons.foreach_get("select", sel)
    return sel


def marcar_caras(mesh, polis, datos) -> None:
    """Deja seleccionadas solo esas caras."""
    sel = np.zeros(datos['caras'], dtype=bool)
    if len(polis):
        sel[np.asarray(polis, dtype=np.int64)] = True
    mesh.polygons.foreach_set("select", sel)
    mesh.update()


def devolver_caras(mesh, sel) -> None:
    if len(sel) == len(mesh.polygons):
        mesh.polygons.foreach_set("select", sel)
        mesh.update()


def margen_seguro(texeles, lado, islas) -> float:
    """Margen en fraccion de UV, acotado para que no reviente el atlas.

    pack_islands con margin_method='FRACTION' deja exactamente esa
    fraccion de aire por lado, que es la unica de las tres formas de
    pedir margen que se puede traducir a texeles. Pero no avisa cuando
    te pasas: con margenes grandes y muchas islas devuelve FINISHED
    habiendo mandado las UV fuera del cuadrado 0..1. El tope es lo que
    cabe repartiendo el atlas entre las islas.
    """
    pedido = max(0.0, float(texeles)) / max(1.0, float(lado))
    tope = 0.25 / max(1.0, math.sqrt(max(1, int(islas))))
    return min(pedido, tope)


def empaquetar_por_forma(context, objetos, forma='CONCAVE', margen=0.004,
                         uniforme=True, girar=True) -> str:
    """Empaqueta con el packer de Blender, que va por la forma real.

    El propio no sabe mas que de cajas envolventes, y una isla en L deja
    vacio todo lo que le sobra dentro de su caja. Este mira el contorno,
    asi que una isla se puede meter en el hueco de otra.

    Solo toca las caras que vengan seleccionadas: las de los materiales
    de un solo color ya estan en su celda y no deben moverse de ahi.
    Devuelve "" si fue bien, o el motivo del fallo.
    """
    ajustes_escena = context.scene.tool_settings
    sync = ajustes_escena.use_uv_select_sync
    modo_sel = tuple(ajustes_escena.mesh_select_mode)
    seleccion = [o for o in context.view_layer.objects if o.select_get()]
    activo = context.view_layer.objects.active
    en_edicion = False
    try:
        ajustes_escena.use_uv_select_sync = True
        ajustes_escena.mesh_select_mode = (False, False, True)
        for obj in context.view_layer.objects:
            obj.select_set(obj in objetos)
        context.view_layer.objects.active = objetos[0]
        bpy.ops.object.mode_set(mode='EDIT')
        en_edicion = True
        if uniforme:
            bpy.ops.uv.average_islands_scale()
        bpy.ops.uv.pack_islands(shape_method=forma, rotate=girar,
                                margin=margen, margin_method='FRACTION',
                                scale=True, merge_overlap=False)
        return ""
    except RuntimeError as ex:
        return str(ex)
    finally:
        if en_edicion:
            try:
                bpy.ops.object.mode_set(mode='OBJECT')
            except RuntimeError:
                pass
        ajustes_escena.use_uv_select_sync = sync
        ajustes_escena.mesh_select_mode = modo_sel
        for obj in context.view_layer.objects:
            obj.select_set(obj in seleccion)
        if activo is not None:
            try:
                context.view_layer.objects.active = activo
            except ReferenceError:
                pass


def encoger(uv, bucles, fx, fy) -> None:
    """Aplasta las UV para dejar sitio a la franja de colores planos."""
    if not len(bucles):
        return
    uv[bucles, 0] *= fx
    uv[bucles, 1] *= fy


# ----------------------------------------------------------- colocacion

def colocar(uv, bucles, medidas, caja, ancho, alto, margen) -> None:
    """Mete el trozo en su hueco del atlas. caja = (x, y, w, h, girado)."""
    x, y, w, h, girado = caja
    ex = max(medidas['x1'] - medidas['x0'], 1e-9)
    ey = max(medidas['y1'] - medidas['y0'], 1e-9)
    u = uv[bucles, 0] - medidas['x0']
    v = uv[bucles, 1] - medidas['y0']
    if girado:
        nu = (x + margen + v * (w / ey)) / float(ancho)
        nv = (y + margen + u * (h / ex)) / float(alto)
    else:
        nu = (x + margen + u * (w / ex)) / float(ancho)
        nv = (y + margen + v * (h / ey)) / float(alto)
    uv[bucles, 0] = nu
    uv[bucles, 1] = nv


ESQUINAS = ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0))


def colocar_plano(uv, datos, polis, celda, ancho, alto, aire=0.0) -> None:
    """Manda las caras de un material plano a su celda de color.

    Las esquinas van rotando por el cuadrado en vez de amontonarse en un
    punto: asi la cara no queda con area UV cero, que es algo que a los
    generadores de tangentes no les sienta bien.

    El cuadradito se queda en el centro de la celda, no pegado al borde.
    Toda la celda lleva el mismo color, asi que ese aire alrededor es
    justo lo que hace falta para que los mipmaps bajos no traigan el
    color del material vecino.
    """
    cx, cy, lado = celda
    if aire <= 0.0:
        aire = lado * 0.3
    # El cuadradito tiene que caber dentro de la celda pase lo que pase:
    # si se sale, la cara acaba muestreando el color del material vecino.
    aire = max(0.0, min(aire, (lado - 1.0) * 0.5))
    dentro = max(lado - 2.0 * aire, 1.0)
    polis = np.asarray(polis, dtype=np.int64)
    if not len(polis):
        return
    bucles = bucles_de(datos, polis)
    total = datos['total'][polis]
    dentro_cara = np.arange(len(bucles), dtype=np.int64)
    saltos = np.concatenate(([0], np.cumsum(total)[:-1]))
    dentro_cara -= np.repeat(saltos, total)
    esquina = np.asarray(ESQUINAS, dtype=np.float64)[dentro_cara % 4]
    uv[bucles, 0] = (cx + aire + esquina[:, 0] * dentro) / float(ancho)
    uv[bucles, 1] = (cy + aire + esquina[:, 1] * dentro) / float(alto)
