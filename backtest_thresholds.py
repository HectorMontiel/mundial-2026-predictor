#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v75 — Backtest de los umbrales de la Capa 1 (`umbrales_capa1.json`).

Qué mide
--------
Sobre `pick_ledger.csv` (predicciones fuera de muestra SIN filtrar, con la
cuota de cierre real), simula qué habría rendido cada combinación de filtros de
la Capa 1 y elige la mejor **fuera de muestra**.

Rejilla:
    prob_min   piso de probabilidad del pick
    ev_min     EV mínimo con la cuota real
    ev_max     techo de EV — la v38 demostró que el tramo alto es tóxico
               (−10 % de ROI en 1.033 apuestas), así que es un parámetro de
               pleno derecho y no una curiosidad
    cuota_min  cuota mínima (nada de micro-cuotas)
    conviccion mínimo de prob×EV (gate de la v40)

Por qué no vale elegir el máximo del ROI
----------------------------------------
`edge_engine` ya documentó que el mapa de rentabilidad POR LIGA no es
estacionario: quedarse con las ligas o los umbrales que mejor rindieron en el
pasado sobreajusta y empeora fuera de muestra. Aquí eso se ataca en tres
frentes:

  1. **Walk-forward anidado**: para cada pliegue k, la combinación se elige
     SOLO con los pliegues anteriores y se evalúa en el k. El ROI que se
     reporta es la media de esas evaluaciones, ninguna de las cuales participó
     en su propia selección.
  2. **Criterio maximin**, no media: entre combinaciones parecidas gana la que
     mejor deja la PEOR ventana. Es la misma regla con la que se calibró la
     banda de EV en la v38.
  3. **Bootstrap p5**: se adopta solo si el percentil 5 del ROI (1.000
     remuestreos) es positivo. Es decir, si el peor 5 % plausible también gana.

Y por liga se exige además superar a la configuración GLOBAL fuera de muestra:
una liga solo tiene umbrales propios si se los gana contra el ajuste común.

Uso:
    python backtest_thresholds.py
    python backtest_thresholds.py --dry-run
