#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Efecto rebote por entrenador nuevo. LA REGLA ESTÁ ESCRITA Y NO ESTÁ ENCENDIDA.

QUÉ PEDÍA EL ENCARGO
--------------------
Detectar equipos que cambiaron de entrenador en los últimos 7 días y penalizar
al rival favorito:

    si el rival cambió de entrenador hace <= 7 días y el favorito paga < 1,85:
        la probabilidad del favorito baja 0,15
        se bloquean «Más de goles» y «Gana el favorito»
        se avisa: «efecto rebote por nuevo entrenador»

El caso que lo motiva: Alavés (favorito a 1,84) perdió contra un Valencia que
había cambiado de entrenador esa semana.

POR QUÉ ESTÁ APAGADA
--------------------
**No hay fuente.** El encargo lo dice él mismo —«si el dato no está en el
pipeline, la regla NO se activa»— y ésta es la comprobación:

    grep de coach/manager/entrenador en todo el repo ........ 0 aciertos
    ESPN soccer scoreboard  (esp.1, 2026-09-15) ............. 0 campos
    ESPN soccer summary     (evento completo, 430 KB) ....... 0 campos
        claves que devuelve: boxscore · broadcasts · commentary · format ·
        gameInfo · hasOdds · header · keyEvents · lastFiveGames · leaders ·
        meta · news · odds · pickcenter · rosters · seasonseries · standings

`rosters` trae jugadores, no cuerpo técnico. Las fuentes que sí lo publican
—Transfermarkt, SofaScore— no están en el pipeline y ninguna ofrece una API
abierta; meterlas es una tanda propia, con su scraper y su medición.

ASÍ QUE ESTO NO INVENTA NADA. `rebote_entrenador` devuelve siempre `False` con
`fuente: None`, y la pata sale marcada `medido: False`. El día que aparezca una
fuente basta con implementar `fuente_cambios()`: la regla, sus umbrales y su
efecto ya están aquí y probados contra una fuente inyectada.

