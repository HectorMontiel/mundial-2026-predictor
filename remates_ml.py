# -*- coding: utf-8 -*-
"""
v308 — REMATES Y REMATES A PUERTA POR JUGADOR: 1+, 2+, 3+ CON SU PROBABILIDAD.

LO QUE PIDIÓ EL USUARIO
    «Quiero saber cuántos tiros a puerta y cuántos tiros tiene probabilidad
     un jugador: Mbappé, un tiro a puerta, tanto por ciento; dos tiros a
     puerta, tanto por ciento. Y medido con cuotas. La alineación influye: si
     es delantero tiene más; el falso nueve, el nueve, las posiciones…
     tienes que medir tú qué influye.»

LO QUE SE MIDIÓ (`_v308_remates_jugador.py`, `_v308_remates_jugador.json`)
268.420 titulares de 13.421 partidos (FotMob, dos temporadas y media de 14
competiciones de clubes y de las selecciones). El modelo de producción de la
v163 (media propia encogida hacia su posición gruesa, Poisson) contra un
LightGBM con objetivo Poisson y cola binomial negativa. Pérdida logarítmica
en el tramo de JUICIO (30 % final), ajustando sólo con lo anterior:

                         v163      este     ECE v163 → este   p5 mejora
    a puerta 1+       0,5266    0,5151       0,017 → 0,005     +0,0106
    a puerta 2+       0,2161    0,2097       0,005 → 0,003     +0,0057
    a puerta 3+       0,0705    0,0676       0,002 → 0,002     +0,0024
    remates  1+       0,6030    0,5931       0,031 → 0,010     +0,0090
    remates  2+       0,4978    0,4871       0,011 → 0,005     +0,0097
    remates  3+       0,3202    0,3113       0,013 → 0,005     +0,0080
    remates  4+       0,1815    0,1747       0,010 → 0,002     +0,0060

y lo mismo en el tramo de elección: gana en los siete, con p5 > 0 en los dos.

QUÉ MUEVE LA PROBABILIDAD (importancia en el modelo, de más a menos)
el valor de mercado del jugador, lo que CONCEDE el rival, sus minutos
habituales, sus remates por 90, su media reciente, lo que remata su equipo.
Y el puesto del partido, que es lo que el usuario intuía:

    puesto (positionId)    a puerta/partido   P(1+)   P(2+)
    delantero centro           0,78           51 %    19 %
    extremo                    0,47           35 %     9 %
    mediapunta                 0,39           29 %     7 %
    mediocentro                0,24           20 %     3 %
    defensa                    0,14           13 %     1 %

QUÉ ES Y QUÉ NO ES
Es la probabilidad SI ES TITULAR: las apuestas de jugador se hacen con la
alineación publicada, y el modelo se midió sobre titulares. Está calibrada
(ECE ≤ 0,010 en todo). Lo que TODAVÍA no está medido es si apostar donde el
modelo ve más que la casa gana dinero: no había histórico de cuotas de
jugador. Desde la v308 `lineas_jugador` guarda cada precio de la escalera y
lo liquida con el resultado real, así que ese número llegará.

Uso:
    python remates_ml.py --entrenar      # con el fondo `_v308_fondo`
"""
from __future__ import annotations

import json
import logging
import math
import os
import sys
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

DIR = 'modelos'
META = os.path.join(DIR, 'remates_ml.json')
MODELO = {'sot': os.path.join(DIR, 'remates_ml_sot.txt'),
          'sh': os.path.join(DIR, 'remates_ml_sh.txt')}
RASGOS = ['m_sot', 'm_sh', 'm_min', 'apar', 'tits', 'por90_sh',
          'por90_sot', 'linea', 'carril', 'up', 'lam_eq_sh', 'lam_eq_sot',
          'local', 'log_mv', 'r_tiros_c', 'r_sot_c', 'eq_tiros', 'eq_sot']
VENT = 10
R_SUPLENTE = 0.48          # un suplente remata el 48 % de lo de un titular
UMBRALES = {'sot': (1, 2, 3), 'sh': (1, 2, 3, 4, 5)}

_CACHE: Dict = {}


