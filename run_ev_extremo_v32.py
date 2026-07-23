#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Backtest del filtro anti-trampas de EV extremo (v32 §3.3).

Hipótesis del spec: los picks con EV > +15 % suelen delatar información que
el modelo NO tiene (lesiones, rotaciones), así que deberían acertar MENOS que
los de EV moderado. Se contrasta con las apuestas simuladas reales de la
validación de cada liga (roi_bets_{liga}.json: prob, cuota de cierre, ev,
gano) — datos ya generados por entrenar_liga, sin fuga.
"""
import glob
import json
import logging

import numpy as np

logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
logger = logging.getLogger(__name__)

TRAMOS = [('moderado_3_15', 0.03, 0.15), ('extremo_15_mas', 0.15, 99.0),
          ('bajo_0_3', 0.0, 0.03)]


def main() -> dict:
    apuestas = []
    for ruta in glob.glob('roi_bets_*.json'):
        liga = ruta[len('roi_bets_'):-len('.json')]
        try:
            with open(ruta, encoding='utf-8') as f:
                for a in json.load(f):
                    a['liga'] = liga
                    apuestas.append(a)
        except Exception:
            continue
    logger.info(f"{len(apuestas)} apuestas simuladas de "
                f"{len({a['liga'] for a in apuestas})} ligas")
    salida = {'n_total': len(apuestas), 'tramos': {}}
    for nombre, lo, hi in TRAMOS:
        sub = [a for a in apuestas if lo <= a.get('ev', 0) < hi]
        if not sub:
            continue
        aciertos = sum(a['gano'] for a in sub)
        ganancia = sum(a['gano'] * (a['cuota'] - 1) - (1 - a['gano']) for a in sub)
        prob_media = float(np.mean([a['prob'] for a in sub]))
        tasa = aciertos / len(sub)
        salida['tramos'][nombre] = {
            'n': len(sub),
            'tasa_acierto': round(tasa, 4),
            'prob_media_modelo': round(prob_media, 4),
            'calibracion_gap': round(tasa - prob_media, 4),
            'roi_pct': round(100 * ganancia / len(sub), 2),
            'cuota_media': round(float(np.mean([a['cuota'] for a in sub])), 2)}
        logger.info(f"  {nombre}: n={len(sub)} acierto={tasa:.3f} "
                    f"(modelo decía {prob_media:.3f}, gap "
                    f"{tasa - prob_media:+.3f}) ROI={salida['tramos'][nombre]['roi_pct']:+.1f}%")
    mod = salida['tramos'].get('moderado_3_15', {})
    ext = salida['tramos'].get('extremo_15_mas', {})
    if mod and ext:
        salida['veredicto'] = {
            'gap_moderado': mod['calibracion_gap'],
            'gap_extremo': ext['calibracion_gap'],
            'diferencia_roi': round(ext['roi_pct'] - mod['roi_pct'], 2),
            'filtro_justificado': bool(ext['calibracion_gap'] < mod['calibracion_gap'])}
        logger.info(f"[ev-extremo] filtro "
                    f"{'JUSTIFICADO' if salida['veredicto']['filtro_justificado'] else 'NO justificado'}: "
                    f"gap extremo {ext['calibracion_gap']:+.3f} vs moderado "
                    f"{mod['calibracion_gap']:+.3f}")
    with open('resultados_ev_extremo_v32.json', 'w', encoding='utf-8') as f:
        json.dump(salida, f, indent=2)
    return salida


if __name__ == '__main__':
    print(json.dumps(main(), indent=2))
