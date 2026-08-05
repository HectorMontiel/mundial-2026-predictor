#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v90 — Auditoría del ledger antes de seguir tocando el modelo (regla de oro 7).

Tres experimentos seguidos han dado lo mismo: modelo 48,96 % de precisión,
mercado 50,04 %, y nada de lo que se prueba encima mueve la aguja. Un techo
tan plano puede ser real (el 1X2 a tres vías es difícil) o puede ser un
problema de alineación de datos — y este proyecto ya se ha comido cuatro veces
la lección de creerse un número antes de auditarlo.

Comprobaciones, de la más barata a la más informativa:

  1. ¿El código de `resultado` corresponde de verdad a (0=local, 1=empate,
     2=visitante)? Si estuviera cambiado, TODO lo medido sería basura. Se
     verifica contra la tasa base conocida del fútbol: gana el local ~45 %,
     empate ~25 %, visitante ~30 %.
  2. ¿El mercado está calibrado POR CLASE? Un 50 % global puede esconder que
     el favorito local acierta mucho y el empate nunca se predice.
  3. ¿Cuánto acierta el mercado POR LIGA? Si el 50 % sale de mezclar ligas
     predecibles con ligas imposibles, el techo no es 50 % en todas partes y
     hay sitio donde ganar.
  4. ¿Cuánto acierta cuando el favorito está CLARO? Es donde vive la
     «Máxima Confianza» y es lo que el usuario mira.
"""
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding='utf-8')


def devig_potencia(cuotas):
    inv = 1.0 / cuotas
    out = np.empty_like(inv)
    for i in range(len(inv)):
        p = inv[i]
        lo, hi = 0.5, 1.5
        for _ in range(40):
            mid = (lo + hi) / 2
            if (p ** mid).sum() > 1:
                lo = mid
            else:
                hi = mid
        q = p ** ((lo + hi) / 2)
        out[i] = q / q.sum()
    return out


def main():
    df = pd.read_csv('pick_ledger_total.csv')
    df = df[~df['liga'].isin(['ATP', 'WTA', 'mlb', 'nba'])]
    df = df.dropna(subset=['pin_home', 'pin_draw', 'pin_away',
                           'p_home', 'p_draw', 'p_away', 'resultado'])
    for c in ('pin_home', 'pin_draw', 'pin_away'):
        df = df[df[c] > 1.0]
    y = df['resultado'].to_numpy(int)
    mk = devig_potencia(df[['pin_home', 'pin_draw', 'pin_away']].to_numpy(float))
    pm = df[['p_home', 'p_draw', 'p_away']].to_numpy(float)
    pm = pm / pm.sum(axis=1, keepdims=True)

    # --- 1. ¿el código de resultado es el que creemos? ---------------------
    print('=== 1. ALINEACIÓN del código de resultado ===')
    tasa = np.bincount(y, minlength=3) / len(y)
    print(f'  observado   local {tasa[0]:.3f} · empate {tasa[1]:.3f} · visitante {tasa[2]:.3f}')
    print(f'  mercado dice local {mk[:,0].mean():.3f} · empate {mk[:,1].mean():.3f} · '
          f'visitante {mk[:,2].mean():.3f}')
    print(f'  modelo dice  local {pm[:,0].mean():.3f} · empate {pm[:,1].mean():.3f} · '
          f'visitante {pm[:,2].mean():.3f}')
    ok = abs(tasa[0] - mk[:, 0].mean()) < 0.03 and tasa[0] > tasa[2] > tasa[1]
    print(f'  → {"COHERENTE" if ok else "⚠️ SOSPECHOSO"}: el mercado y la realidad '
          f'coinciden en la tasa base y el orden local>visitante>empate.\n')

    # --- 2. calibración por CLASE ------------------------------------------
    print('=== 2. Calibración del MERCADO por clase (dice vs pasa) ===')
    for k, nom in enumerate(('local', 'empate', 'visitante')):
        dice, pasa = mk[:, k].mean(), (y == k).mean()
        print(f'  {nom:10s} dice {dice*100:5.2f} % · pasa {pasa*100:5.2f} % · '
              f'sesgo {(dice-pasa)*100:+5.2f} pp')
    print()
    print('=== 2b. Calibración del MODELO por clase ===')
    for k, nom in enumerate(('local', 'empate', 'visitante')):
        dice, pasa = pm[:, k].mean(), (y == k).mean()
        print(f'  {nom:10s} dice {dice*100:5.2f} % · pasa {pasa*100:5.2f} % · '
              f'sesgo {(dice-pasa)*100:+5.2f} pp')

    pred_mk, pred_pm = mk.argmax(axis=1), pm.argmax(axis=1)
    print(f'\n  el mercado elige EMPATE en {(pred_mk==1).mean()*100:.2f} % de los partidos')
    print(f'  el modelo  elige EMPATE en {(pred_pm==1).mean()*100:.2f} % de los partidos')
    print(f'  (el empate ocurre en {(y==1).mean()*100:.2f} %)')

    # --- 3. precisión por liga ---------------------------------------------
    print('\n=== 3. Precisión del MERCADO por liga (¿el techo es igual en todas?) ===')
    df = df.assign(_acc_mk=(pred_mk == y), _acc_pm=(pred_pm == y))
    g = df.groupby('liga').agg(n=('resultado', 'size'), mk=('_acc_mk', 'mean'),
                               pm=('_acc_pm', 'mean'))
    g = g[g['n'] >= 300].sort_values('mk', ascending=False)
    print(f'{"liga":24s} {"n":>6s} {"mercado":>9s} {"modelo":>8s} {"modelo−mercado":>15s}')
    print('-' * 66)
    for liga, r in g.iterrows():
        d = (r['pm'] - r['mk']) * 100
        marca = ' ←' if d > 1.0 else ''
        print(f'{liga:24s} {r["n"]:6.0f} {r["mk"]*100:8.2f} % {r["pm"]*100:7.2f} % '
              f'{d:+14.2f} pp{marca}')
    mejores = g[(g['pm'] - g['mk']) > 0.01]
    print(f'\n  ligas donde el MODELO bate al mercado por >1 pp: {len(mejores)} de {len(g)}')
    if len(mejores):
        print('   ', ', '.join(mejores.index))

    # --- 4. precisión cuando el favorito está claro ------------------------
    print('\n=== 4. Precisión según lo CLARO que esté el favorito (mercado) ===')
    conf = mk.max(axis=1)
    print(f'{"banda":16s} {"n":>6s} {"dice":>8s} {"acierta":>9s} {"sesgo":>8s}')
    print('-' * 52)
    for lo, hi in ((0.33, 0.40), (0.40, 0.50), (0.50, 0.60), (0.60, 0.70),
                   (0.70, 0.80), (0.80, 1.01)):
        m = (conf >= lo) & (conf < hi)
        if m.sum() < 30:
            continue
        acc = (pred_mk[m] == y[m]).mean()
        print(f'{lo:.2f}–{hi:.2f}      {m.sum():6d} {conf[m].mean()*100:7.2f} % '
              f'{acc*100:8.2f} % {(conf[m].mean()-acc)*100:+7.2f} pp')


if __name__ == '__main__':
    main()
