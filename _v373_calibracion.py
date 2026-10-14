#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v373 — H1 · Corregir la probabilidad de la casa antes de elegir.

El usuario (12-oct): soñadoras de N patas (4 a 25+) donde PUEDA ELEGIR LA
CUOTA MÍNIMA POR PATA (1,30 · 1,45 · 1,60 · 1,70 · 1,80, como el «booster
+20 %» de Draftea que pide cada selección ≥ 1,60), con patas sólidas «de
acuerdo con la casa, pero un paso adelante de la casa».

HIPÓTESIS H1. El reparto PROPORCIONAL del margen (lo que usamos hoy para «la
casa sin margen») subestima el lado más probable —el sesgo favorito-sorpresa—
y por eso «Casa 70/130» acierta ~7 pts más de lo que la casa promete. Si se
quita el margen de otra forma, o se corrige con lo ya jugado, la probabilidad
corregida debería (1) calibrar mejor y (2) permitir la misma regla a cuotas
más altas: «p_corregida ≥ umbral y cuota ≥ piso».

FORMAS DE QUITAR EL MARGEN (todas sólo con las cuotas de la propia casa)
  proporcional — p = (1/c) / Σ(1/c)              (la de hoy)
  aditivo      — p = 1/c − margen / n            (margen igual a cada lado)
  potencia     — p = (1/c)^k, k tal que Σ = 1
  shin         — Shin (1993): z de «informados», p = [√(z²+4(1−z)π²/Σπ) − z]/[2(1−z)]
  logit        — logit p = logit(1/c) − d, d tal que Σ = 1 (razón de momios)
  logistica    — recalibración logística por mercado y lado sobre la
                 proporcional (logit, margen, lado, mercado) entrenada
                 WALK-FORWARD: Playdoit día por día (tras 7 días), histórico
                 trimestre por trimestre; sólo con lo anterior.
  isotonica    — isotónica por familia (mercado × lado) sobre la
                 proporcional, igual de walk-forward («por banda»).

DATOS
  (a) PLAYDOIT, escaleras con resultado (`_v371_sencillas.playdoit`, ambos
      lados de cada línea: goles, córners, tiros, a puerta, tarjetas; total y
      por equipo; 28-ago → 9-oct). Universo principal = el de producción (sin
      tarjetas ni córners de equipo); variante con todo.
  (b) HISTÓRICO, 87 ligas (`_v371b_ganador.cargar`): 1X2 desde 2010 y más /
      menos 2,5 desde 2019, cuota de la casa (Pinnacle sólo como referencia
      de calibración: no es simultáneo con Playdoit).

PROTOCOLO
  · Sólo entran las patas con predicción de TODOS los métodos (Playdoit desde
    el día 8, histórico desde 2011 y el más/menos tras su primer trimestre).
  · Dos mitades por fecha (A / B). El umbral de cada método y el método
    mismo se eligen en A con un criterio declarado antes de mirar B: el
    mayor p5 (bootstrap por partido, pesos de Poisson) de la diferencia de
    acierto contra la línea base, con al menos 60 patas y 3 patas por día.
  · LÍNEA BASE: «la casa elige» — la pata más probable según la casa
    proporcional, una por partido, en el MISMO piso (cuota en [piso, piso+0,5]).
  · Pasa sólo si mejora a la línea base en las dos mitades con p5 > 0.
  · También: la regla elegida contra «proporcional con umbral» (Casa u/piso,
    la generalización directa de Casa 70/130); cada método contra la
    proporcional A IGUAL VOLUMEN (umbral que en A da 3 / 5 / 8 patas por día,
    fijado sin mirar el acierto; p5 pareado por partido en A y en B), que es
    la prueba limpia de H1; los métodos fijos de Playdoit también en los 34
    días completos; y los boletos del día de N = 4, 6, 10, 15, 25
    patas (una por partido) sin booster y con ×1,2 / ×1,3 / ×1,8 sobre el
    momio.
  · Calibración (log-loss y Brier por pata; log-loss 1X2 de tres vías) de
    cada método, y lo que promete cada uno contra lo que pasó en las patas
    que elige la casa en cada piso.
