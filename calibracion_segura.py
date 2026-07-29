#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v79 — Acceso a prueba de módulos obsoletos a la calibración de mercado.

El problema real que resuelve
-----------------------------
En producción, con el código correcto en disco y en los dos remotos:

    [alpha] tenis omitido: AttributeError: module 'calibracion_mercado'
            has no attribute 'corregir_dos_vias'

`corregir_dos_vias` existe desde la v78. Lo que ocurre es que Streamlit
mantiene los módulos ya importados en `sys.modules` entre ejecuciones del
script: al desplegar, `alpha_finder` se reimportó nuevo mientras
`calibracion_mercado` seguía siendo el objeto de la v77 cargado en memoria.
El `import calibracion_mercado as _cal` de dentro de la función no vuelve a
leer el fichero — devuelve el módulo viejo, sin el atributo.

Por qué un `try/except` en la función no bastaba
------------------------------------------------
Bastaba para no romper, pero el `except` que recogía el error envolvía el
barrido COMPLETO de tenis, así que un fallo de calibración se llevó por
delante los 319 partidos del día. La corrección de probabilidad es una mejora
de calidad; el barrido es el producto. Nunca pueden caer juntos.

Qué hace este módulo
--------------------
1. Busca la función; si no está, **recarga el módulo desde disco** y la vuelve
   a buscar (que es justo lo que arregla el caso de `sys.modules` caliente).
2. Si aun así no está, devuelve la probabilidad SIN corregir y lo dice en la
   info, en vez de propagar la excepción.

Es deliberadamente pequeño y sin estado para que no tenga nada que envejecer.
"""
import importlib
import logging
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

# Orden de preferencia: el envoltorio resiliente de la v79 y, si no,
# la función original de la v78.
_NOMBRES = ('encoger_dos_vias', 'corregir_dos_vias')


def _resolver(nombres=_NOMBRES):
    import calibracion_mercado as cal
    for n in nombres:
        fn = getattr(cal, n, None)
        if callable(fn):
            return fn
    # `sys.modules` tiene una versión vieja: se relee el fichero.
    try:
        cal = importlib.reload(cal)
    except Exception as e:
        logger.warning(f"[calibracion] no se pudo recargar el módulo: {e}")
        return None
    for n in nombres:
        fn = getattr(cal, n, None)
        if callable(fn):
            logger.info(f"[calibracion] módulo obsoleto en memoria; "
                        f"recargado y resuelto '{n}'")
            return fn
    return None


def encoger_dos_vias(p_home: float, cuota_home: Optional[float],
                     cuota_away: Optional[float],
                     clave_liga: str) -> Tuple[float, dict]:
    """Encogimiento hacia el mercado en deportes sin empate. Nunca lanza."""
    info = {'aplicado': False, 'w': 1.0, 'liga': clave_liga}
    try:
        fn = _resolver()
        if fn is None:
            info['error'] = 'calibracion_mercado sin función de dos vías'
            logger.warning(f"[calibracion] {clave_liga}: {info['error']}")
            return p_home, info
        return fn(p_home, cuota_home, cuota_away, clave_liga)
    except Exception as e:
        logger.warning(f"[calibracion] {clave_liga} sin encoger: "
                       f"{type(e).__name__}: {e}")
        info['error'] = f'{type(e).__name__}: {e}'
        return p_home, info


def peso_modelo(clave_liga: str) -> float:
    """`w` de la liga; 1.0 (sin corrección) si no se puede resolver."""
    try:
        import calibracion_mercado as cal
        fn = getattr(cal, 'peso_modelo', None)
        return float(fn(clave_liga)) if callable(fn) else 1.0
    except Exception:
        return 1.0
