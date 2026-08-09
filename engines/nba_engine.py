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


class _BlendEloNBA:
    """
    v70 — mezcla convexa del ensemble NBA con una logística sobre DIFF_ELO.

    El peso se elige minimizando log-loss en el último 25 % del train, un tramo
    que ninguno de los dos modelos ha visto; jamás se mira la validación. Con
    w=1 es el ensemble de siempre, con w=0 el ELO calibrado, así que la familia
    contiene al modelo anterior y no puede quedarse por debajo en el ajuste.
    """

    def __init__(self):
        self.ensemble = None
        self.elo = None
        self.w = 0.5
        self.classes_ = np.array([0, 1])

    @staticmethod
    def _ensamble():
        from sklearn.calibration import CalibratedClassifierCV
        from sklearn.ensemble import RandomForestClassifier, VotingClassifier
        from lightgbm import LGBMClassifier
        from xgboost import XGBClassifier
        vc = VotingClassifier([
            ('xgb', XGBClassifier(n_estimators=200, max_depth=4,
                                  learning_rate=0.05, verbosity=0)),
            ('lgbm', LGBMClassifier(n_estimators=200, max_depth=4,
                                    learning_rate=0.05, verbose=-1)),
            ('rf', RandomForestClassifier(n_estimators=200, max_depth=8,
                                          random_state=42))], voting='soft')
        return CalibratedClassifierCV(vc, method='isotonic', cv=3)

    @staticmethod
    def _logistica():
        from sklearn.linear_model import LogisticRegressionCV
        from sklearn.model_selection import TimeSeriesSplit
        return LogisticRegressionCV(
            Cs=np.logspace(-3, 2, 10), cv=TimeSeriesSplit(n_splits=3),
            penalty='l2', solver='lbfgs', max_iter=3000,
            scoring='neg_log_loss', n_jobs=-1, random_state=42)

    @staticmethod
    def _p1(modelo, X):
        return modelo.predict_proba(X)[:, list(modelo.classes_).index(1)]

    def fit(self, X, y):
        from sklearn.metrics import log_loss
        X, y = np.asarray(X), np.asarray(y)
        corte = int(len(X) * 0.75)
        if corte > 200 and len(np.unique(y[:corte])) == 2:
            e_i = self._ensamble().fit(X[:corte], y[:corte])
            l_i = self._logistica().fit(X[:corte, [0]], y[:corte])
            pa = self._p1(e_i, X[corte:])
            pe = self._p1(l_i, X[corte:, [0]])
            mejor_w, mejor_ll = 0.5, np.inf
            for w in np.linspace(0.0, 1.0, 11):
                pw = np.clip(w * pa + (1 - w) * pe, 1e-6, 1 - 1e-6)
                ll = log_loss(y[corte:], np.column_stack([1 - pw, pw]))
                if ll < mejor_ll:
                    mejor_ll, mejor_w = ll, float(w)
            self.w = mejor_w
        self.ensemble = self._ensamble().fit(X, y)
        self.elo = self._logistica().fit(X[:, [0]], y)
        self.classes_ = np.array([0, 1])
        logger.info(f"[nba] blend ensemble/ELO con w={self.w:.2f}")
        return self

    def predict_proba(self, X):
        X = np.asarray(X)
        p = np.clip(self.w * self._p1(self.ensemble, X)
                    + (1 - self.w) * self._p1(self.elo, X[:, [0]]), 1e-6, 1 - 1e-6)
        return np.column_stack([1 - p, p])

    def predict(self, X):
        return (self.predict_proba(X)[:, 1] >= 0.5).astype(int)


def _registrar_en_main() -> None:
    """
    v106 — EL MODELO DE NBA NO CARGABA EN NINGÚN SITIO, NI EN PRODUCCIÓN.

        AttributeError: Can't get attribute '_BlendEloNBA'
                        on <module '__main__'>

    La causa es de `pickle`, no del modelo: el entrenamiento se lanza con
    `python -m engines.nba_engine` (así lo hace el workflow diario), y en esa
    ejecución este fichero ES `__main__`. Pickle guarda la clase por su
    módulo, así que el artefacto quedó apuntando a `__main__._BlendEloNBA`.
    Al cargarlo desde la app, `__main__` es Streamlit y allí esa clase no
    existe — falla igual en Windows, en Linux y en el runner.

    Se descubrió al cablear el EV+ automático de la NBA (v106): la vista decía
    «Motor NBA no disponible» y el motivo llevaba versiones escondido detrás
    de que la NBA está fuera de temporada de junio a octubre.

    Esto registra la clase en `__main__` ANTES de deserializar, que repara el
    artefacto que ya está publicado sin tener que reentrenar (el
    reentrenamiento depende de `nba_api`, que fuera de temporada no aporta
    datos nuevos). El bloque `__main__` de abajo, además, evita que el
    problema se reproduzca en el próximo entrenamiento.
    """
    import sys
    principal = sys.modules.get('__main__')
    if principal is not None and not hasattr(principal, '_BlendEloNBA'):
        setattr(principal, '_BlendEloNBA', _BlendEloNBA)


class NBAEngine(BaseSportsEngine):
    def __init__(self):
        super().__init__('NBA', CARPETA)
        self.estado = {}
        ruta = os.path.join(CARPETA, 'estado.json')
        if os.path.exists(ruta):
            with open(ruta, encoding='utf-8') as f:
                self.estado = json.load(f)
        self.equipos = sorted((self.estado.get('equipos') or {}).keys())

    def cargar_modelo(self):
        # v106: repara la referencia a `__main__._BlendEloNBA` del artefacto ya
        # publicado antes de deserializar. Ver `_registrar_en_main`.
        _registrar_en_main()
        return super().cargar_modelo()

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
        # v70 (Mejora F): el ensemble de 9 features SOBREAJUSTA. Medido en
        # walk-forward de 5 pliegues sobre 6.062 juegos limpios, una logística
        # con UN SOLO grado de libertad (DIFF_ELO) lo bate en las tres métricas
        # —0.6668 contra 0.6544 de precisión, log-loss 0.6163 contra 0.6214,
        # ECE 0.0170 contra 0.0205— y encima supera al argmax del ELO (0.6627),
        # que el ensemble no superaba. La mezcla convexa de ambos, con el peso
        # ajustado en un tramo interno del train, da el mejor log-loss (0.6157)
        # y además se autocorrige: si el ensemble mejora cuando llegue la
        # temporada 2026-27, el peso se desplazará solo.
        modelo = _BlendEloNBA().fit(sc.transform(X[m_tr]), y[m_tr])
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
                'familia_modelo': 'blend_elo',
                'peso_ensemble': round(float(getattr(modelo, 'w', 1.0)), 2),
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
    # v106 — SE ENTRENA CON LA CLASE DEL PAQUETE, NO CON LA DE `__main__`.
    #
    # `python -m engines.nba_engine` ejecuta este fichero como `__main__`, así
    # que `_BlendEloNBA` se pickleaba como `__main__._BlendEloNBA` y el
    # artefacto no se podía cargar desde la app (ver `_registrar_en_main`).
    # Reimportando el módulo por su nombre real, la clase que se serializa es
    # `engines.nba_engine._BlendEloNBA` y el modelo carga desde cualquier sitio.
    #
    # No basta con arreglar la carga: si el próximo reentrenamiento vuelve a
    # escribirlo mal, el parche de compatibilidad seguiría tapándolo para
    # siempre en vez de resolverlo.
    from engines.nba_engine import NBAEngine as _NBAEngine
    print(json.dumps(_NBAEngine().entrenar(), indent=2))
