#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v79 — ¿La mejora del vector de tenis se distingue del ruido?

El A/B de `_v79_tenis_features.py` dio ganancias reales pero diminutas:

    ATP  V30 (producción) 0,6228  ->  V69-WTA 0,6217   Δ = +0,0011
    WTA  V35 (producción) 0,6289  ->  V67     0,6279   Δ = +0,0010

Ese script imprimió «ADOPTAR» con una regla que yo mismo fijé a ojo
(`Δ > 0,001`), y las dos ganancias caen justo encima del umbral. Adoptar por
eso sería exactamente el error que el proyecto ya evitó en la v33 (ELO
ataque/defensa) y en la v35 (CDI en UECL): quedarse con el mejor de VARIAS
variantes probadas y confundir el máximo del ruido con señal. Se compararon 5
vectores × 2 circuitos = 10 combinaciones.

Este script mide lo que hay que medir: un **bootstrap pareado** sobre la
diferencia de log-loss partido a partido. Pareado porque los dos vectores
predicen LOS MISMOS partidos, así que la varianza compartida se cancela y el
contraste es mucho más sensible que comparar dos medias sueltas.

Solo se reentrenan las 4 configuraciones necesarias (producción y mejor
candidato de cada circuito), no las 10.
"""
import json
import logging
import os
import sys
import warnings

import numpy as np
import pandas as pd

# La consola de Windows es cp1252 y no sabe escribir «Δ». Ya tumbó una vez
# este análisis DESPUÉS de 50 minutos de entrenamiento, con los resultados ya
# calculados y perdidos por un carácter del `print`. Se fuerza UTF-8.
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
log = logging.getLogger('tenis-sig')

CACHE = '_v79_tenis_predicciones.npz'

N_FOLDS, INICIO, MIN_TEST = 5, 0.55, 400
N_BOOT = 5000


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


def predicciones(eng, df, features):
    """Devuelve (p, y) fuera de muestra con el walk-forward de producción."""
    from sklearn.preprocessing import StandardScaler
    X, y, fechas, odds, _ = eng._dataset(df, features)
    X = np.asarray(X, float)
    y = np.asarray(y).astype(int)
    fechas = pd.Series(pd.to_datetime(fechas)).reset_index(drop=True)
    odds = np.asarray(odds, float)
    n = len(X)
    bordes = np.linspace(int(n * INICIO), n, N_FOLDS + 1).astype(int)
    P, Y, O = [], [], []
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
        P.extend(pr); Y.extend(y[ini:fin]); O.extend(odds[ini:fin, 0])
    return np.array(P), np.array(Y), np.array(O)


def _ll_por_fila(p, y):
    p = p.clip(1e-6, 1 - 1e-6)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


def main():
    from engines.tennis_engine import (TennisEngine, FEATURES_V35,
                                       FEATURES_V67, FEATURES_V69_WTA)

    # (circuito, vector de producción, mejor candidato del A/B)
    casos = [
        ('atp', 'V30 (producción)', None, 'V69-WTA (V35+saque)', FEATURES_V69_WTA),
        ('wta', 'V35 (producción)', FEATURES_V35, 'V67 (con nivel)', FEATURES_V67),
    ]

    # Las predicciones se cachean en disco. Entrenar las 4 configuraciones
    # cuesta ~50 minutos y el análisis posterior es instantáneo: no tiene
    # sentido volver a entrenar para cambiar un percentil o arreglar un print.
    cache = dict(np.load(CACHE)) if os.path.exists(CACHE) else {}

    salida = []
    for circuito, n_prod, f_prod, n_cand, f_cand in casos:
        eng = TennisEngine(circuito)
        if f_prod is None:
            f_prod = list(eng.features)
        k_prod, k_cand = f'{circuito}_prod', f'{circuito}_cand'
        k_y = f'{circuito}_y'
        if k_prod in cache and k_cand in cache and k_y in cache:
            log.info(f'--- {circuito.upper()} (desde caché) ---')
            p_prod, p_cand = cache[k_prod], cache[k_cand]
            y1 = y2 = cache[k_y]
        else:
            df = eng.cargar_datos_historicos()
            log.info(f'--- {circuito.upper()} ---')
            p_prod, y1, _ = predicciones(eng, df, f_prod)
            p_cand, y2, _ = predicciones(eng, df, f_cand)
            cache[k_prod], cache[k_cand], cache[k_y] = p_prod, p_cand, y1
            np.savez_compressed(CACHE, **cache)
            log.info(f'[caché] predicciones de {circuito} guardadas')
        n = min(len(p_prod), len(p_cand))
        p_prod, p_cand, y = p_prod[:n], p_cand[:n], y1[:n]
        if not np.array_equal(y1[:n], y2[:n]):
            log.warning(f'{circuito}: las etiquetas no coinciden; se omite')
            continue

        ll1, ll2 = _ll_por_fila(p_prod, y), _ll_por_fila(p_cand, y)
        d = ll1 - ll2                       # positivo = el candidato es mejor
        media = float(d.mean())

        rng = np.random.default_rng(42)
        idx = rng.integers(0, n, size=(N_BOOT, n))
        muestras = d[idx].mean(axis=1)
        p5, p95 = np.percentile(muestras, [5, 95])
        frac_pos = float((muestras > 0).mean())

        acc1 = float(((p_prod >= .5).astype(int) == y).mean())
        acc2 = float(((p_cand >= .5).astype(int) == y).mean())

        # Corrección por comparaciones múltiples: se probaron 5 vectores por
        # circuito y nos quedamos con el mejor, así que el umbral honesto es
        # más exigente que el 95 % de una comparación única (Bonferroni: 1 %).
        p99_bajo = float(np.percentile(muestras, 1))

        print(f'\n{"="*70}')
        print(f'{circuito.upper()}   n = {n} partidos pareados')
        print(f'{"="*70}')
        print(f'  {n_prod:24s} log-loss {ll1.mean():.4f}  precisión {acc1:.4f}')
        print(f'  {n_cand:24s} log-loss {ll2.mean():.4f}  precisión {acc2:.4f}')
        print(f'\n  Δ log-loss (a favor del candidato): {media:+.5f}')
        print(f'  IC 90 % bootstrap pareado         : [{p5:+.5f}, {p95:+.5f}]')
        print(f'  fracción de remuestreos con Δ > 0 : {frac_pos:.1%}')
        print(f'  percentil 1 (Bonferroni, 5 vectores): {p99_bajo:+.5f}')
        veredicto = ('ADOPTAR' if p99_bajo > 0 else
                     'NO ADOPTAR — indistinguible del ruido tras corregir '
                     'por comparaciones múltiples')
        print(f'\n  VEREDICTO: {veredicto}')
        salida.append({'circuito': circuito, 'n': int(n),
                       'll_produccion': round(float(ll1.mean()), 5),
                       'll_candidato': round(float(ll2.mean()), 5),
                       'precision_produccion': round(acc1, 4),
                       'precision_candidato': round(acc2, 4),
                       'delta_medio': round(media, 5),
                       'ic90': [round(float(p5), 5), round(float(p95), 5)],
                       'frac_positiva': round(frac_pos, 4),
                       'p1_bonferroni': round(p99_bajo, 5),
                       'veredicto': veredicto})

    json.dump(salida, open('_v79_tenis_significancia.json', 'w',
                           encoding='utf-8'), indent=1, ensure_ascii=False)


if __name__ == '__main__':
    main()
