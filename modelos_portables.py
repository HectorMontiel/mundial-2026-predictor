#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v87 — Cargar modelos de XGBoost serializados en otra plataforma.

El problema
-----------
Los `modelo.joblib` que publica el workflow de reentrenamiento se serializan en
el runner de GitHub (Linux) y **no se pueden abrir en Windows** con la MISMA
versión de XGBoost (3.3.0):

    xgboost._c_api.XGBoostError: input stream corrupted

Se descartó, con medición, que fuera corrupción de fichero (v86): el blob del
repo coincide byte a byte con el disco, `.gitattributes` ya declara
`*.joblib binary`, la proporción de CRLF es la de un binario sano, y los
artefactos de sklearn del mismo commit cargan sin problema.

La causa
--------
Al hacer pickle, XGBoost guarda el booster con `XGBoosterSerializeToBuffer`.
Ése es el formato de **serialización**, que la propia librería documenta como
dependiente del entorno y sólo apto para uso inmediato. El formato de **modelo**
—el que escribe `save_model` / `save_raw(raw_format='ubj')`— sí es portable.

La solución
-----------
Medido: el buffer de serialización **contiene dentro** al de modelo.

    save_raw(ubj)            1.209.040 bytes, empieza por {L..\\x07learner
    buffer de serialización  1.217.311 bytes, empieza por {L..\\x06Config
    el segundo contiene al primero a partir del byte 8270

Así que se puede recortar la cabecera `Config` y quedarse con la sección
`learner`, que es exactamente lo que `Booster.load_model` sabe leer — y ese
camino sí funciona entre plataformas.

Comprobado que el recorte no cambia nada: `save_raw(ubj)` -> `load_model`
devuelve predicciones **idénticas** (diferencia máxima 0,00e+00).

Uso
---
    import modelos_portables as mp
    modelo = mp.cargar('modelos/liga_mx/modelo.joblib')

Si el joblib abre de forma normal, se devuelve tal cual y no se toca nada. Sólo
si XGBoost se queja se aplica la reparación.
"""
import logging
import threading
from typing import List, Optional

logger = logging.getLogger(__name__)

# v88 — LA REPARACIÓN PARCHEA `Booster.__setstate__`, QUE ES GLOBAL AL PROCESO.
#
# `alpha_finder.apuestas_del_dia_universal` corre sus cuatro ramas (fútbol,
# MLB, tenis, NBA) en un ThreadPoolExecutor. Mientras el hilo de fútbol tenía
# el parche puesto para reparar un modelo de liga, el hilo de MLB cargaba SU
# modelo y pasaba por el parche del otro. El resultado era
#
#     OSError: exception: access violation reading 0x0000000000000000
#
# dentro de `XGBoosterPredict`, varios pasos más adelante — y en el barrido
# salía como «MLB omitido por error», dejando el deporte entero fuera de las
# Apuestas del Día.
#
# Dos candados:
#   · `_CERROJO` serializa las reparaciones, para que dos hilos no se pisen el
#     parche ni su restauración.
#   · `reponer` comprueba la identidad del hilo y delega en el original si la
#     llamada viene de otro. Así, aunque el parche esté puesto, sólo afecta al
#     `joblib.load` que lo pidió.
_CERROJO = threading.RLock()

# Clave "Model" del objeto UBJSON exterior, escrita como cadena con longitud
# int64 (0x4C = 'L'). Su VALOR es el modelo portable.
#
# OJO: no vale buscar «learner» directamente. La sección «Config» también tiene
# una clave con ese nombre y aparece antes (byte 16), así que buscarla llevaba a
# recortar el trozo equivocado — que es justo lo que hacía fallar el primer
# intento de esta reparación.
MARCA_MODEL = b'L\x00\x00\x00\x00\x00\x00\x00\x05Model'

__all__ = ['cargar', 'recortar_a_modelo', 'es_error_de_plataforma']


def es_error_de_plataforma(e: BaseException) -> bool:
    """¿Es el fallo típico de un booster serializado en otra plataforma?"""
    return 'input stream corrupted' in str(e).lower()


def recortar_a_modelo(buf: bytes) -> Optional[bytes]:
    """
    Saca la sección portable («learner») del buffer de serialización.

    Devuelve None si no se encuentra: mejor no devolver nada que devolver algo
    que no se sabe qué es.
    """
    if not buf:
        return None
    b = bytes(buf)
    i = b.find(MARCA_MODEL)
    if i < 0:
        return None
    return b[i + len(MARCA_MODEL):]


def _boosters_del_pickle(ruta: str) -> List[bytes]:
    """Buffers de booster de un joblib, aunque XGBoost no los pueda abrir."""
    import joblib
    import xgboost.core as xc

    cap: List[bytes] = []
    original = xc.Booster.__setstate__
    hilo = threading.get_ident()

    def espia(self, state):
        # sólo para el hilo que pidió la captura; ver `_CERROJO`
        if threading.get_ident() != hilo:
            return original(self, state)
        st = dict(state) if isinstance(state, dict) else {}
        h = st.get('handle')
        if isinstance(h, (bytes, bytearray)):
            cap.append(bytes(h))
        # `handle` DEBE quedar en None. `Booster.__del__` hace
        #
        #     if hasattr(self, "handle") and self.handle is not None:
        #         _check_call(_LIB.XGBoosterFree(self.handle))
        #
        # así que si se le deja el bytearray del buffer, al recolectar el
        # objeto intenta liberar unos bytes como si fueran un puntero y lanza
        #
        #     ArgumentError: argument 1: TypeError: Don't know how to convert
        #     parameter 1
        #
        # desde `__del__`, o sea en un momento impredecible. En el barrido eso
        # caía dentro del try/except de MLB y salía como «MLB omitido por
        # error», dejando el deporte entero fuera de las Apuestas del Día.
        st['handle'] = None
        self.__dict__.update(st)

    xc.Booster.__setstate__ = espia
    try:
        joblib.load(ruta)
    except Exception:
        pass
    finally:
        xc.Booster.__setstate__ = original
    return cap


def _cargar_en(booster, buf: bytes) -> bool:
    """
    Carga la sección portable de `buf` DENTRO de `booster`.

    v88 — antes esto construía un Booster temporal y le trasplantaba el handle
    al definitivo (`self.handle = tmp.handle; tmp.handle = None`). Parecía
    funcionar —los 43 modelos se reparaban y predecían— pero dejaba la
    biblioteca en un estado inconsistente: más adelante, en el mismo proceso,
    otro modelo cualquiera reventaba con

        OSError: exception: access violation reading 0x0000000000000000

    dentro de `XGBoosterPredict`. Es la firma de un uso-después-de-liberar. En
    el barrido salía como «MLB omitido por error», o sea que el trasplante se
    cargaba un deporte entero a varios pasos de distancia.

    Ahora cada Booster crea y conserva SU handle: se inicializa `booster` como
    un Booster vacío en condiciones y se le carga el modelo encima. Sin
    trasplantes y usando sólo la API pública.
    """
    import xgboost as xgb

    modelo = recortar_a_modelo(buf)
    if modelo is None:
        return False
    for candidato in (modelo, modelo[:-1]):
        try:
            xgb.Booster.__init__(booster)          # handle propio y limpio
            booster.load_model(bytearray(candidato))
            return True
        except Exception:
            continue
    return False


def cargar(ruta: str):
    """
    `joblib.load` con reparación si el booster viene de otra plataforma.

    Devuelve el modelo listo para predecir, o lanza la excepción original si no
    se puede reparar (nunca devuelve un modelo a medias).
    """
    import joblib
    import xgboost.core as xc

    try:
        return joblib.load(ruta)
    except Exception as e:
        if not es_error_de_plataforma(e):
            raise
        logger.info(f'{ruta}: booster de otra plataforma, se repara por la '
                    f'ruta portable')

    # El parche de `__setstate__` es global al proceso, así que la reparación
    # entera va bajo cerrojo. Ver el comentario de `_CERROJO`.
    with _CERROJO:
        # Comprobación previa: que TODOS los boosters se puedan reconstruir
        # antes de tocar nada. Si alguno no, se falla limpio en vez de devolver
        # un modelo a medias.
        buffers = _boosters_del_pickle(ruta)
        if not buffers:
            raise RuntimeError(f'{ruta}: no se pudo extraer ningún booster')
        if any(recortar_a_modelo(b) is None for b in buffers):
            malos = sum(1 for b in buffers if recortar_a_modelo(b) is None)
            raise RuntimeError(f'{ruta}: {malos} de {len(buffers)} boosters sin '
                               f'sección de modelo recuperable')

        # Segunda pasada: cada Booster se reconstruye SOBRE SÍ MISMO (ver
        # `_cargar_en`: nada de trasplantar handles entre objetos).
        fallos = []
        original = xc.Booster.__setstate__
        hilo = threading.get_ident()

        def reponer(self, state):
            # Si la llamada viene de OTRO hilo, este parche no es asunto suyo:
            # se delega en el original. Sin esto, el hilo de MLB cargaba su
            # modelo a través del parche del hilo de fútbol.
            if threading.get_ident() != hilo:
                return original(self, state)
            h = state.get('handle') if isinstance(state, dict) else None
            if isinstance(h, (bytes, bytearray)):
                if _cargar_en(self, bytes(h)):
                    for k, v in state.items():
                        if k != 'handle':
                            setattr(self, k, v)
                    return
                fallos.append(1)
            original(self, state)

        xc.Booster.__setstate__ = reponer
        try:
            modelo = joblib.load(ruta)
        finally:
            xc.Booster.__setstate__ = original
        if fallos:
            raise RuntimeError(f'{ruta}: {len(fallos)} boosters no se pudieron '
                               f'reconstruir')
        return modelo