# ---------------------------------------------------------------------------
# entrenamiento
# ---------------------------------------------------------------------------
def entrenar() -> Dict:
    import lightgbm as lgb
    import _v308_remates_jugador as mr
    d, e = mr.cargar()
    d = mr.rasgos(d, e)
    tit = d[(d['t'] == 1) & d['lam_eq_sh'].notna() & d['lam_eq_sot'].notna()
            & (d['rol'] != 'POR')].copy()
    os.makedirs(DIR, exist_ok=True)
    meta = {'n_titulares': int(len(tit)), 'partidos': int(tit['mid'].nunique()),
            'hasta': str(tit['fecha'].max().date()), 'rasgos': RASGOS,
            'alpha': {}}
    for col in ('sot', 'sh'):
        m = lgb.LGBMRegressor(objective='poisson', n_estimators=400,
                              learning_rate=0.03, num_leaves=31,
                              min_child_samples=100, subsample=0.8,
                              subsample_freq=1, colsample_bytree=0.8,
                              verbose=-1)
        m.fit(tit[RASGOS].astype(float), tit[col])
        m.booster_.save_model(MODELO[col])
        lam = m.predict(tit[RASGOS].astype(float))
        meta['alpha'][col] = round(mr.alpha_mm(tit[col], lam), 5)
    try:
        with open('_v308_remates_jugador.json', encoding='utf-8') as f:
            med = json.load(f)
        meta['medicion'] = {c: {t: {k: v.get('M2') for k, v in
                                    med[c][t].items() if k.endswith('+')}
                                for t in ('eleccion', 'juicio')}
                            for c in ('sot', 'sh')}
        meta['por_rol'] = med.get('por_rol')
    except Exception:
        pass
    with open(META, 'w', encoding='utf-8') as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    return meta


# ---------------------------------------------------------------------------
# predicción
# ---------------------------------------------------------------------------
def _modelos():
    if 'mod' not in _CACHE:
        try:
            import lightgbm as lgb
            with open(META, encoding='utf-8') as f:
                meta = json.load(f)
            _CACHE['mod'] = ({c: lgb.Booster(model_file=MODELO[c])
                              for c in MODELO}, meta)
        except Exception as e:
            logger.debug('[remates_ml] sin modelo: %s', e)
            _CACHE['mod'] = None
    return _CACHE['mod']


def disponible() -> bool:
    return _modelos() is not None


def p_al_menos(lam: float, k: int, alpha: float = 0.0) -> float:
    """P(X ≥ k) con Poisson o, si alpha > 0, binomial negativa
    (var = λ + α·λ²)."""
    lam = max(float(lam), 1e-6)
    if k <= 0:
        return 1.0
    if alpha <= 1e-6:
        acc, term = 0.0, math.exp(-lam)
        for i in range(k):
            acc += term
            term *= lam / (i + 1)
        return max(0.0, min(1.0, 1.0 - acc))
    r = 1.0 / alpha
    p = r / (r + lam)
    # P(X=i) = C(i+r-1, i) p^r (1-p)^i
    acc = 0.0
    for i in range(k):
        acc += math.exp(math.lgamma(i + r) - math.lgamma(r)
                        - math.lgamma(i + 1) + r * math.log(p)
                        + i * math.log(1 - p))
    return max(0.0, min(1.0, 1.0 - acc))


def _media(serie) -> Optional[float]:
    import pandas as pd
    s = pd.to_numeric(serie, errors='coerce').dropna()
    return float(s.mean()) if len(s) else None


def contexto_equipo(clave_liga: str, equipo: str, rival: str) -> Dict:
    """Lo que tira el equipo y lo que concede el rival, de sus 10 últimos
    (los mismos rasgos con los que se entrenó)."""
    import remates_fotmob as rf
    d = rf._equipos_df()
    if d.empty:
        return {}
    cand = rf._candidatos(d, clave_liga)
    eq = rf._resolver_equipo(equipo, cand)
    rv = rf._resolver_equipo(rival, cand)
    fuera = {}
    if eq:
        s = d[d['equipo'] == eq].sort_values('fecha').tail(VENT)
        if len(s) >= 3:
            fuera['eq_tiros'] = _media(s['tiros'])
            fuera['eq_sot'] = _media(s['a_puerta'])
        fuera['equipo_fm'] = eq
    if rv:
        s = d[d['equipo'] == rv].sort_values('fecha').tail(VENT)
        contra = d[d['match_id'].isin(s['match_id']) & (d['equipo'] != rv)]
        if len(contra) >= 3:
            fuera['r_tiros_c'] = _media(contra['tiros'])
            fuera['r_sot_c'] = _media(contra['a_puerta'])
    if all(fuera.get(k) is not None for k in ('eq_tiros', 'r_tiros_c')):
        fuera['lam_eq_sh'] = (fuera['eq_tiros'] + fuera['r_tiros_c']) / 2
    if all(fuera.get(k) is not None for k in ('eq_sot', 'r_sot_c')):
        fuera['lam_eq_sot'] = (fuera['eq_sot'] + fuera['r_sot_c']) / 2
    return fuera


