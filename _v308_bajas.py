# -*- coding: utf-8 -*-
"""
v308 — ¿LAS BAJAS MEJORAN EL MODELO? MEDIDO SOBRE EL HISTÓRICO, NO A OJO.

El usuario: «estoy casi seguro de que sí se puede hacer con el histórico:
tenemos un historial muy grande de partidos y debería haber bajas con las
fechas. Haz pruebas, simulaciones, varias hipótesis, método científico».

EL PROBLEMA DEL DATO, Y CÓMO SE RESUELVE
FotMob borra la lista de lesionados de la ficha cuando el partido termina
(comprobado: 0 bajas en Portugal–España y Fulham–United ya jugados). Pero
deja la CONVOCATORIA entera. Así que la baja se RECONSTRUYE:

    habitual  = titular en al menos la mitad de los 10 partidos anteriores
                de su equipo
    baja      = habitual que NO está en la convocatoria de hoy (ni de
                titular ni en el banquillo): lesión, sanción o no convocado

y se le pone PESO con lo que aportaba en esos 10 partidos: su parte de los
remates y del xG del equipo (ataque), su parte de los minutos de la zaga
(defensa) y su valor de mercado.

LA PRUEBA, CONTRA NUESTRO MODELO DE PRODUCCIÓN
`pick_ledger_totales.csv` guarda la λ de goles que el modelo de producción
dio a cada equipo, sin mirar el resultado (walk-forward). Se cruza cada
partido del fondo de FotMob con su fila del ledger y se prueba:

    λ' = λ_prod · exp(β · rasgo)

con β ajustado por máxima verosimilitud Poisson en el tramo de ELECCIÓN
(70 % más antiguo) y evaluado, sin tocarlo, en el de JUICIO (30 % final):
log-verosimilitud de los goles, pérdida logarítmica del más/menos 2.5 y del
1X2 (Poisson independiente con las dos λ). Bootstrap por partido de la
mejora contra λ_prod: se adopta sólo si p5 > 0 en la elección (ajuste
dentro de muestra, como control) Y en el juicio.

HIPÓTESIS
  H1  las bajas de ATAQUE (parte de remates perdida) bajan los goles propios
  H2  las bajas de DEFENSA (parte de minutos de zaga y portero) suben los
      goles del rival
  H3  el VALOR de mercado perdido explica más que las partes de juego
  H4  el simple número de habituales ausentes
  H5  H1 + H2 juntas

Uso: python _v308_bajas.py
"""
from __future__ import annotations

import glob
import gzip
import json
import sys

import numpy as np
import pandas as pd

SALIDA = '_v308_bajas.json'
VENT = 10
B = 1000


def cargar_fondo() -> pd.DataFrame:
    """Una fila por equipo y partido con sus bajas reconstruidas."""
    partidos = []
    for ruta in sorted(glob.glob('_v308_fondo/*.jsonl.gz')):
        with gzip.open(ruta, 'rt', encoding='utf-8') as f:
            for linea in f:
                try:
                    partidos.append(json.loads(linea))
                except Exception:
                    pass
    partidos.sort(key=lambda r: (r.get('fecha') or '', r.get('mid')))
    hist = {}          # equipo -> lista de (convocados, titulares, stats)
    filas = []
    for r in partidos:
        for lado, otro in (('h', 'a'), ('a', 'h')):
            t = r.get(lado) or {}
            tid = t.get('id')
            jug = t.get('jug') or []
            if tid is None or not jug:
                continue
            conv = {j['id'] for j in jug}
            prev = hist.get(tid, [])[-VENT:]
            fila = {'mid': r['mid'], 'fecha': r['fecha'], 'liga': r['liga'],
                    'eq': t.get('eq'), 'rival': (r.get(otro) or {}).get('eq'),
                    'local': int(lado == 'h'), 'goles': t.get('goles'),
                    'n_prev': len(prev)}
            if len(prev) >= 6:
                tit_cnt, info = {}, {}
                sh_tot = sum(p['sh_eq'] or 0 for p in prev) or 1.0
                xg_tot = sum(p['xg_eq'] or 0 for p in prev) or 1.0
                min_def = sum(p['min_def'] for p in prev) or 1.0
                for p in prev:
                    for j in p['jug']:
                        pid = j['id']
                        d = info.setdefault(pid, {'tit': 0, 'sh': 0.0,
                                                  'xg': 0.0, 'min': 0,
                                                  'min_def': 0, 'mv': 0,
                                                  'n': j.get('n')})
                        d['tit'] += j.get('t') or 0
                        d['sh'] += j.get('sh') or 0
                        d['xg'] += j.get('xg') or 0
                        d['min'] += j.get('min') or 0
                        if _es_def(j):
                            d['min_def'] += j.get('min') or 0
                        d['mv'] = max(d['mv'], j.get('mv') or 0)
                habit = {pid: d for pid, d in info.items()
                         if d['tit'] >= len(prev) / 2}
                aus = {pid: d for pid, d in habit.items() if pid not in conv}
                mv_hab = sum(d['mv'] for d in habit.values()) or 1.0
                fila.update({
                    'n_habit': len(habit), 'n_bajas': len(aus),
                    'ataque': sum(d['sh'] for d in aus.values()) / sh_tot,
                    'ataque_xg': sum(d['xg'] for d in aus.values()) / xg_tot,
                    'defensa': sum(d['min_def'] for d in aus.values()) / min_def,
                    'valor': sum(d['mv'] for d in aus.values()) / mv_hab,
                    'bajas_nombres': '; '.join(str(d['n']) for d in
                                               aus.values())})
            filas.append(fila)
            hist.setdefault(tid, []).append({
                'jug': jug, 'sh_eq': t.get('tiros'), 'xg_eq': t.get('xg'),
                'min_def': sum((j.get('min') or 0) for j in jug if _es_def(j))})
    return pd.DataFrame(filas)


