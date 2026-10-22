#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v446 — la IA busca noticias en la web (bajas, alineaciones) antes de analizar,
y si la búsqueda falla, analiza como antes. Se prueba sin red: con respuestas
simuladas de Gemini."""
import json
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
FALLOS = []


def check(cond, msg):
    print(('OK   ' if cond else 'FALLO') + ' ' + msg)
    if not cond:
        FALLOS.append(msg)


class Resp:
    def __init__(self, code, data):
        self.status_code, self._d = code, data
        self.ok = code < 400
        self.text = json.dumps(data)

    def json(self):
        return self._d


def probar():
    os.environ['GEMINI_API_KEY'] = 'prueba'
    import ia_gemini as ia
    lote = [{'partido': 'Atlas vs Club America', 'deporte': 'Fútbol', 'liga': 'Liga MX', 'inicio': '2026-10-22T02:00:00Z'},
            {'partido': 'Puebla vs Monterrey', 'deporte': 'Fútbol', 'liga': 'Liga MX', 'inicio': '2026-10-22T02:00:00Z'}]
    vistos = []

    def post(url, params=None, json=None, timeout=None):
        vistos.append(json)
        txt = ('Aquí va:\n```json\n{"partidos": [{"partido": "Atlas vs Club America", "noticias": ["Henry Martín, baja por lesión", '
               '"Atlas sin su portero titular (suspendido)"], "fuentes": ["ESPN"]}, {"partido": "Puebla vs Monterrey", '
               '"noticias": ["sin novedades"], "fuentes": []}]}\n```')
        return Resp(200, {'candidates': [{'content': {'parts': [{'text': txt}]},
                                          'groundingMetadata': {'groundingChunks': [{'web': {'title': 'mediotiempo.com'}}]}}]})
    sys.modules['requests'] = types.SimpleNamespace(post=post)
    ia._AGOTADOS_WEB.clear()
    w = ia.noticias_web(lote)
    check(vistos and vistos[0].get('tools') == [{'google_search': {}}] and 'responseSchema' not in vistos[0].get('generationConfig', {}),
          'v446: la búsqueda usa Google (sin esquema, que no se puede combinar con la búsqueda)')
    check(w.get('Atlas vs Club America', {}).get('noticias', [None])[0] == 'Henry Martín, baja por lesión'
          and w['Atlas vs Club America']['fuentes'] == ['ESPN'], 'v446: lee las noticias y sus fuentes aunque vengan entre texto')
    check(w.get('Puebla vs Monterrey', {}).get('noticias') == [], 'v446: «sin novedades» no cuenta como noticia')

    def post429(url, params=None, json=None, timeout=None):
        return Resp(429, {'error': 'cupo'})
    sys.modules['requests'] = types.SimpleNamespace(post=post429)
    ia._AGOTADOS_WEB.clear()
    check(ia.noticias_web(lote) == {} and set(ia._AGOTADOS_WEB) == set(ia.MODELOS),
          'v446: sin cupo de búsqueda, no hay noticias (y el análisis sigue como antes)')

    def roto(url, params=None, json=None, timeout=None):
        return Resp(200, {'candidates': [{'content': {'parts': [{'text': 'no es json'}]}}]})
    sys.modules['requests'] = types.SimpleNamespace(post=roto)
    ia._AGOTADOS_WEB.clear()
    check(ia.noticias_web(lote) == {}, 'v446: una respuesta rara no rompe nada')

    os.environ['IA_BUSCAR'] = '0'
    import importlib
    ia2 = importlib.reload(ia)
    check(ia2.noticias_web(lote) == {}, 'v446: IA_BUSCAR=0 apaga la búsqueda')
    os.environ.pop('IA_BUSCAR', None)
    importlib.reload(ia)

    src = open('ia_gemini.py', encoding='utf-8').read()
    check("d['noticias_recientes_web'] = w['noticias']" in src and "f['con_noticias'] = bool(w and w['noticias'])" in src
          and "for grupo in (_V447, _V446, _V407):" in src,'v446: el análisis recibe las noticias y queda marcado si las usó (y guarda aunque falte la columna)')
    check('noticias_recientes_web' in ia.INSTRUCCION and 'noticias_recientes_web' in ia.instruccion('NBA'),
          'v446: las reglas de la IA dicen que las noticias de la web son datos (en todos los deportes)')
    sql = open(os.path.join('supabase', 'v446_reportes_y_calificaciones.sql'), encoding='utf-8').read()
    check('add column if not exists con_noticias boolean' in sql and 'create or replace function public.resolver_reporte' in sql
          and 'create table if not exists public.ia_calificaciones' in sql and "if v_pagados < 3 then v_monedas := 5; end if;" in sql,
          'v446: la migración nueva (reportes con pago del servidor, calificaciones y columnas de noticias)')


def probar_v447():
    import datetime as dt
    import ia_gemini as ia
    check('primero_anota' in ia.ESQUEMA['required'] and 'primero_anota' in ia.ESQUEMA_GEN['properties']
          and 'primero_anota' not in ia.ESQUEMA_GEN['required'], 'v447: quién anota primero (obligatorio en fútbol, opcional en los demás)')
    f = ia.fila({'id': 'x', 'fecha': '2026-10-22', 'inicio': 'z', 'partido': 'A vs B'},
                {'p_local': .5, 'p_empate': .3, 'p_visita': .2, 'primero_anota': 'visita', 'prob_primero': .44}, {})
    check(f['primero_anota'] == 'visita' and f['prob_primero'] == 0.44, 'v447: la fila guarda quién anota primero y su probabilidad')
    check(ia.fila({'id': 'x', 'fecha': 'f', 'inicio': 'z', 'partido': 'A vs B'}, {'primero_anota': 'quizá'}, {})['primero_anota'] is None,
          'v447: un valor raro no se guarda')

    class R:
        def __init__(self, d):
            self._d = d

        def json(self):
            return self._d
    eventos = {'keyEvents': [{'scoringPlay': False, 'team': {'displayName': 'Atlas'}},
                             {'scoringPlay': True, 'type': {'text': 'Goal'}, 'team': {'displayName': 'América'}}]}
    sys.modules['requests'] = types.SimpleNamespace(get=lambda *a, **k: R(eventos))
    picks = [{'partido': 'Atlas vs Club America', 'espn': 'soccer/mex.1:401876932'}]
    check(ia._primer_gol({'partido': 'Atlas vs Club America'}, picks) == 'visita', 'v447: el primer gol real sale de las jugadas de ESPN')
    eventos['keyEvents'][1]['type']['text'] = 'Own Goal'
    check(ia._primer_gol({'partido': 'Atlas vs Club America'}, picks) is None, 'v447: si el primero fue autogol, no se califica')
    check(ia._primer_gol({'partido': 'Atlas vs Club America'}, [{'partido': 'Atlas vs Club America'}]) is None, 'v447: sin ESPN, no se califica')

    # guardar: si falta la columna nueva, se guarda sin ella (primero lo más nuevo)
    llamadas = []

    class P:
        def __init__(self, ok, txt):
            self.ok, self.text, self.status_code = ok, txt, 200 if ok else 400

    def post(url, headers=None, json=None, timeout=None):
        llamadas.append(json)
        return P(len(llamadas) > 1, '' if len(llamadas) > 1 else 'Could not find the column primero_anota')
    sys.modules['requests'] = types.SimpleNamespace(post=post)
    r = ia.guardar(('u', {}), [{'id': 'x', 'primero_anota': 'local', 'prob_primero': .5, 'con_noticias': True}])
    check(r.ok and 'primero_anota' not in llamadas[1][0] and llamadas[1][0].get('con_noticias') is True,
          'v447: sin la migración, se guarda sin quién anota primero (y sin perder lo demás)')

    # ventanas: cada partido con pick, en su hora; nunca dos veces la misma
    ahora = dt.datetime(2026, 10, 22, 12, tzinfo=dt.timezone.utc)
    hora = lambda h: (ahora + dt.timedelta(hours=h)).isoformat()
    picks = [{'partido': 'A vs B', 'fecha': '2026-10-22', 'estado': 'pendiente', 'inicio': hora(2), 'prob': .8},
             {'partido': 'C vs D', 'fecha': '2026-10-22', 'estado': 'pendiente', 'inicio': hora(6), 'prob': .8},
             {'partido': 'E vs F', 'fecha': '2026-10-22', 'estado': 'pendiente', 'inicio': hora(12), 'prob': .8},
             {'partido': 'G vs H', 'fecha': '2026-10-22', 'estado': 'pendiente', 'inicio': hora(2), 'solo_analisis': True},
             {'partido': 'I vs J', 'fecha': '2026-10-22', 'estado': 'pendiente', 'inicio': hora(30), 'prob': .8}]
    ya = ia._id('2026-10-22', 'C vs D') + '|v6'

    class G:
        ok = True

        def json(self):
            return [{'id': ya}]
    sys.modules['requests'] = types.SimpleNamespace(get=lambda *a, **k: G())
    pedidos = []
    viejo_eval, viejo_an = ia.evaluar, ia.analizar
    ia.evaluar = lambda sb, picks: 0
    ia.analizar = lambda sb, lista, mercado, ventana=None: (pedidos.append((sb[0], ventana, [m['partido'] for m in lista])) or (len(lista), False))
    try:
        n = ia.ventanas(('https://x/rest/v1/ia_analisis', {}), picks, ahora, {})
    finally:
        ia.evaluar, ia.analizar = viejo_eval, viejo_an
    check(pedidos == [('https://x/rest/v1/ia_ventanas', 'v12', ['E vs F']), ('https://x/rest/v1/ia_ventanas', 'v2', ['A vs B'])] and n == 2,
          'v447: ~12 h, ~6 h y ~2 h antes, sólo partidos con pick, en la tabla aparte y sin repetir')
    src = open('ia_gemini.py', encoding='utf-8').read()
    check("medidos = 0 if sin_cupo else ventanas(sb, picks, ahora, mercado)" in src and "f['base'], f['id'], f['ventana'] = f['id'], f['id'] + '|' + ventana, ventana" in src,
          'v447: las ventanas corren después del análisis de siempre y sólo si queda cupo')
    sql = open(os.path.join('supabase', 'v447_primero_y_ventanas.sql'), encoding='utf-8').read()
    check('create table if not exists public.ia_ventanas (like public.ia_analisis including all)' in sql
          and 'revoke all on table public.ia_ventanas from public, anon, authenticated' in sql,
          'v447: la tabla de ventanas sólo la ve el servidor')


if __name__ == '__main__':
    probar()
    probar_v447()
    print('\n' + '=' * 40)
    print('TODO OK' if not FALLOS else '%d FALLOS' % len(FALLOS))
    raise SystemExit(1 if FALLOS else 0)
