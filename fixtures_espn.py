#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Fixtures ESPN (v49) — PRÓXIMOS partidos por liga, SIN clave y SIN coste de API.

El barrido de Apuestas del Día (alpha_finder) se alimentaba EXCLUSIVAMENTE de
odds_actuales.json: si la captura de The Odds API fallaba o se quedaba corta,
el barrido colapsaba a "partidos evaluados: 0". Este módulo aporta una fuente
de FIXTURES independiente de las cuotas: el scoreboard JSON público de ESPN
(site.api.espn.com), el mismo que ya usa el proyecto para el Mundial y la UEFA.

Así, cada partido con jornada se evalúa SIEMPRE:
  · si hay cuota real  → Capa 1 (con EV).
  · si no hay cuota    → Capa 2 (cuota justa del modelo).

Degradación honesta: si ESPN no responde para una liga (receso, cambio de
endpoint), se devuelve [] y el barrido sigue con las demás fuentes.
"""

import logging
import time
from typing import Dict, List

import pandas as pd
import requests

logger = logging.getLogger(__name__)

ESPN_BASE = 'https://site.api.espn.com/apis/site/v2/sports/soccer/{liga}/scoreboard'

# clave interna del proyecto -> código de liga en ESPN (soccer).
# Verificado 2026-07-24: mex.1/usa.1/bra.1/arg.1 devuelven fixtures futuros.
ESPN_CODIGOS: Dict[str, str] = {
    'liga_mx': 'mex.1',
    'mls': 'usa.1',
    'brasil': 'bra.1',
    'argentina': 'arg.1',
    'premier': 'eng.1',
    'laliga': 'esp.1',
    'serie_a': 'ita.1',
    'bundesliga': 'ger.1',
    'ligue_1': 'fra.1',
    'eredivisie': 'ned.1',
    'primeira': 'por.1',
    'noruega': 'nor.1',
    'suecia': 'swe.1',
    'finlandia': 'fin.1',
    'rumania': 'rou.1',
    'irlanda': 'irl.1',
    'turquia': 'tur.1',
    'dinamarca': 'den.1',
    'china': 'chn.1',
    # (Polonia: ESPN devuelve 400 para pol.1 y está en receso hasta agosto; su
    #  cobertura llega por la vía de cuotas cuando reanuda.)
    'champions': 'uefa.champions',
    'europa_league': 'uefa.europa',
    'conference_league': 'uefa.europa.conf',
    'mundial': 'fifa.world',
}

# memoización en proceso (clave, dias) -> (timestamp, fixtures). El barrido de
# la UI ya está cacheado a nivel de Streamlit; esto evita repetir la llamada a
# ESPN dentro de una misma corrida del bot/pipeline.
_CACHE: Dict[str, tuple] = {}
_TTL = 1800  # 30 min


def fixtures_liga(clave: str, dias: int = 3) -> List[Dict]:
    """Próximos partidos (no finalizados) de una liga en [hoy, hoy+dias].
    Devuelve [{'fecha': 'YYYY-MM-DD', 'home': str, 'away': str}]."""
    code = ESPN_CODIGOS.get(clave)
    if not code:
        return []
    ck = f'{clave}:{dias}'
    ahora = time.time()
    if ck in _CACHE and ahora - _CACHE[ck][0] < _TTL:
        return _CACHE[ck][1]
    hoy = pd.Timestamp.today().normalize()
    ini = hoy.strftime('%Y%m%d')
    fin = (hoy + pd.Timedelta(days=dias)).strftime('%Y%m%d')
    fixtures: List[Dict] = []
    try:
        r = requests.get(ESPN_BASE.format(liga=code),
                         params={'dates': f'{ini}-{fin}', 'limit': 500},
                         timeout=25)
        r.raise_for_status()
        eventos = r.json().get('events', []) or []
    except Exception as e:
        logger.warning(f"[fixtures/{clave}] ESPN falló: {type(e).__name__}: {e}")
        _CACHE[ck] = (ahora, [])
        return []
    for ev in eventos:
        try:
            comp = ev['competitions'][0]
            estado = comp.get('status', ev.get('status', {})).get('type', {})
            if estado.get('completed'):
                continue                       # ya jugado → no es fixture
            loc = next(c for c in comp['competitors'] if c['homeAway'] == 'home')
            vis = next(c for c in comp['competitors'] if c['homeAway'] == 'away')
            fecha = pd.to_datetime(ev['date'])
            if fecha.tzinfo:
                fecha = fecha.tz_convert(None)
            fixtures.append({
                'fecha': fecha.strftime('%Y-%m-%d'),
                'home': loc['team']['displayName'],
                'away': vis['team']['displayName'],
            })
        except Exception:
            continue
    logger.info(f"[fixtures/{clave}] {len(fixtures)} próximos partidos (ESPN {code}).")
    _CACHE[ck] = (ahora, fixtures)
    return fixtures


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    import sys
    claves = sys.argv[1:] or ['liga_mx', 'mls', 'brasil', 'argentina']
    for c in claves:
        fs = fixtures_liga(c)
        print(f"\n{c}: {len(fs)} partidos")
        for f in fs[:6]:
            print(f"  {f['fecha']}  {f['home']} vs {f['away']}")
