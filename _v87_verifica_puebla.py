#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v87 — El caso Puebla-Chivas, contra el árbitro que manda: el mercado.

Pinnacle (devigado) da Puebla 19,6 % · empate 22,2 % · Chivas 58,2 %.
La ficha decía Puebla 50,0 %.

Esto comprueba, sobre el camino REAL de producción, que la ficha ya se ancla al
mercado y cuánto se acerca al precio sharp.
"""
import sys

import numpy as np

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass


def main():
    import cuotas_multi as cm
    import league_engine as le

    print('=' * 80)
    print('v87 · PUEBLA vs CHIVAS EN EL CAMINO REAL DE PRODUCCIÓN')
    print('=' * 80)

    e = le.ClubEngine('liga_mx')
    if not e.listo:
        print('  motor de liga_mx no disponible en esta plataforma')
        return
    p = [t for t in e.stats if 'puebla' in t.lower()][0]
    c = [t for t in e.stats if 'chiva' in t.lower()
         or 'guadalajara' in t.lower()][0]
    print(f'\n  {p} (ELO {e.stats[p]["ELO"]:.0f}) vs '
          f'{c} (ELO {e.stats[c]["ELO"]:.0f})')

    # referencia del mercado
    res = cm.cuotas_partido('futbol', p, c)
    pin = {k: v for k, v in (res.get('pinnacle') or {}).items() if v and v > 1}
    ref = cm.devig(pin, metodo='potencia') if len(pin) >= 3 else {}
    if ref:
        print(f'\n  PINNACLE (devigado, el árbitro): '
              f'{p} {ref["home"]:.1%} · empate {ref["draw"]:.1%} · '
              f'{c} {ref["away"]:.1%}')

    filas = []
    for etq, kw in (('ficha ANTES (sin anclar)', {'anclar': False}),
                    ('ficha AHORA (v87)', {'anclar': True})):
        r = e.predecir(p, c, **kw)
        pr = r['prediction']['probabilities']
        mod = r.get('model', {})
        filas.append((etq, pr, mod))
        print(f'\n  {etq}:')
        print(f'    {p} {pr["home"]:.1%} · empate {pr["draw"]:.1%} · '
              f'{c} {pr["away"]:.1%}')
        print(f'    ganador mostrado: {r["prediction"]["winner"]} '
              f'({r["prediction"]["confidence"]:.1%})')
        print(f'    ancla de mercado: {mod.get("ancla_mercado_aplicada")}'
              + (f' (w={mod.get("ancla_mercado_w")})'
                 if mod.get('ancla_mercado_aplicada') else '')
              + f' · prior de ELO: {mod.get("prior_elo_aplicado")}')

    if ref and len(filas) == 2:
        print('\n' + '-' * 80)
        print('DISTANCIA AL PRECIO SHARP')
        print('-' * 80)
        v = np.array([ref['home'], ref['draw'], ref['away']])
        for etq, pr, _ in filas:
            q = np.array([pr['home'], pr['draw'], pr['away']])
            l1 = float(np.abs(q - v).sum())
            print(f'  {etq:28s} error absoluto total {l1:.3f}  '
                  f'(local {abs(q[0] - v[0]):.3f})')
        q0 = np.array([filas[0][1][k] for k in ('home', 'draw', 'away')])
        q1 = np.array([filas[1][1][k] for k in ('home', 'draw', 'away')])
        print(f'\n  la ficha pasa de errar {np.abs(q0 - v).sum():.3f} a '
              f'{np.abs(q1 - v).sum():.3f} respecto a Pinnacle')

    # coherencia local/visitante
    print('\n' + '-' * 80)
    print('COHERENCIA (el fuerte en su propio campo debe ir por delante)')
    print('-' * 80)
    for etq, kw in (('sin anclar', {'anclar': False}),
                    ('v87', {'anclar': True})):
        a = e.predecir(p, c, **kw)['prediction']['probabilities']['home']
        b = e.predecir(c, p, **kw)['prediction']['probabilities']['home']
        print(f'  {etq:12s} {p} en casa {a:.1%} · {c} en casa {b:.1%} -> '
              f'{"COHERENTE" if b > a else "INCOHERENTE"}')


if __name__ == '__main__':
    main()
