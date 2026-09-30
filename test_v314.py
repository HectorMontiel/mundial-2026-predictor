#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test de la v314: goles en las ligas chicas (sin modelo propio).

El usuario: «para los otros modelos también arma Over/Under de goles, global
y por equipo, córners y tarjetas; encuentra los patrones de cada liga chica y
simula con los partidos finalizados; me los das como en el anterior».

Lo que se vigila:
  1. LA MEDICIÓN: los patrones de liga NO se usan porque no suman (medido);
     la regla de goles elegida es «más de 1,5» 80-90 % a cuota 1,10-1,35, y
     con ella el acierto de todo lo «meter» sube en los tres tramos.
  2. LA REGLA EN PRODUCCIÓN: una de resultado (con Pinnacle) + una de goles;
     sin Pinnacle, sólo goles; menos de 3,5 y ambos marcan no se meten.
  3. GOLES POR EQUIPO: salen de λ que reproducen el mercado, como dato.
  4. TELEGRAM: el documento lo dice (y que córners y tarjetas no hay).

Ejecutar:  python test_v314.py
"""
import json
import time

FALLOS = []


def check(cond, msg):
    print(('OK   ' if cond else 'FALLO') + ' ' + msg)
    if not cond:
        FALLOS.append(msg)


def probar_medicion():
    m = json.load(open('_v314_ligas_chicas.json', encoding='utf-8'))
    check(m['partidos'] >= 500 and m['ligas'] >= 100,
          'medido en %d partidos sin modelo de %d ligas' % (m['partidos'], m['ligas']))
    for fam, r in m['patrones_liga'].items():
        check(not r['pasa'], 'patrones de liga en %s: no pasan (w=%s, p5 prueba '
              '%+.5f) y no se usan' % (fam, r['w'], r['prueba']['p5']))
    check(m['regla_goles_elegida'] == 'más de 1,5 · 80-90 %',
          'regla de goles elegida en elección: %s' % m['regla_goles_elegida'])
    for tramo, s in m['sumado'].items():
        antes = float(s['hasta_v313'].split('=')[1].strip(' %'))
        despues = float(s['juntos'].split('=')[1].strip(' %'))
        check(despues >= antes, '%s: el acierto de «meter» no baja (%.1f → %.1f %%)'
              % (tramo, antes, despues))


def _v(q, btts=None, ou=None, casas=('Novibet', 'Winpot')):
    m = {'HOME_DRAW_AWAY': {'home': q[0], 'draw': q[1], 'away': q[2]},
         'DOUBLE_CHANCE': {'homeOrDraw': q[3], 'awayOrDraw': q[4]}}
    if btts:
        m['BOTH_TEAMS_TO_SCORE'] = {'yes': btts[0], 'no': btts[1]}
    if ou:
        m['OVER_UNDER'] = {'lineas': [{'linea': L, 'over': o, 'under': u}
                                      for L, o, u in ou]}
    return {'deporte': 'futbol', 'home': 'Needham Market', 'away': 'Stamford',
            'liga': 'ENGLAND: Southern League', 'inicio': str(int(time.time()) + 86400),
            'casas': {c: m for c in casas}}


def _pred(lh=2.4, la=0.45):
    """v315 — desde la v315 un partido fuera del motor sólo se ofrece con
    modelo propio; en los tests se le da uno fijo."""
    import modelo_competiciones as mc
    return {'p': mc.probabilidades(lh, la), 'lambdas': (lh, la), 'n': (20, 20)}


def _tpd(o15=(1.20, 4.2), o25=(1.70, 2.1)):
    # v315 — el tablero de Playdoit (su 1X2 sin margen y sus goles)
    return {'1x2': {'home': 0.66, 'draw': 0.21, 'away': 0.13},
            'goles': {'1.5': {'p': 0.82, 'mas': o15[0], 'menos': o15[1]},
                      '2.5': {'p': 0.58, 'mas': o25[0], 'menos': o25[1]}}}


def probar_regla():
    import mercado_sin_modelo as msm
    v = _v((1.45, 4.5, 6.5, 1.10, 2.6), btts=(1.8, 1.9),
           ou=[(1.5, 1.20, 4.2), (2.5, 1.70, 2.1), (3.5, 2.9, 1.38)])
    p = msm.pick_de(v, None, pred=_pred(), t_pd=_tpd())
    check(not p.get('pinnacle') and abs(sum(p['board'].values()) - 1) < .01,
          'sin Pinnacle: el 1X2 sale de las casas del usuario sin margen')
    r = msm.recomendadas(p)
    check([x['apuesta'] for x in r] == ['Goles: Más de 1.5']
          and r[0]['bloque'] == 'goles' and 0.80 <= r[0]['prob'] <= 0.90,
          'sin Pinnacle sólo se mete goles: «Más de 1.5» al %.0f %%'
          % (100 * r[0]['prob'] if r else 0))
    v2 = _v((1.23, 7.5, 13.0, 1.05, 4.5), btts=(1.8, 1.9),
            ou=[(1.5, 1.20, 4.2), (2.5, 1.70, 2.1), (3.5, 2.9, 1.38)])
    p2 = msm.pick_de(v2, {'home': 1.18, 'draw': 7.8, 'away': 15.0}, pred=_pred(), t_pd=_tpd())
    r2 = msm.recomendadas(p2)
    check([x['bloque'] for x in r2] == ['resultado', 'goles'],
          'con Pinnacle: una de resultado y una de goles (%s)'
          % [x['apuesta'] for x in r2])
    v3 = _v((1.45, 4.5, 6.5, 1.10, 2.6), btts=(2.4, 1.2),
            ou=[(1.5, 1.8, 1.9), (3.5, 5.0, 1.12)])
    check(msm.recomendadas(msm.pick_de(v3, None, pred=_pred(), t_pd={})) == [],
          'menos de 3,5 y ambos marcan: No no se meten (no pasaron)')
    lam = p['lambdas_mercado']
    ge = msm.goles_equipo(lam)
    check(lam and lam[0] > lam[1] and 0 < ge['visita_0.5'] < ge['local_0.5'] < 1
          and ge['local_1.5'] < ge['local_0.5'],
          'goles por equipo de las λ del mercado (λ %s)' % (lam,))
    # el pick de mercado se anuncia con la fuente correcta
    check('Playdoit' in p['motivo_modelo'] and 'Pinnacle' in p2['motivo_modelo'],
          'la tarjeta dice de dónde sale la probabilidad')


def probar_telegram():
    import formato_ia as fi
    check('Más de 1.5' in fi.GUIA and 'no suman' in fi.GUIA
          and 'Córners y tarjetas en ligas sin modelo' in fi.GUIA,
          'la guía para la IA explica la regla de goles, los patrones y los córners')
    import mercado_sin_modelo as msm
    v = _v((1.45, 4.5, 6.5, 1.10, 2.6), btts=(1.8, 1.9),
           ou=[(1.5, 1.20, 4.2), (2.5, 1.70, 2.1), (3.5, 2.9, 1.38)])
    p = msm.pick_de(v, None, pred=_pred(), t_pd=_tpd())
    r = {'pronosticos': [], 'solo_mercado': [p]}
    t = fi.texto(r, [p['fecha']])
    check('• Goles: Más de 1.5' in t and 'GOLES POR EQUIPO (sin cuota' in t
          and '1X2 de Playdoit sin margen' in t,
          'Telegram: 🎯 más de 1,5, goles por equipo y el 1X2 de Playdoit (v315)')


if __name__ == '__main__':
    print('=== 1. la medición ===')
    probar_medicion()
    print('\n=== 2. la regla ===')
    probar_regla()
    print('\n=== 3. Telegram ===')
    probar_telegram()
    print('\n' + '=' * 40)
    print('TODO OK' if not FALLOS else '%d FALLOS' % len(FALLOS))
    raise SystemExit(1 if FALLOS else 0)
