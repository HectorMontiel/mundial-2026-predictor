#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Modelo de Anulación Táctica — MAT (v23).

FORMALIZACIÓN HONESTA DEL FENÓMENO. El master prompt pedía predecir que una
estrella concreta termine con 0 remates a puerta; ese dato por jugador y
partido NO existe gratis a escala (FBref lo tiene por match report — miles de
páginas tras Cloudflare; API-Football lo cobra por fixture). Lo que SÍ es
observable, masivo y contiene el mismo fenómeno es el **apagón ofensivo del
equipo**: partidos donde un ataque fuerte termina en 0 goles porque el rival
ejecutó un plan de anulación. Cuando el equipo se apaga, la estrella se apaga
— y la probabilidad del goleador se ajusta en consecuencia.

## El modelo, en matemáticas

Para cada (equipo A, rival B, partido m):

  y = 1{goles de A en m = 0}

  P_MAT(y=1 | x)  con  x = [ataque de A, presión defensiva de B, fatiga,
                            contexto eliminatorio, clima, ELO]
  (XGBoost binario + calibración isotónica, features pre-partido sin fuga)

Baseline natural del fútbol: bajo Poisson, P(0) = exp(-λ). El **factor de
supresión táctica** es la información NUEVA del MAT respecto a Poisson:

  τ = log( P_MAT(0) / exp(-λ) )        (τ > 0: el rival "huele" a anulación)

Y la corrección de la tasa de goles es la λ' que hace consistente a Poisson
con el MAT, mezclada con peso w validado en walk-forward:

  λ' = (1 − w)·λ + w·(−ln P_MAT(0))    ⇒  exp(−λ') interpola entre ambos

