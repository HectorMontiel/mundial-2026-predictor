# -*- coding: utf-8 -*-
"""
v336 — ¿LAS BAJAS SON INFORMACIÓN QUE LA CASA TODAVÍA NO TIENE?

El usuario eligió «ambas»; ésta es la B: buscar información que el precio
aún no lleve. La v334 mostró que el modelo propio no sabe nada que el precio
no sepa. Las bajas son la candidata natural: la v308 midió que mejoran
NUESTRO modelo de goles (H6). La pregunta ahora es más dura: ¿mejoran al
MERCADO?

LOS DATOS
  · `_v308_fondo/*.jsonl.gz` (FotMob): por equipo y partido, los habituales
    (titulares en ≥ la mitad de sus 10 anteriores) que NO estaban convocados,
    con el xG que aportaban y los minutos de zaga — la reconstrucción de la
    v308 (`_v308_bajas.cargar_fondo`).
  · `_v308_fd/*.csv` (football-data.co.uk): Pinnacle de APERTURA (PSH,
    P>2.5) y de CIERRE (PSCH, PC>2.5), y el marcador, en 8 ligas grandes.

LAS PRUEBAS (70 % antiguo para ajustar, 30 % reciente para juzgar)
  1. λ de la apertura (motor de mercado) ajustada con las bajas:
       λ' = λ · exp(β1 · xG perdido propio + β2 · zaga perdida del rival)
     ¿pronostica los goles mejor que la apertura sola? ¿y que el cierre?
  2. ¿Las bajas anticipan el MOVIMIENTO apertura → cierre del más de 2,5?
  3. Apostar a la cuota de APERTURA cuando las bajas dicen que hay valor:
     rendimiento y si se gana al cierre (CLV: apertura / cierre − 1).

OJO CON EL TIEMPO, Y SE DICE: la convocatoria se conoce cerca del partido;
la apertura se toma días antes. Si las bajas ganan a la apertura y no al
cierre, la información existe pero el mercado la recoge antes del pitido; en
producción las bajas de FotMob (lesión y sanción) se saben con días.

RESULTADOS (2026-10-07; 3.506 partidos cruzados, sep-2024 a ene-2026)
  1. NO mejoran el pronóstico de la apertura: −0,00035 log-ver. por
     partido (p5 −0,00185). β al mirar: xG perdido −0,162 · zaga rival +0,083.
  2. SÍ anticipan el movimiento: correlación 0,147 con lo que se mueve el
     más de 2,5 de apertura a cierre; cuando dicen −2 pts o más, el mercado
     se mueve −1,22 pts después.
  3. Apostar a la apertura con valor ≥ 0,02 (menos de 2,5): 70 apuestas al
     mirar, +0,6 % y +4,2 % mejor que el cierre (CLV); en el juicio no hay
     ni 30. Pista prometedora, muestra insuficiente: no se activa.
"""
from __future__ import annotations

import glob
import io
import json
import os
import sys

import numpy as np
import pandas as pd

import motor_mercado as mm

LIGAS_FD = {'E0': 'premier', 'E1': 'eng_championship', 'SP1': 'laliga',
            'I1': 'serie_a', 'D1': 'bundesliga', 'F1': 'ligue_1',
            'N1': 'eredivisie', 'P1': 'primeira'}
rng = np.random.default_rng(336)


def football_data() -> pd.DataFrame:
    filas = []
    for ruta in sorted(glob.glob('_v308_fd/*.csv')):
        cod = os.path.basename(ruta).split('_')[0]
        if cod not in LIGAS_FD:
            continue
        try:
            d = pd.read_csv(ruta, encoding='utf-8-sig')
        except Exception:
            d = pd.read_csv(ruta, encoding='latin-1')
        need = ['Date', 'HomeTeam', 'AwayTeam', 'FTHG', 'FTAG', 'PSH', 'PSD', 'PSA',
                'PSCH', 'PSCD', 'PSCA', 'P>2.5', 'P<2.5', 'PC>2.5', 'PC<2.5']
        if not all(c in d.columns for c in need):
            continue
        d = d[need].dropna().rename(columns={'P>2.5': 'Po', 'P<2.5': 'Pu', 'PC>2.5': 'PCo', 'PC<2.5': 'PCu'})
        d['liga'] = LIGAS_FD[cod]
        filas.append(d)
    d = pd.concat(filas, ignore_index=True)
    d['fecha'] = pd.to_datetime(d.Date, dayfirst=True, errors='coerce')
    return d[d.fecha.notna()].reset_index(drop=True)


