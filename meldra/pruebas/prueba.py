# SPDX-License-Identifier: GPL-3.0-or-later
"""Prueba de Meldra contra un Blender real.

    blender --background --factory-startup --python pruebas/prueba.py

Fabrica una malla rota igual que las que salen de un generador de IA (todos
los vertices duplicados, agujeros, basura suelta, caras invertidas y de area
cero) y comprueba que despues de reparar el Decimate ya no abre agujeros y
que los pesos automaticos de esqueleto funcionan.
"""

import ast
import glob
import os
import sys
import time
import tokenize

import bmesh
import bpy
from mathutils import Vector

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AQUI = os.path.dirname(os.path.abspath(__file__))
for _ruta in (RAIZ, AQUI):
    if _ruta not in sys.path:
        sys.path.insert(0, _ruta)

import meldra
from meldra import nucleo

FALLOS = []
PRUEBAS = 0


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


def limpiar_escena():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def leer(obj):
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    return bm


def datos(obj):
    bm = leer(obj)
    try:
        return nucleo.analizar(bm)
    finally:
        bm.free()


def malla_rota(nombre="Rota"):
    """Una esfera cerrada a la que se le hace de todo."""
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=4, radius=1.0)
    obj = bpy.context.active_object
    obj.name = nombre
    obj.scale = (1.7, 1.7, 1.7)          # escala sin aplicar, como los imports

    bm = leer(obj)

    # 1. Desoldar todo: es lo que hacen glTF/OBJ y los generadores de IA.
    bmesh.ops.split_edges(bm, edges=list(bm.edges))

    # 2. Dos agujeros de verdad.
    bm.faces.ensure_lookup_table()
    bmesh.ops.delete(bm, geom=[bm.faces[0], bm.faces[7]], context='FACES')

    # 3. Basura suelta.
    for k in range(5):
        bm.verts.new(Vector((3.0 + k * 0.1, 0.0, 0.0)))

    # 4. Un trozo flotante minusculo.
    a = bm.verts.new(Vector((5.0, 0.0, 0.0)))
    b = bm.verts.new(Vector((5.1, 0.0, 0.0)))
    c = bm.verts.new(Vector((5.0, 0.1, 0.0)))
    d = bm.verts.new(Vector((5.0, 0.0, 0.1)))
    for tri in ((a, b, c), (a, c, d), (a, d, b), (b, d, c)):
        bm.faces.new(tri)

    # 5. Una cara de area cero.
    p = bm.verts.new(Vector((0.0, 2.0, 0.0)))
    q = bm.verts.new(Vector((0.0, 2.0, 0.0)))
    r = bm.verts.new(Vector((1e-9, 2.0, 0.0)))
    try:
        bm.faces.new((p, q, r))
    except ValueError:
        pass

    # 6. Unas cuantas caras del reves.
    bm.faces.ensure_lookup_table()
    bmesh.ops.reverse_faces(bm, faces=[bm.faces[i] for i in range(3, 12)])

    bm.to_mesh(obj.data)
    obj.data.update()
    bm.free()
    return obj


def esqueleto():
    datos_arm = bpy.data.armatures.new("Esqueleto")
    arm = bpy.data.objects.new("Esqueleto", datos_arm)
    bpy.context.collection.objects.link(arm)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode='EDIT')
    h1 = datos_arm.edit_bones.new("inferior")
    h1.head = Vector((0.0, 0.0, -1.2))
    h1.tail = Vector((0.0, 0.0, 0.0))
    h2 = datos_arm.edit_bones.new("superior")
    h2.head = Vector((0.0, 0.0, 0.0))
    h2.tail = Vector((0.0, 0.0, 1.2))
    h2.parent = h1
    bpy.ops.object.mode_set(mode='OBJECT')
    return arm


def activar(obj):
    for o in bpy.context.selected_objects:
        o.select_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


# --------------------------------------------------------------------------

def prueba_diagnostico():
    titulo("Diagnostico de la malla rota")
    limpiar_escena()
    obj = malla_rota()
    d = datos(obj)
    print("  verts=%d aristas=%d caras=%d islas=%d duplicados=%d bordes=%d"
          % (d['verts'], d['aristas'], d['caras'], d['islas'],
             d['duplicados'], d['bordes']))

    comprobar(d['duplicados'] > 1000, "detecta los vertices duplicados")
    comprobar(d['islas'] > 100, "detecta que la malla esta hecha trozos")
    comprobar(d['bordes'] > 0, "detecta las aristas de borde")
    comprobar(d['v_sueltos'] == 5, "cuenta los 5 vertices sueltos")
    comprobar(d['area_cero'] >= 1, "detecta la cara de area cero")
    comprobar(not d['cerrada'], "dice que NO es una malla cerrada")
    comprobar(d['euler'] != 2, "el Euler delata el desguace")


def decimar_a_pelo(obj, ratio):
    mod = obj.modifiers.new("dec", 'DECIMATE')
    mod.ratio = ratio
    with bpy.context.temp_override(object=obj, active_object=obj,
                                   selected_objects=[obj],
                                   selected_editable_objects=[obj]):
        bpy.ops.object.modifier_apply(modifier=mod.name)


def prueba_decimate_rompe():
    """El sintoma: al mismo objetivo, decimar sin soldar destroza la superficie.

    Contar aristas de borde no vale como medida, porque una malla desoldada ya
    parte del maximo posible. Lo que se nota es que la superficie desaparece:
    cada triangulo es su propia isla y el colapso se lo lleva entero en vez de
    repartir el error con los vecinos.
    """
    titulo("Control: decimar sin soldar contra decimar soldado")
    limpiar_escena()
    roto = malla_rota("SinSoldar")
    activar(roto)
    partida = datos(roto)
    decimar_a_pelo(roto, 0.3)
    roto_dec = datos(roto)

    limpiar_escena()
    sano = malla_rota("Soldada")
    activar(sano)
    bpy.context.scene.meldra.borrar_islas = True
    bpy.ops.meldra.reparar()
    sano_pre = datos(sano)
    decimar_a_pelo(sano, 0.3)
    sano_dec = datos(sano)

    conserva_roto = roto_dec['area'] / partida['area']
    conserva_sano = sano_dec['area'] / sano_pre['area']
    print("  sin soldar : %d -> %d tris, conserva %.1f%% de superficie, "
          "bordes %d" % (partida['triangulos'], roto_dec['triangulos'],
                         conserva_roto * 100, roto_dec['bordes']))
    print("  soldada    : %d -> %d tris, conserva %.1f%% de superficie, "
          "bordes %d" % (sano_pre['triangulos'], sano_dec['triangulos'],
                         conserva_sano * 100, sano_dec['bordes']))

    comprobar(conserva_roto < 0.6,
              "sin soldar, decimar se come la superficie (sintoma reproducido)")
    comprobar(roto_dec['bordes'] > 0,
              "sin soldar, el resultado sigue lleno de agujeros")
    comprobar(conserva_sano > 0.95,
              "soldada, decimar conserva la superficie")
    comprobar(conserva_sano > conserva_roto * 1.5,
              "soldar cambia el resultado de forma clara")


