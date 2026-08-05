#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v90 — El modelo no predice mejor que el mercado. ¿Sirve al menos de FILTRO?

De dónde sale la idea
---------------------
Todo lo medido en la v90 apunta a lo mismo:

  · el modelo pierde contra el mercado en 33 de 34 ligas;
  · mezclarlos con peso fijo, con peso por liga, en logit o con un stacking
    aprendido no mejora nada fuera de muestra;
  · corregir el sesgo favorito-perdedor del mercado tampoco (b=1,0158).

Y a la vez, el canal que SÍ tiene edge validado no usa el modelo para nada:
apostar donde la mejor cuota del mercado bate al precio justo de Pinnacle da
ROI +8,57 % con p5 +0,82 % en los pliegues 3-4.

Queda una pregunta sin responder: predecir mejor y DESCARTAR mejor no son la
misma tarea. El modelo puede ser peor en media y aun así saber reconocer las
apuestas de line shopping que son trampa — precios descolgados porque el
mercado sabe algo (una baja, una rotación) que Pinnacle ya incorporó y la casa
blanda todavía no.

Qué se prueba
-------------
Sobre las apuestas que el canal de line shopping YA elegiría, se aplican
filtros basados en el modelo y se mide si el ROI sube fuera de muestra:

  F0  sin filtro                          (lo desplegado hoy)
  F1  el modelo no contradice el lado      (p_modelo ≥ p_mercado)
  F2  el argmax del modelo ES ese lado
  F3  el modelo no lo desprecia            (p_modelo ≥ p_mercado − 5 pp)
  F4  el modelo lo VE mejor que el mercado (p_modelo ≥ p_mercado + 3 pp)

