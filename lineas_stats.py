# -*- coding: utf-8 -*-
"""
v470 — LÍNEAS POR ESTADÍSTICA DESDE LOS PROMEDIOS DEL PARTIDO.

El usuario: «si en el análisis del partido un equipo tiene una media de 7 córners, que me diga que me
vaya por córners de ese equipo +5, +4, +6, y así con cada estadística, por equipo y en general».

λ del equipo = media de la liga en su lado (local/visita) × su ataque (lo suyo en sus últimos 10) ×
la defensa del rival (lo que concede en sus últimos 10), los dos encogidos a la media con 3
partidos. Total = suma. Conteo binomial negativa con la dispersión medida y calibración isotónica.

MEDIDO (D:/Claude/mediciones/medir_lineas.py, 48.762 partidos de 63 ligas, 2025-2026, líneas fijas
alrededor de la media de la liga, calibrado en una mitad y medido en la otra y al revés):
  · ganan a la media de la liga en las dos mitades (p5 > 0): goles, córners, tiros y tiros a puerta
    DE CADA EQUIPO (más y menos), y los tiros TOTALES (más y menos) y los tiros a puerta totales (menos).
  · NO ganan (no se enseñan): goles totales, córners totales, amarillas (de equipo y totales) y tiros a
    puerta totales «más de». Ahí la media de la liga sabe lo mismo que los promedios.
Es información, no un pick.
"""
from __future__ import annotations

import json
import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

CAL = 'lineas_calibracion.json'
K = 3.0
N = 10
COLS = {'goles': ('home_goals', 'away_goals'), 'corners': ('home_corners', 'away_corners'),
        'tiros_puerta': ('home_shots_on', 'away_shots_on'), 'tiros': ('home_tiros', 'away_tiros')}
# lo que pasó la medición: (estadística, equipo|total, mas|menos)
VALE = {('goles', 'equipo', 'mas'), ('goles', 'equipo', 'menos'), ('corners', 'equipo', 'mas'), ('corners', 'equipo', 'menos'),
        ('tiros_puerta', 'equipo', 'mas'), ('tiros_puerta', 'equipo', 'menos'), ('tiros', 'equipo', 'mas'), ('tiros', 'equipo', 'menos'),
        ('tiros', 'total', 'mas'), ('tiros', 'total', 'menos'), ('tiros_puerta', 'total', 'menos')}
P_MIN, P_MAX = 0.60, 0.93
_MEM: Dict = {}


def _cal() -> Dict:
    if 'cal' not in _MEM:
        try:
            _MEM['cal'] = json.load(open(CAL, encoding='utf-8'))
        except Exception:
            _MEM['cal'] = {}
    return _MEM['cal']


def _p_mas(lam: float, linea: float, alpha: float) -> float:
    """P(X > linea), linea = k + 0,5."""
    from scipy.stats import nbinom, poisson
    k = int(linea)
    if alpha <= 1e-6:
        return float(1 - poisson.cdf(k, lam))
    r = 1 / alpha
    return float(1 - nbinom.cdf(k, r, r / (r + lam)))


def _calibrada(clave: str, p: float) -> Optional[float]:
    import numpy as np
    t = _cal().get(clave)
    return float(np.interp(p, t['x'], t['y'])) if t else None


def _lineas(stat: str, tipo: str, lam: float) -> List[list]:
    """Hasta 2 «más de» (las más cercanas a λ con 60-93 %) y 1 «menos de»: [[tipo, línea, prob], …]."""
    cal = _cal()
    alpha = (cal.get('alpha') or {}).get('%s_%s' % (stat, tipo), 0.05)
    out = []
    if (stat, tipo, 'mas') in VALE:
        mas = []
        for k in range(0, int(lam) + 1):
            p = _calibrada('%s_%s_mas' % (stat, tipo), _p_mas(lam, k + 0.5, alpha))
            if p is not None and P_MIN <= p <= P_MAX:
                mas.append(['mas', k + 0.5, round(p, 3)])
        out += sorted(mas, key=lambda x: -x[1])[:2][::-1]
    if (stat, tipo, 'menos') in VALE:
        for k in range(int(lam) + 1, int(lam) + 15):
            p = _calibrada('%s_%s_menos' % (stat, tipo), 1 - _p_mas(lam, k + 0.5, alpha))
            if p is not None and P_MIN <= p <= P_MAX:
                out.append(['menos', k + 0.5, round(p, 3)])
                break
    return out


