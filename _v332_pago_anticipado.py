# -*- coding: utf-8 -*-
"""
v332 — ¿CUÁNTO VALE EL «PAGO ANTICIPADO POR 2 GOLES»?

En los boletos ganadores del usuario, nueve patas «Gana X» de Novibet dicen
«Ganado por Pago Anticipado por 2 Goles»: la casa da la apuesta por ganada
en cuanto X se pone dos goles arriba, acabe como acabe. Eso SUBE la
probabilidad de la pata sin tocar la cuota, que es justo lo que hace falta
para que una pata a 1,40-1,80 deje de perder dinero.

Se mide en dos capas sobre `_v332_ledger_descanso.pkl` (32 mil partidos con
λ del modelo, cuotas y marcador al descanso):

  1. LO OBSERVADO (cota inferior): «ganó, o iba +2 al descanso». No ve las
     remontadas tras ir +2 en la 2.ª parte, así que se queda corto.
  2. LO SIMULADO: un proceso de Poisson minuto a minuto con la λ del modelo
     de cada partido (la 2.ª parte con su peso medido en Flashscore) que
     sigue la diferencia y si llegó a +2. Antes de creerle, tiene que
     reproducir la capa 1 —el +2 al descanso que no acabó en victoria— por
     franjas de probabilidad. Si la reproduce, su «+2 en cualquier minuto»
     es creíble.

Después: lo que rinde «Gana X» con y sin el pago anticipado, por franja de
cuota, con las cuotas reales del histórico. 70/30 por fecha y bootstrap.
"""
from __future__ import annotations

import io
import json
import sys

import numpy as np
import pandas as pd

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8',
                              errors='replace')
rng = np.random.default_rng(332)
MAXD = 12


def peso_segunda_parte() -> float:
    f = pd.read_csv('resultados_flashscore.csv.gz')
    f = f[f.hh.notna()]
    tot = (f.gh + f.ga).sum()
    pri = (f.hh + f.ha).sum()
    return float((tot - pri) / tot)


def dp(lh: np.ndarray, la: np.ndarray, s2: float):
    """Por partido: P(gana local), P(gana visita), P(local llega a +2 alguna
    vez y no gana), lo mismo visita, y las versiones «+2 al descanso»."""
    n = len(lh)
    # estado: diferencia (−MAXD..MAXD) × llegó local a +2 × llegó visita a +2
    D = 2 * MAXD + 1
    P = np.zeros((n, D, 2, 2))
    P[:, MAXD, 0, 0] = 1.0
    ht = None
    for minuto in range(90):
        w = (1 - s2) / 45 if minuto < 45 else s2 / 45
        ph = np.clip(lh * w, 0, 0.5)[:, None, None, None]
        pa = np.clip(la * w, 0, 0.5)[:, None, None, None]
        Q = P * (1 - ph - pa)
        Q[:, 1:] += P[:, :-1] * ph            # gol local: diferencia +1
        Q[:, :-1] += P[:, 1:] * pa            # gol visita: diferencia −1
        # marcar «llegó a +2»
        for d_idx in range(D):
            dif = d_idx - MAXD
            if dif >= 2:
                Q[:, d_idx, 1, :] += Q[:, d_idx, 0, :]
                Q[:, d_idx, 0, :] = 0
            if dif <= -2:
                Q[:, d_idx, :, 1] += Q[:, d_idx, :, 0]
                Q[:, d_idx, :, 0] = 0
        P = Q
        if minuto == 44:
            ht = P.copy()
    dif = np.arange(D) - MAXD
    gana_h = P[:, dif > 0].sum(axis=(1, 2, 3))
    gana_a = P[:, dif < 0].sum(axis=(1, 2, 3))
    ep_h = P[:, dif <= 0][:, :, 1, :].sum(axis=(1, 2))        # llegó a +2 y no ganó
    ep_a = P[:, dif >= 0][:, :, :, 1].sum(axis=(1, 2))
    # «+2 al descanso y no ganó» necesita el cruce descanso→final: se
    # aproxima con P(+2 al descanso) − P(+2 al descanso y ganó) vía otra
    # pasada desde el estado del descanso
    ht_h2 = ht[:, dif >= 2].sum(axis=(1, 2, 3))
    ht_a2 = ht[:, dif <= -2].sum(axis=(1, 2, 3))
    return gana_h, gana_a, ep_h, ep_a, ht_h2, ht_a2


