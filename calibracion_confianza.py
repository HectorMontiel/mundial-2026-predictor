#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v77 — Qué acierta DE VERDAD cada banda de probabilidad.

El hallazgo que obliga a este módulo
------------------------------------
La pestaña «Máxima Confianza» se pidió con umbral prob ≥ 0,80. Medido sobre
36.006 predicciones fuera de muestra con cuota real (`pick_ledger.csv`), esa
promesa no se sostiene:

    umbral   n      acierto real   ROI      p5 bootstrap
    ≥ 0,60   2.300     62,9 %      +1,20 %   −1,48 %
    ≥ 0,65     539     62,9 %      −0,17 %   −5,53 %
    ≥ 0,70     113     63,7 %      +3,67 %   −8,50 %
    ≥ 0,75      45     57,8 %      −6,47 %  −26,69 %
    ≥ 0,80      17     (muestra insuficiente)

Dos cosas que hay que decir sin adornos:

1. **El acierto NO sube con el umbral.** Se estanca en torno al 63 % y por
   encima de 0,75 empeora. El modelo dice 75 % y entrega 58 %: en la cola alta
   está sobreconfiado, que es el mismo fenómeno que la v71 detectó en el pick
   elegido y la v75 corrigió encogiendo hacia el mercado — pero el
   encogimiento reduce el sesgo medio, no arregla la cola.
2. Con 0,80 la pestaña estaría **vacía casi todos los días**: solo el 2,03 %
   de los partidos llega ahí, y el máximo del barrido de hoy era 0,796.

Qué se hace con eso
-------------------
No se esconde y no se infla. La pestaña usa el umbral 0,70, que es el que mejor
rinde de los medidos, y **cada pick lleva el acierto REAL de su banda** para
que la interfaz pueda poner, junto al «78 %» del modelo, el «esta banda acierta
históricamente un 64 %». Un usuario que ve las dos cifras puede decidir; uno
que solo ve la primera, no.

