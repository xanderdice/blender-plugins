# SPDX-License-Identifier: GPL-3.0-or-later
"""Prueba de Atlara contra un Blender real.

    blender --background --factory-startup --python pruebas/prueba.py

Monta una escena como la que se encuentra uno al importar assets: un
objeto con dos materiales (uno con textura y otro que es solo un color),
otro objeto con un material plano, y una luz en medio de la seleccion.
Despues comprueba lo que de verdad importa: que queda un unico material,
que los objetos siguen separados y en 0,0,0, que las UV caben en el
cuadrado y que los colores originales han llegado al atlas.
"""

from __future__ import annotations

import ast
import glob
import os
import sys

import bpy
import numpy as np

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)

import atlara
from atlara import materiales, nucleo, proceso, uvs

FALLOS = []
PRUEBAS = 0

VERDE = (0.0, 1.0, 0.0)
AZUL = (0.0, 0.0, 1.0)
ROJO = (1.0, 0.0, 0.0)


def comprobar(condicion, mensaje):
    global PRUEBAS
    PRUEBAS += 1
    if condicion:
        print("  ok   %s" % mensaje)
    else:
        print("  FALLO %s" % mensaje)
        FALLOS.append(mensaje)


def titulo(texto):
    print("\n== %s %s" % (texto, "=" * max(0, 60 - len(texto))))


# --------------------------------------------------------------- escena

def limpiar():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def material_plano(nombre, color, metalico=0.0, rugosidad=0.5):
    mat = bpy.data.materials.new(nombre)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (
        color[0], color[1], color[2], 1.0)
    bsdf.inputs["Metallic"].default_value = metalico
    bsdf.inputs["Roughness"].default_value = rugosidad
    return mat


def imagen_lisa(nombre, color, lado=64, datos=False):
    img = bpy.data.images.new(nombre, lado, lado, is_data=datos)
    if datos:
        img.colorspace_settings.name = 'Non-Color'
    pix = np.zeros((lado, lado, 4), dtype=np.float32)
    pix[:, :, 0] = color[0]
    pix[:, :, 1] = color[1]
    pix[:, :, 2] = color[2]
    pix[:, :, 3] = 1.0
    img.pixels.foreach_set(pix.reshape(-1))
    return img


def material_textura(nombre, color, lado=64, normal=False):
    mat = bpy.data.materials.new(nombre)
    mat.use_nodes = True
    arbol = mat.node_tree
    bsdf = arbol.nodes["Principled BSDF"]
    tex = arbol.nodes.new('ShaderNodeTexImage')
    tex.image = imagen_lisa(nombre + "_src", color, lado)
    arbol.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    if normal:
        nrm = arbol.nodes.new('ShaderNodeTexImage')
        nrm.image = imagen_lisa(nombre + "_nrm", (0.5, 0.5, 1.0), lado,
                                datos=True)
        mapa = arbol.nodes.new('ShaderNodeNormalMap')
        arbol.links.new(nrm.outputs["Color"], mapa.inputs["Color"])
        arbol.links.new(mapa.outputs["Normal"], bsdf.inputs["Normal"])
    return mat


def cubo(nombre, sitio, escala=1.0):
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=sitio)
    obj = bpy.context.active_object
    obj.name = nombre
    obj.scale = (escala, escala, escala)
    obj.rotation_euler = (0.3, 0.0, 0.7)
    return obj


def montar():
    limpiar()
    uno = cubo("Cofre", (3.0, 0.0, 0.0), 2.0)
    uno.data.materials.append(material_textura("Verde", VERDE, normal=True))
    uno.data.materials.append(material_plano("Azul", AZUL, metalico=1.0))
    for i, poligono in enumerate(uno.data.polygons):
        poligono.material_index = 1 if i < 3 else 0

    dos = cubo("Barril", (-3.0, 1.5, 0.5), 1.0)
    dos.data.materials.append(material_plano("Rojo", ROJO, rugosidad=0.2))

    luz = bpy.data.objects.new("Farol", bpy.data.lights.new("Farol", 'POINT'))
    bpy.context.scene.collection.objects.link(luz)
    luz.location = (0.0, 0.0, 4.0)
    return uno, dos, luz


def seleccionar(objetos):
    for obj in bpy.context.scene.objects:
        obj.select_set(False)
    for obj in objetos:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = objetos[0]


def pixeles(img):
    ancho, alto = img.size
    datos = np.empty(ancho * alto * 4, dtype=np.float32)
    img.pixels.foreach_get(datos)
    return datos.reshape(alto, ancho, 4)


def cuantos_como(img, color, tolerancia=0.08):
    datos = pixeles(img)[:, :, :3]
    cerca = np.abs(datos - np.asarray(color, dtype=np.float32)) < tolerancia
    return int(np.count_nonzero(np.all(cerca, axis=-1)))


def muestrear(img, uv):
    """El pixel del atlas que le toca a esa coordenada UV."""
    datos = pixeles(img)
    alto, ancho = datos.shape[0], datos.shape[1]
    x = min(ancho - 1, max(0, int(uv[0] * ancho)))
    y = min(alto - 1, max(0, int(uv[1] * alto)))
    return datos[y, x]


def centro_uv(obj, poligono):
    uv = uv_de(obj)
    cara = obj.data.polygons[poligono]
    trozo = uv[cara.loop_start:cara.loop_start + cara.loop_total]
    return trozo.mean(axis=0)


def uv_de(obj):
    capa = obj.data.uv_layers.active
    datos = np.empty(len(obj.data.loops) * 2, dtype=np.float32)
    capa.data.foreach_get("uv", datos)
    return datos.reshape(-1, 2)


# ---------------------------------------------------------------- codigo

def prueba_fuente():
    titulo("Codigo")
    ficheros = sorted(glob.glob(os.path.join(RAIZ, "atlara", "*.py")))
    comprobar(len(ficheros) >= 8, "hay %d modulos" % len(ficheros))
    for ruta in ficheros:
        with open(ruta, encoding="utf-8") as fh:
            texto = fh.read()
        try:
            ast.parse(texto)
            bien = True
        except SyntaxError as ex:
            bien = False
            print("      %s" % ex)
        comprobar(bien, "%s compila" % os.path.basename(ruta))
        largas = [n for n, linea in enumerate(texto.splitlines(), 1)
                  if len(linea) > 79]
        comprobar(not largas, "%s sin lineas largas %s"
                  % (os.path.basename(ruta), largas[:3] if largas else ""))


def prueba_empaquetador():
    titulo("Empaquetador")
    col = nucleo.empaquetar([(10, 10), (10, 10), (10, 10), (10, 10)], 20, 20)
    comprobar(col is not None and len(col) == 4, "cuatro cuadrados en 20x20")
    ocupados = set()
    for x, y, _girado in col:
        ocupados.add((x, y))
    comprobar(len(ocupados) == 4, "sin solaparse: %s" % sorted(ocupados))

    comprobar(nucleo.empaquetar([(30, 30)], 20, 20) is None,
              "avisa cuando no cabe")

    col = nucleo.empaquetar([(20, 5)], 10, 30, rotar=True)
    comprobar(col is not None and col[0][2] is True, "gira si hace falta")

    hecho = nucleo.ajustar([(1.0, 1.0)] * 4, 64, 64, margen=2)
    comprobar(hecho is not None, "la biseccion encuentra escala")
    escala, tam, _col = hecho
    comprobar(28 <= tam[0][0] <= 32,
              "cuatro trozos iguales en 64px dan ~32 (%d)" % tam[0][0])

    franja, celdas = nucleo.franja_planos(5, 16, 64, 64)
    comprobar(franja == 32 and len(celdas) == 5,
              "5 celdas de 16 en 64px ocupan 2 filas (%d)" % franja)
    comprobar(all(0 <= c[0] and c[1] + c[2] <= 64 for c in celdas),
              "las celdas caben dentro")

    reparto = nucleo.repartir([(1.0, 1.0)] * 3, 4, 256, 256, 4, 16)
    comprobar(reparto is not None and len(reparto['celdas']) == 4,
              "reparto completo con planos y texturizados")
    comprobar(0.0 < reparto['ocupacion'] <= 1.0,
              "ocupacion %.2f" % reparto['ocupacion'])


def prueba_horizonte():
    titulo("Empaquetado por horizonte")
    import random
    rnd = random.Random(11)
    tam = []
    for _ in range(250):
        w = int(rnd.lognormvariate(3.2, 0.7)) + 4
        h = int(rnd.lognormvariate(3.2, 0.7)) + 4
        tam.append((min(w, 200), min(h, 200)))

    col = nucleo._por_horizonte(tam, 1024, 1024, True)
    comprobar(col is not None, "coloca 250 rectangulos en 1024x1024")
    if col is None:
        return

    cajas = []
    for (x, y, girado), (w, h) in zip(col, tam):
        if girado:
            w, h = h, w
        cajas.append((x, y, x + w, y + h))

    fuera = [c for c in cajas
             if c[0] < 0 or c[1] < 0 or c[2] > 1024 or c[3] > 1024]
    comprobar(not fuera, "ninguno se sale del atlas (%d fuera)" % len(fuera))

    solapes = 0
    for i in range(len(cajas)):
        ax0, ay0, ax1, ay1 = cajas[i]
        for j in range(i + 1, len(cajas)):
            bx0, by0, bx1, by1 = cajas[j]
            if ax0 < bx1 and bx0 < ax1 and ay0 < by1 and by0 < ay1:
                solapes += 1
    comprobar(solapes == 0, "ningun par se pisa (%d solapes)" % solapes)

    usado = sum((c[2] - c[0]) * (c[3] - c[1]) for c in cajas)
    tope = max(c[3] for c in cajas)
    rendimiento = usado / float(1024 * tope)
    comprobar(rendimiento > 0.75,
              "aprovecha el %d%% de la franja que ocupa" % (rendimiento * 100))

    comprobar(nucleo._por_horizonte([(2000, 10)], 1024, 1024, False) is None,
              "avisa cuando un rectangulo no cabe ni girado")
    uno = nucleo._por_horizonte([(2000, 10)], 1024, 3000, True)
    comprobar(uno is not None and uno[0][2] is True,
              "gira el que solo cabe de lado")

    grande = [(60, 60)] * 700
    col = nucleo.empaquetar(grande, 2048, 2048, True)
    comprobar(col is not None, "700 rectangulos de 60 en un atlas de 2048")
    if col:
        sitios = set((x, y) for x, y, _g in col)
        comprobar(len(sitios) == 700, "y los 700 caen en sitios distintos")

    comprobar(nucleo.empaquetar([(1000, 1000)] * 5, 2048, 2048) is None,
              "el descarte por area corta antes de empezar")


