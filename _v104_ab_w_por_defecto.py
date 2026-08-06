#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v104 — El valor por defecto de `w` para las 31 competiciones sin calibrar.

Lo que se encontró
------------------
`calibracion_mercado.json` asigna un peso propio del modelo frente al mercado a
29 competiciones, y su nota lo dice claro: **«Liga ausente = w=1 = sin
corrección»**. Es decir, las 31 competiciones que no tienen entrada propia
publican la probabilidad del modelo CRUDA, sin mirar el precio. Entre ellas:
Champions, Europa League, Conference League, Liga MX, Premier, Libertadores.

Ahí nació el pick que el usuario señaló: el modelo daba 46 % al Vikingur
Reykjavik y el mercado 10,5 %, y como la Conference no tiene `w`, se publicó el
46 %.

El A/B general (`_v104_ab_w_adaptativo.py`) ya midió que en 1X2 de fútbol la
probabilidad del mercado bate a la del modelo (log-loss 1,024 → 1,000, acierto
49,4 % → 50,8 %). Aquí se comprueba lo específico: **¿pasa también en esas 31
competiciones concretas?** Porque cambiar un valor por defecto que afecta a
media plataforma no se hace con una media global.

Se barre `w` y se elige en la mitad temprana; el juicio va en la tardía.
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

BOOT = 4000
SEMILLA = 104
SALIDA = '_v104_ab_w_por_defecto.json'
REJILLA = (0.0, 0.10, 0.25, 0.40, 0.60, 0.80, 1.0)


def main():
    cal = json.load(open('calibracion_mercado.json', encoding='utf-8'))
    con_w = set((cal.get('ligas') or {}).keys())
    d = pd.read_csv('pick_ledger.csv').dropna(
        subset=['p_home', 'p_draw', 'p_away', 'resultado',
                'cuota_home', 'cuota_draw', 'cuota_away'])
    d = d.sort_values('fecha', kind='stable').reset_index(drop=True)
    sin_w = ~d['liga'].isin(con_w)
    print(f'{len(d)} predicciones con cuota · '
          f'{int(sin_w.sum())} en competiciones SIN w propio '
          f'({d.loc[sin_w, "liga"].nunique()} competiciones)\n')

    P = d[['p_home', 'p_draw', 'p_away']].to_numpy(dtype=float)
    inv = 1.0 / d[['cuota_home', 'cuota_draw', 'cuota_away']].to_numpy(dtype=float)
    M = inv / inv.sum(axis=1, keepdims=True)
    y = d['resultado'].to_numpy(dtype=int)
    cuotas = d[['cuota_home', 'cuota_draw', 'cuota_away']].to_numpy(dtype=float)
    idx = np.arange(len(d))
    n = len(d)
    corte = int(n * 0.5)
    temprano = (np.arange(n) < corte) & sin_w.to_numpy()
    tarde = (np.arange(n) >= corte) & sin_w.to_numpy()

    def metricas(w, msk):
        Q = w * P + (1 - w) * M
        Q = Q / Q.sum(axis=1, keepdims=True)
        ll = -np.log(np.clip(Q[idx, y], 1e-9, 1))
        lado = Q.argmax(axis=1)
        ac = (lado == y).astype(float)
        cu = cuotas[idx, lado]
        g = ac * (cu - 1) - (1 - ac)
        return ll, ac, g, Q

    print('barrido en la mitad temprana (sólo competiciones sin w):')
    mejor = None
    for w in REJILLA:
        ll, ac, g, _ = metricas(w, temprano)
        print(f'  w={w:.2f} · log-loss {ll[temprano].mean():.5f} · '
              f'acierto {ac[temprano].mean():.4f} · ROI {g[temprano].mean()*100:+.2f}%')
        if mejor is None or ll[temprano].mean() < mejor[1]:
            mejor = (w, ll[temprano].mean())
    w_elegido = mejor[0]
    print(f'  -> elegido w={w_elegido:.2f}\n')

    print('juicio en la mitad tardía:')
    ll1, ac1, g1, _ = metricas(1.0, tarde)          # lo que hay hoy
    ll2, ac2, g2, _ = metricas(w_elegido, tarde)    # el candidato
    print(f'  hoy (w=1, modelo solo) · log-loss {ll1[tarde].mean():.5f} · '
          f'acierto {ac1[tarde].mean():.4f} · ROI {g1[tarde].mean()*100:+.2f}%')
    print(f'  candidato (w={w_elegido:.2f})   · log-loss {ll2[tarde].mean():.5f} · '
          f'acierto {ac2[tarde].mean():.4f} · ROI {g2[tarde].mean()*100:+.2f}%')
    dif = ll1[tarde] - ll2[tarde]
    rng = np.random.default_rng(SEMILLA)
    bt = np.array([dif[rng.integers(0, len(dif), len(dif))].mean()
                   for _ in range(BOOT)])
    p5 = float(np.percentile(bt, 5))
    ver = 'ADOPTAR' if p5 > 0 and ac2[tarde].mean() >= ac1[tarde].mean() - 0.002 \
        else 'RECHAZAR'
    print(f'  mejora {dif.mean():+.5f} · p5 {p5:+.5f} · {ver}')

    salida = {'w_elegido': w_elegido, 'n_sin_w': int(sin_w.sum()),
              'competiciones': int(d.loc[sin_w, 'liga'].nunique()),
              'hoy': {'ll': float(ll1[tarde].mean()),
                      'acierto': float(ac1[tarde].mean()),
                      'roi_pct': float(g1[tarde].mean() * 100)},
              'candidato': {'ll': float(ll2[tarde].mean()),
                            'acierto': float(ac2[tarde].mean()),
                            'roi_pct': float(g2[tarde].mean() * 100)},
              'mejora': float(dif.mean()), 'p5': p5, 'veredicto': ver}

    # por competición, para ver si alguna se rompe
    print('\npor competición (las 10 con más muestra en la mitad tardía):')
    ligas = d.loc[tarde, 'liga'].value_counts().head(10)
    salida['por_competicion'] = {}
    for lg, cnt in ligas.items():
        m = tarde & (d['liga'] == lg).to_numpy()
        if m.sum() < 60:
            continue
        print(f'  {lg:24} n={int(m.sum()):>5} · log-loss {ll1[m].mean():.4f} → '
              f'{ll2[m].mean():.4f} · acierto {ac1[m].mean():.3f} → '
              f'{ac2[m].mean():.3f}')
        salida['por_competicion'][lg] = {
            'n': int(m.sum()), 'll_hoy': float(ll1[m].mean()),
            'll_candidato': float(ll2[m].mean()),
            'acierto_hoy': float(ac1[m].mean()),
            'acierto_candidato': float(ac2[m].mean())}

    json.dump(salida, open(SALIDA, 'w', encoding='utf-8'), indent=1,
              ensure_ascii=False)
    print(f'\n-> {SALIDA}')


if __name__ == '__main__':
    main()
