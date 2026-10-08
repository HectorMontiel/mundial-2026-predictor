#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v342 — ¿Por qué falla el «Gana X» del tenis a 1,38-1,50?

El usuario mandó cinco «Ganador» de tenis perdidos en Novibet (1,38-1,45) y
pidió calibrar mejor el tenis. Lo que se mide aquí:

  1. LA REGLA DE HOY. `veredicto_pick.evaluar` le aplica al tenis la curva
     por banda de cuota que se midió en el FÚTBOL (`calibrador_bandas`), y
     esa curva sube la probabilidad hasta 9 puntos en 1,40-1,50: un 62 % del
     modelo sale como 71 % y pasa a «meter».
  2. LAS ALTERNATIVAS, elegidas con el 70 % más viejo del histórico y
     juzgadas en el 30 % más reciente:
       · sin la curva del fútbol (modelo ≥ 65/70/75 %)
       · con el precio de la casa (como la v335 del fútbol)
       · con techo de cuota
  3. LA APP REAL: `_v331_meter_app.csv`, las apuestas de tenis que se dijeron
     «meter» y ya se liquidaron.

Datos: `pick_ledger_deportes.csv`, tenis ATP/WTA 2019-2026 fuera de muestra
(walk-forward), con la cuota de cierre de tennis-data.co.uk.
"""
import json
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, '.')
import calibrador_bandas as cb          # noqa: E402

B = 2000
rng = np.random.default_rng(342)


def cargar():
    d = pd.read_csv('pick_ledger_deportes.csv', low_memory=False)
    t = d[d.deporte == 'Tenis'].dropna(subset=['cuota_home', 'cuota_away'])
    t = t[(t.cuota_home > 1.01) & (t.cuota_away > 1.01)
          & (t.cuota_home < 50) & (t.cuota_away < 50)].copy()
    t['over'] = 1 / t.cuota_home + 1 / t.cuota_away
    t = t[(t.over > 1.0) & (t.over < 1.15)]
    filas = []
    for r in t.itertuples():
        for lado, p, c, cc, gana in (
                ('home', r.p_home, r.cuota_home, r.cuota_away, r.resultado == 0),
                ('away', r.p_away, r.cuota_away, r.cuota_home, r.resultado == 2)):
            pm = (1 / c) / (1 / c + 1 / cc)
            filas.append((r.fecha, r.liga, r.match_id, lado, p, c, pm, int(gana)))
    f = pd.DataFrame(filas, columns=['fecha', 'liga', 'id', 'lado', 'p', 'c',
                                     'pm', 'y'])
    # LO QUE LA APP LLAMA «MODELO» YA VA ENCOGIDO HACIA LA CASA: alpha_finder
    # pasa el tenis por `calibracion_segura.encoger_dos_vias` con w=0,25
    # (v78). `p` es el modelo crudo del ledger; `pa`, el número de la app.
    f['pa'] = 0.25 * f.p + 0.75 * f.pm
    f = f[f.pa >= 0.55].copy()           # sólo el lado que la app ve favorito
    f['adj'] = [min(0.99, max(0.01, p + max(-0.10, min(0.10, (cb.calibrar(p, c) or p) - p))))
                for p, c in zip(f.pa, f.c)]
    f = f.sort_values('fecha').reset_index(drop=True)
    corte = f.fecha.iloc[int(len(f) * 0.70)]
    f['tramo'] = np.where(f.fecha < corte, 'elige', 'juzga')
    return f, corte


def resumen(s):
    if len(s) == 0:
        return {'n': 0}
    return {'n': int(len(s)), 'acierto': round(float(s.y.mean()), 4),
            'promete': round(float(s.get('prom', s.p).mean()), 4),
            'cuota': round(float(s.c.mean()), 3),
            'roi': round(float((s.y * s.c - 1).mean()), 4)}


def p5_dif(a, b):
    """Bootstrap por día de (acierto regla b − acierto regla a)."""
    dias = sorted(set(a.fecha) | set(b.fecha))
    ga = a.groupby('fecha').y.agg(['sum', 'size']).reindex(dias, fill_value=0)
    gb = b.groupby('fecha').y.agg(['sum', 'size']).reindex(dias, fill_value=0)
    A, NA, Bv, NB = (ga['sum'].values, ga['size'].values,
                     gb['sum'].values, gb['size'].values)
    out = []
    for _ in range(B):
        i = rng.integers(0, len(dias), len(dias))
        na, nb = NA[i].sum(), NB[i].sum()
        if na and nb:
            out.append(Bv[i].sum() / nb - A[i].sum() / na)
    out = np.array(out)
    return round(float(np.mean(out)), 4), round(float(np.percentile(out, 5)), 4)


def p5_roi(s):
    g = s.assign(g=s.y * s.c - 1).groupby('fecha').g.agg(['sum', 'size'])
    S, N = g['sum'].values, g['size'].values
    out = []
    for _ in range(B):
        i = rng.integers(0, len(g), len(g))
        out.append(S[i].sum() / max(1, N[i].sum()))
    return round(float(np.percentile(out, 5)), 4)


REGLAS = {
    'hoy (curva del fútbol, ≥65 %)': lambda f: f[f.adj >= 0.65].assign(prom=lambda x: x.adj),
    'modelo ≥65 % sin curva': lambda f: f[f.pa >= 0.65],
    'modelo ≥70 % sin curva': lambda f: f[f.pa >= 0.70],
    'modelo ≥75 % sin curva': lambda f: f[f.pa >= 0.75],
    'hoy y cuota <1,35': lambda f: f[(f.adj >= 0.65) & (f.c < 1.35)].assign(prom=lambda x: x.adj),
}
for X in (0.70, 0.72, 0.74, 0.76, 0.78):
    for Y in (0.60, 0.65, 0.70):
        REGLAS['casa ≥%d %% y modelo ≥%d %%' % (X * 100, Y * 100)] = (
            lambda f, X=X, Y=Y: f[(f.pm >= X) & (f.pa >= Y)].assign(prom=lambda x: x.pm))


def main():
    f, corte = cargar()
    print('lados favoritos del modelo:', len(f), 'corte', corte)
    # calibración: ¿qué cumple lo que promete en 1,35-1,50?
    cal = {}
    z = f[(f.c >= 1.35) & (f.c < 1.50)]
    for nombre, col in (('modelo crudo', 'p'), ('modelo de la app', 'pa'),
                        ('app + curva del fútbol', 'adj'),
                        ('casa sin margen', 'pm')):
        cal[nombre] = {'promete': round(float(z[col].mean()), 4),
                       'acierto': round(float(z.y.mean()), 4),
                       'logloss': round(float(-np.mean(
                           z.y * np.log(z[col]) + (1 - z.y) * np.log(1 - z[col]))), 4)}
    print('\n1,35-1,50 (n=%d):' % len(z), json.dumps(cal, ensure_ascii=False, indent=1))
    # por banda de cuota: qué pasa cuando la regla de hoy dice «meter»
    hoy = f[f.adj >= 0.65].copy()
    hoy['banda'] = pd.cut(hoy.c, [1, 1.15, 1.25, 1.35, 1.45, 1.6, 3])
    tb = hoy.groupby('banda', observed=True).agg(
        n=('y', 'size'), acierto=('y', 'mean'), modelo=('pa', 'mean'),
        dice=('adj', 'mean'), casa=('pm', 'mean'), cuota=('c', 'mean')).round(3)
    print('\nregla de hoy por banda:\n', tb)

    res = {}
    for nombre, regla in REGLAS.items():
        res[nombre] = {t: resumen(regla(f[f.tramo == t])) for t in ('elige', 'juzga')}
    print('\n%-34s %26s %26s' % ('regla', 'ELIGE n/acierto/ROI', 'JUZGA n/acierto/ROI'))
    for k, v in res.items():
        e, j = v['elige'], v['juzga']
        print('%-34s %6d %6.1f %6.1f     %6d %6.1f %6.1f' % (
            k, e['n'], 100 * e['acierto'], 100 * e['roi'],
            j['n'], 100 * j['acierto'], 100 * j['roi']))
    # la mejor del tramo de elegir, entre las de casa+modelo, con N >= la mitad
    base_e = res['hoy (curva del fútbol, ≥65 %)']['elige']
    cands = [(k, v) for k, v in res.items() if k.startswith('casa')
             and v['elige']['n'] >= 0.5 * base_e['n']]
    mejor = max(cands, key=lambda kv: (kv[1]['elige']['roi'], kv[1]['elige']['acierto']))
    print('\nelegida con el 70 %:', mejor[0])
    j = f[f.tramo == 'juzga']
    a = REGLAS['hoy (curva del fútbol, ≥65 %)'](j)
    bm = REGLAS[mejor[0]](j)
    sin = REGLAS['modelo ≥70 % sin curva'](j)
    comp = {
        'elegida_vs_hoy_acierto': p5_dif(a, bm),
        'sin_curva70_vs_hoy_acierto': p5_dif(a, sin),
        'roi_p5_hoy': p5_roi(a), 'roi_p5_elegida': p5_roi(bm),
        'roi_p5_sin_curva70': p5_roi(sin),
    }
    print(json.dumps(comp, ensure_ascii=False, indent=1))
    json.dump({'corte': corte, 'calibracion_135_150': cal, 'reglas': res,
               'elegida': mejor[0], 'juicio': comp,
               'banda_hoy': tb.reset_index().astype(str).to_dict('records')},
              open('_v342_tenis.json', 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)


if __name__ == '__main__':
    main()
