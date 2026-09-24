# -*- coding: utf-8 -*-
"""
v308 — ¿CUÁNTOS REMATES A PUERTA VA A HACER ESTE JUGADOR? MEDIDO.

El usuario: «quiero saber la probabilidad de que Mbappé haga un tiro a
puerta, dos tiros a puerta… y con la cuota. La alineación influye: si es
delantero tiene más; lo del falso nueve, el nueve, los puntas, las
posiciones… tienes que medir tú qué influye».

DATOS: `_v308_fondo/*.jsonl.gz` (FotMob, dos temporadas y media de 14 ligas
y las selecciones): cada titular con su puesto de ESE partido (`positionId`,
que codifica la línea y el carril: 105 es el nueve, 83/87 los extremos, 85
el mediapunta…), sus minutos, remates, a puerta y valor de mercado.

QUÉ SE PREDICE: para cada TITULAR (las apuestas de jugador se juegan con la
alineación ya publicada), P(≥1), P(≥2), P(≥3) remates a puerta y P(≥1..≥4)
remates totales. Todo con información previa al partido.

LOS CANDIDATOS
  B0  el de producción (v163): media propia por titularidad de los últimos
      10, encogida (K=12 a puerta, 6 totales) hacia cuota_de_su_posición
      GRUESA (G/D/M/F) × lo que se espera que tire su equipo; Poisson.
  B1  igual, con el puesto FINO del partido (línea y carril del positionId).
  B2  B1 con cola binomial negativa (dispersión ajustada en entrenamiento).
  M1  LightGBM con objetivo Poisson sobre: media propia (a puerta, totales,
      minutos), apariciones, puesto fino, lo que tira su equipo y lo que
      concede el rival, localía, valor de mercado, cuota del equipo que se
      lleva el jugador; la λ que sale se usa con Poisson.
  M2  M1 con cola binomial negativa.

LA PUERTA: se ajusta con el 50 % más antiguo y se evalúa en el 50-70 %
(elección); se reajusta con el 70 % y se evalúa en el 30 % final (juicio).
Pérdida logarítmica de cada umbral, Brier y ECE; y bootstrap por PARTIDO de
la mejora contra B0: p5 > 0 en los dos tramos para adoptarlo.

Uso: python _v308_remates_jugador.py
"""
from __future__ import annotations

import glob
import gzip
import json
import math
import sys

import numpy as np
import pandas as pd

SALIDA = '_v308_remates_jugador.json'
VENT = 10
K = {'sot': 12.0, 'sh': 6.0}
UMBRALES = {'sot': (1, 2, 3), 'sh': (1, 2, 3, 4)}
B = 1000


# ---------------------------------------------------------------------------
# datos
# ---------------------------------------------------------------------------
def cargar():
    filas, equipos = [], []
    for ruta in sorted(glob.glob('_v308_fondo/*.jsonl.gz')):
        with gzip.open(ruta, 'rt', encoding='utf-8') as f:
            for linea in f:
                try:
                    r = json.loads(linea)
                except Exception:
                    continue
                lados = (r.get('h') or {}, r.get('a') or {})
                con_stats = any(j.get('sh') is not None
                                for l in lados for j in l.get('jug') or [])
                for i, (yo, otro) in enumerate((lados, lados[::-1])):
                    equipos.append({
                        'mid': r['mid'], 'fecha': r['fecha'],
                        'liga': r['liga'], 'eq': yo.get('id'),
                        'riv': otro.get('id'), 'local': int(i == 0),
                        'tiros': yo.get('tiros'), 'sot': yo.get('sot'),
                        'tiros_c': otro.get('tiros'), 'sot_c': otro.get('sot')})
                    if not con_stats:
                        continue
                    for j in yo.get('jug') or []:
                        if not j.get('min'):
                            continue
                        filas.append({
                            'mid': r['mid'], 'fecha': r['fecha'],
                            'liga': r['liga'], 'eq': yo.get('id'),
                            'riv': otro.get('id'), 'local': int(i == 0),
                            'pid': j.get('id'), 'n': j.get('n'),
                            't': j.get('t'), 'min': j.get('min'),
                            'pos': j.get('pos'), 'up': j.get('up'),
                            'mv': j.get('mv'),
                            'sh': j.get('sh') or 0, 'sot': j.get('sot') or 0})
    d = pd.DataFrame(filas)
    e = pd.DataFrame(equipos)
    d['fecha'] = pd.to_datetime(d['fecha'])
    e['fecha'] = pd.to_datetime(e['fecha'])
    return d, e


