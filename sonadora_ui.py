#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Pantalla «Armar Soñadora»: el usuario combina patas de alta probabilidad.

QUÉ ENSEÑA Y EN QUÉ ORDEN, Y POR QUÉ ESE ORDEN
----------------------------------------------
Primero lo que se midió, después lo que se puede armar. Al revés —patas
arriba, advertencia al pie— la advertencia no se lee: es el mismo motivo por el
que la alarma de datos va al principio del mensaje de Telegram desde la v41.

    1. La advertencia, con el número medido dentro.
    2. La configuración: cuántas patas, qué rango de cuota, qué deportes.
    3. Lo que rindió ESA configuración en el histórico.
    4. Las patas del día, ordenadas por Score_Segura.
    5. El parlay armado, con el premio Y con lo que se espera perder.

LO QUE ESTA PANTALLA NO HACE
----------------------------
No recomienda. `validar_sonadora.py` midió las veinte configuraciones del
encargo sobre el histórico reciente y **ninguna** tiene esperanza positiva; la
mejor pata suelta pierde el 5,4 % y un parlay multiplica esa pérdida, no la
compensa. La sección existe porque el usuario la pidió sabiendo eso.

No entra en «Apuestas del Día», no viaja por Telegram y no comparte pesos con
`clasificador.py`: es entretenimiento declarado, separado de lo que el sistema
sí recomienda.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

AVISO = (
    "⚠️ **Esto es entretenimiento de alto riesgo, y el número lo dice.** "
    "Se midieron las combinaciones de 4, 6, 8, 10 y 13 patas sobre los "
    "partidos de los últimos meses con cuota de cierre real: **ninguna** sale "
    "con ganancia esperada. Una pata suelta de este tipo pierde un 5,4 % de "
    "media, y un parlay no arregla eso — lo multiplica. Usa sólo dinero que "
    "puedas permitirte perder."
)

N_PATAS_OPCIONES = (4, 6, 8, 10, 13)
MULT_OBJETIVO = (10, 50, 100, 500)
NIVELES = {
    'liga': 'Ligas con calibración medida (recomendado)',
    'mercado': 'Sólo mercados con error de calibración medido (más estricto)',
    'todo': 'Todo lo que cotice Playdoit (sin filtro de calibración)',
}


def _pct(x, dec=1) -> str:
    try:
        return f"{float(x) * 100:.{dec}f} %"
    except (TypeError, ValueError):
        return '—'


def _color_roi(roi: Optional[float]) -> str:
    if roi is None:
        return '⚪'
    if roi > 0:
        return '🟢'
    if roi > -0.05:
        return '🟡'
    return '🔴'


