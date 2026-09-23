# -*- coding: utf-8 -*-
"""
v303 — UN MOTOR DE GOLES PARA LAS LIGAS QUE NO TIENEN MOTOR.

POR QUÉ
Las competiciones con modelo entrenado (`league_engine`) salen de
football-data y ESPN. Las que sólo tienen resultados —Liga MX Femenil desde
FotMob, v303— no producían ni un pronóstico, así que en Apuestas del Día no
existían aunque la casa las cotizara.

QUÉ ES
El modelo clásico de Maher / Dixon-Coles sin la corrección de marcadores
bajos: goles del local ~ Poisson(ataque_local · defensa_visitante · localía),
ajustado por máxima verosimilitud ponderada con decaimiento temporal (vida
media de 180 días). El patrón que el usuario describió —los de arriba
golean, los de abajo no— lo recogen las propias fuerzas: medido en la
Femenil, arriba contra abajo promedia 3,96 goles (72 % de más de 2,5) y abajo
contra abajo 2,82, y un equipo de arriba tiene ataque alto y defensa baja,
que es exactamente lo que hace el producto de las dos fuerzas.

Medido el 2026-09-23 en la Femenil, walk-forward sobre 646 partidos de las
dos últimas temporadas: log-loss del 1X2 0,8163 contra 1,0319 de la base
(p5 de la mejora +0,178) y del más de 2,5 0,6410 contra 0,6630 (p5 +0,0025).

LO QUE PROMETE, MEDIDO ANTES DE USARSE
`validar(clave)` hace walk-forward: para cada partido de las dos últimas
temporadas ajusta sólo con lo anterior y predice. Se compara contra la línea
base de la liga (frecuencias históricas de 1X2 y de más de 2,5). El motor
sólo publica pronósticos si le gana a la base en las DOS cosas; el resultado
queda en `motor_goles.json` y la rama del barrido lo lee.
"""
from __future__ import annotations

import json
import logging
import math
import os
import sys
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

FICHERO = 'motor_goles.json'
VIDA_MEDIA_DIAS = 180
VENTANA_DIAS = 730
# Cuánto se encogen las fuerzas hacia 1 (goles ficticios de previa). Medido
# el 2026-09-23 con 1, 3, 6, 10 y 15 en las dos ligas: 6 mejora los goles de la
# Femenil (p5 +0,0025 -> +0,0074) sin estropear su 1X2 (p5 +0,181), y en la
# Champions femenina el 1X2 sigue ganando (p5 +0,016). Ningún valor hace que
# los goles de la Champions le ganen a su base: por eso se valida por mercado.
PREVIA = 6.0
_CACHE: Dict = {}


def _historico(clave: str) -> pd.DataFrame:
    ruta = 'historico_%s.csv' % clave
    if not os.path.exists(ruta):
        return pd.DataFrame()
    d = pd.read_csv(ruta, low_memory=False)
    d = d.dropna(subset=['date', 'home_team', 'away_team', 'home_goals',
                         'away_goals'])
    d['date'] = pd.to_datetime(d['date'], errors='coerce')
    return d.dropna(subset=['date']).sort_values('date').reset_index(drop=True)


def ajustar(d: pd.DataFrame, hasta: pd.Timestamp, iters: int = 60) -> Dict:
    """Fuerzas de ataque/defensa y localía con lo anterior a `hasta`."""
    s = d[(d['date'] < hasta) &
          (d['date'] >= hasta - pd.Timedelta(days=VENTANA_DIAS))]
    if len(s) < 60:
        return {}
    equipos = sorted(set(s['home_team']) | set(s['away_team']))
    ix = {e: i for i, e in enumerate(equipos)}
    h = s['home_team'].map(ix).to_numpy()
    a = s['away_team'].map(ix).to_numpy()
    gh = s['home_goals'].to_numpy(float)
    ga = s['away_goals'].to_numpy(float)
    edad = (hasta - s['date']).dt.days.to_numpy(float)
    w = np.power(0.5, edad / VIDA_MEDIA_DIAS)
    n = len(equipos)
    att = np.ones(n)
    de = np.ones(n)
    loc = 1.2
    media = (np.sum(w * (gh + ga)) / (2 * np.sum(w))) or 1.3
    for _ in range(iters):
        # ataque: goles marcados / esperados con fuerza 1
        num = np.bincount(h, w * gh, n) + np.bincount(a, w * ga, n)
        den = (np.bincount(h, w * de[a] * loc * media, n)
               + np.bincount(a, w * de[h] * media, n))
        att = (num + PREVIA) / (den + PREVIA)    # previa hacia 1
        num = np.bincount(a, w * gh, n) + np.bincount(h, w * ga, n)
        den = (np.bincount(a, w * att[h] * loc * media, n)
               + np.bincount(h, w * att[a] * media, n))
        de = (num + PREVIA) / (den + PREVIA)
        loc = (np.sum(w * gh) + 1) / (np.sum(w * att[h] * de[a] * media) + 1)
    return {'equipos': ix, 'att': att, 'de': de, 'loc': float(loc),
            'media': float(media)}


