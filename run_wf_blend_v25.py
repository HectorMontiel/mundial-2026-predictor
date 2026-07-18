#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Walk-forward del blending modelo/mercado 70/30 (v25, spec §2.3).

    p_final = 0.7·p_modelo + 0.3·p_mercado_implícita

Objetivo: LaLiga y Ligue 1, las dos ligas donde ni el MESM ni el IMT
lograron acercarse al mercado. El blending es una combinación fija (sin
parámetros que ajustar → sin riesgo de sobreajuste) y solo actúa cuando el
partido tiene cuotas.

Por ventana de 6 meses (arnés v24): el modelo de la config ADOPTADA se
entrena una vez; se evalúan base, blend 70/30 y mercado en las filas CON
cuotas. También se reporta el barrido de pesos 50-90 % (solo informativo —
la adopción es del 70/30 de la spec para no elegir el peso con el test).

Uso: python run_wf_blend_v25.py [liga ...]      # sin args: laliga ligue_1
"""

import json
import logging
import sys
import warnings

warnings.filterwarnings('ignore')

import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, log_loss

import feature_engineering as fe
import league_engine
import meta_ensemble as me
import momentum_tactico as mt
from config import LEAGUES
from train_tda_model import construir_ensemble, calcular_features_topologicas

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

ARCHIVO = 'resultados_blend_v25.json'
PESO_MODELO = 0.70
BARRIDO = (0.5, 0.6, 0.7, 0.8, 0.9)


def _dataset(clave: str):
    df = pd.read_csv(f'historico_{clave}.csv', parse_dates=['date'])
    ds = fe.construir_dataset_supervisado(df)
    X_df = ds['X_df'].reset_index(drop=True).copy()
    ids = [m[3] for m in ds['meta']]
    grupos = LEAGUES[clave].get('features_extra', [])
    cols = league_engine.columnas_extra(clave)
    if cols:
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
        for c in cols:
            X_df[c] = ext[c].values
    topo = calcular_features_topologicas(ds)
    cuotas = df.set_index('MATCH_ID').reindex(ids)[['odd_home', 'odd_draw', 'odd_away']]
    mkt = me.probs_mercado(cuotas)
    return X_df, ds['y'], ds['fechas'], topo, mkt, cols


def _modelo(clave):
    if LEAGUES[clave].get('calibracion') == 'beta':
        return league_engine.ModeloBetaCalibrado()
    return construir_ensemble()


def wf_liga(clave: str) -> dict:
    X_df, y, fechas, topo, mkt, cols = _dataset(clave)
    con_mkt = np.isfinite(mkt).all(axis=1)
    cols_todas = list(fe.FEATURES_MODELO) + cols
    inicio_wf = fechas.quantile(0.60).normalize().replace(day=1)
    ventanas = pd.date_range(inicio_wf, fechas.max(), freq='6MS')
    filas = []
    for inicio in ventanas:
        fin = inicio + pd.DateOffset(months=6)
        m_tr = (fechas < inicio).values
        m_va = ((fechas >= inicio) & (fechas < fin)).values & con_mkt
        if m_va.sum() < 60 or m_tr.sum() < 250:
            continue
        Xv = X_df[cols_todas].copy()
        for c in cols:
            if c in league_engine.COLS_CUOTAS:
                Xv[c] = Xv[c].fillna(float(pd.to_numeric(
                    Xv.loc[m_tr, c], errors='coerce').mean()))
            else:
                Xv[c] = Xv[c].fillna(0.0)
        X_tr_n, X_va_n, _ = fe.normalizar_features(Xv[m_tr], Xv[m_va])
        modelo = _modelo(clave)
        modelo.fit(np.hstack([X_tr_n, topo[m_tr]]), y[m_tr])
        pr = modelo.predict_proba(np.hstack([X_va_n, topo[m_va]]))
        p = np.zeros((int(m_va.sum()), 3))
        for k_idx, k in enumerate(modelo.classes_):
            p[:, int(k)] = pr[:, k_idx]
        p /= p.sum(axis=1, keepdims=True)
        pm = mkt[m_va][:, :3]
        y_va = y[m_va]

        fila = {'ventana': str(inicio.date()), 'n': int(m_va.sum()),
                'acc_base': round(float(accuracy_score(y_va, p.argmax(1))), 4),
                'll_base': round(float(log_loss(y_va, p, labels=[0, 1, 2])), 4),
                'acc_mercado': round(float(accuracy_score(y_va, pm.argmax(1))), 4)}
        for w in BARRIDO:
            pb = w * p + (1 - w) * pm
            pb /= pb.sum(axis=1, keepdims=True)
            fila[f'acc_{int(w*100)}'] = round(float(accuracy_score(y_va, pb.argmax(1))), 4)
            fila[f'll_{int(w*100)}'] = round(float(log_loss(y_va, pb, labels=[0, 1, 2])), 4)
        filas.append(fila)
        logger.info(f"  [{clave}] {inicio.date()} n={fila['n']} base "
                    f"{fila['acc_base']:.3f}/{fila['ll_base']:.3f} · 70/30 "
                    f"{fila['acc_70']:.3f}/{fila['ll_70']:.3f} · mercado "
                    f"{fila['acc_mercado']:.3f}")
    if not filas:
        return {}

    def media(k):
        return round(float(np.mean([f[k] for f in filas])), 4)

    acc_b, ll_b = media('acc_base'), media('ll_base')
    acc_bl, ll_bl = media('acc_70'), media('ll_70')
    salida = {
        'ventanas': filas,
        'media': {'base': {'acc': acc_b, 'll': ll_b},
                  'blend_70_30': {'acc': acc_bl, 'll': ll_bl},
                  'mercado': {'acc': media('acc_mercado')},
                  'barrido_informativo': {
                      str(int(w*100)): {'acc': media(f'acc_{int(w*100)}'),
                                        'll': media(f'll_{int(w*100)}')}
                      for w in BARRIDO}},
        'adoptar': bool((acc_bl - acc_b >= 0.003 and ll_bl - ll_b <= 0.01)
                        or (acc_bl > acc_b and ll_bl < ll_b)),
    }
    logger.info(f"[{clave}] base {acc_b}/{ll_b} → blend70 {acc_bl}/{ll_bl} "
                f"(mercado {media('acc_mercado')}) · "
                f"{'ADOPTAR' if salida['adoptar'] else 'descartado'}")
    return salida


if __name__ == '__main__':
    objetivos = sys.argv[1:] or ['laliga', 'ligue_1']
    salida = {}
    for clave in objetivos:
        try:
            r = wf_liga(clave)
            if r:
                salida[clave] = r
        except Exception as e:
            logger.error(f"[{clave}] falló: {type(e).__name__}: {e}")
        with open(ARCHIVO, 'w', encoding='utf-8') as f:
            json.dump(salida, f, ensure_ascii=False, indent=2)
    print(json.dumps({k: {'media': v['media']['blend_70_30'],
                          'base': v['media']['base'], 'adoptar': v['adoptar']}
                      for k, v in salida.items()}, indent=2))