def rasgos_jugadores(clave_liga: str, equipo: str, rival: str, local: bool,
                     puestos_hoy: Optional[Dict[str, int]] = None) -> List[Dict]:
    """Los rasgos de cada jugador del equipo con historia en FotMob.

    `puestos_hoy` es {jugador: positionId} de la alineación publicada, si la
    hay; si no, se usa el puesto de su última titularidad."""
    import numpy as np
    import remates_fotmob as rf
    ctx = contexto_equipo(clave_liga, equipo, rival)
    if 'lam_eq_sh' not in ctx or 'lam_eq_sot' not in ctx:
        return []
    dj = rf._jugadores()
    s = dj[dj['equipo'] == ctx.get('equipo_fm')].sort_values('fecha')
    if s.empty:
        return []
    fuera = []
    for jid, g in s.groupby('jugador_id'):
        g = g.tail(VENT)
        apar = float(len(g))
        tits = float(g['titular'].sum())
        den_sot = tits + R_SUPLENTE * (apar - tits)
        tot_min = float(g['minutos'].sum())
        ult = g.iloc[-1]
        pos = None
        nombre = str(ult['jugador'])
        if puestos_hoy:
            pos = puestos_hoy.get(nombre)
        if pos is None:
            t = g[g['titular'] == 1]
            if 'pos' in g and len(t):
                pos = t['pos'].dropna().iloc[-1] if t['pos'].notna().any() \
                    else None
        up = ult.get('up') if 'up' in g else None
        mv = g['mv'].dropna().iloc[-1] if 'mv' in g and g['mv'].notna().any() \
            else None
        try:
            pos = float(pos) if pos is not None else float('nan')
        except (TypeError, ValueError):
            pos = float('nan')
        fuera.append({
            'jugador': nombre, 'jugador_id': jid,
            'posicion': str(ult.get('posicion') or ''),
            'm_sot': float(g['a_puerta'].sum()) / den_sot if den_sot else None,
            'm_sh': float(g['tiros'].sum()) / den_sot if den_sot else None,
            'm_min': tot_min / apar if apar else None,
            'apar': apar, 'tits': tits,
            'por90_sh': 90 * float(g['tiros'].sum()) / tot_min if tot_min else None,
            'por90_sot': 90 * float(g['a_puerta'].sum()) / tot_min
            if tot_min else None,
            'linea': math.floor(pos / 10) if pos == pos else float('nan'),
            'carril': abs(pos % 10 - 5) if pos == pos else float('nan'),
            'up': float(up) if up is not None and up == up else float('nan'),
            'local': float(bool(local)),
            'log_mv': float(np.log1p(float(mv))) if mv is not None else 0.0,
            **{k: ctx[k] for k in ('lam_eq_sh', 'lam_eq_sot', 'r_tiros_c',
                                   'r_sot_c', 'eq_tiros', 'eq_sot')}})
    return fuera


def predecir(filas: List[Dict]) -> List[Dict]:
    """Añade a cada fila λ y la escalera de probabilidades (si es titular)."""
    mods = _modelos()
    if not mods or not filas:
        return []
    import numpy as np
    boosters, meta = mods
    X = np.array([[np.nan if f.get(c) is None else float(f.get(c))
                   for c in RASGOS] for f in filas], dtype=float)
    lam = {c: boosters[c].predict(X) for c in boosters}
    alpha = meta.get('alpha') or {}
    fuera = []
    for i, f in enumerate(filas):
        g = dict(f)
        for c in ('sot', 'sh'):
            l = float(lam[c][i])
            g['lam_' + c] = round(l, 3)
            g['p_' + c] = {k: round(p_al_menos(l, k, float(alpha.get(c, 0))), 4)
                           for k in UMBRALES[c]}
        fuera.append(g)
    return fuera


def escalera_equipo(clave_liga: str, equipo: str, rival: str, local: bool,
                    puestos_hoy: Optional[Dict[str, int]] = None) -> List[Dict]:
    """Los jugadores del equipo, de más a menos probabilidad de rematar a
    puerta, con toda su escalera. [] si falta algo."""
    try:
        filas = predecir(rasgos_jugadores(clave_liga, equipo, rival, local,
                                          puestos_hoy))
    except Exception as e:
        logger.debug('[remates_ml] %s: %s', equipo, e)
        return []
    filas.sort(key=lambda x: -x['lam_sot'])
    return filas


def main() -> int:
    sys.stdout.reconfigure(encoding='utf-8')
    logging.basicConfig(level=logging.INFO)
    if '--entrenar' in sys.argv:
        print(json.dumps(entrenar(), ensure_ascii=False, indent=1)[:2000])
    return 0


if __name__ == '__main__':
    sys.exit(main())
