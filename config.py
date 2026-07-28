#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Configuración central del pipeline."""

# ---------------------------------------------------------------------------
# v66: el universo de selecciones pasa de 49 a 200.
#
# El histórico real (historico_partidos.csv) cubre 326 selecciones y el modelo
# YA se entrenaba sobre todas (train_tda_model no filtra por TEAMS): el límite
# de 49 era SÓLO de configuración — team_stats.json, el selector de la UI y el
# mapeo de fixtures de ESPN no conocían más códigos. Ampliar TEAMS abre esas
# tres puertas sin tocar el conjunto de entrenamiento.
#
# `config_selecciones.py` lo genera `generar_universo_selecciones.py` con el
# criterio ">= 100 partidos en el histórico" (= exactamente 200 selecciones).
# Si ese módulo faltara, se cae a la lista de 49 de siempre (degradación limpia).
# ---------------------------------------------------------------------------

# Las 49 selecciones clasificadas al Mundial 2026 (incluye Cabo Verde).
# Se conserva como subconjunto de referencia: es el universo con el que se
# validó el modelo hasta v65 y con el que se compara la precisión en v66.
TEAMS_MUNDIAL_2026 = [
    'MEX', 'USA', 'CAN', 'ARG', 'BRA', 'URU', 'COL', 'ECU', 'PER', 'CHI',
    'FRA', 'ENG', 'ESP', 'GER', 'ITA', 'POR', 'NED', 'BEL', 'CRO', 'SRB',
    'MAR', 'SEN', 'CMR', 'GHA', 'NGA', 'TUN', 'ALG', 'EGY',
    'JPN', 'KOR', 'IRN', 'AUS', 'KSA', 'QAT', 'CRC', 'PAN', 'HON', 'JAM',
    'PAR', 'NOR', 'SUI', 'DEN', 'AUT', 'SCO', 'CIV', 'UZB', 'JOR', 'NZL',
    'CPV',
]
TEAMS = list(TEAMS_MUNDIAL_2026)

# Mapeo código FIFA <-> nombre en el dataset de Kaggle (inglés)
TEAM_NAMES_EN = {
    'MEX': 'Mexico', 'USA': 'United States', 'CAN': 'Canada',
    'ARG': 'Argentina', 'BRA': 'Brazil', 'URU': 'Uruguay',
    'COL': 'Colombia', 'ECU': 'Ecuador', 'PER': 'Peru', 'CHI': 'Chile',
    'FRA': 'France', 'ENG': 'England', 'ESP': 'Spain', 'GER': 'Germany',
    'ITA': 'Italy', 'POR': 'Portugal', 'NED': 'Netherlands',
    'BEL': 'Belgium', 'CRO': 'Croatia', 'SRB': 'Serbia',
    'MAR': 'Morocco', 'SEN': 'Senegal', 'CMR': 'Cameroon', 'GHA': 'Ghana',
    'NGA': 'Nigeria', 'TUN': 'Tunisia', 'ALG': 'Algeria', 'EGY': 'Egypt',
    'JPN': 'Japan', 'KOR': 'South Korea', 'IRN': 'Iran', 'AUS': 'Australia',
    'KSA': 'Saudi Arabia', 'QAT': 'Qatar', 'CRC': 'Costa Rica',
    'PAN': 'Panama', 'HON': 'Honduras', 'JAM': 'Jamaica',
    'PAR': 'Paraguay', 'NOR': 'Norway', 'SUI': 'Switzerland',
    'DEN': 'Denmark', 'AUT': 'Austria', 'SCO': 'Scotland',
    'CIV': 'Ivory Coast', 'UZB': 'Uzbekistan', 'JOR': 'Jordan',
    'NZL': 'New Zealand', 'CPV': 'Cape Verde',
}
NAME_EN_TO_FIFA = {v: k for k, v in TEAM_NAMES_EN.items()}

