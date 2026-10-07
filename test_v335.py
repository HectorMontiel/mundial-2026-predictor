#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test de la v335.

El usuario: «quiero ambas» (meter decidido por el precio de la casa, y buscar
información que la casa no tenga); «valida con simulaciones de los partidos
más recientes… quiero ver las cifras antes/después»; «si hay reglas que se
pueden romper para que el modelo mejore, hazlo, siempre que lo fundamentes».

Lo que se vigila:

  1. LA REGLA: donde la casa cotiza, se mete con casa sin margen ≥ 74 %,
     modelo ≥ 70 % y cuota 1,15-1,35; sin precio de la casa, no; córners y
     tarjetas siguen con la franja 70-80 % del modelo; la línea 2,5 y los
     mercados excluidos siguen fuera.
  2. LA TARJETA: suma las candidatas que respalda la casa y ordena las
     «meter» por ese precio.
  3. LO MEDIDO: la simulación rehecha con el código real mejora en los dos
     tramos y el histórico pasa con p5 > 0.

Ejecutar:  python test_v335.py
"""
import json
import os

FALLOS = []


def check(cond, msg):
    print(('OK   ' if cond else 'FALLO') + ' ' + msg)
    if not cond:
        FALLOS.append(msg)


def motivo(ap, mercado='Goles', prob=0.75, cuota=1.25, casa=0.78, dep='Fútbol'):
    import veredicto_pick as vp
    v = {'pick': {'deporte': dep, 'apuesta': ap, 'mercado': mercado, 'cuota': cuota,
                  'p_mercado': casa},
         'mercado': mercado, 'prob_ajustada': prob}
    return vp.franja_futbol(v)


def probar_la_regla():
    import veredicto_pick as vp
    check((vp.METER_CASA_MIN, vp.METER_CASA_MODELO_MIN, vp.METER_CASA_CUOTA_MIN)
          == (0.74, 0.70, 1.15), 'casa ≥ 74 %, modelo ≥ 70 %, cuota ≥ 1,15')
    check(vp.CUOTA_METER_FUTBOL_MAX == 1.35, 'el tope de cuota 1,35 se queda')
    check(motivo('Goles: Más de 1.5') is None, 'casa 78 %, modelo 75 %, 1,25 → se mete')
    check(bool(motivo('Goles: Más de 1.5', casa=0.72)), 'casa 72 % → no')
    check(bool(motivo('Goles: Más de 1.5', prob=0.68)), 'modelo 68 % → no')
    check(bool(motivo('Goles: Más de 1.5', cuota=1.12)), 'cuota 1,12 → no (paga muy poco)')
    check(bool(motivo('Goles: Más de 1.5', cuota=1.35)), 'cuota 1,35 → no')
    check(bool(motivo('Goles: Más de 1.5', casa=None)), 'sin precio de la casa → no')
    check(motivo('Goles: Más de 1.5', prob=0.84, casa=0.82, cuota=1.18) is None,
          'modelo 84 % con la casa de acuerdo → se mete (83,3 % medido)')
    for mer in ('1X2', 'Doble oportunidad', 'Goles equipo', 'BTTS'):
        check(mer in vp.MERCADOS_CON_PRECIO, '«%s» lo decide el precio' % mer)
    check(motivo('Córners: Menos de 9.5', mercado='Córners', casa=None) is None,
          'córners sin precio: sigue la franja del modelo')
    check(bool(motivo('Córners: Menos de 9.5', mercado='Córners', prob=0.84, casa=None)),
          'y fuera de 70-80 % no')
    check(bool(motivo('Goles: Más de 2.5')), 'la línea 2,5 sigue fuera (v331)')
    check(bool(motivo('x', mercado='Doble y goles')), '«doble y goles» sigue fuera')
    check(motivo('Goles: Más de 1.5', dep='Tenis', casa=None) is None,
          'fuera del fútbol no cambia')


def probar_la_tarjeta():
    src = open('modo_modelo.py', encoding='utf-8').read()
    check('_candidatas_de_la_casa(pick, bloques, candidatas)' in src,
          'la tarjeta suma las candidatas que respalda la casa')
    check('-float(_prioridad_meter(v) or 0)' in src,
          'y ordena las «meter» por el precio de la casa')
    import modo_modelo as mm
    import veredicto_pick as vp
    v = {'veredicto': vp.METER, 'mercado': 'Goles', 'prob_ajustada': 0.76,
         'pick': {'mercado': 'Goles', 'p_mercado': 0.81}}
    check(mm._prioridad_meter(v) == 0.81, 'con precio, ordena por la casa')
    v['pick']['p_mercado'] = None
    check(mm._prioridad_meter(v) == 0.76, 'sin precio, por la probabilidad corregida')


def probar_lo_medido():
    for f in ('_v335_compara.json', '_v335_historico.json', '_v335_meter_casa.json'):
        check(os.path.exists(f), 'existe %s' % f)
    if os.path.exists('_v335_compara.json'):
        c = json.load(open('_v335_compara.json', encoding='utf-8'))
        for t in ('mirar', 'juzgar', 'todo'):
            a, d = c[t]['antes'], c[t]['despues']
            check(d[0] >= a[0], 'simulación real, %s: %.1f → %.1f %%' % (t, 100 * a[0], 100 * d[0]))
        check(c['todo']['despues'][1] >= 0.9 * c['todo']['antes'][1],
              'sin perder más del 10 %% de las apuestas (%d → %d)'
              % (c['todo']['antes'][1], c['todo']['despues'][1]))
        check(c['todo']['despues'][2] >= 1.20, 'la cuota media no baja de 1,20 (%.3f)'
              % c['todo']['despues'][2])
    if os.path.exists('_v335_historico.json'):
        h = json.load(open('_v335_historico.json', encoding='utf-8'))
        check(h['boot'][1] > 0, 'histórico, juicio: p5 %+.2f > 0' % h['boot'][1])
        check(h['mitad1'][2] > h['mitad1'][0] and h['mitad2'][2] > h['mitad2'][0],
              'mejor en las dos mitades del histórico')


if __name__ == '__main__':
    print('=== 1. la regla ===')
    probar_la_regla()
    print('\n=== 2. la tarjeta ===')
    probar_la_tarjeta()
    print('\n=== 3. lo medido ===')
    probar_lo_medido()
    print('\n' + '=' * 40)
    print('TODO OK' if not FALLOS else '%d FALLOS' % len(FALLOS))
    raise SystemExit(1 if FALLOS else 0)
