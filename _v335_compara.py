# -*- coding: utf-8 -*-
"""
v335 — ANTES Y DESPUÉS CON EL CÓDIGO REAL DE LA TARJETA.

Compara dos simulaciones rehechas con `_v324_nada.py --rehacer` sobre los
mismos 765 partidos (20-sep a 6-oct, última foto previa, precios de
Playdoit): la de la regla de hoy y la de la regla nueva. Lo que se «metía»
lo decide la tarjeta de verdad (`modo_modelo.recomendadas` + `metidas`).

Uso: python _v335_compara.py ANTES.csv.gz DESPUES.csv.gz [salida.json]
"""
from __future__ import annotations

import io
import json
import sys

import numpy as np
import pandas as pd

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8',
                              errors='replace')
rng = np.random.default_rng(3353)


def metidas(f):
    d = pd.read_csv(f)
    d = d[d.metida & d.acierto.notna()].copy()
    d['f'] = pd.to_datetime(d.dia)
    return d


def r(s):
    return ('%5.1f %% · %4d · %3d rojos · cuota %.3f · %+5.1f %%'
            % (100 * s.acierto.mean(), len(s), (1 - s.acierto).sum(), s.cuota.mean(),
               100 * ((s.acierto * s.cuota).mean() - 1)))


def main(fa, fn, salida=None):
    A, N = metidas(fa), metidas(fn)
    dias = np.sort(pd.to_datetime(pd.read_csv(fa).dia).unique())
    corte = dias[int(len(dias) * 0.7)]
    out = {}
    for t, ma, mn in (('mirar', A.f < corte, N.f < corte),
                      ('juzgar', A.f >= corte, N.f >= corte),
                      ('todo', A.f.notna(), N.f.notna())):
        print('%-6s ANTES %s   DESPUÉS %s' % (t, r(A[ma]), r(N[mn])))
        out[t] = {'antes': [float(A[ma].acierto.mean()), int(ma.sum()), float(A[ma].cuota.mean())],
                  'despues': [float(N[mn].acierto.mean()), int(mn.sum()), float(N[mn].cuota.mean())]}
    X = A[A.f >= corte].groupby('f').acierto.agg(['sum', 'size'])
    Y = N[N.f >= corte].groupby('f').acierto.agg(['sum', 'size'])
    dd = sorted(set(X.index) | set(Y.index))
    X, Y = X.reindex(dd, fill_value=0).values, Y.reindex(dd, fill_value=0).values
    b = []
    for _ in range(3000):
        q = rng.integers(0, len(dd), len(dd))
        x, y = X[q].sum(0), Y[q].sum(0)
        b.append(y[0] / y[1] - x[0] / x[1])
    print('juzgar: %+.2f pts (p5 %+.2f)' % (100 * np.mean(b), 100 * np.percentile(b, 5)))
    out['boot'] = [100 * np.mean(b), 100 * np.percentile(b, 5)]
    print('\nDÍA POR DÍA (antes → después)')
    out['dias'] = {}
    for d in dias[-10:]:
        a, n = A[A.f == d], N[N.f == d]
        if len(a) + len(n):
            print('  %s  %3d/%3d (%5.1f %%) → %3d/%3d (%5.1f %%)'
                  % (str(d)[:10], a.acierto.sum(), len(a), 100 * a.acierto.mean() if len(a) else 0,
                     n.acierto.sum(), len(n), 100 * n.acierto.mean() if len(n) else 0))
            out['dias'][str(d)[:10]] = [int(a.acierto.sum()), len(a), int(n.acierto.sum()), len(n)]
    print('\nPOR MERCADO (antes → después)')
    for m in sorted(set(A.mercado) | set(N.mercado)):
        a, n = A[A.mercado == m], N[N.mercado == m]
        print('  %-18s %5.1f %% (%3d) → %5.1f %% (%3d)'
              % (m, 100 * a.acierto.mean() if len(a) else float('nan'), len(a),
                 100 * n.acierto.mean() if len(n) else float('nan'), len(n)))
    pa, pn = A.groupby(['dia', 'partido']).size(), N.groupby(['dia', 'partido']).size()
    print('\npartidos con algo que meter: %d → %d' % (len(pa), len(pn)))
    out['partidos'] = [len(pa), len(pn)]
    if salida:
        json.dump(out, open(salida, 'w', encoding='utf-8'), ensure_ascii=False,
                  indent=1, default=float)


if __name__ == '__main__':
    main(*sys.argv[1:4])