def prueba_reparar():
    titulo("Reparar")
    limpiar_escena()
    obj = malla_rota()
    activar(obj)

    ajustes = bpy.context.scene.meldra
    ajustes.borrar_islas = True
    ajustes.islas_porcentaje = 1.0
    bpy.ops.meldra.reparar()

    d = datos(obj)
    print("  verts=%d caras=%d islas=%d bordes=%d volumen=%.4f"
          % (d['verts'], d['caras'], d['islas'], d['bordes'], d['volumen']))

    comprobar(d['cerrada'], "la malla queda CERRADA")
    comprobar(d['duplicados'] == 0, "no quedan vertices duplicados")
    comprobar(d['bordes'] == 0, "no quedan agujeros")
    comprobar(d['multiples'] == 0, "no quedan aristas con mas de dos caras")
    comprobar(d['v_sueltos'] == 0, "no queda geometria suelta")
    comprobar(d['area_cero'] == 0, "no quedan caras de area cero")
    comprobar(d['no_contiguas'] == 0, "las normales quedan coherentes")
    comprobar(d['volumen'] > 0, "las normales miran hacia fuera")
    comprobar(d['islas'] == 1, "queda una sola pieza")
    comprobar(d['euler'] == 2, "Euler V-E+F = 2")
    comprobar(all(abs(s - 1.0) < 1e-5 for s in obj.scale),
              "la escala queda aplicada")
    comprobar(bpy.context.scene.meldra.informe.valido,
              "el informe del panel queda relleno")
    comprobar(bpy.context.scene.meldra.informe.apto_para_rig,
              "el informe la da por apta para rig")
    return obj


def prueba_decimate_bien():
    titulo("Decimar despues de reparar")
    limpiar_escena()
    obj = malla_rota()
    activar(obj)
    ajustes = bpy.context.scene.meldra
    ajustes.borrar_islas = True
    bpy.ops.meldra.reparar()
    antes = datos(obj)

    ajustes.decimar_modo = 'RATIO'
    ajustes.decimar_ratio = 0.3
    ajustes.decimar_aplicar = True
    bpy.ops.meldra.decimar()

    d = datos(obj)
    print("  triangulos %d -> %d, bordes %d, cerrada=%s"
          % (antes['triangulos'], d['triangulos'], d['bordes'], d['cerrada']))
    comprobar(d['triangulos'] < antes['triangulos'] * 0.45,
              "el Decimate reduce de verdad")
    comprobar(d['bordes'] == 0, "SIGUE SIN AGUJEROS despues de decimar")
    comprobar(d['cerrada'], "sigue siendo una malla cerrada")

    # Y por objetivo de triangulos, sobre una malla reparada sin tocar.
    limpiar_escena()
    otro = malla_rota("PorNumero")
    activar(otro)
    ajustes = bpy.context.scene.meldra
    ajustes.borrar_islas = True
    bpy.ops.meldra.reparar()
    partida = datos(otro)['triangulos']

    ajustes.decimar_modo = 'TRIS'
    ajustes.decimar_tris = 500
    ajustes.decimar_aplicar = True
    bpy.ops.meldra.decimar()
    d2 = datos(otro)
    print("  objetivo 500: %d -> %d triangulos" % (partida, d2['triangulos']))
    comprobar(partida > 1000, "se parte de una malla sin decimar")
    comprobar(abs(d2['triangulos'] - 500) <= 20,
              "el objetivo por numero de triangulos acierta")
    comprobar(d2['cerrada'], "y sigue cerrada")


def fraccion_con_peso(obj):
    total = len(obj.data.vertices)
    if not total:
        return 0.0
    con = sum(1 for v in obj.data.vertices
              if any(g.weight > 0.0 for g in v.groups))
    return con / float(total)


def prueba_rig():
    titulo("Esqueleto con pesos automaticos")
    limpiar_escena()
    arm = esqueleto()

    # Camino malo: la malla tal cual sale del generador.
    roto = malla_rota("SinReparar")
    activar(roto)
    roto.select_set(True)
    arm.select_set(True)
    bpy.context.view_layer.objects.active = arm
    try:
        bpy.ops.object.parent_set(type='ARMATURE_AUTO')
        antes = fraccion_con_peso(roto)
        print("  sin reparar: %.1f%% de vertices con peso" % (antes * 100))
    except RuntimeError as ex:
        antes = 0.0
        print("  sin reparar: falla del todo (%s)" % str(ex)[:70])
    comprobar(antes < 0.5,
              "sin reparar, los pesos automaticos no cubren la malla")

    # Camino bueno: una copia limpia del mismo desastre.
    obj = malla_rota("Reparada")
    activar(obj)
    ajustes = bpy.context.scene.meldra
    ajustes.borrar_islas = True
    ajustes.rig_origen = 'SIN'
    bpy.ops.meldra.preparar_rig()
    comprobar(bpy.context.scene.meldra.informe.apto_para_rig,
              "despues de preparar, el informe la da por apta")

    activar(obj)
    ajustes.armadura = arm
    bpy.ops.meldra.emparentar()

    comprobar(obj.parent is arm, "la malla queda emparentada a la armadura")
    comprobar(any(m.type == 'ARMATURE' for m in obj.modifiers),
              "tiene modificador Armature")
    nombres = {g.name for g in obj.vertex_groups}
    comprobar({"inferior", "superior"} <= nombres,
              "se crearon los grupos de vertices de cada hueso")
    pesados = 0
    for v in obj.data.vertices:
        if any(g.weight > 0.0 for g in v.groups):
            pesados += 1
    print("  vertices con peso: %d de %d" % (pesados, len(obj.data.vertices)))
    comprobar(pesados > len(obj.data.vertices) * 0.9,
              "los pesos automaticos cubren la malla")


