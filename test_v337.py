#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test de la v337.

El usuario: «¿las rojas tienen algún patrón de que sea alguna liga específica?
Puede que haga falta calibrar el modelo ahí».

Lo que se vigila:

  1. EL PRECIO DE LOS GOLES POR EQUIPO: «Goles X: Más de 1.5» se de-margina
     con las cuotas DEL EQUIPO, nunca con la línea del total del partido (el
     error que se encontró buscando el patrón por liga); sin cuota del equipo
     no hay precio; los goles del partido siguen igual.
  2. LO MEDIDO: no hay ligas que fallen de forma persistente (calibrar por liga
     no pasa) y la corrección mejora la simulación rehecha en los dos tramos.

Ejecutar:  python test_v337.py
"""
import json
import os

FALLOS = []


def check(cond, msg):
    print(('OK   ' if cond else 'FALLO') + ' ' + msg)
    if not cond:
        FALLOS.append(msg)


def probar_el_precio():
    import concordancia as c
    pick = {'partido': 'Boca vs River',
            'implicitas': {'goles': {'1.5': {'mas': 1.25, 'menos': 3.8}},
                           'goles_home': {'1.5': {'mas': 2.6, 'menos': 1.48}},
                           'goles_away': {'0.5': {'mas': 1.35, 'menos': 3.0}}}}
    p = c.prob_mercado(pick, 'Goles Boca: Más de 1.5', 'Goles equipo')
    check(p is not None and abs(p - (1 / 2.6) / (1 / 2.6 + 1 / 1.48)) < 1e-9,
          'equipo local más de 1,5 sale de SUS cuotas (%.3f)' % (p or -1))
    q = c.prob_mercado(pick, 'Goles Boca: Menos de 1.5', 'Goles equipo')
    check(q is not None and abs(p + q - 1) < 1e-9, 'y el menos es el complemento')
    check(c.prob_mercado(pick, 'Goles River: Más de 0.5', 'Goles equipo') is not None,
          'la visita usa las suyas')
    check(c.prob_mercado(pick, 'Goles River: Más de 1.5', 'Goles equipo') is None,
          'sin cuota del equipo en esa línea: sin precio (no la del partido)')
    t = c.prob_mercado(pick, 'Goles: Más de 1.5', 'Goles')
    check(t is not None and abs(t - (1 / 1.25) / (1 / 1.25 + 1 / 3.8)) < 1e-9,
          'los goles del PARTIDO siguen con la línea del partido')
    check(c.prob_mercado(pick, 'Goles Boca: Más de 1.5', 'Goles equipo')
          != c.prob_mercado(pick, 'Goles: Más de 1.5', 'Goles'),
          'equipo y partido ya no dan el mismo número')


def probar_lo_medido():
    for f in ('_v337_ligas.json', '_v337_compara.json'):
        check(os.path.exists(f), 'existe %s' % f)
    if os.path.exists('_v337_ligas.json'):
        r = json.load(open('_v337_ligas.json', encoding='utf-8'))
        check(r['persistencia'][1] < 0.5,
              'el exceso por liga apenas persiste (correlación %.2f)' % r['persistencia'][1])
        check(all(v['p5'] <= 0 for v in r['quitar'].values()),
              'quitar ligas «malas» no pasa el p5 (no se activa)')
    if os.path.exists('_v337_compara.json'):
        c = json.load(open('_v337_compara.json', encoding='utf-8'))
        for t in ('mirar', 'juzgar', 'todo'):
            a, d = c[t]['antes'], c[t]['despues']
            check(d[0] >= a[0], 'simulación rehecha, %s: %.1f → %.1f %%' % (t, 100 * a[0], 100 * d[0]))
        check(c['boot'][1] > 0, 'juicio de la simulación con p5 %+.2f > 0' % c['boot'][1])


if __name__ == '__main__':
    print('=== 1. el precio de los goles por equipo ===')
    probar_el_precio()
    print('\n=== 2. lo medido ===')
    probar_lo_medido()
    print('\n' + '=' * 40)
    print('TODO OK' if not FALLOS else '%d FALLOS' % len(FALLOS))
    raise SystemExit(1 if FALLOS else 0)
