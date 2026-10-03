# -*- coding: utf-8 -*-
"""
v323 — LOS CONTROLES DE UNA VISTA QUE NO SE EJECUTA, CONSERVADOS.

Hasta la v322 «Apuestas del Día» ejecutaba SIEMPRE sus cinco vistas (hoy,
mañana, pasado, combinadas y estado) y escondía cuatro con CSS. No era
capricho: un widget que no llega vivo al final de una pasada desaparece de
`st.session_state`, y con él lo que el usuario había elegido (§27.9, v177.2).
El precio era calcular cuatro pantallas que nadie miraba en cada clic.

Ahora sólo se ejecuta la vista elegida, y lo que guardaba el widget vivo lo
guarda una COPIA con clave propia (`_copia_<clave>`): las claves que no son de
un widget no las borra Streamlit. Al volver a la vista, la copia se repone en
el widget ANTES de crearlo, y el usuario encuentra sus controles como los dejó
— igual que cuando la vista seguía ejecutándose escondida.

Dos funciones, y se usan siempre juntas:

    estado_vistas.recupera(st, 'mc_bank')
    v = st.number_input(..., key='mc_bank')
    estado_vistas.apunta(st, 'mc_bank', v)
"""
import logging
from typing import Any, Iterable, Optional

logger = logging.getLogger('estado_vistas')

PREFIJO = '_copia_'


def recupera(st, clave: str, opciones: Optional[Iterable] = None) -> None:
    """Repone en el widget `clave` la copia guardada, si el widget no existe.

    Si el usuario ya tocó el widget en esta pasada (la clave está viva), no se
    toca nada. Con `opciones`, una copia que ya no es una opción válida —la
    lista de partidos cambió— no se repone: un `selectbox` con un valor que no
    está en su lista reventaría.
    """
    try:
        ss = st.session_state
        copia = PREFIJO + clave
        if clave in ss or copia not in ss:
            return
        valor = ss[copia]
        if opciones is not None:
            ops = list(opciones)
            if isinstance(valor, (list, tuple)):
                valor = [v for v in valor if v in ops]
            elif valor not in ops:
                return
        ss[clave] = valor
    except Exception as e:
        logger.debug('[estado_vistas] recupera %s: %s', clave, e)


def apunta(st, clave: str, valor: Any) -> None:
    """Guarda la copia del valor que el widget tiene en esta pasada."""
    try:
        st.session_state[PREFIJO + clave] = valor
    except Exception as e:
        logger.debug('[estado_vistas] apunta %s: %s', clave, e)
