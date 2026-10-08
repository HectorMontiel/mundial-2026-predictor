# -*- coding: utf-8 -*-
"""v342 — las fotos de `jugados_dia.json` de cada día, con el marcador de los
otros deportes rellenado DESPUÉS del arreglo de `fixtures_espn` (el tenis de
ESPN se perdía entero por la fecha del torneo). Caché: _v342_fotos.json."""
import json
import os

import _v331_rojos_app as r331
import partidos_jugados as pj

CACHE = '_v342_fotos.json'


def fotos():
    if os.path.exists(CACHE):
        return json.load(open(CACHE, encoding='utf-8'))
    out = {}
    for dia, foto in sorted(r331.fotos_por_dia().items()):
        partidos = foto.get('partidos') or []
        n = pj.marcadores_otros(partidos, dia)
        print(dia, 'marcadores rellenados', n)
        out[dia] = dict(foto, partidos=partidos)
    json.dump(out, open(CACHE, 'w', encoding='utf-8'), ensure_ascii=False)
    return out


if __name__ == '__main__':
    fotos()
