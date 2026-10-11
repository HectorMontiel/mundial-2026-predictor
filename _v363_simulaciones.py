#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v363 — Simulaciones de las apuestas arriesgadas contra los cierres de Playdoit.

El usuario: «checa con el histórico, contra los cierres, si dejan ganancia;
dame todas las simulaciones: % de buenas, % de malas; simula una apuesta como
la que se ganó en Draftea: cuántas veces se cumple, cuántas patas se cumplen
dentro de esa apuesta con sus criterios; y a qué otro mercado se le puede
aplicar».

Datos: `_v362b_lineas.pkl` (`_v362b_escaleras.py`): cada línea «más de» de
las escaleras de Playdoit (la última foto antes del día del partido, que es lo
más parecido al cierre que guardamos) desde el 24-ago, con la probabilidad del
Método Contexto entrenado SÓLO con lo anterior, la de la casa sin margen, la
cuota y si se cumplió. Sin las líneas de otro mercado (|método − casa| > 20 pts).

  A. MERCADO POR MERCADO (zona arriesgada: cuota 1,45-3, método ≥ 55 %, la
     línea de más prob × cuota por equipo/total): buenas, malas, cuota,
     ganancia por $100 y su p5 (bootstrap por partido), en dos mitades.
  B. EL BOLETO DE DRAFTEA: córners de equipo «más de 4,5 / 5,5» y total «más
     de 9,5» (los criterios del boleto ganado), de 3 a 6 patas por día,
     elegidas de tres formas: lo que la CASA ve más probable, lo que el
     MÉTODO ve más probable, y lo que el método ve POR ENCIMA de la casa.
     Cuántos boletos salen enteros, cuántas patas se cumplen dentro (6/6,
     5/6…), el momio medio y la ganancia.
  C. LAS MISMAS COMBINADAS EN LOS OTROS MERCADOS (tiros, a puerta, tarjetas,
     goles, y todo mezclado).
