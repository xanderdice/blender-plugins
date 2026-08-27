from __future__ import annotations

import bmesh
import bpy
from bpy.app.translations import pgettext_iface as _
from bpy.props import EnumProperty
from bpy.types import Operator
from mathutils import Vector
from mathutils.kdtree import KDTree

from . import nucleo, props

PROBLEMAS = (
    ('DUPLICADOS', "Duplicates", "Vertices sitting on top of another"),
    ('BORDES', "Holes", "Edges with a single face"),
    ('NOMANIFOLD', "Non-manifold", "Edges with over two faces, and wire edges"),
    ('INTERIORES', "Interior", "Faces of the inner shell"),
    ('AREA_CERO', "Zero area", "Degenerate faces"),
    ('SUELTOS', "Loose", "Vertices that belong to no face"),
    ('INVERTIDAS', "Flipped", "Edges between two faces that wind opposite ways"),
    ('NGONS', "N-gons", "Faces with more than four sides"),
    ('ISLAS', "Small parts", "Floating parts under the percentage you set"),
)

NOMBRE_PROBLEMA = {clave: nombre for clave, nombre, _desc in PROBLEMAS}

MODO_SELECCION = {
    'DUPLICADOS': (True, False, False),
    'SUELTOS': (True, False, False),
    'ISLAS': (True, False, False),
    'BORDES': (False, True, False),
    'NOMANIFOLD': (False, True, False),
    'INVERTIDAS': (False, True, False),
    'INTERIORES': (False, False, True),
    'AREA_CERO': (False, False, True),
    'NGONS': (False, False, True),
}


def mallas(context) -> list:
    objs = [o for o in context.selected_objects if o.type == 'MESH']
    activo = context.active_object
    if activo is not None and activo.type == 'MESH' and activo not in objs:
        objs.append(activo)
    return objs


def hay_malla(context) -> bool:
    activo = context.active_object
    return activo is not None and activo.type == 'MESH'


def leer_bmesh(obj):
    if obj.mode == 'EDIT':
        return bmesh.from_edit_mesh(obj.data).copy()
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    return bm


def escribir_bmesh(bm, obj) -> None:
    bm.to_mesh(obj.data)
    obj.data.update()


def sobre(context, obj):
    return context.temp_override(
        object=obj,
        active_object=obj,
        selected_objects=[obj],
        selected_editable_objects=[obj],
    )


def distancia(ajustes, bm) -> float:
    return nucleo.umbral(bm, ajustes.modo_umbral, ajustes.umbral_manual)


def volver_a_objeto(context):
    activo = context.active_object
    if activo is not None and activo.mode != 'OBJECT':
        anterior = activo.mode
        bpy.ops.object.mode_set(mode='OBJECT')
        return anterior
    return None


def restaurar_modo(context, modo) -> None:
    if modo and context.active_object is not None:
        try:
            bpy.ops.object.mode_set(mode=modo)
        except RuntimeError:
            pass


def analizar_en(context, obj) -> dict:
    ajustes = context.scene.meldra
    bm = leer_bmesh(obj)
    try:
        datos = nucleo.analizar(bm, distancia(ajustes, bm))
    finally:
        bm.free()
    ajustes.informe.cargar(datos, obj)
    return datos


class MELDRA_OT_analizar(Operator):
    bl_idname = "meldra.analizar"
    bl_label = "Analyze Mesh"
    bl_description = ("Inspects the active mesh: duplicates, holes, "
                      "non-manifold geometry, interior faces, loose parts "
                      "and normals")
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return hay_malla(context)

    def execute(self, context):
        datos = analizar_en(context, context.active_object)
        if datos['cerrada']:
            self.report({'INFO'}, _("Watertight mesh. Ready to decimate and rig"))
        else:
            self.report(
                {'WARNING'},
                _("Not watertight: %d duplicates, %d holes, %d loose parts")
                % (datos['duplicados'], datos['bordes'], datos['islas']))
        return {'FINISHED'}


