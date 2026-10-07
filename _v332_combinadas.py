# -*- coding: utf-8 -*-
"""
v332 — ¿CÓMO SE ARMA UNA COMBINADA QUE GANE A LA LARGA?

El usuario mandó nueve boletos ganadores (uno de 13 patas a ×245, doblado
por un «booster +100 %» de Draftea, que pagó 22.544 por 46) y pidió:
«simulaciones para saber qué patrones se siguieron, qué metodología aplicar
para saber cuándo meter, cuándo no, cuándo arriesgar más y cuándo menos;
muchas permutaciones con modelos matemáticos».

LO PRIMERO: los boletos ganadores no sirven para medir — de los perdedores
no hay foto. Se mide en TODOS los partidos del histórico fuera de muestra
con cuotas reales (`pick_ledger*.csv`, 2018-2026), y aparte con los precios
de Playdoit de la simulación de la tarjeta (765 partidos, 20-sep a 6-oct).

LA MATEMÁTICA QUE MANDA. Una combinada de k patas independientes paga
Π cuotas y acierta con Π p. Lo que devuelve a la larga por peso apostado es
Π (p·cuota): si cada pata devuelve 0,95, cuatro devuelven 0,81 (−19 %) y
trece 0,51 (−49 %). Si cada pata devuelve 1,03, cuatro devuelven 1,13. La
combinada AMPLIFICA lo que ya hay en cada pata; no lo crea. Y un «booster»
que dobla el pago convierte Π en 2·Π: con patas a 0,95 sale positivo hasta
13 patas (2·0,95^13 = 1,03).

LAS ESTRATEGIAS (cómo se eligen las patas de cada día; una por partido):
  S0 meter       la de la app: modelo 70-80 %, cuota < 1,35
  S1 valor mod   modelo × cuota ≥ 1,05 y modelo ≥ 55 %
  S2 error precio la casa paga más que Pinnacle sin margen (p_pin·c ≥ 1,02)
  S3 los dos     S1 y S2 a la vez
  S4 favoritos   cuota 1,40-1,80 y el modelo por encima de la casa (estilo
                 de los boletos del usuario)
  S5 capa 1      modelo ≥ 70 % y casa sin margen 80-88 %, cuota ≥ 1,10
Mercados: ganador, doble oportunidad (cuota aproximada desde el 1X2) y
más/menos 2,5 (cuotas reales).

LAS PERMUTACIONES: cada día se sortean hasta 200 combinadas de k patas
(k = 1…8 y 13) entre las patas elegibles de partidos distintos. Se mide el
acierto, lo que devuelve por peso, y el bootstrap por día (p5). Se repite
con el pago ×2 del booster. 70/30 por fecha.

RESULTADOS (2026-10-06; 323 mil patas con cuota real, 60.901 partidos)
------------------------------------------------------------------------
Rinde por peso en el tramo de juzgar (acierto entre paréntesis):

                 1 pata         2            4            8           13
  S0 meter     −5,3 (77 %)  −10,4 (60)  −19,1 (36)  −37,5 (12)  −55,1 (3)
  S5 capa 1    −4,1 (84 %)   −7,3 (72)  −16,5 (50)  −31,0 (24)  −45,6 (10)
  S4 1,40-1,80 −0,8 (62 %)   −4,5 (37)  −29,4 (11)     —           —
  S1 modelo    −5,9 (54 %)  −10,6 (29)  −13,4 (9)   −23,3 (1)      —
  S2 error de  +5,9 (42 %)  +16,5 (18)   −4,9 (3)   (p5 −52)       —
     precio    (p5 +1,2)    (p5 +3,4)

  · Ninguna forma de elegir patas por el modelo gana a la larga; la
    combinada MULTIPLICA esa pérdida pata a pata.
  · El ERROR DE PRECIO (casa > Pinnacle sin margen) es lo único que gana, y
    también a cuota baja: cuota ≤ 2,00, 64,9 % de acierto, +5,0 / +8,4 %.
  · BOOSTER ×2: con «meter», 4 patas +61,8 % (p5 +54,6), 8 patas +25,0 %
    (p5 +12,3), 13 patas −10,3 %. Lo mejor es el mínimo de patas que pida
    la promoción con las patas más seguras.

PERO CON PRECIOS REALES DE NOVIBET (`_v332_novibet_real.py`, 4.679
partidos del 10-sep al 7-oct) todas las franjas pierden (−2,5 % a cuota
≤ 1,20; −22 % a 3+), y el «error de precio» contra el Pinnacle de
`radar_capturas.csv` PIERDE −37 % (prometía 30-40 %, acertó 22 %): la foto
de Pinnacle no es del mismo momento que la última de Novibet, así que lo que
parece error es la casa moviéndose con información. Hasta capturar las dos
a la vez, ningún «error» en vivo es de fiar. Nada de esto se activa.

PAGO ANTICIPADO POR 2 GOLES (`_v332_pago_anticipado.py`): +1,3 pts a
«Gana X» (simulación minuto a minuto validada contra el +2 al descanso real
de 32 mil partidos). Deja a los favoritos ≤ 1,30 en tablas, no más.
"""
from __future__ import annotations

