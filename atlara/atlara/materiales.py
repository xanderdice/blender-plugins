# SPDX-License-Identifier: GPL-3.0-or-later
"""Lectura y preparacion de los materiales de origen.

Dos trabajos:

  1. Mirar el arbol de nodos y decir que canales usa cada material y si
     es *plano* (solo colores fijos, ninguna textura ni nodo procedural).
     Los planos no se hornean: se les reserva una celda diminuta en el
     atlas y se rellena con su color exacto.

  2. Fabricar copias del material cableadas para hornear un canal
     concreto. El truco es siempre el mismo: se coge lo que alimenta a
     esa entrada del BSDF y se enchufa a un nodo Emission conectado a la
     salida. Horneando EMIT sale el valor crudo, sin luces ni sombras,
     igual para el color base que para el metalico o la rugosidad.
"""

from __future__ import annotations

import bpy

CANALES = ('BASE', 'METAL', 'RUGOSIDAD', 'NORMAL', 'EMISION', 'ALFA')

NOMBRE_CANAL = {
    'BASE': "Color base",
    'METAL': "Metalico",
    'RUGOSIDAD': "Rugosidad",
    'NORMAL': "Normal",
    'EMISION': "Emision",
    'ALFA': "Alfa",
    'AO': "Oclusion",
}

# Nombres de entrada por tipo de shader. Se prueban en orden porque
# Blender los ha ido renombrando entre versiones.
ENTRADAS = {
    'BSDF_PRINCIPLED': {
        'BASE': ("Base Color",),
        'METAL': ("Metallic",),
        'RUGOSIDAD': ("Roughness",),
        'NORMAL': ("Normal",),
        'EMISION': ("Emission Color", "Emission"),
        'ALFA': ("Alpha",),
        'FUERZA': ("Emission Strength",),
    },
    'BSDF_DIFFUSE': {
        'BASE': ("Color",), 'RUGOSIDAD': ("Roughness",), 'NORMAL': ("Normal",),
    },
    'BSDF_GLOSSY': {
        'BASE': ("Color",), 'RUGOSIDAD': ("Roughness",), 'NORMAL': ("Normal",),
    },
    'BSDF_ANISOTROPIC': {
        'BASE': ("Color",), 'RUGOSIDAD': ("Roughness",), 'NORMAL': ("Normal",),
    },
    'BSDF_GLASS': {
        'BASE': ("Color",), 'RUGOSIDAD': ("Roughness",), 'NORMAL': ("Normal",),
    },
    'BSDF_REFRACTION': {
        'BASE': ("Color",), 'RUGOSIDAD': ("Roughness",), 'NORMAL': ("Normal",),
    },
    'BSDF_TRANSLUCENT': {'BASE': ("Color",), 'NORMAL': ("Normal",)},
    'BSDF_TRANSPARENT': {'BASE': ("Color",)},
    'BSDF_TOON': {'BASE': ("Color",), 'NORMAL': ("Normal",)},
    'BSDF_SHEEN': {'BASE': ("Color",), 'NORMAL': ("Normal",)},
    'SUBSURFACE_SCATTERING': {'BASE': ("Color",), 'NORMAL': ("Normal",)},
    'EMISSION': {'EMISION': ("Color",), 'FUERZA': ("Strength",)},
    'BACKGROUND': {'EMISION': ("Color",), 'FUERZA': ("Strength",)},
    # Muchos assets traen el Principled metido en un grupo de nodos. No
    # se puede mirar dentro, pero las entradas del grupo si estan en el
    # arbol de fuera, asi que se buscan por nombre.
    'GROUP': {
        'BASE': ("Base Color", "Color", "Albedo", "Diffuse Color",
                 "BaseColor", "Base"),
        'METAL': ("Metallic", "Metalness", "Metal"),
        'RUGOSIDAD': ("Roughness", "Rough"),
        'NORMAL': ("Normal", "Normal Map", "Bump"),
        'EMISION': ("Emission Color", "Emission", "Emissive"),
        'ALFA': ("Alpha", "Opacity"),
        'FUERZA': ("Emission Strength",),
    },
}

MEZCLADORES = ('MIX_SHADER', 'ADD_SHADER')

# Valores cuando el material no dice nada.
POR_DEFECTO = {
    'BASE': (0.8, 0.8, 0.8, 1.0),
    'METAL': (0.0, 0.0, 0.0, 1.0),
    'RUGOSIDAD': (0.5, 0.5, 0.5, 1.0),
    'EMISION': (0.0, 0.0, 0.0, 1.0),
    'ALFA': (1.0, 1.0, 1.0, 1.0),
    'NORMAL': (0.5, 0.5, 1.0, 1.0),
}

