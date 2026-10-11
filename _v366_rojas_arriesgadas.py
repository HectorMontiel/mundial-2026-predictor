#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v366 — Por qué fallan las patas de «🎲 apuestas arriesgadas», y qué filtro
da más verdes sin bajar mucho la cuota.

El usuario (11-oct, 48 ✅ 36 ❌): «analiza los patrones de las que no se
cumplieron, por qué no se cumplieron, como si se hubieran cumplido, y
simulaciones para validar tu hipótesis; más verdes que rojas,
significativamente, sin arriesgar la cuota».

Datos: `_v362b_lineas.pkl` — cada línea «más de» de las escaleras de Playdoit
(la última foto antes del partido) desde el 28-ago, con la probabilidad del
Método Contexto entrenado SÓLO con lo anterior, la de la casa sin margen, la
cuota y lo que pasó. Se reconstruye la regla de hoy (`arriesgadas`): córners
total, tiros, a puerta y goles; cuota 1,45-3, método ≥ 55 %, |método − casa|
≤ 20 pts, por equipo/total la línea de más prob × cuota.

Cada hipótesis se juzga en DOS MITADES por fecha (A, B) y con bootstrap por
partido (las patas de un mismo partido caen juntas): diferencia de acierto
contra la regla de hoy, cuota media y ganancia por $100 con su p5.
Escribe `_v366_rojas_arriesgadas.json`.
"""
import json

import numpy as np
import pandas as pd

rng = np.random.default_rng(366)
MERC = {('corners', 'total'), ('tiros', 'equipo'), ('tiros', 'total'),
        ('a_puerta', 'equipo'), ('a_puerta', 'total'), ('goles', 'equipo'),
        ('goles', 'total')}
GRANDES = {'eng_premier', 'esp_laliga', 'ita_seriea', 'ger_bundesliga', 'fra_ligue1'}


def cargar():
    d = pd.read_pickle('_v362b_lineas.pkl')
    d = d[[(o, t) in MERC for o, t in zip(d.obj, d.tipo)]].copy()
    d = d[(d.p_mod - d.p_casa).abs() <= 0.20]
    d['lado'] = np.where(d.tipo == 'total', 'total', d.mu.round(4).astype(str))
    d['grupo'] = d.mid.astype(str) + '|' + d.obj + '|' + d.lado
    # el contexto del partido: goles esperados del método (total)
    g = d[(d.obj == 'goles') & (d.tipo == 'total')].groupby('mid').mu.first()
    d['goles_mu'] = d.mid.map(g)
    corte = d.fecha.quantile(0.5)
    d['tramo'] = np.where(d.fecha < corte, 'A', 'B')
    return d


def elegir(d, criterio='pxc', cmin=1.45, cmax=3.0, pmin=0.55):
    z = d[(d.c_mas >= cmin) & (d.c_mas <= cmax) & (d.p_mod >= pmin)].copy()
    z['clave'] = z.p_mod * z.c_mas if criterio == 'pxc' else z.p_mod
    z = z.sort_values('clave', ascending=False).drop_duplicates('grupo')
    z['gan'] = np.where(z.y == 1, z.c_mas - 1, -1.0)
    return z


def _boot(df, fn, n=2000):
    mids = df.mid.values
    um, inv = np.unique(mids, return_inverse=True)
    out = []
    for _ in range(n):
        s = rng.integers(0, len(um), len(um))
        w = np.bincount(s, minlength=len(um))[inv]
        out.append(fn(df, w))
    return np.array(out)


def resumen(z):
    if not len(z):
        return {'n': 0}
    roi = _boot(z, lambda q, w: (q.gan.values * w).sum() / w.sum())
    return {'n': int(len(z)), 'partidos': int(z.mid.nunique()),
            'acierto': round(float(z.y.mean()), 4), 'cuota': round(float(z.c_mas.mean()), 3),
            'prometido': round(float(z.p_mod.mean()), 4),
            'gan_100': round(100 * float(z.gan.mean()), 1),
            'gan_p5': round(100 * float(np.percentile(roi, 5)), 1)}


def contra_base(base, filtro):
    """Diferencia de acierto (filtro − base) por mitad, con p5 por partido."""
    out = {}
    for t in ('A', 'B'):
        b, f = base[base.tramo == t], filtro[filtro.tramo == t]
        if len(f) < 30:
            out[t] = {'n': int(len(f))}
            continue
        um = np.unique(b.mid.values)
        bm = b.groupby('mid').y.agg(['sum', 'count']).reindex(um).fillna(0)
        fm = f.groupby('mid').y.agg(['sum', 'count']).reindex(um).fillna(0)
        dif = []
        for _ in range(2000):
            s = rng.integers(0, len(um), len(um))
            bs, fs = bm.iloc[s].sum(), fm.iloc[s].sum()
            if fs['count'] and bs['count']:
                dif.append(fs['sum'] / fs['count'] - bs['sum'] / bs['count'])
        out[t] = dict(resumen(f), dif_acierto=round(float(f.y.mean() - b.y.mean()), 4),
                      dif_p5=round(float(np.percentile(dif, 5)), 4),
                      dif_cuota=round(float(f.c_mas.mean() - b.c_mas.mean()), 3))
    out['pasa'] = all(isinstance(out[t], dict) and out[t].get('dif_p5', -1) > 0 for t in 'AB')
    return out


def boletos(z, orden, ns=(2, 3, 4), filtro=None):
    """Una pata por partido, las `n` primeras del día según `orden`."""
    q = z if filtro is None else z[filtro(z)]
    q = q.assign(dia=q.fecha.dt.strftime('%Y-%m-%d'))
    out = {}
    for n in ns:
        sale = gan = tot = 0
        momios = []
        for _, g in q.groupby('dia'):
            g = g.sort_values(orden, ascending=False).drop_duplicates('mid').head(n)
            if len(g) < n:
                continue
            tot += 1
            m = float(np.prod(g.c_mas))
            momios.append(m)
            ok = bool(g.y.all())
            sale += ok
            gan += (m - 1) if ok else -1
        out[n] = {'dias': tot, 'salen': sale, 'pct': round(sale / tot, 3) if tot else None,
                  'momio': round(float(np.mean(momios)), 2) if momios else None,
                  'gan_100': round(100 * gan / tot, 1) if tot else None}
    return out


def main():
    d = cargar()
    base = elegir(d)
    R = {'base': resumen(base), 'base_por_mitad': {t: resumen(base[base.tramo == t]) for t in 'AB'}}

    # 1. LAS ROJAS: dónde caen y por cuánto
    roj = base[base.y == 0].copy()
    roj['falta'] = roj.linea - roj.real          # cuánto faltó (≥ 0.5)
    R['rojas'] = {
        'n': int(len(roj)),
        'por_mercado': {('%s %s' % k): {'n': int(len(g)), 'acierto_grupo': round(float(
            base[(base.obj == k[0]) & (base.tipo == k[1])].y.mean()), 3)}
            for k, g in roj.groupby(['obj', 'tipo'])},
        # «como si se hubiera cumplido»: ¿por poco o por mucho?
        'por_una_unidad': round(float((roj.falta <= 1.0).mean()), 3),
        'por_mucho_25pct': round(float((roj.real <= 0.75 * roj.linea).mean()), 3),
        # ¿caen en grupo? de los partidos con alguna roja, cuántos con 3+
        'partidos_con_roja': int(roj.mid.nunique()),
        'partidos_3_o_mas_rojas': int((roj.groupby('mid').size() >= 3).sum()),
        'rojas_en_esos': int(roj.groupby('mid').size()[lambda s: s >= 3].sum()),
    }
    # el partido que sale cerrado: ¿lo dice antes el método?
    por_p = base.groupby('mid').agg(patas=('y', 'size'), verdes=('y', 'sum'),
                                     goles_mu=('goles_mu', 'first'))
    por_p['todas_mal'] = (por_p.verdes == 0) & (por_p.patas >= 3)
    R['partido_cerrado'] = {
        'partidos_3_patas': int((por_p.patas >= 3).sum()),
        'todas_mal': int(por_p.todas_mal.sum()),
        'goles_mu_todas_mal': round(float(por_p[por_p.todas_mal].goles_mu.mean()), 3),
        'goles_mu_resto': round(float(por_p[~por_p.todas_mal & (por_p.patas >= 3)].goles_mu.mean()), 3),
    }
    # una línea más abajo: ¿cuántas rojas habrían salido y a qué cuota?
    abajo = d.set_index(['grupo', 'linea'])
    rec = cuo = 0
    n_ok = 0
    for _, r in roj.iterrows():
        k = (r.grupo, r.linea - 1.0)
        if k in abajo.index:
            x = abajo.loc[k]
            x = x.iloc[0] if isinstance(x, pd.DataFrame) else x
            n_ok += 1
            rec += int(x.y)
            cuo += float(x.c_mas)
    R['una_linea_abajo'] = {'rojas_con_linea': n_ok, 'habrian_sido_verdes': rec,
                            'cuota_media': round(cuo / n_ok, 3) if n_ok else None}

    # 2. LAS HIPÓTESIS (filtros sobre la regla de hoy)
    H = {
        'H1 cuota ≤ 1,70': lambda z: z.c_mas <= 1.70,
        'H1b cuota ≤ 1,80': lambda z: z.c_mas <= 1.80,
        'H2 casa ≥ 55 %': lambda z: z.p_casa >= 0.55,
        'H2b casa ≥ 58 %': lambda z: z.p_casa >= 0.58,
        'H3 método ≥ 60 %': lambda z: z.p_mod >= 0.60,
        'H3b método ≥ 65 %': lambda z: z.p_mod >= 0.65,
        'H4 método ≥ casa': lambda z: z.p_mod >= z.p_casa,
        'H4b método ≥ casa + 5': lambda z: z.p_mod >= z.p_casa + 0.05,
        'H4c casa ≥ método': lambda z: z.p_casa >= z.p_mod,
        'H5 sólo totales': lambda z: z.tipo == 'total',
        'H5b sólo de equipo': lambda z: z.tipo == 'equipo',
        'H6 partido abierto (goles ≥ 2,6)': lambda z: z.goles_mu >= 2.6,
        'H6b partido abierto (goles ≥ 2,9)': lambda z: z.goles_mu >= 2.9,
        'H7 ligas grandes': lambda z: z.liga.isin(GRANDES),
        'H8 sin tiros': lambda z: z.obj != 'tiros',
        'H8b sin goles': lambda z: z.obj != 'goles',
        'H8c sin a puerta': lambda z: z.obj != 'a_puerta',
        'H8d sin córners': lambda z: z.obj != 'corners',
        'H9 casa ≥ 55 % y método ≥ casa': lambda z: (z.p_casa >= 0.55) & (z.p_mod >= z.p_casa),
        'H9b casa ≥ 55 % y cuota ≤ 1,80': lambda z: (z.p_casa >= 0.55) & (z.c_mas <= 1.80),
    }
    R['hipotesis'] = {k: contra_base(base, base[f(base)]) for k, f in H.items()}
    # H10 — otra regla de línea: la MÁS PROBABLE (no la de más prob × cuota)
    alt = elegir(d, criterio='p')
    R['hipotesis']['H10 la línea más probable'] = contra_base(base, alt)
    R['hipotesis']['H10b la más probable, cuota ≥ 1,50'] = contra_base(
        base, elegir(d, criterio='p', cmin=1.50))

    # 3. LOS BOLETOS (una pata por partido; lo que enseña la app: por prob)
    R['boletos'] = {
        'hoy (por prob)': boletos(base, 'p_mod'),
        'casa ≥ 55 % (por prob)': boletos(base, 'p_mod', filtro=lambda z: z.p_casa >= 0.55),
        'cuota ≤ 1,70 (por prob)': boletos(base, 'p_mod', filtro=lambda z: z.c_mas <= 1.70),
        'por la casa': boletos(base, 'p_casa'),
    }
    json.dump(R, open('_v366_rojas_arriesgadas.json', 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1, default=str)
    print(json.dumps(R, ensure_ascii=False, indent=1, default=str))


if __name__ == '__main__':
    main()
