#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v99.1 — IDF + factor de parque en la KBO, y la significancia del IDF en tenis.

Dos preguntas:
  1. ¿La mejora del IDF en tenis es real o es ruido? Bootstrap PAREADO sobre la
     diferencia de log-loss partido a partido — no comparar dos medias sueltas,
     que con 20.000 partidos siempre parecen distintas.
  2. ¿Sirven el IDF y el factor de parque en la KBO, donde el problema medido
     es que el modelo está PEOR calibrado que el mercado (Brier 0,2492 vs
     0,2411)?
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

BOOT = 4000
SEMILLA = 991
N_PLIEGUES = 5


def significancia_tenis():
    """Bootstrap pareado de la diferencia de log-loss por partido."""
    from sklearn.linear_model import LogisticRegression

    from _v99_edge_tenis import preparar
    out = {}
    for circuito in ('atp', 'wta'):
        df = preparar(circuito)
        df['ELO_A'] = 1500.0 + df.DIFF_ELO / 2.0
        df['ELO_B'] = 1500.0 - df.DIFF_ELO / 2.0
        idf = idf_mod.idf_por_participante(
            df, 'Player_1', 'Player_2', 'ELO_A', 'ELO_B', 'y',
            ventana=5)['DIFF_IDF'].to_numpy()
        n = len(df)
        bordes = [int(n * (0.4 + 0.1 * i)) for i in range(7)]
        y = df.y.to_numpy()
        base = df[['DIFF_ELO', 'DIFF_ELO_SUP']].to_numpy() / 100.0
        conB = np.column_stack([base, idf])

        def probas(X):
            p = np.full(n, np.nan)
            for i in range(6):
                ini, fin = bordes[i], bordes[i + 1]
                m = LogisticRegression(max_iter=2000).fit(X[:ini], y[:ini])
                p[ini:fin] = m.predict_proba(X[ini:fin])[:, 1]
            return p

        pa, pb = probas(base), probas(conB)
        msk = ~np.isnan(pa) & (np.arange(n) >= bordes[3])   # pliegues de juicio
        ea = -(y[msk] * np.log(np.clip(pa[msk], 1e-9, 1)) +
               (1 - y[msk]) * np.log(np.clip(1 - pa[msk], 1e-9, 1)))
        eb = -(y[msk] * np.log(np.clip(pb[msk], 1e-9, 1)) +
               (1 - y[msk]) * np.log(np.clip(1 - pb[msk], 1e-9, 1)))
        d = ea - eb                     # >0 = B mejor (menos pérdida)
        rng = np.random.default_rng(SEMILLA)
        bt = np.array([d[rng.integers(0, len(d), len(d))].mean() for _ in range(BOOT)])
        p5, p95 = np.percentile(bt, [5, 95])
        print(f'  {circuito.upper()}: n={len(d)} · mejora media de log-loss '
              f'{d.mean():+.5f} · p5 {p5:+.5f} · P(mejora>0) {(bt > 0).mean():.1%}')
        out[circuito] = {'n': int(len(d)), 'mejora': float(d.mean()),
                         'p5': float(p5), 'prob_positiva': float((bt > 0).mean())}
    return out


