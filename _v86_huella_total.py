#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v86 — Huella de memoria de la app COMPLETA, para dimensionar max_entries.

Las ligas no son lo único que vive en @st.cache_resource: también el motor del
Mundial, el de MLB, el de NBA y los dos de tenis. Para elegir cuántas ligas
caben hay que restar primero todo lo demás.
"""
import gc
import os
import sys

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

import psutil


def rss():
    return psutil.Process(os.getpid()).memory_info().rss / 1024 / 1024


def paso(nombre, fn, ref):
    try:
        fn()
    except Exception as ex:
        print(f'  {nombre:32s} ERROR {type(ex).__name__}: {str(ex)[:60]}')
        return ref
    gc.collect()
    r = rss()
    print(f'  {nombre:32s} RSS {r:7.1f} MB  (+{r - ref:6.1f})')
    return r


def main():
    print('=' * 78)
    print('v86 · HUELLA TOTAL DE LOS OBJETOS CACHEADOS')
    print('=' * 78)
    print()

    guardado = {}
    r = rss()
    print(f'  {"python vacío":32s} RSS {r:7.1f} MB')

    def _stream():
        import streamlit  # noqa: F401
    r = paso('streamlit importado', _stream, r)
    base_streamlit = r

    def _mundial():
        from prediction_api import PredictionEngine
        guardado['mundial'] = PredictionEngine()
    r = paso('motor Mundial (PredictionEngine)', _mundial, r)

    def _mlb():
        from engines.mlb_engine import MLBEngine
        guardado['mlb'] = MLBEngine().cargar_modelo()
    r = paso('motor MLB', _mlb, r)

    def _nba():
        from engines.nba_engine import NBAEngine
        guardado['nba'] = NBAEngine().cargar_modelo()
    r = paso('motor NBA', _nba, r)

    def _tenis():
        from engines.tennis_engine import TennisEngine
        guardado['atp'] = TennisEngine('atp').cargar_modelo()
        guardado['wta'] = TennisEngine('wta').cargar_modelo()
    r = paso('motores de tenis (ATP + WTA)', _tenis, r)

    fijo = r
    print(f'\n  --> COSTE FIJO (todo menos las ligas): {fijo:.1f} MB')

    import config
    import league_engine
    claves = [c for c, cfg in config.LEAGUES.items()
              if cfg.get('disponible', True)]

    print('\n  cargando motores de liga encima de eso:')
    ligas = {}
    prev = fijo
    deltas = []
    for i, c in enumerate(claves[:8], 1):
        try:
            ligas[c] = league_engine.ClubEngine(c)
        except Exception:
            continue
        gc.collect()
        n = rss()
        deltas.append(n - prev)
        print(f'  {i:2d}. {c:28s} RSS {n:7.1f} MB  (+{n - prev:6.1f})')
        prev = n

    import statistics
    coste = statistics.mean(deltas) if deltas else 0
    print(f'\n  coste medio por liga: {coste:.1f} MB')

    print('\n' + '=' * 78)
    print('CUÁNTAS LIGAS CABEN, POR LÍMITE DE CONTENEDOR')
    print('=' * 78)
    print(f'{"límite":>10} {"margen tras el coste fijo":>28} {"ligas":>8}')
    for limite in (1024, 2048, 2700):
        margen = limite * 0.85 - fijo         # 15 % de reserva
        n = int(margen / coste) if coste > 0 else 0
        print(f'{limite:>8} MB {margen:>25.0f} MB {n:>8}')

    print('\nNOTA: la reserva del 15 % cubre los DataFrames de cuotas, el '
          'barrido de alpha_finder y los buffers por sesión.')


if __name__ == '__main__':
    main()
