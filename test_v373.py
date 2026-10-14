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


TAB = {'1x2': {'home': 0.58, 'draw': 0.24, 'away': 0.18}, '1x2_cuotas': {'home': 1.62, 'draw': 3.9, 'away': 5.0},
       'goles': {'2.5': {'p': 0.60, 'mas': 1.60, 'menos': 2.3}, '1.5': {'p': 0.74, 'mas': 1.30, 'menos': 3.4},
                 '2.25': {'p': 0.66, 'mas': 1.45, 'menos': 2.6}},
       'corners': {'9.5': {'p': 0.45, 'mas': 2.1, 'menos': 1.66}},
       'corners_home': {'4.5': {'p': 0.62, 'mas': 1.55, 'menos': 2.3}},
       'tarjetas': {'3.5': {'p': 0.62, 'mas': 1.55, 'menos': 2.3}},
       'btts': 0.57, 'btts_cuotas': {'si': 1.65, 'no': 2.1}}


def probar_piso():
    import mercado_implicito as mi
    import sonadora_piso as sp
    v = mi.del_partido
    mi.del_partido = lambda h, a, **k: TAB
    try:
        p = {'partido': 'Uno FC vs Dos FC', 'deporte': 'Fútbol', 'inicio': '2099-01-01T12:00:00Z'}
        c160 = sp.candidatas(p, 1.60)
        ap = [x['apuesta'] for x in c160]
        check(ap[0] == 'Goles: Más de 2.5' and 'Gana Uno FC' in ap and 'Ambos marcan: Sí' in ap
              and 'Córners: Menos de 9.5' in ap and all(1.60 <= x['cuota'] <= 2.10 for x in c160),
              'a 1,60: sólo patas a 1,60-2,10, de la más probable a la menos (%s)' % ap)
        check(not any('Tarjetas' in a or 'Córners Uno' in a or '2.25' in a for a in ap),
              'fuera tarjetas, córners de equipo y líneas de cuarto')
        c130 = sp.candidatas(p, 1.30)
        check(c130[0]['apuesta'] == 'Goles: Más de 1.5' and c130[0]['prob'] == 0.78
              and 'Casa 70/130' in c130[0]['porque'],
              'a 1,30 la Casa 70/130 entra primero, con su 78 % medido')
        check(sp.candidatas(p, 1.60, con_ganador=False) and
              not any(x['bloque'] == 'resultado' for x in sp.candidatas(p, 1.60, con_ganador=False)),
              'sin ganador si no se pide')
        dd = sp.del_dia([p, dict(p, partido='Tres FC vs Cuatro FC')], 1.60, ahora=0)
        check(len(dd) == 2 and len({x['partido'] for x in dd}) == 2, 'una pata por partido')
        b = sp.boleto(dd, 2)
        ev0, ev2 = sp.valor_esperado(b), sp.valor_esperado(b, 0.2)
        check(abs(ev2 - (1.2 * b['momio'] * b['prob'] - 1) * 100) < 1e-9 and ev2 > ev0,
              'el valor esperado con y sin booster')
        check('NINGUNO' in sp.medido(1.6, 12) and '56 %' in sp.medido(1.6, 4),
              'dice lo medido del piso y avisa con 10+ patas')
    finally:
        mi.del_partido = v
    ui = open('sonadora_ui.py', encoding='utf-8').read()
    check("'🎯 Soñadora por cuota mínima'" in ui and "'Cuota mínima por pata'" in ui
          and "'Booster'" in ui and "max_value=len(pats)" in ui,
          'la pantalla: cuota mínima, booster y tantas patas como partidos haya')


if __name__ == '__main__':
    print('=== 0. la soñadora por cuota mínima ===')
    probar_piso()
    print('\n=== 1. las empezadas ===')
    probar_finalizadas()
    print('\n=== 2. la pantalla ===')
    probar_pantalla()
    print('\n' + '=' * 40)
    print('TODO OK' if not FALLOS else '%d FALLOS' % len(FALLOS))
    raise SystemExit(1 if FALLOS else 0)