LO QUE TAMPOCO SE PUEDE AFIRMAR TODAVÍA
---------------------------------------
Que el efecto rebote exista. Es una creencia razonable y muy extendida, pero
este proyecto no la ha medido nunca, y sin fuente de cambios de entrenador no
puede medirla: haría falta el histórico de destituciones cruzado con los
resultados posteriores. Cuando la fuente llegue, lo primero NO es encender la
regla —es medir si el rebote existe y de qué tamaño—, porque el 0,15 de
penalización que pide el encargo es un número puesto a mano.
"""

import datetime as _dt
import logging
from typing import Callable, Dict, Optional

logger = logging.getLogger(__name__)

# Los parámetros del encargo, tal cual, para cuando haya con qué encenderlos.
DIAS_VENTANA = 7
CUOTA_FAVORITO_MAXIMA = 1.85
PENALIZACION = 0.15
MERCADOS_BLOQUEADOS = ('Más de goles', 'Gana el favorito')

# Lo comprobado el 2026-09-15. Viaja con el código para que nadie repita el
# sondeo ni dé por hecho que el dato está.
SONDEO = {
    'fecha': '2026-09-15',
    'fuentes_probadas': {
        'repo (grep coach/manager/entrenador)': 0,
        'espn soccer scoreboard': 0,
        'espn soccer summary': 0,
    },
    'conclusion': 'ninguna fuente del pipeline publica cuerpo técnico',
    'alternativas_no_integradas': ['Transfermarkt', 'SofaScore'],
}

# El enchufe. Una función que, dado un día, devuelva
# {nombre_de_equipo: 'AAAA-MM-DD' del cambio}.
#
# v203 — YA HAY PUERTA, Y SIGUE SIN HABER DATO. `buscador_fuentes` encontró el
# entrenador en FotMob (por el `__NEXT_DATA__`, la misma vía que el proyecto ya
# usaba para los córners), pero FotMob **no publica la fecha de nombramiento**:
# da quién entrena hoy y nada más. Así que un cambio sólo se ve comparando con
# la foto de ayer, y eso exige un historial con fondo.
#
# `conectar_buscador()` enchufa ese historial. Mientras no tenga ni un cambio
# observado devuelve un diccionario vacío y la regla sigue apagada — que es lo
# correcto y no un fallo: el primer día de una serie no tiene «antes».
_FUENTE: Optional[Callable[[str], Dict[str, str]]] = None


def registrar_fuente(fn: Optional[Callable[[str], Dict[str, str]]]) -> None:
    """Enchufa (o quita) la fuente de cambios de entrenador.

    Existe para que la regla se pueda PROBAR sin inventar datos en producción:
    los tests inyectan una fuente de mentira, comprueban que la regla dispara
    como pide el encargo, y la quitan. Sin llamar a esto, el módulo es inerte.
    """
    global _FUENTE
    _FUENTE = fn


def conectar_buscador() -> bool:
    """Enchufa el historial de entrenadores de `buscador_fuentes`.

    Devuelve `True` sólo si ese historial puede detectar cambios de verdad —o
    sea, si tiene al menos un entrenador anterior guardado—. Si no, no enchufa
    nada: una fuente que siempre devuelve vacío haría creer que la regla está
    viva cuando está ciega.
    """
    try:
        import buscador_fuentes as bf
        if not bf.estado().get('puede_detectar_cambios'):
            return False
        registrar_fuente(lambda dia: bf.cambios_recientes(DIAS_VENTANA, dia))
        return True
    except Exception as e:
        logger.debug('[contexto] no se pudo conectar el buscador: %s', e)
        return False


def hay_fuente() -> bool:
    return _FUENTE is not None


def fuente_cambios(dia: str) -> Dict[str, str]:
    """Cambios de entrenador conocidos para ese día. Vacío si no hay fuente."""
    if _FUENTE is None:
        return {}
    try:
        return dict(_FUENTE(dia) or {})
    except Exception as e:
        logger.warning('[contexto] la fuente de entrenadores falló: %s', e)
        return {}


def _dias_desde(fecha: Optional[str], dia: str) -> Optional[int]:
    try:
        a = _dt.date.fromisoformat(str(fecha)[:10])
        b = _dt.date.fromisoformat(str(dia)[:10])
    except (TypeError, ValueError):
        return None
    return (b - a).days


def cambio_reciente(equipo: Optional[str], dia: str) -> Optional[int]:
    """Días desde el cambio de entrenador de ese equipo, si cae en la ventana."""
    if not equipo:
        return None
    cambios = fuente_cambios(dia)
    d = _dias_desde(cambios.get(str(equipo)), dia)
    if d is None or d < 0 or d > DIAS_VENTANA:
        return None
    return d


def rebote_entrenador(local: Optional[str], visitante: Optional[str],
                      dia: str, cuota_favorito: Optional[float] = None,
                      lado_favorito: str = '') -> Dict:
    """¿Hay efecto rebote contra el favorito de este partido?

    Devuelve siempre un diccionario con `activo` y `medido`, nunca lanza. Con
    `medido: False` —que es el caso de hoy— quien lo consume debe tratarlo como
    «no se sabe», no como «no pasa nada».
    """
    base = {'activo': False, 'medido': hay_fuente(), 'fuente': None,
            'dias': None, 'equipo': None, 'aviso': ''}
    if not hay_fuente():
        return base
    base['fuente'] = 'fuente registrada'
    # el rebote lo produce el RIVAL del favorito: es su entrenador nuevo el que
    # sacude al equipo, y el favorito es quien lo sufre
    rival = {'local': visitante, 'visitante': local}.get(lado_favorito)
    if rival is None:
        return base
    d = cambio_reciente(rival, dia)
    if d is None:
        return base
    try:
        c = float(cuota_favorito)
    except (TypeError, ValueError):
        return base
    if c >= CUOTA_FAVORITO_MAXIMA:
        return base
    return {**base, 'activo': True, 'dias': d, 'equipo': rival,
            'penalizacion': PENALIZACION,
            'mercados_bloqueados': list(MERCADOS_BLOQUEADOS),
            'aviso': f'⚠️ Efecto rebote por nuevo entrenador: {rival} lo '
                     f'cambió hace {d} día(s)'}


def penalizar(prob: float, info: Dict) -> float:
    """La probabilidad del favorito tras el rebote. Sin rebote, intacta."""
    try:
        p = float(prob)
    except (TypeError, ValueError):
        return prob
    if not (info or {}).get('activo'):
        return p
    return max(0.0, min(1.0, p - float(info.get('penalizacion', PENALIZACION))))


def estado() -> Dict:
    """Lo que la pantalla y la bitácora necesitan saber del módulo."""
    return {'activo': hay_fuente(), 'medido': False,
            'motivo': ('' if hay_fuente() else
                       'ninguna fuente del pipeline publica cambios de '
                       'entrenador; la regla está escrita y apagada'),
            'ventana_dias': DIAS_VENTANA,
            'cuota_favorito_maxima': CUOTA_FAVORITO_MAXIMA,
            'penalizacion': PENALIZACION,
            'sondeo': SONDEO}