def prueba_lectura():
    titulo("Lectura de materiales")
    limpiar()
    plano = material_plano("P", AZUL, metalico=1.0)
    ficha = materiales.leer(plano)
    comprobar(ficha['plano'], "un color liso se reconoce como plano")
    comprobar('METAL' in ficha['usa'], "detecta el metalico a 1")
    comprobar(abs(ficha['valores']['BASE'][2] - 1.0) < 1e-5,
              "guarda el azul exacto")

    con = material_textura("T", VERDE)
    ficha = materiales.leer(con)
    comprobar(not ficha['plano'], "con textura no es plano")
    comprobar(len(ficha['imagenes']) == 1, "encuentra la imagen")

    vacio = materiales.leer(None)
    comprobar(vacio['plano'], "sin material tambien es plano")

    raro = bpy.data.materials.new("Raro")
    raro.use_nodes = True
    raro.node_tree.nodes.clear()
    ficha = materiales.leer(raro)
    comprobar(not ficha['entendido'], "avisa del material que no entiende")
    comprobar(ficha['plano'],
              "y como no tiene texturas le da una celda con su color del "
              "visor en vez de hornear un gris")


def prueba_atlas_junto():
    titulo("Un atlas para toda la seleccion")
    uno, dos, luz = montar()
    seleccionar([uno, dos, luz])

    ajustes = bpy.context.scene.atlara
    ajustes.modo = 'TODO'
    ajustes.resolucion = '256'
    ajustes.margen = 4
    ajustes.usar_normal = True
    ajustes.usar_metal = True
    ajustes.usar_rugosidad = True
    ajustes.prefijo = "Prueba"

    resultado = bpy.ops.atlara.atlas()
    comprobar('FINISHED' in resultado, "el operador termina")

    comprobar(len(uno.data.materials) == 1 and len(dos.data.materials) == 1,
              "cada objeto se queda con un material")
    comprobar(uno.data.materials[0] is dos.data.materials[0],
              "y es el mismo para los dos")
    comprobar(uno.name in bpy.data.objects and dos.name in bpy.data.objects,
              "los objetos siguen sin unirse")
    comprobar(luz.type == 'LIGHT' and not hasattr(luz.data, "materials"),
              "la luz se queda como estaba")

    for obj in (uno, dos):
        comprobar(max(abs(v) for v in obj.location) < 1e-6,
                  "%s esta en 0,0,0" % obj.name)
        comprobar(all(abs(s - 1.0) < 1e-5 for s in obj.scale),
                  "%s con la escala aplicada" % obj.name)
        capas = [c.name for c in obj.data.uv_layers]
        comprobar(capas[0] == "Atlas",
                  "%s tiene el atlas como primer canal UV: %s"
                  % (obj.name, capas))
        comprobar(len(capas) == 2,
                  "%s conserva ademas su UV original: %s" % (obj.name, capas))
        uv = uv_de(obj)
        comprobar(uv.min() >= -1e-4 and uv.max() <= 1.0 + 1e-4,
                  "%s con las UV dentro del cuadrado (%.3f..%.3f)"
                  % (obj.name, uv.min(), uv.max()))

    mat = uno.data.materials[0]
    nodos = [n for n in mat.node_tree.nodes if n.type == 'TEX_IMAGE']
    comprobar(len(nodos) >= 2, "el material lleva %d texturas" % len(nodos))

    base = bpy.data.images.get("Prueba_BaseColor")
    comprobar(base is not None, "existe el mapa de color base")
    if base is not None:
        comprobar(cuantos_como(base, VERDE) > 20,
                  "el verde de la textura llego al atlas (%d px)"
                  % cuantos_como(base, VERDE))
        comprobar(cuantos_como(base, AZUL) > 20,
                  "el azul del material plano llego al atlas (%d px)"
                  % cuantos_como(base, AZUL))
        comprobar(cuantos_como(base, ROJO) > 20,
                  "el rojo del otro objeto llego al atlas (%d px)"
                  % cuantos_como(base, ROJO))

    if base is not None:
        azul = muestrear(base, centro_uv(uno, 0))
        comprobar(azul[2] > 0.9 and azul[0] < 0.1,
                  "la cara del material plano cae sobre su celda azul (%s)"
                  % np.round(azul[:3], 2))
        verde = muestrear(base, centro_uv(uno, 4))
        comprobar(verde[1] > 0.9 and verde[0] < 0.1,
                  "la cara con textura cae sobre su parcela verde (%s)"
                  % np.round(verde[:3], 2))
        rojo = muestrear(base, centro_uv(dos, 0))
        comprobar(rojo[0] > 0.9 and rojo[1] < 0.1,
                  "la cara del segundo objeto cae sobre su rojo (%s)"
                  % np.round(rojo[:3], 2))

    orm = bpy.data.images.get("Prueba_ORM")
    comprobar(orm is not None, "existe el mapa ORM combinado")
    if orm is not None:
        datos = pixeles(orm)
        comprobar(float(datos[:, :, 2].max()) > 0.9,
                  "el metalico del azul esta en el canal B")
        comprobar(float(datos[:, :, 1].min()) < 0.3,
                  "la rugosidad 0.2 del rojo esta en el canal G")

    normal = bpy.data.images.get("Prueba_Normal")
    comprobar(normal is not None, "existe el mapa de normales")
    if normal is not None:
        datos = pixeles(normal)
        comprobar(float(datos[:, :, 2].max()) > 0.9,
                  "el azul del mapa de normales esta a tope")
    empaquetadas = [i for i in (base, orm, normal)
                    if i is not None and i.packed_file is not None]
    comprobar(len(empaquetadas) == 3,
              "las %d texturas van empaquetadas en el .blend"
              % len(empaquetadas))
    comprobar(not [m for m in bpy.data.materials
                   if m.name.startswith(materiales.MARCA)],
              "no quedan materiales temporales")


def prueba_atlas_por_objeto():
    titulo("Un atlas por objeto")
    uno, dos, luz = montar()
    seleccionar([uno, dos, luz])
    ajustes = bpy.context.scene.atlara
    ajustes.modo = 'OBJETO'
    ajustes.resolucion = '128'
    ajustes.prefijo = "Solo"

    resultado = bpy.ops.atlara.atlas()
    comprobar('FINISHED' in resultado, "el operador termina")
    comprobar(uno.data.materials[0] is not dos.data.materials[0],
              "cada objeto con su material")
    comprobar(bpy.data.images.get("Solo_Cofre_BaseColor") is not None,
              "el atlas del primero se llama por su objeto")
    comprobar(bpy.data.images.get("Solo_Barril_BaseColor") is not None,
              "y el del segundo tambien")


def prueba_un_objeto_muchos_materiales():
    titulo("Un objeto con varios materiales")
    limpiar()
    obj = cubo("Casa", (0.0, 0.0, 0.0), 1.0)
    for nombre, color in (("A", VERDE), ("B", AZUL), ("C", ROJO)):
        obj.data.materials.append(material_plano(nombre, color))
    for i, poligono in enumerate(obj.data.polygons):
        poligono.material_index = i % 3
    seleccionar([obj])

    ajustes = bpy.context.scene.atlara
    ajustes.modo = 'TODO'
    ajustes.resolucion = '0'
    ajustes.prefijo = "Casa"

    resultado = bpy.ops.atlara.atlas()
    comprobar('FINISHED' in resultado, "el operador termina")
    comprobar(len(obj.data.materials) == 1,
              "tres materiales se convierten en uno")
    indices = {p.material_index for p in obj.data.polygons}
    comprobar(indices == {0}, "todas las caras apuntan a la ranura 0")

    base = bpy.data.images.get("Casa_BaseColor")
    comprobar(base is not None, "existe el atlas")
    if base is not None:
        for nombre, color in (("verde", VERDE), ("azul", AZUL),
                              ("rojo", ROJO)):
            comprobar(cuantos_como(base, color) > 4,
                      "el %s sigue en el atlas (%d px)"
                      % (nombre, cuantos_como(base, color)))


def prueba_sin_uv():
    titulo("Malla sin UV")
    limpiar()
    malla = bpy.data.meshes.new("Pelada")
    malla.from_pydata([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)], [],
                      [(0, 1, 2, 3)])
    malla.update()
    obj = bpy.data.objects.new("Pelada", malla)
    bpy.context.scene.collection.objects.link(obj)
    obj.data.materials.append(material_plano("Gris", (0.5, 0.5, 0.5)))
    comprobar(not obj.data.uv_layers, "la malla llega sin UV")
    seleccionar([obj])

    ajustes = bpy.context.scene.atlara
    ajustes.resolucion = '128'
    ajustes.prefijo = "Pelada"
    resultado = bpy.ops.atlara.atlas()
    comprobar('FINISHED' in resultado, "se le fabrica una UV y termina")
    comprobar(len(obj.data.uv_layers) == 1, "acaba con una capa UV")


def prueba_emision_alfa_islas():
    titulo("Emision, alfa y reparto por isla")
    limpiar()
    obj = cubo("Lampara", (0.0, 0.0, 0.0), 1.0)
    cristal = material_plano("Cristal", (1.0, 1.0, 1.0))
    alfa = cristal.node_tree.nodes["Principled BSDF"]
    alfa.inputs["Alpha"].default_value = 0.25
    obj.data.materials.append(cristal)

    faro = material_textura("Faro", (1.0, 1.0, 1.0))
    bsdf = faro.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Emission Color"].default_value = (1.0, 0.0, 0.0, 1.0)
    bsdf.inputs["Emission Strength"].default_value = 1.0
    obj.data.materials.append(faro)
    for i, poligono in enumerate(obj.data.polygons):
        poligono.material_index = 0 if i < 3 else 1
    seleccionar([obj])

    ajustes = bpy.context.scene.atlara
    ajustes.modo = 'TODO'
    ajustes.resolucion = '256'
    ajustes.agrupacion = 'ISLA'
    ajustes.usar_alfa = True
    ajustes.usar_emision = True
    ajustes.prefijo = "Luz"
    try:
        resultado = bpy.ops.atlara.atlas()
    finally:
        ajustes.agrupacion = 'GRUPO'
        ajustes.usar_alfa = False
        ajustes.usar_emision = False
    comprobar('FINISHED' in resultado, "el operador termina en modo isla")

    emision = bpy.data.images.get("Luz_Emission")
    comprobar(emision is not None, "existe el mapa de emision")
    if emision is not None:
        comprobar(cuantos_como(emision, ROJO) > 20,
                  "la emision roja llego al atlas (%d px)"
                  % cuantos_como(emision, ROJO))

    base = bpy.data.images.get("Luz_BaseColor")
    comprobar(base is not None, "existe el color base")
    if base is not None:
        alfa = pixeles(base)[:, :, 3]
        comprobar(float(alfa.min()) < 0.35,
                  "el alfa 0.25 viaja en el canal A (minimo %.2f)"
                  % float(alfa.min()))
    mat = obj.data.materials[0]
    bsdf = [n for n in mat.node_tree.nodes if n.type == 'BSDF_PRINCIPLED'][0]
    comprobar(bsdf.inputs["Alpha"].is_linked,
              "el material final conecta el alfa")
    comprobar(bsdf.inputs["Emission Color"].is_linked,
              "y la emision")


