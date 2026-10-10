#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v354 — la pretemporada de la NBA, con resultado y cuota (ESPN).

El usuario: «quiero empezar a ver NBA; investiga todas las fuentes que estén
actualizadas, también con la pretemporada». Fuentes probadas el 2026-10-09:

  · ESPN scoreboard (site.api.espn.com) — resultados de pretemporada de 2016
    a hoy (seasontype=1). SÍ.
  · ESPN core API (sports.core.api.espn.com/.../odds) — la cuota de cada
    partido (moneyline, hándicap y total; DraftKings, ESPN BET o Caesars)
    desde ~2021, pretemporada incluida. SÍ.
  · NBA.com (cdn.nba.com, stats.nba.com) — 403 / sin respuesta desde aquí.
  · balldontlie, The Odds API — piden clave (y la histórica es de pago).
  · Playdoit — los precios de hoy (ya emparejados, v354 `cuotas_multi`).

Descarga cada día de pretemporada (20-sep → 25-oct) de 2021 a 2026 y guarda
una fila por partido en `_v354_nba_pretemporada.csv`.
"""
import datetime as dt
import sys
import time

import pandas as pd
import requests

SB = 'https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard'
ODDS = ('https://sports.core.api.espn.com/v2/sports/basketball/leagues/nba/'
        'events/{e}/competitions/{e}/odds')
SALIDA = '_v354_nba_pretemporada.csv'


def _get(url, params=None):
    for i in range(3):
        try:
            r = requests.get(url, params=params, timeout=30)
            if r.ok:
                return r.json()
        except Exception:
            pass
        time.sleep(1 + i)
    return None


def _ml(x):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return 1 + x / 100 if x > 0 else 1 + 100 / abs(x)


def temporada(anio):
    filas = []
    d = dt.date(anio, 9, 20)
    while d <= dt.date(anio, 10, 25):
        j = _get(SB, {'dates': d.strftime('%Y%m%d'), 'seasontype': 1}) or {}
        for ev in j.get('events') or []:
            c = ev['competitions'][0]
            if not c.get('status', {}).get('type', {}).get('completed'):
                continue
            eq = {t['homeAway']: t for t in c['competitors']}
            if 'home' not in eq or 'away' not in eq:
                continue
            fila = {'temporada': anio, 'fecha': ev['date'][:10], 'event_id': ev['id'],
                    'home': eq['home']['team']['displayName'],
                    'away': eq['away']['team']['displayName'],
                    'pts_home': float(eq['home']['score']), 'pts_away': float(eq['away']['score']),
                    'nba_vs_nba': all(t['team'].get('abbreviation') and len(t['team']['abbreviation']) <= 4
                                      for t in c['competitors'])}
            o = (_get(ODDS.format(e=ev['id'])) or {}).get('items') or []
            o = [x for x in o if 'live' not in str((x.get('provider') or {}).get('name')).lower()]
            if o:
                x = o[0]
                fila.update({'casa': (x.get('provider') or {}).get('name'),
                             'ml_home': _ml((x.get('homeTeamOdds') or {}).get('moneyLine')),
                             'ml_away': _ml((x.get('awayTeamOdds') or {}).get('moneyLine')),
                             'spread': x.get('spread'), 'total': x.get('overUnder')})
            filas.append(fila)
        d += dt.timedelta(days=1)
    return filas


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    todas = []
    for anio in range(2021, 2027):
        f = temporada(anio)
        con = sum(1 for x in f if x.get('ml_home'))
        print(anio, 'partidos', len(f), 'con cuota', con, flush=True)
        todas += f
    pd.DataFrame(todas).to_csv(SALIDA, index=False)
    print('guardado', SALIDA, len(todas))