# v472 — EL PARLEY DEL MISMO PARTIDO con las líneas que Playdoit SÍ ofrece (mercado_dia.json).
# MEDIDO (D:/Claude/mediciones/medir_parlay.py, 29.571 partidos): las patas del mismo partido van
# juntas (más tiros, más córners), así que el producto se queda CORTO: 2 patas dice 72,9 % y fue
# 75,8 %; 3 patas 59,5 → 63,5; 4 patas 47,4 → 53,7, igual en las dos mitades. Se corrige con eso.
# v474 — el usuario: «la IA dice más de 2.5 córners de un equipo pero la casa sólo deja meter de 4 en
# adelante: tiene que estar sincronizado». Con el partido en Playdoit, las líneas y el parley usan
# SÓLO las líneas de la casa (con su cuota); sin Playdoit, las nuestras, como referencia.
P_PATA = 0.75          # la pata «buena» (lo medido)
P_POZO = 0.60          # si no hay de 75 %, la más alta de 60 % entra al pozo (y se dice su prob.)
CORR = {2: 1.04, 3: 1.067, 4: 1.13}
CASA = {'goles': ('goles_home', 'goles_away', None), 'corners': ('corners_home', 'corners_away', None),
        'tiros': ('remates_home', 'remates_away', 'remates'), 'tiros_puerta': ('remates_on_home', 'remates_on_away', 'remates_on')}


def _de_la_casa(tabla: Dict, stat: str, tipo: str, lam: float) -> List[list]:
    """[[mas|menos, línea, prob nuestra, cuota de la casa], …] de cada línea x.5 que la casa ofrece."""
    alpha = (_cal().get('alpha') or {}).get('%s_%s' % (stat, tipo), 0.05)
    out = []
    for k, v in (tabla or {}).items():
        try:
            linea = float(k)
        except Exception:
            continue
        if linea % 1 != 0.5:
            continue
        pm = _p_mas(lam, linea, alpha)
        for sent, cuota, praw in (('mas', (v or {}).get('mas'), pm), ('menos', (v or {}).get('menos'), 1 - pm)):
            try:
                cuota = float(cuota or 0)
            except Exception:
                continue
            if cuota <= 1 or (stat, tipo, sent) not in VALE:
                continue
            pr = _calibrada('%s_%s_%s' % (stat, tipo, sent), praw)
            if pr is not None:
                out.append([sent, linea, round(pr, 3), round(cuota, 3)])
    return out


def _lineas_casa(tabla: Dict, stat: str, tipo: str, lam: float) -> List[list]:
    """Como `_lineas` pero sólo con líneas de la casa: hasta 2 «más de» y 1 «menos de» (60-95 %)."""
    xs = _de_la_casa(tabla, stat, tipo, lam)
    mas = sorted([x for x in xs if x[0] == 'mas' and P_MIN <= x[2] <= 0.95], key=lambda x: -x[1])[:2][::-1]
    menos = sorted([x for x in xs if x[0] == 'menos' and P_MIN <= x[2] <= 0.95], key=lambda x: x[1])[:1]
    return mas + menos


def _parley(lams: Dict, mercado: Dict) -> List[list]:
    """El pozo del parley: por estadística y equipo, la línea «más de» MÁS ALTA de la casa con
    prob >= 75 % (si no hay, la más alta con >= 60 %). [[stat, lado, línea, prob, cuota], …]."""
    patas = []
    for stat, cols in CASA.items():
        if stat not in lams:
            continue
        lh, la = lams[stat]
        for lado, col, lam, tipo in (('h', cols[0], lh, 'equipo'), ('a', cols[1], la, 'equipo'), ('t', cols[2], lh + la, 'total')):
            tabla = (mercado or {}).get(col) if col else None
            if not tabla:
                continue
            mas = [x for x in _de_la_casa(tabla, stat, tipo, lam) if x[0] == 'mas']
            buena = [x for x in mas if x[2] >= P_PATA] or [x for x in mas if x[2] >= P_POZO]
            if buena:
                x = max(buena, key=lambda y: y[1])
                patas.append([stat, lado, x[1], x[2], x[3]])
    return sorted(patas, key=lambda x: -x[3])