import io
import json
import sys
from itertools import combinations

import numpy as np
import pandas as pd

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8',
                              errors='replace')
rng = np.random.default_rng(3320)
KS = (1, 2, 3, 4, 5, 6, 8, 13)
MAX_COMB = 200


def patas() -> pd.DataFrame:
    t = pd.read_csv('pick_ledger_totales.csv')
    r = pd.read_csv('pick_ledger.csv').drop(columns=['goles_local', 'goles_visit',
                                                      'fecha', 'pliegue'])
    d = t.merge(r, on=['liga', 'match_id'], how='inner')
    for k in ('cuota_over25', 'cuota_under25'):
        d[k] = d[k + '_y'].fillna(d[k + '_x'])
    d = d[d.goles_local.notna()].copy()
    d['fecha'] = pd.to_datetime(d.fecha)
    gh, ga = d.goles_local, d.goles_visit
    loc, emp, vis = (gh > ga).astype(int), (gh == ga).astype(int), (gh < ga).astype(int)
    ih, ix, ia = 1 / d.cuota_home, 1 / d.cuota_draw, 1 / d.cuota_away
    s = ih + ix + ia
    ph, px, pa = 1 / d.pin_home, 1 / d.pin_draw, 1 / d.pin_away
    sp = ph + px + pa
    P = {'h': ph / sp, 'x': px / sp, 'a': pa / sp}
    C = {'h': ih / s, 'x': ix / s, 'a': ia / s}
    io_, iu = 1 / d.cuota_over25, 1 / d.cuota_under25
    co = io_ / (io_ + iu)
    tot = gh + ga
    filas = [
        ('Gana local', d.p_home, d.cuota_home, loc, P['h'], C['h']),
        ('Gana visita', d.p_away, d.cuota_away, vis, P['a'], C['a']),
        ('Local o empate', d.p_home + d.p_draw, 1 / (ih + ix), loc | emp,
         P['h'] + P['x'], C['h'] + C['x']),
        ('Visita o empate', d.p_away + d.p_draw, 1 / (ia + ix), vis | emp,
         P['a'] + P['x'], C['a'] + C['x']),
        ('Más de 2.5', d['p_over_2.5'], d.cuota_over25, (tot > 2.5).astype(int),
         np.nan, co),
        ('Menos de 2.5', 1 - d['p_over_2.5'], d.cuota_under25,
         (tot < 2.5).astype(int), np.nan, 1 - co),
    ]
    x = pd.concat([pd.DataFrame({'fecha': d.fecha, 'mid': d.match_id,
                                 'liga': d.liga, 'apuesta': n, 'p': p,
                                 'cuota': c, 'verde': v, 'p_pin': pp,
                                 'p_casa': pc})
                   for n, p, c, v, pp, pc in filas], ignore_index=True)
    x = x[x.cuota.notna() & (x.cuota > 1.01) & x.p.notna()]
    return x.reset_index(drop=True)


ESTRATEGIAS = {
    'S0 meter (app)': lambda x: x.p.between(.70, .80) & (x.cuota < 1.35),
    'S1 valor del modelo': lambda x: (x.p * x.cuota >= 1.05) & (x.p >= .55),
    'S2 error de precio (Pinnacle)': lambda x: (x.p_pin * x.cuota >= 1.02),
    'S3 modelo y Pinnacle': lambda x: (x.p * x.cuota >= 1.05) & (x.p >= .55)
    & (x.p_pin * x.cuota >= 1.02),
    'S4 favoritos 1,40-1,80': lambda x: x.cuota.between(1.40, 1.80)
    & (x.p > 1 / x.cuota) & x.apuesta.str.startswith('Gana'),
    'S5 capa 1': lambda x: (x.p >= .70) & x.p_casa.between(.80, .88)
    & (x.cuota >= 1.10),
}


