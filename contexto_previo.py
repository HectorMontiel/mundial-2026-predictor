#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v101 — Contexto del partido ANTERIOR: qué traía cada equipo encima al llegar.

La pregunta que contesta
------------------------
El modelo predice con estadística acumulada: ELO, medias móviles, xG. Todo eso
describe lo que un equipo ES, no en qué CIRCUNSTANCIA llega. Cuando un pronóstico
falla —«más de 1.5 goles» y el partido acaba 0-0— la explicación candidata no
suele estar en la media de la temporada, sino en el partido de antes:

  · venía de medirse a un rival muy superior y se vació;
  · venía de una goleada y bajó el pie;
  · jugó hace tres días y llegó con las piernas cargadas;
  · o el escalón cambió — ganó al primero y hoy visita al decimoquinto.

Este módulo convierte esas cuatro circunstancias en números, con **pase
cronológico estricto**: la fila i sólo ve los partidos anteriores a i. Nunca su
propio resultado.

Qué NO es
---------
No es un modelo ni un ajuste. Es un extractor de features. Si estas columnas
mejoran o no la predicción es una pregunta empírica que se contesta en el A/B
con walk-forward y bootstrap (`_v101_ab_contexto_*.py`), no aquí. El módulo se
limita a producirlas de forma reproducible en entrenamiento y en inferencia.

