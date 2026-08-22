#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v154 — DENTRO DE LA RAMA DE FÚTBOL: qué parte de los 61,5 s es cada cosa.

El perfil por ramas dijo que el fútbol es el techo (61,5 s contra 24,3 del
tenis, que es la siguiente). Con el precálculo del bot, cargar modelos y
predecir ya no están en esa cuenta, así que lo que queda es RED: los fixtures de
ESPN, las cuotas por liga y la consulta de precio partido a partido.

Se cronometra cada fase por separado, no acumulando por función.
"""
import logging
import time
import warnings

warnings.filterwarnings('ignore')
logging.basicConfig(level=logging.ERROR)

import fixtures_espn
from config import LEAGUES


def main():
    claves = [c for c, cfg in LEAGUES.items()
              if cfg.get('disponible') and c in fixtures_espn.ESPN_CODIGOS]
    print('competiciones activas: %d' % len(claves))

    t = time.time()
    fx = fixtures_espn.fixtures_multi(claves, dias=3)
    t_fix = time.time() - t
    con = {k: v for k, v in fx.items() if v}
    n = sum(len(v) for v in con.values())
    print('1. fixtures_multi ............ %6.1f s  (%d competiciones, '
          '%d partidos)' % (t_fix, len(con), n))

    # 2. las cuotas ricas por competición
    t = time.time()
    total_odds = 0
    for clave in list(con)[:8]:
        ids = [f.get('event_id') for f in con[clave]][:12]
        try:
            o = fixtures_espn.odds_multi(clave, ids)
            total_odds += len(o or {})
        except Exception:
            pass
    t_odds = time.time() - t
    print('2. odds_multi (8 ligas) ...... %6.1f s  (%d con cuota) '
          '-> ~%.1f s las %d'
          % (t_odds, total_odds, t_odds / 8 * len(con), len(con)))

    # 3. el precio partido a partido, que es lo que se sospecha
    import cuotas_multi as cm
    muestra = []
    for clave, lista in con.items():
        for f in lista[:2]:
            if f.get('home') and f.get('away'):
                muestra.append((clave, f['home'], f['away']))
        if len(muestra) >= 10:
            break
    t = time.time()
    hechos = 0
    for _clave, h, a in muestra[:10]:
        try:
            cm.valor_vs_sharp('futbol', h, a)
            hechos += 1
        except Exception:
            pass
    t_vs = time.time() - t
    print('3. valor_vs_sharp (10) ....... %6.1f s  (%.2f s por partido)'
          % (t_vs, t_vs / max(hechos, 1)))
    print()
    print('   con ~130 partidos de hoy: %.0f s si fuera en serie'
          % (t_vs / max(hechos, 1) * 130))

    # 4. qué fuentes contesta cada una, y cuánto tarda
    print()
    print('4. POR FUENTE (un partido, la primera de la muestra):')
    if muestra:
        _c, h, a = muestra[0]
        for nombre, fn in (
                ('precargar futbol', lambda: cm.precargar('futbol')),
                ('cuotas_partido', lambda: cm.cuotas_partido('futbol', h, a)),
                ('valor_vs_sharp', lambda: cm.valor_vs_sharp('futbol', h, a)),
                ('mercados_playdoit', lambda: cm.mercados_playdoit('futbol', h, a)),
        ):
            t = time.time()
            try:
                r = fn()
                print('   %-20s %6.2f s  %s' % (nombre, time.time() - t,
                                                type(r).__name__))
            except Exception as e:
                print('   %-20s   FALLO %s' % (nombre, type(e).__name__))


if __name__ == '__main__':
    main()
