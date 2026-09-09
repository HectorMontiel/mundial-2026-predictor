#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Donde se van los segundos de la pantalla de Apuestas del Dia.

La queja del usuario es «tarda muchisimo en cargar». Medido en el navegador:
pulsar una pestaña y que la pantalla obedezca tardo **mas de 153 s**, con el
barrido YA cacheado en disco. O sea que el coste no es bajar datos: es pintar.

Este script cronometra una pasada entera con AppTest y saca las funciones que
mas tiempo acumulan, para poder decidir con numeros si el problema se arregla
mudando de plataforma (CPU mas rapida) o recortando lo que se pinta.
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
    tempfile.mkdtemp(prefix='prefs_perf_'), 'preferencias_usuario.json')

from streamlit.testing.v1 import AppTest

APP = 'dashboard_ui.py'


def main():
    at = AppTest.from_file(APP, default_timeout=1800).run()
    t0 = time.perf_counter()
    at.selectbox(key='competencia').select('\U0001f48e Apuestas del Día').run()
    t_primera = time.perf_counter() - t0
    print('primera pasada de la pantalla: %.1f s' % t_primera, flush=True)

    # La SEGUNDA pasada es la que sufre el usuario cada vez que toca un filtro:
    # el barrido ya esta en memoria y aun asi hay que repintarlo todo.
    pr = cProfile.Profile()
    pr.enable()
    t1 = time.perf_counter()
    at.segmented_control(key='_vista_principal').set_value('manana').run()
    t_rerun = time.perf_counter() - t1
    pr.disable()
    print('rerun al cambiar de vista: %.1f s' % t_rerun, flush=True)

    s = io.StringIO()
    pstats.Stats(pr, stream=s).sort_stats('cumulative').print_stats(45)
    texto = s.getvalue()
    # solo las lineas del proyecto y las cabeceras
    for linea in texto.splitlines():
        if ('predictor-upstream' in linea or 'ncalls' in linea
                or 'function calls' in linea):
            print(linea, flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
