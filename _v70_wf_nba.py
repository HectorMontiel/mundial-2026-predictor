#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v70 · Mejora F — NBA: ¿aportan fatiga+viajes y las avanzadas?

Walk-forward expandente de 5 pliegues sobre 2021-22 … 2025-26 (7.365 juegos),
comparando el vector actual del motor contra tres ampliaciones. Se separan los
dos bloques para saber CUÁL aporta, que es justo lo que v69 no pudo responder
con las features de saque hasta desglosarlas.

  · `actual`      — las 9 features de v29. Referencia.
  · `fatiga`      — + juegos en 5/7 días, 3-en-4, millas de viaje, husos, road trip.
  · `avanzadas`   — + eFG, TOV%, ratio de asistencias, OREB%, tasa de tiros libres.
  · `todo`        — ambos bloques.

Regla del spec §7.6: adoptar si el moneyline mejora ≥ +0.5 pp.
Salida: `_v70_wf_nba.json`
"""
import json
import logging
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings('ignore')
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

SALIDA = '_v70_wf_nba.json'
N_PLIEGUES = 5
FRAC_TEST = 0.40
UMBRAL_ADOPCION = 0.005          # +0.5 pp


def ece(y, p, bins=10):
    b = np.clip((p * bins).astype(int), 0, bins - 1)
    return float(sum(( b == k).mean() * abs(p[b == k].mean() - y[b == k].mean())
                     for k in range(bins) if (b == k).sum()))


def main():
    from sklearn.calibration import CalibratedClassifierCV
    from sklearn.ensemble import RandomForestClassifier, VotingClassifier
    from sklearn.metrics import accuracy_score, log_loss
    from sklearn.preprocessing import StandardScaler
    from lightgbm import LGBMClassifier
    from xgboost import XGBClassifier
    from engines.nba_engine import NBAEngine
    import nba_features as nf

    df = pd.read_csv('historico_nba.csv', parse_dates=['date'])
    X, y, tot, fechas, _ = NBAEngine._dataset(df, con_cdi=True)
    logger.info(f"[nba] base: {len(X)} juegos, {X.shape[1]} features")

    # las filas del dataset base son un subconjunto del histórico (exige >=5
    # partidos previos por equipo); se re-emparejan por GAME_ID y fecha
    adv = nf.descargar_avanzadas(['2021-22', '2022-23', '2023-24',
                                  '2024-25', '2025-26'])
    extra = nf.construir_features(df, adv)
    d = df.sort_values('date').reset_index(drop=True)
    d['_k'] = d['GAME_ID'].map(nf._clave_partido)
    # reconstruir la máscara de filas utilizables igual que _dataset
    usable = []
    cnt = {}
    for r in d.itertuples(index=False):
        usable.append(all(cnt.get(t, 0) >= 5 for t in (r.home_team, r.away_team)))
        for t in (r.home_team, r.away_team):
            cnt[t] = cnt.get(t, 0) + 1
    claves = d.loc[np.array(usable), '_k'].tolist()
    if len(claves) != len(X):
        logger.error(f"desalineado: {len(claves)} claves vs {len(X)} filas")
        return
    # `extra` viene indexado por GAME_ID; si el histórico trajese repetidos el
    # reindex fallaría. Se deduplica por si acaso (el bug de duplicados de
    # `nba_scraper` se arregló en v70, pero un CSV antiguo podría traerlos).
    extra = extra[~extra.index.duplicated(keep='last')]
    E = extra.reindex(claves)
    cob = float(E['DIFF_EFG'].notna().mean())
    logger.info(f"[nba] avanzadas disponibles en {100*cob:.1f} % de las filas")

    F = E[nf.COLS_FATIGA].fillna(0.0).values
    A = E[nf.COLS_AVANZADAS].fillna(0.0).values
    bloques = {'actual': X,
               'fatiga': np.hstack([X, F]),
               'avanzadas': np.hstack([X, A]),
               'todo': np.hstack([X, F, A])}

    # v70 — hallazgo colateral: el motor NBA NO bate a su propia línea base ELO
    # (0.6544 contra 0.6627). Es el mismo cuadro que en las ligas de fútbol
    # pequeñas, donde la solución que funcionó fue mezclar con una logística de
    # un solo grado de libertad sobre el ELO. Aquí se mide lo mismo, en binario.
    blend = True

    n = len(X)
    ini = int(n * (1 - FRAC_TEST))
    cortes = np.linspace(ini, n, N_PLIEGUES + 1).astype(int)
    acum = {k: [] for k in bloques}
    y_oos, elo_oos = [], []

    def _clf():
        vc = VotingClassifier([
            ('xgb', XGBClassifier(n_estimators=200, max_depth=4,
                                  learning_rate=0.05, verbosity=0)),
            ('lgbm', LGBMClassifier(n_estimators=200, max_depth=4,
                                    learning_rate=0.05, verbose=-1)),
            ('rf', RandomForestClassifier(n_estimators=200, max_depth=8,
                                          random_state=42))], voting='soft')
        return CalibratedClassifierCV(vc, method='isotonic', cv=3)

    from sklearn.linear_model import LogisticRegressionCV
    from sklearn.model_selection import TimeSeriesSplit
    acum['elo_logit'] = []
    acum['blend_elo'] = []

    for f in range(N_PLIEGUES):
        a, b = cortes[f], cortes[f + 1]
        tr, te = slice(0, a), slice(a, b)
        for k, M in bloques.items():
            sc = StandardScaler().fit(M[tr])
            m = _clf().fit(sc.transform(M[tr]), y[tr])
            p = m.predict_proba(sc.transform(M[te]))[:, list(m.classes_).index(1)]
            acum[k].append(p)

        if blend:
            sc = StandardScaler().fit(X[tr])
            Xtr, Xte = sc.transform(X[tr]), sc.transform(X[te])

            def _lg():
                return LogisticRegressionCV(
                    Cs=np.logspace(-3, 2, 10), cv=TimeSeriesSplit(n_splits=3),
                    penalty='l2', solver='lbfgs', max_iter=3000,
                    scoring='neg_log_loss', n_jobs=-1, random_state=42)
            le = _lg().fit(Xtr[:, [0]], y[tr])       # columna 0 = DIFF_ELO
            p_elo = le.predict_proba(Xte[:, [0]])[:, list(le.classes_).index(1)]
            acum['elo_logit'].append(p_elo)

            # peso ajustado con el último 25 % del train, nunca con el test
            c75 = int(a * 0.75)
            sc_i = StandardScaler().fit(X[:c75])
            Xa, Xb = sc_i.transform(X[:c75]), sc_i.transform(X[c75:a])
            m_i = _clf().fit(Xa, y[:c75])
            pa_ = m_i.predict_proba(Xb)[:, list(m_i.classes_).index(1)]
            l_i = _lg().fit(Xa[:, [0]], y[:c75])
            pe_ = l_i.predict_proba(Xb[:, [0]])[:, list(l_i.classes_).index(1)]
            mejor_w, mejor_ll = 0.5, np.inf
            for w in np.linspace(0.0, 1.0, 11):
                pw = np.clip(w * pa_ + (1 - w) * pe_, 1e-6, 1 - 1e-6)
                ll = log_loss(y[c75:a], np.column_stack([1 - pw, pw]))
                if ll < mejor_ll:
                    mejor_ll, mejor_w = ll, float(w)
            acum['blend_elo'].append(mejor_w * acum['actual'][-1]
                                     + (1 - mejor_w) * p_elo)
            logger.info(f"    blend w={mejor_w:.2f}")
        y_oos.append(y[te])
        elo_oos.append((X[te][:, 0] > 0).astype(int))
        logger.info(f"  pliegue {f+1}/{N_PLIEGUES}: train {a} · test {b-a}")

    yv = np.concatenate(y_oos)
    res = {'n': int(n), 'n_oos': int(len(yv)), 'pliegues': N_PLIEGUES,
           'cobertura_avanzadas': round(cob, 4),
           'elo_acc': round(float(accuracy_score(yv, np.concatenate(elo_oos))), 4),
           'modelos': {}}
    for k in acum:
        p = np.concatenate(acum[k])
        res['modelos'][k] = {
            'acc': round(float(accuracy_score(yv, (p >= 0.5).astype(int))), 4),
            'll': round(float(log_loss(yv, np.column_stack([1 - p, p]))), 4),
            'ece': round(ece(yv, p), 4)}
    ref = res['modelos']['actual']
    for k, v in res['modelos'].items():
        v['d_acc'] = round(v['acc'] - ref['acc'], 4)
        v['d_ll'] = round(v['ll'] - ref['ll'], 4)
        v['adopta'] = bool(v['d_acc'] >= UMBRAL_ADOPCION and v['d_ll'] <= 0.01)
    with open(SALIDA, 'w', encoding='utf-8') as fh:
        json.dump(res, fh, ensure_ascii=False, indent=1)
    logger.info(f"ELO {res['elo_acc']}")
    for k, v in res['modelos'].items():
        logger.info(f"  {k:11s} acc={v['acc']:.4f} ({v['d_acc']:+.4f}) "
                    f"ll={v['ll']:.4f} ({v['d_ll']:+.4f}) ece={v['ece']:.4f} "
                    f"{'ADOPTA' if v['adopta'] else ''}")


if __name__ == '__main__':
    main()
