#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v86 — Encogimiento hacia un prior de ELO, medido en la población CORRECTA.

El diagnóstico, ya cerrado
--------------------------
Tres mediciones, y sólo la tercera es válida:

  · v85, correlación sobre emparejamientos SINTÉTICOS de los 14 mejores equipos:
    32 ligas "rotas", 4 invertidas. Artefacto: al quedarse con los 14 mejores se
    comprime el rango de ELO mientras la forma varía a rango completo.

  · v86, correlación sobre el ledger REAL: mediana rho +0,76, ninguna liga
    invertida. También engañoso, pero al revés: en partidos reales el ELO va
    correlacionado con la forma y los goles, así que P(local) parece seguir al
    ELO aunque el modelo no lo use.

  · v86, DEPENDENCIA PARCIAL (_v86_dependencia_elo.py): se mueve SÓLO el ELO y
    se deja todo lo demás congelado. Es causal dentro del modelo y no lo puede
    falsear ni el rango ni la colinealidad. Resultado:

        subir 600 puntos de ELO mueve P(local) +0,0751 de MEDIANA
        15 ligas planas (|salto| <= 0,02) · 2 invertidas
        liga_mx: +0,0173   <- el caso Puebla

    O sea: el usuario tenía razón. El modelo apenas responde a la fuerza.

Qué se mide aquí
----------------
Encoger la probabilidad del modelo hacia un prior de ELO, con las correcciones
metodológicas que v85 dejó pendientes:

  POBLACIÓN: las filas SIN ancla de mercado. Es la ficha de partido, que es
  donde el modelo va suelto (cuando hay mercado, `calibracion_mercado` ya
  encoge hacia él). v85 midió sobre todo el ledger: población equivocada.

  PRIOR: de ELO, no la tasa base. v85 usó la tasa base porque el ledger no
  tenía el ELO; ahora sí lo tiene (`elo_por_partido.csv`).

  MÉTRICA: en una ficha no se apuesta, se muestra una probabilidad. Lo que
  importa es la CALIBRACIÓN (log-loss y ECE), no el ROI, que ahí no existe.
  Pero se comprueba aparte que el ROI de las filas CON mercado no empeore, por
  si el cambio se filtrara a los picks.

  SIN FUGA: los parámetros del prior se ajustan con pliegues anteriores y se
  evalúan en el siguiente (walk-forward sobre la columna `pliegue`).
