#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Descubrimiento de mercados de PROPS de jugadores (v41 §2.2).

Búsqueda activa de fuentes GRATUITAS de props, en orden de prioridad. Este
módulo NO modela props todavía (eso exige datos históricos por jugador y un
modelo dedicado); descubre qué feeds de props existen hoy para no volver a dar
por imposible algo que sí está disponible.

HALLAZGO (verificado 2026-07-24, corrige la conclusión de v37):
  · MLB `pitcher_strikeouts`: 5 casas lo ofrecen en The Odds API (regiones
    us,eu). En v37 daba 0 casas → dependía de la región/hora, no de la capa.
    ⇒ El FEED de props de ponches SÍ está disponible.
  · Fútbol: hay mercados de props (player_shots_on_target, etc.); algunos
    nombres son inválidos (player_cards → 422). Cobertura variable por evento.
  · El MODELO de props queda diferido: necesita histórico por jugador
    (pybaseball para MLB, FotMob/StatsBomb para fútbol) — lift mayor, v42+.

Uso:  python props_scraper.py     # audita qué props hay disponibles hoy
"""

import logging
from typing import Dict, List

import requests

logger = logging.getLogger(__name__)

BASE = 'https://api.the-odds-api.com/v4'
# mercados de props por deporte (nombres válidos verificados)
PROPS = {
    'baseball_mlb': ['pitcher_strikeouts', 'batter_hits', 'batter_home_runs'],
    'basketball_nba': ['player_points', 'player_rebounds', 'player_assists'],
    'soccer_epl': ['player_shots_on_target', 'player_shots',
                   'player_goal_scorer_anytime'],
    'americanfootball_nfl': ['player_pass_tds', 'player_rush_yds'],
}


def _clave() -> str:
    import odds_api
    return odds_api._clave()


def descubrir_props(sport: str, markets: List[str],
                    max_eventos: int = 1) -> Dict:
    """¿Qué mercados de props hay disponibles HOY para un deporte? Devuelve por
    mercado el nº de casas que lo ofrecen (0 = no disponible ahora)."""
    k = _clave()
    if not k:
        return {'sport': sport, 'error': 'sin ODDS_API_KEY'}
    try:
        ev = requests.get(f'{BASE}/sports/{sport}/events',
                          params={'apiKey': k}, timeout=20)
        ev.raise_for_status()
        eventos = ev.json()
    except Exception as e:
        return {'sport': sport, 'error': f'events: {e}'}
    if not eventos:
        return {'sport': sport, 'eventos': 0, 'disponibles': {}}
    cobertura: Dict[str, int] = {m: 0 for m in markets}
    for evento in eventos[:max_eventos]:
        try:
            r = requests.get(f"{BASE}/sports/{sport}/events/{evento['id']}/odds",
                             params={'apiKey': k, 'regions': 'us,eu',
                                     'markets': ','.join(markets),
                                     'oddsFormat': 'decimal'}, timeout=20)
            if r.status_code != 200:
                continue
            for casa in r.json().get('bookmakers', []):
                for m in casa.get('markets', []):
                    if m['key'] in cobertura:
                        cobertura[m['key']] += 1
        except Exception:
            continue
    return {'sport': sport, 'eventos': len(eventos),
            'disponibles': {m: n for m, n in cobertura.items() if n > 0},
            'sin_cobertura': [m for m, n in cobertura.items() if n == 0]}


def auditar() -> List[Dict]:
    """Recorre todos los deportes y reporta qué props hay disponibles hoy."""
    out = []
    for sport, markets in PROPS.items():
        out.append(descubrir_props(sport, markets))
    return out


if __name__ == '__main__':
    import json
    logging.basicConfig(level=logging.INFO)
    print(json.dumps(auditar(), indent=2, ensure_ascii=False))
