#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Ciclo de experimentación v16 — mejoras de precisión del Mundial (solo gratis).

Ejecuta una batería de ideas sobre EL MISMO split temporal que el benchmark
(train < 2024-01-01, validación 2024-2026) y reporta precisión y log-loss
frente a la línea base v15. Criterio de adopción (VALIDACION_v16.md):
  - precisión +0.3 pp o más Y log-loss no empeora más de 0.01, o
  - ambas métricas mejoran y la calibración en picks >70 % no empeora.
Los ganadores del screening se confirman con walk-forward antes de adoptar.

Uso:  .venv\\Scripts\\python run_experiments.py [--rapido]
      --rapido omite los experimentos que reconstruyen todo el dataset
      (forma exponencial e histórico 1990), que son los más lentos.
"""

import json
import logging
import sys
import time

import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, log_loss

import feature_engineering as fe
from train_tda_model import construir_ensemble, calcular_features_topologicas
from config import HISTORICO_FILE

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger('experimentos')

CORTE = pd.Timestamp('2024-01-01')
RESULTADOS_FILE = 'resultados_experimentos_v16.json'


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------
def evaluar(X_df, topo, y, fechas, builder=construir_ensemble,
            proba_directa=None) -> dict:
    """Entrena en <CORTE y evalúa en >=CORTE. proba_directa salta el modelo."""
    m_tr = (fechas < CORTE).values
    m_va = ~m_tr
    if proba_directa is not None:
        proba = proba_directa
    else:
        X_tr_n, X_va_n, _ = fe.normalizar_features(X_df[m_tr], X_df[m_va])
        modelo = builder()
        modelo.fit(np.hstack([X_tr_n, topo[m_tr]]), y[m_tr])
        proba = modelo.predict_proba(np.hstack([X_va_n, topo[m_va]]))
    y_va = y[m_va]
    acc = float(accuracy_score(y_va, proba.argmax(axis=1)))
    ll = float(log_loss(y_va, proba, labels=[0, 1, 2]))
    # calibración en picks de alta confianza (>70 %)
    conf = proba.max(axis=1)
    alta = conf > 0.70
    acc_alta = float(accuracy_score(y_va[alta], proba[alta].argmax(axis=1))) \
        if alta.sum() >= 20 else None
    return {'acc': round(acc, 4), 'logloss': round(ll, 4),
            'n_val': int(m_va.sum()),
            'acc_conf70': round(acc_alta, 4) if acc_alta else None,
            'n_conf70': int(alta.sum())}


def extras_cronologicos(historico: pd.DataFrame) -> pd.DataFrame:
    """Features extra por MATCH_ID calculadas en un solo pase cronológico
    SIN fuga (solo información previa al partido)."""
    ultima_fecha = {}          # equipo -> fecha del último partido
    racha_v = {}               # equipo -> victorias consecutivas
    racha_sp = {}              # equipo -> partidos sin perder
    h2h_gd = {}                # pareja -> lista de (equipo_ref, goal_diff)

    filas = []
    for f in historico.itertuples(index=False):
        h, a, fecha = f.home_team, f.away_team, f.date
        # --- lectura del estado PREVIO ---
        desc_h = min((fecha - ultima_fecha[h]).days, 30) if h in ultima_fecha else 30
        desc_a = min((fecha - ultima_fecha[a]).days, 30) if a in ultima_fecha else 30
        clave = tuple(sorted((h, a)))
        prev = h2h_gd.get(clave, [])[-3:]
        gd3 = float(np.mean([gd if ref == h else -gd for ref, gd in prev])) if prev else 0.0
        t = str(f.tournament).lower()
        imp = 2.0 if 'world cup' in t and 'qualification' not in t else \
              (0.0 if 'friendly' in t else 1.0)
        filas.append({
            'MATCH_ID': f.MATCH_ID,
            'DIFF_DESCANSO': (desc_h - desc_a) / 30.0,
            'DIFF_RACHA_V': (racha_v.get(h, 0) - racha_v.get(a, 0)) / 5.0,
            'DIFF_SIN_PERDER': (racha_sp.get(h, 0) - racha_sp.get(a, 0)) / 10.0,
            'H2H_GD3': np.clip(gd3, -3, 3) / 3.0,
            'IMPORTANCIA': imp / 2.0,
        })
        # --- actualización POSTERIOR ---
        gh, ga = float(f.home_goals), float(f.away_goals)
        ultima_fecha[h] = ultima_fecha[a] = fecha
        for eq, propios, rival in ((h, gh, ga), (a, ga, gh)):
            racha_v[eq] = racha_v.get(eq, 0) + 1 if propios > rival else 0
            racha_sp[eq] = racha_sp.get(eq, 0) + 1 if propios >= rival else 0
        h2h_gd.setdefault(clave, []).append((h, gh - ga))
    return pd.DataFrame(filas).set_index('MATCH_ID')


def con_extras(ctx, columnas):
    """X_df + columnas extra alineadas por MATCH_ID del meta."""
    ids = [m[3] for m in ctx['ds']['meta']]
    ext = ctx['extras'].reindex(ids).fillna(0.0).reset_index(drop=True)
    X = ctx['X_df'].reset_index(drop=True).copy()
    for c in columnas:
        X[c] = ext[c].values
    return X


# ---------------------------------------------------------------------------
# Experimentos
# ---------------------------------------------------------------------------
def exp_baseline(ctx):
    return evaluar(ctx['X_df'], ctx['topo'], ctx['y'], ctx['fechas'])


def exp_descanso(ctx):
    return evaluar(con_extras(ctx, ['DIFF_DESCANSO']), ctx['topo'], ctx['y'], ctx['fechas'])


def exp_rachas(ctx):
    return evaluar(con_extras(ctx, ['DIFF_RACHA_V', 'DIFF_SIN_PERDER']),
                   ctx['topo'], ctx['y'], ctx['fechas'])


def exp_h2h_rico(ctx):
    return evaluar(con_extras(ctx, ['H2H_GD3']), ctx['topo'], ctx['y'], ctx['fechas'])


def exp_importancia(ctx):
    return evaluar(con_extras(ctx, ['IMPORTANCIA']), ctx['topo'], ctx['y'], ctx['fechas'])


def exp_extras_combinadas(ctx):
    return evaluar(con_extras(ctx, ['DIFF_DESCANSO', 'DIFF_RACHA_V', 'DIFF_SIN_PERDER',
                                    'H2H_GD3', 'IMPORTANCIA']),
                   ctx['topo'], ctx['y'], ctx['fechas'])


def exp_calibracion_sigmoid(ctx):
    from sklearn.calibration import CalibratedClassifierCV

    def builder():
        base = construir_ensemble()          # CalibratedClassifierCV(isotonic)
        return CalibratedClassifierCV(base.estimator, method='sigmoid', cv=3)
    return evaluar(ctx['X_df'], ctx['topo'], ctx['y'], ctx['fechas'], builder=builder)


def exp_stacking(ctx):
    """Meta-modelo logístico sobre las probs CV de XGB/RF/LGBM."""
    from sklearn.model_selection import cross_val_predict
    from sklearn.linear_model import LogisticRegression

    X_df, topo, y, fechas = ctx['X_df'], ctx['topo'], ctx['y'], ctx['fechas']
    m_tr = (fechas < CORTE).values
    m_va = ~m_tr
    X_tr_n, X_va_n, _ = fe.normalizar_features(X_df[m_tr], X_df[m_va])
    X_tr = np.hstack([X_tr_n, topo[m_tr]])
    X_va = np.hstack([X_va_n, topo[m_va]])
    y_tr = y[m_tr]

    ens = construir_ensemble().estimator          # VotingClassifier sin calibrar
    bases = [clf for _, clf in ens.estimators]
    meta_tr, meta_va = [], []
    for clf in bases:
        p_cv = cross_val_predict(clf, X_tr, y_tr, cv=3, method='predict_proba', n_jobs=1)
        meta_tr.append(p_cv)
        clf.fit(X_tr, y_tr)
        meta_va.append(clf.predict_proba(X_va))
    meta = LogisticRegression(max_iter=1000, C=1.0)
    meta.fit(np.hstack(meta_tr), y_tr)
    proba = meta.predict_proba(np.hstack(meta_va))
    return evaluar(X_df, topo, y, fechas, proba_directa=proba)


def exp_poisson_1x2(ctx):
    """1X2 derivado de los regresores Poisson de goles (idea 12), puro."""
    from sklearn.ensemble import HistGradientBoostingRegressor
    from scipy.stats import poisson

    X_df, topo, y, fechas = ctx['X_df'], ctx['topo'], ctx['y'], ctx['fechas']
    goles = ctx['ds']['goles']
    m_tr = (fechas < CORTE).values
    m_va = ~m_tr
    X_tr_n, X_va_n, _ = fe.normalizar_features(X_df[m_tr], X_df[m_va])
    X_tr = np.hstack([X_tr_n, topo[m_tr]])
    X_va = np.hstack([X_va_n, topo[m_va]])

    probas = []
    lams = []
    for col in (0, 1):
        reg = HistGradientBoostingRegressor(loss='poisson', max_iter=300,
                                            learning_rate=0.06, max_depth=6,
                                            random_state=42)
        reg.fit(X_tr, goles[m_tr][:, col])
        lams.append(np.clip(reg.predict(X_va), 0.05, 5.0))
    lh, la = lams
    k = np.arange(0, 11)
    ph = poisson.pmf(k[None, :], lh[:, None])     # (n, 11)
    pa = poisson.pmf(k[None, :], la[:, None])
    M = ph[:, :, None] * pa[:, None, :]           # (n, 11, 11)
    p_home = np.tril(M, -1).sum(axis=(1, 2))
    p_draw = np.trace(M, axis1=1, axis2=2)
    p_away = np.triu(M, 1).sum(axis=(1, 2))
    proba = np.stack([p_home, p_draw, p_away], axis=1)
    proba /= proba.sum(axis=1, keepdims=True)
    ctx['_proba_poisson'] = proba
    return evaluar(X_df, topo, y, fechas, proba_directa=proba)


def exp_blend_poisson(ctx):
    """Mezcla clasificador calibrado (70 %) + Poisson (30 %)."""
    X_df, topo, y, fechas = ctx['X_df'], ctx['topo'], ctx['y'], ctx['fechas']
    if '_proba_poisson' not in ctx:
        exp_poisson_1x2(ctx)
    m_tr = (fechas < CORTE).values
    m_va = ~m_tr
    X_tr_n, X_va_n, _ = fe.normalizar_features(X_df[m_tr], X_df[m_va])
    modelo = construir_ensemble()
    modelo.fit(np.hstack([X_tr_n, topo[m_tr]]), y[m_tr])
    p_clf = modelo.predict_proba(np.hstack([X_va_n, topo[m_va]]))
    proba = 0.7 * p_clf + 0.3 * ctx['_proba_poisson']
    return evaluar(X_df, topo, y, fechas, proba_directa=proba)


def exp_forma_exponencial(ctx):
    """Pesos exponenciales (decay 0.6) en vez de 'doble al último' (idea 1).
    Reconstruye dataset + topología con la forma nueva."""
    original = fe.media_ponderada

    def exponencial(valores):
        if not valores:
            return 0.0
        v = list(valores)[-5:]
        w = np.array([0.6 ** (len(v) - 1 - i) for i in range(len(v))])
        return float(np.dot(v, w / w.sum()))
    fe.media_ponderada = exponencial
    try:
        ds2 = fe.construir_dataset_supervisado(ctx['historico'])
        topo2 = calcular_features_topologicas(ds2)
        return evaluar(ds2['X_df'], topo2, ds2['y'], ds2['fechas'])
    finally:
        fe.media_ponderada = original


def exp_historico_1990(ctx):
    """Histórico ampliado a 1990 (idea 9): misma validación 2024-2026."""
    import data_fetcher
    import statsbomb_calibration
    from correlated_synthetic_generator import CorrelatedSyntheticGenerator

    original = data_fetcher.FECHA_INICIO_HISTORICO
    data_fetcher.FECHA_INICIO_HISTORICO = '1990-01-01'
    try:
        df = data_fetcher.download_kaggle_results()
    finally:
        data_fetcher.FECHA_INICIO_HISTORICO = original
    df['elo_diff'] = data_fetcher.compute_elo_series(df)
    gen = CorrelatedSyntheticGenerator()
    df = gen.generate_advanced_metrics(df, statsbomb_calibration.calibrar())
    ds2 = fe.construir_dataset_supervisado(df)
    topo2 = calcular_features_topologicas(ds2)
    return evaluar(ds2['X_df'], topo2, ds2['y'], ds2['fechas'])


# ---------------------------------------------------------------------------
# Orquestación
# ---------------------------------------------------------------------------
EXPERIMENTOS = [
    ('baseline_v15', exp_baseline, 'Línea base actual (referencia)'),
    ('descanso', exp_descanso, 'Idea 4: días de descanso entre partidos'),
    ('rachas', exp_rachas, 'Idea 10: rachas de victorias / sin perder'),
    ('h2h_rico', exp_h2h_rico, 'Idea 2: diferencia de goles últimos 3 H2H'),
    ('importancia', exp_importancia, 'Idea 5: importancia del torneo'),
    ('extras_combinadas', exp_extras_combinadas, 'Ideas 2+4+5+10 juntas'),
    ('calibracion_sigmoid', exp_calibracion_sigmoid, 'Idea 8: calibración sigmoid vs isotónica'),
    ('stacking_logistico', exp_stacking, 'Idea 7: meta-modelo sobre XGB/RF/LGBM'),
    ('poisson_1x2', exp_poisson_1x2, 'Idea 12: 1X2 derivado de regresores Poisson'),
    ('blend_poisson_30', exp_blend_poisson, 'Idea 12b: 70 % clasificador + 30 % Poisson'),
]
EXPERIMENTOS_LENTOS = [
    ('forma_exponencial', exp_forma_exponencial, 'Idea 1: pesos exponenciales en la forma'),
    ('historico_1990', exp_historico_1990, 'Idea 9: histórico desde 1990'),
]


if __name__ == '__main__':
    rapido = '--rapido' in sys.argv
    logger.info("Preparando datos compartidos (dataset + topología, una sola vez)...")
    historico = pd.read_csv(HISTORICO_FILE, parse_dates=['date'])
    ds = fe.construir_dataset_supervisado(historico)
    topo = calcular_features_topologicas(ds)
    extras = extras_cronologicos(historico)
    ctx = {'historico': historico, 'ds': ds, 'topo': topo, 'extras': extras,
           'X_df': ds['X_df'], 'y': ds['y'], 'fechas': ds['fechas']}

    lista = EXPERIMENTOS + ([] if rapido else EXPERIMENTOS_LENTOS)
    resultados = {}
    base = None
    for nombre, fn, descripcion in lista:
        t0 = time.time()
        try:
            r = fn(ctx)
        except Exception as e:
            logger.error(f"[{nombre}] falló: {type(e).__name__}: {e}")
            continue
        r['descripcion'] = descripcion
        r['segundos'] = round(time.time() - t0, 1)
        resultados[nombre] = r
        if nombre == 'baseline_v15':
            base = r
        delta = f" (Δacc {100*(r['acc']-base['acc']):+.2f} pp, " \
                f"Δll {r['logloss']-base['logloss']:+.4f})" if base and nombre != 'baseline_v15' else ''
        logger.info(f"[{nombre}] acc={r['acc']:.4f} ll={r['logloss']:.4f} "
                    f"conf70={r['acc_conf70']} ({r['segundos']}s){delta}")

    with open(RESULTADOS_FILE, 'w', encoding='utf-8') as f:
        json.dump(resultados, f, ensure_ascii=False, indent=2)
    logger.info(f"Resultados guardados en {RESULTADOS_FILE}")

    # tabla resumen
    print('\n| Experimento | Acc | Δacc (pp) | Log-loss | Δll | Acc conf>70 % |')
    print('|---|---|---|---|---|---|')
    for nombre, r in resultados.items():
        da = 100 * (r['acc'] - base['acc'])
        dl = r['logloss'] - base['logloss']
        print(f"| {nombre} | {r['acc']*100:.2f} % | {da:+.2f} | "
              f"{r['logloss']:.4f} | {dl:+.4f} | {r['acc_conf70']} |")
