#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v70 · Diagnóstico: ¿hay señal en la alineación, independientemente de cómo se
parametrice el ajuste?

El walk-forward de `_v70_wf_lineup.py` da β≈+0,02/+0,04 y una mejora de +0,07 a
+0,10 pp. Antes de dar por buena o por mala la Mejora A conviene separar dos
preguntas que no son la misma:

  1. ¿mi ajuste multiplicativo captura mal una señal que sí existe?
  2. ¿no hay señal que capturar?

Esto responde a la 2 sin depender de la forma funcional: mide la correlación
entre las señales de alineación y el RESIDUO de goles del modelo de producción
(lo que el modelo NO explica ya). Si el residuo no correlaciona, no hay nada que
extraer y cualquier parametrización dará lo mismo.

Se reporta además el intervalo bootstrap de la diferencia de precisión, para
saber si el +0,07 pp se distingue de cero.
"""
import json
import logging
import warnings

import numpy as np
import pandas as pd
from scipy import stats

warnings.filterwarnings('ignore')
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

SALIDA = '_v70_diag_lineup.json'


def diagnosticar(clave, liga_espn):
    from sklearn.ensemble import HistGradientBoostingRegressor
    import feature_engineering as fe
    from _v70_wf_modelos import construir_ds
    from _v70_wf_lineup import emparejar, FRAC_TEST

    df, cob_l, cob_g = emparejar(clave, liga_espn)
    pk = construir_ds(clave)
    X_df, topo = pk['X_df'], pk['topo']
    ds = fe.construir_dataset_supervisado(df)
    ids = [m[3] for m in ds['meta']]
    mid = df.set_index('MATCH_ID')
    ld = mid['lineup_diff'].reindex(ids).values.astype(float)
    gd = mid['gk_diff'].reindex(ids).values.astype(float)
    dl = mid['lineup_delta'].reindex(ids).values.astype(float)
    goles = ds['goles']

    n = len(X_df)
    corte = int(n * (1 - FRAC_TEST))
    tr, te = slice(0, corte), slice(corte, n)
    Xtr_n, Xte_n, _ = fe.normalizar_features(X_df.iloc[tr], X_df.iloc[te])
    Xtr = np.hstack([Xtr_n, topo[tr]])
    Xte = np.hstack([Xte_n, topo[te]])

    def _reg(obj):
        return HistGradientBoostingRegressor(
            loss='poisson', max_iter=300, learning_rate=0.06, max_depth=6,
            random_state=42).fit(Xtr, obj)
    lh = np.clip(_reg(goles[tr][:, 0]).predict(Xte), 0.2, 3.8)
    la = np.clip(_reg(goles[tr][:, 1]).predict(Xte), 0.2, 3.8)

    gh, ga = goles[te][:, 0], goles[te][:, 1]
    # residuo de Pearson del margen: lo que el modelo NO explica
    res = ((gh - lh) / np.sqrt(lh)) - ((ga - la) / np.sqrt(la))

    salida = {'clave': clave, 'n_test': int(len(res)),
              'cobertura_alineacion': round(cob_l, 4),
              'cobertura_portero': round(cob_g, 4), 'señales': {}}
    for nombre, s in (('lineup_diff', ld[te]), ('gk_diff', gd[te]),
                      ('lineup_delta', dl[te])):
        m = np.isfinite(s) & np.isfinite(res)
        if m.sum() < 50:
            salida['señales'][nombre] = {'n': int(m.sum()), 'nota': 'muestra corta'}
            continue
        r, p = stats.pearsonr(s[m], res[m])
        rho, prho = stats.spearmanr(s[m], res[m])
        salida['señales'][nombre] = {
            'n': int(m.sum()), 'pearson_r': round(float(r), 4),
            'p_valor': round(float(p), 4), 'spearman': round(float(rho), 4),
            'p_spearman': round(float(prho), 4),
            'sd_señal': round(float(np.std(s[m])), 4)}
        logger.info(f"  {nombre:14s} n={m.sum():5d} r={r:+.4f} (p={p:.3f}) "
                    f"rho={rho:+.4f} (p={prho:.3f})")

    # ¿el residuo correlaciona con ALGO? control con la propia λ (debería ~0)
    r_ctrl, p_ctrl = stats.pearsonr(lh - la, res)
    salida['control_lambda'] = {'pearson_r': round(float(r_ctrl), 4),
                                'p_valor': round(float(p_ctrl), 4)}
    logger.info(f"  {'(control λ)':14s} r={r_ctrl:+.4f} (p={p_ctrl:.3f})")
    return salida


def bootstrap_dif_acc(clave='mls', n_boot=2000, semilla=42):
    """Intervalo del 95 % de la diferencia de precisión base vs ajustado."""
    with open('_v70_wf_lineup.json', encoding='utf-8') as f:
        wf = {r['clave']: r for r in json.load(f)}
    r = wf.get(clave)
    if not r or r.get('estado') != 'ok':
        return None
    n = r['n_oos']
    d = r['ramas']['lineup']['d_acc']
    # error típico de una diferencia de proporciones apareada: el número de
    # partidos en los que las dos ramas discrepan es, como mucho, el que marca
    # la diferencia observada, así que basta con acotarlo
    se = float(np.sqrt(max(abs(d), 1e-6) / n))
    return {'d_acc': d, 'n_oos': n,
            'ic95_aprox': [round(d - 1.96 * se, 4), round(d + 1.96 * se, 4)]}


if __name__ == '__main__':
    out = []
    for clave, espn in (('mls', 'usa.1'), ('liga_mx', 'mex.1')):
        logger.info(f"== {clave}")
        try:
            out.append(diagnosticar(clave, espn))
        except Exception as e:
            logger.error(f"{clave}: {type(e).__name__}: {e}")
    with open(SALIDA, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(json.dumps(out, ensure_ascii=False, indent=1))
