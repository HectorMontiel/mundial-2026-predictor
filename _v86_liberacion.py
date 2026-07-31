#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v86 — ¿Se libera la memoria al desalojar un motor de liga?

Poner `max_entries` en @st.cache_resource sólo sirve si al soltar la referencia
Python devuelve la RAM. Si ClubEngine se auto-registra en algún global del
módulo, o guarda un ciclo que el recolector no rompe, el desalojo no liberaría
nada y el arreglo sería cosmético.

Se carga N motores, se sueltan, se recolecta y se vuelve a medir.
"""
import gc
import os
import sys

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

import psutil


def rss_mb():
    return psutil.Process(os.getpid()).memory_info().rss / 1024 / 1024


def main():
    print('=' * 78)
    print('v86 · ¿SE LIBERA LA RAM AL DESALOJAR UN MOTOR?')
    print('=' * 78)

    import config
    import league_engine

    gc.collect()
    base = rss_mb()
    print(f'\nantes de cargar motores : {base:7.1f} MB')

    claves = [c for c, cfg in config.LEAGUES.items()
              if cfg.get('disponible', True)][:8]
    motores = {}
    for c in claves:
        try:
            motores[c] = league_engine.ClubEngine(c)
        except Exception:
            pass
    gc.collect()
    cargado = rss_mb()
    print(f'con {len(motores)} motores cargados  : {cargado:7.1f} MB '
          f'(+{cargado - base:.1f})')

    import weakref
    refs = [weakref.ref(m) for m in motores.values()]

    motores.clear()
    del motores
    for _ in range(3):
        gc.collect()
    liberado = rss_mb()

    vivos = sum(1 for r in refs if r() is not None)
    print(f'tras soltar y recolectar: {liberado:7.1f} MB '
          f'(-{cargado - liberado:.1f})')
    print(f'objetos ClubEngine que siguen vivos: {vivos} de {len(refs)}')

    recuperado = (cargado - liberado) / max(cargado - base, 1e-9) * 100
    print(f'\nporcentaje de RAM recuperada: {recuperado:.1f} %')

    if vivos:
        print('\nALGO LOS RETIENE. Buscando referencias...')
        for r in refs:
            o = r()
            if o is None:
                continue
            reps = gc.get_referrers(o)
            for rp in reps[:4]:
                print(f'  · {type(rp).__name__}: {str(rp)[:160]}')
            break

    veredicto = ('SÍ — limitar el caché con max_entries funcionará'
                 if vivos == 0 and recuperado > 50 else
                 'NO — hay algo reteniendo los motores, max_entries no bastaría')
    print(f'\nVEREDICTO: {veredicto}')


if __name__ == '__main__':
    main()
