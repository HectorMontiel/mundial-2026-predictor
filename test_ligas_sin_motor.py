#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test de las fuentes nuevas y de las ligas sin motor (v303).

«En este proyecto no estará permitido no tener datos.» Lo que se vigila:

  · SELECCIONES CON DATOS REALES: `historico_selecciones.csv` existe, trae
    boxscore de ESPN marcado con `stats_origen`, y la tarjeta de un
    internacional saca los córners de ahí (`observado`), no del histórico
    sintético.
  · LIGA MX FEMENIL Y CHAMPIONS FEMENINA desde FotMob, con miles de partidos
    y los nombres sin la marca «(W)».
  · EL MOTOR DE GOLES se juzga POR MERCADO y sólo publica lo que le ganó a
    la línea base fuera de muestra.
  · LA CHAMPIONS SE MIDE CON LAS LIGAS DE APOYO: sin ellas las fuerzas se
    quedan en la media y manda la localía (Chelsea salía al 49 % contra el
    Austria de Viena).
  · EL PRECIO SE BUSCA CON LA CATEGORÍA DE LA LIGA: sin ella, Pachuca-Santos
    femenil tomaba el precio del varonil.
  · CON PRECIO, LO PUBLICADO SE ENCOGE AL MERCADO (w=0,25), como el fútbol
    de clubes: sin eso un error del modelo sale como EV +95 %.
  · EL BARRIDO TIENE LA RAMA y los workflows refrescan y re-validan.

