#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v67 — Capa de datos MULTIFUENTE de tenis.

Hasta v66 el motor de tenis leía una sola fuente (mirror de Kaggle) que solo
cubre el circuito PRINCIPAL de ATP y WTA. Este módulo une tres fuentes y expone
un histórico con esquema único, además de la CATEGORÍA de cada partido para que
la UI pueda filtrar por competición.

Fuentes (todas gratuitas y sin credenciales):

  1. Kaggle `dissfya/*` (COLUMNA VERTEBRAL, la de siempre)
     ATP 68k partidos desde 2000 · WTA 45k desde 2007 · fresco a ayer.
     Trae ranking, puntos y cuotas de una casa (Odd_1/Odd_2) con cobertura 100 %.
     HALLAZGO v67: el ATP ya traía la columna `Series` (nivel del torneo) y el
     motor nunca la usó. La WTA no la trae — la aporta la fuente 2.

  2. tennis-data.co.uk (ENRIQUECIMIENTO; es el origen real del mirror anterior)
     Añade sobre los MISMOS partidos, enlazados por fecha + jugadores (100 % de
     acierto medido en 2026):
       · `Tier` de la WTA (WTA250/500/1000/Grand Slam) — el nivel que faltaba.
       · `Comment` = Completed / Retired / Walkover. Kaggle NO marca los retiros
         (0 casos detectables en `Score`), así que hasta ahora ~3 % de partidos
         decididos por abandono entraban al entrenamiento como si fueran
         victorias deportivas.
       · Cuotas de MÁS casas (Pinnacle, máxima y media del mercado).
     Descarga .xlsx (el sitio dejó de publicar .zip; verificado 2026-07).

  3. ESPN (COBERTURA DE CATEGORÍAS INFERIORES)
     Las ligas de tenis de ESPN son solo `atp` y `wta`, pero su scoreboard
     incluye torneos que NO están en el circuito principal: WTA 125, ITF
     femeninos y Challengers ATP publicados con su nombre comercial. Da
     resultados y marcador por set, con rango de fechas. NO da estadísticas de
     saque (verificado: `statistics` devuelve 404 en la core API).

Lo que NO existe (auditado en v67, ver VALIDACION_v67.md):
  · Los repos `JeffSackmann/tennis_atp` y `tennis_wta` — la fuente estándar con
    aces/dobles faltas/puntos de saque — **ya no existen** (la cuenta solo
    conserva `tennis_MatchChartingProject`). Por eso el ELO de saque/resto sigue
    sin poder calcularse.
  · El dataset de Challengers de Kaggle sigue devolviendo 403 (como en v35).
  · La API de UTR responde sin credenciales, pero solo expone eventos
    amateur/locales, no la UTR Pro Match Series.