Escribe `_v373_calibracion.json`.
"""
import importlib.util as iu
import json
import sys
import time

import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression


def _mod(nombre, fichero):
    s = iu.spec_from_file_location(nombre, fichero)
    m = iu.module_from_spec(s)
    s.loader.exec_module(m)
    return m


S = _mod('v371', '_v371_sencillas.py')
G = _mod('v371b', '_v371b_ganador.py')

rng = np.random.default_rng(373)
PISOS = (1.30, 1.45, 1.60, 1.70, 1.80)
ANCHO = 0.5
NS = (4, 6, 10, 15, 25)
BOOST = (1.0, 1.2, 1.3, 1.8)
PERDEDORES = ('tarjetas equipo', 'tarjetas total', 'corners equipo')
ESTATICOS = ('proporcional', 'aditivo', 'potencia', 'shin', 'logit')
APRENDIDOS = ('logistica', 'isotonica')
METODOS = ESTATICOS + APRENDIDOS
U = np.round(np.arange(0.30, 0.931, 0.01), 2)
MIN_N, MIN_DIA = 60, 3.0
B_SEL, B_FIN = 300, 2000
VOLUMENES = (3, 5, 8)
EPS = 1e-6
T0 = time.time()


def log(*a):
    print('[%5.0f s]' % (time.time() - T0), *a, flush=True)


# ------------------------------------------------------ quitar el margen
def _biseccion(f, lo, hi, n, it=70):
    lo, hi = np.full(n, float(lo)), np.full(n, float(hi))
    for _ in range(it):
        m = (lo + hi) / 2
        v = f(m)
        lo, hi = np.where(v > 0, m, lo), np.where(v > 0, hi, m)
    return (lo + hi) / 2


def quitar_margen(IM, metodo):
    """IM: (n, k) probabilidades implícitas 1/cuota. Devuelve (n, k) que suman 1."""
    IM = np.clip(np.asarray(IM, float), 1e-4, 0.9999)
    n, k = IM.shape
    s = IM.sum(1, keepdims=True)
    P = IM / s
    con = s[:, 0] > 1.0 + 1e-9          # sin margen (o arbitraje): proporcional
    if metodo == 'proporcional' or not con.any():
        return P
    I = IM[con]
    sc = s[con]
    if metodo == 'aditivo':
        Q = np.clip(I - (sc - 1) / k, 0.005, None)
        Q = Q / Q.sum(1, keepdims=True)
    elif metodo == 'potencia':
        e = _biseccion(lambda t: (I ** t[:, None]).sum(1) - 1, 1.0, 12.0, len(I))
        Q = I ** e[:, None]
    elif metodo == 'shin':
        def pz(z):
            z = z[:, None]
            return (np.sqrt(z ** 2 + 4 * (1 - z) * I ** 2 / sc) - z) / (2 * (1 - z))
        z = _biseccion(lambda t: pz(t).sum(1) - 1, 0.0, 0.99, len(I))
        Q = pz(z)
    elif metodo == 'logit':
        L = np.log(I / (1 - I))
        d = _biseccion(lambda t: (1 / (1 + np.exp(-(L - t[:, None])))).sum(1) - 1, -5.0, 5.0, len(I))
        Q = 1 / (1 + np.exp(-(L - d[:, None])))
    else:
        raise ValueError(metodo)
    P = P.copy()
    P[con] = Q / Q.sum(1, keepdims=True)
    return P


def _lg(p):
    p = np.clip(p, 0.005, 0.995)
    return np.log(p / (1 - p))


# ------------------------------------------------------------- (a) Playdoit
def playdoit():
    x = S.playdoit().reset_index(drop=True)
    n = len(x) // 2
    assert (x.lado_ap.iloc[:n] == 'más').all() and (x.lado_ap.iloc[n:] == 'menos').all()
    assert (x.linea.values[:n] == x.linea.values[n:]).all()
    assert (x.partido.values[:n] == x.partido.values[n:]).all()
    c = x.cuota.values
    c_otro = np.r_[c[n:], c[:n]]
    IM = np.c_[1 / c, 1 / c_otro]
    for m in ESTATICOS:
        x['p_' + m] = quitar_margen(IM, m)[:, 0]
    x['margen'] = IM.sum(1) - 1
    x['mid'] = x.partido
    x['dia'] = x.fecha.dt.strftime('%Y-%m-%d')
    x['gan'] = np.where(x.ok == 1, x.cuota - 1, -1.0)
    x['familia'] = x.mercado + '|' + x.lado_ap
    return x


def _F_playdoit(q, mercs):
    lp = _lg(q.p_proporcional.values)
    mas = (q.lado_ap.values == 'más').astype(float)
    cols = [lp * mas, q.margen.values, q.margen.values * lp, mas,
            (q.lado_real.values == 'local').astype(float), (q.lado_real.values == 'visita').astype(float)]
    for m in mercs:
        d = (q.mercado.values == m).astype(float)
        cols += [d, d * lp]
    return np.column_stack(cols)


def aprender_playdoit(x, dias_min=7):
    mercs = sorted(x.mercado.unique())
    x['p_logistica'] = np.nan
    x['p_isotonica'] = np.nan
    dias = np.sort(x.fecha.unique())
    inicio = dias[0] + np.timedelta64(dias_min, 'D')
    for d in dias[dias >= inicio]:
        tr, te = x[x.fecha < d], x[x.fecha == d]
        lr = LogisticRegression(C=1.0, max_iter=4000, fit_intercept=False)
        lr.fit(_F_playdoit(tr, mercs), tr.ok.values)
        x.loc[te.index, 'p_logistica'] = lr.predict_proba(_F_playdoit(te, mercs))[:, 1]
        glob_iso = IsotonicRegression(y_min=0.01, y_max=0.99, out_of_bounds='clip').fit(
            tr.p_proporcional.values, tr.ok.values)
        for fam, g in te.groupby('familia'):
            t = tr[tr.familia == fam]
            iso = (IsotonicRegression(y_min=0.01, y_max=0.99, out_of_bounds='clip').fit(
                t.p_proporcional.values, t.ok.values) if len(t) >= 300 else glob_iso)
            x.loc[g.index, 'p_isotonica'] = iso.predict(g.p_proporcional.values)
    return x


# ------------------------------------------------------------ (b) histórico
def historico():
    d = G.cargar().reset_index(drop=True)
    d['mid'] = d.liga + '|' + d.MATCH_ID.astype(str)
    gh, ga = d.home_goals.astype(float).values, d.away_goals.astype(float).values
    filas = []
    IM3 = 1 / d[['odd_home', 'odd_draw', 'odd_away']].values
    P3 = {m: quitar_margen(IM3, m) for m in ESTATICOS}
    pin = d[['odd_home_pin', 'odd_draw_pin', 'odd_away_pin']].values
    okp = np.isfinite(pin).all(1) & (pin > 1).all(1)
    PP = np.full(pin.shape, np.nan)
    PP[okp] = quitar_margen(1 / pin[okp], 'proporcional')
    for j, (lado, col, ok) in enumerate((('gana local', 'odd_home', gh > ga), ('empate', 'odd_draw', gh == ga),
                                         ('gana visita', 'odd_away', gh < ga))):
        f = pd.DataFrame({'mid': d.mid, 'fecha': d.fecha, 'liga': d.liga, 'mercado': '1X2', 'lado': lado,
                          'cuota': d[col].values, 'ok': ok.astype(int), 'margen': IM3.sum(1) - 1,
                          'p_pinnacle': PP[:, j]})
        for m in ESTATICOS:
            f['p_' + m] = P3[m][:, j]
        filas.append(f)
    ou = d.dropna(subset=['odd_over25', 'odd_under25'])
    ou = ou[(ou.odd_over25 > 1) & (ou.odd_under25 > 1)]
    IM2 = 1 / ou[['odd_over25', 'odd_under25']].values
    P2 = {m: quitar_margen(IM2, m) for m in ESTATICOS}
    tot = ou.home_goals.astype(float).values + ou.away_goals.astype(float).values
    for j, (lado, col, ok) in enumerate((('más de 2.5', 'odd_over25', tot > 2.5),
                                         ('menos de 2.5', 'odd_under25', tot < 2.5))):
        f = pd.DataFrame({'mid': ou.mid.values, 'fecha': ou.fecha.values, 'liga': ou.liga.values,
                          'mercado': 'OU25', 'lado': lado, 'cuota': ou[col].values, 'ok': ok.astype(int),
                          'margen': IM2.sum(1) - 1, 'p_pinnacle': np.nan})
        for m in ESTATICOS:
            f['p_' + m] = P2[m][:, j]
        filas.append(f)
    x = pd.concat(filas, ignore_index=True)
    x['dia'] = x.fecha.dt.strftime('%Y-%m-%d')
    x['gan'] = np.where(x.ok == 1, x.cuota - 1, -1.0)
    x['familia'] = x.lado
    return x, int(len(d))


LADOS_H = ('gana local', 'empate', 'gana visita', 'más de 2.5', 'menos de 2.5')


def _F_hist(q):
    lp = _lg(q.p_proporcional.values)
    cols = [q.margen.values, q.margen.values * lp]
    for l in LADOS_H:
        dd = (q.lado.values == l).astype(float)
        cols += [dd, dd * lp]
    return np.column_stack(cols)


def aprender_historico(x, max_tr=250_000):
    x['p_logistica'] = np.nan
    x['p_isotonica'] = np.nan
    trims = pd.date_range('2011-01-01', x.fecha.max() + pd.Timedelta(days=1), freq='QS')
    for q0 in trims:
        q1 = q0 + pd.DateOffset(months=3)
        te = x[(x.fecha >= q0) & (x.fecha < q1)]
        if not len(te):
            continue
        tr = x[x.fecha < q0]
        if len(tr) > max_tr:
            tr = tr.iloc[np.argsort(tr.fecha.values, kind='stable')[-max_tr:]]
        n_ou = int((tr.mercado == 'OU25').sum())
        if n_ou < 3000:
            te = te[te.mercado == '1X2']
        if not len(te):
            continue
        lr = LogisticRegression(C=1.0, max_iter=4000, fit_intercept=False)
        lr.fit(_F_hist(tr), tr.ok.values)
        x.loc[te.index, 'p_logistica'] = lr.predict_proba(_F_hist(te))[:, 1]
        for fam, g in te.groupby('familia'):
            t = tr[tr.familia == fam]
            iso = IsotonicRegression(y_min=0.01, y_max=0.99, out_of_bounds='clip').fit(
                t.p_proporcional.values, t.ok.values)
            x.loc[g.index, 'p_isotonica'] = iso.predict(g.p_proporcional.values)
    return x


# --------------------------------------------------------------- calibración
def calibracion(x, extra=()):
    out = {}
    y = x.ok.values
    for m in METODOS + tuple(extra):
        p = x['p_' + m].values
        ok = np.isfinite(p)
        pp = np.clip(p[ok], 1e-4, 1 - 1e-4)
        yy = y[ok]
        out[m] = {'n': int(ok.sum()),
                  'logloss': round(float(-np.mean(yy * np.log(pp) + (1 - yy) * np.log(1 - pp))), 5),
                  'brier': round(float(np.mean((pp - yy) ** 2)), 5),
                  'promete': round(float(pp.mean()), 4), 'pasa': round(float(yy.mean()), 4)}
    return out


def logloss_1x2(x):
    """Log-loss de tres vías (los aprendidos se normalizan a 1 por partido)."""
    z = x[x.mercado == '1X2']
    out = {}
    for m in METODOS + ('pinnacle',):
        piv = z.pivot_table(index='mid', columns='lado', values='p_' + m, aggfunc='first')
        ok = z[z.ok == 1].set_index('mid').lado
        piv = piv.dropna()
        piv = piv.div(piv.sum(axis=1), axis=0)
        ok = ok.reindex(piv.index).dropna()
        piv = piv.loc[ok.index]
        p = piv.values[np.arange(len(piv)), piv.columns.get_indexer(ok.values)]
        out[m] = {'partidos': int(len(p)), 'logloss': round(float(-np.mean(np.log(np.clip(p, 1e-4, 1)))), 5)}
    return out


def fiabilidad(x, mitad):
    """En las patas que la casa elige en cada piso: lo que promete cada método vs lo que pasó."""
    out = {}
    for piso in PISOS:
        b = elegir_base(x, piso)
        b = b[mitad(b)]
        out['%.2f' % piso] = {'n': int(len(b)), 'acierto': round(float(b.ok.mean()), 4),
                              **{m: round(float(b['p_' + m].mean()), 4) for m in METODOS}}
    return out


# ------------------------------------------------------------------ reglas
def en_piso(x, piso):
    return x[(x.cuota >= piso) & (x.cuota <= piso + ANCHO)]


def elegir_base(x, piso, col='p_proporcional'):
    return en_piso(x, piso).sort_values(col, ascending=False, kind='mergesort').drop_duplicates('mid')


class Mitad:
    """Arreglos por partido de una mitad: la línea base y la mejor pata de cada método."""

    def __init__(self, x, piso, filtro, B, metodos):
        base = elegir_base(x, piso)
        base = base[filtro(base)]
        self.mids = base.mid.values
        pos = pd.Series(np.arange(len(self.mids)), index=self.mids)
        self.M = len(self.mids)
        self.dias = base.dia.nunique()
        self.b_ok = base.ok.values.astype(np.float32)
        self.b_gan = base.gan.values.astype(np.float32)
        self.b_cuota = base.cuota.values
        self.base = base
        self.r = {}
        z = en_piso(x, piso)
        z = z[z.mid.isin(self.mids)]
        for m in metodos:
            e = z.sort_values('p_' + m, ascending=False, kind='mergesort').drop_duplicates('mid')
            i = pos.loc[e.mid.values].values
            p = np.full(self.M, -1.0)
            ok, gan, cu = (np.zeros(self.M, np.float32), np.zeros(self.M, np.float32),
                           np.zeros(self.M))
            p[i], ok[i], gan[i], cu[i] = e['p_' + m].values, e.ok.values, e.gan.values, e.cuota.values
            self.r[m] = (p, ok, gan, cu, e.set_index('mid').loc[self.mids].reset_index())
        self.W = rng.poisson(1.0, (B, self.M)).astype(np.float32) if B else None

    def punto(self, m, u):
        p, ok, gan, cu, _ = self.r[m]
        s = p >= u
        n = int(s.sum())
        if n == 0:
            return {'n': 0}
        return {'n': n, 'patas_dia': round(n / self.dias, 2), 'acierto': round(float(ok[s].mean()), 4),
                'promete': round(float(p[s].mean()), 4), 'cuota': round(float(cu[s].mean()), 3),
                'gan_100': round(100 * float(gan[s].mean()), 2),
                'dif_acierto': round(float(ok[s].mean() - self.b_ok.mean()), 4),
                'dif_gan_100': round(100 * float(gan[s].mean() - self.b_gan.mean()), 2)}

    def boot(self, m, u, W=None, otra=None):
        """p5 por partido: acierto, ganancia y las diferencias contra la base (y contra otra regla)."""
        W = self.W if W is None else W
        p, ok, gan, _, _ = self.r[m]
        s = (p >= u).astype(np.float32)
        nr = W @ s
        nr = np.where(nr > 0, nr, np.nan)
        acc = (W @ (s * ok)) / nr
        gg = (W @ (s * gan)) / nr
        nb = W.sum(1)
        accb, gb = (W @ self.b_ok) / nb, (W @ self.b_gan) / nb
        r = {'acierto_p5': acc, 'gan_p5': gg, 'dif_p5': acc - accb, 'dif_gan_p5': gg - gb}
        if otra is not None:
            p2, ok2, gan2, _, _ = self.r[otra[0]]
            s2 = (p2 >= otra[1]).astype(np.float32)
            n2 = W @ s2
            n2 = np.where(n2 > 0, n2, np.nan)
            r['vs_prop_p5'] = acc - (W @ (s2 * ok2)) / n2
            r['vs_prop_gan_p5'] = gg - (W @ (s2 * gan2)) / n2
        return r


    def boot_fin(self, m, u, otra=None, B=B_FIN, trozo=250):
        """Igual que boot, con B_FIN pesos generados por trozos (memoria)."""
        acc = {}
        for i in range(0, B, trozo):
            W = rng.poisson(1.0, (min(trozo, B - i), self.M)).astype(np.float32)
            for k, v in self.boot(m, u, W, otra).items():
                acc.setdefault(k, []).append(v)
        return {k: np.concatenate(v) for k, v in acc.items()}


def _p5(v, mult=1.0):
    v = v[np.isfinite(v)]
    return round(mult * float(np.percentile(v, 5)), 4) if len(v) else None


def elegir_umbral(MA, m):
    """En A: el umbral con mayor p5 de la diferencia de acierto (≥ 60 patas y ≥ 3 por día)."""
    mejor = None
    curva = []
    for u in U:
        pt = MA.punto(m, u)
        if pt['n'] < MIN_N or pt['n'] / MA.dias < MIN_DIA:
            continue
        p5 = _p5(MA.boot(m, u)['dif_p5'])
        curva.append((float(u), pt['n'], pt['acierto'], p5))
        if p5 is not None and (mejor is None or p5 > mejor[1] + 1e-9):
            mejor = (float(u), p5)
    return mejor, curva


def u_por_volumen(MA, m, v):
    """El umbral más alto que en A todavía da ≥ v patas por día."""
    ok = [u for u in U if MA.punto(m, u)['n'] / MA.dias >= v]
    return float(max(ok)) if ok else None


def boletos(sel, dias_mitad):
    """sel: patas elegidas (una por partido) con dia, score, ok, cuota."""
    out = {}
    for n in NS:
        L = []
        for dia, g in sel.groupby('dia'):
            if len(g) < n:
                continue
            g = g.nlargest(n, 'score')
            L.append((int(g.ok.sum()), float(np.prod(g.cuota))))
        if not L:
            out[n] = {'dias_con_boleto': 0, 'dias': int(dias_mitad)}
            continue
        bien = np.array([b for b, _ in L])
        mom = np.array([c for _, c in L])
        r = {'dias_con_boleto': len(L), 'dias': int(dias_mitad), 'enteros': int((bien == n).sum()),
             'pct_entero': round(float((bien == n).mean()), 4), 'rojas_medias': round(float((n - bien).mean()), 2),
             'momio_mediano': round(float(np.median(mom)), 2)}
        for b in BOOST:
            r['gan_100_x%.1f' % b] = round(100 * float(np.mean(np.where(bien == n, mom * b - 1, -1.0))), 1)
        out[n] = r
    return out


def evaluar(x, nombre, metodos=METODOS):
    """Todo el análisis por piso para un universo de patas x."""
    corte = x.fecha.quantile(0.5)
    fA, fB = (lambda z: z.fecha < corte), (lambda z: z.fecha >= corte)
    R = {'corte': str(corte)[:10], 'patas': int(len(x)), 'partidos': int(x.mid.nunique()),
         'dias': int(x.dia.nunique()), 'pisos': {}}
    for piso in PISOS:
        t = time.time()
        MA = Mitad(x, piso, fA, B_SEL, metodos)
        MB = Mitad(x, piso, fB, 0, metodos)
        P = {'linea_base': {
            'A': {'n': MA.M, 'patas_dia': round(MA.M / MA.dias, 2), 'acierto': round(float(MA.b_ok.mean()), 4),
                  'cuota': round(float(MA.b_cuota.mean()), 3), 'gan_100': round(100 * float(MA.b_gan.mean()), 2)},
            'B': {'n': MB.M, 'patas_dia': round(MB.M / MB.dias, 2), 'acierto': round(float(MB.b_ok.mean()), 4),
                  'cuota': round(float(MB.b_cuota.mean()), 3), 'gan_100': round(100 * float(MB.b_gan.mean()), 2)}},
             'metodos': {}}
        elegido = {}
        for m in metodos:
            mejor, curva = elegir_umbral(MA, m)
            f = {'curva_A': curva[::3]}
            if mejor is None:
                P['metodos'][m] = f
                continue
            u = mejor[0]
            elegido[m] = (u, mejor[1])
            f['umbral'] = u
            f['criterio_A'] = mejor[1]
            for t_, MM in (('A', MA), ('B', MB)):
                pt = MM.punto(m, u)
                if pt['n']:
                    bt = MM.boot_fin(m, u)
                    pt.update({k: _p5(v, 100 if 'gan' in k else 1) for k, v in bt.items()})
                f[t_] = pt
            f['frontera'] = {}
            for v in VOLUMENES:
                uv = u_por_volumen(MA, m, v)
                if uv is not None:
                    f['frontera'][v] = {'umbral': uv, 'A': MA.punto(m, uv), 'B': MB.punto(m, uv)}
            P['metodos'][m] = f
        # a IGUAL VOLUMEN (patas por día fijadas en A, sin mirar el acierto): ¿la
        # probabilidad corregida elige mejores patas que la proporcional?
        P['igual_volumen'] = {}
        for v in VOLUMENES:
            up = u_por_volumen(MA, 'proporcional', v)
            if up is None or 'proporcional' not in metodos:
                continue
            fila = {'proporcional': {'umbral': up, 'A': MA.punto('proporcional', up),
                                     'B': MB.punto('proporcional', up)}}
            for m in metodos:
                um = u_por_volumen(MA, m, v) if m != 'proporcional' else None
                if um is None:
                    continue
                fm = {'umbral': um}
                for t_, MM in (('A', MA), ('B', MB)):
                    pm, pp = MM.punto(m, um), MM.punto('proporcional', up)
                    if not (pm['n'] and pp['n']):
                        continue
                    bt = MM.boot_fin(m, um, otra=('proporcional', up), B=1000)
                    fm[t_] = {'n': pm['n'], 'patas_dia': pm['patas_dia'], 'acierto': pm['acierto'],
                              'cuota': pm['cuota'], 'gan_100': pm['gan_100'],
                              'dif_vs_prop': round(pm['acierto'] - pp['acierto'], 4),
                              'dif_vs_prop_p5': _p5(bt['vs_prop_p5']),
                              'dif_gan_vs_prop': round(pm['gan_100'] - pp['gan_100'], 2),
                              'dif_gan_vs_prop_p5': _p5(bt['vs_prop_gan_p5'], 100)}
                fila[m] = fm
            P['igual_volumen'][v] = fila
        # el método se elige en A (mismo criterio) y se juzga en B
        if elegido:
            m_ = max(elegido, key=lambda k: elegido[k][1])
            u_ = elegido[m_][0]
            fin = {'metodo': m_, 'umbral': u_}
            if 'proporcional' in elegido and m_ != 'proporcional':
                up = elegido['proporcional'][0]
                for t_, MM in (('A', MA), ('B', MB)):
                    bt = MM.boot_fin(m_, u_, otra=('proporcional', up))
                    pa, pp = MM.punto(m_, u_), MM.punto('proporcional', up)
                    if pa['n'] and pp['n']:
                        fin['vs_proporcional_' + t_] = {
                            'dif': round(pa['acierto'] - pp['acierto'], 4),
                            'dif_p5': _p5(bt['vs_prop_p5']),
                            'dif_gan_100': round(pa['gan_100'] - pp['gan_100'], 2),
                            'dif_gan_p5': _p5(bt['vs_prop_gan_p5'], 100)}
            fA_, fB_ = P['metodos'][m_].get('A', {}), P['metodos'][m_].get('B', {})
            fin['pasa'] = bool(fA_.get('dif_acierto', -1) > 0 and fB_.get('dif_acierto', -1) > 0
                               and (fA_.get('dif_p5') or -1) > 0 and (fB_.get('dif_p5') or -1) > 0)
            fin['pasa_solo_B'] = bool(fB_.get('dif_acierto', -1) > 0 and (fB_.get('dif_p5') or -1) > 0)
            # boletos del día con la regla elegida (y con la línea base)
            for t_, MM in (('A', MA), ('B', MB)):
                p, ok, gan, cu, e = MM.r[m_]
                s = p >= u_
                sel = pd.DataFrame({'dia': e.dia.values[s], 'score': p[s], 'ok': ok[s], 'cuota': cu[s]})
                fin['boletos_' + t_] = boletos(sel, MM.dias)
                bb = MM.base.assign(score=MM.base.p_proporcional)
                fin['boletos_base_' + t_] = boletos(bb[['dia', 'score', 'ok', 'cuota']], MM.dias)
            # por mercado/lado en B
            p, ok, gan, cu, e = MB.r[m_]
            s = p >= u_
            col = 'mercado' if 'lado_ap' in e else 'lado'
            e2 = e[s].copy()
            if 'lado_ap' in e2:
                e2['grupo'] = e2.mercado + ' ' + e2.lado_ap
            else:
                e2['grupo'] = e2.lado
            fin['por_grupo_B'] = {k: [int(len(g)), round(float(g.ok.mean()), 3), round(float(g.cuota.mean()), 3)]
                                  for k, g in e2.groupby('grupo') if len(g) >= 10}
            P['elegida'] = fin
        R['pisos']['%.2f' % piso] = P
        log(nombre, 'piso %.2f' % piso, 'listo en %.0f s' % (time.time() - t),
            P.get('elegida', {}).get('metodo'), P.get('elegida', {}).get('umbral'))
    R['calibracion_todo'] = calibracion(x)
    R['calibracion_B'] = calibracion(x[fB(x)])
    R['fiabilidad_B'] = fiabilidad(x, fB)
    return R


def casa_70_130(x):
    """La regla de producción tal cual (cuota 1,30-1,70, casa ≥ 70 %), en el mismo universo."""
    z = x[(x.cuota >= 1.30) & (x.cuota <= 1.70) & (x.p_proporcional >= 0.70)]
    z = z.sort_values('p_proporcional', ascending=False).drop_duplicates('mid')
    corte = x.fecha.quantile(0.5)
    out = {}
    for t, q in (('A', z[z.fecha < corte]), ('B', z[z.fecha >= corte])):
        out[t] = {'n': int(len(q)), 'acierto': round(float(q.ok.mean()), 4), 'cuota': round(float(q.cuota.mean()), 3),
                  'gan_100': round(100 * float(q.gan.mean()), 2),
                  'promete': {m: round(float(q['p_' + m].mean()), 4) for m in METODOS}}
    return out


def imprimir(nombre, R):
    print('\n==', nombre, 'corte', R['corte'], 'patas', R['patas'], 'partidos', R['partidos'], 'días', R['dias'])
    for m, c in R['calibracion_B'].items():
        print('   calib B %-12s logloss %.5f brier %.5f promete %.4f pasa %.4f' % (
            m, c['logloss'], c['brier'], c['promete'], c['pasa']))
    for piso, P in R['pisos'].items():
        lb = P['linea_base']
        print('  piso', piso, 'base A %.3f B %.3f (cuota %.2f, %.1f/día)' % (
            lb['A']['acierto'], lb['B']['acierto'], lb['B']['cuota'], lb['B']['patas_dia']))
        for m, f in P['metodos'].items():
            if 'umbral' not in f:
                print('     %-12s sin umbral válido' % m)
                continue
            a, b = f['A'], f['B']
            print('     %-12s u=%.2f | A %.3f (%s) | B n=%s acierto %s cuota %s %s/día dif %s p5 %s gan %s p5 %s' % (
                m, f['umbral'], a.get('acierto', 0), a.get('dif_p5'), b.get('n'), b.get('acierto'),
                b.get('cuota'), b.get('patas_dia'), b.get('dif_acierto'), b.get('dif_p5'), b.get('gan_100'),
                b.get('gan_p5')))
        for v, fila in P.get('igual_volumen', {}).items():
            pr = fila['proporcional']
            print('     igual volumen %s/día: prop u=%.2f B %s' % (v, pr['umbral'], {
                k: pr['B'].get(k) for k in ('n', 'acierto', 'cuota', 'gan_100')}))
            for m, fm in fila.items():
                if m == 'proporcional':
                    continue
                print('        %-12s u=%.2f A dif %s p5 %s | B dif %s p5 %s gan %s p5 %s' % (
                    m, fm['umbral'], fm.get('A', {}).get('dif_vs_prop'), fm.get('A', {}).get('dif_vs_prop_p5'),
                    fm.get('B', {}).get('dif_vs_prop'), fm.get('B', {}).get('dif_vs_prop_p5'),
                    fm.get('B', {}).get('dif_gan_vs_prop'), fm.get('B', {}).get('dif_gan_vs_prop_p5')))
        e = P.get('elegida')
        if e:
            print('     → elegida', e['metodo'], e['umbral'], 'pasa', e['pasa'], 'pasa_B', e['pasa_solo_B'],
                  {k: v for k, v in e.items() if k.startswith('vs_')})
            print('       boletos B', {n: (v.get('enteros'), v.get('dias_con_boleto'), v.get('rojas_medias'),
                                         v.get('gan_100_x1.0'), v.get('gan_100_x1.3')) for n, v in e['boletos_B'].items()})
            print('       base    B', {n: (v.get('enteros'), v.get('dias_con_boleto'), v.get('rojas_medias'),
                                         v.get('gan_100_x1.0'), v.get('gan_100_x1.3')) for n, v in e['boletos_base_B'].items()})


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    R = {'protocolo': {'pisos': PISOS, 'ancho': ANCHO, 'min_patas_A': MIN_N, 'min_patas_dia_A': MIN_DIA,
                       'criterio': 'mayor p5 (bootstrap por partido) de la diferencia de acierto vs la casa elige, en A',
                       'bootstrap_seleccion': B_SEL, 'bootstrap_final': B_FIN}}
    # ------------------------------------------------------ (a) Playdoit
    x = aprender_playdoit(playdoit())
    log('Playdoit: patas', len(x), 'con aprendidos', int(x.p_logistica.notna().sum()))
    xa = x[x.p_logistica.notna() & x.p_isotonica.notna()].copy()
    xs = xa[~xa.mercado.isin(PERDEDORES)].copy()
    R['playdoit'] = evaluar(xs, 'playdoit')
    R['playdoit']['casa_70_130'] = casa_70_130(xs)
    R['playdoit_todo'] = evaluar(xa, 'playdoit_todo')
    # sólo los métodos fijos (no necesitan historia): los 34 días completos
    xe = x[~x.mercado.isin(PERDEDORES)].copy()
    R['playdoit_fijos_34d'] = evaluar(xe, 'playdoit_fijos_34d', metodos=ESTATICOS)
    R['playdoit_fijos_34d']['casa_70_130'] = casa_70_130(xe)
    imprimir('PLAYDOIT (sin tarjetas ni córners de equipo)', R['playdoit'])
    print('   Casa 70/130 en este universo', R['playdoit']['casa_70_130'])
    imprimir('PLAYDOIT (todos los mercados)', R['playdoit_todo'])
    imprimir('PLAYDOIT (métodos fijos, 34 días)', R['playdoit_fijos_34d'])
    print('   Casa 70/130 en este universo', R['playdoit_fijos_34d']['casa_70_130'])
    json.dump(R, open('_v373_calibracion.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1,
              default=lambda o: o.item() if hasattr(o, 'item') else str(o))
    # ------------------------------------------------------ (b) histórico
    h, npart = historico()
    log('histórico: partidos', npart, 'patas', len(h))
    h = aprender_historico(h)
    log('histórico aprendido', int(h.p_logistica.notna().sum()))
    ha = h[h.p_logistica.notna() & h.p_isotonica.notna()].copy()
    R['historico'] = evaluar(ha, 'historico')
    R['historico']['partidos_cargados'] = npart
    R['historico']['casa_70_130'] = casa_70_130(ha)
    R['historico']['logloss_1x2_B'] = logloss_1x2(ha[ha.fecha >= ha.fecha.quantile(0.5)])
    hp = ha[ha.p_pinnacle.notna()]
    R['historico']['calibracion_con_pinnacle'] = calibracion(hp, extra=('pinnacle',))
    imprimir('HISTÓRICO (1X2 + más/menos 2,5)', R['historico'])
    print('   Casa 70/130 en este universo', R['historico']['casa_70_130'])
    print('   log-loss 1X2 B', R['historico']['logloss_1x2_B'])
    print('   con Pinnacle', R['historico']['calibracion_con_pinnacle'])
    json.dump(R, open('_v373_calibracion.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1,
              default=lambda o: o.item() if hasattr(o, 'item') else str(o))
    log('escrito _v373_calibracion.json')


if __name__ == '__main__':
    main()
