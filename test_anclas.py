#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test del ancla de reserva (v273).

Lo que se vigila aquí es sobre todo que esto NO se encienda solo. Un ancla mala
no produce menos picks: produce picks FALSOS, con un EV calculado contra una
referencia equivocada, y esos se cobran del banco de verdad.

  · la puerta de la muestra: con pocos pares, `activo` tiene que ser False
  · la puerta del parecido: aunque haya muestra, si no se pega a Pinnacle
    tampoco se enciende
  · el id 44 no puede estar entre las candidatas: su margen tiene una
    desviación del 15,21 % y no es una casa, es un agregado
  · capturar nunca lanza, porque va dentro del workflow de las cuotas y no
    puede llevarse por delante el commit de los precios

Ejecutar:  .venv\\Scripts\\python test_anclas.py
"""

import csv
import io
import os
import tempfile

FALLOS = []


def check(cond, msg):
    print(('OK   ' if cond else 'FALLO') + ' ' + msg)
    if not cond:
        FALLOS.append(msg)


def _escribir(ruta, filas):
    import anclas
    with io.open(ruta, 'w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=anclas.CAMPOS, extrasaction='ignore')
        w.writeheader()
        w.writerows(filas)


def _fila(i, casa, ch, cd, ca, ph=None, pd_=None, pa=None):
    return {'fecha': '2026-09-21', 'capturado': '2026-09-21T00:00:00Z',
            'event_id': 'ev%d' % i, 'deporte': 'futbol', 'liga': 'X',
            'home': 'A%d' % i, 'away': 'B%d' % i, 'inicio': '',
            'casa_id': casa, 'c_home': ch, 'c_draw': cd, 'c_away': ca,
            'pin_home': ph or '', 'pin_draw': pd_ or '', 'pin_away': pa or ''}


def probar_candidatas():
    import anclas
    check(44 not in anclas.CANDIDATAS,
          'el id 44 NO es candidata (margen inestable: no es una casa)')
    check(len(anclas.CANDIDATAS) >= 2,
          'hay mas de una candidata, para poder compararlas entre si')
    check(anclas.MIN_PARES >= 100,
          'la muestra minima es seria (%d pares)' % anclas.MIN_PARES)
    check(0 < anclas.ERROR_MAXIMO_PP <= 2.0,
          'el error maximo tolerado es exigente (%s pp)'
          % anclas.ERROR_MAXIMO_PP)


def probar_puertas():
    import anclas

    d = tempfile.mkdtemp()
    csv_tmp = os.path.join(d, 'cap.csv')
    meta_tmp = os.path.join(d, 'meta.json')
    antes = (anclas.FICHERO, anclas.META)
    anclas.FICHERO, anclas.META = csv_tmp, meta_tmp
    anclas.olvidar()
    try:
        b = anclas.CANDIDATAS[0]

        # 1. muestra corta: aunque el parecido sea PERFECTO, no se enciende
        _escribir(csv_tmp, [_fila(i, b, 2.0, 3.5, 4.0, 2.0, 3.5, 4.0)
                            for i in range(10)])
        r = anclas.medir(meta_tmp)
        check(r.get('activo') is False,
              'con 10 pares identicos a Pinnacle NO se enciende')
        check('faltan' in str(r.get('motivo')),
              'y dice cuantos pares faltan: %s' % r.get('motivo'))

        # 2. muestra suficiente pero precios distintos: tampoco
        _escribir(csv_tmp, [_fila(i, b, 1.5, 4.0, 7.0, 3.0, 3.4, 2.4)
                            for i in range(anclas.MIN_PARES + 20)])
        r = anclas.medir(meta_tmp)
        check(r.get('activo') is False,
              'con muestra pero sin parecerse a Pinnacle, tampoco se enciende')
        f = (r.get('casas') or {}).get(str(b)) or {}
        check(f.get('suficiente') is True,
              'aun asi reconoce que la muestra ya es suficiente')
        check((f.get('error_mediano_pp') or 0) > anclas.ERROR_MAXIMO_PP,
              'y mide un error por encima del maximo (%s pp)'
              % f.get('error_mediano_pp'))

        # 3. muestra suficiente Y parecido: pasa la PRIMERA puerta, y aun asi
        #    `activo` sigue en False, porque falta la de los resultados
        _escribir(csv_tmp, [_fila(i, b, 2.0, 3.5, 4.0, 2.0, 3.5, 4.0)
                            for i in range(anclas.MIN_PARES + 20)])
        r = anclas.medir(meta_tmp)
        check(r.get('candidata') == b,
              'con muestra y parecido, senala la candidata')
        check(r.get('activo') is False,
              'PERO sigue sin encenderse: falta que sus picks hayan ganado')
        check('segunda puerta' in str(r.get('motivo')),
              'y lo dice con todas las letras: %s' % r.get('motivo'))
        check(anclas.disponible() is False,
              'disponible() sigue devolviendo False')
    finally:
        anclas.FICHERO, anclas.META = antes
        anclas.olvidar()


def probar_no_lanza():
    import anclas

    check(anclas._probabilidades(None, None, None) is None,
          'sin cuotas no hay probabilidades')
    check(anclas._probabilidades(0.5, 3.0, 4.0) is None,
          'una cuota imposible se rechaza')
    q = anclas._probabilidades(2.0, 3.5, 4.0)
    check(q is not None and abs(q['home'] + q['draw'] + q['away'] - 1) < 1e-9,
          'las tres probabilidades suman 1')
    check(q['margen'] > 0, 'y el margen sale positivo (%.3f)' % q['margen'])

    # capturar sobre un tablero que no existe: no puede lanzar
    try:
        r = anclas.capturar(ruta='_no_existe_a_proposito.json')
        check(r.get('filas') == 0,
              'sin tablero no captura nada, y no lanza')
    except Exception as e:
        check(False, 'capturar lanzo sin tablero: %r' % e)

    d = tempfile.mkdtemp()
    antes = anclas.META
    anclas.META = os.path.join(d, 'no_existe.json')
    try:
        check(anclas.disponible() is False,
              'sin fichero de medicion, disponible() es False')
    finally:
        anclas.META = antes


def probar_no_toca_produccion():
    """Lo mas importante: esto no puede colarse en el precio accionable."""
    import io as _io
    fuente = _io.open('anclas.py', encoding='utf-8').read()
    check('cuotas_mx.json' in fuente,
          'lee el tablero (para saber que partidos hay)')
    check("FICHERO = 'anclas_capturas.csv'" in fuente,
          'pero escribe en su PROPIO fichero, no en el tablero')
    for otro in ('cuotas_multi.py', 'alpha_finder.py', 'barrido_capa1.py'):
        s = _io.open(otro, encoding='utf-8').read()
        check('import anclas' not in s and 'anclas.' not in s,
              '%s NO usa todavia el ancla de reserva' % otro)


if __name__ == '__main__':
    print('=== 1. las candidatas ===')
    probar_candidatas()
    print('\n=== 2. las dos puertas ===')
    probar_puertas()
    print('\n=== 3. nunca lanza ===')
    probar_no_lanza()
    print('\n=== 4. no toca produccion ===')
    probar_no_toca_produccion()
    print('\n' + '=' * 40)
    print('TODO OK' if not FALLOS else '%d FALLOS' % len(FALLOS))
    raise SystemExit(1 if FALLOS else 0)
