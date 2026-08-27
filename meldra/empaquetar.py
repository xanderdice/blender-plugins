#!/usr/bin/env python3
"""Genera el zip distribuible de Meldra en dist/.

    python empaquetar.py

Solo usa la libreria estandar, asi que tambien vale el Python que trae Blender:

    blender --background --python empaquetar.py

Escribe las rutas del zip con "/" a proposito: Compress-Archive de Windows
PowerShell las guarda con "\\", que no es lo que dice el estandar ZIP.
"""

import os
import re
import shutil
import zipfile

RAIZ = os.path.dirname(os.path.abspath(__file__))
ORIGEN = os.path.join(RAIZ, "meldra")
DESTINO = os.path.join(RAIZ, "dist")
IGNORAR = (".pyc", ".pyo")


def version() -> str:
    ruta = os.path.join(ORIGEN, "blender_manifest.toml")
    with open(ruta, encoding="utf-8") as fh:
        encontrado = re.search(r'(?m)^\s*version\s*=\s*"([^"]+)"', fh.read())
    if not encontrado:
        raise SystemExit("El manifiesto no declara version")
    return encontrado.group(1)


def main() -> None:
    if not os.path.isdir(ORIGEN):
        raise SystemExit("No encuentro %s" % ORIGEN)

    if os.path.isdir(DESTINO):
        shutil.rmtree(DESTINO)
    os.makedirs(DESTINO)

    zip_ruta = os.path.join(DESTINO, "meldra-%s.zip" % version())
    metidos = 0
    with zipfile.ZipFile(zip_ruta, "w", zipfile.ZIP_DEFLATED) as zip_:
        for carpeta, subcarpetas, ficheros in os.walk(ORIGEN):
            subcarpetas[:] = [d for d in subcarpetas if d != "__pycache__"]
            for fichero in sorted(ficheros):
                if fichero.endswith(IGNORAR):
                    continue
                ruta = os.path.join(carpeta, fichero)
                dentro = os.path.relpath(ruta, RAIZ).replace(os.sep, "/")
                zip_.write(ruta, dentro)
                metidos += 1

    tam = os.path.getsize(zip_ruta) / 1024.0
    print("%d ficheros, %.1f KB" % (metidos, tam))
    print("%s" % zip_ruta)


if __name__ == "__main__":
    main()
