#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Walk-forward del tenis v67 — ¿aportan las fuentes nuevas?

Tres ramas, MISMAS ventanas y —esto es lo importante— **el mismo conjunto de
test** en las tres, para que la comparación sea válida:

  base   producción actual (ATP: vector v30 · WTA: vector v35), entrenando
         SOLO con las filas de Kaggle (circuito principal).
  datos  mismas features, entrenando con el histórico UNIFICADO (Kaggle +
         fases previas de ESPN + Challenger/WTA125/ITF que ESPN publica).
  nivel  `datos` + las tres features de nivel de competición de v67
         (DIFF_ELO_NIVEL, NIVEL_PARTIDO, DIFF_EXP_NIVEL).

El test de cada ventana son SIEMPRE las filas de Kaggle (circuito principal):
es el universo con el que se validó hasta v66, así que la comparación es
manzana-con-manzana. Aparte se reporta la precisión sobre las filas NUEVAS
(categorías inferiores y previas), que es capacidad que antes no existía.

Regla de adopción (la del proyecto desde v26): +0.3 pp de precisión sin
empeorar el log-loss más de 0.01, o mejorar ambas cosas a la vez.

Uso:  .venv\\Scripts\\python.exe run_wf_tenis_v67.py [atp|wta]
"""

import json
import logging
import sys
import warnings

warnings.filterwarnings('ignore')

import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import RandomForestClassifier, VotingClassifier
from sklearn.metrics import accuracy_score, log_loss
from sklearn.preprocessing import StandardScaler
from lightgbm import LGBMClassifier
from xgboost import XGBClassifier

from engines.tennis_engine import (FEATURES_V30, FEATURES_V35, FEATURES_V67,
                                   FEATURES_V69_ATP, FEATURES_V69_WTA,
                                   TennisEngine)

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

ARCHIVO = 'resultados_tenis_v69.json'
MIN_VENTANA = 300
BASE_POR_CIRCUITO = {'atp': FEATURES_V30, 'wta': FEATURES_V35}
# v69: base de producción + las tres features de saque/resto
SAQUE_POR_CIRCUITO = {'atp': FEATURES_V69_ATP, 'wta': FEATURES_V69_WTA}


def _modelo():
    vc = VotingClassifier([
        ('xgb', XGBClassifier(n_estimators=200, max_depth=4,
                              learning_rate=0.05, verbosity=0)),
        ('lgbm', LGBMClassifier(n_estimators=200, max_depth=4,
                                learning_rate=0.05, verbose=-1)),
        ('rf', RandomForestClassifier(n_estimators=200, max_depth=8,
                                      random_state=42))], voting='soft')
    return CalibratedClassifierCV(vc, method='isotonic', cv=3)


def _evaluar(X_tr, y_tr, X_va, y_va):
    sc = StandardScaler().fit(X_tr)
    mod = _modelo().fit(sc.transform(X_tr), y_tr)
    p1 = mod.predict_proba(sc.transform(X_va))[:, list(mod.classes_).index(1)]
    return (float(accuracy_score(y_va, (p1 >= 0.5).astype(int))),
            float(log_loss(y_va, np.column_stack([1 - p1, p1]), labels=[0, 1])),
            p1)


def wf_circuito(circuito: str) -> dict:
    eng = TennisEngine(circuito)
    cols_base = BASE_POR_CIRCUITO[circuito]

    df = eng.cargar_datos_historicos(unificado=True)
    X_base, y, fechas, odds, estado = eng._dataset(df, cols_base)
    X_niv, _, _, _, _ = eng._dataset(df, FEATURES_V67)
    X_sq, _, _, _, _ = eng._dataset(df, SAQUE_POR_CIRCUITO[circuito])
    meta = estado['filas_meta']
    fuente = np.array([m[0] for m in meta])
    es_kaggle = fuente == 'kaggle'
    logger.info(f"[{circuito}] dataset unificado: {len(X_base)} filas "
                f"({int(es_kaggle.sum())} de Kaggle, {int((~es_kaggle).sum())} nuevas)")

    ultimo = fechas.max()
    cortes = [ultimo - pd.DateOffset(years=k) for k in range(5, 0, -1)]
    res = {k: [] for k in ('base', 'datos', 'nivel', 'saque', 'mercado', 'nuevas')}
    for i, ini in enumerate(cortes):
        fin = cortes[i + 1] if i + 1 < len(cortes) else ultimo + pd.Timedelta(days=1)
        en_ventana = ((fechas >= ini) & (fechas < fin)).values
        antes = (fechas < ini).values
        # TEST idéntico en las tres ramas: circuito principal de la ventana
        m_va = en_ventana & es_kaggle
        if m_va.sum() < MIN_VENTANA:
            continue
        # test adicional (capacidad nueva): filas que antes no existían
        m_nuevas = en_ventana & ~es_kaggle

        fila = {}
        # --- base: entrena solo con Kaggle -----------------------------
        a, l, _ = _evaluar(X_base[antes & es_kaggle], y[antes & es_kaggle],
                           X_base[m_va], y[m_va])
        res['base'].append({'ventana': str(ini.date()), 'n': int(m_va.sum()),
                            'acc': round(a, 4), 'll': round(l, 4)})
        fila['base'] = f'{a:.4f}/{l:.4f}'
        # --- datos: entrena con todo ------------------------------------
        a, l, _ = _evaluar(X_base[antes], y[antes], X_base[m_va], y[m_va])
        res['datos'].append({'ventana': str(ini.date()), 'n': int(m_va.sum()),
                             'acc': round(a, 4), 'll': round(l, 4)})
        fila['datos'] = f'{a:.4f}/{l:.4f}'
        # --- nivel: todo + features de nivel ----------------------------
        a, l, _ = _evaluar(X_niv[antes], y[antes], X_niv[m_va], y[m_va])
        res['nivel'].append({'ventana': str(ini.date()), 'n': int(m_va.sum()),
                             'acc': round(a, 4), 'll': round(l, 4)})
        fila['nivel'] = f'{a:.4f}/{l:.4f}'
        # --- saque: base + saque/resto (v69) ----------------------------
        a, l, _ = _evaluar(X_sq[antes], y[antes], X_sq[m_va], y[m_va])
        res['saque'].append({'ventana': str(ini.date()), 'n': int(m_va.sum()),
                             'acc': round(a, 4), 'll': round(l, 4)})
        fila['saque'] = f'{a:.4f}/{l:.4f}'
        # --- capacidad nueva: categorías inferiores y previas ------------
        if m_nuevas.sum() >= 100:
            a_n, l_n, _ = _evaluar(X_niv[antes], y[antes], X_niv[m_nuevas], y[m_nuevas])
            res['nuevas'].append({'ventana': str(ini.date()),
                                  'n': int(m_nuevas.sum()),
                                  'acc': round(a_n, 4), 'll': round(l_n, 4)})
        # --- referencia de mercado ---------------------------------------
        o = odds[m_va]
        mk = np.isfinite(o).all(axis=1)
        acc_mkt = (float(accuracy_score(y[m_va][mk], (o[mk][:, 0] < o[mk][:, 1]).astype(int)))
                   if mk.sum() > 50 else None)
        res['mercado'].append({'ventana': str(ini.date()),
                               'acc': round(acc_mkt, 4) if acc_mkt else None})
        logger.info(f"  [{circuito}] {ini.date()} n={m_va.sum()} :: "
                    + ' · '.join(f'{k} {v}' for k, v in fila.items())
                    + f" · mercado {acc_mkt}")

    if not res['base']:
        return {}

    def _m(rama, campo='acc'):
        vals = [f[campo] for f in res[rama] if f.get(campo) is not None]
        return round(float(np.mean(vals)), 4) if vals else None

    medias = {r: {'acc': _m(r), 'll': _m(r, 'll')} for r in
              ('base', 'datos', 'nivel', 'saque', 'nuevas')}
    medias['mercado'] = {'acc': _m('mercado')}

    def _pasa(cand):
        a0, l0 = medias['base']['acc'], medias['base']['ll']
        a1, l1 = medias[cand]['acc'], medias[cand]['ll']
        if a1 is None or a0 is None:
            return False
        return (a1 - a0 >= 0.003 and l1 - l0 <= 0.01) or (a1 > a0 and l1 < l0)

    veredicto = {'datos': _pasa('datos'), 'nivel': _pasa('nivel'),
                 'saque': _pasa('saque')}
    ganador = ('saque' if veredicto['saque'] else
               'nivel' if veredicto['nivel'] else
               'datos' if veredicto['datos'] else 'base')
    logger.info(f"[{circuito}] medias: " +
                ' · '.join(f"{k} {v['acc']}/{v.get('ll')}" for k, v in medias.items()) +
                f" → ADOPTAR: {ganador}")
    return {'medias': medias, 'ventanas': res, 'pasa': veredicto,
            'adoptar': ganador}


if __name__ == '__main__':
    circuitos = [a for a in sys.argv[1:] if a in ('atp', 'wta')] or ['atp', 'wta']
    todo = {}
    for c in circuitos:
        try:
            r = wf_circuito(c)
            if r:
                todo[c] = r
        except Exception as e:
            logger.error(f"[{c}] falló: {type(e).__name__}: {e}", exc_info=True)
    with open(ARCHIVO, 'w', encoding='utf-8') as fh:
        json.dump(todo, fh, ensure_ascii=False, indent=1)
    print(json.dumps({k: {'medias': v['medias'], 'adoptar': v['adoptar']}
                      for k, v in todo.items()}, indent=1, ensure_ascii=False))
