#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v104 — Calidad del abridor y tamaño del bullpen en la KBO, desde Naver.

Qué se buscaba y qué se encontró
--------------------------------
La v98 dejó la KBO batiendo al ELO pero NO al mercado (ROI −9 a −13 %), y la
conclusión fue que faltaban los datos que las casas sí usan. Statiz —la fuente
obvia para OPS y FIP— quedó descartada en la v102: su `robots.txt` prohíbe la
recolección automatizada y nombra explícitamente a los agentes de Anthropic.

La vía que quedaba era Naver, y estaba más cerca de lo que parecía. El endpoint
`/schedule/games/{gameId}/preview` de la misma API que el proyecto ya usa
devuelve, para cada partido:

  · `homeStarter.currentSeasonStats` — ERA, WHIP, entradas, K, BB, HR y
    victorias del abridor **a fecha del partido** (`gday`), o sea acumulado
    hasta ese día y no la temporada completa. Eso es lo que lo hace utilizable:
    no hay fuga, es exactamente lo que se sabía antes de empezar.
  · `homeTeamLineUp.pitcherBullpen` — la lista de relevistas disponibles. Sólo
    nombres y posición, sin estadística: da el TAMAÑO del bullpen, no su carga.

Y el `gameId` que hacía falta para pedirlo ya venía en la respuesta de
`kbo_naver._juegos`; simplemente se descartaba al construir la fila.

Lo que esto es y lo que no
--------------------------
Es calidad del ABRIDOR, que es la mitad grande del pitcheo de un partido, más
una señal débil de profundidad del bullpen. NO es carga de bullpen (cuántos
lanzamientos llevan los relevistas en los últimos días), que sigue sin fuente:
el payload no trae estadística por relevista.

Se cachea en disco porque son miles de peticiones y la respuesta de un partido
pasado no cambia nunca.

Uso:
    python kbo_preview.py --desde 2025-03-01 --hasta 2026-08-06
