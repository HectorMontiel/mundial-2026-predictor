#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v70 · Mejora D — ¿qué familia de modelo conviene a cada liga?

Contexto
--------
15 de las 40 competiciones de v68 se quedaron por DEBAJO de la línea base ELO.
El spec propone «si len(partidos) < 800, usa LogisticRegressionCV». Al medir,
esa regla no encaja con los datos: sólo 4 de las 15 ligas fallidas tienen menos
de 800 partidos de entrenamiento (FA Cup 305, Sudamericana 333, ISL 476,
A-League 650); el resto llega a 2.144 y también pierde contra el ELO. El
problema, por tanto, no es «pocos partidos» sino **relación señal/ruido baja**,
y eso pide elegir la familia de modelo por liga, no por un umbral de tamaño.

Qué mide este script
--------------------
Walk-forward EXPANDENTE de K pliegues (no el split único 80/20 de
`entrenar_liga`) sobre varios candidatos, con las predicciones fuera de muestra
agrupadas para una sola métrica. El split único de v68 dejaba 79 partidos de
validación en la FA Cup: ±5,5 pp de error típico, es decir, indistinguible de
ruido. Con pliegues expandentes se valida sobre el 40 % final del histórico.

Candidatos
----------
· `ensemble`      — el actual (XGB+RF+LGBM voting + isotónica). Referencia.
· `logistica`     — LogisticRegressionCV multinomial sobre todas las features.
· `logistica_base`— idem pero SÓLO las 15 features base (sin topológicas ni
                    extras): el vector mínimo, máxima resistencia al ruido.
· `elo_logit`     — multinomial sobre DIFF_ELO a secas. Un solo grado de
                    libertad: es la línea base ELO pero PROBABILÍSTICA y
                    calibrada, así que a diferencia del argmax del ELO sí puede
                    devolver empates y sí tiene log-loss decente.
· `blend_elo`     — mezcla convexa ensemble/elo_logit con el peso ajustado en un
                    split interno del train (nunca con datos del test).
· `gbm_regular`   — un único LGBM fuertemente regularizado (sin voting ni
                    isotónica, que es lo que más varianza añade con poco dato).

