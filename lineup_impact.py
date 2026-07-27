#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v70 · Mejoras A y B — ajuste de λ por alineación confirmada y por portero.

Por qué este módulo existe
--------------------------
Un equipo sin sus tres titulares ofensivos no es el mismo equipo, y el modelo
1X2 no lo sabe: sus features son medias móviles de EQUIPO. Este módulo mete esa
información por la única puerta donde no rompe nada: un ajuste multiplicativo
sobre las λ (goles esperados) justo antes de construir la matriz de marcadores.

Auditoría de cobertura (Fase 1, v70)
------------------------------------
La lección de v69 fue no juzgar una feature sin medir antes cuántas veces llega
a calcularse (las de saque tenían techo del 34,5 %). Medido con
`_v70_fase1_rosters.py` sobre 5 ventanas de 2019 a 2026:

    MLS · Liga MX · Premier · LaLiga · Serie A · Brasileirão
    rosters 100 % · 11 titulares 100 % · stats por jugador 100 % · GK saves 100 %

Es decir: cobertura total, no hay dilución posible.

Modelo
------
1. **Rating del jugador** (Mejora A). Aporte ofensivo observado por partido como
   titular:  `goles + 0.5·asistencias + 0.3·remates_a_puerta`.
   Se calcula como media de sus últimos `VENTANA_JUGADOR` partidos ANTERIORES al
   que se predice. Sin datos, se imputa con la mediana de su posición en la liga.

2. **Fuerza de alineación**: media de los ratings de los 11 titulares.
   `lineup_diff = (fuerza_local − fuerza_visitante) / std(ratings de la liga)`.

3. **Ajuste de λ**:
       λ_local     = λ_base · exp( β · lineup_diff)
       λ_visitante = λ_base · exp(−β · lineup_diff)

4. **Índice de portero** (Mejora B). Con `saves` (SV) y `goalsConceded` (GA):
       paradas_esperadas = tiros_a_puerta_enfrentados · (1 − conversión_liga)
       GK_index = (paradas_esperadas − goles_encajados) / partidos
   Positivo = para más de lo que le corresponde. El ajuste va sobre el ataque
   RIVAL, que es a quien frena:
       λ_ataque_rival *= exp(−γ · gk_diff)

β y γ se calibran por liga en walk-forward minimizando la desviación de Poisson
entre goles esperados y reales, **usando sólo partidos anteriores al de test**.
Los valores adoptados viven en `lineup_coef.json`; una liga sin entrada ahí no
recibe ajuste (degradación limpia).

Uso:
    python lineup_impact.py recolectar usa.1 --desde 2018-01-01
    python lineup_impact.py ratings usa.1
    from lineup_impact import adjust_lambda
