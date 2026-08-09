#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v114 — Puente entre una apuesta del tablón y la vista de su partido.

Lo que pidió el usuario
-----------------------
«Si en apuestas del día está una predicción de Monterrey vs Juárez −3.5 goles y
hago click, que me lleves a Liga MX al partido seleccionado para ver sus
estadísticas y poder evaluar qué parlay meter.»

Por qué hace falta un módulo y no basta un botón
------------------------------------------------
Streamlit prohíbe escribir la clave de un widget DESPUÉS de instanciarlo:

    st.session_state.competencia cannot be modified after the widget with
    key `competencia` is instantiated

Y el selector de competición se crea arriba del script, mucho antes de que se
pinte ninguna tarjeta. Así que un botón dentro de una tarjeta no puede tocar
`st.session_state['competencia']` directamente: reventaría la página.

La solución es en dos tiempos, que es el patrón estándar para esto:

  1. la tarjeta sólo APUNTA el destino en una clave propia (`_ir_a`) y pide un
     rerun — eso siempre es legal, porque `_ir_a` no es de ningún widget;
  2. al principio del script siguiente, ANTES de crear el selector,
     `aplicar_pendiente()` traduce ese destino a las claves de los widgets.

Cada deporte tiene sus propias claves de selector, así que el mapa vive aquí y
no repartido por la interfaz.
"""
import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)

CLAVE_PENDIENTE = '_ir_a'

# clave de la vista -> (clave del selector local, clave del selector visitante)
SELECTORES_DEPORTE = {
    'mlb_deporte': ('mlb_h', 'mlb_a'),
    'kbo_deporte': ('kbo_h', 'kbo_a'),
    'nba_deporte': ('nba_h', 'nba_a'),
    'tennis_deporte': ('ten_1', 'ten_2'),
}

# deporte que declara el pick -> vista a la que se navega
VISTA_POR_DEPORTE = {
    'MLB': 'mlb_deporte', 'KBO': 'kbo_deporte', 'NBA': 'nba_deporte',
    'Tenis': 'tennis_deporte',
}


def partes_del_partido(texto: str) -> Optional[tuple]:
    """
    «A vs B» → (A, B).  «A @ B» → (B, A), porque en el formato estadounidense
    el primero es el VISITANTE. Es la misma convención que `cuotas_multi`
    aplica al leer Altenar, y confundirla invierte los bandos.
    """
    t = str(texto or '')
    if ' vs ' in t:
        a, b = t.split(' vs ', 1)
        return a.strip(), b.strip()
    if ' @ ' in t:
        a, b = t.split(' @ ', 1)
        return b.strip(), a.strip()
    return None


def destino_del_pick(pick: Dict) -> Optional[Dict]:
    """
    A dónde lleva esta apuesta, o None si no se sabe.

    Devolver None es un resultado válido y frecuente: un pick sin `clave_liga`
    o con un nombre de partido que no se puede partir en dos no tiene destino,
    y entonces la tarjeta simplemente no ofrece el botón. Es preferible a
    ofrecer un botón que lleve a la liga equivocada.
    """
    if not isinstance(pick, dict):
        return None
    partes = partes_del_partido(pick.get('partido'))
    if not partes:
        return None
    deporte = pick.get('deporte') or 'Fútbol'
    clave = pick.get('clave_liga')
    if deporte != 'Fútbol':
        vista = VISTA_POR_DEPORTE.get(deporte)
        if not vista:
            return None
        # el tenis reparte ATP y WTA en un radio dentro de la MISMA vista
        circuito = None
        if vista == 'tennis_deporte':
            circuito = ('WTA (femenino)' if str(clave).lower() == 'wta'
                        else 'ATP (masculino)')
        return {'vista': vista, 'home': partes[0], 'away': partes[1],
                'circuito': circuito, 'deporte': deporte}
    if not clave:
        return None
    return {'vista': clave, 'home': partes[0], 'away': partes[1],
            'deporte': 'Fútbol'}


def marcar(st, destino: Dict) -> None:
    """Apunta el destino para el próximo script. NO toca claves de widget."""
    st.session_state[CLAVE_PENDIENTE] = destino


def aplicar_pendiente(st, competencias: Dict[str, str],
                      equipos_de_liga=None) -> Optional[str]:
    """
    Consume el destino pendiente y deja el estado listo. Se llama UNA vez, al
    principio del script y antes de crear el selector de competición.

    `competencias` es el mapa {etiqueta visible: clave} de la interfaz.
    `equipos_de_liga(clave) -> list` permite ajustar el nombre del equipo al
    que usa el catálogo de esa competición; si no se pasa, se escribe tal cual.

    Devuelve la etiqueta a la que se ha navegado, o None si no había nada
    pendiente. Nunca lanza: un destino imposible se ignora en silencio y el
    usuario se queda donde estaba, que es mejor que una página en blanco.
    """
    destino = st.session_state.pop(CLAVE_PENDIENTE, None)
    if not destino:
        return None
    try:
        vista = destino.get('vista')
        etiqueta = next((e for e, k in competencias.items() if k == vista), None)
        if not etiqueta:
            logger.info(f'[navegacion] vista «{vista}» no está en el menú')
            return None
        st.session_state['competencia'] = etiqueta

        home, away = destino.get('home'), destino.get('away')
        if vista in SELECTORES_DEPORTE:
            k_h, k_a = SELECTORES_DEPORTE[vista]
            if destino.get('circuito'):
                st.session_state['ten_circ'] = destino['circuito']
            # el selector de tenis se deshabilita cuando hay un partido del
            # calendario elegido; se suelta para que manden estos nombres
            st.session_state.pop('ten_fx_sel', None)
        else:
            k_h, k_a = f'club_home_{vista}', f'club_away_{vista}'
            # lo mismo con el selector de «Próximos partidos» de la liga: si
            # se queda con su valor anterior, su `on_change` no salta pero el
            # usuario ve un partido distinto del que pidió
            st.session_state.pop(f'fx_sel_{vista}', None)

        if equipos_de_liga is not None:
            try:
                catalogo = list(equipos_de_liga(vista) or [])
                home = _ajustar(home, catalogo) or home
                away = _ajustar(away, catalogo) or away
            except Exception as e:
                logger.debug(f'[navegacion] catálogo de {vista}: {e}')
        st.session_state[k_h] = home
        st.session_state[k_a] = away
        return etiqueta
    except Exception as e:
        logger.warning(f'[navegacion] destino descartado: {type(e).__name__}: {e}')
        return None


def _ajustar(nombre: str, catalogo: list) -> Optional[str]:
    """
    El nombre tal y como lo escribe el catálogo de esa competición.

    El pick trae el nombre del motor, así que casi siempre coincide; pero los
    picks de MLB llegan con el nombre largo («Detroit Tigers») y el selector de
    esa vista trabaja con códigos. Si no se encuentra equivalencia se devuelve
    None y el llamador conserva el original: escribir en el `session_state` de
    un selectbox un valor que no está entre sus opciones haría que Streamlit
    lance, y eso sí rompería la página.
    """
    if not nombre or not catalogo:
        return None
    if nombre in catalogo:
        return nombre
    try:
        import name_mapper
        m = name_mapper.mapear(nombre, catalogo, contexto='navegacion')
        if m:
            return m
    except Exception:
        pass
    import difflib
    cerca = difflib.get_close_matches(str(nombre), [str(c) for c in catalogo],
                                      n=1, cutoff=0.85)
    return cerca[0] if cerca else None
