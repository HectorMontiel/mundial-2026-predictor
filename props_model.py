#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Modelo de PROPS de jugadores — ponches del pitcher abridor (MLB) — v45.

## La vía de datos (alternativa contundente)
`pybaseball` NO está instalado y `historico_mlb.csv` no trae ponches por
pitcher. La solución: la **MLB Stats API pública** (`statsapi.mlb.com`, gratis,
sin clave, sin instalar nada) da los game logs de pitcheo con ponches, batters
faced e innings por juego. Verificado 2026-07-24.

## El modelo (sabermétrico, robusto, interpretable)
Ponches esperados de un abridor contra un rival:

    K_esp = (K/BF del pitcher) · (K% del rival / K% liga) · BF_esperados

  · K/BF del pitcher: su tasa de ponche por bateador enfrentado (temporada).
  · Ajuste de rival: cuánto poncha de más/menos ese equipo (su K% vs la liga).
  · BF_esperados: batters faced por apertura del pitcher (~24 un abridor).
Luego K ~ Poisson(K_esp) → P(over/under la línea de la casa).

Es el enfoque estándar del sector; no se sobreajusta con ML pesado. La
validación compara su error (MAE) contra el baseline «media del pitcher».

## Uso en vivo
`apuestas_props()` cruza los pitchers de las cuotas `pitcher_strikeouts` de
The Odds API con el modelo y devuelve los picks con EV+.
"""

import json
import logging
import os
import time
from typing import Dict, List, Optional

import numpy as np
import requests

logger = logging.getLogger(__name__)

API = 'https://statsapi.mlb.com/api/v1'
ESTADO = os.path.join('modelos', 'props_mlb', 'estado.json')
BF_ABRIDOR = 24.0            # batters faced típicos de un abridor
_UA = {'User-Agent': 'mundial-predictor/1.0'}


def _get(url: str, params: Dict) -> Optional[Dict]:
    for i in range(3):
        try:
            r = requests.get(url, params=params, headers=_UA, timeout=20)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            if i == 2:
                logger.warning(f"[props] {url}: {e}")
            time.sleep(1.0 * (i + 1))
    return None


def _equipos_k(season: int) -> Dict[str, float]:
    """K% por equipo (strikeouts / plate appearances) y media de liga."""
    data = _get(f'{API}/teams/stats', {'stats': 'season', 'group': 'hitting',
                                       'season': season, 'sportId': 1})
    out = {}
    if not data:
        return out
    for s in data.get('stats', [{}])[0].get('splits', []):
        st = s.get('stat', {})
        pa = float(st.get('plateAppearances') or 0)
        so = float(st.get('strikeOuts') or 0)
        nombre = s.get('team', {}).get('name')
        if pa > 0 and nombre:
            out[nombre] = so / pa
    return out


def _pitcher_rate(pid: int, season: int) -> Optional[Dict]:
    """K/BF y BF/apertura de un pitcher en la temporada."""
    data = _get(f'{API}/people/{pid}/stats',
                {'stats': 'season', 'group': 'pitching', 'season': season})
    if not data or not data.get('stats'):
        return None
    sp = data['stats'][0].get('splits', [])
    if not sp:
        return None
    st = sp[0]['stat']
    bf = float(st.get('battersFaced') or 0)
    so = float(st.get('strikeOuts') or 0)
    gs = float(st.get('gamesStarted') or 0)
    if bf < 50 or gs < 3:
        return None
    return {'k_bf': so / bf, 'bf_start': bf / gs}


def _game_logs(pid: int, season: int) -> List[Dict]:
    data = _get(f'{API}/people/{pid}/stats',
                {'stats': 'gameLog', 'group': 'pitching', 'season': season})
    out = []
    if not data or not data.get('stats'):
        return out
    for s in data['stats'][0].get('splits', []):
        st = s.get('stat', {})
        bf = float(st.get('battersFaced') or 0)
        if bf >= 10 and st.get('gamesStarted') in (1, '1'):
            out.append({'fecha': s.get('date'),
                        'k': float(st.get('strikeOuts') or 0), 'bf': bf,
                        'rival': s.get('opponent', {}).get('name')})
    return out


# ---------------------------------------------------------------------------
# Validación de la PREDICCIÓN (no hay cuotas históricas de props → se valida
# que el modelo prediga los ponches mejor que el baseline «media del pitcher»)
# ---------------------------------------------------------------------------
def validar(pitcher_ids: List[int], season_train: int = 2024,
            season_test: int = 2025) -> Dict:
    from scipy.stats import poisson
    kliga_tr = _equipos_k(season_train)
    kliga_te = _equipos_k(season_test)
    media_liga = np.mean(list(kliga_te.values())) if kliga_te else 0.22
    err_modelo, err_base, brier_over, n = [], [], [], 0
    for pid in pitcher_ids:
        rate = _pitcher_rate(pid, season_train)
        if not rate:
            continue
        logs = _game_logs(pid, season_test)
        if len(logs) < 5:
            continue
        base = rate['k_bf'] * rate['bf_start']          # media del pitcher (train)
        for g in logs:
            mult = (kliga_te.get(g['rival'], media_liga) / media_liga) if media_liga else 1.0
            k_esp = rate['k_bf'] * BF_ABRIDOR * mult
            err_modelo.append(abs(k_esp - g['k']))
            err_base.append(abs(base - g['k']))
            # calibración de P(over 5.5) como ejemplo
            p_over = 1 - poisson.cdf(5, k_esp)
            brier_over.append((p_over - (1 if g['k'] > 5.5 else 0)) ** 2)
            n += 1
    if n < 30:
        return {'n': n, 'aviso': 'muestra insuficiente para validar'}
    return {'n': n,
            'mae_modelo': round(float(np.mean(err_modelo)), 3),
            'mae_baseline': round(float(np.mean(err_base)), 3),
            'mejora_pct': round(100 * (1 - np.mean(err_modelo) / np.mean(err_base)), 1),
            'brier_over55': round(float(np.mean(brier_over)), 3)}


def entrenar(pitcher_ids: List[int], season: int = 2025) -> Dict:
    """Guarda las tasas de pitchers y equipos para la inferencia en vivo."""
    equipos = _equipos_k(season)
    media_liga = float(np.mean(list(equipos.values()))) if equipos else 0.22
    pitchers = {}
    for pid in pitcher_ids:
        r = _pitcher_rate(pid, season)
        if r:
            pitchers[str(pid)] = r
    os.makedirs(os.path.dirname(ESTADO), exist_ok=True)
    estado = {'season': season, 'media_liga_k': media_liga,
              'equipos_k': equipos, 'pitchers': pitchers,
              'generado': __import__('pandas').Timestamp.today().strftime('%Y-%m-%d')}
    with open(ESTADO, 'w', encoding='utf-8') as f:
        json.dump(estado, f, ensure_ascii=False)
    logger.info(f"[props] estado: {len(pitchers)} pitchers, {len(equipos)} equipos")
    return estado


def _estado() -> Dict:
    try:
        with open(ESTADO, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def predecir_ponches(pid: int, rival: str) -> Optional[Dict]:
    e = _estado()
    p = (e.get('pitchers') or {}).get(str(pid))
    if not p:
        return None
    ml = e.get('media_liga_k') or 0.22
    mult = (e.get('equipos_k', {}).get(rival, ml) / ml) if ml else 1.0
    k_esp = p['k_bf'] * BF_ABRIDOR * mult
    return {'k_esperado': round(k_esp, 2), 'lambda': k_esp}


if __name__ == '__main__':
    import sys
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    # pitchers de referencia (ids MLB) para validar el enfoque
    IDS = [543037, 605483, 592789, 519242, 605400, 592332, 656605, 668678,
           547943, 605151, 621111, 664285, 656756, 543294, 571578]
    if '--entrenar' in sys.argv:
        print(json.dumps(entrenar(IDS), ensure_ascii=False)[:200])
    else:
        print(json.dumps(validar(IDS), indent=2, ensure_ascii=False))
