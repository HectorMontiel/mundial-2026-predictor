#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Ajuste por alineación con VORP — modo EXPERIMENTAL (v25, spec §1.4).

VORP (Value Over Replacement Player) simplificado y honesto con los datos
gratuitos disponibles:

  * Once ESPERADO por equipo: los 11 jugadores con más titularidades en
    alineaciones_historicas.csv (colector ESPN en modo sombra desde v19).
  * Valor ofensivo por jugador: xg90_estimado de jugadores_xg.csv;
    reemplazo = mediana del xg90 de los NO titulares del plantel.
  * Factor de ajuste del equipo = Σ xg90 del once REAL / Σ xg90 del once
    esperado, acotado a [0.85, 1.15]. Se aplica SOLO a las tasas de goles
    (λ) — el 1X2 calibrado NO se toca (misma filosofía que la altitud v10 y
    el MAT v23: ajustes post-regresor).

## Fallback ESTRICTO (spec §1.4)
El ajuste se ABORTA — y el modelo base queda intacto — si:
  1. ESPN no publica aún la alineación del partido (típicamente sale ~1 h
     antes; la regla de decisión es 45 min antes del inicio), o
  2. se parsean MENOS de 10 titulares con fuzzy match > 0.85 contra el
     plantel conocido del equipo, o
  3. el equipo no tiene historial suficiente (menos de 3 alineaciones
     previas en la base sombra).
En la UI se muestra «Ajuste por alineación no disponible» y el motivo.

