#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v176 — LOS FILTROS SE QUEDAN COMO SE DEJARON.

Qué resuelve
------------
«Los filtros deporte y orden deben persistir... Al cambiar de pestaña (Hoy →
Mañana → Hoy), la app NO debe resetear los filtros.»

Y hay que separar dos problemas que el encargo junta, porque se arreglan en
sitios distintos:

  1. **ENTRE PESTAÑAS.** El de deporte ya persistía —vive en `dashboard_ui` con
     una sola clave global, `_filtro_deporte`, así que las dos pestañas leen el
     mismo estado. El de ORDEN no: `modo_modelo.render` usaba
     `'%s_orden' % clave`, o sea `mm_orden` para hoy y `man_orden` para mañana,
     que son dos ajustes distintos a propósito. El encargo pide lo contrario
     («el usuario quiere consistencia»).

     **Y NO SE ARREGLA DÁNDOLES LA MISMA `key`**, que fue lo primero que se
     intentó. Las dos pestañas se pintan en cada pasada —una pestaña oculta se
     renderiza igual—, así que dos `selectbox` con la misma clave levantan un
     `StreamlitDuplicateElementKey` y se llevan por delante la pestaña entera.
     Lo cazó `valida_render`. Lo que se comparte es el VALOR, no la clave: ver
     `sincronizar`.

  2. **ENTRE SESIONES.** Eso `st.session_state` no lo hace: se vacía al
     recargar. Para eso está este módulo, que deja las preferencias en un JSON
     y las vuelve a poner al arrancar.

QUÉ SE GUARDA Y QUÉ NO
----------------------
Sólo la ELECCIÓN del usuario en los controles de la pantalla: qué deporte, qué
orden, qué casillas. Nada de datos, nada de picks, nada que caduque. Si el
fichero se borra, la aplicación arranca con los valores por defecto y no pasa
nada — es una comodidad, no un estado del que dependa un número.

