# -*- coding: utf-8 -*-
"""v160 - como llama Playdoit a los mercados de tarjetas, para no filtrar por
una lista escrita a mano que se quede vieja en silencio."""
import logging
logging.basicConfig(level=logging.WARNING)
import cuotas_multi as cm
import fixtures_espn
import rendimiento_equipos as rq
from config import LEAGUES

claves = [c for c, cfg in LEAGUES.items()
          if cfg.get('disponible') and c in fixtures_espn.ESPN_CODIGOS
          and rq.stats_disponibles(c).get('tarjetas')]
fx = fixtures_espn.fixtures_multi(claves[:8], dias=2)
probados = 0
familias = {}
for clave, lista in (fx or {}).items():
    for f in (lista or [])[:3]:
        h, a = f.get('home'), f.get('away')
        if not h or not a:
            continue
        probados += 1
        try:
            t = cm.mercados_playdoit('futbol', h, a) or {}
        except Exception as e:
            print('  %s vs %s: %s' % (h, a, e))
            continue
        ms = t.get('mercados') or []
        if not ms:
            continue
        print('=== %s | %s vs %s : %d familias' % (clave, h, a, len(ms)))
        for fam in ms:
            n = str(fam.get('nombre') or '')
            familias[n] = familias.get(n, 0) + 1
            low = n.lower()
            if any(k in low for k in ('tarjeta', 'card', 'amarilla', 'roja',
                                      'amonesta', 'booking')):
                sel = [s.get('nombre') for s in (fam.get('selecciones') or [])][:6]
                print('   TARJETAS -> %-42s sv=%-6s %s' % (n, fam.get('sv'), sel))
        if probados >= 8:
            break
    if probados >= 8:
        break

print()
print('TODAS las familias vistas (%d distintas):' % len(familias))
for n, c in sorted(familias.items(), key=lambda t: -t[1]):
    print('  %3d  %s' % (c, n))
