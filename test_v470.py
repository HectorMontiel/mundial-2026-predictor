#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v470-v471 — secciones dentro de «Antes del partido» y del «Análisis IA», ⭐ ligas favoritas
(el resto de la A a la Z), líneas por estadística medidas, y «Arma tu combinada»."""
import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
FALLOS = []


def check(cond, msg):
    print(('OK   ' if cond else 'FALLO') + ' ' + msg)
    if not cond:
        FALLOS.append(msg)


def probar():
    import pandas as pd
    import lineas_stats as ls
    cal = json.load(open(ls.CAL, encoding='utf-8'))
    claves = {k for k in cal if k != 'alpha'}
    check(claves == {'%s_%s_%s' % x for x in ls.VALE}, 'v470: calibración sólo de lo que ganó a la media de la liga')
    check(not any(k.startswith('amarillas') or k.startswith('goles_total') or k.startswith('corners_total') for k in claves)
          and ('tiros_puerta', 'total', 'mas') not in ls.VALE,
          'v470: amarillas, goles totales, córners totales y tiros a puerta totales «más» NO se enseñan (no ganaron)')
    # un histórico de juguete: A tira muchos córners, B concede muchos
    filas = []
    d0 = dt.datetime(2026, 1, 1)
    for i in range(80):
        a, b = ('A', 'B') if i % 4 == 0 else (('C', 'D') if i % 4 == 1 else (('A', 'C') if i % 4 == 2 else ('D', 'B')))
        filas.append({'date': d0 + dt.timedelta(days=i), 'home_team': a, 'away_team': b,
                      'home_goals': 2 if a == 'A' else 1, 'away_goals': 1,
                      'home_corners': 9 if a == 'A' else 5, 'away_corners': 6 if b == 'B' else 4,
                      'home_shots_on': 7 if a == 'A' else 4, 'away_shots_on': 3, 'home_shots_off': 8, 'away_shots_off': 6})
    h = pd.DataFrame(filas)
    lin = ls.calcular(h, 'A', 'B', pd.Timestamp('2026-06-01'))
    check(lin and 'corners' in lin and lin['corners']['lam'][0] > lin['corners']['lam'][1], 'v470: λ por equipo con su ataque y la defensa del rival')
    xs = lin['corners']['h']
    check(all(0.60 <= p <= 0.93 for _, _, p in xs) and [t for t, _, _ in xs].count('mas') <= 2 and [t for t, _, _ in xs].count('menos') <= 1,
          'v470: hasta 2 «más de» y 1 «menos de», todas entre 60 y 93 %')
    check(not lin['corners']['t'] and not lin.get('amarillas'), 'v470: sin córners totales ni amarillas')
    check(ls.calcular(h.head(6), 'A', 'B', pd.Timestamp('2026-06-01')) is None, 'v470: con pocos partidos no se inventa nada')
    ew = open('errores_web.py', encoding='utf-8').read()
    check("lin = lineas_stats.calcular(h, home, away, antes, casa)" in ew and "ctx['lin'] = lin" in ew, 'v470: las líneas van en el contexto del partido')

    app = open(os.path.join('web', 'app.js'), encoding='utf-8').read()
    css = open(os.path.join('web', 'estilo.css'), encoding='utf-8').read()
    check("const sub = (titulo, cuerpo)" in app and "sub('Forma · últimos 5'" in app and "sub('Promedios · últimos '" in app
          and "sub('Enfrentamientos · '" in app and '.ctx details.sub > summary' in css,
          'v470: «Antes del partido» en secciones que se abren')
    ia = app[app.index('function iaHtml('):app.index('function iaHtml(') + 9000]
    check(all(("sub('%s'" % t) in ia for t in ('Predicciones', 'Primer gol y PA1', 'Jugadores', 'Líneas por estadística', 'Nuestros picks según la IA', 'Noticias')),
          'v470: el «Análisis IA» en secciones (lo principal a la vista)')
    check("amarillas" not in app[app.index('const LIN_NOM'):app.index('const LIN_NOM') + 200], 'v470: la página no pinta amarillas en las líneas')
    check("estado.ligasFav.has(l) ? 1 : 0" in app and "data-fav=" in app and "localStorage.setItem('sp_ligas_fav'" in app and '.fav.si' in css,
          'v470: ⭐ ligas favoritas arriba; el resto de la A a la Z (ya no suben solas las de sus intereses)')
    check('function armarCombinada(pasaDep)' in app and "if (v === 'contra') { fuera.push(p); continue; }" in app
          and 'Math.min(20, estado.arm.n' in app and 'Math.max(2,' in app and "SPX.ponerBoleto(" in app,
          'v471: «Arma tu combinada»: niveles, 2-20 patas, el modelo elige y la IA descarta lo que ve en contra')
    # v472 — el parley del mismo partido con las líneas de la casa
    casa = {'corners_home': {'3.5': {'mas': 1.25}, '5.5': {'mas': 1.6}, '9.5': {'mas': 4.0}, '6': {'mas': 1.9}},
            'goles_home': {'0.5': {'mas': 1.1}}, 'remates': {'20.5': {'mas': 1.3}}, 'tarjetas_home': {'0.5': {'mas': 1.05}}}
    lin2 = ls.calcular(h, 'A', 'B', pd.Timestamp('2026-06-01'), casa)
    par = (lin2 or {}).get('par') or []
    check(par and all(x[3] >= ls.P_POZO for x in par) and all(x[2] % 1 == 0.5 for x in par)
          and not any(x[0] == 'amarillas' for x in par), 'v472: patas sólo con líneas de la casa (medias), prob >= 60 %%, sin tarjetas: %s' % par)
    # v474 — las líneas, SINCRONIZADAS con lo que la casa deja meter
    ofrecidas = {('corners', 'h'): {3.5, 5.5, 9.5}, ('goles', 'h'): {0.5}}
    check(lin2.get('casa') is True and all(x[1] in ofrecidas[(st, 'h')] and len(x) == 4
                                           for st in ('corners', 'goles') for x in (lin2.get(st) or {}).get('h', [])),
          'v474: con Playdoit, sólo SUS líneas (con su cuota); nada de «más de 2.5» si la casa empieza en 4')
    check(not (lin2.get('corners') or {}).get('a') and not (lin2.get('tiros_puerta') or {}).get('h'),
          'v474: lo que la casa no ofrece no se enseña')
    check(lin.get('casa') is False, 'v474: sin Playdoit, nuestras líneas como referencia (y se dice)')
    check("data-par-n=\"3\">' + ico('target') + ' Armar parley</button>'" in app and "estado.parley[t.dataset.parK] = Number(t.dataset.parN) || 3" in app
          and "[2, 3, 4].map" in app, 'v474: el botón «Armar parley» (2, 3 o 4 patas) siempre sale')
    check("def casa_del_partido(home: str, away: str, clave: Optional[str]) -> Dict:" in ew and 'escudos._puntos(home, away' in ew,
          'v474: el tablero de la casa se encuentra aunque lo llame distinto («1. FC Nurnberg»)')
    cor = [x for x in par if x[0] == 'corners']
    check(cor and cor[0][2] in (3.5, 5.5) and cor[0][4] in (1.25, 1.6), 'v472: de cada estadística, la línea MÁS ALTA de la casa que pasa el 75 %%, con su cuota')
    check(ls.CORR == {2: 1.04, 3: 1.067, 4: 1.13} and 'const PAR_CORR = { 2: 1.04, 3: 1.067, 4: 1.13 }' in app,
          'v472: la probabilidad conjunta con la corrección medida (las patas del mismo partido van juntas)')
    check("sub('Arma tu parley de este partido', parleyHtml(ctx, L, V))" in app and 'casa_del_partido(home, away, clave)' in ew,
          'v472: «Arma tu parley de este partido» dentro del análisis IA, con Playdoit')
    check("const armNiveles = () => (armVip() ? estado.arm.niv : new Set(['Oro']));" in app and "if (!armVip() && n !== 'Oro') return;" in app,
          'v473: el gratis arma sólo con Oro; los demás niveles con candado (VIP)')
    cu = open(os.path.join('web', 'cuenta.js'), encoding='utf-8').read()
    html = open(os.path.join('web', 'index.html'), encoding='utf-8').read()
    check('window.SPX.ponerBoleto' in cu and 'id="armador" data-vista="combinadas"' in html, 'v471: pasa a «Tu combinada» para guardarla')
    check('Arma tu parley con la IA' in html and 'Combinadas de 2 a 20 patas' in html, 'v473: el plan VIP dice lo nuevo, breve')


if __name__ == '__main__':
    probar()
    print('\n' + '=' * 40)
    print('TODO OK' if not FALLOS else '%d FALLOS' % len(FALLOS))
    raise SystemExit(1 if FALLOS else 0)
