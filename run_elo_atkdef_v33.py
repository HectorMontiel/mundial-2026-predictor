#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ELO Ataque/Defensa descompuesto (v33 §3.1) — walk-forward por liga.

Cada equipo mantiene DOS ratings: ELO_ATK (capacidad de marcar) y ELO_DEF
(capacidad de evitar goles). Tras cada partido se actualizan enfrentando el
ataque de uno contra la defensa del otro, con el resultado esperado dado por
la forma logística habitual y el "resultado observado" derivado de los goles
marcados frente a los esperados por ese emparejamiento.

Features nuevas (diferencias que el ELO global no puede expresar):
    ATK_H_vs_DEF_A = ELO_ATK(local)  − ELO_DEF(visitante)
    DEF_H_vs_ATK_A = ELO_DEF(local)  − ELO_ATK(visitante)

Adopción por liga con la regla de oro (≥ +0.3 pp sin empeorar ll > 0.01).
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

ARCHIVO = 'resultados_elo_atkdef_v33.json'
COLS_AD = ['ATK_H_vs_DEF_A', 'DEF_H_vs_ATK_A']
K = 16
GOLES_MEDIOS = 1.35


def features_atkdef(df: pd.DataFrame):
    """Pase cronológico sin fuga: emite antes de actualizar."""
    atk, dfn = {}, {}
    filas = []
    for r in df.itertuples(index=False):
        h, a = r.home_team, r.away_team
        ah, dh = atk.get(h, 1500.0), dfn.get(h, 1500.0)
        aa, da = atk.get(a, 1500.0), dfn.get(a, 1500.0)
        filas.append({'MATCH_ID': r.MATCH_ID,
                      'ATK_H_vs_DEF_A': (ah - da) / 100.0,
                      'DEF_H_vs_ATK_A': (dh - aa) / 100.0})
        gh, ga = float(r.home_goals), float(r.away_goals)
        # esperado del duelo ataque-vs-defensa (logístico sobre la diferencia)
        e_hl = 1 / (1 + 10 ** ((da - ah) / 400))
        e_av = 1 / (1 + 10 ** ((dh - aa) / 400))
        # observado: fracción de goles sobre el doble de la media (acotado)
        s_hl = float(np.clip(gh / (2 * GOLES_MEDIOS), 0, 1))
        s_av = float(np.clip(ga / (2 * GOLES_MEDIOS), 0, 1))
        atk[h] = ah + K * (s_hl - e_hl)
        dfn[a] = da - K * (s_hl - e_hl)      # si le marcan, su defensa baja
        atk[a] = aa + K * (s_av - e_av)
        dfn[h] = dh - K * (s_av - e_av)
    estado = {eq: {'atk': round(atk.get(eq, 1500), 1),
                   'def': round(dfn.get(eq, 1500), 1)}
              for eq in set(list(atk) + list(dfn))}
    return pd.DataFrame(filas).set_index('MATCH_ID'), estado


def _dataset(clave: str):
    df = pd.read_csv(f'historico_{clave}.csv', parse_dates=['date'])
    ds = fe.construir_dataset_supervisado(df)
    X_df = ds['X_df'].reset_index(drop=True).copy()
    ids = [m[3] for m in ds['meta']]
    grupos = LEAGUES[clave].get('features_extra', [])
    cols_base = league_engine.columnas_extra(clave)
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
        if any(g in grupos for g in ('ent', 'elo_d', 'urg')):
            extras_df = extras_df.join(f26.features_v26(df)[0])
        if any(g.startswith('mls_') for g in grupos):
            import mls_features
            extras_df = extras_df.join(mls_features.features_mls(df))
        ext = extras_df.reindex(ids).reset_index(drop=True)
        for c in cols_base:
            X_df[c] = ext[c].values
    ad, _ = features_atkdef(df)
    ext_ad = ad.reindex(ids).reset_index(drop=True)
    for c in COLS_AD:
        X_df[c] = ext_ad[c].values
    return X_df, ds['y'], ds['fechas'], calcular_features_topologicas(ds), cols_base


def _modelo(clave):
    if LEAGUES[clave].get('calibracion') == 'beta':
        return league_engine.ModeloBetaCalibrado()
    return construir_ensemble()


def wf_liga(clave: str) -> dict:
    X_df, y, fechas, topo, cols_base = _dataset(clave)
    cols_modelo = list(fe.FEATURES_MODELO)
    variantes = {'base': cols_modelo + cols_base,
                 'atkdef': cols_modelo + cols_base + COLS_AD}
    inicio = fechas.quantile(0.60).normalize().replace(day=1)
    res = {v: [] for v in variantes}
    for ini in pd.date_range(inicio, fechas.max(), freq='6MS'):
        fin = ini + pd.DateOffset(months=6)
        m_tr = (fechas < ini).values
        m_va = ((fechas >= ini) & (fechas < fin)).values
        if m_va.sum() < 60 or m_tr.sum() < 250:
            continue
        for nombre, cols in variantes.items():
            Xv = X_df[cols].copy()
            for c in cols:
                if c in league_engine.COLS_CUOTAS:
                    Xv[c] = Xv[c].fillna(float(pd.to_numeric(
                        Xv.loc[m_tr, c], errors='coerce').mean()))
                else:
                    Xv[c] = Xv[c].fillna(0.0)
            Xtr, Xva, _ = fe.normalizar_features(Xv[m_tr], Xv[m_va])
            mod = _modelo(clave)
            mod.fit(np.hstack([Xtr, topo[m_tr]]), y[m_tr])
            pr = mod.predict_proba(np.hstack([Xva, topo[m_va]]))
            res[nombre].append((float(accuracy_score(y[m_va], pr.argmax(axis=1))),
                                float(log_loss(y[m_va], pr, labels=[0, 1, 2]))))
    if not res['base']:
        return {}
    def _m(k, i):
        return round(float(np.mean([v[i] for v in res[k]])), 4)
    salida = {'base': {'acc': _m('base', 0), 'll': _m('base', 1)},
              'atkdef': {'acc': _m('atkdef', 0), 'll': _m('atkdef', 1)},
              'ventanas': len(res['base'])}
    salida['adoptar'] = bool(
        (salida['atkdef']['acc'] - salida['base']['acc'] >= 0.003
         and salida['atkdef']['ll'] - salida['base']['ll'] <= 0.01)
        or (salida['atkdef']['acc'] > salida['base']['acc']
            and salida['atkdef']['ll'] < salida['base']['ll']))
    logger.info(f"[{clave}] base {salida['base']} · atkdef {salida['atkdef']} "
                f"→ {'ADOPTAR' if salida['adoptar'] else 'descartado'}")
    return salida


if __name__ == '__main__':
    objetivos = sys.argv[1:] or [c for c, cfg in LEAGUES.items()
                                 if cfg.get('disponible')]
    salida = {}
    if os.path.exists(ARCHIVO):
        with open(ARCHIVO, encoding='utf-8') as f:
            salida = json.load(f)
    for clave in objetivos:
        logger.info(f"=== ELO atk/def {clave} ===")
        try:
            r = wf_liga(clave)
            if r:
                salida[clave] = r
        except Exception as e:
            logger.error(f"[{clave}] falló: {type(e).__name__}: {e}")
        with open(ARCHIVO, 'w', encoding='utf-8') as f:
            json.dump(salida, f, ensure_ascii=False, indent=2)
    print(json.dumps({k: {'base': v['base']['acc'], 'atkdef': v['atkdef']['acc'],
                          'adoptar': v['adoptar']}
                      for k, v in salida.items()}, indent=2))
