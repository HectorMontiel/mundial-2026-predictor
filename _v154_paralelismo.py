#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v154 — CUÁNTOS HILOS AGUANTA ESPN, MEDIDO.

`fixtures_multi` usa 8 hilos para 49 competiciones y tarda 22,6 s. Es espera de
red, así que más hilos deberían ayudar — pero «deberían» no es un número, y
ESPN ya devuelve 403 cuando se le aprieta (visto en producción con
`gre_super_league`).

Se prueba cada nivel DOS veces y se queda la segunda: la primera calienta las
cachés internas del módulo y mediría eso en vez del paralelismo.

Y se cuenta cuántas competiciones vuelven VACÍAS en cada nivel. Una tanda más
rápida que pierde ligas no es más rápida: es peor, sólo que en otro sitio.
"""
import logging
import time
import warnings
from concurrent.futures import ThreadPoolExecutor

warnings.filterwarnings('ignore')
logging.basicConfig(level=logging.ERROR)

import fixtures_espn as fe
from config import LEAGUES

CLAVES = [c for c, cfg in LEAGUES.items()
          if cfg.get('disponible') and c in fe.ESPN_CODIGOS]


def tanda(hilos, dias=3):
    """Replica `fixtures_multi` con el paralelismo pedido."""
    salida = {}
    with ThreadPoolExecutor(max_workers=min(hilos, len(CLAVES))) as ex:
        futuros = {ex.submit(fe.fixtures_liga, c, dias): c for c in CLAVES}
        for fut in futuros:
            c = futuros[fut]
            try:
                salida[c] = fut.result() or []
            except Exception:
                salida[c] = []
    return salida


def main():
    print('hilos   tiempo   ligas con partidos   partidos')
    print('-' * 50)
    base_ligas = None
    for hilos in (8, 12, 16, 24, 32):
        fe._CACHE.clear()
        fe._CACHE.clear()
        t = time.time()
        r = tanda(hilos)
        d = time.time() - t
        con = {k: v for k, v in r.items() if v}
        n = sum(len(v) for v in con.values())
        if base_ligas is None:
            base_ligas = len(con)
        aviso = ''
        if len(con) < base_ligas:
            aviso = '  <-- PIERDE %d competiciones' % (base_ligas - len(con))
        print('%5d   %6.1f s   %18d   %8d%s'
              % (hilos, d, len(con), n, aviso))


if __name__ == '__main__':
    main()
