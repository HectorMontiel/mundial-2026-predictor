#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v71 · Auditoría — ¿de qué partidos hay cuota y de cuáles no?

Antes de construir la capa de cuotas hay que saber exactamente dónde está el
agujero. Mide, para TODAS las competiciones desplegadas y para el tenis:

  · fixtures de la semana en curso
  · de esos, cuántos traen 1X2 en el `scoreboard` de ESPN (coste cero)
  · cuántos lo traen en el CORE API de ESPN (otra petición, a veces sí cuando
    el scoreboard devuelve `odds: [null]`)

Salida: `_v71_cobertura_cuotas.json`
"""
import json
import logging
import sys
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import requests

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

UA = {'User-Agent': 'Mozilla/5.0'}
SB = 'https://site.api.espn.com/apis/site/v2/sports/{dep}/{liga}/scoreboard'
CORE = ('https://sports.core.api.espn.com/v2/sports/{dep}/leagues/{liga}'
        '/events/{ev}/competitions/{comp}/odds')


def _get(url, params=None):
    try:
        r = requests.get(url, params=params, headers=UA, timeout=25)
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


def odds_core(dep, liga, ev, comp):
    j = _get(CORE.format(dep=dep, liga=liga, ev=ev, comp=comp))
    if not j:
        return 0
    return int(j.get('count') or 0)


def auditar(dep, liga, dias=7):
    import fixtures_espn as fx
    hoy = pd.Timestamp.today().normalize()
    ini = hoy.strftime('%Y%m%d')
    fin = (hoy + pd.Timedelta(days=dias)).strftime('%Y%m%d')
    j = _get(SB.format(dep=dep, liga=liga), {'dates': f'{ini}-{fin}', 'limit': 300})
    evs = [e for e in (j or {}).get('events', [])
           if not e.get('status', {}).get('type', {}).get('completed')]
    n = len(evs)
    con_sb = 0
    sin_sb = []
    for e in evs:
        c = (e.get('competitions') or [{}])[0]
        if fx._odds_de_evento(c).get('odd_home'):
            con_sb += 1
        else:
            sin_sb.append((e['id'], c.get('id')))
    con_core = 0
    if sin_sb:
        with ThreadPoolExecutor(max_workers=6) as ex:
            for cnt in ex.map(lambda t: odds_core(dep, liga, t[0], t[1]), sin_sb[:12]):
                if cnt:
                    con_core += 1
    return {'liga': liga, 'deporte': dep, 'fixtures': n,
            'con_odds_scoreboard': con_sb,
            'sin_odds': len(sin_sb),
            'recuperables_core': con_core,
            'muestra_core': min(len(sin_sb), 12)}


def main():
    import config
    from config_ligas_espn import LIGAS_V68
    claves = []
    for c, cfg in config.LEAGUES.items():
        lg = cfg.get('espn_liga') or cfg.get('espn')
        if not lg:
            continue
        if c in LIGAS_V68 and not LIGAS_V68[c].get('disponible'):
            continue
        claves.append(('soccer', lg, c))
    # mapa manual para las de football-data (no llevan espn_liga en config)
    EXTRA = {'liga_mx': 'mex.1', 'brasil': 'bra.1', 'mls': 'usa.1',
             'premier': 'eng.1', 'laliga': 'esp.1', 'serie_a': 'ita.1',
             'bundesliga': 'ger.1', 'ligue_1': 'fra.1', 'argentina': 'arg.1',
             'eredivisie': 'ned.1', 'portugal': 'por.1'}
    for c, lg in EXTRA.items():
        if c in config.LEAGUES and not any(x[2] == c for x in claves):
            claves.append(('soccer', lg, c))
    vistos = set()
    tareas = []
    for dep, lg, c in claves:
        if lg in vistos:
            continue
        vistos.add(lg)
        tareas.append((dep, lg, c))
    tareas.append(('tennis', 'atp', 'atp'))
    tareas.append(('tennis', 'wta', 'wta'))
    tareas.append(('baseball', 'mlb', 'mlb'))
    tareas.append(('basketball', 'nba', 'nba'))

    salida = []
    for dep, lg, c in tareas:
        try:
            r = auditar(dep, lg)
            r['clave'] = c
        except Exception as e:
            r = {'clave': c, 'liga': lg, 'error': f'{type(e).__name__}: {e}'}
        salida.append(r)
        if 'error' not in r:
            logger.info(f"{c:22s} {lg:10s} fixtures={r['fixtures']:3d} "
                        f"1X2_scoreboard={r['con_odds_scoreboard']:3d} "
                        f"sin={r['sin_odds']:3d} "
                        f"core_recupera={r['recuperables_core']}/{r['muestra_core']}")
        else:
            logger.warning(f"{c}: {r['error']}")
        with open('_v71_cobertura_cuotas.json', 'w', encoding='utf-8') as f:
            json.dump(salida, f, ensure_ascii=False, indent=1)

    tot_f = sum(r.get('fixtures', 0) for r in salida)
    tot_o = sum(r.get('con_odds_scoreboard', 0) for r in salida)
    logger.info(f"== TOTAL: {tot_o}/{tot_f} fixtures con 1X2 de ESPN "
                f"({100*tot_o/max(tot_f,1):.1f} %)")


if __name__ == '__main__':
    main()
