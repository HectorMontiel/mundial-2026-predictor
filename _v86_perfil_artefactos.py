#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v86 — ¿Qué artefacto concreto se come los 329 MB al instanciar el motor?

El perfil por atributos dio 2,7 MB de datos vivos frente a 329 MB de RSS. Esa
diferencia es memoria que el asignador pidió al sistema y no ha devuelto. Hay
que saber si es un pico transitorio (y entonces se devuelve con malloc_trim en
Linux) o si hay estructuras grandes invisibles a sys.getsizeof (los modelos de
XGBoost viven en C++ y Python los ve como objetos diminutos).
"""
import gc
import os
import sys
import tracemalloc

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

import psutil

DIR = 'modelos'


def rss():
    return psutil.Process(os.getpid()).memory_info().rss / 1024 / 1024


def main():
    print('=' * 78)
    print('v86 · COSTE DE CADA ARTEFACTO DEL MOTOR DEL MUNDIAL')
    print('=' * 78)

    import joblib
    import json

    print('\ntamaño en disco de los artefactos:')
    for f in sorted(os.listdir(DIR)):
        p = os.path.join(DIR, f)
        if os.path.isfile(p):
            print(f'  {f:34s} {os.path.getsize(p) / 1024 / 1024:8.2f} MB')

    gc.collect()
    tracemalloc.start()
    base_rss = rss()
    base_py = tracemalloc.get_traced_memory()[0] / 1024 / 1024
    print(f'\npartida: RSS {base_rss:.1f} MB · python vivo {base_py:.1f} MB\n')

    guardado = {}
    for nombre, ruta in (('modelo_tda', 'modelo_tda.joblib'),
                         ('escalador', 'escalador.joblib'),
                         ('reg_goles_local', 'reg_goles_local.joblib'),
                         ('reg_goles_visit', 'reg_goles_visit.joblib')):
        p = os.path.join(DIR, ruta)
        if not os.path.exists(p):
            print(f'  {nombre:20s} (no existe)')
            continue
        antes_rss, antes_py = rss(), tracemalloc.get_traced_memory()[0] / 1024 / 1024
        guardado[nombre] = joblib.load(p)
        gc.collect()
        d_rss = rss() - antes_rss
        d_py = tracemalloc.get_traced_memory()[0] / 1024 / 1024 - antes_py
        print(f'  {nombre:20s} RSS +{d_rss:7.1f} MB   python vivo +{d_py:6.1f} MB')

    ruta_stats = 'team_stats.json'
    if os.path.exists(ruta_stats):
        antes_rss, antes_py = rss(), tracemalloc.get_traced_memory()[0] / 1024 / 1024
        with open(ruta_stats, encoding='utf-8') as f:
            guardado['stats'] = json.load(f)
        gc.collect()
        print(f'  {"team_stats.json":20s} RSS '
              f'+{rss() - antes_rss:7.1f} MB   python vivo '
              f'+{tracemalloc.get_traced_memory()[0] / 1024 / 1024 - antes_py:6.1f} MB')

    pico_py = tracemalloc.get_traced_memory()[1] / 1024 / 1024
    vivo_py = tracemalloc.get_traced_memory()[0] / 1024 / 1024
    total_rss = rss()
    tracemalloc.stop()

    print('\n' + '-' * 78)
    print(f'RSS total ahora           : {total_rss:7.1f} MB '
          f'(+{total_rss - base_rss:.1f} desde la partida)')
    print(f'python: objetos VIVOS     : {vivo_py:7.1f} MB')
    print(f'python: PICO de asignación: {pico_py:7.1f} MB')

    huerfano = (total_rss - base_rss) - vivo_py
    print(f'\ndiferencia RSS - vivos    : {huerfano:7.1f} MB')
    print('  Si esta diferencia es grande, NO son datos que el motor necesite:')
    print('  es memoria liberada por Python que el asignador se ha quedado')
    print('  (arenas fragmentadas). En Linux se devuelve con malloc_trim(0);')
    print('  Streamlit Cloud es Linux.')

    tiene_trim = hasattr(__import__('ctypes'), 'CDLL')
    print(f'\nplataforma actual: {sys.platform} '
          f'(malloc_trim sólo aplica en linux; aquí no se puede comprobar)')
    print(f'ctypes disponible: {tiene_trim}')


if __name__ == '__main__':
    main()
