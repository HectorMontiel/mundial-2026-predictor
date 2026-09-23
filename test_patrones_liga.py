#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test del modelo que aprende el carácter de cada liga (v302).

Lo que se vigila:

  · SIN FUGA. Los rasgos de tabla de un partido se leen ANTES de sumar ese
    partido. Si se colara el resultado, el modelo «acertaría» en el pasado y
    nada en el futuro — el patrón que ha matado casi todas las ideas del
    proyecto.
  · SÓLO SE USA LO QUE GANÓ. El fichero entrenado guarda un modelo por
    mercado únicamente si le ganó a la línea base calibrada con p5 positivo
    en el tramo de juicio. Ambos marcan no pasó y NO puede estar activo.
  · LA ESCALERA DE GOLES SIGUE ORDENADA después de corregir: más de 1,5 >=
    más de 2,5 >= más de 3,5. Un corrector que desordena las líneas publica
    probabilidades imposibles.
  · EL DESPLAZAMIENTO TIENE TOPE, y el pick sin liga entrenada no se toca.
  · NUNCA LANZA, porque va dentro del barrido.
  · EL BARRIDO LO USA y el workflow semanal lo reentrena.

Ejecutar:  python test_patrones_liga.py
"""
import math
import os

FALLOS = []


def check(cond, msg):
    print(('OK   ' if cond else 'FALLO') + ' ' + msg)
    if not cond:
        FALLOS.append(msg)


def probar_sin_fuga():
    import pandas as pd
    import patrones_liga as pl
    t = pl.Tabla()
    d0 = pd.Timestamp('2026-01-01')
    # A gana siempre, B pierde siempre, y hay relleno para que haya tabla
    for i in range(12):
        d = d0 + pd.Timedelta(days=7 * i)
        t.sumar('A', 'X%d' % (i % 4), d, 3.0, 0.0)
        t.sumar('X%d' % ((i + 1) % 4), 'B', d, 2.0, 0.0)
        t.sumar('C', 'D', d, 1.0, 1.0)
    d = d0 + pd.Timedelta(days=90)
    antes = t.rasgos('A', 'B', d)
    check(antes['pct_h'] > antes['pct_a'],
          'el que gana siempre sale arriba de la tabla (%.2f > %.2f)'
          % (antes['pct_h'], antes['pct_a']))
    check(pl.tercio(antes['pct_h']) == 'arriba'
          and pl.tercio(antes['pct_a']) == 'abajo',
          'y en su tercio: arriba y abajo')
    gf_antes = antes['gf_h']
    t.sumar('A', 'B', d, 9.0, 0.0)
    despues = t.rasgos('A', 'B', d + pd.Timedelta(days=7))
    check(despues['gf_h'] > gf_antes,
          'el partido se suma DESPUÉS de leer sus rasgos (%.2f -> %.2f)'
          % (gf_antes, despues['gf_h']))


def probar_solo_lo_que_gano():
    import patrones_liga as pl
    if not os.path.exists(pl.FICHERO):
        check(False, 'falta %s: el modelo no está entrenado' % pl.FICHERO)
        return
    pl.olvidar()
    doc = pl.cargar()
    med = doc.get('medicion') or {}
    mods = doc.get('modelos') or {}
    for k, v in med.items():
        gana = v['mejora'] > 0 and v['p5'] > 0
        check(gana == (k in mods),
              '%s: activo sólo si ganó con p5 > 0 (mejora %+.5f, p5 %+.5f)'
              % (k, v['mejora'], v['p5']))
    check('btts' not in mods, 'ambos marcan NO se corrige: no pasó')
    check(len(doc.get('codigos') or {}) >= 40,
          'aprende de todas las ligas con histórico (%d)'
          % len(doc.get('codigos') or {}))
    check(doc.get('n_juicio', 0) > 10000,
          'y se juzgó sobre un tramo que no vio (%d partidos)'
          % doc.get('n_juicio', 0))


def _pick(liga, h, a):
    return {'deporte': 'Fútbol', 'clave_liga': liga,
            'partido': '%s vs %s' % (h, a),
            'goles_lambda': 2.6,
            'goles_lineas': {'0.5': 0.93, '1.5': 0.74, '2.5': 0.49,
                             '3.5': 0.27, '4.5': 0.12},
            'goles_equipo': {'local': {'0.5': 0.75, '1.5': 0.42, '2.5': 0.17},
                             'visitante': {'0.5': 0.62, '1.5': 0.27,
                                           '2.5': 0.08}},
            'board': {'Más de 2.5': 0.49, 'Menos de 2.5': 0.51},
            'mercados': [{'apuesta': 'Más de 2.5', 'prob': 0.49},
                         {'apuesta': 'Menos de 2.5', 'prob': 0.51}]}


def probar_la_correccion():
    import pandas as pd
    import patrones_liga as pl
    pl.olvidar()
    if not pl.cargar():
        check(False, 'sin modelo entrenado no se puede probar la corrección')
        return
    h = pl._historico('premier')
    if h.empty:
        check(False, 'falta historico_premier.csv')
        return
    ult = h.iloc[-1]
    p = _pick('premier', ult['home_team'], ult['away_team'])
    ok = pl.ajustar(p, ahora=pd.Timestamp(ult['date']) + pd.Timedelta(days=3))
    check(ok, 'corrige un partido de una liga entrenada')
    gl = p['goles_lineas']
    check(gl['0.5'] >= gl['1.5'] >= gl['2.5'] >= gl['3.5'] >= gl['4.5'],
          'la escalera de goles sigue ordenada (%s)' % gl)
    for lado in ('local', 'visitante'):
        e = p['goles_equipo'][lado]
        check(e['0.5'] >= e['1.5'] >= e['2.5'],
              'y la de cada equipo (%s: %s)' % (lado, e))
    check(abs(p['board']['Más de 2.5'] + p['board']['Menos de 2.5'] - 1) < 0.002,
          'más y menos de 2,5 siguen sumando uno')
    des = (p.get('patron_liga') or {}).get('desplazamiento') or {}
    check(all(abs(v) <= 1.0 + 1e-9 for v in des.values()),
          'ningún desplazamiento pasa del tope (%s)' % des)
    otro = _pick('liga_que_no_existe', 'A', 'B')
    antes = dict(otro['goles_lineas'])
    check(pl.ajustar(otro) is False and otro['goles_lineas'] == antes,
          'una liga sin entrenar no se toca')
    raro = {'deporte': 'Fútbol', 'clave_liga': 'premier', 'partido': None}
    try:
        check(pl.ajustar(raro) is False, 'un pick roto no se toca')
        check(pl.ajustar_lista([None, 3, raro]) == 0, 'y la lista no lanza')
    except Exception as e:
        check(False, 'lanzó con un pick roto: %s' % e)


def probar_el_barrido_y_el_workflow():
    src = open('alpha_finder.py', encoding='utf-8').read()
    check('patrones_liga' in src, 'el barrido del día aplica los patrones')
    check("'goles_xg'" in src,
          'y guarda la lambda de cada equipo, que es lo que vio al entrenar')
    wf = open('.github/workflows/recalibrar.yml', encoding='utf-8').read()
    check('patrones_liga.py --entrenar' in wf,
          'el workflow semanal lo reentrena')
    check('patrones_liga.json' in wf, 'y publica el fichero')


if __name__ == '__main__':
    print('=== 1. sin fuga ===')
    probar_sin_fuga()
    print('\n=== 2. sólo lo que ganó ===')
    probar_solo_lo_que_gano()
    print('\n=== 3. la corrección ===')
    probar_la_correccion()
    print('\n=== 4. el barrido y el workflow ===')
    probar_el_barrido_y_el_workflow()
    print('\n' + '=' * 40)
    print('TODO OK' if not FALLOS else '%d FALLOS' % len(FALLOS))
    raise SystemExit(1 if FALLOS else 0)
