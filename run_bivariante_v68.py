#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v68 §3c — ¿Aporta modelar la DEPENDENCIA entre goles local y visitante?

Contexto y por qué esto no repite lo de v27
-------------------------------------------
v27 probó Dixon-Coles (corrección τ de las 4 casillas de marcador bajo) sobre
13k+ partidos y lo DESCARTÓ: el ρ óptimo en train salía con signo opuesto a la
teoría y el log-loss del marcador exacto no mejoraba. Eso NO agota la cuestión:

  · Dixon-Coles retoca 4 celdas; no modela correlación en toda la matriz.
  · El motor INTERNACIONAL ya usa una matriz de CHOQUE COMÚN en producción
    (λ₀ = 0.12·min(λh,λa)) — o sea, el proyecto ya "cree" en la dependencia.
  · Pero las ligas de CLUBES seguían con `np.outer`: independencia pura.

Este experimento mide, con el MISMO protocolo de v27 (tasas rolling sin fuga,
corte cronológico 70/30), tres matrices sobre los mismos partidos:

    independiente · choque_comun · copula gaussiana (ρ ajustado en train)

y compara TRES métricas, no una:
    · log-loss del MARCADOR EXACTO (la de v27)
    · log-loss del 1X2          (lo que de verdad se apuesta)
    · Brier de BTTS             (el mercado que v68 quiere activar)

Uso:  .venv\\Scripts\\python.exe run_bivariante_v68.py
"""

import json
import logging
import os

import numpy as np
import pandas as pd

import distributions as D
from config import LEAGUES

logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
logger = logging.getLogger(__name__)

SALIDA = 'resultados_bivariante_v68.json'
VENTANA = 8            # partidos de la media rolling
MIN_PARTIDOS_EQUIPO = 5


def cargar_partidos() -> list:
    """(liga, lam_h, lam_a, gh, ga) por partido con tasas rolling SIN fuga."""
    filas = []
    for clave in LEAGUES:
        ruta = f'historico_{clave}.csv'
        if not os.path.exists(ruta):
            continue
        try:
            df = pd.read_csv(ruta, parse_dates=['date'],
                             usecols=['date', 'home_team', 'away_team',
                                      'home_goals', 'away_goals'])
        except Exception:
            continue
        gf, gc = {}, {}
        for r in df.sort_values('date').itertuples(index=False):
            h, a = r.home_team, r.away_team
            hh, aa = gf.get(h, []), gf.get(a, [])
            dh, da = gc.get(h, []), gc.get(a, [])
            if len(hh) >= MIN_PARTIDOS_EQUIPO and len(aa) >= MIN_PARTIDOS_EQUIPO:
                # ataque propio x defensa rival (el clásico), con localía
                lam_h = float(np.mean(hh[-VENTANA:]) * np.mean(da[-VENTANA:]) / 1.35)
                lam_a = float(np.mean(aa[-VENTANA:]) * np.mean(dh[-VENTANA:]) / 1.35)
                lam_h, lam_a = np.clip(lam_h, 0.2, 4.0), np.clip(lam_a, 0.2, 4.0)
                filas.append((clave, lam_h, lam_a,
                              int(r.home_goals), int(r.away_goals), r.date))
            gf.setdefault(h, []).append(float(r.home_goals))
            gf.setdefault(a, []).append(float(r.away_goals))
            gc.setdefault(h, []).append(float(r.away_goals))
            gc.setdefault(a, []).append(float(r.home_goals))
    filas.sort(key=lambda x: x[5])
    logger.info(f"{len(filas)} partidos con tasas rolling de "
                f"{len({f[0] for f in filas})} ligas")
    return filas


def _metricas(datos, metodo, rho=0.0):
    ll_exacto, ll_1x2, brier_btts = [], [], []
    n = D.MAX_GOLES_MATRIZ
    for _, lh, la, gh, ga, _d in datos:
        M = D.matriz_goles(lh, la, metodo, rho, n)
        ll_exacto.append(np.log(max(M[min(gh, n), min(ga, n)], 1e-12)))
        p1, px, p2 = D.probabilidades_1x2(M)
        real = 0 if gh > ga else (1 if gh == ga else 2)
        ll_1x2.append(np.log(max([p1, px, p2][real], 1e-12)))
        btts = D.prob_btts(M)
        brier_btts.append((btts - (1.0 if gh > 0 and ga > 0 else 0.0)) ** 2)
    return {'ll_exacto': round(-float(np.mean(ll_exacto)), 5),
            'll_1x2': round(-float(np.mean(ll_1x2)), 5),
            'brier_btts': round(float(np.mean(brier_btts)), 5)}


def main():
    datos = cargar_partidos()
    if len(datos) < 2000:
        logger.error("Muestra insuficiente."); return
    corte = int(len(datos) * 0.70)
    tr, va = datos[:corte], datos[corte:]
    logger.info(f"train {len(tr)} · validación {len(va)}")

    # ρ de la cópula: se AJUSTA en train (minimizando log-loss del 1X2, que es
    # lo que se apuesta), nunca en validación.
    malla = np.round(np.arange(-0.20, 0.201, 0.025), 3)
    lls = {float(r): _metricas(tr[-6000:], 'copula', float(r))['ll_1x2'] for r in malla}
    rho = min(lls, key=lls.get)
    logger.info(f"ρ óptimo en train = {rho} (malla {malla[0]}..{malla[-1]})")

    resultados = {'rho_train': rho, 'malla_train': lls,
                  'n_train': len(tr), 'n_validacion': len(va), 'validacion': {}}
    for nombre, metodo, r in (('independiente', 'independiente', 0.0),
                              ('choque_comun', 'choque_comun', 0.0),
                              ('copula', 'copula', rho)):
        m = _metricas(va, metodo, r)
        resultados['validacion'][nombre] = m
        logger.info(f"  {nombre:14s} ll_exacto={m['ll_exacto']:.5f} "
                    f"ll_1x2={m['ll_1x2']:.5f} brier_btts={m['brier_btts']:.5f}")

    base = resultados['validacion']['independiente']
    veredicto = {}
    for nombre in ('choque_comun', 'copula'):
        m = resultados['validacion'][nombre]
        veredicto[nombre] = {
            'd_ll_exacto': round(m['ll_exacto'] - base['ll_exacto'], 5),
            'd_ll_1x2': round(m['ll_1x2'] - base['ll_1x2'], 5),
            'd_brier_btts': round(m['brier_btts'] - base['brier_btts'], 5),
            # mejora = baja el log-loss del 1X2 sin empeorar el Brier de BTTS
            'mejora': bool(m['ll_1x2'] < base['ll_1x2']
                           and m['brier_btts'] <= base['brier_btts'] + 1e-4),
        }
    resultados['veredicto'] = veredicto
    ganador = min(resultados['validacion'], key=lambda k: resultados['validacion'][k]['ll_1x2'])
    resultados['adoptar'] = ganador
    logger.info(f"VEREDICTO: {json.dumps(veredicto, ensure_ascii=False)}")
    logger.info(f"ADOPTAR: {ganador}")
    with open(SALIDA, 'w', encoding='utf-8') as f:
        json.dump(resultados, f, ensure_ascii=False, indent=1)


if __name__ == '__main__':
    main()
