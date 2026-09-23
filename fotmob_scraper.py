#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Scraper de FotMob (v24) — la fuente gratuita más rica verificada.

VERIFICADO 2026-07-16 desde esta red (sondeo_fuentes_v24, VALIDACION_v24.md):
  * La API interna (www.fotmob.com/api/*) está BLINDADA: exige el header
    firmado `x-mas` y devuelve 404/403 con requests planos.
  * PERO las páginas Next.js incrustan TODO el JSON en <script id="__NEXT_DATA__">
    y se sirven con HTTP 200 a un requests con User-Agent normal:
      - /leagues/{id}/overview/{slug}: tabla, temporadas, TODOS los partidos
        de la temporada con id (leagueOverviewMatches, ~510 en MLS) y líderes.
      - /match/{id}: xG REAL por equipo, remates (totales/a puerta), stats
        DEFENSIVAS (tackles, intercepciones, despejes, paradas), shotmap por
        JUGADOR (con xG por tiro), ratings, alineaciones, clima y momentum.
    Con esto FotMob cubre también lo que el plan v24 esperaba de Soccer24
    (que resultó inviable — ver soccer24_scraper.py).

Estrategia de datos (patrón clima.py/backfill_stats): cada partido consultado
se reduce a un extracto compacto cacheado en fotmob_cache/{id}.json
(COMMITEABLE, ~3 KB vs ~1 MB de la página) y se consolida en
historico_fotmob_{liga}.csv. La cobertura crece de forma incremental en cada
corrida del pipeline; las features solo se adoptan cuando la cobertura
permita validarlas en walk-forward (regla de oro).

Uso:
    python fotmob_scraper.py --backfill mls --max 30
    python fotmob_scraper.py --partido 5070991
"""

import argparse
import json
import logging
import os
import re
import time
from typing import Dict, List, Optional

import pandas as pd
import requests

logger = logging.getLogger(__name__)

UA = {'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                     'AppleWebKit/537.36 (KHTML, like Gecko) '
                     'Chrome/126.0.0.0 Safari/537.36')}
CACHE_DIR = 'fotmob_cache'
PAUSA_SEG = 1.5          # cortesía entre páginas de partido

# Ids de liga en FotMob (slug solo decorativo: la web redirige por id)
FOTMOB_LEAGUE_IDS = {
    'mls': (130, 'mls'),
    'liga_mx': (230, 'liga-mx'),
    'premier': (47, 'premier-league'),
    'laliga': (87, 'laliga'),
    'serie_a': (55, 'serie-a'),
    'bundesliga': (54, 'bundesliga'),
    'ligue_1': (53, 'ligue-1'),
    'eredivisie': (57, 'eredivisie'),
    'primeira': (61, 'liga-portugal'),
    'champions': (42, 'champions-league'),
}

# Títulos de FotMob -> columnas compactas (los títulos son estables en inglés)
STATS_INTERES = {
    'Expected goals (xG)': 'xg',
    'Total shots': 'tiros',
    'Shots on target': 'tiros_puerta',
    'Big chances': 'ocasiones_claras',
    'Ball possession': 'posesion',
    'Tackles': 'entradas',
    'Interceptions': 'intercepciones',
    'Clearances': 'despejes',
    'Keeper saves': 'paradas',
    'Fouls committed': 'faltas',
    'Corners': 'corners',
    # v303 — las tarjetas, que faltaban: son la otra mitad de lo que el
    # usuario juega además de los goles, y FotMob las publica en el mismo
    # bloque de estadísticas del partido.
    'Yellow cards': 'amarillas',
    'Red cards': 'rojas',
}


def _next_data(url: str) -> Optional[dict]:
    """Descarga una página de FotMob y devuelve el JSON de __NEXT_DATA__."""
    try:
        r = requests.get(url, headers=UA, timeout=30)
        r.raise_for_status()
        m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', r.text, re.S)
        if not m:
            logger.warning(f"[fotmob] sin __NEXT_DATA__ en {url}")
            return None
        return json.loads(m.group(1))
    except Exception as e:
        logger.warning(f"[fotmob] {url}: {type(e).__name__}: {e}")
        return None


def partidos_liga(clave: str) -> pd.DataFrame:
    """Partidos de la temporada vigente de la liga (id, fecha, equipos, marcador,
    finalizado) desde la página de overview — 1 sola petición."""
    if clave not in FOTMOB_LEAGUE_IDS:
        raise ValueError(f"liga sin id FotMob: {clave}")
    lid, slug = FOTMOB_LEAGUE_IDS[clave]
    data = _next_data(f'https://www.fotmob.com/leagues/{lid}/overview/{slug}')
    if not data:
        return pd.DataFrame()
    ov = data['props']['pageProps'].get('overview') or {}
    filas = []
    for p in ov.get('leagueOverviewMatches') or []:
        st = p.get('status') or {}
        utc = st.get('utcTime') or p.get('time')
        filas.append({
            'match_id': str(p.get('id')),
            'fecha': pd.to_datetime(utc, errors='coerce', utc=True),
            'home': (p.get('home') or {}).get('name'),
            'away': (p.get('away') or {}).get('name'),
            'gh': (p.get('home') or {}).get('score'),
            'ga': (p.get('away') or {}).get('score'),
            'finalizado': bool(st.get('finished')),
        })
    df = pd.DataFrame(filas)
    if not df.empty:
        df['fecha'] = df['fecha'].dt.tz_localize(None)
    return df


def _stat_par(valor) -> List:
    """FotMob publica cada stat como [home, away] (números o '55%')."""
    def _num(x):
        if isinstance(x, str):
            x = x.replace('%', '').strip()
        try:
            return float(x)
        except (TypeError, ValueError):
            return None
    if isinstance(valor, (list, tuple)) and len(valor) >= 2:
        return [_num(valor[0]), _num(valor[1])]
    return [None, None]


def detalle_partido(match_id: str, forzar: bool = False) -> Optional[Dict]:
    """Extracto compacto del partido (cacheado en disco)."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    ruta = os.path.join(CACHE_DIR, f'{match_id}.json')
    if not forzar and os.path.exists(ruta):
        with open(ruta, encoding='utf-8') as f:
            return json.load(f)

    data = _next_data(f'https://www.fotmob.com/match/{match_id}')
    if not data:
        return None
    pp = data['props']['pageProps']
    gen = pp.get('general') or {}
    cont = pp.get('content') or {}

    out = {
        'match_id': str(match_id),
        'fecha': (gen.get('matchTimeUTCDate') or '')[:10],
        'home': (gen.get('homeTeam') or {}).get('name'),
        'away': (gen.get('awayTeam') or {}).get('name'),
        'liga_id': gen.get('leagueId'),
    }

    # --- stats de equipo (periodo completo) ---
    periodos = ((cont.get('stats') or {}).get('Periods') or {})
    grupos = (periodos.get('All') or {}).get('stats') or []
    for grupo in grupos:
        for s in grupo.get('stats') or []:
            titulo = s.get('title')
            if titulo in STATS_INTERES:
                h, a = _stat_par(s.get('stats'))
                base = STATS_INTERES[titulo]
                # el primer valor gana (los títulos se repiten entre grupos)
                out.setdefault(f'{base}_h', h)
                out.setdefault(f'{base}_a', a)

    # --- shotmap por jugador: remates reales (lo que el MAT necesita) ---
    tiros = ((cont.get('shotmap') or {}).get('shots')) or []
    por_jugador: Dict[str, Dict] = {}
    for t in tiros:
        nombre = t.get('playerName')
        if not nombre:
            continue
        d = por_jugador.setdefault(nombre, {
            'team_id': t.get('teamId'), 'tiros': 0, 'a_puerta': 0,
            'goles': 0, 'xg': 0.0})
        d['tiros'] += 1
        d['a_puerta'] += 1 if t.get('isOnTarget') else 0
        d['goles'] += 1 if t.get('eventType') == 'Goal' else 0
        d['xg'] += float(t.get('expectedGoals') or 0.0)
    for d in por_jugador.values():
        d['xg'] = round(d['xg'], 3)
    out['remates_jugador'] = por_jugador

    # --- ratings medios por equipo (de la alineación) ---
    lineup = cont.get('lineup') or {}
    for lado, equipo in (('h', 'homeTeam'), ('a', 'awayTeam')):
        jugadores = []
        eq = lineup.get(equipo) or {}
        for grupo in ('starters', 'subs'):
            for jug in eq.get(grupo) or []:
                rating = ((jug.get('performance') or {}).get('rating')
                          or jug.get('rating'))
                try:
                    jugadores.append(float(rating))
                except (TypeError, ValueError):
                    pass
        out[f'rating_{lado}'] = round(sum(jugadores) / len(jugadores), 3) \
            if jugadores else None

    with open(ruta, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False)
    return out


def backfill_liga(clave: str, max_partidos: int = 30) -> pd.DataFrame:
    """Consolida en historico_fotmob_{clave}.csv los extractos de los últimos
    partidos FINALIZADOS de la liga (máximo `max_partidos` páginas nuevas por
    corrida; el resto sale de caché). Cobertura incremental, sin martillear."""
    df = partidos_liga(clave)
    if df.empty:
        logger.warning(f"[fotmob] {clave}: sin partidos (¿bloqueo temporal?).")
        return pd.DataFrame()
    fin = df[df['finalizado']].sort_values('fecha', ascending=False)
    filas, nuevos = [], 0
    for f in fin.itertuples(index=False):
        en_cache = os.path.exists(os.path.join(CACHE_DIR, f'{f.match_id}.json'))
        if not en_cache:
            if nuevos >= max_partidos:
                continue
            nuevos += 1
            time.sleep(PAUSA_SEG)
        det = detalle_partido(f.match_id)
        if det:
            plano = {k: v for k, v in det.items() if k != 'remates_jugador'}
            plano['n_rematadores'] = len(det.get('remates_jugador') or {})
            filas.append(plano)
    out = pd.DataFrame(filas)
    if not out.empty:
        out = out.sort_values('fecha').reset_index(drop=True)
        out.to_csv(f'historico_fotmob_{clave}.csv', index=False)
        logger.info(f"[fotmob] {clave}: {len(out)} partidos con stats reales "
                    f"({nuevos} nuevos esta corrida) → historico_fotmob_{clave}.csv")
    return out


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    ap = argparse.ArgumentParser()
    ap.add_argument('--backfill', nargs='+', help='claves de liga (mls liga_mx ...)')
    ap.add_argument('--max', type=int, default=30, help='páginas nuevas por liga')
    ap.add_argument('--partido', help='extracto de un match_id concreto')
    args = ap.parse_args()
    if args.partido:
        print(json.dumps(detalle_partido(args.partido, forzar=True),
                         ensure_ascii=False, indent=2))
    for clave in args.backfill or []:
        backfill_liga(clave, max_partidos=args.max)
