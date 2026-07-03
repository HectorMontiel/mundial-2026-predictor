#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Scraper FBref v2 — fuente única de verdad.

Mejoras sobre la v1:
  * Rotación de User-Agents en cada petición.
  * Soporte de proxies residenciales (archivo `proxies.txt` o variable de
    entorno `PROXIES`, una URL http(s)://usuario:pass@host:puerto por línea
    o separadas por comas). Rotación round-robin con descarte de proxies
    muertos.
  * Reintentos con backoff exponencial + jitter.
  * Ventana histórica de 5 años de partidos internacionales oficiales.
  * Columnas ampliadas: posesión, remates totales, faltas, córners.
  * Conversión al esquema de partido (home_/away_) compatible con el
    pipeline de entrenamiento, deduplicando las dos perspectivas.
"""

import os
import time
import random
import logging
from typing import Dict, List, Optional

import cloudscraper
import pandas as pd
from bs4 import BeautifulSoup

from config import TEAMS

logger = logging.getLogger(__name__)

USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 14.4; rv:125.0) Gecko/20100101 Firefox/125.0',
]

MAPEO_NOMBRES_FBREF = {
    'Mexico': 'MEX', 'United-States': 'USA', 'Canada': 'CAN',
    'Argentina': 'ARG', 'Brazil': 'BRA', 'Uruguay': 'URU',
    'Colombia': 'COL', 'Ecuador': 'ECU', 'Peru': 'PER',
    'Chile': 'CHI', 'France': 'FRA', 'England': 'ENG',
    'Spain': 'ESP', 'Germany': 'GER', 'Italy': 'ITA',
    'Portugal': 'POR', 'Netherlands': 'NED', 'Belgium': 'BEL',
    'Croatia': 'CRO', 'Serbia': 'SRB', 'Morocco': 'MAR',
    'Senegal': 'SEN', 'Cameroon': 'CMR', 'Ghana': 'GHA',
    'Nigeria': 'NGA', 'Tunisia': 'TUN', 'Algeria': 'ALG',
    'Egypt': 'EGY', 'Japan': 'JPN', 'South-Korea': 'KOR',
    'Iran': 'IRN', 'Australia': 'AUS', 'Saudi-Arabia': 'KSA',
    'Qatar': 'QAT', 'Costa-Rica': 'CRC', 'Panama': 'PAN',
    'Honduras': 'HON', 'Jamaica': 'JAM',
}
# Mapeo inverso: nombre en inglés (como aparece en la columna Opponent) -> FIFA
MAPEO_OPPONENT = {k.replace('-', ' '): v for k, v in MAPEO_NOMBRES_FBREF.items()}

TORNEOS_OFICIALES = (
    'World Cup', 'WCQ', 'Qual', 'Copa América', 'Copa America', 'Euro',
    'Nations League', 'Gold Cup', 'AFCON', 'Africa Cup', 'Asian Cup',
    'Confederations',
)


class ProxyPool:
    """Pool round-robin de proxies residenciales con descarte de muertos."""

    def __init__(self, archivo: str = 'proxies.txt'):
        self.proxies: List[str] = []
        env = os.environ.get('PROXIES', '')
        if env:
            self.proxies.extend(p.strip() for p in env.split(',') if p.strip())
        if os.path.exists(archivo):
            with open(archivo, 'r', encoding='utf-8') as f:
                self.proxies.extend(
                    line.strip() for line in f
                    if line.strip() and not line.startswith('#')
                )
        self._i = 0
        if self.proxies:
            logger.info(f"ProxyPool: {len(self.proxies)} proxies cargados.")
        else:
            logger.info("ProxyPool: sin proxies configurados (conexión directa).")

    def siguiente(self) -> Optional[Dict[str, str]]:
        if not self.proxies:
            return None
        proxy = self.proxies[self._i % len(self.proxies)]
        self._i += 1
        return {'http': proxy, 'https': proxy}

    def descartar(self, proxy_dict: Optional[Dict[str, str]]):
        if not proxy_dict:
            return
        url = proxy_dict.get('https') or proxy_dict.get('http')
        if url in self.proxies:
            self.proxies.remove(url)
            logger.warning(f"Proxy muerto descartado ({len(self.proxies)} restantes).")


class FBrefScraperV2:
    """Scraper resiliente de partidos internacionales (últimos 5 años)."""

    NATIONS_URL = "https://fbref.com/en/squads/nations/"

    def __init__(self, rate_limit: float = 4.0, max_reintentos: int = 4):
        self.rate_limit = rate_limit
        self.max_reintentos = max_reintentos
        self.proxy_pool = ProxyPool()
        self.team_urls: Dict[str, str] = {}
        self._nuevo_scraper()

    def _nuevo_scraper(self):
        """Recrea la sesión cloudscraper con un User-Agent aleatorio."""
        ua = random.choice(USER_AGENTS)
        self.scraper = cloudscraper.create_scraper(browser={'custom': ua})

    def _respetar_rate_limit(self):
        time.sleep(self.rate_limit + random.uniform(0.5, 3.0))

    def _fetch_soup(self, url: str) -> Optional[BeautifulSoup]:
        """GET con rotación de UA/proxy y backoff exponencial + jitter."""
        for intento in range(self.max_reintentos):
            proxy = self.proxy_pool.siguiente()
            try:
                self._nuevo_scraper()  # UA nuevo en cada intento
                resp = self.scraper.get(url, timeout=30, proxies=proxy)
                if resp.status_code == 200:
                    return BeautifulSoup(resp.content, 'lxml')
                if resp.status_code == 429:
                    espera = min(300, (2 ** intento) * 30 + random.uniform(0, 10))
                    logger.warning(f"429 en {url}. Backoff {espera:.0f}s...")
                    time.sleep(espera)
                elif resp.status_code in (403, 503):
                    logger.warning(f"HTTP {resp.status_code} (Cloudflare) en {url}. Rotando identidad...")
                    self.proxy_pool.descartar(proxy)
                    time.sleep((2 ** intento) * 5 + random.uniform(0, 5))
                else:
                    logger.error(f"HTTP {resp.status_code} en {url}")
                    time.sleep(5)
            except Exception as e:
                logger.error(f"Error de red (intento {intento + 1}/{self.max_reintentos}): {e}")
                self.proxy_pool.descartar(proxy)
                time.sleep((2 ** intento) * 5 + random.uniform(0, 5))
        return None

    # ------------------------------------------------------------------ #
    # Descubrimiento de selecciones                                        #
    # ------------------------------------------------------------------ #
    def load_nation_links(self) -> bool:
        soup = self._fetch_soup(self.NATIONS_URL)
        if not soup:
            return False
        table = soup.find('table', id='nations')
        if not table:
            logger.error("Tabla de naciones no encontrada.")
            return False
        for fila in table.find('tbody').find_all('tr'):
            celdas = fila.find_all('td')
            if not celdas:
                continue
            enlace = celdas[0].find('a')
            if enlace and 'href' in enlace.attrs:
                href = enlace['href']
                codigo = href.split('/')[-1].replace('-Stats', '')
                codigo_fifa = MAPEO_NOMBRES_FBREF.get(codigo, codigo.upper()[:3])
                self.team_urls[codigo_fifa] = f"https://fbref.com{href}"
        logger.info(f"Cargadas {len(self.team_urls)} selecciones desde FBref.")
        return len(self.team_urls) > 0

    # ------------------------------------------------------------------ #
    # Scraping de partidos por selección (5 años, torneos oficiales)      #
    # ------------------------------------------------------------------ #
    def scrape_team_matches(self, team_code: str, years_back: int = 5) -> pd.DataFrame:
        if team_code not in self.team_urls:
            logger.error(f"URL no disponible para {team_code}.")
            return pd.DataFrame()
        self._respetar_rate_limit()
        soup = self._fetch_soup(self.team_urls[team_code])
        if not soup:
            return pd.DataFrame()
        table = soup.find('table', id='matchlogs_for')
        if not table:
            logger.error(f"Tabla de partidos no encontrada para {team_code}")
            return pd.DataFrame()
        try:
            df = pd.read_html(str(table), header=1)[0]
        except Exception as e:
            logger.error(f"Error al parsear tabla de {team_code}: {e}")
            return pd.DataFrame()

        df.columns = ['_'.join(c).strip() if isinstance(c, tuple) else c for c in df.columns.values]
        df = df[df['Date'].notna() & (df['Date'] != 'Date')].copy()
        df['Date'] = pd.to_datetime(df['Date'], errors='coerce')
        df = df.dropna(subset=['Date'])
        cutoff = pd.Timestamp.today() - pd.DateOffset(years=years_back)
        df = df[df['Date'] >= cutoff]
        if df.empty:
            return df

        col_map = {
            'Date': 'date', 'Comp': 'tournament', 'Round': 'round',
            'Venue': 'venue', 'Opponent': 'opponent',
            'GF': 'goals_for', 'GA': 'goals_against',
            'Poss': 'possession', 'SoT': 'shots_on_target',
            'Sh': 'shots_total', 'Fls': 'fouls', 'CK': 'corners',
            'CrdY': 'yellow_cards', 'CrdR': 'red_cards',
            'xG': 'xG_for', 'xGA': 'xG_against',
        }
        df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})

        # Solo torneos oficiales (eliminatorias, copas, mundial); excluir amistosos
        if 'tournament' in df.columns:
            oficial = df['tournament'].astype(str).str.contains(
                '|'.join(TORNEOS_OFICIALES), case=False, na=False)
            if oficial.any():
                df = df[oficial]

        df['team'] = team_code
        df['home_away'] = df['venue'].apply(lambda x: 'home' if str(x).strip() == 'Home' else 'away')
        df['opponent_fifa'] = df['opponent'].astype(str).str.strip().map(
            lambda x: MAPEO_OPPONENT.get(x, x.upper()[:3]))

        for c in ['goals_for', 'goals_against', 'possession', 'shots_total',
                  'shots_on_target', 'fouls', 'corners', 'yellow_cards',
                  'red_cards', 'xG_for', 'xG_against']:
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0)
            else:
                df[c] = 0.0

        logger.info(f"{team_code}: {len(df)} partidos oficiales scrapeados.")
        return df

    # ------------------------------------------------------------------ #
    # Conversión al esquema de partido del pipeline                        #
    # ------------------------------------------------------------------ #
    @staticmethod
    def to_match_schema(team_logs: pd.DataFrame) -> pd.DataFrame:
        """
        Convierte los logs por-equipo de FBref al esquema home_/away_ del
        histórico, deduplicando las dos perspectivas del mismo partido.
        """
        if team_logs.empty:
            return pd.DataFrame()
        filas = []
        for _, r in team_logs.iterrows():
            if r['home_away'] == 'home':
                home, away = r['team'], r['opponent_fifa']
                g_h, g_a = r['goals_for'], r['goals_against']
                xg_h, xg_a = r['xG_for'], r['xG_against']
                sot_h, sh_h = r['shots_on_target'], r['shots_total']
                pos_h = r['possession']
                fl_h, ck_h = r['fouls'], r['corners']
                am_h, rj_h = r['yellow_cards'], r['red_cards']
                sot_a = sh_a = pos_a = fl_a = ck_a = am_a = rj_a = None
            else:
                home, away = r['opponent_fifa'], r['team']
                g_h, g_a = r['goals_against'], r['goals_for']
                xg_h, xg_a = r['xG_against'], r['xG_for']
                sot_a, sh_a = r['shots_on_target'], r['shots_total']
                pos_a = r['possession']
                fl_a, ck_a = r['fouls'], r['corners']
                am_a, rj_a = r['yellow_cards'], r['red_cards']
                sot_h = sh_h = pos_h = fl_h = ck_h = am_h = rj_h = None
            fecha = pd.to_datetime(r['date'])
            filas.append({
                'MATCH_ID': f"{fecha.strftime('%Y%m%d')}_{home}_{away}",
                'date': fecha.date(), 'home_team': home, 'away_team': away,
                'home_goals': g_h, 'away_goals': g_a,
                'home_xg': xg_h, 'away_xg': xg_a,
                'home_shots_on': sot_h, 'away_shots_on': sot_a,
                'home_shots_off': (sh_h - sot_h) if sh_h is not None and sot_h is not None else None,
                'away_shots_off': (sh_a - sot_a) if sh_a is not None and sot_a is not None else None,
                'home_possession': pos_h, 'away_possession': pos_a,
                'home_fouls': fl_h, 'away_fouls': fl_a,
                'home_yellow': am_h, 'away_yellow': am_a,
                'home_red': rj_h, 'away_red': rj_a,
                'home_corners': ck_h, 'away_corners': ck_a,
                'stadium': None, 'tournament': r.get('tournament', 'Oficial'),
            })
        df = pd.DataFrame(filas)
        # Fusionar las dos perspectivas del mismo MATCH_ID (cada una aporta
        # las estadísticas de su equipo) y rellenar el resto con la mediana.
        df = df.groupby('MATCH_ID', as_index=False).first().combine_first(
            df.groupby('MATCH_ID', as_index=False).last()
        )
        numericas = df.select_dtypes(include='number').columns
        df[numericas] = df[numericas].fillna(df[numericas].median())
        return df.sort_values('date').reset_index(drop=True)

    def build_full_historical_dataset(self, years_back: int = 5) -> pd.DataFrame:
        """Scrapea las 38 selecciones y devuelve el histórico en esquema de partido."""
        logs = []
        for team in TEAMS:
            try:
                df = self.scrape_team_matches(team, years_back)
                if not df.empty:
                    logs.append(df)
            except Exception as e:
                logger.error(f"Error scrapeando {team}: {e}")
            time.sleep(random.uniform(0.5, 1.5))
        if not logs:
            return pd.DataFrame()
        return self.to_match_schema(pd.concat(logs, ignore_index=True))
