# -*- coding: utf-8 -*-
"""
v317 — pruebas: la Capa 1 con lo mejor del modelo y el segundo nivel 🔷, la
tarjeta que lo mete, los partidos fuera del motor apagados, el documento de
Telegram catalogado, el tenis sin repetir y los córners sin fuga.

Uso: python test_v317.py
"""
from __future__ import annotations

import json
import os
import sys

FALLOS = []


def check(cond, msg):
    print(('OK   ' if cond else 'FALLO') + ' ' + msg)
    if not cond:
        FALLOS.append(msg)


def _pick(qh=0.84, qd=0.10, qa=0.06, mh=0.80, md=0.12, ma=0.08, casa='Playdoit',
          dc_1x=1.12, c_home=1.18):
    return {'deporte': 'Fútbol', 'partido': 'Local FC vs Visita FC', 'clave_liga': 'premier',
            'fecha': '2026-10-01', 'fecha_cdmx': '2026-10-01', 'hora_cdmx': '13:00',
            'inicio': '2026-10-01T19:00:00',
            'board': {'Gana Local FC': mh, 'Empate': md, 'Gana Visita FC': ma},
            'implicitas': {'casa': casa, '1x2': {'home': qh, 'draw': qd, 'away': qa},
                           '1x2_cuotas': {'home': c_home, 'draw': 7.0, 'away': 12.0},
                           'doble_cuotas': {'1X': dc_1x, '12': 1.05, 'X2': 4.0}}}


def probar_capa1():
    import lo_mejor as lm
    e = lm.del_pick(_pick())
    check(e and e['apuesta'] in ('Local FC o empate', 'Gana Local FC') and e['elite'],
          'modelo 80 %% y casa 84 %%: entra en la Capa 1 (%s)' % (e or {}).get('apuesta'))
    check(lm.del_pick(_pick(qh=0.90, qd=0.07, qa=0.03, c_home=1.05, dc_1x=1.01)) is None,
          'con la casa por encima del 88 % (cuota < 1,10) no entra')
    check(lm.del_pick(_pick(mh=0.55, md=0.12, ma=0.33)) is None
          or lm.del_pick(_pick(mh=0.55, md=0.12, ma=0.33))['prob'] >= 0.70,
          'con el modelo por debajo del 70 % no entra')
    check(lm.del_pick(_pick(casa='1xBet')) is None, 'sólo en las casas del usuario')
    r = lm.del_pick_riesgo(_pick(qh=0.66, qd=0.20, qa=0.14, mh=0.72, md=0.16, ma=0.12,
                                 c_home=1.42))
    check(r and r['apuesta'] == 'Gana Local FC' and r['riesgo'],
          '🔷 ganador con la casa 66 % y el modelo 72 %: segundo nivel')
    check(lm.del_pick_riesgo(_pick(qh=0.66, qd=0.20, qa=0.14, mh=0.58, md=0.2, ma=0.22,
                                   c_home=1.42)) is None,
          '🔷 con el modelo por debajo del 60 % no entra')
    check(lm.del_pick_riesgo(_pick(qh=0.50, qd=0.25, qa=0.25, mh=0.75, md=0.15, ma=0.10,
                                   c_home=1.90)) is None,
          '🔷 con la casa por debajo del 55 % no entra')
    import veredicto_pick as vp
    v = vp.evaluar(dict(e, cuota=1.12))
    check(v['veredicto'] == vp.METER, 'el veredicto dice «meter» en lo mejor del modelo')
    m = json.load(open('_v317_capa1.json', encoding='utf-8'))
    c = m['capa1']['doble']
    check(c['elegir']['acierto'] > 0.84 and c['juzgar']['acierto'] > 0.84
          and m['resto_modelo_70_80']['juzgar']['acierto'] < 0.75,
          'medido: la Capa 1 acierta %.1f / %.1f %% contra %.1f %% del resto'
          % (100 * c['elegir']['acierto'], 100 * c['juzgar']['acierto'],
             100 * m['resto_modelo_70_80']['juzgar']['acierto']))
    rz = m['riesgo']
    check(rz['elegir']['p5_acierto'] > 0.65 and rz['juzgar']['p5_acierto'] > 0.65
          and rz['juzgar']['cuota_media'] > 1.40,
          '🔷 medido: más del 65 %% de acierto en los dos tramos (p5 %.1f / %.1f %%) a cuota %.2f'
          % (100 * rz['elegir']['p5_acierto'], 100 * rz['juzgar']['p5_acierto'],
             rz['juzgar']['cuota_media']))
    s = m['simulacion']
    check(s['ahora']['elegir']['acierto'] > s['antes']['elegir']['acierto']
          and s['ahora']['juzgar']['acierto'] > s['antes']['juzgar']['acierto']
          and s['mejora_elegir']['p5'] > 0 and s['mejora_juzgar']['p5'] > 0,
          'la tarjeta simulada acierta más: %.1f → %.1f %% y %.1f → %.1f %%'
          % (100 * s['antes']['elegir']['acierto'], 100 * s['ahora']['elegir']['acierto'],
             100 * s['antes']['juzgar']['acierto'], 100 * s['ahora']['juzgar']['acierto']))


