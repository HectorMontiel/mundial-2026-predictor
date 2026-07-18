#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Walk-forward A/B de las features ortogonales v26 (spec §1.2-§1.4).

Variantes con ventanas idénticas de 6 meses (arnés v24/v25):
  base   — configuración ADOPTADA de producción de la liga
  ent    — base + entropía táctica y volatilidad (§1.2)
  elo_d  — base + derivadas del ELO (§1.3)
  urg    — base + índice de urgencia asimétrica (§1.4)

Regla de oro (≥ +0.3 pp sin ll > +0.01, o mejora ambos). Si varias pasan,
gana la de mejor log-loss; la combinación de ganadoras se validará aparte
antes de adoptarse junta. Resultado → resultados_feats_v26.json.

Uso: python run_wf_feats_v26.py [liga ...]     # sin args: todas las de clubes
"""

import json
import logging
import os
import sys
import warnings

warnings.filterwarnings('ignore')

import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, log_loss

import feature_engineering as fe
import features_v26 as f26
import league_engine
import momentum_tactico as mt
from config import LEAGUES
from train_tda_model import construir_ensemble, calcular_features_topologicas

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

ARCHIVO = 'resultados_feats_v26.json'
MIN_PARTIDOS_VENTANA = 60
MIN_TRAIN = 250
GRUPOS = {'ent': f26.COLS_ENT, 'elo_d': f26.COLS_ELO_D, 'urg': f26.COLS_URG}


def _dataset(clave: str):
    df = pd.read_csv(f'historico_{clave}.csv', parse_dates=['date'])
    ds = fe.construir_dataset_supervisado(df)
    X_df = ds['X_df'].reset_index(drop=True).copy()
    ids = [m[3] for m in ds['meta']]
    grupos = LEAGUES[clave].get('features_extra', [])
    # base = config SIN los grupos v26 (aunque ya estén adoptados en config)
    cols_base = [c for c in league_engine.columnas_extra(clave)
                 if c not in f26.COLS_V26]
    if cols_base:
        extras_df, _ = league_engine.features_extra_liga(df)
        if 'mx' in grupos:
            extras_df = extras_df.join(league_engine.features_mx(df))
        if 'imt' in grupos or 'imt_c' in grupos:
            imt_df, _ = mt.features_imt(df)
            if 'imt_c' in grupos:
                coef = mt.optimizar_coeficientes(
                    df, imt_df, hasta_fecha=df['date'].quantile(0.60))['coef']
                imt_df = imt_df.join(mt.indice_compuesto(imt_df, coef))
            extras_df = extras_df.join(imt_df)
        ext = extras_df.reindex(ids).reset_index(drop=True)
        for c in cols_base:
            X_df[c] = ext[c].values
    nuevas_df, _ = f26.features_v26(df)
    ext26 = nuevas_df.reindex(ids).reset_index(drop=True)
    for c in f26.COLS_V26:
        X_df[c] = ext26[c].values
    topo = calcular_features_topologicas(ds)
    return X_df, ds['y'], ds['fechas'], topo, cols_base


def _modelo(clave):
    if LEAGUES[clave].get('calibracion') == 'beta':
        return league_engine.ModeloBetaCalibrado()
    return construir_ensemble()


def wf_liga(clave: str) -> dict:
    X_df, y, fechas, topo, cols_base = _dataset(clave)
    cols_modelo = list(fe.FEATURES_MODELO)
    variantes = {'base': cols_modelo + cols_base}
    for g, cols_g in GRUPOS.items():
        variantes[g] = cols_modelo + cols_base + cols_g

    inicio_wf = fechas.quantile(0.60).normalize().replace(day=1)
    ventanas = pd.date_range(inicio_wf, fechas.max(), freq='6MS')
    res = {v: [] for v in variantes}
    for inicio in ventanas:
        fin = inicio + pd.DateOffset(months=6)
        m_tr = (fechas < inicio).values
        m_va = ((fechas >= inicio) & (fechas < fin)).values
        if m_va.sum() < MIN_PARTIDOS_VENTANA or m_tr.sum() < MIN_TRAIN:
            continue
        fila = {}
        for nombre, cols in variantes.items():
            Xv = X_df[cols].copy()
            for c in cols:
                if c in league_engine.COLS_CUOTAS:
                    Xv[c] = Xv[c].fillna(float(pd.to_numeric(
                        Xv.loc[m_tr, c], errors='coerce').mean()))
                else:
                    Xv[c] = Xv[c].fillna(0.0)
            X_tr_n, X_va_n, _ = fe.normalizar_features(Xv[m_tr], Xv[m_va])
            modelo = _modelo(clave)
            modelo.fit(np.hstack([X_tr_n, topo[m_tr]]), y[m_tr])
            proba = modelo.predict_proba(np.hstack([X_va_n, topo[m_va]]))
            acc = float(accuracy_score(y[m_va], proba.argmax(axis=1)))
            ll = float(log_loss(y[m_va], proba, labels=[0, 1, 2]))
            res[nombre].append({'ventana': str(inicio.date()), 'n': int(m_va.sum()),
                                'acc': round(acc, 4), 'll': round(ll, 4)})
            fila[nombre] = f"{acc:.3f}/{ll:.3f}"
        logger.info(f"  [{clave}] {inicio.date()} n={m_va.sum()} :: "
                    + ' · '.join(f'{k} {v}' for k, v in fila.items()))
    if not res['base']:
        return {}

    def _media(v):
        return (round(float(np.mean([f['acc'] for f in res[v]])), 4),
                round(float(np.mean([f['ll'] for f in res[v]])), 4))

    acc_b, ll_b = _media('base')
    salida = {'ventanas': res,
              'media': {v: {'acc': _media(v)[0], 'll': _media(v)[1]}
                        for v in res}}
    adoptar = None
    for v in GRUPOS:
        acc_v, ll_v = _media(v)
        pasa = ((acc_v - acc_b >= 0.003 and ll_v - ll_b <= 0.01)
                or (acc_v > acc_b and ll_v < ll_b))
        salida['media'][v]['pasa_regla_de_oro'] = bool(pasa)
        if pasa and (adoptar is None or ll_v < salida['media'][adoptar]['ll']):
            adoptar = v
    salida['adoptar'] = adoptar
    logger.info(f"[{clave}] base {acc_b}/{ll_b} · "
                + ' · '.join(f'{v} {_media(v)}' for v in GRUPOS)
                + f" → ADOPTAR: {adoptar or 'ninguna'}")
    return salida


if __name__ == '__main__':
    objetivos = sys.argv[1:] or [c for c, cfg in LEAGUES.items()
                                 if cfg.get('disponible')]
    salida = {}
    if os.path.exists(ARCHIVO):
        with open(ARCHIVO, encoding='utf-8') as f:
            salida = json.load(f)
    for clave in objetivos:
        logger.info(f"=== features v26 walk-forward {clave} ===")
        try:
            r = wf_liga(clave)
            if r:
                salida[clave] = r
        except Exception as e:
            logger.error(f"[{clave}] falló: {type(e).__name__}: {e}")
        with open(ARCHIVO, 'w', encoding='utf-8') as f:
            json.dump(salida, f, ensure_ascii=False, indent=2)
    print(json.dumps({k: {'base': v['media']['base'],
                          **{g: v['media'][g] for g in GRUPOS},
                          'adoptar': v['adoptar']}
                      for k, v in salida.items()}, indent=2))