def prueba_varias_mallas():
    """El panel anuncia que actua sobre todo lo seleccionado."""
    titulo("Varias mallas a la vez")
    limpiar_escena()
    a = malla_rota("UnaA")
    b = malla_rota("UnaB")
    b.location = (12.0, 0.0, 0.0)

    for o in bpy.context.selected_objects:
        o.select_set(False)
    a.select_set(True)
    b.select_set(True)
    bpy.context.view_layer.objects.active = a

    bpy.context.scene.meldra.borrar_islas = True
    bpy.ops.meldra.reparar()

    da, db = datos(a), datos(b)
    print("  A: verts=%d cerrada=%s | B: verts=%d cerrada=%s"
          % (da['verts'], da['cerrada'], db['verts'], db['cerrada']))
    comprobar(da['cerrada'] and db['cerrada'],
              "repara las dos mallas seleccionadas")
    comprobar(abs(b.location.x - 12.0) < 1e-5,
              "aplicar la escala no mueve el objeto de sitio")


def prueba_decimate_sin_aplicar():
    titulo("Decimar sin aplicar el modificador")
    limpiar_escena()
    obj = malla_rota()
    activar(obj)
    ajustes = bpy.context.scene.meldra
    ajustes.borrar_islas = True
    bpy.ops.meldra.reparar()
    antes = datos(obj)['triangulos']

    ajustes.decimar_modo = 'RATIO'
    ajustes.decimar_ratio = 0.25
    ajustes.decimar_aplicar = False
    bpy.ops.meldra.decimar()

    mods = [m for m in obj.modifiers if m.type == 'DECIMATE']
    comprobar(len(mods) == 1, "queda el modificador Decimate puesto")
    comprobar(mods and abs(mods[0].ratio - 0.25) < 1e-6,
              "con la proporcion pedida")
    comprobar(datos(obj)['triangulos'] == antes,
              "y la malla base sigue sin tocar")
    ajustes.decimar_aplicar = True


def prueba_seleccionar():
    titulo("Botones de ver el problema")
    limpiar_escena()
    obj = malla_rota()
    activar(obj)
    for tipo in ('DUPLICADOS', 'BORDES', 'NOMANIFOLD', 'INTERIORES',
                 'AREA_CERO', 'SUELTOS', 'INVERTIDAS', 'NGONS', 'ISLAS'):
        try:
            bpy.ops.meldra.seleccionar(tipo=tipo)
            bpy.ops.object.mode_set(mode='OBJECT')
            n = sum(1 for v in obj.data.vertices if v.select)
            print("  %-12s %d vertices seleccionados" % (tipo, n))
            comprobar(True, "seleccionar %s no revienta" % tipo)
        except Exception as ex:
            comprobar(False, "seleccionar %s: %s" % (tipo, ex))
    bpy.ops.object.mode_set(mode='OBJECT')


def prueba_remesh():
    titulo("Reconstruir por voxeles")
    limpiar_escena()
    obj = malla_rota()
    activar(obj)
    bpy.context.scene.meldra.voxel_detalle = 80
    bpy.ops.meldra.remesh_voxel()
    d = datos(obj)
    print("  %d triangulos, cerrada=%s" % (d['triangulos'], d['cerrada']))
    comprobar(d['cerrada'], "el remesh por voxeles sale cerrado")
    comprobar(d['duplicados'] == 0, "y sin duplicados")


def desde_bmesh(bm, nombre):
    me = bpy.data.meshes.new(nombre)
    bm.to_mesh(me)
    bm.free()
    obj = bpy.data.objects.new(nombre, me)
    bpy.context.collection.objects.link(obj)
    return obj


def icoesfera(subdivisiones=3, radio=1.0):
    bm = bmesh.new()
    bmesh.ops.create_icosphere(bm, subdivisions=subdivisiones, radius=radio)
    return bm


def malla_con_aleta():
    """Una esfera cerrada con una cara de mas colgando de una arista."""
    bm = icoesfera()
    bm.edges.ensure_lookup_table()
    a, b = bm.edges[0].verts
    punta = bm.verts.new((a.co + b.co) * 0.5 + Vector((0.0, 0.0, 0.9)))
    bm.faces.new((a, b, punta))
    return desde_bmesh(bm, "Aleta")


def malla_con_alambre():
    """Una esfera cerrada con una arista de alambre entre dos vertices suyos."""
    bm = icoesfera()
    bm.verts.ensure_lookup_table()
    bm.edges.new((bm.verts[0], bm.verts[10]))
    return desde_bmesh(bm, "Alambre")


def malla_dos_cubos():
    """Dos cubos cerrados que se tocan justo en una arista."""
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=2.0)
    otro = bmesh.new()
    bmesh.ops.create_cube(otro, size=2.0)
    bmesh.ops.translate(otro, verts=list(otro.verts),
                        vec=Vector((2.0, 2.0, 0.0)))
    me = bpy.data.meshes.new("temporal")
    otro.to_mesh(me)
    otro.free()
    bm.from_mesh(me)
    bpy.data.meshes.remove(me)
    return desde_bmesh(bm, "DosCubos")


def malla_con_pincho():
    """Una esfera cerrada con dos triangulos sueltos colgando de un vertice.

    Es la forma exacta del golem que salia de un generador: la malla esta entera
    salvo por unas caras huerfanas que tocan el cuerpo en un solo punto. Sus tres
    aristas son de borde, asi que el "agujero" es la propia cara y no hay nada que
    rellenar: faces.new() contesta que la cara ya existe.
    """
    bm = icoesfera()
    bm.verts.ensure_lookup_table()
    raices = [bm.verts[0], bm.verts[20]]
    for raiz in raices:
        a = bm.verts.new(raiz.co * 1.4 + Vector((0.10, 0.0, 0.0)))
        b = bm.verts.new(raiz.co * 1.4 + Vector((0.0, 0.10, 0.0)))
        bm.faces.new((raiz, a, b))
    return desde_bmesh(bm, "Pincho")


