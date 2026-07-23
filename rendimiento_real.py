#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Rendimiento REAL de las Apuestas del Día (v32 §6) — persistencia SQLite WAL.

Registra cada pick publicado y, cuando el resultado se conoce, lo liquida.
El modo WAL (§1.3) hace que los datos sobrevivan a los reinicios del
contenedor de Streamlit Cloud (aunque el disco del cloud es efímero entre
despliegues: eso se documenta, no se promete lo imposible).

Métricas: tasa de acierto y ROI real con la cuota registrada, en ventanas de
7 y 30 días. A diferencia del ROI simulado del backtest, esto mide lo que el
sistema recomendó DE VERDAD, día a día.
"""

import logging
import os
import sqlite3
from typing import Dict, List, Optional

import pandas as pd

logger = logging.getLogger(__name__)

DB = 'rendimiento_real.db'


def _con() -> sqlite3.Connection:
    con = sqlite3.connect(DB)
    con.execute('PRAGMA journal_mode=WAL')       # §1.3
    con.execute("""CREATE TABLE IF NOT EXISTS picks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        fecha TEXT NOT NULL,
        deporte TEXT, liga TEXT, partido TEXT NOT NULL,
        mercado TEXT, apuesta TEXT NOT NULL,
        prob REAL, cuota REAL, ev REAL, capa TEXT,
        resultado INTEGER,                       -- 1 acierto, 0 fallo, NULL pendiente
        liquidado_utc TEXT,
        UNIQUE(fecha, partido, apuesta))""")
    return con


def registrar(picks: List[Dict], capa: str = 'capa1') -> int:
    """Guarda los picks del día (idempotente por fecha+partido+apuesta)."""
    if not picks:
        return 0
    con = _con()
    n = 0
    with con:
        for p in picks:
            try:
                con.execute(
                    """INSERT OR IGNORE INTO picks
                       (fecha, deporte, liga, partido, mercado, apuesta,
                        prob, cuota, ev, capa)
                       VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (p.get('fecha') or pd.Timestamp.today().strftime('%Y-%m-%d'),
                     p.get('deporte', 'Fútbol'), p.get('liga', ''),
                     p.get('partido', '?'), p.get('mercado', ''),
                     p.get('apuesta', '?'), p.get('prob'), p.get('cuota'),
                     p.get('ev'), capa))
                n += 1
            except Exception as e:
                logger.warning(f"[rendimiento] pick no registrado: {e}")
    con.close()
    return n


def liquidar(fecha: str, partido: str, apuesta: str, acerto: bool) -> bool:
    """Marca el resultado real de un pick ya publicado."""
    con = _con()
    with con:
        cur = con.execute(
            """UPDATE picks SET resultado=?, liquidado_utc=?
               WHERE fecha=? AND partido=? AND apuesta=?""",
            (int(acerto), pd.Timestamp.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'),
             fecha, partido, apuesta))
    con.close()
    return cur.rowcount > 0


def resumen(dias: int = 30) -> Dict:
    """Tasa de acierto y ROI real de los picks liquidados en la ventana."""
    if not os.path.exists(DB):
        return {'n': 0, 'aviso': 'Aún no hay historial registrado.'}
    con = _con()
    desde = (pd.Timestamp.today() - pd.Timedelta(days=dias)).strftime('%Y-%m-%d')
    df = pd.read_sql_query(
        "SELECT * FROM picks WHERE fecha >= ? AND resultado IS NOT NULL",
        con, params=[desde])
    pend = pd.read_sql_query(
        "SELECT COUNT(*) n FROM picks WHERE fecha >= ? AND resultado IS NULL",
        con, params=[desde])['n'].iloc[0]
    con.close()
    if df.empty:
        return {'n': 0, 'pendientes': int(pend),
                'aviso': f'Sin picks liquidados en {dias} días '
                         f'({int(pend)} pendientes de resultado).'}
    aciertos = int(df['resultado'].sum())
    cuotas = df['cuota'].fillna(0)
    ganancia = float((df['resultado'] * (cuotas - 1) - (1 - df['resultado'])).sum())
    return {'n': len(df), 'aciertos': aciertos,
            'tasa_acierto': round(aciertos / len(df), 4),
            'roi_pct': round(100 * ganancia / len(df), 2),
            'pendientes': int(pend), 'ventana_dias': dias,
            'prob_media_prometida': round(float(df['prob'].mean()), 4)}


def serie_diaria(dias: int = 30) -> pd.DataFrame:
    """Evolución diaria (aciertos y ROI acumulado) para el gráfico."""
    if not os.path.exists(DB):
        return pd.DataFrame()
    con = _con()
    desde = (pd.Timestamp.today() - pd.Timedelta(days=dias)).strftime('%Y-%m-%d')
    df = pd.read_sql_query(
        "SELECT fecha, resultado, cuota FROM picks "
        "WHERE fecha >= ? AND resultado IS NOT NULL ORDER BY fecha",
        con, params=[desde])
    con.close()
    if df.empty:
        return df
    df['ganancia'] = df['resultado'] * (df['cuota'].fillna(0) - 1) - (1 - df['resultado'])
    g = df.groupby('fecha').agg(picks=('resultado', 'size'),
                                aciertos=('resultado', 'sum'),
                                ganancia=('ganancia', 'sum')).reset_index()
    g['roi_acumulado_pct'] = (g['ganancia'].cumsum()
                              / g['picks'].cumsum() * 100).round(2)
    return g


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    import json
    print(json.dumps(resumen(), indent=2, ensure_ascii=False))
