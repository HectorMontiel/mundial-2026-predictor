#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test de la v392: las ligas grandes NO pierden sus estadísticas observadas.

CAUSA RAÍZ (5 porqués, 17-oct): desde el 10-oct ESPN completó ~10 partidos
recientes de la Premier, LaLiga, Bundesliga y Eredivisie y los marcó como
`stats_origen = espn`. `_solo_reales` daba por hecho que, habiendo filas
marcadas, las demás eran sintéticas: con 10 (< 200) devolvía NADA y se
perdían las 6.130 filas observadas de football-data. Resultado: sin media de
córners, tarjetas ni remates en las cuatro ligas grandes, y 5 comprobaciones
del catálogo en rojo que se dieron por «preexistentes».

Esta prueba es RÁPIDA (corre con las demás, no sólo en el catálogo largo) y
mira las cuatro ligas a la vez, para que algo así se vea el mismo día.

Ejecutar:  python test_v392.py
"""
FALLOS = []


def check(cond, msg):
    print(('OK   ' if cond else 'FALLO') + ' ' + msg)
    if not cond:
        FALLOS.append(msg)


def probar():
    import pandas as pd
    import rendimiento_equipos as rq
    for liga in ('premier', 'laliga', 'bundesliga', 'eredivisie'):
        h = rq._historico(liga)
        if h is None or getattr(h, 'empty', True):
            continue
        m = rq.media_corners_liga(liga)
        d = rq.dispersion_corners_liga(liga)
        check(m is not None and 7 <= m <= 13 and d is not None and 1.0 <= d <= 1.6,
              '%s: media de córners (%s) y dispersión (%s) observadas' % (liga, m, d))
        r = rq._solo_reales(h, 'corners')
        check(r is not None and len(r) >= 0.9 * h['home_corners'].notna().sum(),
              '%s: las filas observadas de football-data no se tiran por tener unas pocas de ESPN (%d de %d)'
              % (liga, 0 if r is None else len(r), len(h)))
    # filas cuyos córners son del generador, con 10 de ESPN: no se inventa una
    # media (v393: la Liga MX ya tiene los suyos reales; se usan sus filas
    # de antes de 2021, que son sintéticas)
    mx = rq._historico('liga_mx')
    if mx is not None and not getattr(mx, 'empty', True) and 'stats_origen' in mx:
        sint = mx[mx['stats_origen'].isna()].tail(600).copy()
        sint['stats_origen'] = None
        sint.loc[sint.index[-10:], 'stats_origen'] = 'espn'
        check(len(sint) < 60 or len(rq._solo_reales(sint, 'corners')) == 0,
              'unas filas con córners sintéticos no inventan una media')
    # caso pequeño: 10 marcadas + filas reales sin marca → se usan todas
    h = rq._historico('premier')
    if h is not None and not getattr(h, 'empty', True):
        mezcla = h.tail(600).copy()
        mezcla['stats_origen'] = None
        mezcla.loc[mezcla.index[-10:], 'stats_origen'] = 'espn'
        check(len(rq._solo_reales(mezcla, 'corners')) == len(mezcla),
              'con 10 filas de ESPN y el resto observado, se usan todas')


if __name__ == '__main__':
    probar()
    print('\n' + '=' * 40)
    print('TODO OK' if not FALLOS else '%d FALLOS' % len(FALLOS))
    raise SystemExit(1 if FALLOS else 0)
