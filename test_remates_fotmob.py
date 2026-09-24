#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test de las ligas de FotMob y de los remates por jugador (v307).

El usuario: «¿por qué sólo las ligas identificadas y no las 60?» y «quiero
los remates a puerta y remates por jugador de ligas principales y
selecciones». Lo que se vigila:

  · TODAS LAS LIGAS DEL PROYECTO tienen id de FotMob, verificado por sus
    equipos (no por el nombre: «Super League» son cuatro ligas).
  · Las bajas y los remates leen de esa lista, no de las diez de antes.
  · LA EXTRACCIÓN: playerStats > shotmap > totales del equipo. De un
    amistoso (sólo totales) sale el equipo y NINGÚN jugador con ceros.
  · La media del jugador es la POR TITULARIDAD del modelo calibrado.
  · «Quién remata» cae a FotMob cuando ESPN no tiene al equipo, y el nivel
    de remates del equipo usa lo observado en FotMob antes que lo estimado.

Ejecutar:  python test_remates_fotmob.py
"""
import os
import shutil
import tempfile

FALLOS = []


def check(cond, msg):
    print(('OK   ' if cond else 'FALLO') + ' ' + msg)
    if not cond:
        FALLOS.append(msg)


def _ficha(player_stats=True, shotmap=True, stats=True):
    """Una ficha de partido de FotMob de mentira, con la forma real."""
    jugadores = {
        'home': [(1, 'Ana Delantera', 3, True, 90, 4, 2, 1, 0.8),
                 (2, 'Bea Media', 2, True, 70, 1, 0, 0, 0.1),
                 (3, 'Cris Defensa', 1, True, 90, 0, 0, 0, 0.0),
                 (4, 'Dora Suplente', 3, False, 20, 1, 1, 0, 0.2)],
        'away': [(11, 'Eva Punta', 3, True, 90, 2, 1, 0, 0.3),
                 (12, 'Fer Central', 1, True, 90, 0, 0, 0, 0.0)]}
    lineup, pst, shots = {}, {}, []
    for lado, tid, nombre in (('home', 100, 'Local FC'),
                              ('away', 200, 'Visita FC')):
        starters, subs = [], []
        for jid, n, pos, tit, mins, t, on, g, xg in jugadores[lado]:
            j = {'id': jid, 'name': n, 'usualPlayingPositionId': pos,
                 'performance': {'substitutionEvents':
                                 ([] if tit else
                                  [{'type': 'subIn', 'time': 90 - mins}])}}
            (starters if tit else subs).append(j)
            pst[str(jid)] = {'id': jid, 'teamId': tid, 'stats': [
                {'title': 'Top stats', 'stats': {
                    'Minutes played': {'key': 'minutes_played',
                                       'stat': {'value': mins}},
                    'Goals': {'key': 'goals', 'stat': {'value': g}},
                    'Expected goals (xG)': {'key': 'expected_goals',
                                            'stat': {'value': xg}},
                    'Total shots': {'key': 'total_shots',
                                    'stat': {'value': t}},
                    'Shots on target': {'key': 'ShotsOnTarget',
                                        'stat': {'value': on}}}}]}
            for i in range(t):
                shots.append({'playerId': jid, 'teamId': tid,
                              'isOnTarget': i < on,
                              'eventType': 'Goal' if i < g else 'Miss',
                              'expectedGoals': xg / max(1, t)})
        lineup[lado + 'Team'] = {'id': tid, 'name': nombre,
                                 'starters': starters, 'subs': subs}
    cont = {'lineup': lineup}
    if player_stats:
        cont['playerStats'] = pst
    if shotmap:
        cont['shotmap'] = {'shots': shots}
    if stats:
        cont['stats'] = {'Periods': {'All': {'stats': [
            {'title': 'Top stats', 'stats': [
                {'key': 'total_shots', 'stats': [6, 2]},
                {'key': 'ShotsOnTarget', 'stats': [3, 1]},
                {'key': 'expected_goals', 'stats': ['1.10', '0.30']},
                {'key': 'corners', 'stats': [5, 2]}]}]}}}
    return {'props': {'pageProps': {
        'general': {'matchTimeUTCDate': '2026-09-20T18:00:00Z',
                    'homeTeam': {'id': 100, 'name': 'Local FC'},
                    'awayTeam': {'id': 200, 'name': 'Visita FC'}},
        'header': {'status': {'scoreStr': '1 - 0'}},
        'content': cont}}}


def test_ligas():
    import fotmob_ligas as fl
    from config import LEAGUES
    no_futbol = {'mlb', 'nba', 'nfl', 'kbo', 'itf_vivo', 'tenis_espn'}
    futbol = [k for k in LEAGUES if k not in no_futbol
              and os.path.exists('historico_%s.csv' % k)]
    faltan = [k for k in futbol if k not in fl.CONOCIDOS]
    check(not faltan, 'todas las %d ligas de fútbol tienen id conocido '
          '(faltan: %s)' % (len(futbol), faltan))
    doc = fl.cargar()
    ok = doc.get('ligas') or {}
    check(len([k for k in futbol if k in ok]) == len(futbol)
          and not doc.get('sin_resolver'),
          'fotmob_ligas.json las tiene todas verificadas (%d/%d, sin '
          'resolver %s)' % (len([k for k in futbol if k in ok]), len(futbol),
                            list(doc.get('sin_resolver') or {})))
    ids = fl.ids()
    check(ids.get('noruega', (0,))[0] == 59 and ids.get('conference_league',
                                                          (0,))[0] == 10216,
          'ids() da Noruega 59 y la Conference 10216 (no la «Champions '
          'League Qualification» que proponía el buscador)')
    # la verificación, sin red
    orig = (fl.equipos_fotmob, fl.nombre_fotmob, fl.equipos_propios,
            fl.solape, fl.candidatas)
    try:
        fl.equipos_propios = lambda c: ['A', 'B']
        fl.nombre_fotmob = lambda lid: 'Eliteserien'
        fl.equipos_fotmob = lambda lid: ['x'] * 10
        fl.candidatas = lambda t: {}
        fl.solape = lambda a, b: 0.9
        r = fl.resolver('noruega', 'Eliteserien')
        check(r.get('id') == 59 and r.get('origen') == 'conocido',
              'el id conocido se acepta cuando sus equipos casan')
        fl.solape = lambda a, b: 0.1
        r = fl.resolver('noruega', 'Eliteserien')
        check(bool(r.get('error')),
              'y se rechaza cuando no casan (10 %), aunque el nombre sí')
        fl.nombre_fotmob = lambda lid: 'Conference League'
        fl.solape = lambda a, b: 0.22
        r = fl.resolver('conference_league', 'UEFA Conference League')
        check(r.get('id') == 10216,
              'una copa continental se acepta con su nombre y un 22 % de '
              'equipos (cambian de participantes cada año)')
    finally:
        (fl.equipos_fotmob, fl.nombre_fotmob, fl.equipos_propios,
         fl.solape, fl.candidatas) = orig
    import bajas_fotmob as bf
    bl = bf.ligas()
    check(all(k in bl for k in futbol) and 'selecciones' in bl,
          'las bajas cubren las %d ligas y las selecciones (%d '
          'competiciones)' % (len(futbol), len(bl)))


def test_extraer():
    import remates_fotmob as rf
    fj, fe = rf.extraer_de(_ficha(), '1', 'mex_femenil')
    por = {f['jugador']: f for f in fj}
    check(len(fj) == 6, 'salen los 6 que jugaron, también los que no '
          'dispararon (%d)' % len(fj))
    check(por['Ana Delantera']['tiros'] == 4
          and por['Ana Delantera']['a_puerta'] == 2
          and por['Ana Delantera']['posicion'] == 'F',
          'remates, a puerta y posición del jugador desde playerStats')
    check(por['Dora Suplente']['titular'] == 0
          and por['Dora Suplente']['minutos'] == 20,
          'la suplente sale como suplente y con sus minutos')
    e = {x['equipo']: x for x in fe}
    check(e['Local FC']['tiros'] == 6 and e['Local FC']['a_puerta'] == 3
          and e['Local FC']['corners'] == 5 and e['Local FC']['goles'] == 1
          and e['Visita FC']['tiros'] == 2,
          'los totales del equipo salen de las estadísticas del partido')
    # sin playerStats: el mapa de disparos
    fj2, _ = rf.extraer_de(_ficha(player_stats=False), '1', 'x')
    por2 = {f['jugador']: f for f in fj2}
    check(por2['Ana Delantera']['tiros'] == 4
          and por2['Ana Delantera']['a_puerta'] == 2
          and por2['Cris Defensa']['tiros'] == 0,
          'sin playerStats, del mapa de disparos (y el que no tiró, a cero)')
    # un amistoso: sólo totales
    fj3, fe3 = rf.extraer_de(_ficha(player_stats=False, shotmap=False),
                             '1', 'selecciones')
    check(fj3 == [] and len(fe3) == 2 and all(x['por_jugador'] == 0
                                              for x in fe3),
          'de un amistoso (sólo totales) sale el equipo y NINGÚN jugador '
          'con ceros')
    fj4, fe4 = rf.extraer_de(_ficha(False, False, False), '1', 'x')
    check(fj4 == [] and fe4 == [], 'sin nada, nada')
    check(rf.extraer_de({}, '1', 'x') == ([], []), 'una ficha vacía no lanza')
    f = _ficha()
    pp = f['props']['pageProps']
    pp['general']['homeTeam']['name'] = 'USA'
    pp['content']['lineup']['homeTeam']['name'] = 'USA'
    fj5, fe5 = rf.extraer_de(f, '1', 'selecciones')
    check({x['equipo'] for x in fe5} == {'United States', 'Visita FC'}
          and all(x['equipo'] != 'USA' for x in fj5),
          'en selecciones, «USA» de FotMob se guarda como «United States», '
          'el nombre de nuestro histórico')
    import fotmob_scraper as fm
    orig = fm._next_data
    try:
        fm._next_data = lambda url: None
        check(rf.extraer('1', 'x') is None,
              'si FotMob no responde es None, no «vacío»: no se apunta para '
              'siempre por un corte de red')
        fm._next_data = lambda url: _ficha(False, False, False)
        check(rf.extraer('1', 'x') == ([], []),
              'y una ficha que responde sin datos sí es vacía')
    finally:
        fm._next_data = orig


def test_lectura():
    import remates_fotmob as rf
    import remates_jugador as rjg
    tmp = tempfile.mkdtemp()
    orig = (rf.JUGADORES, rf.EQUIPOS)
    try:
        rf.JUGADORES = os.path.join(tmp, 'j.csv')
        rf.EQUIPOS = os.path.join(tmp, 'e.csv')
        rf.olvidar()
        for i in range(5):
            f = _ficha()
            f['props']['pageProps']['general']['matchTimeUTCDate'] = \
                '2026-09-%02dT18:00:00Z' % (10 + i)
            fj, fe = rf.extraer_de(f, str(i), 'mex_femenil')
            rf._anexar(rf.JUGADORES, fj, rf.COL_J)
            rf._anexar(rf.EQUIPOS, fe, rf.COL_E)
        rf.olvidar()
        filas = {f['jugador']: f for f in rf.filas_equipo('mex_femenil',
                                                          'Local FC')}
        a = filas.get('Ana Delantera') or {}
        esperada = rjg.media_por_titularidad(20, 5, 5, 'tot')
        check(abs((a.get('media_tot') or 0) - esperada) < 1e-9
              and a.get('apariciones') == 5,
              'la media es la por titularidad del modelo (%.2f)' % esperada)
        d = filas.get('Dora Suplente') or {}
        check(d.get('titularidades') == 0 and (d.get('media_tot') or 0)
              > 1.0, 'la suplente: su media como titular se despeja (%.2f '
              'con 1 remate en 20 min)' % (d.get('media_tot') or 0))
        lam = rf.lambdas_partido('mex_femenil', 'Local FC', 'Visita FC')
        check(lam and lam['totales']['lambda_home'] == 6.0
              and lam['totales']['lambda_away'] == 2.0
              and lam['a_puerta']['lambda_home'] == 3.0,
              'λ del partido = (lo que tira + lo que concede el rival) / 2')
        # la tarjeta cae a FotMob cuando ESPN no tiene al equipo
        o = (rjg._de_roster, rjg._de_partidos)
        rjg._de_roster = lambda *a, **k: []
        try:
            js = rjg.jugadores_equipo('mex_femenil', 'Local FC',
                                      lambda_tot=6.0, lambda_on=3.0)
        finally:
            rjg._de_roster, rjg._de_partidos = o
        check(bool(js) and js[0]['jugador'] == 'Ana Delantera'
              and js[0]['origen'] == 'últimos partidos (FotMob)'
              and js[0].get('p_al_arco') is not None,
              '«quién remata» sale de FotMob sin roster de ESPN, con remates '
              'y a puerta')
        # poda
        quitadas = rf.podar(rf.JUGADORES, conservar=2)
        rf.olvidar()
        import pandas as pd
        dj = pd.read_csv(rf.JUGADORES)
        check(quitadas > 0 and dj.groupby('equipo')['match_id'].nunique()
              .max() == 2, 'la poda deja los últimos N partidos por equipo')
    finally:
        rf.JUGADORES, rf.EQUIPOS = orig
        rf.olvidar()
        shutil.rmtree(tmp, ignore_errors=True)


def test_flashscore():
    import remates_flashscore as rfs
    texto = ('SE÷Match¬~SF÷Top stats¬~SD÷34¬SG÷Total shots'
             '¬SH÷14¬SI÷30¬~SD÷13¬SG÷Shots on target¬'
             'SH÷4¬SI÷8¬~SE÷1st Half¬~SD÷34¬SG÷'
             'Total shots¬SH÷6¬SI÷9¬~')

    class R:
        status_code = 200
        text = texto

        def raise_for_status(self):
            pass
    orig = rfs.requests.get
    rfs.requests.get = lambda *a, **k: R()
    try:
        st = rfs.estadisticas('x')
    finally:
        rfs.requests.get = orig
    check(st.get('Total shots') == (14.0, 30.0)
          and st.get('Shots on target') == (4.0, 8.0),
          'Flashscore: se leen los remates del partido ENTERO, no los de '
          'la primera parte (14-30, no 6-9)')
    check(rfs._nombre('Club Leon W', ['Club León', 'Tigres']) == 'Club León',
          'y «Club Leon W» se traduce a nuestro «Club León»')
    wf = open('.github/workflows/precalculo_dia.yml', encoding='utf-8').read()
    check('remates_flashscore.py' in wf,
          'el precálculo refresca los remates de la Liga MX Femenil')


def test_enchufes():
    src = open('rendimiento_equipos.py', encoding='utf-8').read()
    check('remates_fotmob.lambdas_partido' in src,
          'el nivel de remates del equipo mira FotMob antes de estimar')
    src = open('remates_jugador.py', encoding='utf-8').read()
    check('remates_fotmob.filas_equipo' in src
          and 'remates_fotmob.lambdas_partido' in src,
          '«quién remata» usa los jugadores y el nivel de FotMob')
    import remates_fotmob as rf
    ids = {x[0] for x in rf.SELECCIONES}
    check({9806, 9807, 10195, 10199, 77, 50, 114} <= ids,
          'las selecciones incluyen Nations League, eliminatorias, '
          'Mundial, Eurocopa y amistosos')
    wf = open('.github/workflows/precalculo_dia.yml', encoding='utf-8').read()
    check('remates_fotmob.py' in wf and 'remates_fotmob_equipos.csv' in wf,
          'el precálculo captura los remates y los guarda')
    check('fotmob_ligas.py' in open('.github/workflows/recalibrar.yml',
                                    encoding='utf-8').read(),
          'la recalibración semanal re-verifica los ids de las ligas')


if __name__ == '__main__':
    test_ligas()
    test_extraer()
    test_lectura()
    test_flashscore()
    test_enchufes()
    print('\n' + '=' * 40)
    print('TODO OK' if not FALLOS else '%d FALLOS' % len(FALLOS))
    raise SystemExit(1 if FALLOS else 0)
