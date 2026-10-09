#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test de la v345.

El usuario: «quiero este modelo en los tiros totales y a puerta por equipo;
si llega a estar en las tarjetas, que tenga buena probabilidad, como lo hemos
hecho; ¿qué hace falta para que el p5 negativo pase a positivo?». Y sobre los
grandes de la Liga MX: «valídalo y dame tu recomendación de meter o no».

Lo que se vigila:
  1. EL MODELO EN LA TARJETA: si hay precálculo, los tiros salen de
     `tiros_equipo`; la probabilidad de cada línea del equipo es la del
     modelo mezclada con la casa con el peso medido, sin las correcciones del
     modelo viejo; la fila dice si cumple la regla.
  2. «SE METE» SÓLO CON LA REGLA GANADA: mientras `tiros_seguimiento` no la
     active (p5 > 0 con 150 apuestas desde el 10-sep), los tiros no se meten;
     cuando la active, sí, y sólo los que la cumplen.
  3. EL SEGUIMIENTO: apunta, liquida y mide solo, en el precálculo.

Ejecutar:  python test_v345.py
"""
import json
import os
import tempfile

import pandas as pd

FALLOS = []


def check(cond, msg):
    print(('OK   ' if cond else 'FALLO') + ' ' + msg)
    if not cond:
        FALLOS.append(msg)


DIA = {'version': 'v345', 'k': {'tiros': 20.0, 'a_puerta': 44.0},
       'peso_modelo': {'tiros': 1.0, 'a_puerta': 0.65},
       'partidos': {'Santos vs Fluminense|brasil': {
           'local': {'tiros': 9.0, 'a_puerta': 3.2, 'partidos': 20},
           'visitante': {'tiros': 17.0, 'a_puerta': 5.8, 'partidos': 20}}}}
PICK = {'partido': 'Santos vs Fluminense', 'clave_liga': 'brasil',
        'deporte': 'Fútbol', 'inicio': '2099-10-10T22:00:00',
        'implicitas': {'remates_away': {'13.5': {'p': 0.5, 'mas': 1.85, 'menos': 1.85}},
                       'remates_on_away': {'4.5': {'p': 0.5, 'mas': 1.85, 'menos': 1.85}},
                       'remates_home': {'11.5': {'p': 0.5, 'mas': 1.85, 'menos': 1.85}}}}


def _dia():
    ruta = os.path.join(tempfile.mkdtemp(), 'tiros_dia.json')
    json.dump(DIA, open(ruta, 'w', encoding='utf-8'))
    return ruta


def probar_modelo():
    import tiros_equipo as te
    from scipy import stats
    check(abs(te.prob_mas(14.0, 13.5, 1e9) - stats.poisson.sf(13, 14.0)) < 1e-3,
          'con k muy grande es la Poisson: P(más de 13,5)')
    check(te.prob_mas(17.0, 13.5, 20) > 0.7, 'y con media alta, el «más»')
    ruta = _dia()
    b = te.bloques_tarjeta(PICK, ruta)
    check(b and b['totales']['lambda_away'] == 17.0
          and b['totales']['modelo_tiros'] == 'v345'
          and b['a_puerta']['peso_modelo'] == 0.65,
          'los bloques de la tarjeta salen del precálculo')
    check(te.bloques_tarjeta(dict(PICK, partido='Otro vs Otro'), ruta) is None,
          'sin precálculo de ese partido, nada')
    check({'p_gana', 'r_t_faltas', 'ppg', 't_pos', 'presion'} <= set(te.COLUMNAS),
          'con las piezas de la metodología: plantilla, faltas del rival, '
          'tabla, posesión, presión')


def probar_tarjeta():
    import modo_modelo as mm
    import tiros_equipo as te
    import valor_apuesta as va
    ruta = _dia()
    orig = te.FICHERO_DIA
    te.FICHERO_DIA = ruta
    te._CACHE.pop('dia_mt', None)
    try:
        orig_bt = te.bloques_tarjeta
        te.bloques_tarjeta = lambda p, r=ruta: orig_bt(p, r)
        rem = mm.remates_tarjeta(PICK)
        check(rem and rem['totales'].get('modelo_tiros') == 'v345',
              'la tarjeta usa el modelo nuevo de tiros')
        bloques = {'Remates': rem['totales'], 'Remates a puerta': rem['a_puerta']}
        filas = va._de_conteo(PICK, bloques)
        vis = [f for f in filas if f['apuesta'] == 'Remates Visita: Más de 13.5']
        p_mod = te.prob_mas(17.0, 13.5, 20.0)
        check(vis and abs(vis[0]['prob'] - round(p_mod, 4)) < 1e-3,
              'tiros: la probabilidad es la del modelo (peso 1) (%s)'
              % (vis and vis[0]['prob']))
        check(vis and vis[0].get('tiros_regla') == 'más',
              'y la fila del lado bueno lleva la marca de la regla')
        men = [f for f in filas if f['apuesta'] == 'Remates Visita: Menos de 13.5']
        check(men and not men[0].get('tiros_regla'), 'el otro lado no')
        ap = [f for f in filas if f['apuesta'] == 'Remates a puerta Visita: Más de 4.5']
        esperado = 0.65 * te.prob_mas(5.8, 4.5, 44.0) + 0.35 * 0.5
        check(ap and abs(ap[0]['prob'] - esperado) < 2e-3,
              'a puerta: 65 %% modelo y 35 %% casa (%.3f vs %.3f)'
              % (ap and ap[0]['prob'] or 0, esperado))
        check(ap and not ap[0].get('tiros_regla'),
              'a puerta no entra en la regla (no está medida para apostar)')
    finally:
        te.FICHERO_DIA = orig
        te.bloques_tarjeta = orig_bt
        te._CACHE.pop('dia_mt', None)


def probar_veredicto():
    import tiros_seguimiento as ts
    import veredicto_pick as vp
    fila = {'apuesta': 'Remates Visita: Más de 13.5', 'mercado': 'Remates',
            'prob': 0.80, 'cuota': 1.85, 'deporte': 'Fútbol',
            'tiros_regla': 'más', 'p_mod_tiros': 0.80, 'p_casa_tiros': 0.5}
    orig = ts.activo
    try:
        ts.activo = lambda *a: False
        v = dict(vp.evaluar(fila), pick=fila)
        bloqueada = v['veredicto'] == vp.NO_METER or bool(vp.franja_futbol(v))
        check(bloqueada, 'mientras la regla no se gana el puesto, no se mete')
        ts.activo = lambda *a: True
        v = dict(vp.evaluar(fila), pick=fila)
        check(v['veredicto'] == vp.METER and vp.franja_futbol(v) is None,
              'con la regla activada, se mete (%s)' % v['razones'][:1])
        sin = dict(fila, tiros_regla='')
        v = dict(vp.evaluar(sin), pick=sin)
        check(v['veredicto'] == vp.NO_METER or bool(vp.franja_futbol(v)),
              'y sólo la que cumple la regla')
    finally:
        ts.activo = orig


def probar_seguimiento():
    import tiros_seguimiento as ts
    check(ts.apuesta_de(0.62, 0.50, 'tiros', 1.9, 1.9) == 'más'
          and ts.apuesta_de(0.38, 0.50, 'tiros', 1.9, 1.9) == 'menos'
          and ts.apuesta_de(0.58, 0.50, 'tiros', 1.9, 1.9) == ''
          and ts.apuesta_de(0.62, 0.50, 'a_puerta', 1.9, 1.9) == ''
          and ts.apuesta_de(0.62, 0.50, 'tiros', 3.5, 1.3) == '',
          'la regla fijada: 10 puntos sobre la casa, tiros, cuota ≤ 3')
    t = tempfile.mkdtemp()
    csv = os.path.join(t, 's.csv')
    filas = []
    for i in range(160):
        filas.append({'fecha': '2026-09-20', 'partido': 'p%d' % i, 'clave_liga': 'x',
                      'equipo': 'e', 'lado': 'local', 'mercado': 'tiros',
                      'linea': 12.5, 'c_mas': 1.9, 'c_menos': 1.9, 'p_casa': 0.5,
                      'p_mod': 0.65, 'apuesta': 'más', 'origen': 'vivo',
                      'real': 15 if i % 4 else 10, 'registrado': ''})
    pd.DataFrame(filas).to_csv(csv, index=False)
    r = ts.medir(csv, os.path.join(t, 's.json'))
    check(r['n'] == 160 and r['activo'] and r['p5'] > 0,
          'con 160 apuestas al 75 %% a 1,90 se activa (p5 %s)' % r.get('p5'))
    check(ts.activo(os.path.join(t, 's.json')), 'y `activo` lo lee')
    pd.DataFrame(filas[:100]).to_csv(csv, index=False)
    r = ts.medir(csv, os.path.join(t, 's.json'))
    check(not r['activo'], 'con menos de 150, no')
    real = ts.medir(ts.FICHERO, os.path.join(t, 'r.json'))
    check(not real['activo'] and real['n'] >= 200,
          'hoy: %d apuestas desde el 10-sep, p5 %s, sin activar'
          % (real['n'], real.get('p5')))
    pre = open('precalculo_dia.py', encoding='utf-8').read()
    wf = open('.github/workflows/precalculo_dia.yml', encoding='utf-8').read()
    rt = open('.github/workflows/retrain_leagues.yml', encoding='utf-8').read()
    check('tiros_equipo.precalcular(' in pre and 'tiros_seguimiento.medir()' in pre
          and pre.index('tiros_equipo.precalcular(') < pre.index('decisiones_dia.anadir('),
          'el precálculo calcula los tiros antes de las decisiones y mide')
    check('tiros_dia.json' in wf and 'tiros_seguimiento.csv' in wf
          and 'tiros_equipo.py --entrenar' in rt,
          'los workflows publican y reentrenan')


if __name__ == '__main__':
    print('=== 1. el modelo ===')
    probar_modelo()
    print('\n=== 2. la tarjeta ===')
    probar_tarjeta()
    print('\n=== 3. el veredicto ===')
    probar_veredicto()
    print('\n=== 4. el seguimiento ===')
    probar_seguimiento()
    print('\n' + '=' * 40)
    print('TODO OK' if not FALLOS else '%d FALLOS' % len(FALLOS))
    raise SystemExit(1 if FALLOS else 0)
