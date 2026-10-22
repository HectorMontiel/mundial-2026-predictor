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
          and "k not in _V446" in src, 'v446: el análisis recibe las noticias y queda marcado si las usó (y guarda aunque falte la columna)')
    check('noticias_recientes_web' in ia.INSTRUCCION and 'noticias_recientes_web' in ia.instruccion('NBA'),
          'v446: las reglas de la IA dicen que las noticias de la web son datos (en todos los deportes)')
    sql = open(os.path.join('supabase', 'v446_reportes_y_calificaciones.sql'), encoding='utf-8').read()
    check('add column if not exists con_noticias boolean' in sql and 'create or replace function public.resolver_reporte' in sql
          and 'create table if not exists public.ia_calificaciones' in sql and "if v_pagados < 3 then v_monedas := 5; end if;" in sql,
          'v446: la migración nueva (reportes con pago del servidor, calificaciones y columnas de noticias)')


if __name__ == '__main__':
    probar()
    print('\n' + '=' * 40)
    print('TODO OK' if not FALLOS else '%d FALLOS' % len(FALLOS))
    raise SystemExit(1 if FALLOS else 0)