def bajas_por_partido() -> pd.DataFrame:
    if os.path.exists('_v336_bajas.pkl'):
        return pd.read_pickle('_v336_bajas.pkl')
    import _v308_bajas as vb
    f = vb.cargar_fondo()
    f = f[f.n_prev >= 6]
    loc = f[f.local == 1].set_index('mid')
    vis = f[f.local == 0].set_index('mid')
    par = loc.join(vis, rsuffix='_v', how='inner')
    par = par[['fecha', 'liga', 'eq', 'eq_v', 'goles', 'goles_v', 'ataque_xg', 'defensa',
               'ataque_xg_v', 'defensa_v', 'n_bajas', 'n_bajas_v']].reset_index()
    par.to_pickle('_v336_bajas.pkl')
    return par


def cruza(fd, b):
    from _v332_cruce_descanso import norm, parecido
    fd = fd.copy()
    fd['h_n'], fd['a_n'] = fd.HomeTeam.map(norm), fd.AwayTeam.map(norm)
    b = b.copy()
    b['fecha'] = pd.to_datetime(b.fecha).dt.normalize()
    b['h_n'], b['a_n'] = b['eq'].map(norm), b['eq_v'].map(norm)
    idx = {}
    for i, (fe, lg, gh, ga) in enumerate(zip(b.fecha, b.liga, b.goles, b.goles_v)):
        idx.setdefault((lg, fe, gh, ga), []).append(i)
    filas = []
    for r in fd.itertuples():
        mejor, s_m = None, 0.0
        for dd in (0, -1, 1):
            for i in idx.get((r.liga, r.fecha + pd.Timedelta(days=dd), r.FTHG, r.FTAG), []):
                s = min(parecido(r.h_n, b.h_n.iat[i]), parecido(r.a_n, b.a_n.iat[i]))
                if s > s_m:
                    mejor, s_m = i, s
        if mejor is not None and s_m >= 0.5:
            x = b.iloc[mejor]
            filas.append({**r._asdict(), 'xg_h': x.ataque_xg, 'zaga_h': x.defensa,
                          'xg_a': x.ataque_xg_v, 'zaga_a': x.defensa_v,
                          'nb_h': x.n_bajas, 'nb_a': x.n_bajas_v})
    return pd.DataFrame(filas)


def lambdas(d, pref):
    """λ del motor de mercado con el 1X2 y el más/menos 2,5 de Pinnacle."""
    if pref == 'apertura':
        h, x, a, o, u = d.PSH, d.PSD, d.PSA, d['Po'], d['Pu']
    else:
        h, x, a, o, u = d.PSCH, d.PSCD, d.PSCA, d['PCo'], d['PCu']
    ih, ix, ia = 1 / h, 1 / x, 1 / a
    s = ih + ix + ia
    io_, iu = 1 / o, 1 / u
    T = mm.tabla()
    i = mm.lote((ih / s).values, (ia / s).values, (io_ / (io_ + iu)).values)
    return T['lh'][i], T['la'][i], (io_ / (io_ + iu)).values


def ll_pois(y, lam):
    from scipy.special import gammaln
    lam = np.clip(lam, 1e-6, None)
    return y * np.log(lam) - lam - gammaln(y + 1)


def ajusta(d, lh, la):
    from scipy.optimize import minimize
    yh, ya = d.FTHG.values, d.FTAG.values
    xh, za, xa, zh = d.xg_h.fillna(0).values, d.zaga_a.fillna(0).values, \
        d.xg_a.fillna(0).values, d.zaga_h.fillna(0).values

    def nll(b):
        l1 = lh * np.exp(b[0] * xh + b[1] * za)
        l2 = la * np.exp(b[0] * xa + b[1] * zh)
        return -(ll_pois(yh, l1).sum() + ll_pois(ya, l2).sum())
    return minimize(nll, [0.0, 0.0], method='Nelder-Mead').x


def p_mas25(lh, la):
    T = mm.tabla()
    paso, n = 0.02, int(round((4.6 - 0.05) / 0.02))
    i = np.clip(np.round((np.clip(lh, .05, 4.55) - .05) / paso).astype(int), 0, n - 1)
    j = np.clip(np.round((np.clip(la, .05, 4.55) - .05) / paso).astype(int), 0, n - 1)
    return T['P']['Más de 2.5'][i * n + j]


