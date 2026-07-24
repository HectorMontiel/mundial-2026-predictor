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


# v14/M10: cuotas GRATUITAS de próximos partidos de clubes desde
# football-data.co.uk/fixtures.csv (mismo proveedor confiable del histórico).
# Trae B365 de 1X2 + over/under 2.5 sin clave ni scraping.
DIV_A_LIGA = {'E0': 'premier', 'SP1': 'laliga', 'I1': 'serie_a',
              'D1': 'bundesliga', 'F1': 'ligue_1', 'N1': 'eredivisie',
              'P1': 'primeira'}
FIXTURES_URL = 'https://www.football-data.co.uk/fixtures.csv'


def descargar_cuotas_fixtures() -> pd.DataFrame:
    """Cuotas B365 reales de los PRÓXIMOS partidos de las ligas de clubes.

    100 % gratuito y sin clave. El MATCH_ID usa los mismos nombres de equipo
    de football-data que league_engine, así que el parlay los cruza directo.
    """
    try:
        import io
        r = requests.get(FIXTURES_URL, headers={'User-Agent': 'Mozilla/5.0'}, timeout=30)
        r.raise_for_status()
        # utf-8-sig: fixtures.csv llega con BOM que rompería la columna 'Div'
        df = pd.read_csv(io.BytesIO(r.content), encoding='utf-8-sig',
                         on_bad_lines='skip')
        df = df[df['Div'].isin(DIV_A_LIGA)]
        df = df.dropna(subset=['Date', 'HomeTeam', 'AwayTeam', 'B365H', 'B365D', 'B365A'])
        fechas = pd.to_datetime(df['Date'], dayfirst=True, errors='coerce')
        filas = pd.DataFrame({
            'MATCH_ID': [f"{f.strftime('%Y%m%d')}_{str(h).replace(' ', '-')}_{str(a).replace(' ', '-')}"
                         for f, h, a in zip(fechas, df['HomeTeam'], df['AwayTeam'])],
            'odd_home': pd.to_numeric(df['B365H'], errors='coerce'),
            'odd_draw': pd.to_numeric(df['B365D'], errors='coerce'),
            'odd_away': pd.to_numeric(df['B365A'], errors='coerce'),
            'odd_over25': pd.to_numeric(df.get('B365>2.5'), errors='coerce'),
            'odd_under25': pd.to_numeric(df.get('B365<2.5'), errors='coerce'),
            # v19: hándicap asiático (línea + cuotas B365 de ambos lados)
            'ah_linea': pd.to_numeric(df.get('AHh'), errors='coerce'),
            'odd_ah_home': pd.to_numeric(df.get('B365AHH'), errors='coerce'),
            'odd_ah_away': pd.to_numeric(df.get('B365AHA'), errors='coerce'),
            'liga': df['Div'].map(DIV_A_LIGA),
        }).dropna(subset=['odd_home', 'odd_draw', 'odd_away'])
        # solo eventos futuros o de hoy: fixtures.csv puede arrastrar filas viejas
        hoy = pd.Timestamp.today().normalize()
        filas = filas[fechas.loc[filas.index] >= hoy]
        logger.info(f"fixtures.csv: {len(filas)} próximos partidos de clubes con cuotas B365.")
        return filas
    except Exception as e:
        logger.warning(f"fixtures.csv no disponible ({e}): sin cuotas de clubes.")
        return pd.DataFrame()