TEAM_STYLE = {
    'MEX': 'bloque_alto', 'USA': 'bloque_alto', 'CAN': 'bloque_alto',
    'ARG': 'bloque_alto', 'BRA': 'bloque_alto', 'URU': 'bloque_bajo',
    'COL': 'bloque_bajo', 'ECU': 'bloque_bajo', 'PER': 'bloque_bajo',
    'CHI': 'bloque_bajo', 'FRA': 'bloque_alto', 'ENG': 'bloque_alto',
    'ESP': 'bloque_alto', 'GER': 'bloque_alto', 'ITA': 'bloque_bajo',
    'POR': 'bloque_alto', 'NED': 'bloque_alto', 'BEL': 'bloque_alto',
    'CRO': 'bloque_bajo', 'SRB': 'bloque_bajo', 'MAR': 'bloque_bajo',
    'SEN': 'bloque_bajo', 'CMR': 'bloque_bajo', 'GHA': 'bloque_bajo',
    'NGA': 'bloque_bajo', 'TUN': 'bloque_bajo', 'ALG': 'bloque_bajo',
    'EGY': 'bloque_bajo', 'JPN': 'bloque_alto', 'KOR': 'bloque_alto',
    'IRN': 'bloque_bajo', 'AUS': 'bloque_bajo', 'KSA': 'bloque_bajo',
    'QAT': 'bloque_bajo', 'CRC': 'bloque_bajo', 'PAN': 'bloque_bajo',
    'HON': 'bloque_bajo', 'JAM': 'bloque_bajo',
    'PAR': 'bloque_bajo', 'NOR': 'bloque_alto', 'SUI': 'bloque_alto',
    'DEN': 'bloque_alto', 'AUT': 'bloque_alto', 'SCO': 'bloque_bajo',
    'CIV': 'bloque_bajo', 'UZB': 'bloque_bajo', 'JOR': 'bloque_bajo',
    'NZL': 'bloque_bajo', 'CPV': 'bloque_bajo',
}

# Alias por selección con los que OTRAS fuentes publican al equipo (ESPN usa
# "Czechia", "Türkiye", "Bosnia-Herzegovina"...). Con 49 selecciones el fuzzy
# de name_mapper bastaba; con 200 hace falta el mapeo exacto para no confundir
# Congo/RD Congo, Guinea/Guinea Ecuatorial o Sudán/Sudán del Sur.
TEAM_ALIAS = {k: [v] for k, v in TEAM_NAMES_EN.items()}

# Nombre en español (lo consume prediction_api.NOMBRES_PAIS).
TEAM_NAMES_ES = {}

# Nº de partidos en el histórico por selección (insumo de la UI y de la
# feature de "nivel de datos"). Vacío si no se ha generado el universo.
TEAM_PARTIDOS = {}

# ELO final de cada selección según el histórico (lo consume el generador
# sintético para estimar el nivel de las selecciones sin tier manual).
TEAM_ELO = {}

# --- v66: ampliación a 200 selecciones (ver cabecera) -----------------------
# Interruptor de emergencia / A-B: con MUNDIAL_UNIVERSO=v65 en el entorno, el
# proyecto entero vuelve al universo de 49 selecciones sin tocar código. Es lo
# que hace comparable el A/B de v66 (mismo histórico, sólo cambia el universo).
import os as _os
try:
    if _os.getenv('MUNDIAL_UNIVERSO', '').lower() == 'v65':
        raise ImportError('universo v65 forzado por MUNDIAL_UNIVERSO')
    import config_selecciones as _sel
    TEAMS = list(_sel.TEAMS)
    TEAM_NAMES_EN = dict(_sel.TEAM_NAMES_EN)
    TEAM_STYLE = dict(_sel.TEAM_STYLE)
    TEAM_NAMES_ES = dict(_sel.TEAM_NAMES_ES)
    TEAM_PARTIDOS = dict(_sel.TEAM_PARTIDOS)
    TEAM_ELO = dict(getattr(_sel, 'TEAM_ELO', {}))
    TEAM_ALIAS = dict(_sel.TEAM_ALIAS)
    UNIVERSO_SELECCIONES = 'v66:>=100 partidos'
except Exception:                      # degradación limpia a las 49 de siempre
    UNIVERSO_SELECCIONES = 'v65:mundial-2026'

NAME_EN_TO_FIFA = {v: k for k, v in TEAM_NAMES_EN.items()}
# Todos los alias apuntando al código (para el mapeo de fixtures y scrapers).
ALIAS_TO_FIFA = {a: c for c, lista in TEAM_ALIAS.items() for a in lista}
ALIAS_TO_FIFA.update(NAME_EN_TO_FIFA)   # el nombre canónico siempre gana

STADIUMS = {
    'Azteca': 2240, 'MetLife': 2, 'AT&T': 168, 'SoFi': 71,
    'HardRock': 2, 'Mercedes-Benz': 315, 'Levi\'s': 2, 'NRG': 43,
    'Lincoln_Financial': 12, 'Arrowhead': 271, 'Gillette': 75,
    'Lumen_Field': 5, 'BC_Place': 2, 'BMO_Field': 86,
    'Estadio_BBVA': 537, 'Akron': 1564,
    # Ciudades de altura del histórico (la columna city de Kaggle se mapea aquí)
    'Mexico City': 2240, 'Guadalajara': 1566, 'Monterrey': 540,
    'Toluca': 2660, 'Puebla': 2135, 'Quito': 2850, 'La Paz': 3640,
    'Bogota': 2640, 'Bogotá': 2640, 'Cusco': 3400, 'Arequipa': 2335,
}

