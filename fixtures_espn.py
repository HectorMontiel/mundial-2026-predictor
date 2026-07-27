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
from typing import Dict, List, Optional

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
    # v68: las 40 competiciones nuevas se inyectan más abajo desde
    # config_ligas_espn.ESPN_CODIGOS_V68 (generado).
    'champions': 'uefa.champions',
    'europa_league': 'uefa.europa',
    'conference_league': 'uefa.europa.conf',
    'mundial': 'fifa.world',
}

# v68 — Competiciones nuevas. Sin esta línea, `alpha_finder.barrido_*` NO las
# recorre: filtra por `clave in fixtures_espn.ESPN_CODIGOS`, así que una liga
# entrenada y disponible pero ausente de este mapa nunca llegaría a Apuestas
# del Día. Las que se entrenan con football-data también van aquí, porque su
# histórico viene del CSV pero sus PRÓXIMOS partidos y cuotas salen de ESPN.
try:
    from config_ligas_espn import ESPN_CODIGOS_V68 as _CODIGOS_V68
    for _k, _v in _CODIGOS_V68.items():
        ESPN_CODIGOS.setdefault(_k, _v)
except Exception:                       # degradación limpia al catálogo previo
    pass

# memoización en proceso (clave, dias) -> (timestamp, fixtures). El barrido de
# la UI ya está cacheado a nivel de Streamlit; esto evita repetir la llamada a
# ESPN dentro de una misma corrida del bot/pipeline.
_CACHE: Dict[str, tuple] = {}
_TTL = 1800  # 30 min


# timeout corto: un scoreboard responde en <2 s cuando está sano. Un timeout
# largo × muchas ligas secuenciales colgaba el barrido en Streamlit Cloud (v50.1).
TIMEOUT = 8


def _am2dec(ml):
    """Cuota americana (moneyline) → decimal. v52."""
    try:
        ml = float(str(ml).replace('+', ''))
    except (TypeError, ValueError):
        return None
    if ml == 0:
        return None
    return round(1 + ml / 100, 3) if ml > 0 else round(1 + 100 / abs(ml), 3)


def _odds_de_evento(comp: dict) -> dict:
    """v52: extrae las cuotas 1X2 y O/U 2.5 que ESPN incluye en el MISMO JSON
    del scoreboard (proveedor DraftKings/consenso). Cero coste, sin clave. Es la
    fuente que rellena la mayoría de los partidos que The Odds API/Betexplorer
    no cubren. Devuelve {} si el evento no trae cuotas usables."""
    odds_list = comp.get('odds') or []
    if not odds_list:
        return {}
    o = odds_list[0] or {}

    def _lado(d):
        d = d or {}
        for k in ('close', 'open'):
            sub = d.get(k) or {}
            if sub.get('odds') is not None:
                return _am2dec(sub['odds'])
        return None

    ml = o.get('moneyline') or {}
    oh, oa = _lado(ml.get('home')), _lado(ml.get('away'))
    dv = (o.get('drawOdds') or {}).get('moneyLine')
    od = _am2dec(dv) if dv is not None else None
    salida = {}
    if oh and od and oa:
        salida.update({'odd_home': oh, 'odd_draw': od, 'odd_away': oa,
                       'casa': o.get('provider', {}).get('name') or 'ESPN'})
    # over/under 2.5 (solo si la línea es 2.5)
    total = o.get('total') or {}
    if (o.get('overUnder') == 2.5) or (str(total.get('over', {}).get('close', {})
                                           .get('line', '')).lstrip('o') == '2.5'):
        over = ((total.get('over') or {}).get('close') or
                (total.get('over') or {}).get('open') or {})
        under = ((total.get('under') or {}).get('close') or
                 (total.get('under') or {}).get('open') or {})
        oo, ou = _am2dec(over.get('odds')), _am2dec(under.get('odds'))
        if oo:
            salida['odd_over25'] = oo
        if ou:
            salida['odd_under25'] = ou
    return salida


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
                         timeout=TIMEOUT)
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
            fx = {
                'fecha': fecha.strftime('%Y-%m-%d'),
                'home': loc['team']['displayName'],
                'away': vis['team']['displayName'],
                'event_id': ev.get('id'),      # v64: para las cuotas por evento
            }
            fx.update(_odds_de_evento(comp))   # v52: cuotas ESPN si las hay
            fixtures.append(fx)
        except Exception:
            continue
    logger.info(f"[fixtures/{clave}] {len(fixtures)} próximos partidos (ESPN {code}).")
    _CACHE[ck] = (ahora, fixtures)
    return fixtures


