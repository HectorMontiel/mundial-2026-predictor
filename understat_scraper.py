#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Scraper ético de Understat — xG REAL para las grandes ligas europeas (v14/M8).

Understat expone un endpoint JSON (GET /getLeagueData/{liga}/{temporada})
que su propio frontend consume; devuelve todos los partidos de la temporada
con xG real de ambos equipos. Gratuito, sin registro.

Cobertura: Premier (EPL), LaLiga, Serie A, Bundesliga, Ligue 1.
NO cubre: Liga MX, Eredivisie, Primeira (esas siguen con el generador
calibrado StatsBomb).

Ética: caché en disco por liga+temporada (las temporadas cerradas no se
re-descargan jamás), pausa de 4 s entre peticiones, User-Agent real.

Uso como módulo:   inyectar_xg(df, clave_liga)  → df con home_xg/away_xg reales
Uso como script:   python understat_scraper.py --liga laliga
"""

import json
import logging
import os
import re
import time
import unicodedata
from typing import Dict, Optional

import pandas as pd
import requests

logger = logging.getLogger(__name__)

# clave de config.LEAGUES -> nombre de liga en Understat
LIGAS_UNDERSTAT = {
    'premier': 'EPL',
    'laliga': 'La_liga',
    'serie_a': 'Serie_A',
    'bundesliga': 'Bundesliga',
    'ligue_1': 'Ligue_1',
}

CACHE_DIR = 'understat_cache'
PAUSA_SEGUNDOS = 4
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/126.0 Safari/537.36')

# alias manuales: nombre Understat -> nombre football-data.co.uk
ALIAS = {
    'atletico madrid': 'ath madrid',
    'athletic club': 'ath bilbao',
    'real sociedad': 'sociedad',
    'real betis': 'betis',
    'celta vigo': 'celta',
    'rayo vallecano': 'vallecano',
    'deportivo alaves': 'alaves',
    'deportivo la coruna': 'la coruna',
    'real oviedo': 'oviedo',
    'manchester united': 'man united',
    'manchester city': 'man city',
    'newcastle united': 'newcastle',
    'wolverhampton wanderers': 'wolves',
    'nottingham forest': "nott'm forest",
    'sheffield united': 'sheffield united',
    'west ham': 'west ham',
    'ac milan': 'milan',
    'parma calcio 1913': 'parma',
    'hellas verona': 'verona',
    'bayern munich': 'bayern munich',
    'borussia dortmund': 'dortmund',
    'borussia m.gladbach': "m'gladbach",
    'bayer leverkusen': 'leverkusen',
    'rasenballsport leipzig': 'rb leipzig',
    'eintracht frankfurt': 'ein frankfurt',
    'fortuna duesseldorf': 'fortuna dusseldorf',
    'sc freiburg': 'freiburg',
    'fc cologne': 'fc koln',
    'vfb stuttgart': 'stuttgart',
    'vfl bochum': 'bochum',
    'werder bremen': 'werder bremen',
    'fc st. pauli': 'st pauli',
    'fc heidenheim': 'heidenheim',
    'paris saint germain': 'paris sg',
    'saint-etienne': 'st etienne',
}


def _normalizar(nombre: str) -> str:
    """minúsculas, sin acentos, sin puntuación redundante."""
    s = unicodedata.normalize('NFKD', str(nombre))
    s = ''.join(c for c in s if not unicodedata.combining(c)).lower().strip()
    s = re.sub(r'\b(fc|cf|cd|ud|sd|ss|as|ac|rc|rcd|ogc|losc|sco)\b', '', s)
    return re.sub(r'\s+', ' ', s).strip()


def _emparejar(nombre_u: str, equipos_fd: Dict[str, str]) -> Optional[str]:
    """Empareja un nombre de Understat con el nombre exacto de football-data."""
    norm = _normalizar(nombre_u)
    candidato = ALIAS.get(norm, norm)
    if candidato in equipos_fd:
        return equipos_fd[candidato]
    # coincidencia por inclusión (p. ej. "espanyol" en "espanol")
    import difflib
    cerca = difflib.get_close_matches(candidato, equipos_fd.keys(), n=1, cutoff=0.75)
    if cerca:
        return equipos_fd[cerca[0]]
    return None


def descargar_temporada(liga_understat: str, temporada: int,
                        forzar: bool = False) -> list:
    """Partidos con xG de una temporada. Cachea en disco (las temporadas
    pasadas nunca cambian; la actual se refresca si el caché tiene >24 h)."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    ruta = os.path.join(CACHE_DIR, f'{liga_understat}_{temporada}.json')
    if os.path.exists(ruta) and not forzar:
        edad_h = (time.time() - os.path.getmtime(ruta)) / 3600
        import datetime
        es_actual = temporada >= datetime.date.today().year - 1
        if not es_actual or edad_h < 24:
            with open(ruta, encoding='utf-8') as f:
                return json.load(f)

    s = requests.Session()
    s.headers['User-Agent'] = UA
    s.get(f'https://understat.com/league/{liga_understat}/{temporada}', timeout=20)
    time.sleep(1)
    r = s.get(f'https://understat.com/getLeagueData/{liga_understat}/{temporada}',
              headers={'X-Requested-With': 'XMLHttpRequest',
                       'Referer': f'https://understat.com/league/{liga_understat}/{temporada}'},
              timeout=30)
    r.raise_for_status()
    dates = r.json()['dates']
    jugados = [d for d in dates if d.get('isResult')]
    with open(ruta, 'w', encoding='utf-8') as f:
        json.dump(jugados, f)
    logger.info(f"[understat] {liga_understat} {temporada}: {len(jugados)} partidos con xG real.")
    time.sleep(PAUSA_SEGUNDOS)
    return jugados