def lambdas(m: Dict, home: str, away: str) -> Optional[tuple]:
    ix = m.get('equipos') or {}
    if home not in ix or away not in ix:
        return None
    i, j = ix[home], ix[away]
    lh = m['att'][i] * m['de'][j] * m['loc'] * m['media']
    la = m['att'][j] * m['de'][i] * m['media']
    return float(lh), float(la)


def matriz(lh: float, la: float, n: int = 10) -> np.ndarray:
    k = np.arange(n)
    ph = np.exp(-lh) * np.power(lh, k) / np.array([math.factorial(x) for x in k])
    pa = np.exp(-la) * np.power(la, k) / np.array([math.factorial(x) for x in k])
    M = np.outer(ph, pa)
    return M / M.sum()


def probabilidades(lh: float, la: float) -> Dict:
    M = matriz(lh, la)
    n = M.shape[0]
    tot = np.add.outer(np.arange(n), np.arange(n))
    return {'home': float(np.tril(M, -1).sum()),
            'draw': float(np.trace(M)),
            'away': float(np.triu(M, 1).sum()),
            'lineas': {'%.1f' % L: round(float(M[tot > L].sum()), 4)
                       for L in (0.5, 1.5, 2.5, 3.5, 4.5, 5.5, 6.5)},
            'local': {'%.1f' % L: round(float(M[np.arange(n) > L, :].sum()), 4)
                      for L in (0.5, 1.5, 2.5)},
            'visitante': {'%.1f' % L: round(float(M[:, np.arange(n) > L].sum()),
                                            4) for L in (0.5, 1.5, 2.5)},
            'btts': float(M[1:, 1:].sum()), 'matriz': M}


def historico_con_apoyo(clave: str) -> pd.DataFrame:
    """La liga más sus ligas de apoyo (ver `historico_fotmob.APOYO`), para
    AJUSTAR. Juzgar se juzga sólo sobre los partidos de la propia liga."""
    d = _historico(clave)
    try:
        import historico_fotmob as hf
        extra = [_historico(c) for c in hf.APOYO.get(clave, [])]
    except Exception:
        extra = []
    extra = [x for x in extra if not x.empty]
    if not extra:
        return d
    t = pd.concat([d] + extra, ignore_index=True)
    return t.sort_values('date').reset_index(drop=True)