# Dataset de Kaggle con resultados reales 1872-presente (actualización continua)
KAGGLE_DATASET = 'martj42/international-football-results-from-1872-to-2017'

# ---------------------------------------------------------------------------
# Ligas de clubes (v12). Fuente: football-data.co.uk (CSV gratuitos con
# resultados reales; los formatos 'main' incluyen remates/córners/tarjetas
# REALES y cuotas de cierre; el formato 'new' solo goles + cuotas).
# Champions no tiene fuente CSV gratuita -> beta, requiere RAPIDAPI_KEY.
# ---------------------------------------------------------------------------
FD_BASE = 'https://www.football-data.co.uk'
LEAGUES = {
    # v13: histórico ampliado (5 temporadas / 8 años MX) — validado en
    # VALIDACION_v13.md contra los modelos v12 de 3 temporadas.
    'liga_mx': {
        'nombre': 'Liga MX', 'pais': 'México', 'formato': 'new',
        'urls': [f'{FD_BASE}/new/MEX.csv'], 'anios_ventana': 8,
        'disponible': True,
        # v18/M2 (walk-forward +1.7pp / -0.028): cuotas de CIERRE de MEX.csv
        # (AvgC*, 100% de cobertura — el parser v12 leía las de apertura,
        # inexistentes). En vivo: Betexplorer días de partido o media del train.
        # v19 (walk-forward +1.0pp adicional, 51.7%/1.011): + features MX
        # (altitud/distancia/liguilla/apertura) + beta calibration.
        # v24 (walk-forward 50.46→50.84, +0.38pp): + índice compuesto IMT
        'features_extra': ['cuotas', 'mx', 'imt_c'],
        'calibracion': 'beta',
    },
    'mls': {
        # v24: MLS con USA.csv de football-data (formato 'new', igual que
        # MEX.csv: goles + cuotas de CIERRE AvgC*/PSC*/B365C* con cobertura
        # total). Fuente verificada 2026-07-16 — 6,000+ partidos desde 2012.
        # FBref/Playwright del master prompt innecesario: esta fuente es
        # estable y accesible desde Streamlit Cloud.
        'nombre': 'MLS', 'pais': 'Estados Unidos/Canadá', 'formato': 'new',
        'urls': [f'{FD_BASE}/new/USA.csv'], 'anios_ventana': 8,
        'disponible': True,
        # v26 (walk-forward 47.01→47.66, ll −0.005): + entropía/volatilidad
        # v35 (walk-forward 47.61→48.61, ll 1.0395→1.0347): + urgencia y CDI
        # JUNTAS (mejoran precisión Y log-loss; el CDI SOLO no pasaba: la MLS
        # cruza hasta 3 husos y la señal aparece al condicionarla al contexto
        # clasificatorio).
        'features_extra': ['cuotas', 'ent', 'urg', 'cdi'],
    },
    # v33 (§1.1): ligas de VERANO — cubren el hueco de julio-agosto cuando
    # Europa está parada. Verificado 2026-07-23 en football-data:
    #   BRA actualizado hace 4 días ✅ · ARG hace 59 (cuarentena v32 lo
    #   degrada solo) · JPN hace 228 → NO se añade (fuente abandonada).
    'brasil': {
        'nombre': 'Brasileirão Serie A', 'pais': 'Brasil', 'formato': 'new',
        'urls': [f'{FD_BASE}/new/BRA.csv'], 'anios_ventana': 8,
        'disponible': True, 'features_extra': ['cuotas'],
    },
    'argentina': {
        'nombre': 'Primera División', 'pais': 'Argentina', 'formato': 'new',
        'urls': [f'{FD_BASE}/new/ARG.csv'], 'anios_ventana': 8,
        'disponible': True, 'features_extra': ['cuotas'],
    },
    # v34 (prioridad absoluta: cobertura): ligas nórdicas y del este, TODAS
    # en plena temporada en julio. Verificado 2026-07-23 en football-data:
    # NOR 5 d · SWE 3 d · FIN 3 d · ROU 3 d · IRL 12 d de antigüedad.
    # (China y Corea tienen cuotas en The Odds API pero NO histórico
    #  gratuito para entrenar → sin modelo no hay pick; documentado.)
    'noruega': {
        'nombre': 'Eliteserien', 'pais': 'Noruega', 'formato': 'new',
        'urls': [f'{FD_BASE}/new/NOR.csv'], 'anios_ventana': 8,
        'disponible': True, 'features_extra': ['cuotas'],
    },
    'suecia': {
        'nombre': 'Allsvenskan', 'pais': 'Suecia', 'formato': 'new',
        'urls': [f'{FD_BASE}/new/SWE.csv'], 'anios_ventana': 8,
        'disponible': True, 'features_extra': ['cuotas'],
    },
    'finlandia': {
        'nombre': 'Veikkausliiga', 'pais': 'Finlandia', 'formato': 'new',
        'urls': [f'{FD_BASE}/new/FIN.csv'], 'anios_ventana': 8,
        'disponible': True, 'features_extra': ['cuotas'],
    },
    'rumania': {
        'nombre': 'Liga I', 'pais': 'Rumanía', 'formato': 'new',
        'urls': [f'{FD_BASE}/new/ROU.csv'], 'anios_ventana': 8,
        'disponible': True, 'features_extra': ['cuotas'],
    },
    'irlanda': {
        'nombre': 'Premier Division', 'pais': 'Irlanda', 'formato': 'new',
        'urls': [f'{FD_BASE}/new/IRL.csv'], 'anios_ventana': 8,
        'disponible': True, 'features_extra': ['cuotas'],
    },
    # v39 (§2.2): cobertura de INVIERNO. Verificado 2026-07-24 en football-data
    # (todas frescas a 17-21 de mayo 2026, fin de sus temporadas de invierno).
    # Grecia/Turquía en formato 'main' (stats + B365); Dinamarca/Suiza/Austria
    # en 'new' (goles + cierre AvgC*). Croacia y Chequia NO están en
    # football-data (404) → no se añaden por esta vía (candidatas a ESPN v40).
    # ADOPTADAS en Capa 1 (baten la línea base ELO en split, v39):
    #   Turquía 55.1 % (ELO 49.5, mercado 53.5) — bate mercado, ROI +14.2 %.
    #   Dinamarca 50.6 % (ELO 47.5) — bate ELO, iguala mercado.
    'turquia': {
        'nombre': 'Süper Lig', 'pais': 'Turquía', 'formato': 'main',
        'urls': [f'{FD_BASE}/mmz4281/{s}/T1.csv' for s in ('2324', '2425', '2526')],
        'disponible': True, 'features_extra': ['cuotas'],
    },
    'dinamarca': {
        'nombre': 'Superliga', 'pais': 'Dinamarca', 'formato': 'new',
        'urls': [f'{FD_BASE}/new/DNK.csv'], 'anios_ventana': 8,
        'disponible': True, 'features_extra': ['cuotas'],
    },
    # v48 (HALLAZGO): football-data SÍ publica estas ligas en formato 'new'
    # (verificado 2026-07-24). La nota de la v34 ("China/Corea sin histórico
    # gratuito") era incorrecta para China: CHN.csv tiene 2.900+ partidos y
    # está EN TEMPORADA (último 18/07/2026, hace 6 días) → cubre el hueco
    # asiático del verano. Polonia y Suiza cerraron en mayo (reanudan agosto);
    # se dejan listas y la cuarentena de pretemporada (v32) las degrada sola
    # hasta que vuelvan. Todas comparten pipeline con brasil/noruega (mismo
    # formato barato). disponible=True para que entrenen y capturen cuotas.
    'china': {
        'nombre': 'Chinese Super League', 'pais': 'China', 'formato': 'new',
        'urls': [f'{FD_BASE}/new/CHN.csv'], 'anios_ventana': 8,
        'disponible': True, 'features_extra': ['cuotas'],
    },
    'polonia': {
        'nombre': 'Ekstraklasa', 'pais': 'Polonia', 'formato': 'new',
        'urls': [f'{FD_BASE}/new/POL.csv'], 'anios_ventana': 8,
        'disponible': True, 'features_extra': ['cuotas'],
    },
    # v75 (HALLAZGO): dos ligas ACTIVAS de la Capa 1 venían de ESPN y por eso
    # tenían CERO cuota histórica — no se podían calibrar, ni medir su ROI, ni
    # devigar contra Pinnacle. Y `aut_bundesliga` era justo la peor calibrada
    # del proyecto (+13,1 pp de sobreconfianza en v71), a ciegas.
    #
    # football-data SÍ las publica en formato 'new'. Verificado por CONTENIDO
    # con `odds_store.fuente_football_data_valida` (no por HTTP 200: el
    # servidor responde 200 con OTRA liga para códigos inexistentes —
    # /new/COL.csv y /new/BOL.csv son byte a byte la Ekstraklasa polaca y
    # /new/KOR.csv es la Eliteserien noruega; con 404 solo fallan PER, URY,
    # ECU, VEN, PRY, CRI, SLV, IND, ZAF, GRC, NED).
    #   AUT: Country='Austria', League='Bundesliga', 969 partidos desde
    #        2021-07, cierre de mercado 100 %, cierre de Pinnacle 87 %.
    #   RUS: Country='Russia',  League='Premier League', 1.220 partidos,
    #        cierre de mercado 93 %, cierre de Pinnacle 88 %.
    # La red de seguridad ESPN de la v74 (`_completar_desde_espn`) sigue
    # cubriendo la cola reciente: el mapeo aut.1/rus.1 no se toca.
    # RESULTADO v75 (regla de oro): con las cuotas ya disponibles se pudo
    # medir por fin, y NO bate al ELO — acc 0.373 vs 0.425 de ELO y 0.442 del
    # mercado, exactamente el mismo veredicto que la vieja `austria` (37.3 <
    # 42.5). Es decir: llevaba desde la v68 metiendo picks en la Capa 1 una
    # liga cuyo modelo pierde contra su propia línea base, y no se veía porque
    # sin cuotas no había con qué medirla. `disponible=False`.
    'aut_bundesliga': {
        'nombre': 'Austrian Bundesliga', 'pais': 'Austria', 'formato': 'new',
        'urls': [f'{FD_BASE}/new/AUT.csv'], 'anios_ventana': 8,
        'disponible': False, 'features_extra': ['cuotas'],
        'nota': 'no bate ELO (37.3<42.5) — medido en v75 con cuotas reales.',
    },
    # RESULTADO v75: sigue adoptada y ahora medible — acc 0.530 vs 0.512 de
    # ELO (+1,8 pp), 1.944 partidos y cuota de cierre en el 100 % de las filas
    # donde antes había 0 %.
    'rus_premier': {
        'nombre': 'Russian Premier League', 'pais': 'Rusia', 'formato': 'new',
        'urls': [f'{FD_BASE}/new/RUS.csv'], 'anios_ventana': 8,
        'disponible': True, 'features_extra': ['cuotas'],
    },
    # v75: `suiza_v48` ELIMINADA. Era un duplicado EXACTO de `suiza` (misma
    # URL SWZ.csv, misma ventana de 8 años, ambas disponible=False): dos claves
    # para la misma competición. Contaba dos veces los mismos 1.599 partidos en
    # cualquier agregado (la importación de cuotas de la v75 lo destapó:
    # 3.028 filas idénticas por partida doble) y duplicaba descarga y
    # entrenamiento en cada reentreno. `validar_catalogo()` (abajo) impide que
    # vuelva a colarse un gemelo.
    # NO adoptadas (no baten ELO en split Y su backtest sangra: Grecia −24.9 %,
    # Suiza −2.3 % pero acc<ELO, Austria −17.7 %). Se dejan definidas pero
    # `disponible: False` para NO meter picks deficitarios en la Capa 1 (regla
    # del spec §2.2). Candidatas a re-evaluar en v40 con más datos / como
    # Capa 2. edge_engine excluye de la calibración las ligas no disponibles.
    # v75: `grecia` FUSIONADA en `gre_super_league` — mismo caso que Austria.
    # La misma Super League griega estaba dos veces: rechazada bajo `grecia`
    # (football-data, ROI backtest −24,9 %) y ACTIVA en Capa 1 bajo
    # `gre_super_league` (ESPN, sin cuotas y por tanto sin backtest posible).
    # Se unifica en `gre_super_league` con la fuente rica (formato 'main':
    # remates, córners, árbitro, cierre de mercado ~100 % y de Pinnacle ~85 %,
    # 5 temporadas / 1.189 partidos verificados) y la regla de oro decide.
    # RESULTADO v75: adoptada. Con 5 temporadas (1.189 partidos) en vez de las
    # 3 que tenía `grecia`, acc 0.536 vs 0.506 de ELO y 0.507 del mercado:
    # +3,0 pp sobre ELO y bate también al mercado. El rechazo de la v40
    # (42.6<44.1) era de una muestra un 40 % más corta.
    'gre_super_league': {
        'nombre': 'Super League Greece', 'pais': 'Grecia', 'formato': 'main',
        'urls': [f'{FD_BASE}/mmz4281/{s}/G1.csv'
                 for s in ('2122', '2223', '2324', '2425', '2526')],
        'disponible': True, 'features_extra': ['cuotas'],
    },
    'suiza': {
        'nombre': 'Super League', 'pais': 'Suiza', 'formato': 'new',
        'urls': [f'{FD_BASE}/new/SWZ.csv'], 'anios_ventana': 8,
        'disponible': False, 'features_extra': ['cuotas'],
        'nota': 'no bate ELO (46.0<47.3) — v40.',
    },
    # v75: `austria` FUSIONADA en `aut_bundesliga`. Eran la MISMA competición
    # (ambas AUT.csv) con veredictos contradictorios: `austria` medida con
    # football-data y RECHAZADA (no bate ELO 37.3<42.5, ROI backtest −17,7 %),
    # mientras `aut_bundesliga` — la misma liga, servida por ESPN y por tanto
    # sin cuotas con las que medir nada — estaba ACTIVA en la Capa 1. Es decir,
    # el proyecto estaba metiendo picks de una liga que su propio backtest
    # había declarado deficitaria, solo porque llevaba otra clave.
    # Se conserva una única clave (`aut_bundesliga`, la que usa el mapeo ESPN),
    # ya apuntando a football-data, y su `disponible` lo decide el
    # reentrenamiento de la v75 con la regla de oro. `validar_catalogo()`
    # impide que vuelva a haber dos claves para una competición.
    'premier': {
        # Premier se mantiene en 3 temporadas: el experimento de 5 temporadas
        # bajó la precisión (49.5%→48.9%) — regla de adopción no superada.
        'nombre': 'Premier League', 'pais': 'Inglaterra', 'formato': 'main',
        'urls': [f'{FD_BASE}/mmz4281/{s}/E0.csv' for s in ('2324', '2425', '2526')],
        'disponible': True,
        # v17 (walk-forward +1.2pp / -0.011): extras + cuotas de cierre
        'features_extra': ['extras', 'cuotas'],
    },
    'laliga': {
        'nombre': 'LaLiga', 'pais': 'España', 'formato': 'main',
        'urls': [f'{FD_BASE}/mmz4281/{s}/SP1.csv'
                 for s in ('2122', '2223', '2324', '2425', '2526')],
        'disponible': True,
        # v17 (walk-forward +1.5pp / -0.055): cuotas de cierre como features
        # v24 (walk-forward 53.09→53.33, ll 1.0328→0.9908): + componentes IMT
        # v26 (walk-forward 53.33→54.30, +0.97pp): + urgencia asimétrica
        # v59 (A/B en el espacio de producción, run_wf_ck_v59.py): +'ck'
        # (dominio territorial: córners, volumen de remates, conversión) sube
        # 52.82→53.62 (+0.80 pp) y MEJORA el log-loss 1.0679→0.9726.
        'features_extra': ['cuotas', 'imt', 'urg', 'ck'],
        # v25 (walk-forward 53.33→54.09, ll −0.016): blending con el mercado
        # en inferencia cuando hay cuotas vigentes del partido
        'blend_mercado': 0.70,
    },
    # v14: grandes ligas europeas (mismo formato 'main' con stats + cuotas B365)
    'serie_a': {
        'nombre': 'Serie A', 'pais': 'Italia', 'formato': 'main',
        # 3 temporadas: margen sobre ELO +0.9pp vs +0.0pp con 5 (v14)
        'urls': [f'{FD_BASE}/mmz4281/{s}/I1.csv' for s in ('2324', '2425', '2526')],
        'disponible': True,
        # v18/M1 (walk-forward +3.2pp / -0.049): cuotas de cierre + beta
        # calibration (la isotónica degradaba el log-loss con cuotas)
        # v26 (walk-forward 53.81→54.35, +0.54pp): + derivadas del ELO
        'features_extra': ['cuotas', 'elo_d'],
        'calibracion': 'beta',
    },
    'bundesliga': {
        'nombre': 'Bundesliga', 'pais': 'Alemania', 'formato': 'main',
        'urls': [f'{FD_BASE}/mmz4281/{s}/D1.csv'
                 for s in ('2122', '2223', '2324', '2425', '2526')],
        'disponible': True,
        # v17 (walk-forward +0.5pp / +0.003): H2H + descanso + rachas + tabla
        # v24 (walk-forward 49.55→49.81, ll 1.0247→1.0213): + índice IMT
        # v26 (walk-forward 48.85→49.25, +0.40pp): + derivadas del ELO
        'features_extra': ['extras', 'imt_c', 'elo_d'],
    },
    'ligue_1': {
        'nombre': 'Ligue 1', 'pais': 'Francia', 'formato': 'main',
        'urls': [f'{FD_BASE}/mmz4281/{s}/F1.csv'
                 for s in ('2122', '2223', '2324', '2425', '2526')],
        'disponible': True,
        # v17 (walk-forward +0.1pp / -0.057, regla 2): cuotas de cierre
        'features_extra': ['cuotas'],
        # v25 (walk-forward 51.65→52.17, ll 1.087→1.000): blending 70/30
        'blend_mercado': 0.70,
    },
    'eredivisie': {
        'nombre': 'Eredivisie', 'pais': 'Países Bajos', 'formato': 'main',
        'urls': [f'{FD_BASE}/mmz4281/{s}/N1.csv'
                 for s in ('2122', '2223', '2324', '2425', '2526')],
        'disponible': True,
        # v17 (walk-forward +0.4pp / -0.023): cuotas de cierre como features
        # v24 (walk-forward 52.21→52.82, +0.61pp): + índice compuesto IMT
        # v26 (walk-forward 51.74→52.93, +1.19pp): + derivadas del ELO
        'features_extra': ['cuotas', 'imt_c', 'elo_d'],
    },
    'primeira': {
        'nombre': 'Primeira Liga', 'pais': 'Portugal', 'formato': 'main',
        # v17 (walk-forward +0.4pp / -0.043): histórico ampliado a 10 temporadas
        'urls': [f'{FD_BASE}/mmz4281/{s}/P1.csv'
                 for s in ('1617', '1718', '1819', '1920', '2021',
                           '2122', '2223', '2324', '2425', '2526')],
        'disponible': True,
        # v24 (walk-forward 56.52→57.16, +0.64pp): componentes IMT
        # v59: +'ck' (territorial) 54.23→54.73 (+0.50 pp) y ll 0.9604→0.9519.
        'features_extra': ['imt', 'ck'],
    },
    'champions': {
        # v21: activada con API-Football (plan Free). LIMITACIÓN honesta del
        # plan: solo temporadas 2022-2024 — el estado de los equipos queda
        # congelado al final de la 2024-25 y se muestra en la UI.
        'nombre': 'UEFA Champions League', 'pais': 'Europa',
        'formato': 'api_football',
        'api_league_id': 2, 'api_seasons': [2022, 2023, 2024],
        # v22: + FBref (resultados 2017-presente, incluida la temporada en
        # curso). Walk-forward de 3 profundidades de historia (VALIDACION_v22):
        # desde 2020 = mejor log-loss medio (0.978) y regla de oro superada
        # en la ventana comparable; 2017+ y solo-2022+ documentados.
        'desde': '2020-06-01',
        'urls': [], 'disponible': True,
        # v26 (walk-forward 57.99→59.67, +1.68pp): + urgencia asimétrica
        # (en Champions la "tabla" es la general de la temporada — proxy de
        # la presión clasificatoria de la fase liga desde 2024)
        'features_extra': ['urg'],
        'nota': 'API-Football (2022-24) + FBref (resto, incl. temporada actual).',
    },
    # v35 (§2): competiciones UEFA secundarias. CORRECCIÓN DEL SPEC —
    # football-data.co.uk NO las publica (su índice solo tiene ligas
    # domésticas; /new/EUR.csv da 404, verificado 2026-07-23). La fuente
    # gratuita con cobertura profunda es el JSON de ESPN, que además trae la
    # SEDE de cada partido (insumo del CDI §3) sin peticiones extra.
    'europa_league': {
        'nombre': 'UEFA Europa League', 'pais': 'Europa',
        'formato': 'espn', 'espn_liga': 'uefa.europa',
        'api_league_id': 3,               # respaldo API-Football (2022-24)
        'desde': '2019-07-01', 'urls': [], 'disponible': True,
        # v35 (walk-forward run_wf_v35.py, 4 ventanas de 6 meses):
        #   base 50.31/1.1123 · +urg 52.13/1.0019 · +cdi 51.79/0.9989 ·
        #   +urg+cdi 51.71/0.9959 ← mejor log-loss entre las que pasan la
        # regla de oro (criterio v26). ELO de referencia 50.61 → superado.
        'features_extra': ['extras', 'urg', 'cdi'],
    },
    'conference_league': {
        'nombre': 'UEFA Conference League', 'pais': 'Europa',
        'formato': 'espn', 'espn_liga': 'uefa.europa.conf',
        'api_league_id': 848,
        # Competición nueva (arrancó en 2021-22).
        'desde': '2021-07-01', 'urls': [], 'disponible': True,
        # v35: el CDI pasa la regla por +0.62 pp pero con el log-loss PLANO
        # (1.0646→1.0670) y solo ~330 partidos de validación entre 4
        # variantes probadas: mismo criterio de comparaciones múltiples que
        # tumbó el ELO ataque/defensa en v33 → NO se adopta, se revisa con
        # una temporada más. El modelo base ya bate al ELO (46.29 vs 43.21).
        'features_extra': ['extras'],
        # Menos historia ⇒ criterio conservador (v35 §2.3).
        'umbral_confianza': 0.75,
    },
}