class MELDRA_OT_copiar_informe(Operator):
    bl_idname = "meldra.copiar_informe"
    bl_label = "Copy Report"
    bl_description = "Copies the report to the clipboard as plain text"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return context.scene.meldra.informe.valido

    def execute(self, context):
        informe = context.scene.meldra.informe
        lineas = ["Meldra - %s" % informe.objeto, ""]
        for etiqueta, numero, texto, ok, _grave in props.filas_informe(informe):
            if numero is None and texto is None:
                lineas.append("")
                lineas.append(_(etiqueta))
                continue
            valor = texto if texto is not None else str(numero)
            lineas.append("  %-34s %10s  %s"
                          % (_(etiqueta), valor, "" if ok else "<--"))
        lineas.append("")
        lineas.append(_("Watertight mesh") if informe.cerrada
                      else _("Not watertight"))
        lineas.append(_("Ready") if informe.apto_para_rig else _("Not ready"))
        context.window_manager.clipboard = "\n".join(lineas)
        self.report({'INFO'}, _("Report copied to the clipboard"))
        return {'FINISHED'}


class MELDRA_OT_seleccionar(Operator):
    bl_idname = "meldra.seleccionar"
    bl_label = "Select Problem"
    bl_description = "Enters Edit Mode with the offending elements selected"
    bl_options = {'REGISTER', 'UNDO'}

    tipo: EnumProperty(name="Type", items=PROBLEMAS, default='BORDES')

    @classmethod
    def poll(cls, context):
        return hay_malla(context)

    def execute(self, context):
        obj = context.active_object
        ajustes = context.scene.meldra

        if obj.mode != 'EDIT':
            bpy.ops.object.mode_set(mode='EDIT')
        context.tool_settings.mesh_select_mode = MODO_SELECCION[self.tipo]

        bm = bmesh.from_edit_mesh(obj.data)
        for f in bm.faces:
            f.select_set(False)
        for e in bm.edges:
            e.select_set(False)
        for v in bm.verts:
            v.select_set(False)
        bm.select_flush(False)

        n = self.marcar(bm, ajustes)

        bm.select_flush(True)
        bmesh.update_edit_mesh(obj.data)

        nombre = _(NOMBRE_PROBLEMA.get(self.tipo, self.tipo))
        if n:
            self.report({'WARNING'}, _("%s: %d elements selected") % (nombre, n))
        else:
            self.report({'INFO'}, _("%s: nothing to flag") % nombre)
        return {'FINISHED'}

    def marcar(self, bm, ajustes) -> int:
        tipo = self.tipo
        n = 0
        if tipo == 'DUPLICADOS':
            return self.duplicados(bm, nucleo.umbral(
                bm, ajustes.modo_umbral, ajustes.umbral_manual))
        if tipo == 'ISLAS':
            return self.islas(bm, ajustes.islas_porcentaje)
        if tipo == 'BORDES':
            for e in bm.edges:
                if e.is_boundary:
                    e.select_set(True)
                    n += 1
        elif tipo == 'NOMANIFOLD':
            for e in bm.edges:
                if len(e.link_faces) > 2 or e.is_wire:
                    e.select_set(True)
                    n += 1
        elif tipo == 'INVERTIDAS':
            for e in bm.edges:
                if len(e.link_faces) == 2 and not e.is_contiguous:
                    e.select_set(True)
                    n += 1
        elif tipo == 'INTERIORES':
            for f in bm.faces:
                if nucleo.es_interior(f):
                    f.select_set(True)
                    n += 1
        elif tipo == 'AREA_CERO':
            eps = nucleo.epsilon_area(nucleo.diagonal(bm))
            for f in bm.faces:
                if f.calc_area() <= eps:
                    f.select_set(True)
                    n += 1
        elif tipo == 'NGONS':
            for f in bm.faces:
                if len(f.verts) > 4:
                    f.select_set(True)
                    n += 1
        elif tipo == 'SUELTOS':
            for v in bm.verts:
                if not v.link_faces:
                    v.select_set(True)
                    n += 1
        return n

    @staticmethod
    def duplicados(bm, dist) -> int:
        verts = list(bm.verts)
        if not verts:
            return 0
        kd = KDTree(len(verts))
        for i, v in enumerate(verts):
            kd.insert(v.co, i)
        kd.balance()
        marcados = set()
        for i, v in enumerate(verts):
            if i in marcados:
                continue
            cerca = kd.find_range(v.co, dist)
            if len(cerca) > 1:
                for punto in cerca:
                    marcados.add(punto[1])
        for i in marcados:
            verts[i].select_set(True)
        return len(marcados)

    @staticmethod
    def islas(bm, porcentaje) -> int:
        padre, caras_isla, _sin_usar = nucleo.islas(bm)
        if not caras_isla:
            return 0
        limite = max(caras_isla.values()) * porcentaje / 100.0
        fuera = set(r for r, c in caras_isla.items() if c < limite)
        if not fuera:
            return 0
        n = 0
        for v in bm.verts:
            if padre[v.index] in fuera:
                v.select_set(True)
                n += 1
        return n


