#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Motor multi-liga de clubes (Mejora 5, v12): Liga MX, Premier League, LaLiga.

Reutiliza TODA la maquinaria validada del Mundial:
  * feature_engineering.EstadoRodante (agnóstico a nombres de equipo)
  * ensemble XGB+RF+LGBM calibrado + entropías topológicas (train_tda_model)
  * regresores Poisson de goles y Monte Carlo de marcadores (prediction_api)
  * relleno determinista por MATCH_ID para las métricas ausentes

Datos: football-data.co.uk (resultados REALES; en formato 'main' además
remates/córners/tarjetas REALES y cuotas de cierre). Modelos independientes
por liga en modelos/{liga}/ y estado en team_stats_{liga}.json.

Uso:
    python league_engine.py --build           # descarga+entrena las 3 ligas
    python league_engine.py --build liga_mx   # solo una
"""

import io
import json
import logging
import os
import sys
from typing import Dict, List, Optional, Tuple

import joblib
import numpy as np
import pandas as pd
import requests

import feature_engineering as fe
import features_v26 as f26
import mls_features
import cdi_futbol
import momentum_tactico as mt
import statsbomb_calibration
from config import LEAGUES
from correlated_synthetic_generator import CorrelatedSyntheticGenerator

logger = logging.getLogger(__name__)


def _entropias_ripser(nube) -> np.ndarray:
    """Entropías de persistencia H0/H1 con ripser (mismo cálculo que
    prediction_api._entropias; aquí replicado para no cargar el motor Mundial)."""
    import ripser
    result = ripser.ripser(np.asarray(nube, dtype=float), maxdim=1)
    ents = []
    for dgm in result['dgms']:
        finite = dgm[np.isfinite(dgm[:, 1])]
        if len(finite) == 0:
            ents.append(0.0)
            continue
        vidas = finite[:, 1] - finite[:, 0]
        total = vidas.sum()
        if total == 0:
            ents.append(0.0)
        else:
            p = vidas / total
            ents.append(float(-np.sum(p * np.log(p + 1e-10))))
    return np.array(ents)


class ModeloBetaCalibrado:
    """Ensemble XGB+RF+LGBM SIN isotónica + beta calibration one-vs-rest
    (Kull et al. 2017), calibrada con el último 20 % del train (cronológico).

    v18/M1: adoptada para Serie A — el modelo con cuotas de cierre pasaba de
    49.0 %/1.047 a 53.4 %/1.062 (log-loss fuera de regla); con beta
    calibration queda en 52.2 %/0.998 en walk-forward (VALIDACION_v18.md).
    """

    def __init__(self):
        from train_tda_model import construir_ensemble
        self.ensemble = construir_ensemble().estimator   # VotingClassifier crudo
        self.calibradores = []
        self.classes_ = np.array([0, 1, 2])

    def fit(self, X, y):
        from sklearn.linear_model import LogisticRegression
        X, y = np.asarray(X), np.asarray(y)
        n_cal = max(int(len(X) * 0.2), 150)
        self.ensemble.fit(X[:-n_cal], y[:-n_cal])
        self.classes_ = self.ensemble.classes_
        p_cal = self.ensemble.predict_proba(X[-n_cal:])
        y_cal = y[-n_cal:]
        eps = 1e-6
        self.calibradores = []
        for k_idx, k in enumerate(self.classes_):
            Xc = np.column_stack([
                np.log(np.clip(p_cal[:, k_idx], eps, 1 - eps)),
                -np.log(np.clip(1 - p_cal[:, k_idx], eps, 1 - eps))])
            lr = LogisticRegression(max_iter=1000)
            lr.fit(Xc, (y_cal == k).astype(int))
            self.calibradores.append(lr)
        return self

    def predict_proba(self, X):
        eps = 1e-6
        p = self.ensemble.predict_proba(np.asarray(X))
        out = np.zeros_like(p)
        for k_idx, lr in enumerate(self.calibradores):
            Xt = np.column_stack([
                np.log(np.clip(p[:, k_idx], eps, 1 - eps)),
                -np.log(np.clip(1 - p[:, k_idx], eps, 1 - eps))])
            out[:, k_idx] = lr.predict_proba(Xt)[:, 1]
        out /= out.sum(axis=1, keepdims=True)
        return out

    def predict(self, X):
        return self.classes_[self.predict_proba(X).argmax(axis=1)]


# ---------------------------------------------------------------------------
# Features extra v17 (adoptadas por liga tras walk-forward — VALIDACION_v17)
# ---------------------------------------------------------------------------
COLS_CUOTAS = ['PROB_IMP_H', 'PROB_IMP_D', 'PROB_IMP_A', 'OVERROUND']
COLS_EXTRAS = ['H2H_GD3', 'DIFF_DESCANSO', 'DIFF_RACHA_V', 'DIFF_SIN_PERDER',
               'DIFF_PPG', 'DIFF_POSICION']
COLS_MX = ['ALT_SEDE', 'DIFF_ALT_HABITUAL', 'DIST_VIAJE', 'LIGUILLA', 'APERTURA']

# v19: geografía Liga MX — (altitud msnm, lat, lon) de la sede habitual
GEO_MX = {
    'Toluca': (2660, 19.29, -99.67), 'Pachuca': (2432, 20.10, -98.75),
    'Club America': (2240, 19.30, -99.15), 'America': (2240, 19.30, -99.15),
    'Cruz Azul': (2240, 19.30, -99.15), 'U.N.A.M.- Pumas': (2240, 19.31, -99.19),
    'Pumas UNAM': (2240, 19.31, -99.19), 'Puebla': (2135, 19.08, -98.16),
    'Necaxa': (1888, 21.89, -102.31), 'Queretaro': (1820, 20.55, -100.44),
    'Leon': (1815, 21.11, -101.66), 'Atl. San Luis': (1860, 22.15, -100.98),
    'Guadalajara Chivas': (1566, 20.68, -103.46), 'Guadalajara': (1566, 20.68, -103.46),
    'Atlas': (1566, 20.70, -103.34), 'Club Tijuana': (20, 32.50, -116.99),
    'Tijuana': (20, 32.50, -116.99), 'Mazatlan FC': (10, 23.26, -106.40),
    'Mazatlan': (10, 23.26, -106.40), 'Monterrey': (540, 25.67, -100.24),
    'Tigres UANL': (540, 25.72, -100.31), 'Tigres': (540, 25.72, -100.31),
    'Santos Laguna': (1120, 25.58, -103.42), 'FC Juarez': (1140, 31.72, -106.42),
    'Juarez': (1140, 31.72, -106.42), 'Veracruz': (10, 19.15, -96.11),
    'Lobos BUAP': (2135, 19.02, -98.24), 'Morelia': (1920, 19.71, -101.17),
    'Atlante': (1600, 21.16, -86.85),
}


def _haversine_km(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dp, dl = np.radians(lat2 - lat1), np.radians(lon2 - lon1)
    a = np.sin(dp / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return float(2 * 6371.0 * np.arcsin(np.sqrt(a)))


def _fila_mx(home: str, away: str, fecha) -> dict:
    """Features específicas de Liga MX para un partido (v19, walk-forward
    +1.0 pp junto con cuotas y beta calibration)."""
    gh = GEO_MX.get(home, (1200, 23.0, -102.0))
    ga = GEO_MX.get(away, (1200, 23.0, -102.0))
    mes, dia = fecha.month, fecha.day
    return {
        'ALT_SEDE': gh[0] / 2700.0,
        'DIFF_ALT_HABITUAL': (gh[0] - ga[0]) / 2700.0,
        'DIST_VIAJE': _haversine_km(gh[1], gh[2], ga[1], ga[2]) / 2500.0,
        'LIGUILLA': 1.0 if (mes == 5 or mes == 12 or (mes == 11 and dia >= 20)) else 0.0,
        'APERTURA': 1.0 if mes >= 7 else 0.0,
    }


def features_mx(df: pd.DataFrame) -> pd.DataFrame:
    filas = [{'MATCH_ID': f.MATCH_ID, **_fila_mx(f.home_team, f.away_team, f.date)}
             for f in df.itertuples(index=False)]
    return pd.DataFrame(filas).set_index('MATCH_ID')


def columnas_extra(clave: str) -> list:
    """Columnas extra configuradas para la liga, en orden de entrenamiento."""
    grupos = LEAGUES.get(clave, {}).get('features_extra', [])
    cols = []
    if 'extras' in grupos:
        cols += COLS_EXTRAS
    if 'cuotas' in grupos:
        cols += COLS_CUOTAS
    if 'mx' in grupos:
        cols += COLS_MX
    if 'imt' in grupos:
        cols += mt.COLS_IMT
    if 'imt_c' in grupos:          # v24: variante de índice compuesto
        cols += mt.COLS_IMT_C
    if 'mls_geo' in grupos:        # v25: geografía continental MLS
        cols += mls_features.COLS_MLS_GEO
    if 'mls_clima' in grupos:      # v25: clima extremo MLS
        cols += mls_features.COLS_MLS_CLIMA
    if 'ent' in grupos:            # v26: entropía táctica y volatilidad
        cols += f26.COLS_ENT
    if 'elo_d' in grupos:          # v26: derivadas del ELO
        cols += f26.COLS_ELO_D
    if 'urg' in grupos:            # v26: urgencia asimétrica
        cols += f26.COLS_URG
    if 'cdi' in grupos:            # v35: desincronización circadiana
        cols += cdi_futbol.COLS_CDI
    return cols


def features_extra_liga(df: pd.DataFrame):
    """Features extra por MATCH_ID en un pase cronológico SIN fuga, más el
    estado FINAL por equipo/pareja para reproducirlas en inferencia."""
    ultima_fecha, racha_v, racha_sp = {}, {}, {}
    h2h_gd = {}
    pts, pj = {}, {}
    temporada_actual = None

    filas = []
    for f in df.itertuples(index=False):
        h, a, fecha = f.home_team, f.away_team, f.date
        temp = fecha.year if fecha.month >= 7 else fecha.year - 1
        if temp != temporada_actual:
            temporada_actual = temp
            pts, pj = {}, {}

        desc_h = min((fecha - ultima_fecha[h]).days, 21) if h in ultima_fecha else 21
        desc_a = min((fecha - ultima_fecha[a]).days, 21) if a in ultima_fecha else 21
        clave_par = tuple(sorted((h, a)))
        prev = h2h_gd.get(clave_par, [])[-3:]
        gd3 = float(np.mean([gd if ref == h else -gd for ref, gd in prev])) if prev else 0.0
        ppg_h = pts.get(h, 0) / pj[h] if pj.get(h) else 1.3
        ppg_a = pts.get(a, 0) / pj[a] if pj.get(a) else 1.3
        tabla = sorted(pts, key=lambda e: -pts[e])
        pos_h = tabla.index(h) + 1 if h in tabla else len(tabla) // 2 + 1
        pos_a = tabla.index(a) + 1 if a in tabla else len(tabla) // 2 + 1

        fila = {
            'MATCH_ID': f.MATCH_ID,
            'H2H_GD3': float(np.clip(gd3, -3, 3)) / 3.0,
            'DIFF_DESCANSO': (desc_h - desc_a) / 21.0,
            'DIFF_RACHA_V': (racha_v.get(h, 0) - racha_v.get(a, 0)) / 5.0,
            'DIFF_SIN_PERDER': (racha_sp.get(h, 0) - racha_sp.get(a, 0)) / 10.0,
            'DIFF_PPG': (ppg_h - ppg_a) / 3.0,
            'DIFF_POSICION': (pos_a - pos_h) / 20.0,
        }
        oh, od, oa = getattr(f, 'odd_home', None), getattr(f, 'odd_draw', None), \
            getattr(f, 'odd_away', None)
        if oh and od and oa and oh > 1 and od > 1 and oa > 1:
            inv = np.array([1 / oh, 1 / od, 1 / oa])
            imp = inv / inv.sum()
            fila.update({'PROB_IMP_H': imp[0], 'PROB_IMP_D': imp[1],
                         'PROB_IMP_A': imp[2], 'OVERROUND': float(inv.sum() - 1)})
        else:
            fila.update({c: np.nan for c in COLS_CUOTAS})
        filas.append(fila)

        gh, ga = float(f.home_goals), float(f.away_goals)
        ultima_fecha[h] = ultima_fecha[a] = fecha
        for eq, propios, rival in ((h, gh, ga), (a, ga, gh)):
            racha_v[eq] = racha_v.get(eq, 0) + 1 if propios > rival else 0
            racha_sp[eq] = racha_sp.get(eq, 0) + 1 if propios >= rival else 0
            pj[eq] = pj.get(eq, 0) + 1
            pts[eq] = pts.get(eq, 0) + (3 if propios > rival else (1 if propios == rival else 0))
        h2h_gd.setdefault(clave_par, []).append((h, gh - ga))

    # --- estado final para inferencia ---
    tabla = sorted(pts, key=lambda e: -pts[e])
    equipos = sorted(set(df['home_team']) | set(df['away_team']))
    estado = {'equipos': {}, 'parejas': {}}
    for eq in equipos:
        estado['equipos'][eq] = {
            'ultima_fecha': ultima_fecha[eq].strftime('%Y-%m-%d') if eq in ultima_fecha else None,
            'racha_v': int(racha_v.get(eq, 0)), 'racha_sp': int(racha_sp.get(eq, 0)),
            'ppg': round(pts.get(eq, 0) / pj[eq], 4) if pj.get(eq) else 1.3,
            'pos': tabla.index(eq) + 1 if eq in tabla else len(tabla) // 2 + 1,
        }
    for par, historial in h2h_gd.items():
        prev = historial[-3:]
        ref = par[0]   # perspectiva del primero en orden alfabético
        gd3 = float(np.mean([gd if r == ref else -gd for r, gd in prev]))
        estado['parejas'][f'{par[0]}|{par[1]}'] = round(gd3, 3)
    return pd.DataFrame(filas).set_index('MATCH_ID'), estado


def _match_id(fecha: pd.Timestamp, home: str, away: str) -> str:
    h = str(home).replace(' ', '-')
    a = str(away).replace(' ', '-')
    return f"{fecha.strftime('%Y%m%d')}_{h}_{a}"


# ---------------------------------------------------------------------------
# Descarga y normalización al esquema del histórico
# ---------------------------------------------------------------------------
def _descargar_api_football(clave: str, cfg: Dict) -> pd.DataFrame:
    """v21: histórico desde API-Football (Champions). 1 request por temporada
    (cacheado de forma permanente por el gateway). Sin clave ni crédito, cae
    al último historico_{clave}.csv guardado para no romper el build."""
    import api_football_manager as afm
    filas = []
    for season in cfg['api_seasons']:
        data = afm.api_call('fixtures',
                            {'league': cfg['api_league_id'], 'season': season},
                            prioridad=3, ttl=None)
        if not data or not data.get('response'):
            logger.warning(f"[{clave}] API-Football sin datos para {season} "
                           f"({(data or {}).get('errors')})")
            continue
        for p in data['response']:
            if p['fixture']['status']['short'] not in ('FT', 'AET', 'PEN'):
                continue
            # score de los 90' (fulltime): el empate se conserva para el 1X2
            ft = p['score']['fulltime']
            if ft['home'] is None:
                continue
            filas.append({
                'date': pd.to_datetime(p['fixture']['date']).tz_localize(None),
                'home_team': p['teams']['home']['name'],
                'away_team': p['teams']['away']['name'],
                'home_goals': float(ft['home']), 'away_goals': float(ft['away']),
                'api_fixture_id': p['fixture']['id'],
                'api_home_id': p['teams']['home']['id'],
                'api_away_id': p['teams']['away']['id'],
            })
    if not filas:
        ruta = f'historico_{clave}.csv'
        if os.path.exists(ruta):
            logger.warning(f"[{clave}] sin acceso a API-Football: se reutiliza {ruta}.")
            df = pd.read_csv(ruta, parse_dates=['date'])
            return df[['date', 'home_team', 'away_team', 'home_goals', 'away_goals']
                      + [c for c in ('api_fixture_id', 'api_home_id', 'api_away_id')
                         if c in df.columns]]
        raise RuntimeError(f"{clave}: API-Football no disponible y no hay CSV previo.")
    df = pd.DataFrame(filas)
    # Nombre canónico por ID de equipo: la API renombra clubes entre
    # temporadas (p. ej. 'Bayern Munich' 2022 → 'Bayern München' 2024) y eso
    # partiría su historial. Se usa el nombre MÁS RECIENTE de cada id.
    df = df.sort_values('date')
    nombre_por_id = {}
    for lado in ('home', 'away'):
        for tid, nombre in zip(df[f'api_{lado}_id'], df[f'{lado}_team']):
            nombre_por_id[tid] = nombre          # el último (más reciente) gana
    df['home_team'] = df['api_home_id'].map(nombre_por_id)
    df['away_team'] = df['api_away_id'].map(nombre_por_id)
    df['odd_home'] = np.nan
    df['odd_draw'] = np.nan
    df['odd_away'] = np.nan
    return df


def _fusionar_fbref_champions(df_api: pd.DataFrame) -> pd.DataFrame:
    """v22: amplía la Champions con los resultados de FBref (2017-presente,
    incluida la temporada en curso que el plan Free de API-Football bloquea).

    - Los nombres FBref se traducen a los canónicos de API-Football con un
      mapeo APRENDIDO del solape 2022-23 (unión por fecha+marcador cuando el
      candidato es único) + fuzzy 0.85 de respaldo; los clubes que solo
      existen en FBref conservan su nombre.
    - Se excluyen los partidos con prórroga/penales de FBref (su calendario
      no publica el marcador de los 90'; ~8 partidos).
    - Solo se añaden fechas FUERA de la cobertura de API-Football (que tiene
      marcadores de 90' exactos y por eso manda en su rango).
    """
    from collections import Counter, defaultdict
    from difflib import SequenceMatcher
    try:
        import fbref_scraper_v3 as fb3
        df_fb = fb3.resultados_champions()
    except Exception as e:
        logger.warning(f"[champions] FBref no disponible ({e}): solo API-Football.")
        return df_api
    if df_fb.empty:
        return df_api

    # Alias verificados a mano FBref -> API (el solape 2022-23 solo enseña a
    # quienes jugaron ESA temporada y el fuzzy 0.85 no llega a estos).
    # OJO con falsos amigos que NO se fusionan: Rīga FC ≠ Rīgas FS,
    # Kauno Žalgiris ≠ FK Zalgiris Vilnius, Tre Fiori ≠ Tre Penne,
    # FK Partizan ≠ Partizani, Atlètic ≠ Inter Club d'Escaldes.
    ALIAS_FBREF_API = {
        'Manchester Utd': 'Manchester United',
        'Olympiacos': 'Olympiakos Piraeus',
        'Qarabağ': 'Qarabag',
        'PSV': 'PSV Eindhoven',
        'Slavia Prague': 'Slavia Praha',
        'Red Star': 'FK Crvena Zvezda',
        'Young Boys': 'BSC Young Boys',
        'Bodø/Glimt': 'Bodo/Glimt',
        'APOEL FC': 'Apoel Nicosia',
        'NK Maribor': 'Maribor',
        'AEK Athens': 'AEK Athens FC',
        'Ferencváros': 'Ferencvarosi TC',
        'Midtjylland': 'FC Midtjylland',
        'Malmö': 'Malmo FF',
        'Union SG': 'Union St. Gilloise',
        'Larne FC': 'Larne',
        'Shamrock': 'Shamrock Rovers',
        'Lincoln FC': 'Lincoln Red Imps FC',
        "Inter d'Escaldes": "Inter Club d'Escaldes",
        'FC Flora': 'Flora Tallinn',
        'KÍ Klaksvík': 'KI Klaksvik',
        'FK Egnatia': 'Egnatia Rrogozhinë',
        'Sutjeska Nikšić': 'Sutjeska',
        'B. Banja Luka': 'Borac Banja Luka',
    }

    indice_api = defaultdict(list)
    for r in df_api.itertuples():
        indice_api[(r.date.date(), r.home_goals, r.away_goals)].append(r)
    votos = defaultdict(Counter)
    for r in df_fb.itertuples():
        cands = indice_api.get((r.date.date(), r.home_goals, r.away_goals), [])
        if len(cands) == 1:
            votos[r.home_team][cands[0].home_team] += 1
            votos[r.away_team][cands[0].away_team] += 1
    mapa = {fb: c.most_common(1)[0][0] for fb, c in votos.items()}
    mapa.update(ALIAS_FBREF_API)          # los alias verificados mandan
    nombres_api = sorted(set(df_api['home_team']) | set(df_api['away_team']))
    for nombre in sorted(set(df_fb['home_team']) | set(df_fb['away_team'])):
        if nombre in mapa:
            continue
        mejor, ratio = None, 0.0
        for n in nombres_api:
            s = SequenceMatcher(None, nombre.lower(), n.lower()).ratio()
            if s > ratio:
                mejor, ratio = n, s
        if ratio >= 0.85:
            mapa[nombre] = mejor
    df_fb = df_fb.copy()
    df_fb['home_team'] = df_fb['home_team'].map(lambda n: mapa.get(n, n))
    df_fb['away_team'] = df_fb['away_team'].map(lambda n: mapa.get(n, n))

    df_fb = df_fb[~df_fb['prorroga']]
    api_min, api_max = df_api['date'].min(), df_api['date'].max()
    df_fb = df_fb[(df_fb['date'] < api_min) | (df_fb['date'] > api_max)]
    columnas = ['date', 'home_team', 'away_team', 'home_goals', 'away_goals']
    fusion = pd.concat([df_api, df_fb[columnas]], ignore_index=True)
    logger.info(f"[champions] fusión FBref: +{len(df_fb)} partidos "
                f"({len(mapa)} nombres mapeados) → {len(fusion)} totales.")
    return fusion


def descargar_liga(clave: str) -> pd.DataFrame:
    cfg = LEAGUES[clave]
    if cfg['formato'] == 'api_football':
        df = _descargar_api_football(clave, cfg)
        if clave == 'champions':
            df = _fusionar_fbref_champions(df)
        if cfg.get('desde'):        # profundidad validada en walk-forward
            df = df[df['date'] >= pd.Timestamp(cfg['desde'])]
        crudo = None
    elif cfg['formato'] == 'espn':
        # v35 (§2): Europa League / Conference League desde el JSON de ESPN
        # con cadena de resiliencia (ESPN → API-Football → CSV local).
        import uefa_scraper
        df = uefa_scraper.historico_uefa(clave, cfg['espn_liga'], cfg['desde'],
                                         cfg.get('api_league_id'))
        df = df[df['date'] >= pd.Timestamp(cfg['desde'])].copy()
        for c in ('odd_home', 'odd_draw', 'odd_away'):
            df[c] = np.nan
        crudo = None
    else:
        frames = []
        for url in cfg['urls']:
            r = requests.get(url, timeout=30)
            r.raise_for_status()
            frames.append(pd.read_csv(io.StringIO(r.text), on_bad_lines='skip',
                                      encoding_errors='ignore'))
        crudo = pd.concat(frames, ignore_index=True)

    if cfg['formato'] in ('api_football', 'espn'):
        pass                                   # df ya construido arriba
    elif cfg['formato'] == 'main':
        df = pd.DataFrame({
            'date': pd.to_datetime(crudo['Date'], dayfirst=True, errors='coerce'),
            'home_team': crudo['HomeTeam'], 'away_team': crudo['AwayTeam'],
            'home_goals': pd.to_numeric(crudo['FTHG'], errors='coerce'),
            'away_goals': pd.to_numeric(crudo['FTAG'], errors='coerce'),
            'home_shots_on': pd.to_numeric(crudo.get('HST'), errors='coerce'),
            'away_shots_on': pd.to_numeric(crudo.get('AST'), errors='coerce'),
            'home_shots_off': pd.to_numeric(crudo.get('HS'), errors='coerce') -
                              pd.to_numeric(crudo.get('HST'), errors='coerce'),
            'away_shots_off': pd.to_numeric(crudo.get('AS'), errors='coerce') -
                              pd.to_numeric(crudo.get('AST'), errors='coerce'),
            'home_corners': pd.to_numeric(crudo.get('HC'), errors='coerce'),
            'away_corners': pd.to_numeric(crudo.get('AC'), errors='coerce'),
            'home_yellow': pd.to_numeric(crudo.get('HY'), errors='coerce'),
            'away_yellow': pd.to_numeric(crudo.get('AY'), errors='coerce'),
            'home_red': pd.to_numeric(crudo.get('HR'), errors='coerce'),
            'away_red': pd.to_numeric(crudo.get('AR'), errors='coerce'),
            'odd_home': pd.to_numeric(crudo.get('B365H'), errors='coerce'),
            'odd_draw': pd.to_numeric(crudo.get('B365D'), errors='coerce'),
            'odd_away': pd.to_numeric(crudo.get('B365A'), errors='coerce'),
            # v26: cierre de PINNACLE (PSC*) para CLV/Shadow — la casa más
            # eficiente; con respaldo PS* (apertura Pinnacle) si falta
            'odd_home_pin': pd.to_numeric(crudo.get('PSCH'), errors='coerce')
                              .fillna(pd.to_numeric(crudo.get('PSH'), errors='coerce')),
            'odd_draw_pin': pd.to_numeric(crudo.get('PSCD'), errors='coerce')
                              .fillna(pd.to_numeric(crudo.get('PSD'), errors='coerce')),
            'odd_away_pin': pd.to_numeric(crudo.get('PSCA'), errors='coerce')
                              .fillna(pd.to_numeric(crudo.get('PSA'), errors='coerce')),
            'referee': crudo.get('Referee'),
        })
    else:  # 'new': goles + cuotas de CIERRE (v18: AvgC* tiene 100 % de
        # cobertura en MEX.csv; AvgH/PH de apertura no existen en este formato)
        def _odds(*cols):
            serie = None
            for c in cols:
                s = pd.to_numeric(crudo.get(c), errors='coerce') \
                    if c in crudo.columns else None
                serie = s if serie is None else serie.fillna(s)
            return serie
        df = pd.DataFrame({
            'date': pd.to_datetime(crudo['Date'], dayfirst=True, errors='coerce'),
            'home_team': crudo['Home'], 'away_team': crudo['Away'],
            'home_goals': pd.to_numeric(crudo['HG'], errors='coerce'),
            'away_goals': pd.to_numeric(crudo['AG'], errors='coerce'),
            'odd_home': _odds('AvgCH', 'PSCH', 'B365CH', 'AvgH', 'PH'),
            'odd_draw': _odds('AvgCD', 'PSCD', 'B365CD', 'AvgD', 'PD'),
            'odd_away': _odds('AvgCA', 'PSCA', 'B365CA', 'AvgA', 'PA'),
            # v26: cierre Pinnacle puro (CLV/Shadow)
            'odd_home_pin': _odds('PSCH'),
            'odd_draw_pin': _odds('PSCD'),
            'odd_away_pin': _odds('PSCA'),
        })
        # Liga MX: ventana configurable de temporadas (v13: 8 años)
        anios = cfg.get('anios_ventana', 4)
        df = df[df['date'] >= df['date'].max() - pd.DateOffset(years=anios)]

    df = df.dropna(subset=['date', 'home_team', 'away_team', 'home_goals', 'away_goals'])
    df['tournament'] = cfg['nombre']
    df['stadium'] = None
    df['MATCH_ID'] = [
        _match_id(f, h, a) for f, h, a in zip(df['date'], df['home_team'], df['away_team'])]
    df = df.drop_duplicates(subset='MATCH_ID', keep='last')
    df = df.sort_values(['date', 'MATCH_ID'], kind='mergesort').reset_index(drop=True)

    # ELO por liga + relleno determinista de lo que falte (xG siempre; en
    # formato 'new' también remates/córners/tarjetas) — mismo método auditado
    df['elo_diff'] = _elo_diff_liga(df)

    # v14/M8: el xG real de Understat se evaluó como feature y EMPEORÓ el
    # log-loss en LaLiga (1.014→1.108) y Premier (también la precisión):
    # el relleno sintético condicionado a goles reales lleva más señal.
    # understat_scraper.inyectar_xg queda disponible pero DESACTIVADO
    # (ver VALIDACION_v14.md).
    cal = statsbomb_calibration.calibrar()
    gen = CorrelatedSyntheticGenerator()
    df = gen.generate_advanced_metrics(df, cal)
    logger.info(f"[{clave}] {len(df)} partidos reales "
                f"({df['date'].min().date()} → {df['date'].max().date()}), "
                f"cuotas de cierre en {df['odd_home'].notna().mean()*100:.0f} % de filas.")
    return df


def _elo_diff_liga(df: pd.DataFrame) -> pd.Series:
    """ELO cronológico local a la liga (sin tocar elo_actual.csv del Mundial)."""
    elo: Dict[str, float] = {}
    diffs = np.zeros(len(df))
    for i, fila in enumerate(df.itertuples(index=False)):
        h, a = fila.home_team, fila.away_team
        r_h, r_a = elo.get(h, 1500.0), elo.get(a, 1500.0)
        diffs[i] = r_h - r_a
        e_h = 1 / (1 + 10 ** ((r_a - r_h) / 400))
        s_h = 1.0 if fila.home_goals > fila.away_goals else (0.5 if fila.home_goals == fila.away_goals else 0.0)
        elo[h] = r_h + 24 * (s_h - e_h)
        elo[a] = r_a + 24 * ((1 - s_h) - (1 - e_h))
    return pd.Series(diffs, index=df.index)


# ---------------------------------------------------------------------------
# Entrenamiento por liga (mismo pipeline validado del Mundial)
# ---------------------------------------------------------------------------
def entrenar_liga(clave: str, con_ratings: bool = False) -> Dict:
    """Entrena el modelo de una liga.

    con_ratings (v14/M9, experimental): añade VAL_LOG_RATIO (log del cociente
    de valores de plantilla Transfermarkt) como feature y NO guarda artefactos
    — es solo para el A/B de backtesting. ADVERTENCIA: los valores son los
    actuales, así que el backtest con ratings tiene sesgo de anticipación.
    """
    from train_tda_model import construir_ensemble, calcular_features_topologicas
    from sklearn.ensemble import HistGradientBoostingRegressor
    from sklearn.metrics import accuracy_score, log_loss

    df = descargar_liga(clave)
    if not con_ratings:
        df.to_csv(f'historico_{clave}.csv', index=False)

    ds = fe.construir_dataset_supervisado(df)
    X_df, y, fechas = ds['X_df'], ds['y'], ds['fechas']
    if len(X_df) < 300:
        raise RuntimeError(f"{clave}: solo {len(X_df)} partidos utilizables.")

    if con_ratings:
        import transfermarkt_scraper as tm
        vals = tm.mapear_a_football_data(
            tm.valores_liga(clave),
            sorted(set(df['home_team']) | set(df['away_team'])))
        if not vals:
            raise RuntimeError(f"{clave}: Transfermarkt sin datos; A/B cancelado.")
        mediana = float(np.median(list(vals.values())))
        X_df = X_df.copy()
        X_df['VAL_LOG_RATIO'] = [
            np.log(max(vals.get(m[0], mediana), 1e-6) /
                   max(vals.get(m[1], mediana), 1e-6))
            for m in ds['meta']]
        logger.info(f"[{clave}] A/B ratings: {len(vals)} equipos con valor de "
                    f"plantilla (mediana €{mediana:.0f}M).")

    topo = calcular_features_topologicas(ds)

    # v17: features extra adoptadas por liga tras walk-forward (VALIDACION_v17)
    cols_extra = columnas_extra(clave)
    estado_extra = None
    estado_imt = None
    estado_v26 = None
    mapa_tz = None
    imt_coef = None
    medias_cuotas = {}
    if cols_extra:
        grupos = LEAGUES[clave].get('features_extra', [])
        extras_df, estado_extra = features_extra_liga(df)
        if 'mx' in grupos:
            extras_df = extras_df.join(features_mx(df))
        # v24: Índice de Momentum Táctico (walk-forward por liga en
        # run_wf_imt_v24.py; solo las ligas donde superó la regla de oro
        # llevan 'imt' — componentes — o 'imt_c' — índice compuesto con
        # α,β,γ,δ ajustados en train-only — en features_extra)
        if 'imt' in grupos or 'imt_c' in grupos:
            imt_df, estado_imt = mt.features_imt(df)
            if 'imt_c' in grupos:
                imt_coef = mt.optimizar_coeficientes(
                    df, imt_df, hasta_fecha=fechas.quantile(0.80))['coef']
                imt_df = imt_df.join(mt.indice_compuesto(imt_df, imt_coef))
            extras_df = extras_df.join(imt_df)
        # v25: geografía + clima extremo MLS (walk-forward run_wf_mls_v25.py)
        if any(g.startswith('mls_') for g in grupos):
            extras_df = extras_df.join(mls_features.features_mls(df))
        # v26: features ortogonales (walk-forward run_wf_feats_v26.py)
        if any(g in grupos for g in ('ent', 'elo_d', 'urg')):
            v26_df, estado_v26 = f26.features_v26(df)
            extras_df = extras_df.join(v26_df)
        # v35 (§3): CDI — solo en las competiciones donde el walk-forward lo
        # adoptó (run_wf_v35.py). El mapa club→huso se guarda en team_stats
        # para poder reproducir la feature en inferencia.
        if 'cdi' in grupos:
            mapa_tz = cdi_futbol.mapa_tz_liga(clave, df)
            extras_df = extras_df.join(cdi_futbol.features_cdi(df, mapa_tz))
            cdi_futbol.guardar_mapa({clave: mapa_tz})
        ids = [m[3] for m in ds['meta']]
        ext = extras_df.reindex(ids).reset_index(drop=True)
        X_df = X_df.reset_index(drop=True).copy()
        for c in cols_extra:
            X_df[c] = ext[c].values

    corte = fechas.quantile(0.80)
    m_tr = (fechas < corte).values
    m_va = ~m_tr
    if cols_extra:
        # cuotas ausentes -> media del TRAIN (misma imputación en inferencia);
        # el resto de extras ausentes -> 0 (neutro)
        for c in cols_extra:
            if c in COLS_CUOTAS:
                media = float(pd.to_numeric(X_df.loc[m_tr, c], errors='coerce').mean())
                medias_cuotas[c] = round(media, 4)
                X_df[c] = X_df[c].fillna(media)
            else:
                X_df[c] = X_df[c].fillna(0.0)
    X_tr_n, X_va_n, escalador = fe.normalizar_features(X_df[m_tr], X_df[m_va])
    X_tr = np.hstack([X_tr_n, topo[m_tr]])
    X_va = np.hstack([X_va_n, topo[m_va]])

    # v18: calibración configurable por liga (Serie A usa beta calibration).
    # La clase se toma del módulo IMPORTADO para que el pickle guarde
    # 'league_engine.ModeloBetaCalibrado' aunque este archivo corra como
    # __main__ (si no, ClubEngine no podría deserializarlo).
    if LEAGUES[clave].get('calibracion') == 'beta':
        import league_engine as _le
        modelo = _le.ModeloBetaCalibrado()
    else:
        modelo = construir_ensemble()
    modelo.fit(X_tr, y[m_tr])
    proba = modelo.predict_proba(X_va)
    acc = accuracy_score(y[m_va], proba.argmax(axis=1))
    ll = log_loss(y[m_va], proba, labels=[0, 1, 2])
    base = accuracy_score(y[m_va], np.where(X_df[m_va]['DIFF_ELO'].values > 0, 0, 2))

    # Línea base del MERCADO (cuotas de cierre reales): referencia honesta
    acc_mercado = None
    ids_val = [m[3] for m, keep in zip(ds['meta'], m_va) if keep]
    odds = df.set_index('MATCH_ID')[['odd_home', 'odd_draw', 'odd_away']]
    disponibles = odds.reindex(ids_val).dropna()
    if len(disponibles) > 50:
        pick = disponibles.values.argmin(axis=1)   # cuota mínima = favorito
        reales = pd.Series(y[m_va], index=ids_val).loc[disponibles.index].values
        acc_mercado = float((pick == reales).mean())

    # v20/M3-M4: simulación de apuestas sobre la validación con cuotas de
    # cierre reales — apuesta 1 u al pick del modelo si conf>70 % o EV>0.
    # Se persisten las apuestas para el panel de ROI y el simulador de banca.
    roi_sim = None
    if len(disponibles) > 50:
        fechas_val = pd.Series([f for f, keep in zip(fechas, m_tr) if not keep],
                               index=ids_val)
        proba_val = pd.DataFrame(proba, index=ids_val)
        # v26 (§3.1): mismas apuestas valoradas también con el cierre de
        # PINNACLE (la casa más eficiente) — el edge contra Pinnacle es la
        # medida realista del CLV.
        odds_pin = None
        if {'odd_home_pin', 'odd_draw_pin', 'odd_away_pin'} <= set(df.columns):
            odds_pin = df.set_index('MATCH_ID')[
                ['odd_home_pin', 'odd_draw_pin', 'odd_away_pin']].reindex(ids_val)
        apuestas = []
        for mid in disponibles.index:
            p = proba_val.loc[mid].values
            k = int(p.argmax())
            cuota = float(disponibles.loc[mid].values[k])
            ev = cuota * float(p[k]) - 1.0
            if p[k] <= 0.70 and ev <= 0:
                continue
            gano = int(k == int(pd.Series(y[m_va], index=ids_val).loc[mid]))
            fila_bet = {'fecha': str(pd.Timestamp(fechas_val.loc[mid]).date()),
                        'prob': round(float(p[k]), 4), 'cuota': round(cuota, 3),
                        'ev': round(ev, 4), 'gano': gano}
            if odds_pin is not None and mid in odds_pin.index:
                cp = odds_pin.loc[mid].values[k]
                if pd.notna(cp) and cp > 1:
                    fila_bet['cuota_pin'] = round(float(cp), 3)
            apuestas.append(fila_bet)
        if apuestas:
            ganancia = sum(a['gano'] * (a['cuota'] - 1) - (1 - a['gano']) for a in apuestas)
            roi_sim = {'n_apuestas': len(apuestas),
                       'roi_pct': round(100 * ganancia / len(apuestas), 2),
                       'aciertos': int(sum(a['gano'] for a in apuestas))}
            con_pin = [a for a in apuestas if 'cuota_pin' in a]
            if len(con_pin) >= 30:
                gan_pin = sum(a['gano'] * (a['cuota_pin'] - 1) - (1 - a['gano'])
                              for a in con_pin)
                roi_sim['roi_pct_pinnacle'] = round(100 * gan_pin / len(con_pin), 2)
                roi_sim['n_con_pinnacle'] = len(con_pin)
            with open(f'roi_bets_{clave}.json', 'w', encoding='utf-8') as f:
                json.dump(sorted(apuestas, key=lambda a: a['fecha']), f)

    # ------------------------------------------------------------------
    # v23 (MESM): meta-ensemble de superación de mercado. Protocolo SIN
    # fuga: un modelo con la MISMA config de la liga se entrena con el
    # primer 75 % del train y sus probs out-of-sample (25 % final) ajustan
    # el meta con pesos asimétricos; se valida aplicándolo a las probs del
    # modelo de PRODUCCIÓN sobre la validación (solo filas con cuotas).
    # El artefacto mesm.joblib solo se escribe si supera la regla de oro.
    # ------------------------------------------------------------------
    mesm_info = None
    try:
        import meta_ensemble as me
        ids_all = [m[3] for m in ds['meta']]
        mkt_all = me.probs_mercado(odds.reindex(ids_all))
        idx_tr = np.where(m_tr)[0]
        corte75 = int(len(idx_tr) * 0.75)
        idx_fit, idx_meta = idx_tr[:corte75], idx_tr[corte75:]
        ok_meta = np.isfinite(mkt_all[idx_meta]).all(axis=1)
        idx_va = np.where(m_va)[0]
        ok_va = np.isfinite(mkt_all[idx_va]).all(axis=1)
        if ok_meta.sum() >= 100 and ok_va.sum() >= 50:
            Xf_n, Xm_n, _ = fe.normalizar_features(X_df.iloc[idx_fit],
                                                   X_df.iloc[idx_meta])
            if LEAGUES[clave].get('calibracion') == 'beta':
                import league_engine as _le
                base75 = _le.ModeloBetaCalibrado()
            else:
                base75 = construir_ensemble()
            base75.fit(np.hstack([Xf_n, topo[idx_fit]]), y[idx_fit])

            def _probs3(mod, Xn, t):
                pr = mod.predict_proba(np.hstack([Xn, t]))
                p = np.zeros((len(Xn), 3))
                for k_idx, k in enumerate(mod.classes_):
                    p[:, int(k)] = pr[:, k_idx]
                return p / p.sum(axis=1, keepdims=True)

            p_meta = _probs3(base75, Xm_n[ok_meta], topo[idx_meta][ok_meta])
            meta = me.MetaEnsemble().fit(y[idx_meta][ok_meta], p_meta,
                                         mkt_all[idx_meta][ok_meta])
            # validación con las probs de PRODUCCIÓN (mismas filas con cuotas)
            p_prod = proba[ok_va]
            p_mesm = meta.predict_proba(p_prod, mkt_all[idx_va][ok_va])
            y_sub = y[m_va][ok_va]
            acc_sub = accuracy_score(y_sub, p_prod.argmax(axis=1))
            ll_sub = log_loss(y_sub, p_prod, labels=[0, 1, 2])
            acc_mesm = accuracy_score(y_sub, p_mesm.argmax(axis=1))
            ll_mesm = log_loss(y_sub, p_mesm, labels=[0, 1, 2])
            golden = bool((acc_mesm - acc_sub >= 0.003 and ll_mesm - ll_sub <= 0.01)
                          or (acc_mesm > acc_sub and ll_mesm < ll_sub))
            mesm_info = {
                'n_val_con_cuotas': int(ok_va.sum()),
                'acc_prod': round(float(acc_sub), 4),
                'acc_mesm': round(float(acc_mesm), 4),
                'll_prod': round(float(ll_sub), 4),
                'll_mesm': round(float(ll_mesm), 4),
                'adoptado': golden,
            }
            logger.info(f"[{clave}] MESM: prod {acc_sub:.3f}/{ll_sub:.3f} → "
                        f"mesm {acc_mesm:.3f}/{ll_mesm:.3f} · "
                        f"{'ADOPTADO' if golden else 'descartado'}")
            if golden and not con_ratings:
                carpeta_mesm = os.path.join('modelos', clave)
                os.makedirs(carpeta_mesm, exist_ok=True)
                joblib.dump(meta, os.path.join(carpeta_mesm, 'mesm.joblib'),
                            compress=3)
            elif not golden:
                ruta_vieja = os.path.join('modelos', clave, 'mesm.joblib')
                if os.path.exists(ruta_vieja) and not con_ratings:
                    os.remove(ruta_vieja)
    except Exception as e:
        logger.warning(f"[{clave}] MESM omitido: {type(e).__name__}: {e}")

    if con_ratings:   # A/B experimental: solo métricas, sin artefactos
        resultado = {
            'liga': LEAGUES[clave]['nombre'], 'experimento': 'ratings_transfermarkt',
            'precision_validacion': round(float(acc), 4),
            'precision_linea_base_elo': round(float(base), 4),
            'precision_mercado_cuotas': round(acc_mercado, 4) if acc_mercado else None,
            'log_loss_validacion': round(float(ll), 4),
        }
        logger.info(f"[{clave}] A/B RATINGS: acc={acc:.3f} logloss={ll:.3f} "
                    f"(sin guardar artefactos).")
        return resultado

    reg_l = HistGradientBoostingRegressor(loss='poisson', max_iter=300,
                                          learning_rate=0.06, max_depth=6, random_state=42)
    reg_v = HistGradientBoostingRegressor(loss='poisson', max_iter=300,
                                          learning_rate=0.06, max_depth=6, random_state=42)
    reg_l.fit(X_tr, ds['goles'][m_tr][:, 0])
    reg_v.fit(X_tr, ds['goles'][m_tr][:, 1])

    carpeta = os.path.join('modelos', clave)
    os.makedirs(carpeta, exist_ok=True)
    joblib.dump(modelo, os.path.join(carpeta, 'modelo.joblib'), compress=3)
    joblib.dump(escalador, os.path.join(carpeta, 'escalador.joblib'), compress=3)
    joblib.dump(reg_l, os.path.join(carpeta, 'reg_local.joblib'), compress=3)
    joblib.dump(reg_v, os.path.join(carpeta, 'reg_visit.joblib'), compress=3)

    # Estado por equipo (mismas claves que el Mundial => paridad de features)
    estado = ds['estado']
    equipos_liga = sorted(set(df['home_team']) | set(df['away_team']))
    equipos = {}
    for t in equipos_liga:
        s = estado.stats_equipo(t)
        s['PERF10'] = [list(map(float, v)) for v in estado.perf10[t]]
        equipos[t] = s
    h2h = {}
    for i, a in enumerate(equipos_liga):
        for b in equipos_liga[i + 1:]:
            bal = estado.h2h_balance(a, b)
            if bal != 0.0:
                h2h[f"{a}|{b}"] = round(bal, 3)
    with open(f'team_stats_{clave}.json', 'w', encoding='utf-8') as f:
        json.dump({'generado': pd.Timestamp.today().strftime('%Y-%m-%d'),
                   'ultima_fecha_historico': str(df['date'].max().date()),
                   'equipos': equipos, 'h2h': h2h,
                   'estado_extra': estado_extra,
                   'estado_imt': estado_imt,
                   'estado_v26': estado_v26,
                   'mapa_tz': mapa_tz,
                   'imt_coef': imt_coef}, f, ensure_ascii=False)

    metadata = {
        'liga': LEAGUES[clave]['nombre'],
        'n_train': int(m_tr.sum()), 'n_validacion': int(m_va.sum()),
        'fecha_corte': str(pd.Timestamp(corte).date()),
        'precision_validacion': round(float(acc), 4),
        'precision_linea_base_elo': round(float(base), 4),
        'precision_mercado_cuotas': round(acc_mercado, 4) if acc_mercado else None,
        'log_loss_validacion': round(float(ll), 4),
        'n_equipos': len(equipos_liga),
        'features_extra_cols': cols_extra,
        'medias_cuotas': medias_cuotas,
        'roi_sim': roi_sim,
        'mesm': mesm_info,
        # v24: α,β,γ,δ del índice lineal IMT (train-only, interpretabilidad)
        'imt': (mt.optimizar_coeficientes(df, imt_df, hasta_fecha=corte)
                if estado_imt is not None else None),
    }
    with open(os.path.join(carpeta, 'metadata.json'), 'w', encoding='utf-8') as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)
    logger.info(f"[{clave}] acc={acc:.3f} (base ELO {base:.3f}"
                + (f", mercado {acc_mercado:.3f}" if acc_mercado else "")
                + f") logloss={ll:.3f} — artefactos en {carpeta}/")
    return metadata


# ---------------------------------------------------------------------------
# Motor de inferencia por liga
# ---------------------------------------------------------------------------
class ClubEngine:
    """Predicción y plantilla extendida para una liga de clubes."""

    def __init__(self, clave: str):
        from prediction_api import PredictionEngine  # reutiliza MC/timeline
        self._pe = PredictionEngine  # solo métodos estáticos
        self.clave = clave
        self.listo, self.error = False, None
        try:
            carpeta = os.path.join('modelos', clave)
            self.modelo = joblib.load(os.path.join(carpeta, 'modelo.joblib'))
            self.escalador = joblib.load(os.path.join(carpeta, 'escalador.joblib'))
            self.reg_l = joblib.load(os.path.join(carpeta, 'reg_local.joblib'))
            self.reg_v = joblib.load(os.path.join(carpeta, 'reg_visit.joblib'))
            with open(os.path.join(carpeta, 'metadata.json'), 'r', encoding='utf-8') as f:
                self.metadata = json.load(f)
            # v23: meta-ensemble de superación de mercado (si fue adoptado)
            self.mesm = None
            ruta_mesm = os.path.join(carpeta, 'mesm.joblib')
            if os.path.exists(ruta_mesm):
                try:
                    import meta_ensemble  # noqa: F401 — ruta de clase del pickle
                    self.mesm = joblib.load(ruta_mesm)
                except Exception as e:
                    logger.warning(f"[{clave}] mesm.joblib ilegible: {e}")
            with open(f'team_stats_{clave}.json', 'r', encoding='utf-8') as f:
                ts = json.load(f)
            self.stats = ts['equipos']
            self.h2h = ts.get('h2h', {})
            self.estado_extra = ts.get('estado_extra')
            self.estado_imt = ts.get('estado_imt')   # v24 (IMT)
            self.imt_coef = ts.get('imt_coef')       # v24 (índice compuesto)
            self.estado_v26 = ts.get('estado_v26')   # v26 (ortogonales)
            self.mapa_tz = ts.get('mapa_tz')         # v35 (CDI: club→huso)
            self.fecha_estado = ts.get('ultima_fecha_historico', '?')
            with open('calibracion_statsbomb.json', 'r', encoding='utf-8') as f:
                self.calibracion = json.load(f)
            self.equipos = sorted(self.stats.keys())
            self.listo = True
        except Exception as e:
            self.error = f"{type(e).__name__}: {e}"

    def _h2h(self, home, away):
        if f"{home}|{away}" in self.h2h:
            return float(self.h2h[f"{home}|{away}"])
        if f"{away}|{home}" in self.h2h:
            return -float(self.h2h[f"{away}|{home}"])
        return 0.0

    def _cuotas_partido(self, home: str, away: str) -> Dict:
        """Probabilidades implícitas del partido desde odds_actuales.json."""
        try:
            with open('odds_actuales.json', encoding='utf-8') as f:
                cuotas = json.load(f).get('cuotas', {})
        except Exception:
            return {}
        sufijo = f"_{home.replace(' ', '-')}_{away.replace(' ', '-')}"
        for mid, o in cuotas.items():
            if mid.endswith(sufijo) and o.get('odd_home'):
                inv = np.array([1 / o['odd_home'], 1 / o['odd_draw'], 1 / o['odd_away']])
                imp = inv / inv.sum()
                return {'PROB_IMP_H': float(imp[0]), 'PROB_IMP_D': float(imp[1]),
                        'PROB_IMP_A': float(imp[2]), 'OVERROUND': float(inv.sum() - 1)}
        return {}

    def _vector_extra(self, home: str, away: str) -> np.ndarray:
        """Reproduce en inferencia las features extra v17 desde el estado
        guardado en team_stats (y cuotas vigentes si las hay)."""
        cols = self.metadata.get('features_extra_cols', [])
        ee = self.estado_extra or {'equipos': {}, 'parejas': {}}
        eq = ee.get('equipos', {})
        eh, ea = eq.get(home, {}), eq.get(away, {})
        hoy = pd.Timestamp.today().normalize()

        def descanso(e):
            f = e.get('ultima_fecha')
            return min((hoy - pd.Timestamp(f)).days, 21) if f else 21

        par = tuple(sorted((home, away)))
        gd3 = float(ee.get('parejas', {}).get(f'{par[0]}|{par[1]}', 0.0))
        gd3 = gd3 if par[0] == home else -gd3
        valores = {
            'H2H_GD3': float(np.clip(gd3, -3, 3)) / 3.0,
            'DIFF_DESCANSO': (descanso(eh) - descanso(ea)) / 21.0,
            'DIFF_RACHA_V': (eh.get('racha_v', 0) - ea.get('racha_v', 0)) / 5.0,
            'DIFF_SIN_PERDER': (eh.get('racha_sp', 0) - ea.get('racha_sp', 0)) / 10.0,
            'DIFF_PPG': (eh.get('ppg', 1.3) - ea.get('ppg', 1.3)) / 3.0,
            'DIFF_POSICION': (ea.get('pos', 10) - eh.get('pos', 10)) / 20.0,
        }
        # cuotas: reales del snapshot vigente o medias del train (imputación
        # idéntica a la del entrenamiento)
        reales = self._cuotas_partido(home, away)
        medias = self.metadata.get('medias_cuotas', {})
        for c in COLS_CUOTAS:
            valores[c] = reales.get(c, medias.get(c, 0.0))
        # features MX (v19): geografía + calendario, computables al vuelo
        if any(c in cols for c in COLS_MX):
            valores.update(_fila_mx(home, away, hoy))
        # IMT (v24): componentes o índice compuesto desde el estado guardado
        if any(c in cols for c in mt.COLS_IMT + mt.COLS_IMT_C):
            v_imt = mt.vector_imt(self.estado_imt, home, away, hoy)
            valores.update(v_imt)
            if 'IMT_DIFF' in cols:
                valores['IMT_DIFF'] = mt.valor_compuesto(v_imt, self.imt_coef or {})
        # MLS (v25): geografía continental + clima extremo (forecast memoizado)
        if any(c in cols for c in mls_features.COLS_MLS):
            valores.update(mls_features.fila_inferencia(home, away))
        # v26: entropía/volatilidad, derivadas ELO y urgencia desde el estado
        if any(c in cols for c in f26.COLS_V26):
            valores.update(f26.vector_v26(self.estado_v26, home, away))
        # v35: CDI del partido (huso de la sede del local − huso del visitante)
        if any(c in cols for c in cdi_futbol.COLS_CDI):
            valores.update(cdi_futbol.vector_cdi(self.mapa_tz, home, away))
        return np.array([[valores[c] for c in cols]])

    def predecir(self, home: str, away: str) -> Dict:
        if home not in self.stats or away not in self.stats:
            return {'error': f"Equipo desconocido en {self.clave}."}
        if home == away:
            return {'error': 'Local y visitante no pueden ser el mismo equipo.'}
        s_l, s_v = self.stats[home], self.stats[away]
        ctx = {'CHOQUE_ESTILOS': 0.0, 'ALTURA_NORM': 0.0, 'VENTAJA_LOCALIA': 0.55,
               'CLIMA_TEMP_NORM': 25 / 40.0, 'H2H_BALANCE': self._h2h(home, away)}
        vec = np.array([fe.vector_features(s_l, s_v, ctx)])
        columnas = fe.FEATURES_MODELO + self.metadata.get('features_extra_cols', [])
        if self.metadata.get('features_extra_cols'):
            vec = np.hstack([vec, self._vector_extra(home, away)])
        vec_n = self.escalador.transform(pd.DataFrame(vec, columns=columnas))
        # entropías con ripser (v17: gtda eliminado también aquí — en el cloud
        # ya no está instalado y este era el último import que quedaba)
        ents = [_entropias_ripser(n) for n in (
            fe.nube_de_puntos(s_l, s_v, ctx),
            fe.nube_equipo(s_l.get('PERF10') or [[1, 1, 1, 1, 4, 4]]),
            fe.nube_equipo(s_v.get('PERF10') or [[1, 1, 1, 1, 4, 4]]))]
        X = np.hstack([vec_n, np.concatenate(ents).reshape(1, -1)])
        crudas = self.modelo.predict_proba(X)[0]
        probs = np.zeros(3)
        for c, v in zip(self.modelo.classes_, crudas):
            probs[int(c)] = v
        probs /= probs.sum()
        # v23 (MESM): si el meta fue adoptado en validación Y hay cuotas
        # reales vigentes de ESTE partido, la probabilidad final es la del
        # meta-ensemble (modelo + mercado con objetivo asimétrico).
        mesm_aplicado = False
        if self.mesm is not None:
            imp = self._cuotas_partido(home, away)
            if imp:
                mkt = np.array([[imp['PROB_IMP_H'], imp['PROB_IMP_D'],
                                 imp['PROB_IMP_A'], imp['OVERROUND']]])
                probs = self.mesm.predict_proba(probs.reshape(1, -1), mkt)[0]
                mesm_aplicado = True
        # v25: blending fijo modelo/mercado (LaLiga y Ligue 1, walk-forward
        # VALIDACION_v25). Solo si hay cuotas vigentes y el MESM no actuó.
        blend_aplicado = False
        w_blend = LEAGUES[self.clave].get('blend_mercado')
        if w_blend and not mesm_aplicado:
            imp = self._cuotas_partido(home, away)
            if imp:
                pm = np.array([imp['PROB_IMP_H'], imp['PROB_IMP_D'],
                               imp['PROB_IMP_A']])
                probs = w_blend * probs + (1 - w_blend) * pm
                probs /= probs.sum()
                blend_aplicado = True
        lam_h = float(np.clip(self.reg_l.predict(X)[0], 0.2, 3.8))
        lam_a = float(np.clip(self.reg_v.predict(X)[0], 0.2, 3.8))
        M, marcador, p_marc = self._pe._monte_carlo(lam_h, lam_a, probs)
        timeline = self._pe._linea_de_tiempo(lam_h, lam_a)
        ganador_idx = int(np.argmax(probs))
        # v24: insight de momentum en lenguaje llano (solo si el IMT está
        # adoptado en esta liga y hay estado suficiente)
        insights_imt = []
        cols_liga = self.metadata.get('features_extra_cols', [])
        if self.estado_imt and any(c.startswith('IMT') for c in cols_liga):
            v_imt = mt.vector_imt(self.estado_imt, home, away)
            d_m, d_f = v_imt['IMT_M_DIFF'], v_imt['IMT_FAT_DIFF']
            if abs(d_m) >= 0.15:
                mejor = home if d_m > 0 else away
                insights_imt.append(
                    f"📈 Momentum: {mejor} llega en mejor racha reciente "
                    f"(índice táctico {abs(d_m):+.2f} a su favor).")
            if abs(d_f) >= 0.25:
                fresco = home if d_f > 0 else away
                insights_imt.append(
                    f"🔋 Calendario: {fresco} llega más descansado "
                    f"(menos partidos en los últimos 14 días).")
        return {
            'match': f'{home} vs {away}', 'liga': LEAGUES[self.clave]['nombre'],
            'estado_al': self.fecha_estado,
            'prediction': {
                'winner': [home, 'Empate', away][ganador_idx],
                'confidence': round(float(probs[ganador_idx]), 3),
                'probabilities': {'home': round(float(probs[0]), 3),
                                  'draw': round(float(probs[1]), 3),
                                  'away': round(float(probs[2]), 3)},
                'most_likely_score': f'{marcador[0]}-{marcador[1]}',
                'score_probability': round(p_marc, 3),
                'total_goals_expected': round(lam_h + lam_a, 2),
                'expected_goals': {'home': round(lam_h, 2), 'away': round(lam_a, 2)},
            },
            'score_matrix': M.round(4).tolist(), 'timeline': timeline,
            'insights': [
                f"Nivel dinámico: {home} {s_l['ELO']:.0f} vs {away} {s_v['ELO']:.0f}.",
                f"Forma (últimos 5): {home} {s_l['FORMA_MA5']:.2f} · {away} {s_v['FORMA_MA5']:.2f}.",
            ] + insights_imt
              + (["🧠 Probabilidades del meta-ensemble MESM: el modelo se combina "
                  "con las cuotas vigentes del partido (objetivo asimétrico "
                  "validado en walk-forward)."] if mesm_aplicado else [])
              + ([f"⚖️ Probabilidades combinadas {int((w_blend or 0)*100)}/"
                  f"{int((1-(w_blend or 0))*100)} con el mercado (blending "
                  "validado en walk-forward v25)."] if blend_aplicado else []),
            'model': {'accuracy_backtest': self.metadata['precision_validacion'],
                      'log_loss_backtest': self.metadata['log_loss_validacion'],
                      'mercado_ref': self.metadata.get('precision_mercado_cuotas'),
                      'mesm_aplicado': mesm_aplicado,
                      'blend_aplicado': blend_aplicado},
        }

    # ------------------------------------------------------------------ #
    def plantilla_club(self, home: str, away: str) -> Dict:
        """Plantilla extendida de clubes (mismo formato que la del Mundial)."""
        from prediction_api import prob_over, cuota_americana
        pred = self.predecir(home, away)
        if 'error' in pred:
            return pred
        M = np.array(pred['score_matrix'])
        idx = np.arange(M.shape[0])
        diff = idx[:, None] - idx[None, :]
        total = idx[:, None] + idx[None, :]
        lam_h = pred['prediction']['expected_goals']['home']
        lam_a = pred['prediction']['expected_goals']['away']
        s_l, s_v = self.stats[home], self.stats[away]
        pct = lambda x: round(float(x) * 100, 1)

        def campo(id_, etiqueta, valor, tipo='pct'):
            return {'id': id_, 'etiqueta': etiqueta, 'valor': valor, 'tipo': tipo}

        p1 = float(M[diff > 0].sum()); px = float(M[diff == 0].sum()); p2 = float(M[diff < 0].sum())
        secciones = [
            {'titulo': '1. Resultado (1X2) con cuota justa', 'campos': [
                campo('home_win_prob', f'Gana {home} ({cuota_americana(p1)})', pct(p1)),
                campo('draw_prob', f'Empate ({cuota_americana(px)})', pct(px)),
                campo('away_win_prob', f'Gana {away} ({cuota_americana(p2)})', pct(p2)),
            ]},
            {'titulo': '2. Doble oportunidad', 'campos': [
                campo('dc_1x', f'{home} o Empate', pct(p1 + px)),
                campo('dc_12', f'{home} o {away}', pct(p1 + p2)),
                campo('dc_x2', f'Empate o {away}', pct(px + p2)),
            ]},
        ]

        # 3. Over/Under con línea deslizable (0.5 a 5.5)
        secciones.append({'titulo': '3. Total de goles (línea deslizable)', 'campos': [
            campo(f'over{str(l).replace(".", "")}', f'Más de {l} goles', pct(M[total > l].sum()))
            for l in (0.5, 1.5, 2.5, 3.5, 4.5, 5.5)]})

        # 4. BTTS, primer/último gol, par/impar
        btts = float(M[(idx[:, None] >= 1) & (idx[None, :] >= 1)].sum())
        p_algun = 1 - float(M[0, 0])
        cuota_h = lam_h / max(lam_h + lam_a, 1e-6)
        par = float(M[(total % 2) == 0].sum())
        secciones.append({'titulo': '4. Ambos marcan · Primer/último gol · Par-Impar', 'campos': [
            campo('btts_si', 'Ambos equipos marcan: Sí', pct(btts)),
            campo('btts_no', 'Ambos equipos marcan: No', pct(1 - btts)),
            campo('primer_gol_home', f'Primer gol de {home}', pct(cuota_h * p_algun)),
            campo('primer_gol_away', f'Primer gol de {away}', pct((1 - cuota_h) * p_algun)),
            campo('sin_goles', 'Sin goles (0-0)', pct(M[0, 0])),
            campo('ultimo_gol_home', f'Último gol de {home}', pct(cuota_h * p_algun)),
            campo('total_par', 'Total de goles PAR (0 cuenta)', pct(par)),
            campo('total_impar', 'Total de goles IMPAR', pct(1 - par)),
        ]})

        # 5. Hándicap asiático completo
        campos_h = []
        for k, linea in [(1, '-0.5'), (2, '-1.5'), (3, '-2.5'), (4, '-3.5')]:
            pk = float(M[diff >= k].sum())
            campos_h.append(campo(f'ah_home_{k}', f'{home} {linea}', pct(pk)))
            campos_h.append(campo(f'ah_away_{k}', f'{away} +{linea[1:]}', pct(1 - pk)))
        campos_h.insert(0, campo('ah_home_mas05', f'{home} +0.5 (no pierde)', pct(p1 + px)))
        campos_h.insert(1, campo('ah_away_mas05', f'{away} +0.5 (no pierde)', pct(p2 + px)))
        secciones.append({'titulo': '5. Hándicap asiático', 'campos': campos_h})

        # 6. Hándicap 1X2 (con ventaja de -1 gol para el favorito)
        fav_es_home = p1 >= p2
        d = diff if fav_es_home else -diff
        fav, dog = (home, away) if fav_es_home else (away, home)
        secciones.append({'titulo': f'6. Hándicap 1X2 ({fav} -1)', 'campos': [
            campo('h1x2_fav', f'{fav} gana por 2+', pct(M[d >= 2].sum())),
            campo('h1x2_empate', f'{fav} gana por exactamente 1', pct(M[d == 1].sum())),
            campo('h1x2_dog', f'{dog} +1 (empata o gana)', pct(M[d <= 0].sum())),
        ]})

        # 7. Marcador exacto (top 8 con cuota justa americana)
        planos = [(int(i), int(j), float(M[i, j])) for i in idx for j in idx]
        planos.sort(key=lambda t: t[2], reverse=True)
        secciones.append({'titulo': '7. Marcador exacto (top 8)', 'campos': [
            campo(f'score_{gh}_{ga}', f'{home} {gh}-{ga} {away} ({cuota_americana(p)})', pct(p))
            for gh, ga, p in planos[:8]]})

        # 8. Margen de victoria
        secciones.append({'titulo': '8. Margen de victoria', 'campos': [
            campo('mv_h1', f'{home} por 1', pct(M[diff == 1].sum())),
            campo('mv_h2', f'{home} por 2', pct(M[diff == 2].sum())),
            campo('mv_h3', f'{home} por 3+', pct(M[diff >= 3].sum())),
            campo('mv_x', 'Empate', pct(px)),
            campo('mv_a1', f'{away} por 1', pct(M[diff == -1].sum())),
            campo('mv_a2', f'{away} por 2', pct(M[diff == -2].sum())),
            campo('mv_a3', f'{away} por 3+', pct(M[diff <= -3].sum())),
        ]})

        # 9. Mitades (HT/FT con mitades Poisson 45 %/55 % del ritmo real)
        from math import exp, factorial
        def poisson_vec(lam, n=7):
            return np.array([exp(-lam) * lam ** k / factorial(k) for k in range(n)])
        res_ht, res_ft2 = {}, {}
        for etq, frac in (('1T', 0.45), ('2T', 0.55)):
            Mh = np.outer(poisson_vec(lam_h * frac), poisson_vec(lam_a * frac))
            i2 = np.arange(7)
            d2 = i2[:, None] - i2[None, :]
            (res_ht if etq == '1T' else res_ft2)['H'] = float(Mh[d2 > 0].sum())
            (res_ht if etq == '1T' else res_ft2)['D'] = float(Mh[d2 == 0].sum())
            (res_ht if etq == '1T' else res_ft2)['A'] = float(Mh[d2 < 0].sum())
        etiquetas = {'H': home, 'D': 'Empate', 'A': away}
        campos_htft = []
        for r1 in 'HDA':
            for r2 in 'HDA':
                # aproximación de mitades independientes; el FT se deriva del 2T
                # condicionado al 1T vía convolución simple del marcador
                p_combo = res_ht[r1] * res_ft2[r2]
                campos_htft.append(campo(f'htft_{r1}{r2}',
                                         f'Descanso: {etiquetas[r1]} / 2ª mitad: {etiquetas[r2]}',
                                         pct(p_combo)))
        secciones.append({'titulo': '9. Mitades (resultado al descanso / 2ª mitad)',
                          'campos': campos_htft})

        # 10. Totales por equipo y multigoles
        g_h = M.sum(axis=1); g_a = M.sum(axis=0)
        secciones.append({'titulo': '10. Goles por equipo y multigoles', 'campos': [
            campo('th_o05', f'{home} más de 0.5 goles', pct(g_h[1:].sum())),
            campo('th_o15', f'{home} más de 1.5 goles', pct(g_h[2:].sum())),
            campo('th_o25', f'{home} más de 2.5 goles', pct(g_h[3:].sum())),
            campo('ta_o05', f'{away} más de 0.5 goles', pct(g_a[1:].sum())),
            campo('ta_o15', f'{away} más de 1.5 goles', pct(g_a[2:].sum())),
            campo('ta_o25', f'{away} más de 2.5 goles', pct(g_a[3:].sum())),
            campo('multi_h', f'{home} marca 2 o más', pct(g_h[2:].sum())),
            campo('multi_a', f'{away} marca 2 o más', pct(g_a[2:].sum())),
        ]})

        # 11. Córners y tarjetas (bases MA5 reales en formato 'main')
        spx = float(self.calibracion.get('shots_on_por_xg', 3.1))
        tpo = float(self.calibracion.get('shots_total_por_on', 2.6))
        ck = 4.0 + 0.25 * (lam_h + lam_a) * spx * tpo
        cards = (s_l['AMAR_MA5'] + s_v['AMAR_MA5'] +
                 s_l['ROJAS_MA5'] + s_v['ROJAS_MA5'])
        secciones.append({'titulo': '11. Córners y tarjetas', 'campos': [
            campo('corners_media', 'Córners totales (media)', round(ck, 1), 'media'),
            campo('ck_o85', 'Más de 8.5 córners', pct(prob_over(ck, 8.5))),
            campo('ck_o95', 'Más de 9.5 córners', pct(prob_over(ck, 9.5))),
            campo('ck_o105', 'Más de 10.5 córners', pct(prob_over(ck, 10.5))),
            campo('cards_media', 'Tarjetas totales (media)', round(cards, 1), 'media'),
            campo('cards_o35', 'Más de 3.5 tarjetas', pct(prob_over(cards, 3.5))),
            campo('cards_o45', 'Más de 4.5 tarjetas', pct(prob_over(cards, 4.5))),
        ]})

        return {
            'partido': f'{home} vs {away}',
            'codigos': {'home': home, 'away': away},
            'liga': LEAGUES[self.clave]['nombre'],
            'fecha': pd.Timestamp.today().strftime('%Y-%m-%d'),
            'estado_al': self.fecha_estado,
            'secciones': secciones,
            'observaciones': pred['insights'] + [
                f"Modelo de {LEAGUES[self.clave]['nombre']}: precisión de backtesting "
                f"{self.metadata['precision_validacion']*100:.1f} % "
                + (f"(mercado con cuotas de cierre: {self.metadata['precision_mercado_cuotas']*100:.1f} %)"
                   if self.metadata.get('precision_mercado_cuotas') else ''),
                "Cuotas mostradas = cuotas JUSTAS del modelo en formato americano "
                "(sin margen de casa).",
            ],
            'prediccion_base': pred,
        }


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    con_ratings = '--ratings' in sys.argv
    argumentos = [a for a in sys.argv[1:] if not a.startswith('--')]
    objetivo = argumentos[0] if argumentos else None
    if '--build' in sys.argv:
        for clave, cfg in LEAGUES.items():
            if not cfg.get('disponible'):
                logger.info(f"[{clave}] omitida: {cfg.get('nota', 'no disponible')}")
                continue
            if objetivo and clave != objetivo:
                continue
            try:
                entrenar_liga(clave, con_ratings=con_ratings)
            except Exception as e:
                logger.error(f"[{clave}] falló: {type(e).__name__}: {e}")
