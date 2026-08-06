#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v104 — El abridor de la KBO, con la elección SEPARADA del juicio.

Por qué se rehace
-----------------
El primer pase midió las seis señales del abridor por separado sobre el mismo
tramo en el que después se juzgó. Salieron dos con p5 positivo (WHIP y BB9), se
probó la pareja y dio +0,0067 con p5 +0,0012 y +4,5 pp de acierto.

Eso no vale, y conviene decir por qué: elegir dos de seis señales mirando el
resultado y luego juzgarlas en ese mismo resultado es pesca. Con seis pruebas al
5 %, que una o dos «pasen» es lo esperable por azar aunque no haya nada.

Aquí la elección se hace SÓLO con los pliegues tempranos y el juicio SÓLO con
los tardíos, que no participan en la decisión. Es el protocolo que el proyecto
usa desde la v35 y el que separa un hallazgo de una casualidad.
"""
import json
import sys
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings('ignore')
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

import contexto_previo as cp

N_PLIEGUES = 6
CORTE_ELECCION = 3        # pliegues 0-2 eligen; 3-5 juzgan
BOOT = 4000
SEMILLA = 104
SALIDA = '_v104_ab_abridor_kbo_limpio.json'
SENALES = ['sp_era', 'sp_whip', 'sp_k9', 'sp_bb9', 'sp_hr9', 'bullpen_n']
# ERA/WHIP/BB9/HR9: menos es mejor → se invierte para que «más alto» sea
# siempre «mejor el local»
INVERTIR = {'sp_era', 'sp_whip', 'sp_bb9', 'sp_hr9'}


def _wf(X, y, bordes):
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    p = np.full(len(y), np.nan)
    for i in range(N_PLIEGUES):
        ini, fin = bordes[i], bordes[i + 1]
        if ini < 150 or len(np.unique(y[:ini])) < 2:
            continue
        sc = StandardScaler().fit(X[:ini])
        m = LogisticRegression(max_iter=3000).fit(sc.transform(X[:ini]), y[:ini])
        p[ini:fin] = m.predict_proba(sc.transform(X[ini:fin]))[:, 1]
    return p


def main():
    pv = pd.read_csv('kbo_preview.csv')
    h = pd.read_csv('historico_kbo.csv')
    h['fecha'] = pd.to_datetime(h['date'], errors='coerce').dt.strftime('%Y-%m-%d')
    d = h.merge(pv, on=['fecha', 'home_team', 'away_team'], how='inner')
    d = d[d['home_runs'] != d['away_runs']]
    d = d.sort_values('fecha', kind='stable').reset_index(drop=True)
    n = len(d)
    y = (d['home_runs'] > d['away_runs']).astype(float).to_numpy()
    bordes = [int(n * (0.4 + 0.1 * i)) for i in range(N_PLIEGUES + 1)]
    d['res_kbo'] = y
    ea, eb, _ = cp.elo_rodante(d, 'home_team', 'away_team', 'res_kbo',
                               ventaja_a=cp.ELO_VENTAJA_LOCAL)
    base = ((ea - eb) / cp.ESCALA_ELO).reshape(-1, 1)
    print(f'{n} partidos cruzados · elección en pliegues 0-{CORTE_ELECCION-1}, '
          f'juicio en {CORTE_ELECCION}-{N_PLIEGUES-1}')

    cols = {}
    for s in SENALES:
        hh = pd.to_numeric(d.get(f'home_{s}'), errors='coerce')
        aa = pd.to_numeric(d.get(f'away_{s}'), errors='coerce')
        if hh is None or aa is None:
            continue
        v = (aa - hh) if s in INVERTIR else (hh - aa)
        cols[s] = v.fillna(0.0).to_numpy(dtype=float)

    pa = _wf(base, y, bordes)
    eleccion = (np.arange(n) >= bordes[0]) & (np.arange(n) < bordes[CORTE_ELECCION])
    juicio = np.arange(n) >= bordes[CORTE_ELECCION]

    def ll_en(p, msk):
        yy = y[msk]
        q = np.clip(p[msk], 1e-9, 1 - 1e-9)
        return -(yy * np.log(q) + (1 - yy) * np.log(1 - q))

    # --- ELECCIÓN: qué señales mejoran en el tramo temprano ---------------
    print('\nelección (pliegues tempranos, NO se juzga aquí):')
    elegidas = []
    for s, v in cols.items():
        pb = _wf(np.column_stack([base, v]), y, bordes)
        m = eleccion & ~np.isnan(pa) & ~np.isnan(pb)
        if m.sum() < 100:
            continue
        mejora = float((ll_en(pa, m) - ll_en(pb, m)).mean())
        print(f'  {s:<12} mejora {mejora:+.6f} {"·  elegida" if mejora > 0 else ""}')
        if mejora > 0:
            elegidas.append(s)
    print(f'  -> elegidas: {elegidas or "ninguna"}')
    if not elegidas:
        json.dump({'veredicto': 'RECHAZAR', 'motivo': 'ninguna señal elegida'},
                  open(SALIDA, 'w', encoding='utf-8'), indent=1, ensure_ascii=False)
        return

    # --- JUICIO: sólo en el tramo que no participó ------------------------
    X = np.column_stack([base] + [cols[s] for s in elegidas])
    pb = _wf(X, y, bordes)
    m = juicio & ~np.isnan(pa) & ~np.isnan(pb)
    yy = y[m]
    ea_, eb_ = ll_en(pa, m), ll_en(pb, m)
    dif = ea_ - eb_
    rng = np.random.default_rng(SEMILLA)
    bt = np.array([dif[rng.integers(0, len(dif), len(dif))].mean()
                   for _ in range(BOOT)])
    p5 = float(np.percentile(bt, 5))
    acc_a = float(((pa[m] >= .5) == yy).mean())
    acc_b = float(((pb[m] >= .5) == yy).mean())
    ver = 'ADOPTAR' if p5 > 0 and acc_b >= acc_a - 0.002 else 'RECHAZAR'
    print(f'\njuicio (n={int(m.sum())}):')
    print(f'  base            log-loss {ea_.mean():.5f} · acierto {acc_a:.4f}')
    print(f'  base + elegidas log-loss {eb_.mean():.5f} · acierto {acc_b:.4f}')
    print(f'  mejora {dif.mean():+.6f} · p5 {p5:+.6f} · {ver}')

    json.dump({'n_cruzados': int(n), 'n_juzgados': int(m.sum()),
               'elegidas': elegidas, 'll_base': float(ea_.mean()),
               'll_con': float(eb_.mean()), 'mejora': float(dif.mean()),
               'p5': p5, 'acc_base': acc_a, 'acc_con': acc_b,
               'veredicto': ver},
              open(SALIDA, 'w', encoding='utf-8'), indent=1, ensure_ascii=False)
    print(f'\n-> {SALIDA}')


if __name__ == '__main__':
    main()
