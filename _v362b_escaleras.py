#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v362b — «🎲 Apuestas arriesgadas» con la ESCALERA de Playdoit, no con líneas seguras.

El usuario: «las cuotas de los córners del boleto de Draftea no son bajas: por
algo son arriesgadas, hay hasta 1,7. Tiene que ser de acuerdo a la casa que
atacamos (Playdoit): si abre desde 4,5 córners a un equipo, desde ahí se
avanza y se saca la probabilidad; o desde 5,5, o desde 2,5. Y tiros ya
arriesgados: más de 2,5, 3,5 o N. Para todos los mercados, todas las
estadísticas».

Datos:
  · las escaleras de Playdoit de cada partido desde el 24-ago (historial de
    git de `mercado_dia.json`, la última foto antes del día del partido):
    córners, tiros, tiros a puerta, tarjetas y goles, de cada equipo y total;
  · el resultado real (ESPN: históricos + `stats_espn`);
  · el Método Contexto (`tiros_equipo`) entrenado SÓLO con lo anterior al
    24-ago y aplicado después (sin fuga).
Para cada línea «más de» de la escalera: la probabilidad del método, la de la
casa (sin margen), la cuota y si se cumplió.

Reglas de «arriesgada» (sólo «más de», cuota 1,45-3,00): probabilidad del
método ≥ pmin y ventaja sobre la casa ≥ e. Se eligen con la primera mitad de
fechas (por el p5 del rendimiento, no por el acierto) y se juzgan con la
segunda. Y la combinada del día con las mejores patas (una por partido).
Escribe `_v362b_escaleras.json` y `_v362b_lineas.pkl`.
"""
import json
import subprocess
import sys

import numpy as np
import pandas as pd

import _v344_precio as P
import _v361_metodo as V
import tiros_equipo as te

rng = np.random.default_rng(3622)
DESDE = pd.Timestamp('2026-08-24')
CACHE = '_v362b_tableros.pkl'
MAX_DIF = 0.20
# objetivo del método → (columna real, clave del tablero)
MERC = {'corners': ('corners', 'corners'), 'tiros': ('tiros', 'remates'),
        'a_puerta': ('a_puerta', 'remates_on'), 'tarjetas': ('amarillas', 'tarjetas'),
        'goles': ('gf', 'goles')}
CLAVES = ['corners', 'corners_home', 'corners_away', 'remates', 'remates_home', 'remates_away',
          'remates_on', 'remates_on_home', 'remates_on_away', 'tarjetas', 'tarjetas_home',
          'tarjetas_away', 'goles', 'goles_home', 'goles_away', '1x2_cuotas', 'casa']


def tableros():
    try:
        return pd.read_pickle(CACHE)
    except Exception:
        pass
    hs = subprocess.run(['git', 'log', '--format=%H %cI', 'origin/main', '--', 'mercado_dia.json'],
                        capture_output=True, text=True).stdout
    filas = []
    for linea in [x for x in hs.split('\n') if x.strip()]:
        h, cuando = linea.split()
        try:
            d = json.loads(subprocess.run(['git', 'show', h + ':mercado_dia.json'],
                                          capture_output=True).stdout.decode('utf-8'))
        except Exception:
            continue
        ts = pd.Timestamp(cuando).tz_convert('UTC').tz_localize(None)
        for v in (d.get('partidos') or {}).values():
            if isinstance(v, dict):
                filas.append((ts, v.get('clave_liga'), v.get('home'), v.get('away'),
                              {k: v.get(k) for k in CLAVES}))
    t = pd.DataFrame(filas, columns=['ts', 'liga', 'home', 'away', 'board'])
    t['h'] = t.home.map(P._norm)
    t['a'] = t.away.map(P._norm)
    t.to_pickle(CACHE)
    return t


def _lineas(x):
    return P._lineas(x) if x else {}


def lineas_con_precio(e):
    import lightgbm as lgb
    el, ju = e[e.fecha < DESDE], e[e.fecha >= DESDE].copy()
    tab = tableros()
    casa = P.emparejar(ju[ju.local == 1], tab)
    print('partidos después del 24-ago', ju.mid.nunique(), 'con tablero', len(casa))
    filas = []
    for obj, (col, clave) in MERC.items():
        a = el.dropna(subset=[col])
        m = lgb.LGBMRegressor(objective='poisson', n_estimators=700, learning_rate=0.03,
                              num_leaves=31, min_child_samples=80, subsample=0.8, subsample_freq=1,
                              colsample_bytree=0.8, reg_lambda=1.0, verbose=-1, random_state=3622)
        m.fit(a[te.COLUMNAS], a[col])
        c2 = a.fecha.quantile(0.85)
        k = te.ajustar_k(a[a.fecha >= c2][col].values,
                         np.clip(m.predict(a[a.fecha >= c2][te.COLUMNAS]), 0.05, None))
        j = ju.dropna(subset=[col]).copy()
        j['mu'] = np.clip(m.predict(j[te.COLUMNAS]), 0.05, None)
        # los dos equipos del partido, para el total
        par = j.groupby('mid').agg(mu_t=('mu', 'sum'), mu2=('mu', lambda x: float((x ** 2).sum())),
                                   real_t=(col, 'sum'), n=('mu', 'size'))
        for r in j.itertuples():
            mid = r.mid
            bd = casa.get(mid if r.local == 1 else None)
            if bd is None:
                # el tablero se emparejó con la fila del local
                hrow = j[(j.mid == mid) & (j.local == 1)]
                bd = casa.get(int(hrow.mid.iloc[0])) if len(hrow) else None
            if bd is None:
                continue
            lado = 'home' if r.local == 1 else 'away'
            for lin, v in _lineas(bd.get('%s_%s' % (clave, lado))).items():
                try:
                    L, cm_, cn = float(lin), float(v['mas']), float(v['menos'])
                except Exception:
                    continue
                if L % 1 != 0.5:
                    continue
                filas.append({'obj': obj, 'tipo': 'equipo', 'mid': mid, 'liga': r.liga,
                              'fecha': r.fecha, 'linea': L, 'mu': r.mu, 'real': getattr(r, col),
                              'y': int(getattr(r, col) > L), 'p_mod': float(te.prob_mas(r.mu, L, k)),
                              'p_casa': (1 / cm_) / (1 / cm_ + 1 / cn), 'c_mas': cm_})
            if r.local == 1 and mid in par.index and par.loc[mid, 'n'] == 2:
                mt, m2, rt = par.loc[mid, 'mu_t'], par.loc[mid, 'mu2'], par.loc[mid, 'real_t']
                k_t = (mt ** 2) / max(m2 / k, 1e-9) if k < 400 else 1e6
                for lin, v in _lineas(bd.get(clave)).items():
                    try:
                        L, cm_, cn = float(lin), float(v['mas']), float(v['menos'])
                    except Exception:
                        continue
                    if L % 1 != 0.5:
                        continue
                    filas.append({'obj': obj, 'tipo': 'total', 'mid': mid, 'liga': r.liga,
                                  'fecha': r.fecha, 'linea': L, 'mu': mt, 'real': rt,
                                  'y': int(rt > L), 'p_mod': float(te.prob_mas(mt, L, k_t)),
                                  'p_casa': (1 / cm_) / (1 / cm_ + 1 / cn), 'c_mas': cm_})
    return pd.DataFrame(filas)


def regla(g, pmin, edge, cmin=1.45, cmax=3.0):
    x = g[(g.c_mas >= cmin) & (g.c_mas <= cmax) & (g.p_mod >= pmin) & (g.p_mod - g.p_casa >= edge)]
    # una por partido, mercado y lado: la de más ventaja (líneas vecinas = misma apuesta)
    x = x.assign(v=x.p_mod - x.p_casa).sort_values('v', ascending=False)
    return x.groupby(['mid', 'obj', 'tipo']).head(1)


def resumen(a):
    if len(a) == 0:
        return {'n': 0}
    gan = (a.y * a.c_mas - 1).values
    um, inv = np.unique(a.mid.values, return_inverse=True)
    s, n = np.bincount(inv, weights=gan), np.bincount(inv)
    bs = [s[i].sum() / n[i].sum() for i in (rng.integers(0, len(um), len(um)) for _ in range(2000))]
    return {'n': int(len(a)), 'partidos': int(len(um)), 'acierto': round(float(a.y.mean()), 3),
            'promete': round(float(a.p_mod.mean()), 3), 'casa': round(float(a.p_casa.mean()), 3),
            'cuota': round(float(a.c_mas.mean()), 3), 'roi': round(float(gan.mean()), 4),
            'p5': round(float(np.percentile(bs, 5)), 4)}


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    e = V.preparar()
    try:
        d = pd.read_pickle('_v362b_lineas.pkl')
    except Exception:
        d = lineas_con_precio(e)
        d.to_pickle('_v362b_lineas.pkl')
    # LAS LÍNEAS DE OTRO MERCADO FUERA: bajo la clave «corners» venían «más de
    # 1,5» a 2,0-2,5 (otro mercado de la casa) con el método al 99,8 %. Una
    # línea que el método y la casa ven a más de 20 pts no es la misma apuesta.
    antes = len(d)
    d = d[(d.p_mod - d.p_casa).abs() <= MAX_DIF].copy()
    print('líneas', len(d), 'de', antes, d.groupby(['obj', 'tipo']).size().to_dict())
    corte = d.fecha.quantile(0.5)
    el, ju = d[d.fecha < corte], d[d.fecha >= corte]
    out = {'corte': str(corte)[:10], 'lineas': int(len(d)), 'partidos': int(d.mid.nunique())}
    # calibración en la zona arriesgada (cuota 1,45-3)
    z = d[(d.c_mas >= 1.45) & (d.c_mas <= 3.0)]
    b = pd.cut(z.p_mod, [0, 0.4, 0.5, 0.55, 0.6, 0.65, 0.7, 1.0])
    out['calibracion'] = [{'banda': str(k), 'n': int(len(g)), 'promete': round(float(g.p_mod.mean()), 3),
                           'casa': round(float(g.p_casa.mean()), 3), 'acierta': round(float(g.y.mean()), 3)}
                          for k, g in z.groupby(b, observed=True)]
    print('calibración cuota 1,45-3:', out['calibracion'])
    rej = []
    for obj in list(MERC) + ['todos']:
        for pmin in (0.45, 0.50, 0.55, 0.60, 0.65):
            for edge in (0.0, 0.03, 0.05, 0.08, 0.12):
                g = el if obj == 'todos' else el[el.obj == obj]
                r = resumen(regla(g, pmin, edge))
                if r['n'] >= 40:
                    rej.append((obj, pmin, edge, r))
    rej.sort(key=lambda x: -x[3]['p5'])
    out['top_elige'] = [{'obj': o, 'pmin': p, 'edge': e_, **r} for o, p, e_, r in rej[:8]]
    mejor = rej[0]
    o, p, e_, _ = mejor
    gj = ju if o == 'todos' else ju[ju.obj == o]
    gt = d if o == 'todos' else d[d.obj == o]
    out['regla'] = {'obj': o, 'pmin': p, 'edge': e_, 'elige': mejor[3],
                    'juzga': resumen(regla(gj, p, e_)), 'todo': resumen(regla(gt, p, e_))}
    print('mejor regla (elige):', json.dumps(out['regla'], ensure_ascii=False))
    # y la regla sencilla, sin ventaja: probabilidad ≥ 60 % a cuota 1,45-3
    for pm in (0.55, 0.60, 0.65):
        out['simple_%d' % int(pm * 100)] = {tr: resumen(regla(g, pm, -1.0))
                                            for tr, g in (('elige', el), ('juzga', ju))}
        print('simple', pm, json.dumps(out['simple_%d' % int(pm * 100)], ensure_ascii=False))
    # la combinada del día: las patas de la regla, de más ventaja a menos, una por partido
    a = regla(d, p, e_).assign(dia=lambda x: x.fecha.dt.strftime('%Y-%m-%d'))
    comb = {}
    for kk in (2, 3, 4, 5):
        filas = []
        for dia, g in a.groupby('dia'):
            g = g.sort_values('v', ascending=False).drop_duplicates('mid').head(kk)
            if len(g) < kk:
                continue
            filas.append({'tramo': 'elige' if pd.Timestamp(dia) < corte else 'juzga',
                          'ok': int(g.y.all()), 'momio': float(g.c_mas.prod()),
                          'p': float(g.p_mod.prod())})
        c = pd.DataFrame(filas)
        if c.empty:
            continue
        comb[kk] = {tr: {'dias': int((c.tramo == tr).sum()), 'entera': round(float(c[c.tramo == tr].ok.mean()), 3),
                         'promete': round(float(c[c.tramo == tr].p.mean()), 3),
                         'momio': round(float(c[c.tramo == tr].momio.mean()), 2),
                         'roi': round(float((c[c.tramo == tr].ok * c[c.tramo == tr].momio - 1).mean()), 3)}
                    for tr in ('elige', 'juzga') if (c.tramo == tr).any()}
        print('combinada de', kk, json.dumps(comb[kk], ensure_ascii=False))
    out['combinada'] = comb
    json.dump(out, open('_v362b_escaleras.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1,
              default=str)


if __name__ == '__main__':
    main()
