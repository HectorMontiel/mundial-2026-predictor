#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v351 — la semilla de `capa1_historial.json`: lo que la Capa 1 enseñó del
3 al 9-oct, liquidado con los marcadores reales.

Reproduce cada foto de `pronostico_dia.json` del git (una cada ~2 h): 🏆 y
🔷 con `lo_mejor` sobre los pronósticos de esa foto y 💰 los errores de
precio que esa foto daba por buenos, sólo de partidos que aún no habían
empezado (lo mismo que hace `anunciadas` en cada precálculo). 🎯 las
probables no se pueden rehacer: salen del tablero de cuotas de ese momento,
que no se guarda; empiezan a contar desde hoy. Después liquida con
`capa1_resultados.liquidar` (FotMob y Flashscore; el feed de Flashscore sólo
llega a una semana atrás).
"""
import datetime as dt
import json
import os
import subprocess
import sys
import tempfile

import anunciadas as an
import capa1_resultados as cr
import probables

DESDE = '2026-10-03T00:00'


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    probables.barrer = lambda *a, **k: []          # el tablero de entonces no está
    hs = subprocess.run(['git', 'log', '--reverse', '--format=%H %cI', '--since=' + DESDE,
                         'origin/main', '--', 'pronostico_dia.json'],
                        capture_output=True, text=True).stdout.split('\n')
    partidos = {}
    n = 0
    for linea in [x for x in hs if x.strip()]:
        h, cuando = linea.split()
        try:
            doc = json.loads(subprocess.run(['git', 'show', h + ':pronostico_dia.json'],
                                            capture_output=True).stdout.decode('utf-8'))
        except Exception:
            continue
        ts = dt.datetime.fromisoformat(cuando).astimezone(dt.timezone.utc)
        n += an._acumular_capa1(doc, partidos, ts)
    print('fotos', len(hs), 'entradas', n, 'partidos', len(partidos))
    tmp = os.path.join(tempfile.mkdtemp(), 'anunciadas.json')
    json.dump({'version': 1, 'partidos': partidos}, open(tmp, 'w', encoding='utf-8'),
              ensure_ascii=False)
    liq = cr.liquidar(tmp, cr.FICHERO)
    d = cr.cargar(cr.FICHERO)
    print('liquidadas', liq)
    por = {}
    for e in partidos.values():
        for x in e.get('capa1') or []:
            por.setdefault(x['nivel'], [0, 0])[0] += 1
    for f in d.get('filas') or []:
        por.setdefault(f['nivel'], [0, 0])[1] += 1
    for nivel, (tot, liqd) in por.items():
        v, r = cr.cuenta(nivel, '2026-01-01', '2099-01-01')
        print(nivel, 'enseñadas', tot, 'liquidadas', liqd, '✅', v, '❌', r,
              '%.1f %%' % (100 * v / (v + r)) if v + r else '')


if __name__ == '__main__':
    main()
