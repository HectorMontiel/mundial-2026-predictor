#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Constructor de parlays inteligente (Mejora 3, v12).

Genera el mejor parlay de N selecciones combinando los mercados del fixture:
  1. Candidatos: apuestas con probabilidad del modelo ≥ prob_min y cuota ≥ 1.10.
  2. Cuotas: reales de odds_historicas.csv / The Odds API si existen; si no,
     cuotas JUSTAS implícitas del modelo (1/p) — en ese caso el EV es 0 por
     construcción y el parlay es PURAMENTE INFORMATIVO (se etiqueta así).
  3. Control de correlación: máximo 2 selecciones por partido y nunca dos del
     mismo grupo de mercados dependientes (p. ej. "gana X" + "X +0.5");
     a los pares del mismo partido se les aplica un recorte de probabilidad
     conjunta (haircut 0.95) por la correlación residual.
  4. Límite de cuota combinada: 1000. Diversificación entre mercados.
"""

import itertools
import os
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

# Grupos de mercados dependientes dentro del MISMO partido: no se combinan
GRUPOS_DEPENDIENTES = {
    'resultado': {'1x2', 'doble_oportunidad', 'handicap'},
    'goles': {'over_under', 'btts'},
    'corners': {'corners'},
    'tarjetas': {'tarjetas'},
}
HAIRCUT_MISMO_PARTIDO = 0.95
CUOTA_MAXIMA_TOTAL = 1000.0


def _grupo(mercado: str) -> str:
    for g, ms in GRUPOS_DEPENDIENTES.items():
        if mercado in ms:
            return g
    return mercado


def _cuotas_reales() -> Dict[str, Dict]:
    """Cuotas 1X2 reales: snapshot vigente (odds_actuales.json) + histórico."""
    cuotas: Dict[str, Dict] = {}
    if os.path.exists('odds_historicas.csv'):
        try:
            df = pd.read_csv('odds_historicas.csv')
            cuotas.update({r.MATCH_ID: {'home': r.odd_home, 'draw': r.odd_draw,
                                        'away': r.odd_away} for r in df.itertuples()})
        except Exception:
            pass
    if os.path.exists('odds_actuales.json'):
        try:
            import json
            with open('odds_actuales.json', 'r', encoding='utf-8') as f:
                actuales = json.load(f).get('cuotas', {})
            for mid, o in actuales.items():
                cuotas[mid] = {'home': o.get('odd_home'), 'draw': o.get('odd_draw'),
                               'away': o.get('odd_away')}
        except Exception:
            pass
    return cuotas


def _risk_flags() -> Dict[str, str]:
    """Niveles de riesgo por cruce generados por market_intelligence (M4)."""
    if not os.path.exists('risk_flags.json'):
        return {}
    try:
        import json
        with open('risk_flags.json', 'r', encoding='utf-8') as f:
            return json.load(f).get('flags', {})
    except Exception:
        return {}


def _candidatos_del_partido(engine, home: str, away: str, prob_min: float) -> List[Dict]:
    """Todas las apuestas candidatas de un cruce con su prob y cuota."""
    pred = engine.predecir(home, away)
    if 'error' in pred:
        return []
    dist = engine.distribuciones(home, away)
    p = pred['prediction']['probabilities']
    nl = pred['match'].split(' vs ')[0]
    na = pred['match'].split(' vs ')[1]
    partido = f"{home}-{away}"

    velas: List[Dict] = []

    def añadir(mercado, etiqueta, prob):
        if prob_min <= prob <= 0.909:   # cuota justa >= 1.10
            velas.append({'partido': partido, 'mercado': mercado,
                          'apuesta': etiqueta, 'prob': round(float(prob), 4)})

    # 1X2 y doble oportunidad
    ganador = max(('home', 'draw', 'away'), key=lambda k: p[k])
    nombres = {'home': f'Gana {nl}', 'draw': 'Empate', 'away': f'Gana {na}'}
    añadir('1x2', nombres[ganador], p[ganador])
    añadir('doble_oportunidad', f'{nl} o Empate', p['home'] + p['draw'])
    añadir('doble_oportunidad', f'{na} o Empate', p['away'] + p['draw'])

    # Over/Under y BTTS desde las distribuciones exactas
    m = dist['mercados']
    ov25 = m['goles_totales']['over_2.5'] / 100
    añadir('over_under', 'Más de 2.5 goles', ov25)
    añadir('over_under', 'Menos de 2.5 goles', 1 - ov25)
    ov15 = m['goles_totales']['over_1.5'] / 100
    añadir('over_under', 'Más de 1.5 goles', ov15)
    M = np.array(pred['score_matrix'])
    i = np.arange(M.shape[0])
    btts = float(M[(i[:, None] >= 1) & (i[None, :] >= 1)].sum())
    añadir('btts', 'Ambos marcan: Sí', btts)
    añadir('btts', 'Ambos marcan: No', 1 - btts)

    # Córners y tarjetas (líneas centrales)
    añadir('corners', 'Más de 7.5 córners', m['corners_totales']['over_7.5'] / 100)
    añadir('corners', 'Menos de 9.5 córners', 1 - m['corners_totales']['over_9.5'] / 100)
    añadir('tarjetas', 'Menos de 5.5 tarjetas', 1 - m['tarjetas_totales']['over_5.5'] / 100)
    añadir('tarjetas', 'Más de 2.5 tarjetas', m['tarjetas_totales']['over_2.5'] / 100)

    # Cuotas: reales si existen (solo 1X2 disponible en odds_historicas)
    reales = _cuotas_reales()
    for v in velas:
        v['cuota'] = round(1.0 / v['prob'], 3)   # cuota justa del modelo
        v['cuota_fuente'] = 'modelo (justa)'
        for mid, odds in reales.items():
            if home in mid and away in mid and v['mercado'] == '1x2':
                clave = {f'Gana {nl}': 'home', 'Empate': 'draw', f'Gana {na}': 'away'}.get(v['apuesta'])
                if clave and odds.get(clave):
                    v['cuota'] = float(odds[clave])
                    v['cuota_fuente'] = 'mercado'
        v['ev'] = round(v['cuota'] * v['prob'] - 1, 4)
    return velas


def construir_parlay(engine, n_legs: int = 8, prob_min: float = 0.55,
                     partidos: Optional[List] = None, ev_min: float = 0.0,
                     filtrar_riesgo: bool = True) -> Dict:
    """
    Selecciona el mejor parlay del fixture con control de correlación.
    v13: excluye selecciones de partidos con riesgo 🔴 (risk_flags.json de la
    inteligencia de mercado) y, con cuotas REALES, aplica el filtro ev_min.
    """
    if partidos is None:
        cal = engine.calendario
        partidos = [(r['home'], r['away']) for _, r in cal.iterrows()] if len(cal) else []
    if not partidos:
        return {'error': 'Sin partidos en el fixture para construir el parlay.'}

    flags = _risk_flags() if filtrar_riesgo else {}
    excluidos_riesgo = []
    candidatos: List[Dict] = []
    for home, away in partidos:
        riesgo = flags.get(f"{home}|{away}") or flags.get(f"{away}|{home}") or 'bajo'
        if riesgo == 'alto':
            excluidos_riesgo.append(f"{home}-{away}")
            continue
        try:
            legs = _candidatos_del_partido(engine, home, away, prob_min)
            for l in legs:
                l['riesgo'] = riesgo
            candidatos.extend(legs)
        except Exception:
            continue
    if not candidatos:
        return {'error': f'Ningún mercado supera el umbral de probabilidad ({prob_min:.0%}).'}

    con_mercado = any(c['cuota_fuente'] == 'mercado' for c in candidatos)
    if con_mercado and ev_min > 0:
        candidatos = [c for c in candidatos
                      if c['cuota_fuente'] != 'mercado' or c['ev'] >= ev_min]
    # Orden: EV con cuotas reales; probabilidad si solo hay cuotas justas
    candidatos.sort(key=lambda c: (c['ev'], c['prob']), reverse=True)

    seleccion: List[Dict] = []
    grupos_usados = set()          # (partido, grupo) para evitar dependencias
    conteo_partido: Dict[str, int] = {}
    for c in candidatos:
        if len(seleccion) >= n_legs:
            break
        clave_grupo = (c['partido'], _grupo(c['mercado']))
        if clave_grupo in grupos_usados:
            continue
        if conteo_partido.get(c['partido'], 0) >= 2:
            continue
        cuota_acum = float(np.prod([s['cuota'] for s in seleccion])) * c['cuota']
        if cuota_acum > CUOTA_MAXIMA_TOTAL:
            continue
        seleccion.append(c)
        grupos_usados.add(clave_grupo)
        conteo_partido[c['partido']] = conteo_partido.get(c['partido'], 0) + 1

    if not seleccion:
        return {'error': 'No fue posible componer un parlay con las restricciones.'}

    cuota_total = float(np.prod([s['cuota'] for s in seleccion]))
    prob_conjunta = float(np.prod([s['prob'] for s in seleccion]))
    pares_mismo_partido = sum(1 for p, n in conteo_partido.items() if n >= 2)
    prob_conjunta *= HAIRCUT_MISMO_PARTIDO ** pares_mismo_partido
    orden_riesgo = {'bajo': 0, 'medio': 1, 'alto': 2}
    riesgo_parlay = max((s.get('riesgo', 'bajo') for s in seleccion),
                        key=lambda r: orden_riesgo[r])
    return {
        'selecciones': seleccion,
        'n_legs': len(seleccion),
        'cuota_combinada': round(cuota_total, 2),
        'prob_conjunta': round(prob_conjunta, 4),
        'ev_parlay': round(cuota_total * prob_conjunta - 1, 4),
        'cuotas_reales': con_mercado,
        'riesgo_parlay': riesgo_parlay,
        'partidos_excluidos_por_riesgo': excluidos_riesgo,
        'nota': ('Cuotas de mercado (The Odds API)' if con_mercado else
                 'EV teórico (basado en cuotas justas del modelo) — NO accionable; '
                 'compara contra las cuotas de tu casa para encontrar valor.'),
    }
