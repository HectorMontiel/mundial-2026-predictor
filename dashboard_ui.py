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
import os

import numpy as np
import pandas as pd
import streamlit as st
import plotly.graph_objects as go

from prediction_api import PredictionEngine, NOMBRES_PAIS, plantilla_a_markdown
from arbitros import ARBITROS
from altitud import ESTADIOS_MUNDIAL, nivel_aclimatacion

# 1. PRIMER COMANDO DE STREAMLIT (OBLIGATORIO)
st.set_page_config(
    page_title="¿Quién gana? — Predictor deportivo",
    page_icon="🏆",
    layout="wide",
    initial_sidebar_state="expanded",
)

# v14: login con contraseña RETIRADO a petición del usuario — la app es pública.

# CSS para ocultar el branding/pie de Streamlit (aporte del repo de despliegue)
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

        /* 4. Mantener oculta la barra superior y el pie de página */
        footer, [data-testid="stHeader"] {
            display: none !important;
            visibility: hidden !important;
        }
    </style>
"""
st.markdown(limpiar_interfaz_v2, unsafe_allow_html=True)

# v47: REFRESCO AUTOMÁTICO AL ABRIR LA APP. En Streamlit Cloud el proceso es
# compartido entre visitantes, así que el caché de datos (cuotas, picks) puede
# venir de la sesión de otra persona y quedar obsoleto. Al abrir la app en una
# sesión NUEVA se limpia el caché de datos una sola vez, garantizando que cada
# usuario ve la última información al entrar. No toca @st.cache_resource (los
# modelos, que no cambian) para no recargarlos en balde.
if not st.session_state.get('_refresco_inicial'):
    st.session_state['_refresco_inicial'] = True
    try:
        st.cache_data.clear()
    except Exception:
        pass
    # v52: Streamlit Cloud hot-sincroniza ESTE script pero cachea en sys.modules
    # los módulos importados (alpha_finder, fixtures_espn, ...), así que un
    # despliegue no surtía efecto hasta reiniciar el contenedor. Al abrir una
    # sesión nueva se recargan los módulos propios en orden de dependencia, de
    # modo que cada push se refleje al instante para cada visitante.
    import sys as _sys
    import importlib as _il
    for _mod in ('config', 'name_mapper', 'fixtures_espn', 'odds_api',
                 'source_resilience', 'betexplorer_scraper', 'edge_engine',
                 'traductor_quant', 'league_engine', 'reto_escalera',
                 'data_health', 'alpha_finder', 'bot_telegram'):
        if _mod in _sys.modules:
            try:
                _il.reload(_sys.modules[_mod])
            except Exception:
                pass

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


def render_parlay_partido(motor, home: str, away: str, key: str):
    """Sección interactiva de parlay para EL partido en pantalla."""
    # v58.1 FIX: este símbolo se importa MÁS ABAJO dentro de esta misma función
    # (bloque de Kelly), lo que lo convierte en local para todo el cuerpo. Sin
    # este import al principio, usarlo antes lanzaba UnboundLocalError en
    # producción al pulsar «Proponer parlays». Se importa aquí una sola vez.
    from bankroll_manager import AVISO_JUEGO_RESPONSABLE
    # v58: VARIAS combinadas propuestas automáticamente + copiar estadísticas.
    # Universal: funciona con cualquier motor (fútbol, MLB, ...).
    st.markdown("#### 🎲 Parlays propuestos con cuotas")
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
            opciones = proponer_parlays(
                motor, home, away, max_opciones=5,
                solo_cuotas_reales=_solo_reales,
                bankroll=float(st.session_state.get('bankroll', 0) or 0))
        if not opciones:
            st.warning("No hay combinadas que superen el listón de "
                       "probabilidad para este partido (no se fuerzan parlays "
                       "soñadores).")
        else:
            st.success(f"{len(opciones)} combinadas propuestas, ordenadas por "
                       "calidad (probabilidad × cuota).")
            for i, op in enumerate(opciones, 1):
                with st.container(border=True):
                    oc1, oc2, oc3 = st.columns([2, 1, 1])
                    oc1.markdown(f"**{op['etiqueta_opcion']}** · "
                                 f"{op['n_selecciones']} patas  \n"
                                 f"{op['descripcion_opcion']}")
                    oc2.metric("Prob. de acertar todo",
                               f"{op['prob_conjunta']*100:.0f}%")
                    oc3.metric("Cuota combinada", f"{op['cuota_combinada']:.2f}",
                               help=f"100 u → {op['cuota_combinada']*100:.0f} u "
                                    "si entra.")
                    for s in op['selecciones']:
                        st.write(f"• [{s['mercado']}] **{s['apuesta']}** "
                                 f"@ {s['cuota']} · {s['prob']*100:.0f}%"
                                 + ("  ·  cuota real" if s.get('cuota_fuente') == 'real'
                                    else ""))
                    if op.get('avisos'):
                        for av in op['avisos']:
                            st.caption(av)
                    _txt = "\n".join(
                        f"{j}. [{s['mercado']}] {s['apuesta']} @ {s['cuota']} "
                        f"(p={s['prob']*100:.0f}%)"
                        for j, s in enumerate(op['selecciones'], 1))
                    _txt += (f"\nCuota combinada: {op['cuota_combinada']:.2f} · "
                             f"Prob: {op['prob_conjunta']*100:.1f}%")
                    with st.expander("📋 Copiar esta combinada"):
                        st.code(_txt, language=None)
            st.caption("⚠️ Con cuotas justas del modelo el EV es teórico: "
                       "compara contra tu casa. " + AVISO_JUEGO_RESPONSABLE)

    # v58: copiar TODAS las estadísticas del partido (universal)
    with st.expander("📋 Copiar todas las estadísticas de este partido"):
        try:
            from match_parlay import plantilla_a_texto
            _pl_txt = (motor.plantilla_club(home, away)
                       if hasattr(motor, 'plantilla_club')
                       else motor.plantilla(home, away))
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
                help="🔒 Super Seguro (v37): prioriza mercados de ALTA "
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
                _pl_cats = (motor.plantilla_club(home, away)
                            if hasattr(motor, 'plantilla_club')
                            else motor.plantilla(home, away))
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
                r = construir_parlay_partido(motor, home, away,
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
        pl_manual = (motor.plantilla_club(home, away)
                     if hasattr(motor, 'plantilla_club')
                     else motor.plantilla(home, away))
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
    if not LEAGUES[clave].get('disponible'):
        st.info(f"🔧 **{nombre_liga} (beta):** {LEAGUES[clave].get('nota', 'no disponible')}")
        st.stop()
    motor = cargar_motor_liga(clave)
    if not motor.listo:
        st.error(f"❌ Motor de {nombre_liga} no inicializado: `{motor.error}`\n\n"
                 f"Ejecuta `python league_engine.py --build {clave}`.")
        st.stop()

    st.title(f"⚽ {nombre_liga} — Predictor de clubes")
    fuente_liga = ('API-Football' if LEAGUES[clave].get('formato') == 'api_football'
                   else 'football-data.co.uk')
    st.caption(
        f"Datos reales ({fuente_liga}) al **{motor.fecha_estado}** · "
        f"Precisión backtesting 1X2: **{motor.metadata['precision_validacion']*100:.1f} %** "
        f"(línea base ELO {motor.metadata['precision_linea_base_elo']*100:.1f} %"
        + (f", favorito del mercado {motor.metadata['precision_mercado_cuotas']*100:.1f} %"
           if motor.metadata.get('precision_mercado_cuotas') else '') + ")"
    )
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
        _cat = list(motor.equipos)
        _ops = {}
        for f in _fx:
            h = _nm.mapear(f['home'], _cat, contexto=f'ui→{clave}')
            a = _nm.mapear(f['away'], _cat, contexto=f'ui→{clave}')
            if h and a and h != a:
                _ops[f"{f['fecha']} · {h} vs {a}"] = (h, a)
        if _ops:
            cfx1, cfx2 = st.columns([3, 1])
            _sel_fx = cfx1.selectbox(
                f"📅 Próximos partidos de {nombre_liga} ({len(_ops)})",
                list(_ops.keys()), key=f"fx_sel_{clave}",
                help="Elige un partido programado y pulsa «Cargar» para "
                     "rellenar los equipos automáticamente.")
            if cfx2.button("⬇️ Cargar", key=f"fx_btn_{clave}", width='stretch'):
                h, a = _ops[_sel_fx]
                st.session_state[f"club_home_{clave}"] = h
                st.session_state[f"club_away_{clave}"] = a
                st.rerun()

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

    # v15: parlay del partido en pantalla
    st.divider()
    render_parlay_partido(motor, home, away, key=clave)
    render_h2h_club(clave, home, away, key=clave)
    render_comparador(motor, motor.equipos, key=clave)      # v25 (§2.4)
    render_rendimiento(key=clave)

    from prediction_api import plantilla_a_markdown
    st.download_button("⬇️ Descargar plantilla (Markdown)",
                       data=plantilla_a_markdown(pl).encode('utf-8'),
                       file_name=f"plantilla_{clave}_{home}_vs_{away}.md".replace(' ', '_'),
                       mime="text/markdown")


COMPETENCIAS = {'🌍 Partidos Internacionales': 'mundial',
                '💎 Apuestas del Día': 'alpha',
                '⚾ MLB (béisbol)': 'mlb_deporte',
                '🏀 NBA (baloncesto)': 'nba_deporte',
                '🎾 Tenis (ATP/WTA)': 'tennis_deporte',
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
                 'conference_league': 'UEFA Conference League'}
# v23 (móvil): el selector de competición vive ARRIBA del área principal —
# en el teléfono la barra lateral llega colapsada y el usuario no encontraba
# las ligas. El estado se comparte con st.session_state.
competencia_sel = st.selectbox(
    "🏆 Competición", list(COMPETENCIAS.keys()), index=0, key='competencia',
    help="En móvil: elige aquí la liga; los controles finos (modo, bankroll) "
         "siguen en la barra lateral (botón » arriba a la izquierda).")
st.sidebar.checkbox(
    "🤖 Reescribir comentarios con SLM local (Ollama)", value=False, key='usar_slm',
    help="Opcional y solo en ejecución local: si tienes Ollama corriendo "
         "(OLLAMA_MODEL, por defecto phi3), el comentario del analista se "
         "reescribe con el modelo. Sin Ollama, se usa el comentario base.")

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
BANKROLL = st.sidebar.number_input(
    "💵 Mi bankroll (unidades)", min_value=0.0, max_value=1_000_000.0,
    value=1000.0, step=100.0, key='bankroll',
    help="Tu banca total para apostar. Con cuotas reales y EV positivo, la "
         "app sugiere el stake por ¼ de Kelly (tope 5 % del bankroll por "
         "apuesta). Solo informativo.")

def render_alpha_finder():
    """v26 (§4.1-§4.2): Apuestas del Día + simulador Montecarlo de bankroll."""
    st.header("💎 Apuestas del Día")
    st.caption("Barrido UNIVERSAL (v51): TODAS las ligas con jornada (fixtures "
               "ESPN, sin depender de cuotas) + ⚾ MLB, 🏀 NBA y 🎾 tenis ATP/WTA. "
               "**Capa 1** = cuota real con EV; **Capa 2** = alta confianza sin "
               "cuota en vivo; **Pronósticos** = cobertura completa del día.")
    # v47/v49: acciones SIEMPRE visibles arriba — refrescar y enviar a Telegram
    # (el botón de Telegram estaba escondido en un expander; ahora es fijo).
    cacc1, cacc2 = st.columns(2)
    if cacc1.button("🔄 Actualizar ahora", key='refresh_alpha', width='stretch',
                    help="Vuelve a bajar cuotas y recalcula todas las apuestas."):
        st.cache_data.clear()
        st.rerun()
    if cacc2.button("📤 Enviar a Telegram ahora", key='tg_send_top',
                    width='stretch', type="primary",
                    help="Envía el resumen del día a tu Telegram (mismo mensaje "
                         "que el envío diario automático)."):
        try:
            import bot_telegram
            msg = bot_telegram.construir_mensaje()
            if bot_telegram.enviar(msg):
                st.success("✅ Enviado a Telegram.")
            else:
                st.warning("Sin TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID en los "
                           "Secrets. Vista previa del mensaje:")
                st.code(msg, language=None)
        except Exception as e:
            st.error(f"No se pudo enviar ({type(e).__name__}: {e}).")

    @st.cache_data(ttl=1800, show_spinner="🔍 Buscando valor en todos los deportes…")
    def _buscar():
        import alpha_finder
        return alpha_finder.apuestas_del_dia_universal()

    r = _buscar()
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

    # v32 (§5.3): PICK DEL DÍA único
    pdd = r.get('pick_del_dia')
    if pdd:
        st.success(f"🥇 **Pick del Día** — {pdd['partido']} ({pdd.get('liga','')})  \n"
                   f"**{pdd['apuesta']}** @ {pdd.get('cuota')} · "
                   f"EV {(pdd.get('ev') or 0)*100:+.1f} % · "
                   f"prob {(pdd.get('prob') or 0)*100:.0f} % · "
                   f"{pdd.get('fiabilidad','')}")
    else:
        st.info("🥇 Hoy **no hay Pick del Día**: ninguno reúne confianza >80 %, "
                "EV entre +2 % y +15 % y fiabilidad histórica suficiente. "
                "Forzarlo sería el error clásico.")

    # v53: COMBINADA DEL DÍA (un solo partido) — la app propone automáticamente
    # la combinada más SEGURA de mercados del MISMO partido para el mejor pick
    # de fútbol del día. Es "la mejor selección propuesta" surfaceada en
    # Apuestas del Día (el usuario la pidió aquí, no solo por partido).
    cand_combo = pdd if (pdd and pdd.get('deporte', 'Fútbol') == 'Fútbol') else None
    if not cand_combo:
        for _p in (r.get('capa1') or []):
            if _p.get('deporte', 'Fútbol') == 'Fútbol':
                cand_combo = _p
                break
    if cand_combo:
        _REV_LIGAS = {v: k for k, v in NOMBRES_LIGAS.items()}
        _clave_liga = _REV_LIGAS.get(cand_combo.get('liga', ''))
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

    # v58: COMBINADAS DEL DÍA — varias, de distintos partidos y perfiles. Se
    # arman sobre los mejores partidos del día (Capa 1 y pronósticos) para que
    # el usuario tenga una selección amplia y no solo la "súper segura".
    st.divider()
    with st.expander("🎲 Combinadas del Día — varias opciones con cuota", expanded=False):
        st.caption("Combinadas de UN SOLO partido (más controlables que las "
                   "multi-partido), de los mejores encuentros del día. Escalera "
                   "de la más segura a la de más cuota.")
        if st.button("🎲 Generar combinadas del día", key='combo_dia_btn',
                     type="primary"):
            from bankroll_manager import AVISO_JUEGO_RESPONSABLE   # v58.1 FIX
            from match_parlay import proponer_parlays
            _REV = {v: k for k, v in NOMBRES_LIGAS.items()}
            # candidatos: mejores picks de fútbol del día (Capa 1 → pronósticos)
            vistos, candidatos = set(), []
            for p in ((r.get('capa1') or []) + (r.get('seleccion_dia') or [])
                      + (r.get('pronosticos') or [])):
                if p.get('deporte', 'Fútbol') != 'Fútbol':
                    continue
                cl = _REV.get(p.get('liga', ''))
                partes = str(p.get('partido', '')).split(' vs ')
                if not cl or len(partes) != 2 or p['partido'] in vistos:
                    continue
                vistos.add(p['partido'])
                candidatos.append((cl, partes[0].strip(), partes[1].strip()))
                if len(candidatos) >= 4:
                    break
            if not candidatos:
                st.info("Hoy no hay partidos con datos suficientes para armar "
                        "combinadas.")
            with st.spinner("Armando combinadas de los mejores partidos…"):
                for cl, h, a in candidatos:
                    try:
                        ops = proponer_parlays(cargar_motor_liga(cl), h, a,
                                               max_opciones=3)
                    except Exception as e:
                        st.caption(f"{h} vs {a}: no disponible ({type(e).__name__}).")
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

    def _tarjetas(lista, titulo):
        if not lista:
            return
        if titulo:
            st.subheader(titulo)
        for t in lista:
            pref = ('💠 ' if t.get('sharp_confirmado') else '') \
                + ('⭐ ' if t.get('platino') else '') \
                + ('⚡ ' if t.get('shadow') else '')
            # v31: las tarjetas sirven a las DOS capas — con cuota real
            # (EV) o sin ella (cuota mínima sugerida). Todo defensivo.
            cuota = t.get('cuota')
            if cuota:
                precio = (f"{t.get('valor','')} Cuota **{cuota}** "
                          f"(justa {t.get('cuota_justa','?')})  \n"
                          f"EV **{(t.get('ev') or 0)*100:+.1f} %** · "
                          f"prob {(t.get('prob') or 0)*100:.0f} %")
            else:
                precio = (f"🎯 Sin cuota en vivo  \n"
                          f"Cuota mínima sugerida **{t.get('cuota_justa','?')}** · "
                          f"prob {(t.get('prob') or 0)*100:.0f} %")
            with st.container(border=True):
                c1, c2, c3 = st.columns([3, 2, 2])
                c1.markdown(f"**{pref}{t.get('partido','?')}**  \n"
                            f"{t.get('deporte','Fútbol')} · {t.get('liga','')} · "
                            f"{t.get('fecha','')}"
                            + (f"  \n{t['antiguedad']}" if t.get('antiguedad')
                               else ''),
                            help=("Frescura de los datos con los que se entrenó "
                                  "esta liga: el modelo no ve partidos nuevos "
                                  "desde hace ese número de días.")
                            if t.get('antiguedad') else None)
                c2.markdown(f"**{t.get('apuesta','?')}**  \n{t.get('mercado','')}")
                rent = t.get('rentabilidad') or {}
                _gap = t.get('sharp_gap')
                import traductor_quant as _tq
                c3.markdown(precio
                            + (f"  \n**{_tq.frase_sharp(_gap, ES_PRO)}**"
                               if t.get('sharp_confirmado') else '')
                            + (f"  \n🏠 mejor cuota en **{t['casa']}**" if t.get('casa') else '')
                            + (f"  \n{t['fiabilidad']}" if t.get('fiabilidad') else '')
                            + (f"  \n{rent['etiqueta']}" if rent.get('etiqueta')
                               and rent.get('tier') != 'sin_ev' else '')
                            + (f"  \n💼 Stake: **{t['stake_txt']}**"
                               if t.get('stake_txt') else '')
                            + (f"  \nℹ️ {t['nota_seleccion']}" if t.get('nota_seleccion') else '')
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

    # v27 (§5+§7): stakes por Kelly SIMULTÁNEO (⅛, cap global 20 %)
    elite = r.get('elite') or []
    if elite:
        import kelly_simultaneo as ks
        bank = float(st.session_state.get('bankroll', 0) or 1000)
        con_stake = ks.stakes_jornada(elite, bank)
        for t, s in zip(elite, con_stake):
            t['stake_txt'] = (f"{s['stake']:.0f} u ({s['stake_pct']*100:.1f} %)"
                              if s['stake_pct'] > 0 else '—')
        expo = sum(s['stake_pct'] for s in con_stake)
        st.caption(f"💼 Exposición total de la jornada: {expo*100:.1f} % del "
                   f"bankroll (⅛ Kelly simultáneo, cap 20 % — v27).")
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
    seleccion = r.get('seleccion_dia') or []
    if not elite and seleccion:
        st.subheader("⭐ Selección del Día — mejor valor disponible")
        st.info("Hoy ninguna apuesta reunió cuota real + confirmación profesional. "
                "Estas son las de mayor valor esperado del día. Úsalas con stake "
                "prudente: no llevan el sello de la línea sharp.")
        _tarjetas(seleccion, "")

    # v31 (§5): CAPA 2 — alta confianza SIN cuota real (modo analítico)
    capa2 = r.get('capa2') or []
    if capa2:
        st.divider()
        st.subheader("🎯 Capa 2 — Predicciones de Alta Confianza"
                     if ES_PRO else "🎯 Apuestas sugeridas (sin cuota confirmada)")
        st.warning("Sin cuotas en vivo para estos partidos: compara "
                   "manualmente con tu casa. Solo apuesta si te ofrecen MÁS "
                   "que la cuota mínima sugerida. No se calcula stake.")
        _tarjetas(capa2, "")

    # v37 (§6): sección destacada de Ambos Marcan (BTTS)
    btts = r.get('btts_destacado') or []
    if btts:
        st.divider()
        st.subheader("⚽ Ambos Marcan (BTTS)")
        st.caption("Uno de los mercados mejor calibrados del sistema (modelo de "
                   "supervivencia Weibull, v27). Picks con confianza > 70 %"
                   + (" y EV > +3 % donde hay cuota real." if any(p.get('cuota')
                      for p in btts) else "."))
        _tarjetas(btts, "")

    # v49: TODOS LOS PRONÓSTICOS DEL DÍA — cada partido con jornada, aunque no
    # haya cuota en vivo (el modelo da su 1X2 con cuota justa). Máxima cobertura
    # de opciones sin relajar los filtros de la Capa 1.
    pronos = r.get('pronosticos') or []
    if pronos:
        st.divider()
        st.subheader(f"📋 Todos los pronósticos del día ({len(pronos)})")
        st.caption("Cobertura completa: el 1X2 del modelo para cada partido "
                   "programado, con cuota justa (1/probabilidad). Informativo — "
                   "solo la Capa 1 lleva EV validado.")
        import pandas as _pd
        def _pct(v):
            return f"{v*100:.0f}%" if isinstance(v, (int, float)) else '—'
        filas_p = []
        for p in sorted(pronos, key=lambda x: (x.get('fecha', ''),
                                               -(x.get('prob') or 0))):
            board = p.get('board') or {}
            partes = p.get('partido', ' vs ').split(' vs ')
            home = partes[0] if partes else ''
            away = partes[-1] if len(partes) > 1 else ''
            filas_p.append({
                'Fecha': p.get('fecha', ''), 'Liga': p.get('liga', ''),
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
        st.dataframe(_pd.DataFrame(filas_p), hide_index=True, width='stretch')
        st.caption("1/X/2 = victoria local / empate / visitante · +2.5/−2.5 = "
                   "más/menos de 2.5 goles · BTTS = ambos marcan. Todas con la "
                   "probabilidad del modelo (cuota justa = 1/prob).")

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

    # v47: ENVIAR A TELEGRAM AHORA — el usuario quiere un botón bajo demanda
    # además del envío diario automático (GitHub Actions).
    st.divider()
    with st.expander("📲 Enviar estas apuestas a Telegram"):
        st.caption("Envía el resumen completo del día a tu canal de Telegram. "
                   "El envío automático diario sigue activo por separado.")
        if st.button("📤 Enviar a Telegram ahora", key='tg_send', type="primary"):
            try:
                import bot_telegram
                msg = bot_telegram.construir_mensaje()
                if bot_telegram.enviar(msg):
                    st.success("✅ Enviado a Telegram.")
                else:
                    st.warning("No hay TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID "
                               "configurados en los Secrets. Vista previa abajo:")
                    st.code(msg, language=None)
            except Exception as e:
                st.error(f"No se pudo enviar ({type(e).__name__}: {e}).")

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
    with st.expander("📉 Rentabilidad y CLV (motor v38)"):
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
            st.markdown(f"**🎯 Selección rentable validada (v40):** EV "
                        f"{lo*100:.0f}–{hi*100:.0f} % · prob ≥ "
                        f"{edge_engine.piso_prob()*100:.0f} % · convicción "
                        f"prob×EV ≥ {edge_engine.conviccion_min():.3f}.")
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

    if r.get('no_enlazados'):
        with st.expander(f"ℹ️ {len(r['no_enlazados'])} partidos no evaluados "
                         "(nombre no enlazado con el modelo)"):
            st.caption("No se descartan en silencio: el nombre de la casa no "
                       "cruzó con el catálogo del modelo (jugador nuevo o "
                       "grafía distinta).")
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
                       "⚠️ recuerda: los EV por encima de +15 % son la zona "
                       "que el backtest v32 marcó como poco fiable.")
            st.dataframe(pd.DataFrame(rv['filas'])[
                ['partido', 'liga', 'mercado', 'cuota_inicial', 'cuota_actual',
                 'ev_pct', 'tendencia', 'snapshots']],
                width='stretch', hide_index=True)

    # v32 (§6): rendimiento REAL de lo recomendado
    with st.expander("📊 Rendimiento real de las Apuestas del Día"):
        import rendimiento_real as rreal
        res7, res30 = rreal.resumen(7), rreal.resumen(30)
        if res30.get('n'):
            c1, c2, c3 = st.columns(3)
            c1.metric("Aciertos (30 d)",
                      f"{res30['tasa_acierto']*100:.0f} %",
                      f"prometido {res30['prob_media_prometida']*100:.0f} %")
            c2.metric("ROI real (30 d)", f"{res30['roi_pct']:+.1f} %")
            c3.metric("Picks (7 d / 30 d)", f"{res7.get('n',0)} / {res30['n']}")
            serie = rreal.serie_diaria(30)
            if not serie.empty:
                st.line_chart(serie.set_index('fecha')['roi_acumulado_pct'])
        else:
            st.info(res30.get('aviso', 'Sin historial todavía.')
                    + " Los picks se registran automáticamente cada día; el "
                      "resultado se liquida cuando termina el partido.")

    _tarjetas(r.get('candidatos'), "Candidatos con EV positivo"
              if ES_PRO else "Otras oportunidades con Ventaja Matemática 📈")
    if r.get('deportes_cubiertos'):
        st.caption(f"🌐 Deportes cubiertos hoy: "
                   f"{', '.join(r['deportes_cubiertos'])}.")
    from bankroll_manager import AVISO_JUEGO_RESPONSABLE
    st.caption(AVISO_JUEGO_RESPONSABLE)

    # v27 (§4): arbitraje de mercado cruzado (gasta ~5 requests por corrida)
    with st.expander("💹 " + tq.t('arbitraje', ES_PRO)):
        st.caption(("Valora double chance, draw no bet y totales alternativos "
                    "(líneas .5) con la matriz exacta del motor. Señal si la "
                    "cuota supera la justa en >5 % Y el índice "
                    + tq.t('vaca', ES_PRO) + " > 1 (v28: solo oportunidades "
                    "estables).") if ES_PRO else
                   (tq.tooltip('arbitraje') + " " + tq.tooltip('vaca')))
        if st.button("🔍 Buscar oportunidades ahora (usa ~5 créditos de API)",
                     key='arb_btn'):
            import cross_arbitrage
            with st.spinner("Valorando mercados derivados…"):
                ra = cross_arbitrage.analizar()
            if ra.get('aviso'):
                st.info(ra['aviso'])
            if ra['oportunidades']:
                st.dataframe(pd.DataFrame(ra['oportunidades']),
                             width='stretch', hide_index=True)

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


# v28 (§1): auto-actualización de cuotas nativa de Streamlit — sin
# subprocesos ni cron. TTL 6 h; cada refresco alimenta además los snapshots
# RLM del tier-1 (§2.1) con presupuesto gestionado en odds_api.
@st.cache_data(ttl=21600, show_spinner="⏳ Actualizando cuotas…")
def cargar_cuotas_actualizadas() -> dict:
    try:
        import odds_api
        rem = odds_api.creditos_restantes()
        if rem is not None and rem < odds_api.MIN_CREDITOS_MES:
            return {'ok': False,
                    'aviso': f'Cuotas sin actualizar por límite de API '
                             f'({rem} créditos restantes este mes).'}
        import fetch_odds
        fetch_odds.actualizar_odds()
        return {'ok': True, 'aviso': None,
                'restantes': odds_api.creditos_restantes()}
    except Exception as e:
        return {'ok': False, 'aviso': f'Cuotas no actualizadas ({e}) — se usa '
                                      'la última captura disponible.'}


_cuotas_estado = cargar_cuotas_actualizadas()
if _cuotas_estado.get('aviso'):
    st.caption(f"⚠️ {_cuotas_estado['aviso']}")

def render_mlb():
    """v29 (§3-§6): vista del motor MLB (béisbol), aislada del fútbol."""
    st.header("⚾ MLB — Béisbol")
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
    st.caption(f"Modelo entrenado con {md.get('n_juegos')} juegos (Retrosheet "
               f"2021-2025) · precisión backtest {md.get('precision_validacion')*100:.1f} % "
               f"(ELO {md.get('precision_linea_base_elo')*100:.1f} %) · estado de "
               f"equipos congelado al cierre de 2025 hasta que Retrosheet "
               "publique 2026.")

    nombres = {c: CODIGO_A_NOMBRE.get(c, c) for c in eng.equipos}
    tab1, tab2 = st.tabs(["🎯 Predecir partido", "💰 Apuestas del Día MLB"])
    with tab1:
        c1, c2 = st.columns(2)
        home = c1.selectbox("🏠 Local", eng.equipos,
                            format_func=lambda c: nombres.get(c, c), key='mlb_h')
        away = c2.selectbox("✈️ Visitante", eng.equipos,
                            index=1, format_func=lambda c: nombres.get(c, c),
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
            # v56: combinador de mercados (manual + automático) para MLB
            render_parlay_partido(eng, home, away, key='mlb')
    with tab2:
        st.caption("Cuotas en vivo de The Odds API (baseball_mlb, EE. UU.). "
                   "Filtros: prob >58 %, EV >+3 %, cuota >1.50.")
        if st.button("🔍 Buscar picks MLB de hoy (usa 1 crédito de API)",
                     key='mlb_alpha'):
            with st.spinner("Consultando cuotas MLB…"):
                r = eng.apuestas_dia()
            if r.get('aviso'):
                st.info(r['aviso'])
            for pk in r['picks']:
                with st.container(border=True):
                    cc1, cc2 = st.columns([3, 2])
                    cc1.markdown(f"**{pk['partido']}**  \n{pk['fecha']}")
                    cc2.markdown(f"{pk['valor']} {pk['apuesta']}  \n"
                                 f"Cuota **{pk['cuota']}** (justa {pk['cuota_justa']}) · "
                                 f"EV **{pk['ev']*100:+.1f} %**")
            from bankroll_manager import AVISO_JUEGO_RESPONSABLE
            st.caption(AVISO_JUEGO_RESPONSABLE)


def render_nba():
    """v30 (§4): vista NBA — modo analítico (sin cuotas en vivo hasta oct 2026)."""
    st.header("🏀 NBA — Baloncesto")
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
    c1, c2 = st.columns(2)
    home = c1.selectbox("🏠 Local", eng.equipos, key='nba_h')
    away = c2.selectbox("✈️ Visitante", eng.equipos, index=1, key='nba_a')
    if home != away:
        pl = eng.plantilla(home, away)
        pr = pl['prediccion']
        m1, m2, m3 = st.columns(3)
        m1.metric(f"Gana {home}", f"{pr['prob_home']*100:.0f} %")
        m2.metric(f"Gana {away}", f"{pr['prob_away']*100:.0f} %")
        m3.metric("Puntos totales (est.)", f"{pr['total_estimado']:.0f}")
        st.caption("🎾/🏀 Modo analítico: cuota justa = 1/probabilidad; sin EV "
                   "real hasta que The Odds API reactive la NBA en octubre.")


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
    st.header("🎾 Tenis — ATP / WTA")
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
    st.caption(f"Entrenado con {md.get('n_partidos')} partidos "
               f"({eng.circuito.upper()}, mirror de Kaggle) · precisión "
               f"{_pct(md.get('precision_validacion'))} (ranking "
               f"{_pct(md.get('precision_linea_base_elo'))}, mercado "
               f"{_pct(md.get('precision_mercado'))}).")
    c1, c2, c3 = st.columns(3)
    p1 = c1.selectbox("Jugador 1", eng.jugadores, key='ten_1')
    p2 = c2.selectbox("Jugador 2", eng.jugadores, index=1, key='ten_2')
    sup = c3.selectbox("Superficie", ['Hard', 'Clay', 'Grass'], key='ten_s')
    c4, c5 = st.columns(2)
    indoor = c4.checkbox("Pista cubierta (indoor)", key='ten_in')
    formato = c5.radio("Formato", ['Al mejor de 3 sets', 'Al mejor de 5 sets (Grand Slam)'],
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


_clave_comp = COMPETENCIAS[competencia_sel]
if _clave_comp == 'mlb_deporte':
    render_mlb()
    st.stop()
if _clave_comp == 'nba_deporte':
    render_nba()
    st.stop()
if _clave_comp == 'tennis_deporte':
    render_tennis()
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
col_banner, col_boton = st.columns([5, 1])
with col_boton:
    if st.button("🔄 Actualizar datos ahora", width='stretch',
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
            from live_worldcup import fase_del_torneo
            fase_actual = fase_del_torneo(MOTOR.fecha_estado)
            st.markdown(f"🟢 **Datos actualizados al {MOTOR.fecha_estado}**"
                        + (f" — incluyen partidos de **{fase_actual}**." if fase_actual
                           else " — incluyen los partidos disputados de la fase actual."))
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
st.title("🏆 ¿Quién gana? — Predictor deportivo")
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
                       f"gol de cada lado. Desde la v27 este modelo ES el "
                       "BTTS oficial de la plantilla (transición validada).")
    except Exception:
        pass

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

    # ---- 🎯 Parlay del partido en pantalla (v15) ------------------------------
    st.divider()
    render_parlay_partido(MOTOR, home, away, key='mundial')
    render_h2h_mundial(home, away)
    from config import TEAMS as _TEAMS
    render_comparador(MOTOR, sorted(_TEAMS), key='mundial')     # v25 (§2.4)
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
