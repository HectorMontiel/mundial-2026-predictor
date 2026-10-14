#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v373 — Revisión escéptica de `_v373_boleto.py` (H5: armar el boleto).

QUÉ SE REVISA
  1. Reproducir sin el código del autor las cifras clave del histórico: el
     boleto «la casa elige» (las N más probables del día según la casa, una
     pata por partido, cuota en [piso, piso + 0,5]) con N = 4 y 6, y su
     ganancia por $100 sin booster y con ×1,2 / ×1,3 / ×1,8, en las mismas
     dos mitades (corte = mediana de las patas, 26-dic-2021).
  2. OTRO CORTE TEMPORAL: 70/30 por fecha, año por año y sólo lo reciente
     (2025-26, cuando el margen de la casa sube de ~6 % a 7-8 %, parecido a
     Playdoit). ¿El «×1,3 con 4 patas a 1,30 pasa» y el «+20 % de Draftea
     queda en punto muerto» aguantan?
  3. Máx. momio con p_min (la única forma de armar que ganó en una mitad):
     validación cruzada (p_min elegido en B, juzgado en A), y walk-forward
     por año (p_min elegido con los años anteriores, juzgado en el siguiente).
     Bootstrap por partido emparejado contra «la casa elige».
  4. Ishikawa por otra vía: si las rojas del mismo boleto no se agrupan, la
     varianza del número de rojas por boleto es Σ p(1−p) y los enteros salen
     ≈ Π p. Se mide la dispersión observada / esperada con la casa sin margen
     calibrada SÓLO con meses anteriores (bootstrap por día).
  5. Fugas: fechas mal leídas, partidos duplicados entre ligas, mitades que se
     solapan, la calibración p̂ (sólo meses anteriores), cuántas ligas tienen
     cuota de verdad.
