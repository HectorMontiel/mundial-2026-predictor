#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test de los goles por equipo, la doble oportunidad con goles y la razón
corta de cada apuesta (v303).

El usuario: «hay juegos donde es mejor la doble oportunidad y meter over u
under por lo parejos que serán», «podemos irnos al under de goles individual
por equipo», y «en la tarjeta debes decir brevemente por qué... algo corto».

Lo que se vigila:

  · EL LECTOR DEL TABLERO saca «<Equipo> total de goles» y «Doble
    oportunidad y total N de goles», con el lado correcto aunque la casa
    nombre primero al visitante.
  · LA CONJUNTA NO CONTRADICE A LA TARJETA: la matriz con la que se calcula
    «Japón o empate y menos de 2.5» reproduce el 1X2 y el «más de 2.5» que
    la misma tarjeta enseña.
  · LAS CANDIDATAS EXISTEN y van marcadas `sin_medir`: no tienen histórico
    propio y la tarjeta tiene que decirlo.
  · LA RAZÓN ES CORTA (dos datos como mucho) y nunca cita córners de un
    histórico sintético.

Ejecutar:  python test_mercados_equipo.py
"""
FALLOS = []


def check(cond, msg):
    print(('OK   ' if cond else 'FALLO') + ' ' + msg)
    if not cond:
        FALLOS.append(msg)


def _tablero():
    return {'casa_home': 'Japón', 'casa_away': 'Uruguay', 'mercados': [
        {'nombre': 'Japón total de goles', 'selecciones': [
            {'nombre': 'Más de 0.5', 'cuota': 1.25},
            {'nombre': 'Menos de 0.5', 'cuota': 3.6},
            {'nombre': 'Más de 1.5', 'cuota': 2.2},
            {'nombre': 'Menos de 1.5', 'cuota': 1.6}]},
        {'nombre': 'Uruguay total de goles', 'selecciones': [
            {'nombre': 'Más de 0.5', 'cuota': 1.556},
            {'nombre': 'Menos de 0.5', 'cuota': 2.286}]},
        {'nombre': '1ª mitad - Japón total de goles', 'selecciones': [
            {'nombre': 'Más de 0.5', 'cuota': 1.9},
            {'nombre': 'Menos de 0.5', 'cuota': 1.8}]},
        {'nombre': 'Doble oportunidad y total 2.5 de goles', 'selecciones': [
            {'nombre': 'Japón/empate y más de 2.5', 'cuota': 2.714},
            {'nombre': 'Japón/empate y menos de 2.5', 'cuota': 1.889},
            {'nombre': 'Empate/Uruguay y más de 2.5', 'cuota': 5.0},
            {'nombre': 'Empate/Uruguay y menos de 2.5', 'cuota': 2.4},
            {'nombre': 'Japón/Uruguay y más de 2.5', 'cuota': 2.286},
            {'nombre': 'Japón/Uruguay y menos de 2.5', 'cuota': 2.333}]},
    ]}


def probar_el_lector():
    import mercado_implicito as mi
    d = mi.del_tablero(_tablero())
    gh, ga = d.get('goles_home') or {}, d.get('goles_away') or {}
    check('0.5' in gh and '1.5' in gh, 'lee los goles del local (%s)' % gh)
    check(abs(gh['0.5']['mas'] - 1.25) < 1e-9 and gh['0.5']['menos'] == 3.6,
          'con sus dos cuotas')
    check('0.5' in ga and '1.5' not in ga, 'y los del visitante, sólo lo que hay')
    check(gh['0.5']['p'] > 0.7, 'la implícita va sin margen (%.3f)'
          % gh['0.5']['p'])
    dc = (d.get('dc_goles') or {}).get('2.5') or {}
    check(dc.get('1X_menos') == 1.889 and dc.get('X2_mas') == 5.0
          and dc.get('12_menos') == 2.333,
          'lee la doble oportunidad con goles con su lado (%s)' % dc)
    check(len(dc) == 6, 'las seis salidas')
    # la media parte es otro partido
    check(all(abs(v['mas'] - 1.9) > 1e-9 for v in gh.values()),
          'la primera mitad no se cuela como goles del partido')


def _pick():
    return {'deporte': 'Fútbol', 'clave_liga': 'selecciones',
            'partido': 'Japan vs Uruguay',
            'board': {'Gana Japan': 0.49, 'Empate': 0.27,
                      'Gana Uruguay': 0.24},
            'mercados': [{'mercado': '1X2', 'apuesta': 'Gana Japan',
                          'prob': 0.49}],
            'goles_lineas': {'0.5': 0.91, '1.5': 0.68, '2.5': 0.45,
                             '3.5': 0.24, '4.5': 0.10, '5.5': 0.035,
                             '6.5': 0.01},
            'goles_equipo': {'local': {'0.5': 0.77, '1.5': 0.42,
                                       '2.5': 0.16},
                             'visitante': {'0.5': 0.58, '1.5': 0.22}},
            'goles_xg': {'local': 1.45, 'visitante': 0.85}}


def probar_la_conjunta():
    import valor_apuesta as va
    import modo_modelo as mm
    p = _pick()
    M = va._conjunta_dc_goles(p)
    check(M is not None, 'hay matriz conjunta')
    if not M:
        return
    n = len(M)
    tri = mm.probabilidades_1x2(p)
    loc = sum(M[i][j] for i in range(n) for j in range(n) if i > j)
    emp = sum(M[i][j] for i in range(n) for j in range(n) if i == j)
    mas25 = sum(M[i][j] for i in range(n) for j in range(n) if i + j > 2.5)
    check(abs(loc - tri[0]) < 0.01 and abs(emp - tri[1]) < 0.01,
          'respeta el 1X2 de la tarjeta (%.3f/%.3f contra %.3f/%.3f)'
          % (loc, emp, tri[0], tri[1]))
    check(abs(mas25 - 0.45) < 0.01,
          'y el más de 2,5 de la tarjeta (%.3f contra 0,45)' % mas25)


def probar_las_candidatas():
    import mercado_implicito as mi
    import valor_apuesta as va
    p = _pick()
    p['implicitas'] = mi.del_tablero(_tablero())
    ge = va._de_goles_equipo(p)
    check(any(f['apuesta'] == 'Goles Japan: Más de 0.5' for f in ge),
          'propone «Japan marca» con su cuota')
    check(all(f.get('sin_medir') for f in ge),
          'y la marca como mercado sin medición propia')
    dc = va._de_dc_goles(p)
    txt = [f['apuesta'] for f in dc]
    check('Japan o empate y menos de 2.5' in txt,
          'propone la doble oportunidad con goles (%s)' % txt[:3])
    f = [x for x in dc if x['apuesta'] == 'Japan o empate y menos de 2.5']
    check(f and abs(f[0]['cuota'] - 1.889) < 1e-9 and 0 < f[0]['prob'] < 1,
          'con el precio de la casa y una probabilidad válida')
    check(all(x.get('sin_medir') for x in dc), 'también marcada sin medir')
    todas = va.candidatos(p, {})
    mks = {x['mercado'] for x in todas}
    check({'Goles equipo', 'Doble y goles'} <= mks,
          'y las dos entran en las candidatas de la tarjeta (%s)' % sorted(mks))


def probar_la_razon():
    import razon_apuesta as ra
    import pandas as pd
    h = pd.read_csv('historico_premier.csv', low_memory=False).dropna(
        subset=['home_goals']).iloc[-1]
    p = {'clave_liga': 'premier', 'goles_lambda': 2.7,
         'partido': '%s vs %s' % (h['home_team'], h['away_team'])}
    r = ra.razon(p, {'mercado': 'Goles', 'apuesta': 'Goles: Más de 2.5'})
    check(bool(r), 'da una razón para un partido de la Premier («%s»)' % r)
    check(r.count(' · ') <= 1 and len(r) <= 170,
          'corta: dos datos como mucho (%d caracteres)' % len(r))
    check('mete' in r and 'recibe' in r, 'y con la media de goles de los dos')
    pf = ra.perfil('premier', h['home_team'])
    check(pf and pf['casa']['n'] <= 10 and pf['fuera']['n'] <= 10,
          'el perfil mira los últimos 10 en casa y fuera')
    # un histórico con córners sintéticos no puede citarlos
    check(ra.razon({'clave_liga': 'no_existe', 'partido': 'A vs B'},
                   {'mercado': 'Córners'}) == '',
          'sin histórico no inventa nada')
    src = open('razon_apuesta.py', encoding='utf-8').read()
    check("stats_origen" in src and "stats_disponibles" in src,
          'sólo cita córners y tarjetas observados')


def probar_la_cache_del_tablero():
    """Lo guardado es lo que se lee después en el mismo proceso: si no, cada
    precálculo salía con los precios de la pasada anterior."""
    import os
    import tempfile
    import mercado_implicito as mi
    ruta_orig = mi.FICHERO
    d = tempfile.mkdtemp()
    mi.FICHERO = os.path.join(d, 'mercado_dia.json')
    try:
        mi.guardar({'partidos': {'a|b': {'goles': {}}}}, mi.FICHERO)
        mi.cargar(mi.FICHERO, recargar=True)
        mi._MEM.clear()
        mi.del_partido('a', 'b')
        mi.guardar({'partidos': {'a|b': {'goles': {},
                                         'dc_goles': {'2.5': {}}}}},
                   mi.FICHERO)
        check('dc_goles' in mi.del_partido('a', 'b'),
              'tras guardar, el mismo proceso lee el tablero NUEVO')
    finally:
        mi.FICHERO = ruta_orig
        mi._DISCO = None
        mi._MEM.clear()


def probar_la_tarjeta():
    src = open('modo_modelo.py', encoding='utf-8').read()
    check("razon_apuesta" in src and 'mm-rec-rz' in src,
          'la tarjeta enseña la razón dentro de la apuesta')
    check("('Goles equipo'" in src and "('Doble y goles'" in src,
          'y los dos mercados nuevos tienen su fila')


if __name__ == '__main__':
    print('=== 1. el lector del tablero ===')
    probar_el_lector()
    print('\n=== 2. la conjunta ===')
    probar_la_conjunta()
    print('\n=== 3. las candidatas ===')
    probar_las_candidatas()
    print('\n=== 4. la razón ===')
    probar_la_razon()
    print('\n=== 5. la caché del tablero ===')
    probar_la_cache_del_tablero()
    print('\n=== 6. la tarjeta ===')
    probar_la_tarjeta()
    print('\n' + '=' * 40)
    print('TODO OK' if not FALLOS else '%d FALLOS' % len(FALLOS))
    raise SystemExit(1 if FALLOS else 0)
