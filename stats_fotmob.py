# -*- coding: utf-8 -*-
"""
v393 — ESTADÍSTICAS REALES DE FOTMOB PARA LAS LIGAS QUE ESPN NO CUBRE.

El usuario: «No podemos dejar ninguna liga sin las estadísticas, medidas
correctamente». ESPN (`stats_espn`) cubre ~55 competiciones; para el resto
—Polonia, Finlandia, Suiza, Austria, las femeniles…— el histórico sólo tenía
córners y tarjetas del generador sintético, y `media_corners_liga` devolvía
None (bien: no se inventa), así que esas ligas se quedaban sin medir.

FotMob sí las publica. La ficha de cada partido (`/match/<id>`, página
Next.js) trae córners, amarillas, rojas, remates a puerta y totales, faltas,
posesión y fueras de juego; medido el 17-oct en la Ekstraklasa 2024/25.

QUÉ ESCRIBE
`stats_fotmob/<clave>.csv.gz` con las MISMAS columnas que `stats_espn`
(`stats_espn.COLUMNAS`), y se guarda con el mismo `_guardar` (candado: no se
pisa un fichero ilegible ni se escribe uno con 30 % menos filas).
`league_engine` lo inyecta DESPUÉS de ESPN y ANTES del generador sintético,
con `stats_origen = 'fotmob'`; sólo rellena huecos, así que donde ESPN o
football-data ya tienen el dato, mandan ellos.

Uso:
    python stats_fotmob.py                     # las ligas sin ESPN, 4 temporadas
    python stats_fotmob.py polonia suiza       # sólo esas
    python stats_fotmob.py --dias 10           # la pasada diaria del bot
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

DIRECTORIO = 'stats_fotmob'
ORIGEN = 'fotmob'
HILOS = 6
PAUSA = 0.3
# Una liga se da por cubierta por ESPN con estas filas en `stats_espn/`.
MIN_ESPN = 400
# La clave de FotMob -> la columna (`stats_espn.DERIVADAS`).
MAPA = {
    'corners': 'corners',
    'yellow_cards': 'yellow',
    'red_cards': 'red',
    'ShotsOnTarget': 'shots_on',
    'fouls': 'fouls',
    'BallPossesion': 'possession',
    'Offsides': 'offsides',
}


def competiciones() -> Dict[str, List[tuple]]:
    """{clave: [(id, slug), ...]} de FotMob (ligas verificadas y femeniles)."""
    import remates_fotmob as rf
    fuera: Dict[str, List[tuple]] = {}
    for clave, lid, slug in rf.competiciones():
        if clave == 'selecciones':
            continue
        fuera.setdefault(clave, [])
        if (lid, slug) not in fuera[clave]:
            fuera[clave].append((lid, slug))
    return fuera


def ligas_sin_espn() -> List[str]:
    """Las competiciones de FotMob que ESPN no cubre (o cubre poco)."""
    fuera = []
    for clave in competiciones():
        if len(se.leer(clave)) < MIN_ESPN:
            fuera.append(clave)
    return sorted(fuera)


def fila_de_partido(mid: str) -> Optional[Dict]:
    """Las estadísticas de un partido en columnas de `stats_espn`; {} si la
    ficha no trae estadísticas y None si FotMob no respondió."""
    import fotmob_scraper as fm
    import remates_fotmob as rf
    raw = fm._next_data('https://www.fotmob.com/match/%s' % mid)
    pp = ((raw or {}).get('props') or {}).get('pageProps') or {}
    if not pp.get('general'):
        return None
    s = rf._stats_equipo(pp.get('content') or {})
    fila = {}
    for k, col in MAPA.items():
        if k in s:
            for i, b in enumerate(('home', 'away')):
                if s[k][i] is not None:
                    fila['%s_%s' % (b, col)] = float(s[k][i])
    if 'total_shots' in s and 'ShotsOnTarget' in s:
        for i, b in enumerate(('home', 'away')):
            t, a = s['total_shots'][i], s['ShotsOnTarget'][i]
            if t is not None and a is not None:
                fila['%s_shots_off' % b] = max(float(t) - float(a), 0.0)
    # el mismo detector de boxscore vacío que `stats_espn`: la posesión suma
    # ~100 en un partido de verdad y 0 cuando no hay datos.
    if (fila.get('home_possession') or 0) + (fila.get('away_possession') or 0) <= 1.0 \
            and not fila.get('home_corners') and not fila.get('away_corners'):
        return {}
    return fila


def _partidos(paginas: List[tuple], temporadas: int, desde) -> List[Dict]:
    import historico_fotmob as hf
    fuera, vistos = [], set()
    for lid, slug in paginas:
        try:
            ts = hf.temporadas(lid, slug)[:max(int(temporadas), 1)]
        except Exception as e:
            logger.warning('[stats_fotmob] temporadas de %s: %s', slug, e)
            ts = ['']
        for t in ts:
            try:
                ms = hf._temporada(lid, slug, t)
            except Exception as e:
                logger.warning('[stats_fotmob] %s %s: %s', slug, t, e)
                continue
            for m in ms:
                st = m.get('status') or {}
                if not st.get('finished') or st.get('cancelled'):
                    continue
                f = pd.to_datetime(st.get('utcTime'), errors='coerce', utc=True)
                mid = str(m.get('id'))
                if pd.isna(f) or mid in vistos:
                    continue
                f = f.tz_convert(None)
                if desde is not None and f < desde:
                    continue
                vistos.add(mid)
                fuera.append({'fecha': f.strftime('%Y-%m-%d'),
                              'home': hf._limpia((m.get('home') or {}).get('name')),
                              'away': hf._limpia((m.get('away') or {}).get('name')),
                              'event_id': mid})
            if desde is not None:
                break                 # la pasada diaria: sólo la temporada vigente
    return fuera


def backfill(clave: str, temporadas: int = 4, dias: Optional[int] = None,
             hilos: int = HILOS) -> Dict:
    paginas = competiciones().get(clave)
    if not paginas:
        return {'clave': clave, 'error': 'sin id de FotMob'}
    previo = se.leer(clave, DIRECTORIO)
    ya = set(previo['event_id'].astype(str)) if len(previo) else set()
    desde = (pd.Timestamp.now('UTC').tz_localize(None).normalize()
             - pd.Timedelta(days=int(dias))) if dias else None
    pendientes = [p for p in _partidos(paginas, temporadas, desde)
                  if p['event_id'] not in ya]
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
                filas.append(r)    # sin estadísticas también: así no se vuelve a pedir
    total = previo
    if filas:
        nuevas = pd.DataFrame(filas)
        for c in se.COLUMNAS:
            if c not in nuevas.columns:
                nuevas[c] = float('nan')
        total = pd.concat([previo[se.COLUMNAS], nuevas[se.COLUMNAS]],
                          ignore_index=True)
        se._guardar(clave, total, directorio=DIRECTORIO)
    con = int(pd.to_numeric(total.get('home_corners'), errors='coerce').notna().sum()) if len(total) else 0
    return {'clave': clave, 'nuevas': len(filas), 'sin_respuesta': sin_respuesta,
            'acumulado': len(total), 'con_corners': con,
            'segundos': time.time() - t0}


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument('claves', nargs='*')
    ap.add_argument('--temporadas', type=int, default=4)
    ap.add_argument('--dias', type=int, default=None)
    ap.add_argument('--hilos', type=int, default=HILOS)
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format='%(levelname)s %(message)s')
    claves = a.claves or ligas_sin_espn()
    print('%d competiciones: %s' % (len(claves), ' '.join(claves)), flush=True)
    for c in claves:
        try:
            r = backfill(c, a.temporadas, a.dias, a.hilos)
        except se.EscrituraPeligrosa as e:
            print('::warning::[stats_fotmob] %s' % e, flush=True)
            continue
        except Exception as e:
            print('::warning::[stats_fotmob] %s: %s: %s' % (c, type(e).__name__, e), flush=True)
            continue
        if r.get('error'):
            print('  %-24s %s' % (c, r['error']), flush=True)
            continue
        print('  %-24s +%-5d nuevas · %5d acumuladas · %5d con córners · %d sin respuesta · %.0f s'
              % (c, r['nuevas'], r['acumulado'], r['con_corners'],
                 r['sin_respuesta'], r['segundos']), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
