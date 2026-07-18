#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Cliente de The Odds API agrupado por LIGA + almacén histórico de cuotas para
CLV — Closing Line Value (v25, spec §1.2).

## Diseño
  * The Odds API devuelve TODOS los próximos partidos de una liga en una
    sola llamada → agrupar por liga (spec): 10 ligas ≈ 10 requests/jornada,
    ~500 créditos/mes de la capa gratuita alcanzan de sobra. Presupuesto
    defensivo: máx. MAX_REQUESTS_DIA por día (estado en odds_api_state.json).
  * Mercados: h2h (1X2), totals (over/under 2.5) y btts donde el plan lo
    exponga (no todas las casas lo publican — se guarda lo que llegue).
  * TODO snapshot (también los de fixtures.csv/Betexplorer, sin clave) se
    escribe en odds_historico.db (SQLite) con marca de tiempo → el
    backtesting de EV usa la cuota MÁS CERCANA al inicio del partido y el
    CLV se mide comparando la cuota tomada contra la de cierre.
  * SIN ODDS_API_KEY el módulo degrada limpio: la captura de The Odds API se
    omite (con log) pero el almacén histórico sigue funcionando con las
    fuentes gratuitas — el CLV empieza a acumularse desde HOY sin clave.

## Estado honesto (2026-07-17)
No hay ODDS_API_KEY en secrets.toml: la vía The Odds API queda implementada
y probada en seco, pendiente de que el usuario cree la clave gratuita en
the-odds-api.com y la añada como env o en .streamlit/secrets.toml.
"""

import datetime
import json
import logging
import os
import sqlite3
from typing import Dict, List, Optional

import pandas as pd
import requests

logger = logging.getLogger(__name__)

DB = 'odds_historico.db'
ESTADO = 'odds_api_state.json'
BASE = 'https://api.the-odds-api.com/v4'
MAX_REQUESTS_DIA = 20            # spec §1.2: margen de sobra con 500/mes
CUOTA_FRESCA_HORAS = 6           # spec: aviso si la cuota es más vieja

# clave del proyecto -> sport key de The Odds API
SPORT_KEYS = {
    'premier': 'soccer_epl',
    'laliga': 'soccer_spain_la_liga',
    'serie_a': 'soccer_italy_serie_a',
    'bundesliga': 'soccer_germany_bundesliga',
    'ligue_1': 'soccer_france_ligue_one',
    'eredivisie': 'soccer_netherlands_eredivisie',
    'primeira': 'soccer_portugal_primeira_liga',
    'liga_mx': 'soccer_mexico_ligamx',
    'mls': 'soccer_usa_mls',
    'champions': 'soccer_uefa_champs_league',
    'mundial': 'soccer_fifa_world_cup',
}


def _clave() -> str:
    k = os.getenv('ODDS_API_KEY', '')
    if not k:
        try:
            import tomllib
            with open('.streamlit/secrets.toml', 'rb') as f:
                k = tomllib.load(f).get('ODDS_API_KEY', '')
        except Exception:
            pass
    return k


# ---------------------------------------------------------------------------
# Almacén SQLite (funciona con y sin clave)
# ---------------------------------------------------------------------------
def _conexion() -> sqlite3.Connection:
    con = sqlite3.connect(DB)
    con.execute("""CREATE TABLE IF NOT EXISTS snapshots (
        match_id TEXT NOT NULL,
        liga TEXT,
        capturado_utc TEXT NOT NULL,
        inicio_utc TEXT,
        fuente TEXT,
        mercado TEXT NOT NULL,       -- h2h | totals25 | btts | ah
        seleccion TEXT NOT NULL,     -- home/draw/away | over/under | yes/no
        cuota REAL NOT NULL,
        PRIMARY KEY (match_id, capturado_utc, mercado, seleccion))""")
    con.execute("CREATE INDEX IF NOT EXISTS ix_snap_match ON snapshots(match_id)")
    return con


def guardar_snapshots(filas: List[Dict]):
    """filas: dicts con match_id/liga/inicio_utc/fuente/mercado/seleccion/cuota."""
    if not filas:
        return
    ahora = pd.Timestamp.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')
    con = _conexion()
    with con:
        con.executemany(
            """INSERT OR IGNORE INTO snapshots
               (match_id, liga, capturado_utc, inicio_utc, fuente, mercado,
                seleccion, cuota) VALUES (?,?,?,?,?,?,?,?)""",
            [(f['match_id'], f.get('liga'), ahora, f.get('inicio_utc'),
              f.get('fuente', '?'), f['mercado'], f['seleccion'],
              float(f['cuota'])) for f in filas])
    con.close()
    logger.info(f"odds_historico.db: +{len(filas)} cuotas ({ahora}).")


def cuota_mas_cercana(match_id: str, mercado: str = 'h2h',
                      antes_de: Optional[str] = None) -> Optional[Dict]:
    """La captura más reciente (opcionalmente anterior a `antes_de` — para
    backtesting: la cuota más cercana al inicio SIN mirar el futuro).
    Devuelve {'seleccion': cuota, ..., 'capturado_utc', 'aviso_frescura'}."""
    if not os.path.exists(DB):
        return None
    con = _conexion()
    q = ("SELECT capturado_utc, seleccion, cuota FROM snapshots "
         "WHERE match_id=? AND mercado=?")
    args = [match_id, mercado]
    if antes_de:
        q += " AND capturado_utc<=?"
        args.append(antes_de)
    df = pd.read_sql_query(q + " ORDER BY capturado_utc", con, params=args)
    con.close()
    if df.empty:
        return None
    ultimo = df['capturado_utc'].iloc[-1]
    sel = df[df['capturado_utc'] == ultimo]
    out = {r['seleccion']: float(r['cuota']) for _, r in sel.iterrows()}
    out['capturado_utc'] = ultimo
    ref = pd.Timestamp(antes_de) if antes_de else pd.Timestamp.utcnow()
    edad_h = (ref.tz_localize(None) - pd.Timestamp(ultimo).tz_localize(None)) \
        / pd.Timedelta(hours=1)
    out['aviso_frescura'] = bool(edad_h > CUOTA_FRESCA_HORAS)
    return out


def clv_reporte() -> pd.DataFrame:
    """CLV por partido: primera captura vs última (proxy de cierre) del 1X2.
    Cobra sentido conforme el pipeline acumula capturas repetidas."""
    if not os.path.exists(DB):
        return pd.DataFrame()
    con = _conexion()
    df = pd.read_sql_query(
        "SELECT match_id, capturado_utc, seleccion, cuota FROM snapshots "
        "WHERE mercado='h2h' ORDER BY capturado_utc", con)
    con.close()
    if df.empty:
        return pd.DataFrame()
    filas = []
    for (mid, sel), g in df.groupby(['match_id', 'seleccion']):
        if len(g) < 2:
            continue
        primera, ultima = g.iloc[0], g.iloc[-1]
        filas.append({'match_id': mid, 'seleccion': sel,
                      'cuota_inicial': primera['cuota'],
                      'cuota_cierre': ultima['cuota'],
                      'clv_pct': round(100 * (primera['cuota'] / ultima['cuota'] - 1), 2)})
    return pd.DataFrame(filas)


# ---------------------------------------------------------------------------
# The Odds API (con clave) — una request por liga
# ---------------------------------------------------------------------------
def _presupuesto_disponible() -> bool:
    hoy = datetime.date.today().isoformat()
    try:
        with open(ESTADO, encoding='utf-8') as f:
            st = json.load(f)
    except Exception:
        st = {}
    return st.get('fecha') != hoy or st.get('requests', 0) < MAX_REQUESTS_DIA


def _consumir_request():
    hoy = datetime.date.today().isoformat()
    try:
        with open(ESTADO, encoding='utf-8') as f:
            st = json.load(f)
    except Exception:
        st = {}
    if st.get('fecha') != hoy:
        st = {'fecha': hoy, 'requests': 0}
    st['requests'] = st.get('requests', 0) + 1
    with open(ESTADO, 'w', encoding='utf-8') as f:
        json.dump(st, f)


def capturar_liga(clave_liga: str) -> List[Dict]:
    """Una request: todos los próximos partidos de la liga con h2h+totals+btts."""
    k = _clave()
    if not k:
        return []
    if clave_liga not in SPORT_KEYS or not _presupuesto_disponible():
        return []
    _consumir_request()
    filas = []
    try:
        r = requests.get(f"{BASE}/sports/{SPORT_KEYS[clave_liga]}/odds",
                         params={'apiKey': k, 'regions': 'eu',
                                 'markets': 'h2h,totals,btts',
                                 'oddsFormat': 'decimal'}, timeout=30)
        r.raise_for_status()
        for ev in r.json():
            inicio = ev.get('commence_time')
            fecha = pd.to_datetime(inicio).tz_localize(None)
            mid = (f"{fecha.strftime('%Y%m%d')}_"
                   f"{str(ev['home_team']).replace(' ', '-')}_"
                   f"{str(ev['away_team']).replace(' ', '-')}")
            for casa in ev.get('bookmakers', [])[:1]:      # la primera casa
                for m in casa.get('markets', []):
                    if m['key'] == 'h2h':
                        for o in m['outcomes']:
                            sel = ('home' if o['name'] == ev['home_team'] else
                                   'away' if o['name'] == ev['away_team'] else 'draw')
                            filas.append({'match_id': mid, 'liga': clave_liga,
                                          'inicio_utc': inicio, 'fuente': 'odds_api',
                                          'mercado': 'h2h', 'seleccion': sel,
                                          'cuota': o['price']})
                    elif m['key'] == 'totals':
                        for o in m['outcomes']:
                            if abs(float(o.get('point', 0)) - 2.5) < 0.01:
                                filas.append({'match_id': mid, 'liga': clave_liga,
                                              'inicio_utc': inicio, 'fuente': 'odds_api',
                                              'mercado': 'totals25',
                                              'seleccion': o['name'].lower(),
                                              'cuota': o['price']})
                    elif m['key'] == 'btts':
                        for o in m['outcomes']:
                            filas.append({'match_id': mid, 'liga': clave_liga,
                                          'inicio_utc': inicio, 'fuente': 'odds_api',
                                          'mercado': 'btts',
                                          'seleccion': o['name'].lower(),
                                          'cuota': o['price']})
        logger.info(f"The Odds API [{clave_liga}]: {len(filas)} cuotas capturadas.")
    except Exception as e:
        logger.warning(f"The Odds API [{clave_liga}] falló: {e}")
    return filas


def capturar_todas() -> int:
    """Captura agrupada por liga (una request por liga, respetando presupuesto)."""
    if not _clave():
        logger.info("ODDS_API_KEY ausente: captura The Odds API omitida "
                    "(el almacén CLV sigue nutriéndose de fixtures.csv/Betexplorer).")
        return 0
    total = 0
    for clave_liga in SPORT_KEYS:
        filas = capturar_liga(clave_liga)
        guardar_snapshots(filas)
        total += len(filas)
    return total


def cuotas_recientes(mercado: str, horas: int = 24) -> Dict[str, Dict[str, float]]:
    """Últimas cuotas de un mercado por match_id (capturas de ≤ `horas`)."""
    if not os.path.exists(DB):
        return {}
    con = _conexion()
    desde = (pd.Timestamp.utcnow() - pd.Timedelta(hours=horas)) \
        .strftime('%Y-%m-%dT%H:%M:%SZ')
    df = pd.read_sql_query(
        "SELECT match_id, capturado_utc, seleccion, cuota FROM snapshots "
        "WHERE mercado=? AND capturado_utc>=? ORDER BY capturado_utc",
        con, params=[mercado, desde])
    con.close()
    out: Dict[str, Dict[str, float]] = {}
    for (mid), g in df.groupby('match_id'):
        ultimo = g['capturado_utc'].iloc[-1]
        sel = g[g['capturado_utc'] == ultimo]
        out[mid] = {r['seleccion']: float(r['cuota']) for _, r in sel.iterrows()}
    return out


def snapshot_desde_fixtures(df: pd.DataFrame):
    """Vuelca el snapshot gratuito de fixtures.csv/Betexplorer al almacén CLV
    (1X2 + O/U 2.5 + AH cuando existen). df: formato de fetch_odds."""
    filas = []
    for r in df.itertuples(index=False):
        mid = getattr(r, 'MATCH_ID', None)
        if not mid:
            continue
        liga = getattr(r, 'liga', None)
        base = {'match_id': mid, 'liga': liga, 'inicio_utc': None,
                'fuente': 'fixtures_csv'}
        for sel, attr in (('home', 'odd_home'), ('draw', 'odd_draw'),
                          ('away', 'odd_away')):
            v = getattr(r, attr, None)
            if v is not None and pd.notna(v):
                filas.append({**base, 'mercado': 'h2h', 'seleccion': sel, 'cuota': v})
        for sel, attr in (('over', 'odd_over25'), ('under', 'odd_under25')):
            v = getattr(r, attr, None)
            if v is not None and pd.notna(v):
                filas.append({**base, 'mercado': 'totals25', 'seleccion': sel, 'cuota': v})
    guardar_snapshots(filas)


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    n = capturar_todas()
    print(f"cuotas capturadas: {n}")
    rep = clv_reporte()
    print(f"CLV medible en {len(rep)} selecciones" if not rep.empty
          else "CLV: aún sin capturas repetidas (se acumulan con el pipeline).")
