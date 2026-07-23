#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Fuente de datos de las competiciones UEFA secundarias (v35 §2).

HALLAZGO (verificado 2026-07-23, contra lo que asumía el spec v35):
football-data.co.uk NO publica Europa League ni Conference League — su
índice (`data.php`) solo contiene ligas domésticas; `/new/EUR.csv` da 404.
La fuente gratuita que SÍ las cubre en profundidad es el JSON público de
ESPN (`site.api.espn.com`), ya usado en el proyecto para el Mundial y la
cadena de resiliencia de la MLS:

    /apis/site/v2/sports/soccer/{liga}/scoreboard?dates=AAAAMMDD-AAAAMMDD

  · uefa.europa       → UEFA Europa League
  · uefa.europa.conf  → UEFA Conference League

Además del marcador, el evento trae la SEDE (`venue.address.city/country`),
que alimenta el CDI de fútbol (v35 §3) sin ninguna petición adicional.

Cadena de resiliencia: ESPN → API-Football (temporadas 2022-24 del plan
Free) → CSV local previo. Ningún eslabón rompe el pipeline.
"""

import io
import json
import logging
import os
import time
from typing import Dict, List, Optional

import pandas as pd
import requests

from source_resilience import Cadena

logger = logging.getLogger(__name__)

ESPN_BASE = 'https://site.api.espn.com/apis/site/v2/sports/soccer/{liga}/scoreboard'
SEDES_FILE = 'sedes_futbol.csv'          # sede por partido (para el CDI)

# Meses SIN actividad UEFA (receso de verano): se saltan para no gastar
# peticiones. Junio se conserva (finales tardías).
MESES_SIN_UEFA = (7,)


def _rango_meses(desde: str, hasta: Optional[str] = None):
    ini = pd.Timestamp(desde).normalize().replace(day=1)
    fin = pd.Timestamp(hasta) if hasta else pd.Timestamp.today()
    cur = ini
    while cur <= fin:
        if cur.month not in MESES_SIN_UEFA:
            ultimo = (cur + pd.offsets.MonthEnd(1)).normalize()
            yield cur.strftime('%Y%m%d'), min(ultimo, fin).strftime('%Y%m%d')
        cur = (cur + pd.offsets.MonthBegin(1)).normalize()


def descargar_espn(liga_espn: str, desde: str, hasta: Optional[str] = None,
                   pausa: float = 0.2) -> pd.DataFrame:
    """Resultados finalizados de una competición ESPN entre dos fechas."""
    filas = []
    for ini, fin in _rango_meses(desde, hasta):
        try:
            r = requests.get(ESPN_BASE.format(liga=liga_espn),
                             params={'dates': f'{ini}-{fin}', 'limit': 500},
                             timeout=30)
            r.raise_for_status()
            eventos = r.json().get('events', []) or []
        except Exception as e:
            logger.warning(f"[uefa/{liga_espn}] {ini}-{fin}: {type(e).__name__} {e}")
            continue
        for ev in eventos:
            try:
                comp = ev['competitions'][0]
                if not comp.get('status', ev.get('status', {})).get('type', {}).get('completed'):
                    continue
                loc = next(c for c in comp['competitors'] if c['homeAway'] == 'home')
                vis = next(c for c in comp['competitors'] if c['homeAway'] == 'away')
                gh, ga = loc.get('score'), vis.get('score')
                if gh is None or ga is None:
                    continue
                venue = comp.get('venue', {}) or {}
                dirn = venue.get('address', {}) or {}
                filas.append({
                    'date': pd.to_datetime(ev['date']).tz_convert(None)
                            if pd.to_datetime(ev['date']).tzinfo
                            else pd.to_datetime(ev['date']),
                    'home_team': loc['team']['displayName'],
                    'away_team': vis['team']['displayName'],
                    'home_goals': float(gh), 'away_goals': float(ga),
                    'sede_ciudad': dirn.get('city'),
                    'sede_pais': dirn.get('country'),
                    'sede_nombre': venue.get('fullName'),
                })
            except Exception:
                continue
        time.sleep(pausa)
    df = pd.DataFrame(filas)
    if df.empty:
        return df
    # Prórroga/penales: ESPN publica el marcador FINAL (incl. prórroga). El
    # 1X2 de eliminatorias a ida y vuelta se entrena igual que en Champions
    # (donde la fusión FBref ya excluía prórrogas): aquí se conserva porque
    # el marcador es el del partido disputado y el empate sigue siendo un
    # resultado observable en la fase de liga (la gran mayoría de partidos).
    df = df.drop_duplicates(subset=['date', 'home_team', 'away_team'])
    return df.sort_values('date').reset_index(drop=True)


def _de_api_football(league_id: int) -> pd.DataFrame:
    """Eslabón 2: API-Football (plan Free → solo temporadas 2022-2024)."""
    import api_football_manager as afm
    filas = []
    for season in (2022, 2023, 2024):
        data = afm.api_call('fixtures', {'league': league_id, 'season': season},
                            prioridad=3, ttl=None)
        for p in ((data or {}).get('response') or []):
            ft = p['score']['fulltime']
            if p['fixture']['status']['short'] not in ('FT', 'AET', 'PEN') \
                    or ft['home'] is None:
                continue
            filas.append({
                'date': pd.to_datetime(p['fixture']['date']).tz_localize(None),
                'home_team': p['teams']['home']['name'],
                'away_team': p['teams']['away']['name'],
                'home_goals': float(ft['home']), 'away_goals': float(ft['away']),
                'sede_ciudad': (p['fixture'].get('venue') or {}).get('city'),
                'sede_pais': None, 'sede_nombre': (p['fixture'].get('venue') or {}).get('name'),
            })
    return pd.DataFrame(filas)


def _de_csv_local(clave: str) -> pd.DataFrame:
    ruta = f'historico_{clave}.csv'
    if not os.path.exists(ruta):
        return pd.DataFrame()
    return pd.read_csv(ruta, parse_dates=['date'])


def historico_uefa(clave: str, liga_espn: str, desde: str,
                   api_league_id: Optional[int] = None) -> pd.DataFrame:
    """Histórico con cadena de resiliencia (principio transversal v33)."""
    fuentes = [('ESPN', lambda: descargar_espn(liga_espn, desde))]
    if api_league_id:
        fuentes.append(('API-Football', lambda: _de_api_football(api_league_id)))
    fuentes.append(('CSV local', lambda: _de_csv_local(clave)))
    cadena = Cadena(f'histórico {clave}', fuentes)
    df = cadena.obtener(validador=lambda d: d is not None and len(d) > 50)
    if df is None or df.empty:
        raise RuntimeError(f"{clave}: ninguna fuente devolvió histórico.")
    logger.info(f"[uefa/{clave}] {len(df)} partidos "
                f"({df['date'].min().date()} → {df['date'].max().date()}) "
                f"vía {[t for t in cadena.traza if t['estado'] == 'ok']}")
    return df


def volcar_sedes(dfs: Dict[str, pd.DataFrame], ruta: str = SEDES_FILE) -> int:
    """Acumula la sede de cada partido (para el CDI de fútbol v35 §3)."""
    trozos = []
    if os.path.exists(ruta):
        trozos.append(pd.read_csv(ruta, parse_dates=['date']))
    for clave, df in dfs.items():
        if df is None or df.empty or 'sede_ciudad' not in df.columns:
            continue
        t = df[['date', 'home_team', 'away_team', 'sede_ciudad',
                'sede_pais', 'sede_nombre']].copy()
        t['competicion'] = clave
        trozos.append(t)
    if not trozos:
        return 0
    todo = pd.concat(trozos, ignore_index=True)
    todo = todo.drop_duplicates(subset=['date', 'home_team', 'away_team'], keep='last')
    todo.sort_values('date').to_csv(ruta, index=False, encoding='utf-8')
    return len(todo)


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    import config
    salida = {}
    for clave in ('europa_league', 'conference_league'):
        cfg = config.LEAGUES[clave]
        df = historico_uefa(clave, cfg['espn_liga'], cfg['desde'],
                            cfg.get('api_league_id'))
        df.to_csv(f'historico_{clave}.csv', index=False, encoding='utf-8')
        salida[clave] = df
        print(f"{clave}: {len(df)} partidos, "
              f"{df['sede_ciudad'].notna().mean()*100:.0f} % con sede")
    print('sedes acumuladas:', volcar_sedes(salida))