def _es_def(j) -> bool:
    pos = j.get('pos')
    if pos is not None:
        return pos // 10 <= 4               # portero y zaga
    return j.get('up') in (0, 1)


def cruzar(f: pd.DataFrame) -> pd.DataFrame:
    """Cada partido del fondo con su λ de producción del ledger."""
    import name_mapper as nm
    led = pd.read_csv('pick_ledger_totales.csv', low_memory=False)
    led = led[led['fecha'] >= '2023-07-01']
    led['home'] = led['match_id'].str.split('_').str[1].str.replace('-', ' ')
    led['away'] = led['match_id'].str.split('_').str[2].str.replace('-', ' ')
    loc = f[f['local'] == 1].set_index('mid')
    vis = f[f['local'] == 0].set_index('mid')
    par = loc.join(vis, rsuffix='_v', how='inner')
    fuera = []
    for liga, g in par.groupby('liga'):
        l = led[led['liga'] == liga]
        if l.empty:
            continue
        cat = sorted(set(l['home']) | set(l['away']))
        mapa = {}
        for n in set(g['eq']) | set(g['eq_v']):
            mapa[n] = nm.mapear(n, cat, contexto='v308_bajas')
        l_idx = {(r.fecha, r.home): r for r in l.itertuples()}
        for mid, r in g.iterrows():
            h = mapa.get(r['eq'])
            if not h:
                continue
            fe = pd.Timestamp(r['fecha'])
            hit = None
            for dd in (0, -1, 1):
                k = ((fe + pd.Timedelta(days=dd)).strftime('%Y-%m-%d'), h)
                if k in l_idx:
                    hit = l_idx[k]
                    break
            if hit is None:
                continue
            fuera.append({**r.to_dict(), 'mid': mid, 'lam_h': hit.lam_h,
                          'lam_a': hit.lam_a,
                          'gl': hit.goles_local, 'gv': hit.goles_visit})
    return pd.DataFrame(fuera)


# --------------------------------------------------------------------------
def pois_ll(y, lam):
    from scipy.special import gammaln
    lam = np.clip(lam, 1e-6, None)
    return y * np.log(lam) - lam - gammaln(y + 1)


def p_1x2(lh, la, n=11):
    from scipy.stats import poisson
    k = np.arange(n)
    ph = poisson.pmf(k[None, :], lh[:, None])
    pa = poisson.pmf(k[None, :], la[:, None])
    m = ph[:, :, None] * pa[:, None, :]
    home = np.tril(np.ones((n, n)), -1)
    draw = np.eye(n)
    return ((m * home[None]).sum((1, 2)), (m * draw[None]).sum((1, 2)),
            (m * home.T[None]).sum((1, 2)))


def ajusta(d, rasgos_h, rasgos_a):
    """β por máxima verosimilitud Poisson (goles local y visitante)."""
    from scipy.optimize import minimize
    X_h = d[rasgos_h].to_numpy(float)
    X_a = d[rasgos_a].to_numpy(float)
    yh, ya = d['gl'].to_numpy(float), d['gv'].to_numpy(float)
    lh, la = d['lam_h'].to_numpy(float), d['lam_a'].to_numpy(float)

    def nll(b):
        return -(pois_ll(yh, lh * np.exp(X_h @ b)).sum()
                 + pois_ll(ya, la * np.exp(X_a @ b)).sum())
    r = minimize(nll, np.zeros(len(rasgos_h)), method='BFGS')
    return r.x


