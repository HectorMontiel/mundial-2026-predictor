#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v70 · Fase 1 — Auditoría de cobertura de `rosters` de ESPN.

Antes de escribir una línea de `lineup_impact.py` hay que responder a la
pregunta que hundió las features de saque en v69: **¿qué porcentaje de los
partidos del histórico tendría alineación con estadística por jugador?**

Mide, por liga y por temporada:
  · partidos del scoreboard de ESPN con `rosters`
  · de esos, cuántos traen `starter` marcado (alineación titular)
  · cuántos traen estadística por jugador (SHOT/SOG/G/A)
  · cuántos traen estadística de PORTERO (SV = saves, GA = goles encajados)
  · % de los partidos del histórico local emparejables por fecha

Salida: `_v70_fase1_rosters.json`
"""
import json
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import requests

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

BASE = 'https://site.api.espn.com/apis/site/v2/sports/soccer/{liga}'
UA = {'User-Agent': 'Mozilla/5.0'}
TRAMO = 55          # ESPN devuelve 400 con rangos largos en futbol


def _get(url, params, reintentos=3):
    for i in range(reintentos):
        try:
            r = requests.get(url, params=params, headers=UA, timeout=25)
            if r.status_code == 400 and i == 0:
                return None
            r.raise_for_status()
            return r.json()
        except Exception:
            time.sleep(1.2 * (i + 1))
    return None


def eventos(liga, ini, fin):
    """IDs de partidos terminados en [ini, fin], troceando en tramos de 55d."""
    out = []
    cur = pd.Timestamp(ini)
    fin = pd.Timestamp(fin)
    while cur < fin:
        hasta = min(cur + pd.Timedelta(days=TRAMO), fin)
        j = _get(BASE.format(liga=liga) + '/scoreboard',
                 {'dates': f'{cur:%Y%m%d}-{hasta:%Y%m%d}', 'limit': 500})
        for ev in (j or {}).get('events', []):
            if ev.get('status', {}).get('type', {}).get('completed'):
                out.append({'id': ev['id'], 'fecha': ev.get('date', '')[:10]})
        cur = hasta + pd.Timedelta(days=1)
    return out


def auditar_evento(liga, eid):
    j = _get(BASE.format(liga=liga) + '/summary', {'event': eid})
    r = {'rosters': False, 'starters': 0, 'con_stats': 0, 'gk_sv': 0,
         'gk_ga': 0, 'jugadores': 0}
    if not j:
        return r
    ros = j.get('rosters') or []
    if not ros:
        return r
    r['rosters'] = True
    for ro in ros:
        for a in ro.get('roster', []):
            r['jugadores'] += 1
            if a.get('starter'):
                r['starters'] += 1
            st = {x.get('abbreviation'): x.get('displayValue')
                  for x in (a.get('stats') or [])}
            if 'SHOT' in st:
                r['con_stats'] += 1
            if 'SV' in st:
                r['gk_sv'] += 1
            if 'GA' in st:
                r['gk_ga'] += 1
    return r


def auditar_liga(liga, nombre, ventanas, muestra=25):
    res = {'liga': liga, 'nombre': nombre, 'ventanas': []}
    for ini, fin in ventanas:
        evs = eventos(liga, ini, fin)
        if not evs:
            res['ventanas'].append({'desde': ini, 'hasta': fin, 'eventos': 0})
            logger.info(f"  {nombre} {ini}..{fin}: 0 eventos")
            continue
        sel = evs[:: max(1, len(evs) // muestra)][:muestra]
        with ThreadPoolExecutor(max_workers=6) as ex:
            audits = list(ex.map(lambda e: auditar_evento(liga, e['id']), sel))
        n = len(audits)
        con_ros = sum(1 for a in audits if a['rosters'])
        con_star = sum(1 for a in audits if a['starters'] >= 20)
        con_st = sum(1 for a in audits if a['con_stats'] >= 20)
        con_gk = sum(1 for a in audits if a['gk_sv'] >= 1)
        con_ga = sum(1 for a in audits if a['gk_ga'] >= 1)
        v = {'desde': ini, 'hasta': fin, 'eventos': len(evs), 'muestra': n,
             'pct_rosters': round(100 * con_ros / n, 1),
             'pct_11_titulares': round(100 * con_star / n, 1),
             'pct_stats_jugador': round(100 * con_st / n, 1),
             'pct_portero_sv': round(100 * con_gk / n, 1),
             'pct_portero_ga': round(100 * con_ga / n, 1)}
        res['ventanas'].append(v)
        logger.info(f"  {nombre} {ini}..{fin}: {len(evs)} ev · muestra {n} · "
                    f"rosters {v['pct_rosters']}% · 11tit {v['pct_11_titulares']}% · "
                    f"stats {v['pct_stats_jugador']}% · GK-SV {v['pct_portero_sv']}%")
    return res


VENTANAS = [('2019-03-01', '2019-10-31'),
            ('2022-03-01', '2022-10-31'),
            ('2024-03-01', '2024-10-31'),
            ('2025-08-01', '2026-03-31'),
            ('2026-04-01', '2026-07-26')]

LIGAS = [('usa.1', 'MLS'), ('mex.1', 'Liga MX'), ('eng.1', 'Premier'),
         ('esp.1', 'LaLiga'), ('ita.1', 'Serie A'), ('bra.1', 'Brasileirao')]

if __name__ == '__main__':
    solo = sys.argv[1] if len(sys.argv) > 1 else None
    salida = []
    for liga, nombre in LIGAS:
        if solo and liga != solo:
            continue
        logger.info(f"== {nombre} ({liga})")
        salida.append(auditar_liga(liga, nombre, VENTANAS))
        with open('_v70_fase1_rosters.json', 'w', encoding='utf-8') as f:
            json.dump(salida, f, ensure_ascii=False, indent=1)
    print(json.dumps(salida, ensure_ascii=False, indent=1))
