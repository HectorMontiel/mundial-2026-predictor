#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test de la v396: combinadas (por deporte y mixtas), probabilidades de la IA y
los textos sin «segura» ni «se cumplen 9 de 10».

Ejecutar:  python test_v396.py
"""
import datetime as dt
import os

FALLOS = []


def check(cond, msg):
    print(('OK   ' if cond else 'FALLO') + ' ' + msg)
    if not cond:
        FALLOS.append(msg)


def probar_combinadas():
    import combinadas_web as cw
    ahora = dt.datetime(2026, 10, 17, 15, tzinfo=dt.timezone.utc)
    t = lambda h: (ahora + dt.timedelta(hours=h)).strftime('%Y-%m-%d %H:%M:%S')
    def pk(i, dep, cuota, prob, h=2, **k):
        return dict({'id': 'p%d' % i, 'partido': 'A%d vs B%d' % (i, i), 'deporte': dep, 'apuesta': 'Gana A%d' % i,
                     'cuota': cuota, 'prob': prob, 'inicio': t(h), 'estado': 'pendiente', 'tipo': 'pick'}, **k)
    ps = [pk(1, 'Fútbol', 1.15, .88), pk(2, 'Fútbol', 1.18, .86), pk(3, 'Fútbol', 1.20, .84),
          pk(4, 'Tenis', 1.15, .87), pk(5, 'Tenis', 1.17, .85),
          pk(6, 'Fútbol', 1.16, .95, tipo='error'),            # error de cuota: no entra
          pk(7, 'Fútbol', 1.16, .95, h=0.1),                    # empieza ya: no entra
          pk(8, 'Fútbol', 1.16, .70)]                           # prob baja: no entra
    ia = {'A1 vs B1': {'veredictos': [{'apuesta': 'Gana A1', 'opinion': 'en_contra'}]}}
    cs = cw.armar(ps, ia, ahora)
    usados = {x['id'] for c in cs for x in c['patas']}
    check('p1' not in usados, 'una pata que la IA ve en contra no entra')
    check(not usados & {'p6', 'p7', 'p8'}, 'ni errores de cuota, ni lo que ya empieza, ni probabilidad baja')
    al = {(c['alcance'], c['tipo']) for c in cs}
    check(('Fútbol', 'combinada') in al and ('Tenis', 'combinada') in al and ('Mixta', 'combinada') in al,
          'hay combinada por deporte y mixta (%s)' % sorted(al))
    mx = [c for c in cs if c['alcance'] == 'Mixta']
    check(all(len({x['deporte'] for x in c['patas']}) >= 2 for c in mx), 'la mixta lleva 2 deportes o más')
    for c in cs:
        lo, hi = cw.TIPOS[c['tipo']]['cuota']
        pr = 1.0
        for x in c['patas']:
            pr *= x['prob']
        if not (lo <= c['cuota'] <= hi and abs(c['prob'] - pr) < 0.002 and len({x['partido'] for x in c['patas']}) == len(c['patas'])):
            check(False, 'combinada fuera de regla: %s' % c)
            break
    else:
        check(bool(cs), 'cuota dentro del rango, partidos distintos y probabilidad = producto de las patas')
    est = {'a': 'verde', 'b': 'roja', 'c': 'pendiente'}
    check(cw.estado_de([{'id': 'a'}, {'id': 'b'}], est) == 'roja' and cw.estado_de([{'id': 'a'}], est) == 'verde'
          and cw.estado_de([{'id': 'a'}, {'id': 'c'}], est) == 'vivo', 'verde sólo si todas; roja si falla una')
    x = open('exportar_web.py', encoding='utf-8').read()
    check('combinadas_web.subir' in x and "_real=reales.get" in x, 'la exportación sube las combinadas (con el texto real sólo para la IA)')


def probar_ia_y_textos():
    import ia_gemini as ia
    check({'prob_goles', 'prob_ambos_anotan', 'prob_corners', 'prob_tarjetas', 'prob_marcador'} <= set(ia.ESQUEMA['required']),
          'la IA da la probabilidad de cada predicción')
    m = {'id': 'x', 'fecha': '2026-10-17', 'inicio': '2026-10-17 20:00:00', 'partido': 'A vs B', 'picks': []}
    f = ia.fila(m, {'partido': 'A vs B', 'p_local': .5, 'p_empate': .3, 'p_visita': .2, 'prob_goles': 0.62, 'prob_ambos_anotan': 55}, {})
    check(f['prob_goles'] == 0.62 and f['prob_ambos'] == 0.55, 'y se guarda de 0 a 1')
    app = open(os.path.join('web', 'app.js'), encoding='utf-8').read()
    html = open(os.path.join('web', 'index.html'), encoding='utf-8').read()
    check('class="ia-prob">probabilidad' in app, 'la página enseña esas probabilidades')
    check("'De cada 10'" not in app and 'Se cumplen</small>' not in app and "<span>acierta '" not in app,
          'las tarjetas dicen «Probabilidad» y «Nivel», no «se cumplen» ni «9 de 10»')
    check('De cada 10 como ésta, se cumplen 9' not in html and 'muy segura' not in html and '— segura' not in html
          and 'ninguna apuesta es segura' in html, 'la ayuda habla de probabilidad, nunca de «segura»')
    check('id="combinadas-lista"' in html and 'id="comb-hist"' in html and 'function tarjetaCombinada(' in app,
          'la página tiene combinadas y su historial')
    tg = open('telegram_canales.py', encoding='utf-8').read()
    check('acierta %d' not in tg and 'acierta ~%d' not in tg, 'Telegram también dice probabilidad')
    check(os.path.exists(os.path.join('supabase', 'v396_combinadas.sql')), 'el SQL está guardado')


def probar_desbloquear_combinada():
    """v397 — la combinada entera con monedas, «No Win, No Pay», y lo pagado no se rehace."""
    sql = open(os.path.join('supabase', 'v397_desbloquear_combinada.sql'), encoding='utf-8').read()
    check('function public.desbloquear_combinada' in sql and 'least(public.precio_por_cuota(c.cuota), suelto)' in sql,
          'el precio es el de la cuota total (o lo que falte, si es menos)')
    check("'ya empezó'" in sql and 'devolver_combinada_si_falla' in sql and "new.estado in ('roja', 'nula')" in sql,
          'sólo antes de empezar, y si sale roja se devuelven las monedas')
    cw = open('combinadas_web.py', encoding='utf-8').read()
    check("'desbloqueos_combinada'" in cw and "c['id'] in pagadas and not empezo(c)" in cw,
          'una combinada que alguien pagó no se rehace ni se borra')
    cu = open(os.path.join('web', 'cuenta.js'), encoding='utf-8').read()
    app = open(os.path.join('web', 'app.js'), encoding='utf-8').read()
    check("sb.rpc('desbloquear_combinada'" in cu and 'Desbloquear la combinada por' in cu and 'SPX.extraComb(c)' in app,
          'la tarjeta de la combinada tiene su botón de desbloquear')


if __name__ == '__main__':
    probar_desbloquear_combinada()
    probar_combinadas()
    probar_ia_y_textos()
    print('\n' + '=' * 40)
    print('TODO OK' if not FALLOS else '%d FALLOS' % len(FALLOS))
    raise SystemExit(1 if FALLOS else 0)