# ---------------------------------------------------------------------------
# v68 — Ampliación del catálogo de competiciones.
#
# Hasta v67 el catálogo eran 19 competiciones, casi todas atadas a las ~22 ligas
# que publica football-data.co.uk. `config_ligas_espn.py` (generado por
# `generar_ligas_v68.py`) añade 49 más, cada una desde la mejor fuente que la
# sirva: segundas divisiones europeas con estadística y cuotas desde
# football-data /mmz4281/, y Latinoamérica, copas y competiciones continentales
# desde ESPN.
#
# TODAS entran con `disponible: False`. Sólo el entrenamiento
# (`entrenar_ligas_v68.py`) las activa, y sólo si baten a la línea base ELO —
# la misma regla que se aplicó a Grecia, Suiza y Austria en v39.
# ---------------------------------------------------------------------------
LIGAS_V68_ANADIDAS = []
try:
    import config_ligas_espn as _lg68
    for _clave, _cfg in _lg68.LIGAS_V68.items():
        if _clave not in LEAGUES:            # nunca se pisa una liga existente
            LEAGUES[_clave] = dict(_cfg)
            LIGAS_V68_ANADIDAS.append(_clave)
    LIGAS_SIN_COBERTURA = dict(getattr(_lg68, 'SIN_VOLUMEN', {}))
