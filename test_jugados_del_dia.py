#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test de los finalizados del día y de la carrera del workflow de cuotas
(v305).

El usuario: «me borras los anteriores del día de hoy, cuando debería
mostrarme todos los finalizados del día hasta la hora de actualización», y un
correo de GitHub: «Cuotas de las casas mexicanas: All jobs have failed».

Lo que se vigila:

  · LA LISTA DEL DÍA SÓLO CRECE: lo que ya había en el fichero del mismo día
    se conserva aunque la pasada nueva no lo traiga.
  · LO QUE ESTABA EN EL PRONÓSTICO Y YA SE JUGÓ ENTRA COMO FINALIZADO, con su
    pronóstico previo. Lo que no ha empezado o puede seguir en juego, no.
  · EL DÍA ES EL DE CDMX en el precálculo, no el del servidor.
  · EL PRECÁLCULO VA A LA RED y no se fía de la marca del barrido.
  · EL WORKFLOW DE CUOTAS mide la edad con el tablero de main recién traído y
    sube con reintentos y resolviendo el conflicto a favor de lo recién
    barrido.

Ejecutar:  python test_jugados_del_dia.py
"""
import json
import os
import tempfile
import time

FALLOS = []


def check(cond, msg):
    print(('OK   ' if cond else 'FALLO') + ' ' + msg)
    if not cond:
        FALLOS.append(msg)


def _pron(partido, inicio_ts, liga='champions_femenil'):
    import datetime as dt
    ini = dt.datetime.fromtimestamp(inicio_ts, dt.timezone.utc).strftime(
        '%Y-%m-%d %H:%M:%S')
    return {'deporte': 'Fútbol', 'partido': partido, 'clave_liga': liga,
            'inicio': ini, 'fecha': ini[:10], 'prob': 0.6,
            'board': {'Gana X': 0.6}}


def probar_el_archivo_y_la_union():
    import partidos_jugados as pj
    import dia_picks as dp
    import datetime as _dt
    # v310 — una hora FIJA de referencia (las 23:00 UTC de hoy, 17:00 de
    # CDMX): con `time.time()` el test fallaba de madrugada en México, cuando
    # «hace 4 h» y «hace 30 min» caen en días distintos de CDMX.
    _hoy = _dt.datetime.now(_dt.timezone.utc).replace(hour=23, minute=0,
                                                       second=0, microsecond=0)
    ahora = _hoy.timestamp()
    d = tempfile.mkdtemp()
    hoy = dp.hoy_local().strftime('%Y-%m-%d')
    # un partido de hoy que empezó hace 4 h y otro que empezó hace 30 min
    import horario as hz
    base = ahora - 4 * 3600
    viejo = _pron('Equipo A vs Equipo B', base)
    reciente = _pron('Equipo C vs Equipo D', ahora - 1800)
    futuro = _pron('Equipo E vs Equipo F', ahora + 3 * 3600)
    rp = os.path.join(d, 'pd.json')
    with open(rp, 'w', encoding='utf-8') as f:
        json.dump({'datos': {'pronosticos': [viejo, reciente, futuro]}}, f)
    arch = pj.archivar_del_pronostico(dp.dia_de(viejo), rp, ahora=ahora)
    nombres = [p['partido'] for p in arch]
    check('Equipo A vs Equipo B' in nombres,
          'el que ya se jugó entra como finalizado')
    # v309 — el que empezó hace 30 min SÍ se archiva: esperar 2,5 h con
    # pasadas cada 1,6 h hacía que no se archivara NUNCA (ver la cabecera
    # v309 de `partidos_jugados`). La vista lo marca «en juego».
    check('Equipo C vs Equipo D' in nombres,
          'v309: el que ya empezó se archiva aunque siga en juego (%s)'
          % nombres)
    check('Equipo E vs Equipo F' not in nombres,
          'el que no ha empezado, no (%s)' % nombres)
    check(all(p.get('jugado') and p.get('board') for p in arch),
          'y conserva su pronóstico previo')
    # la unión: lo previo no se pierde y gana el que trae marcador
    a = {'partido': 'X vs Y', 'goles_home': None}
    b = {'partido': 'X vs Y', 'goles_home': 2, 'goles_away': 1}
    c = {'partido': 'Z vs W', 'goles_home': 0, 'goles_away': 0}
    u = pj.unir([a], [c], [b])
    check(len(u) == 2, 'une sin repetir (%d)' % len(u))
    check(any(p['partido'] == 'X vs Y' and p['goles_home'] == 2 for p in u),
          'y ante el mismo partido gana el que trae marcador')
    # escribir_dia: lo que ya había en el fichero del día se conserva
    rj = os.path.join(d, 'jug.json')
    with open(rj, 'w', encoding='utf-8') as f:
        json.dump({'dia': hoy, 'ts': ahora,
                   'partidos': [{'partido': 'Previo vs Anterior',
                                 'jugado': True, 'goles_home': 1,
                                 'goles_away': 1,
                                 'inicio': '2000-01-01 00:00:00'}]}, f)
    orig = pj._de_dia_por_red
    orig_fm = pj.marcadores_fotmob
    pj._de_dia_por_red = lambda dia, maximo=200, usar_cache=True: []
    pj.marcadores_fotmob = lambda dia: []          # sin red en el test
    try:
        pj.escribir_dia(hoy, ruta=rj, ruta_pronostico=rp)
    finally:
        pj._de_dia_por_red = orig
        pj.marcadores_fotmob = orig_fm
    doc = json.load(open(rj, encoding='utf-8'))
    ps = [p['partido'] for p in doc['partidos']]
    check('Previo vs Anterior' in ps,
          'una pasada nueva NO borra lo que ya estaba del día (%s)' % ps)


def probar_el_codigo():
    src = open('precalculo_dia.py', encoding='utf-8').read()
    i = src.find('escribir_dia(')
    check(i > 0 and 'hoy_local()' in src[i - 900:i],
          'el precálculo cocina el día de CDMX')
    check('ruta_pronostico=a.salida' in src,
          'y le pasa el pronóstico anterior para archivar lo ya jugado')
    pj = open('partidos_jugados.py', encoding='utf-8').read()
    check('usar_cache=False' in pj, 'el precálculo va a la red de verdad')
    fe = open('fixtures_espn.py', encoding='utf-8').read()
    check('usar_cache: bool = True' in fe,
          'jugados_del_dia sabe saltarse la marca del barrido')


def probar_el_workflow():
    import yaml
    t = open('.github/workflows/cuotas_mx.yml', encoding='utf-8').read()
    yaml.safe_load(t)
    i = t.find('FRESCURA_MINUTOS=')
    j = t.find("get('generado')", i)
    k = t.find('git fetch --quiet --depth=1 origin main', i)
    check(0 < i < k < j,
          'la guarda trae el tablero de main ANTES de medir su edad')
    check('git pull --rebase -X theirs origin main' in t,
          'la subida resuelve el choque a favor de lo recién barrido')
    check('for _i in 1 2 3' in t and 'git rebase --abort' in t,
          'y reintenta tres veces limpiando el rebase fallido')


if __name__ == '__main__':
    print('=== 1. el archivo y la unión ===')
    probar_el_archivo_y_la_union()
    print('\n=== 2. el código ===')
    probar_el_codigo()
    print('\n=== 3. el workflow de cuotas ===')
    probar_el_workflow()
    print('\n' + '=' * 40)
    print('TODO OK' if not FALLOS else '%d FALLOS' % len(FALLOS))
    raise SystemExit(1 if FALLOS else 0)
