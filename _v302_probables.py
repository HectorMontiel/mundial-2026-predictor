# -*- coding: utf-8 -*-
"""
v302 — «LAS PROBABLES CON BUENA CUOTA»: ¿HAY ALGUNA REGLA QUE PASE LAS DOS
PUERTAS?

El usuario:

    «En apuestas del día veo muy buenas apuestas y de acuerdo al histórico
     cuando finalizan veo que muchas se aciertan. Quiero que esas lleguen
     también a Capa 1 para que puedan entrar a la escalera... Encontrar las
     probables con buena cuota, esa es la idea.»

Y además es el punto abierto del traspaso: el «Constructor» de Novibet con el
que gana —doble oportunidad + goles en el mismo boleto— nunca se había medido.

Se miden, sobre `pick_ledger.csv` (probabilidades FUERA DE MUESTRA del modelo,
cierre de mercado y de Pinnacle, goles reales):

  A  probable del MODELO:    p_modelo >= P  y  cuota >= C          (1X2)
  B  probable del MERCADO:   p_justa_pinnacle >= P  y  cuota >= C  (1X2)
  C  los dos de acuerdo:     A y B a la vez
  D  doble oportunidad (1X / X2) con la cuota que sale de la casa
  E  «constructor»: doble oportunidad + menos de 2,5 en el mismo boleto,
     cobrado multiplicando (como la casa cobra la combinada, ver v297)
  F  ganador + más de 2,5 (la combinada ya medida, como control)

LAS DOS PUERTAS: se parte por fecha, 70 % antiguo (elección) y 30 % reciente
(juicio). Vale sólo si el ROI y el p5 del bootstrap son POSITIVOS EN LOS DOS.

Salida: `_v302_probables.json`.
"""
from __future__ import annotations

import json
import sys

import numpy as np
import pandas as pd

RNG = np.random.default_rng(302)
B = 2000


def p5(ganancias: np.ndarray) -> float:
    if len(ganancias) < 30:
        return float('nan')
    idx = RNG.integers(0, len(ganancias), size=(B, len(ganancias)))
    medias = ganancias[idx].mean(axis=1)
    return float(np.percentile(medias, 5))


def resumen(g: np.ndarray, ok: np.ndarray) -> dict:
    return {'n': int(len(g)),
            'acierta': round(float(ok.mean()), 4) if len(ok) else None,
            'roi': round(float(g.mean()), 4) if len(g) else None,
            'p5': round(p5(g), 4) if len(g) >= 30 else None}


def cargar() -> pd.DataFrame:
    df = pd.read_csv('pick_ledger.csv', low_memory=False)
    df = df.dropna(subset=['goles_local', 'goles_visit', 'fecha'])
    df['fecha'] = pd.to_datetime(df['fecha'], errors='coerce')
    df = df.dropna(subset=['fecha']).sort_values('fecha').reset_index(drop=True)
    gl, gv = df['goles_local'].astype(int), df['goles_visit'].astype(int)
    df['r_home'] = gl > gv
    df['r_draw'] = gl == gv
    df['r_away'] = gl < gv
    df['r_u25'] = (gl + gv) <= 2
    df['r_o25'] = (gl + gv) >= 3
    # la justa de Pinnacle, sin margen (proporcional)
    inv = 1 / df[['pin_home', 'pin_draw', 'pin_away']]
    s = inv.sum(axis=1)
    for k in ('home', 'draw', 'away'):
        df['f_' + k] = inv['pin_' + k] / s
    # la justa del total, desde el propio mercado (no hay Pinnacle de goles)
    invt = 1 / df[['cuota_over25', 'cuota_under25']]
    st = invt.sum(axis=1)
    df['f_o25'] = invt['cuota_over25'] / st
    df['f_u25'] = invt['cuota_under25'] / st
    # la doble oportunidad que la casa deriva de su 1X2: la probabilidad
    # implicita de las dos salidas, CON su margen. Es como la publican.
    df['c_1x'] = 1 / (1 / df['cuota_home'] + 1 / df['cuota_draw'])
    df['c_x2'] = 1 / (1 / df['cuota_away'] + 1 / df['cuota_draw'])
    corte = df['fecha'].iloc[int(len(df) * 0.70)]
    df['tramo'] = np.where(df['fecha'] < corte, 'eleccion', 'juicio')
    return df


def evaluar(df: pd.DataFrame, mascara: pd.Series, cuota: pd.Series,
            acierto: pd.Series) -> dict:
    m = mascara.fillna(False) & cuota.notna() & (cuota > 1)
    out = {}
    for tramo in ('eleccion', 'juicio'):
        mm = m & (df['tramo'] == tramo)
        ok = acierto[mm].astype(bool).to_numpy()
        c = cuota[mm].to_numpy(dtype=float)
        g = np.where(ok, c - 1, -1.0)
        out[tramo] = resumen(g, ok)
    ok = acierto[m].astype(bool).to_numpy()
    c = cuota[m].to_numpy(dtype=float)
    out['global'] = resumen(np.where(ok, c - 1, -1.0), ok)
    out['cuota_media'] = round(float(c.mean()), 3) if len(c) else None
    e, j = out['eleccion'], out['juicio']
    out['pasa'] = bool(e['p5'] is not None and j['p5'] is not None
                       and e['roi'] > 0 and j['roi'] > 0
                       and e['p5'] > 0 and j['p5'] > 0)
    out['peor_p5'] = (min(e['p5'], j['p5'])
                      if e['p5'] is not None and j['p5'] is not None else None)
    return out


