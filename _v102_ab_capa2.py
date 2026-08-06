#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v102 — Extender la corrección de calibración a la Capa 2: el A/B que decide.

El problema
-----------
La corrección por banda (v84/v86) sólo se aplica a la pestaña de Máxima
Confianza. Lo que se REGISTRA —`capa1` y `capa2`— lleva la probabilidad cruda
del modelo. Medido en la v101 sobre los picks publicados:

    Capa 2 · n=108 · acierto 58,3 % · prometido 74,5 % · brecha −16,2 pp

Por qué no basta con relabelar
------------------------------
Corregir la probabilidad no es cosmético: la Capa 2 SE SELECCIONA por
probabilidad («alta confianza»), y el EV y el Kelly se calculan con ella. Bajar
un 74,5 % a un 61 % no cambia sólo lo que se enseña — cambia **qué picks entran**
y **cuánto se apuesta**. Así que el A/B no puede comparar dos etiquetas: tiene
que comparar dos SELECCIONES.

Cómo se mide
------------
Sobre `pick_ledger_total.csv` (120.077 predicciones fuera de muestra en fútbol,
tenis y MLB), se simula la Capa 2 de las dos formas:

  A · se elige el lado más probable y se filtra por la probabilidad CRUDA.
  B · lo mismo, pero filtrando por la probabilidad CORREGIDA.

La corrección se aprende SÓLO con el pasado y se aplica al futuro, avanzando por
pliegues. Se comparan tamaño de la selección, acierto real, brecha de
calibración y ROI con la cuota registrada.

Lo que se espera —y lo que hay que comprobar— es que B seleccione MENOS picks y
que los que seleccione acierten más cerca de lo que prometen. Si B acaba con la
misma brecha, la corrección no sirve para esto y se dice.
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

import aprendizaje_continuo as ac

N_PLIEGUES = 6
JUICIO_DESDE = 2
BOOT = 4000
SEMILLA = 102
UMBRALES = (0.65, 0.70, 0.75, 0.80)
SALIDA = '_v102_ab_capa2.json'


def preparar() -> pd.DataFrame:
    """El pick de máxima probabilidad de cada partido, con su cuota y acierto."""
    d = pd.read_csv('pick_ledger_total.csv')
    d = d.dropna(subset=['p_home', 'p_away', 'resultado'])
    p = d[['p_home', 'p_draw', 'p_away']].fillna(0.0).to_numpy(dtype=float)
    lado = p.argmax(axis=1)                      # 0 local, 1 empate, 2 visita
    # el ledger codifica el resultado igual: 0 local, 1 empate, 2 visitante
    # (verificado contra el marcador en la v101)
    out = pd.DataFrame({
        'fecha': d['fecha'].to_numpy(),
        'deporte': d['deporte'].to_numpy(),
        'liga': d['liga'].to_numpy(),
        'prob': p[np.arange(len(p)), lado],
        'acierto': (d['resultado'].to_numpy() == lado).astype(float),
        'cuota': np.select(
            [lado == 0, lado == 1, lado == 2],
            [d['cuota_home'].to_numpy(dtype=float),
             d['cuota_draw'].to_numpy(dtype=float),
             d['cuota_away'].to_numpy(dtype=float)], np.nan),
    })
    out['mercado'] = np.where(out['deporte'] == 'Fútbol', '1X2', 'Ganador')
    return out.sort_values('fecha', kind='stable').reset_index(drop=True)


def con_correccion(d: pd.DataFrame) -> np.ndarray:
    """Probabilidad corregida, aprendiendo sólo con el pasado (walk-forward)."""
    n = len(d)
    bordes = [int(n * (0.4 + 0.1 * i)) for i in range(N_PLIEGUES + 1)]
    salida = d['prob'].to_numpy(dtype=float).copy()
    for i in range(N_PLIEGUES):
        ini, fin = bordes[i], bordes[i + 1]
        mapa = ac.aprender(d.iloc[:ini], 'prob', 'acierto',
                           ['deporte', 'mercado'])
        sub = d.iloc[ini:fin]
        salida[ini:fin] = [
            ac.aplicar(float(r.prob), mapa,
                       {'deporte': r.deporte, 'mercado': r.mercado})
            for r in sub.itertuples(index=False)]
    return salida, bordes


