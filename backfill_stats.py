#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Backfill progresivo de estadísticas avanzadas + utilidades de IDs y H2H (v21).

Con el plan Free de API-Football (100 req/día, temporadas 2022-2024) las
estadísticas por partido (remates, posesión, córners, tarjetas y xG cuando
existe) se descargan POCO A POCO: cada día, el pipeline gasta el presupuesto
sobrante (prioridad 2 de la jerarquía v21) en partidos aún no procesados,
empezando por las ligas más necesitadas (Liga MX y Primeira no tienen stats
reales en football-data; Champions las aprovechará en su reentrenamiento).

Estado: el propio CSV (`historico_estadisticas_avanzadas.csv`) dice qué
fixture_ids ya están procesados — no hay estado duplicado que se desincronice.
Cuando el backfill de una liga/temporada se completa, deja de consumir.

También expone:
  - ids_equipos_liga(clave): nombre API -> id (desde los fixtures cacheados)
  - h2h(id_a, id_b): historial de cruces (endpoint headtohead; el plan Free
    no admite `last`, se ordena y recorta en cliente)
"""

import json
import logging
import os
from difflib import SequenceMatcher
from typing import Dict, List, Optional

import pandas as pd

import api_football_manager as afm
from config import LEAGUES

logger = logging.getLogger(__name__)

ARCHIVO_STATS = 'historico_estadisticas_avanzadas.csv'
# Orden de backfill (spec v21 §6.1): primero las ligas sin stats reales
LIGAS_BACKFILL = ['liga_mx', 'primeira', 'champions']
TEMPORADAS_PLAN_FREE = [2024, 2023, 2022]

# ID de cada liga en API-Football (v3)
API_LEAGUE_IDS = {
    'champions': 2, 'premier': 39, 'ligue_1': 61, 'bundesliga': 78,
    'eredivisie': 88, 'primeira': 94, 'serie_a': 135, 'laliga': 140,
    'liga_mx': 262,
}

# type de la API -> columna del CSV (por lado)
_MAPA_STATS = {
    'Shots on Goal': 'remates_arco', 'Total Shots': 'remates',
    'Ball Possession': 'posesion', 'Corner Kicks': 'corners',
    'Yellow Cards': 'amarillas', 'Red Cards': 'rojas',
    'Fouls': 'faltas', 'expected_goals': 'xg',
}


def fixtures_liga(clave: str, season: int, prioridad: int = 2) -> List[dict]:
    """Fixtures finalizados de una liga/temporada (cacheado permanente)."""
    liga_id = API_LEAGUE_IDS.get(clave)
    if not liga_id:
        return []
    data = afm.api_call('fixtures', {'league': liga_id, 'season': season},
                        prioridad=prioridad, ttl=None)
    if not data or not data.get('response'):
        return []
    return [p for p in data['response']
            if p['fixture']['status']['short'] in ('FT', 'AET', 'PEN')]


def ids_equipos_liga(clave: str, prioridad: int = 6) -> Dict[str, int]:
    """Nombre de equipo (API) -> id, desde los fixtures cacheados de la liga."""
    nombres: Dict[str, int] = {}
    for season in TEMPORADAS_PLAN_FREE:
        for p in fixtures_liga(clave, season, prioridad=prioridad):
            for lado in ('home', 'away'):
                nombres[p['teams'][lado]['name']] = p['teams'][lado]['id']
        if nombres:
            break        # con una temporada basta para el mapa de ids
    return nombres


def id_equipo(clave: str, nombre: str, prioridad: int = 6) -> Optional[int]:
    """Resuelve un nombre local (football-data) al id de la API (fuzzy 0.75)."""
    nombres = ids_equipos_liga(clave, prioridad=prioridad)
    if not nombres:
        return None
    if nombre in nombres:
        return nombres[nombre]
    mejor, mejor_r = None, 0.0
    for n_api, tid in nombres.items():
        r = SequenceMatcher(None, nombre.lower(), n_api.lower()).ratio()
        if r > mejor_r:
            mejor, mejor_r = tid, r
    return mejor if mejor_r >= 0.75 else None


def h2h(id_a: int, id_b: int, n: int = 5, prioridad: int = 6) -> List[dict]:
    """Últimos n cruces entre dos equipos (caché 24 h). El plan Free no admite
    el parámetro `last`: se ordena por fecha y se recorta en cliente."""
    data = afm.api_call('fixtures/headtohead', {'h2h': f'{id_a}-{id_b}'},
                        prioridad=prioridad)
    if not data or not data.get('response'):
        return []
    finalizados = [p for p in data['response']
                   if p['fixture']['status']['short'] in ('FT', 'AET', 'PEN')]
    finalizados.sort(key=lambda p: p['fixture']['date'], reverse=True)
    return [{
        'fecha': p['fixture']['date'][:10],
        'competicion': p['league']['name'],
        'local': p['teams']['home']['name'], 'visitante': p['teams']['away']['name'],
        'goles_local': p['goals']['home'], 'goles_visitante': p['goals']['away'],
    } for p in finalizados[:n]]


# ---------------------------------------------------------------------------
# Backfill progresivo
# ---------------------------------------------------------------------------
def _parsear_statistics(fixture: dict, clave: str, data: dict) -> Optional[dict]:
    resp = data.get('response') or []
    if len(resp) != 2:
        return None
    fila = {
        'liga': clave,
        'fixture_id': fixture['fixture']['id'],
        'date': fixture['fixture']['date'][:10],
        'home_team_api': fixture['teams']['home']['name'],
        'away_team_api': fixture['teams']['away']['name'],
        'home_id': fixture['teams']['home']['id'],
        'away_id': fixture['teams']['away']['id'],
        'home_goals': fixture['score']['fulltime']['home'],
        'away_goals': fixture['score']['fulltime']['away'],
    }
    for equipo_stats in resp:
        lado = 'home' if equipo_stats['team']['id'] == fila['home_id'] else 'away'
        for s in equipo_stats.get('statistics', []):
            col = _MAPA_STATS.get(s.get('type'))
            if not col:
                continue
            v = s.get('value')
            if isinstance(v, str) and v.endswith('%'):
                v = v.rstrip('%')
            try:
                fila[f'{lado}_{col}'] = float(v) if v is not None else None
            except (TypeError, ValueError):
                fila[f'{lado}_{col}'] = None
    return fila


def _procesados() -> set:
    if not os.path.exists(ARCHIVO_STATS):
        return set()
    try:
        return set(pd.read_csv(ARCHIVO_STATS, usecols=['fixture_id'])['fixture_id'])
    except Exception:
        return set()


def backfill(max_requests: int = 40) -> Dict:
    """Descarga estadísticas de partidos pendientes hasta agotar el cupo del
    lote (o el presupuesto de prioridad 2 del gateway). Reanudable: el CSV es
    el estado. Devuelve un resumen para el log del pipeline."""
    hechos = _procesados()
    nuevas, usados = [], 0
    for clave in LIGAS_BACKFILL:
        for season in TEMPORADAS_PLAN_FREE:
            for p in fixtures_liga(clave, season, prioridad=2):
                fid = p['fixture']['id']
                if fid in hechos:
                    continue
                if usados >= max_requests:
                    break
                data = afm.api_call('fixtures/statistics', {'fixture': fid},
                                    prioridad=2)
                if data is None:            # sin presupuesto/clave: parar YA
                    usados = max_requests
                    break
                usados += 1
                if data.get('errors') and len(data['errors']):
                    continue
                fila = _parsear_statistics(p, clave, data)
                if fila:
                    nuevas.append(fila)
                    hechos.add(fid)
            if usados >= max_requests:
                break
        if usados >= max_requests:
            break

    if nuevas:
        df_nuevas = pd.DataFrame(nuevas)
        modo_append = os.path.exists(ARCHIVO_STATS)
        df_nuevas.to_csv(ARCHIVO_STATS, mode='a' if modo_append else 'w',
                         header=not modo_append, index=False)
    resumen = {'nuevos_partidos': len(nuevas), 'requests_gastados': usados,
               'total_acumulado': len(hechos),
               'restantes_hoy': afm.requests_restantes()}
    logger.info(f"Backfill de estadísticas: {resumen}")
    return resumen


if __name__ == '__main__':
    import sys
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    lote = int(sys.argv[1]) if len(sys.argv) > 1 else 40
    print(json.dumps(backfill(lote), indent=2))
