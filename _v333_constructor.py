# -*- coding: utf-8 -*-
"""
v333 — VALIDACIÓN 4: EL CONSTRUCTOR (BET BUILDER) Y LA CORRELACIÓN.

Los boletos del usuario usan mucho el «Constructor» de Novibet: dos o más
patas del MISMO partido (1X + menos de 3,5, gana Bayern + más de 2,5…). Esas
patas no son independientes. Si van en el mismo sentido, la probabilidad de
que salgan juntas es MAYOR que el producto de las dos, y una casa que las
paga cerca del producto las está regalando; si van en sentido contrario, al
revés.

El motor de mercado tiene la matriz de marcadores entera, así que da la
probabilidad CONJUNTA exacta. Aquí se mide, en el tramo de juzgar del
histórico (2024-08 a 2026-10, 24 mil partidos):

  · conjunta del motor vs lo que de verdad pasó (¿calibra?)
  · factor de correlación = conjunta / (producto de las dos sueltas)
  · por combinación típica y por fuerza del favorito

No hay histórico de precios del constructor, así que esto no mide
rendimiento: mide la herramienta y dice QUÉ combinaciones juegan a favor.
"""
from __future__ import annotations

import io
import json
import sys

import numpy as np
import pandas as pd

import motor_mercado as mm
from _v333_motor import datos

# (la salida en UTF-8 ya la pone `_v333_motor` al importarse)

G = np.arange(mm.MAXG)
I, J_ = np.meshgrid(G, G, indexing='ij')


def mascaras(fav_local: bool):
    """Máscaras sobre la matriz de marcadores para cada pata (fav = el de
    mayor probabilidad de ganar)."""
    if fav_local:
        gana_f, no_pierde_f = I > J_, I >= J_
        f_mas15 = I > 1.5
    else:
        gana_f, no_pierde_f = J_ > I, J_ >= I
        f_mas15 = J_ > 1.5
    t = I + J_
    return {
        'Gana favorito': gana_f, 'Favorito o empate': no_pierde_f,
        'Más de 1.5': t > 1.5, 'Más de 2.5': t > 2.5, 'Menos de 3.5': t < 3.5,
        'Menos de 4.5': t < 4.5, 'Ambos marcan sí': (I > 0) & (J_ > 0),
        'Ambos marcan no': ~((I > 0) & (J_ > 0)), 'Favorito más de 1.5': f_mas15,
    }


COMBOS = [('Gana favorito', 'Más de 1.5'), ('Gana favorito', 'Más de 2.5'),
          ('Gana favorito', 'Menos de 4.5'), ('Gana favorito', 'Ambos marcan no'),
          ('Gana favorito', 'Favorito más de 1.5'),
          ('Favorito o empate', 'Menos de 3.5'), ('Favorito o empate', 'Menos de 4.5'),
          ('Favorito o empate', 'Ambos marcan sí'), ('Favorito o empate', 'Más de 1.5'),
          ('Más de 1.5', 'Ambos marcan sí'), ('Menos de 3.5', 'Ambos marcan no')]


def main():
    d = datos()
    dias = np.sort(d.fecha.unique())
    corte = dias[int(len(dias) * 0.7)]
    d = d[d.fecha >= corte].reset_index(drop=True)
    T = mm.tabla()
    idx = mm.lote(d.m1.values, d.m2.values, d.mo.values)
    M = T['M'][idx]                                   # (n, G, G)
    fav_local = (d.m1 >= d.m2).values
    gh, ga = d.goles_local.values.astype(int), d.goles_visit.values.astype(int)
    pfav = np.where(fav_local, T['P']['Gana local'][idx], T['P']['Gana visita'][idx])
    out = {}
    print('JUICIO: %d partidos (%s en adelante)' % (len(d), str(corte)[:10]))
    print('combinación                              conjunta  producto  factor   pasó   (n)')
    for a, b in COMBOS:
        pj, pa_, pb_, real = np.zeros(len(d)), np.zeros(len(d)), np.zeros(len(d)), np.zeros(len(d))
        for fl in (True, False):
            sel = fav_local == fl
            mk = mascaras(fl)
            A, B = mk[a], mk[b]
            pj[sel] = (M[sel] * (A & B)[None]).sum(axis=(1, 2))
            pa_[sel] = (M[sel] * A[None]).sum(axis=(1, 2))
            pb_[sel] = (M[sel] * B[None]).sum(axis=(1, 2))
            real[sel] = (A & B)[np.clip(gh[sel], 0, mm.MAXG - 1), np.clip(ga[sel], 0, mm.MAXG - 1)]
        prod = pa_ * pb_
        nom = '%s + %s' % (a, b)
        print('%-40s %6.1f %%  %6.1f %%  ×%.2f  %5.1f %%  (%d)'
              % (nom, 100 * pj.mean(), 100 * prod.mean(), pj.mean() / prod.mean(),
                 100 * real.mean(), len(d)))
        # por fuerza del favorito: donde se parece a los boletos (favorito claro)
        res = {'conjunta': pj.mean(), 'producto': prod.mean(), 'real': real.mean(), 'bandas': {}}
        for lo, hi in ((.45, .60), (.60, .75), (.75, .95)):
            m = (pfav >= lo) & (pfav < hi)
            if m.sum() > 200:
                res['bandas']['%.2f-%.2f' % (lo, hi)] = [int(m.sum()), pj[m].mean(), prod[m].mean(), real[m].mean()]
        out[nom] = res
    print('\npor fuerza del favorito (conjunta del motor / producto / lo que pasó):')
    for nom, r in out.items():
        trozos = ['fav %s: %.0f/%.0f/%.0f %% (×%.2f)' % (k, 100 * v[1], 100 * v[2], 100 * v[3], v[1] / v[2])
                  for k, v in r['bandas'].items()]
        print('   %-40s %s' % (nom, ' · '.join(trozos)))
    json.dump(out, open('_v333_constructor.json', 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1, default=float)


if __name__ == '__main__':
    main()
