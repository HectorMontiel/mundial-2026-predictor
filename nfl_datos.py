#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v131 · NFL — capa de datos.

Qué fuente y por qué (Informe de Viabilidad, medido el 2026-08-15)
------------------------------------------------------------------
La pregunta del encargo era si ESPN basta o hay que salir a scrapear
Pro-Football-Reference o `nflfastR`. Se midió antes de decidir, y ESPN basta
**con holgura**, incluida la parte que no se esperaba:

| endpoint ESPN | qué da | coste |
|---|---|---|
| `site.../football/nfl/scoreboard?dates=YYYY` | el año natural entero de una vez (335 eventos en 2024: playoffs del año anterior + pretemporada + liga regular) | 1 petición · 2,8 MB |
| `site.../football/nfl/summary?event=ID` | **25 estadísticas de equipo por bando**: yardas totales, yardas por jugada, yardas por acarreo y por pase, 3.º y 4.º down, zona roja, pérdidas de balón, sacks, penalizaciones, posesión, jugadas totales | 1 petición/partido · ~1,2 s |
| `sports.core.../events/{id}/competitions/{id}/odds` | **cuotas de CIERRE históricas** (moneyline, hándicap y total) de hasta 13 casas, con `open` y `close` separados | 1 petición/partido |
| `site.../football/nfl/teams` | los 32 equipos con id, abreviatura y nombre | 1 petición |

El tercero es el que cambia el proyecto: **sin él no habría backtest de ROI**,
sólo de acierto — y la bitácora es explícita en que el acierto no decide nada
(§0: el modelo está calibrado y aun así pierde). Con precios de cierre reales
se puede medir lo único que importa, que es si comprar a ese precio gana.

Las alternativas que el encargo pedía evaluar, y por qué NO se usan
------------------------------------------------------------------
| fuente | pros | contras | veredicto |
|---|---|---|---|
| **ESPN** *(elegida)* | ya integrada (`fixtures_espn`), sin clave, sin coste, trae stats **y** cuotas de cierre, un solo espacio de nombres para calendario y estadística | 403 desde IP de centro de datos (ya conocido, v98) | **ELEGIDA** |
| Pro-Football-Reference | la referencia histórica, muy profunda | HTML, tablas dentro de comentarios, `robots.txt` con 1 petición/3 s y bloqueo agresivo por ráfaga; **no trae cuotas**; habría que casar sus nombres con los de ESPN, o sea un segundo espacio de identificadores | descartada: añade fragilidad y un mapeo más sin aportar nada que ESPN no dé |
| nflfastR / `nfl_data_py` | play-by-play con EPA ya calculado | dependencia pesada (pyarrow + parquets de cientos de MB por temporada) contra el techo de memoria de Streamlit Cloud, que la bitácora §8 vigila explícitamente; **no trae cuotas de casa**; y para 1X2/hándicap/total la agregación por partido de ESPN contiene la misma información | descartada por coste de memoria en despliegue |
| APIs públicas gratuitas de terceros | — | las sondeadas en la v126 (`sondeo_casas`) o piden clave de pago o no cubren NFL | descartada |
| Combinación calendario ESPN + stats PFR | — | resuelve un problema que no existe: ESPN ya da las dos cosas **con el mismo id de partido**, que es justo lo que evita el desemparejamiento | innecesaria |

**Regla que esto respeta** (bitácora §5b): no se añade una fuente nueva si la
integrada cubre el dato. Aquí lo cubre, y además con un identificador común
—el `event_id` de ESPN— que es lo que impide el fallo silencioso de cruzar dos
espacios de nombres distintos (la lección del tenis: Altenar `dst:player:NNN`
no es StatsAPI).

Riesgo asumido y su plan
------------------------
ESPN devuelve **403 desde Streamlit Cloud** (medido en la v98 con la MLB). Por
eso el histórico se construye **fuera de línea** y viaja en el repositorio como
`historico_nfl.csv`; en producción sólo hace falta el calendario del día, y ahí
`fixtures_nfl()` degrada al catálogo de Playdoit, que es la misma cadena de
respaldo que ya usan la MLB y la NBA.
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Dict, List, Optional, Tuple

import pandas as pd
import requests

logger = logging.getLogger(__name__)

SITE = 'https://site.api.espn.com/apis/site/v2/sports/football/nfl'
CORE = 'https://sports.core.api.espn.com/v2/sports/football/leagues/nfl'
# EL USER-AGENT LARGO ES EL QUE BLOQUEAN, NO EL CORTO.
#
# Medido el 2026-08-15 contra `site.api/summary`, tres peticiones seguidas al
# mismo evento:
#
#     'Mozilla/5.0'                                   → 200 · 467 KB
#     'Mozilla/5.0 (Windows NT 10.0…Chrome/126.0…)'   → 403 ·  442 B
#     sin cabecera                                    → 200 · 467 KB
#
# Es al revés de lo que se supondría: imitar mejor a un navegador es lo que
# activa el filtro. `fixtures_espn` ya usaba el corto y por eso nunca dio
# problema; copiar aquí el de `cuotas_multi` (que va contra otras casas)
# habría dejado el histórico entero sin descargar, con un 403 por partido y
# ningún error visible más allá de un CSV vacío.
UA = {'User-Agent': 'Mozilla/5.0'}
TIMEOUT = 25
HISTORICO = 'historico_nfl.csv'

