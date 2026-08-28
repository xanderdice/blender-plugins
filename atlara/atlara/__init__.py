bl_info = {
    "name": "Atlara",
    "author": "xander.dice",
    "version": (1, 0, 0),
    "blender": (4, 2, 0),
    "location": "Vista 3D > Barra lateral (N) > Atlara",
    "description": "Funde varios materiales y objetos en un unico atlas "
                   "para gastar el minimo de drawcalls",
    "category": "Material",
}

from . import ops, props, ui

MODULOS = (props, ops, ui)


def register():
    for modulo in MODULOS:
        modulo.register()


def unregister():
    for modulo in reversed(MODULOS):
        modulo.unregister()