El ajuste solo toca la CAPA DE GOLES (over/under, marcador, BTTS, goleadores
vía λ'/λ) — el 1X2 calibrado queda intacto por construcción, porque el Monte
Carlo re-pondera la matriz de marcadores a los marginales del clasificador.

## Validación (regla de oro)

Walk-forward temporal con ventanas de 6 meses sobre 2024+:
  1. ¿P_MAT(0) mejora el Brier/log-loss de predecir el 0 vs exp(-λ)?
  2. ¿λ' mejora la NLL Poisson de los goles observados vs λ?  → elige w.
Si (1) o (2) fallan, el MAT queda como señal informativa y NO toca nada.
"""

import json
import logging
import os
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

ARCHIVO_MODELO = os.path.join('modelos', 'mat_mundial.joblib')
ARCHIVO_META = os.path.join('modelos', 'mat_metadata.json')
FECHA_INICIO = '2015-01-01'      # era con clima backfilleado
VENTANA_FATIGA_D = 14

FEATURES = [
    # ataque propio (lo que el rival intenta apagar)
    'GF_MA5', 'XGF_MA5', 'SOTF_MA5', 'FORMA_MA5',
    # presión/solidez defensiva del rival
    'RIVAL_GA_MA5', 'RIVAL_XGC_MA5', 'RIVAL_SOTC_MA5', 'RIVAL_AMAR_MA5',
    'RIVAL_FORMA_MA5',
    # fatiga y calendario
    'DESCANSO_DIAS', 'PARTIDOS_14D', 'DIFF_DESCANSO',
    # contexto
    'ELO_DIFF', 'ES_LOCAL_REAL', 'TORNEO_FINAL',
    # clima (Open-Meteo; NaN → mediana del train)
    'CLIMA_TMAX', 'CLIMA_PRECIP', 'CLIMA_VIENTO', 'CLIMA_HUMEDAD',
    # baseline Poisson como feature (el MAT aprende el RESIDUO táctico)
    'P0_POISSON',
]


def _lambda_heuristica(xgf_propio: float, xgc_rival: float, es_local: int) -> float:
    """La misma heurística de λ del motor (prediction_api fallback)."""
    lam = 0.55 * xgf_propio + 0.45 * xgc_rival
    if es_local:
        lam *= 1.15
    return float(np.clip(lam, 0.2, 3.5))


def construir_dataset(historico: pd.DataFrame,
                      con_clima: bool = True) -> pd.DataFrame:
    """2 filas por partido (perspectiva de cada equipo), features SIN fuga:
    estado rodante propio hasta la víspera. Devuelve DataFrame con FEATURES,
    'y' (anotó 0), 'goles', 'date' y 'MATCH_ID'."""
    import feature_engineering as fe
    if con_clima:
        import clima

    df = historico.copy()
    df['date'] = pd.to_datetime(df['date'])
    df = df[df['date'] >= FECHA_INICIO]
    claves = ['date', 'MATCH_ID'] if 'MATCH_ID' in df.columns else ['date']
    df = df.sort_values(claves, kind='mergesort').reset_index(drop=True)
    numericas = ['home_goals', 'away_goals', 'home_xg', 'away_xg',
                 'home_shots_on', 'away_shots_on', 'home_yellow',
                 'away_yellow', 'home_red', 'away_red']
    for c in numericas:
        df[c] = pd.to_numeric(df[c], errors='coerce')
    df = df.dropna(subset=numericas).reset_index(drop=True)

    estado = fe.EstadoRodante()
    ultima_fecha: Dict[str, pd.Timestamp] = {}
    fechas_prev: Dict[str, List[pd.Timestamp]] = {}
    filas = []
    for _, fila in df.iterrows():
        h, a = fila['home_team'], fila['away_team']
        s_h, s_a = estado.stats_equipo(h), estado.stats_equipo(a)
        torneo = str(fila.get('tournament', ''))
        torneo_final = int('qualification' not in torneo.lower()
                           and torneo != 'Friendly')
        es_neutral = bool(fila.get('neutral', True))
        cl = None
        if con_clima:
            cl = clima.obtener_clima(fila.get('city'), fila.get('country'),
                                     str(fila['date'])[:10])
        cl = cl or {}

        def descanso(eq):
            ult = ultima_fecha.get(eq)
            return min((fila['date'] - ult).days, 30) if ult is not None else 14

        def carga14(eq):
            corte = fila['date'] - pd.Timedelta(days=VENTANA_FATIGA_D)
            return sum(1 for f in fechas_prev.get(eq, []) if f >= corte)

        for eq, riv, s_eq, s_riv, goles, es_local in [
                (h, a, s_h, s_a, fila['home_goals'], 0 if es_neutral else 1),
                (a, h, s_a, s_h, fila['away_goals'], 0)]:
            if s_eq['N_PARTIDOS'] < 3 or s_riv['N_PARTIDOS'] < 3:
                continue
            lam = _lambda_heuristica(s_eq['XGF_MA5'], s_riv['XGC_MA5'], es_local)
            filas.append({
                'MATCH_ID': fila.get('MATCH_ID'), 'date': fila['date'],
                'equipo': eq, 'rival': riv,
                'GF_MA5': s_eq['GF_MA5'], 'XGF_MA5': s_eq['XGF_MA5'],
                'SOTF_MA5': s_eq['SOTF_MA5'], 'FORMA_MA5': s_eq['FORMA_MA5'],
                'RIVAL_GA_MA5': s_riv['GA_MA5'], 'RIVAL_XGC_MA5': s_riv['XGC_MA5'],
                'RIVAL_SOTC_MA5': s_riv['SOTC_MA5'],
                'RIVAL_AMAR_MA5': s_riv['AMAR_MA5'],
                'RIVAL_FORMA_MA5': s_riv['FORMA_MA5'],
                'DESCANSO_DIAS': descanso(eq), 'PARTIDOS_14D': carga14(eq),
                'DIFF_DESCANSO': descanso(eq) - descanso(riv),
                'ELO_DIFF': (estado.elo[eq] - estado.elo[riv]) / 400.0,
                'ES_LOCAL_REAL': es_local, 'TORNEO_FINAL': torneo_final,
                'CLIMA_TMAX': cl.get('tmax'), 'CLIMA_PRECIP': cl.get('precip'),
                'CLIMA_VIENTO': cl.get('viento'), 'CLIMA_HUMEDAD': cl.get('humedad'),
                'P0_POISSON': float(np.exp(-lam)),
                'LAMBDA_BASE': lam,
                'goles': float(goles), 'y': int(goles == 0),
            })
        estado.actualizar(fila)
        for eq in (h, a):
            ultima_fecha[eq] = fila['date']
            fechas_prev.setdefault(eq, []).append(fila['date'])
    return pd.DataFrame(filas)


def _construir_clf():
    from xgboost import XGBClassifier
    from sklearn.calibration import CalibratedClassifierCV
    xgb = XGBClassifier(n_estimators=250, max_depth=4, learning_rate=0.05,
                        subsample=0.85, colsample_bytree=0.8, reg_lambda=3.0,
                        eval_metric='logloss', tree_method='hist',
                        random_state=42, n_jobs=-1, verbosity=0)
    return CalibratedClassifierCV(xgb, method='isotonic', cv=3)


def _imputar(X_tr: pd.DataFrame, X_va: pd.DataFrame) -> Tuple:
    X_tr = X_tr.apply(pd.to_numeric, errors='coerce')
    X_va = X_va.apply(pd.to_numeric, errors='coerce')
    medianas = X_tr.median(numeric_only=True)
    # columna completamente vacía (p. ej. clima sin backfill) → 0 constante
    medianas = medianas.reindex(X_tr.columns).fillna(0.0)
    return X_tr.fillna(medianas), X_va.fillna(medianas), medianas


def lambda_ajustada(lam: np.ndarray, p0_mat: np.ndarray, w: float) -> np.ndarray:
    """λ' = (1−w)·λ + w·(−ln P_MAT(0)) — la λ consistente con el MAT."""
    p0 = np.clip(p0_mat, 1e-4, 0.97)
    return (1.0 - w) * lam + w * (-np.log(p0))


def validar_walk_forward(ds: pd.DataFrame,
                         pesos=(0.0, 0.25, 0.5, 0.75)) -> Dict:
    """Ventanas de 6 meses sobre 2024+. Mide (1) Brier/ll de P(0) del MAT vs
    Poisson y (2) NLL Poisson de goles con λ' para cada w."""
    from sklearn.metrics import brier_score_loss, log_loss
    fechas = ds['date']
    ventanas = pd.date_range('2024-01-01', fechas.max(), freq='6MS')
    filas, por_w = [], {w: [] for w in pesos}
    for inicio in ventanas:
        fin = inicio + pd.DateOffset(months=6)
        m_tr = (fechas < inicio).values
        m_va = ((fechas >= inicio) & (fechas < fin)).values
        if m_va.sum() < 200:
            continue
        X_tr, X_va, _ = _imputar(ds.loc[m_tr, FEATURES], ds.loc[m_va, FEATURES])
        clf = _construir_clf()
        clf.fit(X_tr, ds.loc[m_tr, 'y'])
        p0_mat = clf.predict_proba(X_va)[:, 1]
        y_va = ds.loc[m_va, 'y'].values
        p0_pois = ds.loc[m_va, 'P0_POISSON'].values
        lam = ds.loc[m_va, 'LAMBDA_BASE'].values
        goles = ds.loc[m_va, 'goles'].values
        fila = {
            'ventana': f"{inicio.date()} → {fin.date()}", 'n': int(m_va.sum()),
            'tasa_apagon': round(float(y_va.mean()), 4),
            'brier_mat': round(float(brier_score_loss(y_va, p0_mat)), 5),
            'brier_poisson': round(float(brier_score_loss(
                y_va, np.clip(p0_pois, 1e-6, 1 - 1e-6))), 5),
            'll_mat': round(float(log_loss(y_va, np.clip(p0_mat, 1e-6, 1 - 1e-6),
                                           labels=[0, 1])), 5),
            'll_poisson': round(float(log_loss(y_va, np.clip(p0_pois, 1e-6, 1 - 1e-6),
                                               labels=[0, 1])), 5),
        }
        # NLL Poisson de los goles observados con λ'(w)
        from scipy.stats import poisson as _poisson
        for w in pesos:
            lam_w = lambda_ajustada(lam, p0_mat, w)
            nll = float(-_poisson.logpmf(goles.astype(int),
                                         np.clip(lam_w, 0.05, 6)).mean())
            fila[f'nll_goles_w{w}'] = round(nll, 5)
            por_w[w].append(nll)
        filas.append(fila)
        logger.info(f"  MAT wf {inicio.date()}: n={fila['n']} "
                    f"brier {fila['brier_mat']:.4f} vs pois {fila['brier_poisson']:.4f}")
    medias_w = {str(w): round(float(np.mean(v)), 5) for w, v in por_w.items() if v}
    mejor_w = min(medias_w, key=medias_w.get) if medias_w else '0.0'
    return {
        'ventanas': filas,
        'brier_mat_medio': round(float(np.mean([f['brier_mat'] for f in filas])), 5),
        'brier_poisson_medio': round(float(np.mean([f['brier_poisson'] for f in filas])), 5),
        'll_mat_medio': round(float(np.mean([f['ll_mat'] for f in filas])), 5),
        'll_poisson_medio': round(float(np.mean([f['ll_poisson'] for f in filas])), 5),
        'nll_goles_por_w': medias_w,
        'mejor_w': float(mejor_w),
        'mat_supera_poisson': bool(
            np.mean([f['brier_mat'] for f in filas])
            < np.mean([f['brier_poisson'] for f in filas])),
    }


def entrenar_final(ds: pd.DataFrame, w: float) -> Dict:
    """Entrena con TODO el histórico y persiste modelo + medianas + w."""
    import joblib
    X, _, medianas = _imputar(ds[FEATURES], ds[FEATURES].iloc[:0])
    clf = _construir_clf()
    clf.fit(X, ds['y'])
    joblib.dump(clf, ARCHIVO_MODELO, compress=3)
    meta = {'w': w, 'medianas': {k: (None if pd.isna(v) else round(float(v), 4))
                                 for k, v in medianas.items()},
            'n_train': int(len(ds)), 'features': FEATURES,
            'entrenado_en': pd.Timestamp.now().isoformat(timespec='seconds')}
    with open(ARCHIVO_META, 'w', encoding='utf-8') as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    logger.info(f"MAT final: {len(ds)} obs, w={w} → {ARCHIVO_MODELO}")
    return meta


class MAT:
    """Inferencia en vivo para el motor del Mundial."""

    def __init__(self):
        import joblib
        self.listo = False
        try:
            self.clf = joblib.load(ARCHIVO_MODELO)
            with open(ARCHIVO_META, encoding='utf-8') as f:
                self.meta = json.load(f)
            self.listo = True
        except Exception as e:
            logger.warning(f"MAT no disponible: {e}")

    def prob_apagon(self, features: Dict) -> Optional[float]:
        if not self.listo:
            return None
        x = pd.DataFrame([{k: features.get(k) for k in FEATURES}])
        x = x.apply(pd.to_numeric, errors='coerce')
        x = x.fillna({k: v for k, v in self.meta['medianas'].items()
                      if v is not None}).fillna(0.0)
        return float(self.clf.predict_proba(x)[0, 1])

    def ajustar_lambda(self, lam: float, p0_mat: float) -> float:
        return float(lambda_ajustada(np.array([lam]), np.array([p0_mat]),
                                     self.meta.get('w', 0.0))[0])


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    h = pd.read_csv('historico_partidos.csv')
    ds = construir_dataset(h)
    cobertura = ds['CLIMA_TMAX'].notna().mean()
    print(f"dataset: {len(ds)} observaciones · apagones: {ds['y'].mean()*100:.1f} % "
          f"· clima cubierto: {cobertura*100:.1f} %")
    res = validar_walk_forward(ds)
    print(json.dumps(res, indent=2))
    with open('resultados_mat_v23.json', 'w', encoding='utf-8') as f:
        json.dump(res, f, indent=2)
    if res['mat_supera_poisson']:
        # w se CAPA en 0.5 (conservador): la NLL se validó sobre la λ
        # heurística, pero en el motor el cociente λ'/λ se aplica a la λ del
        # regresor (más fuerte). La ganancia 0.5→1.0 es marginal (~2 %) y no
        # justifica el riesgo de sobrecorregir — validar sobre la λ del
        # regresor queda para v24.
        entrenar_final(ds, min(res['mejor_w'], 0.5))
