#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test de la v343.

El usuario armó un parley de madrugada con lo que daba la app y a mediodía,
en los mismos partidos, la tarjeta enseñaba otras apuestas: «quiero entender
por qué, si está bien o mal, y que lo que aposté sea seguro, también en las
Soñadoras, que son de varios días».

Lo que se vigila:
  1. LO ANUNCIADO SE APUNTA (`anunciadas`): la primera vez, con su hora y su
     cuota; lo ya anunciado no se reescribe; lo empezado no se anuncia.
  2. LA TARJETA LO ENSEÑA si ya no está entre lo que se mete, con su estado
     («sigue entrando» o «ya no entra» y por qué); al acabar, liquidado.
  3. MIS BOLETOS: lo confirmado en la Soñadora se guarda pata a pata y cada
     pata dice cómo va: verde/roja, en juego, o si la app la sigue metiendo.

Ejecutar:  python test_v343.py
"""
import datetime as dt
import json
import os
import tempfile

FALLOS = []


def check(cond, msg):
    print(('OK   ' if cond else 'FALLO') + ' ' + msg)
    if not cond:
        FALLOS.append(msg)


def _doc(recos, inicio='2026-10-08 22:30:00'):
    return {'decisiones': {'listas': {'pronosticos': [
        {'llave': ['Santos vs Flamengo RJ', inicio, 'brasil'],
         'recomendadas_tarjeta': recos}]}}}


R1 = {'apuesta': 'Goles Flamengo RJ: Más de 0.5', 'mercado': 'Goles equipo',
      'bloque': 'goles_equipo', 'etiqueta': 'Visitante', 'linea': 0.5,
      'cuota': 1.154, 'prob': 0.66, 'prob_meter': 0.734, 'veredicto_vp': 'meter'}
R2 = {'apuesta': 'Goles: Menos de 4.5', 'mercado': 'Goles', 'bloque': 'goles',
      'linea': 4.5, 'cuota': 1.167, 'prob': 0.85, 'prob_meter': 0.83,
      'veredicto_vp': 'meter'}


def probar_anunciadas():
    import anunciadas as an
    ruta = os.path.join(tempfile.mkdtemp(), 'an.json')
    t1 = dt.datetime(2026, 10, 8, 7, 2, tzinfo=dt.timezone.utc)
    t2 = dt.datetime(2026, 10, 8, 8, 37, tzinfo=dt.timezone.utc)
    check(an.acumular(_doc([R1]), ruta, t1) == 1, 'la primera «meter» se apunta')
    check(an.acumular(_doc([dict(R1, cuota=1.143, veredicto_vp='no_meter'), R2]),
                      ruta, t2) == 1, 'la nueva se añade y la retirada no se borra')
    an._CACHE.clear()
    lst = an.del_partido({'partido': 'Santos vs Flamengo RJ',
                          'clave_liga': 'brasil'}, ruta)
    check([a['apuesta'] for a in lst] == [R1['apuesta'], R2['apuesta']],
          'las dos, en orden (%s)' % [a['apuesta'] for a in lst])
    check(lst[0]['cuota'] == 1.154 and lst[0]['desde'] == '2026-10-08T07:02:00Z',
          'con la cuota y la hora de la PRIMERA vez')
    t3 = dt.datetime(2026, 10, 8, 23, 0, tzinfo=dt.timezone.utc)
    check(an.acumular(_doc([dict(R1, apuesta='Otra')]), ruta, t3) == 0,
          'lo que se anuncia con el partido empezado no cuenta')
    e = an.estado(lst[0], [dict(R1, cuota=1.143, veredicto_vp='no_meter')])
    check(e['tono'] == 'aviso' and '1.15 → 1.14' in e['texto'],
          'el estado dice que ya no entra y por qué (%s)' % e['texto'])
    e = an.estado(lst[0], [dict(R1)])
    check(e['tono'] == 'ok', 'o que sigue entrando')
    check(an.hora_cdmx('2026-10-08T07:02:00Z') == '08/10 01:02',
          'la hora, en CDMX (%s)' % an.hora_cdmx('2026-10-08T07:02:00Z'))
    t4 = dt.datetime(2026, 10, 11, 0, 0, tzinfo=dt.timezone.utc)
    an.acumular({}, ruta, t4)
    an._CACHE.clear()
    check(not an.del_partido({'partido': 'Santos vs Flamengo RJ',
                              'clave_liga': 'brasil'}, ruta),
          'y a los dos días se olvida')


class _St:
    def __init__(self):
        self.txt = []
        self.plegados = []

    def expander(self, rot, **k):
        self.plegados.append(rot)
        return self

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def markdown(self, t, **k):
        self.txt.append(str(t))


def probar_tarjeta():
    import anunciadas as an
    import modo_modelo as mm
    ruta = os.path.join(tempfile.mkdtemp(), 'an.json')
    an.acumular(_doc([R1]), ruta, dt.datetime(2026, 10, 8, 7, 2,
                                              tzinfo=dt.timezone.utc))
    an._CACHE.clear()
    os.environ['ANUNCIADAS_FICHERO'] = ruta
    try:
        pick = {'partido': 'Santos vs Flamengo RJ', 'clave_liga': 'brasil'}
        st = _St()
        mm._bloque_anunciadas(st, pick, [R2],
                              [R2, dict(R1, cuota=1.143, veredicto_vp='no_meter')])
        t = ''.join(st.txt)
        check('📌 Antes' in t and 'Goles Flamengo RJ: Más de 0.5' in t
              and 'ya no entra' in t and 'mm-anunciada aviso' in t,
              'la tarjeta enseña lo anunciado antes, con su estado')
        st = _St()
        mm._bloque_anunciadas(st, pick, [R1], [R1])
        check(not st.txt, 'lo que se sigue enseñando no se repite')
        an.acumular(_doc([dict(R1, apuesta='Otra %d' % i) for i in range(2)]
                         + [dict(R1, apuesta='Más')]), ruta,
                    dt.datetime(2026, 10, 8, 9, 0, tzinfo=dt.timezone.utc))
        an._CACHE.clear()
        st = _St()
        mm._bloque_anunciadas(st, pick, [], [])
        check(st.plegados and '3 que ya no se enseñan' in st.plegados[0],
              'si son más de dos, plegadas y con cuántas (%s)' % st.plegados)
        # al acabar: liquidado con el mismo marcador
        jug = dict(pick, deporte='Fútbol', goles_home=0, goles_away=2,
                   fecha='2026-10-08', jugado=True)
        f = mm._filas_anunciadas_jugadas(jug, [dict(R2)])
        f = [x for x in f if x.get('apuesta') == R1['apuesta']]
        check(len(f) == 1 and f[0].get('anunciada') and f[0]['estado'] == 'cumplido',
              'y en el finalizado, con su resultado (%s)'
              % [(x.get('apuesta'), x.get('estado')) for x in f])
    finally:
        os.environ.pop('ANUNCIADAS_FICHERO', None)
        an._CACHE.clear()
    import estilo_ui as eu
    check('.mm-anunciada' in eu.CSS_VIDRIO, 'con su estilo')
    src = open('modo_modelo.py', encoding='utf-8').read()
    check('_bloque_anunciadas(st, pick, recos, _todas_recos)' in src,
          'conectado en la tarjeta del partido')
    pre = open('precalculo_dia.py', encoding='utf-8').read()
    wf = open('.github/workflows/precalculo_dia.yml', encoding='utf-8').read()
    check('anunciadas.acumular(' in pre and 'anunciadas_dia.json' in wf,
          'el precálculo lo acumula y el workflow lo publica')


def probar_boletos():
    import decisiones_dia as dd
    import sonadora_motor as sm
    import sonadora_ui as su
    ruta = os.path.join(tempfile.mkdtemp(), 'parlays.json')
    pata = {'partido': 'A vs B', 'apuesta': 'Gana A', 'mercado': '1X2',
            'bloque': 'resultado', 'etiqueta': 'Resultado', 'cuota': 1.4,
            'prob': 0.7, 'inicio': '2099-01-01T00:00:00Z', 'id': 'x'}
    doc = sm.registrar_parlay({'n_patas': 1, 'patas': [pata]}, '2026-10-08',
                              ruta, detalle=[dict(pata, sobra=1)])
    det = doc['parlays'][-1]['detalle']
    check(det and det[0]['apuesta'] == 'Gana A' and 'sobra' not in det[0]
          and det[0]['bloque'] == 'resultado',
          'el boleto confirmado se guarda pata a pata')
    orig = dd.tarjeta_de_pick
    try:
        r = {'pronosticos': [{'partido': 'A vs B'}]}
        dd.tarjeta_de_pick = lambda p: [{'apuesta': 'Gana A', 'veredicto_vp': 'meter'}]
        f = su.estado_patas({'detalle': [pata]}, r)
        check(f[0]['estado'] == 'sigue', 'por jugar: la app la sigue metiendo')
        dd.tarjeta_de_pick = lambda p: [{'apuesta': 'Gana A', 'cuota': 1.3,
                                         'prob_meter': 0.66,
                                         'veredicto_vp': 'no_meter'}]
        f = su.estado_patas({'detalle': [pata]}, r)
        check(f[0]['estado'] == 'cambio' and '1.40 → 1.30' in f[0]['texto'],
              'o ya no, y por qué (%s)' % f[0]['texto'])
    finally:
        dd.tarjeta_de_pick = orig
    # terminado: un partido archivado con su marcador. v350 — fijo y no el
    # de `jugados_ayer.json`, que rota cada día y dejaba la prueba en rojo
    # en cuanto «ayer» dejaba de ser el 7 de octubre.
    import partidos_jugados as pj
    archivado = {'partido': 'Vitoria vs Chapecoense-SC', 'home': 'Vitoria',
                 'away': 'Chapecoense-SC', 'inicio': '2026-10-07 19:00:00',
                 'fecha': '2026-10-07', 'jugado': True,
                 'goles_home': 4.0, 'goles_away': 0.0}
    orig_leer = pj._leer_precalculo
    pj._leer_precalculo = lambda dia, permitir_viejo=False: [archivado]
    try:
        q = {'partido': archivado['partido'], 'apuesta': 'Vitoria o empate',
             'mercado': 'Doble oportunidad', 'bloque': 'resultado',
             'etiqueta': 'Resultado', 'cuota': 1.12,
             'inicio': '2026-10-07T19:00:00Z'}
        f = su.estado_patas({'detalle': [q]}, {})
        check(f[0]['estado'] == 'verde' and '4-0' in f[0]['texto'],
              'terminada: verde con el marcador (%s)' % f[0]['texto'])
    finally:
        pj._leer_precalculo = orig_leer
    src = open('sonadora_ui.py', encoding='utf-8').read()
    check('detalle=_sel[\'patas\']' in src and '_mis_boletos(st, _r_todo)' in src,
          'la Soñadora guarda al confirmar y enseña «Mis boletos»')
    pv = open('patas_veredicto.py', encoding='utf-8').read()
    check("'bloque': (v.get('pick') or {}).get('bloque')" in pv,
          'las patas llevan con qué liquidarse')


if __name__ == '__main__':
    print('=== 1. lo anunciado ===')
    probar_anunciadas()
    print('\n=== 2. la tarjeta ===')
    probar_tarjeta()
    print('\n=== 3. mis boletos ===')
    probar_boletos()
    print('\n' + '=' * 40)
    print('TODO OK' if not FALLOS else '%d FALLOS' % len(FALLOS))
    raise SystemExit(1 if FALLOS else 0)
