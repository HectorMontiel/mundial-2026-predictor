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

    def fit(self, X: np.ndarray, t: np.ndarray, evento: np.ndarray,
            k_fijo: Optional[float] = None):
        """
        MLE censurado. `k_fijo` (v70) clava la forma de Weibull en vez de
        estimarla: hace falta cuando NO hay minuto de gol y todas las
        observaciones están censuradas en t=90 (ver `ajustar_cloglog`), porque
        con t90≡1 el término log(t90) desaparece y k deja de estar identificado
        (la verosimilitud crece de forma monótona con k). Con k fijo el modelo
        sigue siendo el mismo evaluado en t=90, que es lo único que se usa.
        """
        X = np.column_stack([np.ones(len(X)), X])       # intercepto
        t90 = np.clip(t / 90.0, 1e-4, 1.0)

        def _nll(par):
            logk, beta = par[0], par[1:]
            k = np.exp(logk) if k_fijo is None else float(k_fijo)
            eta = np.clip(X @ beta, -8, 8)
            lam = np.exp(eta)
            # h(t) = k/90 · t90^(k−1) · lam ;  H(t) = t90^k · lam
            log_h = np.log(k / 90.0) + (k - 1) * np.log(t90) + eta
            H = t90 ** k * lam
            return -(np.sum(evento * log_h) - np.sum(H))

        x0 = np.zeros(X.shape[1] + 1)
        r = minimize(_nll, x0, method='L-BFGS-B', options={'maxiter': 500})
        self.k = float(k_fijo) if k_fijo is not None else float(np.exp(r.x[0]))
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
# v70 (Mejora C): P(BTTS) para CLUBES, como feature del clasificador 1X2
#
# Por qué hace falta una variante y no vale el modelo de arriba
# -------------------------------------------------------------
# El AFT de v26 se ajusta con el MINUTO del primer gol recibido, y ese dato sólo
# existe en `goleadores.csv`, que es de SELECCIONES (10.354 goles con minuto).
# Para clubes no hay minuto en ninguna fuente del proyecto: sólo sabemos si el
# equipo encajó o no. Medido, no supuesto — verificado en Fase 1 de v70.
#
# Eso no bloquea la mejora: con todas las observaciones censuradas en t=90, el
# Weibull AFT evaluado en 90 es exactamente
#
#     P(encajar) = 1 − exp(−exp(β·x))
#
# es decir, una regresión binomial con enlace **complementary log-log**. Es el
# MISMO modelo, la misma familia de valor extremo y la misma asimetría (que es
# lo que le daba ventaja de calibración sobre Poisson en v27, Brier 0.2358 vs
# 0.2516); lo único que se pierde es la forma temporal k, que no interviene en
# la probabilidad a 90 minutos. Por eso `ajustar_cloglog` fija k=1.
#
# La aportación al 1X2 se mide en walk-forward (`_v70_wf_btts.py`); si no supera
# la regla de oro, la columna no entra en el vector y el código queda apagado.
# ---------------------------------------------------------------------------
COVS_CLUB = ['ATQ_RIVAL', 'DEF_PROPIA', 'DIFF_ELO', 'LOCAL']


def ajustar_cloglog(X: np.ndarray, encajo: np.ndarray) -> WeibullAFT:
    """
    AFT de Weibull evaluado en t=90, ajustado por máxima verosimilitud
    BINOMIAL con enlace cloglog:

        ll = Σ [ y·log(1 − exp(−exp(η))) − (1−y)·exp(η) ]

    Ojo con el atajo que NO funciona (medido, v70): reutilizar `WeibullAFT.fit`
    con t=90 para todas las filas y k=1 parece equivalente y no lo es. La
    verosimilitud censurada le carga H(90) completo también a las filas CON
    evento —porque les está diciendo que encajaron exactamente en el minuto 90—
    y eso la convierte en una verosimilitud de POISSON. El estimador resultante
    iguala E[exp(η)] a la tasa de eventos (0,72 en LaLiga) en vez de igualar
    E[P] a esa tasa, y P sale 0,51 en lugar de 0,72: P(BTTS) media 0,25 contra
    un 0,52 real. Con la verosimilitud binomial correcta el ajuste es exacto.

    Devuelve un `WeibullAFT` (k=1) para que `prob_gol_90` y el resto del módulo
    sigan funcionando sin cambios.
    """
    X = np.asarray(X, dtype=float)
    y = np.asarray(encajo, dtype=float)
    Xi = np.column_stack([np.ones(len(X)), X])

    def _nll(beta):
        eta = np.clip(Xi @ beta, -8.0, 4.0)
        lam = np.exp(eta)
        # log P(evento) = log(1 − exp(−lam)), estable con expm1
        log_p = np.log(-np.expm1(-lam) + 1e-12)
        return -float(np.sum(y * log_p - (1.0 - y) * lam))

    beta0 = np.zeros(Xi.shape[1])
    # intercepto de arranque: cloglog de la tasa media observada
    tasa = float(np.clip(y.mean(), 1e-3, 1 - 1e-3))
    beta0[0] = float(np.log(-np.log1p(-tasa)))
    r = minimize(_nll, beta0, method='L-BFGS-B', options={'maxiter': 800})
    m = WeibullAFT()
    m.k = 1.0
    m.beta = r.x
    return m


