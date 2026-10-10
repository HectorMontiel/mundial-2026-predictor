#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test de la v355.

El usuario: «lo mismo que la NBA para la MLB y la KBO: ganador, más/menos,
hándicap, abridores, ponches…; analiza patrones (cancha, altura, local/visita,
tabla); quiero verlos en Capa 1 y en Apuestas del día» y «hace falta un filtro
"En juego"».

Lo que se vigila:
  1. EL FILTRO «En juego».
  2. LA LIQUIDACIÓN DEL BÉISBOL: «visita @ local» (antes se cruzaban los
     lados: Cleveland ganó 9-5 de visitante y salió ROJA).
  3. LA MEDICIÓN: hándicap y totales por la probabilidad de la casa, estables
     en las dos mitades; ningún patrón contra la casa pasa; la KBO cuadra con
     las tablas de la MLB.
  4. LA TARJETA Y LA CAPA 1 de MLB/KBO con las escaleras de Playdoit.

Ejecutar:  python test_v355.py
"""
import json

import pandas as pd

FALLOS = []


def check(cond, msg):
    print(('OK   ' if cond else 'FALLO') + ' ' + msg)
    if not cond:
        FALLOS.append(msg)


def probar_en_juego():
    import modo_modelo as mm
    check(mm.ESTADOS == (mm.ESTADO_SIN_JUGAR, mm.ESTADO_EN_JUEGO, mm.ESTADO_JUGADOS,
                         mm.ESTADO_TODOS),
          'el filtro: Sin jugar · En juego · Finalizados · Todos')
    check(mm.en_juego({'jugado': True, 'en_juego': True})
          and not mm.en_juego({'jugado': True, 'en_juego': True, 'goles_home': 1})
          and not mm.en_juego({'jugado': True}),
          'en juego = empezado y sin marcador final')


def probar_liquidacion():
    import modo_modelo as mm
    import pronosticos_guardados as pg
    p = {'deporte': 'MLB', 'partido': 'Cleveland Guardians @ Chicago White Sox',
         'goles_home': 5.0, 'goles_away': 9.0, 'clave_liga': 'mlb', 'jugado': True}
    check(mm._equipos(p) == ('Chicago White Sox', 'Cleveland Guardians'),
          'en «visita @ local» el local es el de después de la @')
    f = pg.validar(p, filas=[{'apuesta': 'Gana Cleveland Guardians', 'mercado': '1X2',
                              'bloque': 'resultado', 'etiqueta': 'Resultado',
                              'veredicto': 'meter'}])
    check(f and f[0]['estado'] == pg.CUMPLIDO,
          'Cleveland ganó 9-5 de visitante: VERDE (antes salía roja)')
    check(mm._equipos({'partido': 'A vs B'}) == ('A', 'B'), 'el fútbol, igual que siempre')
    import lo_mejor as lm
    check(lm.resultado('Handicap: Cleveland Guardians +2.5',
                       'Chicago White Sox @ Cleveland Guardians', 3, 4) == 'verde',
          'y el hándicap de la Capa 1 también con la @')


def probar_medicion():
    m = json.load(open('mlb_lineas.json', encoding='utf-8'))
    hj = {b['banda']: b for b in m['handicap']}
    he = {b['banda']: b for b in m['elige']['handicap']}
    f = '(0.55, 0.6]'
    check(hj[f]['+2.5'] >= 0.76 and hj[f]['+3.5'] >= 0.82,
          'favorito 55-60 %%: +2,5 %.0f %%, +3,5 %.0f %% (juzga 2017-21)'
          % (100 * hj[f]['+2.5'], 100 * hj[f]['+3.5']))
    dif = max(abs(hj[b][c] - he[b][c]) for b in hj for c in ('+1.5', '+2.5', '+3.5', '+4.5')
              if b in he and hj[b]['n'] >= 500)
    check(dif < 0.05, 'estable en las dos mitades (máx. %.1f pts)' % (100 * dif))
    check(m['totales']['mas']['3.5'] >= 0.77 and m['totales']['menos']['4.5'] >= 0.80,
          'totales: más a 3,5 carreras %.0f %%, menos a 4,5 %.0f %%'
          % (100 * m['totales']['mas']['3.5'], 100 * m['totales']['menos']['4.5']))
    check(m['patrones_que_pasan'] == [],
          'ningún patrón (estadio, altura, local, tabla, zurdo, mes…) le gana a la casa')
    import mlb_lineas as ml
    k = pd.read_csv('cuotas_kbo_cierre.csv').dropna(subset=['odd_home', 'odd_away',
                                                            'runs_home', 'runs_away'])
    s = 1 / k.odd_home + 1 / k.odd_away
    ph = (1 / k.odd_home) / s
    pred, real = [], []
    for p_, m_ in zip(ph, k.runs_home - k.runs_away):
        for pe, mm_ in ((p_, m_), (1 - p_, -m_)):
            pred.append(ml.prob_handicap(pe, 3.5))
            real.append(int(mm_ + 3.5 > 0))
    check(abs(sum(pred) / len(pred) - sum(real) / len(real)) < 0.03,
          'KBO (%d cierres): la tabla de la MLB predice %.1f %% en +3,5 y pasó %.1f %%'
          % (len(k), 100 * sum(pred) / len(pred), 100 * sum(real) / len(real)))


TAB = {'p_local': 0.5526, 'ml': {'local': 1.74, 'visita': 2.15},
       'handicap': {'local': {'2.5': 1.2353, '1.5': 1.45, '-1.5': 2.5},
                    'visita': {'3.5': 1.1819, '1.5': 1.6, '4.5': 1.11}},
       'totales': {'principal': 7.0, 'mas': {'7': 1.9, '4.5': 1.36, '5.5': 1.6},
                   'menos': {'7': 1.9, '9.5': 1.33, '10.5': 1.2}}}


def probar_tarjeta():
    import mlb_lineas as ml
    import veredicto_pick as vp
    det = {'mercados': [
        {'nombre': 'Totales (incl. extra innings)', 'selecciones': [
            {'nombre': 'Más de 6', 'cuota': 1.91}, {'nombre': 'Menos de 6', 'cuota': 1.91},
            {'nombre': 'Más de 5.5', 'cuota': 1.71}, {'nombre': 'Menos de 5.5', 'cuota': 2.05}]}]}
    check(ml.del_tablero(det, 'Milwaukee Brewers', 'Los Angeles Dodgers')['totales']['principal'] == 6,
          'la línea principal puede ser entera (6 a 1,91/1,91)')
    p = {'deporte': 'MLB', 'partido': 'Chicago White Sox @ Cleveland Guardians',
         'implicitas': {'mlb_playdoit': TAB}}
    el = ml.elegidas(p)
    met = [c for c in el if not c.get('informativa')]
    check(any(c['apuesta'] == 'Handicap: Cleveland Guardians +2.5' for c in met),
          'Cleveland (55 %%) +2,5 a 1,24: se mete (%s)' % [(c['apuesta'], c['prob']) for c in met])
    c = met[0]
    fila = {'deporte': 'MLB', 'apuesta': c['apuesta'], 'mercado': 'Handicap', 'prob': c['prob'],
            'cuota': c['cuota'], 'mlb_linea': True}
    check(vp.evaluar(fila)['veredicto'] == vp.METER, 'el veredicto la mete')
    check(vp.evaluar({'deporte': 'MLB', 'apuesta': 'Carreras: Menos de 10.5', 'mercado': 'Carreras',
                      'prob': 0.72, 'cuota': 1.4})['veredicto'] == vp.NO_METER,
          'lo que no sale de la tabla medida sigue sin meterse')
    pk = dict(p, deporte='KBO', partido='SSG Landers @ Kia Tigers')
    ek = ml.candidatas(pk)
    check(ek and all(c['mercado'] == 'Handicap' for c in ek),
          'KBO: el hándicap sí; los totales no (sin historial de líneas)')
    import lo_mejor as lm
    p84 = dict(p, implicitas={'mlb_playdoit': dict(TAB, handicap={
        'local': {'4.5': 1.12}, 'visita': {'1.5': 1.6}})})
    e = lm.del_pick(p84)
    check(e is not None and e['prob'] >= 0.84 and e['deporte'] == 'MLB',
          'Capa 1 🏆 MLB: el hándicap de ≥ 84 %% (%s)' % ((e and (e['apuesta'], e['prob'])),))


def probar_abridores():
    import modo_modelo as mm
    h = mm._analisis_conciso_html(
        {'deporte': 'MLB', 'partido': 'Los Angeles Dodgers @ Milwaukee Brewers',
         'abridores': {'visita': {'nombre': 'Tarik Skubal', 'era': 2.7,
                                  'ponches_esperados': 7.4}}}, {}, None, None)
    check('⚾ Abridores' in h and 'Tarik Skubal' in h and '7,4 ponches esperados' in h,
          'el análisis enseña el abridor y sus ponches esperados')


if __name__ == '__main__':
    print('=== 1. En juego ===')
    probar_en_juego()
    print('\n=== 2. la liquidación del béisbol ===')
    probar_liquidacion()
    print('\n=== 3. la medición ===')
    probar_medicion()
    print('\n=== 4. tarjeta y Capa 1 ===')
    probar_tarjeta()
    probar_abridores()
    print('\n' + '=' * 40)
    print('TODO OK' if not FALLOS else '%d FALLOS' % len(FALLOS))
    raise SystemExit(1 if FALLOS else 0)
