#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v71 · Diagnóstico del ROI negativo — el modelo contra el mercado sharp.

La pregunta
-----------
EFL League One (−21,7 %), MLS (−15,6 %) y Liga MX (−11,8 %) pierden dinero de
forma sostenida aunque sus modelos batan al ELO. Hay dos explicaciones posibles
y llevan a arreglos opuestos:

  (a) el modelo SOBRESTIMA sus probabilidades (mala calibración) → hay que
      recalibrar, y ningún umbral lo va a salvar;
  (b) el modelo está bien pero los filtros de Capa 1 eligen mal → hay que
      reajustar umbrales por liga.

Se distinguen comparando la probabilidad del modelo con la **probabilidad justa
de Pinnacle** (su cuota sin margen). Pinnacle es el mercado más eficiente que
existe: tratarlo como «verdad» aproximada es lo que hace cualquier analista
serio, y hasta v71 el proyecto no podía hacerlo porque no tenía sus cuotas.

Qué mide
--------
Por liga, sobre los partidos con cuota de Pinnacle vigente:
  · sesgo medio = media(p_modelo − p_pinnacle) por selección
  · sesgo del PICK = lo mismo, solo en la selección que el modelo elegiría
  · correlación y error absoluto medio
  · cuántas veces el modelo cree tener >70 % y Pinnacle da <60 %

Un sesgo positivo grande en el pick es la firma de (a): el modelo se enamora de
su favorito, el EV sale inflado y la apuesta pierde a la larga.

Salida: `_v71_calibracion_vs_pinnacle.json`
"""
import json
import logging

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

SALIDA = '_v71_calibracion_vs_pinnacle.json'

LIGAS = ['liga_mx', 'mls', 'brasil', 'argentina', 'usl_championship',
         'col_primera_a', 'per_liga1', 'uru_primera', 'chi_primera',
         'bra_serie_b', 'sudamericana', 'aut_bundesliga', 'rus_premier',
         'eng_league_one', 'mex_expansion', 'par_division']


def main():
    import cuotas_multi as cm
    import fixtures_espn as fx
    import name_mapper
    from league_engine import ClubEngine
    from config import LEAGUES

    cm.precargar('futbol')
    salida = []
    todos = []

    for clave in LIGAS:
        if clave not in LEAGUES:
            continue
        try:
            eng = ClubEngine(clave)
        except Exception as e:
            logger.warning(f'{clave}: motor no disponible ({e})')
            continue
        if not getattr(eng, 'listo', False):
            continue
        catalogo = list(eng.stats.keys())
        fixtures = fx.fixtures_liga(clave)
        filas = []
        for f in fixtures:
            r = cm.cuotas_partido('futbol', f['home'], f['away'],
                                  odds_espn={k: f.get(k) for k in
                                             ('odd_home', 'odd_draw',
                                              'odd_away', 'casa') if f.get(k)})
            pin = r.get('pinnacle')
            if not pin or not pin.get('home') or not pin.get('away'):
                continue
            just = cm.devig({k: v for k, v in pin.items() if v}, metodo='potencia')
            if len(just) < 3:
                continue
            h = name_mapper.mapear(f['home'], catalogo, contexto=f'cal/{clave}')
            a = name_mapper.mapear(f['away'], catalogo, contexto=f'cal/{clave}')
            if not (h and a) or h == a:
                continue
            pred = eng.predecir(h, a)
            if 'error' in pred:
                continue
            p = pred['prediction']['probabilities']
            modelo = {'home': p['home'], 'draw': p['draw'], 'away': p['away']}
            for lado in ('home', 'draw', 'away'):
                filas.append({'lado': lado, 'p_modelo': modelo[lado],
                              'p_pin': just.get(lado, np.nan)})
            k_mod = max(modelo, key=modelo.get)
            filas.append({'lado': 'PICK', 'p_modelo': modelo[k_mod],
                          'p_pin': just.get(k_mod, np.nan),
                          'partido': f"{h} vs {a}", 'seleccion': k_mod})
        if not filas:
            continue
        d = pd.DataFrame(filas).dropna(subset=['p_pin'])
        sel = d[d['lado'] != 'PICK']
        pk = d[d['lado'] == 'PICK']
        if len(sel) < 6:
            continue
        info = {
            'clave': clave, 'n_partidos': int(len(pk)),
            'n_selecciones': int(len(sel)),
            'sesgo_medio': round(float((sel['p_modelo'] - sel['p_pin']).mean()), 4),
            'mae': round(float((sel['p_modelo'] - sel['p_pin']).abs().mean()), 4),
            'corr': round(float(sel['p_modelo'].corr(sel['p_pin'])), 4)
                    if sel['p_modelo'].std() > 0 else None,
            'sesgo_pick': round(float((pk['p_modelo'] - pk['p_pin']).mean()), 4)
                          if len(pk) else None,
            'p_modelo_medio_pick': round(float(pk['p_modelo'].mean()), 4) if len(pk) else None,
            'p_pin_medio_pick': round(float(pk['p_pin'].mean()), 4) if len(pk) else None,
            'sobreconfianza_grave': int(((pk['p_modelo'] > 0.70)
                                         & (pk['p_pin'] < 0.60)).sum()) if len(pk) else 0,
        }
        salida.append(info)
        todos.append(sel.assign(liga=clave))
        logger.info(f"{clave:20s} n={info['n_partidos']:3d} "
                    f"sesgo={info['sesgo_medio']:+.4f} "
                    f"sesgo_pick={info['sesgo_pick']:+.4f} "
                    f"MAE={info['mae']:.4f} corr={info['corr']} "
                    f"sobreconf={info['sobreconfianza_grave']}")

    glob = None
    if todos:
        T = pd.concat(todos)
        glob = {'n': int(len(T)),
                'sesgo_medio': round(float((T['p_modelo'] - T['p_pin']).mean()), 4),
                'mae': round(float((T['p_modelo'] - T['p_pin']).abs().mean()), 4),
                'corr': round(float(T['p_modelo'].corr(T['p_pin'])), 4)}
        logger.info(f"== GLOBAL n={glob['n']} sesgo={glob['sesgo_medio']:+.4f} "
                    f"MAE={glob['mae']:.4f} corr={glob['corr']}")
    with open(SALIDA, 'w', encoding='utf-8') as f:
        json.dump({'generado': str(pd.Timestamp.now()), 'global': glob,
                   'por_liga': salida}, f, ensure_ascii=False, indent=1)


if __name__ == '__main__':
    main()