def preparar_objeto(op, context, obj, ajustes) -> bool:
    if obj.data.shape_keys and len(obj.data.shape_keys.key_blocks):
        if not ajustes.quitar_shapekeys:
            op.report({'ERROR'}, _(
                "%s has shape keys. Repairing changes the topology and "
                "invalidates them: tick Remove Shape Keys or delete them by "
                "hand") % obj.name)
            return False
        obj.shape_key_clear()

    if ajustes.limpiar_normales_custom and getattr(
            obj.data, "has_custom_normals", False):
        try:
            with sobre(context, obj):
                bpy.ops.mesh.customdata_custom_splitnormals_clear()
        except RuntimeError:
            pass

    if ajustes.aplicar_transformaciones:
        if obj.parent is not None:
            op.report({'WARNING'}, _(
                "%s has a parent, the transforms were not applied") % obj.name)
        elif obj.data.users > 1:
            op.report({'WARNING'}, _(
                "The mesh of %s is shared by %d objects, the transforms were "
                "not applied") % (obj.name, obj.data.users))
        else:
            try:
                with sobre(context, obj):
                    bpy.ops.object.transform_apply(
                        location=False, rotation=True, scale=True)
            except RuntimeError as ex:
                op.report({'WARNING'}, _(
                    "Could not apply the transform of %s: %s")
                    % (obj.name, ex))
    return True


class MELDRA_OT_reparar(Operator):
    bl_idname = "meldra.reparar"
    bl_label = "Repair All"
    bl_description = ("Welds the vertices, clears the junk, closes the holes "
                      "and leaves the normals facing outwards")
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return hay_malla(context)

    def execute(self, context):
        ajustes = context.scene.meldra
        modo = volver_a_objeto(context)
        total = {'soldados': 0, 'parches': 0, 'sueltos': 0, 'interiores': 0,
                 'degenerados': 0, 'area_cero': 0, 'islas': 0}
        avisos = []

        for obj in mallas(context):
            if not preparar_objeto(self, context, obj, ajustes):
                restaurar_modo(context, modo)
                return {'CANCELLED'}

            bm = leer_bmesh(obj)
            try:
                hecho = nucleo.reparar(
                    bm,
                    dist=distancia(ajustes, bm),
                    borrar_sueltos=ajustes.borrar_sueltos,
                    soldar=ajustes.soldar,
                    degenerados=ajustes.degenerados,
                    interiores=ajustes.interiores,
                    rellenar=ajustes.rellenar,
                    lados_max=ajustes.lados_max,
                    triangular_parches=ajustes.triangular_parches,
                    normales=ajustes.normales,
                    borrar_islas=ajustes.borrar_islas,
                    islas_porcentaje=ajustes.islas_porcentaje,
                )
                escribir_bmesh(bm, obj)
            finally:
                bm.free()

            for clave in total:
                total[clave] += hecho[clave]
            if hecho['medio_interior']:
                avisos.append(_(
                    "%s: %d faces look interior, over half the mesh, so they "
                    "were left alone") % (obj.name, hecho['medio_interior']))
            if hecho['volteada']:
                avisos.append(_(
                    "%s: every normal faced inwards, the mesh was flipped")
                    % obj.name)

        activo = context.active_object
        if activo is not None and activo.type == 'MESH':
            analizar_en(context, activo)

        for aviso in avisos:
            self.report({'WARNING'}, aviso)

        informe = context.scene.meldra.informe
        self.report({'INFO'}, _(
            "Welded %d vertices, %d patches, %d loose, %d interior, "
            "%d degenerate. %s")
            % (total['soldados'], total['parches'], total['sueltos'],
               total['interiores'], total['degenerados'] + total['area_cero'],
               _("Watertight mesh") if informe.cerrada
               else _("Still not watertight")))

        restaurar_modo(context, modo)
        return {'FINISHED'}