def medir(d: pd.DataFrame, sel: np.ndarray, prob_mostrada: np.ndarray,
          etiqueta: str) -> dict:
    """Qué rinde una selección: acierto, brecha y ROI con la cuota real."""
    if sel.sum() == 0:
        print(f'    {etiqueta:<28} selección vacía')
        return {'n': 0}
    a = d['acierto'].to_numpy(dtype=float)[sel]
    p = prob_mostrada[sel]
    cu = d['cuota'].to_numpy(dtype=float)[sel]
    con_cuota = ~np.isnan(cu) & (cu > 1)
    roi = (float(np.mean(a[con_cuota] * (cu[con_cuota] - 1)
                         - (1 - a[con_cuota]))) * 100
           if con_cuota.sum() >= 30 else None)
    brecha = float(a.mean() - p.mean())
    print(f'    {etiqueta:<28} n={int(sel.sum()):>6} · acierto {a.mean():.4f} '
          f'· prometido {p.mean():.4f} · brecha {brecha:+.4f} · ROI '
          + (f'{roi:+.2f} %' if roi is not None else '—'))
    return {'n': int(sel.sum()), 'acierto': float(a.mean()),
            'prometido': float(p.mean()), 'brecha': brecha,
            'roi_pct': roi, 'n_con_cuota': int(con_cuota.sum())}


def preparar_goles() -> pd.DataFrame:
    """
    Los mercados que la Capa 2 ocupa DE VERDAD.

    El primer pase de este A/B midió `pick_ledger_total.csv`, que sólo tiene
    1X2 y moneyline, y salió RECHAZAR en los cuatro umbrales: ahí el modelo ya
    está calibrado (brechas de +0,001 a −0,012). Pero mirando los 108 picks de
    Capa 2 realmente publicados, el fútbol son **22 de BTTS y 29 de Goles**, y
    sólo 6 de 1X2. Se estaba midiendo el mercado equivocado.

    `pick_ledger_totales.csv` es el que tiene esos mercados, con 47.794
    predicciones fuera de muestra. Cada fila da tres picks posibles (over 1.5,
    over 2.5, BTTS) y se toma el lado que el modelo prefiere, que es como sale
    a producción.
    """
    t = pd.read_csv('pick_ledger_totales.csv')
    trozos = []
    for mercado, cp_, cy in (('Goles', 'p_over_1.5', 'over_1.5_real'),
                             ('Goles', 'p_over_2.5', 'over_2.5_real'),
                             ('BTTS', 'p_btts', 'btts_real')):
        s = t.dropna(subset=[cp_, cy])[['fecha', 'liga', cp_, cy]].copy()
        s.columns = ['fecha', 'liga', 'p', 'y']
        # el pick es el lado más probable: si p<0,5 se apuesta al contrario
        s['prob'] = np.where(s['p'] >= 0.5, s['p'], 1 - s['p'])
        s['acierto'] = np.where(s['p'] >= 0.5, s['y'], 1 - s['y'])
        s['mercado'] = mercado
        s['deporte'] = 'Fútbol'
        s['cuota'] = np.nan          # la Capa 2 es «sin precio» por definición
        trozos.append(s[['fecha', 'deporte', 'liga', 'prob', 'acierto',
                         'cuota', 'mercado']])
    d = pd.concat(trozos, ignore_index=True)
    return d.sort_values('fecha', kind='stable').reset_index(drop=True)


