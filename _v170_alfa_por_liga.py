#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v170 — LA α DE GOLES, UNA POR COMPETICIÓN.

Qué cambia respecto a la v166
-----------------------------
La v166 encoge la probabilidad de goles hacia la casa con un peso ÚNICO (0,25,
el suelo de `calibracion_mercado`). Medido en la v169, con ese peso quedan
**cinco competiciones por encima del 0,05** de error de calibración:

    sco_premiership 0,078 · sco_championship 0,063 · turquía 0,062
    bundesliga 0,052 · eredivisie 0,051

El encargo pide lo evidente: que la α dependa de lo bueno que sea el modelo en
ESA liga. Aquí se ajusta una por competición sobre su propio histórico, en vez
de fijarla.

CÓMO SE ELIGE, Y POR QUÉ ASÍ
-----------------------------
Por ECE, la métrica con la que este proyecto decide desde la v163, sobre una
rejilla de 0 a 1. Con dos cautelas que no son adorno:

  · **muestra mínima.** Con menos de 300 partidos el mínimo de la rejilla es
    ruido: se elegiría el α que mejor ajusta ESE ruido. Esas ligas heredan la
    α global, que es encogimiento jerárquico de manual y lo que ya hace
    `calibracion_mercado.peso_modelo` desde la v80.
  · **validación fuera de muestra.** El α se ajusta sobre las temporadas
    ANTIGUAS y se comprueba sobre la ÚLTIMA. Sin eso, «mejora el ECE» sólo
    dice que la rejilla encontró su propio mínimo — que es el error que la
    bitácora ya documenta dos veces.

    python _v170_alfa_por_liga.py