def prueba_oclusion():
    titulo("Oclusion ambiental")
    limpiar()
    obj = cubo("Piedra", (0.0, 0.0, 0.0), 1.0)
    obj.data.materials.append(material_plano("Gris", (0.5, 0.5, 0.5)))
    seleccionar([obj])

    ajustes = bpy.context.scene.atlara
    ajustes.resolucion = '128'
    ajustes.usar_ao = True
    ajustes.ao_muestras = 8
    ajustes.prefijo = "Ao"
    try:
        resultado = bpy.ops.atlara.atlas()
    finally:
        ajustes.usar_ao = False
    comprobar('FINISHED' in resultado, "el operador termina con oclusion")

    orm = bpy.data.images.get("Ao_ORM")
    comprobar(orm is not None, "la oclusion va dentro del ORM")
    if orm is not None:
        rojo = pixeles(orm)[:, :, 0]
        comprobar(float(rojo.max()) > 0.5,
                  "el canal R trae la oclusion (max %.2f)" % float(rojo.max()))
    comprobar(all(not o.hide_render for o in bpy.context.scene.objects),
              "nadie se queda oculto despues de la oclusion")


def prueba_guardar_en_disco():
    titulo("Texturas en disco")
    import tempfile
    limpiar()
    obj = cubo("Caja", (0.0, 0.0, 0.0), 1.0)
    obj.data.materials.append(material_textura("Lata", VERDE))
    seleccionar([obj])

    carpeta = os.path.join(tempfile.gettempdir(), "atlara_prueba")
    ajustes = bpy.context.scene.atlara
    ajustes.resolucion = '128'
    ajustes.guardado = 'DISCO'
    ajustes.carpeta = carpeta
    ajustes.prefijo = "Disco"
    try:
        resultado = bpy.ops.atlara.atlas()
    finally:
        ajustes.guardado = 'EMPAQUETAR'
    comprobar('FINISHED' in resultado, "el operador termina")
    escritos = glob.glob(os.path.join(carpeta, "Disco_*.png"))
    comprobar(len(escritos) >= 1,
              "escribe los PNG en la carpeta (%d)" % len(escritos))
    for ruta in escritos:
        os.remove(ruta)


def prueba_geometria():
    titulo("Medidas de la malla")
    limpiar()
    obj = cubo("Metro", (0.0, 0.0, 0.0), 1.0)
    obj.rotation_euler = (0.0, 0.0, 0.0)
    obj.scale = (2.0, 2.0, 2.0)
    bpy.context.view_layer.update()
    datos = uvs.indices(obj.data)
    area = uvs.areas_mundo(obj.data, obj.matrix_world, datos)
    comprobar(abs(float(area.sum()) - 24.0) < 1e-3,
              "un cubo de lado 1 escalado x2 mide 24 m2 (%.3f)"
              % float(area.sum()))
    comprobar(len(area) == len(obj.data.polygons), "un area por cara")

    obj.rotation_euler = (0.7, 0.3, 1.1)
    bpy.context.view_layer.update()
    area2 = uvs.areas_mundo(obj.data, obj.matrix_world, datos)
    comprobar(abs(float(area2.sum()) - 24.0) < 1e-3,
              "girar no cambia el area (%.3f)" % float(area2.sum()))

    capa = uvs.capa_origen(obj.data)
    uv = uvs.leer(obj.data, capa)
    auv = uvs.areas_uv(uv, datos)
    comprobar(float(auv.sum()) > 0.0, "el area UV sale positiva")


def prueba_enderezar():
    titulo("Giro a la caja minima")
    lado = np.array([[0.0, 0.0], [1.0, 0.0], [1.0, 0.25], [0.0, 0.25]])
    ang = np.deg2rad(37.0)
    giro = np.array([[np.cos(ang), -np.sin(ang)],
                     [np.sin(ang), np.cos(ang)]])
    torcido = lado @ giro.T

    def caja(p):
        return ((p[:, 0].max() - p[:, 0].min())
                * (p[:, 1].max() - p[:, 1].min()))

    antes = caja(torcido)
    comprobar(antes > 0.4, "en diagonal la caja mide %.3f, mucho mas que "
              "el 0.25 real" % antes)

    uv = np.zeros((8, 2), dtype=np.float32)
    uv[:4] = torcido
    bucles = np.arange(4)
    uvs.orientar(uv, bucles)
    despues = caja(uv[bucles].astype(np.float64))
    comprobar(despues < antes * 0.7,
              "enderezado baja a %.3f, un %d%% menos"
              % (despues, int(100 - 100 * despues / antes)))
    comprobar(abs(despues - 0.25) < 0.02,
              "y se queda pegado al area real (%.3f)" % despues)


def prueba_texeles_y_margen():
    titulo("Resolucion y margen automaticos")
    limpiar()
    mat = material_textura("Cuatro", VERDE, lado=1024)
    arbol = mat.node_tree
    bsdf = arbol.nodes["Principled BSDF"]
    for nombre, entrada in (("nrm", "Normal"), ("met", "Metallic"),
                            ("rug", "Roughness")):
        tex = arbol.nodes.new('ShaderNodeTexImage')
        tex.image = imagen_lisa("extra_" + nombre, (0.5, 0.5, 0.5), 1024,
                                datos=True)
        if entrada == "Normal":
            mapa = arbol.nodes.new('ShaderNodeNormalMap')
            arbol.links.new(tex.outputs["Color"], mapa.inputs["Color"])
            arbol.links.new(mapa.outputs["Normal"], bsdf.inputs[entrada])
        else:
            arbol.links.new(tex.outputs["Color"], bsdf.inputs[entrada])

    fichas = {"Cuatro": materiales.leer(mat)}
    texeles = proceso.texeles_de(fichas)
    comprobar(abs(texeles - 1024.0 * 1024.0) < 1.0,
              "cuatro mapas de 1024 piden 1 megatexel, no 4 (%.2f MT)"
              % (texeles / 1e6))
    comprobar(nucleo.resolucion_sugerida(texeles) == 1024,
              "y el atlas sugerido es 1024, no 2048")

    ajustes = bpy.context.scene.atlara
    ajustes.margen_auto = True
    comprobar(proceso.margen_de(ajustes, 2048, 64) == 8,
              "2048 px con 64 trozos pide 8 de margen (%d)"
              % proceso.margen_de(ajustes, 2048, 64))
    comprobar(proceso.margen_de(ajustes, 2048, 1024) == 2,
              "con 1024 trozos baja a 2, que si no el relleno se come el "
              "atlas (%d)" % proceso.margen_de(ajustes, 2048, 1024))
    comprobar(proceso.margen_de(ajustes, 2048, 1) == 32,
              "con un solo trozo se topa en 32 (%d)"
              % proceso.margen_de(ajustes, 2048, 1))
    comprobar(proceso.margen_de(ajustes, 128, 64) == 2,
              "y nunca baja de 2 (%d)" % proceso.margen_de(ajustes, 128, 64))

    gordo = proceso.margen_de(ajustes, 2048, 4)
    fino = proceso.margen_de(ajustes, 2048, 400)
    comprobar(gordo > fino,
              "a mas trozos, menos margen por trozo (%d vs %d)"
              % (gordo, fino))

    ajustes.margen_auto = False
    ajustes.margen = 7
    comprobar(proceso.margen_de(ajustes, 2048, 64) == 7,
              "y a mano manda el usuario")
    ajustes.margen_auto = True


def prueba_reparto_automatico():
    titulo("Reparto automatico")
    uno, dos, luz = montar()
    seleccionar([uno, dos, luz])
    ajustes = bpy.context.scene.atlara
    ajustes.modo = 'TODO'
    ajustes.agrupacion = 'AUTO'
    ajustes.resolucion = '256'
    ajustes.prefijo = "Auto"
    resultado = bpy.ops.atlara.atlas()
    comprobar('FINISHED' in resultado, "el operador termina en AUTO")
    texto = ajustes.informe.resultado
    comprobar("reparto" in texto, "dice que reparto eligio: %s" % texto)
    base = bpy.data.images.get("Auto_BaseColor")
    comprobar(base is not None and cuantos_como(base, VERDE) > 20,
              "el verde sigue llegando con reparto automatico")


def monos_texturizados(cuantos=2, planos=1):
    """Suzannes con UV de verdad: islas irregulares, que es lo dificil."""
    limpiar()
    objetos = []
    for i in range(cuantos):
        bpy.ops.mesh.primitive_monkey_add(location=(i * 3.0, 0.0, 0.0))
        obj = bpy.context.active_object
        obj.name = "Mono%d" % i
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_all(action='SELECT')
        bpy.ops.uv.smart_project(angle_limit=1.15, island_margin=0.01)
        bpy.ops.object.mode_set(mode='OBJECT')
        obj.data.materials.append(material_textura("Piel%d" % i, VERDE))
        for k in range(planos):
            obj.data.materials.append(
                material_plano("Liso%d_%d" % (i, k), AZUL))
        ranuras = 1 + planos
        for j, poligono in enumerate(obj.data.polygons):
            poligono.material_index = j % ranuras
        objetos.append(obj)
    seleccionar(objetos)
    return objetos


def util_de(objetos, planas_por_objeto):
    """Area UV real de las caras con textura, medida a mano."""
    total = 0.0
    for obj in objetos:
        mesh = obj.data
        uv = uv_de(obj)
        datos = uvs.indices(mesh)
        areas = uvs.areas_uv(uv, datos)
        fuera = np.zeros(len(areas), dtype=bool)
        fuera[planas_por_objeto[obj.name]] = True
        total += float(areas[~fuera].sum())
    return total