class MELDRA_OT_decimar(Operator):
    bl_idname = "meldra.decimar"
    bl_label = "Decimate"
    bl_description = ("Adds the Decimate modifier in Collapse mode with the "
                      "ratio worked out for you, and applies it")
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return hay_malla(context)

    def execute(self, context):
        ajustes = context.scene.meldra
        modo = volver_a_objeto(context)

        for obj in mallas(context):
            if obj.data.shape_keys and len(obj.data.shape_keys.key_blocks):
                if not ajustes.quitar_shapekeys:
                    self.report({'ERROR'}, _(
                        "%s has shape keys and Decimate does not work with "
                        "them") % obj.name)
                    restaurar_modo(context, modo)
                    return {'CANCELLED'}
                obj.shape_key_clear()

            bm = leer_bmesh(obj)
            try:
                tris = sum(len(f.verts) - 2 for f in bm.faces)
            finally:
                bm.free()
            if tris < 4:
                continue

            if ajustes.decimar_modo == 'RATIO':
                ratio = ajustes.decimar_ratio
            else:
                ratio = min(1.0, max(0.0, ajustes.decimar_tris / float(tris)))

            mod = obj.modifiers.new("Meldra Decimate", 'DECIMATE')
            mod.decimate_type = 'COLLAPSE'
            mod.ratio = ratio
            mod.use_symmetry = ajustes.decimar_simetria
            mod.symmetry_axis = ajustes.decimar_eje

            if not ajustes.decimar_aplicar:
                self.report({'INFO'}, _(
                    "%s: modifier added with ratio %.4f, %d to about %d "
                    "triangles") % (obj.name, ratio, tris, int(tris * ratio)))
                continue

            if obj.data.users > 1:
                obj.modifiers.remove(mod)
                self.report({'ERROR'}, _(
                    "The mesh of %s is shared by %d objects. Use Object > "
                    "Relations > Make Single User > Object & Data")
                    % (obj.name, obj.data.users))
                restaurar_modo(context, modo)
                return {'CANCELLED'}

            try:
                with sobre(context, obj):
                    bpy.ops.object.modifier_apply(modifier=mod.name)
            except RuntimeError as ex:
                obj.modifiers.remove(mod)
                self.report({'ERROR'},
                            _("Could not apply on %s: %s") % (obj.name, ex))
                restaurar_modo(context, modo)
                return {'CANCELLED'}

        activo = context.active_object
        if activo is not None and activo.type == 'MESH':
            datos = analizar_en(context, activo)
            self.report({'INFO'}, _("%s: %d triangles, %s")
                        % (activo.name, datos['triangulos'],
                           _("still watertight") if datos['cerrada']
                           else _("WARNING: it left holes")))

        restaurar_modo(context, modo)
        return {'FINISHED'}


