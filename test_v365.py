#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test de la v365.

El usuario, con Andorra–Castellón (11-oct): «antes me salía Goles Castellón
más de 0,5 como se mete (fijada) y ahora me marcas que no era se mete».

Lo que se vigila:
  1. EL PARTIDO EMPEZADO usa lo ARCHIVADO AL PITIDO (lo oficial, lo que
     cuenta el marcador), no lo guardado la primera vez que se pintó.
  2. Si se metía algo y aún no hay resultado, la tarjeta lo dice («por
     liquidar»), no «no había nada que meter».
  3. `test_v323` ya no depende del reloj: `anunciadas` acepta una hora
     congelada (`ANUNCIADAS_AHORA`), sólo para las pruebas.

Ejecutar:  python test_v365.py
"""
import os

FALLOS = []


def check(cond, msg):
    print(('OK   ' if cond else 'FALLO') + ' ' + msg)
    if not cond:
        FALLOS.append(msg)


def probar_archivo_manda():
    import pronosticos_guardados as pg
    viejo = pg.de_partido
    # lo guardado la primera vez: una sola «se mete»
    pg.de_partido = lambda *a, **k: {'recomendadas': [
        {'apuesta': 'Goles: Menos de 4.5', 'bloque': 'goles', 'etiqueta': 'Total',
         'veredicto': 'meter', 'prob': 0.81}]}
    try:
        p = {'partido': 'Andorra vs Castellon', 'clave_liga': 'esp_segunda', 'fecha': '2026-10-11',
             'goles_home': 1, 'goles_away': 0, 'recomendadas_previas': [
                 {'apuesta': 'Goles: Menos de 4.5', 'bloque': 'goles', 'etiqueta': 'Total',
                  'veredicto': 'meter', 'prob': 0.82},
                 {'apuesta': 'Goles Castellon: Más de 0.5', 'bloque': 'goles_equipo',
                  'etiqueta': 'Visitante', 'veredicto': 'meter', 'prob': 0.73}]}
        f = pg.validar(p)
        check([(x['apuesta'], x['estado']) for x in f] ==
              [('Goles: Menos de 4.5', pg.CUMPLIDO), ('Goles Castellon: Más de 0.5', pg.FALLADO)],
              'manda lo archivado al pitido: las dos «se mete», ✅ y ❌ con el 1-0 (%s)'
              % [(x['apuesta'], x['estado']) for x in f])
        q = {k: v for k, v in p.items() if k != 'recomendadas_previas'}
        check([x['apuesta'] for x in pg.validar(q)] == ['Goles: Menos de 4.5'],
              'sin archivo, lo guardado sigue sirviendo (partidos viejos)')
    finally:
        pg.de_partido = viejo
    src = open('modo_modelo.py', encoding='utf-8').read()
    check("'🎯 se metía: %d, por liquidar · '" in src,
          'con apuestas pendientes dice «por liquidar», no «no había nada que meter»')


def probar_reloj():
    import anunciadas as an
    os.environ['ANUNCIADAS_AHORA'] = '2026-10-11T07:00:00Z'
    try:
        check(an._ahora().strftime('%Y-%m-%dT%H:%M') == '2026-10-11T07:00',
              'las pruebas pueden congelar la hora de «anunciadas»')
    finally:
        os.environ.pop('ANUNCIADAS_AHORA', None)
    check(abs((an._ahora() - __import__('datetime').datetime.now(
        __import__('datetime').timezone.utc)).total_seconds()) < 5,
          'sin la variable, la hora de verdad (producción)')
    t = open('test_v323.py', encoding='utf-8').read()
    check("os.environ['ANUNCIADAS_AHORA']" in t, 'y test_v323 la congela')


if __name__ == '__main__':
    print('=== 1-2. el partido empezado ===')
    probar_archivo_manda()
    print('\n=== 3. el reloj de las pruebas ===')
    probar_reloj()
    print('\n' + '=' * 40)
    print('TODO OK' if not FALLOS else '%d FALLOS' % len(FALLOS))
    raise SystemExit(1 if FALLOS else 0)