def xg_de_liga(clave: str, temporadas: list) -> pd.DataFrame:
    """DataFrame [date, home_u, away_u, home_xg, away_xg] de varias temporadas."""
    liga_u = LIGAS_UNDERSTAT[clave]
    filas = []
    for t in temporadas:
        for m in descargar_temporada(liga_u, t):
            filas.append({
                'date': pd.to_datetime(m['datetime']).normalize(),
                'home_u': m['h']['title'], 'away_u': m['a']['title'],
                'home_xg': float(m['xG']['h']), 'away_xg': float(m['xG']['a']),
            })
    return pd.DataFrame(filas)


def temporadas_de_urls(urls: list) -> list:
    """Deduce los años Understat de las URLs football-data (2324 -> 2023)."""
    anios = set()
    for u in urls:
        m = re.search(r'/(\d{2})(\d{2})/', u)
        if m:
            anios.add(2000 + int(m.group(1)))
    return sorted(anios)


def inyectar_xg(df: pd.DataFrame, clave: str) -> pd.DataFrame:
    """Fusiona el xG real de Understat en el histórico de la liga.

    Empareja por (equipos normalizados + fecha ±1 día). Los partidos sin
    match conservan NaN y el generador calibrado los rellenará después.
    Cualquier fallo de red deja el df intacto (fallback sintético).
    """
    if clave not in LIGAS_UNDERSTAT:
        return df
    try:
        from config import LEAGUES
        temporadas = temporadas_de_urls(LEAGUES[clave]['urls'])
        xg = xg_de_liga(clave, temporadas)
    except Exception as e:
        logger.warning(f"[understat] {clave}: sin xG real ({e}); se usa el relleno calibrado.")
        return df
    if xg.empty:
        return df

    equipos_fd = {_normalizar(e): e for e in
                  pd.concat([df['home_team'], df['away_team']]).unique()}
    xg['home_fd'] = xg['home_u'].map(lambda n: _emparejar(n, equipos_fd))
    xg['away_fd'] = xg['away_u'].map(lambda n: _emparejar(n, equipos_fd))
    sin_mapa = sorted(set(xg.loc[xg['home_fd'].isna(), 'home_u']) |
                      set(xg.loc[xg['away_fd'].isna(), 'away_u']))
    if sin_mapa:
        logger.warning(f"[understat] {clave}: equipos sin emparejar: {sin_mapa}")
    xg = xg.dropna(subset=['home_fd', 'away_fd'])

    # índice por (home, away) -> lista de (fecha, xg_h, xg_a)
    indice: Dict = {}
    for fila in xg.itertuples(index=False):
        indice.setdefault((fila.home_fd, fila.away_fd), []).append(
            (fila.date, fila.home_xg, fila.away_xg))

    df = df.copy()
    if 'home_xg' not in df.columns:
        df['home_xg'] = float('nan')
    if 'away_xg' not in df.columns:
        df['away_xg'] = float('nan')

    enchufados = 0
    fechas = pd.to_datetime(df['date']).dt.normalize()
    for i in df.index:
        candidatos = indice.get((df.at[i, 'home_team'], df.at[i, 'away_team']))
        if not candidatos:
            continue
        f = fechas.at[i]
        mejor = min(candidatos, key=lambda c: abs((c[0] - f).days))
        if abs((mejor[0] - f).days) <= 1:
            df.at[i, 'home_xg'] = mejor[1]
            df.at[i, 'away_xg'] = mejor[2]
            enchufados += 1
    logger.info(f"[understat] {clave}: xG real inyectado en {enchufados}/{len(df)} "
                f"partidos ({enchufados/len(df)*100:.0f} %).")
    return df


if __name__ == '__main__':
    import argparse
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    parser = argparse.ArgumentParser(description='Descarga xG real de Understat.')
    parser.add_argument('--liga', required=True, choices=list(LIGAS_UNDERSTAT))
    args = parser.parse_args()
    from config import LEAGUES
    temporadas = temporadas_de_urls(LEAGUES[args.liga]['urls'])
    datos = xg_de_liga(args.liga, temporadas)
    print(datos.tail(10).to_string())
    print(f"\nTotal: {len(datos)} partidos con xG real.")
