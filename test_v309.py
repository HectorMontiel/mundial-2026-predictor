#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test de la v309: todos los finalizados del día con su apuesta, y un solo
nombre por competición.

El usuario: «en los partidos finalizados no me despliegas todos los que
finalizaron ya y con su apuesta que tú recomendaste», y «hay ligas que me das
en inglés y otras en español, y son lo mismo pero traen diferentes partidos».

Lo que se vigila:

  1. EL DICCIONARIO DE LIGAS junta los nombres reales vistos en el tablero
     (amistosos ×3, Nations League con y sin división, eliminatoria africana,
     LaLiga2, Colombia), separa las tres «Primera División», no cruza deportes
     y es idempotente.
  2. EL ARCHIVO: con pasadas cada 1,6 h, un partido que empieza entre dos
     pasadas SE ARCHIVA (antes nunca: exigía 2,5 h de juego), lleva la
     apuesta recomendada de antes del inicio y no se recalcula si ya estaba.
  3. LA FUSIÓN: la copia de ESPN (con marcador) y la archivada (con apuesta)
     acaban en UNA tarjeta con las dos cosas.
  4. FOTMOB: el marcador se casa por hora de inicio y nombres, y no casa un
     partido de otra hora.
  5. LA LIQUIDACIÓN de los mercados que se quedaban ⏳: goles de un equipo,
     doble con goles y hándicap asiático (con la devolución ⚪).
  6. LA VISTA: nombre canónico, «en juego» sin marcador, y el código que lo
     pinta.

