#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v68 — Competiciones de fútbol añadidas al catálogo.

GENERADO por `generar_ligas_v68.py`. No editar a mano.

40 competiciones nuevas, cada una desde la fuente de MÁS calidad
que la sirva:
  · 11 de football-data /mmz4281/ — formato "main": remates,
       córners, tarjetas Y cuotas de cierre. La mejor fuente.
  ·  1 de football-data /new/     — formato "new": goles + cuotas.
  · 28 de ESPN                   — resultados; sin cuotas ni
       estadística, pero es la única que cubre Latinoamérica y las copas.

`disponible` arranca en False en TODAS: lo activa el entrenamiento sólo
para las que baten a la línea base ELO (regla de oro del proyecto).
"""

FD_BASE = 'https://www.football-data.co.uk'

LIGAS_V68 = {
    'eng_championship': {
        'nombre': 'EFL Championship', 'pais': 'Inglaterra', 'formato': 'main',
        'urls': [f'{FD_BASE}/mmz4281/2122/E1.csv', f'{FD_BASE}/mmz4281/2223/E1.csv', f'{FD_BASE}/mmz4281/2324/E1.csv', f'{FD_BASE}/mmz4281/2425/E1.csv', f'{FD_BASE}/mmz4281/2526/E1.csv'],
        'disponible': False, 'features_extra': ['cuotas', 'extras'],
        'fuente_v68': 'football-data/mmz4281',
        'nota': 'no bate ELO (0.4422 vs 0.4496) - medido en v106 al reentrenarla; estaba activa con el modelo fuera del repo.',
    },
    'eng_league_one': {
        # v147: ventana MEDIDA del modelo. El CSV guarda 16 temporadas para el H2H; el modelo sigue entrenando con 5.
        'temporadas_modelo': 5,
        'nombre': 'EFL League One', 'pais': 'Inglaterra', 'formato': 'main',
        'urls': [f'{FD_BASE}/mmz4281/{s}/E2.csv'
                 for s in ('1011', '1112', '1213', '1314', '1415', '1516', '1617', '1718', '1819', '1920', '2021', '2122', '2223', '2324', '2425', '2526')],
        'disponible': True, 'features_extra': ['cuotas', 'extras'],
        'fuente_v68': 'football-data/mmz4281',
    },
    'eng_league_two': {
        # v147: ventana MEDIDA del modelo. El CSV guarda 16 temporadas para el H2H; el modelo sigue entrenando con 5.
        'temporadas_modelo': 5,
        'nombre': 'EFL League Two', 'pais': 'Inglaterra', 'formato': 'main',
        'urls': [f'{FD_BASE}/mmz4281/{s}/E3.csv'
                 for s in ('1011', '1112', '1213', '1314', '1415', '1516', '1617', '1718', '1819', '1920', '2021', '2122', '2223', '2324', '2425', '2526')],
        'disponible': True, 'features_extra': ['cuotas', 'extras'],
        'fuente_v68': 'football-data/mmz4281',
    },
    'eng_national': {
        # v147: ventana MEDIDA del modelo. El CSV guarda 16 temporadas para el H2H; el modelo sigue entrenando con 5.
        'temporadas_modelo': 5,
        'nombre': 'National League', 'pais': 'Inglaterra', 'formato': 'main',
        'urls': [f'{FD_BASE}/mmz4281/{s}/EC.csv'
                 for s in ('1011', '1112', '1213', '1314', '1415', '1516', '1617', '1718', '1819', '1920', '2021', '2122', '2223', '2324', '2425', '2526')],
        'disponible': True, 'features_extra': ['cuotas', 'extras'],
        'fuente_v68': 'football-data/mmz4281',
    },
    'sco_premiership': {
        # v147: ventana MEDIDA del modelo. El CSV guarda 16 temporadas para el H2H; el modelo sigue entrenando con 5.
        'temporadas_modelo': 5,
        'nombre': 'Scottish Premiership', 'pais': 'Escocia', 'formato': 'main',
        'urls': [f'{FD_BASE}/mmz4281/{s}/SC0.csv'
                 for s in ('1011', '1112', '1213', '1314', '1415', '1516', '1617', '1718', '1819', '1920', '2021', '2122', '2223', '2324', '2425', '2526')],
        'disponible': True, 'features_extra': ['cuotas', 'extras'],
        'fuente_v68': 'football-data/mmz4281',
    },
    'sco_championship': {
        # v147: ventana MEDIDA del modelo. El CSV guarda 9 temporadas para el H2H; el modelo sigue entrenando con 5.
        'temporadas_modelo': 5,
        'nombre': 'Scottish Championship', 'pais': 'Escocia', 'formato': 'main',
        'urls': [f'{FD_BASE}/mmz4281/{s}/SC1.csv'
                 for s in ('1718', '1819', '1920', '2021', '2122', '2223', '2324', '2425', '2526')],
        'disponible': True, 'features_extra': ['cuotas', 'extras'],
        'fuente_v68': 'football-data/mmz4281',
    },
    'esp_hypermotion': {
        # v147: ventana MEDIDA del modelo. El CSV guarda 9 temporadas para el H2H; el modelo sigue entrenando con 5.
        'temporadas_modelo': 5,
        'nombre': 'LaLiga Hypermotion', 'pais': 'España', 'formato': 'main',
        'urls': [f'{FD_BASE}/mmz4281/{s}/SP2.csv'
                 for s in ('1718', '1819', '1920', '2021', '2122', '2223', '2324', '2425', '2526')],
        'disponible': True, 'features_extra': ['cuotas', 'extras'],
        'fuente_v68': 'football-data/mmz4281',
    },
    'ita_serie_b': {
        # v147: ventana MEDIDA del modelo. El CSV guarda 9 temporadas para el H2H; el modelo sigue entrenando con 5.
        'temporadas_modelo': 5,
        'nombre': 'Serie B', 'pais': 'Italia', 'formato': 'main',
        'urls': [f'{FD_BASE}/mmz4281/{s}/I2.csv'
                 for s in ('1718', '1819', '1920', '2021', '2122', '2223', '2324', '2425', '2526')],
        'disponible': True, 'features_extra': ['cuotas', 'extras'],
        'fuente_v68': 'football-data/mmz4281',
    },
    'fra_ligue2': {
        # v147: ventana MEDIDA del modelo. El CSV guarda 9 temporadas para el H2H; el modelo sigue entrenando con 5.
        'temporadas_modelo': 5,
        'nombre': 'Ligue 2', 'pais': 'Francia', 'formato': 'main',
        'urls': [f'{FD_BASE}/mmz4281/{s}/F2.csv'
                 for s in ('1718', '1819', '1920', '2021', '2122', '2223', '2324', '2425', '2526')],
        'disponible': True, 'features_extra': ['cuotas', 'extras'],
        'fuente_v68': 'football-data/mmz4281',
    },
    'ger_bundesliga2': {
        # v147: ventana MEDIDA del modelo. El CSV guarda 9 temporadas para el H2H; el modelo sigue entrenando con 5.
        'temporadas_modelo': 5,
        'nombre': '2. Bundesliga', 'pais': 'Alemania', 'formato': 'main',
        'urls': [f'{FD_BASE}/mmz4281/{s}/D2.csv'
                 for s in ('1718', '1819', '1920', '2021', '2122', '2223', '2324', '2425', '2526')],
        'disponible': True, 'features_extra': ['cuotas', 'extras'],
        'fuente_v68': 'football-data/mmz4281',
    },
    'bel_pro_league': {
        'nombre': 'Jupiler Pro League', 'pais': 'Bélgica', 'formato': 'main',
        'urls': [f'{FD_BASE}/mmz4281/2122/B1.csv', f'{FD_BASE}/mmz4281/2223/B1.csv', f'{FD_BASE}/mmz4281/2324/B1.csv', f'{FD_BASE}/mmz4281/2425/B1.csv', f'{FD_BASE}/mmz4281/2526/B1.csv'],
        'disponible': False, 'features_extra': ['cuotas', 'extras'],
        'fuente_v68': 'football-data/mmz4281',
        'nota': 'no bate ELO (0.4719 vs 0.4719) - medido en v106 al reentrenarla; estaba activa con el modelo fuera del repo.',
    },
    'jpn_j1': {
        'nombre': 'J1 League', 'pais': 'Japón', 'formato': 'new',
        'urls': [f'{FD_BASE}/new/JPN.csv'], 'anios_ventana': 8,
        'disponible': True, 'features_extra': ['cuotas'],
        'fuente_v68': 'football-data/new',
    },
    'arg_primera_nacional': {
        'nombre': 'Primera Nacional', 'pais': 'Argentina', 'formato': 'espn',
        'espn_liga': 'arg.2', 'desde': '2021-07-01', 'urls': [],
        'disponible': True, 'features_extra': [],
        'fuente_v68': 'espn', 'partidos_espn': 1971,
    },
    'col_primera_a': {
        'nombre': 'Categoría Primera A', 'pais': 'Colombia', 'formato': 'espn',
        'espn_liga': 'col.1', 'desde': '2021-07-01', 'urls': [],
        'disponible': True, 'features_extra': [],
        'fuente_v68': 'espn', 'partidos_espn': 1297,
    },
    'usl_championship': {
        'nombre': 'USL Championship', 'pais': 'Estados Unidos', 'formato': 'espn',
        'espn_liga': 'usa.usl.1', 'desde': '2021-07-01', 'urls': [],
        'disponible': True, 'features_extra': [],
        'fuente_v68': 'espn', 'partidos_espn': 1166,
    },
    'ned_eerste': {
        'nombre': 'Eerste Divisie', 'pais': 'Países Bajos', 'formato': 'espn',
        'espn_liga': 'ned.2', 'desde': '2021-07-01', 'urls': [],
        'disponible': False, 'features_extra': [],
        'fuente_v68': 'espn', 'partidos_espn': 1140,
        'nota': 'no bate ELO (0.4744 vs 0.4744) - medido en v106 al reentrenarla; estaba activa con el modelo fuera del repo.',
    },
    'bra_serie_b': {
        'nombre': 'Brasileirão Série B', 'pais': 'Brasil', 'formato': 'espn',
        'espn_liga': 'bra.2', 'desde': '2021-07-01', 'urls': [],
        'disponible': True, 'features_extra': [],
        'fuente_v68': 'espn', 'partidos_espn': 1136,
    },
    'per_liga1': {
        'nombre': 'Liga 1', 'pais': 'Perú', 'formato': 'espn',
        'espn_liga': 'per.1', 'desde': '2021-07-01', 'urls': [],
        'disponible': True, 'features_extra': [],
        'fuente_v68': 'espn', 'partidos_espn': 929,
    },
    'uru_primera': {
        'nombre': 'Primera División', 'pais': 'Uruguay', 'formato': 'espn',
        'espn_liga': 'uru.1', 'desde': '2021-07-01', 'urls': [],
        'disponible': True, 'features_extra': [],
        'fuente_v68': 'espn', 'partidos_espn': 888,
    },
    'ecu_liga_pro': {
        'nombre': 'LigaPro Serie A', 'pais': 'Ecuador', 'formato': 'espn',
        'espn_liga': 'ecu.1', 'desde': '2021-07-01', 'urls': [],
        'disponible': True, 'features_extra': [],
        'fuente_v68': 'espn', 'partidos_espn': 849,
    },
    'slv_primera': {
        'nombre': 'Primera División', 'pais': 'El Salvador', 'formato': 'espn',
        'espn_liga': 'slv.1', 'desde': '2021-07-01', 'urls': [],
        'disponible': False, 'features_extra': [],
        'fuente_v68': 'espn', 'partidos_espn': 832,
        'nota': 'no bate ELO (0.4713 vs 0.4828) - medido en v106 al reentrenarla; estaba activa con el modelo fuera del repo.',
    },
    'bol_division': {
        'nombre': 'División Profesional', 'pais': 'Bolivia', 'formato': 'espn',
        'espn_liga': 'bol.1', 'desde': '2021-07-01', 'urls': [],
        'disponible': True, 'features_extra': [],
        'fuente_v68': 'espn', 'partidos_espn': 799,
    },
    'par_division': {
        'nombre': 'División Profesional', 'pais': 'Paraguay', 'formato': 'espn',
        'espn_liga': 'par.1', 'desde': '2021-07-01', 'urls': [],
        'disponible': False, 'features_extra': [],
        'fuente_v68': 'espn', 'partidos_espn': 774,
        'nota': 'no bate ELO (0.4722 vs 0.4722) - medido en v106 al reentrenarla; estaba activa con el modelo fuera del repo.',
    },
    'crc_fpd': {
        'nombre': 'Liga FPD', 'pais': 'Costa Rica', 'formato': 'espn',
        'espn_liga': 'crc.1', 'desde': '2021-07-01', 'urls': [],
        'disponible': False, 'features_extra': [],
        'fuente_v68': 'espn', 'partidos_espn': 741,
        'nota': 'no bate ELO (0.4741 vs 0.4781) - medido en v106 al reentrenarla; estaba activa con el modelo fuera del repo.',
    },
    'mex_expansion': {
        'nombre': 'Liga de Expansión MX', 'pais': 'México', 'formato': 'espn',
        'espn_liga': 'mex.2', 'desde': '2021-07-01', 'urls': [],
        'disponible': True, 'features_extra': [],
        'fuente_v68': 'espn', 'partidos_espn': 720,
    },
    'gre_super_league': {
        # v147: ventana MEDIDA del modelo. El CSV guarda 9 temporadas para el H2H; el modelo sigue entrenando con 5.
        'temporadas_modelo': 5,
        'nombre': 'Super League Greece', 'pais': 'Grecia', 'formato': 'espn',
        'espn_liga': 'gre.1', 'desde': '2021-07-01', 'urls': [],
        'disponible': True, 'features_extra': [],
        'fuente_v68': 'espn', 'partidos_espn': 712,
    },
    'rus_premier': {
        'nombre': 'Russian Premier League', 'pais': 'Rusia', 'formato': 'espn',
        'espn_liga': 'rus.1', 'desde': '2021-07-01', 'urls': [],
        'disponible': True, 'features_extra': [],
        'fuente_v68': 'espn', 'partidos_espn': 712,
    },
    'chi_primera': {
        'nombre': 'Campeonato Nacional', 'pais': 'Chile', 'formato': 'espn',
        'espn_liga': 'chi.1', 'desde': '2021-07-01', 'urls': [],
        'disponible': True, 'features_extra': [],
        'fuente_v68': 'espn', 'partidos_espn': 695,
    },
    'rsa_premier': {
        'nombre': 'South African Premier Division', 'pais': 'Sudáfrica', 'formato': 'espn',
        'espn_liga': 'rsa.1', 'desde': '2021-07-01', 'urls': [],
        'disponible': True, 'features_extra': [],
        'fuente_v68': 'espn', 'partidos_espn': 695,
    },
    'ven_primera': {
        'nombre': 'Liga FUTVE', 'pais': 'Venezuela', 'formato': 'espn',
        'espn_liga': 'ven.1', 'desde': '2021-07-01', 'urls': [],
        'disponible': False, 'features_extra': [],
        'fuente_v68': 'espn', 'partidos_espn': 657,
    },
    'aut_bundesliga': {
        'nombre': 'Austrian Bundesliga', 'pais': 'Austria', 'formato': 'espn',
        'espn_liga': 'aut.1', 'desde': '2021-07-01', 'urls': [],
        'disponible': True, 'features_extra': [],
        'fuente_v68': 'espn', 'partidos_espn': 579,
    },
    'aus_aleague': {
        'nombre': 'A-League Men', 'pais': 'Australia', 'formato': 'espn',
        'espn_liga': 'aus.1', 'desde': '2021-07-01', 'urls': [],
        'disponible': False, 'features_extra': [],
        'fuente_v68': 'espn', 'partidos_espn': 508,
    },
    'libertadores': {
        'nombre': 'Copa Libertadores', 'pais': 'Américas', 'formato': 'espn',
        'espn_liga': 'conmebol.libertadores', 'desde': '2021-07-01', 'urls': [],
        'disponible': True, 'features_extra': [],
        'fuente_v68': 'espn', 'partidos_espn': 464,
    },
    'sudamericana': {
        'nombre': 'Copa Sudamericana', 'pais': 'Américas', 'formato': 'espn',
        'espn_liga': 'conmebol.sudamericana', 'desde': '2021-07-01', 'urls': [],
        'disponible': True, 'features_extra': [],
        'fuente_v68': 'espn', 'partidos_espn': 462,
    },
    'eng_fa_cup': {
        'nombre': 'FA Cup', 'pais': 'Inglaterra', 'formato': 'espn',
        'espn_liga': 'eng.fa', 'desde': '2021-07-01', 'urls': [],
        'disponible': False, 'features_extra': [],
        'fuente_v68': 'espn', 'partidos_espn': 395,
        'nota': 'no bate ELO (0.4177 vs 0.5823) - medido en v106 al reentrenarla; estaba activa con el modelo fuera del repo.',
    },
    'ind_isl': {
        'nombre': 'Indian Super League', 'pais': 'India', 'formato': 'espn',
        'espn_liga': 'ind.1', 'desde': '2021-07-01', 'urls': [],
        'disponible': False, 'features_extra': [],
        'fuente_v68': 'espn', 'partidos_espn': 393,
    },
    'esp_copa_rey': {
        'nombre': 'Copa del Rey', 'pais': 'España', 'formato': 'espn',
        'espn_liga': 'esp.copa_del_rey', 'desde': '2021-07-01', 'urls': [],
        'disponible': False, 'features_extra': [],
        'fuente_v68': 'espn', 'partidos_espn': 389,
    },
    'afc_champions': {
        'nombre': 'AFC Champions League', 'pais': 'Asia', 'formato': 'espn',
        'espn_liga': 'afc.champions', 'desde': '2021-07-01', 'urls': [],
        'disponible': True, 'features_extra': [],
        'fuente_v68': 'espn', 'partidos_espn': 377,
    },
    'bra_copa': {
        'nombre': 'Copa do Brasil', 'pais': 'Brasil', 'formato': 'espn',
        'espn_liga': 'bra.copa_do_brazil', 'desde': '2021-07-01', 'urls': [],
        'disponible': False, 'features_extra': [],
        'fuente_v68': 'espn', 'partidos_espn': 374,
    },
    'eng_carabao': {
        'nombre': 'EFL Cup (Carabao)', 'pais': 'Inglaterra', 'formato': 'espn',
        'espn_liga': 'eng.league_cup', 'desde': '2021-07-01', 'urls': [],
        'disponible': False, 'features_extra': [],
        'fuente_v68': 'espn', 'partidos_espn': 279,
    },
    # v144 — SAUDI PRO LEAGUE, con la validación estricta que se pidió.
    #
    # El encargo la pedía «sólo si el backtest supera el 52 % y el p5 del ROI
    # es positivo». Se da de alta con la FUENTE configurada y
    # `disponible: False`, que es exactamente lo que implementa esa condición
    # en este proyecto: el flujo de reentrenamiento (`entrenar_ligas_v68.py`,
    # que corre a diario en `retrain_leagues.yml`) la entrena, la mide contra
    # la línea base ELO y **sólo entonces** le pone `disponible: True`. Si no
    # bate, se queda informativa y con el motivo escrito, como las quince que
    # ya están así.
    #
    # Volumen verificado contra ESPN el 2026-08-16: **865 partidos en 2023,
    # 2024 y 2025**, muy por encima del mínimo de volumen del catálogo. Es la
    # única de las seis ligas nuevas del encargo con cobertura suficiente
    # (ver `SIN_FUENTE` abajo).
    'ksa_pro': {
        'nombre': 'Saudi Pro League', 'pais': 'Arabia Saudita',
        'formato': 'espn', 'espn_liga': 'ksa.1', 'desde': '2022-07-01',
        'urls': [], 'disponible': False, 'features_extra': [],
        'fuente_v68': 'espn', 'partidos_espn': 865,
        'nota': 'alta en v144 con validación estricta: se activa sola si el '
                'reentrenamiento la mide por encima de la línea base ELO.',
    },
}

# v144 — BÚSQUEDA DE FUENTE PARA LAS LIGAS PEDIDAS QUE NO TENÍAMOS.
#
# ESPN se verificó contra su CATÁLOGO REAL, no contra códigos adivinados:
# `site.api.espn.com/apis/site/v2/leagues/dropdown?sport=soccer` devuelve las
# **216 competiciones** que publica. Ninguna de las cinco de abajo está en esa
# lista; sí están `ksa.1`, `aut.1`, `ger.2` y `jpn.1`, que son otras.
#
# Después se sondearon, una por una, las fuentes gratuitas del proyecto y
# varias externas. El resultado, medido el 2026-08-16:
#
# | fuente                | qué aporta                                        |
# |-----------------------|---------------------------------------------------|
# | ESPN (216 ligas)      | Saudi `ksa.1` ✔ · ninguna de las otras cinco       |
# | football-data.co.uk   | **NINGUNA**. Ver la trampa de abajo               |
# | FBref                 | HTTP 403 (Cloudflare), sigue bloqueado            |
# | OpenLigaDB            | **3. Liga alemana ✔** 380 partidos/temporada      |
# | OpenFootball (GitHub) | **2. Liga austriaca ✔** 240/temporada, 2 años     |
# | TheSportsDB (clave 3) | tiene Croacia y J2 en catálogo, pero la clave     |
# |                       | gratuita devuelve **5 partidos por temporada**:   |
# |                       | es una muestra comercial, no un histórico         |
#
# LA TRAMPA DE football-data, QUE CASI CUESTA UN ERROR CARO
# ---------------------------------------------------------
# `new/JPN2.csv` responde 200 con 4.523 filas y parece la J2. **No lo es**: su
# columna `League` dice «J1 League» en las 4.523. El `2` del nombre es
# numeración de fichero, no división — igual que `AUT2.csv` y `SWZ2.csv`, que
# devuelven exactamente las mismas filas que `AUT.csv` y `SWZ.csv`.
#
# Registrar ese CSV como «Japón J2» habría metido partidos de PRIMERA división
# en una liga de segunda, con nombres de equipo que casan y sin dar un solo
# error. Es el mismo modo de fallo que «Wroclaw Panthers → Carolina Panthers»
# de la v131: no revienta, miente. Se comprobó la columna antes de usarlo.
SIN_FUENTE = {
    'cro_hnl': ('Croatian HNL',
                'ESPN no la tiene (216 ligas revisadas) · football-data no · '
                'FBref 403 · OpenFootball no · TheSportsDB sólo 5 por temporada',
                'sin fuente gratuita con histórico completo'),
    'jpn_j2': ('J2 League',
               'ESPN no · football-data `JPN2.csv` es J1, no J2 · FBref 403 · '
               'TheSportsDB sólo 5 por temporada',
               'sin fuente gratuita con histórico completo'),
    'esp_primera_fed': ('Primera Federación',
                        'ESPN no · football-data llega a 2.ª (`SP2`) · '
                        'OpenFootball llega a `es.2` · FBref 403',
                        'sin fuente gratuita con histórico completo'),
}

# v144 — PEDIDA, CON FUENTE ENCONTRADA Y PENDIENTE DE INGESTA.
#
# SÍ tiene de dónde salir. No se da de alta en `LIGAS_V68` todavía porque su
# fuente no es ninguna de las dos que el pipeline sabe leer (football-data y
# ESPN): hace falta un ingestor, como en su día lo hubo para la KBO o la
# Leagues Cup. Queda escrito con el endpoint exacto y el volumen verificado
# para que sea trabajo de implementar, no de investigar.
CON_FUENTE_PENDIENTE = {
    'ger_3liga': {
        'nombre': '3. Liga', 'pais': 'Alemania',
        'fuente': 'OpenLigaDB', 'sin_clave': True,
        'endpoint': 'https://api.openligadb.de/getmatchdata/bl3/{temporada}',
        'volumen': '380 partidos por temporada, temporadas 2022-2026 '
                   'disponibles (~1.900 en total) y SIN huecos',
        'verificado': '2026-08-16',
    },
}

# Pedidas pero descartadas por falta de volumen. Se documentan para no
# fingir cobertura: el número es cuántos partidos devuelve ESPN en 3 años.
SIN_VOLUMEN = {
    'uefa_nations': ('UEFA Nations League', 'uefa.nations', 'solo 190 partidos en 3 años'),
    'fra_coupe': ('Coupe de France', 'fra.coupe_de_france', 'solo 189 partidos en 3 años'),
    'ger_dfb_pokal': ('DFB-Pokal', 'ger.dfb_pokal', 'solo 189 partidos en 3 años'),
    'caf_champions': ('CAF Champions League', 'caf.champions', 'solo 186 partidos en 3 años'),
    'leagues_cup': ('Leagues Cup', 'concacaf.leagues.cup', 'solo 171 partidos en 3 años'),
    'concacaf_ccc': ('CONCACAF Champions Cup', 'concacaf.champions', 'solo 153 partidos en 3 años'),
    'ita_coppa': ('Coppa Italia', 'ita.coppa_italia', 'solo 133 partidos en 3 años'),
    'afcon': ('Copa Africana de Naciones', 'caf.nations', 'solo 104 partidos en 3 años'),
    'mundial_clubes': ('Mundial de Clubes', 'fifa.cwc', 'solo 71 partidos en 3 años'),
    'copa_asiatica': ('Copa Asiática', 'afc.asian.cup', 'solo 51 partidos en 3 años'),
    'mex_femenil': ('Liga MX Femenil', 'mex.w.1', 'sin cobertura en ESPN'),
    'arg_copa_liga': ('Copa de la Liga', 'arg.copa_lpf', 'sin cobertura en ESPN'),
    'bul_parva': ('First Professional Football League', 'bul.1', 'sin cobertura en ESPN'),
    'can_premier': ('Canadian Premier League', 'can.1', 'sin cobertura en ESPN'),
    'col_primera_b': ('Categoría Primera B', 'col.2', 'sin cobertura en ESPN'),
    'cro_hnl': ('HNL', 'cro.1', 'sin cobertura en ESPN'),
    'cyp_first': ('Cypriot First Division', 'cyp.1', 'sin cobertura en ESPN'),
    'cze_first': ('Czech First League', 'cze.1', 'sin cobertura en ESPN'),
    'est_meistriliiga': ('Meistriliiga', 'est.1', 'sin cobertura en ESPN'),
    'hun_nbi': ('Nemzeti Bajnokság I', 'hun.1', 'sin cobertura en ESPN'),
    'isl_besta': ('Besta deild karla', 'isl.1', 'sin cobertura en ESPN'),
    'idn_liga1': ('Liga 1', 'idn.1', 'sin cobertura en ESPN'),
    'isr_premier': ('Israeli Premier League', 'isr.1', 'sin cobertura en ESPN'),
    'kaz_premier': ('Kazakhstan Premier League', 'kaz.1', 'sin cobertura en ESPN'),
    'ltu_alyga': ('A Lyga', 'ltu.1', 'sin cobertura en ESPN'),
    'nir_premiership': ('NIFL Premiership', 'nir.1', 'sin cobertura en ESPN'),
    'pan_lpf': ('Liga Panameña de Fútbol', 'pan.1', 'sin cobertura en ESPN'),
    'por_liga2': ('Liga Portugal 2', 'por.2', 'sin cobertura en ESPN'),
    'kor_k1': ('K League 1', 'kor.1', 'sin cobertura en ESPN'),
    'kor_k2': ('K League 2', 'kor.2', 'sin cobertura en ESPN'),
    'srb_superliga': ('Serbian SuperLiga', 'srb.1', 'sin cobertura en ESPN'),
    'svk_nike': ('Niké Liga', 'svk.1', 'sin cobertura en ESPN'),
    'svn_prvaliga': ('PrvaLiga', 'slo.1', 'sin cobertura en ESPN'),
    'sui_super_league': ('Swiss Super League', 'sui.1', 'sin cobertura en ESPN'),
    'ukr_premier': ('Ukrainian Premier League', 'ukr.1', 'sin cobertura en ESPN'),
    'uzb_super': ('Uzbekistan Super League', 'uzb.1', 'sin cobertura en ESPN'),
    'wal_cymru': ('Cymru Premier', 'wal.1', 'sin cobertura en ESPN'),
    'nic_primera': ('Liga Primera', 'nca.1', 'sin cobertura en ESPN'),
    'lbn_premier': ('Lebanese Premier League', 'lbn.1', 'sin cobertura en ESPN'),
    'mya_national': ('Myanmar National League', 'mya.1', 'sin cobertura en ESPN'),
    'bhu_premier': ('Bhutan Premier League', 'bhu.1', 'sin cobertura en ESPN'),
    'fro_effodeildin': ('Effodeildin', 'fro.1', 'sin cobertura en ESPN'),
    'chi_primera_b': ('Primera B', 'chi.2', 'sin cobertura en ESPN'),
    'ecu_serie_b': ('LigaPro Serie B', 'ecu.2', 'sin cobertura en ESPN'),
    'per_liga2': ('Liga 2', 'per.2', 'sin cobertura en ESPN'),
    'esp_primera_rfef': ('Primera RFEF', 'esp.3', 'sin cobertura en ESPN'),
    'ita_serie_c': ('Serie C', 'ita.3', 'sin cobertura en ESPN'),
    'mex_liga_premier': ('Liga Premier', 'mex.3', 'sin cobertura en ESPN'),
    # v144 — Austria 2. Liga. SÍ tiene fuente gratuita (OpenFootball
    # `at.2.json`) y aun así se descarta, que es la diferencia con las de
    # arriba: no falta de dónde bajarla, falta QUÉ bajar.
    #
    # Medido el 2026-08-16: 240 partidos en 2024-25 y 240 en 2025-26, y
    # **2023-24 no existe en la fuente**. O sea 480 de los ~720 de tres
    # temporadas, con un año entero en blanco justo al principio de la ventana
    # — que es el tramo con el que se entrena.
    #
    # Un hueco así no es «menos muestra»: descoloca el estado rodante y el ELO
    # arrancaría de cero a mitad del histórico. El criterio del usuario fue
    # explícito —«solo mantén las que tengan buen histórico»— y ésta no lo
    # tiene. Se deja escrita para no volver a investigarla.
    'aut_2liga': ('2. Liga (Austria)', 'OpenFootball at.2.json',
                  'sólo 480 de ~720 partidos: falta la temporada 2023-24 '
                  'entera. Histórico con hueco, descartada en v144'),
}

# Slug de ESPN por competición. Es lo que hace que la liga aparezca en
# FIXTURES y, con ello, en Apuestas del Día: `alpha_finder` solo barre las
# ligas que están en `fixtures_espn.ESPN_CODIGOS`. Las que vienen de
# football-data también lo llevan, porque su histórico es de ahí pero sus
# PRÓXIMOS partidos y cuotas salen de ESPN.
ESPN_CODIGOS_V68 = {
    'eng_championship': 'eng.2',
    'eng_league_one': 'eng.3',
    'eng_league_two': 'eng.4',
    'eng_national': 'eng.5',
    'sco_premiership': 'sco.1',
    'sco_championship': 'sco.2',
    'esp_hypermotion': 'esp.2',
    'ita_serie_b': 'ita.2',
    'fra_ligue2': 'fra.2',
    'ger_bundesliga2': 'ger.2',
    'bel_pro_league': 'bel.1',
    'jpn_j1': 'jpn.1',
    'arg_primera_nacional': 'arg.2',
    'col_primera_a': 'col.1',
    'usl_championship': 'usa.usl.1',
    'ned_eerste': 'ned.2',
    'bra_serie_b': 'bra.2',
    'per_liga1': 'per.1',
    'uru_primera': 'uru.1',
    'ecu_liga_pro': 'ecu.1',
    'slv_primera': 'slv.1',
    'bol_division': 'bol.1',
    'par_division': 'par.1',
    'crc_fpd': 'crc.1',
    'mex_expansion': 'mex.2',
    'gre_super_league': 'gre.1',
    'rus_premier': 'rus.1',
    'chi_primera': 'chi.1',
    'rsa_premier': 'rsa.1',
    'ven_primera': 'ven.1',
    'aut_bundesliga': 'aut.1',
    'aus_aleague': 'aus.1',
    'libertadores': 'conmebol.libertadores',
    'sudamericana': 'conmebol.sudamericana',
    'eng_fa_cup': 'eng.fa',
    'ind_isl': 'ind.1',
    'esp_copa_rey': 'esp.copa_del_rey',
    'afc_champions': 'afc.champions',
    'bra_copa': 'bra.copa_do_brazil',
    'eng_carabao': 'eng.league_cup',
}
