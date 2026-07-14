#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Colector de alineaciones confirmadas en MODO SOMBRA (v19).

Fuente: JSON público de ESPN (site.api.espn.com) — la misma que ya usamos
para resultados en vivo del Mundial (v14/M7). El endpoint `summary` publica
los rosters con el once titular (verificado: FRA-MAR del Mundial devolvió
26 jugadores por equipo con 11 titulares y posición).

MODO SOMBRA: solo ACUMULA datos en alineaciones_historicas.csv — no toca
las predicciones. Al cierre de la temporada 2026-27 se evaluará si las
features de alineación (p. ej. calidad media de los titulares) mejoran el
backtest (plan en VALIDACION_v19.md; evaluación en VALIDACION_v20.md).

Uso:
    python lineup_collector.py                 # partidos de hoy (todas las ligas)
    python lineup_collector.py --fecha 20260714
    python lineup_collector.py --dias-atras 7  # backfill de la última semana

Programación diaria (junto al pipeline): se engancha como paso opcional de
pipeline_total.py. 1 petición por liga/día + 1 por partido encontrado.
"""

import argparse
import logging
import os
import time
from typing import List, Optional

import pandas as pd
import requests

logger = logging.getLogger(__name__)

ARCHIVO = 'alineaciones_historicas.csv'
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'
BASE = 'https://site.api.espn.com/apis/site/v2/sports/soccer'
PAUSA = 2  # segundos entre partidos

# clave de liga propia -> código de liga en ESPN
LIGAS_ESPN = {
    'mundial': 'fifa.world',
    'premier': 'eng.1', 'laliga': 'esp.1', 'serie_a': 'ita.1',
    'bundesliga': 'ger.1', 'ligue_1': 'fra.1', 'eredivisie': 'ned.1',
    'primeira': 'por.1', 'liga_mx': 'mex.1',
}


def _eventos_del_dia(codigo_espn: str, fecha: str) -> List[dict]:
    r = requests.get(f'{BASE}/{codigo_espn}/scoreboard',
                     params={'dates': fecha, 'limit': 50},
                     headers={'User-Agent': UA}, timeout=20)
    r.raise_for_status()
    return r.json().get('events', [])


def _alineacion_evento(codigo_espn: str, event_id: str) -> List[dict]:
    r = requests.get(f'{BASE}/{codigo_espn}/summary',
                     params={'event': event_id},
                     headers={'User-Agent': UA}, timeout=20)
    r.raise_for_status()
    filas = []
    for lado in r.json().get('rosters', []):
        equipo = lado.get('team', {}).get('displayName', '?')
        for j in lado.get('roster', []):
            filas.append({
                'equipo': equipo,
                'lado': lado.get('homeAway'),
                'jugador': j.get('athlete', {}).get('displayName'),
                'posicion': (j.get('position') or {}).get('abbreviation'),
                'titular': bool(j.get('starter')),
                # v20: para estimar minutos (90 titular completo / ~70 si
                # sale / ~25 suplente que entra / 0 resto)
                'entro': bool(j.get('subbedIn')),
                'salio': bool(j.get('subbedOut')),
            })
    return filas


def recolectar(fecha: Optional[str] = None, ligas=None) -> int:
    """Recolecta alineaciones de un día. Devuelve nº de partidos nuevos."""
    fecha = fecha or pd.Timestamp.today().strftime('%Y%m%d')
    ligas = ligas or list(LIGAS_ESPN)

    previos = set()
    if os.path.exists(ARCHIVO):
        try:
            previos = set(pd.read_csv(ARCHIVO)['event_id'].astype(str))
        except Exception:
            pass

    nuevos = []
    for clave in ligas:
        codigo = LIGAS_ESPN[clave]
        try:
            eventos = _eventos_del_dia(codigo, fecha)
        except Exception as e:
            logger.warning(f"[alineaciones] {clave}: scoreboard no disponible ({e}).")
            continue
        for ev in eventos:
            if str(ev['id']) in previos:
                continue
            try:
                jugadores = _alineacion_evento(codigo, ev['id'])
            except Exception as e:
                logger.warning(f"[alineaciones] {clave}/{ev.get('name')}: {e}")
                continue
            titulares = [j for j in jugadores if j['titular']]
            if not titulares:
                continue    # alineación aún no publicada (se reintenta luego)
            for j in jugadores:
                nuevos.append({
                    'event_id': str(ev['id']), 'liga': clave,
                    'fecha': pd.to_datetime(ev['date']).strftime('%Y-%m-%d'),
                    'partido': ev.get('name', ''), **j,
                })
            time.sleep(PAUSA)

    if not nuevos:
        logger.info(f"[alineaciones] {fecha}: sin alineaciones nuevas.")
        return 0
    df = pd.DataFrame(nuevos)
    df.to_csv(ARCHIVO, mode='a', index=False,
              header=not os.path.exists(ARCHIVO), encoding='utf-8')
    n_partidos = df['event_id'].nunique()
    logger.info(f"[alineaciones] {fecha}: {n_partidos} partidos, "
                f"{len(df)} filas añadidas a {ARCHIVO} (modo sombra).")
    return n_partidos


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    parser = argparse.ArgumentParser(description='Colector de alineaciones (modo sombra).')
    parser.add_argument('--fecha', help='AAAAMMDD (por defecto: hoy)')
    parser.add_argument('--dias-atras', type=int, default=0,
                        help='backfill: recolectar también los N días previos')
    args = parser.parse_args()
    base = pd.Timestamp(args.fecha) if args.fecha else pd.Timestamp.today()
    total = 0
    for d in range(args.dias_atras, -1, -1):
        total += recolectar((base - pd.Timedelta(days=d)).strftime('%Y%m%d'))
    print(f"Total: {total} partidos recolectados.")
