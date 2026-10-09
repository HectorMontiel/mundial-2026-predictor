#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v345 — la metodología de tiros, mejorada y contra la línea de Playdoit.

La v344 midió que la metodología del usuario (tabla, posesión, faltas del
rival, plantilla) predice los tiros mucho mejor que «los últimos 5», y que
contra Playdoit apostar con 12 puntos de ventaja daba +20 % con p5 −0,3 %
(257 partidos: los históricos se quedaban atrás). Aquí:

  1. LOS DATOS AL DÍA: el histórico + lo que `stats_espn/` tiene después (con
     el marcador y la hora de ESPN), con los nombres traducidos al catálogo.
     Desde el 24-ago pasan de 257 a ~1.000 partidos con línea de Playdoit.
  2. MÁS DE LO QUE DIJO, MEDIDO: forma reciente ponderada, calidad de los
     rivales que ya enfrentó, la temporada en la misma condición, posesión
     esperada contra la del rival, descanso, avance de la temporada × zona
     de la tabla, y el empate según la cuota.
  3. LA REGLA DE APUESTA se elige con la PRIMERA mitad del periodo con precio
     y se juzga con la SEGUNDA, con bootstrap por partido.

Uso: python _v345_tiros.py
"""
import json
import sys

import numpy as np
import pandas as pd
import requests

import _v344_precio as P
import _v344_tiros as T

DESDE = P.DESDE
CACHE = '_v345_filas.pkl'
rng = np.random.default_rng(345)


# ---------------------------------------------------------------- datos
def _marcadores(code, meses):
    """{event_id: (goles local, goles visita, inicio)} del scoreboard."""
    out = {}
    for m in meses:
        try:
            j = requests.get('https://site.api.espn.com/apis/site/v2/sports/'
                             'soccer/%s/scoreboard' % code,
                             params={'dates': m, 'limit': 500}, timeout=30).json()
        except Exception:
            continue
        for ev in j.get('events') or []:
            try:
                comp = ev['competitions'][0]
                h = next(c for c in comp['competitors'] if c['homeAway'] == 'home')
                a = next(c for c in comp['competitors'] if c['homeAway'] == 'away')
                if not ((ev.get('status') or {}).get('type') or {}).get('completed'):
                    continue
                out[str(ev['id'])] = (float(h['score']), float(a['score']), ev.get('date'))
            except Exception:
                continue
    return out


def cargar():
    import fixtures_espn
    import stats_espn as se
    base = T.cargar()                      # los históricos con ESPN
    nuevos = []
    for liga, g in base.groupby('liga'):
        code = fixtures_espn.ESPN_CODIGOS.get(liga)
        if not code:
            continue
        try:
            s = se.leer(liga)
        except Exception:
            continue
        if not len(s):
            continue
        tope = g.fecha.max()
        s = s[pd.to_datetime(s.fecha) > tope].copy()
        if s.empty:
            continue
        meses = sorted({pd.Timestamp(f).strftime('%Y%m') for f in s.fecha})
        mk = _marcadores(code, meses)
        s['ev'] = s.event_id.astype(str)
        s = s[s.ev.isin(mk)]
        if s.empty:
            continue
        cat = set(g.home_team) | set(g.away_team)
        tr = se._traductor(set(s.home) | set(s.away), cat)
        s['home_team'] = s.home.map(lambda n: tr.get(n, n))
        s['away_team'] = s.away.map(lambda n: tr.get(n, n))
        s['home_goals'] = s.ev.map(lambda e: mk[e][0])
        s['away_goals'] = s.ev.map(lambda e: mk[e][1])
        s['inicio'] = s.ev.map(lambda e: mk[e][2])
        s['date'] = s.fecha
        s['fecha'] = pd.to_datetime(s.fecha)
        s['liga'] = liga
        s['stats_origen'] = 'espn'
        nuevos.append(s)
        print('  %-20s +%d partidos después del %s' % (liga, len(s), tope.date()))
    d = pd.concat([base] + nuevos, ignore_index=True).sort_values('fecha')
    d['mid'] = np.arange(len(d))
    return d


def _cuotas_de_tablero(d):
    """Para los partidos sin Pinnacle: el 1X2 de Playdoit sin margen."""
    tab = P.tableros()
    sin = d[d.odd_home_pin.isna() & d.odd_home.isna() & (d.fecha >= DESDE)]
    prox = pd.DataFrame({'mid': sin.mid, 'liga': sin.liga, 'fecha': sin.fecha,
                         'equipo': sin.home_team, 'rival': sin.away_team})
    casa = P.emparejar(prox, tab)
    for mid, b in casa.items():
        c = P._lineas(b.get('1x2_cuotas'))
        if c.get('home') and c.get('draw') and c.get('away'):
            i = d.index[d.mid == mid]
            d.loc[i, 'odd_home'] = c['home']
            d.loc[i, 'odd_draw'] = c['draw']
            d.loc[i, 'odd_away'] = c['away']
    return d


# ---------------------------------------------------------------- rasgos
def rasgos_extra(e):
    """Lo nuevo de la v345, también sólo con lo anterior al partido."""
    e = e.sort_values(['fecha', 'mid']).copy()
    g = e.groupby(['liga', 'temporada', 'equipo'], sort=False)
    for c in ('tiros', 'a_puerta', 'tiros_c', 'a_puerta_c', 'pos', 'faltas_r'):
        e['ew_' + c] = g[c].transform(lambda x: x.shift(1).ewm(span=8, min_periods=1).mean())
    gv = e.groupby(['liga', 'temporada', 'equipo', 'local'], sort=False)
    for c in ('tiros', 'a_puerta', 'tiros_c'):
        e['v_' + c] = gv[c].transform(lambda x: x.shift(1).expanding().mean())
    e['descanso'] = g.fecha.transform(lambda x: x.diff().dt.days).clip(0, 30)
    # avance de la temporada: partidos jugados contra lo que suele durar
    largo = e.groupby(['liga', 'temporada']).n_prev.transform('max').clip(lower=10)
    e['avance'] = e.n_prev / largo
    e['presion'] = e.avance * (e.zona_baja + e.zona_alta)
    inv = 1 / e[['odd_w', 'odd_d', 'odd_l']]
    e['p_empate'] = inv.odd_d / inv.sum(axis=1)
    return e


def calidad_rivales(e):
    """Lo que el equipo tiró contra rivales que conceden poco vale más: tiros
    del equipo entre lo que conceden sus rivales (antes de cada partido)."""
    conc = e[['mid', 'equipo', 't_tiros_c']].rename(
        columns={'equipo': 'rival', 't_tiros_c': 'rc'})
    e = e.merge(conc, on=['mid', 'rival'], how='left')
    e['ratio'] = e.tiros / e.rc
    e = e.sort_values(['fecha', 'mid'])
    g = e.groupby(['liga', 'temporada', 'equipo'], sort=False)
    e['t_ratio'] = g['ratio'].transform(lambda x: x.shift(1).expanding().mean())
    return e.drop(columns=['rc', 'ratio'])


def preparar():
    try:
        return pd.read_pickle(CACHE)
    except Exception:
        pass
    d = cargar()
    for c in ('odd_home_pin', 'odd_draw_pin', 'odd_away_pin', 'odd_home',
              'odd_draw', 'odd_away'):
        if c not in d:
            d[c] = np.nan
    d = _cuotas_de_tablero(d)
    e = T.a_equipos(d)
    e = T.rasgos(e)
    e = rasgos_extra(e)
    e = calidad_rivales(e)
    cols = ['ew_tiros', 'ew_a_puerta', 'ew_tiros_c', 'ew_a_puerta_c', 'ew_pos',
            'ew_faltas_r', 'v_tiros', 'v_a_puerta', 'v_tiros_c', 'descanso',
            'avance', 'presion']          # `t_ratio` ya lo pega `con_rival`
    e = T.con_rival(e)
    r = e[['mid', 'equipo'] + cols].rename(columns={c: 'r_' + c for c in cols}
                                           ).rename(columns={'equipo': 'rival'})
    e = e.merge(r, on=['mid', 'rival'], how='left')
    e.to_pickle(CACHE)
    return e


EXTRA = ['ew_tiros', 'ew_a_puerta', 'r_ew_tiros_c', 'r_ew_a_puerta_c', 'ew_pos',
         'r_ew_pos', 'r_ew_faltas_r', 'v_tiros', 'v_a_puerta', 'r_v_tiros_c',
         'descanso', 'r_descanso', 'avance', 'presion', 'r_presion',
         'p_empate', 't_ratio', 'r_t_ratio']


def columnas(version):
    base = T.columnas(None)
    return base if version == 'v344' else base + EXTRA


def _modelo(objetivo, ent, cols):
    import lightgbm as lgb
    m = lgb.LGBMRegressor(objective='poisson', n_estimators=700,
                          learning_rate=0.03, num_leaves=31,
                          min_child_samples=80, subsample=0.8, subsample_freq=1,
                          colsample_bytree=0.8, reg_lambda=1.0, verbose=-1,
                          random_state=345)
    c2 = ent.fecha.quantile(0.85)
    a, b = ent[ent.fecha < c2], ent[ent.fecha >= c2]
    m.fit(a[cols], a[objetivo])
    k = T.ajustar_k(b[objetivo].values, np.clip(m.predict(b[cols]), 0.3, None))
    m.fit(ent[cols], ent[objetivo])
    return m, k


def _base(e):
    if 'r_t_ratio_x' in e:                 # cachés de antes del arreglo
        e = e.rename(columns={'r_t_ratio_x': 'r_t_ratio', 't_ratio_x': 't_ratio'})
        e = e.drop(columns=[c for c in e.columns if c.endswith('_y')])
    e = e[~e.liga.isin(T.COPAS)].copy()
    e['liga_tiros'] = T.media_liga(e, 'tiros')
    e['liga_a_puerta'] = T.media_liga(e, 'a_puerta')
    return e[(e.n_prev >= 3) & (e.r_n_prev >= 3)].dropna(subset=['p_gana']).copy()


# ---------------------------------------------------------------- pruebas
def prueba_estadistica(e):
    """Como la v344: elige 70 % / juzga 30 %, log-loss en las líneas típicas."""
    res = {}
    e = e[e.fecha < DESDE]
    corte = e.fecha.quantile(0.70)
    el, ju = e[e.fecha < corte], e[e.fecha >= corte]
    for obj in ('tiros', 'a_puerta'):
        ll = {}
        for ver in ('v344', 'v345'):
            m, k = _modelo(obj, el, columnas(ver))
            lam = np.clip(m.predict(ju[columnas(ver)]), 0.3, None)
            y = ju[obj].values
            tot = np.zeros(len(ju))
            for L in T.LINEAS[obj]:
                p = np.clip(T.nb_sf(lam, L, k), 1e-4, 1 - 1e-4)
                yb = (y > L)
                tot += -(yb * np.log(p) + (1 - yb) * np.log(1 - p))
            ll[ver] = tot / len(T.LINEAS[obj])
        um, inv = np.unique(ju.mid.values, return_inverse=True)
        dif = ll['v344'] - ll['v345']
        s, n = np.bincount(inv, weights=dif), np.bincount(inv)
        bs = [s[i].sum() / n[i].sum() for i in
              (rng.integers(0, len(um), len(um)) for _ in range(2000))]
        res[obj] = {'ll_v344': round(float(ll['v344'].mean()), 4),
                    'll_v345': round(float(ll['v345'].mean()), 4),
                    'mejora': round(float(np.mean(bs)), 5),
                    'p5': round(float(np.percentile(bs, 5)), 5)}
    return res


def lineas_con_precio(e, ver='v345'):
    """Cada línea de tiros de Playdoit desde el 24-ago con la probabilidad del
    modelo (entrenado SÓLO con lo anterior al 24-ago)."""
    el, ju = e[e.fecha < DESDE], e[e.fecha >= DESDE]
    tab = P.tableros()
    casa = P.emparejar(ju[ju.local == 1], tab)
    filas = []
    for obj, clave in (('tiros', 'remates'), ('a_puerta', 'remates_on')):
        cols = columnas(ver)
        m, k = _modelo(obj, el, cols)
        lam = np.clip(m.predict(ju[cols]), 0.3, None)
        for r, l in zip(ju.itertuples(), lam):
            bd = casa.get(r.mid)
            if bd is None:
                continue
            lado = 'home' if r.local == 1 else 'away'
            for lin, v in P._lineas(bd.get('%s_%s' % (clave, lado))).items():
                try:
                    L, cm_, cn = float(lin), float(v['mas']), float(v['menos'])
                except Exception:
                    continue
                pm = (1 / cm_) / (1 / cm_ + 1 / cn)
                filas.append({'obj': obj, 'mid': r.mid, 'liga': r.liga,
                              'fecha': r.fecha, 'equipo': r.equipo, 'linea': L,
                              'lam': l, 'real': getattr(r, obj),
                              'y': int(getattr(r, obj) > L),
                              'p_mod': float(T.nb_sf(l, L, k)), 'p_casa': pm,
                              'c_mas': cm_, 'c_menos': cn})
    return pd.DataFrame(filas)


def apuestas(g, edge, pmin, cmax=3.0):
    """Las apuestas de una regla: el lado que el modelo ve ≥ pmin y ≥ edge
    por encima de la casa, a cuota ≤ cmax."""
    mas = (g.p_mod - g.p_casa >= edge) & (g.p_mod >= pmin) & (g.c_mas <= cmax)
    pmen = 1 - g.p_mod
    menos = (g.p_mod - g.p_casa <= -edge) & (pmen >= pmin) & (g.c_menos <= cmax)
    a = pd.DataFrame({'mid': np.r_[g.mid[mas], g.mid[menos]],
                      'fecha': np.r_[g.fecha[mas], g.fecha[menos]],
                      'gana': np.r_[g.y[mas], 1 - g.y[menos]],
                      'cuota': np.r_[g.c_mas[mas], g.c_menos[menos]],
                      'p': np.r_[g.p_mod[mas], pmen[menos]],
                      'lado': ['más'] * int(mas.sum()) + ['menos'] * int(menos.sum())})
    # una por equipo y mercado: la de mayor ventaja (líneas vecinas = misma apuesta)
    return a


def resumen(a):
    if len(a) == 0:
        return {'n': 0}
    gan = (a.gana * a.cuota - 1).values
    um, inv = np.unique(a.mid.values, return_inverse=True)
    s, n = np.bincount(inv, weights=gan), np.bincount(inv)
    bs = [s[i].sum() / n[i].sum() for i in
          (rng.integers(0, len(um), len(um)) for _ in range(3000))]
    return {'n': int(len(a)), 'partidos': int(len(um)),
            'acierto': round(float(a.gana.mean()), 3),
            'promete': round(float(a.p.mean()), 3),
            'cuota': round(float(a.cuota.mean()), 3),
            'roi': round(float(gan.mean()), 4),
            'p5': round(float(np.percentile(bs, 5)), 4)}


def prueba_precio(d):
    corte = d.fecha.quantile(0.5)
    el, ju = d[d.fecha < corte], d[d.fecha >= corte]
    rejilla = []
    for obj in ('tiros', 'a_puerta', 'ambos'):
        for edge in (0.05, 0.08, 0.10, 0.12, 0.15):
            for pmin in (0.50, 0.55, 0.60, 0.65, 0.70):
                ge = el if obj == 'ambos' else el[el.obj == obj]
                r = resumen(apuestas(ge, edge, pmin))
                if r['n'] >= 40:
                    rejilla.append((obj, edge, pmin, r))
    # el criterio, fijado ANTES de mirar la segunda mitad: el mejor p5 con al
    # menos 40 apuestas (no el mejor ROI, que premia la suerte)
    mejor = max(rejilla, key=lambda x: x[3]['p5'])
    obj, edge, pmin, r_el = mejor
    gj = ju if obj == 'ambos' else ju[ju.obj == obj]
    gt = d if obj == 'ambos' else d[d.obj == obj]
    return {'corte': str(corte.date()),
            'regla': {'mercado': obj, 'ventaja': edge, 'prob_min': pmin},
            'elige': r_el, 'juzga': resumen(apuestas(gj, edge, pmin)),
            'todo': resumen(apuestas(gt, edge, pmin)),
            'top5_elige': [(o, e_, p_, r['n'], r['roi'], r['p5'])
                           for o, e_, p_, r in sorted(rejilla, key=lambda x: -x[3]['p5'])[:5]]}


def main():
    e = _base(preparar())
    print('filas', len(e), 'desde 24-ago', int((e.fecha >= DESDE).sum()))
    out = {'estadistica': prueba_estadistica(e)}
    print(json.dumps(out, ensure_ascii=False, indent=1))
    lin = lineas_con_precio(e)
    lin.to_pickle('_v345_lineas.pkl')
    out['lineas'] = {'n': len(lin), 'partidos': int(lin.mid.nunique())}
    for obj, g in lin.groupby('obj'):
        y = g.y.values
        ll = {}
        for nom, p in (('casa', g.p_casa.values), ('modelo', g.p_mod.values)):
            p = np.clip(p, 1e-4, 1 - 1e-4)
            ll[nom] = round(float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p))), 4)
        out['lineas'][obj] = ll
    out['precio'] = prueba_precio(lin)
    print(json.dumps({k: v for k, v in out.items() if k != 'estadistica'},
                     ensure_ascii=False, indent=1, default=str))
    json.dump(out, open('_v345_tiros.json', 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1, default=str)


if __name__ == '__main__':
    main()