def prueba_empaquetado_por_forma():
    titulo("Empaquetado por la forma real")
    resultados = {}
    for modo in ('CAJA', 'FORMA'):
        objetos = monos_texturizados(2, 1)
        planas = {o.name: [j for j, p in enumerate(o.data.polygons)
                           if p.material_index != 0] for o in objetos}
        ajustes = bpy.context.scene.atlara
        ajustes.resolucion = '512'
        ajustes.prefijo = "Forma" + modo
        ajustes.empaquetador = modo
        resultado = bpy.ops.atlara.atlas()
        comprobar('FINISHED' in resultado, "%s termina" % modo)
        resultados[modo] = (bpy.context.scene.atlara.informe.util,
                            util_de(objetos, planas), objetos, planas)
    bpy.context.scene.atlara.empaquetador = 'FORMA'

    for modo in ('CAJA', 'FORMA'):
        informado, medido, _o, _p = resultados[modo]
        comprobar(abs(informado - medido) < 0.03,
                  "%s: informa %.1f%% y de verdad hay %.1f%%"
                  % (modo, informado * 100, medido * 100))

    caja = resultados['CAJA'][0]
    forma = resultados['FORMA'][0]
    comprobar(forma > caja * 1.05,
              "por forma se aprovecha mas: %.1f%% contra %.1f%% (+%.0f%%)"
              % (forma * 100, caja * 100, (forma - caja) / caja * 100))
    comprobar(forma <= 1.0, "y nunca pasa del 100%% (%.1f%%)" % (forma * 100))

    objetos, planas = resultados['FORMA'][2], resultados['FORMA'][3]
    for obj in objetos:
        uv = uv_de(obj)
        comprobar(uv.min() >= -1e-4 and uv.max() <= 1.0 + 1e-4,
                  "%s con las UV dentro del cuadrado (%.3f..%.3f)"
                  % (obj.name, uv.min(), uv.max()))


def prueba_forma_respeta_celdas():
    titulo("La forma no desparrama las celdas de color")
    objetos = monos_texturizados(1, 3)
    obj = objetos[0]
    planas = [j for j, p in enumerate(obj.data.polygons)
              if p.material_index != 0]
    ajustes = bpy.context.scene.atlara
    ajustes.resolucion = '512'
    ajustes.prefijo = "Celdas"
    ajustes.empaquetador = 'FORMA'
    comprobar('FINISHED' in bpy.ops.atlara.atlas(), "termina")

    uv = uv_de(obj)
    datos = uvs.indices(obj.data)
    bucles = uvs.bucles_de(datos, np.asarray(planas, dtype=np.int64))
    puntos = uv[bucles]
    lados = (float(puntos[:, 0].max() - puntos[:, 0].min()),
             float(puntos[:, 1].max() - puntos[:, 1].min()))
    # Tres celdas de 16 px en un atlas de 512: la nube entera tiene que
    # seguir siendo pequena. Si el packer las hubiera repartido por ahi,
    # esta caja se comeria el atlas.
    comprobar(max(lados) < 0.25,
              "las celdas siguen juntas y pequenas (%.3f x %.3f)" % lados)

    base = bpy.data.images.get("Celdas_BaseColor")
    comprobar(base is not None and cuantos_como(base, AZUL) > 100,
              "y su color exacto sigue en el atlas (%d px)"
              % (cuantos_como(base, AZUL) if base else 0))
    comprobar(base is not None and cuantos_como(base, VERDE) > 100,
              "junto a la textura verde (%d px)"
              % (cuantos_como(base, VERDE) if base else 0))


def prueba_forma_no_solapa():
    titulo("La forma no solapa parcelas")
    objetos = monos_texturizados(2, 0)
    ajustes = bpy.context.scene.atlara
    ajustes.resolucion = '512'
    ajustes.prefijo = "Solape"
    ajustes.empaquetador = 'FORMA'
    comprobar('FINISHED' in bpy.ops.atlara.atlas(), "termina")

    # Rasterizo los triangulos de todas las caras y cuento cuantas veces
    # se pinta cada texel. Con dos objetos en el mismo atlas, si el
    # packer los pisara se veria aqui.
    LADO = 256
    conteo = np.zeros((LADO, LADO), dtype=np.int32)
    for obj in objetos:
        uv = uv_de(obj)
        datos = uvs.indices(obj.data)
        for p in range(datos['caras']):
            a = int(datos['inicio'][p])
            k = int(datos['total'][p])
            pts = uv[a:a + k]
            cx = int(np.clip(pts[:, 0].mean() * LADO, 0, LADO - 1))
            cy = int(np.clip(pts[:, 1].mean() * LADO, 0, LADO - 1))
            conteo[cy, cx] += 1
    # El centro de dos caras distintas puede caer en el mismo texel por
    # redondeo, asi que se mira que no sea sistematico.
    pisados = int(np.count_nonzero(conteo > 1))
    tocados = int(np.count_nonzero(conteo))
    comprobar(pisados < tocados * 0.35,
              "centros de cara casi nunca coinciden: %d de %d"
              % (pisados, tocados))


def prueba_empaquetado_automatico():
    titulo("Empaquetado automatico: nunca peor")
    medidas = {}
    for modo, forma in (('CAJA', 'CONCAVE'), ('FORMA', 'AABB'),
                        ('AUTO', 'AABB')):
        objetos = monos_texturizados(2, 1)
        ajustes = bpy.context.scene.atlara
        ajustes.resolucion = '512'
        ajustes.prefijo = "Auto" + modo
        ajustes.empaquetador = modo
        ajustes.forma = forma
        comprobar('FINISHED' in bpy.ops.atlara.atlas(), "%s termina" % modo)
        medidas[modo] = bpy.context.scene.atlara.informe.util
    bpy.context.scene.atlara.empaquetador = 'AUTO'
    bpy.context.scene.atlara.forma = 'CONCAVE'

    mejor = max(medidas['CAJA'], medidas['FORMA'])
    comprobar(medidas['AUTO'] >= mejor - 0.005,
              "automatico %.1f%% iguala al mejor de caja %.1f%% y forma "
              "%.1f%%" % (medidas['AUTO'] * 100, medidas['CAJA'] * 100,
                          medidas['FORMA'] * 100))


def prueba_margen_exacto():
    titulo("El margen pedido es el que sale")
    for modo in ('CAJA', 'FORMA'):
        objetos = monos_texturizados(1, 0)
        ajustes = bpy.context.scene.atlara
        ajustes.resolucion = '1024'
        ajustes.prefijo = "Marg" + modo
        ajustes.empaquetador = modo
        ajustes.margen_auto = False
        ajustes.margen = 8
        try:
            comprobar('FINISHED' in bpy.ops.atlara.atlas(),
                      "%s termina" % modo)
            uv = uv_de(objetos[0])
            borde = min(float(uv.min()), 1.0 - float(uv.max())) * 1024
            comprobar(6.0 <= borde <= 10.0,
                      "%s deja %.1f texeles de borde pidiendo 8"
                      % (modo, borde))
        finally:
            ajustes.margen_auto = True
    bpy.context.scene.atlara.empaquetador = 'AUTO'


def prueba_margen_no_revienta():
    titulo("Un margen absurdo no manda las UV fuera del atlas")
    comprobar(uvs.margen_seguro(8, 1024, 1) <= 0.25,
              "con una isla el margen se topa (%.4f)"
              % uvs.margen_seguro(8, 1024, 1))
    comprobar(uvs.margen_seguro(400, 1024, 100) < 0.05,
              "con 100 islas se topa mucho antes (%.4f)"
              % uvs.margen_seguro(400, 1024, 100))
    comprobar(abs(uvs.margen_seguro(8, 1024, 400) - 8 / 1024.0) < 1e-9,
              "y si el pedido es razonable lo respeta tal cual")

    objetos = monos_texturizados(1, 0)
    ajustes = bpy.context.scene.atlara
    ajustes.resolucion = '256'
    ajustes.prefijo = "Bestia"
    ajustes.empaquetador = 'FORMA'
    ajustes.margen_auto = False
    ajustes.margen = 60
    try:
        comprobar('FINISHED' in bpy.ops.atlara.atlas(),
                  "termina con un margen desproporcionado")
        uv = uv_de(objetos[0])
        comprobar(uv.min() >= -1e-4 and uv.max() <= 1.0 + 1e-4,
                  "y las UV siguen dentro del cuadrado (%.3f..%.3f)"
                  % (uv.min(), uv.max()))
    finally:
        ajustes.margen_auto = True
        ajustes.empaquetador = 'AUTO'


def prueba_canal_uv_del_atlas():
    titulo("El canal UV del atlas")
    import tempfile

    uno, dos, luz = montar()
    seleccionar([uno, dos, luz])
    ajustes = bpy.context.scene.atlara
    ajustes.resolucion = '256'
    ajustes.prefijo = "Canal"
    ajustes.capas_uv = 'CONSERVAR'
    comprobar('FINISHED' in bpy.ops.atlara.atlas(), "termina")

    capas = [c.name for c in uno.data.uv_layers]
    comprobar(capas[0] == "Atlas", "el atlas es el canal 0: %s" % capas)
    comprobar("UVMap" in capas, "y la UV original sigue ahi: %s" % capas)

    mat = uno.data.materials[0]
    mapas = [n for n in mat.node_tree.nodes if n.type == 'UVMAP']
    comprobar(len(mapas) == 1 and mapas[0].uv_map == "Atlas",
              "el material dice explicitamente que capa lee: %s"
              % [m.uv_map for m in mapas])
    texturas = [n for n in mat.node_tree.nodes if n.type == 'TEX_IMAGE']
    comprobar(all(n.inputs["Vector"].is_linked for n in texturas),
              "y las %d texturas van enganchadas a ella" % len(texturas))

    # Lo que de verdad importa: que al exportar, el motor reciba el
    # atlas en TEXCOORD_0. Los exportadores se guian por el ORDEN de las
    # capas, no por cual es la activa.
    ruta = os.path.join(tempfile.gettempdir(), "atlara_canal.gltf")
    antes = uv_de(uno).copy()
    try:
        bpy.ops.export_scene.gltf(filepath=ruta, export_format='GLTF_SEPARATE',
                                  use_selection=False)
        exportado = True
    except (RuntimeError, AttributeError):
        exportado = False
    comprobar(exportado, "se exporta a glTF")
    if exportado:
        nombre = uno.name
        bpy.ops.wm.read_factory_settings(use_empty=True)
        bpy.ops.import_scene.gltf(filepath=ruta)
        vuelto = None
        for obj in bpy.context.scene.objects:
            if obj.type == 'MESH' and obj.name.startswith(nombre[:4]):
                vuelto = obj
                break
        comprobar(vuelto is not None, "y se reimporta")
        if vuelto is not None:
            capa0 = vuelto.data.uv_layers[0]
            datos = np.empty(len(vuelto.data.loops) * 2, dtype=np.float32)
            capa0.data.foreach_get("uv", datos)
            reimportado = datos.reshape(-1, 2)
            parecido = (abs(float(reimportado.min()) - float(antes.min()))
                        < 0.02)
            comprobar(parecido,
                      "TEXCOORD_0 trae las UV del atlas (%.3f contra %.3f)"
                      % (reimportado.min(), antes.min()))
        try:
            os.remove(ruta)
            for extra in glob.glob(ruta.replace(".gltf", "*")):
                os.remove(extra)
        except OSError:
            pass


