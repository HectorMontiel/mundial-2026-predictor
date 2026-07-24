#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MLBEngine (v29 §4) — béisbol, hereda de BaseSportsEngine.

Fuente: Retrosheet game logs (histórico gratuito, 2021-2025, 11.9k juegos)
para entrenar; The Odds API (baseball_mlb, en temporada) para cuotas en vivo.
Sin empates → clasificador binario (gana local sí/no).

Features pre-partido SIN fuga (pase cronológico):
  DIFF_ELO · DIFF_RUNS_SCORED_MA10 · DIFF_RUNS_ALLOWED_MA10 · DIFF_STREAK ·
  DIFF_REST · DIFF_PITCHER_RA (carreras/apertura recientes del abridor —
  la variable más crítica del béisbol) + absolutos para el regresor de total.

Estado por equipo/pitcher persistido en modelos/mlb/estado.json para
reproducir las features en inferencia (mismo patrón que las ligas de fútbol).
"""

import json
import logging
import os
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from engines.base_engine import BaseSportsEngine

logger = logging.getLogger(__name__)

MA = 10
FEATURES = ['DIFF_ELO', 'DIFF_RS_MA', 'DIFF_RA_MA', 'DIFF_STREAK',
            'DIFF_REST', 'DIFF_PIT_RA', 'SUMA_RS_MA', 'SUMA_RA_MA',
            'MEDIA_PIT_RA']
CARPETA = os.path.join('modelos', 'mlb')

# nombre The Odds API/ESPN -> código Retrosheet (para cruzar cuotas en vivo)
NOMBRES_MLB = {
    'Los Angeles Angels': 'ANA', 'Arizona Diamondbacks': 'ARI',
    'Atlanta Braves': 'ATL', 'Baltimore Orioles': 'BAL', 'Boston Red Sox': 'BOS',
    'Chicago White Sox': 'CHA', 'Chicago Cubs': 'CHN', 'Cincinnati Reds': 'CIN',
    'Cleveland Guardians': 'CLE', 'Colorado Rockies': 'COL',
    'Detroit Tigers': 'DET', 'Houston Astros': 'HOU', 'Kansas City Royals': 'KCA',
    'Los Angeles Dodgers': 'LAN', 'Miami Marlins': 'MIA',
    'Milwaukee Brewers': 'MIL', 'Minnesota Twins': 'MIN',
    'New York Yankees': 'NYA', 'New York Mets': 'NYN', 'Oakland Athletics': 'OAK',
    'Athletics': 'ATH', 'Philadelphia Phillies': 'PHI', 'Pittsburgh Pirates': 'PIT',
    'San Diego Padres': 'SDN', 'Seattle Mariners': 'SEA',
    'San Francisco Giants': 'SFN', 'St. Louis Cardinals': 'SLN',
    'Tampa Bay Rays': 'TBA', 'Texas Rangers': 'TEX', 'Toronto Blue Jays': 'TOR',
    'Washington Nationals': 'WAS',
}
CODIGO_A_NOMBRE = {v: k for k, v in NOMBRES_MLB.items()}


def codigo_mlb(nombre: str) -> str:
    """Nombre de casa → código Retrosheet (con respaldo fuzzy)."""
    if nombre in NOMBRES_MLB:
        return NOMBRES_MLB[nombre]
    from difflib import SequenceMatcher
    mejor, ratio = nombre, 0.0
    for n, c in NOMBRES_MLB.items():
        s = SequenceMatcher(None, nombre.lower(), n.lower()).ratio()
        if s > ratio:
            mejor, ratio = c, s
    return mejor if ratio >= 0.6 else nombre


class MLBEngine(BaseSportsEngine):
    def __init__(self):
        super().__init__('MLB', CARPETA)
        self.estado = {}
        ruta = os.path.join(CARPETA, 'estado.json')
        if os.path.exists(ruta):
            with open(ruta, encoding='utf-8') as f:
                self.estado = json.load(f)
        self.equipos = sorted((self.estado.get('equipos') or {}).keys())

    def cargar_datos_historicos(self) -> pd.DataFrame:
        import retrosheet_scraper
        import datetime
        y = datetime.date.today().year
        return retrosheet_scraper.actualizar(list(range(y - 5, y + 1)))

    # ---- construcción de features sin fuga (train + estado final) -------
    @staticmethod
    def _dataset(df: pd.DataFrame):
        df = df.sort_values('date').reset_index(drop=True)
        elo: Dict[str, float] = {}
        rs: Dict[str, list] = {}      # runs scored recientes
        ra: Dict[str, list] = {}      # runs allowed recientes
        streak: Dict[str, int] = {}
        ult_fecha: Dict[str, pd.Timestamp] = {}
        pit_ra: Dict[str, list] = {}  # carreras permitidas por apertura
        X, y, tot, fechas = [], [], [], []
        for r in df.itertuples(index=False):
            h, a = r.home_team, r.away_team
            eh, ea = elo.get(h, 1500.0), elo.get(a, 1500.0)
            def _m(d, k, dv):
                v = d.get(k, [])
                return np.mean(v[-MA:]) if v else dv
            rs_h, rs_a = _m(rs, h, 4.5), _m(rs, a, 4.5)
            ra_h, ra_a = _m(ra, h, 4.5), _m(ra, a, 4.5)
            rest_h = min((r.date - ult_fecha[h]).days, 7) if h in ult_fecha else 3
            rest_a = min((r.date - ult_fecha[a]).days, 7) if a in ult_fecha else 3
            pr_h = np.mean(pit_ra.get(r.home_pitcher, [])[-5:]) \
                if pit_ra.get(r.home_pitcher) else 4.5
            pr_a = np.mean(pit_ra.get(r.away_pitcher, [])[-5:]) \
                if pit_ra.get(r.away_pitcher) else 4.5
            if all(len(rs.get(t, [])) >= 5 for t in (h, a)):
                X.append([(eh - ea) / 100.0, (rs_h - rs_a) / 3.0,
                          (ra_h - ra_a) / 3.0,
                          (streak.get(h, 0) - streak.get(a, 0)) / 5.0,
                          (rest_h - rest_a) / 5.0, (pr_h - pr_a) / 3.0,
                          (rs_h + rs_a) / 9.0, (ra_h + ra_a) / 9.0,
                          (pr_h + pr_a) / 9.0])
                y.append(int(r.home_runs > r.away_runs))
                tot.append(r.home_runs + r.away_runs)
                fechas.append(r.date)
            # actualizar estado (sin fuga: después de emitir)
            gh, ga = float(r.home_runs), float(r.away_runs)
            rs.setdefault(h, []).append(gh); ra.setdefault(h, []).append(ga)
            rs.setdefault(a, []).append(ga); ra.setdefault(a, []).append(gh)
            pit_ra.setdefault(r.home_pitcher, []).append(ga)
            pit_ra.setdefault(r.away_pitcher, []).append(gh)
            for eq, gano in ((h, gh > ga), (a, ga > gh)):
                streak[eq] = max(streak.get(eq, 0), 0) + 1 if gano else \
                    min(streak.get(eq, 0), 0) - 1
            e_h = 1 / (1 + 10 ** ((ea - eh) / 400))
            s_h = 1.0 if gh > ga else 0.0
            elo[h] = eh + 20 * (s_h - e_h)
            elo[a] = ea + 20 * ((1 - s_h) - (1 - e_h))
            ult_fecha[h] = ult_fecha[a] = r.date
        estado = {'equipos': {}, 'pitchers': {}}
        for t in set(list(rs) + list(ra)):
            estado['equipos'][t] = {
                'elo': round(elo.get(t, 1500), 1),
                'rs': [round(x, 2) for x in rs.get(t, [])[-MA:]],
                'ra': [round(x, 2) for x in ra.get(t, [])[-MA:]],
                'streak': int(streak.get(t, 0)),
                'ult_fecha': ult_fecha[t].strftime('%Y-%m-%d') if t in ult_fecha else None}
        for p, v in pit_ra.items():
            estado['pitchers'][p] = [round(x, 2) for x in v[-5:]]
        return (np.array(X), np.array(y), np.array(tot),
                pd.Series(fechas), estado)

    def entrenar(self) -> Dict:
        from sklearn.calibration import CalibratedClassifierCV
        from sklearn.ensemble import (HistGradientBoostingRegressor,
                                      RandomForestClassifier, VotingClassifier)
        from sklearn.linear_model import LogisticRegression
        from sklearn.metrics import accuracy_score, log_loss
        from sklearn.preprocessing import StandardScaler
        from lightgbm import LGBMClassifier
        from xgboost import XGBClassifier

        df = self.cargar_datos_historicos()
        X, y, tot, fechas, estado = self._dataset(df)
        logger.info(f"[mlb] dataset: {len(X)} juegos utilizables")
        corte = fechas.quantile(0.80)
        m_tr = (fechas < corte).values
        sc = StandardScaler().fit(X[m_tr])
        Xtr, Xva = sc.transform(X[m_tr]), sc.transform(X[~m_tr])

        def _ens():
            vc = VotingClassifier([
                ('xgb', XGBClassifier(n_estimators=200, max_depth=4,
                                      learning_rate=0.05, verbosity=0)),
                ('lgbm', LGBMClassifier(n_estimators=200, max_depth=4,
                                        learning_rate=0.05, verbose=-1)),
                ('rf', RandomForestClassifier(n_estimators=200, max_depth=8,
                                              random_state=42))], voting='soft')
            return CalibratedClassifierCV(vc, method='isotonic', cv=3)
        modelo = _ens().fit(Xtr, y[m_tr])
        proba = modelo.predict_proba(Xva)[:, list(modelo.classes_).index(1)]
        pred = (proba >= 0.5).astype(int)
        acc = accuracy_score(y[~m_tr], pred)
        ll = log_loss(y[~m_tr], np.column_stack([1 - proba, proba]))
        base = accuracy_score(y[~m_tr], (X[~m_tr][:, 0] > 0).astype(int))  # ELO

        reg = HistGradientBoostingRegressor(loss='poisson', max_iter=300,
                                            learning_rate=0.05, max_depth=5,
                                            random_state=42).fit(Xtr, tot[m_tr])

        os.makedirs(CARPETA, exist_ok=True)
        import joblib
        joblib.dump(modelo, os.path.join(CARPETA, 'moneyline.joblib'), compress=3)
        joblib.dump(sc, os.path.join(CARPETA, 'scaler.joblib'), compress=3)
        joblib.dump(reg, os.path.join(CARPETA, 'totales.joblib'), compress=3)
        with open(os.path.join(CARPETA, 'estado.json'), 'w', encoding='utf-8') as f:
            json.dump(estado, f)
        meta = {'deporte': 'MLB', 'n_juegos': len(X),
                'precision_validacion': round(float(acc), 4),
                'precision_linea_base_elo': round(float(base), 4),
                'log_loss_validacion': round(float(ll), 4),
                'linea_total_tipica': float(np.median(tot)),
                'fecha_entrenamiento': pd.Timestamp.today().strftime('%Y-%m-%d')}
        with open(os.path.join(CARPETA, 'metadata.json'), 'w', encoding='utf-8') as f:
            json.dump(meta, f, indent=2)
        logger.info(f"[mlb] acc={acc:.4f} (ELO {base:.4f}) ll={ll:.4f}")
        return meta

    def construir_features(self, home: str, away: str,
                           home_pitcher: str = None,
                           away_pitcher: str = None, **ctx) -> Optional[List[float]]:
        eq = self.estado.get('equipos', {})
        if home not in eq or away not in eq:
            return None
        pit = self.estado.get('pitchers', {})
        h, a = eq[home], eq[away]
        rs_h = np.mean(h['rs']) if h['rs'] else 4.5
        rs_a = np.mean(a['rs']) if a['rs'] else 4.5
        ra_h = np.mean(h['ra']) if h['ra'] else 4.5
        ra_a = np.mean(a['ra']) if a['ra'] else 4.5
        pr_h = np.mean(pit.get(home_pitcher, [])[-5:]) if pit.get(home_pitcher) else 4.5
        pr_a = np.mean(pit.get(away_pitcher, [])[-5:]) if pit.get(away_pitcher) else 4.5
        return [(h['elo'] - a['elo']) / 100.0, (rs_h - rs_a) / 3.0,
                (ra_h - ra_a) / 3.0, (h['streak'] - a['streak']) / 5.0,
                0.0, (pr_h - pr_a) / 3.0, (rs_h + rs_a) / 9.0,
                (ra_h + ra_a) / 9.0, (pr_h + pr_a) / 9.0]


    def apuestas_dia(self, min_prob: float = 0.58, min_ev: float = 0.03,
                     min_cuota: float = 1.50, max_req: int = 1) -> Dict:
        """Picks MLB desde The Odds API (baseball_mlb) en vivo (§4)."""
        import odds_api
        k = odds_api._clave()
        if not k or not self.listo:
            return {'picks': [], 'aviso': 'Sin clave de API o modelo MLB.'}
        if not odds_api._presupuesto_disponible():
            return {'picks': [], 'aviso': 'Presupuesto de API agotado hoy.'}
        import requests
        odds_api._consumir_request()
        try:
            # v46: us,eu para incluir Pinnacle (referencia sharp) y más casas
            # (line shopping — mejor precio). Cuesta 1 crédito más pero MLB es
            # 1 llamada/día y aporta el edge más transferible.
            r = requests.get(f'{odds_api.BASE}/sports/baseball_mlb/odds',
                             params={'apiKey': k, 'regions': 'us,eu',
                                     'markets': 'h2h', 'oddsFormat': 'decimal'},
                             timeout=30)
            r.raise_for_status()
            odds_api._registrar_restantes(r)
        except Exception as e:
            return {'picks': [], 'aviso': f'The Odds API MLB no disponible: {e}'}
        picks = []
        for ev in r.json():
            hc = codigo_mlb(ev['home_team'])
            ac = codigo_mlb(ev['away_team'])
            pred = self.predecir(hc, ac)
            if 'error' in pred:
                continue
            # v46: mejor precio + casa + Pinnacle por selección
            precios = odds_api.extraer_precios(ev, 'h2h')
            for lado, cod, prob in (('home', hc, pred['prob_home']),
                                    ('away', ac, pred['prob_away'])):
                nombre = ev['home_team'] if lado == 'home' else ev['away_team']
                otro = ev['away_team'] if lado == 'home' else ev['home_team']
                info = precios.get(nombre)
                if not info:
                    continue
                cuota = info['cuota']
                ev_val = self.calcular_ev(prob, float(cuota))
                if prob > min_prob and ev_val > min_ev and float(cuota) > min_cuota:
                    # v46: confirmación sharp (modelo vs devig de Pinnacle)
                    gap = odds_api.sharp_gap_2via(
                        prob, info.get('pin'), (precios.get(otro) or {}).get('pin'))
                    pick = {
                        'deporte': 'MLB',
                        'partido': f"{CODIGO_A_NOMBRE.get(ac, ac)} @ "
                                   f"{CODIGO_A_NOMBRE.get(hc, hc)}",
                        'fecha': str(pd.to_datetime(ev['commence_time']).date()),
                        'apuesta': f"Gana {nombre}", 'prob': round(prob, 3),
                        'cuota': round(float(cuota), 2),
                        'cuota_justa': round(1 / max(prob, 1e-6), 2),
                        'ev': ev_val, 'casa': info.get('casa'),
                        'valor': '🟢' if ev_val > 0.05 else '🟡'}
                    if gap is not None:
                        pick['sharp_gap'] = round(gap, 4)
                        # v46 GUARDARRAÍL: la confirmación sharp solo cuenta en
                        # picks razonablemente probables (prob≥0.52). En
                        # underdogs el modelo tiende a sobreconfiar y el gap es
                        # espurio (la trampa de EV extremo, no valor real).
                        pick['sharp_confirmado'] = bool(gap >= 0.03 and prob >= 0.52)
                    picks.append(pick)
        # los confirmados por el sharp primero (más valor)
        picks.sort(key=lambda p: (-int(p.get('sharp_confirmado', False)), -p['ev']))
        return {'picks': picks, 'eventos': len(r.json()),
                'aviso': None if picks else
                'Sin picks MLB con EV suficiente hoy (o fuera de horario de juego).'}


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    print(json.dumps(MLBEngine().entrenar(), indent=2))