def una_por_partido(e: pd.DataFrame) -> pd.DataFrame:
    """Si un partido tiene varias patas elegibles, la de mayor modelo×cuota."""
    e = e.assign(v=e.p * e.cuota).sort_values('v', ascending=False)
    return e.drop_duplicates('mid')


def simula(e: pd.DataFrame, k: int):
    """Por día: hasta MAX_COMB combinadas de k patas → (apostado, devuelto,
    aciertos, devuelto con booster) sumados por día."""
    filas = []
    for fecha, g in e.groupby('fecha'):
        n = len(g)
        if n < k:
            continue
        c = g.cuota.values
        v = g.verde.values
        if k == 1:
            idx = np.arange(n)[:, None]
        else:
            from math import comb
            if comb(n, k) <= MAX_COMB:
                idx = np.array(list(combinations(range(n), k)))
            else:
                idx = np.array([rng.choice(n, k, replace=False)
                                for _ in range(MAX_COMB)])
        pago = np.prod(c[idx], axis=1)
        gana = np.prod(v[idx], axis=1)
        filas.append((fecha, len(idx), float((pago * gana).sum()),
                      float(gana.sum()), float(pago.mean())))
    return pd.DataFrame(filas, columns=['fecha', 'n', 'dev', 'aciertos', 'cuota_media'])


def resumen(t: pd.DataFrame, booster=1.0):
    if t.empty:
        return None
    A = np.c_[t.n.values, t.dev.values * booster]
    roi = A[:, 1].sum() / A[:, 0].sum() - 1
    b = []
    for _ in range(1500):
        s = A[rng.integers(0, len(A), len(A))].sum(axis=0)
        b.append(s[1] / s[0] - 1)
    return {'dias': int(len(t)), 'combinadas': int(t.n.sum()),
            'acierto': float(t.aciertos.sum() / t.n.sum()),
            'cuota_media': float((t.cuota_media * t.n).sum() / t.n.sum()),
            'rinde': float(roi), 'p5': float(np.percentile(b, 5)),
            'p95': float(np.percentile(b, 95))}


def main():
    x = patas()
    dias = np.sort(x.fecha.unique())
    corte = dias[int(len(dias) * 0.7)]
    print('patas con cuota real: %d de %d partidos (%s a %s); corte %s'
          % (len(x), x.mid.nunique(), str(dias[0])[:10], str(dias[-1])[:10],
             str(corte)[:10]))
    out = {}
    for nombre, regla in ESTRATEGIAS.items():
        e = una_por_partido(x[regla(x).fillna(False)])
        print('\n' + '=' * 92)
        print('%s — %d patas elegibles; por pata: acierto %.1f %%, cuota media %.2f'
              % (nombre, len(e), 100 * e.verde.mean(), e.cuota.mean()))
        print('  k  tramo   días  combinadas  acierto   cuota   rinde      p5      '
              'con booster ×2 (p5)')
        out[nombre] = {}
        for k in KS:
            for tramo, s in (('mirar', e[e.fecha < corte]),
                             ('juzgar', e[e.fecha >= corte])):
                t = simula(s, k)
                r1, r2 = resumen(t), resumen(t, 2.0)
                if not r1 or r1['dias'] < 20:
                    continue
                out[nombre]['%d|%s' % (k, tramo)] = {'normal': r1, 'booster': r2}
                print(' %2d  %-6s %5d  %9d   %5.1f %%  %6.2f  %+6.1f %%  %+6.1f %%   '
                      '%+7.1f %% (%+.1f)'
                      % (k, tramo, r1['dias'], r1['combinadas'], 100 * r1['acierto'],
                         r1['cuota_media'], 100 * r1['rinde'], 100 * r1['p5'],
                         100 * r2['rinde'], 100 * r2['p5']))
    json.dump(out, open('_v332_combinadas.json', 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1, default=float)


if __name__ == '__main__':
    main()
