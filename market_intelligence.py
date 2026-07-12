#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Inteligencia de mercado (Mejora 4, v12) — EXPERIMENTAL.

Recoge las probabilidades implícitas de Polymarket (API pública Gamma) para
mercados del Mundial, las compara con el modelo propio y genera señales:

  * Divergencia modelo vs mercado (>15 % => alerta de posible información
    asimétrica o valor).
  * Movimiento de la probabilidad entre snapshots (proxy del flujo de dinero).
  * Cambio brusco de liquidez (>20 % entre snapshots => alerta).
  * Indicador de riesgo (bajo/medio/alto) agregando las señales anteriores.

Los datos NUNCA entran como features del 1X2 (sería fuga de información en el
backtesting); alimentan únicamente el panel informativo de la UI.

Alcance honesto: el análisis de wallets on-chain (Polygon) requiere un nodo
RPC/indexador propio; esta versión aproxima el flujo con los cambios de
volumen y liquidez que expone la propia API. Etiquetado como experimental.

Ejecución: cada 15 minutos durante el Mundial ->
  schtasks /create /tn "MarketIntel" /tr "...market_intelligence.py" /sc minute /mo 15
Salida: market_data.json (histórico de snapshots + señales actuales).
"""

import datetime
import json
import logging
import os
from typing import Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

MARKET_FILE = 'market_data.json'
GAMMA_URL = 'https://gamma-api.polymarket.com/markets'
UMBRAL_DIVERGENCIA = 0.15
UMBRAL_LIQUIDEZ = 0.20
MAX_SNAPSHOTS = 200


def _cargar() -> Dict:
    if os.path.exists(MARKET_FILE):
        try:
            with open(MARKET_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {'snapshots': [], 'senales': [], 'actualizado': None, 'disponible': False}


def obtener_mercados_polymarket(termino: str = 'World Cup', limite: int = 40) -> List[Dict]:
    """Mercados abiertos de Polymarket relacionados con el Mundial."""
    r = requests.get(GAMMA_URL, params={'closed': 'false', 'limit': limite,
                                        'order': 'volume', 'ascending': 'false'},
                     timeout=20)
    r.raise_for_status()
    mercados = []
    for m in r.json():
        pregunta = str(m.get('question', ''))
        if termino.lower() not in pregunta.lower() and 'world cup' not in pregunta.lower():
            continue
        try:
            precios = json.loads(m.get('outcomePrices', '[]'))
            salidas = json.loads(m.get('outcomes', '[]'))
        except Exception:
            precios, salidas = [], []
        mercados.append({
            'pregunta': pregunta,
            'salidas': salidas,
            'precios': [float(p) for p in precios] if precios else [],
            'volumen': float(m.get('volume', 0) or 0),
            'liquidez': float(m.get('liquidity', 0) or 0),
        })
    return mercados


def _senales(snapshots: List[Dict], engine=None) -> List[Dict]:
    """Genera alertas comparando el snapshot actual con los anteriores y el modelo."""
    if not snapshots:
        return []
    actual = snapshots[-1]
    previo = snapshots[-2] if len(snapshots) > 1 else None
    senales = []

    for m in actual['mercados']:
        alertas, riesgo = [], 0
        if previo:
            m_prev = next((x for x in previo['mercados'] if x['pregunta'] == m['pregunta']), None)
            if m_prev:
                if m_prev['liquidez'] > 0:
                    delta_liq = (m['liquidez'] - m_prev['liquidez']) / m_prev['liquidez']
                    if abs(delta_liq) > UMBRAL_LIQUIDEZ:
                        alertas.append(f"Liquidez {'+' if delta_liq > 0 else ''}{delta_liq*100:.0f} % desde el último snapshot")
                        riesgo += 1
                if m['precios'] and m_prev['precios']:
                    delta_p = m['precios'][0] - m_prev['precios'][0]
                    if abs(delta_p) > 0.05:
                        alertas.append(f"La probabilidad se movió {delta_p*100:+.0f} pts")
                        riesgo += 1

        # Divergencia contra el modelo propio (si el engine puede mapear equipos)
        if engine is not None and m['precios']:
            equipos = engine.detectar_equipos(m['pregunta'])
            if len(equipos) >= 2:
                pred = engine.predecir(equipos[0], equipos[1])
                if 'error' not in pred:
                    p_modelo = pred['prediction']['probabilities']['home']
                    div = m['precios'][0] - p_modelo
                    if abs(div) > UMBRAL_DIVERGENCIA:
                        alertas.append(
                            f"Divergencia modelo vs mercado: {div*100:+.0f} pts "
                            f"(modelo {p_modelo*100:.0f} % vs mercado {m['precios'][0]*100:.0f} %)")
                        riesgo += 2

        nivel = 'alto' if riesgo >= 3 else ('medio' if riesgo >= 1 else 'bajo')
        senales.append({'pregunta': m['pregunta'], 'precios': m['precios'],
                        'salidas': m['salidas'], 'volumen': m['volumen'],
                        'liquidez': m['liquidez'], 'alertas': alertas,
                        'riesgo_manipulacion': nivel})
    return senales


def actualizar(engine=None) -> Dict:
    """Toma un snapshot de Polymarket y regenera las señales. Degrada limpio."""
    datos = _cargar()
    try:
        mercados = obtener_mercados_polymarket()
        datos['snapshots'].append({
            'timestamp': datetime.datetime.now().isoformat(timespec='minutes'),
            'mercados': mercados,
        })
        datos['snapshots'] = datos['snapshots'][-MAX_SNAPSHOTS:]
        datos['senales'] = _senales(datos['snapshots'], engine)
        datos['disponible'] = len(mercados) > 0
        datos['actualizado'] = datetime.datetime.now().isoformat(timespec='minutes')
        logger.info(f"Polymarket: {len(mercados)} mercados del Mundial capturados.")
    except Exception as e:
        datos['disponible'] = False
        datos['error'] = f"{type(e).__name__}: {e}"
        logger.warning(f"Polymarket no disponible ({e}): el panel mostrará 'no disponible'.")
    with open(MARKET_FILE, 'w', encoding='utf-8') as f:
        json.dump(datos, f, ensure_ascii=False)
    return datos


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    actualizar()