def main() -> int:
    df = cargar()
    res = {'filas': int(len(df)),
           'corte': str(df.loc[df['tramo'] == 'juicio', 'fecha'].min().date()),
           'reglas': {}}
    R = res['reglas']
    lados = (('home', 'p_home', 'cuota_home', 'f_home', 'r_home'),
             ('away', 'p_away', 'cuota_away', 'f_away', 'r_away'))
    for P in (0.50, 0.55, 0.60, 0.65, 0.70, 0.75):
        for C in (1.30, 1.40, 1.50, 1.60, 1.80, 2.00):
            for lado, pm, cu, fj, ra in lados:
                base = df[cu] >= C
                R['A_modelo|%s|p%.2f|c%.2f' % (lado, P, C)] = evaluar(
                    df, base & (df[pm] >= P), df[cu], df[ra])
                R['B_mercado|%s|p%.2f|c%.2f' % (lado, P, C)] = evaluar(
                    df, base & (df[fj] >= P), df[cu], df[ra])
                R['C_ambos|%s|p%.2f|c%.2f' % (lado, P, C)] = evaluar(
                    df, base & (df[pm] >= P) & (df[fj] >= P), df[cu], df[ra])
    # D — doble oportunidad
    for P in (0.60, 0.70, 0.75, 0.80, 0.85):
        for C in (1.15, 1.25, 1.35, 1.50):
            R['D_1x|p%.2f|c%.2f' % (P, C)] = evaluar(
                df, (df['c_1x'] >= C) & ((df['f_home'] + df['f_draw']) >= P),
                df['c_1x'], df['r_home'] | df['r_draw'])
            R['D_x2|p%.2f|c%.2f' % (P, C)] = evaluar(
                df, (df['c_x2'] >= C) & ((df['f_away'] + df['f_draw']) >= P),
                df['c_x2'], df['r_away'] | df['r_draw'])
    # E — el constructor: doble oportunidad + menos de 2,5, multiplicado
    c_1xu = df['c_1x'] * df['cuota_under25']
    c_x2u = df['c_x2'] * df['cuota_under25']
    ok_1xu = (df['r_home'] | df['r_draw']) & df['r_u25']
    ok_x2u = (df['r_away'] | df['r_draw']) & df['r_u25']
    # la conjunta «como si fueran independientes», que es lo que cobra la casa
    ind_1xu = (df['f_home'] + df['f_draw']) * df['f_u25']
    ind_x2u = (df['f_away'] + df['f_draw']) * df['f_u25']
    for P in (0.0, 0.30, 0.35, 0.40, 0.45, 0.50):
        for C in (1.50, 1.80, 2.00):
            R['E_1x_u25|p%.2f|c%.2f' % (P, C)] = evaluar(
                df, (c_1xu >= C) & (ind_1xu >= P), c_1xu, ok_1xu)
            R['E_x2_u25|p%.2f|c%.2f' % (P, C)] = evaluar(
                df, (c_x2u >= C) & (ind_x2u >= P), c_x2u, ok_x2u)
    # la correlacion en si: cuanto mas entra de verdad que el producto
    for nombre, ok, ind in (('1x_u25', ok_1xu, ind_1xu),
                            ('x2_u25', ok_x2u, ind_x2u)):
        m = ind.notna()
        res['correlacion_' + nombre] = {
            'n': int(m.sum()),
            'real': round(float(ok[m].mean()), 4),
            'producto': round(float(ind[m].mean()), 4)}
    # F — control: la combinada ya medida (ganador + más de 2,5)
    c_ho = df['cuota_home'] * df['cuota_over25']
    R['F_home_o25|todas'] = evaluar(df, c_ho.notna(), c_ho,
                                    df['r_home'] & df['r_o25'])

    pasan = {k: v for k, v in R.items() if v['pasa']}
    orden = sorted(pasan.items(), key=lambda kv: -kv[1]['peor_p5'])
    res['pasan'] = [k for k, _ in orden]
    with open('_v302_probables.json', 'w', encoding='utf-8') as f:
        json.dump(res, f, ensure_ascii=False, indent=1)

    print('filas %d · corte %s' % (res['filas'], res['corte']))
    for k in ('correlacion_1x_u25', 'correlacion_x2_u25'):
        print(k, res[k])
    print('\nPASAN LAS DOS PUERTAS: %d de %d' % (len(pasan), len(R)))
    for k, v in orden[:40]:
        print('%-34s n=%5d cuota %.2f acierta %.1f%%  ELEC %+.2f%% (p5 %+.2f)  '
              'JUICIO %+.2f%% (p5 %+.2f)'
              % (k, v['global']['n'], v['cuota_media'],
                 100 * v['global']['acierta'],
                 100 * v['eleccion']['roi'], 100 * v['eleccion']['p5'],
                 100 * v['juicio']['roi'], 100 * v['juicio']['p5']))
    # y las que el usuario ve como «muy probables», para enseñar lo que dan
    print('\nREFERENCIA (no pasan necesariamente):')
    for k in ('A_modelo|home|p0.70|c1.30', 'A_modelo|home|p0.60|c1.50',
              'B_mercado|home|p0.70|c1.30', 'C_ambos|home|p0.60|c1.50',
              'D_1x|p0.80|c1.15', 'D_x2|p0.70|c1.25',
              'E_1x_u25|p0.40|c1.80', 'E_x2_u25|p0.30|c1.80',
              'F_home_o25|todas'):
        v = R.get(k)
        if v and v['global']['n']:
            print('%-30s n=%5d acierta %.1f%% ELEC %s JUICIO %s' % (
                k, v['global']['n'], 100 * (v['global']['acierta'] or 0),
                v['eleccion'], v['juicio']))
    return 0


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.exit(main())