def metricas(d, b, rasgos_h, rasgos_a):
    lh0, la0 = d['lam_h'].to_numpy(float), d['lam_a'].to_numpy(float)
    lh1 = lh0 * np.exp(d[rasgos_h].to_numpy(float) @ b)
    la1 = la0 * np.exp(d[rasgos_a].to_numpy(float) @ b)
    yh, ya = d['gl'].to_numpy(float), d['gv'].to_numpy(float)
    ll0 = pois_ll(yh, lh0) + pois_ll(ya, la0)
    ll1 = pois_ll(yh, lh1) + pois_ll(ya, la1)
    from scipy.stats import poisson
    o0 = 1 - poisson.cdf(2, lh0 + la0)
    o1 = 1 - poisson.cdf(2, lh1 + la1)
    yo = ((yh + ya) > 2.5).astype(float)

    def lg(y, p):
        p = np.clip(p, 1e-6, 1 - 1e-6)
        return y * np.log(p) + (1 - y) * np.log(1 - p)
    ou = lg(yo, o1) - lg(yo, o0)
    h0, e0, a0 = p_1x2(lh0, la0)
    h1, e1, a1 = p_1x2(lh1, la1)
    res = np.where(yh > ya, 0, np.where(yh == ya, 1, 2))
    p0 = np.choose(res, [h0, e0, a0])
    p1 = np.choose(res, [h1, e1, a1])
    x12 = np.log(np.clip(p1, 1e-9, 1)) - np.log(np.clip(p0, 1e-9, 1))
    return {'goles': ll1 - ll0, 'ou25': ou, '1x2': x12}


def resumen(dif: np.ndarray, rng) -> dict:
    bs = [dif[rng.integers(0, len(dif), len(dif))].mean() for _ in range(B)]
    return {'mejora': round(float(dif.mean()), 6),
            'p5': round(float(np.percentile(bs, 5)), 6)}


HIPOTESIS = {
    'H1_ataque': (['ataque'], ['ataque_v']),
    'H1b_ataque_xg': (['ataque_xg'], ['ataque_xg_v']),
    'H2_defensa_rival': (['defensa_v'], ['defensa']),
    'H3_valor': (['valor', 'valor_v'], ['valor_v', 'valor']),
    'H4_numero': (['n_bajas', 'n_bajas_v'], ['n_bajas_v', 'n_bajas']),
    'H5_ataque_y_defensa': (['ataque', 'defensa_v'], ['ataque_v', 'defensa']),
    'H6_xg_y_defensa': (['ataque_xg', 'defensa_v'],
                        ['ataque_xg_v', 'defensa']),
}


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    f = cargar_fondo()
    print('equipo-partido', len(f), 'con historia', int(f['n_habit'].notna().sum()))
    d = cruzar(f)
    d = d.dropna(subset=['lam_h', 'lam_a', 'gl', 'gv', 'ataque', 'ataque_v'])
    d = d.sort_values('fecha').reset_index(drop=True)
    print('partidos cruzados con el ledger', len(d))
    corte = d['fecha'].quantile(0.7) if False else d['fecha'].iloc[int(len(d) * 0.7)]
    ele, jui = d[d['fecha'] < corte], d[d['fecha'] >= corte]
    rng = np.random.default_rng(308)
    doc = {'partidos': int(len(d)), 'corte': corte,
           'bajas_medias': {c: round(float(d[c].mean()), 4)
                            for c in ('n_bajas', 'ataque', 'defensa', 'valor')},
           'con_alguna_baja': round(float((d['n_bajas'] > 0).mean()), 3),
           'hipotesis': {}}
    for nombre, (rh, ra) in HIPOTESIS.items():
        b = ajusta(ele, rh, ra)
        r = {'beta': [round(float(x), 4) for x in b]}
        for tramo, x in (('eleccion', ele), ('juicio', jui)):
            m = metricas(x, b, rh, ra)
            r[tramo] = {k: resumen(v, rng) for k, v in m.items()}
        r['pasa'] = {k: (r['eleccion'][k]['p5'] > 0
                         and r['juicio'][k]['p5'] > 0)
                     for k in ('goles', 'ou25', '1x2')}
        doc['hipotesis'][nombre] = r
        print(nombre, json.dumps(r, ensure_ascii=False))
    # efecto medido en goles, por tamaño de la baja de ataque
    d['tramo_ataque'] = pd.cut(d['ataque'], [-0.01, 0.0, 0.1, 0.2, 0.3, 1.0])
    g = d.groupby('tramo_ataque', observed=True).agg(
        n=('gl', 'size'), goles=('gl', 'mean'), lam=('lam_h', 'mean'))
    doc['local_por_baja_de_ataque'] = {str(k): {'n': int(v.n),
                                                'goles': round(v.goles, 3),
                                                'lam_prod': round(v.lam, 3)}
                                       for k, v in g.iterrows()}
    print(json.dumps(doc['local_por_baja_de_ataque'], ensure_ascii=False))
    with open(SALIDA, 'w', encoding='utf-8') as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=1, default=str)


if __name__ == '__main__':
    main()
