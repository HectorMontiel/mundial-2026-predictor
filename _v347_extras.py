#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v347 — ¿las que también se meten y no caben arriba aciertan igual?

El usuario: «las dos más probables en la tarjeta y las demás que también se
meten (tiros, tarjetas, córners…) en el desplegable de cada partido, con su
probabilidad, sin bajar el 80 % de verdes». La réplica de la tarjeta con el
código de hoy (`_v324_nada.py` → `_v347_candidatas.csv.gz`: 794 partidos de
fútbol del 19-sep en adelante, la última foto antes de cada uno, precios de
Playdoit, liquidados) guarda cada candidata con su motivo ('' = pasa la regla
de «meter») y si la tarjeta la enseñó arriba.

EXTRAS = las que pasan la regla y NO están arriba, una por mercado y lado (la
más probable), sin repetir el mercado de las de arriba — exactamente lo que
pinta `modo_modelo.otras_que_se_meten`. Se compara su acierto con el de las
de arriba, por mitades de fecha y con bootstrap por partido.
"""
import json

import numpy as np
import pandas as pd

rng = np.random.default_rng(347)
d = pd.read_csv('_v347_candidatas.csv.gz', low_memory=False)
d = d[d.acierto.notna()].copy()
d['etq'] = d.etiqueta.fillna('')
arriba = d[d.metida]
usados = set(zip(arriba.partido, arriba.mercado, arriba.etq))
ex = d[(d.motivo.fillna('') == '') & ~d.metida].copy()
ex = ex[[(p, m, e) not in usados for p, m, e in zip(ex.partido, ex.mercado, ex.etq)]]
ex['p'] = ex.ajustada.fillna(ex.prob)
ex = ex.sort_values('p', ascending=False).drop_duplicates(['partido', 'mercado', 'etq'])
dias = sorted(d.dia.unique())
corte = dias[len(dias) // 2]


def res(g):
    return {'n': int(len(g)), 'partidos': int(g.partido.nunique()),
            'acierto': round(float(g.acierto.mean()), 4) if len(g) else None,
            'promete': round(float(g.ajustada.fillna(g.prob).mean()), 4) if len(g) else None,
            'cuota': round(float(g.cuota.mean()), 3) if len(g) else None}


def boot_dif(a, b):
    """acierto(b) − acierto(a), bootstrap por partido (los de los dos)."""
    ps = sorted(set(a.partido) | set(b.partido))
    A = a.groupby('partido').acierto.agg(['sum', 'size']).reindex(ps, fill_value=0)
    B = b.groupby('partido').acierto.agg(['sum', 'size']).reindex(ps, fill_value=0)
    out = []
    for _ in range(4000):
        i = rng.integers(0, len(ps), len(ps))
        nb, na = B['size'].values[i].sum(), A['size'].values[i].sum()
        if na and nb:
            out.append(B['sum'].values[i].sum() / nb - A['sum'].values[i].sum() / na)
    return round(float(np.mean(out)), 4), round(float(np.percentile(out, 5)), 4)


out = {'partidos': int(d.partido.nunique()), 'corte': corte,
       'arriba': res(arriba), 'extras': res(ex),
       'extras_menos_arriba': boot_dif(arriba, ex)}
for tr, f in (('elige', lambda x: x[x.dia < corte]), ('juzga', lambda x: x[x.dia >= corte])):
    out[tr] = {'arriba': res(f(arriba)), 'extras': res(f(ex)),
               'dif': boot_dif(f(arriba), f(ex))}
out['extras_por_mercado'] = {m: res(g) for m, g in ex.groupby('mercado')}
out['extras_por_prob'] = {str(b): res(g) for b, g in ex.groupby(
    pd.cut(ex.p, [0.65, 0.70, 0.75, 0.80, 0.85, 1.0]), observed=True)}
# el marcador si las extras contaran (para saber si diluirían el 80 %)
junto = pd.concat([arriba, ex])
out['si_contaran'] = res(junto)
print(json.dumps(out, ensure_ascii=False, indent=1, default=str))
json.dump(out, open('_v347_extras.json', 'w', encoding='utf-8'),
          ensure_ascii=False, indent=1, default=str)
