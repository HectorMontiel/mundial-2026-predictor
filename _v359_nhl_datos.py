#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v359 — NHL: los cierres de la casa y el marcador, 2007 → hoy.

El usuario: «agrega la NHL con todo lo de contra la casa, nuestro método».
La app no tenía hockey. Fuentes (probadas el 2026-10-10):

  · sportsbookreviewsonline — una página por temporada (2007-08 a 2021-22):
    moneyline de apertura y cierre, puck line (±1,5) con su cuota y total de
    cierre con su cuota; marcador final (incluye el gol de la tanda).
  · ESPN (site.api scoreboard + core API odds) — 2022-23 a hoy, con la
    PRETEMPORADA (seasontype=1) y los playoffs (3): moneyline, puck line y
    total de la casa (DraftKings / ESPN BET).

Guarda una fila por partido en `_v359_nhl_cierres.csv`.
"""
import datetime as dt
import io
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd
import requests

UA = {'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                     '(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36')}
SBRO = 'https://www.sportsbookreviewsonline.com/scoresoddsarchives/nhl-odds-%s'
SB = 'https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/scoreboard'
ODDS = ('https://sports.core.api.espn.com/v2/sports/hockey/leagues/nhl/'
        'events/{e}/competitions/{e}/odds')
SALIDA = '_v359_nhl_cierres.csv'
TIPOS = {1: 'pretemporada', 2: 'regular', 3: 'playoffs'}


def _dec(x):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return np.nan
    if not np.isfinite(x) or x == 0:
        return np.nan
    return 1 + x / 100.0 if x > 0 else 1 + 100.0 / abs(x)


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return np.nan


def sbro(temporada):
    r = requests.get(SBRO % temporada, headers=UA, timeout=90)
    t = pd.read_html(io.StringIO(r.text))[0]
    t = t.iloc[1:].reset_index(drop=True)
    a0 = int(temporada[:4])
    filas = []
    for i in range(0, len(t) - 1, 2):
        v, h = t.iloc[i], t.iloc[i + 1]
        try:
            mmdd = int(v[0])
        except (TypeError, ValueError):
            continue
        mes, dia = divmod(mmdd, 100)
        anio = a0 if mes >= 8 else a0 + 1
        try:
            fecha = dt.date(anio, mes, dia).isoformat()
        except ValueError:
            continue
        pl_h = _num(h[10])
        filas.append({'fuente': 'sbro', 'temporada': a0, 'tipo': 'regular', 'fecha': fecha,
                      'home': str(h[3]), 'away': str(v[3]),
                      'gh': _num(h[7]), 'ga': _num(v[7]),
                      'ml_home': _dec(h[9]), 'ml_away': _dec(v[9]),
                      'pl_home': pl_h, 'pl_home_c': _dec(h[11]), 'pl_away_c': _dec(v[11]),
                      'total': _num(v[14]) if np.isfinite(_num(v[14])) else _num(h[14]),
                      'over_c': _dec(v[15]), 'under_c': _dec(h[15])})
    return filas


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


def _odds(eid):
    o = (_get(ODDS.format(e=eid)) or {}).get('items') or []
    o = [x for x in o if 'live' not in str((x.get('provider') or {}).get('name')).lower()]
    if not o:
        return {}
    x = o[0]
    ho, ao = x.get('homeTeamOdds') or {}, x.get('awayTeamOdds') or {}
    sp = _num(x.get('spread'))
    return {'casa': (x.get('provider') or {}).get('name'),
            'ml_home': _dec(ho.get('moneyLine')), 'ml_away': _dec(ao.get('moneyLine')),
            'pl_home': sp, 'pl_home_c': _dec(ho.get('spreadOdds')), 'pl_away_c': _dec(ao.get('spreadOdds')),
            'total': _num(x.get('overUnder')), 'over_c': _dec(x.get('overOdds')),
            'under_c': _dec(x.get('underOdds'))}


def espn(desde, hasta):
    eventos = []
    d = desde
    while d <= hasta:
        j = _get(SB, {'dates': d.strftime('%Y%m%d')}) or {}
        for ev in j.get('events') or []:
            c = ev['competitions'][0]
            if not c.get('status', {}).get('type', {}).get('completed'):
                continue
            eq = {t['homeAway']: t for t in c['competitors']}
            if 'home' not in eq or 'away' not in eq:
                continue
            st = (ev.get('season') or {})
            eventos.append({'fuente': 'espn', 'event_id': ev['id'],
                            'temporada': int(st.get('year', d.year)) - 1,
                            'tipo': TIPOS.get(int(st.get('type', 2)), 'regular'),
                            'fecha': ev['date'][:10],
                            'home': eq['home']['team']['displayName'],
                            'away': eq['away']['team']['displayName'],
                            'gh': _num(eq['home'].get('score')), 'ga': _num(eq['away'].get('score'))})
        d += dt.timedelta(days=1)
    with ThreadPoolExecutor(8) as ex:
        odds = list(ex.map(lambda e: _odds(e['event_id']), eventos))
    for e, o in zip(eventos, odds):
        e.update(o)
    return eventos


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    todas = []
    for a in range(2007, 2022):
        s = '%d-%02d' % (a, (a + 1) % 100) if a != 2020 else '2021'
        try:
            f = sbro(s)
        except Exception as e:
            print(s, 'error', e, flush=True)
            continue
        print('sbro', s, len(f), flush=True)
        todas += f
    for a in range(2022, 2027):
        desde, hasta = dt.date(a, 9, 15), min(dt.date(a + 1, 6, 30), dt.date.today())
        if desde > hasta:
            continue
        f = espn(desde, hasta)
        con = sum(1 for x in f if x.get('ml_home') == x.get('ml_home') and x.get('ml_home'))
        print('espn', a, len(f), 'con cuota', con, flush=True)
        todas += f
    pd.DataFrame(todas).to_csv(SALIDA, index=False)
    print('guardado', SALIDA, len(todas))