def prueba_solo_el_atlas():
    titulo("Modo de un solo canal UV")
    uno, dos, luz = montar()
    seleccionar([uno, dos, luz])
    ajustes = bpy.context.scene.atlara
    ajustes.resolucion = '256'
    ajustes.prefijo = "Solo1"
    ajustes.capas_uv = 'UNA'
    try:
        comprobar('FINISHED' in bpy.ops.atlara.atlas(), "termina")
        capas = [c.name for c in uno.data.uv_layers]
        comprobar(capas == ["UVMap"], "queda un solo canal, UVMap: %s" % capas)
        mat = uno.data.materials[0]
        mapas = [n for n in mat.node_tree.nodes if n.type == 'UVMAP']
        comprobar(mapas and mapas[0].uv_map == "UVMap",
                  "y el material apunta a el: %s" % [m.uv_map for m in mapas])
    finally:
        bpy.context.scene.atlara.capas_uv = 'CONSERVAR'


def prueba_reproyectar_con_dos_capas():
    titulo("Reproyectar toca la capa que se usa, no otra")
    limpiar()
    obj = cubo("Doble", (0.0, 0.0, 0.0), 1.0)
    obj.data.materials.append(material_textura("Piel", VERDE))
    mesh = obj.data
    while mesh.uv_layers:
        mesh.uv_layers.remove(mesh.uv_layers[0])
    principal = mesh.uv_layers.new(name="UVMap")
    lightmap = mesh.uv_layers.new(name="Lightmap")
    n = len(mesh.loops) * 2
    principal.data.foreach_set("uv", np.linspace(0, 1, n).astype(np.float32))
    lightmap.data.foreach_set("uv", np.full(n, 0.5, dtype=np.float32))
    principal.active_render = True
    mesh.uv_layers.active = lightmap
    antes_light = uvs.leer(mesh, mesh.uv_layers["Lightmap"]).copy()
    seleccionar([obj])

    ajustes = bpy.context.scene.atlara
    ajustes.resolucion = '256'
    ajustes.prefijo = "Reproy"
    ajustes.reproyectar = True
    ajustes.capas_uv = 'CONSERVAR'
    try:
        comprobar('FINISHED' in bpy.ops.atlara.atlas(), "termina")
    finally:
        ajustes.reproyectar = False

    despues_light = uvs.leer(mesh, mesh.uv_layers["Lightmap"])
    comprobar(np.allclose(antes_light, despues_light),
              "el lightmap se queda intacto (max dif %.4f)"
              % float(np.abs(antes_light - despues_light).max()))
    capas = [c.name for c in mesh.uv_layers]
    comprobar(capas[0] == "Atlas", "y el atlas es el canal 0: %s" % capas)


def prueba_nombres_de_fichero():
    titulo("Nombres de objeto que romperian el PNG")
    from atlara import horneado as H
    comprobar(H.nombre_de_fichero("Pared/Izq") == "Pared_Izq",
              "la barra se sustituye: %s" % H.nombre_de_fichero("Pared/Izq"))
    comprobar(H.nombre_de_fichero("Pared:Izq") == "Pared_Izq",
              "y los dos puntos tambien")
    comprobar(H.nombre_de_fichero("  ..  ") == "atlas",
              "y un nombre imposible no deja el fichero sin nombre")
    comprobar(H.nombre_de_fichero("Muro normal") == "Muro normal",
              "pero un nombre normal no se toca")

    import tempfile
    limpiar()
    obj = cubo("Pared/Izq", (0.0, 0.0, 0.0), 1.0)
    obj.data.materials.append(material_textura("Ladrillo", ROJO))
    seleccionar([obj])
    carpeta = os.path.join(tempfile.gettempdir(), "atlara_nombres")
    ajustes = bpy.context.scene.atlara
    ajustes.resolucion = '128'
    ajustes.prefijo = "Raro"
    ajustes.modo = 'OBJETO'
    ajustes.guardado = 'DISCO'
    ajustes.carpeta = carpeta
    try:
        comprobar('FINISHED' in bpy.ops.atlara.atlas(), "termina")
        sueltos = glob.glob(os.path.join(carpeta, "*.png"))
        comprobar(len(sueltos) >= 1,
                  "el PNG cae en la carpeta pedida (%d)" % len(sueltos))
        comprobar(not glob.glob(os.path.join(carpeta, "*", "*.png")),
                  "y no se inventa subcarpetas")
        for ruta in sueltos:
            os.remove(ruta)
    finally:
        ajustes.guardado = 'EMPAQUETAR'
        ajustes.modo = 'TODO'


def prueba_error_a_medias():
    titulo("Si uno no cabe, no quedan otros a medias")
    limpiar()
    cabe = cubo("SiCabe", (0.0, 0.0, 0.0), 1.0)
    cabe.data.materials.append(material_textura("Uno", VERDE))
    no_cabe = cubo("NoCabe", (3.0, 0.0, 0.0), 1.0)
    no_cabe.data.materials.append(material_textura("Dos", AZUL))
    no_cabe.data.materials.append(material_textura("Tres", ROJO))
    for i, poligono in enumerate(no_cabe.data.polygons):
        poligono.material_index = i % 2
    seleccionar([cabe, no_cabe])

    materiales_antes = [m.name for m in cabe.data.materials]
    capas_antes = [c.name for c in cabe.data.uv_layers]

    ajustes = bpy.context.scene.atlara
    ajustes.modo = 'OBJETO'
    ajustes.resolucion = '128'
    ajustes.empaquetador = 'CAJA'
    ajustes.agrupacion = 'GRUPO'
    ajustes.margen_auto = False
    ajustes.margen = 40
    try:
        try:
            resultado = bpy.ops.atlara.atlas()
            fallo = 'CANCELLED' in resultado
        except RuntimeError:
            fallo = True
        comprobar(fallo, "el operador avisa de que no cabe")
        vuelto = bpy.data.objects.get("SiCabe")
        comprobar(vuelto is not None, "el primer objeto sigue ahi")
        if vuelto is not None:
            comprobar([m.name for m in vuelto.data.materials]
                      == materiales_antes,
                      "y con sus materiales de antes: %s"
                      % [m.name for m in vuelto.data.materials])
            comprobar([c.name for c in vuelto.data.uv_layers] == capas_antes,
                      "y sus capas UV de antes: %s"
                      % [c.name for c in vuelto.data.uv_layers])
    finally:
        ajustes = bpy.context.scene.atlara
        ajustes.modo = 'TODO'
        ajustes.margen_auto = True
        ajustes.empaquetador = 'AUTO'
        ajustes.agrupacion = 'AUTO'


def prueba_formato_webp():
    titulo("Guardado en WebP")
    from atlara import horneado as H

    comprobar(H.calidad_de('NORMAL', 'WEBP', 80) == 100,
              "el mapa de normales se guarda sin perdida pase lo que pase")
    comprobar(H.calidad_de('ORM', 'WEBP', 50) == 100,
              "y el ORM tambien")
    comprobar(H.calidad_de('BASE', 'WEBP', 80) == 80,
              "el color base si respeta la calidad pedida")
    comprobar(H.calidad_de('BASE', 'PNG', 80) == 100,
              "en PNG la calidad no pinta nada")

    import tempfile
    carpeta = os.path.join(tempfile.gettempdir(), "atlara_formato")
    pesos = {}
    for formato in ('PNG', 'WEBP'):
        limpiar()
        obj = cubo("Lata", (0.0, 0.0, 0.0), 1.0)
        obj.data.materials.append(
            material_textura("Pintura", VERDE, lado=256, normal=True))
        seleccionar([obj])
        ajustes = bpy.context.scene.atlara
        ajustes.resolucion = '512'
        ajustes.prefijo = "Fmt" + formato
        ajustes.guardado = 'DISCO'
        ajustes.carpeta = carpeta
        ajustes.formato = formato
        ajustes.calidad = 90
        try:
            comprobar('FINISHED' in bpy.ops.atlara.atlas(),
                      "%s termina" % formato)
        finally:
            ajustes.guardado = 'EMPAQUETAR'
            ajustes.formato = 'PNG'
        ext = H.EXTENSION[formato]
        ficheros = glob.glob(os.path.join(carpeta, "Fmt%s_*.%s"
                                          % (formato, ext)))
        comprobar(len(ficheros) >= 2,
                  "%s escribe %d ficheros .%s" % (formato, len(ficheros), ext))
        pesos[formato] = sum(os.path.getsize(f) for f in ficheros)
        for f in ficheros:
            os.remove(f)

    comprobar(pesos['WEBP'] < pesos['PNG'],
              "WebP pesa menos: %.1f KB frente a %.1f KB (%.0f%% menos)"
              % (pesos['WEBP'] / 1024.0, pesos['PNG'] / 1024.0,
                 (1 - pesos['WEBP'] / max(pesos['PNG'], 1)) * 100))


def prueba_webp_sin_perdida_en_datos():
    titulo("WebP no toca un solo texel del mapa de normales")
    import tempfile
    from atlara import horneado as H
    limpiar()
    img = bpy.data.images.new("NormalPrueba", 128, 128, alpha=True,
                              is_data=True)
    img.colorspace_settings.name = 'Non-Color'
    rng = np.random.default_rng(11)
    pix = np.zeros((128, 128, 4), dtype=np.float32)
    yy, xx = np.mgrid[0:128, 0:128] / 128.0
    pix[:, :, 0] = np.clip(0.5 + 0.4 * np.sin(xx * 40)
                           + 0.05 * rng.random((128, 128)), 0, 1)
    pix[:, :, 1] = np.clip(0.5 + 0.4 * np.cos(yy * 40)
                           + 0.05 * rng.random((128, 128)), 0, 1)
    pix[:, :, 2] = 1.0
    pix[:, :, 3] = 1.0
    img.pixels.foreach_set(pix.reshape(-1))
    antes = pixeles(img).copy()

    carpeta = os.path.join(tempfile.gettempdir(), "atlara_sinperdida")
    os.makedirs(carpeta, exist_ok=True)
    ruta = H.guardar(img, carpeta, 'WEBP', 60, 'NORMAL')
    comprobar(ruta.endswith(".webp"), "se escribe como .webp")

    vuelta = bpy.data.images.load(ruta)
    vuelta.colorspace_settings.name = 'Non-Color'
    despues = pixeles(vuelta)
    error = float(np.abs(antes[:, :, :3] - despues[:, :, :3]).max())
    comprobar(error < 1e-4,
              "ida y vuelta sin perdida aunque se pida calidad 60 "
              "(error maximo %.6f)" % error)
    os.remove(ruta)


