#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v79 — ¿Por qué NINGÚN pick de fútbol recibe el encogimiento?

Medido en el barrido de hoy: 0 de 41 picks de fútbol llevan corrección de
mercado. La condición que la activa es
`clave_liga and o['pin_home'] and o['pin_away']`, y `pin_home` solo se rellena
si `cuotas_partido` devolvió bloque `pinnacle` para ese partido.

Hay dos explicaciones posibles y hay que distinguirlas con datos:

  A) Pinnacle no cubre las ligas que juegan hoy (sudamericanas, Liga MX, MLS).
     Sería una limitación de la fuente, no un fallo — pero significa que los
     picks que salen HOY no son los que se validaron con w=0,25.

  B) Pinnacle sí las cubre y el emparejamiento falla. Sería un fallo nuestro y
     tendría arreglo.
"""
import logging
from collections import Counter

logging.basicConfig(level=logging.WARNING)


def main():
    import config
    import cuotas_multi as cm
    import fixtures_espn

    cm.precargar('futbol')
    idx = cm._indice('futbol') or {}
    print(f'Pinnacle publica {len(idx)} partidos de fútbol ahora mismo\n')

    activas = [c for c in config.LEAGUES if c in fixtures_espn.ESPN_CODIGOS]
    fx = fixtures_espn.fixtures_multi(activas, dias=1)

    res = Counter()
    detalle = []
    for liga, partidos in fx.items():
        for p in partidos[:60]:
            r = cm.cuotas_partido('futbol', p['home'], p['away'])
            pin = r.get('pinnacle') or {}
            mejor = r.get('mejor') or {}
            tiene_pin = bool(pin.get('home') and pin.get('away'))
            tiene_precio = bool(mejor.get('home'))
            res[(liga, tiene_pin)] += 1
            if tiene_precio and not tiene_pin:
                detalle.append((liga, p['home'], p['away'],
                                r.get('casas')))

    print(f"{'liga':26s} {'partidos':>9} {'con Pinnacle':>13}")
    print('-' * 52)
    ligas = sorted({k[0] for k in res})
    tot_p = tot_pin = 0
    for liga in ligas:
        con = res[(liga, True)]
        sin = res[(liga, False)]
        if con + sin == 0:
            continue
        tot_p += con + sin
        tot_pin += con
        print(f'{liga:26s} {con+sin:9d} {con:13d}')
    print('-' * 52)
    print(f"{'TOTAL':26s} {tot_p:9d} {tot_pin:13d}")
    if tot_p:
        print(f'\nCobertura de Pinnacle en fútbol hoy: '
              f'{tot_pin}/{tot_p} = {tot_pin/tot_p:.1%}')

    if detalle:
        print(f'\n{len(detalle)} partidos CON precio pero SIN Pinnacle '
              f'(muestra de 10):')
        for liga, h, a, casas in detalle[:10]:
            print(f'   {liga:20s} {h} vs {a}   casas={casas}')


if __name__ == '__main__':
    main()
