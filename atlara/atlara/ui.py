# SPDX-License-Identifier: GPL-3.0-or-later
"""Panel de Atlara en la barra lateral del visor 3D."""

from __future__ import annotations

import bpy
from bpy.types import Panel

from . import props, version

REDES = (
    ("Instagram", "https://www.instagram.com/xander.dice"),
    ("YouTube", "https://www.youtube.com/@xanderdice"),
    ("Facebook", "https://www.facebook.com/djxanderdice"),
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
    bl_category = "Atlara"


class ATLARA_PT_principal(Base, Panel):
    bl_idname = "ATLARA_PT_principal"
    bl_label = "Atlara"

    def draw(self, context):
        ajustes = context.scene.atlara
        col = self.layout.column()

        if context.mode != 'OBJECT':
            col.label(text="Sal del modo edicion", icon='INFO')
            return

        fx = col.column()
        fx.scale_y = 1.3
        fx.operator("atlara.analizar", icon='ZOOM_SELECTED')

        informe = ajustes.informe
        if informe.valido:
            caja = col.box().column(align=True)
            pintar_filas(caja, props.filas_informe(informe))
        else:
            col.label(text="Selecciona los objetos y analiza", icon='INFO')

        col.separator()
        col.prop(ajustes, "modo", text="")
        if informe.avance:
            # El boton se deja a la vista aposta: si un cierre a lo bruto
            # dejo este texto pegado, no queremos que el panel se quede
            # sin nada que pulsar.
            caja = col.box().column(align=True)
            caja.label(text="Trabajando...", icon='SORTTIME')
            for linea in informe.avance.split("  —  "):
                caja.label(text=linea)

        fx = col.column()
        fx.scale_y = 1.6
        fx.operator("atlara.atlas", icon='TEXTURE')
        col.label(text="Las luces se omiten solas", icon='LIGHT')

        if informe.resultado:
            caja = col.box().column(align=True)
            caja.label(text="Hecho", icon='CHECKMARK')
            for linea in informe.resultado.split(". "):
                caja.label(text=linea)


class ATLARA_PT_atlas(Base, Panel):
    bl_parent_id = "ATLARA_PT_principal"
    bl_label = "Atlas"

    def draw(self, context):
        ajustes = context.scene.atlara
        col = self.layout.column()
        col.prop(ajustes, "resolucion")
        fila = col.row(align=True)
        fila.prop(ajustes, "margen_auto", text="", icon='AUTO')
        sub = fila.row()
        sub.enabled = not ajustes.margen_auto
        sub.prop(ajustes, "margen")
        col.separator()
        col.prop(ajustes, "empaquetador")
        if ajustes.empaquetador in ('AUTO', 'FORMA'):
            col.prop(ajustes, "forma")
            col.prop(ajustes, "rotar")
        if ajustes.empaquetador in ('AUTO', 'CAJA'):
            col.prop(ajustes, "agrupacion")
            fila = col.row(align=True)
            fila.prop(ajustes, "rotar")
            fila.prop(ajustes, "orientar")
        col.prop(ajustes, "densidad")
        col.separator()
        col.prop(ajustes, "celda_plana")
        if ajustes.informe.valido and ajustes.informe.planos:
            col.label(icon='INFO', text="%d materiales son solo color"
                      % ajustes.informe.planos)


class ATLARA_PT_canales(Base, Panel):
    bl_parent_id = "ATLARA_PT_principal"
    bl_label = "Canales y texturas"

    def draw(self, context):
        ajustes = context.scene.atlara
        col = self.layout.column()

        col.prop(ajustes, "empaquetado")
        col.separator()
        col.prop(ajustes, "auto_canales")
        rejilla = col.grid_flow(columns=2, even_columns=True, align=True)
        for nombre in ("usar_normal", "usar_metal", "usar_rugosidad",
                       "usar_emision", "usar_alfa"):
            rejilla.prop(ajustes, nombre)
        col.separator()
        col.prop(ajustes, "usar_ao")
        if ajustes.usar_ao:
            col.prop(ajustes, "ao_muestras")
            col.label(text="Con oclusion no se usan celdas de color",
                      icon='INFO')
        col.prop(ajustes, "voltear_verde")

        col.separator()
        col.prop(ajustes, "prefijo")
        col.prop(ajustes, "guardado", text="")
        if ajustes.guardado == 'DISCO':
            col.prop(ajustes, "carpeta")


class ATLARA_PT_objetos(Base, Panel):
    bl_parent_id = "ATLARA_PT_principal"
    bl_label = "Objetos"

    def draw(self, context):
        ajustes = context.scene.atlara
        col = self.layout.column()
        col.prop(ajustes, "aplicar_transformaciones")
        col.prop(ajustes, "origen")
        col.prop(ajustes, "mover_a_cero")
        if ajustes.mover_a_cero:
            col.label(text="Se van a amontonar en el visor", icon='INFO')
        col.separator()
        col.prop(ajustes, "capas_uv")
        col.prop(ajustes, "reproyectar")
        if ajustes.reproyectar:
            col.prop(ajustes, "angulo")
        col.separator()
        col.operator("atlara.centrar", icon='OBJECT_ORIGIN')


class ATLARA_PT_creditos(Base, Panel):
    bl_parent_id = "ATLARA_PT_principal"
    bl_label = "Creditos"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        col = self.layout.column(align=True)
        col.label(text="xander.dice", icon='USER')
        col.separator()
        for etiqueta, url in REDES:
            col.operator("wm.url_open", text=etiqueta, icon='URL').url = url
        col.separator()
        col.label(text="Atlara %s" % version.NUMERO)
        col.label(text="GPL-3.0-or-later")


CLASES = (
    ATLARA_PT_principal,
    ATLARA_PT_atlas,
    ATLARA_PT_canales,
    ATLARA_PT_objetos,
    ATLARA_PT_creditos,
)


def register():
    for clase in CLASES:
        bpy.utils.register_class(clase)


def unregister():
    for clase in reversed(CLASES):
        bpy.utils.unregister_class(clase)
