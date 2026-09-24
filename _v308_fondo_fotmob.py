# -*- coding: utf-8 -*-
"""
v308 — EL FONDO HISTÓRICO DE FOTMOB PARA MEDIR (no lo lee la app).

Dos mediciones lo necesitan y ninguna cabe en los 8 partidos por equipo que
guarda `remates_fotmob`:

  1. REMATES Y REMATES A PUERTA POR JUGADOR: qué probabilidad tiene un
     jugador de hacer 1, 2 o 3 remates a puerta, y qué la mueve (su puesto
     en ESE partido —delantero centro, extremo, mediapunta…—, si es titular,
     su media, lo que remata su equipo, el rival, la localía). Para medirlo
     fuera de muestra hace falta la historia de cada jugador ANTES de cada
     partido.
  2. LAS BAJAS: FotMob borra la lista de lesionados de la ficha cuando el
     partido termina, pero deja la CONVOCATORIA entera (titulares y
     suplentes) con el valor de mercado de cada jugador. Un habitual que no
     está convocado es una baja; su peso, lo que aportaba (minutos, remates,
     valor). Así se reconstruyen las bajas de todo el histórico.

Guarda, por competición, `_v308_fondo/<clave>.jsonl.gz`: un partido por
línea con marcador, estadísticas del equipo y a cada convocado con su puesto
del día (`positionId`), su puesto habitual, si fue titular, minutos, remates,
a puerta, goles, xG y valor de mercado. Reanudable: lo ya guardado no se pide.

Uso:
    python _v308_fondo_fotmob.py [claves...] [--temporadas 3] [--hilos 8]
"""
from __future__ import annotations

import gzip
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

DIR = '_v308_fondo'
LIGAS = ['premier', 'laliga', 'serie_a', 'bundesliga', 'ligue_1',
         'eredivisie', 'primeira', 'eng_championship', 'liga_mx', 'mls',
         'brasil', 'argentina', 'champions', 'europa_league']
PAUSA = 0.8


def _registro(raw, mid, liga):
    import remates_fotmob as rf
    import historico_fotmob as hf
    pp = ((raw or {}).get('props') or {}).get('pageProps') or {}
    gen = pp.get('general') or {}
    cont = pp.get('content') or {}
    if not gen:
        return None
    marcador = rf._marcador(pp)
    ste = rf._stats_equipo(cont)
    pst = {}
    for k, p in (cont.get('playerStats') or {}).items():
        pst[str((p or {}).get('id') or k)] = rf._stats_jugador(p or {})
    lu = cont.get('lineup') or {}
    lados = {}
    for i, lado in enumerate(('homeTeam', 'awayTeam')):
        t = lu.get(lado) or {}
        g = gen.get(lado) or {}
        jug = []
        for grupo, tit in (('starters', True), ('subs', False)):
            for j in t.get(grupo) or []:
                st = pst.get(str(j.get('id'))) or {}
                mins = st.get('minutes_played')
                if mins is None:
                    mins = rf._minutos(j, tit) or 0
                jug.append({
                    'id': j.get('id'), 'n': j.get('name'), 't': int(tit),
                    'min': int(mins or 0), 'pos': j.get('positionId'),
                    'up': j.get('usualPlayingPositionId'),
                    'mv': j.get('marketValue'),
                    'sh': st.get('total_shots'), 'sot': st.get('ShotsOnTarget'),
                    'g': st.get('goals'), 'xg': st.get('expected_goals')})
        unav = [{'id': u.get('id'), 'n': u.get('name'),
                 'tipo': (u.get('unavailability') or {}).get('type')}
                for u in t.get('unavailable') or []]

        def de(k):
            return (ste.get(k) or (None, None))[i]
        lados['h' if i == 0 else 'a'] = {
            'eq': hf._limpia(g.get('name')), 'id': g.get('id'),
            'goles': marcador[i] if marcador else None,
            'tiros': de('total_shots'), 'sot': de('ShotsOnTarget'),
            'xg': de('expected_goals'), 'corners': de('corners'),
            'formacion': t.get('formation'),
            'jug': jug, 'bajas': unav}
    return {'mid': mid, 'liga': liga,
            'fecha': str(gen.get('matchTimeUTCDate') or '')[:10],
            'ronda': gen.get('leagueRoundName'), **lados}


def _hechos(ruta):
    ya = set()
    if os.path.exists(ruta):
        with gzip.open(ruta, 'rt', encoding='utf-8') as f:
            for linea in f:
                try:
                    ya.add(json.loads(linea)['mid'])
                except Exception:
                    pass
    return ya


def fondo(clave, lid, slug, n_temporadas, hilos):
    import fotmob_scraper as fm
    import historico_fotmob as hf
    os.makedirs(DIR, exist_ok=True)
    ruta = os.path.join(DIR, '%s.jsonl.gz' % clave)
    ya = _hechos(ruta)
    try:
        temps = hf.temporadas(lid, slug)[:n_temporadas] or ['']
    except Exception:
        temps = ['']
    ids = []
    for i, t in enumerate(temps):
        for m in hf._temporada(lid, slug, t if i else ''):
            st = m.get('status') or {}
            if st.get('finished') and not st.get('cancelled'):
                ids.append(str(m.get('id')))
    ids = [x for x in dict.fromkeys(ids) if x not in ya]
    cerrojo = threading.Lock()
    cuenta = {'ok': 0, 'fallo': 0}

    def uno(mid):
        raw = fm._next_data('https://www.fotmob.com/match/%s' % mid)
        time.sleep(PAUSA)
        r = _registro(raw, mid, clave) if raw else None
        with cerrojo:
            if not r:
                cuenta['fallo'] += 1
                return
            with gzip.open(ruta, 'at', encoding='utf-8') as f:
                f.write(json.dumps(r, ensure_ascii=False) + '\n')
            cuenta['ok'] += 1

    with ThreadPoolExecutor(hilos) as ex:
        list(ex.map(uno, ids))
    print('%-18s temporadas %s · nuevos %d · fallos %d · antes %d'
          % (clave, temps, cuenta['ok'], cuenta['fallo'], len(ya)),
          flush=True)


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    import fotmob_ligas as fl
    import remates_fotmob as rf
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    n = 3
    hilos = 8
    if '--temporadas' in sys.argv:
        n = int(sys.argv[sys.argv.index('--temporadas') + 1])
        args = [a for a in args if a != str(n)]
    if '--hilos' in sys.argv:
        hilos = int(sys.argv[sys.argv.index('--hilos') + 1])
        args = [a for a in args if a != str(hilos)]
    ids = fl.ids()
    claves = args or LIGAS + ['selecciones']
    for c in claves:
        if c == 'selecciones':
            for lid, slug in rf.SELECCIONES:
                if lid == 114:
                    continue                 # amistosos: sin jugadores
                fondo('selecciones', lid, slug, n, hilos)
        elif c in ids:
            fondo(c, ids[c][0], ids[c][1], n, hilos)


if __name__ == '__main__':
    main()
