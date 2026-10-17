#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v384 — ¿QUÉ ERRORES DE CUOTA (💰) SE CUMPLEN MÁS?

El usuario: «hay algunos que son error de cuota pero no tienen tanta
probabilidad, y revisando el historial reciente y el H2H se ve bastante bien».
Con los 💰 ya liquidados (`capa1_historial.json`, 3 al 16-oct) y lo que se
anunció de cada uno (git de `anunciadas_dia.json`: prob del modelo, prob del
mercado), más la FORMA y el H2H del histórico (sólo partidos ANTERIORES a la
fecha), se mide acierto y dinero por grupo, en dos mitades por fecha, con
bootstrap del p5 de la ganancia. Escribe `_v384_errores.json`.
"""
import collections
import datetime as dt
import json
import subprocess
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, '.')
sys.stdout.reconfigure(encoding='utf-8')
rng = np.random.default_rng(384)

# 1) lo liquidado
filas = [x for x in json.load(open('capa1_historial.json', encoding='utf-8'))['filas']
         if x.get('nivel') == '💰' and x.get('resultado') in ('verde', 'rojo') and x.get('cuota')]
# 2) lo anunciado de cada uno (la primera vez que salió)
anun, ligas_de = {}, {}
hs = subprocess.run(['git', 'log', '--since=2026-10-02', '--format=%h', '--', 'anunciadas_dia.json'],
                    capture_output=True, text=True).stdout.split()
for h in reversed(hs):
    r = subprocess.run(['git', 'show', '%s:anunciadas_dia.json' % h], capture_output=True)
    if r.returncode:
        continue
    try:
        d = json.loads(r.stdout.decode('utf-8'))
    except Exception:
        continue
    for k, e in (d.get('partidos') or {}).items():
        for c in e.get('capa1') or []:
            if c.get('nivel') != '💰':
                continue
            kk = (e.get('partido'), c.get('apuesta'))
            if kk not in anun:
                anun[kk] = dict(c, liga=e.get('liga'), inicio=e.get('inicio'), deporte=e.get('deporte'))
# 3) liga (nombre) → clave_liga, de los partidos ya jugados archivados
for f in ('jugados_ayer.json', 'jugados_dia.json', 'pronostico_dia.json'):
    try:
        d = json.load(open(f, encoding='utf-8'))
        ps = d.get('partidos') or (d.get('datos') or {}).get('pronosticos') or []
        for p in ps:
            if p.get('liga') and p.get('clave_liga'):
                ligas_de[p['liga']] = p['clave_liga']
    except Exception:
        pass
try:
    import nombres_ligas as nl
    for p in list(ligas_de):
        ligas_de[nl.canonica(p, ligas_de[p])] = ligas_de[p]
except Exception:
    pass

# v384 — la forma y el H2H del histórico de Flashscore (los 💰 son casi todos
# de ligas chicas que sólo tiene Flashscore; mismos nombres de equipo)
FS = pd.concat([pd.read_csv(f) for f in ('resultados_flashscore.csv.gz', 'resultados_flashscore_reciente.csv.gz')])
FS = FS.drop_duplicates('match_id')
FS['date'] = pd.to_datetime(FS['ini'], errors='coerce')
FS = FS.rename(columns={'home': 'home_team', 'away': 'away_team', 'gh': 'home_goals', 'ga': 'away_goals'})
_POR_EQ = {}
for i, r in enumerate(FS[['home_team', 'away_team']].itertuples(index=False)):
    _POR_EQ.setdefault(r.home_team, []).append(i)
    _POR_EQ.setdefault(r.away_team, []).append(i)
import panel_equipos as pe
_hist = {}


def hist(clave):
    if clave not in _hist:
        try:
            h = pe._historico(clave)
            h = h.copy()
            h['date'] = pd.to_datetime(h['date'], errors='coerce')
            _hist[clave] = h
        except Exception:
            _hist[clave] = None
    return _hist[clave]


def hist_eq(eq):
    idx = _POR_EQ.get(eq)
    return FS.iloc[idx] if idx else None


def forma_h2h(clave, home, away, eq, dia):
    """puntos por partido del equipo apostado en sus últimos 5 y su balance en
    los últimos 5 cruces, todo ANTES de `dia`."""
    h = hist_eq(eq)
    if h is None or getattr(h, 'empty', True):
        return None, None, None
    h = h[h['date'] < pd.Timestamp(dia)]
    m = h[(h.home_team == eq) | (h.away_team == eq)].sort_values('date').tail(5)
    pts = []
    for r in m.itertuples():
        gf, gc = (r.home_goals, r.away_goals) if r.home_team == eq else (r.away_goals, r.home_goals)
        if pd.isna(gf) or pd.isna(gc):
            continue
        pts.append(3 if gf > gc else (1 if gf == gc else 0))
    rival = away if eq == home else home
    c = h[((h.home_team == eq) & (h.away_team == rival)) | ((h.home_team == rival) & (h.away_team == eq))].sort_values('date').tail(5)
    g = e = p = 0
    for r in c.itertuples():
        gf, gc = (r.home_goals, r.away_goals) if r.home_team == eq else (r.away_goals, r.home_goals)
        if pd.isna(gf) or pd.isna(gc):
            continue
        g += gf > gc; e += gf == gc; p += gf < gc
    return (np.mean(pts) if len(pts) >= 3 else None), ((g, e, p) if g + e + p >= 2 else None), len(m)


F = []
for x in filas:
    a = anun.get((x['partido'], x['apuesta'])) or {}
    pm, pr = a.get('p_mercado') or a.get('prob'), a.get('prob')
    eq = x['apuesta'][5:].strip() if x['apuesta'].startswith('Gana ') else None
    home = away = None
    if ' vs ' in x['partido']:
        home, away = [s.strip() for s in x['partido'].split(' vs ', 1)]
    fo = h2 = None
    clave = ligas_de.get(a.get('liga') or '')
    if x['deporte'] == 'Fútbol' and eq and eq in (home, away):
        fo, h2, _ = forma_h2h(clave, home, away, eq, x['dia'])
    F.append({'dia': x['dia'], 'ok': x['resultado'] == 'verde', 'cuota': float(x['cuota']), 'dep': x['deporte'],
              'pm': pm, 'pr': pr, 'edge': (float(x['cuota']) * pm - 1) if pm else None,
              'gana': bool(eq), 'forma': fo, 'h2h': h2})
dd = sorted({f['dia'] for f in F}); mitad = dd[len(dd) // 2]


def roi(s):
    if len(s) < 15:
        return None
    g = np.array([f['cuota'] - 1 if f['ok'] else -1 for f in s])
    b = [g[rng.integers(0, len(g), len(g))].mean() for _ in range(2000)]
    return '%3d · acierta %2.0f%% · cuota %.2f · %+5.1f por $100 (p5 %+5.1f)' % (
        len(s), 100 * np.mean([f['ok'] for f in s]), np.mean([f['cuota'] for f in s]), 100 * g.mean(), 100 * np.percentile(b, 5))


G = collections.OrderedDict()
G['todos'] = lambda f: True
for dep in ('Fútbol', 'Tenis', 'NBA', 'NHL', 'NFL', 'MLB'):
    G['deporte ' + dep] = (lambda d: lambda f: f['dep'] == d)(dep)
for a, b in ((1.0, 1.8), (1.8, 2.2), (2.2, 2.8), (2.8, 4.0), (4.0, 99)):
    G['cuota %.1f-%.1f' % (a, b)] = (lambda a, b: lambda f: a <= f['cuota'] < b)(a, b)
G['mercado ≥ 50 % (favorito)'] = lambda f: (f['pm'] or 0) >= 0.5
G['mercado 40-50 %'] = lambda f: 0.4 <= (f['pm'] or 0) < 0.5
G['mercado < 40 %'] = lambda f: f['pm'] is not None and f['pm'] < 0.4
G['ventaja ≥ 8 %'] = lambda f: (f['edge'] or 0) >= 0.08
G['ventaja 3-8 %'] = lambda f: 0.03 <= (f['edge'] or 0) < 0.08
G['ventaja < 3 %'] = lambda f: f['edge'] is not None and f['edge'] < 0.03
G['modelo ≥ mercado'] = lambda f: f['pr'] is not None and f['pm'] is not None and f['pr'] >= f['pm']
G['modelo < mercado'] = lambda f: f['pr'] is not None and f['pm'] is not None and f['pr'] < f['pm']
G['forma buena (≥ 1,8 pts)'] = lambda f: f['forma'] is not None and f['forma'] >= 1.8
G['forma mala (< 1,2 pts)'] = lambda f: f['forma'] is not None and f['forma'] < 1.2
G['H2H a favor (más ganados)'] = lambda f: f['h2h'] is not None and f['h2h'][0] > f['h2h'][2]
G['H2H en contra'] = lambda f: f['h2h'] is not None and f['h2h'][0] < f['h2h'][2]
G['forma buena y H2H no en contra'] = lambda f: f['forma'] is not None and f['forma'] >= 1.8 and (f['h2h'] is None or f['h2h'][0] >= f['h2h'][2])
G['favorito + modelo ≥ mercado'] = lambda f: (f['pm'] or 0) >= 0.5 and f['pr'] is not None and f['pr'] >= f['pm']
R = {'dias': [dd[0], dd[-1]], 'mitad': mitad, 'n': len(F),
     'con_datos_anunciados': sum(1 for f in F if f['pm'] is not None),
     'con_forma': sum(1 for f in F if f['forma'] is not None), 'con_h2h': sum(1 for f in F if f['h2h'] is not None)}
print(R)
for k, fn in G.items():
    A = roi([f for f in F if fn(f) and f['dia'] < mitad]); B = roi([f for f in F if fn(f) and f['dia'] >= mitad])
    R[k] = [A, B]
    if A or B:
        print('%-34s | %s | %s' % (k, A, B))
json.dump(R, open('_v384_errores.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