# Tipos de temporada de ESPN. La PRETEMPORADA se recoge pero se marca, nunca se
# mezcla: los titulares juegan un cuarto y las medias de un partido de agosto no
# describen al equipo que jugará en septiembre. El modelo la excluye del
# entrenamiento y la interfaz la etiqueta.
TIPO_TEMPORADA = {1: 'pretemporada', 2: 'regular', 3: 'playoffs', 4: 'pro_bowl'}


# ---------------------------------------------------------------------------
# Los 32 equipos y el mapeo de nombres — la parte crítica del encargo
# ---------------------------------------------------------------------------
# EL MAPEO NO SE ADIVINA, SE ESCRIBE.
#
# Playdoit publica los equipos abreviados y con basura de tabulación:
# «NE  Patriots», «SF 49ers\t\t», «ARZ Cardinals», «WAS Commanders\t\t». ESPN
# los publica completos: «New England Patriots», «San Francisco 49ers»,
# «Arizona Cardinals», «Washington Commanders».
#
# Tres trampas concretas que un emparejador por parecido resolvería MAL, y que
# son la razón de que esta tabla sea explícita:
#
#   · «LA Rams» y «LA Chargers» comparten prefijo de ciudad. Un parecido por
#     tokens los confunde entre sí en cuanto el sufijo se abrevie.
#   · «NY Jets» y «NY Giants», lo mismo.
#   · «ARZ Cardinals» — Playdoit usa ARZ, ESPN usa ARI. Ninguna abreviatura
#     estándar dice ARZ, así que casar por abreviatura falla en silencio.
#
# El fallo aquí no da excepción: da una apuesta al equipo equivocado con un EV
# inventado. Es exactamente lo que la v77 encontró en la MLB con la orientación
# local/visitante, y lo que `VENTAJA_IMPOSIBLE` existe para atrapar después.
# Esta tabla es la primera red; la de `clasificador` es la segunda.
EQUIPOS: Dict[str, Dict[str, str]] = {
    'ARI': {'espn_id': '22', 'nombre': 'Arizona Cardinals', 'apodo': 'Cardinals'},
    'ATL': {'espn_id': '1', 'nombre': 'Atlanta Falcons', 'apodo': 'Falcons'},
    'BAL': {'espn_id': '33', 'nombre': 'Baltimore Ravens', 'apodo': 'Ravens'},
    'BUF': {'espn_id': '2', 'nombre': 'Buffalo Bills', 'apodo': 'Bills'},
    'CAR': {'espn_id': '29', 'nombre': 'Carolina Panthers', 'apodo': 'Panthers'},
    'CHI': {'espn_id': '3', 'nombre': 'Chicago Bears', 'apodo': 'Bears'},
    'CIN': {'espn_id': '4', 'nombre': 'Cincinnati Bengals', 'apodo': 'Bengals'},
    'CLE': {'espn_id': '5', 'nombre': 'Cleveland Browns', 'apodo': 'Browns'},
    'DAL': {'espn_id': '6', 'nombre': 'Dallas Cowboys', 'apodo': 'Cowboys'},
    'DEN': {'espn_id': '7', 'nombre': 'Denver Broncos', 'apodo': 'Broncos'},
    'DET': {'espn_id': '8', 'nombre': 'Detroit Lions', 'apodo': 'Lions'},
    'GB': {'espn_id': '9', 'nombre': 'Green Bay Packers', 'apodo': 'Packers'},
    'HOU': {'espn_id': '34', 'nombre': 'Houston Texans', 'apodo': 'Texans'},
    'IND': {'espn_id': '11', 'nombre': 'Indianapolis Colts', 'apodo': 'Colts'},
    'JAX': {'espn_id': '30', 'nombre': 'Jacksonville Jaguars', 'apodo': 'Jaguars'},
    'KC': {'espn_id': '12', 'nombre': 'Kansas City Chiefs', 'apodo': 'Chiefs'},
    'LAC': {'espn_id': '24', 'nombre': 'Los Angeles Chargers', 'apodo': 'Chargers'},
    'LAR': {'espn_id': '14', 'nombre': 'Los Angeles Rams', 'apodo': 'Rams'},
    'LV': {'espn_id': '13', 'nombre': 'Las Vegas Raiders', 'apodo': 'Raiders'},
    'MIA': {'espn_id': '15', 'nombre': 'Miami Dolphins', 'apodo': 'Dolphins'},
    'MIN': {'espn_id': '16', 'nombre': 'Minnesota Vikings', 'apodo': 'Vikings'},
    'NE': {'espn_id': '17', 'nombre': 'New England Patriots', 'apodo': 'Patriots'},
    'NO': {'espn_id': '18', 'nombre': 'New Orleans Saints', 'apodo': 'Saints'},
    'NYG': {'espn_id': '19', 'nombre': 'New York Giants', 'apodo': 'Giants'},
    'NYJ': {'espn_id': '20', 'nombre': 'New York Jets', 'apodo': 'Jets'},
    'PHI': {'espn_id': '21', 'nombre': 'Philadelphia Eagles', 'apodo': 'Eagles'},
    'PIT': {'espn_id': '23', 'nombre': 'Pittsburgh Steelers', 'apodo': 'Steelers'},
    'SEA': {'espn_id': '26', 'nombre': 'Seattle Seahawks', 'apodo': 'Seahawks'},
    'SF': {'espn_id': '25', 'nombre': 'San Francisco 49ers', 'apodo': '49ers'},
    'TB': {'espn_id': '27', 'nombre': 'Tampa Bay Buccaneers', 'apodo': 'Buccaneers'},
    'TEN': {'espn_id': '10', 'nombre': 'Tennessee Titans', 'apodo': 'Titans'},
    'WSH': {'espn_id': '28', 'nombre': 'Washington Commanders', 'apodo': 'Commanders'},
}

