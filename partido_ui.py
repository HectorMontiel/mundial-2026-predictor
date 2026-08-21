#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v147 · Navegación por secciones de la ficha del partido.

El problema, medido
-------------------
La ficha era un scroll único y tardaba. Medido el 2026-08-17 abriendo la ficha
de una liga cuyo motor no estaba cargado:

    abrir la ficha en frío ......... 15,9 s
      ClubEngine (cargar modelo) ...  3,1 s
      PETICIONES DE RED ............ 41 peticiones · 21,4 s acumulados
          site.api.espn.com ........ 35 · 18,4 s
          sports.core.api.espn.com ..  6 ·  3,0 s

Y con las cachés de disco ya calientes, todavía 7 peticiones y 7,2 s.

O sea: **el coste es de RED, no de cálculo.** La predicción y el H2H salen del
CSV local en centésimas; lo que se va en segundos son las cuotas por casa, los
rosters y los remates de ESPN.

Por qué un selector y NO `st.tabs`
-----------------------------------
Esto es lo importante y es contraintuitivo:

**Streamlit renderiza el contenido de TODAS las pestañas**, se vea la que se
vea. Un `st.tabs` reorganiza el scroll y no ahorra ni una petición: la ficha
quedaría igual de lenta y mejor peinada, que es la peor combinación. Lo mismo
con `st.expander`, cuyo contenido también se ejecuta aunque esté plegado.

Un selector —`st.radio` horizontal— devuelve **cuál** está elegida, así que el
código puede ejecutar sólo esa. Es lo que convierte la navegación en ahorro
real. Se ve prácticamente como unas pestañas. (Sobre por qué radio y no
`st.segmented_control`, que queda mejor: ver el comentario de `selector`.)

Con el «Resumen» por defecto —que sólo lee el CSV local— abrir una ficha deja
de tocar la red.

Lo que NO cambia
----------------
Las secciones son las mismas y hacen lo mismo; sólo se ejecutan cuando se
miran. Nada se oculta: el selector enseña las cinco desde el primer momento, y
cada una dice qué contiene.
"""
from __future__ import annotations

import logging
from typing import Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

# Las cinco secciones, uniformes para todos los deportes. El contenido varía
# —córners en fútbol, yardas en NFL, abridores en MLB— y la estructura no, que
# es lo que permite aprender la navegación una sola vez.
RESUMEN = '📊 Resumen'
MERCADOS = '📈 Mercados'
H2H = '🤝 H2H y forma'
ESPECIFICOS = '🚩 Específicos'
COMBINADAS = '🧩 Combinadas'

ORDEN = (RESUMEN, MERCADOS, H2H, ESPECIFICOS, COMBINADAS)

# Qué secciones tocan la red. Se usa para avisar al usuario ANTES de que pulse,
# en vez de dejarle esperando sin saber por qué.
CON_RED = {MERCADOS, ESPECIFICOS}

AYUDA = {
    RESUMEN: 'Pronóstico, marcador probable y lectura. Sale del histórico '
             'local: no consulta ninguna casa, así que es instantáneo.',
    MERCADOS: 'Todos los mercados con su probabilidad y las cuotas reales de '
              'las casas. Consulta la red la primera vez.',
    H2H: 'Cara a cara, forma reciente y estadísticas de los dos equipos.',
    ESPECIFICOS: 'Lo propio de este deporte: córners en fútbol, yardas en NFL, '
                 'abridores en MLB, saque en tenis.',
    COMBINADAS: 'Parlays de este partido, con su probabilidad conjunta.',
}


def selector(st, clave: str, disponibles: Optional[List[str]] = None) -> str:
    """
    Pinta el selector de sección y devuelve la elegida.

    `clave` separa el estado por partido/competición, para que abrir otra ficha
    no herede la sección de la anterior — y para que volver a la misma la
    recuerde, que es lo que se espera al ir y venir con el botón «Ver».
    """
    ops = [s for s in ORDEN if not disponibles or s in disponibles]
    k = f'_sec_{clave}'
    # v147 — RADIO HORIZONTAL Y NO `segmented_control`, POR TESTABILIDAD.
    #
    # `st.segmented_control` existe en esta versión (1.61) y queda mejor, pero
    # **AppTest no lo expone**: comprobado, `at.get('segmented_control')`
    # devuelve cero elementos aunque el control se pinte. Con él, el smoke no
    # podría pulsar las secciones, y este proyecto ya sabe lo que cuesta un
    # camino que sólo se recorre en producción — el UnboundLocalError de la
    # v58.1 llegó al usuario exactamente así.
    #
    # `st.radio(horizontal=True)` se ve casi igual, hace lo mismo y AppTest lo
    # maneja entero. Se prefiere poder probarlo a que se vea un poco mejor.
    #
    # Lo que NO se usa, y es el motivo de este módulo: `st.tabs`. Streamlit
    # renderiza el contenido de todas las pestañas se mire la que se mire, así
    # que no diferiría ni una petición.
    sel = st.radio('Sección', ops, horizontal=True, key=k,
                   label_visibility='collapsed',
                   help='Se carga sólo la sección que abres. Las de mercados '
                        'consultan las casas; el resto son instantáneas.')
    sel = sel or ops[0]
    if AYUDA.get(sel):
        st.caption(AYUDA[sel])
    return sel


def render(st, clave: str, secciones: Dict[str, Callable[[], None]],
           titulo: Optional[str] = None) -> str:
    """
    Pinta el selector y ejecuta SÓLO la sección elegida.

    `secciones` es `{nombre: función sin argumentos}`. Las que no se eligen no
    se llaman — que es todo el punto: es donde se ahorran las peticiones.

    Una sección que falla no tumba la ficha: se informa y el selector sigue,
    así que el usuario puede irse a otra.
    """
    if titulo:
        st.markdown(titulo)
    sel = selector(st, clave, disponibles=list(secciones))
    fn = secciones.get(sel)
    if fn is None:
        st.info('Esta sección no está disponible para este partido.')
        return sel
    try:
        fn()
    except Exception as e:                                  # pragma: no cover
        logger.warning(f'[partido-ui] sección {sel}: {type(e).__name__}: {e}')
        st.error(f'No se pudo cargar «{sel}» ({type(e).__name__}). '
                 f'Las demás secciones siguen disponibles.')
    return sel
