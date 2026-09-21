#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test del radar de errores de cuota y de su cuaderno de capturas (v270-271).

Lo que se comprueba aquí es lo que ya ha fallado alguna vez, no una lista de
buenos deseos:

  · que el modelo se cargue de verdad. El selector se rompió el 2026-09-20
    porque git le cambió los saltos de línea a su fichero .txt y LightGBM
    contestó «Model format error, expect a tree here». El radar es otro .txt
    con el mismo peligro exacto.
  · que ordenar no reviente con dos puntuaciones iguales. La primera versión
    ordenaba pares (puntuación, diccionario) y con un empate Python intentaba
    comparar los diccionarios.
  · que puntuar y ordenar NUNCA lancen. Van dentro del barrido: si lanzan,
    el barrido se queda sin cuotas y el usuario sin picks.
  · que el cuaderno no repita el mismo partido doce veces al día.

Ejecutar:  .venv\\Scripts\\python test_radar.py
"""

import io
import os
import tempfile

FALLOS = []


def check(cond, msg):
    print(('OK   ' if cond else 'FALLO') + ' ' + msg)
    if not cond:
        FALLOS.append(msg)


# ---------------------------------------------------------------------------
# 1. El fichero del modelo, y la trampa de los saltos de línea
# ---------------------------------------------------------------------------
def probar_fichero():
    import radar_errores as radar

    attrs = io.open('.gitattributes', encoding='utf-8').read()
    check('radar_errores.txt' in attrs and '-text' in attrs.split(
        'radar_errores.txt')[1].split('\n')[0],
        '.gitattributes declara radar_errores.txt como binario')

    if not os.path.exists(radar.MODELO):
        check(True, 'sin modelo entrenado todavía: nada que comprobar')
        return
    crudo = io.open(radar.MODELO, 'rb').read(4096)
    check(b'\r\n' not in crudo,
          'el modelo está en LF (con CRLF, LightGBM lo rechaza)')
    check(crudo.startswith(b'tree'), 'el modelo empieza por «tree»')
    radar.olvidar()
    check(radar.disponible() is True, 'el modelo carga y queda disponible')


# ---------------------------------------------------------------------------
# 2. Puntuar y ordenar: alineados, acotados y sin lanzar nunca
# ---------------------------------------------------------------------------
def probar_puntuar():
    import radar_errores as radar

    normal = {'pinnacle': {'home': 2.1, 'draw': 3.3, 'away': 3.5},
              'liga': 'SPAIN: LaLiga', 'inicio': 1789938900}
    basura = [
        {},
        {'pinnacle': None, 'liga': None, 'inicio': None},
        {'pinnacle': {'home': 'x', 'away': None}, 'liga': 7, 'inicio': 'ayer'},
        {'pinnacle': {'home': 0.5, 'away': -3}, 'liga': '', 'inicio': -1},
        {'pinnacle': {'home': 2.0, 'away': 2.0}, 'liga': 'liga inventada',
         'inicio': 1789938900},
    ]
    try:
        ps = radar.puntuar([normal] + basura)
        check(len(ps) == 6, 'devuelve una puntuación por partido')
        check(all(isinstance(x, float) and 0.0 <= x <= 1.0 for x in ps),
              'todas las puntuaciones son probabilidades')
        check(ps[1] == 0.5 and ps[2] == 0.5,
              'lo que no se puede puntuar sale a 0,5, ni premio ni castigo')
    except Exception as e:
        check(False, 'puntuar lanzó con datos rotos: %r' % e)

    check(radar.puntuar([]) == [], 'una lista vacía no rompe nada')
    check(radar.puntuar(None) == [], 'None tampoco')

    # el empate: dos diccionarios con la misma puntuación
    iguales = [{'pinnacle': {}, 'liga': 'a', 'inicio': None},
               {'pinnacle': {}, 'liga': 'b', 'inicio': None},
               {'pinnacle': {}, 'liga': 'c', 'inicio': None}]
    try:
        r = radar.ordenar(iguales)
        check(len(r) == 3, 'ordenar con TODO empatado no revienta')
        check([x['liga'] for x in r] == ['a', 'b', 'c'],
              'con empate se respeta el orden de llegada')
    except Exception as e:
        check(False, 'ordenar lanzó con puntuaciones empatadas: %r' % e)

    try:
        r = radar.ordenar([normal] + basura)
        check(len(r) == 6, 'ordenar devuelve todos los partidos, no un subconjunto')
        ps2 = radar.puntuar(r)
        check(all(ps2[i] >= ps2[i + 1] - 1e-9 for i in range(len(ps2) - 1)),
              'salen de mayor a menor puntuación')
    except Exception as e:
        check(False, 'ordenar lanzó: %r' % e)


# ---------------------------------------------------------------------------
# 3. El cuaderno de capturas
# ---------------------------------------------------------------------------
def probar_capturas():
    import radar_capturas as cap

    antes = cap.FICHERO
    tmp = os.path.join(tempfile.mkdtemp(), 'capturas.csv')
    cap.FICHERO = tmp
    cap.olvidar()
    try:
        p = {'deporte': 'futbol', 'liga': 'MEXICO: Liga MX',
             'home': 'América', 'away': 'Chivas', 'inicio': 1789938900}
        pin = {'home': 2.0, 'draw': 3.4, 'away': 3.8}
        sin_valor = []
        con_valor = [{'ev': 0.04, 'prob_justa': 0.45, 'casa': 'Novibet'}]

        check(cap.anotar(p, pin, sin_valor) is True, 'anota la primera vez')
        check(cap.anotar(p, pin, sin_valor) is False,
              'no repite el mismo partido el mismo día')
        check(cap.anotar(p, pin, con_valor) is True,
              'sí vuelve a anotar si una pasada posterior SÍ encuentra error')
        check(cap.anotar(p, pin, con_valor) is False,
              'y ya no repite más una vez anotado el error')

        # dos filas, no cuatro: la primera pasada y la que encontró el error.
        # Las dos repetidas no escribieron nada.
        r = cap.resumen()
        check(r['filas'] == 2 and r['con_error'] == 1 and r['dias'] == 1,
              'el resumen cuadra: %s' % r)

        check(cap.anotar(p, {}, con_valor) is False,
              'sin precio de Pinnacle no se anota')
        check(cap.anotar({'home': '', 'away': ''}, pin, con_valor) is False,
              'sin nombres de equipo no se anota')

        # nunca lanza, pase lo que pase
        for malo in (None, {}, {'home': None, 'away': 3}):
            try:
                cap.anotar(malo, pin, con_valor)
            except Exception as e:
                check(False, 'anotar lanzó con %r: %r' % (malo, e))

        # el tenis y el béisbol no tienen empate
        q = cap.probabilidades({'home': 1.8, 'away': 2.0})
        check(q is not None and q['pin_draw'] is None
              and abs(q['q_home'] + q['q_away'] - 1.0) < 1e-9,
              'sin empate, las dos probabilidades suman 1')
        check(cap.probabilidades({'home': 0.5, 'away': 2.0}) is None,
              'una cuota imposible no produce probabilidades')

        e = cap.hubo_error([{'ev': 0.04, 'prob_justa': 0.20}])
        check(e['hay_error'] == 0,
              'una probabilidad por debajo del mínimo no cuenta como error')
        e = cap.hubo_error([{'ev': 0.001, 'prob_justa': 0.50}])
        check(e['hay_error'] == 0, 'una ventaja por debajo del mínimo tampoco')
    finally:
        cap.FICHERO = antes
        cap.olvidar()


# ---------------------------------------------------------------------------
# 4. El barrido corta por el tope pase lo que pase
# ---------------------------------------------------------------------------
def probar_prioriza():
    import cuotas_mx as mx

    evs = [{'id': str(i), 'home': 'A%d' % i, 'away': 'B%d' % i,
            'liga': 'X', 'inicio': 1789938900} for i in range(50)]
    try:
        r = mx._prioriza('futbol', evs, 10)
        check(len(r) == 10, 'nunca devuelve más partidos que el tope')
        check(all(x in evs for x in r), 'devuelve los eventos originales')
        check(mx._prioriza('futbol', evs, 200) == evs,
              'con tope mayor que la lista, la lista entera')
        check(mx._prioriza('futbol', [], 10) == [],
              'una lista vacía no rompe el barrido')
        check(len(mx._prioriza('deporte inventado', evs, 5)) == 5,
              'un deporte desconocido cae al corte de siempre')
    except Exception as e:
        check(False, '_prioriza lanzó: %r' % e)


# ---------------------------------------------------------------------------
# 5. Las dos fuentes del universo hablan el mismo idioma
# ---------------------------------------------------------------------------
def probar_universo():
    import radar_errores as radar

    columnas = {'fecha', 'liga', 'q_home', 'q_away', 'margen_pin',
                'hay_error', 'fuente'}
    led = radar._del_ledger()
    if led is not None:
        check(columnas.issubset(set(led.columns)),
              'el ledger aporta las columnas del universo')
    cap = radar._de_capturas()
    if cap is not None:
        check(columnas.issubset(set(cap.columns)),
              'las capturas aportan las mismas columnas')
    d = radar.construir_universo()
    if d is None:
        check(True, 'sin universo: nada que comprobar')
        return
    check(set(radar.FEATS).issubset(set(d.columns)),
          'el universo trae todas las variables del modelo')
    check(d['dt'].is_monotonic_increasing,
          'el universo va ordenado por fecha (si no, el corte por tiempo miente)')
    check(int(d['hay_error'].isin((0, 1)).all()) == 1,
          'la etiqueta es 0 o 1, sin nulos')


if __name__ == '__main__':
    print('=== 1. el fichero del modelo ===')
    probar_fichero()
    print('\n=== 2. puntuar y ordenar ===')
    probar_puntuar()
    print('\n=== 3. el cuaderno de capturas ===')
    probar_capturas()
    print('\n=== 4. el corte del barrido ===')
    probar_prioriza()
    print('\n=== 5. el universo ===')
    probar_universo()
    print('\n' + '=' * 40)
    print('TODO OK' if not FALLOS else '%d FALLOS' % len(FALLOS))
    raise SystemExit(1 if FALLOS else 0)
