#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v385 — LOS ERRORES DE CUOTA DE 8 AÑOS: ¿QUÉ PATRONES LOS HACEN CUMPLIRSE?

El usuario: «checa los errores de cuota pasados… patrones muy específicos que
nos den la probabilidad de acertar». `pick_ledger.csv`: 51.642 partidos
(2018-02 → 2026-01, 35 ligas) con la cuota de una casa y la de Pinnacle A LA
VEZ y el resultado. Un ERROR = la casa paga más que el precio justo de
Pinnacle (sin margen) por al menos 3 %. Para cada error, sus variables:
probabilidad justa, ventaja, cuota, lado (local/empate/visita), favorito,
liga, FORMA de los dos equipos (puntos en sus últimos 5) y H2H (últimos 5
cruces), todo con partidos ANTERIORES de la propia base.

Se mide por grupos en dos mitades por fecha y, además, un modelo (LightGBM)
entrenado con lo viejo (hasta 2023) y juzgado con lo nuevo (2024 en
adelante): ¿su probabilidad está bien calibrada y sus mejores aciertan más y
ganan más? Escribe `_v385_errores_hist.json`.
"""
import collections
import json
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding='utf-8')
rng = np.random.default_rng(385)
EDGE = 0.03

d = pd.read_csv('pick_ledger.csv', low_memory=False)
d = d.dropna(subset=['cuota_home', 'cuota_draw', 'cuota_away', 'pin_home', 'pin_draw', 'pin_away', 'resultado'])
d = d.drop_duplicates('match_id').sort_values('fecha').reset_index(drop=True)
p = d['match_id'].str.split('_', n=2, expand=True)
d['home'], d['away'] = p[1], p[2]

# forma y H2H con lo ANTERIOR (recorriendo por fecha)
forma = collections.defaultdict(lambda: collections.deque(maxlen=5))
cruces = collections.defaultdict(lambda: collections.deque(maxlen=5))
F_H, F_A, H2H = [], [], []
for r in d.itertuples():
    fh, fa = forma[(r.liga, r.home)], forma[(r.liga, r.away)]
    F_H.append(np.mean(fh) if len(fh) >= 3 else np.nan)
    F_A.append(np.mean(fa) if len(fa) >= 3 else np.nan)
    c = cruces[(r.liga, frozenset((r.home, r.away)))]
    # balance del LOCAL de hoy en los cruces anteriores (+1 gana, 0 empate, −1 pierde)
    H2H.append(np.mean([s if g == r.home else -s for g, s in c]) if len(c) >= 2 else np.nan)
    res = int(r.resultado)
    ph, pa = (3, 0) if res == 0 else ((1, 1) if res == 1 else (0, 3))
    fh.append(ph); fa.append(pa)
    c.append((r.home, 1 if res == 0 else (0 if res == 1 else -1)))
d['f_h'], d['f_a'], d['h2h_h'] = F_H, F_A, H2H

# los errores
E = []
for r in d.itertuples():
    pins = np.array([r.pin_home, r.pin_draw, r.pin_away], float)
    q = (1 / pins) / (1 / pins).sum()
    cuotas = [r.cuota_home, r.cuota_draw, r.cuota_away]
    for i, lado in enumerate(('local', 'empate', 'visita')):
        edge = cuotas[i] * q[i] - 1
        if edge < EDGE or cuotas[i] > 10:
            continue
        fe = r.f_h if i == 0 else (r.f_a if i == 2 else np.nan)
        fr = r.f_a if i == 0 else (r.f_h if i == 2 else np.nan)
        h2 = r.h2h_h if i == 0 else (-r.h2h_h if i == 2 else np.nan)
        E.append({'fecha': r.fecha, 'anio': int(r.fecha[:4]), 'liga': r.liga, 'lado': lado, 'i': i,
                  'p': q[i], 'edge': edge, 'cuota': cuotas[i], 'fav': q[i] == q.max(),
                  'forma_eq': fe, 'forma_rival': fr, 'dif_forma': (fe - fr) if not (np.isnan(fe) or np.isnan(fr)) else np.nan,
                  'h2h': h2, 'margen_pin': (1 / pins).sum() - 1, 'ok': int(r.resultado) == i})
E = pd.DataFrame(E)
mitad = E['fecha'].iloc[len(E) // 2]
print('errores:', len(E), 'de', len(d), 'partidos ·', E.fecha.min(), '→', E.fecha.max(), '· mitad', mitad)


def roi(s):
    if len(s) < 40:
        return None
    g = np.where(s.ok, s.cuota - 1, -1.0)
    b = [g[rng.integers(0, len(g), len(g))].mean() for _ in range(1000)]
    return {'n': int(len(s)), 'acierto': round(float(s.ok.mean()), 3), 'p_justa': round(float(s.p.mean()), 3),
            'cuota': round(float(s.cuota.mean()), 2), 'gana_100': round(100 * float(g.mean()), 1),
            'p5': round(100 * float(np.percentile(b, 5)), 1)}


def txt(x):
    return '—' if not x else '%5d · acierta %2.0f%% (justa %2.0f%%) · cuota %.2f · %+5.1f (p5 %+5.1f)' % (
        x['n'], 100 * x['acierto'], 100 * x['p_justa'], x['cuota'], x['gana_100'], x['p5'])


G = collections.OrderedDict()
G['todos'] = lambda e: e.index == e.index
for lado in ('local', 'empate', 'visita'):
    G['lado ' + lado] = (lambda l: lambda e: e.lado == l)(lado)
for a, b in ((0.03, 0.05), (0.05, 0.08), (0.08, 0.12), (0.12, 1)):
    G['ventaja %d-%d %%' % (100 * a, 100 * b)] = (lambda a, b: lambda e: (e.edge >= a) & (e.edge < b))(a, b)
for a, b in ((0, 0.3), (0.3, 0.45), (0.45, 0.6), (0.6, 1)):
    G['prob justa %d-%d %%' % (100 * a, 100 * b)] = (lambda a, b: lambda e: (e.p >= a) & (e.p < b))(a, b)
for a, b in ((1, 1.6), (1.6, 2.2), (2.2, 2.8), (2.8, 4), (4, 10)):
    G['cuota %.1f-%.1f' % (a, b)] = (lambda a, b: lambda e: (e.cuota >= a) & (e.cuota < b))(a, b)
G['favorito'] = lambda e: e.fav
G['no favorito'] = lambda e: ~e.fav
G['forma del apostado ≥ 2 pts'] = lambda e: e.forma_eq >= 2
G['forma del apostado < 1 pt'] = lambda e: e.forma_eq < 1
G['más en forma que el rival (+0,8)'] = lambda e: e.dif_forma >= 0.8
G['menos en forma que el rival (−0,8)'] = lambda e: e.dif_forma <= -0.8
G['H2H a favor'] = lambda e: e.h2h > 0.2
G['H2H en contra'] = lambda e: e.h2h < -0.2
G['favorito + más en forma'] = lambda e: e.fav & (e.dif_forma >= 0.8)
G['favorito + H2H a favor'] = lambda e: e.fav & (e.h2h > 0.2)
G['local favorito + ventaja ≥ 5 %'] = lambda e: (e.lado == 'local') & e.fav & (e.edge >= 0.05)
G['visita + ventaja ≥ 5 %'] = lambda e: (e.lado == 'visita') & (e.edge >= 0.05)
G['margen Pinnacle < 3 %'] = lambda e: e.margen_pin < 0.03
R = {'n_partidos': int(len(d)), 'n_errores': int(len(E)), 'mitad': mitad, 'grupos': {}}
for k, fn in G.items():
    m = fn(E)
    A, B = roi(E[m & (E.fecha < mitad)]), roi(E[m & (E.fecha >= mitad)])
    R['grupos'][k] = [A, B]
    print('%-36s | %s | %s' % (k, txt(A), txt(B)))

# el modelo: probabilidad de que el error se cumpla (entrenado hasta 2023)
try:
    import lightgbm as lgb
    X = ['p', 'edge', 'cuota', 'i', 'fav', 'forma_eq', 'forma_rival', 'dif_forma', 'h2h', 'margen_pin']
    tr, te = E[E.anio <= 2023], E[E.anio >= 2024]
    mdl = lgb.LGBMClassifier(n_estimators=300, learning_rate=0.03, num_leaves=15, min_child_samples=200,
                             subsample=0.8, subsample_freq=1, colsample_bytree=0.8, verbose=-1)
    mdl.fit(tr[X].astype(float), tr.ok)
    te = te.copy()
    te['pm'] = mdl.predict_proba(te[X].astype(float))[:, 1]
    from sklearn.metrics import roc_auc_score, brier_score_loss
    R['modelo'] = {'n_train': int(len(tr)), 'n_test': int(len(te)),
                   'auc_modelo': round(float(roc_auc_score(te.ok, te.pm)), 4),
                   'auc_solo_p_justa': round(float(roc_auc_score(te.ok, te.p)), 4),
                   'brier_modelo': round(float(brier_score_loss(te.ok, te.pm)), 4),
                   'brier_p_justa': round(float(brier_score_loss(te.ok, te.p)), 4)}
    print('\nmodelo:', R['modelo'])
    te['ev_m'] = te.pm * te.cuota - 1
    R['modelo']['por_tramo'] = {}
    for a, b in ((0, 0.35), (0.35, 0.5), (0.5, 0.6), (0.6, 0.7), (0.7, 1)):
        s = te[(te.pm >= a) & (te.pm < b)]
        R['modelo']['por_tramo']['%d-%d %%' % (100 * a, 100 * b)] = roi(s)
        print('modelo dice %2d-%3d %% | %s' % (100 * a, 100 * b, txt(roi(s))))
    for corte in (0.0, 0.03, 0.06, 0.1):
        s = te[te.ev_m >= corte]
        R['modelo']['ev_%d' % (100 * corte)] = roi(s)
        print('modelo: ganancia esperada ≥ %2d %% | %s' % (100 * corte, txt(roi(s))))
    imp = dict(zip(X, [int(v) for v in mdl.feature_importances_]))
    R['modelo']['importancia'] = imp
    print('importancia:', imp)
except Exception as ex:
    print('sin modelo:', ex)
json.dump(R, open('_v385_errores_hist.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1, default=str)
