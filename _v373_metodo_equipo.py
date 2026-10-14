#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v373 — H4 · Método Contexto POR EQUIPO a cuota alta: ¿sabe algo que la casa no?

El usuario (12-oct) quiere soñadoras de N patas (4 a 25+) eligiendo la cuota
mínima por pata (1,30 · 1,45 · 1,60 · 1,70 · 1,80, como el booster de Draftea:
«cada selección ≥ 1,60, mínimo 4»), con patas sólidas y justificadas, «de
acuerdo con la casa, pero un paso adelante de la casa».

HIPÓTESIS (H4)
  En las líneas POR EQUIPO de Playdoit —goles del equipo (más de 0,5 / 1,5),
  tiros, tiros a puerta, córners y tarjetas del equipo; «más» y «menos»— el
  Método Contexto (λ por equipo, `tiros_equipo`) sabe algo que la casa no: donde
  ve la pata u puntos por encima de la casa sin margen (método − casa > u), la
  pata acierta más que lo que la casa elegiría en el mismo piso de cuota.

DATOS (todo local)
  · `_v362b_lineas.pkl` + `_v366_lado.pkl`: escaleras de Playdoit con resultado
    (28-ago → 9-oct), método fuera de muestra (`p_mod`), casa proporcional
    (`p_casa`); el «menos» se reconstruye como en `_v371_sencillas.playdoit`.
  · contexto del equipo (`e_v361.pkl`): cuota 1X2 de la casa (favorito / no
    favorito), días de descanso (desgaste). El partido se empata como en
    `_v366c_lado.py` (liga, fecha, totales reales). El EQUIPO de cada línea se
    saca de su λ (el método reentrenado igual que en `_v362b`, sólo con lo
    anterior al 24-ago, y la λ de la línea se pega a la del local o la de la
    visita), no del resultado: el «igual» de `_v366_lado` (los dos equipos
    sacaron lo mismo) depende del marcador —24 % de las líneas de goles,
    27 % de las de tarjetas— y dejarlo fuera sesgaba los segmentos por lado.
  · Ambos marcan: Novibet real (`_v332_novibet_patas.pkl`, 15-sep → 7-oct) con
    la λ de goles de los dos equipos: P(sí) = P(local ≥ 1) · P(visita ≥ 1).

PROTOCOLO
  Pisos 1,30 / 1,45 / 1,60 / 1,70 / 1,80 (cuota ≥ piso y ≤ piso + 0,5). Línea
  base: «la casa elige» (la pata más probable según la casa, una por partido)
  en el mismo piso, sobre TODO Playdoit (y, aparte, sólo sobre las de equipo).
  Regla: de las líneas de equipo del segmento con método − casa > u, una por
  partido, la que la casa ve más probable («la casa elige dentro de lo que el
  método respalda»). Segmentos: estadística, más/menos, local/visita,
  favorito / no favorito, distancia λ↔línea, liga, descanso; solos y de dos en
  dos, con u ∈ {0; 3; 6; 9 pts}. Se ELIGE en la mitad A (el mejor p5 de la
  diferencia de acierto contra la base, n ≥ 30) y se JUZGA en la mitad B.
  Bootstrap por partido EMPAREJADO (regla y base con los mismos partidos
  remuestreados). Boletos del día de 4/6/10/15/25 patas, con booster ×1 / ×1,2
  / ×1,3 / ×1,8 sobre el momio.
  Además, ¿la diferencia método − casa lleva información? Logística en A
  (logit casa + [logit método − logit casa]) y log-loss en B contra la casa
  sola recalibrada, y contra la casa corregida por lado × estadística (el «más»
  de equipo de Playdoit acierta 1-3 pts sobre su precio y el «menos» 1,5-3 por
  debajo: parte de lo que «sabe» el método es ese sesgo).

RESULTADO (12-oct, 642 partidos, 353 con líneas de equipo; A 28-ago→11-sep,
B 12-sep→9-oct)
  · Información: el método suma algo sobre la casa en las de equipo (log-loss B
    0,6864 → 0,6798 a cuota 1,45-2,30), pero tras corregir lado × estadística
    queda en 0,0031 y el p95 de la pérdida es +0,0007: no es firme.
  · Las patas de equipo con método − casa > 0 (cuota 1,45-2,30) aciertan 3-6 pts
    sobre la casa sin margen en las dos mitades (55,8 / 58,4 % frente a 52,9 %),
    lo justo para el margen: ganancia −3,7 / +0,9 por $100.
  · Contra «la casa elige» en el mismo piso (lo que manda el protocolo), la
    regla elegida en A NO pasa: 1,30 / 1,45 / 1,60 caen en B (−1,5, −8,0 y
    −8,2 pts); 1,70 y 1,80 quedan «parcial» (+1,6 y +5,8 pts en B, p5 −6,8 y
    −3,0). Los segmentos minados (liga, a puerta, MLS, favorito) no se
    sostienen: de 101 candidatos con p5 > 0 en A a 1,70, sólo 10 lo repiten.
  · Goles por equipo (más de 0,5 / 1,5): Playdoit los da sólo desde el 24-sep
    (55 partidos, todo en B); el método no se adelanta (53,3 % con casa 53,7 %).
    Ambos marcan (Novibet, 96 partidos): el método calibra peor que la casa.
