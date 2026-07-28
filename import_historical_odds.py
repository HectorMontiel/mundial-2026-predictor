#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v75 — Importación masiva de cuotas de cierre a `odds_historico.db`.

El hallazgo que cambia el plan
------------------------------
El plan de la v75 partía de que había que releer los CSV crudos de
football-data desde `data/raw/`. **`data/raw/` no existe en este proyecto**: el
pipeline (`league_engine.descargar_liga`) ya normaliza las cuotas de cierre al
descargar y las persiste en `historico_{clave}.csv` como `odd_home/draw/away`
(media de mercado con respaldo B365), `odd_*_pin` (cierre de Pinnacle),
`odd_over25/under25` y el hándicap asiático.

Es decir: el histórico de cuotas ya lo teníamos, disperso en 70 CSV. Reimportar
de la web habría sido descargar 200 ficheros para reconstruir algo que ya
estaba en disco, y además habría reintroducido el riesgo de desalinear el
`MATCH_ID` (el del CSV es EXACTAMENTE el que usan los modelos y `alpha_finder`;
uno reconstruido a mano no lo sería).

Así que la importación lee los CSV del propio proyecto. Medido: 40 ligas con
cuota de cierre real.

Casas
-----
  · `mercado`  — media de mercado de cierre (AvgC*), respaldo B365 de cierre.
                 Es la cuota que un usuario puede conseguir de verdad.
  · `pinnacle` — cierre de Pinnacle (PSC*). Es el ancla sharp: la referencia
                 para devig, sesgo de calibración y CLV.

Uso:
    python import_historical_odds.py            # importa todo
    python import_historical_odds.py --liga premier