def covariables_club(gf_h, gc_h, gf_a, gc_a, elo_diff) -> np.ndarray:
    """
    Dos filas por partido —una por equipo— con las covariables del spec §2.2.
    Fila 0 = el LOCAL (su ataque rival es el GF del visitante); fila 1 = el
    visitante. Misma convención y misma escala que `construir_dataset`, para
    que los coeficientes sean comparables con los de selecciones.
    """
    return np.array([
        [gf_a / 3.0, gc_h / 3.0, elo_diff / 400.0, 1.0],
        [gf_h / 3.0, gc_a / 3.0, -elo_diff / 400.0, 0.0],
    ], dtype=float)


def prob_btts(modelo: WeibullAFT, gf_h, gc_h, gf_a, gc_a, elo_diff) -> float:
    """
    P(marcan ambos) = P(el local encaja) · P(el visitante encaja).

    «Que el local encaje» y «que el visitante marque» son el mismo suceso, así
    que el producto es el BTTS con la independencia entre los dos equipos que ya
    asume el proyecto (la cópula gaussiana se probó en v68 y se descartó: el ρ
    óptimo huía al borde de la malla).
    """
    p = modelo.prob_gol_90(covariables_club(gf_h, gc_h, gf_a, gc_a, elo_diff))
    return float(p[0] * p[1])


def serie_btts_sin_fuga(df: pd.DataFrame, reajustar_cada: int = 200,
                        minimo_train: int = 150) -> np.ndarray:
    """
    P(BTTS) partido a partido para una liga, SIN FUGA.

    Recorre el histórico en orden y, cada `reajustar_cada` partidos, reajusta el
    cloglog con TODO lo anterior y sólo con lo anterior. Los primeros
    `minimo_train` partidos no tienen modelo aún y salen como NaN (el motor los
    imputará con la media del train, igual que hace con las cuotas ausentes).

    `df` necesita: date, home_team, away_team, home_goals, away_goals, elo_diff.
    """
    d = df.sort_values(['date', 'MATCH_ID'] if 'MATCH_ID' in df.columns else ['date'],
                       kind='mergesort').reset_index(drop=True)
    gf: Dict[str, list] = {}
    gc: Dict[str, list] = {}
    filas_X, filas_y = [], []          # historial acumulado para reajustar
    salida = np.full(len(d), np.nan)
    modelo: Optional[WeibullAFT] = None

    for i, r in enumerate(d.itertuples(index=False)):
        h, a = r.home_team, r.away_team
        gf_h = float(np.mean(gf.get(h, [])[-MA:])) if gf.get(h) else np.nan
        gc_h = float(np.mean(gc.get(h, [])[-MA:])) if gc.get(h) else np.nan
        gf_a = float(np.mean(gf.get(a, [])[-MA:])) if gf.get(a) else np.nan
        gc_a = float(np.mean(gc.get(a, [])[-MA:])) if gc.get(a) else np.nan
        elo = float(getattr(r, 'elo_diff', 0.0) or 0.0)
        completo = not any(np.isnan(v) for v in (gf_h, gc_h, gf_a, gc_a))

        if modelo is not None and completo:
            salida[i] = prob_btts(modelo, gf_h, gc_h, gf_a, gc_a, elo)

        if completo:
            Xi = covariables_club(gf_h, gc_h, gf_a, gc_a, elo)
            filas_X.append(Xi)
            # fila 0 = local: ¿encajó? = el visitante marcó
            filas_y.append([float(r.away_goals > 0), float(r.home_goals > 0)])

        n = len(filas_y)
        if n >= minimo_train and (modelo is None or n % reajustar_cada == 0):
            try:
                modelo = ajustar_cloglog(np.vstack(filas_X),
                                         np.concatenate(filas_y))
            except Exception as e:
                logger.debug(f"[btts-club] reajuste fallido en {i}: {e}")

        for eq, propios, contra in ((h, r.home_goals, r.away_goals),
                                    (a, r.away_goals, r.home_goals)):
            gf.setdefault(eq, []).append(float(propios))
            gc.setdefault(eq, []).append(float(contra))
            gf[eq] = gf[eq][-MA:]
            gc[eq] = gc[eq][-MA:]

    # devolver en el orden original del dataframe recibido
    orden = pd.Series(salida, index=d.index)
    return orden.reindex(range(len(d))).values


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
