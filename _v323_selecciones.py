# -*- coding: utf-8 -*-
"""v323 — replay honesto del motor de selecciones (la medición de
`actualizar_selecciones.py`).

Para cada partido de selecciones desde 2024-01-01 (el clasificador se entrenó
con lo ANTERIOR a esa fecha: todo esto es fuera de muestra), calcula las
probabilidades que habría dado el motor:

  · `fresco`: con el estado de los equipos al día justo antes del partido
    (lo que daría si el estado se actualizara a diario);
  · `actual` (sólo julio→hoy): con el `team_stats.json` del repo, congelado
    el 2026-07-15, que es lo que hace hoy producción.

Misma maquinaria que `PredictionEngine.predecir` (vista directa, espejada y
la regla de localía: en casa salvo sede neutral, como `selecciones_dia`).

Salida: `_v323_replay_selecciones.csv`. Se corre con el histórico y el
`team_stats.json` de ANTES de `actualizar_selecciones` (congelados el
2026-07-15). Análisis: `python _v323_selecciones_analisis.py`.
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.getcwd())
SCR = os.getcwd()   # escribe los _v323_*.csv en la raíz del repo

import feature_engineering as fe
import selecciones_dia as sd
from config import NAME_EN_TO_FIFA
from correlated_synthetic_generator import CorrelatedSyntheticGenerator
import statsbomb_calibration
import altitud

m = sd._motor()


def _un_hilo(obj, vistos=None):
    """n_jobs=1 en todo el árbol del modelo: mismo resultado, sin abrir un
    grupo de procesos por predicción."""
    vistos = vistos or set()
    if id(obj) in vistos:
        return
    vistos.add(id(obj))
    if hasattr(obj, 'n_jobs'):
        try:
            obj.n_jobs = 1
        except Exception:
            pass
    for attr in ('estimator', 'estimators_', 'calibrated_classifiers_', 'base_estimator'):
        sub = getattr(obj, attr, None)
        if sub is None:
            continue
        for x in (sub if isinstance(sub, (list, tuple)) else [sub]):
            _un_hilo(x, vistos)


_un_hilo(m.modelo)
cat = sd.catalogo(m)
CORTE_ESTADO = pd.Timestamp('2026-07-15')

# ---- 1. histórico extendido -------------------------------------------------
H = pd.read_csv('historico_partidos.csv')
H['date'] = pd.to_datetime(H['date'])
E = pd.read_csv('historico_selecciones.csv')
E['date'] = pd.to_datetime(E['date'])
E = E[(E.date > H.date.max())].dropna(subset=['home_goals', 'away_goals'])


def codigo(nombre):
    return cat.get(nombre) or NAME_EN_TO_FIFA.get(nombre) or nombre


nuevos = []
for _, r in E.iterrows():
    f = {'home': r.home_team, 'away': r.away_team, 'torneo': r.tournament}
    if not sd._es_absoluta(f):
        continue
    h, a = codigo(r.home_team), codigo(r.away_team)
    nuevos.append({'date': r.date, 'home_team': h, 'away_team': a,
                   'home_goals': float(r.home_goals), 'away_goals': float(r.away_goals),
                   'tournament': r.tournament, 'city': None, 'country': None,
                   'neutral': str(r.neutral).lower() == 'true', 'stadium': None,
                   'MATCH_ID': '%s_%s_%s' % (r.date.strftime('%Y%m%d'),
                                             str(h).replace(' ', '-'),
                                             str(a).replace(' ', '-'))})
N = pd.DataFrame(nuevos).drop_duplicates('MATCH_ID')
todo = pd.concat([H, N], ignore_index=True).sort_values(
    ['date', 'MATCH_ID'], kind='mergesort').reset_index(drop=True)
# elo_diff como `data_fetcher.compute_elo_series` (sin escribir elo_actual.csv)
elo, diffs = {}, np.zeros(len(todo))
for i, fila in enumerate(todo.itertuples(index=False)):
    hh, aa = fila.home_team, fila.away_team
    rh, ra = elo.get(hh, 1500.0), elo.get(aa, 1500.0)
    diffs[i] = rh - ra
    eh = 1 / (1 + 10 ** ((ra - rh) / 400))
    sh = 1.0 if fila.home_goals > fila.away_goals else (0.5 if fila.home_goals == fila.away_goals else 0.0)
    k = 48 if 'World Cup' in str(fila.tournament) else (20 if 'Friendly' in str(fila.tournament) else 32)
    elo[hh] = rh + k * (sh - eh)
    elo[aa] = ra + k * ((1 - sh) - (1 - eh))
todo['elo_diff'] = diffs
es_nuevo = todo['MATCH_ID'].isin(set(N['MATCH_ID']))
gen = CorrelatedSyntheticGenerator()
cal = statsbomb_calibration.calibrar()
rel = gen.generate_advanced_metrics(todo[es_nuevo].reset_index(drop=True), cal)
for c in rel.columns:
    if c not in todo.columns:
        todo[c] = np.nan
    todo.loc[es_nuevo, c] = rel[c].values
todo.to_csv(os.path.join(SCR, '_v323_historico_extendido.csv'), index=False)
print('histórico extendido: %d partidos (+%d nuevos de ESPN, hasta %s)'
      % (len(todo), int(es_nuevo.sum()), todo.date.max().date()))

# ---- 2. replay ----------------------------------------------------------------
ESTADIO = altitud.ESTADIO_POR_DEFECTO


def probs_motor(home, away, en_casa, s_l, s_v, h2h):
    m.stats_equipos = {home: s_l, away: s_v}
    m.h2h_balance = h2h
    est = m._estadio_del_cruce(home, away) or ESTADIO
    ctx = m._contexto(home, away, est)
    _, _, pd_ = m._inferencia_modelo(home, away, s_l, s_v, ctx)
    ctx_e = m._contexto(away, home, est)
    _, _, pe = m._inferencia_modelo(away, home, s_v, s_l, ctx_e)
    pe = pe[::-1]
    sede = m._pais_sede(est)
    if en_casa:
        sede = home
    p = pd_ if sede == home else (pe if sede == away else (pd_ + pe) / 2.0)
    return p / p.sum()


import json
ts = json.load(open('team_stats.json'))
congelado = ts['equipos']
h2h_cong = ts.get('h2h', {})


def h2h_c(a, b):
    if '%s|%s' % (a, b) in h2h_cong:
        return float(h2h_cong['%s|%s' % (a, b)])
    if '%s|%s' % (b, a) in h2h_cong:
        return -float(h2h_cong['%s|%s' % (b, a)])
    return 0.0


num = ['home_goals', 'away_goals', 'home_xg', 'away_xg', 'home_shots_on',
       'away_shots_on', 'home_yellow', 'away_yellow', 'home_red', 'away_red']
for c in num:
    todo[c] = pd.to_numeric(todo[c], errors='coerce')
todo = todo.dropna(subset=num).reset_index(drop=True)
estado = fe.EstadoRodante()
equipos = set(m.equipos)
filas = []
for _, f in todo.iterrows():
    hh, aa = f['home_team'], f['away_team']
    if f['date'] >= pd.Timestamp('2024-01-01') and hh in equipos and aa in equipos:
        sl, sv = estado.stats_equipo(hh), estado.stats_equipo(aa)
        if sl['N_PARTIDOS'] >= 3 and sv['N_PARTIDOS'] >= 3:
            sl = dict(sl, PERF10=[list(map(float, v)) for v in estado.perf10[hh]])
            sv = dict(sv, PERF10=[list(map(float, v)) for v in estado.perf10[aa]])
            en_casa = not bool(f['neutral'])
            pf = probs_motor(hh, aa, en_casa, sl, sv, estado.h2h_balance)
            pc = [np.nan] * 3
            if f['date'] > CORTE_ESTADO and hh in congelado and aa in congelado:
                pc = probs_motor(hh, aa, en_casa, dict(congelado[hh]),
                                 dict(congelado[aa]), h2h_c)
            gh, ga = f['home_goals'], f['away_goals']
            filas.append({'date': f['date'], 'home': hh, 'away': aa,
                          'tournament': f['tournament'], 'neutral': bool(f['neutral']),
                          'y': 0 if gh > ga else (1 if gh == ga else 2),
                          'f0': pf[0], 'f1': pf[1], 'f2': pf[2],
                          'c0': pc[0], 'c1': pc[1], 'c2': pc[2],
                          'elo_diff': (sl['ELO'] - sv['ELO'])})
    estado.actualizar(f)
R = pd.DataFrame(filas)
R.to_csv(os.path.join(SCR, '_v323_replay_selecciones.csv'), index=False)
print('replay: %d partidos desde 2024 (%d después del 15-jul)'
      % (len(R), int((R.date > CORTE_ESTADO).sum())))
