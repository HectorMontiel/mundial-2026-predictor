#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Ciclo de experimentación v17 — precisión de las ligas de clubes (solo gratis).

Para cada liga activa ejecuta, sobre EL MISMO split temporal que usa
league_engine (train 80 % / validación 20 % cronológico):

  baseline          modelo v16 actual (referencia)
  h2h_gd3           diferencia de goles de los últimos 3 cruces directos
  descanso          días de descanso entre partidos (congestión)
  rachas            victorias seguidas / partidos sin perder
  tabla             posición y puntos-por-partido en la clasificación viva
  cuotas            probabilidades implícitas del cierre B365 como features
  extras            h2h+descanso+rachas+tabla juntas (sin cuotas)
  extras_cuotas     todas las anteriores + cuotas
  forma_exp         media exponencial (decay 0.6) en vez de doble-al-último
  historico_10t     histórico ampliado a ~10 temporadas (v16 del Mundial)

Criterio (regla de oro, VALIDACION_v17.md): ≥ +0.3 pp de precisión sin
empeorar el log-loss más de 0.01 (o mejora en calibración de picks >70 %).
Los ganadores del screening se confirman con walk-forward antes de adoptar.

Uso:  .venv\\Scripts\\python run_league_experiments.py [liga ...]
"""

import json
import logging
import sys
import time

import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, log_loss

import feature_engineering as fe
import league_engine
from train_tda_model import construir_ensemble, calcular_features_topologicas
from config import LEAGUES, FD_BASE

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger('exp_ligas')
logging.getLogger('league_engine').setLevel(logging.WARNING)

RESULTADOS_FILE = 'resultados_experimentos_v17.json'

LIGAS = ['liga_mx', 'premier', 'laliga', 'serie_a', 'bundesliga',
         'ligue_1', 'eredivisie', 'primeira']

# temporadas ampliadas (~10) para el experimento historico_10t
TEMPORADAS_10 = ('1617', '1718', '1819', '1920', '2021',
                 '2122', '2223', '2324', '2425', '2526')
ARCHIVO_FD = {'premier': 'E0', 'laliga': 'SP1', 'serie_a': 'I1',
              'bundesliga': 'D1', 'ligue_1': 'F1', 'eredivisie': 'N1',
              'primeira': 'P1'}


# ---------------------------------------------------------------------------
# Features extra por liga — la implementación canónica vive en league_engine
# (features_extra_liga); aquí queda la versión original de screening v17.
# ---------------------------------------------------------------------------
def extras_liga(df: pd.DataFrame) -> pd.DataFrame:
    return league_engine.features_extra_liga(df)[0]


def _extras_liga_screening_v17(df: pd.DataFrame) -> pd.DataFrame:
    ultima_fecha, racha_v, racha_sp = {}, {}, {}
    h2h_gd = {}
    # clasificación viva por temporada (jul-jun): puntos y partidos jugados
    pts, pj = {}, {}
    temporada_actual = None

    filas = []
    for f in df.itertuples(index=False):
        h, a, fecha = f.home_team, f.away_team, f.date
        temp = fecha.year if fecha.month >= 7 else fecha.year - 1
        if temp != temporada_actual:      # reset de la tabla en cada temporada
            temporada_actual = temp
            pts, pj = {}, {}

        desc_h = min((fecha - ultima_fecha[h]).days, 21) if h in ultima_fecha else 21
        desc_a = min((fecha - ultima_fecha[a]).days, 21) if a in ultima_fecha else 21
        clave = tuple(sorted((h, a)))
        prev = h2h_gd.get(clave, [])[-3:]
        gd3 = float(np.mean([gd if ref == h else -gd for ref, gd in prev])) if prev else 0.0
        ppg_h = pts.get(h, 0) / pj[h] if pj.get(h) else 1.3
        ppg_a = pts.get(a, 0) / pj[a] if pj.get(a) else 1.3
        # posición: ranking por puntos dentro de la temporada en curso
        tabla = sorted(pts, key=lambda e: -pts[e])
        pos_h = tabla.index(h) + 1 if h in tabla else len(tabla) // 2 + 1
        pos_a = tabla.index(a) + 1 if a in tabla else len(tabla) // 2 + 1

        fila = {
            'MATCH_ID': f.MATCH_ID,
            'DIFF_DESCANSO': (desc_h - desc_a) / 21.0,
            'DIFF_RACHA_V': (racha_v.get(h, 0) - racha_v.get(a, 0)) / 5.0,
            'DIFF_SIN_PERDER': (racha_sp.get(h, 0) - racha_sp.get(a, 0)) / 10.0,
            'H2H_GD3': float(np.clip(gd3, -3, 3)) / 3.0,
            'DIFF_PPG': (ppg_h - ppg_a) / 3.0,
            'DIFF_POSICION': (pos_a - pos_h) / 20.0,   # positivo = local mejor puesto
        }
        # probabilidades implícitas del cierre (pre-partido; NaN si no hay)
        oh = getattr(f, 'odd_home', None)
        od = getattr(f, 'odd_draw', None)
        oa = getattr(f, 'odd_away', None)
        if oh and od and oa and oh > 1 and od > 1 and oa > 1:
            inv = np.array([1 / oh, 1 / od, 1 / oa])
            imp = inv / inv.sum()
            fila.update({'PROB_IMP_H': imp[0], 'PROB_IMP_D': imp[1],
                         'PROB_IMP_A': imp[2], 'OVERROUND': float(inv.sum() - 1)})
        else:
            fila.update({'PROB_IMP_H': np.nan, 'PROB_IMP_D': np.nan,
                         'PROB_IMP_A': np.nan, 'OVERROUND': np.nan})
        filas.append(fila)

        # actualización posterior
        gh, ga = float(f.home_goals), float(f.away_goals)
        ultima_fecha[h] = ultima_fecha[a] = fecha
        for eq, propios, rival in ((h, gh, ga), (a, ga, gh)):
            racha_v[eq] = racha_v.get(eq, 0) + 1 if propios > rival else 0
            racha_sp[eq] = racha_sp.get(eq, 0) + 1 if propios >= rival else 0
            pj[eq] = pj.get(eq, 0) + 1
            pts[eq] = pts.get(eq, 0) + (3 if propios > rival else (1 if propios == rival else 0))
        h2h_gd.setdefault(clave, []).append((h, gh - ga))
    return pd.DataFrame(filas).set_index('MATCH_ID')


COLS_CUOTAS = ['PROB_IMP_H', 'PROB_IMP_D', 'PROB_IMP_A', 'OVERROUND']
COLS_EXTRAS = ['H2H_GD3', 'DIFF_DESCANSO', 'DIFF_RACHA_V', 'DIFF_SIN_PERDER',
               'DIFF_PPG', 'DIFF_POSICION']


def evaluar(X_df, topo, y, fechas, corte=None) -> dict:
    corte = corte if corte is not None else fechas.quantile(0.80)
    m_tr = (fechas < corte).values
    m_va = ~m_tr
    # imputación de cuotas con medias del TRAIN (mismo patrón v11 del Mundial)
    X = X_df.copy()
    for c in COLS_CUOTAS:
        if c in X.columns:
            X[c] = X[c].fillna(X.loc[m_tr, c].mean())
    X_tr_n, X_va_n, _ = fe.normalizar_features(X[m_tr], X[m_va])
    modelo = construir_ensemble()
    modelo.fit(np.hstack([X_tr_n, topo[m_tr]]), y[m_tr])
    proba = modelo.predict_proba(np.hstack([X_va_n, topo[m_va]]))
    y_va = y[m_va]
    acc = float(accuracy_score(y_va, proba.argmax(axis=1)))
    ll = float(log_loss(y_va, proba, labels=[0, 1, 2]))
    conf = proba.max(axis=1)
    alta = conf > 0.70
    acc70 = float(accuracy_score(y_va[alta], proba[alta].argmax(axis=1))) \
        if alta.sum() >= 15 else None
    return {'acc': round(acc, 4), 'logloss': round(ll, 4), 'n_val': int(m_va.sum()),
            'acc_conf70': round(acc70, 4) if acc70 else None, 'n_conf70': int(alta.sum())}


def con_cols(ctx, cols):
    ids = [m[3] for m in ctx['ds']['meta']]
    ext = ctx['extras'].reindex(ids).reset_index(drop=True)
    X = ctx['X_df'].reset_index(drop=True).copy()
    for c in cols:
        X[c] = ext[c].values
        if c not in COLS_CUOTAS:
            X[c] = X[c].fillna(0.0)
    return X


def preparar(clave: str) -> dict:
    df = league_engine.descargar_liga(clave)
    ds = fe.construir_dataset_supervisado(df)
    topo = calcular_features_topologicas(ds)
    return {'df': df, 'ds': ds, 'topo': topo, 'extras': extras_liga(df),
            'X_df': ds['X_df'], 'y': ds['y'], 'fechas': ds['fechas']}


def experimentar_liga(clave: str) -> dict:
    logger.info(f"=== {clave} ===")
    ctx = preparar(clave)
    cobertura = float(ctx['extras']['PROB_IMP_H'].notna().mean())
    out = {'n_partidos': len(ctx['X_df']), 'cobertura_cuotas': round(cobertura, 3)}

    out['baseline'] = evaluar(ctx['X_df'], ctx['topo'], ctx['y'], ctx['fechas'])
    out['h2h_gd3'] = evaluar(con_cols(ctx, ['H2H_GD3']), ctx['topo'], ctx['y'], ctx['fechas'])
    out['descanso'] = evaluar(con_cols(ctx, ['DIFF_DESCANSO']), ctx['topo'], ctx['y'], ctx['fechas'])
    out['rachas'] = evaluar(con_cols(ctx, ['DIFF_RACHA_V', 'DIFF_SIN_PERDER']),
                            ctx['topo'], ctx['y'], ctx['fechas'])
    out['tabla'] = evaluar(con_cols(ctx, ['DIFF_PPG', 'DIFF_POSICION']),
                           ctx['topo'], ctx['y'], ctx['fechas'])
    if cobertura >= 0.5:
        out['cuotas'] = evaluar(con_cols(ctx, COLS_CUOTAS), ctx['topo'], ctx['y'], ctx['fechas'])
        out['extras_cuotas'] = evaluar(con_cols(ctx, COLS_EXTRAS + COLS_CUOTAS),
                                       ctx['topo'], ctx['y'], ctx['fechas'])
    out['extras'] = evaluar(con_cols(ctx, COLS_EXTRAS), ctx['topo'], ctx['y'], ctx['fechas'])

    # forma exponencial (reconstruye dataset con la ponderación nueva)
    original = fe.media_ponderada

    def exponencial(valores):
        if not valores:
            return 0.0
        v = list(valores)[-5:]
        w = np.array([0.6 ** (len(v) - 1 - i) for i in range(len(v))])
        return float(np.dot(v, w / w.sum()))
    fe.media_ponderada = exponencial
    try:
        ds2 = fe.construir_dataset_supervisado(ctx['df'])
        topo2 = calcular_features_topologicas(ds2)
        out['forma_exp'] = evaluar(ds2['X_df'], topo2, ds2['y'], ds2['fechas'])
    finally:
        fe.media_ponderada = original

    # histórico ampliado a ~10 temporadas
    try:
        if clave in ARCHIVO_FD:
            cfg = dict(LEAGUES[clave])
            cfg['urls'] = [f'{FD_BASE}/mmz4281/{s}/{ARCHIVO_FD[clave]}.csv'
                           for s in TEMPORADAS_10]
            LEAGUES[clave], respaldo = cfg, LEAGUES[clave]
        elif clave == 'liga_mx':
            cfg = dict(LEAGUES[clave])
            cfg['anios_ventana'] = 12
            LEAGUES[clave], respaldo = cfg, LEAGUES[clave]
        else:
            respaldo = None
        if respaldo is not None:
            try:
                df3 = league_engine.descargar_liga(clave)
                ds3 = fe.construir_dataset_supervisado(df3)
                topo3 = calcular_features_topologicas(ds3)
                # validación = mismo periodo (20 % final del dataset CORTO)
                corte = ctx['fechas'].quantile(0.80)
                out['historico_10t'] = evaluar(ds3['X_df'], topo3, ds3['y'],
                                               ds3['fechas'], corte=corte)
            finally:
                LEAGUES[clave] = respaldo
    except Exception as e:
        logger.warning(f"[{clave}] historico_10t falló: {e}")

    base = out['baseline']
    for nombre, r in out.items():
        if not isinstance(r, dict) or 'acc' not in r:
            continue
        d = '' if nombre == 'baseline' else \
            f" (Δacc {100*(r['acc']-base['acc']):+.2f} pp, Δll {r['logloss']-base['logloss']:+.4f})"
        logger.info(f"  [{clave}/{nombre}] acc={r['acc']:.4f} ll={r['logloss']:.4f} "
                    f"conf70={r['acc_conf70']}{d}")
    return out


if __name__ == '__main__':
    objetivo = [a for a in sys.argv[1:] if not a.startswith('--')] or LIGAS
    resultados = {}
    for clave in objetivo:
        t0 = time.time()
        try:
            resultados[clave] = experimentar_liga(clave)
            resultados[clave]['segundos'] = round(time.time() - t0, 1)
        except Exception as e:
            logger.error(f"[{clave}] falló: {type(e).__name__}: {e}")
    with open(RESULTADOS_FILE, 'w', encoding='utf-8') as f:
        json.dump(resultados, f, ensure_ascii=False, indent=2)
    logger.info(f"Resultados guardados en {RESULTADOS_FILE}")