# Estadios: coordenadas y huso horario estándar, para viaje y cruce de husos.
# Mismo patrón que `nba_features.ARENAS`, que ya está medido y probado.
ESTADIOS: Dict[str, Tuple[float, float, int]] = {
    'ARI': (33.5276, -112.2626, -7), 'ATL': (33.7554, -84.4008, -5),
    'BAL': (39.2780, -76.6227, -5), 'BUF': (42.7738, -78.7870, -5),
    'CAR': (35.2258, -80.8528, -5), 'CHI': (41.8623, -87.6167, -6),
    'CIN': (39.0955, -84.5160, -5), 'CLE': (41.5061, -81.6995, -5),
    'DAL': (32.7473, -97.0945, -6), 'DEN': (39.7439, -105.0201, -7),
    'DET': (42.3400, -83.0456, -5), 'GB': (44.5013, -88.0622, -6),
    'HOU': (29.6847, -95.4107, -6), 'IND': (39.7601, -86.1639, -5),
    'JAX': (30.3239, -81.6373, -5), 'KC': (39.0489, -94.4839, -6),
    'LAC': (33.9535, -118.3392, -8), 'LAR': (33.9535, -118.3392, -8),
    'LV': (36.0909, -115.1833, -8), 'MIA': (25.9580, -80.2389, -5),
    'MIN': (44.9738, -93.2578, -6), 'NE': (42.0909, -71.2643, -5),
    'NO': (29.9511, -90.0812, -6), 'NYG': (40.8135, -74.0745, -5),
    'NYJ': (40.8135, -74.0745, -5), 'PHI': (39.9008, -75.1675, -5),
    'PIT': (40.4468, -80.0158, -5), 'SEA': (47.5952, -122.3316, -8),
    'SF': (37.4030, -121.9700, -8), 'TB': (27.9759, -82.5033, -5),
    'TEN': (36.1665, -86.7713, -6), 'WSH': (38.9077, -76.8645, -5),
}

# Alias de Playdoit/Altenar → abreviatura canónica. Escritos a mano contra el
# volcado real del 2026-08-15 (los 32 equipos aparecieron en el catálogo de
# `sportid=75`). Se incluyen también las variantes de otras casas que ya se
# vieron en Pinnacle, Bovada y Matchbook, que escriben el nombre completo.
_ALIAS = {
    'arz cardinals': 'ARI', 'ari cardinals': 'ARI', 'arizona cardinals': 'ARI',
    'atl falcons': 'ATL', 'atlanta falcons': 'ATL',
    'bal ravens': 'BAL', 'baltimore ravens': 'BAL',
    'buf bills': 'BUF', 'buffalo bills': 'BUF',
    'car panthers': 'CAR', 'carolina panthers': 'CAR',
    'chi bears': 'CHI', 'chicago bears': 'CHI',
    'cin bengals': 'CIN', 'cincinnati bengals': 'CIN',
    'cle browns': 'CLE', 'cleveland browns': 'CLE',
    'dal cowboys': 'DAL', 'dallas cowboys': 'DAL',
    'den broncos': 'DEN', 'denver broncos': 'DEN',
    'det lions': 'DET', 'detroit lions': 'DET',
    'gb packers': 'GB', 'green bay packers': 'GB', 'gnb packers': 'GB',
    'hou texans': 'HOU', 'houston texans': 'HOU',
    'ind colts': 'IND', 'indianapolis colts': 'IND',
    'jax jaguars': 'JAX', 'jacksonville jaguars': 'JAX', 'jac jaguars': 'JAX',
    'kc chiefs': 'KC', 'kansas city chiefs': 'KC', 'kan chiefs': 'KC',
    'la chargers': 'LAC', 'lac chargers': 'LAC', 'los angeles chargers': 'LAC',
    'san diego chargers': 'LAC',
    'la rams': 'LAR', 'lar rams': 'LAR', 'los angeles rams': 'LAR',
    'st louis rams': 'LAR',
    'lv raiders': 'LV', 'las vegas raiders': 'LV', 'oakland raiders': 'LV',
    'lvr raiders': 'LV',
    'mia dolphins': 'MIA', 'miami dolphins': 'MIA',
    'min vikings': 'MIN', 'minnesota vikings': 'MIN',
    'ne patriots': 'NE', 'new england patriots': 'NE', 'nwe patriots': 'NE',
    'no saints': 'NO', 'new orleans saints': 'NO', 'nor saints': 'NO',
    'ny giants': 'NYG', 'nyg giants': 'NYG', 'new york giants': 'NYG',
    'ny jets': 'NYJ', 'nyj jets': 'NYJ', 'new york jets': 'NYJ',
    'phi eagles': 'PHI', 'philadelphia eagles': 'PHI',
    'pit steelers': 'PIT', 'pittsburgh steelers': 'PIT',
    'sea seahawks': 'SEA', 'seattle seahawks': 'SEA',
    'sf 49ers': 'SF', 'san francisco 49ers': 'SF', 'sfo 49ers': 'SF',
    'tb buccaneers': 'TB', 'tampa bay buccaneers': 'TB', 'tam buccaneers': 'TB',
    'ten titans': 'TEN', 'tennessee titans': 'TEN',
    'was commanders': 'WSH', 'wsh commanders': 'WSH',
    'washington commanders': 'WSH', 'washington football team': 'WSH',
    'washington redskins': 'WSH',
}
# El apodo suelto («Chiefs», «49ers») sólo es ambiguo en un caso: no lo es en
# ninguno, porque los 32 apodos son distintos. Se acepta como último recurso.
for _a, _v in EQUIPOS.items():
    _ALIAS.setdefault(_v['apodo'].lower(), _a)
    _ALIAS.setdefault(_v['nombre'].lower(), _a)
    _ALIAS.setdefault(_a.lower(), _a)

