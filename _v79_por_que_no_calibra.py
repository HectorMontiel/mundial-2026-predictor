#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v79 — Instrumenta `_mercados_del_partido` para ver POR QUÉ no se calibra.

Datos ya establecidos:
  · Pinnacle publica 634 partidos de fútbol y cubre el 73 % de los de hoy.
  · 23 de 160 fixtures llegan con `odd_home_pin`.
  · 0 de 41 picks de fútbol salen con corrección de mercado.

Se envuelve la función y se registra, en cada llamada, cuál de las tres
condiciones falla: falta `clave_liga`, falta la cuota de Pinnacle, o no hay
probabilidad justa que calcular.
"""
import logging
from collections import Counter

logging.basicConfig(level=logging.WARNING)

CUENTA = Counter()
EJEMPLOS = []


def main():
    import alpha_finder

    orig = alpha_finder._mercados_del_partido

    def espia(pred, o, home, away, clave_liga=None):
        tiene_pin = bool(o.get('pin_home') and o.get('pin_away'))
        if not clave_liga and not tiene_pin:
            CUENTA['sin clave_liga NI Pinnacle'] += 1
        elif not clave_liga:
            CUENTA['SIN clave_liga (pero CON Pinnacle)'] += 1
            if len(EJEMPLOS) < 5:
                EJEMPLOS.append(f'{home} vs {away}: hay Pinnacle pero '
                                f'clave_liga=None')
        elif not tiene_pin:
            CUENTA['con clave_liga, SIN Pinnacle'] += 1
        else:
            CUENTA['AMBOS presentes -> se calibra'] += 1
        return orig(pred, o, home, away, clave_liga)

    alpha_finder._mercados_del_partido = espia
    alpha_finder.apuestas_del_dia(max_partidos=40)

    total = sum(CUENTA.values())
    print(f'\n{total} evaluaciones de mercados\n')
    for k, v in CUENTA.most_common():
        print(f'  {v:5d}  ({v/max(total,1):5.1%})  {k}')
    if EJEMPLOS:
        print('\nCasos con Pinnacle desaprovechado por falta de clave:')
        for e in EJEMPLOS:
            print(f'   · {e}')


if __name__ == '__main__':
    main()
