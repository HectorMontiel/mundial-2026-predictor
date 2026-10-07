#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test de la v331.

El usuario: «quiero que veas qué patrones hay en las apuestas rojas… haz
hipótesis, método científico y simulaciones; tiene que haber algo mejor, sin
bajar las cuotas a 1,20».

Lo que se vigila:

  1. LA LÍNEA 2,5 DEL TOTAL DE GOLES NO SE «METE» (la única de las once
     hipótesis que pasó las tres pruebas); 1,5, 3,5 y los goles por equipo
     siguen igual, y la regla de la v312 no se ha movido.
  2. LO MEDIDO SIGUE DICIENDO LO MISMO: los JSON de la v331 existen, la
     memoria del equipo no pasa, y la línea 2,5 acierta menos de lo que
     promete en el histórico.

Ejecutar:  python test_v331.py
"""
import json
import os

FALLOS = []


def check(cond, msg):
    print(('OK   ' if cond else 'FALLO') + ' ' + msg)
    if not cond:
        FALLOS.append(msg)


def motivo(apuesta, mercado='Goles', prob=0.75, cuota=1.28, dep='Fútbol'):
    import veredicto_pick as vp
    v = {'pick': {'deporte': dep, 'apuesta': apuesta, 'mercado': mercado,
                  'cuota': cuota},
         'mercado': mercado, 'prob_ajustada': prob}
    return vp.franja_futbol(v)


def probar_la_linea():
    import veredicto_pick as vp
    check((vp.METER_FUTBOL_MIN, vp.METER_FUTBOL_MAX,
           vp.CUOTA_METER_FUTBOL_MAX) == (0.70, 0.80, 1.35),
          'la franja de la v312 no se mueve (70-80 %, cuota < 1,35)')
    for ap in ('Goles: Más de 2.5', 'Goles: Menos de 2.5'):
        m = motivo(ap)
        check(bool(m) and '2,5' in m, '«%s» no se mete y dice por qué' % ap)
    for ap in ('Goles: Más de 1.5', 'Goles: Menos de 3.5',
               'Goles: Menos de 4.5'):
        check(motivo(ap) is None, '«%s» se sigue metiendo' % ap)
    check(motivo('Goles Boca: Más de 2.5', mercado='Goles equipo') is None,
          'los goles POR EQUIPO a 2,5 no se tocan (no están medidos)')
    check(motivo('Goles: Más de 2.5', dep='Tenis') is None,
          'fuera del fútbol no cambia nada')
    check(bool(motivo('Goles: Más de 1.5', cuota=1.40)),
          'el tope de cuota sigue mandando')


def probar_lo_medido():
    for f in ('_v331_memoria_equipos.json', '_v331_hipotesis.json',
              '_v331_linea_25.json', '_v331_meta_ablacion_sin_btts.json'):
        check(os.path.exists(f), 'existe %s' % f)
    if os.path.exists('_v331_memoria_equipos.json'):
        m = json.load(open('_v331_memoria_equipos.json', encoding='utf-8'))
        check(not m['resultado']['r1']['pasa'] and not m['goles']['r1']['pasa'],
              'saltar al equipo tras un rojo NO pasa (no volver a proponerlo)')
    if os.path.exists('_v331_linea_25.json'):
        l = json.load(open('_v331_linea_25.json', encoding='utf-8'))
        h = l['historico']
        check(h['juzgar']['con'] > h['juzgar']['sin'] and h['p5_sin'] > 0,
              'quitar la 2,5 mejora el juicio del histórico con p5 > 0')
        check(all(x[1] < x[0] for x in h['anios'].values()),
              'la 2,5 acierta menos de lo que promete en todos los años')
        for k in ('reales', 'simulacion'):
            r = l[k]
            check(r['mirar']['con'] >= r['mirar']['sin']
                  and r['juzgar']['con'] >= r['juzgar']['sin'],
                  'en %s queda igual o mejor en los dos tramos' % k)


if __name__ == '__main__':
    print('=== 1. la línea 2,5 ===')
    probar_la_linea()
    print('\n=== 2. lo medido ===')
    probar_lo_medido()
    print('\n' + '=' * 40)
    print('TODO OK' if not FALLOS else '%d FALLOS' % len(FALLOS))
    raise SystemExit(1 if FALLOS else 0)