def colocar_origen(context, obj, donde) -> None:
    if donde == 'SIN':
        return
    cursor = context.scene.cursor
    previo = cursor.location.copy()
    try:
        if donde == 'CENTRO':
            with sobre(context, obj):
                bpy.ops.object.origin_set(type='ORIGIN_GEOMETRY',
                                          center='MEDIAN')
        else:
            esquinas = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
            cx = (min(v.x for v in esquinas) + max(v.x for v in esquinas)) / 2.0
            cy = (min(v.y for v in esquinas) + max(v.y for v in esquinas)) / 2.0
            cz = min(v.z for v in esquinas)
            cursor.location = Vector((cx, cy, cz))
            with sobre(context, obj):
                bpy.ops.object.origin_set(type='ORIGIN_CURSOR')
    except RuntimeError:
        pass
    finally:
        cursor.location = previo


class MELDRA_OT_preparar_rig(Operator):
    bl_idname = "meldra.preparar_rig"
    bl_label = "Prepare For Armature"
    bl_description = ("Repairs the mesh and also leaves scale, origin and data "
                      "the way automatic weights want them")
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return hay_malla(context)

    def execute(self, context):
        ajustes = context.scene.meldra
        modo = volver_a_objeto(context)

        transf = ajustes.aplicar_transformaciones
        ajustes.aplicar_transformaciones = True
        try:
            resultado = bpy.ops.meldra.reparar()
        except RuntimeError as ex:
            self.report({'ERROR'}, "%s" % ex)
            restaurar_modo(context, modo)
            return {'CANCELLED'}
        finally:
            ajustes.aplicar_transformaciones = transf
        if 'CANCELLED' in resultado:
            restaurar_modo(context, modo)
            return {'CANCELLED'}

        for obj in mallas(context):
            if ajustes.rig_quitar_grupos:
                obj.vertex_groups.clear()
            colocar_origen(context, obj, ajustes.rig_origen)

        activo = context.active_object
        if activo is not None and activo.type == 'MESH':
            analizar_en(context, activo)
            if context.scene.meldra.informe.apto_para_rig:
                self.report({'INFO'},
                            _("Ready to parent with automatic weights"))
            else:
                self.report({'WARNING'}, _(
                    "The report still shows warnings: check what is red "
                    "before parenting"))

        restaurar_modo(context, modo)
        return {'FINISHED'}


class MELDRA_OT_emparentar(Operator):
    bl_idname = "meldra.emparentar"
    bl_label = "Parent With Automatic Weights"
    bl_description = ("Parents the mesh to the chosen armature with automatic "
                      "weights, and explains the failure when there is one")
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return hay_malla(context) and context.scene.meldra.armadura is not None

    def execute(self, context):
        arm = context.scene.meldra.armadura
        if arm is None or arm.type != 'ARMATURE':
            self.report({'ERROR'}, _("Pick an armature"))
            return {'CANCELLED'}
        if not arm.data.bones:
            self.report({'ERROR'}, _("The armature %s has no bones") % arm.name)
            return {'CANCELLED'}

        volver_a_objeto(context)
        objetivos = [o for o in mallas(context) if o is not arm]
        if not objetivos:
            self.report({'ERROR'}, _("No mesh selected"))
            return {'CANCELLED'}

        for o in context.selected_objects:
            o.select_set(False)
        for o in objetivos:
            o.select_set(True)
        arm.select_set(True)
        context.view_layer.objects.active = arm

        try:
            bpy.ops.object.parent_set(type='ARMATURE_AUTO')
        except RuntimeError as ex:
            self.report({'ERROR'}, "%s" % ex)
            self.report({'INFO'}, self.pista(context))
            return {'CANCELLED'}

        self.report({'INFO'},
                    _("Parented to %s with automatic weights") % arm.name)
        return {'FINISHED'}

    @staticmethod
    def pista(context) -> str:
        i = context.scene.meldra.informe
        if not i.valido:
            return _("Press Analyze Mesh to see what is wrong with it")
        fallos = []
        if i.duplicados:
            fallos.append(_("%d duplicate vertices") % i.duplicados)
        if not i.cerrada:
            fallos.append(_("the mesh is not watertight"))
        if i.islas > 1:
            fallos.append(_("%d loose parts") % i.islas)
        if i.area_cero:
            fallos.append(_("%d zero area faces") % i.area_cero)
        if i.interiores:
            fallos.append(_("%d interior faces") % i.interiores)
        if not i.escala_ok:
            fallos.append(_("the scale is not applied"))
        if not fallos:
            return _("The mesh is clean: check that the bones sit inside the "
                     "model volume")
        return _("Likely cause: %s") % ", ".join(fallos)


