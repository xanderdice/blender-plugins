from __future__ import annotations

import os
import tomllib

MANIFIESTO = os.path.join(os.path.dirname(__file__), "blender_manifest.toml")


def leer() -> str:
    try:
        with open(MANIFIESTO, "rb") as fh:
            return str(tomllib.load(fh).get("version", ""))
    except Exception:
        return ""


NUMERO = leer()