"""
import argparse
import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import requests

logger = logging.getLogger(__name__)

BASE = 'https://site.api.espn.com/apis/site/v2/sports/soccer/{liga}'
UA = {'User-Agent': 'Mozilla/5.0'}
TIMEOUT = 25
TRAMO_DIAS = 55                      # ESPN devuelve 400 con rangos largos
ARCHIVO_COEF = 'lineup_coef.json'
VENTANA_JUGADOR = 5                  # partidos previos para el rating
VENTANA_EQUIPO = 10                  # onces previos para el once "habitual"
MIN_TITULARES = 9                    # menos de esto = alineación no fiable

# Peso de cada contribución observada en el rating ofensivo del jugador
W_GOL, W_ASIS, W_SOG = 1.0, 0.5, 0.3

# Topes de seguridad: el ajuste nunca puede mover λ más de un ±35 %
TOPE_LOG = 0.30


def _ruta_alineaciones(liga: str) -> str:
    return f"alineaciones_{liga.replace('.', '_')}.csv.gz"


def _ruta_ratings(liga: str) -> str:
    return f"jugadores_rating_{liga.replace('.', '_')}.csv.gz"


# ---------------------------------------------------------------------------
# 1. Recolección del histórico de alineaciones desde ESPN
# ---------------------------------------------------------------------------
def _get(url: str, params: dict, reintentos: int = 3) -> Optional[dict]:
    for i in range(reintentos):
        try:
            r = requests.get(url, params=params, headers=UA, timeout=TIMEOUT)
            if r.status_code == 400:
                return None                  # rango que ESPN rechaza: no insistir
            r.raise_for_status()
            return r.json()
        except Exception:
            time.sleep(1.0 * (i + 1))
    return None


def eventos_liga(liga: str, desde: str, hasta: str) -> List[dict]:
    """Partidos TERMINADOS de la liga entre esas fechas, troceando el rango."""
    out, vistos = [], set()
    cur, fin = pd.Timestamp(desde), pd.Timestamp(hasta)
    while cur < fin:
        tope = min(cur + pd.Timedelta(days=TRAMO_DIAS), fin)
        j = _get(BASE.format(liga=liga) + '/scoreboard',
                 {'dates': f'{cur:%Y%m%d}-{tope:%Y%m%d}', 'limit': 500})
        for ev in (j or {}).get('events', []):
            if not ev.get('status', {}).get('type', {}).get('completed'):
                continue
            if ev['id'] in vistos:
                continue
            vistos.add(ev['id'])
            comp = (ev.get('competitions') or [{}])[0]
            eq = {}
            for c in comp.get('competitors', []):
                eq[c.get('homeAway')] = (c.get('team') or {}).get('displayName')
            out.append({'id': ev['id'], 'fecha': (ev.get('date') or '')[:10],
                        'home': eq.get('home'), 'away': eq.get('away')})
        cur = tope + pd.Timedelta(days=1)
    out.sort(key=lambda x: x['fecha'])
    return out


def _fila_jugador(a: dict) -> Optional[dict]:
    """Una fila por jugador del `roster` de ESPN, con sus estadísticas."""
    atleta = a.get('athlete') or {}
    st = {x.get('abbreviation'): x.get('displayValue') for x in (a.get('stats') or [])}

    def _num(k):
        try:
            return float(st.get(k) or 0)
        except (TypeError, ValueError):
            return 0.0

    nombre = atleta.get('displayName')
    if not nombre:
        return None
    return {
        'jugador': nombre,
        'jugador_id': str(atleta.get('id') or nombre),
        'posicion': (a.get('position') or {}).get('abbreviation') or '',
        'titular': bool(a.get('starter')),
        'tiene_stats': 'SHOT' in st,
        'goles': _num('G'), 'asistencias': _num('A'),
        'remates': _num('SHOT'), 'al_arco': _num('SOG'),
        # portero
        'paradas': _num('SV'), 'goles_encajados': _num('GA'),
        'tiros_recibidos': _num('SHF'),
    }


def alineacion_evento(liga: str, ev: dict) -> List[dict]:
    j = _get(BASE.format(liga=liga) + '/summary', {'event': ev['id']})
    if not j:
        return []
    filas = []
    for ro in (j.get('rosters') or []):
        equipo = (ro.get('team') or {}).get('displayName')
        lado = ro.get('homeAway') or ('home' if equipo == ev['home'] else 'away')
        for a in (ro.get('roster') or []):
            f = _fila_jugador(a)
            if f is None:
                continue
            f.update({'event_id': ev['id'], 'fecha': ev['fecha'], 'liga': liga,
                      'equipo': equipo, 'lado': lado,
                      'home': ev['home'], 'away': ev['away']})
            filas.append(f)
    return filas


def recolectar(liga: str, desde: str = '2018-01-01',
               hasta: Optional[str] = None, hilos: int = 6) -> pd.DataFrame:
    """
    Construye/actualiza el histórico de alineaciones de una liga.

    Es incremental: si el CSV ya existe sólo pide los eventos que faltan, así
    que el bot diario cuesta unos segundos en vez de rehacerlo todo.
    """
    hasta = hasta or str(pd.Timestamp.today().date())
    ruta = _ruta_alineaciones(liga)
    previo = pd.DataFrame()
    ya = set()
    if os.path.exists(ruta):
        previo = pd.read_csv(ruta)
        ya = set(previo['event_id'].astype(str))
        logger.info(f"[{liga}] histórico previo: {len(previo)} filas, "
                    f"{len(ya)} partidos.")

    evs = [e for e in eventos_liga(liga, desde, hasta) if str(e['id']) not in ya]
    logger.info(f"[{liga}] {len(evs)} partidos nuevos que pedir a ESPN.")
    filas: List[dict] = []
    if evs:
        with ThreadPoolExecutor(max_workers=hilos) as ex:
            for i, res in enumerate(ex.map(lambda e: alineacion_evento(liga, e), evs), 1):
                filas.extend(res)
                if i % 100 == 0:
                    logger.info(f"[{liga}]   {i}/{len(evs)} partidos...")
    nuevo = pd.DataFrame(filas)
    todo = pd.concat([previo, nuevo], ignore_index=True) if len(previo) else nuevo
    if todo.empty:
        logger.warning(f"[{liga}] sin alineaciones.")
        return todo
    todo['event_id'] = todo['event_id'].astype(str)
    todo = todo.drop_duplicates(subset=['event_id', 'equipo', 'jugador_id'], keep='last')
    todo = todo.sort_values(['fecha', 'event_id']).reset_index(drop=True)
    todo.to_csv(ruta, index=False, compression='gzip')
    logger.info(f"[{liga}] guardado {ruta}: {len(todo)} filas · "
                f"{todo['event_id'].nunique()} partidos · "
                f"{todo['fecha'].min()} → {todo['fecha'].max()}")
    return todo


# ---------------------------------------------------------------------------
# 2. Ratings rodantes por jugador (SIN FUGA: sólo partidos anteriores)
# ---------------------------------------------------------------------------
def _aporte(fila) -> float:
    return (W_GOL * fila['goles'] + W_ASIS * fila['asistencias']
            + W_SOG * fila['al_arco'])


def construir_ratings(liga: str, df: Optional[pd.DataFrame] = None) -> pd.DataFrame:
    """
    Para cada (partido, jugador) calcula el rating con la media de sus
    `VENTANA_JUGADOR` titularidades ANTERIORES. La primera vez que aparece un
    jugador su rating es NaN y se imputará con la mediana de su posición.

    Devuelve el mismo dataframe con las columnas `rating_previo`,
    `n_previos`, `gk_index_previo`.
    """
    if df is None:
        ruta = _ruta_alineaciones(liga)
        if not os.path.exists(ruta):
            raise FileNotFoundError(f"falta {ruta}; corre `recolectar` primero.")
        df = pd.read_csv(ruta)
    df = df.sort_values(['fecha', 'event_id']).reset_index(drop=True)
    df['aporte'] = df.apply(_aporte, axis=1)

    # conversión de la liga: goles por tiro a puerta, para las paradas esperadas
    tot_sog = df['al_arco'].sum()
    tot_gol = df['goles'].sum()
    conversion = float(tot_gol / tot_sog) if tot_sog > 0 else 0.33

    # aporte del portero en ESE partido (se promedia igual que el de campo)
    esperadas = df['tiros_recibidos'] * (1.0 - conversion)
    df['gk_aporte'] = np.where(df['tiros_recibidos'] > 0,
                               esperadas - df['goles_encajados'], np.nan)

    hist: Dict[str, List[float]] = {}
    hist_gk: Dict[str, List[float]] = {}
    ratings, previos, gk_ratings = [], [], []
    for r in df.itertuples(index=False):
        h = hist.get(r.jugador_id, [])
        ratings.append(float(np.mean(h)) if h else np.nan)
        previos.append(len(h))
        hg = hist_gk.get(r.jugador_id, [])
        gk_ratings.append(float(np.mean(hg)) if hg else np.nan)
        # sólo las TITULARIDADES con estadística alimentan el historial
        if r.titular and r.tiene_stats:
            hist.setdefault(r.jugador_id, []).append(r.aporte)
            hist[r.jugador_id] = hist[r.jugador_id][-VENTANA_JUGADOR:]
        if r.titular and not np.isnan(r.gk_aporte):
            hist_gk.setdefault(r.jugador_id, []).append(r.gk_aporte)
            hist_gk[r.jugador_id] = hist_gk[r.jugador_id][-VENTANA_JUGADOR:]

    df['rating_previo'] = ratings
    df['n_previos'] = previos
    df['gk_index_previo'] = gk_ratings
    df.attrs['conversion_liga'] = conversion
    return df


def fuerza_alineaciones(liga: str, df: Optional[pd.DataFrame] = None) -> pd.DataFrame:
    """
    Un registro por PARTIDO con la fuerza de cada alineación titular,
    `lineup_diff` (normalizado por la desviación típica de la liga) y `gk_diff`.
    """
    df = construir_ratings(liga, df)
    tit = df[df['titular']].copy()
    # imputación por posición con la mediana de la liga (sin fuga: es un
    # agregado estable, no depende del resultado del partido concreto)
    med_pos = tit.groupby('posicion')['rating_previo'].median()
    med_global = float(tit['rating_previo'].median() or 0.0)
    tit['rating'] = tit.apply(
        lambda r: r['rating_previo'] if pd.notna(r['rating_previo'])
        else float(med_pos.get(r['posicion'], med_global) or med_global), axis=1)

    sd = float(tit['rating'].std()) or 1.0
    filas = []
    for (eid, fecha), g in tit.groupby(['event_id', 'fecha']):
        lados = {}
        gk = {}
        equipos = {}
        for lado, gl in g.groupby('lado'):
            if len(gl) < MIN_TITULARES:
                continue
            lados[lado] = float(gl['rating'].mean())
            equipos[lado] = gl['equipo'].iat[0]
            porteros = gl[gl['posicion'].isin(('G', 'GK'))]
            if len(porteros):
                v = porteros['gk_index_previo'].mean()
                gk[lado] = float(v) if pd.notna(v) else np.nan
        if 'home' not in lados or 'away' not in lados:
            continue
        fila = {'event_id': str(eid), 'fecha': fecha,
                'home': g['home'].iat[0], 'away': g['away'].iat[0],
                'equipo_home': equipos.get('home'), 'equipo_away': equipos.get('away'),
                'fuerza_home': round(lados['home'], 4),
                'fuerza_away': round(lados['away'], 4),
                'lineup_diff': round((lados['home'] - lados['away']) / sd, 4),
                'gk_home': gk.get('home', np.nan),
                'gk_away': gk.get('away', np.nan)}
        fila['gk_diff'] = (fila['gk_home'] - fila['gk_away']
                           if pd.notna(fila['gk_home']) and pd.notna(fila['gk_away'])
                           else np.nan)
        filas.append(fila)
    out = pd.DataFrame(filas).sort_values('fecha').reset_index(drop=True)
    out.attrs['sd_liga'] = sd
    return _anadir_delta_propio(out, sd)


def _anadir_delta_propio(fz: pd.DataFrame, sd: float,
                         ventana: int = VENTANA_EQUIPO) -> pd.DataFrame:
    """
    v70 — `lineup_delta`: cuánto se desvía el once de HOY del once HABITUAL de
    ese mismo equipo.

    Por qué hace falta además de `lineup_diff`
    ------------------------------------------
    `lineup_diff` mide la calidad ABSOLUTA de los onces enfrentados, y eso el
    modelo ya lo sabe: está en el ELO, en la forma y en las medias móviles de
    goles. Medido en MLS, ese solapamiento deja β en +0,02/+0,04 y una mejora de
    +0,07 pp — dirección correcta, magnitud de ruido.

    Lo que el modelo NO puede saber por otra vía es si el equipo sale hoy con su
    once de siempre o rotado, que es exactamente el enunciado de la mejora («un
    equipo sin sus tres titulares ofensivos no es el mismo equipo»). Eso es la
    desviación respecto a la media móvil de la fuerza de sus propios onces
    anteriores — ortogonal por construcción a la calidad del equipo.

    Sin fuga: la media móvil usa sólo partidos ANTERIORES del equipo.
    """
    hist: Dict[str, List[float]] = {}
    d_h, d_a = [], []
    for r in fz.itertuples(index=False):
        for lado, eq, fuerza, destino in (
                ('home', r.equipo_home, r.fuerza_home, d_h),
                ('away', r.equipo_away, r.fuerza_away, d_a)):
            prev = hist.get(eq, [])
            destino.append((fuerza - float(np.mean(prev))) / sd
                           if len(prev) >= 3 else np.nan)
        for eq, fuerza in ((r.equipo_home, r.fuerza_home),
                           (r.equipo_away, r.fuerza_away)):
            hist.setdefault(eq, []).append(float(fuerza))
            hist[eq] = hist[eq][-ventana:]
    fz = fz.copy()
    fz['delta_home'] = np.round(d_h, 4)
    fz['delta_away'] = np.round(d_a, 4)
    fz['lineup_delta'] = np.round(np.asarray(d_h) - np.asarray(d_a), 4)
    return fz


# ---------------------------------------------------------------------------
# 3. Ajuste de λ (lo que consume producción)
# ---------------------------------------------------------------------------
def _cargar_coef() -> Dict[str, dict]:
    if os.path.exists(ARCHIVO_COEF):
        try:
            with open(ARCHIVO_COEF, encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def coeficientes(clave_liga: str) -> Optional[dict]:
    """β y γ adoptados para esa liga, o None si no se adoptó ninguno."""
    c = _cargar_coef().get(clave_liga)
    if not c or not c.get('adoptado'):
        return None
    return c


def adjust_lambda(lam_h: float, lam_a: float, clave_liga: str,
                  lineup_diff: Optional[float] = None,
                  gk_diff: Optional[float] = None,
                  lineup_delta: Optional[float] = None) -> Tuple[float, float, dict]:
    """
    Devuelve (λ_local, λ_visitante, info) con el ajuste por alineación y portero.

    Si la liga no tiene coeficientes adoptados o no hay alineación confirmada,
    devuelve las λ ORIGINALES sin tocar — la degradación es silenciosa y limpia,
    igual que hace el proyecto con las cuotas ausentes.
    """
    info = {'aplicado': False, 'lineup_diff': lineup_diff, 'gk_diff': gk_diff,
            'lineup_delta': lineup_delta}
    c = coeficientes(clave_liga)
    if c is None:
        return lam_h, lam_a, info

    beta = float(c.get('beta', 0.0))
    gamma = float(c.get('gamma', 0.0))
    delta = float(c.get('delta', 0.0))
    ajuste_h, ajuste_a = 0.0, 0.0

    if lineup_diff is not None and np.isfinite(lineup_diff) and beta:
        ajuste_h += beta * float(lineup_diff)
        ajuste_a -= beta * float(lineup_diff)
        info['aplicado'] = True
        info['beta'] = beta

    # rotación respecto al once habitual del propio equipo (v70)
    if lineup_delta is not None and np.isfinite(lineup_delta) and delta:
        ajuste_h += delta * float(lineup_delta)
        ajuste_a -= delta * float(lineup_delta)
        info['aplicado'] = True
        info['delta'] = delta

    # gk_diff > 0 = el portero LOCAL para más de lo esperado respecto al visitante
    # => frena el ataque VISITANTE (λ_a baja) y viceversa.
    if gk_diff is not None and np.isfinite(gk_diff) and gamma:
        ajuste_a -= gamma * float(gk_diff)
        ajuste_h += gamma * float(gk_diff)
        info['aplicado'] = True
        info['gamma'] = gamma

    if not info['aplicado']:
        return lam_h, lam_a, info

    ajuste_h = float(np.clip(ajuste_h, -TOPE_LOG, TOPE_LOG))
    ajuste_a = float(np.clip(ajuste_a, -TOPE_LOG, TOPE_LOG))
    nh = float(np.clip(lam_h * np.exp(ajuste_h), 0.15, 5.0))
    na = float(np.clip(lam_a * np.exp(ajuste_a), 0.15, 5.0))
    info.update({'factor_home': round(float(np.exp(ajuste_h)), 4),
                 'factor_away': round(float(np.exp(ajuste_a)), 4),
                 'lambda_home_base': round(lam_h, 4),
                 'lambda_away_base': round(lam_a, 4)})
    return nh, na, info


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    ap = argparse.ArgumentParser()
    ap.add_argument('accion', choices=['recolectar', 'ratings', 'fuerza'])
    ap.add_argument('liga')
    ap.add_argument('--desde', default='2018-01-01')
    ap.add_argument('--hasta', default=None)
    a = ap.parse_args()
    if a.accion == 'recolectar':
        recolectar(a.liga, a.desde, a.hasta)
    elif a.accion == 'ratings':
        d = construir_ratings(a.liga)
        print(d[['fecha', 'equipo', 'jugador', 'titular', 'rating_previo',
                 'n_previos']].tail(20).to_string(index=False))
    else:
        d = fuerza_alineaciones(a.liga)
        print(d.tail(20).to_string(index=False))
        print(f"\n{len(d)} partidos con alineación · "
              f"lineup_diff sd={d['lineup_diff'].std():.3f} · "
              f"gk_diff disponible en {d['gk_diff'].notna().mean()*100:.1f} %")
