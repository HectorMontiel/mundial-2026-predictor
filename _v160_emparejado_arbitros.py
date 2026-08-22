# -*- coding: utf-8 -*-
"""v160 - que fixtures no encuentran su partido en FotMob, y por que."""
import logging
from difflib import SequenceMatcher

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
        f = dict(f)
        f['clave_liga'] = clave
        fixtures.append(f)

fechas = sorted({str(f['fecha'])[:10] for f in fixtures})
idx = {d: ap.indice_dia(d) for d in fechas}

print('%-9s %-44s %-6s %s' % ('liga', 'fixture', 'score', 'mejor candidato de FotMob'))
fallos = 0
for f in fixtures:
    fecha = str(f['fecha'])[:10]
    m = ap._empareja(f['home'], f['away'], idx.get(fecha) or [])
    if m:
        continue
    fallos += 1
    oh, oa = ap._norm(f['home']), ap._norm(f['away'])
    mejor, mp = None, 0.0
    for c in (idx.get(fecha) or []):
        p = min(SequenceMatcher(None, oh, ap._norm(c['home'])).ratio(),
                SequenceMatcher(None, oa, ap._norm(c['away'])).ratio())
        if p > mp:
            mejor, mp = c, p
    print('%-9s %-44s %.3f  %s' % (
        f['clave_liga'], ('%s vs %s' % (f['home'], f['away']))[:44], mp,
        ('%s vs %s  [%s]' % (mejor['home'], mejor['away'], mejor['liga'])) if mejor else '-'))
print()
print('fixtures %d · sin emparejar %d' % (len(fixtures), fallos))
