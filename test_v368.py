#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test de la v368.

El usuario (11-oct), con Gaziantep–Corum terminado: «no sale lo de tiros y
dice "sin el método todavía" cuando ya debería tenerlo; dime tanto global como
por equipo qué acertó y qué no» y «si pongo el filtro de la estrella sigue sin
filtrármelo».

Lo que se vigila:
  1. EL PARTIDO EMPEZADO usa el método APUNTADO antes del pitido (las cinco
     estadísticas), no el cálculo de respaldo.
  2. CADA EQUIPO con su línea y su resultado (✅/❌), y el resumen por equipo.
  3. EL SEGUIMIENTO guarda lo de cada equipo y rellena lo ya liquidado.
  4. EL FILTRO «Sólo ⭐ ELIGE».

Ejecutar:  python test_v368.py
"""
import json
import os
import shutil
import tempfile

FALLOS = []


def check(cond, msg):
    print(('OK   ' if cond else 'FALLO') + ' ' + msg)
    if not cond:
        FALLOS.append(msg)


FILA = {'local': 4.84, 'visita': 4.43, 'total': 9.27, 'linea': 6.5, 'p': 0.80,
        'real': 9.0, 'cumple': 1.0, 'real_l': 2.0, 'real_v': 7.0}


def probar_archivado():
    import analisis_seguimiento as an
    import modo_modelo as mm
    x = mm.de_lo_archivado('a_puerta', dict(FILA))
    check(x['metodo'] and x['linea_l'] == 2.5 and x['cumple_l'] == 0 and x['cumple_v'] == 1,
          'lo apuntado, con la línea de cada equipo y su resultado (local 2 ❌, visita 7 ✅): %s'
          % {k: x[k] for k in ('linea_l', 'cumple_l', 'linea_v', 'cumple_v')})
    v1, v2 = mm.metodo_contexto, an.del_partido
    mm.metodo_contexto = lambda p, *a, **k: {
        'goles': {'local': 1.5, 'visita': 1.3, 'total': 2.8, 'linea': 1.5, 'p': 0.77,
                  'metodo': False}}
    an.del_partido = lambda p, *a, **k: {
        'goles': {'local': 1.47, 'visita': 1.37, 'total': 2.83, 'linea': 1.5, 'p': 0.77,
                  'real': 3.0, 'cumple': 1.0, 'real_l': 0.0, 'real_v': 3.0},
        'tiros': {'local': 14.8, 'visita': 13.1, 'total': 27.9, 'linea': 23.5, 'p': 0.73,
                  'real': 25.0, 'cumple': 1.0, 'real_l': 12.0, 'real_v': 13.0}}
    try:
        h = mm._tabla_metodo_html({'partido': 'Gaziantep vs Corum', 'jugado': True,
                                   'goles_home': 0, 'goles_away': 3})
    finally:
        mm.metodo_contexto, an.del_partido = v1, v2
    check('Tiros' in h and 'sin el método todavía' not in h,
          'el partido terminado enseña el método apuntado, con tiros y sin «*»')
    check('✅ 25' in h and '❌ 0' in h and '✅ 3' in h,
          'con el resultado del total y el de cada equipo')


def probar_seguimiento():
    import analisis_seguimiento as an
    import modo_modelo as mm
    tmp = tempfile.mkdtemp()
    cwd = os.getcwd()
    try:
        ruta = os.path.join(tmp, 's.csv')
        viejo = mm.metodo_contexto
        mm.metodo_contexto = lambda p, *a, **k: {
            'corners': {'local': 5, 'visita': 4, 'total': 9, 'linea': 7.5, 'p': 0.72,
                        'metodo': True, 'linea_l': 2.5, 'p_l': 0.8, 'linea_v': 1.5, 'p_v': 0.82}}
        try:
            an.registrar([{'partido': 'A vs B', 'deporte': 'Fútbol', 'clave_liga': 'mls',
                           'inicio': '2099-01-01T12:00:00Z', 'fecha': '2099-01-01'}],
                         ruta=ruta, ahora=0)
        finally:
            mm.metodo_contexto = viejo
        d = an._leer(ruta)
        check(float(d.linea_l.iloc[0]) == 2.5 and float(d.linea_v.iloc[0]) == 1.5,
              'apunta la línea de cada equipo')
        # una fila vieja, ya liquidada, sin lo de cada equipo
        d.loc[0, 'real'] = 9.0
        d.loc[0, 'cumple'] = 1
        d.to_csv(ruta, index=False)
        os.chdir(tmp)
        json.dump({'dia': d.dia.iloc[0], 'partidos': [{
            'partido': 'A vs B', 'goles_home': 1, 'goles_away': 1,
            'stats_partido': {'corners_home': 8, 'corners_away': 1}}]},
            open('jugados_dia.json', 'w', encoding='utf-8'))
        an.liquidar(ruta)
        d = an._leer(ruta)
        check(float(d.real_l.iloc[0]) == 8 and float(d.real_v.iloc[0]) == 1,
              'rellena lo de cada equipo en lo ya liquidado')
        rs = an.resumen(ruta, dias=3650, hoy='2100-01-01')
        check(rs['corners']['eq_n'] == 2 and rs['corners']['eq_verdes'] == 1,
              'y el resumen por equipo (8 > 2,5 ✅, 1 < 1,5 ❌): %s' % rs['corners'])
    finally:
        os.chdir(cwd)
        shutil.rmtree(tmp, ignore_errors=True)
    src = open('modo_modelo.py', encoding='utf-8').read()
    check('👥 Por equipo' in src, 'la tabla dice cómo va el método por equipo')


def probar_filtro():
    src = open('modo_modelo.py', encoding='utf-8').read()
    check("st.checkbox('Sólo ⭐ ELIGE'" in src and "con = [p for p in con if _k_elige(p)[1] == 0]" in src,
          'el filtro «Sólo ⭐ ELIGE» deja sólo los partidos con ⭐')
    check("elif _antes_de_filtrar and 'elige' in _quito:" in src,
          'y si ya no queda ninguna, lo dice')
    r = json.load(open('_v368_aprendiz.json', encoding='utf-8'))
    check('p_lgb' in r['calibracion'] and r['no_supervisado'],
          'la medición del aprendiz (supervisado y no supervisado) queda guardada')


if __name__ == '__main__':
    print('=== 1. el método apuntado ===')
    probar_archivado()
    print('\n=== 2-3. el seguimiento por equipo ===')
    probar_seguimiento()
    print('\n=== 4. el filtro ⭐ ===')
    probar_filtro()
    print('\n' + '=' * 40)
    print('TODO OK' if not FALLOS else '%d FALLOS' % len(FALLOS))
    raise SystemExit(1 if FALLOS else 0)
