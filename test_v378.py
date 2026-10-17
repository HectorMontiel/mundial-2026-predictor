#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test de la v378: el sitio web EN VIVO (estadísticas tipo SofaScore).

  1. `espn_vivo` empareja cada pick con su partido de ESPN por hora y nombres
     (también con nombres cortos: «Wolves» / «Wolverhampton») y sabe cuándo
     nuestro «A vs B» va al revés que ESPN.
  2. Nunca pide un rango de fechas con guion (ESPN devuelve 0 sin error).
  3. La página lee el en vivo de ESPN, tiene la ficha del partido, niveles,
     simulador de banca y se puede instalar (manifest + service worker).
  4. La clave secreta nunca va en la página.

Ejecutar:  python test_v378.py
"""
import datetime as dt
import os

FALLOS = []


def check(cond, msg):
    print(('OK   ' if cond else 'FALLO') + ' ' + msg)
    if not cond:
        FALLOS.append(msg)


def probar():
    import espn_vivo as ev
    ini = dt.datetime(2026, 10, 17, 14, 0, tzinfo=dt.timezone.utc)
    falsos = {('soccer/all', '20261017'): [
        {'id': '1', 'inicio': ini, 'home': 'Burnley', 'away': 'Wolverhampton Wanderers', 'logo_h': 'b.png', 'logo_a': 'w.png'},
        {'id': '2', 'inicio': ini, 'home': 'Arsenal', 'away': 'Chelsea', 'logo_h': 'a.png', 'logo_a': 'c.png'}],
        ('soccer/all', '20261016'): []}
    v = ev.eventos
    pedidas = []
    ev.eventos = lambda ruta, dia: pedidas.append(dia) or falsos.get((ruta, dia), [])
    try:
        ps = [{'deporte': 'Fútbol', 'partido': 'Burnley vs Wolves', 'inicio': '2026-10-17 14:00:00'},
              {'deporte': 'Fútbol', 'partido': 'Chelsea vs Arsenal', 'inicio': '2026-10-17 14:05:00'},
              {'deporte': 'Fútbol', 'partido': 'Real Madrid vs Getafe', 'inicio': '2026-10-17 14:00:00'},
              {'deporte': 'Tenis', 'partido': 'A vs B', 'inicio': '2026-10-17 14:00:00'}]
        n = ev.emparejar(ps)
        check(n == 2 and ps[0].get('espn') == 'soccer/all:1' and not ps[0]['girado'],
              'empareja con nombre corto («Wolves») a la misma hora (%s)' % ps[0])
        check(ps[1].get('espn') == 'soccer/all:2' and ps[1]['girado'] and ps[1]['logo_h'] == 'c.png',
              'sabe que «Chelsea vs Arsenal» va al revés que ESPN y voltea los escudos')
        check('espn' not in ps[2] and 'espn' not in ps[3], 'sin partido parecido o sin ESPN (tenis), no inventa')
        check(all('-' not in d and len(d) == 8 for d in pedidas), 'pide día por día, nunca un rango con guion')
    finally:
        ev.eventos = v
    check(ev._parecido('Ein Frankfurt', 'Eintracht Frankfurt') < 1 and ev._norm('FC Köln') == 'koln',
          'normaliza acentos y quita «FC»')
    js = open(os.path.join('web', 'app.js'), encoding='utf-8').read()
    check('site.api.espn.com' in js and '/summary?event=' in js and 'setInterval(vivo, 30 * 1000)' in js,
          'la página lee el en vivo de ESPN cada 30 s')
    check('function ficha(' in js and 'function filaStat(' in js and 'function posesion(' in js
          and 'function simular(' in js and 'function nivel(' in js,
          'ficha del partido con barras tipo SofaScore, niveles y simulador de banca')
    html = open(os.path.join('web', 'index.html'), encoding='utf-8').read()
    check('manifest.json' in html and 'sw.js' in html and os.path.exists(os.path.join('web', 'sw.js')),
          'se puede instalar en el celular')
    cfg = open(os.path.join('web', 'config.js'), encoding='utf-8').read()
    check('sb_secret_' not in cfg.replace('(sb_secret_…)', '') and 'eyJ' not in cfg,
          'en la página sólo va la clave pública')
    import exportar_web as ew
    check('espn' in ew.CAMPOS and 'girado' in ew.CAMPOS, 'el pick sube con su partido de ESPN')


if __name__ == '__main__':
    probar()
    print('\n' + '=' * 40)
    print('TODO OK' if not FALLOS else '%d FALLOS' % len(FALLOS))
    raise SystemExit(1 if FALLOS else 0)