"""

import argparse
import datetime as dt
import glob
import json
import logging
import sys
import os
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

import odds_store

# La consola de Windows es cp1252: sin esto, imprimir una flecha o un
# visto aborta el script DESPUÉS de haber hecho todo el trabajo.
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

logger = logging.getLogger(__name__)

SALIDA = '_v75_import_odds.json'

# Mapa columna del CSV -> columna de la tabla, por casa.
MAPA_MERCADO = {
    'odd_home': 'odds_home', 'odd_draw': 'odds_draw', 'odd_away': 'odds_away',
    'odd_over25': 'odds_over25', 'odd_under25': 'odds_under25',
    'odd_ah_home': 'odds_ah_home', 'odd_ah_away': 'odds_ah_away',
}
MAPA_PINNACLE = {
    'odd_home_pin': 'odds_home', 'odd_draw_pin': 'odds_draw',
    'odd_away_pin': 'odds_away',
}


def ligas_del_proyecto() -> Dict[str, dict]:
    from config import LEAGUES
    return LEAGUES


def get_csv_files(solo: Optional[str] = None) -> Dict[str, str]:
    """
    `{clave_liga: ruta_csv}` de las ligas ACTIVAS del catálogo que tienen CSV.

    Se filtra por `config.LEAGUES` a propósito: en el repo hay CSV huérfanos de
    experimentos (p. ej. `historico_suiza_v48.csv`, gemelo de `suiza`) que, si
    entrasen, contarían dos veces los mismos partidos en cualquier métrica
    agregada.
    """
    ligas = ligas_del_proyecto()
    salida = {}
    for clave in ligas:
        if solo and clave != solo:
            continue
        ruta = f'historico_{clave}.csv'
        if os.path.exists(ruta):
            salida[clave] = ruta
    huerfanos = [p for p in glob.glob('historico_*.csv')
                 if p[len('historico_'):-4] not in ligas]
    if huerfanos and not solo:
        logger.info(f"{len(huerfanos)} CSV fuera del catálogo, ignorados "
                    f"(p. ej. {', '.join(os.path.basename(h) for h in huerfanos[:3])}).")
    return salida


def parse_csv(filepath: str, league_key: str) -> List[dict]:
    """
    Extrae de un `historico_*.csv` las filas de cuota de cierre listas para
    la tabla. Devuelve [] si la liga no tiene ninguna columna de cuota (las
    servidas por ESPN: el proveedor retira el bloque `odds` tras el pitido
    final, así que ahí no hay nada que importar — ver `daily_snapshots.py`).
    """
    df = pd.read_csv(filepath, low_memory=False)
    if 'MATCH_ID' not in df.columns or 'date' not in df.columns:
        logger.warning(f"[{league_key}] sin MATCH_ID/date: se omite.")
        return []
    disponibles = set(df.columns)
    if not ({'odd_home'} & disponibles) and not ({'odd_home_pin'} & disponibles):
        return []

    df = df.copy()
    df['date'] = pd.to_datetime(df['date'], errors='coerce')
    df = df.dropna(subset=['date', 'MATCH_ID'])
    ahora = dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')
    origen = os.path.basename(filepath)
    filas: List[dict] = []

    for casa, mapa in (('mercado', MAPA_MERCADO), ('pinnacle', MAPA_PINNACLE)):
        cols = {o: d for o, d in mapa.items() if o in disponibles}
        if not cols:
            continue
        sub = df[['MATCH_ID', 'date', 'home_team', 'away_team'] + list(cols)].copy()
        # descartar filas sin ninguna cuota de esta casa (evita millares de
        # filas vacías en las ligas donde Pinnacle solo cubre el 85 %)
        sub = sub.dropna(subset=list(cols), how='all')
        linea_ah = (pd.to_numeric(df.get('ah_linea'), errors='coerce')
                    if 'ah_linea' in disponibles and casa == 'mercado' else None)
        if linea_ah is not None:
            sub['ah_linea'] = linea_ah.reindex(sub.index)
        for r in sub.itertuples(index=False):
            d = dict(zip(sub.columns, r))
            fila = {
                'match_id': str(d['MATCH_ID']),
                'league_key': league_key,
                'match_date': pd.Timestamp(d['date']).strftime('%Y-%m-%d'),
                'home_team': str(d.get('home_team') or ''),
                'away_team': str(d.get('away_team') or ''),
                'bookmaker': casa,
                'fase': 'cierre', 'snapshot_key': 'cierre',
                'dias_al_partido': 0.0,
                'ah_linea': d.get('ah_linea'),
                'source_file': origen, 'ingested_at': ahora,
            }
            for o, destino in cols.items():
                fila[destino] = d.get(o)
            filas.append(fila)
    return filas


def importar(solo: Optional[str] = None, ruta_db: str = odds_store.DB) -> dict:
    con = odds_store.conectar(ruta_db)
    ficheros = get_csv_files(solo)
    total, por_liga, sin_cuota = 0, {}, []
    for clave, ruta in sorted(ficheros.items()):
        try:
            filas = parse_csv(ruta, clave)
        except Exception as e:
            logger.error(f"[{clave}] error al leer {ruta}: {e}")
            continue
        if not filas:
            sin_cuota.append(clave)
            continue
        n = odds_store.guardar(con, filas, reemplazar=True)
        total += n
        partidos = len({f['match_id'] for f in filas})
        por_liga[clave] = {'filas': n, 'partidos': partidos}
        logger.info(f"[{clave}] {n} filas de cuota ({partidos} partidos).")

    resumen = {
        'generado': dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z'),
        'filas_insertadas': total,
        'ligas_con_cuota': len(por_liga),
        'ligas_sin_cuota': sorted(sin_cuota),
        'por_liga': por_liga,
        'nota': 'Fuente: historico_*.csv del propio proyecto (data/raw no '
                'existe; league_engine ya normaliza las cuotas al descargar). '
                'Las ligas sin cuota son las servidas por ESPN, que retira el '
                'bloque odds tras el partido -> solo pueden acumular histórico '
                'vía daily_snapshots.py.',
    }
    with open(SALIDA, 'w', encoding='utf-8') as f:
        json.dump(resumen, f, ensure_ascii=False, indent=1)
    con.close()
    return resumen


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    ap = argparse.ArgumentParser()
    ap.add_argument('--liga')
    args = ap.parse_args()
    r = importar(args.liga)
    print(f"\n{r['filas_insertadas']} filas en {r['ligas_con_cuota']} ligas.")
    print(f"{len(r['ligas_sin_cuota'])} ligas sin cuota histórica: "
          f"{', '.join(r['ligas_sin_cuota'][:12])}"
          + ('…' if len(r['ligas_sin_cuota']) > 12 else ''))