def main():
    fd = football_data()
    b = bajas_por_partido()
    d = cruza(fd, b).sort_values('fecha').reset_index(drop=True)
    print('football-data (8 ligas): %d partidos · con bajas reconstruidas: %d (%s a %s)'
          % (len(fd), len(d), d.fecha.min().date(), d.fecha.max().date()))
    lh_o, la_o, po_o = lambdas(d, 'apertura')
    lh_c, la_c, po_c = lambdas(d, 'cierre')
    dias = np.sort(d.fecha.unique())
    corte = dias[int(len(dias) * 0.7)]
    M = (d.fecha < corte).values
    J = ~M
    beta = ajusta(d[M], lh_o[M], la_o[M])
    print('β ajustados al mirar sobre la APERTURA: xG perdido propio %+.3f · zaga perdida '
          'del rival %+.3f   (v308, sobre nuestro modelo: −0,201 / +0,254)' % tuple(beta))
    adj = lambda lh, la: (lh * np.exp(beta[0] * d.xg_h.fillna(0).values + beta[1] * d.zaga_a.fillna(0).values),
                          la * np.exp(beta[0] * d.xg_a.fillna(0).values + beta[1] * d.zaga_h.fillna(0).values))
    lh_ob, la_ob = adj(lh_o, la_o)
    yh, ya = d.FTHG.values, d.FTAG.values
    out = {'n': len(d), 'beta': list(beta), 'corte': str(corte)[:10]}
    print('\n1. ¿PRONOSTICA MEJOR? log-verosimilitud de los goles en el JUICIO (%d partidos), mayor es mejor' % J.sum())
    res = {}
    for nom, (a1, a2) in (('apertura', (lh_o, la_o)), ('apertura + bajas', (lh_ob, la_ob)),
                          ('cierre', (lh_c, la_c))):
        v = ll_pois(yh, a1) + ll_pois(ya, a2)
        res[nom] = v
        print('   %-18s %.5f por partido' % (nom, v[J].mean()))
    for a_, b_ in (('apertura + bajas', 'apertura'), ('apertura + bajas', 'cierre')):
        dif = res[a_][J] - res[b_][J]
        g = pd.Series(dif).groupby(d.fecha[J].values).agg(['sum', 'size']).values
        bs = []
        for _ in range(3000):
            q = g[rng.integers(0, len(g), len(g))].sum(axis=0)
            bs.append(q[0] / q[1])
        print('   %s − %s: %+.5f por partido (p5 %+.5f)' % (a_, b_, dif.mean(), np.percentile(bs, 5)))
        out['%s - %s' % (a_, b_)] = [float(dif.mean()), float(np.percentile(bs, 5))]
    print('\n2. ¿ANTICIPAN EL MOVIMIENTO? más de 2,5 sin margen, apertura → cierre')
    p_ob = p_mas25(lh_ob, la_ob)
    p_o = p_mas25(lh_o, la_o)
    señal = p_ob - p_o                              # lo que las bajas mueven
    mov = po_c - po_o                               # lo que se movió el mercado
    c = np.corrcoef(señal[J], mov[J])[0, 1]
    print('   correlación (juicio) entre lo que dicen las bajas y lo que se movió: %.3f' % c)
    for lo, hi in ((-1, -0.02), (-0.02, -0.005), (-0.005, 0.005), (0.005, 0.02), (0.02, 1)):
        m = J & (señal > lo) & (señal <= hi)
        if m.sum() > 50:
            print('   bajas mueven el más de 2,5 en (%+.3f, %+.3f]: n %4d · el mercado se movió %+.2f pts'
                  % (lo, hi, m.sum(), 100 * mov[m].mean()))
    out['corr_movimiento'] = float(c)
    print('\n3. APOSTAR A LA APERTURA CUANDO LAS BAJAS DAN VALOR (más/menos de 2,5, Pinnacle)')
    tot = yh + ya
    for u in (0.02, 0.04, 0.06):
        for lado, p_adj, cuota_o, cuota_c, gana in (
                ('Más de 2.5', p_ob, d['Po'].values, d['PCo'].values, tot > 2.5),
                ('Menos de 2.5', 1 - p_ob, d['Pu'].values, d['PCu'].values, tot < 2.5)):
            ev = p_adj * cuota_o - 1
            for tramo, m0 in (('mirar', M), ('juzgar', J)):
                m = m0 & (ev >= u)
                if m.sum() < 30:
                    continue
                rinde = (gana[m] * cuota_o[m]).mean() - 1
                clv = (cuota_o[m] / cuota_c[m] - 1).mean()
                print('   valor ≥ %.2f %-13s %-6s n %4d · acierto %5.1f %% · rinde %+6.1f %% · '
                      'le gana al cierre %+5.1f %%' % (u, lado, tramo, m.sum(), 100 * gana[m].mean(),
                                                       100 * rinde, 100 * clv))
                out['%s|%.2f|%s' % (lado, u, tramo)] = [int(m.sum()), float(gana[m].mean()),
                                                        float(rinde), float(clv)]
    d.to_pickle('_v336_cruce.pkl')
    json.dump(out, open('_v336_bajas_mercado.json', 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1, default=float)


if __name__ == '__main__':
    # sin envolver la salida: los módulos que se importan dentro ya lo hacen
    # (y envolverla dos veces la cierra). Ejecutar con PYTHONIOENCODING=utf-8.
    main()
