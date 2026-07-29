#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v80 — ¿A qué debe caer una liga que no tiene potencia para decidir su propio w?

El problema
-----------
`recalibrate_from_history` calcula un `w` por liga y luego aplica una regla de
adopción. La liga que no la pasa se queda **sin corrección (w = 1,00)**.

Eso es una decisión implícita que nadie midió, y va contra la evidencia que sí
está medida:

  · El `w` GLOBAL (0,25) se elige sobre 75.131 partidos y se valida en un
    pliegue aparte de 14.636: log-loss 0,8056 → 0,7855, precisión 0,5808 →
    0,5987. Es el resultado más sólido que tiene el proyecto.
  · El `w` POR LIGA se decide con muestras de 52 a 124 picks. Con 38 ligas
    evaluadas, eso son 38 decisiones tomadas sobre ruido.

Cuando una liga no tiene datos para decidir, mandarla a w=1,00 no es
«abstenerse»: es elegir activamente la opción que la evidencia global descarta.
Lo neutral es caer al w global.

Consecuencia práctica medida en la v79: en julio eso deja **el 69 % de los
partidos del día sin encoger**, porque las ligas que juegan en verano son justo
las que menos muestra tienen.

Qué se compara
--------------
  A) ACTUAL   — w por liga si fue adoptada; 1,00 si no.
  B) GLOBAL   — w por liga si fue adoptada; w global (0,25) si no.
  C) UNIFORME — w global para todas.

Con el criterio del proyecto: ROI fuera de muestra Y bootstrap p5.
"""
import json
import logging

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
log = logging.getLogger('politica')

LEDGER = 'pick_ledger_total.csv'
N_BOOT = 5000
W_GLOBAL = 0.25


def simular(d, pesos, umbral_prob=0.55, min_ev=0.03, min_cuota=1.50):
    """
    Emite los picks que produccion haria con ese mapa de pesos.

    v80 — se replica EXACTAMENTE el metodo de `validacion_deportes.calcular`,
    que es el que decide la Capa 1, y no una version propia. Dos detalles que
    la primera version de este script se salto y que cambian el resultado:

      · PRECIO: `max(cuota, pinnacle)` — line shopping, que es lo que toma
        produccion. Medir con la cuota base subestima el ROI (en la v76 se vio
        la diferencia: +4,43 % con la media frente a +5,80 % con el mejor
        precio).
      · UN pick por partido, el del **argmax** de la probabilidad corregida.
        Evaluar los tres lados a la vez infla el numero de apuestas con
        selecciones que produccion nunca emitiria.
    """
    gan, det = [], []
    for liga, g in d.groupby('liga'):
        w = pesos(liga)
        pm = g[['p_home', 'p_draw', 'p_away']].values.astype(float)
        mk = g[['m_home', 'm_draw', 'm_away']].values.astype(float)
        cu = np.fmax(
            g[['cuota_home', 'cuota_draw', 'cuota_away']].fillna(0)
             .values.astype(float),
            np.nan_to_num(g[['pin_home', 'pin_draw', 'pin_away']]
                          .values.astype(float), nan=0.0))
        res = g['resultado'].values.astype(int)
        p = w * pm + (1 - w) * mk
        s = p.sum(axis=1, keepdims=True)
        p = np.divide(p, s, out=np.full_like(p, np.nan), where=s > 0)
        if not np.isfinite(p).all():
            ok = np.isfinite(p).all(axis=1)
            p, cu, res = p[ok], cu[ok], res[ok]
        if len(p) == 0:
            continue
        f = np.arange(len(p))
        k = p.argmax(axis=1)
        prob, cuota = p[f, k], cu[f, k]
        e = cuota * prob - 1.0
        sel = (prob > umbral_prob) & (e > min_ev) & (cuota > min_cuota)
        for i in np.flatnonzero(sel):
            gan.append(cuota[i] - 1.0 if k[i] == res[i] else -1.0)
            det.append(liga)
    if not gan:
        return None
    g = np.array(gan, float)
    rng = np.random.default_rng(11)
    bs = g[rng.integers(0, len(g), size=(N_BOOT, len(g)))].mean(axis=1)
    return {'n': int(len(g)), 'roi': float(g.mean()),
            'p5': float(np.percentile(bs, 5)),
            'p95': float(np.percentile(bs, 95)),
            'hit': float((g > 0).mean()),
            'ligas': int(len(set(det)))}


def main():
    import calibracion_mercado as cal

    # Se carga con el MISMO lector que usa la validación, que es quien añade
    # las columnas `m_*` (probabilidad justa del mercado, sin margen).
    import recalibrate_from_history as rec
    d = rec.cargar(LEDGER)
    d = d[(d['deporte'] == 'Fútbol') & d['cuota_home'].notna()]
    log.info(f'{len(d)} filas de fútbol con cuota · '
             f"{d['liga'].nunique()} ligas")

    adoptadas = {k for k in
                 (json.load(open('calibracion_mercado.json', encoding='utf-8'))
                  .get('ligas') or {})}
    adoptadas = {k.lower() for k in adoptadas}
    log.info(f'{len(adoptadas)} ligas con peso adoptado hoy')

    politicas = {
        'A) ACTUAL   (no adoptada -> w=1,00)':
            lambda l: cal.peso_modelo(l),
        'B) GLOBAL   (no adoptada -> w=0,25)':
            lambda l: (cal.peso_modelo(l) if l.lower() in adoptadas
                       else W_GLOBAL),
        'C) UNIFORME (w=0,25 para todas)':
            lambda l: W_GLOBAL,
    }

    print('\n' + '=' * 92)
    print(f"{'política':38s} {'n':>6} {'ligas':>6} {'ROI':>9} "
          f"{'p5':>9} {'p95':>9} {'acierto':>8}")
    print('=' * 92)
    salida = {}
    for nombre, fn in politicas.items():
        r = simular(d, fn)
        if not r:
            print(f'{nombre:38s}  sin picks')
            continue
        salida[nombre] = r
        print(f"{nombre:38s} {r['n']:6d} {r['ligas']:6d} {r['roi']:9.2%} "
              f"{r['p5']:9.2%} {r['p95']:9.2%} {r['hit']:8.1%}")
    print('=' * 92)

    a = salida.get('A) ACTUAL   (no adoptada -> w=1,00)')
    b = salida.get('B) GLOBAL   (no adoptada -> w=0,25)')
    if a and b:
        print(f"\nB frente a A:  ROI {b['roi']-a['roi']:+.2%}   "
              f"p5 {b['p5']-a['p5']:+.2%}   picks {b['n']-a['n']:+d}")
        mejor = (b['roi'] > a['roi'] and b['p5'] > a['p5'])
        print(f"\nVEREDICTO: {'ADOPTAR B' if mejor else 'NO ADOPTAR B'}"
              f" — criterio del proyecto: ROI Y p5 tienen que mejorar.")
    json.dump(salida, open('_v80_politica_w.json', 'w', encoding='utf-8'),
              indent=1, ensure_ascii=False)


if __name__ == '__main__':
    main()
