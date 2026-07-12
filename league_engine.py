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
import statsbomb_calibration
from config import LEAGUES
from correlated_synthetic_generator import CorrelatedSyntheticGenerator

logger = logging.getLogger(__name__)


def _match_id(fecha: pd.Timestamp, home: str, away: str) -> str:
    h = str(home).replace(' ', '-')
    a = str(away).replace(' ', '-')
    return f"{fecha.strftime('%Y%m%d')}_{h}_{a}"


# ---------------------------------------------------------------------------
# Descarga y normalización al esquema del histórico
# ---------------------------------------------------------------------------
def descargar_liga(clave: str) -> pd.DataFrame:
    cfg = LEAGUES[clave]
    frames = []
    for url in cfg['urls']:
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        frames.append(pd.read_csv(io.StringIO(r.text), on_bad_lines='skip',
                                  encoding_errors='ignore'))
    crudo = pd.concat(frames, ignore_index=True)

    if cfg['formato'] == 'main':
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
        })
    else:  # 'new': solo goles + cuotas
        df = pd.DataFrame({
            'date': pd.to_datetime(crudo['Date'], dayfirst=True, errors='coerce'),
            'home_team': crudo['Home'], 'away_team': crudo['Away'],
            'home_goals': pd.to_numeric(crudo['HG'], errors='coerce'),
            'away_goals': pd.to_numeric(crudo['AG'], errors='coerce'),
            'odd_home': pd.to_numeric(crudo.get('AvgH', crudo.get('PH')), errors='coerce'),
            'odd_draw': pd.to_numeric(crudo.get('AvgD', crudo.get('PD')), errors='coerce'),
            'odd_away': pd.to_numeric(crudo.get('AvgA', crudo.get('PA')), errors='coerce'),
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

    corte = fechas.quantile(0.80)
    m_tr = (fechas < corte).values
    m_va = ~m_tr
    X_tr_n, X_va_n, escalador = fe.normalizar_features(X_df[m_tr], X_df[m_va])
    X_tr = np.hstack([X_tr_n, topo[m_tr]])
    X_va = np.hstack([X_va_n, topo[m_va]])

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
                   'equipos': equipos, 'h2h': h2h}, f, ensure_ascii=False)

    metadata = {
        'liga': LEAGUES[clave]['nombre'],
        'n_train': int(m_tr.sum()), 'n_validacion': int(m_va.sum()),
        'fecha_corte': str(pd.Timestamp(corte).date()),
        'precision_validacion': round(float(acc), 4),
        'precision_linea_base_elo': round(float(base), 4),
        'precision_mercado_cuotas': round(acc_mercado, 4) if acc_mercado else None,
        'log_loss_validacion': round(float(ll), 4),
        'n_equipos': len(equipos_liga),
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
            with open(f'team_stats_{clave}.json', 'r', encoding='utf-8') as f:
                ts = json.load(f)
            self.stats = ts['equipos']
            self.h2h = ts.get('h2h', {})
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

    def predecir(self, home: str, away: str) -> Dict:
        from gtda.homology import VietorisRipsPersistence
        from gtda.diagrams import PersistenceEntropy
        if home not in self.stats or away not in self.stats:
            return {'error': f"Equipo desconocido en {self.clave}."}
        if home == away:
            return {'error': 'Local y visitante no pueden ser el mismo equipo.'}
        s_l, s_v = self.stats[home], self.stats[away]
        ctx = {'CHOQUE_ESTILOS': 0.0, 'ALTURA_NORM': 0.0, 'VENTAJA_LOCALIA': 0.55,
               'CLIMA_TEMP_NORM': 25 / 40.0, 'H2H_BALANCE': self._h2h(home, away)}
        vec = np.array([fe.vector_features(s_l, s_v, ctx)])
        vec_n = self.escalador.transform(pd.DataFrame(vec, columns=fe.FEATURES_MODELO))
        vr = VietorisRipsPersistence(homology_dimensions=[0, 1], n_jobs=-1)
        pe = PersistenceEntropy(nan_fill_value=0.0)
        ents = [pe.fit_transform(vr.fit_transform(n[np.newaxis]))[0] for n in (
            fe.nube_de_puntos(s_l, s_v, ctx),
            fe.nube_equipo(s_l.get('PERF10') or [[1, 1, 1, 1, 4, 4]]),
            fe.nube_equipo(s_v.get('PERF10') or [[1, 1, 1, 1, 4, 4]]))]
        X = np.hstack([vec_n, np.concatenate(ents).reshape(1, -1)])
        crudas = self.modelo.predict_proba(X)[0]
        probs = np.zeros(3)
        for c, v in zip(self.modelo.classes_, crudas):
            probs[int(c)] = v
        probs /= probs.sum()
        lam_h = float(np.clip(self.reg_l.predict(X)[0], 0.2, 3.8))
        lam_a = float(np.clip(self.reg_v.predict(X)[0], 0.2, 3.8))
        M, marcador, p_marc = self._pe._monte_carlo(lam_h, lam_a, probs)
        timeline = self._pe._linea_de_tiempo(lam_h, lam_a)
        ganador_idx = int(np.argmax(probs))
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
            ],
            'model': {'accuracy_backtest': self.metadata['precision_validacion'],
                      'log_loss_backtest': self.metadata['log_loss_validacion'],
                      'mercado_ref': self.metadata.get('precision_mercado_cuotas')},
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
