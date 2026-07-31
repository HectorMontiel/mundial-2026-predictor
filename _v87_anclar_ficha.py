#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v87 — ¿Debe la FICHA anclarse al mercado, como ya hacen los picks?

El hallazgo que lo motiva
-------------------------
Puebla vs Chivas, 2026-08-01. La ficha muestra Puebla 50,0 %. Pinnacle, con el
margen quitado, dice:

    Puebla 19,6 %   ·   empate 22,2 %   ·   Chivas 58,2 %

Treinta puntos de diferencia en el lado local, contra la casa más eficiente del
mercado. Y el ELO (1349 vs 1597) coincide con Pinnacle, no con el modelo.

Lo importante: **esas cuotas están en la app**. `cuotas_multi.cuotas_partido`
devuelve Pinnacle, Bovada y Playdoit para ese partido ahora mismo. La ficha no
las usa porque `ClubEngine._cuotas_partido` sólo lee `odds_actuales.json` (que
hoy tiene 4 partidos y no incluye éste) y porque, aunque las encontrara, sólo
alimentan el MESM y el `blend_mercado` — y el blend está configurado en DOS
ligas (laliga y ligue_1).

O sea: los picks se anclan al mercado desde la v75 y la ficha no. Es la misma
incoherencia que la v80 encontró al revés (los candidatos salían calibrados y
los picks de élite no).

Qué se mide aquí
----------------
Sobre las filas del ledger que SÍ tienen cuota (n≈36.006), se comparan como
probabilidad MOSTRADA:

    (a) el modelo crudo                        — lo que enseña la ficha hoy
    (b) el modelo encogido hacia el mercado    — con el w por liga ya validado
                                                 de `calibracion_mercado`
    (c) el mercado devigado a secas
    (d) el modelo encogido hacia el prior de ELO (v86)

Métrica: ECE y log-loss, que es lo que importa cuando se MUESTRA un número.
Walk-forward: se usa la partición por pliegues del ledger.
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


