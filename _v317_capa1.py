# -*- coding: utf-8 -*-
"""
v317 — LA CAPA 1 CON LO MEJOR DEL MODELO, Y UN SEGUNDO NIVEL CON MÁS CUOTA.

Tres mediciones, en `_v317_capa1.json`:

1. HISTÓRICO DE RESULTADO (`pick_ledger.csv`, predicción fuera de muestra y
   cuota de la casa; 70 % antiguo para elegir, 30 % reciente para juzgar):
     · 🏆 modelo ≥ 70 % y casa sin margen 80-88 %, por tipo (ganador/doble);
     · 🔷 ganador, casa 55-70 %, modelo ≥ 70 % (≥ 60 % si la casa da 65-70 %),
       con acierto, ganancia y bootstrap.
2. LA TARJETA SIMULADA (`_v312_patrones.py` con los partidos del 20 al 29
   de septiembre, histórico recortado a cada fecha): lo que se dice «meter»
   antes (`_v317_candidatas.csv`) y con lo mejor del modelo dentro
   (`_v317b_candidatas.csv`), con bootstrap por partido de la mejora.

Uso: python _v317_capa1.py
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

CORTE_SIM = '2026-09-26'


def _ledger():
    d = pd.read_csv('pick_ledger.csv', low_memory=False)
    d = d[d['liga'] != 'liga']
    for c in ['cuota_home', 'cuota_draw', 'cuota_away', 'p_home', 'p_draw',
              'p_away', 'resultado']:
        d[c] = pd.to_numeric(d[c], errors='coerce')
    d = d.dropna(subset=['cuota_home', 'cuota_draw', 'cuota_away', 'resultado',
                         'p_home'])
    d = d[(d.cuota_home > 1) & (d.cuota_draw > 1) & (d.cuota_away > 1)]
    inv = 1 / d[['cuota_home', 'cuota_draw', 'cuota_away']]
    q = inv.div(inv.sum(axis=1), axis=0)
    q.columns = ['q_h', 'q_d', 'q_a']
    d = pd.concat([d, q], axis=1)
    d['fecha'] = pd.to_datetime(d['fecha'], errors='coerce')
    d = d.sort_values('fecha')
    corte = d['fecha'].iloc[int(len(d) * .7)]
    r = d['resultado'].astype(int)
    c1x = 1 / (1 / d.cuota_home + 1 / d.cuota_draw)
    cx2 = 1 / (1 / d.cuota_away + 1 / d.cuota_draw)
    sel = {'home': (d.p_home, d.q_h, r == 0, d.cuota_home),
           'away': (d.p_away, d.q_a, r == 2, d.cuota_away),
           '1X': (d.p_home + d.p_draw, d.q_h + d.q_d, r != 2, c1x),
           'X2': (d.p_away + d.p_draw, d.q_a + d.q_d, r != 0, cx2)}
    F = pd.concat([pd.DataFrame({'sel': s, 'p': p, 'q': qq, 'y': y.astype(int),
                                 'c': c, 'fecha': d.fecha})
                   for s, (p, qq, y, c) in sel.items()])
    F['tramo'] = np.where(F.fecha < corte, 'elegir', 'juzgar')
    F['tipo'] = np.where(F.sel.isin(['home', 'away']), 'ganador', 'doble')
    F['ret'] = F.y * F.c - 1
    return F, len(d), str(corte.date())


def _resumen(z, rng, con_roi=True):
    out = {}
    for tr, x in z.groupby('tramo'):
        idx = rng.integers(0, len(x), size=(2000, len(x)))
        fila = {'n': int(len(x)), 'cuota_media': round(float(x.c.mean()), 3),
                'acierto': round(float(x.y.mean()), 4),
                'p5_acierto': round(float(np.percentile(x.y.values[idx].mean(axis=1), 5)), 4)}
        if con_roi:
            fila['ganancia'] = round(float(x.ret.mean()), 4)
            fila['p5_ganancia'] = round(float(np.percentile(x.ret.values[idx].mean(axis=1), 5)), 4)
        out[tr] = fila
    return out


def _simulacion(rng):
    def meter(f):
        d = pd.read_csv(f).dropna(subset=['acierto'])
        d['tramo'] = np.where(d['dia'] <= CORTE_SIM, 'elegir', 'juzgar')
        return d, d[d.mostrada & (d.veredicto == 'meter')]
    a, ma = meter('_v317_candidatas.csv')
    b, mb = meter('_v317b_candidatas.csv')
    out = {'partidos': int(b.partido.nunique()), 'candidatas': int(len(b))}
    for nombre, m, todo in (('antes', ma, a), ('ahora', mb, b)):
        g = m.groupby('tramo')['acierto'].agg(['size', 'mean', 'sum'])
        out[nombre] = {tr: {'apuestas': int(f['size']), 'acierto': round(float(f['mean']), 4),
                            'rojos': int(f['size'] - f['sum'])} for tr, f in g.iterrows()}
        out[nombre]['partidos_con_algo'] = int(m.partido.nunique())
    for tr in ('elegir', 'juzgar'):
        A, B = ma[ma.tramo == tr], mb[mb.tramo == tr]
        ids = sorted(set(A.partido) | set(B.partido))
        ga = A.groupby('partido').acierto.agg(['sum', 'size']).reindex(ids, fill_value=0)
        gb = B.groupby('partido').acierto.agg(['sum', 'size']).reindex(ids, fill_value=0)
        bs = []
        for _ in range(2000):
            s = rng.choice(len(ids), len(ids))
            x, y = ga.iloc[s].sum(), gb.iloc[s].sum()
            bs.append(y['sum'] / y['size'] - x['sum'] / x['size'])
        out['mejora_' + tr] = {
            'puntos': round(float(gb['sum'].sum() / gb['size'].sum()
                                  - ga['sum'].sum() / ga['size'].sum()), 4),
            'p5': round(float(np.percentile(bs, 5)), 4)}
    el = mb[mb.apuesta.str.contains(' o empate') & (mb.p_mercado >= .8)
            & (mb.p_mercado < .88)]
    out['capa1_en_la_simulacion'] = {tr: {'n': int(len(x)), 'acierto': round(float(x.acierto.mean()), 4)}
                                     for tr, x in el.groupby('tramo')}
    return out


def main():
    rng = np.random.default_rng(317)
    F, n, corte = _ledger()
    out = {'ledger_partidos': n, 'ledger_corte': corte}
    el = F[(F.p >= .70) & (F.q >= .80) & (F.q < .88)]
    out['capa1'] = {t: _resumen(z, rng, con_roi=False) for t, z in el.groupby('tipo')}
    resto = F[(F.p >= .70) & (F.p < .80) & (F.q < .80)]
    out['resto_modelo_70_80'] = _resumen(resto, rng, con_roi=False)
    G = F[(F.tipo == 'ganador') & (F.c >= 1.35)]
    rz = G[(G.q >= .55) & (G.q < .70) & ((G.p >= .70) | ((G.q >= .65) & (G.p >= .60)))]
    out['riesgo'] = _resumen(rz, rng)
    out['riesgo_por_cuota'] = {
        str(k): {tr: {'n': int(len(x)), 'acierto': round(float(x.y.mean()), 4),
                      'ganancia': round(float(x.ret.mean()), 4)} for tr, x in g.groupby('tramo')}
        for k, g in rz.groupby(pd.cut(rz.c, [1.3, 1.45, 1.6, 1.8, 2.2]), observed=True)}
    D = F[(F.tipo == 'doble') & (F.c >= 1.40) & (F.c <= 2.10)]
    out['doble_con_cuota_alta'] = _resumen(D[D.p >= .60], rng)
    out['simulacion'] = _simulacion(rng)
    json.dump(out, open('_v317_capa1.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
