#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v114 — pares que casi casan (0.60-0.80): ¿qué equivalencias faltan?"""
import sys, collections
for _f in (sys.stdout, sys.stderr):
    try: _f.reconfigure(encoding='utf-8', errors='replace')
    except Exception: pass
import logging; logging.disable(logging.WARNING)
import cuotas_multi as cm, fixtures_espn, name_mapper as nm
from league_engine import ClubEngine
import config

cm.precargar('futbol')
pin = cm._indice('futbol'); pdt = cm._indice_pdt('futbol')
tablon = {**pin, **pdt}
activas = [k for k, c in config.LEAGUES.items() if c.get('disponible')]
print(f'{len(activas)} ligas activas · tablón {len(tablon)} partidos')

con, sin, casi = 0, 0, []
for clave in activas:
    try:
        fx = fixtures_espn.fixtures_liga(clave)
    except Exception:
        continue
    for f in fx[:12]:
        h, a = f.get('home'), f.get('away')
        if not h or not a:
            continue
        fe = f.get('inicio') or f.get('fecha')
        hit = cm._buscar(tablon, h, a, 'futbol', fecha=fe)
        if hit:
            con += 1
            continue
        sin += 1
        # el mejor candidato aunque no llegue al umbral
        mejor, sc = None, 0.0
        for v in tablon.values():
            if cm._dias_entre(fe, v.get('fecha')) not in (None,) and \
               (cm._dias_entre(fe, v.get('fecha')) or 0) > 2:
                continue
            s = min(cm._sim_club(h, v['home']), cm._sim_club(a, v['away']))
            if s > sc:
                mejor, sc = v, s
        if mejor and 0.55 <= sc < 0.80:
            casi.append((round(sc,3), clave, h, a, mejor['home'], mejor['away']))
print(f'\nfixtures con precio: {con} · sin precio: {sin}')
print(f'CASI-CASOS (0.55-0.80): {len(casi)}\n')
for sc, cl, h, a, h2, a2 in sorted(casi, reverse=True)[:40]:
    print(f'  {sc}  [{cl}] «{h} vs {a}»')
    print(f'         ≈ «{h2} vs {a2}»')