La tabla se regenera con `python calibracion_confianza.py` cada vez que cambie
el ledger.
"""

import json
import logging
import os
import sys
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

ARCHIVO = 'calibracion_confianza.json'
# v78: el ledger TOTAL incluye los tres deportes, así que las bandas se
# calculan sobre 120.076 predicciones en vez de 36.006.
LEDGER = 'pick_ledger_total.csv'
# Bordes de banda. Se paran en 0,80 porque por encima no hay muestra suficiente
# para afirmar nada (17 casos en todo el histórico).
BANDAS = [(0.50, 0.55), (0.55, 0.60), (0.60, 0.65), (0.65, 0.70),
          (0.70, 0.75), (0.75, 1.01)]
MIN_MUESTRA = 30
_CACHE: Dict[str, dict] = {}


def _tabla() -> dict:
    if 'datos' not in _CACHE:
        datos = {}
        try:
            if os.path.exists(ARCHIVO):
                with open(ARCHIVO, encoding='utf-8') as f:
                    datos = json.load(f)
        except Exception as e:
            logger.warning(f"[confianza] no se pudo leer {ARCHIVO}: {e}")
        _CACHE['datos'] = datos
    return _CACHE['datos']


def acierto_real(prob: Optional[float]) -> Optional[float]:
    """
    Acierto histórico medido de la banda a la que pertenece `prob`.

    None si no hay muestra suficiente para esa banda — que es una respuesta
    mejor que inventar un número.
    """
    if prob is None:
        return None
    for b in (_tabla().get('bandas') or []):
        if b['desde'] <= prob < b['hasta'] and b.get('n', 0) >= MIN_MUESTRA:
            return b['acierto']
    return None


def aviso_calibracion(prob: Optional[float]) -> Optional[str]:
    """Texto para la UI cuando el modelo promete más de lo que cumple."""
    real = acierto_real(prob)
    if real is None or prob is None:
        return None
    if prob - real >= 0.05:
        return (f"El modelo da {prob:.0%}, pero esta banda de probabilidad "
                f"acierta históricamente un {real:.0%}.")
    return None


def calcular(ledger: str = LEDGER) -> dict:
    import numpy as np
    import pandas as pd
    import calibracion_mercado as cm
    import recalibrate_from_history as rec

    # v78: NO se exige `cuota_draw`. Es nula en tenis, MLB y NBA —no tienen
    # empate— y pedirla descartaba los tres deportes en silencio, dejando las
    # bandas calculadas solo con fútbol. Es el mismo descuido que tenía
    # `recalibrate_from_history.cargar` antes de generalizarla.
    d = rec.cargar(ledger).dropna(subset=['cuota_home', 'cuota_away'])
    pm = d[['p_home', 'p_draw', 'p_away']].values
    mk = d[['m_home', 'm_draw', 'm_away']].values
    cu = d[['cuota_home', 'cuota_draw', 'cuota_away']].values.astype(float)
    cp = d[['pin_home', 'pin_draw', 'pin_away']].values.astype(float)
    mejor = np.fmax(cu, np.nan_to_num(cp, nan=0.0))
    w = d['liga'].map(lambda k: cm.peso_modelo(k)).values[:, None]
    p = w * pm + (1 - w) * mk
    p = p / p.sum(axis=1, keepdims=True)
    y = d['resultado'].values.astype(int)
    f = np.arange(len(d))
    k = p.argmax(axis=1)
    prob, cuota, gano = p[f, k], mejor[f, k], (k == y)

    rng = np.random.default_rng(20260728)
    bandas = []
    for lo, hi in BANDAS:
        sel = (prob >= lo) & (prob < hi) & (cuota >= 1.5)
        n = int(sel.sum())
        fila = {'desde': lo, 'hasta': hi, 'n': n}
        if n >= MIN_MUESTRA:
            pnl = np.where(gano[sel], cuota[sel] - 1, -1.0)
            idx = rng.integers(0, len(pnl), size=(2000, len(pnl)))
            fila.update({
                'acierto': round(float(gano[sel].mean()), 4),
                'prob_media_modelo': round(float(prob[sel].mean()), 4),
                'sesgo': round(float(prob[sel].mean() - gano[sel].mean()), 4),
                'roi': round(float(pnl.mean()), 4),
                'p5': round(float(np.percentile(pnl[idx].mean(axis=1), 5)), 4),
                'cuota_media': round(float(cuota[sel].mean()), 3)})
        bandas.append(fila)

    # y los umbrales acumulados, que es lo que decide la pestaña
    umbrales = []
    for u in (0.60, 0.65, 0.70, 0.75, 0.80):
        sel = (prob >= u) & (cuota >= 1.5)
        n = int(sel.sum())
        fila = {'umbral': u, 'n': n, 'pct_partidos': round(float(sel.mean()), 4)}
        if n >= MIN_MUESTRA:
            pnl = np.where(gano[sel], cuota[sel] - 1, -1.0)
            idx = rng.integers(0, len(pnl), size=(2000, len(pnl)))
            fila.update({'acierto': round(float(gano[sel].mean()), 4),
                         'roi': round(float(pnl.mean()), 4),
                         'p5': round(float(np.percentile(pnl[idx].mean(axis=1), 5)), 4)})
        umbrales.append(fila)

    validos = [u for u in umbrales if u.get('roi') is not None]
    recomendado = max(validos, key=lambda u: u['roi'])['umbral'] if validos else 0.70

    salida = {
        'generado_de': ledger, 'n_total': int(len(d)),
        'bandas': bandas, 'umbrales': umbrales,
        'umbral_recomendado': recomendado,
        'nota': 'Acierto REAL por banda de probabilidad, medido fuera de '
                'muestra. El acierto no crece con el umbral: se estanca en '
                '~63 % y por encima de 0,75 baja (el modelo sobreconfía en la '
                'cola). La pestaña de Máxima Confianza lo muestra junto a la '
                'probabilidad del modelo para no prometer lo que no cumple.',
    }
    with open(ARCHIVO, 'w', encoding='utf-8') as fh:
        json.dump(salida, fh, ensure_ascii=False, indent=1)
    _CACHE.pop('datos', None)
    return salida


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    s = calcular()
    print(f"{s['n_total']} predicciones fuera de muestra\n")
    print(f"{'banda':>14s} {'n':>6s} {'modelo':>8s} {'real':>8s} {'sesgo':>8s} {'ROI':>8s}")
    for b in s['bandas']:
        if b.get('acierto') is None:
            print(f"{b['desde']:.2f}-{b['hasta']:.2f}   {b['n']:6d}   (muestra insuficiente)")
            continue
        print(f"  {b['desde']:.2f}-{b['hasta']:.2f} {b['n']:6d} "
              f"{b['prob_media_modelo']:8.1%} {b['acierto']:8.1%} "
              f"{b['sesgo']:+8.1%} {b['roi']:+8.2%}")
    print(f"\numbral recomendado para «Máxima Confianza»: {s['umbral_recomendado']:.2f}")
