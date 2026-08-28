from __future__ import annotations

import bpy
from bpy.app.translations import pgettext_iface as _
from bpy.types import Panel

from . import props, version

REDES = (
    ("Instagram", "https://www.instagram.com/xander.dice"),
    ("YouTube", "https://www.youtube.com/@xanderdice"),
    ("Facebook", "https://www.facebook.com/djxanderdice"),
)

BOTONES_PROBLEMA = (
    "DUPLICADOS", "BORDES", "NOMANIFOLD", "INTERIORES", "AREA_CERO",
    "SUELTOS", "INVERTIDAS", "NGONS", "ISLAS",
)


def pintar_filas(col, filas) -> None:
    for etiqueta, numero, texto, ok, grave in filas:
        if numero is None and texto is None:
            col.separator()
            col.label(text=etiqueta)
            continue
        fila = col.row(align=True)
        fila.alert = not ok and grave
        fila.label(text=etiqueta,
                   icon='CHECKMARK' if ok else ('ERROR' if grave else 'INFO'))
        der = fila.row()
        der.alignment = 'RIGHT'
        der.label(text=texto if texto is not None else str(numero))


class Base:
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Meldra"


class MELDRA_PT_principal(Base, Panel):
    bl_idname = "MELDRA_PT_principal"
    bl_label = "Meldra"

    def draw(self, context):
        col = self.layout.column()
        obj = context.active_object

        if obj is None or obj.type != 'MESH':
            col.label(text="Select a mesh", icon='INFO')
            return

        fx = col.column()
        fx.scale_y = 1.4
        fx.operator("meldra.analizar", icon='ZOOM_SELECTED')

        i = context.scene.meldra.informe
        if not i.valido:
            col.label(text="Not analyzed yet", icon='INFO')
            return

        caja = col.box().column(align=True)
        cab = caja.row(align=True)
        cab.label(text=i.objeto, icon='MESH_DATA')
        cab.operator("meldra.copiar_informe", text="", icon='COPYDOWN')
        if i.objeto != obj.name:
            caja.label(text="The report belongs to another object", icon='ERROR')

        pintar_filas(caja, props.filas_informe(i))

        veredicto = caja.row()
        veredicto.alert = not (i.cerrada or i.cerrada_al_soldar)
        if i.cerrada:
            veredicto.label(text="Watertight mesh", icon='CHECKMARK')
        elif i.cerrada_al_soldar:
            veredicto.label(text="Watertight once welded", icon='INFO')
            caja.label(text="Press Repair All first", icon='INFO')
        else:
            veredicto.label(text="Not watertight", icon='ERROR')


class MELDRA_PT_ver(Base, Panel):
    bl_parent_id = "MELDRA_PT_principal"
    bl_label = "Locate Problems"

    def draw(self, context):
        from .ops import NOMBRE_PROBLEMA

        col = self.layout.column(align=True)
        col.label(text="Enter Edit Mode and select:")
        rejilla = col.grid_flow(columns=2, even_columns=True, align=True)
        for clave in BOTONES_PROBLEMA:
            rejilla.operator(
                "meldra.seleccionar",
                text=_(NOMBRE_PROBLEMA[clave])).tipo = clave

        col.separator()
        col.label(text="Tip: turn on Face Orientation", icon='INFO')
        col.label(text="in Overlays to check the normals")


class MELDRA_PT_reparar(Base, Panel):
    bl_parent_id = "MELDRA_PT_principal"
    bl_label = "Repair"

    def draw(self, context):
        a = context.scene.meldra
        col = self.layout.column()

        col.prop(a, "modo_umbral")
        if a.modo_umbral == 'MANUAL':
            col.prop(a, "umbral_manual")
        elif a.informe.valido:
            col.label(text=_("Distance: %.6f") % a.informe.umbral, icon='INFO')

        col.separator()
        pasos = col.column(align=True)
        pasos.prop(a, "aplicar_transformaciones")
        pasos.prop(a, "quitar_shapekeys")
        pasos.prop(a, "limpiar_normales_custom")
        pasos.prop(a, "borrar_sueltos")
        pasos.prop(a, "soldar")
        pasos.prop(a, "degenerados")
        pasos.prop(a, "interiores")
        pasos.prop(a, "rellenar")
        if a.rellenar:
            sub = pasos.row(align=True)
            sub.prop(a, "lados_max")
            sub.prop(a, "triangular_parches", text="", icon='MOD_TRIANGULATE')
        pasos.prop(a, "normales")

        col.separator()
        peligro = col.box().column(align=True)
        peligro.prop(a, "borrar_islas", icon='TRASH')
        if a.borrar_islas:
            peligro.prop(a, "islas_porcentaje")
            peligro.operator("meldra.seleccionar", text="See which ones",
                             icon='ZOOM_SELECTED').tipo = 'ISLAS'

        col.separator()
        fx = col.column()
        fx.scale_y = 1.5
        fx.operator("meldra.reparar", icon='FILE_REFRESH')
        col.label(text="Acts on everything selected", icon='INFO')


