#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Supervivencia del primer gol RECIBIDO → BTTS (v26, spec §2).

## Por qué NO lifelines (documentado, regla de transparencia)
lifelines 0.30.3 exige pandas<3 y su instalación DEGRADÓ pandas 3.0.3→2.3.3
(verificado 2026-07-18): el proyecto pinnea pandas==3.0.3 porque los pickles
del cloud degeneran si las versiones divergen (lección v14). Se desinstaló y
el modelo se implementa como **Weibull AFT en numpy/scipy puro** (cero
dependencias nuevas) — misma familia de análisis de supervivencia, con
riesgo dependiente del tiempo:

    T_i = minuto del primer gol RECIBIDO por el equipo i (censura en 90)
    S(t|x) = exp(−(t/90)^k · exp(β·x))          (Weibull AFT)
    P(BTTS) = [1 − S_local(90)] · [1 − S_visit(90)]

Covariables (disponibles ANTES del partido, spec §2.2): ataque del rival
(GF_MA5), defensa propia (GC_MA5), diferencia de ELO y localía. MLE con
scipy.optimize sobre la log-verosimilitud censurada:

    ll = Σ_evento [log h(t)] + Σ log S(t)

## Datos
goleadores.csv (Kaggle, minuto real de cada gol internacional) cruzado con
historico_partidos.csv. El 1X2 del Mundial NO se toca: esto solo recalibra
el mercado BTTS/O-U de la plantilla si supera la validación.

## Validación
Walk-forward temporal: Brier del BTTS (sí/no real) del modelo de
supervivencia vs el baseline Poisson (P(BTTS) desde tasas de gol rolling).
Se adopta solo si mejora el Brier sin degradar nada más.

