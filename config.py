#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Configuración central del pipeline."""

# Las 49 selecciones clasificadas al Mundial 2026 (incluye Cabo Verde)
TEAMS = [
    'MEX', 'USA', 'CAN', 'ARG', 'BRA', 'URU', 'COL', 'ECU', 'PER', 'CHI',
    'FRA', 'ENG', 'ESP', 'GER', 'ITA', 'POR', 'NED', 'BEL', 'CRO', 'SRB',
    'MAR', 'SEN', 'CMR', 'GHA', 'NGA', 'TUN', 'ALG', 'EGY',
    'JPN', 'KOR', 'IRN', 'AUS', 'KSA', 'QAT', 'CRC', 'PAN', 'HON', 'JAM',
    'PAR', 'NOR', 'SUI', 'DEN', 'AUT', 'SCO', 'CIV', 'UZB', 'JOR', 'NZL',
    'CPV',
]

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
        'features_extra': ['cuotas', 'ent'],
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
        'features_extra': ['cuotas', 'imt', 'urg'],
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
        'features_extra': ['imt'],
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
}

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
