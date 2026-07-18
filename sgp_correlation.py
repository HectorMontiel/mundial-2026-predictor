#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Correlación empírica para Same Game Parlays — SGP (v25, spec §1.1).

## El problema
El haircut fijo de 0.95 por pareja "de la misma macro-familia" (v15-v24) no
distingue entre correlaciones fuertes (gana local ↔ local anota 2+) y débiles
(over córners ↔ over goles), y puede generar probabilidades conjuntas — y por
tanto EV — infladas.

## El modelo (cópula gaussiana simplificada)
Para dos eventos binarios A, B con marginales pA, pB y coeficiente φ
(la correlación de Pearson de los INDICADORES, medida en el histórico):

    P(A ∩ B) = pA·pB + φ·σA·σB          con σ = √(p(1−p))

que es exactamente la forma bivariada a primer orden de la cópula gaussiana.
El factor multiplicativo por pareja es:

    f(A,B) = P(A∩B) / (pA·pB) = 1 + φ·σA·σB/(pA·pB)

y la probabilidad conjunta del parlay es Π p_i · Π_{i<j} f(i,j).

## Calibración anti-falso-EV+ (spec: "no superar la cuota máxima permitida")
El precio del parlay se construye multiplicando cuotas INDIVIDUALES, pero
ninguna casa paga ese producto en legs positivamente correlacionados. Para no
fabricar EV+ ilusorio, el factor se TRUNCA a f ≤ 1: la correlación positiva
nunca aumenta nuestra probabilidad conjunta accionable (conservador a
propósito, documentado); la negativa sí la penaliza, hasta f ≥ 0.5.

## Datos
φ se estima por pareja de mercados con los históricos de TODAS las ligas de
clubes (últimas 3 temporadas, ~15,000 partidos) y se cachea en
sgp_correlaciones.json (commiteable). Parejas sin dato → haircut legado 0.95
si comparten macro-familia, 1.0 si no.

## Validación (spec §1.1)
`backtest()` compara, por pareja frecuente, la frecuencia conjunta REAL
contra la predicha por (a) independencia y (b) el ajuste φ — el error medio
del ajuste debe ser menor. Resultado en resultados_sgp_v25.json.

Uso:
    python sgp_correlation.py --construir     # recalcula la matriz
    python sgp_correlation.py --backtest      # validación
