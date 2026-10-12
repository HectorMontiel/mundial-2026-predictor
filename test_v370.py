#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test de la v370.

El usuario (11-oct), con un boleto de Draftea de 21 patas: «quiero lograr
hacer este tipo de apuestas con las soñadoras».

Lo que se vigila (`boleto_largo`):
  1. Sólo «se mete», UNA por partido, las ⭐ primero; sin las ♻️.
  2. Por deportes (sólo fútbol, sólo básquetbol, combinados).
  3. Momio y probabilidad multiplicados; partido en boletos de 5.
  4. Sin precálculo (justo tras una actualización) también sale: la misma
     cuenta de la tarjeta.
  5. La pantalla de Soñadoras lo enseña, con lo medido.

Ejecutar:  python test_v370.py
"""
FALLOS = []


def check(cond, msg):
    print(('OK   ' if cond else 'FALLO') + ' ' + msg)
    if not cond:
        FALLOS.append(msg)


def _fila(partido, apuesta, cuota, prob, elige, dep='Fútbol', inicio='2099-01-01T12:00:00Z', **k):
    return dict({'partido': partido, 'apuesta': apuesta, 'cuota': cuota, 'prob': prob,
                 'elige': elige, 'deporte': dep, 'inicio': inicio}, **k)


def probar_patas():
    import boleto_largo as bl
    v = bl._filas
    bl._filas = lambda ps, ahora=None: [
        _fila('A vs B', 'Goles: Más de 1.5', 1.25, 0.79, False, inicio='2099-01-01T10:00:00Z'),
        _fila('A vs B', '⭐ Goles: Menos de 4.5', 1.15, 0.86, True, inicio='2099-01-01T10:00:00Z'),
        _fila('C vs D', 'C o empate', 1.20, 0.79, False, inicio='2099-01-01T09:00:00Z'),
        _fila('E vs F', '♻️ Goles: Menos de 3.5', 1.30, 0.885, False, sigue=True),
        _fila('Lakers vs Celtics', 'Gana Lakers', 1.22, 0.82, False, dep='NBA',
              inicio='2099-01-01T23:00:00Z'),
        _fila('G vs H', '⭐ Goles G: Más de 0.5', 1.12, 0.86, True, inicio='2099-01-01T20:00:00Z')]
    try:
        p = bl.patas([])
        check([x['partido'] for x in p][:2] == ['A vs B', 'G vs H']
              and p[0]['apuesta'].startswith('⭐') and len(p) == 4
              and not any(x.get('sigue') for x in p),
              'una por partido, las ⭐ primero y sin ♻️ (%s)' % [(x['partido'], x['apuesta']) for x in p])
        f = bl.patas([], ['⚽ Fútbol'])
        n = bl.patas([], ['🏀 Básquetbol'])
        check(len(f) == 3 and [x['partido'] for x in n] == ['Lakers vs Celtics'],
              'por deportes: sólo fútbol / sólo básquetbol')
        b = bl.boleto(p, 3)
        check(b and len(b['patas']) == 3 and abs(b['momio'] - 1.15 * 1.12 * 1.22) < 1e-9
              and abs(b['prob'] - 0.86 * 0.86 * 0.82) < 1e-9 and b['n_elige'] == 2
              and [x['partido'] for x in b['patas']] == ['A vs B', 'G vs H', 'Lakers vs Celtics'],
              'el boleto multiplica cuota y probabilidad, en orden de hora')
        b2 = bl.boleto(p, 20)
        check(b2 and len(b2['patas']) == 4 and not b2['completo'],
              'si faltan patas, lleva todas y lo dice')
        tr = bl.partir(bl.boleto(p, 4), 2)
        check(len(tr) == 2 and all(len(t['patas']) == 2 for t in tr),
              'partido en boletos chicos')
        check('10 patas' in bl.medido(11) and '3 de 7' in bl.medido(10), 'lo medido del largo más cercano')
    finally:
        bl._filas = v


def probar_en_vivo():
    import boleto_largo as bl
    import decisiones_dia as dd
    import modo_modelo as mm
    v1, v2 = dd.tarjeta_de_pick, mm.recos_tarjeta
    dd.tarjeta_de_pick = lambda p: None
    mm.recos_tarjeta = lambda p: [{'apuesta': 'Goles: Menos de 4.5', 'veredicto_vp': 'meter',
                                   'prob': 0.85, 'prob_meter': 0.85, 'cuota': 1.15}]
    try:
        f = bl._filas([{'partido': 'X vs Y', 'deporte': 'Fútbol', 'prob': 0.5,
                        'inicio': '2099-01-01T12:00:00Z'}], ahora=0)
        check(len(f) == 1 and f[0]['elige'] and f[0]['apuesta'] == '⭐ Goles: Menos de 4.5',
              'sin precálculo sale con la cuenta de la tarjeta')
    finally:
        dd.tarjeta_de_pick, mm.recos_tarjeta = v1, v2


def probar_pantalla():
    src = open('sonadora_ui.py', encoding='utf-8').read()
    check("🎟️ Boleto largo con las «se mete»" in src and '_boleto_largo(st, r)' in src
          and 'bl.medido(' in src and 'bl.partir(' in src,
          'Soñadoras enseña el boleto largo, lo medido y partido en boletos de 5')
    import json
    m = json.load(open('_v370_boleto_largo.json', encoding='utf-8'))
    check(m['boletos']['elige_y_resto · 20 patas']['enteros'] == 1,
          'la medición queda guardada (20 patas: 1 de 7 días)')


if __name__ == '__main__':
    print('=== 1-3. las patas y el boleto ===')
    probar_patas()
    print('\n=== 4. sin precálculo ===')
    probar_en_vivo()
    print('\n=== 5. la pantalla ===')
    probar_pantalla()
    print('\n' + '=' * 40)
    print('TODO OK' if not FALLOS else '%d FALLOS' % len(FALLOS))
    raise SystemExit(1 if FALLOS else 0)