def render(st, r: Dict, dia: Optional[str] = None) -> None:
    """Pinta la pantalla entera. `r` es un barrido YA calculado."""
    import sonadora_motor as sm
    import mercados_dia as md

    st.header('🎰 Armar Soñadora')
    st.error(AVISO)

    hist = sm.historico()
    if not hist.get('medido'):
        st.warning(
            'Todavía no hay validación histórica (`sonadora_historico.json`). '
            'Se puede armar el parlay, pero no hay con qué comparar: corre '
            '`python validar_sonadora.py`.')
    else:
        ps = hist.get('pata_suelta') or {}
        st.caption(
            f"Medido sobre {hist.get('n_partidos', 0)} partidos del periodo "
            f"{hist.get('periodo', '?')}: una pata de cuota 1,10-1,80 con "
            f"probabilidad ≥ 55 % la da el modelo al "
            f"{_pct(ps.get('prob_media'))} y **acierta el "
            f"{_pct(ps.get('acierto'))}** — un ROI de "
            f"**{_pct(ps.get('roi'), 2)}** por pata "
            f"(n={ps.get('n', 0)}, p5 {_pct(ps.get('p5'), 2)}).")

    # ------------------------------------------------------------------ #
    # 2. Configuración
    # ------------------------------------------------------------------ #
    st.subheader('⚙️ Configuración')
    c1, c2 = st.columns(2)
    cuota_min, cuota_max = c1.slider(
        'Cuota por pata', min_value=1.01, max_value=2.50,
        value=(sm.CUOTA_MIN, sm.CUOTA_MAX), step=0.01, key='son_cuota',
        help='El parlay que ganó el usuario iba de 1,35 a 1,79.')
    prob_min = c2.slider(
        'Probabilidad mínima del modelo', min_value=0.50, max_value=0.95,
        value=sm.PROB_MINIMA, step=0.01, key='son_prob',
        format='%.2f')

    c3, c4 = st.columns(2)
    n_patas = c3.selectbox(
        'Número de patas', N_PATAS_OPCIONES,
        index=N_PATAS_OPCIONES.index(13), key='son_n')
    # v197 — el número NO va dentro de la opción del selector de nivel.
    # La preferencia guardaría un valor que mañana no existe: es la lección de
    # la v177 con el filtro de deportes, y se resuelve con `format_func`.
    nivel = c4.selectbox(
        'Exigencia de calibración', list(NIVELES), index=0, key='son_nivel',
        format_func=lambda k: NIVELES[k])

    deportes_todos = ['Fútbol', 'Tenis', 'MLB', 'KBO', 'NBA', 'NFL']
    deportes = st.multiselect(
        'Deportes', deportes_todos, default=deportes_todos, key='son_deportes')

    # ------------------------------------------------------------------ #
    # 3. Lo que rindió esta configuración
    # ------------------------------------------------------------------ #
    cfg = sm.configuracion(n_patas, (cuota_min, cuota_max))
    st.subheader('📊 Lo que rindió esta configuración en el histórico')
    if not cfg or not cfg.get('intentos'):
        st.info(
            f'No hay medición para {n_patas} patas en ese rango: '
            f"{(cfg or {}).get('motivo', 'no se pudo simular')}. "
            f'Sin medición no hay tasa de acierto que enseñar, y no se '
            f'inventa una.')
    else:
        rango = cfg.get('rango_cuota') or []
        m1, m2, m3, m4 = st.columns(4)
        m1.metric('Acierto', _pct(cfg.get('hit_rate'), 2),
                  help=f"{cfg.get('ganadas', 0)} de {cfg.get('intentos', 0)} "
                       f"combinaciones simuladas")
        m2.metric('Multiplicador medio',
                  f"{cfg.get('multiplicador_medio', 0):.1f}x")
        m3.metric('ROI simulado', _pct(cfg.get('roi_simulado')),
                  help='Rendimiento medio de esa configuración en las '
                       'jornadas simuladas.')
        m4.metric('p5 por jornada', _pct(cfg.get('p5_por_dia')),
                  help='Percentil 5 remuestreando JORNADAS, no combinaciones: '
                       'las combinaciones comparten partidos y su intervalo '
                       'miente.')
        st.caption(
            f"{_color_roi(cfg.get('roi_simulado'))} Veredicto medido: "
            f"**{cfg.get('veredicto', '?')}** · rango simulado "
            f"{rango[0] if rango else '?'}–{rango[1] if len(rango) > 1 else '?'} "
            f"· {cfg.get('dias_con_suficientes_partidos', 0)} jornadas con "
            f"partidos suficientes, de las que "
            f"{cfg.get('dias_que_aportan_ganadoras', 0)} aportan alguna "
            f"ganadora.")
        if cfg.get('veredicto') == 'sin_muestra':
            st.warning(
                'Esta configuración **no tiene muestra suficiente**: se armó '
                'sobre muy pocas jornadas distintas, así que su ROI es el de '
                'esas tardes concretas y no el de una estrategia. No se puede '
                'leer como una expectativa.')
        _teorico = cfg.get('hit_rate_teorico')
        if _teorico and cfg.get('hit_rate'):
            st.caption(
                f"El producto de las probabilidades daría "
                f"{_pct(_teorico, 2)} y en la práctica salió "
                f"{_pct(cfg.get('hit_rate'), 2)}: los partidos de una misma "
                f"jornada **no son independientes**, así que la cuenta de "
                f"multiplicar se queda corta en las dos direcciones.")

    # ------------------------------------------------------------------ #
    # 4. Las patas del día
    # ------------------------------------------------------------------ #
    st.subheader('🎯 Patas disponibles')
    dia = dia or md.dia_cdmx()
    with st.spinner('Leyendo el tablero de Playdoit…'):
        try:
            res = sm.patas_del_dia(r, dia, cuota_min=cuota_min,
                                   cuota_max=cuota_max, prob_min=prob_min,
                                   deportes=deportes or None, nivel=nivel)
        except Exception as e:
            st.error(f'No se pudieron leer las patas ({type(e).__name__}: {e}).')
            return
    patas = res.get('patas') or []
    st.caption(
        f"{res.get('n_partidos', 0)} partidos del {dia} · "
        f"{res.get('tableros_pedidos', 0)} tableros de Playdoit leídos "
        f"({res.get('sin_tablero', 0)} sin tablero) · "
        f"{res.get('n_sin_filtrar', 0)} patas antes de filtrar · "
        f"{res.get('n_apartadas_por_calibracion', 0)} apartadas por "
        f"calibración.")
    if not patas:
        st.info(
            'Ninguna pata pasa estos filtros hoy. Baja la probabilidad '
            'mínima, ensancha el rango de cuota o afloja la exigencia de '
            'calibración. Cero patas no es un fallo: es que hoy no hay nada '
            'que cumpla lo que pediste.')
        return

    opciones = {q['id']: q for q in patas}

    def _rotulo(cid: str) -> str:
        q = opciones[cid]
        sello = '' if q.get('medido') else ' · sin ECE medido'
        return (f"[{q['deporte']}] {q['partido']} — {q['etiqueta']}  "
                f"({q['cuota']:.2f} · {_pct(q['prob'], 0)} · {q['casa']}"
                f"{sello})")

    elegidas = st.multiselect(
        f'Elige hasta {sm.MAX_PATAS} patas (ordenadas por Score_Segura)',
        list(opciones), key='son_elegidas', format_func=_rotulo,
        max_selections=sm.MAX_PATAS)

    if st.button(f'⚡ Rellenar con las {n_patas} de mayor Score',
                 key='son_autorellena'):
        # una pata por PARTIDO: dos del mismo encuentro están correlacionadas
        # y la casa ni siquiera las deja combinar sin tratarlas aparte
        vistos, auto = set(), []
        for q in patas:
            if q['partido'] in vistos:
                continue
            vistos.add(q['partido'])
            auto.append(q['id'])
            if len(auto) >= n_patas:
                break
        st.session_state['son_elegidas'] = auto
        st.rerun()

    # ------------------------------------------------------------------ #
    # 5. El parlay
    # ------------------------------------------------------------------ #
    if not elegidas:
        st.info('Elige patas arriba para ver el parlay.')
        return
    st.subheader('🎰 Parlay armado')
    parlay = sm.armar([opciones[c] for c in elegidas])
    partidos = {q['partido'] for q in parlay['patas']}
    if len(partidos) < len(parlay['patas']):
        st.warning(
            'Hay dos patas del MISMO partido. Están muy correlacionadas y la '
            'casa normalmente no las deja combinar: el multiplicador que ves '
            'no es el que te van a pagar.')

    p1, p2, p3 = st.columns(3)
    p1.metric('Patas', parlay['n_patas'])
    p2.metric('Multiplicador', f"{parlay['multiplicador']:.2f}x")
    p3.metric('Probabilidad del modelo', _pct(parlay['prob_producto'], 2),
              help='Producto de las probabilidades. Supone independencia, que '
                   'es un supuesto, no una medición.')

    apuesta = st.number_input('¿Cuánto apostarías?', min_value=1.0,
                              value=46.0, step=1.0, key='son_apuesta',
                              help='46 es lo que costó el parlay que ganaste.')
    st.markdown(
        f"### Premio: **${apuesta * parlay['multiplicador']:,.2f}**")

    roi_med = parlay.get('roi_esperado_medido')
    if roi_med is not None:
        st.error(
            f"Con lo medido, la expectativa de este parlay es "
            f"**{_pct(roi_med)}** sobre lo apostado — unos "
            f"**${apuesta * roi_med:,.2f}** de media por cada "
            f"${apuesta:,.2f}. Sale de aplicar {parlay['n_patas']} veces el "
            f"−5,4 % que pierde una pata suelta; combinar no crea ventaja, "
            f"multiplica la que haya.")
    cfg_p = parlay.get('configuracion_medida')
    if cfg_p and cfg_p.get('intentos'):
        st.caption(
            f"La configuración medida más parecida "
            f"({cfg_p['n_patas']} patas, {cfg_p.get('rango_cuota')}) ganó "
            f"{cfg_p.get('ganadas', 0)} de {cfg_p.get('intentos', 0)} veces "
            f"({_pct(cfg_p.get('hit_rate'), 2)}).")

    st.markdown('**Las patas:**')
    for q in parlay['patas']:
        sello = '' if q.get('medido') else '  ·  _sin error de calibración medido_'
        st.markdown(
            f"- `{q['cuota']:.2f}`  **{q['etiqueta']}** — {q['partido']} "
            f"({q['liga']}, {q['hora'] or 'sin hora'})  ·  modelo "
            f"{_pct(q['prob'], 0)}  ·  {q['casa']}{sello}")

    entendido = st.checkbox(
        'Entiendo que el rendimiento medido de esto es negativo y que apuesto '
        'dinero que puedo perder.', key='son_entendido')
    if st.button('🎲 Confirmar parlay', key='son_confirmar',
                 disabled=not entendido, type='primary'):
        st.success(
            'Anotado. Ve a Playdoit y móntalo ahí: esta pantalla no apuesta '
            'por ti ni manda nada a ningún sitio.')
        st.code(
            '\n'.join(f"{q['partido']} — {q['etiqueta']} @ {q['cuota']:.2f}"
                      for q in parlay['patas']), language=None)

    # ------------------------------------------------------------------ #
    # 6. Las otras configuraciones, para comparar
    # ------------------------------------------------------------------ #
    with st.expander('📊 Todas las configuraciones medidas'):
        filas = []
        for c in (hist.get('configuraciones') or []):
            if not c.get('intentos'):
                continue
            rango = c.get('rango_cuota') or [0, 0]
            filas.append({
                'Patas': c['n_patas'],
                'Cuota': f"{rango[0]:.2f}–{rango[1]:.2f}",
                'Jornadas': c.get('dias_con_suficientes_partidos'),
                'Acierto': _pct(c.get('hit_rate'), 2),
                'Multiplicador': f"{c.get('multiplicador_medio', 0):.1f}x",
                'ROI simulado': _pct(c.get('roi_simulado')),
                'p5 por jornada': _pct(c.get('p5_por_dia')),
                'Veredicto': c.get('veredicto'),
            })
        if filas:
            st.dataframe(filas, width='stretch', hide_index=True)
        st.caption(
            'El ROI simulado de una fila con pocas jornadas es el de esas '
            'jornadas, no el de una estrategia; por eso va al lado el número '
            'de jornadas y el veredicto dice «sin_muestra».')