# v59: otros deportes en el MISMO scoreboard de ESPN (mismo patrón, sin clave).
# Verificado 2026-07-24: MLB devuelve 57 partidos programados; la NBA 0 por
# estar fuera de temporada (correcto, no es un fallo).
ESPN_DEPORTES = {
    'mlb': 'baseball/mlb',
    'nba': 'basketball/nba',
}
ESPN_BASE_DEP = 'https://site.api.espn.com/apis/site/v2/sports/{path}/scoreboard'


def fixtures_deporte(deporte: str, dias: int = 2) -> List[Dict]:
    """Próximos partidos de un deporte NO futbolístico (mlb, nba) desde ESPN.
    Devuelve [{'fecha','home','away'}] con los nombres que publica ESPN."""
    path = ESPN_DEPORTES.get(deporte)
    if not path:
        return []
    ck = f'dep:{deporte}:{dias}'
    ahora = time.time()
    if ck in _CACHE and ahora - _CACHE[ck][0] < _TTL:
        return _CACHE[ck][1]
    hoy = pd.Timestamp.today().normalize()
    ini = hoy.strftime('%Y%m%d')
    fin = (hoy + pd.Timedelta(days=dias)).strftime('%Y%m%d')
    salida: List[Dict] = []
    try:
        r = requests.get(ESPN_BASE_DEP.format(path=path),
                         params={'dates': f'{ini}-{fin}', 'limit': 300},
                         timeout=TIMEOUT, headers={'User-Agent': 'Mozilla/5.0'})
        r.raise_for_status()
        eventos = r.json().get('events', []) or []
    except Exception as e:
        logger.warning(f"[fixtures/{deporte}] ESPN falló: {type(e).__name__}: {e}")
        _CACHE[ck] = (ahora, [])
        return []
    for ev in eventos:
        try:
            comp = ev['competitions'][0]
            if comp.get('status', ev.get('status', {})).get('type', {}).get('completed'):
                continue
            loc = next(c for c in comp['competitors'] if c['homeAway'] == 'home')
            vis = next(c for c in comp['competitors'] if c['homeAway'] == 'away')
            fecha = pd.to_datetime(ev['date'])
            if fecha.tzinfo:
                fecha = fecha.tz_convert(None)
            salida.append({'fecha': fecha.strftime('%Y-%m-%d'),
                           'home': loc['team']['displayName'],
                           'away': vis['team']['displayName']})
        except Exception:
            continue
    logger.info(f"[fixtures/{deporte}] {len(salida)} próximos partidos (ESPN).")
    _CACHE[ck] = (ahora, salida)
    return salida


# v60: competiciones de SELECCIONES NACIONALES. Tras el Mundial 2026 la vista
# «Partidos Internacionales» debe mostrar lo que viene de verdad: amistosos,
# Nations League y clasificatorias. Verificado 2026-07-24: 165 partidos
# programados a 200 días (amistosos desde el 23-sep, Nations League 24-sep).
LIGAS_SELECCIONES = [
    ('fifa.friendly', 'Amistoso'),
    ('uefa.nations', 'UEFA Nations League'),
    ('fifa.worldq.uefa', 'Clasif. UEFA'),
    ('fifa.worldq.concacaf', 'Clasif. CONCACAF'),
    ('fifa.worldq.conmebol', 'Clasif. CONMEBOL'),
    ('fifa.worldq.afc', 'Clasif. AFC'),
    ('fifa.worldq.caf', 'Clasif. CAF'),
]


