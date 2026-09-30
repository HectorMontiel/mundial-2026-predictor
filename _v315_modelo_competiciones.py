# -*- coding: utf-8 -*-
"""
v315 — ¿EL MODELO PROPIO DE LAS COMPETICIONES CHICAS ACIERTA, Y SUMA A LA
CASA? SIMULACIÓN CON LOS FINALIZADOS.

1. AJUSTE (sólo agosto de 2026, todas las competiciones de FotMob): el paso
   de corrección y el decaimiento que dan menor log-loss en el 1X2 y menor
   Brier en más/menos 2,5. Nada de septiembre.
2. SIMULACIÓN (19-28 sep): los partidos del tablero de casas que el motor de
   ligas NO cubre, casados con su partido de FotMob, con la predicción del
   modelo hecha SÓLO con lo anterior (el modelo es secuencial) y la
   probabilidad del mercado (media de casas sin margen, devigado «potencia»).
   Se comparan modelo, mercado y la mezcla 50/50 que usa el motor de ligas.
3. REGLAS DE «METER»: por familia (resultado, goles, ambos marcan, goles por
   equipo), elegidas en elección (19-26) y juzgadas en prueba (27-28), con el
   acierto sumado a lo que ya se dice «meter» (v312) — no puede bajar.

Uso: python _v315_modelo_competiciones.py   (escribe el .json)

RESULTADO (29-sep-2026, 696 partidos simulados, 500 competiciones en la base)
  · El modelo SOLO acierta menos que la casa: Brier de resultado 0,206 contra
    0,185; la mezcla 50/50 que usa el motor de ligas tampoco mejora (p5 de
    la mejora −0,0095 en elección). En estas competiciones la casa sabe más.
  · Como VETO tampoco pasa: con el acierto sumado a lo que ya se dice
    «meter», en elección sin veto 79,62 % y con veto ≥ 60 % 79,53 % (en
    prueba sí subía, 82,92 → 83,12 %, pero se elige en elección). No se veta.
  · Lo que sí queda: el modelo propio se EXIGE (partido y equipos en la base)
    y se enseña como segunda opinión. Las reglas de mercado sobre estos
    partidos, en esta simulación: 88,1 % (286) y 85,2 % (115).
  · Exigir modelo propio deja fuera los partidos cuyos equipos no están en la
    base (sub-19/sub-20 que FotMob no publica): ésos no se podían liquidar.
"""
from __future__ import annotations

import json
import math
import os
import sys

import numpy as np
import pandas as pd

SALIDA = '_v315_modelo_competiciones.json'
CORTE = '2026-09-27'
DESDE_REG = pd.Timestamp('2026-08-01')


def _ll(p, y):
    return -math.log(max(p, 1e-6)) if y else -math.log(max(1 - p, 1e-6))


def ajustar(df):
    import modelo_competiciones as mc
    ago = (df.ini >= '2026-08-01') & (df.ini < '2026-09-01')
    res = {}
    for eta in (0.04, 0.06, 0.09):
        for dec in (0.995, 0.999):
            m = mc.Motor(eta=eta, decaimiento=dec)
            _, pred = mc.entrenar(df[df.ini < '2026-09-01'], motor=m,
                                  registrar_desde=pd.Timestamp('2026-08-01'))
            P = pd.DataFrame(pred, columns=['match_id', 'lh', 'la', 'nh', 'na'])
            P = P.merge(df[ago][['match_id', 'gh', 'ga']], on='match_id')
            P = P[(P.nh >= mc.MIN_PARTIDOS) & (P.na >= mc.MIN_PARTIDOS)]
            ll, br = [], []
            for r in P.itertuples(index=False):
                p = mc.probabilidades(r.lh, r.la)
                y = 0 if r.gh > r.ga else (1 if r.gh == r.ga else 2)
                ll.append(-math.log(max([p['home'], p['draw'], p['away']][y], 1e-6)))
                br.append((p['mas_2.5'] - (r.gh + r.ga > 2.5)) ** 2)
            res['%s|%s' % (eta, dec)] = {'n': len(P), 'logloss_1x2': float(np.mean(ll)),
                                        'brier_o25': float(np.mean(br))}
            print('ajuste', eta, dec, res['%s|%s' % (eta, dec)], flush=True)
    mejor = min(res, key=lambda k: res[k]['logloss_1x2'] + res[k]['brier_o25'])
    return res, mejor