Ejecutar:  python test_v309.py
"""
import datetime as dt
import json
import os
import tempfile
import time

FALLOS = []


def check(cond, msg):
    print(('OK   ' if cond else 'FALLO') + ' ' + msg)
    if not cond:
        FALLOS.append(msg)


# ---------------------------------------------------------------------------
def probar_el_diccionario():
    import nombres_ligas as nl
    c = nl.canonica
    amistosos = {c('International - Friendlies', 'selecciones', 'Fútbol'),
                 c('Partidos Amistosos Internacionales', 'selecciones',
                   'Fútbol'),
                 c('WORLD: Friendly International', 'world: friendly '
                   'international', 'Fútbol')}
    check(amistosos == {'Amistosos internacionales'},
          'los tres nombres de los amistosos son uno (%s)' % amistosos)
    uefa = {c(x, 'selecciones', 'Fútbol') for x in (
        'UEFA - Nations League A', 'UEFA - Nations League D',
        'International — UEFA Nations League',
        'EUROPE: UEFA Nations League - League B')}
    check(uefa == {'Liga de Naciones UEFA'},
          'la Nations League UEFA, con o sin división, es una (%s)' % uefa)
    conc = {c(x, 'selecciones', 'Fútbol') for x in (
        'CONCACAF - Nations League A', 'CONCACAF — Nations League',
        'International — CONCACAF Nations League',
        'NORTH & CENTRAL AMERICA: CONCACAF Nations League - League C')}
    check(conc == {'Liga de Naciones CONCACAF'},
          'y la de CONCACAF también (%s)' % conc)
    caf = {c('CAF - Africa Cup of Nations Qualifiers', 'selecciones',
             'Fútbol'),
           c('AFRICA: Africa Cup of Nations - Qualification', '', 'Fútbol')}
    check(caf == {'Eliminatorias Copa Africana'},
          'la eliminatoria africana es una (%s)' % caf)
    check(c('SPAIN: LaLiga2', 'spain: laliga2', 'Fútbol')
          == c('LaLiga Hypermotion', 'esp_hypermotion', 'Fútbol')
          == 'LaLiga Hypermotion',
          '«SPAIN: LaLiga2» del tablero es LaLiga Hypermotion')
    check(c('COLOMBIA: Primera A - Clausura', '', 'Fútbol')
          == 'Categoría Primera A',
          'y «COLOMBIA: Primera A - Clausura» es la Primera A')
    prim = {c('Primera División', k, 'Fútbol')
            for k in ('argentina', 'uru_primera', 'slv_primera')}
    check(len(prim) == 3 and all('(' in x for x in prim),
          'las tres «Primera División» quedan separadas por país (%s)' % prim)
    check(c('TURKEY: Super Lig', '', 'Baloncesto') != 'Süper Lig',
          'el baloncesto turco NO se convierte en la Süper Lig de fútbol')
    check(c('JAPAN: B.League One', '', 'Baloncesto') == 'Japón: B.League One',
          'el país del tablero se escribe en español')
    ten = {c(x, '', 'Tenis') for x in (
        'ATP Challenger Genoa - Qualifiers', 'Challenger — Genoa',
        'CHALLENGER MEN - SINGLES: Genova 2 (Italy) - Qualification, clay')}
    check(ten == {'Challenger — Genoa'},
          'tenis: el mismo Challenger escrito de tres maneras es uno (%s)'
          % ten)
    check(c('CHALLENGER WOMEN - SINGLES: Porto (Portugal) - Qualification, '
            'hard', '', 'Tenis') == c('WTA 125K Porto - Qualifiers', '',
                                      'Tenis') == 'WTA 125 — Porto',
          'el «Challenger femenino» de Flashscore es el WTA 125')
    # idempotencia sobre todo lo anterior
    muestras = list(amistosos | uefa | conc | caf | prim | ten) + [
        'LaLiga Hypermotion', 'Japón: B.League One', 'WTA 125 — Porto',
        'Chile: LNB']
    malos = [x for x in muestras
             if c(x, '', 'Tenis' if '—' in x else 'Fútbol') != x]
    check(not malos, 'es idempotente (%s)' % malos)
    check(c('CHILE: LNB - Clausura - Winners', '', 'Baloncesto')
          == 'Chile: LNB', 'las fases encadenadas se quitan todas')
    # aplicar: no toca clave_liga y guarda el original
    datos = {'pronosticos': [{'partido': 'A vs B', 'deporte': 'Fútbol',
                              'clave_liga': 'selecciones',
                              'liga': 'International - Friendlies'}],
             'capa1': [{'apuesta': 'x', 'liga': 'Partidos Amistosos '
                        'Internacionales', 'clave_liga': 'selecciones'}]}
    nl.aplicar(datos)
    p = datos['pronosticos'][0]
    check(p['liga'] == 'Amistosos internacionales'
          and p['clave_liga'] == 'selecciones'
          and p['liga_origen'] == 'International - Friendlies',
          'aplicar cambia el nombre, NO la clave, y guarda el original')
    check(datos['capa1'][0]['liga'] == 'Amistosos internacionales',
          'y llega a las listas anidadas (Capa 1)')
    nl.aplicar(datos)
    check(p['liga_origen'] == 'International - Friendlies',
          'aplicarlo dos veces no pisa el original')


# ---------------------------------------------------------------------------
def _ini(ts):
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime(
        '%Y-%m-%d %H:%M:%S')


def _pron(partido, inicio_ts, clave='selecciones', liga='UEFA - Nations '
          'League A'):
    i = _ini(inicio_ts)
    return {'deporte': 'Fútbol', 'partido': partido, 'clave_liga': clave,
            'liga': liga, 'inicio': i, 'fecha': i[:10], 'prob': 0.6,
            'board': {'Gana X': 0.6}}


def probar_el_archivo():
    import partidos_jugados as pj
    import dia_picks as dp
    d = tempfile.mkdtemp()
    llamadas = []
    orig = pj._recomendadas_previas
    pj._recomendadas_previas = lambda p: (
        llamadas.append(p['partido']) or
        [{'mercado': 'Goles', 'bloque': 'goles', 'etiqueta': 'Total',
          'apuesta': 'Goles: Más de 1.5', 'linea': 1.5, 'prob': 0.7,
          'origen': 'archivo'}])
    try:
        # la aritmética que perdía las selecciones: pasadas cada 1,6 h y un
        # partido que empieza 20 min después de la pasada T0
        T0 = time.time() - 3 * 3600
        ini = T0 + 20 * 60
        p = _pron('Italy vs Belgium', ini)
        rp = os.path.join(d, 'pron_T0.json')
        with open(rp, 'w', encoding='utf-8') as f:
            json.dump({'generado_ts': T0, 'datos': {'pronosticos': [p]}}, f)
        T1 = T0 + 1.6 * 3600          # en T1 lleva 1 h 16 min de juego
        arch = pj.archivar_del_pronostico(dp.dia_de(p), rp, ahora=T1)
        check([q['partido'] for q in arch] == ['Italy vs Belgium'],
              'un partido con 1 h 16 min de juego se archiva en la pasada '
              'siguiente (antes: nunca)')
        q = arch[0] if arch else {}
        check(bool(q.get('recomendadas_previas'))
              and q['recomendadas_previas'][0]['apuesta']
              == 'Goles: Más de 1.5',
              'con la apuesta que se recomendaba antes del inicio')
        check(q.get('pronostico_ts') == T0 and q.get('pronostico_ts') < ini,
              'y se sabe que ese pronóstico era de ANTES del inicio')
        # si ya estaba archivado con su apuesta, no se recalcula
        llamadas.clear()
        pj.archivar_del_pronostico(dp.dia_de(p), rp, ahora=T1,
                                   ya={pj._llave(q)})
        check(llamadas == [], 'lo ya archivado no vuelve a calcularse')
    finally:
        pj._recomendadas_previas = orig


def probar_la_fusion():
    import partidos_jugados as pj
    ini = '2026-09-25 18:45:00'
    archivado = {'partido': 'Inverness Caledonian Thistle vs Morton',
                 'clave_liga': 'sco_championship', 'inicio': ini,
                 'jugado': True, 'archivado_del_pronostico': True,
                 'recomendadas_previas': [{'apuesta': 'Gana Inverness',
                                           'bloque': 'resultado'}]}
    tardio = dict(archivado, recomendadas_previas=[{'apuesta': 'OTRA'}])
    espn = {'partido': 'Inverness C vs Morton',
            'clave_liga': 'sco_championship', 'inicio': ini,
            'jugado': True, 'goles_home': 2, 'goles_away': 0,
            '_home_crudo': 'Inverness C', '_away_crudo': 'Morton'}
    u = pj.unir([archivado], [tardio], [espn])
    check(len(u) == 1, 'la copia de ESPN y la archivada son UN partido '
                       '(%d)' % len(u))
    x = u[0] if u else {}
    check(x.get('goles_home') == 2 and x.get('recomendadas_previas')
          and x['recomendadas_previas'][0]['apuesta'] == 'Gana Inverness',
          'con el marcador de ESPN y la PRIMERA apuesta archivada')
    check(x.get('_home_crudo') == 'Inverness C',
          'y con el nombre crudo de ESPN, la llave del precálculo')
    otro = dict(espn, partido='Ayr vs Stenhousemuir', _home_crudo='Ayr')
    check(len(pj.unir([archivado], [otro])) == 2,
          'dos partidos distintos a la misma hora no se funden')


def probar_fotmob():
    import partidos_jugados as pj
    import horario as hz
    lista = [{'ini': hz._a_utc('2026-09-25 18:45:00'), 'home': 'Italy',
              'away': 'Belgium', 'gh': 0.0, 'ga': 2.0, 'id': 1},
             {'ini': hz._a_utc('2026-09-25 16:00:00'), 'home': 'Georgia',
              'away': 'Northern Ireland', 'gh': 0.0, 'ga': 1.0, 'id': 2},
             {'ini': hz._a_utc('2026-09-26 01:00:00'), 'home': 'Chivas (W)',
              'away': 'Cruz Azul (W)', 'gh': 1.0, 'ga': 1.0, 'id': 3}]
    p = {'partido': 'Italy vs Belgium', 'inicio': '2026-09-25 18:45:00'}
    f = pj._casar_fotmob(p, lista)
    check(bool(f) and f['id'] == 1, 'casa por hora y nombres')
    p2 = {'partido': 'Italy vs Belgium', 'inicio': '2026-09-25 21:00:00'}
    check(pj._casar_fotmob(p2, lista) is None,
          'no casa el mismo par a otra hora')
    p3 = {'partido': 'Chivas vs Cruz Azul', 'inicio': '2026-09-26 01:00:00'}
    f3 = pj._casar_fotmob(p3, lista)
    check(bool(f3) and f3['id'] == 3, 'quita la marca femenina «(W)»')
    partidos = [dict(p, jugado=True), {'partido': 'Georgia vs Northern '
                'Ireland', 'inicio': '2026-09-25 16:00:00', 'jugado': True,
                'clave_liga': 'selecciones'}]
    orig = pj._marcador
    pj._marcador = lambda q: None
    try:
        n = pj.poner_marcadores(partidos, '2026-09-25',
                                ahora=hz._a_utc('2026-09-26 03:00:00')
                                .timestamp(), fotmob=lista)
    finally:
        pj._marcador = orig
    check(n == 2 and partidos[0]['goles_away'] == 2.0
          and partidos[0]['marcador_fuente'] == 'fotmob',
          'poner_marcadores rellena desde FotMob (%d)' % n)


# ---------------------------------------------------------------------------
def probar_la_liquidacion():
    import pronosticos_guardados as pg

    def liq(ap, bloque, etiqueta, gh, ga, linea=None, h='Senegal',
            a='Mozambique'):
        f = {'apuesta': ap, 'bloque': bloque, 'etiqueta': etiqueta,
             'linea': linea}
        real = pg._valor_real(f, gh, ga, None)
        return pg._acierto(f, real, h, a)

    check(liq('Goles Senegal: Más de 1.5', 'goles_equipo', 'Local', 2, 0,
              1.5)[0] is True, 'goles de un equipo (local): gana')
    check(liq('Goles Mozambique: Más de 0.5', 'goles_equipo', 'Visitante', 2,
              0, 0.5)[0] is False, 'goles de un equipo (visitante): pierde')
    check(liq('Senegal o empate y más de 1.5', 'dc_goles', '1X', 1, 1,
              1.5)[0] is True, 'doble con goles: 1-1 con 1X y más de 1.5')
    check(liq('Senegal o empate y más de 1.5', 'dc_goles', '1X', 0, 0,
              1.5)[0] is False, 'doble con goles: 0-0 no llega a la línea')
    check(liq('Senegal o Mozambique y menos de 4.5', 'dc_goles', '12', 1, 1,
              4.5)[0] is False, 'doble con goles: el empate tumba el 12')
    check(liq('Handicap: Mozambique +0.5', 'handicap', 'Total', 1, 1,
              0.5)[0] is True, 'hándicap +0.5 con empate: gana')
    check(liq('Handicap: Senegal -1.5', 'handicap', 'Total', 2, 1,
              -1.5)[0] is False, 'hándicap -1.5 ganando por uno: pierde')
    check(liq('Handicap: Senegal -1', 'handicap', 'Total', 2, 1,
              -1.0) == (None, 0.0), 'hándicap -1 ganando por uno: nula')
    check(liq('Handicap: Senegal -0.75', 'handicap', 'Total', 2, 1,
              -0.75)[0] is True, 'hándicap -0.75 ganando por uno: media '
                                 'ganada, se cobra')
    check(liq('Handicap: Mozambique +0.25', 'handicap', 'Total', 1, 0,
              0.25)[0] is False, 'hándicap +0.25 perdiendo por uno: pierde')
    # validar: la apuesta archivada y la estadística de FotMob del partido
    pick = {'partido': 'Italy vs Belgium', 'clave_liga': 'selecciones',
            'fecha': '2026-09-25', 'jugado': True, 'goles_home': 0,
            'goles_away': 2,
            'recomendadas_previas': [
                {'apuesta': 'Goles: Más de 1.5', 'bloque': 'goles',
                 'etiqueta': 'Total', 'linea': 1.5, 'prob': 0.7,
                 'origen': 'archivo'},
                {'apuesta': 'Córners: Menos de 12', 'bloque': 'corners',
                 'etiqueta': 'Total', 'linea': 12, 'prob': 0.6,
                 'origen': 'archivo'},
                {'apuesta': 'Handicap: Belgium -2', 'bloque': 'handicap',
                 'etiqueta': 'Total', 'linea': -2, 'prob': 0.5,
                 'origen': 'archivo'}],
            'stats_partido': {'corners_home': 4.0, 'corners_away': 8.0}}
    orig = pg.de_partido
    pg.de_partido = lambda *a, **k: None
    try:
        filas = pg.validar(pick)
    finally:
        pg.de_partido = orig
    est = [f['estado'] for f in filas]
    check(est == [pg.CUMPLIDO, pg.FALLADO, pg.NULA],
          'validar liquida la apuesta archivada: goles 🟢, córners con la '
          'ficha de FotMob 🔴 (12), hándicap justo en la línea ⚪ (%s)' % est)


# ---------------------------------------------------------------------------
def probar_la_vista():
    import partidos_jugados as pj
    ahora = time.time()
    ps = [{'partido': 'A vs B', 'liga': 'International - Friendlies',
           'clave_liga': 'selecciones', 'deporte': 'Fútbol',
           'inicio': _ini(ahora - 1800), 'jugado': True},
          {'partido': 'C vs D', 'liga': 'SPAIN: LaLiga2',
           'clave_liga': 'esp_hypermotion', 'deporte': 'Fútbol',
           'inicio': _ini(ahora - 3 * 3600), 'jugado': True,
           'goles_home': 1, 'goles_away': 0}]
    v = pj._para_la_vista(ps, ahora=ahora)
    check(v[0]['liga'] == 'Amistosos internacionales'
          and v[1]['liga'] == 'LaLiga Hypermotion',
          'los finalizados llevan el nombre canónico (casan con el filtro)')
    check(v[0].get('en_juego') and not v[1].get('en_juego'),
          'sin marcador y con menos de 2,5 h: «en juego»; con marcador, no')
    check('en_juego' not in ps[0] and ps[0]['liga'] ==
          'International - Friendlies', 'y no muta la lista del fichero')

    src = open('dashboard_ui.py', encoding='utf-8').read()
    i = src.find('def barrido_universal')
    check(i > 0 and 'nombres_ligas.aplicar(r)' in src[i:i + 1600],
          'el barrido de la aplicación pasa por el diccionario de ligas')
    check('return _con_nombres_de_liga(_bc1.barrer())' in src
          and 'return _con_nombres_de_liga(_pb.barrer(_pronosticos))' in src,
          'y la Capa 1 y las probables del tablero en vivo también')
    j = src.find('def _capa1_en_vivo')
    check(src[j - 60:j].strip().endswith(
          '@st.cache_data(ttl=600, show_spinner=False)'),
          'la Capa 1 en vivo conserva su caché de diez minutos')
    mm = open('modo_modelo.py', encoding='utf-8').read()
    check("elif pick.get('en_juego'):" in mm and '⏱️ En juego' in mm,
          'la tarjeta dice «En juego» en vez de inventar un final')
    check("isinstance(real, (tuple, list))" in mm,
          'y pinta el marcador de la doble con goles y el hándicap')
    check("'archivo': 'lo que se recomendó antes del inicio'" in mm,
          'y rotula de dónde sale la apuesta')
    pjs = open('partidos_jugados.py', encoding='utf-8').read()
    check('ini.timestamp() > ahora' in pjs
          and 'HORAS_PARTIDO * 3600 > ahora:\n            continue' not in pjs,
          'el archivo ya no espera 2,5 h')
    check("unir(previos, archivados, de_red)" in pjs,
          'lo ya archivado va antes: gana la apuesta de antes del inicio')


if __name__ == '__main__':
    print('=== 1. el diccionario de ligas ===')
    probar_el_diccionario()
    print('\n=== 2. el archivo ===')
    probar_el_archivo()
    print('\n=== 3. la fusión ===')
    probar_la_fusion()
    print('\n=== 4. FotMob ===')
    probar_fotmob()
    print('\n=== 5. la liquidación ===')
    probar_la_liquidacion()
    print('\n=== 6. la vista ===')
    probar_la_vista()
    print('\n' + '=' * 40)
    print('TODO OK' if not FALLOS else '%d FALLOS' % len(FALLOS))
    raise SystemExit(1 if FALLOS else 0)
