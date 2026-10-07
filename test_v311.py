#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test de la v311: la tarjeta sólo enseña lo que se mete, y una sola apuesta
de resultado por partido.

El usuario, con México–Colombia (1-1) delante: «me estás dando dos de doble
oportunidad y eso no es posible meterlo; tiene que ser una o la otra. Quiero
que ya sólo me des las de meter: esto se mete, y es la única que se muestra.
No quiero tanto rollo. Replícalo en todas las ligas».

Lo que se vigila:

  1. UNA SOLA DE RESULTADO: 1X2, doble oportunidad, doble con goles y
     hándicap no pueden salir juntas; se queda la mejor ordenada.
  2. SÓLO «METER»: la tarjeta filtra por veredicto y, si no hay nada, lo dice
     en una línea; lo que se guarda es lo mismo que se enseña.
  3. EL FINALIZADO: enseña sólo las que se dijeron «meter»; si se archivó sin
     nada que meter, lo dice y no reconstruye una apuesta que nadie propuso.

Ejecutar:  python test_v311.py
"""
FALLOS = []


def check(cond, msg):
    print(('OK   ' if cond else 'FALLO') + ' ' + msg)
    if not cond:
        FALLOS.append(msg)


def probar_una_de_resultado():
    import modo_modelo as mm
    import valor_apuesta as va
    import veredicto_pick as vp
    # v312 — dentro de la franja medida de «meter» (70-80 %, cuota < 1,35):
    # dos apuestas de resultado (doble oportunidad y 1X2) y una de goles
    filas = [
        {'mercado': 'Doble oportunidad', 'apuesta': 'Mexico o empate',
         'prob': .76, 'cuota': 1.25, 'bloque': 'resultado', 'etiqueta': 'Doble'},
        {'mercado': '1X2', 'apuesta': 'Gana Mexico', 'prob': .72,
         'cuota': 1.30, 'bloque': 'resultado', 'etiqueta': 'Resultado'},
        {'mercado': 'Goles', 'apuesta': 'Goles: Menos de 3.5', 'prob': .78,
         'cuota': 1.22, 'bloque': 'goles', 'etiqueta': 'Total'},
    ]
    orig_m, orig_e = va.mejores, vp.evaluar_lista
    # v335 — donde la casa cotiza, «meter» exige su precio (`p_mercado`): se
    # le da uno de acuerdo con el modelo para seguir probando la mecánica.
    import concordancia as _conc
    orig_pm = _conc.prob_mercado
    _conc.prob_mercado = lambda pick, apuesta, mercado='': 0.80
    va.mejores = lambda pick, bloques, n=3: [dict(f) for f in filas]
    vp.evaluar_lista = lambda cands, con_contexto=False: [
        {'pick': c, 'veredicto': 'meter' if c['prob'] >= .65 else 'no_meter',
         'prob_ajustada': c['prob']}
        for c in sorted(cands, key=lambda c: -c['prob'])]
    try:
        r = mm.recomendadas({'partido': 'Mexico vs Colombia',
                             'deporte': 'Fútbol'}, None, n=4)
    finally:
        va.mejores, vp.evaluar_lista = orig_m, orig_e
        _conc.prob_mercado = orig_pm
    merc = [x['mercado'] for x in r]
    res = [m for m in merc if m in mm.FAMILIA_RESULTADO]
    check(len(res) == 1, 'una sola apuesta de resultado por partido (%s)' % merc)
    check(r and r[0]['apuesta'] == 'Goles: Menos de 3.5'
          and res == ['Doble oportunidad'],
          'y es la mejor de las de resultado, no la primera que llega')
    check(mm.metidas(r) and all(x['veredicto_vp'] == 'meter'
                                for x in mm.metidas(r)),
          '`metidas` deja sólo las de «meter»')


def probar_la_tarjeta():
    src = open('modo_modelo.py', encoding='utf-8').read()
    check('recos = metidas(recos)' in src,
          'la tarjeta sólo trabaja con lo que se mete')
    check('🚫 Nada que meter en este partido' in src,
          'y si no hay nada, lo dice en una línea')
    check("'Meter o no meter, corregido por lo '" not in src
          and "'🎯 Se mete'" in src,
          'el panel se llama «🎯 Se mete» y ya no lista los descartes')
    check('filas += _filas_de_mercados(' not in src,
          'MERCADOS ya no enseña una «mejor apuesta» de cada mercado')
    i = src.find('_pgs.guardar(pick, recos)')
    j = src.find('recos = metidas(recos)')
    check(0 < j < i, 'lo que se guarda es lo mismo que se enseña')


def probar_el_finalizado():
    import pronosticos_guardados as pg
    import partidos_jugados as pj
    src = open('modo_modelo.py', encoding='utf-8').read()
    check("filas = [f for f in filas if f.get('veredicto') == 'meter']" in src,
          'el finalizado enseña sólo las que se dijeron «meter»')
    check('🚫 No había nada que meter en este' in src,
          'y si no hubo ninguna, lo dice')
    check("filas = [f for f in filas if f.get('origen') != 'modelo']" in src,
          'las lecturas del modelo sin precio no salen como apuesta')
    check("f['prob'] = f['prob_meter']" in src,
          'el porcentaje es con el que se decidió meter')
    pick = {'partido': 'A vs B', 'clave_liga': 'x', 'fecha': '2026-09-26',
            'jugado': True, 'goles_home': 1, 'goles_away': 1,
            'recomendadas_previas': []}
    orig = pg.reconstruir
    pg.reconstruir = lambda p: [{'apuesta': 'INVENTADA', 'bloque': 'goles'}]
    try:
        check(pg.validar(pick) == [],
              'archivado sin nada que meter: no se reconstruye una apuesta')
    finally:
        pg.reconstruir = orig
    psrc = open('partidos_jugados.py', encoding='utf-8').read()
    check("recos = [o for o in recos if o.get('veredicto_vp') == 'meter']"
          in psrc, 'el archivo guarda sólo las «meter»')


if __name__ == '__main__':
    print('=== 1. una sola de resultado ===')
    probar_una_de_resultado()
    print('\n=== 2. la tarjeta ===')
    probar_la_tarjeta()
    print('\n=== 3. el finalizado ===')
    probar_el_finalizado()
    print('\n' + '=' * 40)
    print('TODO OK' if not FALLOS else '%d FALLOS' % len(FALLOS))
    raise SystemExit(1 if FALLOS else 0)