def fixtures_selecciones(dias: int = 210, limite: int = 200) -> List[Dict]:
    """Próximos partidos de SELECCIONES NACIONALES (amistosos, Nations League y
    clasificatorias) desde ESPN. Devuelve [{'fecha','home','away','torneo'}]
    ordenados por fecha. La ventana es amplia porque las fechas FIFA son
    ventanas concretas separadas por meses."""
    ck = f'selecciones:{dias}'
    ahora = time.time()
    if ck in _CACHE and ahora - _CACHE[ck][0] < _TTL:
        return _CACHE[ck][1]
    hoy = pd.Timestamp.today().normalize()
    ini = hoy.strftime('%Y%m%d')
    fin = (hoy + pd.Timedelta(days=dias)).strftime('%Y%m%d')
    salida: List[Dict] = []
    for liga, torneo in LIGAS_SELECCIONES:
        try:
            r = requests.get(ESPN_BASE.format(liga=liga),
                             params={'dates': f'{ini}-{fin}', 'limit': 400},
                             timeout=TIMEOUT,
                             headers={'User-Agent': 'Mozilla/5.0'})
            r.raise_for_status()
            eventos = r.json().get('events', []) or []
        except Exception as e:
            logger.warning(f"[selecciones/{liga}] {type(e).__name__}: {e}")
            continue
        for ev in eventos:
            try:
                comp = ev['competitions'][0]
                if comp.get('status', ev.get('status', {})).get('type', {}).get('completed'):
                    continue
                loc = next(c for c in comp['competitors'] if c['homeAway'] == 'home')
                vis = next(c for c in comp['competitors'] if c['homeAway'] == 'away')
                fecha = pd.to_datetime(ev['date'])
                if fecha.tzinfo:
                    fecha = fecha.tz_convert(None)
                salida.append({'fecha': fecha.strftime('%Y-%m-%d'),
                               'home': loc['team']['displayName'],
                               'away': vis['team']['displayName'],
                               'torneo': torneo})
            except Exception:
                continue
    salida.sort(key=lambda x: x['fecha'])
    salida = salida[:limite]
    logger.info(f"[selecciones] {len(salida)} próximos partidos de selecciones.")
    _CACHE[ck] = (ahora, salida)
    return salida


def fixtures_multi(claves: List[str], dias: int = 3) -> Dict[str, List[Dict]]:
    """v50.1: descarga los fixtures de MUCHAS ligas EN PARALELO. Convierte
    ~14 llamadas secuenciales (que colgaban el barrido en Streamlit Cloud) en
    un único lote concurrente. Cada liga sigue cacheada individualmente."""
    from concurrent.futures import ThreadPoolExecutor
    claves = [c for c in claves if c in ESPN_CODIGOS]
    if not claves:
        return {}
    salida: Dict[str, List[Dict]] = {}
    with ThreadPoolExecutor(max_workers=min(8, len(claves))) as ex:
        futuros = {ex.submit(fixtures_liga, c, dias): c for c in claves}
        for fut in futuros:
            c = futuros[fut]
            try:
                salida[c] = fut.result()
            except Exception as e:
                logger.warning(f"[fixtures/{c}] {type(e).__name__}: {e}")
                salida[c] = []
    return salida


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    import sys
    claves = sys.argv[1:] or ['liga_mx', 'mls', 'brasil', 'argentina']
    for c in claves:
        fs = fixtures_liga(c)
        print(f"\n{c}: {len(fs)} partidos")
        for f in fs[:6]:
            print(f"  {f['fecha']}  {f['home']} vs {f['away']}")


# ---------------------------------------------------------------------------
# v64 — CUOTAS AUTOMÁTICAS POR EVENTO (hándicap + props de jugador).
#
# El scoreboard ya daba 1X2 y O/U (v52). El endpoint `core` POR EVENTO añade,
# también gratis y sin clave:
#   · spread + spreadOdds  → el HÁNDICAP con su cuota real
#   · propBets             → ~229 mercados por partido, incluido «First
#                            Goalscorer» / «Anytime Goalscorer», con cuota
#                            DECIMAL real y el atleta al que pertenecen.
# Verificado 2026-07-24 en Liga MX (proveedor DraftKings).
# ---------------------------------------------------------------------------
ESPN_CORE_ODDS = ('https://sports.core.api.espn.com/v2/sports/soccer/leagues/'
                  '{liga}/events/{eid}/competitions/{eid}/odds')
TTL_ODDS = 900          # 15 min: las cuotas se mueven


def _num(x):
    try:
        v = float(x)
        return v if v == v else None       # descarta NaN
    except (TypeError, ValueError):
        return None


def _am2dec_seguro(ml):
    v = _am2dec(ml)
    return v if v and v > 1.0 else None


