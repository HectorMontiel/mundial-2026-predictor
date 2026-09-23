#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test de las selecciones en Apuestas del Día (v302).

El usuario: «ya pronto se juega la UEFA Nations League y varios partidos de
equipos internacionales, pero no lo veo reflejado en las apuestas del día».

Lo que se vigila:

  · EL BARRIDO TIENE LA RAMA. Sin ella no hay forma de que aparezcan: ése era
    el fallo, no un filtro.
  · LA LOCALÍA SE RESPETA. El motor nació para el Mundial y por defecto
    promedia las dos ópticas como si la sede fuera neutral; un Países
    Bajos-Alemania en Ámsterdam no es neutral. Con `en_casa=True` el local
    tiene que salir MÁS favorito que en sede neutral.
  · SÓLO ABSOLUTAS MASCULINAS: el motor no sabe nada de un sub-20 ni de una
    selección femenina.
  · EL PRONÓSTICO TIENE LA FORMA DE LOS DE CLUBES: la tarjeta, el filtro de
    día y la Escalera lo tratan igual sin casos especiales.
  · NO LANZA sin calendario.

Ejecutar:  python test_selecciones.py
"""
FALLOS = []


def check(cond, msg):
    print(('OK   ' if cond else 'FALLO') + ' ' + msg)
    if not cond:
        FALLOS.append(msg)


def probar_la_rama():
    src = open('alpha_finder.py', encoding='utf-8').read()
    check("'selecciones'" in src and 'selecciones_dia' in src,
          'el barrido del día tiene la rama de selecciones')
    i = src.find("for nombre in ('mlb', 'tenis'")
    check(i > 0 and "'selecciones'" in src[i:i + 120],
          'y suma sus evaluados y sus no enlazados como las demás')


def probar_la_localia():
    from prediction_api import PredictionEngine
    m = PredictionEngine()
    if not m.listo:
        check(False, 'el motor de selecciones no carga: %s' % m.error)
        return
    neu = m.predecir('NED', 'GER')['prediction']['probabilities']
    casa = m.predecir('NED', 'GER', en_casa=True)
    pc = casa['prediction']['probabilities']
    check(casa['localia']['metodo'] == 'anfitrion_local',
          'con en_casa el motor usa la óptica directa (%s)'
          % casa['localia']['metodo'])
    check(pc['home'] > neu['home'],
          'y el local sale más favorito que en sede neutral (%.3f > %.3f)'
          % (pc['home'], neu['home']))
    visto = m.predecir('GER', 'NED', en_casa=True)['prediction']['probabilities']
    check(visto['home'] > neu['away'],
          'la ventaja es del que juega en casa, sea quien sea (%.3f > %.3f)'
          % (visto['home'], neu['away']))


def probar_absolutas():
    import selecciones_dia as sd
    check(sd._es_absoluta({'home': 'Netherlands', 'away': 'Germany',
                           'torneo': 'UEFA Nations League'}),
          'la Nations League entra')
    check(not sd._es_absoluta({'home': 'Fiji (W)', 'away': 'Solomon Islands (W)',
                               'torneo': 'International — National Friendlies - Women'}),
          'un amistoso femenino no')
    check(not sd._es_absoluta({'home': 'Iran U23', 'away': 'North Korea U23',
                               'torneo': 'International — Asian Games U23'}),
          'un sub-23 no')
    check(not sd._es_absoluta({'home': 'Fiyi (F)', 'away': 'Islas Salomón',
                               'torneo': 'Amistosos Internac, Fem.'}),
          'ni el femenino con el nombre en español')


def probar_la_forma():
    import selecciones_dia as sd
    m = sd._motor()
    if m is None:
        check(False, 'sin motor no se puede probar la forma')
        return
    f = {'home': 'Netherlands', 'away': 'Germany',
         'torneo': 'UEFA Nations League', 'fecha': '2026-09-24',
         'inicio': '2026-09-24T18:45Z'}
    p = sd.pronostico(m, f, 'NED', 'GER')
    check(p is not None, 'produce un pronóstico')
    if not p:
        return
    for k in ('deporte', 'liga', 'partido', 'inicio', 'fecha', 'mercado',
              'apuesta', 'prob', 'board', 'goles_lineas', 'mercados'):
        check(k in p, 'lleva «%s», como los de clubes' % k)
    check(p['deporte'] == 'Fútbol' and p['liga'] == 'UEFA Nations League',
          'es fútbol y dice su torneo')
    check(p['partido'] == 'Netherlands vs Germany',
          'con los nombres de la fuente, que son los que casan con las casas')
    b = p['board']
    s = sum(v for k, v in b.items() if k.startswith(('Gana', 'Empate')))
    check(abs(s - 1) < 0.01, 'el 1X2 suma uno (%.3f)' % s)
    gl = p['goles_lineas']
    check(gl['0.5'] >= gl['1.5'] >= gl['2.5'] >= gl['3.5'],
          'las líneas de goles van ordenadas')
    check(p['inicio'].startswith('2026-09-24 18:45'),
          'la hora en UTC, como el resto (%s)' % p['inicio'])
    check(p.get('localia') == 'anfitrion_local', 'y con la localía puesta')
    import dia_picks as dp
    check(dp.dia_de(p) == '2026-09-24', 'el filtro de día lo reconoce')


def probar_no_lanza():
    import fixtures_espn as fe
    import selecciones_dia as sd
    orig = fe.fixtures_selecciones
    fe.fixtures_selecciones = lambda **kw: (_ for _ in ()).throw(OSError('x'))
    try:
        r = sd.barrer()
        check(r['pronosticos'] == [] and r['incidencias'],
              'sin calendario no lanza y lo dice como incidencia')
    except Exception as e:
        check(False, 'lanzó: %s' % e)
    finally:
        fe.fixtures_selecciones = orig


if __name__ == '__main__':
    print('=== 1. la rama existe ===')
    probar_la_rama()
    print('\n=== 2. la localía ===')
    probar_la_localia()
    print('\n=== 3. sólo absolutas ===')
    probar_absolutas()
    print('\n=== 4. la forma del pronóstico ===')
    probar_la_forma()
    print('\n=== 5. no lanza ===')
    probar_no_lanza()
    print('\n' + '=' * 40)
    print('TODO OK' if not FALLOS else '%d FALLOS' % len(FALLOS))
    raise SystemExit(1 if FALLOS else 0)
