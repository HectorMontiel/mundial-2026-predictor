#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test de la v417-v418.

  v417 — la IA bloqueada para quien no es VIP (lleva a Planes) y los planes con
         sus números REALES (30 días, sólo con 30+ partidos; de la IA sólo lo mejor).
  v418 — tarjetas de TODOS los partidos: los que no tienen pick salen como
         «sólo análisis», en un fichero aparte que nunca cuenta en verdes/rojas.

Ejecutar:  python test_v417.py
"""
import datetime as dt
import os

FALLOS = []


def check(cond, msg):
    print(('OK   ' if cond else 'FALLO') + ' ' + msg)
    if not cond:
        FALLOS.append(msg)


def leer(*p):
    return open(os.path.join(*p), encoding='utf-8').read()


def probar_v417():
    sql = leer('supabase', 'v417_planes_y_ia_bloqueada.sql')
    check('historial_niveles with (security_invoker = true)' in sql and "coalesce(tipo, 'pick') <> 'analisis'" in sql,
          'el récord por nivel respeta la RLS de picks y no cuenta las tarjetas de sólo análisis')
    check('select distinct partido, fecha from public.ia_analisis' in sql,
          'ia_disponibles sólo dice QUÉ partidos tienen IA, nunca el contenido')
    app, js, html = leer('web', 'app.js'), leer('web', 'cuenta.js'), leer('web', 'index.html')
    check('function iaBloque(p, L, V, ctx)' in app and 'data-vista-ir="planes" data-foco="plan-vip"' in app
          and 'SPX.esVip && SPX.esVip()' in app, 'quien no es VIP ve «🤖 Análisis IA 🔒 VIP» y lo lleva al plan VIP')
    check('t.dataset.foco && document.getElementById(t.dataset.foco)' in app, 'el candado aterriza en el plan VIP')
    check("esVip: () => esVip()" in js and "from('ia_disponibles')" in js, 'la página sabe qué partidos tienen IA')
    check('async function numerosPlanes()' in js and 'v + r >= 30' in js and "x.que === 'mejor' && x.total >= 30" in js,
          'los planes enseñan números reales, sólo con 30+ partidos, y de la IA sólo lo mejor')
    check('id="plan-vip"' in html and 'id="numeros-vip"' in html and 'id="numeros-monedas"' in html
          and 'Análisis IA de cada partido' in html, 'cada plan dice lo que incluye y trae sus números')


def probar_v418():
    import exportar_web as xw
    hoy = dt.date(2026, 10, 21)
    prons = [{'deporte': 'Fútbol', 'partido': 'A vs B', 'fecha': '2026-10-21', 'inicio': '2026-10-21 19:00:00', 'apuesta': 'Gana A', 'prob': 0.6},
             {'deporte': 'Fútbol', 'partido': 'C vs D', 'fecha': '2026-10-21', 'inicio': '2026-10-21 19:00:00', 'apuesta': 'Gana C', 'prob': 0.7},
             {'deporte': 'Fútbol', 'partido': 'E vs F', 'fecha': '2026-10-30', 'inicio': '2026-10-30 19:00:00', 'apuesta': 'Gana E', 'prob': 0.7}]
    picks = [{'partido': 'C vs D', 'fecha': '2026-10-21', 'id': 'x'}]
    jugados = [{'deporte': 'Fútbol', 'partido': 'G vs H', 'fecha': '2026-10-20', 'inicio': '2026-10-20 19:00:00', 'apuesta': 'Gana H',
                'prob': 0.48, 'jugado': True, 'goles_home': 1, 'goles_away': 2},
               {'deporte': 'Fútbol', 'partido': 'I vs J', 'fecha': '2026-10-20', 'jugado': True}]
    an = xw.solo_analisis(prons, picks, jugados, hoy)
    por = {a['partido']: a for a in an}
    check(set(por) == {'A vs B', 'G vs H'}, 'sólo los partidos SIN pick, de hoy a pasado, y los jugados con marcador: %s' % sorted(por))
    a = por.get('A vs B') or {}
    check(a.get('solo_analisis') and a.get('tipo') == 'analisis' and a.get('premium') is False and a.get('cuota') is None
          and str(a.get('id', '')).startswith('an-'), 'la tarjeta va marcada, sin cuota ni premium, y con su propio id')
    check((por.get('G vs H') or {}).get('marcador') == '1-2' and (por.get('G vs H') or {}).get('estado') == 'final',
          'lo ya jugado sale con su marcador')
    src = leer('exportar_web.py')
    check("ANALISIS = os.environ.get('WEB_ANALISIS'" in src and "r.pop('analisis', [])" in src
          and 'subir_supabase(r[' not in src.split('def solo_analisis')[1].split('def construir')[0],
          'las de sólo análisis van a su fichero, nunca a la tabla picks')
    ia = leer('ia_gemini.py')
    check("'analisis.json'" in ia and "if not x.get('solo_analisis')" in ia and "-1 if x.get('solo_analisis')" in ia,
          'la IA analiza también esos partidos, sin tomar la sugerencia del modelo como pick nuestro')
    app = leer('web', 'app.js')
    check("if (p.solo_analisis) return { n: 'Sólo análisis'" in app and 'function listaConAnalisis()' in app
          and "cajaMarcador('Hoy', estado.picks.filter" in app, 'la página las enseña sutiles y los marcadores siguen contando sólo picks')


def probar_v419():
    import pandas as pd
    import config
    import historico_fotmob as hf
    import stats_flashscore as sf
    for c, n in (('cze_first', 1000), ('aze_premier', 600)):
        h = pd.read_csv('historico_%s.csv' % c)
        check(c in config.LEAGUES and c in hf.LIGAS and c in sf.EXTRA and len(h) >= n and h['home_corners'].notna().sum() >= 200,
              'v419: %s con partidos y córners REALES (%d partidos, %d con córners)' % (c, len(h), h['home_corners'].notna().sum()))
    check(config.LEAGUES['cze_first'].get('disponible') is False and config.LEAGUES['aze_premier'].get('disponible') is False,
          'v419: Chequia y Azerbaiyán no entran al barrido de picks (sólo dan liga local)')
    js = leer('web', 'cuenta.js')
    check('>= 0.75 ? linea(ico, n' in js, 'v419: los planes sólo presumen los niveles de 75 % o más')


def probar_v420():
    import datetime as _dt
    import combinadas_web as cw
    check(cw.TIPOS['combinada']['cuota'] == (1.20, 1.60) and cw.TIPOS['combinada'].get('solo_altos')
          and cw.TIPOS['combinada'].get('por_acierto') and cw.TIPOS['alta']['cuota'] == (1.80, 2.60),
          'v420: las de 2 patas con 💎/🔷 por acierto real, cuota 1,20-1,60; las de 3 sin cambio')
    ahora = _dt.datetime(2026, 10, 21, 12, tzinfo=_dt.timezone.utc)
    ini = (ahora + _dt.timedelta(hours=3)).strftime('%Y-%m-%d %H:%M:%S')
    pk = lambda i, dep, c, pr, el=False: {'id': 'q%d' % i, 'partido': 'X%d vs Y%d' % (i, i), 'deporte': dep, 'apuesta': 'Gana X%d' % i,
                                           'cuota': c, 'prob': pr, 'elige': el, 'inicio': ini, 'estado': 'pendiente', 'tipo': 'pick'}
    ps = [pk(1, 'Tenis', 1.12, .90, True), pk(2, 'Tenis', 1.12, .89, True), pk(3, 'Tenis', 1.25, .80), pk(4, 'Tenis', 1.24, .81)]
    cs = [c for c in cw.armar(ps, {}, ahora, cal={}) if c['tipo'] == 'combinada' and c['alcance'] == 'Tenis']
    check(cs and {x['id'] for x in cs[0]['patas']} == {'q1', 'q2'},
          'v420: dos 💎 a 1,12 (1,25 total) ya entran; antes se forzaban patas más flojas')
    cal = cw.calibracion([{'elige': True, 'deporte': 'Tenis', 'estado': 'verde'}] * 20 + [{'elige': True, 'deporte': 'NBA', 'estado': 'roja'}] * 20)
    check(cal[('Diamante', 'Tenis')] > 0.9 and cal[('Diamante', 'NBA')] < 0.3, 'v420: la calibración es el acierto real por nivel y deporte')


def probar_v420_web():
    sql = leer('supabase', 'v420_precios_plata_deportes.sql')
    import re as _re
    bandas = [(float(a), float(b), int(m)) for a, b, m in _re.findall(r'\((\d\.\d\d), (\d+\.\d\d), (\d+)\)', sql)]
    check(bandas and min(m for _, _, m in bandas) == 5 and bandas[0][:2] == (1.00, 1.15) and bandas[1] == (1.15, 1.30, 6)
          and all(bandas[i][1] == bandas[i + 1][0] and bandas[i][2] < bandas[i + 1][2] for i in range(len(bandas) - 1)),
          'v420: precios escalonados desde 5 🪙, sin huecos y siempre subiendo: %s' % bandas)
    check("coalesce((p).prob, 0) >= 0.80 and coalesce((p).prob, 0) < 0.85 then 0" in sql and "= 'analisis' then 0" in sql,
          'v420: 🥇 Oro gratis, 🥈 Plata a monedas y el «sólo análisis» nunca se cobra')
    check('create or replace view public.historial_deportes' in sql and 'gana_por_100' in sql.split('create or replace view public.historial_niveles')[-1],
          'v420: historial por deporte y la ganancia por nivel')
    js, html = leer('web', 'cuenta.js'), leer('web', 'index.html')
    check("['Diamante', 'Platino', 'Plata', 'Cuota alta'].includes(n)" in js and '<li>Picks 🥇 Oro</li>' in html,
          'v420: la página cobra 🥈 Plata y el plan gratis dice sólo 🥇 Oro')
    check('function mejorIA(med)' in js and 'm.total >= 20 && m.ok / m.total >= 0.65' in js and 'function wilson(ok, n)' in js
          and 'calibracion(med)' not in js.split('mejorIA(med) +')[0][-400:],
          'v420: de la IA sólo lo mejor, nivelado entre porcentaje y cantidad (Wilson, 20+ partidos)')
    check("'IA, el ganador del partido'" in js and "id=\"tabla-precios\"" in html and "from('historial_deportes')" in js
          and 'id="dep-hist"' in html, 'v420: el ganador de la IA en el VIP, precios de la base y el historial por deporte')


if __name__ == '__main__':
    probar_v420_web()
    probar_v420()
    probar_v419()
    probar_v417()
    probar_v418()
    print('\n' + '=' * 40)
    print('TODO OK' if not FALLOS else '%d FALLOS' % len(FALLOS))
    raise SystemExit(1 if FALLOS else 0)
