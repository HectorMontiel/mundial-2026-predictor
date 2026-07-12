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

import numpy as np
import pandas as pd
import streamlit as st
import plotly.graph_objects as go

from prediction_api import PredictionEngine, NOMBRES_PAIS, plantilla_a_markdown
from arbitros import ARBITROS
from altitud import ESTADIOS_MUNDIAL, nivel_aclimatacion

st.set_page_config(
    page_title="¿Quién gana? — Mundial 2026",
    page_icon="🏆",
    layout="wide",
)

# ===========================================================================
# AUTENTICACIÓN (validación EXCLUSIVAMENTE en el servidor)
# ===========================================================================
# Se almacena el hash SHA-256 de la contraseña, nunca el texto plano: ni el
# repositorio ni el HTML/JS del navegador contienen la clave. Streamlit
# ejecuta esta comparación en el backend; el cliente solo recibe el HTML
# renderizado del formulario. Sin components.html ni JavaScript inyectado.
import hashlib

_HASH_CLAVE = "32378eae9feab1633a0e24afb9dd4725d2d5e0cd8106dae891d55522c51d8693"
_MAX_INTENTOS = 3

if "autenticado" not in st.session_state:
    st.session_state.autenticado = False
    st.session_state.intentos_fallidos = 0


def _login():
    st.title("🔐 Acceso Restringido")
    st.write("Ingresa la contraseña para acceder al predictor del Mundial 2026.")
    if st.session_state.intentos_fallidos >= _MAX_INTENTOS:
        st.error("Demasiados intentos fallidos. Cierra la pestaña y vuelve a intentarlo.")
        st.stop()
    password = st.text_input("Contraseña", type="password", key="login_password")
    if st.button("Entrar", type="primary"):
        if hashlib.sha256(password.encode()).hexdigest() == _HASH_CLAVE:
            st.session_state.autenticado = True
            st.rerun()
        else:
            st.session_state.intentos_fallidos += 1
            restantes = _MAX_INTENTOS - st.session_state.intentos_fallidos
            st.error(f"Contraseña incorrecta. Inténtalo de nuevo "
                     f"({restantes} intento(s) restante(s)).")


if not st.session_state.autenticado:
    _login()
    st.stop()   # nada de la app real se renderiza sin autenticación

COLORES = {'local': '#2ecc71', 'empate': '#95a5a6', 'visitante': '#3498db'}


# ===========================================================================
# CARGA DEL MOTOR (una sola vez)
# ===========================================================================
@st.cache_resource(show_spinner="🔮 Cargando el motor de predicción...")
def cargar_motor() -> PredictionEngine:
    return PredictionEngine()


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
@st.cache_resource(show_spinner="⚽ Cargando el motor de la liga...")
def cargar_motor_liga(clave: str):
    from league_engine import ClubEngine
    return ClubEngine(clave)


@st.cache_data(show_spinner="📋 Calculando la plantilla del partido...")
def plantilla_club_cacheada(clave: str, home: str, away: str) -> dict:
    return cargar_motor_liga(clave).plantilla_club(home, away)