"""
import json
import logging
import sys
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings('ignore')
logging.basicConfig(level=logging.ERROR)
for _f in (sys.stdout, sys.stderr):
    try:
        _f.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

SALIDA = 'alfa_goles_por_liga.json'
DIAG = '_v170_alfa_por_liga.json'
MIN_N = 300
REJILLA = [round(x, 2) for x in np.arange(0.0, 1.001, 0.05)]
UMBRAL_ACEPTABLE = 0.05


def ece(p, y, n_bins: int = 10):
    p, y = np.asarray(p, float), np.asarray(y, float)
    if len(p) < 100:
        return None
    b = np.quantile(p, np.linspace(0, 1, n_bins + 1))
    b[0], b[-1] = -1e-9, 1 + 1e-9
    t = 0.0
    for i in range(n_bins):
        m = (p >= b[i]) & (p < b[i + 1])
        if m.sum():
            t += m.sum() * abs(p[m].mean() - y[m].mean())
    return float(t / len(p))


def devig2(c1, c2):
    return (1.0 / c1) / ((1.0 / c1) + (1.0 / c2))


def _mejor_alfa(p_mod, p_mkt, y):
    """El α que minimiza el ECE en esa muestra, o `None` si no da para medir."""
    mejor, mejor_e = None, None
    for a in REJILLA:
        e = ece(a * p_mod + (1 - a) * p_mkt, y)
        if e is None:
            continue
        if mejor_e is None or e < mejor_e:
            mejor, mejor_e = a, e
    return mejor, mejor_e


def main():
    d = pd.read_csv('pick_ledger_totales.csv')
    d = d[d['cuota_over25'].notna() & d['cuota_under25'].notna()].copy()
    d = d[(d['cuota_over25'] > 1) & (d['cuota_under25'] > 1)]
    d['p_mkt'] = devig2(d['cuota_over25'].astype(float).values,
                        d['cuota_under25'].astype(float).values)
    d['p_mod'] = d['p_over_2.5'].astype(float)
    d['y'] = d['over_2.5_real'].astype(int)
    d['fecha'] = pd.to_datetime(d['fecha'], errors='coerce')

    # la α GLOBAL, para las ligas sin muestra propia
    a_glob, e_glob = _mejor_alfa(d['p_mod'].values, d['p_mkt'].values,
                                 d['y'].values)
    print('α global sobre %d partidos: %.2f (ECE %.5f)\n'
          % (len(d), a_glob, e_glob))

    print('%-22s %6s %6s %9s %9s %9s %9s'
          % ('competición', 'n', 'α', 'ECE.25', 'ECE α', 'fuera α',
             'fuera .25'))
    print('-' * 80)
    alfas, filas = {}, []
    for lg, g in d.groupby('liga'):
        n = len(g)
        if n < MIN_N:
            filas.append({'liga': lg, 'n': n, 'alfa': None,
                          'motivo': 'muestra corta'})
            continue
        # ajuste en lo antiguo, comprobación en lo último
        corte = g['fecha'].quantile(0.75)
        tr, te = g[g['fecha'] <= corte], g[g['fecha'] > corte]
        a, _ = _mejor_alfa(tr['p_mod'].values, tr['p_mkt'].values,
                           tr['y'].values)
        if a is None:
            continue
        e025 = ece(0.25 * g['p_mod'] + 0.75 * g['p_mkt'], g['y'])
        ea = ece(a * g['p_mod'] + (1 - a) * g['p_mkt'], g['y'])
        # FUERA DE MUESTRA, LAS DOS POLITICAS SOBRE EL MISMO TRAMO.
        # Comparar el alfa fuera de muestra contra el 0,25 DENTRO seria
        # compararlo contra un numero que ya vio esos partidos.
        fuera = fuera025 = None
        if len(te) >= 100:
            fuera = ece(a * te['p_mod'] + (1 - a) * te['p_mkt'], te['y'])
            fuera025 = ece(0.25 * te['p_mod'] + 0.75 * te['p_mkt'], te['y'])
        alfas[lg] = a
        filas.append({'liga': lg, 'n': n, 'alfa': a,
                      'ece_025': None if e025 is None else round(e025, 5),
                      'ece_alfa': None if ea is None else round(ea, 5),
                      'ece_fuera': None if fuera is None else round(fuera, 5),
                      'ece_fuera_025': (None if fuera025 is None
                                        else round(fuera025, 5))})
        print('%-22s %6d %6.2f %9s %9s %9s %9s'
              % (lg, n, a,
                 '%.4f' % e025 if e025 is not None else '-',
                 '%.4f' % ea if ea is not None else '-',
                 '%.4f' % fuera if fuera is not None else '-',
                 '%.4f' % fuera025 if fuera025 is not None else '-'))

    med = [f for f in filas if f.get('ece_025') is not None]
    ok025 = sum(1 for f in med if f['ece_025'] <= UMBRAL_ACEPTABLE)
    okalfa = sum(1 for f in med if (f['ece_alfa'] or 9) <= UMBRAL_ACEPTABLE)
    print('\n  ligas medidas: %d' % len(med))
    print('  con ECE <= 0,05 con α=0,25 fijo ....  %d' % ok025)
    print('  con ECE <= 0,05 con α por liga .....  %d' % okalfa)
    dentro = [f for f in med if f.get('ece_fuera') is not None]
    if dentro:
        dentro = [f for f in dentro if f.get('ece_fuera_025') is not None]
        mejora = sum(1 for f in dentro
                     if f['ece_fuera'] <= f['ece_fuera_025'])
        print('\n  FUERA DE MUESTRA, las dos sobre el MISMO tramo:')
        print('    la α por liga mejora o iguala al 0,25 en %d de %d'
              % (mejora, len(dentro)))
        import statistics as _st
        print('    ECE medio fuera de muestra: α %.4f · 0,25 %.4f'
              % (_st.mean(f['ece_fuera'] for f in dentro),
                 _st.mean(f['ece_fuera_025'] for f in dentro)))

    doc = {'generado_por': '_v170_alfa_por_liga.py', 'n': int(len(d)),
           'alfa_global': a_glob, 'min_n': MIN_N, 'ligas': alfas}
    json.dump(doc, open(SALIDA, 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    json.dump({'resumen': doc, 'detalle': filas},
              open(DIAG, 'w', encoding='utf-8'), ensure_ascii=False, indent=1,
              default=float)
    print('\n-> %s  (%d ligas con α propia)' % (SALIDA, len(alfas)))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
