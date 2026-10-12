#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v371c — Afinar la regla de las sencillas a 1,30+ con los finalizados.

Sobre las escaleras de Playdoit (`_v371_sencillas.playdoit`, sin los mercados
que pierden contra la casa: tarjetas y córners de equipo) se prueban:
  casa            — la más probable según la casa sin margen;
  casa_veto3      — igual, pero fuera las que el método ve 3+ pts POR DEBAJO
                    de la casa (medido: «casa ve +5» acierta 56,7 %);
  casa_y_metodo   — sólo donde el método ve lo mismo o más que la casa;
  consenso        — la mejor en el peor de los dos.
Con cuota mínima 1,25 / 1,30 / 1,35 (máxima 1,70), una pata por partido. Para
cada una: el acierto de las patas (dos mitades, p5 de la diferencia contra
«casa») y los boletos del día de 2, 3, 4 y 5 patas (enteros en cada mitad,
con 3+ rojas, momio, ganancia).
Escribe `_v371c_refinar.json`.
"""
import importlib.util as iu
import json
import sys

import numpy as np

s = iu.spec_from_file_location('v371', '_v371_sencillas.py')
V = iu.module_from_spec(s)
s.loader.exec_module(V)
rng = np.random.default_rng(3713)
PERDEDORES = ('tarjetas equipo', 'tarjetas total', 'corners equipo')


def elegir(x, regla, cmin):
    z = x[(x.cuota >= cmin) & (x.cuota <= 1.70) & ~x.mercado.isin(PERDEDORES)]
    if regla == 'casa_veto3':
        z = z[z.p_m >= z.p_c - 0.03]
    elif regla == 'casa_y_metodo':
        z = z[z.p_m >= z.p_c]
    sc = np.minimum(z.p_m, z.p_c) if regla == 'consenso' else z.p_c
    z = z.assign(score=sc).sort_values('score', ascending=False).drop_duplicates('partido')
    return z.assign(gan=np.where(z.ok == 1, z.cuota - 1, -1.0))


def boletos(z, n, corte):
    z = z.assign(dia=z.fecha.dt.strftime('%Y-%m-%d'))
    out = {'A': [], 'B': []}
    for dia, g in z.groupby('dia'):
        g = g.sort_values('score', ascending=False).head(n)
        if len(g) < n:
            continue
        out['A' if g.fecha.iloc[0] < corte else 'B'].append((int(g.ok.sum()), float(np.prod(g.cuota))))
    r = {}
    for t, L in out.items():
        if not L:
            continue
        bien = np.array([b for b, _ in L])
        r[t] = {'dias': len(L), 'enteros': int((bien == n).sum()),
                'pct': round(float((bien == n).mean()), 3),
                'tres_rojas': int((bien <= n - 3).sum()) if n >= 3 else 0,
                'momio': round(float(np.mean([m for _, m in L])), 2),
                'gan_100': round(100 * float(np.mean([(m - 1) if b == n else -1 for b, m in L])), 1)}
    return r


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    x = V.playdoit()
    corte = x.fecha.quantile(0.5)
    R = {}
    for cmin in (1.25, 1.30, 1.35):
        base = elegir(x, 'casa', cmin)
        for regla in ('casa', 'casa_veto3', 'casa_y_metodo', 'consenso'):
            z = elegir(x, regla, cmin)
            f = {'todo': V.resumen(z), 'promete_casa': round(float(z.p_c.mean()), 4)}
            for t, m in (('A', z.fecha < corte), ('B', z.fecha >= corte)):
                q, b = z[m], base[(base.fecha < corte) if t == 'A' else (base.fecha >= corte)]
                f[t] = {'n': int(len(q)), 'acierto': round(float(q.ok.mean()), 4),
                        'cuota': round(float(q.cuota.mean()), 3)}
                if regla != 'casa':
                    d = V._boot(q, 'ok') - V._boot(b, 'ok')
                    f[t]['dif'] = round(float(q.ok.mean() - b.ok.mean()), 4)
                    f[t]['dif_p5'] = round(float(np.percentile(d, 5)), 4)
            f['boletos'] = {n: boletos(z, n, corte) for n in (2, 3, 4, 5)}
            f['por_mercado'] = {m: [int(len(g)), round(float(g.ok.mean()), 3), round(float(g.cuota.mean()), 3)]
                                for m, g in z.groupby('mercado') if len(g) >= 15}
            f['por_lado'] = {m: [int(len(g)), round(float(g.ok.mean()), 3)] for m, g in z.groupby('lado_ap')}
            R['%.2f %s' % (cmin, regla)] = f
    json.dump(R, open('_v371c_refinar.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1, default=str)
    for k, f in R.items():
        print('%-20s %s | A %s | B %s' % (k, {a: f['todo'][a] for a in ('n', 'acierto', 'cuota', 'gan_100')},
                                           f['A'], f['B']))
        print('    boletos', {n: {t: (v['enteros'], v['dias'], v['tres_rojas'], v['momio']) for t, v in b.items()}
                              for n, b in f['boletos'].items()})
        print('    mercado', f['por_mercado'], f['por_lado'])


if __name__ == '__main__':
    main()
