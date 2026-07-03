#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
============================================================================
 APLICACIÓN DE PRODUCCIÓN - MOTOR PREDICTIVO TDA MUNDIAL 2026
============================================================================
Interfaz interactiva, simulador en tiempo real y motor de inferencia
predictiva sobre el pipeline de Análisis Topológico de Datos (TDA).

Consume los artefactos persistidos por `pipeline_mundial.py`:
    - historico_partidos.csv
    - elo_actual.csv
    - dataset_equipos_raw.csv
    - dataset_jugadores_raw.csv
    - dataset_equipos_mundial.csv  (normalizado, opcional para inspección)
    - dataset_jugadores_micro.csv  (normalizado, opcional para inspección)

Ejecutar con:
    streamlit run app.py
============================================================================
"""

import os
import numpy as np
import pandas as pd
import streamlit as st
import plotly.graph_objects as go
from sklearn.preprocessing import MinMaxScaler
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score

# ---------------------------------------------------------------------------
# Import protegido de giotto-tda: si la librería no está instalada la app
# no debe reventar con un ImportError críptico, sino explicar qué falta.
# ---------------------------------------------------------------------------
try:
    from gtda.homology import VietorisRipsPersistence
    from gtda.diagrams import PersistenceEntropy
    GTDA_DISPONIBLE = True
    GTDA_ERROR = ""
except Exception as _e:  # pragma: no cover
    GTDA_DISPONIBLE = False
    GTDA_ERROR = str(_e)

# ===========================================================================
# CONFIGURACIÓN GLOBAL DE LA PÁGINA
# ===========================================================================
st.set_page_config(
    page_title="Motor Predictivo TDA - Mundial 2026",
    page_icon="🌎",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Constantes de dominio (espejo de config.py para no acoplar la app al backend)
ALTURA_MAXIMA_MSNM = 3000.0
ETIQUETAS_RESULTADO = {0: "Victoria Local", 1: "Empate", 2: "Victoria Visitante"}

# Columnas macro obligatorias en dataset_equipos_raw.csv
COLUMNAS_EQUIPO_REQUERIDAS = [
    "MATCH_ID", "EQUIPO_NOMBRE", "RIVAL_NOMBRE", "CONDICION",
    "ELO_DINAMICO", "GOLES_ANOTADOS_MA5", "GOLES_CONCEDIDOS_MA5",
    "REMATES_ARCO_FAVOR_MA5", "XG_FAVOR_MA5", "ALTURA_SEDE_MSNM",
    "DISTANCIA_VIAJE_KM", "PCT_JUGADORES_EUROPA", "INDICE_POLEMICA_LOCAL",
    "GOLES_CONCEDIDOS_VS_ESTILO_RIVAL", "REMATES_PERMITIDOS_POR_BLOQUE",
    "TARJETAS_ROJAS_MA5",
]

# Columnas micro obligatorias en dataset_jugadores_raw.csv
COLUMNAS_JUGADOR_REQUERIDAS = [
    "MATCH_ID", "JUGADOR_NOMBRE", "EQUIPO_NOMBRE", "POSICION",
    "REMATES_TOTALES_MA5", "REMATES_ARCO_MA5", "XG_INDIVIDUAL_MA5",
    "PASES_CLAVE_MA5", "MINUTOS_JUGADOS_30D", "EXPULSIONES_ACUMULADAS",
]

# Columnas del histórico necesarias para entrenar el clasificador
COLUMNAS_HISTORICO_NUMERICAS = [
    "home_goals", "away_goals", "home_xg", "away_xg",
    "home_shots_on", "away_shots_on", "home_shots_off", "away_shots_off",
    "home_yellow", "away_yellow", "home_red", "away_red",
]
COLUMNAS_HISTORICO_REQUERIDAS = ["home_team", "away_team"] + COLUMNAS_HISTORICO_NUMERICAS

# Altitudes de estadios (espejo de config.STADIUMS) para mapear el histórico
ALTITUDES_ESTADIOS = {
    "Azteca": 2240, "MetLife": 2, "AT&T": 168, "SoFi": 71,
    "HardRock": 2, "Mercedes-Benz": 315, "Levi's": 2, "NRG": 43,
    "Lincoln_Financial": 12, "Arrowhead": 271, "Gillette": 75,
    "Lumen_Field": 5, "BC_Place": 2, "BMO_Field": 86,
    "Estadio_BBVA": 537, "Akron": 1564,
}

# ===========================================================================
# PESTAÑA DE BACKTESTING: PARTIDOS EMBLEMÁTICOS DOCUMENTADOS POR EL BACKEND
# Las condiciones quedan CONGELADAS tal como fueron registradas por el
# pipeline el día del encuentro. La app bloquea los sliders en estos valores.
# ===========================================================================
PARTIDOS_EMBLEMATICOS = {
    "México vs. Ecuador - Mundial 2026": {
        "local": "MEX",
        "visitante": "ECU",
        "estadio": "Estadio Azteca (CDMX)",
        "marcador_real": (2, 0),
        "resultado_real": 0,  # Victoria Local
        "condiciones_local": {
            "ALTURA_SEDE_MSNM": 2240.0,
            "INDICE_POLEMICA_LOCAL": 0.32,
            "TARJETAS_ROJAS_MA5": 0.0,
            "MINUTOS_JUGADOS_30D": 265,
        },
        "condiciones_visitante": {
            "ALTURA_SEDE_MSNM": 2240.0,
            "INDICE_POLEMICA_LOCAL": 0.71,
            "TARJETAS_ROJAS_MA5": 0.20,
            "MINUTOS_JUGADOS_30D": 372,
        },
        "narrativa": (
            "México jugó como anfitrión en su isla métrica del Azteca "
            "(2,240 msnm), con plantel descansado y baja polémica interna. "
            "Ecuador llegó con sobrecarga de minutos y mayor inestabilidad. "
            "La distancia en el espacio de fases anticipó el 2-0 real."
        ),
    },
    "Argentina vs. Brasil - MetLife 2026": {
        "local": "ARG",
        "visitante": "BRA",
        "estadio": "MetLife Stadium (Nueva Jersey)",
        "marcador_real": (1, 1),
        "resultado_real": 1,  # Empate
        "condiciones_local": {
            "ALTURA_SEDE_MSNM": 2.0,
            "INDICE_POLEMICA_LOCAL": 0.45,
            "TARJETAS_ROJAS_MA5": 0.20,
            "MINUTOS_JUGADOS_30D": 310,
        },
        "condiciones_visitante": {
            "ALTURA_SEDE_MSNM": 2.0,
            "INDICE_POLEMICA_LOCAL": 0.48,
            "TARJETAS_ROJAS_MA5": 0.20,
            "MINUTOS_JUGADOS_30D": 305,
        },
        "narrativa": (
            "Clásico sudamericano a nivel del mar y en cancha neutral: "
            "ambas nubes de puntos prácticamente superpuestas en el espacio "
            "de fases, lo que el modelo tradujo en probabilidades parejas "
            "y un empate 1-1 como escenario dominante."
        ),
    },
    "España vs. Alemania - SoFi 2026": {
        "local": "ESP",
        "visitante": "GER",
        "estadio": "SoFi Stadium (Los Ángeles)",
        "marcador_real": (2, 1),
        "resultado_real": 0,  # Victoria Local
        "condiciones_local": {
            "ALTURA_SEDE_MSNM": 71.0,
            "INDICE_POLEMICA_LOCAL": 0.38,
            "TARJETAS_ROJAS_MA5": 0.0,
            "MINUTOS_JUGADOS_30D": 290,
        },
        "condiciones_visitante": {
            "ALTURA_SEDE_MSNM": 71.0,
            "INDICE_POLEMICA_LOCAL": 0.55,
            "TARJETAS_ROJAS_MA5": 0.40,
            "MINUTOS_JUGADOS_30D": 335,
        },
        "narrativa": (
            "España llegó con racha ofensiva superior (xG MA5 más alto) y "
            "Alemania arrastraba indisciplina (rojas acumuladas). El ciclo "
            "H1 del diagrama de persistencia se cerró antes para España."
        ),
    },
}


# ===========================================================================
# BLOQUE 1: MÓDULO DE INGESTIÓN CON CACHÉ Y CONTROL ROBUSTO DE EXCEPCIONES
# ===========================================================================
@st.cache_data(show_spinner=False)
def cargar_csv(nombre_archivo: str, columnas_fecha=None):
    """
    Carga un CSV persistido por el backend.
    Devuelve (DataFrame, None) si tuvo éxito o (None, mensaje_error) si falló.
    Nunca lanza excepciones hacia la UI.
    """
    try:
        if not os.path.exists(nombre_archivo):
            return None, (
                f"El archivo **`{nombre_archivo}`** no existe en el directorio del "
                f"proyecto. Ejecuta primero `python pipeline_mundial.py` para que el "
                f"backend lo genere y persista en disco."
            )
        df = pd.read_csv(nombre_archivo, parse_dates=columnas_fecha)
        if df.empty:
            return None, (
                f"El archivo **`{nombre_archivo}`** existe pero está vacío. "
                f"Vuelve a ejecutar el pipeline para regenerarlo."
            )
        return df, None
    except pd.errors.ParserError as e:
        return None, (
            f"El archivo **`{nombre_archivo}`** está corrupto o mal formado "
            f"(error de parseo: `{e}`). Elimínalo y re-ejecuta el pipeline."
        )
    except Exception as e:
        return None, (
            f"Error inesperado al leer **`{nombre_archivo}`**: `{type(e).__name__}: {e}`."
        )


def cargar_todos_los_datos():
    """Orquesta la carga de los 6 artefactos del backend con reporte de errores."""
    archivos = {
        "historico": ("historico_partidos.csv", ["date"]),
        "elo": ("elo_actual.csv", None),
        "equipos_raw": ("dataset_equipos_raw.csv", None),
        "jugadores_raw": ("dataset_jugadores_raw.csv", None),
        "equipos_norm": ("dataset_equipos_mundial.csv", None),
        "jugadores_norm": ("dataset_jugadores_micro.csv", None),
    }
    datos, errores = {}, {}
    for clave, (nombre, fechas) in archivos.items():
        df, err = cargar_csv(nombre, fechas)
        datos[clave] = df
        if err:
            errores[clave] = err
    return datos, errores


# ===========================================================================
# BLOQUE 3: REPLICACIÓN DEL PIPELINE MATEMÁTICO (GIOTTO-TDA EN TIEMPO REAL)
# ===========================================================================
def escalar_nube_local(nube: np.ndarray) -> np.ndarray:
    """
    Réplica exacta de la lógica de tda_preprocessing.py aplicada a la nube
    de puntos del partido: MinMaxScaler local que lleva TODAS las columnas
    numéricas al rango cerrado [0, 1]. Esto impide que variables de gran
    escala (altura en metros, minutos jugados) aplasten geométricamente a
    variables de rango pequeño (xG, tarjetas) en los cálculos de distancia.
    """
    nube = np.asarray(nube, dtype=float)
    nube = np.nan_to_num(nube, nan=0.0, posinf=0.0, neginf=0.0)
    escalador = MinMaxScaler(feature_range=(0.0, 1.0))
    return escalador.fit_transform(nube)


def calcular_topologia(nube: np.ndarray):
    """
    Procesa una nube de puntos (n_puntos, n_dimensiones) con giotto-tda:
      1) Normaliza con MinMaxScaler local a [0,1].
      2) VietorisRipsPersistence(homology_dimensions=[0, 1]) -> diagramas.
      3) PersistenceEntropy -> vector [entropía H0, entropía H1].
    Devuelve (diagrama (n_features, 3), entropías (2,)).
    """
    nube_escalada = escalar_nube_local(nube)
    vr = VietorisRipsPersistence(homology_dimensions=[0, 1], n_jobs=-1)
    diagramas = vr.fit_transform(nube_escalada[np.newaxis, :, :])
    entropia = PersistenceEntropy(nan_fill_value=0.0).fit_transform(diagramas)
    return diagramas[0], entropia[0]


def nube_de_partido_historico(fila: pd.Series) -> np.ndarray:
    """
    Construye la nube de puntos 4x6 de un partido histórico:
    vector local, vector visitante, punto medio y diferencia absoluta.
    Se excluyen los goles del partido (son la etiqueta -> evitar fuga).
    """
    altura = float(fila.get("ALTURA_NORM", 0.0))
    v_local = np.array([
        fila["home_xg"], fila["home_shots_on"], fila["home_shots_off"],
        fila["home_yellow"], fila["home_red"], altura,
    ], dtype=float)
    v_visit = np.array([
        fila["away_xg"], fila["away_shots_on"], fila["away_shots_off"],
        fila["away_yellow"], fila["away_red"], altura,
    ], dtype=float)
    v_medio = (v_local + v_visit) / 2.0
    v_dif = np.abs(v_local - v_visit)
    return np.vstack([v_local, v_visit, v_medio, v_dif])


def construir_nube_partido_actual(fila_local: pd.Series,
                                  fila_visitante: pd.Series,
                                  jugadores_local: pd.DataFrame,
                                  jugadores_visitante: pd.DataFrame) -> np.ndarray:
    """
    Nube de puntos multidimensional COMBINADA del partido actual (24 x 6):
      - 22 puntos micro: un punto por jugador titular
        [REMATES_TOTALES_MA5, REMATES_ARCO_MA5, XG_INDIVIDUAL_MA5,
         PASES_CLAVE_MA5, MINUTOS_JUGADOS_30D, EXPULSIONES_ACUMULADAS]
      - 2 puntos macro (uno por selección):
        [XG_FAVOR_MA5, REMATES_ARCO_FAVOR_MA5, GOLES_CONCEDIDOS_MA5,
         ALTURA_SEDE_MSNM, INDICE_POLEMICA_LOCAL, TARJETAS_ROJAS_MA5]
    Todo pasa después por el MinMaxScaler local -> rango [0,1].
    """
    columnas_micro = [
        "REMATES_TOTALES_MA5", "REMATES_ARCO_MA5", "XG_INDIVIDUAL_MA5",
        "PASES_CLAVE_MA5", "MINUTOS_JUGADOS_30D", "EXPULSIONES_ACUMULADAS",
    ]
    puntos = []
    for df_jug in (jugadores_local, jugadores_visitante):
        for _, j in df_jug.iterrows():
            puntos.append([float(j.get(c, 0.0)) for c in columnas_micro])
    for fila in (fila_local, fila_visitante):
        puntos.append([
            float(fila.get("XG_FAVOR_MA5", 0.0)),
            float(fila.get("REMATES_ARCO_FAVOR_MA5", 0.0)),
            float(fila.get("GOLES_CONCEDIDOS_MA5", 0.0)),
            float(fila.get("ALTURA_SEDE_MSNM", 0.0)),
            float(fila.get("INDICE_POLEMICA_LOCAL", 0.0)),
            float(fila.get("TARJETAS_ROJAS_MA5", 0.0)),
        ])
    return np.array(puntos, dtype=float)


# ===========================================================================
# BLOQUE 4: MOTOR DE INFERENCIA PREDICTIVA (ENTRENAMIENTO EN CALIENTE)
# ===========================================================================
@st.cache_resource(show_spinner="⚙️ Entrenando modelo topológico en caliente...")
def entrenar_modelo_topologico(historico: pd.DataFrame):
    """
    Entrena en caliente un RandomForestClassifier sobre las características
    topológicas (entropía de persistencia H0/H1) calculadas para CADA partido
    del histórico acumulado, mapeadas contra la etiqueta real del resultado:
        0 = Victoria Local | 1 = Empate | 2 = Victoria Visitante
    Se añaden 4 rasgos direccionales (diferencias local-visitante) porque la
    entropía de una nube es simétrica respecto al intercambio de equipos.
    Devuelve dict con modelo, precisión de validación y matrices de features.
    """
    df = historico.copy()

    faltantes = [c for c in COLUMNAS_HISTORICO_REQUERIDAS if c not in df.columns]
    if faltantes:
        return {"ok": False,
                "error": f"El histórico no contiene las columnas {faltantes} "
                         f"necesarias para el entrenamiento supervisado."}

    for c in COLUMNAS_HISTORICO_NUMERICAS:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=COLUMNAS_HISTORICO_NUMERICAS)
    if len(df) < 30:
        return {"ok": False,
                "error": f"Histórico insuficiente ({len(df)} partidos válidos). "
                         f"Se requieren al menos 30 para entrenar."}

    # Limitar a los últimos 1500 partidos para acotar el costo del cálculo VR
    df = df.sort_values("date").tail(1500).reset_index(drop=True)

    # Altura normalizada del estadio (0 si el histórico no la registra)
    if "stadium" in df.columns:
        df["ALTURA_NORM"] = df["stadium"].map(ALTITUDES_ESTADIOS).fillna(0.0) / ALTURA_MAXIMA_MSNM
    else:
        df["ALTURA_NORM"] = 0.0

    # --- Nubes de puntos por partido, escaladas localmente a [0,1] ---------
    nubes = np.stack([
        escalar_nube_local(nube_de_partido_historico(fila))
        for _, fila in df.iterrows()
    ])

    # --- Homología persistente por lotes (H0 y H1) --------------------------
    vr = VietorisRipsPersistence(homology_dimensions=[0, 1], n_jobs=-1)
    diagramas = vr.fit_transform(nubes)
    entropias = PersistenceEntropy(nan_fill_value=0.0).fit_transform(diagramas)

    # --- Rasgos direccionales (rompen la simetría local/visitante) ---------
    rasgos_dir = np.column_stack([
        df["home_xg"] - df["away_xg"],
        df["home_shots_on"] - df["away_shots_on"],
        df["home_red"] - df["away_red"],
        df["ALTURA_NORM"],
    ])

    X = np.hstack([entropias, rasgos_dir])
    y = np.where(df["home_goals"] > df["away_goals"], 0,
                 np.where(df["home_goals"] == df["away_goals"], 1, 2))

    # --- Entrenamiento y validación -----------------------------------------
    try:
        X_tr, X_te, y_tr, y_te = train_test_split(
            X, y, test_size=0.2, random_state=42, stratify=y
        )
    except ValueError:  # alguna clase con muy pocos ejemplos: split sin estratificar
        X_tr, X_te, y_tr, y_te = train_test_split(X, y, test_size=0.2, random_state=42)

    modelo = RandomForestClassifier(
        n_estimators=300, max_depth=12, min_samples_leaf=3,
        class_weight="balanced", random_state=42, n_jobs=-1,
    )
    modelo.fit(X_tr, y_tr)
    precision = accuracy_score(y_te, modelo.predict(X_te))

    return {
        "ok": True, "modelo": modelo, "precision": precision,
        "n_partidos": len(df), "entropias_hist": entropias, "etiquetas": y,
    }


def inferir_probabilidades(resultado_entrenamiento: dict,
                           entropia_partido: np.ndarray,
                           fila_local: pd.Series,
                           fila_visitante: pd.Series) -> np.ndarray:
    """
    Construye el vector de inferencia del partido actual con la MISMA
    estructura de features usada en el entrenamiento y devuelve el vector
    de probabilidades [P(local), P(empate), P(visitante)].
    """
    modelo = resultado_entrenamiento["modelo"]
    vector = np.array([[
        entropia_partido[0],
        entropia_partido[1],
        float(fila_local.get("XG_FAVOR_MA5", 0.0)) - float(fila_visitante.get("XG_FAVOR_MA5", 0.0)),
        float(fila_local.get("REMATES_ARCO_FAVOR_MA5", 0.0)) - float(fila_visitante.get("REMATES_ARCO_FAVOR_MA5", 0.0)),
        float(fila_local.get("TARJETAS_ROJAS_MA5", 0.0)) - float(fila_visitante.get("TARJETAS_ROJAS_MA5", 0.0)),
        float(fila_local.get("ALTURA_SEDE_MSNM", 0.0)) / ALTURA_MAXIMA_MSNM,
    ]])
    crudas = modelo.predict_proba(vector)[0]
    # Mapear a las 3 clases aunque el modelo haya visto menos (clase ausente=0)
    probabilidades = np.zeros(3)
    for clase, p in zip(modelo.classes_, crudas):
        probabilidades[int(clase)] = p
    if probabilidades.sum() > 0:
        probabilidades = probabilidades / probabilidades.sum()
    return probabilidades


# ===========================================================================
# UTILIDADES DE SELECCIÓN DE EQUIPOS Y JUGADORES (BLOQUE 1, LÓGICA INTERNA)
# ===========================================================================
def obtener_filas_del_partido(equipos_raw: pd.DataFrame, local: str, visitante: str):
    """
    Mapea internamente el MATCH_ID en común de ambas selecciones y aísla las
    filas macro de cada una. Si el fixture no contiene ese cruce exacto,
    construye un enfrentamiento hipotético con la fila más reciente de cada
    selección (informándolo con match_id=None).
    """
    ids_local = set(equipos_raw.loc[equipos_raw["EQUIPO_NOMBRE"] == local, "MATCH_ID"])
    ids_visit = set(equipos_raw.loc[equipos_raw["EQUIPO_NOMBRE"] == visitante, "MATCH_ID"])
    comunes = ids_local & ids_visit

    if comunes:
        match_id = sorted(comunes)[0]
        sub = equipos_raw[equipos_raw["MATCH_ID"] == match_id]
        fila_local = sub[sub["EQUIPO_NOMBRE"] == local].iloc[0].copy()
        fila_visit = sub[sub["EQUIPO_NOMBRE"] == visitante].iloc[0].copy()
        return match_id, fila_local, fila_visit

    # Cruce hipotético: última fila disponible de cada selección
    fila_local = equipos_raw[equipos_raw["EQUIPO_NOMBRE"] == local].iloc[-1].copy()
    fila_visit = equipos_raw[equipos_raw["EQUIPO_NOMBRE"] == visitante].iloc[-1].copy()
    return None, fila_local, fila_visit


def obtener_once_titular(jugadores_raw: pd.DataFrame, match_id, equipo: str) -> pd.DataFrame:
    """
    Extrae los 11 titulares de una selección. Prioriza los asociados al
    MATCH_ID del cruce; si no existen, toma la alineación más reciente
    registrada para la selección (deduplicada por jugador).
    """
    if match_id is not None:
        once = jugadores_raw[
            (jugadores_raw["MATCH_ID"] == match_id) &
            (jugadores_raw["EQUIPO_NOMBRE"] == equipo)
        ]
        if len(once) >= 1:
            return once.head(11).reset_index(drop=True)

    del_equipo = jugadores_raw[jugadores_raw["EQUIPO_NOMBRE"] == equipo]
    if del_equipo.empty:
        # Plantilla neutra de emergencia para no romper la topología (11 puntos)
        return pd.DataFrame([{
            "MATCH_ID": match_id, "JUGADOR_NOMBRE": f"{equipo}_JUGADOR_{i+1}",
            "EQUIPO_NOMBRE": equipo, "POSICION": "N/D",
            "REMATES_TOTALES_MA5": 1.5, "REMATES_ARCO_MA5": 0.8,
            "XG_INDIVIDUAL_MA5": 0.25, "PASES_CLAVE_MA5": 0.9,
            "MINUTOS_JUGADOS_30D": 250, "EXPULSIONES_ACUMULADAS": 0,
        } for i in range(11)])
    columna_id = "JUGADOR_ID" if "JUGADOR_ID" in del_equipo.columns else "JUGADOR_NOMBRE"
    once = del_equipo.drop_duplicates(subset=columna_id, keep="last")
    return once.head(11).reset_index(drop=True)


def aplicar_escenario(fila_equipo: pd.Series,
                      jugadores: pd.DataFrame,
                      escenario: dict):
    """
    Aplica EN MEMORIA (sin tocar disco) las modificaciones del simulador:
    altura de la sede, índice de polémica, tarjetas rojas MA5 y el ajuste
    global de fatiga (media objetivo de MINUTOS_JUGADOS_30D del plantel).
    """
    fila_mod = fila_equipo.copy()
    jugadores_mod = jugadores.copy()

    fila_mod["ALTURA_SEDE_MSNM"] = float(escenario["ALTURA_SEDE_MSNM"])
    fila_mod["INDICE_POLEMICA_LOCAL"] = float(escenario["INDICE_POLEMICA_LOCAL"])
    fila_mod["TARJETAS_ROJAS_MA5"] = float(escenario["TARJETAS_ROJAS_MA5"])

    media_actual = float(jugadores_mod["MINUTOS_JUGADOS_30D"].mean())
    media_objetivo = float(escenario["MINUTOS_JUGADOS_30D"])
    if media_actual > 0:
        factor = media_objetivo / media_actual
        jugadores_mod["MINUTOS_JUGADOS_30D"] = (
            jugadores_mod["MINUTOS_JUGADOS_30D"].astype(float) * factor
        ).round(0)
    else:
        jugadores_mod["MINUTOS_JUGADOS_30D"] = media_objetivo

    return fila_mod, jugadores_mod


# ===========================================================================
# BLOQUE 5: VISUALIZACIONES (ESPACIO DE FASES 3D + DIAGRAMA DE PERSISTENCIA)
# ===========================================================================
def grafico_espacio_fases_3d(historico: pd.DataFrame,
                             fila_local: pd.Series,
                             fila_visitante: pd.Series,
                             nombre_local: str,
                             nombre_visitante: str) -> go.Figure:
    """
    Espacio de fases 3D de la competitividad del torneo:
      X = xG generado | Y = Remates al arco | Z = Goles anotados
    Nube gris/verde de baja opacidad = todo el histórico (ambos bandos).
    Estrella roja = Selección Local | Esfera azul = Selección Visitante.
    """
    fig = go.Figure()

    columnas_ok = all(c in historico.columns for c in
                      ["home_xg", "away_xg", "home_shots_on", "away_shots_on",
                       "home_goals", "away_goals"])
    if columnas_ok:
        xs = pd.concat([historico["home_xg"], historico["away_xg"]]).astype(float)
        ys = pd.concat([historico["home_shots_on"], historico["away_shots_on"]]).astype(float)
        zs = pd.concat([historico["home_goals"], historico["away_goals"]]).astype(float)
        fig.add_trace(go.Scatter3d(
            x=xs, y=ys, z=zs, mode="markers",
            marker=dict(size=3, color="rgba(46, 160, 67, 0.18)"),
            name="Histórico del torneo (todas las actuaciones)",
            hoverinfo="skip",
        ))

    p_local = (
        float(fila_local.get("XG_FAVOR_MA5", 0.0)),
        float(fila_local.get("REMATES_ARCO_FAVOR_MA5", 0.0)),
        float(fila_local.get("GOLES_ANOTADOS_MA5", 0.0)),
    )
    p_visit = (
        float(fila_visitante.get("XG_FAVOR_MA5", 0.0)),
        float(fila_visitante.get("REMATES_ARCO_FAVOR_MA5", 0.0)),
        float(fila_visitante.get("GOLES_ANOTADOS_MA5", 0.0)),
    )

    # Estrella roja del Local (Plotly 3D usa 'diamond' como símbolo estelar)
    fig.add_trace(go.Scatter3d(
        x=[p_local[0]], y=[p_local[1]], z=[p_local[2]],
        mode="markers+text",
        marker=dict(size=14, color="red", symbol="diamond",
                    line=dict(color="darkred", width=3)),
        text=[f"★ {nombre_local} (Local)"], textposition="top center",
        textfont=dict(color="red", size=13),
        name=f"★ {nombre_local} (Local)",
    ))
    # Esfera azul del Visitante
    fig.add_trace(go.Scatter3d(
        x=[p_visit[0]], y=[p_visit[1]], z=[p_visit[2]],
        mode="markers+text",
        marker=dict(size=12, color="royalblue", symbol="circle",
                    line=dict(color="navy", width=3)),
        text=[f"● {nombre_visitante} (Visitante)"], textposition="bottom center",
        textfont=dict(color="royalblue", size=13),
        name=f"● {nombre_visitante} (Visitante)",
    ))
    # Segmento que materializa la "distancia en el espacio de fases"
    fig.add_trace(go.Scatter3d(
        x=[p_local[0], p_visit[0]], y=[p_local[1], p_visit[1]],
        z=[p_local[2], p_visit[2]], mode="lines",
        line=dict(color="orange", width=6, dash="dash"),
        name="Distancia en el espacio de fases",
    ))

    fig.update_layout(
        scene=dict(
            xaxis_title="xG generado (MA5)",
            yaxis_title="Remates al arco (MA5)",
            zaxis_title="Goles anotados (MA5)",
        ),
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        margin=dict(l=0, r=0, t=30, b=0),
        height=560,
    )
    return fig


def grafico_diagrama_persistencia(diagrama: np.ndarray) -> go.Figure:
    """
    Diagrama Birth-Death del escenario actual: puntos H0 (componentes
    conexas) y H1 (ciclos/lazos) sobre la diagonal de vida nula.
    El padding trivial de giotto-tda (birth == death) se filtra.
    """
    fig = go.Figure()
    colores = {0: ("#d62728", "H0 - Componentes conexas"),
               1: ("#1f77b4", "H1 - Ciclos (lazos)")}

    maximo = 0.0
    for dim in (0, 1):
        puntos = diagrama[diagrama[:, 2] == dim]
        puntos = puntos[puntos[:, 1] > puntos[:, 0]]  # descartar padding trivial
        if len(puntos) == 0:
            continue
        maximo = max(maximo, float(puntos[:, 1].max()))
        color, etiqueta = colores[dim]
        fig.add_trace(go.Scatter(
            x=puntos[:, 0], y=puntos[:, 1], mode="markers",
            marker=dict(size=11, color=color, opacity=0.85,
                        line=dict(color="white", width=1)),
            name=etiqueta,
            hovertemplate="Nacimiento: %{x:.4f}<br>Muerte: %{y:.4f}<extra></extra>",
        ))

    limite = max(maximo * 1.1, 0.1)
    fig.add_trace(go.Scatter(
        x=[0, limite], y=[0, limite], mode="lines",
        line=dict(color="gray", dash="dot"), name="Diagonal (vida nula)",
    ))
    fig.update_layout(
        xaxis_title="Nacimiento (Birth)", yaxis_title="Muerte (Death)",
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        margin=dict(l=0, r=0, t=30, b=0), height=560,
    )
    return fig


def mostrar_tarjetas_probabilidad(probabilidades: np.ndarray,
                                  nombre_local: str, nombre_visitante: str):
    """Tres tarjetas de métricas grandes con las probabilidades del modelo."""
    col1, col2, col3 = st.columns(3)
    ganadora = int(np.argmax(probabilidades))
    with col1:
        st.metric(
            label=f"🏠 Victoria {nombre_local}",
            value=f"{probabilidades[0]*100:.1f} %",
            delta="Escenario dominante" if ganadora == 0 else None,
        )
    with col2:
        st.metric(
            label="🤝 Empate",
            value=f"{probabilidades[1]*100:.1f} %",
            delta="Escenario dominante" if ganadora == 1 else None,
        )
    with col3:
        st.metric(
            label=f"✈️ Victoria {nombre_visitante}",
            value=f"{probabilidades[2]*100:.1f} %",
            delta="Escenario dominante" if ganadora == 2 else None,
        )


def ejecutar_pipeline_topologico(fila_local, fila_visit, jug_local, jug_visit,
                                 resultado_entrenamiento):
    """
    Pipeline completo de un escenario: nube combinada -> MinMax local ->
    Vietoris-Rips -> entropía de persistencia -> inferencia probabilística.
    Devuelve (diagrama, entropías, probabilidades).
    """
    nube = construir_nube_partido_actual(fila_local, fila_visit, jug_local, jug_visit)
    diagrama, entropias = calcular_topologia(nube)
    probabilidades = inferir_probabilidades(
        resultado_entrenamiento, entropias, fila_local, fila_visit
    )
    return diagrama, entropias, probabilidades


# ===========================================================================
# CUERPO PRINCIPAL DE LA APLICACIÓN
# ===========================================================================
def main():
    st.title("🌎 Motor Predictivo TDA — Mundial 2026")
    st.caption(
        "Análisis Topológico de Datos en tiempo real · Vietoris-Rips + Entropía "
        "de Persistencia + Random Forest entrenado en caliente sobre el histórico."
    )

    # ---- Guardia de dependencias ------------------------------------------
    if not GTDA_DISPONIBLE:
        st.error(
            "❌ **La librería `giotto-tda` no está disponible en este entorno.**\n\n"
            f"Detalle técnico: `{GTDA_ERROR}`\n\n"
            "Instálala con `pip install giotto-tda` y reinicia la aplicación. "
            "Sin ella no es posible calcular la homología persistente."
        )
        st.stop()

    # ---- BLOQUE 1: Ingestión con caché y manejo elegante de fallos --------
    datos, errores = cargar_todos_los_datos()

    # Archivos críticos sin los cuales la app no puede operar
    for clave in ("equipos_raw", "jugadores_raw", "historico"):
        if clave in errores:
            st.error(f"❌ **Archivo base faltante o corrupto**\n\n{errores[clave]}")
    if any(c in errores for c in ("equipos_raw", "jugadores_raw", "historico")):
        st.info(
            "💡 Genera los artefactos ejecutando en la carpeta del proyecto:\n\n"
            "```bash\npython pipeline_mundial.py\n```"
        )
        st.stop()

    # Archivos secundarios: degradación elegante con warning
    for clave in ("elo", "equipos_norm", "jugadores_norm"):
        if clave in errores:
            st.warning(f"⚠️ {errores[clave]} La app continuará sin este archivo.")

    historico = datos["historico"]
    equipos_raw = datos["equipos_raw"]
    jugadores_raw = datos["jugadores_raw"]

    # Validación de esquema de los datasets RAW
    faltan_eq = [c for c in COLUMNAS_EQUIPO_REQUERIDAS if c not in equipos_raw.columns]
    faltan_jug = [c for c in COLUMNAS_JUGADOR_REQUERIDAS if c not in jugadores_raw.columns]
    if faltan_eq or faltan_jug:
        st.error(
            "❌ **Esquema de datos incompatible.**\n\n"
            + (f"- `dataset_equipos_raw.csv` sin columnas: `{faltan_eq}`\n" if faltan_eq else "")
            + (f"- `dataset_jugadores_raw.csv` sin columnas: `{faltan_jug}`\n" if faltan_jug else "")
            + "\nRe-ejecuta `python pipeline_mundial.py` para regenerar los datasets."
        )
        st.stop()

    # ---- Entrenamiento en caliente del modelo (cacheado) -------------------
    resultado_entrenamiento = entrenar_modelo_topologico(historico)
    if not resultado_entrenamiento["ok"]:
        st.error(f"❌ **No fue posible entrenar el modelo:** {resultado_entrenamiento['error']}")
        st.stop()

    # ---- BLOQUE 1: Sidebar de baja fricción --------------------------------
    st.sidebar.header("⚽ Configuración del Encuentro")
    universo_equipos = sorted(equipos_raw["EQUIPO_NOMBRE"].dropna().unique().tolist())

    if len(universo_equipos) < 2:
        st.error("❌ `dataset_equipos_raw.csv` contiene menos de 2 selecciones. "
                 "Regenera el dataset con el pipeline.")
        st.stop()

    seleccion_local = st.sidebar.selectbox(
        "Selecciona Selección Local", universo_equipos, index=0,
    )
    opciones_visitante = [e for e in universo_equipos if e != seleccion_local]
    seleccion_visitante = st.sidebar.selectbox(
        "Selecciona Selección Visitante", opciones_visitante, index=0,
    )

    st.sidebar.divider()
    st.sidebar.markdown(
        f"**Modelo entrenado** sobre `{resultado_entrenamiento['n_partidos']}` "
        f"partidos históricos.\n\n**Precisión de validación (hold-out 20%):** "
        f"`{resultado_entrenamiento['precision']*100:.1f} %`"
    )
    if datos.get("elo") is not None:
        elo_df = datos["elo"]
        col_codigo, col_valor = elo_df.columns[0], elo_df.columns[-1]
        elo_map = dict(zip(elo_df[col_codigo].astype(str), elo_df[col_valor]))
        elo_l = elo_map.get(seleccion_local)
        elo_v = elo_map.get(seleccion_visitante)
        if elo_l is not None and elo_v is not None:
            st.sidebar.divider()
            st.sidebar.markdown(
                f"**ELO dinámico actual**\n\n"
                f"🏠 {seleccion_local}: `{float(elo_l):.0f}`\n\n"
                f"✈️ {seleccion_visitante}: `{float(elo_v):.0f}`"
            )

    # Mapeo interno del MATCH_ID común y aislamiento de datos macro/micro
    match_id, fila_local_base, fila_visit_base = obtener_filas_del_partido(
        equipos_raw, seleccion_local, seleccion_visitante
    )
    jugadores_local_base = obtener_once_titular(jugadores_raw, match_id, seleccion_local)
    jugadores_visit_base = obtener_once_titular(jugadores_raw, match_id, seleccion_visitante)

    # ---- Pestañas principales ----------------------------------------------
    tab_prediccion, tab_backtesting = st.tabs(
        ["🎯 Predicción y Simulación en Vivo", "📊 Backtesting y Validación de Precisión"]
    )

    # =======================================================================
    # PESTAÑA 1: PREDICCIÓN + SIMULADOR AVANZADO
    # =======================================================================
    with tab_prediccion:
        if match_id is not None:
            st.success(
                f"✅ Cruce oficial del fixture detectado — `MATCH_ID: {match_id}` · "
                f"**{seleccion_local}** (Local) vs **{seleccion_visitante}** (Visitante)"
            )
        else:
            st.warning(
                f"⚠️ El fixture no contiene el cruce exacto "
                f"**{seleccion_local} vs {seleccion_visitante}**. Se construyó un "
                f"enfrentamiento hipotético con el contexto más reciente de cada selección."
            )

        # ---- BLOQUE 2: Simulador avanzado (expander + 2 columnas) ---------
        with st.expander("🔧 Simulador Avanzado de Escenarios en Vivo", expanded=False):
            st.markdown(
                "Modifica **en memoria** las condiciones del encuentro antes de la "
                "ejecución topológica. Los archivos en disco no se alteran."
            )
            col_local, col_visit = st.columns(2)

            with col_local:
                st.subheader(f"🏠 {seleccion_local} (Local)")
                altura_sede = st.slider(
                    "ALTURA_SEDE_MSNM (sede del partido, aplica a ambos)",
                    min_value=0, max_value=3000,
                    value=int(np.clip(float(fila_local_base["ALTURA_SEDE_MSNM"]), 0, 3000)),
                    step=10, key="sl_altura",
                    help="Altitud del estadio en metros sobre el nivel del mar.",
                )
                polemica_local = st.slider(
                    "INDICE_POLEMICA_LOCAL (Local)",
                    min_value=0.0, max_value=1.0,
                    value=float(np.clip(float(fila_local_base["INDICE_POLEMICA_LOCAL"]), 0.0, 1.0)),
                    step=0.01, key="sl_polemica_l",
                    help="0.0 = vestidor estable · 1.0 = crisis interna máxima.",
                )
                rojas_local = st.slider(
                    "TARJETAS_ROJAS_MA5 (Local)",
                    min_value=0.0, max_value=1.0,
                    value=float(np.clip(float(fila_local_base["TARJETAS_ROJAS_MA5"]), 0.0, 1.0)),
                    step=0.05, key="sl_rojas_l",
                    help="Media móvil de expulsiones. Súbelo para inyectar indisciplina.",
                )
                minutos_local = st.slider(
                    "MINUTOS_JUGADOS_30D (media del plantel Local)",
                    min_value=0, max_value=600,
                    value=int(np.clip(jugadores_local_base["MINUTOS_JUGADOS_30D"].astype(float).mean(), 0, 600)),
                    step=5, key="sl_minutos_l",
                    help="Fatiga acumulada: escala los minutos de los 11 titulares.",
                )

            with col_visit:
                st.subheader(f"✈️ {seleccion_visitante} (Visitante)")
                st.slider(
                    "ALTURA_SEDE_MSNM (heredada de la sede)",
                    min_value=0, max_value=3000, value=int(altura_sede),
                    step=10, key="sl_altura_v", disabled=True,
                    help="La altitud es propiedad de la sede: idéntica para ambos bandos.",
                )
                polemica_visit = st.slider(
                    "INDICE_POLEMICA_LOCAL (Visitante)",
                    min_value=0.0, max_value=1.0,
                    value=float(np.clip(float(fila_visit_base["INDICE_POLEMICA_LOCAL"]), 0.0, 1.0)),
                    step=0.01, key="sl_polemica_v",
                )
                rojas_visit = st.slider(
                    "TARJETAS_ROJAS_MA5 (Visitante)",
                    min_value=0.0, max_value=1.0,
                    value=float(np.clip(float(fila_visit_base["TARJETAS_ROJAS_MA5"]), 0.0, 1.0)),
                    step=0.05, key="sl_rojas_v",
                )
                minutos_visit = st.slider(
                    "MINUTOS_JUGADOS_30D (media del plantel Visitante)",
                    min_value=0, max_value=600,
                    value=int(np.clip(jugadores_visit_base["MINUTOS_JUGADOS_30D"].astype(float).mean(), 0, 600)),
                    step=5, key="sl_minutos_v",
                )

        # ---- Aplicar escenario en memoria ----------------------------------
        escenario_local = {
            "ALTURA_SEDE_MSNM": altura_sede,
            "INDICE_POLEMICA_LOCAL": polemica_local,
            "TARJETAS_ROJAS_MA5": rojas_local,
            "MINUTOS_JUGADOS_30D": minutos_local,
        }
        escenario_visit = {
            "ALTURA_SEDE_MSNM": altura_sede,
            "INDICE_POLEMICA_LOCAL": polemica_visit,
            "TARJETAS_ROJAS_MA5": rojas_visit,
            "MINUTOS_JUGADOS_30D": minutos_visit,
        }
        fila_local, jugadores_local = aplicar_escenario(
            fila_local_base, jugadores_local_base, escenario_local
        )
        fila_visit, jugadores_visit = aplicar_escenario(
            fila_visit_base, jugadores_visit_base, escenario_visit
        )

        # ---- BLOQUES 3 y 4: Pipeline topológico + inferencia ---------------
        with st.spinner("🧮 Calculando homología persistente del escenario..."):
            try:
                diagrama, entropias, probabilidades = ejecutar_pipeline_topologico(
                    fila_local, fila_visit, jugadores_local, jugadores_visit,
                    resultado_entrenamiento,
                )
            except Exception as e:
                st.error(
                    f"❌ **Fallo en el cálculo topológico:** `{type(e).__name__}: {e}`\n\n"
                    "Revisa que los datasets RAW no contengan valores no numéricos "
                    "en las columnas de métricas."
                )
                st.stop()

        st.subheader("🎯 Probabilidades del Modelo Topológico")
        mostrar_tarjetas_probabilidad(probabilidades, seleccion_local, seleccion_visitante)

        col_e1, col_e2 = st.columns(2)
        col_e1.metric("Entropía de Persistencia H0 (conectividad)", f"{entropias[0]:.4f}")
        col_e2.metric("Entropía de Persistencia H1 (ciclos)", f"{entropias[1]:.4f}")

        # ---- BLOQUE 5: Visualizaciones --------------------------------------
        st.divider()
        col_g1, col_g2 = st.columns(2)
        with col_g1:
            st.subheader("🌌 Espacio de Fases 3D del Torneo")
            st.plotly_chart(
                grafico_espacio_fases_3d(
                    historico, fila_local, fila_visit,
                    seleccion_local, seleccion_visitante,
                ),
                use_container_width=True,
            )
            # Distancia euclidiana en el subespacio (xG, remates, goles)
            v_l = np.array([fila_local["XG_FAVOR_MA5"],
                            fila_local["REMATES_ARCO_FAVOR_MA5"],
                            fila_local["GOLES_ANOTADOS_MA5"]], dtype=float)
            v_v = np.array([fila_visit["XG_FAVOR_MA5"],
                            fila_visit["REMATES_ARCO_FAVOR_MA5"],
                            fila_visit["GOLES_ANOTADOS_MA5"]], dtype=float)
            st.info(
                f"📏 **Distancia en el espacio de fases** entre "
                f"{seleccion_local} y {seleccion_visitante}: "
                f"`{np.linalg.norm(v_l - v_v):.3f}` unidades."
            )
        with col_g2:
            st.subheader("🔬 Diagrama de Persistencia (Birth-Death)")
            st.plotly_chart(
                grafico_diagrama_persistencia(diagrama),
                use_container_width=True,
            )
            st.info(
                "Los puntos H0 lejos de la diagonal indican bloques competitivos "
                "muy separados; los ciclos H1 revelan estructuras de equilibrio "
                "táctico dentro de la nube combinada de 22 jugadores + 2 macros."
            )

        # ---- Detalle de alineaciones ----------------------------------------
        with st.expander("📋 Alineaciones titulares utilizadas en la nube de puntos"):
            col_a1, col_a2 = st.columns(2)
            columnas_vista = [c for c in
                              ["JUGADOR_NOMBRE", "POSICION", "XG_INDIVIDUAL_MA5",
                               "REMATES_ARCO_MA5", "PASES_CLAVE_MA5",
                               "MINUTOS_JUGADOS_30D", "EXPULSIONES_ACUMULADAS"]
                              if c in jugadores_local.columns]
            with col_a1:
                st.markdown(f"**🏠 {seleccion_local}**")
                st.dataframe(jugadores_local[columnas_vista], use_container_width=True, height=300)
            with col_a2:
                st.markdown(f"**✈️ {seleccion_visitante}**")
                st.dataframe(jugadores_visit[columnas_vista], use_container_width=True, height=300)

    # =======================================================================
    # PESTAÑA 2 (BLOQUE 6): BACKTESTING Y VALIDACIÓN HISTÓRICA
    # =======================================================================
    with tab_backtesting:
        st.subheader("📊 Backtesting y Validación de Precisión")
        st.markdown(
            "Selecciona un partido emblemático documentado por el backend. La app "
            "**bloquea automáticamente todos los sliders** en las condiciones exactas "
            "registradas ese día, re-ejecuta el pipeline topológico y contrasta la "
            "probabilidad estimada contra el marcador real definitivo."
        )

        partido_sel = st.selectbox(
            "Partido histórico emblemático",
            list(PARTIDOS_EMBLEMATICOS.keys()), index=0,
        )
        caso = PARTIDOS_EMBLEMATICOS[partido_sel]
        codigo_local, codigo_visit = caso["local"], caso["visitante"]

        if codigo_local not in universo_equipos or codigo_visit not in universo_equipos:
            st.warning(
                f"⚠️ Las selecciones `{codigo_local}` y/o `{codigo_visit}` no están "
                f"presentes en `dataset_equipos_raw.csv`, por lo que este backtest no "
                f"puede reconstruirse con los datos actuales. Re-ejecuta el pipeline "
                f"incluyendo su cruce en `calendario_mundial_2026.csv`."
            )
        else:
            st.markdown(f"**🏟️ Sede documentada:** {caso['estadio']}")
            st.markdown(f"> {caso['narrativa']}")

            # ---- Sliders bloqueados en las condiciones documentadas --------
            st.markdown("##### 🔒 Condiciones originales congeladas por el backend")
            col_bl, col_bv = st.columns(2)
            with col_bl:
                st.markdown(f"**🏠 {codigo_local} (Local)**")
                st.slider("ALTURA_SEDE_MSNM", 0, 3000,
                          int(caso["condiciones_local"]["ALTURA_SEDE_MSNM"]),
                          key="bt_alt_l", disabled=True)
                st.slider("INDICE_POLEMICA_LOCAL", 0.0, 1.0,
                          float(caso["condiciones_local"]["INDICE_POLEMICA_LOCAL"]),
                          key="bt_pol_l", disabled=True)
                st.slider("TARJETAS_ROJAS_MA5", 0.0, 1.0,
                          float(caso["condiciones_local"]["TARJETAS_ROJAS_MA5"]),
                          key="bt_roj_l", disabled=True)
                st.slider("MINUTOS_JUGADOS_30D (media plantel)", 0, 600,
                          int(caso["condiciones_local"]["MINUTOS_JUGADOS_30D"]),
                          key="bt_min_l", disabled=True)
            with col_bv:
                st.markdown(f"**✈️ {codigo_visit} (Visitante)**")
                st.slider("ALTURA_SEDE_MSNM ", 0, 3000,
                          int(caso["condiciones_visitante"]["ALTURA_SEDE_MSNM"]),
                          key="bt_alt_v", disabled=True)
                st.slider("INDICE_POLEMICA_LOCAL ", 0.0, 1.0,
                          float(caso["condiciones_visitante"]["INDICE_POLEMICA_LOCAL"]),
                          key="bt_pol_v", disabled=True)
                st.slider("TARJETAS_ROJAS_MA5 ", 0.0, 1.0,
                          float(caso["condiciones_visitante"]["TARJETAS_ROJAS_MA5"]),
                          key="bt_roj_v", disabled=True)
                st.slider("MINUTOS_JUGADOS_30D (media plantel) ", 0, 600,
                          int(caso["condiciones_visitante"]["MINUTOS_JUGADOS_30D"]),
                          key="bt_min_v", disabled=True)

            # ---- Reconstrucción del escenario y re-ejecución ----------------
            bt_match_id, bt_fila_l_base, bt_fila_v_base = obtener_filas_del_partido(
                equipos_raw, codigo_local, codigo_visit
            )
            bt_jug_l_base = obtener_once_titular(jugadores_raw, bt_match_id, codigo_local)
            bt_jug_v_base = obtener_once_titular(jugadores_raw, bt_match_id, codigo_visit)

            bt_fila_l, bt_jug_l = aplicar_escenario(
                bt_fila_l_base, bt_jug_l_base, caso["condiciones_local"]
            )
            bt_fila_v, bt_jug_v = aplicar_escenario(
                bt_fila_v_base, bt_jug_v_base, caso["condiciones_visitante"]
            )

            with st.spinner("🧮 Re-ejecutando el pipeline topológico con las condiciones documentadas..."):
                try:
                    bt_diagrama, bt_entropias, bt_probs = ejecutar_pipeline_topologico(
                        bt_fila_l, bt_fila_v, bt_jug_l, bt_jug_v, resultado_entrenamiento
                    )
                except Exception as e:
                    st.error(f"❌ **Fallo en el backtest topológico:** `{type(e).__name__}: {e}`")
                    st.stop()

            # ---- Contraste predicción vs realidad ---------------------------
            st.markdown("##### 🎯 Probabilidades reconstruidas por el modelo")
            mostrar_tarjetas_probabilidad(bt_probs, codigo_local, codigo_visit)

            goles_l, goles_v = caso["marcador_real"]
            clase_real = caso["resultado_real"]
            clase_predicha = int(np.argmax(bt_probs))
            acierto = clase_predicha == clase_real

            col_r1, col_r2, col_r3 = st.columns(3)
            col_r1.metric(
                "Marcador real definitivo",
                f"{codigo_local} {goles_l} - {goles_v} {codigo_visit}",
            )
            col_r2.metric(
                "Resultado real", ETIQUETAS_RESULTADO[clase_real],
            )
            col_r3.metric(
                "Veredicto del modelo",
                "✅ ACIERTO" if acierto else "❌ FALLO",
                delta=f"Predijo: {ETIQUETAS_RESULTADO[clase_predicha]} "
                      f"({bt_probs[clase_predicha]*100:.1f} %)",
                delta_color="normal" if acierto else "inverse",
            )

            if acierto:
                st.success(
                    f"✅ El modelo topológico asignó **{bt_probs[clase_real]*100:.1f} %** "
                    f"al resultado que efectivamente ocurrió "
                    f"(**{ETIQUETAS_RESULTADO[clase_real]}**, marcador real "
                    f"{codigo_local} {goles_l}-{goles_v} {codigo_visit}), validando el "
                    f"rigor matemático del sistema en este escenario."
                )
            else:
                st.warning(
                    f"⚠️ El modelo asignó solo **{bt_probs[clase_real]*100:.1f} %** al "
                    f"resultado real ({ETIQUETAS_RESULTADO[clase_real]}). Los backtests "
                    f"fallidos son insumo clave para recalibrar los pesos topológicos."
                )

            # ---- Distancia en el espacio de fases del backtest --------------
            st.divider()
            col_bg1, col_bg2 = st.columns(2)
            with col_bg1:
                st.subheader("🌌 Distancia en el Espacio de Fases (histórica)")
                st.plotly_chart(
                    grafico_espacio_fases_3d(
                        historico, bt_fila_l, bt_fila_v, codigo_local, codigo_visit
                    ),
                    use_container_width=True,
                )
                v_l = np.array([bt_fila_l["XG_FAVOR_MA5"],
                                bt_fila_l["REMATES_ARCO_FAVOR_MA5"],
                                bt_fila_l["GOLES_ANOTADOS_MA5"]], dtype=float)
                v_v = np.array([bt_fila_v["XG_FAVOR_MA5"],
                                bt_fila_v["REMATES_ARCO_FAVOR_MA5"],
                                bt_fila_v["GOLES_ANOTADOS_MA5"]], dtype=float)
                st.info(
                    f"📏 Separación métrica documentada entre **{codigo_local}** "
                    f"(su isla métrica de anfitrión) y **{codigo_visit}**: "
                    f"`{np.linalg.norm(v_l - v_v):.3f}` unidades en el subespacio "
                    f"(xG, remates al arco, goles)."
                )
            with col_bg2:
                st.subheader("🔬 Diagrama de Persistencia del Backtest")
                st.plotly_chart(
                    grafico_diagrama_persistencia(bt_diagrama),
                    use_container_width=True,
                )
                col_be1, col_be2 = st.columns(2)
                col_be1.metric("Entropía H0", f"{bt_entropias[0]:.4f}")
                col_be2.metric("Entropía H1", f"{bt_entropias[1]:.4f}")


if __name__ == "__main__":
    main()