CONSTANTES = ('RGB', 'VALUE')

MARCA = "ATLARA_TMP"


# --------------------------------------------------------------- lectura

def salida_de(arbol):
    activa = [n for n in arbol.nodes
              if n.type == 'OUTPUT_MATERIAL' and n.is_active_output]
    if activa:
        return activa[0]
    todas = [n for n in arbol.nodes if n.type == 'OUTPUT_MATERIAL']
    return todas[0] if todas else None


def _ramas_de_mezcla(nodo):
    """Las entradas de un Mix Shader, la que manda primero.

    Con Fac a 1 manda la segunda rama, con Fac a 0 la primera. Coger
    siempre la primera, como se hacia antes, pintaba de rojo un material
    que en pantalla era azul.
    """
    if nodo.type != 'MIX_SHADER':
        return [e for e in nodo.inputs if e.is_linked]
    sombras = [e for e in nodo.inputs if e.type == 'SHADER']
    if len(sombras) < 2:
        return [e for e in sombras if e.is_linked]
    fac = nodo.inputs[0]
    if not fac.is_linked and float(fac.default_value) >= 0.5:
        sombras = [sombras[1], sombras[0]]
    return [e for e in sombras if e.is_linked]


def _saltar(nodo, visitados=None, aviso=None):
    """Atraviesa reroutes y mezcladores hasta dar con un shader conocido."""
    if nodo is None:
        return None
    visitados = visitados if visitados is not None else set()
    if id(nodo) in visitados:
        return None
    visitados.add(id(nodo))
    if nodo.type in ENTRADAS:
        return nodo
    if nodo.type == 'REROUTE':
        for entrada in nodo.inputs:
            if entrada.is_linked:
                hallado = _saltar(entrada.links[0].from_node, visitados,
                                  aviso)
                if hallado is not None:
                    return hallado
    elif nodo.type in MEZCLADORES:
        if aviso is not None:
            aviso.add(nodo.type)
        for entrada in _ramas_de_mezcla(nodo):
            hallado = _saltar(entrada.links[0].from_node, visitados, aviso)
            if hallado is not None:
                return hallado
    return None


def shader_de_arbol(arbol, aviso=None):
    """El nodo shader que manda, o None si el material no se entiende."""
    if arbol is None:
        return None
    salida = salida_de(arbol)
    if salida is not None:
        entrada = salida.inputs.get("Surface")
        if entrada is not None and entrada.is_linked:
            nodo = _saltar(entrada.links[0].from_node, aviso=aviso)
            if nodo is not None and _sirve(nodo):
                return nodo
    # Setups raros (grupos de nodos, cables a medias): vale el primero.
    for tipo in ('BSDF_PRINCIPLED', 'EMISSION', 'BSDF_DIFFUSE'):
        for nodo in arbol.nodes:
            if nodo.type == tipo:
                return nodo
    return None


def arbol_de(mat):
    """El arbol de nodos del material, o None si no tiene.

    A proposito no se mira `use_nodes`: Blender lo da por deprecado y
    desde 4.2 todo material que llega a Cycles pasa por nodos.
    """
    if mat is None:
        return None
    return getattr(mat, "node_tree", None)


def _sirve(nodo) -> bool:
    """Un grupo solo vale si expone alguna entrada que reconozcamos."""
    if nodo.type != 'GROUP':
        return True
    return entrada_de(nodo, 'BASE') is not None


def shader_de(mat, aviso=None):
    return shader_de_arbol(arbol_de(mat), aviso)


def entrada_de(shader, canal):
    if shader is None:
        return None
    for nombre in ENTRADAS.get(shader.type, {}).get(canal, ()):
        socket = shader.inputs.get(nombre)
        if socket is not None:
            return socket
    return None


def _origen(socket):
    """Sigue el enlace saltando reroutes. Devuelve el socket de salida."""
    if socket is None or not socket.is_linked:
        return None
    enlace = socket.links[0]
    nodo, salida = enlace.from_node, enlace.from_socket
    vueltas = 0
    while nodo.type == 'REROUTE' and vueltas < 32:
        entrada = nodo.inputs[0]
        if not entrada.is_linked:
            return None
        enlace = entrada.links[0]
        nodo, salida = enlace.from_node, enlace.from_socket
        vueltas += 1
    return salida


