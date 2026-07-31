#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v86 — ¿Cuánta RAM consume la app conforme se usan más ligas?

Streamlit Community Cloud limita el contenedor (~1 GB en el plan gratuito).
`cargar_motor_liga` está decorado con @st.cache_resource y se cachea POR LIGA:
cada liga distinta que alguien abra deja un ClubEngine residente para siempre.
Con un usuario eso crece despacio; con dos usuarios navegando ligas distintas
crece al doble de velocidad. Si se cruza el límite, el contenedor muere y a
todos se les cae la app a la vez — exactamente el síntoma reportado.

Esto lo mide en vez de suponerlo.
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
    print('v86 · HUELLA DE MEMORIA POR MOTOR DE LIGA')
    print('=' * 78)

    base = rss_mb()
    print(f'\npython vacío                       : {base:7.1f} MB')

    import config
    import league_engine
    tras_import = rss_mb()
    print(f'tras importar league_engine+config : {tras_import:7.1f} MB '
          f'(+{tras_import - base:.1f})')

    claves = [c for c, cfg in config.LEAGUES.items() if cfg.get('disponible', True)]
    print(f'ligas disponibles                  : {len(claves)}')

    motores = {}
    medidas = []
    muestra = claves[:12]
    print(f'\nCargando {len(muestra)} motores (como si los usuarios los abrieran):')
    prev = tras_import
    for i, c in enumerate(muestra, 1):
        try:
            motores[c] = league_engine.ClubEngine(c)
        except Exception as ex:
            print(f'  {i:2d}. {c:20s} ERROR {type(ex).__name__}')
            continue
        gc.collect()
        ahora = rss_mb()
        delta = ahora - prev
        medidas.append(delta)
        print(f'  {i:2d}. {c:20s} RSS {ahora:7.1f} MB  (+{delta:6.1f})')
        prev = ahora

    if not medidas:
        print('sin medidas')
        return

    import statistics
    media = statistics.mean(medidas)
    total = prev - base
    print('\n' + '-' * 78)
    print(f'coste medio por motor de liga : {media:6.1f} MB')
    print(f'RSS con {len(medidas)} ligas cargadas   : {prev:6.1f} MB')
    print(f'proyección a las {len(claves)} ligas   : '
          f'{tras_import + media * len(claves):6.1f} MB')

    for limite in (1024, 2048):
        cabe = int((limite - tras_import) / media) if media > 0 else 999
        print(f'ligas que caben en {limite} MB      : ~{cabe}')

    print('\nNOTA: a esto hay que sumarle los motores de MLB, NBA y tenis, los '
          'DataFrames de cuotas y el propio Streamlit.')


if __name__ == '__main__':
    main()
