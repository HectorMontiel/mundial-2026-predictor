#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v86 — El escenario que de verdad tumbaba la app al entrar el segundo usuario.

Hasta v85, cada sesión NUEVA ejecutaba `st.cache_data.clear()`. Ese caché no es
por sesión: es del proceso. Así que la secuencia era:

    usuario 1 entra  -> barrido de alpha_finder (caro) -> queda cacheado
    usuario 2 entra  -> BORRA el caché de todos
    usuario 1 pulsa  -> vuelve a lanzar el barrido entero
    usuario 2 pulsa  -> lanza OTRO barrido entero, a la vez

Dos barridos completos simultáneos en el mismo proceso. Esto mide cuánto cuesta
uno y cuánto cuestan dos a la vez, en tiempo y en memoria.
"""
import gc
import os
import sys
import threading
import time

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

import psutil

PROC = psutil.Process(os.getpid())
pico = [0.0]
vigilar = threading.Event()


def rss():
    return PROC.memory_info().rss / 1024 / 1024


def vigilante():
    while not vigilar.is_set():
        pico[0] = max(pico[0], rss())
        time.sleep(0.05)


def barrido(resultados, idx):
    t0 = time.time()
    try:
        import alpha_finder
        r = alpha_finder.apuestas_del_dia_universal()
        n = sum(len(v) for v in r.values()) if isinstance(r, dict) else len(r)
        resultados[idx] = (True, time.time() - t0, n)
    except Exception as ex:
        resultados[idx] = (False, time.time() - t0, f'{type(ex).__name__}: {ex}')


def main():
    print('=' * 78)
    print('v86 · COSTE DE UN BARRIDO DE alpha_finder, SOLO Y DUPLICADO')
    print('=' * 78)

    h = threading.Thread(target=vigilante, daemon=True)
    h.start()

    gc.collect()
    base = rss()
    pico[0] = base
    print(f'\nRSS de partida: {base:.1f} MB')

    print('\n--- 1 barrido (un solo usuario) ---')
    res = {}
    t0 = time.time()
    barrido(res, 0)
    solo_dt = time.time() - t0
    solo_pico = pico[0]
    gc.collect()
    solo_fin = rss()
    ok, dt, n = res[0]
    print(f'  resultado : {"OK" if ok else "FALLO"} ({n})')
    print(f'  tiempo    : {dt:.1f} s')
    print(f'  RSS pico  : {solo_pico:.1f} MB  (+{solo_pico - base:.1f})')
    print(f'  RSS final : {solo_fin:.1f} MB')

    print('\n--- 2 barridos SIMULTÁNEOS (el caso de dos usuarios) ---')
    print('    (con el caché borrado, como hacía la versión anterior)')
    gc.collect()
    antes2 = rss()
    pico[0] = antes2
    res2 = {}
    hilos = [threading.Thread(target=barrido, args=(res2, i)) for i in (0, 1)]
    t0 = time.time()
    for x in hilos:
        x.start()
    for x in hilos:
        x.join()
    dos_dt = time.time() - t0
    dos_pico = pico[0]
    vigilar.set()
    gc.collect()

    for i in (0, 1):
        ok, dt, n = res2[i]
        print(f'  hebra {i}: {"OK" if ok else "FALLO"} en {dt:.1f} s ({n})')
    print(f'  tiempo total: {dos_dt:.1f} s')
    print(f'  RSS pico    : {dos_pico:.1f} MB  (+{dos_pico - antes2:.1f})')

    print('\n' + '-' * 78)
    print(f'pico con 1 barrido : {solo_pico:7.1f} MB')
    print(f'pico con 2 barridos: {dos_pico:7.1f} MB  '
          f'(+{dos_pico - solo_pico:.1f} MB sobre el de uno)')
    print(f'tiempo 1 barrido   : {solo_dt:7.1f} s')
    print(f'tiempo 2 barridos  : {dos_dt:7.1f} s')
    print('\nCon el arreglo de v86 el caché ya NO se borra al entrar cada '
          'visitante, así que el segundo usuario reutiliza el barrido del '
          'primero en lugar de lanzar otro.')


if __name__ == '__main__':
    main()
