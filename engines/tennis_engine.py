#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TennisEngine (v30 §5, ampliado en v35 §1) — ATP **y WTA**.

Fuentes (Kaggle, sin credenciales, actualizadas a diario):
  · ATP → dissfya/atp-tennis-2000-2023daily-pull (68.3k partidos 2000-2026)
  · WTA → dissfya/wta-tennis-2007-2023-daily-update (45.1k partidos
    2006-2026) — MISMAS columnas que el ATP, incluidas Odd_1/Odd_2 con
    100 % de cobertura, así que el circuito femenino también se valida
    contra el MERCADO y no solo contra el ranking.
Ambos con superficie, tipo de pista (Indoor/Outdoor), ranking, puntos y
marcador. Binario: gana Player_1 sí/no.

CHALLENGERS (v35 §1.2): NO se incorporan. El dataset de Challengers del
mismo autor devuelve 403 (privado) y el único mirror gratuito con
categorías inferiores (ehallmar/a-large-tennis-dataset...) está congelado
en 2018 → serviría para inflar el volumen de entrenamiento con partidos de
hace 8 años, no para predecir los de hoy. Documentado en VALIDACION_v35.md.

Features v35 (todas cronológicas, sin fuga):
  · ELO POR SUPERFICIE, ahora con pista INDOOR como superficie propia
    (hard_indoor ≠ hard): el bote y la ausencia de viento cambian el juego.
  · ELO global, ranking (log) y PUNTOS de ranking (log).
  · Forma últimos 10 y % de victorias en la superficie a 12 meses.
  · FATIGA: días desde el último partido, partidos en 14 días y horas en
    pista en 7 días (estimadas del marcador: ~3.75 min por juego).
  · H2H acumulado.