Salida: `_v70_wf_modelos.json`
"""
import argparse
import json
import logging
import os
import pickle
import sys
import time
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings('ignore')
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

SALIDA = '_v70_wf_modelos.json'
CACHE = '_v70_cache_ds'
N_PLIEGUES = 5
FRAC_TEST = 0.40          # el 40 % final del histórico se usa como out-of-sample

# Las 15 que perdieron contra el ELO en v68 (de `_v68_entrenamiento.json`)
LIGAS_OBJETIVO = [
    'eng_fa_cup', 'sudamericana', 'ind_isl', 'par_division', 'ned_eerste',
    'aus_aleague', 'eng_championship', 'gre_super_league', 'slv_primera',
    'bel_pro_league', 'eng_league_two', 'bra_serie_b', 'ven_primera',
    'crc_fpd', 'esp_hypermotion',
]


# ---------------------------------------------------------------------------
# Dataset (cacheado en disco: construirlo cuesta minutos por las topológicas)
# ---------------------------------------------------------------------------
def construir_ds(clave: str):
    os.makedirs(CACHE, exist_ok=True)
    ruta = os.path.join(CACHE, f'{clave}.pkl')
    if os.path.exists(ruta):
        with open(ruta, 'rb') as f:
            return pickle.load(f)

    import feature_engineering as fe
    from train_tda_model import calcular_features_topologicas
    import league_engine as le

    csv = f'historico_{clave}.csv'
    if os.path.exists(csv):
        df = pd.read_csv(csv, parse_dates=['date'])
    else:
        df = le.descargar_liga(clave)
        df.to_csv(csv, index=False)

    ds = fe.construir_dataset_supervisado(df)
    topo = calcular_features_topologicas(ds)

    # Mismas features extra que usa producción en esta liga (si las tiene)
    cols_extra = le.columnas_extra(clave)
    X_df = ds['X_df'].reset_index(drop=True).copy()
    if cols_extra:
        try:
            extras_df, _ = le.features_extra_liga(df)
            grupos = le.LEAGUES[clave].get('features_extra', [])
            if 'mx' in grupos:
                extras_df = extras_df.join(le.features_mx(df))
            if any(g in grupos for g in ('ent', 'elo_d', 'urg')):
                import features_v26 as f26
                extras_df = extras_df.join(f26.features_v26(df)[0])
            if 'ck' in grupos:
                import features_v59 as f59
                extras_df = extras_df.join(f59.features_ck(df)[0])
            ids = [m[3] for m in ds['meta']]
            ext = extras_df.reindex(ids).reset_index(drop=True)
            for c in cols_extra:
                if c in ext.columns:
                    X_df[c] = ext[c].values
        except Exception as e:
            logger.warning(f"[{clave}] features extra omitidas: {type(e).__name__}: {e}")
            cols_extra = []

    paquete = {
        'X_df': X_df, 'y': ds['y'], 'fechas': ds['fechas'].reset_index(drop=True),
        'topo': topo, 'cols_extra': cols_extra,
        'n_base': len(fe.FEATURES_MODELO),
        'columnas': list(X_df.columns),
    }
    with open(ruta, 'wb') as f:
        pickle.dump(paquete, f)
    logger.info(f"[{clave}] dataset: {len(X_df)} partidos, "
                f"{X_df.shape[1]} features (+{topo.shape[1]} topo)")
    return paquete


# ---------------------------------------------------------------------------
# Candidatos
# ---------------------------------------------------------------------------
def _probs3(modelo, X):
    """predict_proba reordenado a [P(local), P(empate), P(visitante)]."""
    pr = modelo.predict_proba(X)
    p = np.full((len(X), 3), 1e-9)
    for i, k in enumerate(modelo.classes_):
        p[:, int(k)] = pr[:, i]
    return p / p.sum(axis=1, keepdims=True)


def _fit_ensemble(Xtr, ytr):
    from train_tda_model import construir_ensemble
    m = construir_ensemble()
    m.fit(Xtr, ytr)
    return m


def _fit_logistica(Xtr, ytr):
    from sklearn.linear_model import LogisticRegressionCV
    from sklearn.model_selection import TimeSeriesSplit
    n_cv = 3 if len(Xtr) >= 200 else 2
    m = LogisticRegressionCV(
        Cs=np.logspace(-3, 2, 10), cv=TimeSeriesSplit(n_splits=n_cv),
        penalty='l2', solver='lbfgs', max_iter=3000,
        scoring='neg_log_loss', n_jobs=-1, random_state=42)
    m.fit(Xtr, ytr)
    return m


def _fit_gbm(Xtr, ytr):
    from lightgbm import LGBMClassifier
    m = LGBMClassifier(
        n_estimators=180, num_leaves=7, max_depth=3, learning_rate=0.04,
        min_child_samples=40, subsample=0.8, subsample_freq=1,
        colsample_bytree=0.6, reg_lambda=20.0, reg_alpha=1.0,
        objective='multiclass', random_state=42, n_jobs=-1, verbose=-1)
    m.fit(Xtr, ytr)
    return m


def evaluar_liga(clave: str, n_pliegues: int = N_PLIEGUES) -> dict:
    from sklearn.metrics import accuracy_score, log_loss
    import feature_engineering as fe

    pk = construir_ds(clave)
    X_df, y, topo = pk['X_df'].copy(), pk['y'], pk['topo']
    n = len(X_df)
    if n < 200:
        return {'clave': clave, 'estado': 'pocos_datos', 'n': n}

    base_cols = [c for c in X_df.columns if c in fe.FEATURES_MODELO]
    i_elo = list(X_df.columns).index('DIFF_ELO')

    ini = int(n * (1 - FRAC_TEST))
    cortes = np.linspace(ini, n, n_pliegues + 1).astype(int)

    # Imputación de las features extra, igual que `entrenar_liga`: las de
    # cuotas con la media del TRAIN (aquí, del primer tramo, que es train en
    # todos los pliegues) y el resto con 0. Sin esto el RandomForest del
    # ensemble revienta con «Input X contains NaN» en las ligas cuyo histórico
    # tiene cuotas incompletas (Bélgica, League Two, Hypermotion).
    import league_engine as _le
    for c in pk.get('cols_extra') or []:
        if c not in X_df.columns:
            continue
        s = pd.to_numeric(X_df[c], errors='coerce')
        relleno = float(s.iloc[:ini].mean()) if c in _le.COLS_CUOTAS else 0.0
        X_df[c] = s.fillna(0.0 if not np.isfinite(relleno) else relleno)
    X_df = X_df.fillna(0.0)

    nombres = ['ensemble', 'logistica', 'logistica_base', 'elo_logit',
               'blend_elo', 'gbm_regular']
    acum = {k: [] for k in nombres}
    y_oos, elo_oos = [], []

    t0 = time.time()
    for f in range(n_pliegues):
        a, b = cortes[f], cortes[f + 1]
        if b - a < 10 or a < 120:
            continue
        tr = slice(0, a)
        te = slice(a, b)
        ytr, yte = y[tr], y[te]
        if len(np.unique(ytr)) < 3:
            continue

        Xtr_n, Xte_n, _ = fe.normalizar_features(X_df.iloc[tr], X_df.iloc[te])
        Xtr = np.hstack([Xtr_n, topo[tr]])
        Xte = np.hstack([Xte_n, topo[te]])
        # variante sin topológicas ni extras
        ib = [list(X_df.columns).index(c) for c in base_cols]
        Xtr_b, Xte_b = Xtr_n[:, ib], Xte_n[:, ib]
        # variante ELO puro
        Xtr_e = Xtr_n[:, [i_elo]]
        Xte_e = Xte_n[:, [i_elo]]

        p = {}
        p['ensemble'] = _probs3(_fit_ensemble(Xtr, ytr), Xte)
        p['logistica'] = _probs3(_fit_logistica(Xtr, ytr), Xte)
        p['logistica_base'] = _probs3(_fit_logistica(Xtr_b, ytr), Xte_b)
        m_elo = _fit_logistica(Xtr_e, ytr)
        p['elo_logit'] = _probs3(m_elo, Xte_e)
        p['gbm_regular'] = _probs3(_fit_gbm(Xtr, ytr), Xte)

        # blend: peso ajustado en el ÚLTIMO 25 % del train (nunca con el test)
        c75 = int(a * 0.75)
        if c75 > 100 and len(np.unique(y[:c75])) == 3:
            Xa_n, Xb_n, _ = fe.normalizar_features(X_df.iloc[:c75], X_df.iloc[c75:a])
            Xa = np.hstack([Xa_n, topo[:c75]])
            Xb = np.hstack([Xb_n, topo[c75:a]])
            pa = _probs3(_fit_ensemble(Xa, y[:c75]), Xb)
            pe = _probs3(_fit_logistica(Xa_n[:, [i_elo]], y[:c75]), Xb_n[:, [i_elo]])
            mejor_w, mejor_ll = 0.5, 1e9
            for w in np.linspace(0, 1, 11):
                ll = log_loss(y[c75:a], w * pa + (1 - w) * pe, labels=[0, 1, 2])
                if ll < mejor_ll:
                    mejor_ll, mejor_w = ll, w
        else:
            mejor_w = 0.5
        p['blend_elo'] = mejor_w * p['ensemble'] + (1 - mejor_w) * p['elo_logit']

        for k in nombres:
            acum[k].append(p[k])
        y_oos.append(yte)
        elo_oos.append(np.where(X_df['DIFF_ELO'].values[te] > 0, 0, 2))

    if not y_oos:
        return {'clave': clave, 'estado': 'sin_pliegues', 'n': n}

    yv = np.concatenate(y_oos)
    elo_pred = np.concatenate(elo_oos)

    # ------------------------------------------------------------------
    # Selección SECUENCIAL honesta.
    #
    # Quedarse con el mejor de seis candidatos mirando el propio test infla el
    # resultado: el máximo de seis estimaciones ruidosas es optimista aunque
    # ninguna familia sea mejor. Aquí la familia de cada pliegue se elige con el
    # log-loss acumulado de los pliegues ANTERIORES, que es exactamente lo que
    # podría hacerse en producción. El primer pliegue usa `ensemble`, el modelo
    # que ya está desplegado. Éste es el número que manda para adoptar.
    # ------------------------------------------------------------------
    elegidas, p_sec = [], []
    for f in range(len(y_oos)):
        if f == 0:
            fam = 'ensemble'
        else:
            y_prev = np.concatenate(y_oos[:f])
            fam = min(nombres, key=lambda k: log_loss(
                y_prev, np.concatenate(acum[k][:f]), labels=[0, 1, 2]))
        elegidas.append(fam)
        p_sec.append(acum[fam][f])
    p_sec = np.concatenate(p_sec)

    res = {'clave': clave, 'estado': 'ok', 'n': n, 'n_oos': int(len(yv)),
           'pliegues': len(y_oos),
           'elo_acc': round(float(accuracy_score(yv, elo_pred)), 4),
           'seleccion_secuencial': {
               'familias': elegidas,
               'acc': round(float(accuracy_score(yv, p_sec.argmax(axis=1))), 4),
               'll': round(float(log_loss(yv, p_sec, labels=[0, 1, 2])), 4)},
           'segundos': round(time.time() - t0, 1), 'modelos': {}}
    for k in nombres:
        pk_ = np.concatenate(acum[k])
        res['modelos'][k] = {
            'acc': round(float(accuracy_score(yv, pk_.argmax(axis=1))), 4),
            'll': round(float(log_loss(yv, pk_, labels=[0, 1, 2])), 4),
        }
    return res


def main(solo=None, ligas=None, pliegues=N_PLIEGUES):
    claves = [solo] if solo else (ligas or LIGAS_OBJETIVO)
    previos = {}
    if os.path.exists(SALIDA):
        with open(SALIDA, encoding='utf-8') as f:
            previos = {r['clave']: r for r in json.load(f)}
    for i, c in enumerate(claves, 1):
        logger.info(f"[{i}/{len(claves)}] {c}")
        try:
            r = evaluar_liga(c, pliegues)
        except Exception as e:
            logger.error(f"  {c}: {type(e).__name__}: {e}")
            r = {'clave': c, 'estado': 'error', 'detalle': f'{type(e).__name__}: {e}'}
        previos[c] = r
        with open(SALIDA, 'w', encoding='utf-8') as f:
            json.dump(list(previos.values()), f, ensure_ascii=False, indent=1)
        if r.get('estado') == 'ok':
            linea = f"  ELO {r['elo_acc']:.4f} | "
            linea += ' | '.join(f"{k} {v['acc']:.4f}/{v['ll']:.3f}"
                                for k, v in r['modelos'].items())
            logger.info(linea)


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--solo', default=None)
    ap.add_argument('--pliegues', type=int, default=N_PLIEGUES)
    a = ap.parse_args()
    main(solo=a.solo, pliegues=a.pliegues)
