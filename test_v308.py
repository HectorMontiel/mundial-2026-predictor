#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test de la v308: calibración, escalera de remates por jugador, varias
apuestas por partido y selecciones con todos sus mercados.

Lo que se vigila:
  · LO QUE NO ESTÁ VALIDADO NO SE ENSEÑA COMO APUESTA: ni en la Capa 1 ni en
    la Escalera (el canal de goles por precio se midió y pierde).
  · Las líneas asiáticas de cuarto se escriben con dos decimales (2.25).
  · Las selecciones buscan la casa con su nombre en ESPAÑOL (Gales, no
    Wales): sin eso se quedaban sólo con el 1X2.
  · La escalera 1+/2+/3+ de remates a puerta: sale del modelo que ganó, es
    monótona, lleva la cuota de cada peldaño y se guarda su histórico de
    precios para medir contra la cuota.
  · La tarjeta enseña hasta cuatro apuestas y NINGUNA alternativa en rojo.

Ejecutar:  python test_v308.py
"""
import os
import shutil
import tempfile

FALLOS = []


def check(cond, msg):
    print(('OK   ' if cond else 'FALLO') + ' ' + msg)
    if not cond:
        FALLOS.append(msg)


def test_sin_validar():
    import barrido_capa1 as bc
    check([bc.texto_linea(x) for x in (2.25, 2.5, 4.25, 3.0, 2.75)]
          == ['2.25', '2.5', '4.25', '3.0', '2.75'],
          'las líneas de cuarto salen con dos decimales («2.25», no «2.2»)')
    ui = open('dashboard_ui.py', encoding='utf-8').read()
    check('html_lista(\n                _c1_nov' not in ui
          and '_c1_nov, con_css' not in ui,
          'la Capa 1 ya no pinta las apuestas sin validar')
    check('for pk in _nov:' not in ui,
          'y «Todo lo de hoy» tampoco las pinta como tarjeta')
    check('_TEXTO_SIN_VALIDAR' in ui and '48.510' in ui,
          'se dice cuántas quedan fuera y por qué (medido en 48.510 partidos)')
    import escalera as esc
    check(all(nv.get('acierta') is not None for nv in esc.NIVELES),
          'la Escalera sólo ofrece niveles con acierto medido')
    import json
    doc = json.load(open('_v308_canal_goles.json', encoding='utf-8'))
    check(doc['cierre_media']['pasa'] is False
          and doc['cierre_maxima']['pasa'] is False,
          'la medición del canal de goles está guardada y dice que no pasa')


def test_selecciones_en_espanol():
    import lineas_jugador as lj
    check(lj.nombres_de_casa('selecciones', 'Portugal', 'Wales')[0]
          == ('Portugal', 'Gales'),
          'Portugal–Wales se busca como Portugal–Gales')
    check(lj.nombres_de_casa('selecciones', 'Republic of Ireland', 'Kosovo')[0]
          == ('Irlanda', 'Kosovo'), 'Republic of Ireland se busca como Irlanda')
    check(lj.nombres_de_casa('premier', 'Arsenal', 'Chelsea')
          == [('Arsenal', 'Chelsea')], 'un club se busca tal cual')
    for f in ('mercado_implicito.py', 'selecciones_dia.py'):
        check('nombres_de_casa' in open(f, encoding='utf-8').read(),
              '%s usa la traducción al español' % f)
    sd = open('selecciones_dia.py', encoding='utf-8').read()
    check('_NP.get(h,' not in sd,
          'y ya no busca el nombre inglés en una tabla indexada por código')


def test_lineas_historico():
    import lineas_jugador as lj
    check('lineas' in lj._CAMPOS_GUARDADOS,
          'el fichero del día guarda la escalera entera de la casa')
    tmp = tempfile.mkdtemp()
    orig = lj.HIST_DIR
    try:
        lj.HIST_DIR = os.path.join(tmp, 'hist')
        doc = {'generado': '2026-09-23T20:00:00Z', 'partidos': {
            'x': {'clave_liga': 'selecciones', 'home': 'Portugal',
                  'away': 'Wales', 'fecha': '2026-09-24',
                  'Cristiano Ronaldo': {'equipo': 'POR', 'on': {
                      'principal': 1.5, 'cuota': 1.65,
                      'lineas': {'0.5': 1.09, '1.5': 1.65, '2.5': 3.1}}}}}}
        n1 = lj.registrar_historico(doc)
        doc['generado'] = '2026-09-24T10:00:00Z'
        doc['partidos']['x']['Cristiano Ronaldo']['on']['lineas']['1.5'] = 1.55
        lj.registrar_historico(doc)
        filas = lj._leer_hist(os.path.join(lj.HIST_DIR, '2026-09.csv'))
        f15 = [r for r in filas if r['linea'] == '1.5'][0]
        check(n1 == 3 and len(filas) == 3,
              'cada peldaño es una fila y no se duplica al volver a verlo')
        check(f15['cuota_primera'] == '1.65' and f15['cuota'] == '1.55',
              'se guarda el primer precio y el último (el más cercano al '
              'saque)')
    finally:
        lj.HIST_DIR = orig
        shutil.rmtree(tmp, ignore_errors=True)
    wf = open('.github/workflows/precalculo_dia.yml', encoding='utf-8').read()
    check('lineas_jugador.py --dias 2' in wf and 'lineas_jugador_hist' in wf,
          'el precálculo captura las líneas en cada pasada y guarda su '
          'histórico')


def test_escalera_remates():
    import remates_ml as rm
    import remates_jugador as rj
    check(abs(rm.p_al_menos(0.8, 1) - (1 - 2.718281828 ** -0.8)) < 1e-6,
          'P(≥1) con Poisson es 1 − e^−λ')
    check(rm.p_al_menos(0.8, 2, 0.3) > rm.p_al_menos(0.8, 2, 0.0),
          'con cola binomial negativa el 2+ pesa más que con Poisson')
    check(rj._linea_a_k(1.5) == 2 and rj._linea_a_k(0.5) == 1,
          '«Más de 1.5» se gana con 2 remates')
    check(rm.disponible(), 'el modelo entrenado está en modelos/')
    import json
    meta = json.load(open(rm.META, encoding='utf-8'))
    med = meta.get('medicion') or {}
    gana = all(v['p5'] > 0 for c in ('sot', 'sh')
               for t in ('eleccion', 'juicio')
               for v in (med.get(c, {}).get(t) or {}).values())
    check(bool(med) and gana,
          'el modelo guardado es el que ganó en todos los umbrales y en los '
          'dos tramos (p5 > 0)')
    fila = {'m_sot': 0.9, 'm_sh': 2.2, 'm_min': 85, 'apar': 10, 'tits': 10,
            'por90_sh': 2.3, 'por90_sot': 0.95, 'linea': 10, 'carril': 0,
            'up': 3, 'lam_eq_sh': 14, 'lam_eq_sot': 5, 'local': 1,
            'log_mv': 18.4, 'r_tiros_c': 13, 'r_sot_c': 4.5,
            'eq_tiros': 15, 'eq_sot': 5.5}
    d = rm.predecir([fila, dict(fila, linea=3, carril=1, up=1, m_sot=0.1,
                                m_sh=0.5, por90_sh=0.5, por90_sot=0.1)])
    nueve, defensa = d[0], d[1]
    check(nueve['p_sot'][1] >= nueve['p_sot'][2] >= nueve['p_sot'][3],
          'la escalera es monótona (1+ ≥ 2+ ≥ 3+)')
    check(nueve['p_sot'][1] > defensa['p_sot'][1] + 0.2,
          'un nueve con 0,9 a puerta por partido rema mucho más que un '
          'defensa (%.0f %% contra %.0f %%)'
          % (100 * nueve['p_sot'][1], 100 * defensa['p_sot'][1]))


def test_tarjeta():
    import modo_modelo as mm
    check(mm.MAX_RECOMENDADAS == 4, 'hasta cuatro apuestas por partido')
    src = open('modo_modelo.py', encoding='utf-8').read()
    check("if o.get('veredicto_vp') != 'no_meter'" in src,
          'ninguna alternativa puede ser un «no la metas»')
    qr = {'home': 'Portugal', 'away': 'Wales',
          'home_jugadores': [{'jugador': 'Cristiano Ronaldo',
                              'tits_ml': 10, 'apar_ml': 10,
                              'escalera_on': {1: 0.80, 2: 0.45, 3: 0.18},
                              'escalera_tot': {1: 0.95, 2: 0.80},
                              'cuotas_on': {1: 1.09, 2: 2.60, 3: 3.10}}],
          'away_jugadores': []}
    vs = mm.remates_con_valor(qr)
    check(len(vs) == 1 and vs[0]['k'] == 2 and abs(vs[0]['ev'] - 0.17) < 1e-9,
          'remate con valor: 2+ a puerta al 45 %% @2,60 (+17 %%); el 1+ @1,09 '
          '(−13 %%) y el 3+ (18 %%, lotería) no')
    qr_sup = {'home': 'Wales', 'away': 'X', 'away_jugadores': [],
              'home_jugadores': [{'jugador': 'Lewis Koumas', 'tits_ml': 2,
                                  'apar_ml': 9,
                                  'escalera_on': {1: 0.54, 2: 0.19},
                                  'cuotas_on': {1: 3.0}}]}
    check(mm.remates_con_valor(qr_sup) == [],
          'un suplente habitual no sale como valor aunque la cuota sea alta '
          '(la probabilidad es si es titular)')
    qr_raro = {'home': 'A', 'away': 'B', 'away_jugadores': [],
               'home_jugadores': [{'jugador': 'Z', 'tits_ml': 10,
                                   'apar_ml': 10, 'escalera_on': {1: 0.70},
                                   'cuotas_on': {1: 2.5}}]}
    check(mm.remates_con_valor(qr_raro) == [],
          'un +75 % no se marca: casi siempre es información que falta')
    html = mm._escalera_compacta(qr)
    check('A puerta 1+ / 2+' in html and '80 %' in html and '2+ 45 %' in html,
          'la fila compacta enseña la escalera a puerta')


def test_bajas_modelo():
    import json
    import bajas_modelo as bm
    doc = json.load(open('_v308_bajas.json', encoding='utf-8'))
    h6 = doc['hipotesis']['H6_xg_y_defensa']
    check(h6['pasa']['goles'] and h6['pasa']['ou25']
          and not h6['pasa']['1x2'],
          'la hipótesis adoptada (H6) pasa en goles y 2,5 y NO en 1X2 '
          '(medido sobre %d partidos)' % doc['partidos'])
    check(abs(bm.BETA_ATAQUE_XG - h6['beta'][0]) < 1e-3
          and abs(bm.BETA_ZAGA_RIVAL - h6['beta'][1]) < 1e-3,
          'los coeficientes de producción son los medidos')
    sin = {'ataque_xg': 0.0, 'zaga': 0.0}
    f_l, f_v = bm.factores({'ataque_xg': 0.2, 'zaga': 0.0},
                           {'ataque_xg': 0.0, 'zaga': 0.5})
    check(f_l < 1.0 or f_l > 1.0, 'las bajas mueven la λ')
    f_l, f_v = bm.factores({'ataque_xg': 0.2, 'zaga': 0.0}, sin)
    check(abs(f_l - 0.9606) < 0.001 and f_v == 1.0,
          'sin el 20 %% de su xG un equipo marca un 4 %% menos (%.3f)' % f_l)
    f_l, f_v = bm.factores({'ataque_xg': 0.0, 'zaga': 0.0},
                           {'ataque_xg': 0.0, 'zaga': 1.0})
    check(f_l == 1.15, 'el ajuste tiene tope (±15 %%): %.3f' % f_l)
    m = bm._mover({'2.5': 0.50, '1.5': 0.75}, 2.6, 2.4)
    check(m['2.5'] < 0.50 and m['1.5'] < 0.75,
          'con menos λ bajan las líneas de más')
    pick = {'partido': 'A vs B', 'clave_liga': 'x', 'goles_xg': {
        'local': 1.5, 'visitante': 1.1}, 'goles_lineas': {'2.5': 0.5}}
    orig = (bm.rasgos, )
    import bajas_fotmob as bf
    o_dp = bf.de_partido
    try:
        bf.de_partido = lambda p: {'home': {'bajas': [{'jugador': 'Nueve'}]},
                                   'away': {'bajas': []}}
        bm.rasgos = lambda c, e, n: ({'ataque_xg': 0.35, 'zaga': 0.0,
                                      'ausentes': ['Nueve']} if n else
                                     {'ataque_xg': 0.0, 'zaga': 0.0,
                                      'ausentes': []})
        info = bm.ajustar_pick(pick)
    finally:
        bf.de_partido = o_dp
        bm.rasgos = orig[0]
    check(info and pick['goles_xg']['local'] < 1.5
          and pick['goles_xg']['visitante'] == 1.1
          and pick['goles_lineas']['2.5'] < 0.5
          and 'A -7 % goles' in bm.texto(pick),
          'sin su nueve (35 %% del xG) el local baja y el 2,5 también (%s)'
          % bm.texto(pick))
    check(bm.ajustar_pick(pick) is None, 'no se ajusta dos veces')


if __name__ == '__main__':
    test_sin_validar()
    test_selecciones_en_espanol()
    test_lineas_historico()
    test_escalera_remates()
    test_tarjeta()
    test_bajas_modelo()
    print('\n' + '=' * 40)
    print('TODO OK' if not FALLOS else '%d FALLOS' % len(FALLOS))
    raise SystemExit(1 if FALLOS else 0)
