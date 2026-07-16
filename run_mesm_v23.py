#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Experimento MESM v23 — walk-forward por liga con cuotas de cierre.

Por ventana de 6 meses (sobre el último 40 % del histórico):
  base  = ensemble del proyecto entrenado con el 75 % inicial del train
  meta  = MetaEnsemble ajustado con el 25 % final del train (stacking sin fuga)
  se comparan EN LA MISMA validación: base vs meta vs favorito del mercado,
  con precisión, log-loss y ROI simulado (1 u si p>50 % y EV>0, cierre real).

Uso: python run_mesm_v23.py [liga ...]
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
import meta_ensemble as me
from train_tda_model import construir_ensemble, calcular_features_topologicas

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

LIGAS = ['liga_mx', 'premier', 'laliga', 'serie_a', 'bundesliga',
         'ligue_1', 'eredivisie', 'primeira']


def evaluar_liga(clave: str) -> dict:
    df = pd.read_csv(f'historico_{clave}.csv', parse_dates=['date'])
    ds = fe.construir_dataset_supervisado(df)
    X_df, y, fechas = ds['X_df'], np.array(ds['y']), ds['fechas']
    topo = calcular_features_topologicas(ds)
    ids = [m[3] for m in ds['meta']]
    cuotas = df.set_index('MATCH_ID').reindex(ids)[['odd_home', 'odd_draw', 'odd_away']]
    mkt = me.probs_mercado(cuotas)
    con_mkt = np.isfinite(mkt).all(axis=1)
    logger.info(f"[{clave}] {len(X_df)} partidos, cuotas en {con_mkt.mean()*100:.0f} %")

    inicio_eval = fechas.quantile(0.60)
    ventanas = pd.date_range(inicio_eval.normalize(), fechas.max(), freq='6MS')
    filas = []
    for ini in ventanas:
        fin = ini + pd.DateOffset(months=6)
        m_tr = (fechas < ini).values & con_mkt
        m_va = ((fechas >= ini) & (fechas < fin)).values & con_mkt
        if m_va.sum() < 60 or m_tr.sum() < 250:
            continue
        idx_tr = np.where(m_tr)[0]
        corte = int(len(idx_tr) * 0.75)
        idx_fit, idx_meta = idx_tr[:corte], idx_tr[corte:]
        if len(idx_meta) < 80:
            continue

        Xn_fit, _, esc = fe.normalizar_features(X_df.iloc[idx_fit], None)
        base = construir_ensemble()
        base.fit(np.hstack([Xn_fit, topo[idx_fit]]), y[idx_fit])

        def probs_de(idx):
            Xn = esc.transform(X_df.iloc[idx])
            proba = base.predict_proba(np.hstack([Xn, topo[idx]]))
            p = np.zeros((len(idx), 3))
            for k_idx, k in enumerate(base.classes_):
                p[:, int(k)] = proba[:, k_idx]
            return p / p.sum(axis=1, keepdims=True)

        p_meta_tr = probs_de(idx_meta)
        asim = '--simetrico' not in sys.argv
        meta = me.MetaEnsemble().fit(y[idx_meta], p_meta_tr, mkt[idx_meta],
                                     asimetrico=asim)

        idx_va = np.where(m_va)[0]
        p_base = probs_de(idx_va)
        p_mesm = meta.predict_proba(p_base, mkt[idx_va])
        y_va = y[idx_va]
        fav_mkt = mkt[idx_va, :3].argmax(axis=1)
        cuotas_va = cuotas.iloc[idx_va]

        fila = {
            'ventana': f"{ini.date()} → {fin.date()}", 'n': int(m_va.sum()),
            'acc_base': round(float(accuracy_score(y_va, p_base.argmax(1))), 4),
            'acc_mesm': round(float(accuracy_score(y_va, p_mesm.argmax(1))), 4),
            'acc_mercado': round(float(accuracy_score(y_va, fav_mkt)), 4),
            'll_base': round(float(log_loss(y_va, p_base, labels=[0, 1, 2])), 4),
            'll_mesm': round(float(log_loss(y_va, p_mesm, labels=[0, 1, 2])), 4),
            'roi_base': me.roi_simulado(y_va, p_base, cuotas_va),
            'roi_mesm': me.roi_simulado(y_va, p_mesm, cuotas_va),
        }
        filas.append(fila)
        logger.info(f"  {clave} {ini.date()}: base {fila['acc_base']:.3f}/{fila['ll_base']:.3f} "
                    f"→ mesm {fila['acc_mesm']:.3f}/{fila['ll_mesm']:.3f} "
                    f"(mercado {fila['acc_mercado']:.3f})")
    if not filas:
        return {'liga': clave, 'ventanas': []}

    def media(k):
        return round(float(np.mean([f[k] for f in filas])), 4)

    def roi_medio(k):
        vals = [f[k]['roi_pct'] for f in filas if f[k]]
        return round(float(np.mean(vals)), 2) if vals else None

    return {'liga': clave, 'ventanas': filas,
            'acc_base': media('acc_base'), 'acc_mesm': media('acc_mesm'),
            'acc_mercado': media('acc_mercado'),
            'll_base': media('ll_base'), 'll_mesm': media('ll_mesm'),
            'roi_base_medio': roi_medio('roi_base'),
            'roi_mesm_medio': roi_medio('roi_mesm'),
            'golden_rule': bool(media('acc_mesm') - media('acc_base') >= 0.003
                                and media('ll_mesm') - media('ll_base') <= 0.01
                                or (media('acc_mesm') > media('acc_base')
                                    and media('ll_mesm') < media('ll_base')))}


if __name__ == '__main__':
    objetivo = [a for a in sys.argv[1:] if not a.startswith('-')] or LIGAS
    salida = ('resultados_mesm_v23_simetrico.json' if '--simetrico' in sys.argv
              else 'resultados_mesm_v23.json')
    resultados = {}
    for clave in objetivo:
        try:
            resultados[clave] = evaluar_liga(clave)
        except Exception as e:
            logger.error(f"[{clave}] falló: {type(e).__name__}: {e}")
    with open(salida, 'w', encoding='utf-8') as f:
        json.dump(resultados, f, indent=2, ensure_ascii=False)
    print(json.dumps({k: {kk: v[kk] for kk in
                          ('acc_base', 'acc_mesm', 'acc_mercado', 'll_base',
                           'll_mesm', 'roi_base_medio', 'roi_mesm_medio',
                           'golden_rule') if kk in v}
                      for k, v in resultados.items()}, indent=2))
