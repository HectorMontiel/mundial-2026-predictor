# -*- coding: utf-8 -*-
"""
v393 — ESTADÍSTICAS REALES DE FLASHSCORE PARA LAS LIGAS QUE NI ESPN NI FOTMOB
PUBLICAN.

Son las ocho de `remates_flashscore.TORNEOS`: Liga MX Femenil, Expansión MX,
Uruguay, Costa Rica, El Salvador, Primera Nacional, National League y la
Championship escocesa. ESPN no tiene su boxscore y FotMob sólo el marcador
(comprobado en la v307 y otra vez el 17-oct: 759 partidos de la Femenil en
FotMob, 0 con córners). El feed de Flashscore (`df_st_1_<id>`) sí trae
córners, tarjetas, remates, faltas, posesión y fueras de juego de cada equipo.

Los ids salen de la base de resultados que ya mantiene `resultados_flashscore`
(`resultados_flashscore*.csv.gz`), así que no hay que recorrer páginas.
Escribe `stats_flashscore/<clave>.csv.gz` con las columnas de `stats_espn` y
el mismo candado; `league_engine` y `historico_fotmob` lo inyectan después de
ESPN y FotMob, sólo en los huecos, con `stats_origen = 'flashscore'`.

Uso:
    python stats_flashscore.py                 # las ocho, todo lo que haya
    python stats_flashscore.py --dias 10       # la pasada diaria del bot
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional

import pandas as pd

import stats_espn as se

logger = logging.getLogger(__name__)

DIRECTORIO = 'stats_flashscore'
ORIGEN = 'flashscore'
HILOS = 4
PAUSA = 0.5
BASES = ('resultados_flashscore.csv.gz', 'resultados_flashscore_reciente.csv.gz')
MAPA = {
    'Corner kicks': 'corners',
    'Yellow cards': 'yellow',
    'Red cards': 'red',
    'Shots on target': 'shots_on',
    'Fouls': 'fouls',
    'Ball possession': 'possession',
    'Offsides': 'offsides',
}


# Y las que FotMob cubre a medias (sus temporadas viejas llegan sin
# estadísticas): con las dos fuentes juntas pasan de las 200 filas reales.
EXTRA = {
    'isr_premier': 'football/israel/ligat-ha-al',
    'fem_italia': 'football/italy/serie-a-women',
    'champions_femenil': 'football/europe/uefa-champions-league-women',
}


def torneos() -> Dict[str, str]:
    import remates_flashscore as rf
    return dict(rf.TORNEOS, **EXTRA)


def _nombre(n) -> str:
    import remates_flashscore as rf
    t = str(n or '').strip()
    if t.endswith(' W'):
        t = t[:-2].strip()
    return rf.ALIAS.get(t, t)


def _partidos(ruta: str, desde=None) -> List[Dict]:
    trozos = []
    for b in BASES:
        if os.path.exists(b):
            try:
                trozos.append(pd.read_csv(b, low_memory=False,
                                          usecols=['match_id', 'ini', 'ruta', 'home', 'away']))
            except Exception as e:
                logger.warning('[stats_flashscore] %s: %s', b, e)
    if not trozos:
        return []
    d = pd.concat(trozos, ignore_index=True).drop_duplicates('match_id')
    d = d[d['ruta'].astype(str).str.strip('/') == ruta.strip('/')]
    d['ini'] = pd.to_datetime(d['ini'], errors='coerce')
    d = d.dropna(subset=['ini'])
    if desde is not None:
        d = d[d['ini'] >= desde]
    return [{'fecha': r.ini.strftime('%Y-%m-%d'), 'home': _nombre(r.home),
             'away': _nombre(r.away), 'event_id': str(r.match_id)}
            for r in d.itertuples()]


def fila_de_partido(mid: str) -> Optional[Dict]:
    """Las columnas de `stats_espn`; {} si no hay estadísticas; None si
    Flashscore no respondió (se reintenta otra pasada)."""
    import remates_flashscore as rf
    try:
        st = rf.estadisticas(mid)
    except Exception:
        return None
    fila = {}
    for k, col in MAPA.items():
        for i, b in enumerate(('home', 'away')):
            v = (st.get(k) or (None, None))[i]
            if v is not None:
                fila['%s_%s' % (b, col)] = float(v)
    # Flashscore omite «Red cards» cuando no hubo ninguna
    if 'Yellow cards' in st and 'Red cards' not in st:
        fila['home_red'] = fila['away_red'] = 0.0
    # v409 — EL TOTAL DE REMATES SÓLO SI TRAE LOS BLOQUEADOS. En varias ligas
    # (National League, Uruguay, Primera Nacional, El Salvador, parte de Costa
    # Rica) Flashscore da «Total shots» SIN los bloqueados: ~16 por partido
    # contra 22-27 de ESPN y FotMob, y eso tumbaba la recta remates↔goles de
    # `stats_estimadas` (corr 0,50 → 0,43 el 19-oct). Sin ellos, el «fuera» se
    # deja vacío: mejor un hueco que un total incompleto.
    tot, den = st.get('Total shots'), st.get('Shots on target')
    if tot and den and 'Blocked shots' in st:
        for i, b in enumerate(('home', 'away')):
            if tot[i] is not None and den[i] is not None:
                fila['%s_shots_off' % b] = max(tot[i] - den[i], 0.0)
    if 'home_corners' not in fila and 'home_possession' not in fila:
        return {}
    return fila


def backfill(clave: str, dias: Optional[int] = None, hilos: int = HILOS, rehacer: bool = False) -> Dict:
    ruta = torneos().get(clave)
    if not ruta:
        return {'clave': clave, 'error': 'sin ruta de Flashscore'}
    previo = se.leer(clave, DIRECTORIO)
    ya = set(previo['event_id'].astype(str)) if len(previo) else set()
    desde = (pd.Timestamp.now('UTC').tz_localize(None).normalize()
             - pd.Timedelta(days=int(dias))) if dias else None
    pendientes = [p for p in _partidos(ruta, desde) if rehacer or p['event_id'] not in ya]
    t0 = time.time()

    def uno(p):
        time.sleep(PAUSA)
        f = fila_de_partido(p['event_id'])
        return None if f is None else dict(p, **f)

    filas, sin_respuesta = [], 0
    with ThreadPoolExecutor(max_workers=hilos) as ex:
        for r in ex.map(uno, pendientes):
            if r is None:
                sin_respuesta += 1
            else:
                filas.append(r)
    total = previo
    if filas:
        nuevas = pd.DataFrame(filas)
        for c in se.COLUMNAS:
            if c not in nuevas.columns:
                nuevas[c] = float('nan')
        total = pd.concat([previo[se.COLUMNAS], nuevas[se.COLUMNAS]], ignore_index=True)
        se._guardar(clave, total, directorio=DIRECTORIO)
    con = int(pd.to_numeric(total.get('home_corners'), errors='coerce').notna().sum()) if len(total) else 0
    return {'clave': clave, 'nuevas': len(filas), 'sin_respuesta': sin_respuesta,
            'acumulado': len(total), 'con_corners': con, 'segundos': time.time() - t0}


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument('claves', nargs='*')
    ap.add_argument('--dias', type=int, default=None)
    ap.add_argument('--hilos', type=int, default=HILOS)
    ap.add_argument('--rehacer', action='store_true', help='vuelve a pedir también lo ya guardado')
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format='%(levelname)s %(message)s')
    for c in a.claves or list(torneos()):
        try:
            r = backfill(c, a.dias, a.hilos, a.rehacer)
        except Exception as e:
            print('::warning::[stats_flashscore] %s: %s: %s' % (c, type(e).__name__, e), flush=True)
            continue
        if r.get('error'):
            print('  %-24s %s' % (c, r['error']), flush=True)
            continue
        print('  %-24s +%-5d nuevas · %5d acumuladas · %5d con córners · %d sin respuesta · %.0f s'
              % (c, r['nuevas'], r['acumulado'], r['con_corners'], r['sin_respuesta'],
                 r['segundos']), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