SIN_MAPEAR = 'nombres_sin_mapear.json'


def _limpio(t) -> str:
    """Minúsculas, sin tabulaciones ni dobles espacios ni puntuación suelta."""
    s = ' '.join(str(t or '').split()).lower()
    for c in '.,;:()[]*':
        s = s.replace(c, ' ')
    return ' '.join(s.split())


def abreviatura(nombre) -> Optional[str]:
    """
    Nombre de equipo (de la casa que sea) → abreviatura canónica, o `None`.

    Devuelve `None` y NO adivina. Ésta es la disciplina que el encargo pide
    explícitamente y que el proyecto ya aplica en tenis y MLB: un nombre sin
    mapear se descarta y se registra; un nombre mapeado MAL es un error caro.
    """
    s = _limpio(nombre)
    if not s:
        return None
    if s in _ALIAS:
        return _ALIAS[s]
    # NO HAY RELAJACIÓN POR APODO SUELTO, Y ESTO SE MIDIÓ.
    #
    # La primera versión aceptaba «el apodo aparece entre las palabras», con el
    # argumento de que los 32 apodos son únicos ENTRE SÍ. Y lo son — pero no
    # son únicos en el mundo. El propio catálogo de Altenar, en el mismo
    # `sportid=75`, trae la liga europea de fútbol americano:
    #
    #     «Wroclaw Panthers»  →  CAR   (Carolina Panthers)
    #     «London Warriors», «Rhein Fire», «Paris Musketeers»…
    #
    # O sea que un partido de la AFLE habría entrado al índice de la NFL con el
    # equipo equivocado, buscado modelo, cuotas y consenso, y producido un EV
    # inventado sobre dos equipos que no se enfrentan. Es exactamente el fallo
    # que `VENTAJA_IMPOSIBLE` existe para atrapar DESPUÉS, y la disciplina del
    # proyecto es no llegar ahí: un nombre que no está en la tabla se descarta
    # y se registra.
    #
    # Coste de quitarlo: cero. Los 32 apodos sueltos («Chiefs», «49ers») ya
    # están en `_ALIAS` como claves exactas, así que lo único que se pierde es
    # la capacidad de adivinar — que es justo lo que no se quiere.
    registrar_sin_mapear(nombre)
    return None


def registrar_sin_mapear(nombre, contexto: str = 'nfl') -> None:
    """
    Deja constancia en `nombres_sin_mapear.json`, EN EL FORMATO DEL FICHERO.

    El fichero es `{nombre: {'contexto': str, 'visto': 'AAAA-MM-DD'}}` y
    `name_mapper.volcar_fallos` lo purga cada 30 días leyendo `visto`. La
    primera versión de esta función metía un sub-diccionario `{'nfl': {...}}`
    con contadores: no rompía nada, pero al no tener `visto` la purga lo
    tomaba por caducado y **lo borraba en el siguiente vuelco**. O sea, un
    registro que parecía funcionar y desaparecía solo — que es peor que no
    registrar, porque da la falsa impresión de que se está vigilando.
    """
    clave = ' '.join(str(nombre or '').split())
    if not clave:
        return
    try:
        import datetime as _dt
        datos = {}
        if os.path.exists(SIN_MAPEAR):
            with open(SIN_MAPEAR, encoding='utf-8') as f:
                datos = json.load(f) or {}
        if not isinstance(datos, dict):
            datos = {}
        datos.pop('nfl', None)          # limpia el formato erróneo anterior
        datos[clave] = {'contexto': contexto,
                        'visto': _dt.date.today().isoformat()}
        with open(SIN_MAPEAR, 'w', encoding='utf-8') as f:
            json.dump(datos, f, ensure_ascii=False, indent=2, sort_keys=True)
    except Exception as e:
        logger.debug(f'[nfl] no se pudo registrar «{nombre}»: {e}')


def nombre_largo(abrev) -> str:
    """Abreviatura → nombre de ESPN, que es el que ve el usuario."""
    return (EQUIPOS.get(str(abrev or '').upper()) or {}).get('nombre', str(abrev or ''))


# ---------------------------------------------------------------------------
# Descarga
# ---------------------------------------------------------------------------
def _get(url: str, params: Optional[dict] = None, reintentos: int = 3):
    ultimo = None
    for i in range(reintentos):
        try:
            r = requests.get(url, params=params, headers=UA, timeout=TIMEOUT)
            if r.status_code == 200:
                return r.json()
            ultimo = f'HTTP {r.status_code}'
            if r.status_code in (403, 429):
                time.sleep(2 + 3 * i)
                continue
            return None
        except Exception as e:
            ultimo = f'{type(e).__name__}: {e}'
            time.sleep(1 + i)
    logger.debug(f'[nfl] {url} falló: {ultimo}')
    return None


