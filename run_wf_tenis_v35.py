#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Walk-forward del modelo de tenis v35 (spec §1.5) — ATP y WTA por separado.

Variantes con las MISMAS ventanas (una por temporada, últimas 5):
  v30 — features de producción v30 (ELO superficie/global, ranking, forma,
        % victorias en superficie 12 m, H2H)
  v35 — v30 + puntos de ranking + fatiga (días de descanso, partidos en 14 d,
        horas en pista en 7 d) + ELO de pista INDOOR como superficie propia

Líneas base de la misma ventana: favorito por RANKING y favorito por CUOTA
de cierre (mercado). Regla de oro: ≥ +0.3 pp sin empeorar el log-loss > 0.01.

Uso: python run_wf_tenis_v35.py [atp|wta ...]   → resultados_tenis_v35.json
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

from engines.tennis_engine import FEATURES, FEATURES_V30, TennisEngine

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

ARCHIVO = 'resultados_tenis_v35.json'
VARIANTES = {'v30': FEATURES_V30, 'v35': FEATURES}
MIN_VENTANA = 300


def _modelo():
    vc = VotingClassifier([
        ('xgb', XGBClassifier(n_estimators=200, max_depth=4,
                              learning_rate=0.05, verbosity=0)),
        ('lgbm', LGBMClassifier(n_estimators=200, max_depth=4,
                                learning_rate=0.05, verbose=-1)),
        ('rf', RandomForestClassifier(n_estimators=200, max_depth=8,
                                      random_state=42))], voting='soft')
    return CalibratedClassifierCV(vc, method='isotonic', cv=3)


def wf_circuito(circuito: str) -> dict:
    eng = TennisEngine(circuito)
    df = eng.cargar_datos_historicos()
    datos = {v: eng._dataset(df, cols) for v, cols in VARIANTES.items()}
    _, y, fechas, odds, _ = datos['v35']
    # el ranking es la 3ª feature de ambas variantes (DIFF_RANK_LOG)
    rank_diff = datos['v35'][0][:, FEATURES.index('DIFF_RANK_LOG')]

    ultimo = fechas.max()
    cortes = [ultimo - pd.DateOffset(years=k) for k in range(5, 0, -1)]
    res = {v: [] for v in VARIANTES}
    res['ranking'], res['mercado'] = [], []
    for i, ini in enumerate(cortes):
        fin = cortes[i + 1] if i + 1 < len(cortes) else ultimo + pd.Timedelta(days=1)
        m_tr = (fechas < ini).values
        m_va = ((fechas >= ini) & (fechas < fin)).values
        if m_va.sum() < MIN_VENTANA:
            continue
        fila = {}
        for v, cols in VARIANTES.items():
            X = datos[v][0]
            sc = StandardScaler().fit(X[m_tr])
            mod = _modelo().fit(sc.transform(X[m_tr]), y[m_tr])
            p1 = mod.predict_proba(sc.transform(X[m_va]))[:, list(mod.classes_).index(1)]
            acc = float(accuracy_score(y[m_va], (p1 >= 0.5).astype(int)))
            ll = float(log_loss(y[m_va], np.column_stack([1 - p1, p1])))
            res[v].append({'ventana': str(ini.date()), 'n': int(m_va.sum()),
                           'acc': round(acc, 4), 'll': round(ll, 4)})
            fila[v] = f'{acc:.3f}/{ll:.3f}'
        acc_rank = float(accuracy_score(y[m_va], (rank_diff[m_va] > 0).astype(int)))
        res['ranking'].append({'ventana': str(ini.date()), 'acc': round(acc_rank, 4)})
        o = odds[m_va]
        mk = np.isfinite(o).all(axis=1)
        acc_mkt = (float(accuracy_score(y[m_va][mk], (o[mk][:, 0] < o[mk][:, 1]).astype(int)))
                   if mk.sum() > 50 else None)
        res['mercado'].append({'ventana': str(ini.date()),
                               'acc': round(acc_mkt, 4) if acc_mkt else None,
                               'cobertura': round(float(mk.mean()), 3)})
        logger.info(f"  [{circuito}] {ini.date()} n={m_va.sum()} :: "
                    + ' · '.join(f'{k} {v}' for k, v in fila.items())
                    + f" · ranking {acc_rank:.3f} · mercado {acc_mkt}")
    if not res['v35']:
        return {}

    def _m(v, campo='acc'):
        vals = [f[campo] for f in res[v] if f.get(campo) is not None]
        return round(float(np.mean(vals)), 4) if vals else None

    a30, l30 = _m('v30'), _m('v30', 'll')
    a35, l35 = _m('v35'), _m('v35', 'll')
    pasa = ((a35 - a30 >= 0.003 and l35 - l30 <= 0.01) or (a35 > a30 and l35 < l30))
    salida = {'media': {'v30': {'acc': a30, 'll': l30},
                        'v35': {'acc': a35, 'll': l35,
                                'pasa_regla_de_oro': bool(pasa)},
                        'ranking': {'acc': _m('ranking')},
                        'mercado': {'acc': _m('mercado')}},
              'ventanas': res, 'adoptar_v35': bool(pasa)}
    logger.info(f"[{circuito}] v30 {a30}/{l30} · v35 {a35}/{l35} · "
                f"ranking {_m('ranking')} · mercado {_m('mercado')} → "
                f"{'ADOPTADO' if pasa else 'descartado'}")
    return salida


if __name__ == '__main__':
    circuitos = [a for a in sys.argv[1:] if not a.startswith('--')] or ['atp', 'wta']
    todo = {}
    for c in circuitos:
        try:
            r = wf_circuito(c)
            if r:
                todo[c] = r
        except Exception as e:
            logger.error(f"[{c}] falló: {type(e).__name__}: {e}")
    with open(ARCHIVO, 'w', encoding='utf-8') as fh:
        json.dump(todo, fh, ensure_ascii=False, indent=1)
    print(json.dumps({k: v['media'] for k, v in todo.items()}, indent=1))
