#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Pantalla «Armar Soñadora»: dos controles, permutaciones propuestas y elección
manual.

QUÉ CAMBIÓ RESPECTO A LA PRIMERA VERSIÓN
----------------------------------------
La primera tenía seis controles, una advertencia roja permanente y salía vacía.
Vacía no por prudencia: la rama de fútbol del barrido estaba reventando
(arreglado en `alpha_finder`) y encima el filtro de calibración tiraba 133 de
174 patas. Ahora:

    · **Configuración corta**: rango de cuota, número de patas y qué deportes
      entran. La probabilidad mínima queda fija en 55 % y el filtro de
      calibración desapareció — cada pata lleva su semáforo y el usuario
      decide.
    · **Nunca vacía**: si el rango no deja nada, el motor lo ensancha solo y la
      pantalla lo dice en una línea.
    · **Sin advertencia roja**: un aviso pequeño arriba y una casilla antes de
      confirmar. El rendimiento medido sigue estando, al lado del premio.

EL SEMÁFORO
-----------
🟢 sólida · 🟡 moderada · 🔴 alto riesgo · ⚪ sin probabilidad. Lo calcula
`sonadora_motor.color` y aquí sólo se pinta. Las rojas se esconden por defecto
y hay un interruptor para verlas; si un día NO hay nada mejor que rojas, se
enseñan igual — esconder lo único que hay es dejar la pantalla vacía por otra
vía.

EL ORDEN DE LO QUE SE ENSEÑA
----------------------------
Permutación A (la más segura) primero, y el ROI medido junto al premio y no al
pie: al pie no se lee. Es la misma lección que puso la alarma de datos al
principio del mensaje diario en la v41.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

AVISO = ('ℹ️ Sección de entretenimiento. No es asesoramiento financiero ni una '
         'recomendación del sistema.')

N_PATAS_OPCIONES = (4, 6, 8, 10, 13)


def _pct(x, dec=1) -> str:
    try:
        return f"{float(x) * 100:.{dec}f} %"
    except (TypeError, ValueError):
        return '—'


def _sello(q: Dict) -> str:
    """El semáforo de la pata.

    Normalmente lo trae el motor. Si faltara —una pata de un camino antiguo, o
    un estado guardado de antes— se recalcula aquí en vez de caer a gris: gris
    es «no se sabe», y con la probabilidad delante sí se sabe. Es justo el
    síntoma que el usuario reportó, «veo puro blanco», y esta red lo cierra
    venga de donde venga la pata.
    """
    color = q.get('color')
    if color:
        return color
    try:
        import sonadora_motor as sm
        return sm.color(q.get('prob'), q.get('ece'),
                        bool(q.get('calibracion_floja')))
    except Exception:
        return '⚪'


_FLECHA = {'a_favor': '📉 el mercado se mueve a favor',
           'en_contra': '📈 el mercado se mueve en contra',
           'estable': ''}
_ALI = {'confirmada': '✅ alineación confirmada',
        'probable': '🔸 alineación probable',
        'ultimo_once': '', 'desconocida': ''}


def _linea_pata(q: Dict) -> str:
    cola = '' if q.get('medido') else '  ·  _sin calibración medida_'
    extra = [x for x in (_FLECHA.get(q.get('movimiento') or '', ''),
                         _ALI.get(q.get('alineacion') or '', '')) if x]
    pie = ('  \n     ' + ' · '.join(extra)) if extra else ''
    return (f"{_sello(q)} **{q['etiqueta']}** · {q['partido']} "
            f"— `{q['cuota']:.2f}` · modelo {_pct(q['prob'], 0)} "
            f"· {q['liga']}{(' · ' + q['hora']) if q.get('hora') else ''}"
            f"{cola}{pie}")