LA GUARDA QUE HACE FALTA, Y NO ES OBVIA
----------------------------------------
Una preferencia guardada puede quedarse **huérfana**: si mañana se renombra un
criterio de orden, el JSON seguirá pidiendo el viejo y `st.selectbox` reventaría
con un valor que no está en su lista. Por eso `leer_opcion` recibe las opciones
válidas y devuelve el valor por defecto cuando lo guardado ya no existe. Es el
mismo cuidado que `dashboard_ui._olvidar_seleccion_muerta` tiene con los
selectores de partido, aplicado aquí antes de que muerda.
"""
import logging
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger('preferencias_usuario')

FICHERO = os.environ.get('PREFERENCIAS_USUARIO', 'preferencias_usuario.json')

_CACHE: Optional[Dict] = None


def _leer() -> Dict:
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    doc = {}
    try:
        import io_atomico
        doc = io_atomico.leer_json(FICHERO, {}) or {}
    except Exception as e:
        logger.debug('[preferencias] no se pudo leer %s: %s', FICHERO, e)
    _CACHE = doc if isinstance(doc, dict) else {}
    return _CACHE


def leer(clave: str, por_defecto: Any = None) -> Any:
    """La preferencia guardada, o `por_defecto`."""
    return _leer().get(str(clave), por_defecto)


def leer_opcion(clave: str, opciones: List, por_defecto: Any = None) -> Any:
    """
    La preferencia guardada SI sigue siendo una opción válida.

    Un valor huérfano —de una versión en la que ese criterio se llamaba de otra
    forma— no puede llegar a un `selectbox`: reventaría la pantalla entera. Se
    devuelve el defecto y se olvida.
    """
    v = leer(clave)
    if v is not None and v in (opciones or []):
        return v
    if por_defecto is not None and por_defecto in (opciones or []):
        return por_defecto
    return (opciones or [None])[0]


def guardar(clave: str, valor: Any) -> bool:
    """
    Deja la preferencia en disco. No escribe si no ha cambiado.

    Esa comprobación no es un adorno: `render` se ejecuta entero en cada
    interacción de Streamlit, así que sin ella la aplicación escribiría el
    fichero cada vez que el usuario pulsa cualquier cosa.
    """
    doc = _leer()
    if doc.get(str(clave)) == valor:
        return False
    nuevo = dict(doc)
    nuevo[str(clave)] = valor
    global _CACHE
    _CACHE = nuevo
    try:
        import io_atomico
        return bool(io_atomico.escribir_json(FICHERO, nuevo, indent=1))
    except Exception as e:
        logger.debug('[preferencias] no se pudo escribir %s: %s', FICHERO, e)
        return False


def sembrar(st, clave_sesion: str, valor) -> None:
    """
    Pone el valor guardado en `st.session_state` ANTES de crear el widget.

    Es la única forma de que un widget de Streamlit arranque con un valor
    distinto del primero de su lista sin pasarle `index=`, y funciona igual
    para `selectbox`, `radio` y `checkbox`. Si la clave ya está —o sea, si el
    usuario ya tocó el control en esta sesión— no se toca: lo que el usuario
    acaba de elegir manda sobre lo que había guardado.
    """
    try:
        if clave_sesion not in st.session_state:
            st.session_state[clave_sesion] = valor
    except Exception as e:
        logger.debug('[preferencias] sembrar %s: %s', clave_sesion, e)


def recordar(st, clave_sesion: str, opciones: Optional[List] = None,
             por_defecto: Any = None) -> Any:
    """
    Siembra el widget con lo guardado y devuelve el valor que debe usar.

    Uso:

        preferencias_usuario.recordar(st, 'mm_orden', list(ORDENES), 'Hora')
        etq = st.selectbox('Ordenar por', list(ORDENES), key='mm_orden')
        preferencias_usuario.guardar('mm_orden', etq)
    """
    if opciones is not None:
        valor = leer_opcion(clave_sesion, opciones, por_defecto)
    else:
        valor = leer(clave_sesion, por_defecto)
    sembrar(st, clave_sesion, valor)
    return valor


def sincronizar(st, clave_widget: str, clave_pref: str,
                opciones: Optional[List] = None,
                por_defecto: Any = None) -> Any:
    """
    Dos widgets distintos que comparten UN ajuste. Devuelve el valor.

    POR QUÉ NO BASTA CON DARLES LA MISMA `key`, que es lo que se intentó
    primero: Streamlit no lo permite. Las pestañas de Hoy y Mañana se
    pintan **las dos en cada pasada** —una pestaña oculta se renderiza
    igual—, así que dos `selectbox` con `key='mm_orden_global'` levantan
    un `StreamlitDuplicateElementKey` y se lleva por delante la pestaña
    entera. Lo cazó `valida_render`, que es exactamente para lo que está.

    Así que cada widget conserva SU clave y lo que se comparte es el
    VALOR:

      · al entrar, si la preferencia cambió desde la última vez que ESTA
        vista la miró, se adopta —así el orden elegido en Hoy aparece en
        Mañana—;
      · al salir, si el usuario tocó este widget, se guarda.

    La marca `_sync_<clave_widget>` es lo que distingue «la preferencia
    cambió en otra vista» de «este widget ya está en su valor». Sin ella
    habría que reescribir el widget en cada pasada, y eso pisaría lo que
    el usuario acaba de elegir aquí.
    """
    if opciones is not None:
        valor = leer_opcion(clave_pref, opciones, por_defecto)
    else:
        valor = leer(clave_pref, por_defecto)
    marca = '_sync_%s' % clave_widget
    try:
        if st.session_state.get(marca) != valor:
            st.session_state[clave_widget] = valor
            st.session_state[marca] = valor
    except Exception as e:
        logger.debug('[preferencias] sincronizar %s: %s', clave_widget, e)
    return valor


def confirmar(st, clave_widget: str, clave_pref: str, valor) -> None:
    """Guarda lo que el usuario acaba de elegir en este widget."""
    if guardar(clave_pref, valor):
        try:
            st.session_state['_sync_%s' % clave_widget] = valor
        except Exception as e:
            logger.debug('[preferencias] confirmar %s: %s',
                         clave_widget, e)


def olvidar() -> None:
    """Vacía la caché en memoria. Sólo lo usan los tests."""
    global _CACHE
    _CACHE = None