Escribe `_v373_boleto_revision.json`.
"""
import importlib.util as iu
import json
import sys
import time

import numpy as np
import pandas as pd

T0 = time.time()
rng = np.random.default_rng(37399)
NB = 1000
BOOST = (1.0, 1.2, 1.3, 1.8)


def _mod(nombre, fichero):
    s = iu.spec_from_file_location(nombre, fichero)
    m = iu.module_from_spec(s)
    s.loader.exec_module(m)
    return m


G = _mod('v371b', '_v371b_ganador.py')


def _t():
    return '%.0fs' % (time.time() - T0)


# ----------------------------------------------------------- datos propios
def bolsa():
    d = G.cargar()
    x = G.patas(d)
    x = x[(x.cuota > 1.0) & x.p_c.between(0.01, 0.99)].copy()
    x['dia'] = x.fecha.dt.normalize()
    x['mes'] = x.fecha.dt.to_period('M').astype(str)
    return d, x.reset_index(drop=True)


def p_hat_previo(x, prior=50.0):
    """Calibración independiente: por mercado y banda de 5 pts, sólo meses anteriores."""
    b = np.clip((x.p_c.values / 0.05).astype(int), 0, 19)
    k = x.lado.values + '#' + b.astype(str)
    t = pd.DataFrame({'k': k, 'mes': x.mes.values, 'ok': x.ok.values.astype(float), 'pc': x.p_c.values})
    g = t.groupby(['k', 'mes']).agg(so=('ok', 'sum'), sp=('pc', 'sum'), n=('ok', 'size'))
    g = g.groupby(level=0).cumsum() - g          # acumulado ANTES de ese mes
    m = g.reindex(pd.MultiIndex.from_arrays([t.k, t.mes])).values
    ph = x.p_c.values + (m[:, 0] - m[:, 1]) / (m[:, 2] + prior)
    return np.clip(ph, 0.01, 0.99)


def base(x, piso):
    """La casa elige, implementación propia: la de mayor p_c por partido dentro del piso."""
    z = x[(x.cuota >= piso) & (x.cuota <= piso + 0.5)]
    z = z.loc[z.groupby('mid').p_c.idxmax()]
    z = z.sort_values(['dia', 'p_c'], ascending=[True, False]).copy()
    z['rango'] = z.groupby('dia').cumcount()
    return z


def max_momio(x, piso, pmin):
    z = x[(x.cuota >= piso) & (x.cuota <= piso + 0.5) & (x.p_c >= pmin)]
    z = z.assign(s=z.cuota + 1e-4 * z.p_c)
    z = z.loc[z.groupby('mid').s.idxmax()]
    return z


def boletos(z, n):
    t = z[z.rango < n]
    c = t.groupby('dia').size()
    t = t[t.dia.isin(c[c == n].index)]
    g = t.groupby('dia')
    b = pd.DataFrame({'bien': g.ok.sum(), 'momio': np.exp(g.cuota.apply(lambda s: np.log(s).sum()))})
    if 'p_hat' in t:
        b['p_esp'] = g.p_hat.apply(lambda s: float(np.prod(s)))
        b['var_esp'] = g.p_hat.apply(lambda s: float((s * (1 - s)).sum()))
        b['rojas_esp'] = g.p_hat.apply(lambda s: float((1 - s).sum()))
    b['entero'] = (b.bien == n).astype(int)
    return b


def p5(v):
    v = np.asarray(v, float)
    if len(v) < 5:
        return None
    i = rng.integers(0, len(v), (NB, len(v)))
    return round(100 * float(np.percentile(v[i].mean(1), 5)), 1)


def gan_boleto(b, n, piso):
    out = {'dias': int(len(b)), 'enteros': int(b.entero.sum()),
           'pct_entero': round(float(b.entero.mean()), 4) if len(b) else None,
           'momio_mediana': round(float(b.momio.median()), 2) if len(b) else None}
    for f in BOOST:
        if f == 1.2 and piso < 1.6:
            continue
        g = np.where(b.entero == 1, b.momio * (f if n >= 4 else 1.0) - 1, -1.0)
        out['gan_x%.1f' % f] = round(100 * float(g.mean()), 1) if len(g) else None
        out['p5_x%.1f' % f] = p5(g)
    return out


# ------------------------------------------------------- 1 y 2: boosters
def boosters(x, cortes):
    R = {}
    for piso in (1.30, 1.45, 1.60, 1.70, 1.80):
        z = base(x, piso)
        for n in (4, 6):
            b = boletos(z, n)
            fila = {}
            for nombre, (ini, fin) in cortes.items():
                q = b[(b.index >= ini) & (b.index < fin)]
                fila[nombre] = gan_boleto(q, n, piso)
            # año por año: cuántos años sale positivo con ×1,3 / ×1,2 / ×1,8
            por_anio = {}
            for y, q in b.groupby(b.index.year):
                if len(q) < 20:
                    continue
                r = gan_boleto(q, n, piso)
                por_anio[int(y)] = {k: r.get(k) for k in ('dias', 'pct_entero', 'gan_x1.0', 'gan_x1.2',
                                                          'gan_x1.3', 'gan_x1.8')}
            fila['por_anio'] = por_anio
            for f in ('gan_x1.0', 'gan_x1.2', 'gan_x1.3', 'gan_x1.8'):
                vals = [v[f] for v in por_anio.values() if v.get(f) is not None]
                if vals:
                    fila['anios_positivos_' + f] = '%d/%d' % (sum(v > 0 for v in vals), len(vals))
            R['%.2f · %d' % (piso, n)] = fila
        print('  boosters piso %.2f %s' % (piso, _t()), flush=True)
    return R


# --------------------------------------------- 3: máx. momio, sin la mitad A
def _pareado(q, b):
    """Bootstrap por partido emparejado: diferencia de ganancia y de acierto por pata."""
    q = q.assign(gan=np.where(q.ok == 1, q.cuota - 1, -1.0))
    b = b.assign(gan=np.where(b.ok == 1, b.cuota - 1, -1.0))
    gq = q.groupby('mid').agg(ok=('ok', 'sum'), gan=('gan', 'sum'), n=('ok', 'size'))
    gb = b.groupby('mid').agg(ok=('ok', 'sum'), gan=('gan', 'sum'), n=('ok', 'size'))
    u = gq.index.union(gb.index)
    Q = gq.reindex(u, fill_value=0).values.astype(float)
    B = gb.reindex(u, fill_value=0).values.astype(float)
    W = rng.poisson(1.0, (NB, len(u))).astype(float)
    sq, sb = W @ Q, W @ B
    dg = sq[:, 1] / sq[:, 2] - sb[:, 1] / sb[:, 2]
    do = sq[:, 0] / sq[:, 2] - sb[:, 0] / sb[:, 2]
    return {'n': int(len(q)), 'n_base': int(len(b)), 'acierto': round(float(q.ok.mean()), 4),
            'cuota': round(float(q.cuota.mean()), 3), 'gan_100': round(100 * float(q.gan.mean()), 2),
            'base_gan_100': round(100 * float(b.gan.mean()), 2),
            'dif_gan': round(100 * float(q.gan.mean() - b.gan.mean()), 2),
            'dif_gan_p5': round(100 * float(np.percentile(dg, 5)), 2),
            'dif_acierto': round(float(q.ok.mean() - b.ok.mean()), 4),
            'dif_acierto_p5': round(float(np.percentile(do, 5)), 4)}


GRID = np.round(np.arange(0.40, 0.80, 0.025), 3)


def elegir_pmin(xx, piso):
    mejor = None
    for pm in GRID:
        z = max_momio(xx, piso, pm)
        if not len(z):
            continue
        if z.groupby('dia').size().mean() < 4:
            continue
        g = float(np.where(z.ok == 1, z.cuota - 1, -1).mean())
        if mejor is None or g > mejor[1]:
            mejor = (float(pm), g)
    return mejor[0] if mejor else None


def max_momio_revision(x, corte, corte70):
    R = {}
    for piso in (1.30, 1.45, 1.60, 1.70, 1.80):
        f = {}
        xa, xb = x[x.fecha < corte], x[x.fecha >= corte]
        # el autor: elegido en A, juzgado en B; aquí además al revés (elegido en B, juzgado en A)
        pa, pb = elegir_pmin(xa, piso), elegir_pmin(xb, piso)
        f['pmin_A'], f['pmin_B'] = pa, pb
        f['elegido_A_juzgado_B'] = _pareado(max_momio(xb, piso, pa), base(xb, piso))
        f['elegido_B_juzgado_A'] = _pareado(max_momio(xa, piso, pb), base(xa, piso))
        # 70/30: elegido en el 70 % primero, juzgado en el 30 % final
        x7, x3 = x[x.fecha < corte70], x[x.fecha >= corte70]
        p7 = elegir_pmin(x7, piso)
        f['pmin_70'] = p7
        f['elegido_70_juzgado_30'] = _pareado(max_momio(x3, piso, p7), base(x3, piso))
        # walk-forward por año: p_min con los años anteriores
        qs, bs, elegidos = [], [], {}
        for y in range(2013, 2027):
            prev = x[x.fecha.dt.year < y]
            cur = x[x.fecha.dt.year == y]
            if not len(cur):
                continue
            pm = elegir_pmin(prev, piso)
            if pm is None:
                continue
            elegidos[y] = pm
            qs.append(max_momio(cur, piso, pm))
            bs.append(base(cur, piso))
        f['walk_forward_pmin'] = elegidos
        f['walk_forward'] = _pareado(pd.concat(qs), pd.concat(bs))
        R['%.2f' % piso] = f
        print('  max_momio piso %.2f %s' % (piso, _t()), flush=True)
    return R


# ------------------------------------------------------ 4: Ishikawa (otra vía)
def dispersion(x, corte):
    R = {}
    for piso in (1.30, 1.60):
        z = base(x, piso)
        for n in (4, 6, 10):
            b = boletos(z, n)
            fila = {}
            for tramo, m in (('A', b.index < corte), ('B', b.index >= corte)):
                q = b[m]
                if len(q) < 30:
                    continue
                rojas = n - q.bien.values
                # varianza observada alrededor de lo esperado (rojas_esp), contra Σ p(1−p)
                res2 = (rojas - q.rojas_esp.values) ** 2
                ve = q.var_esp.values
                i = rng.integers(0, len(q), (NB, len(q)))
                ratio_bs = res2[i].mean(1) / ve[i].mean(1)
                ent = q.entero.values.astype(float)
                pe = q.p_esp.values
                ratio_ent = ent[i].mean(1) / pe[i].mean(1)
                fila[tramo] = {'dias': int(len(q)), 'rojas_obs': round(float(rojas.mean()), 3),
                               'rojas_esp': round(float(q.rojas_esp.mean()), 3),
                               'dispersion_obs_sobre_esp': round(float(res2.mean() / ve.mean()), 3),
                               'disp_p5': round(float(np.percentile(ratio_bs, 5)), 3),
                               'disp_p95': round(float(np.percentile(ratio_bs, 95)), 3),
                               'enteros_obs': round(float(ent.mean()), 4), 'enteros_esp': round(float(pe.mean()), 4),
                               'ent_obs_sobre_esp_p5': round(float(np.percentile(ratio_ent, 5)), 3),
                               'ent_obs_sobre_esp_p95': round(float(np.percentile(ratio_ent, 95)), 3)}
            R['%.2f · %d' % (piso, n)] = fila
    return R


# ------------------------------------------------------------- 5: fugas
def fugas(d, x, corte):
    s = d['date'].astype(str)
    f = {'ligas_con_cuota': int(d.liga.nunique()), 'ficheros_historico': 87,
         'formatos_fecha': s.str.replace(r'\d', '9', regex=True).value_counts().to_dict(),
         'fecha_vs_MATCH_ID_distintas': int((d.fecha.dt.normalize() !=
                                             pd.to_datetime(d.MATCH_ID.astype(str).str[:8], format='%Y%m%d',
                                                            errors='coerce')).sum())}
    k = d.assign(f=d.fecha.dt.normalize())
    # mismo partido en dos ligas: mismo día, mismos goles y las 3 cuotas y la de más 2,5
    cols = ['f', 'home_goals', 'away_goals', 'odd_home', 'odd_draw', 'odd_away', 'odd_over25']
    dup = k[k.duplicated(cols, keep=False)]
    f['posibles_duplicados_entre_ligas'] = int(dup.groupby(cols).liga.nunique().gt(1).sum())
    # mitades: ningún día en las dos
    da = set(x[x.fecha < corte].dia.unique())
    db = set(x[x.fecha >= corte].dia.unique())
    f['dias_en_las_dos_mitades'] = len(da & db)
    # margen de la casa por año (la casa del histórico NO es Draftea)
    d2 = d.assign(m=1 / d.odd_home + 1 / d.odd_draw + 1 / d.odd_away - 1)
    f['margen_1x2_por_anio'] = {int(y): round(float(v), 4) for y, v in d2.groupby(d2.fecha.dt.year).m.median().items()}
    return f


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    d, x = bolsa()
    x['p_hat'] = p_hat_previo(x)
    corte = x.fecha.quantile(0.5)
    corte70 = x.fecha.quantile(0.7)
    print('patas', len(x), 'partidos', x.mid.nunique(), 'corte', corte.date(), 'corte70', corte70.date(), _t(),
          flush=True)
    lo, hi = pd.Timestamp('1900-01-01'), pd.Timestamp('2100-01-01')
    cortes = {'A': (lo, corte), 'B': (corte, hi), 'primer_70': (lo, corte70), 'ultimo_30': (corte70, hi),
              'desde_2025': (pd.Timestamp('2025-01-01'), hi)}
    R = {'corte': str(corte.date()), 'corte70': str(corte70.date()),
         'patas': int(len(x)), 'partidos': int(x.mid.nunique())}
    R['fugas'] = fugas(d, x, corte)
    print('fugas', R['fugas'], flush=True)
    R['boosters'] = boosters(x, cortes)
    R['dispersion_rojas'] = dispersion(x, corte)
    R['max_momio'] = max_momio_revision(x, corte, corte70)
    json.dump(R, open('_v373_boleto_revision.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1,
              default=str)
    for k, fila in R['boosters'].items():
        print('==', k)
        for c in cortes:
            print('   %-10s %s' % (c, fila[c]))
        print('   años +', {kk: v for kk, v in fila.items() if kk.startswith('anios')})
    for k, v in R['dispersion_rojas'].items():
        print('disp', k, v)
    for k, v in R['max_momio'].items():
        print('maxmomio', k, {kk: vv for kk, vv in v.items()})
    print('listo', _t())


if __name__ == '__main__':
    main()
