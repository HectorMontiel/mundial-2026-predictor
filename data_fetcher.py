#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Capa de datos híbrida de 3 fuentes abiertas (sin scraping frágil):

  1. Kaggle – International Football Results (1872-presente): resultados
     REALES de todos los partidos internacionales, actualizados al día.
     Descarga vía kagglehub (sin credenciales para datasets públicos).
  2. API-Football (RapidAPI, capa gratuita): estadísticas reales de los
     últimos partidos (remates, posesión, tarjetas). Opcional: se activa
     definiendo la variable de entorno RAPIDAPI_KEY.
  3. StatsBomb Open Data: calibra las relaciones goles↔xG↔remates con las
     que el generador correlacionado completa las métricas faltantes de
     forma causal (no ruido independiente).

Salidas:
  - historico_partidos.csv   (resultados reales + métricas coherentes)
  - goleadores.csv           (goleadores REALES por partido, desde 2018)
  - elo_actual.csv           (ELO dinámico recalculado)
  - fuente_datos.json        (procedencia: real_hybrid)
"""

import datetime
import json
import logging
import os
from typing import Dict, Optional

import numpy as np
import pandas as pd
import requests

from config import (TEAMS, TEAM_NAMES_EN, NAME_EN_TO_FIFA, STADIUMS,
                    KAGGLE_DATASET, HISTORICO_FILE, ELO_FILE)
from correlated_synthetic_generator import CorrelatedSyntheticGenerator
import statsbomb_calibration

logger = logging.getLogger(__name__)

GOLEADORES_FILE = 'goleadores.csv'
FUENTE_FILE = 'fuente_datos.json'
API_IDS_CACHE = 'api_football_ids.json'
FECHA_INICIO_HISTORICO = '2010-01-01'


# ---------------------------------------------------------------------------
# 1. Base histórica real de Kaggle
# ---------------------------------------------------------------------------
def download_kaggle_results(live: bool = False) -> pd.DataFrame:
    """
    Descarga (o usa caché de kagglehub) y normaliza el histórico real.
    Con live=True fuerza la re-descarga ignorando el caché: modo Mundial en
    curso, para incorporar la última jornada en cuanto la fuente la publique.
    """
    import kagglehub
    path = kagglehub.dataset_download(KAGGLE_DATASET, force_download=live)
    df = pd.read_csv(os.path.join(path, 'results.csv'))
    df = df.rename(columns={'home_score': 'home_goals', 'away_score': 'away_goals'})
    df['date'] = pd.to_datetime(df['date'], errors='coerce')
    df = df.dropna(subset=['date', 'home_goals', 'away_goals'])
    df = df[df['date'] >= FECHA_INICIO_HISTORICO].copy()

    # Mapear las 48 selecciones a código FIFA; los demás países conservan su
    # nombre (siguen aportando señal a ELO y medias móviles de los nuestros).
    df['home_team'] = df['home_team'].map(lambda x: NAME_EN_TO_FIFA.get(x, x))
    df['away_team'] = df['away_team'].map(lambda x: NAME_EN_TO_FIFA.get(x, x))

    # La ciudad se usa como "estadio" para heredar la altitud si es conocida
    df['stadium'] = df['city'].where(df['city'].isin(STADIUMS.keys()), None)

    df['MATCH_ID'] = (df['date'].dt.strftime('%Y%m%d') + '_' +
                      df['home_team'].astype(str).str.replace(' ', '-') + '_' +
                      df['away_team'].astype(str).str.replace(' ', '-'))
    df = df.drop_duplicates(subset='MATCH_ID', keep='last')
    columnas = ['MATCH_ID', 'date', 'home_team', 'away_team', 'home_goals',
                'away_goals', 'tournament', 'city', 'country', 'neutral', 'stadium']
    logger.info(f"Kaggle: {len(df)} partidos reales desde {FECHA_INICIO_HISTORICO} "
                f"(hasta {df['date'].max().date()}).")
    # Orden TOTAL determinista (fecha + MATCH_ID, sort estable): los empates de
    # fecha siempre se procesan en el mismo orden => ELO reproducible.
    return df[columnas].sort_values(['date', 'MATCH_ID'], kind='mergesort').reset_index(drop=True)


def download_kaggle_goalscorers() -> pd.DataFrame:
    """Goleadores REALES por partido (nombres de jugadores) desde 2018."""
    import kagglehub
    path = kagglehub.dataset_download(KAGGLE_DATASET)
    g = pd.read_csv(os.path.join(path, 'goalscorers.csv'))
    g['date'] = pd.to_datetime(g['date'], errors='coerce')
    g = g.dropna(subset=['date', 'scorer'])
    g = g[g['date'] >= '2018-01-01'].copy()
    for col in ('home_team', 'away_team', 'team'):
        g[col] = g[col].map(lambda x: NAME_EN_TO_FIFA.get(x, x))
    # Conservar TODO gol de partidos que involucren a nuestras selecciones:
    # los goles del rival son los "encajados" (reacción, últimos 15 minutos).
    g = g[g['home_team'].isin(TEAMS) | g['away_team'].isin(TEAMS)]
    g['MATCH_ID'] = (g['date'].dt.strftime('%Y%m%d') + '_' +
                     g['home_team'].astype(str).str.replace(' ', '-') + '_' +
                     g['away_team'].astype(str).str.replace(' ', '-'))
    logger.info(f"Kaggle: {len(g)} goles reales con nombre y minuto (desde 2018).")
    return g


def agregar_minutos_de_gol(historico: pd.DataFrame, goleadores: pd.DataFrame) -> pd.DataFrame:
    """
    Añade al histórico, por partido, los agregados de MINUTO de gol reales:
      home/away_goals_2h  -> goles anotados en la segunda mitad (minuto > 45)
      home/away_goals_u15 -> goles anotados en los últimos 15 min (minuto >= 75)
    NaN cuando el partido no tiene desglose de goleadores (p. ej. anterior a 2018):
    las ventanas rodantes simplemente lo omiten.
    """
    g = goleadores.dropna(subset=['minute']).copy()
    g['minute'] = pd.to_numeric(g['minute'], errors='coerce')
    g = g.dropna(subset=['minute'])
    g['es_local'] = g['team'] == g['home_team']
    g['es_2h'] = g['minute'] > 45
    g['es_u15'] = g['minute'] >= 75

    agg = g.groupby('MATCH_ID').apply(
        lambda d: pd.Series({
            'home_goals_2h': int((d['es_local'] & d['es_2h']).sum()),
            'away_goals_2h': int((~d['es_local'] & d['es_2h']).sum()),
            'home_goals_u15': int((d['es_local'] & d['es_u15']).sum()),
            'away_goals_u15': int((~d['es_local'] & d['es_u15']).sum()),
        }), include_groups=False).reset_index()

    historico = historico.drop(columns=[c for c in ('home_goals_2h', 'away_goals_2h',
                                                    'home_goals_u15', 'away_goals_u15')
                                        if c in historico.columns])
    return historico.merge(agg, on='MATCH_ID', how='left')


# ---------------------------------------------------------------------------
# 2. Enriquecimiento reciente con API-Football (opcional, capa gratuita)
# ---------------------------------------------------------------------------
def _api_headers() -> Optional[Dict]:
    key = os.getenv('RAPIDAPI_KEY')
    if key:
        return {'X-RapidAPI-Key': key,
                'X-RapidAPI-Host': 'api-football-v1.p.rapidapi.com'}
    return None


def _api_team_id(team_fifa: str, headers: Dict, cache: Dict) -> Optional[int]:
    if team_fifa in cache:
        return cache[team_fifa]
    nombre = TEAM_NAMES_EN.get(team_fifa, team_fifa)
    try:
        r = requests.get('https://api-football-v1.p.rapidapi.com/v3/teams',
                         headers=headers, params={'search': nombre, 'country': nombre},
                         timeout=20)
        respuesta = r.json().get('response', [])
        nacionales = [t for t in respuesta if t['team'].get('national')]
        if nacionales:
            cache[team_fifa] = nacionales[0]['team']['id']
            return cache[team_fifa]
    except Exception as e:
        logger.warning(f"API-Football: fallo buscando id de {team_fifa}: {e}")
    return None


def fetch_last_matches_api_football(team_fifa: str, n: int = 5) -> pd.DataFrame:
    """Últimos n partidos finalizados del equipo con estadísticas reales."""
    headers = _api_headers()
    if not headers:
        return pd.DataFrame()
    cache = {}
    if os.path.exists(API_IDS_CACHE):
        try:
            with open(API_IDS_CACHE, 'r', encoding='utf-8') as f:
                cache = json.load(f)
        except Exception:
            cache = {}
    team_id = _api_team_id(team_fifa, headers, cache)
    with open(API_IDS_CACHE, 'w', encoding='utf-8') as f:
        json.dump(cache, f)
    if not team_id:
        return pd.DataFrame()

    try:
        r = requests.get('https://api-football-v1.p.rapidapi.com/v3/fixtures',
                         headers=headers, params={'team': team_id, 'last': n, 'status': 'FT'},
                         timeout=20)
        partidos = r.json().get('response', [])
    except Exception as e:
        logger.warning(f"API-Football: fallo fixtures de {team_fifa}: {e}")
        return pd.DataFrame()

    filas = []
    for m in partidos:
        home = NAME_EN_TO_FIFA.get(m['teams']['home']['name'], m['teams']['home']['name'])
        away = NAME_EN_TO_FIFA.get(m['teams']['away']['name'], m['teams']['away']['name'])
        fecha = pd.to_datetime(m['fixture']['date']).tz_localize(None).normalize()
        fila = {
            'MATCH_ID': f"{fecha.strftime('%Y%m%d')}_{str(home).replace(' ', '-')}_{str(away).replace(' ', '-')}",
            'date': fecha, 'home_team': home, 'away_team': away,
            'home_goals': m['goals']['home'], 'away_goals': m['goals']['away'],
            'tournament': m.get('league', {}).get('name', 'Oficial'),
        }
        # Estadísticas reales por bando si el plan las incluye
        for lado, prefijo in [('home', 'home'), ('away', 'away')]:
            stats = {}
            for ts in (m.get('statistics') or []):
                if ts['team']['id'] == m['teams'][lado]['id']:
                    stats = {s['type']: s['value'] for s in ts.get('statistics', [])}
            if stats:
                pos = str(stats.get('Ball Possession') or '').replace('%', '')
                fila[f'{prefijo}_possession'] = float(pos) if pos else None
                fila[f'{prefijo}_shots_on'] = stats.get('Shots on Goal')
                total = stats.get('Total Shots')
                if total is not None and stats.get('Shots on Goal') is not None:
                    fila[f'{prefijo}_shots_off'] = int(total) - int(stats['Shots on Goal'])
                fila[f'{prefijo}_yellow'] = stats.get('Yellow Cards')
                fila[f'{prefijo}_red'] = stats.get('Red Cards')
                fila[f'{prefijo}_corners'] = stats.get('Corner Kicks')
        filas.append(fila)
    return pd.DataFrame(filas)


def fetch_recent_all_teams(n: int = 5) -> pd.DataFrame:
    """Actualización reciente de las 48 selecciones (si hay RAPIDAPI_KEY)."""
    if not _api_headers():
        logger.info("RAPIDAPI_KEY no configurada: se omite la capa API-Football "
                    "(el histórico de Kaggle ya llega hasta ayer).")
        return pd.DataFrame()
    frames = []
    for team in TEAMS:
        df = fetch_last_matches_api_football(team, n)
        if not df.empty:
            frames.append(df)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


# ---------------------------------------------------------------------------
# 2b. Enriquecimiento con FBref (fuente primaria de stats recientes; opcional)
# ---------------------------------------------------------------------------
def actualizar_recientes_fbref(max_equipos: Optional[int] = None) -> pd.DataFrame:
    """
    Scrapea los partidos recientes (último año) desde FBref para inyectar
    estadísticas REALES (xG, remates, posesión, tarjetas) que pisan a las
    estimadas. Cadena de respaldo de la especificación:
        FBref -> API-Football -> caché (CSV existente) + aviso de frescura.
    Devuelve DataFrame en esquema de partido (vacío si FBref no responde).
    """
    try:
        from fbref_scraper_v2 import FBrefScraperV2
        scraper = FBrefScraperV2()
        if not scraper.load_nation_links():
            raise RuntimeError('índice de naciones no accesible')
        logs = []
        equipos = TEAMS[:max_equipos] if max_equipos else TEAMS
        for team in equipos:
            df = scraper.scrape_team_matches(team, years_back=1)
            if not df.empty:
                logs.append(df)
        if not logs:
            raise RuntimeError('sin datos de ningún equipo')
        recientes = scraper.to_match_schema(pd.concat(logs, ignore_index=True))
        logger.info(f"FBref: {len(recientes)} partidos recientes con estadísticas reales.")
        return recientes
    except Exception as e:
        logger.warning(f"FBref no disponible ({e}); se intentará API-Football y, "
                       f"en su defecto, el caché local.")
        return pd.DataFrame()


# ---------------------------------------------------------------------------
# 3. ELO cronológico sobre resultados reales
# ---------------------------------------------------------------------------
def compute_elo_series(df: pd.DataFrame) -> pd.Series:
    """
    Recorre el histórico en orden y devuelve la serie elo_diff (previo al
    partido, local - visitante). También persiste el ELO final por equipo.
    """
    elo: Dict[str, float] = {}
    diffs = np.zeros(len(df))
    for i, fila in enumerate(df.itertuples(index=False)):
        h, a = fila.home_team, fila.away_team
        r_h, r_a = elo.get(h, 1500.0), elo.get(a, 1500.0)
        diffs[i] = r_h - r_a
        e_h = 1 / (1 + 10 ** ((r_a - r_h) / 400))
        s_h = 1.0 if fila.home_goals > fila.away_goals else (0.5 if fila.home_goals == fila.away_goals else 0.0)
        k = 48 if 'World Cup' in str(fila.tournament) else (20 if 'Friendly' in str(fila.tournament) else 32)
        elo[h] = r_h + k * (s_h - e_h)
        elo[a] = r_a + k * ((1 - s_h) - (1 - e_h))
    pd.Series({t: elo.get(t, 1500.0) for t in TEAMS}, name='ELO').round(1).to_csv(ELO_FILE)
    logger.info(f"ELO dinámico recalculado sobre {len(df)} partidos reales.")
    return pd.Series(diffs, index=df.index)


# ---------------------------------------------------------------------------
# 4. Unificación
# ---------------------------------------------------------------------------
def build_unified_history(usar_fbref: bool = False, live: bool = False) -> pd.DataFrame:
    """Pipeline completo de la capa de datos. Devuelve el histórico unificado."""
    kaggle_df = download_kaggle_results(live=live)

    # Estadísticas recientes reales: FBref (primaria, opcional por lentitud)
    # con respaldo automático en API-Football; sin ambas, queda el caché.
    recientes = actualizar_recientes_fbref() if usar_fbref else pd.DataFrame()
    fuente_recientes = 'FBref' if not recientes.empty else None
    if recientes.empty:
        recientes = fetch_recent_all_teams(5)
        fuente_recientes = 'API-Football' if not recientes.empty else None

    if not recientes.empty:
        completo = pd.concat([kaggle_df, recientes], ignore_index=True)
        # Las estadísticas reales pisan a Kaggle en el mismo MATCH_ID
        completo = completo.drop_duplicates(subset='MATCH_ID', keep='last')
        logger.info(f"{fuente_recientes}: {len(recientes)} partidos recientes con stats reales inyectados.")
    else:
        completo = kaggle_df
    con_api = fuente_recientes is not None
    completo = completo.sort_values(['date', 'MATCH_ID'], kind='mergesort').reset_index(drop=True)

    # ELO previo al partido (insumo del relleno causal y del modelo)
    completo['elo_diff'] = compute_elo_series(completo)

    # Métricas avanzadas coherentes con los goles reales (StatsBomb-calibrado)
    calibracion = statsbomb_calibration.calibrar()
    generador = CorrelatedSyntheticGenerator()
    completo = generador.generate_advanced_metrics(completo, calibracion)

    # Minutos de gol REALES por partido (2ª mitad, últimos 15 minutos)
    goleadores = download_kaggle_goalscorers()
    goleadores.to_csv(GOLEADORES_FILE, index=False)
    completo = agregar_minutos_de_gol(completo, goleadores)

    completo.to_csv(HISTORICO_FILE, index=False)

    detalle = "Kaggle (resultados reales) + StatsBomb (calibración de métricas)"
    if con_api:
        detalle += f" + {fuente_recientes} (estadísticas recientes reales)"
    with open(FUENTE_FILE, 'w', encoding='utf-8') as f:
        json.dump({'source': 'real_hybrid', 'detalle': detalle,
                   'calibracion': calibracion.get('fuente'),
                   'ultima_fecha': str(completo['date'].max().date()),
                   'updated': datetime.date.today().isoformat()}, f, ensure_ascii=False, indent=2)

    logger.info(f"✅ Histórico unificado guardado: {len(completo)} partidos "
                f"(hasta {completo['date'].max().date()}).")
    return completo


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    build_unified_history()
