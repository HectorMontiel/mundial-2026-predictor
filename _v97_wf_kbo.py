#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v97 — Walk-forward de la KBO contra su línea base.

Por qué no basta el 80/20 del entrenamiento
-------------------------------------------
`KBOEngine.entrenar` parte el histórico en 80/20 y reporta 54,35 % frente a un
ELO de 53,68 %. Eso es UNA ventana y una diferencia de 0,67 pp: con ~2.500
juegos de validación, el error típico de una proporción ronda el 1 %, así que
esa cifra sola no distingue «el modelo aporta» de «tuvo suerte en el corte».

Aquí se hace lo que el proyecto exige desde la v13: pliegues cronológicos
sucesivos (entrenar con el pasado, juzgar el futuro inmediato) y bootstrap
sobre la diferencia por partido — que es lo que de verdad importa, porque
modelo y ELO aciertan los mismos partidos fáciles y la comparación no pareada
infla el error.
"""
import io
import json
import sys

import numpy as np
import pandas as pd

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from engines.kbo_engine import KBOEngine

N_PLIEGUES = 5
BOOT = 4000
SEMILLA = 97


def construir_modelo():
    from sklearn.calibration import CalibratedClassifierCV
    from sklearn.ensemble import RandomForestClassifier, VotingClassifier
    from lightgbm import LGBMClassifier
    from xgboost import XGBClassifier
    vc = VotingClassifier([
        ('xgb', XGBClassifier(n_estimators=200, max_depth=4,
                              learning_rate=0.05, verbosity=0)),
        ('lgbm', LGBMClassifier(n_estimators=200, max_depth=4,
                                learning_rate=0.05, verbose=-1)),
        ('rf', RandomForestClassifier(n_estimators=200, max_depth=8,
                                      random_state=42))], voting='soft')
    return CalibratedClassifierCV(vc, method='isotonic', cv=3)


def main():
    from sklearn.metrics import log_loss
    from sklearn.preprocessing import StandardScaler

    df = pd.read_csv('historico_kbo.csv', parse_dates=['date'])
    X, y, tot, fechas, _ = KBOEngine._dataset(df)
    print(f'dataset: {len(X)} juegos  {fechas.min().date()} .. {fechas.max().date()}')

    orden = np.argsort(fechas.values, kind='stable')
    X, y, fechas = X[orden], y[orden], fechas.iloc[orden].reset_index(drop=True)

    n = len(X)
    # pliegues cronologicos: se entrena con todo lo anterior
    bordes = [int(n * (0.5 + 0.1 * i)) for i in range(N_PLIEGUES + 1)]
    filas = []
    ac_mod, ac_elo, ac_loc = [], [], []
    for i in range(N_PLIEGUES):
        ini, fin = bordes[i], bordes[i + 1]
        tr = slice(0, ini)
        sc = StandardScaler().fit(X[tr])
        mod = construir_modelo().fit(sc.transform(X[tr]), y[tr])
        p = mod.predict_proba(sc.transform(X[ini:fin]))[:, list(mod.classes_).index(1)]
        yv = y[ini:fin]
        a_mod = (p >= 0.5).astype(int) == yv
        a_elo = (X[ini:fin, 0] > 0).astype(int) == yv
        a_loc = np.ones_like(yv) == yv        # "gana siempre el local"
        ll_mod = log_loss(yv, np.column_stack([1 - p, p]), labels=[0, 1])
        # log-loss del ELO convertido a probabilidad con una logistica simple
        # ajustada SOLO en el tramo de entrenamiento (si no, seria fuga)
        from sklearn.linear_model import LogisticRegression
        lr = LogisticRegression().fit(X[tr][:, [0]], y[tr])
        p_elo = lr.predict_proba(X[ini:fin][:, [0]])[:, 1]
        ll_elo = log_loss(yv, np.column_stack([1 - p_elo, p_elo]), labels=[0, 1])
        filas.append({
            'pliegue': i + 1, 'n': int(fin - ini),
            'desde': str(fechas.iloc[ini].date()), 'hasta': str(fechas.iloc[fin - 1].date()),
            'acc_modelo': round(float(a_mod.mean()), 4),
            'acc_elo': round(float(a_elo.mean()), 4),
            'acc_local': round(float(a_loc.mean()), 4),
            'll_modelo': round(float(ll_mod), 4), 'll_elo': round(float(ll_elo), 4)})
        ac_mod.append(a_mod); ac_elo.append(a_elo); ac_loc.append(a_loc)
        print(f"  pliegue {i+1}: n={fin-ini:>5} {filas[-1]['desde']}..{filas[-1]['hasta']}  "
              f"modelo {a_mod.mean():.4f}  ELO {a_elo.mean():.4f}  local {a_loc.mean():.4f}  "
              f"ll {ll_mod:.4f} vs {ll_elo:.4f}")

    am = np.concatenate(ac_mod); ae = np.concatenate(ac_elo); al = np.concatenate(ac_loc)
    dif = am.astype(float) - ae.astype(float)          # pareado por partido
    rng = np.random.default_rng(SEMILLA)
    muestras = np.array([dif[rng.integers(0, len(dif), len(dif))].mean()
                         for _ in range(BOOT)])
    p5, p50, p95 = np.percentile(muestras, [5, 50, 95])
    frac_pos = float((muestras > 0).mean())

    print()
    print(f'AGREGADO fuera de muestra (n={len(am)})')
    print(f'  modelo        {am.mean():.4f}')
    print(f'  ELO           {ae.mean():.4f}')
    print(f'  siempre local {al.mean():.4f}')
    print(f'  ventaja modelo-ELO  {dif.mean():+.4f}  '
          f'(bootstrap p5 {p5:+.4f} · mediana {p50:+.4f} · p95 {p95:+.4f})')
    print(f'  P(ventaja > 0) = {frac_pos:.1%}')
    print(f'  pliegues en los que el modelo gana al ELO: '
          f"{sum(1 for f in filas if f['acc_modelo'] > f['acc_elo'])}/{N_PLIEGUES}")

    salida = {'n_total': int(len(am)), 'pliegues': filas,
              'acc_modelo': round(float(am.mean()), 4),
              'acc_elo': round(float(ae.mean()), 4),
              'acc_local': round(float(al.mean()), 4),
              'ventaja': round(float(dif.mean()), 4),
              'bootstrap_p5': round(float(p5), 4),
              'bootstrap_p50': round(float(p50), 4),
              'bootstrap_p95': round(float(p95), 4),
              'prob_ventaja_positiva': round(frac_pos, 4),
              'pliegues_ganados': sum(1 for f in filas
                                      if f['acc_modelo'] > f['acc_elo'])}
    json.dump(salida, open('_v97_wf_kbo.json', 'w'), indent=1)
    print('\n-> _v97_wf_kbo.json')


if __name__ == '__main__':
    main()