def _a_color(valor):
    try:
        n = len(valor)
    except TypeError:
        return (float(valor), float(valor), float(valor), 1.0)
    if n >= 4:
        return tuple(float(v) for v in valor[:4])
    if n == 3:
        return (float(valor[0]), float(valor[1]), float(valor[2]), 1.0)
    v = float(valor[0])
    return (v, v, v, 1.0)


def constante(socket):
    """(es_constante, color rgba). Sigue nodos RGB y Valor."""
    if socket is None:
        return False, None
    salida = _origen(socket)
    if salida is None:
        return True, _a_color(socket.default_value)
    if salida.node.type in CONSTANTES:
        return True, _a_color(salida.node.outputs[0].default_value)
    return False, None


def imagenes_de(mat) -> set:
    arbol = arbol_de(mat)
    if arbol is None:
        return set()
    return {n.image for n in arbol.nodes
            if n.type == 'TEX_IMAGE' and n.image is not None}


def respaldo_de(mat):
    """El color con el que tirar cuando el shader no se entiende.

    El del visor (`diffuse_color`) no es una invencion: los importadores
    de glTF, FBX y OBJ lo rellenan con el color real del material, asi
    que se parece mucho mas a la verdad que un gris de fabrica.
    """
    if mat is None:
        return POR_DEFECTO['BASE']
    return _a_color(getattr(mat, "diffuse_color", POR_DEFECTO['BASE']))


def leer(mat, canales=CANALES) -> dict:
    """Radiografia del material: canales usados, colores fijos y texturas."""
    mezclas = set()
    shader = shader_de(mat, mezclas)
    datos = {
        'nombre': mat.name if mat is not None else "",
        'shader': shader.type if shader is not None else "",
        'entendido': shader is not None,
        'plano': True,
        'usa': set(),
        'valores': dict(POR_DEFECTO),
        'imagenes': imagenes_de(mat),
        'fuerza': 1.0,
        'mezclado': bool(mezclas),
    }

    if mat is None:
        return datos

    if shader is None:
        # No se entiende: se conserva al menos el color que ensena el
        # visor, y se avisa. Si ademas lleva texturas, se hornea para no
        # perder lo que se pueda.
        datos['valores']['BASE'] = respaldo_de(mat)
        datos['valores']['METAL'] = _a_color(getattr(mat, "metallic", 0.0))
        datos['valores']['RUGOSIDAD'] = _a_color(
            getattr(mat, "roughness", 0.5))
        if datos['valores']['METAL'][0] > 1e-4:
            datos['usa'].add('METAL')
        if datos['imagenes']:
            datos['plano'] = False
            datos['usa'].add('BASE')
        return datos

    for canal in canales:
        if canal == 'NORMAL':
            # El socket Normal sin conectar vale (0,0,0), que descodifica
            # a (-1,-1,-1). La normal neutra es (0.5,0.5,1) y ya esta en
            # POR_DEFECTO: aqui no se toca. Se mira mas abajo.
            continue
        socket = entrada_de(shader, canal)
        if socket is None:
            continue
        fijo, color = constante(socket)
        if not fijo:
            datos['plano'] = False
            datos['usa'].add(canal)
            continue
        datos['valores'][canal] = color
        if canal == 'METAL' and color[0] > 1e-4:
            datos['usa'].add(canal)
        elif canal == 'ALFA' and color[0] < 1.0 - 1e-4:
            datos['usa'].add(canal)
        elif canal == 'RUGOSIDAD' and abs(color[0] - 0.5) > 1e-4:
            datos['usa'].add(canal)

    fuerza = entrada_de(shader, 'FUERZA')
    fijo, valor = constante(fuerza)
    if fuerza is not None and not fijo:
        datos['plano'] = False
        datos['usa'].add('EMISION')
    elif valor is not None:
        datos['fuerza'] = float(valor[0])

    color = datos['valores'].get('EMISION') or (0.0, 0.0, 0.0, 1.0)
    f = datos['fuerza']
    datos['valores']['EMISION'] = (color[0] * f, color[1] * f,
                                   color[2] * f, 1.0)
    if max(datos['valores']['EMISION'][:3]) > 1e-4:
        datos['usa'].add('EMISION')

    normal = entrada_de(shader, 'NORMAL')
    if normal is not None and normal.is_linked:
        datos['plano'] = False
        datos['usa'].add('NORMAL')

    if datos['imagenes']:
        datos['plano'] = False
    return datos


def texeles_de(mat) -> float:
    return float(sum(i.size[0] * i.size[1] for i in imagenes_de(mat)
                     if i.size[0] and i.size[1]))


def lado_mayor(mat, minimo=64) -> int:
    lados = [max(i.size) for i in imagenes_de(mat) if max(i.size) > 0]
    return max(lados) if lados else minimo


