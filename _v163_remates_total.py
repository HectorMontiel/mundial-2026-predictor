#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v163 — EL TOTAL DEL PARTIDO: ¿sumar las dos lambdas o usar la media de la liga?

Esta pregunta ya se contestó dos veces en este proyecto y salió al revés cada
vez, así que no se puede heredar de ninguna de las dos:

  · CÓRNERS (§10.7): gana la media de la competición. La parte variable del
    total tiene correlación −0,0012 con el total real, o sea que sumar las dos
    lambdas mete varianza sin señal.
  · TARJETAS (§11): gana el estimador del partido, 0,0119 contra 0,0488 de la
    media de liga.

Los remates podrían ir por cualquiera de los dos lados. A favor de sumar: la
correlación por equipo sale 0,31-0,56, mucho más alta que en córners. En contra:
un partido cerrado hace que los dos equipos tiren MENOS, y ese efecto podría
estar ya dentro de cada lambda y contarse dos veces al sumar.

Se mide igual que lo demás: probabilidad contra frecuencia real en las líneas
que cotiza la casa, más Brier y ECE para que no gane un empate de sesgos.

    python _v163_remates_total.py [liga ...]
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

SALIDA = '_v163_remates_total.json'
LINEAS = {'tot': (20.5, 22.5, 24.5, 26.5), 'on': (6.5, 7.5, 8.5, 9.5)}
MIN_PREV = 5


def main():
    from _v163_remates_estimadores import _p_mas, marco, dispersion, metricas

    ligas = sys.argv[1:]
    if not ligas:
        ligas = json.load(open('_v163_cobertura_remates.json',
                               encoding='utf-8'))['con_remates']
    resultado = {}
    for obj in ('tot', 'on'):
        print('=' * 78)
        print('TOTAL DEL PARTIDO — remates %s'
              % ('TOTALES' if obj == 'tot' else 'A PUERTA'))
        print('=' * 78)
        acumulado, por_liga = {}, {}
        for clave in ligas:
            df = marco(clave)
            if df is None or len(df) < 600:
                continue
            col_h, col_a = 'home_rem_' + obj, 'away_rem_' + obj
            df = df.sort_values('date').reset_index(drop=True)
            hist, lig = {}, {'casa': [], 'fuera': []}

            def H(eq):
                return hist.setdefault(eq, {'tira_casa': [], 'tira_fuera': [],
                                            'conc_casa': [], 'conc_fuera': []})

            filas = []
            for f in df.itertuples(index=False):
                vh, va = float(getattr(f, col_h)), float(getattr(f, col_a))
                hh, ha = H(f.home_team), H(f.away_team)
                ok = (len(hh['tira_casa']) >= MIN_PREV
                      and len(ha['tira_fuera']) >= MIN_PREV
                      and len(ha['conc_fuera']) >= MIN_PREV
                      and len(hh['conc_casa']) >= MIN_PREV
                      and len(lig['casa']) >= 60)
                if ok:
                    lh = (np.mean(hh['tira_casa'][-10:])
                          + np.mean(ha['conc_fuera'][-10:])) / 2.0
                    la = (np.mean(ha['tira_fuera'][-10:])
                          + np.mean(hh['conc_casa'][-10:])) / 2.0
                    filas.append({
                        'real': vh + va,
                        'suma_lambdas': float(lh + la),
                        'media_liga': float(np.mean(lig['casa'])
                                            + np.mean(lig['fuera'])),
                    })
                hh['tira_casa'].append(vh)
                hh['conc_casa'].append(va)
                ha['tira_fuera'].append(va)
                ha['conc_fuera'].append(vh)
                lig['casa'].append(vh)
                lig['fuera'].append(va)
            d = pd.DataFrame(filas)
            if len(d) < 600:
                continue
            tot_real = (df[col_h] + df[col_a]).astype(float)
            disp = dispersion(tot_real)
            corr = float(np.corrcoef(d['suma_lambdas'], d['real'])[0, 1])
            print('%-16s n=%5d  disp_total=%.3f  media=%5.2f  '
                  'corr(suma,real)=%.3f'
                  % (clave, len(d), disp, float(tot_real.mean()), corr),
                  flush=True)
            fila_liga = {}
            for est in ('suma_lambdas', 'media_liga'):
                acc = {'marginal': [], 'brier': [], 'ece': []}
                for L in LINEAS[obj]:
                    p = d[est].apply(lambda m: _p_mas(m, L, disp))
                    real = (d['real'] > L).astype(float)
                    mt = metricas(p, real)
                    if mt is None:
                        continue
                    for k in acc:
                        acc[k].append(mt[k])
                if not acc['marginal']:
                    continue
                res = {k: float(np.nanmean(v)) for k, v in acc.items()}
                acumulado.setdefault(est, []).append((len(d), res))
                fila_liga[est] = {k: round(v, 5) for k, v in res.items()}
            por_liga[clave] = {'n': int(len(d)), 'dispersion': round(disp, 4),
                               'media': round(float(tot_real.mean()), 3),
                               'corr': round(corr, 4), 'errores': fila_liga}
        if not acumulado:
            continue
        filas = []
        for est, vals in acumulado.items():
            n = sum(v[0] for v in vals)
            filas.append({'estimador': est, 'n': n,
                          **{k: sum(v[0] * v[1][k] for v in vals) / n
                             for k in ('marginal', 'brier', 'ece')}})
        print()
        print('%-16s %10s %10s %10s'
              % ('estimador', 'marginal', 'brier', 'ECE'))
        print('-' * 49)
        for f in sorted(filas, key=lambda f: f['brier']):
            print('%-16s %10.5f %10.5f %10.5f'
                  % (f['estimador'], f['marginal'], f['brier'], f['ece']))
        mejor = min(filas, key=lambda f: f['brier'])
        print('\nMEJOR: %s\n' % mejor['estimador'])
        resultado[obj] = {'filas': sorted(filas, key=lambda f: f['brier']),
                          'mejor': mejor, 'por_liga': por_liga}
    json.dump(resultado, open(SALIDA, 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    print('escrito %s' % SALIDA)
    return 0


if __name__ == '__main__':
    sys.exit(main())