def malla_muro_interior():
    """Un cubo cerrado con un tabique dentro pegado a una de sus aristas."""
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=2.0)
    bm.faces.ensure_lookup_table()
    tapa = [f for f in bm.faces if f.calc_center_median().z > 0.9][0]
    arriba = list(tapa.verts)
    abajo = [bm.verts.new(v.co - Vector((0.0, 0.0, 2.0))) for v in arriba]
    for i in range(4):
        j = (i + 1) % 4
        bm.faces.new((arriba[i], arriba[j], abajo[j], abajo[i]))
    return desde_bmesh(bm, "MuroInterior")


def reparar_sola(obj):
    activar(obj)
    bpy.ops.meldra.reparar()
    return datos(obj)


def prueba_no_manifold():
    titulo("Geometria no manifold")

    # 1. La aleta: una cara pegada a una arista que ya tenia dos.
    limpiar_escena()
    aleta = malla_con_aleta()
    antes = datos(aleta)
    comprobar(antes['multiples'] == 1 and antes['bordes'] == 2,
              "la aleta deja una arista con tres caras y dos bordes")
    d = reparar_sola(aleta)
    print("  aleta    : bordes=%d multi=%d cerrada=%s"
          % (d['bordes'], d['multiples'], d['cerrada']))
    comprobar(d['cerrada'], "reparar arranca la aleta y CIERRA la malla")
    comprobar(d['multiples'] == 0, "no queda ninguna arista con mas de dos caras")
    comprobar(d['volumen'] > 0, "y el volumen sigue saliendo hacia fuera")

    # 2. El alambre pegado a la superficie, que barrer_basura no veia.
    limpiar_escena()
    alambre = malla_con_alambre()
    antes = datos(alambre)
    comprobar(antes['alambre'] == 1,
              "el alambre entre dos vertices con cara se detecta")
    d = reparar_sola(alambre)
    print("  alambre  : alambre=%d nomanifold=%d cerrada=%s"
          % (d['alambre'], d['v_nomanifold'], d['cerrada']))
    comprobar(d['alambre'] == 0, "reparar borra la arista de alambre")
    comprobar(d['cerrada'], "y la malla vuelve a estar CERRADA")

    # 3. Dos cubos que se tocan: soldar los unia y rompia lo que estaba bien.
    limpiar_escena()
    cubos = malla_dos_cubos()
    antes = datos(cubos)
    comprobar(antes['cerrada'], "los dos cubos entran cerrados")
    d = reparar_sola(cubos)
    print("  dos cubos: multi=%d nomanifold=%d islas=%d volumen=%.2f"
          % (d['multiples'], d['v_nomanifold'], d['islas'], d['volumen']))
    comprobar(d['cerrada'], "y SIGUEN cerrados despues de reparar")
    comprobar(d['multiples'] == 0,
              "soldar no deja la arista comun con cuatro caras")
    comprobar(d['v_nomanifold'] == 0, "ni vertices no manifold")
    comprobar(d['islas'] == 2, "siguen siendo dos piezas")
    comprobar(abs(d['volumen'] - 16.0) < 1e-4,
              "y conservan los 16 de volumen entre los dos")

    # 4. El tabique interior sale y el cubo queda limpio.
    limpiar_escena()
    muro = malla_muro_interior()
    d = reparar_sola(muro)
    print("  muro     : caras=%d cerrada=%s volumen=%.2f"
          % (d['caras'], d['cerrada'], d['volumen']))
    comprobar(d['cerrada'], "el cubo con tabique queda CERRADO")
    comprobar(d['caras'] == 6, "el tabique se va y quedan las seis caras")
    comprobar(abs(d['volumen'] - 8.0) < 1e-4, "con su volumen de 8")

    # 5. Un vertice donde se tocan dos conos cerrados: se separa en dos.
    limpiar_escena()
    bm = bmesh.new()
    centro = bm.verts.new(Vector((0.0, 0.0, 0.0)))
    for signo in (1.0, -1.0):
        anillo = [bm.verts.new((1.0 * signo, 0.0, 1.0 * signo)),
                  bm.verts.new((0.0, 1.0 * signo, 1.0 * signo)),
                  bm.verts.new((-1.0 * signo, 0.0, 1.0 * signo)),
                  bm.verts.new((0.0, -1.0 * signo, 1.0 * signo))]
        for i in range(4):
            bm.faces.new((centro, anillo[i], anillo[(i + 1) % 4]))
        bm.faces.new(anillo)
    pajarita = desde_bmesh(bm, "Pajarita")
    antes = datos(pajarita)
    comprobar(antes['v_nomanifold'] == 1, "detecta el vertice no manifold")
    d = reparar_sola(pajarita)
    print("  pajarita : nomanifold=%d islas=%d cerrada=%s"
          % (d['v_nomanifold'], d['islas'], d['cerrada']))
    comprobar(d['v_nomanifold'] == 0, "reparar separa el vertice compartido")
    comprobar(d['islas'] == 2, "y deja los dos conos como dos piezas")
    comprobar(d['cerrada'], "las dos siguen cerradas")

    # 5b. Y separarlo no deja alambre suelto ni con la limpieza desmarcada.
    limpiar_escena()
    otra = malla_dos_cubos()
    bpy.context.scene.meldra.borrar_sueltos = False
    d = reparar_sola(otra)
    bpy.context.scene.meldra.borrar_sueltos = True
    print("  sin barrer: alambre=%d cerrada=%s" % (d['alambre'], d['cerrada']))
    comprobar(d['alambre'] == 0,
              "separar no deja alambre aunque no se barra la basura")
    comprobar(d['cerrada'], "y los cubos quedan cerrados igual")

    # 6. Todo a la vez sobre una malla desoldada, como las de los generadores.
    limpiar_escena()
    bm = icoesfera(subdivisiones=4)
    bmesh.ops.split_edges(bm, edges=list(bm.edges))
    bm.faces.ensure_lookup_table()
    bmesh.ops.delete(bm, geom=[bm.faces[0], bm.faces[9], bm.faces[40]],
                     context='FACES')
    for k in range(6):
        bm.verts.new(Vector((4.0 + k * 0.2, 0.0, 0.0)))
    bm.verts.ensure_lookup_table()
    bm.edges.new((bm.verts[0], bm.verts[30]))
    bm.edges.ensure_lookup_table()
    x, y = bm.edges[5].verts
    punta = bm.verts.new((x.co + y.co) * 0.5 + Vector((0.0, 0.0, 1.1)))
    bm.faces.new((x, y, punta))
    revuelta = desde_bmesh(bm, "Revuelta")
    d = reparar_sola(revuelta)
    print("  revuelta : bordes=%d multi=%d alambre=%d islas=%d cerrada=%s"
          % (d['bordes'], d['multiples'], d['alambre'], d['islas'],
             d['cerrada']))
    comprobar(d['cerrada'], "la malla con todos los males a la vez CIERRA")
    comprobar(d['bordes'] == 0 and d['multiples'] == 0 and d['alambre'] == 0,
              "sin agujeros, sin aristas multiples y sin alambre")
    comprobar(bpy.context.scene.meldra.informe.apto_para_rig,
              "y el informe la da por apta para rig")

    # 7. El caso del golem: caras huerfanas colgando de un solo vertice.
    limpiar_escena()
    pincho = malla_con_pincho()
    antes = datos(pincho)
    caras_buenas = antes['caras'] - 2
    comprobar(antes['bordes'] == 6 and not antes['cerrada'],
              "los dos triangulos huerfanos dejan 6 aristas de borde")
    comprobar(antes['islas'] == 1,
              "tocan el cuerpo por un vertice, asi que cuentan como una pieza")
    d = reparar_sola(pincho)
    print("  pincho   : caras=%d bordes=%d islas=%d cerrada=%s"
          % (d['caras'], d['bordes'], d['islas'], d['cerrada']))
    comprobar(d['cerrada'], "reparar quita los huerfanos y CIERRA la malla")
    comprobar(d['caras'] == caras_buenas,
              "se van las dos caras sueltas y no se toca ninguna mas")
    comprobar(d['islas'] == 1 and d['volumen'] > 0,
              "queda una sola pieza con volumen hacia fuera")

    # 8. Pero una malla plana entera no se borra por parecer una hoja suelta.
    limpiar_escena()
    bpy.ops.mesh.primitive_plane_add()
    plano = bpy.context.active_object
    d = reparar_sola(plano)
    comprobar(d['caras'] == 1,
              "el guardarrail salva la malla plana de una sola cara")