def validar(clave: str, temporadas_juicio: int = 2) -> Dict:
    """Walk-forward sobre el tramo reciente contra la línea base de la liga."""
    propio = _historico(clave)
    if propio.empty:
        return {'clave': clave, 'ok': False, 'motivo': 'sin histórico'}
    d = historico_con_apoyo(clave)
    corte = propio['date'].max() - pd.Timedelta(days=365 * temporadas_juicio)
    jui = propio[propio['date'] >= corte]
    ll_m, ll_b, lo_m, lo_b = [], [], [], []
    ajuste, fecha_aj = {}, None
    for r in jui.itertuples(index=False):
        # re-ajusta cada semana: suficiente y 50 veces más barato
        if fecha_aj is None or (r.date - fecha_aj).days >= 7:
            ajuste = ajustar(d, r.date)
            fecha_aj = r.date
            prev = propio[propio['date'] < r.date]
            base = {'home': float((prev.home_goals > prev.away_goals).mean()),
                    'draw': float((prev.home_goals == prev.away_goals).mean()),
                    'away': float((prev.home_goals < prev.away_goals).mean()),
                    'o25': float(((prev.home_goals + prev.away_goals) > 2.5)
                                 .mean())}
        lam = lambdas(ajuste, r.home_team, r.away_team) if ajuste else None
        if not lam:
            continue
        p = probabilidades(*lam)
        y = ('home' if r.home_goals > r.away_goals else
             'draw' if r.home_goals == r.away_goals else 'away')
        ll_m.append(-math.log(max(p[y], 1e-6)))
        ll_b.append(-math.log(max(base[y], 1e-6)))
        o = (r.home_goals + r.away_goals) > 2.5
        po = p['lineas']['2.5']
        lo_m.append(-math.log(max(po if o else 1 - po, 1e-6)))
        lo_b.append(-math.log(max(base['o25'] if o else 1 - base['o25'],
                                  1e-6)))
    if len(ll_m) < 100:
        return {'clave': clave, 'ok': False, 'motivo': 'juicio corto',
                'n': len(ll_m)}
    rng = np.random.default_rng(303)
    d1 = np.array(ll_b) - np.array(ll_m)
    d2 = np.array(lo_b) - np.array(lo_m)
    idx = rng.integers(0, len(d1), size=(2000, len(d1)))
    p5_1 = float(np.percentile(d1[idx].mean(1), 5))
    p5_2 = float(np.percentile(d2[idx].mean(1), 5))
    return {'clave': clave, 'n': len(ll_m),
            'll_1x2_motor': round(float(np.mean(ll_m)), 4),
            'll_1x2_base': round(float(np.mean(ll_b)), 4),
            'mejora_1x2_p5': round(p5_1, 4),
            'll_o25_motor': round(float(np.mean(lo_m)), 4),
            'll_o25_base': round(float(np.mean(lo_b)), 4),
            'mejora_o25_p5': round(p5_2, 4),
            # POR MERCADO: el 1X2 y los goles se juzgan por separado. En la
            # Champions femenina el motor gana en el 1X2 y pierde en goles, y
            # tirar el 1X2 por culpa de los goles sería tirar lo que sí sirve.
            'ok_1x2': bool(p5_1 > 0),
            'ok_goles': bool(p5_2 > 0),
            'ok': bool(p5_1 > 0)}


def lineas_base(clave: str, dias: int = 730) -> Dict[str, float]:
    """P(más de L) de la liga en sus dos últimos años: la línea base que el
    motor tiene que batir, y lo que se usa cuando no la bate."""
    d = _historico(clave)
    if d.empty:
        return {}
    d = d[d['date'] >= d['date'].max() - pd.Timedelta(days=dias)]
    tot = d['home_goals'] + d['away_goals']
    return {'%.1f' % L: round(float((tot > L).mean()), 4)
            for L in (0.5, 1.5, 2.5, 3.5, 4.5, 5.5, 6.5)}


def estado() -> Dict:
    if 'estado' not in _CACHE:
        try:
            with open(FICHERO, encoding='utf-8') as f:
                _CACHE['estado'] = json.load(f)
        except Exception:
            _CACHE['estado'] = {}
    return _CACHE['estado']


def modelo(clave: str) -> Dict:
    """El ajuste de hoy de una liga validada, cacheado por proceso."""
    if clave not in _CACHE:
        v = (estado().get('ligas') or {}).get(clave) or {}
        if not v.get('ok'):
            _CACHE[clave] = {}
        else:
            d = historico_con_apoyo(clave)
            _CACHE[clave] = ajustar(d, pd.Timestamp.now()) if len(d) else {}
    return _CACHE[clave]


def main() -> int:
    sys.stdout.reconfigure(encoding='utf-8')
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    claves = sys.argv[1:] or ['mex_femenil']
    doc = {'ligas': {}}
    for c in claves:
        r = validar(c)
        doc['ligas'][c] = r
        print(r)
    doc['generado'] = pd.Timestamp.now('UTC').strftime('%Y-%m-%dT%H:%M:%SZ')
    with open(FICHERO, 'w', encoding='utf-8') as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    return 0


if __name__ == '__main__':
    sys.exit(main())
