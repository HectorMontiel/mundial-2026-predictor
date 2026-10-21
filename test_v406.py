#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test de la v406-v408.

  v406 — «mañana y pasado mañana salían vacíos»: sin decisiones válidas del
         precálculo, la exportación las calcula; y una pasada incompleta no
         borra lo publicado.
  v407 — la IA en TODOS los partidos (todos los deportes, 72 h) con un template
         común: ganador, marcador, total y hándicap con su probabilidad.
  v408 — ganadores de NBA (casa ≥ 72 %), NFL (≥ 70 %) y béisbol (≥ 68 %).

Ejecutar:  python test_v406.py
"""
import datetime as dt
import os

FALLOS = []


def check(cond, msg):
    print(('OK   ' if cond else 'FALLO') + ' ' + msg)
    if not cond:
        FALLOS.append(msg)


def probar_exportar():
    import exportar_web as xw
    import decisiones_dia as dd
    llamados = []
    viejo = dd.decidir
    dd.decidir = lambda p: llamados.append(p['partido']) or {'recomendadas_tarjeta': []}
    try:
        datos = {'pronosticos': [{'partido': 'A vs B', 'inicio': '2030-01-01 10:00:00'},
                                 {'partido': 'C vs D', 'inicio': '2030-01-01 10:00:00', dd.CLAVE_PICK: {'x': 1}},
                                 {'partido': 'E vs F', 'jugado': True}]}
        n = xw.decidir_lo_que_falta(datos)
    finally:
        dd.decidir = viejo
    check(n == 1 and llamados == ['A vs B'] and dd.CLAVE_PICK in datos['pronosticos'][0],
          'sólo se decide lo que no trae decisión (y no lo jugado)')
    src = open('exportar_web.py', encoding='utf-8').read()
    check('decidir_lo_que_falta(doc.get' in src and 'not _pasada_incompleta(url, key, picks)' in src,
          'la exportación decide lo que falta y no borra con una pasada incompleta')


def probar_ia():
    import ia_gemini as ia
    ahora = dt.datetime(2026, 10, 20, 12, tzinfo=dt.timezone.utc)
    def pk(dep, h, partido):
        return {'deporte': dep, 'estado': 'pendiente', 'partido': partido, 'fecha': '2026-10-20', 'apuesta': 'Gana X',
                'inicio': (ahora + dt.timedelta(hours=h)).strftime('%Y-%m-%d %H:%M:%S')}
    ms = ia.partidos([pk('NHL', 5, 'A vs B'), pk('Fútbol', 50, 'C vs D'), pk('Tenis', 70, 'E vs F'), pk('NBA', 80, 'G vs H')], ahora)
    check({m['partido'] for m in ms} == {'A vs B', 'C vs D', 'E vs F'} and all(m.get('deporte') for m in ms),
          'la IA analiza todos los deportes de las próximas 72 h (hoy, mañana y pasado)')
    check('p_empate = 0' in ia.instruccion('NBA') and 'Puntos: Más de N.5' in ia.instruccion('NBA')
          and 'Ambos anotan' in ia.instruccion('NHL') and 'Sets' in ia.instruccion('Tenis'),
          'cada deporte con su unidad (goles, puntos, carreras, sets) y sin empate')
    req = set(ia.ESQUEMA_GEN['required'])
    check({'total_esperado', 'linea_total', 'pred_total', 'prob_total', 'linea_handicap', 'pred_handicap',
           'prob_handicap', 'marcador_probable', 'mejor_apuesta', 'veredictos'} <= req
          and {'total_esperado', 'prob_total', 'prob_handicap'} <= set(ia.ESQUEMA['required']),
          'el mismo template (total y hándicap con probabilidad) en el fútbol y en los demás')
    check(ia.liquidar('Handicap: Pumas +1.5', 'América', 'Pumas', (2, 1)) is True
          and ia.liquidar('Puntos: Más de 210.5', 'A', 'B', (110, 105)) is True
          and ia.liquidar('Sets: Menos de 2.5', 'A', 'B', (2, 1)) is False,
          'lo que metería la IA se califica también en hándicap, puntos y sets')
    check(ia._linea_h(-1.2) == -1.5 and ia._linea_h(0) == 0.5 and ia._linea_h(3) == 3.5, 'el hándicap siempre en .5')
    sql = open(os.path.join('supabase', 'v407_ia_template.sql'), encoding='utf-8').read()
    check('add column if not exists prob_total' in sql and "'handicap', prob_handicap" in sql,
          'las columnas y la calibración del total y el hándicap')
    app = open(os.path.join('web', 'app.js'), encoding='utf-8').read()
    check("'📊 Total de ' + U" in app and "'⚖️ Hándicap'" in app, 'la página enseña el template en todos los deportes')


def probar_ganadores():
    import veredicto_pick as vp
    check(vp.METER_GANADOR_CASA_MIN['NBA'] == 0.72 and vp.METER_GANADOR_CASA_MIN['NFL'] == 0.70
          and vp.METER_GANADOR_CASA_MIN['MLB'] == 0.68 and vp.METER_GANADOR_CUOTA_MAX == 1.50,
          'umbrales del ganador: NBA 72 %, NFL 70 %, MLB/KBO 68 %, cuota hasta 1,50')


def probar_escudos():
    import espn_vivo as ev
    ev._ESCUDOS['mex.1'] = {'santos': 'https://a.espncdn.com/i/teamlogos/soccer/500/225.png'}
    santos = {'displayName': 'Santos', 'logo': 'https://a.espncdn.com/i/teamlogos/soccer/500/133985.png'}
    check(ev._escudo('mex.w.1', santos).endswith('/225.png'),
          'el Santos de la Femenil lleva el escudo del Santos Laguna, no el del Santos de Brasil')
    check(ev._escudo('mex.w.1', {'displayName': 'Club Nuevo', 'logo': 'x.png'}) == 'x.png'
          and ev._escudo('bra.1', santos).endswith('/133985.png'),
          'si el nombre no coincide, o la liga no es femenil, se deja el de ESPN')


def probar_sesion():
    js = open(os.path.join('web', 'cuenta.js'), encoding='utf-8').read()
    check('if (sb) yo.user = sesionGuardada();' in js and "'-auth-token'" in js,
          'v412: la sesión guardada en el dispositivo se lee al instante')
    check('if (!yo.user && listo) await aTiempo(listo' in js and 'listo = refrescar();' in js,
          'v412: «Mi cuenta» no pide entrar hasta que termina de cargar la sesión (el regreso de Stripe)')
    check(js.count('try { pintarCabecera(); }') >= 2 and "addEventListener('visibilitychange'" in js,
          'v412: la cabecera no enseña «Entrar» mientras carga, y se pone al día al volver a la app')
    fn = open(os.path.join('supabase', 'functions', 'stripe', 'index.ts'), encoding='utf-8').read()
    check('payment_method_types:' not in fn, 'v411: Stripe sin payment_method_types (la API nueva lo rechaza)')


if __name__ == '__main__':
    probar_sesion()
    probar_escudos()
    probar_exportar()
    probar_ia()
    probar_ganadores()
    print('\n' + '=' * 40)
    print('TODO OK' if not FALLOS else '%d FALLOS' % len(FALLOS))
    raise SystemExit(1 if FALLOS else 0)
