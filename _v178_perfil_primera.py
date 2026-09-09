#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Donde se van los ~4 minutos de la PRIMERA carga de Apuestas del Dia.

Es la queja literal del usuario: «cuando dejo de usar la app y quiero volver a
usarla tarda muchisimo en cargar todo». El barrido ya esta cacheado en disco,
asi que lo que se mide aqui es lo que cuesta PINTAR la pantalla la primera vez.
"""
import cProfile
import io
import os
import pstats
import sys
import tempfile
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8',
                              errors='replace')
os.environ['PREFERENCIAS_USUARIO'] = os.path.join(
    tempfile.mkdtemp(prefix='prefs_perf1_'), 'preferencias_usuario.json')

import guardia_barrido
# El guardia revalida en un HILO cuando el barrido pasa de 5 min, y esa
# revalidacion (simulaciones de tenis) compite por la CPU y falsea la
# medida: una pasada salio en 377 s con `_revalidar` corriendo detras.
guardia_barrido.FRESCURA_S = 10 ** 9

from streamlit.testing.v1 import AppTest

APP = 'dashboard_ui.py'


def main():
    at = AppTest.from_file(APP, default_timeout=1800).run()
    pr = cProfile.Profile()
    pr.enable()
    t0 = time.perf_counter()
    at.selectbox(key='competencia').select('\U0001f48e Apuestas del Día').run()
    t = time.perf_counter() - t0
    pr.disable()
    print('primera pasada de la pantalla: %.1f s' % t, flush=True)
    s = io.StringIO()
    pstats.Stats(pr, stream=s).sort_stats('cumulative').print_stats(60)
    for linea in s.getvalue().splitlines():
        if ('predictor-upstream' in linea or 'ncalls' in linea
                or 'function calls' in linea):
            print(linea, flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
