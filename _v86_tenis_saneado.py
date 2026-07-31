#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v86 — `valor_vs_sharp` en tenis con Odd_Max SANEADO.

Qué encontró _v86_atp_outliers.py
---------------------------------
ATP, mejora de Odd_Max sobre Pinnacle:

    mediana +2,6 a +5,8 % según el año   (normal)
    media   2015: +140,36 %   2016: +360,25 %   (imposible)
    máximo  +892.688 %  -> una cuota de 42.586

O sea: la mediana está sana y la media está destrozada por unos pocos partidos.
Y `valor_vs_sharp` selecciona precisamente por EV máximo, así que iba directa a
esa basura. Eso explica por qué ninguna configuración del ATP sobrevivía fuera
de muestra.

El criterio de limpieza
-----------------------
NO se elige por ROI. Elegir el corte que más paga es el sobreajuste que ya
obligó a tres correcciones en este proyecto. Los tres filtros son de
IMPOSIBILIDAD ECONÓMICA, y se habrían escrito igual sin mirar el resultado:

  1. Odd_Max >= Odd_PS en los dos lados.
     "La mejor cuota del mercado" no puede ser PEOR que la de una casa concreta
     que está dentro de ese mercado. Si lo es, la fila está mal.

  2. Overround de Odd_Max >= 0,95.
     Tomando la mejor cuota de cada lado, 1/c1 + 1/c2 < 1 es arbitraje puro. Un
     2-3 % aparece de verdad y dura segundos; un 5 % o más sostenido no existe:
     es un dato erróneo.

  3. Odd_Max <= 1,5 x Odd_PS en cada lado.
     Pinnacle es el precio de referencia del tenis. Una casa que ofrezca un 50 %
     más que Pinnacle no está "descolgada": está mal transcrita. El p99 de la
     mejora real es +21 %, así que este corte sólo toca la cola imposible.

Se mide, con los mismos guardarraíles de v80/v82 (elegir en el 70 % antiguo,
validar en el 30 % reciente, exigir p5 > 0 en LOS DOS):

  a) ATP saneado — ¿aparece el edge que la basura tapaba?
  b) WTA saneado — CONTROL OBLIGATORIO: la WTA ya está desplegada en Capa 1. Si
     su edge venía de las mismas filas corruptas, hay que saberlo AHORA.
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

N_BOOT = 5000
MIN_N = 80
CORTE = 0.70

RATIO_MAX = 1.50        # Odd_Max no puede superar a Pinnacle en más de un 50 %
OVERROUND_MIN = 0.95    # arbitraje de más del 5 % = dato erróneo


def cargar(circuito):
    from engines.tennis_engine import TennisEngine
    e = TennisEngine(circuito)
    df = e.cargar_datos_historicos()
    need = ['Odd_PS_1', 'Odd_PS_2', 'Odd_Max_1', 'Odd_Max_2']
    if any(c not in df.columns for c in need):
        return None, None
    d = df.dropna(subset=need).copy()
    for c in need:
        d[c] = pd.to_numeric(d[c], errors='coerce')
    d = d.dropna(subset=need)
    d = d[(d[need] > 1.0).all(axis=1)]
    if 'Winner' not in d.columns or 'Player_1' not in d.columns:
        return None, None
    gana1 = (d['Winner'].astype(str) == d['Player_1'].astype(str)).values
    col_f = 'Date' if 'Date' in d.columns else ('date' if 'date' in d.columns else None)
    d['__f'] = pd.to_datetime(d[col_f], errors='coerce') if col_f else pd.RangeIndex(len(d))
    orden = np.argsort(d['__f'].values)
    d = d.iloc[orden].reset_index(drop=True)
    return d, gana1[orden]


def sanear(d, gana1):
    """Aplica los tres filtros estructurales. Devuelve (d, gana1, informe)."""
    pin = d[['Odd_PS_1', 'Odd_PS_2']].values.astype(float)
    mx = d[['Odd_Max_1', 'Odd_Max_2']].values.astype(float)

    f1 = (mx >= pin).all(axis=1)
    f2 = (1 / mx).sum(axis=1) >= OVERROUND_MIN
    f3 = (mx <= RATIO_MAX * pin).all(axis=1)
    keep = f1 & f2 & f3

    informe = {
        'n_inicial': int(len(d)),
        'descartados_max_peor_que_pinnacle': int((~f1).sum()),
        'descartados_arbitraje_imposible': int((~f2).sum()),
        'descartados_ratio_absurdo': int((~f3).sum()),
        'n_final': int(keep.sum()),
        'pct_descartado': float(1 - keep.mean()),
    }
    return d[keep].reset_index(drop=True), gana1[keep], informe


def evaluar(cu, justa, gana1, margen, pmin, semilla=5):
    ev = cu * justa - 1.0
    sel = (ev > margen) & (justa > pmin)
    if sel.sum() < MIN_N:
        return None
    idx = np.argwhere(sel)
    gan = []
    for i, j in idx:
        acierto = (j == 0) if gana1[i] else (j == 1)
        gan.append(cu[i, j] - 1.0 if acierto else -1.0)
    g = np.array(gan, float)
    rng = np.random.default_rng(semilla)
    bs = g[rng.integers(0, len(g), size=(N_BOOT, len(g)))].mean(axis=1)
    return {'n': int(len(g)), 'roi': float(g.mean()),
            'p5': float(np.percentile(bs, 5)), 'hit': float((g > 0).mean())}


