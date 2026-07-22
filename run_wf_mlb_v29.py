#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Walk-forward del motor MLB (v29 §4.5). Ventanas de 6 meses (temporadas MLB)
sobre el último ~40 % del histórico; entrenamiento expansivo por ventana
(scaler reajustado — sin fuga). Base = favorito por ELO (no hay cuotas MLB
históricas gratuitas; degradación honesta documentada).
"""

import json
import logging
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

from engines.mlb_engine import MLBEngine

logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
logger = logging.getLogger(__name__)


def _ens():
    vc = VotingClassifier([
        ('xgb', XGBClassifier(n_estimators=200, max_depth=4, learning_rate=0.05, verbosity=0)),
        ('lgbm', LGBMClassifier(n_estimators=200, max_depth=4, learning_rate=0.05, verbose=-1)),
        ('rf', RandomForestClassifier(n_estimators=200, max_depth=8, random_state=42))],
        voting='soft')
    return CalibratedClassifierCV(vc, method='isotonic', cv=3)


def main():
    df = pd.read_csv('historico_mlb.csv', parse_dates=['date'])
    X, y, tot, fechas, _ = MLBEngine._dataset(df)
    inicio = fechas.quantile(0.60).normalize().replace(day=1)
    ventanas = pd.date_range(inicio, fechas.max(), freq='6MS')
    filas = []
    for ini in ventanas:
        fin = ini + pd.DateOffset(months=6)
        m_tr = (fechas < ini).values
        m_va = ((fechas >= ini) & (fechas < fin)).values
        if m_va.sum() < 200 or m_tr.sum() < 1000:
            continue
        sc = StandardScaler().fit(X[m_tr])
        modelo = _ens().fit(sc.transform(X[m_tr]), y[m_tr])
        proba = modelo.predict_proba(sc.transform(X[m_va]))[:, list(modelo.classes_).index(1)]
        acc = float(accuracy_score(y[m_va], (proba >= 0.5).astype(int)))
        ll = float(log_loss(y[m_va], np.column_stack([1 - proba, proba]), labels=[0, 1]))
        base = float(accuracy_score(y[m_va], (X[m_va][:, 0] > 0).astype(int)))
        filas.append({'ventana': str(ini.date()), 'n': int(m_va.sum()),
                      'acc': round(acc, 4), 'll': round(ll, 4),
                      'acc_elo': round(base, 4)})
        logger.info(f"  [mlb] {ini.date()} n={m_va.sum()} acc={acc:.4f} "
                    f"ll={ll:.4f} (ELO {base:.4f})")
    if not filas:
        return {}
    resumen = {'ventanas': filas,
               'precision_media': round(float(np.mean([f['acc'] for f in filas])), 4),
               'log_loss_medio': round(float(np.mean([f['ll'] for f in filas])), 4),
               'precision_elo_media': round(float(np.mean([f['acc_elo'] for f in filas])), 4)}
    resumen['supera_elo'] = resumen['precision_media'] > resumen['precision_elo_media']
    with open('resultados_mlb_v29.json', 'w', encoding='utf-8') as f:
        json.dump(resumen, f, ensure_ascii=False, indent=2)
    logger.info(f"[mlb] WF: {resumen['precision_media']} vs ELO "
                f"{resumen['precision_elo_media']} · ll {resumen['log_loss_medio']}")
    return resumen


if __name__ == '__main__':
    print(json.dumps({k: v for k, v in main().items() if k != 'ventanas'}, indent=2))
