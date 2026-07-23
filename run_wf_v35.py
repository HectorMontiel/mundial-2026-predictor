#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Walk-forward v35 — arnés único para los dos frentes de fútbol del spec:

  §2  Europa League / Conference League: ¿el modelo bate a su línea base
      (favorito por ELO) con ventanas móviles?
  §3  CDI en fútbol: A/B de los grupos 'cdi' (CDI_SEDE + CDI_VIAJE) sobre la
      configuración ADOPTADA de cada competición con viajes largos.

Mismo protocolo que v24/v26/v33: ventanas de 6 meses desde el percentil 60
de la historia, entrenando solo con el pasado. Regla de oro: ≥ +0.3 pp sin
empeorar el log-loss más de 0.01 (o mejorar ambos).

Uso:  python run_wf_v35.py [liga ...]      → resultados_v35.json
"""

import json
import logging
import sys
import warnings

warnings.filterwarnings('ignore')

import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, log_loss

import cdi_futbol
import feature_engineering as fe
import features_v26 as f26
import league_engine
import momentum_tactico as mt
from config import LEAGUES
from train_tda_model import construir_ensemble, calcular_features_topologicas

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

ARCHIVO = 'resultados_v35.json'
MIN_PARTIDOS_VENTANA = 50
MIN_TRAIN = 200
LIGAS_CDI = ['champions', 'europa_league', 'conference_league', 'mls', 'liga_mx']


def _extras_adoptadas(clave: str, df: pd.DataFrame, ids):
    """Reproduce las features extra ADOPTADAS en producción para la liga."""
    grupos = LEAGUES[clave].get('features_extra', [])
    cols = league_engine.columnas_extra(clave)
    if not cols:
        return {}, []
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
    if any(g.startswith('mls_') for g in grupos):
        import mls_features
        extras_df = extras_df.join(mls_features.features_mls(df))
    if any(g in grupos for g in ('ent', 'elo_d', 'urg')):
        v26_df, _ = f26.features_v26(df)
        extras_df = extras_df.join(v26_df)
    ext = extras_df.reindex(ids).reset_index(drop=True)
    return {c: ext[c].values for c in cols}, cols


def _dataset(clave: str):
    df = pd.read_csv(f'historico_{clave}.csv', parse_dates=['date'])
    ds = fe.construir_dataset_supervisado(df)
    X_df = ds['X_df'].reset_index(drop=True).copy()
    ids = [m[3] for m in ds['meta']]
    valores, cols_base = _extras_adoptadas(clave, df, ids)
    elo_alineado = _elo_alineado(df, ids)
    for c, v in valores.items():
        X_df[c] = v
    mapa = cdi_futbol.mapa_tz_liga(clave, df)
    cdi_df = cdi_futbol.features_cdi(df, mapa).reindex(ids).reset_index(drop=True)
    for c in cdi_futbol.COLS_CDI:
        X_df[c] = cdi_df[c].values
    if 'urg' not in LEAGUES[clave].get('features_extra', []):
        urg_df, _ = f26.features_v26(df)
        urg_df = urg_df.reindex(ids).reset_index(drop=True)
        for c in f26.COLS_URG:
            X_df[c] = urg_df[c].values
    cobertura = float((cdi_df['CDI_SEDE'].abs() > 1e-9).mean())
    topo = calcular_features_topologicas(ds)
    return (X_df, ds['y'], ds['fechas'], topo, cols_base, cobertura, mapa,
            elo_alineado)


def _modelo(clave):
    if LEAGUES[clave].get('calibracion') == 'beta':
        return league_engine.ModeloBetaCalibrado()
    return construir_ensemble()


def _elo_alineado(df: pd.DataFrame, ids) -> np.ndarray:
    """ELO diff del histórico alineado por MATCH_ID con el dataset supervisado
    (que descarta las primeras jornadas de cada equipo)."""
    if 'elo_diff' not in df.columns:
        df = df.assign(elo_diff=league_engine._elo_diff_liga(df))
    serie = pd.Series(df['elo_diff'].values, index=df['MATCH_ID'])
    serie = serie[~serie.index.duplicated(keep='last')]
    return serie.reindex(ids).fillna(0.0).values


def wf_liga(clave: str) -> dict:
    X_df, y, fechas, topo, cols_base, cobertura, mapa, elo = _dataset(clave)
    cols_modelo = list(fe.FEATURES_MODELO)
    variantes = {'base': cols_modelo + cols_base,
                 'cdi': cols_modelo + cols_base + cdi_futbol.COLS_CDI}
    # §2: en las competiciones nuevas se prueba además la urgencia asimétrica
    # (el grupo que más aportó en Champions, +1.68 pp en v26).
    if 'urg' not in LEAGUES[clave].get('features_extra', []):
        variantes['urg'] = cols_modelo + cols_base + f26.COLS_URG
        variantes['urg_cdi'] = (cols_modelo + cols_base + f26.COLS_URG
                                + cdi_futbol.COLS_CDI)

    inicio_wf = fechas.quantile(0.60).normalize().replace(day=1)
    ventanas = pd.date_range(inicio_wf, fechas.max(), freq='6MS')
    res = {v: [] for v in variantes}
    res['elo'] = []
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
        # línea base ELO sobre la misma ventana (0 = local, 2 = visitante)
        pred_elo = np.where(elo[m_va] >= 0, 0, 2)
        acc_elo = float(accuracy_score(y[m_va], pred_elo))
        res['elo'].append({'ventana': str(inicio.date()), 'acc': round(acc_elo, 4)})
        fila['elo'] = f"{acc_elo:.3f}"
        logger.info(f"  [{clave}] {inicio.date()} n={m_va.sum()} :: "
                    + ' · '.join(f'{k} {v}' for k, v in fila.items()))
    if not res['base']:
        logger.warning(f"[{clave}] sin ventanas válidas.")
        return {}

    def _media(v, campo='acc'):
        return round(float(np.mean([f[campo] for f in res[v]])), 4)

    acc_b, ll_b = _media('base'), _media('base', 'll')

    def _pasa(v):
        a, l = _media(v), _media(v, 'll')
        return ((a - acc_b >= 0.003 and l - ll_b <= 0.01)
                or (a > acc_b and l < ll_b))

    pasa = _pasa('cdi')
    medias = {'base': {'acc': acc_b, 'll': ll_b}, 'elo': {'acc': _media('elo')}}
    for v in variantes:
        if v == 'base':
            continue
        medias[v] = {'acc': _media(v), 'll': _media(v, 'll'),
                     'pasa_regla_de_oro': bool(_pasa(v))}
    acc_c, ll_c = _media('cdi'), _media('cdi', 'll')
    salida = {
        'ventanas': res,
        'media': medias,
        'cobertura_cdi': round(cobertura, 3),
        'supera_elo': bool(acc_b > _media('elo')),
        'adoptar_cdi': bool(pasa and cobertura >= 0.10),
        'equipos_con_huso': len(mapa),
    }
    logger.info(f"[{clave}] base {acc_b}/{ll_b} · cdi {acc_c}/{ll_c} "
                f"(cobertura {cobertura:.0%}) · ELO {_media('elo')} → "
                f"CDI {'ADOPTADO' if salida['adoptar_cdi'] else 'descartado'}")
    return salida


if __name__ == '__main__':
    objetivos = [a for a in sys.argv[1:] if not a.startswith('--')] or LIGAS_CDI
    todo = {}
    for clave in objetivos:
        try:
            r = wf_liga(clave)
            if r:
                todo[clave] = r
        except Exception as e:
            logger.error(f"[{clave}] falló: {type(e).__name__}: {e}")
    with open(ARCHIVO, 'w', encoding='utf-8') as fh:
        json.dump(todo, fh, ensure_ascii=False, indent=1)
    print(json.dumps({k: v['media'] for k, v in todo.items()},
                     ensure_ascii=False, indent=1))