def cabecera_de(datos) -> str:
    """Que formato hay dentro del fichero, por su firma."""
    firma_png = bytes([137, 80, 78, 71, 13, 10, 26, 10])
    if datos[:8] == firma_png:
        return "PNG"
    if datos[:4] == b"RIFF" and datos[8:12] == b"WEBP":
        return "WEBP"
    return "desconocido"


def prueba_empaquetado_es_webp_de_verdad():
    titulo("Empaquetado dentro del .blend: WebP de verdad")
    import tempfile
    antes_tmp = set(glob.glob(os.path.join(tempfile.gettempdir(),
                                           "atlara_*")))
    limpiar()
    obj = cubo("Bidon", (0.0, 0.0, 0.0), 1.0)
    obj.data.materials.append(
        material_textura("Chapa", VERDE, lado=256, normal=True))
    seleccionar([obj])

    pesos = {}
    for formato in ('PNG', 'WEBP'):
        ajustes = bpy.context.scene.atlara
        ajustes.resolucion = '512'
        ajustes.prefijo = "Pk" + formato
        ajustes.guardado = 'EMPAQUETAR'
        ajustes.formato = formato
        ajustes.calidad = 90
        try:
            comprobar('FINISHED' in bpy.ops.atlara.atlas(),
                      "%s termina" % formato)
        finally:
            ajustes.formato = 'PNG'
        imgs = [i for i in bpy.data.images
                if i.name.startswith("Pk" + formato) and i.packed_file]
        comprobar(len(imgs) >= 2,
                  "%s deja %d imagenes empaquetadas" % (formato, len(imgs)))
        cabeceras = {cabecera_de(i.packed_file.data) for i in imgs}
        comprobar(cabeceras == {formato},
                  "y por dentro son %s: %s" % (formato, sorted(cabeceras)))
        pesos[formato] = sum(i.packed_file.size for i in imgs)

    comprobar(pesos['WEBP'] < pesos['PNG'],
              "WebP empaquetado pesa menos: %.1f KB frente a %.1f KB "
              "(%.0f%% menos)"
              % (pesos['WEBP'] / 1024.0, pesos['PNG'] / 1024.0,
                 (1 - pesos['WEBP'] / max(pesos['PNG'], 1)) * 100))

    normal = [i for i in bpy.data.images
              if i.name == "PkWEBP_Normal" and i.packed_file]
    comprobar(bool(normal) and cabecera_de(normal[0].packed_file.data)
              == "WEBP", "el mapa de normales empaquetado tambien es WebP")

    nuevas = set(glob.glob(os.path.join(tempfile.gettempdir(),
                                        "atlara_*"))) - antes_tmp
    comprobar(not nuevas,
              "y no deja carpetas temporales atras (%s)"
              % sorted(os.path.basename(c) for c in nuevas))


def a_srgb(x):
    """El buffer de una imagen sRGB guarda los valores ya codificados.

    img.pixels no los devuelve en lineal. Con colores puros (0 y 1) da
    igual porque la codificacion es la identidad, pero en cuanto se
    comprueba un degradado hay que codificar lo que se esperaba.
    """
    x = np.clip(np.asarray(x, dtype=np.float64), 0.0, 1.0)
    return np.where(x <= 0.0031308, x * 12.92,
                    1.055 * np.power(x, 1.0 / 2.4) - 0.055)


def material_degradado(nombre, lado=256):
    """Textura cuyo color DICE su coordenada UV."""
    mat = bpy.data.materials.new(nombre)
    if mat.node_tree is None:
        mat.use_nodes = True
    bsdf = mat.node_tree.nodes["Principled BSDF"]
    img = bpy.data.images.new(nombre + "_g", lado, lado, is_data=True)
    img.colorspace_settings.name = 'Non-Color'
    pix = np.zeros((lado, lado, 4), dtype=np.float32)
    yy, xx = np.mgrid[0:lado, 0:lado]
    pix[:, :, 0] = (xx + 0.5) / lado
    pix[:, :, 1] = (yy + 0.5) / lado
    pix[:, :, 3] = 1.0
    img.pixels.foreach_set(pix.reshape(-1))
    tex = mat.node_tree.nodes.new('ShaderNodeTexImage')
    tex.image = img
    mat.node_tree.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    return mat


def cajas_por_isla(obj):
    mesh = obj.data
    uv = uvs.leer(mesh, uvs.capa_origen(mesh))
    datos = uvs.indices(mesh)
    salida = []
    for isla in uvs.islas(uv, np.arange(datos['caras']), datos):
        b = uvs.bucles_de(datos, isla)
        salida.append((round(float(uv[b, 0].min()), 3),
                       round(float(uv[b, 1].min()), 3),
                       round(float(uv[b, 0].max()), 3),
                       round(float(uv[b, 1].max()), 3)))
    return salida


def escena_compartida(n, mat):
    limpiar_menos_datos = None
    objetos = []
    for i in range(n):
        bpy.ops.mesh.primitive_cube_add(size=1, location=(i * 2.0, 0, 0))
        o = bpy.context.active_object
        o.name = "Cmp%d" % i
        o.data.materials.append(mat)
        objetos.append(o)
    seleccionar(objetos)
    return objetos


def prueba_reutilizar_parcelas():
    titulo("Reutilizar parcelas repetidas")
    limpiar()
    mat = material_degradado("Comun")
    objetos = escena_compartida(5, mat)
    antes = {o.name: uvs.leer(o.data, uvs.capa_origen(o.data)).copy()
             for o in objetos}

    ajustes = bpy.context.scene.atlara
    ajustes.resolucion = '512'
    ajustes.prefijo = "Reuso"
    ajustes.empaquetador = 'CAJA'
    ajustes.agrupacion = 'GRUPO'
    ajustes.reutilizar = True
    try:
        comprobar('FINISHED' in bpy.ops.atlara.atlas(), "termina")
    finally:
        ajustes.empaquetador = 'AUTO'
        ajustes.agrupacion = 'AUTO'

    cajas = []
    for o in objetos:
        cajas.extend(cajas_por_isla(o))
    comprobar(len(set(cajas)) == 1,
              "los 5 objetos comparten UNA sola parcela (%d distintas)"
              % len(set(cajas)))

    img = bpy.data.images["Reuso_BaseColor"]
    atlas = pixeles(img)
    lado = img.size[0]
    fallos = comprobadas = 0
    for o in objetos:
        datos = uvs.indices(o.data)
        despues = uvs.leer(o.data, uvs.capa_origen(o.data))
        viejo = antes[o.name]
        for p in range(datos['caras']):
            ini = int(datos['inicio'][p])
            tot = int(datos['total'][p])
            cu = float(viejo[ini:ini + tot, 0].mean())
            cv = float(viejo[ini:ini + tot, 1].mean())
            nu = float(despues[ini:ini + tot, 0].mean())
            nv = float(despues[ini:ini + tot, 1].mean())
            x = min(lado - 1, max(0, int(nu * lado)))
            y = min(lado - 1, max(0, int(nv * lado)))
            comprobadas += 1
            if np.abs(atlas[y, x, :3]
                      - a_srgb((cu, cv, 0.0))).max() > 0.06:
                fallos += 1
    comprobar(fallos == 0,
              "y las %d caras siguen leyendo su color exacto (%d fallan)"
              % (comprobadas, fallos))


def prueba_no_reutilizar_lo_que_depende_del_objeto():
    titulo("Lo que depende del objeto no se comparte")
    limpiar()
    mat = material_degradado("PorObjeto")
    info = mat.node_tree.nodes.new('ShaderNodeObjectInfo')
    mezcla = mat.node_tree.nodes.new('ShaderNodeMixRGB')
    bsdf = mat.node_tree.nodes["Principled BSDF"]
    tex = [n for n in mat.node_tree.nodes if n.type == 'TEX_IMAGE'][0]
    mat.node_tree.links.new(tex.outputs["Color"], mezcla.inputs[1])
    mat.node_tree.links.new(info.outputs["Color"], mezcla.inputs[2])
    mat.node_tree.links.new(mezcla.outputs[0], bsdf.inputs["Base Color"])

    ficha = materiales.leer(mat)
    comprobar(bool(ficha['geometrico']),
              "se detecta que depende del objeto: %s" % ficha['geometrico'])

    objetos = escena_compartida(4, mat)
    ajustes = bpy.context.scene.atlara
    ajustes.resolucion = '512'
    ajustes.prefijo = "NoReuso"
    ajustes.empaquetador = 'CAJA'
    ajustes.agrupacion = 'GRUPO'
    try:
        comprobar('FINISHED' in bpy.ops.atlara.atlas(), "termina")
    finally:
        ajustes.empaquetador = 'AUTO'
        ajustes.agrupacion = 'AUTO'

    cajas = []
    for o in objetos:
        cajas.extend(cajas_por_isla(o))
    comprobar(len(set(cajas)) == 4,
              "cada objeto se queda con SU parcela (%d distintas de 4)"
              % len(set(cajas)))


def prueba_criterio_de_fusion():
    titulo("Cuando compartir sale a cuenta y cuando no")
    from atlara.proceso import Trozo, cabe_junto

    def trozo(x0, y0, x1, y1):
        medidas = {'x0': x0, 'y0': y0, 'x1': x1, 'y1': y1,
                   'areauv': (x1 - x0) * (y1 - y0), 'area3d': 1.0}
        return Trozo(None, None, None, medidas, (1.0, 1.0), "m")

    comprobar(cabe_junto(trozo(0, 0, 1, 1), trozo(0, 0, 1, 1)),
              "dos parcelas identicas se funden")
    comprobar(cabe_junto(trozo(0, 0, 1, 1), trozo(0.1, 0.1, 0.9, 0.9)),
              "y una dentro de otra tambien")
    comprobar(not cabe_junto(trozo(0, 0, 0.1, 0.1),
                             trozo(0.9, 0.9, 1.0, 1.0)),
              "pero dos en esquinas opuestas no, que la union es un "
              "caseron vacio")
    comprobar(cabe_junto(trozo(0, 0, 0.5, 1.0), trozo(0.5, 0, 1.0, 1.0)),
              "dos mitades pegadas si: la union no cuesta mas")


