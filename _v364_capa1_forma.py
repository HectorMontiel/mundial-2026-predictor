#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v364 — ¿La forma reciente separa las verdes de las rojas en la Capa 1 🏆?

El usuario: «la Capa 1 también debería tener las ⭐ ELIGE de acuerdo al
histórico reciente, los partidos recientes y el rendimiento; evalúa la
hipótesis con simulaciones, a ver si sube el acierto, si agarramos más verdes».

(Lo que ya se sabía — `filtrar-capa1-por-forma`: en los 💰 errores de precio
la forma sube el ACIERTO pero no la ganancia. Aquí se pregunta sólo por el
acierto, y en las 🏆.)

Datos: `_v361_metodo.preparar()` (52.000 partidos de 26 ligas con
estadística real y cuota de cierre; los rasgos de cada equipo, sólo con lo
jugado ANTES). Las 🏆 se reconstruyen con la casa: doble oportunidad o
ganador del equipo con la casa sin margen entre 80 % y 88 % (lo que pide la
Capa 1; el filtro del modelo ≥ 70 % casi siempre se cumple ahí).
Hipótesis (fijadas antes de mirar):
  H1 el equipo apostado viene en forma: ≥ 2,0 puntos por partido en sus 5 últimos
  H2 el rival viene mal: ≤ 1,0 punto por partido en sus 5 últimos
  H3 H1 y H2
  H4 el apostado en el tercio de arriba de la tabla y el rival en la mitad de abajo
  H5 el apostado mete ≥ 1,8 goles por partido en sus 5 últimos
  H6 el rival recibe ≥ 1,8 goles por partido en sus 5 últimos
  H7 el apostado juega de local
Se mide el acierto con y sin la hipótesis en dos mitades de fechas, con
bootstrap de la diferencia. Escribe `_v364_capa1_forma.json`."""
import json
import sys

import numpy as np
import pandas as pd

import _v361_metodo as V

rng = np.random.default_rng(3641)


def dif(a, b, n=2000):
    a, b = np.asarray(a, float), np.asarray(b, float)
    if len(a) < 30 or len(b) < 30:
        return None
    ds = [a[rng.integers(0, len(a), len(a))].mean() - b[rng.integers(0, len(b), len(b))].mean()
          for _ in range(n)]
    return [round(float(np.mean(ds)), 4), round(float(np.percentile(ds, 5)), 4)]


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    e = V.preparar().sort_values(['fecha', 'mid']).reset_index(drop=True)
    g = e.groupby(['liga', 'temporada', 'equipo'], sort=False)
    e['l5_pts'] = g['pts'].transform(lambda x: x.shift(1).rolling(5, 3).mean())
    r = e[['mid', 'equipo', 'l5_pts']].rename(columns={'equipo': 'rival', 'l5_pts': 'r_l5_pts'})
    e = e.merge(r, on=['mid', 'rival'], how='left')
    e = e.dropna(subset=['p_gana', 'p_empate', 'gf', 'gc'])
    dc = e[(e.p_gana + e.p_empate).between(0.80, 0.88)].assign(tipo='doble', y=lambda x: (x.gf >= x.gc).astype(int))
    gw = e[e.p_gana.between(0.80, 0.88)].assign(tipo='ganador', y=lambda x: (x.gf > x.gc).astype(int))
    c = pd.concat([dc, gw], ignore_index=True)
    mitad = c.fecha.quantile(0.5)
    c['tramo'] = np.where(c.fecha < mitad, 'A', 'B')
    out = {'n': int(len(c)), 'mitad': str(mitad)[:10],
           'base': {tr: round(float(c[c.tramo == tr].y.mean()), 4) for tr in ('A', 'B')}}
    print('🏆 reconstruidas', len(c), 'acierto base', out['base'], 'mitad', out['mitad'])
    H = {'H1 el apostado en forma (≥ 2,0 pts/partido en 5)': c.l5_pts >= 2.0,
         'H2 el rival mal (≤ 1,0 pts/partido en 5)': c.r_l5_pts <= 1.0,
         'H3 H1 y H2': (c.l5_pts >= 2.0) & (c.r_l5_pts <= 1.0),
         'H4 apostado arriba, rival en la mitad de abajo': (c.pos_rel <= 1 / 3) & (c.r_pos_rel > 0.5),
         'H5 el apostado mete ≥ 1,8 por partido en 5': c.l5_gf >= 1.8,
         'H6 el rival recibe ≥ 1,8 por partido en 5': c.r_l5_gc >= 1.8,
         'H7 el apostado juega de local': c.local == 1}
    out['hipotesis'] = {}
    for nom, f in H.items():
        f = f.fillna(False)
        rr = {}
        for tr in ('A', 'B'):
            a, b = c[f & (c.tramo == tr)], c[~f & (c.tramo == tr)]
            rr[tr] = {'n': int(len(a)), 'acierto': round(float(a.y.mean()), 4) if len(a) else None,
                      'resto': round(float(b.y.mean()), 4), 'dif_p5': dif(a.y, b.y)}
        ok = all(rr[t]['dif_p5'] and rr[t]['dif_p5'][1] > 0 for t in ('A', 'B'))
        rr['pasa'] = bool(ok)
        out['hipotesis'][nom] = rr
        print('%-48s A %s · B %s %s' % (nom, (rr['A']['n'], rr['A']['acierto'], rr['A']['resto']),
                                       (rr['B']['n'], rr['B']['acierto'], rr['B']['resto']),
                                       '✔ PASA' if ok else ''))
    json.dump(out, open('_v364_capa1_forma.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1,
              default=str)


if __name__ == '__main__':
    main()