except Exception:
    LIGAS_SIN_COBERTURA = {}

# v33 (§2): umbrales adaptativos de confianza por deporte. El techo de
# precisión no es igual en todos: exigir 70 % en MLB dejaría al béisbol sin
# picks (su modelo ronda 55-60 % por diseño del deporte).
UMBRALES_DEPORTE = {
    'Fútbol': {'capa1': 0.70, 'capa2': 0.75},
    'MLB':    {'capa1': 0.58, 'capa2': 0.65},
    'NBA':    {'capa1': 0.60, 'capa2': 0.70},
    'Tenis':  {'capa1': 0.65, 'capa2': 0.75},
}

POSITIONS = ['POR', 'DFC', 'DFC', 'DFC', 'LI', 'LD', 'MCD', 'MC', 'MC', 'ED', 'DC']

HISTORICO_FILE = 'historico_partidos.csv'
HISTORICO_JUGADORES_FILE = 'historico_jugadores_partidos.csv'
ELO_FILE = 'elo_actual.csv'
CALENDARIO_FILE = 'calendario_mundial_2026.csv'
EQUIPOS_OUTPUT = 'dataset_equipos_mundial.csv'
JUGADORES_OUTPUT = 'dataset_jugadores_micro.csv'

# IDs de selecciones en FBref (actualizados dinámicamente en la primera ejecución)
TEAM_IDS_FBREF = {}


