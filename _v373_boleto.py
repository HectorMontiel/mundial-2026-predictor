#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v373 — Armar el boleto: rutas, diversificación y boosters.

El usuario (12-oct): «soñadoras de hasta 25 patas o más; poder escoger la cuota
(1,5 · 1,6 · 1,7, hay promociones donde cada selección tiene que ser de 1,60);
patas sólidas, de acuerdo con la casa pero un paso adelante; mejores rutas,
álgebra lineal, árboles, Ishikawa si hace falta».

LA HIPÓTESIS (H5): CÓMO se arma el boleto cambia cuántas veces sale entero,
más allá de la calidad de cada pata. Se mide con las mismas patas candidatas
y se cambia sólo el armado.

DATOS (todo local, nada del futuro)
  P. PLAYDOIT, escaleras con resultado (`_v371_sencillas.playdoit`, los dos
     lados de cada línea, 28-ago → 9-oct), sin tarjetas ni córners de equipo
     (medidos perdedores, fuera también en la regla de hoy). Probabilidad = la
     casa sin margen (reparto proporcional). Aparte, el Método Casa 70/130
     (casa ≥ 70 % y cuota 1,30-1,70).
  H. HISTÓRICO (`_v371b_ganador.cargar/patas`, 87 ligas, 2010-2026): gana local,
     empate, gana visita, más y menos de 2,5, con la cuota de la casa. La hora
     de inicio NO sobrevive en las filas con cuota (todas vienen con fecha sin
     hora) y en Playdoit tampoco hay hora de inicio: la «franja horaria» no se
     puede medir con estos datos; se diversifica por liga-día y por mercado.
     (El código de la franja queda por si algún día llega la hora.)
  p̂ — la probabilidad CALIBRADA de cada pata: la casa sin margen corregida con
     lo que esa banda de la casa (de 5 en 5 pts) y ese mercado acertaron ANTES
     (día a día en P, mes a mes en H; encogida hacia la casa con 50 patas de
     peso). Sirve para el valor esperado «teórico» del boleto y para la ruta.

PISOS DE CUOTA: 1,30 · 1,45 · 1,60 · 1,70 · 1,80 (pata con cuota ≥ piso y
≤ piso + 0,5). Una pata por partido.

LAS FORMAS DE ARMAR (todas con la misma bolsa de patas del piso)
  base        — la casa elige: la más probable de cada partido según la casa y,
                en el boleto, las N más altas del día (LÍNEA BASE).
  max_momio   — la de más cuota con la casa ≥ p_min; el p_min se elige en la
                mitad A (ganancia de las patas sueltas, con ≥ 4 patas/día) y
                se juzga en B.
  valor       — la de más p̂ × cuota (valor esperado calibrado).
  div_liga2   — como base, pero a lo más 2 patas por liga y día (y en P a lo
                más N/3 del mismo mercado y lado); en H, además, 1 por liga y
                hora cuando hay hora (los simultáneos).
  sistema     — las N patas de base partidas en boletos de 2, 3 o 5, o el
                sistema «N−1 de N» (aguanta una roja).
  ruta (DP)   — «mejor ruta»: mochila de elección múltiple sobre log p̂ con la
                restricción Σ log cuota ≥ log T (momio objetivo), una por
                partido, patas de 1,15 a 2,50. Se compara contra «subir el
                momio con patas del mismo piso» (1,30 / 1,45 / 1,60 / 1,70)
                hasta llegar a T. Con piso por pata y N fijo, la ruta óptima
                ES base (las N de mayor log p): la mochila sólo importa con
                un momio total objetivo.

BOOSTERS (Draftea): el pago del boleto entero × 1,2 / 1,3 / 1,8. El +20 %
pide cada selección ≥ 1,60 y mínimo 4; a los otros se les aplica mínimo 4.

PUNTO MUERTO del booster: con el rendimiento por pata r (acierto × cuota) de
las N patas del boleto, el boleto rinde ≈ r^N y el booster que lo deja en
cero es 1 / r^N (teórico) o 1 / media(entero × momio) (real).

ISHIKAWA de las rojas: correlación por pares de los residuos (acertó − p̂)
de las patas de base de partidos distintos, por grupo: misma liga y día,
mismo día otra liga, mismo mercado y lado, misma liga y hora; bootstrap por
día. Y el exceso de rojas (observadas − esperadas por p̂) por mercado, línea
(en Playdoit), liga, banda de la casa y día de la semana.

PROTOCOLO: dos mitades por fecha (A/B); bootstrap por partido para las patas
(emparejado: los mismos partidos para la regla y para base) y por día para los
boletos (un boleto por día); la diferencia contra base en el mismo piso y la
misma N, emparejada por día. Una regla «pasa» sólo si gana a base en LAS DOS
mitades con p5 > 0.
Escribe `_v373_boleto.json`.

RESULTADO (12-oct, corre en ~3 min)
  · El armado NO cambia cuántas veces sale entero más allá de la calidad de
    las patas. Histórico (125.721 partidos): las rojas NO se agrupan entre
    partidos distintos (ρ misma liga y día 0,001 [p5 −0,004]; mismo día otra
    liga 0,000; mismo mercado y liga 0,007 [p5 −0,001]); sin exceso de rojas
    por liga, banda, mercado ni día de la semana. Diversificar por liga:
    dif. de enteros −0,2 / −0,1 pts (no). Máx. momio, valor (p̂×cuota),
    sistemas (trozos, N−1 de N) y la ruta óptima (mochila): ninguno gana a
    «la casa elige» en las dos mitades con p5 > 0.
  · Cada pata de la casa rinde ~0,96 (histórico, margen ~6 %) → el booster
    de punto muerto es ~×1,15-1,20 con 4 patas, ×1,2-1,35 con 6, ×1,3-1,6 con
    10, ×1,4-2,0 con 15 y ×2,1-4,6 con 25. El +20 % de Draftea (≥ 1,60, 4+)
    queda en punto muerto con 4 patas (1,60·4: +2,3 / −9,4 por $100) y pierde
    con más. ×1,3 con 4 patas a 1,30: +16,6 / +15,0 (p5 +6,9 / +5,1).
    ×1,8 con 4 patas: positivo en todos los pisos (p5 > 0 en las dos); con
    6 patas, p5 > 0 sólo a 1,30 (+48 / +42) y positivo sin p5 en los demás.
  · Playdoit (34 días, margen ~8,5 %) no alcanza para boletos: 13-14 días por
    mitad; se reporta pero no decide.