def rasgos(d: pd.DataFrame, e: pd.DataFrame) -> pd.DataFrame:
    # --- el equipo: lo que tira y lo que concede, de sus 10 anteriores
    e = e.sort_values(['fecha', 'mid']).copy()
    for c in ('tiros', 'sot', 'tiros_c', 'sot_c'):
        e[c] = pd.to_numeric(e[c], errors='coerce')
        e['m_' + c] = (e.groupby('eq')[c]
                       .transform(lambda s: s.shift(1).rolling(VENT, 3).mean()))
    eq = e.set_index(['mid', 'eq'])
    d = d.join(eq[['m_tiros', 'm_sot']].rename(
        columns={'m_tiros': 'eq_tiros', 'm_sot': 'eq_sot'}), on=['mid', 'eq'])
    riv = eq[['m_tiros_c', 'm_sot_c']].rename(
        columns={'m_tiros_c': 'r_tiros_c', 'm_sot_c': 'r_sot_c'})
    d = d.join(riv, on=['mid', 'riv'])
    d['lam_eq_sh'] = (d['eq_tiros'] + d['r_tiros_c']) / 2
    d['lam_eq_sot'] = (d['eq_sot'] + d['r_sot_c']) / 2

    # --- el jugador: su historia ANTERIOR (sólo apariciones)
    d = d.sort_values(['fecha', 'mid']).reset_index(drop=True)
    g = d.groupby('pid')
    d['n_prev'] = g.cumcount()
    for c in ('sot', 'sh', 'min', 't'):
        d['s_' + c] = g[c].transform(lambda s: s.shift(1).rolling(VENT, 1).sum())
    d['s_n'] = g['t'].transform(lambda s: s.shift(1).rolling(VENT, 1).count())
    # titularidades y apariciones de la ventana
    d['apar'] = d['s_n'].fillna(0)
    d['tits'] = d['s_t'].fillna(0)
    # media por titularidad (la de producción): total / (T + r·S)
    r_sup = {'sot': 0.48, 'sh': 0.48}
    for c in ('sot', 'sh'):
        den = d['tits'] + r_sup[c] * (d['apar'] - d['tits'])
        d['m_' + c] = np.where(den > 0, d['s_' + c] / den.replace(0, np.nan),
                               np.nan)
    d['m_min'] = np.where(d['apar'] > 0, d['s_min'] / d['apar'], np.nan)
    # cuota del jugador en los remates de su equipo (por 90)
    d['por90_sh'] = np.where(d['s_min'] > 0, 90 * d['s_sh'] / d['s_min'], np.nan)
    d['por90_sot'] = np.where(d['s_min'] > 0, 90 * d['s_sot'] / d['s_min'],
                              np.nan)
    # el puesto: línea y carril del positionId (105 -> línea 10, carril 5)
    pos = pd.to_numeric(d['pos'], errors='coerce')
    d['linea'] = np.floor(pos / 10)
    d['carril'] = (pos % 10 - 5).abs()
    d['rol'] = _rol(d['linea'], d['carril'], d['up'])
    d['log_mv'] = np.log1p(pd.to_numeric(d['mv'], errors='coerce').fillna(0))
    d['up'] = pd.to_numeric(d['up'], errors='coerce')
    return d


def _rol(linea, carril, up) -> pd.Series:
    """El puesto del partido en seis grupos, sacados del positionId."""
    fuera = []
    for l, c, u in zip(linea, carril, up):
        if l != l:                          # sin positionId: el habitual
            fuera.append({0: 'POR', 1: 'DEF', 2: 'MED', 3: 'DEL'}.get(u, 'MED'))
        elif l <= 1:
            fuera.append('POR')
        elif l <= 4:
            fuera.append('DEF')
        elif l <= 6:
            fuera.append('MED')
        elif l <= 8:
            fuera.append('EXT' if c >= 2 else 'MP')
        else:
            fuera.append('DEL')
    return pd.Series(fuera, index=linea.index if hasattr(linea, 'index')
                     else None)


GRUESA = {0: 'G', 1: 'D', 2: 'M', 3: 'F'}


