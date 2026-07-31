#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v87 — Cuando el modelo y el ELO se contradicen, ¿quién acierta?

Por qué es LA pregunta
----------------------
El caso Puebla-Chivas es exactamente eso: el ELO dice Chivas (−248 puntos) y el
modelo dice Puebla. Todo lo que se ha hecho hasta ahora —encoger hacia el ELO
con un peso fijo— trata igual a un partido donde los dos coinciden que a uno
donde se pelean. Y son situaciones distintas.

Antes de seguir ajustando pesos hay que contestar esto con datos:

  · Si cuando discrepan acierta el MODELO, no hay nada que arreglar y el
    «favorito raro» es una virtud, no un fallo.
  · Si acierta el ELO, entonces la corrección tiene que ser CONDICIONAL al
    tamaño del desacuerdo, no un `w` global ni uno por liga (que ya se midió y
    se rechazó: barajar qué w toca a cada liga da un ECE igual o mejor el 80 %
    de las veces).

Se mide sobre las 38.409 predicciones fuera de muestra del ledger, partiendo
por cuánto discrepan modelo y prior de ELO.
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


def cargar():
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
    return pd.concat(filas, ignore_index=True)


def main():
    ev = cargar()
    pm = ev[['p_home', 'p_draw', 'p_away']].values.astype(float)
    pe = ev[['pe_home', 'pe_draw', 'pe_away']].values.astype(float)
    y = ev['resultado'].values.astype(int)

    fav_m = pm.argmax(axis=1)
    fav_e = pe.argmax(axis=1)
    discrepan = fav_m != fav_e
    # tamaño del desacuerdo: cuánto separa el modelo a su favorito frente a lo
    # que le da el prior de ELO a ese mismo lado
    f = np.arange(len(pm))
    brecha = pm[f, fav_m] - pe[f, fav_m]

    print('=' * 86)
    print('v87 · CUANDO EL MODELO Y EL ELO SE CONTRADICEN, ¿QUIÉN ACIERTA?')
    print('=' * 86)
    print(f'  predicciones fuera de muestra: {len(ev)}')
    print(f'  eligen favorito DISTINTO     : {int(discrepan.sum())} '
          f'({discrepan.mean():.1%})')

    print('\n--- en los partidos donde eligen favorito distinto ---')
    sub = discrepan
    ac_m = (fav_m[sub] == y[sub]).mean()
    ac_e = (fav_e[sub] == y[sub]).mean()
    n = int(sub.sum())
    se = np.sqrt(ac_m * (1 - ac_m) / n + ac_e * (1 - ac_e) / n)
    z = (ac_m - ac_e) / se if se > 0 else 0
    print(f'  acierta el MODELO : {ac_m:.2%}')
    print(f'  acierta el ELO    : {ac_e:.2%}')
    print(f'  diferencia        : {ac_m - ac_e:+.2%}  (z = {z:+.2f}, n={n})')
    if abs(z) < 2:
        print('  -> EMPATE ESTADÍSTICO: ninguno de los dos manda cuando discrepan')
    elif z > 0:
        print('  -> gana el MODELO: su "favorito raro" está justificado')
    else:
        print('  -> gana el ELO: el modelo se equivoca justo cuando más se aleja')

    # ¿y por tamaño del desacuerdo?
    print('\n--- por tamaño del desacuerdo (brecha = P_modelo − P_elo '
          'sobre el favorito del modelo) ---')
    print(f'  {"tramo de brecha":>20} {"n":>7} {"acierta modelo":>15} '
          f'{"acierta ELO":>13} {"dif":>8} {"log-loss mod":>13} '
          f'{"log-loss ELO":>13}')
    bordes = [-1, 0.0, 0.05, 0.10, 0.15, 0.20, 1.0]
    filas = []
    for lo, hi in zip(bordes, bordes[1:]):
        m = (brecha > lo) & (brecha <= hi)
        if m.sum() < 100:
            continue
        pmc = np.clip(pm[m], 1e-9, 1)
        pec = np.clip(pe[m], 1e-9, 1)
        ll_m = float(-np.log(pmc[np.arange(m.sum()), y[m]]).mean())
        ll_e = float(-np.log(pec[np.arange(m.sum()), y[m]]).mean())
        a_m = float((fav_m[m] == y[m]).mean())
        a_e = float((fav_e[m] == y[m]).mean())
        filas.append({'lo': lo, 'hi': hi, 'n': int(m.sum()),
                      'acierto_modelo': a_m, 'acierto_elo': a_e,
                      'll_modelo': ll_m, 'll_elo': ll_e})
        print(f'  {f"{lo:+.2f} a {hi:+.2f}":>20} {int(m.sum()):7d} '
              f'{a_m:15.2%} {a_e:13.2%} {a_m - a_e:+8.2%} '
              f'{ll_m:13.4f} {ll_e:13.4f}')

    print('\n  Lectura: si al crecer la brecha el modelo pierde terreno frente')
    print('  al ELO, entonces la corrección debe depender de la brecha.')

    # ¿existe un w que dependa de la brecha y mejore?
    print('\n' + '=' * 86)
    print('¿SIRVE UN w QUE DEPENDA DE LA BRECHA?')
    print('=' * 86)
    elec = ev['pliegue'].isin([1, 2]).values
    vali = ev['pliegue'].isin([3, 4]).values

    def ece(p, yy, bins=10):
        conf, pred = p.max(axis=1), p.argmax(axis=1)
        ac = (pred == yy).astype(float)
        b = np.linspace(0, 1, bins + 1)
        e = 0.0
        for i in range(bins):
            mm = (conf > b[i]) & (conf <= b[i + 1])
            if mm.sum():
                e += mm.mean() * abs(ac[mm].mean() - conf[mm].mean())
        return float(e)

    def met(mask, w):
        w = np.asarray(w, float).reshape(-1, 1)
        p = w * pm[mask] + (1 - w) * pe[mask]
        p = np.clip(p, 1e-9, 1)
        p = p / p.sum(axis=1, keepdims=True)
        return {'ll': float(-np.log(p[np.arange(mask.sum()), y[mask]]).mean()),
                'ece': ece(p, y[mask]),
                'acc': float((p.argmax(axis=1) == y[mask]).mean())}

    # política: w = w0 cuando la brecha es pequeña, w1 cuando es grande
    mejor, mejor_e = None, 1e9
    for umbral in (0.05, 0.10, 0.15, 0.20):
        grande = brecha > umbral
        for w0 in (1.00, 0.95, 0.90):
            for w1 in (0.90, 0.80, 0.70, 0.60, 0.50, 0.40):
                w = np.where(grande, w1, w0)
                a = met(elec, w[elec])
                if a['ece'] < mejor_e:
                    mejor_e, mejor = a['ece'], (umbral, w0, w1)
    umbral, w0, w1 = mejor
    grande = brecha > umbral
    v_cond = met(vali, np.where(grande, w1, w0)[vali])
    v_fijo90 = met(vali, np.full(vali.sum(), 0.90))
    v_fijo95 = met(vali, np.full(vali.sum(), 0.95))
    v_base = met(vali, np.full(vali.sum(), 1.0))

    print(f'  elegido en pliegues 1-2: si brecha > {umbral:.2f} usar '
          f'w={w1:.2f}, si no w={w0:.2f}')
    print(f'    (afecta al {grande[vali].mean():.1%} de los partidos de '
          f'validación)')
    print(f'\n  {"política":<32} {"ECE":>9} {"log-loss":>11} {"precisión":>10}')
    for nom, r in (('sin encoger', v_base),
                   ('w fijo 0,90 (v86)', v_fijo90),
                   ('w fijo 0,95', v_fijo95),
                   (f'w condicional a la brecha', v_cond)):
        print(f'  {nom:<32} {r["ece"]:9.4f} {r["ll"]:11.5f} {r["acc"]:10.4f}')

    gana = (v_cond['ece'] < v_fijo90['ece'] and v_cond['ll'] <= v_fijo90['ll'])
    print(f'\nVEREDICTO: {"el w condicional MEJORA sobre el fijo" if gana else "el w condicional NO mejora sobre el fijo"}')

    json.dump({'discrepan': int(discrepan.sum()),
               'acierto_modelo_discrepancia': float(ac_m),
               'acierto_elo_discrepancia': float(ac_e), 'z': float(z),
               'tramos': filas,
               'condicional': {'umbral': umbral, 'w0': w0, 'w1': w1},
               'validacion': {'base': v_base, 'fijo090': v_fijo90,
                              'fijo095': v_fijo95, 'condicional': v_cond},
               'gana_condicional': bool(gana)},
              open('_v87_quien_acierta.json', 'w', encoding='utf-8'),
              indent=1, ensure_ascii=False, default=float)


if __name__ == '__main__':
    main()
