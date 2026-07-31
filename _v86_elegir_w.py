#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v86 — Elegir el peso del encogimiento SIN quedarse con el máximo del barrido.

El barrido de _v86_encogimiento_elo.py mejora monótonamente hasta w=0,50, que
es el extremo de la rejilla. Quedarse ahí es exactamente el error que este
proyecto ya ha pagado tres veces: el máximo de un barrido no es una estimación,
es el ruido más favorable.

Protocolo
---------
  1. w se ELIGE con los pliegues 1-2 (los más antiguos disponibles fuera de
     muestra).
  2. w se VALIDA en los pliegues 3-4, que no participaron en la elección.
  3. Sólo se adopta si la mejora persiste en validación.

Y se comprueba el efecto sobre la propiedad que motivó todo esto: la
dependencia parcial respecto al ELO (¿responde ya el modelo a la fuerza?).
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


def ece(p, y, bins=10):
    conf, pred = p.max(axis=1), p.argmax(axis=1)
    acierto = (pred == y).astype(float)
    bordes = np.linspace(0, 1, bins + 1)
    e = 0.0
    for i in range(bins):
        m = (conf > bordes[i]) & (conf <= bordes[i + 1])
        if m.sum():
            e += m.mean() * abs(acierto[m].mean() - conf[m].mean())
    return float(e)


def met(p, y):
    p = np.clip(p, 1e-9, 1)
    p = p / p.sum(axis=1, keepdims=True)
    return {'ll': float(-np.log(p[np.arange(len(y)), y]).mean()),
            'ece': ece(p, y),
            'acc': float((p.argmax(axis=1) == y).mean())}


def main():
    from sklearn.linear_model import LogisticRegression

    led = pd.read_csv('pick_ledger_total.csv')
    elo = pd.read_csv('elo_por_partido.csv')
    d = (led[led['deporte'] == 'Fútbol']
         .merge(elo, on=['liga', 'match_id'], how='inner')
         .sort_values(['pliegue', 'fecha']).reset_index(drop=True))

    filas = []
    for k in sorted(d['pliegue'].unique())[1:]:
        tr, te = d[d['pliegue'] < k], d[d['pliegue'] == k]
        if len(tr) < 500 or len(te) < 100:
            continue
        m = LogisticRegression(max_iter=1000)
        m.fit(tr['diff_elo'].values.reshape(-1, 1),
              tr['resultado'].values.astype(int))
        p = m.predict_proba(te['diff_elo'].values.reshape(-1, 1))
        pe = np.zeros((len(te), 3))
        for i, c in enumerate(m.classes_):
            pe[:, int(c)] = p[:, i]
        t = te.copy()
        t[['pe_home', 'pe_draw', 'pe_away']] = pe
        filas.append(t)
    ev = pd.concat(filas, ignore_index=True)

    # sólo la ficha: filas SIN ancla de mercado
    ev = ev[ev['cuota_home'].isna()].reset_index(drop=True)
    print('=' * 78)
    print('v86 · ELECCIÓN DE w FUERA DE MUESTRA (sólo fichas sin mercado)')
    print('=' * 78)
    print(f'  filas sin mercado evaluables: {len(ev)}')

    eleccion = ev[ev['pliegue'].isin([1, 2])]
    validacion = ev[ev['pliegue'].isin([3, 4])]
    print(f'  ELECCIÓN  (pliegues 1-2): {len(eleccion)}')
    print(f'  VALIDACIÓN(pliegues 3-4): {len(validacion)}')

    def bloque(sub):
        return (sub[['p_home', 'p_draw', 'p_away']].values.astype(float),
                sub[['pe_home', 'pe_draw', 'pe_away']].values.astype(float),
                sub['resultado'].values.astype(int))

    pm_e, pe_e, y_e = bloque(eleccion)
    pm_v, pe_v, y_v = bloque(validacion)

    print(f"\n  {'w':>6} | {'ELECCIÓN log-loss':>18} {'ECE':>8} | "
          f"{'VALIDACIÓN log-loss':>20} {'ECE':>8} {'precisión':>10}")
    print('  ' + '-' * 74)
    res = []
    for w in PESOS:
        a = met(w * pm_e + (1 - w) * pe_e, y_e)
        b = met(w * pm_v + (1 - w) * pe_v, y_v)
        res.append({'w': w, 'eleccion': a, 'validacion': b})
        print(f"  {w:6.2f} | {a['ll']:18.5f} {a['ece']:8.4f} | "
              f"{b['ll']:20.5f} {b['ece']:8.4f} {b['acc']:10.4f}")

    base = res[0]
    print('\n' + '-' * 78)
    # criterio: el mejor ECE de la ELECCIÓN (la ficha muestra una probabilidad,
    # así que lo que importa es que ese número sea fiel), exigiendo además que
    # el log-loss no empeore.
    cands = [r for r in res
             if r['w'] < 1.0 and r['eleccion']['ll'] <= base['eleccion']['ll']]
    elegido = min(cands, key=lambda r: r['eleccion']['ece']) if cands else None

    if not elegido:
        print('VEREDICTO: ningún peso mejora en la elección. NO adoptar.')
        return

    w = elegido['w']
    print(f'w elegido en los pliegues 1-2 por mejor ECE: {w:.2f}')
    print(f'  elección : log-loss {elegido["eleccion"]["ll"]:.5f} '
          f'(base {base["eleccion"]["ll"]:.5f}) · '
          f'ECE {elegido["eleccion"]["ece"]:.4f} '
          f'(base {base["eleccion"]["ece"]:.4f})')
    print(f'  VALIDACIÓN: log-loss {elegido["validacion"]["ll"]:.5f} '
          f'(base {base["validacion"]["ll"]:.5f}) · '
          f'ECE {elegido["validacion"]["ece"]:.4f} '
          f'(base {base["validacion"]["ece"]:.4f})')

    mejora_ll = base['validacion']['ll'] - elegido['validacion']['ll']
    mejora_ece = base['validacion']['ece'] - elegido['validacion']['ece']
    mejora_acc = elegido['validacion']['acc'] - base['validacion']['acc']
    print(f'\n  mejora EN VALIDACIÓN: log-loss {mejora_ll:+.5f} · '
          f'ECE {mejora_ece:+.4f} · precisión {mejora_acc:+.4f}')

    ok = mejora_ll > 0 and mejora_ece > 0
    print(f'\nVEREDICTO: {"ADOPTAR w=%.2f" % w if ok else "NO adoptar"} — '
          f'{"la mejora persiste fuera de la muestra de elección" if ok else "no persiste"}')

    # ¿y si hubiéramos cogido el máximo del barrido?
    maxi = min(res, key=lambda r: r['eleccion']['ll'])
    print(f'\n  (para contraste: el máximo del barrido sería w={maxi["w"]:.2f}, '
          f'que en validación da log-loss {maxi["validacion"]["ll"]:.5f} '
          f'y ECE {maxi["validacion"]["ece"]:.4f})')

    json.dump({'w_elegido': w, 'ok': bool(ok), 'barrido': res},
              open('_v86_elegir_w.json', 'w', encoding='utf-8'),
              indent=1, default=float)


if __name__ == '__main__':
    main()
