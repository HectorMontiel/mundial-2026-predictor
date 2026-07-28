#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v75 — Libro mayor de predicciones fuera de muestra (`pick_ledger.csv`).

El problema que resuelve
------------------------
Para recalibrar el modelo o backtestear umbrales hace falta responder a
"¿qué habría dicho el modelo ANTES de este partido, y a qué cuota cerró?".
Hasta la v74 el proyecto no lo podía responder:

  · `roi_bets_*.json` guarda solo las apuestas que YA pasaron un filtro
    (`prob>0.70 o EV>0`) — backtestear umbrales sobre eso es circular: no se
    puede medir un umbral más bajo que el que generó los datos.
  · Guarda la probabilidad del lado elegido, pero no el VECTOR completo, así
    que tampoco se puede devigar contra el mercado ni evaluar otro lado.
  · No lleva `MATCH_ID`, así que no cruza con las cuotas de `odds_historico.db`.
  · Y sale de un ÚNICO corte 80/20 (`fechas.quantile(0.80)`), no de un
    walk-forward: 78 apuestas en Premier, 61 en League Two. Con esas muestras
    cualquier "umbral óptimo" es ruido.

Este módulo genera el sustrato que faltaba: **todas** las predicciones fuera de
muestra, sin filtrar, con vector completo, MATCH_ID y cuotas de cierre.

Cómo evita la fuga temporal
---------------------------
Walk-forward de origen móvil: el histórico se parte en `n_folds` bloques
consecutivos sobre el último `1-inicio` del calendario; para cada bloque se
entrena SOLO con lo anterior y se predice el bloque. Nunca entra en el
entrenamiento un partido posterior al que se predice.

  · El escalado (`normalizar_features`) se ajusta con el train del pliegue.
  · La imputación de cuotas ausentes usa la media del train del pliegue.
  · Las features y la familia de modelo son las MISMAS de producción, porque
    salen de `league_engine.preparar_features_extra` y
    `league_engine.familia_de_liga` (v75: extraídas para no duplicar código —
    un backtest que mide otro modelo no sirve de nada).

Salida
------
`pick_ledger.csv`, una fila por partido evaluado:
    liga, match_id, fecha, pliegue, p_home, p_draw, p_away, resultado,
    goles_local, goles_visit, cuota_home/draw/away (mercado),
    pin_home/draw/away (Pinnacle), cuota_over25/under25

Uso:
    python build_pick_ledger.py                # todas las ligas disponibles
    python build_pick_ledger.py --liga premier --folds 5