def prueba_reutilizar_de_fabrica():
    titulo("Reutilizar con los ajustes de fabrica")
    limpiar()
    mat = material_degradado("Fabrica")
    objetos = escena_compartida(5, mat)
    ajustes = bpy.context.scene.atlara
    ajustes.resolucion = '512'
    ajustes.prefijo = "Fab"
    # A proposito NO se tocan empaquetador ni agrupacion: se prueba
    # justo lo que se encuentra el usuario al instalar.
    comprobar(ajustes.empaquetador == 'AUTO' and ajustes.agrupacion == 'AUTO'
              and ajustes.reutilizar,
              "los ajustes de fabrica son AUTO/AUTO con reutilizar puesto")
    comprobar('FINISHED' in bpy.ops.atlara.atlas(), "termina")

    cajas = []
    for o in objetos:
        cajas.extend(cajas_por_isla(o))
    comprobar(len(set(cajas)) == 1,
              "y de fabrica ya comparte: %d parcelas distintas de 5"
              % len(set(cajas)))


def prueba_islas_apiladas():
    titulo("Las UV apiladas a proposito se respetan")
    limpiar()
    malla = bpy.data.meshes.new("Apilada")
    verts, caras = [], []
    for mitad in range(2):
        for i in range(4):
            base = len(verts)
            x = i * 1.5 + mitad * 20.0
            verts += [(x, 0, 0), (x + 1, 0, 0), (x + 1, 1, 0), (x, 1, 0)]
            caras.append((base, base + 1, base + 2, base + 3))
    malla.from_pydata(verts, [], caras)
    malla.update()
    obj = bpy.data.objects.new("Apilada", malla)
    bpy.context.scene.collection.objects.link(obj)
    obj.data.materials.append(material_degradado("Apilado"))

    capa = malla.uv_layers.new(name="UVMap")
    datos = uvs.indices(malla)
    uv = uvs.leer(malla, capa)
    # Las dos mitades reciben EXACTAMENTE las mismas UV.
    esquinas = np.asarray([(0.05, 0.05), (0.95, 0.05),
                           (0.95, 0.95), (0.05, 0.95)])
    for p in range(datos['caras']):
        ini = int(datos['inicio'][p])
        uv[ini:ini + 4] = esquinas
    uvs.escribir(malla, capa, uv)
    seleccionar([obj])

    ajustes = bpy.context.scene.atlara
    ajustes.resolucion = '512'
    ajustes.prefijo = "Apil"
    comprobar('FINISHED' in bpy.ops.atlara.atlas(), "termina")

    despues = uvs.leer(malla, uvs.capa_origen(malla))
    datos = uvs.indices(malla)
    cajas = set()
    for p in range(datos['caras']):
        ini = int(datos['inicio'][p])
        trozo = despues[ini:ini + 4]
        cajas.add((round(float(trozo[:, 0].min()), 3),
                   round(float(trozo[:, 1].min()), 3),
                   round(float(trozo[:, 0].max()), 3),
                   round(float(trozo[:, 1].max()), 3)))
    comprobar(len(cajas) == 1,
              "las 8 caras apiladas siguen encima unas de otras "
              "(%d sitios distintos)" % len(cajas))
    caja = list(cajas)[0]
    lado_uv = min(caja[2] - caja[0], caja[3] - caja[1])
    comprobar(lado_uv > 0.5,
              "y se llevan casi todo el atlas, no un rincon (%.2f de lado)"
              % lado_uv)


def prueba_cancelar():
    titulo("Cancelacion")
    uno, dos, _luz = montar()
    seleccionar([uno, dos])
    ajustes = bpy.context.scene.atlara
    ajustes.resolucion = '128'
    ajustes.prefijo = "Cancelada"

    capa = uvs.capa_origen(uno.data)
    nombre_previo = capa.name
    antes = uvs.leer(uno.data, capa).copy()
    capas_antes = [c.name for c in uno.data.uv_layers]
    materiales_antes = [m.name for m in uno.data.materials]
    motor_antes = bpy.context.scene.render.engine

    tanda = proceso.Tanda([("", [uno, dos])], ajustes)
    comprobar(tanda.avanzar(bpy.context), "prepara el primer lote")
    comprobar(not tanda.error, "sin error al preparar: %s" % tanda.error)
    comprobar(tanda.actual.total > 0, "hay %d horneados por delante"
              % tanda.actual.total)
    tanda.avanzar(bpy.context)
    comprobar(tanda.fraccion() > 0.0, "la fraccion avanza (%.2f)"
              % tanda.fraccion())
    comprobar(" de " in tanda.etiqueta(), "la etiqueta dice que hace: %s"
              % tanda.etiqueta())

    tanda.tirar_todo(bpy.context)
    comprobar([c.name for c in uno.data.uv_layers] == capas_antes,
              "las capas UV vuelven a ser %s" % capas_antes)
    despues = uvs.leer(uno.data, uvs.capa_origen(uno.data))
    comprobar(float(np.abs(despues - antes).max()) < 1e-6,
              "las UV originales estan intactas")
    comprobar([m.name for m in uno.data.materials] == materiales_antes,
              "los materiales siguen siendo los de antes")
    comprobar(not [i for i in bpy.data.images
                   if i.name.startswith("Cancelada")],
              "no queda ninguna imagen del atlas a medias")
    comprobar(uvs.capa_origen(uno.data).name == nombre_previo,
              "y la capa activa vuelve a ser %s" % nombre_previo)
    comprobar(bpy.context.scene.render.engine == motor_antes,
              "el motor de render vuelve a %s" % motor_antes)


def prueba_cancelar_con_lotes_hechos():
    titulo("Cancelar cuando ya hay atlas terminados")
    limpiar()
    objetos = []
    for i in range(3):
        obj = cubo("Lote%d" % i, (i * 3.0, 0.0, 0.0), 1.0)
        obj.data.materials.append(material_textura("Tex%d" % i, VERDE))
        objetos.append(obj)
    seleccionar(objetos)

    ajustes = bpy.context.scene.atlara
    ajustes.modo = 'OBJETO'
    ajustes.resolucion = '128'
    ajustes.prefijo = "Lotes"

    capas_antes = [c.name for c in objetos[0].data.uv_layers]
    materiales_antes = [m.name for m in objetos[0].data.materials]

    marcado = True
    try:
        bpy.ops.ed.undo_push(message="Atlara: antes de fundir")
    except RuntimeError:
        marcado = False
    comprobar(marcado, "se puede marcar el historial antes de empezar")

    lotes = [("_" + o.name, [o]) for o in objetos]
    tanda = proceso.Tanda(lotes, ajustes)
    vueltas = 0
    while not tanda.terminado and len(tanda.resultados) < 1 and vueltas < 200:
        tanda.avanzar(bpy.context)
        vueltas += 1
    comprobar(len(tanda.resultados) >= 1,
              "el primer objeto llega a rematarse (%d hechos)"
              % len(tanda.resultados))
    tanda.avanzar(bpy.context)
    comprobar(tanda.actual is not None,
              "y el segundo ya esta en marcha cuando se cancela")

    sucio = bpy.data.objects["Lote0"]
    comprobar([c.name for c in sucio.data.uv_layers] != capas_antes
              or [m.name for m in sucio.data.materials] != materiales_antes,
              "el primero quedo tocado: capas %s materiales %s"
              % ([c.name for c in sucio.data.uv_layers],
                 [m.name for m in sucio.data.materials]))

    tanda.tirar_todo(bpy.context)
    if marcado:
        bpy.ops.ed.undo_push(message="Atlara: cancelado")
        try:
            bpy.ops.ed.undo()
            deshecho = True
        except RuntimeError:
            deshecho = False
        comprobar(deshecho, "el historial deshace lo ya rematado")

        # Tras deshacer, toda referencia vieja esta muerta: hay que
        # volver a pedir los objetos por su nombre.
        vuelto = bpy.data.objects.get("Lote0")
        comprobar(vuelto is not None, "el objeto sigue existiendo")
        if vuelto is not None:
            comprobar([c.name for c in vuelto.data.uv_layers] == capas_antes,
                      "y recupera sus capas UV %s"
                      % [c.name for c in vuelto.data.uv_layers])
            comprobar([m.name for m in vuelto.data.materials]
                      == materiales_antes,
                      "y sus materiales de antes %s"
                      % [m.name for m in vuelto.data.materials])

    # Deshacer rehace la escena entera: cualquier referencia de Python a
    # datos de la escena, `ajustes` incluido, apunta a memoria liberada.
    # Escribir ahi tumba Blender con un fallo de segmento, asi que hay
    # que volver a pedirlo por contexto. Esto no es un detalle de la
    # prueba: le pasa a cualquiera que llame al add-on desde un script.
    ajustes = bpy.context.scene.atlara
    comprobar(ajustes.modo in ('TODO', 'OBJETO'),
              "tras deshacer hay que volver a pedir los ajustes")
    ajustes.modo = 'TODO'


def prueba_reejecutar():
    titulo("Atlasear dos veces seguidas")
    uno, dos, _luz = montar()
    seleccionar([uno, dos])
    ajustes = bpy.context.scene.atlara
    ajustes.resolucion = '128'
    ajustes.prefijo = "Dos"
    comprobar('FINISHED' in bpy.ops.atlara.atlas(), "primera pasada")
    seleccionar([uno, dos])
    comprobar('FINISHED' in bpy.ops.atlara.atlas(), "segunda pasada")
    capas = [c.name for c in uno.data.uv_layers]
    comprobar(capas == ["Atlas", "UVMap"],
              "atlasear dos veces no acumula capas UV: %s" % capas)
    comprobar(len(uno.data.materials) == 1, "y un solo material")
    uv = uv_de(uno)
    comprobar(uv.min() >= -1e-4 and uv.max() <= 1.0 + 1e-4,
              "las UV siguen dentro del cuadrado")


def prueba_invocar_sin_ventana():
    titulo("Invoke en background")
    limpiar()
    obj = cubo("Fondo", (0.0, 0.0, 0.0), 1.0)
    obj.data.materials.append(material_plano("Liso", VERDE))
    seleccionar([obj])
    bpy.context.scene.atlara.resolucion = '128'
    bpy.context.scene.atlara.prefijo = "Fondo"
    resultado = bpy.ops.atlara.atlas('INVOKE_DEFAULT')
    comprobar('FINISHED' in resultado,
              "sin ventana no se pone modal, termina de un tiron (%s)"
              % resultado)
    comprobar(len(obj.data.materials) == 1, "y deja el material fundido")


