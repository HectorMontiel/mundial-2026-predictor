#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v78 — Cuotas de cierre históricas de MLB.

Por qué hace falta
------------------
`historico_mlb.csv` tiene 11.928 juegos (2021-2025) y **ninguna cuota**: el
motor sacaba los precios en vivo de The Odds API y nunca los guardaba. Sin
cuotas no se puede medir el sesgo del modelo ni encogerlo hacia el mercado, que
es exactamente lo que le falta a la MLB (sus picks salían con EV de +11 % justo
donde el fútbol ya está corregido).

Fuentes probadas
----------------
  · **sportsbookreviewsonline.com** — ADOPTADA. Publica un `.xlsx` por
    temporada con el moneyline de apertura y cierre. Cubre 2010-2021: solapa
    con nuestro histórico en la temporada 2021 (~2.430 juegos), que es muestra
    de sobra para calibrar. Las temporadas 2022+ tienen página pero **sin
    fichero descargable** (verificado: 200 OK, cero enlaces a .xls/.xlsx y
    cero tablas en el HTML).
  · **BetExplorer** — sirve solo la fase final de cada temporada (36 juegos en
    2025), porque el resto está tras `?stage=`, que su robots.txt prohíbe.
    Se usa como complemento, no como fuente principal.

Formato de sportsbookreviewsonline
----------------------------------
Dos filas por juego: primero el visitante (`VH='V'`) y después el local
(`VH='H'`). `Date` es MMDD sin año, así que el año lo pone el fichero y hay que
detectar el salto de diciembre a enero (no ocurre en MLB, que va de marzo a
octubre, pero se comprueba igual). `Open`/`Close` son moneyline **americano**.

Uso:
    python backfill_mlb_odds.py
