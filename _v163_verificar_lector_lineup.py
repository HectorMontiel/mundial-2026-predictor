#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v163 — CONTROL DEL LECTOR DE ALINEACIÓN.

`_v163_sondeo_fotmob_lineup.py` devolvió cero onces en 50 partidos por jugar.
Antes de escribir eso en la bitácora hay que descartar la explicación aburrida:
que el lector esté mirando la ruta equivocada del JSON y devuelva cero SIEMPRE.

Un sondeo que no encuentra nada y un lector roto se parecen demasiado.

Así que se le pasa el mismo lector a partidos ya TERMINADOS, donde la
alineación tiene que estar. Si ahí sale 22 y en los futuros 0, el sondeo vale.
Si ahí también sale 0, el sondeo no medía nada y hay que arreglar el lector.

    python _v163_verificar_lector_lineup.py
"""
import json
import logging
import sys
import warnings

import pandas as pd

warnings.filterwarnings('ignore')
logging.basicConfig(level=logging.ERROR)
for _f in (sys.stdout, sys.stderr):
    try:
        _f.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass


def main():
    import arbitro_partido as ap
    from _v163_sondeo_fotmob_lineup import _once

    ayer = (pd.Timestamp.now(tz='UTC') - pd.Timedelta(days=1)).strftime('%Y-%m-%d')
    idx = ap.indice_dia(ayer)
    print('%s: %d partidos' % (ayer, len(idx)))
    vistos, con_once = 0, 0
    for m in idx[:12]:
        d = ap._get('%s/matchDetails?matchId=%s' % (ap.BASE, m['match_id']))
        if not d:
            continue
        n, optimal, claves = _once(d)
        vistos += 1
        con_once += int(n >= 22)
        print('   %-38s once=%3d  probable=%-5s  claves=%s'
              % (('%s-%s' % (m['home'], m['away']))[:38], n, optimal,
                 claves[:8]))
        if vistos == 1 and n < 22:
            # el lector no encuentra nada donde tiene que haberlo: se vuelca la
            # estructura para ver por dónde ha cambiado FotMob el bloque
            c = (d.get('content') or {})
            print('\n   claves de content:', sorted(c.keys()))
            lu = c.get('lineup')
            print('   tipo de content.lineup:', type(lu).__name__)
            if isinstance(lu, dict):
                print('   claves de content.lineup:', sorted(lu.keys()))
                print('   muestra:', json.dumps(lu, ensure_ascii=False)[:900])
    print()
    print('TERMINADOS con once según el lector: %d de %d' % (con_once, vistos))
    if vistos and con_once == 0:
        print('EL LECTOR ESTÁ ROTO: el sondeo de partidos futuros no vale.')
        return 1
    print('El lector funciona: el cero de los partidos por jugar es real.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