## Evaluación
Experimental durante la temporada 2026-27: cada aplicación se registra en
vorp_log.json (fecha, partido, factores) para comparar precisión/log-loss
con y sin ajuste al cierre (adopción permanente solo si mejora ≥1 pp en los
partidos donde se aplicó — spec §1.4).
"""

import json
import logging
import os
from difflib import SequenceMatcher
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

UMBRAL_FUZZY = 0.85
MIN_TITULARES = 10
MIN_HISTORIAL = 3
FACTOR_MIN, FACTOR_MAX = 0.85, 1.15
XG90_DEFECTO = 0.08
LOG_ARCHIVO = 'vorp_log.json'


def _cargar_bases() -> Tuple[pd.DataFrame, pd.DataFrame]:
    al = pd.read_csv('alineaciones_historicas.csv') \
        if os.path.exists('alineaciones_historicas.csv') else pd.DataFrame()
    xg = pd.read_csv('jugadores_xg.csv') \
        if os.path.exists('jugadores_xg.csv') else pd.DataFrame()
    return al, xg


def _fuzzy(a: str, b: str) -> float:
    return SequenceMatcher(None, str(a).lower(), str(b).lower()).ratio()


def _equipo_en_base(al: pd.DataFrame, equipo: str) -> Optional[str]:
    """Nombre del equipo en la base sombra (fuzzy: ESPN vs football-data)."""
    if al.empty:
        return None
    candidatos = al['equipo'].dropna().unique()
    mejor, ratio = None, 0.0
    for c in candidatos:
        s = _fuzzy(equipo, c)
        if s > ratio:
            mejor, ratio = c, s
    return mejor if ratio >= UMBRAL_FUZZY else None


def once_esperado(equipo: str) -> Optional[Dict]:
    """Once esperado + valores xg90 del equipo desde la base sombra."""
    al, xg = _cargar_bases()
    nombre = _equipo_en_base(al, equipo)
    if nombre is None:
        return None
    del_eq = al[al['equipo'] == nombre]
    n_partidos = del_eq['event_id'].nunique()
    if n_partidos < MIN_HISTORIAL:
        return None
    titularidades = (del_eq[del_eq['titular']]
                     .groupby('jugador')['event_id'].nunique()
                     .sort_values(ascending=False))
    once = list(titularidades.head(11).index)
    plantel = sorted(set(del_eq['jugador'].dropna()))

    valores = {}
    xg_eq = xg if xg.empty else xg
    for j in plantel:
        v = XG90_DEFECTO
        if not xg.empty:
            cand = xg_eq[xg_eq['nombre'].map(lambda n: _fuzzy(n, j) >= UMBRAL_FUZZY)]
            if len(cand):
                v = float(cand['xg90_estimado'].iloc[0])
        valores[j] = v
    suplentes = [j for j in plantel if j not in once]
    reemplazo = float(np.median([valores[j] for j in suplentes])) \
        if suplentes else XG90_DEFECTO
    return {'equipo_base': nombre, 'once': once, 'plantel': plantel,
            'valores': valores, 'reemplazo': reemplazo,
            'n_partidos': int(n_partidos)}


def evaluar_alineacion(equipo: str, titulares_hoy: List[str]) -> Dict:
    """Factor VORP del equipo con el once de HOY. Fallback estricto."""
    esperado = once_esperado(equipo)
    if esperado is None:
        return {'aplicado': False,
                'motivo': f'{equipo}: historial de alineaciones insuficiente '
                          f'(se necesitan ≥{MIN_HISTORIAL} partidos en la base sombra).'}
    # fuzzy match de los titulares de hoy contra el plantel conocido
    emparejados = []
    for t in titulares_hoy:
        mejor, ratio = None, 0.0
        for p in esperado['plantel']:
            s = _fuzzy(t, p)
            if s > ratio:
                mejor, ratio = p, s
        if ratio >= UMBRAL_FUZZY:
            emparejados.append(mejor)
    if len(emparejados) < MIN_TITULARES:
        return {'aplicado': False,
                'motivo': f'{equipo}: solo {len(emparejados)} titulares '
                          f'emparejados (>{UMBRAL_FUZZY}) — se necesitan '
                          f'≥{MIN_TITULARES}. Modelo base sin modificar.'}
    v = esperado['valores']
    xg_esperado = sum(v.get(j, XG90_DEFECTO) for j in esperado['once'])
    xg_real = sum(v.get(j, esperado['reemplazo']) for j in emparejados)
    # titulares de hoy no emparejados (fichajes nuevos) valen el reemplazo
    xg_real += esperado['reemplazo'] * (len(titulares_hoy) - len(emparejados))
    factor = float(np.clip(xg_real / max(xg_esperado, 1e-6),
                           FACTOR_MIN, FACTOR_MAX))
    ausentes = [j for j in esperado['once'] if j not in emparejados]
    return {'aplicado': True, 'factor': round(factor, 3),
            'emparejados': len(emparejados), 'ausentes_clave': ausentes[:5],
            'equipo_base': esperado['equipo_base']}


def alineacion_hoy(liga: str, home: str, away: str) -> Optional[Dict]:
    """Titulares publicados HOY en ESPN para el partido (o None)."""
    import lineup_collector as lc
    codigo = lc.LIGAS_ESPN.get(liga)
    if not codigo:
        return None
    fecha = pd.Timestamp.today().strftime('%Y%m%d')
    try:
        eventos = lc._eventos_del_dia(codigo, fecha)
    except Exception as e:
        logger.warning(f"[vorp] scoreboard {liga}: {e}")
        return None
    objetivo = None
    for ev in eventos:
        nombre = str(ev.get('name', ''))
        if (_fuzzy(home, nombre) > 0.3 and home.split()[0].lower() in nombre.lower()) \
                or (away.split()[0].lower() in nombre.lower()):
            objetivo = ev
            break
    if objetivo is None:
        return None
    try:
        jugadores = lc._alineacion_evento(codigo, objetivo['id'])
    except Exception as e:
        logger.warning(f"[vorp] summary {liga}: {e}")
        return None
    out = {'home': [], 'away': []}
    for j in jugadores:
        if j.get('titular') and j.get('jugador'):
            out[j['lado']].append(j['jugador'])
    return out if (out['home'] or out['away']) else None


def ajuste_partido(liga: str, home: str, away: str) -> Dict:
    """Factores λ por lado con fallback estricto + registro para evaluación."""
    lineups = alineacion_hoy(liga, home, away)
    if not lineups:
        return {'aplicado': False,
                'motivo': 'Alineaciones aún no publicadas en ESPN para este '
                          'partido (salen ~1 h antes; la regla es decidir a '
                          '45 min). Modelo base sin modificar.'}
    res_h = evaluar_alineacion(home, lineups.get('home') or [])
    res_a = evaluar_alineacion(away, lineups.get('away') or [])
    if not (res_h['aplicado'] and res_a['aplicado']):
        motivo = res_h.get('motivo') if not res_h['aplicado'] else res_a.get('motivo')
        return {'aplicado': False, 'motivo': motivo}
    out = {'aplicado': True, 'factor_home': res_h['factor'],
           'factor_away': res_a['factor'],
           'ausentes_home': res_h['ausentes_clave'],
           'ausentes_away': res_a['ausentes_clave']}
    try:                                    # registro para la evaluación 2026-27
        log = []
        if os.path.exists(LOG_ARCHIVO):
            with open(LOG_ARCHIVO, encoding='utf-8') as f:
                log = json.load(f)
        log.append({'fecha': pd.Timestamp.today().strftime('%Y-%m-%d'),
                    'liga': liga, 'partido': f'{home} vs {away}', **{
                        k: v for k, v in out.items() if k != 'aplicado'}})
        with open(LOG_ARCHIVO, 'w', encoding='utf-8') as f:
            json.dump(log[-500:], f, ensure_ascii=False)
    except Exception:
        pass
    return out


if __name__ == '__main__':
    import sys
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    liga, home, away = (sys.argv[1:4] + ['mundial', 'Argentina', 'Switzerland'])[:3]
    print(json.dumps(ajuste_partido(liga, home, away), ensure_ascii=False, indent=2))
