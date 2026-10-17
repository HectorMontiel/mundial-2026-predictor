#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test de la v384-v385: errores de cuota (💰 Cuota alta) con el filtro medido
en 8 años, el contexto del partido (forma, H2H, bajas), la ayuda y el aviso
de deportes sin pick.

Medido (`_v385_errores_hist.py`, 13.217 errores 2018-2026): se cumplen con la
probabilidad de Pinnacle y ganan +5,6 / +5,7 por $100; empate, cuota > 4 y
ventaja 3-5 % no; forma y H2H no mejoran a Pinnacle.

Ejecutar:  python test_v384.py
"""
import datetime as dt
import json
import os

FALLOS = []


def check(cond, msg):
    print(('OK   ' if cond else 'FALLO') + ' ' + msg)
    if not cond:
        FALLOS.append(msg)


def probar():
    import errores_web as ew
    ahora = dt.datetime(2026, 10, 17, 12, 0, tzinfo=dt.timezone.utc)
    base = {'origen': 'line shopping vs Pinnacle', 'validado': True, 'deporte': 'Fútbol', 'liga': 'X',
            'inicio': '2026-10-17T20:00:00', 'fecha': '2026-10-17'}
    c = [dict(base, partido='A vs B', apuesta='Gana A', cuota=1.80, cuota_justa=1.65, lado='home'),     # p .61, +9 %
         dict(base, partido='C vs D', apuesta='Gana D', cuota=3.30, cuota_justa=2.80, lado='away'),     # p .36, +18 %
         dict(base, partido='E vs F', apuesta='Empate', cuota=3.60, cuota_justa=3.20),                  # empate: fuera
         dict(base, partido='G vs H', apuesta='Gana H', cuota=5.50, cuota_justa=4.60),                  # cuota > 4: fuera
         dict(base, partido='I vs J', apuesta='Gana I', cuota=2.00, cuota_justa=1.94),                  # +3 %: fuera
         dict(base, partido='K vs L', apuesta='Gana K', cuota=2.0, cuota_justa=1.7, validado=False)]    # sin validar: fuera
    e = ew.errores({'capa1': c}, ahora)
    check([x['apuesta'] for x in e] == ['Gana A', 'Gana D'],
          'pasan sólo ventaja ≥ 5 %%, prob ≥ 30 %%, cuota ≤ 4, sin empate y validados (%s)' % [x['apuesta'] for x in e])
    a = e[0]
    check(abs(a['prob'] - 1 / 1.65) < 0.002 and abs(a['ventaja'] - (1.80 / 1.65 - 1)) < 0.002 and a['tipo'] == 'error',
          'la probabilidad es la de Pinnacle sin margen y la ventaja lo que paga de más')
    check(a['gratis'] and not e[1]['gratis'], 'al gratis va el probable (≥ 55 %), no el de cuota 3,30')
    check(e[1]['porque'].startswith('🔥'), 'los patrones fuertes (ventaja ≥ 12 %) llevan 🔥')
    import exportar_web as xw
    check(xw.nivel({'tipo': 'error'}) == 'Cuota alta', 'el error de cuota es el nivel «Cuota alta»')
    os.environ['PREMIUM_NIVELES'] = 'Diamante,Platino,Cuota alta'
    try:
        ps = [dict(x, id=str(i), estado='pendiente') for i, x in enumerate(e)]
        xw.premium(ps)
        check(not ps[0]['premium'] and ps[1]['premium'] and ps[1]['apuesta'].startswith('🔒'),
              'el de muestra para el gratis no se tapa; el resto sí')
    finally:
        os.environ.pop('PREMIUM_NIVELES', None)
    import telegram_canales as tc
    os.environ.pop('TELEGRAM_VIP_NIVELES', None)
    check('Cuota alta' in tc.niveles_vip() and tc.nivel({'tipo': 'error'}) == 'Cuota alta', 'los errores van al VIP')
    a12 = dt.datetime(2026, 10, 17, 18, 30, tzinfo=dt.timezone.utc)   # 12:30 CDMX
    ps = [dict(x, id=str(i), estado='pendiente') for i, x in enumerate(e)]
    g = [t for t, _ in tc.armar_gratis(ps, set(), a12) if 'Error de cuota del día' in t]
    check(len(g) == 1 and 'Gana A' in g[0] and 'Gana D' not in g[0], 'a mediodía, el gratis recibe el error de muestra')
    # contexto
    ctx = ew.contexto({'deporte': 'Fútbol', 'partido': 'Everton vs Chelsea', 'inicio': '2026-10-17 11:30:00'})
    check(ctx is None or (set(ctx) <= {'fl', 'fv', 'sl', 'sv', 'h2h', 'bl', 'bv'} and all(len(x) == 4 for x in ctx.get('h2h', []))),
          'el contexto trae forma, H2H (fecha, local, marcador, visita) y bajas (%s)' % (ctx and list(ctx)))
    check(ew.contexto({'deporte': 'Tenis', 'partido': 'A vs B'}) is None, 'sin contexto fuera del fútbol')
    check(ew._norm('Real Sociedad B') == ew._norm('Sociedad B') and ew._norm('FC Köln') == 'koln',
          'nombres parecidos entre fuentes empatan («Sociedad B» / «Real Sociedad B»)')
    c2 = ew.contexto({'deporte': 'Fútbol', 'partido': 'Sociedad B vs Almeria', 'inicio': '2026-10-17 12:00:00', 'clave_liga': 'esp_hypermotion'})
    check(c2 is None or (c2.get('sl') and c2.get('sv') and len(c2.get('fl', '')) == 5),
          'con la liga, los dos equipos traen forma y promedios (%s)' % (c2 and {k: c2[k] for k in ('fl', 'fv') if k in c2}))
    app = open(os.path.join('web', 'app.js'), encoding='utf-8').read()
    html = open(os.path.join('web', 'index.html'), encoding='utf-8').read()
    check("p.tipo === 'error'" in app and 'function contextoHtml(' in app and "'Cuota alta'" in app,
          'la página tiene el nivel Cuota alta y el contexto del partido')
    check('id="ayuda"' in html and 'data-ayuda' in html and 'De cada 10 como ésta, se cumplen 9' in html,
          'la ayuda explica todo en lenguaje sencillo')
    check('sin_pick' in app and "'meta.json'" in open('exportar_web.py', encoding='utf-8').read(),
          'se avisa cuando un deporte tiene partidos pero ningún pick')
    check('isNaN(d) ? null : d' in app, 'una fecha rara no tumba la página')


if __name__ == '__main__':
    probar()
    print('\n' + '=' * 40)
    print('TODO OK' if not FALLOS else '%d FALLOS' % len(FALLOS))
    raise SystemExit(1 if FALLOS else 0)
