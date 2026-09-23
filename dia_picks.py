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


def hoy_local() -> _dt.date:
    """Qué día es HOY para el usuario, que vive en CDMX. NUNCA lanza.

    v301 — ESTO ERA `date.today()` Y ESTABA MAL, CON CONSECUENCIAS.

    `date.today()` da el día del SERVIDOR, y el servidor de Streamlit va en
    UTC. Medido el 2026-09-22 a las 04:26 UTC:

        hoy en UTC ..... 2026-09-23
        hoy en CDMX .... 2026-09-22

    O sea que la aplicación iba un día por delante del usuario y todo lo que
    llamaba «hoy» era su mañana. Él lo vio como «me estás combinando los
    días», que es exactamente lo que pasaba.
    """
    try:
        import horario as _h
        return _dt.datetime.now(_dt.timezone.utc).astimezone(
            _h._zona()).date()
    except Exception as e:
        logger.warning('[dia_picks] sin zona de CDMX (%s); se usa UTC-6', e)
        return (_dt.datetime.now(_dt.timezone.utc)
                - _dt.timedelta(hours=6)).date()


def dia_de(pick) -> str:
    """El día del pick EN HORA DE CDMX, en AAAA-MM-DD. NUNCA lanza.

    v301 — SE CONVIERTE DESDE `inicio`, QUE ES LA VERDAD EN UTC.

    El proyecto tiene un invariante que un test vigila (`test_un_solo_reloj`):
    todo el barrido razona en UTC, porque las fechas de las fuentes son UTC y
    mezclar relojes ya costó un día entero de partidos descartados (v91). La
    conversión a CDMX es de PRESENTACIÓN, y este módulo es presentación.

    Por qué importa tanto: de los 618 partidos del tablero del 2026-09-22,
    **123 cambian de día** según la zona que se use.

        Lanus vs Estudiantes L.P.    UTC 22 00:15  |  CDMX 21 18:15
        Independiente vs Tomayapo    UTC 22 00:30  |  CDMX 21 18:30

    Un partido de las 18:15 en México es de HOY por la tarde, y en UTC ya es
    del día siguiente. Con `fecha` —que el barrido calcula en la hora del
    servidor— salía como «mañana» a alguien que lo iba a ver esa misma noche.

    Por eso se prefiere SIEMPRE `inicio`: es la marca de tiempo real y se
    puede convertir. `fecha` sólo se usa cuando no hay `inicio`, y entonces se
    toma tal cual, que es lo único que se puede hacer con una cadena ya
    calculada en otra zona.
    """
    if not isinstance(pick, dict):
        return ''
    ini = pick.get('inicio')
    if ini not in (None, ''):
        try:
            import horario as _h
            f = _h.fecha(ini)
            if f:
                return f
        except Exception as e:
            logger.debug('[dia_picks] horario.fecha(%r): %s', ini, e)
    f = str(pick.get('fecha') or '')[:10]
    if len(f) == 10 and f[4:5] == '-' and f[7:8] == '-':
        return f
    return ''


def fecha_del_modo(modo: str, hoy: Optional[_dt.date] = None) -> str:
    """La fecha que representa 'hoy' o 'mañana' EN CDMX.

    Cadena vacía para cualquier otro modo.
    """
    base = hoy or hoy_local()
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
