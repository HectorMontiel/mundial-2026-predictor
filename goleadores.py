#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Goleadores (v57) — mercados de jugador para fútbol, en TODAS las ligas.

FUENTE: el roster de ESPN (`site.api.espn.com/.../teams/{id}/roster`), el MISMO
JSON público que ya usamos para fixtures y cuotas. Gratis, sin clave, sin
scraping frágil y con cobertura de todas nuestras ligas (mex.1, usa.1, bra.1,
arg.1, eng.1, esp.1, ...). Verificado 2026-07-24: por jugador devuelve
`totalGoals`, `goalAssists`, `appearances`, `totalShots`, `shotsOnTarget`.

Alternativas descartadas (auditadas):
  · Understat — solo top-5 ligas y la temporada nueva viene vacía.
  · scores24.live — Cloudflare + SPA React (no scrapeable de forma estable).
  · FBref / API-Football — rate-limit agresivo o plan de pago.

MODELO (declarado, sin inventar):
  cuota_goleador_p = goles_p / goles_del_equipo        (su cuota histórica)
  λ_p = xG_del_equipo_en_ESTE_partido · cuota_goleador_p
  P(marca ≥1) = 1 − e^(−λ_p) · ...   (Poisson)
  P(marca 2+) = 1 − e^(−λ)(1+λ)
