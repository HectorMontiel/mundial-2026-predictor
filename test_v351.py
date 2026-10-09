#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test de la v351.

El usuario: «¿cuál es la hora adecuada para apostar ese partido? Algo breve
y visual; no siempre una hora antes, que con un parlay no da tiempo» y «que
todo lo de la Capa 1 —errores de cuota, buena cuota con buena probabilidad,
mayor riesgo— tenga si se ganó o no, con un indicador súper breve de la tasa
de conversión verdes contra rojas».

Lo que se vigila:
  1. LA HORA: medida (apostar pronto no cuesta acierto ni cuota; desde 4 h
     antes la apuesta ya casi no cambia), en la tarjeta y en las listas.
  2. LA CAPA 1 GUARDA LOS CUATRO GRUPOS (🏆 🔷 💰 🎯).
  3. LA LIQUIDACIÓN de cualquier liga, con doble oportunidad y devolución.
  4. LA TASA y las filas terminadas, en la pantalla.

Ejecutar:  python test_v351.py
"""
import datetime as dt
import json
import os
import tempfile

FALLOS = []


def check(cond, msg):
    print(('OK   ' if cond else 'FALLO') + ' ' + msg)
    if not cond:
        FALLOS.append(msg)


def probar_hora():
    import hora_apuesta as ha
    import vista_compacta as vc
    m = json.load(open('_v351_hora.json', encoding='utf-8'))
    pr, ta = m['acierto_pronto_vs_tarde']['pronto_>6h'], m['acierto_pronto_vs_tarde']['tarde_<=3h']
    check(abs(pr[0] - ta[0]) < 0.03 and abs(m['acierto_pronto_vs_tarde']['cuota_pronto_vs_pitido']) < 0.01,
          'medido: apostar pronto acierta lo mismo (%.1f vs %.1f %%) y a la misma cuota'
          % (100 * pr[0], 100 * ta[0]))
    fut = {r['b']: r for r in m['tabla_Fútbol']}
    check(fut['(2, 3]']['se_queda'] >= 0.88 and fut['(3, 4]']['se_queda'] >= 0.85
          and fut['(12, 18]']['se_queda'] < 0.80,
          'fútbol: a 2-4 h la apuesta ya es la del pitido (%.0f / %.0f %%); a 12-18 h no (%.0f %%)'
          % (100 * fut['(2, 3]']['se_queda'], 100 * fut['(3, 4]']['se_queda'],
             100 * fut['(12, 18]']['se_queda']))
    check(ha.texto({'deporte': 'Fútbol', 'inicio': '2026-10-10 18:00:00'}) == '⏰ apuesta desde 08:00',
          'fútbol: 4 h antes, en hora de CDMX (12:00 → 08:00)')
    check(ha.texto({'deporte': 'Tenis', 'inicio': '2026-10-10 18:00:00'}) == '⏰ apuesta en cuanto salga',
          'tenis: la apuesta no cambia, en cuanto salga')
    check(ha.texto({'deporte': 'Fútbol'}) == '', 'sin hora del partido no se inventa')
    p = {'deporte': 'Fútbol', 'inicio': '2026-10-10 18:00:00', 'cuota': 1.2,
         'apuesta': 'Gana A', 'partido': 'A vs B', 'prob': 0.8}
    check('⏰08:00' in vc.html_lista([p]), 'las listas (Capa 1) llevan ⏰08:00')
    check('⏰' not in vc.html_lista([dict(p, resultado_c1='verde', marcador='1-0')]),
          'y lo terminado ya no')
    src = open('modo_modelo.py', encoding='utf-8').read()
    check('_ha.texto(pick)' in src, 'la tarjeta la lleva junto a la hora del partido')


def probar_acumular():
    import anunciadas as an
    import probables
    orig = probables.barrer
    probables.barrer = lambda *a, **k: [
        {'deporte': 'Fútbol', 'clave_liga': 'x', 'partido': 'C vs D',
         'inicio': '2026-10-10 20:00:00', 'mercado': 'Ganador',
         'apuesta': 'Gana D', 'cuota': 1.6, 'prob': 0.66}]
    try:
        partidos = {}
        doc = {'datos': {'pronosticos': [{'partido': 'Z vs W', 'jugado': True}], 'capa1': [
            {'deporte': 'Baloncesto', 'clave_liga': 'iceland', 'liga': 'iceland',
             'partido': 'E vs F', 'inicio': '2026-10-10 19:00:00',
             'mercado': 'Ganador', 'apuesta': 'Gana F', 'cuota': 2.7, 'validado': True},
            {'deporte': 'Fútbol', 'clave_liga': 'y', 'partido': 'G vs H',
             'inicio': '2026-10-10 19:00:00', 'mercado': 'Goles',
             'apuesta': 'Más de 3.0 goles', 'cuota': 2.8, 'validado': False}]}}
        n = an._acumular_capa1(doc, partidos, dt.datetime(2026, 10, 10, 12, tzinfo=dt.timezone.utc))
    finally:
        probables.barrer = orig
    niveles = {x['nivel'] for e in partidos.values() for x in e.get('capa1', [])}
    check(n == 2 and niveles == {'💰', '🎯'},
          'guarda 💰 (los que la app enseña, no los «sin validar») y 🎯 (%s)' % niveles)
    e = partidos['E vs F|iceland']
    check(e['deporte'] == 'Baloncesto' and e['partido'] == 'E vs F',
          'con su deporte y su partido, para liquidarlo aunque no tenga modelo')


def probar_liquidar():
    import capa1_resultados as cr
    check(cr.resolver('Doble oportunidad', 'A o empate', 'A', 'B', 1, 1) == 'verde'
          and cr.resolver('Doble oportunidad', 'B o empate', 'A', 'B', 2, 1) == 'rojo',
          'doble oportunidad (lo más común en 🏆), que el liquidador no conocía')
    check(cr.resolver('Goles', 'Más de 3.0 goles', 'A', 'B', 2, 1) == 'nula'
          and cr.resolver('Goles', 'Más de 3.0 goles', 'A', 'B', 3, 1) == 'verde',
          'línea entera con el total exacto: se devuelve (nula), no se da perdida')
    check(cr.resolver('Ganador', 'Gana F', 'E', 'F', 80, 91) == 'verde', 'ganador de básquet')
    d = tempfile.mkdtemp()
    ra, rh = os.path.join(d, 'a.json'), os.path.join(d, 'h.json')
    json.dump({'partidos': {'Elan Chalon vs Fos Provence|fra': {
        'inicio': '2026-10-08 19:00:00', 'partido': 'Elan Chalon vs Fos Provence', 'deporte': 'Baloncesto',
        'capa1': [{'apuesta': 'Gana Fos Provence', 'mercado': 'Ganador', 'cuota': 2.7,
                   'nivel': '💰', 'desde': '2026-10-08T10:00:00Z'}]}}},
              open(ra, 'w', encoding='utf-8'))
    orig = cr._lista
    cr._lista = lambda dep, dia, hoy, cache: [
        {'ini': dt.datetime(2026, 10, 8, 19, tzinfo=dt.timezone.utc),
         'home': 'Elan Chalon', 'away': 'Fos Provence', 'gh': 80.0, 'ga': 91.0}]
    try:
        n = cr.liquidar(ra, rh, dt.datetime(2026, 10, 9, 3, tzinfo=dt.timezone.utc))
        n2 = cr.liquidar(ra, rh, dt.datetime(2026, 10, 9, 5, tzinfo=dt.timezone.utc))
    finally:
        cr._lista = orig
    h = json.load(open(rh, encoding='utf-8'))['filas']
    check(n == 1 and n2 == 0 and h[0]['resultado'] == 'verde' and h[0]['marcador'] == '80-91',
          'liquida el error de precio de una liga sin modelo y no lo repite')
    check(cr.tasa('💰', '2026-10-08', rh) == '📈 7 días 100 % (✅1 ❌0)'
          and cr.tasa('💰', '2026-10-08', rh, deportes={'Fútbol'}) == '',
          'la tasa breve del grupo, que respeta el filtro de deportes')
    f = cr.finalizadas('💰', '2026-10-08', ra, dt.datetime(2026, 10, 9, 5, tzinfo=dt.timezone.utc))
    check(len(f) == 1 and f[0]['resultado_c1'] == 'verde' and f[0]['marcador'] == '80-91',
          'y la fila terminada, en verde con su marcador')
    hist = json.load(open('capa1_historial.json', encoding='utf-8'))['filas']
    v = sum(1 for x in hist if x['nivel'] == '🏆' and x['resultado'] == 'verde')
    r = sum(1 for x in hist if x['nivel'] == '🏆' and x['resultado'] == 'rojo')
    check(v + r >= 50 and v / (v + r) >= 0.78,
          'la semilla (3-8 oct): 🏆 %d ✅ %d ❌ (%.0f %%)' % (v, r, 100 * v / max(1, v + r)))


def probar_pantalla():
    d = open('dashboard_ui.py', encoding='utf-8').read()
    check("_c1r.finalizadas('💰', _hoy_c1)" in d and "_c1r.finalizadas('🎯', _hoy_c1)" in d
          and d.count('_tasa_c1(') >= 5,
          'la Capa 1 pinta 💰 y 🎯 terminados y la tasa en los cuatro grupos')
    pre = open('precalculo_dia.py', encoding='utf-8').read()
    wf = open('.github/workflows/precalculo_dia.yml', encoding='utf-8').read()
    check('capa1_resultados.liquidar()' in pre and 'capa1_historial.json' in wf,
          'el cron liquida y publica el historial')


if __name__ == '__main__':
    print('=== 1. la hora ===')
    probar_hora()
    print('\n=== 2. la Capa 1 guarda los cuatro grupos ===')
    probar_acumular()
    print('\n=== 3. la liquidación ===')
    probar_liquidar()
    print('\n=== 4. la pantalla ===')
    probar_pantalla()
    print('\n' + '=' * 40)
    print('TODO OK' if not FALLOS else '%d FALLOS' % len(FALLOS))
    raise SystemExit(1 if FALLOS else 0)