def render(st, r: Dict, dia: Optional[str] = None) -> None:
    """Pinta la pantalla. `r` es un barrido YA calculado."""
    import mercados_dia as md
    import sonadora_motor as sm

    st.header('🎰 Armar Soñadora')
    st.info(AVISO)

    # ------------------------------------------------------------------ #
    # 1. Los dos controles
    # ------------------------------------------------------------------ #
    c1, c2 = st.columns([2, 1])
    cuota_min, cuota_max = c1.slider(
        'Cuota por pata', min_value=sm.CUOTA_MIN_ABS,
        max_value=sm.CUOTA_MAX_ABS, value=(sm.CUOTA_MIN, sm.CUOTA_MAX),
        step=0.05, key='son_cuota',
        help='El parlay que ganaste iba de 1,35 a 1,79.')
    # v198 — el número NO va dentro de la etiqueta de la opción. La preferencia
    # guardaría un valor que mañana no existe: lección de la v177 con el filtro
    # de deportes. El valor es el entero y `format_func` pone el rótulo.
    n_patas = c2.selectbox(
        'Número de patas', N_PATAS_OPCIONES,
        index=N_PATAS_OPCIONES.index(13), key='son_n',
        format_func=lambda n: f'{n} patas')

    deportes = st.multiselect(
        'Deportes', list(sm.DEPORTES), default=list(sm.DEPORTES_POR_DEFECTO),
        key='son_deportes',
        help='El tablero de Playdoit se pide sólo para lo que marques, así '
             'que marcar menos deportes es también más rápido.')
    if not deportes:
        st.warning('Marca al menos un deporte para ver patas.')
        return
    con_rojas = st.checkbox('Mostrar patas de alto riesgo (🔴)',
                            key='son_rojas')

    # ------------------------------------------------------------------ #
    # 2. Las patas del día
    # ------------------------------------------------------------------ #
    dia = dia or md.dia_cdmx()

    # EN CLOUD CADA CLIC ES UNA PASADA ENTERA, y esta sección pide hasta
    # sesenta tableros de Playdoit. Sin caché, marcar una pata del multiselect
    # volvía a bajarlos todos: medido en local, de 3 s con caché caliente a 32 s
    # con la fría — y el contenedor de Streamlit Cloud es más lento que esto.
    #
    # La clave incluye `actualizado` del barrido, así que un barrido nuevo
    # invalida la lista sola. `_r` con guion bajo le dice a Streamlit que no
    # intente hashear el diccionario del barrido, que es enorme.
    @st.cache_data(ttl=900, show_spinner=False)
    def _patas(_r, sello, dia_, lo, hi, deps, rojas):
        return sm.patas_del_dia(_r, dia_, cuota_min=lo, cuota_max=hi,
                                deportes=list(deps), con_rojas=rojas)

    with st.spinner('Leyendo el tablero de Playdoit…'):
        try:
            res = _patas(r, str(r.get('actualizado') or ''), dia,
                         cuota_min, cuota_max, tuple(sorted(deportes)),
                         con_rojas)
        except Exception as e:
            st.error(f'No se pudieron leer las patas ({type(e).__name__}: {e}).')
            return
    patas: List[Dict] = res.get('patas') or []

    if not patas:
        st.warning(
            f"📅 Hoy no hay partidos con mercados suficientes "
            f"({res.get('n_partidos', 0)} partidos, "
            f"{res.get('tableros_pedidos', 0)} tableros leídos). "
            f"Vuelve más tarde o prueba el día siguiente.")
        return
    if res.get('ensanchado'):
        rango = res.get('rango') or []
        st.caption(
            f"⚙️ Ajustamos el rango automáticamente a "
            f"{rango[0]:.2f}–{rango[1]:.2f} para mostrarte opciones: con el "
            f"que pediste no había ninguna pata hoy.")

    cc = res.get('conteo_color') or {}
    st.markdown(
        '**Semáforo:** 🟢 sólida (probabilidad ≥ 70 %) · '
        '🟡 moderada (≥ 58 %) · 🔴 alto riesgo · '
        '⚪ sin probabilidad. La calibración de la competición sólo puede '
        'bajar un escalón, nunca subirlo.')
    st.caption(
        f"**{len(patas)} patas** de {res.get('partidos_con_pata', 0)} "
        f"partidos · 🟢 {cc.get('🟢', 0)} sólidas · 🟡 {cc.get('🟡', 0)} "
        f"moderadas · 🔴 {cc.get('🔴', 0)} de alto riesgo"
        + (f" ({res.get('rojas_ocultas', 0)} ocultas)"
           if res.get('rojas_ocultas') else '')
        + f" · {res.get('tableros_pedidos', 0)} tableros de Playdoit leídos.")
    st.caption(
        f"El color lo manda la probabilidad del modelo; la calibración sólo "
        f"puede bajarlo. {res.get('n_medidas', 0)} de estas patas tienen error "
        f"de calibración medido — al resto se le encoge la probabilidad un "
        f"15 % al puntuar, y se dice en cada línea.")
    if res.get('solidez') == 'debil':
        st.warning('⚠️ Pocas patas verdes hoy con esta configuración. '
                   'Considera ampliar el rango de cuota o marcar más '
                   'deportes.')
    elif res.get('solidez') == 'solida':
        st.success('✅ Lista sólida: la mayoría de las patas de hoy son '
                   'verdes.')

    # ------------------------------------------------------------------ #
    # 3. Permutaciones
    # ------------------------------------------------------------------ #
    st.subheader('🎯 Permutaciones generadas')
    perms = sm.permutaciones(patas, n_patas)
    if not perms:
        st.info(
            f'Hoy no hay {n_patas} partidos distintos con pata disponible '
            f'(hay {res.get("partidos_con_pata", 0)}). Prueba con menos '
            f'patas o ensancha el rango de cuota.')
    for p in perms:
        with st.container(border=True):
            a, b, c = st.columns([2, 1, 1])
            a.markdown(f"**{p['nombre']}**  \n{p['descripcion']}")
            b.metric('Multiplicador', f"{p['multiplicador']:.2f}x")
            c.metric('Probabilidad', _pct(p['prob_producto'], 2),
                     help='Producto de las probabilidades del modelo. Supone '
                          'independencia, que es un supuesto: los partidos de '
                          'un mismo día se parecen más de lo que dice esa '
                          'cuenta.')
            for q in p['patas']:
                st.markdown(_linea_pata(q))
            _cc = p.get('conteo_color') or {}
            pie = [f"🟢 {_cc.get('🟢', 0)} · 🟡 {_cc.get('🟡', 0)} · "
                   f"🔴 {_cc.get('🔴', 0)}",
                   f"{p['ligas']} competiciones distintas",
                   ' + '.join(p.get('deportes') or [])]
            if p.get('n_sin_medir'):
                pie.append(f"{p['n_sin_medir']} patas sin calibración medida")
            roi = p.get('roi_esperado_medido')
            if roi is not None:
                pie.append(f"rendimiento histórico de esta longitud: "
                           f"{_pct(roi)}")
            st.caption(' · '.join(pie))
            if st.button(f"Usar {p['nombre']}", key=f"son_usar_{p['letra']}"):
                st.session_state['son_elegidas'] = [q['id'] for q in p['patas']]
                st.rerun()

    # ------------------------------------------------------------------ #
    # 4. Elección manual
    # ------------------------------------------------------------------ #
    st.subheader('✍️ O arma la tuya')
    opciones = {q['id']: q for q in patas}
    # Una selección guardada puede apuntar a patas que ya no están (cambió el
    # rango, cambió el día). Streamlit lanza si el default no es una opción, y
    # eso es una pantalla en blanco: se limpia aquí, que es donde se sabe.
    previas = [c for c in (st.session_state.get('son_elegidas') or [])
               if c in opciones]
    if previas != (st.session_state.get('son_elegidas') or []):
        st.session_state['son_elegidas'] = previas

    elegidas = st.multiselect(
        f'Patas (hasta {sm.MAX_PATAS})', list(opciones), key='son_elegidas',
        format_func=lambda cid: (
            f"{_sello(opciones[cid])} [{opciones[cid]['deporte']}] "
            f"{opciones[cid]['partido']} — {opciones[cid]['etiqueta']} "
            f"({opciones[cid]['cuota']:.2f} · "
            f"{_pct(opciones[cid]['prob'], 0)})"),
        max_selections=sm.MAX_PATAS)
    if not elegidas:
        st.caption('Elige patas arriba o pulsa «Usar» en una permutación.')
        return

    # ------------------------------------------------------------------ #
    # 5. El parlay
    # ------------------------------------------------------------------ #
    st.subheader('🎰 Tu parlay')
    parlay = sm.armar([opciones[c] for c in elegidas])
    if len({q['partido'] for q in parlay['patas']}) < parlay['n_patas']:
        st.warning(
            'Hay dos patas del mismo partido. Están muy correlacionadas y la '
            'casa normalmente no las deja combinar: el multiplicador que ves '
            'no es el que te van a pagar.')

    m1, m2, m3 = st.columns(3)
    m1.metric('Patas', parlay['n_patas'])
    m2.metric('Multiplicador', f"{parlay['multiplicador']:.2f}x")
    m3.metric('Probabilidad', _pct(parlay['prob_producto'], 2))

    apuesta = st.number_input('¿Cuánto apostarías?', min_value=1.0, value=46.0,
                              step=1.0, key='son_apuesta',
                              help='46 es lo que costó el parlay que ganaste.')
    st.markdown(f"### Premio: **${apuesta * parlay['multiplicador']:,.2f}**")

    roi = parlay.get('roi_esperado_medido')
    cfg = parlay.get('configuracion_medida')
    datos = []
    if roi is not None:
        datos.append(
            f"**Rendimiento histórico de un parlay de {parlay['n_patas']} "
            f"patas: {_pct(roi)}** (≈ ${apuesta * roi:,.2f} por cada "
            f"${apuesta:,.2f}). Sale de aplicar {parlay['n_patas']} veces lo "
            f"que rinde una pata suelta: combinar multiplica el rendimiento "
            f"de las patas, no lo mejora.")
    if cfg and cfg.get('intentos'):
        datos.append(
            f"La configuración medida más parecida ({cfg['n_patas']} patas, "
            f"{cfg.get('rango_cuota')}) acertó "
            f"{cfg.get('ganadas', 0)} de {cfg.get('intentos', 0)} veces "
            f"({_pct(cfg.get('hit_rate'), 2)}), con un multiplicador medio de "
            f"{cfg.get('multiplicador_medio', 0):.1f}x.")
    if datos:
        st.caption('  \n'.join(datos))

    st.markdown('**Las patas:**')
    for q in parlay['patas']:
        st.markdown(_linea_pata(q))

    entendido = st.checkbox('Entiendo que este parlay tiene un alto riesgo.',
                            key='son_entendido')
    if st.button('🎲 Confirmar parlay', key='son_confirmar', type='primary',
                 disabled=not entendido):
        st.success('Listo. Móntalo en Playdoit: esta pantalla no apuesta por '
                   'ti ni manda nada a ningún sitio.')
        st.code('\n'.join(f"{q['partido']} — {q['etiqueta']} @ {q['cuota']:.2f}"
                          for q in parlay['patas']), language=None)

    # ------------------------------------------------------------------ #
    # 6. Lo medido, para quien quiera mirarlo
    # ------------------------------------------------------------------ #
    hist = sm.historico()
    with st.expander('📊 Qué rindió cada longitud en el histórico'):
        ps = hist.get('pata_suelta') or {}
        if ps.get('n'):
            st.caption(
                f"Periodo {hist.get('periodo', '?')} · "
                f"{hist.get('n_partidos', 0)} partidos. Una pata suelta de "
                f"cuota 1,10-1,80 con probabilidad ≥ 55 %: el modelo le da "
                f"{_pct(ps.get('prob_media'))} y acierta "
                f"{_pct(ps.get('acierto'))} (n={ps.get('n')}).")
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
                'Rendimiento': _pct(c.get('roi_simulado')),
            })
        if filas:
            st.dataframe(filas, width='stretch', hide_index=True)
        st.caption(
            'Una fila con pocas jornadas describe esas jornadas, no una '
            'estrategia: por eso va al lado el número de jornadas.')
