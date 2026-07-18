#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Alpha Finder — panel «Apuestas del Día» (v26, spec §4.2).

Recorre los partidos con cuotas vigentes en odds_actuales.json (próximas
48 h), pide la predicción al motor de su liga y evalúa los mercados
disponibles (1X2, O/U 2.5, BTTS, AH ±0.5) con la cuota REAL.

Filtros de élite (spec):
  * probabilidad del modelo para el mercado > 0.70
  * EV > +3 % con la cuota real
  * cuota real > 1.50 (nada de micro-cuotas)

Si el Shadow Booster está adoptado y hay señal para el partido, el pick se
marca con ⚡ y se prioriza. Degradación honesta: si ningún candidato pasa
los filtros, se devuelven los mejores por EV marcados como no-élite; si un
partido no tiene cuota para un mercado, ese mercado no se evalúa (lista
blanca implícita de mercados disponibles).
"""

import json
import logging
import os
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

MIN_PROB = 0.70
MIN_EV = 0.03
MIN_CUOTA = 1.50
HORIZONTE_HORAS = 48


def _mapa_equipo_liga() -> Dict[str, str]:
    from config import LEAGUES
    mapa = {}
    for clave in LEAGUES:
        try:
            with open(f'team_stats_{clave}.json', encoding='utf-8') as f:
                for eq in json.load(f).get('equipos', {}):
                    mapa[eq] = clave
        except Exception:
            continue
    return mapa


def _mercados_del_partido(pred: Dict, o: Dict, home: str, away: str) -> List[Dict]:
    """Evalúa cada mercado con cuota disponible contra el modelo."""
    M = np.array(pred['score_matrix'])
    idx = np.arange(M.shape[0])
    diff = idx[:, None] - idx[None, :]
    total = idx[:, None] + idx[None, :]
    pr = pred['prediction']['probabilities']
    btts = float(M[(idx[:, None] >= 1) & (idx[None, :] >= 1)].sum())
    over25 = float(M[total > 2.5].sum())

    candidatos = []

    def _add(mercado, etiqueta, prob, cuota):
        if not cuota or pd.isna(cuota) or cuota <= 1:
            return
        candidatos.append({'mercado': mercado, 'apuesta': etiqueta,
                           'prob': round(float(prob), 3),
                           'cuota': round(float(cuota), 2),
                           'cuota_justa': round(1 / max(float(prob), 1e-6), 2),
                           'ev': round(float(cuota) * float(prob) - 1, 3)})

    _add('1X2', f'Gana {home}', pr['home'], o.get('odd_home'))
    _add('1X2', 'Empate', pr['draw'], o.get('odd_draw'))
    _add('1X2', f'Gana {away}', pr['away'], o.get('odd_away'))
    _add('Goles', 'Más de 2.5', over25, o.get('odd_over25'))
    _add('Goles', 'Menos de 2.5', 1 - over25, o.get('odd_under25'))
    _add('BTTS', 'Ambos marcan: Sí', btts, o.get('odd_btts_yes'))
    _add('BTTS', 'Ambos marcan: No', 1 - btts, o.get('odd_btts_no'))
    linea = o.get('ah_linea')
    try:
        linea = float(linea)
    except (TypeError, ValueError):
        linea = None
    if linea == -0.5:
        _add('Hándicap', f'{home} −0.5', float(M[diff > 0].sum()), o.get('odd_ah_home'))
        _add('Hándicap', f'{away} +0.5', float(M[diff <= 0].sum()), o.get('odd_ah_away'))
    elif linea == 0.5:
        _add('Hándicap', f'{home} +0.5', float(M[diff >= 0].sum()), o.get('odd_ah_home'))
        _add('Hándicap', f'{away} −0.5', float(M[diff < 0].sum()), o.get('odd_ah_away'))
    return candidatos


def _senales_shadow() -> Dict[str, int]:
    """Señales del Shadow Booster si está adoptado (shadow_senales.json,
    generado por el pipeline cuando el Shadow pasa validación)."""
    try:
        with open('shadow_senales.json', encoding='utf-8') as f:
            return json.load(f).get('senales', {})
    except Exception:
        return {}


def apuestas_del_dia(max_partidos: int = 40) -> Dict:
    """Tarjetas del panel. Devuelve élite + candidatos (degradación honesta)."""
    try:
        with open('odds_actuales.json', encoding='utf-8') as f:
            datos = json.load(f)
    except Exception:
        return {'actualizado': None, 'elite': [], 'candidatos': [],
                'aviso': 'Sin odds_actuales.json — corre el pipeline de cuotas.'}
    cuotas = datos.get('cuotas', {})
    mapa = _mapa_equipo_liga()
    senales = _senales_shadow()

    hoy = pd.Timestamp.today().normalize()
    limite = hoy + pd.Timedelta(hours=HORIZONTE_HORAS)
    motores: Dict[str, object] = {}
    elite, candidatos = [], []
    evaluados = 0
    for mid, o in sorted(cuotas.items()):
        partes = mid.split('_')
        if len(partes) != 3:
            continue
        try:
            fecha = pd.Timestamp(partes[0])
        except ValueError:
            continue
        if not (hoy <= fecha <= limite):
            continue
        home = partes[1].replace('-', ' ')
        away = partes[2].replace('-', ' ')
        liga = mapa.get(home) or mapa.get(away)
        if not liga:
            continue
        if liga not in motores:
            from league_engine import ClubEngine
            motores[liga] = ClubEngine(liga)
        eng = motores[liga]
        if not getattr(eng, 'listo', False) or home not in eng.stats \
                or away not in eng.stats:
            continue
        if evaluados >= max_partidos:
            break
        evaluados += 1
        pred = eng.predecir(home, away)
        if 'error' in pred:
            continue
        shadow = senales.get(mid, 0)
        for c in _mercados_del_partido(pred, o, home, away):
            tarjeta = {
                'partido': f'{home} vs {away}', 'liga': pred.get('liga', liga),
                'fecha': str(fecha.date()), **c,
                'shadow': bool(shadow),
                'valor': ('🟢' if c['ev'] > 0.05 else
                          '🟡' if c['ev'] > 0 else '🔴'),
            }
            if (c['prob'] > MIN_PROB and c['ev'] > MIN_EV
                    and c['cuota'] > MIN_CUOTA):
                elite.append(tarjeta)
            elif c['ev'] > 0:
                candidatos.append(tarjeta)

    orden = lambda t: (-int(t['shadow']), -t['ev'])
    return {'actualizado': datos.get('actualizado'),
            'partidos_evaluados': evaluados,
            'elite': sorted(elite, key=orden),
            'candidatos': sorted(candidatos, key=orden)[:15],
            'aviso': None if elite else
            ('Ningún mercado cumple hoy los filtros de élite (prob >70 %, '
             'EV >+3 %, cuota >1.50) — se muestran los mejores candidatos '
             'con EV positivo.')}


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    r = apuestas_del_dia()
    print(f"evaluados: {r['partidos_evaluados']} · élite: {len(r['elite'])} · "
          f"candidatos: {len(r['candidatos'])}")
    for t in (r['elite'] or r['candidatos'])[:8]:
        print(f"  {t['valor']} {t['fecha']} {t['liga']}: {t['partido']} — "
              f"{t['apuesta']} @ {t['cuota']} (justa {t['cuota_justa']}, "
              f"EV {t['ev']*100:+.1f} %)")
