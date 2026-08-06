#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v101 — ¿El lazo de aprendizaje mejora de verdad, o sólo lo parece?

Un módulo que se recalibra a sí mismo es peligrosamente fácil de validar mal:
si se ajusta la calibración sobre todo el histórico y luego se mide en ese
mismo histórico, SIEMPRE sale que mejora. Eso no es aprendizaje, es memoria.

Aquí se mide como se usaría de verdad: **el mapa de calibración se aprende sólo
con el pasado y se aplica al futuro**, avanzando por pliegues. En el pliegue k,
`aprendizaje_continuo.aprender` sólo ve los partidos anteriores al corte, y sus
correcciones se juzgan sobre los posteriores, que no ha visto.

Se reportan las tres cosas que importan:
  · log-loss antes y después (¿mejora la calibración?)
  · Brier antes y después (¿mejora la precisión de la probabilidad?)
  · acierto antes y después (debe quedar IGUAL: la corrección es monótona y no
    reordena; si el acierto se mueve, hay un bug)

Veredicto por p5 de bootstrap pareado, como todo lo demás en el proyecto.
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
SEMILLA = 101
SALIDA = '_v101_validar_aprendizaje.json'


def walk_forward(d: pd.DataFrame, col_p: str, col_y: str,
                 niveles, etiqueta: str) -> dict:
    d = d.dropna(subset=[col_p, col_y]).sort_values('fecha', kind='stable')
    d = d.reset_index(drop=True)
    n = len(d)
    if n < 2000:
        print(f'  {etiqueta}: muestra insuficiente ({n})')
        return {'veredicto': 'SIN MUESTRA', 'n': n}
    bordes = [int(n * (0.4 + 0.1 * i)) for i in range(N_PLIEGUES + 1)]
    p_cru = pd.to_numeric(d[col_p], errors='coerce').to_numpy(dtype=float)
    y = pd.to_numeric(d[col_y], errors='coerce').to_numpy(dtype=float)
    p_aju = p_cru.copy()

    for i in range(N_PLIEGUES):
        ini, fin = bordes[i], bordes[i + 1]
        mapa = ac.aprender(d.iloc[:ini], col_p, col_y, niveles)
        for j in range(ini, fin):
            ctx = {k: str(d.iloc[j][k]) for k in niveles if k in d.columns}
            p_aju[j] = ac.aplicar(float(p_cru[j]), mapa, ctx)

    msk = np.arange(n) >= bordes[JUICIO_DESDE]
    yy = y[msk]

    def ll(p):
        p = np.clip(p[msk], 1e-9, 1 - 1e-9)
        return -(yy * np.log(p) + (1 - yy) * np.log(1 - p))

    ea, eb = ll(p_cru), ll(p_aju)
    dif = ea - eb
    rng = np.random.default_rng(SEMILLA)
    bt = np.array([dif[rng.integers(0, len(dif), len(dif))].mean()
                   for _ in range(BOOT)])
    p5 = float(np.percentile(bt, 5))
    acc_a = float(((p_cru[msk] >= 0.5) == yy).mean())
    acc_b = float(((p_aju[msk] >= 0.5) == yy).mean())
    br_a = float(np.mean((p_cru[msk] - yy) ** 2))
    br_b = float(np.mean((p_aju[msk] - yy) ** 2))
    # brecha de calibración: |acierto − prometido|, que es lo que se quiere bajar
    bre_a = abs(float(yy.mean() - p_cru[msk].mean()))
    bre_b = abs(float(yy.mean() - p_aju[msk].mean()))
    ver = 'ADOPTAR' if p5 > 0 else 'RECHAZAR'
    print(f'  {etiqueta:<20} n={len(dif):>6} · log-loss {ea.mean():.5f} → '
          f'{eb.mean():.5f} (p5 {p5:+.5f}) · Brier {br_a:.4f} → {br_b:.4f} · '
          f'acierto {acc_a:.4f} → {acc_b:.4f} · brecha {bre_a:.4f} → '
          f'{bre_b:.4f} · {ver}')
    return {'n': int(len(dif)), 'll_crudo': float(ea.mean()),
            'll_ajustado': float(eb.mean()), 'mejora': float(dif.mean()),
            'p5': p5, 'brier_crudo': br_a, 'brier_ajustado': br_b,
            'acierto_crudo': acc_a, 'acierto_ajustado': acc_b,
            'brecha_cruda': bre_a, 'brecha_ajustada': bre_b,
            'veredicto': ver}


def main():
    salida = {}
    print('\n=== Ledger de goles (predicciones fuera de muestra)')
    t = pd.read_csv('pick_ledger_totales.csv')
    for mercado, cp_, cy in (('Goles over 1.5', 'p_over_1.5', 'over_1.5_real'),
                             ('Goles over 2.5', 'p_over_2.5', 'over_2.5_real'),
                             ('BTTS', 'p_btts', 'btts_real')):
        d = t[['fecha', 'liga', cp_, cy]].copy()
        d['deporte'] = 'Fútbol'
        d['mercado'] = mercado
        salida[mercado] = walk_forward(d, cp_, cy, ['deporte', 'mercado'],
                                       mercado)

    print('\n=== Ledger 1X2')
    led = pd.read_csv('pick_ledger.csv')
    for etiqueta, cp_, valor in (('1x2 gana local', 'p_home', 0),
                                 ('1x2 empate', 'p_draw', 1),
                                 ('1x2 gana visita', 'p_away', 2)):
        d = led[['fecha', 'liga', cp_, 'resultado']].copy()
        d['_y'] = (d['resultado'] == valor).astype(float)
        d['deporte'] = 'Fútbol'
        d['mercado'] = etiqueta
        salida[etiqueta] = walk_forward(d, cp_, '_y', ['deporte', 'mercado'],
                                        etiqueta)

    print('\n=== Picks REALES publicados (muestra pequeña, por eso se separa)')
    if pd.io.common.file_exists('picks_historico.csv'):
        d = pd.read_csv('picks_historico.csv')
        d = d[d['resultado'].notna()]
        salida['produccion'] = walk_forward(d, 'prob', 'resultado',
                                            ['deporte', 'mercado'],
                                            'producción')

    json.dump(salida, open(SALIDA, 'w'), indent=1, ensure_ascii=False)
    print(f'\n-> {SALIDA}')


if __name__ == '__main__':
    main()