# ---------------------------------------------------------------------------
# modelos
# ---------------------------------------------------------------------------
def cuotas(entreno: pd.DataFrame, clave: str, col: str) -> dict:
    """La cuota del equipo que se lleva cada puesto (titulares)."""
    x = entreno.dropna(subset=['lam_eq_' + col])
    x = x[x['t'] == 1]
    tot = x.groupby(clave)[col].sum()
    base = x.groupby(clave)['lam_eq_' + col].sum()
    return (tot / base).to_dict()


def lam_encogida(d, cuota_map, clave, col):
    cuota = d[clave].map(cuota_map).fillna(np.nanmean(list(cuota_map.values())))
    previo = cuota * d['lam_eq_' + col]
    n = d['apar'].clip(upper=VENT)
    m = d['m_' + col]
    lam = np.where(m.notna(), (n * m.fillna(0) + K[col] * previo) / (n + K[col]),
                   previo)
    return pd.Series(lam, index=d.index)


def p_ge_poisson(lam, k):
    lam = np.clip(np.asarray(lam, float), 1e-6, None)
    acc = np.zeros_like(lam)
    term = np.exp(-lam)
    for i in range(k):
        acc += term
        term = term * lam / (i + 1)
    return np.clip(1 - acc, 1e-6, 1 - 1e-6)


def p_ge_nb(lam, k, alpha):
    """Binomial negativa con var = λ + α λ²."""
    from scipy.stats import nbinom
    lam = np.clip(np.asarray(lam, float), 1e-6, None)
    if alpha <= 1e-6:
        return p_ge_poisson(lam, k)
    r = 1.0 / alpha
    p = r / (r + lam)
    return np.clip(nbinom.sf(k - 1, r, p), 1e-6, 1 - 1e-6)


def alpha_mm(y, lam):
    """Dispersión por momentos: E[(y-λ)² - y] / E[λ²]."""
    y = np.asarray(y, float)
    lam = np.asarray(lam, float)
    a = np.mean((y - lam) ** 2 - y) / max(np.mean(lam ** 2), 1e-9)
    return float(max(a, 0.0))


RASGOS_ML = ['m_sot', 'm_sh', 'm_min', 'apar', 'tits', 'por90_sh',
             'por90_sot', 'linea', 'carril', 'up', 'lam_eq_sh', 'lam_eq_sot',
             'local', 'log_mv', 'r_tiros_c', 'r_sot_c', 'eq_tiros', 'eq_sot']


def ajustar_ml(entreno, col):
    import lightgbm as lgb
    x = entreno[RASGOS_ML].astype(float)
    m = lgb.LGBMRegressor(objective='poisson', n_estimators=400,
                          learning_rate=0.03, num_leaves=31,
                          min_child_samples=100, subsample=0.8,
                          subsample_freq=1, colsample_bytree=0.8,
                          verbose=-1)
    m.fit(x, entreno[col])
    return m


def predecir(entreno, prueba, col):
    """λ de cada candidato para `prueba`, ajustado sólo con `entreno`."""
    ent_t = entreno[entreno['t'] == 1]
    fuera = {}
    c_gruesa = cuotas(ent_t.assign(gr=ent_t['up'].map(GRUESA)), 'gr', col)
    fuera['B0'] = lam_encogida(prueba.assign(gr=prueba['up'].map(GRUESA)),
                               c_gruesa, 'gr', col)
    c_fina = cuotas(ent_t, 'rol', col)
    fuera['B1'] = lam_encogida(prueba, c_fina, 'rol', col)
    lam_ent_b1 = lam_encogida(ent_t, c_fina, 'rol', col)
    a_b1 = alpha_mm(ent_t[col], lam_ent_b1)
    m = ajustar_ml(ent_t, col)
    fuera['M1'] = pd.Series(m.predict(prueba[RASGOS_ML].astype(float)),
                            index=prueba.index)
    lam_ent_m = m.predict(ent_t[RASGOS_ML].astype(float))
    a_m = alpha_mm(ent_t[col], lam_ent_m)
    return fuera, {'B2': a_b1, 'M2': a_m}, m


def probs(lams, alphas, col):
    out = {}
    for k in UMBRALES[col]:
        out[('B0', k)] = p_ge_poisson(lams['B0'], k)
        out[('B1', k)] = p_ge_poisson(lams['B1'], k)
        out[('B2', k)] = p_ge_nb(lams['B1'], k, alphas['B2'])
        out[('M1', k)] = p_ge_poisson(lams['M1'], k)
        out[('M2', k)] = p_ge_nb(lams['M1'], k, alphas['M2'])
    return out


