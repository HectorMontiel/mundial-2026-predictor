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
    # v92 — LA VÍA POR LA QUE SALIÓ EL PICK.
    #
    # Sin esto no se puede comparar producción con backtest, que es lo único
    # que dirá si el edge validado se está cobrando de verdad: el proyecto
    # tiene DOS vías con números muy distintos —`valor_vs_sharp` (line
    # shopping, p5 +1,07 % fuera de muestra) y el modelo— y en esta tabla se
    # mezclaban. Un ROI agregado no distingue si falla el canal validado o si
    # simplemente hubo pocos picks de él.
    #
    # Se añade con ALTER porque la base ya existe en producción; las filas
    # antiguas quedan con `canal` NULL y se reportan como «sin clasificar»
    # en vez de atribuirse a una vía que no se sabe cuál fue.
    cols = {r[1] for r in con.execute('PRAGMA table_info(picks)')}
    if 'canal' not in cols:
        con.execute('ALTER TABLE picks ADD COLUMN canal TEXT')
        con.commit()
        logger.info('[rendimiento] columna `canal` añadida (v92)')
    return con


def _canal(p: Dict) -> str:
    """Vía por la que salió el pick, para poder auditarla por separado."""
    if p.get('valor_mercado') or p.get('origen') == 'line shopping vs Pinnacle':
        return 'line_shopping'
    if p.get('sin_modelo'):
        return 'sin_modelo'
    return 'modelo'


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
                        prob, cuota, ev, capa, canal)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    (p.get('fecha') or pd.Timestamp.utcnow().strftime('%Y-%m-%d'),
                     p.get('deporte', 'Fútbol'), p.get('liga', ''),
                     p.get('partido', '?'), p.get('mercado', ''),
                     p.get('apuesta', '?'), p.get('prob'), p.get('cuota'),
                     p.get('ev'), capa, _canal(p)))
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
    # v92 — EL ROI SOLO SE CALCULA SOBRE PICKS CON CUOTA REAL.
    #
    # Estaba `df['cuota'].fillna(0)`, y los picks de Capa 2 no tienen cuota
    # POR DEFINICIÓN (son «alta confianza sin precio en vivo»). Con el relleno
    # a 0, un pick de Capa 2 ACERTADO puntuaba 1·(0−1) = −1: un acierto
    # contabilizado como pérdida total. En cuanto se liquidaron los primeros
    # picks (v92) el panel mostró un ROI de −62,93 % con un acierto del
    # 47,4 % — imposible de conciliar, y la señal de que el cálculo estaba
    # roto, no el sistema.
    #
    # Una apuesta sin precio no tiene retorno que medir. Se separan: el ROI
    # sale de las que sí tienen cuota, y el acierto de la Capa 2 se reporta
    # aparte, que es lo único que de ella se puede medir.
    con_cuota = df[df['cuota'].notna() & (df['cuota'] > 1)]
    ganancia = float((con_cuota['resultado'] * (con_cuota['cuota'] - 1)
                      - (1 - con_cuota['resultado'])).sum()) if len(con_cuota) else 0.0
    sin_cuota = df[~df.index.isin(con_cuota.index)]
    return {'n': len(df), 'aciertos': aciertos,
            'tasa_acierto': round(aciertos / len(df), 4),
            'n_con_cuota': int(len(con_cuota)),
            'roi_pct': (round(100 * ganancia / len(con_cuota), 2)
                        if len(con_cuota) else None),
            'n_sin_cuota': int(len(sin_cuota)),
            'acierto_sin_cuota': (round(float(sin_cuota['resultado'].mean()), 4)
                                  if len(sin_cuota) else None),
            'pendientes': int(pend), 'ventana_dias': dias,
            'prob_media_prometida': round(float(df['prob'].mean()), 4)}


