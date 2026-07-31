#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v86 — Un solo barrido de alpha_finder a la vez en todo el proceso.

El problema medido
------------------
_v86_barrido_concurrente.py, sobre el barrido real:

    1 barrido  -> pico de 1297,7 MB  (95,8 s)
    2 barridos -> pico de 2172,2 MB

Streamlit Cloud es UN proceso con UNA hebra por sesión, así que dos barridos
simultáneos suman en el mismo contenedor. Ése es el "se cae cuando se conectan
dos personas".

Por qué no bastaba el caché de Streamlit
----------------------------------------
`@st.cache_data` YA evita que dos sesiones calculen la misma clave a la vez,
mediante un cerrojo por clave (`compute_value_lock`, en
streamlit/runtime/caching/cache_utils.py). Pero `cache_data.clear()` borra ese
diccionario de cerrojos:

    cache_utils.py:162   with self._value_locks_lock:
    cache_utils.py:164       self._value_locks.clear()

y hasta v85 el dashboard llamaba a `clear()` **en cada visitante nuevo** y
también en el botón "Actualizar ahora". O sea que la protección de Streamlit se
desactivaba justo en el momento en que hacía falta.

Este guardia es independiente del caché de Streamlit: vive en un módulo normal,
así que sobrevive a cualquier `clear()` y también a que app.py re-ejecute
dashboard_ui.py con runpy en cada rerun (los globales de ese script se pierden
en cada interacción; los de un módulo importado, no).

Doble comprobación con cerrojo: el segundo que llega ESPERA y se lleva el
resultado del primero, en vez de lanzar un segundo barrido en paralelo.
"""
import threading
import time

FRESCURA_S = 900          # 15 min: mismo TTL que tenía el caché anterior

_cerrojo = threading.Lock()
_estado = {'ts': 0.0, 'datos': None, 'barridos': 0, 'esperas': 0}


def _fresco(ahora: float) -> bool:
    return _estado['datos'] is not None and ahora - _estado['ts'] < FRESCURA_S


def barrido(calcular, forzar: bool = False):
    """
    Ejecuta `calcular()` garantizando que no se solape consigo mismo.

    `calcular` es una función sin argumentos (normalmente
    alpha_finder.apuestas_del_dia_universal). Se inyecta en vez de importarla
    aquí para poder probar este módulo sin pagar un barrido de 90 segundos.
    """
    entrada = time.time()
    if not forzar and _fresco(entrada):
        return _estado['datos']

    with _cerrojo:
        if time.time() - entrada > 0.01:
            _estado['esperas'] += 1
        # Otro hilo pudo calcularlo mientras esperábamos el cerrojo.
        #
        # El criterio no es sólo "¿hay algo fresco?", porque con forzar=True
        # (el botón "Actualizar ahora") siempre lo hay y nunca se recalcularía.
        # Es "¿alguien ha terminado un barrido DESPUÉS de que yo pidiera el
        # mío?": si sí, ese resultado ya satisface mi petición y me lo llevo;
        # si no, lo calculo yo. Así `forzar` recalcula de verdad, pero cinco
        # usuarios pulsando "Actualizar" a la vez siguen provocando un único
        # barrido en lugar de cinco de 1,3 GB cada uno.
        if _estado['datos'] is not None and _estado['ts'] > entrada:
            return _estado['datos']
        if not forzar and _fresco(time.time()):
            return _estado['datos']
        datos = calcular()
        _estado['datos'] = datos
        _estado['ts'] = time.time()
        _estado['barridos'] += 1
        return datos


def estadisticas() -> dict:
    """Para pruebas y diagnóstico: cuántos barridos reales y cuántas esperas."""
    return dict(_estado, datos=('sí' if _estado['datos'] is not None else 'no'))


def reiniciar() -> None:
    """Sólo para pruebas."""
    _estado.update(ts=0.0, datos=None, barridos=0, esperas=0)