"""

import json
import logging
import os
from typing import Callable, Dict, List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

ARCHIVO_MATRIZ = 'sgp_correlaciones.json'
TEMPORADAS = 3
F_MIN, F_MAX = 0.5, 1.0          # truncado del factor (anti-falso-EV+)
HAIRCUT_LEGADO = 0.95            # respaldo para parejas sin dato
MIN_OBS = 400                    # observaciones mínimas para fiarse de φ

# ---------------------------------------------------------------------------
# Indicadores por id de la plantilla: fila del histórico → 1/0/None
# (None = el dato necesario no existe en esa fila; se excluye del cálculo)
# ---------------------------------------------------------------------------
def _tot(r):
    return r['home_goals'] + r['away_goals']


def _ck(r):
    c = r.get('home_corners'), r.get('away_corners')
    return None if (pd.isna(c[0]) or pd.isna(c[1])) else c[0] + c[1]


def _tarj(r):
    t = (r.get('home_yellow'), r.get('away_yellow'),
         r.get('home_red'), r.get('away_red'))
    return None if any(pd.isna(x) for x in t) else sum(t)


def _b(cond) -> Optional[int]:
    return None if cond is None else int(cond)


INDICADORES: Dict[str, Callable] = {
    # 1X2 y doble oportunidad (ids del Mundial y de clubes)
    'home_win_prob': lambda r: _b(r['home_goals'] > r['away_goals']),
    'draw_prob': lambda r: _b(r['home_goals'] == r['away_goals']),
    'away_win_prob': lambda r: _b(r['home_goals'] < r['away_goals']),
    'dc_1x': lambda r: _b(r['home_goals'] >= r['away_goals']),
    'dc_12': lambda r: _b(r['home_goals'] != r['away_goals']),
    'dc_x2': lambda r: _b(r['home_goals'] <= r['away_goals']),
    'home_or_draw_prob': lambda r: _b(r['home_goals'] >= r['away_goals']),
    'home_or_away_prob': lambda r: _b(r['home_goals'] != r['away_goals']),
    'draw_or_away_prob': lambda r: _b(r['home_goals'] <= r['away_goals']),
    # over/under de goles
    'over05': lambda r: _b(_tot(r) > 0.5), 'over15': lambda r: _b(_tot(r) > 1.5),
    'over25': lambda r: _b(_tot(r) > 2.5), 'over35': lambda r: _b(_tot(r) > 3.5),
    'over45': lambda r: _b(_tot(r) > 4.5), 'over55': lambda r: _b(_tot(r) > 5.5),
    'over25_prob': lambda r: _b(_tot(r) > 2.5),
    'under25_prob': lambda r: _b(_tot(r) < 2.5),
    'over15_goles': lambda r: _b(_tot(r) > 1.5),
    'over35_goles': lambda r: _b(_tot(r) > 3.5),
    # btts / paridad / momentos
    'btts_si': lambda r: _b(min(r['home_goals'], r['away_goals']) >= 1),
    'btts_no': lambda r: _b(min(r['home_goals'], r['away_goals']) < 1),
    'btts_yes_prob': lambda r: _b(min(r['home_goals'], r['away_goals']) >= 1),
    'btts_no_prob': lambda r: _b(min(r['home_goals'], r['away_goals']) < 1),
    'sin_goles': lambda r: _b(_tot(r) == 0),
    'total_par': lambda r: _b(_tot(r) % 2 == 0),
    'total_impar': lambda r: _b(_tot(r) % 2 == 1),
    # hándicap asiático ±0.5 / 1X2 con hándicap / margen
    'ah_home_1': lambda r: _b(r['home_goals'] - r['away_goals'] >= 1),
    'ah_home_2': lambda r: _b(r['home_goals'] - r['away_goals'] >= 2),
    'ah_home_mas05': lambda r: _b(r['home_goals'] >= r['away_goals']),
    'ah_away_mas05': lambda r: _b(r['home_goals'] <= r['away_goals']),
    'h1x2_fav': lambda r: _b(abs(r['home_goals'] - r['away_goals']) >= 2),
    'mv_h1': lambda r: _b(r['home_goals'] - r['away_goals'] == 1),
    'mv_a1': lambda r: _b(r['away_goals'] - r['home_goals'] == 1),
    # totales por equipo / multigoles
    'th_o05': lambda r: _b(r['home_goals'] > 0.5),
    'th_o15': lambda r: _b(r['home_goals'] > 1.5),
    'th_o25': lambda r: _b(r['home_goals'] > 2.5),
    'ta_o05': lambda r: _b(r['away_goals'] > 0.5),
    'ta_o15': lambda r: _b(r['away_goals'] > 1.5),
    'ta_o25': lambda r: _b(r['away_goals'] > 2.5),
    'multi_h': lambda r: _b(r['home_goals'] >= 2),
    'multi_a': lambda r: _b(r['away_goals'] >= 2),
    # córners y tarjetas (solo ligas con datos reales — formato 'main')
    'ck_o85': lambda r: _b(None if _ck(r) is None else _ck(r) > 8.5),
    'ck_o95': lambda r: _b(None if _ck(r) is None else _ck(r) > 9.5),
    'ck_o105': lambda r: _b(None if _ck(r) is None else _ck(r) > 10.5),
    'cards_o35': lambda r: _b(None if _tarj(r) is None else _tarj(r) > 3.5),
    'cards_o45': lambda r: _b(None if _tarj(r) is None else _tarj(r) > 4.5),
}

# ids equivalentes → id canónico de la matriz (reduce combinatoria)
ALIAS = {
    'over25_prob': 'over25', 'under25_prob': 'under25',
    'over15_goles': 'over15', 'over35_goles': 'over35',
    'btts_yes_prob': 'btts_si', 'btts_no_prob': 'btts_no',
    'home_or_draw_prob': 'dc_1x', 'home_or_away_prob': 'dc_12',
    'draw_or_away_prob': 'dc_x2',
    'home_minus05_prob': 'home_win_prob', 'away_minus05_prob': 'away_win_prob',
    'home_plus05_prob': 'dc_1x', 'away_plus05_prob': 'dc_x2',
}

_matriz_cache = None


def _canonico(id_: str) -> str:
    return ALIAS.get(id_, id_)


def construir_matriz(temporadas: int = TEMPORADAS) -> Dict:
    """φ por pareja de mercados con los históricos de todas las ligas."""
    from config import LEAGUES
    frames = []
    for clave in LEAGUES:
        ruta = f'historico_{clave}.csv'
        if not os.path.exists(ruta):
            continue
        df = pd.read_csv(ruta, parse_dates=['date'])
        corte = df['date'].max() - pd.DateOffset(years=temporadas)
        frames.append(df[df['date'] >= corte])
    datos = pd.concat(frames, ignore_index=True)
    logger.info(f"[sgp] {len(datos)} partidos de {len(frames)} ligas "
                f"(últimas {temporadas} temporadas) para la matriz φ.")

    # under25 no está en INDICADORES con ese nombre canónico: añadirlo
    inds = dict(INDICADORES)
    inds['under25'] = lambda r: _b(_tot(r) < 2.5)

    ids = sorted({_canonico(i) for i in inds})
    columnas = {}
    for id_ in ids:
        fn = inds.get(id_) or inds.get({v: k for k, v in ALIAS.items()}.get(id_, id_))
        if fn is None:
            continue
        columnas[id_] = datos.apply(lambda r: fn(r), axis=1).astype('float')

    mat = {}
    for i, a in enumerate(ids):
        va = columnas.get(a)
        if va is None:
            continue
        for b in ids[i + 1:]:
            vb = columnas.get(b)
            if vb is None:
                continue
            ok = va.notna() & vb.notna()
            n = int(ok.sum())
            if n < MIN_OBS:
                continue
            x, y = va[ok].values, vb[ok].values
            sx, sy = x.std(), y.std()
            if sx < 1e-9 or sy < 1e-9:
                continue
            phi = float(np.corrcoef(x, y)[0, 1])
            mat[f'{a}|{b}'] = {'phi': round(phi, 4), 'n': n}
    salida = {'generado': pd.Timestamp.today().strftime('%Y-%m-%d'),
              'n_partidos': int(len(datos)), 'parejas': mat}
    with open(ARCHIVO_MATRIZ, 'w', encoding='utf-8') as f:
        json.dump(salida, f, ensure_ascii=False)
    logger.info(f"[sgp] matriz con {len(mat)} parejas → {ARCHIVO_MATRIZ}")
    return salida


def _matriz() -> Dict:
    global _matriz_cache
    if _matriz_cache is None:
        try:
            with open(ARCHIVO_MATRIZ, encoding='utf-8') as f:
                _matriz_cache = json.load(f).get('parejas', {})
        except Exception:
            _matriz_cache = {}
    return _matriz_cache


def phi(id_a: str, id_b: str) -> Optional[float]:
    a, b = _canonico(id_a), _canonico(id_b)
    m = _matriz()
    par = m.get(f'{a}|{b}') or m.get(f'{b}|{a}')
    return par['phi'] if par else None


def factor_par(id_a: str, p_a: float, id_b: str, p_b: float,
               misma_familia: bool) -> float:
    """Factor multiplicativo de la prob conjunta para la pareja (truncado).

    Sin φ empírica: haircut legado si comparten macro-familia, 1.0 si no."""
    ph = phi(id_a, id_b)
    if ph is None:
        return HAIRCUT_LEGADO if misma_familia else 1.0
    pa = min(max(p_a, 1e-6), 1 - 1e-6)
    pb = min(max(p_b, 1e-6), 1 - 1e-6)
    f = 1.0 + ph * np.sqrt(pa * (1 - pa) * pb * (1 - pb)) / (pa * pb)
    return float(np.clip(f, F_MIN, F_MAX))


def backtest(temporadas: int = TEMPORADAS,
             fuera_de_muestra: bool = True) -> Dict:
    """Validación: ¿el ajuste φ acerca la conjunta predicha a la real?

    fuera_de_muestra=True (la validación que cuenta): φ se estima con los
    datos hasta hace 1 año y la conjunta se evalúa SOLO en el último año.
    Con False, φ y evaluación comparten muestra: la fórmula bivariada es una
    identidad y el error ~0 solo valida la implementación."""
    from config import LEAGUES
    inds = dict(INDICADORES)
    inds['under25'] = lambda r: _b(_tot(r) < 2.5)
    frames = []
    for clave in LEAGUES:
        ruta = f'historico_{clave}.csv'
        if os.path.exists(ruta):
            df = pd.read_csv(ruta, parse_dates=['date'])
            corte = df['date'].max() - pd.DateOffset(years=temporadas)
            frames.append(df[df['date'] >= corte])
    datos = pd.concat(frames, ignore_index=True)

    ids = sorted({_canonico(i) for i in inds})

    def _columnas(sub):
        out = {}
        for id_ in ids:
            fn = inds.get(id_)
            if fn is not None:
                out[id_] = sub.apply(lambda r: fn(r), axis=1).astype('float')
        return out

    if fuera_de_muestra:
        corte_oos = datos['date'].max() - pd.DateOffset(years=1)
        col_fit = _columnas(datos[datos['date'] < corte_oos])
        columnas = _columnas(datos[datos['date'] >= corte_oos])
    else:
        col_fit = columnas = _columnas(datos)

    # φ de la muestra de ajuste (no de la de evaluación)
    def _phi_fit(a, b):
        va, vb = col_fit.get(a), col_fit.get(b)
        if va is None or vb is None:
            return None
        ok = va.notna() & vb.notna()
        if ok.sum() < MIN_OBS:
            return None
        x, y = va[ok].values, vb[ok].values
        if x.std() < 1e-9 or y.std() < 1e-9:
            return None
        return float(np.corrcoef(x, y)[0, 1])

    filas, err_ind, err_phi = [], [], []
    for par in _matriz():
        a, b = par.split('|')
        ph = _phi_fit(a, b)
        va, vb = columnas.get(a), columnas.get(b)
        if ph is None or va is None or vb is None:
            continue
        ok = va.notna() & vb.notna()
        if ok.sum() < 200:
            continue
        x, y = va[ok].values, vb[ok].values
        pa, pb = x.mean(), y.mean()
        real = float((x * y).mean())
        indep = pa * pb
        ajuste = indep + ph * np.sqrt(pa*(1-pa)*pb*(1-pb))
        err_ind.append(abs(indep - real))
        err_phi.append(abs(ajuste - real))
        filas.append({'par': par, 'phi': round(ph, 4), 'n': int(ok.sum()),
                      'conjunta_real': round(real, 4),
                      'independencia': round(indep, 4),
                      'ajuste_phi': round(float(ajuste), 4)})
    resumen = {
        'n_parejas': len(filas),
        'error_medio_independencia': round(float(np.mean(err_ind)), 5),
        'error_medio_ajuste_phi': round(float(np.mean(err_phi)), 5),
        'mejora_pct': round(100 * (1 - np.mean(err_phi) / max(np.mean(err_ind), 1e-9)), 1),
        'peores_independencia': sorted(filas, key=lambda f: -abs(
            f['independencia'] - f['conjunta_real']))[:10],
    }
    with open('resultados_sgp_v25.json', 'w', encoding='utf-8') as f:
        json.dump({'resumen': {k: v for k, v in resumen.items()
                               if k != 'peores_independencia'},
                   'peores_independencia': resumen['peores_independencia'],
                   'parejas': filas}, f, ensure_ascii=False, indent=2)
    logger.info(f"[sgp] backtest: err indep {resumen['error_medio_independencia']} "
                f"vs err φ {resumen['error_medio_ajuste_phi']} "
                f"(mejora {resumen['mejora_pct']} %)")
    return resumen


if __name__ == '__main__':
    import sys
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    if '--construir' in sys.argv:
        construir_matriz()
    if '--backtest' in sys.argv:
        print(json.dumps({k: v for k, v in backtest().items()
                          if k != 'peores_independencia'}, indent=2))
