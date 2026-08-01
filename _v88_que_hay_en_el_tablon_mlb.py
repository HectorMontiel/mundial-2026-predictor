#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v88 — ¿Qué hay REALMENTE en el tablón de cuotas «mlb»?

Los dos únicos picks de MLB que llegaron a la Capa 1 hoy fueron:

    Rakuten Monkeys @ Uni-President 7-Eleven Lions
    Rakuten Monkeys @ Uni-President Lions

Eso es la **CPBL de Taiwán**, no la MLB. Y es el MISMO partido dos veces,
porque el nombre del rival cambia entre casas y la clave de deduplicación
—`codigo_mlb(nombre)`— devuelve el nombre crudo cuando el fuzzy no llega a
0,6, así que «Uni-President Lions» y «Uni-President 7-Eleven Lions» cuentan
como equipos distintos.

O sea que la vía de valor de mercado de MLB estaba operando ligas que nunca se
validaron. El edge de `valor_vs_sharp` en béisbol se midió sobre **27.977
juegos de MLB** con apertura y cierre; aplicarlo a la CPBL es extrapolar.

Esto inventaría qué contiene el tablón antes de decidir el filtro.
"""
import sys
from collections import Counter

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass


def main():
    import cuotas_multi as cm
    from engines.mlb_engine import NOMBRES_MLB, codigo_mlb

    validos = set(NOMBRES_MLB.values())
    print('=' * 78)
    print('v88 · CONTENIDO DEL TABLÓN «mlb»')
    print('=' * 78)
    print(f'  equipos MLB reconocidos: {len(NOMBRES_MLB)} nombres -> '
          f'{len(validos)} códigos')

    total, mlb_puro, otros = 0, [], []
    vistos = set()
    for fuente, idx in (('Pinnacle', cm._indice('mlb')),
                        ('Bovada', cm._indice_bov('mlb')),
                        ('Playdoit', cm._indice_pdt('mlb'))):
        n = len(idx or {})
        print(f'\n  {fuente}: {n} partidos')
        for v in (idx or {}).values():
            h, a = v.get('home'), v.get('away')
            if not (h and a):
                continue
            total += 1
            ch, ca = codigo_mlb(h), codigo_mlb(a)
            es_mlb = ch in validos and ca in validos
            clave = tuple(sorted((ch, ca)))
            if es_mlb:
                if clave not in vistos:
                    mlb_puro.append((h, a))
                    vistos.add(clave)
            else:
                otros.append((h, a, ch, ca))

    print('\n' + '-' * 78)
    print(f'  entradas totales en los tres tablones : {total}')
    print(f'  partidos de MLB de verdad (sin repetir): {len(mlb_puro)}')
    print(f'  entradas que NO son MLB               : {len(otros)}')

    print('\n  MLB de verdad:')
    for h, a in mlb_puro[:20]:
        print(f'    · {a} @ {h}')

    print('\n  lo que NO es MLB (equipo -> a qué se parecía):')
    cuenta = Counter()
    for h, a, ch, ca in otros:
        cuenta[h] += 1
        cuenta[a] += 1
    for nombre, n in cuenta.most_common(20):
        c = codigo_mlb(nombre)
        marca = '' if c in validos else '  <- no resuelve a código MLB'
        print(f'    {nombre:38s} x{n:<3d} -> {c}{marca}')

    # el caso concreto que se coló
    print('\n  el caso que llegó a la Capa 1:')
    for nombre in ('Rakuten Monkeys', 'Uni-President 7-Eleven Lions',
                   'Uni-President Lions'):
        c = codigo_mlb(nombre)
        print(f'    codigo_mlb({nombre!r}) = {c!r} '
              f'{"(código MLB válido)" if c in validos else "(NO es código MLB)"}')
    print('\n  -> por eso el mismo partido entró dos veces: dos nombres')
    print('     distintos que no resuelven a ningún código dan dos claves.')


if __name__ == '__main__':
    main()
