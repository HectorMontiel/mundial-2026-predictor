#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v358 — la pretemporada de la NFL, con resultado y cuota (ESPN).

El usuario: «quiero meter en la NFL hándicap, más/menos puntos y ganador,
con un modelo con la misma metodología para la pretemporada y la temporada
oficial; si hacen falta fuentes, extráelas». nflverse (`historico_nfl_largo`)
sólo trae temporada regular y playoffs; la pretemporada sale de ESPN, igual
que la de la NBA (`_v354_nba_espn.py`):

  · ESPN scoreboard (site.api.espn.com, seasontype=1) — resultados.
  · ESPN core API (.../events/{e}/competitions/{e}/odds) — moneyline,
    hándicap y total de la casa (DraftKings / ESPN BET / Caesars), ~2021+.

Descarga cada día de agosto y primeros de septiembre de 2016 a 2026 y guarda
una fila por partido en `_v358_nfl_pretemporada.csv`.
"""
import datetime as dt
import sys
import time

import pandas as pd
import requests

SB = 'https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard'
ODDS = ('https://sports.core.api.espn.com/v2/sports/football/leagues/nfl/'
        'events/{e}/competitions/{e}/odds')
SALIDA = '_v358_nfl_pretemporada.csv'


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
    d = dt.date(anio, 7, 28)
    while d <= dt.date(anio, 9, 6):
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
                    'abrev_home': eq['home']['team'].get('abbreviation'),
                    'abrev_away': eq['away']['team'].get('abbreviation'),
                    'pts_home': float(eq['home']['score']), 'pts_away': float(eq['away']['score'])}
            if anio >= 2020:
                o = (_get(ODDS.format(e=ev['id'])) or {}).get('items') or []
                o = [x for x in o if 'live' not in str((x.get('provider') or {}).get('name')).lower()]
                if o:
                    x = o[0]
                    fila.update({'casa': (x.get('provider') or {}).get('name'),
                                 'ml_home': _ml((x.get('homeTeamOdds') or {}).get('moneyLine')),
                                 'ml_away': _ml((x.get('awayTeamOdds') or {}).get('moneyLine')),
                                 'spread': x.get('spread'), 'total': x.get('overUnder'),
                                 'fav_home': (x.get('homeTeamOdds') or {}).get('favorite')})
            filas.append(fila)
        d += dt.timedelta(days=1)
    return filas


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    todas = []
    for anio in range(2016, 2027):
        f = temporada(anio)
        con = sum(1 for x in f if x.get('ml_home') or x.get('spread') is not None)
        print(anio, 'partidos', len(f), 'con cuota', con, flush=True)
        todas += f
    pd.DataFrame(todas).to_csv(SALIDA, index=False)
    print('guardado', SALIDA, len(todas))