"""
import json
import sys

import numpy as np
import pandas as pd

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

PESOS = [1.0, 0.95, 0.90, 0.85, 0.80, 0.75, 0.70, 0.60, 0.50]
N_BOOT = 4000


def prior_elo(diff_tr, y_tr, diff_te):
    """
    Prior de 3 vías a partir del ELO, ajustado SOLO con el train.

    Regresión logística multinomial con una única variable (DIFF_ELO). Con una
    sola feature el orden local/visitante es monótono por construcción, que es
    justo la propiedad que le falta al modelo grande.
    """
    from sklearn.linear_model import LogisticRegression
    m = LogisticRegression(max_iter=1000, C=1.0)
    m.fit(diff_tr.reshape(-1, 1), y_tr)
    p = m.predict_proba(diff_te.reshape(-1, 1))
    out = np.zeros((len(diff_te), 3))
    for i, k in enumerate(m.classes_):
        out[:, int(k)] = p[:, i]
    return out, m


def ece(p, y, bins=10):
    """Error de calibración esperado sobre la clase predicha."""
    conf = p.max(axis=1)
    pred = p.argmax(axis=1)
    acierto = (pred == y).astype(float)
    bordes = np.linspace(0, 1, bins + 1)
    e = 0.0
    for i in range(bins):
        m = (conf > bordes[i]) & (conf <= bordes[i + 1])
        if m.sum() == 0:
            continue
        e += m.mean() * abs(acierto[m].mean() - conf[m].mean())
    return float(e)


def metricas(p, y):
    p = np.clip(p, 1e-9, 1)
    p = p / p.sum(axis=1, keepdims=True)
    return {
        'log_loss': float(-np.log(p[np.arange(len(y)), y]).mean()),
        'precision': float((p.argmax(axis=1) == y).mean()),
        'ece': ece(p, y),
    }


def main():
    led = pd.read_csv('pick_ledger_total.csv')
    elo = pd.read_csv('elo_por_partido.csv')
    d = (led[led['deporte'] == 'Fútbol']
         .merge(elo, on=['liga', 'match_id'], how='inner')
         .sort_values(['pliegue', 'fecha'])
         .reset_index(drop=True))

    sin_mercado = d['cuota_home'].isna()
    print('=' * 84)
    print('v86 · ENCOGIMIENTO HACIA UN PRIOR DE ELO')
    print('=' * 84)
    print(f'  ledger de fútbol con ELO : {len(d)}')
    print(f'  SIN ancla de mercado     : {int(sin_mercado.sum())}  '
          f'<- la ficha de partido, población objetivo')
    print(f'  CON ancla de mercado     : {int((~sin_mercado).sum())}  '
          f'<- control, no debe empeorar')

    pliegues = sorted(d['pliegue'].unique())
    print(f'  pliegues                 : {pliegues}')

    # --- walk-forward: prior ajustado con pliegues anteriores ---------------
    filas_out = []
    for k in pliegues[1:]:
        tr = d[d['pliegue'] < k]
        te = d[d['pliegue'] == k]
        if len(tr) < 500 or len(te) < 100:
            continue
        p_elo, modelo = prior_elo(tr['diff_elo'].values,
                                  tr['resultado'].values.astype(int),
                                  te['diff_elo'].values)
        t = te.copy()
        t['pe_home'], t['pe_draw'], t['pe_away'] = p_elo[:, 0], p_elo[:, 1], p_elo[:, 2]
        filas_out.append(t)

    ev = pd.concat(filas_out, ignore_index=True)
    print(f'\n  evaluables fuera de muestra (pliegues {pliegues[1:]}): {len(ev)}')

    pm = ev[['p_home', 'p_draw', 'p_away']].values.astype(float)
    pe = ev[['pe_home', 'pe_draw', 'pe_away']].values.astype(float)
    y = ev['resultado'].values.astype(int)
    sm = ev['cuota_home'].isna().values

    # cordura del prior
    mp = metricas(pe, y)
    mm = metricas(pm, y)
    print(f'\n  cordura del prior de ELO solo: log-loss {mp["log_loss"]:.5f} '
          f'· precisión {mp["precision"]:.4f}')
    print(f'  modelo solo                  : log-loss {mm["log_loss"]:.5f} '
          f'· precisión {mm["precision"]:.4f}')
    print('  (el prior debe ser PEOR que el modelo: es tosco pero monótono)')

    # --- barrido sobre la población objetivo --------------------------------
    for etiqueta, mascara in (('SIN MERCADO (la ficha)', sm),
                              ('CON MERCADO (control)', ~sm)):
        n = int(mascara.sum())
        if n < 200:
            print(f'\n  {etiqueta}: sólo {n} filas, se omite')
            continue
        print('\n' + '=' * 84)
        print(f'{etiqueta}  ·  n = {n}')
        print('=' * 84)
        print(f"  {'w modelo':>9} {'log-loss':>11} {'ECE':>9} {'precisión':>11}")
        print('  ' + '-' * 46)
        res = []
        for w in PESOS:
            p = w * pm[mascara] + (1 - w) * pe[mascara]
            m = metricas(p, y[mascara])
            res.append({'w': w, **m})
            print(f"  {w:9.2f} {m['log_loss']:11.5f} {m['ece']:9.4f} "
                  f"{m['precision']:11.4f}")
        base = res[0]
        mejor = min(res, key=lambda r: r['log_loss'])
        print(f"\n  mejor log-loss: w={mejor['w']:.2f} "
              f"({mejor['log_loss']:.5f} frente a {base['log_loss']:.5f} "
              f"sin encoger, {base['log_loss'] - mejor['log_loss']:+.5f})")
        mejor_ece = min(res, key=lambda r: r['ece'])
        print(f"  mejor ECE     : w={mejor_ece['w']:.2f} "
              f"({mejor_ece['ece']:.4f} frente a {base['ece']:.4f})")
        if etiqueta.startswith('SIN'):
            objetivo = res

    # --- ¿el ROI de los picks con mercado se resiente? -----------------------
    print('\n' + '=' * 84)
    print('CONTROL DE ROI (sólo filas con cuota; la ficha no apuesta)')
    print('=' * 84)
    cu = np.fmax(
        ev[['cuota_home', 'cuota_draw', 'cuota_away']].fillna(0).values.astype(float),
        np.nan_to_num(ev[['pin_home', 'pin_draw', 'pin_away']].values.astype(float),
                      nan=0.0))
    print(f"  {'w modelo':>9} {'n':>7} {'ROI':>9} {'p5':>9}")
    print('  ' + '-' * 36)
    for w in PESOS:
        p = w * pm + (1 - w) * pe
        p = p / p.sum(axis=1, keepdims=True)
        k = p.argmax(axis=1)
        f = np.arange(len(p))
        prob, cuota = p[f, k], cu[f, k]
        sel = (prob > 0.55) & (cuota * prob - 1 > 0.03) & (cuota > 1.50)
        if sel.sum() < 60:
            print(f'  {w:9.2f} {int(sel.sum()):7d}  (muestra corta)')
            continue
        pnl = np.where(k[sel] == y[sel], cuota[sel] - 1, -1.0)
        rng = np.random.default_rng(31)
        bs = pnl[rng.integers(0, len(pnl), size=(N_BOOT, len(pnl)))].mean(axis=1)
        print(f'  {w:9.2f} {int(sel.sum()):7d} {pnl.mean():9.2%} '
              f'{np.percentile(bs, 5):9.2%}')

    json.dump({'sin_mercado': objetivo}, open('_v86_encogimiento_elo.json', 'w',
                                              encoding='utf-8'),
              indent=1, default=float)
    print('\nGuardado en _v86_encogimiento_elo.json')


if __name__ == '__main__':
    main()
