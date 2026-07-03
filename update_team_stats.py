#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Estado actual de cada selección (ejecución diaria).

Lee el histórico unificado (resultados reales) y calcula, con el MISMO
EstadoRodante que usa el entrenamiento (paridad de features garantizada):
  - ELO dinámico por selección.
  - Medias móviles ponderadas de los últimos 5 partidos (peso doble al último).
  - Balance H2H reciente por pareja de selecciones.
  => team_stats.json (lo consume el endpoint de predicción, carga instantánea)

Y además, desde los goleadores REALES de Kaggle:
  - jugadores_clave.csv: máximos artilleros vigentes de cada selección con
    goles reales, racha goleadora y goles esperados estimados por calibración.
"""

import datetime
import json
import logging

import numpy as np
import pandas as pd

import feature_engineering as fe
import statsbomb_calibration
from config import TEAMS, HISTORICO_FILE

logger = logging.getLogger(__name__)

TEAM_STATS_FILE = 'team_stats.json'
JUGADORES_CLAVE_FILE = 'jugadores_clave.csv'
GOLEADORES_FILE = 'goleadores.csv'


def _metricas_reaccion(historico: pd.DataFrame) -> dict:
    """
    Métricas de carácter calculadas con los MINUTOS DE GOL REALES (24 meses):
      REACCION_TRAS_GOL: tras encajar, ¿el equipo responde marcando después?
      RENDIMIENTO_2DA_MITAD: % de sus goles anotados en la segunda mitad.
      PARTIDOS_30D: carga reciente de partidos (proxy de fatiga del plantel).
    """
    try:
        goles = pd.read_csv(GOLEADORES_FILE, parse_dates=['date'])
    except FileNotFoundError:
        return {}
    goles['minute'] = pd.to_numeric(goles['minute'], errors='coerce')
    goles = goles.dropna(subset=['minute'])
    fin = historico['date'].max()
    goles = goles[goles['date'] >= fin - pd.DateOffset(months=24)]

    resultado = {}
    for equipo in TEAMS:
        del_partido = goles[(goles['home_team'] == equipo) | (goles['away_team'] == equipo)]
        propios = del_partido[del_partido['team'] == equipo]
        encajados = del_partido[del_partido['team'] != equipo]

        # Reacción: de cada gol encajado, ¿hubo respuesta propia más tarde?
        respuestas, total_encajados = 0, 0
        for match_id, grupo in del_partido.groupby('MATCH_ID'):
            minutos_propios = grupo.loc[grupo['team'] == equipo, 'minute'].values
            for m in grupo.loc[grupo['team'] != equipo, 'minute'].values:
                total_encajados += 1
                if (minutos_propios > m).any():
                    respuestas += 1
        tasa = respuestas / total_encajados if total_encajados else 0.30
        if tasa >= 0.40:
            reaccion = 'Fuerte (responde tras encajar)'
        elif tasa >= 0.22:
            reaccion = 'Neutra'
        else:
            reaccion = 'Débil (se desorganiza)'

        # Rendimiento en segundas mitades (goles propios)
        pct_2h = float((propios['minute'] > 45).mean()) if len(propios) else 0.5
        if pct_2h > 0.55:
            rendimiento = f'Mejora (+{(pct_2h - 0.5) * 100:.0f}%)'
        elif pct_2h < 0.45:
            rendimiento = f'Empeora ({(pct_2h - 0.5) * 100:.0f}%)'
        else:
            rendimiento = 'Estable'

        partidos_30d = int(len(historico[
            ((historico['home_team'] == equipo) | (historico['away_team'] == equipo)) &
            (historico['date'] >= fin - pd.Timedelta(days=30))
        ]))

        resultado[equipo] = {
            'REACCION_TRAS_GOL': reaccion,
            'REACCION_RATE': round(tasa, 3),
            'RENDIMIENTO_2DA_MITAD': rendimiento,
            'PCT_GOLES_2H': round(pct_2h, 3),
            'GOLES_ENC_U15_24M': round(float((encajados['minute'] >= 75).sum() /
                                             max(len(del_partido['MATCH_ID'].unique()), 1)), 3),
            'PARTIDOS_30D': partidos_30d,
        }
    return resultado


def build_team_stats() -> dict:
    """Reconstruye el estado rodante y lo serializa a team_stats.json."""
    historico = pd.read_csv(HISTORICO_FILE, parse_dates=['date'])
    estado = fe.construir_dataset_supervisado(historico)['estado']
    reaccion = _metricas_reaccion(historico)

    equipos = {}
    for t in TEAMS:
        s = estado.stats_equipo(t)
        # Vectores de rendimiento de los últimos 10 partidos: insumo de las
        # entropías topológicas por equipo en el motor de inferencia.
        s['PERF10'] = [list(map(float, v)) for v in estado.perf10[t]]
        s.update(reaccion.get(t, {}))
        equipos[t] = s
    h2h = {}
    for i, a in enumerate(TEAMS):
        for b in TEAMS[i + 1:]:
            balance = estado.h2h_balance(a, b)  # desde la óptica de `a`
            if balance != 0.0:
                h2h[f"{a}|{b}"] = round(balance, 3)

    stats = {
        'generado': datetime.date.today().isoformat(),
        'ultima_fecha_historico': str(historico['date'].max().date()),
        'equipos': equipos,
        'h2h': h2h,
    }
    with open(TEAM_STATS_FILE, 'w', encoding='utf-8') as f:
        json.dump(stats, f, ensure_ascii=False, indent=1)
    logger.info(f"team_stats.json actualizado: {len(equipos)} selecciones, "
                f"{len(h2h)} parejas H2H con historial.")
    return stats


def build_key_players() -> pd.DataFrame:
    """
    Máximos artilleros vigentes por selección a partir de los goles REALES.
    Ventana: últimos 24 meses del histórico. Por jugador:
      - goles reales y partidos del equipo en la ventana
      - en cuántos de los últimos 5 partidos del equipo marcó (racha real)
      - goles esperados por partido (goles/partido con encogimiento bayesiano)
      - remates estimados vía calibración StatsBomb (remates_por_xg)
    """
    try:
        goles = pd.read_csv(GOLEADORES_FILE, parse_dates=['date'])
    except FileNotFoundError:
        logger.warning(f"No existe {GOLEADORES_FILE}: ejecuta data_fetcher primero.")
        return pd.DataFrame()

    historico = pd.read_csv(HISTORICO_FILE, parse_dates=['date'])
    cal = statsbomb_calibration.calibrar()
    fin = goles['date'].max()
    inicio = fin - pd.DateOffset(months=24)
    goles = goles[(goles['date'] >= inicio) & (~goles['own_goal'].fillna(False))]

    filas = []
    for equipo in TEAMS:
        g_eq = goles[goles['team'] == equipo]
        partidos_eq = historico[
            ((historico['home_team'] == equipo) | (historico['away_team'] == equipo)) &
            (historico['date'] >= inicio)
        ].sort_values('date')
        n_partidos = max(len(partidos_eq), 1)
        ultimos5_ids = set(partidos_eq.tail(5)['MATCH_ID'])

        if g_eq.empty:
            continue
        por_jugador = g_eq.groupby('scorer').agg(
            goles=('scorer', 'size'),
            penales=('penalty', 'sum'),
            partidos_con_gol=('MATCH_ID', 'nunique'),
        ).sort_values('goles', ascending=False).head(8)

        for nombre, r in por_jugador.iterrows():
            marco_en_ult5 = g_eq[(g_eq['scorer'] == nombre) &
                                 (g_eq['MATCH_ID'].isin(ultimos5_ids))]['MATCH_ID'].nunique()
            # Goles esperados/partido con encogimiento (prior 0.15, peso 6 partidos)
            xg_pp = (r['goles'] + 0.15 * 6) / (n_partidos + 6)
            remates_arco = xg_pp * cal['shots_on_por_xg']
            filas.append({
                'EQUIPO_NOMBRE': equipo,
                'JUGADOR_NOMBRE': nombre,
                'GOLES_24M': int(r['goles']),
                'PENALES_24M': int(r['penales']),
                'PARTIDOS_EQUIPO_24M': int(n_partidos),
                'GOLES_POR_PARTIDO': round(float(r['goles'] / n_partidos), 3),
                'XG_ESTIMADO_PARTIDO': round(float(xg_pp), 3),
                'REMATES_ARCO_ESTIMADOS': round(float(remates_arco), 2),
                'REMATES_TOTALES_ESTIMADOS': round(float(remates_arco * cal['shots_total_por_on']), 2),
                'PARTIDOS_MARCANDO_DE_5': int(marco_en_ult5),
                'PROB_MARCAR': round(float(1 - np.exp(-1.3 * xg_pp)), 3),
            })

    df = pd.DataFrame(filas)
    df.to_csv(JUGADORES_CLAVE_FILE, index=False)
    logger.info(f"jugadores_clave.csv: {len(df)} artilleros reales de "
                f"{df['EQUIPO_NOMBRE'].nunique() if not df.empty else 0} selecciones.")
    return df


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    build_team_stats()
    build_key_players()
