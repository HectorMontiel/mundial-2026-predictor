#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v79 — ¿El aplanamiento de MLB es del modelo o del deporte?

Antes de meter features nuevas hay que saber contra qué se compite. Si el
mercado sharp también reparte las probabilidades entre 45 % y 55 %, entonces
«todo da 50-50» es una propiedad del béisbol y el modelo no está roto. Si el
mercado abre mucho más el abanico, el modelo se está quedando corto y hay
margen real que ganar.

Se compara sobre los partidos de HOY con cuota de Pinnacle (la referencia
eficiente), quitando el margen de la casa.
"""
import logging
import numpy as np

logging.basicConfig(level=logging.WARNING)


def main():
    import cuotas_multi as cm
    import mlb_statsapi
    from engines.mlb_engine import MLBEngine, codigo_mlb

    eng = MLBEngine().cargar_modelo()
    abridores = mlb_statsapi.indice_abridores()
    cm.precargar('mlb')

    idx = {}
    for i in (cm._indice('mlb'), cm._indice_bov('mlb'), cm._indice_pdt('mlb')):
        for v in (i or {}).values():
            if v.get('home') and v.get('away'):
                idx.setdefault((codigo_mlb(v['home']), codigo_mlb(v['away'])), v)

    filas = []
    for (hc, ac), v in idx.items():
        hp, ap = abridores.get((hc, ac), ('', ''))
        pred = eng.predecir(hc, ac, home_pitcher=hp, away_pitcher=ap)
        if 'error' in pred:
            continue
        c = cm.cuotas_partido('mlb', v['home'], v['away'])
        pin = c.get('pinnacle') or {}
        ch, ca = pin.get('home'), pin.get('away')
        if not ch or not ca or ch <= 1 or ca <= 1:
            mejor = c.get('mejor') or {}
            ch = (mejor.get('home') or {}).get('cuota')
            ca = (mejor.get('away') or {}).get('cuota')
        if not ch or not ca or float(ch) <= 1 or float(ca) <= 1:
            continue
        ih, ia = 1 / float(ch), 1 / float(ca)
        p_mkt = ih / (ih + ia)
        filas.append((hc, ac, pred['prob_home'], p_mkt, bool(hp and ap)))

    if not filas:
        print('sin partidos con cuota ahora mismo')
        return

    pm = np.array([f[2] for f in filas])
    pk = np.array([f[3] for f in filas])
    print(f"\n{len(filas)} partidos con cuota y predicción\n")
    print(f"{'vis':>4} {'loc':>5}   {'modelo':>7} {'mercado':>8} {'dif':>7}  abridor")
    for hc, ac, a, b, tiene in sorted(filas, key=lambda x: -abs(x[2] - x[3])):
        print(f"{ac:>4} @ {hc:>4}   {a:7.3f} {b:8.3f} {a-b:+7.3f}  "
              f"{'sí' if tiene else 'NO'}")

    def desc(v, etiq):
        print(f"\n  {etiq}")
        print(f"    media {v.mean():.4f}   std {v.std():.4f}")
        print(f"    min {v.min():.4f}   max {v.max():.4f}   "
              f"recorrido {v.max()-v.min():.4f}")
        print(f"    fracción entre 45 % y 55 %: "
              f"{((v > .45) & (v < .55)).mean():.1%}")

    desc(pm, 'MODELO')
    desc(pk, 'MERCADO (sin margen)')
    print(f"\n  correlación modelo/mercado: {np.corrcoef(pm, pk)[0,1]:.4f}")
    print(f"  error absoluto medio        : {np.abs(pm-pk).mean():.4f}")
    print(f"  RATIO de dispersión (modelo/mercado): "
          f"{pm.std()/max(pk.std(),1e-9):.3f}")
    print("\n  Lectura: un ratio muy por debajo de 1 significa que el modelo "
          "\n  comprime el abanico respecto al mercado — le falta señal, no le "
          "\n  sobra. Un ratio cercano a 1 significa que el 50-50 es del deporte.")


if __name__ == '__main__':
    main()
