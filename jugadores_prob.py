# -*- coding: utf-8 -*-
"""
v469 — QUÉ JUGADOR PUEDE ANOTAR Y QUIÉN PUEDE TIRAR A PUERTA 1+ / 2+ VECES.

El usuario: «quiero que me des porcentaje de qué jugador puede meter gol y qué jugador puede tirar
a puerta más de una o dos veces; dentro del análisis de la IA».

Con la base propia de FotMob (`remates_fotmob_jugadores.csv`: minutos, tiros a puerta, goles y xG
de cada jugador en cada partido) y SÓLO lo que se sabe antes del partido:
  · candidatos: los que jugaron alguno de los 5 partidos anteriores de su equipo;
  · minutos esperados: su media en esos 5 (0 si no jugó: así cuenta que puede no salir);
  · tasa por 90': lo suyo en los últimos 15 partidos con una previa de su posición (3 partidos);
  · el rival: lo que concede (tiros a puerta, xG) frente a la media de su liga;
  · goles: 75 % xG + 25 % goles (en las ligas sin xG, sólo goles); conteo binomial negativo.
Y al final la CALIBRACIÓN isotónica medida (`jugadores_calibracion.json`).

MEDIDO (D:/Claude/mediciones/medir_jugadores.py, 121.483 jugador-partido de mar-oct 2026, calibrado
en una mitad y medido en la otra, y al revés): anota, a puerta 1+ y a puerta 2+ ganan a la media de
su posición en las dos mitades con p5 > 0 y quedan calibrados (1-3 pts por tramo). A puerta 3+ no
gana: no se enseña. Es información, no un pick.
"""
from __future__ import annotations

import collections
import json
import logging
import os
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

HIST = 'remates_fotmob_jugadores.csv'
CAL = 'jugadores_calibracion.json'
K = 3.0
VENT = 15
ALPHA = 0.3
POR_EQUIPO = 4
_MEM: Dict = {}


def _p_ge(lam: float, k: int, alpha: float = ALPHA) -> float:
    """P(X >= k) binomial negativa (varianza lam + alpha·lam²)."""
    if lam <= 0:
        return 0.0
    r = 1 / alpha
    pp = r / (r + lam)
    acc, t = 0.0, pp ** r
    for i in range(k):
        acc += t
        t = t * (r + i) / (i + 1) * (1 - pp)
    return max(0.0, 1 - acc)


def _cal(nombre: str, p: float) -> float:
    import numpy as np
    c = _MEM.get('cal')
    if c is None:
        try:
            c = json.load(open(CAL, encoding='utf-8'))
        except Exception:
            c = {}
        _MEM['cal'] = c
    t = c.get(nombre)
    return float(np.interp(p, t['x'], t['y'])) if t else p


def _datos():
    """La base cargada una vez por proceso: filas por equipo, partidos por equipo y previas."""
    if 'df' in _MEM:
        return _MEM['df']
    import pandas as pd
    df = pd.read_csv(HIST, usecols=['match_id', 'fecha', 'liga', 'equipo', 'jugador', 'jugador_id', 'posicion',
                                    'minutos', 'a_puerta', 'goles', 'xg'])
    df['posicion'] = df.posicion.fillna('M').astype(str).str[0]
    # el femenil del Atlético también se llama «Atlético Madrid» en la base: se separan (si no, sus
    # partidos se mezclan y los minutos de todos se van a la mitad)
    fem = df.liga.astype(str).str.startswith('fem_') | df.liga.astype(str).str.contains('femenil')
    df['equipo'] = df.equipo.astype(str) + fem.map({True: '|F', False: ''})
    df = df.sort_values('fecha')
    conxg = set(df.groupby('liga').xg.sum().pipe(lambda x: x[x > 0]).index)
    pos = df[(df.minutos > 0) & df.liga.isin(conxg)].groupby('posicion').agg(m=('minutos', 'sum'), s=('a_puerta', 'sum'),
                                                                               x=('xg', 'sum'), g=('goles', 'sum'))
    prev = {p: (r.s / (r.m / 90), r.x / (r.m / 90), r.g / (r.m / 90)) for p, r in pos.iterrows()}
    part = df.groupby(['match_id', 'equipo']).agg(fecha=('fecha', 'first'), liga=('liga', 'first'),
                                                  sot=('a_puerta', 'sum'), xg=('xg', 'sum')).reset_index()
    riv = part.merge(part[['match_id', 'equipo', 'sot', 'xg']], on='match_id', suffixes=('', '_r'))
    riv = riv[riv.equipo != riv.equipo_r].sort_values('fecha')
    conc = {e: list(zip(g.sot_r, g.xg_r)) for e, g in riv.groupby('equipo')}       # lo que le tiraron
    liga = {l: list(zip(g.sot, g.xg)) for l, g in riv.groupby('liga')}
    d = {'df': df, 'eq': {e: g for e, g in df.groupby('equipo')}, 'conxg': conxg, 'prev': prev,
         'conc': conc, 'liga': liga, 'liga_eq': part.groupby('equipo').liga.last().to_dict()}
    _MEM['df'] = d
    return d


def _factor(d: Dict, rival: str, liga: str) -> tuple:
    """Lo que concede el rival (últimos 10) frente a la media de su liga, encogido con 3."""
    import numpy as np
    c, lm = d['conc'].get(rival) or [], d['liga'].get(liga) or []
    if len(c) < 3 or len(lm) < 30:
        return 1.0, 1.0
    m_s, m_x = np.mean([x[0] for x in lm[-400:]]), np.mean([x[1] for x in lm[-400:]])
    c = c[-10:]
    fs = (sum(x[0] for x in c) + 3 * m_s) / (len(c) + 3) / m_s if m_s > 0 else 1.0
    fx = (sum(x[1] for x in c) + 3 * m_x) / (len(c) + 3) / m_x if m_x > 0 else 1.0
    return (fs if np.isfinite(fs) else 1.0), (fx if np.isfinite(fx) else 1.0)


