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
    'ah_home_3': lambda r: _b(r['home_goals'] - r['away_goals'] >= 3),
    'ah_home_4': lambda r: _b(r['home_goals'] - r['away_goals'] >= 4),
    'ah_home_mas05': lambda r: _b(r['home_goals'] >= r['away_goals']),
    'ah_away_mas05': lambda r: _b(r['home_goals'] <= r['away_goals']),
    # v53.1: lados que faltaban (local positivo / visitante negativo)
    'ah_home_p2': lambda r: _b(r['home_goals'] - r['away_goals'] >= -1),
    'ah_home_p3': lambda r: _b(r['home_goals'] - r['away_goals'] >= -2),
    'ah_home_p4': lambda r: _b(r['home_goals'] - r['away_goals'] >= -3),
    'ah_away_1': lambda r: _b(r['home_goals'] - r['away_goals'] <= 0),
    'ah_away_2': lambda r: _b(r['home_goals'] - r['away_goals'] <= 1),
    'ah_away_3': lambda r: _b(r['home_goals'] - r['away_goals'] <= 2),
    'ah_away_4': lambda r: _b(r['home_goals'] - r['away_goals'] <= 3),
    'ah_away_m1': lambda r: _b(r['home_goals'] - r['away_goals'] <= -1),
    'ah_away_m2': lambda r: _b(r['home_goals'] - r['away_goals'] <= -2),
    'ah_away_m3': lambda r: _b(r['home_goals'] - r['away_goals'] <= -3),
    'ah_away_m4': lambda r: _b(r['home_goals'] - r['away_goals'] <= -4),
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


def _factor_bruto(ph: float, p_a: float, p_b: float) -> float:
    """Factor multiplicativo SIN truncar: 1 + φ·σA·σB/(pA·pB)."""
    pa = min(max(p_a, 1e-6), 1 - 1e-6)
    pb = min(max(p_b, 1e-6), 1 - 1e-6)
    return 1.0 + ph * np.sqrt(pa * (1 - pa) * pb * (1 - pb)) / (pa * pb)


def factor_par(id_a: str, p_a: float, id_b: str, p_b: float,
               misma_familia: bool) -> float:
    """Factor multiplicativo de la prob conjunta para la pareja (TRUNCADO a
    [0.5, 1.0]). Este es el que usa el constructor de parlays para PRECIAR de
    forma conservadora: la correlación positiva nunca infla la conjunta
    accionable. Sin φ empírica: haircut legado si comparten macro-familia.
    """
    ph = phi(id_a, id_b)
    if ph is None:
        return HAIRCUT_LEGADO if misma_familia else 1.0
    return float(np.clip(_factor_bruto(ph, p_a, p_b), F_MIN, F_MAX))


def factor_par_real(id_a: str, p_a: float, id_b: str, p_b: float) -> Optional[float]:
    """Factor SIN truncar (para DETECTAR SGP+, no para preciar). Devuelve None
    si no hay φ empírica fiable para la pareja."""
    ph = phi(id_a, id_b)
    if ph is None:
        return None
    return float(_factor_bruto(ph, p_a, p_b))


# ---------------------------------------------------------------------------
# v37 (§1): explotación de correlaciones positivas asimétricas (SGP+)
# ---------------------------------------------------------------------------
# Un SGP con dos patas POSITIVAMENTE correlacionadas (φ>0) tiene una prob
# conjunta REAL mayor que el producto de las individuales. Las casas suelen
# preciar el SGP como (producto de cuotas) × (recorte genérico) sin medir la
# correlación exacta de ESA pareja. Cuando nuestra φ empírica dice que la
# correlación real es más fuerte que la que el recorte genérico de la casa
# asume, el SGP está infravalorado y hay ventaja.
#
# HONESTIDAD (documentada en VALIDACION_v37): no existe feed gratuito de
# precios HISTÓRICOS de SGP, así que no podemos backtestear el ROI del SGP+
# directamente. Lo que SÍ validamos (sgp_correlation.backtest, error de la
# conjunta 0.049→0.003) es que nuestra φ predice bien la frecuencia conjunta
# real. La señal SGP+ es, por tanto, "esta pareja está correlacionada de
# forma que las casas tienden a infrapreciar; búscala en tu libro".
PHI_MIN_SGP = 0.08          # correlación mínima para considerar SGP+
RECORTE_GENERICO_CASA = 0.92  # recorte típico que aplica una casa al SGP
# El SGP+ está pensado para mercados de probabilidad RAZONABLE, no para
# billetes de lotería: con probabilidades extremas la cópula gaussiana de
# primer orden se dispara (σσ/(pa·pb) → ∞) y fabrica EV+ ilusorio. Ese fue
# precisamente el motivo del truncado de la v25.
PROB_MIN_LEG_SGP = 0.20     # cada pata debe ser al menos moderadamente probable
PROB_MAX_LEG_SGP = 0.92     # y no una casi-certeza (cuota ínfima, sin margen)


