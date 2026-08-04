#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v97 — ¿Merece la Leagues Cup un modelo, y entrenado con qué?

Se juzga SÓLO sobre partidos de Leagues Cup (que es lo que se va a predecir),
por ediciones: se entrena con todo lo anterior a la edición y se juzga esa
edición entera. Ediciones con volumen: 2023 (77), 2024 (77) y 2025 (62).

Se comparan tres estrategias:
  A. AGRUPADO  — ELO y modelo sobre MLS + Liga MX + Leagues Cup.
  B. SOLO LC   — ELO y modelo únicamente con partidos de Leagues Cup.
  C. ELO       — línea base: gana quien tenga más ELO (el del agrupado).

La pregunta que decide el despliegue es la del proyecto desde la v13: ¿bate
alguna a la línea base ELO fuera de muestra?
"""
import io
import json
import sys

import numpy as np
import pandas as pd

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import leagues_cup as lc

EDICIONES = (2023, 2024, 2025)
BOOT = 4000
SEMILLA = 97


def elo_cronologico(df, k=24.0):
    """ELO del proyecto (`league_engine._elo_diff_liga`), devuelto por fila."""
    elo, diffs = {}, np.zeros(len(df))
    for i, f in enumerate(df.itertuples(index=False)):
        h, a = f.home_team, f.away_team
        rh, ra = elo.get(h, 1500.0), elo.get(a, 1500.0)
        diffs[i] = rh - ra
        eh = 1 / (1 + 10 ** ((ra - rh) / 400))
        sh = 1.0 if f.home_goals > f.away_goals else (0.5 if f.home_goals == f.away_goals else 0.0)
        elo[h] = rh + k * (sh - eh)
        elo[a] = ra + k * ((1 - sh) - (1 - eh))
    return diffs


def features(df):
    """DIFF_ELO + forma reciente (puntos por partido de los últimos 5)."""
    d = df.reset_index(drop=True).copy()
    d['DIFF_ELO'] = elo_cronologico(d)
    ppg, X = {}, []
    for f in d.itertuples(index=False):
        h, a = f.home_team, f.away_team
        ph = np.mean(ppg.get(h, [])[-5:]) if ppg.get(h) else 1.3
        pa = np.mean(ppg.get(a, [])[-5:]) if ppg.get(a) else 1.3
        X.append([f.DIFF_ELO / 100.0, ph - pa, ph + pa])
        rh = 3 if f.home_goals > f.away_goals else (1 if f.home_goals == f.away_goals else 0)
        ppg.setdefault(h, []).append(rh)
        ppg.setdefault(a, []).append(3 - rh if rh != 1 else 1)
    d['_X'] = list(np.array(X))
    return d


def etiqueta(f):
    return 0 if f.home_goals > f.away_goals else (1 if f.home_goals == f.away_goals else 2)


def main():
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import accuracy_score, log_loss
    from sklearn.preprocessing import StandardScaler

    agr = features(lc.historico(con_ligas=True))
    solo = features(lc.historico(con_ligas=False))
    agr['anio'] = agr['date'].dt.year
    solo['anio'] = solo['date'].dt.year

    print('agrupado :', len(agr), 'partidos ·', agr['competicion'].value_counts().to_dict())
    print('solo LC  :', len(solo), 'partidos')
    res_lc = agr[agr.competicion == 'leagues_cup']
    rep = res_lc.apply(etiqueta, axis=1).value_counts(normalize=True).sort_index()
    print('reparto 1X2 en Leagues Cup: local %.3f  empate %.3f  visitante %.3f'
          % (rep.get(0, 0), rep.get(1, 0), rep.get(2, 0)))
    print()

    filas, ok_agr, ok_solo, ok_elo = [], [], [], []
    for ed in EDICIONES:
        te = agr[(agr.competicion == 'leagues_cup') & (agr.anio == ed)]
        if te.empty:
            continue
        idx_te = te.index
        y_te = np.array([etiqueta(f) for f in te.itertuples(index=False)])

        # --- A: agrupado -------------------------------------------------
        tr = agr[(agr.date < te.date.min())]
        Xtr = np.vstack(tr['_X'].values); ytr = np.array([etiqueta(f) for f in tr.itertuples(index=False)])
        Xte = np.vstack(te['_X'].values)
        sc = StandardScaler().fit(Xtr)
        m = LogisticRegression(max_iter=2000, multi_class='multinomial').fit(sc.transform(Xtr), ytr)
        p_a = m.predict_proba(sc.transform(Xte))
        a_agr = m.predict(sc.transform(Xte)) == y_te

        # --- B: solo Leagues Cup -----------------------------------------
        trs = solo[solo.date < te.date.min()]
        if len(trs) >= 40:
            Xs = np.vstack(trs['_X'].values); ys = np.array([etiqueta(f) for f in trs.itertuples(index=False)])
            tes = solo[solo.anio == ed]
            Xts = np.vstack(tes['_X'].values); yts = np.array([etiqueta(f) for f in tes.itertuples(index=False)])
            scs = StandardScaler().fit(Xs)
            ms = LogisticRegression(max_iter=2000, multi_class='multinomial').fit(scs.transform(Xs), ys)
            p_b = ms.predict_proba(scs.transform(Xts))
            a_solo = ms.predict(scs.transform(Xts)) == yts
            ll_b = log_loss(yts, p_b, labels=[0, 1, 2])
        else:
            a_solo, ll_b = np.array([]), float('nan')

        # --- C: ELO ------------------------------------------------------
        a_elo = (np.where(Xte[:, 0] > 0, 0, 2)) == y_te

        ll_a = log_loss(y_te, p_a, labels=[0, 1, 2])
        filas.append({'edicion': ed, 'n': int(len(te)),
                      'acc_agrupado': round(float(a_agr.mean()), 4),
                      'acc_solo_lc': round(float(a_solo.mean()), 4) if len(a_solo) else None,
                      'acc_elo': round(float(a_elo.mean()), 4),
                      'll_agrupado': round(float(ll_a), 4),
                      'll_solo_lc': round(float(ll_b), 4) if ll_b == ll_b else None})
        ok_agr.append(a_agr); ok_elo.append(a_elo)
        if len(a_solo):
            ok_solo.append(a_solo)
        print(f"  {ed}: n={len(te):>3}  agrupado {a_agr.mean():.4f} (ll {ll_a:.4f})  "
              f"solo-LC {a_solo.mean() if len(a_solo) else float('nan'):.4f}  "
              f"ELO {a_elo.mean():.4f}")

    A = np.concatenate(ok_agr); E = np.concatenate(ok_elo)
    S = np.concatenate(ok_solo) if ok_solo else np.array([])
    rng = np.random.default_rng(SEMILLA)
    dif = A.astype(float) - E.astype(float)
    boot = np.array([dif[rng.integers(0, len(dif), len(dif))].mean() for _ in range(BOOT)])
    p5, p50, p95 = np.percentile(boot, [5, 50, 95])

    print()
    print(f'AGREGADO sobre {len(A)} partidos de Leagues Cup fuera de muestra')
    print(f'  agrupado (MLS+MX+LC) {A.mean():.4f}')
    if len(S):
        print(f'  solo Leagues Cup     {S.mean():.4f}')
    print(f'  ELO (línea base)     {E.mean():.4f}')
    print(f'  ventaja agrupado-ELO {dif.mean():+.4f}  '
          f'(p5 {p5:+.4f} · mediana {p50:+.4f} · p95 {p95:+.4f})')
    print(f'  P(ventaja > 0) = {(boot > 0).mean():.1%}')
    print(f"  ediciones ganadas al ELO: "
          f"{sum(1 for f in filas if f['acc_agrupado'] > f['acc_elo'])}/{len(filas)}")

    json.dump({'ediciones': filas, 'n': int(len(A)),
               'acc_agrupado': round(float(A.mean()), 4),
               'acc_solo_lc': round(float(S.mean()), 4) if len(S) else None,
               'acc_elo': round(float(E.mean()), 4),
               'ventaja': round(float(dif.mean()), 4),
               'p5': round(float(p5), 4), 'p50': round(float(p50), 4),
               'p95': round(float(p95), 4),
               'prob_positiva': round(float((boot > 0).mean()), 4)},
              open('_v97_wf_leagues_cup.json', 'w'), indent=1)
    print('\n-> _v97_wf_leagues_cup.json')


if __name__ == '__main__':
    main()