def barrer(d, gana1, etiqueta):
    pin = d[['Odd_PS_1', 'Odd_PS_2']].values.astype(float)
    mx = d[['Odd_Max_1', 'Odd_Max_2']].values.astype(float)
    inv = 1.0 / pin
    justa = inv / inv.sum(axis=1, keepdims=True)

    p1 = np.clip(justa[:, 0], 1e-9, 1 - 1e-9)
    ll = float(-(gana1 * np.log(p1) + (~gana1) * np.log(1 - p1)).mean())
    print(f'\n  log-loss de Pinnacle: {ll:.4f} (azar {np.log(2):.4f}) '
          f'{"OK" if ll < np.log(2) else "DESALINEADO"}')
    if ll >= np.log(2):
        print('  cuotas desalineadas: cualquier ROI sería ficticio')
        return None

    mejora = mx / pin - 1.0
    print(f'  mejora sobre Pinnacle: media {mejora.mean():+.2%} · '
          f'mediana {np.median(mejora):+.2%} · máx {mejora.max():+.2%}')

    n = len(d)
    c = int(n * CORTE)
    print(f"\n  {'margen':>7} {'pmin':>6} | {'n(70%)':>7} {'ROI':>8} {'p5':>8} "
          f"| {'n(30%)':>7} {'ROI':>8} {'p5':>8}  robusta")
    print('  ' + '-' * 80)
    robustas = []
    for margen in (0.00, 0.01, 0.02, 0.03, 0.05):
        for pmin in (0.0, 0.30, 0.50):
            a = evaluar(mx[:c], justa[:c], gana1[:c], margen, pmin)
            b = evaluar(mx[c:], justa[c:], gana1[c:], margen, pmin, semilla=11)
            if not a or not b:
                continue
            ok = a['p5'] > 0 and b['p5'] > 0
            if ok:
                robustas.append((margen, pmin, a, b))
            print(f"  {margen:7.0%} {pmin:6.0%} | {a['n']:7d} {a['roi']:8.2%} "
                  f"{a['p5']:8.2%} | {b['n']:7d} {b['roi']:8.2%} "
                  f"{b['p5']:8.2%}  {'SI' if ok else ''}")

    if robustas:
        mejor = max(robustas, key=lambda x: x[3]['n'])
        print(f"\n  ROBUSTA ({len(robustas)} de 15 configuraciones): "
              f"margen {mejor[0]:.0%} · prob mínima {mejor[1]:.0%}")
        print(f"    elección  n={mejor[2]['n']} ROI {mejor[2]['roi']:+.2%} "
              f"p5 {mejor[2]['p5']:+.2%}")
        print(f"    VALIDACIÓN n={mejor[3]['n']} ROI {mejor[3]['roi']:+.2%} "
              f"p5 {mejor[3]['p5']:+.2%}")
        print(f"  VEREDICTO {etiqueta}: EDGE VALIDADO")
        return {'robusta': True, 'n_robustas': len(robustas),
                'margen': mejor[0], 'pmin': mejor[1],
                'eleccion': mejor[2], 'validacion': mejor[3]}
    print(f"\n  VEREDICTO {etiqueta}: sin configuración robusta")
    return {'robusta': False, 'n_robustas': 0}


def main():
    salida = {}
    for circ in ('atp', 'wta'):
        print('\n' + '=' * 84)
        print(f'{circ.upper()}')
        print('=' * 84)
        d, gana1 = cargar(circ)
        if d is None:
            print('  sin datos utilizables')
            continue

        print(f'\n--- ANTES de sanear ({len(d)} partidos) ---')
        antes = barrer(d, gana1, f'{circ.upper()} SIN SANEAR')

        ds, gs, inf = sanear(d, gana1)
        print(f'\n--- SANEADO ---')
        print(f'  descartes:')
        print(f'    Odd_Max peor que Pinnacle : '
              f'{inf["descartados_max_peor_que_pinnacle"]:6d}')
        print(f'    arbitraje > 5 % (imposible): '
              f'{inf["descartados_arbitraje_imposible"]:6d}')
        print(f'    Odd_Max > 1,5x Pinnacle    : '
              f'{inf["descartados_ratio_absurdo"]:6d}')
        print(f'    quedan {inf["n_final"]} de {inf["n_inicial"]} '
              f'({1 - inf["pct_descartado"]:.2%})')
        despues = barrer(ds, gs, f'{circ.upper()} SANEADO')

        salida[circ] = {'informe_limpieza': inf, 'antes': antes,
                        'despues': despues}

    print('\n' + '=' * 84)
    print('RESUMEN')
    print('=' * 84)
    for circ, r in salida.items():
        a = (r['antes'] or {}).get('robusta')
        p = (r['despues'] or {}).get('robusta')
        na = (r['antes'] or {}).get('n_robustas', 0)
        npo = (r['despues'] or {}).get('n_robustas', 0)
        print(f'  {circ.upper():4s} antes: {"EDGE" if a else "sin edge":9s} '
              f'({na}/15 configs)   '
              f'saneado: {"EDGE" if p else "sin edge":9s} ({npo}/15 configs)')

    json.dump(salida, open('_v86_tenis_saneado.json', 'w', encoding='utf-8'),
              indent=1, ensure_ascii=False, default=float)
    print('\nGuardado en _v86_tenis_saneado.json')


if __name__ == '__main__':
    main()
