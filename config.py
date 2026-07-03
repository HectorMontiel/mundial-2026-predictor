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

POSITIONS = ['POR', 'DFC', 'DFC', 'DFC', 'LI', 'LD', 'MCD', 'MC', 'MC', 'ED', 'DC']

HISTORICO_FILE = 'historico_partidos.csv'
HISTORICO_JUGADORES_FILE = 'historico_jugadores_partidos.csv'
ELO_FILE = 'elo_actual.csv'
CALENDARIO_FILE = 'calendario_mundial_2026.csv'
EQUIPOS_OUTPUT = 'dataset_equipos_mundial.csv'
JUGADORES_OUTPUT = 'dataset_jugadores_micro.csv'

# IDs de selecciones en FBref (actualizados dinámicamente en la primera ejecución)
TEAM_IDS_FBREF = {}
