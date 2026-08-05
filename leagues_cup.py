#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v97 — Leagues Cup (MLS vs Liga MX).

El problema: 230 partidos no dan para un modelo
-----------------------------------------------
ESPN sirve la competición entera (`concacaf.leagues.cup`) y con calidad:
2019 (7), 2021 (7), 2023 (77), 2024 (77) y 2025 (62) = **230 partidos
terminados**, más los 54 de la edición 2026 que arranca hoy. Pero 230 partidos
repartidos entre 47 equipos son ~5 por equipo: entrenar ahí un modelo propio
daría un ELO de ruido y una precisión que no significaría nada.

La solución: los equipos NO son nuevos
--------------------------------------
Todos los participantes son de la MLS o de la Liga MX, y de esas dos el
proyecto ya tiene **3.719 y 2.660 partidos**. Lo que falta no es historia de
los equipos: es la **escala entre las dos ligas** — cuánto vale un punto de
ELO mexicano en dólares estadounidenses. Y eso es justamente lo que miden los
230 partidos cruzados, que son los únicos que enfrentan a las dos.

Así que el histórico de la Leagues Cup se construye **agrupando las tres
fuentes en un solo hilo cronológico**: el ELO se calcula sobre el conjunto, la
MLS y la Liga MX aportan el nivel de cada club y los partidos de Leagues Cup
son los que calibran el escalón entre ligas. Es el mismo razonamiento por el
que la v96 unió ITF y circuito principal en un solo histórico de tenis.

