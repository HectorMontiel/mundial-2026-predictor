#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test de la v394: la IA en todos los partidos, qué metería, y la página.

POR QUÉ (17-oct): la IA sólo había analizado unos pocos partidos. El nivel
gratis de Gemini cuenta consultas por día y por modelo; se hacía una por
partido y, al primer «429» del primer modelo, se paraba la pasada entera
aunque los otros modelos tuvieran cupo. Ahora van 5 partidos por consulta y
un 429 pasa al siguiente modelo.

Ejecutar:  python test_v394.py
"""
import os

FALLOS = []


def check(cond, msg):
    print(('OK   ' if cond else 'FALLO') + ' ' + msg)
    if not cond:
        FALLOS.append(msg)


class _R:
    def __init__(self, code, txt=''):
        self.status_code, self.ok, self._t = code, code == 200, txt

    def json(self):
        return {'candidates': [{'content': {'parts': [{'text': self._t}]}}]}


def probar_ia():
    import json
    import requests
    import ia_gemini as ia
    check(ia.LOTE >= 3 and 'partidos' in ia.ESQUEMA_LOTE['properties'], 'varios partidos por consulta')
    check({'mejor_apuesta', 'prob_mejor_apuesta', 'goles_local_esperados', 'goles_visita_esperados'}
          <= set(ia.ESQUEMA['required']), 'la IA dice qué metería y los goles de cada equipo')
    llamados = []
    resp = json.dumps({'partidos': [{'partido': 'A vs B', 'analisis': 'x', 'mejor_apuesta': 'Gana A',
                                     'prob_mejor_apuesta': 72}]})

    def falso(url, **kw):
        llamados.append(url.split('/models/')[1].split(':')[0])
        return _R(429) if len(llamados) == 1 else _R(200, resp)

    viejo, os.environ['GEMINI_API_KEY'] = requests.post, os.environ.get('GEMINI_API_KEY', 'x') or 'x'
    requests.post = falso
    ia._AGOTADOS.clear()
    try:
        r = ia.preguntar([{'partido': 'A vs B'}])
    finally:
        requests.post = viejo
    check(len(llamados) == 2 and llamados[0] != llamados[1] and r and 'A vs B' in r,
          'un 429 pasa al siguiente modelo en vez de parar la pasada (%s)' % llamados)
    ia._AGOTADOS.update(ia.MODELOS)
    check(ia.preguntar([{'partido': 'A vs B'}]) == {'_limite': True}, 'sólo se para cuando TODOS agotaron su cupo')
    ia._AGOTADOS.clear()
    m = {'id': 'x', 'fecha': '2026-10-17', 'inicio': '2026-10-17 20:00:00', 'partido': 'A vs B', 'picks': []}
    f = ia.fila(m, dict(r['A vs B'], p_local=.5, p_empate=.3, p_visita=.2), {})
    check(f['mejor_apuesta'] == 'Gana A' and f['prob_mejor_apuesta'] == 0.72, 'la probabilidad en % se guarda como 0-1')


def probar_pagina():
    app = open(os.path.join('web', 'app.js'), encoding='utf-8').read()
    check("estado.fase === 'todos' ? faseDe(g) !== 'terminado' : faseDe(g) === estado.fase" in app,
          'los destacados siguen el filtro Próximos / Vivo / Final')
    check('AVISO_SIN_STATS' in app and "v.fase === 'in' && statsVacias(v)" in app,
          'sin estadísticas de ESPN se avisa en vez de pintar ceros')
    check('Lo que metería la IA' in app and ("filaStat('Goles esperados'" in app or "' esperados', a.goles_local_esperados" in app) and 'Lo que usó' not in app,
          'el análisis IA trae qué metería y goles por equipo (v468: sin repetir los promedios de «Antes del partido»)')
    check(os.path.exists(os.path.join('supabase', 'v394_ia_que_meter.sql')), 'el SQL de las columnas nuevas está guardado')


if __name__ == '__main__':
    probar_ia()
    probar_pagina()
    print('\n' + '=' * 40)
    print('TODO OK' if not FALLOS else '%d FALLOS' % len(FALLOS))
    raise SystemExit(1 if FALLOS else 0)
