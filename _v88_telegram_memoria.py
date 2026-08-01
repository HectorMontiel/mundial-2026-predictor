#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v88 — ¿Cuánto costaba pulsar «Enviar a Telegram»?

El usuario reportó: «cuando envío los datos a telegram es cuando peta la app».

`bot_telegram.construir_mensaje()` llamaba a
`alpha_finder.apuestas_del_dia_universal()` por su cuenta, saltándose el guardia
de proceso de la v86. Como el dashboard ya tenía el barrido en memoria, pulsar
el botón lanzaba un SEGUNDO barrido completo dentro del mismo contenedor.

Esto lo mide en vez de suponerlo: se cuenta cuántas veces se ejecuta el barrido
en cada versión, y cuánta memoria pica.
"""
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
        time.sleep(0.03)


def main():
    import alpha_finder
    import bot_telegram
    import guardia_barrido

    llamadas = []
    original = alpha_finder.apuestas_del_dia_universal

    def barrido_falso():
        llamadas.append(time.time())
        # se reserva memoria a propósito para que el coste se vea: el barrido
        # real pica 1.297,7 MB, aquí basta con una fracción medible
        import numpy as np
        lastre = np.zeros((40, 1024, 1024), dtype=np.uint8)   # 40 MB
        time.sleep(0.8)
        del lastre
        return {'actualizado': '2026-07-31', 'capa1': [], 'capa2': [],
                'candidatos': [], 'pronosticos': [], 'combinadas': [],
                'deportes_cubiertos': ['Fútbol'], 'incidencias': [],
                'seleccion_dia': [], 'btts_destacado': [],
                'pick_del_dia': None, 'partidos_evaluados': 0,
                'cobertura_ligas': {}}

    alpha_finder.apuestas_del_dia_universal = barrido_falso
    h = threading.Thread(target=vigilante, daemon=True)
    h.start()
    try:
        print('=' * 76)
        print('v88 · COSTE DE PULSAR «ENVIAR A TELEGRAM»')
        print('=' * 76)

        # ---- lo que hacía la versión anterior -----------------------------
        # El `construir_mensaje` de v87 llamaba a
        # `alpha_finder.apuestas_del_dia_universal()` A PELO, sin pasar por el
        # guardia. Se reproduce esa llamada literal, porque el de este módulo
        # ya está arreglado y no serviría para comparar.
        guardia_barrido.reiniciar()
        llamadas.clear()
        pico[0] = rss()
        # el dashboard calcula el barrido...
        r = guardia_barrido.barrido(alpha_finder.apuestas_del_dia_universal)
        n_tras_barrido = len(llamadas)
        # ...y el botón, ANTES, rehacía el barrido entero
        _r_viejo = alpha_finder.apuestas_del_dia_universal()
        msg_viejo = bot_telegram.construir_mensaje(_r_viejo)
        n_viejo = len(llamadas)
        pico_viejo = pico[0]

        print(f'\n  ANTES (el botón rehacía el barrido):')
        print(f'    barridos tras pintar la página : {n_tras_barrido}')
        print(f'    barridos tras pulsar el botón  : {n_viejo}')
        print(f'    -> el botón provoca {n_viejo - n_tras_barrido} barrido(s) más')
        print(f'    RSS pico: {pico_viejo:.1f} MB')

        # ---- lo que hace ahora --------------------------------------------
        guardia_barrido.reiniciar()
        llamadas.clear()
        pico[0] = rss()
        r = guardia_barrido.barrido(alpha_finder.apuestas_del_dia_universal)
        n_tras_barrido2 = len(llamadas)
        msg_nuevo = bot_telegram.construir_mensaje(r)      # <- se le pasa
        n_nuevo = len(llamadas)
        pico_nuevo = pico[0]

        print(f'\n  AHORA (construir_mensaje(r)):')
        print(f'    barridos tras pintar la página : {n_tras_barrido2}')
        print(f'    barridos tras pulsar el botón  : {n_nuevo}')
        print(f'    -> el botón provoca {n_nuevo - n_tras_barrido2} barrido(s) más')
        print(f'    RSS pico: {pico_nuevo:.1f} MB')

        # ---- y el mensaje debe ser el mismo -------------------------------
        print(f'\n  ¿el mensaje sale igual? '
              f'{"SÍ" if msg_viejo == msg_nuevo else "NO"}')
        print(f'    ({len(msg_nuevo)} caracteres)')

        # ---- sin argumento, ¿pasa ahora por el guardia? --------------------
        guardia_barrido.reiniciar()
        llamadas.clear()
        bot_telegram.construir_mensaje()          # primera vez: calcula
        bot_telegram.construir_mensaje()          # segunda: debe reutilizar
        print(f'\n  sin argumento, dos llamadas seguidas provocan '
              f'{len(llamadas)} barrido(s)')
        print('    (antes eran 2: ahora pasa por el guardia y reutiliza)')

        ok = (n_viejo - n_tras_barrido == 1
              and n_nuevo - n_tras_barrido2 == 0
              and msg_viejo == msg_nuevo
              and len(llamadas) == 1)
        print('\n' + '=' * 76)
        print(f'VEREDICTO: {"ARREGLADO" if ok else "revisar"}')
        return 0 if ok else 1
    finally:
        vigilar.set()
        alpha_finder.apuestas_del_dia_universal = original


if __name__ == '__main__':
    sys.exit(main())
