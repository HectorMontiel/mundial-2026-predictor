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

# nombres Betexplorer -> inglés estándar (solo donde difieren)
BETEXPLORER_ALIAS = {
    'South Korea': 'South Korea', 'Korea Republic': 'South Korea',
    'USA': 'United States', 'Ivory Coast': 'Ivory Coast',
    'Cape Verde': 'Cabo Verde',
}


def _a_fifa(nombre: str):
    n = BETEXPLORER_ALIAS.get(nombre.strip(), nombre.strip())
    return NAME_EN_TO_FIFA.get(n)


def cuotas_mundial_hoy() -> pd.DataFrame:
    """Partidos del Mundial de HOY con cuotas 1X2 medias de Betexplorer.

    Devuelve DataFrame [MATCH_ID, odd_home, odd_draw, odd_away] (vacío si
    hoy no juega ninguna selección o si la web no responde).
    """
    try:
        from bs4 import BeautifulSoup
        r = requests.get(URL, headers={'User-Agent': UA}, timeout=25)
        r.raise_for_status()
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


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    df = cuotas_mundial_hoy()
    if not df.empty:
        print(df.to_string())
