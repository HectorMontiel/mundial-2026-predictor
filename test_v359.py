#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test de la v359.

El usuario: «agrega la NHL, con todo lo de contra la casa, nuestro método,
para seguir ganando».

Lo que se vigila:
  1. LO MEDIDO (`nhl_lineas.json`): las líneas al 78 % aciertan ~82 % al
     juzgar; la Capa 1 (85 %) ~89 %; el ganador con la casa ≥ 75 %, ~79 %.
  2. EL TABLERO de Playdoit («EDM Oilers», «Hándicap (incl. prórroga y
     penaltis)», «Totales (incl. …)») con nuestros nombres.
  3. LA TARJETA: se meten las de ≥ 78 % con cuota ≥ 1,15; el ganador con la
     casa ≥ 75 % y no en pretemporada; la Capa 1; y se liquida.
  4. LOS MARCADORES de ESPN, día por día (con rango devuelve 0 sin error).

Ejecutar:  python test_v359.py
"""
import json

FALLOS = []


def check(cond, msg):
    print(('OK   ' if cond else 'FALLO') + ' ' + msg)
    if not cond:
        FALLOS.append(msg)


def probar_medicion():
    d = json.load(open('nhl_lineas.json', encoding='utf-8'))
    r = d['reglas']
    m78, m85 = r['meta78'], r['meta85']
    check(m78['elige']['acierta'] >= 0.80 and m78['juzga']['acierta'] >= 0.80
          and m78['juzga']['p5'] >= 0.80,
          'meta 78 %%: elegir %.1f %%, juzgar %.1f %% (p5 %.1f)'
          % (100 * m78['elige']['acierta'], 100 * m78['juzga']['acierta'], 100 * m78['juzga']['p5']))
    check(all(v[1] >= 0.79 for v in m78['juzga']['por_tipo'].values()),
          'los cuatro lados aguantan al juzgar (%s)' % m78['juzga']['por_tipo'])
    check(m85['juzga']['acierta'] >= 0.87, 'la Capa 1 (85 %%) acierta %.1f %% al juzgar'
          % (100 * m85['juzga']['acierta']))
    g = [b for b in d['ganador']['juzga'] if b['banda'] in ('(0.75, 0.8]', '(0.8, 1.0]')]
    n = sum(b['n'] for b in g)
    ac = sum(b['n'] * b['acierta'] for b in g) / n
    check(ac >= 0.78, 'el ganador con la casa ≥ 75 %% acierta %.1f %% (%d partidos, 2019-25)' % (100 * ac, n))
    pm = d['pretemporada_mitades']
    check(all(v[1] >= 0.78 for x in pm.values() for v in x['por_tipo'].values()),
          'pretemporada: los cuatro lados aguantan en las dos mitades')


DET = {'mercados': [
    {'nombre': 'Ganador (incl. prórroga y penaltis)', 'selecciones': [
        {'nombre': 'EDM Oilers', 'cuota': 1.6667}, {'nombre': 'SJ Sharks', 'cuota': 2.25}]},
    {'nombre': 'Hándicap (incl. prórroga y penaltis)', 'selecciones': [
        {'nombre': 'EDM Oilers (+2.5)', 'cuota': 1.125}, {'nombre': 'EDM Oilers (+1.5)', 'cuota': 1.2858},
        {'nombre': 'SJ Sharks (+2.5)', 'cuota': 1.2353}, {'nombre': 'SJ Sharks (+3.5)', 'cuota': 1.0834},
        {'nombre': 'SJ Sharks (+1.5)', 'cuota': 1.5}]},
    {'nombre': 'Hándicap 1x2', 'selecciones': [{'nombre': 'EDM Oilers (0:2)', 'cuota': 1.2667}]},
    {'nombre': 'Totales (incl. prórroga y penaltis)', 'selecciones': [
        {'nombre': 'Más de 6.5', 'cuota': 1.7693}, {'nombre': 'Menos de 6.5', 'cuota': 2.1},
        {'nombre': 'Más de 4.5', 'cuota': 1.1539}, {'nombre': 'Más de 5.5', 'cuota': 1.4445},
        {'nombre': 'Menos de 8.5', 'cuota': 1.2858}]},
    {'nombre': 'Total EDM Oilers (incl. prórroga y penaltis)', 'selecciones': [
        {'nombre': 'Más de 1.5', 'cuota': 1.1}]}]}
PAR = 'San Jose Sharks vs Edmonton Oilers'


def probar_tablero():
    import nhl_lineas as nl
    check(nl.nombre('EDM Oilers') == 'Edmonton Oilers' and nl.nombre('TOR Maple Leafs') == 'Toronto Maple Leafs'
          and nl.nombre('VGS Golden Knights') == 'Vegas Golden Knights' and nl.nombre('Real Madrid') is None,
          'los nombres de Playdoit se traducen a los 32 equipos; otro club no')
    t = nl.del_tablero(DET, 'San Jose Sharks', 'Edmonton Oilers')
    check(t and abs(t['p_local'] - 0.4255) < 0.001 and t['totales']['principal'] == 6.5
          and '2.5' in t['handicap']['visita'],
          'lee el ganador sin margen, la escalera de hándicap y la de goles')
    import cuotas_multi as cm
    check(cm.ALTENAR_SPORT.get('nhl') == 70 and 'nhl' in cm.ALTENAR_CAMPEONATOS,
          'Playdoit: hockey (70), sólo la NHL')
    af = open('alpha_finder.py', encoding='utf-8').read()
    check("'nhl': _picks_nhl" in af and "'nfl', 'nhl'" in af, 'el barrido tiene su rama de la NHL')
    return t


def probar_tarjeta(t):
    import lo_mejor as lm
    import valor_apuesta as va
    import veredicto_pick as vp
    pick = {'deporte': 'NHL', 'partido': PAR, 'implicitas': {'nhl_playdoit': t}}
    cs = va._de_nhl_lineas(pick)
    met = {c['apuesta']: c for c in cs
           if vp.evaluar(dict(c, deporte='NHL', partido=PAR))['veredicto'] == vp.METER}
    check('Handicap: Edmonton Oilers +2.5' not in met or met['Handicap: Edmonton Oilers +2.5']['cuota'] >= 1.15,
          'nunca se mete una línea por debajo de 1,15')
    check(sorted(met) == ['Goles: Menos de 8.5', 'Goles: Más de 4.5'],
          'se meten las de ≥ 78 %% con cuota ≥ 1,15 (%s)' % sorted(met))
    inf = [c['apuesta'] for c in cs if c.get('informativa')]
    check(inf == ['Handicap: San Jose Sharks +3.5'],
          'el hándicap no llega (77,6 %% o cuota < 1,15): sale el más probable, informativo (%s)' % inf)
    g = {'deporte': 'NHL', 'apuesta': 'Gana Edmonton Oilers', 'mercado': 'Moneyline'}
    check(vp.evaluar(dict(g, prob=0.77, cuota=1.27))['veredicto'] == vp.METER
          and vp.evaluar(dict(g, prob=0.71, cuota=1.36))['veredicto'] == vp.METER
          and vp.evaluar(dict(g, prob=0.68, cuota=1.42))['veredicto'] == vp.NO_METER
          and vp.evaluar(dict(g, prob=0.77, cuota=1.27, pretemporada=True))['veredicto'] == vp.NO_METER,
          'el ganador (v375): con la casa ≥ 70 % sí; al 68 % no; en pretemporada no')
    c1 = lm.del_pick(dict(pick, board={}))
    check(c1 is not None and c1['prob'] >= 0.85 and c1['cuota'] >= 1.10 and c1['deporte'] == 'NHL',
          'la Capa 1 🏆: una línea de ≥ 85 %% con cuota ≥ 1,10 (%s)' % (c1 and c1['apuesta']))
    check(lm.del_pick(dict(pick, pretemporada=True)) is None, 'y en pretemporada no hay 🏆')
    import pronosticos_guardados as pg
    h, a = PAR.split(' vs ')
    res = []
    for ap, bloque, gh, ga in (('Goles: Menos de 8.5', 'goles', 4, 3), ('Goles: Más de 4.5', 'goles', 2, 1),
                               ('Handicap: San Jose Sharks +2.5', 'handicap', 2, 4)):
        gd = {'apuesta': ap, 'bloque': bloque, 'etiqueta': 'Goles', 'mercado': 'Goles'}
        res.append(pg._acierto(gd, pg._valor_real(gd, gh, ga, None), h, a)[0])
    check(res == [True, False, True], 'y se liquida con el marcador (%s)' % res)


def probar_marcadores():
    pj = open('partidos_jugados.py', encoding='utf-8').read()
    check("rango = '%s-%s'" not in pj and 'def _eventos_espn' in pj and '_marcador_nhl' in pj,
          'los marcadores de ESPN se piden día por día (NBA y NHL)')
    ui = open('dashboard_ui.py', encoding='utf-8').read()
    check("('🏒', 'NHL')" in ui, 'y la NHL tiene su filtro 🏒')


if __name__ == '__main__':
    print('=== 1. lo medido ===')
    probar_medicion()
    print('\n=== 2. el tablero ===')
    t = probar_tablero()
    print('\n=== 3. la tarjeta ===')
    probar_tarjeta(t)
    print('\n=== 4. marcadores y pantalla ===')
    probar_marcadores()
    print('\n' + '=' * 40)
    print('TODO OK' if not FALLOS else '%d FALLOS' % len(FALLOS))
    raise SystemExit(1 if FALLOS else 0)
