# -*- coding: utf-8 -*-
"""
v318 — pruebas: el envío automático de Telegram manda el documento nuevo,
con el balance de la app y el escalón de cada «meter»; el tenis repetido con
una hora de diferencia sale una vez.

Uso: python test_v318.py
"""
from __future__ import annotations

import sys

FALLOS = []


def check(cond, msg):
    print(('OK   ' if cond else 'FALLO') + ' ' + msg)
    if not cond:
        FALLOS.append(msg)


def _pick():
    return {'deporte': 'Fútbol', 'partido': 'Local FC vs Visita FC',
            'board': {'Gana Local FC': 0.62, 'Empate': 0.22, 'Gana Visita FC': 0.16},
            'goles_lineas': {'0.5': 0.93, '1.5': 0.79, '2.5': 0.56, '3.5': 0.37},
            'goles_equipo': {'local': {'0.5': 0.85, '1.5': 0.60, '2.5': 0.37},
                             'visitante': {'0.5': 0.55, '1.5': 0.21}},
            'implicitas': {'1x2': {'home': 0.60, 'draw': 0.24, 'away': 0.16},
                           '1x2_cuotas': {'home': 1.58, 'draw': 3.9, 'away': 5.9},
                           'goles': {'2.5': {'p': 0.52, 'mas': 1.80, 'menos': 1.95},
                                     '0.5': {'p': 0.95, 'mas': 1.03, 'menos': 9}},
                           'goles_home': {'1.5': {'p': 0.56, 'mas': 1.67, 'menos': 2.1}}}}


def probar_escalon():
    import formato_ia as fi
    p = _pick()
    e = fi.escalon(p, {'mercado': 'Goles', 'apuesta': 'Goles: Más de 1.5'})
    check(e and e['apuesta'] == 'Goles: Más de 2.5' and abs(e['prob'] - 0.56) < 1e-9
          and e['cuota'] == 1.80, 'más de 1,5 → subir a más de 2,5 con modelo, casa y cuota')
    e = fi.escalon(p, {'mercado': 'Doble oportunidad', 'apuesta': 'Local FC o empate'})
    check(e and e['apuesta'] == 'Gana Local FC' and e['cuota'] == 1.58,
          'X o empate → subir a gana X')
    e = fi.escalon(p, {'mercado': 'Goles equipo', 'apuesta': 'Goles Local FC: Más de 0.5'})
    check(e and e['apuesta'] == 'Goles Local FC: Más de 1.5' and e['cuota'] == 1.67,
          'equipo mete 1+ → subir a 2+')
    e = fi.escalon(p, {'mercado': 'Goles', 'apuesta': 'Goles: Menos de 1.5'})
    check(e is None, 'menos de 1,5 no baja a menos de 0,5 sin datos')
    reg = {'hora': '10:00', 'partido': p['partido']}
    lin = fi._linea_meter(reg, {'mercado': 'Goles', 'apuesta': 'Goles: Más de 1.5',
                                'prob': 0.78, 'cuota': 1.22}, p)
    check('↗ subir a Goles: Más de 2.5' in lin, 'la línea de la categoría lleva el escalón')


def probar_envio_automatico():
    src = open('bot_dia_completo.py', encoding='utf-8').read()
    check('fi.texto(r, [dia])' in src and 'texto_dia_completo(r' not in src,
          'el envío automático de cada madrugada usa el documento nuevo')
    import formato_ia as fi
    check('ASÍ LE FUE A LA APP' in fi.GUIA and 'subir a' in fi.GUIA,
          'la guía explica el balance y el escalón')
    import partidos_jugados as pj
    import pronosticos_guardados as pg
    o1, o2 = pj.de_dia, pg.validar
    pj.de_dia = lambda f: [{'deporte': 'Fútbol', 'partido': 'A vs B', 'goles_home': 0,
                            'goles_away': 0}]
    pg.validar = lambda p: [{'veredicto': 'meter', 'estado': pg.CUMPLIDO, 'mercado': 'Goles',
                             'apuesta': 'Goles: Menos de 2.5'},
                            {'veredicto': 'meter', 'estado': pg.FALLADO, 'mercado': '1X2',
                             'apuesta': 'Gana A'},
                            {'veredicto': 'no_meter', 'estado': pg.FALLADO, 'mercado': 'BTTS',
                             'apuesta': 'Ambos marcan: Sí'}]
    try:
        L = fi.balance_app(['2026-10-01'])
    finally:
        pj.de_dia, pg.validar = o1, o2
    t = '\n'.join(L)
    check('1 verdes de 2' in t and 'GOLES DEL PARTIDO 1/1' in t and 'RESULTADO 0/1' in t
          and 'Rojos del 2026-09-30' in t and 'Gana A' in t,
          'el balance cuenta sólo las «meter», por categoría, y lista los rojos de ayer')


def probar_tenis():
    import alpha_finder as af
    lista = [{'deporte': 'Tenis', 'fecha': '2026-10-01', 'inicio': '2026-10-01T08:00:00',
              'partido': 'Balshaw F. vs Budkov Kjaer N.'},
             {'deporte': 'Tenis', 'fecha': '2026-10-01', 'inicio': '2026-10-01T09:00:00',
              'partido': 'Felix Balshaw vs Nicolai Budkov Kjaer'},
             {'deporte': 'Tenis', 'fecha': '2026-10-01', 'inicio': '2026-10-01T18:00:00',
              'partido': 'Felix Balshaw vs Otro Rival'}]
    out = af._pronosticos_multideporte({'tenis': {'pronosticos': lista}})
    check(sorted(p['partido'] for p in out) == ['Felix Balshaw vs Nicolai Budkov Kjaer',
                                                'Felix Balshaw vs Otro Rival'],
          'tenis: el mismo partido con una hora de diferencia sale una vez')


if __name__ == '__main__':
    print('=== 1. el escalón ===')
    probar_escalon()
    print('\n=== 2. el envío automático y el balance ===')
    probar_envio_automatico()
    print('\n=== 3. tenis ===')
    probar_tenis()
    print('\n' + '=' * 40)
    print('TODO OK' if not FALLOS else '%d FALLOS' % len(FALLOS))
    sys.exit(1 if FALLOS else 0)