def clave(nombre: str, femenil: bool) -> str:
    """El equipo en la base: su nombre de FotMob (sin el «(W)» de la lista del día) y «|F» si es femenil."""
    n = str(nombre or '').replace(' (W)', '').strip()
    return n + ('|F' if femenil else '')


def equipo(nombre: str, rival: str) -> List[Dict]:
    """Los jugadores de `nombre` (su `clave`) contra `rival`, con sus probabilidades
    calibradas; los POR_EQUIPO más probables de anotar. [] si no está en la base."""
    d = _datos()
    g = d['eq'].get(nombre)
    if g is None or not len(g):
        return []
    ms = list(dict.fromkeys(g.match_id))
    if len(ms) < 5:
        return []
    ult5 = g[g.match_id.isin(ms[-5:])]
    ultv = g[g.match_id.isin(ms[-VENT:]) & (g.minutos > 0)]
    liga = d['liga_eq'].get(nombre)
    fs, fx = _factor(d, rival, liga)
    out = []
    for j, h5 in ult5[ult5.minutos > 0].groupby('jugador_id'):
        emin = g[g.match_id.isin(ms[-5:]) & (g.jugador_id == j)].minutos.sum() / 5.0
        hv = ultv[ultv.jugador_id == j]
        p = hv.posicion.iloc[-1] if len(hv) else 'M'
        ps, px, pg = d['prev'].get(p, d['prev'].get('M'))
        n90 = hv.minutos.sum() / 90.0
        r_s = (hv.a_puerta.sum() + ps * K) / (n90 + K)
        r_x = (hv.xg.sum() + px * K) / (n90 + K)
        r_g = (hv.goles.sum() + pg * K) / (n90 + K)
        lam_s = r_s * emin / 90 * fs ** 0.5
        lam_g = ((0.75 * r_x + 0.25 * r_g) if liga in d['conxg'] else r_g) * emin / 90 * fx ** 0.5
        out.append({'n': str(h5.jugador.iloc[-1]), 'pos': p,
                    'gol': round(_cal('gol', _p_ge(lam_g, 1)), 3),
                    'p1': round(_cal('p1', _p_ge(lam_s, 1)), 3),
                    'p2': round(_cal('p2', _p_ge(lam_s, 2)), 3)})
    out.sort(key=lambda x: (-x['gol'], -x['p1']))
    return out[:POR_EQUIPO]


def poner(filas: List[Dict], dias: int = 3) -> int:
    """`jug` = {'h': [...], 'a': [...]} en cada partido de fútbol que aún no empieza (próximos
    `dias`), con los equipos de FotMob del MISMO partido (el emparejador de los escudos)."""
    import datetime as dt
    import escudos
    try:
        _datos()
    except Exception as e:
        logger.warning('[jugadores] sin la base de FotMob: %s', e)
        return 0
    ahora = dt.datetime.now(dt.timezone.utc)
    cache, hecho, n = {}, {}, 0
    for f in filas:
        if f.get('deporte') != 'Fútbol' or f.get('estado') not in (None, 'pendiente'):
            continue
        ini = escudos._utc(f.get('inicio'))
        if not ini or ini < ahora or ini > ahora + dt.timedelta(days=dias):
            continue
        k = (f.get('partido'), str(f.get('inicio')))
        if k not in hecho:
            hecho[k] = None
            try:
                fx = escudos.fixture(f.get('partido'), f.get('inicio'), cache, f.get('liga') or '')
                if fx:
                    fem = escudos._cat(f.get('liga') or '', *fx)[0]
                    h, a = clave(fx[0], fem), clave(fx[1], fem)
                    jh, ja = equipo(h, a), equipo(a, h)
                    if jh or ja:
                        hecho[k] = {'h': jh, 'a': ja}
            except Exception as e:
                logger.debug('[jugadores] %s: %s', f.get('partido'), e)
        if hecho[k]:
            f['jug'] = hecho[k]
            n += 1
    return n


def calibrar(pkl: str) -> Dict:
    """Ajusta la calibración isotónica con el backtest de `medir_jugadores.py` (todas las filas:
    ya se comprobó en las dos mitades) y la guarda en `jugadores_calibracion.json`."""
    import numpy as np
    import pandas as pd
    from sklearn.isotonic import IsotonicRegression
    R = pd.read_pickle(pkl)
    out = {}
    for nom, lam, k, y in (('gol', 'lam_g', 1, R.gol.values), ('p1', 'lam_s', 1, (R.sot >= 1).values),
                           ('p2', 'lam_s', 2, (R.sot >= 2).values)):
        p = np.array([_p_ge(x, k) for x in R[lam].values])
        iso = IsotonicRegression(out_of_bounds='clip', y_min=0, y_max=1).fit(p, y.astype(float))
        out[nom] = {'x': [round(float(v), 5) for v in iso.X_thresholds_], 'y': [round(float(v), 5) for v in iso.y_thresholds_]}
    with open(CAL, 'w', encoding='utf-8') as fh:
        json.dump(out, fh)
    return out


if __name__ == '__main__':
    import sys
    if len(sys.argv) > 2 and sys.argv[1] == 'calibrar':
        print({k: len(v['x']) for k, v in calibrar(sys.argv[2]).items()})
