#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Cuotas 1X2 del Mundial desde Betexplorer (v14/M10) — gratuito, sin clave.

Betexplorer solo sirve en HTML estático la lista de PARTIDOS DEL DÍA (el
detalle por torneo carga vía JS), así que este scraper:
  1. Baja esa lista (una sola petición, robots.txt lo permite).
  2. Se queda con los partidos donde AMBOS equipos son selecciones del
     Mundial (mapeo nombre inglés -> código FIFA).
  3. En días de partido del Mundial eso captura exactamente las cuotas que
     el parlay necesita; el resto de días devuelve vacío sin coste.

Ética: 1 petición por corrida, User-Agent real, sin paralelismo.
"""

import logging
from typing import Dict, List

import pandas as pd
import requests

from config import TEAMS, NAME_EN_TO_FIFA

logger = logging.getLogger(__name__)

URL = 'https://www.betexplorer.com/football/world/world-cup/fixtures/'
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/126.0 Safari/537.36')
# UAs alternativos para rotar ante un 429 (v41 §resiliencia)
UAS = [UA,
       ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 '
        '(KHTML, like Gecko) Version/17.0 Safari/605.1.15'),
       ('Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0')]


def _get(url: str, intentos: int = 3, timeout: int = 25):
    """GET con reintento y backoff ante 429/5xx (v41). Rota User-Agent. Ético:
    espera creciente, no martillea. Devuelve el Response o lanza la última
    excepción para que el llamador la registre y degrade a la siguiente
    fuente de la cadena de resiliencia."""
    import time
    ultima = None
    for i in range(intentos):
        try:
            r = requests.get(url, headers={'User-Agent': UAS[i % len(UAS)],
                                           'Accept-Language': 'en-US,en;q=0.9'},
                             timeout=timeout)
            if r.status_code == 429 or r.status_code >= 500:
                ultima = requests.HTTPError(f"{r.status_code} en {url}")
                time.sleep(2 * (i + 1))          # 2 s, 4 s, 6 s
                continue
            r.raise_for_status()
            return r
        except Exception as e:
            ultima = e
            time.sleep(1.5 * (i + 1))
    raise ultima if ultima else RuntimeError(f"GET falló: {url}")

# nombres Betexplorer -> inglés estándar (solo donde difieren)
BETEXPLORER_ALIAS = {
    'South Korea': 'South Korea', 'Korea Republic': 'South Korea',
    'USA': 'United States', 'Ivory Coast': 'Ivory Coast',
    'Cape Verde': 'Cabo Verde',
}


def _a_fifa(nombre: str):
    n = BETEXPLORER_ALIAS.get(nombre.strip(), nombre.strip())
    return NAME_EN_TO_FIFA.get(n)


# ---------------------------------------------------------------------------
# v31 (§4): tenis y baloncesto. VERIFICADO 2026-07-22: las URLs del spec
# (/tennis/matches-today/) devuelven la página de FÚTBOL; la ruta real es
# /next/{deporte}/ (tabla con spans --home/--away y botones data-odd).
# ---------------------------------------------------------------------------
URL_NEXT = 'https://www.betexplorer.com/next/{}/'


def _partidos_next(deporte: str, filtro_href: str = '') -> List[Dict]:
    """Partidos próximos de Betexplorer con cuotas medias (2 vías)."""
    from bs4 import BeautifulSoup
    try:
        r = _get(URL_NEXT.format(deporte))
    except Exception as e:
        logger.warning(f"[betexplorer/{deporte}] no disponible: {e}")
        return []
    soup = BeautifulSoup(r.text, 'lxml')
    out = []
    for tr in soup.select('tr'):
        odds = [b.get('data-odd') for b in tr.select('button[data-odd]')]
        a = tr.select_one('a.table-main__teamsLink')
        if not a or len(odds) < 2:
            continue
        href = a.get('href') or ''
        if filtro_href and filtro_href not in href:
            continue
        h = a.select_one('.table-main__teamLine--home')
        v = a.select_one('.table-main__teamLine--away')
        if not h or not v:
            continue
        try:
            o1, o2 = float(odds[0]), float(odds[1])
        except (TypeError, ValueError):
            continue
        out.append({'home': h.get_text(strip=True), 'away': v.get_text(strip=True),
                    'odd_home': o1, 'odd_away': o2, 'href': href})
    logger.info(f"[betexplorer/{deporte}] {len(out)} partidos"
                + (f" (filtro '{filtro_href}')" if filtro_href else ''))
    return out


def cuotas_tenis_hoy(solo_atp: bool = True) -> List[Dict]:
    """Partidos de tenis próximos con cuotas. Por defecto solo ATP (el modelo
    está entrenado con ATP; los ITF/Challenger tienen otro nivel)."""
    return _partidos_next('tennis', 'atp-single' if solo_atp else '')


def cuotas_baloncesto_hoy(solo_nba: bool = True) -> List[Dict]:
    """Partidos de baloncesto próximos con cuotas (por defecto solo NBA)."""
    return _partidos_next('basketball', '/nba/' if solo_nba else '')


def normalizar_nombre(nombre: str) -> str:
    """Normaliza a 'apellido i.' (minúsculas, sin tildes) para el fuzzy."""
    import unicodedata
    n = unicodedata.normalize('NFKD', str(nombre))
    n = ''.join(c for c in n if not unicodedata.combining(c))
    return ' '.join(n.lower().replace('.', ' ').split())


_CACHE_FUZZY: Dict[str, str] = {}


def emparejar_jugador(nombre: str, catalogo: List[str],
                      umbral: float = 0.75):
    """Cruza un nombre de Betexplorer con el catálogo del dataset ATP.
    Devuelve el nombre del catálogo o None (el llamador lo manda a la
    Capa 2 con aviso, nunca lo descarta en silencio — §4.2)."""
    from difflib import SequenceMatcher
    if nombre in _CACHE_FUZZY:
        return _CACHE_FUZZY[nombre]
    objetivo = normalizar_nombre(nombre)
    mejor, ratio = None, 0.0
    for c in catalogo:
        s = SequenceMatcher(None, objetivo, normalizar_nombre(c)).ratio()
        if s > ratio:
            mejor, ratio = c, s
    resultado = mejor if ratio >= umbral else None
    _CACHE_FUZZY[nombre] = resultado
    return resultado


def cuotas_mundial_hoy() -> pd.DataFrame:
    """Partidos del Mundial de HOY con cuotas 1X2 medias de Betexplorer.

    Devuelve DataFrame [MATCH_ID, odd_home, odd_draw, odd_away] (vacío si
    hoy no juega ninguna selección o si la web no responde).
    """
    try:
        from bs4 import BeautifulSoup
        r = _get(URL)
        soup = BeautifulSoup(r.text, 'lxml')
        filas: List[Dict] = []
        hoy = pd.Timestamp.today().normalize()
        for cont in soup.select('li.table-main__tournamentLiContent'):
            equipos_el = cont.select_one('.table-main__participants')
            odds = [b.get('data-odd') for b in cont.select('button[data-odd]')]
            if equipos_el is None or len(odds) < 3:
                continue
            texto = equipos_el.get_text(' ', strip=True)
            if ' - ' not in texto:
                continue
            nombre_h, nombre_a = [p.strip() for p in texto.split(' - ', 1)]
            home, away = _a_fifa(nombre_h), _a_fifa(nombre_a)
            if home not in TEAMS or away not in TEAMS:
                continue           # no es un partido del Mundial
            filas.append({
                'MATCH_ID': f"{hoy.strftime('%Y%m%d')}_{home}_{away}",
                'odd_home': float(odds[0]), 'odd_draw': float(odds[1]),
                'odd_away': float(odds[2]),
            })
        logger.info(f"Betexplorer: {len(filas)} partidos del Mundial hoy con cuotas.")
        return pd.DataFrame(filas)
    except Exception as e:
        logger.warning(f"Betexplorer no disponible ({e}): sin cuotas del Mundial hoy.")
        return pd.DataFrame()


def _normalizar_club(nombre: str) -> str:
    import re
    import unicodedata
    s = unicodedata.normalize('NFKD', str(nombre))
    s = ''.join(c for c in s if not unicodedata.combining(c)).lower().strip()
    s = re.sub(r'[^\w\s]', ' ', s)
    return re.sub(r'\s+', ' ', s).strip()


def _claves_disponibles():
    """v50: TODAS las ligas de clubes con modelo disponible (no solo las 8
    europeas). Así las ligas EN TEMPORADA de verano (Brasil, Argentina, MLS,
    China, nórdicas) también obtienen cuotas 1X2 reales de Betexplorer y sus
    picks pasan de Capa 2 (sin cuota) a Capa 1 (con EV validado)."""
    try:
        from config import LEAGUES
        return tuple(c for c, cfg in LEAGUES.items()
                     if cfg.get('disponible') and cfg.get('formato') != 'espn'
                     and cfg.get('formato') != 'api_football')
    except Exception:
        return ('liga_mx', 'premier', 'laliga', 'serie_a', 'bundesliga',
                'ligue_1', 'eredivisie', 'primeira')


def cuotas_clubes_hoy(claves=None) -> pd.DataFrame:
    """Cuotas 1X2 de HOY para partidos de nuestras ligas de clubes (v18/M2,
    ampliado en v50 a todas las ligas disponibles).

    La página diaria de Betexplorer lista todos los partidos del día con
    cuotas; se emparejan los equipos contra team_stats_{liga}.json (fuzzy,
    cutoff alto para evitar falsos positivos). Es la única fuente gratuita de
    cuotas EN VIVO para Liga MX (fixtures.csv no la cubre). 1 petición.
    """
    if claves is None:
        claves = _claves_disponibles()
    import difflib
    import json as _json
    import os as _os

    indices = {}
    for clave in claves:
        ruta = f'team_stats_{clave}.json'
        if not _os.path.exists(ruta):
            continue
        with open(ruta, encoding='utf-8') as f:
            equipos = list(_json.load(f).get('equipos', {}).keys())
        indices[clave] = {_normalizar_club(e): e for e in equipos}

    def emparejar(nombre):
        norm = _normalizar_club(nombre)
        for indice in indices.values():
            if norm in indice:
                return indice[norm]
            cerca = difflib.get_close_matches(norm, indice.keys(), n=1, cutoff=0.85)
            if cerca:
                return indice[cerca[0]]
        return None

    try:
        from bs4 import BeautifulSoup
        r = _get(URL)
        soup = BeautifulSoup(r.text, 'lxml')
        filas: List[Dict] = []
        hoy = pd.Timestamp.today().normalize()
        for cont in soup.select('li.table-main__tournamentLiContent'):
            equipos_el = cont.select_one('.table-main__participants')
            odds = [b.get('data-odd') for b in cont.select('button[data-odd]')]
            if equipos_el is None or len(odds) < 3:
                continue
            texto = equipos_el.get_text(' ', strip=True)
            if ' - ' not in texto:
                continue
            nombre_h, nombre_a = [p.strip() for p in texto.split(' - ', 1)]
            home, away = emparejar(nombre_h), emparejar(nombre_a)
            if not home or not away:
                continue
            filas.append({
                'MATCH_ID': f"{hoy.strftime('%Y%m%d')}_{home.replace(' ', '-')}_{away.replace(' ', '-')}",
                'odd_home': float(odds[0]), 'odd_draw': float(odds[1]),
                'odd_away': float(odds[2]),
            })
        logger.info(f"Betexplorer: {len(filas)} partidos de clubes hoy con cuotas.")
        return pd.DataFrame(filas)
    except Exception as e:
        logger.warning(f"Betexplorer clubes no disponible ({e}).")
        return pd.DataFrame()


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    df = cuotas_mundial_hoy()
    if not df.empty:
        print(df.to_string())
    df2 = cuotas_clubes_hoy()
    if not df2.empty:
        print(df2.to_string())
