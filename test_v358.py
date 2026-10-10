#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test de la v358.

El usuario: «quiero meter en la NFL hándicap, puntos más/menos y ganador, con
un modelo con la misma metodología para la pretemporada y la temporada
oficial; si hacen falta fuentes, extráelas».

Lo que se vigila:
  1. LO MEDIDO (`nfl_lineas.json`, `_v358_nfl_variantes.json`): la línea a k
     puntos de la principal; con la meta de 78 % acierta ~80 % en las dos
     mitades; el modelo de la NFL no suma.
  2. EL TABLERO de Playdoit («JAX Jaguars», «Hándicap (incl. prórroga)»).
  3. LA TARJETA: la línea de mejor cuota con ≥ 78 % se mete; la informativa
     no; la pretemporada con su regla; y se liquida con el marcador.

Ejecutar:  python test_v358.py
"""
import json

FALLOS = []


def check(cond, msg):
    print(('OK   ' if cond else 'FALLO') + ' ' + msg)
    if not cond:
        FALLOS.append(msg)


def probar_medicion():
    d = json.load(open('nfl_lineas.json', encoding='utf-8'))
    t = d['tablas']
    check(d['forma'] == 'k', 'gana la forma por distancia k (elegida con 1999-2014: %s)' % d['brier_elegir'])
    check(0.78 <= t['favorito']['10.5'] <= 0.83 and 0.76 <= t['no_favorito']['10.5'] <= 0.81
          and t['mas']['3.0'] < 0.62,
          'favorito a 10,5 %.0f %%, no favorito a 10,5 %.0f %%, más a 3 %.0f %%'
          % (100 * t['favorito']['10.5'], 100 * t['no_favorito']['10.5'], 100 * t['mas']['3.0']))
    v = json.load(open('_v358_nfl_variantes.json', encoding='utf-8'))
    m78 = v['meta78']
    check(m78['elige_2010_14']['acierta'] >= 0.79 and m78['juzga_2015_25']['acierta'] >= 0.80
          and m78['juzga_2015_25']['p5'] >= 0.79,
          'meta 78 %%: elegir %.1f %%, juzgar %.1f %% (p5 %.1f)'
          % (100 * m78['elige_2010_14']['acierta'], 100 * m78['juzga_2015_25']['acierta'],
             100 * m78['juzga_2015_25']['p5']))
    mod = v['meta75_modelo']['juzga_2015_25']['acierta'] - v['meta75']['juzga_2015_25']['acierta']
    check(mod <= 0.005, 'el modelo de la NFL como filtro no suma al juzgar (%+.1f pts)' % (100 * mod))


DET = {'mercados': [
    {'nombre': 'Hándicap (incl. prórroga)', 'selecciones': [
        {'nombre': 'PIT Steelers (-3.0)', 'cuota': 1.9}, {'nombre': 'IND Colts (+3.0)', 'cuota': 1.9},
        {'nombre': 'PIT Steelers (+7.5)', 'cuota': 1.217}, {'nombre': 'PIT Steelers (+2.5)', 'cuota': 1.45},
        {'nombre': 'IND Colts (+13.5)', 'cuota': 1.215}, {'nombre': 'IND Colts (+8.5)', 'cuota': 1.52}]},
    {'nombre': 'Totales (incl. prórroga)', 'selecciones': [
        {'nombre': 'Más de 43.5', 'cuota': 1.9}, {'nombre': 'Menos de 43.5', 'cuota': 1.9},
        {'nombre': 'Más de 33.5', 'cuota': 1.195}, {'nombre': 'Menos de 49.5', 'cuota': 1.45}]},
    {'nombre': '1ª Mitad - Hándicap', 'selecciones': [
        {'nombre': 'PIT Steelers (-1.5)', 'cuota': 1.9}]}]}
PAR = 'Pittsburgh Steelers vs Indianapolis Colts'


def probar_tablero():
    import nfl_lineas as nf
    check(nf.apodo('Jacksonville Jaguars') == nf.apodo('JAX Jaguars') == 'jaguars'
          and nf.apodo('San Francisco 49ers') == nf.apodo('SF 49ers'),
          'el apodo casa nuestros nombres con los de Playdoit')
    t = nf.del_tablero(DET, 'Pittsburgh Steelers', 'Indianapolis Colts')
    check(t and t['handicap']['principal_local'] == -3.0 and t['totales']['principal'] == 43.5,
          'lee la línea principal del hándicap y de los puntos (%s)' % str(t and (t['handicap']['principal_local'],
                                                                           t['totales']['principal'])))
    af = open('alpha_finder.py', encoding='utf-8').read()
    check(af.count('_tablero_nfl(fila, cm, h, a, fx)') == 2,
          'el barrido de la NFL cuelga el tablero (temporada y pretemporada)')
    return t


def probar_tarjeta(t):
    import nfl_lineas as nf
    import valor_apuesta as va
    import veredicto_pick as vp
    pick = {'deporte': 'NFL', 'partido': PAR, 'implicitas': {'nfl_playdoit': t}}
    cs = va._de_nfl_lineas(pick)
    met = [c['apuesta'] for c in cs if vp.evaluar(dict(c, deporte='NFL', partido=PAR))['veredicto'] == vp.METER]
    check('Handicap: Pittsburgh Steelers +7.5' in met and 'Handicap: Indianapolis Colts +13.5' in met
          and 'Puntos: Más de 33.5' in met,
          'se meten las de ≥ 78 %% con cuota ≥ 1,15 (%s)' % met)
    t2 = dict(t, totales=dict(t['totales'], mas={'43.5': 1.9}))
    cs2 = va._de_nfl_lineas({'deporte': 'NFL', 'partido': PAR, 'implicitas': {'nfl_playdoit': t2}})
    inf = [c for c in cs2 if c.get('informativa')]
    check(inf and all(vp.evaluar(dict(c, deporte='NFL'))['veredicto'] == vp.NO_METER for c in inf),
          'si ninguna línea de puntos llega, la más probable sale informativa y no se mete (%s)'
          % [c['apuesta'] for c in inf])
    c = next(c for c in cs if c['apuesta'] == 'Handicap: Pittsburgh Steelers +7.5')
    check(vp.evaluar(dict(c, deporte='NFL', cuota=1.12))['veredicto'] == vp.NO_METER,
          'con cuota por debajo de 1,15 no se mete')
    pre = dict(c, deporte='NFL', pretemporada=True)
    esperado = vp.METER if c.get('nba_tipo') in nf.PRETEMPORADA_TIPOS else vp.NO_METER
    check(vp.evaluar(pre)['veredicto'] == esperado,
          'en pretemporada sólo los lados medidos (%s)' % (nf.PRETEMPORADA_TIPOS,))
    import lo_mejor as lm
    import pronosticos_guardados as pg
    check(lm.resultado('Handicap: Indianapolis Colts +13.5', PAR, 30, 20) == 'verde'
          and lm.resultado('Handicap: Indianapolis Colts +13.5', PAR, 34, 20) == 'rojo',
          'el hándicap se liquida con el marcador')
    h, a = PAR.split(' vs ')
    res = []
    for ap, bloque, etq, gh, ga in (('Puntos: Más de 33.5', 'totales', 'Puntos', 24, 13),
                                    ('Puntos: Más de 33.5', 'totales', 'Puntos', 20, 13),
                                    ('Carreras: Menos de 9.5', 'totales', 'Carreras', 4, 3),
                                    ('Handicap: Indianapolis Colts +13.5', 'handicap', 'Hándicap', 30, 20)):
        g = {'apuesta': ap, 'bloque': bloque, 'etiqueta': etq, 'mercado': etq}
        res.append(pg._acierto(g, pg._valor_real(g, gh, ga, None), h, a)[0])
    check(res == [True, False, True, True],
          'y en el marcador: los puntos y las carreras ya no se quedan ⏳ (%s)' % res)


def probar_pretemporada():
    d = json.load(open('nfl_lineas.json', encoding='utf-8'))
    pre = d.get('pretemporada') or {}
    check(pre.get('con_linea', 0) >= 150,
          'la pretemporada medida con ESPN (%s partidos con línea)' % pre.get('con_linea'))
    m = pre['regla_78_mitades']
    check(all(m[x]['no_favorito']['acierta'] >= 0.78 and m[x]['mas']['acierta'] >= 0.78 for x in m)
          and min(m[x]['favorito']['acierta'] for x in m) < 0.75,
          'pretemporada: no favorito y «más» aguantan en las dos mitades; el favorito no')
    check(pre['ganador_casa74']['acierta'] < 0.6
          and "_dep == 'NFL' and p.get('pretemporada')" in open('veredicto_pick.py', encoding='utf-8').read(),
          'y el ganador en pretemporada no se mete (el favorito de la casa ganó %.0f %%)'
          % (100 * pre['ganador_casa74']['acierta']))


if __name__ == '__main__':
    print('=== 1. lo medido ===')
    probar_medicion()
    print('\n=== 2. el tablero ===')
    t = probar_tablero()
    print('\n=== 3. la tarjeta ===')
    probar_tarjeta(t)
    print('\n=== 4. la pretemporada ===')
    probar_pretemporada()
    print('\n' + '=' * 40)
    print('TODO OK' if not FALLOS else '%d FALLOS' % len(FALLOS))
    raise SystemExit(1 if FALLOS else 0)
