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
RISK_FILE = 'risk_flags.json'
GAMMA_URL = 'https://gamma-api.polymarket.com/markets'
# Riesgo compuesto (v13): 🔴 div>20pp Y liquidez>30% · 🟡 div>15pp O liq>20%
UMBRAL_DIVERGENCIA = 0.15
UMBRAL_DIVERGENCIA_ALTA = 0.20
UMBRAL_LIQUIDEZ = 0.20
UMBRAL_LIQUIDEZ_ALTA = 0.30
MAX_SNAPSHOTS = 200
# Frecuencia recomendada en horas previas a partido: cada 10 minutos
#   schtasks /create /tn "MarketIntel" /tr "...market_intelligence.py" /sc minute /mo 10
# Limitación documentada: el rastreo de wallets (Polygonscan) requiere clave
# y un indexador propio; el flujo se aproxima con volumen/liquidez de la API.


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
        alertas = []
        div_abs, liq_abs = 0.0, 0.0
        equipos_detectados = []
        if previo:
            m_prev = next((x for x in previo['mercados'] if x['pregunta'] == m['pregunta']), None)
            if m_prev:
                if m_prev['liquidez'] > 0:
                    liq_abs = abs((m['liquidez'] - m_prev['liquidez']) / m_prev['liquidez'])
                    if liq_abs > UMBRAL_LIQUIDEZ:
                        alertas.append(f"Liquidez {'+' if m['liquidez'] > m_prev['liquidez'] else '-'}"
                                       f"{liq_abs*100:.0f} % desde el último snapshot")
                if m['precios'] and m_prev['precios']:
                    delta_p = m['precios'][0] - m_prev['precios'][0]
                    if abs(delta_p) > 0.05:
                        alertas.append(f"La probabilidad se movió {delta_p*100:+.0f} pts")

        # Divergencia contra el modelo propio (si el engine puede mapear equipos)
        if engine is not None and m['precios']:
            equipos_detectados = engine.detectar_equipos(m['pregunta'])
            if len(equipos_detectados) >= 2:
                pred = engine.predecir(equipos_detectados[0], equipos_detectados[1])
                if 'error' not in pred:
                    p_modelo = pred['prediction']['probabilities']['home']
                    div_abs = abs(m['precios'][0] - p_modelo)
                    if div_abs > UMBRAL_DIVERGENCIA:
                        alertas.append(
                            f"Divergencia modelo vs mercado: {(m['precios'][0]-p_modelo)*100:+.0f} pts "
                            f"(modelo {p_modelo*100:.0f} % vs mercado {m['precios'][0]*100:.0f} %)")

        # Riesgo COMPUESTO (especificación v13)
        if div_abs > UMBRAL_DIVERGENCIA_ALTA and liq_abs > UMBRAL_LIQUIDEZ_ALTA:
            nivel = 'alto'
        elif div_abs > UMBRAL_DIVERGENCIA or liq_abs > UMBRAL_LIQUIDEZ:
            nivel = 'medio'
        else:
            nivel = 'bajo'
        senales.append({'pregunta': m['pregunta'], 'precios': m['precios'],
                        'salidas': m['salidas'], 'volumen': m['volumen'],
                        'liquidez': m['liquidez'], 'alertas': alertas,
                        'equipos': equipos_detectados,
                        'riesgo_manipulacion': nivel})
    return senales


def _guardar_risk_flags(senales: List[Dict]):
    """risk_flags.json: nivel de riesgo por pareja de equipos (para el parlay)."""
    flags = {}
    orden = {'bajo': 0, 'medio': 1, 'alto': 2}
    for s in senales:
        eq = s.get('equipos') or []
        if len(eq) >= 2:
            clave = f"{eq[0]}|{eq[1]}"
            if orden[s['riesgo_manipulacion']] >= orden.get(flags.get(clave, 'bajo'), 0):
                flags[clave] = s['riesgo_manipulacion']
    with open(RISK_FILE, 'w', encoding='utf-8') as f:
        json.dump({'actualizado': datetime.datetime.now().isoformat(timespec='minutes'),
                   'flags': flags}, f, ensure_ascii=False)


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
        _guardar_risk_flags(datos['senales'])
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
