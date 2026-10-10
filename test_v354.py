#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test de la v354.

El usuario: «quiero NBA: ganador y más/menos puntos; empecemos al 75 % y lo
vamos subiendo; en Capa 1, en Apuestas del día, en todo»; «investiga todas
las fuentes, también con la pretemporada».

Lo que se vigila:
  1. PLAYDOIT SE ENCUENTRA: «Detroit Pistons» casa con «DET Pistons».
  2. LAS TABLAS: la línea alternativa acierta según su distancia a la
     principal, igual en las dos mitades del historial.
  3. LA TARJETA: la línea de mejor cuota que llega al 75 % se mete; si
     ninguna llega, la más probable sale como informativa.
  4. CAPA 1 🏆 por hándicap (≥ 84 %) y su liquidación en verde/rojo.

Ejecutar:  python test_v354.py
"""
import json

FALLOS = []


def check(cond, msg):
    print(('OK   ' if cond else 'FALLO') + ' ' + msg)
    if not cond:
        FALLOS.append(msg)


def probar_playdoit():
    import cuotas_multi as cm
    check(cm.apodo_nba('Detroit Pistons') == cm.apodo_nba('DET Pistons') == 'pistons'
          and cm.apodo_nba('Philadelphia 76ers') == '76ers'
          and cm.apodo_nba('Portland Trail Blazers') == 'blazers'
          and cm.apodo_nba('Real Madrid') is None,
          'el apodo de la NBA casa los dos nombres; un club europeo no')
    idx = {'det pistons|bos celtics': {'home': 'DET Pistons', 'away': 'BOS Celtics',
                                       'fecha': '2026-10-20T19:00:00', 'event_id': 1}}
    r = cm._buscar(idx, 'Boston Celtics', 'Detroit Pistons', 'nba', '2026-10-20T19:00:00')
    check(r is not None and r['invertido'], 'y lo encuentra aunque venga con los bandos al revés')
    check(cm._buscar(idx, 'Boston Celtics', 'Detroit Pistons', 'nba', '2026-11-20') is None,
          'en otra fecha, no')


def probar_tablas():
    d = json.load(open('nba_lineas.json', encoding='utf-8'))
    t, te = d['tablas'], d['tablas_elige_2010_2016']
    check(t['no_favorito']['10.5'] >= 0.78 and t['favorito']['12.5'] >= 0.80
          and t['mas']['9.5'] < 0.72,
          'juzga 2017-25: no favorito +10.5 %.0f %%, favorito a 12.5 %.0f %%, más a 9.5 %.0f %%'
          % (100 * t['no_favorito']['10.5'], 100 * t['favorito']['12.5'], 100 * t['mas']['9.5']))
    dif = max(abs(t[c][k] - te[c][k]) for c in t for k in ('8.5', '10.5', '12.5'))
    check(dif < 0.04, 'las dos mitades del historial dicen lo mismo (máx. %.1f pts)' % (100 * dif))


TAB = {'handicap': {'principal_local': -2.5,
                    'local': {'-2.5': 1.9, '2.5': 1.45, '7.5': 1.25, '9.5': 1.17},
                    'visita': {'2.5': 1.9, '8.5': 1.4, '11.5': 1.2353, '13.5': 1.1667}},
       'totales': {'principal': 239.5, 'mas': {'239.5': 1.9, '229.5': 1.38},
                   'menos': {'239.5': 1.9, '249.5': 1.37}}}
PICK = {'deporte': 'NBA', 'partido': 'Chicago Bulls vs Memphis Grizzlies', 'clave_liga': 'nba',
        'implicitas': {'nba_playdoit': TAB}}


def probar_tarjeta():
    import nba_lineas as nl
    import veredicto_pick as vp
    el = nl.elegidas(PICK)
    hcp = [c for c in el if c['mercado'] == 'Handicap' and not c.get('informativa')]
    tot = [c for c in el if c['mercado'] == 'Puntos']
    check(any(c['apuesta'] == 'Handicap: Chicago Bulls +7.5' for c in hcp),
          'el hándicap: la línea de mejor cuota que llega al 75 % (Bulls +7.5 a 1,25)')
    check(tot and all(c.get('informativa') for c in tot),
          'los puntos no llegan al 75 %% con la escalera de Playdoit: informativos (%s)'
          % [(c['apuesta'], c['prob']) for c in tot])
    c = hcp[0]
    fila = {'deporte': 'NBA', 'apuesta': c['apuesta'], 'mercado': 'Handicap', 'prob': c['prob'],
            'cuota': c['cuota'], 'nba_linea': True, 'nba_k': c['k']}
    check(vp.evaluar(fila)['veredicto'] == vp.METER, 'se mete')
    check(vp.evaluar(dict(fila, pretemporada=True, nba_tipo='favorito'))['veredicto'] == vp.NO_METER
          and vp.evaluar(dict(fila, pretemporada=True, nba_tipo='no_favorito'))['veredicto'] == vp.METER,
          'pretemporada: el no favorito sí, el favorito no (medido con ESPN 2021-26)')
    pre = json.load(open('nba_lineas.json', encoding='utf-8'))['pretemporada']
    check(pre['partidos'] >= 400 and pre['tablas']['no_favorito']['8.5'] >= 0.75
          and pre['regla_ganador_casa78']['acierta'] < 0.75,
          'la medición de pretemporada: no favorito +8,5 %.0f %%, ganador casa ≥78 %.0f %% (%d partidos)'
          % (100 * pre['tablas']['no_favorito']['8.5'],
             100 * pre['regla_ganador_casa78']['acierta'], pre['partidos']))
    check(vp.evaluar(dict(fila, informativa=True))['veredicto'] == vp.NO_METER,
          'una informativa no se mete')


def probar_capa1():
    import lo_mejor as lm
    p = dict(PICK, board={'Gana Chicago Bulls': 0.58, 'Gana Memphis Grizzlies': 0.42},
             implicitas={'1x2_cuotas': {'home': 1.74, 'away': 2.15},
                         'nba_playdoit': dict(TAB, handicap=dict(
                             TAB['handicap'], visita={'2.5': 1.9, '15.5': 1.12, '14.5': 1.14}))})
    e = lm.del_pick(p)
    check(e is not None and e['mercado'] == 'Handicap' and e['prob'] >= 0.84 and e['cuota'] >= 1.10,
          'sin ganador que entre, el 🏆 es el hándicap de ≥ 84 %% (%s)' % (e and e['apuesta']))
    check(lm.resultado('Handicap: Memphis Grizzlies +14.5', PICK['partido'], 120, 108) == 'verde'
          and lm.resultado('Handicap: Memphis Grizzlies +14.5', PICK['partido'], 125, 108) == 'rojo',
          'y se liquida en verde o rojo con el marcador')
    import capa1_resultados as cr
    check(cr.resolver('Handicap', 'Handicap: Memphis Grizzlies +14.5', 'Chicago Bulls',
                      'Memphis Grizzlies', 120, 108) == 'verde',
          'también en el historial de la Capa 1')


if __name__ == '__main__':
    print('=== 1. Playdoit se encuentra ===')
    probar_playdoit()
    print('\n=== 2. las tablas ===')
    probar_tablas()
    print('\n=== 3. la tarjeta ===')
    probar_tarjeta()
    print('\n=== 4. la Capa 1 ===')
    probar_capa1()
    print('\n' + '=' * 40)
    print('TODO OK' if not FALLOS else '%d FALLOS' % len(FALLOS))
    raise SystemExit(1 if FALLOS else 0)