def _num(x):
    try:
        v = float(x)
        return v if v == v else None
    except (TypeError, ValueError):
        return None


def _frac(txt) -> Tuple[Optional[float], Optional[float]]:
    """
    «7-14» → (7, 14). ESPN escribe así 3.º down, 4.º down, zona roja, sacks y
    penalizaciones… salvo `completionAttempts`, que usa barra: «26/41».

    El separador no es cosmético: con sólo `-`, los pases completados y los
    intentados salían a `None` en los 900 partidos y el modelo se quedaba sin
    la tasa de acierto de pase, que es la magnitud que mejor separa a un
    ataque de otro. Se aceptan los dos.
    """
    s = str(txt or '')
    sep = '/' if '/' in s else ('-' if '-' in s else None)
    if not sep:
        return None, None
    a, _, b = s.partition(sep)
    return _num(a), _num(b)


def _segundos(reloj) -> Optional[float]:
    """«33:43» → 2023 segundos de posesión."""
    s = str(reloj or '')
    if ':' not in s:
        return None
    m, _, seg = s.partition(':')
    mm, ss = _num(m), _num(seg)
    return mm * 60 + ss if mm is not None and ss is not None else None


# Las 20 magnitudes que se extraen del boxscore de equipo. Se guardan CRUDAS;
# la normalización (por jugada, por drive) la hace `modelo_nfl`, que es quien
# sabe contra qué se compara. Guardar ya dividido impediría cambiar el
# denominador sin volver a descargar 900 partidos.
def _stats_equipo(bloque: dict) -> Dict[str, Optional[float]]:
    st = {s.get('name'): s.get('displayValue') for s in (bloque.get('statistics') or [])}
    conv3, int3 = _frac(st.get('thirdDownEff'))
    conv4, int4 = _frac(st.get('fourthDownEff'))
    rz_conv, rz_int = _frac(st.get('redZoneAttempts'))
    sacks, yds_sack = _frac(st.get('sacksYardsLost'))
    pen, yds_pen = _frac(st.get('totalPenaltiesYards'))
    comp, att = _frac(st.get('completionAttempts'))
    return {
        'primeros_downs': _num(st.get('firstDowns')),
        'jugadas': _num(st.get('totalOffensivePlays')),
        'yardas': _num(st.get('totalYards')),
        'yardas_jugada': _num(st.get('yardsPerPlay')),
        'drives': _num(st.get('totalDrives')),
        'yardas_pase': _num(st.get('netPassingYards')),
        'yardas_carrera': _num(st.get('rushingYards')),
        'acarreos': _num(st.get('rushingAttempts')),
        'yardas_acarreo': _num(st.get('yardsPerRushAttempt')),
        'yardas_pase_int': _num(st.get('yardsPerPass')),
        'pases_comp': comp, 'pases_int': att,
        'conv3': conv3, 'int3': int3,
        'conv4': conv4, 'int4': int4,
        'rz_conv': rz_conv, 'rz_int': rz_int,
        'sacks_sufridos': sacks,
        'penalizaciones': pen, 'yardas_penal': yds_pen,
        'perdidas': _num(st.get('turnovers')),
        'balones_sueltos': _num(st.get('fumblesLost')),
        'intercepciones': _num(st.get('interceptions')),
        'posesion_s': _segundos(st.get('possessionTime')),
    }


def resumen_partido(event_id: str) -> Optional[dict]:
    """Marcador, contexto y las 25 estadísticas de equipo de ambos bandos."""
    j = _get(f'{SITE}/summary', {'event': event_id})
    if not isinstance(j, dict):
        return None
    cab = j.get('header') or {}
    comps = (cab.get('competitions') or [{}])[0]
    equipos = comps.get('competitors') or []
    if len(equipos) != 2:
        return None
    por_lado = {}
    for c in equipos:
        lado = c.get('homeAway')
        eq = c.get('team') or {}
        por_lado[lado] = {'abrev': abreviatura(eq.get('displayName')
                                               or eq.get('abbreviation')),
                          'puntos': _num(c.get('score'))}
    if 'home' not in por_lado or 'away' not in por_lado:
        return None
    if not por_lado['home']['abrev'] or not por_lado['away']['abrev']:
        return None

    # boxscore: el orden de `teams` no está garantizado, se casa por id
    caja = {}
    for t in ((j.get('boxscore') or {}).get('teams') or []):
        ab = abreviatura((t.get('team') or {}).get('displayName')
                         or (t.get('team') or {}).get('abbreviation'))
        if ab:
            caja[ab] = _stats_equipo(t)

    temporada = cab.get('season') or {}
    fila = {
        'event_id': str(event_id),
        'fecha': str(comps.get('date') or cab.get('date') or '')[:10],
        'inicio': str(comps.get('date') or ''),
        'temporada': int(temporada.get('year') or 0) or None,
        'tipo': TIPO_TEMPORADA.get(int(temporada.get('type') or 0), 'otro'),
        'semana': (cab.get('week') if isinstance(cab.get('week'), int)
                   else (cab.get('week') or {}).get('number')),
        'neutral': bool(comps.get('neutralSite')),
        'home': por_lado['home']['abrev'], 'away': por_lado['away']['abrev'],
        'pts_home': por_lado['home']['puntos'], 'pts_away': por_lado['away']['puntos'],
    }
    for lado in ('home', 'away'):
        for k, v in (caja.get(fila[lado]) or {}).items():
            fila[f'{lado}_{k}'] = v
    return fila