def odds_evento(clave: str, event_id: str) -> Dict:
    """Cuotas del EVENTO: 1X2, over/under y HÁNDICAP con su cuota. {} si no hay."""
    code = ESPN_CODIGOS.get(clave)
    if not code or not event_id:
        return {}
    ck = f'oddsev:{clave}:{event_id}'
    ahora = time.time()
    if ck in _CACHE and ahora - _CACHE[ck][0] < TTL_ODDS:
        return _CACHE[ck][1]
    try:
        r = requests.get(ESPN_CORE_ODDS.format(liga=code, eid=event_id),
                         timeout=TIMEOUT, headers={'User-Agent': 'Mozilla/5.0'})
        r.raise_for_status()
        items = r.json().get('items') or []
    except Exception as e:
        logger.warning(f"[odds/{clave}/{event_id}] {type(e).__name__}: {e}")
        _CACHE[ck] = (ahora, {})
        return {}
    if not items:
        _CACHE[ck] = (ahora, {})
        return {}
    it = items[0]
    ho, ao = it.get('homeTeamOdds') or {}, it.get('awayTeamOdds') or {}
    salida = {
        'casa': (it.get('provider') or {}).get('name') or 'ESPN',
        'odd_home': _am2dec_seguro(ho.get('moneyLine')),
        'odd_away': _am2dec_seguro(ao.get('moneyLine')),
        'odd_draw': _am2dec_seguro((it.get('drawOdds') or {}).get('moneyLine')),
        'ou_linea': _num(it.get('overUnder')),
        'odd_over': _am2dec_seguro(it.get('overOdds')),
        'odd_under': _am2dec_seguro(it.get('underOdds')),
        # HÁNDICAP: la línea es del LOCAL (negativa = favorito)
        'ah_linea': _num(it.get('spread')),
        'odd_ah_home': _am2dec_seguro(ho.get('spreadOdds')),
        'odd_ah_away': _am2dec_seguro(ao.get('spreadOdds')),
        'event_id': event_id,
    }
    _CACHE[ck] = (ahora, salida)
    return salida


def props_evento(clave: str, event_id: str, max_paginas: int = 4,
                 nombres: Optional[Dict[str, str]] = None) -> List[Dict]:
    """Props del evento con CUOTA DECIMAL real. `nombres` mapea id de atleta →
    nombre (se obtiene del roster cacheado de goleadores.py) para no gastar una
    petición por jugador. Devuelve [{'tipo','atleta','cuota'}]."""
    code = ESPN_CODIGOS.get(clave)
    if not code or not event_id:
        return []
    ck = f'props:{clave}:{event_id}'
    ahora = time.time()
    if ck in _CACHE and ahora - _CACHE[ck][0] < TTL_ODDS:
        return _CACHE[ck][1]
    base = (ESPN_CORE_ODDS.format(liga=code, eid=event_id)
            + '/100/propBets?limit=25')
    salida: List[Dict] = []
    try:
        for pagina in range(1, max_paginas + 1):
            r = requests.get(f'{base}&page={pagina}', timeout=TIMEOUT,
                             headers={'User-Agent': 'Mozilla/5.0'})
            r.raise_for_status()
            j = r.json()
            for it in (j.get('items') or []):
                cuota = ((it.get('current') or {}).get('over') or {}).get('decimal')
                cuota = _num(cuota)
                if not cuota or cuota <= 1.0:
                    continue
                ref = (it.get('athlete') or {}).get('$ref') or ''
                aid = ref.rstrip('/').split('/')[-1].split('?')[0] if ref else ''
                salida.append({
                    'tipo': (it.get('type') or {}).get('name') or 'Prop',
                    'atleta_id': aid,
                    'atleta': (nombres or {}).get(aid, ''),
                    'cuota': round(cuota, 2),
                })
            if pagina >= (j.get('pageCount') or 1):
                break
    except Exception as e:
        logger.warning(f"[props/{clave}/{event_id}] {type(e).__name__}: {e}")
    logger.info(f"[props/{clave}] {len(salida)} props con cuota real.")
    _CACHE[ck] = (ahora, salida)
    return salida


def odds_multi(clave: str, event_ids: List[str]) -> Dict[str, Dict]:
    """v65: cuotas por evento de MUCHOS partidos EN PARALELO. El barrido diario
    necesita ~1 petición por partido; secuencial serían minutos, concurrente
    son segundos. Cada evento conserva su caché individual (15 min)."""
    from concurrent.futures import ThreadPoolExecutor
    ids = [e for e in event_ids if e]
    if not ids:
        return {}
    salida: Dict[str, Dict] = {}
    with ThreadPoolExecutor(max_workers=min(10, len(ids))) as ex:
        futuros = {ex.submit(odds_evento, clave, eid): eid for eid in ids}
        for fut in futuros:
            eid = futuros[fut]
            try:
                salida[eid] = fut.result() or {}
            except Exception as e:
                logger.warning(f"[odds_multi/{clave}/{eid}] {type(e).__name__}: {e}")
                salida[eid] = {}
    return salida
