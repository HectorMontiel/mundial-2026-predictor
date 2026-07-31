#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v87 — El peso del encogimiento hacia el ELO, ahora SÍ por liga.

Qué se corrige de v86
---------------------
En v86 el `w` por liga se midió sólo sobre las fichas SIN ancla de mercado,
porque ésa es la población donde la corrección se aplica en producción. Pero
había **20 filas** en ligas planas de un total de 9.870: la comparación era
ruido y se rechazó, correctamente.

La restricción era innecesaria. El ledger guarda `p_home/p_draw/p_away` tal cual
salen del modelo, **antes** de cualquier encogimiento hacia el mercado (se ve en
`build_pick_ledger`: `proba = modelo.predict_proba(X_te)`, y en
`calibracion_confianza.calcular`, que aplica `w·pm + (1−w)·mk` DESPUÉS). O sea
que para estimar cuánto hay que encoger la salida CRUDA basta con tener el
resultado real; que el partido tuviera cuota o no es irrelevante para el
parámetro.

Con eso, Liga MX pasa de ~0 filas útiles a **1.311**, y las 25 ligas planas van
de 429 a 1.843 cada una.

Tres políticas, la misma validación
-----------------------------------
  (a) w global = 0,90            — lo que hay hoy (1 parámetro)
  (b) w por tramo de respuesta   — 2 parámetros, según la dependencia parcial
  (c) w por liga                 — 56 parámetros

Se eligen los parámetros en los pliegues 1-2 y se validan en los 3-4. Se adopta
la que mejor GENERALICE, no la que mejor ajuste: con 56 parámetros libres es
fácil ganar dentro de la muestra de elección y perder fuera.

Guardia contra comparaciones múltiples: se mide cuántas ligas «mejorarían» por
azar, barajando el emparejamiento entre el w elegido y la liga.
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

REJILLA = [1.00, 0.95, 0.90, 0.85, 0.80, 0.75, 0.70, 0.60, 0.50]
MIN_ELECCION = 150      # filas mínimas en pliegues 1-2 para fijar un w propio
MIN_VALIDACION = 100
CORTE_RESPONDE = 0.05


def ece(p, y, bins=10):
    conf, pred = p.max(axis=1), p.argmax(axis=1)
    ac = (pred == y).astype(float)
    b = np.linspace(0, 1, bins + 1)
    e = 0.0
    for i in range(bins):
        m = (conf > b[i]) & (conf <= b[i + 1])
        if m.sum():
            e += m.mean() * abs(ac[m].mean() - conf[m].mean())
    return float(e)


def met(p, y):
    p = np.clip(p, 1e-9, 1)
    p = p / p.sum(axis=1, keepdims=True)
    return {'ll': float(-np.log(p[np.arange(len(y)), y]).mean()),
            'ece': ece(p, y),
            'acc': float((p.argmax(axis=1) == y).mean()),
            'n': int(len(y))}


def cargar():
    from sklearn.linear_model import LogisticRegression

    led = pd.read_csv('pick_ledger_total.csv')
    elo = pd.read_csv('elo_por_partido.csv')
    d = (led[led['deporte'] == 'Fútbol']
         .merge(elo, on=['liga', 'match_id'], how='inner')
         .sort_values(['pliegue', 'fecha']).reset_index(drop=True))

    # el prior de ELO se ajusta con pliegues ANTERIORES (sin fuga)
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
    return pd.concat(filas, ignore_index=True)


def bloque(sub):
    return (sub[['p_home', 'p_draw', 'p_away']].values.astype(float),
            sub[['pe_home', 'pe_draw', 'pe_away']].values.astype(float),
            sub['resultado'].values.astype(int))


def evaluar(sub, w):
    pm, pe, y = bloque(sub)
    w = np.asarray(w, dtype=float).reshape(-1, 1)
    return met(w * pm + (1 - w) * pe, y)