Escribe `_v363_simulaciones.json`.
"""
import json
import sys

import numpy as np
import pandas as pd

rng = np.random.default_rng(363)
MAX_DIF = 0.20
NOMBRE = {'corners': 'Córners', 'tiros': 'Tiros', 'a_puerta': 'Tiros a puerta',
          'tarjetas': 'Tarjetas', 'goles': 'Goles'}


def cargar():
    d = pd.read_pickle('_v362b_lineas.pkl')
    d = d[(d.p_mod - d.p_casa).abs() <= MAX_DIF].copy()
    d['dia'] = d.fecha.dt.strftime('%Y-%m-%d')
    # el equipo de cada fila de «equipo» (dos por partido): su media
    d['lado'] = np.where(d.tipo == 'total', 'total', d.mu.round(4).astype(str))
    corte = d.fecha.quantile(0.5)
    d['tramo'] = np.where(d.fecha < corte, 'A', 'B')
    return d, corte


def roi_p5(gan, mids):
    gan, mids = np.asarray(gan, float), np.asarray(mids)
    um, inv = np.unique(mids, return_inverse=True)
    s, n = np.bincount(inv, weights=gan), np.bincount(inv)
    bs = [s[i].sum() / n[i].sum() for i in (rng.integers(0, len(um), len(um)) for _ in range(2000))]
    return round(float(np.percentile(bs, 5)), 4)


def resumen(x):
    if not len(x):
        return {'n': 0}
    gan = x.y * x.c_mas - 1
    return {'n': int(len(x)), 'buenas': round(float(x.y.mean()), 3),
            'malas': round(float(1 - x.y.mean()), 3), 'promete': round(float(x.p_mod.mean()), 3),
            'casa': round(float(x.p_casa.mean()), 3), 'cuota': round(float(x.c_mas.mean()), 3),
            'ganancia_por_100': round(float(100 * gan.mean()), 1),
            'p5_por_100': round(100 * roi_p5(gan, x.mid), 1)}


def patas(d, pmin=0.55, cmin=1.45, cmax=3.0):
    x = d[(d.c_mas >= cmin) & (d.c_mas <= cmax) & (d.p_mod >= pmin)]
    x = x.assign(ev=x.p_mod * x.c_mas).sort_values('ev', ascending=False)
    return x.groupby(['mid', 'obj', 'tipo', 'lado']).head(1)


def boletos(legs, k, orden, max_por_partido=2):
    """Cada día, las k patas de mejor `orden` (hasta 2 por partido, como el
    boleto de Draftea). Devuelve una fila por día."""
    filas = []
    for (dia, tr), g in legs.groupby(['dia', 'tramo']):
        g = g.sort_values(orden, ascending=False)
        g = g.groupby('mid').head(max_por_partido).head(k)
        if len(g) < k:
            continue
        filas.append({'dia': dia, 'tramo': tr, 'entero': int(g.y.all()), 'patas_ok': int(g.y.sum()),
                      'momio': float(g.c_mas.prod()), 'p': float(g.p_mod.prod()),
                      'p_casa': float(g.p_casa.prod())})
    return pd.DataFrame(filas)


def resumen_boletos(b, k):
    if b.empty:
        return {'dias': 0}
    gan = b.entero * b.momio - 1
    bs = [gan.values[rng.integers(0, len(b), len(b))].mean() for _ in range(2000)]
    dist = {'%d/%d' % (j, k): int((b.patas_ok == j).sum()) for j in range(k, -1, -1)}
    return {'dias': int(len(b)), 'enteros': int(b.entero.sum()),
            'sale_entero': round(float(b.entero.mean()), 3),
            'promete_metodo': round(float(b.p.mean()), 3), 'promete_casa': round(float(b.p_casa.mean()), 3),
            'patas_buenas': round(float(b.patas_ok.mean() / k), 3), 'momio_medio': round(float(b.momio.mean()), 2),
            'ganancia_por_100': round(float(100 * gan.mean()), 1),
            'p5_por_100': round(float(100 * np.percentile(bs, 5)), 1), 'patas_cumplidas': dist}


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    d, corte = cargar()
    out = {'corte': str(corte)[:10], 'desde': d.dia.min(), 'hasta': d.dia.max(),
           'partidos': int(d.mid.nunique()), 'lineas': int(len(d))}
    print('del', out['desde'], 'al', out['hasta'], '·', out['partidos'], 'partidos ·', out['lineas'],
          'líneas · corte', out['corte'])
    # ---------------------------------------------------------------- A
    legs = patas(d)
    out['mercados'] = {}
    print('\n=== A. mercado por mercado (cuota 1,45-3, método ≥ 55 %) ===')
    for (obj, tipo), g in legs.groupby(['obj', 'tipo']):
        r = {tr: resumen(g[g.tramo == tr]) for tr in ('A', 'B')}
        r['todo'] = resumen(g)
        out['mercados']['%s %s' % (NOMBRE[obj], tipo)] = r
        print('%-24s %s' % ('%s %s' % (NOMBRE[obj], tipo), json.dumps(r['todo'], ensure_ascii=False)))
    out['mercados']['todo'] = {tr: resumen(legs[legs.tramo == tr]) for tr in ('A', 'B')}
    out['mercados']['todo']['todo'] = resumen(legs)
    print('%-24s %s' % ('TODO', json.dumps(out['mercados']['todo']['todo'], ensure_ascii=False)))
    out['umbral'] = {}
    for pm in (0.55, 0.60, 0.65, 0.70):
        lg = patas(d, pm)
        out['umbral']['%d' % int(pm * 100)] = {tr: resumen(lg[lg.tramo == tr]) for tr in ('A', 'B')}
        print('método ≥ %d %%' % int(pm * 100), json.dumps(out['umbral']['%d' % int(pm * 100)], ensure_ascii=False))
    # ---------------------------------------------------------------- B
    dr = d[(d.obj == 'corners') & (((d.tipo == 'equipo') & d.linea.isin([4.5, 5.5]))
                                   | ((d.tipo == 'total') & (d.linea == 9.5)))].copy()
    dr = dr.sort_values('p_mod', ascending=False).groupby(['mid', 'tipo', 'lado']).head(1)
    dr['valor'] = dr.p_mod - dr.p_casa
    out['draftea'] = {'patas': {'equipo más de 4,5': resumen(dr[(dr.tipo == 'equipo') & (dr.linea == 4.5)]),
                                'equipo más de 5,5': resumen(dr[(dr.tipo == 'equipo') & (dr.linea == 5.5)]),
                                'total más de 9,5': resumen(dr[dr.tipo == 'total'])}}
    print('\n=== B. el boleto de Draftea (córners equipo +4,5/+5,5 y total +9,5) ===')
    print('patas sueltas:', json.dumps(out['draftea']['patas'], ensure_ascii=False))
    for nombre, orden, filtro in (('casa', 'p_casa', None), ('metodo', 'p_mod', None),
                                  ('metodo_sobre_casa', 'valor', 'valor')):
        g = dr if filtro is None else dr[(dr.valor > 0) & (dr.p_mod >= 0.5)]
        out['draftea'][nombre] = {}
        for k in (3, 4, 5, 6):
            b = boletos(g, k, orden)
            out['draftea'][nombre][k] = {tr: resumen_boletos(b[b.tramo == tr], k) for tr in ('A', 'B')}
            out['draftea'][nombre][k]['todo'] = resumen_boletos(b, k)
            print('  %-18s %d patas: %s' % (nombre, k, json.dumps(out['draftea'][nombre][k]['todo'],
                                                                   ensure_ascii=False)))
    # ---------------------------------------------------------------- C
    print('\n=== C. combinadas en los otros mercados (patas de A, método ≥ 55 %) ===')
    out['combinadas'] = {}
    for obj in list(NOMBRE) + ['todo']:
        g = legs if obj == 'todo' else legs[legs.obj == obj]
        out['combinadas'][obj] = {}
        for k in (2, 3, 4, 6):
            b = boletos(g, k, 'p_mod', max_por_partido=1)
            out['combinadas'][obj][k] = {tr: resumen_boletos(b[b.tramo == tr], k) for tr in ('A', 'B')}
            out['combinadas'][obj][k]['todo'] = resumen_boletos(b, k)
            t = out['combinadas'][obj][k]['todo']
            if t.get('dias'):
                print('  %-12s %d patas: días %d, enteros %d (%.0f %%), patas buenas %.0f %%, momio %.1f, '
                      'ganancia %+.0f por $100 (p5 %+.0f)' % (
                          NOMBRE.get(obj, 'Todo'), k, t['dias'], t['enteros'], 100 * t['sale_entero'],
                          100 * t['patas_buenas'], t['momio_medio'], t['ganancia_por_100'],
                          t['p5_por_100']))
    json.dump(out, open('_v363_simulaciones.json', 'w', encoding='utf-8'), ensure_ascii=False,
              indent=1, default=str)


if __name__ == '__main__':
    main()