El umbral de F3/F4 se ELIGE en los pliegues 0-2 barriendo el margen, y el
filtro ganador se JUZGA en los 3-4. Un filtro que sólo gana en los pliegues
donde se eligió es ruido, y este proyecto ya se ha comido esa lección.
"""
import json
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding='utf-8')
MARGEN_EV = 0.01      # el validado en la v80 para este canal
PROB_MIN = 0.30


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


def boot_p5(g, n_boot=4000, semilla=17):
    rng = np.random.default_rng(semilla)
    return float(np.percentile(
        [g[rng.integers(0, len(g), len(g))].mean() for _ in range(n_boot)], 5) * 100)


def candidatos(mk, pm, cu, y):
    """Las apuestas que el canal de line shopping elegiría, con su contexto."""
    idx = np.arange(len(mk))
    ev = np.where(np.isfinite(cu) & (cu > 1), cu * mk - 1.0, -9.9)
    k = ev.argmax(axis=1)
    ok = ((ev[idx, k] > MARGEN_EV) & (mk[idx, k] >= PROB_MIN)
          & np.isfinite(cu[idx, k]) & (cu[idx, k] > 1))
    return {'lado': k[ok], 'precio': cu[idx, k][ok], 'p_mkt': mk[idx, k][ok],
            'p_mod': pm[idx, k][ok], 'argmax_mod': pm.argmax(axis=1)[ok],
            'y': y[ok], 'n': int(ok.sum()), 'mask': ok}


def evalua(c, sel, etiqueta):
    if sel.sum() < 40:
        return {'filtro': etiqueta, 'n': int(sel.sum()), 'roi': None, 'p5': None}
    g = np.where(c['lado'][sel] == c['y'][sel], c['precio'][sel] - 1.0, -1.0)
    return {'filtro': etiqueta, 'n': int(sel.sum()),
            'roi': float(g.mean() * 100), 'p5': boot_p5(g),
            'acierto': float((c['lado'][sel] == c['y'][sel]).mean() * 100)}


def filtros(c):
    d = c['p_mod'] - c['p_mkt']
    return {
        'F0 sin filtro (hoy)': np.ones(c['n'], bool),
        'F1 modelo ≥ mercado': d >= 0,
        'F2 argmax del modelo': c['argmax_mod'] == c['lado'],
        'F3 modelo ≥ mkt−5pp': d >= -0.05,
        'F4 modelo ≥ mkt+3pp': d >= 0.03,
    }


def main():
    df = pd.read_csv('pick_ledger_total.csv')
    df = df[~df['liga'].isin(['ATP', 'WTA', 'mlb', 'nba'])]
    df = df.dropna(subset=['pin_home', 'pin_draw', 'pin_away',
                           'p_home', 'p_draw', 'p_away', 'resultado'])
    for col in ('pin_home', 'pin_draw', 'pin_away'):
        df = df[df[col] > 1.0]
    mk = devig_potencia(df[['pin_home', 'pin_draw', 'pin_away']].to_numpy(float))
    pm = df[['p_home', 'p_draw', 'p_away']].to_numpy(float)
    pm = pm / pm.sum(axis=1, keepdims=True)
    y = df['resultado'].to_numpy(int)
    cu = df[['cuota_home', 'cuota_draw', 'cuota_away']].to_numpy(float)
    pl = df['pliegue'].to_numpy(int)
    e, j = pl <= 2, pl >= 3

    ce = candidatos(mk[e], pm[e], cu[e], y[e])
    cj = candidatos(mk[j], pm[j], cu[j], y[j])
    print(f'apuestas de line shopping · elección {ce["n"]} · juicio {cj["n"]}\n')

    print('=== PLIEGUES 0-2 (elección) ===')
    print(f'{"filtro":24s} {"n":>6s} {"ROI":>9s} {"p5":>9s} {"acierto":>9s}')
    print('-' * 62)
    res_e = {}
    for etq, sel in filtros(ce).items():
        r = evalua(ce, sel, etq)
        res_e[etq] = r
        print(f'{etq:24s} {r["n"]:6d} '
              f'{"—" if r["roi"] is None else f"{r['roi']:+8.2f}%"} '
              f'{"—" if r["p5"] is None else f"{r['p5']:+8.2f}%"} '
              f'{"" if r.get("acierto") is None else f"{r['acierto']:8.2f}%"}')

    print('\n=== PLIEGUES 3-4 (juicio, no participaron en la elección) ===')
    print(f'{"filtro":24s} {"n":>6s} {"ROI":>9s} {"p5":>9s} {"acierto":>9s}')
    print('-' * 62)
    res_j = {}
    for etq, sel in filtros(cj).items():
        r = evalua(cj, sel, etq)
        res_j[etq] = r
        print(f'{etq:24s} {r["n"]:6d} '
              f'{"—" if r["roi"] is None else f"{r['roi']:+8.2f}%"} '
              f'{"—" if r["p5"] is None else f"{r['p5']:+8.2f}%"} '
              f'{"" if r.get("acierto") is None else f"{r['acierto']:8.2f}%"}')

    # --- barrido del umbral de discrepancia, con las dos mitades a la vista --
    print('\n=== Barrido del umbral «p_modelo − p_mercado ≥ u» ===')
    print(f'{"u":>7s} {"n elige":>8s} {"ROI elige":>10s} {"p5 elige":>9s} '
          f'{"n juzga":>8s} {"ROI juzga":>10s} {"p5 juzga":>9s} {"robusto":>8s}')
    print('-' * 76)
    robustos = []
    for u in np.arange(-0.15, 0.121, 0.02):
        re_ = evalua(ce, (ce['p_mod'] - ce['p_mkt']) >= u, f'u={u:+.2f}')
        rj_ = evalua(cj, (cj['p_mod'] - cj['p_mkt']) >= u, f'u={u:+.2f}')
        if re_['roi'] is None or rj_['roi'] is None:
            continue
        rob = re_['p5'] > 0 and rj_['p5'] > 0
        if rob:
            robustos.append(u)
        print(f'{u:+7.2f} {re_["n"]:8d} {re_["roi"]:+9.2f}% {re_["p5"]:+8.2f}% '
              f'{rj_["n"]:8d} {rj_["roi"]:+9.2f}% {rj_["p5"]:+8.2f}% '
              f'{"SÍ" if rob else "no":>8s}')

    base_e, base_j = res_e['F0 sin filtro (hoy)'], res_j['F0 sin filtro (hoy)']
    print(f'\nreferencia sin filtro: elección p5 {base_e["p5"]:+.2f} % · '
          f'juicio p5 {base_j["p5"]:+.2f} %')
    print(f'umbrales con p5>0 en LAS DOS mitades: {len(robustos)} '
          f'({[round(u,2) for u in robustos]})')

    with open('_v90_modelo_como_filtro.json', 'w', encoding='utf-8') as f:
        json.dump({'eleccion': res_e, 'juicio': res_j,
                   'umbrales_robustos': [float(u) for u in robustos]},
                  f, ensure_ascii=False, indent=1, default=float)
    print('\n→ _v90_modelo_como_filtro.json')


if __name__ == '__main__':
    main()