Uso: python supervivencia_btts.py          # experimento completo
"""

import json
import logging
from typing import Dict, Optional, Tuple

import numpy as np
import pandas as pd
from scipy.optimize import minimize

logger = logging.getLogger(__name__)

ARCHIVO = 'resultados_supervivencia_v26.json'
MA = 5     # ventana de las medias móviles


# ---------------------------------------------------------------------------
# Weibull AFT censurado en numpy (sin dependencias nuevas)
# ---------------------------------------------------------------------------
class WeibullAFT:
    """S(t|x) = exp(−(t/90)^k · exp(β·x)); MLE censurado."""

    def __init__(self):
        self.beta = None
        self.k = 1.0

    def fit(self, X: np.ndarray, t: np.ndarray, evento: np.ndarray):
        X = np.column_stack([np.ones(len(X)), X])       # intercepto
        t90 = np.clip(t / 90.0, 1e-4, 1.0)

        def _nll(par):
            logk, beta = par[0], par[1:]
            k = np.exp(logk)
            eta = np.clip(X @ beta, -8, 8)
            lam = np.exp(eta)
            # h(t) = k/90 · t90^(k−1) · lam ;  H(t) = t90^k · lam
            log_h = np.log(k / 90.0) + (k - 1) * np.log(t90) + eta
            H = t90 ** k * lam
            return -(np.sum(evento * log_h) - np.sum(H))

        x0 = np.zeros(X.shape[1] + 1)
        r = minimize(_nll, x0, method='L-BFGS-B', options={'maxiter': 500})
        self.k = float(np.exp(r.x[0]))
        self.beta = r.x[1:]
        return self

    def prob_gol_90(self, X: np.ndarray) -> np.ndarray:
        """1 − S(90|x): probabilidad de recibir al menos un gol."""
        X = np.column_stack([np.ones(len(X)), X])
        eta = np.clip(X @ self.beta, -8, 8)
        return 1.0 - np.exp(-np.exp(eta))       # t90=1 → H = exp(eta)


# ---------------------------------------------------------------------------
# Dataset: un registro por equipo-partido con minuto del primer gol recibido
# ---------------------------------------------------------------------------
def construir_dataset() -> pd.DataFrame:
    h = pd.read_csv('historico_partidos.csv', parse_dates=['date'])
    g = pd.read_csv('goleadores.csv')
    primer_gol: Dict[Tuple[str, str], float] = {}
    for r in g.itertuples(index=False):
        if pd.isna(r.minute):
            continue
        rival = r.away_team if r.team == r.home_team else r.home_team
        k = (r.MATCH_ID, rival)                 # gol RECIBIDO por el rival
        primer_gol[k] = min(primer_gol.get(k, 999.0), float(r.minute))

    ids_con_goles = {mid for mid, _ in primer_gol}
    gf, gc, elo = {}, {}, {}
    filas = []
    for r in h.sort_values(['date', 'MATCH_ID']).itertuples(index=False):
        hh, aa = r.home_team, r.away_team
        e_h, e_a = elo.get(hh, 1500.0), elo.get(aa, 1500.0)
        for eq, rival, es_local, propios, contra in (
                (hh, aa, 1.0, r.home_goals, r.away_goals),
                (aa, hh, 0.0, r.away_goals, r.home_goals)):
            g5p = gf.get(eq, [])[-MA:]
            g5c = gc.get(eq, [])[-MA:]
            g5r = gf.get(rival, [])[-MA:]
            if len(g5p) >= 3 and len(g5r) >= 3 and r.MATCH_ID in ids_con_goles:
                t1 = primer_gol.get((r.MATCH_ID, eq))
                recibio = float(contra) > 0
                # sin minuto pero con gol encajado: dato inconsistente → fuera
                if not (recibio and t1 is None):
                    filas.append({
                        'MATCH_ID': r.MATCH_ID, 'date': r.date, 'equipo': eq,
                        't': min(t1 if t1 is not None else 90.0, 90.0),
                        'evento': int(recibio),
                        'ATQ_RIVAL': np.mean(g5r) / 3.0,
                        'DEF_PROPIA': np.mean(g5c) / 3.0,
                        'DIFF_ELO': ((elo.get(eq, 1500) - elo.get(rival, 1500))
                                     / 400.0),
                        'LOCAL': es_local,
                    })
            gf.setdefault(eq, []).append(float(propios))
            gc.setdefault(eq, []).append(float(contra))
            gf[eq] = gf[eq][-MA:]
            gc[eq] = gc[eq][-MA:]
        exp_h = 1 / (1 + 10 ** ((e_a - e_h) / 400))
        s_h = 1.0 if r.home_goals > r.away_goals else \
            (0.5 if r.home_goals == r.away_goals else 0.0)
        elo[hh] = e_h + 24 * (s_h - exp_h)
        elo[aa] = e_a + 24 * ((1 - s_h) - (1 - exp_h))
    return pd.DataFrame(filas)


COVS = ['ATQ_RIVAL', 'DEF_PROPIA', 'DIFF_ELO', 'LOCAL']


def experimento() -> Dict:
    df = construir_dataset()
    logger.info(f"[surv] {len(df)} registros equipo-partido con minutos "
                f"({df['date'].min().date()} → {df['date'].max().date()})")
    df = df.sort_values(['date', 'MATCH_ID']).reset_index(drop=True)

    # BTTS real por partido (desde los eventos de ambos equipos)
    por_partido = df.groupby('MATCH_ID').agg(
        n=('evento', 'size'), ambos=('evento', 'sum'),
        fecha=('date', 'first')).query('n == 2')
    por_partido['btts'] = (por_partido['ambos'] == 2).astype(int)

    inicio = df['date'].quantile(0.60)
    ventanas = pd.date_range(inicio.normalize(), df['date'].max(), freq='6MS')
    filas = []
    for ini in ventanas:
        fin = ini + pd.DateOffset(months=6)
        tr = df[df['date'] < ini]
        va = df[(df['date'] >= ini) & (df['date'] < fin)]
        va_p = por_partido[(por_partido['fecha'] >= ini)
                           & (por_partido['fecha'] < fin)]
        if len(va_p) < 60 or len(tr) < 1000:
            continue
        modelo = WeibullAFT().fit(tr[COVS].values, tr['t'].values,
                                  tr['evento'].values)
        p_gol = pd.Series(modelo.prob_gol_90(va[COVS].values),
                          index=pd.MultiIndex.from_frame(va[['MATCH_ID', 'equipo']]))
        # Baseline POISSON con las mismas covariables de tasas: la tasa
        # esperada de goles recibidos ≈ media(ATQ_RIVAL·3, DEF_PROPIA·3)
        lam_base = (va['ATQ_RIVAL'].values * 3 + va['DEF_PROPIA'].values * 3) / 2
        p_gol_pois = pd.Series(1 - np.exp(-lam_base), index=p_gol.index)
        lam_por = pd.Series(lam_base, index=p_gol.index)

        y_pred_s, y_pred_p, y_pred_m, y_real = [], [], [], []
        for mid, fila_p in va_p.iterrows():
            sub_s = p_gol.loc[mid] if mid in p_gol.index.get_level_values(0) else None
            if sub_s is None or len(sub_s) != 2:
                continue
            y_pred_s.append(float(sub_s.iloc[0] * sub_s.iloc[1]))
            sub_p = p_gol_pois.loc[mid]
            y_pred_p.append(float(sub_p.iloc[0] * sub_p.iloc[1]))
            # v27: baseline MATRIZ con choque común (mismo λc=0.12·min que
            # _monte_carlo de producción): BTTS = 1 − P(X=0) − P(Y=0) + P(0,0)
            l1, l2 = float(lam_por.loc[mid].iloc[0]), float(lam_por.loc[mid].iloc[1])
            lc = 0.12 * min(l1, l2)
            p00 = np.exp(-(max(l1 - lc, .05) + max(l2 - lc, .05) + lc))
            y_pred_m.append(float(1 - np.exp(-l1) - np.exp(-l2) + p00))
            y_real.append(int(fila_p['btts']))
        if len(y_real) < 50:
            continue
        y_real = np.array(y_real)
        brier_s = float(np.mean((np.array(y_pred_s) - y_real) ** 2))
        brier_p = float(np.mean((np.array(y_pred_p) - y_real) ** 2))
        brier_m = float(np.mean((np.array(y_pred_m) - y_real) ** 2))
        filas.append({'ventana': str(ini.date()), 'n': len(y_real),
                      'brier_superv': round(brier_s, 4),
                      'brier_poisson': round(brier_p, 4),
                      'brier_matriz_choque': round(brier_m, 4),
                      'k_weibull': round(modelo.k, 3)})
        logger.info(f"  [surv] {ini.date()} n={len(y_real)} "
                    f"brier superv {brier_s:.4f} vs poisson {brier_p:.4f} "
                    f"vs matriz-choque {brier_m:.4f} (k={modelo.k:.2f})")
    if not filas:
        return {'veredicto': 'sin datos suficientes'}
    bs = float(np.mean([f['brier_superv'] for f in filas]))
    bp = float(np.mean([f['brier_poisson'] for f in filas]))
    bm = float(np.mean([f['brier_matriz_choque'] for f in filas]))
    salida = {'ventanas': filas, 'brier_superv_medio': round(bs, 4),
              'brier_poisson_medio': round(bp, 4),
              'brier_matriz_choque_medio': round(bm, 4),
              'k_medio': round(float(np.mean([f['k_weibull'] for f in filas])), 3),
              'adoptar': bool(bs < bp - 0.001),
              # v27: transición del BTTS de plantilla solo si vence TAMBIÉN
              # al baseline de matriz con choque común (el de producción)
              'adoptar_transicion': bool(bs < bm - 0.001)}
    logger.info(f"[surv] Brier medio: supervivencia {bs:.4f} vs poisson {bp:.4f} "
                f"vs matriz-choque {bm:.4f} → "
                f"{'TRANSICIONAR' if salida['adoptar_transicion'] else 'solo señal'}")
    with open(ARCHIVO, 'w', encoding='utf-8') as f:
        json.dump(salida, f, ensure_ascii=False, indent=2)
    if salida['adoptar']:
        modelo = WeibullAFT().fit(df[COVS].values, df['t'].values,
                                  df['evento'].values)
        import os
        os.makedirs('modelos', exist_ok=True)
        with open('modelos/supervivencia_btts.json', 'w', encoding='utf-8') as f:
            json.dump({'beta': [round(float(b), 6) for b in modelo.beta],
                       'k': round(modelo.k, 4), 'covs': COVS,
                       'brier_wf': salida['brier_superv_medio']}, f)
        logger.info("[surv] artefacto final → modelos/supervivencia_btts.json")
    return salida


def btts_en_vivo(stats_local: Dict, stats_visit: Dict) -> Optional[float]:
    """P(BTTS) de supervivencia para la UI del Mundial, desde team_stats
    (GF_MA5/GA_MA5/ELO). None si no hay artefacto (no adoptado)."""
    import os
    ruta = 'modelos/supervivencia_btts.json'
    if not os.path.exists(ruta):
        return None
    try:
        with open(ruta, encoding='utf-8') as f:
            art = json.load(f)
        m = WeibullAFT()
        m.beta = np.array(art['beta'])
        m.k = art['k']
        d_elo = (stats_local['ELO'] - stats_visit['ELO']) / 400.0
        X = np.array([
            # registro del LOCAL: ataque rival = GF del visitante...
            [stats_visit['GF_MA5'] / 3.0, stats_local['GA_MA5'] / 3.0, d_elo, 1.0],
            [stats_local['GF_MA5'] / 3.0, stats_visit['GA_MA5'] / 3.0, -d_elo, 0.0],
        ])
        p = m.prob_gol_90(X)
        return float(p[0] * p[1])
    except Exception:
        return None


# ---------------------------------------------------------------------------
# v28 (§2.3): Over 2.5 por supervivencia — T₃ = minuto del TERCER gol del
# partido (censura en 90 si acaba con ≤2 goles). P(Over) = 1 − S(90).
# Covariables a nivel PARTIDO: suma de ataques, suma de defensas, |ΔELO|.
# ---------------------------------------------------------------------------
COVS_O25 = ['ATQ_TOTAL', 'DEF_TOTAL', 'ABS_DELO']


def construir_dataset_over25() -> pd.DataFrame:
    h = pd.read_csv('historico_partidos.csv', parse_dates=['date'])
    g = pd.read_csv('goleadores.csv')
    minutos: Dict[str, list] = {}
    for r in g.itertuples(index=False):
        if not pd.isna(r.minute):
            minutos.setdefault(r.MATCH_ID, []).append(float(r.minute))
    gf, gc, elo = {}, {}, {}
    filas = []
    for r in h.sort_values(['date', 'MATCH_ID']).itertuples(index=False):
        hh, aa = r.home_team, r.away_team
        tot = float(r.home_goals + r.away_goals)
        mins = sorted(minutos.get(r.MATCH_ID, []))
        # consistencia: nº de minutos debe casar con el total de goles
        if (all(len(gf.get(e, [])) >= 3 for e in (hh, aa))
                and len(mins) == int(tot)):
            t3 = mins[2] if tot >= 3 else 90.0
            filas.append({
                'MATCH_ID': r.MATCH_ID, 'date': r.date,
                't': min(t3, 90.0), 'evento': int(tot >= 3),
                'ATQ_TOTAL': (np.mean(gf[hh][-MA:]) + np.mean(gf[aa][-MA:])) / 5.0,
                'DEF_TOTAL': (np.mean(gc[hh][-MA:]) + np.mean(gc[aa][-MA:])) / 5.0,
                'ABS_DELO': abs(elo.get(hh, 1500) - elo.get(aa, 1500)) / 400.0,
            })
        for e, p, c in ((hh, r.home_goals, r.away_goals),
                        (aa, r.away_goals, r.home_goals)):
            gf.setdefault(e, []).append(float(p))
            gc.setdefault(e, []).append(float(c))
            gf[e] = gf[e][-MA:]
            gc[e] = gc[e][-MA:]
        e_h, e_a = elo.get(hh, 1500.0), elo.get(aa, 1500.0)
        exp_h = 1 / (1 + 10 ** ((e_a - e_h) / 400))
        s_h = 1.0 if r.home_goals > r.away_goals else \
            (0.5 if r.home_goals == r.away_goals else 0.0)
        elo[hh] = e_h + 24 * (s_h - exp_h)
        elo[aa] = e_a + 24 * ((1 - s_h) - (1 - exp_h))
    return pd.DataFrame(filas)


def experimento_over25() -> Dict:
    """WF: Brier del Over 2.5 — Weibull T₃ vs matriz Poisson choque-común."""
    df = construir_dataset_over25().sort_values(['date', 'MATCH_ID'])
    logger.info(f"[surv-o25] {len(df)} partidos con minutos consistentes")
    inicio = df['date'].quantile(0.60)
    ventanas = pd.date_range(inicio.normalize(), df['date'].max(), freq='6MS')
    filas = []
    for ini in ventanas:
        fin = ini + pd.DateOffset(months=6)
        tr = df[df['date'] < ini]
        va = df[(df['date'] >= ini) & (df['date'] < fin)]
        if len(va) < 60 or len(tr) < 800:
            continue
        m = WeibullAFT().fit(tr[COVS_O25].values, tr['t'].values,
                             tr['evento'].values)
        p_over_s = m.prob_gol_90(va[COVS_O25].values)
        # baseline: matriz con choque común y λ totales de las mismas tasas
        lam_h = va['ATQ_TOTAL'].values * 5 / 2 * 0 + \
            (va['ATQ_TOTAL'].values * 5 + va['DEF_TOTAL'].values * 5) / 4
        # λ por lado ≈ (ataques+defensas)/4 (mitad del total esperado)
        lc = 0.12 * lam_h
        from math import exp as _e
        p_over_m = []
        for l in lam_h:
            l1 = max(l - 0.12 * l, .05)
            lam_tot = 2 * l1 + 0.12 * l          # E[total] con choque común
            k0 = np.exp(-lam_tot)
            p_le2 = k0 * (1 + lam_tot + lam_tot ** 2 / 2)
            p_over_m.append(1 - p_le2)
        y = va['evento'].values
        bs = float(np.mean((p_over_s - y) ** 2))
        bm = float(np.mean((np.array(p_over_m) - y) ** 2))
        filas.append({'ventana': str(ini.date()), 'n': len(va),
                      'brier_superv': round(bs, 4), 'brier_matriz': round(bm, 4),
                      'k': round(m.k, 3)})
        logger.info(f"  [surv-o25] {ini.date()} n={len(va)} superv {bs:.4f} "
                    f"vs matriz {bm:.4f} (k={m.k:.2f})")
    if not filas:
        return {'veredicto': 'sin datos'}
    bs = float(np.mean([f['brier_superv'] for f in filas]))
    bm = float(np.mean([f['brier_matriz'] for f in filas]))
    salida = {'ventanas': filas, 'brier_superv_medio': round(bs, 4),
              'brier_matriz_medio': round(bm, 4),
              'adoptar': bool(bs < bm - 0.001)}
    logger.info(f"[surv-o25] medio: superv {bs:.4f} vs matriz {bm:.4f} → "
                f"{'ADOPTAR' if salida['adoptar'] else 'descartado'}")
    with open('resultados_over25_v28.json', 'w', encoding='utf-8') as f:
        json.dump(salida, f, ensure_ascii=False, indent=2)
    if salida['adoptar']:
        m = WeibullAFT().fit(df[COVS_O25].values, df['t'].values,
                             df['evento'].values)
        import os
        with open('modelos/supervivencia_over25.json', 'w', encoding='utf-8') as f:
            json.dump({'beta': [round(float(b), 6) for b in m.beta],
                       'k': round(m.k, 4), 'covs': COVS_O25,
                       'brier_wf': salida['brier_superv_medio']}, f)
        logger.info("[surv-o25] artefacto → modelos/supervivencia_over25.json")
    return salida


def over25_en_vivo(stats_local: Dict, stats_visit: Dict) -> Optional[float]:
    """P(Over 2.5) de supervivencia para la plantilla del Mundial."""
    import os
    ruta = 'modelos/supervivencia_over25.json'
    if not os.path.exists(ruta):
        return None
    try:
        with open(ruta, encoding='utf-8') as f:
            art = json.load(f)
        m = WeibullAFT()
        m.beta = np.array(art['beta'])
        m.k = art['k']
        X = np.array([[
            (stats_local['GF_MA5'] + stats_visit['GF_MA5']) / 5.0,
            (stats_local['GA_MA5'] + stats_visit['GA_MA5']) / 5.0,
            abs(stats_local['ELO'] - stats_visit['ELO']) / 400.0,
        ]])
        return float(m.prob_gol_90(X)[0])
    except Exception:
        return None


if __name__ == '__main__':
    import sys
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    if '--over25' in sys.argv:
        r = experimento_over25()
    else:
        r = experimento()
    print(json.dumps({k: v for k, v in r.items() if k != 'ventanas'}, indent=2))