def main():
    s2 = peso_segunda_parte()
    print('Flashscore: la 2.ª parte lleva el %.1f %% de los goles' % (100 * s2))
    d = pd.read_pickle('_v332_ledger_descanso.pkl')
    d = d[d.hh.notna() & d.lam_h.notna() & d.lam_a.notna()].reset_index(drop=True)
    gh, ga, ep_h, ep_a, ht_h2, ht_a2 = dp(d.lam_h.values, d.lam_a.values, s2)
    d['sim_gana_h'], d['sim_gana_a'] = gh, ga
    d['sim_ep_h'], d['sim_ep_a'] = ep_h, ep_a
    d['sim_ht2_h'], d['sim_ht2_a'] = ht_h2, ht_a2
    filas = []
    for lado, p_mod, cuota, gan, ht2, sim_g, sim_ep, sim_ht2 in (
            ('local', d.p_home, d.cuota_home, d.goles_local > d.goles_visit,
             (d.hh - d.ha) >= 2, d.sim_gana_h, d.sim_ep_h, d.sim_ht2_h),
            ('visita', d.p_away, d.cuota_away, d.goles_visit > d.goles_local,
             (d.ha - d.hh) >= 2, d.sim_gana_a, d.sim_ep_a, d.sim_ht2_a)):
        filas.append(pd.DataFrame({
            'fecha': d.fecha, 'liga': d.liga, 'lado': lado, 'p': p_mod,
            'cuota': cuota, 'gana': gan.astype(int),
            'gana_o_ht2': (gan | ht2).astype(int), 'ht2': ht2.astype(int),
            'sim_gana': sim_g, 'sim_ep': sim_ep, 'sim_ht2': sim_ht2}))
    x = pd.concat(filas, ignore_index=True)
    # 1. ¿la simulación reproduce lo observado?
    print('\n1. VALIDACIÓN DE LA SIMULACIÓN (por franja de probabilidad del modelo)')
    print('   franja      n      gana real/sim     +2 al descanso real/sim')
    x['banda'] = pd.cut(x.p, [0, .3, .45, .55, .65, .75, .9])
    val = {}
    for b, s in x.groupby('banda', observed=True):
        print('   %-10s %6d   %5.1f / %5.1f %%      %5.1f / %5.1f %%'
              % (b, len(s), 100 * s.gana.mean(), 100 * s.sim_gana.mean(),
                 100 * s.ht2.mean(), 100 * s.sim_ht2.mean()))
        val[str(b)] = [len(s), s.gana.mean(), s.sim_gana.mean(), s.ht2.mean(),
                       s.sim_ht2.mean()]
    # 2. cuánto sube la pata
    print('\n2. CUÁNTO SUBE «GANA X» CON EL PAGO ANTICIPADO')
    print('   franja      gana    + observado(descanso)   + simulado(cualquier minuto)')
    sube = {}
    for b, s in x.groupby('banda', observed=True):
        print('   %-10s %5.1f %%   %5.1f %% (+%.1f)            %5.1f %% (+%.1f)'
              % (b, 100 * s.gana.mean(), 100 * s.gana_o_ht2.mean(),
                 100 * (s.gana_o_ht2.mean() - s.gana.mean()),
                 100 * (s.gana.mean() + s.sim_ep.mean()), 100 * s.sim_ep.mean()))
        sube[str(b)] = [s.gana.mean(), s.gana_o_ht2.mean(), s.sim_ep.mean()]
    # 3. lo que rinde con las cuotas reales
    print('\n3. LO QUE RINDE «GANA X» CON CUOTA REAL (rendimiento por peso apostado)')
    y = x[x.cuota.notna() & (x.cuota > 1)].copy()
    dias = np.sort(y.fecha.unique())
    corte = dias[int(len(dias) * 0.7)]
    y['cband'] = pd.cut(y.cuota, [1, 1.3, 1.5, 1.8, 2.2, 3.0])
    rinde = {}
    print('   cuota        tramo   n      sin pago   con descanso   con simulado')
    for b, s in y.groupby('cband', observed=True):
        for t, q in (('mirar', s[s.fecha < corte]), ('juzgar', s[s.fecha >= corte])):
            r0 = (q.gana * q.cuota).mean() - 1
            r1 = (q.gana_o_ht2 * q.cuota).mean() - 1
            r2 = ((q.gana + q.sim_ep) * q.cuota).mean() - 1
            print('   %-11s %-6s %6d   %+6.1f %%    %+6.1f %%       %+6.1f %%'
                  % (b, t, len(q), 100 * r0, 100 * r1, 100 * r2))
            rinde['%s|%s' % (b, t)] = [len(q), r0, r1, r2]
    # bootstrap por día del rendimiento con el pago (observado, cota inferior)
    print('\n   bootstrap por día (juzgar), cuota 1,30-1,80, «con descanso» = cota inferior:')
    q = y[(y.fecha >= corte) & (y.cuota >= 1.3) & (y.cuota < 1.8)]
    g = q.assign(v0=q.gana * q.cuota, v1=q.gana_o_ht2 * q.cuota).groupby('fecha')[
        ['v0', 'v1', 'cuota']].agg(['sum', 'count'])
    A = np.c_[g[('v0', 'sum')], g[('v1', 'sum')], g[('v0', 'count')]]
    b0, b1 = [], []
    for _ in range(3000):
        s = A[rng.integers(0, len(A), len(A))].sum(axis=0)
        b0.append(s[0] / s[2] - 1); b1.append(s[1] / s[2] - 1)
    print('   sin pago: media %+.2f %% (p5 %+.2f) · con pago (descanso): media %+.2f %% (p5 %+.2f)'
          % (100 * np.mean(b0), 100 * np.percentile(b0, 5),
             100 * np.mean(b1), 100 * np.percentile(b1, 5)))
    x.to_pickle('_v332_patas_ganador.pkl')
    json.dump({'s2': s2, 'validacion': val, 'sube': sube, 'rinde': rinde,
               'boot': {'sin': [np.mean(b0), np.percentile(b0, 5)],
                        'con_descanso': [np.mean(b1), np.percentile(b1, 5)]}},
              open('_v332_pago_anticipado.json', 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1, default=float)


if __name__ == '__main__':
    main()