# Casas cuyo `close` se acepta como precio de cierre. Se prefieren en este
# orden y se toma LA PRIMERA que publique cierre completo, no la media: un
# backtest tiene que decir a qué precio concreto se habría apostado.
_PROVEEDORES = ('ESPN BET', 'DraftKings', 'Caesars Sportsbook (Colorado)',
                'Caesars Sportsbook', 'William Hill (New Jersey)',
                'Westgate', 'Bet 365', 'unibet', 'SugarHouse')


def _rama(od: dict, campo: str, fase: str = 'close'):
    """`homeTeamOdds.close.moneyLine.decimal` sin reventar si falta un eslabón."""
    r = (od or {}).get(fase)
    if not isinstance(r, dict):
        return None
    v = r.get(campo)
    if isinstance(v, dict):
        return _num(v.get('decimal')) or _num(v.get('value'))
    return _num(v)


def _pointspread(od: dict, fase: str = 'close') -> Optional[float]:
    r = ((od or {}).get(fase) or {}).get('pointSpread')
    if not isinstance(r, dict):
        return None
    v = _num(r.get('value'))
    if v is not None:
        return v
    # cuando `value` falta, ESPN deja el americano en texto: «-3», «+3»
    return _num(str(r.get('american') or r.get('alternateDisplayValue') or '')
                .replace('+', ''))


def cuotas_partido(event_id: str) -> Dict[str, Optional[float]]:
    """
    Cuotas de CIERRE de un partido: moneyline, hándicap con su línea y total.

    Devuelve decimales, que es la unidad de todo el proyecto. Vacío si ninguna
    casa publicó cierre — resultado legítimo y frecuente en pretemporada.
    """
    j = _get(f'{CORE}/events/{event_id}/competitions/{event_id}/odds')
    items = (j or {}).get('items') or []
    por_casa = {}
    for it in items:
        nom = ((it.get('provider') or {}).get('name') or '').strip()
        por_casa.setdefault(nom, it)
    salida: Dict[str, Optional[float]] = {}
    for nom in _PROVEEDORES:
        it = por_casa.get(nom)
        if not it:
            continue
        h, a = it.get('homeTeamOdds') or {}, it.get('awayTeamOdds') or {}
        ml_h, ml_a = _rama(h, 'moneyLine'), _rama(a, 'moneyLine')
        if not (ml_h and ml_a):
            continue
        salida = {
            'casa_cierre': nom,
            'ml_home': ml_h, 'ml_away': ml_a,
            'hcp_home': _pointspread(h), 'hcp_away': _pointspread(a),
            'hcp_cuota_home': _rama(h, 'spread'), 'hcp_cuota_away': _rama(a, 'spread'),
            'total': _num(it.get('overUnder')),
            'total_over': _num((it.get('overOdds') or {}).get('decimal')
                               if isinstance(it.get('overOdds'), dict)
                               else None),
            'total_under': _num((it.get('underOdds') or {}).get('decimal')
                                if isinstance(it.get('underOdds'), dict)
                                else None),
        }
        break
    # el total suele venir como número suelto en la raíz aunque no haya cierre
    if not salida and items:
        it = items[0]
        salida = {'casa_cierre': ((it.get('provider') or {}).get('name') or ''),
                  'total': _num(it.get('overUnder')),
                  'hcp_home': _num(it.get('spread'))}
    return salida


def eventos_de_anio(anio: int) -> List[Dict]:
    """
    Todos los partidos de un AÑO NATURAL desde el scoreboard, en una petición.

    Se usa el año natural y no la temporada porque el scoreboard lo acepta
    directamente (`dates=2024` devolvió 335 eventos: playoffs de 2023,
    pretemporada y liga regular de 2024). Cada evento trae ya su temporada real
    dentro, así que agrupar por temporada es trivial después y no se pierde
    ninguna frontera.
    """
    j = _get(f'{SITE}/scoreboard', {'dates': str(anio), 'limit': 1000})
    evs = (j or {}).get('events') or []
    out = []
    for ev in evs:
        try:
            comp = (ev.get('competitions') or [{}])[0]
            estado = ((comp.get('status') or ev.get('status') or {})
                      .get('type') or {})
            out.append({'event_id': str(ev.get('id')),
                        'fecha': str(ev.get('date') or '')[:10],
                        'completado': bool(estado.get('completed')),
                        'nombre': ev.get('name')})
        except Exception:
            continue
    return out


