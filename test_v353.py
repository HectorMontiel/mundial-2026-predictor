#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test de la v353.

El usuario, con el día en 6 ✅ 4 ❌: «¿bajó la precisión? ¿metimos algo mal?
valídalo»; «hay mucho texto en "también se meten"»; y «no veo los tiros a
puerta ni los remates de la metodología de mi amigo, aunque sea informativo
con su porcentaje».

Lo que se vigila:
  1. EL TENIS CONTADO DOS VECES: el mismo partido con los nombres de dos
     fuentes («Karen Khachanov» / «Khachanov K.») se une en uno.
  2. LOS TIROS EN EL ANÁLISIS, con la línea «más de X» al 70 %+ (y lo que
     dice el modelo en esa franja se cumple en los partidos reales).
  3. «TAMBIÉN SE METEN» EN UNA LÍNEA CORTA.

Ejecutar:  python test_v353.py
"""
FALLOS = []


def check(cond, msg):
    print(('OK   ' if cond else 'FALLO') + ' ' + msg)
    if not cond:
        FALLOS.append(msg)


def probar_tenis():
    import partidos_jugados as pj
    a = {'deporte': 'Tenis', 'clave_liga': 'atp', 'partido': 'Karen Khachanov vs Arthur Fery',
         'inicio': '2026-10-09T08:00:00', 'recomendadas_previas': [{'apuesta': 'Gana Karen Khachanov'}]}
    b = {'deporte': 'Tenis', 'clave_liga': 'atp', 'partido': 'Khachanov K. vs Fery A.',
         'inicio': '2026-10-09T08:30:00', 'goles_home': 2.0, 'goles_away': 1.0}
    c = {'deporte': 'Tenis', 'clave_liga': 'atp', 'partido': 'Fery A. vs Khachanov K.',
         'inicio': '2026-10-09T10:00:00'}
    otro = {'deporte': 'Tenis', 'clave_liga': 'atp', 'partido': 'Karen Khachanov vs Jannik Sinner',
            'inicio': '2026-10-09T08:00:00'}
    check(pj._misma_cita(a, b) and pj._misma_cita(a, c),
          'el mismo partido con nombres de dos fuentes (y con los bandos al revés) es uno')
    check(not pj._misma_cita(a, otro), 'con otro rival no es el mismo partido')
    check(not pj._mismo_tenista('Maria Sakkari', 'Maria Bouzkova')
          and pj._mismo_tenista('Maria Florencia Urrutia', 'Maria Urrutia'),
          'compartir el nombre de pila no basta; el apellido sí')
    u = pj.unir([a, b])
    check(len(u) == 1 and u[0].get('recomendadas_previas') and u[0].get('goles_home') == 2.0,
          'se fusionan: la apuesta de una copia y el marcador de la otra')


def probar_tiros():
    import modo_modelo as mm
    import tiros_equipo as te
    orig = te.del_partido
    te.del_partido = lambda p, *a, **k: {
        'lados': {'local': {'tiros': 15.3, 'a_puerta': 5.1},
                  'visitante': {'tiros': 15.1, 'a_puerta': 5.6}},
        'k': {'tiros': 19.7, 'a_puerta': 42.9}, 'peso_modelo': {}}
    try:
        lin = mm._lineas_tiros({'partido': 'Tigres UANL vs Toluca'}, 'Tigres UANL', 'Toluca')
    finally:
        te.del_partido = orig
    check(len(lin) == 2 and lin[0].startswith('🎯 Tiros') and lin[1].startswith('🥅 A puerta')
          and 'más de 11.5:' in lin[0] and 'más de 3.5:' in lin[1],
          'los tiros y los tiros a puerta, con la media y su «más de» al 70 %%+ (%s)' % lin)
    import pandas as pd
    s = pd.read_csv('tiros_seguimiento.csv')
    s = s[s.real.notna()].drop_duplicates(['partido', 'equipo', 'mercado', 'linea'])
    s = s[(s.p_mod >= 0.7) & (s.p_mod < 0.8)]
    real, promete = float((s.real > s.linea).mean()), float(s.p_mod.mean())
    check(len(s) >= 100 and abs(real - promete) <= 0.05,
          'en partidos reales lo que da al 70-80 %% se cumple: promete %.1f, acierta %.1f (%d)'
          % (100 * promete, 100 * real, len(s)))
    src = open('modo_modelo.py', encoding='utf-8').read()
    check('lineas.extend(_lineas_tiros(pick, h, a))' in src, 'y van en el «🔍 Análisis»')


def probar_fijada_reconstruida():
    """v353 — la fijada que la tarjeta de ahora ya no propone se pinta entera
    (le faltaba `verde` y la tarjeta se rompía; lo cazó test_v327)."""
    import datetime as dt
    import json as _j
    import os
    import tempfile
    import anunciadas as an
    ruta = os.path.join(tempfile.mkdtemp(), 'an.json')
    _j.dump({'partidos': {'A vs B|x': {'inicio': '2026-10-10 18:00:00', 'apuestas': [],
                                       'fijada': [{'apuesta': 'Goles: Más de 1.5', 'cuota': 1.2,
                                                   'prob': 0.8, 'prob_meter': 0.8,
                                                   'mercado': 'Goles'}],
                                       'fijada_ts': '2026-10-10T13:00:00Z'}}},
            open(ruta, 'w', encoding='utf-8'))
    r = an.aplicar_fijada({'partido': 'A vs B', 'clave_liga': 'x', 'inicio': '2026-10-10 18:00:00'},
                          [], ruta, dt.datetime(2026, 10, 10, 15, tzinfo=dt.timezone.utc))
    falta = [c for c in ('verde', 'prob', 'cuota', 'score', 'cuota_justa', 'puesto_valor')
             if c not in r[0]]
    check(not falta and r[0]['verde'], 'la fijada reconstruida trae lo que pinta la tarjeta (%s)' % falta)


def probar_texto():
    import modo_modelo as mm
    check(len(mm.TEXTO_OTRAS) <= 70 and '79 %' in mm.TEXTO_OTRAS,
          '«También se meten» en una línea corta (%d letras)' % len(mm.TEXTO_OTRAS))


if __name__ == '__main__':
    print('=== 1. el tenis contado dos veces ===')
    probar_tenis()
    print('\n=== 2. los tiros, informativos ===')
    probar_tiros()
    probar_fijada_reconstruida()
    print('\n=== 3. breve ===')
    probar_texto()
    print('\n' + '=' * 40)
    print('TODO OK' if not FALLOS else '%d FALLOS' % len(FALLOS))
    raise SystemExit(1 if FALLOS else 0)
