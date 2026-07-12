#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Cuotas 1X2 de apertura históricas (The Odds API) -> odds_historicas.csv.

Uso EXCLUSIVO en entrenamiento/backtesting: las probabilidades implícitas del
mercado son una feature muy informativa para el 1X2 histórico, pero NO están
disponibles para partidos futuros, así que la inferencia en vivo nunca las
usa y la interfaz no muestra campos de cuotas.

Requiere la variable de entorno ODDS_API_KEY (the-odds-api.com, capa
gratuita: 500 créditos/mes). Sin clave, o si la API falla, el script termina
sin error y el entrenamiento continúa sin estas features (degradación limpia
documentada en la especificación).

Salida: odds_historicas.csv con columnas
    MATCH_ID, odd_home, odd_draw, odd_away
Ejecución recomendada: semanal.
"""

import datetime
import json
import logging
import os

import numpy as np
import pandas as pd
import requests

from config import NAME_EN_TO_FIFA

logger = logging.getLogger(__name__)

ODDS_FILE = 'odds_historicas.csv'
DEPORTE = 'soccer_fifa_world_cup'   # y amistosos/eliminatorias si el plan los incluye
BASE = 'https://api.the-odds-api.com/v4'


def _clave() -> str:
    return os.getenv('ODDS_API_KEY', '')


def _a_match_id(fecha: pd.Timestamp, home: str, away: str) -> str:
    h = NAME_EN_TO_FIFA.get(home, home).replace(' ', '-')
    a = NAME_EN_TO_FIFA.get(away, away).replace(' ', '-')
    return f"{fecha.strftime('%Y%m%d')}_{h}_{a}"


def descargar_cuotas_historicas(dias_atras: int = 365) -> pd.DataFrame:
    """
    Descarga cuotas de apertura de partidos YA DISPUTADOS (endpoint
    historical, requiere plan con acceso histórico; la capa gratuita solo
    expone eventos próximos, en cuyo caso se registran esos y se van
    acumulando semana a semana en el CSV).
    """
    clave = _clave()
    if not clave:
        logger.info("ODDS_API_KEY no configurada: se omiten las cuotas de apertura "
                    "(el modelo se entrena sin esta feature, como prevé la especificación).")
        return pd.DataFrame()

    filas = []
    try:
        r = requests.get(f"{BASE}/sports/{DEPORTE}/odds",
                         params={'apiKey': clave, 'regions': 'eu',
                                 'markets': 'h2h', 'oddsFormat': 'decimal'},
                         timeout=30)
        r.raise_for_status()
        for ev in r.json():
            fecha = pd.to_datetime(ev['commence_time']).tz_localize(None)
            casas = ev.get('bookmakers', [])
            if not casas:
                continue
            mercado = next((m for m in casas[0].get('markets', []) if m['key'] == 'h2h'), None)
            if not mercado:
                continue
            cuotas = {o['name']: o['price'] for o in mercado['outcomes']}
            odd_h = cuotas.get(ev['home_team'])
            odd_a = cuotas.get(ev['away_team'])
            odd_d = cuotas.get('Draw')
            if odd_h and odd_a and odd_d:
                filas.append({'MATCH_ID': _a_match_id(fecha, ev['home_team'], ev['away_team']),
                              'odd_home': float(odd_h), 'odd_draw': float(odd_d),
                              'odd_away': float(odd_a)})
        logger.info(f"The Odds API: {len(filas)} eventos con cuotas 1X2.")
    except Exception as e:
        logger.warning(f"The Odds API no disponible ({e}): se omiten las cuotas.")
        return pd.DataFrame()
    return pd.DataFrame(filas)


def actualizar_odds():
    """Acumula las cuotas nuevas en odds_historicas.csv (dedupe por MATCH_ID)."""
    nuevas = descargar_cuotas_historicas()
    if nuevas.empty:
        return
    if os.path.exists(ODDS_FILE):
        previas = pd.read_csv(ODDS_FILE)
        completas = pd.concat([previas, nuevas], ignore_index=True)
        completas = completas.drop_duplicates(subset='MATCH_ID', keep='first')
    else:
        completas = nuevas
    completas.to_csv(ODDS_FILE, index=False)
    logger.info(f"{ODDS_FILE}: {len(completas)} partidos con cuotas de apertura acumuladas.")
    # Snapshot ACTUAL para el parlay (v13): cuotas vigentes de eventos próximos
    with open('odds_actuales.json', 'w', encoding='utf-8') as f:
        json.dump({'actualizado': datetime.date.today().isoformat(),
                   'cuotas': nuevas.set_index('MATCH_ID').to_dict('index')}, f)


def cargar_features_cuotas(match_ids) -> pd.DataFrame:
    """
    Features de cuotas para el ENTRENAMIENTO: probabilidades implícitas
    normalizadas (sin margen) y overround de la casa. NaN donde no hay cuota.
        PROB_IMP_HOME, PROB_IMP_DRAW, PROB_IMP_AWAY, OVERROUND
    """
    columnas = ['PROB_IMP_HOME', 'PROB_IMP_DRAW', 'PROB_IMP_AWAY', 'OVERROUND']
    base = pd.DataFrame(index=range(len(match_ids)), columns=columnas, dtype=float)
    if not os.path.exists(ODDS_FILE):
        return base
    odds = pd.read_csv(ODDS_FILE).set_index('MATCH_ID')
    for i, mid in enumerate(match_ids):
        if mid in odds.index:
            fila = odds.loc[mid]
            inv = np.array([1 / fila['odd_home'], 1 / fila['odd_draw'], 1 / fila['odd_away']])
            base.iloc[i] = list(inv / inv.sum()) + [float(inv.sum() - 1)]
    return base


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    actualizar_odds()
