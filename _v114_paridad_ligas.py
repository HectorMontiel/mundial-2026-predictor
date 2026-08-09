#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v114 — ¿todas las ligas enseñan ahora los mismos mercados que Liga MX?"""
import sys
for _f in (sys.stdout, sys.stderr):
    try: _f.reconfigure(encoding='utf-8', errors='replace')
    except Exception: pass
import logging
logging.disable(logging.WARNING)
import cuotas_multi as cm, cuotas_tablon as ct, cuotas_auto as ca
from league_engine import ClubEngine
import fixtures_espn

LIGAS = ['liga_mx', 'champions', 'conference_league', 'eredivisie', 'brasil']
cm.precargar('futbol')
for clave in LIGAS:
    print('=' * 74)
    try:
        eng = ClubEngine(clave)
        if not eng.listo:
            print(f'{clave}: motor no listo'); continue
        fx = fixtures_espn.fixtures_liga(clave)
        import name_mapper as nm
        par = None
        for f in fx:
            h = nm.mapear(f['home'], list(eng.equipos), contexto='t')
            a = nm.mapear(f['away'], list(eng.equipos), contexto='t')
            if h and a and h != a:
                par = (h, a, f); break
        if not par:
            print(f'{clave}: sin fixture mapeable ({len(fx)} fixtures)'); continue
        h, a, f = par
        print(f'{clave}: {h} vs {a}   ({f.get("fecha")})')
        eid = ca.buscar_event_id(clave, h, a)
        print(f'  vía ESPN (event_id): {eid or "NO ENCONTRADO"}')
        res = cm.cuotas_partido('futbol', h, a,
                                fecha=f.get('inicio') or f.get('fecha'))
        print(f'  casas en el tablón: {res.get("n_casas")} '
              f'{sorted(k for k in (res.get("casas") or {}) if not k.startswith("_"))}')
        filas = ct.filas_del_tablon(res, h, a)
        print(f'  filas del tablón: {len(filas)}')
        pl = eng.plantilla_club(h, a)
        mk = ct.mercados_con_ev(res, pl, h, a)
        print(f'  MERCADOS CON EV: {len(mk)}')
        for r in mk[:10]:
            print(f'    {r["ev"]*100:+6.1f}%  {r["apuesta"]:<34} '
                  f'{r["cuota_casa"]:>7} ({r["casa"]}, {r["n_casas"]} casas) '
                  f'justa {r["cuota_justa"]}')
        s = ct.resumen_line_shopping(res)
        if s: print('  ', s.replace('**',''))
    except Exception as e:
        import traceback; traceback.print_exc()