def actualizar_odds():
    """Acumula las cuotas nuevas en odds_historicas.csv (dedupe por MATCH_ID)."""
    nuevas = descargar_cuotas_historicas()          # Mundial (The Odds API, con clave)
    fixtures = descargar_cuotas_fixtures()          # clubes (gratuito, sin clave)
    # Mundial sin clave (v14/M10): Betexplorer en días de partido
    if nuevas.empty:
        try:
            from betexplorer_scraper import cuotas_mundial_hoy
            nuevas = cuotas_mundial_hoy()
        except Exception as e:
            logger.warning(f"Betexplorer no disponible: {e}")
    # Clubes en vivo (v18/M2): Betexplorer también lista Liga MX y europa;
    # complementa a fixtures.csv (única vía gratuita de cuotas MX del día)
    try:
        from betexplorer_scraper import cuotas_clubes_hoy
        clubes_hoy = cuotas_clubes_hoy()
        if not clubes_hoy.empty:
            fixtures = pd.concat([fixtures, clubes_hoy], ignore_index=True)
    except Exception as e:
        logger.warning(f"Betexplorer clubes no disponible: {e}")

    if not nuevas.empty:
        if os.path.exists(ODDS_FILE):
            previas = pd.read_csv(ODDS_FILE)
            completas = pd.concat([previas, nuevas], ignore_index=True)
            completas = completas.drop_duplicates(subset='MATCH_ID', keep='first')
        else:
            completas = nuevas
        completas.to_csv(ODDS_FILE, index=False)
        logger.info(f"{ODDS_FILE}: {len(completas)} partidos con cuotas de apertura acumuladas.")

    # Snapshot ACTUAL para el parlay: Mundial (si hay clave) + clubes (siempre)
    snapshot = pd.concat([nuevas, fixtures], ignore_index=True) \
        if not (nuevas.empty and fixtures.empty) else pd.DataFrame()

    # v25 (CLV): todo snapshot se acumula con marca de tiempo en
    # odds_historico.db, y The Odds API se captura AGRUPADA por liga
    # (h2h + totals 2.5 + btts) si hay ODDS_API_KEY.
    btts = {}
    api_h2h, api_tot = {}, {}
    try:
        import odds_api
        if not snapshot.empty:
            odds_api.snapshot_desde_fixtures(snapshot)
        # v28: orquestador con presupuesto (tier-1 RLM + resto 1×/día)
        odds_api.capturar_auto()
        btts = odds_api.cuotas_recientes('btts')
        # v26: el h2h/totals de The Odds API también alimenta odds_actuales —
        # clave fuera de temporada europea: fixtures.csv llega vacío pero
        # Liga MX/MLS juegan y la API sí trae sus cuotas.
        api_h2h = odds_api.cuotas_recientes('h2h')
        api_tot = odds_api.cuotas_recientes('totals25')
        # v42: línea SHARP de Pinnacle (referencia de confirmación)
        api_pin = odds_api.cuotas_recientes('h2h', fuente='pinnacle')
    except Exception as e:
        logger.warning(f"Almacén CLV no disponible: {e}")
        api_pin = {}

    extra = []
    ya = set(snapshot['MATCH_ID']) if not snapshot.empty else set()
    for mid, c in api_h2h.items():
        if mid in ya or not all(c.get(s) for s in ('home', 'draw', 'away')):
            continue
        tot = api_tot.get(mid, {})
        extra.append({'MATCH_ID': mid, 'odd_home': c['home'],
                      'odd_draw': c['draw'], 'odd_away': c['away'],
                      'odd_over25': tot.get('over'),
                      'odd_under25': tot.get('under')})
    if extra:
        snapshot = pd.concat([snapshot, pd.DataFrame(extra)], ignore_index=True)
        logger.info(f"The Odds API aporta {len(extra)} partidos a odds_actuales "
                    "(no estaban en fixtures.csv/Betexplorer).")

    if snapshot.empty:
        logger.info("Sin cuotas vigentes que registrar en odds_actuales.json.")
        return
    snapshot = snapshot.drop_duplicates(subset='MATCH_ID', keep='first')
    cuotas_dict = snapshot.set_index('MATCH_ID').to_dict('index')
    # BTTS de The Odds API → mismo diccionario (v25: EV de BTTS en la UI)
    for mid, c in btts.items():
        if mid in cuotas_dict:
            if c.get('yes'):
                cuotas_dict[mid]['odd_btts_yes'] = c['yes']
            if c.get('no'):
                cuotas_dict[mid]['odd_btts_no'] = c['no']
    # v42: cuotas de cierre SHARP de Pinnacle → confirmación sharp en alpha
    for mid, c in (api_pin or {}).items():
        if mid in cuotas_dict:
            for sel, attr in (('home', 'odd_home_pin'), ('draw', 'odd_draw_pin'),
                              ('away', 'odd_away_pin')):
                if c.get(sel):
                    cuotas_dict[mid][attr] = c[sel]
    with open('odds_actuales.json', 'w', encoding='utf-8') as f:
        json.dump({'actualizado': datetime.date.today().isoformat(),
                   'cuotas': cuotas_dict}, f)
    logger.info(f"odds_actuales.json: {len(snapshot)} eventos con cuotas vigentes"
                + (f" ({len(btts)} con BTTS)" if btts else "") + ".")


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
