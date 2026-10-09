#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v348 — «Ambos marcan» con la metodología del usuario.

Lo mismo que se hizo con los tiros (`_v345_tiros.py`): las variables de la
metodología (tabla y presión, goles a favor y en contra, tiros, posesión,
faltas del rival, córners, tarjetas, forma ponderada, plantilla por la cuota)
de los DOS equipos, en un LightGBM binario, contra:

    B   la Poisson de ataque × defensa de la temporada (lo clásico)

  A. HISTORIAL (2021-2026, 43 ligas con estadística ESPN): elige 70 % /
     juzga 30 %, log-loss y calibración en las bandas altas.
  B. CONTRA PLAYDOIT (`btts_cuotas` de las fotos del tablero, 24-ago en
     adelante): log-loss contra la casa y una regla de «meter» (el lado del
     modelo ≥ X), elegida con la primera mitad y juzgada con la segunda.
"""
import json

import numpy as np
import pandas as pd

import _v344_precio as P
import _v345_tiros as V

rng = np.random.default_rng(3481)
DESDE = V.DESDE
EQ = ['t_gf', 't_gc', 'l5_gf', 'l5_gc', 't_tiros', 't_a_puerta', 't_tiros_c',
      't_a_puerta_c', 'ew_tiros', 'ew_a_puerta', 'ew_tiros_c', 'ew_a_puerta_c',
      't_pos', 't_faltas', 't_faltas_r', 't_corners', 't_amarillas', 'ppg',
      'pos_rel', 'zona_baja', 'zona_alta', 'presion', 'n_prev', 'v_tiros',
      'v_tiros_c', 'descanso', 't_ratio']


def partidos():
    e = V._base(V.preparar())
    h = e[e.local == 1]
    a = e[e.local == 0]
    cols = ['mid', 'fecha', 'liga'] + EQ + ['p_gana', 'p_pierde', 'p_empate',
                                           'gf', 'gc', 'equipo', 'rival']
    m = h[cols].merge(a[['mid'] + EQ], on='mid', suffixes=('_h', '_a'))
    m['btts'] = ((m.gf > 0) & (m.gc > 0)).astype(int)
    # B: Poisson de ataque × defensa, encogida hacia la liga
    lg = m.groupby('liga').gf.transform('mean') * 0 + 1.35
    lh = (m.t_gf_h * m.n_prev_h + lg * 5) / (m.n_prev_h + 5)
    la = (m.t_gf_a * m.n_prev_a + lg * 5) / (m.n_prev_a + 5)
    dh = (m.t_gc_a * m.n_prev_a + lg * 5) / (m.n_prev_a + 5)
    da = (m.t_gc_h * m.n_prev_h + lg * 5) / (m.n_prev_h + 5)
    m['lam_h'] = lh * dh / lg
    m['lam_a'] = la * da / lg
    m['p_poisson'] = (1 - np.exp(-m.lam_h)) * (1 - np.exp(-m.lam_a))
    return m


def ll(p, y):
    p = np.clip(p, 1e-4, 1 - 1e-4)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


def modelo(ent):
    import lightgbm as lgb
    X = [c + s for c in EQ for s in ('_h', '_a')] + ['p_gana', 'p_pierde', 'p_empate', 'p_poisson']
    mdl = lgb.LGBMClassifier(n_estimators=500, learning_rate=0.03, num_leaves=31,
                             min_child_samples=100, subsample=0.8, subsample_freq=1,
                             colsample_bytree=0.8, reg_lambda=1.0, verbose=-1,
                             random_state=348)
    mdl.fit(ent[X], ent.btts)
    return mdl, X


def boot(dif, mids):
    um, inv = np.unique(mids, return_inverse=True)
    s, n = np.bincount(inv, weights=dif), np.bincount(inv)
    bs = [s[i].sum() / n[i].sum() for i in
          (rng.integers(0, len(um), len(um)) for _ in range(3000))]
    return round(float(np.mean(bs)), 5), round(float(np.percentile(bs, 5)), 5)


def parte_a(m):
    m = m[m.fecha < DESDE]
    corte = m.fecha.quantile(0.70)
    el, ju = m[m.fecha < corte], m[m.fecha >= corte]
    mdl, X = modelo(el)
    p = mdl.predict_proba(ju[X])[:, 1]
    y = ju.btts.values
    out = {'n_juzga': int(len(ju)), 'll_poisson': round(float(ll(ju.p_poisson.values, y).mean()), 4),
           'll_modelo': round(float(ll(p, y).mean()), 4),
           'modelo_vs_poisson': boot(ll(ju.p_poisson.values, y) - ll(p, y), ju.mid.values)}
    f = pd.DataFrame({'p': np.r_[p, 1 - p], 'y': np.r_[y, 1 - y]})
    f = f[f.p >= 0.6]
    f['b'] = pd.cut(f.p, [0.6, 0.65, 0.7, 0.75, 0.8, 1.0], right=False)
    out['calibracion'] = f.groupby('b', observed=True).agg(
        n=('y', 'size'), promete=('p', 'mean'), acierta=('y', 'mean')).round(4).reset_index().astype(str).to_dict('records')
    return out


def parte_b(m):
    el, ju = m[m.fecha < DESDE], m[m.fecha >= DESDE].copy()
    mdl, X = modelo(el)
    ju['p_mod'] = mdl.predict_proba(ju[X])[:, 1]
    tab = P.tableros()
    # las fotos de `_v344_precio` no guardan el BTTS: se leen de nuevo
    import _v344_patrones as PT
    tab2 = PT.tableros_todo() if False else None
    filas = []
    tb = _tableros_btts()
    prox = pd.DataFrame({'mid': ju.mid, 'liga': ju.liga, 'fecha': ju.fecha,
                         'equipo': ju.equipo, 'rival': ju.rival})
    casa = P.emparejar(prox, tb)
    for r in ju.itertuples():
        b = casa.get(r.mid)
        if not b:
            continue
        c = P._lineas(b.get('btts_cuotas'))
        if not (c.get('si') and c.get('no')):
            continue
        pc = (1 / c['si']) / (1 / c['si'] + 1 / c['no'])
        filas.append({'mid': r.mid, 'fecha': r.fecha, 'liga': r.liga, 'y': r.btts,
                      'p_mod': r.p_mod, 'p_casa': pc, 'c_si': c['si'], 'c_no': c['no']})
    d = pd.DataFrame(filas)
    out = {'partidos': int(len(d)),
           'll_casa': round(float(ll(d.p_casa.values, d.y.values).mean()), 4),
           'll_modelo': round(float(ll(d.p_mod.values, d.y.values).mean()), 4),
           'modelo_vs_casa': boot(ll(d.p_casa.values, d.y.values) - ll(d.p_mod.values, d.y.values), d.mid.values)}
    corte = d.fecha.quantile(0.5)

    def regla(g, pm, cmin, cmax):
        si = (g.p_mod >= pm) & g.c_si.between(cmin, cmax)
        no = ((1 - g.p_mod) >= pm) & g.c_no.between(cmin, cmax)
        a = pd.DataFrame({'mid': np.r_[g.mid[si], g.mid[no]],
                          'gana': np.r_[g.y[si], 1 - g.y[no]],
                          'cuota': np.r_[g.c_si[si], g.c_no[no]],
                          'p': np.r_[g.p_mod[si], 1 - g.p_mod[no]]})
        if len(a) == 0:
            return {'n': 0}
        gan = (a.gana * a.cuota - 1).values
        r = {'n': len(a), 'acierto': round(float(a.gana.mean()), 4),
             'promete': round(float(a.p.mean()), 4), 'cuota': round(float(a.cuota.mean()), 3),
             'roi': round(float(gan.mean()), 4)}
        r['p5_roi'] = boot(gan, a.mid.values)[1]
        return r
    rej = []
    for pm in (0.60, 0.65, 0.70, 0.75):
        for cmin, cmax in ((1.0, 3.0), (1.15, 1.6)):
            r = regla(d[d.fecha < corte], pm, cmin, cmax)
            if r['n'] >= 30:
                rej.append(((pm, cmin, cmax), r))
    out['rejilla_elige'] = [(k, v['n'], v['acierto'], v['roi'], v['p5_roi']) for k, v in rej]
    if rej:
        k, r_el = max(rej, key=lambda x: x[1]['p5_roi'])
        out['regla'] = k
        out['elige'] = r_el
        out['juzga'] = regla(d[d.fecha >= corte], *k)
    return out


def _tableros_btts():
    import json as _j
    import subprocess
    hs = subprocess.run(['git', 'log', '--format=%H %cI', 'origin/main', '--',
                         'mercado_dia.json'], capture_output=True, text=True).stdout
    filas = []
    for linea in [x for x in hs.split('\n') if x.strip()][::2]:
        h, cuando = linea.split()
        try:
            dd = _j.loads(subprocess.run(['git', 'show', h + ':mercado_dia.json'],
                                         capture_output=True).stdout.decode('utf-8'))
        except Exception:
            continue
        ts = pd.Timestamp(cuando).tz_convert('UTC').tz_localize(None)
        for v in (dd.get('partidos') or {}).values():
            if isinstance(v, dict) and v.get('btts_cuotas'):
                filas.append((ts, v.get('clave_liga'), v.get('home'), v.get('away'),
                              {'btts_cuotas': v.get('btts_cuotas')}))
    t = pd.DataFrame(filas, columns=['ts', 'liga', 'home', 'away', 'board'])
    t['h'] = t.home.map(P._norm)
    t['a'] = t.away.map(P._norm)
    return t


if __name__ == '__main__':
    m = partidos()
    out = {'A_historial': parte_a(m)}
    print(json.dumps(out, ensure_ascii=False, indent=1, default=str))
    out['B_playdoit'] = parte_b(m)
    print(json.dumps(out['B_playdoit'], ensure_ascii=False, indent=1, default=str))
    json.dump(out, open('_v348_btts.json', 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1, default=str)