def render_liga_club(clave: str, nombre_liga: str):
    from config import LEAGUES
    if not LEAGUES[clave].get('disponible'):
        st.info(f"🔧 **{nombre_liga} (beta):** {LEAGUES[clave].get('nota', 'no disponible')}")
        st.stop()
    motor = cargar_motor_liga(clave)
    if not motor.listo:
        st.error(f"❌ Motor de {nombre_liga} no inicializado: `{motor.error}`\n\n"
                 f"Ejecuta `python league_engine.py --build {clave}`.")
        st.stop()

    st.title(f"⚽ {nombre_liga} — Predictor de clubes")
    st.caption(
        f"Datos reales (football-data.co.uk) al **{motor.fecha_estado}** · "
        f"Precisión backtesting 1X2: **{motor.metadata['precision_validacion']*100:.1f} %** "
        f"(línea base ELO {motor.metadata['precision_linea_base_elo']*100:.1f} %"
        + (f", favorito del mercado {motor.metadata['precision_mercado_cuotas']*100:.1f} %"
           if motor.metadata.get('precision_mercado_cuotas') else '') + ")"
    )
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

    st.markdown(f"### 🏆 Ganador más probable: **{p['winner']}** "
                f"({p['confidence']*100:.0f} % de confianza)")
    st.markdown(f"### ⚽ Marcador más probable: **{p['most_likely_score']}** "
                f"({p['score_probability']*100:.0f} %) · "
                f"{p['total_goals_expected']:.1f} goles esperados")
    st.markdown(f"### 📊 {home} **{p['probabilities']['home']*100:.0f} %** · "
                f"Empate **{p['probabilities']['draw']*100:.0f} %** · "
                f"{away} **{p['probabilities']['away']*100:.0f} %**")

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
        st.plotly_chart(fig_b, use_container_width=True)
    with col_g2:
        matriz = np.array(pred['score_matrix'])
        fig_h = go.Figure(go.Heatmap(
            z=matriz * 100, x=[str(i) for i in range(matriz.shape[1])],
            y=[str(i) for i in range(matriz.shape[0])], colorscale='YlOrRd',
            colorbar=dict(title='%')))
        fig_h.update_layout(xaxis_title=f"Goles {away}", yaxis_title=f"Goles {home}",
                            height=320, margin=dict(l=0, r=0, t=10, b=0))
        st.plotly_chart(fig_h, use_container_width=True)

    # ---- Plantilla extendida de clubes (editable, mismo formato) ----------
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
            st.dataframe(pd.DataFrame(hallazgos), use_container_width=True, hide_index=True)
        else:
            st.success("Tus valores coinciden con el modelo.")

    for obs in pl['observaciones']:
        st.markdown(f"- {obs}")
    from prediction_api import plantilla_a_markdown
    st.download_button("⬇️ Descargar plantilla (Markdown)",
                       data=plantilla_a_markdown(pl).encode('utf-8'),
                       file_name=f"plantilla_{clave}_{home}_vs_{away}.md".replace(' ', '_'),
                       mime="text/markdown")


COMPETENCIAS = {'🌎 Mundial 2026': 'mundial', '🇲🇽 Liga MX': 'liga_mx',
                '🏴 Premier League': 'premier', '🇪🇸 LaLiga': 'laliga',
                '🇪🇺 Champions League (beta)': 'champions'}
competencia_sel = st.sidebar.radio("🏆 Competición", list(COMPETENCIAS.keys()), index=0)
_clave_comp = COMPETENCIAS[competencia_sel]
if _clave_comp != 'mundial':
    nombres_ligas = {'liga_mx': 'Liga MX', 'premier': 'Premier League',
                     'laliga': 'LaLiga', 'champions': 'UEFA Champions League'}
    render_liga_club(_clave_comp, nombres_ligas[_clave_comp])
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
col_banner, col_boton = st.columns([5, 1])
with col_boton:
    if st.button("🔄 Actualizar datos ahora", use_container_width=True,
                 help="Ejecuta el pipeline completo (Kaggle + árbitros + estado de equipos). Tarda ~1 minuto."):
        import subprocess, sys as _sys
        with st.spinner("⏬ Descargando resultados y recalculando el estado de las 49 selecciones..."):
            proceso = subprocess.run(
                [_sys.executable, "pipeline_mundial.py"],
                capture_output=True, text=True, cwd=".", timeout=1800)
        if proceso.returncode == 0:
            st.cache_data.clear()
            st.cache_resource.clear()
            st.success("✅ Datos actualizados. Recargando...")
            st.rerun()
        else:
            st.error(f"La actualización falló:\n```\n{(proceso.stderr or '')[-800:]}\n```")

