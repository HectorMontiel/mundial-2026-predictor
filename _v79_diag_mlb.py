#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v79 — Diagnóstico del modelo de MLB.

Tres hipótesis a comprobar con números, no con intuición:

  H1. El estado del modelo (ELO, forma, racha) está congelado en 2025-09-28,
      así que la temporada 2026 se predice con la forma del año pasado.
  H2. Las features de PITCHER están muertas en inferencia: `apuestas_dia`
      llama a `predecir(home, away)` sin abridores, así que `pr_h` y `pr_a`
      caen al valor por defecto 4.5 y DIFF_PIT_RA sale 0 SIEMPRE.
  H3. Por H1+H2 las probabilidades colapsan hacia 50-50.
"""
import json
import logging
import numpy as np

logging.basicConfig(level=logging.WARNING)


def main():
    from engines.mlb_engine import MLBEngine, FEATURES, codigo_mlb
    eng = MLBEngine().cargar_modelo()
    print(f"modelo listo: {eng.listo}  | metadata: "
          f"acc={eng.metadata.get('precision_validacion')} "
          f"ll={eng.metadata.get('log_loss_validacion')}")

    # ---------- H1: frescura del estado --------------------------------
    import pandas as pd
    eq = eng.estado.get('equipos', {})
    fechas = [v.get('ult_fecha') for v in eq.values() if v.get('ult_fecha')]
    hoy = pd.Timestamp.today().normalize()
    ult = pd.Timestamp(max(fechas))
    print(f"\n[H1] estado del modelo")
    print(f"     último partido en el estado : {ult.date()}")
    print(f"     hoy                          : {hoy.date()}")
    print(f"     ANTIGÜEDAD                   : {(hoy - ult).days} días")
    print(f"     filas de identidad (v78)     : {len(eng.estado.get('filas') or [])}")

    # ---------- H2: features de pitcher en inferencia -------------------
    # v79: se mide el camino REAL de producción, con los abridores probables
    # que publica la API oficial, no una llamada pelada.
    import mlb_statsapi
    abridores = mlb_statsapi.indice_abridores()
    print(f"\n[H2] features en inferencia (con abridores reales: "
          f"{len(abridores)} partidos hoy)")
    codigos = sorted(eq.keys())
    muestras = []
    for (h, a), (hp, ap) in abridores.items():
        x = eng.construir_features(h, a, home_pitcher=hp, away_pitcher=ap)
        if x:
            muestras.append(x)
    if not muestras:                      # sin jornada: pares sintéticos
        for i in range(0, min(len(codigos) - 1, 20), 2):
            x = eng.construir_features(codigos[i], codigos[i + 1])
            if x:
                muestras.append(x)
    M = np.array(muestras)
    print(f"     {len(M)} enfrentamientos de muestra")
    for j, nombre in enumerate(FEATURES):
        col = M[:, j]
        marca = '  <-- CONSTANTE (muerta)' if col.std() < 1e-9 else ''
        print(f"     {nombre:14s} media={col.mean():+.4f} "
              f"std={col.std():.4f}{marca}")

    # ---------- H3: distribución de probabilidades ----------------------
    print(f"\n[H3] probabilidades sobre TODOS los emparejamientos posibles")
    probs = []
    for i, h in enumerate(codigos):
        for a in codigos:
            if h == a:
                continue
            hp, ap = abridores.get((h, a), ('', ''))
            p = eng.predecir(h, a, home_pitcher=hp, away_pitcher=ap)
            if 'error' not in p:
                probs.append(p['prob_home'])

    # Probabilidades de los partidos REALES de hoy, que es lo que ve el usuario
    hoy_probs = []
    for (h, a), (hp, ap) in abridores.items():
        p = eng.predecir(h, a, home_pitcher=hp, away_pitcher=ap)
        if 'error' not in p:
            hoy_probs.append((h, a, p['prob_home']))
    if hoy_probs:
        print(f"\n[HOY] {len(hoy_probs)} partidos con abridor:")
        for h, a, pr in sorted(hoy_probs, key=lambda x: -abs(x[2] - 0.5)):
            print(f"       {a:4s} @ {h:4s}   local {pr:.3f}")
    probs = np.array(probs)
    print(f"     n={len(probs)}  media={probs.mean():.4f}  std={probs.std():.4f}")
    print(f"     min={probs.min():.4f}  p25={np.percentile(probs,25):.4f}  "
          f"mediana={np.median(probs):.4f}  p75={np.percentile(probs,75):.4f}  "
          f"max={probs.max():.4f}")
    cerca = ((probs > 0.45) & (probs < 0.55)).mean()
    print(f"     FRACCIÓN entre 45% y 55% (o sea, «50-50»): {cerca:.1%}")
    for lo in (0.30, 0.40, 0.45, 0.50, 0.55, 0.60, 0.70):
        n = ((probs >= lo) & (probs < lo + 0.05)).sum()
        print(f"       {lo:.2f}-{lo+0.05:.2f}: {n:5d}  "
              f"{'#' * int(60*n/max(len(probs),1))}")

    json.dump({'antiguedad_dias': int((hoy - ult).days),
               'ultimo_estado': str(ult.date()),
               'frac_50_50': float(cerca),
               'std_prob': float(probs.std()),
               'media_prob': float(probs.mean())},
              open('_v79_diag_mlb.json', 'w', encoding='utf-8'), indent=1)


if __name__ == '__main__':
    main()
