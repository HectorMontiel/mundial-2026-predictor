#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FBref scraper v3 (v22) — calendarios de la Champions League.

REALIDAD VERIFICADA (2026-07-14, ver VALIDACION_v22.md):
  - `cloudscraper` NO supera el 403 de Cloudflare de FBref desde esta red
    (el master prompt v22 asumía que sí). El módulo lo intenta igualmente
    con pausas éticas de 4-8 s y rotación de User-Agent, porque desde otras
    redes puede funcionar; si recibe 403 degrada a la caché en disco.
  - Las páginas "Scores & Fixtures" de FBref YA NO publican columnas de xG
    para Liga MX ni Champions (verificado en 2023-2024 y 2024-2025): la
    promesa de "posesión + xG masivo" del plan no existe hoy. Lo que sí dan
    es RESULTADOS completos 2017-presente, incluida la temporada en curso
    que el plan Free de API-Football bloquea.
  - La caché `fbref_cache/champions_{temporada}.psv` fue sembrada con una
    sesión de navegador real (2026-07-14). Formato por línea:
    fecha|local|goles_local|goles_visitante|visitante|ronda|notas

Los partidos con prórroga/penales (nota "Required Extra Time" / "penalties")
no traen el marcador de los 90': el fusionador los excluye del 1X2.
"""

import glob
import logging
import os
import random
import re
import time
from typing import List, Optional

import pandas as pd

logger = logging.getLogger(__name__)

DIRECTORIO_CACHE = 'fbref_cache'
COMP_CHAMPIONS = 8
PAUSA_S = (4.0, 8.0)          # pausa aleatoria entre peticiones (ética FBref)
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 13_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15',
    'Mozilla/5.0 (X11; Linux x86_64; rv:127.0) Gecko/20100101 Firefox/127.0',
]

_FILA_RE = re.compile(
    r'data-stat="date"[^>]*>(?:<a[^>]*>)?(?P<date>\d{4}-\d{2}-\d{2})', re.S)


def _ruta_cache(temporada: str) -> str:
    return os.path.join(DIRECTORIO_CACHE, f'champions_{temporada}.psv')


def descargar_schedule(temporada: str) -> Optional[str]:
    """Intenta descargar el calendario con cloudscraper. None si Cloudflare
    bloquea (esperado desde esta red) o no hay librería."""
    try:
        import cloudscraper
    except ImportError:
        logger.warning("FBref: cloudscraper no instalado.")
        return None
    url = (f'https://fbref.com/en/comps/{COMP_CHAMPIONS}/{temporada}/schedule/'
           f'{temporada}-Champions-League-Scores-and-Fixtures')
    time.sleep(random.uniform(*PAUSA_S))
    try:
        s = cloudscraper.create_scraper(
            browser={'browser': 'chrome', 'platform': 'windows', 'desktop': True})
        r = s.get(url, timeout=40, headers={'User-Agent': random.choice(USER_AGENTS)})
        if r.status_code != 200:
            logger.warning(f"FBref: HTTP {r.status_code} en {temporada} "
                           f"(Cloudflare sigue bloqueando esta red).")
            return None
        return r.text
    except Exception as e:
        logger.warning(f"FBref: {type(e).__name__}: {e}")
        return None


def _parsear_html(html: str) -> List[str]:
    """HTML del schedule -> líneas psv (mismo formato de la caché)."""
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html, 'html.parser')
    tabla = soup.select_one('table.stats_table')
    if not tabla:
        return []
    filas = []
    for tr in tabla.select('tbody tr'):
        def celda(stat):
            c = tr.select_one(f'[data-stat="{stat}"]')
            if c is None:
                return ''
            a = c.select_one('a')
            return (a or c).get_text(strip=True)
        m = re.match(r'^(\d+)–(\d+)', celda('score'))
        if not m:
            continue
        filas.append('|'.join([celda('date'), celda('home_team'), m.group(1),
                               m.group(2), celda('away_team'), celda('round'),
                               celda('notes')]))
    return filas


def actualizar_temporada(temporada: str) -> bool:
    """Refresca la caché de una temporada vía cloudscraper (si la red deja)."""
    html = descargar_schedule(temporada)
    if not html:
        return False
    filas = _parsear_html(html)
    if not filas:
        return False
    os.makedirs(DIRECTORIO_CACHE, exist_ok=True)
    with open(_ruta_cache(temporada), 'w', encoding='utf-8') as f:
        f.write('\n'.join(filas) + '\n')
    logger.info(f"FBref: {temporada} actualizada ({len(filas)} partidos).")
    return True


def temporada_actual() -> str:
    hoy = pd.Timestamp.today()
    inicio = hoy.year if hoy.month >= 6 else hoy.year - 1
    return f'{inicio}-{inicio + 1}'


def resultados_champions(refrescar_actual: bool = True) -> pd.DataFrame:
    """Todos los resultados de Champions de la caché FBref.

    Columnas: date, home_team, away_team, home_goals, away_goals, round,
    notas, prorroga (bool: el marcador NO es el de los 90').
    """
    if refrescar_actual:
        actualizar_temporada(temporada_actual())   # degrada sola si 403
    filas = []
    for ruta in sorted(glob.glob(os.path.join(DIRECTORIO_CACHE, 'champions_*.psv'))):
        with open(ruta, encoding='utf-8') as f:
            for linea in f:
                p = linea.rstrip('\n').split('|')
                if len(p) < 5 or not p[0]:
                    continue
                notas = p[6] if len(p) > 6 else ''
                filas.append({
                    'date': p[0], 'home_team': p[1], 'away_team': p[4],
                    'home_goals': float(p[2]), 'away_goals': float(p[3]),
                    'round': p[5] if len(p) > 5 else '', 'notas': notas,
                    'prorroga': ('Extra Time' in notas) or ('penalt' in notas.lower()),
                })
    df = pd.DataFrame(filas)
    if df.empty:
        return df
    df['date'] = pd.to_datetime(df['date'])
    df = df.drop_duplicates(subset=['date', 'home_team', 'away_team'])
    return df.sort_values('date').reset_index(drop=True)


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    df = resultados_champions()
    print(f"{len(df)} partidos en caché FBref "
          f"({df['date'].min().date()} → {df['date'].max().date()}); "
          f"con prórroga/penales: {int(df['prorroga'].sum())}")