with col_banner:
    if MOTOR.fuente == 'real_hybrid':
        st.info(
            f"✅ **Resultados reales** actualizados al **{MOTOR.fecha_estado}** — "
            f"{MOTOR.fuente_detalle}. Las métricas avanzadas (remates, posesión) se "
            f"estiman con un modelo calibrado con datos reales de StatsBomb."
        )
    # Indicador de frescura: verde si incluye la fase actual del torneo
    try:
        antiguedad = (pd.Timestamp.today().normalize() -
                      pd.Timestamp(MOTOR.generado)).days
        if antiguedad >= 1:
            st.warning(
                f"⏰ **Datos del {MOTOR.generado}. Pueden no reflejar los partidos "
                f"de ayer.** Usa «Actualizar datos ahora» o espera la tarea diaria."
            )
        else:
            st.markdown(f"🟢 **Datos actualizados al {MOTOR.fecha_estado}** — incluyen "
                        f"los partidos disputados de la fase actual del torneo.")
    except Exception:
        pass

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
objetivo = MOTOR.metadata.get('objetivo_estricto', {})
if MOTOR.metadata.get('deploy_ready') and not objetivo.get('cumplido', False):
    st.caption(
        f"ℹ️ Transparencia: el objetivo estricto (precisión ≥ {objetivo.get('precision', 0.62)*100:.0f} % "
        f"y log-loss ≤ {objetivo.get('log_loss', 0.85)}) aún no se alcanza sobre partidos reales "
        f"(actual: {MOTOR.metadata.get('precision_validacion', 0)*100:.1f} % / "
        f"{MOTOR.metadata.get('log_loss_validacion', 0):.3f}). El techo teórico del 1X2 "
        f"internacional ronda el 60-65 %."
    )

# ===========================================================================
# SELECCIÓN DEL PARTIDO
# ===========================================================================
st.title("🏆 ¿Quién gana? — Mundial 2026")
st.caption(
    f"Motor topológico-predictivo · Ensemble XGBoost+RF+LightGBM calibrado · "
    f"Enfrenta a **cualquiera de las 49 selecciones clasificadas** (incluye Cabo Verde) · "
    f"Precisión backtesting: **{MOTOR.metadata.get('precision_validacion', 0)*100:.1f} %**"
)

col_sel1, col_sel2, col_sel3 = st.columns([2, 1, 1])
with col_sel1:
    opciones_fixture = ["(elegir equipos manualmente)"]
    fixture_map = {}
    for _, f in MOTOR.calendario.iterrows():
        etiqueta = (f"{NOMBRES_PAIS.get(f['home'], f['home'])} vs "
                    f"{NOMBRES_PAIS.get(f['away'], f['away'])} — "
                    f"{pd.to_datetime(f['date']).strftime('%d %b')} · {f['stadium']}")
        opciones_fixture.append(etiqueta)
        fixture_map[etiqueta] = (f['home'], f['away'])
    partido_fixture = st.selectbox("📅 Partido del fixture oficial (opcional)", opciones_fixture)

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

# ---- Árbitro designado y fase del torneo -----------------------------------
col_arb, col_fase = st.columns([3, 1])
with col_arb:
    opciones_arbitro = ["(promedio FIFA, sin asignar)"] + sorted(ARBITROS.keys())
    arbitro_sel = st.selectbox(
        "👨‍⚖️ Árbitro designado (opcional — ajusta tarjetas, rojas y penaltis)",
        opciones_arbitro,
        format_func=lambda n: n if n.startswith("(") else
        f"{n} ({ARBITROS[n]['pais']}, {ARBITROS[n]['criterio'].lower()}, {ARBITROS[n]['ama_p90']:.1f} am/90)",
    )
arbitro = None if arbitro_sel.startswith("(") else arbitro_sel
with col_fase:
    fase_sel = st.selectbox("🏆 Fase", ["Fase de grupos", "Dieciseisavos", "Octavos",
                                        "Cuartos de final", "Semifinal", "Final"])
fase = 'grupos' if fase_sel == "Fase de grupos" else 'eliminatoria'

