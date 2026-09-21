# -*- coding: utf-8 -*-
"""
v298 — De qué día es cada pick, y quedarse con los de uno.

DE DONDE SALE
El usuario lo pidió con un caso concreto:

    «Capa uno sólo me da apuestas de hoy, a pesar de que aplique el filtro de
     mañana en apuestas del día... también tengo que tener filtro de hoy y de
     mañana en la sección de escaleras.»

Y tenía razón a medias, que es lo interesante. El barrido SÍ trae mañana: el
tablero del 2026-09-21 tenía 78 partidos de hoy y 418 del día siguiente, y de
los nueve picks de esa pasada, cuatro eran del 22. Lo que faltaba era el
mando. El selector de hoy/mañana existía SÓLO en Soñadoras; en Apuestas del
Día los días se agrupaban bajo un encabezado, así que los de mañana quedaban
al final de la lista y parecían no existir, y en la Escalera no había nada.

POR QUE ESTO ES UN MODULO Y NO DOS FUNCIONES EN LA PANTALLA
Porque `dashboard_ui` no se puede importar en un test: al importarlo se
ejecuta el router y revienta con `KeyError: 'alpha'`. Una lógica que decide
qué apuestas ve el usuario no puede quedarse en un sitio donde no se pueda
probar.
"""
from __future__ import annotations

import datetime as _dt
import logging
from typing import List, Optional

logger = logging.getLogger(__name__)

HOY = 'hoy'
MANANA = 'mañana'
TODO = 'todo'


def dia_de(pick) -> str:
    """La fecha del pick en AAAA-MM-DD, o cadena vacía. NUNCA lanza.

    Los picks llegan por dos caminos con la fecha en dos formatos: el barrido
    en vivo la trae normalizada en `fecha`, y el precálculo puede traer sólo
    `inicio`, que es una marca de tiempo Unix. Leer sólo uno de los dos deja
    fuera media lista sin avisar — el mismo tropiezo que la v279, donde un
    `inicio` en crudo llegó a `_etiqueta_dia` y tumbó la app entera.
    """
    if not isinstance(pick, dict):
        return ''
    f = str(pick.get('fecha') or '')[:10]
    if len(f) == 10 and f[4:5] == '-' and f[7:8] == '-':
        return f
    try:
        return _dt.datetime.fromtimestamp(
            float(pick.get('inicio'))).strftime('%Y-%m-%d')
    except (TypeError, ValueError, OSError, OverflowError):
        return ''


def fecha_del_modo(modo: str, hoy: Optional[_dt.date] = None) -> str:
    """La fecha que representa 'hoy' o 'mañana'. Cadena vacía para el resto."""
    base = hoy or _dt.date.today()
    if modo == HOY:
        return base.strftime('%Y-%m-%d')
    if modo == MANANA:
        return (base + _dt.timedelta(days=1)).strftime('%Y-%m-%d')
    return ''


def solo_del_dia(picks: List[dict], modo: str,
                 hoy: Optional[_dt.date] = None) -> List[dict]:
    """Los picks de ese día. Cualquier `modo` que no sea hoy/mañana: todos.

    Va aparte del selector a propósito: hay pantallas que filtran DOS listas
    con un solo mando —las secciones 1 y 2 de Apuestas del Día— y hacerlo
    comparando identidades de objetos se rompe en cuanto algo los copia.

    NUNCA lanza.
    """
    try:
        objetivo = fecha_del_modo(modo, hoy)
        if not objetivo:
            return [p for p in (picks or []) if isinstance(p, dict)]
        return [p for p in (picks or [])
                if isinstance(p, dict) and dia_de(p) == objetivo]
    except Exception as e:
        logger.debug('[dia_picks] %s', e)
        return [p for p in (picks or []) if isinstance(p, dict)]


def cuenta(picks: List[dict], hoy: Optional[_dt.date] = None) -> dict:
    """{'todo': n, 'hoy': n, 'mañana': n} para rotular el selector."""
    lista = [p for p in (picks or []) if isinstance(p, dict)]
    return {TODO: len(lista),
            HOY: len(solo_del_dia(lista, HOY, hoy)),
            MANANA: len(solo_del_dia(lista, MANANA, hoy))}
