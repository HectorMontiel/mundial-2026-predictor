#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test de la v360.

El usuario: «quiero toda la Capa 1 ordenada por hora; y quiero saber cuál
tiene más probabilidad de cumplirse DE VERDAD —no lo que dice la tarjeta— y
que me lo señales de forma visual; enlaza el marcador con las apuestas».

Lo que se vigila:
  1. LO MEDIDO (`_v360_elige.json`): ⭐ (app ≥ 82 % o cuota ≤ 1,16) acierta
     ~86 % contra ~79 % del resto, en las dos mitades, con p5 > 0.
  2. LA REGLA (`modo_modelo.elige`, `acierta_de_verdad`) en fútbol y fuera.
  3. LA LISTA bajo el marcador, de la que más se cumple a la que menos, sin
     los partidos que ya empezaron; y la Capa 1 por hora.

Ejecutar:  python test_v360.py
"""
import json

FALLOS = []


def check(cond, msg):
    print(('OK   ' if cond else 'FALLO') + ' ' + msg)
    if not cond:
        FALLOS.append(msg)


def probar_medicion():
    d = json.load(open('_v360_elige.json', encoding='utf-8'))
    r = d['reglas']['R3 app ≥ 82 % o cuota ≤ 1,16']
    check(r['elige']['acierto'] >= 0.85 and r['juzga']['acierto'] >= 0.85
          and r['elige']['resto'] <= 0.80 and r['juzga']['resto'] <= 0.80
          and r['juzga']['dif_p5'][1] > 0,
          '⭐ acierta %.1f / %.1f %% contra %.1f / %.1f %% del resto (p5 %+.1f)'
          % (100 * r['elige']['acierto'], 100 * r['juzga']['acierto'], 100 * r['elige']['resto'],
             100 * r['juzga']['resto'], 100 * r['juzga']['dif_p5'][1]))
    c1 = d['reglas']['R5 Capa 1']
    check(c1['juzga']['dif_p5'][1] < 0, 'dentro de la Capa 1 no se marca (no separa)')
    e = json.load(open('_v360_estrategias.json', encoding='utf-8'))
    check('F pitido + retiradas desaparecidas' in e['estrategias'],
          'y la medición de las retiradas queda guardada')


def probar_regla():
    import modo_modelo as mm
    m = {'veredicto_vp': 'meter'}
    check(mm.elige(dict(m, prob=0.83, cuota=1.22)) and mm.elige(dict(m, prob=0.76, cuota=1.15))
          and not mm.elige(dict(m, prob=0.78, cuota=1.22))
          and not mm.elige({'veredicto_vp': 'no_meter', 'prob': 0.9, 'cuota': 1.1}),
          'fútbol: ⭐ con la app ≥ 82 % o cuota ≤ 1,16; sólo si se mete')
    check(mm.acierta_de_verdad(dict(m, prob=0.83, cuota=1.22)) == 0.86
          and mm.acierta_de_verdad(dict(m, prob=0.78, cuota=1.22)) == 0.79,
          'fútbol: «acierta de verdad» 86 % con ⭐ y 79 % sin ella')
    check(mm.elige(dict(m, prob=0.80, p_mercado=0.88, cuota=1.08), 'Tenis')
          and not mm.elige(dict(m, prob=0.90, p_mercado=0.80, cuota=1.2), 'Tenis')
          and mm.acierta_de_verdad(dict(m, prob=0.90, p_mercado=0.80), 'Tenis') == 0.80,
          'tenis: manda la casa sin margen (lo mejor calibrado)')
    check(mm.elige(dict(m, prob=0.88, nhl_linea=True, p_mercado=0.5), 'NHL')
          and mm.acierta_de_verdad(dict(m, prob=0.81, nhl_linea=True, p_mercado=0.5), 'NHL') == 0.81,
          'líneas medidas (NHL, NFL…): su probabilidad medida')


def probar_lista():
    import time
    import decisiones_dia as dd
    import modo_modelo as mm
    ahora = time.time()
    fila = {'recomendadas_tarjeta': [
        {'apuesta': 'Goles: Menos de 4.5', 'veredicto_vp': 'meter', 'prob': 0.80, 'cuota': 1.15},
        {'apuesta': 'A o empate', 'veredicto_vp': 'meter', 'prob': 0.77, 'cuota': 1.25}]}
    ps = [{'partido': 'A vs B', 'deporte': 'Fútbol', 'inicio': '2099-01-01T12:00:00Z',
           dd.CLAVE_PICK: fila},
          {'partido': 'C vs D', 'deporte': 'Fútbol', 'inicio': '2000-01-01T12:00:00Z',
           dd.CLAVE_PICK: fila}]
    l = mm.lista_por_acierto(ps, ahora=ahora)
    check([x['apuesta'] for x in l] == ['⭐ Goles: Menos de 4.5', 'A o empate']
          and l[0]['prob'] == 0.86 and l[1]['prob'] == 0.79,
          'la lista: de la que más se cumple a la que menos, ⭐ delante (%s)'
          % [(x['apuesta'], x['prob']) for x in l])
    ui = open('dashboard_ui.py', encoding='utf-8').read()
    check('lista_por_acierto(' in ui and '_por_hora(_lm_c1)' in ui and '_por_hora(_prob_c1)' in ui,
          'bajo el marcador va la lista, y la Capa 1 va por hora')
    check("titulo = '⭐ ELIGE · ' + titulo" in open('modo_modelo.py', encoding='utf-8').read(),
          'y la tarjeta lo dice en el título')


if __name__ == '__main__':
    print('=== 1. lo medido ===')
    probar_medicion()
    print('\n=== 2. la regla ===')
    probar_regla()
    print('\n=== 3. la lista y el orden ===')
    probar_lista()
    print('\n' + '=' * 40)
    print('TODO OK' if not FALLOS else '%d FALLOS' % len(FALLOS))
    raise SystemExit(1 if FALLOS else 0)