def bloque(d: pd.DataFrame, titulo: str, salida: dict) -> None:
    print(f'\n{"#" * 70}\n# {titulo}: {len(d)} predicciones fuera de muestra')
    p_cor, bordes = con_correccion(d)
    tarde = np.arange(len(d)) >= bordes[JUICIO_DESDE]
    p_cru = d['prob'].to_numpy(dtype=float)
    rng = np.random.default_rng(SEMILLA)
    aa = d['acierto'].to_numpy(dtype=float)
    for u in UMBRALES:
        print(f'\n=== umbral de Capa 2: prob >= {u:.2f}')
        sel_a = tarde & (p_cru >= u)
        sel_b = tarde & (p_cor >= u)
        ra = medir(d, sel_a, p_cru, 'A · probabilidad CRUDA')
        rb = medir(d, sel_b, p_cor, 'B · probabilidad CORREGIDA')
        if not (ra.get('n') and rb.get('n')):
            continue

        def _boot(sel, prob):
            idx = np.flatnonzero(sel)
            return np.array([abs(aa[s].mean() - prob[s].mean())
                             for s in (idx[rng.integers(0, len(idx), len(idx))]
                                       for _ in range(BOOT))])

        ba, bb = _boot(sel_a, p_cru), _boot(sel_b, p_cor)
        dif = ba - bb
        p5 = float(np.percentile(dif, 5))
        ver = 'ADOPTAR' if p5 > 0 else 'RECHAZAR'
        print(f'    |brecha| A {ba.mean():.4f} → B {bb.mean():.4f} · '
              f'p5 de la mejora {p5:+.4f} · {ver}')
        salida.setdefault(titulo, {})[f'{u:.2f}'] = {
            'A': ra, 'B': rb, 'brecha_abs_a': float(ba.mean()),
            'brecha_abs_b': float(bb.mean()), 'p5': p5, 'veredicto': ver}


def main():
    salida_total: dict = {}
    bloque(preparar_goles(), 'GOLES y BTTS (lo que ocupa la Capa 2)',
           salida_total)

    d = preparar()
    print(f'\n{"#" * 70}\n# 1X2 y GANADOR: {len(d)} predicciones fuera de muestra · '
          f'{d.deporte.value_counts().to_dict()}')
    p_cor, bordes = con_correccion(d)
    tarde = np.arange(len(d)) >= bordes[JUICIO_DESDE]
    p_cru = d['prob'].to_numpy(dtype=float)
    salida = salida_total
    salida['n_total_1x2'] = int(len(d))
    salida['por_umbral'] = {}

    rng = np.random.default_rng(SEMILLA)
    for u in UMBRALES:
        print(f'\n=== umbral de Capa 2: prob >= {u:.2f}')
        sel_a = tarde & (p_cru >= u)
        sel_b = tarde & (p_cor >= u)
        ra = medir(d, sel_a, p_cru, 'A · probabilidad CRUDA')
        rb = medir(d, sel_b, p_cor, 'B · probabilidad CORREGIDA')
        # ¿mejora la brecha? bootstrap sobre |brecha|, que es lo que se quiere
        # bajar: prometer lo que se cumple, ni más ni menos.
        if ra.get('n') and rb.get('n'):
            aa = d['acierto'].to_numpy(dtype=float)
            def _boot(sel, prob):
                idx = np.flatnonzero(sel)
                return np.array([
                    abs(aa[s].mean() - prob[s].mean())
                    for s in (idx[rng.integers(0, len(idx), len(idx))]
                              for _ in range(BOOT))])
            ba, bb = _boot(sel_a, p_cru), _boot(sel_b, p_cor)
            dif = ba - bb                     # positivo = B tiene menos brecha
            p5 = float(np.percentile(dif, 5))
            ver = 'ADOPTAR' if p5 > 0 else 'RECHAZAR'
            print(f'    |brecha| A {ba.mean():.4f} → B {bb.mean():.4f} · '
                  f'p5 de la mejora {p5:+.4f} · {ver}')
            salida['por_umbral'][f'{u:.2f}'] = {
                'A': ra, 'B': rb, 'brecha_abs_a': float(ba.mean()),
                'brecha_abs_b': float(bb.mean()), 'p5': p5, 'veredicto': ver}

    json.dump(salida, open(SALIDA, 'w'), indent=1, ensure_ascii=False)
    print(f'\n-> {SALIDA}')


if __name__ == '__main__':
    main()