def main():
    import calibracion_mercado as cm
    import cuotas_multi as cmu
    from sklearn.linear_model import LogisticRegression

    led = pd.read_csv('pick_ledger_total.csv')
    elo = pd.read_csv('elo_por_partido.csv')
    d = (led[led['deporte'] == 'Fútbol']
         .merge(elo, on=['liga', 'match_id'], how='inner')
         .sort_values(['pliegue', 'fecha']).reset_index(drop=True))

    # prior de ELO sin fuga (para la comparación con v86)
    filas = []
    for k in sorted(d['pliegue'].unique())[1:]:
        tr, te = d[d['pliegue'] < k], d[d['pliegue'] == k]
        if len(tr) < 500 or len(te) < 100:
            continue
        m = LogisticRegression(max_iter=1000)
        m.fit(tr['diff_elo'].values.reshape(-1, 1),
              tr['resultado'].values.astype(int))
        pp = m.predict_proba(te['diff_elo'].values.reshape(-1, 1))
        pe = np.zeros((len(te), 3))
        for i, c in enumerate(m.classes_):
            pe[:, int(c)] = pp[:, i]
        t = te.copy()
        t[['pe_home', 'pe_draw', 'pe_away']] = pe
        filas.append(t)
    ev = pd.concat(filas, ignore_index=True)

    # sólo filas con cuota: es la población donde la ficha PODRÍA anclarse
    # (se prefiere Pinnacle si está, que es el ancla sharp)
    cu = ev[['cuota_home', 'cuota_draw', 'cuota_away']].values.astype(float)
    pin = ev[['pin_home', 'pin_draw', 'pin_away']].values.astype(float)
    usa_pin = np.isfinite(pin).all(axis=1) & (pin > 1).all(axis=1)
    mercado = np.where(usa_pin[:, None], pin, cu)
    ok = np.isfinite(mercado).all(axis=1) & (mercado > 1).all(axis=1)

    ev = ev[ok].reset_index(drop=True)
    mercado = mercado[ok]
    usa_pin = usa_pin[ok]
    print('=' * 86)
    print('v87 · ¿DEBE LA FICHA ANCLARSE AL MERCADO?')
    print('=' * 86)
    print(f'  filas del ledger con cuota utilizable: {len(ev)}')
    print(f'    de ellas con Pinnacle (ancla sharp): {int(usa_pin.sum())} '
          f'({usa_pin.mean():.1%})')

    # devig del mercado, con el mismo método que producción
    mk = np.zeros((len(ev), 3))
    for i in range(len(ev)):
        j = cmu.devig({'home': mercado[i, 0], 'draw': mercado[i, 1],
                       'away': mercado[i, 2]}, metodo='potencia')
        mk[i] = [j.get('home', 0), j.get('draw', 0), j.get('away', 0)]

    pm = ev[['p_home', 'p_draw', 'p_away']].values.astype(float)
    pe = ev[['pe_home', 'pe_draw', 'pe_away']].values.astype(float)
    y = ev['resultado'].values.astype(int)

    # w por liga, el ya validado de calibracion_mercado
    w_mkt = ev['liga'].map(lambda k: cm.peso_modelo(k)).values[:, None]
    print(f'  w medio hacia el mercado (calibracion_mercado): '
          f'{float(w_mkt.mean()):.3f}')
    print(f'    (w bajo = MÁS peso al mercado)')

    politicas = {
        '(a) modelo crudo (la ficha hoy)': pm,
        '(b) modelo encogido al MERCADO': w_mkt * pm + (1 - w_mkt) * mk,
        '(c) sólo el mercado devigado': mk,
        '(d) modelo encogido al ELO (v86)': 0.90 * pm + 0.10 * pe,
        '(e) mercado y luego ELO': None,   # se rellena abajo
    }
    # (e) no aplica aquí: si hay mercado, no se usa el ELO. Se deja fuera.
    politicas.pop('(e) mercado y luego ELO')

    print('\n' + '-' * 86)
    print('SOBRE TODAS LAS FILAS CON CUOTA')
    print('-' * 86)
    print(f'  {"política":<38} {"ECE":>9} {"log-loss":>11} {"precisión":>10}')
    res = {}
    for nom, p in politicas.items():
        r = met(p, y)
        res[nom] = r
        print(f'  {nom:<38} {r["ece"]:9.4f} {r["ll"]:11.5f} {r["acc"]:10.4f}')

    # partido tipo Puebla: donde el modelo se aleja MUCHO del mercado
    f = np.arange(len(pm))
    fav_m = pm.argmax(axis=1)
    brecha_mkt = pm[f, fav_m] - mk[f, fav_m]
    print('\n' + '-' * 86)
    print('SÓLO DONDE EL MODELO SE ALEJA MUCHO DEL MERCADO (el caso Puebla)')
    print('-' * 86)
    for umbral in (0.15, 0.20, 0.25, 0.30):
        m = brecha_mkt > umbral
        if m.sum() < 100:
            continue
        print(f'\n  brecha > {umbral:.2f}  ->  n = {int(m.sum())} '
              f'({m.mean():.1%} de los partidos)')
        print(f'    {"política":<38} {"ECE":>9} {"log-loss":>11} '
              f'{"precisión":>10}')
        for nom, p in politicas.items():
            r = met(p[m], y[m])
            print(f'    {nom:<38} {r["ece"]:9.4f} {r["ll"]:11.5f} '
                  f'{r["acc"]:10.4f}')

    # ¿y en Liga MX en particular?
    print('\n' + '-' * 86)
    print('LIGA MX')
    print('-' * 86)
    m = (ev['liga'] == 'liga_mx').values
    print(f'  n = {int(m.sum())}  ·  w hacia el mercado = '
          f'{cm.peso_modelo("liga_mx"):.2f}')
    print(f'  {"política":<38} {"ECE":>9} {"log-loss":>11} {"precisión":>10}')
    for nom, p in politicas.items():
        r = met(p[m], y[m])
        print(f'  {nom:<38} {r["ece"]:9.4f} {r["ll"]:11.5f} {r["acc"]:10.4f}')

    base = res['(a) modelo crudo (la ficha hoy)']
    anc = res['(b) modelo encogido al MERCADO']
    gana = anc['ece'] < base['ece'] and anc['ll'] < base['ll']
    print('\n' + '=' * 86)
    print(f'VEREDICTO: anclar la ficha al mercado '
          f'{"MEJORA" if gana else "NO mejora"} '
          f'(ECE {base["ece"]:.4f} -> {anc["ece"]:.4f}, '
          f'log-loss {base["ll"]:.5f} -> {anc["ll"]:.5f})')

    json.dump({'n': len(ev), 'resultados': res, 'gana': bool(gana)},
              open('_v87_anclar_ficha.json', 'w', encoding='utf-8'),
              indent=1, ensure_ascii=False, default=float)


if __name__ == '__main__':
    main()
