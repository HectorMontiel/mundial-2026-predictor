#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v88 — MLB ya entra en el barrido. ¿Por qué hoy no da picks?

Con el filtro de la v88 el barrido evalúa 15 partidos DE MLB de verdad (antes
metía 64 entradas de LMB, Japón, Corea, Taiwán y Triple-A). Hoy ninguno pasa
los filtros. Hay dos explicaciones posibles y conviene distinguirlas:

  · hoy las casas coinciden y no hay valor -> correcto, no hay nada que tocar;
  · los umbrales son inalcanzables -> entonces MLB nunca daría picks y habría
    que revisarlos.

Esto mira lo cerca que se quedan, que es lo que separa una cosa de la otra.
"""
import sys

import numpy as np

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass


def main():
    import alpha_finder as af
    import cuotas_multi as cm
    from engines.mlb_engine import (MLBEngine, codigo_mlb, es_partido_mlb,
                                    CODIGO_A_NOMBRE)

    print('=' * 80)
    print('v88 · ¿ESTÁ MLB CERCA DE DAR PICKS?')
    print('=' * 80)
    print(f'  umbrales de la vía de VALOR DE MERCADO:')
    print(f'    prob mínima : {af.VS_MLB_PROB_MIN:.0%}')
    print(f'    EV mínimo   : {af.VS_MLB_EV_MIN:.0%}')
    print(f'    cuota mínima: {af.MIN_CUOTA}')
    print(f'  umbral del MODELO: prob > {af.UMBRAL_CONF["MLB"]:.0%}')

    cm.precargar('mlb')
    vistos, filas = set(), []
    for idx in (cm._indice('mlb'), cm._indice_bov('mlb'), cm._indice_pdt('mlb')):
        for v in (idx or {}).values():
            h, a = v.get('home'), v.get('away')
            if not (h and a) or not es_partido_mlb(h, a):
                continue
            cl = (codigo_mlb(h), codigo_mlb(a))
            if cl in vistos:
                continue
            vistos.add(cl)
            vm = cm.valor_vs_sharp('mlb', h, a)
            for x in (vm.get('valor') or [])[:1]:
                filas.append({'partido': f'{CODIGO_A_NOMBRE.get(cl[1], a)} @ '
                                         f'{CODIGO_A_NOMBRE.get(cl[0], h)}',
                              'lado': x.get('lado'),
                              'prob': x.get('prob_justa', 0),
                              'ev': x.get('ev', 0),
                              'cuota': x.get('cuota', 0),
                              'casa': x.get('casa')})

    print(f'\n  partidos de MLB con precio comparable: {len(vistos)}')
    print(f'  con alguna selección por encima de Pinnacle: {len(filas)}')

    if filas:
        filas.sort(key=lambda f: -f['ev'])
        print(f'\n  {"partido":<44} {"prob":>7} {"EV":>8} {"cuota":>7} {"casa":>12}')
        for f in filas[:12]:
            pasa = (f['prob'] >= af.VS_MLB_PROB_MIN
                    and f['ev'] >= af.VS_MLB_EV_MIN
                    and f['cuota'] > af.MIN_CUOTA)
            print(f'  {f["partido"][:44]:<44} {f["prob"]:7.1%} {f["ev"]:8.2%} '
                  f'{f["cuota"]:7.2f} {str(f["casa"])[:12]:>12}'
                  f'{"  <- PASA" if pasa else ""}')

        evs = np.array([f['ev'] for f in filas])
        print(f'\n  EV: máximo {evs.max():+.2%} · mediana {np.median(evs):+.2%}')
        print(f'  hace falta {af.VS_MLB_EV_MIN:+.0%} -> '
              f'faltan {af.VS_MLB_EV_MIN - evs.max():+.2%} al mejor')

    # y el modelo
    eng = MLBEngine().cargar_modelo()
    r = eng.apuestas_dia(min_prob=0.0, min_ev=-9, min_cuota=1.0)
    picks = r.get('picks') or []
    print(f'\n  el MODELO evalúa {r.get("evaluados", 0)} partidos; sin filtros '
          f'produce {len(picks)} selecciones')
    if picks:
        picks.sort(key=lambda p: -(p.get('prob') or 0))
        print(f'  {"partido":<44} {"prob":>7} {"EV":>8} {"cuota":>7}')
        for p in picks[:8]:
            print(f'  {str(p.get("partido"))[:44]:<44} {p.get("prob", 0):7.1%} '
                  f'{p.get("ev", 0):8.2%} {p.get("cuota", 0):7.2f}')
        probs = np.array([p.get('prob', 0) for p in picks])
        print(f'\n  prob máxima del modelo hoy: {probs.max():.1%} '
              f'(hace falta > {af.UMBRAL_CONF["MLB"]:.0%})')

    print('\n' + '=' * 80)
    print('  Nota: el modelo de MLB está FUERA de la Capa 1 por decisión medida')
    print('  (ROI +6,69 % pero p5 −1,03 %: sin edge validado). La vía que sí')
    print('  puede dar picks de MLB es la de valor de mercado, que no usa el')
    print('  modelo y tiene p5 +1,67 % fuera de muestra sobre 27.977 juegos.')


if __name__ == '__main__':
    main()