"""

import argparse
import datetime as dt
import io
import json
import logging
import os
import re
import sys
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
import requests

import odds_store

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

logger = logging.getLogger(__name__)

BASE = 'https://www.sportsbookreviewsonline.com'
INDICE = f'{BASE}/scoresoddsarchives/mlb/mlboddsarchives.htm'
UA = {'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                     'AppleWebKit/537.36 (KHTML, like Gecko) '
                     'Chrome/126.0.0.0 Safari/537.36')}
SALIDA = '_v78_backfill_mlb.json'
CACHE = 'mlb_odds_cache'

# Abreviatura de sportsbookreviewsonline -> código Retrosheet.
#
# Es imprescindible: la fuente escribe «CUB», «LAD», «SFO»… y `codigo_mlb`
# compara contra nombres completos («Chicago Cubs»), así que una abreviatura de
# tres letras no supera su umbral difuso y se devuelve tal cual. Resultado
# medido antes de conectar esta tabla: **1.537 de 2.462 juegos sin enlazar**,
# con LAD (174), SFO (167), TAM (166), CWS (165)… encabezando la lista. El
# diccionario existía y no se usaba — el mismo descuido que `YA_CUBIERTAS` en
# la v76, y por eso `_codigo()` es ahora la ÚNICA vía de traducción.
ABREV = {
    'LOS': 'LAN', 'LAD': 'LAN', 'ANA': 'ANA', 'LAA': 'ANA',
    'CUB': 'CHN', 'CHC': 'CHN', 'CWS': 'CHA', 'CHW': 'CHA',
    'KAN': 'KCA', 'KC': 'KCA', 'TAM': 'TBA', 'TB': 'TBA',
    'SDG': 'SDN', 'SD': 'SDN', 'SFO': 'SFN', 'SF': 'SFN',
    'STL': 'SLN', 'NYY': 'NYA', 'NYM': 'NYN', 'WAS': 'WAS',
    'ARI': 'ARI', 'OAK': 'OAK', 'ATH': 'ATH', 'ATL': 'ATL',
    'BAL': 'BAL', 'BOS': 'BOS', 'CIN': 'CIN', 'CLE': 'CLE',
    'COL': 'COL', 'DET': 'DET', 'HOU': 'HOU', 'MIA': 'MIA',
    'MIL': 'MIL', 'MIN': 'MIN', 'PHI': 'PHI', 'PIT': 'PIT',
    'SEA': 'SEA', 'TEX': 'TEX', 'TOR': 'TOR',
}


def _codigo(abrev: str) -> str:
    """Abreviatura de la fuente -> código Retrosheet. Tabla primero, difuso
    después (para nombres largos que sí puede resolver `codigo_mlb`)."""
    from engines.mlb_engine import codigo_mlb
    a = str(abrev or '').strip().upper()
    if a in ABREV:
        return ABREV[a]
    return codigo_mlb(str(abrev or '').strip())


def _ahora() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')


def _american_a_decimal(v) -> Optional[float]:
    try:
        p = float(v)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(p) or p == 0:
        return None
    d = 1 + p / 100.0 if p > 0 else 1 + 100.0 / abs(p)
    return round(d, 4) if 1.01 < d < 100 else None


def ficheros_disponibles() -> Dict[int, str]:
    r = requests.get(INDICE, headers=UA, timeout=40)
    r.raise_for_status()
    out = {}
    for href in re.findall(r'href="([^"]+mlb[^"]*\.(?:xlsx|xls))"', r.text, re.I):
        m = re.search(r'(20\d\d)', href)
        if m:
            out[int(m.group(1))] = BASE + href if href.startswith('/') else href
    return dict(sorted(out.items()))


def _descargar(anio: int, url: str) -> Optional[pd.DataFrame]:
    os.makedirs(CACHE, exist_ok=True)
    ruta = os.path.join(CACHE, f'mlb_{anio}.parquet')
    if os.path.exists(ruta):
        try:
            return pd.read_parquet(ruta)
        except Exception:
            pass
    try:
        r = requests.get(url, headers=UA, timeout=90)
        r.raise_for_status()
        d = pd.read_excel(io.BytesIO(r.content))
    except Exception as e:
        logger.warning(f"[mlb {anio}] {type(e).__name__}: {e}")
        return None
    try:
        d.to_parquet(ruta, index=False)
    except Exception:
        pass
    return d


def parsear(d: pd.DataFrame, anio: int) -> List[dict]:
    """
    Convierte el .xlsx en (fecha, visitante, local, cuota_v, cuota_l).

    Las filas van de dos en dos: la primera es el visitante y la segunda el
    local. Se comprueba explícitamente en vez de asumirlo, porque un fichero
    con una fila suelta desplazaría TODOS los partidos siguientes y el backfill
    asignaría cuotas a juegos equivocados sin dar ningún error.
    """
    cols = {c.strip().lower(): c for c in d.columns}
    # v83 — se lee tambien `Open`. La fuente publica la linea de APERTURA y la
    # de CIERRE, y hasta ahora solo se ingeria el cierre. Con las dos se puede
    # medir la estrategia que si funciono en WTA: precio tomable (apertura)
    # contra referencia eficiente (cierre). Es accionable porque la app toma
    # precios con dias de antelacion, no al cierre.
    req = ('date', 'vh', 'team', 'final', 'close')
    if not all(k in cols for k in req):
        logger.warning(f"[mlb {anio}] faltan columnas: {sorted(set(req) - set(cols))}")
        return []
    d = d.rename(columns={cols['date']: 'Date', cols['vh']: 'VH',
                          cols['team']: 'Team', cols['final']: 'Final',
                          cols['close']: 'Close'})
    if 'open' in cols:
        d = d.rename(columns={cols['open']: 'Open'})
    d = d[d['VH'].astype(str).str.upper().isin(['V', 'H'])].reset_index(drop=True)

    salida, saltadas = [], 0
    i = 0
    while i + 1 < len(d):
        v, h = d.iloc[i], d.iloc[i + 1]
        if str(v['VH']).upper() != 'V' or str(h['VH']).upper() != 'H':
            saltadas += 1
            i += 1                      # desalineada: se avanza de una en una
            continue
        try:
            mmdd = int(float(v['Date']))
        except (TypeError, ValueError):
            i += 2
            continue
        mes, dia = mmdd // 100, mmdd % 100
        if not (1 <= mes <= 12 and 1 <= dia <= 31):
            i += 2
            continue
        try:
            fecha = dt.date(anio, mes, dia)
        except ValueError:
            i += 2
            continue
        cv = _american_a_decimal(v.get('Close'))
        cl = _american_a_decimal(h.get('Close'))
        av = _american_a_decimal(v.get('Open')) if 'Open' in d.columns else None
        al = _american_a_decimal(h.get('Open')) if 'Open' in d.columns else None
        if cv and cl:
            salida.append({
                'apertura_visitante': av, 'apertura_local': al,
                'fecha': fecha.isoformat(),
                'visitante': _codigo(v['Team']),
                'local': _codigo(h['Team']),
                'abrev_v': str(v['Team']).strip(), 'abrev_l': str(h['Team']).strip(),
                'cuota_visitante': cv, 'cuota_local': cl,
                'runs_v': v.get('Final'), 'runs_l': h.get('Final'),
            })
        i += 2
    if saltadas:
        logger.warning(f"[mlb {anio}] {saltadas} filas desalineadas (V/H) "
                       f"— se avanzó de una en una para no desplazar el resto")
    return salida


def enlazar(partidos: List[dict]) -> List[dict]:
    """
    Cruza con `historico_mlb.csv` exigiendo que coincidan fecha, equipos **y
    marcador**. El marcador es la verificación: sin él, un desfase de una fila
    en el Excel asignaría la cuota de otro partido y contaminaría el backtest
    sin dejar rastro (misma lección que el backfill de fútbol en la v76).
    """
    from engines.mlb_engine import codigo_mlb
    ruta = 'historico_mlb.csv'
    if not os.path.exists(ruta):
        return []
    h = pd.read_csv(ruta, low_memory=False)
    h['date'] = pd.to_datetime(h['date'], errors='coerce')
    h = h.dropna(subset=['date'])
    real = {}
    for r in h.itertuples(index=False):
        clave = (r.date.date().isoformat(),
                 codigo_mlb(str(r.home_team)), codigo_mlb(str(r.away_team)))
        real.setdefault(clave, []).append((int(r.home_runs), int(r.away_runs)))

    out, sin_partido, marcador = [], 0, 0
    for p in partidos:
        clave = (p['fecha'], p['local'], p['visitante'])
        cands = real.get(clave)
        if not cands:
            sin_partido += 1
            continue
        try:
            rl, rv = int(float(p['runs_l'])), int(float(p['runs_v']))
        except (TypeError, ValueError):
            rl = rv = None
        if rl is not None and (rl, rv) not in cands:
            marcador += 1
            continue
        out.append({**p, 'match_id': f"{p['fecha'].replace('-', '')}_"
                                     f"{p['local']}_{p['visitante']}"})
    logger.info(f"[mlb] enlazados {len(out)}/{len(partidos)} "
                f"(sin partido {sin_partido}, marcador distinto {marcador})")
    return out


def main(desde: int = 2021) -> dict:
    ficheros = ficheros_disponibles()
    logger.info(f"ficheros en la fuente: {sorted(ficheros)}")
    crudos = []
    for anio, url in ficheros.items():
        if anio < desde:
            continue
        d = _descargar(anio, url)
        if d is None:
            continue
        p = parsear(d, anio)
        logger.info(f"[mlb {anio}] {len(p)} juegos con cuota de cierre")
        crudos += p
    enlazados = enlazar(crudos)

    ahora = _ahora()
    filas = [{
        'match_id': p['match_id'], 'league_key': 'mlb',
        'match_date': p['fecha'], 'home_team': p['local'],
        'away_team': p['visitante'], 'bookmaker': 'mercado',
        'fase': 'cierre', 'snapshot_key': 'cierre', 'dias_al_partido': 0.0,
        'odds_home': p['cuota_local'], 'odds_away': p['cuota_visitante'],
        'source_file': 'sportsbookreviewsonline', 'ingested_at': ahora,
    } for p in enlazados]
    n = 0
    if filas:
        con = odds_store.conectar()
        n = odds_store.guardar(con, filas, reemplazar=True)
        odds_store.exportar_snapshots(con)    # se persiste: no es regenerable
        con.close()
    salida = {'generado': ahora, 'anios': sorted(a for a in ficheros if a >= desde),
              'leidos': len(crudos), 'enlazados': len(enlazados), 'insertados': n,
              'nota': 'sportsbookreviewsonline publica hasta 2021; 2022+ tienen '
                      'página pero sin fichero descargable (verificado).'}
    with open(SALIDA, 'w', encoding='utf-8') as f:
        json.dump(salida, f, ensure_ascii=False, indent=1)
    return salida


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    ap = argparse.ArgumentParser()
    ap.add_argument('--desde', type=int, default=2021)
    a = ap.parse_args()
    r = main(a.desde)
    print(f"\n{r['insertados']} cuotas de MLB insertadas "
          f"({r['enlazados']}/{r['leidos']} enlazadas).")
