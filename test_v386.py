#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test de la v386-v387: errores de cuota uno por partido y con su marcador
aparte; la IA (Gemini) que analiza, predice y se mide contra el favorito.

Ejecutar:  python test_v386.py
"""
import datetime as dt
import os

FALLOS = []


def check(cond, msg):
    print(('OK   ' if cond else 'FALLO') + ' ' + msg)
    if not cond:
        FALLOS.append(msg)


def probar():
    import errores_web as ew
    base = {'origen': 'line shopping vs Pinnacle', 'validado': True, 'deporte': 'Fútbol', 'liga': 'X',
            'inicio': '2026-10-17T20:00:00', 'fecha': '2026-10-17'}
    c = [dict(base, partido='Gomora vs Cape Town City', apuesta='Gana Cape Town City', cuota=2.45, cuota_justa=2.25),
         dict(base, partido='Gomora vs Cape Town City', apuesta='Gana Gomora', cuota=3.0, cuota_justa=2.44),
         dict(base, partido='Ayr vs Partick', apuesta='Gana Partick', cuota=1.83, cuota_justa=1.70),
         dict(base, partido='Ayr vs Partick Thistle', apuesta='Gana Partick Thistle', cuota=1.83, cuota_justa=1.70)]
    e = ew.errores({'capa1': c}, dt.datetime(2026, 10, 17, 12, tzinfo=dt.timezone.utc))
    check(len(e) == 2 and {x['apuesta'] for x in e} >= {'Gana Cape Town City'},
          'uno por partido: no los dos lados ni el mismo partido con dos nombres (%s)' % [x['apuesta'] for x in e])

    import ia_gemini as ia
    ahora = dt.datetime(2026, 10, 17, 12, tzinfo=dt.timezone.utc)
    picks = [{'deporte': 'Fútbol', 'estado': 'pendiente', 'inicio': '2026-10-17 20:00:00', 'fecha': '2026-10-17',
              'partido': 'A vs B', 'apuesta': 'Gana A', 'prob': 0.86, 'elige': True},
             {'deporte': 'Fútbol', 'estado': 'pendiente', 'inicio': '2026-10-17 20:00:00', 'fecha': '2026-10-17',
              'partido': 'C vs D', 'apuesta': 'Goles: Menos de 4.5', 'prob': 0.8},
             {'deporte': 'Tenis', 'estado': 'pendiente', 'inicio': '2026-10-17 20:00:00', 'fecha': '2026-10-17',
              'partido': 'E vs F', 'apuesta': 'Gana E', 'prob': 0.9},
             {'deporte': 'Fútbol', 'estado': 'pendiente', 'inicio': '2026-10-20 20:00:00', 'fecha': '2026-10-20',
              'partido': 'G vs H', 'apuesta': 'Gana G', 'prob': 0.9}]
    ps = ia.partidos(picks, ahora)
    # v407 — ahora TODOS los deportes y 72 h (hoy, mañana y pasado); lo de las
    # próximas 24 h primero y, dentro, lo más importante primero
    check([m['partido'] for m in ps][:2] == ['A vs B', 'E vs F'] and set(m['partido'] for m in ps) == {'A vs B', 'C vs D', 'E vs F'},
          'la IA analiza todos los deportes de las próximas 72 h, lo más importante primero (%s)' % [m['partido'] for m in ps])
    d = ia.datos_del_partido(ps[0], {'A vs B': {'1x2': {'home': 0.6, 'draw': 0.25, 'away': 0.15}, 'mas25': 0.5}})
    check(d['probabilidades_del_mercado_sin_margen']['home'] == 0.6 and d['nuestros_picks'][0]['apuesta'] == 'Gana A',
          'a la IA se le da el mercado y nuestros picks')
    f = ia.fila(ps[0], {'analisis': 'x', 'p_local': 2, 'p_empate': 1, 'p_visita': 1, 'pred_goles': 'mas',
                        'confianza': 9, 'pick_ia': 'Gana A', 'coincide': True, '_modelo': 'm'},
                {'A vs B': {'1x2': {'home': 0.6, 'draw': 0.25, 'away': 0.15}}})
    check(abs(f['p_local'] - 0.5) < 1e-6 and f['pred_resultado'] == 'local' and f['confianza'] == 5
          and f['p_mercado_local'] == 0.6, 'sus probabilidades se normalizan y se guarda el mercado para compararla')
    check(ia._final('A vs B', '2026-10-17', [{'partido': 'A vs B', 'estado': 'verde', 'marcador': '2-1'}]) == (2, 1),
          'el marcador final sale de nuestros picks ya liquidados')
    check('Usa SÓLO esos datos' in ia.INSTRUCCION and "'responseSchema'" in open('ia_gemini.py', encoding='utf-8').read(),
          'la IA no inventa datos y responde en JSON')
    for k in ('GEMINI_API_KEY', 'SUPABASE_URL', 'SUPABASE_SERVICE_KEY'):
        os.environ.pop(k, None)
    check(ia.preguntar({}) is None, 'sin clave de Gemini no se llama a nada')
    wf = open(os.path.join('.github', 'workflows', 'sitio_web.yml'), encoding='utf-8').read()
    check('python ia_gemini.py' in wf, 'la IA corre en el envío automático')
    app = open(os.path.join('web', 'app.js'), encoding='utf-8').read()
    cu = open(os.path.join('web', 'cuenta.js'), encoding='utf-8').read()
    check("p.tipo !== 'error'" in app and 'Cuota alta: ✅' in app and 'function iaHtml(' in app,
          'la página separa el marcador de los errores y enseña la IA')
    check("from('ia_aciertos')" in cu and 'Elegir al favorito' in cu and "from('ia_analisis')" in cu and "$('ia-hist')" in cu,
          'el historial mide a la IA contra elegir al favorito (y sale siempre)')
    src = open('ia_gemini.py', encoding='utf-8').read()
    check("'enum': ['a_favor', 'en_contra']" in src and "'veredictos': vs" in src and 'function iaDelPick(' in app,
          'la IA dice a favor o en contra de cada pick, se mide, y se avisa en la fila')
    check("'pred_corners'" in src and "'pred_tarjetas'" in src and "'marcador_probable'" in src and 'def _corners_tarjetas(' in src,
          'la IA da marcador, córners y tarjetas, y se miden contra lo real')
    check(ia._linea(9.2) == 9.5 and ia._linea(4) == 4.5 and ia._linea(None) is None, 'las líneas de la IA siempre son .5')


if __name__ == '__main__':
    probar()
    print('\n' + '=' * 40)
    print('TODO OK' if not FALLOS else '%d FALLOS' % len(FALLOS))
    raise SystemExit(1 if FALLOS else 0)
