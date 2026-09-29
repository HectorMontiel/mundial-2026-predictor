# -*- coding: utf-8 -*-
"""
v312 — RESULTADOS: LO QUE LA APP DICE «METER», ANTES Y AHORA, DÍA POR DÍA.

Lee las dos reproducciones de `_v312_patrones.py` sobre los MISMOS partidos
(20-28 sep): la hecha con el código de la v311 (`V312_ANTES`) y la hecha con
el de la v312 (`V312_DESPUES`), y cuenta el acierto de lo que la tarjeta
enseña como «🎯 meter» en cada una. La regla se eligió con los días 20-26;
el 27 y el 28 (hoy) son la prueba.

Uso: V312_ANTES=… V312_DESPUES=… python _v312_resultados.py
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np
import pandas as pd

SALIDA = '_v312_patrones.json'
ELECCION = ('2026-09-20', '2026-09-21', '2026-09-22', '2026-09-23',
            '2026-09-24', '2026-09-25', '2026-09-26')


def mostradas(ruta: str) -> pd.DataFrame:
    d = pd.read_csv(ruta)
    d = d[d['acierto'].notna()]
    return d[d['mostrada'] & (d['veredicto'] == 'meter')].copy()


def fila(x: pd.DataFrame) -> dict:
    if x.empty:
        return {'apuestas': 0}
    return {'apuestas': int(len(x)), 'partidos': int(x['partido'].nunique()),
            'verdes': int(x['acierto'].sum()),
            'rojos': int(len(x) - x['acierto'].sum()),
            'acierto': round(float(x['acierto'].mean()), 4),
            'prometido': round(float(x['prob_meter'].mean()), 4),
            'roi': round(float((x['acierto'] * x['cuota'] - 1).mean()), 4)}


def boot(a: pd.DataFrame, b: pd.DataFrame, dias, rng, B=2000) -> dict:
    a, b = a[a['dia'].isin(dias)], b[b['dia'].isin(dias)]
    ks = sorted(set(zip(a['dia'], a['partido'])) | set(zip(b['dia'], b['partido'])))
    ga = a.groupby(['dia', 'partido'])['acierto'].agg(['sum', 'size'])
    gb = b.groupby(['dia', 'partido'])['acierto'].agg(['sum', 'size'])
    A = np.array([ga.loc[k].values if k in ga.index else (0, 0) for k in ks], float)
    Bv = np.array([gb.loc[k].values if k in gb.index else (0, 0) for k in ks], float)
    dif = []
    for _ in range(B):
        i = rng.integers(0, len(ks), len(ks))
        dif.append(Bv[i, 0].sum() / max(Bv[i, 1].sum(), 1)
                   - A[i, 0].sum() / max(A[i, 1].sum(), 1))
    return {'mejora_pts': round(100 * float(np.mean(dif)), 2),
            'p5_pts': round(100 * float(np.percentile(dif, 5)), 2)}


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    a = mostradas(os.environ['V312_ANTES'])
    b = mostradas(os.environ['V312_DESPUES'])
    dias = sorted(set(a['dia']) | set(b['dia']))
    prueba = [x for x in dias if x not in ELECCION]
    hoy = dias[-1]
    rng = np.random.default_rng(312)
    doc = {'por_dia': {d: {'antes': fila(a[a['dia'] == d]),
                           'ahora': fila(b[b['dia'] == d])} for d in dias},
           'eleccion': {'antes': fila(a[a['dia'].isin(ELECCION)]),
                        'ahora': fila(b[b['dia'].isin(ELECCION)]),
                        'bootstrap': boot(a, b, ELECCION, rng)},
           'prueba': {'dias': prueba, 'antes': fila(a[a['dia'].isin(prueba)]),
                      'ahora': fila(b[b['dia'].isin(prueba)]),
                      'bootstrap': boot(a, b, prueba, rng)},
           'hoy': {'dia': hoy, 'antes': fila(a[a['dia'] == hoy]),
                   'ahora': fila(b[b['dia'] == hoy])},
           'total': {'antes': fila(a), 'ahora': fila(b)},
           'ahora_por_mercado': {m: fila(x) for m, x in b.groupby('mercado')}}
    json.dump(doc, open(SALIDA, 'w', encoding='utf-8'), ensure_ascii=False,
              indent=1)
    for d in dias:
        x, y = doc['por_dia'][d]['antes'], doc['por_dia'][d]['ahora']
        print('%s  antes %3s apuestas %5s  →  ahora %3s apuestas %5s'
              % (d, x.get('apuestas'), '%.1f%%' % (100 * x['acierto'])
                 if x.get('apuestas') else '—', y.get('apuestas'),
                 '%.1f%%' % (100 * y['acierto']) if y.get('apuestas') else '—'))
    for k in ('eleccion', 'prueba', 'total'):
        print(k, json.dumps(doc[k], ensure_ascii=False))
    print('hoy', json.dumps(doc['hoy'], ensure_ascii=False))


if __name__ == '__main__':
    main()
