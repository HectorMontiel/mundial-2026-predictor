#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test de la v363.

El usuario: «sí, una marca distinguible y distinta a las demás» (las
retiradas que siguen valiendo); «no se ve completo el texto, ¿qué significa
ese círculo amarillo?, quiero saber fácilmente todo»; «en el análisis de cada
tarjeta lo veo cortado»; y las simulaciones contra los cierres.

Lo que se vigila:
  1. ♻️ SIGUE VALIENDO: retirada con ≥ 77 % (o Capa 1) que desapareció del
     tablero; no si la desplazó otra o sigue como «no meter».
  2. LAS LISTAS: el texto de la apuesta completo (sin «…»), sin círculo que
     no diga nada, y sin «$» que Streamlit pinta como fórmula.
  3. LA TABLA del análisis en tres columnas que caben en el celular.
  4. LAS SIMULACIONES guardadas (`_v363_simulaciones.json`).

Ejecutar:  python test_v363.py
"""
import json

FALLOS = []


def check(cond, msg):
    print(('OK   ' if cond else 'FALLO') + ' ' + msg)
    if not cond:
        FALLOS.append(msg)


def probar_sigue():
    import decisiones_dia as dd
    import modo_modelo as mm
    viejo = mm._por_mercado_de
    # nunca el tablero en vivo (costaba ~50 s por pasada)
    mm._por_mercado_de = lambda p: (_ for _ in ()).throw(AssertionError('en vivo'))
    try:
        p = {'partido': 'A vs B', 'deporte': 'Fútbol', dd.CLAVE_PICK: {
            'recomendadas_tarjeta': [{'apuesta': 'A o empate', 'veredicto_vp': 'meter'}],
            'otras_tarjeta': [{'apuesta': 'Córners: Menos de 12.5'}],
            'por_mercado': {'Goles': {'apuesta': 'Goles: Más de 2.5'}}}}
        a = {'apuesta': 'Goles: Más de 1.5', 'prob': 0.80, 'cuota': 1.25}
        check(mm.sigue_valiendo(p, a), 'retirada al 80 % que desapareció: ♻️ sigue valiendo')
        check(not mm.sigue_valiendo(p, dict(a, prob=0.74)), 'al 74 %, no')
        check(mm.sigue_valiendo(p, dict(a, prob=0.70, elite=True)), 'si era Capa 1, sí')
        check(not mm.sigue_valiendo(p, dict(a, apuesta='Córners: Menos de 12.5'))
              and not mm.sigue_valiendo(p, dict(a, apuesta='Goles: Más de 2.5')),
              'si sigue en «también se meten» o en el tablero (desplazada / no meter), no')
        check(not mm.sigue_valiendo(dict(p, deporte='Tenis'), a), 'sólo fútbol (lo medido)')
        check(not mm.sigue_valiendo({'partido': 'A vs B', 'deporte': 'Fútbol'}, a),
              'sin el precálculo no se marca (y no se calcula en vivo)')
    finally:
        mm._por_mercado_de = viejo
    src = open('modo_modelo.py', encoding='utf-8').read()
    check('♻️ <b>SIGUE VALIENDO</b>' in src and '#7F77DD' in src and "'sigue': True" in src,
          'se pinta con su marca propia (morada) y entra en la lista bajo el marcador')


def probar_listas():
    import vista_compacta as vc
    css = vc.CSS
    i = css.find('.vc-ap{')
    check(i >= 0 and 'ellipsis' not in css[i:css.find('}', i)],
          'el texto de la apuesta se ve completo (sin «…»)')
    f = vc.fila({'apuesta': 'Tiros a puerta Besiktas: Más de 4.5', 'cuota': 1.69, 'prob': 0.73,
                 'partido': 'Besiktas vs Kocaelispor'})
    check(f and f['icono'] == '', 'sin semáforo no hay círculo amarillo')
    f2 = vc.fila({'apuesta': 'x', 'cuota': 1.5, 'prob': 0.6, 'partido': 'A vs B', 'icono': '🎲'})
    check(f2['icono'] == '🎲', 'la pata arriesgada lleva 🎲')
    ui = open('dashboard_ui.py', encoding='utf-8').read()
    check("por $100" not in ui and '100 → %.0f' in ui, 'el boleto ya no usa «$» (se pintaba como fórmula)')


def probar_tabla():
    import modo_modelo as mm
    import tiros_equipo as te
    doc = {'k': {'corners': 11.6}, 'partidos': {'A vs B|mls': {
        'local': {'tiros': 15.0, 'a_puerta': 6.0, 'goles': 1.8, 'corners': 5.6, 'tarjetas': 2.0},
        'visitante': {'tiros': 11.0, 'a_puerta': 4.0, 'goles': 1.2, 'corners': 4.3, 'tarjetas': 2.4}}}}
    viejo = te._dia
    te._dia = lambda ruta=None: doc
    try:
        h = mm._tabla_metodo_html({'partido': 'A vs B', 'clave_liga': 'mls', 'deporte': 'Fútbol'})
    finally:
        te._dia = viejo
    fila = h.split('<tr>')[1]
    check('table-layout:fixed' in h and fila.count('<td') == 3 and 'nowrap' not in h,
          'la tabla del análisis: tres columnas, ancho fijo y con salto de línea')


def probar_velocidad():
    import time
    import arriesgadas as ar
    import modo_modelo as mm
    ps = [{'partido': 'X%d vs Y%d' % (i, i), 'deporte': 'Fútbol',
           'inicio': '2099-01-01T12:00:00Z'} for i in range(300)]
    mm.lista_por_acierto(ps)
    ar.del_dia(ps)
    t0 = time.time()
    for _ in range(20):
        mm.lista_por_acierto(ps)
        ar.del_dia(ps)
    check(time.time() - t0 < 1.0, 'la lista y las arriesgadas se recuerdan entre pasadas '
          '(20 pasadas en %.2f s)' % (time.time() - t0))
    check('tarjetas' not in [m[0] for m in ar.MERCADOS]
          and all(m[1] is None for m in ar.MERCADOS if m[0] == 'corners'),
          'fuera de las arriesgadas: tarjetas y córners de equipo (prometían de más)')


def probar_simulaciones():
    d = json.load(open('_v363_simulaciones.json', encoding='utf-8'))
    check(d['partidos'] >= 500 and 'Córners equipo' in d['mercados'] and 'draftea' in d
          and d['draftea']['metodo']['6']['todo']['dias'] >= 20,
          'las simulaciones contra los cierres de Playdoit están guardadas (%d partidos)' % d['partidos'])


if __name__ == '__main__':
    print('=== 1. ♻️ sigue valiendo ===')
    probar_sigue()
    print('\n=== 2. las listas ===')
    probar_listas()
    print('\n=== 3. la tabla del análisis ===')
    probar_tabla()
    print('\n=== 4. velocidad y mercados ===')
    probar_velocidad()
    print('\n=== 5. las simulaciones ===')
    probar_simulaciones()
    print('\n' + '=' * 40)
    print('TODO OK' if not FALLOS else '%d FALLOS' % len(FALLOS))
    raise SystemExit(1 if FALLOS else 0)
