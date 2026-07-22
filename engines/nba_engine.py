#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NBAEngine (v30 §4) — baloncesto, hereda de BaseSportsEngine.

Fuente: nba_api (game logs oficiales, 6.1k juegos 2021-26). Binario (sin
empate). Features pre-partido sin fuga: ELO, OFF/DEF rating (puntos por 100
posesiones, MA5), pace, net rating, back-to-back, descanso, racha, + CDI
(husos cruzados por el visitante). El Odds API no tiene NBA en temporada
julio → modo analítico hasta octubre 2026 (§4.4).
"""

import json
import logging
import os
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

import cdi as cdi_mod
from engines.base_engine import BaseSportsEngine

logger = logging.getLogger(__name__)

MA = 5
CARPETA = os.path.join('modelos', 'nba')
FEATURES = ['DIFF_ELO', 'DIFF_OFF', 'DIFF_DEF', 'DIFF_NET', 'DIFF_PACE',
            'DIFF_REST', 'DIFF_B2B', 'DIFF_STREAK', 'CDI_VIS']


class NBAEngine(BaseSportsEngine):
    def __init__(self):
        super().__init__('NBA', CARPETA)
        self.estado = {}
        ruta = os.path.join(CARPETA, 'estado.json')
        if os.path.exists(ruta):
            with open(ruta, encoding='utf-8') as f:
                self.estado = json.load(f)
        self.equipos = sorted((self.estado.get('equipos') or {}).keys())

    def cargar_datos_historicos(self) -> pd.DataFrame:
        import nba_scraper
        return nba_scraper.actualizar(['2021-22', '2022-23', '2023-24',
                                       '2024-25', '2025-26'])

    @staticmethod
    def _dataset(df: pd.DataFrame, con_cdi: bool = True):
        df = df.sort_values('date').reset_index(drop=True)
        elo, off, dfn, pace, streak, ultf, ultsede, cnt = {}, {}, {}, {}, {}, {}, {}, {}
        X, y, tot, fechas = [], [], [], []
        for r in df.itertuples(index=False):
            h, a = r.home_team, r.away_team
            eh, ea = elo.get(h, 1500.0), elo.get(a, 1500.0)
            def _m(d, k, dv):
                v = d.get(k, [])
                return np.mean(v[-MA:]) if v else dv
            oh, oa = _m(off, h, 112), _m(off, a, 112)
            dh, da = _m(dfn, h, 112), _m(dfn, a, 112)
            ph, pa = _m(pace, h, 99), _m(pace, a, 99)
            rest_h = min((r.date - ultf[h]).days, 5) if h in ultf else 3
            rest_a = min((r.date - ultf[a]).days, 5) if a in ultf else 3
            b2b_h = 1.0 if h in ultf and (r.date - ultf[h]).days <= 1 else 0.0
            b2b_a = 1.0 if a in ultf and (r.date - ultf[a]).days <= 1 else 0.0
            prev_a = ultsede.get(a)
            reciente = a in ultf and (r.date - ultf[a]).days <= 4
            tz_prev = cdi_mod.TZ_NBA.get(prev_a) if (prev_a and reciente) else None
            cdi_vis = cdi_mod.cdi_desde_offsets(tz_prev, cdi_mod.TZ_NBA.get(h, -5))
            if all(cnt.get(t, 0) >= 5 for t in (h, a)):
                fila = [(eh - ea) / 100.0, (oh - oa) / 10.0, (dh - da) / 10.0,
                        ((oh - dh) - (oa - da)) / 10.0, (ph - pa) / 10.0,
                        (rest_h - rest_a) / 3.0, b2b_h - b2b_a,
                        (streak.get(h, 0) - streak.get(a, 0)) / 5.0]
                if con_cdi:
                    fila.append(cdi_vis)
                X.append(fila)
                y.append(int(r.home_pts > r.away_pts))
                tot.append(r.home_pts + r.away_pts)
                fechas.append(r.date)
            # actualizar estado
            posh = max(r.home_poss, 50); posa = max(r.away_poss, 50)
            off.setdefault(h, []).append(r.home_pts / posh * 100)
            dfn.setdefault(h, []).append(r.away_pts / posa * 100)
            off.setdefault(a, []).append(r.away_pts / posa * 100)
            dfn.setdefault(a, []).append(r.home_pts / posh * 100)
            pace.setdefault(h, []).append(posh); pace.setdefault(a, []).append(posa)
            for eq, gano in ((h, r.home_pts > r.away_pts), (a, r.away_pts > r.home_pts)):
                streak[eq] = max(streak.get(eq, 0), 0) + 1 if gano else min(streak.get(eq, 0), 0) - 1
                cnt[eq] = cnt.get(eq, 0) + 1
            e_h = 1 / (1 + 10 ** ((ea - eh) / 400))
            s_h = 1.0 if r.home_pts > r.away_pts else 0.0
            elo[h] = eh + 20 * (s_h - e_h); elo[a] = ea + 20 * ((1 - s_h) - (1 - e_h))
            ultf[h] = ultf[a] = r.date
            ultsede[h] = ultsede[a] = h
        estado = {'equipos': {}}
        for t in cnt:
            estado['equipos'][t] = {
                'elo': round(elo.get(t, 1500), 1),
                'off': [round(x, 1) for x in off.get(t, [])[-MA:]],
                'def': [round(x, 1) for x in dfn.get(t, [])[-MA:]],
                'pace': [round(x, 1) for x in pace.get(t, [])[-MA:]],
                'streak': int(streak.get(t, 0)),
                'ult_fecha': ultf[t].strftime('%Y-%m-%d') if t in ultf else None}
        return np.array(X), np.array(y), np.array(tot), pd.Series(fechas), estado

    def entrenar(self, con_cdi: bool = True) -> Dict:
        from sklearn.calibration import CalibratedClassifierCV
        from sklearn.ensemble import (HistGradientBoostingRegressor,
                                      RandomForestClassifier, VotingClassifier)
        from sklearn.metrics import accuracy_score, log_loss
        from sklearn.preprocessing import StandardScaler
        from lightgbm import LGBMClassifier
        from xgboost import XGBClassifier

        df = self.cargar_datos_historicos()
        X, y, tot, fechas, estado = self._dataset(df, con_cdi=con_cdi)
        logger.info(f"[nba] dataset: {len(X)} juegos (cdi={con_cdi})")
        corte = fechas.quantile(0.80)
        m_tr = (fechas < corte).values
        sc = StandardScaler().fit(X[m_tr])
        vc = VotingClassifier([
            ('xgb', XGBClassifier(n_estimators=200, max_depth=4, learning_rate=0.05, verbosity=0)),
            ('lgbm', LGBMClassifier(n_estimators=200, max_depth=4, learning_rate=0.05, verbose=-1)),
            ('rf', RandomForestClassifier(n_estimators=200, max_depth=8, random_state=42))], voting='soft')
        modelo = CalibratedClassifierCV(vc, method='isotonic', cv=3).fit(sc.transform(X[m_tr]), y[m_tr])
        proba = modelo.predict_proba(sc.transform(X[~m_tr]))[:, list(modelo.classes_).index(1)]
        acc = accuracy_score(y[~m_tr], (proba >= 0.5).astype(int))
        ll = log_loss(y[~m_tr], np.column_stack([1 - proba, proba]))
        base = accuracy_score(y[~m_tr], (X[~m_tr][:, 0] > 0).astype(int))
        reg = HistGradientBoostingRegressor(loss='poisson', max_iter=300, learning_rate=0.05,
                                            max_depth=5, random_state=42).fit(sc.transform(X[m_tr]), tot[m_tr])
        os.makedirs(CARPETA, exist_ok=True)
        import joblib
        joblib.dump(modelo, os.path.join(CARPETA, 'moneyline.joblib'), compress=3)
        joblib.dump(sc, os.path.join(CARPETA, 'scaler.joblib'), compress=3)
        joblib.dump(reg, os.path.join(CARPETA, 'totales.joblib'), compress=3)
        with open(os.path.join(CARPETA, 'estado.json'), 'w', encoding='utf-8') as f:
            json.dump(estado, f)
        meta = {'deporte': 'NBA', 'n_juegos': len(X), 'con_cdi': con_cdi,
                'precision_validacion': round(float(acc), 4),
                'precision_linea_base_elo': round(float(base), 4),
                'log_loss_validacion': round(float(ll), 4),
                'linea_total_tipica': float(np.median(tot)),
                'modo': 'analitico hasta temporada 2026-27 (Odds API sin NBA en julio)',
                'fecha_entrenamiento': pd.Timestamp.today().strftime('%Y-%m-%d')}
        with open(os.path.join(CARPETA, 'metadata.json'), 'w', encoding='utf-8') as f:
            json.dump(meta, f, indent=2)
        logger.info(f"[nba] acc={acc:.4f} (ELO {base:.4f}) ll={ll:.4f}")
        return meta

    def construir_features(self, home: str, away: str, **ctx) -> Optional[List[float]]:
        eq = self.estado.get('equipos', {})
        if home not in eq or away not in eq:
            return None
        h, a = eq[home], eq[away]
        def _m(v, dv):
            return np.mean(v) if v else dv
        oh, oa = _m(h['off'], 112), _m(a['off'], 112)
        dh, da = _m(h['def'], 112), _m(a['def'], 112)
        ph, pa = _m(h['pace'], 99), _m(a['pace'], 99)
        return [(h['elo'] - a['elo']) / 100.0, (oh - oa) / 10.0, (dh - da) / 10.0,
                ((oh - dh) - (oa - da)) / 10.0, (ph - pa) / 10.0, 0.0, 0.0,
                (h['streak'] - a['streak']) / 5.0, 0.0]


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    print(json.dumps(NBAEngine().entrenar(), indent=2))
