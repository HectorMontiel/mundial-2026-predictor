#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v79 — Quitar el paralelismo de joblib en INFERENCIA (no en entrenamiento).

El hallazgo
-----------
Perfilando el barrido diario, después de arreglar el emparejamiento de
nombres, el mayor consumo restante era este:

    league_engine.predecir            146 llamadas    50,1 s   (0,34 s cada una)
      └ VotingClassifier.predict_proba 370 llamadas   44,3 s   (0,12 s cada una)
    joblib.parallel._get_outputs   167.240 llamadas   75,7 s
    multiprocessing ... PeekNamedPipe / CloseHandle   ~120 s acumulados

0,12 segundos para predecir **una sola fila** no es cálculo: es coordinación.
Los modelos se guardaron con `RandomForestClassifier(n_jobs=-1)` y
`XGBClassifier(n_jobs=-1)`, que es lo correcto al ENTRENAR con miles de filas.
Pero esa configuración viaja dentro del `.joblib`, así que en producción cada
predicción de un partido reparte el trabajo entre todos los núcleos, con su
cola de procesos, sus tuberías y su recogida de resultados... para repartir
200 árboles sobre UNA muestra. El reparto cuesta órdenes de magnitud más que
evaluar los árboles.

Qué hace este módulo
--------------------
Recorre el estimador cargado y pone `n_jobs = 1` en todo lo que lo tenga.
Las predicciones son EXACTAMENTE las mismas — `n_jobs` solo decide cómo se
reparte el cálculo, no qué se calcula. Es una optimización sin efecto
observable salvo el tiempo.

No se toca el entrenamiento: allí el paralelismo sí compensa y se sigue
usando `n_jobs=-1`.
"""
import logging

logger = logging.getLogger(__name__)

# Atributos por los que hay que descender para encontrar estimadores anidados.
_HIJOS = ('estimators_', 'estimators', 'estimator', 'base_estimator',
          'calibrated_classifiers_', 'estimator_', 'named_estimators_')


def secuencial(modelo, _visto=None) -> int:
    """
    Pone `n_jobs=1` en el estimador y en todos sus hijos. Devuelve cuántos
    cambió. Nunca lanza: si un modelo tiene una forma inesperada, se deja como
    está (perder velocidad es aceptable; romper la carga del modelo no).
    """
    if modelo is None:
        return 0
    if _visto is None:
        _visto = set()
    if id(modelo) in _visto:
        return 0
    _visto.add(id(modelo))

    n = 0
    try:
        if hasattr(modelo, 'n_jobs') and getattr(modelo, 'n_jobs') not in (1, None):
            modelo.n_jobs = 1
            n += 1
    except Exception:
        pass

    for attr in _HIJOS:
        try:
            hijo = getattr(modelo, attr, None)
        except Exception:
            continue
        if hijo is None:
            continue
        try:
            if isinstance(hijo, dict):
                for v in hijo.values():
                    n += secuencial(v, _visto)
            elif isinstance(hijo, (list, tuple)):
                for v in hijo:
                    # VotingClassifier guarda ('nombre', estimador)
                    if isinstance(v, tuple) and len(v) == 2:
                        n += secuencial(v[1], _visto)
                    else:
                        n += secuencial(v, _visto)
            elif hasattr(hijo, '__class__'):
                n += secuencial(hijo, _visto)
        except Exception:
            continue
    return n


def preparar(*modelos) -> int:
    """Aplica `secuencial` a varios modelos y registra el total."""
    total = 0
    for m in modelos:
        try:
            total += secuencial(m)
        except Exception as e:
            logger.debug(f"[inferencia] no se pudo secuenciar: {e}")
    if total:
        logger.debug(f"[inferencia] n_jobs=1 en {total} estimadores")
    return total
