#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v83 — MLB: la misma vía que devolvió el tenis a la Capa 1.

De dónde viene
--------------
En la v82 el tenis volvió a la Capa 1 sin arreglar su modelo: bastó apostar
donde una casa se queda descolgada respecto a la referencia eficiente
(`valor_vs_sharp`). En MLB no se pudo replicar porque el ledger no guarda ancla
de Pinnacle (`pin_*` va a None en `ledger_mlb`).

Pero la fuente sí tiene con qué. `sportsbookreviewsonline` publica el moneyline
de **APERTURA** y el de **CIERRE**, y hasta ahora solo se ingería el cierre. Con
los dos se reconstruye exactamente la misma estructura:

    precio tomable   = la línea de APERTURA (la que había días antes)
    referencia sharp = la línea de CIERRE  (la más eficiente que existe)

Y es accionable: la app toma precios con días de antelación, no al cierre. De
hecho los picks de hoy son de partidos a 1-6 días vista.

Esto es CLV (closing line value) puro, que es el criterio más establecido para
saber si una apuesta era buena independientemente de si acertó. La pregunta que
se responde aquí es si en MLB se puede convertir en dinero.

Guardarraíles (los de siempre)
------------------------------
  · elección en el 70 % más antiguo, validación en el 30 % reciente;
  · ROI **y** bootstrap p5 positivos en LOS DOS periodos;
  · guardia de cordura: el log-loss del CIERRE debe batir al azar. Si no, las
    cuotas están mal pegadas y cualquier ROI es ficticio (lección v78).
"""
import json
import logging

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
log = logging.getLogger('mlb-clv')

N_BOOT = 5000
MIN_N = 80
CORTE = 0.70


def evaluar(cu, justa, gana_local, margen, pmin, semilla=5):
    """cu: [apertura_local, apertura_visitante]; justa: prob del cierre."""
    ev = cu * justa - 1.0
    sel = (ev > margen) & (justa > pmin)
    if sel.sum() < MIN_N:
        return None
    idx = np.argwhere(sel)
    gan = []
    for i, j in idx:
        acierto = gana_local[i] if j == 0 else (not gana_local[i])
        gan.append(cu[i, j] - 1.0 if acierto else -1.0)
    g = np.array(gan, float)
    rng = np.random.default_rng(semilla)
    bs = g[rng.integers(0, len(g), size=(N_BOOT, len(g)))].mean(axis=1)
    return {'n': int(len(g)), 'roi': float(g.mean()),
            'p5': float(np.percentile(bs, 5)),
            'hit': float((g > 0).mean())}


def main():
    import backfill_mlb_odds as bo

    disponibles = bo.ficheros_disponibles()
    log.info(f'{len(disponibles)} temporadas publicadas por la fuente')
    filas = []
    for anio, url in sorted(disponibles.items()):
        try:
            d = bo._descargar(anio, url)
            if d is None or d.empty:
                continue
            filas.extend(bo.parsear(d, anio))
        except Exception as e:
            log.warning(f'{anio}: {type(e).__name__}: {e}')
    if not filas:
        print('no se pudieron leer las temporadas; se aborta')
        return

    df = pd.DataFrame(filas)
    log.info(f'{len(df)} juegos leídos de la fuente')
    need = ['apertura_local', 'apertura_visitante',
            'cuota_local', 'cuota_visitante', 'runs_l', 'runs_v']
    faltan = [c for c in need if c not in df.columns]
    if faltan:
        print(f'faltan columnas: {faltan} — ¿se re-ingirió con la apertura?')
        return
    for c in need:
        df[c] = pd.to_numeric(df[c], errors='coerce')
    df = df.dropna(subset=need)
    df = df[(df[['apertura_local', 'apertura_visitante',
                 'cuota_local', 'cuota_visitante']] > 1).all(axis=1)]
    df = df[df['runs_l'] != df['runs_v']]
    df = df.sort_values('fecha').reset_index(drop=True)
    log.info(f'{len(df)} juegos con apertura Y cierre utilizables')
    if len(df) < 1000:
        print('muestra insuficiente')
        return

    cierre = df[['cuota_local', 'cuota_visitante']].values.astype(float)
    apertura = df[['apertura_local', 'apertura_visitante']].values.astype(float)
    gana_local = (df['runs_l'] > df['runs_v']).values
    inv = 1.0 / cierre
    justa = inv / inv.sum(axis=1, keepdims=True)

    # GUARDIA: el cierre tiene que batir al azar
    pl = np.clip(justa[:, 0], 1e-9, 1 - 1e-9)
    ll = float(-(gana_local * np.log(pl) + (~gana_local) * np.log(1 - pl)).mean())
    print(f'\n{"="*84}')
    print(f'MLB · {len(df)} juegos con apertura y cierre')
    print(f'  log-loss del CIERRE: {ll:.4f}   (azar {np.log(2):.4f})  '
          f'{"OK" if ll < np.log(2) else "DESALINEADO"}')
    if ll >= np.log(2):
        print('  cuotas desalineadas: cualquier ROI de aquí sería ficticio')
        return
    mov = (apertura / cierre - 1.0)
    print(f'  la apertura supera al cierre de media en {mov.mean():+.2%} '
          f'(mediana {np.median(mov):+.2%})')
    print('='*84)

    n = len(df)
    c = int(n * CORTE)
    print(f"{'margen':>7} {'pmin':>6} | {'n(70%)':>7} {'ROI':>8} {'p5':>8} "
          f"| {'n(30%)':>7} {'ROI':>8} {'p5':>8}  ambos")
    print('-'*84)
    robustas = []
    for margen in (0.00, 0.01, 0.02, 0.03, 0.05):
        for pmin in (0.0, 0.30, 0.45, 0.55):
            a = evaluar(apertura[:c], justa[:c], gana_local[:c], margen, pmin)
            b = evaluar(apertura[c:], justa[c:], gana_local[c:], margen, pmin,
                        semilla=11)
            if not a or not b:
                continue
            ok = a['p5'] > 0 and b['p5'] > 0
            if ok:
                robustas.append((margen, pmin, a, b))
            print(f"{margen:7.0%} {pmin:6.0%} | {a['n']:7d} {a['roi']:8.2%} "
                  f"{a['p5']:8.2%} | {b['n']:7d} {b['roi']:8.2%} "
                  f"{b['p5']:8.2%}  {'SI' if ok else ''}")

    if robustas:
        mejor = max(robustas, key=lambda x: x[3]['n'])
        print(f"\n  ROBUSTA: margen {mejor[0]:.0%} · prob mínima {mejor[1]:.0%}")
        print(f"    elección  n={mejor[2]['n']:5d} ROI {mejor[2]['roi']:+.2%} "
              f"p5 {mejor[2]['p5']:+.2%}")
        print(f"    validación n={mejor[3]['n']:5d} ROI {mejor[3]['roi']:+.2%} "
              f"p5 {mejor[3]['p5']:+.2%}")
        print(f"\n  VEREDICTO: EDGE VALIDADO en MLB")
        res = {'robusta': True, 'margen': mejor[0], 'pmin': mejor[1],
               'eleccion': mejor[2], 'validacion': mejor[3], 'n': int(n)}
    else:
        print(f"\n  VEREDICTO: ninguna configuración con p5 positivo en los dos "
              f"periodos → sin edge robusto en MLB por esta vía")
        res = {'robusta': False, 'n': int(n)}
    json.dump(res, open('_v83_mlb_clv.json', 'w', encoding='utf-8'),
              indent=1, ensure_ascii=False, default=float)


if __name__ == '__main__':
    main()
