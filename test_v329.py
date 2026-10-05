# -*- coding: utf-8 -*-
"""
v329 — pruebas: «Finalizados» trae TODOS los deportes, no sólo el fútbol.

  1. `archivar_del_pronostico` archiva tenis, NFL, MLB… con la apuesta que se
     recomendaba antes de empezar.
  2. La NFL sale con su marcador de nflverse; lo que no tiene marcador se
     queda sin él («marcador pendiente»), no se inventa.
  3. «En juego» con la duración de cada deporte, y el fútbol sigue igual.

Uso: python test_v329.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time

FALLOS = []


def check(cond, msg):
    print(('OK   ' if cond else 'FALLO') + ' ' + msg)
    if not cond:
        FALLOS.append(msg)


def main():
    import pandas as pd
    import partidos_jugados as pj
    tmp = tempfile.mkdtemp(prefix='v329_')
    # un pronóstico de la tarde del domingo 2026-10-04 (tenis, NFL, MLB…)
    h = subprocess.check_output(['git', 'log', '--format=%h', '--until=2026-10-04T18:00',
                                 '-1', '--', 'pronostico_dia.json'], text=True).strip()
    ruta = os.path.join(tmp, 'pron.json')
    if h:
        open(ruta, 'wb').write(subprocess.check_output(['git', 'show', h + ':pronostico_dia.json']))
    else:
        # sin historial de git (clon superficial): el pronóstico de hoy con las
        # horas movidas al pasado
        d = json.load(open('pronostico_dia.json', encoding='utf-8'))
        json.dump(d, open(ruta, 'w', encoding='utf-8'))
    doc = json.load(open(ruta, encoding='utf-8'))
    import dia_picks as dp
    dias = sorted({dp.dia_de(p) for p in doc['datos']['pronosticos']})
    dia = '2026-10-04' if '2026-10-04' in dias else dias[0]
    ahora = time.time() + (0 if h else 3 * 86400)
    arch = pj.archivar_del_pronostico(dia, ruta, ahora=ahora)
    deps = {p.get('deporte') for p in arch}
    check(len(deps - {'Fútbol'}) >= 1,
          'se archivan otros deportes además del fútbol (%s)' % sorted(deps))
    check(all(p.get('jugado') and 'recomendadas_previas' in p for p in arch),
          'todos como jugados y con lo que se recomendaba antes (%d)' % len(arch))
    nfl = [p for p in arch if p.get('deporte') == 'NFL']
    if nfl:
        n = pj.marcadores_otros(nfl, dia, ahora=ahora)
        con = [p for p in nfl if p.get('goles_home') is not None]
        check(n == len(con) and len(con) >= len(nfl) // 2,
              'la NFL sale con su marcador de nflverse (%d de %d)' % (len(con), len(nfl)))
        largo = pd.read_csv('historico_nfl_largo.csv', low_memory=False)
        p = con[0] if con else None
        if p:
            import nfl_datos as nd
            hh, aa = (nd.abreviatura(x) for x in p['partido'].split(' vs '))
            r = largo[(largo.home == hh) & (largo.away == aa) & largo.home_score.notna()].iloc[-1]
            check((p['goles_home'], p['goles_away']) == (r.home_score, r.away_score),
                  '%s: %s-%s, el de nflverse' % (p['partido'], p['goles_home'], p['goles_away']))
    otros = [p for p in arch if p.get('deporte') == 'Tenis'][:5]
    sin = [p for p in otros if p.get('goles_home') is None]
    check(len(sin) == len(otros), 'el tenis sin marcador conocido no se inventa (se queda pendiente)')
    # la duración de cada deporte
    ini = pd.Timestamp.now('UTC') - pd.Timedelta(hours=3)
    f = {'inicio': ini.strftime('%Y-%m-%d %H:%M:%S'), 'deporte': 'Fútbol', 'partido': 'A vs B'}
    n_ = dict(f, deporte='NFL')
    v = pj._para_la_vista([f, n_])
    check(not v[0].get('en_juego') and v[1].get('en_juego'),
          'a las 3 h el fútbol ya terminó y la NFL sigue «en juego»')
    check(pj.duracion_h({'deporte': 'Fútbol'}) == pj.HORAS_PARTIDO,
          'el fútbol conserva sus 2,5 h')


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
    print('\n' + '=' * 40)
    print('TODO OK' if not FALLOS else '%d FALLOS' % len(FALLOS))
    sys.exit(1 if FALLOS else 0)
