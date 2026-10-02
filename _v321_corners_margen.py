# -*- coding: utf-8 -*-
"""
v321 — CÓRNERS: ¿ACIERTAN MÁS CON LA LÍNEA LEJOS DEL λ?

Idea del usuario: «apostar "menos de 10,5" cuando el λ es 9,8 es muy distinto
a apostarlo cuando el λ es 7,5… si filtra sólo los córners donde la línea
está al menos 1,5 córners alejada del λ, probablemente el acierto sube».

1. BACKTEST (`_v319_corners_filas.pkl`, que deja `_v319_conteos_reales.py`
   con el λ y el margen de cada apuesta): 11.874 partidos con histórico real,
   franja 70-80 %, la regla del favorito ya aplicada a los de equipo; margen
   = λ − línea en «más», línea − λ en «menos». Por mitades del periodo y con
   bootstrap.
2. LA TARJETA SIMULADA (`_v319_candidatas.csv`, 20-sep a 1-oct, líneas reales
   de la casa): el λ de cada candidata se reconstruye invirtiendo su
   probabilidad con la dispersión de su liga.

Uso: python _v321_corners_margen.py   (escribe _v321_corners_margen.json)
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

MARGEN_TOTAL, MARGEN_EQUIPO = 2.5, 2.0


def backtest(rng):
    P = pd.read_pickle('_v319_corners_filas.pkl')
    P = P[P.real & P.tipo.isin(['total_suma', 'local', 'visita']) & P.p.between(.70, .80)].copy()
    P['fecha'] = pd.to_datetime(P['fecha'])
    P['t'] = np.where(P.tipo == 'total_suma', 'total', 'equipo')
    med = P['fecha'].quantile(.5)
    P['tramo'] = np.where(P.fecha < med, 1, 2)
    P = P[(P.t == 'total') | (P.fav >= .65)]          # la regla del favorito (v320)
    out = {}
    for t, u in (('total', MARGEN_TOTAL), ('equipo', MARGEN_EQUIPO)):
        z = P[P.t == t]
        k = z[z.margen >= u]
        g = z.assign(k=z.margen >= u)
        bs = [(lambda x: x[x.k].y.mean() - x.y.mean())(g.iloc[rng.integers(0, len(g), len(g))])
              for _ in range(1000)]
        out[t] = {'margen_minimo': u, 'apuestas_todas': int(len(z)), 'apuestas_con_margen': int(len(k)),
                  'acierto_todas': round(float(z.y.mean()), 4),
                  'acierto_con_margen': round(float(k.y.mean()), 4),
                  'primera_mitad': round(float(k[k.tramo == 1].y.mean()), 4),
                  'segunda_mitad': round(float(k[k.tramo == 2].y.mean()), 4),
                  'p5_mejora': round(float(np.percentile(bs, 5)), 4)}
    req = np.where(P.t == 'total', MARGEN_TOTAL, MARGEN_EQUIPO)
    out['conjunto'] = {'antes': round(float(P.y.mean()), 4),
                       'despues': round(float(P[P.margen >= req].y.mean()), 4),
                       'se_queda': round(float((P.margen >= req).mean()), 4)}
    out['margen_1_5_total'] = round(float((P[P.t == 'total'].margen >= 1.5).mean()), 4)
    return out


def tarjeta():
    import corners_fotmob as cf
    import rendimiento_equipos as rq
    d = pd.read_csv('_v319_candidatas.csv').dropna(subset=['acierto'])
    met = d[d.mostrada & (d.veredicto == 'meter')].copy()
    cache = {}

    def disps(liga):
        if liga not in cache:
            a, b = rq.dispersion_corners_equipo(liga), rq.dispersion_corners_liga(liga)
            if not a or not b:
                dd = cf._datos()
                dl = dd[dd.liga == liga] if dd is not None else None
                v = cf._dispersion(dl) * cf.FACTOR_DISPERSION if dl is not None and len(dl) else None
                a, b = a or v, b or v
            cache[liga] = (a, b)
        return cache[liga]

    def lam_de(p_over, L, disp):
        lo, hi = 0.3, 30.0
        for _ in range(60):
            m = (lo + hi) / 2
            if rq.prob_mas_de(m, L, disp) < p_over:
                lo = m
            else:
                hi = m
        return (lo + hi) / 2
    fuera = []
    for i, r in met[met.mercado == 'Córners'].iterrows():
        de, dt = disps(r.liga)
        disp = dt if r.etiqueta == 'Total' else de
        if not disp or r.linea != r.linea:
            continue
        mas = 'Más' in r.apuesta
        lam = lam_de(r.prob if mas else 1 - r.prob, float(r.linea), disp)
        margen = lam - r.linea if mas else r.linea - lam
        if margen < (MARGEN_TOTAL if r.etiqueta == 'Total' else MARGEN_EQUIPO):
            fuera.append(i)
    nuevo = met.drop(index=fuera)
    ck_a, ck_d = met[met.mercado == 'Córners'], nuevo[nuevo.mercado == 'Córners']

    def res(z):
        return {'apuestas': int(len(z)), 'acierto': round(float(z.acierto.mean()), 4),
                'rojos': int((1 - z.acierto).sum()),
                'tramo_20_26': round(float(z[z.dia <= '2026-09-26'].acierto.mean()), 4),
                'tramo_27_en_adelante': round(float(z[z.dia > '2026-09-26'].acierto.mean()), 4)}
    return {'corners_antes': res(ck_a), 'corners_despues': res(ck_d),
            'todo_antes': res(met), 'todo_despues': res(nuevo)}


def main():
    rng = np.random.default_rng(321)
    out = {'backtest': backtest(rng), 'tarjeta_simulada': tarjeta()}
    json.dump(out, open('_v321_corners_margen.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
