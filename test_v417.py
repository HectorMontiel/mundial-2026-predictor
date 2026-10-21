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


if __name__ == '__main__':
    probar_v417()
    probar_v418()
    print('\n' + '=' * 40)
    print('TODO OK' if not FALLOS else '%d FALLOS' % len(FALLOS))
    raise SystemExit(1 if FALLOS else 0)