def parche_con_diagonal_ocupada():
    """Un parche de cuatro lados cuyas DOS diagonales ya existen en la malla.

    Triangular ese parche a la brava tiene que elegir una de las dos diagonales,
    y la arista que elija ya tenia sus dos caras: se queda con tres. Es lo que
    pasaba al rellenar agujeros de mallas importadas de verdad.
    """
    bm = bmesh.new()
    a = bm.verts.new(Vector((-1.0, -1.0, 0.0)))
    b = bm.verts.new(Vector((1.0, -1.0, 0.0)))
    c = bm.verts.new(Vector((1.0, 1.0, 0.0)))
    d = bm.verts.new(Vector((-1.0, 1.0, 0.0)))
    arriba = bm.verts.new(Vector((0.0, 0.0, 1.0)))
    abajo = bm.verts.new(Vector((0.0, 0.0, -1.0)))
    parche = bm.faces.new((a, b, c, d))
    for x, y in ((a, c), (b, d)):
        bm.faces.new((x, y, arriba))
        bm.faces.new((y, x, abajo))
    return bm, parche


def aristas_multiples(bm):
    return sum(1 for e in bm.edges if len(e.link_faces) > 2)


def prueba_triangular_parches():
    titulo("Triangular los parches sin romper la malla")

    bm, parche = parche_con_diagonal_ocupada()
    comprobar(aristas_multiples(bm) == 0,
              "de partida ninguna arista tiene mas de dos caras")
    bmesh.ops.triangulate(bm, faces=[parche])
    a_la_brava = aristas_multiples(bm)
    print("  bmesh.ops.triangulate deja %d aristas con mas de dos caras"
          % a_la_brava)
    comprobar(a_la_brava > 0,
              "triangular a la brava reutiliza una diagonal ya ocupada")
    bm.free()

    bm, parche = parche_con_diagonal_ocupada()
    caras_antes = len(bm.faces)
    hechas = nucleo.triangular_en_abanico(bm, [parche])
    print("  triangular_en_abanico deja %d aristas con mas de dos caras, "
          "%d triangulos" % (aristas_multiples(bm), hechas))
    comprobar(aristas_multiples(bm) == 0,
              "en abanico NO se crea ninguna arista con mas de dos caras")
    comprobar(hechas == 4, "el parche de cuatro lados sale en cuatro triangulos")
    comprobar(len(bm.faces) == caras_antes + 3,
              "y el parche queda cubierto, no borrado")
    comprobar(all(len(f.verts) == 3 for f in bm.faces),
              "no queda ningun n-gon")
    bm.free()

    # Y de punta a punta: una esfera con un agujero se cierra y se triangula
    # sin dejar geometria no manifold.
    limpiar_escena()
    bm = icoesfera(subdivisiones=3)
    bm.faces.ensure_lookup_table()
    fuera = [f for f in bm.faces if f.calc_center_median().z > 0.55]
    bmesh.ops.delete(bm, geom=fuera, context='FACES')
    obj = desde_bmesh(bm, "ConAgujero")
    d = reparar_sola(obj)
    print("  esfera agujereada: caras=%d bordes=%d multi=%d ngons=%d cerrada=%s"
          % (d['caras'], d['bordes'], d['multiples'], d['ngons'], d['cerrada']))
    comprobar(d['cerrada'] and d['multiples'] == 0,
              "el agujero se tapa sin dejar aristas con mas de dos caras")
    comprobar(d['ngons'] == 0, "y el parche queda triangulado")