def main():
    ev = cargar()
    dep = json.load(open('_v86_dependencia_elo.json', encoding='utf-8'))
    salto = {r['liga']: r['salto'] for r in dep if not r.get('error')}
    ev['salto'] = ev['liga'].map(salto)
    ev['plana'] = ev['salto'] <= CORTE_RESPONDE

    elec = ev[ev['pliegue'].isin([1, 2])]
    vali = ev[ev['pliegue'].isin([3, 4])]

    print('=' * 88)
    print('v87 · ¿UN w POR LIGA? TRES POLÍTICAS, LA MISMA VALIDACIÓN')
    print('=' * 88)
    print(f'  filas evaluables    : {len(ev)}   (v86 usaba sólo '
          f'{int(ev["cuota_home"].isna().sum())}, las que no tienen mercado)')
    print(f'  elección (pliegues 1-2): {len(elec)}')
    print(f'  validación (pliegues 3-4): {len(vali)}')
    print(f'  ligas planas / totales : {ev["plana"].sum()} filas en '
          f'{ev[ev["plana"]]["liga"].nunique()} ligas planas')

    # ---------------- (a) w global -----------------------------------------
    print('\n' + '-' * 88)
    print('(a) w GLOBAL')
    print('-' * 88)
    base_v = evaluar(vali, 1.0)
    print(f"  {'w':>6} {'elección ECE':>13} {'ll':>10} | "
          f"{'VALID ECE':>10} {'ll':>10}")
    mejor_glob, mejor_ece_e = None, 1e9
    for w in REJILLA:
        a, b = evaluar(elec, w), evaluar(vali, w)
        marca = ''
        if w < 1.0 and a['ece'] < mejor_ece_e:
            mejor_ece_e, mejor_glob = a['ece'], w
            marca = '  <- mejor en elección'
        print(f"  {w:6.2f} {a['ece']:13.4f} {a['ll']:10.5f} | "
              f"{b['ece']:10.4f} {b['ll']:10.5f}{marca}")
    glob_v = evaluar(vali, mejor_glob)
    print(f'\n  w global elegido: {mejor_glob:.2f}')
    print(f'  VALIDACIÓN: ECE {glob_v["ece"]:.4f} · ll {glob_v["ll"]:.5f} '
          f'(sin encoger {base_v["ece"]:.4f} / {base_v["ll"]:.5f})')

    # ---------------- (b) w por tramo --------------------------------------
    print('\n' + '-' * 88)
    print('(b) w POR TRAMO DE RESPUESTA AL ELO (2 parámetros)')
    print('-' * 88)
    mejor_par, mejor_ece_e = None, 1e9
    for wp in REJILLA:
        for wr in REJILLA:
            w_e = np.where(elec['plana'].values, wp, wr)
            a = evaluar(elec, w_e)
            if a['ece'] < mejor_ece_e:
                mejor_ece_e, mejor_par = a['ece'], (wp, wr)
    wp, wr = mejor_par
    tramo_v = evaluar(vali, np.where(vali['plana'].values, wp, wr))
    print(f'  elegido: w_planas={wp:.2f} · w_responden={wr:.2f}')
    print(f'  VALIDACIÓN: ECE {tramo_v["ece"]:.4f} · ll {tramo_v["ll"]:.5f}')

    # ---------------- (c) w por liga ---------------------------------------
    print('\n' + '-' * 88)
    print('(c) w POR LIGA (un parámetro por liga)')
    print('-' * 88)
    w_liga = {}
    detalle = []
    for liga, ge in elec.groupby('liga'):
        if len(ge) < MIN_ELECCION:
            continue
        mejor, mejor_e = None, 1e9
        for w in REJILLA:
            a = evaluar(ge, w)
            if a['ece'] < mejor_e:
                mejor_e, mejor = a['ece'], w
        w_liga[liga] = mejor
        gv = vali[vali['liga'] == liga]
        if len(gv) >= MIN_VALIDACION:
            v_prop = evaluar(gv, mejor)
            v_glob = evaluar(gv, mejor_glob)
            detalle.append({'liga': liga, 'w': mejor, 'n_val': len(gv),
                            'salto': salto.get(liga),
                            'ece_propio': v_prop['ece'],
                            'ece_global': v_glob['ece'],
                            'll_propio': v_prop['ll'],
                            'll_global': v_glob['ll']})
    print(f'  ligas con w propio: {len(w_liga)}')

    w_v = vali['liga'].map(w_liga).fillna(mejor_glob).values
    liga_v = evaluar(vali, w_v)
    print(f'  VALIDACIÓN: ECE {liga_v["ece"]:.4f} · ll {liga_v["ll"]:.5f}')

    # guardia de comparaciones múltiples: barajar qué w le toca a cada liga
    rng = np.random.default_rng(87)
    ligas = sorted(w_liga)
    nulos = []
    for _ in range(200):
        perm = dict(zip(ligas, rng.permutation([w_liga[l] for l in ligas])))
        wv = vali['liga'].map(perm).fillna(mejor_glob).values
        nulos.append(evaluar(vali, wv)['ece'])
    nulos = np.array(nulos)
    p_azar = float((nulos <= liga_v['ece']).mean())
    print(f'  guardia de azar: barajando qué w toca a cada liga, el ECE de '
          f'validación es <= al real el {p_azar:.1%} de las veces')
    print(f'    (ECE barajado: mediana {np.median(nulos):.4f}, '
          f'mínimo {nulos.min():.4f})')

    # ---------------- veredicto --------------------------------------------
    print('\n' + '=' * 88)
    print('COMPARACIÓN EN VALIDACIÓN (pliegues 3-4, no vistos al elegir)')
    print('=' * 88)
    print(f'  {"política":<34} {"params":>7} {"ECE":>9} {"log-loss":>11} '
          f'{"precisión":>10}')
    for nom, npar, r in (('sin encoger', 0, base_v),
                         (f'(a) w global = {mejor_glob:.2f}', 1, glob_v),
                         (f'(b) w por tramo {wp:.2f}/{wr:.2f}', 2, tramo_v),
                         (f'(c) w por liga ({len(w_liga)} ligas)',
                          len(w_liga), liga_v)):
        print(f'  {nom:<34} {npar:>7} {r["ece"]:9.4f} {r["ll"]:11.5f} '
              f'{r["acc"]:10.4f}')

    gana_liga = (liga_v['ece'] < glob_v['ece'] and liga_v['ll'] <= glob_v['ll']
                 and p_azar < 0.05)
    print(f'\n  ¿el w por liga bate al global en validación? '
          f'ECE {"SÍ" if liga_v["ece"] < glob_v["ece"] else "no"} · '
          f'log-loss {"SÍ" if liga_v["ll"] <= glob_v["ll"] else "no"} · '
          f'no-azar {"SÍ" if p_azar < 0.05 else "no"}')
    print(f'\nVEREDICTO: '
          f'{"ADOPTAR w por liga" if gana_liga else "MANTENER w global"}')

    # detalle por liga, ordenado por lo plano que estaba
    if detalle:
        det = pd.DataFrame(detalle).sort_values('salto')
        print('\n' + '-' * 88)
        print('DETALLE POR LIGA (validación)')
        print('-' * 88)
        print(f'  {"liga":<22} {"salto":>8} {"w":>5} {"n":>6} '
              f'{"ECE propio":>11} {"ECE global":>11} {"mejora":>9}')
        for _, r in det.iterrows():
            mej = r['ece_global'] - r['ece_propio']
            print(f'  {r["liga"]:<22} {r["salto"]:+8.4f} {r["w"]:5.2f} '
                  f'{int(r["n_val"]):6d} {r["ece_propio"]:11.4f} '
                  f'{r["ece_global"]:11.4f} {mej:+9.4f}')
        print(f'\n  ligas donde el w propio mejora: '
              f'{int((det["ece_global"] > det["ece_propio"]).sum())} de {len(det)}')
        # ¿hay relación entre lo plano que está el modelo y el w elegido?
        from scipy.stats import spearmanr
        rho, pv = spearmanr(det['salto'], det['w'])
        print(f'  Spearman(salto de ELO, w elegido) = {rho:+.3f} (p={pv:.3f})')
        print('    positivo = las ligas que MENOS responden al ELO reciben '
              'MENOS w (más encogimiento), que es el mecanismo esperado')

    json.dump({'w_global': mejor_glob, 'w_tramo': [wp, wr],
               'w_liga': w_liga, 'p_azar': p_azar,
               'validacion': {'base': base_v, 'global': glob_v,
                              'tramo': tramo_v, 'liga': liga_v},
               'adoptar_por_liga': bool(gana_liga),
               'detalle': detalle},
              open('_v87_w_por_liga.json', 'w', encoding='utf-8'),
              indent=1, ensure_ascii=False, default=float)


if __name__ == '__main__':
    main()
