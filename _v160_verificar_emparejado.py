# -*- coding: utf-8 -*-
"""v160 - los 48 emparejados, uno a uno, para poder mirarlos.

Un emparejado FALSO es el fallo caro: pone el arbitro de otro partido y mueve
la probabilidad sin dejar rastro. Asi que se imprimen todos con su puntuacion
y se marca cualquiera que no sea obviamente el mismo partido.
"""
import logging
logging.basicConfig(level=logging.WARNING)
import fixtures_espn
import rendimiento_equipos as rq
import arbitro_partido as ap
from config import LEAGUES

claves = [c for c, cfg in LEAGUES.items()
          if cfg.get('disponible') and c in fixtures_espn.ESPN_CODIGOS
          and rq.stats_disponibles(c).get('tarjetas')]
por_liga = fixtures_espn.fixtures_multi(claves, dias=2)
fixtures = []
for clave, fx in (por_liga or {}).items():
    for f in (fx or []):
        f = dict(f); f['clave_liga'] = clave; fixtures.append(f)

fechas = sorted({str(f['fecha'])[:10] for f in fixtures})
idx = {d: ap.indice_dia(d) for d in fechas}

print('%-17s %-40s %-40s %-6s %s' % ('liga', 'nuestro fixture', 'FotMob', 'score', 'liga FotMob'))
dudosos = 0
for f in sorted(fixtures, key=lambda x: x['clave_liga']):
    fecha = str(f['fecha'])[:10]
    m = ap._empareja(f['home'], f['away'], idx.get(fecha) or [])
    if not m:
        print('%-17s %-40s %-40s %-6s %s' % (f['clave_liga'],
              ('%s vs %s' % (f['home'], f['away']))[:40], '(sin emparejar)', '-', ''))
        continue
    p = min(ap._similitud(f['home'], m['home']), ap._similitud(f['away'], m['away']))
    marca = ''
    if p < 0.75:
        marca = '  <-- REVISAR'
        dudosos += 1
    print('%-17s %-40s %-40s %.3f  %s%s' % (
        f['clave_liga'], ('%s vs %s' % (f['home'], f['away']))[:40],
        ('%s vs %s' % (m['home'], m['away']))[:40], p, m['liga'], marca))
print()
print('fixtures %d · con score por debajo de 0,75 (a revisar a ojo): %d'
      % (len(fixtures), dudosos))
