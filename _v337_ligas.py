# -*- coding: utf-8 -*-
"""
v337 — ¿LAS ROJAS SE CONCENTRAN EN ALGUNAS LIGAS? ¿HAY QUE CALIBRAR AHÍ?

El usuario: «¿las rojas tienen algún patrón de que sea alguna liga
específica donde hay más rojas? Puede que haga falta calibrar el modelo ahí».

No basta con contar rojas: una liga con muchas apuestas tiene muchas rojas.
Lo que se mide es el EXCESO = acierto real − lo prometido, con su error
(z = exceso / √(p(1−p)/n)). Y no basta con que una liga salga mal: tiene que
SEGUIR saliendo mal, o «calibrarla» empeora (ya pasó con los córners, v319).

  A. las «meter» REALES de la app (`_v331_meter_app.csv`, 26-sep a 6-oct)
  B. la simulación de la tarjeta con la regla de hoy (`_v335_sim_candidatas`)
  C. el histórico (2018-2026) con la regla de hoy (casa ≥ 74 %, modelo
     ≥ 70 %, cuota 1,15-1,35), y la prueba de verdad:
       · ¿el exceso de una liga en la 1.ª mitad predice el de la 2.ª?
       · quitar las ligas que salen mal al mirar, ¿mejora el juicio?
       · recalibrar el modelo por liga con lo visto al mirar, ¿mejora?
     bootstrap por día, frente a no hacer nada.

RESULTADOS (2026-10-07)
  · Reales (826): sólo liga_mx sale mal (13 apuestas, 46,2 % vs 75,0 %,
    z −2,40); 1 de 16 ligas, por azar se espera 0,4. Con la regla v335 en la
    simulación: 77,3 % (22).
  · Histórico con la regla de hoy (16.867, 34 ligas): NINGUNA con z < −1,96
    (por azar 0,9). El exceso de una liga en una mitad apenas predice el de la
    otra (correlación 0,27; ponderada 0,35). Quitar las ligas que salen mal
    al mirar: +0,05 a +0,18 pts, p5 < 0. Recalibrar el modelo por liga:
    +0,06 a +0,08 pts, p5 < 0. NO hay que calibrar por liga.
  · LO QUE SÍ HABÍA: buscando por qué las selecciones fallaban más, el precio
    de la casa de los GOLES POR EQUIPO salía de la línea del TOTAL del
    partido (`concordancia.prob_mercado`): equipo «más de 1,5» decía 73,0 %
    y pasaba 41,2 %. Corregido en la v337 (ver `concordancia`): simulación
    rehecha 80,4 % (907, 178 rojos) → 82,2 % (935, 166 rojos); juzgar 78,0 →
    81,8 % (p5 +2,35); goles por equipo 78,2 → 85,5 %.
"""
from __future__ import annotations

import io
import json
import sys

import numpy as np
import pandas as pd

import _v332_combinadas as C   # (ya deja la salida en UTF-8: no se envuelve dos veces)
rng = np.random.default_rng(337)


def tabla_ligas(d, liga, prom, verde, minimo=12, top=10, titulo=''):
    g = d.groupby(liga).agg(n=(verde, 'size'), verdes=(verde, 'mean'), prometido=(prom, 'mean'))
    g = g[g.n >= minimo]
    g['exceso'] = g.verdes - g.prometido
    g['z'] = g.exceso / np.sqrt(g.prometido * (1 - g.prometido) / g.n)
    g = g.sort_values('z')
    print('\n%s (ligas con ≥ %d apuestas: %d)' % (titulo, minimo, len(g)))
    print('   liga                         n   verdes  prometido  exceso    z')
    for lg, r in pd.concat([g.head(top), g.tail(3)]).drop_duplicates().iterrows():
        print('   %-26s %4d   %5.1f %%   %5.1f %%   %+5.1f   %+5.2f'
              % (str(lg)[:26], r.n, 100 * r.verdes, 100 * r.prometido, 100 * r.exceso, r.z))
    n_mal = int((g.z < -1.96).sum())
    print('   ligas con z < −1,96: %d de %d (por puro azar se esperan %.1f)'
          % (n_mal, len(g), 0.025 * len(g)))
    return g


def historico():
    x = C.patas()
    x = x[x.p_casa.notna()]
    x = x[(x.p_casa >= .74) & (x.p >= .70) & (x.cuota >= 1.15) & (x.cuota < 1.35)]
    return x.sort_values('p_casa', ascending=False).drop_duplicates('mid').reset_index(drop=True)


def boot_dif(base, nueva, n=3000):
    A = base.groupby('fecha').verde.agg(['sum', 'size'])
    B = nueva.groupby('fecha').verde.agg(['sum', 'size'])
    dd = sorted(set(A.index) | set(B.index))
    A, B = A.reindex(dd, fill_value=0).values, B.reindex(dd, fill_value=0).values
    d = []
    for _ in range(n):
        q = rng.integers(0, len(dd), len(dd))
        a, b = A[q].sum(0), B[q].sum(0)
        if a[1] and b[1]:
            d.append(b[0] / b[1] - a[0] / a[1])
    return 100 * np.mean(d), 100 * np.percentile(d, 5)