"""

import io
import json
import logging
import os
import re
import time
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
import requests

logger = logging.getLogger(__name__)

CACHE_DIR = 'tenis_cache'
TTL_ESPN = 6 * 3600            # el histórico de ESPN cambia poco intradía
UA = {'User-Agent': 'Mozilla/5.0'}
TIMEOUT = 45

TENNIS_DATA_BASE = 'http://www.tennis-data.co.uk'
ESPN_SCOREBOARD = 'https://site.api.espn.com/apis/site/v2/sports/tennis/{liga}/scoreboard'

# Esquema común (superconjunto del que ya consume TennisEngine._dataset)
COLUMNAS = ['Tournament', 'Date', 'Series', 'Court', 'Surface', 'Round',
            'Best of', 'Player_1', 'Player_2', 'Winner', 'Rank_1', 'Rank_2',
            'Pts_1', 'Pts_2', 'Odd_1', 'Odd_2', 'Score',
            'Comment', 'Categoria', 'Fuente']

# ---------------------------------------------------------------------------
# Categorías que pide la UI (las del menú del usuario)
# ---------------------------------------------------------------------------
GRAND_SLAMS = {
    'wimbledon': 'Wimbledon',
    'australian open': 'Open de Australia',
    'french open': 'Roland Garros',
    'roland garros': 'Roland Garros',
    'us open': 'US Open',
}

CATEGORIAS = {
    'gs_wimbledon_m':  'Wimbledon Individual Masculino',
    'gs_wimbledon_f':  'Wimbledon Individual Femenino',
    'gs_australia_m':  'Open de Australia Individual Masculino',
    'gs_australia_f':  'Open de Australia Individual Femenino',
    'gs_roland_m':     'Roland Garros Individual Masculino',
    'gs_roland_f':     'Roland Garros Individual Femenino',
    'gs_usopen_m':     'US Open Individual Masculino',
    'gs_usopen_f':     'US Open Individual Femenino',
    'atp_tour':        'ATP Torneos y Masters',
    'wta_tour':        'WTA Torneos y Premier',
    'wta_125':         'WTA 125 / Challenge Femenino',
    'challenger_atp':  'Challenger Masculino ATP',
    'itf_m':           'ITF M-World',
    'itf_w':           'ITF W-World',
}

# Agrupación del menú (etiqueta de grupo -> claves de categoría)
GRUPOS_UI = [
    ('Wimbledon',          ['gs_wimbledon_m', 'gs_wimbledon_f']),
    ('Open de Australia',  ['gs_australia_m', 'gs_australia_f']),
    ('Roland Garros',      ['gs_roland_m', 'gs_roland_f']),
    ('US Open',            ['gs_usopen_m', 'gs_usopen_f']),
    ('ATP',                ['atp_tour']),
    ('WTA',                ['wta_tour']),
    ('Challenge Femenino', ['wta_125']),
    ('Challenger',         ['challenger_atp']),
    ('ITF Masculino',      ['itf_m']),
    ('ITF Femenino',       ['itf_w']),
]

_SUFIJO_GS = {'atp': 'm', 'wta': 'f'}

# Rankings de referencia para deducir la categoría cuando el nombre del torneo
# no la delata. Un cuadro de ATP Tour vive por debajo del 120; un Challenger,
# entre 120 y 350; por debajo de ahí es circuito ITF.
UMBRAL_RANK_CHALLENGER = 120.0
UMBRAL_RANK_ITF = 350.0


def _slug_gs(torneo: str) -> Optional[str]:
    t = str(torneo).strip().lower()
    for clave, _ in GRAND_SLAMS.items():
        if clave in t:
            return {'wimbledon': 'wimbledon', 'australian open': 'australia',
                    'french open': 'roland', 'roland garros': 'roland',
                    'us open': 'usopen'}[clave]
    return None


def es_principal(torneo: str, catalogo: List[str], circuito: str = '') -> bool:
    """
    ¿Este torneo pertenece al circuito principal? Se resuelve contra el catálogo
    real de torneos de Kaggle con el `name_mapper` del proyecto (tolera
    patrocinadores: "Rolex Shanghai Masters" -> "Shanghai Masters").

    Es lo que distingue un Challenger de verdad ("Open Occitanie", sin
    equivalente) de la fase previa de un Masters ("Miami Open presented by
    Itau"), que ESPN publica igual pero NO es categoría inferior.
    """
    if not catalogo:
        return False
    # OJO: la clave lleva el CIRCUITO. Sin él, procesar ATP y luego WTA en el
    # mismo proceso reutilizaba el veredicto del circuito masculino para el
    # femenino y mandaba los torneos ITF/125 al cajón de "WTA Tour"
    # (defecto cazado al reentrenar en v67).
    clave = f'{circuito}|{str(torneo).strip().lower()}'
    if clave in _CACHE_PRINCIPAL:
        return _CACHE_PRINCIPAL[clave]
    if _slug_gs(torneo):
        _CACHE_PRINCIPAL[clave] = True
        return True
    try:
        import name_mapper
        ok = name_mapper.mapear(torneo, catalogo,
                                contexto=f'tenis/{circuito}') is not None
    except Exception:
        ok = str(torneo).strip().lower() in {c.strip().lower() for c in catalogo}
    _CACHE_PRINCIPAL[clave] = ok
    return ok


_CACHE_PRINCIPAL: Dict[str, bool] = {}


def categoria_de(circuito: str, torneo: str, series: Optional[str],
                 fuente: str = 'kaggle',
                 catalogo: Optional[List[str]] = None,
                 major: bool = False,
                 rank_medio: Optional[float] = None,
                 por_descarte: str = 'inferior') -> str:
    """
    Clasifica un partido en una de `CATEGORIAS`.

    Reglas, de la más fiable a la más heurística:
      1. Nombre de Grand Slam  -> categoría de GS del circuito.
      2. `Series`/`Tier` de tennis-data ('ATP250', 'WTA1000', ...) -> tour.
      3. Nombre con '125' / 'challenger' / 'itf' / patrón ITF (W15, M25...).
      4. Sin nivel conocido: si viene de ESPN y NO está en el circuito
         principal, es categoría inferior — Challenger en el feed ATP, ITF
         femenino en el feed WTA. Se documenta como heurística, no como dato.
    """
    gs = _slug_gs(torneo)
    if gs:
        return f'gs_{gs}_{_SUFIJO_GS.get(circuito, "m")}'
    t = str(torneo).lower()
    s = str(series or '').lower().strip()
    if '125' in t or s == 'wta125':
        return 'wta_125'
    if 'challenger' in t or s.startswith('challenger'):
        return 'challenger_atp'
    if 'itf' in t or re.search(r'\b[mw]\s?\d{2,3}\b', t):
        return 'itf_m' if circuito == 'atp' else 'itf_w'
    # OJO: 'International' es un nivel que usan LOS DOS circuitos (ATP
    # International hasta 2008, WTA International hasta 2020). Por eso el
    # circuito manda sobre el nombre del nivel — clasificar solo por `Series`
    # metía 5.232 partidos de la WTA en la categoría ATP (bug cazado en v67).
    if s and s not in ('nan', 'none'):
        return 'atp_tour' if circuito == 'atp' else 'wta_tour'
    if fuente == 'espn':
        # ESPN no publica el nivel. Se reconoce el torneo contra el catálogo de
        # Kaggle (o `major`). OJO: eso funciona con el histórico pero NO con el
        # calendario en curso, porque el patrocinador cambia el nombre cada año
        # ("Mubadala DC Open" es el "Citi Open"). Por eso, cuando no se
        # reconoce, el desempate lo pone el RANKING de los jugadores (que es lo
        # que de verdad define la categoría) y, a falta de ranking, se asume
        # circuito principal: es peor degradar un ATP 500 a "Challenger" que al
        # revés.
        if major or es_principal(torneo, catalogo or [], circuito):
            return 'atp_tour' if circuito == 'atp' else 'wta_tour'
        if rank_medio is not None:
            if rank_medio > UMBRAL_RANK_ITF:
                return 'itf_m' if circuito == 'atp' else 'itf_w'
            if rank_medio > UMBRAL_RANK_CHALLENGER:
                return 'challenger_atp' if circuito == 'atp' else 'wta_125'
            return 'atp_tour' if circuito == 'atp' else 'wta_tour'
        # Sin ranking y sin torneo reconocido, `por_descarte` decide:
        #   'inferior'  (HISTÓRICO): si Kaggle no lo tiene, no es circuito
        #               principal — es la inferencia correcta sobre datos ya
        #               ocurridos y es la que puebla las categorías bajas.
        #   'principal' (FIXTURES): el calendario en curso renombra torneos por
        #               patrocinador cada temporada, así que no reconocerlo NO
        #               prueba nada; degradar un ATP 500 a "Challenger" en la UI
        #               es peor error que lo contrario.
        if por_descarte == 'principal':
            return 'atp_tour' if circuito == 'atp' else 'wta_tour'
        return 'challenger_atp' if circuito == 'atp' else 'itf_w'
    return 'atp_tour' if circuito == 'atp' else 'wta_tour'


# ---------------------------------------------------------------------------
# 1. Kaggle (columna vertebral)
# ---------------------------------------------------------------------------
KAGGLE = {
    'atp': ('dissfya/atp-tennis-2000-2023daily-pull', 'atp_tennis.csv'),
    'wta': ('dissfya/wta-tennis-2007-2023-daily-update', 'wta.csv'),
}


def cargar_kaggle(circuito: str) -> pd.DataFrame:
    import kagglehub
    ds, archivo = KAGGLE[circuito]
    p = kagglehub.dataset_download(ds)
    df = pd.read_csv(os.path.join(p, archivo), parse_dates=['Date'], low_memory=False)
    if 'Series' not in df.columns:
        df['Series'] = np.nan          # la WTA no la trae; la aporta tennis-data
    df['Comment'] = np.nan
    df['Fuente'] = 'kaggle'
    logger.info(f"[tenis/{circuito}] Kaggle: {len(df)} partidos "
                f"(hasta {df['Date'].max().date()}).")
    return df


# ---------------------------------------------------------------------------
# 2. tennis-data.co.uk (enriquecimiento)
# ---------------------------------------------------------------------------
_RE_ABREVIADO = re.compile(r'^(.+?)\s+([A-Za-zÀ-ÿ])\.?$')
_PARTICULAS = {'de', 'del', 'van', 'von', 'der', 'den', 'di', 'da', 'dos',
               'la', 'le', 'el', 'al', 'bin', 'ben', 'mc', 'st'}


def canonico(nombre: str) -> str:
    """
    Lleva cualquier grafía al formato del circuito principal: `Apellido I.`.

    Es la pieza que hace compatibles las tres fuentes. Kaggle y
    tennis-data escriben `Alcaraz C.`; ESPN escribe `Carlos Alcaraz`. Sin esta
    normalización, ESPN duplicaba los partidos del circuito principal Y partía
    el historial de cada jugador en dos personas distintas — que es justo lo
    que arruinaría el ELO (defecto cazado y corregido en v67).

    Convención: el PRIMER token es el nombre de pila y el resto el apellido,
    respetando partículas ("Luca Van Assche" -> "Van Assche L.").
    """
    n = ' '.join(str(nombre).replace('\xa0', ' ').split())
    if not n:
        return ''
    m = _RE_ABREVIADO.match(n)
    if m:                                   # ya viene abreviado
        return f'{m.group(1).strip()} {m.group(2).upper()}.'
    partes = n.split()
    if len(partes) == 1:
        return partes[0]
    pila, apellido = partes[0], ' '.join(partes[1:])
    # "Alex de Minaur": la partícula pertenece al apellido, no al nombre
    while len(partes) > 2 and partes[0].lower() in _PARTICULAS:
        partes = partes[1:]
        pila, apellido = partes[0], ' '.join(partes[1:])
    return f'{apellido} {pila[0].upper()}.'


def clave_jugador(nombre: str) -> str:
    """Clave de comparación insensible a tildes, mayúsculas y guiones."""
    import unicodedata
    c = canonico(nombre)
    c = unicodedata.normalize('NFKD', c)
    c = ''.join(ch for ch in c if not unicodedata.combining(ch)).lower()
    return re.sub(r'[^a-z0-9]', '', c)


def _clave_partido(fechas: pd.Series, a: pd.Series, b: pd.Series) -> pd.Series:
    """Clave simétrica fecha + pareja normalizada, para enlazar sin depender de
    quién ganó ni de cómo escriba los nombres cada fuente."""
    pares = ['|'.join(sorted((clave_jugador(x), clave_jugador(y))))
             for x, y in zip(a, b)]
    return pd.Series(fechas.dt.strftime('%Y%m%d'), index=fechas.index) + '|' + \
        pd.Series(pares, index=fechas.index)


def cargar_tennis_data(circuito: str, desde_anio: int = 2015) -> pd.DataFrame:
    """Descarga los .xlsx anuales. Devuelve vacío si la fuente no responde."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    sufijo = '' if circuito == 'atp' else 'w'
    anio_actual = pd.Timestamp.today().year
    marcos = []
    for anio in range(desde_anio, anio_actual + 1):
        destino = os.path.join(CACHE_DIR, f'td_{circuito}_{anio}.parquet')
        # El año en curso se refresca a diario; los cerrados se cachean para siempre
        vigente = (os.path.exists(destino) and
                   (anio < anio_actual or
                    time.time() - os.path.getmtime(destino) < 12 * 3600))
        if vigente:
            try:
                marcos.append(pd.read_parquet(destino))
                continue
            except Exception:
                pass
        url = f'{TENNIS_DATA_BASE}/{anio}{sufijo}/{anio}.xlsx'
        try:
            r = requests.get(url, headers=UA, timeout=TIMEOUT)
            r.raise_for_status()
            df = pd.read_excel(io.BytesIO(r.content))
        except Exception as e:
            logger.warning(f"[tenis/{circuito}] tennis-data {anio}: {type(e).__name__}: {e}")
            continue
        df['Date'] = pd.to_datetime(df['Date'], errors='coerce')
        # La fuente tiene erratas de fecha puntuales (vi un 2029 en 2026w)
        df = df[df['Date'].dt.year.between(desde_anio - 1, anio_actual)]
        nivel = 'Series' if 'Series' in df.columns else ('Tier' if 'Tier' in df.columns else None)
        salida = pd.DataFrame({
            'Date': df['Date'],
            'Tournament': df.get('Tournament'),
            'Nivel': df[nivel] if nivel else np.nan,
            'Comment': df.get('Comment'),
            'Winner': df.get('Winner'),
            'Loser': df.get('Loser'),
        })
        for col_o, col_d in (('PSW', 'Odd_PS_W'), ('PSL', 'Odd_PS_L'),
                             ('MaxW', 'Odd_Max_W'), ('MaxL', 'Odd_Max_L'),
                             ('AvgW', 'Odd_Avg_W'), ('AvgL', 'Odd_Avg_L')):
            salida[col_d] = pd.to_numeric(df.get(col_o), errors='coerce')
        salida = salida.dropna(subset=['Date', 'Winner', 'Loser'])
        try:
            salida.to_parquet(destino, index=False)
        except Exception:
            pass
        marcos.append(salida)
    if not marcos:
        return pd.DataFrame()
    out = pd.concat(marcos, ignore_index=True)
    logger.info(f"[tenis/{circuito}] tennis-data: {len(out)} partidos "
                f"{desde_anio}-{anio_actual}.")
    return out


def enriquecer(base: pd.DataFrame, extra: pd.DataFrame) -> pd.DataFrame:
    """
    Vuelca `Nivel`, `Comment` y las cuotas multi-casa sobre las filas de Kaggle,
    enlazando por fecha + pareja de jugadores. Las cuotas se reorientan a
    Player_1/Player_2 (la fuente las publica como ganador/perdedor).
    """
    if extra.empty or base.empty:
        base['Retirado'] = False
        return base
    base = base.copy()
    base['_k'] = _clave_partido(base['Date'], base['Player_1'], base['Player_2'])
    extra = extra.copy()
    extra['_k'] = _clave_partido(extra['Date'], extra['Winner'], extra['Loser'])
    extra = extra.drop_duplicates('_k', keep='last')
    cols = ['_k', 'Nivel', 'Comment', 'Winner', 'Odd_PS_W', 'Odd_PS_L',
            'Odd_Max_W', 'Odd_Max_L', 'Odd_Avg_W', 'Odd_Avg_L']
    unido = base.merge(extra[cols].rename(columns={'Winner': '_ganador_td'}),
                       on='_k', how='left')

    gano_p1 = unido['_ganador_td'].astype(str).str.strip() == \
        unido['Player_1'].astype(str).str.strip()
    for casa in ('PS', 'Max', 'Avg'):
        w, l = unido[f'Odd_{casa}_W'], unido[f'Odd_{casa}_L']
        unido[f'Odd_{casa}_1'] = np.where(gano_p1, w, l)
        unido[f'Odd_{casa}_2'] = np.where(gano_p1, l, w)
        unido = unido.drop(columns=[f'Odd_{casa}_W', f'Odd_{casa}_L'])

    # `Series` de Kaggle manda; `Nivel` de tennis-data rellena lo que falte
    unido['Series'] = unido['Series'].where(unido['Series'].notna(), unido['Nivel'])
    unido['Comment'] = unido['Comment_y'].where(
        unido['Comment_y'].notna(), unido.get('Comment_x'))
    unido['Retirado'] = unido['Comment'].astype(str).str.lower().isin(
        ['retired', 'walkover', 'disqualified', 'def.'])
    cobertura = float(unido['Nivel'].notna().mean())
    # HALLAZGO v67: el mirror de Kaggle YA excluye retiradas y walkovers. De las
    # 1.095 filas de tennis-data que no enlazan, 1.023 son exactamente
    # Retired/Walkover/Awarded/Disqualified. Es decir, el entrenamiento nunca
    # estuvo contaminado por partidos decididos por abandono, y filtrarlos —una
    # de las mejoras que se iban a probar— no habría cambiado nada.
    solo_extra = int((~extra['_k'].isin(set(base['_k']))).sum())
    logger.info(f"[tenis] enriquecido: nivel en {cobertura*100:.1f} % de las filas · "
                f"{int(unido['Retirado'].sum())} retiradas presentes en Kaggle · "
                f"{solo_extra} filas de tennis-data sin equivalente "
                f"(en su práctica totalidad, retiradas que Kaggle ya descarta).")
    return unido.drop(columns=[c for c in ('_k', '_ganador_td', 'Nivel',
                                           'Comment_x', 'Comment_y')
                               if c in unido.columns])


# ---------------------------------------------------------------------------
# 3. ESPN (categorías inferiores)
# ---------------------------------------------------------------------------
# ESPN no publica la superficie. Se deduce del torneo cuando se conoce y, si no,
# del calendario: la gira de tierra es abril-junio y la de hierba junio-julio.
SUP_POR_TORNEO = {
    'wimbledon': 'Grass', 'roland garros': 'Clay', 'french open': 'Clay',
    'us open': 'Hard', 'australian open': 'Hard',
}


def _superficie_espn(torneo: str, fecha: pd.Timestamp,
                     conocidas: Dict[str, str]) -> str:
    t = str(torneo).strip().lower()
    for clave, sup in SUP_POR_TORNEO.items():
        if clave in t:
            return sup
    if t in conocidas:
        return conocidas[t]
    if 'grass' in t or 'hierba' in t:
        return 'Grass'
    if 'clay' in t or 'terra' in t or 'tierra' in t:
        return 'Clay'
    mes = fecha.month
    if mes in (4, 5, 6):
        return 'Clay'
    if mes == 7:
        return 'Grass' if fecha.day <= 20 else 'Hard'
    return 'Hard'


def _marcador(comp: dict) -> str:
    """Reconstruye '6-4 3-6 7-5' desde los linescores de los dos competidores."""
    try:
        a, b = comp['competitors'][0], comp['competitors'][1]
        if a.get('order', 1) > b.get('order', 2):
            a, b = b, a
        la = [int(x['value']) for x in a.get('linescores', [])]
        lb = [int(x['value']) for x in b.get('linescores', [])]
        return ' '.join(f'{x}-{y}' for x, y in zip(la, lb))
    except Exception:
        return ''


def _espn_pide(circuito: str, ini: pd.Timestamp, fin: pd.Timestamp) -> Optional[list]:
    try:
        r = requests.get(ESPN_SCOREBOARD.format(liga=circuito),
                         params={'dates': f'{ini:%Y%m%d}-{fin:%Y%m%d}', 'limit': 400},
                         headers=UA, timeout=TIMEOUT * 2)
        r.raise_for_status()
        return r.json().get('events', []) or []
    except Exception as e:
        logger.debug(f"[tenis/{circuito}] ESPN {ini:%Y-%m-%d}..{fin:%Y-%m-%d}: "
                     f"{type(e).__name__}: {e}")
        return None


def _espn_eventos(circuito: str, ini: pd.Timestamp, fin: pd.Timestamp) -> Optional[list]:
    """
    Pide un tramo y, si ESPN devuelve 500 (pasa en los tramos con Grand Slam:
    demasiados partidos para una sola respuesta), lo TROCEA por meses y luego
    por semanas. Devolver `None` significa "no se pudo"; una lista vacía es un
    tramo legítimamente sin partidos.
    """
    ev = _espn_pide(circuito, ini, fin)
    if ev is not None:
        return ev
    salida, ok = [], False
    for m_ini in pd.date_range(ini, fin, freq='MS'):
        m_fin = min(m_ini + pd.DateOffset(months=1) - pd.Timedelta(days=1), fin)
        sub = _espn_pide(circuito, m_ini, m_fin)
        if sub is None:                       # aún demasiado grande: por semanas
            for s_ini in pd.date_range(m_ini, m_fin, freq='7D'):
                s_fin = min(s_ini + pd.Timedelta(days=6), m_fin)
                trozo = _espn_pide(circuito, s_ini, s_fin)
                if trozo is not None:
                    salida.extend(trozo)
                    ok = True
        else:
            salida.extend(sub)
            ok = True
    if not ok:
        logger.warning(f"[tenis/{circuito}] ESPN {ini:%Y-%m}: tramo no recuperable.")
        return None
    logger.info(f"[tenis/{circuito}] ESPN {ini:%Y-%m}: recuperado troceando "
                f"({len(salida)} eventos).")
    return salida


def cargar_espn(circuito: str, desde: str = '2023-01-01',
                hasta: Optional[str] = None,
                conocidas: Optional[Dict[str, str]] = None) -> pd.DataFrame:
    """
    Histórico de ESPN por tramos de 2 meses (la API acepta rangos `dates=A-B`).
    Solo individuales. Cachea en disco cada tramo cerrado.
    """
    os.makedirs(CACHE_DIR, exist_ok=True)
    conocidas = conocidas or {}
    slug = 'mens-singles' if circuito == 'atp' else 'womens-singles'
    hasta_ts = pd.Timestamp(hasta) if hasta else pd.Timestamp.today().normalize()
    filas: List[dict] = []
    for ini in pd.date_range(pd.Timestamp(desde), hasta_ts, freq='2MS'):
        fin = min(ini + pd.DateOffset(months=2) - pd.Timedelta(days=1), hasta_ts)
        destino = os.path.join(CACHE_DIR, f'espn_{circuito}_{ini:%Y%m}.json')
        cerrado = fin < pd.Timestamp.today().normalize() - pd.Timedelta(days=3)
        if os.path.exists(destino) and (cerrado or
                                        time.time() - os.path.getmtime(destino) < TTL_ESPN):
            try:
                with open(destino, encoding='utf-8') as f:
                    filas.extend(json.load(f))
                continue
            except Exception:
                pass
        eventos = _espn_eventos(circuito, ini, fin)
        if eventos is None:
            continue
        tramo: List[dict] = []
        for ev in eventos:
            nombre = ev.get('name', '')
            for g in ev.get('groupings', []):
                if g.get('grouping', {}).get('slug') != slug:
                    continue
                for c in g.get('competitions', []):
                    if not c.get('status', {}).get('type', {}).get('completed'):
                        continue
                    comps = c.get('competitors', [])
                    if len(comps) != 2:
                        continue
                    orden = sorted(comps, key=lambda x: x.get('order', 9))
                    n1 = (orden[0].get('athlete') or {}).get('displayName')
                    n2 = (orden[1].get('athlete') or {}).get('displayName')
                    if not n1 or not n2 or n1 == n2:
                        continue
                    ganador = next((x for x in comps if x.get('winner')), None)
                    if ganador is None:
                        continue
                    tramo.append({
                        'Tournament': nombre,
                        'Date': str(pd.to_datetime(c.get('date')).tz_localize(None).date()),
                        'Round': (c.get('round') or {}).get('displayName'),
                        'Best of': ((c.get('format') or {}).get('regulation') or {}).get('periods', 3),
                        'Player_1': n1, 'Player_2': n2,
                        'Winner': (ganador.get('athlete') or {}).get('displayName'),
                        'Score': _marcador(c),
                        'major': bool(ev.get('major')),
                    })
        try:
            with open(destino, 'w', encoding='utf-8') as f:
                json.dump(tramo, f, ensure_ascii=False)
        except Exception:
            pass
        filas.extend(tramo)

    if not filas:
        return pd.DataFrame()
    df = pd.DataFrame(filas).drop_duplicates(
        subset=['Date', 'Tournament', 'Player_1', 'Player_2'], keep='last')
    df['Date'] = pd.to_datetime(df['Date'])
    # Nombres al formato del circuito principal: sin esto, ESPN duplicaría los
    # partidos del tour Y crearía un jugador nuevo por cada grafía.
    for col in ('Player_1', 'Player_2', 'Winner'):
        df[col] = df[col].map(canonico)
    df = df[(df['Player_1'] != df['Player_2']) &
            df['Winner'].isin(set(df['Player_1']) | set(df['Player_2']))]
    df['Surface'] = [_superficie_espn(t, d, conocidas)
                     for t, d in zip(df['Tournament'], df['Date'])]
    df['Court'] = 'Outdoor'
    df['Series'] = np.nan
    for c in ('Rank_1', 'Rank_2', 'Pts_1', 'Pts_2', 'Odd_1', 'Odd_2'):
        df[c] = np.nan
    df['Comment'] = 'Completed'
    df['Fuente'] = 'espn'
    logger.info(f"[tenis/{circuito}] ESPN: {len(df)} partidos de individuales "
                f"desde {desde}.")
    return df


# ---------------------------------------------------------------------------
# Unificación
# ---------------------------------------------------------------------------
def historico_unificado(circuito: str, con_espn: bool = True,
                        con_tennis_data: bool = True,
                        espn_desde: str = '2023-01-01') -> pd.DataFrame:
    """
    Devuelve el histórico del circuito con esquema `COLUMNAS`, ordenado por
    fecha. Kaggle manda; ESPN solo aporta los partidos que Kaggle no tiene
    (es decir, las categorías inferiores).
    """
    base = cargar_kaggle(circuito)
    if con_tennis_data:
        try:
            base = enriquecer(base, cargar_tennis_data(circuito))
        except Exception as e:
            logger.warning(f"[tenis/{circuito}] enriquecimiento omitido: "
                           f"{type(e).__name__}: {e}")
            base['Retirado'] = False
    else:
        base['Retirado'] = False

    # Superficies conocidas por torneo (las aprende del circuito principal y se
    # las presta a ESPN, que no publica superficie)
    conocidas = {}
    if 'Surface' in base.columns:
        vc = base.dropna(subset=['Surface']).groupby(
            base['Tournament'].astype(str).str.strip().str.lower())['Surface']
        conocidas = vc.agg(lambda s: s.mode().iat[0] if len(s.mode()) else 'Hard').to_dict()

    marcos = [base]
    if con_espn:
        try:
            espn = cargar_espn(circuito, desde=espn_desde, conocidas=conocidas)
            if not espn.empty:
                # Solape con Kaggle: misma pareja canónica y fecha ±1 día (las
                # dos fuentes usan husos distintos, así que un partido nocturno
                # puede figurar un día antes o después).
                claves_base = set()
                for delta in (-1, 0, 1):
                    claves_base |= set(_clave_partido(
                        base['Date'] + pd.Timedelta(days=delta),
                        base['Player_1'], base['Player_2']))
                ke = _clave_partido(espn['Date'], espn['Player_1'], espn['Player_2'])
                espn['Retirado'] = False
                nuevos = espn[~ke.isin(claves_base)]
                logger.info(f"[tenis/{circuito}] ESPN aporta {len(nuevos)} partidos "
                            f"nuevos ({len(espn) - len(nuevos)} ya estaban en Kaggle).")
                if not nuevos.empty:
                    marcos.append(nuevos)
        except Exception as e:
            logger.warning(f"[tenis/{circuito}] ESPN omitido: {type(e).__name__}: {e}")

    df = pd.concat(marcos, ignore_index=True, sort=False)
    # Catálogo de torneos del circuito principal (para reconocer los de ESPN).
    # SOLO los de los últimos años: con el catálogo histórico completo (200+
    # nombres, muchos de torneos extintos) el fuzzy encontraba parecidos donde
    # no los hay y ascendía torneos ITF a "WTA Tour".
    catalogo = catalogo_principal(circuito)
    if not catalogo:
        catalogo = sorted(base['Tournament'].dropna().astype(str).unique())
    if 'major' not in df.columns:
        df['major'] = False
    df['major'] = df['major'].fillna(False).astype(bool)
    df['Categoria'] = [categoria_de(circuito, t, s, f, catalogo, mj)
                       for t, s, f, mj in zip(df['Tournament'], df.get('Series'),
                                              df['Fuente'], df['major'])]
    # Fase: ESPN es la única fuente que publica la previa; el circuito
    # principal de Kaggle es siempre cuadro final.
    ronda = df.get('Round', pd.Series([''] * len(df))).astype(str).str.lower()
    df['Fase'] = np.where(ronda.str.startswith('qualifying'),
                          'clasificacion', 'cuadro_principal')
    df = df.dropna(subset=['Date', 'Player_1', 'Player_2', 'Winner'])
    df = df.sort_values('Date').reset_index(drop=True)
    logger.info(f"[tenis/{circuito}] histórico unificado: {len(df)} partidos · "
                f"categorías: {df['Categoria'].value_counts().to_dict()} · "
                f"fases: {df['Fase'].value_counts().to_dict()}")
    return df


# ---------------------------------------------------------------------------
# Próximos partidos (se refrescan solos)
# ---------------------------------------------------------------------------
_CACHE_FIXTURES: Dict[str, tuple] = {}
_CACHE_CATALOGO: Dict[str, List[str]] = {}
TTL_FIXTURES = 20 * 60


def catalogo_principal(circuito: str) -> List[str]:
    """
    Nombres de torneo del circuito PRINCIPAL (los que publica Kaggle). Es lo
    que permite distinguir un Challenger de verdad de la fase previa de un
    Masters. Se cachea en disco: sin él, `fixtures_tenis` clasificaba el
    "Mubadala DC Open" (ATP 500) como Challenger.
    """
    if circuito in _CACHE_CATALOGO:
        return _CACHE_CATALOGO[circuito]
    os.makedirs(CACHE_DIR, exist_ok=True)
    ruta = os.path.join(CACHE_DIR, f'catalogo_{circuito}.json')
    if os.path.exists(ruta) and time.time() - os.path.getmtime(ruta) < 7 * 86400:
        try:
            with open(ruta, encoding='utf-8') as f:
                _CACHE_CATALOGO[circuito] = json.load(f)
                return _CACHE_CATALOGO[circuito]
        except Exception:
            pass
    try:
        base = cargar_kaggle(circuito)
        # Solo torneos vigentes: uno de hace 20 años no dice nada del calendario
        recientes = base[base['Date'] >= base['Date'].max() - pd.DateOffset(years=3)]
        nombres = sorted(recientes['Tournament'].dropna().astype(str).unique())
    except Exception as e:
        logger.warning(f"[tenis/{circuito}] catálogo no disponible: {type(e).__name__}")
        nombres = []
    _CACHE_CATALOGO[circuito] = nombres
    try:
        with open(ruta, 'w', encoding='utf-8') as f:
            json.dump(nombres, f, ensure_ascii=False)
    except Exception:
        pass
    return nombres


def fixtures_tenis(circuito: str = 'atp', dias: int = 8,
                   catalogo: Optional[List[str]] = None,
                   rankings: Optional[Dict[str, float]] = None) -> List[Dict]:
    """
    Próximos partidos de individuales del circuito, desde ESPN.

    Devuelve [{'fecha','hora','torneo','categoria','ronda','p1','p2','major'}]
    ordenados por fecha. Se cachea 20 minutos: la UI no necesita botón de
    recarga, el propio TTL hace que se actualicen solos.
    """
    ck = f'{circuito}:{dias}'
    ahora = time.time()
    if ck in _CACHE_FIXTURES and ahora - _CACHE_FIXTURES[ck][0] < TTL_FIXTURES:
        return _CACHE_FIXTURES[ck][1]

    if catalogo is None:
        catalogo = catalogo_principal(circuito)
    slug = 'mens-singles' if circuito == 'atp' else 'womens-singles'
    hoy = pd.Timestamp.today().normalize()
    fin = hoy + pd.Timedelta(days=dias)
    eventos = _espn_eventos(circuito, hoy, fin) or []
    salida: List[Dict] = []
    for ev in eventos:
        nombre = ev.get('name', '')
        major = bool(ev.get('major'))
        for g in ev.get('groupings', []):
            if g.get('grouping', {}).get('slug') != slug:
                continue
            for c in g.get('competitions', []):
                estado = c.get('status', {}).get('type', {})
                if estado.get('completed'):
                    continue
                comps = c.get('competitors', [])
                if len(comps) != 2:
                    continue
                orden = sorted(comps, key=lambda x: x.get('order', 9))
                n1 = ((orden[0].get('athlete') or {}).get('displayName') or '').strip()
                n2 = ((orden[1].get('athlete') or {}).get('displayName') or '').strip()
                if not n1 or not n2 or n1 == n2:
                    continue
                try:
                    f = pd.to_datetime(c.get('date')).tz_convert(None)
                except Exception:
                    try:
                        f = pd.to_datetime(c.get('date')).tz_localize(None)
                    except Exception:
                        continue
                ronda = (c.get('round') or {}).get('displayName', '')
                fase = ('clasificacion' if str(ronda).lower().startswith('qualifying')
                        else 'cuadro_principal')
                rank_medio = None
                if rankings:
                    rs = [rankings.get(canonico(n)) for n in (n1, n2)]
                    rs = [r for r in rs if r]
                    if rs:
                        rank_medio = float(np.mean(rs))
                salida.append({
                    'fecha': f.strftime('%Y-%m-%d'),
                    'hora': f.strftime('%H:%M'),
                    'torneo': nombre,
                    'categoria': categoria_de(circuito, nombre, None, 'espn',
                                              catalogo or [], major, rank_medio,
                                              por_descarte='principal'),
                    'rank_medio': round(rank_medio, 1) if rank_medio else None,
                    'ronda': ronda, 'fase': fase,
                    'best_of': ((c.get('format') or {}).get('regulation') or {}).get('periods', 3),
                    'p1': canonico(n1), 'p2': canonico(n2),
                    'p1_largo': n1, 'p2_largo': n2,
                    'major': major,
                    'estado': estado.get('shortDetail', ''),
                })
    # Consolidar la categoría POR TORNEO: clasificar partido a partido dejaba
    # el mismo cuadro repartido entre "ATP Tour" y "Challenger" según a quién
    # le tocara jugar. La categoría de un torneo es una sola, y la marca la
    # MEDIANA del ranking de todo su cuadro.
    if rankings:
        por_torneo: Dict[str, List[float]] = {}
        for f in salida:
            if f['rank_medio']:
                por_torneo.setdefault(f['torneo'], []).append(f['rank_medio'])
        for f in salida:
            muestras = por_torneo.get(f['torneo'])
            if not muestras or len(muestras) < 3:
                continue
            f['categoria'] = categoria_de(circuito, f['torneo'], None, 'espn',
                                          catalogo or [], f['major'],
                                          float(np.median(muestras)),
                                          por_descarte='principal')
    salida.sort(key=lambda x: (x['fecha'], x['hora']))
    _CACHE_FIXTURES[ck] = (ahora, salida)
    logger.info(f"[tenis/{circuito}] {len(salida)} próximos partidos de individuales.")
    return salida


def resumen_fuentes(circuito: str) -> Dict:
    """Diagnóstico rápido (lo usa el informe de validación y la UI)."""
    df = historico_unificado(circuito)
    return {
        'circuito': circuito,
        'n_partidos': int(len(df)),
        'desde': str(df['Date'].min().date()),
        'hasta': str(df['Date'].max().date()),
        'por_fuente': df['Fuente'].value_counts().to_dict(),
        'por_categoria': df['Categoria'].value_counts().to_dict(),
        'por_fase': df['Fase'].value_counts().to_dict(),
        'con_nivel': round(float(df['Series'].notna().mean()), 4),
        'retirados': int(df.get('Retirado', pd.Series(dtype=bool)).sum()),
        'con_cuotas': round(float(df['Odd_1'].notna().mean()), 4),
    }


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    for c in ('atp', 'wta'):
        print(json.dumps(resumen_fuentes(c), indent=2, ensure_ascii=False))