def construir_historico(anios: List[int], salida: str = HISTORICO,
                        con_cuotas: bool = True,
                        incremental: bool = True) -> pd.DataFrame:
    """
    Descarga y guarda un CSV con una fila por partido: contexto, marcador, las
    estadísticas de equipo de ambos bandos y las cuotas de cierre.

    `incremental` conserva lo ya descargado y sólo pide lo que falta, que es lo
    que permite refrescarlo cada semana sin volver a bajar tres temporadas.
    """
    previos = pd.DataFrame()
    ya = set()
    if incremental and os.path.exists(salida):
        try:
            previos = pd.read_csv(salida, dtype={'event_id': str})
            ya = set(previos['event_id'].astype(str))
            logger.info(f'[nfl] histórico previo: {len(previos)} partidos')
        except Exception as e:
            logger.warning(f'[nfl] no se pudo leer {salida}: {e}')

    pendientes = []
    for a in anios:
        evs = eventos_de_anio(a)
        n_nuevos = 0
        for e in evs:
            if not e['completado'] or e['event_id'] in ya:
                continue
            pendientes.append(e['event_id'])
            n_nuevos += 1
        logger.info(f'[nfl] {a}: {len(evs)} eventos, {n_nuevos} por descargar')

    filas = []
    t0 = time.time()
    for i, eid in enumerate(pendientes, 1):
        fila = resumen_partido(eid)
        if not fila:
            continue
        if con_cuotas:
            fila.update(cuotas_partido(eid))
        filas.append(fila)
        if i % 25 == 0 or i == len(pendientes):
            logger.info(f'[nfl] {i}/{len(pendientes)} '
                        f'({(time.time()-t0)/max(i,1):.2f} s/partido)')

    nuevo = pd.DataFrame(filas)
    d = pd.concat([previos, nuevo], ignore_index=True) if len(previos) else nuevo
    if not len(d):
        logger.warning('[nfl] no se descargó ningún partido')
        return d
    d = d.drop_duplicates(subset=['event_id'], keep='last')
    d = d.sort_values(['fecha', 'event_id']).reset_index(drop=True)
    d.to_csv(salida, index=False)
    logger.info(f'[nfl] guardado {salida}: {len(d)} partidos '
                f'({d["fecha"].min()} → {d["fecha"].max()})')
    return d


def cargar_historico(ruta: str = HISTORICO) -> pd.DataFrame:
    if not os.path.exists(ruta):
        return pd.DataFrame()
    d = pd.read_csv(ruta, dtype={'event_id': str})
    d['fecha'] = pd.to_datetime(d['fecha'], errors='coerce')
    return d.dropna(subset=['fecha']).sort_values('fecha').reset_index(drop=True)


# ---------------------------------------------------------------------------
# Calendario del día (producción)
# ---------------------------------------------------------------------------
_CACHE: Dict[str, tuple] = {}
_TTL = 1800


def fixtures_nfl(dias: int = 3) -> List[Dict]:
    """
    Próximos partidos con la forma que espera el barrido
    (`{'fecha','inicio','home','away','event_id'}`), con los nombres LARGOS de
    ESPN.

    Degrada al catálogo de Playdoit si ESPN no responde — es el mismo respaldo
    que la v98 puso en la MLB cuando ESPN empezó a devolver 403 desde Streamlit
    Cloud. Aquí importa más que en la MLB: sin calendario no hay pestaña.
    """
    ck = f'nfl:{dias}'
    ahora = time.time()
    if ck in _CACHE and ahora - _CACHE[ck][0] < _TTL:
        return _CACHE[ck][1]

    hoy = pd.Timestamp.now('UTC').tz_localize(None).normalize()
    ini = hoy.strftime('%Y%m%d')
    fin = (hoy + pd.Timedelta(days=dias)).strftime('%Y%m%d')
    salida: List[Dict] = []
    j = _get(f'{SITE}/scoreboard', {'dates': f'{ini}-{fin}', 'limit': 300})
    for ev in ((j or {}).get('events') or []):
        try:
            comp = (ev.get('competitions') or [{}])[0]
            estado = ((comp.get('status') or ev.get('status') or {})
                      .get('type') or {})
            if estado.get('completed'):
                continue
            loc = next(c for c in comp['competitors'] if c['homeAway'] == 'home')
            vis = next(c for c in comp['competitors'] if c['homeAway'] == 'away')
            f = pd.to_datetime(ev['date'])
            if f.tzinfo:
                f = f.tz_convert(None)
            ah = abreviatura(loc['team']['displayName'])
            aa = abreviatura(vis['team']['displayName'])
            if not ah or not aa:
                continue
            temporada = ev.get('season') or {}
            salida.append({
                'fecha': f.strftime('%Y-%m-%d'),
                'inicio': f.strftime('%Y-%m-%d %H:%M:%S'),
                'home': nombre_largo(ah), 'away': nombre_largo(aa),
                'abrev_home': ah, 'abrev_away': aa,
                'event_id': str(ev.get('id')),
                'tipo': TIPO_TEMPORADA.get(int(temporada.get('type') or 2), 'regular'),
                'neutral': bool(comp.get('neutralSite')),
            })
        except Exception:
            continue

    if not salida:
        salida = _fixtures_desde_playdoit(dias)
        if salida:
            logger.info(f'[nfl] ESPN sin datos; {len(salida)} partidos desde '
                        f'el catálogo de Playdoit')
    logger.info(f'[nfl] {len(salida)} próximos partidos ({dias} días)')
    _CACHE[ck] = (ahora, salida)
    return salida


def _fixtures_desde_playdoit(dias: int) -> List[Dict]:
    """Respaldo: el propio catálogo de la casa ya trae el calendario."""
    try:
        import cuotas_multi as cm
        idx = cm._indice_pdt('nfl') or {}
    except Exception as e:
        logger.debug(f'[nfl] respaldo Playdoit no disponible: {e}')
        return []
    tope = pd.Timestamp.now('UTC').tz_localize(None) + pd.Timedelta(days=dias)
    out = []
    for v in idx.values():
        ah, aa = abreviatura(v.get('home')), abreviatura(v.get('away'))
        if not ah or not aa:
            continue
        try:
            f = pd.to_datetime(v.get('fecha'))
            if f.tzinfo:
                f = f.tz_convert(None)
        except Exception:
            continue
        if f > tope:
            continue
        out.append({'fecha': f.strftime('%Y-%m-%d'),
                    'inicio': f.strftime('%Y-%m-%d %H:%M:%S'),
                    'home': nombre_largo(ah), 'away': nombre_largo(aa),
                    'abrev_home': ah, 'abrev_away': aa,
                    'event_id': None, 'tipo': 'regular', 'neutral': False})
    return out