Los nombres se mapean A MANO
----------------------------
Se probó el emparejamiento difuso de `name_mapper` sobre los 47 equipos y
acertó 46… y falló justo donde más caro sale: mandó **«Red Bull New York» a
«New York City»**, que son dos clubes distintos de la misma ciudad. Fundir sus
historiales habría dado a los dos un ELO promediado y nadie lo habría notado
mirando la precisión. Con un universo cerrado de 47 equipos, la tabla explícita
cuesta media hora y no puede fallar en silencio: `historico()` comprueba que
todo nombre de ESPN esté en la tabla y **avisa del que falte**.
"""

import logging
from typing import Dict, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

ESPN_LIGA = 'concacaf.leagues.cup'
DESDE = '2019-01-01'
_FD = 'https://www.football-data.co.uk'


def _desde_csv(url: str):
    """MLS o Liga MX completas desde football-data, con el esquema del motor."""
    import io as _io

    import pandas as pd
    import requests
    r = requests.get(url, timeout=40)
    r.raise_for_status()
    crudo = pd.read_csv(_io.StringIO(r.text), on_bad_lines='skip',
                        encoding_errors='ignore')
    d = pd.DataFrame({
        'date': pd.to_datetime(crudo['Date'], dayfirst=True, errors='coerce'),
        'home_team': crudo['Home'], 'away_team': crudo['Away'],
        'home_goals': pd.to_numeric(crudo['HG'], errors='coerce'),
        'away_goals': pd.to_numeric(crudo['AG'], errors='coerce'),
    })
    return d.dropna(subset=['date', 'home_team', 'away_team',
                            'home_goals', 'away_goals']).reset_index(drop=True)

# Nombre en ESPN -> nombre en el histórico de football-data de su liga.
ALIAS = {
    # --- Liga MX -------------------------------------------------------
    'América': 'Club America',
    'Atlante': 'Atlante',
    'Atlas': 'Atlas',
    'Atlético de San Luis': 'Atl. San Luis',
    'Cruz Azul': 'Cruz Azul',
    'FC Juarez': 'Juarez',
    'Guadalajara': 'Guadalajara Chivas',
    'León': 'Club Leon',
    'Mazatlán FC': 'Mazatlan FC',
    'Monterrey': 'Monterrey',
    'Necaxa': 'Necaxa',
    'Pachuca': 'Pachuca',
    'Puebla': 'Puebla',
    'Pumas UNAM': 'UNAM Pumas',
    'Querétaro': 'Queretaro',
    'Santos': 'Santos Laguna',
    'Tigres UANL': 'Tigres UANL',
    'Tijuana': 'Club Tijuana',
    'Toluca': 'Toluca',
    # --- MLS -----------------------------------------------------------
    'Atlanta United FC': 'Atlanta Utd',
    'Austin FC': 'Austin FC',
    'CF Montréal': 'CF Montreal',
    'Charlotte FC': 'Charlotte',
    'Chicago Fire FC': 'Chicago Fire',
    'Colorado Rapids': 'Colorado Rapids',
    'Columbus Crew': 'Columbus Crew',
    'D.C. United': 'DC United',
    'FC Cincinnati': 'FC Cincinnati',
    'FC Dallas': 'FC Dallas',
    'Houston Dynamo FC': 'Houston Dynamo',
    'Inter Miami CF': 'Inter Miami',
    'LA Galaxy': 'Los Angeles Galaxy',
    'LAFC': 'Los Angeles FC',
    'Minnesota United FC': 'Minnesota United',
    'Nashville SC': 'Nashville SC',
    'New England Revolution': 'New England Revolution',
    'New York City FC': 'New York City',
    'Orlando City SC': 'Orlando City',
    'Philadelphia Union': 'Philadelphia Union',
    'Portland Timbers': 'Portland Timbers',
    'Real Salt Lake': 'Real Salt Lake',
    # OJO: NO es «New York City». Son dos clubes distintos de Nueva York y el
    # emparejamiento difuso los confundía.
    'Red Bull New York': 'New York Red Bulls',
    'San Diego FC': 'San Diego FC',
    'San Jose Earthquakes': 'San Jose Earthquakes',
    'Seattle Sounders FC': 'Seattle Sounders',
    'Sporting Kansas City': 'Sporting Kansas City',
    'St. Louis CITY SC': 'St. Louis City',
    'Toronto FC': 'Toronto FC',
    'Vancouver Whitecaps': 'Vancouver Whitecaps',
}

# Equipos sin emparejar en el cuadro (rondas aún sin sortear).
IGNORAR = {'TBD', ''}


def traducir(nombre: str) -> Optional[str]:
    n = str(nombre or '').strip()
    if n in IGNORAR:
        return None
    return ALIAS.get(n)


def partidos_espn(desde: str = DESDE, hasta: Optional[str] = None) -> pd.DataFrame:
    """Partidos TERMINADOS de Leagues Cup, ya con los nombres del proyecto."""
    import uefa_scraper
    df = uefa_scraper.descargar_espn(ESPN_LIGA, desde, hasta)
    if df.empty:
        return df
    desconocidos = sorted(
        {n for n in set(df.home_team) | set(df.away_team)
         if n not in IGNORAR and n not in ALIAS})
    if desconocidos:
        # No se cae: se avisa y se descartan esos partidos. Un equipo nuevo
        # (la Leagues Cup cambia de formato cada año) no debe tumbar el
        # entrenamiento, pero tampoco puede entrar sin nombre canónico.
        logger.warning(f'[leagues_cup] {len(desconocidos)} equipos sin alias, '
                       f'sus partidos se descartan: {desconocidos}')
    df = df.copy()
    df['home_team'] = df['home_team'].map(traducir)
    df['away_team'] = df['away_team'].map(traducir)
    df = df.dropna(subset=['home_team', 'away_team'])
    df['competicion'] = 'leagues_cup'
    return df.reset_index(drop=True)


def historico(con_ligas: bool = True) -> pd.DataFrame:
    """
    Histórico con el que se entrena la Leagues Cup.

    Con `con_ligas=True` (lo desplegado) devuelve MLS + Liga MX + Leagues Cup
    en un solo hilo cronológico, de modo que `_elo_diff_liga` calcule un ELO
    COMÚN a las tres. Con `False` devuelve sólo la Leagues Cup, que es la
    alternativa contra la que se midió (ver `_v97_wf_leagues_cup.py`).
    """
    lc = partidos_espn()
    if lc.empty:
        return lc
    if not con_ligas:
        return lc.sort_values('date').reset_index(drop=True)

    # v99 — SE TIRA DEL CSV COMPLETO, NO DE LA VENTANA DE 8 AÑOS.
    #
    # `descargar_liga` recorta MLS y Liga MX a `anios_ventana: 8`, que es una
    # elección VALIDADA para los modelos de esas dos ligas y no se toca. Pero
    # para la Leagues Cup el problema es el contrario: le sobra recorte. Los
    # CSV de football-data llegan a **2012** (USA 6.084 partidos, MEX 4.682) y
    # el agrupado sólo usaba desde 2018-08 — 6.379 de los 10.766 que hay.
    #
    # Aquí lo que se busca es el nivel de cada club y la escala entre las dos
    # ligas, y para eso más pasado es mejor: el ELO llega mejor anclado al
    # primer cruce. Se leen los CSV directamente para no alterar en nada lo
    # que consumen `mls` y `liga_mx`.
    marcos = []
    for clave, url in (('mls', f'{_FD}/new/USA.csv'),
                       ('liga_mx', f'{_FD}/new/MEX.csv')):
        try:
            d = _desde_csv(url)
            d['competicion'] = clave
            marcos.append(d)
            logger.info(f'[leagues_cup] {clave}: {len(d)} partidos desde '
                        f'{d["date"].min().date()}')
        except Exception as e:
            logger.warning(f'[leagues_cup] {clave} desde CSV falló '
                           f'({type(e).__name__}: {e}); se cae a descargar_liga.')
            try:
                import league_engine as le
                d = le.descargar_liga(clave).dropna(
                    subset=['date', 'home_team', 'away_team',
                            'home_goals', 'away_goals']).copy()
                d['competicion'] = clave
                marcos.append(d)
            except Exception as e2:
                logger.warning(f'[leagues_cup] {clave} no disponible: '
                               f'{type(e2).__name__}: {e2}')
    marcos.append(lc)
    df = pd.concat(marcos, ignore_index=True, sort=False)
    df = df.dropna(subset=['date', 'home_goals', 'away_goals'])
    df = (df.sort_values('date')
            .drop_duplicates(subset=['date', 'home_team', 'away_team'],
                             keep='first')
            .reset_index(drop=True))
    logger.info(f"[leagues_cup] histórico agrupado: {len(df)} partidos "
                f"({df['competicion'].value_counts().to_dict()}) · "
                f"{df['home_team'].nunique()} equipos")
    return df


def proximos(dias: int = 14) -> pd.DataFrame:
    """
    Partidos de Leagues Cup por jugar, con los dos equipos ya definidos.

    Los que siguen en TBD (rondas sin sortear) se descartan: es el mismo
    criterio que el tenis usa desde la v94 — una casa no cotiza un TBD y el
    modelo no puede predecirlo.
    """
    import requests
    hoy = pd.Timestamp.utcnow().tz_localize(None).normalize()
    fin = hoy + pd.Timedelta(days=dias)
    try:
        r = requests.get(
            f'https://site.api.espn.com/apis/site/v2/sports/soccer/{ESPN_LIGA}/scoreboard',
            params={'dates': f"{hoy:%Y%m%d}-{fin:%Y%m%d}", 'limit': 500},
            timeout=30)
        r.raise_for_status()
        eventos = r.json().get('events', []) or []
    except Exception as e:
        logger.warning(f'[leagues_cup] próximos: {type(e).__name__}: {e}')
        return pd.DataFrame()
    filas = []
    for ev in eventos:
        try:
            comp = ev['competitions'][0]
            if comp.get('status', {}).get('type', {}).get('completed'):
                continue
            loc = next(c for c in comp['competitors'] if c['homeAway'] == 'home')
            vis = next(c for c in comp['competitors'] if c['homeAway'] == 'away')
            h = traducir(loc['team']['displayName'])
            a = traducir(vis['team']['displayName'])
            if not h or not a:
                continue
            filas.append({'date': pd.to_datetime(ev['date']).tz_localize(None)
                          if pd.to_datetime(ev['date']).tzinfo
                          else pd.to_datetime(ev['date']),
                          'home_team': h, 'away_team': a,
                          'home_espn': loc['team']['displayName'],
                          'away_espn': vis['team']['displayName'],
                          'sede': (comp.get('venue') or {}).get('fullName')})
        except Exception:
            continue
    return pd.DataFrame(filas).sort_values('date').reset_index(drop=True) \
        if filas else pd.DataFrame()


if __name__ == '__main__':
    import json
    import sys
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    sys.stdout.reconfigure(encoding='utf-8')
    df = historico()
    px = proximos()
    print(json.dumps({
        'partidos': len(df),
        'por_competicion': df['competicion'].value_counts().to_dict(),
        'equipos': int(df['home_team'].nunique()),
        'desde': str(df['date'].min().date()), 'hasta': str(df['date'].max().date()),
        'proximos': len(px)}, ensure_ascii=False, indent=1))
    if len(px):
        print(px[['date', 'home_team', 'away_team']].head(12).to_string())