La cuota se calcula sobre TODOS los partidos del equipo (no solo los que jugó),
así que ya incorpora su probabilidad de ser titular — es la esperanza
incondicional correcta cuando no se conoce la alineación.
"""

import json
import logging
import os
import time
from typing import Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

ESPN_TEAMS = 'https://site.api.espn.com/apis/site/v2/sports/soccer/{liga}/teams'
ESPN_ROSTER = ('https://site.api.espn.com/apis/site/v2/sports/soccer/'
               '{liga}/teams/{tid}/roster')
CACHE_FILE = 'goleadores_cache.json'
TTL_DIAS = 3                      # el roster cambia poco; 3 días es prudente
TIMEOUT = 10
_MEM: Dict[str, dict] = {}


def _cache_cargar() -> dict:
    if _MEM:
        return _MEM
    try:
        with open(CACHE_FILE, encoding='utf-8') as f:
            _MEM.update(json.load(f))
    except Exception:
        pass
    return _MEM


def _cache_guardar():
    try:
        with open(CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(_MEM, f, ensure_ascii=False)
    except Exception as e:
        logger.warning(f"[goleadores] no se pudo guardar caché: {e}")


def _fresco(entrada: dict) -> bool:
    return (time.time() - entrada.get('ts', 0)) < TTL_DIAS * 86400


def equipos_liga(clave: str) -> List[Dict]:
    """[{id, nombre}] de la liga (ESPN). Cacheado."""
    import fixtures_espn
    code = fixtures_espn.ESPN_CODIGOS.get(clave)
    if not code:
        return []
    cache = _cache_cargar()
    ck = f'teams:{clave}'
    if ck in cache and _fresco(cache[ck]):
        return cache[ck]['data']
    try:
        r = requests.get(ESPN_TEAMS.format(liga=code), timeout=TIMEOUT,
                         headers={'User-Agent': 'Mozilla/5.0'})
        r.raise_for_status()
        bloques = (r.json().get('sports', [{}])[0]
                   .get('leagues', [{}])[0].get('teams', []))
        datos = [{'id': b['team']['id'], 'nombre': b['team']['displayName']}
                 for b in bloques]
    except Exception as e:
        logger.warning(f"[goleadores/{clave}] equipos: {type(e).__name__}: {e}")
        return cache.get(ck, {}).get('data', [])
    cache[ck] = {'ts': time.time(), 'data': datos}
    _cache_guardar()
    return datos


def _stat(cats, nombre) -> float:
    for c in cats or []:
        for s in (c.get('stats') or []):
            if s.get('name') == nombre:
                try:
                    return float(s.get('value') or 0)
                except (TypeError, ValueError):
                    return 0.0
    return 0.0


MIN_GOLES_MUESTRA = 12       # por debajo, la temporada en curso no basta
# Shrinkage de la cuota goleadora: con muestras chicas la cuota cruda es
# inestable. PRIOR_CUOTA ≈ cuota de un jugador cualquiera de la rotación;
# K_SHRINK = goles de "masa" del prior (a más goles reales, menos encoge).
PRIOR_CUOTA = 0.06
K_SHRINK = 12.0


def _roster_crudo(code: str, team_id: str, season: Optional[int]) -> List[Dict]:
    url = ESPN_ROSTER.format(liga=code, tid=team_id)
    params = {'season': season} if season else {}
    r = requests.get(url, params=params, timeout=TIMEOUT,
                     headers={'User-Agent': 'Mozilla/5.0'})
    r.raise_for_status()
    j = r.json()
    jugadores = []
    for a in j.get('athletes', []):
        cats = (a.get('statistics') or {}).get('splits', {}).get('categories')
        apar = _stat(cats, 'appearances')
        if apar <= 0:
            continue                       # no ha jugado: sin base para estimar
        jugadores.append({
            'id': a.get('id'), 'nombre': a.get('displayName'),
            'posicion': (a.get('position') or {}).get('abbreviation', ''),
            'goles': _stat(cats, 'totalGoals'), 'apariciones': apar,
            'asistencias': _stat(cats, 'goalAssists'),
            'remates': _stat(cats, 'totalShots'),
        })
    return jugadores


def plantilla_equipo(clave: str, team_id: str) -> List[Dict]:
    """Jugadores del equipo con goles/asistencias/apariciones. Usa la temporada
    en curso y, si la muestra es pobre (arranque de torneo), la ANTERIOR — que
    es la que tiene el histórico completo. Cacheado 3 días."""
    import datetime
    import fixtures_espn
    code = fixtures_espn.ESPN_CODIGOS.get(clave)
    if not code:
        return []
    cache = _cache_cargar()
    ck = f'roster:{clave}:{team_id}'
    if ck in cache and _fresco(cache[ck]):
        return cache[ck]['data']
    jugadores: List[Dict] = []
    try:
        jugadores = _roster_crudo(code, team_id, None)
        if sum(j['goles'] for j in jugadores) < MIN_GOLES_MUESTRA:
            # arranque de temporada: se cae a la anterior (histórico completo)
            previa = _roster_crudo(code, team_id,
                                   datetime.date.today().year - 1)
            if sum(j['goles'] for j in previa) > sum(j['goles'] for j in jugadores):
                jugadores = previa
    except Exception as e:
        logger.warning(f"[goleadores/{clave}] roster {team_id}: "
                       f"{type(e).__name__}: {e}")
        return cache.get(ck, {}).get('data', [])
    cache[ck] = {'ts': time.time(), 'data': jugadores}
    _cache_guardar()
    return jugadores


def _buscar_team_id(clave: str, nombre_equipo: str) -> Optional[str]:
    import name_mapper
    equipos = equipos_liga(clave)
    if not equipos:
        return None
    catalogo = {e['nombre']: e['id'] for e in equipos}
    m = name_mapper.mapear(nombre_equipo, catalogo.keys(),
                           contexto=f'goleadores→{clave}')
    return catalogo.get(m) if m else None


def mercados_goleadores(clave: str, home: str, away: str,
                        lam_h: float, lam_a: float,
                        top: int = 6) -> List[Dict]:
    """Mercados de goleador del partido: «marca en cualquier momento» y
    «marca 2+», para los `top` jugadores más probables de cada equipo.
    Devuelve [] si ESPN no cubre la liga o no hay datos (degradación honesta)."""
    import math
    campos: List[Dict] = []
    for equipo, lam, lado in ((home, lam_h, 'h'), (away, lam_a, 'a')):
        tid = _buscar_team_id(clave, equipo)
        if not tid:
            continue
        jug = plantilla_equipo(clave, tid)
        if not jug:
            continue
        goles_equipo = sum(j['goles'] for j in jug)
        if goles_equipo <= 0:
            continue
        # cuota de cada jugador sobre los goles del equipo, con SHRINKAGE
        # bayesiano: con pocos goles de muestra la cuota cruda es inestable (un
        # jugador puede acaparar el 100 % con 2 goles). Se encoge hacia una
        # cuota típica de plantilla (PRIOR_CUOTA) con peso K_SHRINK goles.
        ranking = sorted(jug, key=lambda j: -j['goles'])[:top]
        for j in ranking:
            if j['goles'] <= 0:
                continue
            cuota_g = ((j['goles'] + K_SHRINK * PRIOR_CUOTA)
                       / (goles_equipo + K_SHRINK))
            lam_p = max(lam * cuota_g, 1e-4)
            p1 = 1 - math.exp(-lam_p)                     # marca ≥1
            p2 = 1 - math.exp(-lam_p) * (1 + lam_p)       # marca 2+
            pid = j['id']
            campos.append({'id': f'scorer_{lado}_{pid}',
                           'etiqueta': f"{j['nombre']} marca ({equipo})",
                           'valor': round(p1 * 100, 1), 'tipo': 'pct'})
            if p2 >= 0.01:
                campos.append({'id': f'scorer2_{lado}_{pid}',
                               'etiqueta': f"{j['nombre']} marca 2 o más",
                               'valor': round(p2 * 100, 1), 'tipo': 'pct'})
    return campos


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    import sys
    clave = sys.argv[1] if len(sys.argv) > 1 else 'liga_mx'
    eqs = equipos_liga(clave)
    print(f'{clave}: {len(eqs)} equipos')
    if len(sys.argv) > 3:
        camps = mercados_goleadores(clave, sys.argv[2], sys.argv[3], 1.4, 1.1)
        for c in camps:
            print(f"  {c['etiqueta']:45} {c['valor']}%")
