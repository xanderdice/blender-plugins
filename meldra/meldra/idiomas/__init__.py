from __future__ import annotations

from . import (
    ab_ky_eo, balcanes, de_nl_en, es_pt, fr_it_ca, hu_ro_el, india, ja_ko,
    lt_eu_ka, norte, oriente, pl_cs_sk, ru_uk_be, sudeste, tr_sw, zh,
)

MODULOS = (
    es_pt, fr_it_ca, de_nl_en, norte, ru_uk_be, pl_cs_sk, balcanes, hu_ro_el,
    lt_eu_ka, ab_ky_eo, zh, ja_ko, sudeste, india, oriente, tr_sw,
)


CONTEXTOS = ("*", "Operator")


def construir() -> dict:
    completo = {}
    for modulo in MODULOS:
        for codigo, pares in modulo.IDIOMAS.items():
            destino = completo.setdefault(codigo, {})
            for original, traducido in pares.items():
                for contexto in CONTEXTOS:
                    destino[(contexto, original)] = traducido
    return completo


TRADUCCIONES = construir()
CODIGOS = tuple(sorted(TRADUCCIONES))
