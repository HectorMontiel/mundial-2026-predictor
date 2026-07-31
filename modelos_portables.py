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
from typing import List, Optional

logger = logging.getLogger(__name__)

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

    def espia(self, state):
        if isinstance(state, dict) and isinstance(state.get('handle'),
                                                  (bytes, bytearray)):
            cap.append(bytes(state['handle']))
        # se deja el objeto a medio construir a propósito: sólo interesa el buffer
        self.__dict__.update(state if isinstance(state, dict) else {})

    xc.Booster.__setstate__ = espia
    try:
        joblib.load(ruta)
    except Exception:
        pass
    finally:
        xc.Booster.__setstate__ = original
    return cap


def _booster_desde_buffer(buf: bytes):
    """Reconstruye un Booster por la ruta portable."""
    import xgboost as xgb

    modelo = recortar_a_modelo(buf)
    if modelo is None:
        return None
    for candidato in (modelo, modelo[:-1]):
        try:
            b = xgb.Booster()
            b.load_model(bytearray(candidato))
            return b
        except Exception:
            continue
    return None


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

    buffers = _boosters_del_pickle(ruta)
    if not buffers:
        raise RuntimeError(f'{ruta}: no se pudo extraer ningún booster')

    reparados = [_booster_desde_buffer(b) for b in buffers]
    if any(r is None for r in reparados):
        malos = sum(1 for r in reparados if r is None)
        raise RuntimeError(f'{ruta}: {malos} de {len(reparados)} boosters no '
                           f'se pudieron reparar')

    # segunda pasada: ahora __setstate__ coge el booster ya reconstruido
    pendientes = list(reparados)
    original = xc.Booster.__setstate__

    def reponer(self, state):
        if isinstance(state, dict) and isinstance(state.get('handle'),
                                                  (bytes, bytearray)):
            b = pendientes.pop(0)
            self.__dict__.update(
                {k: v for k, v in state.items() if k != 'handle'})
            self.handle = b.handle
            # se le quita la propiedad al Booster temporal para que su __del__
            # no libere un handle que ahora usa otro objeto
            b.handle = None
            return
        original(self, state)

    xc.Booster.__setstate__ = reponer
    try:
        return joblib.load(ruta)
    finally:
        xc.Booster.__setstate__ = original