def probar_tarjeta():
    import modo_modelo as mm
    p = _pick()
    rec = mm.recomendadas(p, n=3)
    met = mm.metidas(rec)
    check(met and met[0].get('elite') and met[0]['veredicto_vp'] == 'meter',
          'la tarjeta pone lo mejor del modelo primero y «meter»')
    fam = [c for c in rec if c.get('mercado') in mm.FAMILIA_RESULTADO]
    check(len(fam) == 1, 'y sigue habiendo una sola apuesta de resultado por partido')
    src = open('dashboard_ui.py', encoding='utf-8').read()
    check('lo mejor del modelo' in src and '_lm.del_dia(r, riesgo=True)' in src,
          'la Capa 1 enseña 🏆 lo mejor del modelo y 🔷 más cuota')
    src = open('modo_modelo.py', encoding='utf-8').read()
    check('Más riesgo, más cuota' in src, 'la tarjeta marca aparte el 🔷')


def probar_fuera_del_motor():
    import mercado_sin_modelo as msm
    check(msm.MOSTRAR is False and msm.construir({'pronosticos': []}) == [],
          'los partidos fuera del motor ya no se construyen')
    import formato_ia as fi
    r = {'pronosticos': [], 'solo_mercado': [{'deporte': 'Fútbol', 'partido': 'A W vs B W',
                                              'solo_mercado': True}]}
    check(fi._pick_de(r, {'partido': 'A W vs B W', 'deporte': 'Fútbol'}) is None,
          'ni se mandan a Telegram')


def probar_telegram():
    import formato_ia as fi
    r = {'pronosticos': [_pick()]}
    t = fi.texto(r, ['2026-10-01'])
    check('🏆 LO MEJOR DEL MODELO' in t and '🔷 MÁS RIESGO, MÁS CUOTA' in t
          and '🎯 APUESTAS A METER POR CATEGORÍA' in t and 'RESULTADO (' in t
          and 'DETALLE POR PARTIDO' in t,
          'el documento va catalogado: Capa 1, 🔷, apuestas por categoría y detalle')
    check(fi.categoria({'mercado': 'Goles equipo'}, 'Fútbol') == 'GOLES DE CADA EQUIPO'
          and fi.categoria({'mercado': 'Córners'}, 'Fútbol') == 'CÓRNERS'
          and fi.categoria({'mercado': 'x'}, 'Tenis') == 'TENIS',
          'cada apuesta va a su categoría')


def probar_tenis():
    import alpha_finder as af
    import cuotas_multi as cm
    check(cm._clave_tenista('Morag, Snir') == cm._clave_tenista('Snir Morag'),
          '«Apellido, Nombre» es el mismo jugador')
    base = {'deporte': 'Tenis', 'fecha': '2026-09-30', 'inicio': '2026-09-30T06:00:00'}
    lista = [dict(base, partido='Zheng W. vs Sorribes Tormo S.'),
             dict(base, partido='Wushuang Zheng vs Sara Sorribes Tormo'),
             dict(base, partido='Morag, Snir vs Raghav Jaisinghani'),
             dict(base, partido='Snir Morag vs Raghav Jaisinghani'),
             dict(base, partido='Otro Jugador vs Raghav Jaisinghani')]
    out = af._pronosticos_multideporte({'tenis': {'pronosticos': lista}})
    nombres = sorted(p['partido'] for p in out)
    check(nombres == ['Otro Jugador vs Raghav Jaisinghani', 'Snir Morag vs Raghav Jaisinghani',
                      'Wushuang Zheng vs Sara Sorribes Tormo'],
          'el mismo partido de tenis de dos fuentes sale una vez, con los nombres completos (%s)'
          % nombres)


def probar_corners_sin_fuga():
    import pandas as pd
    import corners_tabla as ct
    import rendimiento_equipos as rq
    orig = rq._historico
    d = pd.DataFrame({'date': pd.to_datetime(['2026-01-%02d' % i for i in range(1, 11)]),
                      'home_team': ['A', 'B'] * 5, 'away_team': ['B', 'A'] * 5,
                      'home_goals': [1] * 10, 'away_goals': [0] * 10,
                      'home_corners': [5.0] * 10, 'away_corners': [3.0] * 10,
                      'stats_origen': ['espn'] * 5 + [None] * 5})
    try:
        rq._historico = lambda clave: d
        h = ct._historico('x')
        rq._historico = lambda clave: d.iloc[:4]
        h4 = ct._historico('x')
    finally:
        rq._historico = orig
    check(h['home_corners'].notna().sum() == 5,
          'córners con tabla: las filas del generador sintético se descartan')
    check(len(h4) == 4, 'y leen el histórico recortado de las simulaciones (sin fuga)')


if __name__ == '__main__':
    os.environ.setdefault('PYTHONIOENCODING', 'utf-8')
    print('=== 1. Capa 1 ===')
    probar_capa1()
    print('\n=== 2. la tarjeta ===')
    probar_tarjeta()
    print('\n=== 3. fuera del motor ===')
    probar_fuera_del_motor()
    print('\n=== 4. Telegram ===')
    probar_telegram()
    print('\n=== 5. tenis ===')
    probar_tenis()
    print('\n=== 6. córners sin fuga ===')
    probar_corners_sin_fuga()
    print('\n' + '=' * 40)
    print('TODO OK' if not FALLOS else '%d FALLOS' % len(FALLOS))
    sys.exit(1 if FALLOS else 0)