"""

import argparse
import datetime as dt
import json
import logging
import sys
import os
import warnings
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

# La consola de Windows es cp1252: sin esto, imprimir una flecha o un
# visto aborta el script DESPUÉS de haber hecho todo el trabajo.
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

logger = logging.getLogger(__name__)

SALIDA_CSV = 'pick_ledger.csv'
SALIDA_META = '_v75_pick_ledger.json'

# Fracción inicial del calendario que se reserva SIEMPRE para entrenar. Con
# 0.50 el primer pliegue ya ve la mitad del histórico (en las ligas de 5
# temporadas, ~2,5 temporadas) y quedan 5 bloques de evaluación.
INICIO_TRAIN = 0.50
N_FOLDS = 5
MIN_PARTIDOS = 300          # mismo mínimo que exige `entrenar_liga`
MIN_TEST_POR_FOLD = 30


def _ahora() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')


def ligas_objetivo(solo: Optional[str] = None) -> List[str]:
    """Ligas disponibles con CSV en disco. Sin cuotas no hay nada que medir,
    pero se incluyen igual: el ledger sirve también para calibración pura."""
    from config import LEAGUES
    claves = []
    for clave, cfg in LEAGUES.items():
        if solo and clave != solo:
            continue
        if not solo and not cfg.get('disponible'):
            continue
        if os.path.exists(f'historico_{clave}.csv'):
            claves.append(clave)
    return sorted(claves)


def _ordenar_clases(modelo, proba: np.ndarray) -> np.ndarray:
    """Reordena a [local, empate, visitante] si el estimador barajó clases
    (misma corrección que aplica `entrenar_liga`)."""
    if proba.shape[1] == 3 and list(getattr(modelo, 'classes_', [0, 1, 2])) != [0, 1, 2]:
        p = np.zeros_like(proba)
        for i, k in enumerate(modelo.classes_):
            p[:, int(k)] = proba[:, i]
        return p / p.sum(axis=1, keepdims=True)
    return proba


def ledger_liga(clave: str, n_folds: int = N_FOLDS,
                inicio: float = INICIO_TRAIN) -> pd.DataFrame:
    """Walk-forward de origen móvil sobre una liga. DataFrame vacío si no se
    puede evaluar (pocos partidos)."""
    import feature_engineering as fe
    import league_engine as le
    from train_tda_model import calcular_features_topologicas

    df = pd.read_csv(f'historico_{clave}.csv', low_memory=False)
    df['date'] = pd.to_datetime(df['date'], errors='coerce')
    df = df.dropna(subset=['date']).sort_values(['date', 'MATCH_ID'],
                                                kind='mergesort').reset_index(drop=True)

    ds = fe.construir_dataset_supervisado(df)
    X_df, y, fechas = ds['X_df'], ds['y'], ds['fechas']
    if len(X_df) < MIN_PARTIDOS:
        logger.info(f"[{clave}] solo {len(X_df)} partidos utilizables: se omite.")
        return pd.DataFrame()

    topo = calcular_features_topologicas(ds)
    fechas = pd.Series(pd.to_datetime(fechas)).reset_index(drop=True)
    # Los coeficientes del IMT compuesto (ligas con 'imt_c') se ajustan SOLO
    # con lo anterior al primer pliegue de evaluación. Producción los ajusta
    # con el 80 % inicial porque valida sobre el 20 % final; aquí el primer
    # pliegue empieza en `inicio`, así que el corte tiene que ser ese o los
    # pliegues tempranos se predecirían con coeficientes que vieron su futuro.
    corte_imt = fechas.quantile(inicio)
    X_df, cols_extra, _ = le.preparar_features_extra(clave, df, ds, X_df, corte_imt)
    X_df = X_df.reset_index(drop=True)
    ids = np.array([m[3] for m in ds['meta']])
    goles = ds['goles']

    familia = ('beta' if le.LEAGUES[clave].get('calibracion') == 'beta'
               else le.familia_de_liga(clave))

    n = len(X_df)
    orden = np.argsort(fechas.values, kind='mergesort')      # ya viene ordenado
    corte0 = int(n * inicio)
    bordes = np.linspace(corte0, n, n_folds + 1).astype(int)

    filas = []
    for k in range(n_folds):
        ini_test, fin_test = bordes[k], bordes[k + 1]
        if fin_test - ini_test < MIN_TEST_POR_FOLD:
            continue
        idx_tr = orden[:ini_test]
        idx_te = orden[ini_test:fin_test]
        # blindaje anti-fuga: ningún partido de train puede ser posterior al
        # primero de test (los empates de fecha se resuelven a favor de test)
        f_corte = fechas.iloc[idx_te].min()
        idx_tr = idx_tr[fechas.iloc[idx_tr].values < f_corte]
        if len(idx_tr) < 200:
            continue

        Xk = X_df.copy()
        if cols_extra:
            for c in cols_extra:
                if c in le.COLS_CUOTAS:
                    media = float(pd.to_numeric(Xk.iloc[idx_tr][c],
                                                errors='coerce').mean())
                    Xk[c] = Xk[c].fillna(media if np.isfinite(media) else 0.0)
                else:
                    Xk[c] = Xk[c].fillna(0.0)

        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            X_tr_n, X_te_n, _ = fe.normalizar_features(Xk.iloc[idx_tr], Xk.iloc[idx_te])
            X_tr = np.hstack([X_tr_n, topo[idx_tr]])
            X_te = np.hstack([X_te_n, topo[idx_te]])
            if familia == 'beta':
                modelo = le.ModeloBetaCalibrado()
            else:
                modelo = le.construir_modelo_familia(
                    familia, n_base=len(fe.FEATURES_MODELO), n_total=X_tr.shape[1])
            modelo.fit(X_tr, y[idx_tr])
            proba = _ordenar_clases(modelo, modelo.predict_proba(X_te))

        for j, i_glob in enumerate(idx_te):
            filas.append({
                'liga': clave, 'match_id': ids[i_glob],
                'fecha': fechas.iloc[i_glob].strftime('%Y-%m-%d'),
                'pliegue': k,
                'p_home': round(float(proba[j, 0]), 5),
                'p_draw': round(float(proba[j, 1]), 5),
                'p_away': round(float(proba[j, 2]), 5),
                'resultado': int(y[i_glob]),
                'goles_local': int(goles[i_glob, 0]),
                'goles_visit': int(goles[i_glob, 1]),
            })

    if not filas:
        return pd.DataFrame()
    out = pd.DataFrame(filas)
    logger.info(f"[{clave}] {len(out)} predicciones fuera de muestra en "
                f"{out['pliegue'].nunique()} pliegues "
                f"({out['fecha'].min()} → {out['fecha'].max()}), familia={familia}.")
    return out


def adjuntar_cuotas(ledger: pd.DataFrame) -> pd.DataFrame:
    """Cruza el ledger con las cuotas de cierre de `odds_historico.db`."""
    import odds_store
    con = odds_store.conectar()
    cur = con.execute(
        "SELECT match_id, bookmaker, odds_home, odds_draw, odds_away, "
        "       odds_over25, odds_under25 "
        "FROM historical_odds WHERE fase = 'cierre'")
    mercado, pin = {}, {}
    for mid, casa, oh, od, oa, oo, ou in cur.fetchall():
        destino = pin if casa == 'pinnacle' else mercado
        destino[mid] = (oh, od, oa, oo, ou)
    con.close()

    def _col(mapa, pos):
        return ledger['match_id'].map(lambda m: (mapa.get(m) or (None,) * 5)[pos])

    ledger = ledger.copy()
    for nombre, pos in (('cuota_home', 0), ('cuota_draw', 1), ('cuota_away', 2),
                        ('cuota_over25', 3), ('cuota_under25', 4)):
        ledger[nombre] = _col(mercado, pos)
    for nombre, pos in (('pin_home', 0), ('pin_draw', 1), ('pin_away', 2)):
        ledger[nombre] = _col(pin, pos)
    return ledger


def construir(solo: Optional[str] = None, n_folds: int = N_FOLDS) -> pd.DataFrame:
    claves = ligas_objetivo(solo)
    logger.info(f"Construyendo ledger de {len(claves)} ligas "
                f"({n_folds} pliegues de origen móvil)…")
    partes = []
    fallos = {}
    for clave in claves:
        try:
            d = ledger_liga(clave, n_folds=n_folds)
            if not d.empty:
                partes.append(d)
        except Exception as e:
            fallos[clave] = f"{type(e).__name__}: {e}"
            logger.warning(f"[{clave}] no evaluable: {e}")
    if not partes:
        raise RuntimeError('ninguna liga produjo predicciones')
    ledger = adjuntar_cuotas(pd.concat(partes, ignore_index=True))
    ledger.to_csv(SALIDA_CSV, index=False)

    con_cuota = int(ledger['cuota_home'].notna().sum())
    con_pin = int(ledger['pin_home'].notna().sum())
    meta = {
        'generado': _ahora(), 'n_folds': n_folds, 'inicio_train': INICIO_TRAIN,
        'filas': int(len(ledger)), 'ligas': int(ledger['liga'].nunique()),
        'con_cuota_mercado': con_cuota, 'con_cuota_pinnacle': con_pin,
        'rango': [ledger['fecha'].min(), ledger['fecha'].max()],
        'fallos': fallos,
        'por_liga': {k: {'n': int(v), 'con_cuota': int(
            ledger.loc[ledger['liga'] == k, 'cuota_home'].notna().sum())}
            for k, v in ledger['liga'].value_counts().items()},
    }
    with open(SALIDA_META, 'w', encoding='utf-8') as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    logger.info(f"✅ {len(ledger)} predicciones OOS de {meta['ligas']} ligas; "
                f"{con_cuota} con cuota de mercado, {con_pin} con Pinnacle.")
    return ledger


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    ap = argparse.ArgumentParser()
    ap.add_argument('--liga')
    ap.add_argument('--folds', type=int, default=N_FOLDS)
    args = ap.parse_args()
    construir(args.liga, args.folds)
