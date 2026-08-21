#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v149 — cProfile DENTRO de `cuotas_partido`.

El perfil por actividad dijo que el emparejador de cuotas se lleva el 70 % del
barrido, y memorizar las funciones puras sólo bajó un 6 % de esa parte. O sea
que el coste está en otro sitio del que yo suponía. Esto lo localiza en vez de
seguir probando.

Se profila sobre partidos REALES del día, con los índices ya cargados, para no
medir la descarga.
"""
import cProfile
import io as _io
import logging
import pstats
import time
import warnings

warnings.filterwarnings('ignore')
logging.basicConfig(level=logging.ERROR)

N_PARTIDOS = 25


def main():
    import cuotas_multi as cm
    import fixtures_espn
    from config import LEAGUES

    claves = [c for c, cfg in LEAGUES.items()
              if cfg.get('disponible') and c in fixtures_espn.ESPN_CODIGOS]
    fx = fixtures_espn.fixtures_multi(claves, dias=3)
    partidos = []
    for c in claves:
        for f in (fx.get(c) or []):
            if f.get('home') and f.get('away'):
                partidos.append(f)
    partidos = partidos[:N_PARTIDOS]
    print(f'partidos a medir: {len(partidos)}')

    # calentar los índices: lo que se quiere medir es el EMPAREJADO, no la
    # descarga del tablón, que ocurre una vez y ya está cacheada.
    t = time.perf_counter()
    for dep in ('futbol',):
        for fn in (cm._indice, cm._indice_bov, cm._indice_uni,
                   cm._indice_mb, cm._indice_pdt):
            try:
                idx = fn(dep)
                print(f'   {fn.__name__:<14} {len(idx or {}):5d} eventos')
            except Exception as e:
                print(f'   {fn.__name__:<14} falló: {type(e).__name__}')
    print(f'índices cargados en {time.perf_counter() - t:.1f} s\n')

    def _tanda():
        for f in partidos:
            try:
                cm.valor_vs_sharp('futbol', f['home'], f['away'], odds_espn=f)
            except Exception:
                pass

    t = time.perf_counter()
    _tanda()
    print(f'tanda SIN profiler: {time.perf_counter() - t:.1f} s '
          f'({(time.perf_counter() - t) / max(len(partidos), 1):.2f} s/partido)\n')

    pr = cProfile.Profile()
    pr.enable()
    _tanda()
    pr.disable()
    buf = _io.StringIO()
    pstats.Stats(pr, stream=buf).sort_stats('cumulative').print_stats(28)
    texto = buf.getvalue()
    # sólo las líneas de la tabla, que es lo que interesa
    for linea in texto.splitlines():
        if linea.strip():
            print(linea)


if __name__ == '__main__':
    main()