Es genérico por diseño: la firma no menciona fútbol. Recibe un histórico
cronológico de enfrentamientos A-vs-B y devuelve el contexto de los dos lados,
igual sirva para equipos o para tenistas.
"""

import logging
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ELO rodante propio. K y ventaja local son los valores estándar del proyecto
# (`calibracion_elo`); no se afinan aquí porque este ELO no compite con el del
# modelo: sólo sirve de REGLA para medir a los rivales entre sí. Lo único que
# se le pide es ser consistente.
ELO_INICIAL = 1500.0
ELO_K = 20.0
ELO_VENTAJA_LOCAL = 60.0

# Escala con la que se normalizan las diferencias de ELO. 400 es un "escalón"
# de ELO completo (10:1 en cuota), así que las features salen en unidades
# interpretables: 0,5 = medio escalón.
ESCALA_ELO = 400.0

COLUMNAS = ['DIFF_DESCANSO', 'DIFF_ESCALON', 'DIFF_SORPRESA_PREV',
            'DIFF_MARGEN_PREV', 'DIFF_CARGA']

# Tope de días de descanso. Por encima de esto no es "descanso", es pretemporada
# o una lesión larga, y la diferencia entre 60 y 200 días no informa de lo mismo.
DESCANSO_MAX = 21.0


def elo_rodante(df: pd.DataFrame, col_a: str, col_b: str, col_res_a: str,
                ventaja_a: float = 0.0, k: float = ELO_K
                ) -> Tuple[np.ndarray, np.ndarray, Dict[str, float]]:
    """
    ELO PRE-partido de los dos lados, en orden cronológico.

    `col_res_a` es el resultado desde la perspectiva de A: 1 gana, 0,5 empata,
    0 pierde. `ventaja_a` es el bono de localía en puntos de ELO (0 en deportes
    sin campo propio, como el tenis).

    Devuelve (elo_a, elo_b, estado_final). El estado final permite reproducir la
    feature en inferencia sin rehacer el pase entero — el mismo patrón que usa
    `indice_forma.idf_por_participante`.
    """
    a = df[col_a].astype(str).to_numpy()
    b = df[col_b].astype(str).to_numpy()
    r = pd.to_numeric(df[col_res_a], errors='coerce').to_numpy(dtype=float)
    ea = np.full(len(df), ELO_INICIAL)
    eb = np.full(len(df), ELO_INICIAL)
    elo: Dict[str, float] = {}
    for i in range(len(df)):
        ra = elo.get(a[i], ELO_INICIAL)
        rb = elo.get(b[i], ELO_INICIAL)
        ea[i], eb[i] = ra, rb
        if np.isnan(r[i]):
            continue
        esp = 1.0 / (1.0 + 10 ** ((rb - (ra + ventaja_a)) / ESCALA_ELO))
        ajuste = k * (r[i] - esp)
        elo[a[i]] = ra + ajuste
        elo[b[i]] = rb - ajuste
    return ea, eb, elo


def contexto(df: pd.DataFrame, col_fecha: str, col_a: str, col_b: str,
             col_res_a: str, col_margen_a: Optional[str] = None,
             ventaja_a: float = 0.0) -> pd.DataFrame:
    """
    Contexto del partido anterior de cada lado, fila a fila y sin fuga.

    `df` debe venir ORDENADO por fecha ascendente. Cada fila mira sólo hacia
    atrás; el resultado de la propia fila se registra después de emitirla.

    Columnas devueltas (todas como diferencia A−B, que es lo que informa a un
    modelo que predice A contra B; las de cada lado van también, con sufijo):

      DIFF_DESCANSO       días de descanso de A menos los de B, normalizado.
      DIFF_ESCALON        cuánto BAJA el nivel del rival respecto al anterior.
                          Positivo = A viene de alguien más fuerte que el de hoy.
                          Es la hipótesis literal: «venció a un equipo más fuerte».
      DIFF_SORPRESA_PREV  observado − esperado en el partido anterior. Positivo =
                          A rindió por encima de su nivel la última vez.
      DIFF_MARGEN_PREV    margen del partido anterior, normalizado y con signo.
      DIFF_CARGA          partidos jugados en los últimos 14 días (acumulación).
    """
    n = len(df)
    if n == 0:
        return pd.DataFrame(columns=COLUMNAS)

    ea, eb, _final = elo_rodante(df, col_a, col_b, col_res_a, ventaja_a)
    fechas = pd.to_datetime(df[col_fecha], errors='coerce')
    a = df[col_a].astype(str).to_numpy()
    b = df[col_b].astype(str).to_numpy()
    res = pd.to_numeric(df[col_res_a], errors='coerce').to_numpy(dtype=float)
    if col_margen_a and col_margen_a in df.columns:
        margen = pd.to_numeric(df[col_margen_a], errors='coerce').to_numpy(dtype=float)
    else:
        margen = np.full(n, np.nan)

    # último partido de cada participante: (fecha, elo_del_rival, sorpresa, margen)
    ultimo: Dict[str, tuple] = {}
    # fechas de todos sus partidos, para la carga de 14 días
    agenda: Dict[str, List[pd.Timestamp]] = {}

    cols = {c: np.zeros(n) for c in
            ('DESCANSO_A', 'DESCANSO_B', 'ESCALON_A', 'ESCALON_B',
             'SORPRESA_PREV_A', 'SORPRESA_PREV_B', 'MARGEN_PREV_A',
             'MARGEN_PREV_B', 'CARGA_A', 'CARGA_B')}

    for i in range(n):
        f = fechas.iloc[i]
        for lado, quien, elo_propio, elo_rival_hoy in (
                ('A', a[i], ea[i], eb[i]), ('B', b[i], eb[i], ea[i])):
            prev = ultimo.get(quien)
            if prev is not None and pd.notna(f) and pd.notna(prev[0]):
                dias = (f - prev[0]).days
                cols[f'DESCANSO_{lado}'][i] = min(max(dias, 0), DESCANSO_MAX) / DESCANSO_MAX
                # escalón: rival de la vez pasada MENOS rival de hoy. Positivo
                # significa que hoy se enfrenta a alguien más débil que el
                # anterior — que es cuando el usuario sospecha la relajación.
                cols[f'ESCALON_{lado}'][i] = (prev[1] - elo_rival_hoy) / ESCALA_ELO
                cols[f'SORPRESA_PREV_{lado}'][i] = prev[2]
                cols[f'MARGEN_PREV_{lado}'][i] = prev[3]
            # carga: cuántos partidos en los 14 días previos (sin contar hoy)
            if pd.notna(f):
                prevs = agenda.get(quien, [])
                cols[f'CARGA_{lado}'][i] = sum(
                    1 for x in prevs[-12:] if 0 <= (f - x).days <= 14)

        # …y ahora sí se registra este partido, después de haberlo emitido.
        if pd.notna(f):
            agenda.setdefault(a[i], []).append(f)
            agenda.setdefault(b[i], []).append(f)
        if not np.isnan(res[i]):
            esp_a = 1.0 / (1.0 + 10 ** ((eb[i] - (ea[i] + ventaja_a)) / ESCALA_ELO))
            m = margen[i]
            # el margen se aplasta con tanh: la diferencia entre ganar por 1 y
            # por 3 informa, la de ganar por 6 u 8 ya no.
            m_norm = float(np.tanh(m / 2.0)) if not np.isnan(m) else 0.0
            ultimo[a[i]] = (f, eb[i], res[i] - esp_a, m_norm)
            ultimo[b[i]] = (f, ea[i], (1.0 - res[i]) - (1.0 - esp_a), -m_norm)

    out = pd.DataFrame(cols, index=df.index)
    out['DIFF_DESCANSO'] = out['DESCANSO_A'] - out['DESCANSO_B']
    out['DIFF_ESCALON'] = out['ESCALON_A'] - out['ESCALON_B']
    out['DIFF_SORPRESA_PREV'] = out['SORPRESA_PREV_A'] - out['SORPRESA_PREV_B']
    out['DIFF_MARGEN_PREV'] = out['MARGEN_PREV_A'] - out['MARGEN_PREV_B']
    out['DIFF_CARGA'] = (out['CARGA_A'] - out['CARGA_B']) / 4.0
    # El ELO pre-partido va como COLUMNA, no como `attrs`: pandas propaga
    # `attrs` en las operaciones y un array ahí revienta cualquier `concat` de
    # dos tramos de distinta longitud. Además la autopsia lo necesita para poder
    # decir «venía de un rival de 1720».
    out['ELO_A'] = ea
    out['ELO_B'] = eb
    return out


def contexto_futbol(df: pd.DataFrame) -> pd.DataFrame:
    """
    Atajo para el histórico de fútbol del proyecto (`historico_<liga>.csv`).

    Espera `date`, `home_team`, `away_team`, `home_goals`, `away_goals`.
    Ordena por fecha —el pase cronológico lo exige— y devuelve el contexto con
    el índice original, para poder pegarlo por `MATCH_ID`.
    """
    d = df.copy()
    d['_f'] = pd.to_datetime(d['date'], errors='coerce')
    d = d.sort_values('_f', kind='stable')
    gl = pd.to_numeric(d['home_goals'], errors='coerce')
    gv = pd.to_numeric(d['away_goals'], errors='coerce')
    d['_res'] = np.where(gl > gv, 1.0, np.where(gl == gv, 0.5, 0.0))
    d.loc[gl.isna() | gv.isna(), '_res'] = np.nan
    d['_margen'] = gl - gv
    ctx = contexto(d, '_f', 'home_team', 'away_team', '_res', '_margen',
                   ventaja_a=ELO_VENTAJA_LOCAL)
    if 'MATCH_ID' in d.columns:
        ctx['MATCH_ID'] = d['MATCH_ID'].to_numpy()
    ctx['_fecha'] = d['_f'].to_numpy()
    return ctx


def contexto_tenis(df: pd.DataFrame) -> pd.DataFrame:
    """
    Atajo para `historico_tenis_espn.csv` y el histórico ATP/WTA del motor.

    Sin ventaja local —no la hay— y el margen sale de los sets. Acepta tanto el
    formato de ESPN (`jugador_1`/`ganador`) como el del motor (`winner_name`/
    `loser_name`), que es el que ve `TennisEngine`.
    """
    d = df.copy()
    if 'jugador_1' in d.columns:
        d['_f'] = pd.to_datetime(d['fecha'], errors='coerce')
        d['_a'], d['_b'] = d['jugador_1'].astype(str), d['jugador_2'].astype(str)
        d['_res'] = (d['ganador'].astype(str) == d['_a']).astype(float)
        s1 = pd.to_numeric(d.get('sets_1'), errors='coerce')
        s2 = pd.to_numeric(d.get('sets_2'), errors='coerce')
        d['_margen'] = s1 - s2
    else:
        col_f = 'tourney_date' if 'tourney_date' in d.columns else 'fecha'
        d['_f'] = pd.to_datetime(d[col_f], errors='coerce', format='mixed')
        d['_a'], d['_b'] = d['winner_name'].astype(str), d['loser_name'].astype(str)
        d['_res'] = 1.0
        d['_margen'] = np.nan
    d = d.sort_values('_f', kind='stable')
    return contexto(d, '_f', '_a', '_b', '_res', '_margen', ventaja_a=0.0)


if __name__ == '__main__':
    import sys
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
    liga = sys.argv[1] if len(sys.argv) > 1 else 'premier'
    d = pd.read_csv(f'historico_{liga}.csv')
    ctx = contexto_futbol(d)
    print(f'{liga}: {len(ctx)} partidos')
    print(ctx[COLUMNAS].describe().T.to_string())
