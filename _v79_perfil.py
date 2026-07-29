#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v79 — Perfilado real del barrido de fútbol.

La paralelización por hilos apenas movió la aguja (197,9 s → 188,0 s) y
`_barrido_fixtures` incluso EMPEORÓ al competir con las otras ramas
(112 s → 171,7 s). Eso descarta la hipótesis de «está esperando a la red»: si
el tiempo fuera espera, los hilos habrían solapado. Que empeore al paralelizar
significa contención de CPU bajo el GIL.

Así que se perfila de verdad, en vez de seguir adivinando.
"""
import cProfile
import io
import logging
import pstats

logging.basicConfig(level=logging.WARNING)


def main():
    import alpha_finder
    pr = cProfile.Profile()
    pr.enable()
    alpha_finder.apuestas_del_dia(max_partidos=40)
    pr.disable()

    s = io.StringIO()
    ps = pstats.Stats(pr, stream=s).sort_stats('cumulative')
    ps.print_stats(45)
    texto = s.getvalue()
    with open('_v79_perfil.txt', 'w', encoding='utf-8') as f:
        f.write(texto)
    # se imprime solo la parte útil
    for linea in texto.splitlines():
        print(linea)

    s2 = io.StringIO()
    pstats.Stats(pr, stream=s2).sort_stats('tottime').print_stats(25)
    print('\n\n===== POR TIEMPO PROPIO (tottime) =====')
    print(s2.getvalue())
    with open('_v79_perfil.txt', 'a', encoding='utf-8') as f:
        f.write('\n\n===== tottime =====\n')
        f.write(s2.getvalue())


if __name__ == '__main__':
    main()
