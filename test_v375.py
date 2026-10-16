#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test de la v375: el tope de cuota 1,25 de la «se mete».

Medido (`_v375_rojas.py`, 2.009 «se mete» del 3 al 15-oct): a más de 1,25
aciertan 68 / 75 % en las dos mitades; con el tope, 77,0 → 82,9 % y 81,6 →
82,9 % (p5 de la diferencia +9 / +2 pts). La NHL va aparte (ganador medido con
siete temporadas a 1,30-1,40).

Ejecutar:  python test_v375.py
"""
import json

FALLOS = []


def check(cond, msg):
    print(('OK   ' if cond else 'FALLO') + ' ' + msg)
    if not cond:
        FALLOS.append(msg)


def probar():
    import veredicto_pick as vp
    v = vp._evaluar_sin_tope
    vp._evaluar_sin_tope = lambda p, c=False: {'veredicto': vp.METER, 'razones': ['x']}
    try:
        r = vp.evaluar({'cuota': 1.30, 'deporte': 'Fútbol'})
        check(r['veredicto'] == vp.NO_METER and '1.25' in r['razones'][0],
              'a 1,30 ya no es «se mete», y dice por qué')
        check(vp.evaluar({'cuota': 1.25, 'deporte': 'Fútbol'})['veredicto'] == vp.METER,
              'a 1,25 sí')
        check(vp.evaluar({'cuota': 1.36, 'deporte': 'NBA'})['veredicto'] == vp.METER and vp.evaluar({'cuota': 1.36, 'deporte': 'NHL'})['veredicto'] == vp.METER
              and vp.evaluar({'cuota': 1.36, 'nhl_linea': True})['veredicto'] == vp.METER,
              'la NHL queda fuera del tope (su ganador está medido aparte)')
    finally:
        vp._evaluar_sin_tope = v
    t = json.load(open('_v375_tope.json', encoding='utf-8'))
    check(t['1.25 A']['p5_dif_vs_quitadas'] > 0 and t['1.25 B']['p5_dif_vs_quitadas'] > 0,
          'lo medido queda guardado (p5 > 0 en las dos mitades)')


if __name__ == '__main__':
    probar()
    print('\n' + '=' * 40)
    print('TODO OK' if not FALLOS else '%d FALLOS' % len(FALLOS))
    raise SystemExit(1 if FALLOS else 0)
