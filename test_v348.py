#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test de la v348.

El usuario: «en remates no puedes usar "menos de", sólo "más de"»; «un filtro
para ordenar los partidos que tengan tiros a puerta, tarjetas, goles…, que
abarque también lo de "también se meten"»; «haz la misma prueba para ambos
marcan»; y «en el marcador, que se pueda desplegar la conversión de lo
primero que se anunció contra lo de ahora, para validarlo yo».

Lo que se vigila:
  1. REMATES SÓLO «MÁS DE», en la tarjeta y en las reglas de tiros (que con
     sólo «más» quedan en seguimiento, sin activar hasta tener p5 > 0).
  2. EL FILTRO POR MERCADO: la mejor apuesta de cada familia (primero las que
     se meten), los partidos ordenados y la apuesta arriba de la tarjeta.
  3. AMBOS MARCAN: medido, no mejora a la casa: no entra.
  4. LA COMPARACIÓN en el marcador, plegable.

Ejecutar:  python test_v348.py
"""
import json
import os
import tempfile

FALLOS = []


def check(cond, msg):
    print(('OK   ' if cond else 'FALLO') + ' ' + msg)
    if not cond:
        FALLOS.append(msg)


def probar_remates():
    import tiros_seguimiento as ts
    import valor_apuesta as va
    bloque = {'lambda_home': 4.0, 'lambda_away': 6.0, 'lambda_total': 10.0,
              'dispersion': 1.1, 'dispersion_total': 1.1, 'k': 44.0,
              'modelo_tiros': 'v345', 'peso_modelo': 0.65,
              'confianza': {'insignia': True}}
    pick = {'partido': 'A vs B', 'clave_liga': 'brasil', 'implicitas': {
        'remates_on_home': {'5.5': {'p': 0.4, 'mas': 2.4, 'menos': 1.5}},
        'remates_on': {'9.5': {'p': 0.5, 'mas': 1.85, 'menos': 1.85}}}}
    filas = va._de_conteo(pick, {'Remates a puerta': bloque})
    ap = [f['apuesta'] for f in filas]
    check(ap and all('Menos de' not in a for a in ap) and any('Más de' in a for a in ap),
          'en remates sólo salen los «más de» (%s)' % ap)
    check(ts.alta_de(0.20, 'a_puerta', 3.0, 1.3) == ''
          and ts.apuesta_de(0.30, 0.50, 'tiros', 2.0, 1.6) == '',
          'y las reglas de tiros ya no apuestan al «menos»')
    r = ts.medir(ts.FICHERO, os.path.join(tempfile.mkdtemp(), 'r.json'))
    check(not r['activo'] and not r['alta']['activo'],
          'con sólo «más», las dos reglas en seguimiento (alta: %s apuestas, p5 %s)'
          % (r['alta'].get('n'), r['alta'].get('p5')))


class _St:
    def __init__(self):
        self.txt = []

    def markdown(self, t, **k):
        self.txt.append(str(t))


def probar_filtro():
    import modo_modelo as mm
    arriba = [{'apuesta': 'Goles: Más de 1.5', 'mercado': 'Goles', 'prob': 0.78, 'cuota': 1.25}]
    otras = [{'apuesta': 'Córners: Más de 7.5', 'mercado': 'Córners', 'prob': 0.76, 'cuota': 1.3}]
    import valor_apuesta as va
    orig = va.candidatos
    try:
        va.candidatos = lambda p, b: [
            {'apuesta': 'Goles: Más de 0.5', 'mercado': 'Goles', 'prob': 0.93, 'cuota': 1.05},
            {'apuesta': 'Tarjetas: Más de 3.5', 'mercado': 'Tarjetas', 'prob': 0.6, 'cuota': 1.6},
            {'apuesta': 'Remates a puerta Local: Más de 3.5', 'mercado': 'Remates a puerta',
             'prob': 0.7, 'cuota': 1.4}]
        pm = mm.mejor_por_mercado({}, {}, arriba, otras)
    finally:
        va.candidatos = orig
    check(pm['Goles']['apuesta'] == 'Goles: Más de 1.5' and pm['Goles']['donde'] == 'arriba',
          'en cada mercado manda la que se mete, aunque haya otra más probable')
    check(pm['Córners']['donde'] == 'tambien' and pm['Tarjetas']['donde'] == 'informativa'
          and pm['Tiros a puerta']['prob'] == 0.7,
          'luego «también se meten», y si no, la más probable como informativa')
    mm_orig = mm._por_mercado_de
    try:
        datos = {'A': {'Tarjetas': {'apuesta': 'x', 'prob': 0.6, 'cuota': 1.5, 'donde': 'informativa'}},
                 'B': {'Tarjetas': {'apuesta': 'y', 'prob': 0.7, 'cuota': 1.3, 'donde': 'tambien'}},
                 'C': {'Goles': {'apuesta': 'z', 'prob': 0.8, 'cuota': 1.2, 'donde': 'arriba'}}}
        mm._por_mercado_de = lambda p: datos[p['partido']]
        r = mm._filtra_mercado([{'partido': 'A'}, {'partido': 'B'}, {'partido': 'C'}], 'Tarjetas')
        check([p['partido'] for p in r] == ['B', 'A'],
              'el filtro deja los partidos con el mercado, las que se meten primero')
    finally:
        mm._por_mercado_de = mm_orig
    src = open('modo_modelo.py', encoding='utf-8').read()
    dd = open('decisiones_dia.py', encoding='utf-8').read()
    check("key='%s_mercado' % clave" in src and 'mm-filtro' in src
          and "out['por_mercado'] = mm.mejor_por_mercado(" in dd,
          'con su control en «Filtros», su línea en la tarjeta y precalculado')


def probar_btts():
    r = json.load(open('_v348_btts.json', encoding='utf-8'))
    a, b = r['A_historial'], r['B_playdoit']
    check(a['modelo_vs_poisson'][1] < 0 and b['modelo_vs_casa'][0] < 0,
          'ambos marcan con la metodología no mejora (historial p5 %s; contra '
          'la casa %s): no entra' % (a['modelo_vs_poisson'][1], b['modelo_vs_casa'][0]))


def probar_comparacion():
    import estilo_ui as eu
    h = eu.marcador_doble({'titulo': 'Ayer', 'verdes': 8, 'rojas': 2, 'prim_v': 7, 'prim_r': 3},
                          {'titulo': 'Hoy', 'verdes': 1, 'rojas': 0})
    check('<details class="mc-comp">' in h and '80 %' in h and '70 %' in h,
          'el marcador trae plegada la comparación pitido / primera anunciada')
    check('<details' not in eu.marcador_doble({'titulo': 'A', 'verdes': 1, 'rojas': 0},
                                              {'titulo': 'B', 'verdes': 0, 'rojas': 0}),
          'sin datos de la primera, no se pinta')
    d = open('dashboard_ui.py', encoding='utf-8').read()
    check("'prim_v': prim_v," in d, 'y el cálculo del día la lleva')


if __name__ == '__main__':
    print('=== 1. remates sólo «más de» ===')
    probar_remates()
    print('\n=== 2. el filtro por mercado ===')
    probar_filtro()
    print('\n=== 3. ambos marcan ===')
    probar_btts()
    print('\n=== 4. la comparación ===')
    probar_comparacion()
    print('\n' + '=' * 40)
    print('TODO OK' if not FALLOS else '%d FALLOS' % len(FALLOS))
    raise SystemExit(1 if FALLOS else 0)
