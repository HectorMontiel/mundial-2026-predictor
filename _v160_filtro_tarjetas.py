# -*- coding: utf-8 -*-
"""v160 - el filtro de familias de tarjetas contra el tablero COMPLETO.

Un filtro asi no se valida con los casos que a uno se le ocurren: se valida
pidiendo las 851 familias que la casa cotiza en un partido y mirando cuales
pasan y cuales no. Lo que pasa se imprime entero, para poder leerlo.
"""
import logging
logging.basicConfig(level=logging.WARNING)
import cuotas_multi as cm
import snapshots_tarjetas as st

PARTIDOS = [('futbol', 'Eyupspor', 'Gaziantep FK'),
            ('futbol', 'Brighton & Hove Albion', 'Aston Villa'),
            ('futbol', 'Atlético Madrid', 'Villarreal')]

todas, pasan = set(), set()
for dep, h, a in PARTIDOS:
    try:
        t = cm.mercados_playdoit(dep, h, a) or {}
    except Exception as e:
        print('  %s vs %s: %s' % (h, a, e))
        continue
    ms = t.get('mercados') or []
    print('%s vs %s: %d familias' % (h, a, len(ms)))
    for fam in ms:
        n = str(fam.get('nombre') or '')
        todas.add(n)
        if st._es_tarjeta(n):
            pasan.add(n)

print()
print('familias distintas vistas: %d' % len(todas))
print('familias que PASAN el filtro: %d' % len(pasan))
for n in sorted(pasan):
    print('   +  %s' % n)

print()
print('familias con palabra de tarjeta que se DESCARTAN (deben ser todas de jugador):')
for n in sorted(todas - pasan):
    low = st._sin_parentesis(n).lower()
    if any(p in low for p in st._PALABRAS):
        print('   -  %s' % n)