Ejecutar:  python test_ligas_sin_motor.py
"""
import os

FALLOS = []


def check(cond, msg):
    print(('OK   ' if cond else 'FALLO') + ' ' + msg)
    if not cond:
        FALLOS.append(msg)


def probar_selecciones_reales():
    import pandas as pd
    check(os.path.exists('historico_selecciones.csv'),
          'existe el histórico real de selecciones')
    if not os.path.exists('historico_selecciones.csv'):
        return
    d = pd.read_csv('historico_selecciones.csv', low_memory=False)
    obs = (d['stats_origen'] == 'espn').sum()
    check(len(d) > 2000 and obs > 1000,
          'con miles de partidos y más de mil boxscores reales (%d / %d)'
          % (obs, len(d)))
    sin = d[d['stats_origen'] != 'espn']
    check(sin['home_corners'].isna().all(),
          'un partido sin boxscore NO trae córners inventados')
    import modo_modelo as mm
    p = {'deporte': 'Fútbol', 'clave_liga': 'selecciones',
         'partido': 'Netherlands vs Germany'}
    ck = mm.corners_tarjeta(p)
    check(ck is not None and ck.get('origen') == 'observado',
          'la tarjeta de un internacional saca córners observados (%s)'
          % (ck or {}).get('origen'))


def probar_fotmob():
    import pandas as pd
    import historico_fotmob as hf
    for clave, minimo in (('mex_femenil', 1000), ('champions_femenil', 500),
                          ('fem_inglaterra', 400), ('fem_espana', 800)):
        r = 'historico_%s.csv' % clave
        n = len(pd.read_csv(r)) if os.path.exists(r) else 0
        check(n >= minimo, '%s con histórico (%d partidos)' % (clave, n))
    check(hf._limpia('Chelsea (W)') == 'Chelsea'
          and hf._limpia('Austria Wien W') == 'Austria Wien'
          and hf._limpia('Pachuca') == 'Pachuca',
          'los nombres pierden la marca femenina, para ser el mismo equipo '
          'en todas sus ligas')
    check(set(hf.APOYO.get('champions_femenil', [])) >=
          {'fem_inglaterra', 'fem_espana', 'fem_alemania', 'fem_francia'},
          'la Champions femenina se apoya en las ligas grandes')


def probar_el_motor():
    import motor_goles as mg
    import json
    doc = json.load(open(mg.FICHERO, encoding='utf-8'))
    ligas = doc.get('ligas') or {}
    fem = ligas.get('mex_femenil') or {}
    check(fem.get('ok_1x2') and fem.get('ll_1x2_motor') < fem.get('ll_1x2_base'),
          'la Femenil: el motor le gana a la base en el 1X2 (%s < %s)'
          % (fem.get('ll_1x2_motor'), fem.get('ll_1x2_base')))
    for c, v in ligas.items():
        check(v.get('ok_goles') == (v.get('mejora_o25_p5', -1) > 0),
              '%s: goles publicados sólo si ganaron con p5 > 0' % c)
        check(v.get('ok_1x2') == (v.get('mejora_1x2_p5', -1) > 0),
              '%s: 1X2 publicado sólo si ganó con p5 > 0' % c)
    # con apoyo, Chelsea es favorita clara ante un equipo de fuera del pool
    m = mg.ajustar(mg.historico_con_apoyo('champions_femenil'),
                   __import__('pandas').Timestamp('2026-09-22'))
    lam = mg.lambdas(m, 'Barcelona', 'Paris FC')
    pr = mg.probabilidades(*lam) if lam else {}
    check(pr and pr['home'] > 0.75,
          'con las ligas de apoyo, Barcelona es favorita clara ante Paris FC '
          '(%.2f)' % (pr or {}).get('home', 0))


def probar_cada_cruce_tiene_sus_goles():
    """v306 — el 2026-09-23 Servette-Lyon y Leuven-Roma salieron con la MISMA
    escalera de goles (la media de la liga) y la tarjeta recomendó «Menos de
    6.5» en un 0-8. Dos cruces distintos no pueden tener los mismos goles, y
    los goles por equipo tienen que estar."""
    import ligas_sin_motor as l
    import motor_goles as mg
    m = mg.modelo('champions_femenil')
    if not m:
        check(False, 'sin modelo de la Champions femenina')
        return
    a = l._pronostico('champions_femenil', 'x', {
        'home': 'Servette', 'away': 'OL Lyonnes',
        'inicio': '2026-09-23 16:45:00', 'fecha': '2026-09-23'}, m)
    b = l._pronostico('champions_femenil', 'x', {
        'home': 'Oud-Heverlee Leuven', 'away': 'Roma',
        'inicio': '2026-09-23 16:45:00', 'fecha': '2026-09-23'}, m)
    check(a and b and a['goles_lineas'] != b['goles_lineas'],
          'dos cruces distintos, dos escaleras de goles distintas')
    check(a and a['goles_lineas']['4.5'] > b['goles_lineas']['4.5'],
          'y el desigual (Lyon) espera más goles (%.2f > %.2f)'
          % (a['goles_lineas']['4.5'], b['goles_lineas']['4.5']))
    check(bool((a or {}).get('goles_equipo')),
          'los goles por equipo están, para poder proponer «Lyon más de 2,5»')


def probar_la_rama():
    import ligas_sin_motor as l
    check(abs(l.MODELO_W - 0.25) < 1e-9,
          'encoge al mercado con el mismo w=0,25 del fútbol de clubes')
    check(all('women' in ' '.join(v) or 'mexico' in v[0]
              for k, v in l.LIGA_TABLERO.items()),
          'toda liga femenina se busca en el tablero con su categoría')
    # un precio de un partido de otra fecha no vale
    import barrido_capa1 as bc
    orig = bc._tablero
    base = 1790000000
    bc._tablero = lambda ruta=None: [
        {'deporte': 'futbol', 'liga': 'MEXICO: Liga MX Women', 'home': 'Tigres W',
         'away': 'Atlas W', 'inicio': str(base + 10 * 86400),
         'casas': {'1xBet': {'HOME_DRAW_AWAY': {'home': 1.2, 'draw': 6.0,
                                                'away': 11.0}}}},
        {'deporte': 'futbol', 'liga': 'MEXICO: Liga MX', 'home': 'Tigres',
         'away': 'Atlas', 'inicio': str(base),
         'casas': {'1xBet': {'HOME_DRAW_AWAY': {'home': 2.0, 'draw': 3.4,
                                                'away': 3.6}}}}]
    try:
        import datetime as dt
        ini = dt.datetime.fromtimestamp(base, dt.timezone.utc).strftime(
            '%Y-%m-%d %H:%M:%S')
        imp = l.implicitas_del_tablero('mex_femenil', 'Tigres', 'Atlas', ini)
        check(imp == {}, 'no toma el varonil ni un femenil de otra fecha (%s)'
              % imp.get('1x2_cuotas'))
        ini2 = dt.datetime.fromtimestamp(base + 10 * 86400,
                                         dt.timezone.utc).strftime(
            '%Y-%m-%d %H:%M:%S')
        imp = l.implicitas_del_tablero('mex_femenil', 'Tigres', 'Atlas', ini2)
        check((imp.get('1x2_cuotas') or {}).get('home') == 1.2,
              'y sí el femenil de su fecha')
    finally:
        bc._tablero = orig
    src = open('alpha_finder.py', encoding='utf-8').read()
    check("'sin_motor': _picks_sin_motor" in src,
          'el barrido del día tiene la rama')
    wf = open('.github/workflows/precalculo_dia.yml', encoding='utf-8').read()
    check('historico_selecciones.py' in wf and 'historico_fotmob.py' in wf,
          'el precálculo refresca los históricos nuevos')
    wr = open('.github/workflows/recalibrar.yml', encoding='utf-8').read()
    check('motor_goles.py' in wr and 'champions_femenil' in wr,
          'y la recalibración semanal re-valida el motor')


if __name__ == '__main__':
    print('=== 1. selecciones con datos reales ===')
    probar_selecciones_reales()
    print('\n=== 2. FotMob ===')
    probar_fotmob()
    print('\n=== 3. el motor de goles ===')
    probar_el_motor()
    print('\n=== 4. cada cruce tiene sus goles ===')
    probar_cada_cruce_tiene_sus_goles()
    print('\n=== 5. la rama ===')
    probar_la_rama()
    print('\n' + '=' * 40)
    print('TODO OK' if not FALLOS else '%d FALLOS' % len(FALLOS))
    raise SystemExit(1 if FALLOS else 0)