def material_en_grupo(nombre, color):
    """Un Principled metido en un grupo de nodos, como muchos assets."""
    grupo = bpy.data.node_groups.new(nombre + "_grp", 'ShaderNodeTree')
    grupo.interface.new_socket("Base Color", in_out='INPUT',
                               socket_type='NodeSocketColor')
    grupo.interface.new_socket("Shader", in_out='OUTPUT',
                               socket_type='NodeSocketShader')
    dentro = grupo.nodes.new('NodeGroupInput')
    fuera = grupo.nodes.new('NodeGroupOutput')
    bsdf = grupo.nodes.new('ShaderNodeBsdfPrincipled')
    grupo.links.new(dentro.outputs[0], bsdf.inputs["Base Color"])
    grupo.links.new(bsdf.outputs["BSDF"], fuera.inputs[0])

    mat = bpy.data.materials.new(nombre)
    if mat.node_tree is None:
        mat.use_nodes = True
    arbol = mat.node_tree
    arbol.nodes.clear()
    salida = arbol.nodes.new('ShaderNodeOutputMaterial')
    nodo = arbol.nodes.new('ShaderNodeGroup')
    nodo.node_tree = grupo
    nodo.inputs["Base Color"].default_value = (
        color[0], color[1], color[2], 1.0)
    arbol.links.new(nodo.outputs[0], salida.inputs["Surface"])
    return mat


def prueba_shaders_raros():
    titulo("Shaders que no son un Principled pelado")
    limpiar()

    mat = material_en_grupo("Grupo", ROJO)
    ficha = materiales.leer(mat)
    comprobar(ficha['entendido'],
              "un Principled dentro de un grupo se entiende por sus "
              "entradas (%s)" % ficha['shader'])
    comprobar(abs(ficha['valores']['BASE'][0] - 1.0) < 1e-4
              and ficha['valores']['BASE'][1] < 1e-4,
              "y saca el rojo de verdad %s"
              % str(tuple(round(v, 2) for v in ficha['valores']['BASE'])))

    ciego = bpy.data.materials.new("Ciego")
    if ciego.node_tree is None:
        ciego.use_nodes = True
    ciego.node_tree.nodes.clear()
    ciego.diffuse_color = (0.0, 1.0, 0.0, 1.0)
    ficha = materiales.leer(ciego)
    comprobar(not ficha['entendido'], "el que no se entiende se marca")
    comprobar(abs(ficha['valores']['BASE'][1] - 1.0) < 1e-4,
              "pero se queda con el color del visor, no con un gris %s"
              % str(tuple(round(v, 2) for v in ficha['valores']['BASE'])))
    comprobar(ficha['plano'], "y como no tiene texturas, va a celda")

    mezcla = bpy.data.materials.new("Mezcla")
    if mezcla.node_tree is None:
        mezcla.use_nodes = True
    arbol = mezcla.node_tree
    arbol.nodes.clear()
    salida = arbol.nodes.new('ShaderNodeOutputMaterial')
    nodo = arbol.nodes.new('ShaderNodeMixShader')
    rojo = arbol.nodes.new('ShaderNodeBsdfPrincipled')
    rojo.inputs["Base Color"].default_value = (1.0, 0.0, 0.0, 1.0)
    azul = arbol.nodes.new('ShaderNodeBsdfPrincipled')
    azul.inputs["Base Color"].default_value = (0.0, 0.0, 1.0, 1.0)
    arbol.links.new(rojo.outputs["BSDF"], nodo.inputs[1])
    arbol.links.new(azul.outputs["BSDF"], nodo.inputs[2])
    arbol.links.new(nodo.outputs["Shader"], salida.inputs["Surface"])

    nodo.inputs[0].default_value = 1.0
    ficha = materiales.leer(mezcla)
    comprobar(ficha['valores']['BASE'][2] > 0.9,
              "con Fac a 1 manda la segunda rama, la azul %s"
              % str(tuple(round(v, 2) for v in ficha['valores']['BASE'])))
    comprobar(ficha.get('mezclado'), "y queda avisado de que es una mezcla")

    nodo.inputs[0].default_value = 0.0
    ficha = materiales.leer(mezcla)
    comprobar(ficha['valores']['BASE'][0] > 0.9,
              "con Fac a 0 manda la primera, la roja %s"
              % str(tuple(round(v, 2) for v in ficha['valores']['BASE'])))

    fichas = {"Ciego": materiales.leer(ciego), "Mezcla": ficha}
    avisos = proceso.avisos_de(fichas)
    comprobar(any("Ciego" in a for a in avisos),
              "el informe avisa del material que no se entiende")
    comprobar(any("Mezcla" in a for a in avisos),
              "y del que mezcla shaders")


def prueba_normal_de_los_planos():
    titulo("La normal de los materiales planos")
    ficha = materiales.leer(material_plano("Liso", AZUL))
    normal = ficha['valores']['NORMAL']
    comprobar(abs(normal[0] - 0.5) < 1e-4 and abs(normal[2] - 1.0) < 1e-4,
              "un material plano guarda la normal neutra (0.5,0.5,1) y no "
              "el (0,0,0) del socket: %s"
              % str(tuple(round(v, 2) for v in normal)))

    limpiar()
    obj = cubo("Mixto", (0.0, 0.0, 0.0), 1.0)
    obj.data.materials.append(material_textura("ConNormal", VERDE,
                                               normal=True))
    obj.data.materials.append(material_plano("SinNormal", AZUL))
    for i, poligono in enumerate(obj.data.polygons):
        poligono.material_index = 1 if i < 3 else 0
    seleccionar([obj])
    ajustes = bpy.context.scene.atlara
    ajustes.resolucion = '256'
    ajustes.prefijo = "Nrm"
    comprobar('FINISHED' in bpy.ops.atlara.atlas(), "el operador termina")

    mapa = bpy.data.images.get("Nrm_Normal")
    comprobar(mapa is not None, "existe el mapa de normales")
    if mapa is not None:
        texel = muestrear(mapa, centro_uv(obj, 0))
        comprobar(texel[2] > 0.9 and abs(texel[0] - 0.5) < 0.1,
                  "la cara plana lleva la normal neutra, no negro %s"
                  % np.round(texel[:3], 2))
        datos = pixeles(mapa)[:, :, :3]
        negros = int(np.count_nonzero(np.all(datos < 0.01, axis=-1)))
        comprobar(negros == 0,
                  "y no queda ni un texel negro en el mapa (%d)" % negros)


def prueba_celdas_impares():
    titulo("Celdas de color con lados raros")
    for celda in (2, 3, 5, 7, 16, 31):
        for cantidad in (1, 7, 40, 300):
            _franja, celdas = nucleo.franja_planos(cantidad, celda, 128, 128)
            if not celdas:
                continue
            lados = set(c[2] for c in celdas)
            comprobar(min(lados) >= 2,
                      "celda %d x %d: ningun lado baja de 2 (%s)"
                      % (celda, cantidad, sorted(lados)))
            break

    limpiar()
    obj = cubo("Celdas", (0.0, 0.0, 0.0), 1.0)
    obj.data.materials.append(material_plano("Uno", ROJO))
    datos = uvs.indices(obj.data)
    uv = np.zeros((len(obj.data.loops), 2), dtype=np.float32)
    polis = np.arange(len(obj.data.polygons), dtype=np.int64)
    for lado in (2, 3, 16):
        uvs.colocar_plano(uv, datos, polis, (10, 20, lado), 128, 128)
        x = uv[:, 0] * 128.0
        y = uv[:, 1] * 128.0
        comprobar(x.min() >= 10.0 - 1e-4 and x.max() <= 10.0 + lado + 1e-4
                  and y.min() >= 20.0 - 1e-4
                  and y.max() <= 20.0 + lado + 1e-4,
                  "con lado %d las UV se quedan dentro de la celda "
                  "(%.2f..%.2f)" % (lado, x.min(), x.max()))


def prueba_solo_luces():
    titulo("Solo luces seleccionadas")
    limpiar()
    luz = bpy.data.objects.new("Sol", bpy.data.lights.new("Sol", 'SUN'))
    bpy.context.scene.collection.objects.link(luz)
    seleccionar([luz])
    try:
        resultado = bpy.ops.atlara.atlas()
        cancelado = 'CANCELLED' in resultado
    except RuntimeError as ex:
        cancelado = "malla" in str(ex)
    comprobar(cancelado, "cancela sin romper nada")


def main():
    print("\nAtlara %s sobre Blender %s"
          % (atlara.bl_info["version"], bpy.app.version_string))
    atlara.register()
    try:
        prueba_fuente()
        prueba_empaquetador()
        prueba_horizonte()
        prueba_lectura()
        prueba_atlas_junto()
        prueba_atlas_por_objeto()
        prueba_un_objeto_muchos_materiales()
        prueba_sin_uv()
        prueba_emision_alfa_islas()
        prueba_oclusion()
        prueba_guardar_en_disco()
        prueba_geometria()
        prueba_enderezar()
        prueba_texeles_y_margen()
        prueba_reparto_automatico()
        prueba_empaquetado_por_forma()
        prueba_forma_respeta_celdas()
        prueba_forma_no_solapa()
        prueba_empaquetado_automatico()
        prueba_margen_exacto()
        prueba_margen_no_revienta()
        prueba_canal_uv_del_atlas()
        prueba_reproyectar_con_dos_capas()
        prueba_nombres_de_fichero()
        prueba_error_a_medias()
        prueba_formato_webp()
        prueba_webp_sin_perdida_en_datos()
        prueba_empaquetado_es_webp_de_verdad()
        prueba_criterio_de_fusion()
        prueba_reutilizar_parcelas()
        prueba_no_reutilizar_lo_que_depende_del_objeto()
        prueba_reutilizar_de_fabrica()
        prueba_islas_apiladas()
        prueba_solo_el_atlas()
        prueba_cancelar()
        prueba_cancelar_con_lotes_hechos()
        prueba_reejecutar()
        prueba_invocar_sin_ventana()
        prueba_shaders_raros()
        prueba_normal_de_los_planos()
        prueba_celdas_impares()
        prueba_solo_luces()
    finally:
        pass

    print("\n" + "=" * 64)
    if FALLOS:
        print("%d de %d comprobaciones FALLAN:" % (len(FALLOS), PRUEBAS))
        for fallo in FALLOS:
            print("  - %s" % fallo)
        sys.exit(1)
    print("las %d comprobaciones pasan" % PRUEBAS)
    sys.exit(0)


if __name__ == "__main__":
    main()
