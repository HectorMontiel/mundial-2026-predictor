#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Cuantos partidos pasan de estadistica ESTIMADA a OBSERVADA con el enchufe.

`origen: 'estimado'` quiere decir que la competicion no pudo dar una lambda por
equipo y se reparte el nivel medio entre los dos bandos: los dos equipos salen
con el mismo numero. `origen: 'observado'` es una lambda calculada con partidos
de verdad.

Se recorren los proximos partidos de las competiciones donde el enchufe aplica.
"""
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8',
                              errors='replace')

import fixtures_espn as fe
import perfil_liga_local as plc
import rendimiento_equipos as rq

COMPS = ('champions', 'europa_league', 'conference_league')


def mide(con_enchufe):
    if not con_enchufe:
        plc.COMPETICIONES = ()
    else:
        plc.COMPETICIONES = COMPS
    filas = []
    for comp in COMPS:
        try:
            fx = fe.fixtures_liga(comp, dias=7)
        except Exception:
            continue
        for f in fx:
            h, a = f.get('home'), f.get('away')
            if not h or not a:
                continue
            for objetivo, fn in (('corners', rq.corners_equipo),
                                 ('tarjetas', rq.tarjetas_equipo)):
                try:
                    r = fn(comp, h, a)
                except Exception:
                    r = None
                filas.append((comp, '%s vs %s' % (h, a), objetivo,
                              (r or {}).get('origen'),
                              (r or {}).get('lambda_home'),
                              (r or {}).get('lambda_away')))
    return filas


def main():
    rq._historico.cache_clear() if hasattr(rq._historico, 'cache_clear') else None
    sin = mide(False)
    con = mide(True)
    print('%-14s %-8s %-10s %-10s' % ('competicion', 'stat', 'SIN', 'CON'))
    cambios = 0
    for a, b in zip(sin, con):
        c1, p1, s1, o1, lh1, la1 = a
        c2, p2, s2, o2, lh2, la2 = b
        if o1 != o2:
            cambios += 1
            print('  %-38s %-9s %-10s -> %-10s (%s/%s)'
                  % (p1[:38], s1, o1 if o1 else '-', o2 if o2 else '-',
                     lh2, la2))
    n = len(sin)
    est_sin = sum(1 for x in sin if x[3] == 'estimado')
    est_con = sum(1 for x in con if x[3] == 'estimado')
    obs_sin = sum(1 for x in sin if x[3] == 'observado')
    obs_con = sum(1 for x in con if x[3] == 'observado')
    print()
    print('casos (partido x estadistica): %d' % n)
    print('  observado   SIN enchufe %3d  ->  CON enchufe %3d' % (obs_sin, obs_con))
    print('  estimado    SIN enchufe %3d  ->  CON enchufe %3d' % (est_sin, est_con))
    print('  cambian: %d' % cambios)
    return 0


if __name__ == '__main__':
    sys.exit(main())