"""
import argparse
import json
import logging
import os
import sys
import time
from typing import Dict, List, Optional

import pandas as pd
import requests

logger = logging.getLogger(__name__)

BASE = 'https://api-gw.sports.naver.com/schedule/games/{gid}/preview'
CABECERAS = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://m.sports.naver.com/'}
CACHE = 'kbo_preview_cache'
SALIDA = 'kbo_preview.csv'
# Cortesía con la fuente: el proyecto ya usa esta API para el calendario y no
# tiene sentido castigarla por unos cientos de partidos.
PAUSA = 0.35
TIMEOUT = 25


def _num(x) -> Optional[float]:
    try:
        return float(str(x).strip())
    except (TypeError, ValueError):
        return None


def _stats_abridor(bloque: dict) -> Dict[str, Optional[float]]:
    """ERA/WHIP y derivados del abridor, a fecha del partido."""
    s = (bloque or {}).get('currentSeasonStats') or {}
    inn = _num(s.get('inn'))
    kk, bb, hr = _num(s.get('kk')), _num(s.get('bb')), _num(s.get('hr'))
    return {
        'era': _num(s.get('era')),
        'whip': _num(s.get('whip')),
        'inn': inn,
        'juegos': _num(s.get('gameCount')),
        # tasas por 9 entradas: comparables entre lanzadores con distinta carga
        'k9': (9.0 * kk / inn) if inn and kk is not None and inn > 0 else None,
        'bb9': (9.0 * bb / inn) if inn and bb is not None and inn > 0 else None,
        'hr9': (9.0 * hr / inn) if inn and hr is not None and inn > 0 else None,
    }


def preview(gid: str, usar_cache: bool = True) -> Optional[dict]:
    """El preview de un partido, cacheado en disco."""
    os.makedirs(CACHE, exist_ok=True)
    ruta = os.path.join(CACHE, f'{gid}.json')
    if usar_cache and os.path.exists(ruta):
        try:
            with open(ruta, encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    try:
        r = requests.get(BASE.format(gid=gid), headers=CABECERAS, timeout=TIMEOUT)
        if r.status_code != 200:
            return None
        j = r.json()
    except Exception as e:
        logger.debug(f'[kbo_preview] {gid}: {type(e).__name__}: {e}')
        return None
    p = (j.get('result') or {}).get('previewData')
    if not p:
        return None
    with open(ruta, 'w', encoding='utf-8') as f:
        json.dump(p, f, ensure_ascii=False)
    time.sleep(PAUSA)
    return p


def fila(gid: str, p: dict) -> dict:
    """Una fila de features por partido, con el mismo esquema para los dos lados."""
    out = {'game_id': gid}
    for lado, clave_st, clave_lu in (('home', 'homeStarter', 'homeTeamLineUp'),
                                     ('away', 'awayStarter', 'awayTeamLineUp')):
        for k, v in _stats_abridor(p.get(clave_st)).items():
            out[f'{lado}_sp_{k}'] = v
        bp = (p.get(clave_lu) or {}).get('pitcherBullpen') or []
        out[f'{lado}_bullpen_n'] = len(bp)
        pi = (p.get(clave_st) or {}).get('playerInfo') or {}
        out[f'{lado}_sp_nombre'] = (pi.get('playerName') or '').strip()
    # La fecha se saca del propio `gameId` (`20260804KTHT02026`): `gameInfo`
    # la llama `gdate` y el id es estable y siempre está.
    out['fecha'] = (f'{gid[:4]}-{gid[4:6]}-{gid[6:8]}'
                    if len(gid) >= 8 and gid[:8].isdigit() else '')
    # Códigos de equipo, que son la clave de unión con `historico_kbo.csv`:
    # `gameInfo` los da en `hCode`/`aCode` con el mismo espacio de nombres que
    # `kbo_naver.CODIGO_A_EQUIPO`, así que se traducen aquí y el A/B puede
    # cruzar por (fecha, local, visitante) sin adivinar nada.
    gi = p.get('gameInfo') or {}
    try:
        from kbo_naver import CODIGO_A_EQUIPO
    except Exception:
        CODIGO_A_EQUIPO = {}
    out['home_team'] = CODIGO_A_EQUIPO.get(gi.get('hCode') or '', '')
    out['away_team'] = CODIGO_A_EQUIPO.get(gi.get('aCode') or '', '')
    out['estadio'] = (gi.get('stadium') or '').strip()
    return out


def ingerir(desde: str, hasta: str, limite: Optional[int] = None) -> pd.DataFrame:
    """Recorre los partidos del rango y construye la tabla de features."""
    import kbo_naver as kn
    # la API quiere las fechas CON guiones (`fromDate=2026-07-01`); sin ellos
    # devuelve 400
    juegos = kn._juegos(desde, hasta)
    ids = [g.get('gameId') for g in juegos if g.get('gameId')
           and not g.get('cancel') and not g.get('suspended')]
    if limite:
        ids = ids[:limite]
    logger.info(f'[kbo_preview] {len(ids)} partidos en {desde}..{hasta}')
    filas, fallos = [], 0
    for i, gid in enumerate(ids, 1):
        p = preview(gid)
        if not p:
            fallos += 1
            continue
        filas.append(fila(gid, p))
        if i % 100 == 0:
            logger.info(f'[kbo_preview] {i}/{len(ids)} · {fallos} sin preview')
    df = pd.DataFrame(filas)
    if df.empty:
        logger.warning('[kbo_preview] sin filas')
        return df
    # se acumula: los partidos pasados no cambian
    if os.path.exists(SALIDA):
        try:
            previo = pd.read_csv(SALIDA)
            df = pd.concat([previo, df], ignore_index=True)
        except Exception:
            pass
    df = df.drop_duplicates('game_id', keep='last').sort_values('fecha')
    from io_atomico import escribir_texto
    escribir_texto(SALIDA, df.to_csv(index=False))
    logger.info(f'[kbo_preview] {len(df)} partidos con features -> {SALIDA} '
                f'({fallos} sin preview en esta pasada)')
    return df


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument('--desde', default='2025-03-01')
    ap.add_argument('--hasta', default='2026-08-06')
    ap.add_argument('--limite', type=int, default=None)
    a = ap.parse_args()
    d = ingerir(a.desde, a.hasta, a.limite)
    if not d.empty:
        print(d[['fecha', 'home_sp_era', 'home_sp_whip', 'away_sp_era',
                 'home_bullpen_n']].tail(5).to_string(index=False))