def bloque_de_cubos(celdas, nombre):
    """Cada celda es un cubo cerrado independiente, pegado cara con cara.

    Es lo que queda tras un Ctrl+J sobre un modelo blocky, un kitbash de cajas
    o un export de voxeles. Entra estanco de verdad, asi que reparar no tiene
    derecho a tocarlo.
    """
    bm = bmesh.new()
    for (i, j, k) in sorted(set(celdas)):
        cubo = bmesh.new()
        bmesh.ops.create_cube(cubo, size=1.0)
        bmesh.ops.translate(cubo, verts=cubo.verts, vec=(i, j, k))
        me = bpy.data.meshes.new("temporal")
        cubo.to_mesh(me)
        cubo.free()
        bm.from_mesh(me)
        bpy.data.meshes.remove(me)
    return desde_bmesh(bm, nombre)


def malla_pajarita_con_uv():
    """Dos conos pegados por la punta, con UVs en todas las caras."""
    bm = bmesh.new()
    centro = bm.verts.new(Vector((0.0, 0.0, 0.0)))
    for signo in (1.0, -1.0):
        anillo = [bm.verts.new((1.0 * signo, 0.0, 1.0 * signo)),
                  bm.verts.new((0.0, 1.0 * signo, 1.0 * signo)),
                  bm.verts.new((-1.0 * signo, 0.0, 1.0 * signo)),
                  bm.verts.new((0.0, -1.0 * signo, 1.0 * signo))]
        for i in range(4):
            bm.faces.new((centro, anillo[i], anillo[(i + 1) % 4]))
        bm.faces.new(anillo)
    capa = bm.loops.layers.uv.new("UVMap")
    for n, f in enumerate(bm.faces):
        for m, bucle in enumerate(f.loops):
            bucle[capa].uv = (0.05 * (n + 1), 0.05 * (m + 1))
    return desde_bmesh(bm, "PajaritaUV")


def prueba_no_destruir():
    titulo("Reparar no puede empeorar lo que ya estaba bien")

    # 1. Un solido de cubos soldados: al soldar salen tabiques internos, y
    #    separar los vertices sin mas lo desintegraba en parches sueltos.
    for nombre, celdas in (
            ("3x3x3", [(i, j, k) for i in range(3) for j in range(3)
                       for k in range(3)]),
            ("losa 5x5", [(i, j, 0) for i in range(5) for j in range(5)]),
            ("ele", [(i, 0, 0) for i in range(4)]
             + [(0, j, 0) for j in range(4)] + [(0, 0, k) for k in range(4)])):
        limpiar_escena()
        obj = bloque_de_cubos(celdas, nombre)
        antes = datos(obj)
        d = reparar_sola(obj)
        print("  %-9s caras %d -> %d, islas %d -> %d, volumen %.1f -> %.1f"
              % (nombre, antes['caras'], d['caras'], antes['islas'],
                 d['islas'], antes['volumen'], d['volumen']))
        comprobar(antes['cerrada'], "%s: entra cerrado" % nombre)
        comprobar(d['cerrada'], "%s: y SIGUE cerrado" % nombre)
        comprobar(d['bordes'] == 0, "%s: sin aristas de borde" % nombre)
        comprobar(abs(d['volumen'] - antes['volumen']) < 1e-3,
                  "%s: conserva el volumen entero" % nombre)
        comprobar(d['islas'] == 1, "%s: queda de una pieza" % nombre)

    # 2. Separar un vertice no manifold no puede llevarse las UVs por delante.
    limpiar_escena()
    obj = malla_pajarita_con_uv()
    antes_uv = sorted(tuple(d.uv) for d in obj.data.uv_layers.active.data)
    antes = datos(obj)
    d = reparar_sola(obj)
    despues_uv = sorted(tuple(x.uv) for x in obj.data.uv_layers.active.data)
    print("  UVs: %d bucles antes, %d despues" % (len(antes_uv),
                                                  len(despues_uv)))
    comprobar(antes['v_nomanifold'] == 1 and d['v_nomanifold'] == 0,
              "el vertice no manifold se separa")
    comprobar(despues_uv == antes_uv,
              "y las UVs salen exactamente iguales, ni una a cero")

    # 3. Un vertice tirado lejos dispara la diagonal, y con ella el umbral de
    #    soldado y el de area cero: antes se comia la malla entera.
    for lejos in (0.0, 20000.0, 1000000.0):
        limpiar_escena()
        bpy.ops.mesh.primitive_uv_sphere_add(segments=32, ring_count=16)
        obj = bpy.context.active_object
        if lejos:
            obj.data.vertices[0].co.x = lejos
        antes = datos(obj)
        d = reparar_sola(obj)
        print("  vertice a x=%-9.0f area_cero=%d, caras %d -> %d, volumen %.4f"
              % (lejos, antes['area_cero'], antes['caras'], d['caras'],
                 d['volumen']))
        comprobar(antes['area_cero'] == 0,
                  "x=%.0f: no se inventa caras de area cero" % lejos)
        comprobar(d['caras'] == antes['caras'],
                  "x=%.0f: no pierde ni una cara" % lejos)
        comprobar(d['volumen'] > 4.0,
                  "x=%.0f: la esfera sigue entera" % lejos)

    # 4. Y el coste no puede dispararse con el numero de parches.
    limpiar_escena()
    bm = icoesfera(subdivisiones=5)
    bmesh.ops.split_edges(bm, edges=list(bm.edges))
    bm.faces.ensure_lookup_table()
    bmesh.ops.delete(bm, geom=[bm.faces[i] for i in range(0, len(bm.faces), 11)],
                     context='FACES')
    obj = desde_bmesh(bm, "MuchosAgujeros")
    antes = datos(obj)
    reloj = time.time()
    d = reparar_sola(obj)
    tardo = time.time() - reloj
    print("  %d vertices y %d aristas de borde reparadas en %.2fs"
          % (antes['verts'], antes['bordes'], tardo))
    comprobar(d['cerrada'], "la malla grande y agujereada cierra")
    comprobar(tardo < 30.0,
              "y tarda menos de 30 segundos (%.2fs)" % tardo)