Escribe `_v373_metodo_equipo.json`.
"""
import importlib.util as iu
import json
import os
import sys
import time
from itertools import combinations

import numpy as np
import pandas as pd


def _mod(nombre, ruta):
    s = iu.spec_from_file_location(nombre, ruta)
    m = iu.module_from_spec(s)
    s.loader.exec_module(m)
    return m


V = _mod('v371', '_v371_sencillas.py')

E_PATH = os.environ.get('V373_E', r'C:\Users\HMREY\AppData\Local\Temp\claude\D--Claude'
                                  r'\ac0b7101-79c7-47ef-8aff-6775a8d6ea8b\scratchpad\e_v361.pkl')
DESDE = pd.Timestamp('2026-08-24')
PISOS = (1.30, 1.45, 1.60, 1.70, 1.80)
ANCHO = 0.5
UMBRALES = (0.0, 0.03, 0.06, 0.09)
NS = (4, 6, 10, 15, 25)
BOOST = (1.0, 1.2, 1.3, 1.8)
NMIN = 30
NB = 2000
COL = {'corners': 'corners', 'tiros': 'tiros', 'a_puerta': 'a_puerta', 'tarjetas': 'amarillas',
       'goles': 'gf'}
rng = np.random.default_rng(373)
r4 = lambda v: None if v is None or not np.isfinite(v) else round(float(v), 4)


# ------------------------------------------------------------------ el contexto
def emparejar(d, e):
    """mid de las líneas → mid del partido en e (liga, fecha ±1, totales reales)."""
    e = e[e.fecha >= d.fecha.min() - pd.Timedelta(days=1)]
    loc = e[e.local == 1].drop_duplicates('mid').set_index('mid')
    vis = e[e.local == 0].drop_duplicates('mid').set_index('mid')
    part = {}
    for m in loc.index.intersection(vis.index):
        a, b = loc.loc[m], vis.loc[m]
        part.setdefault((a.liga, pd.Timestamp(a.fecha).normalize()), []).append(
            (m, {o: (a[c], b[c]) for o, c in COL.items()}))
    out = {}
    for mid, g in d.groupby('mid'):
        liga, fecha = g.liga.iloc[0], pd.Timestamp(g.fecha.iloc[0]).normalize()
        cands = []
        for dd in (0, -1, 1):
            cands += part.get((liga, fecha + pd.Timedelta(days=dd)), [])
        ok = []
        for em, c in cands:
            bien = True
            for r in g[g.tipo == 'total'].drop_duplicates('obj').itertuples():
                h, a = c[r.obj]
                if not (h == h and a == a and abs(h + a - r.real) < 1e-6):
                    bien = False
                    break
            for r in g[g.tipo == 'equipo'].drop_duplicates(['obj', 'real']).itertuples():
                if bien and r.real not in c[r.obj]:
                    bien = False
            if bien:
                ok.append(em)
        out[mid] = ok[0] if len(ok) == 1 else None
    return out


def lambdas(e):
    """El Método Contexto reentrenado como en `_v362b` (sólo con lo anterior al 24-ago)."""
    import lightgbm as lgb
    import tiros_equipo as te
    el, ju = e[e.fecha < DESDE], e[e.fecha >= DESDE].copy()
    ks = {}
    for obj, col in COL.items():
        a = el.dropna(subset=[col])
        m = lgb.LGBMRegressor(objective='poisson', n_estimators=700, learning_rate=0.03,
                              num_leaves=31, min_child_samples=80, subsample=0.8, subsample_freq=1,
                              colsample_bytree=0.8, reg_lambda=1.0, verbose=-1, random_state=3622)
        m.fit(a[te.COLUMNAS], a[col])
        c2 = a.fecha.quantile(0.85)
        ks[obj] = te.ajustar_k(a[a.fecha >= c2][col].values,
                               np.clip(m.predict(a[a.fecha >= c2][te.COLUMNAS]), 0.05, None))
        ju['mu_' + obj] = np.clip(m.predict(ju[te.COLUMNAS]), 0.05, None)
    return ju, ks


def con_contexto(d, e, ju):
    """Equipo de cada línea por su λ, y el contexto del equipo (1X2, descanso)."""
    emp = emparejar(d, e)
    d = d.copy()
    d['emid'] = d.mid.map(emp)
    H = ju[ju.local == 1].drop_duplicates('mid').set_index('mid')
    A = ju[ju.local == 0].drop_duplicates('mid').set_index('mid')
    eq = pd.Series(np.nan, index=d.index, dtype=object)
    conf = pd.Series(np.nan, index=d.index)
    for idx, r in d[(d.tipo == 'equipo') & d.emid.notna()].iterrows():
        m = r.emid
        if m not in H.index or m not in A.index:
            continue
        mh, ma = H.at[m, 'mu_' + r.obj], A.at[m, 'mu_' + r.obj]
        dh, da = abs(r.mu - mh), abs(r.mu - ma)
        eq[idx] = 'local' if dh < da else 'visita'
        conf[idx] = min(dh, da) / max(abs(mh - ma), 1e-6)
    d['equipo'] = eq
    d['conf_lado'] = conf
    # contexto del equipo de la línea
    cols = ['odd_w', 'odd_d', 'odd_l', 'descanso', 'r_descanso']
    for c in cols:
        d[c] = np.nan
    for lado, T in (('local', H), ('visita', A)):
        f = (d.equipo == lado) & d.emid.isin(T.index)
        for c in cols:
            d.loc[f, c] = d.loc[f, 'emid'].map(T[c]).values
    im = 1 / d[['odd_w', 'odd_d', 'odd_l']]
    d['p_1x2'] = im.odd_w / im.sum(axis=1)
    d['fav'] = np.where(d.odd_w.isna(), np.nan, np.where(d.odd_w < d.odd_l, 'favorito', 'no favorito'))
    d['desc'] = np.where(d.descanso.isna(), np.nan,
                         np.where((d.descanso <= 4) & (d.r_descanso >= 5), 'equipo con ≤4 días',
                                  np.where((d.r_descanso <= 4) & (d.descanso >= 5), 'rival con ≤4 días',
                                           'descanso parejo')))
    return d


# ------------------------------------------------------------------ el universo
def universo(d):
    """Los dos lados de cada línea (como `_v371_sencillas.playdoit`), con contexto."""
    d = d[(d.p_mod - d.p_casa).abs() <= 0.20].copy()
    d['c_menos'] = 1.0 / ((1.0 / d.c_mas) * (1 - d.p_casa) / d.p_casa)
    mas = d.assign(lado_ap='más', p_m=d.p_mod, p_c=d.p_casa, cuota=d.c_mas, ok=d.y)
    men = d.assign(lado_ap='menos', p_m=1 - d.p_mod, p_c=1 - d.p_casa, cuota=d.c_menos, ok=1 - d.y)
    x = pd.concat([mas, men], ignore_index=True)
    x['mercado'] = x.obj + ' ' + x.tipo
    x['partido'] = x.mid.astype(str)
    x['edge'] = x.p_m - x.p_c
    s = np.sqrt(x.mu.clip(lower=0.2))
    x['margen'] = np.where(x.lado_ap == 'más', (x.mu - x.linea) / s, (x.linea - x.mu) / s)
    x['banda_margen'] = pd.cut(x.margen, [-99, 0, 0.5, 99], right=False,
                               labels=['λ en contra', 'λ a favor <0,5 sd', 'λ a favor ≥0,5 sd']).astype(str)
    x['gan'] = np.where(x.ok == 1, x.cuota - 1, -1.0)
    return x


def una_por_partido(z):
    return z.sort_values(['p_c', 'edge'], ascending=False, kind='mergesort').drop_duplicates('partido')


# ------------------------------------------------- bootstrap emparejado por partido
class Mitad:
    """Una mitad y un piso: la base fija y el remuestreo de partidos compartido."""

    def __init__(self, base, dias):
        self.P = np.array(sorted(base.partido.unique()))
        self.ix = {p: i for i, p in enumerate(self.P)}
        M = len(self.P)
        self.W = rng.multinomial(M, np.full(M, 1.0 / M), size=NB).astype(np.float64)
        self.dias = max(int(dias), 1)
        self.b = self._vec(base)
        self.bW = {k: self.W @ v for k, v in self.b.items()}

    def _vec(self, z):
        M = len(self.P)
        o, n, g = np.zeros(M), np.zeros(M), np.zeros(M)
        if len(z):
            i = np.array([self.ix[p] for p in z.partido])
            np.add.at(o, i, z.ok.values)
            np.add.at(n, i, 1.0)
            np.add.at(g, i, z.gan.values)
        return {'ok': o, 'n': n, 'gan': g}

    def juzgar(self, z, completo=True):
        r = self._vec(z)
        n = int(r['n'].sum())
        out = {'n': n, 'patas_dia': round(n / self.dias, 2)}
        if n == 0:
            return out
        R = {k: self.W @ v for k, v in r.items()}
        with np.errstate(all='ignore'):
            ar, ab = R['ok'] / R['n'], self.bW['ok'] / self.bW['n']
            gr, gb = R['gan'] / R['n'], self.bW['gan'] / self.bW['n']
        dif, dg = ar - ab, gr - gb
        out.update({'acierto': r4(r['ok'].sum() / n), 'cuota': r4(z.cuota.mean()),
                    'casa': r4(z.p_c.mean()), 'metodo': r4(z.p_m.mean()),
                    'gan_100': round(100 * r['gan'].sum() / n, 1),
                    'base_acierto': r4(self.b['ok'].sum() / self.b['n'].sum()),
                    'base_cuota': None,
                    'dif': r4(r['ok'].sum() / n - self.b['ok'].sum() / self.b['n'].sum()),
                    'dif_p5': r4(np.nanpercentile(dif, 5))})
        if not completo:
            return out
        mk = (r['n'] > 0).astype(float)
        bo, bn, bg = (self.W @ (self.b[k] * mk) for k in ('ok', 'n', 'gan'))
        with np.errstate(all='ignore'):
            dm = ar - bo / bn
        out.update({'acierto_p5': r4(np.nanpercentile(ar, 5)),
                    'gan_p5': round(100 * float(np.nanpercentile(gr, 5)), 1),
                    'base_gan_100': round(100 * self.b['gan'].sum() / self.b['n'].sum(), 1),
                    'dif_gan_100': round(100 * (r['gan'].sum() / n - self.b['gan'].sum() / self.b['n'].sum()), 1),
                    'dif_gan_p5': round(100 * float(np.nanpercentile(dg, 5)), 1),
                    'base_mismos_partidos': r4((self.b['ok'] * mk).sum() / max((self.b['n'] * mk).sum(), 1)),
                    'dif_mismos_partidos_p5': r4(np.nanpercentile(dm, 5))})
        return out


def boletos(z, n, dias_tot):
    """Una pata por partido; del día, las n que la casa ve más probables."""
    filas = []
    for _, g in z.groupby(z.fecha.dt.date):
        g = g.sort_values(['p_c', 'edge'], ascending=False, kind='mergesort').head(n)
        if len(g) < n:
            continue
        filas.append((int(g.ok.sum()), float(np.prod(g.cuota))))
    if not filas:
        return {'dias_con_boleto': 0, 'dias': int(dias_tot)}
    bien = np.array([b for b, _ in filas])
    mom = np.array([m for _, m in filas])
    return {'dias_con_boleto': len(filas), 'dias': int(dias_tot), 'enteros': int((bien == n).sum()),
            'pct_entero': round(float((bien == n).mean()), 3),
            'rojas_medias': round(float((n - bien).mean()), 2),
            'momio_mediano': round(float(np.median(mom)), 2),
            'gan_100': {'x%.1f' % b: round(100 * float(np.mean(np.where(bien == n, mom * b - 1, -1.0))), 1)
                        for b in BOOST}}


# ------------------------------------------------------------------ segmentos
def dimensiones(T):
    ligas = [l for l, k in T.groupby('liga').partido.nunique().items() if k >= 25]
    return {'est': ('obj', ['goles', 'tiros', 'a_puerta', 'corners', 'tarjetas']),
            'ap': ('lado_ap', ['más', 'menos']),
            'lado': ('equipo', ['local', 'visita']),
            'fav': ('fav', ['favorito', 'no favorito']),
            'margen': ('banda_margen', ['λ en contra', 'λ a favor <0,5 sd', 'λ a favor ≥0,5 sd']),
            'liga': ('liga', sorted(ligas)),
            'desc': ('desc', ['equipo con ≤4 días', 'rival con ≤4 días', 'descanso parejo'])}


def segmentos(D):
    seg = [()]
    for k, (_, vals) in D.items():
        seg += [((k, v),) for v in vals]
    for k1, k2 in combinations(D, 2):
        for v1 in D[k1][1]:
            for v2 in D[k2][1]:
                seg.append(((k1, v1), (k2, v2)))
    return seg


def mascara(z, seg, D):
    m = np.ones(len(z), dtype=bool)
    for k, v in seg:
        m &= (z[D[k][0]].values == v)
    return m


def nombre(seg, u):
    s = ' · '.join(v for _, v in seg) if seg else 'todas las de equipo'
    return '%s · método − casa > %d pts' % (s, round(100 * u))


# ------------------------------------------------------------------ información
def informacion(x, corte):
    """¿Método − casa lleva información? Logística en A, log-loss en B (lado «más»)."""
    from sklearn.linear_model import LogisticRegression
    lg = lambda p: np.log(np.clip(p, .01, .99) / (1 - np.clip(p, .01, .99)))
    out = {}
    for nom, f in (('equipo, toda cuota', lambda q: q), ('equipo, cuota 1,45-2,30',
                                                         lambda q: q[(q.cuota >= 1.45) & (q.cuota <= 2.30)])):
        q = f(x[x.tipo == 'equipo'])     # los dos lados: sólo la cuota acota
        q = q.assign(lc=lg(q.p_c), gap=lg(q.p_m) - lg(q.p_c))
        a, b = q[q.fecha < corte], q[q.fecha >= corte]
        m1 = LogisticRegression(C=1e6, max_iter=5000).fit(a[['lc']], a.ok)
        m2 = LogisticRegression(C=1e6, max_iter=5000).fit(a[['lc', 'gap']], a.ok)
        p0 = b.p_c.clip(1e-4, 1 - 1e-4).values
        p1 = m1.predict_proba(b[['lc']])[:, 1]
        p2 = m2.predict_proba(b[['lc', 'gap']])[:, 1]
        pm = b.p_m.clip(1e-4, 1 - 1e-4).values
        ll = lambda p: -(b.ok.values * np.log(p) + (1 - b.ok.values) * np.log(1 - p))
        L0, L1, L2, Lm = ll(p0), ll(p1), ll(p2), ll(pm)
        # bootstrap por partido de la mejora (L2 − L1: negativo = el método suma)
        g = pd.DataFrame({'p': b.partido.values, 'd': L2 - L1, 'n': 1.0}).groupby('p')[['d', 'n']].sum().values
        bs = [g[i, 0].sum() / g[i, 1].sum() for i in (rng.integers(0, len(g), len(g)) for _ in range(NB))]
        # coeficiente del gap en A y en B por separado, por estadística
        por = {}
        for o, qq in q.groupby('obj'):
            cc = []
            for h in (qq[qq.fecha < corte], qq[qq.fecha >= corte]):
                if len(h) < 60 or h.ok.nunique() < 2:
                    cc.append(None)
                    continue
                cc.append(round(float(LogisticRegression(C=1e6, max_iter=5000)
                                      .fit(h[['lc', 'gap']], h.ok).coef_[0][1]), 3))
            por[o] = {'n': int(len(qq)), 'coef_gap_A': cc[0], 'coef_gap_B': cc[1]}
        # control: la casa ya trae un sesgo por lado (el «más» de equipo acierta sobre su precio
        # y el «menos» por debajo). ¿El método suma DESPUÉS de corregir lado × estadística?
        sgn = np.where(q.lado_ap == 'más', 1.0, -1.0)
        q = q.assign(s=sgn, **{'s_' + o: sgn * (q.obj == o) for o in COL})
        X0 = ['lc', 's'] + ['s_' + o for o in COL]
        a, b = q[q.fecha < corte], q[q.fecha >= corte]
        c0 = LogisticRegression(C=1e6, max_iter=5000).fit(a[X0], a.ok)
        c1 = LogisticRegression(C=1e6, max_iter=5000).fit(a[X0 + ['gap']], a.ok)
        K0 = ll(c0.predict_proba(b[X0])[:, 1])
        K1 = ll(c1.predict_proba(b[X0 + ['gap']])[:, 1])
        g = pd.DataFrame({'p': b.partido.values, 'd': K1 - K0, 'n': 1.0}).groupby('p')[['d', 'n']].sum().values
        bs2 = [g[i, 0].sum() / g[i, 1].sum() for i in (rng.integers(0, len(g), len(g)) for _ in range(NB))]
        out[nom] = {'n_A': int(len(a)), 'n_B': int(len(b)),
                    'coef_gap_A': round(float(m2.coef_[0][1]), 3),
                    'logloss_B': {'casa': r4(L0.mean()), 'casa_recalibrada': r4(L1.mean()),
                                  'casa_mas_metodo': r4(L2.mean()), 'metodo_solo': r4(Lm.mean()),
                                  'casa_con_lado_y_estadistica': r4(K0.mean()),
                                  'casa_con_lado_y_estadistica_mas_metodo': r4(K1.mean())},
                    'mejora_metodo_B': r4(L1.mean() - L2.mean()),
                    'mejora_metodo_B_p95_de_la_perdida': r4(np.percentile(bs, 95)),
                    'control_lado_estadistica': {
                        'coef_gap_A': round(float(c1.coef_[0][-1]), 3),
                        'mejora_metodo_B': r4(K0.mean() - K1.mean()),
                        'p95_de_la_perdida': r4(np.percentile(bs2, 95))},
                    'por_estadistica': por}
    return out


def estables(T, corte, D):
    """Descriptivo: cada segmento solo, cuota 1,45-2,30, ¿acierta sobre lo que promete la casa
    en las dos mitades? Una pata por partido, estadística, equipo y lado."""
    z = T[(T.cuota >= 1.45) & (T.cuota <= 2.30)]
    out = []
    for seg in [s for s in segmentos(D) if len(s) <= 1]:
        for u in (0.0, 0.06):
            q = z[mascara(z, seg, D) & (z.edge.values > u)]
            q = q.sort_values('p_c', ascending=False).drop_duplicates(['partido', 'obj', 'equipo', 'lado_ap'])
            q = q.assign(exc=q.ok - q.p_c)
            f = {'segmento': nombre(seg, u)}
            for t, h in (('A', q[q.fecha < corte]), ('B', q[q.fecha >= corte])):
                if len(h) < 15:
                    f[t] = {'n': int(len(h))}
                    continue
                f[t] = {'n': int(len(h)), 'acierto': r4(h.ok.mean()), 'casa': r4(h.p_c.mean()),
                        'metodo': r4(h.p_m.mean()), 'cuota': r4(h.cuota.mean()),
                        'exceso_vs_casa': r4(h.exc.mean()),
                        'exceso_p5': r4(np.percentile(V._boot(h, 'exc', 1000), 5)),
                        'gan_100': round(100 * float(h.gan.mean()), 1)}
            f['estable'] = bool(all(f[t].get('exceso_vs_casa') is not None and f[t]['exceso_vs_casa'] > 0
                                    for t in 'AB'))
            out.append(f)
    return out


# ------------------------------------------------------------------ ambos marcan
def _sim():
    try:
        import cuotas_multi as cm
        return cm._sim_club
    except Exception:
        from difflib import SequenceMatcher
        import unicodedata
        nn = lambda s: ''.join(ch for ch in unicodedata.normalize('NFKD', str(s)).encode('ascii', 'ignore')
                               .decode().lower() if ch.isalnum())
        return lambda a, b: SequenceMatcher(None, nn(a), nn(b)).ratio()


def ambos_marcan(ju, ks):
    """Novibet «Ambos marcan» real contra P(sí) del método (λ de goles de los dos)."""
    k = ks['goles']
    p0 = lambda mu: (k / (k + mu)) ** k
    h = ju[ju.local == 1][['mid', 'fecha', 'equipo', 'rival', 'mu_goles']].drop_duplicates('mid')
    a = ju[ju.local == 0][['mid', 'mu_goles']].drop_duplicates('mid')
    m = h.merge(a, on='mid', suffixes=('_h', '_a'))
    m['p_btts'] = (1 - p0(m.mu_goles_h)) * (1 - p0(m.mu_goles_a))
    m['dia'] = m.fecha.dt.normalize()
    n = pd.read_pickle('_v332_novibet_patas.pkl')
    n = n[n.mercado == 'Ambos marcan'].copy()
    n['im'] = 1 / n.cuota
    n = n[n.groupby('eid').im.transform('size') == 2]
    n['p_c'] = n.im / n.groupby('eid').im.transform('sum')
    sim = _sim()
    ev = n.drop_duplicates('eid')[['eid', 'fecha', 'partido']]
    casados = {}
    por_dia = {dd: g for dd, g in m.groupby('dia')}
    for r in ev.itertuples():
        if ' vs ' not in str(r.partido):
            continue
        lh, la = [s.strip() for s in r.partido.split(' vs ', 1)]
        dia = pd.Timestamp(r.fecha).normalize()
        cand = []
        for dd in (0, -1, 1):
            g = por_dia.get(dia + pd.Timedelta(days=dd))
            if g is None:
                continue
            for q in g.itertuples():
                if sim(lh, q.equipo) >= 0.8 and sim(la, q.rival) >= 0.8:
                    cand.append(q.mid)
        if len(set(cand)) == 1:
            casados[r.eid] = cand[0]
    n['emid'] = n.eid.map(casados)
    n = n[n.emid.notna()].merge(m[['mid', 'p_btts']], left_on='emid', right_on='mid')
    if n.empty:
        return {'partidos': 0}
    si = n.apuesta.str.contains('sí')
    n['p_m'] = np.where(si, n.p_btts, 1 - n.p_btts)
    n['ok'] = n.verde.astype(int)
    n['edge'] = n.p_m - n.p_c
    n['partido'] = n.eid
    n['gan'] = np.where(n.ok == 1, n.cuota - 1, -1.0)
    corte = n.fecha.quantile(0.5)
    out = {'partidos': int(n.eid.nunique()), 'corte': str(corte)[:10],
           'logloss_casa': r4(-np.mean(n.ok * np.log(n.p_c) + (1 - n.ok) * np.log(1 - n.p_c))),
           'logloss_metodo': r4(-np.mean(n.ok * np.log(n.p_m.clip(1e-4, 1 - 1e-4)) +
                                         (1 - n.ok) * np.log((1 - n.p_m).clip(1e-4, 1 - 1e-4)))),
           'pisos': {}}
    for piso in PISOS:
        z = n[(n.cuota >= piso) & (n.cuota <= piso + ANCHO)]
        fila = {}
        for u in (None,) + UMBRALES:
            q = z if u is None else z[z.edge > u]
            q = una_por_partido(q)
            fila['casa elige' if u is None else 'método − casa > %d' % round(100 * u)] = {
                t: ({'n': int(len(h)), 'acierto': r4(h.ok.mean()), 'casa': r4(h.p_c.mean()),
                     'cuota': r4(h.cuota.mean()), 'gan_100': round(100 * float(h.gan.mean()), 1)}
                    if len(h) else {'n': 0})
                for t, h in (('A', q[q.fecha < corte]), ('B', q[q.fecha >= corte]))}
        out['pisos']['%.2f' % piso] = fila
    return out


# ------------------------------------------------------------------ principal
def main():
    sys.stdout.reconfigure(encoding='utf-8')
    t0 = time.time()
    d = pd.read_pickle('_v362b_lineas.pkl').join(pd.read_pickle('_v366_lado.pkl'))
    e = pd.read_pickle(E_PATH)
    ju, ks = lambdas(e)
    print('λ reentrenadas %.0f s' % (time.time() - t0), {k: round(v, 1) for k, v in ks.items()})
    d = con_contexto(d, e, ju)
    q = d[(d.tipo == 'equipo') & d.lado_real.isin(['local', 'visita']) & d.equipo.notna()]
    acuerdo = float((q.lado_real == q.equipo).mean())
    print('equipo por λ vs lado por resultado: %.4f de %d' % (acuerdo, len(q)))
    x = universo(d)
    assert len(x) == len(V.playdoit()), 'el universo no es el de _v371'
    corte = x.fecha.quantile(0.5)
    dias = {'A': x[x.fecha < corte].fecha.dt.date.nunique(), 'B': x[x.fecha >= corte].fecha.dt.date.nunique()}
    T = x[x.tipo == 'equipo']
    D = dimensiones(T)
    SEG = segmentos(D)
    R = {'datos': {'lineas': int(len(d)), 'patas_dos_lados': int(len(x)), 'partidos': int(x.partido.nunique()),
                   'patas_equipo': int(len(T)), 'partidos_con_equipo': int(T.partido.nunique()),
                   'equipo_por_partido': {o: int(g.partido.nunique()) for o, g in T.groupby('obj')},
                   'desde': str(x.fecha.min())[:10], 'hasta': str(x.fecha.max())[:10],
                   'corte': str(corte)[:10], 'dias': dias,
                   'equipo_sin_identificar': int(T.equipo.isna().sum()),
                   'acuerdo_lado_lambda_vs_resultado': round(acuerdo, 4),
                   'ligas_segmento': D['liga'][1], 'segmentos_x_umbrales': len(SEG) * len(UMBRALES)}}
    R['informacion'] = informacion(x, corte)
    print('información', json.dumps({k: (v['coef_gap_A'], v['logloss_B'], v['mejora_metodo_B'],
                                         v['mejora_metodo_B_p95_de_la_perdida'], v['control_lado_estadistica'])
                                     for k, v in R['informacion'].items()}, ensure_ascii=False))
    R['segmentos_estables'] = estables(T, corte, D)
    R['pisos'] = {}
    for piso in PISOS:
        tp = time.time()
        band = x[(x.cuota >= piso) & (x.cuota <= piso + ANCHO)]
        Tb = band[band.tipo == 'equipo']
        mitades = {}
        for t, f in (('A', band.fecha < corte), ('B', band.fecha >= corte)):
            mitades[t] = Mitad(una_por_partido(band[f]), dias[t])
        Me = {t: Mitad(una_por_partido(Tb[(Tb.fecha < corte) if t == 'A' else (Tb.fecha >= corte)]), dias[t])
              for t in 'AB'}
        F = {'base_casa_todo_playdoit': {t: mitades[t].juzgar(una_por_partido(
                band[(band.fecha < corte) if t == 'A' else (band.fecha >= corte)]), completo=False)
            for t in 'AB'}}
        F['base_casa_solo_equipo'] = {t: mitades[t].juzgar(una_por_partido(
            Tb[(Tb.fecha < corte) if t == 'A' else (Tb.fecha >= corte)])) for t in 'AB'}
        cand = []
        TA, TB = Tb[Tb.fecha < corte], Tb[Tb.fecha >= corte]
        for seg in SEG:
            mA, mB = mascara(TA, seg, D), mascara(TB, seg, D)
            for u in UMBRALES:
                zA = una_por_partido(TA[mA & (TA.edge.values > u)])
                if len(zA) < NMIN:
                    continue
                zB = una_por_partido(TB[mB & (TB.edge.values > u)])
                cand.append({'regla': nombre(seg, u), 'seg': seg, 'u': u,
                             'A': mitades['A'].juzgar(zA), 'B': mitades['B'].juzgar(zB),
                             'A_vs_equipo': Me['A'].juzgar(zA, completo=False),
                             'B_vs_equipo': Me['B'].juzgar(zB, completo=False)})
        # la regla simple (todas las de equipo), u elegido en A
        simples = [c for c in cand if c['seg'] == ()]
        F['simple'] = (max(simples, key=lambda c: c['A']['dif_p5']) if simples else None)
        F['simple_todas_u'] = [{k: c[k] for k in ('regla', 'A', 'B')} for c in simples]
        F['candidatos_con_n'] = len(cand)
        if cand:
            pa = sorted(cand, key=lambda c: (-c['A']['dif_p5'], -c['A']['n']))
            pg = sorted(cand, key=lambda c: (-c['A']['dif_gan_p5'], -c['A']['n']))
            F['elegida_acierto'] = pa[0]
            F['elegida_ganancia'] = pg[0]
            F['top10_A_acierto'] = [{'regla': c['regla'], 'A': {k: c['A'][k] for k in ('n', 'acierto', 'cuota', 'dif', 'dif_p5')},
                                     'B': {k: c['B'].get(k) for k in ('n', 'acierto', 'cuota', 'dif', 'dif_p5')}}
                                    for c in pa[:10]]
            pos = [c for c in cand if c['A']['dif_p5'] > 0]
            F['arrastre_A_a_B'] = {'candidatos_p5A_mayor_0': len(pos),
                                   'de_esos_dif_B_mayor_0': int(sum(1 for c in pos if (c['B'].get('dif') or -1) > 0)),
                                   'de_esos_p5B_mayor_0': int(sum(1 for c in pos if (c['B'].get('dif_p5') or -1) > 0)),
                                   'todos_dif_B_mayor_0': int(sum(1 for c in cand if (c['B'].get('dif') or -1) > 0)),
                                   'todos': len(cand)}
            # boletos de la elegida por acierto y de la base
            el = F['elegida_acierto']
            zt = una_por_partido(Tb[mascara(Tb, el['seg'], D) & (Tb.edge.values > el['u'])])
            bt = una_por_partido(band)
            zs = una_por_partido(Tb[Tb.edge.values > F['simple']['u']]) if F.get('simple') else bt.iloc[:0]
            F['boletos'] = {}
            for nom, z in (('regla', zt), ('simple', zs), ('base', bt)):
                F['boletos'][nom] = {}
                for t, f in (('B', z.fecha >= corte), ('todo', z.fecha >= z.fecha.min())):
                    F['boletos'][nom][t] = {n: boletos(z[f], n, dias['B'] if t == 'B' else dias['A'] + dias['B'])
                                            for n in NS}
            # boleto «teórico» con el acierto y la cuota de la mitad B (patas independientes,
            # una por partido): (acierto · cuota)^N · booster − 1, por $1
            F['boleto_teorico_B'] = {}
            for nom, z in (('regla', zt), ('simple', zs), ('base', bt)):
                q = z[z.fecha >= corte]
                if len(q):
                    v = float(q.ok.mean() * q.cuota.mean())
                    F['boleto_teorico_B'][nom] = {'valor_pata': round(v, 4), **{
                        str(n): {'x%.1f' % b: round(100 * (v ** n * b - 1), 1) for b in BOOST} for n in NS}}
            for c in (F['elegida_acierto'], F['elegida_ganancia'], F['simple']):
                if c:
                    c['seg'] = [list(s) for s in c['seg']]
        R['pisos']['%.2f' % piso] = F
        ea = F.get('elegida_acierto')
        print('\n== piso %.2f (%d candidatos con n≥%d, %.0f s)' % (piso, len(cand), NMIN, time.time() - tp))
        print('  base todo   A', F['base_casa_todo_playdoit']['A'], '\n              B', F['base_casa_todo_playdoit']['B'])
        print('  base equipo A', {k: F['base_casa_solo_equipo']['A'].get(k) for k in ('n', 'acierto', 'cuota', 'dif', 'dif_p5')},
              '| B', {k: F['base_casa_solo_equipo']['B'].get(k) for k in ('n', 'acierto', 'cuota', 'dif', 'dif_p5')})
        if F.get('simple'):
            s = F['simple']
            print('  simple  ', s['regla'], '| A', {k: s['A'].get(k) for k in ('n', 'acierto', 'cuota', 'dif', 'dif_p5')},
                  '| B', {k: s['B'].get(k) for k in ('n', 'acierto', 'cuota', 'dif', 'dif_p5', 'gan_100')})
        if ea:
            for lab in ('elegida_acierto', 'elegida_ganancia'):
                c = F[lab]
                print('  %-16s %s\n     A %s\n     B %s' % (lab, c['regla'], {k: c['A'].get(k) for k in (
                    'n', 'acierto', 'cuota', 'gan_100', 'dif', 'dif_p5', 'dif_gan_100', 'dif_gan_p5')},
                    {k: c['B'].get(k) for k in ('n', 'acierto', 'cuota', 'gan_100', 'gan_p5', 'dif', 'dif_p5',
                                                 'dif_gan_100', 'dif_gan_p5', 'patas_dia')}))
            print('  arrastre', F['arrastre_A_a_B'])
            print('  boletos regla B', {n: (v.get('enteros'), v.get('dias_con_boleto'), v.get('gan_100'))
                                       for n, v in F['boletos']['regla']['B'].items()})
            print('  boletos simple B', {n: (v.get('enteros'), v.get('dias_con_boleto'), v.get('gan_100'))
                                        for n, v in F['boletos']['simple']['B'].items()})
            print('  boletos base  B', {n: (v.get('enteros'), v.get('dias_con_boleto'), v.get('gan_100'))
                                       for n, v in F['boletos']['base']['B'].items()})
    R['ambos_marcan_novibet'] = ambos_marcan(ju, ks)
    print('\nambos marcan', json.dumps(R['ambos_marcan_novibet'], ensure_ascii=False)[:1500])
    print('\nsegmentos estables (exceso > 0 en A y B, cuota 1,45-2,30):')
    for f in R['segmentos_estables']:
        if f['estable']:
            print('  ', f['segmento'], f['A'], f['B'])
    # veredicto: pasa si la elegida en A mejora a la base en B con p5 > 0
    ver = {}
    for p, F in R['pisos'].items():
        c = F.get('elegida_acierto')
        if not c:
            ver[p] = 'sin candidatos'
            continue
        b = c['B']
        ver[p] = ('pasa' if (c['A']['dif'] > 0 and (b.get('dif') or -1) > 0 and (b.get('dif_p5') or -1) > 0)
                  else 'parcial' if (b.get('dif') or -1) > 0 else 'no pasa')
    R['veredicto_por_piso'] = ver
    R['segundos'] = round(time.time() - t0, 1)
    print('\nveredicto', ver, '%.0f s' % (time.time() - t0))
    json.dump(R, open('_v373_metodo_equipo.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1,
              default=str)


if __name__ == '__main__':
    main()
