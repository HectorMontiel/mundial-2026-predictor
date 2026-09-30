#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test de la v316.

El usuario: «te dije que le hagas el modelo a esos partidos, o si no se
puede, dime por qué», y tres ideas para los goles (zonas de la tabla,
goles a favor/en contra con % de 4+, la cola de 4+ goles), «probar en
historial y adoptarlo sólo si mejora».

Lo que se vigila:
  1. LA BASE DE FLASHSCORE: lee el formato, separa equipos por país, y el
     modelo propio la usa con los nombres exactos del tablero.
  2. LA TABLA: posición, zonas, goles a favor/en contra casa/fuera, 4+.
  3. LO MEDIDO Y ADOPTADO: el contexto de tabla solo no pasó; en
     `patrones_liga` entran «más de 1,5» y los rasgos de temporada donde
     ganaron (3,5); más verdes en la simulación de goles.
  4. LA PANTALLA: la «g» de la forma ya dice «a favor / en contra».

Ejecutar:  python test_v316.py
"""
import json
import os
import tempfile

FALLOS = []


def check(cond, msg):
    print(('OK   ' if cond else 'FALLO') + ' ' + msg)
    if not cond:
        FALLOS.append(msg)


def probar_flashscore():
    import resultados_flashscore as rf
    feed = ('SA÷1¬~ZA÷ARGENTINA: Reserve League¬ZL÷/football/argentina/reserve-league/¬'
            '~AA÷abc12345¬AD÷1790700000¬AB÷3¬AE÷Platense 2¬AF÷Huracan 2¬AG÷2¬AH÷1¬'
            '~AA÷def12345¬AD÷1790700000¬AB÷1¬AE÷A¬AF÷B¬')
    p = rf._partidos(feed, '', '')
    check(len(p) == 1 and p[0]['home'] == 'Platense 2' and p[0]['gh'] == 2
          and p[0]['liga'] == 'ARGENTINA: Reserve League',
          'lee los terminados del formato de Flashscore (y salta los no terminados)')
    feed2 = ('~AA÷ght12345¬AD÷1790700000¬AB÷3¬AE÷A¬AF÷B¬AG÷5¬AH÷3¬BC÷2¬BD÷1¬')
    p2 = rf._partidos(feed2, 'X', '/football/x/y/')
    check(p2 and (p2[0]['hh'], p2[0]['ha']) == (3, 2) and 'hh' in rf.COLUMNAS,
          'guarda el marcador al descanso: final menos los goles de la 2.ª mitad (BC/BD)')
    pedidas = []
    orig_get = rf._get

    def falso(url, intentos=3):
        pedidas.append(url)
        if url.endswith('/football/costa-rica/primera-division/results/'):
            return '~AA÷x1¬AD÷1790700000¬AB÷3¬AE÷Saprissa¬AF÷Heredia¬AG÷1¬AH÷0¬'
        return None
    rf._get = falso
    try:
        r1 = rf.adivinar_ruta('COSTA RICA: Primera Division - Apertura')
        r2 = rf.adivinar_ruta('NARNIA: Liga de Leones')
    finally:
        rf._get = orig_get
    check(r1 == '/football/costa-rica/primera-division/' and r2 is None,
          'la liga que el feed del día no trae se busca por su nombre (sin la fase), '
          'y sólo se acepta si tiene partidos')
    html = ('country_id = 198;tournament_id = "dYlOSQOD";'
            'seasonId: 184, allEventsCount: 380,')
    pedidas = []

    def falso2(url, intentos=3):
        pedidas.append(url)
        if url.endswith('_1_3_es-mx_1') or url.endswith('_2_3_es-mx_1'):
            return '~AA÷p%d¬AD÷1790700000¬AB÷3¬AE÷A¬AF÷B¬AG÷1¬AH÷0¬' % len(pedidas)
        return ''
    rf._get = falso2
    try:
        pags = rf.paginas_siguientes(html)
        pocas = rf.paginas_siguientes(html.replace('380', '90'))
    finally:
        rf._get = orig_get
    check(len(pags) == 2 and 'tr_1_198_dYlOSQOD_184_1_' in pedidas[0] and pocas == [],
          'pide el resto de la temporada (la página de resultados sólo trae ~100)')
    # el cron sólo reescribe el fichero chico de lo reciente
    import pandas as pd
    d0 = tempfile.mkdtemp()
    cwd0 = os.getcwd()
    os.chdir(d0)
    orig_rutas = rf.rutas
    try:
        pd.DataFrame([{'match_id': 'viejo1', 'ini': '2025-01-01 12:00:00', 'liga': 'X: Y',
                       'ruta': '/football/x/y/', 'home': 'A', 'away': 'B', 'gh': 1, 'ga': 0,
                       'hh': 0, 'ha': 0}]).to_csv(rf.FICHERO, index=False, compression='gzip')
        json.dump(['/football/x/y/'], open(rf.HISTORIA, 'w'))
        antes = os.path.getmtime(rf.FICHERO)
        rf.rutas = lambda dias=7: {'X: Y': '/football/x/y/'}
        rf._get = lambda url, intentos=3: (
            '~AA÷nuevo1¬AD÷1790700000¬AB÷3¬AE÷A¬AF÷C¬AG÷2¬AH÷2¬BC÷1¬BD÷1¬')
        rf._MEM.clear()
        n_nuevos = rf.actualizar(ligas=['X: Y'])
        rec = pd.read_csv(rf.FICHERO_RECIENTE)
        rf._MEM.clear()
        todo = rf.cargar()
        ok_split = (n_nuevos == 1 and list(rec['match_id']) == ['nuevo1']
                    and os.path.getmtime(rf.FICHERO) == antes
                    and set(todo['match_id']) == {'viejo1', 'nuevo1'})
    finally:
        rf._get, rf.rutas = orig_get, orig_rutas
        rf._MEM.clear()
        os.chdir(cwd0)
    check(ok_split, 'el histórico queda fijo y lo nuevo va al fichero chico (el repositorio no crece 7 MB por pasada)')
    check(rf.clave_equipo('/football/argentina/reserve-league/', 'Platense 2')
          == 'argentina|Platense 2'
          and rf.clave_equipo('/football/europe/euro-u21/', 'Belgium U21') == 'Belgium U21',
          'un equipo es su nombre dentro de su país (en torneos internacionales, a secas)')
    # el modelo propio con una base mínima
    import pandas as pd
    import modelo_competiciones as mc
    d = tempfile.mkdtemp()
    cwd = os.getcwd()
    os.chdir(d)
    try:
        filas = []
        t0 = pd.Timestamp('2026-08-01')
        for i in range(10):
            filas.append({'match_id': 'a%d' % i, 'ini': t0 + pd.Timedelta(days=2 * i),
                          'liga': 'X: Y', 'ruta': '/football/x/y/', 'home': 'Fuerte',
                          'away': 'Debil', 'gh': 3, 'ga': 0})
            filas.append({'match_id': 'b%d' % i, 'ini': t0 + pd.Timedelta(days=2 * i + 1),
                          'liga': 'X: Y', 'ruta': '/football/x/y/', 'home': 'Debil',
                          'away': 'Fuerte', 'gh': 0, 'ga': 2})
        pd.DataFrame(filas).to_csv(rf.FICHERO, index=False, compression='gzip')
        json.dump({'X: Y': '/football/x/y/'}, open(rf.RUTAS, 'w'))
        rf._MEM.clear()
        mc._MEM.pop('mfs', None)
        r = mc.predecir_flashscore('Fuerte', 'Debil', 'X: Y')
    finally:
        os.chdir(cwd)
        rf._MEM.clear()
        mc._MEM.pop('mfs', None)
    check(r and r.get('p') and r['p']['home'] > 0.6 and r['fuente'] == 'flashscore',
          'el modelo propio con la base de Flashscore: el que gana 3-0 es favorito '
          '(%.2f)' % (r['p']['home'] if r and r.get('p') else 0))
    pj = open('partidos_jugados.py', encoding='utf-8').read()
    check('marcadores_flashscore(dia)' in pj, 'se liquida también con Flashscore')
    t = open('.github/workflows/precalculo_dia.yml', encoding='utf-8').read()
    check('resultados_flashscore.csv.gz' in t and 'rutas_flashscore.json' in t,
          'el cron guarda la base de Flashscore')
    ms = open('mercado_sin_modelo.py', encoding='utf-8').read()
    check("liga=v.get('liga')" in ms, 'los partidos fuera del motor buscan su competición')


def probar_tabla():
    import pandas as pd
    import tabla_liga as tl
    t0 = pd.Timestamp('2026-08-01')
    filas = []
    eqs = ['A', 'B', 'C', 'D']
    k = 0
    for i, h in enumerate(eqs):
        for a in eqs:
            if h == a:
                continue
            gh, ga = (3, 1) if h == 'A' else (1, 1)
            filas.append({'date': t0 + pd.Timedelta(days=k), 'home': h, 'away': a,
                          'gh': gh, 'ga': ga})
            k += 1
    t = tl.tabla(pd.DataFrame(filas))
    check(t['A']['pos'] == 1 and t['A']['casa_gf'] == 3.0 and t['A']['casa_gc'] == 1.0,
          'la tabla: primero, y goles a favor/en contra en casa')
    check(t['A']['pct_4mas'] is not None and 0 < t['A']['pct_4mas'] <= 1,
          'el % de partidos con 4+ goles')
    check('a_zona_arriba' in t['B'] and 'a_descenso' in t['B'],
          'los puntos a la zona de arriba y al descenso')


def probar_medido():
    c = json.load(open('_v316_contexto.json', encoding='utf-8'))
    check(not c['over_2.5']['+ contexto de tabla']['adopta']
          and not c['over_3.5']['+ contexto de tabla']['adopta'],
          'el contexto de tabla SOLO no mejoró (no se adopta así)')
    u = c['under_3.5_franja_70_80']
    check(u['1.0']['acierto'] >= u['0.0']['acierto'],
          'en partidos decisivos los «menos de 3,5» no fallan más (%.1f %% contra %.1f %%)'
          % (100 * u['1.0']['acierto'], 100 * u['0.0']['acierto']))
    e = json.load(open('_v316_patrones_extra.json', encoding='utf-8'))
    check(e['mas35']['+ todo']['adopta'] and not e['mas25']['+ todo']['adopta'],
          'zonas y 4+ goles suman en la cola (3,5) y no en 2,5')
    import patrones_liga as pl
    check('mas15' in pl.OBJETIVOS and set(pl.RASGOS_TEMPORADA) <= set(pl.RASGOS_V3),
          'patrones_liga corrige ya «más de 1,5» y conoce los rasgos de temporada')
    doc = json.load(open('patrones_liga.json', encoding='utf-8'))
    check('mas15' in doc['modelos'] and 'p4_h' in doc['rasgos_modelo']['mas35'],
          'el modelo entrenado corrige 1,5 y usa 4+ goles/zonas en 3,5')
    t = pl.Tabla()
    import pandas as pd
    t.sumar('A', 'B', pd.Timestamp('2026-08-01'), 3, 2)
    f = t.rasgos('A', 'B', pd.Timestamp('2026-08-05'))
    check(all(k in f for k in pl.RASGOS_TEMPORADA),
          'la tabla en vivo da los rasgos de temporada')
    m = json.load(open('_v316_meter_goles.json', encoding='utf-8'))
    check(m['total']['v316']['acierto'] > m['total']['hoy']['acierto']
          and m['total']['v316']['rojos'] < m['total']['hoy']['rojos'],
          'simulación de goles: %.1f %% → %.1f %%, %d → %d rojos'
          % (100 * m['total']['hoy']['acierto'], 100 * m['total']['v316']['acierto'],
             m['total']['hoy']['rojos'], m['total']['v316']['rojos']))


def probar_pantalla():
    src = open('modo_modelo.py', encoding='utf-8').read()
    check('a favor · ' in src and 'en contra</span>' in src and ' g</span>' not in src,
          'la forma dice «a favor» y «en contra», no «g»')
    check('tabla_liga as _tl' in src, 'la tarjeta enseña la tabla')
    fi = open('formato_ia.py', encoding='utf-8').read()
    check('tl.texto(pick)' in fi and '«TABLA»' in fi, 'y Telegram también, con su guía')


def probar_equipo_y_corners():
    t = json.load(open('_v316_tabla_mercados.json', encoding='utf-8'))
    ge = t['goles_equipo']
    check(ge['local_mas15']['+ tabla']['adopta'] and ge['visit_mas15']['+ tabla']['adopta'],
          'la tabla (diferencia de goles, a favor/en contra, posición) suma en «equipo mete 2+»')
    check(all(t['corners'][k]['+ tabla']['adopta'] for k in ('local_mas_4.5', 'visit_mas_3.5')),
          'y en los córners de cada equipo, en todas las ligas con córners')
    import patrones_liga as pl
    check(set(pl.RASGOS_TABLA) <= set(pl.RASGOS_V4) and 'gdpj_h' in pl.RASGOS_TABLA,
          'patrones_liga prueba la tabla de la temporada en cada mercado')
    c = json.load(open('_v316_corners_tabla.json', encoding='utf-8'))
    check(c['adopta'] and c['tabla']['p5_vs_prod'] > 0
          and c['tabla']['acierto_70_80'] > c['prod']['acierto_70_80'],
          'córners con tabla contra producción: p5 %+.5f, franja 70-80 %% %.1f %% -> %.1f %%'
          % (c['tabla']['p5_vs_prod'], 100 * c['prod']['acierto_70_80'],
             100 * c['tabla']['acierto_70_80']))
    import corners_tabla as ct
    doc = ct.cargar()
    check(doc.get('activo') and set(doc.get('modelos') or {}) == {'local', 'visita'},
          'el modelo de córners entrenado está activo')
    import rendimiento_equipos as rq
    r = rq.corners_equipo('premier', 'Arsenal', 'Wolves')
    check(r and r.get('fuente_lambda') == 'tabla' and r['lambda_home'] > r['lambda_away'],
          'la tarjeta usa las λ de córners con tabla (Arsenal %.1f, Wolves %.1f)'
          % ((r or {}).get('lambda_home', 0), (r or {}).get('lambda_away', 0)))
    guardado = dict(ct._DOC)
    try:
        ct._DOC.clear()
        ct._DOC.update(dict(guardado, activo=False))
        check(ct.lambdas('premier', 'Arsenal', 'Wolves') is None,
              'si el fichero no dice que ganó, producción no cambia')
    finally:
        ct._DOC.clear()
        ct._DOC.update(guardado)


if __name__ == '__main__':
    print('=== 1. Flashscore ===')
    probar_flashscore()
    print('\n=== 2. la tabla ===')
    probar_tabla()
    print('\n=== 3. lo medido ===')
    probar_medido()
    print('\n=== 4. la pantalla ===')
    probar_pantalla()
    print('\n=== 5. goles por equipo y córners con la tabla ===')
    probar_equipo_y_corners()
    print('\n' + '=' * 40)
    print('TODO OK' if not FALLOS else '%d FALLOS' % len(FALLOS))
    raise SystemExit(1 if FALLOS else 0)
