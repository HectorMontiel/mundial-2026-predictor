#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v99.2 — IDF en la MLB, con el mismo protocolo que en tenis y KBO.

La MLB tiene 9 features y ya incluye racha (`DIFF_STREAK`) y medias móviles de
carreras. Igual que en tenis con `DIFF_FORMA10`, la pregunta es si el IDF
—desviación respecto a lo que el ELO predice— aporta ENCIMA de eso.

Se mide sobre el `_dataset` del motor desplegado, sin tocarlo.
"""
import io
import json
import sys

import numpy as np
import pandas as pd

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

import indice_forma as idf_mod

N_PLIEGUES = 5
BOOT = 4000
SEMILLA = 992
VENTANAS = (5, 10, 15)


def main():
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import log_loss
    from sklearn.preprocessing import StandardScaler

    from engines.mlb_engine import MLBEngine

    df = pd.read_csv('historico_mlb.csv', parse_dates=['date'])
    X, y, tot, fechas, estado = MLBEngine._dataset(df)
    print(f'MLB: {len(X)} juegos utilizables ({fechas.min().date()} → {fechas.max().date()})')

    ident = pd.DataFrame(estado['filas'], columns=['date', 'home', 'away'])
    ident['date'] = pd.to_datetime(ident['date'])
    ident['ELO_A'] = 1500.0 + X[:, 0] * 50.0
    ident['ELO_B'] = 1500.0 - X[:, 0] * 50.0
    ident['y'] = y

    n = len(X)
    bordes = [int(n * (0.5 + 0.1 * i)) for i in range(N_PLIEGUES + 1)]
    juicio_desde = 3

    def oos(M):
        p = np.full(n, np.nan)
        for i in range(N_PLIEGUES):
            ini, fin = bordes[i], bordes[i + 1]
            sc = StandardScaler().fit(M[:ini])
            m = LogisticRegression(max_iter=3000).fit(sc.transform(M[:ini]), y[:ini])
            p[ini:fin] = m.predict_proba(sc.transform(M[ini:fin]))[:, 1]
        return p

    variantes = {'A · desplegado': X}
    for v in VENTANAS:
        idf = idf_mod.idf_por_participante(
            ident, 'home', 'away', 'ELO_A', 'ELO_B', 'y',
            ventana=v)['DIFF_IDF'].to_numpy()
        variantes[f'B · ventana {v}'] = np.column_stack([X, idf])

    # ELECCIÓN en pliegues tempranos
    print(f"   {'variante':<18}{'ll elección':>13}")
    elec = {}
    for nombre, M in variantes.items():
        p = oos(M)
        msk = ~np.isnan(p) & (np.arange(n) < bordes[juicio_desde])
        ll = float(log_loss(y[msk], np.column_stack([1 - p[msk], p[msk]]), labels=[0, 1]))
        elec[nombre] = (ll, M, p)
        print(f'   {nombre:<18}{ll:>13.5f}')
    cand = {k: v for k, v in elec.items() if k.startswith('B')}
    mejor = min(cand, key=lambda k: cand[k][0])
    print(f'   -> elegida: {mejor}')

    # JUICIO
    print(f"   {'JUICIO':<18}{'log-loss':>11}{'acc':>9}{'Brier':>9}")
    out = {}
    for nombre in ('A · desplegado', mejor):
        p = elec[nombre][2]
        msk = ~np.isnan(p) & (np.arange(n) >= bordes[juicio_desde])
        yy, pp = y[msk], p[msk]
        ll = float(log_loss(yy, np.column_stack([1 - pp, pp]), labels=[0, 1]))
        acc = float(((pp >= 0.5) == yy).mean())
        br = float(np.mean((pp - yy) ** 2))
        print(f'   {nombre:<18}{ll:>11.5f}{acc:>9.4f}{br:>9.4f}')
        out[nombre] = {'ll': ll, 'acc': acc, 'brier': br}

    pa = elec['A · desplegado'][2]
    pb = elec[mejor][2]
    msk = ~np.isnan(pa) & (np.arange(n) >= bordes[juicio_desde])
    yy = y[msk]
    ea = -(yy * np.log(np.clip(pa[msk], 1e-9, 1)) + (1 - yy) * np.log(np.clip(1 - pa[msk], 1e-9, 1)))
    eb = -(yy * np.log(np.clip(pb[msk], 1e-9, 1)) + (1 - yy) * np.log(np.clip(1 - pb[msk], 1e-9, 1)))
    d = ea - eb
    rng = np.random.default_rng(SEMILLA)
    bt = np.array([d[rng.integers(0, len(d), len(d))].mean() for _ in range(BOOT)])
    p5 = float(np.percentile(bt, 5))
    prob = float((bt > 0).mean())
    print(f'   n={len(d)} · mejora {d.mean():+.5f} · p5 {p5:+.5f} · P(>0) {prob:.1%}')
    veredicto = 'ADOPTAR' if p5 > 0 else 'RECHAZAR'
    print(f'   VEREDICTO: {veredicto}')

    json.dump({'elegida': mejor, 'n': int(len(d)), 'mejora': float(d.mean()),
               'p5': p5, 'prob_positiva': prob, 'metricas': out,
               'veredicto': veredicto},
              open('_v992_ab_idf_mlb.json', 'w'), indent=1)
    print('-> _v992_ab_idf_mlb.json')


if __name__ == '__main__':
    main()
