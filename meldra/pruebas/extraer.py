"""Dev tool. Lists every user facing string of the add-on.

    blender --background --factory-startup --python pruebas/extraer.py

Reads the operators, panels and properties through the RNA, and scans the
sources for literals that reach the user. The result is the canonical msgid
list that every language file has to cover.
"""

from __future__ import annotations

import os
import re
import sys

import bpy

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)

import meldra

NO_TRADUCIR = {
    "", "Meldra", "X", "Y", "Z", "Instagram", "YouTube", "Facebook",
    "xander.dice", "GPL-3.0-or-later", "N-gons", "Euler V-E+F", "QuadriFlow",
    "Meldra %s", "informe", "Informe",
}


def propias(cls):
    for nombre in getattr(cls, "__annotations__", {}):
        prop = cls.bl_rna.properties.get(nombre)
        if prop is not None:
            yield prop


def de_rna() -> set:
    textos = set()
    for cls in meldra.ops.CLASES + meldra.ui.CLASES:
        textos.add(getattr(cls, "bl_label", ""))
        textos.add(getattr(cls, "bl_description", ""))
    ajustes = [c for c in meldra.props.CLASES
               if c.__name__ != "MELDRA_Informe"]
    for cls in tuple(ajustes) + meldra.ops.CLASES:
        for prop in propias(cls):
            textos.add(prop.name)
            textos.add(prop.description)
            for item in getattr(prop, "enum_items", ()) or ():
                textos.add(item.name)
                textos.add(item.description)
    return textos


def literales(ruta) -> set:
    with open(ruta, encoding="utf-8") as fh:
        fuente = fh.read()
    fuente = re.sub(r"\)\s*\n\s*", ") ", fuente)
    juntado = re.sub(r'"\s*\n\s*"', "", fuente)
    textos = set()
    for patron in (r'text="((?:[^"\\]|\\.)*)"',
                   r'_\(\s*"((?:[^"\\]|\\.)*)"\s*\)',
                   r'_\(\s*"((?:[^"\\]|\\.)*)"\s*%'):
        textos.update(re.findall(patron, juntado))
    return textos


def de_tablas() -> set:
    textos = set()
    for _clave, nombre, descripcion in meldra.ops.PROBLEMAS:
        textos.add(nombre)
        textos.add(descripcion)
    informe = bpy.context.scene.meldra.informe
    informe.cerrada = True
    informe.usuarios = 2
    for etiqueta, _numero, _texto, _ok, _grave in meldra.props.filas_informe(
            informe):
        textos.add(etiqueta)
    for etiqueta, _numero, _texto, _ok, _grave in meldra.props.filas_rig(
            informe):
        textos.add(etiqueta)
    textos.update({"yes", "no"})
    return textos


def catalogo() -> list:
    ya_estaba = hasattr(bpy.types.Scene, "meldra")
    if not ya_estaba:
        meldra.register()
    try:
        textos = de_rna() | de_tablas()
        for nombre in ("ops.py", "ui.py"):
            textos |= literales(os.path.join(RAIZ, "meldra", nombre))
    finally:
        if not ya_estaba:
            meldra.unregister()
    limpio = {t for t in textos if t and t not in NO_TRADUCIR}
    return sorted(limpio)


def main() -> None:
    lista = catalogo()
    print("MSGIDS %d" % len(lista))
    for texto in lista:
        print("::%s" % texto)


if __name__ == "__main__":
    main()
