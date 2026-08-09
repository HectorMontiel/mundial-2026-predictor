#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v114 — ¿Cuánto aporta Matchbook al tablón, ya neto de comisión y con las
guardias de liquidez puestas?

La medición previa (`_v114_medir_exchanges.py`) se hizo con el precio BRUTO y
sin filtrar libros vacíos, así que exageraba: daba margen 1,0337 y +1,80 % de
mejora media. Aquí se mide lo que el usuario cobraría de verdad.
"""
import statistics, sys
for _f in (sys.stdout, sys.stderr):
    try: _f.reconfigure(encoding='utf-8', errors='replace')
    except Exception: pass
import logging; logging.disable(logging.INFO)
import cuotas_multi as cm

cm.precargar('futbol')
pin = cm._indice('futbol')
mejor_con, mejor_sin, mejoras = [], [], []
gana = {}
n = 0
for v in pin.values():
    r = cm.cuotas_partido('futbol', v['home'], v['away'],
                          fecha=v.get('fecha'), liga=v.get('liga'))
    casas = {k: c for k, c in (r.get('casas') or {}).items()
             if not k.startswith('_')}
    if 'Matchbook' not in casas or len(casas) < 3:
        continue
    n += 1
    sin_mb = {k: c for k, c in casas.items() if k != 'Matchbook'}
    m_con = m_sin = 0.0
    for lado in ('home', 'draw', 'away'):
        ps = {k: c[lado] for k, c in casas.items() if c.get(lado)}
        qs = {k: c[lado] for k, c in sin_mb.items() if c.get(lado)}
        if not ps or not qs:
            continue
        top = max(ps.values())
        for k, p in ps.items():
            if p == top:
                gana[k] = gana.get(k, 0) + 1
        m_con += 1 / top
        m_sin += 1 / max(qs.values())
        if 'Matchbook' in ps:
            mejoras.append(ps['Matchbook'] / max(qs.values()) - 1)
    if m_con and m_sin:
        mejor_con.append(m_con); mejor_sin.append(m_sin)

print(f'partidos con Matchbook y ≥2 casas más: {n}')
print('\nquién da el mejor precio (selecciones):')
tot = sum(gana.values()) or 1
for k, c in sorted(gana.items(), key=lambda x: -x[1]):
    print(f'  {k:<12} {c:>5}  ({c/tot*100:.1f} %)')
if mejor_con:
    print(f'\nmargen del MEJOR precio SIN Matchbook: {statistics.mean(mejor_sin):.4f}')
    print(f'margen del MEJOR precio CON Matchbook: {statistics.mean(mejor_con):.4f}')
    print(f'  → mejora del margen: '
          f'{(statistics.mean(mejor_sin)-statistics.mean(mejor_con))*100:.2f} puntos')
if mejoras:
    pos = sum(1 for x in mejoras if x > 0)
    print(f'\nMatchbook mejora al mejor de las casas en {pos}/{len(mejoras)} '
          f'selecciones ({pos/len(mejoras)*100:.1f} %)')
    print(f'  mejora media (incluyendo cuando pierde): '
          f'{statistics.mean(mejoras)*100:+.2f} %')
    ganadoras = [x for x in mejoras if x > 0]
    if ganadoras:
        print(f'  cuando gana, mejora {statistics.mean(ganadoras)*100:+.2f} % '
              f'de media')
print(f'\n(cuotas ya netas del {cm.COMISION_EXCHANGE*100:.0f} % de comisión, '
      f'y sólo precios con ≥{cm.IMPORTE_MINIMO_EXCHANGE:.0f} disponibles)')
