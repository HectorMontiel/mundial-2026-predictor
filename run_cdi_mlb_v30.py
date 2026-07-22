#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A/B walk-forward del CDI en MLB (v30 §2/§3.3): mismo modelo con y sin la
feature CDI del visitante (husos cruzados desde su partido anterior)."""
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

import cdi as cdi_mod
from engines.mlb_engine import MLBEngine

logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
logger = logging.getLogger(__name__)


def _ens():
    vc = VotingClassifier([
        ('xgb', XGBClassifier(n_estimators=200, max_depth=4, learning_rate=0.05, verbosity=0)),
        ('lgbm', LGBMClassifier(n_estimators=200, max_depth=4, learning_rate=0.05, verbose=-1)),
        ('rf', RandomForestClassifier(n_estimators=200, max_depth=8, random_state=42))], voting='soft')
    return CalibratedClassifierCV(vc, method='isotonic', cv=3)


def main():
    df = pd.read_csv('historico_mlb.csv', parse_dates=['date'])
    X, y, tot, fechas, _ = MLBEngine._dataset(df)
    # CDI alineado con las MISMAS filas utilizables de _dataset
    df = df.sort_values('date').reset_index(drop=True)
    ult_sede = {}
    ult_fecha = {}
    rs_count = {}
    cdis = []
    idx_util = 0
    for r in df.itertuples(index=False):
        h, a = r.home_team, r.away_team
        usable = all(rs_count.get(t, 0) >= 5 for t in (h, a))
        if usable:
            prev = ult_sede.get(a)
            reciente = (a in ult_fecha and (r.date - ult_fecha[a]).days <= 7)
            tz_prev = cdi_mod.TZ_MLB.get(prev) if (prev and reciente) else None
            cdis.append(cdi_mod.cdi_desde_offsets(tz_prev, cdi_mod.TZ_MLB.get(h, -5)))
        for t in (h, a):
            rs_count[t] = rs_count.get(t, 0) + 1
        ult_sede[h] = ult_sede[a] = h
        ult_fecha[h] = ult_fecha[a] = r.date
    cdi_arr = np.array(cdis).reshape(-1, 1)
    assert len(cdi_arr) == len(X), f"{len(cdi_arr)} != {len(X)}"

    inicio = fechas.quantile(0.60).normalize().replace(day=1)
    ventanas = pd.date_range(inicio, fechas.max(), freq='6MS')
    res = {'base': [], 'cdi': []}
    for ini in ventanas:
        fin = ini + pd.DateOffset(months=6)
        m_tr = (fechas < ini).values
        m_va = ((fechas >= ini) & (fechas < fin)).values
        if m_va.sum() < 200 or m_tr.sum() < 1000:
            continue
        for nombre, XX in (('base', X), ('cdi', np.hstack([X, cdi_arr]))):
            sc = StandardScaler().fit(XX[m_tr])
            mod = _ens().fit(sc.transform(XX[m_tr]), y[m_tr])
            p = mod.predict_proba(sc.transform(XX[m_va]))[:, list(mod.classes_).index(1)]
            acc = float(accuracy_score(y[m_va], (p >= 0.5).astype(int)))
            ll = float(log_loss(y[m_va], np.column_stack([1 - p, p]), labels=[0, 1]))
            res[nombre].append((acc, ll))
        logger.info(f"  [cdi] {ini.date()} base {res['base'][-1][0]:.4f}/{res['base'][-1][1]:.4f} "
                    f"· cdi {res['cdi'][-1][0]:.4f}/{res['cdi'][-1][1]:.4f}")
    def _m(k, i):
        return round(float(np.mean([v[i] for v in res[k]])), 4)
    salida = {'acc_base': _m('base', 0), 'll_base': _m('base', 1),
              'acc_cdi': _m('cdi', 0), 'll_cdi': _m('cdi', 1)}
    salida['adoptar'] = bool((salida['acc_cdi'] - salida['acc_base'] >= 0.003
                              and salida['ll_cdi'] - salida['ll_base'] <= 0.01)
                             or (salida['acc_cdi'] > salida['acc_base']
                                 and salida['ll_cdi'] < salida['ll_base']))
    with open('resultados_cdi_mlb_v30.json', 'w', encoding='utf-8') as f:
        json.dump(salida, f, indent=2)
    logger.info(f"[cdi] MLB base {salida['acc_base']}/{salida['ll_base']} → "
                f"cdi {salida['acc_cdi']}/{salida['ll_cdi']} · "
                f"{'ADOPTAR' if salida['adoptar'] else 'descartado'}")
    return salida


if __name__ == '__main__':
    print(json.dumps(main(), indent=2))
