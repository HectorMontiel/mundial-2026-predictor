#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v361 — El «Método Contexto» (la metodología del amigo) para goles, córners
y tarjetas, además de los tiros.

El usuario: «en el análisis de cada tarjeta quiero goles, tarjetas, córners,
tiros y tiros a puerta con su porcentaje; ocupa la metodología de mi amigo
y ponle nombre». La metodología (v344-v345, `tiros_equipo`): la tabla y la
presión de la temporada, goles a favor y en contra, posesión, faltas del
rival, córners, tarjetas, la fuerza por precio, la forma ponderada, la
calidad de los rivales y el descanso. Ya predecía los tiros mucho mejor que
«los últimos 5» (log-loss 0,549 contra 0,632).

Aquí, con los mismos datos y rasgos (`tiros_equipo.cargar_partidos`, `rasgos`;
históricos de ESPN 2021-2026 con estadística real), por equipo y partido:

  · objetivos: goles (gf), córners, tarjetas amarillas; y tiros / a puerta
    como control (ya medidos);
  · B1 «últimos 5» (la media de sus 5 anteriores);
  · B2 ataque × defensa (su media de la temporada × lo que concede el rival
    / la media de la liga);
  · M  el Método Contexto (LightGBM Poisson con todos los rasgos).
Se entrena con el 70 % más antiguo de fechas y se juzga con el 30 % reciente:
desviación de Poisson y log-loss de «más de X» en las líneas típicas, con
bootstrap por partido de la mejora. Escribe `_v361_metodo.json`.
"""
import json
import sys

import numpy as np
import pandas as pd

import tiros_equipo as te

rng = np.random.default_rng(361)
OBJ = {'goles': 'gf', 'corners': 'corners', 'tarjetas': 'amarillas',
       'tiros': 'tiros', 'a_puerta': 'a_puerta'}
CONCEDE = {'gf': 'gc', 'corners': 'corners_c', 'amarillas': None,
           'tiros': 'tiros_c', 'a_puerta': 'a_puerta_c'}


def preparar():
    d = te.cargar_partidos()
    e = te.rasgos(te.a_equipos(d))
    e = e[(e.n_prev >= te.MIN_PARTIDOS) & (e.r_n_prev >= te.MIN_PARTIDOS)]
    e = e.dropna(subset=['p_gana'])
    return e


def dev_poisson(y, mu):
    y, mu = np.asarray(y, float), np.clip(np.asarray(mu, float), 1e-3, None)
    t = np.where(y > 0, y * np.log(y / mu), 0.0)
    return 2 * (t - (y - mu))


def logloss_lineas(y, mu, k, lineas):
    """log-loss medio de «más de L» para cada línea (por fila)."""
    from scipy import stats
    y, mu = np.asarray(y, float), np.clip(np.asarray(mu, float), 1e-3, None)
    p = k / (k + mu)
    tot = np.zeros(len(y))
    for L in lineas:
        q = np.clip(stats.nbinom.sf(np.floor(L), k, p), 1e-4, 1 - 1e-4)
        o = (y > L).astype(float)
        tot += -(o * np.log(q) + (1 - o) * np.log(1 - q))
    return tot / len(lineas)


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    import lightgbm as lgb
    e = preparar()
    corte = e.fecha.quantile(0.70)
    ent, jui = e[e.fecha < corte], e[e.fecha >= corte]
    print('filas', len(e), 'entrenar', len(ent), 'juzgar', len(jui), 'corte', str(corte)[:10],
          'ligas', e.liga.nunique())
    out = {'filas': int(len(e)), 'corte': str(corte)[:10], 'objetivos': {}}
    for nombre, obj in OBJ.items():
        a, b = ent.dropna(subset=[obj]), jui.dropna(subset=[obj])
        if len(b) < 500:
            continue
        m = lgb.LGBMRegressor(objective='poisson', n_estimators=700, learning_rate=0.03,
                              num_leaves=31, min_child_samples=80, subsample=0.8,
                              subsample_freq=1, colsample_bytree=0.8, reg_lambda=1.0,
                              verbose=-1, random_state=361)
        m.fit(a[te.COLUMNAS], a[obj])
        mu_m = np.clip(m.predict(b[te.COLUMNAS]), 0.05, None)
        mu_1 = b['l5_' + obj].fillna(b['t_' + obj]).clip(lower=0.05).values
        conc = CONCEDE[obj]
        liga_m = a.groupby('liga')[obj].mean()
        lm = b.liga.map(liga_m).fillna(a[obj].mean()).values
        if conc:
            mu_2 = (b['t_' + obj] * b['r_t_' + conc] / lm).clip(lower=0.05).values
        else:
            mu_2 = ((b['t_' + obj] + b['r_t_' + obj]) / 2).clip(lower=0.05).values
        mu_2 = np.where(np.isfinite(mu_2), mu_2, mu_1)
        y = b[obj].values
        k = te.ajustar_k(y, mu_m)
        base = float(np.median(y))
        lineas = [max(base - 1, 0) + 0.5, base + 0.5, base + 1.5] if base >= 1 else [0.5, 1.5]
        r = {'n': int(len(b)), 'media': round(float(y.mean()), 3), 'k': round(k, 1),
             'lineas': lineas}
        dm, d1, d2 = dev_poisson(y, mu_m), dev_poisson(y, mu_1), dev_poisson(y, mu_2)
        lm_, l1, l2 = (logloss_lineas(y, mu_m, k, lineas), logloss_lineas(y, mu_1, k, lineas),
                       logloss_lineas(y, mu_2, k, lineas))
        mids = b.mid.values
        um = np.unique(mids)
        idx = {u: np.where(mids == u)[0] for u in um}

        def boot(x, n=600):
            s = []
            for _ in range(n):
                sel = rng.choice(um, len(um))
                ii = np.concatenate([idx[u] for u in sel])
                s.append(x[ii].mean())
            return round(float(np.percentile(s, 5)), 5)
        r.update({'desv_metodo': round(float(dm.mean()), 4), 'desv_ult5': round(float(d1.mean()), 4),
                  'desv_atq_def': round(float(d2.mean()), 4),
                  'll_metodo': round(float(lm_.mean()), 4), 'll_ult5': round(float(l1.mean()), 4),
                  'll_atq_def': round(float(l2.mean()), 4),
                  'mejora_vs_ult5_p5': boot(l1 - lm_), 'mejora_vs_atq_def_p5': boot(l2 - lm_)})
        # ¿promete lo que acierta? «más de» la línea central, por banda
        from scipy import stats
        L = lineas[1] if len(lineas) > 1 else lineas[0]
        q = stats.nbinom.sf(np.floor(L), k, k / (k + mu_m))
        bb = pd.cut(q, [0, 0.3, 0.5, 0.6, 0.7, 0.8, 1.0])
        r['calibracion_mas_%s' % L] = [
            {'banda': str(kk), 'n': int(len(g)), 'promete': round(float(g.q.mean()), 3),
             'acierta': round(float(g.o.mean()), 3)}
            for kk, g in pd.DataFrame({'q': q, 'o': (y > L).astype(float), 'b': bb}).groupby('b', observed=True)]
        out['objetivos'][nombre] = r
        print(nombre, json.dumps({kk: v for kk, v in r.items() if not kk.startswith('calib')},
                                 ensure_ascii=False))
        print('   calibración', r['calibracion_mas_%s' % L])
    json.dump(out, open('_v361_metodo.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1,
              default=str)


if __name__ == '__main__':
    main()
