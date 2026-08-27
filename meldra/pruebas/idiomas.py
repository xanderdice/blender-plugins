"""Checks the translation files against the canonical string list.

    blender --background --factory-startup --python pruebas/idiomas.py

Verifies that every language Blender can display is covered, that no language
has extra or missing keys, and that the format placeholders survive the
translation in the same order. A mismatch there would crash the add-on at
runtime, so it is worth a hard failure.
"""

from __future__ import annotations

import os
import re
import sys

import bpy

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AQUI = os.path.dirname(os.path.abspath(__file__))
for ruta in (RAIZ, AQUI):
    if ruta not in sys.path:
        sys.path.insert(0, ruta)

import extraer
from meldra import idiomas

FORMATO = re.compile(r"%[-#0-9.+ ]*[a-zA-Z%]")

PARCIALES = {"en_GB"}


def idiomas_de_blender() -> set:
    items = bpy.types.PreferencesView.bl_rna.properties['language'].enum_items
    return {e.identifier for e in items} - {"DEFAULT", "en_US"}


def revisar():
    claves = set(extraer.catalogo())
    esperados = idiomas_de_blender()
    presentes = set(idiomas.TRADUCCIONES)
    fallos = []

    faltan = sorted(esperados - presentes)
    if faltan:
        fallos.append("idiomas sin fichero: %s" % ", ".join(faltan))
    sobran = sorted(presentes - esperados)
    if sobran:
        fallos.append("codigos que Blender no conoce: %s" % ", ".join(sobran))

    for codigo in sorted(presentes):
        pares = {origen: destino
                 for (_ctx, origen), destino in idiomas.TRADUCCIONES[codigo].items()}
        desconocidas = sorted(set(pares) - claves)
        if desconocidas:
            fallos.append("%s: claves que no existen en el add-on: %s"
                          % (codigo, desconocidas[:3]))
        if codigo not in PARCIALES:
            sin_traducir = sorted(claves - set(pares))
            if sin_traducir:
                fallos.append("%s: faltan %d cadenas, p.ej. %s"
                              % (codigo, len(sin_traducir), sin_traducir[:2]))
        for origen, destino in pares.items():
            if not destino.strip():
                fallos.append("%s: traduccion vacia para %r" % (codigo, origen))
                continue
            if FORMATO.findall(origen) != FORMATO.findall(destino):
                fallos.append("%s: los marcadores no cuadran en %r -> %r"
                              % (codigo, origen, destino))
    return claves, esperados, presentes, fallos


def main() -> None:
    claves, esperados, presentes, fallos = revisar()
    print("cadenas del add-on : %d" % len(claves))
    print("idiomas de Blender : %d" % len(esperados))
    print("idiomas cubiertos  : %d" % len(presentes & esperados))
    print("entradas totales   : %d"
          % sum(len(v) for v in idiomas.TRADUCCIONES.values()))
    if fallos:
        print("\n%d PROBLEMAS" % len(fallos))
        for fallo in fallos:
            print("  - %s" % fallo)
        sys.exit(1)
    print("\nTodo cuadra.")
    sys.exit(0)


if __name__ == "__main__":
    main()