def logloss(y, p):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


def ece(y, p, bins=10):
    y, p = np.asarray(y), np.asarray(p)
    cortes = np.quantile(p, np.linspace(0, 1, bins + 1))
    idx = np.clip(np.searchsorted(cortes, p, side='right') - 1, 0, bins - 1)
    tot = 0.0
    for b in range(bins):
        s = idx == b
        if s.any():
            tot += s.mean() * abs(y[s].mean() - p[s].mean())
    return float(tot)


def evaluar(prueba, pr, col, rng):
    fuera = {}
    mids = prueba['mid'].to_numpy()
    uniq, inv = np.unique(mids, return_inverse=True)
    for k in UMBRALES[col]:
        y = (prueba[col].to_numpy() >= k).astype(float)
        base = logloss(y, pr[('B0', k)])
        fila = {'tasa': round(float(y.mean()), 4)}
        for mod in ('B0', 'B1', 'B2', 'M1', 'M2'):
            p = pr[(mod, k)]
            ll = logloss(y, p)
            # bootstrap por PARTIDO de la mejora media contra B0
            dif = base - ll
            por_partido = np.bincount(inv, weights=dif, minlength=len(uniq))
            cuenta = np.bincount(inv, minlength=len(uniq))
            bs = []
            for _ in range(B):
                s = rng.integers(0, len(uniq), len(uniq))
                bs.append(por_partido[s].sum() / max(cuenta[s].sum(), 1))
            fila[mod] = {'logloss': round(float(ll.mean()), 5),
                         'brier': round(float(((p - y) ** 2).mean()), 5),
                         'ece': round(ece(y, p), 4),
                         'mejora': round(float(dif.mean()), 5),
                         'p5': round(float(np.percentile(bs, 5)), 5)}
        fuera['%d+' % k] = fila
    return fuera


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    d, e = cargar()
    print('jugador-partido', len(d), 'partidos', d['mid'].nunique())
    d = rasgos(d, e)
    tit = d[(d['t'] == 1) & d['lam_eq_sh'].notna() & d['lam_eq_sot'].notna()
            & (d['rol'] != 'POR')].copy()
    fechas = tit['fecha'].sort_values()
    q50, q70 = fechas.quantile(0.5), fechas.quantile(0.7)
    rng = np.random.default_rng(308)
    doc = {'n_titulares': int(len(tit)), 'partidos': int(tit['mid'].nunique()),
           'corte_50': str(q50.date()), 'corte_70': str(q70.date())}
    # la tasa por puesto: qué mueve la media (lo que pidió el usuario)
    doc['por_rol'] = (tit.groupby('rol')
                      .agg(n=('sot', 'size'), sot=('sot', 'mean'),
                           sh=('sh', 'mean'),
                           p_sot1=('sot', lambda s: (s >= 1).mean()),
                           p_sot2=('sot', lambda s: (s >= 2).mean()))
                      .round(3).to_dict('index'))
    for col in ('sot', 'sh'):
        doc[col] = {}
        for nombre, ent, pru in (
                ('eleccion', tit[tit['fecha'] < q50],
                 tit[(tit['fecha'] >= q50) & (tit['fecha'] < q70)]),
                ('juicio', tit[tit['fecha'] < q70], tit[tit['fecha'] >= q70])):
            lams, alphas, m = predecir(ent, pru, col)
            pr = probs(lams, alphas, col)
            doc[col][nombre] = {'n': int(len(pru)),
                                'alphas': {k: round(v, 4)
                                           for k, v in alphas.items()},
                                **evaluar(pru, pr, col, rng)}
            if nombre == 'juicio':
                imp = dict(zip(RASGOS_ML, m.feature_importances_.tolist()))
                doc[col]['importancia_ml'] = dict(sorted(
                    imp.items(), key=lambda x: -x[1]))
        print(col, json.dumps(doc[col], ensure_ascii=False)[:3000])
    print('por rol', json.dumps(doc['por_rol'], ensure_ascii=False))
    with open(SALIDA, 'w', encoding='utf-8') as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)


if __name__ == '__main__':
    main()