"""
import importlib.util as iu
import json
import math
import sys
import time

import numpy as np
import pandas as pd


def _mod(nombre, fichero):
    s = iu.spec_from_file_location(nombre, fichero)
    m = iu.module_from_spec(s)
    s.loader.exec_module(m)
    return m


V = _mod('v371', '_v371_sencillas.py')
G = _mod('v371b', '_v371b_ganador.py')
rng = np.random.default_rng(373)
PISOS = (1.30, 1.45, 1.60, 1.70, 1.80)
PISOS_BOL = (1.30, 1.45, 1.60, 1.70, 1.80)
NS = (4, 6, 10, 15, 25)
BOOST = (1.0, 1.2, 1.3, 1.8)
PERDEDORES = ('tarjetas equipo', 'tarjetas total', 'corners equipo')
NB = 1000                      # remuestreos del bootstrap
T0 = time.time()


def _t():
    return '%.0fs' % (time.time() - T0)


# ------------------------------------------------------------------ las bolsas
def bolsa_playdoit():
    x = V.playdoit()
    x = x[~x.mercado.isin(PERDEDORES)].copy()
    x['dia'] = x.fecha.dt.normalize()
    x['grupo'] = x.mercado + ' ' + x.lado_ap
    x['hora'] = np.nan
    x['clave_cal'] = x.grupo
    x['periodo'] = x.dia
    return x[['partido', 'fecha', 'dia', 'liga', 'grupo', 'linea', 'hora', 'p_c', 'cuota', 'ok',
              'clave_cal', 'periodo']].reset_index(drop=True)


def bolsa_historico():
    d = G.cargar()
    s = d['date'].astype(str)
    hora = pd.to_numeric(s.str.extract(r'\s(\d{1,2}):\d{2}')[0], errors='coerce')
    d = d.assign(hora=hora.values)
    x = G.patas(d)
    hmap = pd.Series(d.hora.values, index=(d.liga + '|' + d.MATCH_ID.astype(str)).values)
    hmap = hmap[~hmap.index.duplicated()]
    x['hora'] = x.mid.map(hmap)
    x = x.rename(columns={'mid': 'partido'})
    x['dia'] = x.fecha.dt.normalize()
    x['grupo'] = x.lado
    x['linea'] = np.nan
    x['clave_cal'] = x.lado
    x['periodo'] = x.fecha.dt.to_period('M').astype(str)
    x = x[(x.cuota > 1.0) & x.p_c.between(0.01, 0.99)]
    return x[['partido', 'fecha', 'dia', 'liga', 'grupo', 'linea', 'hora', 'p_c', 'cuota', 'ok',
              'clave_cal', 'periodo']].reset_index(drop=True)


def calibrar(x, prior=50.0):
    """p̂: la casa + (aciertos − casa) de esa banda y mercado en periodos ANTERIORES."""
    b = np.clip((x.p_c.values / 0.05).astype(int), 0, 19)
    t = pd.DataFrame({'k': x.clave_cal.values + '#' + b.astype(str), 'per': x.periodo.values,
                      'ok': x.ok.values.astype(float), 'pc': x.p_c.values})
    g = t.groupby(['k', 'per'], sort=True).agg(s_ok=('ok', 'sum'), s_pc=('pc', 'sum'),
                                                n=('ok', 'size')).reset_index()
    for c in ('s_ok', 's_pc', 'n'):
        g['c_' + c] = g.groupby('k')[c].cumsum() - g[c]
    m = t[['k', 'per']].merge(g[['k', 'per', 'c_s_ok', 'c_s_pc', 'c_n']], on=['k', 'per'], how='left')
    ph = x.p_c.values + (m.c_s_ok.values - m.c_s_pc.values) / (m.c_n.values + prior)
    return np.clip(ph, 0.01, 0.99)


# --------------------------------------------------------------- las patas
def en_piso(x, piso):
    return x[(x.cuota >= piso) & (x.cuota <= piso + 0.5)]


def una_por_partido(z, score):
    z = z.assign(score=score).sort_values('score', ascending=False, kind='mergesort')
    return z.drop_duplicates('partido')


def ordenar(z, clave='score'):
    z = z.sort_values(['dia', clave], ascending=[True, False], kind='mergesort').copy()
    z['rango'] = z.groupby('dia').cumcount()
    return z


def regla_base(x, piso):
    z = en_piso(x, piso)
    return ordenar(una_por_partido(z, z.p_c.values))


def regla_casa70(x):
    z = x[(x.p_c >= 0.70) & (x.cuota >= 1.30) & (x.cuota <= 1.70)]
    return ordenar(una_por_partido(z, z.p_c.values))


def regla_max_momio(x, piso, pmin):
    z = en_piso(x, piso)
    z = z[z.p_c >= pmin]
    z = una_por_partido(z, z.cuota.values + 1e-4 * z.p_c.values)
    return ordenar(z)


def regla_valor(x, piso):
    z = en_piso(x, piso)
    z = una_por_partido(z, z.p_hat.values * z.cuota.values)
    return ordenar(z)


def diversificar(z, n, hist):
    """base con tope: ≤ 2 por liga-día; en P ≤ ceil(N/3) por mercado-lado; en H
    ≤ 1 por liga-día-hora cuando hay hora."""
    z = z.sort_values(['dia', 'score'], ascending=[True, False], kind='mergesort').copy()
    keep = z.groupby(['dia', 'liga']).cumcount() < 2
    if hist:
        con_h = z.hora.notna()
        k2 = z[con_h].groupby(['dia', 'liga', 'hora']).cumcount() < 1
        keep &= ~con_h | k2.reindex(z.index, fill_value=True)
    else:
        keep &= z.groupby(['dia', 'grupo']).cumcount() < math.ceil(n / 3)
    z = z[keep].copy()
    z['rango'] = z.groupby('dia').cumcount()
    return z


# -------------------------------------------------------------- los boletos
def boletos_de(z, n):
    """Un boleto por día: las primeras n por `rango`. Días con menos de n: fuera."""
    t = z[z.rango < n]
    cnt = t.groupby('dia').size()
    t = t[t.dia.isin(cnt[cnt == n].index)]
    if not len(t):
        return pd.DataFrame(columns=['bien', 'lc', 'lp', 'entero', 'momio', 'p_esp'])
    t = t.assign(lc=np.log(t.cuota), lp=np.log(t.p_hat))
    g = t.groupby('dia')
    b = pd.DataFrame({'bien': g.ok.sum(), 'lc': g.lc.sum(), 'lp': g.lp.sum()})
    b['entero'] = (b.bien == n).astype(int)
    b['momio'] = np.exp(b.lc)
    b['p_esp'] = np.exp(b.lp)
    return b


def _vale(f, piso):
    """El +20 % de Draftea pide cada selección ≥ 1,60: con piso menor no aplica."""
    return not (abs(f - 1.2) < 1e-9 and piso < 1.60 - 1e-9)


def ganancias(b, n, piso):
    """gan por peso con cada booster (aplica con ≥ 4 patas; el +20 % además con piso ≥ 1,60)."""
    out = {}
    for f in BOOST:
        if not _vale(f, piso):
            continue
        ff = f if n >= 4 else 1.0
        out[f] = np.where(b.entero.values == 1, b.momio.values * ff - 1, -1.0)
    return out


def _boot_media(v, nb=NB):
    if len(v) < 2:
        return float('nan')
    idx = rng.integers(0, len(v), (nb, len(v)))
    return float(np.percentile(v[idx].mean(1), 5))


def resumen_boletos(b, n, piso, corte, base_b=None):
    r = {}
    if not len(b):
        return {'A': {'dias': 0}, 'B': {'dias': 0}, 'todo': {'dias': 0}}
    for tramo, m in (('A', b.index < corte), ('B', b.index >= corte), ('todo', np.ones(len(b), bool))):
        q = b[m]
        if not len(q):
            r[tramo] = {'dias': 0}
            continue
        gs = ganancias(q, n, piso)
        f = {'dias': int(len(q)), 'enteros': int(q.entero.sum()),
             'pct_entero': round(float(q.entero.mean()), 4),
             'p_esperada': round(float(q.p_esp.mean()), 4),
             'rojas_media': round(float(n - q.bien.mean()), 2),
             'momio_medio': round(float(q.momio.mean()), 2),
             'momio_mediana': round(float(q.momio.median()), 2)}
        for fct, g in gs.items():
            k = 'x%.1f' % fct
            f['gan_' + k] = round(100 * float(g.mean()), 1)
            f['gan_p5_' + k] = round(100 * _boot_media(g), 1)
            f['ev_esp_' + k] = round(100 * float((fct * q.momio * q.p_esp - 1).mean()), 1)
        if base_b is not None and tramo != 'todo':
            comunes = q.index.intersection(base_b.index)
            if len(comunes) >= 5:
                g1 = ganancias(q.loc[comunes], n, piso)[1.0]
                g0 = ganancias(base_b.loc[comunes], n, piso)[1.0]
                e1, e0 = q.loc[comunes].entero.values, base_b.loc[comunes].entero.values
                f['dias_comunes'] = int(len(comunes))
                f['dif_entero'] = round(float((e1 - e0).mean()), 4)
                f['dif_entero_p5'] = round(_boot_media((e1 - e0).astype(float)), 4)
                f['dif_gan'] = round(100 * float((g1 - g0).mean()), 1)
                f['dif_gan_p5'] = round(100 * _boot_media(g1 - g0), 1)
        r[tramo] = f
    return r


def sistemas(z, n, piso, corte):
    """Las n de base partidas: trozos de m (stake igual) y «n−1 de n»."""
    t = z[z.rango < n]
    cnt = t.groupby('dia').size()
    t = t[t.dia.isin(cnt[cnt == n].index)].copy()
    if not len(t):
        return {}
    out = {}
    t['lc'] = np.log(t.cuota)
    t['ic'] = 1.0 / t.cuota
    for m in (2, 3, 5):
        if m >= n:
            continue
        t['trozo'] = t.rango // m
        g = t.groupby(['dia', 'trozo'])
        tr = pd.DataFrame({'ok': g.ok.min(), 'momio': np.exp(g.lc.sum()), 'k': g.size()}).reset_index()
        res = {}
        for f in BOOST:
            if not _vale(f, piso):
                continue
            ff = np.where(tr.k >= 4, f, 1.0)
            tr['g'] = np.where(tr.ok == 1, tr.momio * ff - 1, -1.0)
            gd = tr.groupby('dia').g.mean()
            for tramo, msk in (('A', gd.index < corte), ('B', gd.index >= corte)):
                v = gd[msk].values
                res.setdefault(tramo, {'dias': int(len(v))})
                res[tramo]['gan_x%.1f' % f] = round(100 * float(v.mean()), 1) if len(v) else None
                res[tramo]['gan_p5_x%.1f' % f] = round(100 * _boot_media(v), 1) if len(v) else None
        tr['pago'] = np.where(tr.ok == 1, tr.momio, 0.0)
        pos = tr.groupby('dia').pago.mean() - 1
        for tramo, msk in (('A', pos.index < corte), ('B', pos.index >= corte)):
            res.setdefault(tramo, {})['dias_con_ganancia'] = round(float((pos[msk] > 0).mean()), 3)
            res[tramo]['algun_trozo_entero'] = round(float(
                tr[(tr.dia < corte) == (tramo == 'A')].groupby('dia').ok.max().mean()), 3)
        out['trozos de %d' % m] = res
    # n−1 de n: n boletos de n−1 patas, uno por cada pata que se deja fuera
    g = t.groupby('dia')
    dd = pd.DataFrame({'rojas': n - g.ok.sum(), 'lc': g.lc.sum(), 'inv': g.ic.sum()})
    roja_c = t[t.ok == 0].groupby('dia').cuota.first()
    dd['c_roja'] = roja_c.reindex(dd.index)
    res = {}
    for f in BOOST:
        if not _vale(f, piso):
            continue
        ff = f if n - 1 >= 4 else 1.0
        M = np.exp(dd.lc) * ff
        pago = np.where(dd.rojas == 0, M * dd.inv / n,
                        np.where(dd.rojas == 1, M / dd.c_roja.fillna(1) / n, 0.0))
        gv = pd.Series(pago - 1, index=dd.index)
        for tramo, msk in (('A', gv.index < corte), ('B', gv.index >= corte)):
            v = gv[msk].values
            res.setdefault(tramo, {'dias': int(len(v)),
                                   'cobra_algo': round(float((dd.rojas[msk] <= 1).mean()), 3)})
            res[tramo]['gan_x%.1f' % f] = round(100 * float(v.mean()), 1)
            res[tramo]['gan_p5_x%.1f' % f] = round(100 * _boot_media(v), 1)
    out['%d-1 de %d' % (n, n)] = res
    return out


# -------------------------------------------------------- patas: resumen
def _boot_pareado(q, b, nb=NB):
    """Bootstrap POR PARTIDO, emparejado: se remuestrean los partidos de la unión
    (pesos de Poisson-multinomial con bincount, sin matrices gigantes) y en cada
    remuestreo se recalculan el acierto y la ganancia de q y de b con los MISMOS
    partidos. Devuelve (gan_q, ok_q − ok_b, gan_q − gan_b) por remuestreo."""
    gq = q.groupby('partido').agg(ok=('ok', 'sum'), gan=('gan', 'sum'), n=('ok', 'size'))
    gb = b.groupby('partido').agg(ok=('ok', 'sum'), gan=('gan', 'sum'), n=('ok', 'size'))
    u = gq.index.union(gb.index)
    Q = gq.reindex(u, fill_value=0).values.astype(float)
    B = gb.reindex(u, fill_value=0).values.astype(float)
    n = len(u)
    out = np.empty((nb, 3))
    for i in range(nb):
        w = np.bincount(rng.integers(0, n, n), minlength=n).astype(float)
        sq, sb = w @ Q, w @ B
        nq, nb_ = max(sq[2], 1.0), max(sb[2], 1.0)
        out[i] = (sq[1] / nq, sq[0] / nq - sb[0] / nb_, sq[1] / nq - sb[1] / nb_)
    return out


def resumen_patas(z, base, corte):
    z = z.assign(gan=np.where(z.ok == 1, z.cuota - 1, -1.0))
    base = base.assign(gan=np.where(base.ok == 1, base.cuota - 1, -1.0))
    f = {'n': int(len(z)), 'patas_por_dia': round(float(z.groupby('dia').size().mean()), 1) if len(z) else 0}
    for tramo, m, mb in (('A', z.fecha < corte, base.fecha < corte), ('B', z.fecha >= corte, base.fecha >= corte),
                         ('todo', z.fecha.notna(), base.fecha.notna())):
        q, b = z[m], base[mb]
        if len(q) < 20:
            f[tramo] = {'n': int(len(q))}
            continue
        bs = _boot_pareado(q, b if len(b) else q)
        r = {'n': int(len(q)), 'patas_por_dia': round(float(q.groupby('dia').size().mean()), 1),
             'acierto': round(float(q.ok.mean()), 4),
             'casa': round(float(q.p_c.mean()), 4), 'p_hat': round(float(q.p_hat.mean()), 4),
             'cuota': round(float(q.cuota.mean()), 3), 'gan_100': round(100 * float(q.gan.mean()), 1),
             'gan_p5': round(100 * float(np.percentile(bs[:, 0], 5)), 1),
             'base_acierto': round(float(b.ok.mean()), 4) if len(b) else None,
             'base_cuota': round(float(b.cuota.mean()), 3) if len(b) else None,
             'base_gan_100': round(100 * float(b.gan.mean()), 1) if len(b) else None}
        if len(b) >= 20:
            r['dif'] = round(float(q.ok.mean() - b.ok.mean()), 4)
            r['dif_p5'] = round(float(np.percentile(bs[:, 1], 5)), 4)
            r['dif_gan'] = round(100 * float(q.gan.mean() - b.gan.mean()), 1)
            r['dif_gan_p5'] = round(100 * float(np.percentile(bs[:, 2], 5)), 1)
        f[tramo] = r
    return f


# ------------------------------------------------------------- Ishikawa
def correlacion(z, hist):
    """ρ de los residuos (ok − p̂) entre patas de partidos distintos, por grupo."""
    z = z.assign(r=z.ok - z.p_hat)
    z = z.assign(r2=z.r ** 2)

    def agg(cols, q=None):
        q = z if q is None else q
        g = q.groupby(cols).agg(s=('r', 'sum'), qq=('r2', 'sum'), n=('r', 'size')).reset_index()
        g['num'] = g.s ** 2 - g.qq
        g['den'] = g.n * (g.n - 1)
        return g.groupby('dia')[['num', 'den']].sum()

    dias = pd.Index(sorted(z.dia.unique()))
    base = z.groupby('dia').agg(r2=('r2', 'sum'), n=('r', 'size')).reindex(dias)
    gr = {'mismo día': agg(['dia']), 'misma liga y día': agg(['dia', 'liga']),
          'mismo mercado-lado y día': agg(['dia', 'grupo']),
          'misma liga, día y mercado-lado': agg(['dia', 'liga', 'grupo'])}
    G2 = {}
    G2['misma liga y día'] = gr['misma liga y día']
    G2['mismo día, otra liga'] = gr['mismo día'].sub(gr['misma liga y día'], fill_value=0)
    G2['misma liga y día, mismo mercado-lado'] = gr['misma liga, día y mercado-lado']
    G2['misma liga y día, otro mercado-lado'] = gr['misma liga y día'].sub(
        gr['misma liga, día y mercado-lado'], fill_value=0)
    G2['mismo mercado-lado y día, otra liga'] = gr['mismo mercado-lado y día'].sub(
        gr['misma liga, día y mercado-lado'], fill_value=0)
    if hist:
        qh = z[z.hora.notna()]
        if len(qh) > 100:
            a = agg(['dia', 'liga', 'hora'], qh)
            b = agg(['dia', 'liga'], qh)
            G2['misma liga, día y hora (simultáneos)'] = a
            G2['misma liga y día, otra hora'] = b.sub(a, fill_value=0)
    out = {}
    r2 = base.r2.values
    nn = base.n.values
    idx = rng.integers(0, len(dias), (NB, len(dias)))
    var = r2.sum() / nn.sum()
    for k, df in G2.items():
        df = df.reindex(dias).fillna(0)
        num, den = df.num.values, df.den.values
        if den.sum() <= 0:
            continue
        rho = (num.sum() / den.sum()) / var
        bs = (num[idx].sum(1) / np.maximum(den[idx].sum(1), 1)) / (r2[idx].sum(1) / nn[idx].sum(1))
        out[k] = {'rho': round(float(rho), 4), 'p5': round(float(np.percentile(bs, 5)), 4),
                  'p95': round(float(np.percentile(bs, 95)), 4), 'pares': int(den.sum() / 2)}
    return out


def exceso_rojas(z, hist):
    """Ishikawa: rojas observadas − esperadas (1 − p̂) por categoría."""
    z = z.assign(roja=1 - z.ok, esp=1 - z.p_hat, v=z.p_hat * (1 - z.p_hat),
                 banda=pd.cut(z.p_c, [0, .5, .55, .6, .65, .7, .75, .8, 1]).astype(str),
                 dsem=z.dia.dt.dayofweek.map(dict(enumerate(['lun', 'mar', 'mié', 'jue', 'vie', 'sáb', 'dom'])))
                 )
    out = {}
    cols = ('grupo', 'liga', 'banda', 'dsem') if hist else ('grupo', 'linea', 'liga', 'banda', 'dsem')
    if not hist:
        z = z.assign(linea=z.grupo + ' ' + z.linea.astype(str))
    for col in cols:
        g = z.groupby(col).agg(n=('roja', 'size'), rojas=('roja', 'sum'), esp=('esp', 'sum'), v=('v', 'sum'))
        g = g[g.n >= (200 if hist else 25)]
        g['exceso'] = g.rojas - g.esp
        g['z'] = g.exceso / np.sqrt(g.v)
        g['tasa_roja'] = g.rojas / g.n
        g['tasa_esp'] = g.esp / g.n
        g = g.sort_values('z', ascending=False)
        out[col] = {str(k): {'n': int(r.n), 'roja': round(float(r.tasa_roja), 3),
                             'esperada': round(float(r.tasa_esp), 3), 'z': round(float(r.z), 2)}
                    for k, r in g.iterrows()}
    return out


# ---------------------------------------------------------------- rutas
def _ruta_dia(part_ids, w, v, J):
    """Mochila de elección múltiple: máx Σ v con Σ w ≥ J (cap en J), una por partido."""
    upart = np.unique(part_ids)
    dp = np.full(J + 1, -np.inf)
    dp[0] = 0.0
    eleccion, origen = [], []
    for p in upart:
        ii = np.where(part_ids == p)[0]
        new = dp.copy()
        ch = np.full(J + 1, -1, dtype=np.int64)
        src = np.arange(J + 1)
        for i in ii:
            wi = int(min(w[i], J))
            cand = np.full(J + 1, -np.inf)
            s = np.arange(J + 1)
            if wi < J:
                cand[wi:J] = dp[0:J - wi]
                s[wi:J] = np.arange(0, J - wi)
            tail = dp[J - wi:J + 1]
            k = int(np.argmax(tail))
            cand[J] = tail[k]
            s[J] = J - wi + k
            cand = cand + v[i]
            better = cand > new
            new = np.where(better, cand, new)
            ch = np.where(better, i, ch)
            src = np.where(better, s, src)
        dp = new
        eleccion.append(ch)
        origen.append(src)
    if not np.isfinite(dp[J]):
        return None
    j, sel = J, []
    for ch, src in zip(reversed(eleccion), reversed(origen)):
        if ch[j] >= 0:
            sel.append(int(ch[j]))
            j = int(src[j])
    return sel


def rutas(x, objetivos, corte, max_dias=None):
    """Para cada momio objetivo T: la ruta óptima (DP) contra subir con patas
    del mismo piso, en los mismos días."""
    cand = x[(x.cuota >= 1.15) & (x.cuota <= 2.50)].copy()
    cand['lc'] = np.log(cand.cuota)
    cand['lp'] = np.log(cand.p_hat)
    # sólo la mejor pata por partido y por «escalón» de cuota de 0,05 (achica la mochila)
    cand['esc'] = (cand.cuota / 0.05).astype(int)
    cand = cand.sort_values('p_hat', ascending=False).drop_duplicates(['partido', 'esc'])
    escal = {p: regla_base(x, p) for p in (1.30, 1.45, 1.60, 1.70)}
    dias = sorted(cand.dia.unique())
    if max_dias and len(dias) > max_dias:
        dias = [dias[i] for i in sorted(rng.choice(len(dias), max_dias, replace=False))]
    R = {}
    por_dia = {d: g for d, g in cand.groupby('dia')}
    esc_dia = {p: {d: g for d, g in z.groupby('dia')} for p, z in escal.items()}
    for T in objetivos:
        J = int(math.ceil(math.log(T) / 0.01))
        filas = []
        for d in dias:
            g = por_dia.get(d)
            if g is None or g.partido.nunique() < 3:
                continue
            fila = {'dia': d}
            sel = _ruta_dia(g.partido.values, np.round(g.lc.values / 0.01).astype(int), g.lp.values, J)
            if sel is None:
                continue
            q = g.iloc[sel]
            fila['ruta'] = (int(q.ok.min()), float(np.exp(q.lc.sum())), len(q), float(np.exp(q.lp.sum())))
            for p, zd in esc_dia.items():
                h = zd.get(d)
                if h is None:
                    continue
                h = h.sort_values('rango')
                cs = np.cumsum(np.log(h.cuota.values))
                k = np.searchsorted(cs, math.log(T) - 1e-9)
                if k >= len(h):
                    continue
                hh = h.iloc[:k + 1]
                fila['piso %.2f' % p] = (int(hh.ok.min()), float(np.exp(cs[k])), k + 1,
                                         float(np.exp(np.log(hh.p_hat).sum())))
            filas.append(fila)
        if not filas:
            continue
        F = pd.DataFrame(filas).set_index('dia')
        res = {}
        for col in F.columns:
            sub = F[col].dropna()
            comunes = F[['ruta', col]].dropna().index
            for tramo, msk in (('A', sub.index < corte), ('B', sub.index >= corte)):
                s = sub[msk]
                if not len(s):
                    continue
                ok = np.array([a[0] for a in s]); mo = np.array([a[1] for a in s])
                n_p = np.array([a[2] for a in s]); pe = np.array([a[3] for a in s])
                f = {'dias': int(len(s)), 'enteros': int(ok.sum()), 'pct_entero': round(float(ok.mean()), 4),
                     'p_esperada': round(float(pe.mean()), 4), 'patas_media': round(float(n_p.mean()), 1),
                     'momio_medio': round(float(mo.mean()), 1)}
                piso_col = float(col.split()[1]) if col.startswith('piso') else 1.15
                for fct in BOOST:
                    if not _vale(fct, piso_col):
                        continue
                    ff = np.where(n_p >= 4, fct, 1.0)
                    gv = np.where(ok == 1, mo * ff - 1, -1.0)
                    f['gan_x%.1f' % fct] = round(100 * float(gv.mean()), 1)
                    f['ev_esp_x%.1f' % fct] = round(100 * float((ff * mo * pe - 1).mean()), 1)
                if col != 'ruta':
                    cm = [d for d in comunes if (d < corte) == (tramo == 'A')]
                    if len(cm) >= 5:
                        e1 = np.array([F.loc[d, 'ruta'][0] for d in cm], float)
                        e0 = np.array([F.loc[d, col][0] for d in cm], float)
                        f['ruta_menos_esta_entero'] = round(float((e1 - e0).mean()), 4)
                        f['ruta_menos_esta_p5'] = round(_boot_media(e1 - e0), 4)
                res.setdefault(col, {})[tramo] = f
        R['momio %g' % T] = res
    return R


# ------------------------------------------------------- punto muerto
def punto_muerto(x, corte):
    """¿Qué booster hace falta para que el boleto de la casa elige no pierda?
    r = rendimiento medio por pata (acierto × cuota) de las N patas del boleto
    en cada mitad; el boleto rinde ≈ r^N (las rojas no se agrupan, ver Ishikawa)
    y el booster de punto muerto es 1 / r^N. También el real: 1 / media(entero × momio)."""
    out = {}
    for piso in PISOS:
        base = regla_base(x, piso)
        for n in NS:
            t = base[base.rango < n]
            cnt = t.groupby('dia').size()
            t = t[t.dia.isin(cnt[cnt == n].index)]
            if t.dia.nunique() < 4:
                continue
            f = {}
            for tramo, m in (('A', t.fecha < corte), ('B', t.fecha >= corte)):
                q = t[m]
                if not len(q):
                    continue
                r = float((q.ok * q.cuota).mean())
                b = boletos_de(q, n)
                real = float((b.entero * b.momio).mean()) if len(b) else float('nan')
                f[tramo] = {'rend_pata': round(r, 4), 'rend_boleto_teo': round(r ** n, 4),
                            'booster_punto_muerto_teo': round(1 / r ** n, 2),
                            'rend_boleto_real': round(real, 4),
                            'booster_punto_muerto_real': round(1 / real, 2) if real > 0 else None,
                            'dias': int(len(b))}
            out['%.2f · %d' % (piso, n)] = f
    return out


# ------------------------------------------------------------- veredicto
def _estado(a, b, k, kp):
    """'pasa' si gana en A y en B con p5 > 0; 'parcial' si gana en las dos sin p5;
    'no' en otro caso."""
    va, vb = a.get(k), b.get(k)
    if va is None or vb is None:
        return 'sin datos'
    if va > 0 and vb > 0:
        pa, pb = a.get(kp), b.get(kp)
        if pa is not None and pb is not None and pa > 0 and pb > 0:
            return 'pasa'
        return 'parcial'
    return 'no'


def veredicto(R):
    V_ = {'patas': {}, 'boletos': {}, 'ev_positivo': [], 'sistemas_ev_positivo': [], 'rutas': {}}
    for piso, P in R['patas_por_piso'].items():
        for k in ('max_momio', 'valor', 'top6_del_dia', 'casa70'):
            if k in P and 'A' in P[k] and 'B' in P[k]:
                V_['patas']['%s %s' % (piso, k)] = {
                    'ganancia': _estado(P[k]['A'], P[k]['B'], 'dif_gan', 'dif_gan_p5'),
                    'acierto': _estado(P[k]['A'], P[k]['B'], 'dif', 'dif_p5')}
    for clave, fila in R['boletos'].items():
        piso = float(clave.split('·')[0].replace(',', '.'))
        for regla, r in fila.items():
            a, b = r.get('A', {}), r.get('B', {})
            if regla != 'base':
                V_['boletos']['%s %s' % (clave, regla)] = {
                    'ganancia': _estado(a, b, 'dif_gan', 'dif_gan_p5'),
                    'entero': _estado(a, b, 'dif_entero', 'dif_entero_p5')}
            for f in BOOST:
                if not _vale(f, piso):
                    continue
                k = 'gan_x%.1f' % f
                if a.get(k) is not None and b.get(k) is not None and a[k] > 0 and b[k] > 0:
                    V_['ev_positivo'].append({
                        'boleto': clave, 'regla': regla, 'booster': f,
                        'gan_A': a[k], 'gan_B': b[k], 'p5_A': a.get('gan_p5_' + k[4:]),
                        'p5_B': b.get('gan_p5_' + k[4:]),
                        'p5_positivo_en_las_dos': bool((a.get('gan_p5_' + k[4:]) or -1) > 0
                                                       and (b.get('gan_p5_' + k[4:]) or -1) > 0),
                        'enteros_A': '%s/%s' % (a.get('enteros'), a.get('dias')),
                        'enteros_B': '%s/%s' % (b.get('enteros'), b.get('dias'))})
    for clave, S in R['sistemas'].items():
        for forma, r in S.items():
            a, b = r.get('A', {}), r.get('B', {})
            for f in BOOST:
                k = 'gan_x%.1f' % f
                if a.get(k) is not None and b.get(k) is not None and a[k] > 0 and b[k] > 0:
                    V_['sistemas_ev_positivo'].append({'boleto': clave, 'forma': forma, 'booster': f,
                                                       'gan_A': a[k], 'gan_B': b[k],
                                                       'p5_A': a.get('gan_p5_x%.1f' % f),
                                                       'p5_B': b.get('gan_p5_x%.1f' % f)})
    for T, res in R.get('rutas', {}).items():
        for col, v in res.items():
            if col == 'ruta':
                continue
            a, b = v.get('A', {}), v.get('B', {})
            V_['rutas']['%s ruta vs %s' % (T, col)] = _estado(a, b, 'ruta_menos_esta_entero',
                                                              'ruta_menos_esta_p5')
    return V_


# ----------------------------------------------------------------- todo
def elegir_pmin(x, piso, corte, minimo_dia=4.0):
    """p_min de max_momio: en A, la ganancia de las patas sueltas más alta con ≥ 4 patas/día."""
    grid = np.round(np.arange(0.40, 0.80, 0.025), 3)
    mejor, tabla = None, {}
    xa = x[x.fecha < corte]
    for pm in grid:
        z = regla_max_momio(xa, piso, pm)
        if not len(z):
            continue
        pd_ = z.groupby('dia').size().mean()
        g = float(np.where(z.ok == 1, z.cuota - 1, -1).mean())
        tabla[float(pm)] = (round(100 * g, 2), round(float(pd_), 1), int(len(z)))
        if pd_ >= minimo_dia and (mejor is None or g > mejor[1]):
            mejor = (float(pm), g)
    return (mejor[0] if mejor else None), tabla


def universo(nombre, x, hist):
    print('==', nombre, len(x), 'patas', x.partido.nunique(), 'partidos', _t(), flush=True)
    x = x.copy()
    x['p_hat'] = calibrar(x)
    corte = x.fecha.quantile(0.5)
    R = {'patas': int(len(x)), 'partidos': int(x.partido.nunique()), 'dias': int(x.dia.nunique()),
         'desde': str(x.fecha.min().date()), 'hasta': str(x.fecha.max().date()), 'corte': str(corte.date()),
         'calibracion': {}, 'patas_por_piso': {}, 'boletos': {}, 'sistemas': {}, 'ishikawa': {}}
    # calibración de la casa por banda (para leer p̂)
    bb = pd.cut(x.p_c, [0, .4, .5, .55, .6, .65, .7, .75, .8, .9, 1])
    R['calibracion'] = {str(k): [int(len(g)), round(float(g.ok.mean()), 4), round(float(g.p_c.mean()), 4)]
                        for k, g in x.groupby(bb, observed=True)}
    pmins = {}
    for piso in PISOS:
        base = regla_base(x, piso)
        pm, tabla = elegir_pmin(x, piso, corte)
        pmins[piso] = pm
        reglas = {'base': base, 'valor': regla_valor(x, piso)}
        if pm is not None:
            reglas['max_momio'] = regla_max_momio(x, piso, pm)
        P = {'pmin_elegido_en_A': pm, 'pmin_tabla_A': tabla}
        for k, z in reglas.items():
            P[k] = resumen_patas(z, base, corte)
        # las N más probables del día (las patas del boleto de 6): ¿más acierto que todas?
        P['top6_del_dia'] = resumen_patas(base[base.rango < 6], base, corte)
        if piso == 1.30:
            P['casa70'] = resumen_patas(regla_casa70(x), base, corte)
        R['patas_por_piso']['%.2f' % piso] = P
        if piso in PISOS_BOL:
            for n in NS:
                bb0 = boletos_de(base, n)
                if len(bb0) < 4:
                    continue
                fila = {'base': resumen_boletos(bb0, n, piso, corte)}
                for k in ('valor', 'max_momio'):
                    if k in reglas:
                        fila[k] = resumen_boletos(boletos_de(reglas[k], n), n, piso, corte, bb0)
                fila['div_liga2'] = resumen_boletos(boletos_de(diversificar(base, n, hist), n), n, piso,
                                                    corte, bb0)
                if piso == 1.30:
                    c70 = boletos_de(regla_casa70(x), n)
                    if len(c70) >= 4:
                        fila['casa70'] = resumen_boletos(c70, n, piso, corte, bb0)
                R['boletos']['%.2f · %d' % (piso, n)] = fila
                if n in (4, 6, 10, 15, 25) and piso in (1.30, 1.45, 1.60, 1.70):
                    R['sistemas']['%.2f · %d' % (piso, n)] = sistemas(base, n, piso, corte)
        print('   piso %.2f listo (p_min %s) %s' % (piso, pm, _t()), flush=True)
    for piso in (1.30, 1.60):
        b = regla_base(x, piso)
        R['ishikawa']['%.2f' % piso] = {'correlacion': correlacion(b, hist), 'exceso_rojas': exceso_rojas(b, hist)}
    print('   ishikawa listo', _t(), flush=True)
    R['rutas'] = rutas(x, (6.5, 17.0, 50.0, 110.0), corte, max_dias=1500 if hist else None)
    print('   rutas listas', _t(), flush=True)
    R['punto_muerto'] = punto_muerto(x, corte)
    R['veredicto'] = veredicto(R)
    return R


def imprimir(nombre, R):
    print('\n######', nombre, R['desde'], '→', R['hasta'], 'corte', R['corte'])
    print('calibración', R['calibracion'])
    for piso, P in R['patas_por_piso'].items():
        print('piso', piso, 'p_min', P['pmin_elegido_en_A'])
        for k in ('base', 'top6_del_dia', 'max_momio', 'valor', 'casa70'):
            if k in P:
                f = P[k]
                print('   %-13s %5.1f/día | A %s | B %s' % (
                    k, f['patas_por_dia'],
                    {a: f['A'].get(a) for a in ('n', 'acierto', 'cuota', 'gan_100', 'dif', 'dif_p5')},
                    {a: f['B'].get(a) for a in ('n', 'acierto', 'cuota', 'gan_100', 'dif', 'dif_p5')}))
    for k, fila in R['boletos'].items():
        for regla, r in fila.items():
            a, b = r.get('A', {}), r.get('B', {})
            print('  %-11s %-10s A %s/%s (esp %.3f) ×%s gan %s/+20 %s/+80 %s ev+80 %s dif %s(%s) | '
                  'B %s/%s (esp %.3f) ×%s gan %s/+20 %s/+80 %s ev+80 %s dif %s(%s)' % (
                      k, regla, a.get('enteros'), a.get('dias'), a.get('p_esperada', 0) or 0,
                      a.get('momio_mediana'), a.get('gan_x1.0'), a.get('gan_x1.2'), a.get('gan_x1.8'),
                      a.get('ev_esp_x1.8'), a.get('dif_gan'), a.get('dif_gan_p5'),
                      b.get('enteros'), b.get('dias'), b.get('p_esperada', 0) or 0, b.get('momio_mediana'),
                      b.get('gan_x1.0'), b.get('gan_x1.2'), b.get('gan_x1.8'), b.get('ev_esp_x1.8'),
                      b.get('dif_gan'), b.get('dif_gan_p5')))
    for k, s in R['sistemas'].items():
        print('  sistema', k, {kk: {t: (v.get('gan_x1.0'), v.get('gan_x1.2'), v.get('gan_x1.8'))
                                    for t, v in vv.items() if t in ('A', 'B')} for kk, vv in s.items()})
    for piso, I in R['ishikawa'].items():
        print('  ishikawa', piso, I['correlacion'])
    for T, res in R['rutas'].items():
        for col, v in res.items():
            print('  ruta', T, col, {t: (f['enteros'], f['dias'], f['patas_media'], f['momio_medio'],
                                        f['gan_x1.0'], f['ev_esp_x1.0'], f.get('ruta_menos_esta_entero'),
                                        f.get('ruta_menos_esta_p5')) for t, f in v.items()})
    for k, f in R['punto_muerto'].items():
        print('  punto muerto', k, {t: (v['rend_pata'], v['booster_punto_muerto_teo'],
                                        v['booster_punto_muerto_real'], v['dias']) for t, v in f.items()})
    Vd = R['veredicto']
    print('  VEREDICTO patas', {k: v for k, v in Vd['patas'].items()})
    print('  VEREDICTO boletos (no «no»)', {k: v for k, v in Vd['boletos'].items()
                                           if v['ganancia'] != 'no' or v['entero'] != 'no'})
    print('  EV positivo en A y B:')
    for e in Vd['ev_positivo']:
        print('    ', e)
    print('  sistemas EV positivo:', Vd['sistemas_ev_positivo'])
    print('  rutas:', Vd['rutas'])


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    R = {}
    R['playdoit'] = universo('playdoit', bolsa_playdoit(), hist=False)
    imprimir('playdoit', R['playdoit'])
    json.dump(R, open('_v373_boleto.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1,
              default=str)
    R['historico'] = universo('historico', bolsa_historico(), hist=True)
    imprimir('historico', R['historico'])
    json.dump(R, open('_v373_boleto.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1,
              default=str)
    print('listo', _t())


if __name__ == '__main__':
    main()
