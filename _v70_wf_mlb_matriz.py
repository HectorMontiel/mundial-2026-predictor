#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v70 · Mejora E (segunda parte) — de dónde salen las λ de la matriz de carreras.

Por qué esta segunda medición
-----------------------------
`_v70_wf_mlb.py` respondió a la pregunta del spec —¿sustituir el clasificador de
moneyline por un modelo de carreras?— y la respuesta fue NO: el clasificador
gana en calibración (ECE 0.0093 frente a 0.0167) y las carreras solas pierden
precisión. Pero eso no agota la mejora, porque la matriz de carreras —de la que
cuelgan run line, totales, totales por equipo, F5 y primer inning— hoy no sale
de ningún modelo de carreras: `plantilla_mlb` la RECONSTRUYE invirtiendo una
normal,

    mu = sigma · Φ⁻¹(p_home);  λ_local = (total+mu)/2;  λ_visit = (total−mu)/2

mezclando el clasificador, el regresor del total y una σ constante de metadata.
Aquí se compara ese apaño contra dos regresores Poisson directos, midiendo lo
único que importa para esos mercados: cómo de bien describen las CARRERAS de
cada equipo.

Métricas: desvianza de Poisson de local y visitante, y error absoluto medio.
Salida: `_v70_wf_mlb_matriz.json`
"""
import json
import logging
import os
import sys
import warnings

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
warnings.filterwarnings('ignore')
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

SALIDA = '_v70_wf_mlb_matriz.json'
N_PLIEGUES = 5
FRAC_TEST = 0.40


def deviance_poisson(y, lam):
    lam = np.clip(lam, 1e-6, None)
    with np.errstate(divide='ignore', invalid='ignore'):
        t = np.where(y > 0, y * np.log(y / lam), 0.0)
    return float(2.0 * np.sum(t - (y - lam)))


def main():
    from sklearn.calibration import CalibratedClassifierCV
    from sklearn.ensemble import (HistGradientBoostingRegressor,
                                  RandomForestClassifier, VotingClassifier)
    from sklearn.preprocessing import StandardScaler
    from scipy.stats import norm
    from lightgbm import LGBMClassifier
    from xgboost import XGBClassifier
    from _v70_wf_mlb import dataset_carreras

    import retrosheet_scraper
    import datetime
    anio = datetime.date.today().year
    df = retrosheet_scraper.actualizar(list(range(anio - 5, anio + 1)))
    X, y, runs, fechas = dataset_carreras(df)
    tot = runs.sum(axis=1)
    logger.info(f"[mlb] {len(X)} juegos")

    n = len(X)
    ini = int(n * (1 - FRAC_TEST))
    cortes = np.linspace(ini, n, N_PLIEGUES + 1).astype(int)
    acum = {'actual_sigma': [], 'regresores': [], 'sigma_encogida': []}
    r_oos, eses = [], []

    for f in range(N_PLIEGUES):
        a, b = cortes[f], cortes[f + 1]
        tr, te = slice(0, a), slice(a, b)
        sc = StandardScaler().fit(X[tr])
        Xtr, Xte = sc.transform(X[tr]), sc.transform(X[te])

        # --- rama ACTUAL: clasificador + regresor del total + sigma constante
        vc = VotingClassifier([
            ('xgb', XGBClassifier(n_estimators=200, max_depth=4,
                                  learning_rate=0.05, verbosity=0)),
            ('lgbm', LGBMClassifier(n_estimators=200, max_depth=4,
                                    learning_rate=0.05, verbose=-1)),
            ('rf', RandomForestClassifier(n_estimators=200, max_depth=8,
                                          random_state=42))], voting='soft')
        clf = CalibratedClassifierCV(vc, method='isotonic', cv=3).fit(Xtr, y[tr])
        p_home = clf.predict_proba(Xte)[:, list(clf.classes_).index(1)]
        reg_tot = HistGradientBoostingRegressor(
            loss='poisson', max_iter=300, learning_rate=0.05, max_depth=5,
            random_state=42).fit(Xtr, tot[tr])
        total_pred = np.clip(reg_tot.predict(Xte), 2.0, 25.0)
        # sigma del margen medida en el TRAIN (lo que guarda metadata)
        sigma = float(np.std(runs[tr][:, 0] - runs[tr][:, 1])) or 4.4
        mu = sigma * norm.ppf(np.clip(p_home, 1e-4, 1 - 1e-4))
        lh_s = np.clip((total_pred + mu) / 2, 0.15, 20)
        la_s = np.clip((total_pred - mu) / 2, 0.15, 20)

        # --- rama NUEVA: dos regresores Poisson directos
        def _reg(obj):
            return HistGradientBoostingRegressor(
                loss='poisson', max_iter=300, learning_rate=0.05, max_depth=5,
                min_samples_leaf=40, l2_regularization=1.0,
                random_state=42).fit(Xtr, obj)
        lh_r = np.clip(_reg(runs[tr][:, 0]).predict(Xte), 0.5, 15)
        la_r = np.clip(_reg(runs[tr][:, 1]).predict(Xte), 0.5, 15)

        # --- rama ACTUAL + encogimiento (Mejora G aplicada al béisbol)
        # Las λ de la inversión normal salen en media (4.63, 4.30) contra unas
        # carreras reales de (4.43, 4.38): separa los dos equipos seis veces más
        # de lo que la realidad justifica. Se calibra `s` con el último 25 % del
        # train, con modelos ajustados sólo con el 75 % anterior.
        c75 = int(a * 0.75)
        sc_i = StandardScaler().fit(X[:c75])
        Xa, Xb = sc_i.transform(X[:c75]), sc_i.transform(X[c75:a])
        clf_i = CalibratedClassifierCV(
            VotingClassifier([
                ('xgb', XGBClassifier(n_estimators=200, max_depth=4,
                                      learning_rate=0.05, verbosity=0)),
                ('lgbm', LGBMClassifier(n_estimators=200, max_depth=4,
                                        learning_rate=0.05, verbose=-1)),
                ('rf', RandomForestClassifier(n_estimators=200, max_depth=8,
                                              random_state=42))], voting='soft'),
            method='isotonic', cv=3).fit(Xa, y[:c75])
        p_i = clf_i.predict_proba(Xb)[:, list(clf_i.classes_).index(1)]
        tot_i = np.clip(HistGradientBoostingRegressor(
            loss='poisson', max_iter=300, learning_rate=0.05, max_depth=5,
            random_state=42).fit(Xa, tot[:c75]).predict(Xb), 2.0, 25.0)
        sg_i = float(np.std(runs[:c75, 0] - runs[:c75, 1])) or 4.4
        mu_i = sg_i * norm.ppf(np.clip(p_i, 1e-4, 1 - 1e-4))
        lh_i = np.clip((tot_i + mu_i) / 2, 0.15, 20)
        la_i = np.clip((tot_i - mu_i) / 2, 0.15, 20)
        mejor_s, mejor_d = 1.0, np.inf
        for s in np.round(np.arange(0.10, 1.0001, 0.02), 4):
            m_ = (lh_i + la_i) / 2.0
            d_ = (lh_i - la_i) / 2.0
            dv = (deviance_poisson(runs[c75:a, 0], np.clip(m_ + s * d_, 0.15, 20))
                  + deviance_poisson(runs[c75:a, 1], np.clip(m_ - s * d_, 0.15, 20)))
            if dv < mejor_d:
                mejor_d, mejor_s = dv, float(s)
        eses.append(mejor_s)
        m_s, d_s = (lh_s + la_s) / 2.0, (lh_s - la_s) / 2.0
        lh_e = np.clip(m_s + mejor_s * d_s, 0.15, 20)
        la_e = np.clip(m_s - mejor_s * d_s, 0.15, 20)

        acum['actual_sigma'].append((lh_s, la_s))
        acum['regresores'].append((lh_r, la_r))
        acum['sigma_encogida'].append((lh_e, la_e))
        r_oos.append(runs[te])
        logger.info(f"  pliegue {f+1}/{N_PLIEGUES}: train {a} test {b-a} "
                    f"· sigma={sigma:.2f} · s={mejor_s:.2f}")

    R = np.vstack(r_oos)
    res = {'n': int(n), 'n_oos': int(len(R)), 'pliegues': N_PLIEGUES, 'ramas': {}}
    for k, v in acum.items():
        lh = np.concatenate([x[0] for x in v])
        la = np.concatenate([x[1] for x in v])
        res['ramas'][k] = {
            'deviance': round((deviance_poisson(R[:, 0], lh)
                               + deviance_poisson(R[:, 1], la)) / len(R), 5),
            'mae': round(float((np.abs(R[:, 0] - lh) + np.abs(R[:, 1] - la)).mean() / 2), 4),
            'lambda_media_local': round(float(lh.mean()), 3),
            'lambda_media_visit': round(float(la.mean()), 3),
            'carreras_reales_local': round(float(R[:, 0].mean()), 3),
            'carreras_reales_visit': round(float(R[:, 1].mean()), 3)}
    b_ = res['ramas']['actual_sigma']
    res['s_por_pliegue'] = eses
    res['s_mediano'] = float(np.median(eses)) if eses else 1.0
    for k, v in res['ramas'].items():
        v['d_deviance'] = round(v['deviance'] - b_['deviance'], 5)
        v['d_mae'] = round(v['mae'] - b_['mae'], 5)
        v['adopta'] = bool(v['d_deviance'] < 0 and v['d_mae'] <= 0)
    with open(SALIDA, 'w', encoding='utf-8') as fh:
        json.dump(res, fh, ensure_ascii=False, indent=1)
    logger.info(f"s mediano = {res['s_mediano']:.2f}")
    for k, v in res['ramas'].items():
        logger.info(f"  {k:16s} dev={v['deviance']:.4f} ({v['d_deviance']:+.5f}) "
                    f"mae={v['mae']:.4f} ({v['d_mae']:+.5f}) "
                    f"λ=({v['lambda_media_local']:.2f},{v['lambda_media_visit']:.2f}) "
                    f"real=({v['carreras_reales_local']:.2f},"
                    f"{v['carreras_reales_visit']:.2f}) "
                    f"{'ADOPTA' if v['adopta'] else ''}")


if __name__ == '__main__':
    main()
