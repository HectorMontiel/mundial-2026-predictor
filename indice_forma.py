#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v99.1 — Índice de Dispersión de Forma (IDF), y factor de parque de la KBO.

La idea del IDF
---------------
El ELO mide poderío a largo plazo. La forma reciente ya está en el modelo de
tenis (`DIFF_FORMA10`), pero **en bruto**: cuántos partidos ganó. Lo que no
está es la forma **relativa a lo que su nivel predeciría**, que es otra cosa:

    IDF = (resultado observado en los últimos N) − (resultado ESPERADO por ELO)

Un jugador de ELO 2000 que gana 6 de 10 contra rivales flojos no está en forma:
está por debajo. Uno de ELO 1500 que gana 4 de 10 contra top-20 está por
encima. La forma bruta no distingue esos dos casos; el IDF sí, porque descuenta
la dificultad del calendario.

Es escalable por diseño: la función es la misma para tenis, béisbol o fútbol —
sólo cambia de dónde salen «resultado» y «esperado».

Factor de parque (KBO)
----------------------
Cuántas carreras se anotan en un estadio comparado con la media de la liga. Es
información que el mercado descuenta en la línea de totales y que el modelo no
tenía: hasta la v99.1 el campo `stadium` de Naver se tiraba al construir el
histórico.

Las dos cosas se calculan con **pase cronológico**: cada partido sólo ve lo
anterior. Un factor de parque calculado con la temporada entera y aplicado a un
partido de abril es fuga de datos pura.
"""

import logging
from typing import Dict, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

VENTANAS = (5, 10, 15)          # se eligen en walk-forward, no a ojo
SUAVIZADO_PARQUE = 200          # partidos de "prior" hacia la media de liga


def esperado_elo(elo_a: float, elo_b: float) -> float:
    """Probabilidad que el ELO le da a A. Es el «lo que debería pasar»."""
    return 1.0 / (1.0 + 10 ** ((elo_b - elo_a) / 400.0))


def idf_series(resultados, esperados, ventana: int) -> np.ndarray:
    """
    IDF por evento: media móvil de (observado − esperado) sobre los `ventana`
    eventos ANTERIORES. La posición i nunca mira el resultado i.
    """
    r = np.asarray(resultados, dtype=float)
    e = np.asarray(esperados, dtype=float)
    d = r - e
    out = np.zeros(len(d))
    acc: list = []
    for i in range(len(d)):
        out[i] = float(np.mean(acc[-ventana:])) if acc else 0.0
        acc.append(d[i])
    return out


def idf_por_participante(df: pd.DataFrame, col_a: str, col_b: str,
                         col_elo_a: str, col_elo_b: str, col_gana_a: str,
                         ventana: int = 10) -> pd.DataFrame:
    """
    Calcula el IDF de los dos lados de cada enfrentamiento, cronológicamente.

    Devuelve `IDF_A`, `IDF_B` y su diferencia `DIFF_IDF`, que es la feature que
    entra al modelo (el modelo predice A contra B, así que lo que informa es la
    diferencia de desviaciones, no cada una por separado).
    """
    hist: Dict[str, list] = {}
    idf_a = np.zeros(len(df))
    idf_b = np.zeros(len(df))
    for i, f in enumerate(df.itertuples(index=False)):
        a, b = getattr(f, col_a), getattr(f, col_b)
        ea, eb = float(getattr(f, col_elo_a)), float(getattr(f, col_elo_b))
        ha, hb = hist.get(a, []), hist.get(b, [])
        idf_a[i] = float(np.mean(ha[-ventana:])) if ha else 0.0
        idf_b[i] = float(np.mean(hb[-ventana:])) if hb else 0.0
        # se registra DESPUÉS de emitir: sin fuga
        p_a = esperado_elo(ea, eb)
        gana_a = float(getattr(f, col_gana_a))
        hist.setdefault(a, []).append(gana_a - p_a)
        hist.setdefault(b, []).append((1.0 - gana_a) - (1.0 - p_a))
    out = pd.DataFrame({'IDF_A': idf_a, 'IDF_B': idf_b,
                        'DIFF_IDF': idf_a - idf_b}, index=df.index)
    # Estado FINAL por participante, para poder reproducir la feature en
    # inferencia sin rehacer el pase entero. Sin esto el modelo entrenaría con
    # una columna que en producción no existe — y fallaría al predecir, que es
    # el mejor de los casos; el peor sería que alguien la rellenara con ceros.
    out.attrs['estado'] = {k: [round(float(x), 5) for x in v[-ventana:]]
                           for k, v in hist.items()}
    return out


def factor_parque(df: pd.DataFrame, col_estadio: str = 'estadio',
                  col_total: str = 'total_carreras',
                  suavizado: int = SUAVIZADO_PARQUE) -> np.ndarray:
    """
    Factor de parque por partido, con pase cronológico y encogido a la media.

    `factor = carreras medias del estadio / carreras medias de la liga`, ambas
    calculadas SÓLO con partidos anteriores. Se encoge hacia 1 con un prior de
    `suavizado` partidos para que un estadio con 20 juegos no dé un factor
    extremo por azar — el mismo criterio de encogimiento que el proyecto usa
    con el mercado desde la v78.
    """
    est = df[col_estadio].astype(str).to_numpy()
    tot = pd.to_numeric(df[col_total], errors='coerce').to_numpy(dtype=float)
    suma_liga, n_liga = 0.0, 0
    suma_est: Dict[str, float] = {}
    n_est: Dict[str, int] = {}
    out = np.ones(len(df))
    for i in range(len(df)):
        media_liga = (suma_liga / n_liga) if n_liga else np.nan
        e = est[i]
        ne = n_est.get(e, 0)
        if n_liga >= 50 and media_liga and media_liga > 0:
            media_est = (suma_est.get(e, 0.0) / ne) if ne else media_liga
            # encogimiento: con pocos partidos, el estadio "es" la liga
            peso = ne / (ne + suavizado)
            out[i] = (peso * media_est + (1 - peso) * media_liga) / media_liga
        if not np.isnan(tot[i]):
            suma_liga += tot[i]; n_liga += 1
            suma_est[e] = suma_est.get(e, 0.0) + tot[i]
            n_est[e] = ne + 1
    return out


def resumen_parque(ruta: str = 'historico_kbo.csv') -> pd.DataFrame:
    """Factor de parque FINAL por estadio (para inspección, no para el modelo)."""
    d = pd.read_csv(ruta)
    d['total_carreras'] = d.home_runs + d.away_runs
    media = d.total_carreras.mean()
    g = d.groupby('estadio')['total_carreras'].agg(['mean', 'size'])
    g['factor'] = g['mean'] / media
    return g[g['size'] >= 100].sort_values('factor', ascending=False)


if __name__ == '__main__':
    import sys
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    sys.stdout.reconfigure(encoding='utf-8')
    print('Factor de parque de la KBO (estadios con 100+ partidos):')
    print(resumen_parque().to_string())