def prueba_costuras():
    """El caso de exportar a glTF: el formato parte los vertices de costura.

    En glTF un vertice ES posicion mas UV, asi que un vertice que este sobre
    una costura del mapa UV se duplica al exportar. Al reabrir, la malla llega
    con las costuras despegadas y parece agujereada, cuando en realidad basta
    soldarla. El informe tiene que saber distinguir eso de un agujero real.
    """
    titulo("Costuras despegadas contra agujeros de verdad")

    # 1. Una esfera cerrada a la que se le despegan unas costuras.
    limpiar_escena()
    bm = icoesfera(subdivisiones=3)
    bm.edges.ensure_lookup_table()
    bmesh.ops.split_edges(bm, edges=[bm.edges[i]
                                     for i in range(0, len(bm.edges), 5)])
    obj = desde_bmesh(bm, "Costuras")
    d = datos(obj)
    print("  costuras : duplicados=%d bordes=%d cerrada=%s cierra_al_soldar=%s"
          % (d['duplicados'], d['bordes'], d['cerrada'],
             d['cerrada_al_soldar']))
    comprobar(not d['cerrada'] and d['bordes'] > 0,
              "la malla despegada no esta cerrada")
    comprobar(d['duplicados'] > 0, "y se ven los vertices duplicados")
    comprobar(d['cerrada_al_soldar'],
              "pero el informe sabe que soldando queda cerrada")
    d = reparar_sola(obj)
    comprobar(d['cerrada'], "y reparar la cierra de verdad")

    # 2. Un agujero de verdad no se arregla soldando, y el informe no miente.
    limpiar_escena()
    bm = icoesfera(subdivisiones=3)
    bm.faces.ensure_lookup_table()
    bmesh.ops.delete(bm, geom=[f for f in bm.faces
                               if f.calc_center_median().z > 0.55],
                     context='FACES')
    agujero = desde_bmesh(bm, "Agujero")
    d = datos(agujero)
    print("  agujero  : duplicados=%d bordes=%d cerrada=%s cierra_al_soldar=%s"
          % (d['duplicados'], d['bordes'], d['cerrada'],
             d['cerrada_al_soldar']))
    comprobar(not d['cerrada'] and not d['cerrada_al_soldar'],
              "un agujero de verdad no se cierra soldando")

    # 3. Una malla ya cerrada sigue contando como cerrada al soldar.
    limpiar_escena()
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=3)
    d = datos(bpy.context.active_object)
    comprobar(d['cerrada'] and d['cerrada_al_soldar'],
              "una malla sana cumple las dos cosas")

    # 4. Y el veredicto del panel dice las tres cosas distintas.
    from meldra import ui
    fuente = open(os.path.join(RAIZ, "meldra", "ui.py"),
                  encoding="utf-8").read()
    for texto in ("Watertight mesh", "Watertight once welded",
                  "Not watertight"):
        comprobar('text="%s"' % texto in fuente,
                  "el panel puede decir %r" % texto)
    comprobar(ui.MELDRA_PT_principal is not None, "el panel sigue registrado")


def prueba_casos_limite():
    titulo("Casos limite")
    limpiar_escena()

    # Malla vacia.
    me = bpy.data.meshes.new("Vacia")
    obj = bpy.data.objects.new("Vacia", me)
    bpy.context.collection.objects.link(obj)
    activar(obj)
    try:
        d = datos(obj)
        comprobar(d['verts'] == 0 and not d['cerrada'],
                  "analizar una malla vacia no revienta")
        bpy.ops.meldra.reparar()
        comprobar(True, "reparar una malla vacia no revienta")
    except Exception as ex:
        comprobar(False, "malla vacia: %s" % ex)

    # Un plano: abierto por definicion, no debe cerrarse a lo loco.
    limpiar_escena()
    bpy.ops.mesh.primitive_plane_add()
    plano = bpy.context.active_object
    activar(plano)
    bpy.ops.meldra.reparar()
    d = datos(plano)
    print("  plano tras reparar: caras=%d bordes=%d" % (d['caras'], d['bordes']))
    comprobar(d['caras'] >= 1, "el plano sobrevive a la reparacion")

    # Cubo sano: reparar no debe cambiarlo.
    limpiar_escena()
    bpy.ops.mesh.primitive_cube_add()
    cubo = bpy.context.active_object
    activar(cubo)
    antes = datos(cubo)
    bpy.ops.meldra.reparar()
    despues = datos(cubo)
    comprobar(antes['verts'] == despues['verts'] == 8,
              "un cubo sano sale intacto de la reparacion")
    comprobar(despues['cerrada'] and despues['volumen'] > 0,
              "el cubo sigue cerrado y con normales fuera")

    # Malla con todas las normales del reves.
    limpiar_escena()
    bpy.ops.mesh.primitive_uv_sphere_add()
    esfera = bpy.context.active_object
    bm = leer(esfera)
    bmesh.ops.reverse_faces(bm, faces=list(bm.faces))
    bm.to_mesh(esfera.data)
    bm.free()
    activar(esfera)
    comprobar(datos(esfera)['invertida'], "detecta la malla del reves")
    bpy.ops.meldra.reparar()
    comprobar(datos(esfera)['volumen'] > 0, "y le da la vuelta")


def prueba_panel():
    """El panel no se puede dibujar en segundo plano, asi que se revisan a
    mano los dos motivos por los que suele reventar: iconos y propiedades."""
    titulo("Panel: iconos y propiedades")
    import re

    ruta = os.path.join(RAIZ, "meldra", "ui.py")
    with open(ruta, encoding="utf-8") as fh:
        fuente = fh.read()

    iconos = set(re.findall(r"icon='([A-Z0-9_]+)'", fuente))
    validos = {e.identifier for e in
               bpy.types.UILayout.bl_rna.functions['prop']
               .parameters['icon'].enum_items}
    malos = sorted(iconos - validos)
    print("  iconos usados: %s" % ", ".join(sorted(iconos)))
    comprobar(not malos, "todos los iconos existen%s"
              % ("" if not malos else " (fallan: %s)" % malos))

    propiedades = set(re.findall(r'\.prop\(a,\s*"([a-z_]+)"', fuente))
    ajustes = bpy.context.scene.meldra
    faltan = sorted(p for p in propiedades if p not in ajustes.bl_rna.properties)
    print("  propiedades pintadas: %d" % len(propiedades))
    comprobar(not faltan, "todas las propiedades del panel existen%s"
              % ("" if not faltan else " (faltan: %s)" % faltan))

    informe = ajustes.informe
    campos = set(re.findall(r"\bi\.([a-z_]+)", fuente))
    faltan_i = sorted(c for c in campos
                      if c not in informe.bl_rna.properties
                      and not hasattr(informe, c))
    comprobar(not faltan_i, "todos los campos del informe existen%s"
              % ("" if not faltan_i else " (faltan: %s)" % faltan_i))

    ids = {c.bl_idname for c in meldra.ops.CLASES} | {"wm.url_open"}
    usados = set(re.findall(r'operator\("([a-z_.]+)"', fuente))
    comprobar(usados <= ids, "todos los operadores del panel estan registrados"
              " (sobran: %s)" % sorted(usados - ids))


