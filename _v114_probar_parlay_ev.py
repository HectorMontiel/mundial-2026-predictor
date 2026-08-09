#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v114 — ¿las combinadas se arman ya con precio real de casa?"""
import sys
for _f in (sys.stdout, sys.stderr):
    try: _f.reconfigure(encoding='utf-8', errors='replace')
    except Exception: pass
import logging; logging.disable(logging.WARNING)
import cuotas_multi as cm, cuotas_tablon as ct
from league_engine import ClubEngine
from match_parlay import proponer_parlays
import fixtures_espn, name_mapper as nm

cm.precargar('futbol')
for clave in ('liga_mx', 'brasil'):
    eng = ClubEngine(clave)
    par = None
    for f in fixtures_espn.fixtures_liga(clave):
        h = nm.mapear(f['home'], list(eng.equipos), contexto='t')
        a = nm.mapear(f['away'], list(eng.equipos), contexto='t')
        if h and a and h != a:
            par = (h, a, f); break
    if not par: print(f'{clave}: sin fixture'); continue
    h, a, f = par
    print('='*74); print(f'{clave}: {h} vs {a}')
    m2, n = ct.motor_con_tablon(eng, h, a, fecha=f.get('inicio') or f.get('fecha'))
    print(f'  mercados con precio real inyectados: {n}')
    if n:
        pl = m2.plantilla_club(h, a)
        print('  ejemplos:', list(pl['cuotas_tablon'].items())[:6])
        print('  casas   :', list(pl['casas_tablon'].items())[:4])
    ops = proponer_parlays(m2, h, a, max_opciones=4)
    print(f'  combinadas: {len(ops)}')
    for op in ops[:3]:
        reales = sum(1 for s in op['selecciones'] if s.get('cuota_fuente')=='real')
        print(f"   · {op['etiqueta_opcion']}: {op['n_selecciones']} patas · "
              f"prob {op['prob_conjunta']*100:.0f}% · cuota {op['cuota_combinada']:.2f} "
              f"· {reales}/{len(op['selecciones'])} con cuota REAL")
        for s in op['selecciones']:
            print(f"       {s['apuesta']:<34} @{s['cuota']:<7} "
                  f"{s['prob']*100:>4.0f}%  {s.get('cuota_fuente')}")
