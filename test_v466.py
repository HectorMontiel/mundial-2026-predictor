#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v466 — «de pasado mañana sólo me salen dos partidos y también juega el Barcelona contra el
Real Madrid; no quiero faltantes». Causa raíz: la base entrega como MÁXIMO 1000 filas por
consulta aunque la página pidiera «limit=5000»; con 1157 picks en la ventana, los 157 últimos
(los de pasado mañana) no llegaban. Y los partidos sin pick de «Pasado» desde las 18:00 de
México se quedaban fuera porque el corte usaba la fecha en UTC."""
import datetime as dt
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
FALLOS = []


def check(cond, msg):
    print(('OK   ' if cond else 'FALLO') + ' ' + msg)
    if not cond:
        FALLOS.append(msg)


def probar():
    js = {n: open(os.path.join('web', n), encoding='utf-8').read() for n in os.listdir('web') if n.endswith('.js')}
    altos = [(n, m) for n, s in js.items() for m in re.findall(r"limit=(\d+)|\.limit\((\d+)\)", s)
             if int(m[0] or m[1]) > 1000 and not re.search(r"//[^\n]*" + re.escape(m[0] or m[1]), s)]
    check(not altos, 'v466: ninguna consulta pide más de 1000 filas de golpe (la base corta en 1000 sin avisar): %s' % altos)
    app, cta = js['app.js'], js['cuenta.js']
    check("todasLasFilas(C.SUPABASE_URL.replace(/\\/$/, '') + '/rest/v1/picks?" in app
          and "todasLasFilas(C.SUPABASE_URL.replace(/\\/$/, '') + '/rest/v1/combinadas?" in app,
          'v466: los picks y las combinadas se piden por páginas')
    check("Prefer: 'count=exact'" in app and "throw new Error('faltan filas: '" in app,
          'v466: se comprueba contra el total de la base; si falta alguna, se usa el respaldo completo')
    check(len(re.findall(r"rest/v1/[a-z_]+\?", app)) == app.count("todasLasFilas(C.SUPABASE_URL"),
          'v466: TODA consulta directa a la base en app.js pasa por la paginación')
    for t in ('ia_disponibles', 'ia_analisis', 'seguidores', 'telegram_publicados'):
        check(re.search(r"todasSb\(\([a-z], [a-z]\) => sb\.from\('%s'\)[^\n]*\.range\(" % t, cta) is not None,
              'v466: %s se pide por páginas' % t)

    import exportar_web as ew
    check(ew._dia_mx({'inicio': '2026-10-26 00:06:00', 'fecha': '2026-10-26'}) == '2026-10-25'
          and ew._dia_mx({'inicio': '2026-10-25T20:00:00+00:00'}) == '2026-10-25',
          'v466: el día es el de México (Tigres-Monterrey 18:06 del 25 es del 25, no del 26)')
    prons = [{'partido': 'Tigres vs Monterrey', 'fecha': '2026-10-26', 'inicio': '2026-10-26 00:06:00', 'deporte': 'Fútbol',
              'liga': 'Liga MX Femenil', 'apuesta': 'Gana Tigres', 'prob': 0.53},
             {'partido': 'Sevilla vs Osasuna', 'fecha': '2026-10-26', 'inicio': '2026-10-26 20:00:00', 'deporte': 'Fútbol',
              'liga': 'LaLiga', 'apuesta': 'Gana Sevilla', 'prob': 0.5}]
    an = ew.solo_analisis(prons, [], [], dt.date(2026, 10, 23))
    check([a['partido'] for a in an] == ['Tigres vs Monterrey'],
          'v466: el partido sin pick de la noche de «Pasado» sale; el del día siguiente, todavía no')

    # COBERTURA con el precálculo real: cada partido de hoy, mañana y pasado (en México) tiene
    # tarjeta, sea pick o sólo análisis. Si el precálculo local es de otro día, la ventana es la suya.
    import precalculo_dia as pc
    import modo_modelo as mm
    doc = pc.leer() or {}
    pr = (doc.get('datos') or {}).get('pronosticos') or []
    if pr:
        gen = dt.datetime.fromisoformat(str(doc.get('generado') or doc.get('ts') or '').replace('Z', '+00:00')) \
            if (doc.get('generado') or doc.get('ts')) else dt.datetime.now(dt.timezone.utc)
        gen = gen if gen.tzinfo else gen.replace(tzinfo=dt.timezone.utc)
        hoy = gen.astimezone(dt.timezone(dt.timedelta(hours=-6))).date()
        prox = [ew._fila(p, 'pendiente') for p in mm.lista_por_acierto(pr) if not p.get('sigue')]
        an = ew.solo_analisis(pr, prox, [], hoy)
        hay = {(ew._dia_mx(f), f['partido']) for f in prox + an}
        lim = (hoy + dt.timedelta(days=ew.DIAS_ANALISIS - 1)).isoformat()
        sin = [(ew._dia_mx(p), p.get('partido')) for p in pr if not p.get('sigue') and not p.get('jugado')
               and ' vs ' in str(p.get('partido')) and hoy.isoformat() <= ew._dia_mx(p) <= lim
               and (ew._dia_mx(p), p.get('partido')) not in hay]
        check(not sin, 'v466: TODOS los partidos del precálculo (hoy, mañana y pasado) tienen tarjeta: faltan %d %s' % (len(sin), sin[:5]))


if __name__ == '__main__':
    probar()
    print('\n' + '=' * 40)
    print('TODO OK' if not FALLOS else '%d FALLOS' % len(FALLOS))
    raise SystemExit(1 if FALLOS else 0)
