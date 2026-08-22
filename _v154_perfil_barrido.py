#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v154 — DÓNDE SE VA EL TIEMPO DE «APUESTAS DEL DÍA», POR RAMAS.

Se cronometra cada rama del barrido POR SEPARADO y en su propio proceso-tiempo,
no acumulando por función. Es la lección que este proyecto ya pagó tres veces:
sumar tiempos de hebras concurrentes no da tiempo de reloj, y tres diagnósticos
de velocidad seguidos salieron falsos por eso.

Las seis ramas corren EN PARALELO en producción, así que el total no es la suma:
es el máximo. Lo que este perfil busca es cuál es ese máximo, porque optimizar
cualquier otra no cambia nada de lo que ve el usuario.
"""
import logging
import time
import warnings

warnings.filterwarnings('ignore')
logging.basicConfig(level=logging.ERROR)

import alpha_finder as af


def crono(nombre, fn):
    t = time.time()
    try:
        r = fn()
        d = time.time() - t
        n = 0
        if isinstance(r, dict):
            n = len(r.get('pronosticos') or r.get('capa1') or [])
        print('%-10s %7.1f s   (%d filas)' % (nombre, d, n), flush=True)
        return d
    except Exception as e:
        print('%-10s   FALLO  %s: %s' % (nombre, type(e).__name__, e),
              flush=True)
        return 0.0


def main():
    print('rama         tiempo    filas')
    print('-' * 34)
    tiempos = {
        'futbol': crono('futbol', lambda: af.apuestas_del_dia()),
        'mlb': crono('mlb', af._picks_mlb),
        'tenis': crono('tenis', af._picks_tenis),
        'nba': crono('nba', af._picks_nba),
        'kbo': crono('kbo', af._picks_kbo),
        'nfl': crono('nfl', af._picks_nfl),
    }
    print('-' * 34)
    peor = max(tiempos, key=tiempos.get)
    print('suma (NO es el reloj):   %6.1f s' % sum(tiempos.values()))
    print('techo real (la peor):    %6.1f s  -> %s'
          % (tiempos[peor], peor))
    print()
    print('Optimizar cualquier rama que no sea «%s» no cambia lo que ve el '
          'usuario.' % peor)


if __name__ == '__main__':
    main()
