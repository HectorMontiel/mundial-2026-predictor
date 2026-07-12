#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Actualización EN VIVO del Mundial 2026 (M1, v13).

Cadena de fuentes (orden de preferencia):
  1. API-Football (RAPIDAPI_KEY): /fixtures league=1 season=2026 — goles,
     tarjetas, posesión, remates de los partidos ya finalizados.
  2. FBref: Scores & Fixtures del Mundial (cloudscraper + rate-limit).
  3. Kaggle con force_download (la fuente base se actualiza a diario y es
     la vía que SIEMPRE funciona sin claves).

Solo añade partidos NUEVOS al histórico (dedupe por MATCH_ID) y dispara el
recálculo de ELO/medias móviles. Programación en días de partido:
  schtasks /create /tn "MundialLive" /tr "...pipeline_mundial.py --live" /sc hourly /mo 2
"""

import datetime
import json
import logging
import os
from typing import Dict, List, Optional

import pandas as pd
import requests

from config import TEAMS, NAME_EN_TO_FIFA

logger = logging.getLogger(__name__)

WC_LEAGUE_ID = 1        # API-Football: FIFA World Cup
WC_SEASON = 2026

# Fases del Mundial 2026 por rango de fechas (calendario oficial FIFA)
FASES_2026 = [
    ('Fase de grupos', '2026-06-11', '2026-06-27'),
    ('Dieciseisavos de final', '2026-06-28', '2026-07-03'),
    ('Octavos de final', '2026-07-04', '2026-07-07'),
    ('Cuartos de final', '2026-07-09', '2026-07-11'),
    ('Semifinales', '2026-07-14', '2026-07-15'),
    ('Tercer puesto y Final', '2026-07-18', '2026-07-19'),
]


def fase_del_torneo(fecha) -> Optional[str]:
    """Nombre de la fase del Mundial a la que pertenece una fecha."""
    f = pd.Timestamp(fecha)
    for nombre, ini, fin in FASES_2026:
        if pd.Timestamp(ini) <= f <= pd.Timestamp(fin):
            return nombre
    return None


def _desde_api_football() -> pd.DataFrame:
    """Partidos finalizados del Mundial vía API-Football (si hay clave)."""
    key = os.getenv('RAPIDAPI_KEY')
    if not key:
        return pd.DataFrame()
    try:
        r = requests.get('https://api-football-v1.p.rapidapi.com/v3/fixtures',
                         headers={'X-RapidAPI-Key': key,
                                  'X-RapidAPI-Host': 'api-football-v1.p.rapidapi.com'},
                         params={'league': WC_LEAGUE_ID, 'season': WC_SEASON,
                                 'status': 'FT'}, timeout=30)
        r.raise_for_status()
        filas = []
        for m in r.json().get('response', []):
            home = NAME_EN_TO_FIFA.get(m['teams']['home']['name'], m['teams']['home']['name'])
            away = NAME_EN_TO_FIFA.get(m['teams']['away']['name'], m['teams']['away']['name'])
            fecha = pd.to_datetime(m['fixture']['date']).tz_localize(None).normalize()
            filas.append({
                'MATCH_ID': f"{fecha.strftime('%Y%m%d')}_{str(home).replace(' ', '-')}_{str(away).replace(' ', '-')}",
                'date': fecha, 'home_team': home, 'away_team': away,
                'home_goals': m['goals']['home'], 'away_goals': m['goals']['away'],
                'tournament': 'FIFA World Cup', 'stadium': None,
            })
        logger.info(f"API-Football (live): {len(filas)} partidos del Mundial finalizados.")
        return pd.DataFrame(filas)
    except Exception as e:
        logger.warning(f"API-Football live no disponible: {e}")
        return pd.DataFrame()


def _desde_fbref() -> pd.DataFrame:
    """Scores & Fixtures del Mundial en FBref (best-effort, sin clave)."""
    try:
        import cloudscraper
        scraper = cloudscraper.create_scraper()
        url = 'https://fbref.com/en/comps/1/schedule/World-Cup-Scores-and-Fixtures'
        r = scraper.get(url, timeout=30)
        r.raise_for_status()
        tablas = pd.read_html(r.text)
        df = tablas[0]
        df = df[df.get('Score').notna()] if 'Score' in df.columns else pd.DataFrame()
        if df.empty:
            return pd.DataFrame()
        goles = df['Score'].astype(str).str.extract(r'(\d+)\D+(\d+)')
        filas = pd.DataFrame({
            'date': pd.to_datetime(df['Date'], errors='coerce'),
            'home_team': df['Home'].map(lambda x: NAME_EN_TO_FIFA.get(str(x).strip(), str(x).strip())),
            'away_team': df['Away'].map(lambda x: NAME_EN_TO_FIFA.get(str(x).strip(), str(x).strip())),
            'home_goals': pd.to_numeric(goles[0], errors='coerce'),
            'away_goals': pd.to_numeric(goles[1], errors='coerce'),
        }).dropna()
        filas['tournament'] = 'FIFA World Cup'
        filas['stadium'] = None
        filas['MATCH_ID'] = (filas['date'].dt.strftime('%Y%m%d') + '_' +
                             filas['home_team'].str.replace(' ', '-') + '_' +
                             filas['away_team'].str.replace(' ', '-'))
        logger.info(f"FBref (live): {len(filas)} partidos del Mundial con marcador.")
        return filas
    except Exception as e:
        logger.warning(f"FBref live no disponible: {e}")
        return pd.DataFrame()


def actualizar_en_vivo() -> int:
    """
    Añade al histórico los partidos del Mundial recién finalizados que las
    fuentes en vivo reporten y que aún no estén registrados (dedupe por
    MATCH_ID). Devuelve el número de partidos añadidos. Los goles añadidos
    aquí quedan luego consolidados por la siguiente descarga completa de la
    fuente base (que también trae los minutos de gol).
    """
    from config import HISTORICO_FILE
    if not os.path.exists(HISTORICO_FILE):
        logger.warning("Sin histórico base: ejecuta el pipeline completo primero.")
        return 0
    historico = pd.read_csv(HISTORICO_FILE, parse_dates=['date'])
    existentes = set(historico['MATCH_ID'])

    nuevos = _desde_api_football()
    if nuevos.empty:
        nuevos = _desde_fbref()
    if nuevos.empty:
        logger.info("Fuentes en vivo sin datos nuevos: la re-descarga base (--live) "
                    "de la fuente principal cubre la actualización.")
        return 0

    nuevos = nuevos[~nuevos['MATCH_ID'].isin(existentes)]
    nuevos = nuevos[nuevos['home_team'].isin(TEAMS) | nuevos['away_team'].isin(TEAMS)]
    if nuevos.empty:
        logger.info("Todos los partidos en vivo ya estaban registrados.")
        return 0

    # Relleno determinista de las métricas ausentes (mismo método auditado)
    import statsbomb_calibration
    from correlated_synthetic_generator import CorrelatedSyntheticGenerator
    combinado = pd.concat([historico, nuevos], ignore_index=True)
    combinado = combinado.sort_values(['date', 'MATCH_ID'], kind='mergesort').reset_index(drop=True)
    from data_fetcher import compute_elo_series
    combinado['elo_diff'] = compute_elo_series(combinado)
    gen = CorrelatedSyntheticGenerator()
    combinado = gen.generate_advanced_metrics(combinado, statsbomb_calibration.calibrar())
    combinado.to_csv(HISTORICO_FILE, index=False)
    logger.info(f"🟢 {len(nuevos)} partidos del Mundial añadidos en vivo: "
                f"{list(nuevos['MATCH_ID'])}")
    return len(nuevos)


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    actualizar_en_vivo()