class MELDRA_OT_remesh_voxel(Operator):
    bl_idname = "meldra.remesh_voxel"
    bl_label = "Voxel Rebuild"
    bl_description = ("Rebuilds the mesh from scratch. It always comes out "
                      "watertight and manifold, but UVs and materials are lost")
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return hay_malla(context)

    def execute(self, context):
        ajustes = context.scene.meldra
        modo = volver_a_objeto(context)

        for obj in mallas(context):
            if obj.data.shape_keys and len(obj.data.shape_keys.key_blocks):
                obj.shape_key_clear()
            if ajustes.voxel_auto:
                bm = leer_bmesh(obj)
                try:
                    d = nucleo.diagonal(bm)
                finally:
                    bm.free()
                tam = d / max(ajustes.voxel_detalle, 1) if d > 0 else 0.02
            else:
                tam = ajustes.voxel_tam
            obj.data.remesh_voxel_size = max(tam, 1e-5)
            try:
                with sobre(context, obj):
                    bpy.ops.object.voxel_remesh()
            except RuntimeError as ex:
                self.report({'ERROR'}, "%s: %s" % (obj.name, ex))
                restaurar_modo(context, modo)
                return {'CANCELLED'}

        activo = context.active_object
        if activo is not None and activo.type == 'MESH':
            datos = analizar_en(context, activo)
            self.report({'INFO'}, _("%s: %d triangles, voxel %.5f, %s")
                        % (activo.name, datos['triangulos'],
                           activo.data.remesh_voxel_size,
                           _("watertight") if datos['cerrada']
                           else _("not watertight")))
        restaurar_modo(context, modo)
        return {'FINISHED'}


class MELDRA_OT_remesh_quad(Operator):
    bl_idname = "meldra.remesh_quad"
    bl_label = "QuadriFlow Rebuild"
    bl_description = ("Automatic quad retopology. It needs a mesh that is "
                      "already manifold, so repair first")
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return hay_malla(context)

    def execute(self, context):
        ajustes = context.scene.meldra
        modo = volver_a_objeto(context)
        obj = context.active_object
        if obj.data.shape_keys and len(obj.data.shape_keys.key_blocks):
            obj.shape_key_clear()
        try:
            with sobre(context, obj):
                bpy.ops.object.quadriflow_remesh(
                    mode='FACES', target_faces=ajustes.quad_caras)
        except RuntimeError as ex:
            self.report({'ERROR'}, _(
                "QuadriFlow failed (%s). Usually the mesh is not manifold: "
                "press Repair All first") % ex)
            restaurar_modo(context, modo)
            return {'CANCELLED'}

        datos = analizar_en(context, obj)
        self.report({'INFO'}, _("%s: %d faces, %s")
                    % (obj.name, datos['caras'],
                       _("watertight") if datos['cerrada']
                       else _("not watertight")))
        restaurar_modo(context, modo)
        return {'FINISHED'}


CLASES = (
    MELDRA_OT_analizar,
    MELDRA_OT_copiar_informe,
    MELDRA_OT_seleccionar,
    MELDRA_OT_reparar,
    MELDRA_OT_decimar,
    MELDRA_OT_preparar_rig,
    MELDRA_OT_emparentar,
    MELDRA_OT_remesh_voxel,
    MELDRA_OT_remesh_quad,
)


def register():
    for clase in CLASES:
        bpy.utils.register_class(clase)


def unregister():
    for clase in reversed(CLASES):
        bpy.utils.unregister_class(clase)