def calcular(h, home: str, away: str, antes, mercado: Optional[Dict] = None) -> Optional[Dict]:
    """{stat: {'h': [...], 'a': [...], 't': [...]}, 'casa': bool, 'par': [...]} con el histórico de la
    liga `h` (el de «Antes del partido»). Con `mercado` (Playdoit) las líneas son las de la casa."""
    import pandas as pd
    h = h[h['date'] < antes].sort_values('date')
    if 'home_shots_on' in h.columns and 'home_shots_off' in h.columns:
        h = h.assign(home_tiros=pd.to_numeric(h.home_shots_on, errors='coerce') + pd.to_numeric(h.home_shots_off, errors='coerce'),
                     away_tiros=pd.to_numeric(h.away_shots_on, errors='coerce') + pd.to_numeric(h.away_shots_off, errors='coerce'))
    casa = bool(mercado) and any((mercado or {}).get(c) for cols in CASA.values() for c in cols if c)
    out, lams = {}, {}
    for stat, (hc, ac) in COLS.items():
        if hc not in h.columns:
            continue
        d = h[['home_team', 'away_team', hc, ac]].copy()
        d[hc], d[ac] = pd.to_numeric(d[hc], errors='coerce'), pd.to_numeric(d[ac], errors='coerce')
        d = d.dropna()
        if len(d) < 60:
            continue
        ult = d.tail(600)
        m_h, m_a = float(ult[hc].mean()), float(ult[ac].mean())
        m = (m_h + m_a) / 2
        if m <= 0:
            continue

        def lado(eq):
            x = d[(d.home_team == eq) | (d.away_team == eq)].tail(N)
            f = x[hc].where(x.home_team == eq, x[ac])
            c = x[ac].where(x.home_team == eq, x[hc])
            return len(x), float(f.sum()), float(c.sum())
        nh, fh, ch = lado(home)
        na, fa, ca = lado(away)
        if nh < 5 or na < 5:
            continue
        F = lambda s, n: (s + K * m) / (n + K) / m
        lam_h = m_h * F(fh, nh) * F(ca, na)
        lam_a = m_a * F(fa, na) * F(ch, nh)
        lams[stat] = [round(lam_h, 2), round(lam_a, 2)]
        if casa:
            c = CASA[stat]
            r = {'h': _lineas_casa(mercado.get(c[0]), stat, 'equipo', lam_h), 'a': _lineas_casa(mercado.get(c[1]), stat, 'equipo', lam_a),
                 't': _lineas_casa(mercado.get(c[2]) if c[2] else None, stat, 'total', lam_h + lam_a)}
        else:
            r = {'h': _lineas(stat, 'equipo', lam_h), 'a': _lineas(stat, 'equipo', lam_a), 't': _lineas(stat, 'total', lam_h + lam_a)}
        r['lam'] = lams[stat]
        if r['h'] or r['a'] or r['t']:
            out[stat] = r
    if not lams:
        return None
    out['casa'] = casa
    if casa:
        out['par'] = _parley(lams, mercado)[:8]
    return out


def calibrar(carpeta: str, alphas: Dict[str, float]) -> Dict:
    """La calibración isotónica de cada (estadística, equipo|total, más|menos) que pasó, con los
    backtests de `medir_lineas.py`; se guarda en `lineas_calibracion.json`."""
    import os
    import pandas as pd
    from sklearn.isotonic import IsotonicRegression
    out = {'alpha': alphas}
    for stat, tipo, sent in sorted(VALE):
        R = pd.read_pickle(os.path.join(carpeta, 'lineas_%s_%s.pkl' % (stat, tipo)))
        R = R[R.tipo == sent]
        iso = IsotonicRegression(out_of_bounds='clip', y_min=0, y_max=1).fit(R.p.values, R.y.values)
        out['%s_%s_%s' % (stat, tipo, sent)] = {'x': [round(float(v), 5) for v in iso.X_thresholds_],
                                                'y': [round(float(v), 5) for v in iso.y_thresholds_]}
    with open(CAL, 'w', encoding='utf-8') as fh:
        json.dump(out, fh)
    return out