"""

import argparse
import datetime as dt
import itertools
import json
import logging
import sys
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

# La consola de Windows es cp1252: sin esto, imprimir una flecha o un
# visto aborta el script DESPUÉS de haber hecho todo el trabajo.
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

logger = logging.getLogger(__name__)

LEDGER = 'pick_ledger.csv'
ARCHIVO = 'umbrales_capa1.json'
SALIDA_DIAG = '_v75_umbrales.json'

REJILLA = {
    'prob_min':   [0.45, 0.50, 0.55, 0.60, 0.65, 0.70],
    'ev_min':     [0.0, 0.02, 0.03, 0.05, 0.08],
    'ev_max':     [0.10, 0.12, 0.15, 0.25, 9.99],
    'cuota_min':  [1.30, 1.50, 1.70, 2.00],
    'conviccion': [0.0, 0.015, 0.025, 0.035],
}
MIN_APUESTAS_TOTAL = 50
MIN_APUESTAS_PLIEGUE = 8
MEJORA_MINIMA_ROI = 0.02        # +2 pp sobre la referencia, como pide el plan
N_BOOTSTRAP = 1000
SEMILLA = 20260728


def _ahora() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')


def referencia_produccion() -> dict:
    """Umbrales que rigen hoy en `alpha_finder` (la referencia a batir)."""
    ref = {'prob_min': 0.55, 'ev_min': 0.03, 'ev_max': 0.12,
           'cuota_min': 1.50, 'conviccion': 0.025}
    try:
        import edge_engine as ee
        banda = ee.banda_rentable()
        ref.update({'prob_min': float(ee.piso_prob()),
                    'ev_min': float(banda[0]), 'ev_max': float(banda[1]),
                    'conviccion': float(ee.conviccion_min())})
    except Exception as e:
        logger.warning(f"no se pudo leer edge_engine ({e}); referencia por defecto.")
    return ref


def preparar(ledger: str = LEDGER, aplicar_w: bool = True) -> pd.DataFrame:
    """
    Un candidato por partido: el argmax del modelo con su cuota de cierre.

    `aplicar_w=True` encoge la probabilidad hacia el mercado igual que hace
    producción. Es imprescindible: si los umbrales se calibrasen sobre la
    probabilidad CRUDA, en producción se aplicarían a otra magnitud (la
    encogida) y el filtro dejaría pasar un conjunto distinto del medido.
    """
    import recalibrate_from_history as rec
    d = rec.cargar(ledger)
    d = d.dropna(subset=['cuota_home', 'cuota_draw', 'cuota_away']).copy()
    if d.empty:
        raise RuntimeError('el ledger no tiene cuotas de mercado')

    pm = d[['p_home', 'p_draw', 'p_away']].values
    mk = d[['m_home', 'm_draw', 'm_away']].values
    if aplicar_w:
        import calibracion_mercado as cm
        w = d['liga'].map(lambda k: cm.peso_modelo(k)).values[:, None]
        p = w * pm + (1 - w) * mk
        p = p / p.sum(axis=1, keepdims=True)
    else:
        p = pm

    cuotas = d[['cuota_home', 'cuota_draw', 'cuota_away']].values.astype(float)
    k = p.argmax(axis=1)
    fila = np.arange(len(d))
    d['prob'] = p[fila, k]
    d['cuota'] = cuotas[fila, k]
    d['ev'] = d['cuota'] * d['prob'] - 1.0
    d['conviccion'] = d['prob'] * d['ev']
    d['gano'] = (k == d['resultado'].values).astype(int)
    d['pnl'] = np.where(d['gano'] == 1, d['cuota'] - 1.0, -1.0)
    d['lado'] = k
    return d


def _filtra(d: pd.DataFrame, c: dict) -> pd.DataFrame:
    return d[(d['prob'] >= c['prob_min']) & (d['ev'] >= c['ev_min']) &
             (d['ev'] <= c['ev_max']) & (d['cuota'] >= c['cuota_min']) &
             (d['conviccion'] >= c['conviccion'])]


def _roi(d: pd.DataFrame) -> Optional[float]:
    return float(d['pnl'].mean()) if len(d) else None


def _bootstrap_p5(pnl: np.ndarray, n: int = N_BOOTSTRAP) -> Optional[float]:
    if len(pnl) < 20:
        return None
    rng = np.random.default_rng(SEMILLA)
    idx = rng.integers(0, len(pnl), size=(n, len(pnl)))
    return float(np.percentile(pnl[idx].mean(axis=1), 5))


def _combinaciones() -> List[dict]:
    claves = list(REJILLA)
    return [dict(zip(claves, v)) for v in itertools.product(*REJILLA.values())]


def _evaluar_walkforward(d: pd.DataFrame, combos: List[dict],
                         ref: dict) -> dict:
    """
    Walk-forward anidado. Devuelve el resumen fuera de muestra de la política
    "elige con lo anterior, apuesta en el pliegue" y el de la referencia.
    """
    pliegues = sorted(d['pliegue'].unique())
    if len(pliegues) < 3:
        return {}
    apuestas_oos, apuestas_ref, elegidas = [], [], []
    for k in pliegues[1:]:
        prev = d[d['pliegue'] < k]
        act = d[d['pliegue'] == k]
        if len(prev) < 100 or len(act) < 20:
            continue
        # criterio maximin sobre los pliegues previos
        mejor, mejor_llave = None, None
        for c in combos:
            sub = _filtra(prev, c)
            if len(sub) < MIN_APUESTAS_TOTAL:
                continue
            por_pliegue = [g['pnl'].mean() for _, g in sub.groupby('pliegue')
                           if len(g) >= MIN_APUESTAS_PLIEGUE]
            if len(por_pliegue) < 2:
                continue
            llave = (round(min(por_pliegue), 4), round(float(sub['pnl'].mean()), 4),
                     len(sub))
            if mejor_llave is None or llave > mejor_llave:
                mejor, mejor_llave = c, llave
        if mejor is None:
            continue
        sel = _filtra(act, mejor)
        if len(sel):
            apuestas_oos.append(sel)
        elegidas.append({'pliegue': int(k), **mejor,
                         'n_oos': int(len(sel)),
                         'roi_oos': round(float(sel['pnl'].mean()), 4) if len(sel) else None})
        ref_sel = _filtra(act, ref)
        if len(ref_sel):
            apuestas_ref.append(ref_sel)

    def _resumen(lista):
        if not lista:
            return {'n': 0, 'roi': None, 'p5': None, 'peor_ventana': None}
        todo = pd.concat(lista, ignore_index=True)
        ventanas = [float(g['pnl'].mean()) for _, g in todo.groupby('pliegue')
                    if len(g) >= MIN_APUESTAS_PLIEGUE]
        return {'n': int(len(todo)), 'roi': round(float(todo['pnl'].mean()), 4),
                'p5': (lambda x: round(x, 4) if x is not None else None)(
                    _bootstrap_p5(todo['pnl'].values)),
                'peor_ventana': round(min(ventanas), 4) if ventanas else None,
                'ventanas': [round(v, 4) for v in ventanas],
                'aciertos': int(todo['gano'].sum())}

    return {'optimizado': _resumen(apuestas_oos), 'referencia': _resumen(apuestas_ref),
            'elegidas_por_pliegue': elegidas}


def _combo_final(d: pd.DataFrame, combos: List[dict]) -> Optional[dict]:
    """La combinación maximin sobre TODO el histórico (la que se desplegaría)."""
    mejor, mejor_llave = None, None
    for c in combos:
        sub = _filtra(d, c)
        if len(sub) < MIN_APUESTAS_TOTAL:
            continue
        ventanas = [g['pnl'].mean() for _, g in sub.groupby('pliegue')
                    if len(g) >= MIN_APUESTAS_PLIEGUE]
        if len(ventanas) < 3:
            continue
        llave = (round(min(ventanas), 4), round(float(sub['pnl'].mean()), 4), len(sub))
        if mejor_llave is None or llave > mejor_llave:
            mejor, mejor_llave = c, llave
    return mejor


def analizar(ledger: str = LEDGER) -> dict:
    d = preparar(ledger)
    combos = _combinaciones()
    ref = referencia_produccion()
    logger.info(f"{len(d)} candidatos con cuota real, {len(combos)} combinaciones, "
                f"referencia de producción {ref}")

    global_wf = _evaluar_walkforward(d, combos, ref)
    global_combo = _combo_final(d, combos)
    g_opt = global_wf.get('optimizado', {})
    g_ref = global_wf.get('referencia', {})

    adopta_global = bool(
        global_combo and g_opt.get('roi') is not None and g_ref.get('roi') is not None
        and g_opt['n'] >= MIN_APUESTAS_TOTAL
        and (g_opt['roi'] - g_ref['roi']) >= MEJORA_MINIMA_ROI
        and (g_opt.get('p5') or -1) > 0)

    # --- por liga: debe batir a la configuración global fuera de muestra ---
    por_liga = {}
    for clave, g in d.groupby('liga'):
        if len(g) < 150:
            continue
        base = global_combo or ref
        wf = _evaluar_walkforward(g, combos, base)
        if not wf:
            continue
        opt, base_r = wf.get('optimizado', {}), wf.get('referencia', {})
        combo = _combo_final(g, combos)
        adopta = bool(
            combo and opt.get('roi') is not None and base_r.get('roi') is not None
            and opt['n'] >= MIN_APUESTAS_TOTAL
            and (opt['roi'] - base_r['roi']) >= MEJORA_MINIMA_ROI
            and (opt.get('p5') or -1) > 0)
        por_liga[clave] = {'n_candidatos': int(len(g)), 'combo': combo,
                           'oos_optimizado': opt, 'oos_base': base_r,
                           'adoptada': adopta}

    diag = {
        'generado': _ahora(),
        'n_candidatos': int(len(d)), 'ligas': int(d['liga'].nunique()),
        'referencia_produccion': ref,
        'global': {'combo': global_combo, 'oos_optimizado': g_opt,
                   'oos_referencia': g_ref, 'adoptada': adopta_global,
                   'elegidas_por_pliegue': global_wf.get('elegidas_por_pliegue', [])},
        'por_liga': por_liga,
        'regla': f'se adopta si el ROI fuera de muestra supera a la referencia '
                 f'en ≥{MEJORA_MINIMA_ROI:.0%}, con ≥{MIN_APUESTAS_TOTAL} '
                 f'apuestas y bootstrap p5 > 0.',
    }
    with open(SALIDA_DIAG, 'w', encoding='utf-8') as f:
        json.dump(diag, f, ensure_ascii=False, indent=1, default=str)
    return diag


def escribir(diag: dict, archivo: str = ARCHIVO) -> dict:
    """
    Escribe `umbrales_capa1.json`. Si nada superó la regla, se escribe igual
    con `global: null` y `ligas: {}` — así `alpha_finder` puede leer el archivo
    siempre y la ausencia de mejora queda documentada en vez de dejar un hueco
    que el año que viene nadie sepa interpretar.
    """
    g = diag['global']
    salida = {
        'generado': diag['generado'],
        'nota': 'v75. Umbrales de la Capa 1 validados con walk-forward anidado '
                '(la combinación se elige con pliegues anteriores y se juzga en '
                'el siguiente) + bootstrap p5. null = no se encontró mejora '
                'sobre los umbrales vigentes y se mantienen los de edge_engine.',
        'regla': diag['regla'],
        'referencia_produccion': diag['referencia_produccion'],
        'global': g['combo'] if g['adoptada'] else None,
        'global_metricas': {'optimizado': g['oos_optimizado'],
                            'referencia': g['oos_referencia'],
                            'adoptada': g['adoptada']},
        'ligas': {k: v['combo'] for k, v in diag['por_liga'].items() if v['adoptada']},
        'ligas_evaluadas': {k: {'adoptada': v['adoptada'],
                                'roi_oos': v['oos_optimizado'].get('roi'),
                                'roi_base': v['oos_base'].get('roi'),
                                'p5': v['oos_optimizado'].get('p5'),
                                'n': v['oos_optimizado'].get('n')}
                            for k, v in diag['por_liga'].items()},
    }
    with open(archivo, 'w', encoding='utf-8') as f:
        json.dump(salida, f, ensure_ascii=False, indent=1, default=str)
    return salida


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--ledger', default=LEDGER)
    args = ap.parse_args()
    diag = analizar(args.ledger)
    g = diag['global']
    print(f"\nCandidatos: {diag['n_candidatos']} en {diag['ligas']} ligas")
    print(f"Referencia de producción: {diag['referencia_produccion']}")
    print(f"  ROI fuera de muestra referencia : {g['oos_referencia']}")
    print(f"  ROI fuera de muestra optimizado : {g['oos_optimizado']}")
    print(f"  Combinación final propuesta     : {g['combo']}")
    print(f"  ¿Adoptada? {'SÍ' if g['adoptada'] else 'NO (no supera la regla)'}")
    adoptadas = [k for k, v in diag['por_liga'].items() if v['adoptada']]
    print(f"\nLigas con umbrales propios adoptados: {len(adoptadas)} "
          f"de {len(diag['por_liga'])} evaluadas")
    for k, v in sorted(diag['por_liga'].items(),
                       key=lambda kv: -(kv[1]['oos_optimizado'].get('roi') or -9)):
        o, b = v['oos_optimizado'], v['oos_base']
        print(f"  {'✔' if v['adoptada'] else ' '} {k:22s} "
              f"ROI {o.get('roi')} vs base {b.get('roi')}  "
              f"p5={o.get('p5')}  n={o.get('n')}")
    if not args.dry_run:
        escribir(diag)
        print(f"\n{ARCHIVO} escrito.")
