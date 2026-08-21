#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Medición v148: cuántos partidos se quedan sin pronóstico y por qué."""
import sys, warnings, json, collections
warnings.filterwarnings('ignore')
import fixtures_espn, name_mapper
from config import LEAGUES
from league_engine import ClubEngine

claves = [c for c, cfg in LEAGUES.items()
          if cfg.get('disponible') and c in fixtures_espn.ESPN_CODIGOS]
fx = fixtures_espn.fixtures_multi(claves, dias=3)

tot_ok = tot_no = tot_fix = 0
por_causa = collections.Counter()
detalle = []
sinmotor = []
for c in sorted(claves):
    f = fx.get(c) or []
    if not f:
        continue
    tot_fix += len(f)
    try:
        eng = ClubEngine(c)
    except Exception as e:
        sinmotor.append((c, str(e)[:60])); continue
    if not eng.listo:
        sinmotor.append((c, str(eng.error)[:60])); continue
    cat = list(eng.stats.keys())
    ok = 0; falt = []
    for x in f:
        h = name_mapper.mapear(x['home'], cat, contexto='m')
        a = name_mapper.mapear(x['away'], cat, contexto='m')
        if h and a and h != a:
            ok += 1
        else:
            for n, m in ((x['home'], h), (x['away'], a)):
                if not m:
                    _cand, _r = name_mapper.mejor_candidato(n, cat)
                    causa = 'alias que falta' if _r >= 0.62 else 'equipo nuevo (asciende)'
                    por_causa[causa] += 1
                    falt.append(f'{n} [{causa[:5]}·{_r:.2f}]')
    no = len(f) - ok
    tot_ok += ok; tot_no += no
    if no:
        detalle.append((c, len(f), no, sorted(set(falt))[:8]))

print(f'\nFIXTURES TOTALES: {tot_fix}')
print(f'CON pronostico  : {tot_ok}')
print(f'SIN pronostico  : {tot_no}   ({tot_no/max(tot_fix,1)*100:.1f} %)')
print('\nPOR CAUSA (equipos, no partidos):')
for k, v in por_causa.most_common():
    print(f'   {v:3d}  {k}')
print('\nDETALLE POR LIGA:')
for c, n, no, falt in detalle:
    print(f'   {c:<22} {no}/{n}  {falt}')
print('\nSIN MOTOR:', sinmotor or 'ninguna')
