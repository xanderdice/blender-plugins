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