ELO de saque/resto: IMPOSIBLE con esta fuente (no publica aces, dobles
faltas ni puntos ganados al saque) → fallback al ELO global, exactamente
como prevé el propio spec §1.3.
"""

import json
import logging
import os
import re
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from engines.base_engine import BaseSportsEngine

logger = logging.getLogger(__name__)

CIRCUITOS = {
    # 'features': conjunto ADOPTADO tras el walk-forward de 5 temporadas
    # (run_wf_tenis_v35.py). En el ATP las features nuevas suben +0.25 pp
    # (64.98→65.23) — por debajo del umbral de 0.3 pp y con el log-loss
    # plano (+0.0005) → NO se adoptan y el circuito masculino conserva su
    # vector v30. En la WTA mejoran precisión Y log-loss (65.34→65.57,
    # 0.6164→0.6137) → adoptadas.
    'atp': {'carpeta': os.path.join('modelos', 'tennis'),
            'dataset': 'dissfya/atp-tennis-2000-2023daily-pull',
            'archivo': 'atp_tennis.csv', 'etiqueta': 'Tenis (ATP)',
            'features': None},          # None → FEATURES_V30 (ver abajo)
    'wta': {'carpeta': os.path.join('modelos', 'tennis_wta'),
            'dataset': 'dissfya/wta-tennis-2007-2023-daily-update',
            'archivo': 'wta.csv', 'etiqueta': 'Tenis (WTA)'},
}
CARPETA = CIRCUITOS['atp']['carpeta']          # compatibilidad v30-v34
DATASET = CIRCUITOS['atp']['dataset']
FEATURES = ['DIFF_ELO_SUP', 'DIFF_ELO_GLOBAL', 'DIFF_RANK_LOG',
            'DIFF_FORMA10', 'DIFF_WIN_SUP_12M', 'H2H',
            'DIFF_PTS_LOG', 'DIFF_DIAS_DESCANSO', 'DIFF_PARTIDOS_14D',
            'DIFF_HORAS_7D']
FEATURES_V30 = FEATURES[:6]                    # para el A/B de la v35
SUP = {'Clay': 'clay', 'Hard': 'hard', 'Grass': 'grass',
       'Carpet': 'hard', 'Indoor': 'hard', 'Greenset': 'hard'}
MIN_POR_JUEGO = 3.75 / 60.0                    # horas por juego disputado


def _juegos_del_marcador(score) -> float:
    """Juegos totales del partido a partir del marcador ('6-4 7-6(3)' → 23).
    Si no es parseable, se asume un partido medio (21 juegos)."""
    if not isinstance(score, str) or not score.strip():
        return 21.0
    total = 0
    for a, b in re.findall(r'(\d+)-(\d+)', score.replace('(', ' (')):
        ja, jb = int(a), int(b)
        if ja <= 7 and jb <= 7:                # descarta tie-breaks (7-3 sí, 10-8 no)
            total += ja + jb
    return float(total) if total else 21.0


class TennisEngine(BaseSportsEngine):
    def __init__(self, circuito: str = 'atp'):
        cfg = CIRCUITOS[circuito]
        self.circuito = circuito
        self.cfg = cfg
        super().__init__(cfg['etiqueta'], cfg['carpeta'])
        # Conjunto de features ADOPTADO por circuito (run_wf_tenis_v35.py);
        # se fija tras la validación walk-forward, no por defecto.
        self.features = list(cfg.get('features') or FEATURES_V30)             if 'features' in cfg else list(FEATURES)
        self.estado = {}
        ruta = os.path.join(cfg['carpeta'], 'estado.json')
        if os.path.exists(ruta):
            with open(ruta, encoding='utf-8') as f:
                self.estado = json.load(f)
        self.jugadores = sorted((self.estado.get('jugadores') or {}).keys())

    def cargar_datos_historicos(self) -> pd.DataFrame:
        import kagglehub
        p = kagglehub.dataset_download(self.cfg['dataset'])
        df = pd.read_csv(os.path.join(p, self.cfg['archivo']),
                         parse_dates=['Date'], low_memory=False)
        for c in ('Rank_1', 'Rank_2', 'Pts_1', 'Pts_2', 'Odd_1', 'Odd_2'):
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors='coerce')
        base = df['Surface'].map(lambda s: SUP.get(str(s), 'hard'))
        indoor = df.get('Court', pd.Series(['Outdoor'] * len(df))).astype(str) \
            .str.lower().eq('indoor')
        # v35: la pista cubierta es una superficie propia (ELO_INDOOR)
        df['sup'] = np.where(indoor, base + '_indoor', base)
        df['juegos'] = df.get('Score', pd.Series([None] * len(df))).map(_juegos_del_marcador)
        if 'Best of' in df.columns:
            df['bo'] = pd.to_numeric(df['Best of'], errors='coerce').fillna(3)
        else:
            df['bo'] = 3
        df = df.dropna(subset=['Date', 'Player_1', 'Player_2', 'Winner'])
        return df.sort_values('Date')

    @staticmethod
    def _dataset(df: pd.DataFrame, features: Optional[List[str]] = None):
        elo_g: Dict[str, float] = {}
        elo_s: Dict[str, Dict[str, float]] = {}
        forma: Dict[str, list] = {}
        win_sup: Dict[str, list] = {}     # (fecha, ganó) por superficie
        h2h: Dict[tuple, int] = {}
        agenda: Dict[str, list] = {}      # v35: (fecha, juegos) por jugador
        features = features or FEATURES
        idx = [FEATURES.index(f) for f in features]
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
            r1 = float(r.Rank_1) if np.isfinite(r.Rank_1 or np.nan) and r.Rank_1 > 0 else 500
            r2 = float(r.Rank_2) if np.isfinite(r.Rank_2 or np.nan) and r.Rank_2 > 0 else 500
            pt1 = float(getattr(r, 'Pts_1', np.nan) or np.nan)
            pt2 = float(getattr(r, 'Pts_2', np.nan) or np.nan)
            pt1 = pt1 if np.isfinite(pt1) and pt1 > 0 else 100.0
            pt2 = pt2 if np.isfinite(pt2) and pt2 > 0 else 100.0

            # --- fatiga (v35 §1.3), estrictamente con partidos ANTERIORES ---
            def _fatiga(p):
                hist = agenda.get(p)
                if not hist:
                    return 21.0, 0.0, 0.0
                dias = min((r.Date - hist[-1][0]).days, 21)
                p14 = sum(1 for d, _ in hist if 0 <= (r.Date - d).days <= 14)
                h7 = sum(j for d, j in hist if 0 <= (r.Date - d).days <= 7) * MIN_POR_JUEGO
                return float(dias), float(p14), float(h7)

            d1, n1, h1 = _fatiga(p1)
            d2, n2, h2_ = _fatiga(p2)
            gano1 = int(r.Winner == p1)
            if p1 in elo_g and p2 in elo_g:   # ambos con historial
                completo = [(es1 - es2) / 100.0, (eg1 - eg2) / 100.0,
                            (np.log(r2) - np.log(r1)) / 3.0, f1 - f2,
                            ws1 - ws2, float(np.clip(hb, -5, 5)) / 5.0,
                            (np.log(pt1) - np.log(pt2)) / 5.0,
                            (d1 - d2) / 21.0, (n1 - n2) / 8.0, (h1 - h2_) / 10.0]
                X.append([completo[i] for i in idx])
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
            juegos = float(getattr(r, 'juegos', 21.0) or 21.0)
            for p in (p1, p2):
                agenda.setdefault(p, []).append((r.Date, juegos))
                if len(agenda[p]) > 30:
                    agenda[p] = agenda[p][-30:]
        estado = {'jugadores': {}}
        ultima = pd.Timestamp(df['Date'].max())
        for p in elo_g:
            hist = agenda.get(p, [])
            estado['jugadores'][p] = {
                'elo': round(elo_g[p], 1),
                'elo_sup': {k: round(v, 1) for k, v in elo_s.get(p, {}).items()},
                'forma': [int(x) for x in forma.get(p, [])[-10:]],
                'rank': None, 'pts': None,
                # v35: estado de fatiga a la fecha de corte del dataset
                'ultimo_partido': hist[-1][0].strftime('%Y-%m-%d') if hist else None,
                'partidos_14d': sum(1 for d, _ in hist if (ultima - d).days <= 14),
                'horas_7d': round(sum(j for d, j in hist
                                      if (ultima - d).days <= 7) * MIN_POR_JUEGO, 2),
            }
        # ranking más reciente por jugador
        for r in df.itertuples(index=False):
            for jugador, rank, pts in ((r.Player_1, r.Rank_1, getattr(r, 'Pts_1', None)),
                                       (r.Player_2, r.Rank_2, getattr(r, 'Pts_2', None))):
                e = estado['jugadores'].get(jugador)
                if e is None:
                    continue
                if rank and np.isfinite(rank):
                    e['rank'] = float(rank)
                if pts and np.isfinite(pts):
                    e['pts'] = float(pts)
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
        cols = self.features
        X, y, fechas, odds, estado = self._dataset(df, cols)
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

        carpeta = self.cfg['carpeta']
        os.makedirs(carpeta, exist_ok=True)
        import joblib
        joblib.dump(modelo, os.path.join(carpeta, 'moneyline.joblib'), compress=3)
        joblib.dump(sc, os.path.join(carpeta, 'scaler.joblib'), compress=3)
        with open(os.path.join(carpeta, 'estado.json'), 'w', encoding='utf-8') as f:
            json.dump(estado, f)
        previa = {}
        ruta_meta = os.path.join(carpeta, 'metadata.json')
        if os.path.exists(ruta_meta):
            with open(ruta_meta, encoding='utf-8') as f:
                previa = json.load(f)          # conserva coef_juegos/sigmas v32
        meta = {**previa,
                'deporte': self.cfg['etiqueta'], 'circuito': self.circuito,
                'features': cols, 'n_partidos': len(X),
                'precision_validacion': round(float(acc), 4),
                'precision_linea_base_elo': round(float(base), 4),
                'precision_mercado': round(float(acc_mkt), 4) if acc_mkt else None,
                'log_loss_validacion': round(float(ll), 4),
                'modo': 'analitico (sin cuotas en vivo gratis)',
                'fecha_entrenamiento': pd.Timestamp.today().strftime('%Y-%m-%d')}
        with open(ruta_meta, 'w', encoding='utf-8') as f:
            json.dump(meta, f, indent=2)
        logger.info(f"[tenis/{self.circuito}] acc={acc:.4f} "
                    f"(ELO {base:.4f}, mercado {acc_mkt}) ll={ll:.4f}")
        return meta

    def construir_features(self, home: str, away: str, surface: str = 'hard',
                           indoor: bool = False, **ctx) -> Optional[List[float]]:
        jug = self.estado.get('jugadores', {})
        if home not in jug or away not in jug:
            return None
        p1, p2 = jug[home], jug[away]
        sup = SUP.get(str(surface).capitalize(), str(surface).lower())
        clave_sup = f'{sup}_indoor' if indoor else sup

        def _elo_sup(e):
            # ELO de la superficie exacta → de la misma superficie al aire
            # libre → ELO global (cadena de fallback explícita)
            return e['elo_sup'].get(clave_sup, e['elo_sup'].get(sup, e['elo']))

        es1, es2 = _elo_sup(p1), _elo_sup(p2)
        f1 = np.mean(p1['forma']) if p1['forma'] else 0.5
        f2 = np.mean(p2['forma']) if p2['forma'] else 0.5
        r1 = p1.get('rank') or 500
        r2 = p2.get('rank') or 500
        hk = '|'.join(sorted((home, away)))
        hb = self.estado.get('h2h', {}).get(hk, 0)
        hb = hb if hk.split('|')[0] == home else -hb
        def _pts(e):
            v = e.get('pts')
            # OJO: NaN es "truthy" → un `or` no lo filtra (bug cazado en v35)
            return float(v) if v is not None and np.isfinite(v) and v > 0 else 100.0

        pt1, pt2 = _pts(p1), _pts(p2)

        # fatiga: el estado guarda la foto a la fecha de corte del dataset; los
        # días de descanso se recalculan contra HOY (lo único que sí avanza).
        hoy = pd.Timestamp.today().normalize()

        def _dias(e):
            f = e.get('ultimo_partido')
            return min((hoy - pd.Timestamp(f)).days, 21) if f else 21.0

        cols = (self.metadata.get('features') or FEATURES_V30)
        completo = {
            'DIFF_ELO_SUP': (es1 - es2) / 100.0,
            'DIFF_ELO_GLOBAL': (p1['elo'] - p2['elo']) / 100.0,
            'DIFF_RANK_LOG': (np.log(r2) - np.log(r1)) / 3.0,
            'DIFF_FORMA10': f1 - f2,
            'DIFF_WIN_SUP_12M': 0.0,
            'H2H': float(np.clip(hb, -5, 5)) / 5.0,
            'DIFF_PTS_LOG': (np.log(pt1) - np.log(pt2)) / 5.0,
            'DIFF_DIAS_DESCANSO': (_dias(p1) - _dias(p2)) / 21.0,
            'DIFF_PARTIDOS_14D': (p1.get('partidos_14d', 0)
                                  - p2.get('partidos_14d', 0)) / 8.0,
            'DIFF_HORAS_7D': (p1.get('horas_7d', 0.0)
                              - p2.get('horas_7d', 0.0)) / 10.0,
        }
        return [completo[c] for c in cols]


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
    import sys
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    circuitos = [a for a in sys.argv[1:] if a in CIRCUITOS] or ['atp']
    for c in circuitos:
        print(json.dumps(TennisEngine(c).entrenar(), indent=2, ensure_ascii=False))