def casar(df, pr):
    """Cada partido del tablero sin motor de ligas -> su partido de la base."""
    import cuotas_multi as cm
    import horario as hz
    import mercado_sin_modelo as msm
    import partidos_jugados as pj
    import _v313_sin_modelo as v313
    cub = {}
    for dia, par in v313.cubiertos():
        cub.setdefault(dia, []).append(par)
    base = df[df.ini >= '2026-09-18'].copy()
    filas = []
    for k, v in pr.items():
        ini = pd.Timestamp(v['inicio'], unit='s')
        dia = hz.fecha(str(v['inicio']))
        par = '%s vs %s' % (v['home'], v['away'])
        if any(msm.mismo_partido(par, x) for x in cub.get(dia, [])):
            continue
        c = base[(base.ini >= ini - pd.Timedelta(hours=3)) & (base.ini <= ini + pd.Timedelta(hours=3))]
        mejor, ms = None, 0
        for r in c.itertuples(index=False):
            if msm._categoria(v['home']) != msm._categoria(r.home) or \
                    msm._categoria(v['away']) != msm._categoria(r.away):
                continue
            s = min(cm._sim_club(pj._sin_femenino(v['home']), pj._sin_femenino(r.home)),
                    cm._sim_club(pj._sin_femenino(v['away']), pj._sin_femenino(r.away)))
            if abs((r.ini - ini).total_seconds()) > 1200 and s < .85:
                continue
            if s > ms:
                mejor, ms = r, s
        if mejor is None or ms < .6:
            continue
        filas.append({'clave': k, 'dia': dia, 'match_id': mejor.match_id,
                      'liga': mejor.liga, 'partido': par})
    return pd.DataFrame(filas)