# ---- Estadio oficial (la altitud activa la capa de aclimatación) ------------
opciones_estadio = ["(del fixture / MetLife por defecto)"] + list(ESTADIOS_MUNDIAL.keys())
estadio_sel = st.selectbox(
    "🏟️ Estadio del partido (la altitud ajusta el xG por aclimatación)",
    opciones_estadio,
    format_func=lambda k: k if k.startswith("(") else
    f"{ESTADIOS_MUNDIAL[k]['nombre']} — {ESTADIOS_MUNDIAL[k]['ciudad']} · {ESTADIOS_MUNDIAL[k]['altitud']} msnm",
)
estadio = None if estadio_sel.startswith("(") else estadio_sel

pred = prediccion_cacheada(id(MOTOR), home, away, arbitro, fase, estadio)
if 'error' in pred:
    st.error(f"❌ {pred['error']}")
    st.stop()

p = pred['prediction']
nombre_local = NOMBRES_PAIS.get(home, home)
nombre_visit = NOMBRES_PAIS.get(away, away)

tab_rapida, tab_plantilla = st.tabs(
    ["⚡ Vista Rápida", "📋 Plantilla de Análisis (editable)"]
)

# ===========================================================================
# PESTAÑA 1: VISTA RÁPIDA
# ===========================================================================
with tab_rapida:
    st.markdown(f"### 🏆 Ganador más probable: **{p['winner']}** "
                f"(con un {p['confidence']*100:.0f} % de confianza)")
    st.markdown(f"### ⚽ Marcador más probable: **{p['most_likely_score']}** "
                f"({p['score_probability']*100:.0f} % de probabilidad)")
    st.markdown(f"### 📊 Probabilidades: {nombre_local} **{p['probabilities']['home']*100:.0f} %** · "
                f"Empate **{p['probabilities']['draw']*100:.0f} %** · "
                f"{nombre_visit} **{p['probabilities']['away']*100:.0f} %**")
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
    monitor = pred.get('monitor_cambios')
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
        st.plotly_chart(fig_barras, use_container_width=True)

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
        st.plotly_chart(fig_heat, use_container_width=True)

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
        st.plotly_chart(fig_tl, use_container_width=True)

    st.divider()
    st.subheader("🧠 Lo que dicen los números (en cristiano)")
    for frase in pred['insights']:
        st.markdown(f"- {frase}")
    st.caption(f"Se esperan **{p['total_goals_expected']:.1f} goles** en total "
               f"({nombre_local}: {p['expected_goals']['home']:.1f} · "
               f"{nombre_visit}: {p['expected_goals']['away']:.1f}).")

    # ---- ¿Quién remata? -----------------------------------------------------
    st.divider()
    st.subheader("🎯 ¿Quién remata? — Goleadores reales de cada equipo")
    st.caption("Goles reales de los últimos 24 meses (fuente Kaggle); remates estimados con calibración StatsBomb.")

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
            'Remates/partido': j['remates_totales'],
            'Al arco': j['remates_al_arco'],
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
                                use_container_width=True)
                st.dataframe(tabla_rematadores(jugadores_lado),
                             use_container_width=True, hide_index=True)
            else:
                st.info(f"{emoji} {nombre_eq}: sin goleadores registrados en los últimos 24 meses.")

    # ---- 🎯 Parlay recomendado (Mejora 3, v12) --------------------------------
    st.divider()
    with st.expander("🎯 Parlay Recomendado del fixture (informativo)"):
        st.caption(
            "Selecciona los mercados de mayor probabilidad del fixture con control "
            "de correlación (máx. 2 por partido, nunca mercados dependientes). "
            "⚠️ Sin cuotas de casas conectadas, las cuotas son las JUSTAS del modelo "
            "(EV≈0): úsalo para comparar contra tu casa de apuestas. No es "
            "asesoramiento financiero."
        )
        if st.button("Generar parlay de 8 selecciones", key="btn_parlay"):
            from parlay_builder import construir_parlay
            with st.spinner("🧮 Evaluando todos los mercados del fixture..."):
                parlay = construir_parlay(MOTOR, n_legs=8)
            if 'error' in parlay:
                st.warning(parlay['error'])
            else:
                st.dataframe(pd.DataFrame([{
                    'Partido': s['partido'], 'Apuesta': s['apuesta'],
                    'Prob.': f"{s['prob']*100:.1f} %", 'Cuota': s['cuota'],
                    'Fuente': s['cuota_fuente'], 'EV': s['ev'],
                } for s in parlay['selecciones']]), use_container_width=True, hide_index=True)
                c1, c2, c3 = st.columns(3)
                c1.metric("Cuota combinada", f"{parlay['cuota_combinada']:.2f}")
                c2.metric("Prob. conjunta", f"{parlay['prob_conjunta']*100:.1f} %")
                c3.metric("EV del parlay", f"{parlay['ev_parlay']:+.3f}")
                st.caption(parlay['nota'])

    # ---- 📈 Inteligencia de mercado (Mejora 4, v12 — experimental) ------------
    with st.expander("📈 Inteligencia de Mercado — Polymarket (experimental)"):
        st.caption(
            "Probabilidades del mercado de predicción Polymarket vs el modelo, "
            "con alertas de movimientos de liquidez y divergencias. "
            "**Experimental — no es asesoramiento financiero.** Las señales del "
            "mercado NO alimentan al modelo 1X2 (evita fuga de información)."
        )
        if st.button("🔄 Actualizar Polymarket ahora", key="btn_market"):
            import market_intelligence
            with st.spinner("Consultando Polymarket..."):
                market_intelligence.actualizar(MOTOR)
        import os as _os, json as _json
        if _os.path.exists('market_data.json'):
            try:
                md_datos = _json.load(open('market_data.json', encoding='utf-8'))
            except Exception:
                md_datos = {'disponible': False}
            if md_datos.get('disponible') and md_datos.get('senales'):
                st.markdown(f"Último snapshot: **{md_datos.get('actualizado', '?')}** · "
                            f"{len(md_datos['senales'])} mercados monitorizados")
                for s in md_datos['senales'][:8]:
                    icono = {'bajo': '🟢', 'medio': '🟡', 'alto': '🔴'}[s['riesgo_manipulacion']]
                    precios = ' / '.join(f"{sal}: {pr*100:.0f} %"
                                         for sal, pr in zip(s['salidas'], s['precios']))
                    st.markdown(f"{icono} **{s['pregunta']}** — {precios} · "
                                f"volumen ${s['volumen']:,.0f}")
                    for a in s['alertas']:
                        st.markdown(f"   ⚠️ {a}")
            else:
                st.info("Polymarket no disponible en el último intento "
                        f"({md_datos.get('error', 'sin mercados del Mundial abiertos')}).")
        else:
            st.info("Aún sin datos: pulsa «Actualizar Polymarket ahora» o programa "
                    "`market_intelligence.py` cada 15 minutos.")

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
                    use_container_width=True, hide_index=True)
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
            st.dataframe(pd.DataFrame(hallazgos), use_container_width=True, hide_index=True)
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
            mime="text/markdown", use_container_width=True,
        )
    with col_d2:
        st.download_button(
            "⬇️ Descargar plantilla (con mis ediciones)",
            data=plantilla_a_markdown(pl, valores_usuario).encode('utf-8'),
            file_name=f"plantilla_{home}_vs_{away}_usuario.md",
            mime="text/markdown", use_container_width=True,
        )

st.divider()
st.caption(
    "🔬 Bajo el capó: ensemble XGBoost + Random Forest + LightGBM con calibración "
    "isotónica, entropías de persistencia H0/H1 (nube del par + últimos 10 partidos "
    "de cada equipo), regresores Poisson de goles esperados y Monte Carlo de 20,000 "
    "partidos. Backtesting temporal sobre partidos reales: "
    f"{MOTOR.metadata.get('precision_validacion', 0)*100:.1f} % de acierto · "
    f"log-loss {MOTOR.metadata.get('log_loss_validacion', 0):.3f}."
)