# ---------------------------------------------------------------------------
# v92 — PERSISTENCIA EN EL REPOSITORIO
#
# `rendimiento_real.db` está en `.gitignore`, y eso abría el mismo agujero que
# `odds_store` ya había tapado para las fotos de cuotas: el runner de Actions
# clona limpio y Streamlit Cloud tiene disco efímero, así que la base arrancaba
# VACÍA en cada ejecución. Los picks se registraban, se perdían, y al día
# siguiente se empezaba de cero — por eso el historial nunca crecía.
#
# Un pick publicado y su resultado son irrepetibles: si no se guardan, esa
# información no existe en ninguna otra parte. Se vuelcan a un CSV de texto
# plano, diffeable y pequeño, que sí se commitea.
# ---------------------------------------------------------------------------
CSV_PICKS = 'picks_historico.csv'
_CAMPOS = ('fecha', 'deporte', 'liga', 'partido', 'mercado', 'apuesta',
           'prob', 'cuota', 'ev', 'capa', 'canal', 'resultado', 'liquidado_utc')


def exportar(ruta: str = CSV_PICKS) -> int:
    """Vuelca los picks al CSV que se commitea. Devuelve cuántos escribió."""
    import csv
    if not os.path.exists(DB):
        return 0
    con = _con()
    filas = con.execute(
        f"SELECT {','.join(_CAMPOS)} FROM picks "
        f"ORDER BY fecha, partido, apuesta").fetchall()
    con.close()
    from io_atomico import escribir_texto
    buf = [','.join(_CAMPOS)]
    for f in filas:
        buf.append(','.join(
            '' if v is None else str(v).replace(',', ';').replace('\n', ' ')
            for v in f))
    escribir_texto(ruta, '\n'.join(buf) + '\n')
    logger.info(f'[rendimiento] {len(filas)} picks exportados a {ruta}')
    return len(filas)


def importar(ruta: str = CSV_PICKS) -> int:
    """
    Recarga los picks del CSV. Idempotente y NO PISA lo que ya está resuelto:
    un pick liquidado conserva su resultado aunque el CSV traiga la versión
    pendiente (y al revés, el CSV puede aportar el resultado que falte).
    """
    import csv
    if not os.path.exists(ruta):
        return 0
    with open(ruta, encoding='utf-8', newline='') as f:
        filas = list(csv.DictReader(f))
    con = _con()
    n = 0
    with con:
        for r in filas:
            try:
                con.execute(
                    f"INSERT OR IGNORE INTO picks ({','.join(_CAMPOS)}) "
                    f"VALUES ({','.join('?' * len(_CAMPOS))})",
                    tuple((r.get(c) or None) for c in _CAMPOS))
                if r.get('resultado') not in (None, ''):
                    con.execute(
                        "UPDATE picks SET resultado=?, liquidado_utc=? "
                        "WHERE fecha=? AND partido=? AND apuesta=? "
                        "AND resultado IS NULL",
                        (int(r['resultado']), r.get('liquidado_utc'),
                         r['fecha'], r['partido'], r['apuesta']))
                n += 1
            except Exception as e:
                logger.debug(f'[rendimiento] fila no importada: {e}')
    con.close()
    logger.info(f'[rendimiento] {n} picks recargados desde {ruta}')
    return n


def serie_diaria(dias: int = 30) -> pd.DataFrame:
    """Evolución diaria (aciertos y ROI acumulado) para el gráfico."""
    if not os.path.exists(DB):
        return pd.DataFrame()
    con = _con()
    desde = (pd.Timestamp.utcnow() - pd.Timedelta(days=dias)).strftime('%Y-%m-%d')
    # v92: sólo picks CON cuota real — ver el porqué en `resumen`. Una apuesta
    # sin precio no tiene retorno, y rellenarlo con 0 convertía sus aciertos
    # en pérdidas totales.
    df = pd.read_sql_query(
        "SELECT fecha, resultado, cuota FROM picks "
        "WHERE fecha >= ? AND resultado IS NOT NULL "
        "AND cuota IS NOT NULL AND cuota > 1 ORDER BY fecha",
        con, params=[desde])
    con.close()
    if df.empty:
        return df
    df['ganancia'] = df['resultado'] * (df['cuota'] - 1) - (1 - df['resultado'])
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
