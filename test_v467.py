#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v467 — «¿por qué no me das bien los logos? Valida uno por uno». Ath Madrid vs La Coruna salía
con una «A» y una «L»: los escudos sólo venían de ESPN. Ahora cada escudo se descarga y se
comprueba, y los que faltan salen del MISMO partido en FotMob/Flashscore (fútbol) o 365Scores
(la foto del tenista). Sin red: respuestas simuladas."""
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
FALLOS = []


def check(cond, msg):
    print(('OK   ' if cond else 'FALLO') + ' ' + msg)
    if not cond:
        FALLOS.append(msg)


def u(t):
    return dt.datetime.fromisoformat(t).replace(tzinfo=dt.timezone.utc)


class Resp:
    def __init__(self, codigo, tipo, cuerpo):
        self.status_code, self.headers, self.cuerpo = codigo, {'content-type': tipo}, cuerpo

    def iter_content(self, n):
        for i in range(0, len(self.cuerpo), n):
            yield self.cuerpo[i:i + n]

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def probar():
    import escudos as es
    check(es._jugador('Liudmila Samsonova', 'Samsonova L.') and es._jugador('Adolfo Daniel Vallejo', 'Vallejo D.')
          and es._jugador('Darwin Blanch', 'Blanch Dar.') and es._jugador('Ane Mintegi Del Olmo', 'Mintegi Del Olmo A.')
          and es._jugador('Kyoka Okamura', 'Kyoka Okamura'), 'v467: el tenista se reconoce por apellido e inicial')
    check(not es._jugador('Kaili Demi Teso', 'Teso N.') and not es._jugador('Lorenzo Sonego', 'Musetti L.'),
          'v467: y la hermana (otra inicial) o el otro jugador, no')
    check(es._cat('Serie A (Italia, femenil)', 'Milan', 'Ternana') == (True, False) and es._cat('', 'Juventus (W)', 'Roma (W)') == (True, False)
          and es._cat('', 'Atletico Madrid', 'Albacete U19') == (False, True) and es._cat('LaLiga', 'Calcio Como 1907', 'Mainz 05') == (False, False),
          'v467: la categoría (femenil, juvenil) se lee de la liga y los nombres')

    dia = [{'ini': u('2026-10-24T19:00:00'), 'home': 'Atlético Madrid', 'away': 'Deportivo A Coruña', 'hid': 9906, 'aid': 9783, 'cat': (False, False)},
           {'ini': u('2026-10-24T19:00:00'), 'home': 'Atlético Madrid (W)', 'away': 'Deportivo A Coruña (W)', 'hid': 1, 'aid': 2, 'cat': (True, False)},
           {'ini': u('2026-10-25T17:00:00'), 'home': 'AGF', 'away': 'Viborg', 'hid': 8071, 'aid': 8070, 'cat': (False, False)},
           {'ini': u('2026-10-24T14:00:00'), 'home': 'Queens Park Rangers', 'away': 'Swansea City', 'hid': 10204, 'aid': 10003, 'cat': (False, False)},
           {'ini': u('2026-10-25T20:00:00'), 'home': 'Paris Saint-Germain', 'away': 'Lyon', 'hid': 9847, 'aid': 9748, 'cat': (False, False)}]
    cache = {d: dia for d in ('20261024', '20261025', '20261023', '20261026')}
    L = es.LOGO.format
    check(es.buscar('Ath Madrid vs La Coruna', '2026-10-24 19:00:00', cache, 'LaLiga') == (L(id=9906), L(id=9783)),
          'v467: «Ath Madrid vs La Coruna» = Atlético Madrid - Deportivo A Coruña (el varonil, no el femenil)')
    check(es.buscar('Atlético Madrid vs Deportivo La Coruña', '2026-10-24 19:00:00', cache, 'Liga F (España, femenil)') == (L(id=1), L(id=2)),
          'v467: y el femenil lleva el escudo del femenil')
    check(es.buscar('Aarhus vs Viborg', '2026-10-25 17:00:00', cache, 'Superliga') == (L(id=8071), L(id=8070)),
          'v467: «Aarhus» = AGF por los alias del proyecto (en cualquier sentido)')
    check(es.buscar('QPR vs Swansea', '2026-10-24 14:00:00', cache) == (L(id=10204), L(id=10003)), 'v467: los alias del proyecto (QPR)')
    check(es.buscar('Swansea vs QPR', '2026-10-24 14:00:00', cache) == (L(id=10003), L(id=10204)), 'v467: con los lados al revés, cada escudo en su lado')
    check(es.buscar('Paris FC vs Lyon', '2026-10-25 20:00:00', cache) is None, 'v467: Paris FC NUNCA lleva el escudo del PSG')
    check(es.buscar('Ath Madrid vs La Coruna', '2026-10-27 19:00:00', cache) is None, 'v467: otro día, otro partido: nada')

    import requests
    real = requests.get
    respuestas = {'https://x/real.png': Resp(200, 'image/png', b'x' * 3000),
                  'https://static.flashscore.com/res/image/data/vacio.png': Resp(200, 'image/png', b'x' * 120),
                  'https://imagecache.365scores.com/blanco': Resp(200, 'image/png', b'x' * 694),
                  'https://imagecache.365scores.com/foto': Resp(200, 'image/png', b'x' * 1500),
                  'https://x/404.png': Resp(404, 'text/html', b'x' * 6000),
                  'https://x/html.png': Resp(200, 'text/html', b'x' * 6000)}

    def falso(url, **kw):
        if url == 'https://x/caida.png':
            raise requests.ConnectionError('sin red')
        return respuestas[url]
    requests.get = falso
    try:
        c = {}
        check(es.valida('https://x/real.png', c) == 'https://x/real.png' and es.valida('https://imagecache.365scores.com/foto', c),
              'v467: la imagen de verdad pasa')
        check(not es.valida('https://static.flashscore.com/res/image/data/vacio.png', c) and not es.valida('https://imagecache.365scores.com/blanco', c),
              'v467: el transparente de Flashscore y el cuadro en blanco de 365 NO pasan')
        check(not es.valida('https://x/404.png', c) and not es.valida('https://x/html.png', c)
              and not es.valida('https://a.espncdn.com/i/teamlogos/soccer/500/default-team-logo-500.png', c),
              'v467: ni un 404, ni una página, ni el escudo genérico de ESPN')
        check(es.valida('https://x/caida.png', c) == 'https://x/caida.png', 'v467: si falla la red no se sabe: se deja')
        filas = [{'deporte': 'Fútbol', 'partido': 'A vs B', 'logo_h': 'https://x/real.png', 'logo_a': 'https://x/404.png', 'inicio': None}]
        st = es.poner(filas)
        check(filas[0]['logo_h'] == 'https://x/real.png' and filas[0]['logo_a'] is None and st['quitados'] == 1,
              'v467: poner valida TODO lo que ya venía (ESPN incluido) y quita lo que no es imagen')
    finally:
        requests.get = real

    ex = open('exportar_web.py', encoding='utf-8').read()
    check(0 < ex.find('espn_vivo.emparejar(') < ex.find('escudos.poner(picks + analisis)'), 'v467: los escudos se validan después de ESPN, en cada pasada')
    app = open(os.path.join('web', 'app.js'), encoding='utf-8').read()
    check('escudo letra' not in app and 'SILUETA(dep)' in app and "im.outerHTML = SILUETA(im.dataset.dep)" in app,
          'v467: sin escudo, o si la imagen no carga, una silueta; nunca una letra suelta')
    check(app.count('escudo(p.logo_h, L, p.deporte)') == 4 and app.count('escudo(p.logo_a, V, p.deporte)') == 4,
          'v467: todas las tarjetas pasan el deporte (persona para el tenis)')


if __name__ == '__main__':
    probar()
    print('\n' + '=' * 40)
    print('TODO OK' if not FALLOS else '%d FALLOS' % len(FALLOS))
    raise SystemExit(1 if FALLOS else 0)