def kbo():
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import log_loss
    from sklearn.preprocessing import StandardScaler

    from engines.kbo_engine import COLS_MODELO, KBOEngine

    df = pd.read_csv('historico_kbo.csv', parse_dates=['date'])
    dfd = df[df.home_runs != df.away_runs].sort_values('date').reset_index(drop=True)
    X, y, tot, fechas, estado = KBOEngine._dataset(dfd)
    ident = pd.DataFrame(estado['filas'], columns=['date', 'home', 'away'])
    ident['date'] = pd.to_datetime(ident['date'])

    # --- IDF: se necesita el ELO de cada lado en el momento del partido -----
    # `X[:,0]` es (elo_h - elo_a)/100, así que se reconstruye la diferencia.
    ident['ELO_A'] = 1500.0 + X[:, 0] * 100.0 / 2.0
    ident['ELO_B'] = 1500.0 - X[:, 0] * 100.0 / 2.0
    ident['y'] = y
    idf = idf_mod.idf_por_participante(ident, 'home', 'away', 'ELO_A', 'ELO_B',
                                       'y', ventana=10)['DIFF_IDF'].to_numpy()

    # --- factor de parque, cronológico -------------------------------------
    d2 = dfd.copy()
    d2['total_carreras'] = d2.home_runs + d2.away_runs
    fp_todos = idf_mod.factor_parque(d2)
    # sólo las filas que el dataset emitió (necesitan >=5 partidos de historia)
    llave = pd.MultiIndex.from_frame(
        d2[['date', 'home_team', 'away_team']].rename(
            columns={'home_team': 'home', 'away_team': 'away'}))
    serie_fp = pd.Series(fp_todos, index=llave)
    fp = serie_fp.reindex(
        pd.MultiIndex.from_frame(ident[['date', 'home', 'away']])).to_numpy()
    fp = np.where(np.isnan(fp), 1.0, fp)

    n = len(X)
    bordes = [int(n * (0.5 + 0.1 * i)) for i in range(N_PLIEGUES + 1)]
    variantes = {
        'A (desplegado)': X[:, COLS_MODELO],
        'B + IDF': np.column_stack([X[:, COLS_MODELO], idf]),
        'C + parque': np.column_stack([X[:, COLS_MODELO], fp]),
        'D + IDF + parque': np.column_stack([X[:, COLS_MODELO], idf, fp]),
    }
    print(f'  KBO: {n} juegos · factor de parque entre '
          f'{np.nanmin(fp):.3f} y {np.nanmax(fp):.3f}')
    res = {}
    for nombre, M in variantes.items():
        p = np.full(n, np.nan)
        for i in range(N_PLIEGUES):
            ini, fin = bordes[i], bordes[i + 1]
            sc = StandardScaler().fit(M[:ini])
            m = LogisticRegression(max_iter=2000).fit(sc.transform(M[:ini]), y[:ini])
            p[ini:fin] = m.predict_proba(sc.transform(M[ini:fin]))[:, 1]
        msk = ~np.isnan(p)
        ll = float(log_loss(y[msk], np.column_stack([1 - p[msk], p[msk]]), labels=[0, 1]))
        acc = float(((p[msk] >= 0.5) == y[msk]).mean())
        br = float(np.mean((p[msk] - y[msk]) ** 2))
        print(f'    {nombre:<18} log-loss {ll:.5f}  acc {acc:.4f}  Brier {br:.4f}')
        res[nombre] = {'ll': ll, 'acc': acc, 'brier': br, 'p': p, 'msk': msk}

    # contra la cuota de cierre real
    cu = pd.read_csv('cuotas_kbo_cierre.csv')
    ident2 = ident.copy()
    ident2['fecha'] = ident2['date'].dt.strftime('%Y-%m-%d')
    print('    --- contra la cuota de cierre (n cruzados) ---')
    salida = {}
    for nombre, r in res.items():
        t = ident2.copy()
        t['p'] = r['p']
        j = cu.merge(t, on=['fecha', 'home', 'away'], how='inner').dropna(subset=['p'])
        if len(j) < 30:
            continue
        imp = (1 / j.odd_home) / (1 / j.odd_home + 1 / j.odd_away)
        gh = j.y.to_numpy()
        br = float(np.mean((j.p.to_numpy() - gh) ** 2))
        br_m = float(np.mean((imp.to_numpy() - gh) ** 2))
        print(f'    {nombre:<18} n={len(j)} Brier {br:.4f} (mercado {br_m:.4f})')
        salida[nombre] = {'n': int(len(j)), 'brier': br, 'brier_mercado': br_m,
                          'll': r['ll'], 'acc': r['acc']}
    return salida


if __name__ == '__main__':
    print('=== 1) ¿Es real la mejora del IDF en tenis? (bootstrap pareado) ===')
    sig = significancia_tenis()
    print()
    print('=== 2) IDF y factor de parque en la KBO ===')
    k = kbo()
    json.dump({'significancia_tenis': sig, 'kbo': k},
              open('_v991_ab_idf_kbo.json', 'w'), indent=1)
    print('\n-> _v991_ab_idf_kbo.json')
