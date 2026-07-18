#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Verificación de calibración por condición de localía (v26, spec §3.3).

Consume las predicciones OUT-OF-FOLD del walk-forward (predicciones_oof.csv,
generado por shadow_booster.py): para cada clase (victoria local / empate /
victoria visitante) construye la curva de fiabilidad (prob predicha vs
frecuencia observada, 10 bins) y el Brier score. En las ligas de clubes la
"condición" es la clase misma (local/empate/visitante); el Mundial juega en
sede neutral y su simetría ya está garantizada bit a bit por test_simetria.

Si el Brier de la clase LOCAL fuese sistemáticamente peor que el de la clase
VISITANTE (sobrestimación de la localía), habría que revisar
VENTAJA_LOCALIA. Resultado → calibracion_v26.json + resumen en consola.

Uso: python run_calibracion_v26.py
"""

import json
import logging

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
logger = logging.getLogger(__name__)

BINS = np.linspace(0, 1, 11)


def curva(p: np.ndarray, y: np.ndarray) -> dict:
    """Curva de fiabilidad + Brier para una clase binaria."""
    idx = np.clip(np.digitize(p, BINS) - 1, 0, 9)
    filas = []
    for b in range(10):
        m = idx == b
        if m.sum() < 20:
            continue
        filas.append({'bin': f'{BINS[b]:.1f}-{BINS[b+1]:.1f}',
                      'n': int(m.sum()),
                      'prob_media': round(float(p[m].mean()), 4),
                      'freq_observada': round(float(y[m].mean()), 4)})
    return {'brier': round(float(np.mean((p - y) ** 2)), 4),
            'n': int(len(p)),
            'curva': filas,
            'ece': round(float(np.sum([f['n'] * abs(f['prob_media']
                                                    - f['freq_observada'])
                                       for f in filas]) / max(len(p), 1)), 4)}


def main() -> dict:
    df = pd.read_csv('predicciones_oof.csv')
    logger.info(f"{len(df)} predicciones OOF de {df['liga'].nunique()} ligas")
    salida = {}
    for ambito, sub in [('global', df)] + list(df.groupby('liga')):
        if len(sub) < 300:
            continue
        y = sub['resultado'].values
        res = {}
        for clase, col, cod in (('local', 'p_home', 0), ('empate', 'p_draw', 1),
                                ('visitante', 'p_away', 2)):
            res[clase] = curva(sub[col].values, (y == cod).astype(float))
        # OJO: comparar Brier ENTRE clases confunde calibración con tasa
        # base (la clase local ronda el 45 % y su Brier máximo teórico es
        # mayor que el de la visitante ~28 %). El sesgo de localía se mide
        # con el ECE (brecha |prob predicha − frecuencia| ponderada).
        res['sesgo_localia_ece'] = round(res['local']['ece']
                                         - res['visitante']['ece'], 4)
        salida[ambito] = res
        logger.info(f"  [{ambito}] ECE local {res['local']['ece']} · "
                    f"empate {res['empate']['ece']} · visitante "
                    f"{res['visitante']['ece']} (Brier "
                    f"{res['local']['brier']}/{res['empate']['brier']}/"
                    f"{res['visitante']['brier']})")
    with open('calibracion_v26.json', 'w', encoding='utf-8') as f:
        json.dump(salida, f, ensure_ascii=False, indent=2)
    g = salida.get('global', {})
    if g:
        ece_l = g['local']['ece']
        veredicto = ('SIN sesgo de localía material'
                     if ece_l < 0.03 and abs(g.get('sesgo_localia_ece', 0)) < 0.02
                     else '⚠️ REVISAR VENTAJA_LOCALIA')
        logger.info(f"Veredicto global: {veredicto} "
                    f"(ECE local = {ece_l}, ΔECE local−visitante = "
                    f"{g.get('sesgo_localia_ece')})")
    return salida


if __name__ == '__main__':
    main()
