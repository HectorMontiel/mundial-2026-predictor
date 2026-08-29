#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Dashboard — "¿Quién gana?" + Plantilla General de Análisis Estadístico.

Pestaña 1: respuesta ultra simple (ganador, marcador, probabilidades,
           factor decisivo, goleadores reales, consultas en texto libre).
Pestaña 2: la Plantilla General de Análisis (9 secciones, ~85 campos)
           rellenada automáticamente por el modelo, con TODOS los campos
           editables, botón "Validar mis estimaciones" (diferencias +
           cuotas justas + detección de valor) y exportación a Markdown.

Ejecutar:  streamlit run dashboard_ui.py
"""

import json
import logging
import os

import numpy as np
import pandas as pd
import streamlit as st
import plotly.graph_objects as go

import horario as _horario          # v106: hora de los partidos en CDMX
from prediction_api import PredictionEngine, NOMBRES_PAIS, plantilla_a_markdown
from arbitros import ARBITROS
from altitud import ESTADIOS_MUNDIAL, nivel_aclimatacion

# v152 — EL `logger` DE ESTE FICHERO NO EXISTÍA, Y SE USABA EN SEIS SITIOS.
#
# Los seis viven dentro de un `except` que intenta dejar constancia del fallo
# antes de degradar la pantalla. Sin esta línea, ese `except` lanzaba
# `NameError: name 'logger' is not defined` **encima** del error original: el
# manejador se llevaba por delante la vista entera y además borraba la pista de
# lo que había pasado de verdad.
#
# Cinco de los seis llevaban versiones ahí, latentes, porque son caminos de
# excepción que casi nunca se recorren. Lo destapó la validación de render de
# esta misma versión al cargar «Apuestas del Día»: la vista murió con el
# NameError y el fallo real quedó tapado.
#
# Es exactamente para esto que el render se valida con AppTest y no con
# `py_compile`: un nombre indefinido dentro de un `except` compila igual de bien
# que uno definido.
logger = logging.getLogger(__name__)

# 1. PRIMER COMANDO DE STREAMLIT (OBLIGATORIO)
st.set_page_config(
    page_title="Predictor deportivo — cuotas, valor y combinadas",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="expanded",
)

# v117 — LA CAPA VISUAL.
#
# La aplicación tenía cinco años de funciones amontonadas y ninguna gramática
# visual: todo del mismo tamaño, del mismo color, y la jerarquía la marcaba el
# orden en que estaban escritas las cosas. `estilo_ui` sólo inyecta CSS y
# ofrece componentes; no toca ningún número. Si falla, la app se ve como antes
# y sigue funcionando igual — por eso va en try.
try:
    import estilo_ui as _estilo
    _estilo.aplicar(st)
except Exception:
    _estilo = None

# v119 — AYUDA EN CASTELLANO LLANO, EN CADA SECCIÓN.
#
# El usuario lo pidió así: «quizá no sabe qué es EV, tradúcelo a su idioma,
# quizá no sabe qué es line shopping». `ayuda.py` traduce la jerga y explica
# cómo leer cada pantalla — y dice también lo que NO conviene creerse, que es
# la parte que una ayuda comercial se saltaría.
try:
    import ayuda as _ayuda
except Exception:
    _ayuda = None


# ===========================================================================
# v122 — LOS ATAJOS DE PRESENTACIÓN
#
# `estilo_ui` puede no cargar (va en `try` a propósito: la capa visual jamás
# puede costar la aplicación), así que cada uso suyo necesitaría un `if
# _estilo is not None`. Con más de cien usos repartidos por catorce pantallas
# eso es ruido puro y, sobre todo, es la clase de comprobación que alguien se
# salta un día y deja la app en blanco.
#
# Estos tres atajos lo resuelven de una vez: si no hay capa visual, no pintan
# nada y la pantalla sigue entera con el texto de siempre.
# ===========================================================================
def _html_esc(t) -> str:
    """
    Texto del modelo que va a entrar en un componente HTML.

    Los nombres de equipo y las descripciones vienen de catálogos y de
    plantillas propias, no de nadie de fuera, pero un `&` o un `<` sin escapar
    rompe el componente entero y deja media tarjeta en blanco. Sale más barato
    escapar siempre que ir caso por caso decidiendo si hace falta.
    """
    import html as _h
    return _h.escape(str(t if t is not None else ''), quote=True)


def _pinta(html) -> None:
    """Escribe un componente de `estilo_ui`; no hace nada si no hay capa."""
    if _estilo is not None and html:
        _estilo.pinta(st, html)


def _olvidar_seleccion_muerta(clave: str, opciones) -> None:
    """
    Borra de la sesión una selección que ya no existe entre las opciones.

    v123 — un `st.selectbox` con `key` lee su valor de la sesión, y si ese
    valor NO está en la lista de opciones Streamlit lanza `ValueError: ... is
    not in list` y se lleva la vista entera por delante. Pasa siempre que las
    opciones salen de una fuente viva: un partido que termina desaparece del
    calendario, y el que el usuario tenía elegido deja de existir.

    Lo cazó `smoke_botones.py` pulsando «🔄 Actualizar» en MLB:

        ValueError: '2026-08-12 11:40 · Baltimore Orioles @ Minnesota Twins'
        is not in list

    Con las claves estables (ver `selector_proximos`) el caso raro se vuelve
    poco frecuente, pero no imposible — por eso esta guardia va aparte y cubre
    lo que las claves estables no pueden cubrir: que la opción sencillamente ya
    no esté.
    """
    try:
        if clave in st.session_state and st.session_state[clave] not in opciones:
            del st.session_state[clave]
    except Exception:
        pass


def _seccion(titulo: str, sub: str = '', tono: str = 'ok') -> None:
    """Cabecera de sección. Sin capa visual, cae al `####` de siempre."""
    if _estilo is not None:
        _estilo.pinta(st, _estilo.seccion(titulo, sub, tono))
    else:
        st.markdown(f"#### {titulo}" + (f" — {sub}" if sub else ''))


def _cabecera(titulo: str, subtitulo: str = '', chips=(), icono: str = '') -> None:
    """Cabecera de pantalla. Sin capa visual, cae al `st.title` de siempre."""
    if _estilo is not None:
        _estilo.pinta(st, _estilo.cabecera(titulo, subtitulo, chips, icono))
    else:
        st.title(f"{icono} {titulo}".strip())
        if subtitulo:
            st.caption(subtitulo)

# v14: login con contraseña RETIRADO a petición del usuario — la app es pública.

# CSS para ocultar el branding/pie de Streamlit (aporte del repo de despliegue)
#
# v128 — «LA BARRA LATERAL NO ME SALE EN MÓVILES». NO ERA LA BARRA LATERAL.
#
# Era la regla 4 de este bloque, que hasta ahora decía
#
#     footer, [data-testid="stHeader"] { display: none !important }
#
# Streamlit 1.61 mete el botón de ABRIR la barra lateral DENTRO de la cabecera.
# Medido en el navegador, a 375 px, con el CSS de la v127:
#
#     header[stHeader]                         -> display:none / hidden
#       └ div[stToolbar]
#           └ button[stExpandSidebarButton]    -> visibility:hidden · 0x0
#
# En escritorio no se nota porque la barra arranca desplegada y nadie la cierra.
# En el teléfono la barra se abre ENCIMA del contenido, así que lo primero que
# hace cualquiera es cerrarla para poder leer — y a partir de ahí no queda
# ningún control en pantalla que la devuelva: los únicos botones visibles
# pertenecen a la propia barra, que está fuera de la pantalla. Se pierden el
# modo Principiante/Pro, el bankroll, el panel de créditos y la navegación
# entera hasta recargar la página.
#
# La cabecera se HUNDE, no se borra: fondo transparente, sin sombra y sin
# capturar toques, de modo que el contenido sigue empezando arriba del todo
# exactamente igual que antes — está en `position: absolute`, así que no empuja
# nada (comprobado: el `top` del h1 no se mueve de 112 px). Lo único que vuelve
# a existir es el botón de abrir la barra, que sí recibe el toque. La marca de
# Streamlit (menú, «Deploy», widget de estado) se oculta una por una, que es lo
# que esta regla quería hacer desde el principio.
#
# El texto de dentro NO puede citar versiones: `test_mensajes_sin_jerga_interna`
# analiza las cadenas de este fichero y esta constante es una de ellas.
limpiar_interfaz_v2 = """
    <style>
        /* 1. Apuntar al identificador oficial moderno de Streamlit */
        [data-testid="stViewerBadge"] {
            display: none !important;
            visibility: hidden !important;
            height: 0 !important;
            width: 0 !important;
            opacity: 0 !important;
            pointer-events: none !important;
        }

        /* 2. Por si acaso usan clases antiguas o variantes */
        div[class*="viewerBadge"], .viewerBadge_container {
            display: none !important;
            visibility: hidden !important;
        }

        /* 3. Bloquear cualquier enlace oculto a su dominio */
        a[href^="https://share.streamlit.io"] {
            display: none !important;
        }

        /* 4. El pie, fuera. La barra superior NO: dentro vive el botón que
         * abre la barra lateral, y sin él no hay forma de recuperarla en un
         * teléfono. Se hunde la cabecera y se oculta la marca una por una.
         * El porqué completo, medido, está en el comentario de Python de
         * arriba. */
        footer {
            display: none !important;
            visibility: hidden !important;
        }
        header[data-testid="stHeader"] {
            display: block !important;
            visibility: visible !important;
            background: transparent !important;
            box-shadow: none !important;
            pointer-events: none !important;
        }
        header[data-testid="stHeader"] [data-testid="stToolbar"] {
            visibility: visible !important;
            pointer-events: none !important;
        }
        [data-testid="stMainMenu"],
        [data-testid="stAppDeployButton"],
        [data-testid="stStatusWidget"],
        [data-testid="stToolbarActions"] {
            display: none !important;
        }
        /* el único superviviente de la cabecera: abrir la barra lateral */
        [data-testid="stExpandSidebarButton"] {
            visibility: visible !important;
            opacity: 1 !important;
            pointer-events: auto !important;
        }
        /* En el teléfono ese botón queda flotando sobre el contenido, así que
         * se le da cuerpo para que se lea como un control y no como un icono
         * suelto encima del texto. */
        @media (max-width: 768px) {
            [data-testid="stExpandSidebarButton"] {
                background: rgba(22, 27, 38, .92) !important;
                border: 1px solid rgba(255, 255, 255, .14) !important;
                border-radius: 10px !important;
                box-shadow: 0 2px 10px rgba(0, 0, 0, .45) !important;
            }
        }
    </style>
"""
st.markdown(limpiar_interfaz_v2, unsafe_allow_html=True)

# v47/v52 -> v86: REFRESCO AL ARRANCAR EL PROCESO, NO POR VISITANTE.
#
# Hasta v85 este bloque se ejecutaba en cada sesión nueva (`session_state`), y
# hacía dos cosas globales al proceso entero:
#
#   st.cache_data.clear()   -> el caché de datos NO es por sesión. Cada visitante
#                              nuevo borraba el de todos los que ya estaban
#                              dentro, obligándoles a recalcular el barrido de
#                              alpha_finder y las cuotas. Con dos usuarios eso
#                              es trabajo pesado duplicado en el mismo proceso.
#
#   importlib.reload(...)   -> reescribe el __dict__ del módulo en caliente
#                              mientras otra hebra puede estar ejecutando código
#                              de ese mismo módulo. Medido en
#                              _v86_repro_concurrencia.py: tras la recarga, el
#                              ClubEngine que guarda @st.cache_resource deja de
#                              ser instancia de league_engine.ClubEngine
#                              (isinstance -> False), porque la clase es un
#                              objeto nuevo y el motor cacheado apunta al viejo.
#
# El propósito original (que un despliegue se vea sin reiniciar) se conserva:
# Streamlit Cloud reinicia el contenedor en cada push, y este bloque se ejecuta
# igualmente al arrancar el proceso. Lo que se elimina es repetirlo por cada
# visitante, que es lo que rompía a los demás.
@st.cache_resource
def _refresco_de_arranque() -> bool:
    """Se ejecuta UNA vez por proceso: cache_resource es global, no por sesión."""
    import importlib as _il
    import sys as _sys
    # v88: `odds_api` sale de la lista — el módulo se ha retirado.
    for _mod in ('config', 'name_mapper', 'fixtures_espn', 'cuotas_multi',
                 'source_resilience', 'betexplorer_scraper', 'edge_engine',
                 'traductor_quant', 'league_engine', 'reto_escalera',
                 'data_health', 'alpha_finder', 'bot_telegram'):
        if _mod in _sys.modules:
            try:
                _il.reload(_sys.modules[_mod])
            except Exception:
                pass
    return True


_refresco_de_arranque()

COLORES = {'local': '#2ecc71', 'empate': '#95a5a6', 'visitante': '#3498db'}


# ===========================================================================
# v75 — Estado de la calibración de mercado y de los umbrales por liga
# ===========================================================================
def _panel_calibracion_v75(st) -> None:
    """
    Muestra, sin adornos, en qué se apoya hoy la selección de picks:
    el encogimiento hacia el cierre sharp, los umbrales de Capa 1 y cuánto
    histórico de cuotas hay detrás. Es la parte de "transparencia total": si un
    número no se puede sostener, se dice que no se puede.
    """
    try:
        if os.path.exists('calibracion_mercado.json'):
            with open('calibracion_mercado.json', encoding='utf-8') as f:
                cal = json.load(f)
            ligas = cal.get('ligas') or {}
            g = cal.get('global') or {}
            if ligas:
                txt = (f"**⚖️ Ajuste hacia el mercado:** {len(ligas)} ligas "
                       f"con peso propio · w global {cal.get('w_global', '—')}")
                if g.get('delta_logloss') is not None:
                    txt += (f" · validación fuera de muestra: log-loss "
                            f"{g.get('logloss_antes')} → {g.get('logloss_despues')} "
                            f"({g.get('delta_logloss'):+.4f}), precisión "
                            f"{g.get('delta_acc'):+.4f}")
                st.markdown(txt)
                with st.expander("Ver peso por liga"):
                    dfc = pd.DataFrame([
                        {'liga': k, 'w': v.get('w'),
                         'n partidos': v.get('n_partidos'),
                         'Δ log-loss': v.get('delta_logloss'),
                         'Δ precisión': v.get('delta_acc'),
                         'sesgo del pick': v.get('sesgo_pick')}
                        for k, v in ligas.items()])
                    st.dataframe(dfc.sort_values('w'), hide_index=True,
                                 width='stretch')
                    st.caption("w = peso del modelo frente al cierre devigado de "
                               "Pinnacle. w<1 corrige la sobreconfianza del lado "
                               "elegido (maldición del ganador). Elegido por "
                               "log-loss fuera de muestra, no por fórmula.")

        if os.path.exists('umbrales_capa1.json'):
            with open('umbrales_capa1.json', encoding='utf-8') as f:
                umb = json.load(f)
            met = (umb.get('global_metricas') or {}).get('optimizado') or {}
            base = (umb.get('global_metricas') or {}).get('referencia') or {}
            if umb.get('global'):
                st.markdown(
                    f"**🎚️ Filtros de selección recalibrados:** "
                    f"{umb['global']} · ROI fuera de muestra "
                    f"{(met.get('roi') or 0)*100:+.1f} % vs "
                    f"{(base.get('roi') or 0)*100:+.1f} % de los anteriores "
                    f"(p5 bootstrap {(met.get('p5') or 0)*100:+.1f} %, "
                    f"n={met.get('n')}).")
            else:
                st.caption(
                    "🎚️ Filtros de selección: ninguna combinación nueva "
                    "superó a la actual en las pruebas, así que se mantiene. "
                    "No mejorar y decirlo también es un resultado.")
            propias = umb.get('ligas') or {}
            if propias:
                st.caption(f"Con umbrales propios validados: "
                           f"{', '.join(sorted(propias))}.")

        if os.path.exists('_v75_import_odds.json'):
            with open('_v75_import_odds.json', encoding='utf-8') as f:
                imp = json.load(f)
            snaps = 0
            try:
                import sqlite3
                _c = sqlite3.connect('odds_historico.db')
                snaps = _c.execute("SELECT COUNT(*) FROM historical_odds "
                                   "WHERE fase='snapshot'").fetchone()[0]
                _c.close()
            except Exception:
                pass
            st.caption(
                f"📚 Histórico de cuotas: {imp.get('filas_insertadas', 0):,} "
                f"cierres en {imp.get('ligas_con_cuota', 0)} ligas · "
                f"{snaps:,} fotos diarias acumuladas para las "
                f"{len(imp.get('ligas_sin_cuota') or [])} competiciones que "
                f"ESPN deja sin cuota tras el partido.")
    except Exception as e:
        st.caption(f"Estado de calibración no disponible ({type(e).__name__}).")


# ===========================================================================
# v77 — Pestañas «Máxima Confianza» y «Combinadas»
# ===========================================================================
def _render_maxima_confianza(r) -> None:
    """
    Picks de probabilidad alta, con el acierto REAL de su banda al lado.

    La honestidad aquí no es un adorno. Medido sobre 36.006 predicciones fuera
    de muestra, el modelo dice 79,6 % en la banda ≥0,75 y acierta el 57,8 %:
    los picks que la app presentaría como los más seguros son los peor
    calibrados. Enseñar solo la probabilidad del modelo en una pestaña que se
    llama «Máxima Confianza» sería vender exactamente lo que no cumple.
    """
    picks = r.get('capa1_prob') or []
    st.caption(
        "Mismos modelos y mismas cuotas reales que «Máximo Valor»; lo que "
        "cambia es el criterio: prioriza acertar sobre cobrar caro. "
        "Stake reducido a ¼ de Kelly."
    )
    try:
        with open('calibracion_confianza.json', encoding='utf-8') as f:
            cal = json.load(f)
        # -------------------------------------------------------------------
        # v108 — EL ROI VA DELANTE, NO ESCONDIDO EN UN DESPLEGABLE.
        #
        # El usuario dijo «no quiero perder dinero y quiero que sean seguras», y
        # usa esta pestaña para decidir («los que tienen de 67 % si aciertan»).
        # La medición dice lo contrario y estaba dentro de un expander que hay
        # que abrir:
        #
        #     banda        n        ROI
        #     0,50-0,55  13.792   -5,03 %
        #     0,55-0,60  13.106   -4,66 %
        #     0,60-0,65   8.821   -4,88 %
        #     0,65-0,70   1.439   -6,52 %   <- justo la que él usa
        #     0,70-0,75      33  +27,76 %   <- 33 apuestas: ruido, no señal
        #
        # Apostar por la probabilidad del modelo pierde dinero en TODAS las
        # bandas con muestra real. Enseñar el acierto («61,5 %») sin el ROI
        # («-6,52 %») al lado es la media verdad que hace perder dinero: se
        # acierta seis de cada diez y aun así se pierde, porque la cuota de un
        # favorito no paga lo que arriesga.
        #
        # Un aviso que hay que desplegar para verlo no es un aviso.
        # -------------------------------------------------------------------
        _bandas = [b for b in cal.get('bandas', [])
                   if b.get('roi') is not None and b.get('n', 0) >= 500]
        _perdedoras = [b for b in _bandas if b['roi'] < 0]
        if _perdedoras:
            _peor = min(_perdedoras, key=lambda b: b['roi'])
            _n = sum(b['n'] for b in _perdedoras)
            st.error(
                f"🚨 **Estos picks, apostados sueltos, han PERDIDO dinero.** "
                f"Medido sobre {_n:,} apuestas fuera de muestra: las "
                f"{len(_perdedoras)} bandas con muestra real dan ROI negativo, "
                f"y la peor es la de "
                f"{_peor['desde']:.2f}–{_peor['hasta']:.2f} con "
                f"**{_peor['roi']:+.2%}** ({_peor['n']:,} apuestas, acierto "
                f"{_peor['acierto']:.1%}).  \n\n"
                f"Acertar y ganar no son lo mismo: se acierta seis de cada "
                f"diez y aun así se pierde, porque la cuota de un favorito no "
                f"paga lo que arriesga. **Esta pestaña sirve para elegir patas "
                f"de combinada, no para apostar sueltas.**  \n\n"
                f"Lo único con ROI positivo y robusto en el histórico del "
                f"proyecto es el **line shopping** (una casa pagando por "
                f"encima del precio justo de Pinnacle): +11,5 % en el tramo de "
                f"juicio con p5 +1,7 %. Está en «⚡ Máximo Valor», marcado "
                f"como «line shopping vs Pinnacle»."
                .replace(',', '.')
            )
        # v122 — LOS DOS NÚMEROS QUE DAN SENTIDO A ESTA PESTAÑA, EN GRANDE.
        #
        # «El modelo dice 79,6 % y acierta 57,8 %» es la frase más importante
        # de la pantalla y estaba enterrada en mitad de un párrafo de aviso.
        # Dos anillos enfrentados se leen antes de leer: la distancia entre los
        # dos arcos ES el mensaje.
        _alta = [b for b in cal.get('bandas', [])
                 if b.get('acierto') and b.get('prob_media_modelo')
                 and b.get('n', 0) >= 30 and b.get('desde', 0) >= 0.75]
        if _alta and _estilo is not None:
            _b = max(_alta, key=lambda b: b.get('n', 0))
            _c1, _c2, _c3 = st.columns([1, 1, 3])
            with _c1:
                _pinta(_estilo.anillo(_b['prob_media_modelo'],
                                      'dice el modelo', 'mira'))
            with _c2:
                _pinta(_estilo.anillo(_b['acierto'], 'acierta', 'no'))
            _c3.markdown(
                f"**En la banda de {_b['desde']:.2f} para arriba, el modelo "
                f"promete un {_b['prob_media_modelo']:.1%} y acierta un "
                f"{_b['acierto']:.1%}** ({_b['n']:,} predicciones fuera de "
                f"muestra). El acierto **no crece** con la probabilidad: se "
                f"estanca en torno al 63 % y por encima de 0,75 empeora. Por "
                f"eso el umbral está en "
                f"{cal.get('umbral_recomendado', 0.70):.0%} y por eso cada pick "
                f"muestra el acierto real de su banda, no sólo lo que promete."
                .replace(',', '.'))
        else:
            st.warning(
                f"**Cómo leer esta pestaña.** Sobre {cal['n_total']:,} "
                f"predicciones fuera de muestra, el acierto **no crece** con la "
                f"probabilidad: se estanca en torno al 63 % y por encima de "
                f"0,75 empeora (el modelo dice 79,6 % y acierta 57,8 %). Por "
                f"eso el umbral está en "
                f"{cal.get('umbral_recomendado', 0.70):.0%}, que es el que "
                f"mejor rindió, y por eso cada pick muestra el acierto real de "
                f"su banda."
                .replace(',', '.')
            )
        with st.expander("📊 Acierto real y ROI por banda de probabilidad",
                         expanded=True):
            dfb = pd.DataFrame([
                {'Banda': f"{b['desde']:.2f}–{b['hasta']:.2f}", 'n': b['n'],
                 'Dice el modelo': (f"{b['prob_media_modelo']:.1%}"
                                    if b.get('prob_media_modelo') else '—'),
                 'Acierta de verdad': (f"{b['acierto']:.1%}"
                                       if b.get('acierto') else 'muestra corta'),
                 'ROI': (f"{b['roi']:+.2%}" if b.get('roi') is not None else '—'),
                 # v108: el ROI sin su p5 engaña. La banda 0,70-0,75 luce
                 # +27,76 % con 33 apuestas: eso no es una oportunidad, es el
                 # tamaño de muestra. El percentil 5 del bootstrap dice cuánto
                 # de eso aguanta.
                 'ROI en el peor 5 %': (f"{b['p5']:+.2%}"
                                        if b.get('p5') is not None else '—'),
                 'Fiable': ('✅' if (b.get('n', 0) >= 500) else
                            '⚠️ muestra corta')}
                for b in cal.get('bandas', [])])
            st.dataframe(dfb, hide_index=True, width='stretch')
            st.caption(
                "**n** es cuántas apuestas se midieron. Una banda con menos de "
                "500 no dice nada: la de 0,70–0,75 luce +27,8 % con **33 "
                "apuestas**, que es ruido, no una oportunidad. La columna del "
                "peor 5 % es el bootstrap: cuánto queda del ROI si repites el "
                "histórico mil veces y te toca una racha mala.")
    except Exception:
        pass

    if not picks:
        if _estilo is not None:
            _pinta(_estilo.vacio(
                "Hoy ningún pick llega al umbral",
                "Es lo normal algunos días: históricamente sólo un 0,31 % de "
                "los partidos lo consigue. Mejor una pestaña vacía que un pick "
                "forzado.", '🎯'))
        else:
            st.info("Hoy ningún pick alcanza el umbral de confianza. Es lo "
                    "normal algunos días: históricamente solo un 0,31 % de los "
                    "partidos lo consigue.")
        return

    neg = [p for p in picks if p.get('ev_negativo')]
    if neg:
        st.error(f"⚠️ {len(neg)} de estos picks tienen **EV negativo**: se "
                 f"acierta mucho y aun así se pierde dinero a la larga, porque "
                 f"la cuota no paga el riesgo. Úsalos como patas de combinada, "
                 f"no como apuesta simple.")
    # -----------------------------------------------------------------------
    # v106 — HORA DEL PARTIDO Y FRANJA HORARIA.
    #
    # El usuario usa esta tabla para decidir («los que tienen de 67 % si
    # aciertan») y pidió dos cosas más: ver la hora, y poder agrupar por
    # franjas «para saber qué parlay puedo armar por secciones de hora». Una
    # combinada sólo tiene sentido si sus patas se juegan en una ventana que
    # se pueda seguir; con la tabla ordenada por fecha eso había que deducirlo
    # partido a partido.
    #
    # Se ordena por HORA dentro del día, no por liga: es el orden en que hay
    # que apostarlos.
    # -----------------------------------------------------------------------
    def _franja(p):
        """Bloque de 3 horas en hora de CDMX, o '' si la fuente no dio hora."""
        h = p.get('hora_cdmx')
        if not h:
            return ''
        try:
            hh = int(str(h).split(':')[0])
        except (ValueError, IndexError):
            return ''
        ini = (hh // 3) * 3
        return f'{ini:02d}:00–{(ini + 3) % 24:02d}:00'

    filas = []
    # v89: la semana entera entra al barrido — HOY primero y el resto por fecha
    # v106: y dentro del día, por hora de inicio
    for p in sorted(picks, key=lambda p: (not p.get('es_hoy'),
                                          str(p.get('fecha_cdmx')
                                              or p.get('fecha', '')),
                                          str(p.get('hora_cdmx') or '99:99'))):
        ar = p.get('acierto_real')
        filas.append({
            'Fecha': p.get('fecha_cdmx') or p.get('fecha', ''),
            'Hora (CDMX)': p.get('hora_cdmx') or '—',
            'Franja': _franja(p) or '—',
            'Deporte': p.get('deporte'), 'Liga': p.get('liga'),
            'Partido': p.get('partido'), 'Apuesta': p.get('apuesta'),
            'Dice el modelo': f"{(p.get('prob') or 0):.0%}",
            'Acierta de verdad': f"{ar:.0%}" if ar else 'n/d',
            'Cuota': p.get('cuota'), 'Casa': p.get('casa'),
            'EV': f"{(p.get('ev') or 0):+.1%}",
        })
    st.dataframe(pd.DataFrame(filas), hide_index=True, width='stretch')
    st.caption("Las horas son de **Ciudad de México**. «Franja» agrupa en "
               "bloques de 3 h para armar la combinada con partidos que se "
               "juegan seguidos; «—» es que la casa aún no publicó la hora.")

    # --- combinada por franja horaria --------------------------------------
    porh: dict = {}
    for p in picks:
        f = _franja(p)
        if f:
            porh.setdefault((p.get('fecha_cdmx') or p.get('fecha', ''), f),
                            []).append(p)
    if porh:
        with st.expander(f"🕒 Por franja horaria ({len(porh)} bloques) — "
                         f"para armar la parlay por secciones", expanded=False):
            st.caption("Sólo se listan las franjas con **2 o más** picks: con "
                       "una sola pata no hay combinada que armar. La "
                       "probabilidad conjunta supone independencia, así que es "
                       "un TECHO — dos partidos de la misma liga y hora "
                       "correlacionan y el número real es algo menor.")
            for (fecha, franja), ps in sorted(porh.items()):
                if len(ps) < 2:
                    continue
                # se usa el acierto MEDIDO cuando existe; si no, el del modelo
                probs = [(p.get('acierto_real') or p.get('prob') or 0)
                         for p in ps]
                conjunta = 1.0
                for x in probs:
                    conjunta *= x
                cuota = 1.0
                for p in ps:
                    cuota *= float(p.get('cuota') or 1.0)
                st.markdown(
                    f"**{fecha} · {franja}** — {len(ps)} picks · "
                    f"prob. conjunta ≈ **{conjunta*100:.0f} %** · "
                    f"cuota combinada **{cuota:.2f}**")
                for p in ps:
                    _ar = p.get('acierto_real')
                    st.caption(
                        f"  {p.get('hora_cdmx')} · [{p.get('deporte')}] "
                        f"{p.get('partido')} → **{p.get('apuesta')}** "
                        f"@ {p.get('cuota')} · "
                        + (f"acierta de verdad {_ar:.0%}" if _ar
                           else f"modelo {(p.get('prob') or 0):.0%}"))

    for p in picks:
        if p.get('aviso_calibracion'):
            st.caption(f"· {p.get('partido')} — {p['aviso_calibracion']}")


def _render_combinadas(r) -> None:
    """Combinadas multi-deporte, con su supuesto declarado."""
    combis = r.get('combinadas') or []
    st.caption(
        "Combinadas que cruzan **al menos dos deportes**. No es un capricho: "
        "el riesgo de una combinada es la correlación entre patas, y dos picks "
        "de la misma liga fallan juntos mucho más de lo que sugiere multiplicar "
        "sus probabilidades — comparten contexto y comparten el sesgo del "
        "modelo que los generó. Cruzar deportes rompe esa correlación."
    )
    if not combis:
        if _estilo is not None:
            _pinta(_estilo.vacio(
                "Hoy no se puede cruzar deportes",
                "Hacen falta picks de al menos dos deportes distintos que "
                "superen el mínimo por pata, y hoy no los hay. Mira el estado "
                "del sistema, arriba, para ver qué fuente no ha traído nada.",
                '🧩'))
        else:
            st.info("Hoy no hay material para cruzar deportes: hacen falta "
                    "picks de al menos dos deportes distintos que superen el "
                    "mínimo por pata. Revisa el registro de incidencias.")
        return
    _pinta(_estilo.nota(
        "Una combinada paga más, pero <b>basta con fallar una pata para "
        "perderlo todo</b>: gana menos veces de las que parece. Por eso no se "
        "añaden solas — abajo tienes cuánto arriesgar y la decisión es tuya.",
        'mira', 'Antes de seguir:') if _estilo else None)
    if _estilo is None:
        st.warning("Una combinada paga más, pero **basta con fallar una pata "
                   "para perderlo todo**: gana menos veces de las que parece.")
    for c in combis:
        with st.container(border=True):
            _seccion(f"{c['perfil'].capitalize()}",
                     " + ".join(c['deportes']), 'azul')
            _pinta(_estilo.ticket(c['cuota_total'], c['prob_conjunta'],
                                  _html_esc(c['descripcion']))
                   if _estilo else None)
            if _estilo is None:
                st.markdown(f"### {c['perfil'].capitalize()} · cuota "
                            f"**{c['cuota_total']}** · probabilidad "
                            f"**{c['prob_conjunta']:.1%}**")
                st.caption(c['descripcion'])
            _pinta(_estilo.kpis([
                {'valor': f"{c['ev']:+.1%}", 'etiqueta': 'EV',
                 'tono': 'ok' if c['ev'] > 0 else 'no'},
                {'valor': f"{c['stake_sugerido_pct']:.2f} %",
                 'etiqueta': 'Stake sugerido', 'tono': 'azul',
                 'sub': 'fracción prudente del bankroll'},
                {'valor': len(c['patas']), 'etiqueta': 'Patas',
                 'tono': 'info', 'sub': " + ".join(c['deportes'])},
            ]) if _estilo else None)
            if _estilo is not None:
                _pinta(_estilo.patas([
                    _estilo.pata(
                        p['apuesta'], p['cuota'], p['prob'],
                        f"{p['deporte']} · {p['partido']}",
                        [(str(p['casa']), 'azul')] if p.get('casa') else [],
                        'azul')
                    for p in c['patas']]))
            else:
                st.dataframe(pd.DataFrame([
                    {'Deporte': p['deporte'], 'Partido': p['partido'],
                     'Apuesta': p['apuesta'], 'Prob': f"{p['prob']:.0%}",
                     'Cuota': p['cuota'], 'Casa': p.get('casa')}
                    for p in c['patas']]), hide_index=True, width='stretch')
            st.caption(f"ℹ️ {c['supuesto']}")


def _render_incidencias(r) -> None:
    """
    v91 — «Estado del sistema», ya no «registro de incidencias».

    El registro mezclaba fallos reales con operación normal (el filtro
    anti-CPBL trabajando, Playdoit sin cotizar una liga chica cubierta por
    Pinnacle…) y el usuario veía seis avisos donde todo funcionaba. Ahora
    cada línea trae severidad desde su origen — ✅ operativo · ℹ️ contexto ·
    ⚠️ problema real — y el titular resume: verde si no hay ⚠️.
    """
    inc = r.get('incidencias') or []
    problemas = [i for i in inc if str(i).startswith('⚠️')]
    ok = [i for i in inc if str(i).startswith('✅')]
    info = [i for i in inc if i not in problemas and i not in ok]
    titulo = (f"🩺 Estado del sistema — ⚠️ {len(problemas)} problema"
              f"{'s' if len(problemas) != 1 else ''}" if problemas else
              "🩺 Estado del sistema — ✅ todo operativo")
    with st.expander(titulo, expanded=bool(problemas)):
        if not inc:
            st.success("✅ Barrido completado sin nada que reportar.")
            return
        for i in problemas:
            st.error(i)
        for i in ok:
            st.success(i)
        for i in info:
            st.markdown(f"- {i}")
        if not problemas:
            st.caption("Las líneas ℹ️ son contexto de operación normal, no "
                       "fallos.")


# ===========================================================================
# CARGA DEL MOTOR (una sola vez)
# ===========================================================================
@st.cache_resource(show_spinner="🔮 Cargando el motor de predicción...")
def cargar_motor() -> PredictionEngine:
    return PredictionEngine()


# ===========================================================================
# v86 — UN SOLO BARRIDO A LA VEZ EN TODO EL PROCESO
# ===========================================================================
# El barrido de alpha_finder pica a 1297,7 MB; dos a la vez, a 2172,2 MB
# (_v86_barrido_concurrente.py). La lógica del guardia vive en
# guardia_barrido.py, que es un módulo importado de verdad: app.py re-ejecuta
# ESTE script con runpy en cada rerun, así que un global de aquí no recordaría
# nada entre interacciones.
def barrido_universal(forzar: bool = False) -> dict:
    """Barrido de alpha_finder con garantía de no solaparse consigo mismo."""
    import alpha_finder
    import guardia_barrido
    return guardia_barrido.barrido(alpha_finder.apuestas_del_dia_universal,
                                   forzar=forzar)


@st.cache_data(show_spinner=False)
def prediccion_cacheada(_motor_id: int, home: str, away: str, arbitro: str = None,
                        fase: str = 'grupos', estadio: str = None) -> dict:
    return MOTOR.predecir(home, away, arbitro=arbitro, fase=fase, estadio=estadio)


@st.cache_data(show_spinner="📋 Rellenando la plantilla de análisis...")
def plantilla_cacheada(_motor_id: int, home: str, away: str, arbitro: str = None,
                       fase: str = 'grupos', estadio: str = None) -> dict:
    return MOTOR.plantilla(home, away, arbitro=arbitro, fase=fase, estadio=estadio)


MOTOR = cargar_motor()


# ===========================================================================
# MODO LIGAS DE CLUBES (v12): vista independiente, sin tocar el flujo Mundial
# ===========================================================================
# v86 — TECHO DE MEMORIA. Este caché se indexa POR LIGA y hay 56 disponibles.
# Sin `max_entries` cada liga que alguien abriera quedaba residente para
# siempre. Medido en _v86_memoria.py sobre 12 ligas reales:
#
#     coste medio por motor .......... 59,0 MB
#     RSS con 12 ligas cargadas ..... 847,8 MB
#     proyección a las 56 ligas .... 3445,3 MB
#
# El contenedor gratuito de Streamlit Cloud muere bastante antes de eso. Con un
# usuario el límite se alcanza despacio; con dos navegando ligas distintas se
# alcanza al doble de velocidad, y cuando el contenedor cae se les cae a los
# dos a la vez. Ése es el síntoma de "se cae cuando entran dos personas".
#
# _v86_liberacion.py confirma que el desalojo SÍ devuelve la RAM (71 % del pico,
# 0 de 8 motores retenidos; el resto es fragmentación del asignador), así que
# el tope funciona de verdad y no es cosmético.
#
# 6 motores ~= 494 MB con el proceso base incluido, dejando aire para MLB, NBA,
# tenis y los DataFrames de cuotas. El coste de un desalojo es recargar la liga
# (~3,8 s medidos en liga_mx), que es infinitamente preferible a un OOM.
MAX_LIGAS_EN_MEMORIA = int(os.environ.get('MAX_LIGAS_EN_MEMORIA', '6'))


@st.cache_resource(show_spinner="⚽ Cargando el motor de la liga...",
                   max_entries=MAX_LIGAS_EN_MEMORIA)
def cargar_motor_liga(clave: str):
    from league_engine import ClubEngine
    return ClubEngine(clave)


@st.cache_data(show_spinner="📋 Calculando la plantilla del partido...")
def plantilla_club_cacheada(clave: str, home: str, away: str) -> dict:
    return cargar_motor_liga(clave).plantilla_club(home, away)


# ===========================================================================
# CUOTAS REALES + EV EN LA PLANTILLA (v18/M3)
# ===========================================================================
def _cuota_americana(decimal: float) -> str:
    if decimal >= 2.0:
        return f"+{(decimal - 1) * 100:.0f}"
    return f"-{100 / (decimal - 1):.0f}"


def render_cuotas_reales(pl: dict):
    """Tabla de mercados con cuota REAL vigente y su EV según el modelo."""
    from match_parlay import _cuotas_reales_del_partido
    reales = _cuotas_reales_del_partido(pl)
    st.markdown("#### 💰 Cuotas reales y valor (EV)")
    # v25 (CLV): aviso de frescura — cuotas de hace más de 6 h pierden valor
    try:
        with open('odds_actuales.json', encoding='utf-8') as _f:
            _act = json.load(_f).get('actualizado')
        if _act and pd.Timestamp(_act) < pd.Timestamp.today().normalize():
            st.caption(f"⚠️ Cuotas capturadas el {_act} (más de 6 h): pueden "
                       "haberse movido — el pipeline las refresca a diario.")
    except Exception:
        pass
    if not reales:
        st.caption(
            "Cuotas reales: **N/D** por ahora — sin cuotas vigentes para este "
            "partido en `odds_actuales.json`. En temporada llegan a diario de "
            "fixtures.csv (clubes) y Betexplorer (Mundial, días de partido)."
        )
        return
    filas = []
    for seccion in pl.get('secciones', []):
        for c in seccion.get('campos', []):
            if c.get('tipo') != 'pct' or c['id'] not in reales:
                continue
            prob = float(c['valor']) / 100.0
            cuota = float(reales[c['id']])
            if not (0 < prob < 1) or cuota <= 1:
                continue
            ev = (cuota * prob - 1) * 100
            if ev > 5:
                icono = '🟢 Valor positivo'
            elif ev > 0:
                icono = '🟡 Ligeramente positivo'
            elif ev > -2:
                icono = '⚪ Sin valor'
            else:
                icono = '🔴 Mercado sobrevalora'
            # v19: stake recomendado por ¼ Kelly (solo con EV > 0)
            from bankroll_manager import calcular_stake
            bankroll = float(st.session_state.get('bankroll', 0) or 0)
            k = calcular_stake(prob, cuota, bankroll)
            stake_txt = (f"{k['stake']:.2f} u ({k['pct']*100:.1f} %)"
                         if k['stake'] > 0 else '—')
            filas.append({
                'Mercado': c['etiqueta'],
                'Prob. modelo': f"{prob*100:.1f} %",
                'Cuota real': cuota,
                'Americana': _cuota_americana(cuota),
                'EV': f"{ev:+.1f} %",
                'Valor': icono,
                'Stake ¼ Kelly': stake_txt,
            })
    if filas:
        st.dataframe(pd.DataFrame(filas), width='stretch', hide_index=True)
        from bankroll_manager import AVISO_JUEGO_RESPONSABLE
        st.caption(
            "**EV** = (cuota real × probabilidad del modelo − 1) × 100. "
            "🟢 EV > +5 % · 🟡 0 a +5 % · ⚪ ≈ 0 · 🔴 negativo. "
            "**Stake ¼ Kelly** = fracción del bankroll sugerida (tope 5 %) "
            "solo cuando hay valor. " + AVISO_JUEGO_RESPONSABLE
        )
    else:
        st.caption("Sin mercados con cuota real emparejable en este partido.")


# ===========================================================================
# PANEL DE RENDIMIENTO + SIMULADOR DE BANKROLL (v20)
# ===========================================================================
def render_rendimiento(key: str):
    """ROI simulado por liga (validación con cuotas de cierre) + simulador
    de banca con ¼ Kelly sobre las apuestas históricas persistidas."""
    import json as _json
    import os as _os
    with st.expander("📈 Rendimiento del modelo por liga (ROI simulado)"):
        st.caption(
            "Simulación sobre la VALIDACIÓN de cada liga con cuotas de cierre "
            "reales: 1 unidad al pick del modelo cuando la confianza supera el "
            "70 % o el EV es positivo. Rendimiento pasado ≠ rendimiento futuro."
        )
        filas, grafico = [], []
        for clave, nombre in NOMBRES_LIGAS.items():
            ruta = _os.path.join('modelos', clave, 'metadata.json')
            if not _os.path.exists(ruta):
                continue
            with open(ruta, encoding='utf-8') as f:
                md = _json.load(f)
            r = md.get('roi_sim')
            mesm = md.get('mesm') or {}
            filas.append({
                'Liga': nombre,
                'Modelo': f"{md['precision_validacion']*100:.1f} %",
                'MESM 🧠': (f"{mesm['acc_mesm']*100:.1f} %" if mesm.get('adoptado')
                            else '—'),
                'Mercado': (f"{md['precision_mercado_cuotas']*100:.1f} %"
                            if md.get('precision_mercado_cuotas') else 'N/D'),
                'Apuestas': r['n_apuestas'] if r else 0,
                # v31: string siempre — mezclar int y '—' rompía la
                # serialización Arrow del dataframe ("Conversion failed
                # for column Aciertos")
                'Aciertos': str(r['aciertos']) if r else '—',
                'ROI': f"{r['roi_pct']:+.1f} %" if r else 'N/D',
            })
            grafico.append({'liga': nombre,
                            'Modelo': md['precision_validacion'] * 100,
                            'ELO': (md.get('precision_linea_base_elo') or 0) * 100,
                            'Mercado': (md.get('precision_mercado_cuotas') or 0) * 100})
        if filas:
            st.dataframe(pd.DataFrame(filas), width='stretch', hide_index=True)
            # v22: comparativa visual modelo vs líneas base
            gdf = pd.DataFrame(grafico)
            fig_cmp = go.Figure()
            for serie, color in (('Modelo', '#2ecc71'), ('ELO', '#95a5a6'),
                                 ('Mercado', '#e67e22')):
                vals = gdf[serie].where(gdf[serie] > 0)
                fig_cmp.add_bar(name=serie, x=gdf['liga'], y=vals, marker_color=color)
            fig_cmp.update_layout(barmode='group', height=300,
                                  margin=dict(l=0, r=0, t=25, b=0),
                                  yaxis_title='Precisión 1X2 (%)',
                                  yaxis_range=[40, 62],
                                  legend=dict(orientation='h', y=1.12))
            st.plotly_chart(fig_cmp, width='stretch')
            st.caption("El mercado (cuotas de cierre) solo existe donde hay cuotas "
                       "reales; batirlo de forma sostenida es la vara más alta.")

        # v22: evolución de la precisión por ventanas walk-forward
        if _os.path.exists('wf_panel_v22.json'):
            with open('wf_panel_v22.json', encoding='utf-8') as f:
                wf = _json.load(f)
            ligas_wf = [c for c in wf if wf[c].get('ventanas')]
            if ligas_wf:
                st.markdown("**📉 Evolución walk-forward (ventanas de 6 meses)**")
                liga_wf = st.selectbox(
                    "Liga a inspeccionar", ligas_wf,
                    format_func=lambda c: NOMBRES_LIGAS.get(c, c),
                    key=f"wf_liga_{key}")
                vent = wf[liga_wf]['ventanas']
                etiquetas = [v['ventana'].split(' ')[0] for v in vent]
                fig_wf = go.Figure()
                fig_wf.add_scatter(x=etiquetas, y=[v['precision'] * 100 for v in vent],
                                   mode='lines+markers', name='Modelo',
                                   line=dict(color='#2ecc71'))
                if any(v.get('precision_mercado') for v in vent):
                    fig_wf.add_scatter(
                        x=etiquetas,
                        y=[(v.get('precision_mercado') or None) and
                           v['precision_mercado'] * 100 for v in vent],
                        mode='lines+markers', name='Mercado',
                        line=dict(color='#e67e22', dash='dot'))
                fig_wf.update_layout(height=280, margin=dict(l=0, r=0, t=10, b=0),
                                     yaxis_title='Precisión (%)',
                                     legend=dict(orientation='h', y=1.15))
                st.plotly_chart(fig_wf, width='stretch')
                st.caption("Cada punto es una ventana de validación de 6 meses "
                           "(entrenamiento expansivo, sin fuga). La variación "
                           "entre ventanas es la incertidumbre real del modelo.")

        # ---- simulador de bankroll ----
        st.markdown("**💵 Simulador de bankroll (¼ Kelly, tope 5 %)**")
        ligas_con_bets = [c for c in NOMBRES_LIGAS
                          if _os.path.exists(f'roi_bets_{c}.json')]
        if not ligas_con_bets:
            st.caption("Aún no hay apuestas simuladas persistidas (reentrena las ligas).")
            return
        c1, c2 = st.columns(2)
        with c1:
            liga_sim = st.selectbox("Liga", ligas_con_bets,
                                    format_func=lambda c: NOMBRES_LIGAS[c],
                                    key=f"sim_liga_{key}")
        with c2:
            banca0 = st.number_input("Bankroll inicial", 100.0, 1_000_000.0,
                                     1000.0, step=100.0, key=f"sim_b0_{key}")
        if st.button("Simular", key=f"sim_btn_{key}"):
            from bankroll_manager import calcular_stake, AVISO_JUEGO_RESPONSABLE
            with open(f'roi_bets_{liga_sim}.json', encoding='utf-8') as f:
                bets = _json.load(f)
            banca, serie = float(banca0), []
            for b in bets:
                k = calcular_stake(b['prob'], b['cuota'], banca)
                if k['stake'] <= 0:
                    continue
                banca += k['stake'] * (b['cuota'] - 1) if b['gano'] else -k['stake']
                serie.append({'fecha': b['fecha'], 'banca': round(banca, 2)})
            if not serie:
                st.info("Ninguna apuesta con stake positivo en el histórico de esta liga.")
                return
            df_s = pd.DataFrame(serie)
            fig = go.Figure(go.Scatter(x=df_s['fecha'], y=df_s['banca'],
                                       mode='lines', fill='tozeroy'))
            fig.update_layout(height=260, margin=dict(l=0, r=0, t=10, b=0),
                              yaxis_title='Bankroll')
            st.plotly_chart(fig, width='stretch')
            delta = banca - banca0
            st.metric("Bankroll final", f"{banca:,.2f}",
                      delta=f"{delta:+,.2f} ({delta/banca0*100:+.1f} %)")
            st.caption(f"{len(serie)} apuestas simuladas. {AVISO_JUEGO_RESPONSABLE}")


# ===========================================================================
# COMENTARIO DEL ANALISTA (v22): plantillas desde datos reales del modelo;
# si hay Ollama local, el SLM lo reescribe (marcado como tal).
# ===========================================================================
def render_comentario(pred: dict, home: str, away: str, riesgo: str = 'bajo'):
    try:
        from asistente_comentarios import comentario_partido, mejorar_con_slm
        base = comentario_partido(pred, home, away, riesgo=riesgo)
        if not base:
            return
        slm = mejorar_con_slm(base) if st.session_state.get('usar_slm') else None
        st.info(f"🎙️ **Comentario del analista:** {slm or base}"
                + ("\n\n*↳ reescrito por tu SLM local (Ollama).*" if slm else ""))
    except Exception:
        pass          # el comentario jamás debe tumbar la vista


# ===========================================================================
# HISTORIAL RECIENTE H2H (v21): API-Football para clubes, histórico local
# para el Mundial. Solo consume requests al pulsar el botón (caché 24 h).
# ===========================================================================
def render_panel_equipos(clave: str, home: str, away: str, key: str,
                         prob_modelo: dict = None) -> None:
    """
    v107 — H2H, clasificación y forma del cruce, sin pulsar nada.

    Sustituye en la práctica a `render_h2h_club`, que dependía de API-Football:
    hacía falta una clave, gastaba presupuesto de peticiones, exigía un botón y
    su plan gratuito **se queda en la temporada 2024-25**. Quien no configuraba
    la clave no veía absolutamente nada.

    Esto sale del `historico_<clave>.csv` que el proyecto ya usa para entrenar:
    cubre las 50 competiciones activas, llega más atrás que el plan gratuito de
    la API, es instantáneo y no puede fallar por red. Medido en Liga MX: 26
    cruces de América-Cruz Azul entre 2018 y 2026.
    """
    import panel_equipos as _pe

    st.subheader(f"📊 {home} vs {visitante_txt(away)}")

    @st.cache_data(ttl=3600, show_spinner=False)
    def _resumen(cl, h, a):
        return _pe.resumen(cl, h, a)

    try:
        r = _resumen(clave, home, away)
    except Exception as e:
        st.caption(f"Panel no disponible ahora ({type(e).__name__}).")
        return

    # --- la lectura, primero: es lo que se usa para decidir ------------------
    for frase in _pe.lectura(clave, home, away, prob_modelo):
        st.markdown(f"- {frase}")

    h = r['h2h']
    t1, t2, t3 = st.tabs(['🤝 Cara a cara', '🏆 Clasificación',
                          '📈 Últimos partidos y estadísticas'])

    with t1:
        if not h.get('n'):
            if _estilo is not None:
                _pinta(_estilo.vacio(
                    'Sin cruces en el histórico',
                    h.get('motivo') or '', '🤝'))
            else:
                st.info(h.get('motivo') or 'Sin cruces en el histórico.')
        else:
            _pinta(_estilo.kpis([
                {'valor': h['gana_a'], 'etiqueta': home, 'tono': 'ok',
                 'sub': 'victorias'},
                {'valor': h['empates'], 'etiqueta': 'Empates', 'tono': 'info'},
                {'valor': h['gana_b'], 'etiqueta': away, 'tono': 'azul',
                 'sub': 'victorias'},
                {'valor': h['media_goles'], 'etiqueta': 'Goles por partido',
                 'tono': 'info', 'sub': f"{h['goles_a']}-{h['goles_b']} en total"},
                {'valor': f"{h['pct_ambos_marcan']*100:.0f} %",
                 'etiqueta': 'Ambos marcan', 'tono': 'info'},
            ]) if _estilo else None)
            if _estilo is None:
                c1, c2, c3 = st.columns(3)
                c1.metric(home, h['gana_a'], help='victorias en el historial')
                c2.metric('Empates', h['empates'])
                c3.metric(away, h['gana_b'], help='victorias en el historial')
            st.caption(f"{h['n']} cruces entre {h['desde']} y {h['hasta']}.")

            # v123 — CÓRNERS, TARJETAS Y REMATES DE ESTOS CRUCES.
            #
            # Pedido del usuario mirando esta misma pantalla: «algo que no veo
            # en los cara a cara son estadísticas como tarjetas, córners, etc.»
            # Estaban en el histórico desde siempre —67 de los 74 ficheros las
            # traen, con cobertura del 100 % donde existen— y nadie las leía.
            _ex = h.get('extra') or {}
            if _ex:
                _seccion('Córners, tarjetas y remates de estos cruces',
                         f"{_ex.get('_n_cruces', h['n'])} partidos", 'azul')
                _tar = []
                for _k, _tono in (('corners', 'azul'), ('tarjetas', 'mira'),
                                  ('remates_puerta', 'info'),
                                  ('posesion', 'info'), ('xg', 'info')):
                    _d = _ex.get(_k)
                    if not _d:
                        continue
                    if _k == 'posesion':
                        _tar.append({
                            'valor': f"{_d['media_a']:.0f}-{_d['media_b']:.0f}",
                            'etiqueta': 'Posesión media', 'tono': _tono,
                            'sub': f"{home} · {away}"})
                        continue
                    _tar.append({
                        'valor': _d['media_total'],
                        'etiqueta': _d['etiqueta'].capitalize(), 'tono': _tono,
                        'sub': (f"{_d['media_a']:.1f} · {_d['media_b']:.1f} por "
                                f"equipo" if _d.get('media_a') is not None
                                else f"de {_d['minimo']:.0f} a {_d['maximo']:.0f}")})
                _pinta(_estilo.kpis(_tar) if _estilo else None)

                # el porcentaje histórico por encima de cada línea de mercado,
                # que es lo que se compara con una cuota
                _filas_l = []
                for _k in ('corners', 'tarjetas'):
                    _d = _ex.get(_k)
                    for _L, _p in (_d or {}).get('lineas', {}).items():
                        _filas_l.append([
                            f"Más de {_L} {_d['etiqueta']}",
                            f"{_p*100:.0f} %",
                            f"{round(1/_p, 2) if _p > 0 else '—'}",
                            str(_d['n'])])
                if _filas_l and _estilo is not None:
                    _pinta(_estilo.tabla(
                        ['Línea', 'Se cumplió', 'Cuota mínima que la pagaría',
                         'Partidos'], _filas_l, alineadas=[1, 2, 3]))
                st.caption(
                    f"⚠️ Son **{_ex.get('_n_cruces', h['n'])} partidos**, no una "
                    f"muestra grande: un porcentaje sobre esa cantidad se mueve "
                    f"mucho. Úsalo como contexto del cruce, no como una señal. "
                    f"Y **ninguna de las seis casas del tablón publica precio "
                    f"de córners ni de tarjetas**, así que esto no se puede "
                    f"convertir en una apuesta con cuota real desde aquí.")

            _cols = ['Fecha', 'Local', 'Resultado', 'Visitante', 'Ganó']
            _hay_extra = any(p.get('corners_local') is not None
                             for p in h['partidos'])
            if _hay_extra:
                _cols += ['Córners', 'Tarjetas', 'Remates a puerta']
            st.dataframe(pd.DataFrame([{
                'Fecha': p['fecha'],
                'Local': p['local'],
                'Resultado': f"{p['goles_local']} - {p['goles_visit']}",
                'Visitante': p['visitante'],
                'Ganó': p['ganador'] or 'Empate',
                **({'Córners': (f"{p['corners_local']:.0f}-{p['corners_visit']:.0f}"
                                if p.get('corners_local') is not None else '—'),
                    'Tarjetas': (f"{(p.get('amarillas_local') or 0) + (p.get('rojas_local') or 0):.0f}"
                                 f"-{(p.get('amarillas_visit') or 0) + (p.get('rojas_visit') or 0):.0f}"
                                 if p.get('amarillas_local') is not None else '—'),
                    'Remates a puerta': (f"{p['remates_local']:.0f}-{p['remates_visit']:.0f}"
                                         if p.get('remates_local') is not None else '—')}
                   if _hay_extra else {}),
            } for p in h['partidos']])[_cols], hide_index=True, width='stretch')

    with t2:
        cl = r['clasificacion']
        if not cl:
            st.info('Sin partidos suficientes del torneo en curso.')
        else:
            df = pd.DataFrame([{
                '#': f['pos'], 'Equipo': f['equipo'], 'PJ': f['pj'],
                'G': f['g'], 'E': f['e'], 'P': f['p'],
                'GF': f['gf'], 'GC': f['gc'], 'DG': f['dg'], 'Pts': f['pts'],
            } for f in cl])
            st.dataframe(df, hide_index=True, width='stretch',
                         height=min(38 * (len(df) + 1) + 3, 620))
            st.caption("Calculada del histórico del propio proyecto (3 puntos "
                       "por victoria) sobre el torneo en curso, que se detecta "
                       "por el último parón largo del calendario. No se lee de "
                       "ninguna fuente externa, así que no puede contradecir "
                       "al modelo ni quedarse sin actualizar por su cuenta.")

    with t3:
        # v118 — TODAS LAS COMPETICIONES, NO SÓLO ESTA LIGA.
        #
        # El usuario lo señaló con el caso exacto: «la MLS y la Liga MX juegan
        # el Mundial de Clubes, la Leagues Cup… deben aparecer los partidos de
        # todas las competiciones para determinar desgaste». Y era cierto:
        # Monterrey tiene 316 partidos en el histórico de Liga MX y 330 en el
        # de la Leagues Cup, y aquí sólo se veían los primeros.
        #
        # `forma_global` los junta, quita los duplicados —el mismo partido está
        # en los dos ficheros— y cuenta la carga de 14 y 30 días, que es lo que
        # de verdad dice si un equipo llega fundido.
        import panel_equipos as _pe_g
        for lado, eq, f, cf in (('🏠', home, r['forma_local'], r['casa_fuera_local']),
                                ('✈️', away, r['forma_visitante'],
                                 r['casa_fuera_visitante'])):
            try:
                _fg = _pe_g.forma_global(clave, eq, n=8)
                if _fg.get('n'):
                    f = _fg
            except Exception:
                pass
            if not f.get('n'):
                continue
            _comps = f.get('competiciones') or []
            _carga = ''
            if f.get('partidos_14d') is not None:
                _n14 = f['partidos_14d']
                _sem = '🔴' if _n14 >= 5 else ('🟡' if _n14 >= 4 else '🟢')
                _carga = (f"  \n{_sem} **Desgaste**: {_n14} partidos en 14 días "
                          f"· {f.get('partidos_30d', 0)} en 30")
            # v135 — LA RACHA, EN IMAGEN.
            #
            # Esto decía «últimos 8: `PPEGGEGE`». Para saber si el equipo
            # llega bien había que leer ocho letras y acordarse de cuál era la
            # más reciente; nadie hace eso. `h2h_visual` pinta los cinco
            # últimos como cuadros de color con su letra dentro y el marcador
            # en el tooltip — SVG en línea, sin ninguna librería.
            #
            # El texto NO desaparece: va debajo en una línea, porque un lector
            # de pantalla no ve los cuadros y porque una frase se copia y se
            # pega en un mensaje. Si el módulo falla, se cae al texto de
            # siempre y la ficha sigue entera.
            _pintado_h2h = False
            try:
                import h2h_visual as _hv
                _pinta(_hv.tarjeta_equipo(f"{lado} {eq}", f, '', n=5))
                st.caption(_hv.resumen_texto(eq, f, n=5))
                _pintado_h2h = True
            except Exception as _e_hv:
                logger.debug(f'[h2h] visual omitido: {type(_e_hv).__name__}')
            if not _pintado_h2h:
                st.markdown(
                    f"**{lado} {eq}** — últimos {f['n']}: `{f['racha']}` · "
                    f"{f['pts_por_partido']} pts/partido · "
                    f"{f['gf_media']} goles a favor y {f['gc_media']} en contra")
            st.markdown(
                (f"🏆 Cuenta **{len(_comps)} competiciones**: "
                 f"{', '.join(NOMBRES_LIGAS.get(c, c) for c in _comps)}"
                 if len(_comps) > 1 else '')
                + _carga)
            if cf:
                partes = []
                for donde, d in cf.items():
                    partes.append(f"{donde}: {d['g']}-{d['e']}-{d['p']} en "
                                  f"{d['pj']} PJ ({d['pts_por_partido']} pts/p)")
                st.caption('En el torneo actual · ' + ' · '.join(partes))
            # v114 — LOS ÚLTIMOS PARTIDOS, CON SUS ESTADÍSTICAS.
            #
            # Pedido del usuario: «que haya otra sección que me muestre los
            # partidos más recientes de cada equipo con sus estadísticas,
            # marcador, etc., para evaluar qué conviene elegir». El histórico
            # ya traía tiros, córners, tarjetas y posesión, y la tabla sólo
            # enseñaba el marcador. Cada estadística sale como «propio-rival»
            # para poder leer de un vistazo si el equipo dominó o resistió.
            _filas_f = []
            for p in f['partidos']:
                _fila = {
                    'Fecha': p['fecha'],
                    # v118: de qué competición es cada partido. Sin esto, ver
                    # «Monterrey 2-1 Inter Miami» en la forma de Liga MX
                    # despista: es de la Leagues Cup.
                    'Competición': NOMBRES_LIGAS.get(p.get('competicion'),
                                                     p.get('competicion') or '—'),
                    'Dónde': 'Casa' if p['casa'] else 'Fuera',
                    'Rival': p['rival'],
                    'Marcador': f"{p['goles']} - {p['encajados']}",
                    'Resultado': {'G': 'Ganó', 'E': 'Empató',
                                  'P': 'Perdió'}[p['resultado']],
                }
                for _et, _v in (p.get('stats') or {}).items():
                    _fila[_et] = (f"{_v['propio']:g} - {_v['rival']:g}"
                                  if _v.get('rival') is not None
                                  else f"{_v['propio']:g}")
                _filas_f.append(_fila)
            st.dataframe(pd.DataFrame(_filas_f), hide_index=True,
                         width='stretch')
            if _filas_f and len(_filas_f[0]) <= 5:
                st.caption("Esta competición sólo publica el marcador en su "
                           "histórico; las de football-data con estadística "
                           "completa añaden tiros, córners y tarjetas.")

    st.caption("ℹ️ Esto es información para juzgar, no una señal de apuesta: "
               "el historial y la forma **ya están dentro del modelo** (el ELO "
               "los absorbe partido a partido), así que ver aquí que un equipo "
               "domina no significa que haya valor — lo normal es que la cuota "
               "ya lo refleje.")


def visitante_txt(x: str) -> str:
    """Pequeña ayuda para el encabezado (evita romper si llega vacío)."""
    return str(x or '?')


def render_panel_beisbol(clave: str, home: str, away: str, key: str,
                         nombres: dict = None) -> None:
    """
    v114 — el mismo panel que el fútbol, en MLB y KBO.

    Lo pidió el usuario: «en MLB y tenis también falta la sección de H2H que
    tenga lo mismo que muestra el fútbol pero acomodado a su respectivo
    deporte». Sale del histórico local (26.544 partidos de MLB, 13.009 de KBO),
    así que es instantáneo y no depende de ninguna red ni clave.
    """
    import panel_deportes as _pd
    nombres = nombres or {}

    def _n(x):
        return nombres.get(x, x)

    st.subheader(f"📊 {_n(away)} @ {_n(home)}")

    @st.cache_data(ttl=3600, show_spinner=False)
    def _res(cl, h, a):
        return _pd.resumen_beisbol(cl, h, a)

    try:
        r = _res(clave, home, away)
        for frase in _pd.lectura_beisbol(clave, home, away, nombres):
            st.markdown(f"- {frase}")
    except Exception as e:
        st.caption(f"Panel no disponible ahora ({type(e).__name__}).")
        return

    t1, t2, t3 = st.tabs(['🤝 Serie histórica', '🏆 Clasificación',
                          '📈 Últimos partidos y estadísticas'])
    h = r['h2h']
    with t1:
        if not h.get('n'):
            st.info(h.get('motivo') or 'Sin cruces en el histórico.')
        else:
            c1, c2 = st.columns(2)
            c1.metric(_n(home), h['gana_a'], help='victorias en la serie')
            c2.metric(_n(away), h['gana_b'])
            st.caption(f"{h['n']} partidos entre {h['desde']} y {h['hasta']} · "
                       f"carreras totales {h['goles_a']}-{h['goles_b']} · "
                       f"media {h['media_goles']} por partido")
            st.dataframe(pd.DataFrame([{
                'Fecha': p['fecha'], 'Local': _n(p['local']),
                'Marcador': f"{p['goles_local']} - {p['goles_visit']}",
                'Visitante': _n(p['visitante']),
                'Ganó': _n(p['ganador'] or '—'),
            } for p in h['partidos']]), hide_index=True, width='stretch')
    with t2:
        cl = r['clasificacion']
        if not cl:
            st.info('Sin partidos suficientes de la temporada en curso.')
        else:
            st.dataframe(pd.DataFrame([{
                '#': f['pos'], 'Equipo': _n(f['equipo']), 'PJ': f['pj'],
                'G': f['g'], 'P': f['p'], '%': f"{f['pct']*100:.1f}",
                'CF': f['cf'], 'CC': f['cc'], 'Dif': f['dif'],
            } for f in cl]), hide_index=True, width='stretch',
                height=min(38 * (len(cl) + 1) + 3, 620))
            st.caption("Ordenada por porcentaje de victorias, que es como se "
                       "clasifica el béisbol (no por puntos: los equipos no "
                       "juegan el mismo número de partidos). Calculada del "
                       "histórico del propio proyecto.")
    with t3:
        for lado, eq, f, cf in (('🏠', home, r['forma_local'], r['casa_fuera_local']),
                                ('✈️', away, r['forma_visitante'],
                                 r['casa_fuera_visitante'])):
            if not f.get('n'):
                continue
            st.markdown(f"**{lado} {_n(eq)}** — últimos {f['n']}: "
                        f"`{f['racha']}` · {f['gf_media']} carreras a favor y "
                        f"{f['gc_media']} en contra")
            if cf:
                st.caption('En la temporada · ' + ' · '.join(
                    f"{donde}: {d['g']}-{d['p']} en {d['pj']} PJ"
                    for donde, d in cf.items()))
            st.dataframe(pd.DataFrame([{
                'Fecha': p['fecha'],
                'Dónde': 'Casa' if p['casa'] else 'Fuera',
                'Rival': _n(p['rival']),
                'Marcador': f"{p['goles']} - {p['encajados']}",
                'Resultado': {'G': 'Ganó', 'E': '—', 'P': 'Perdió'}[p['resultado']],
            } for p in f['partidos']]), hide_index=True, width='stretch')

    st.caption("ℹ️ Información para juzgar, no una señal de apuesta: el "
               "historial y la forma **ya están dentro del modelo**, así que "
               "ver aquí que un equipo domina no significa que haya valor.")


def render_panel_tenis(engine, p1: str, p2: str, superficie: str,
                       key: str) -> None:
    """
    v114 — el equivalente del panel de equipos para tenis.

    En tenis no hay local, ni tabla, ni temporada regular, así que cada bloque
    se traduce a lo que sí significa algo: el balance del cara a cara, el
    ranking y el **ELO por superficie** (que es lo que de verdad ordena a dos
    tenistas en un partido concreto) y la forma con la carga reciente.
    """
    import panel_deportes as _pd

    st.subheader(f"📊 {p1} vs {p2}")
    try:
        for frase in _pd.lectura_tenis(engine, p1, p2, superficie):
            st.markdown(f"- {frase}")
    except Exception as e:
        st.caption(f"Panel no disponible ahora ({type(e).__name__}).")
        return

    t1, t2, t3 = st.tabs(['🤝 Cara a cara', '🏆 Ranking y ELO',
                          '📈 Últimos partidos'])
    with t1:
        h = _pd.h2h_tenis(engine, p1, p2)
        if h.get('balance') is not None:
            b = int(h['balance'])
            st.metric("Balance histórico",
                      f"{p1 if b >= 0 else p2} +{abs(b)}" if b else "Igualado",
                      help="Diferencia de victorias en todo el histórico del "
                           "motor, que cubre 259.443 parejas de jugadores.")

        # v123 — CUÁNTOS JUEGOS DURAN SUS PARTIDOS.
        #
        # Pedido del usuario: «en tenis ver en los h2h o en las demás stats
        # históricas ver cuántos juegos se jugaron para irte por ahí en la
        # apuesta». El dato estaba en el histórico unificado (la columna
        # `Score`, con cobertura del 100 % sobre 354.250 partidos del ATP) y
        # nadie lo leía. `tenis_juegos` lo precalcula fuera de la interfaz.
        try:
            import tenis_juegos as _tj
            _circ = 'wta' if 'wta' in str(getattr(engine, 'circuito', '')).lower() \
                else 'atp'
            # El formato importa mucho: al mejor de 5 la línea de juegos vive
            # unos diez juegos más arriba, así que mezclarlos daría una media
            # que no corresponde a ningún partido. Esta vista no sabe de qué
            # torneo es el partido, así que se ofrece el interruptor en vez de
            # adivinar — y por defecto va el mejor de 3, que es el 95 % del
            # circuito.
            _bo = 5 if st.toggle(
                "Grand Slam masculino (al mejor de 5 sets)", value=False,
                key=f'tj_bo5_{key}',
                help="Cámbialo si este partido es de cuadro masculino de "
                     "Grand Slam: ahí se juega al mejor de 5 y las líneas de "
                     "juegos son otras.") else 3
            _jg = _tj.linea_sugerida(_circ, p1, p2, _bo)
        except Exception:
            _jg = None
        if _jg:
            _seccion('Juegos por partido',
                     f"al mejor de {_jg['best_of']} sets", 'azul')
            _tar_j = [
                {'valor': _jg['media_estimada'], 'etiqueta': 'Media esperada',
                 'tono': 'azul',
                 'sub': 'promedio de los dos jugadores'},
            ]
            for _n_j, _p_j in ((p1, _jg.get('perfil_1')),
                               (p2, _jg.get('perfil_2'))):
                if _p_j:
                    _tar_j.append({
                        'valor': _p_j['media'], 'etiqueta': _n_j, 'tono': 'info',
                        'sub': f"{_p_j['n']} partidos · ±{_p_j['sd']:.1f}"})
            if _jg.get('h2h'):
                _tar_j.append({
                    'valor': _jg['h2h']['media'], 'etiqueta': 'Entre ellos',
                    'tono': 'ok',
                    'sub': f"{_jg['h2h']['n']} cruces al mejor de {_bo}"})
            _pinta(_estilo.kpis(_tar_j) if _estilo else None)
            if _jg.get('over') and _estilo is not None:
                _pinta(_estilo.tabla(
                    ['Línea de juegos', 'Se pasó', 'Cuota mínima que la pagaría'],
                    [[f"Más de {_L}", f"{_p*100:.0f} %",
                      f"{round(1/_p, 2) if _p > 0 else '—'}"]
                     for _L, _p in sorted(_jg['over'].items(),
                                          key=lambda x: float(x[0]))],
                    alineadas=[1, 2]))
            st.caption(
                ("⚠️ **Muestra corta** en al menos uno de los dos: la media se "
                 "mueve mucho. " if _jg.get('muestra_corta') else "")
                + "La media esperada es el promedio de las dos medias "
                  "individuales, **no una predicción del modelo**: es "
                  "histórico, y se enseña para compararlo con la línea que "
                  "publique tu casa. Los cruces entre ellos van aparte y sólo "
                  "aparecen si se han visto dos o más veces en este formato — "
                  "con un solo precedente no hay media que dar.")

        if h.get('partidos'):
            st.dataframe(pd.DataFrame([{
                'Fecha': p['fecha'], 'Torneo': p['torneo'],
                'Ganó': p['ganador'], 'Sets': p['sets'],
                'Juegos': p['juegos'],
            } for p in h['partidos']]), hide_index=True, width='stretch')
            st.caption(f"{h['n']} cruces con detalle. El balance de arriba "
                       f"puede cubrir más partidos que esta tabla: sale del "
                       f"histórico completo del motor y aquí sólo se listan "
                       f"los que además tienen marcador registrado.")
        elif h.get('balance') is None:
            st.info(h.get('motivo') or 'Sin cruces previos.')
    with t2:
        filas = []
        for j in (p1, p2):
            p = _pd.perfil_tenista(engine, j)
            # v123 — «Puntos» va como TEXTO, igual que sus vecinas.
            #
            # Era la única columna que salía sin formatear, así que cuando un
            # jugador tenía puntos (un número) y el otro no («—»), la columna
            # mezclaba tipos y Arrow no la podía convertir:
            #
            #   ArrowInvalid: Could not convert '—' with type str:
            #   tried to convert to double  ·  columna «Puntos»
            #
            # `st.dataframe` lanzaba, el `try` del llamador lo recogía y la
            # pestaña de ranking y ELO **desaparecía entera** con un
            # «Panel de jugadores no disponible (ArrowInvalid)». Lo cazó
            # `smoke_botones.py`, que es exactamente para lo que está.
            fila = {'Jugador': j,
                    'Ranking': (f"{p['rank']:.0f}" if p.get('rank') else '—'),
                    'Puntos': (f"{p['puntos']:.0f}"
                               if isinstance(p.get('puntos'), (int, float))
                               else (str(p['puntos']) if p.get('puntos')
                                     else '—')),
                    'ELO': (f"{p['elo']:.0f}" if p.get('elo') else '—')}
            for sup in ('hard', 'clay', 'grass'):
                v = (p.get('elo_superficie') or {}).get(sup)
                fila[f'ELO {sup}'] = f"{v:.0f}" if v else '—'
            filas.append(fila)
        st.dataframe(pd.DataFrame(filas), hide_index=True, width='stretch')
        st.caption("El ELO por superficie es el que manda en un partido "
                   "concreto: el general mezcla resultados de tierra y de "
                   "pista rápida, que no se transfieren.")
    with t3:
        for j in (p1, p2):
            p = _pd.perfil_tenista(engine, j)
            st.markdown(
                f"**{j}** — racha `{p['racha'] or '—'}` · "
                f"{p['ganados_recientes']}/{p['jugados_recientes']} recientes · "
                f"{p.get('partidos_14d') or 0} partidos en 14 días · "
                f"{p.get('horas_7d') or 0:.1f} h en pista en 7 días")
            det = _pd.forma_tenis(j)
            if det:
                st.dataframe(pd.DataFrame([{
                    'Fecha': d['fecha'], 'Torneo': d['torneo'],
                    'Rival': d['rival'], 'Resultado': d['resultado'],
                    'Sets': d['sets'],
                } for d in det]), hide_index=True, width='stretch')
            elif p.get('ultimo_partido'):
                st.caption(f"Último partido registrado: {p['ultimo_partido']}. "
                           f"El detalle partido a partido sólo existe para los "
                           f"cruces recientes de ESPN.")

    st.caption("ℹ️ Información para juzgar, no una señal de apuesta: el ELO ya "
               "absorbe historial, forma y fatiga.")


def render_h2h_club(clave: str, home: str, away: str, key: str):
    with st.expander(f"📜 Historial reciente — {home} vs {away}"):
        import api_football_manager as afm
        if not afm.api_key():
            st.caption("Configura API_FOOTBALL_KEY (Settings → Secrets en "
                       "Streamlit Cloud) para consultar el historial de cruces.")
            return
        st.caption(f"Fuente: API-Football (plan Free: hasta la temporada "
                   f"2024-25) · Requests restantes hoy: {afm.requests_restantes()}")
        if st.button("📜 Consultar últimos cruces", key=f"h2h_btn_{key}"):
            import backfill_stats as bs
            with st.spinner("Buscando cruces..."):
                if clave == 'champions' and os.path.exists('historico_champions.csv'):
                    hc = pd.read_csv('historico_champions.csv')
                    ids = {}
                    for lado in ('home', 'away'):
                        ids.update(dict(zip(hc[f'{lado}_team'], hc[f'api_{lado}_id'])))
                    id_h, id_a = ids.get(home), ids.get(away)
                else:
                    id_h = bs.id_equipo(clave, home)
                    id_a = bs.id_equipo(clave, away)
                cruces = bs.h2h(int(id_h), int(id_a)) if id_h and id_a else []
            if not cruces:
                st.info("Sin cruces disponibles (equipos no mapeados a la API o "
                        "sin presupuesto de requests hoy).")
                return
            st.dataframe(pd.DataFrame([{
                'Fecha': c['fecha'], 'Competición': c['competicion'],
                'Partido': f"{c['local']} {c['goles_local']}-{c['goles_visitante']} "
                           f"{c['visitante']}",
            } for c in cruces]), width='stretch', hide_index=True)


def render_h2h_mundial(home: str, away: str):
    """H2H del Mundial desde el histórico local de Kaggle — gratis y completo."""
    with st.expander(f"📜 Historial reciente — {home} vs {away}"):
        try:
            h = pd.read_csv('historico_partidos.csv',
                            usecols=['date', 'home_team', 'away_team',
                                     'home_goals', 'away_goals', 'tournament'])
        except Exception:
            st.caption("Histórico no disponible.")
            return
        par = h[((h['home_team'] == home) & (h['away_team'] == away)) |
                ((h['home_team'] == away) & (h['away_team'] == home))]
        par = par.sort_values('date', ascending=False).head(5)
        if par.empty:
            st.caption("Estas selecciones no se han enfrentado en el histórico (1990-).")
            return
        st.dataframe(pd.DataFrame([{
            'Fecha': str(r['date'])[:10], 'Competición': r['tournament'],
            'Partido': f"{r['home_team']} {r['home_goals']:.0f}-{r['away_goals']:.0f} "
                       f"{r['away_team']}",
        } for _, r in par.iterrows()]), width='stretch', hide_index=True)


# ===========================================================================
# ASISTENTE DE PARLAY POR PARTIDO (v15): agnóstico de competición
# ===========================================================================
def render_remates_partido(clave: str, home: str, away: str, key: str):
    """
    v163 — LOS REMATES DEL PARTIDO: por equipo y por jugador.

    Dos cosas distintas, una debajo de la otra:

      · **por equipo** — remates totales y a puerta, del partido y de cada
        lado, con su línea y su probabilidad. Sale de
        `rendimiento_equipos.remates_equipo`, calibrado en la §13 de la
        bitácora (error 0,0131 en totales y 0,0129 a puerta donde hay datos
        observados; 0,0281 y 0,0168 donde va estimado).

      · **por jugador** — quién tira, con el once probable de FotMob cuando lo
        hay. Aquí SÍ se piden los últimos partidos a ESPN (`en_vivo=True`),
        que es lo que no cabe en la tarjeta de «Apuestas del Día»: la ficha se
        abre de una en una y el gasto es de una decena de peticiones, ya
        cacheadas seis horas en disco por `remates_jugadores`.

    LO QUE NO SE PROMETE, Y ESTÁ MEDIDO. Cuánto remata un jugador calibra
    (ECE 0,029 en «al menos un remate»). Si va a jugar, no: la frecuencia de
    titularidad da ECE de 0,057 a 0,073, por encima del umbral de 0,05 del
    proyecto. Por eso el bloque dice siempre de dónde sale el once, y cuando no
    hay, lo dice también en vez de ordenar la lista y callarse.
    """
    st.divider()
    st.subheader("🎯 Remates del partido")

    try:
        import rendimiento_equipos as _rq
        eq = _rq.remates_equipo(clave, home, away)
    except Exception as e:
        st.caption(f"No disponible: {type(e).__name__}")
        return
    if not eq:
        st.info("Esta competición no tiene ni goles con los que situar su "
                "nivel de remates, así que no hay nada honesto que enseñar "
                "aquí.")
        return

    import modo_modelo as _mm
    filas = []
    for nombre, titulo in (('totales', 'Remates'), ('a_puerta', 'A puerta')):
        bloque = eq.get(nombre)
        if not bloque:
            continue
        pintado = _mm._filas_de(bloque, '🎯', nombre)
        if not pintado:
            continue
        for f in pintado['filas']:
            etq = {'Total': 'Partido', 'Local': home, 'Visita': away}.get(
                f['etiqueta'], f['etiqueta'])
            filas.append({'Mercado': titulo, 'Quién': etq,
                          'Esperados': round(f['media'], 2),
                          'Apuesta': f['texto'],
                          'Probabilidad': f"{f['prob']*100:.0f} %"})
    if filas:
        st.dataframe(pd.DataFrame(filas), hide_index=True, width='stretch')
        origen = (eq.get('totales') or {}).get('origen') or 'observado'
        if origen == 'estimado':
            err = (eq.get('totales') or {}).get('error_calibracion')
            st.caption(
                "📐 **Estimado** · esta competición no publica remates "
                "observados: el nivel sale de sus goles y es igual para todos "
                "sus partidos, así que no distingue a un equipo de otro. Su "
                f"error de calibración medido dejando la liga fuera es "
                f"{err:.4f}, por debajo del umbral de 0,05 que se fijó como "
                "aceptable.".replace('.', ','))
        else:
            st.caption(
                "Remates observados de esta competición. El error de "
                "calibración medido es 0,0131 en remates totales y 0,0129 a "
                "puerta. Es una probabilidad bien calibrada, **no** una "
                "ventaja de precio: no hay histórico de líneas de remates con "
                "el que medir un percentil 5.")

    # ---- por jugador --------------------------------------------------------
    @st.cache_data(ttl=3600, show_spinner="Buscando quién remata…")
    def _por_jugador(c: str, h: str, a: str):
        import remates_jugador as _rjg
        return _rjg.partido(c, h, a, en_vivo=True)

    try:
        qr = _por_jugador(clave, home, away)
    except Exception as e:
        st.caption(f"Jugadores no disponibles: {type(e).__name__}")
        return
    if not qr:
        return
    al = qr.get('alineacion') or {}
    if al.get('aviso'):
        formaciones = ' · '.join(
            x for x in (al.get('home_formacion'), al.get('away_formacion')) if x)
        st.markdown(f"**{al['aviso']}**"
                    + (f" ({formaciones})" if formaciones else ""))
        # Si el once no se ha podido casar entero con la estadistica de ESPN,
        # se dice. Una tabla de seis nombres bajo el rotulo «alineacion
        # probable» afirma que el once son esos seis, y no lo es. Medido: casan
        # 88 de 132 nombres (67 %), y solo el 2 % es un fallo del emparejador —
        # el resto son fichajes que ESPN aun no tiene y jugadores con menos de
        # dos partidos.
        _falt = [qr.get(l + '_casados_de') for l in ('home', 'away')]
        _falt = [c for c in _falt if c and c[0] < c[1]]
        if _falt:
            st.caption(
                "De la alineación se han encontrado con estadística "
                + " y ".join(f"**{a} de {b}**" for a, b in _falt)
                + " jugadores. Los que faltan no están en los últimos "
                "partidos que publica ESPN — suelen ser fichajes recientes o "
                "jugadores con muy pocos minutos.")
    else:
        st.warning(
            "**Todavía no hay alineación publicada.** Lo de abajo son los "
            "jugadores del plantel ordenados por su probabilidad de rematar "
            "SI JUEGAN, no una predicción de quién sale de inicio. Estimar "
            "eso con la frecuencia de titularidad calibra a 0,057-0,073, por "
            "encima del umbral aceptable del proyecto, así que no se hace.")

    cols = st.columns(2)
    for col, lado, nombre_eq in ((cols[0], 'home', home), (cols[1], 'away', away)):
        with col:
            st.markdown(f"**{nombre_eq}**")
            js = qr.get(lado + '_jugadores') or []
            if not js:
                st.caption("Sin estadística por jugador de este equipo. Puede "
                           "ser que ESPN no cubra la competición, que nos "
                           "esté devolviendo 403, o que el equipo no haya "
                           "jugado en la ventana consultada.")
                continue
            tabla = pd.DataFrame([{
                'Jugador': (j.get('jugador') or '')
                           + (' *' if j.get('muestra_corta') else ''),
                'Pos': j.get('posicion'),
                'PJ': int(j.get('apariciones') or 0),
                'Rem. esperados': j.get('lambda_tot'),
                # v164 — LA LÍNEA DE LA CASA Y SU PROBABILIDAD.
                #
                # Playdoit cotiza «Remates - <Jugador> (<COD>)» y «Remates a
                # Puerta - …» con tres líneas cada una; se enseña la principal
                # y la probabilidad del modelo para ESA línea, que es la que el
                # usuario va a ver en el boleto.
                #
                # Cuando la casa no cotiza a ese jugador se escribe «línea no
                # disponible», NO un 0 %: son cosas distintas y confundirlas
                # sería afirmar algo que nadie ha dicho. La casa ofrece unos 40
                # jugadores por partido y ESPN devuelve ~55, así que pasa a
                # menudo y no es un fallo.
                'Línea casa': (f"+{j['linea_tot']:.1f}"
                               if j.get('linea_tot') is not None
                               else 'no disponible'),
                'Prob. línea': (f"{j['p_linea_tot']*100:.0f} %"
                                if j.get('p_linea_tot') is not None else '—'),
                'Línea a puerta': (f"+{j['linea_on']:.1f}"
                                   if j.get('linea_on') is not None
                                   else 'no disponible'),
                'Prob. a puerta': (f"{j['p_linea_on']*100:.0f} %"
                                   if j.get('p_linea_on') is not None else '—'),
                '≥1 remate': (f"{j['p_remata']*100:.0f} %"
                              if j.get('p_remata') is not None else '—'),
                '≥1 a puerta': (f"{j['p_al_arco']*100:.0f} %"
                                if j.get('p_al_arco') is not None else '—'),
                # Titularidades OBSERVADAS, no una probabilidad de jugar.
                # Se escribe «8/10» y no «80 %» a proposito: convertir esto en
                # un porcentaje seria presentarlo como prediccion, y como
                # prediccion calibra a 0,057-0,073 de ECE, por encima del
                # umbral de 0,05. Como dato de cuantas veces salio de inicio
                # es exacto y sirve para leer la tabla.
                'Titular': (f"{int(j['titularidades'])}/{int(j['apariciones'])}"
                            if j.get('titularidades') is not None else '—'),
            } for j in js])
            st.dataframe(tabla, hide_index=True, width='stretch')
    pie = ("Los remates esperados de cada jugador se encogen hacia la media de "
           "su posición según su muestra (K=6 en totales, K=12 a puerta): con "
           "cuatro a diez partidos, su media suelta es un tercio de ruido. "
           "Medido sobre 6.688 titulares-partido, encoger baja el error de "
           "calibración por deciles de 0,056 a 0,029 y encima sube la "
           "correlación. **Prob. línea** es la probabilidad del modelo para la "
           "línea que cotiza la casa; «no disponible» significa que la casa no "
           "cotiza a ese jugador, que no es lo mismo que un 0 %.")
    if any(j.get('muestra_corta') for j in
           (qr.get('home_jugadores') or []) + (qr.get('away_jugadores') or [])):
        pie += (" El asterisco marca a quien lleva menos de cuatro partidos: "
                "por debajo de ahí no hay medición y su número es casi entero "
                "la media de su puesto.")
    st.caption(pie)


def render_remates_reales(lados: list, key: str):
    """
    v67 — Remates y remates a puerta REALES **por jugador**.

    `lados` = [(etiqueta, callable_que_devuelve_df), ...]. El callable se
    resuelve dentro de un `st.cache_data` para no repetir las llamadas a ESPN.

    Antes de v67 esta información era un ESTIMADO derivado de los goles
    (goles × calibración StatsBomb) y solo aparecían jugadores que habían
    marcado. Ahora son remates observados partido a partido, así que también
    salen los que rematan mucho y no anotan — que es justo lo que sirve para
    el mercado de remates.
    """
    st.divider()
    st.subheader("🎯 Remates por jugador (datos reales)")
    # v107 — SI ESTA COMPETICIÓN NO LA CUBRE ESPN, SE DICE UNA VEZ Y CLARO.
    #
    # Antes salía una tabla vacía con un «no disponible» junto a cada equipo,
    # que es indistinguible de un fallo de red o de un equipo mal mapeado.
    # Medido sobre las 49 activas: 41 tienen estadística por jugador y 8 no
    # (ver `remates_jugadores.cobertura`).
    try:
        import remates_jugadores as _rjc
        _hay = _rjc.hay_remates(key)
        if _hay is False:
            st.info(
                "ESPN **no publica estadística por jugador** de esta "
                "competición — no es un fallo ni le falta nada a tu "
                "conexión. Está medido pidiendo tres "
                "equipos de cada una: de las 49 competiciones activas la "
                "cubre en **44**. Los remates por EQUIPO sí están en el "
                "análisis del partido.")
            return
    except Exception:
        pass
    cols = st.columns(len(lados))
    hubo = False
    for col, (etiqueta, obtener) in zip(cols, lados):
        with col:
            st.markdown(f"**{etiqueta}**")
            try:
                df = obtener()
            except Exception as e:
                st.caption(f"No disponible: {type(e).__name__}")
                continue
            if df is None or df.empty:
                # v121 — DECIR POR QUÉ FALTA, Y QUE SEA VERDAD.
                #
                # Este mensaje decía «ESPN no publica estadística por jugador».
                # Es falso: la publica —en local salen 36 jugadores de
                # Monterrey, 32 de Chivas, 34 de Santos— pero devuelve **403 a
                # las IPs de centro de datos**, que es donde corre la app. El
                # usuario lo reportó tres veces buscando un dato que sí existe.
                _bloqueo = False
                try:
                    import remates_jugadores as _rj_b
                    _bloqueo = _rj_b.espn_nos_bloquea()
                except Exception:
                    pass
                if _bloqueo:
                    st.caption(
                        "🚫 ESPN **sí publica** esta estadística, pero está "
                        "bloqueando las peticiones desde el servidor donde "
                        "corre la app (responde 403 a las IPs de centro de "
                        "datos). No falta el dato: falta el acceso. En una "
                        "ejecución local sí aparece.")
                else:
                    st.caption(
                        "Sin estadística por jugador para los últimos "
                        "partidos de este equipo. Puede ser que no haya "
                        "jugado en la ventana consultada.")
                continue
            hubo = True
            muestra = int(df['n_partidos_muestra'].iloc[0]) if 'n_partidos_muestra' in df else None
            vista = df.head(12).copy()
            tabla = pd.DataFrame({
                'Jugador': vista['jugador'],
                'Pos': vista['posicion'],
                'PJ': vista['partidos'],
                'Remates': vista['remates'],
                'Rem/PJ': vista['remates_pp'],
                'A puerta': vista['al_arco'],
                'AP/PJ': vista['al_arco_pp'],
                'Puntería': (vista['punteria'] * 100).round(0).map(
                    lambda v: f"{v:.0f} %" if pd.notna(v) else '—'),
                'Goles': vista['goles'],
            })
            st.dataframe(tabla, hide_index=True, width='stretch')
            if muestra:
                st.caption(f"Últimos {muestra} partidos.")
    if hubo:
        st.caption("Fuente: estadística por jugador de ESPN, partido a partido. "
                   "«Rem/PJ» y «AP/PJ» son las medias que se comparan con la "
                   "línea de la casa en los mercados de remates.")


def render_comparador(motor, equipos: list, key: str):
    """v25 (§2.4): comparación rápida de DOS partidos lado a lado."""
    with st.expander("🆚 Comparador rápido de dos partidos"):
        cols = st.columns(2)
        preds = []
        for i, col in enumerate(cols):
            with col:
                st.markdown(f"**Partido {'A' if i == 0 else 'B'}**")
                h = st.selectbox("Local", equipos, index=min(i * 2, len(equipos) - 2),
                                 key=f'cmp_h{i}_{key}')
                a = st.selectbox("Visitante", equipos,
                                 index=min(i * 2 + 1, len(equipos) - 1),
                                 key=f'cmp_a{i}_{key}')
                if h == a:
                    st.warning("Elige equipos distintos.")
                    preds.append(None)
                    continue
                try:
                    preds.append(motor.predecir(h, a))
                except Exception as e:
                    st.error(f"No se pudo predecir: {e}")
                    preds.append(None)
        if all(p and 'error' not in p for p in preds):
            filas = []
            for p in preds:
                pr = p['prediction']
                filas.append({
                    'Partido': p.get('match', ''),
                    'Favorito': f"{pr['winner']} ({pr['confidence']*100:.0f} %)",
                    '1X2': (f"{pr['probabilities']['home']*100:.0f} / "
                            f"{pr['probabilities']['draw']*100:.0f} / "
                            f"{pr['probabilities']['away']*100:.0f} %"),
                    'Marcador probable': pr['most_likely_score'],
                    'Goles esperados': f"{pr['total_goals_expected']:.2f}",
                })
            st.dataframe(pd.DataFrame(filas), width='stretch',
                         hide_index=True)
            confs = [p['prediction']['confidence'] for p in preds]
            mas = 'A' if confs[0] >= confs[1] else 'B'
            st.caption(f"El modelo ve más claro el partido **{mas}** "
                       f"({max(confs)*100:.0f} % vs {min(confs)*100:.0f} % "
                       "de confianza en el favorito).")


def selector_proximos(deporte: str, catalogo, key_home: str, key_away: str,
                      etiqueta: str, mapear=None) -> None:
    """v59: selector de PRÓXIMOS PARTIDOS reutilizable para cualquier deporte
    (MLB, NBA...). Se alimenta del scoreboard de ESPN (se refresca solo: caché
    de 30 min) y autorrellena los selectores de equipos al pulsar «Cargar».

    `mapear` traduce el nombre de ESPN al identificador del motor (p. ej.
    `codigo_mlb`); si es None se usa name_mapper contra `catalogo`."""
    try:
        import fixtures_espn
        fx = fixtures_espn.fixtures_deporte(deporte)
    except Exception:
        fx = []
    if not fx:
        st.caption(f"📅 Sin partidos programados de {etiqueta} en las próximas "
                   "48 h (fuera de temporada o sin datos).")
        return
    # v91 — misma política que en las ligas de fútbol: se enseña la SEMANA
    # completa ordenada por fecha (el más próximo primero) y lo que aún no
    # cotiza se marca «· sin cuota aún» en vez de esconderse.
    _con = set()
    try:
        import fixtures_espn as _fe
        _sel = _fe.con_cuota(fx)
        _con = {id(f) for f in (_sel['apostables'] or [])}
        if _sel['sin_cuota']:
            st.caption(f"ℹ️ {len(_sel['apostables'])} partidos con cuota "
                       f"abierta · {len(_sel['sin_cuota'])} aún sin precio "
                       f"(las casas publican 2-4 días antes).")
    except Exception:
        pass
    fx = sorted(fx, key=lambda f: (str(f.get('fecha', '')),
                                   str(f.get('inicio', ''))))
    cat = list(catalogo)
    ops = {}
    etiquetas = {}          # clave estable → texto que se pinta (v123)
    for f in fx:
        try:
            if mapear:
                h, a = mapear(f['home']), mapear(f['away'])
            else:
                import name_mapper as _nm
                h = _nm.mapear(f['home'], cat, contexto=f'ui→{deporte}')
                a = _nm.mapear(f['away'], cat, contexto=f'ui→{deporte}')
        except Exception:
            continue
        if h in cat and a in cat and h != a:
            # v106 — el selector dice la HORA de CDMX, no sólo el día. Con
            # varios partidos el mismo día, «2026-08-08 · A @ B» no permitía
            # distinguir cuál empieza antes, que es lo que decide si te da
            # tiempo a apostarlo. La fecha que se enseña es la LOCAL: un
            # partido de las 01:00 UTC del sábado es del viernes en México.
            _p = _horario.partes(f.get('inicio'))
            _cuando = f"{_p[0]} {_p[1]}" if _p else str(f.get('fecha', ''))
            # v123 — LA ETIQUETA NO PUEDE SER LA IDENTIDAD DE LA OPCIÓN.
            #
            # «· sin cuota aún» depende de si las casas han abierto línea, o
            # sea que cambia entre una recarga y la siguiente. Como la etiqueta
            # era además la CLAVE de la opción, al pulsar «🔄 Actualizar» el
            # valor guardado en la sesión dejaba de existir en la lista nueva y
            # Streamlit reventaba la vista entera:
            #
            #   ValueError: '2026-08-12 11:40 · Baltimore Orioles @ Minnesota
            #   Twins' is not in list
            #
            # Lo cazó `smoke_botones.py` pulsando ese botón en MLB. Ahora la
            # clave es estable —la pareja de equipos y la hora— y lo volátil
            # vive sólo en el texto que se pinta (`format_func`), que puede
            # cambiar todo lo que quiera sin invalidar la selección.
            _clave = f"{_cuando}|{f['away']}|{f['home']}"
            _etq = f"{_cuando} · {f['away']} @ {f['home']}"
            if _con and id(f) not in _con:
                _etq += "  · sin cuota aún"
            ops[_clave] = (h, a)
            etiquetas[_clave] = _etq
    if not ops:
        st.caption(f"📅 {len(fx)} partidos de {etiqueta} encontrados, pero sus "
                   "equipos no coinciden con los del modelo.")
        return
    # v71: sin botón «Cargar». Elegir el partido YA carga los equipos y sus
    # estadísticas; el botón era un paso manual que no decidía nada.
    def _cargar_dep():
        elegido = st.session_state.get(f"fxd_sel_{deporte}")
        par = ops.get(elegido)
        if par:
            st.session_state[key_home], st.session_state[key_away] = par

    _olvidar_seleccion_muerta(f"fxd_sel_{deporte}", ops)
    sel = st.selectbox(f"📅 Próximos partidos de {etiqueta} ({len(ops)})",
                       list(ops.keys()), key=f"fxd_sel_{deporte}",
                       format_func=lambda k: etiquetas.get(k, k),
                       on_change=_cargar_dep,
                       help="Al elegir un partido se cargan sus datos solos.")
    # primera carga: dejar el estado coherente con lo que muestra el selector
    if key_home not in st.session_state and sel in ops:
        st.session_state[key_home], st.session_state[key_away] = ops[sel]


def _mostrar_cuotas_multi(clave_liga: str, home: str, away: str,
                          deporte: str = 'futbol',
                          plantilla: dict = None, fecha=None) -> bool:
    """
    v71 — cuotas del partido desde TODAS las fuentes sin cuota de API
    (Pinnacle + ESPN), con line shopping.

    Es el respaldo de `cuotas_auto` (que depende del core de ESPN y solo cubre
    algunas ligas). Si tampoco hay nada, lo dice con el motivo real en vez de
    dejar un «sin cuota» sin explicación.

    v114 — con `plantilla` deja de ser un respaldo pobre: cruza TODO el tablón
    con el modelo y enseña los mismos mercados que la vía de ESPN, al mejor
    precio de las seis casas. `fecha` desambigua el emparejamiento.
    """
    try:
        import cuotas_multi as _cm
    except Exception:
        return False
    try:
        # v127 — `liga` NO es opcional aquí, aunque lo parezca.
        #
        # `cuotas_partido` la usa para dos cosas: la guardia de categoría del
        # emparejador (femenino/filial) y, desde esta versión, para saber si la
        # competición está en la lista blanca de The Odds API. Sin ella el
        # consenso se queda en las cinco casas de siempre y la ficha decía
        # «Consenso: 4 casas · modo de respaldo» teniendo veinte disponibles.
        # Lo cazó el propio indicador de consenso el día que se añadió.
        res = _cm.cuotas_partido(deporte, home, away, fecha=fecha,
                                 liga=clave_liga)
    except Exception:
        return False
    if not res.get('n_casas'):
        if _estilo is not None:
            _pinta(_estilo.vacio(
                "Ninguna casa ha abierto línea todavía",
                "Suele pasar a más de 3 días vista —las casas publican 2-4 "
                "días antes— o en ligas que ningún operador grande cubre. "
                "Mientras tanto se muestra la cuota justa del modelo, que no "
                "es un precio que puedas tomar.", '💤'))
        else:
            st.info(
                "Ninguna casa ha abierto línea todavía para este partido. "
                "Suele pasar a más de 3 días vista (las casas publican 2-4 días "
                "antes) o en ligas que ningún operador grande cubre. "
                "Mientras tanto se muestra la **cuota justa** del modelo.")
        return False
    import pandas as _pd
    # v122 — EL TABLÓN, COMO UN TABLÓN.
    #
    # Esto era un `st.dataframe` de tres columnas de números: para saber quién
    # pagaba más había que leer las seis filas y comparar a ojo, que es
    # justamente el trabajo que la pantalla debería ahorrar. Ahora el mejor
    # precio de cada lado va marcado, y la casa del usuario va señalada
    # aparte, porque un precio que no puede tomar no le sirve para decidir.
    _casas_1x2 = {k: v for k, v in res['casas'].items()
                  if not k.startswith('_')}
    _mejor_lado = {}
    for _lado in ('home', 'draw', 'away'):
        _cands = [(c[_lado], k) for k, c in _casas_1x2.items()
                  if (c or {}).get(_lado)]
        if _cands:
            _mejor_lado[_lado] = max(_cands)[1]
    _mia = None
    try:
        _mia = _cm.CASA_PRIORITARIA
    except Exception:
        _mia = 'Playdoit'
    if _estilo is not None:
        _filas_html = []
        for casa, c in _casas_1x2.items():
            _et = _estilo.pildora(casa, 'ok' if casa == _mia else 'info')
            if casa == _mia:
                _et += ' ' + _estilo.pildora('tu casa', 'ok')
            _filas_html.append([_et] + [
                _estilo.chip_cuota((c or {}).get(l), '',
                                   _mejor_lado.get(l) == casa) or '—'
                for l in ('home', 'draw', 'away')])
        _pinta(_estilo.tabla(['Casa', home, 'Empate', away], _filas_html,
                             alineadas=[1, 2, 3]))
        # v127 — CUÁNTAS CASAS RESPALDAN ESTE PARTIDO.
        #
        # Con 5 casas una desviación del 5 % es ruido; con 20 es una señal. Y
        # el número cambia partido a partido —según la liga esté o no en la
        # lista blanca y según quede presupuesto—, así que tiene que verse
        # AQUÍ y no sólo en la barra lateral.
        _n_casas_c = len(_casas_1x2)
        _ampliado = _n_casas_c > 6
        _pinta(_estilo.pildora(
            f"Consenso: {_n_casas_c} casas"
            + ('' if _ampliado else ' · modo de respaldo'),
            'ok' if _ampliado else 'mira') if _estilo else None)
        if _estilo is None:
            st.caption(f"Consenso: {_n_casas_c} casas")
        st.caption(
            "El precio **marcado en verde** es el mejor de todas las casas en "
            "ese resultado. Si tu casa no lo tiene, ésa es la diferencia que te "
            "cuesta tener una sola cuenta."
            + ("" if _ampliado else
               "  \n🟡 **Modo de respaldo**: este partido sólo tiene el tablón "
               "básico. O su liga no está en la lista blanca de la API, o se "
               "agotaron los créditos del mes. Con pocas casas, una ventaja "
               "del 5 % no se puede distinguir del ruido."))
    else:
        filas = []
        for casa, c in _casas_1x2.items():
            filas.append({'Casa': casa,
                          f'{home}': c.get('home'), 'Empate': c.get('draw'),
                          f'{away}': c.get('away')})
        st.dataframe(_pd.DataFrame(filas), hide_index=True, width='stretch')

    # v114 — LA TABLA RICA, TAMBIÉN AQUÍ.
    #
    # Esto enseñaba el 1X2 y se acababa. Las competiciones cuyo `event_id` de
    # ESPN no se localiza —Champions, Conference, Eredivisie— caían siempre por
    # esta rama, así que veían tres cuotas mientras Liga MX veía treinta
    # mercados con su EV. El usuario lo pidió explícito: «todas las ligas al
    # mismo nivel».
    #
    # No hacía falta ninguna fuente nueva: `cuotas_partido` ya devolvía
    # totales, ambos-marcan y hándicap de las seis casas, y esta función los
    # tiraba. `cuotas_tablon` los traduce al vocabulario de la plantilla y los
    # cruza con el modelo — y de paso elige el MEJOR precio de cada mercado,
    # que es lo que la rama de ESPN no puede hacer porque lee una casa sola.
    if plantilla:
        try:
            import cuotas_tablon as _ct
            _mk = _ct.marcar_ev_sospechoso(
                _ct.mercados_con_ev(res, plantilla, home, away))
            if _mk:
                _pos = [r for r in _mk if r['ev'] > 0]
                st.success(f"**{len(_mk)} mercados** con cuota real de "
                           f"**{len({r['casa'] for r in _mk if r.get('casa')})} "
                           f"casas** · **{len(_pos)} con EV positivo**.")
                # v115 — SE ORDENA POR PRECIO, NO POR EV.
                #
                # Ordenar por EV es ordenar por el error del modelo. Está
                # medido en este proyecto: el modelo no bate al mercado (4 de
                # 37 ligas) y su EV declarado es ANTI-indicador del cierre
                # (corr −0,054 con el CLV). Lo que sí mide positivo es comprar
                # al mejor precio, así que arriba va lo que más se gana por
                # comprar bien, y el EV se queda como columna informativa.
                _orden = st.radio(
                    "Ordenar por", ['🛒 Ventaja de precio', '📊 EV del modelo'],
                    horizontal=True, key=f'ord_mk_{clave_liga}_{home}_{away}',
                    help="«Ventaja de precio» = cuánto más paga la mejor casa "
                         "que la peor en ese mismo mercado. Es lo único que "
                         "este proyecto ha medido con ROI positivo. El EV "
                         "compara contra el modelo, que se sabe que pierde.")
                if _orden.startswith('🛒'):
                    _mk = sorted(_mk, key=lambda r: (
                        -(r.get('ventaja_line_shopping') or 0),
                        -(r.get('n_casas') or 0)))
                # v122 — LA COLUMNA DE TU CASA.
                #
                # La tabla decía cuál es el mejor precio del mercado, pero no
                # lo que el usuario preguntó: «de esa forma sabré cuál me da
                # una buena cuota a mí». Playdoit publica el tablero entero del
                # partido (ver `cuotas_multi.mercados_playdoit`), así que aquí
                # se pega su precio al lado del mejor y la diferencia entre los
                # dos. Cuesta una petición por partido y se cachea 30 min.
                _pdt_por_id = {}
                try:
                    _det_t = _cm.mercados_playdoit(deporte, home, away,
                                                   fecha=fecha)
                    if _det_t:
                        for _r in _ct.mercados_playdoit_con_ev(
                                _det_t, plantilla, home, away):
                            if _r.get('id'):
                                _pdt_por_id[_r['id']] = _r
                except Exception:
                    _pdt_por_id = {}
                if _estilo is not None:
                    _fh = []
                    for r in _mk:
                        _p = _pdt_por_id.get(r.get('id'))
                        _cp = _p.get('cuota_casa') if _p else None
                        _dif = ((_cp / r['cuota_casa'] - 1)
                                if _cp and r.get('cuota_casa') else None)
                        _fh.append([
                            _html_esc(r['apuesta']),
                            _estilo.chip_cuota(r['cuota_casa'],
                                               r.get('casa') or '', True),
                            (_estilo.chip_cuota(_cp, _mia,
                                                _dif is not None and _dif >= 0)
                             if _cp else '<span style="opacity:.45">no cotiza'
                                         '</span>'),
                            (_estilo.pildora(f"{_dif*100:+.1f} %",
                                             _estilo.tono_por_diferencia(_dif))
                             if _dif is not None else '—'),
                            str(r.get('n_casas') or 1),
                            (f"+{(r.get('ventaja_line_shopping') or 0)*100:.1f} %"
                             if (r.get('n_casas') or 1) >= 2 else '—'),
                            f"{r['prob']*100:.0f} %",
                            (_estilo.pildora(f"{r['ev']*100:+.0f} %", 'mira')
                             if r.get('ev_sospechoso')
                             else f"{r['ev']*100:+.1f} %"),
                        ])
                    _pinta(_estilo.tabla(
                        ['Mercado', 'Mejor del mercado', f'Tu casa ({_mia})',
                         'Diferencia', 'Casas', 'Ventaja precio',
                         'Prob. modelo', 'EV'],
                        _fh, alineadas=[1, 2, 3, 4, 5, 6, 7]))
                    if _pdt_por_id:
                        st.caption(
                            f"**Diferencia** = cuánto paga {_mia} frente al "
                            f"mejor precio del mercado en ESE mismo mercado. "
                            f"En verde, tu casa iguala o mejora; en rojo, ahí "
                            f"se te va dinero por tener una sola cuenta. Es la "
                            f"única columna de esta tabla que **no depende de "
                            f"que el modelo acierte**.")
                else:
                    st.dataframe(_pd.DataFrame([{
                        'Mercado': r['apuesta'],
                        'Cuota casa': r['cuota_casa'],
                        'Casa': r.get('casa') or '—',
                        'Casas': r.get('n_casas') or 1,
                        'Ventaja precio': (
                            f"+{(r.get('ventaja_line_shopping') or 0)*100:.1f}%"
                            if (r.get('n_casas') or 1) >= 2 else '—'),
                        'Cuota justa': r['cuota_justa'],
                        'Prob. modelo': f"{r['prob']*100:.0f}%",
                        'EV': (f"⚠️ {r['ev']*100:+.0f}%"
                               if r.get('ev_sospechoso')
                               else f"{r['ev']*100:+.1f}%"),
                    } for r in _mk]), hide_index=True, width='stretch')
                if any(r.get('ev_sospechoso') for r in _mk):
                    st.caption(
                        "⚠️ Los EV marcados vienen de **una sola casa** y son "
                        "demasiado altos para ser reales. Un mercado líquido "
                        "no se equivoca un 40 %: el que se equivoca es el "
                        "modelo. No los tomes como oportunidades.")
                _sh = _ct.resumen_line_shopping(res)
                if _sh:
                    st.caption("🛒 " + _sh + " Comprar al mejor precio es lo "
                               "único que este proyecto ha medido con ROI "
                               "positivo y robusto; el EV del modelo, no.")
        except Exception as e:
            st.caption(f"Mercados cruzados no disponibles "
                       f"({type(e).__name__}).")

    # v122 — TU CASA CONTRA EL MERCADO, EN LA MISMA LÍNEA.
    #
    # Antes esto era «🛒 Mejor precio disponible — Monterrey 1.55 (Pinnacle)…»,
    # que informa del techo pero no de lo que el usuario preguntó: si SU casa
    # le sirve. `cuotas_partido` ya calcula `preferida` desde la v77 con el
    # diferencial contra la mejor alternativa, y nadie lo estaba enseñando.
    mejor = res.get('mejor') or {}
    pref = res.get('preferida') or {}
    if _estilo is not None and (mejor or pref):
        _tarj = []
        for lado, etiq in (('home', home), ('draw', 'Empate'), ('away', away)):
            if lado not in mejor:
                continue
            _mj = mejor[lado]
            _pf = pref.get(lado)
            if _pf and _pf['casa'] != _mj['casa']:
                _d = -(float(_pf.get('ventaja_alternativa') or 0))
                _tarj.append({'valor': f"{_pf['cuota']:.2f}", 'etiqueta': etiq,
                              'tono': _estilo.tono_por_diferencia(_d),
                              'sub': (f"en {_pf['casa']} · el mercado paga "
                                      f"{_mj['cuota']:.2f} ({_mj['casa']})")})
            elif _pf:
                _tarj.append({'valor': f"{_pf['cuota']:.2f}", 'etiqueta': etiq,
                              'tono': 'ok',
                              'sub': f"en {_pf['casa']} · nadie paga más"})
            else:
                _tarj.append({'valor': f"{_mj['cuota']:.2f}", 'etiqueta': etiq,
                              'tono': 'info',
                              'sub': (f"mejor: {_mj['casa']} · tu casa no "
                                      f"cotiza este lado")})
        _pinta(_estilo.kpis(_tarj))
        if pref:
            st.caption(f"Las cifras son las de **{_mia}**, tu casa, con el "
                       f"mejor precio del mercado debajo para comparar.")
    else:
        partes = []
        for lado, etiq in (('home', home), ('draw', 'Empate'), ('away', away)):
            if lado in mejor:
                partes.append(f"**{etiq}** {mejor[lado]['cuota']} "
                              f"({mejor[lado]['casa']})")
        if partes:
            st.success("🛒 Mejor precio disponible — " + " · ".join(partes))
    if res.get('pinnacle'):
        st.caption("📌 Pinnacle es la referencia *sharp*: si tu casa te paga "
                   "más que ella, ahí está el valor.")
    if res.get('emparejado_difuso'):
        st.caption(f"ℹ️ Partido emparejado por similitud de nombres "
                   f"({res['emparejado_difuso']}). Verifica que sea el correcto.")
    return True


def render_ev_automatico(deporte: str, obtener, ayuda: str = '',
                         nota: str = '') -> None:
    """
    v106 — EV+ AUTOMÁTICO, IGUAL EN TODOS LOS DEPORTES.

    El usuario lo dijo claro: «en deportes que no son fútbol no tienes la
    opción de EV+ automático, y ese me ayuda mucho a ver qué apostar casi en
    vivo antes de iniciar».

    Y era exacto. El barrido universal (`alpha_finder`) YA calculaba picks con
    cuota y EV de MLB, NBA, KBO y tenis — están en «Apuestas del Día» — pero
    la vista propia de cada deporte no los enseñaba: sólo la MLB tenía su
    pestaña, y las otras tres obligaban a salir a la pantalla general y buscar
    entre todos los deportes. Aquí eso se acaba: el mismo panel, con la misma
    lógica y los mismos filtros, en las cuatro vistas.

    `obtener` es una función sin argumentos que devuelve el dict de picks de
    ese deporte (las que ya existen en `alpha_finder`). Se cachea 15 minutos
    por deporte, que es la frescura del tablón de cuotas: pedirlo más a menudo
    no trae precios nuevos y sí gasta peticiones.
    """
    st.caption(
        "Cuotas en vivo de **Pinnacle, Bovada, Playdoit, Unibet y Matchbook** "
        "(sin límite de "
        "peticiones) contra la probabilidad del modelo, ya encogida hacia el "
        "mercado. **Capa 1** = pasa todos los filtros de élite; "
        "**alta confianza** = probable pero fuera de esos filtros, y se dice "
        "por qué. Horas en hora de Ciudad de México."
        + (f" {ayuda}" if ayuda else ''))

    @st.cache_data(ttl=900, show_spinner=f"Buscando valor en {deporte}…",
                   max_entries=8)
    def _picks_deporte(dep: str):
        # `dep` existe SOLO para que la clave de caché distinga deportes:
        # `obtener` viaja por cierre porque una función no es cacheable, así
        # que sin este argumento las cuatro llamadas —MLB, NBA, KBO y tenis—
        # compartirían la MISMA entrada y la vista de NBA enseñaría los picks
        # de la MLB.
        #
        # Y NO puede llamarse `_dep`: Streamlit excluye del hash cualquier
        # parámetro que empiece por guion bajo (es su convención para pasar
        # objetos no hasheables), así que el guion bajo habría reintroducido
        # exactamente el fallo que este argumento existe para evitar.
        return obtener()

    # el botón va DESPUÉS de la definición: Streamlit ejecuta el cuerpo de la
    # función de arriba abajo y `_picks_deporte.clear()` antes del `def` sería
    # un NameError en cuanto alguien lo pulsara.
    c1, _ = st.columns([1, 3])
    if c1.button("🔄 Actualizar", key=f'ev_ref_{deporte}', width='stretch',
                 help="Vuelve a bajar las cuotas de este deporte."):
        _picks_deporte.clear()
        st.rerun()

    try:
        r = _picks_deporte(deporte)
    except Exception as e:
        st.error(f"No se pudieron obtener las cuotas de {deporte} "
                 f"({type(e).__name__}: {e}).")
        return
    r = r or {}

    for inc in (r.get('incidencias') or []):
        st.info(inc)
    if nota:
        st.caption(nota)

    capa1 = r.get('capa1') or r.get('picks') or []
    capa2 = r.get('capa2') or r.get('confianza') or []

    def _tarjeta(pk, con_ev: bool):
        """
        Un pick de EV+ automático. v122 — con la misma gramática visual que las
        tarjetas de «Apuestas del Día», que hasta ahora eran otra cosa aunque
        enseñaran lo mismo: dos pantallas con el mismo dato y dos maquetas
        distintas obligan a reaprender a leerlas.
        """
        with st.container(border=True):
            # la hora, en CDMX (v106). Si la casa no la publicó, no se inventa.
            _h = _horario.etiqueta(pk.get('inicio'))
            _falta = _horario.falta_para(pk.get('inicio')) or ''
            cuota = pk.get('cuota')
            ev = pk.get('ev')
            if _estilo is not None:
                _nom = str(pk.get('partido', '?'))
                _sp = next((x for x in (' vs ', ' vs. ', ' @ ', ' - ')
                            if x in _nom), None)
                _meta = [t for t in (pk.get('fecha', ''), _h, _falta) if t]
                if _sp:
                    _hh, _aa = _nom.split(_sp, 1)
                    _pinta(_estilo.cabecera_partido(_hh, _aa, _meta))
                else:
                    st.markdown(f"**{_nom}**")
                    if _meta:
                        st.caption(' · '.join(_meta))
                _tono = (_estilo.tono_por_ev(ev, int(pk.get('n_casas') or 1))
                         if (con_ev and ev is not None) else 'info')
                _etqs = []
                if con_ev and ev is not None:
                    _etqs.append((f"EV {ev*100:+.1f} %", _tono))
                if pk.get('casa'):
                    _etqs.append((f"🏠 {pk['casa']}", 'azul'))
                if pk.get('origen'):
                    _etqs.append((f"🔎 {pk['origen']}", 'info'))
                _pinta(_estilo.pata(
                    f"{pk.get('valor','')} {pk.get('apuesta','?')}".strip(),
                    cuota or pk.get('cuota_justa'), pk.get('prob'), '',
                    _etqs, _tono))
                _pie = [f"Cuota justa del modelo: {pk.get('cuota_justa','?')}"]
                if pk.get('motivo_capa2'):
                    _pie.append(f"Fuera de élite: {pk['motivo_capa2']}")
                st.caption(' · '.join(_pie))
            else:
                cc1, cc2 = st.columns([3, 2])
                cc1.markdown(
                    f"**{pk.get('partido','?')}**  \n{pk.get('fecha','')}"
                    + (f"  \n{_h}" + (f" · {_falta}" if _falta else '')
                       if _h else '')
                    + (f"  \n🏠 {pk['casa']}" if pk.get('casa') else ''))
                txt = f"{pk.get('valor','')} **{pk.get('apuesta','?')}**"
                if cuota:
                    txt += (f"  \nCuota **{cuota}** "
                            f"(justa {pk.get('cuota_justa','?')})")
                if con_ev and ev is not None:
                    txt += f"  \nEV **{ev*100:+.1f} %**"
                txt += f"  \nprob {(pk.get('prob') or 0)*100:.0f} %"
                if pk.get('motivo_capa2'):
                    txt += f"  \nℹ️ Fuera de élite: {pk['motivo_capa2']}"
                if pk.get('origen'):
                    txt += f"  \n🔎 {pk['origen']}"
                cc2.markdown(txt)

    if capa1:
        _seccion(f"⚡ Con valor ({len(capa1)})",
                 'la cuota paga más de lo que el modelo cree que vale', 'ok')
        for pk in capa1:
            _tarjeta(pk, con_ev=True)
    elif _estilo is not None:
        _pinta(_estilo.vacio(
            f"Hoy ninguna apuesta de {deporte} pasa los filtros",
            "Cero picks no es un fallo: significa que las casas y el modelo "
            "coinciden, y forzar una apuesta ahí es exactamente cómo se pierde "
            "dinero.", '⚖️'))
    else:
        st.info(
            f"Hoy **ninguna apuesta de {deporte} pasa los filtros de valor**. "
            "Cero picks no es un fallo: significa que las casas y el modelo "
            "coinciden, y forzar una apuesta ahí es exactamente cómo se "
            "pierde dinero.")

    if capa2:
        with st.expander(f"🎯 Alta confianza, sin valor suficiente "
                         f"({len(capa2)})", expanded=not capa1):
            st.caption("Probables según el modelo, pero el precio no paga lo "
                       "que arriesgan. **Combinarlos no arregla eso: multiplica "
                       "el margen de la casa.** Con patas de EV −4,8 %, una "
                       "combinada de tres sale a −13,6 %. Ver la bitácora de "
                       "arquitectura.")
            for pk in capa2:
                _tarjeta(pk, con_ev=True)

    # v124 — MEJORA 7: estos picks se pueden mandar al teléfono.
    #
    # Hasta ahora el botón de Telegram existía sólo para las combinadas de un
    # partido, así que la pantalla que se mira antes de un partido de MLB o de
    # tenis no tenía salida: había que copiar a mano.
    if capa1 or capa2:
        if st.button(f"📲 Enviar estos picks de {deporte} a Telegram",
                     key=f'tg_ev_{deporte}', width='stretch',
                     help="Manda la lista con su precio, su casa y su "
                          "probabilidad. El aviso sobre el EV viaja con el "
                          "mensaje: se lee fuera de contexto."):
            try:
                import bot_telegram as _bt
                _msg = _bt.formatear_picks(
                    f"EV+ AUTOMÁTICO — {deporte.upper()}",
                    list(capa1) + list(capa2),
                    nota=(f"{len(capa1)} con valor · {len(capa2)} de alta "
                          f"confianza sin valor suficiente"))
                if _bt.enviar(_msg):
                    st.success("✅ Enviado a Telegram.")
                else:
                    st.warning("Sin TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID en "
                               "los Secrets. Vista previa del mensaje:")
                    st.code(_msg, language=None)
            except Exception as e:
                st.error(f"No se pudo enviar ({type(e).__name__}: {e}).")

    from bankroll_manager import AVISO_JUEGO_RESPONSABLE
    st.caption(AVISO_JUEGO_RESPONSABLE)


@st.cache_resource(show_spinner="Cargando modelo MLB…")
def cargar_motor_mlb():
    """
    v118 — el motor de MLB, compartido por las tres pestañas.

    `render_mlb` lo cargaba en un cierre propio, así que la pestaña de
    abridores no tenía forma de pedirle una probabilidad — y por eso el
    veredicto se quedaba sin ella. A nivel de módulo y cacheado, las tres
    pestañas usan la misma instancia y el modelo se carga una sola vez.
    """
    from engines.mlb_engine import MLBEngine
    return MLBEngine().cargar_modelo()


def render_beisbol_pitchers() -> None:
    """
    v106 — ABRIDORES, ESTADIO Y PONCHES: el veredicto de parlay del usuario.

    Implementa en pantalla la regla que él describió (ver el docstring de
    `beisbol_pitchers.py`): mirar quién abre y dónde se juega, y de ahí decidir
    si el partido va a la parlay como ganador, como run line o si se queda
    fuera. Todo automático — abridores de la API oficial, estadísticas de la
    misma, factor del parque medido del histórico del proyecto, y línea de
    ponches con su cuota desde Pinnacle.
    """
    import beisbol_pitchers as bp

    st.caption(
        "Regla de decisión: **1)** si el favorito del casino abre con buen "
        "lanzador y su cuota de ganador llega a 1.50 → va de **ganador**; "
        "**2)** si no, se mira la línea de ponches del mejor abridor —aunque "
        "sea el del equipo que va en positivo— y si pide **más de 6** no se "
        "toca: se propone el **hándicap (run line)** al equipo de ese "
        "lanzador; **3)** si la línea es de 6 o menos y el precio paga, van "
        "los **ponches**; **4)** si no se cumple nada, el partido **no entra**."
    )
    st.caption(
        "⚠️ Esta regla es **tuya**, no una estrategia medida contra el "
        "histórico del proyecto. Se aplica tal cual la pediste y junto a cada "
        "veredicto va el EV que calcula el modelo por su cuenta, para que "
        "veas las dos lecturas sin que una se disfrace de la otra.")

    @st.cache_data(ttl=900, show_spinner="Bajando abridores, cuotas y ponches…")
    def _analisis_beisbol():
        import beisbol_pitchers as _bp
        import cuotas_multi as _cm
        import mlb_statsapi as _msa
        from engines.mlb_engine import codigo_mlb as _cod

        # v118: el motor, para poder dar la probabilidad de cada partido.
        # Cacheado a nivel de proceso por `cargar_motor_mlb`, así que esto no
        # vuelve a cargar el modelo en cada refresco.
        try:
            _eng_p = cargar_motor_mlb()
        except Exception:
            _eng_p = None

        def _prob_mlb(h, a):
            """Probabilidad de que gane el local, o None si no se sabe."""
            if _eng_p is None or not getattr(_eng_p, 'listo', False):
                return None
            try:
                pr = _eng_p.predecir(h, a)
                v = (pr or {}).get('prob_home')
                return float(v) if v is not None else None
            except Exception:
                return None

        juegos = _msa.partidos_del_dia()
        props = _bp.props_ponches()
        idx = _cm._indice('mlb')
        # índice por par de códigos, para cruzar la API oficial con el tablón
        por_par = {}
        for v in (idx or {}).values():
            if v.get('home') and v.get('away'):
                por_par[(_cod(v['home']), _cod(v['away']))] = v
        salida = []
        for j in juegos:
            fila = por_par.get((j['home'], j['away'])) or {}
            c = fila.get('cuotas') or {}
            salida.append({
                'home': j['home'], 'away': j['away'],
                'inicio': fila.get('fecha') or j.get('fecha'),
                # v118 — LA PROBABILIDAD DEL MODELO, QUE NUNCA SE PASABA.
                #
                # `veredicto()` acepta `prob_home` desde la v106 y calcula con
                # ella la probabilidad del lado y el EV. Esta llamada nunca se
                # la daba, así que `prob_home` llegaba None y los dos campos
                # salían vacíos: por eso la pantalla enseñaba «Gana BOS @ 1.64»
                # a secas, sin el «X % de ganarla» ni el EV. El usuario lo
                # reportó dos veces y las dos veces el arreglo estaba en la UI,
                # no en la regla.
                #
                # Si el motor no puede predecir ese cruce (equipo desconocido,
                # modelo sin cargar) se pasa None y el veredicto se comporta
                # como antes — la regla no depende de la probabilidad.
                'veredicto': _bp.veredicto(
                    j['home'], j['away'],
                    j.get('home_pitcher'), j.get('away_pitcher'),
                    cuota_home=c.get('home'), cuota_away=c.get('away'),
                    spreads=fila.get('spreads'), props=props,
                    prob_home=_prob_mlb(j['home'], j['away'])),
            })
        return salida

    # el botón va DESPUÉS del `def`: pulsarlo antes sería un NameError.
    c1, _ = st.columns([1, 3])
    if c1.button("🔄 Actualizar datos", key='bp_ref', width='stretch',
                 help="Vuelve a bajar abridores, cuotas y líneas de ponches."):
        bp.limpiar_cache()
        _analisis_beisbol.clear()
        st.rerun()

    try:
        analisis = _analisis_beisbol()
    except Exception as e:
        st.error(f"No se pudo analizar la jornada ({type(e).__name__}: {e}).")
        return

    if not analisis:
        st.info("No hay partidos de MLB programados hoy.")
        return

    dentro = [a for a in analisis if a['veredicto'].get('entra')]
    st.markdown(f"**{len(dentro)} de {len(analisis)} partidos entrarían** "
                f"en la parlay según la regla.")

    # v115 — SE REGISTRA LO QUE SE RECOMIENDA, Y SE ENSEÑA CÓMO SALIÓ.
    #
    # Era el agujero más grande del proyecto: la app emitía líneas de ponches y
    # nadie comprobaba si acertaban. Cuando el usuario dijo «de cinco sólo se
    # cumplió una», hubo que auditar el modelo a mano durante horas para
    # descubrir que `bf_apertura` inflaba el λ medio ponche. Con el círculo
    # cerrado, eso se ve en esta misma pantalla.
    #
    # Se registran sólo las recomendaciones de PONCHES, y con canal propio: la
    # regla es del usuario, no una estrategia validada del proyecto, y mezclar
    # su tasa de acierto con la del resto confundiría dos cosas distintas.
    try:
        import liquidador_ponches as _lp
        _regs = []
        for _a in dentro:
            _v = dict(_a['veredicto'])
            _v['partido'] = f"{_a['away']} @ {_a['home']}"
            _regs.append(_v)
        _lp.registrar_ponches(_regs)
        _rend = _lp.resumen_ponches(dias=60)
        if _rend.get('n'):
            with st.container(border=True):
                st.markdown("**📊 Cómo va esta regla, de verdad**")
                r1, r2, r3 = st.columns(3)
                r1.metric("Recomendaciones cerradas", _rend['n'])
                r2.metric("Acertadas", f"{_rend['tasa']*100:.0f} %"
                          if _rend.get('tasa') is not None else '—')
                r3.metric("ROI", f"{_rend['roi']*100:+.1f} %"
                          if _rend.get('roi') is not None else '—',
                          help="Con stake plano de 1 unidad por recomendación.")
                if _rend.get('pendientes'):
                    st.caption(f"{_rend['pendientes']} pendientes de liquidar "
                               f"(se resuelven solas cuando el lanzador "
                               f"aparece en el registro oficial).")
                if _rend['n'] < 30:
                    st.caption("⚠️ Con menos de 30 apuestas cerradas esta tasa "
                               "no distingue una buena regla de una mala "
                               "racha. Es un recuento, no una conclusión.")
        else:
            st.caption("📊 Las recomendaciones de ponches quedan registradas "
                       "desde ahora y se liquidan contra el registro oficial "
                       "de MLB. En unos días esta pantalla dirá cuántas "
                       "acertaron.")
    except Exception as _e:
        st.caption(f"Registro de rendimiento no disponible ({type(_e).__name__}).")

    # v124 — MEJORA 8: la sección ENTERA a Telegram.
    #
    # «Entera» es la palabra que el usuario usó, así que van los partidos que
    # entran Y los que no, con el motivo por el que se caen: saber qué se
    # descartó y por qué es la mitad de la utilidad de esta pantalla.
    if st.button("📲 Enviar la sección de ponches completa a Telegram",
                 key='tg_ponches', width='stretch',
                 help="Manda los partidos que entran en la regla y los que no, "
                      "con su línea, su precio y el motivo del descarte."):
        try:
            import bot_telegram as _bt_p
            _filas_tg = []
            for _a in analisis:
                _v = _a.get('veredicto') or {}
                _d = _v.get('datos') or {}
                _abr = (_d.get('abridor') or _d.get('nombre')
                        or _v.get('lanzador') or '')
                _filas_tg.append({
                    'lanzador': _abr or _v.get('apuesta') or '—',
                    'partido': f"{_a.get('away','?')} @ {_a.get('home','?')}",
                    'linea': _v.get('linea'),
                    'cuota': _v.get('cuota'),
                    'prob': _v.get('prob'),
                    'ev': _v.get('ev_modelo'),
                    'recomendacion': (
                        f"✅ {_v.get('apuesta')} · {_v.get('mercado')}"
                        if _v.get('entra')
                        else "❌ no entra: " + '; '.join(
                            str(m) for m in (_v.get('motivos') or [])[:2])),
                })
            _msg_p = _bt_p.formatear_ponches(
                _filas_tg, titulo='PONCHES Y ABRIDORES DE HOY',
                nota=(f"{len(dentro)} de {len(analisis)} partidos entran en la "
                      f"regla. Es una regla del usuario, no una estrategia "
                      f"validada del proyecto."))
            if _bt_p.enviar(_msg_p):
                st.success("✅ Sección de ponches enviada a Telegram.")
            else:
                st.warning("Sin TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID en los "
                           "Secrets. Vista previa del mensaje:")
                st.code(_msg_p, language=None)
        except Exception as e:
            st.error(f"No se pudo enviar ({type(e).__name__}: {e}).")

    for a in analisis:
        v = a['veredicto']
        cab = f"{a['away']} @ {a['home']}"
        _h = _horario.etiqueta(a.get('inicio'))
        with st.container(border=True):
            k1, k2 = st.columns([3, 2])
            k1.markdown(f"**{cab}**" + (f"  \n{_h}" if _h else ''))
            if v.get('entra'):
                # v117 — la PROBABILIDAD, delante del EV.
                #
                # El usuario la pidió y es la cifra que se entiende: un EV de
                # +2 % no dice nada sin saber que sale de un 55 % a cuota 1,85.
                # Cuando el modelo no la tiene —el hándicap de carreras no se
                # modela— se dice, en vez de dejar el hueco sin explicar.
                _pv = v.get('prob')
                _txt_p = (f"  \n🎯 **{_pv*100:.0f} % de ganarla** (según el "
                          f"modelo)" if _pv is not None
                          else ("  \nℹ️ El modelo no estima la probabilidad de "
                                "cubrir un hándicap de carreras: esta pata "
                                "sale de la regla, no de una probabilidad."
                                if v.get('prob_no_disponible') else ''))
                k2.success(f"✅ **{v['apuesta']}**  \n{v['mercado']}"
                           + (f" @ {v['cuota']}" if v.get('cuota') else '')
                           + _txt_p
                           + (f"  \nEV del modelo {v['ev_modelo']*100:+.1f} %"
                              if v.get('ev_modelo') is not None else ''))
            else:
                k2.warning("⛔ Fuera de la parlay")
            # v118 — la probabilidad del modelo para ESTE partido, entre o no.
            #
            # Es la cifra que permite contrastar la regla con el modelo: un
            # partido descartado por la regla puede tener un 60 % del local, y
            # sin verlo no hay forma de juzgar si la regla se está dejando algo.
            _pm = (v.get('datos') or {}).get('prob_modelo') or {}
            if _pm.get('home') is not None:
                _bar = ''
                if _estilo is not None:
                    try:
                        _bar = _estilo.barra(_pm['home'])
                    except Exception:
                        _bar = ''
                st.markdown(
                    f"📊 Probabilidad del modelo — **{a['home']} "
                    f"{_pm['home']*100:.0f} %** · {a['away']} "
                    f"{_pm['away']*100:.0f} %" + _bar,
                    unsafe_allow_html=bool(_bar))
            for m in v.get('motivos', []):
                st.caption(m)
            # el detalle de cada abridor, para poder discutir el veredicto
            abr = (v.get('datos') or {}).get('abridores') or {}
            filas = []
            for lado in ('away', 'home'):
                p = abr.get(lado)
                if not p:
                    continue
                prop = p.get('prop') or {}
                filas.append({
                    'Lado': 'Visitante' if lado == 'away' else 'Local',
                    'Abridor': p.get('nombre') or '?',
                    'FIP': p.get('fip'),
                    'K/bateador': p.get('k_bf'),
                    'K esperados': (round(p['k_esperados'], 1)
                                    if p.get('k_esperados') else None),
                    'Línea K': prop.get('linea'),
                    'Cuota over': prop.get('odd_over'),
                    'P(over)': (f"{p['prob_over']*100:.0f} %"
                                if p.get('prob_over') else None),
                    'Top liga': '✅' if p.get('bueno') else '—',
                })
            if filas:
                st.dataframe(pd.DataFrame(filas), hide_index=True,
                             width='stretch')

    with st.expander("🏟️ Factores de parque (medidos del histórico)"):
        st.caption(
            "Carreras por juego en casa frente a las de ese mismo equipo como "
            "visitante, últimas 5 temporadas. Compararlo contra sí mismo "
            "cancela lo bueno o malo que sea el equipo; lo que queda es el "
            "estadio. Por encima de 1 se anota más de lo normal.")
        f = bp.factores_parque()
        if f:
            st.dataframe(
                pd.DataFrame(
                    [{'Equipo': k, 'Factor': v}
                     for k, v in sorted(f.items(), key=lambda x: -x[1])]),
                hide_index=True, width='stretch')
        else:
            st.caption("Sin histórico suficiente para medirlos.")

    from bankroll_manager import AVISO_JUEGO_RESPONSABLE
    st.caption(AVISO_JUEGO_RESPONSABLE)


def _renderizar_secciones(clas: dict, opciones_s3: list) -> None:
    """
    Las tres secciones del clasificador, en el orden en que se decide.

    v125 — sustituye al «aquí van todos los mercados ordenados por EV» que
    había. El cambio de fondo no es visual: es que el criterio deja de ser el
    EV del modelo —medido en −4,66 % a −6,52 %— y pasa a ser la ventaja de
    precio contra el consenso, que es lo único con señal positiva. Ver
    `clasificador.py` para las mediciones que fijan el umbral en el 5 %.
    """
    s1 = clas.get('seccion1') or []
    s2 = clas.get('seccion2') or []
    rojo = clas.get('descartados') or []
    conf = clas.get('confianza') or {}

    # el indicador de confianza de la liga: se ENSEÑA, no filtra (medido: con
    # 213 apuestas su p5 es −13,06 %, así que no da para puerta)
    _chips = []
    if conf.get('estrellas'):
        _chips.append(('★' * conf['estrellas'] + '☆' * (5 - conf['estrellas'])
                       + '  confianza en la liga',
                       'ok' if conf['estrellas'] >= 4
                       else 'mira' if conf['estrellas'] >= 3 else 'no'))
    _pinta(_estilo.cabecera(
        'Qué se puede jugar en este partido',
        'El criterio es el PRECIO: si tu casa paga por encima del consenso del '
        'mercado, y por cuánto. No es el valor esperado del modelo — ése está '
        'medido en negativo.',
        chips=_chips, icono='🚦') if _estilo else None)
    if conf.get('texto'):
        st.caption(f"Confianza en la liga: **{conf.get('estrellas', 0)}/5** — "
                   f"{conf['texto']}. Es un indicador, **no un filtro**: no hay "
                   f"muestra suficiente para descartar picks por él.")

    _pinta(_estilo.kpis([
        {'valor': len(s1), 'etiqueta': '🟢 Máximo valor',
         'tono': 'ok' if s1 else 'info', 'sub': 'jugables en solitario'},
        {'valor': len(s2), 'etiqueta': '🟡 Sólo como pata',
         'tono': 'mira' if s2 else 'info', 'sub': 'no en solitario'},
        {'valor': len(opciones_s3), 'etiqueta': '🧩 Combinadas',
         'tono': 'azul' if opciones_s3 else 'info',
         'sub': 'armadas desde la sección verde'},
        {'valor': len(rojo), 'etiqueta': '🔴 Descartados',
         'tono': 'no' if rojo else 'info', 'sub': 'tu casa paga peor'},
    ]) if _estilo else None)

    # --- SECCIÓN 1 ---------------------------------------------------------
    _seccion('🟢 Sección 1 · Máximo valor',
             'para jugar en solitario', 'ok')
    if not s1:
        _comparables = sum(1 for m in (s1 + s2)
                           if (m.get('n_casas_mercado') or 0) >= 2)
        _pinta(_estilo.vacio(
            'Hoy ningún mercado de este partido llega al listón',
            f'Hace falta que tu casa pague al menos un 5 % por encima del '
            f'consenso del mercado, y con al menos dos casas respaldando ese '
            f'consenso. De {len(s1) + len(s2) + len(rojo)} mercados, sólo '
            f'{_comparables} tienen ese respaldo: las líneas alternativas las '
            f'publica casi siempre Pinnacle y nadie más. No encontrar nada es '
            f'el resultado correcto, no un fallo — por debajo de ese 5 % el ROI '
            f'medido es −11,5 %.', '🟢') if _estilo else None)
    else:
        _pinta(_estilo.nota(
            "Tu casa paga por encima del consenso del mercado en estos "
            "mercados. Es lo único que este proyecto mide con señal positiva "
            "(+8,22 % de ROI sobre 791 selecciones con ventaja ≥ 5 %). "
            "<b>No es una garantía</b>: el percentil 5 del bootstrap sigue en "
            "−3,12 %, o sea que es la mejor apuesta disponible, no una apuesta "
            "ganadora segura.", 'ok') if _estilo else None)
        _pinta(_estilo.patas([
            _estilo.pata(
                m.get('apuesta', '?'), m.get('cuota_casa'), m.get('prob'),
                m.get('mercado', ''),
                [(f"+{(m.get('ventaja') or 0)*100:.1f} % sobre el mercado", 'ok'),
                 (f"{m.get('n_casas', 1)} casas", 'azul')]
                + ([(str(m['casa']), 'info')] if m.get('casa') else []),
                'ok')
            for m in s1]) if _estilo else None)
        if _estilo is None:
            for m in s1:
                st.write(f"• **{m.get('apuesta')}** @ {m.get('cuota_casa')} "
                         f"· +{(m.get('ventaja') or 0)*100:.1f} % sobre el mercado")

    # --- SECCIÓN 2 ---------------------------------------------------------
    with st.expander(f"🟡 Sección 2 · Alta probabilidad, precio insuficiente "
                     f"({len(s2)})", expanded=not s1):
        _pinta(_estilo.nota(
            "Estos <b>no se juegan en solitario</b>: su precio no paga lo que "
            "arriesgan. Y combinarlos entre sí <b>tampoco lo arregla</b> — "
            "multiplica el margen de la casa: tres patas de −4,76 % dan "
            "−13,62 %. Sirven como relleno puntual de una combinada que ya "
            "parta de la Sección 1.", 'mira') if _estilo else None)
        for m in s2[:25]:
            _pinta(_estilo.pata(
                m.get('apuesta', '?'), m.get('cuota_casa'), m.get('prob'),
                m.get('mercado', ''),
                [(str(m.get('motivo', ''))[:80], 'mira')], 'mira')
                if _estilo else None)
            if _estilo is None:
                st.write(f"• {m.get('apuesta')} @ {m.get('cuota_casa')} "
                         f"— {m.get('motivo')}")
        if len(s2) > 25:
            st.caption(f"… y {len(s2) - 25} más.")

    # --- SECCIÓN 3 ---------------------------------------------------------
    _seccion('🧩 Sección 3 · Combinadas desde la sección verde',
             'sólo con patas que tienen ventaja de precio', 'azul')
    if opciones_s3:
        _pinta(_estilo.nota(
            "Armadas <b>únicamente</b> con patas de la Sección 1. Es la única "
            "forma de que el efecto multiplicador juegue a favor: "
            "<code>EV_parlay = Π(1+EV_i) − 1</code>, así que tres patas de "
            "+4,50 % dan +14,12 % y tres de −4,76 % dan −13,62 %.",
            'azul') if _estilo else None)
        _render_grupo_combinadas(opciones_s3, s1 + s2, criterio='casa_unica')
    else:
        _pinta(_estilo.vacio(
            'No hay material para combinar',
            'Hacen falta al menos dos mercados en la Sección 1. Forzar una '
            'combinada con patas amarillas multiplicaría el margen de la casa '
            'en vez de reducirlo.', '🧩') if _estilo else None)

    # --- LO DESCARTADO, accesible pero fuera ------------------------------
    if rojo:
        with st.expander(f"🔴 Descartados ({len(rojo)}) — por qué no aparecen"):
            st.caption("Tu casa paga por debajo del precio justo del mercado "
                       "en estos mercados. Se retiran de las vistas "
                       "principales, pero no se ocultan: tienes derecho a ver "
                       "qué se descartó y por qué.")
            _pinta(_estilo.tabla(
                ['Mercado', 'Tu casa', 'Justo del mercado', 'Diferencia'],
                [[_html_esc(m.get('apuesta', '?')),
                  f"{m.get('cuota_casa')}",
                  f"{m.get('cuota_mercado') or '—'}",
                  f"{(m.get('ventaja') or 0)*100:+.1f} %"] for m in rojo],
                alineadas=[1, 2, 3]) if _estilo else None)


def _render_grupo_combinadas(opciones: list, mercados: list,
                             criterio: str = 'mercado') -> None:
    """
    Un grupo de combinadas: la recomendada arriba y todas las demás debajo.

    v122 — se extrae de `render_parlay_partido` porque ahora hay DOS grupos que
    se pintan igual y se juzgan distinto: el de la casa del usuario (una sola
    casa, un solo boleto) y el del mejor precio del mercado (varias casas,
    varios boletos). Tenerlo dos veces copiado era garantizar que uno de los
    dos se quedara atrás en el siguiente cambio.

    `criterio` viaja hasta `cuotas_tablon.recomendar_combinada` y decide con
    qué se puntúa: con cuántas patas están comparadas entre casas (mercado) o
    con cuánto paga tu casa frente al resto (casa_unica). Ver allí el porqué.
    """
    if not opciones:
        return
    _una_casa = (criterio == 'casa_unica')
    por_id = {m.get('id'): m for m in (mercados or []) if m.get('id')}

    _rec = None
    try:
        import cuotas_tablon as _ct_r
        _rec = _ct_r.recomendar_combinada(opciones, mercados, criterio=criterio)
    except Exception:
        _rec = None
    _firma_rec = (tuple(sorted(s['apuesta'] for s in _rec['selecciones']))
                  if _rec else None)

    def _patas_html(op) -> str:
        """Las patas de una opción, con lo que matiza cada una."""
        if _estilo is None:
            return ''
        trozos = []
        for s in op.get('selecciones') or []:
            m = por_id.get(s.get('id')) or {}
            etqs, extra = [], ''
            if _una_casa:
                # Lo que importa aquí no es el EV: es si tu casa paga bien esa
                # pata comparada con el resto del mercado. Es la única cifra
                # que no depende de que el modelo acierte.
                d = m.get('dif_vs_mercado')
                if d is not None:
                    etqs.append((f'{d*100:+.1f} % vs {m.get("casa_mercado")}',
                                 _estilo.tono_por_diferencia(d)))
                    extra = _estilo.medidor_precio(
                        d, 'Playdoit', m.get('casa_mercado') or 'el mercado')
                else:
                    etqs.append(('sin precio con el que comparar', 'info'))
                tono = (_estilo.tono_por_diferencia(d) if d is not None
                        else 'info')
            else:
                n_c = m.get('n_casas') or 1
                etqs.append((f'{n_c} casas comparadas', 'ok') if n_c >= 2
                            else ('una sola casa', 'info'))
                if m.get('casa'):
                    etqs.append((str(m['casa']), 'azul'))
                tono = _estilo.tono_por_ev(m.get('ev'), n_c,
                                           bool(m.get('ev_sospechoso')))
            if m.get('ev_sospechoso'):
                etqs.append(('⚠️ EV demasiado alto para ser real', 'mira'))
            trozos.append(_estilo.pata(
                s.get('apuesta', '?'), s.get('cuota'), s.get('prob'),
                s.get('mercado', ''), etqs, tono) + extra)
        return _estilo.patas(trozos)

    def _texto_copiable(op) -> str:
        t = "\n".join(f"{j}. {s['apuesta']} @ {s['cuota']}"
                      for j, s in enumerate(op['selecciones'], 1))
        return (t + f"\nCuota combinada: {op['cuota_combinada']:.2f} · "
                f"Prob: {op['prob_conjunta']*100:.0f}%"
                + ("\nCasa: Playdoit (todas las patas)" if _una_casa else ''))

    if _rec:
        with st.container(border=True):
            _pinta(_estilo.seccion(f"⭐ Recomendada — {_rec['etiqueta_opcion']}",
                                   '', 'ok') if _estilo else None)
            if _estilo is None:
                st.markdown(f"### ⭐ Recomendada — {_rec['etiqueta_opcion']}")
            _pinta(_estilo.ticket(_rec['cuota_combinada'],
                                  _rec['prob_conjunta']) if _estilo else None)
            _pinta(_patas_html(_rec))
            if _estilo is None:
                for s in _rec['selecciones']:
                    st.write(f"• **{s['apuesta']}** @ {s['cuota']} · "
                             f"{s['prob']*100:.0f}%")
            st.markdown("**Por qué ésta:**")
            for _m in _rec.get('motivo_recomendacion', []):
                st.markdown(f"- {_m}")
            with st.expander("📋 Copiar esta combinada"):
                st.code(_texto_copiable(_rec), language=None)

    _seccion("Todas las opciones", "elige la que prefieras", 'info')
    for i, op in enumerate(opciones):
        _firma = tuple(sorted(s['apuesta'] for s in op['selecciones']))
        with st.container(border=True):
            st.markdown(
                ("⭐ " if _firma == _firma_rec else "")
                + f"**{op['etiqueta_opcion']}** · {op['n_selecciones']} patas"
                + (f"  \n{op['descripcion_opcion']}"
                   if op.get('descripcion_opcion') else ''))
            _pinta(_estilo.ticket(op['cuota_combinada'],
                                  op['prob_conjunta']) if _estilo else None)
            if _estilo is None:
                c1, c2 = st.columns(2)
                c1.metric("Prob. de acertar todo",
                          f"{op['prob_conjunta']*100:.0f}%")
                c2.metric("Cuota combinada", f"{op['cuota_combinada']:.2f}")
            _pinta(_patas_html(op))
            if _estilo is None:
                for s in op['selecciones']:
                    st.write(f"• **{s['apuesta']}** @ {s['cuota']} · "
                             f"{s['prob']*100:.0f}%")
            if op.get('avisos'):
                for av in op['avisos']:
                    st.caption(av)
            with st.expander("📋 Copiar esta combinada"):
                st.code(_texto_copiable(op), language=None)


def render_parlay_partido(motor, home: str, away: str, key: str):
    """Sección interactiva de parlay para EL partido en pantalla."""
    # v58.1 FIX: este símbolo se importa MÁS ABAJO dentro de esta misma función
    # (bloque de Kelly), lo que lo convierte en local para todo el cuerpo. Sin
    # este import al principio, usarlo antes lanzaba UnboundLocalError en
    # producción al pulsar «Proponer parlays». Se importa aquí una sola vez.
    from bankroll_manager import AVISO_JUEGO_RESPONSABLE

    # v147 — LA PLANTILLA SE CALCULA UNA VEZ, NO OCHO.
    #
    # Esta función pedía `motor.plantilla_club(home, away)` en OCHO sitios
    # distintos, cada uno recalculándola entera. Medido sobre `liga_mx`:
    #
    #     plantilla_club, 1.ª llamada .... 12,3 s
    #     plantilla_club, 2.ª llamada ....  0,4 s
    #
    # O sea que el trabajo ya era cacheable —la segunda llamada es 30 veces más
    # rápida— y lo que faltaba era usar la caché. Los 12 s que el usuario nota
    # al pulsar «Ver» no son renderizado pesado: son el mismo cálculo repetido.
    #
    # `_pl()` lo resuelve en dos niveles:
    #   1. memo local, para que dentro de UN render se calcule una sola vez;
    #   2. `plantilla_club_cacheada`, para que entre reruns de Streamlit
    #      tampoco se repita.
    #
    # El nivel 2 sólo se puede usar cuando `key` es de verdad una clave de liga:
    # esta función la llaman también MLB (`key='mlb'`), el tenis
    # (`key='tenis_atp'`) y la vista de selecciones (`key='mundial'`), donde el
    # motor no es un `ClubEngine`. Ahí se cae al nivel 1, que ya elimina siete
    # de los ocho cálculos.
    _memo_pl = {}

    def _pl():
        """La plantilla de este partido, calculada una sola vez."""
        if 'v' in _memo_pl:
            return _memo_pl['v']
        try:
            import config as _cfg_pl
            if hasattr(motor, 'plantilla_club') and key in _cfg_pl.LEAGUES:
                _memo_pl['v'] = plantilla_club_cacheada(key, home, away)
            elif hasattr(motor, 'plantilla_club'):
                _memo_pl['v'] = motor.plantilla_club(home, away)
            else:
                _memo_pl['v'] = motor.plantilla(home, away)
        except Exception as _e_pl:
            logger.warning(f'[parlay] plantilla no disponible: {_e_pl}')
            _memo_pl['v'] = {}
        return _memo_pl['v']

    # v58: VARIAS combinadas propuestas automáticamente + copiar estadísticas.
    # Universal: funciona con cualquier motor (fútbol, MLB, ...).
    st.markdown("#### 🎲 Parlays propuestos con cuotas")
    if _ayuda is not None:
        _ayuda.render(st, 'combinadas')
    st.caption("La app arma varias combinadas de ESTE partido con distintos "
               "perfiles (de la más segura a la de más cuota), con su "
               "probabilidad real de acertar todo y la cuota combinada.")
    cmp1, cmp2 = st.columns([2, 1])
    _solo_reales = cmp2.checkbox("Solo cuotas reales", value=False,
                                 key=f"mpv_reales_{key}",
                                 help="Limita a mercados con cuota vigente "
                                      "(EV accionable).")
    if cmp1.button("🎲 Proponer parlays con cuotas", key=f"mpv_btn_{key}",
                   type="primary", width='stretch'):
        from match_parlay import proponer_parlays
        with st.spinner("Buscando las mejores combinadas del partido…"):
            # v114 — LAS COMBINADAS SE ARMAN CON EL PRECIO REAL DE LAS CASAS.
            #
            # Antes el motor puntuaba casi todas las patas con cuota justa
            # (1/prob), y con cuota justa el EV de toda pata vale 0 por
            # construcción: el constructor sólo podía ordenar por
            # probabilidad. Ahora recibe el MEJOR precio de las seis casas
            # para cada mercado, así que puede ver cuál paga de más, que es lo
            # que el usuario pidió. Si el tablón no cubre el partido, esto
            # devuelve el motor tal cual y todo sigue como antes.
            _m_parlay, _n_reales = motor, 0
            try:
                import cuotas_tablon as _ct
                _dep_tab = ('tenis' if str(key).startswith('tenis')
                            else 'mlb' if key in ('mlb', 'kbo')
                            else 'nba' if key == 'nba' else 'futbol')
                _m_parlay, _n_reales = _ct.motor_con_tablon(
                    motor, home, away, deporte=_dep_tab)
            except Exception:
                pass
            opciones = proponer_parlays(
                _m_parlay, home, away, max_opciones=5,
                solo_cuotas_reales=_solo_reales,
                bankroll=float(st.session_state.get('bankroll', 0) or 0))
            # v114 — y aparte, la combinada SÓLO con mercados que tienen
            # precio de casa. Una combinada que mezcla cuota real y cuota
            # justa anuncia una «cuota combinada» que ninguna casa va a pagar:
            # sirve para ordenar, no para cobrar. Esta otra sí es la de verdad.
            _ops_ev, _mk_ev = [], []
            if _n_reales >= 2 and not _solo_reales:
                try:
                    # v114 — VARIAS opciones, no una. Antes se pedían 3 pero
                    # con sólo cinco mercados cotizados el motor no podía
                    # construir más de una: el material lo daban las líneas
                    # alternativas de Pinnacle, que hasta esta versión se
                    # tiraban. Ahora hay veinte mercados con precio y se piden
                    # los cuatro perfiles para que el usuario elija.
                    _ops_ev = proponer_parlays(
                        _m_parlay, home, away, max_opciones=6,
                        solo_cuotas_reales=True,
                        bankroll=float(st.session_state.get('bankroll', 0) or 0))
                    import cuotas_multi as _cm_ev
                    import cuotas_tablon as _ct_ev
                    _pl_ev = _pl()
                    # v127: con `liga`, para que el consenso ampliado de The
                    # Odds API entre también en las combinadas. Sin ella, la
                    # Sección 1 se compararía contra cinco casas mientras la
                    # ficha de cuotas usa veinte, y los dos números no
                    # cuadrarían.
                    _res_ev = _cm_ev.cuotas_partido(
                        _dep_tab, home, away,
                        liga=(getattr(motor, 'clave', None) or key))
                    _mk_ev = _ct_ev.marcar_ev_sospechoso(
                        _ct_ev.mercados_con_ev(_res_ev, _pl_ev, home, away))
                except Exception:
                    # sin combinada de EV real la pantalla sigue entera: las
                    # combinadas normales de arriba no dependen de ésta
                    _ops_ev, _mk_ev = [], []
            # v122 — Y LA QUE DE VERDAD SE PUEDE PONER: SÓLO EN TU CASA.
            #
            # El usuario lo dijo así: «en el mundo real no es posible hacer
            # cuotas con diferentes casas. Quiero que me des cuotas también
            # pero solo con la casa de Playdoit que es la mía».
            #
            # Y es correcto: la combinada de arriba coge el mejor precio de
            # cada mercado venga de donde venga, así que sus tres patas pueden
            # estar en tres casas distintas. Eso no es un ticket, son tres
            # apuestas — y la «cuota combinada» que anuncia no la paga nadie.
            # Ésta sí: todas las patas con precio publicado por Playdoit, y
            # además con cuánto se deja frente al mejor precio del mercado en
            # cada una, que es la cifra que no depende de que el modelo
            # acierte.
            _ops_pdt, _mk_pdt, _n_pdt = [], [], 0
            try:
                import cuotas_tablon as _ct_p
                _m_pdt, _n_pdt, _det_pdt = _ct_p.motor_solo_playdoit(
                    motor, home, away, deporte=_dep_tab)
                if _n_pdt >= 2:
                    _ops_pdt = proponer_parlays(
                        _m_pdt, home, away, max_opciones=6,
                        solo_cuotas_reales=True,
                        bankroll=float(st.session_state.get('bankroll', 0) or 0))
                    _pl_p = _pl()
                    _mk_pdt = _ct_p.marcar_ev_sospechoso(
                        _ct_p.comparar_con_el_mercado(
                            _ct_p.mercados_playdoit_con_ev(
                                _det_pdt, _pl_p, home, away),
                            _mk_ev))
            except Exception:
                _ops_pdt, _mk_pdt, _n_pdt = [], [], 0

            # v125 — EL CLASIFICADOR: TRES SECCIONES Y COMBINADAS DESDE LA 1.
            #
            # El semáforo no mira el EV del modelo: mira si tu casa paga por
            # encima del consenso del mercado, y por cuánto. El umbral es 5 % y
            # no 0 % porque está medido: entre 0 % y 5 % el ROI es −11,48 %
            # (n=623) y por encima de 5 % es +8,22 % (n=791). Ver
            # `clasificador.py` y BITACORA_ARQUITECTURA.md.
            #
            # Y la Sección 3 se arma SÓLO con patas de la Sección 1. La
            # aritmética no deja otra: juntar patas de EV negativo multiplica
            # la pérdida (tres de −4,76 % dan −13,62 %).
            _clas, _ops_s3 = None, []
            try:
                import clasificador as _cla
                _bt_liga = (getattr(motor, 'metadata', {}) or {}).get(
                    'precision_validacion')
                _techo_liga = (getattr(motor, 'metadata', {}) or {}).get(
                    'precision_mercado_cuotas')
                _clas = _cla.clasificar(_mk_pdt, _bt_liga, _techo_liga)
                _ids_ok = set(_cla.ids_para_parlay(_clas))
                if len(_ids_ok) >= 2:
                    # el motor se envuelve SÓLO con los precios de la Sección 1
                    # (más el relleno permitido), así que `solo_cuotas_reales`
                    # deja fuera todo lo demás sin tocar el constructor
                    _cu_s3 = {m['id']: float(m['cuota_casa'])
                              for m in (_clas['seccion1'] + _clas['seccion2'])
                              if m.get('id') in _ids_ok and m.get('cuota_casa')}
                    _ca_s3 = {m['id']: m.get('casa')
                              for m in (_clas['seccion1'] + _clas['seccion2'])
                              if m.get('id') in _ids_ok}
                    if len(_cu_s3) >= 2:
                        _ops_s3 = proponer_parlays(
                            _ct_p.MotorConTablon(motor, _cu_s3, _ca_s3),
                            home, away, max_opciones=6,
                            solo_cuotas_reales=True,
                            bankroll=float(
                                st.session_state.get('bankroll', 0) or 0))
            except Exception:
                _clas, _ops_s3 = None, []
        # v115 — LAS COMBINADAS PROPUESTAS SE REGISTRAN.
        #
        # Sin esto no hay forma de saber si las que la app propone entran o no,
        # que es exactamente el agujero que la auditoría puso como prioridad
        # nº 1. Cada pata se guarda como un pick normal con canal
        # `combinada:<perfil>`, así la resuelve el liquidador de siempre y la
        # combinada se da por acertada sólo si aciertan todas.
        #
        # Se registran las de CUOTA REAL, no las de cuota justa: una combinada
        # con precio inventado no se puede juzgar contra nada.
        try:
            import liquidador_ponches as _lp_reg
            _liga_reg = NOMBRES_LIGAS.get(getattr(motor, 'clave', ''), key)
            _dep_reg = ('Tenis' if str(key).startswith('tenis')
                        else 'MLB' if key in ('mlb', 'kbo')
                        else 'NBA' if key == 'nba' else 'Fútbol')
            for _op in (_ops_ev or []):
                _lp_reg.registrar_combinada(
                    f'{home} vs {away}', _op, liga=_liga_reg, deporte=_dep_reg)
            # v122 — las de una sola casa se registran IGUAL, y con su propio
            # canal. Son las que el usuario va a poner de verdad, así que son
            # las que más falta hace juzgar contra el resultado; mezclarlas con
            # las de mejor precio en el mismo canal impediría comparar las dos
            # políticas dentro de unas semanas, que es justo lo interesante.
            for _op in (_ops_pdt or []):
                _op_reg = dict(_op)
                _op_reg['etiqueta_opcion'] = (
                    f"playdoit · {_op.get('etiqueta_opcion', '')}")
                _lp_reg.registrar_combinada(
                    f'{home} vs {away}', _op_reg, liga=_liga_reg,
                    deporte=_dep_reg)
        except Exception:
            pass
        # v62: se guardan en sesión para que el botón de Telegram (que provoca
        # un rerun) siga teniéndolas disponibles.
        st.session_state[f'parlays_{key}'] = {
            'partido': f'{home} vs {away}', 'opciones': opciones,
            'n_reales': _n_reales, 'opciones_ev': _ops_ev,
            'mercados_ev': _mk_ev, 'opciones_pdt': _ops_pdt,
            'mercados_pdt': _mk_pdt, 'n_pdt': _n_pdt,
            'clasificacion': _clas, 'opciones_s3': _ops_s3}

    # v62: el RENDER se hace desde la sesión (no dentro del bloque del botón),
    # así las combinadas siguen en pantalla tras pulsar «Enviar a Telegram»
    # (que provoca un rerun). Universal: fútbol, MLB, tenis, internacional...
    _guardado = st.session_state.get(f'parlays_{key}') or {}
    _vigente = _guardado.get('partido') == f'{home} vs {away}'
    if _vigente:
        opciones = _guardado.get('opciones') or []
        if not opciones:
            st.warning("No hay combinadas que superen el listón de "
                       "probabilidad para este partido (no se fuerzan parlays "
                       "soñadores).")
        else:
            # v114: de dónde salen los precios con los que se han armado
            _nr = _guardado.get('n_reales') or 0
            _np = _guardado.get('n_pdt') or 0
            _pinta(_estilo.kpis([
                {'valor': len(opciones), 'etiqueta': 'Combinadas',
                 'tono': 'azul', 'sub': 'de este partido'},
                {'valor': _np or '—', 'etiqueta': 'En tu casa',
                 'tono': 'ok' if _np else 'info',
                 'sub': 'mercados con precio en Playdoit'},
                {'valor': _nr or '—', 'etiqueta': 'En el mercado',
                 'tono': 'azul' if _nr else 'info',
                 'sub': 'mercados al mejor precio de 6 casas'},
            ]) if _estilo else None)
            if not _nr:
                st.caption("ℹ️ Ninguna casa cotiza todavía este partido, así "
                           "que las patas van con **cuota justa** "
                           "(1/probabilidad). La cuota combinada es "
                           "orientativa, no la que te van a pagar.")

            # v123 — ¿ESTÁ EL PARTIDO PAREJO? ENTONCES EL 1X2 NO ES LA ÚNICA
            # FORMA DE JUGARLO.
            #
            # Pedido del usuario: «en partidos que sean parejos deberías
            # también evaluar en el modelo no irte tanto por un ganador, si no
            # ver si es mejor irte por doble oportunidad».
            #
            # Va ANTES de las combinadas a propósito: es una decisión sobre qué
            # mercado jugar, y se toma antes de decidir con qué combinarlo.
            # Los cuatro se leen de la SESIÓN y aquí arriba, antes del primer
            # uso. Dentro del bloque del botón existen como locales, pero en un
            # rerun sin pulsarlo no estarían definidas y el primero que las
            # tocara reventaría con UnboundLocalError — que es literalmente el
            # fallo que llegó a producción en la v58.1 y por el que existe
            # `smoke_botones.py`.
            _ops_pdt = _guardado.get('opciones_pdt') or []
            _mk_pdt = _guardado.get('mercados_pdt') or []
            _ops_ev = _guardado.get('opciones_ev') or []
            _mk_ev = _guardado.get('mercados_ev') or []
            _clas = _guardado.get('clasificacion') or None
            _ops_s3 = _guardado.get('opciones_s3') or []

            # v125 — LAS TRES SECCIONES, ANTES QUE NADA.
            #
            # Es el orden de decisión: primero qué se puede jugar solo, luego
            # qué sólo sirve de pata, y al final con qué se combina. Todo lo
            # demás de esta pantalla es material de apoyo.
            if _clas:
                _renderizar_secciones(_clas, _ops_s3)

            try:
                import partido_parejo as _pp
                _pl_pj = _pl()
                # se prefiere el tablero de la casa del usuario: los dos
                # márgenes que compara tienen que ser del MISMO libro
                _an_pj = _pp.comparar(_pl_pj, _mk_pdt or _mk_ev, home, away)
            except Exception:
                _an_pj = None
            if _an_pj:
                _seccion(
                    ("⚖️ Este partido está parejo — mira la doble oportunidad"
                     if _an_pj.get('parejo')
                     else "⚖️ Ganador o doble oportunidad"),
                    _an_pj.get('motivo', ''),
                    'mira' if _an_pj.get('parejo') else 'info')
                _pinta(_estilo.barra_1x2(
                    _an_pj['p_home'], _an_pj['p_draw'], _an_pj['p_away'],
                    home, away) if _estilo else None)
                _filas_pj = []
                for _f in _an_pj.get('lados', []):
                    if not (_f.get('cuota_gana') and _f.get('cuota_doble')):
                        continue
                    _filas_pj.append([
                        _html_esc(_f['etiqueta_gana']),
                        f"{_f['prob_gana']*100:.0f} %",
                        f"{_f['cuota_gana']:.2f}",
                        _html_esc(_f['etiqueta_doble']),
                        f"{_f['prob_doble']*100:.0f} %",
                        f"{_f['cuota_doble']:.2f}",
                        (_estilo.pildora(f"{_f['prob_extra']*100:+.0f} pts / "
                                         f"{_f['cuota_menos']*100:.0f} %",
                                         'mira') if _estilo else ''),
                    ])
                if _filas_pj and _estilo is not None:
                    _pinta(_estilo.tabla(
                        ['Ganador', 'Acierta', 'Paga', 'Doble oportunidad',
                         'Acierta', 'Paga', 'Cubres más / pagas menos'],
                        _filas_pj, alineadas=[1, 2, 4, 5, 6]))
                for _fr in _pp.frases(_an_pj):
                    st.markdown(f"- {_fr}")

            if _ops_pdt:
                _seccion("💚 En TU casa — Playdoit", "un solo ticket, "
                         "colocable tal cual", 'ok')
                _pinta(_estilo.nota(
                    "Todas las patas tienen precio publicado <b>por Playdoit</b>, "
                    "así que esta cuota combinada la puedes poner en un solo "
                    "boleto. Debajo de cada pata verás cuánto paga tu casa "
                    "frente al mejor precio del mercado: es la única cifra de "
                    "esta pantalla que <b>no depende de que el modelo "
                    "acierte</b>, porque son dos precios del mismo suceso.",
                    'ok', 'Lo que de verdad puedes jugar.') if _estilo else None)
                st.caption(
                    "⚠️ Si tu casa no admite combinar dos mercados del MISMO "
                    "partido en un boleto (lo que se suele llamar «crea tu "
                    "apuesta»), tendrás que jugarlas por separado. El precio de "
                    "cada pata es real en cualquier caso.")
                # v123 — QUÉ FAMILIAS DE MERCADO HAY PARA COMBINAR, Y CUÁLES NO.
                #
                # El usuario pidió «combinadas de córners, tarjetas, tiempos».
                # De las tres sólo una tiene precio, y medido: en Monterrey vs
                # Juárez, Playdoit publica 148 mercados y **cero** de córners o
                # tarjetas. Decirlo aquí es lo único honesto — armar esas
                # combinadas con cuota justa sería inventar el precio.
                _fams = {}
                for _m_f in _mk_pdt:
                    _fams[_m_f.get('familia') or '—'] = \
                        _fams.get(_m_f.get('familia') or '—', 0) + 1
                if _fams:
                    _pinta(_estilo.kpis([
                        {'valor': _v, 'etiqueta': _k, 'tono': 'info'}
                        for _k, _v in sorted(_fams.items(),
                                             key=lambda x: -x[1])]
                    ) if _estilo else None)
                if any(_m_f.get('ev_no_fiable') for _m_f in _mk_pdt):
                    _pinta(_estilo.nota(
                        "Los mercados de <b>1ª y 2ª mitad</b> sí tienen precio "
                        "real y se pueden combinar, pero su EV va marcado como "
                        "no fiable: el modelo reparte los goles a partes "
                        "iguales entre las dos mitades —da la misma "
                        "probabilidad a las dos— y en el fútbol real se marca "
                        "alrededor del 55 % de los goles en la segunda. Ese EV "
                        "mide lo que al modelo le falta, no valor.",
                        'mira', 'Tiempos: precio sí, EV no.') if _estilo else None)
                _pinta(_estilo.nota(
                    "<b>Córners y tarjetas no se pueden combinar aquí</b>: "
                    "ninguna de las seis casas del tablón publica precio para "
                    "ellos, y una combinada con cuota justa es una cuota "
                    "inventada. Lo que sí tienes es el histórico del cruce "
                    "—medias y porcentajes por línea— en «Cara a cara», para "
                    "compararlo a mano con lo que te ofrezca tu casa.",
                    'info') if _estilo else None)
                _render_grupo_combinadas(_ops_pdt, _mk_pdt,
                                         criterio='casa_unica')
            elif _estilo is not None:
                # Que la sección no aparezca sería peor que decir por qué: el
                # usuario la pidió expresamente y un hueco se lee como avería.
                _seccion("💚 En TU casa — Playdoit", 'sin tablero hoy', 'info')
                _pinta(_estilo.vacio(
                    "Playdoit no cotiza este partido todavía",
                    "Para armar una combinada de un solo boleto hacen falta al "
                    "menos dos mercados con precio publicado por tu casa, y hoy "
                    "no los tiene. Puede ser una liga que no cubre o que aún no "
                    "ha abierto línea: suele hacerlo 2-4 días antes.", '💚'))

            # v114 — LA COMBINADA POR EV REAL, en su propia sección.
            #
            # Ésta es la que responde a lo que el usuario pidió en la v114:
            # «propón un parlay en base a las cuotas reales automáticas». Todas
            # sus patas tienen precio publicado por una casa, pero NO por la
            # misma casa — por eso desde la v122 va después de la de Playdoit y
            # dice con todas las letras que son varios tickets.
            # (`_ops_ev` y `_mk_ev` se leen de la sesión más arriba, junto con
            # los de Playdoit, porque la sección de partido parejo ya los usa.)
            if _ops_ev:
                _seccion("💰 Al mejor precio del mercado",
                         "reparte patas entre varias casas", 'azul')
                _pinta(_estilo.nota(
                    "Cada pata va a la casa que mejor la paga, así que esta "
                    "cuota es la mejor posible <b>pero requiere cuenta en "
                    "varias casas</b> y son apuestas separadas, no un boleto. "
                    "Sirve para dos cosas: ver el techo de precio que existe, "
                    "y decidir si compensa abrir una segunda cuenta.",
                    'azul', 'Ojo: esto son varios tickets.') if _estilo else None)
                st.caption(
                    "**Aviso medido**: el proyecto tiene comprobado que apostar "
                    "por la probabilidad del modelo pierde entre −4,66 % y "
                    "−6,52 % (37.158 apuestas), y que el EV que declara es "
                    "*anti*-indicador del cierre. Lo que sí mide positivo es "
                    "comprar al mejor precio. Trata el EV como «esta casa paga "
                    "más que las otras», no como «esto gana dinero».")
                _render_grupo_combinadas(_ops_ev, _mk_ev)

            # v114 — el CONTEXTO que el usuario pidió tener a la vista al
            # decidir la combinada: historial del cruce, forma y clasificación.
            # Es el mismo texto del panel de equipos, aquí resumido, para no
            # tener que subir a buscarlo.
            try:
                _cl_ctx = getattr(motor, 'clave', None)
                if _cl_ctx:
                    import panel_equipos as _pe
                    _frases = _pe.lectura(_cl_ctx, home, away, None)
                    if _frases:
                        with st.expander("📊 Contexto del cruce (historial, "
                                         "forma y clasificación)",
                                         expanded=True):
                            for _fr in _frases:
                                st.markdown(f"- {_fr}")
                            st.caption(
                                "Esto es para JUZGAR la combinada, no una "
                                "señal aparte: el historial y la forma ya "
                                "están dentro del modelo (el ELO los absorbe "
                                "partido a partido), así que ver aquí que un "
                                "equipo domina no significa que haya valor.")
            except Exception:
                pass
            # Las de SIEMPRE, que mezclan precio real y cuota justa. Van las
            # últimas y en un desplegable desde la v122: sirven para ordenar
            # ideas, no para cobrar, y tenerlas al mismo nivel que las dos de
            # arriba invita a confundir una cuota inventada con un precio.
            with st.expander(f"🧮 Todas las combinadas posibles "
                             f"({len(opciones)}) — incluidas las que van con "
                             f"cuota justa", expanded=not (_ops_pdt or _ops_ev)):
                _pinta(_estilo.nota(
                    "Aquí entran también los mercados que <b>ninguna casa ha "
                    "cotizado</b>: esas patas van con cuota justa "
                    "(1 ÷ probabilidad), que no es un precio que puedas tomar. "
                    "La cuota combinada de esas opciones es orientativa.",
                    'mira') if _estilo else None)
                for i, op in enumerate(opciones, 1):
                    with st.container(border=True):
                        st.markdown(f"**{op['etiqueta_opcion']}** · "
                                    f"{op['n_selecciones']} patas  \n"
                                    f"{op['descripcion_opcion']}")
                        _pinta(_estilo.ticket(op['cuota_combinada'],
                                              op['prob_conjunta'])
                               if _estilo else None)
                        if _estilo is None:
                            oc2, oc3 = st.columns(2)
                            oc2.metric("Prob. de acertar todo",
                                       f"{op['prob_conjunta']*100:.0f}%")
                            oc3.metric("Cuota combinada",
                                       f"{op['cuota_combinada']:.2f}")
                        if _estilo is not None:
                            _pinta(_estilo.patas([
                                _estilo.pata(
                                    s['apuesta'], s['cuota'], s['prob'],
                                    s['mercado'],
                                    [('cuota real de casa', 'ok')]
                                    if s.get('cuota_fuente') == 'real'
                                    else [('cuota justa, no es un precio',
                                           'mira')],
                                    'ok' if s.get('cuota_fuente') == 'real'
                                    else 'mira')
                                for s in op['selecciones']]))
                        else:
                            for s in op['selecciones']:
                                st.write(
                                    f"• [{s['mercado']}] **{s['apuesta']}** "
                                    f"@ {s['cuota']} · {s['prob']*100:.0f}%"
                                    + ("  ·  cuota real"
                                       if s.get('cuota_fuente') == 'real'
                                       else ""))
                        if op.get('avisos'):
                            for av in op['avisos']:
                                st.caption(av)
                        _txt = "\n".join(
                            f"{j}. [{s['mercado']}] {s['apuesta']} @ {s['cuota']} "
                            f"(p={s['prob']*100:.0f}%)"
                            for j, s in enumerate(op['selecciones'], 1))
                        _txt += (f"\nCuota combinada: "
                                 f"{op['cuota_combinada']:.2f} · "
                                 f"Prob: {op['prob_conjunta']*100:.1f}%")
                        with st.expander("📋 Copiar esta combinada"):
                            st.code(_txt, language=None)
            st.caption("⚠️ Con cuotas justas del modelo el EV es teórico: "
                       "compara contra tu casa. " + AVISO_JUEGO_RESPONSABLE)

    if _vigente and _guardado.get('opciones'):
        if st.button("📲 Enviar estos parlays a Telegram",
                     key=f"mpv_tg_{key}", width='stretch'):
            try:
                import bot_telegram
                _comp = (getattr(motor, 'deporte', None)
                         or NOMBRES_LIGAS.get(key, key))
                msg = bot_telegram.formatear_parlays(
                    _guardado['partido'], _guardado['opciones'], str(_comp))
                if bot_telegram.enviar(msg):
                    st.success("✅ Parlays enviados a Telegram.")
                else:
                    st.warning("Sin TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID en "
                               "los Secrets. Vista previa del mensaje:")
                    st.code(msg, language=None)
            except Exception as e:
                st.error(f"No se pudo enviar ({type(e).__name__}: {e}).")

    # v64: CUOTAS REALES AUTOMÁTICAS (ESPN core: 1X2, O/U, HÁNDICAP y props de
    # jugador con cuota decimal). Sin pegar nada, sin clave y sin scraping.
    if key in NOMBRES_LIGAS or key in getattr(motor, 'clave', ''):
        with st.expander("💰 Cuotas reales AUTOMÁTICAS + EV", expanded=False):
            st.caption("Cuotas de casa descargadas automáticamente (1X2, "
                       "over/under, **hándicap** y props de jugador) y cruzadas "
                       "con el modelo para darte el EV real de cada mercado.")
            _clave_liga_auto = getattr(motor, 'clave', None) or key
            # v71: sin botón. Las cuotas se descargan solas al abrir el
            # desplegable; el resultado se cachea 30 min en `cuotas_multi`, así
            # que abrirlo no cuesta una petición nueva cada vez.
            # v114 — LAS DOS VÍAS, NO UNA U OTRA.
            #
            # Esto era un `if/else`: con `event_id` de ESPN se enseñaba la
            # tabla rica y SIN él sólo el 1X2 multi-casa. Como el `event_id`
            # falla justo en las competiciones europeas (los equipos de fase
            # previa no están en el catálogo del motor, ver los registros de
            # `name_mapper` con contexto «evid»), la Champions, la Conference
            # y la Eredivisie se quedaban con tres cuotas.
            #
            # Ahora el tablón multi-casa se enseña SIEMPRE —es el que trae las
            # seis casas y, con ellas, el mejor precio— y la vía de ESPN se
            # suma cuando existe, porque aporta lo único que la otra no tiene:
            # los props de jugador.
            if True:
                try:
                    import cuotas_auto as _ca
                    with st.spinner("Descargando cuotas reales…"):
                        _plc = _pl()
                        _mostrar_cuotas_multi(_clave_liga_auto, home, away,
                                              plantilla=_plc)
                        _eid = _ca.buscar_event_id(_clave_liga_auto, home, away)
                        if _eid:
                            _res = _ca.evaluar(_clave_liga_auto, home, away,
                                               _eid, _plc)
                            if _res:
                                st.markdown("---")
                                st.markdown(
                                    "**➕ Mercados adicionales de ESPN** "
                                    "(incluye props de jugador, que el tablón "
                                    "multi-casa no publica)")
                                _pos = [r for r in _res if r['ev'] > 0]
                                st.success(f"**{len(_res)} mercados** con cuota "
                                           f"real de *{_res[0]['casa']}* · "
                                           f"**{len(_pos)} con EV positivo**.")
                                import pandas as _pd
                                st.dataframe(_pd.DataFrame([{
                                    'Mercado': r['apuesta'],
                                    'Cuota casa': r['cuota_casa'],
                                    'Cuota justa': r['cuota_justa'],
                                    'Prob. modelo': f"{r['prob']*100:.0f}%",
                                    'EV': f"{r['ev']*100:+.1f}%",
                                } for r in _res]), hide_index=True,
                                    width='stretch')
                                st.caption("EV = cuota real × probabilidad del "
                                           "modelo − 1. " + AVISO_JUEGO_RESPONSABLE)
                except Exception as e:
                    st.error(f"No se pudo obtener ({type(e).__name__}: {e}).")

    # v63: PEGAR LAS CUOTAS DE TU CASA → EV real por mercado (RESPALDO manual
    # para casas que no cubre la vía automática).
    with st.expander("✍️ Pegar cuotas de otra casa (opcional)"):
        st.caption("Copia de tu casa de apuestas los mercados con sus cuotas "
                   "(texto o el HTML del inspector) y pégalo aquí. Se cruzan "
                   "con el modelo y se calcula el **EV real** de cada uno. "
                   "Funciona con cualquier casa.")
        _casa = st.text_input("Casa de apuestas", value="", key=f"cm_casa_{key}",
                              placeholder="Playdoit, Caliente, Bet365...")
        _pegado = st.text_area(
            "Cuotas pegadas", height=160, key=f"cm_txt_{key}",
            placeholder="Gana Atlante 2.55\nEmpate 3.10\n"
                        "Menos de 2.5 goles 1.95\nAmbos marcan: Sí 1.72")
        if st.button("💰 Calcular EV con estas cuotas", key=f"cm_btn_{key}"):
            if not _pegado.strip():
                st.warning("Pega primero las cuotas.")
            else:
                try:
                    import cuotas_manual as _cm
                    _pl_cm = _pl()
                    _filas = _cm.parsear(_pegado)
                    _res = _cm.cruzar_con_plantilla(_filas, _pl_cm)
                    if not _res:
                        st.warning(f"Detecté {len(_filas)} cuotas pero ninguna "
                                   "coincide con los mercados del modelo. "
                                   "Revisa que el texto incluya el nombre del "
                                   "mercado junto a la cuota.")
                    else:
                        _cm.guardar(f'{home} vs {away}', _casa or 'casa', _res)
                        _pos = [r for r in _res if r['ev'] > 0]
                        st.success(f"{len(_res)} mercados cruzados · "
                                   f"**{len(_pos)} con EV positivo**.")
                        import pandas as _pd
                        st.dataframe(_pd.DataFrame([{
                            'Mercado': r['apuesta'],
                            'Cuota casa': r['cuota_casa'],
                            'Cuota justa': r['cuota_justa'],
                            'Prob. modelo': f"{r['prob']*100:.0f}%",
                            'EV': f"{r['ev']*100:+.1f}%",
                        } for r in _res]), hide_index=True, width='stretch')
                        st.caption("EV = cuota de tu casa × probabilidad del "
                                   "modelo − 1. Positivo = la casa paga de más "
                                   "según el modelo. " + AVISO_JUEGO_RESPONSABLE)
                except Exception as e:
                    st.error(f"No se pudo procesar ({type(e).__name__}: {e}).")

    # v58: copiar TODAS las estadísticas del partido (universal)
    with st.expander("📋 Copiar todas las estadísticas de este partido"):
        try:
            from match_parlay import plantilla_a_texto
            _pl_txt = _pl()
            _texto = plantilla_a_texto(_pl_txt)
            st.code(_texto, language=None)
            st.download_button("⬇️ Descargar (.txt)", data=_texto.encode('utf-8'),
                               file_name=f"stats_{home}_vs_{away}.txt".replace(' ', '_'),
                               mime='text/plain', key=f"dl_stats_{key}")
        except Exception as e:
            st.caption(f"No disponible ahora ({type(e).__name__}).")

    with st.expander(f"🎯 Parlay de ESTE partido — {home} vs {away}"):
        c1, c2 = st.columns(2)
        with c1:
            n_sel = st.slider("Número de apuestas", 2, 8, 6, key=f"mp_n_{key}",
                              help="Cuántas selecciones del MISMO partido combinar "
                                   "(2 = doble sencilla, 8 = combinada larga).")
        with c2:
            perfil_sel = st.radio(
                "Perfil de riesgo",
                ['🔒 Super Seguro', '🛡️ Conservador', '⚖️ Medio', '🚀 Agresivo'],
                index=0, key=f"mp_perfil_{key}", horizontal=True,
                help="🔒 Súper Seguro: prioriza mercados de ALTA "
                     "probabilidad (doble oportunidad, hándicap +0.5, BTTS) para "
                     "maximizar el PFP — la probabilidad real de acertar TODO el "
                     "parlay. 🛡️ Conservador: mínimo 60 % conjunto. ⚖️ Medio: "
                     "balance prob/cuota (15-60 %). 🚀 Agresivo: cuota más alta "
                     "sin bajar del 5 % conjunto. Los parlays con PFP < 45 % solo "
                     "salen en Medio/Agresivo (riesgo asumido).")
        excluir = st.checkbox("Excluir si el partido tiene riesgo de mercado 🔴",
                              value=True, key=f"mp_riesgo_{key}")
        # v25 (§2.1): lista blanca dinámica + control de categorías
        c3, c4 = st.columns(2)
        with c3:
            solo_reales = st.checkbox(
                "Solo mercados con cuota REAL vigente", value=False,
                key=f"mp_reales_{key}",
                help="Lista blanca dinámica: limita el parlay a los mercados "
                     "presentes en odds_actuales.json (1X2, O/U 2.5, BTTS, "
                     "AH ±0.5). EV 100 % accionable, menos mercados.")
        with c4:
            # v57: las categorías salen de la plantilla REAL de este partido, así
            # que en MLB se ven las de béisbol (run line, innings, carreras...) y
            # en fútbol las de fútbol. Antes era una lista fija de fútbol.
            from match_parlay import categorias_disponibles
            try:
                _pl_cats = _pl()
                _cats_disp = categorias_disponibles(_pl_cats)
            except Exception:
                _cats_disp = []
            cats_sel = st.multiselect(
                "Categorías permitidas", _cats_disp, default=_cats_disp,
                key=f"mp_cats_{key}",
                help="Tipos de mercado disponibles en ESTE partido "
                     "(cambian según el deporte).")
        categorias = set(cats_sel) if cats_sel else None
        if st.button("🎯 Proponer parlay para este partido", key=f"mp_btn_{key}",
                     type="primary"):
            from match_parlay import construir_parlay_partido
            perfil = ('super_seguro' if 'Super Seguro' in perfil_sel else
                      'conservador' if 'Conservador' in perfil_sel else
                      'agresivo' if 'Agresivo' in perfil_sel else 'medio')
            with st.spinner("🧮 Combinando los mercados del partido..."):
                # v114 — ESTA SECCIÓN TAMBIÉN NECESITA EL TABLÓN.
                #
                # Marcar «Solo mercados con cuota REAL vigente» respondía «no
                # hay suficientes mercados vigentes para este partido» aunque
                # la combinada por EV real de más arriba SÍ los encontraba: el
                # motor que se le pasaba aquí era el pelado, así que las únicas
                # cuotas reales que veía eran las cuatro de
                # `odds_actuales.json`. Con el tablón enganchado ve las mismas
                # que la otra sección.
                _m_cfg = motor
                try:
                    import cuotas_tablon as _ct
                    _dep_cfg = ('tenis' if str(key).startswith('tenis')
                                else 'mlb' if key in ('mlb', 'kbo')
                                else 'nba' if key == 'nba' else 'futbol')
                    _m_cfg, _ = _ct.motor_con_tablon(motor, home, away,
                                                     deporte=_dep_cfg)
                except Exception:
                    pass
                r = construir_parlay_partido(_m_cfg, home, away,
                                             num_selecciones=n_sel, perfil=perfil,
                                             excluir_alto_riesgo=excluir,
                                             solo_cuotas_reales=solo_reales,
                                             categorias=categorias,
                                             bankroll=float(st.session_state.get(
                                                 'bankroll', 0) or 0))
            if 'error' in r:
                st.warning(r['error'])
                return
            for aviso in r['avisos']:
                st.warning(aviso)
            st.success(
                f"**Este parlay tiene un {r['prob_conjunta']*100:.0f} % de probabilidad "
                f"de ganar**, cuota combinada {r['cuota_combinada']:.2f}"
                + (f", EV {r['ev_parlay']:+.2f} unidades." if r['cuotas_reales']
                   else " (cuotas justas del modelo).")
            )
            st.dataframe(pd.DataFrame([{
                'Categoría': s.get('categoria', ''),
                'Mercado': s['mercado'], 'Apuesta': s['apuesta'],
                'Prob.': f"{s['prob']*100:.1f} %", 'Cuota': s['cuota'],
                'Fuente': s['cuota_fuente'], 'EV': s['ev'],
            } for s in r['selecciones']]), width='stretch', hide_index=True)
            # v20: por qué estas categorías encajan con ESTE partido
            if r.get('explicacion'):
                st.markdown("**🧭 Composición del parlay** — " +
                            ", ".join(r.get('categorias', [])))
                for linea in r['explicacion']:
                    st.caption(f"• {linea}")
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Cuota combinada", f"{r['cuota_combinada']:.2f}",
                      help="Producto de las cuotas: lo que pagaría 1 unidad si aciertas todo.")
            pfp = r.get('pfp', r['prob_conjunta'])
            m2.metric("🎯 PFP (fuerza real)", f"{pfp*100:.1f} %",
                      delta=("✅ ≥45 %" if r.get('cumple_pfp') else "⚠️ <45 %"),
                      delta_color=("normal" if r.get('cumple_pfp') else "inverse"),
                      help="Parlay Force Point: probabilidad REAL de acertar TODAS "
                           "las patas, ajustada por correlación empírica. Es el "
                           "criterio rey: por debajo del 45 % el parlay es arriesgado.")
            m3.metric("EV del parlay", f"{r['ev_parlay']:+.3f}",
                      help="Solo accionable con cuotas reales de mercado.")
            m4.metric("Riesgo del partido",
                      {'bajo': '🟢 Bajo', 'medio': '🟡 Medio', 'alto': '🔴 Alto'}[r['riesgo_partido']])
            # v19: stake por ¼ Kelly cuando el parlay tiene EV real positivo
            if r['cuotas_reales'] and r['ev_parlay'] > 0:
                from bankroll_manager import calcular_stake, AVISO_JUEGO_RESPONSABLE
                k = calcular_stake(r['prob_conjunta'], r['cuota_combinada'],
                                   float(st.session_state.get('bankroll', 0) or 0))
                if k['stake'] > 0:
                    st.info(f"💵 Stake recomendado (¼ Kelly): **{k['stake']:.2f} "
                            f"unidades** ({k['pct']*100:.1f} % del bankroll). "
                            + AVISO_JUEGO_RESPONSABLE)
            st.caption(r['nota'])
            texto = "\n".join(
                f"{i}. [{s['mercado']}] {s['apuesta']} @ {s['cuota']} (p={s['prob']*100:.0f}%)"
                for i, s in enumerate(r['selecciones'], 1)
            ) + (f"\nCuota combinada: {r['cuota_combinada']} · "
                 f"Prob: {r['prob_conjunta']*100:.1f}% · EV: {r['ev_parlay']:+.3f}")
            st.code(texto, language=None)
            st.download_button("📥 Descargar parlay (.txt)", data=texto.encode('utf-8'),
                               file_name=f"parlay_{home}_vs_{away}.txt".replace(' ', '_'),
                               mime="text/plain", key=f"mp_dl_{key}")

        # v53: COMBINADOR MANUAL — el usuario elige los mercados y la app calcula
        # la probabilidad conjunta REAL (ajustada por correlación) y la cuota.
        st.divider()
        st.markdown("**🎰 Arma TU combinada de este partido**")
        st.caption("Elige 2 o más mercados y te calculo la probabilidad REAL de "
                   "que acierten TODOS a la vez (ajustada por la correlación "
                   "entre mercados del mismo partido) y la cuota combinada. Ideal "
                   "para juntar mercados seguros y subir la ganancia en un solo "
                   "partido.")
        pl_manual = _pl()
        if isinstance(pl_manual, dict) and 'error' not in pl_manual:
            from match_parlay import obtener_selecciones, combinar_manual
            sels_manual = obtener_selecciones(pl_manual)
            opciones = {}
            for s in sorted(sels_manual, key=lambda x: -x.prob):
                etq = f"{s.apuesta} — {s.prob*100:.0f}% (cuota {s.cuota})"
                opciones[etq] = s.id
            if opciones:
                elegidas = st.multiselect(
                    "Mercados a combinar (ordenados por probabilidad)",
                    list(opciones.keys()), key=f"manual_ms_{key}",
                    help="Combina mercados de alta probabilidad para una cuota "
                         "mayor con un solo partido.")
                if len(elegidas) >= 2:
                    rm = combinar_manual(pl_manual, [opciones[e] for e in elegidas])
                    if 'error' in rm:
                        st.warning(rm['error'])
                    else:
                        for a, b in rm['incompatibles']:
                            st.error(f"⚠️ «{a}» y «{b}» no pueden ocurrir a la vez "
                                     "— quita una para que la combinada sea válida.")
                        cc1, cc2, cc3 = st.columns(3)
                        cc1.metric("Prob. de acertar TODO",
                                   f"{rm['prob_conjunta']*100:.0f}%")
                        cc2.metric("Cuota combinada",
                                   rm['cuota_real_combinada'] or rm['cuota_justa_combinada'],
                                   help="Real si hay cuotas vigentes; si no, justa "
                                        "(1/probabilidad, sin margen de casa).")
                        if rm['ev'] is not None:
                            cc3.metric("EV (cuotas reales)", f"{rm['ev']*100:+.1f}%")
                        else:
                            cc3.metric("Cuota justa", rm['cuota_justa_combinada'])
                        if not rm['incompatibles']:
                            ganancia = (rm['cuota_real_combinada']
                                        or rm['cuota_justa_combinada'])
                            st.success(f"Combinada de {rm['n']} mercados · "
                                       f"**{rm['prob_conjunta']*100:.0f}%** de acertar "
                                       f"todo · cuota **{ganancia}** "
                                       f"(100 u → {ganancia*100:.0f} u si entra).")
                        if rm['correlacion_aplicada']:
                            st.caption("✔️ Ajustado por correlación entre mercados "
                                       "del mismo partido (no es el simple producto "
                                       "de probabilidades).")
                        st.caption(rm['nota'])
                else:
                    st.caption("Selecciona al menos 2 mercados arriba.")

        # v37 (§1): SGP+ — pareja correlacionada del MISMO partido que la casa
        # tiende a infrapreciar (requiere cuotas reales vigentes).
        st.divider()
        st.caption("**🔗 SGP+** — busca DOS mercados de este partido "
                   "positivamente correlacionados que las casas suelen "
                   "infrapreciar (necesita cuotas reales vigentes).")
        if st.button("🔗 Buscar SGP+ en este partido", key=f"sgp_btn_{key}"):
            from match_parlay import construir_sgp_plus
            s = construir_sgp_plus(motor, home, away)
            if 'error' in s:
                st.info(s['error'])
            else:
                st.success(f"**SGP+ detectado** · EV estimado "
                           f"**{s['ev_estimado']*100:+.0f} %** · φ={s['phi']}")
                st.dataframe(pd.DataFrame([
                    {'Mercado': x['mercado'], 'Apuesta': x['apuesta'],
                     'Prob.': f"{x['prob']*100:.0f} %", 'Cuota': x['cuota']}
                    for x in s['selecciones']], ), hide_index=True, width='stretch')
                cs1, cs2, cs3 = st.columns(3)
                cs1.metric("Prob. conjunta REAL", f"{s['prob_conjunta_real']*100:.1f} %",
                           help="Ajustada por la correlación empírica φ.")
                cs2.metric("Si fueran independientes",
                           f"{s['prob_si_independientes']*100:.1f} %",
                           help=f"Boost por correlación: ×{s['boost_correlacion']}")
                cs3.metric("Cuota SGP estimada", f"{s['cuota_sgp_estimada']:.2f}")
                st.caption(s['nota'])


def render_liga_club(clave: str, nombre_liga: str):
    from config import LEAGUES
    # v98 — UNA LIGA QUE FALTA NO PUEDE TUMBAR LA APP ENTERA.
    #
    # Esto era `LEAGUES[clave]`, y en producción tiró un `KeyError:
    # 'leagues_cup'` que dejó la aplicación en blanco justo después de
    # desplegar la v97 — con la competición SÍ presente en el `config.py`
    # publicado (comprobado en los dos remotos). Es el patrón que la v79 ya
    # documentó en `calibracion_segura`: Streamlit Cloud conserva módulos
    # viejos en `sys.modules` entre despliegues, así que durante la ventana de
    # recarga convive un `dashboard_ui` NUEVO —que ya ofrece la liga en el
    # selector— con un `config` VIEJO que todavía no la tiene.
    #
    # El selector y el catálogo pueden desincronizarse por un momento; lo que
    # no puede es costar la app. Se degrada a un aviso.
    cfg = LEAGUES.get(clave)
    if cfg is None:
        st.warning(
            f"🔄 **{nombre_liga}** todavía no está en el catálogo de esta "
            f"sesión. Suele pasar durante unos segundos justo después de una "
            f"actualización: recarga la página y aparecerá.")
        st.stop()
    if not cfg.get('disponible'):
        st.info(f"🔧 **{nombre_liga} (beta):** {cfg.get('nota', 'no disponible')}")
        st.stop()
    motor = cargar_motor_liga(clave)
    if not motor.listo:
        st.error(f"❌ Motor de {nombre_liga} no inicializado: `{motor.error}`\n\n"
                 f"Ejecuta `python league_engine.py --build {clave}`.")
        st.stop()

    fuente_liga = ('API-Football' if LEAGUES[clave].get('formato') == 'api_football'
                   else 'football-data.co.uk')
    _cabecera(
        nombre_liga, 'Predicción, cuotas de seis casas y constructor de '
        'combinadas para cualquier partido de la competición.',
        chips=[(f"{len(motor.equipos)} equipos", 'info'),
               (f"acierta {motor.metadata['precision_validacion']*100:.0f} % en 1X2",
                'ok'),
               (f"datos al {motor.fecha_estado}", 'azul')],
        icono='⚽')
    if _ayuda is not None:
        _ayuda.render(st, 'liga')
    st.caption(
        f"Datos reales ({fuente_liga}) al **{motor.fecha_estado}** · "
        f"Precisión backtesting 1X2: **{motor.metadata['precision_validacion']*100:.1f} %** "
        f"(línea base ELO {motor.metadata['precision_linea_base_elo']*100:.1f} %"
        + (f", favorito del mercado {motor.metadata['precision_mercado_cuotas']*100:.1f} %"
           if motor.metadata.get('precision_mercado_cuotas') else '') + ")"
    )
    # v70 (Mejora D): la familia de clasificador se elige por liga. Se muestra
    # cuando NO es el ensemble por defecto, que es cuando aporta información.
    _FAMILIAS_UI = {
        'logistica': 'regresión logística regularizada',
        'logistica_base': 'regresión logística sobre el vector base',
        'elo_logit': 'logística calibrada sobre el ELO',
        'gbm_regular': 'GBM regularizado',
        'blend_elo': 'mezcla ensemble + ELO calibrado',
        'beta': 'ensemble con beta calibration',
    }
    _fam = motor.metadata.get('familia_modelo')
    if _fam and _fam not in ('ensemble', None):
        st.caption(
            f"🧩 Modelo de esta competición: **{_FAMILIAS_UI.get(_fam, _fam)}**. "
            f"En ligas con pocos datos, un modelo grande aprende ruido en vez "
            f"de señal; aquí se eligió el que mejor acertó en las pruebas.")
    try:
        import distributions as _d
        _s = _d.factor_shrink(clave)
        if _s < 1.0:
            st.caption(
                f"📉 Goles esperados con encogimiento **s={_s:.2f}**: los "
                f"regresores separaban demasiado las dos λ. Afecta al marcador "
                f"exacto y a los mercados de goles, no al 1X2.")
    except Exception:
        pass
    if LEAGUES[clave].get('formato') == 'api_football':
        st.info("ℹ️ Fuentes: API-Football (2022-24, marcadores de 90') + FBref "
                "(resto e incluida la temporada en curso). La forma se actualiza "
                "con cada corrida del pipeline.")
    # v58: PRÓXIMOS PARTIDOS de la liga (fixtures ESPN) — el usuario elige el
    # partido real y se autorrellenan los selectores de local/visitante.
    try:
        import fixtures_espn
        import name_mapper as _nm
        _fx = fixtures_espn.fixtures_liga(clave)
    except Exception:
        _fx = []
    if _fx:
        # v91 — LA SEMANA COMPLETA, ORDENADA POR FECHA (el más próximo
        # primero). La v72 escondía los partidos sin cuota; el usuario pidió
        # ver la jornada entera en la vista de la liga, así que ahora entran
        # todos y los que aún no cotizan se marcan «· sin cuota aún» en vez de
        # desaparecer — visibilidad sin invitar a apostar a ciegas.
        _sel = fixtures_espn.con_cuota(_fx)
        _con = {id(f) for f in (_sel['apostables'] or [])}
        _fx_mostrar = sorted(_fx, key=lambda f: (str(f.get('fecha', '')),
                                                 str(f.get('inicio', ''))))
        # v102 — el texto dice el horizonte REAL, no «la semana».
        #
        # `fixtures_liga` ya no se limita a 7 días: si la competición no juega
        # esta semana amplía hasta encontrar sus próximos partidos (Champions en
        # fase previa, ligas europeas entre temporadas…). Seguir diciendo «de la
        # semana» sobre una lista que empieza dentro de tres semanas sería
        # mentir en la etiqueta.
        _f0 = str(_fx_mostrar[0].get('fecha', '')) if _fx_mostrar else ''
        _dias_al_primero = None
        try:
            import pandas as _pd
            _dias_al_primero = (_pd.Timestamp(_f0)
                                - _pd.Timestamp.now('UTC').tz_localize(None)
                                .normalize()).days
        except Exception:
            pass
        if _dias_al_primero is not None and _dias_al_primero > 7:
            st.caption(f"ℹ️ Esta competición no juega esta semana. Se muestran "
                       f"sus próximos {len(_fx_mostrar)} partidos, a partir del "
                       f"{_f0} (dentro de {_dias_al_primero} días).")
        if _sel['sin_cuota']:
            st.caption(f"ℹ️ {len(_sel['apostables'])} partidos con cuota "
                       f"abierta · {len(_sel['sin_cuota'])} aún sin precio "
                       f"(las casas publican 2-4 días antes).")
        _cat = list(motor.equipos)
        _ops = {}
        _etqs = {}          # v123: clave estable → texto que se pinta
        for f in _fx_mostrar:
            h = _nm.mapear(f['home'], _cat, contexto=f'ui→{clave}')
            a = _nm.mapear(f['away'], _cat, contexto=f'ui→{clave}')
            if h and a and h != a:
                # v106: día y HORA de CDMX (ver `selector_proximos`)
                _pf = _horario.partes(f.get('inicio'))
                _cuando = f"{_pf[0]} {_pf[1]}" if _pf else str(f.get('fecha', ''))
                # v123 — misma corrección que en `selector_proximos`: «· sin
                # cuota aún» cambia entre recargas y no puede formar parte de
                # la CLAVE de la opción, o la selección guardada deja de
                # existir y Streamlit tumba la vista.
                _clv = f"{_cuando}|{h}|{a}"
                _etq = f"{_cuando} · {h} vs {a}"
                if id(f) not in _con:
                    _etq += "  · sin cuota aún"
                _ops[_clv] = (h, a)
                _etqs[_clv] = _etq
        if _ops:
            # v71: sin botón. Elegir el partido rellena los equipos y dispara
            # el análisis; el paso manual sobraba.
            def _cargar_fx():
                par = _ops.get(st.session_state.get(f"fx_sel_{clave}"))
                if par:
                    (st.session_state[f"club_home_{clave}"],
                     st.session_state[f"club_away_{clave}"]) = par

            _olvidar_seleccion_muerta(f"fx_sel_{clave}", _ops)
            st.selectbox(
                f"📅 Próximos partidos de {nombre_liga} ({len(_ops)})",
                list(_ops.keys()), key=f"fx_sel_{clave}",
                format_func=lambda k: _etqs.get(k, k), on_change=_cargar_fx,
                help="Al elegir un partido se cargan sus equipos y sus datos.")

    c1, c2 = st.columns(2)
    with c1:
        home = st.selectbox("🏠 Local", motor.equipos, key=f"club_home_{clave}")
    with c2:
        visitantes = [e for e in motor.equipos if e != home]
        away = st.selectbox("✈️ Visitante", visitantes, key=f"club_away_{clave}")

    pl = plantilla_club_cacheada(clave, home, away)
    if 'error' in pl:
        st.error(f"❌ {pl['error']}")
        st.stop()
    pred = pl['prediccion_base']
    p = pred['prediction']

    # v147 — LA FICHA SE PARTE EN SECCIONES, Y SÓLO SE EJECUTA LA ABIERTA.
    #
    # Medido el 2026-08-17 abriendo una ficha con el motor frío: 15,9 s, de los
    # cuales **41 peticiones a ESPN**. Con las cachés de disco calientes seguían
    # siendo 7 peticiones y 7,2 s. El coste es de RED, no de cálculo: la
    # predicción y el H2H salen del CSV local en centésimas.
    #
    # Por eso NO se usa `st.tabs`: Streamlit renderiza el contenido de todas
    # las pestañas se mire la que se mire, así que habría reorganizado el
    # scroll sin ahorrar una sola petición. `partido_ui` usa
    # `st.segmented_control`, que dice CUÁL está abierta, y sólo se llama a esa.
    #
    # El «Resumen» —que es el que se abre por defecto— no toca la red.
    import partido_ui as _pui


    def _sec_resumen():
        st.markdown(f"### 🏆 Ganador más probable: **{p['winner']}** "
                    f"({p['confidence']*100:.0f} % de confianza)")
        st.markdown(f"### ⚽ Marcador más probable: **{p['most_likely_score']}** "
                    f"({p['score_probability']*100:.0f} %) · "
                    f"{p['total_goals_expected']:.1f} goles esperados")
        st.markdown(f"### 📊 {home} **{p['probabilities']['home']*100:.0f} %** · "
                    f"Empate **{p['probabilities']['draw']*100:.0f} %** · "
                    f"{away} **{p['probabilities']['away']*100:.0f} %**")
        render_comentario(pred, home, away)

        col_g1, col_g2 = st.columns(2)
        with col_g1:
            fig_b = go.Figure(go.Bar(
                x=[f"Gana {home}", "Empate", f"Gana {away}"],
                y=[p['probabilities']['home'] * 100, p['probabilities']['draw'] * 100,
                   p['probabilities']['away'] * 100],
                marker_color=['#2ecc71', '#95a5a6', '#3498db'],
                text=[f"{p['probabilities'][k]*100:.0f} %" for k in ('home', 'draw', 'away')],
                textposition='outside'))
            fig_b.update_layout(yaxis_range=[0, 100], height=320, margin=dict(l=0, r=0, t=10, b=0))
            st.plotly_chart(fig_b, width='stretch')
        with col_g2:
            matriz = np.array(pred['score_matrix'])
            fig_h = go.Figure(go.Heatmap(
                z=matriz * 100, x=[str(i) for i in range(matriz.shape[1])],
                y=[str(i) for i in range(matriz.shape[0])], colorscale='YlOrRd',
                colorbar=dict(title='%')))
            fig_h.update_layout(xaxis_title=f"Goles {away}", yaxis_title=f"Goles {home}",
                                height=320, margin=dict(l=0, r=0, t=10, b=0))
            st.plotly_chart(fig_h, width='stretch')

        # ---- Plantilla extendida de clubes (editable, mismo formato) ----------

    def _sec_mercados():
        st.markdown(f"## 📋 Plantilla de análisis — {pl['partido']}")
        st.caption("Todos los mercados con probabilidades del modelo; las cuotas entre "
                   "paréntesis son cuotas JUSTAS en formato americano (sin margen).")
        prefijo = f"club_{clave}_{home}_{away}_".replace(' ', '-')
        with st.form(key=f"form_{prefijo}"):
            for seccion in pl['secciones']:
                st.markdown(f"#### {seccion['titulo']}")
                editables = [c for c in seccion['campos'] if c['tipo'] != 'texto']
                columnas = st.columns(3)
                for i, c in enumerate(editables):
                    with columnas[i % 3]:
                        if c['tipo'] == 'pct':
                            st.number_input(f"{c['etiqueta']} (%)", 0.0, 100.0,
                                            float(c['valor']), 0.5, key=prefijo + c['id'])
                        else:
                            st.number_input(c['etiqueta'], 0.0, 60.0,
                                            float(c['valor']), 0.1, key=prefijo + c['id'])
            validar = st.form_submit_button("✅ Validar mis estimaciones", type="primary")
        if validar:
            hallazgos = []
            for s in pl['secciones']:
                for c in s['campos']:
                    if c['tipo'] == 'texto':
                        continue
                    vu = float(st.session_state.get(prefijo + c['id'], c['valor']))
                    if abs(vu - float(c['valor'])) >= 0.05:
                        hallazgos.append({'Campo': c['etiqueta'], 'Tu valor': round(vu, 1),
                                          'Modelo': round(float(c['valor']), 1),
                                          'Diferencia': round(vu - float(c['valor']), 1)})
            if hallazgos:
                st.dataframe(pd.DataFrame(hallazgos), width='stretch', hide_index=True)
            else:
                st.success("Tus valores coinciden con el modelo.")

        for obs in pl['observaciones']:
            st.markdown(f"- {obs}")

        # v18/M3: cuotas reales vigentes + EV por mercado
        render_cuotas_reales(pl)

        # v25: ajuste por alineación VORP — EXPERIMENTAL con fallback estricto
        with st.expander("🧪 Ajuste por alineación (VORP) — experimental"):
            st.caption("Compara el once CONFIRMADO (ESPN, ~1 h antes) contra el "
                       "once esperado del equipo y ajusta las tasas de goles (λ) "
                       "— el 1X2 calibrado no se toca. Si la alineación no está "
                       "publicada o no se parsea con confianza, NO se aplica nada.")
            if st.checkbox("Consultar alineaciones de hoy", key=f'vorp_{clave}'):
                import alineacion_vorp
                with st.spinner("Consultando alineaciones en ESPN…"):
                    aj = alineacion_vorp.ajuste_partido(clave, home, away)
                if not aj.get('aplicado'):
                    st.info(f"⚠️ Ajuste por alineación no disponible — {aj.get('motivo')}")
                else:
                    lam_h0 = pl['prediccion_base']['prediction']['expected_goals']['home']
                    lam_a0 = pl['prediccion_base']['prediction']['expected_goals']['away']
                    lam_h = lam_h0 * aj['factor_home']
                    lam_a = lam_a0 * aj['factor_away']
                    c1, c2 = st.columns(2)
                    c1.metric(f"λ {home}", f"{lam_h:.2f}",
                              f"{(aj['factor_home']-1)*100:+.1f} % por alineación")
                    c2.metric(f"λ {away}", f"{lam_a:.2f}",
                              f"{(aj['factor_away']-1)*100:+.1f} % por alineación")
                    for lado, aus in (('local', aj['ausentes_home']),
                                      ('visitante', aj['ausentes_away'])):
                        if aus:
                            st.caption(f"Titulares habituales ausentes ({lado}): "
                                       + ", ".join(aus))
                    st.caption("🧪 Experimental: cada aplicación se registra en "
                               "vorp_log.json; la adopción permanente se decidirá "
                               "con la evaluación de la temporada 2026-27 "
                               "(mejora ≥1 pp en los partidos ajustados).")

        # v67: remates REALES por jugador (antes solo existía en la vista
        # internacional, y ahí eran estimados a partir de los goles)
        @st.cache_data(ttl=6 * 3600, show_spinner="Buscando remates por jugador…")
        def _remates_club(liga_clave: str, equipo: str):
            import remates_jugadores as _rj
            import fixtures_espn as _fx
            code = _fx.ESPN_CODIGOS.get(liga_clave)
            if not code:
                return None
            nombre_espn = _rj.resolver_equipo(code, equipo)
            if not nombre_espn:
                return None
            return _rj.remates_equipo(code, nombre_espn)

        # v163 - los remates del partido: por equipo con su linea y su
        # probabilidad, y por jugador con el once probable de FotMob. Va antes
        # de la tabla cruda de la v67, que sigue debajo con los totales
        # observados sin modelo encima.
        render_remates_partido(clave, home, away, key=clave)

        render_remates_reales(
            [(f"🏠 {home}", lambda: _remates_club(clave, home)),
             (f"✈️ {away}", lambda: _remates_club(clave, away))],
            key=clave)

    def _sec_h2h():
        # v107 — EL PANEL DE EQUIPOS, ANTES DEL PARLAY.
        #
        # Va aquí y no al final a propósito: el usuario lo pidió para DECIDIR la
        # apuesta («si los equipos en todos los partidos los ha ganado el equipo A
        # pues obvio hay más probabilidad, pero si en el torneo actual el equipo B
        # tiene mejor rendimiento baja su probabilidad»), así que tiene que estar
        # antes del combinador, no después.
        st.divider()
        try:
            render_panel_equipos(clave, home, away, key=clave,
                                 prob_modelo=(p.get('probabilities')
                                              if isinstance(p, dict) else None))
        except Exception as e:
            st.caption(f"Panel de equipos no disponible ahora ({type(e).__name__}).")
        # el H2H de API-Football se conserva como extra opcional: aporta cruces en
        # OTRAS competiciones (copas, europeas) que el histórico de esta liga no
        # tiene. Ya no es la única vía, así que no pasa nada si falta la clave.
        render_h2h_club(clave, home, away, key=clave)
        render_comparador(motor, motor.equipos, key=clave)      # v25 (§2.4)
        render_rendimiento(key=clave)

    def _sec_especificos():
        # v146 — CÓRNERS. Va aquí, en la ficha del partido, que es donde el
        # usuario los pidió: «eso deberá estar cuando analizas el partido
        # individualmente». El tablero de Playdoit se reutiliza si ya está en
        # caché; si no está, la sección sigue enseñando el pronóstico y el H2H.
        st.divider()
        try:
            import corners_ui as _cku
            _det_ck = None
            try:
                import cuotas_multi as _cm_ck
                _det_ck = _cm_ck.mercados_playdoit('futbol', home, away)
            except Exception as _e_ck:
                logger.debug(f'[corners] tablero no disponible: {_e_ck}')
            _cku.render(st, pl, clave, home, away, _det_ck)
        except Exception as _e_cku:
            st.caption(f'Sección de córners no disponible ({type(_e_cku).__name__}).')

    def _sec_combinadas():
        # v15: parlay del partido en pantalla
        st.divider()
        render_parlay_partido(motor, home, away, key=clave)

    _pui.render(st, f'{clave}_{home}_{away}', {
        _pui.RESUMEN: _sec_resumen,
        _pui.MERCADOS: _sec_mercados,
        _pui.H2H: _sec_h2h,
        _pui.ESPECIFICOS: _sec_especificos,
        _pui.COMBINADAS: _sec_combinadas,
    })

    from prediction_api import plantilla_a_markdown
    st.download_button("⬇️ Descargar plantilla (Markdown)",
                       data=plantilla_a_markdown(pl).encode('utf-8'),
                       file_name=f"plantilla_{clave}_{home}_vs_{away}.md".replace(' ', '_'),
                       mime="text/markdown")


COMPETENCIAS = {'🌍 Partidos Internacionales': 'mundial',
                '💎 Apuestas del Día': 'alpha',
                '⚾ MLB (béisbol)': 'mlb_deporte',
                '⚾ KBO (béisbol coreano)': 'kbo_deporte',       # v97
                '🏀 NBA (baloncesto)': 'nba_deporte',
                '🎾 Tenis (ATP/WTA)': 'tennis_deporte',
                '🏈 NFL (fútbol americano)': 'nfl_deporte',   # v131
                '🏆 Leagues Cup': 'leagues_cup',                 # v97
                '🇲🇽 Liga MX': 'liga_mx',
                '🇧🇷 Brasileirão': 'brasil',
                '🇦🇷 Primera (ARG)': 'argentina',
                '🇺🇸 MLS': 'mls',
                '🇹🇷 Süper Lig': 'turquia',
                '🇩🇰 Superliga': 'dinamarca',
                '🏴 Premier League': 'premier', '🇪🇸 LaLiga': 'laliga',
                '🇮🇹 Serie A': 'serie_a', '🇩🇪 Bundesliga': 'bundesliga',
                '🇫🇷 Ligue 1': 'ligue_1', '🇳🇱 Eredivisie': 'eredivisie',
                '🇵🇹 Primeira Liga': 'primeira',
                '🇪🇺 Champions League': 'champions',
                '🇪🇺 Europa League': 'europa_league',
                '🇪🇺 Conference League': 'conference_league'}
NOMBRES_LIGAS = {'liga_mx': 'Liga MX', 'mls': 'MLS',
                 'brasil': 'Brasileirão Serie A',
                 'argentina': 'Primera División (ARG)',
                 'premier': 'Premier League',
                 'laliga': 'LaLiga', 'serie_a': 'Serie A',
                 'bundesliga': 'Bundesliga', 'ligue_1': 'Ligue 1',
                 'eredivisie': 'Eredivisie', 'primeira': 'Primeira Liga',
                 'champions': 'UEFA Champions League',
                 'turquia': 'Süper Lig', 'dinamarca': 'Superliga',
                 'europa_league': 'UEFA Europa League',
                 'conference_league': 'UEFA Conference League',
                 'leagues_cup': 'Leagues Cup'}                   # v97

# v68 — Las competiciones nuevas se añaden solas al selector, agrupadas por
# país, y SOLO las que el entrenamiento marcó `disponible` (es decir, las que
# baten a la línea base ELO). Así el menú crece con el catálogo sin tener que
# mantener dos listas a mano.
_BANDERAS = {
    'Inglaterra': '🏴', 'Escocia': '🏴', 'España': '🇪🇸', 'Italia': '🇮🇹',
    'Francia': '🇫🇷', 'Alemania': '🇩🇪', 'Bélgica': '🇧🇪', 'Japón': '🇯🇵',
    'México': '🇲🇽', 'Argentina': '🇦🇷', 'Brasil': '🇧🇷', 'Chile': '🇨🇱',
    'Colombia': '🇨🇴', 'Perú': '🇵🇪', 'Uruguay': '🇺🇾', 'Bolivia': '🇧🇴',
    'Ecuador': '🇪🇨', 'Paraguay': '🇵🇾', 'Venezuela': '🇻🇪',
    'Costa Rica': '🇨🇷', 'El Salvador': '🇸🇻', 'Estados Unidos': '🇺🇸',
    'Australia': '🇦🇺', 'Austria': '🇦🇹', 'Grecia': '🇬🇷', 'Rusia': '🇷🇺',
    'Sudáfrica': '🇿🇦', 'India': '🇮🇳', 'Países Bajos': '🇳🇱',
    'Américas': '🏆', 'Asia': '🏆', 'África': '🏆', 'Europa': '🇪🇺', 'Mundo': '🌍',
    # v144 — los que faltaban y salían con el balón genérico. No es cosmético:
    # con 37 países en el selector, la bandera es lo que se busca antes de
    # leer el nombre.
    'Portugal': '🇵🇹', 'Dinamarca': '🇩🇰', 'Turquía': '🇹🇷', 'Suecia': '🇸🇪',
    'Noruega': '🇳🇴', 'Finlandia': '🇫🇮', 'Polonia': '🇵🇱', 'Rumanía': '🇷🇴',
    'Irlanda': '🇮🇪', 'China': '🇨🇳', 'Croacia': '🇭🇷', 'Suiza': '🇨🇭',
    'Corea del Sur': '🇰🇷', 'Arabia Saudita': '🇸🇦',
    'Estados Unidos/Canadá': '🇺🇸', 'Norteamérica': '🏆',
}
# v144 — EL MENÚ SE CONSTRUYE DESDE EL CATÁLOGO ENTERO, NO DESDE UNA SUBLISTA.
#
# El bucle de la v68 recorría sólo `LIGAS_V68_ANADIDAS`, que son las ligas que
# entraron por `config_ligas_espn`. Las del catálogo base nunca pasaban por
# aquí, así que el menú se quedaba con las 17 escritas a mano de arriba.
#
# Medido el 2026-08-16: **50 ligas disponibles, las 50 con modelo entrenado, y
# sólo 17 en el selector.** O sea 33 competiciones que el sistema predice cada
# día, cuyos picks entran en el barrido y salen en «Apuestas del Día»… y a las
# que no se podía llegar desde el menú para ver su ficha. Entre ellas:
#
#     Rusia (Premier), Escocia (Premiership y Championship), Inglaterra
#     (League One, League Two, National), España (Hypermotion), Italia
#     (Serie B), Alemania (2. Bundesliga), Francia (Ligue 2), Japón (J1),
#     Grecia, Polonia, Rumanía, Noruega, Suecia, Finlandia, Irlanda…
#
# Por eso «añadir la liga de Rusia» no era dar de alta nada: era enseñarla.
# El catálogo la tenía desde hacía versiones, con histórico y con modelo.
#
# Se recorre `LEAGUES` entero y se respeta el mismo filtro de siempre: sólo
# `disponible`, que es la marca que pone el entrenamiento cuando la liga bate a
# la línea base ELO. Una liga que no supera esa prueba sigue sin aparecer.
# LA DEDUPLICACIÓN ES POR CLAVE, NO POR ETIQUETA — y esto se midió.
#
# Las 17 entradas escritas a mano usan nombres cortos («🇧🇷 Brasileirão»,
# «🇦🇷 Primera (ARG)») y el catálogo usa el largo («Brasileirão Serie A»,
# «Primera División»). Comparando etiquetas, las dos versiones de la MISMA liga
# entraban al menú: la primera pasada dejó **10 competiciones duplicadas**
# —Brasil, Argentina, MLS, Turquía, Dinamarca, Portugal, las tres de UEFA y la
# Leagues Cup— cada una con dos entradas que abren exactamente la misma vista.
#
# Peor que feo: partía países. `mls` tiene `pais = 'Estados Unidos/Canadá'` y la
# entrada a mano decía «Estados Unidos», así que el selector ofrecía los dos
# países con una MLS en cada uno.
try:
    import config as _cfg68
    _ya_en_menu = set(COMPETENCIAS.values())
    for _k, _c in _cfg68.LEAGUES.items():
        if not _c.get('disponible'):
            continue                    # entrenada pero no supera al ELO
        if _k in _ya_en_menu:
            continue                    # ya está, con su etiqueta de siempre
        _pais = _c.get('pais', '')
        _et = f"{_BANDERAS.get(_pais, '⚽')} {_c.get('nombre', _k)}"
        # dos ligas DISTINTAS pueden llamarse igual en países distintos
        # («Primera División» es Argentina y Uruguay); se desambigua con el
        # país detrás, que es lo que las separa de verdad.
        if _et in COMPETENCIAS:
            _et = f"{_et} ({_pais})"
        COMPETENCIAS[_et] = _k
        _ya_en_menu.add(_k)
        NOMBRES_LIGAS.setdefault(_k, _c.get('nombre', _k))
except Exception as _e_menu:
    import logging as _lg_menu
    _lg_menu.getLogger(__name__).warning(
        f'[ui] el menú no pudo crecer con el catálogo: {_e_menu}')


# v144 — AGRUPACIÓN POR PAÍS.
#
# Con 50 competiciones, la lista plana deja de ser navegable: hay que
# desplazarse por medio menú para encontrar la Championship, y las cuatro
# divisiones inglesas quedan repartidas por toda la lista según cómo se llamen.
#
# El mapa NO se escribe a mano. Sale de `config.LEAGUES['pais']`, que es el
# mismo campo que ya alimenta las banderas: si mañana entra una liga nueva,
# aparece en su país sola. Mantener a mano una segunda lista de 50 entradas es
# exactamente lo que produjo el desfase que esta versión arregla.
GRUPO_DESTACADOS = '⭐ Deportes y destacados'
PAIS_TODOS = '🌐 Todas las competiciones'

# Los países más jugados primero y el resto alfabético. No es capricho: el
# 80 % de las aperturas van a media docena de ligas, y obligar a buscar
# «Inglaterra» entre veinte países ordenados por alfabeto es peor experiencia
# que un orden que reconoce para qué se abre la aplicación.
_PAISES_PRIMERO = ('Inglaterra', 'España', 'Italia', 'Alemania', 'Francia',
                   'México', 'Estados Unidos', 'Brasil', 'Argentina', 'Europa')


# Las entradas del menú que NO salen del catálogo de ligas. Se declara ANTES
# de la función que la usa, y no después: en este fichero un nombre definido
# más abajo del punto donde se usa ya dejó la aplicación sin arrancar una vez
# (UnboundLocalError que ni `py_compile` ni el AST detectan). Aquí serían
# globales de módulo y funcionaría igual, pero el orden se mantiene por
# disciplina, no porque el intérprete lo exija.
_NO_SON_LIGAS_PREVIO = {'mundial', 'alpha', 'mlb_deporte', 'kbo_deporte',
                        'nba_deporte', 'tennis_deporte', 'nfl_deporte'}


def _pais_de(clave: str) -> str:
    """El país de una competición, con las vistas de deporte en su grupo."""
    if clave in _NO_SON_LIGAS_PREVIO:
        return GRUPO_DESTACADOS
    try:
        import config as _c
        p = (_c.LEAGUES.get(clave) or {}).get('pais')
        return p or GRUPO_DESTACADOS
    except Exception:
        return GRUPO_DESTACADOS


def _mapa_paises(competencias: dict) -> dict:
    """`{país: [(etiqueta, clave), …]}`, con los destacados siempre primero."""
    mapa: dict = {}
    for _et, _k in competencias.items():
        mapa.setdefault(_pais_de(_k), []).append((_et, _k))
    for _p in mapa:
        mapa[_p].sort(key=lambda t: t[0])
    orden = ([GRUPO_DESTACADOS]
             + [p for p in _PAISES_PRIMERO if p in mapa]
             + sorted(p for p in mapa
                      if p != GRUPO_DESTACADOS and p not in _PAISES_PRIMERO))
    return {p: mapa[p] for p in orden if p in mapa}


PAIS_COMPETICIONES = _mapa_paises(COMPETENCIAS)

# v98 — EL SELECTOR NO PUEDE OFRECER UNA LIGA QUE EL CATÁLOGO NO TIENE.
#
# Las competiciones de fútbol de arriba están escritas a mano, así que pueden
# desincronizarse del `config.LEAGUES` que esté cargado. Y eso no da un aviso:
# da un `KeyError` en `render_liga_club` que deja la app EN BLANCO. Pasó en
# producción con `leagues_cup` al desplegar la v97, con la liga presente en el
# `config.py` publicado — Streamlit Cloud conserva módulos viejos en
# `sys.modules` entre despliegues (misma causa que la v79 documentó en
# `calibracion_segura`), así que durante la recarga convive un `dashboard_ui`
# nuevo con un `config` viejo.
#
# Aquí se cae la entrada del menú en vez de la aplicación. `_NO_SON_LIGAS` son
# las vistas que no salen del catálogo y por eso no se comprueban.
_NO_SON_LIGAS = {'mundial', 'alpha', 'mlb_deporte', 'kbo_deporte',
                 'nba_deporte', 'tennis_deporte', 'nfl_deporte'}   # v131
try:
    import logging as _log_menu

    import config as _cfg_menu
    _huerfanas = [_et for _et, _k in COMPETENCIAS.items()
                  if _k not in _NO_SON_LIGAS and _k not in _cfg_menu.LEAGUES]
    for _et in _huerfanas:
        COMPETENCIAS.pop(_et, None)
    if _huerfanas:
        _log_menu.getLogger(__name__).warning(
            f"[ui] {len(_huerfanas)} competiciones fuera del menú porque no "
            f"están en el catálogo cargado: {_huerfanas}")
except Exception:
    # Este bloque es una RED, no una función: si falla, el menú se queda como
    # estaba y manda la guardia de `render_liga_club`. Lo que no puede hacer
    # es lanzar — sería el mismo fallo que viene a evitar.
    pass
# v114 — AQUÍ SE CONSUME EL DESTINO DE UNA TARJETA PULSADA.
#
# Tiene que ser exactamente aquí: después de construir `COMPETENCIAS` (hace
# falta el mapa etiqueta→clave) y ANTES del `st.selectbox` de abajo, porque
# Streamlit prohíbe escribir la clave de un widget ya instanciado. Ver
# `navegacion.py` para el porqué del rodeo en dos pasos.
try:
    import navegacion as _nav

    def _equipos_de(clave_liga):
        """Catálogo de la competición de destino, para escribir el nombre tal
        y como lo espera su selector."""
        if clave_liga in _nav.SELECTORES_DEPORTE:
            return None                 # cada deporte tiene el suyo; no se toca
        return getattr(cargar_motor_liga(clave_liga), 'equipos', None)

    _nav.aplicar_pendiente(st, COMPETENCIAS, equipos_de_liga=_equipos_de)
    # v141: la vuelta a Apuestas del Día, consumida antes de que exista el
    # selector — que es el único momento en que se puede escribir su clave.
    if st.session_state.pop('_volver_a_alpha', False):
        for _et, _cl in COMPETENCIAS.items():
            if _cl == 'alpha':
                st.session_state['competencia'] = _et
                break
except Exception:
    # una navegación fallida NUNCA puede costar la página: si algo va mal, el
    # usuario se queda en la vista en la que estaba.
    pass

# v122 — LA BARRA DE MARCA, ARRIBA DEL TODO.
#
# La aplicación empezaba directamente con un desplegable etiquetado
# «🏆 Competición» sobre fondo blanco. Sin un encabezado, ninguna pantalla
# decía QUÉ es esto ni de dónde salen los números, y la primera impresión era
# la de un formulario. Esta barra no ocupa apenas y fija las dos cosas que
# gobiernan todo lo demás: que el edge está en el precio y que hay seis casas
# detrás de cada cuota.
_pinta(_estilo.cabecera(
    'Predictor deportivo',
    'Predicción, cuotas de seis casas y combinadas — con lo que el proyecto '
    'tiene medido delante, no en letra pequeña.',
    chips=[('⚽ fútbol', 'info'), ('⚾ MLB · KBO', 'info'),
           ('🏀 NBA', 'info'), ('🎾 tenis', 'info'), ('🏈 NFL', 'info'),
           ('el edge está en el precio', 'ok')],
    icono='🎯') if _estilo else None)

# v23 (móvil): el selector de competición vive ARRIBA del área principal —
# en el teléfono la barra lateral llega colapsada y el usuario no encontraba
# las ligas. El estado se comparte con st.session_state.
# v144 — SELECTOR JERÁRQUICO: PAÍS → COMPETICIÓN.
#
# El país FILTRA, no obliga. La primera opción es «Todas las competiciones», y
# con ella el desplegable de abajo se comporta exactamente como antes: la
# lista entera, en un solo clic. Elegir un país la recorta.
#
# Se hace así y no como dos pasos obligatorios por dos razones concretas:
#
#   1. **No rompe nada de lo que ya funcionaba.** El desplegable de competición
#      conserva su clave (`competencia`) y sus etiquetas, así que los enlaces
#      internos (`navegacion.marcar`), el estado de sesión y el smoke de
#      botones —que selecciona por etiqueta— siguen valiendo sin tocarlos.
#   2. **Un paso obligatorio de más se paga cada vez.** Quien entra a mirar la
#      Premier tendría que elegir «Inglaterra» primero, siempre. Filtrar es
#      opcional para quien lo necesita y gratis para quien no.
_paises = list(PAIS_COMPETICIONES.keys())
_col_pais, _col_comp = st.columns([1, 2])
_pais_sel = _col_pais.selectbox(
    "🌍 País", [PAIS_TODOS] + _paises, index=0, key='pais_competicion',
    help="Filtra el desplegable de al lado. Con «Todas» se ven las "
         f"{len(COMPETENCIAS)} competiciones juntas.")
if _pais_sel == PAIS_TODOS:
    _opciones_comp = list(COMPETENCIAS.keys())
else:
    _opciones_comp = [_et for _et, _ in PAIS_COMPETICIONES.get(_pais_sel, [])]
    # Al cambiar de país, lo que hubiera elegido antes puede no estar en la
    # lista nueva. Streamlit conserva el valor de `session_state` y entonces
    # lanza una excepción por un default que ya no es una opción, que es una
    # pantalla en blanco. Se limpia aquí, que es donde se sabe.
    if st.session_state.get('competencia') not in _opciones_comp:
        st.session_state.pop('competencia', None)
competencia_sel = _col_comp.selectbox(
    "🏆 Competición", _opciones_comp, index=0, key='competencia',
    help="En móvil: elige aquí la liga; los controles finos (modo, bankroll) "
         "siguen en la barra lateral (botón » arriba a la izquierda). "
         "Escribe para buscar.")
st.sidebar.checkbox(
    "🤖 Reescribir comentarios con SLM local (Ollama)", value=False, key='usar_slm',
    help="Opcional y solo en ejecución local: si tienes Ollama corriendo "
         "(OLLAMA_MODEL, por defecto phi3), el comentario del analista se "
         "reescribe con el modelo. Sin Ollama, se usa el comentario base.")

# v122 — LA BARRA LATERAL, ORDENADA.
#
# Tenía cuatro controles de tres tipos distintos, sin agrupar y sin decir a qué
# afecta cada uno: la casilla de Ollama (que sólo sirve en local) salía primera
# y el bankroll —el único que cambia números en pantalla— el último.
if _estilo is not None:
    with st.sidebar:
        _estilo.pinta(st, _estilo.seccion('Tus ajustes',
                                          'afectan a toda la app', 'ok'))

# v14/M11: modo de uso — Principiante muestra solo lo esencial para apostar
MODO_USO = st.sidebar.radio(
    "🎚️ Modo de uso", ['🟢 Principiante', '🔵 Pro'], index=1,
    help="**Principiante**: ganador, marcador, over/under y parlay guiado, "
         "sin jerga técnica. **Pro**: plantilla completa (~85 campos), "
         "distribuciones, monitor de features y todos los mercados.")
ES_PRO = MODO_USO.startswith('🔵')
st.sidebar.caption(
    "💡 **EV** (valor esperado): ganancia media por unidad apostada si "
    "repitieras la apuesta muchas veces. EV positivo = el modelo cree que "
    "la cuota paga de más. **Cuota justa** = 1/probabilidad, sin margen de casa.")

# v19: gestión de banca (¼ Kelly sobre mercados con EV > 0 y cuota real)
# v119: el diccionario completo, siempre a mano en la barra lateral
if _ayuda is not None:
    with st.sidebar:
        _ayuda.glosario_completo(st)

# v127 — EL CONTADOR DE CRÉDITOS, A LA VISTA.
#
# El consenso ampliado (20 casas en vez de 5) sale del plan GRATUITO de The
# Odds API: 500 créditos al mes que se renuevan. Sin este contador no hay forma
# de saber si la app está usando el consenso ampliado o ya cayó al de cinco
# casas, y esa diferencia decide si la Sección 1 puede detectar algo.
#
# Se lee del contador que devuelve el propio proveedor en cada respuesta
# (`x-requests-used`), que es el único número que no se descuadra si la app
# corre desde dos sitios a la vez.
def _panel_creditos_api() -> None:
    """Créditos de la API en la barra lateral, con su aviso si quedan pocos."""
    try:
        import consenso_api as _oa
    except Exception:
        return
    with st.sidebar:
        if not _oa.disponible():
            _pinta(_estilo.seccion('Consenso del mercado', '5 casas', 'info')
                   if _estilo else None)
            st.caption(
                "Sin `ODDS_API_KEY` en los Secrets. El tablón funciona con sus "
                "**5 casas** de siempre; con la clave pasa a ~20 y la Sección 1 "
                "puede detectar ventajas que ahora no se ven.")
            return
        p = _oa.presupuesto()
        usados, cuota = p['usados'], p['cuota']
        quedan = max(cuota - usados, 0)
        tono = ('no' if p['agotado'] else
                'mira' if quedan < 100 else 'ok')
        _pinta(_estilo.seccion('Créditos API', p['mes'], tono)
               if _estilo else None)
        # v129 — EL REPARTO DEL DÍA, NO SÓLO EL TOTAL DEL MES.
        #
        # Desde que el barrido del día pide consenso, el gasto puede
        # dispararse: 15 ligas cada media hora son 720 créditos diarios si
        # nadie lo reparte. `consenso_api` lo corta por días restantes, y ese
        # número tiene que verse, porque explica por qué a media tarde un
        # partido puede salir con el tablón básico teniendo créditos de sobra
        # en el mes. Sin esto parecería una avería.
        _pd = _oa.presupuesto_dia()
        _tono_dia = ('mira' if _pd['agotado_dia'] else 'ok')
        _pinta(_estilo.kpis([
            {'valor': f"{usados} / {cuota}", 'etiqueta': 'Consumidos',
             'tono': tono, 'sub': f"{quedan} restantes este mes"},
            {'valor': f"{_pd['usados_dia']} / {_pd['limite_dia']}",
             'etiqueta': 'Hoy', 'tono': _tono_dia,
             'sub': ('cupo del día agotado' if _pd['agotado_dia']
                     else f"{_pd['queda_dia']} disponibles hoy")},
        ]) if _estilo else None)
        if _pd['agotado_dia'] and not p['agotado']:
            st.caption(
                f"🟡 **Hoy ya se usó el cupo de {_pd['limite_dia']} créditos.** "
                f"No es una avería: el mes se reparte por días para que no se "
                f"agote en una tarde. Quedan {quedan} para el resto del mes y "
                f"mañana vuelve a haber cupo. Mientras tanto el tablón sigue "
                f"con sus casas de siempre.")
        if _estilo is None:
            st.metric("Créditos API", f"{usados} / {cuota}")
        if p['agotado']:
            st.warning(
                f"⚠️ Límite alcanzado ({usados} de {cuota}). La app ha vuelto "
                f"al **consenso de 5 casas** hasta que el mes se renueve. No "
                f"se pierde nada más que la amplitud del consenso.")
        elif quedan < 100:
            st.warning(
                f"🟡 **Créditos bajos: {quedan} restantes.** Al llegar a "
                f"{cuota - p['limite']} de margen la app pasará al modo de "
                f"5 casas.")
        else:
            st.caption(
                f"Consenso ampliado **activo**. Cada consulta de una liga "
                f"cuesta 1 crédito y sirve para todos sus partidos durante "
                f"30 min. Corte automático a los {p['limite']}.")


_panel_creditos_api()

BANKROLL = st.sidebar.number_input(
    "💵 Mi bankroll (unidades)", min_value=0.0, max_value=1_000_000.0,
    value=1000.0, step=100.0, key='bankroll',
    help="Tu banca total para apostar. Con cuotas reales y EV positivo, la "
         "app sugiere el stake por ¼ de Kelly (tope 5 % del bankroll por "
         "apuesta). Solo informativo.")

def render_alpha_finder():
    """v26 (§4.1-§4.2): Apuestas del Día + simulador Montecarlo de bankroll."""
    # v128 — EL CHIP DE CASAS DEJA DE SER UN LITERAL.
    #
    # Decía «6 casas» escrito a mano, así que seguía diciendo 6 tanto si el
    # consenso ampliado estaba activo (hasta 20 casas) como si no. El usuario
    # lo leyó como un tope del sistema —«sólo 6 casas»— cuando en realidad es
    # el tablón base, y lo que decide si se amplía es un secreto que hoy falta.
    #
    # El número que importa no es cuántas casas EXISTEN, sino cuántas
    # respaldan la comparación: con 6 una desviación del 5 % es ruido; con 20
    # es una señal. Por eso el chip dice también si el consenso está ampliado
    # o en modo de respaldo, igual que la ficha de partido desde la v127.
    _chip_casas, _tono_casas = '6 casas', 'azul'
    try:
        import consenso_api as _oa_chip
        if _oa_chip.disponible() and _oa_chip.hay_presupuesto():
            _chip_casas, _tono_casas = '6 casas + consenso (~20)', 'ok'
        elif _oa_chip.disponible():
            _chip_casas, _tono_casas = '6 casas · créditos agotados', 'mira'
        else:
            _chip_casas, _tono_casas = '6 casas · sin ODDS_API_KEY', 'mira'
    except Exception:
        pass
    _cabecera(
        'Apuestas del Día',
        'Todos los partidos de HOY con cuota y valor calculados solos, '
        'ordenados para que lo accionable esté arriba.',
        chips=[(_chip_casas, _tono_casas), ('hora de CDMX', 'info'),
               ('⚽ ⚾ 🏀 🎾 🏈', 'info')],
        icono='💎')
    if _tono_casas == 'mira':
        # El número de la barra lateral («cinco casas») y el de este chip
        # («6») no se contradicen, pero puestos uno al lado del otro lo
        # parecen: el consenso lo forman cinco casas y la sexta fuente es
        # DraftKings a través de ESPN. Se dice entero para que no haya que
        # adivinarlo.
        st.caption(
            "🟡 **El tablón va con sus 6 fuentes de precio base**: cinco casas "
            "—Pinnacle, Bovada, Unibet, Matchbook y Playdoit— más DraftKings "
            "a través de ESPN. El consenso ampliado a ~20 casas necesita "
            "`ODDS_API_KEY` en los Secrets de Streamlit Cloud. No es un tope "
            "del sistema: es una clave que falta, y con más casas la Sección 1 "
            "detecta ventajas de precio que con seis no se distinguen del "
            "ruido.")
    if _ayuda is not None:
        _ayuda.render(st, 'apuestas_dia')
    st.caption("SOLO los partidos de **HOY**: todas las ligas con "
               "jornada este día (ESPN + Pinnacle + Bovada + Playdoit + "
               "Unibet + Matchbook) + "
               "⚾ MLB, 🏀 NBA, 🎾 tenis ATP/WTA y 🏈 NFL, con cuota y EV automáticos. "
               "**Todas las horas están en hora de Ciudad de México.** "
               "**Capa 1** = cuota real con EV; **Capa 2** = alta confianza "
               "sin cuota en vivo; **Pronósticos** = todos los partidos de "
               "hoy. La semana completa vive en la vista de cada liga "
               "(«Próximos partidos»).")
    # v47/v49: acciones SIEMPRE visibles arriba — refrescar y enviar a Telegram
    # (el botón de Telegram estaba escondido en un expander; ahora es fijo).
    cacc1, cacc2 = st.columns(2)
    if cacc1.button("🔄 Actualizar ahora", key='refresh_alpha', width='stretch',
                    help="Vuelve a bajar cuotas y recalcula todas las apuestas."):
        # v86: antes esto hacía `st.cache_data.clear()`, que es GLOBAL al
        # proceso: un usuario pulsando "Actualizar" borraba el caché de todos
        # los demás y, de paso, los cerrojos que impiden barridos simultáneos.
        # Ahora sólo se marca que este usuario quiere datos frescos; el guardia
        # se encarga de que siga habiendo un único barrido a la vez.
        st.session_state['_forzar_barrido'] = True
        st.rerun()
    # v88 — El botón sólo MARCA la intención; el envío se hace más abajo,
    # cuando el barrido `r` ya está calculado, y se le pasa.
    #
    # Antes llamaba a `bot_telegram.construir_mensaje()` sin argumentos, y esa
    # función lanzaba `alpha_finder.apuestas_del_dia_universal()` por su cuenta:
    # un SEGUNDO barrido completo dentro del proceso de Streamlit, encima del
    # que ya estaba en memoria.
    #
    #     1 barrido  -> pico de 1.297,7 MB
    #     2 barridos -> pico de 2.172,2 MB   (_v86_barrido_concurrente.py)
    #
    # Eso es lo que tumbaba la app al pulsar «Enviar a Telegram»: no fallaba el
    # envío, fallaba la memoria de rehacer un trabajo que ya estaba hecho.
    if cacc2.button("📤 Enviar a Telegram ahora", key='tg_send_top',
                    width='stretch', type="primary",
                    help="Envía el resumen del día a tu Telegram (mismo mensaje "
                         "que el envío diario automático)."):
        st.session_state['_enviar_telegram'] = True

    # v86: pasa por el guardia de proceso (ver barrido_universal), que impide
    # que dos sesiones lancen el barrido a la vez. El spinner se pone aquí
    # porque el guardia no es un decorador de Streamlit.
    with st.spinner("🔍 Buscando valor en todos los deportes…"):
        r = barrido_universal(forzar=st.session_state.pop('_forzar_barrido', False))

    # v148 — LA EDAD DE LO QUE SE ESTÁ MIRANDO, ANTES DE MIRARLO.
    #
    # Desde que el guardia puede servir un barrido de hace un rato para que la
    # pantalla no tarde dos minutos en aparecer, hay una pregunta nueva que la
    # interfaz TIENE que responder sin que nadie la haga: ¿de cuándo es este
    # precio? El pronóstico del modelo aguanta perfectamente media hora —sale
    # de un modelo entrenado de madrugada—, pero una cuota de hace media hora
    # enseñada como la de ahora es justo lo que este proyecto no hace.
    #
    # Va aquí arriba, encima de las pestañas, porque debajo ya hay cuotas.
    # v154 — LA EDAD, EN HORAS CUANDO SON HORAS.
    #
    # La ventana de caché subió a 3 h para que la primera visita no pague los
    # ~52 s del barrido. A cambio, el aviso tiene que ser legible en todo el
    # rango: «hace 150 min» se lee mal y se subestima. Y el tono sube con la
    # edad — a partir de una hora deja de ser un apunte y pasa a ser una
    # advertencia, porque una cuota de hace dos horas puede no existir ya.
    _fr = (r or {}).get('_frescura') or {}
    if _fr and not _fr.get('fresco', True):
        _seg = int(_fr.get('edad_s', 0))
        _h, _m = _seg // 3600, (_seg % 3600) // 60
        _edad_txt = (f"{_h} h {_m:02d} min" if _h else f"{_m} min")
        _texto = (
            f"⏱️ Los precios que se ven se bajaron hace **{_edad_txt}** y se "
            f"están actualizando en segundo plano. Los pronósticos del modelo "
            f"siguen siendo válidos —sólo cambian cuando reentrena el bot—, "
            f"pero **confirma el precio en la casa antes de apostar**. "
            f"«Actualizar ahora» rehace el barrido.")
        (st.error if _seg >= 3600 else st.warning)(_texto)

    if st.session_state.pop('_enviar_telegram', False):
        try:
            import bot_telegram
            # se le pasa el barrido YA calculado: cero trabajo repetido
            msg = bot_telegram.construir_mensaje(r)
            if bot_telegram.enviar(msg):
                st.success("✅ Enviado a Telegram.")
            else:
                st.warning("Sin TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID en los "
                           "Secrets. Vista previa del mensaje:")
                st.code(msg, language=None)
        except Exception as e:
            st.error(f"No se pudo enviar ({type(e).__name__}: {e}).")
    # v41: BANNER de salud de datos — distingue "no llegan datos" (problema)
    # de "llegan pero hoy no hay picks" (normal). Antes salía indistinguible.
    try:
        import data_health
        salud = data_health.estado_datos()
        if salud['nivel'] == 'critico':
            st.error("🚨 **Alerta de datos** — " + (salud.get('alarma') or ''))
            for d in salud['detalles']:
                st.caption(d)
        elif salud['nivel'] == 'degradado':
            st.warning("⚠️ Cobertura de datos parcial hoy. " +
                       " · ".join(salud['detalles']))
    except Exception:
        pass
    if r.get('actualizado'):
        cob = r.get('cobertura_ligas', {})
        st.caption(f"Cuotas actualizadas: {r['actualizado']} · "
                   f"partidos evaluados: {r.get('partidos_evaluados', 0)} · "
                   f"ligas: {', '.join(f'{k}:{v}' for k, v in cob.items()) or '—'}"
                   + (f" · {r.get('partidos_sin_liga', 0)} sin mapear"
                      if r.get('partidos_sin_liga') else ''))
    if r.get('aviso'):
        st.info(r['aviso'])
    # v30 (§1): exportar las apuestas del día — BLINDADO (pre-genera el
    # contenido en try/except; un fallo aquí nunca debe romper la página).
    # v49: también con Capa 2 / pronósticos (el barrido ya casi nunca va vacío).
    if (r.get('elite') or r.get('candidatos') or r.get('capa2')
            or r.get('pronosticos')):
        try:
            import alpha_finder as _af
            txt = _af.exportar_txt(r)
            csv = _af.exportar_csv(r)
            fecha_exp = r.get('actualizado') or 'hoy'
            cexp1, cexp2 = st.columns(2)
            cexp1.download_button("📋 Exportar (texto)", txt,
                                  file_name=f"apuestas_{fecha_exp}.txt",
                                  width='stretch')
            cexp2.download_button("📊 Exportar (CSV)", csv,
                                  file_name=f"apuestas_{fecha_exp}.csv",
                                  mime='text/csv', width='stretch')
            # v32 (§7): copiar al portapapeles — st.code trae botón nativo
            with st.expander("📋 Copiar al portapapeles"):
                st.code(txt, language=None)
        except Exception as e:
            st.caption(f"⚠️ Exportación no disponible ahora ({type(e).__name__}).")

    # v115 — LA FRANJA QUE RESPONDE «¿QUÉ HAGO HOY?».
    #
    # Hasta ahora había que leer media pantalla para saber si merecía la pena
    # abrir la app. Cuatro cifras arriba del todo, y la más importante NO es el
    # número de picks: es la dispersión de precios, porque es lo único que este
    # proyecto ha medido con ROI positivo (+11,49 % en juicio, p5 +1,73 %).
    try:
        _n_capa1 = len(r.get('capa1') or [])
        _n_prons = len(r.get('pronosticos') or [])
        # v145 — EL CONTADOR TIENE QUE CUADRAR CON LAS PESTAÑAS.
        #
        # Decía 148 mientras las dos pestañas sumaban 141, y el usuario lo
        # notó. Los 7 de diferencia son reales y correctos: la ventana del
        # barrido se ensanchó a tres días UTC a propósito, para que el día de
        # MAÑANA EN CDMX entre entero (ver `alpha_finder._en_ventana`). O sea
        # que el barrido evalúa un día más de lo que se enseña.
        #
        # Un número de cabecera que no cuadra con la lista de debajo hace
        # dudar de los dos. Se cuenta lo mismo que se pinta: hoy y mañana en
        # hora de CDMX. Lo que sobra de la ventana no se tira —sirve para que
        # mañana esté completo— simplemente no se cuenta aquí.
        def _dia_cdmx_de(p):
            return (_horario.fecha(p.get('inicio'))
                    or str(p.get('fecha') or '')[:10])

        _hoy_kpi = _horario.fecha(pd.Timestamp.now('UTC')) or ''
        _man_kpi = (str(pd.Timestamp(_hoy_kpi).date() + pd.Timedelta(days=1))
                    if _hoy_kpi else '')
        _prons = [p for p in (r.get('pronosticos') or []) if isinstance(p, dict)]
        _de_hoy = [p for p in _prons if _dia_cdmx_de(p) == _hoy_kpi]
        _de_man = [p for p in _prons if _dia_cdmx_de(p) == _man_kpi]
        _hoy_ct = sum(1 for p in _de_hoy if p.get('cuota') or p.get('n_casas'))
        _casas_vistas = set()
        for _p in (r.get('capa1') or []):
            if _p.get('casa'):
                _casas_vistas.add(_p['casa'])
        f1, f2, f3, f4 = st.columns(4)
        f1.metric("Partidos evaluados", len(_de_hoy) + len(_de_man),
                  help=f"Los de hoy ({len(_de_hoy)}) más los de mañana "
                       f"({len(_de_man)}), en hora de CDMX — exactamente los "
                       f"que salen en las dos pestañas. El barrido mira un día "
                       f"más para que mañana esté completo, y ese sobrante no "
                       f"se cuenta aquí.")
        f2.metric("Hoy con cuota", _hoy_ct,
                  help=f"De los {len(_de_hoy)} de hoy, los que tienen precio "
                       f"abierto en alguna casa. El resto se muestran igual, "
                       f"marcados «sin cuota».")
        f3.metric("Pasan el filtro", _n_capa1,
                  help="Cumplen probabilidad, EV y fiabilidad mínimas. Que "
                       "sean pocos —o ninguno— es lo normal y es correcto.")
        # v141 — CONTABA EN EL SITIO EQUIVOCADO.
        #
        # `_casas_vistas` sale sólo de `capa1`, y `capa1` está vacía la mayoría
        # de los días —hoy tenía 0 picks—, así que el indicador enseñaba «—»
        # aunque el barrido hubiera comparado tres casas. Medido: Pinnacle 28
        # precios, Bovada 14, Playdoit 2, y el contador decía que ninguna.
        #
        # Se cuentan las casas de TODAS las listas del barrido, que es lo que
        # de verdad respalda el consenso. Y si no hay ninguna se dice con
        # palabras, porque un guion no distingue «cero» de «no lo sé».
        _casas_todas = set()
        for _lst in ('capa1', 'capa2', 'candidatos', 'pronosticos',
                     'capa1_prob', 'seleccion_dia'):
            for _p in (r.get(_lst) or []):
                if isinstance(_p, dict) and _p.get('casa'):
                    _casas_todas.add(str(_p['casa']))
        f4.metric("Casas comparadas",
                  len(_casas_todas) if _casas_todas else '0',
                  help=("Casas que han puesto precio hoy: "
                        + (', '.join(sorted(_casas_todas)) if _casas_todas
                           else 'ninguna ha respondido todavía, así que no hay '
                                'consenso con el que comparar')
                        + ". Cuantas más, más veces aparece un precio mejor "
                          "que el resto — es la ventaja medida del proyecto."))
        if not _casas_todas:
            st.caption("⚠️ **Consenso no disponible**: ninguna casa ha dado "
                       "precio en este barrido. Sin dos precios del mismo "
                       "suceso no se puede medir ventaja, así que hoy no hay "
                       "Sección 1 posible.")
    except Exception:
        pass

    # v32 (§5.3): PICK DEL DÍA único
    pdd = r.get('pick_del_dia')
    if pdd:
        # v93: se muestra la probabilidad CALIBRADA — la que el mercado
        # acierta de verdad en su banda, no la que promete el modelo.
        _pc = pdd.get('prob_calibrada')
        _pc = _pc if _pc is not None else (pdd.get('prob') or 0)
        st.success(f"🥇 **Pick del Día** — {pdd['partido']} ({pdd.get('liga','')})  \n"
                   f"**{pdd['apuesta']}** @ {pdd.get('cuota')} · "
                   f"**{_pc*100:.0f} % de acertar** · "
                   f"EV {(pdd.get('ev') or 0)*100:+.1f} % · "
                   f"{pdd.get('fiabilidad','')}")
        if pdd.get('nota_calibracion'):
            st.caption(f"ℹ️ {pdd['nota_calibracion']}")
    else:
        st.info("🥇 Hoy **no hay Pick del Día**: ninguno reúne confianza >80 %, "
                "EV entre +2 % y +15 % y fiabilidad histórica suficiente. "
                "Forzarlo sería el error clásico.")

    # v91 — LAS COMBINADAS SE MUEVEN AL FINAL DE LA PÁGINA.
    #
    # Estaban AQUÍ, antes de las pestañas, y las dos cargan motores de liga y
    # corren Monte Carlo: Streamlit ejecuta el script de arriba abajo, así que
    # Máximo Valor, Máxima Confianza y todo lo demás no aparecía hasta que las
    # combinadas terminaban (minutos en frío). El usuario lo veía como «la
    # página no abre hasta que clickeo» — el click forzaba un rerun con los
    # cachés ya calientes. Ver el final de esta función.
    def _render_combinada_segura(pdd):
        cand_combo = pdd if (pdd and pdd.get('deporte', 'Fútbol') == 'Fútbol') else None
        if not cand_combo:
            for _p in (r.get('capa1') or []):
                if _p.get('deporte', 'Fútbol') == 'Fútbol':
                    cand_combo = _p
                    break
        if not cand_combo:
            return
        # v82 — se usa la CLAVE que trae el pick. Invertir el mapa de nombres
        # elegía la liga equivocada cuando dos comparten nombre: «Primera
        # División» son Argentina, Uruguay Y El Salvador, y el inverso se
        # quedaba con la última. Resultado: se cargaba el motor salvadoreño y
        # se le pedían equipos argentinos → AttributeError, que es el
        # «Combinada no disponible ahora» que se veía en pantalla.
        _REV_LIGAS = {v: k for k, v in NOMBRES_LIGAS.items()}
        _clave_liga = (cand_combo.get('clave_liga')
                       or _REV_LIGAS.get(cand_combo.get('liga', '')))
        partes = str(cand_combo.get('partido', '')).split(' vs ')
        if _clave_liga and len(partes) == 2:
            with st.expander(f"🎰 Combinada segura del día — {cand_combo['partido']} "
                             "(un solo partido)", expanded=False):
                try:
                    from match_parlay import construir_parlay_partido
                    _motor_combo = cargar_motor_liga(_clave_liga)
                    rc = construir_parlay_partido(
                        _motor_combo, partes[0].strip(), partes[1].strip(),
                        num_selecciones=3, perfil='super_seguro',
                        excluir_alto_riesgo=True)
                    if 'error' in rc:
                        st.caption(rc['error'])
                    else:
                        st.markdown(f"**{rc['prob_conjunta']*100:.0f}% de acertar todo** "
                                    f"· cuota combinada **{rc['cuota_combinada']:.2f}** "
                                    f"(100 u → {rc['cuota_combinada']*100:.0f} u).")
                        for i, s in enumerate(rc['selecciones'], 1):
                            st.write(f"{i}. [{s['mercado']}] **{s['apuesta']}** "
                                     f"@ {s['cuota']} · {s['prob']*100:.0f}%")
                        st.caption("Propuesta automática (perfil súper seguro). "
                                   "Puedes armar la tuya en la vista de la liga → "
                                   "«🎰 Arma TU combinada de este partido».")
                except Exception as e:
                    st.caption(f"Combinada no disponible ahora ({type(e).__name__}).")

    # v58: COMBINADAS DEL DÍA — varias, de distintos partidos y perfiles.
    # v91: también diferidas al final de la página (ver el comentario de
    # arriba: cargan motores y bloqueaban el render de las pestañas).
    def _render_combinadas_dia():
      with st.expander("🎲 Combinadas del Día — varias opciones con cuota",
                       expanded=False):
        st.caption("Combinadas de UN SOLO partido (más controlables que las "
                   "multi-partido), de los mejores encuentros del día. Escalera "
                   "de la más segura a la de más cuota.")
        # v89 — SIN BOTÓN: el usuario pidió que todo lo automático sea
        # automático. Se calculan solas (cacheadas 30 min por lista de
        # partidos, así abrir el expander no repite el trabajo).
        from bankroll_manager import AVISO_JUEGO_RESPONSABLE   # v58.1 FIX
        _REV = {v: k for k, v in NOMBRES_LIGAS.items()}
        # candidatos: mejores picks de fútbol del día (Capa 1 → pronósticos),
        # HOY primero (v89: con la semana evaluada, sin este orden las
        # combinadas podían armarse con partidos del sábado)
        vistos, candidatos = set(), []
        _pool_combo = sorted(
            (r.get('capa1') or []) + (r.get('seleccion_dia') or [])
            + (r.get('pronosticos') or []),
            key=lambda p: (not p.get('es_hoy'), str(p.get('fecha', ''))))
        for p in _pool_combo:
            if p.get('deporte', 'Fútbol') != 'Fútbol':
                continue
            cl = p.get('clave_liga') or _REV.get(p.get('liga', ''))
            partes = str(p.get('partido', '')).split(' vs ')
            if not cl or len(partes) != 2 or p['partido'] in vistos:
                continue
            vistos.add(p['partido'])
            candidatos.append((cl, partes[0].strip(), partes[1].strip()))
            if len(candidatos) >= 4:
                break

        @st.cache_data(ttl=1800, show_spinner="Armando combinadas…",
                       max_entries=4)
        def _combinadas_dia(lista):
            from match_parlay import proponer_parlays
            out = []
            for cl, h, a in lista:
                try:
                    ops = proponer_parlays(cargar_motor_liga(cl), h, a,
                                           max_opciones=3)
                except Exception as e:
                    out.append((cl, h, a, None, type(e).__name__))
                    continue
                out.append((cl, h, a, ops or [], None))
            return out

        if not candidatos:
            st.info("Hoy no hay partidos con datos suficientes para armar "
                    "combinadas.")
        for cl, h, a, ops, err in _combinadas_dia(tuple(candidatos)):
            if err:
                st.caption(f"{h} vs {a}: no disponible ({err}).")
                continue
            if not ops:
                continue
            st.markdown(f"**⚽ {h} vs {a}** — {NOMBRES_LIGAS.get(cl, cl)}")
            for op in ops:
                with st.container(border=True):
                    k1, k2, k3 = st.columns([2, 1, 1])
                    k1.markdown(f"{op['etiqueta_opcion']} · "
                                f"{op['n_selecciones']} patas")
                    k2.metric("Prob.", f"{op['prob_conjunta']*100:.0f}%")
                    k3.metric("Cuota", f"{op['cuota_combinada']:.2f}")
                    st.caption(" + ".join(s['apuesta']
                                          for s in op['selecciones']))
        st.caption(AVISO_JUEGO_RESPONSABLE)

    # v37 (§5): PLAN DE ATAQUE TEMPORAL (oleadas)
    oleadas = r.get('oleadas') or {}
    if any(oleadas.get(k) for k in ('oleada1', 'oleada2', 'resto')):
        with st.container(border=True):
            st.markdown("**🌊 Plan de ataque temporal** — no inviertas más del "
                        "**50 % del bankroll** en una sola oleada.")
            co1, co2, co3 = st.columns(3)
            def _mejor(lst):
                return (f"{lst[0]['partido']} · {lst[0].get('apuesta','')} "
                        f"(EV {(lst[0].get('ev') or 0)*100:+.0f} %)") if lst else '—'
            co1.metric("🔴 Oleada 1 · Hoy", len(oleadas.get('oleada1', [])),
                       help=_mejor(oleadas.get('oleada1', [])))
            co2.metric("🟡 Oleada 2 · Mañana", len(oleadas.get('oleada2', [])),
                       help=_mejor(oleadas.get('oleada2', [])))
            co3.metric("📋 Días siguientes", len(oleadas.get('resto', [])),
                       help=_mejor(oleadas.get('resto', [])))

    def _fila_apuesta(t):
        """
        Una apuesta (mercado) de un partido.

        v122 — se rehace entera. Antes eran dos columnas de `st.markdown` con
        ocho datos del MISMO tamaño y el MISMO color separados por saltos de
        línea: la cuota, el EV, la probabilidad, la casa, la fiabilidad, el
        stake y dos notas. Con eso no se puede decidir de un vistazo cuál de
        seis tarjetas mirar, que es exactamente para lo que sirve esta
        pantalla.
        Ahora hay jerarquía: la apuesta manda, la cuota va en grande y con la
        casa debajo, y lo que matiza va en píldoras de color con significado
        (ver `estilo_ui.tono_por_ev`: verde SÓLO si hay varias casas
        comparadas, porque es lo único con ROI medido positivo).
        """
        pref = ('💠 ' if t.get('sharp_confirmado') else '') \
            + ('⭐ ' if t.get('platino') else '') \
            + ('⚡ ' if t.get('shadow') else '')
        cuota = t.get('cuota')
        _p_vis = t.get('prob_calibrada')
        _p_vis = _p_vis if _p_vis is not None else t.get('prob')
        rent = t.get('rentabilidad') or {}
        _gap = t.get('sharp_gap')
        import traductor_quant as _tq

        if _estilo is not None:
            _n_casas = int(t.get('n_casas') or 1)
            _tono = (_estilo.tono_por_ev(t.get('ev'), _n_casas)
                     if cuota else 'info')
            etqs = []
            if cuota:
                etqs.append((f"EV {(t.get('ev') or 0)*100:+.1f} %", _tono))
            else:
                etqs.append(('sin cuota abierta todavía', 'info'))
            if t.get('casa'):
                etqs.append((f"🏠 {t['casa']}", 'azul'))
            if t.get('sharp_confirmado'):
                etqs.append(('💠 confirmado por el sharp', 'ok'))
            if t.get('stake_txt'):
                etqs.append((f"💼 {t['stake_txt']}", 'azul'))
            if rent.get('etiqueta') and rent.get('tier') != 'sin_ev':
                etqs.append((str(rent['etiqueta']), 'info'))
            _pinta(_estilo.pata(
                f"{pref}{t.get('apuesta','?')}",
                cuota or t.get('cuota_justa'),
                _p_vis, t.get('mercado', ''), etqs, _tono))
            # la probabilidad también en barra: un «69 %» y un «51 %» se leen
            # igual de rápido y no se distinguen; una barra sí
            if _p_vis is not None:
                _pinta(_estilo.barra(_p_vis, _tono))
            _pie = []
            if not cuota:
                _pie.append(f"Cuota mínima que merecería la pena: "
                            f"**{t.get('cuota_justa','?')}**")
            else:
                _pie.append(f"Cuota justa del modelo: {t.get('cuota_justa','?')}")
            if t.get('sharp_confirmado'):
                _pie.append(_tq.frase_sharp(_gap, ES_PRO))
            for _k in ('fiabilidad', 'nota_seleccion', 'nota'):
                if t.get(_k):
                    _pie.append(str(t[_k]))
            if t.get('motivo_capa2'):
                _pie.append(f"Fuera de élite: {t['motivo_capa2']}")
            if _pie:
                st.caption(' · '.join(_pie))
        else:
            # sin capa visual, la fila de siempre
            if cuota:
                precio = (f"{t.get('valor','')} Cuota **{cuota}** "
                          f"(justa {t.get('cuota_justa','?')})  \n"
                          f"EV **{(t.get('ev') or 0)*100:+.1f} %** · "
                          f"prob {(t.get('prob') or 0)*100:.0f} %")
                if t.get('casa'):
                    precio += f"  \n🏠 {t['casa']}"
                if t.get('motivo_capa2'):
                    precio += f"  \nℹ️ Fuera de élite: {t['motivo_capa2']}"
            else:
                precio = (f"🎯 Sin cuota abierta todavía  \n"
                          f"Cuota mínima sugerida **{t.get('cuota_justa','?')}** · "
                          f"prob {(t.get('prob') or 0)*100:.0f} %")
            c2, c3 = st.columns([2, 3])
            c2.markdown(f"**{pref}{t.get('apuesta','?')}**  \n"
                        f"{t.get('mercado','')}")
            c3.markdown(precio
                        + (f"  \n**{_tq.frase_sharp(_gap, ES_PRO)}**"
                           if t.get('sharp_confirmado') else '')
                        + (f"  \n{t['fiabilidad']}" if t.get('fiabilidad') else '')
                        + (f"  \n{rent['etiqueta']}" if rent.get('etiqueta')
                           and rent.get('tier') != 'sin_ev' else '')
                        + (f"  \n💼 Stake: **{t['stake_txt']}**"
                           if t.get('stake_txt') else '')
                        + (f"  \nℹ️ {t['nota_seleccion']}"
                           if t.get('nota_seleccion') else '')
                        + (f"  \n{t['nota']}" if t.get('nota') else ''))
        # v47: tenis — 19 mercados derivados para armar parlays
        mts = t.get('mercados_tenis') or []
        if mts:
            with st.expander(f"🎾 Ver {len(mts)} mercados de este partido "
                             "(para parlays)"):
                import pandas as _pd
                df = _pd.DataFrame([
                    {'Mercado': c['etiqueta'],
                     'Probabilidad': f"{c['valor']:.0f}%",
                     'Cuota justa': round(100 / max(c['valor'], 1e-6), 2)}
                    for c in sorted(mts, key=lambda x: -x['valor'])])
                st.dataframe(df, hide_index=True, width='stretch')

    def _etiqueta_dia(fecha):
        """
        v95 — ÚLTIMA GUARDIA contra una fecha imposible.

        El origen ya está arreglado (`cuotas_multi.fecha_normalizada`), pero
        esto es lo que el usuario ve: si por cualquier vía futura llegara una
        fecha absurda, aquí se dice «fecha no disponible» en vez de imprimir
        «Hoy · 1970-01-01», que es lo que salió en las tarjetas de MLB.
        """
        hoy = pd.Timestamp.now('UTC').tz_localize(None).normalize()
        try:
            f = pd.Timestamp(fecha).normalize()
        except (ValueError, TypeError):
            return '📅 Fecha no disponible'
        if not (2000 <= f.year <= 2100):
            return '📅 Fecha no disponible'
        if f <= hoy:
            return f"📅 Hoy · {fecha}"
        if f == hoy + pd.Timedelta(days=1):
            return f"📅 Mañana · {fecha}"
        return f"📅 {fecha}"

    # v114 — contador para las claves de los botones «Ver el partido».
    #
    # El mismo partido aparece en varias listas de esta página (Máximo Valor,
    # Máxima Confianza, pronósticos, oleadas), y `_tarjetas` se llama una vez
    # por lista. Una clave construida con partido+fecha se repetía y Streamlit
    # lanzaba `There are multiple elements with the same key` — lo cazó
    # `smoke_botones.py`, que es justo para lo que está.
    #
    # El contador es determinista: el orden de render no cambia entre
    # ejecuciones, así que la clave de cada botón es estable de un rerun al
    # siguiente, que es lo que Streamlit necesita para no perder el estado.
    _n_boton = {'i': 0}

    def _tarjetas(lista, titulo, agrupar_dia=True):
        """v89 — agrupación en dos niveles, pedida por el usuario:
          · por DÍA (hoy primero, luego el resto de la semana), y
          · por PARTIDO (todas las apuestas con valor de un partido juntas,
            no solo la mejor).
        """
        if not lista:
            return
        if titulo:
            st.subheader(titulo)
        # nivel 1: día (el orden de llegada dentro del día se conserva)
        dias: dict = {}
        for t in lista:
            dias.setdefault(str(t.get('fecha', '')), []).append(t)
        for fecha in sorted(dias):
            if agrupar_dia and len(dias) > 1:
                st.markdown(f"**{_etiqueta_dia(fecha)}**")
            # nivel 2: partido
            partidos: dict = {}
            for t in dias[fecha]:
                clave = (t.get('deporte', 'Fútbol'), t.get('partido', '?'))
                partidos.setdefault(clave, []).append(t)
            for (_dep, _p), ts in partidos.items():
                t0 = ts[0]
                # v90: techo real de acierto de la competición (medido sobre el
                # ledger, estable entre mitades con correlación 0,72)
                _techo = ''
                try:
                    import precision_ligas as _pl
                    _techo = _pl.etiqueta(t0.get('clave_liga'))
                except Exception:
                    pass
                # v106 — LA HORA, EN HORA DE CDMX.
                #
                # Las fuentes publican el inicio y el barrido ya lo guardaba
                # (`inicio`, UTC), pero la tarjeta sólo enseñaba el día. Sin
                # la hora no se puede decidir «antes de que empiece», que es
                # justo para lo que se usa esta pantalla. `hora_txt` lo pone
                # `alpha_finder` al cerrar el barrido; si la fuente no trajo
                # hora, queda vacío y la tarjeta se ve como siempre.
                #
                # Se enseña también la FECHA de CDMX cuando difiere de la
                # fecha UTC con la que está agrupada la tarjeta: un partido de
                # las 01:00 UTC del sábado se juega el viernes por la noche en
                # México, y enseñar «sábado 19:00» sería mentir.
                _hora = t0.get('hora_txt') or ''
                if _hora and t0.get('fecha_cdmx') \
                        and t0.get('fecha_cdmx') != str(t0.get('fecha', '')):
                    _hora = _horario.etiqueta(t0.get('inicio'), con_fecha=True)
                _falta = ''
                try:
                    _falta = _horario.falta_para(t0.get('inicio')) or ''
                except Exception:
                    _falta = ''
                with st.container(border=True):
                    # v122 — la cabecera del partido, con los dos equipos
                    # enfrentados y su contexto en UNA línea de metadatos, en
                    # vez de cuatro saltos de línea con todo del mismo peso.
                    _pintado = False
                    if _estilo is not None:
                        _nom = str(t0.get('partido', '?'))
                        _sep = next((x for x in (' vs ', ' vs. ', ' @ ', ' - ')
                                     if x in _nom), None)
                        if _sep:
                            _h_c, _a_c = _nom.split(_sep, 1)
                            _meta = [t0.get('deporte', 'Fútbol'),
                                     t0.get('liga', ''), t0.get('fecha', '')]
                            if _hora:
                                _meta.append(_hora)
                            if _falta:
                                _meta.append(_falta)
                            if t0.get('antiguedad'):
                                _meta.append(t0['antiguedad'])
                            if _techo:
                                _meta.append(_techo)
                            _pinta(_estilo.cabecera_partido(_h_c, _a_c, _meta))
                            _pintado = True
                    if not _pintado:
                        st.markdown(
                            f"**{t0.get('partido','?')}**  \n"
                            f"{t0.get('deporte','Fútbol')} · {t0.get('liga','')} · "
                            f"{t0.get('fecha','')}"
                            + (f"  \n{_hora}" + (f" · {_falta}" if _falta else '')
                               if _hora else '')
                            + (f"  \n{t0['antiguedad']}" if t0.get('antiguedad')
                               else '')
                            + (f"  \n{_techo}" if _techo else ''),
                            help=("Frescura de los datos con los que se entrenó "
                                  "esta liga: el modelo no ve partidos nuevos "
                                  "desde hace ese número de días.")
                            if t0.get('antiguedad') else None)
                    # v114 — LA TARJETA LLEVA A SU PARTIDO.
                    #
                    # Pedido del usuario: «si hago click me llevas a Liga MX al
                    # partido seleccionado para ver sus estadísticas y evaluar
                    # qué parlay meter». El botón sólo APUNTA el destino; la
                    # navegación la ejecuta `navegacion.aplicar_pendiente` al
                    # principio del script siguiente, porque tocar aquí la
                    # clave del selector de competición —ya instanciado más
                    # arriba— es un error de Streamlit, no una opción de
                    # diseño.
                    _dest = None
                    try:
                        import navegacion as _nav
                        _dest = _nav.destino_del_pick(t0)
                    except Exception:
                        _dest = None
                    if _dest:
                        _n_boton['i'] += 1
                        _kb = f"ir_partido_{_n_boton['i']}"
                        if st.button(
                                f"📊 Ver {t0.get('partido','el partido')} en "
                                f"{t0.get('liga') or _dep} →",
                                key=_kb, width='stretch',
                                help="Abre la vista de esa competición con "
                                     "este partido cargado: historial, "
                                     "clasificación, forma, todos los "
                                     "mercados y el constructor de "
                                     "combinadas."):
                            _nav.marcar(st, _dest)
                            st.rerun()
                    for i, t in enumerate(ts):
                        if i:
                            st.divider()
                        _fila_apuesta(t)

    # -----------------------------------------------------------------------
    # v77 — TRES PESTAÑAS. La sección de siempre pasa a ser la primera; las
    # otras dos son vistas nuevas sobre los MISMOS modelos y las mismas cuotas
    # reales, así que no hay riesgo de degradar nada: cambia el criterio de
    # selección, no la predicción.
    # -----------------------------------------------------------------------
    _render_incidencias(r)          # v77: visible antes de las pestañas

    # v131 — EL FILTRO DE DEPORTE, Y POR QUÉ NO TOCA LOS DATOS.
    #
    # Filtra en el PUNTO DE PINTADO, no el barrido. Si recortara `r`, el botón
    # de Telegram enviaría sólo el deporte seleccionado y la exportación saldría
    # coja — y el envío diario es un canal que no puede depender de dónde tenga
    # puesto el usuario un selector. Así que `r` se queda entero y lo único que
    # se filtra son las listas justo antes de dibujarlas.
    _DEPORTES_FILTRO = [('Todo', 'Todo'), ('⚽', 'Fútbol'), ('⚾', 'MLB'),
                        ('🏀', 'NBA'), ('🎾', 'Tenis'), ('🏈', 'NFL')]
    _presentes = {p.get('deporte') for p in (r.get('pronosticos') or [])
                  if p.get('deporte')}
    _opciones = [e for e, d in _DEPORTES_FILTRO
                 if d == 'Todo' or d in _presentes]
    _mapa_dep = {e: d for e, d in _DEPORTES_FILTRO}
    # v176 — LA ELECCIÓN SOBREVIVE A LA RECARGA.
    #
    # Entre pestañas ya persistía —las dos leen la misma clave global,
    # `_filtro_deporte`, así que Hoy y Mañana comparten estado dentro de
    # una sesión—. Lo que no sobrevivía era recargar la página, y el
    # encargo lo pide: «guardarse en un archivo de preferencias para que al
    # recargar la app se mantengan».
    #
    # `recordar` sólo SIEMBRA: si el usuario ya tocó el control en esta
    # sesión, lo que acaba de elegir manda sobre lo guardado. Y si el
    # deporte guardado hoy no está en el barrido —ayer había tenis y hoy
    # no—, `leer_opcion` lo descarta en vez de reventar el `radio` con un
    # valor que no está en su lista.
    try:
        import preferencias_usuario as _prefu
    except Exception:
        _prefu = None
    if len(_opciones) > 2:
        if _prefu is not None:
            _prefu.recordar(st, '_filtro_deporte', _opciones, 'Todo')
        _sel = st.radio('Deporte', _opciones, horizontal=True,
                        key='_filtro_deporte', label_visibility='collapsed',
                        help='Reordena lo que se ve. No cambia lo que se '
                             'envía a Telegram ni lo que se exporta. Se '
                             'recuerda entre pestañas y entre sesiones.')
        if _prefu is not None:
            _prefu.guardar('_filtro_deporte', _sel)
    else:
        _sel = 'Todo'
    _dep_sel = _mapa_dep.get(_sel, 'Todo')

    # v152 — EL FILTRO DE LIGAS SECUNDARIAS, EN EL MISMO SITIO QUE EL DE
    # DEPORTE Y POR EL MISMO MOTIVO.
    #
    # Se pidió para poder mirar sólo las competiciones de menos volumen. Va
    # aquí arriba, al lado del deporte, y no dentro de una pestaña: dos
    # controles del mismo eje en dos sitios acaban divergiendo, y entonces el
    # mismo partido aparece en una pantalla y no en la otra. Es la lección de
    # la v141 aplicada antes de que ocurra.
    #
    # Lo que este filtro NO hace: prometer que las secundarias rinden más. Es
    # una hipótesis razonable —menos volumen, líneas menos trabajadas— que en
    # este proyecto todavía no tiene su propio percentil 5.
    _GRUPOS_LIGA = ['Todas', 'Sólo secundarias', 'Sólo principales']
    if _prefu is not None:
        _prefu.recordar(st, '_filtro_grupo_liga', _GRUPOS_LIGA,
                        'Todas')
    _grupo_liga = st.radio(
        'Competiciones', _GRUPOS_LIGA,
        horizontal=True, key='_filtro_grupo_liga', label_visibility='collapsed',
        help='«Secundaria» es toda competición de FÚTBOL que no está en la '
             'lista corta de ligas grandes. El resto de deportes no se reparte '
             'por este eje —la MLB no es una liga de fútbol secundaria— así '
             'que sólo aparecen en «Todas». Reordena lo que se ve: no cambia '
             'el barrido, ni el envío a Telegram, ni la exportación.')

    if _prefu is not None:
        _prefu.guardar('_filtro_grupo_liga', _grupo_liga)

    def _filtra(lista):
        """La lista tal cual, o sólo lo elegido. Nunca muta el barrido."""
        salida = list(lista or [])
        if _dep_sel != 'Todo':
            salida = [p for p in salida
                      if isinstance(p, dict) and p.get('deporte') == _dep_sel]
        if _grupo_liga != 'Todas':
            try:
                import modo_modelo as _mmf
                quiere_sec = (_grupo_liga == 'Sólo secundarias')
                # `es_secundaria` devuelve None cuando el eje no aplica (todo
                # lo que no es fútbol). Se compara con `is` a propósito: un
                # `None` no debe colarse en «Sólo principales» por ser distinto
                # de True, que es lo que pasaría con una negación.
                salida = [p for p in salida if isinstance(p, dict)
                          and _mmf.es_secundaria(p) is quiere_sec]
            except Exception:
                pass
        return salida

    # v141 — LA SEPARACIÓN POR DÍA, QUE HASTA AHORA NO EXISTÍA.
    #
    # La pestaña decía «Todos los partidos» y la cabecera prometía «SOLO los
    # de HOY»: una de las dos mentía. Medido el 2026-08-15, la lista traía 201
    # partidos de un día y 22 de otro, todos mezclados.
    #
    # Ahora se parte por la fecha REAL del partido. Antes no se podía: el
    # tenis escribía `hoy` en todos sus registros aunque su `inicio` dijera
    # otra cosa (arreglado en `alpha_finder`), así que cualquier filtro por
    # día habría dado el mismo resultado que no filtrar.
    # v144 — EL DÍA SE PARTE EN HORA DE CDMX, NO EN UTC.
    #
    # El reparto comparaba la fecha UTC del partido, y la pantalla enseña la
    # hora de CDMX. México va 6 horas por detrás, así que **todo lo que se
    # juega entre las 18:00 y las 23:59 de México cae ya en el día siguiente
    # en UTC** y se iba a la pestaña de mañana. Es la franja de máxima
    # audiencia, o sea justo la que peor se podía equivocar.
    #
    # Medido sobre el barrido real del 2026-08-15: **9 de 196 partidos en el
    # día equivocado**, y no cualquiera —
    #
    #     Santos Laguna vs Guadalajara Chivas   19:10 CDMX de HOY → salía en MAÑANA
    #     Club Tijuana vs Cruz Azul             21:00 CDMX de HOY → salía en MAÑANA
    #     Seattle Sounders vs Vancouver         20:30 CDMX de HOY → salía en MAÑANA
    #
    # `horario.py` ya advertía de esto en su cabecera («un partido de las 01:00
    # UTC del sábado se juega el VIERNES a las 19:00 en México») y aun así
    # dejaba el reparto en UTC «donde estaba validado». Lo que estaba validado
    # era el BARRIDO, no la pestaña.
    #
    # Y esa distinción es la que se conserva: el barrido sigue razonando en UTC
    # de punta a punta (`test_un_solo_reloj` lo vigila y no se toca). Lo único
    # que pasa a CDMX es el borde de PRESENTACIÓN, que es donde vive el
    # usuario. Los campos internos `fecha` e `inicio` siguen en UTC.
    _HOY_S = _horario.fecha(pd.Timestamp.now('UTC'))
    if not _HOY_S:                      # sin base de zonas: se degrada a UTC
        _HOY_S = str(pd.Timestamp.now('UTC').tz_localize(None).date())
    _MANANA_S = str(pd.Timestamp(_HOY_S).date() + pd.Timedelta(days=1))

    def _fecha_local(p: dict) -> str:
        """
        La fecha del partido EN CDMX.

        Se calcula desde `inicio`, que es la marca de tiempo completa. `fecha`
        es sólo el día en UTC y no permite saber de qué lado de la medianoche
        mexicana cae; cuando `inicio` falta —alguna rama todavía no lo
        publica— se usa `fecha` tal cual, que es lo mejor disponible y nunca
        peor que antes.
        """
        return _horario.fecha(p.get('inicio')) or str(p.get('fecha') or '')[:10]

    def _del_dia(lista, dia: str):
        """Los del día pedido, en hora de CDMX. Sin fecha legible, fuera."""
        return [p for p in (lista or [])
                if isinstance(p, dict) and _fecha_local(p) == dia]

    # v141 — EL SEMÁFORO, EN UN SOLO SITIO.
    #
    # Vivía dentro de la pestaña de hoy. Con la pestaña de mañana harían falta
    # dos copias, y dos copias de una regla de decisión acaban divergiendo:
    # el mismo partido saldría verde en una pantalla y ámbar en la otra, que
    # es justo lo que el clasificador único existe para impedir.
    #
    # `❌ Sin precio` SE RETIRA. Medido: de 114 pronósticos de fútbol sin
    # cuota propia, 40 SÍ tenían precio en otra lista del mismo barrido, y de
    # los 74 restantes no se puede afirmar que no exista — sólo que este
    # registro no lo trae. Afirmar la ausencia era un fallo de búsqueda
    # disfrazado de veredicto. Quedan tres estados y los tres son
    # demostrables.
    PROB_PATA = 0.70
    _en_s1_g = {(str(p.get('deporte') or ''), str(p.get('partido') or ''))
                for p in (r.get('seccion1') or [])}
    _en_s2_g = {(str(p.get('deporte') or ''), str(p.get('partido') or ''))
                for p in (r.get('seccion2') or [])}

    def _ir_al_partido(p):
        """Abre la ficha del partido pulsado. Reutiliza el camino ya probado."""
        try:
            import navegacion as _nav_b
            d = _nav_b.destino_del_pick(p)
            if d:
                _nav_b.marcar(st, d)
                st.rerun()
            else:
                st.warning(f"No hay vista de competición para "
                           f"«{p.get('liga', '?')}», así que no se puede abrir "
                           f"su ficha desde aquí.")
        except Exception as e:
            st.caption(f"No se pudo abrir el partido ({type(e).__name__}).")

    def _marca_global(p):
        k = (str(p.get('deporte') or ''), str(p.get('partido') or ''))
        if k in _en_s1_g:
            return '✅ Para jugar'
        if k in _en_s2_g:
            return '🟡 Sólo pata'
        if p.get('cuota') and (p.get('prob') or 0) >= PROB_PATA:
            return '🟡 Sólo pata'
        return '· informativo'

    _s1_f = _filtra(r.get('seccion1'))
    _s2_f = _filtra(r.get('seccion2'))
    if _dep_sel != 'Todo':
        st.caption(f"Filtrando por **{_dep_sel}**. El envío a Telegram y la "
                   f"exportación siguen llevando todos los deportes.")

    # v131 — CINCO PESTAÑAS, Y EL DEPORTE COMO FILTRO.
    #
    # La pantalla era un bloque lineal de mil cuatrocientas líneas. Se corta
    # por lo que el usuario viene a decidir —qué juega— y NO por deporte: el
    # deporte no decide nada en este proyecto (ver el §0 de la bitácora), y
    # cortar por él mezclaría el tenis con probabilidad ≥ 90 %, que es el único
    # canal con p5 positivo, con los favoritos de ITF medidos en −4,9 %.
    #
    # El filtro de deporte va ARRIBA y afecta a todas las pestañas a la vez,
    # así que reordena sin esconder: la Sección 1 sigue existiendo se filtre lo
    # que se filtre.
    # v131 — LAS DOS FUNCIONES SE DEFINEN ANTES DE LAS PESTAÑAS.
    #
    # Nacieron dentro de `with _tab_ev:` porque ahí vivía su código, y
    # allí se definían DESPUÉS de la pestaña que las llama:
    # UnboundLocalError en cuanto se abría la página. Lo cazó la
    # validación de render, que es exactamente para esto.
    def _render_todos_los_partidos():
        """La tabla completa del día, en su propia pestaña."""
        # v49: TODOS LOS PRONÓSTICOS DEL DÍA — cada partido con jornada, aunque no
        # haya cuota en vivo (el modelo da su 1X2 con cuota justa). Máxima cobertura
        # de opciones sin relajar los filtros de la Capa 1.
        pronos = r.get('pronosticos') or []
        if pronos:
            st.divider()
            st.subheader(f"📋 Todos los pronósticos del día ({len(pronos)})")
            st.caption("Cobertura completa de HOY en **todos los deportes** "
                       "—fútbol, MLB, NBA, KBO y tenis—: el pronóstico del "
                       "modelo para cada partido evaluado, con su cuota "
                       "justa (1/probabilidad). Las columnas de goles y "
                       "ambos-marcan sólo aplican al fútbol; en el resto "
                       "salen vacías. Informativo: sólo la Capa 1 lleva EV "
                       "validado.")
            import pandas as _pd
            def _pct(v):
                return f"{v*100:.0f}%" if isinstance(v, (int, float)) else '—'
            # v90 — TECHO DE LA COMPETICIÓN.
            #
            # Medido sobre las 26.666 filas del ledger con cierre de Pinnacle:
            # el acierto del mercado —el mejor predictor que existe, y por
            # tanto el techo práctico— va del 42,4 % en la Serie B italiana al
            # 59,1 % en la Superliga turca. Sin esta columna, los 274
            # pronósticos se leen como si valieran lo mismo, y un 55 % en
            # Turquía y un 55 % en la Serie B son cosas muy distintas: en una
            # queda margen y en la otra se está prometiendo más de lo que nadie
            # consigue. Es estable (correlación 0,72 entre mitades del ledger),
            # a diferencia del ROI por liga, que la v38 midió no estacionario.
            try:
                import precision_ligas as _pl
            except Exception:
                _pl = None
            # v117 — LA HORA, EL ORDEN Y EL BOTÓN.
            #
            # Pedido del usuario: «no me estás poniendo a qué hora juegan esos
            # partidos, ordena esa sección de la hora más temprana a la más
            # tarde, y que tenga el botón para ir a la sección de ese partido».
            #
            # El orden era por fecha y luego por probabilidad descendente, que
            # para una lista del día es el orden equivocado: lo que decide si
            # llegas a tiempo a apostar es la hora de inicio. `inicio` ya viaja
            # en cada pronóstico desde la v89; sólo había que usarlo.
            #
            # Los partidos sin hora publicada van al final, no al principio:
            # una cadena vacía ordena antes que cualquier hora y los habría
            # puesto arriba, que es justo donde no sirven.
            def _clave_orden(x):
                _ini = str(x.get('inicio') or '')
                return (str(x.get('fecha', '')), _ini == '', _ini,
                        -(x.get('prob') or 0))

            _pronos_ord = sorted(pronos, key=_clave_orden)
            # v119 — LA LISTA YA NO ES SÓLO DE FÚTBOL, ASÍ QUE SE PUEDE FILTRAR.
            #
            # Antes sólo había fútbol y un filtro no tenía sentido. Ahora entran
            # MLB, tenis, NBA y KBO, y con treinta y pico de partidos mezclados
            # el usuario necesita poder quedarse con lo suyo.
            # v133: el multiselect de deportes que vivía aquí se retira. El
            # filtro de arriba hace lo mismo para TODAS las pestañas, y tener
            # dos sitios donde filtrar lo mismo es cómo se acaba viendo una
            # lista recortada sin saber por qué.
            _pronos_ord = _filtra(_pronos_ord)

            # v133 — EL SEMÁFORO PRESCRIPTIVO.
            #
            # La tabla decía «verde = gana el local», que describe quién juega
            # en casa y no ayuda a decidir nada. Ahora la marca dice QUÉ HACER,
            # que es la única pregunta que trae al usuario aquí:
            #
            #     ✅  hay pick en la Sección 1: es lo que se juega
            #     🟡  sólo como pata de una combinada
            #     ❌  sin precio con el que comparar, o EV negativo
            #
            # El icono nunca va solo: lleva texto al lado. Un daltónico no
            # distingue el verde del ámbar, y en el móvil a pleno sol tampoco
            # lo distingue nadie.
            def _clave_partido(p):
                return (str(p.get('deporte') or ''), str(p.get('partido') or ''))

            _en_s1 = {_clave_partido(p) for p in (r.get('seccion1') or [])}
            _en_s2 = {_clave_partido(p) for p in (r.get('seccion2') or [])}
            _apuesta_s1 = {_clave_partido(p): p for p in (r.get('seccion1') or [])}

            # v134 — LA MARCA SE LEE DEL PARTIDO, NO DE UNA LISTA INCOMPLETA.
            #
            # La primera versión decidía sólo por pertenencia a `seccion1` /
            # `seccion2`, y esas listas contienen únicamente lo que llegó a ser
            # PICK — 21 de 71 pronósticos. Medido el 2026-08-13:
            #
            #     MLB     11 pronósticos · en Sección 2: 1 · sin cuota: 0
            #     Tenis   26 pronósticos · en Sección 2: 19
            #     Fútbol  33 pronósticos · en Sección 2: 0 · sin cuota: 33
            #
            # O sea que diez partidos de MLB con precio real caían a
            # «informativo» por descarte, que es lo que el usuario vio. No
            # hacía falta un caso especial para MLB: hacía falta dejar de
            # preguntar dónde no estaba la respuesta.
            #
            # El orden importa. Primero mandan las secciones, que son el
            # veredicto del clasificador; sólo cuando el partido no llegó a
            # pick se mira lo que tiene delante. Así la marca nunca contradice
            # a la Sección 1.
            # v141: delega en `_marca_global`, definida antes de las
            # pestañas. Dos copias de una regla de decisión acaban
            # divergiendo, y entonces el mismo partido sale verde en
            # una pantalla y ámbar en la otra.
            _marca = _marca_global

            filas_p = []
            for p in _pronos_ord:
                board = p.get('board') or {}
                partes = p.get('partido', ' vs ').split(' vs ')
                home = partes[0] if partes else ''
                away = partes[-1] if len(partes) > 1 else ''
                _t = _pl.techo(p.get('clave_liga')) if _pl else None
                try:
                    _hp = _horario.partes(p.get('inicio'))
                    _hora_txt = _hp[1] if _hp else '—'
                except Exception:
                    _hora_txt = '—'
                filas_p.append({
                    'Qué hacer': _marca(p),
                    'Hora (CDMX)': _hora_txt,
                    'Fecha': p.get('fecha', ''),
                    # v119: con varios deportes en la misma lista hay que decir
                    # cuál es cada uno
                    'Deporte': p.get('deporte', 'Fútbol'),
                    'Liga': p.get('liga', ''),
                    'Techo liga': f"{_t['mercado']*100:.0f}%" if _t else '—',
                    'Partido': p.get('partido', ''),
                    '1 (local)': _pct(board.get(f'Gana {home}')),
                    'X': _pct(board.get('Empate')),
                    '2 (visita)': _pct(board.get(f'Gana {away}')),
                    '+2.5': _pct(board.get('Más de 2.5')),
                    '−2.5': _pct(board.get('Menos de 2.5')),
                    'BTTS Sí': _pct(board.get('Ambos marcan: Sí')),
                    'Mejor pronóstico': f"{p.get('apuesta','')} "
                                        f"({(p.get('prob') or 0)*100:.0f}%)",
                })
            # v133 — LA FILA SE PULSA, Y SIN DEPENDENCIAS NUEVAS.
            #
            # `st.dataframe` de Streamlit 1.61 trae `on_select` y
            # `selection_mode`, comprobado en la versión instalada. Por eso NO
            # entra `st-aggrid`: es un componente de terceros de ~1 MB de JS
            # que se rompe entre versiones de Streamlit, y en Cloud eso es un
            # riesgo de despliegue a cambio de nada.
            #
            # La barra de probabilidad va con `ProgressColumn`, que es nativa y
            # se lee de un vistazo — que era el problema de doce columnas de
            # porcentajes.
            # v137 — LA LISTA VISUAL, ANTES DE LA TABLA.
            #
            # Catorce columnas y setenta filas no se escanean: para saber quién
            # es favorito había que comparar tres cifras por fila. La barra
            # proporcional ya resolvía eso en «los seis más próximos»; aquí se
            # aplica a la lista entera, ordenada estrictamente por hora.
            #
            # Se pinta en UNA llamada, no una fila de widgets por partido: con
            # 71 partidos, un `st.button` por fila serían 71 widgets nuevos
            # —la vista entera tiene 69— y cada uno es estado que Streamlit
            # mantiene y que el smoke pulsa. Así el coste de render es plano.
            #
            # La tabla NO se borra: baja a un desplegable. Ordena, filtra y
            # busca, y tiene la fila cliqueable; eso sigue siendo útil para
            # quien quiere comparar cifras exactas.
            try:
                import render_todos_partidos as _rtp
                # v141: SÓLO los de hoy. La cabecera lo prometía y la
                # lista no lo cumplía.
                _lista_hoy = _del_dia(_pronos_ord, _HOY_S)
                _orden_hoy = _rtp.selector_orden(st, 'hoy')
                _rtp.pintar_con_boton(
                    st, _lista_hoy, _marca, _horario,
                    navegar=_ir_al_partido, clave='hoy', orden=_orden_hoy)
                st.caption(
                    f"{len(_lista_hoy)} partidos de hoy — **todos**, tengan o "
                    "no cuota y tengan o no pronóstico. "
                    "El ancho de cada tramo es la probabilidad del modelo "
                    "(verde local · gris empate · azul visitante); pasa por "
                    "encima para la cifra exacta. **La etiqueta de la derecha "
                    "es la que dice qué hacer.**")
            except Exception as _e_rtp:
                st.caption(f"Lista visual no disponible ahora "
                           f"({type(_e_rtp).__name__}).")

            _df_p = _pd.DataFrame(filas_p)
            _exp_tabla = st.expander(
                "🔢 Ver la tabla con todas las cifras (ordenable y "
                "cliqueable)", expanded=False)
            with _exp_tabla:
              _sel_tabla = st.dataframe(
                _df_p, hide_index=True, width='stretch',
                key='tabla_pronosticos',
                on_select='rerun', selection_mode='single-row',
                column_config={
                    'Qué hacer': st.column_config.TextColumn(
                        'Qué hacer', width='small',
                        help='✅ hay pick en la Sección 1 · 🟡 sólo como pata '
                             'de una combinada · ❌ sin precio con el que '
                             'comparar'),
                })
            try:
                _filas_sel = list(_sel_tabla.selection.rows)
            except Exception:
                _filas_sel = []
            if _filas_sel and _filas_sel[0] < len(_pronos_ord):
                _pick = _pronos_ord[_filas_sel[0]]
                _k = _clave_partido(_pick)
                with st.container(border=True):
                    st.markdown(f"**{_pick.get('partido','?')}** · "
                                f"{_pick.get('liga','')} · "
                                f"{_pick.get('deporte','')}")
                    _s1p = _apuesta_s1.get(_k)
                    if _s1p:
                        st.success(
                            f"✅ **{_s1p.get('apuesta','')}**"
                            + (f" @ {_s1p['cuota']}" if _s1p.get('cuota') else '')
                            + f" · {(_s1p.get('prob') or 0)*100:.0f} % — "
                            + str(_s1p.get('motivo', ''))[:180])
                    elif _k in _en_s2:
                        st.warning(
                            "🟡 Alta probabilidad, precio insuficiente. **No "
                            "lo juegues solo**: sirve como pata de una "
                            "combinada que parta de la Sección 1.")
                    else:
                        st.caption(
                            "Sin pick accionable: el modelo lo pronostica, "
                            "pero no hay ventaja de precio con la que "
                            "sostener una apuesta.")
                    try:
                        import navegacion as _nav_s
                        _dest_s = _nav_s.destino_del_pick(_pick)
                    except Exception:
                        _dest_s = None
                    if _dest_s and st.button(
                            "Ver el análisis completo de este partido →",
                            key='tabla_ir', type='primary', width='stretch'):
                        _nav_s.marcar(st, _dest_s)
                        st.rerun()
            # el botón por partido va DEBAJO de la tabla: Streamlit no permite
            # meter un widget dentro de una celda, y una fila de botones sueltos
            # se pierde. Un desplegable con el mismo orden cronológico y un
            # solo botón hace el mismo trabajo sin ensuciar la pantalla.
            _dest_p = {}
            for p in _pronos_ord:
                try:
                    import navegacion as _nav_p
                    _d = _nav_p.destino_del_pick(p)
                except Exception:
                    _d = None
                if not _d:
                    continue
                _hp = None
                try:
                    _hp = _horario.partes(p.get('inicio'))
                except Exception:
                    pass
                _et = (f"{_hp[1]} · " if _hp else '') + \
                      f"{p.get('partido','?')} — {p.get('liga','')}"
                _dest_p[_et] = _d
            # v118 — LOS PRÓXIMOS, EN VISUAL Y NO EN TABLA.
            #
            # La tabla de arriba es la referencia completa, pero doce columnas
            # de porcentajes no se leen: hay que comparar mentalmente 1, X y 2
            # fila por fila. Los seis primeros —que son los que están a punto
            # de empezar— salen además como barra proporcional, donde cada
            # tramo ocupa lo que vale y el favorito se ve sin leer un número.
            if _estilo is not None and _pronos_ord:
                st.markdown("**⏱️ Los seis más próximos, de un vistazo**")
                for p in _pronos_ord[:6]:
                    _b = p.get('board') or {}
                    _pt = p.get('partido', ' vs ').split(' vs ')
                    _h = _pt[0] if _pt else ''
                    _a = _pt[-1] if len(_pt) > 1 else ''
                    _pl = _b.get(f'Gana {_h}')
                    _px = _b.get('Empate')
                    _pv = _b.get(f'Gana {_a}')
                    if None in (_pl, _px, _pv):
                        continue
                    try:
                        _hp2 = _horario.partes(p.get('inicio'))
                        _hh = _hp2[1] if _hp2 else '—'
                    except Exception:
                        _hh = '—'
                    with st.container(border=True):
                        st.markdown(
                            f"**{_hh}** · {p.get('partido','?')}  \n"
                            f"<small>{p.get('liga','')}</small>"
                            + _estilo.barra_1x2(_pl, _px, _pv, _h, _a),
                            unsafe_allow_html=True)
                # v133: la barra sigue siendo descriptiva —es un reparto de
                # probabilidad, no una recomendación— pero se dice que NO es
                # la señal de qué jugar, para que no compita con el semáforo
                # de la columna «Qué hacer».
                st.caption("El ancho de cada tramo es la probabilidad del "
                           "modelo (local · empate · visitante). **Esto no es "
                           "la recomendación**: para saber qué jugar, mira la "
                           "columna «Qué hacer» de la tabla.")

            if _dest_p:
                cbp1, cbp2 = st.columns([3, 1])
                _sel_p = cbp1.selectbox(
                    "📊 Ver las estadísticas de un partido de la lista",
                    list(_dest_p.keys()), key='prono_ir_sel',
                    help="Abre la vista de su competición con el partido "
                         "cargado: historial, forma, todos los mercados y el "
                         "constructor de combinadas.")
                if cbp2.button("Ir al partido →", key='prono_ir_btn',
                               width='stretch', type='primary'):
                    import navegacion as _nav_p2
                    _nav_p2.marcar(st, _dest_p[_sel_p])
                    st.rerun()
            st.caption("**Techo liga** = cuánto acierta ahí la mejor casa de "
                       "apuestas del mundo; es el máximo que logra nadie. Va "
                       "del 42 % en la Serie B italiana al 59 % en Turquía. Si "
                       "un pronóstico promete mucho más que ese techo, "
                       "desconfía.")
            st.caption("1/X/2 = victoria local / empate / visitante · +2.5/−2.5 = "
                       "más/menos de 2.5 goles · BTTS = ambos marcan. Todas con la "
                       "probabilidad del modelo (cuota justa = 1/prob).")

    def _render_estado_sistema():
        """Diagnóstico, auditoría y simuladores. Contexto, no decisión."""
        # v47: PARLAY DEL DÍA DE TENIS — combinación contundente de los mercados
        # derivados más seguros (uno por partido). El usuario pidió una apuesta de
        # tenis "contundente" para parlay a partir de la plantilla de mercados.
        tp = r.get('tenis_parlay') or {}
        if tp.get('patas'):
            st.divider()
            st.subheader("🎾 Parlay del Día — Tenis")
            st.caption(tp.get('nota', ''))
            cpa, cpb = st.columns(2)
            cpa.metric("Cuota combinada", tp['cuota_combinada'])
            cpb.metric("Prob. conjunta", f"{tp['prob_conjunta']*100:.0f}%")
            import pandas as _pd
            st.dataframe(_pd.DataFrame([
                {'Circuito': p['circuito'], 'Partido': p['partido'],
                 'Mercado': p['mercado'], 'Prob': f"{p['prob']*100:.0f}%",
                 'Cuota justa': p['cuota_justa']} for p in tp['patas']],
            ), hide_index=True, width='stretch')

        # v89 — SE ELIMINA el segundo botón «Enviar a Telegram» que vivía aquí
        # en un expander: llamaba a `bot_telegram.construir_mensaje()` SIN
        # pasarle el barrido ya calculado, que es exactamente el bug que
        # tumbaba la app en la v88 (segundo barrido de 1,3 GB encima del que ya
        # estaba en memoria). La v88 arregló el botón de arriba y este
        # duplicado se quedó con el código viejo. El de arriba hace lo mismo y
        # lo hace bien.

        # v43 (§4.1): Auditoría de modelos — matriz de rendimiento por liga
        st.divider()
        with st.expander("📊 Auditoría de Modelos (transparencia total)"):
            st.caption("Rendimiento REAL de cada liga contra su mercado de cierre "
                       "(pool 1X2 crudo, ANTES del filtro de selección validado). "
                       "🟢 bate al mercado y es rentable · 🟡 marginal · 🔴 no bate.")
            try:
                import model_audit
                aud = model_audit.cargar() or model_audit.auditar()
                ligas = aud.get('ligas', [])
                if ligas:
                    st.caption(f"**{aud.get('ligas_rentables')}/{aud.get('n_ligas')} "
                               "ligas rentables en el pool crudo.**")
                    import pandas as _pd
                    dfa = _pd.DataFrame([{
                        '': l['semaforo'], 'Liga': l['nombre'], 'n': l['n'],
                        'ROI %': l['roi_pct'], 'Precisión': l['precision'],
                        'CLV %': l['clv_pct'], 'En Capa 1': '✅' if l['disponible'] else '—',
                    } for l in ligas])
                    st.dataframe(dfa, hide_index=True, width='stretch')
            except Exception as e:
                st.caption(f"Auditoría no disponible ({type(e).__name__}).")

        # v38: MOTOR DE RENTABILIDAD — CLV (métrica rey) + banda validada + mapa
        st.divider()
        with st.expander("📉 Rentabilidad y calidad del precio"):
            st.caption("El **CLV** (Closing Line Value) mide si apostamos a MEJOR "
                       "precio que el cierre del mercado — el único predictor "
                       "robusto del beneficio a largo plazo.")
            try:
                import clv_tracker
                import edge_engine
                clv = clv_tracker.clv_historico()
                if clv.get('n'):
                    cc1, cc2, cc3 = st.columns(3)
                    cc1.metric("CLV medio", f"{clv['clv_medio_pct']:+.2f} %",
                               help="Negativo = apostamos peor que el cierre "
                                    "(causa estructural de pérdidas).")
                    cc2.metric("Batimos el cierre", f"{clv['pct_batimos_cierre']:.0f} %")
                    cc3.metric("ROI si batimos vs no",
                               f"{clv.get('roi_cuando_batimos','?')} / "
                               f"{clv.get('roi_cuando_no','?')} %")
                    st.caption(clv['interpretacion'])
                lo, hi = edge_engine.banda_rentable()
                st.markdown(f"**🎯 Franja en la que el sistema gana dinero:** EV "
                            f"{lo*100:.0f}–{hi*100:.0f} % · prob ≥ "
                            f"{edge_engine.piso_prob()*100:.0f} % · convicción "
                            f"prob×EV ≥ {edge_engine.conviccion_min():.3f}.")
                _panel_calibracion_v75(st)
                ci = edge_engine._mapa().get('ci_bootstrap_seleccion') or {}
                if ci.get('n'):
                    cb1, cb2, cb3 = st.columns(3)
                    cb1.metric("ROI medio (backtest)", f"{ci['roi_medio']:+.1f} %",
                               help=f"{ci['n']} apuestas históricas de la selección.")
                    cb2.metric("ROI p5 (bootstrap)", f"{ci['roi_p5']:+.1f} %",
                               help="Peor ROI plausible al 95 %. Positivo = el edge "
                                    "no es casualidad (robustez, no una ventana afortunada).")
                    cb3.metric("ROI p95", f"{ci['roi_p95']:+.1f} %")
                m = edge_engine._mapa()
                ligas = m.get('ligas', {})
                if ligas:
                    st.caption("Mapa de rentabilidad por liga (DIAGNÓSTICO — no "
                               "filtro; la rentabilidad por liga no es estable):")
                    import pandas as _pd
                    dfm = _pd.DataFrame([{'liga': k, 'n': v['n'], 'ROI %': v['roi'],
                                          'acierto': v['hit']}
                                         for k, v in ligas.items()])
                    st.dataframe(dfm.sort_values('ROI %', ascending=False),
                                 hide_index=True, width='stretch')
            except Exception as e:
                st.caption(f"Métricas de rentabilidad no disponibles ({type(e).__name__}).")

        # v41 (§3.1-§3.2): Mejores Patas + constructor integrado de parlays
        patas = r.get('mejores_patas') or []
        if patas:
            st.divider()
            st.subheader("🧩 Mejores Patas para Parlay")
            st.caption("Picks de alta probabilidad (≥ 55 %) para COMBINAR en "
                       "parlays seguros — no son apuestas simples. ⚽ = BTTS.")
            opciones = {}
            for i, p in enumerate(patas[:20]):
                icono = '⚽ ' if p.get('btts') else ''
                cuota = p.get('cuota')
                precio = (f"@ {cuota} · EV {(p.get('ev') or 0)*100:+.0f} %" if cuota
                          else f"cuota justa {p.get('cuota_justa','?')}")
                etq = (f"{icono}{p.get('partido','?')} — {p.get('apuesta','?')} "
                       f"(prob {(p.get('prob') or 0)*100:.0f} % {precio})")
                opciones[etq] = p
            elegidas_lbl = st.multiselect(
                "Elige 2–4 patas y púlsalo abajo para combinar:",
                list(opciones.keys()), max_selections=6, key='patas_sel')
            if st.button("🧩 Calcular Parlay", key='patas_btn', type="primary") \
                    and len(elegidas_lbl) >= 2:
                from match_parlay import combinar_patas
                res = combinar_patas([opciones[l] for l in elegidas_lbl],
                                     bankroll=float(st.session_state.get('bankroll', 0) or 0))
                if 'error' in res:
                    st.warning(res['error'])
                else:
                    for a in res['avisos']:
                        st.warning(a)
                    pm1, pm2, pm3, pm4 = st.columns(4)
                    pm1.metric("🎯 PFP", f"{res['pfp']*100:.1f} %", res['riesgo'])
                    pm2.metric("Cuota combinada", f"{res['cuota_combinada']:.2f}")
                    pm3.metric("EV", f"{res['ev_parlay']:+.2f}")
                    pm4.metric("Patas", res['n_patas'])
                    if res.get('stake', {}).get('stake', 0) > 0:
                        st.info(f"💵 Stake sugerido (¼ Kelly): "
                                f"**{res['stake']['stake']:.2f} u** "
                                f"({res['stake']['pct']*100:.1f} % del bankroll).")

        # v37 (§7): informe mensual de rendimiento
        st.divider()
        with st.expander("📊 Informe Mensual de rendimiento"):
            import resumen_mensual as rm
            meses = rm.meses_disponibles()
            if not meses:
                st.info("Aún no hay picks liquidados. El informe se llena a medida "
                        "que los partidos publicados terminan y se registran sus "
                        "resultados (rendimiento_real.db).")
            else:
                mes_sel = st.selectbox("Mes", meses, key='rm_mes')
                inf = rm.informe_mes(mes_sel)
                if inf.get('n'):
                    m1, m2, m3, m4 = st.columns(4)
                    m1.metric("Picks liquidados", inf['n'])
                    m2.metric("Tasa de acierto", f"{inf['tasa_acierto']*100:.1f} %")
                    m3.metric("ROI real", f"{inf['roi_pct']:+.1f} %",
                              help="Con la cuota registrada al publicar el pick.")
                    m4.metric("EV prometido",
                              f"{(inf.get('ev_medio_prometido') or 0)*100:+.1f} %",
                              help="Compara el EV que prometía el modelo con el ROI real.")
                    serie = rm.serie_mensual()
                    if not serie.empty:
                        st.line_chart(serie.set_index('mes')[['roi_pct']],
                                      height=200)
                    if inf.get('por_deporte'):
                        st.caption("Por deporte:")
                        st.dataframe(pd.DataFrame(inf['por_deporte']),
                                     hide_index=True, width='stretch')
                else:
                    st.info(inf.get('aviso', 'Sin datos.'))

        # v91 — LOS PARTIDOS SIN MODELO YA TIENEN TARJETA CON CUOTA.
        #
        # Antes esto era una lista de 22 nombres en crudo («Duncan Chan vs
        # Thiago Agustin Tirante», …) que no servía para nada: son partidos de
        # challenger/ITF con precio real en las casas cuyos jugadores no están
        # en el catálogo del modelo. Ahora cada uno sale con su cuota y la
        # probabilidad implícita del precio, y la etiqueta dice que ahí no hay
        # predicción propia.
        _sm = r.get('sin_modelo') or []
        if _sm:
            st.divider()
            st.subheader(f"🏷️ Con cuota, sin modelo propio ({len(_sm)})")
            st.info("Partidos con precio real de las casas cuyos jugadores no "
                    "están en el catálogo del modelo (típico en challengers e "
                    "ITF). La probabilidad que se muestra es **la implícita "
                    "del precio**, no una predicción nuestra: sirve para "
                    "ver el mercado, no lleva EV ni entra en ninguna capa.")
            _tarjetas(_sm, "", agrupar_dia=False)
        elif r.get('no_enlazados'):
            with st.expander(f"ℹ️ {len(r['no_enlazados'])} partidos sin modelo "
                             "propio y sin cuota utilizable"):
                st.caption("No se descartan en silencio: ni el nombre cruzó "
                           "con el catálogo ni hay precio con el que armar "
                           "una tarjeta.")
                st.write(r['no_enlazados'])

        # v32 (§3): EV extremo segregado, oculto por defecto
        extremo = r.get('ev_extremo') or []
        if extremo:
            st.divider()
            if st.checkbox(f"⚠️ Mostrar {len(extremo)} picks de EV extremo "
                           "(alta incertidumbre)", value=False, key='ev_extremo_tog'):
                st.warning("Estos picks tienen un EV inusualmente alto (>+15 %). "
                           "En el histórico, ese tramo acertó **15 pp por debajo** "
                           "de lo que el modelo prometía y su ROI fue 12 pp peor: "
                           "suele delatar información que el modelo no ve "
                           "(lesiones, rotaciones). Apuesta con precaución.")
                _tarjetas(extremo, "")

        # v32 (§2): Reto Escalera (interés compuesto)
        st.divider()
        with st.expander("🪜 Reto Escalera (interés compuesto)"):
            import reto_escalera as re_esc
            c1, c2 = st.columns(2)
            cap0 = c1.number_input("Capital inicial", 10.0, 1e6, 100.0, step=10.0,
                                   key='esc_cap')
            frac = c2.slider("Porcentaje del capital por día", 10, 100, 100,
                             key='esc_frac',
                             help="100 % = all-in: un solo fallo liquida la banca.") / 100
            esc = re_esc.construir((r.get('capa1') or []) + (r.get('capa2') or []),
                                   capital=cap0, fraccion=frac)
            if not esc.get('picks'):
                st.info(esc.get('aviso'))
            else:
                sim = esc['simulacion']
                st.warning(esc['aviso'])
                m1, m2, m3 = st.columns(3)
                m1.metric("Prob. de completar hoy", f"{esc['prob_conjunta']*100:.1f} %")
                m2.metric("Cuota combinada", f"{esc['cuota_combinada']:.3f}",
                          f"+{esc['retorno_por_dia_pct']:.1f} % por día")
                m3.metric("Prob. de ruina (10 días)",
                          f"{sim['prob_ruina_10d']*100:.0f} %")
                st.dataframe(pd.DataFrame([{
                    'Deporte': p.get('deporte', 'Fútbol'), 'Partido': p['partido'],
                    'Apuesta': p['apuesta'], 'Prob.': f"{p['prob']*100:.0f} %",
                    'Cuota': p.get('cuota')} for p in esc['picks']]),
                    width='stretch', hide_index=True)
                st.caption(f"Monte Carlo (10.000 simulaciones): racha media "
                           f"{sim['dias_racha_medios']:.1f} días · ruina a 20 días "
                           f"{sim['prob_ruina_20d']*100:.0f} % · capital mediano a "
                           f"30 días {sim['capital_mediano_30d']:,.0f}.")

        # v34 (§6): Valor en Vivo — SIN consumir API (solo snapshots guardados)
        with st.expander("📡 Valor en Vivo (sin gastar API)"):
            st.caption("Evolución del EV a partir de los snapshots de cuotas ya "
                       "capturados para el RLM. No hace ni una petición nueva.")

            @st.cache_data(ttl=1800, show_spinner="Leyendo snapshots…")
            def _vivo():
                import valor_en_vivo
                return valor_en_vivo.valor_en_vivo()

            rv = _vivo()
            if rv.get('aviso'):
                st.info(rv['aviso'])
            if rv.get('filas'):
                st.caption(f"{rv.get('n_partidos', 0)} partidos con snapshots · "
                           "⚠️ ojo: un valor esperado por encima de +15 % suele "
                           "significar que la probabilidad está mal calculada, "
                           "no que haya una ganga.")
                st.dataframe(pd.DataFrame(rv['filas'])[
                    ['partido', 'liga', 'mercado', 'cuota_inicial', 'cuota_actual',
                     'ev_pct', 'tendencia', 'snapshots']],
                    width='stretch', hide_index=True)

        # v32 (§6): rendimiento REAL de lo recomendado
        # v92: el circuito por fin se cierra — `liquidador.py` resuelve los
        # picks contra el marcador de ESPN. Hasta ahora esto siempre salía
        # vacío porque nadie llamaba a `liquidar()`.
        with st.expander("📊 Rendimiento real de las Apuestas del Día"):
            import rendimiento_real as rreal
            res7, res30 = rreal.resumen(7), rreal.resumen(30)
            if res30.get('n'):
                c1, c2, c3 = st.columns(3)
                c1.metric("Aciertos (30 d)",
                          f"{res30['tasa_acierto']*100:.0f} %",
                          f"prometido {res30['prob_media_prometida']*100:.0f} %",
                          help="Si el acierto real va muy por debajo de lo "
                               "prometido, el modelo sobreconfía — es la misma "
                               "brecha que la pestaña de Máxima Confianza "
                               "corrige por banda.")
                c2.metric("ROI real (30 d)",
                          f"{res30['roi_pct']:+.1f} %"
                          if res30.get('roi_pct') is not None else "—",
                          f"sobre {res30.get('n_con_cuota', 0)} con cuota real",
                          help="Sólo cuenta los picks que llevaban precio: una "
                               "apuesta sin cuota no tiene retorno que medir.")
                c3.metric("Picks (7 d / 30 d)", f"{res7.get('n',0)} / {res30['n']}",
                          f"{res30.get('pendientes', 0)} sin resolver")
                if res30.get('n_sin_cuota'):
                    st.caption(
                        f"De los {res30['n']} liquidados, **{res30['n_sin_cuota']} "
                        f"no llevaban cuota** (Capa 2): de esos sólo se puede "
                        f"medir el acierto, "
                        f"**{(res30.get('acierto_sin_cuota') or 0)*100:.0f} %**, "
                        f"no el ROI.")
                serie = rreal.serie_diaria(30)
                if not serie.empty:
                    st.line_chart(serie.set_index('fecha')['roi_acumulado_pct'])
            else:
                st.info(res30.get('aviso', 'Sin historial todavía.')
                        + " Los picks se registran automáticamente cada día y "
                          "se liquidan contra el marcador cuando el partido "
                          "termina.")

        # v92 — PRODUCCIÓN CONTRA BACKTEST, por canal de valor.
        with st.expander("🎯 ¿Se está cobrando el edge? (producción vs backtest)"):
            st.caption("El backtest es una promesa; esto es la factura. Cada "
                       "canal de valor se compara con el peor caso plausible "
                       "(p5) que midió su validación fuera de muestra.")
            try:
                import monitor_canales as _mc
                _rc = _mc.rendimiento(30)
                if _rc.get('aviso'):
                    st.info(_rc['aviso'])
                for _f in _rc.get('canales', []):
                    with st.container(border=True):
                        st.markdown(f"**{_f['nombre']}**"
                                    + (f" · {', '.join(_f['deportes'])}"
                                       if _f.get('deportes') else ''))
                        _v = _mc.veredicto(_f)
                        (st.success if _f['estado'] == 'ok' else
                         st.error if _f['estado'] == 'bajo' else st.info)(_v)
                        if _f.get('ref_fuente'):
                            st.caption(f"Referencia: ROI {_f['ref_roi']:+.2f} % "
                                       f"· p5 {_f['ref_p5']:+.2f} % "
                                       f"({_f['ref_fuente']})")
            except Exception as e:
                st.caption(f"Monitor no disponible ({type(e).__name__}).")

            # --- v101: qué ha aprendido el sistema de sus propios fallos ----
            try:
                import json as _json
                import os as _os
                st.markdown("**🧠 Lo que el sistema ha aprendido de sus "
                            "resultados**")
                if not _os.path.exists('calibracion_adaptativa.json'):
                    st.caption("Todavía no hay calibración adaptativa: se "
                               "genera con la recalibración semanal.")
                else:
                    _ad = _json.load(open('calibracion_adaptativa.json',
                                          encoding='utf-8'))
                    _mapa = _ad.get('mapa') or {}
                    _g = _mapa.get('global') or {}
                    st.caption(
                        f"Aprendido de {_g.get('n', 0)} picks liquidados · "
                        f"peso propio {_g.get('peso_propio', 0):.0%} (el resto "
                        f"lo pone el histórico) · corrección topada a "
                        f"±{_ad.get('tope_ajuste', 0):.0%}. "
                        "No cambia QUÉ se apuesta: sólo con cuánta seguridad "
                        "se dice.")
                    import aprendizaje_continuo as _ac
                    _filas = []
                    for _k, _n in sorted(_mapa.items(),
                                         key=lambda kv: -kv[1].get('n', 0))[:6]:
                        _filas.append({
                            'segmento': _k, 'n': _n.get('n'),
                            **{f'{int(_p*100)} %':
                               f"{_ac.aplicar(_p, {'global': _n}):.0%}"
                               for _p in (0.55, 0.65, 0.75)}})
                    if _filas:
                        st.dataframe(_filas, hide_index=True,
                                     width='stretch')
                        st.caption("Cada fila: lo que el modelo dice (columnas) "
                                   "y lo que el sistema publica tras corregirse "
                                   "con lo que de verdad ocurrió.")
                    # v102 — en QUÉ deportes y mercados se autoriza, y en
                    # cuáles no. Lo decide el propio sistema reevaluando su A/B
                    # en cada recalibración, así que aquí se enseña tal cual:
                    # un mercado rechazado no es un fallo, es el listón haciendo
                    # su trabajo.
                    _val = _ad.get('validacion') or {}
                    if _val:
                        st.markdown("**Dónde se autoriza a corregir "
                                    "(lo decide su propio A/B)**")
                        _rows = []
                        for _k, _v in sorted(
                                _val.items(),
                                key=lambda kv: -(kv[1].get('n') or 0)):
                            _rows.append({
                                'deporte y mercado': _k.replace('|', ' · '),
                                'n': _v.get('n'),
                                'brecha antes': (f"{_v['brecha_cruda']:.3f}"
                                                 if 'brecha_cruda' in _v else '—'),
                                'brecha después': (f"{_v['brecha_ajustada']:.3f}"
                                                   if 'brecha_ajustada' in _v
                                                   else '—'),
                                'veredicto': _v.get('veredicto')})
                        st.dataframe(_rows, hide_index=True,
                                     width='stretch')
                        st.caption("RECHAZAR significa que ahí el modelo ya "
                                   "está bien calibrado y corregirlo sólo "
                                   "añadiría ruido. Un deporte entra solo el "
                                   "día que sus datos pasen el listón.")
                # y el diagnóstico que lo motiva
                if _os.path.exists('autopsia.json'):
                    _au = (_json.load(open('autopsia.json', encoding='utf-8'))
                           .get('produccion') or {})
                    _lec = [f for f in (_au.get('filas') or []) if f['leccion']]
                    if _lec:
                        st.caption("Segmentos donde la brecha es "
                                   "estadísticamente firme: " +
                                   " · ".join(f"{f['corte']}={f['segmento']} "
                                              f"({f['brecha']:+.0%}, n={f['n']})"
                                              for f in _lec[:3]))
            except Exception as e:
                st.caption(f"Aprendizaje no disponible ({type(e).__name__}).")

        _tarjetas(r.get('candidatos'), "Candidatos con EV positivo"
                  if ES_PRO else "Otras oportunidades con Ventaja Matemática 📈")
        if r.get('deportes_cubiertos'):
            st.caption(f"🌐 Deportes cubiertos hoy: "
                       f"{', '.join(r['deportes_cubiertos'])}.")
        from bankroll_manager import AVISO_JUEGO_RESPONSABLE
        st.caption(AVISO_JUEGO_RESPONSABLE)

        # v88 — El arbitraje de mercado cruzado se retira con The Odds API.
        # `cross_arbitrage` colgaba entera de esa API (clave, presupuesto de
        # créditos y endpoint de eventos), que lleva devolviendo 401. El botón
        # decía «usa ~5 créditos de API» y ya no había créditos que usar: sólo
        # podía fallar. Lo que hacía —valorar mercados derivados con la matriz
        # del motor— sigue disponible en la ficha de cada partido.

        # ---- 📈 Simulador Montecarlo (v26 §4.1) -------------------------------
        st.divider()
        st.subheader("📈 Simulador de bankroll (Montecarlo)")
        st.caption("1,000 futuros posibles con el rendimiento REAL del modelo: "
                   "ve la varianza antes de arriesgar un peso.")
        import montecarlo_sim as mc
        c1, c2, c3, c4 = st.columns(4)
        bank0 = c1.number_input("Bankroll inicial", 50.0, 1e6, 1000.0, step=50.0,
                                key='mc_bank')
        liga_mc = c2.selectbox("Rendimiento de", list(NOMBRES_LIGAS.keys()),
                               format_func=lambda k: NOMBRES_LIGAS[k], key='mc_liga')
        estrategia = c3.selectbox(
            "Estrategia", list(mc.ESTRATEGIAS.keys()),
            format_func=lambda k: mc.ESTRATEGIAS[k][0], key='mc_estr')
        n_bets = c4.slider("Apuestas a simular", 20, 500, 100, key='mc_n')
        par = mc.parametros_de_liga(liga_mc)
        st.caption(f"Parámetros: win-rate {par['win_rate']*100:.1f} %, cuota media "
                   f"{par['odds_mean']} ± {par['odds_std']} — fuente: {par['fuente']}.")
        if st.button("🎲 Simular 1,000 trayectorias", key='mc_btn'):
            res = mc.simular_bankroll(bank0, par['win_rate'], par['odds_mean'],
                                      par['odds_std'], n_bets, estrategia)
            x = list(range(n_bets + 1))
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=x, y=res['p95'], name='Percentil 95',
                                     line=dict(width=1), mode='lines'))
            fig.add_trace(go.Scatter(x=x, y=res['p5'], name='Percentil 5',
                                     fill='tonexty', line=dict(width=1), mode='lines'))
            fig.add_trace(go.Scatter(x=x, y=res['p50'], name='Mediana',
                                     line=dict(width=3), mode='lines'))
            fig.update_layout(height=380, margin=dict(l=10, r=10, t=30, b=10),
                              xaxis_title='Apuesta nº', yaxis_title='Bankroll')
            st.plotly_chart(fig, width='stretch')
            m1, m2, m3 = st.columns(3)
            m1.metric("Bankroll final mediano", f"{res['final_mediano']:,.0f}")
            m2.metric("Rango 5-95 %", f"{res['final_p5']:,.0f} – {res['final_p95']:,.0f}")
            m3.metric("Probabilidad de ruina (<10 %)", f"{res['prob_ruina']*100:.1f} %")
            st.caption("⚠️ Educativo: incluso con ventaja real, la varianza puede "
                       "producir rachas largas de pérdida — por eso el proyecto "
                       "usa ¼ Kelly con tope del 5 % y nunca all-in. "
                       + AVISO_JUEGO_RESPONSABLE)


    # v133 — «Todos los partidos» sube a segunda posición.
    #
    # «Para jugar» estará en cero muchos días, y está bien que lo esté: es el
    # sistema no forzando apuestas. Pero una primera pantalla vacía sin nada
    # útil al lado invita a buscar valor donde no lo hay, que es exactamente
    # lo que este proyecto existe para evitar. Con la vista general a un clic,
    # el día sin picks sigue teniendo dónde mirar.
    # v141: los contadores cuentan HOY. Un rótulo que suma los dos días y una
    # lista que enseña uno solo es lo que hacía que 227 y 148 no cuadraran.
    _pron_f = _filtra(r.get('pronosticos'))
    _pron_hoy = _del_dia(_pron_f, _HOY_S)
    _pron_man = _del_dia(_pron_f, _MANANA_S)
    _s1_hoy = _del_dia(_s1_f, _HOY_S) or _s1_f
    _s2_hoy = _del_dia(_s2_f, _HOY_S) or _s2_f
    # v152 — MODO MODELO PRIMERO, MODO VALOR SEGUNDO.
    #
    # Es una decisión del usuario, pedida dos veces y con estas palabras: «no
    # quiero ver EV alto en equipos débiles; quiero que la app me diga que este
    # equipo está jugando mejor». La pantalla que ordena por probabilidad del
    # modelo pasa a ser la primera.
    #
    # LO QUE NO CAMBIA: cuál es el criterio con percentil 5 positivo. Sigue
    # siendo la ventaja de precio, sigue viviendo en la pestaña de al lado, y
    # el Modo Modelo lleva esa advertencia DENTRO —no debajo— porque un orden
    # por probabilidad del modelo está medido en −4,66 % a −6,52 % de ROI.
    # Cambiar el orden de las pestañas es cambiar lo que se mira primero; no es
    # cambiar lo que la medición dice.
    # v154 — DE SIETE PESTAÑAS A CUATRO.
    #
    # Eran siete y tres enseñaban lo mismo con otro orden: «Modo Modelo»,
    # «Partidos de hoy» y «Sólo como pata» recorrían la misma lista del día.
    # El encargo fue «una sola vista de apuestas, sin pestañas complicadas», y
    # eso es lo que queda:
    #
    #     ⚽ Apuestas de hoy   la vista de tarjetas, con TODO lo de hoy dentro
    #     🗓️ Mañana            los que aún no se juegan
    #     🧩 Combinadas
    #     ⚙️ Estado
    #
    # LO QUE NO SE PIERDE, Y ES LA PARTE DELICADA: la ventaja de precio es el
    # único criterio con percentil 5 positivo medido en todo el proyecto. No
    # puede desaparecer porque la pantalla se simplifique, así que baja a un
    # desplegable DENTRO de la vista principal, abierto cuando hay algo que
    # enseñar. Cambia dónde está, no si está.
    # v177 — LAS PESTAÑAS DEJAN DE SER `st.tabs`, Y ES UN ARREGLO, NO UN
    # CAMBIO DE ESTILO.
    #
    # EL DEFECTO, con las palabras del usuario: «al cambiar el filtro
    # Ordenar por en la pestaña de mañana, la app te regresa a partidos de
    # hoy». Y no era el filtro: **`st.tabs` no tiene estado de servidor**.
    # La pestaña abierta vive en el navegador, y cualquier interacción
    # rehace el script y la devuelve a la primera. Da igual lo persistente
    # que sea el valor del filtro —la v176 lo dejó guardado en disco— si el
    # usuario acaba mirando otra lista.
    #
    # `segmented_control` sí tiene clave, así que la elección sobrevive a
    # la recarga igual que los filtros, y por el mismo camino:
    # `preferencias_usuario` la siembra al arrancar.
    #
    # EL SUMIDERO, que es la parte que no se ve. Los cuatro cuerpos siguen
    # ejecutándose —con `st.tabs` también se ejecutaban los cuatro, así que
    # no hay coste nuevo— y al final se BORRA el contenido de los tres que
    # no se han elegido. Se hace así, y no con un `if` alrededor de cada
    # bloque, porque la vista de hoy tiene su cuerpo repartido en seis
    # sitios distintos de esta función: envolverlos todos habría sido
    # reindentar trescientas líneas para arreglar una pestaña.
    _VISTAS = [
        ('hoy', f"⚽ Hoy ({len(_pron_hoy)})"),
        ('manana', f"🗓️ Mañana ({len(_pron_man)})"),
        ('combi', f"🧩 Combinadas ({len(r.get('combinadas') or [])})"),
        ('estado', "⚙️ Estado"),
    ]
    # LAS OPCIONES SON CLAVES, NO RÓTULOS, y eso no es un detalle de
    # estilo. El rótulo lleva dentro el número de partidos —«Hoy (247)»— y
    # eso es lo que se guardaría en la preferencia: mañana habría 231 y el
    # valor guardado dejaría de ser una opción válida, así que la vista se
    # perdería justo al recargar, que es lo que esto viene a arreglar. Con
    # `format_func` el usuario ve el rótulo y el estado guarda `hoy`.
    _ROTULO = {k: e for k, e in _VISTAS}
    _claves = [k for k, _ in _VISTAS]
    try:
        import preferencias_usuario as _prefv
        _prefv.recordar(st, '_vista_principal', _claves, 'hoy')
    except Exception:
        _prefv = None
    _sel_vista = st.segmented_control(
        'Vista', _claves, key='_vista_principal',
        format_func=lambda k: _ROTULO.get(k, k),
        label_visibility='collapsed',
        help='La vista elegida se recuerda: cambiar un filtro ya no te '
             'devuelve a «Hoy».')
    # `segmented_control` admite deselección: si el usuario pulsa la que ya
    # estaba, devuelve None y la pantalla se quedaría en blanco.
    _vista = _sel_vista if _sel_vista in _ROTULO else 'hoy'
    if _prefv is not None:
        _prefv.guardar('_vista_principal', _vista)
    _slots = {k: st.empty() for k, _ in _VISTAS}
    _tab_hoy = _slots['hoy'].container()
    _tab_manana = _slots['manana'].container()
    _tab_combi = _slots['combi'].container()
    _tab_estado = _slots['estado'].container()
    # Los nombres antiguos siguen apuntando a la vista de hoy: el resto de la
    # función los usa en una docena de sitios y renombrarlos todos en el mismo
    # cambio que reordena las pestañas sería mezclar dos cosas que conviene
    # poder revisar por separado.
    _tab_modelo = _tab_jugar = _tab_todos = _tab_pata = _tab_hoy
    with _tab_hoy:
        try:
            import modo_modelo as _mm
            _mm.render(st, _pron_hoy, navegar=_ir_al_partido, clave='mm',
                       dia=_HOY_S)
        except Exception as _e_mm:
            logger.exception('[modo_modelo] fallo al pintar')
            st.caption(f"La lista de apuestas no está disponible "
                       f"({type(_e_mm).__name__}). Las demás pestañas siguen "
                       f"funcionando.")
    with _tab_manana:
        # La fecha lleva «CDMX» pegada a propósito: es la única forma de que un
        # partido a las 19:00 del 15 no parezca un error de la aplicación
        # cuando el reloj del servidor ya marca 16.
        # v155 — MAÑANA USA LA MISMA TARJETA QUE HOY.
        #
        # Enseñaba una tabla con la barra de 1X2 y la etiqueta «· informativo»,
        # mientras hoy tenía la apuesta destacada, las rachas y los mercados.
        # Eran dos diseños para el mismo partido, y la diferencia no venía de
        # los datos —que son los mismos— sino de que cada vista se había
        # construido en un momento distinto.
        #
        # `con_apuesta=False` es la ÚNICA diferencia, y es de fondo: los
        # partidos de mañana no producen picks porque las líneas se mueven
        # durante la noche, y ese movimiento es justo el canal que este
        # proyecto mide. Se enseña el análisis entero y se dice por qué todavía
        # no hay apuesta, en vez de proponer una que mañana no valdrá.
        if not _pron_man:
            st.subheader(f"🗓️ Partidos de MAÑANA · {_MANANA_S} (hora de CDMX)")
            st.info("Todavía no hay partidos de mañana en el barrido. Las "
                    "casas suelen abrir línea 2-4 días antes, así que esto se "
                    "llena solo a lo largo del día.")
        else:
            try:
                import modo_modelo as _mm_man
                _mm_man.render(
                    st, _pron_man, navegar=_ir_al_partido, clave='man',
                    con_apuesta=False,
                    titulo=f"🗓️ Partidos de mañana · {_MANANA_S} (CDMX)")
            except Exception as _e_m:
                logger.exception('[modo_modelo/manana] fallo al pintar')
                st.caption(f"Lista no disponible ({type(_e_m).__name__}).")
    _tab_ev, _tab_prob = _tab_jugar, _tab_pata
    with _tab_estado:
        _render_estado_sistema()
    with _tab_combi:
        _render_combinadas(r)

    # Lo que antes eran tres pestañas cae ahora DENTRO de la vista de hoy, cada
    # cosa en su desplegable y cerrada, para que la primera pantalla siga siendo
    # las tarjetas y nada más.
    #
    # Se anida el expander en el propio `with` en vez de sacar el cuerpo a una
    # función nueva. Mover cien líneas a una función definida más abajo es
    # exactamente el fallo que la v131 dejó escrito —se llamaba antes de
    # definirse y la vista moría con UnboundLocalError—, y aquí no hace falta:
    # `with A, B:` anida los dos contextos sin tocar una sola línea del cuerpo.
    with _tab_hoy:
        st.divider()
    with _tab_todos, st.expander(f"📋 Tabla completa del día "
                                 f"({len(_pron_hoy)})"):
        _render_todos_los_partidos()
    with _tab_prob, st.expander(f"🟡 Sólo como pata de combinada "
                                f"({len(_s2_hoy)})"):
        _render_maxima_confianza(r)

    # LA VENTAJA DE PRECIO NO DESAPARECE AL SIMPLIFICAR: CAMBIA DE SITIO.
    #
    # Es el único criterio con percentil 5 positivo medido en todo el proyecto
    # (+1,73 % en el tramo de juicio). Que la pantalla principal pase a ordenar
    # por probabilidad del modelo es una decisión de producto; borrar lo único
    # que tiene rentabilidad demostrada sería otra cosa muy distinta.
    #
    # Va en un desplegable dentro de la vista de hoy, y se abre solo cuando hay
    # algo dentro: un día con Sección 1 vacía no roba sitio, y un día con picks
    # los enseña sin que haya que buscarlos.
    with _tab_ev, st.expander(
            f"💎 Ventaja de precio — lo único con rentabilidad medida "
            f"({len(_s1_hoy)})", expanded=bool(_s1_hoy)):
        # -------------------------------------------------------------------
        # v128 — LAS DOS SECCIONES, ARRIBA DEL TODO.
        #
        # Es la respuesta a «quiero ver apuestas en la capa 1 que sí pueda
        # ganar». La lista que había debajo se ordenaba por el EV del modelo,
        # que es el criterio medido en −4,66 % a −6,52 % sobre 37.158 apuestas.
        # No se borra —sigue justo debajo, entera— pero deja de ser lo primero
        # que se ve, porque lo primero que se ve es lo que se juega.
        #
        # Arriba sólo suben los canales con p5 de bootstrap positivo en el
        # tramo que no se usó para elegirlos. Hoy son dos, y los dos aprueban
        # raspando: ver `clasificador.secciones_del_dia`.
        # -------------------------------------------------------------------
        # v131: ya filtradas por el selector de deporte de arriba. `r` sigue
        # intacto para Telegram y la exportación.
        _s1 = _s1_f
        _s2 = _s2_f
        _CANALES = {
            'precio_local': ('💰 Ventaja de precio al local',
                             'Una casa blanda paga por encima del precio justo '
                             'de Pinnacle. No depende de que el modelo acierte: '
                             'son dos precios del mismo suceso.'),
            'tenis_90': ('🎾 Tenis con probabilidad ≥ 90 %',
                         'La única banda del proyecto con p5 positivo. Cuotas '
                         'cortas (~1,15 de media): se gana por volumen y un '
                         'solo precio malo se come varias apuestas buenas.'),
        }
        _seccion(f"✅ Sección 1 — para jugar en solitario ({len(_s1)})",
                 'los únicos canales con percentil 5 positivo medido',
                 'ok' if _s1 else 'mira')
        if _s1:
            for _canal, (_tit, _sub) in _CANALES.items():
                _grupo = [p for p in _s1 if p.get('canal') == _canal]
                if not _grupo:
                    continue
                st.markdown(f"**{_tit}** — {_sub}")
                st.caption('Por qué está aquí: ' + (_grupo[0].get('motivo') or ''))
                _tarjetas(_grupo, "")
            st.caption(
                "⚠️ **La mejor apuesta disponible no es una apuesta ganadora "
                "garantizada.** Los dos canales de arriba aprueban el listón "
                "del proyecto por poco: p5 +1,73 % el de precio y +0,18 % el "
                "del tenis. Con una racha mala se ponen en negativo. Aquí no "
                "se promete ROI: se promete que es lo único que la medición "
                "sostiene.")
        else:
            st.info(
                "**Hoy no hay nada en la Sección 1, y eso es un resultado, no "
                "un fallo.** Sólo suben aquí dos cosas: fútbol donde una casa "
                "paga por encima del precio justo de Pinnacle **al lado "
                "local**, y tenis con probabilidad ≥ 90 % y precio publicado. "
                "El resto de picks del día están abajo, con su motivo. "
                "Forzar una apuesta porque la pantalla se ve vacía es "
                "exactamente lo que este sistema existe para evitar.")
        if _s2:
            # v131: con filtro puesto, el total del día ya no describe lo que
            # se está viendo; manda lo que hay delante.
            _n2 = len(_s2) if _dep_sel != 'Todo' else (r.get('n_seccion2')
                                                       or len(_s2))
            with st.expander(f"🟡 NO JUGAR EN SOLITARIO — sólo como pata de "
                             f"una combinada ({_n2})", expanded=False):
                st.warning(
                    "⚠️ **Estos picks NO se juegan solos.** Tienen "
                    "probabilidad alta y cuota que no compensa: sueltos "
                    "pierden dinero. Sirven para **inflar la cuota** de una "
                    "combinada que parta de la Sección 1, y aun así cada uno "
                    "empeora el valor del boleto.")
                st.caption(
                    "Combinarlos entre sí no arregla el problema, lo "
                    "multiplica: EV combinado = Π(1+EVᵢ)−1, así que tres "
                    "patas al −4,76 % dan −13,62 %. Están aquí porque saber "
                    "por qué algo NO se juega vale tanto como la lista de lo "
                    "que sí.")
                if _n2 > len(_s2):
                    st.caption(f"Se muestran {len(_s2)} de {_n2}, las de mayor "
                               f"probabilidad.")
                for _p in _s2[:12]:
                    st.markdown(
                        f"- **{_p.get('apuesta','?')}** · {_p.get('partido','?')} "
                        f"({_p.get('liga','')}) · "
                        + (f"@ {_p['cuota']} · " if _p.get('cuota') else '')
                        + f"{(_p.get('prob') or 0)*100:.0f} % — "
                        f"{_p.get('motivo','')}")
                if len(_s2) > 12:
                    st.caption(f"…y {len(_s2)-12} más, en la lista completa de "
                               f"abajo.")

        # v136 — LA CALCULADORA DE COMBINADAS.
        #
        # El encargo pedía «sugerir un parlay con EV positivo» combinando
        # picks de la Sección 2. No se puede: todos tienen EV negativo —es lo
        # que los puso ahí— y `Π(1+EVᵢ)−1` sobre números menores que 1 sigue
        # siendo menor que 1. Lo que sí se puede, y es lo que hay aquí, es
        # calcular el EV de VERDAD y enseñarlo antes de confirmar nada.
        #
        # Se parte siempre de la Sección 1 y se admite UNA pata de relleno.
        # Ver `parlay_ev` para la aritmética y las reglas.
        if _s1:
            with st.expander("🧮 Arma tu combinada — con el EV calculado antes "
                             "de jugarla", expanded=False):
                try:
                    import parlay_ev as _pev
                    _op_base = {
                        f"{p.get('apuesta','?')} · {p.get('partido','?')}"
                        f" @ {p.get('cuota','—')}": p for p in _s1}
                    _sel_base = st.selectbox(
                        "Pata base — de la Sección 1, la única con ventaja de "
                        "precio medida", list(_op_base.keys()),
                        key='parlay_base')
                    _aptos = [p for p in _s2
                              if (p.get('prob') or 0) >= _pev.PROB_MINIMA_RELLENO
                              and p.get('cuota')]
                    _op_rell = {'(ninguna — juega la pata sola)': None}
                    for p in _aptos[:15]:
                        _op_rell[f"{p.get('apuesta','?')} · "
                                 f"{p.get('partido','?')} @ {p.get('cuota')} · "
                                 f"{(p.get('prob') or 0)*100:.0f} %"] = p
                    if len(_op_rell) == 1:
                        st.caption(
                            f"Hoy ninguna pata de la Sección 2 llega al "
                            f"{_pev.PROB_MINIMA_RELLENO*100:.0f} % de "
                            f"probabilidad que exige el relleno, así que sólo "
                            f"cabe la pata sola.")
                    _sel_rell = st.selectbox(
                        "Pata de relleno — como mucho UNA, y cada una empeora "
                        "el boleto", list(_op_rell.keys()), key='parlay_rell')
                    _base_p = _op_base.get(_sel_base)
                    _rell_p = _op_rell.get(_sel_rell)
                    _res = _pev.evaluar(_base_p,
                                        [_rell_p] if _rell_p else [])
                    _c1, _c2, _c3 = st.columns(3)
                    _c1.metric("EV del boleto",
                               f"{(_res['ev'] or 0)*100:+.2f} %"
                               if _res['ev'] is not None else '—')
                    _c2.metric("Cuota combinada",
                               f"{_res['cuota']:.2f}" if _res.get('cuota')
                               else '—')
                    _c3.metric("Prob. conjunta",
                               f"{(_res['prob'] or 0)*100:.0f} %"
                               if _res.get('prob') is not None else '—')
                    if _res['ok']:
                        st.success(_res['motivo'])
                    else:
                        st.error(_res['motivo'])
                    for _a in _res.get('avisos') or []:
                        st.warning(_a)
                    _patas = [_base_p] + ([_rell_p] if _rell_p else [])
                    st.caption("La cuenta, para que no haya que creérsela:  \n"
                               f"`EV = {_pev.texto_formula(_patas)}`")
                except Exception as _e_pev:
                    st.caption(f"Calculadora no disponible ahora "
                               f"({type(_e_pev).__name__}).")
        st.divider()

        # v27 (§5+§7): stakes por Kelly SIMULTÁNEO (⅛, cap global 20 %)
        # v134: el filtro de deporte NO llegaba aquí. Al filtrar por MLB,
        # la Selección del Día seguía enseñando fútbol — el usuario vio
        # «Cusco FC vs Juan Pablo II» con el filtro puesto en béisbol.
        # `r` sigue intacto: se filtra la copia que se pinta.
        elite = _filtra(r.get('elite'))
        if elite:
            import kelly_simultaneo as ks
            bank = float(st.session_state.get('bankroll', 0) or 1000)
            con_stake = ks.stakes_jornada(elite, bank)
            for t, s in zip(elite, con_stake):
                t['stake_txt'] = (f"{s['stake']:.0f} u ({s['stake_pct']*100:.1f} %)"
                                  if s['stake_pct'] > 0 else '—')
            expo = sum(s['stake_pct'] for s in con_stake)
            st.caption(f"💼 Exposición total de la jornada: {expo*100:.1f} % del "
                       f"bankroll. Nunca se arriesga más del 20 % en un mismo día."  # v82: el texto
                       # decía ⅛ y la v81 subió la fracción a ¼ tras
                       # medirla; un pie que miente sobre cuánto se
                       # arriesga es peor que no tenerlo.
                       )
        # v28: Traductor Quant — etiquetas según el modo Principiante/Pro (v14)
        import traductor_quant as tq
        platino = [t for t in elite if t.get('platino')]
        if platino:
            st.subheader(tq.t('evc_platino', ES_PRO))
            st.caption(tq.tooltip('evc_platino'))
            _tarjetas(platino, "")
        _tarjetas([t for t in elite if t.get('evc') and not t.get('platino')],
                  tq.t('evc', ES_PRO))
        if not ES_PRO:
            st.caption(tq.tooltip('evc'))
        _tarjetas([t for t in elite if not t.get('evc')], "⭐ Picks de élite")

        # v47: SELECCIÓN DEL DÍA — la Capa 1 nunca queda vacía. Si hoy no hubo
        # ningún 1X2 con cuota real y confirmación, se promueven las mejores
        # oportunidades por valor esperado (con aviso honesto).
        seleccion = _filtra(r.get('seleccion_dia'))
        if not elite and seleccion:
            st.subheader("⭐ Selección del Día — mejor valor disponible")
            st.info("Hoy ninguna apuesta reunió cuota real + confirmación profesional. "
                    "Estas son las de mayor valor esperado del día. Úsalas con stake "
                    "prudente: no llevan el sello de la línea sharp.")
            _tarjetas(seleccion, "")

        # v31 (§5): CAPA 2 — alta confianza SIN cuota real (modo analítico)
        capa2 = _filtra(r.get('capa2'))
        if capa2:
            st.divider()
            st.subheader("🎯 Capa 2 — Predicciones de Alta Confianza"
                         if ES_PRO else "🎯 Apuestas sugeridas (sin cuota confirmada)")
            # v73: la Capa 2 ya NO es «sin cuota». Muchos de estos partidos tienen
            # precio real y lo que no alcanzan es un filtro de élite (casi siempre
            # la cuota mínima de 1.50 en favoritos muy cortos). Los que salen sin
            # cuota son los que ninguna casa ha abierto todavía.
            _con = sum(1 for t in capa2 if t.get('cuota'))
            st.info(
                f"Partidos donde el modelo está muy seguro pero que **no "
                f"recomendamos jugar sueltos**: {_con} tienen una cuota tan "
                f"baja que apenas compensa el riesgo, y el resto todavía no "
                f"tiene precio. Sirven para combinar.")
            _tarjetas(capa2, "")

        # v37 (§6): sección destacada de Ambos Marcan (BTTS)
        btts = _filtra(r.get('btts_destacado'))
        if btts:
            st.divider()
            st.subheader("⚽ Ambos Marcan (BTTS)")
            # v75: el texto anterior decía "uno de los mercados mejor calibrados del
            # sistema". La medición lo desmiente y no se puede seguir afirmando:
            # sobre 15.950 partidos fuera de muestra de 20 ligas, el Weibull de BTTS
            # da Brier 0.24880 frente a 0.24891 de contestar siempre la tasa base de
            # la liga — no discrimina — y el cierre de 1X2 + O/U 2.5 ya lo hace
            # mejor (0.24559). Se mantiene la sección (la pidió el usuario en v43)
            # con la etiqueta honesta.
            st.caption("Picks con confianza > 60 %"
                       + (" y EV > +1 % donde hay cuota real. " if any(p.get('cuota')
                          for p in btts) else ". ")
                       + "⚠️ Comprobado sobre 15.950 partidos: acertar «ambos "
                         "marcan» con el modelo **no es mejor que mirar la "
                         "media de la liga**. Aquí lo único que puede hacer "
                         "buena una apuesta es que la cuota esté alta, no la "
                         "probabilidad.")
            _tarjetas(btts, "")

        # v91 — LAS COMBINADAS, AL FINAL. Cargan motores de liga y corren Monte
        # Carlo; cuando vivían antes de las pestañas, todo lo importante (Máximo
        # Valor, Máxima Confianza) esperaba a que terminaran. Aquí abajo cuestan
        # lo mismo pero ya no retrasan nada.
    st.divider()
    _render_combinada_segura(pdd)
    _render_combinadas_dia()

    # v177 — y aquí se descartan las vistas que no se han elegido. Va
    # al FINAL a propósito: el cuerpo de «hoy» se pinta en seis sitios
    # distintos de esta función y el último es el de aquí arriba.
    for _k_vista, _slot in _slots.items():
        if _k_vista != _vista:
            _slot.empty()


# v88 — SE RETIRA LA ACTUALIZACIÓN VÍA THE ODDS API.
#
# La clave lleva devolviendo 401 en TODAS las ligas, así que este bloque no
# actualizaba nada: sólo escupía veinticinco líneas de error en el arranque de
# cada sesión, una por competición.
#
# Y no hace falta. Las cuotas del proyecto vienen desde la v71/v72 de
# `cuotas_multi` (Pinnacle + Bovada + Playdoit) y de los fixtures de ESPN, que
# son gratuitas, sin cuota mensual y cubren más partidos. Medido el mismo día
# de la retirada: Pinnacle 881 partidos de fútbol, 64 de tenis, 39 de MLB y 57
# de NBA; The Odds API, 0.
#
# `apuestas_del_dia` ya contemplaba esta situación desde la v61: si falta
# `odds_actuales.json` sigue adelante con el barrido de ESPN, que trae fixtures
# Y cuotas. Por eso quitarlo no deja hueco de cobertura.
def render_mlb():
    """v29 (§3-§6): vista del motor MLB (béisbol), aislada del fútbol."""
    _cabecera(
        'MLB — Béisbol',
        'Modelo calibrado sobre 23.466 predicciones fuera de muestra: '
        'cuando dice 62 %, es un 62 %.',
        chips=[('probabilidad calibrada', 'ok'), ('abridores', 'info')],
        icono='⚾')
    if _ayuda is not None:
        _ayuda.render(st, 'mlb')
    from engines.mlb_engine import MLBEngine, CODIGO_A_NOMBRE

    @st.cache_resource(show_spinner="Cargando modelo MLB…")
    def _motor():
        return MLBEngine().cargar_modelo()

    eng = _motor()
    if not eng.listo:
        st.error(f"El motor MLB no está disponible: {eng.error}")
        st.caption("Entrena con `python -m engines.mlb_engine` (descarga "
                   "Retrosheet y crea modelos/mlb/).")
        return
    md = eng.metadata
    # v80 — el pie decía «Retrosheet 2021-2025 · estado congelado al cierre de
    # 2025» y desde la v79 eso es FALSO en las tres afirmaciones: la fuente ya
    # no es Retrosheet sino la API oficial, el histórico llega a la temporada
    # en curso y el estado se refresca. Un pie de página que miente sobre la
    # frescura del modelo es peor que no tenerlo: el usuario decide con él.
    # Ahora se calcula de los datos, no se escribe a mano.
    import pandas as _pd
    _fechas = [v.get('ult_fecha') for v in (eng.estado.get('equipos') or {}).values()
               if v.get('ult_fecha')]
    if _fechas:
        _ult = _pd.Timestamp(max(_fechas))
        _dias = (_pd.Timestamp.today().normalize() - _ult.normalize()).days
        _sem = '🟢' if _dias <= 3 else ('🟡' if _dias <= 14 else '🔴')
        _frescura = (f"{_sem} último partido en el estado: {_ult.date()} "
                     f"({_dias} d)")
    else:
        _frescura = "⚠️ el estado del modelo no registra fechas"
    st.caption(
        f"Modelo entrenado con {md.get('n_juegos')} juegos "
        f"(MLB StatsAPI oficial, {md.get('temporadas', '2015-actual')}) · "
        f"precisión backtest {md.get('precision_validacion')*100:.1f} % "
        f"(ELO {md.get('precision_linea_base_elo')*100:.1f} %) · {_frescura}")

    nombres = {c: CODIGO_A_NOMBRE.get(c, c) for c in eng.equipos}
    # v106: tercera pestaña — abridores, estadio y ponches con la regla de
    # decisión de parlay que pidió el usuario (ver `beisbol_pitchers.py`).
    tab1, tab2, tab3 = st.tabs(["🎯 Predecir partido", "💰 EV+ automático MLB",
                                "⚾ Abridores, estadio y ponches"])
    with tab1:
        # v59: próximos partidos MLB (ESPN) con autorrelleno
        from engines.mlb_engine import codigo_mlb as _cod_mlb
        selector_proximos('mlb', eng.equipos, 'mlb_h', 'mlb_a', 'MLB',
                          mapear=_cod_mlb)
        # v91 — el default se siembra en session_state ANTES de crear el
        # widget, nunca con `index=`. `selector_proximos` escribe estas claves
        # vía Session State API, y un widget creado con default + clave ya
        # escrita dispara el aviso de Streamlit que en producción salía como
        # un stack de 30 líneas en el arranque (policies.check_session_state_rules).
        if 'mlb_a' not in st.session_state and len(eng.equipos) > 1:
            st.session_state['mlb_a'] = eng.equipos[1]
        c1, c2 = st.columns(2)
        home = c1.selectbox("🏠 Local", eng.equipos,
                            format_func=lambda c: nombres.get(c, c), key='mlb_h')
        away = c2.selectbox("✈️ Visitante", eng.equipos,
                            format_func=lambda c: nombres.get(c, c),
                            key='mlb_a')
        if home == away:
            st.warning("Elige equipos distintos.")
        else:
            # v56: plantilla MLB COMPLETA en secciones (run line, margen,
            # totales por equipo, primeros innings/F5, extra innings).
            pl = eng.plantilla_mlb(home, away)
            pr = pl['prediccion_base']
            m1, m2, m3 = st.columns(3)
            m1.metric(f"Gana {nombres.get(home, home)}", f"{pr['prob_home']*100:.0f} %")
            m2.metric(f"Gana {nombres.get(away, away)}", f"{pr['prob_away']*100:.0f} %")
            m3.metric("Carreras totales (est.)", f"{pr['total_estimado']:.1f}")
            for sec in pl['secciones']:
                with st.expander(f"📋 {sec['titulo']}", expanded=sec['titulo'].startswith('1.')):
                    st.dataframe(pd.DataFrame([{
                        'Mercado': c['etiqueta'], 'Prob.': f"{c['valor']:.0f} %",
                        'Cuota justa': round(100 / max(c['valor'], 1e-6), 2)}
                        for c in sec['campos'] if c.get('tipo', 'pct') == 'pct']),
                        width='stretch', hide_index=True)
            for obs in pl.get('observaciones', []):
                st.caption(obs)
            # v114: serie histórica, clasificación y forma (lo que el fútbol
            # ya tenía y la MLB no)
            st.divider()
            try:
                render_panel_beisbol('mlb', home, away, key='mlb',
                                     nombres=nombres)
            except Exception as e:
                st.caption(f"Panel de equipos no disponible ({type(e).__name__}).")
            # v56: combinador de mercados (manual + automático) para MLB
            st.divider()
            render_parlay_partido(eng, home, away, key='mlb')
    with tab2:
        # v106 — pasa al panel común de EV+ (`render_ev_automatico`), el mismo
        # de NBA, KBO y tenis. Gana lo que le faltaba y los otros ya tenían:
        # la Capa 2 («alta confianza», que el motor calculaba desde la v91 y
        # esta pestaña tiraba), la hora del partido en CDMX y el botón de
        # refresco. Los filtros y la fuente no cambian.
        render_ev_automatico(
            'MLB', eng.apuestas_dia,
            ayuda="Filtros de élite: prob >58 %, EV >+3 %, cuota >1.50.")

    with tab3:
        render_beisbol_pitchers()


def render_kbo():
    """
    v97 — vista de la KBO (béisbol coreano).

    Misma estructura que la de la MLB porque es el mismo motor de béisbol,
    con dos diferencias que el usuario tiene que ver escritas: el modelo va
    en modo informativo (no hay cuota de cierre histórica con la que validar
    un edge de apuesta) y en la KBO existe el empate.
    """
    _cabecera(
        'KBO — Béisbol coreano',
        'Con las estadísticas del abridor y del bullpen dentro del '
        'modelo, no como comentario aparte.',
        chips=[('abridor y bullpen', 'ok')], icono='⚾')
    # v98 — misma red que en `render_liga_club`: durante la ventana de recarga
    # de Streamlit Cloud puede haber un `dashboard_ui` nuevo con el motor de
    # KBO todavía sin desplegar. Un ImportError aquí dejaría la app en blanco.
    try:
        from engines.kbo_engine import KBOEngine
    except Exception as e:
        st.warning(
            f"🔄 El motor de KBO todavía no está disponible en esta sesión "
            f"(`{type(e).__name__}`). Suele durar unos segundos tras una "
            f"actualización: recarga la página.")
        st.stop()

    @st.cache_resource(show_spinner="Cargando modelo KBO…")
    def _motor():
        return KBOEngine().cargar_modelo()

    eng = _motor()
    if not eng.listo:
        st.error(f"El motor KBO no está disponible: {eng.error}")
        st.caption("Entrena con `python -m engines.kbo_engine` (descarga el "
                   "histórico de Naver Sports y crea modelos/kbo/).")
        return

    md = eng.metadata
    import pandas as _pd
    _fechas = [v.get('ult_fecha') for v in (eng.estado.get('equipos') or {}).values()
               if v.get('ult_fecha')]
    if _fechas:
        _ult = _pd.Timestamp(max(_fechas))
        _dias = (_pd.Timestamp.today().normalize() - _ult.normalize()).days
        _sem = '🟢' if _dias <= 3 else ('🟡' if _dias <= 14 else '🔴')
        _frescura = f"{_sem} último partido en el estado: {_ult.date()} ({_dias} d)"
    else:
        _frescura = "⚠️ el estado del modelo no registra fechas"
    _wf = md.get('walk_forward') or {}
    st.caption(
        f"Modelo entrenado con {md.get('n_juegos')} juegos "
        f"(Naver Sports, 2008-actual) · precisión backtest "
        f"{md.get('precision_validacion', 0)*100:.1f} % "
        f"(ELO {md.get('precision_linea_base_elo', 0)*100:.1f} %) · {_frescura}")
    if _wf:
        # v99 — el texto decía «no existe histórico de cuotas de cierre». Ya no
        # es cierto: se encontró (BetExplorer, 2012-2025) y se midió. El
        # resultado es peor que no tener dato, pero es el que hay y se dice.
        st.info(
            f"**Modo informativo, y ahora por una razón medida.** El modelo "
            f"acierta el **{_wf.get('precision', 0)*100:.1f} %** frente al "
            f"**{_wf.get('precision_elo', 0)*100:.1f} %** de la línea base, así "
            f"que sí aporta sobre el ELO. Pero contra el **precio de cierre "
            f"real** —204 partidos de KBO reunidos de BetExplorer— pierde "
            f"dinero: **ROI −9,1 %** apostando a su lado favorito y **−13,5 %** "
            f"filtrando por EV, y su probabilidad está peor calibrada que la de "
            f"la casa (Brier 0,249 contra 0,241). Batir al ELO no es batir al "
            f"mercado. Por eso sus partidos se muestran y **no se proponen como "
            f"apuesta**.")
        st.caption(
            'Se probaron cuatro salidas y ninguna funciona: mezclar modelo y '
            'mercado da un peso óptimo del modelo de **cero**; no hay banda de '
            'discrepancia donde acierte más que la casa; filtrar por favoritos '
            'claros deja ROI −10,4 %; y apostar **al revés** que el modelo '
            'también pierde (−3,0 %), que es la señal de que no hay '
            'información explotable en ningún sentido, no de que esté al revés. '
            'Lo que sí puede dar picks aquí es la diferencia entre casas (line '
            'shopping), que no depende de que el modelo acierte, y se comprueba '
            'en cada barrido.')
    st.caption(
        "En la KBO se corta a las 12 entradas: alrededor del 4 % de los juegos "
        "acaba en empate. Las probabilidades de abajo son de ganar **a condición "
        "de que haya ganador**.")

    # v106: la KBO también tiene su EV+ automático (ver `render_ev_automatico`)
    tab1, tab2, tab3 = st.tabs(["🎯 Predecir partido", "📅 Partidos de hoy",
                                "💰 EV+ automático KBO"])
    with tab1:
        # v99 — PRÓXIMOS PARTIDOS, que faltaban.
        #
        # La vista obligaba a elegir los dos equipos a mano. La KBO publica su
        # calendario en la misma fuente de la que salen los resultados (Naver),
        # con el abridor anunciado, así que no hay razón para no ofrecerlos ya
        # rellenados — es lo que hacen MLB, NBA y las ligas de fútbol.
        try:
            import kbo_naver
            import pandas as _pd

            @st.cache_data(ttl=1800, show_spinner='Buscando partidos de KBO…')
            def _proximos_kbo():
                hoy = _pd.Timestamp.now('UTC').tz_localize(None).normalize()
                fuera = []
                for k in range(0, 4):           # hoy y los 3 días siguientes
                    f = (hoy + _pd.Timedelta(days=k)).strftime('%Y-%m-%d')
                    for p in kbo_naver.partidos_del_dia(f):
                        if p.get('estado') != 'RESULT':
                            fuera.append(p)
                return fuera

            px = _proximos_kbo()
            if px:
                etiquetas = [
                    f"{p['fecha']} · {p['away']} @ {p['home']}"
                    + (f" (abren {p['away_pitcher']} / {p['home_pitcher']})"
                       if p['home_pitcher'] and p['away_pitcher'] else ' · abridor sin anunciar')
                    for p in px]
                st.caption(f"📅 {len(px)} partidos por jugar en los próximos 4 días.")
                elegido = st.selectbox('Próximos partidos', range(len(px)),
                                       format_func=lambda i: etiquetas[i],
                                       key='kbo_px')
                if st.button('Cargar este partido', key='kbo_cargar'):
                    st.session_state['kbo_h'] = px[elegido]['home']
                    st.session_state['kbo_a'] = px[elegido]['away']
                    st.rerun()
            else:
                st.caption('📅 No hay partidos de KBO en los próximos 4 días '
                           '(la temporada va de marzo a octubre).')
        except Exception as e:
            st.caption(f'📅 No se pudo consultar el calendario de KBO ({type(e).__name__}).')

        if 'kbo_a' not in st.session_state and len(eng.equipos) > 1:
            st.session_state['kbo_a'] = eng.equipos[1]
        c1, c2 = st.columns(2)
        home = c1.selectbox("🏠 Local", eng.equipos, key='kbo_h')
        away = c2.selectbox("✈️ Visitante", eng.equipos, key='kbo_a')
        if home == away:
            st.warning("Elige equipos distintos.")
        else:
            pl = eng.plantilla_kbo(home, away)
            if 'error' in pl:
                st.error(pl['error'])
            else:
                pr = pl['prediccion_base']
                m1, m2, m3 = st.columns(3)
                m1.metric(f"Gana {home}", f"{pr['prob_home']*100:.0f} %")
                m2.metric(f"Gana {away}", f"{pr['prob_away']*100:.0f} %")
                m3.metric("Carreras totales (est.)",
                          f"{pr['total_estimado']:.1f}")
                for sec in pl['secciones']:
                    with st.expander(f"📋 {sec['titulo']}",
                                     expanded=sec['titulo'].startswith('1.')):
                        st.dataframe(pd.DataFrame([{
                            'Mercado': c['etiqueta'], 'Prob.': f"{c['valor']:.0f} %",
                            'Cuota justa': round(100 / max(c['valor'], 1e-6), 2)}
                            for c in sec['campos'] if c.get('tipo', 'pct') == 'pct']),
                            width='stretch', hide_index=True)
                for obs in pl.get('observaciones', []):
                    st.caption(obs)
                if pl.get('nota_empate'):
                    st.caption(pl['nota_empate'])
                # v114: serie histórica, clasificación y forma (13.009
                # partidos de KBO en el histórico local)
                st.divider()
                try:
                    render_panel_beisbol('kbo', home, away, key='kbo')
                except Exception as e:
                    st.caption(f"Panel de equipos no disponible "
                               f"({type(e).__name__}).")

    with tab2:
        @st.cache_data(ttl=1800, show_spinner="Consultando cuotas KBO…")
        def _kbo_hoy():
            return eng.apuestas_dia()

        r = _kbo_hoy()
        st.caption(f"{r.get('eventos', 0)} partidos con cuota · "
                   f"{r.get('evaluados', 0)} evaluados por el modelo · "
                   f"{r.get('con_abridor', 0)} con abridor anunciado. "
                   f"Cuotas de Pinnacle y Playdoit.")
        filas = (r.get('picks') or []) + (r.get('confianza') or [])
        if not filas:
            st.info("Hoy no hay ningún partido de KBO donde el modelo se "
                    "separe del precio lo suficiente como para destacarlo. "
                    "La temporada va de marzo a octubre.")
        for pk in filas:
            with st.container(border=True):
                cc1, cc2 = st.columns([3, 2])
                cc1.markdown(f"**{pk['partido']}**  \n{pk['fecha']}")
                cc2.markdown(f"{pk.get('valor', '🎯')} {pk['apuesta']}  \n"
                             f"Cuota **{pk['cuota']}** (justa {pk['cuota_justa']}) · "
                             f"EV **{pk['ev']*100:+.1f} %**")
        for inc in r.get('incidencias') or []:
            st.caption(inc)
        from bankroll_manager import AVISO_JUEGO_RESPONSABLE
        st.caption(AVISO_JUEGO_RESPONSABLE)

    with tab3:
        import alpha_finder as _af
        render_ev_automatico(
            'KBO', _af._picks_kbo,
            nota="Recuerda lo de arriba: el modelo de KBO bate al ELO pero "
                 "**no al mercado** (medido sobre 204 cierres reales), así que "
                 "sus picks con valor salen de la diferencia entre casas "
                 "—Pinnacle contra el resto—, no de que el modelo acierte "
                 "más. Por eso van marcados y no entran en la Capa 1.")


def render_nba():
    """
    v30 (§4): vista NBA. v106: con EV+ automático, como el resto de deportes.

    El docstring decía «modo analítico (sin cuotas en vivo hasta oct 2026)» y
    llevaba desfasado desde la v88: The Odds API se retiró entonces y las
    cuotas de NBA salen desde la v77 de Pinnacle y Bovada vía `cuotas_multi`.
    Fuera de temporada no hay partidos y el panel sale vacío — que es correcto
    y distinto de «no hay EV».
    """
    _cabecera(
        'NBA — Baloncesto',
        'Ganador, hándicap y total del partido, con la cuota real de las '
        'casas cuando la hay.', icono='🏀')
    from engines.nba_engine import NBAEngine

    @st.cache_resource(show_spinner="Cargando modelo NBA…")
    def _m():
        return NBAEngine().cargar_modelo()
    eng = _m()
    if not eng.listo:
        st.error(f"Motor NBA no disponible: {eng.error}")
        return
    md = eng.metadata
    st.caption(f"Entrenado con {md.get('n_juegos')} juegos (nba_api 2021-26) · "
               f"precisión backtest {md.get('precision_validacion')*100:.1f} % "
               f"(ELO {md.get('precision_linea_base_elo')*100:.1f} %) · "
               f"incluye el CDI (desincronización circadiana). {md.get('modo')}")
    selector_proximos('nba', eng.equipos, 'nba_h', 'nba_a', 'NBA')  # v59
    # v91: mismo arreglo que en MLB — default sembrado, sin `index=` (evita el
    # aviso de Streamlit por widget con default + clave escrita por código)
    if 'nba_a' not in st.session_state and len(eng.equipos) > 1:
        st.session_state['nba_a'] = eng.equipos[1]
    c1, c2 = st.columns(2)
    home = c1.selectbox("🏠 Local", eng.equipos, key='nba_h')
    away = c2.selectbox("✈️ Visitante", eng.equipos, key='nba_a')
    # v106 — la NBA gana su pestaña de EV+ automático, igual que los demás.
    #
    # El pie de página decía «sin EV real hasta que The Odds API reactive la
    # NBA en octubre», y eso quedó desfasado dos veces: The Odds API se retiró
    # en la v88, y desde entonces las cuotas de NBA salen de Pinnacle y Bovada
    # vía `cuotas_multi` — que es de donde ya las saca `alpha_finder._picks_nba`
    # para la pantalla general. O sea que el EV existía; lo que faltaba era
    # enseñarlo aquí.
    tab1, tab2 = st.tabs(["🎯 Predecir partido", "💰 EV+ automático NBA"])
    with tab1:
        if home != away:
            pl = eng.plantilla(home, away)
            pr = pl['prediccion']
            m1, m2, m3 = st.columns(3)
            m1.metric(f"Gana {home}", f"{pr['prob_home']*100:.0f} %")
            m2.metric(f"Gana {away}", f"{pr['prob_away']*100:.0f} %")
            m3.metric("Puntos totales (est.)", f"{pr['total_estimado']:.0f}")
            st.caption("Cuota justa = 1/probabilidad. El EV contra cuota real "
                       "está en la pestaña de al lado.")
    with tab2:
        import alpha_finder as _af
        render_ev_automatico(
            'NBA', _af._picks_nba,
            nota="Fuera de temporada (julio-septiembre) ninguna casa publica "
                 "partidos de NBA y aquí no aparece nada: es correcto, no un "
                 "fallo.")


def render_nfl():
    """
    v131 — vista de la NFL: predicción, forma reciente y el tablero de la casa.

    Se dice lo que es desde la primera línea, porque es lo que la bitácora §0
    obliga a decir: el modelo sirve para ORDENAR, y quien decide si algo tiene
    valor es la ventaja de precio contra el consenso. La cifra que lo respalda
    se lee de `nfl_calibracion.json`, o sea de la medición real, no de un texto
    escrito a mano que se quedaría viejo.
    """
    _cabecera(
        'NFL — Fútbol americano',
        'Ganador, hándicap, total del partido y totales de equipo, con el '
        'tablero completo de tu casa y el consenso de las demás al lado.',
        chips=[('32 equipos', 'info'), ('ESPN + 3 casas', 'info'),
               ('el edge está en el precio', 'ok')],
        icono='🏈')
    try:
        import nfl_datos as nd
        import modelo_nfl as mnfl
    except Exception as e:
        st.error(f"Módulos de NFL no disponibles: {type(e).__name__}: {e}")
        return

    @st.cache_data(ttl=3600, show_spinner="Cargando histórico de la NFL…")
    def _hist():
        return nd.cargar_historico()

    @st.cache_resource(show_spinner="Cargando modelo NFL…")
    def _modelo():
        return mnfl.NFLModelo.cargar(historico=nd.cargar_historico())

    hist = _hist()
    if not len(hist):
        st.warning(
            "No hay histórico de la NFL en el repositorio. Se construye con "
            "`python nfl_datos.py`, que descarga de ESPN el marcador, las 25 "
            "estadísticas de equipo y las cuotas de cierre de cada partido.")
        return
    modelo = _modelo()

    # --- lo que está medido, dicho antes que nada -------------------------
    cal = {}
    try:
        with open(mnfl.CALIBRACION, encoding='utf-8') as _f:
            cal = json.load(_f)
    except Exception:
        pass
    _cm = cal.get('contra_mercado') or {}
    _n = len(hist[hist['tipo'].isin(('regular', 'playoffs'))]) if 'tipo' in hist else len(hist)
    st.caption(
        f"Entrenado con {_n} partidos de la NFL "
        f"({str(hist['fecha'].min())[:10]} → {str(hist['fecha'].max())[:10]}) — "
        f"marcador y estadística de equipo de ESPN."
        + (f" Fuera de muestra acierta el ganador el "
           f"{_cm['acierto_modelo']*100:.1f} % frente al {_cm['acierto_mercado']*100:.1f} % "
           f"del mercado (n={_cm['n']})." if _cm else ''))
    if _cm and _cm.get('brier_modelo', 9) > _cm.get('brier_mercado', 0):
        st.info(
            "ℹ️ **El modelo NO bate al mercado en la NFL**, y se dice antes de "
            f"enseñar un solo número: su Brier fuera de muestra es "
            f"{_cm['brier_modelo']:.4f} contra {_cm['brier_mercado']:.4f} del "
            "precio de cierre. Por eso sus picks van a «Sólo como pata» y "
            "nunca a la Sección 1 — ahí sólo entra la NFL por **ventaja de "
            "precio** contra el consenso, que no depende del modelo.")

    equipos = sorted(nd.EQUIPOS, key=lambda k: nd.EQUIPOS[k]['nombre'])
    nombres = [nd.EQUIPOS[k]['nombre'] for k in equipos]
    por_nombre = {nd.EQUIPOS[k]['nombre']: k for k in equipos}

    # --- selector de próximos partidos -------------------------------------
    try:
        prox = nd.fixtures_nfl(dias=8)
    except Exception:
        prox = []
    # EL TIPO DE PARTIDO VIAJA CON EL PARTIDO, no se supone.
    #
    # El selector de abajo es por EQUIPOS, así que sin esto la ficha de un
    # partido de agosto se predeciría como si fuera liga regular — y el modelo
    # no tiene ahí ninguna información (correlación −0,013 con el margen real).
    # Se guarda el tipo del fixture cargado y se le pasa al modelo.
    if prox:
        _ops = {f"{p['away']} @ {p['home']} · {p['fecha']}"
                + (' · pretemporada' if p.get('tipo') == 'pretemporada' else ''):
                (p['abrev_home'], p['abrev_away'], p.get('tipo') or 'regular')
                for p in prox}
        c0, c1 = st.columns([3, 1])
        _elegido = c0.selectbox('📅 Próximos partidos', list(_ops),
                                key='nfl_prox')
        if c1.button('Cargar', key='nfl_cargar', width='stretch'):
            h_, a_, t_ = _ops[_elegido]
            st.session_state['nfl_h'] = nd.nombre_largo(h_)
            st.session_state['nfl_a'] = nd.nombre_largo(a_)
            st.session_state['nfl_tipo'] = t_
            st.rerun()
    else:
        st.caption('📅 Sin partidos de NFL en los próximos 8 días.')

    if 'nfl_a' not in st.session_state:
        st.session_state['nfl_a'] = nombres[1]
    c1, c2 = st.columns(2)
    home_n = c1.selectbox('🏠 Local', nombres, key='nfl_h')
    away_n = c2.selectbox('✈️ Visitante', nombres, key='nfl_a')
    if home_n == away_n:
        st.warning('Elige dos equipos distintos.')
        return
    home, away = por_nombre[home_n], por_nombre[away_n]

    tab1, tab2, tab3 = st.tabs(['🎯 Predecir partido', '📊 Forma y H2H',
                                '💰 EV+ automático NFL'])

    with tab1:
        if modelo is None:
            st.warning(
                'El modelo no está entrenado. Se genera con '
                '`python modelo_nfl.py --entrenar`, que además escribe la '
                'medición en `nfl_calibracion.json`.')
        else:
            # las líneas que publica la casa, para no inventar ninguna
            det, lineas = None, {}
            try:
                import cuotas_multi as _cm2
                import nfl_mercados as _nm2
                det = _cm2.mercados_playdoit('nfl', home_n, away_n)
                if det:
                    lineas = _nm2.lineas_del_tablero(det, home_n, away_n)
            except Exception as e:
                logger.debug(f'[nfl-ui] tablero: {e}')
            pred = modelo.predecir_partido(
                home, away,
                tipo=st.session_state.get('nfl_tipo', 'regular'),
                linea_hcp=(lineas.get('handicap') or [None])[0],
                linea_total=(lineas.get('total') or [None])[0],
                lineas_equipo=((lineas.get('total_home') or [None])[0],
                               (lineas.get('total_away') or [None])[0]))
            if 'error' in pred:
                st.warning(f"Sin predicción: {pred['error']}")
            else:
                if not pred.get('probabilidades_publicables', True):
                    st.info('ℹ️ ' + pred.get('motivo_sin_probabilidad', ''))
                m1, m2, m3 = st.columns(3)
                _ph = pred.get('prob_home_sin_empate')
                _pa = pred.get('prob_away_sin_empate')
                m1.metric(f'Gana {home_n}',
                          f"{_ph*100:.0f} %" if _ph is not None else '—')
                m2.metric(f'Gana {away_n}',
                          f"{_pa*100:.0f} %" if _pa is not None else '—')
                m3.metric('Puntos totales (est.)',
                          f"{pred['total_esperado']:.0f}")
                try:
                    import render_todos_partidos as _rtp
                    _pinta(_rtp.CSS + _rtp.barra_dos_vias(
                        _ph, f"{home_n} · {away_n}"))
                except Exception:
                    pass
                st.caption(
                    f"Marcador esperado **{home_n} {pred['pts_home_esperado']:.0f} – "
                    f"{pred['pts_away_esperado']:.0f} {away_n}** · margen "
                    f"{pred['margen_esperado']:+.1f} (σ {pred['sigma_margen']}) · "
                    f"total {pred['total_esperado']:.1f} (σ {pred['sigma_total']}). "
                    f"La σ es la dispersión MEDIDA de los residuos, no un "
                    f"supuesto: es lo que convierte un marcador esperado en "
                    f"una probabilidad honesta.")
                if pred.get('n_home', 99) < 4 or pred.get('n_away', 99) < 4:
                    st.warning(
                        f"⚠️ Muestra corta: {home_n} lleva {pred.get('n_home')} "
                        f"partidos en la memoria del modelo y {away_n}, "
                        f"{pred.get('n_away')}. Al principio de temporada las "
                        f"medias son casi las de la liga y la predicción vale "
                        f"poco más que la localía.")

                # --- el tablero de la casa cruzado con el modelo ------------
                if det:
                    try:
                        import nfl_mercados as _nm3
                        filas = _nm3.mercados_con_ev_nfl(det, pred, home_n, away_n)
                    except Exception as e:
                        filas, _ = [], logger.warning(f'[nfl-ui] cruce: {e}')
                    if filas:
                        st.markdown(f'#### 💵 Tablero de {det.get("casa")} '
                                    f'— {len(filas)} mercados')
                        _df = pd.DataFrame([{
                            'Mercado': r.get('familia') or r.get('mercado'),
                            'Apuesta': r.get('apuesta'),
                            'Cuota': r.get('cuota_casa'),
                            'Prob. modelo': (f"{r['prob']*100:.1f} %"
                                             if r.get('prob') is not None else '—'),
                            'EV': ('—' if r.get('ev') is None
                                   or r.get('ev_no_fiable') or r.get('sin_modelo')
                                   else f"{r['ev']*100:+.1f} %"),
                            'Aviso': ('el modelo no cubre este mercado'
                                      if r.get('sin_modelo') or r.get('ev_no_fiable')
                                      else ''),
                        } for r in filas])
                        st.dataframe(_df, width='stretch', hide_index=True)
                        # Sin número de versión en el texto: es jerga interna y
                        # el test `test_mensajes_sin_jerga_interna` lo vigila.
                        # La referencia al precedente del fútbol vive en el
                        # comentario, que es donde le sirve a quien mantiene
                        # esto, no al usuario que quiere apostar.
                        st.caption(
                            "Los mercados de mitades, cuartos y «primer equipo "
                            "en marcar» salen **con precio y sin EV**: el modelo "
                            "predice el partido completo y no tiene medido el "
                            "reparto por periodo. Se dice en vez de rellenarlo "
                            "con una proporción inventada.")
                else:
                    st.caption('Este partido no está hoy en el catálogo de '
                               'Playdoit, así que no hay tablero que cruzar.')

    with tab2:
        try:
            import h2h_visual as _h2h
            f_h = nd.forma_reciente(hist, home, n=5)
            f_a = nd.forma_reciente(hist, away, n=5)
            _pinta(_h2h.bloque(home_n, away_n, f_h, f_a, n=5, deporte='nfl'))
            st.caption(_h2h.resumen_texto(home_n, f_h, 5) + '  \n'
                       + _h2h.resumen_texto(away_n, f_a, 5))
        except Exception as e:
            st.info(f'Forma reciente no disponible: {type(e).__name__}: {e}')
        try:
            _dir = nd.h2h(hist, home, away, n=6)
        except Exception:
            _dir = []
        st.markdown('#### 🤝 Enfrentamientos directos')
        if _dir:
            st.dataframe(pd.DataFrame([{
                'Fecha': d['fecha'], 'Temporada': d['temporada'],
                'Partido': f"{d['away']} @ {d['home']}",
                'Marcador': f"{d['pts_away']} – {d['pts_home']}",
                'Tipo': d['tipo']} for d in _dir]),
                width='stretch', hide_index=True)
        else:
            st.caption('Sin enfrentamientos directos en el histórico '
                       'descargado. En la NFL es lo normal: sólo se cruzan '
                       'una vez cada varios años fuera de la división.')

    with tab3:
        import alpha_finder as _af
        render_ev_automatico(
            'NFL', _af._picks_nfl,
            nota='Los picks de NFL en la Sección 1 salen de la ventaja de '
                 'precio contra Pinnacle, no del modelo.')


def _prob_set_local(p_partido: float, best_of: int = 3) -> float:
    """v51.2: invierte P(partido)→P(set) bajo sets i.i.d. Réplica local (en el
    script principal, siempre fresco) para no depender de que Streamlit Cloud
    recargue el módulo del motor tras un despliegue."""
    p_partido = min(max(p_partido, 1e-4), 1 - 1e-4)
    lo, hi = 0.0, 1.0
    for _ in range(60):
        s = (lo + hi) / 2
        pm = (s ** 3 * (1 + 3 * (1 - s) + 6 * (1 - s) ** 2) if best_of == 5
              else s ** 2 * (3 - 2 * s))
        if pm < p_partido:
            lo = s
        else:
            hi = s
    return (lo + hi) / 2


def _mercados_sets_tenis(home: str, away: str, p: float, best_of: int = 3):
    """v51.2: TODOS los mercados de sets derivables (primer set, marcador
    exacto ambos lados, gana exactamente 1 set, ambos ganan un set, hándicap
    de sets ±1.5, doble resultado 1er set/partido) calculados AQUÍ, en el
    script principal. Robusto ante el caché de módulos de Streamlit Cloud."""
    s = _prob_set_local(p, best_of)
    campos = []
    if best_of == 3:
        h20, h21 = s ** 2, 2 * s ** 2 * (1 - s)
        a20, a21 = (1 - s) ** 2, 2 * (1 - s) ** 2 * s
        p_ambos = 1 - s ** 2 - (1 - s) ** 2
        dr_hh = s * (1 - (1 - s) ** 2)
        dr_ha = s * (1 - s) ** 2
        dr_ah = (1 - s) * s ** 2
        dr_aa = (1 - s) * (1 - s ** 2)
        campos = [
            {'id': 'set1_home', 'etiqueta': f'Gana 1er set: {home}', 'valor': s * 100},
            {'id': 'set1_away', 'etiqueta': f'Gana 1er set: {away}', 'valor': (1 - s) * 100},
            {'id': 'set_2_0', 'etiqueta': f'{home} gana 2-0', 'valor': h20 * 100},
            {'id': 'set_2_1', 'etiqueta': f'{home} gana 2-1', 'valor': h21 * 100},
            {'id': 'set_0_2', 'etiqueta': f'{away} gana 2-0', 'valor': a20 * 100},
            {'id': 'set_1_2', 'etiqueta': f'{away} gana 2-1', 'valor': a21 * 100},
            {'id': 'ambos_set', 'etiqueta': 'Ambos ganan al menos un set', 'valor': p_ambos * 100},
            {'id': 'set_home', 'etiqueta': f'{home} gana al menos un set', 'valor': (1 - (1 - s) ** 2) * 100},
            {'id': 'set_away', 'etiqueta': f'{away} gana al menos un set', 'valor': (1 - s ** 2) * 100},
            {'id': 'exact1_home', 'etiqueta': f'{home} gana exactamente 1 set', 'valor': a21 * 100},
            {'id': 'exact1_away', 'etiqueta': f'{away} gana exactamente 1 set', 'valor': h21 * 100},
            {'id': 'hset_home_-1.5', 'etiqueta': f'{home} −1.5 sets (gana 2-0)', 'valor': h20 * 100},
            {'id': 'hset_home_+1.5', 'etiqueta': f'{home} +1.5 sets (gana ≥1 set)', 'valor': (1 - (1 - s) ** 2) * 100},
            {'id': 'hset_away_-1.5', 'etiqueta': f'{away} −1.5 sets (gana 2-0)', 'valor': a20 * 100},
            {'id': 'hset_away_+1.5', 'etiqueta': f'{away} +1.5 sets (gana ≥1 set)', 'valor': (1 - s ** 2) * 100},
            {'id': 'dr_hh', 'etiqueta': f'Doble: {home} 1er set y {home} partido', 'valor': dr_hh * 100},
            {'id': 'dr_ha', 'etiqueta': f'Doble: {home} 1er set y {away} partido', 'valor': dr_ha * 100},
            {'id': 'dr_ah', 'etiqueta': f'Doble: {away} 1er set y {home} partido', 'valor': dr_ah * 100},
            {'id': 'dr_aa', 'etiqueta': f'Doble: {away} 1er set y {away} partido', 'valor': dr_aa * 100},
        ]
    else:
        p20 = s ** 3 * (1 + 3 * (1 - s))
        campos = [
            {'id': 'set1_home', 'etiqueta': f'Gana 1er set: {home}', 'valor': s * 100},
            {'id': 'set1_away', 'etiqueta': f'Gana 1er set: {away}', 'valor': (1 - s) * 100},
            {'id': 'set_home', 'etiqueta': f'{home} gana al menos un set', 'valor': (1 - (1 - s) ** 3) * 100},
            {'id': 'set_away', 'etiqueta': f'{away} gana al menos un set', 'valor': (1 - s ** 3) * 100},
        ]
    return campos


def render_tennis():
    """v30 (§5) + v35 (§1): vista de Tenis con los DOS circuitos, ELO por
    superficie (incluida pista cubierta) y features de fatiga."""
    _cabecera(
        'Tenis — ATP / WTA',
        'Partido, sets y juegos, con la superficie y el desgaste '
        'dentro del cálculo.',
        chips=[('ATP', 'info'), ('WTA', 'info')], icono='🎾')
    if _ayuda is not None:
        _ayuda.render(st, 'tenis')
    from engines.tennis_engine import TennisEngine

    @st.cache_resource(show_spinner="Cargando modelo de tenis…")
    def _m(circuito):
        return TennisEngine(circuito).cargar_modelo()

    circuito = st.radio("Circuito", ['ATP (masculino)', 'WTA (femenino)'],
                        horizontal=True, key='ten_circ')
    eng = _m('wta' if circuito.startswith('WTA') else 'atp')
    if not eng.listo:
        st.error(f"Motor de tenis no disponible: {eng.error}")
        return
    md = eng.metadata

    def _pct(v):
        return f"{v*100:.1f} %" if isinstance(v, (int, float)) else "n/d"
    # v67: la precisión GLOBAL ya no es comparable con versiones anteriores
    # (el conjunto de validación incluye ahora previas, Challenger, WTA 125 e
    # ITF, mucho menos predecibles). Se muestran las dos por separado.
    _uni = md.get('validacion_por_universo') or {}
    _princ = (_uni.get('circuito_principal') or {}).get('precision')
    _nuevas = (_uni.get('categorias_nuevas') or {}).get('precision')
    st.caption(
        f"Entrenado con {md.get('n_partidos')} partidos "
        f"({eng.circuito.upper()} · {md.get('fuente_datos', 'Kaggle')}) · "
        f"precisión **{_pct(_princ) if _princ else _pct(md.get('precision_validacion'))}** "
        f"en el circuito principal"
        + (f" y {_pct(_nuevas)} en categorías inferiores" if _nuevas else "")
        + f" · ranking {_pct(md.get('precision_linea_base_elo'))}, "
        f"mercado {_pct(md.get('precision_mercado'))}. "
        f"{len(eng.jugadores)} jugadores cubiertos.")

    # v106 — EV+ AUTOMÁTICO TAMBIÉN EN TENIS.
    #
    # Va en un desplegable y no en una pestaña a propósito: esta vista es un
    # flujo largo (calendario → jugadores → 19 mercados → parlays) y partirlo
    # en pestañas obligaría a reindentar doscientas líneas por un cambio de
    # colocación. El panel es EL MISMO que el de MLB, NBA y KBO.
    #
    # Cubre los dos circuitos a la vez —el barrido de tenis no separa ATP de
    # WTA— así que no depende del selector de arriba.
    #
    # v114 — PERO SE PINTA AL FINAL, NO AQUÍ.
    #
    # Un expander CERRADO no ahorra trabajo: Streamlit ejecuta su cuerpo
    # siempre, y sólo decide si lo enseña. Con el panel en esta posición, el
    # barrido de cuotas de tenis (ATP + WTA + challengers + ITF, la lista más
    # larga de los cuatro deportes) corría ANTES del calendario, de los
    # selectores de jugador y de los 19 mercados — así que la vista entera
    # esperaba a la red para pintar su primera línea útil.
    #
    # El usuario lo describió exacto: «cuando selecciono tenis no me carga
    # todo el contenido hasta que hago click en cuota automática». El click no
    # arreglaba nada: disparaba un rerun que ya encontraba el caché de 15
    # minutos caliente. Es la MISMA causa que la v91 documentó y corrigió en
    # Apuestas del Día con las combinadas.
    #
    # Aquí se define y se llama al final de la función (ver el pie). El trabajo
    # total es el mismo; lo que cambia es que el calendario y las estadísticas
    # —que es a lo que se viene— salen sin esperar a las cuotas.
    def _panel_ev_tenis():
        with st.expander("💰 EV+ automático — ATP y WTA con cuota real",
                         expanded=False):
            import alpha_finder as _af
            render_ev_automatico(
                'Tenis', _af._picks_tenis,
                nota="Cubre ATP y WTA a la vez, incluidos challengers e ITF. "
                     "El canal de «valor de mercado» (una casa pagando por "
                     "encima del precio justo de Pinnacle) está validado en "
                     "WTA y **no** en ATP: los de ATP salen sólo por modelo.")

    # ---- v67: próximos partidos desde ESPN, por COMPETICIÓN ----------------
    # Antes: solo los partidos de hoy que apareciesen en la fuente de cuotas de
    # Betexplorer, y hacía falta pulsar «Cargar». Ahora: el calendario completo
    # de ESPN (que se refresca solo cada 20 min), filtrable por competición, y
    # al elegir el partido las estadísticas salen directamente.
    _circ = 'wta' if circuito.startswith('WTA') else 'atp'
    _ranks = {j: (d.get('rank') or 0)
              for j, d in (eng.estado.get('jugadores') or {}).items()}
    _ranks = {j: r for j, r in _ranks.items() if r}

    @st.cache_data(ttl=20 * 60, show_spinner="Buscando próximos partidos…")
    def _fixtures_tenis(circ, ranks_firma):
        import tenis_fuentes as _tf
        return _tf.fixtures_tenis(circ, dias=10, rankings=_ranks)

    try:
        import tenis_fuentes as _tf
        _fx_t = _fixtures_tenis(_circ, len(_ranks))
    except Exception as _e:
        _fx_t, _tf = [], None
        st.caption(f"📅 Calendario no disponible ahora ({type(_e).__name__}).")

    _sel_fx = None
    if _fx_t and _tf is not None:
        _cats_presentes = {f['categoria'] for f in _fx_t}
        _opciones_cat = ['Todas las competiciones']
        _mapa_cat = {}
        for _grupo, _claves in _tf.GRUPOS_UI:
            for _c in _claves:
                if _c in _cats_presentes:
                    _et = f"{_grupo} — {_tf.CATEGORIAS[_c]}"
                    _opciones_cat.append(_et)
                    _mapa_cat[_et] = _c
        cf1, cf2 = st.columns([1, 2])
        _cat_sel = cf1.selectbox("🏆 Competición", _opciones_cat, key='ten_cat')
        _clave_cat = _mapa_cat.get(_cat_sel)
        _lista = [f for f in _fx_t
                  if _clave_cat is None or f['categoria'] == _clave_cat]
        _lista = [f for f in _lista
                  if f['p1'] in eng.jugadores and f['p2'] in eng.jugadores]
        if _lista:
            def _etq(f):
                _fase = ' · previa' if f['fase'] == 'clasificacion' else ''
                # v106 — la hora que trae `tenis_fuentes` es UTC (sale de la
                # fecha de ESPN, ya sin zona). Se enseñaba tal cual, así que
                # un partido a las 18:00 de México aparecía como «00:00» del
                # día siguiente. Se convierte a CDMX, con su fecha local.
                _p = _horario.partes(f"{f['fecha']} {f['hora']}:00")
                _cuando = f"{_p[0]} {_p[1]}" if _p else f"{f['fecha']} {f['hora']}"
                return (f"{_cuando} · {f['p1']} vs {f['p2']} "
                        f"— {f['torneo']}{_fase}")
            _etiquetas = ['(elegir jugadores manualmente)'] + [_etq(f) for f in _lista]
            _elegido = cf2.selectbox(
                f"📅 Próximos partidos ({len(_lista)})", _etiquetas, key='ten_fx_sel',
                help="Hora de Ciudad de México. Se actualiza solo cada 20 "
                     "minutos desde ESPN. Al elegir un partido, las "
                     "estadísticas aparecen abajo — sin botones.")
            if _elegido != '(elegir jugadores manualmente)':
                _sel_fx = _lista[_etiquetas.index(_elegido) - 1]
        else:
            cf2.caption("Sin partidos de esta competición con los dos jugadores "
                        "en el modelo.")
    elif _fx_t is not None:
        st.caption("📅 No hay partidos programados en los próximos 10 días.")

    # v67: SIN botón «Cargar». Si hay partido elegido, sus datos mandan sobre
    # los selectores manuales (que se muestran igualmente, deshabilitados).
    c1, c2, c3 = st.columns(3)
    if _sel_fx:
        p1, p2 = _sel_fx['p1'], _sel_fx['p2']
        c1.text_input("Jugador 1", p1, disabled=True, key='ten_1_fx')
        c2.text_input("Jugador 2", p2, disabled=True, key='ten_2_fx')
        _sup_auto = None
        try:
            _sup_auto = _tf._superficie_espn(_sel_fx['torneo'],
                                             pd.Timestamp(_sel_fx['fecha']), {})
        except Exception:
            pass
        _sups = ['Hard', 'Clay', 'Grass']
        sup = c3.selectbox("Superficie", _sups,
                           index=_sups.index(_sup_auto) if _sup_auto in _sups else 0,
                           key='ten_s_fx',
                           help="Deducida del torneo; puedes corregirla.")
        best_of = 5 if int(_sel_fx.get('best_of') or 3) >= 5 else 3
        indoor = False
        st.caption(f"🎾 **{_sel_fx['torneo']}** · {_sel_fx['ronda']} · "
                   f"al mejor de {best_of} sets"
                   + (f" · categoría: {_tf.CATEGORIAS.get(_sel_fx['categoria'], '—')}"
                      if _tf else ''))
    else:
        p1 = c1.selectbox("Jugador 1", eng.jugadores, key='ten_1')
        p2 = c2.selectbox("Jugador 2", eng.jugadores, index=1, key='ten_2')
        sup = c3.selectbox("Superficie", ['Hard', 'Clay', 'Grass'], key='ten_s')
        c4, c5 = st.columns(2)
        indoor = c4.checkbox("Pista cubierta (indoor)", key='ten_in')
        formato = c5.radio("Formato", ['Al mejor de 3 sets',
                                       'Al mejor de 5 sets (Grand Slam)'],
                           key='ten_bo', horizontal=False)
        best_of = 5 if formato.startswith('Al mejor de 5') else 3
    if p1 != p2:
        pred = eng.predecir(p1, p2, surface=sup, indoor=indoor)
        if 'error' in pred:
            st.warning(pred['error'])
        else:
            m1, m2 = st.columns(2)
            m1.metric(f"Gana {p1}", f"{pred['prob_home']*100:.0f} %",
                      f"cuota justa {1/max(pred['prob_home'],1e-6):.2f}")
            m2.metric(f"Gana {p2}", f"{pred['prob_away']*100:.0f} %",
                      f"cuota justa {1/max(pred['prob_away'],1e-6):.2f}")
            st.caption(f"En {sup.lower()}, el modelo favorece a "
                       f"**{p1 if pred['prob_home']>=0.5 else p2}**. "
                       "El mercado de tenis (cuotas de cierre) es más preciso "
                       "que nuestro modelo — herramienta de análisis, no de EV.")
            # v51: PLANTILLA COMPLETA de mercados de tenis (la que pidió el
            # usuario): ganador, primer set, marcador exacto, hándicap de sets
            # y juegos, totales de juegos, gana exactamente 1 set, doble
            # resultado. Todo derivado del modelo con cuota justa (1/prob).
            pl = eng.plantilla(p1, p2, surface=sup, best_of=best_of, indoor=indoor)
            campos = list(pl.get('campos', []))
            # v51.2: los mercados de SETS se calculan aquí (script principal,
            # siempre fresco) y se fusionan por id, de modo que aparezcan aunque
            # Streamlit Cloud sirva una versión cacheada del módulo del motor.
            ids = {c.get('id') for c in campos}
            for c in _mercados_sets_tenis(p1, p2, pred['prob_home'], best_of):
                if c['id'] not in ids:
                    campos.append(c)
            if campos:
                st.divider()
                st.subheader("📋 Plantilla completa de mercados (para parlays)")
                if pl.get('total_juegos_estimado'):
                    st.caption(f"Total de juegos estimado: "
                               f"**{pl['total_juegos_estimado']}** · "
                               "todas las cuotas son justas (1/probabilidad).")
                import pandas as _pd
                # agrupación por tipo de mercado para legibilidad
                def _grupo(c):
                    i = c.get('id', '')
                    if i.startswith('ml_'):
                        return '🏆 Ganador'
                    if i.startswith('set1_'):
                        return '1️⃣ Primer set'
                    if i.startswith('juegos_'):
                        return '🎾 Total de juegos'
                    if i.startswith('hand_'):
                        return '➕ Hándicap de juegos'
                    if i.startswith('hset_'):
                        return '➕ Hándicap de sets'
                    if i.startswith('dr_'):
                        return '🔗 Doble resultado (1er set / partido)'
                    return '📐 Sets (marcador y especiales)'
                orden_grupos = ['🏆 Ganador', '1️⃣ Primer set',
                                '📐 Sets (marcador y especiales)',
                                '➕ Hándicap de sets', '🎾 Total de juegos',
                                '➕ Hándicap de juegos',
                                '🔗 Doble resultado (1er set / partido)']
                for g in orden_grupos:
                    filas = [{'Mercado': c['etiqueta'],
                              'Probabilidad': f"{c['valor']:.0f}%",
                              'Cuota justa': round(100 / max(c['valor'], 1e-6), 2)}
                             for c in campos if _grupo(c) == g]
                    if not filas:
                        continue
                    st.markdown(f"**{g}**")
                    st.dataframe(_pd.DataFrame(filas), hide_index=True,
                                 width='stretch')
                if pl.get('excluidos'):
                    with st.expander("¿Por qué no están todos los mercados?"):
                        st.caption("Estos mercados exigen datos de saque/resto "
                                   "o cadenas de Markov que esta fuente gratuita "
                                   "no publica, así que NO se inventan:")
                        for e in pl['excluidos']:
                            st.caption(f"• {e}")

            # ---- v67: PARLAY COMBINADO + TELEGRAM ------------------------
            # El tenis era el único deporte de la app sin combinadas: su
            # plantilla publicaba `campos` pero no `secciones`, que es lo que
            # lee match_parlay. Con eso resuelto, reutiliza EXACTAMENTE el
            # mismo componente que fútbol y MLB (incluido el envío a Telegram).
            st.divider()
            _eng_ctx = eng.con_contexto(
                surface=sup, best_of=best_of, indoor=indoor,
                categoria=(_sel_fx or {}).get('categoria'),
                fase=(_sel_fx or {}).get('fase'))
            # v114: cara a cara, ranking/ELO por superficie y forma — el
            # equivalente en tenis del panel de equipos del fútbol.
            try:
                render_panel_tenis(eng, p1, p2, sup,
                                   key=f'tenis_{eng.circuito}')
            except Exception as e:
                st.caption(f"Panel de jugadores no disponible "
                           f"({type(e).__name__}).")
            st.divider()
            render_parlay_partido(_eng_ctx, p1, p2, key=f'tenis_{eng.circuito}')
            render_rendimiento(key=f'tenis_{eng.circuito}')

    # v114 — el EV+ automático, al final: es lo único de esta vista que
    # depende de la red, y arriba retrasaba todo lo demás (ver su definición).
    # Va fuera del `if p1 != p2` a propósito: cubre los dos circuitos enteros,
    # no el partido en pantalla, así que tiene que salir aunque no haya un
    # cruce válido elegido.
    st.divider()
    _panel_ev_tenis()


_clave_comp = COMPETENCIAS[competencia_sel]
# v141 — VOLVER A APUESTAS DEL DÍA, SIN EL BOTÓN DEL NAVEGADOR.
#
# Se llega a una ficha desde la lista del día —ahora con un botón «Ver» por
# tarjeta— y no había forma de deshacer ese paso dentro de la aplicación: el
# retroceso del navegador en Streamlit no restaura el estado, así que el
# usuario acababa recargando y perdiendo el barrido.
#
# Va ARRIBA de todo, antes de pintar la vista, para que no haya que bajar
# hasta el final para volver. Sólo aparece fuera de la propia pantalla del
# día, donde no tendría sentido.
if _clave_comp != 'alpha':
    if st.button('⬅ Volver a Apuestas del Día', key='volver_alpha'):
        # SÓLO se apunta la intención. Escribir aquí `competencia` lanza
        # «cannot be modified after the widget is instantiated», porque el
        # selector ya existe cuando se pulsa este botón. Es la misma razón por
        # la que `navegacion.marcar` no toca claves de widget: la bandera se
        # consume al principio del script siguiente, antes de crear el
        # desplegable. Lo cazó la validación de render.
        st.session_state['_volver_a_alpha'] = True
        st.rerun()

if _clave_comp == 'mlb_deporte':
    render_mlb()
    st.stop()
if _clave_comp == 'kbo_deporte':                          # v97
    render_kbo()
    st.stop()
if _clave_comp == 'nba_deporte':
    render_nba()
    st.stop()
if _clave_comp == 'tennis_deporte':
    render_tennis()
    st.stop()
if _clave_comp == 'nfl_deporte':                          # v131
    render_nfl()
    st.stop()
if _clave_comp == 'alpha':
    render_alpha_finder()
    st.stop()
if _clave_comp != 'mundial':
    render_liga_club(_clave_comp, NOMBRES_LIGAS[_clave_comp])
    st.stop()

if not MOTOR.listo:
    st.error(
        f"❌ **El motor de predicción no pudo inicializarse.**\n\n"
        f"Detalle: `{MOTOR.error}`\n\n"
        f"Asegúrate de haber ejecutado, en este orden:\n"
        f"```bash\npython pipeline_mundial.py\npython train_tda_model.py\n```"
    )
    st.stop()

# ---- Transparencia: procedencia y FRESCURA de los datos ---------------------
# v89 — SE RETIRA el botón «Actualizar datos ahora»: lanzaba pipeline_mundial
# en un subprocess de hasta 30 minutos DENTRO del proceso de Streamlit y
# después hacía `st.cache_data.clear()` + `st.cache_resource.clear()`, que son
# GLOBALES al proceso — exactamente el patrón que la v86 identificó como causa
# de las caídas con varios usuarios (borra también los cerrojos internos).
# La actualización de datos vive en la tarea diaria (actualizacion_diaria.bat
# en local, retrain_leagues.yml en CI), donde siempre debió estar.
# v115 — LOS AVISOS DE CABECERA, EN UNA LÍNEA Y PLEGADOS.
#
# Eran tres bloques de colores que ocupaban media pantalla antes de que
# apareciera nada útil, y dos de ellos hablaban del Mundial 2026 («incluyen
# partidos de octavos», la calibración con StatsBomb). Toda esa información
# sigue disponible —es honesta y hay que poder consultarla— pero como una
# línea con la frescura de los datos y un desplegable con el detalle.
col_banner = st.container()
with col_banner:
    try:
        antiguedad = (pd.Timestamp.today().normalize()
                      - pd.Timestamp(MOTOR.generado)).days
    except Exception:
        antiguedad = None
    _sem = ('🟢' if antiguedad is not None and antiguedad < 1
            else '🟡' if antiguedad is not None and antiguedad <= 7 else '⏰')
    st.caption(
        f"{_sem} Datos al **{MOTOR.fecha_estado}**"
        + (f" · generados hace {antiguedad} día(s)" if antiguedad else '')
        + f" · {len(MOTOR.equipos)} selecciones cubiertas"
        + " · la tarea diaria los refresca sola")
    with st.expander("ℹ️ De dónde salen estos datos y qué precisión tienen"):
        if MOTOR.fuente == 'real_hybrid':
            st.markdown(
                f"- **Resultados reales** hasta el {MOTOR.fecha_estado} — "
                f"{MOTOR.fuente_detalle}.")
            st.markdown(
                "- Las métricas avanzadas (remates, posesión) se **estiman** "
                "con un modelo calibrado con datos reales de StatsBomb: no son "
                "observaciones, son estimaciones, y por eso se dicen aparte.")
        _obj = MOTOR.metadata.get('objetivo_estricto', {}) or {}
        if MOTOR.metadata.get('deploy_ready') and not _obj.get('cumplido', False):
            st.markdown(
                f"- **Transparencia**: el objetivo estricto (precisión ≥ "
                f"{_obj.get('precision', 0.62)*100:.0f} % y log-loss ≤ "
                f"{_obj.get('log_loss', 0.85)}) todavía no se alcanza sobre "
                f"partidos reales — va por "
                f"{MOTOR.metadata.get('precision_validacion', 0)*100:.1f} % / "
                f"{MOTOR.metadata.get('log_loss_validacion', 0):.3f}. El techo "
                f"teórico del 1X2 internacional ronda el 60-65 %, así que el "
                f"objetivo es exigente a propósito.")

if MOTOR.fuente == 'synthetic':
    st.warning(
        "⚠️ **Datos estimados – precisión limitada.** Las fuentes reales no "
        "estaban disponibles, así que las estadísticas provienen del generador "
        "de respaldo (con correlaciones realistas, pero no reales)."
    )
if not MOTOR.metadata.get('deploy_ready', False):
    st.error(
        f"🚫 **Modelo en modo referencia:** su precisión de backtesting "
        f"({MOTOR.metadata.get('precision_validacion', 0)*100:.1f} %) no alcanzó "
        f"el umbral de despliegue del 55 %. Tómalo solo como orientación."
    )
# (la nota de transparencia se ha movido al desplegable de cabecera, v115)

# ===========================================================================
# SELECCIÓN DEL PARTIDO
# ===========================================================================
# v115 — ESTA VISTA YA NO ES «EL MUNDIAL».
#
# El torneo terminó y la vista quedó con su ropa puesta: se titulaba «¿Quién
# gana? — Predictor deportivo», hablaba de la calibración con StatsBomb del
# Mundial y ofrecía «Fase de grupos» y «Estadio (MetLife por defecto)» para un
# amistoso en Tokio. El usuario lo pidió dos veces seguidas.
#
# Lo que es de verdad: un predictor de SELECCIONES —200 de ellas— que cubre
# amistosos, Nations League, clasificatorias y torneos continentales de los dos
# sexos. Los controles del Mundial siguen existiendo porque el modelo los usa
# (el árbitro ajusta tarjetas, la altitud ajusta el xG), pero pasan a un
# desplegable de ajustes finos en vez de presidir la pantalla.
_cabecera(
    'Partidos Internacionales',
    f'Enfrenta a cualquiera de las {len(MOTOR.equipos)} selecciones del '
    f'histórico: amistosos, Nations League, clasificatorias y torneos '
    f'continentales, masculinos y femeninos.',
    chips=[(f"{len(MOTOR.equipos)} selecciones", 'info'),
           (f"acierta {MOTOR.metadata.get('precision_validacion', 0)*100:.0f} %",
            'ok')],
    icono='🌍')
if _ayuda is not None:
    _ayuda.render(st, 'selecciones')
st.caption(
    f"Enfrenta a **cualquiera de las {len(MOTOR.equipos)} selecciones "
    f"nacionales** del histórico: amistosos, Nations League, clasificatorias y "
    f"torneos continentales, masculinos y femeninos · "
    f"Precisión backtesting **{MOTOR.metadata.get('precision_validacion', 0)*100:.1f} %** "
    f"(el techo del 1X2 internacional ronda el 60-65 %)"
)

col_sel1, col_sel2, col_sel3 = st.columns([2, 1, 1])
with col_sel1:
    opciones_fixture = ["(elegir equipos manualmente)"]
    fixture_map = {}
    # v60: el Mundial 2026 ya terminó. La vista pasa a los PRÓXIMOS PARTIDOS
    # REALES de selecciones (amistosos, Nations League y clasificatorias) desde
    # ESPN, que se refrescan solos. Si ESPN no devuelve nada se cae al
    # calendario oficial guardado (degradación honesta).
    _sel_fx = []
    try:
        import fixtures_espn as _fx_mod
        _sel_fx = _fx_mod.fixtures_selecciones()
    except Exception:
        _sel_fx = []
    import name_mapper as _nm_int
    # ESPN publica los nombres en INGLÉS ("Netherlands", "Germany"), así que el
    # catálogo se construye con TEAM_NAMES_EN (mapear contra los nombres en
    # español dejaba fuera casi todo).
    # v66: con 200 selecciones el catálogo incluye además los ALIAS de cada una
    # ("Czechia", "Türkiye", "Bosnia-Herzegovina"...). El alias da coincidencia
    # EXACTA y evita que el fuzzy confunda pares peligrosos que antes no
    # coexistían: Congo / RD Congo, Guinea / Guinea Ecuatorial / Guinea-Bisáu,
    # Irlanda / Irlanda del Norte, Corea del Sur / Corea del Norte.
    from config import TEAM_NAMES_EN as _EN, TEAM_ALIAS as _ALIAS
    _cat_int = {}
    for _c in MOTOR.equipos:
        _cat_int[_EN.get(_c, _c)] = _c
        for _al in _ALIAS.get(_c, []):
            _cat_int.setdefault(_al, _c)
        _cat_int.setdefault(NOMBRES_PAIS.get(_c, _c), _c)
    # v114 — SELECTOR DE COMPETICIÓN, como en las ligas de clubes.
    #
    # El usuario lo pidió: «en partidos internacionales deberá haber la parte
    # de seleccionar copa y que se extraigan automáticamente los próximos
    # partidos según la copa, como en las demás ligas».
    #
    # Las competiciones se sacan de los propios partidos encontrados, no de una
    # lista fija: así el desplegable enseña siempre lo que HAY, y no promete
    # una Copa Oro que no se juega hasta dentro de un año.
    _comps = sorted({str(f.get('torneo') or '—') for f in _sel_fx})
    if len(_comps) > 1:
        _comp_sel = st.selectbox(
            f"🏆 Competición de selecciones ({len(_comps)})",
            ['Todas las competiciones'] + _comps, key='sel_comp_int',
            help="Amistosos, Nations League, clasificatorias, torneos "
                 "continentales y las competiciones femeninas. Sale de ESPN y "
                 "del tablón de cuotas, y se actualiza solo.")
        if _comp_sel != 'Todas las competiciones':
            _sel_fx = [f for f in _sel_fx if str(f.get('torneo')) == _comp_sel]
    _n_int = 0
    _sin_enlazar = []
    for f in _sel_fx:
        _h = _nm_int.mapear(f['home'], _cat_int.keys(), contexto='selecciones')
        _a = _nm_int.mapear(f['away'], _cat_int.keys(), contexto='selecciones')
        if not (_h and _a) or _h == _a:
            _sin_enlazar.append(f"{f['home']} vs {f['away']}")
            continue
        etiqueta = (f"{f['fecha']} · {f['home']} vs {f['away']} — {f['torneo']}"
                    + ("  · con cuota abierta" if f.get('origen') == 'tablon'
                       else ""))
        opciones_fixture.append(etiqueta)
        fixture_map[etiqueta] = (_cat_int[_h], _cat_int[_a])
        _n_int += 1
    # v121 — SE ACABÓ EL RESPALDO AL CALENDARIO DEL MUNDIAL.
    #
    # Aquí estaba el motivo de que el usuario siguiera viendo «la plantilla del
    # Mundial» después de pedir tres veces que desapareciera: cuando no había
    # partidos de selecciones —que es lo normal fuera de las fechas FIFA, y
    # SIEMPRE en producción, porque ESPN devuelve 403 a las IPs de centro de
    # datos— esta rama rellenaba el desplegable con el fixture del Mundial
    # 2026, un torneo terminado. El resto de la vista funcionaba, así que
    # parecía que no se había cambiado nada.
    #
    # Una lista vacía es la respuesta correcta y se dice con todas las letras.
    # Los dos selectores de equipo siguen ahí: se puede analizar cualquier
    # cruce de las 200 selecciones aunque hoy no haya calendario.
    if _n_int == 0:
        st.info(
            "📅 **No hay partidos de selecciones programados ahora mismo.** "
            "Las selecciones juegan en ventanas concretas (las «fechas FIFA»), "
            "y entre ellas el calendario está vacío — no es un fallo. "
            "Mientras tanto puedes analizar cualquier cruce eligiendo los dos "
            "equipos abajo.")
    partido_fixture = st.selectbox(
        f"📅 Próximos partidos de selecciones ({_n_int})" if _n_int
        else "📅 Partido del fixture oficial (opcional)", opciones_fixture,
        help=(f"Amistosos, Nations League y clasificatorias que vienen, desde "
              f"ESPN (se actualizan solos). {_n_int} de {len(_sel_fx)} "
              f"programados enlazan con el modelo.") if _n_int else None)
    if _sin_enlazar:
        with st.expander(f"ℹ️ {len(_sin_enlazar)} partidos programados que el "
                         f"modelo aún no cubre"):
            st.caption("Selecciones con menos de 100 partidos en el histórico "
                       "desde 1990: no hay muestra suficiente para predecirlas "
                       "con la misma exigencia que al resto.")
            st.write(" · ".join(_sin_enlazar))

equipos_disponibles = MOTOR.equipos
if partido_fixture != "(elegir equipos manualmente)":
    home, away = fixture_map[partido_fixture]
    with col_sel2:
        st.text_input("Local", NOMBRES_PAIS.get(home, home), disabled=True)
    with col_sel3:
        st.text_input("Visitante", NOMBRES_PAIS.get(away, away), disabled=True)
else:
    with col_sel2:
        home = st.selectbox("🏠 Local", equipos_disponibles,
                            index=equipos_disponibles.index('MEX') if 'MEX' in equipos_disponibles else 0,
                            format_func=lambda c: NOMBRES_PAIS.get(c, c))
    with col_sel3:
        visitantes = [e for e in equipos_disponibles if e != home]
        away = st.selectbox("✈️ Visitante", visitantes,
                            index=visitantes.index('ECU') if 'ECU' in visitantes else 0,
                            format_func=lambda c: NOMBRES_PAIS.get(c, c))

# ---- v115: AJUSTES FINOS, PLEGADOS -----------------------------------------
#
# Árbitro, fase y estadio se quedan porque el modelo los usa de verdad: el
# árbitro mueve tarjetas y penaltis, la fase cambia cómo se juega y la altitud
# ajusta el xG por aclimatación. Lo que no tiene sentido es que presidan la
# pantalla de un amistoso en Tokio con «Fase de grupos» y «MetLife» por
# defecto, como si el Mundial siguiera en marcha.
#
# Van a un desplegable cerrado, con los valores neutros por defecto. Quien
# quiera afinar los tiene; quien sólo quiera el pronóstico ya no los ve.
with st.expander("⚙️ Ajustes finos del partido (árbitro, fase, estadio)",
                 expanded=False):
    st.caption("Opcionales. El modelo funciona sin ellos: si no los tocas usa "
               "el promedio FIFA, fase regular y altitud neutra. Los estadios "
               "de la lista son los del Mundial 2026 y sólo aportan su "
               "**altitud** — útil si el partido se juega en uno de ellos o a "
               "una altura parecida.")
    _ca1, _ca2 = st.columns([3, 1])
    with _ca1:
        opciones_arbitro = ["(promedio FIFA, sin asignar)"] + sorted(ARBITROS.keys())
        arbitro_sel = st.selectbox(
            "👨‍⚖️ Árbitro designado — ajusta tarjetas, rojas y penaltis",
            opciones_arbitro,
            format_func=lambda n: n if n.startswith("(") else
            f"{n} ({ARBITROS[n]['pais']}, {ARBITROS[n]['criterio'].lower()}, {ARBITROS[n]['ama_p90']:.1f} am/90)",
        )
    with _ca2:
        fase_sel = st.selectbox("🏆 Tipo de partido",
                                ["Fase regular / amistoso", "Eliminatoria"],
                                help="En eliminatoria se juega distinto: menos "
                                     "goles y más cautela.")
    opciones_estadio = ["(altitud neutra)"] + list(ESTADIOS_MUNDIAL.keys())
    estadio_sel = st.selectbox(
        "🏟️ Estadio — la altitud ajusta el xG por aclimatación",
        opciones_estadio,
        format_func=lambda k: k if k.startswith("(") else
        f"{ESTADIOS_MUNDIAL[k]['nombre']} — {ESTADIOS_MUNDIAL[k]['ciudad']} · {ESTADIOS_MUNDIAL[k]['altitud']} msnm",
    )
arbitro = None if arbitro_sel.startswith("(") else arbitro_sel
fase = 'grupos' if fase_sel.startswith("Fase regular") else 'eliminatoria'
estadio = None if estadio_sel.startswith("(") else estadio_sel

pred = prediccion_cacheada(id(MOTOR), home, away, arbitro, fase, estadio)
if 'error' in pred:
    st.error(f"❌ {pred['error']}")
    st.stop()

p = pred['prediction']
nombre_local = NOMBRES_PAIS.get(home, home)
nombre_visit = NOMBRES_PAIS.get(away, away)

# v119 — AVISO DE CATEGORÍA: EL MODELO ES DE SELECCIONES ABSOLUTAS.
#
# El usuario lo señaló y tiene razón: «hay partidos sub-20 donde no están las
# mismas plantillas que en la alta». El histórico con el que se entrenó este
# motor es de selecciones ABSOLUTAS; un Brasil sub-20 o un España femenino
# comparten bandera pero no comparten jugadoras, ni nivel, ni resultados. Usar
# el ELO de la absoluta para predecirlos no es una aproximación: es otro
# equipo.
#
# No se bloquea la predicción —puede servir de orientación— pero se dice con
# claridad y arriba del todo, no en letra pequeña.
try:
    import cuotas_multi as _cm_cat
    _torneo_sel = ''
    if partido_fixture != "(elegir equipos manualmente)":
        _torneo_sel = str(partido_fixture)
    _cat_sel = _cm_cat.categoria_partido(nombre_local, nombre_visit,
                                         _torneo_sel)
    if _cat_sel:
        _que = []
        if 'fem' in _cat_sel:
            _que.append('**femenino**')
        if 'filial' in _cat_sel:
            _que.append('de **categoría inferior** (sub-20, sub-17, olímpico…)')
        st.warning(
            "⚠️ Este partido parece " + " y ".join(_que) + ", y el modelo está "
            "entrenado con el histórico de las selecciones **absolutas "
            "masculinas**. Comparten bandera pero no comparten plantilla, "
            "nivel ni resultados: toma el pronóstico como una orientación muy "
            "floja, no como una probabilidad medida. El historial y las cuotas "
            "de abajo sí son de este partido.")
except Exception:
    pass

tab_rapida, tab_plantilla = st.tabs(
    ["⚡ Resumen del partido", "📋 Análisis completo (editable)"]
)

# ===========================================================================
# PESTAÑA 1: VISTA RÁPIDA
# ===========================================================================
with tab_rapida:
    # v122 — LA RESPUESTA, EN FORMA DE RESPUESTA.
    #
    # Esto eran cuatro `### ` seguidos: ganador, marcador, probabilidades y
    # factor decisivo, los cuatro del mismo tamaño y sin nada que distinguiera
    # el dato de la etiqueta. Con una barra proporcional del 1X2 no hace falta
    # comparar tres porcentajes mentalmente, y las tres cifras que deciden
    # (ganador, marcador, confianza) van donde se ven.
    if _estilo is not None:
        _pinta(_estilo.cabecera_partido(
            nombre_local, nombre_visit,
            [f"Ganador más probable: {p['winner']}",
             f"Marcador: {p['most_likely_score']}"]))
        _pinta(_estilo.barra_1x2(
            p['probabilities']['home'], p['probabilities']['draw'],
            p['probabilities']['away'], nombre_local, nombre_visit))
        _pinta(_estilo.kpis([
            {'valor': p['winner'], 'etiqueta': 'Ganador más probable',
             'tono': 'ok', 'sub': f"confianza {p['confidence']*100:.0f} %"},
            {'valor': p['most_likely_score'], 'etiqueta': 'Marcador',
             'tono': 'azul',
             'sub': f"{p['score_probability']*100:.0f} % de probabilidad"},
            {'valor': f"{p['probabilities']['home']*100:.0f} %",
             'etiqueta': nombre_local, 'tono': 'info'},
            {'valor': f"{p['probabilities']['draw']*100:.0f} %",
             'etiqueta': 'Empate', 'tono': 'info'},
            {'valor': f"{p['probabilities']['away']*100:.0f} %",
             'etiqueta': nombre_visit, 'tono': 'info'},
        ]))
    else:
        st.markdown(f"### 🏆 Ganador más probable: **{p['winner']}** "
                    f"(con un {p['confidence']*100:.0f} % de confianza)")
        st.markdown(f"### ⚽ Marcador más probable: **{p['most_likely_score']}** "
                    f"({p['score_probability']*100:.0f} % de probabilidad)")
        st.markdown(f"### 📊 Probabilidades: {nombre_local} "
                    f"**{p['probabilities']['home']*100:.0f} %** · "
                    f"Empate **{p['probabilities']['draw']*100:.0f} %** · "
                    f"{nombre_visit} **{p['probabilities']['away']*100:.0f} %**")
    render_comentario(pred, nombre_local, nombre_visit)
    st.markdown(f"### 🔥 Factor decisivo: *{pred['decisive_factor']}*")

    arb = pred['referee']
    tarj = pred['cards']
    pen = pred['penalties']
    st.markdown(
        f"##### 👨‍⚖️ {arb['nombre']} ({arb['criterio'].lower()}) · "
        f"🟨 {tarj['total_tarjetas']:.1f} tarjetas esperadas "
        f"({nombre_local} {tarj['amarillas_local']:.1f} · {nombre_visit} {tarj['amarillas_visitante']:.1f}) · "
        f"🟥 {tarj['rojas_local'] + tarj['rojas_visitante']:.2f} rojas · "
        f"⚪ {pen['prob_penal_en_partido']*100:.0f} % de que haya penalti"
    )
    det_alt = pred.get('altitude', {})
    if det_alt.get('altitud_sede', 0) > 1000:
        st.markdown(
            f"##### ⛰️ Sede a {det_alt['altitud_sede']:.0f} msnm · "
            f"{nombre_local}: {nivel_aclimatacion(home)} (xG ×{det_alt['factor_xg_local']:.2f}) · "
            f"{nombre_visit}: {nivel_aclimatacion(away)} (xG ×{det_alt['factor_xg_visitante']:.2f})"
        )

    # Monitor de transparencia: qué cambió desde la consulta anterior de este cruce
    monitor = pred.get('monitor_cambios') if ES_PRO else None
    if monitor and monitor.get('cambios'):
        pa = monitor['anterior']['probs']
        st.caption(
            f"📊 **Desde tu consulta anterior** ({monitor['anterior']['fecha']}, datos al "
            f"{monitor['anterior']['estado_al']}): probabilidades "
            f"{pa[0]*100:.0f}/{pa[1]*100:.0f}/{pa[2]*100:.0f} % → "
            f"{pred['prediction']['probabilities']['home']*100:.0f}/"
            f"{pred['prediction']['probabilities']['draw']*100:.0f}/"
            f"{pred['prediction']['probabilities']['away']*100:.0f} %. "
            f"Features que más variaron: "
            + " · ".join(f"`{c['feature']}` {c['antes']}→{c['ahora']}" for c in monitor['cambios'])
        )
    elif monitor is not None and not monitor.get('cambios'):
        st.caption("📊 Sin cambios en las features de este cruce desde tu consulta anterior.")

    st.divider()
    col_g1, col_g2, col_g3 = st.columns(3)

    with col_g1:
        st.subheader("📊 Probabilidad de cada resultado")
        fig_barras = go.Figure(go.Bar(
            x=[f"Gana {nombre_local}", "Empate", f"Gana {nombre_visit}"],
            y=[p['probabilities']['home'] * 100,
               p['probabilities']['draw'] * 100,
               p['probabilities']['away'] * 100],
            marker_color=[COLORES['local'], COLORES['empate'], COLORES['visitante']],
            text=[f"{p['probabilities']['home']*100:.0f} %",
                  f"{p['probabilities']['draw']*100:.0f} %",
                  f"{p['probabilities']['away']*100:.0f} %"],
            textposition='outside',
        ))
        fig_barras.update_layout(yaxis_title="%", yaxis_range=[0, 100],
                                 margin=dict(l=0, r=0, t=10, b=0), height=340)
        st.plotly_chart(fig_barras, width='stretch')

    with col_g2:
        st.subheader("🎯 Marcadores exactos (calor)")
        matriz = np.array(pred['score_matrix'])
        fig_heat = go.Figure(go.Heatmap(
            z=matriz * 100,
            x=[str(i) for i in range(matriz.shape[1])],
            y=[str(i) for i in range(matriz.shape[0])],
            colorscale='YlOrRd',
            hovertemplate=(f"{nombre_local} %{{y}} - %{{x}} {nombre_visit}"
                           "<br>Probabilidad: %{z:.1f} %<extra></extra>"),
            colorbar=dict(title="%"),
        ))
        fig_heat.update_layout(
            xaxis_title=f"Goles de {nombre_visit}",
            yaxis_title=f"Goles de {nombre_local}",
            margin=dict(l=0, r=0, t=10, b=0), height=340,
        )
        st.plotly_chart(fig_heat, width='stretch')

    with col_g3:
        st.subheader("⏱️ Probabilidad de gol por minuto")
        timeline = pd.DataFrame(pred['timeline'])
        fig_tl = go.Figure()
        fig_tl.add_trace(go.Scatter(
            x=timeline['minuto'], y=timeline['prob_gol'] * 100,
            mode='lines', fill='tozeroy', name='Prob. de gol en ese minuto',
            line=dict(color='#e67e22', width=2),
            hovertemplate="Minuto %{x}: %{y:.2f} %<extra></extra>",
        ))
        fig_tl.add_trace(go.Scatter(
            x=timeline['minuto'], y=timeline['goles_esperados_acumulados'],
            mode='lines', name='Goles esperados acumulados', yaxis='y2',
            line=dict(color='#8e44ad', width=2, dash='dot'),
            hovertemplate="Minuto %{x}: %{y:.2f} goles<extra></extra>",
        ))
        fig_tl.update_layout(
            xaxis_title="Minuto", yaxis_title="Prob. de gol (%)",
            yaxis2=dict(title="Goles acumulados", overlaying='y', side='right'),
            legend=dict(orientation='h', y=1.12),
            margin=dict(l=0, r=0, t=10, b=0), height=340,
        )
        st.plotly_chart(fig_tl, width='stretch')

    st.divider()
    st.subheader("🧠 Lo que dicen los números (en cristiano)")
    for frase in pred['insights']:
        st.markdown(f"- {frase}")
    st.caption(f"Se esperan **{p['total_goals_expected']:.1f} goles** en total "
               f"({nombre_local}: {p['expected_goals']['home']:.1f} · "
               f"{nombre_visit}: {p['expected_goals']['away']:.1f}).")
    # v26 (§2): segunda opinión del modelo de SUPERVIVENCIA (Weibull AFT,
    # minuto del primer gol; Brier 0.236 vs 0.252 del baseline en walk-forward)
    try:
        import supervivencia_btts as _sb
        _p_btts = _sb.btts_en_vivo(MOTOR.stats_equipo(home),
                                   MOTOR.stats_equipo(away))
        if _p_btts is not None:
            st.caption(f"⏱️ **Ambos marcan (modelo de supervivencia): "
                       f"{_p_btts*100:.0f} %** — estima el minuto del primer "
                       f"gol de cada lado. Este modelo ES el "
                       "BTTS oficial de la plantilla (transición validada).")
    except Exception:
        pass

    # ---- Remates REALES por jugador (v67) -----------------------------------
    @st.cache_data(ttl=6 * 3600, show_spinner="Buscando remates por jugador…")
    def _remates_sel(codigo: str):
        import remates_jugadores as _rj
        return _rj.remates_seleccion(codigo)

    render_remates_reales(
        [(f"🏠 {nombre_local}", lambda c=home: _remates_sel(c)),
         (f"✈️ {nombre_visit}", lambda c=away: _remates_sel(c))],
        key='mundial')

    # ---- ¿Quién remata? -----------------------------------------------------
    st.divider()
    st.subheader("⚽ Goleadores de cada equipo")
    st.caption("Goles reales de los últimos 24 meses (fuente Kaggle). El xG y "
               "los remates de esta tabla son ESTIMADOS por calibración "
               "StatsBomb — los remates observados están en la tabla de arriba.")

    EJES_RADAR = ['Goles (24 meses)', 'Remates', 'Al arco', 'Goles esperados', 'Racha (últ. 5)']
    MAXIMOS_RADAR = [15.0, 4.0, 2.5, 0.8, 5.0]

    def radar_jugadores(jugadores: list, titulo: str) -> go.Figure:
        fig = go.Figure()
        for j in jugadores:
            valores = [
                min(1.0, j['goles_24m'] / MAXIMOS_RADAR[0]),
                min(1.0, j['remates_totales'] / MAXIMOS_RADAR[1]),
                min(1.0, j['remates_al_arco'] / MAXIMOS_RADAR[2]),
                min(1.0, j['goles_esperados'] / MAXIMOS_RADAR[3]),
                min(1.0, j['partidos_marcando_de_5'] / MAXIMOS_RADAR[4]),
            ]
            fig.add_trace(go.Scatterpolar(
                r=valores + [valores[0]],
                theta=EJES_RADAR + [EJES_RADAR[0]],
                fill='toself', opacity=0.45, name=j['nombre'],
            ))
        fig.update_layout(
            title=dict(text=titulo, font=dict(size=14)),
            polar=dict(radialaxis=dict(range=[0, 1], showticklabels=False)),
            legend=dict(orientation='h', y=-0.15),
            margin=dict(l=40, r=40, t=40, b=10), height=380,
        )
        return fig

    def tabla_rematadores(jugadores: list) -> pd.DataFrame:
        return pd.DataFrame([{
            'Jugador': j['nombre'],
            'Goles (24 m)': j['goles_24m'],
            'Remates/partido (est.)': j['remates_totales'],
            'Al arco (est.)': j['remates_al_arco'],
            'Prob. de marcar': f"{j['prob_marcar']*100:.0f} %",
            'Marcó en (últ. 5)': f"{j['partidos_marcando_de_5']}/5",
        } for j in jugadores])

    col_j1, col_j2 = st.columns(2)
    for col, lado, nombre_eq in [(col_j1, 'home', nombre_local), (col_j2, 'away', nombre_visit)]:
        with col:
            jugadores_lado = pred['key_players'][lado]
            emoji = '🏠' if lado == 'home' else '✈️'
            if jugadores_lado:
                st.plotly_chart(radar_jugadores(jugadores_lado, f"{emoji} {nombre_eq}"),
                                width='stretch')
                st.dataframe(tabla_rematadores(jugadores_lado),
                             width='stretch', hide_index=True)
            else:
                st.info(f"{emoji} {nombre_eq}: sin goleadores registrados en los últimos 24 meses.")

    # v20: ajuste informativo por alineación confirmada (solo si hay del día)
    try:
        import player_db
        fac = player_db.factores_para_partido(home, away)
        if fac:
            st.info(f"📋 **Alineación confirmada detectada** ({fac[2]}): factor de "
                    f"calidad de titulares — local ×{fac[0]:.2f}, visitante ×{fac[1]:.2f}. "
                    f"xG ajustado (informativo, NO altera el 1X2): "
                    f"local {pred['prediction']['expected_goals']['home']*fac[0]:.2f} · "
                    f"visitante {pred['prediction']['expected_goals']['away']*fac[1]:.2f}.")
    except Exception:
        pass

    # ---- v114: CUOTAS REALES + EV, igual que en las ligas de clubes ----------
    #
    # El usuario pidió que las selecciones tuvieran «extracción automática, EV
    # automático y todas las features que tenemos en las ligas de fútbol, como
    # en la Liga MX». Le faltaba justo esto: el calendario ya salía de ESPN
    # (ahora con 22 competiciones, no 7) pero no había ni una cuota.
    #
    # El tablón se consulta con el nombre en INGLÉS de cada selección, que es
    # como las publican las casas; el motor trabaja con códigos FIFA («MEX»).
    st.divider()
    with st.expander("💰 Cuotas reales AUTOMÁTICAS + EV", expanded=False):
        try:
            from config import TEAM_NAMES_EN as _EN_ODDS
            _h_odds = _EN_ODDS.get(home, NOMBRES_PAIS.get(home, home))
            _a_odds = _EN_ODDS.get(away, NOMBRES_PAIS.get(away, away))
            st.caption(f"Buscando **{_h_odds} vs {_a_odds}** en Pinnacle, "
                       f"Bovada, Playdoit y Unibet. Las casas abren línea de "
                       f"selecciones cuando hay fecha FIFA; fuera de esas "
                       f"ventanas es normal que no haya precio.")
            _pl_int = MOTOR.plantilla(home, away)
            _mostrar_cuotas_multi('mundial', _h_odds, _a_odds,
                                  plantilla=_pl_int)
        except Exception as e:
            st.caption(f"No se pudieron obtener las cuotas "
                       f"({type(e).__name__}: {e}).")

    # ---- 🎯 Parlay del partido en pantalla (v15) ------------------------------
    st.divider()
    render_parlay_partido(MOTOR, home, away, key='mundial')
    render_h2h_mundial(home, away)
    # v66: el comparador usa el MISMO orden que el selector principal (por
    # nombre mostrado). Antes recibía sorted(TEAMS) — con 200 selecciones eso
    # ordenaba por código y arrancaba en Afganistán/Albania.
    render_comparador(MOTOR, MOTOR.equipos, key='mundial')      # v25 (§2.4)
    render_rendimiento(key='mundial')

    # ---- 🎯 Asistente de Parlay del FIXTURE (v12; v14/M11: niveles de riesgo) --
    with st.expander("🎯 Asistente de Parlay del fixture — 3 pasos", expanded=False):
        st.markdown("**Paso 1 — Elige tu perfil de riesgo:**")
        NIVELES = {
            '🛡️ Conservador — pocas selecciones muy probables': (4, 0.65),
            '⚖️ Medio — equilibrio entre cuota y probabilidad': (6, 0.55),
            '🚀 Agresivo — cuota alta, probabilidad baja': (8, 0.50),
        }
        nivel_sel = st.radio("Nivel de riesgo", list(NIVELES.keys()), index=1,
                             label_visibility='collapsed',
                             help="Más selecciones y probabilidades más bajas = "
                                  "cuota combinada mayor pero menos opciones de acertar.")
        n_legs_sel, prob_min_sel = NIVELES[nivel_sel]
        st.markdown("**Paso 2 — Genera la propuesta:**")
        st.caption(
            "El asistente elige los mercados de mayor probabilidad del fixture con "
            "control de correlación (máx. 2 por partido, nunca mercados dependientes) "
            "y excluye partidos con riesgo de mercado 🔴. ⚠️ Sin cuotas de casas "
            "conectadas usa las cuotas JUSTAS del modelo (EV≈0): compáralas con tu "
            "casa. No es asesoramiento financiero."
        )
        if st.button("✨ Proponer mi parlay", key="btn_parlay", type="primary"):
            from parlay_builder import construir_parlay
            with st.spinner("🧮 Evaluando todos los mercados del fixture..."):
                parlay = construir_parlay(MOTOR, n_legs=n_legs_sel, prob_min=prob_min_sel)
            if 'error' in parlay:
                st.warning(parlay['error'])
            else:
                st.success(
                    f"**Este parlay tiene un {parlay['prob_conjunta']*100:.0f} % de "
                    f"probabilidad de ganar**, cuota total {parlay['cuota_combinada']:.2f}, "
                    f"EV {parlay['ev_parlay']:+.2f} unidades."
                )
                st.dataframe(pd.DataFrame([{
                    'Partido': s['partido'], 'Apuesta': s['apuesta'],
                    'Prob.': f"{s['prob']*100:.1f} %", 'Cuota': s['cuota'],
                    'Fuente': s['cuota_fuente'], 'EV': s['ev'],
                    'Riesgo': {'bajo': '🟢', 'medio': '🟡', 'alto': '🔴'}[s.get('riesgo', 'bajo')],
                } for s in parlay['selecciones']]), width='stretch', hide_index=True)
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Cuota combinada", f"{parlay['cuota_combinada']:.2f}",
                          help="Producto de todas las cuotas: lo que pagaría 1 unidad si aciertas todo.")
                c2.metric("Prob. conjunta", f"{parlay['prob_conjunta']*100:.1f} %",
                          help="Probabilidad de acertar TODAS las selecciones a la vez.")
                c3.metric("EV del parlay", f"{parlay['ev_parlay']:+.3f}",
                          help="Ganancia media esperada por unidad apostada. Positivo = valor a favor.")
                c4.metric("Riesgo general",
                          {'bajo': '🟢 Bajo', 'medio': '🟡 Medio', 'alto': '🔴 Alto'}[parlay['riesgo_parlay']],
                          help="Riesgo compuesto por divergencia con mercados de predicción y liquidez.")
                if parlay.get('partidos_excluidos_por_riesgo'):
                    st.warning("🔴 Partidos excluidos por riesgo de mercado: "
                               + ", ".join(parlay['partidos_excluidos_por_riesgo']))
                st.caption(parlay['nota'])
                st.markdown("**Paso 3 — Llévate las selecciones:**")
                texto = "\n".join(
                    f"{i}. {s['partido']}: {s['apuesta']} @ {s['cuota']} (p={s['prob']*100:.0f}%)"
                    for i, s in enumerate(parlay['selecciones'], 1)
                ) + (f"\nCuota combinada: {parlay['cuota_combinada']} · "
                     f"Prob: {parlay['prob_conjunta']*100:.1f}% · EV: {parlay['ev_parlay']:+.3f}")
                st.code(texto, language=None)
                st.download_button("📥 Descargar parlay (.txt)", data=texto.encode('utf-8'),
                                   file_name="parlay_mundial.txt", mime="text/plain")

    # v89 — SE RETIRA la sección «Inteligencia de Mercado — Polymarket»:
    # consultaba los mercados de predicción del Mundial 2026, que CERRARON al
    # terminar el torneo. Desde entonces la sección vivía en un bucle de «sin
    # mercados del Mundial abiertos» con un botón manual que nunca podía traer
    # nada. El módulo market_intelligence.py se retira con ella.

    # ---- Consultas en texto libre --------------------------------------------
    st.divider()
    st.subheader("💬 Pregúntale al modelo")
    st.caption(
        'Ejemplos: *"¿Cuántos goles se esperan en el Argentina vs Brasil?"* · '
        '*"¿Quién es el máximo rematador de México?"* · '
        '*"¿Qué equipo tiene más riesgo de expulsión?"* · '
        '*"Muéstrame el análisis completo."*'
    )
    consulta = st.text_input("Escribe tu pregunta", key="consulta_libre",
                             placeholder="¿Quién gana el México vs Ecuador?")

    if consulta.strip():
        respuesta = MOTOR.responder_consulta(consulta, equipos_por_defecto=(home, away))
        tipo = respuesta.get('tipo')

        if tipo == 'error':
            st.warning(f"🤔 {respuesta['mensaje']}")

        elif tipo == 'rematadores':
            if respuesta['jugadores']:
                st.markdown(f"**🎯 Máximos goleadores/rematadores de {respuesta['equipo_nombre']} "
                            f"(goles reales, últimos 24 meses):**")
                st.dataframe(pd.DataFrame([{
                    'Jugador': j['nombre'],
                    'Goles (24 m)': j['goles_24m'],
                    'Remates/partido': j['remates_totales'],
                    'Al arco': j['remates_al_arco'],
                    'Prob. de marcar': f"{j['prob_marcar']*100:.0f} %",
                } for j in respuesta['jugadores'][:5]]),
                    width='stretch', hide_index=True)
            else:
                st.info(f"{respuesta['equipo_nombre']}: sin goleadores registrados recientemente.")

        elif tipo == 'expulsiones':
            st.markdown("**🟥 Riesgo de expulsión por equipo (disciplina reciente):**")
            for c in respuesta['candidatos']:
                st.markdown(
                    f"- **{c['equipo']}**: {c['prob_expulsion_partido']*100:.0f} % de riesgo de ver "
                    f"una roja hoy (promedia {c['rojas_ma5']:.1f} expulsiones y "
                    f"{c['amarillas_ma5']:.1f} amarillas en sus últimos 5 partidos).")

        elif tipo == 'goles_esperados':
            st.markdown(
                f"**⚽ En el {respuesta['match']} se esperan "
                f"{respuesta['total']:.1f} goles en total** "
                f"(local: {respuesta['desglose']['home']:.1f} · "
                f"visitante: {respuesta['desglose']['away']:.1f}). "
                f"Marcador más probable: **{respuesta['marcador_mas_probable']}**.")

        elif tipo in ('ganador', 'analisis_completo'):
            pr = respuesta['prediccion']
            if 'error' in pr:
                st.warning(f"🤔 {pr['error']}")
            else:
                pp = pr['prediction']
                st.markdown(
                    f"**🏆 {pr['match']}:** ganador más probable **{pp['winner']}** "
                    f"({pp['confidence']*100:.0f} %), marcador más probable "
                    f"**{pp['most_likely_score']}**. "
                    f"Probabilidades: local {pp['probabilities']['home']*100:.0f} % · "
                    f"empate {pp['probabilities']['draw']*100:.0f} % · "
                    f"visitante {pp['probabilities']['away']*100:.0f} %.")
                if tipo == 'analisis_completo':
                    st.markdown(f"**🔥 Factor decisivo:** {pr['decisive_factor']}")
                    for frase in pr['insights']:
                        st.markdown(f"- {frase}")

# ===========================================================================
# PESTAÑA 2: PLANTILLA GENERAL DE ANÁLISIS (EDITABLE + VALIDACIÓN)
# ===========================================================================
with tab_plantilla:
    if not ES_PRO:
        st.info("🎚️ Estás en modo **Principiante**: esta plantilla muestra los ~85 "
                "campos técnicos del análisis completo (hándicaps, córners, "
                "tarjetas, distribuciones). Si prefieres solo lo esencial, "
                "quédate en la Vista Rápida — o cambia a modo **Pro** en la "
                "barra lateral para trabajar con todo el detalle.")
    pl = plantilla_cacheada(id(MOTOR), home, away, arbitro, fase, estadio)
    if 'error' in pl:
        st.error(f"❌ {pl['error']}")
        st.stop()

    st.markdown(f"## 📋 Plantilla General de Análisis Estadístico de Rendimiento")
    arb_pl = pl['arbitro']
    nombre_estadio = ESTADIOS_MUNDIAL.get(pl.get('estadio'), {}).get('nombre', pl.get('estadio'))
    st.markdown(f"**Partido:** {pl['partido']} · **Fecha:** {pl['fecha']}"
                + (f" · **Estadio:** {nombre_estadio} ({pl.get('altitud_sede', 0):.0f} msnm)"
                   if pl.get('estadio') else '')
                + f" · **Datos al:** {pl['estado_al']}")
    st.markdown(f"**Árbitro:** {arb_pl['nombre']} ({arb_pl['criterio']}, "
                f"{arb_pl['ama_p90']:.1f} am/90, {arb_pl['roj_p90']:.2f} roj/90, "
                f"{arb_pl['pen_p90']:.2f} pen/90)")
    st.caption(
        "Cada campo llega pre-rellenado con la predicción del modelo. Edita los que "
        "quieras y pulsa **Validar mis estimaciones** para compararlas con el modelo "
        "y detectar dónde habría valor frente a cuotas de mercado."
    )

    # v18/M3: cuotas reales vigentes + EV por mercado
    render_cuotas_reales(pl)

    etiqueta_arb = (arbitro or 'promedio').replace(' ', '-') + f"_{fase}_{(estadio or 'auto').replace(' ', '-')}"
    prefijo_clave = f"pl_{home}_{away}_{etiqueta_arb}_"

    with st.form(key=f"form_plantilla_{home}_{away}_{etiqueta_arb}"):
        for seccion in pl['secciones']:
            st.markdown(f"#### {seccion['titulo']}")
            editables = [c for c in seccion['campos'] if c['tipo'] != 'texto']
            textos = [c for c in seccion['campos'] if c['tipo'] == 'texto']
            columnas = st.columns(3)
            for i, c in enumerate(editables):
                with columnas[i % 3]:
                    if c['tipo'] == 'pct':
                        st.number_input(f"{c['etiqueta']} (%)", min_value=0.0, max_value=100.0,
                                        value=float(c['valor']), step=0.5,
                                        key=prefijo_clave + c['id'])
                    else:  # media
                        st.number_input(f"{c['etiqueta']}", min_value=0.0, max_value=60.0,
                                        value=float(c['valor']), step=0.1,
                                        key=prefijo_clave + c['id'])
            for c in textos:
                st.markdown(f"- **{c['etiqueta']}** → `{c['valor']}`")
        validar = st.form_submit_button("✅ Validar mis estimaciones", type="primary")

    # ---- Validación: usuario vs modelo ---------------------------------------
    if validar:
        st.markdown("### 🔍 Validación: tus estimaciones vs el modelo")
        hallazgos, editados = [], 0
        for seccion in pl['secciones']:
            for c in seccion['campos']:
                if c['tipo'] == 'texto':
                    continue
                clave = prefijo_clave + c['id']
                valor_usuario = float(st.session_state.get(clave, c['valor']))
                valor_modelo = float(c['valor'])
                dif = valor_usuario - valor_modelo
                if abs(dif) < 0.05:
                    continue
                editados += 1
                fila = {'Campo': c['etiqueta'], 'Tu valor': round(valor_usuario, 1),
                        'Modelo': round(valor_modelo, 1), 'Diferencia': round(dif, 1)}
                if c['tipo'] == 'pct' and valor_usuario > 0 and valor_modelo > 0:
                    cuota_justa_modelo = 100.0 / valor_modelo
                    cuota_exigida_usuario = 100.0 / valor_usuario
                    fila['Cuota justa (modelo)'] = round(cuota_justa_modelo, 2)
                    direccion = "por debajo" if dif < 0 else "por encima"
                    fila['Lectura'] = (
                        f"Tu estimación ({valor_usuario:.0f} %) está {direccion} del modelo "
                        f"({valor_modelo:.0f} %). Según el modelo, cualquier cuota de mercado "
                        f"mayor a {cuota_justa_modelo:.2f} ofrece valor esperado positivo"
                        + (f"; tú la exigirías desde {cuota_exigida_usuario:.2f}." if dif < 0 else ".")
                    )
                hallazgos.append(fila)

        if not hallazgos:
            st.success("No modificaste ningún campo (o tus valores coinciden con el modelo). "
                       "Edita los campos que quieras contrastar y vuelve a validar.")
        else:
            difs = [abs(h['Diferencia']) for h in hallazgos]
            c1, c2, c3 = st.columns(3)
            c1.metric("Campos modificados", editados)
            c2.metric("Diferencia media", f"{np.mean(difs):.1f}")
            c3.metric("Mayor discrepancia", f"{max(difs):.1f}")
            st.dataframe(pd.DataFrame(hallazgos), width='stretch', hide_index=True)
            for h in hallazgos:
                if 'Lectura' in h and abs(h['Diferencia']) >= 3:
                    st.info(f"💡 **{h['Campo']}** — {h['Lectura']}")

    # ---- Observaciones + exportación ------------------------------------------
    st.markdown("#### 📝 Observaciones adicionales (generadas automáticamente)")
    for obs in pl['observaciones']:
        st.markdown(f"- {obs}")

    valores_usuario = {
        c['id']: float(st.session_state.get(prefijo_clave + c['id'], c['valor']))
        for s in pl['secciones'] for c in s['campos'] if c['tipo'] != 'texto'
    }
    col_d1, col_d2 = st.columns(2)
    with col_d1:
        st.download_button(
            "⬇️ Descargar plantilla (valores del modelo)",
            data=plantilla_a_markdown(pl).encode('utf-8'),
            file_name=f"plantilla_{home}_vs_{away}_modelo.md",
            mime="text/markdown", width='stretch',
        )
    with col_d2:
        st.download_button(
            "⬇️ Descargar plantilla (con mis ediciones)",
            data=plantilla_a_markdown(pl, valores_usuario).encode('utf-8'),
            file_name=f"plantilla_{home}_vs_{away}_usuario.md",
            mime="text/markdown", width='stretch',
        )

st.divider()
if ES_PRO:
    st.caption(
        "🔬 Bajo el capó: ensemble XGBoost + Random Forest + LightGBM con calibración "
        "isotónica, entropías de persistencia H0/H1 (nube del par + últimos 10 partidos "
        "de cada equipo), regresores Poisson de goles esperados y Monte Carlo de 20,000 "
        "partidos. Backtesting temporal sobre partidos reales: "
        f"{MOTOR.metadata.get('precision_validacion', 0)*100:.1f} % de acierto · "
        f"log-loss {MOTOR.metadata.get('log_loss_validacion', 0):.3f}."
    )
else:
    st.caption(
        f"🔬 El modelo acierta el resultado (gana local / empate / gana visitante) "
        f"en {MOTOR.metadata.get('precision_validacion', 0)*100:.0f} de cada 100 "
        f"partidos reales pasados. Ninguna apuesta es segura: apuesta solo lo que "
        f"puedas permitirte perder."
    )
