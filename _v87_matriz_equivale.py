#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v87 — ¿Es la matriz analítica la misma que la del Monte Carlo de producción?

`build_ledger_handicap` calcula la matriz de marcadores de forma analítica
porque hacerlo como producción (20.000 simulaciones por partido) sobre 47.794
partidos serían mil millones de sorteos.

Sustituir un método por otro sin comprobarlo sería exactamente el tipo de
atajo que invalida una medición. Se comparan las dos sobre partidos reales.
"""
import sys

import numpy as np

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

LINEAS = (-2.5, -1.5, -0.5, 0.5, 1.5, 2.5)


def main():
    import pandas as pd
    from build_ledger_handicap import matriz_marcadores, MAX_GOLES
    from prediction_api import PredictionEngine

    tot = pd.read_csv('pick_ledger_totales.csv')
    uno = pd.read_csv('pick_ledger_total.csv')
    uno = uno[uno['deporte'] == 'Fútbol'][
        ['liga', 'match_id', 'p_home', 'p_draw', 'p_away']]
    d = tot.merge(uno, on=['liga', 'match_id'], how='inner')

    rng = np.random.default_rng(87)
    muestra = d.iloc[rng.choice(len(d), 60, replace=False)]

    n = MAX_GOLES + 1
    idx = np.arange(n)
    diff = idx[:, None] - idx[None, :]

    print('=' * 76)
    print('v87 · MATRIZ ANALÍTICA FRENTE AL MONTE CARLO DE PRODUCCIÓN')
    print('=' * 76)
    print(f'  {len(muestra)} partidos reales al azar\n')

    difs_celda, difs_ah = [], {L: [] for L in LINEAS}
    for _, r in muestra.iterrows():
        P = np.array([r['p_home'], r['p_draw'], r['p_away']])
        Ma = matriz_marcadores(float(r['lam_h']), float(r['lam_a']), P)
        Mm, _, _ = PredictionEngine._monte_carlo(
            float(r['lam_h']), float(r['lam_a']), P)
        difs_celda.append(float(np.abs(Ma - Mm).max()))
        for L in LINEAS:
            difs_ah[L].append(abs(float(Ma[diff > -L].sum())
                                  - float(Mm[diff > -L].sum())))

    print(f'  diferencia máxima en una celda de la matriz:')
    print(f'    media {np.mean(difs_celda):.5f} · máx {np.max(difs_celda):.5f}')
    print(f'\n  diferencia en P(el local cubre), por línea:')
    print(f'    {"línea":>8} {"media":>10} {"máx":>10}')
    peor = 0.0
    for L in LINEAS:
        m, mx = np.mean(difs_ah[L]), np.max(difs_ah[L])
        peor = max(peor, mx)
        print(f'    {L:+8.1f} {m:10.5f} {mx:10.5f}')

    # el Monte Carlo tiene 20.000 sorteos: su propio error de muestreo es
    # ~1/sqrt(20000) = 0,0071 en una probabilidad del 50 %
    ruido_mc = 0.5 / np.sqrt(20000)
    print(f'\n  ruido de muestreo del propio Monte Carlo (20.000 sims): '
          f'~{ruido_mc:.5f}')
    print(f'  peor diferencia observada                         : {peor:.5f}')
    veredicto = ('EQUIVALENTES: la diferencia está en el orden del ruido de '
                 'muestreo' if peor < 5 * ruido_mc else
                 'NO equivalentes: la diferencia supera el ruido esperable')
    print(f'\nVEREDICTO: {veredicto}')


if __name__ == '__main__':
    main()
