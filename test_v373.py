#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test de la v373.

El usuario (12-oct): «las de estrella, cuando pasa el partido, se borran en
lugar de que las marques en verde como las probables; quiero saber cuáles son
verdes o rojas también de las estrellas».

Lo que se vigila:
  1. `lista_finalizadas`: las «se mete» de lo ya empezado, con ✅/❌/⏳ y el
     marcador, sacadas de lo archivado al pitido; las ⭐ primero.
  2. La lista bajo el marcador las enseña («Ya empezaron hoy») y cuenta
     verdes/rojas, también de las ⭐.

Ejecutar:  python test_v373.py
"""
FALLOS = []


def check(cond, msg):
    print(('OK   ' if cond else 'FALLO') + ' ' + msg)
    if not cond:
        FALLOS.append(msg)


def probar_finalizadas():
    import modo_modelo as mm
    import pronosticos_guardados as pg
    v = pg.validar
    pg.validar = lambda p, filas=None: {
        'A vs B': [{'apuesta': 'Goles: Menos de 4.5', 'veredicto': 'meter', 'prob': 0.85,
                    'prob_meter': 0.85, 'cuota': 1.15, 'estado': pg.CUMPLIDO},
                   {'apuesta': 'Goles B: Más de 0.5', 'veredicto': 'meter', 'prob': 0.76,
                    'prob_meter': 0.76, 'cuota': 1.25, 'estado': pg.FALLADO},
                   {'apuesta': 'Gana A', 'veredicto': 'no_meter', 'prob': 0.5, 'cuota': 2.0,
                    'estado': pg.FALLADO}],
        'C vs D': [{'apuesta': 'Goles: Más de 1.5', 'veredicto': 'meter', 'prob': 0.80,
                    'prob_meter': 0.80, 'cuota': 1.25, 'estado': pg.PENDIENTE}]}[p['partido']]
    try:
        f = mm.lista_finalizadas([
            {'partido': 'C vs D', 'deporte': 'Fútbol', 'inicio': '2099-01-01T10:00:00Z'},
            {'partido': 'A vs B', 'deporte': 'Fútbol', 'inicio': '2099-01-01T12:00:00Z',
             'goles_home': 1, 'goles_away': 0},
            {'partido': 'X vs Y', 'deporte': 'Fútbol', 'solo_mercado': True}])
    finally:
        pg.validar = v
    check([(x['apuesta'], x['resultado_c1'], x['marcador']) for x in f] ==
          [('⭐ Goles: Menos de 4.5', 'verde', '1-0'), ('Goles: Más de 1.5', 'vivo', ''),
           ('Goles B: Más de 0.5', 'rojo', '1-0')],
          'las «se mete» empezadas: ⭐ primero, ✅/❌ con marcador, ⏳ si no hay resultado, '
          'sin las «no meter» (%s)' % [(x['apuesta'], x['resultado_c1']) for x in f])
    import vista_compacta as vc
    h = vc.html_lista(f)
    check('✅ SÍ' in h and '❌ NO' in h, 'y la lista compacta las pinta en verde y rojo')


def probar_pantalla():
    ui = open('dashboard_ui.py', encoding='utf-8').read()
    check('def _semete_finalizadas(' in ui and '**Ya empezaron hoy**' in ui
          and "' · jugadas ✅ %d ❌ %d (⭐ ✅ %d ❌ %d)'" in ui,
          'la lista bajo el marcador enseña las ya empezadas y cuenta verdes/rojas de las ⭐')


if __name__ == '__main__':
    print('=== 1. las empezadas ===')
    probar_finalizadas()
    print('\n=== 2. la pantalla ===')
    probar_pantalla()
    print('\n' + '=' * 40)
    print('TODO OK' if not FALLOS else '%d FALLOS' % len(FALLOS))
    raise SystemExit(1 if FALLOS else 0)
