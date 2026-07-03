#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Feature engineering táctico-topológico.

Principios:
  * SIN FUGA DE DATOS: todas las features de un partido se calculan solo con
    información disponible ANTES del pitazo inicial (ELO previo, medias
    móviles ponderadas de los 5 partidos anteriores, historial H2H previo).
  * Agregación inteligente de jugadores: las 110 variables individuales se
    condensan en métricas de equipo + heterogeneidad. La tabla individual
    se conserva solo para consultas ("¿quién remata más?").
  * Interacciones tácticas: choque de estilos, altitud, ventaja de localía
    real por estadio, clima histórico de la sede, historial reciente H2H.
  * Normalización MinMax [0,1] de todas las variables numéricas.
"""

import datetime
from collections import defaultdict, deque
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from sklearn.preprocessing import MinMaxScaler

from config import TEAM_STYLE, STADIUMS

# ---------------------------------------------------------------------------
# Contexto de sedes: influencia real de localía y clima histórico (junio-julio)
# ---------------------------------------------------------------------------
VENTAJA_LOCALIA_ESTADIO = {
    'Azteca': 1.00, 'Akron': 0.85, 'Estadio_BBVA': 0.85,
    'Arrowhead': 0.75, 'Lumen_Field': 0.75, 'Gillette': 0.60,
    'MetLife': 0.55, 'AT&T': 0.60, 'SoFi': 0.55, 'HardRock': 0.60,
    'Mercedes-Benz': 0.60, "Levi's": 0.55, 'NRG': 0.60,
    'Lincoln_Financial': 0.60, 'BC_Place': 0.65, 'BMO_Field': 0.65,
}
CLIMA_ESTADIO_TEMP_C = {
    'Azteca': 18, 'Akron': 24, 'Estadio_BBVA': 31, 'MetLife': 26,
    'AT&T': 33, 'SoFi': 24, 'HardRock': 31, 'Mercedes-Benz': 30,
    "Levi's": 24, 'NRG': 34, 'Lincoln_Financial': 28, 'Arrowhead': 31,
    'Gillette': 25, 'Lumen_Field': 21, 'BC_Place': 20, 'BMO_Field': 24,
}

ALTURA_MAXIMA = 3000.0
ELO_MIN, ELO_MAX = 1200.0, 2000.0

# Estadísticas rodadas que se mantienen por equipo (últimos 5 partidos)
# g2h = fracción de los goles propios anotados en la 2ª mitad (minuto real)
# encu15 = goles encajados en los últimos 15 minutos (minuto real)
STATS_RODADAS = ['gf', 'ga', 'xgf', 'xgc', 'sotf', 'sotc', 'amar', 'rojas', 'pts',
                 'g2h', 'encu15']

# Nombres de las features del clasificador (diferencias local - visitante + contexto)
# NOTA: G2H_MA5 y ENCU15_MA5 se calculan y exponen en stats_equipo, pero NO
# entran al clasificador: en backtesting empeoraron levemente el log-loss
# (0.892 -> 0.899) porque el desglose de minutos solo existe desde 2018.
# Se usan donde sí demuestran valor: tarjetas, timeline y observaciones.
FEATURES_MODELO = [
    'DIFF_ELO', 'DIFF_GF_MA5', 'DIFF_GA_MA5', 'DIFF_XGF_MA5', 'DIFF_XGC_MA5',
    'DIFF_SOTF_MA5', 'DIFF_SOTC_MA5', 'DIFF_AMAR_MA5', 'DIFF_ROJAS_MA5',
    'DIFF_FORMA_MA5', 'CHOQUE_ESTILOS', 'ALTURA_NORM', 'VENTAJA_LOCALIA',
    'CLIMA_TEMP_NORM', 'H2H_BALANCE',
]

# Features topológicas que se anexan tras la normalización:
# entropías del par (nube combinada) + entropías por equipo (últimos 10 partidos)
FEATURES_TOPO = ['ENT_PAR_H0', 'ENT_PAR_H1',
                 'ENT_LOCAL_H0', 'ENT_LOCAL_H1',
                 'ENT_VISIT_H0', 'ENT_VISIT_H1']

# Dimensiones del vector de rendimiento por partido (para la nube de 10)
PERF_DENOMINADORES = np.array([4.0, 4.0, 4.0, 4.0, 10.0, 10.0])  # gf, gc, xgf, xgc, sotf, sotc


def media_ponderada(valores: List[float]) -> float:
    """Media móvil ponderada de los últimos 5 valores, peso doble al más reciente."""
    if not valores:
        return 0.0
    v = list(valores)[-5:]
    n = len(v)
    w = np.array(([1.0] * (n - 1) + [2.0]) if n > 1 else [1.0])
    return float(np.dot(v, w / w.sum()))


def choque_estilos(local: str, visitante: str) -> float:
    """
    Codifica la interacción táctica:
      +1  bloque alto (local) vs bloque bajo (visitante) — local domina el balón
       0  estilos iguales
      -1  bloque bajo (local) vs bloque alto (visitante) — visitante presiona
    """
    e_l = TEAM_STYLE.get(local, 'bloque_alto')
    e_v = TEAM_STYLE.get(visitante, 'bloque_alto')
    if e_l == e_v:
        return 0.0
    return 1.0 if e_l == 'bloque_alto' else -1.0


class EstadoRodante:
    """
    Mantiene, partido a partido y en orden cronológico, el estado previo de
    cada selección: ELO dinámico, ventanas de 5 partidos y H2H por pareja.
    Es el mismo objeto para entrenamiento e inferencia => paridad de features.
    """

    def __init__(self):
        self.elo: Dict[str, float] = defaultdict(lambda: 1500.0)
        self.ventanas: Dict[str, Dict[str, deque]] = defaultdict(
            lambda: {s: deque(maxlen=5) for s in STATS_RODADAS})
        self.h2h: Dict[Tuple[str, str], deque] = defaultdict(lambda: deque(maxlen=6))
        # Vectores de rendimiento de los últimos 10 partidos (nube topológica)
        self.perf10: Dict[str, deque] = defaultdict(lambda: deque(maxlen=10))

    # ---------------- lectura del estado previo ---------------- #
    def stats_equipo(self, equipo: str) -> Dict[str, float]:
        v = self.ventanas[equipo]
        return {
            'ELO': self.elo[equipo],
            'GF_MA5': media_ponderada(list(v['gf'])),
            'GA_MA5': media_ponderada(list(v['ga'])),
            'XGF_MA5': media_ponderada(list(v['xgf'])),
            'XGC_MA5': media_ponderada(list(v['xgc'])),
            'SOTF_MA5': media_ponderada(list(v['sotf'])),
            'SOTC_MA5': media_ponderada(list(v['sotc'])),
            'AMAR_MA5': media_ponderada(list(v['amar'])),
            'ROJAS_MA5': media_ponderada(list(v['rojas'])),
            'FORMA_MA5': media_ponderada(list(v['pts'])),
            # Neutros cuando no hay desglose de minutos (partidos previos a 2018)
            'G2H_MA5': media_ponderada(list(v['g2h'])) if len(v['g2h']) else 0.5,
            'ENCU15_MA5': media_ponderada(list(v['encu15'])) if len(v['encu15']) else 0.3,
            'N_PARTIDOS': len(v['gf']),
        }

    def h2h_balance(self, local: str, visitante: str) -> float:
        """Balance de los últimos cruces directos desde la óptica del local: [-1, 1]."""
        clave = tuple(sorted((local, visitante)))
        historial = self.h2h[clave]
        if not historial:
            return 0.0
        # Cada entrada es (ganador, perdedor) o ('empate', ...)
        saldo = 0.0
        for ganador in historial:
            if ganador == local:
                saldo += 1.0
            elif ganador == visitante:
                saldo -= 1.0
        return saldo / len(historial)

    # ---------------- actualización tras el partido ---------------- #
    def actualizar(self, fila: pd.Series):
        h, a = fila['home_team'], fila['away_team']
        gh, ga = float(fila['home_goals']), float(fila['away_goals'])

        for equipo, gf, gc, xgf, xgc, sotf, sotc, amar, rojas in [
            (h, gh, ga, fila['home_xg'], fila['away_xg'],
             fila['home_shots_on'], fila['away_shots_on'],
             fila['home_yellow'], fila['home_red']),
            (a, ga, gh, fila['away_xg'], fila['home_xg'],
             fila['away_shots_on'], fila['home_shots_on'],
             fila['away_yellow'], fila['away_red']),
        ]:
            v = self.ventanas[equipo]
            v['gf'].append(float(gf)); v['ga'].append(float(gc))
            v['xgf'].append(float(xgf)); v['xgc'].append(float(xgc))
            v['sotf'].append(float(sotf)); v['sotc'].append(float(sotc))
            v['amar'].append(float(amar)); v['rojas'].append(float(rojas))
            pts = 1.0 if gf > gc else (0.5 if gf == gc else 0.0)
            v['pts'].append(pts)
            self.perf10[equipo].append([float(gf), float(gc), float(xgf),
                                        float(xgc), float(sotf), float(sotc)])

        # Minutos de gol reales (disponibles desde 2018): 2ª mitad y últimos 15'
        g2h_h, g2h_a = fila.get('home_goals_2h'), fila.get('away_goals_2h')
        u15_h, u15_a = fila.get('home_goals_u15'), fila.get('away_goals_u15')
        if pd.notna(g2h_h) and pd.notna(g2h_a):
            if gh > 0:
                self.ventanas[h]['g2h'].append(float(g2h_h) / gh)
            if ga > 0:
                self.ventanas[a]['g2h'].append(float(g2h_a) / ga)
        if pd.notna(u15_h) and pd.notna(u15_a):
            self.ventanas[h]['encu15'].append(float(u15_a))  # encajados por el local
            self.ventanas[a]['encu15'].append(float(u15_h))  # encajados por el visitante

        # ELO
        e_h = 1 / (1 + 10 ** ((self.elo[a] - self.elo[h]) / 400))
        s_h = 1.0 if gh > ga else (0.5 if gh == ga else 0.0)
        self.elo[h] += 32 * (s_h - e_h)
        self.elo[a] += 32 * ((1 - s_h) - (1 - e_h))

        # H2H
        clave = tuple(sorted((h, a)))
        ganador = h if gh > ga else (a if ga > gh else 'empate')
        self.h2h[clave].append(ganador)


def contexto_partido(local: str, visitante: str, stadium: Optional[str],
                     estado: EstadoRodante) -> Dict[str, float]:
    """Variables de contexto de la sede + interacción táctica + H2H."""
    altura = STADIUMS.get(stadium, 0) if stadium else 0
    return {
        'CHOQUE_ESTILOS': choque_estilos(local, visitante),
        'ALTURA_NORM': float(altura) / ALTURA_MAXIMA,
        'VENTAJA_LOCALIA': VENTAJA_LOCALIA_ESTADIO.get(stadium, 0.55) if stadium else 0.55,
        'CLIMA_TEMP_NORM': (CLIMA_ESTADIO_TEMP_C.get(stadium, 25) if stadium else 25) / 40.0,
        'H2H_BALANCE': estado.h2h_balance(local, visitante),
    }


def vector_features(stats_local: Dict, stats_visit: Dict, contexto: Dict) -> List[float]:
    """Vector de entrada del clasificador (orden = FEATURES_MODELO)."""
    return [
        (stats_local['ELO'] - stats_visit['ELO']) / 400.0,
        stats_local['GF_MA5'] - stats_visit['GF_MA5'],
        stats_local['GA_MA5'] - stats_visit['GA_MA5'],
        stats_local['XGF_MA5'] - stats_visit['XGF_MA5'],
        stats_local['XGC_MA5'] - stats_visit['XGC_MA5'],
        stats_local['SOTF_MA5'] - stats_visit['SOTF_MA5'],
        stats_local['SOTC_MA5'] - stats_visit['SOTC_MA5'],
        stats_local['AMAR_MA5'] - stats_visit['AMAR_MA5'],
        stats_local['ROJAS_MA5'] - stats_visit['ROJAS_MA5'],
        stats_local['FORMA_MA5'] - stats_visit['FORMA_MA5'],
        contexto['CHOQUE_ESTILOS'],
        contexto['ALTURA_NORM'],
        contexto['VENTAJA_LOCALIA'],
        contexto['CLIMA_TEMP_NORM'],
        contexto['H2H_BALANCE'],
    ]


def nube_de_puntos(stats_local: Dict, stats_visit: Dict, contexto: Dict) -> np.ndarray:
    """
    Nube de puntos del partido para el complejo de Vietoris-Rips (6 x 10):
    vector local, vector visitante, punto medio, diferencia absoluta y los
    perfiles ofensivo/defensivo cruzados. Cada eje ya está pre-escalado a
    magnitudes comparables; el MinMax local final garantiza [0,1].
    """
    def perfil(s: Dict) -> np.ndarray:
        return np.array([
            (s['ELO'] - ELO_MIN) / (ELO_MAX - ELO_MIN),
            s['GF_MA5'] / 4.0, s['GA_MA5'] / 4.0,
            s['XGF_MA5'] / 4.0, s['XGC_MA5'] / 4.0,
            s['SOTF_MA5'] / 10.0, s['SOTC_MA5'] / 10.0,
            s['AMAR_MA5'] / 5.0, s['ROJAS_MA5'],
            s['FORMA_MA5'],
        ], dtype=float)

    v_l, v_v = perfil(stats_local), perfil(stats_visit)
    contexto_vec = np.array([
        contexto['ALTURA_NORM'], contexto['VENTAJA_LOCALIA'],
        contexto['CLIMA_TEMP_NORM'], (contexto['CHOQUE_ESTILOS'] + 1) / 2,
        (contexto['H2H_BALANCE'] + 1) / 2,
        0.0, 0.0, 0.0, 0.0, 0.0,
    ], dtype=float)
    return np.vstack([
        v_l, v_v, (v_l + v_v) / 2.0, np.abs(v_l - v_v),
        np.concatenate([v_l[:5], v_v[5:]]),   # ataque local vs defensa visitante
        contexto_vec,
    ])


def nube_equipo(perf: List[List[float]]) -> np.ndarray:
    """
    Nube topológica de un equipo: sus últimos 10 vectores de rendimiento
    (goles, xG, remates a favor y en contra), escalados a magnitudes
    comparables y rellenados por repetición de borde hasta 10 puntos.
    """
    arr = np.asarray(perf, dtype=float) / PERF_DENOMINADORES
    if len(arr) < 10:
        relleno = np.repeat(arr[-1:], 10 - len(arr), axis=0)
        arr = np.vstack([arr, relleno])
    return arr


def construir_dataset_supervisado(historico: pd.DataFrame):
    """
    Recorre el histórico en orden cronológico construyendo, para cada
    partido, las features previas (sin fuga) y la etiqueta real.
    Devuelve un dict con: X_df, y, fechas, nubes_par (n,6,10),
    nubes_local (n,10,6), nubes_visit (n,10,6), goles (n,2) y estado.
    """
    df = historico.copy()
    df['date'] = pd.to_datetime(df['date'])
    # Orden total determinista: los empates de fecha se procesan siempre igual
    claves_orden = ['date', 'MATCH_ID'] if 'MATCH_ID' in df.columns else ['date']
    df = df.sort_values(claves_orden, kind='mergesort').reset_index(drop=True)

    numericas = ['home_goals', 'away_goals', 'home_xg', 'away_xg',
                 'home_shots_on', 'away_shots_on', 'home_yellow',
                 'away_yellow', 'home_red', 'away_red']
    for c in numericas:
        df[c] = pd.to_numeric(df[c], errors='coerce')
    df = df.dropna(subset=numericas).reset_index(drop=True)

    estado = EstadoRodante()
    filas, etiquetas, fechas, meta = [], [], [], []
    nubes_par, nubes_local, nubes_visit, goles = [], [], [], []

    for _, fila in df.iterrows():
        local, visit = fila['home_team'], fila['away_team']
        s_l = estado.stats_equipo(local)
        s_v = estado.stats_equipo(visit)
        # Solo entrenar con partidos donde ambos equipos ya tienen historial
        if s_l['N_PARTIDOS'] >= 3 and s_v['N_PARTIDOS'] >= 3:
            ctx = contexto_partido(local, visit, fila.get('stadium'), estado)
            filas.append(vector_features(s_l, s_v, ctx))
            nubes_par.append(nube_de_puntos(s_l, s_v, ctx))
            nubes_local.append(nube_equipo(list(estado.perf10[local])))
            nubes_visit.append(nube_equipo(list(estado.perf10[visit])))
            gh, ga = fila['home_goals'], fila['away_goals']
            etiquetas.append(0 if gh > ga else (1 if gh == ga else 2))
            goles.append([float(gh), float(ga)])
            fechas.append(fila['date'])
            meta.append((local, visit, fila.get('stadium'), fila.get('MATCH_ID')))
        estado.actualizar(fila)

    return {
        'X_df': pd.DataFrame(filas, columns=FEATURES_MODELO),
        'y': np.array(etiquetas),
        'fechas': pd.Series(fechas),
        'nubes_par': np.stack(nubes_par) if nubes_par else np.empty((0, 6, 10)),
        'nubes_local': np.stack(nubes_local) if nubes_local else np.empty((0, 10, 6)),
        'nubes_visit': np.stack(nubes_visit) if nubes_visit else np.empty((0, 10, 6)),
        'goles': np.array(goles) if goles else np.empty((0, 2)),
        'meta': meta,  # (local, visitante, estadio, MATCH_ID) por fila
        'estado': estado,
    }


def normalizar_features(X_train: pd.DataFrame, X_val: Optional[pd.DataFrame] = None):
    """MinMax [0,1] ajustado SOLO con entrenamiento (sin fuga temporal)."""
    escalador = MinMaxScaler(feature_range=(0.0, 1.0))
    X_tr = escalador.fit_transform(X_train)
    X_va = escalador.transform(X_val) if X_val is not None else None
    return X_tr, X_va, escalador


# ---------------------------------------------------------------------------
# Agregación inteligente de jugadores -> features de equipo (Bloque 1.3)
# ---------------------------------------------------------------------------
def agregar_jugadores_a_equipo(jugadores: pd.DataFrame) -> Dict[str, float]:
    """
    Condensa los 11 titulares en métricas de equipo + heterogeneidad.
    La tabla individual NO alimenta el modelo; estas agregaciones se exportan
    para interpretación y para los insights de la UI.
    """
    if jugadores.empty:
        return {
            'XG_PLANTEL_SUMA': 0.0, 'XG_PLANTEL_MEDIA': 0.0,
            'PASES_CLAVE_TOTAL': 0.0, 'FATIGA_MEDIA_MIN30D': 0.0,
            'CALIDAD_STD': 0.0, 'DIF_MEJOR_PEOR': 0.0,
            'CONCENTRACION_TALENTO': 0.0, 'REMATES_ARCO_TOTAL': 0.0,
        }
    xg = pd.to_numeric(jugadores.get('XG_INDIVIDUAL_MA5', 0), errors='coerce').fillna(0)
    pases = pd.to_numeric(jugadores.get('PASES_CLAVE_MA5', 0), errors='coerce').fillna(0)
    minutos = pd.to_numeric(jugadores.get('MINUTOS_JUGADOS_30D', 0), errors='coerce').fillna(0)
    remates_arco = pd.to_numeric(jugadores.get('REMATES_ARCO_MA5', 0), errors='coerce').fillna(0)

    calidad = xg + 0.5 * pases  # índice simple de contribución ofensiva
    top3 = calidad.nlargest(3).sum()
    total = calidad.sum()
    return {
        'XG_PLANTEL_SUMA': round(float(xg.sum()), 3),
        'XG_PLANTEL_MEDIA': round(float(xg.mean()), 3),
        'PASES_CLAVE_TOTAL': round(float(pases.sum()), 3),
        'FATIGA_MEDIA_MIN30D': round(float(minutos.mean()), 1),
        'CALIDAD_STD': round(float(calidad.std(ddof=0)), 3),
        'DIF_MEJOR_PEOR': round(float(calidad.max() - calidad.min()), 3),
        'CONCENTRACION_TALENTO': round(float(top3 / total) if total > 0 else 0.0, 3),
        'REMATES_ARCO_TOTAL': round(float(remates_arco.sum()), 3),
    }
