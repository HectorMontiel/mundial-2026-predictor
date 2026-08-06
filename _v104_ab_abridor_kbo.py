#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v104 — ¿Aporta la calidad del abridor (ERA/WHIP de Naver) al modelo de la KBO?

Contexto
--------
El modelo desplegado de la KBO usa tres columnas: `DIFF_ELO`, `DIFF_PIT_RA` (el
diferencial de carreras del abridor, derivado del propio histórico) y
`DIFF_IDF`. Bate al ELO en 1 pp pero NO al mercado (ROI −9 a −13 %), y la
hipótesis de la v98 era que faltaban los datos que las casas sí miran.

`kbo_preview.py` (v104) trae ahora, para cada partido y **a fecha del partido**,
la ERA, el WHIP y las tasas por 9 entradas del abridor de cada equipo, más el
número de relevistas disponibles. Es información pre-partido: no hay fuga.

La pregunta dura es la de siempre: ¿aporta ENCIMA de lo que el modelo ya tiene?
`DIFF_PIT_RA` ya es una medida de abridor, así que el ERA podría ser redundante.

Protocolo: walk-forward, elección en pliegues tempranos, juicio en los tardíos,
bootstrap pareado y veredicto por p5.
"""
import json
import os
import sys
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings('ignore')
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

N_PLIEGUES = 6
JUICIO_DESDE = 2
BOOT = 4000
SEMILLA = 104
SALIDA = '_v104_ab_abridor_kbo.json'

# diferencias local−visitante de las señales del abridor
PARES = [('sp_era', True), ('sp_whip', True), ('sp_k9', False),
         ('sp_bb9', True), ('sp_hr9', True), ('bullpen_n', False)]


def _wf(X, y, bordes):
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    p = np.full(len(y), np.nan)
    for i in range(N_PLIEGUES):
        ini, fin = bordes[i], bordes[i + 1]
        if ini < 150 or len(np.unique(y[:ini])) < 2:
            continue
        sc = StandardScaler().fit(X[:ini])
        m = LogisticRegression(max_iter=3000).fit(sc.transform(X[:ini]), y[:ini])
        p[ini:fin] = m.predict_proba(sc.transform(X[ini:fin]))[:, 1]
    return p


def main():
    if not os.path.exists('kbo_preview.csv'):
        print('falta kbo_preview.csv — ejecuta antes kbo_preview.py')
        return
    pv = pd.read_csv('kbo_preview.csv')
    pv = pv[(pv['home_team'].astype(str) != '') &
            (pv['away_team'].astype(str) != '')]
    hist = pd.read_csv('historico_kbo.csv')
    hist['fecha'] = pd.to_datetime(hist['date'], errors='coerce').dt.strftime('%Y-%m-%d')
    d = hist.merge(pv, on=['fecha', 'home_team', 'away_team'], how='inner')
    d = d[d['home_runs'] != d['away_runs']].copy()
    d = d.sort_values('fecha', kind='stable').reset_index(drop=True)
    print(f'{len(hist)} partidos en el histórico · {len(pv)} con preview · '
          f'{len(d)} cruzados y con ganador')
    if len(d) < 600:
        print('muestra insuficiente para juzgar; se aborta en vez de publicar '
              'un veredicto sobre ruido')
        json.dump({'veredicto': 'SIN MUESTRA', 'n': int(len(d))},
                  open(SALIDA, 'w', encoding='utf-8'), indent=1)
        return

    y = (d['home_runs'] > d['away_runs']).astype(float).to_numpy()
    n = len(d)
    bordes = [int(n * (0.4 + 0.1 * i)) for i in range(N_PLIEGUES + 1)]

    # base: el ELO rodante del propio proyecto (proxy honesto del vector
    # desplegado, que en producción es DIFF_ELO + DIFF_PIT_RA + DIFF_IDF)
    import contexto_previo as cp
    d['res_kbo'] = y
    ea, eb, _ = cp.elo_rodante(d, 'home_team', 'away_team', 'res_kbo',
                               ventaja_a=cp.ELO_VENTAJA_LOCAL)
    base = ((ea - eb) / cp.ESCALA_ELO).reshape(-1, 1)

    extras, nombres = [], []
    for col, invertir in PARES:
        h = pd.to_numeric(d.get(f'home_{col}'), errors='coerce')
        a = pd.to_numeric(d.get(f'away_{col}'), errors='coerce')
        if h is None or a is None or h.isna().all():
            continue
        # ERA/WHIP/BB9/HR9: MENOS es mejor, así que la diferencia se invierte
        # para que en todas las columnas «más alto» signifique «mejor el local»
        v = (a - h) if invertir else (h - a)
        extras.append(v.fillna(0.0).to_numpy(dtype=float))
        nombres.append(col)
    X_extra = np.column_stack(extras)
    print(f'features de abridor disponibles: {nombres}')

    pa = _wf(base, y, bordes)
    pb = _wf(np.column_stack([base, X_extra]), y, bordes)
    msk = ~np.isnan(pa) & ~np.isnan(pb) & (np.arange(n) >= bordes[JUICIO_DESDE])
    yy = y[msk]

    def ll(p):
        q = np.clip(p[msk], 1e-9, 1 - 1e-9)
        return -(yy * np.log(q) + (1 - yy) * np.log(1 - q))

    a_, b_ = ll(pa), ll(pb)
    dif = a_ - b_
    rng = np.random.default_rng(SEMILLA)
    bt = np.array([dif[rng.integers(0, len(dif), len(dif))].mean()
                   for _ in range(BOOT)])
    p5 = float(np.percentile(bt, 5))
    acc_a = float(((pa[msk] >= .5) == yy).mean())
    acc_b = float(((pb[msk] >= .5) == yy).mean())
    ver = 'ADOPTAR' if p5 > 0 and acc_b >= acc_a - 0.002 else 'RECHAZAR'
    print(f'\nn juzgados = {int(msk.sum())}')
    print(f'  base (ELO)            log-loss {a_.mean():.5f} · acierto {acc_a:.4f}')
    print(f'  base + abridor        log-loss {b_.mean():.5f} · acierto {acc_b:.4f}')
    print(f'  mejora {dif.mean():+.6f} · p5 {p5:+.6f} · {ver}')

    # y columna a columna, para saber QUÉ aporta
    print('\naporte de cada señal por separado:')
    detalle = {}
    for i, nom in enumerate(nombres):
        pb1 = _wf(np.column_stack([base, extras[i]]), y, bordes)
        m1 = ~np.isnan(pa) & ~np.isnan(pb1) & (np.arange(n) >= bordes[JUICIO_DESDE])
        yy1 = y[m1]
        q0 = np.clip(pa[m1], 1e-9, 1 - 1e-9)
        q1 = np.clip(pb1[m1], 1e-9, 1 - 1e-9)
        e0 = -(yy1 * np.log(q0) + (1 - yy1) * np.log(1 - q0))
        e1 = -(yy1 * np.log(q1) + (1 - yy1) * np.log(1 - q1))
        dd = e0 - e1
        bt1 = np.array([dd[rng.integers(0, len(dd), len(dd))].mean()
                        for _ in range(1500)])
        p51 = float(np.percentile(bt1, 5))
        print(f'  {nom:<12} mejora {dd.mean():+.6f} · p5 {p51:+.6f} · '
              f'{"ADOPTAR" if p51 > 0 else "RECHAZAR"}')
        detalle[nom] = {'mejora': float(dd.mean()), 'p5': p51}

    json.dump({'n': int(msk.sum()), 'll_base': float(a_.mean()),
               'll_con_abridor': float(b_.mean()), 'mejora': float(dif.mean()),
               'p5': p5, 'acc_base': acc_a, 'acc_con': acc_b,
               'veredicto': ver, 'por_senal': detalle},
              open(SALIDA, 'w', encoding='utf-8'), indent=1, ensure_ascii=False)
    print(f'\n-> {SALIDA}')


if __name__ == '__main__':
    main()