def main():
    out = {}
    # A. reales
    r = pd.read_csv('_v331_meter_app.csv')
    r = r[r.deporte == 'Fútbol']
    gA = tabla_ligas(r, 'clave_liga', 'prob', 'verde', titulo='A. «METER» REALES DE LA APP (26-sep a 6-oct, %d apuestas, %.1f %% verdes)'
                     % (len(r), 100 * r.verde.mean()))
    out['reales'] = gA.reset_index().to_dict('records')
    # B. simulación con la regla de hoy
    v = pd.read_csv('_v335_sim_candidatas.csv.gz')
    v = v[v.metida & v.acierto.notna()].copy()
    v['prom'] = v.p_mercado.fillna(v.ajustada)
    gB = tabla_ligas(v, 'liga', 'prom', 'acierto', titulo='B. SIMULACIÓN, REGLA DE HOY (%d apuestas, %.1f %% verdes)'
                     % (len(v), 100 * v.acierto.mean()))
    out['simulacion'] = gB.reset_index().to_dict('records')
    # C. histórico con la regla de hoy
    x = historico()
    x['fecha'] = pd.to_datetime(x.fecha)
    dias = np.sort(x.fecha.unique())
    corte = dias[int(len(dias) * 0.7)]
    mitad = dias[len(dias) // 2]
    gC = tabla_ligas(x, 'liga', 'p_casa', 'verde', minimo=100,
                     titulo='C. HISTÓRICO, REGLA DE HOY (%d apuestas, %.1f %% verdes)'
                     % (len(x), 100 * x.verde.mean()))
    out['historico'] = gC.reset_index().to_dict('records')
    # ¿persiste? exceso por liga en cada mitad
    e1 = x[x.fecha < mitad].groupby('liga').apply(lambda s: pd.Series({'n': len(s), 'e': (s.verde - s.p_casa).mean()}), include_groups=False)
    e2 = x[x.fecha >= mitad].groupby('liga').apply(lambda s: pd.Series({'n': len(s), 'e': (s.verde - s.p_casa).mean()}), include_groups=False)
    j = e1.join(e2, lsuffix='1', rsuffix='2').dropna()
    j = j[(j.n1 >= 80) & (j.n2 >= 80)]
    w = np.minimum(j.n1, j.n2)
    c = np.corrcoef(j.e1, j.e2)[0, 1]
    cw = np.cov(j.e1, j.e2, aweights=w)[0, 1] / np.sqrt(np.cov(j.e1, aweights=w) * np.cov(j.e2, aweights=w))
    print('\n¿PERSISTE? exceso de cada liga en la 1.ª mitad frente a la 2.ª (%d ligas con ≥ 80 en cada una):'
          % len(j))
    print('   correlación %.3f (ponderada por apuestas %.3f) — 0 = azar, 1 = la liga es siempre igual' % (c, cw))
    out['persistencia'] = [float(c), float(cw), int(len(j))]
    # reglas por liga, elegidas al mirar y juzgadas después
    M, J = x[x.fecha < corte], x[x.fecha >= corte]
    em = M.groupby('liga').apply(lambda s: pd.Series({'n': len(s), 'e': (s.verde - s.p_casa).mean(),
                                                       'z': (s.verde - s.p_casa).mean() / np.sqrt((s.p_casa * (1 - s.p_casa)).mean() / len(s))}),
                                 include_groups=False)
    print('\nQUITAR LAS LIGAS QUE SALEN MAL AL MIRAR (juzgar: %d apuestas, %.1f %% verdes sin quitar nada)'
          % (len(J), 100 * J.verde.mean()))
    out['quitar'] = {}
    for nom, malas in (('z < −1,96 al mirar', em[(em.n >= 50) & (em.z < -1.96)].index),
                       ('z < −1,0 al mirar', em[(em.n >= 50) & (em.z < -1.0)].index),
                       ('exceso < −3 pts al mirar', em[(em.n >= 50) & (em.e < -0.03)].index)):
        q = J[~J.liga.isin(malas)]
        med, p5 = boot_dif(J, q)
        print('   %-26s quita %2d ligas → %5.1f %% (%d apuestas) · %+.2f pts (p5 %+.2f)'
              % (nom, len(malas), 100 * q.verde.mean(), len(q), med, p5))
        out['quitar'][nom] = {'ligas': list(malas), 'verdes': float(q.verde.mean()), 'n': len(q),
                              'media': med, 'p5': p5}
    # recalibrar el modelo por liga: corrección = exceso del MODELO al mirar
    print('\nRECALIBRAR EL MODELO POR LIGA (corrección = lo que falló el modelo en esa liga al mirar)')
    todo = C.patas()
    todo = todo[todo.p_casa.notna() & (todo.cuota >= 1.15) & (todo.cuota < 1.35) & (todo.p_casa >= .74)]
    todo['fecha'] = pd.to_datetime(todo.fecha)
    Mt = todo[todo.fecha < corte]
    corr = Mt.groupby('liga').apply(lambda s: (s.verde - s.p).mean() if len(s) >= 100 else 0.0, include_groups=False)
    for enc in (1.0, 0.5):
        t = todo.copy()
        t['p2'] = (t.p + enc * t.liga.map(corr).fillna(0)).clip(0, 1)
        nueva = t[(t.p2 >= .70)].sort_values('p_casa', ascending=False).drop_duplicates('mid')
        nueva = nueva[nueva.fecha >= corte]
        med, p5 = boot_dif(J, nueva)
        print('   corrección ×%.1f: %5.1f %% (%d apuestas) frente a %5.1f %% (%d) · %+.2f pts (p5 %+.2f)'
              % (enc, 100 * nueva.verde.mean(), len(nueva), 100 * J.verde.mean(), len(J), med, p5))
        out['recalibrar_%.1f' % enc] = [float(nueva.verde.mean()), len(nueva), med, p5]
    json.dump(out, open('_v337_ligas.json', 'w', encoding='utf-8'), ensure_ascii=False,
              indent=1, default=float)


if __name__ == '__main__':
    main()