# -------------------------------------------------------------- horneado

def _limpiar_marcados(arbol) -> None:
    for nodo in [n for n in arbol.nodes if n.name.startswith(MARCA)]:
        arbol.nodes.remove(nodo)


def anclar_uv(arbol, nombre_uv) -> None:
    """Obliga a las texturas a leerse con el UV original.

    Sin esto usarian el UV activo, que durante el horneado es el del
    atlas, y saldria papilla.
    """
    if not nombre_uv:
        return

    def mapa_en(cerca):
        nodo = arbol.nodes.new('ShaderNodeUVMap')
        nodo.name = MARCA + "_uv"
        nodo.uv_map = nombre_uv
        nodo.location = (cerca.location.x - 260.0, cerca.location.y - 120.0)
        return nodo

    for nodo in list(arbol.nodes):
        if nodo.type in ('TEX_IMAGE', 'TEX_ENVIRONMENT'):
            vector = nodo.inputs.get("Vector")
            if vector is not None and not vector.is_linked:
                arbol.links.new(mapa_en(nodo).outputs["UV"], vector)
        elif nodo.type == 'TEX_COORD':
            salida = nodo.outputs.get("UV")
            if salida is not None and salida.is_linked:
                nuevo = mapa_en(nodo).outputs["UV"]
                for enlace in list(salida.links):
                    destino = enlace.to_socket
                    arbol.links.remove(enlace)
                    arbol.links.new(nuevo, destino)


def nodo_imagen(arbol, imagen):
    """Deja la imagen destino como nodo activo, que es donde hornea."""
    for nodo in arbol.nodes:
        nodo.select = False
    nodo = arbol.nodes.new('ShaderNodeTexImage')
    nodo.name = MARCA + "_destino"
    nodo.image = imagen
    nodo.location = (-600.0, 500.0)
    nodo.select = True
    arbol.nodes.active = nodo
    return nodo


def cablear_emision(arbol, canal, respaldo=None) -> None:
    """Manda el canal pedido a un Emission conectado a la salida."""
    salida = salida_de(arbol)
    if salida is None:
        salida = arbol.nodes.new('ShaderNodeOutputMaterial')
        salida.name = MARCA + "_salida"
    shader = shader_de_arbol(arbol)

    emision = arbol.nodes.new('ShaderNodeEmission')
    emision.name = MARCA + "_emision"
    emision.location = (salida.location.x - 240.0, salida.location.y - 280.0)
    emision.inputs["Strength"].default_value = 1.0

    socket = entrada_de(shader, canal)
    fuente = _origen(socket)
    if fuente is not None:
        arbol.links.new(fuente, emision.inputs["Color"])
    elif socket is not None:
        emision.inputs["Color"].default_value = _a_color(socket.default_value)
    elif canal == 'BASE' and respaldo is not None:
        emision.inputs["Color"].default_value = respaldo
    else:
        emision.inputs["Color"].default_value = POR_DEFECTO.get(
            canal, (0.0, 0.0, 0.0, 1.0))

    if canal == 'EMISION':
        fuerza = entrada_de(shader, 'FUERZA')
        origen_fuerza = _origen(fuerza)
        if origen_fuerza is not None:
            arbol.links.new(origen_fuerza, emision.inputs["Strength"])
        elif fuerza is not None:
            emision.inputs["Strength"].default_value = float(
                fuerza.default_value)

    entrada = salida.inputs.get("Surface")
    for enlace in list(entrada.links):
        arbol.links.remove(enlace)
    arbol.links.new(emision.outputs["Emission"], entrada)


def copia_para(mat, canal, nombre_uv, imagen):
    """Copia temporal del material, lista para hornear `canal`."""
    if mat is None:
        copia = bpy.data.materials.new(MARCA + "_vacio")
    else:
        copia = mat.copy()
        copia.name = MARCA + "_" + mat.name
    if copia.node_tree is None:
        copia.use_nodes = True
    copia.use_fake_user = False
    arbol = copia.node_tree
    _limpiar_marcados(arbol)
    anclar_uv(arbol, nombre_uv)
    if canal != 'NORMAL':
        cablear_emision(arbol, canal, respaldo_de(mat))
    nodo_imagen(arbol, imagen)
    return copia


def tirar(materiales) -> None:
    for mat in materiales:
        if mat is None:
            continue
        try:
            if mat.name.startswith(MARCA):
                bpy.data.materials.remove(mat, do_unlink=True)
        except (ReferenceError, RuntimeError):
            pass