class MELDRA_PT_decimar(Base, Panel):
    bl_parent_id = "MELDRA_PT_principal"
    bl_label = "Decimate"

    def draw(self, context):
        a = context.scene.meldra
        i = a.informe
        col = self.layout.column()

        if i.valido and not i.cerrada:
            aviso = col.box().column(align=True)
            aviso.alert = True
            aviso.label(text="The mesh is not watertight", icon='ERROR')
            aviso.label(text="Decimating now will open holes")
            aviso.label(text="Press Repair All first")

        col.prop(a, "decimar_modo", expand=True)
        if a.decimar_modo == 'RATIO':
            col.prop(a, "decimar_ratio", slider=True)
            if i.valido:
                col.label(icon='INFO', text=_("%d to about %d triangles")
                          % (i.triangulos, int(i.triangulos * a.decimar_ratio)))
        else:
            col.prop(a, "decimar_tris")
            if i.valido and i.triangulos:
                col.label(icon='INFO', text=_("%d to %d, ratio %.4f")
                          % (i.triangulos, a.decimar_tris,
                             min(1.0, a.decimar_tris / float(i.triangulos))))

        col.separator()
        sim = col.row(align=True)
        sim.prop(a, "decimar_simetria")
        if a.decimar_simetria:
            sim.prop(a, "decimar_eje", expand=True)
        col.prop(a, "decimar_aplicar")

        col.separator()
        fx = col.column()
        fx.scale_y = 1.5
        fx.operator("meldra.decimar", icon='MOD_DECIM')


class MELDRA_PT_rig(Base, Panel):
    bl_parent_id = "MELDRA_PT_principal"
    bl_label = "Armature"

    def draw(self, context):
        a = context.scene.meldra
        i = a.informe
        col = self.layout.column()

        if i.valido:
            caja = col.box().column(align=True)
            caja.label(text="Automatic weights need")
            pintar_filas(caja, props.filas_rig(i))
            v = caja.row()
            v.alert = not i.apto_para_rig
            v.label(text="Ready" if i.apto_para_rig else "Not ready",
                    icon='CHECKMARK' if i.apto_para_rig else 'ERROR')

        col.separator()
        col.prop(a, "rig_origen")
        col.prop(a, "rig_quitar_grupos")
        fx = col.column()
        fx.scale_y = 1.4
        fx.operator("meldra.preparar_rig", icon='ARMATURE_DATA')

        col.separator()
        col.prop(a, "armadura")
        fx = col.column()
        fx.scale_y = 1.4
        fx.enabled = a.armadura is not None
        fx.operator("meldra.emparentar", icon='ARMATURE_DATA')
        if a.armadura is None:
            col.label(text="Pick the armature above", icon='INFO')


class MELDRA_PT_reconstruir(Base, Panel):
    bl_parent_id = "MELDRA_PT_principal"
    bl_label = "Rebuild"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        a = context.scene.meldra
        col = self.layout.column()
        col.label(text="Last resort: UVs and materials", icon='ERROR')
        col.label(text="are lost")

        col.separator()
        col.prop(a, "voxel_auto")
        col.prop(a, "voxel_detalle" if a.voxel_auto else "voxel_tam")
        col.operator("meldra.remesh_voxel", icon='MOD_REMESH')

        col.separator()
        col.prop(a, "quad_caras")
        col.operator("meldra.remesh_quad", icon='MOD_REMESH')


class MELDRA_PT_creditos(Base, Panel):
    bl_parent_id = "MELDRA_PT_principal"
    bl_label = "Credits"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        col = self.layout.column(align=True)
        col.label(text="xander.dice", icon='USER')
        col.separator()
        for etiqueta, url in REDES:
            col.operator("wm.url_open", text=etiqueta, icon='URL').url = url
        col.separator()
        col.label(text="Meldra %s" % version.NUMERO)
        col.label(text="GPL-3.0-or-later")


CLASES = (
    MELDRA_PT_principal,
    MELDRA_PT_ver,
    MELDRA_PT_reparar,
    MELDRA_PT_decimar,
    MELDRA_PT_rig,
    MELDRA_PT_reconstruir,
    MELDRA_PT_creditos,
)


def register():
    for clase in CLASES:
        bpy.utils.register_class(clase)


def unregister():
    for clase in reversed(CLASES):
        bpy.utils.unregister_class(clase)
