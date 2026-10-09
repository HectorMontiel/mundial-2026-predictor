#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test de la v352.

El usuario, con Kashiwa–Vissel delante (cinco apuestas 📌 a lo largo del
día, ninguna al pitido, rojas que el semáforo no contaba): «cambian mucho, es
ruido; quiero saber cuál es la segura» y «un filtro por el reloj: lo que hay
que apostar a las seis, porque a esa hora ya está definido».

Lo que se vigila:
  1. LA MEDICIÓN: fijar la apuesta al abrir la hora de apostar acierta igual
     o más que la del pitido y quita el ruido de lo anunciado.
  2. EL CICLO: provisional → fijada (y ya no cambia) → lo archivado y lo que
     cuenta el semáforo es la fijada. El tenis no se toca.
  3. LA PANTALLA: título FIJADA/PROVISIONAL, provisionales plegadas, el texto
     de la fila entero y el filtro por reloj.

Ejecutar:  python test_v352.py
"""
import datetime as dt
import json
import os
import tempfile

FALLOS = []
UTC = dt.timezone.utc


def check(cond, msg):
    print(('OK   ' if cond else 'FALLO') + ' ' + msg)
    if not cond:
        FALLOS.append(msg)


def probar_medicion():
    m = json.load(open('_v352_fijar.json', encoding='utf-8'))
    t = {r['version']: r for r in m['Fútbol']['tabla']}
    a, b2, d = t['A_pitido'], t['B2_al_abrir'], t['D_todo']
    check(b2['acierto'] >= a['acierto'] and m['Fútbol']['B2_menos_A'][1] > 0,
          'fútbol: fijada al abrir %.1f %% contra pitido %.1f %% (p5 %+.1f pts)'
          % (100 * b2['acierto'], 100 * a['acierto'], 100 * m['Fútbol']['B2_menos_A'][1]))
    check(b2['rojas'] < a['rojas'] < d['rojas'] and b2['por_partido'] < d['por_partido'],
          'menos rojas (%d contra %d) y menos apuestas por partido que todo lo anunciado '
          '(%.2f contra %.2f)' % (b2['rojas'], a['rojas'], b2['por_partido'], d['por_partido']))


R1 = {'apuesta': 'Goles: Más de 1.5', 'mercado': 'Goles', 'bloque': 'goles', 'linea': 1.5,
      'cuota': 1.2, 'prob': 0.8, 'prob_meter': 0.8, 'veredicto_vp': 'meter'}
R2 = {'apuesta': 'A o empate', 'mercado': 'Doble oportunidad', 'bloque': 'resultado',
      'cuota': 1.18, 'prob': 0.82, 'prob_meter': 0.82, 'veredicto_vp': 'meter'}
INI = '2026-10-10 18:00:00'          # la ventana se abre a las 14:00 UTC


def _doc(met):
    return {'datos': {'pronosticos': [{'partido': 'A vs B', 'clave_liga': 'x',
                                       'deporte': 'Fútbol', 'inicio': INI}]},
            'decisiones': {'listas': {'pronosticos': [
                {'llave': ['A vs B', INI, 'x'], 'recomendadas_tarjeta': met}]}}}


def probar_ciclo():
    import anunciadas as an
    import modo_modelo as mm
    ruta = os.path.join(tempfile.mkdtemp(), 'an.json')
    pick = {'partido': 'A vs B', 'clave_liga': 'x', 'deporte': 'Fútbol', 'inicio': INI}
    an.acumular(_doc([R2]), ruta, dt.datetime(2026, 10, 10, 6, tzinfo=UTC))
    check('fijada' not in an.cargar(ruta)['partidos']['A vs B|x'],
          'a más de 6 h de la ventana no se guarda candidata')
    an.acumular(_doc([R2]), ruta, dt.datetime(2026, 10, 10, 9, tzinfo=UTC))
    an.acumular(_doc([R1]), ruta, dt.datetime(2026, 10, 10, 12, tzinfo=UTC))
    ent = an.cargar(ruta)['partidos']['A vs B|x']
    check([a['apuesta'] for a in ent['fijada']] == ['Goles: Más de 1.5'],
          'antes de la ventana, cada pasada reescribe la candidata (la última manda)')
    an.acumular(_doc([R2]), ruta, dt.datetime(2026, 10, 10, 15, tzinfo=UTC))
    ent = an.cargar(ruta)['partidos']['A vs B|x']
    check([a['apuesta'] for a in ent['fijada']] == ['Goles: Más de 1.5'],
          'ya abierta la ventana, otra apuesta no la cambia')
    recos = [dict(R2), dict(R1, veredicto_vp='no_meter')]
    pr = an.aplicar_fijada(pick, recos, ruta, dt.datetime(2026, 10, 10, 13, tzinfo=UTC))
    check(pr[0].get('provisional_hasta') == '08:00' and mm.metidas(pr)[0]['apuesta'] == 'A o empate',
          'antes de las 08:00 CDMX: la de ahora, marcada PROVISIONAL')
    fj = an.aplicar_fijada(pick, recos, ruta, dt.datetime(2026, 10, 10, 15, tzinfo=UTC))
    met = mm.metidas(fj)
    check([r['apuesta'] for r in met] == ['Goles: Más de 1.5'] and met[0]['fijada']
          and any(r.get('fuera_por_fijada') for r in fj),
          'desde la hora de apostar: sólo la fijada se mete; la nueva queda fuera')
    fj2 = an.aplicar_fijada(pick, [dict(R2)], ruta, dt.datetime(2026, 10, 10, 15, tzinfo=UTC))
    check(mm.metidas(fj2)[0]['apuesta'] == 'Goles: Más de 1.5'
          and mm.metidas(fj2)[0].get('fuera_de_tarjeta'),
          'aunque la tarjeta de ahora ya no la proponga, la oficial se enseña igual')
    ten = dict(pick, deporte='Tenis')
    check(an.aplicar_fijada(ten, recos, ruta, dt.datetime(2026, 10, 10, 15, tzinfo=UTC)) == recos,
          'el tenis no se toca (su apuesta no cambia)')
    an.acumular({'datos': {'pronosticos': [dict(pick, partido='C vs D')]},
                 'decisiones': {'listas': {'pronosticos': [
                     {'llave': ['C vs D', INI, 'x'], 'recomendadas_tarjeta': []}]}}},
                ruta, dt.datetime(2026, 10, 10, 13, tzinfo=UTC))
    vacia = an.aplicar_fijada(dict(pick, partido='C vs D'), [dict(R1)], ruta,
                              dt.datetime(2026, 10, 10, 15, tzinfo=UTC))
    check(not mm.metidas(vacia),
          'si a la hora de apostar no había nada que meter, después tampoco')
    # lo archivado al empezar es la fijada (un partido que empezó hace 1 h:
    # el archivo usa la hora de verdad)
    import partidos_jugados as pj
    ahora = dt.datetime.now(UTC)
    ini = (ahora - dt.timedelta(hours=1)).strftime('%Y-%m-%d %H:%M:%S')
    pick = dict(pick, inicio=ini)
    ruta = os.path.join(tempfile.mkdtemp(), 'an2.json')
    doc = _doc([R1])
    doc['datos']['pronosticos'][0]['inicio'] = ini
    doc['decisiones']['listas']['pronosticos'][0]['llave'][1] = ini
    an.acumular(doc, ruta, ahora - dt.timedelta(hours=6))
    orig_r, orig_ruta = mm.recomendadas, os.environ.get('ANUNCIADAS_FICHERO')
    os.environ['ANUNCIADAS_FICHERO'] = ruta
    mm.recomendadas = lambda *a, **k: [dict(R2)]
    try:
        arch = pj._recomendadas_previas(dict(pick, jugado=True))
    finally:
        mm.recomendadas = orig_r
        if orig_ruta is None:
            os.environ.pop('ANUNCIADAS_FICHERO', None)
        else:
            os.environ['ANUNCIADAS_FICHERO'] = orig_ruta
    check([a['apuesta'] for a in arch] == ['Goles: Más de 1.5'],
          'lo que se archiva al empezar (y cuenta el semáforo) es la fijada')


def probar_pantalla():
    import hora_apuesta as ha
    src = open('modo_modelo.py', encoding='utf-8').read()
    check("' · 🔒 FIJADA'" in src and '⏳ PROVISIONAL · se fija a las' in src,
          'la tarjeta dice FIJADA o PROVISIONAL')
    check("[:30]" not in src.split('def _bloque_validacion')[1].split('def tarjeta(')[0]
          and 'overflow-wrap:anywhere' in src,
          'la fila del terminado ya no corta «Más de 0.5» en «Más de 0»')
    check('provisional%s antes de fijarse' in src and 'filas + _prov' in src,
          'las provisionales van plegadas y fuera de la tira de puntos')
    check(src.count('con_fijada(') >= 6, 'la fijada se aplica en todos los caminos de la tarjeta')
    est = open('estilo_ui.py', encoding='utf-8').read()
    check('provisionales (no cuentan)' in est, 'el marcador dice que las provisionales no cuentan')
    ps = [{'deporte': 'Fútbol', 'inicio': '2026-10-10 18:00:00'},
          {'deporte': 'Fútbol', 'inicio': '2026-10-10 18:45:00'},
          {'deporte': 'Fútbol', 'inicio': '2026-10-10 12:00:00'},
          {'deporte': 'Tenis', 'inicio': '2026-10-10 12:00:00'}]
    fr = ha.franjas(ps)
    check(list(fr.items()) == [('02:00', 1), ('08:00', 2), ('ya', 1)],
          'el reloj agrupa por la hora en que se abre la ventana (%s)' % fr)
    check("'Hora para apostar'" in src and "if hora_sel in _franjas and _ha_f is not None:" in src,
          'y el filtro «Hora para apostar» deja sólo esa franja')


if __name__ == '__main__':
    print('=== 1. la medición ===')
    probar_medicion()
    print('\n=== 2. el ciclo provisional → fijada → archivada ===')
    probar_ciclo()
    print('\n=== 3. la pantalla ===')
    probar_pantalla()
    print('\n' + '=' * 40)
    print('TODO OK' if not FALLOS else '%d FALLOS' % len(FALLOS))
    raise SystemExit(1 if FALLOS else 0)
