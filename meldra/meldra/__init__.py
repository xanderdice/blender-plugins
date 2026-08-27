bl_info = {
    "name": "Meldra",
    "author": "xander.dice",
    "version": (2, 0, 0),
    "blender": (4, 2, 0),
    "location": "3D View > Sidebar (N) > Meldra",
    "description": "Weld, seal and validate meshes for decimation and rigging",
    "category": "Mesh",
}

import bpy

from . import idiomas, ops, props, ui

MODULOS = (props, ops, ui)


def register():
    for modulo in MODULOS:
        modulo.register()
    try:
        bpy.app.translations.register(__name__, idiomas.TRADUCCIONES)
    except ValueError:
        bpy.app.translations.unregister(__name__)
        bpy.app.translations.register(__name__, idiomas.TRADUCCIONES)


def unregister():
    try:
        bpy.app.translations.unregister(__name__)
    except ValueError:
        pass
    for modulo in reversed(MODULOS):
        modulo.unregister()