# ---------------------------------------------------------------------------
# v75 — Guardia de catálogo: dos claves NO pueden apuntar a la misma liga
# ---------------------------------------------------------------------------
def validar_catalogo(leagues: dict = None) -> list:
    """
    Devuelve la lista de conflictos del catálogo. Vacía = catálogo sano.

    Nace de un fallo real: `suiza` y `suiza_v48` eran la misma competición con
    dos claves (misma URL de football-data), así que sus 1.599 partidos se
    contaban dos veces en todo agregado y se descargaban y entrenaban dos
    veces. Se detecta por la HUELLA de la fuente, que es lo único que no puede
    mentir: el conjunto de URLs para football-data, o (liga ESPN, fecha de
    inicio) para ESPN. Dos claves con la misma huella son la misma liga.

    Lo usa `tests/test_catalogo.py` — si alguien vuelve a clonar una liga, el
    test falla antes de que los números se ensucien.
    """
    leagues = LEAGUES if leagues is None else leagues
    huellas = {}
    conflictos = []
    for clave, cfg in leagues.items():
        formato = cfg.get('formato')
        if formato == 'espn':
            huella = ('espn', cfg.get('espn_liga'), str(cfg.get('desde')))
        elif cfg.get('urls'):
            huella = ('urls', tuple(sorted(cfg['urls'])),
                      cfg.get('anios_ventana'))
        elif formato == 'api_football':
            huella = ('api', cfg.get('api_league_id'),
                      tuple(cfg.get('api_seasons') or ()))
        else:
            continue
        if huella in huellas:
            conflictos.append(
                f"'{clave}' duplica a '{huellas[huella]}': misma fuente {huella[0]} "
                f"({huella[1]}). Una de las dos sobra.")
        else:
            huellas[huella] = clave
    return conflictos
