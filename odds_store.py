#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v75 — Almacén canónico de cuotas históricas (`odds_historico.db`).

Por qué existe
--------------
Hasta la v74 el proyecto tenía las cuotas de cierre REPARTIDAS en 70 CSV de
liga (`historico_{clave}.csv`, columnas `odd_*`) y una tabla `snapshots` que
solo se llenaba con lo que capturaba el barrido en vivo. Eso hacía imposible
responder preguntas básicas sin releer 70 ficheros:

  · ¿qué ligas tienen cuota de cierre y cuántos partidos?
  · ¿cómo se movió la línea entre hoy y el día del partido? (CLV)
  · ¿qué umbral de Capa 1 habría sido rentable en esta liga?

Este módulo centraliza TODO en una tabla `historical_odds` con dos fases:

  · `fase='cierre'`   — cuota de cierre de un partido YA jugado. Idempotente:
                        reimportar no duplica (clave única por partido/casa).
  · `fase='snapshot'` — foto de la cuota de un partido FUTURO, tomada el día
                        `snapshot_key`. Una fila por día y casa: es la materia
                        prima del CLV y la única forma de tener histórico en
                        las ligas que football-data no publica.

La tabla `snapshots` de la v43 se conserva intacta (la lee `clv_tracker`).

Verificación de fuente (v75 — lección aprendida)
-----------------------------------------------
`fuente_football_data_valida()` existe porque football-data.co.uk devuelve
**HTTP 200 con el fichero de OTRA liga** cuando el código de país no existe:
medido el 2026-07-28, `/new/COL.csv` y `/new/BOL.csv` son byte a byte
`/new/POL.csv` (Ekstraklasa), y `/new/KOR.csv` es `/new/NOR.csv`. Comprobar el
código de estado NO basta y habría metido partidos polacos en la liga
colombiana. Cualquier alta de liga por esta vía tiene que pasar por aquí.
"""

import io
import json
import logging
import os
import re
import sqlite3
from typing import Dict, Iterable, List, Optional

logger = logging.getLogger(__name__)

DB = 'odds_historico.db'

# Mercados normalizados que sabe guardar la tabla
COLUMNAS_CUOTA = ('odds_home', 'odds_draw', 'odds_away',
                  'odds_over25', 'odds_under25',
                  'odds_btts_yes', 'odds_btts_no',
                  'odds_ah_home', 'odds_ah_away')

_ESQUEMA = """
CREATE TABLE IF NOT EXISTS historical_odds (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id      TEXT    NOT NULL,
    league_key    TEXT    NOT NULL,
    match_date    TEXT    NOT NULL,
    home_team     TEXT    NOT NULL,
    away_team     TEXT    NOT NULL,
    bookmaker     TEXT    NOT NULL,
    fase          TEXT    NOT NULL DEFAULT 'cierre',
    snapshot_key  TEXT    NOT NULL DEFAULT 'cierre',
    dias_al_partido REAL,
    odds_home     REAL,
    odds_draw     REAL,
    odds_away     REAL,
    odds_over25   REAL,
    odds_under25  REAL,
    odds_btts_yes REAL,
    odds_btts_no  REAL,
    ah_linea      REAL,
    odds_ah_home  REAL,
    odds_ah_away  REAL,
    source_file   TEXT,
    ingested_at   TEXT    NOT NULL,
    UNIQUE (match_id, bookmaker, snapshot_key)
);
CREATE INDEX IF NOT EXISTS ix_ho_liga_fecha ON historical_odds (league_key, match_date);
CREATE INDEX IF NOT EXISTS ix_ho_match      ON historical_odds (match_id);
CREATE INDEX IF NOT EXISTS ix_ho_fase       ON historical_odds (fase, league_key);
"""


def conectar(ruta: str = DB) -> sqlite3.Connection:
    """Conexión con el esquema garantizado (crea la tabla si no existe)."""
    con = sqlite3.connect(ruta)
    con.executescript(_ESQUEMA)
    con.commit()
    return con


def _limpiar(fila: dict) -> dict:
    """
    Deja solo cuotas plausibles y descarta el resto.

    Además del rango por cuota individual, se comprueba el MARGEN de la terna
    1X2: la suma de probabilidades implícitas tiene que estar entre 1,00 y
    1,50. Por debajo de 1,00 la terna implicaría arbitraje garantizado, que
    ninguna casa ofrece — es la firma inconfundible de un error de extracción.

    La guardia nace de un caso real: el backfill de la v76 metió 9 ternas del
    Eerste Divisie, todas de la misma fecha, con márgenes de 0,61 a 0,96
    (frente al 1,078 de mediana del resto). Son 9 de 7.379 —el 0,12 %— pero
    una cuota inventada de 7,69 en un partido que pagaba 2,50 genera un EV
    fantasma enorme y se colaría directa en la Capa 1. Mejor perderlas que
    creérselas, y mejor filtrarlas AQUÍ que en cada importador, para que
    ninguna fuente futura pueda saltarse la comprobación.
    """
    out = dict(fila)
    for c in COLUMNAS_CUOTA:
        v = out.get(c)
        try:
            v = float(v) if v is not None else None
        except (TypeError, ValueError):
            v = None
        out[c] = v if (v is not None and 1.01 < v < 1000) else None

    # v106 — LA CADENA VACÍA NO ES UN NÚMERO, Y AQUÍ SÍ IMPORTA.
    #
    # `importar_snapshots` recarga el CSV con `csv.DictReader`, que devuelve
    # '' para toda celda vacía. Los mercados ya se saneaban arriba, pero las
    # columnas numéricas que NO son cuotas no: `ah_linea` y `dias_al_partido`
    # entraban como '' en una columna REAL. Medido al empezar a guardar el
    # hándicap: **17.202 filas con `ah_linea = ''`**, todas de fotos
    # anteriores, que un `WHERE ah_linea IS NOT NULL` cuenta como si tuvieran
    # línea. Sin esto, el primer backtest de hándicap sobre las fotos habría
    # arrancado con 17.000 filas fantasma — el tipo de contaminación que no
    # deja rastro y que este módulo existe para evitar.
    for c in ('ah_linea', 'dias_al_partido'):
        v = out.get(c)
        if v == '' or v is None:
            out[c] = None
            continue
        try:
            v = float(v)
            out[c] = v if v == v else None          # descarta NaN
        except (TypeError, ValueError):
            out[c] = None

    h, d, a = out.get('odds_home'), out.get('odds_draw'), out.get('odds_away')
    if h and d and a:
        margen = 1.0 / h + 1.0 / d + 1.0 / a
        if not (1.0 <= margen <= 1.5):
            logger.debug(f"terna 1X2 descartada por margen implausible "
                         f"({margen:.3f}): {out.get('match_id')} "
                         f"{out.get('bookmaker')} {h}/{d}/{a}")
            out['odds_home'] = out['odds_draw'] = out['odds_away'] = None
    return out


CAMPOS = ('match_id', 'league_key', 'match_date', 'home_team', 'away_team',
          'bookmaker', 'fase', 'snapshot_key', 'dias_al_partido',
          'odds_home', 'odds_draw', 'odds_away', 'odds_over25', 'odds_under25',
          'odds_btts_yes', 'odds_btts_no', 'ah_linea', 'odds_ah_home',
          'odds_ah_away', 'source_file', 'ingested_at')


def guardar(con: sqlite3.Connection, filas: Iterable[dict],
            reemplazar: bool = True) -> int:
    """
    Inserta filas idempotentemente.

    `reemplazar=True` (cierre) pisa el valor anterior de esa clave: reimportar
    los CSV corregidos actualiza en vez de duplicar.
    `reemplazar=False` (snapshots) conserva la primera foto del día: si el
    workflow se ejecuta dos veces, el histórico de CLV no se altera.
    """
    verbo = 'INSERT OR REPLACE' if reemplazar else 'INSERT OR IGNORE'
    sql = (f"{verbo} INTO historical_odds ({','.join(CAMPOS)}) "
           f"VALUES ({','.join('?' * len(CAMPOS))})")
    lote, n = [], 0
    for f in filas:
        f = _limpiar(f)
        # una fila sin ninguna cuota no aporta nada
        if not any(f.get(c) for c in COLUMNAS_CUOTA):
            continue
        lote.append(tuple(f.get(c) for c in CAMPOS))
        if len(lote) >= 2000:
            con.executemany(sql, lote); n += len(lote); lote = []
    if lote:
        con.executemany(sql, lote); n += len(lote)
    con.commit()
    return n


def resumen(con: sqlite3.Connection) -> List[dict]:
    """Cobertura por liga y fase (para el informe y la UI)."""
    q = """SELECT league_key, fase, bookmaker, COUNT(*) n,
                  COUNT(DISTINCT match_id) partidos,
                  MIN(match_date) desde, MAX(match_date) hasta,
                  SUM(odds_over25 IS NOT NULL) con_ou,
                  SUM(odds_btts_yes IS NOT NULL) con_btts
           FROM historical_odds GROUP BY league_key, fase, bookmaker"""
    cur = con.execute(q)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def cierres(con: sqlite3.Connection, league_key: Optional[str] = None,
            bookmaker: Optional[str] = None) -> Dict[str, dict]:
    """
    Cuotas de cierre indexadas por match_id (para cruzar con el ledger).
    Si `bookmaker` es None devuelve la casa de mercado (`mercado`) con
    respaldo en Pinnacle.
    """
    cond, args = ["fase = 'cierre'"], []
    if league_key:
        cond.append('league_key = ?'); args.append(league_key)
    if bookmaker:
        cond.append('bookmaker = ?'); args.append(bookmaker)
    cur = con.execute(f"SELECT {','.join(CAMPOS)} FROM historical_odds "
                      f"WHERE {' AND '.join(cond)}", args)
    cols = [d[0] for d in cur.description]
    out: Dict[str, dict] = {}
    prioridad = {'mercado': 2, 'pinnacle': 1}
    for r in cur.fetchall():
        d = dict(zip(cols, r))
        prev = out.get(d['match_id'])
        if prev is None or prioridad.get(d['bookmaker'], 0) > prioridad.get(prev['bookmaker'], 0):
            out[d['match_id']] = d
    return out


# ---------------------------------------------------------------------------
# Persistencia de las FOTOS en el repositorio
#
# `odds_historico.db` está en `.gitignore` (línea 31) y así debe seguir: pesa
# 49 MB y crece cada día. Pero eso abre un agujero silencioso: el workflow de
# GitHub Actions clona limpio en cada ejecución, así que sin persistir nada
# fuera de la base, cada día arrancaría con la tabla vacía, capturaría sus 500
# filas, no commitearía nada — la base está ignorada — y al día siguiente
# volvería a empezar de cero. Meses después el "histórico acumulado" seguiría
# teniendo un día.
#
# La solución sale de separar lo reproducible de lo que no lo es:
#
#   · Las filas `fase='cierre'` se DERIVAN de los `historico_*.csv`, que sí
#     están en el repositorio: se regeneran con `import_historical_odds.py`
#     cuando haga falta. No hay que guardarlas.
#   · Las filas `fase='snapshot'` son irrepetibles: si no se capturó la línea
#     antes del partido, esa foto no existe en ninguna parte del mundo.
#
# Así que solo las fotos se vuelcan a `odds_snapshots.csv` — texto plano,
# diffeable, unos pocos MB al año — y ese fichero sí se commitea.
# ---------------------------------------------------------------------------
CSV_SNAPSHOTS = 'odds_snapshots.csv'

# v76: qué filas NO se pueden reconstruir desde el repositorio y por tanto hay
# que persistir sí o sí.
#
#   · `fase='snapshot'` — la línea antes del partido. Si no se fotografió, no
#     existe en ninguna parte.
#   · `source_file='betexplorer'` — el backfill histórico de las 22 ligas que
#     ESPN dejaba a ciegas. Se puede volver a raspar, pero depende de que un
#     sitio de terceros siga en pie y con la misma estructura; tratarlo como
#     "regenerable" sería confiar el histórico a que nada cambie nunca.
#
# Todo lo demás (los cierres de football-data) sale de los `historico_*.csv`
# que ya están versionados, así que no se duplica.
_COND_NO_REPRODUCIBLE = "(fase = 'snapshot' OR source_file = 'betexplorer')"


def exportar_snapshots(con: sqlite3.Connection,
                       ruta: str = CSV_SNAPSHOTS) -> int:
    """Vuelca al CSV todo lo que el repositorio no puede reconstruir solo."""
    import csv
    cur = con.execute(f"SELECT {','.join(CAMPOS)} FROM historical_odds "
                      f"WHERE {_COND_NO_REPRODUCIBLE} "
                      f"ORDER BY fase, snapshot_key, league_key, match_id, bookmaker")
    filas = cur.fetchall()
    with open(ruta, 'w', encoding='utf-8', newline='') as f:
        w = csv.writer(f)
        w.writerow(CAMPOS)
        w.writerows(filas)
    logger.info(f"{len(filas)} fotos exportadas a {ruta}")
    return len(filas)


def importar_snapshots(con: sqlite3.Connection,
                       ruta: str = CSV_SNAPSHOTS) -> int:
    """Recarga las fotos del CSV. Idempotente: no pisa lo que ya esté."""
    import csv
    if not os.path.exists(ruta):
        return 0
    with open(ruta, encoding='utf-8', newline='') as f:
        filas = list(csv.DictReader(f))
    # Las fotos no se pisan (INSERT OR IGNORE conserva la primera del día); los
    # cierres del backfill sí pueden refrescarse si se vuelve a raspar.
    fotos = [f for f in filas if f.get('fase') == 'snapshot']
    cierres = [f for f in filas if f.get('fase') != 'snapshot']
    n = guardar(con, fotos, reemplazar=False)
    n += guardar(con, cierres, reemplazar=True)
    logger.info(f"{n} filas no reproducibles recargadas desde {ruta} "
                f"({len(fotos)} fotos, {len(cierres)} cierres de backfill)")
    return n


def rehidratar(ruta_db: str = DB, ruta_csv: str = CSV_SNAPSHOTS,
               importar_cierres: bool = True) -> dict:
    """
    Reconstruye la base completa desde el repositorio.

    Es lo que hace utilizable una base ignorada por git: los cierres se vuelven
    a derivar de los CSV de liga y las fotos se recargan del CSV commiteado.
    Cualquier clon limpio (el runner de Actions, o el usuario en otra máquina)
    recupera el histórico entero con una llamada.
    """
    con = conectar(ruta_db)
    fotos = importar_snapshots(con, ruta_csv)
    cierres = 0
    if importar_cierres:
        con.close()
        import import_historical_odds
        cierres = import_historical_odds.importar()['filas_insertadas']
        con = conectar(ruta_db)
    total = con.execute("SELECT COUNT(*) FROM historical_odds").fetchone()[0]
    con.close()
    return {'fotos_recargadas': fotos, 'cierres_importados': cierres,
            'filas_totales': total}


# ---------------------------------------------------------------------------
# Verificación de fuentes football-data (blindaje contra el 200 engañoso)
# ---------------------------------------------------------------------------
_PAIS_ESPERADO = {
    'ARG': 'Argentina', 'AUT': 'Austria', 'BRA': 'Brazil', 'CHN': 'China',
    'DNK': 'Denmark', 'FIN': 'Finland', 'IRL': 'Ireland', 'JPN': 'Japan',
    'MEX': 'Mexico', 'NOR': 'Norway', 'POL': 'Poland', 'ROU': 'Romania',
    'RUS': 'Russia', 'SWE': 'Sweden', 'SWZ': 'Switzerland', 'USA': 'USA',
}


def _leer_csv_remoto(url: str, timeout: int = 45):
    import pandas as pd
    import requests
    r = requests.get(url, timeout=timeout)
    r.raise_for_status()
    r.encoding = 'utf-8-sig'
    df = pd.read_csv(io.StringIO(r.text), on_bad_lines='skip',
                     encoding_errors='ignore')
    # football-data sirve el BOM y, según la codificación detectada, puede
    # llegar como '﻿' o como 'ï»¿'. Se limpian ambos.
    df.columns = [re.sub(r'^(﻿|ï»¿)', '', str(c)).strip() for c in df.columns]
    return df


def fuente_football_data_valida(codigo: str, pais_esperado: Optional[str] = None,
                                equipos_esperados: Optional[Iterable[str]] = None
                                ) -> dict:
    """
    Comprueba que `/new/{codigo}.csv` es DE VERDAD la liga que se le pide.

    Devuelve {'valida': bool, 'motivo': str, 'pais': str, 'liga': str,
              'filas': int}. Nunca lanza: un fallo de red devuelve valida=False.

    Se comprueba el CONTENIDO (columna `Country` y, si se dan, los equipos),
    no el código de estado: /new/COL.csv responde 200 con la Ekstraklasa.
    """
    url = f'https://www.football-data.co.uk/new/{codigo}.csv'
    try:
        df = _leer_csv_remoto(url)
    except Exception as e:
        return {'valida': False, 'motivo': f'no accesible: {e}', 'url': url}
    if 'Country' not in df.columns or 'Home' not in df.columns:
        return {'valida': False, 'motivo': 'no tiene el esquema "new"', 'url': url}
    paises = [str(p) for p in df['Country'].dropna().unique()[:3]]
    liga = [str(p) for p in df.get('League', []).dropna().unique()[:3]] \
        if 'League' in df.columns else []
    esperado = pais_esperado or _PAIS_ESPERADO.get(codigo.upper())
    info = {'url': url, 'pais': paises, 'liga': liga, 'filas': int(len(df))}
    if esperado and (not paises or paises[0].strip().lower() != esperado.strip().lower()):
        info.update({'valida': False,
                     'motivo': f'sirve {paises} y se esperaba {esperado} '
                               f'(football-data devuelve otra liga con HTTP 200)'})
        return info
    if equipos_esperados:
        propios = {str(x).lower() for x in df['Home'].dropna().unique()}
        pedidos = {str(x).lower() for x in equipos_esperados}
        # coincidencia laxa: basta con que 3 equipos aparezcan como subcadena
        golpes = sum(1 for p in pedidos
                     if any(p in q or q in p for q in propios))
        if golpes < 3:
            info.update({'valida': False,
                         'motivo': f'solo {golpes} equipos coinciden con la liga pedida'})
            return info
        info['equipos_coincidentes'] = golpes
    info.update({'valida': True, 'motivo': 'ok'})
    return info


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    con = conectar()
    filas = resumen(con)
    print(f"{len(filas)} combinaciones liga/fase/casa en {DB}")
    for r in sorted(filas, key=lambda d: (d['league_key'], d['fase'])):
        print(f"  {r['league_key']:24s} {r['fase']:9s} {r['bookmaker']:10s} "
              f"{r['partidos']:5d} partidos  {r['desde']}..{r['hasta']}")