def prueba_idiomas():
    titulo("Idiomas")
    import idiomas as revisor

    claves, esperados, presentes, fallos = revisor.revisar()
    print("  %d cadenas x %d idiomas = %d entradas"
          % (len(claves), len(presentes),
             sum(len(v) for v in meldra.idiomas.TRADUCCIONES.values())))
    comprobar(not (esperados - presentes),
              "cubre los %d idiomas que Blender sabe mostrar" % len(esperados))
    comprobar(not fallos, "ningun idioma tiene claves de mas, de menos ni "
                          "marcadores de formato descuadrados%s"
              % ("" if not fallos else ": %s" % fallos[:2]))


def prueba_traduccion_viva():
    """Que el sistema de traduccion de Blender realmente devuelva el texto."""
    titulo("Traduccion en vivo")
    vista = bpy.context.preferences.view
    antes_idioma = vista.language
    antes_activo = vista.use_translate_interface
    muestras = (
        ("es", "Repair All", "Reparar todo"),
        ("fr_FR", "Repair All", "Tout réparer"),
        ("de_DE", "Watertight mesh", "Geschlossenes Mesh"),
        ("ja_JP", "Repair All", "すべて修復"),
        ("ar_EG", "Repair All", "إصلاح الكل"),
        ("zh_HANS", "Analyze Mesh", "分析网格"),
        ("es", "Watertight once welded", "Cerrada al soldar"),
        ("pl_PL", "Watertight once welded", "Zamknięta po scaleniu"),
        ("ko_KR", "Watertight once welded", "병합하면 닫힘"),
    )
    try:
        vista.use_translate_interface = True
        for codigo, original, esperado in muestras:
            vista.language = codigo
            obtenido = bpy.app.translations.pgettext_iface(original)
            comprobar(obtenido == esperado,
                      "%s: %r -> %r" % (codigo, original, obtenido))
    finally:
        vista.language = antes_idioma
        vista.use_translate_interface = antes_activo


def prueba_estilo():
    """El add-on se distribuye sin comentarios ni docstrings, a peticion."""
    titulo("Estilo del codigo distribuido")
    fuentes = sorted(glob.glob(os.path.join(RAIZ, "meldra", "**", "*.py"),
                               recursive=True))
    comprobar(len(fuentes) >= 6, "hay %d ficheros que revisar" % len(fuentes))

    con_comentario = []
    con_docstring = []
    for ruta in fuentes:
        with open(ruta, "rb") as fh:
            for pieza in tokenize.tokenize(fh.readline):
                if pieza.type == tokenize.COMMENT:
                    con_comentario.append("%s:%d"
                                          % (os.path.basename(ruta),
                                             pieza.start[0]))
        with open(ruta, encoding="utf-8") as fh:
            arbol = ast.parse(fh.read())
        for nodo in ast.walk(arbol):
            if isinstance(nodo, (ast.Module, ast.FunctionDef, ast.ClassDef,
                                 ast.AsyncFunctionDef)):
                if ast.get_docstring(nodo):
                    con_docstring.append(os.path.basename(ruta))
                    break

    comprobar(not con_comentario,
              "ningun comentario%s" % ("" if not con_comentario
                                       else ": %s" % con_comentario[:4]))
    comprobar(not con_docstring,
              "ningun docstring%s" % ("" if not con_docstring
                                      else ": %s" % sorted(set(con_docstring))))


def prueba_creditos():
    titulo("Creditos")
    from meldra import ui, version
    redes = dict(ui.REDES)
    comprobar(redes.get("Instagram", "").endswith("/xander.dice"),
              "Instagram apunta a xander.dice")
    comprobar(redes.get("YouTube", "").endswith("/@xanderdice"),
              "YouTube apunta a @xanderdice")
    comprobar(redes.get("Facebook", "").endswith("/djxanderdice"),
              "Facebook apunta a djxanderdice")
    comprobar(all(u.startswith("https://") for u in redes.values()),
              "todos los enlaces son https")
    comprobar(version.NUMERO and version.NUMERO[0].isdigit(),
              "la version sale del manifiesto: %r" % version.NUMERO)
    manifiesto = open(os.path.join(RAIZ, "meldra", "blender_manifest.toml"),
                      encoding="utf-8").read()
    comprobar('maintainer = "xander.dice"' in manifiesto,
              "el manifiesto acredita a xander.dice")


def main():
    print("Blender %s" % bpy.app.version_string)
    meldra.register()
    try:
        prueba_diagnostico()
        prueba_decimate_rompe()
        prueba_reparar()
        prueba_no_manifold()
        prueba_triangular_parches()
        prueba_no_destruir()
        prueba_costuras()
        prueba_decimate_bien()
        prueba_decimate_sin_aplicar()
        prueba_varias_mallas()
        prueba_seleccionar()
        prueba_rig()
        prueba_remesh()
        prueba_casos_limite()
        prueba_panel()
        prueba_idiomas()
        prueba_traduccion_viva()
        prueba_estilo()
        prueba_creditos()
    finally:
        meldra.unregister()

    print("\n" + "=" * 64)
    if FALLOS:
        print("%d FALLOS de %d comprobaciones:" % (len(FALLOS), PRUEBAS))
        for f in FALLOS:
            print("  - %s" % f)
        sys.exit(1)
    print("Las %d comprobaciones pasan." % PRUEBAS)
    sys.exit(0)


if __name__ == "__main__":
    main()
