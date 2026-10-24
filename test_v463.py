#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v460-v465 — la presión de todos los partidos (FotMob), los pendientes que se cierran
solos con su resultado final, el contexto para todos y los tiros. Sin red: respuestas
simuladas."""
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
FALLOS = []


def check(cond, msg):
    print(('OK   ' if cond else 'FALLO') + ' ' + msg)
    if not cond:
        FALLOS.append(msg)


class R:
    def __init__(self, data, ok=True, text=''):
        self._d, self.ok, self.text, self.status_code = data, ok, text, 200 if ok else 500

    def json(self):
        return self._d


def resumen_espn(home, away, gh, ga, terminado=True, corners=None):
    st = [{'name': 'wonCorners', 'displayValue': str(c)} for c in (corners or [])]
    return {'header': {'competitions': [{'status': {'type': {'completed': terminado, 'state': 'post' if terminado else 'in'}},
                                         'competitors': [{'homeAway': 'home', 'score': str(gh), 'team': {'displayName': home}},
                                                         {'homeAway': 'away', 'score': str(ga), 'team': {'displayName': away}}]}]},
            'boxscore': {'teams': [{'statistics': [st[0]]}, {'statistics': [st[1]]}]} if corners else {}}


class Sesion:
    """Una base y un ESPN de juguete."""
    def __init__(self, pendientes, resumenes, premium=None):
        self.pend, self.res, self.prem, self.parches = pendientes, resumenes, premium or {}, []

    def get(self, url, params=None, headers=None, timeout=None):
        if url.endswith('/rest/v1/picks'):
            return R(self.pend)
        if url.endswith('/rest/v1/picks_premium'):
            return R([{'id': k, 'apuesta': v} for k, v in self.prem.items()])
        if 'site.api.espn.com' in url:
            return R(self.res.get((params or {}).get('event')) or {})
        return R([], ok=False)

    def patch(self, url, headers=None, timeout=None, params=None, json=None):
        self.parches.append((params['id'].replace('eq.', '', 1), json))
        return R(None)


def probar():
    import liquidar_pendientes as lq
    check(lq._orden('Olympiacos', 'Sparta Prague', 'Olympiacos', 'Sparta Prague', 1, 1) == (1, 1)
          and lq._orden('Sparta Prague', 'Olympiacos', 'Olympiacos', 'Sparta Prague', 2, 0) == (0, 2),
          'v463: el marcador se pone en el orden de NUESTRO «A vs B» aunque la fuente lo tenga al revés')
    check(lq._orden('Real Madrid', 'Getafe', 'Olympiacos', 'Sparta Prague', 1, 0) is None, 'v463: si los equipos no son los mismos, no se usa')
    hace = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=20)).isoformat()
    reciente = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=50)).isoformat()
    pend = [
        {'id': 'a', 'partido': 'Olympiacos vs Sparta Prague', 'apuesta': '🔒 Pick Platino', 'deporte': 'Fútbol', 'inicio': hace, 'espn': 'soccer/all:1', 'tipo': 'pick'},
        {'id': 'b', 'partido': 'Olympiacos vs Sparta Prague', 'apuesta': 'Goles: Más de 3.5', 'deporte': 'Fútbol', 'inicio': hace, 'espn': 'soccer/all:1', 'tipo': 'pick'},
        {'id': 'c', 'partido': 'Bayern Munich vs Arsenal', 'apuesta': 'Córners: Más de 8.5', 'deporte': 'Fútbol', 'inicio': hace, 'espn': 'soccer/all:2', 'tipo': 'pick'},
        {'id': 'd', 'partido': 'Lyon vs Nice', 'apuesta': 'Gana Lyon', 'deporte': 'Fútbol', 'inicio': hace, 'espn': 'soccer/all:3', 'tipo': 'pick'},
        {'id': 'e', 'partido': 'Monterrey vs Pachuca', 'apuesta': 'Gana Monterrey', 'deporte': 'Fútbol', 'inicio': reciente, 'espn': 'soccer/all:4', 'tipo': 'pick'},
    ]
    res = {'1': resumen_espn('Sparta Prague', 'Olympiacos', 0, 1), '2': resumen_espn('Bayern Munich', 'Arsenal', 2, 2, corners=[6, 4]),
           '3': resumen_espn('Lyon', 'Nice', 1, 0, terminado=False)}
    s = Sesion(pend, res, premium={'a': 'Olympiacos o empate'})
    locales = [{'id': 'a', 'estado': 'pendiente'}, {'id': 'b', 'estado': 'vivo'}, {'id': 'x', 'estado': 'pendiente'}]
    n = lq.cerrar(locales, 'https://base', 'clave', sesion=s)
    hechos = dict((pid, j['estado']) for pid, j in s.parches)
    check(hechos.get('a') == 'verde' and hechos.get('b') == 'roja', 'v463: se cierra con el resultado de ESPN y el texto real del premium')
    check(hechos.get('c') == 'verde', 'v463: córners con el dato real de ESPN (6 + 4 = 10 > 8.5)')
    check('d' not in hechos, 'v463: si ESPN dice que aún no termina, no se cierra')
    check('e' not in hechos, 'v463: lo que empezó hace menos de lo que dura un partido, no se toca')
    check(n == 3 and locales[0]['estado'] == 'verde' and locales[0]['marcador'] == '1-0' and locales[1]['estado'] == 'roja'
          and locales[2]['estado'] == 'pendiente', 'v463: también se pone en los picks de esta pasada (el upsert no lo regresa a pendiente)')
    check(all(p[1].get('marcador') for p in s.parches), 'v463: con su marcador')
    check(lq.cerrar([], None, None) == 0, 'v463: sin claves de la base no hace nada')
    src = open('exportar_web.py', encoding='utf-8').read()
    i, j = src.find('liquidar_pendientes.cerrar(r[\'picks\'])'), src.find('n = subir_supabase(r[\'picks\'], secretos)')
    k = src.find('/rest/v1/rpc/liquidar_combinadas_usuario')
    check(0 < i < j < k, 'v463: se cierra ANTES de subir los picks, y las combinadas después')

    # v464 — el contexto para todos y los tiros
    check("if f.get('deporte') == 'Fútbol':" in src and "if f.get('estado') == 'pendiente' and f.get('deporte') == 'Fútbol':" not in src,
          'v464: el contexto también para los partidos que ya empezaron o terminaron')
    import pandas as pd
    import errores_web as ew
    h = pd.DataFrame({'date': pd.to_datetime(['2026-10-0%d' % d for d in range(1, 6)]), 'home_team': ['A', 'B', 'A', 'C', 'A'],
                      'away_team': ['B', 'A', 'C', 'A', 'D'], 'home_goals': [1, 0, 2, 1, 3], 'away_goals': [0, 0, 1, 1, 0],
                      'home_shots_on': [5, 3, 6, 2, 7], 'away_shots_on': [2, 4, 1, 5, 1], 'home_shots_off': [4, 2, 5, 3, 6], 'away_shots_off': [3, 5, 2, 4, 2]})
    p = ew._promedios(h, 'A', pd.Timestamp('2026-10-10'))
    check(p and p.get('tir') == round((9 + 9 + 11 + 9 + 13) / 5, 1) and p.get('tap') == round((5 + 4 + 6 + 5 + 7) / 5, 1),
          'v464: los tiros totales (a puerta + desviados) en los promedios')
    df = pd.DataFrame({'date': pd.to_datetime(['2026-10-01', '2026-10-03', '2026-10-05']), 'home': ['X', 'Y', 'X'], 'away': ['Y', 'X', 'Z'],
                       'gh': [2, 1, 0], 'ga': [1, 1, 3]})
    q = ew._promedios_fs(df, {'X': [0, 1, 2]}, 'X', pd.Timestamp('2026-10-10'))
    check(q and q['n'] == 3 and q['gf'] == 1.0 and q['gc'] == round(5 / 3, 2) and q['forma'] == 'GEP',
          'v464: sin histórico de su liga, los promedios salen de los resultados de Flashscore')

    js = open(os.path.join('functions', 'presion.js'), encoding='utf-8').read()
    check("API + 'matchDetails?matchId='" in js and 'momentum' in js and "uno('FirstHalf')" in js and 'compensacion' in js and 'caches.default' in js,
          'v460-v462: /presion trae de FotMob la presión, las mitades, el partido completo y la compensación (con caché)')


if __name__ == '__main__':
    probar()
    print('\n' + '=' * 40)
    print('TODO OK' if not FALLOS else '%d FALLOS' % len(FALLOS))
    raise SystemExit(1 if FALLOS else 0)
