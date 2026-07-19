#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Arbitraje de Mercado Cruzado — EV sintético (v27 §4).

VERIFICADO 2026-07-18: la capa gratuita de The Odds API NO expone los
compuestos pre-empaquetados (result+btts / result+totals devuelven 422,
INVALID_MARKET). SÍ expone, POR EVENTO, mercados derivados donde las casas
cargan overround alto y que nosotros valoramos EXACTAMENTE con la matriz de
marcadores del motor:

    double_chance · draw_no_bet · alternate_totals · team_totals · h2h_h1*

(*h2h_h1 exigiría el modelo de mitades — fuera de esta versión.)

Señal: cuota_casa > cuota_justa × 1.05 (margen de seguridad del 5 %, spec).
Presupuesto: 1 request POR evento — tope MAX_EVENTOS por corrida, eventos
más próximos primero. Sin clave o sin eventos → lista vacía con aviso.
"""

import json
import logging
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

import odds_api

logger = logging.getLogger(__name__)

MARGEN = 1.05
MAX_EVENTOS = 5
MERCADOS = 'double_chance,draw_no_bet,alternate_totals,team_totals'
# v28 (§2.2) — índice VACA: ν = EV% / (entropías de resultados NORMALIZADAS
# de ambos equipos + 0.1). Adaptación de escala documentada: con la fórmula
# literal del spec (entropías en bits, EV como fracción) ν jamás superaría
# 1.0; normalizando la entropía a [0,1] (÷log₂3) y el EV a %, el umbral 1.0
# discrimina como se pretende (EV 5 % con entropías medias ~1.7 → ν≈2.9;
# EV 1.5 % con equipos caóticos → ν≈0.7, filtrado).
VACA_UMBRAL = 1.0
CACHE_ARB = 'arbitraje_cache.json'


def _entropia_norm(eng, equipo: str) -> float:
    import features_v26 as f26
    try:
        res = (eng.estado_v26 or {}).get(equipo, {}).get('res') or []
        return f26._entropia(res[-6:]) / np.log2(3) if len(res) >= 4 else 0.8
    except Exception:
        return 0.8


def _prob_mercado(M: np.ndarray, mkey: str, o: Dict, home: str, away: str
                  ) -> Optional[float]:
    """Probabilidad del outcome `o` según la matriz M (defensivo)."""
    idx = np.arange(M.shape[0])
    diff = idx[:, None] - idx[None, :]
    total = idx[:, None] + idx[None, :]
    nombre = str(o.get('name', ''))
    punto = o.get('point')
    desc = str(o.get('description', ''))
    p1 = float(M[diff > 0].sum())
    px = float(M[diff == 0].sum())
    p2 = float(M[diff < 0].sum())
    if mkey == 'double_chance':
        tiene_h = home.lower() in nombre.lower()
        tiene_a = away.lower() in nombre.lower()
        tiene_x = 'draw' in nombre.lower()
        if tiene_h and tiene_x:
            return p1 + px
        if tiene_a and tiene_x:
            return p2 + px
        if tiene_h and tiene_a:
            return p1 + p2
        return None
    if mkey == 'draw_no_bet':
        if home.lower() in nombre.lower():
            return p1 / max(p1 + p2, 1e-9)
        if away.lower() in nombre.lower():
            return p2 / max(p1 + p2, 1e-9)
        return None
    # líneas ENTERAS (1.0, 2.0…) tienen PUSH (reembolso en el total exacto)
    # y la prob binaria las sobrevalora → solo se valoran líneas .5
    def _linea_limpia(p):
        return p is not None and abs(float(p) % 1 - 0.5) < 1e-6
    if mkey == 'alternate_totals' and _linea_limpia(punto):
        p_over = float(M[total > float(punto)].sum())
        return p_over if nombre.lower().startswith('over') else 1 - p_over
    if mkey == 'team_totals' and _linea_limpia(punto):
        gv = M.sum(axis=0) if away.lower() in desc.lower() else M.sum(axis=1)
        p_over = float(gv[np.arange(len(gv)) > float(punto)].sum())
        return p_over if nombre.lower().startswith('over') else 1 - p_over
    return None


def analizar(max_eventos: int = MAX_EVENTOS) -> Dict:
    """Barrido de oportunidades en los eventos más próximos con motor."""
    import requests
    from league_engine import ClubEngine
    k = odds_api._clave()
    if not k:
        return {'oportunidades': [], 'aviso': 'Sin ODDS_API_KEY.'}
    mapa = {}
    from config import LEAGUES
    for clave in LEAGUES:
        try:
            with open(f'team_stats_{clave}.json', encoding='utf-8') as f:
                for eq in json.load(f).get('equipos', {}):
                    mapa[eq] = clave
        except Exception:
            continue

    # eventos próximos por liga (reusa la lista del snapshot h2h del día)
    eventos = []
    for clave_liga, sport in odds_api.SPORT_KEYS.items():
        if clave_liga == 'mundial':
            continue
        try:
            r = requests.get(f"{odds_api.BASE}/sports/{sport}/events",
                             params={'apiKey': k}, timeout=20)
            if not r.ok:
                continue
            for ev in r.json():
                h = odds_api._normalizar_nombre(clave_liga, ev['home_team'])
                a = odds_api._normalizar_nombre(clave_liga, ev['away_team'])
                if mapa.get(h) == clave_liga and mapa.get(a) == clave_liga:
                    eventos.append((ev['commence_time'], clave_liga, sport,
                                    ev['id'], h, a))
        except Exception:
            continue
        if len(eventos) >= max_eventos * 3:
            break
    eventos.sort()
    eventos = eventos[:max_eventos]

    motores, oportunidades, evaluados = {}, [], 0
    for inicio, clave_liga, sport, eid, home, away in eventos:
        if clave_liga not in motores:
            motores[clave_liga] = ClubEngine(clave_liga)
        eng = motores[clave_liga]
        if not eng.listo:
            continue
        pred = eng.predecir(home, away)
        if 'error' in pred:
            continue
        M = np.array(pred['score_matrix'])
        if not odds_api._presupuesto_disponible():
            break
        odds_api._consumir_request()
        try:
            r = requests.get(f"{odds_api.BASE}/sports/{sport}/events/{eid}/odds",
                             params={'apiKey': k, 'regions': 'eu',
                                     'markets': MERCADOS,
                                     'oddsFormat': 'decimal'}, timeout=30)
            r.raise_for_status()
        except Exception as e:
            logger.warning(f"[arb] {home}-{away}: {e}")
            continue
        evaluados += 1
        for casa in (r.json().get('bookmakers') or [])[:2]:
            for m in casa.get('markets', []):
                for o in m.get('outcomes', []):
                    p = _prob_mercado(M, m['key'], o, home, away)
                    if p is None or not (0.02 < p < 0.98):
                        continue
                    justa = 1.0 / p
                    cuota = float(o.get('price', 0))
                    if cuota > justa * MARGEN:
                        ev_sint = (cuota - justa) / justa * 100
                        vaca = round(ev_sint / (_entropia_norm(eng, home)
                                                + _entropia_norm(eng, away)
                                                + 0.1), 2)
                        oportunidades.append({
                            'vaca': vaca,
                            'partido': f'{home} vs {away}',
                            'liga': clave_liga, 'inicio': inicio,
                            'casa': casa.get('title', '?'),
                            'mercado': m['key'],
                            'apuesta': (o.get('description', '') + ' '
                                        + o['name']
                                        + (f" {o['point']}" if o.get('point')
                                           is not None else '')).strip(),
                            'cuota_casa': round(cuota, 2),
                            'cuota_justa': round(justa, 2),
                            'prob_modelo': round(p, 3),
                            'ev_pct': round((cuota * p - 1) * 100, 1)})
    # v28: filtro VACA (solo ν > umbral) y orden por ν descendente
    filtradas = sorted([o for o in oportunidades if o['vaca'] > VACA_UMBRAL],
                       key=lambda x: -x['vaca'])
    salida = {'oportunidades': filtradas,
              'descartadas_por_vaca': len(oportunidades) - len(filtradas),
              'eventos_evaluados': evaluados,
              'generado': pd.Timestamp.today().strftime('%Y-%m-%d %H:%M'),
              'aviso': None if filtradas else
              ('Sin oportunidades estables (ν > 1) en los eventos evaluados.')}
    try:        # caché para el EVC Platino (alpha_finder) y auditoría
        with open(CACHE_ARB, 'w', encoding='utf-8') as f:
            json.dump(salida, f, ensure_ascii=False)
    except Exception:
        pass
    return salida


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    import warnings
    warnings.filterwarnings('ignore')
    r = analizar()
    print(f"eventos: {r['eventos_evaluados']} · oportunidades: "
          f"{len(r['oportunidades'])}")
    for op in r['oportunidades'][:8]:
        print(f"  {op['liga']} {op['partido']} — {op['mercado']}: "
              f"{op['apuesta']} @ {op['cuota_casa']} (justa {op['cuota_justa']}, "
              f"EV {op['ev_pct']:+.1f} %) [{op['casa']}]")