def main():
    import modelo_competiciones as mc
    import resultados_fotmob as rf
    import _v314_ligas_chicas as v314
    df = rf.cargar()
    print('base', len(df), df.ini.min(), df.ini.max(), flush=True)
    out = {'base_partidos': int(len(df)), 'base_ligas': int(df.liga_id.nunique()),
           'base_equipos': int(pd.concat([df.home_id, df.away_id]).nunique())}
    aj, mejor = ajustar(df)
    out['ajuste_agosto'] = aj
    eta, dec = [float(x) for x in mejor.split('|')]
    out['elegido'] = {'eta': eta, 'decaimiento': dec}
    m = mc.Motor(eta=eta, decaimiento=dec)
    _, pred = mc.entrenar(df, motor=m, registrar_desde=pd.Timestamp('2026-09-15'))
    P = pd.DataFrame(pred, columns=['match_id', 'lh', 'la', 'nh', 'na'])
    P = P.merge(df[['match_id', 'gh', 'ga', 'home', 'away']], on='match_id')
    pr = v314.precios()
    C = casar(df, pr).merge(P, on='match_id')
    print('simulación:', len(C), 'partidos casados', flush=True)
    filas = []
    for r in C.itertuples(index=False):
        pm, q = v314.mercado(pr[r.clave])
        if r.nh < mc.MIN_PARTIDOS or r.na < mc.MIN_PARTIDOS:
            continue
        pmod = mc.probabilidades(r.lh, r.la)
        pmod['1X'], pmod['X2'] = pmod['homeOrDraw'], pmod['awayOrDraw']
        for sel in list(v314.SELS) + ['local_mas_0.5', 'local_mas_1.5',
                                      'visita_mas_0.5', 'visita_mas_1.5']:
            if sel not in pmod:
                continue
            y = _res(sel, r.gh, r.ga)
            filas.append({'dia': r.dia, 'partido': r.partido, 'liga': r.liga,
                          'sel': sel, 'fam': _fam(sel), 'y': int(y),
                          'p_mod': pmod[sel], 'p_mer': pm.get(sel),
                          'q': q.get(sel)})
    L = pd.DataFrame(filas)
    out['partidos_simulados'] = int(L.partido.nunique())
    rng = np.random.default_rng(0)
    # 2) ¿modelo, mercado o mezcla?
    out['brier'] = {}
    for fam, x in L.dropna(subset=['p_mer']).groupby('fam'):
        r_ = {}
        for tramo, y in (('eleccion', x[x.dia < CORTE]), ('prueba', x[x.dia >= CORTE])):
            b = {}
            for w in (0, .25, .5, .75, 1):
                p = w * y.p_mod + (1 - w) * y.p_mer
                b[str(w)] = round(float(((p - y.y) ** 2).mean()), 5)
            r_[tramo] = b
            r_[tramo]['n'] = int(len(y))
        # bootstrap de la mezcla 0,5 contra el mercado solo
        for tramo, y in (('eleccion', x[x.dia < CORTE]), ('prueba', x[x.dia >= CORTE])):
            d0 = (y.p_mer - y.y) ** 2
            d1 = (.5 * y.p_mod + .5 * y.p_mer - y.y) ** 2
            g = (d0 - d1).groupby(y.partido).sum()
            nn = y.groupby('partido').size()
            ms = g.index.values
            bs = [g[s].sum() / nn[s].sum() for s in (rng.choice(ms, len(ms)) for _ in range(1500))]
            r_[tramo]['mezcla_vs_mercado_p5'] = round(float(np.percentile(bs, 5)), 5)
        out['brier'][fam] = r_
    # modelo solo, calibración por banda (incluye goles por equipo sin cuota)
    out['calibracion_modelo'] = {}
    for fam, x in L.groupby('fam'):
        b = pd.cut(x.p_mod, [.5, .6, .7, .75, .8, .85, .9, 1])
        out['calibracion_modelo'][fam] = {
            str(k): {'n': int(len(v)), 'p': round(float(v.p_mod.mean()), 3),
                     'real': round(float(v.y.mean()), 3)}
            for k, v in x.groupby(b, observed=True)}
    # 3) reglas de «meter» con la mezcla 50/50
    L['p_mix'] = np.where(L.p_mer.notna(), .5 * L.p_mod + .5 * L.p_mer.fillna(0), np.nan)
    reglas = {}
    fams = {'resultado local / local o empate': ['home', '1X'],
            'resultado (todo)': ['home', 'away', '1X', 'X2'],
            'más de 1,5': ['mas_1.5'], 'menos de 3,5': ['menos_3.5'],
            'goles (todas las líneas)': [s for s in v314.SELS if _fam(s) == 'goles'],
            'ambos marcan': ['btts_si', 'btts_no']}
    for nombre, sels in fams.items():
        for lo, hi in ((.70, .80), (.75, .85), (.80, .90)):
            def elegir(x):
                y = x[x.sel.isin(sels) & (x.p_mix >= lo) & (x.p_mix <= hi)
                      & (x.q >= 1.10) & (x.q < 1.35)]
                return y.sort_values('p_mix', ascending=False).drop_duplicates('partido')
            reglas['%s · %.0f-%.0f %%' % (nombre, 100 * lo, 100 * hi)] = {
                'eleccion': _res_(elegir(L[L.dia < CORTE]), rng),
                'prueba': _res_(elegir(L[L.dia >= CORTE]), rng),
                '_f': elegir}
    out['reglas'] = {k: {kk: vv for kk, vv in v.items() if not kk.startswith('_')}
                     for k, v in reglas.items()}

    # 4) EL VETO DEL MODELO PROPIO sobre las reglas de mercado de la v313/v314
    # (local o local/empate y más de 1,5, mercado 80-90 %, cuota 1,10-1,35):
    # se mete sólo si el modelo propio le da al menos X. X se elige con el
    # acierto SUMADO a lo que ya se dice «meter» (v312) en ELECCIÓN; la prueba
    # juzga.
    v312 = json.load(open('_v312_patrones.json', encoding='utf-8'))
    veto = {}
    for x_min in (None, .5, .6, .7, .75, .8):
        def pick(y):
            z = y[y.sel.isin(['home', '1X', 'mas_1.5']) & (y.p_mer >= .8)
                  & (y.p_mer <= .9) & (y.q >= 1.10) & (y.q < 1.35)]
            if x_min is not None:
                z = z[z.p_mod >= x_min]
            # una de resultado y una de goles por partido
            z = z.assign(fam2=np.where(z.sel == 'mas_1.5', 'g', 'r'))
            return z.sort_values('p_mer', ascending=False).drop_duplicates(['partido', 'fam2'])
        fila = {}
        for tramo, y in (('eleccion', L[L.dia < CORTE]), ('prueba', L[L.dia >= CORTE])):
            z = pick(y)
            a = v312[tramo]['ahora']
            n_, v_ = a['apuestas'] + len(z), a['verdes'] + int(z.y.sum())
            fila[tramo] = {'n': int(len(z)), 'acierto': round(float(z.y.mean()), 4)
                           if len(z) else None,
                           'sumado_a_v312': round(v_ / n_, 4)}
        veto['sin veto' if x_min is None else 'modelo ≥ %.2f' % x_min] = fila
    out['veto_modelo'] = veto
    elegido = max(veto, key=lambda k: veto[k]['eleccion']['sumado_a_v312'])
    out['veto_elegido'] = elegido
    json.dump(out, open(SALIDA, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    L.to_csv('_v315_simulacion.csv', index=False)
    print(json.dumps({k: v for k, v in out.items() if k not in ('ajuste_agosto',)},
                     ensure_ascii=False, indent=1))


def _res_(x, rng):
    if not len(x):
        return {'n': 0}
    bs = [rng.choice(x.y.values, len(x)).mean() for _ in range(1500)]
    return {'n': int(len(x)), 'acierto': round(float(x.y.mean()), 4),
            'p5': round(float(np.percentile(bs, 5)), 4),
            'roi': round(float((x.y * x.q - 1).mean()), 4)}


def _fam(sel):
    if sel.startswith('local_') or sel.startswith('visita_'):
        return 'goles_equipo'
    if sel in ('home', 'away', '1X', 'X2', 'homeOrDraw', 'awayOrDraw', 'draw'):
        return 'resultado'
    return 'ambos' if sel.startswith('btts') else 'goles'


def _res(sel, gh, ga):
    t = gh + ga
    if sel.startswith('local_mas_'):
        return gh > float(sel.split('_')[-1])
    if sel.startswith('visita_mas_'):
        return ga > float(sel.split('_')[-1])
    if sel.startswith('mas_'):
        return t > float(sel.split('_')[1])
    if sel.startswith('menos_'):
        return t < float(sel.split('_')[1])
    return {'home': gh > ga, 'away': ga > gh, '1X': gh >= ga, 'X2': ga >= gh,
            'homeOrDraw': gh >= ga, 'awayOrDraw': ga >= gh,
            'btts_si': gh > 0 and ga > 0, 'btts_no': not (gh > 0 and ga > 0)}[sel]


if __name__ == '__main__':
    main()
