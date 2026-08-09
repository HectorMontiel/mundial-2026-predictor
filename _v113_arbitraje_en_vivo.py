"""
¿Cuántas oportunidades de arbitraje salen con NUESTRAS cinco casas?

El histórico dice que con las 18 casas de football-data el 40 % de los partidos
deja el margen por debajo de 1. Pero nosotros tomamos cinco (Pinnacle, Bovada,
Playdoit, Unibet y DraftKings vía ESPN). Esto lo mide en vivo, sobre el tablón
de hoy, que es lo único honesto.
"""
import logging

logging.basicConfig(level=logging.WARNING)

import cuotas_multi as cm

print('=== tablón de hoy, con las cinco casas ===')
idx = cm._indice('futbol')
print(f'{len(idx)} partidos en el índice de Pinnacle\n')

n = arbs = casi = 0
detalle = []
for k, v in list(idx.items())[:120]:
    c = cm.cuotas_partido('futbol', v['home'], v['away'])
    casas = c.get('casas') or {}
    if len(casas) < 2:
        continue
    n += 1
    # el mejor precio de CADA lado, y de qué casa
    mejor = {}
    for lado in ('home', 'draw', 'away'):
        cands = [(float(p[lado]), nom) for nom, p in casas.items()
                 if p.get(lado) and float(p[lado]) > 1]
        if cands:
            mejor[lado] = max(cands)
    if len(mejor) < 2:
        continue
    # margen con el mejor precio de cada lado
    margen = sum(1.0 / x[0] for x in mejor.values())
    if margen < 1.0:
        arbs += 1
        detalle.append((margen, v['home'], v['away'], mejor, len(casas)))
    elif margen < 1.02:
        casi += 1

print(f'partidos evaluados con 2+ casas: {n}')
print(f'  ARBITRAJE (margen < 1,00):     {arbs}  ({arbs/max(n,1):.1%})')
print(f'  casi (margen < 1,02):          {casi}  ({casi/max(n,1):.1%})')

if detalle:
    print('\n=== oportunidades encontradas ===')
    for m, h, a, mej, nc in sorted(detalle)[:8]:
        ben = (1 / m - 1) * 100
        print(f'\n  {h} vs {a}   ({nc} casas)')
        print(f'    margen {m:.4f}  ->  beneficio garantizado {ben:+.2f} %')
        for lado, (cuota, casa) in mej.items():
            reparto = (1 / cuota) / m * 100
            print(f'      {lado:5s} @ {cuota:6.2f} en {casa:10s} '
                  f'(apostar el {reparto:.1f} % del total)')
else:
    print('\n  Ninguna ahora mismo. Con cinco casas es lo esperable:')
    print('  el 40 % del histórico sale con DIECIOCHO.')

# ¿cuánto margen queda de media con nuestras casas?
import statistics
margenes = []
for k, v in list(idx.items())[:120]:
    c = cm.cuotas_partido('futbol', v['home'], v['away'])
    casas = c.get('casas') or {}
    if len(casas) < 2:
        continue
    mejor = {}
    for lado in ('home', 'draw', 'away'):
        cands = [float(p[lado]) for nom, p in casas.items()
                 if p.get(lado) and float(p[lado]) > 1]
        if cands:
            mejor[lado] = max(cands)
    if len(mejor) == 3:
        margenes.append(sum(1 / x for x in mejor.values()))

if margenes:
    print(f'\n=== margen con el mejor precio de nuestras casas ===')
    print(f'  n={len(margenes)}  media {statistics.mean(margenes):.4f} · '
          f'mediana {statistics.median(margenes):.4f} · '
          f'mínimo {min(margenes):.4f}')
    print(f'  (histórico: 1,0550 al precio medio · 1,0034 con las 18 casas)')
