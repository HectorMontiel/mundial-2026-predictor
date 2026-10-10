#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test de la v356.

El usuario, con las rojas del 8 y 9-oct (todas de goles): «analiza por qué no
se cumplieron, haz un modelo de anticipación, que haya menos rojas y más
verdes sin bajar el estándar».

Lo que se vigila:
  1. LO MEDIDO: el «modelo de anticipación» (acuerdo del modelo de goles con
     la casa) NO mejora; quitar «Más de 1.5» arregla esos dos días pero pierde
     verdes; lo que sí mejora en las dos mitades es quitar «córners: más de» y
     una tercera «se mete» de ≥ 78 %.
  2. LA REGLA en la tarjeta, el precálculo y el archivo.

Ejecutar:  python test_v356.py
"""
import json

FALLOS = []


def check(cond, msg):
    print(('OK   ' if cond else 'FALLO') + ' ' + msg)
    if not cond:
        FALLOS.append(msg)


def probar_medicion():
    m = json.load(open('_v356_anticipar.json', encoding='utf-8'))
    j = m['H2_juzga']
    check(j['boot']['acierto_dif'] <= 0.002,
          'cambiar las de goles en desacuerdo con el modelo no mejora (%+.1f pts al juzgar)'
          % (100 * j['boot']['acierto_dif']))
    check(m['H3_menos35_cuando_falla_mas15']['acierta'] == 1.0,
          'la «otra cola» se cumple siempre que falla la primera (no anticipa nada)')


def probar_regla():
    import modo_modelo as mm
    check(mm.corners_mas_total({'apuesta': 'Córners: Más de 8.5'})
          and mm.corners_mas_total({'apuesta': 'Córners: Menos de 12.5'}) is None
          and mm.corners_mas_total({'apuesta': 'Córners Local: Más de 4.5'}) is None,
          '«córners: más de» (total) no se mete; los «menos» y los de equipo siguen su regla')
    recos = [{'apuesta': 'Goles: Más de 1.5', 'mercado': 'Goles', 'veredicto_vp': 'meter'},
             {'apuesta': 'A o empate', 'mercado': 'Doble oportunidad', 'veredicto_vp': 'meter'}]
    otras = [{'apuesta': 'Córners: Menos de 12.5', 'mercado': 'Córners', 'prob_meter': 0.82},
             {'apuesta': 'Tarjetas: Menos de 5.5', 'mercado': 'Tarjetas', 'prob': 0.80}]
    r = mm.con_tercera(recos, otras)
    met = mm.metidas(r)
    check(len(met) == 3 and met[2]['apuesta'] == 'Córners: Menos de 12.5' and met[2]['tercera'],
          'la tercera es la mejor de «también se meten» si llega al 78 %% (%s)' % [x['apuesta'] for x in met])
    baja = [{'apuesta': 'Tarjetas: Menos de 5.5', 'mercado': 'Tarjetas', 'prob': 0.76}]
    check(len(mm.metidas(mm.con_tercera(recos, baja))) == 2, 'si la mejor no llega al 78 %, dos')
    # v357 — y «goles de un equipo: menos de» nunca es tercera (67 / 45 %)
    eq = [{'apuesta': 'Goles B: Menos de 2.5', 'mercado': 'Goles equipo', 'prob_meter': 0.85}]
    check(len(mm.metidas(mm.con_tercera(recos, eq))) == 2,
          '«goles de un equipo: menos de» no sale de tercera (acertaba 67 y 45 %)')
    check(len(mm.metidas(recos + [dict(recos[0], apuesta='x')])) == 2,
          'sin la marca de tercera, siguen siendo como mucho dos')
    dd = open('decisiones_dia.py', encoding='utf-8').read()
    pj = open('partidos_jugados.py', encoding='utf-8').read()
    an = open('anunciadas.py', encoding='utf-8').read()
    check('mm.con_tercera(' in dd and 'mm.con_tercera(' in pj and "r.get('tercera')" in an,
          'y la llevan el precálculo, el archivo al empezar (semáforo) y las anunciadas')


if __name__ == '__main__':
    print('=== 1. lo medido ===')
    probar_medicion()
    print('\n=== 2. la regla ===')
    probar_regla()
    print('\n' + '=' * 40)
    print('TODO OK' if not FALLOS else '%d FALLOS' % len(FALLOS))
    raise SystemExit(1 if FALLOS else 0)
