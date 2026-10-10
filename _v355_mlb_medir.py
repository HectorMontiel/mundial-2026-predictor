#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v355 — MLB: qué apuestas llegan al 75-85 % y qué patrones le ganan a la casa.

Datos: `_v355_mlb_cierres.csv` (28.060 partidos 2010-2021 con el cierre de la
casa: ganador, run line desde 2014 y total, con sus cuotas). Elige 2010-2016,
juzga 2017-2021 (2020 fue de 60 partidos). Bootstrap por partido.

  A. GANADOR por banda de la casa sin margen.
  B. HÁNDICAP (run line) del equipo X con línea h: lo que acierta según la
     probabilidad de X en la casa. Playdoit publica hasta ±4,5.
  C. TOTALES a k carreras de la línea de cierre (Playdoit: de «más de 5» a
     «menos de 10»).
  D. PATRONES contra la casa (lo que la casa NO pone en su precio): estadio
     (altitud: Coors), local/visita, tabla (% de victorias hasta ese día),
     mano del abridor, mes, nivel del total, movimiento de la cuota.
     Se dice «patrón» sólo si se ve en las DOS mitades y el p5 es > 0.
"""
import json
import sys

import numpy as np
import pandas as pd

rng = np.random.default_rng(355)
CORTE = 2016


def cargar():
    d = pd.read_csv('_v355_mlb_cierres.csv')
    d = d.dropna(subset=['runs_home', 'runs_away', 'ml_home', 'ml_away'])
    d = d[~d.neutral]
    s = 1 / d.ml_home + 1 / d.ml_away
    d['p_home'] = (1 / d.ml_home) / s
    d['margen'] = d.runs_home - d.runs_away
    d['tot'] = d.runs_home + d.runs_away
    d['tramo'] = np.where(d.temporada <= CORTE, 'elige', 'juzga')
    d['mes'] = d.fecha.str[5:7].astype(int)
    d = d.sort_values('fecha').reset_index(drop=True)
    return d


def boot(v, n=2000):
    v = np.asarray(v, float)
    if len(v) < 30:
        return None, None
    bs = [v[rng.integers(0, len(v), len(v))].mean() for _ in range(n)]
    return round(float(np.mean(bs)), 4), round(float(np.percentile(bs, 5)), 4)


def ganador(d):
    out = {}
    fav = np.maximum(d.p_home, 1 - d.p_home)
    gana = np.where(d.p_home >= 0.5, d.margen > 0, d.margen < 0)
    b = pd.cut(fav, [0.5, 0.55, 0.6, 0.65, 0.7, 0.75, 1.0])
    for tr in ('elige', 'juzga'):
        f = d.tramo == tr
        t = pd.DataFrame({'b': b[f], 'p': fav[f], 'g': gana[f]}).groupby('b', observed=True).agg(
            n=('g', 'size'), promete=('p', 'mean'), acierta=('g', 'mean')).round(3)
        out[tr] = t.reset_index().astype({'b': str}).to_dict('records')
    out['favoritos_70_o_mas_por_temporada'] = round(float((fav >= 0.70).sum() / d.temporada.nunique()), 1)
    return out


def handicap(d):
    """{banda de prob del equipo: {línea: acierto}} (equipo = local y visitante)."""
    filas = []
    for lado in ('home', 'away'):
        p = d.p_home if lado == 'home' else 1 - d.p_home
        m = d.margen if lado == 'home' else -d.margen
        filas.append(pd.DataFrame({'p': p, 'm': m, 'tramo': d.tramo, 'temporada': d.temporada}))
    t = pd.concat(filas)
    t['banda'] = pd.cut(t.p, [0.2, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70, 0.80])
    lineas = [-2.5, -1.5, 1.5, 2.5, 3.5, 4.5]
    out = {}
    for tr in ('elige', 'juzga'):
        g = t[t.tramo == tr]
        tab = {}
        for b_, gg in g.groupby('banda', observed=True):
            tab[str(b_)] = {'n': int(len(gg)), 'p': round(float(gg.p.mean()), 3),
                            **{'%+g' % h: round(float(((gg.m + h) > 0).mean()), 4) for h in lineas}}
        out[tr] = tab
    return out


def totales(d):
    out = {}
    for tr in ('elige', 'juzga'):
        g = d[(d.tramo == tr) & d.total.notna()]
        tab = {}
        for k in (0.5, 1.5, 2.5, 3.5, 4.5):
            tab['%g' % k] = {'mas': round(float((g.tot > g.total - k).mean()), 4),
                             'menos': round(float((g.tot < g.total + k).mean()), 4)}
        # por nivel del total (bajo / medio / alto)
        for nivel, f in (('bajo<=7.5', g.total <= 7.5), ('medio', (g.total > 7.5) & (g.total < 9.5)),
                         ('alto>=9.5', g.total >= 9.5)):
            gg = g[f]
            tab['nivel_%s' % nivel] = {'n': int(len(gg)), 'mas_k2.5': round(float((gg.tot > gg.total - 2.5).mean()), 4),
                                       'menos_k2.5': round(float((gg.tot < gg.total + 2.5).mean()), 4),
                                       'mas_k3.5': round(float((gg.tot > gg.total - 3.5).mean()), 4),
                                       'menos_k3.5': round(float((gg.tot < gg.total + 3.5).mean()), 4)}
        out[tr] = tab
    return out


def _tabla_corrida(d):
    """% de victorias de cada equipo ANTES de cada partido (misma temporada)."""
    pct_h, pct_a = [], []
    reg = {}
    for r in d.itertuples():
        kh, ka = (r.temporada, r.home), (r.temporada, r.away)
        wh, gh = reg.get(kh, (0, 0))
        wa, ga = reg.get(ka, (0, 0))
        pct_h.append(wh / gh if gh >= 15 else np.nan)
        pct_a.append(wa / ga if ga >= 15 else np.nan)
        hw = 1 if r.margen > 0 else 0
        reg[kh] = (wh + hw, gh + 1)
        reg[ka] = (wa + 1 - hw, ga + 1)
    d['pct_h'], d['pct_a'] = pct_h, pct_a
    return d


def patrones(d):
    """Residuo contra la casa: (real − prometido) por grupo, en las dos mitades."""
    out = {}
    d = _tabla_corrida(d)
    res_ml = (d.margen > 0).astype(float) - d.p_home          # local gana − lo que prometía
    tm = d.total.notna()
    res_tot = (d.tot > d.total).astype(float) - 0.5            # «más» por encima de 50 %
    res_tot[d.tot == d.total] = np.nan

    def grupo(nombre, mask, serie):
        r = {}
        for tr in ('elige', 'juzga'):
            v = serie[mask & (d.tramo == tr)].dropna()
            r[tr] = {'n': int(len(v)), 'residuo_y_p5': boot(v)}
        out[nombre] = r

    # estadio (por local): sólo los que destacan en el total
    for eq in sorted(d.home.unique()):
        grupo('estadio_%s_mas' % eq, (d.home == eq) & tm, res_tot)
    grupo('local_favorito', d.p_home >= 0.5, res_ml)
    grupo('local_no_favorito', d.p_home < 0.5, -(-res_ml))
    dif = d.pct_h - d.pct_a
    grupo('local_con_mejor_tabla_10pts', dif >= 0.10, res_ml)
    grupo('local_con_peor_tabla_10pts', dif <= -0.10, res_ml)
    zurdo_h = d.home_sp.str.endswith('-L')
    zurdo_a = d.away_sp.str.endswith('-L')
    grupo('abridor_local_zurdo', zurdo_h, res_ml)
    grupo('abridor_visita_zurdo', zurdo_a, -res_ml)
    for mes in (4, 5, 6, 7, 8, 9):
        grupo('mes_%02d_mas' % mes, (d.mes == mes) & tm, res_tot)
    grupo('total_bajo_7.5_mas', (d.total <= 7.5), res_tot)
    grupo('total_alto_9.5_mas', (d.total >= 9.5), res_tot)
    mov = (1 / d.ml_home) / (1 / d.ml_home + 1 / d.ml_away) - \
          (1 / d.ml_home_open) / (1 / d.ml_home_open + 1 / d.ml_away_open)
    grupo('cuota_local_sube_3pts', mov >= 0.03, res_ml)
    grupo('cuota_local_baja_3pts', mov <= -0.03, res_ml)
    # los que pasan: mismo signo en las dos mitades y p5 > 0 (o p95 < 0)
    pasan = []
    for k, v in out.items():
        e, j = v['elige']['residuo_y_p5'], v['juzga']['residuo_y_p5']
        if e[0] is None or j[0] is None:
            continue
        if e[1] > 0 and j[1] > 0:
            pasan.append((k, e, j, v['juzga']['n']))
    return out, pasan


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    d = cargar()
    print('partidos', len(d), d.temporada.min(), d.temporada.max())
    res = {'partidos': int(len(d)), 'ganador': ganador(d), 'handicap': handicap(d),
           'totales': totales(d)}
    pat, pasan = patrones(d.copy())
    res['patrones'] = pat
    res['patrones_que_pasan'] = pasan
    print(json.dumps(res['ganador'], indent=0)[:1500])
    for tr in ('elige', 'juzga'):
        print('\nHÁNDICAP', tr)
        print(pd.DataFrame(res['handicap'][tr]).T.to_string())
    print('\nTOTALES'); print(json.dumps(res['totales'], indent=0))
    print('\nPATRONES QUE PASAN (p5>0 en las dos mitades):')
    for x in pasan:
        print('  ', x)
    # el residuo de los estadios, para ver Coors
    est = sorted(((k, v['elige']['residuo_y_p5'][0], v['juzga']['residuo_y_p5'][0])
                  for k, v in pat.items() if k.startswith('estadio_')
                  and v['elige']['residuo_y_p5'][0] is not None),
                 key=lambda z: -(z[1] + z[2]))
    print('\nESTADIOS (más de la línea − 50 %): primeros y últimos')
    for x in est[:5] + est[-5:]:
        print('  ', x)
    json.dump(res, open('_v355_mlb_medir.json', 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1, default=str)


if __name__ == '__main__':
    main()
