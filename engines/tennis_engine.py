#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TennisEngine (v30 §5) — ATP, hereda de BaseSportsEngine.

Fuente: dataset Kaggle (dissfya/atp-tennis-2000-2023daily-pull, 68k partidos
2000-2026, con superficie Y cuotas de cierre Odd_1/Odd_2 — permite validar
contra el MERCADO, no solo el ranking). Binario: gana Player_1 sí/no.

Feature principal: ELO POR SUPERFICIE (clay/hard/grass), calculado
cronológicamente. Más ELO global, ranking, forma reciente y H2H.
Modo ANALÍTICO: The Odds API no tiene tenis en la capa gratuita, así que en
vivo se generan cuotas justas (sin EV real) — pero el backtest sí usa las
cuotas del dataset como línea base de mercado.
"""

import json
import logging
import os
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from engines.base_engine import BaseSportsEngine

logger = logging.getLogger(__name__)

CARPETA = os.path.join('modelos', 'tennis')
DATASET = 'dissfya/atp-tennis-2000-2023daily-pull'
FEATURES = ['DIFF_ELO_SUP', 'DIFF_ELO_GLOBAL', 'DIFF_RANK_LOG',
            'DIFF_FORMA10', 'DIFF_WIN_SUP_12M', 'H2H']
SUP = {'Clay': 'clay', 'Hard': 'hard', 'Grass': 'grass',
       'Carpet': 'hard', 'Indoor': 'hard'}


class TennisEngine(BaseSportsEngine):
    def __init__(self):
        super().__init__('Tenis', CARPETA)
        self.estado = {}
        ruta = os.path.join(CARPETA, 'estado.json')
        if os.path.exists(ruta):
            with open(ruta, encoding='utf-8') as f:
                self.estado = json.load(f)
        self.jugadores = sorted((self.estado.get('jugadores') or {}).keys())

    def cargar_datos_historicos(self) -> pd.DataFrame:
        import kagglehub
        p = kagglehub.dataset_download(DATASET)
        df = pd.read_csv(os.path.join(p, 'atp_tennis.csv'), parse_dates=['Date'])
        df['sup'] = df['Surface'].map(lambda s: SUP.get(str(s), 'hard'))
        return df.dropna(subset=['Player_1', 'Player_2', 'Winner']).sort_values('Date')

    @staticmethod
    def _dataset(df: pd.DataFrame):
        elo_g: Dict[str, float] = {}
        elo_s: Dict[str, Dict[str, float]] = {}
        forma: Dict[str, list] = {}
        win_sup: Dict[str, list] = {}     # (fecha, ganó) por superficie
        h2h: Dict[tuple, int] = {}
        X, y, fechas, odds = [], [], [], []
        for r in df.itertuples(index=False):
            p1, p2, sup = r.Player_1, r.Player_2, r.sup
            eg1, eg2 = elo_g.get(p1, 1500.0), elo_g.get(p2, 1500.0)
            es1 = elo_s.get(p1, {}).get(sup, 1500.0)
            es2 = elo_s.get(p2, {}).get(sup, 1500.0)
            f1 = np.mean(forma.get(p1, [])[-10:]) if forma.get(p1) else 0.5
            f2 = np.mean(forma.get(p2, [])[-10:]) if forma.get(p2) else 0.5
            def _ws(p):
                v = [g for (d, s, g) in win_sup.get(p, [])
                     if s == sup and (r.Date - d).days <= 365]
                return np.mean(v) if v else 0.5
            ws1, ws2 = _ws(p1), _ws(p2)
            hk = tuple(sorted((p1, p2)))
            hb = h2h.get(hk, 0) * (1 if hk[0] == p1 else -1)
            r1 = float(r.Rank_1) if r.Rank_1 and r.Rank_1 > 0 else 500
            r2 = float(r.Rank_2) if r.Rank_2 and r.Rank_2 > 0 else 500
            gano1 = int(r.Winner == p1)
            if p1 in elo_g and p2 in elo_g:   # ambos con historial
                X.append([(es1 - es2) / 100.0, (eg1 - eg2) / 100.0,
                          (np.log(r2) - np.log(r1)) / 3.0, f1 - f2,
                          ws1 - ws2, float(np.clip(hb, -5, 5)) / 5.0])
                y.append(gano1)
                fechas.append(r.Date)
                odds.append((getattr(r, 'Odd_1', None), getattr(r, 'Odd_2', None)))
            # actualizar (sin fuga)
            exp1 = 1 / (1 + 10 ** ((eg2 - eg1) / 400))
            elo_g[p1] = eg1 + 32 * (gano1 - exp1)
            elo_g[p2] = eg2 + 32 * ((1 - gano1) - (1 - exp1))
            exps = 1 / (1 + 10 ** ((es2 - es1) / 400))
            elo_s.setdefault(p1, {})[sup] = es1 + 32 * (gano1 - exps)
            elo_s.setdefault(p2, {})[sup] = es2 + 32 * ((1 - gano1) - (1 - exps))
            forma.setdefault(p1, []).append(gano1)
            forma.setdefault(p2, []).append(1 - gano1)
            win_sup.setdefault(p1, []).append((r.Date, sup, gano1))
            win_sup.setdefault(p2, []).append((r.Date, sup, 1 - gano1))
            h2h[hk] = h2h.get(hk, 0) + (1 if r.Winner == hk[0] else -1)
        estado = {'jugadores': {}}
        for p in elo_g:
            estado['jugadores'][p] = {
                'elo': round(elo_g[p], 1),
                'elo_sup': {k: round(v, 1) for k, v in elo_s.get(p, {}).items()},
                'forma': [int(x) for x in forma.get(p, [])[-10:]],
                'rank': None}
        # ranking más reciente por jugador
        for r in df.itertuples(index=False):
            if r.Player_1 in estado['jugadores'] and r.Rank_1:
                estado['jugadores'][r.Player_1]['rank'] = float(r.Rank_1)
            if r.Player_2 in estado['jugadores'] and r.Rank_2:
                estado['jugadores'][r.Player_2]['rank'] = float(r.Rank_2)
        estado['h2h'] = {f'{a}|{b}': v for (a, b), v in h2h.items() if v != 0}
        return (np.array(X), np.array(y), pd.Series(fechas),
                np.array(odds, dtype=float), estado)

    def entrenar(self) -> Dict:
        from sklearn.calibration import CalibratedClassifierCV
        from sklearn.ensemble import RandomForestClassifier, VotingClassifier
        from sklearn.metrics import accuracy_score, log_loss
        from sklearn.preprocessing import StandardScaler
        from lightgbm import LGBMClassifier
        from xgboost import XGBClassifier

        df = self.cargar_datos_historicos()
        X, y, fechas, odds, estado = self._dataset(df)
        logger.info(f"[tenis] dataset: {len(X)} partidos")
        corte = fechas.quantile(0.80)
        m_tr = (fechas < corte).values
        sc = StandardScaler().fit(X[m_tr])
        vc = VotingClassifier([
            ('xgb', XGBClassifier(n_estimators=200, max_depth=4, learning_rate=0.05, verbosity=0)),
            ('lgbm', LGBMClassifier(n_estimators=200, max_depth=4, learning_rate=0.05, verbose=-1)),
            ('rf', RandomForestClassifier(n_estimators=200, max_depth=8, random_state=42))],
            voting='soft')
        modelo = CalibratedClassifierCV(vc, method='isotonic', cv=3).fit(
            sc.transform(X[m_tr]), y[m_tr])
        proba = modelo.predict_proba(sc.transform(X[~m_tr]))[:, list(modelo.classes_).index(1)]
        acc = accuracy_score(y[~m_tr], (proba >= 0.5).astype(int))
        ll = log_loss(y[~m_tr], np.column_stack([1 - proba, proba]))
        # baseline mercado: favorito por cuota (menor odd)
        o = odds[~m_tr]
        mask = np.isfinite(o).all(axis=1)
        acc_mkt = accuracy_score(y[~m_tr][mask],
                                 (o[mask][:, 0] < o[mask][:, 1]).astype(int)) \
            if mask.sum() > 50 else None
        base = accuracy_score(y[~m_tr], (X[~m_tr][:, 0] > 0).astype(int))

        os.makedirs(CARPETA, exist_ok=True)
        import joblib
        joblib.dump(modelo, os.path.join(CARPETA, 'moneyline.joblib'), compress=3)
        joblib.dump(sc, os.path.join(CARPETA, 'scaler.joblib'), compress=3)
        with open(os.path.join(CARPETA, 'estado.json'), 'w', encoding='utf-8') as f:
            json.dump(estado, f)
        meta = {'deporte': 'Tenis (ATP)', 'n_partidos': len(X),
                'precision_validacion': round(float(acc), 4),
                'precision_linea_base_elo': round(float(base), 4),
                'precision_mercado': round(float(acc_mkt), 4) if acc_mkt else None,
                'log_loss_validacion': round(float(ll), 4),
                'modo': 'analitico (sin cuotas en vivo gratis)',
                'fecha_entrenamiento': pd.Timestamp.today().strftime('%Y-%m-%d')}
        with open(os.path.join(CARPETA, 'metadata.json'), 'w', encoding='utf-8') as f:
            json.dump(meta, f, indent=2)
        logger.info(f"[tenis] acc={acc:.4f} (ELO {base:.4f}, mercado {acc_mkt}) ll={ll:.4f}")
        return meta

    def construir_features(self, home: str, away: str,
                           surface: str = 'hard', **ctx) -> Optional[List[float]]:
        jug = self.estado.get('jugadores', {})
        if home not in jug or away not in jug:
            return None
        p1, p2 = jug[home], jug[away]
        sup = SUP.get(str(surface).capitalize(), str(surface).lower())
        es1 = p1['elo_sup'].get(sup, p1['elo'])
        es2 = p2['elo_sup'].get(sup, p2['elo'])
        f1 = np.mean(p1['forma']) if p1['forma'] else 0.5
        f2 = np.mean(p2['forma']) if p2['forma'] else 0.5
        r1 = p1.get('rank') or 500
        r2 = p2.get('rank') or 500
        hk = '|'.join(sorted((home, away)))
        hb = self.estado.get('h2h', {}).get(hk, 0)
        hb = hb if hk.split('|')[0] == home else -hb
        return [(es1 - es2) / 100.0, (p1['elo'] - p2['elo']) / 100.0,
                (np.log(r2) - np.log(r1)) / 3.0, f1 - f2, 0.0,
                float(np.clip(hb, -5, 5)) / 5.0]


    # ------------------------------------------------------------------
    # v32 (§8.1): plantilla de tenis con RESTRICCIÓN MATEMÁTICA ESTRICTA.
    # Solo lo derivable: ganador (clasificador), total de juegos y hándicap
    # (regresión de juegos calibrada sobre 68k partidos) y reparto de sets
    # bajo independencia condicional (asunción declarada, no inventada).
    # EXCLUIDOS: marcador exacto de sets, «set a cero» y ganador del primer
    # set — exigen cadenas de Markov / datos de saque que NO tenemos.
    # ------------------------------------------------------------------
    def plantilla(self, home: str, away: str, surface: str = 'Hard',
                  best_of: int = 3, **ctx) -> Dict:
        from scipy.stats import norm
        pred = self.predecir(home, away, surface=surface)
        if 'error' in pred:
            return pred
        p = pred['prob_home']
        md = self.metadata
        campos = [
            {'id': 'ml_home', 'etiqueta': f'Gana {home}', 'valor': p * 100},
            {'id': 'ml_away', 'etiqueta': f'Gana {away}', 'valor': (1 - p) * 100},
        ]
        # --- total de juegos ---
        coef = md.get('coef_juegos')
        sigma_j = md.get('sigma_juegos')
        total_juegos = None
        if coef and sigma_j:
            jug = self.estado.get('jugadores', {})
            r1 = (jug.get(home, {}).get('rank') or 100)
            r2 = (jug.get(away, {}).get('rank') or 100)
            gap = abs(np.log(max(r1, 1)) - np.log(max(r2, 1)))
            total_juegos = float(coef[0] + coef[1] * gap
                                 + coef[2] * (1.0 if best_of == 5 else 0.0))
            for l in (total_juegos - 2.5, total_juegos + 0.5, total_juegos + 3.5):
                l = round(l * 2) / 2
                p_over = float(1 - norm.cdf((l - total_juegos) / sigma_j))
                campos += [
                    {'id': f'juegos_over_{l}', 'etiqueta': f'Más de {l} juegos',
                     'valor': p_over * 100},
                    {'id': f'juegos_under_{l}', 'etiqueta': f'Menos de {l} juegos',
                     'valor': (1 - p_over) * 100},
                ]
        # --- hándicap de juegos (margen ~ N(μ, σ) con μ del favorito) ---
        sm = md.get('sigma_margen_juegos')
        mm = md.get('margen_juegos_medio')
        if sm and mm:
            # el favorito gana por mm de media; μ con signo según quién es
            mu = mm * (1 if p >= 0.5 else -1) * (2 * abs(p - 0.5) * 2)
            for h in (2.5, 4.5, 6.5):
                p_cubre = float(1 - norm.cdf((h - mu) / sm))
                campos += [
                    {'id': f'hand_home_{h}', 'etiqueta': f'{home} −{h} juegos',
                     'valor': p_cubre * 100},
                    {'id': f'hand_away_{h}', 'etiqueta': f'{away} +{h} juegos',
                     'valor': (1 - p_cubre) * 100},
                ]
        # --- sets: se invierte p → prob de ganar UN set (independencia) ---
        s = _prob_set_desde_partido(p, best_of)
        if best_of == 3:
            p20, p21 = s ** 2, 2 * s ** 2 * (1 - s)
            p_ambos = 1 - s ** 2 - (1 - s) ** 2
            campos += [
                {'id': 'set_2_0', 'etiqueta': f'{home} gana 2-0', 'valor': p20 * 100},
                {'id': 'set_2_1', 'etiqueta': f'{home} gana 2-1', 'valor': p21 * 100},
                {'id': 'ambos_set', 'etiqueta': 'Ambos ganan al menos un set',
                 'valor': p_ambos * 100},
                {'id': 'set_home', 'etiqueta': f'{home} gana al menos un set',
                 'valor': (1 - (1 - s) ** 2) * 100},
                {'id': 'set_away', 'etiqueta': f'{away} gana al menos un set',
                 'valor': (1 - s ** 2) * 100},
            ]
        return {'deporte': self.deporte, 'partido': f'{home} vs {away}',
                'superficie': surface, 'prediccion': pred,
                'total_juegos_estimado': (round(total_juegos, 1)
                                          if total_juegos else None),
                'campos': campos,
                'excluidos': md.get('mercados_excluidos', []),
                'nota': ('Sets bajo independencia condicional entre sets '
                         '(asunción declarada). Sin cuotas en vivo, las '
                         'cuotas son justas = 1/probabilidad.')}


def _prob_set_desde_partido(p_partido: float, best_of: int = 3) -> float:
    """Invierte numéricamente P(partido) → P(set) suponiendo sets i.i.d.
    bo3: P = s²(3−2s). Búsqueda binaria (monótona en s)."""
    p_partido = min(max(p_partido, 1e-4), 1 - 1e-4)
    lo, hi = 0.0, 1.0
    for _ in range(60):
        s = (lo + hi) / 2
        if best_of == 5:
            pm = s ** 3 * (1 + 3 * (1 - s) + 6 * (1 - s) ** 2)
        else:
            pm = s ** 2 * (3 - 2 * s)
        if pm < p_partido:
            lo = s
        else:
            hi = s
    return (lo + hi) / 2


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    print(json.dumps(TennisEngine().entrenar(), indent=2))
