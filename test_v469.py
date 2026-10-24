#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v469 — qué jugador puede anotar y tirar a puerta 1+/2+ (dentro del análisis IA), y las noticias
de verdad para la IA (Google News: la búsqueda de Gemini nunca funcionó). Sin red."""
import json
import os
import sys
import tempfile
import types

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
FALLOS = []


def check(cond, msg):
    print(('OK   ' if cond else 'FALLO') + ' ' + msg)
    if not cond:
        FALLOS.append(msg)


def base_falsa(ruta):
    """Dos equipos de 6 partidos; el femenil del Local se llama igual y NO debe mezclarse."""
    filas = ['match_id,fecha,liga,equipo,jugador,jugador_id,posicion,titular,minutos,tiros,a_puerta,goles,xg,pos,up,mv']
    for i in range(6):
        m, f = 100 + i, '2026-10-%02d' % (i + 1)
        filas += ['%d,%s,laliga,Local,Goleador,1,F,1,90,5,3,1,0.8,0,0,0' % (m, f),
                  '%d,%s,laliga,Local,Lateral,2,D,1,90,0,0,0,0.02,0,0,0' % (m, f),
                  '%d,%s,laliga,Local,Suplente,3,M,0,10,0,0,0,0.0,0,0,0' % (m, f),
                  '%d,%s,laliga,Rival,Delantero,4,F,1,90,2,1,0,0.3,0,0,0' % (m, f)]
        mf = 200 + i
        filas += ['%d,%s,fem_espana,Local,Jugadora,9,F,1,90,6,4,2,1.2,0,0,0' % (mf, f),
                  '%d,%s,fem_espana,Otra,Defensa,8,D,1,90,0,0,0,0.0,0,0,0' % (mf, f)]
    open(ruta, 'w', encoding='utf-8').write('\n'.join(filas) + '\n')


def probar():
    import jugadores_prob as jp
    check(abs(jp._p_ge(1.0, 1, 1e-6) - (1 - 2.718281828 ** -1)) < 1e-3 and jp._p_ge(0, 1) == 0 and jp._p_ge(2, 2) < jp._p_ge(2, 1),
          'v469: el conteo (binomial negativa ≈ Poisson con alpha 0) y 2+ < 1+')
    cal = json.load(open(jp.CAL, encoding='utf-8'))
    check(set(cal) == {'gol', 'p1', 'p2'} and all(v['y'] == sorted(v['y']) for v in cal.values()),
          'v469: la calibración medida (isotónica) de anota, 1+ y 2+; nada de 3+ (no ganó)')
    d = tempfile.mkdtemp()
    ruta = os.path.join(d, 'jug.csv')
    base_falsa(ruta)
    viejo = jp.HIST
    jp.HIST, jp._MEM = ruta, {'cal': {}}
    try:
        xs = jp.equipo(jp.clave('Local', False), jp.clave('Rival', False))
        fem = jp.equipo(jp.clave('Local (W)', True), jp.clave('Otra', True))
    finally:
        jp.HIST, jp._MEM = viejo, {}
    nombres = [x['n'] for x in xs]
    check('Jugadora' not in nombres and [x['n'] for x in fem] == ['Jugadora'],
          'v469: el femenil del mismo club (mismo nombre en la base) va aparte: no se mezclan')
    check(nombres[0] == 'Goleador' and xs[0]['gol'] > xs[1]['gol'] and xs[0]['p1'] > 0.5 and xs[0]['p2'] > 0.2,
          'v469: el que más tira y anota sale primero, con 1+ y 2+ a puerta')
    sup = [x for x in xs if x['n'] == 'Suplente']
    check(sup and sup[0]['p1'] < xs[0]['p1'] / 3, 'v469: el que juega 10 minutos casi no cuenta (minutos esperados)')
    check(jp.clave('Ajax (W)', True) == 'Ajax|F' and jp.clave('Ajax', False) == 'Ajax', 'v469: la clave del equipo')

    ex = open('exportar_web.py', encoding='utf-8').read()
    check("'jug')" in ex and 0 < ex.find('escudos.poner(picks + analisis)') < ex.find('jugadores_prob.poner(picks + analisis)'),
          'v469: los jugadores se ponen en cada pasada (después de emparejar el partido con FotMob) y suben en `jug`')
    check(os.path.exists(os.path.join('supabase', 'v469_jugadores.sql'))
          and 'add column if not exists jug jsonb' in open(os.path.join('supabase', 'v469_jugadores.sql'), encoding='utf-8').read(),
          'v469: la columna nueva va en una migración NUEVA')

    import ia_gemini as ia
    check(not any('2.5' in m for m in ia.MODELOS), 'v469: sin los modelos 2.5 (Google los retiró: 404 en cada pasada)')
    rss = ('<rss><channel>'
           '<item><title>Baja de Julián Álvarez para el sábado - MARCA</title><pubDate>Fri, 23 Oct 2026 10:00:00 GMT</pubDate></item>'
           '<item><title>Atlético - Deportivo: dónde ver el partido - AS</title><pubDate>Fri, 23 Oct 2026 11:00:00 GMT</pubDate></item>'
           '<item><title>Atlético gana 3-0 al Deportivo - El País</title><pubDate>Sat, 24 Oct 2026 21:00:00 GMT</pubDate></item>'
           '</channel></rss>')
    pedidos = []
    falso = types.SimpleNamespace(get=lambda url, params=None, timeout=None, headers=None: (
        pedidos.append(params['q']) or types.SimpleNamespace(ok=True, text=rss)))
    viejo_r, viejo_s = sys.modules.get('requests'), ia.time.sleep
    sys.modules['requests'], ia.time.sleep = falso, (lambda s: None)
    try:
        w = ia.noticias_rss([{'partido': 'Ath Madrid vs La Coruna', 'inicio': '2026-10-24 19:00:00'}])
    finally:
        sys.modules['requests'], ia.time.sleep = viejo_r, viejo_s
    n = (w.get('Ath Madrid vs La Coruna') or {}).get('noticias')
    check(n == ['Baja de Julián Álvarez para el sábado'], 'v469: Google News trae lo de ANTES del inicio y sin «dónde ver»: %s' % n)
    check(pedidos and 'Atlético Madrid' in pedidos[0], 'v469: busca con el nombre completo de los alias («Ath Madrid» → «Atlético Madrid»)')
    src = open('ia_gemini.py', encoding='utf-8').read()
    check("web = noticias_rss(lote) if dep == 'Fútbol' else {}" in src and "'jugadores_probables'" in src,
          'v469: la IA recibe las noticias de Google News (todos los partidos) y los jugadores probables')

    app = open(os.path.join('web', 'app.js'), encoding='utf-8').read()
    ia_js = app[app.index('function iaHtml('):app.index('function iaHtml(') + 7000]
    check('jugadoresHtml(jug, L, V)' in ia_js and 'function jugadoresHtml(jug, L, V)' in app and '<small>2+</small>' in app and '3+' not in ia_js,
          'v469: los jugadores van DENTRO del análisis IA (anota, a puerta 1+ y 2+)')
    check("if (vip && (jugadoresHtml(jug, L, V) || lineasHtml(ctx, L, V)))" in app, 'v469: el VIP los ve aunque la IA aún no analice el partido; los demás, con candado')


if __name__ == '__main__':
    probar()
    print('\n' + '=' * 40)
    print('TODO OK' if not FALLOS else '%d FALLOS' % len(FALLOS))
    raise SystemExit(1 if FALLOS else 0)
