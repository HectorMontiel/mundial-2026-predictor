#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test de la v361.

El usuario: «el análisis de cada tarjeta, más breve y visual: goles,
tarjetas, córners, tiros y tiros a puerta con su porcentaje, con la
metodología de mi amigo (ponle nombre); saber cuáles se cumplieron para
analizar patrones; y que el filtro de mercado funcione con esas estadísticas».

Lo que se vigila:
  1. LO MEDIDO (`_v361_metodo.json`): el «Método Contexto» bate a «últimos 5»
     y a ataque × defensa en las cinco estadísticas, con p5 > 0.
  2. EL MODELO (`tiros_equipo`): entrena y precalcula los cinco objetivos, y
     con un modelo publicado sin los nuevos no se rompe.
  3. LA TABLA del análisis y el filtro por estadística.
  4. EL SEGUIMIENTO (`analisis_seguimiento`): apunta, liquida y resume.

Ejecutar:  python test_v361.py
"""
import json
import os
import shutil
import tempfile

FALLOS = []


def check(cond, msg):
    print(('OK   ' if cond else 'FALLO') + ' ' + msg)
    if not cond:
        FALLOS.append(msg)


def probar_medicion():
    d = json.load(open('_v361_metodo.json', encoding='utf-8'))['objetivos']
    ok = all(d[o]['ll_metodo'] < d[o]['ll_ult5'] and d[o]['ll_metodo'] < d[o]['ll_atq_def']
             and d[o]['mejora_vs_ult5_p5'] > 0 and d[o]['mejora_vs_atq_def_p5'] > 0
             for o in ('goles', 'corners', 'tarjetas', 'tiros', 'a_puerta'))
    check(ok, 'el método bate a «últimos 5» y a ataque × defensa en las cinco (p5 > 0): %s'
          % {o: (d[o]['ll_metodo'], d[o]['ll_ult5']) for o in d})


DOC = {'k': {'tiros': 20.0, 'a_puerta': 43.0, 'corners': 11.6},
       'partidos': {'A vs B|mls': {
           'local': {'tiros': 15.4, 'a_puerta': 5.8, 'goles': 1.85, 'corners': 5.6, 'tarjetas': 2.0},
           'visitante': {'tiros': 11.3, 'a_puerta': 4.0, 'goles': 1.19, 'corners': 4.3,
                         'tarjetas': 2.4}}}}


def probar_modelo():
    import tiros_equipo as te
    check(te.OBJETIVOS == ('tiros', 'a_puerta', 'goles', 'corners', 'tarjetas')
          and te.COL_OBJ['tarjetas'] == 'amarillas' and te.METODO == 'Método Contexto',
          'el modelo tiene los cinco objetivos y se llama «Método Contexto»')
    src = open('tiros_equipo.py', encoding='utf-8').read()
    check("if os.path.exists(os.path.join(directorio, '%s.txt' % o))" in src
          and 'for obj in boosters:' in src,
          'con un modelo publicado sin los nuevos objetivos, carga sólo los que hay')


def probar_tabla():
    import modo_modelo as mm
    import tiros_equipo as te
    viejo = te._dia
    te._dia = lambda ruta=None: DOC
    try:
        pick = {'partido': 'A vs B', 'clave_liga': 'mls', 'deporte': 'Fútbol'}
        mc = mm.metodo_contexto(pick)
        check(set(mc) == {'goles', 'corners', 'tarjetas', 'tiros', 'a_puerta'}
              and mc['goles']['linea'] == 1.5 and 0.78 <= mc['goles']['p'] <= 0.84
              and all(x['metodo'] for x in mc.values()),
              'las cinco filas con la línea al 70 %%+ (goles más de 1.5 al %.0f %%)'
              % (100 * mc['goles']['p']))
        html = mm._tabla_metodo_html(pick)
        check('📐 Método Contexto' in html and 'Córners' in html and 'A puerta' in html
              and '*' not in html.split('</table>')[0].split('Goles')[1][:3],
              'la tabla del análisis lleva el nombre y las cinco estadísticas')
        DOC['partidos']['A vs B|mls']['local'].pop('corners')
        mc2 = mm.metodo_contexto(pick, _ck={'origen': 'observado', 'filas': [
            {'etiqueta': 'Local', 'media': 5.0}, {'etiqueta': 'Visita', 'media': 4.0}]})
        check(mc2['corners']['metodo'] is False and abs(mc2['corners']['total'] - 9.0) < 1e-9,
              'sin el objetivo en el modelo publicado: la media de antes, marcada')
        DOC['partidos']['A vs B|mls']['local']['corners'] = 5.6
        # el filtro por estadística
        mm._por_mercado_de = (lambda p: {})
        out = mm._filtra_mercado([dict(pick, inicio='2099-01-01T12:00:00Z')], 'Tiros')
        fm = out[0]['_filtro_mercado'] if out else {}
        check(out and fm.get('donde') == 'analisis' and fm['apuesta'].startswith('Tiros: Más de'),
              'el filtro «Tiros» encuentra el partido por el análisis (%s)' % fm.get('apuesta'))
    finally:
        te._dia = viejo
        import importlib
        importlib.reload(mm)
    src = open('modo_modelo.py', encoding='utf-8').read()
    check("!= 'analisis']" in src and "_p_fm.pop('_filtro_mercado', None)" in src,
          'los del análisis no se esconden en «sin nada que meter», y la marca se limpia')


def probar_seguimiento():
    import analisis_seguimiento as an
    import modo_modelo as mm
    tmp = tempfile.mkdtemp()
    cwd = os.getcwd()
    try:
        ruta = os.path.join(tmp, 's.csv')
        viejo = mm.metodo_contexto
        mm.metodo_contexto = lambda p, *a, **k: {
            'goles': {'local': 1.8, 'visita': 1.2, 'total': 3.0, 'linea': 1.5, 'p': 0.8, 'metodo': True},
            'corners': {'local': 5, 'visita': 4, 'total': 9, 'linea': 7.5, 'p': 0.72, 'metodo': True}}
        try:
            n = an.registrar([{'partido': 'A vs B', 'deporte': 'Fútbol', 'clave_liga': 'mls',
                               'inicio': '2099-01-01T12:00:00Z', 'fecha': '2099-01-01'}],
                             ruta=ruta, ahora=0)
        finally:
            mm.metodo_contexto = viejo
        check(n == 2, 'apunta una fila por estadística (%d)' % n)
        dia = an._leer(ruta).dia.iloc[0]
        os.chdir(tmp)
        json.dump({'dia': dia, 'partidos': [{'partido': 'A vs B', 'goles_home': 1, 'goles_away': 1,
                                              'stats_partido': {'corners_home': 3, 'corners_away': 3}}]},
                  open('jugados_dia.json', 'w', encoding='utf-8'))
        m = an.liquidar(ruta)
        d = an._leer(ruta)
        check(m == 2 and sorted(d.cumple.astype(int).tolist()) == [0, 1],
              'liquida: goles 2 > 1.5 ✅, córners 6 < 7.5 ❌')
        rs = an.resumen(ruta, dias=3650, hoy='2100-01-01')
        check(rs['goles']['verdes'] == 1 and rs['corners']['verdes'] == 0,
              'y resume cuántas se cumplieron por estadística')
    finally:
        os.chdir(cwd)
        shutil.rmtree(tmp, ignore_errors=True)
    pc = open('precalculo_dia.py', encoding='utf-8').read()
    wf = open('.github/workflows/precalculo_dia.yml', encoding='utf-8').read()
    check('analisis_seguimiento.registrar(' in pc and ' analisis_seguimiento.csv ' in wf,
          'el precálculo lo apunta y lo liquida, y el fichero se sube')


if __name__ == '__main__':
    print('=== 1. lo medido ===')
    probar_medicion()
    print('\n=== 2. el modelo ===')
    probar_modelo()
    print('\n=== 3. la tabla y el filtro ===')
    probar_tabla()
    print('\n=== 4. el seguimiento ===')
    probar_seguimiento()
    print('\n' + '=' * 40)
    print('TODO OK' if not FALLOS else '%d FALLOS' % len(FALLOS))
    raise SystemExit(1 if FALLOS else 0)
