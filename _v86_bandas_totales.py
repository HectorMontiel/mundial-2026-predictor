#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v86 — Muestra las bandas de acierto real de Goles y BTTS."""
import sys

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

import calibracion_confianza as cc

b = cc.bandas_de_totales()
for merc, filas in b.items():
    print(f'=== {merc} ===')
    print(f'{"banda":>13} {"n":>7} {"modelo":>9} {"real":>9} {"sesgo":>9} '
          f'{"p5 acierto":>11}')
    for f in filas:
        if f.get('acierto') is None:
            print(f'  {f["desde"]:.2f}-{f["hasta"]:.2f} {f["n"]:7d}   '
                  f'(muestra insuficiente)')
        else:
            print(f'  {f["desde"]:.2f}-{f["hasta"]:.2f} {f["n"]:7d} '
                  f'{f["prob_media_modelo"]:9.1%} {f["acierto"]:9.1%} '
                  f'{f["sesgo"]:+9.1%} {f["acierto_p5"]:11.1%}')
    print()

print('¿hay medición ahora?')
for m in ('1X2', 'Goles', 'BTTS', 'Hándicap asiático', 'Ganador'):
    print(f'  {m:22s} {cc.hay_medicion(m)}')
