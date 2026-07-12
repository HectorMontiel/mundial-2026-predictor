#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Orquestador TOTAL de la plataforma (v14/M13) — un solo comando actualiza todo.

Secuencia:
  1. Mundial: pipeline base (Kaggle) + fuentes en vivo (API-Football/ESPN).
  2. Ligas de clubes: re-descarga football-data.co.uk y reentrena cada liga.
  3. Cuotas: The Odds API (con clave) / Betexplorer (Mundial, días de partido)
     + fixtures.csv (clubes) -> odds_actuales.json para el parlay.
  4. Inteligencia de mercado (Polymarket) -> risk_flags.json.
  5. Valores de plantilla Transfermarkt (SOLO con --ratings; experimental,
     no alimenta modelos — ver VALIDACION_v14.md).

Uso:
    python pipeline_total.py                # todo menos ratings
    python pipeline_total.py --solo-mundial # solo pasos 1, 3 y 4
    python pipeline_total.py --solo-clubes  # solo pasos 2 y 3
    python pipeline_total.py --ratings      # añade el paso 5

Programación (Windows, días de partido):
    schtasks /create /tn "PlataformaTotal" /tr "...\.venv\Scripts\python.exe ...\pipeline_total.py" /sc daily /st 07:00
"""

import argparse
import logging
import subprocess
import sys

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger('pipeline_total')

PYTHON = sys.executable


def paso(nombre: str, funcion) -> bool:
    """Ejecuta un paso con aislamiento de errores: un fallo no detiene el resto."""
    logger.info(f"{'='*20} {nombre} {'='*20}")
    try:
        funcion()
        return True
    except Exception as e:
        logger.error(f"[{nombre}] falló: {type(e).__name__}: {e} — se continúa.")
        return False


def actualizar_mundial():
    subprocess.run([PYTHON, 'pipeline_mundial.py', '--live'], check=True)


def actualizar_clubes():
    subprocess.run([PYTHON, 'league_engine.py', '--build'], check=True)


def actualizar_cuotas():
    import fetch_odds
    fetch_odds.actualizar_odds()


def actualizar_mercado():
    import market_intelligence
    from prediction_api import PredictionEngine
    market_intelligence.actualizar(PredictionEngine())


def actualizar_ratings():
    import transfermarkt_scraper as tm
    for clave in tm.LIGAS_TM:
        tm.valores_liga(clave)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Actualiza toda la plataforma con fuentes gratuitas.')
    parser.add_argument('--solo-mundial', action='store_true')
    parser.add_argument('--solo-clubes', action='store_true')
    parser.add_argument('--ratings', action='store_true',
                        help='Descarga también valores de plantilla Transfermarkt (experimental).')
    args = parser.parse_args()

    resultados = {}
    if not args.solo_clubes:
        resultados['Mundial'] = paso('MUNDIAL (Kaggle + en vivo)', actualizar_mundial)
    if not args.solo_mundial:
        resultados['Clubes'] = paso('LIGAS DE CLUBES (football-data)', actualizar_clubes)
    resultados['Cuotas'] = paso('CUOTAS (fixtures.csv / Betexplorer / Odds API)', actualizar_cuotas)
    if not args.solo_clubes:
        resultados['Mercado'] = paso('INTELIGENCIA DE MERCADO (Polymarket)', actualizar_mercado)
    if args.ratings:
        resultados['Ratings'] = paso('TRANSFERMARKT (--ratings)', actualizar_ratings)

    logger.info('=' * 55)
    for nombre, ok in resultados.items():
        logger.info(f"  {'OK ' if ok else 'FALLO'}  {nombre}")
    if not all(resultados.values()):
        sys.exit(1)