# ---------------------------------------------------------------------------
# Forma reciente, con la forma que espera `h2h_visual`
# ---------------------------------------------------------------------------
def forma_reciente(historico: pd.DataFrame, abrev: str, n: int = 5,
                   incluir_pretemporada: bool = False) -> Dict:
    """
    Los últimos `n` partidos de un equipo, del más nuevo al más viejo.

    Devuelve el mismo diccionario que `panel_equipos.forma_global` para el
    fútbol, porque `h2h_visual.tarjeta_equipo` ya sabe pintarlo. Reutilizar el
    contrato en vez de inventar otro es lo que hace que la tarjeta de NFL salga
    con la misma racha, el mismo desglose y el mismo tema oscuro sin escribir
    una segunda tarjeta que se irá desincronizando de la primera.

    Las estadísticas por partido van bajo las claves que declara
    `h2h_visual.PERFILES['nfl']` — yardas, yardas por jugada y pérdidas.
    """
    vacio = {'n': 0, 'partidos': []}
    if historico is None or not len(historico):
        return vacio
    d = historico
    if not incluir_pretemporada and 'tipo' in d.columns:
        d = d[d['tipo'].isin(('regular', 'playoffs'))]
    d = d[(d['home'] == abrev) | (d['away'] == abrev)]
    if not len(d):
        return vacio
    d = d.sort_values('fecha', ascending=False).head(max(n, 8))
    partidos, pts_f, pts_c, puntos = [], [], [], 0
    for r in d.to_dict('records'):
        casa = r['home'] == abrev
        lado, rival_lado = ('home', 'away') if casa else ('away', 'home')
        pf, pc = r.get(f'pts_{lado}'), r.get(f'pts_{rival_lado}')
        if pf is None or pc is None or pf != pf or pc != pc:
            continue
        pf, pc = float(pf), float(pc)
        res = 'G' if pf > pc else 'P' if pf < pc else 'E'
        puntos += 3 if res == 'G' else 1 if res == 'E' else 0
        pts_f.append(pf)
        pts_c.append(pc)
        stats = {}
        for clave, col in (('Yardas', 'yardas'),
                           ('Yardas por jugada', 'yardas_jugada'),
                           ('Pérdidas', 'perdidas')):
            v = r.get(f'{lado}_{col}')
            if v is not None and v == v:
                stats[clave] = {'propio': float(v),
                                'rival': r.get(f'{rival_lado}_{col}')}
        partidos.append({
            'resultado': res, 'goles': int(pf), 'encajados': int(pc),
            'rival': nombre_largo(r[rival_lado]), 'casa': casa,
            'fecha': str(r['fecha'])[:10],
            'temporada': r.get('temporada'), 'tipo': r.get('tipo'),
            'stats': stats})
    if not partidos:
        return vacio
    return {
        'n': len(partidos), 'partidos': partidos,
        'gf_media': round(sum(pts_f) / len(pts_f), 2),
        'gc_media': round(sum(pts_c) / len(pts_c), 2),
        'pts_por_partido': round(puntos / len(partidos), 2),
        'ganados': sum(1 for p in partidos if p['resultado'] == 'G'),
        'empatados': sum(1 for p in partidos if p['resultado'] == 'E'),
        'perdidos': sum(1 for p in partidos if p['resultado'] == 'P'),
    }


def h2h(historico: pd.DataFrame, a: str, b: str, n: int = 6) -> List[Dict]:
    """Los últimos enfrentamientos directos entre dos equipos."""
    if historico is None or not len(historico):
        return []
    d = historico[((historico['home'] == a) & (historico['away'] == b))
                  | ((historico['home'] == b) & (historico['away'] == a))]
    d = d.sort_values('fecha', ascending=False).head(n)
    out = []
    for r in d.to_dict('records'):
        if r.get('pts_home') is None or r['pts_home'] != r['pts_home']:
            continue
        out.append({'fecha': str(r['fecha'])[:10],
                    'temporada': r.get('temporada'), 'tipo': r.get('tipo'),
                    'home': nombre_largo(r['home']),
                    'away': nombre_largo(r['away']),
                    'pts_home': int(r['pts_home']),
                    'pts_away': int(r['pts_away'])})
    return out


if __name__ == '__main__':
    import argparse
    logging.basicConfig(level=logging.INFO,
                        format='%(asctime)s %(levelname)s %(message)s')
    ap = argparse.ArgumentParser()
    ap.add_argument('--anios', default='2023,2024,2025,2026')
    ap.add_argument('--sin-cuotas', action='store_true')
    ap.add_argument('--desde-cero', action='store_true')
    a = ap.parse_args()
    d = construir_historico([int(x) for x in a.anios.split(',')],
                            con_cuotas=not a.sin_cuotas,
                            incremental=not a.desde_cero)
    if len(d):
        print(f'\n{len(d)} partidos · {d["fecha"].min()} → {d["fecha"].max()}')
        print(d.groupby(['temporada', 'tipo']).size().to_string())
        for c in ('ml_home', 'total', 'home_yardas'):
            if c in d.columns:
                print(f'cobertura {c}: {d[c].notna().mean()*100:.1f} %')
