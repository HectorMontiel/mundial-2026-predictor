#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test de la v333.

El usuario: «quiero una nueva manera de ver las cosas, algún modelo
matemático nuevo… y que lo valides con simulaciones; tenemos histórico
amplio, incluso las cuotas».

Lo que se vigila:

  1. EL MOTOR DE MERCADO (`motor_mercado.py`) hace lo que dice: recupera las
     λ de las que salió un 1X2, la tabla en lote da lo mismo que el cálculo
     exacto, las probabilidades suman lo que deben y el hándicap asiático
     reparte bien las devoluciones.
  2. LO MEDIDO SIGUE DICIENDO LO MISMO: el motor gana al modelo en log-loss
     en los mercados que deriva, sus conjuntas calibran, y ni Novibet ni
     Playdoit tienen patas sólidas mal puestas que den dinero.

Ejecutar:  python test_v333.py
"""
import json
import os

import numpy as np

FALLOS = []


def check(cond, msg):
    print(('OK   ' if cond else 'FALLO') + ' ' + msg)
    if not cond:
        FALLOS.append(msg)


def probar_el_motor():
    import motor_mercado as mm
    m = mm.matriz(1.6, 1.1)
    check(abs(m.sum() - 1) < 1e-9, 'la matriz de marcadores suma 1')
    p = mm.probabilidades(1.6, 1.1)
    check(abs(p['Gana local'] + p['Empate'] + p['Gana visita'] - 1) < 1e-9,
          'el 1X2 suma 1')
    check(abs(p['Más de 2.5'] + p['Menos de 2.5'] - 1) < 1e-9, 'más + menos de 2,5 = 1')
    check(p['Local o empate'] > p['Gana local'], 'la doble oportunidad cubre más que el ganador')
    l = mm.lambdas(p['Gana local'], p['Empate'], p['Gana visita'], p['Más de 2.5'])
    check(l is not None and abs(l[0] - 1.6) < 0.02 and abs(l[1] - 1.1) < 0.02,
          'recupera las λ de las que salió el precio (%s)' % (l,))
    T = mm.tabla()
    i = mm.lote([p['Gana local']], [p['Gana visita']], [p['Más de 2.5']])[0]
    check(abs(T['lh'][i] - 1.6) <= 0.03 and abs(T['la'][i] - 1.1) <= 0.03,
          'la tabla en lote da las mismas λ (%.2f, %.2f)' % (T['lh'][i], T['la'][i]))
    check(abs(T['P']['Más de 1.5'][i] - p['Más de 1.5']) < 0.01,
          'y las mismas probabilidades derivadas')
    # hándicap: con cuota justa 1/p y sin empate posible el valor es 0
    ph = p['Gana local']
    evh, _ = mm.handicap_ev(1.6, 1.1, -0.5, 1 / ph, 2.0)
    check(abs(evh) < 1e-6, 'hándicap −0,5 a cuota justa vale 0 (%.4f)' % evh)
    ev0, _ = mm.handicap_ev(1.6, 1.1, 0.0, 2.0, 2.0)
    esperado = p['Gana local'] * 2.0 + p['Empate'] - 1
    check(abs(ev0 - esperado) < 1e-9,
          'hándicap 0: el empate devuelve lo apostado (%.4f = %.4f)' % (ev0, esperado))
    evq, _ = mm.handicap_ev(1.6, 1.1, -0.25, 2.0, 2.0)
    esperado_q = (p['Gana local'] * 2.0 - 1 + (p['Gana local'] * 2.0 + p['Empate'] - 1)) / 2
    check(abs(evq - esperado_q) < 1e-9, 'hándicap −0,25: media en −0,5 y media en 0')
    check(mm.sin_margen(2.0, 2.0) == [0.5, 0.5], 'quitar el margen de 2,00 / 2,00 da 50 / 50')


def probar_lo_medido():
    for f in ('_v333_motor.json', '_v333_novibet_interno.json',
              '_v333_playdoit_pinnacle.json', '_v333_constructor.json'):
        check(os.path.exists(f), 'existe %s' % f)
    if os.path.exists('_v333_motor.json'):
        r = json.load(open('_v333_motor.json', encoding='utf-8'))
        for k, v in r['juicio'].items():
            check(v['motor'][0] < v['modelo'][0],
                  'el motor gana al modelo en log-loss en «%s»' % k)
        check(abs(r['rho'] - (-0.06)) < 1e-9, 'el ρ de Dixon-Coles es el elegido al mirar (−0,06)')
    if os.path.exists('_v333_constructor.json'):
        c = json.load(open('_v333_constructor.json', encoding='utf-8'))
        check(all(abs(v['conjunta'] - v['real']) < 0.025 for v in c.values()),
              'las conjuntas del motor calibran (< 2,5 pts)')
        check(c['Gana favorito + Más de 2.5']['conjunta'] /
              c['Gana favorito + Más de 2.5']['producto'] > 1.1,
              '«gana favorito + más de 2,5» van juntas (factor > 1,1)')
    if os.path.exists('_v333_novibet_interno.json'):
        n = json.load(open('_v333_novibet_interno.json', encoding='utf-8'))
        check(n['solidas'][3] < 0, 'las sólidas «de valor» de Novibet NO pasan el p5 (no se activa)')


if __name__ == '__main__':
    print('=== 1. el motor ===')
    probar_el_motor()
    print('\n=== 2. lo medido ===')
    probar_lo_medido()
    print('\n' + '=' * 40)
    print('TODO OK' if not FALLOS else '%d FALLOS' % len(FALLOS))
    raise SystemExit(1 if FALLOS else 0)
