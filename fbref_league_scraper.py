#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Scraper genérico de ligas en FBref (M5, v13) — Liga MX, LaLiga (xG), Champions.

Parametrizable por competición; extrae la tabla Scores & Fixtures (marcador,
xG de ambos equipos, fecha). ESTADO ACTUAL: FBref devuelve 403 (Cloudflare)
desde esta red — verificado el 2026-07-12 — por lo que el módulo degrada
limpiamente y las ligas siguen con football-data.co.uk. La infraestructura
queda lista para redes no bloqueadas o proxies (proxies.txt / PROXIES).
"""

import logging
import random
import time
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

COMPETICIONES_FBREF = {
    'liga_mx': (31, 'Liga-MX'),
    'laliga': (12, 'La-Liga'),
    'premier': (9, 'Premier-League'),
    'champions': (8, 'Champions-League'),
}


def scrape_fixtures(clave_liga: str, temporada: Optional[str] = None,
                    rate_limit: float = 6.0) -> pd.DataFrame:
    """
    Scores & Fixtures de una liga: date, home, away, home_goals, away_goals,
    home_xg, away_xg. DataFrame vacío si FBref no es accesible (403/red).
    """
    if clave_liga not in COMPETICIONES_FBREF:
        raise ValueError(f"Liga desconocida: {clave_liga}")
    comp_id, slug = COMPETICIONES_FBREF[clave_liga]
    sufijo = f"{temporada}/" if temporada else ""
    url = (f"https://fbref.com/en/comps/{comp_id}/{sufijo}schedule/"
           f"{slug}-Scores-and-Fixtures")
    try:
        import cloudscraper
        from fbref_scraper_v2 import USER_AGENTS, ProxyPool
        pool = ProxyPool()
        time.sleep(rate_limit + random.uniform(0.5, 2.0))
        scraper = cloudscraper.create_scraper(
            browser={'custom': random.choice(USER_AGENTS)})
        r = scraper.get(url, timeout=30, proxies=pool.siguiente())
        r.raise_for_status()
        tablas = pd.read_html(r.text)
        df = next(t for t in tablas if 'Score' in t.columns)
        df = df[df['Score'].notna() & (df['Score'].astype(str).str.contains(r'\d'))]
        goles = df['Score'].astype(str).str.extract(r'(\d+)\D+(\d+)')
        salida = pd.DataFrame({
            'date': pd.to_datetime(df['Date'], errors='coerce'),
            'home_team': df['Home'].astype(str).str.strip(),
            'away_team': df['Away'].astype(str).str.strip(),
            'home_goals': pd.to_numeric(goles[0], errors='coerce'),
            'away_goals': pd.to_numeric(goles[1], errors='coerce'),
        })
        for col_fb, col in (('xG', 'home_xg'), ('xG.1', 'away_xg')):
            if col_fb in df.columns:
                salida[col] = pd.to_numeric(df[col_fb], errors='coerce')
        salida = salida.dropna(subset=['date', 'home_goals', 'away_goals'])
        logger.info(f"FBref [{clave_liga}]: {len(salida)} partidos con marcador"
                    + (" y xG real" if 'home_xg' in salida.columns else ""))
        return salida
    except Exception as e:
        logger.warning(f"FBref [{clave_liga}] no disponible ({type(e).__name__}): "
                       f"se mantiene football-data.co.uk como fuente.")
        return pd.DataFrame()


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    print(scrape_fixtures('liga_mx').head())
