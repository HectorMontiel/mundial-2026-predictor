#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Base de jugadores con xG/90 estimado + ajuste por alineación (v20, EXPERIMENTAL).

Minutos: estimados desde las alineaciones de ESPN (lineup_collector) —
90 titular completo, 70 titular sustituido, 25 suplente que entra.
Goles: reales de Kaggle (goleadores.csv). xg90 = goles*90/minutos con
suavizado bayesiano hacia la media (evita xg90 absurdos con pocos minutos).

El ajuste de xG por alineación confirmada NUNCA toca el modelo 1X2: solo se
muestra como información en la UI cuando hay alineación del día. Su impacto
se medirá EN VIVO durante la temporada 2026-27 (comparando predicción base
vs ajustada en los mismos partidos) — VALIDACION_v21.
"""

import logging
import os
import unicodedata

import pandas as pd

logger = logging.getLogger(__name__)

ALINEACIONES = 'alineaciones_historicas.csv'
SALIDA = 'jugadores_xg.csv'
MIN_MINUTOS = 180          # bajo esto, xg90 = media de la plantilla
XG90_MEDIO = 0.12          # prior (gol cada ~750 min, típico de plantilla)
PESO_PRIOR = 450.0         # minutos de peso del prior en el suavizado


def _norm(s: str) -> str:
    s = unicodedata.normalize('NFKD', str(s))
    return ''.join(c for c in s if not unicodedata.combining(c)).lower().strip()


def _minutos(fila) -> float:
    if fila.get('titular'):
        return 70.0 if fila.get('salio') else 90.0
    return 25.0 if fila.get('entro') else 0.0


def construir() -> pd.DataFrame:
    """Reconstruye jugadores_xg.csv desde alineaciones + goleadores."""
    if not os.path.exists(ALINEACIONES):
        logger.info("[player_db] sin alineaciones acumuladas todavía.")
        return pd.DataFrame()
    al = pd.read_csv(ALINEACIONES)
    al['minutos'] = al.apply(_minutos, axis=1)
    mins = al.groupby(al['jugador'].map(_norm)).agg(
        nombre=('jugador', 'last'), equipo=('equipo', 'last'),
        minutos=('minutos', 'sum'), partidos=('event_id', 'nunique')).reset_index(names='jid')

    goles = pd.DataFrame(columns=['jid', 'goles'])
    if os.path.exists('goleadores.csv'):
        g = pd.read_csv('goleadores.csv')
        col = next((c for c in ('scorer', 'jugador', 'player') if c in g.columns), None)
        if col:
            fecha_col = next((c for c in ('date', 'fecha') if c in g.columns), None)
            if fecha_col:
                g[fecha_col] = pd.to_datetime(g[fecha_col], errors='coerce')
                g = g[g[fecha_col] >= pd.Timestamp.today() - pd.DateOffset(months=24)]
            goles = g.groupby(g[col].map(_norm)).size().reset_index(name='goles') \
                .rename(columns={col: 'jid', g[col].map(_norm).name: 'jid'})
            goles.columns = ['jid', 'goles']

    df = mins.merge(goles, on='jid', how='left').fillna({'goles': 0})
    # suavizado bayesiano: (goles + prior*peso/90) / (minutos + peso) * 90
    df['xg90_estimado'] = ((df['goles'] + XG90_MEDIO * PESO_PRIOR / 90.0)
                           / (df['minutos'] + PESO_PRIOR) * 90.0).round(4)
    df.loc[df['minutos'] < MIN_MINUTOS, 'xg90_estimado'] = XG90_MEDIO
    df.to_csv(SALIDA, index=False, encoding='utf-8')
    logger.info(f"[player_db] {len(df)} jugadores, {df['minutos'].sum():.0f} min acumulados.")
    return df


def factores_para_partido(home: str, away: str):
    """(factor_home, factor_away, detalle) si HOY hay alineación confirmada de
    ambos equipos; None si no. factor = avg_xg90_titulares / avg_xg90_plantilla."""
    if not (os.path.exists(ALINEACIONES) and os.path.exists(SALIDA)):
        return None
    al = pd.read_csv(ALINEACIONES)
    hoy = pd.Timestamp.today().strftime('%Y-%m-%d')
    al = al[al['fecha'] == hoy]
    if al.empty:
        return None
    db = pd.read_csv(SALIDA)
    db['jid'] = db['nombre'].map(_norm)
    xg = db.set_index('jid')['xg90_estimado']

    factores = {}
    for equipo in (home, away):
        rows = al[al['equipo'].map(_norm).str.contains(_norm(equipo)[:8], na=False)]
        tit = rows[rows['titular'] == True]      # noqa: E712
        if len(tit) < 7:
            return None
        v_tit = tit['jugador'].map(_norm).map(xg).dropna()
        v_all = rows['jugador'].map(_norm).map(xg).dropna()
        if len(v_tit) < 5 or v_all.mean() <= 0:
            return None
        factores[equipo] = float(v_tit.mean() / v_all.mean())
    return (round(factores[home], 3), round(factores[away], 3),
            f"titulares confirmados hoy ({hoy})")


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    df = construir()
    if not df.empty:
        print(df.sort_values('xg90_estimado', ascending=False).head(10).to_string())