def senal_sgp_plus(id_a: str, p_a: float, cuota_a: float,
                   id_b: str, p_b: float, cuota_b: float) -> Optional[Dict]:
    """Detecta si la pareja (A,B) del MISMO partido es un SGP+ accionable.

    SOLO tiene sentido con cuotas REALES de mercado en ambas patas (con cuotas
    justas cuota=1/prob y el EV degenera en f_real·recorte−1, un artefacto).
    El llamador debe garantizar que cuota_a/cuota_b son de mercado.

    Compara la prob conjunta REAL (ajustada por φ, ACOTADA a [pa·pb, min(pa,pb)]
    porque una conjunta no puede exceder ninguna marginal) contra lo que
    pagaría la casa si preciara el SGP como producto × recorte genérico.
    """
    ph = phi(id_a, id_b)
    if ph is None or ph < PHI_MIN_SGP or ph >= 0.985:
        return None                      # sin corr. relevante, o identidad (φ≈1)
    if not (PROB_MIN_LEG_SGP <= p_a <= PROB_MAX_LEG_SGP and
            PROB_MIN_LEG_SGP <= p_b <= PROB_MAX_LEG_SGP):
        return None                      # probabilidades fuera del rango sano
    if not (cuota_a and cuota_b and cuota_a > 1 and cuota_b > 1):
        return None
    f_real = factor_par_real(id_a, p_a, id_b, p_b)
    if f_real is None:
        return None
    # conjunta acotada: nunca por debajo del producto (corr positiva) ni por
    # encima de la marginal más pequeña (cota de Fréchet).
    prob_conjunta_real = float(np.clip(p_a * p_b * f_real,
                                       p_a * p_b, min(p_a, p_b)))
    # cuota que la casa daría al SGP ≈ producto × recorte (payout menor)
    cuota_sgp_estimada = cuota_a * cuota_b * RECORTE_GENERICO_CASA
    ev = prob_conjunta_real * cuota_sgp_estimada - 1.0
    if ev <= 0.05:                       # umbral del spec: EV conjunto > +5 %
        return None
    return {
        'id_a': _canonico(id_a), 'id_b': _canonico(id_b),
        'phi': round(ph, 3),
        'prob_conjunta_real': round(float(prob_conjunta_real), 4),
        'prob_producto': round(float(p_a * p_b), 4),
        'boost_correlacion': round(float(f_real), 3),
        'cuota_sgp_estimada': round(float(cuota_sgp_estimada), 2),
        'ev_estimado': round(float(ev), 3),
    }


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


def parejas_correlacionadas(phi_min: float = PHI_MIN_SGP) -> List[Dict]:
    """Parejas con correlación POSITIVA fuerte, ordenadas — consulta O(1)
    sobre la matriz ya precalculada (spec §1.2: nada de cómputo en el
    frontend). Sirve para priorizar SGP+ y para la UI de diagnóstico."""
    out = []
    for par, d in _matriz().items():
        if d['phi'] >= phi_min:
            a, b = par.split('|')
            out.append({'par': par, 'a': a, 'b': b,
                        'phi': d['phi'], 'n': d['n']})
    return sorted(out, key=lambda d: -d['phi'])


if __name__ == '__main__':
    import sys
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    if '--construir' in sys.argv:
        construir_matriz()
    if '--sgp-plus' in sys.argv:
        top = parejas_correlacionadas()
        print(f"{len(top)} parejas con φ ≥ {PHI_MIN_SGP}:")
        for d in top[:25]:
            print(f"  {d['par']:40s} φ={d['phi']:+.3f}  n={d['n']}")
    if '--backtest' in sys.argv:
        print(json.dumps({k: v for k, v in backtest().items()
                          if k != 'peores_independencia'}, indent=2))
