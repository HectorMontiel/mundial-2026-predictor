#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v97 — Qué familia de modelo merece la KBO.

El walk-forward de `_v97_wf_kbo.py` dice que el ensemble de la MLB NO bate al
ELO en la KBO (54,26 % frente a 54,52 %, p5 −1,31 %, gana 2 pliegues de 5) y
que además empeora el log-loss en 4 de 5. Con 12.687 juegos y 10 equipos que
se enfrentan sin parar, el ELO ya captura casi todo lo que hay que capturar:
el ensemble le está metiendo varianza a cambio de nada.

Es exactamente la situación que el proyecto resolvió en la v70 para las ligas
de fútbol pequeñas con `construir_modelo_familia`: cuando hay poco que
aprender, se aprende con un modelo más simple.

PROTOCOLO (regla de oro 3): la familia se ELIGE mirando sólo los pliegues
tempranos (1-3) y se JUZGA en los tardíos (4-5), que no se han mirado para
decidir. Quedarse con el máximo de un barrido sobre todos los pliegues es
justo la trampa que la v90 documentó seis veces.
"""
import io
import json
import sys

import numpy as np
import pandas as pd

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from engines.kbo_engine import KBOEngine

N_PLIEGUES = 5
ELECCION = (0, 1, 2)          # pliegues 1-3
JUICIO = (3, 4)               # pliegues 4-5
BOOT = 4000
SEMILLA = 97


def familias():
    from sklearn.calibration import CalibratedClassifierCV
    from sklearn.ensemble import RandomForestClassifier, VotingClassifier
    from sklearn.linear_model import LogisticRegression, LogisticRegressionCV
    from sklearn.model_selection import TimeSeriesSplit
    from lightgbm import LGBMClassifier
    from xgboost import XGBClassifier

    def _ensemble():
        vc = VotingClassifier([
            ('xgb', XGBClassifier(n_estimators=200, max_depth=4,
                                  learning_rate=0.05, verbosity=0)),
            ('lgbm', LGBMClassifier(n_estimators=200, max_depth=4,
                                    learning_rate=0.05, verbose=-1)),
            ('rf', RandomForestClassifier(n_estimators=200, max_depth=8,
                                          random_state=42))], voting='soft')
        return CalibratedClassifierCV(vc, method='isotonic', cv=3)

    def _logistica():
        return LogisticRegressionCV(
            Cs=np.logspace(-3, 2, 10), cv=TimeSeriesSplit(n_splits=3),
            penalty='l2', solver='lbfgs', max_iter=3000,
            scoring='neg_log_loss', n_jobs=-1, random_state=42)

    def _gbm():
        return LGBMClassifier(n_estimators=180, num_leaves=7, max_depth=3,
                              learning_rate=0.04, min_child_samples=40,
                              subsample=0.8, subsample_freq=1,
                              colsample_bytree=0.6, reg_lambda=20.0,
                              reg_alpha=1.0, random_state=42, n_jobs=-1,
                              verbose=-1)

    return {
        'ensemble': (_ensemble, None),
        'logistica': (_logistica, None),
        'gbm_regular': (_gbm, None),
        'elo_logit': (lambda: LogisticRegression(max_iter=2000), [0]),
        'elo_pitcher_logit': (lambda: LogisticRegression(max_iter=2000), [0, 5]),
        'base_logit': (lambda: LogisticRegression(max_iter=2000), [0, 1, 2, 5]),
    }


def main():
    from sklearn.metrics import log_loss
    from sklearn.preprocessing import StandardScaler

    df = pd.read_csv('historico_kbo.csv', parse_dates=['date'])
    X, y, tot, fechas, _ = KBOEngine._dataset(df)
    orden = np.argsort(fechas.values, kind='stable')
    X, y, fechas = X[orden], y[orden], fechas.iloc[orden].reset_index(drop=True)
    n = len(X)
    bordes = [int(n * (0.5 + 0.1 * i)) for i in range(N_PLIEGUES + 1)]

    res = {}
    for nombre, (ctor, cols) in familias().items():
        accs, lls, aciertos = [], [], []
        for i in range(N_PLIEGUES):
            ini, fin = bordes[i], bordes[i + 1]
            Xtr, Xva = X[:ini], X[ini:fin]
            if cols is not None:
                Xtr, Xva = Xtr[:, cols], Xva[:, cols]
            sc = StandardScaler().fit(Xtr)
            m = ctor().fit(sc.transform(Xtr), y[:ini])
            p = m.predict_proba(sc.transform(Xva))[:, list(m.classes_).index(1)]
            yv = y[ini:fin]
            ok = (p >= 0.5).astype(int) == yv
            accs.append(float(ok.mean()))
            lls.append(float(log_loss(yv, np.column_stack([1 - p, p]), labels=[0, 1])))
            aciertos.append(ok)
        res[nombre] = {'acc': accs, 'll': lls, 'ok': aciertos}
        print(f"{nombre:<20} acc {' '.join(f'{a:.4f}' for a in accs)}   "
              f"ll {' '.join(f'{l:.4f}' for l in lls)}")

    # linea base ELO puro (sin ajustar nada): signo de DIFF_ELO
    base_ok = []
    for i in range(N_PLIEGUES):
        ini, fin = bordes[i], bordes[i + 1]
        base_ok.append((X[ini:fin, 0] > 0).astype(int) == y[ini:fin])
    print(f"{'ELO (signo)':<20} acc "
          f"{' '.join(f'{o.mean():.4f}' for o in base_ok)}")

    print()
    print('=== ELECCION (pliegues 1-3, log-loss medio) ===')
    ranking = sorted(res.items(), key=lambda kv: np.mean([kv[1]['ll'][i] for i in ELECCION]))
    for nombre, r in ranking:
        print(f"   {nombre:<20} ll={np.mean([r['ll'][i] for i in ELECCION]):.4f}  "
              f"acc={np.mean([r['acc'][i] for i in ELECCION]):.4f}")
    elegida = ranking[0][0]
    print(f'   -> elegida: {elegida}')

    print()
    print('=== JUICIO (pliegues 4-5, NO mirados para elegir) ===')
    rng = np.random.default_rng(SEMILLA)
    ok_el = np.concatenate([res[elegida]['ok'][i] for i in JUICIO])
    ok_base = np.concatenate([base_ok[i] for i in JUICIO])
    dif = ok_el.astype(float) - ok_base.astype(float)
    boot = np.array([dif[rng.integers(0, len(dif), len(dif))].mean() for _ in range(BOOT)])
    p5, p50, p95 = np.percentile(boot, [5, 50, 95])
    print(f'   {elegida}: acc={ok_el.mean():.4f}  '
          f"ll={np.mean([res[elegida]['ll'][i] for i in JUICIO]):.4f}")
    print(f'   ELO      : acc={ok_base.mean():.4f}')
    print(f'   ventaja  : {dif.mean():+.4f}  (p5 {p5:+.4f} · mediana {p50:+.4f} · p95 {p95:+.4f})')
    print(f'   P(>0)    : {(boot > 0).mean():.1%}')
    print()
    print('   todas las familias en el juicio:')
    for nombre, r in res.items():
        oo = np.concatenate([r['ok'][i] for i in JUICIO])
        print(f"      {nombre:<20} acc={oo.mean():.4f}  "
              f"ll={np.mean([r['ll'][i] for i in JUICIO]):.4f}")

    json.dump({'elegida': elegida,
               'eleccion_pliegues': [i + 1 for i in ELECCION],
               'juicio_pliegues': [i + 1 for i in JUICIO],
               'familias': {k: {'acc': v['acc'], 'll': v['ll']} for k, v in res.items()},
               'acc_elo_por_pliegue': [float(o.mean()) for o in base_ok],
               'juicio': {'acc_elegida': float(ok_el.mean()),
                          'acc_elo': float(ok_base.mean()),
                          'ventaja': float(dif.mean()),
                          'p5': float(p5), 'p50': float(p50), 'p95': float(p95),
                          'prob_positiva': float((boot > 0).mean())}},
              open('_v97_familias_kbo.json', 'w'), indent=1)
    print('\n-> _v97_familias_kbo.json')


if __name__ == '__main__':
    main()
