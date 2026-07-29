#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v79 — A/B de vectores de features en tenis, con el ledger como juez.

Situación de partida (v78, medida sobre el ledger):

    tenis: log-loss del MODELO 0,6109   ·   del MERCADO 0,5831
    ROI negativo con TODOS los pesos entre 1,00 y 0,30
    → fuera de la Capa 1

Y sin embargo el ATP está en producción con **6 features** (`FEATURES_V30`),
porque el A/B de la v35 le dio mejor que el vector de 10, y las de nivel (v67)
y las de saque (v69) se midieron y se descartaron.

Aquellas decisiones se tomaron ANTES de que existieran dos cosas que cambian
el juicio: el encogimiento hacia el mercado (v78) y este walk-forward con
cuota real. Un vector puede empeorar la log-loss cruda y aun así producir
mejores picks tras calibrar, o al revés. Así que se vuelven a medir todas las
variantes con el mismo protocolo, el mismo estimador y los mismos pliegues.

Regla de adopción: la del proyecto — se adopta lo que mejora, medido, y se
documenta lo que no.
"""
import json
import logging
import warnings

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
log = logging.getLogger('tenis-ab')

N_FOLDS, INICIO, MIN_TEST = 5, 0.55, 400


def _modelo():
    from sklearn.calibration import CalibratedClassifierCV
    from sklearn.ensemble import RandomForestClassifier, VotingClassifier
    from lightgbm import LGBMClassifier
    from xgboost import XGBClassifier
    vc = VotingClassifier([
        ('xgb', XGBClassifier(n_estimators=200, max_depth=4,
                              learning_rate=0.05, verbosity=0)),
        ('lgbm', LGBMClassifier(n_estimators=200, max_depth=4,
                                learning_rate=0.05, verbose=-1)),
        ('rf', RandomForestClassifier(n_estimators=200, max_depth=8,
                                      random_state=42))], voting='soft')
    return CalibratedClassifierCV(vc, method='isotonic', cv=3)


def evaluar(circuito, nombre_vector, features, df, eng):
    from sklearn.preprocessing import StandardScaler
    X, y, fechas, odds, _ = eng._dataset(df, features)
    X = np.asarray(X, float)
    y = np.asarray(y).astype(int)
    fechas = pd.Series(pd.to_datetime(fechas)).reset_index(drop=True)
    odds = np.asarray(odds, float)
    n = len(X)
    if n < 2000:
        return None
    bordes = np.linspace(int(n * INICIO), n, N_FOLDS + 1).astype(int)
    P, Y, O1, O2 = [], [], [], []
    for k in range(N_FOLDS):
        ini, fin = bordes[k], bordes[k + 1]
        if fin - ini < MIN_TEST:
            continue
        corte = fechas.iloc[ini:fin].min()
        tr = np.arange(ini)[fechas.iloc[:ini].values < corte]
        if len(tr) < 1000:
            continue
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            sc = StandardScaler().fit(X[tr])
            m = _modelo().fit(sc.transform(X[tr]), y[tr])
            i1 = list(m.classes_).index(1)
            pr = m.predict_proba(sc.transform(X[ini:fin]))[:, i1]
        P.extend(pr); Y.extend(y[ini:fin])
        O1.extend(odds[ini:fin, 0]); O2.extend(odds[ini:fin, 1])

    P, Y = np.array(P), np.array(Y)
    O1, O2 = np.array(O1), np.array(O2)
    ok = np.isfinite(O1) & np.isfinite(O2) & (O1 > 1) & (O2 > 1)
    ll = lambda p, yy: float(-(yy * np.log(p.clip(1e-6, 1 - 1e-6)) +
                               (1 - yy) * np.log((1 - p).clip(1e-6, 1 - 1e-6))).mean())
    res = {'circuito': circuito, 'vector': nombre_vector,
           'n_features': len(features), 'n': int(len(P)),
           'log_loss': round(ll(P, Y), 4),
           'precision': round(float(((P >= .5).astype(int) == Y).mean()), 4)}
    if ok.sum() > 100:
        ih, ia = 1 / O1[ok], 1 / O2[ok]
        pmkt = ih / (ih + ia)
        res.update({
            'n_con_cuota': int(ok.sum()),
            'log_loss_mercado': round(ll(pmkt, Y[ok]), 4),
            'log_loss_con_cuota': round(ll(P[ok], Y[ok]), 4),
            'precision_mercado': round(
                float(((pmkt >= .5).astype(int) == Y[ok]).mean()), 4),
            'ratio_dispersion': round(float(P[ok].std() / max(pmkt.std(), 1e-9)), 3),
        })
    log.info(f"{circuito}/{nombre_vector} ({len(features)} feat): "
             f"n={res['n']} ll={res['log_loss']} acc={res['precision']}")
    return res


def main():
    from engines.tennis_engine import (TennisEngine, FEATURES_V30, FEATURES_V35,
                                       FEATURES_V67, FEATURES_SAQUE,
                                       FEATURES_V69_ATP, FEATURES_V69_WTA)

    variantes = {
        'V30 (6, ATP en producción)': FEATURES_V30,
        'V35 (10, WTA en producción)': FEATURES_V35,
        'V67 (13, con nivel)': FEATURES_V67,
        'V69-ATP (V30+saque)': FEATURES_V69_ATP,
        'V69-WTA (V35+saque)': FEATURES_V69_WTA,
    }
    salida = []
    for circuito in ('atp', 'wta'):
        eng = TennisEngine(circuito)
        df = eng.cargar_datos_historicos()
        log.info(f'--- {circuito.upper()}: {len(df)} partidos en el histórico ---')
        actual = list(eng.features)
        for nombre, feats in variantes.items():
            try:
                faltan = [f for f in feats if f not in df.columns
                          and f not in ('H2H',)]
                r = evaluar(circuito, nombre, feats, df, eng)
                if r:
                    r['es_produccion'] = (list(feats) == actual)
                    salida.append(r)
            except Exception as e:
                log.warning(f'{circuito}/{nombre}: {type(e).__name__}: {e}')

    print('\n' + '=' * 96)
    print(f"{'circuito':9s} {'vector':30s} {'n':>7} {'log-loss':>9} "
          f"{'precisión':>10} {'ll mercado':>11} {'ratio':>7}  prod")
    print('=' * 96)
    for r in salida:
        print(f"{r['circuito'].upper():9s} {r['vector']:30s} {r['n']:7d} "
              f"{r['log_loss']:9.4f} {r['precision']:10.4f} "
              f"{r.get('log_loss_mercado', float('nan')):11.4f} "
              f"{r.get('ratio_dispersion', float('nan')):7.3f}"
              f"  {'<- actual' if r['es_produccion'] else ''}")
    print('=' * 96)

    for circuito in ('atp', 'wta'):
        rs = [r for r in salida if r['circuito'] == circuito]
        if not rs:
            continue
        prod = next((r for r in rs if r['es_produccion']), None)
        mejor = min(rs, key=lambda r: r['log_loss'])
        if prod and mejor['vector'] != prod['vector']:
            d = prod['log_loss'] - mejor['log_loss']
            da = mejor['precision'] - prod['precision']
            print(f"\n{circuito.upper()}: mejor = «{mejor['vector']}» "
                  f"(log-loss {d:+.4f}, precisión {da*100:+.2f} pp frente al actual)")
            print(f"   VEREDICTO: "
                  f"{'ADOPTAR' if (d > 0.001 and da > 0) else 'RECHAZAR (no mejora las dos)'}")
        elif prod:
            print(f"\n{circuito.upper()}: el vector de producción sigue siendo "
                  f"el mejor. Se mantiene.")
    json.dump(salida, open('_v79_tenis_features.json', 'w', encoding='utf-8'),
              indent=1, ensure_ascii=False)


if __name__ == '__main__':
    main()
