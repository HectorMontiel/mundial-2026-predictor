#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test de la v367.

El usuario (11-oct), con la lista bajo el marcador: «las de estrella no están
ordenadas bien por hora y no está bien aplicado el filtro del día».

Lo que se vigila:
  1. Las ⭐ ELIGE van primero y POR HORA; detrás, las demás de la que más se
     cumple a la que menos (aunque una ♻️ prometa más que una ⭐).
  2. La lista sólo trae el día que se está viendo (la pestaña de arriba).

Ejecutar:  python test_v367.py
"""
FALLOS = []


def check(cond, msg):
    print(('OK   ' if cond else 'FALLO') + ' ' + msg)
    if not cond:
        FALLOS.append(msg)


def probar_orden():
    import decisiones_dia as dd
    import modo_modelo as mm
    v = mm.sigue_valiendo
    mm.sigue_valiendo = lambda *a, **k: False
    try:
        estrella = {'recomendadas_tarjeta': [
            {'apuesta': 'Goles: Menos de 4.5', 'veredicto_vp': 'meter', 'prob': 0.85, 'cuota': 1.15}]}
        normal = {'recomendadas_tarjeta': [
            {'apuesta': 'A o empate', 'veredicto_vp': 'meter', 'prob': 0.77, 'cuota': 1.25}]}
        ps = [{'partido': 'Tarde vs X', 'deporte': 'Fútbol', 'inicio': '2099-01-01T20:00:00Z',
               dd.CLAVE_PICK: estrella},
              {'partido': 'Normal vs Y', 'deporte': 'Fútbol', 'inicio': '2099-01-01T08:00:00Z',
               dd.CLAVE_PICK: normal},
              {'partido': 'Pronto vs Z', 'deporte': 'Fútbol', 'inicio': '2099-01-01T10:00:00Z',
               dd.CLAVE_PICK: estrella}]
        l = mm.lista_por_acierto(ps, ahora=0)
        orden = [x['partido'] for x in l]
        check(orden == ['Pronto vs Z', 'Tarde vs X', 'Normal vs Y'],
              'las ⭐ primero y por hora, luego las demás (%s)' % orden)
    finally:
        mm.sigue_valiendo = v
    # una ♻️ (88 %) no se cuela delante de una ⭐ (86 %)
    xs = [{'elige': False, 'prob': 0.885, 'inicio': '2099-01-01T06:00:00Z', 'partido': 'R'},
          {'elige': True, 'prob': 0.86, 'inicio': '2099-01-01T12:00:00Z', 'partido': 'E'}]
    src = open('modo_modelo.py', encoding='utf-8').read()
    check("(0, 0.0, str(x.get('inicio') or '')) if x.get('elige')" in src,
          'la clave de orden pone las ⭐ delante de las ♻️ aunque prometan menos')
    del xs


def probar_dia():
    ui = open('dashboard_ui.py', encoding='utf-8').read()
    check('_lpa = _mmk.lista_por_acierto(solo_del_dia(_prons, _modo_lpa))' in ui
          and '_modo_lpa = dia_de_vista()' in ui
          and 'lista_por_acierto(_de_hoy + _de_man)' not in ui,
          'la lista sólo trae el día de la pestaña que se está viendo')
    import dia_picks as dp
    import datetime as dt
    hoy = dt.date(2026, 10, 11)
    ps = [{'partido': 'a', 'fecha': '2026-10-11', 'inicio': '2026-10-11 20:00:00'},
          {'partido': 'b', 'fecha': '2026-10-12', 'inicio': '2026-10-12 16:00:00'}]
    check([p['partido'] for p in dp.solo_del_dia(ps, 'hoy', hoy)] == ['a']
          and [p['partido'] for p in dp.solo_del_dia(ps, 'mañana', hoy)] == ['b'],
          'hoy sólo hoy y mañana sólo mañana')


if __name__ == '__main__':
    print('=== 1. el orden ===')
    probar_orden()
    print('\n=== 2. el día ===')
    probar_dia()
    print('\n' + '=' * 40)
    print('TODO OK' if not FALLOS else '%d FALLOS' % len(FALLOS))
    raise SystemExit(1 if FALLOS else 0)
