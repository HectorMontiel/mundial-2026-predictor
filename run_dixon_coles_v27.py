#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Dixon-Coles (v27 §1): estimación heurística de ρ + validación temporal.

τρ corrige las 4 casillas de baja puntuación del producto Poisson:
  τ(0,0)=1+ρ · τ(1,0)=τ(0,1)=1−ρ · τ(1,1)=1+ρ · resto=1

ρ se estima por MÁXIMA VEROSIMILITUD en malla (−0.15…+0.05) sobre el primer
70 % cronológico de TODAS las ligas de clubes (λ,μ = tasas rolling
ataque/defensa, las mismas que alimentarían la matriz); se valida en el
30 % final comparando el log-loss del MARCADOR EXACTO (matriz 7×7) de
Poisson puro vs Dixon-Coles. El 1X2 calibrado NO se toca: en producción τ
se aplica ANTES de la re-ponderación por regiones de _monte_carlo (los
marginales del clasificador se preservan exactos).

Salida: params_dixon_coles.json {rho, generado, validacion} — el pipeline
lo refresca cada 30 días (pipeline_total).
"""

import json
import logging
from math import exp, factorial

import numpy as np
import pandas as pd

from config import LEAGUES

logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
logger = logging.getLogger(__name__)

MAXG = 6
MA = 5


def _muestras():
    """(lam, mu, gh, ga) por partido con tasas rolling SIN fuga."""
    import os
    filas = []
    for clave in LEAGUES:
        ruta = f'historico_{clave}.csv'
        if not os.path.exists(ruta):
            continue
        df = pd.read_csv(ruta, parse_dates=['date'],
                         usecols=['date', 'home_team', 'away_team',
                                  'home_goals', 'away_goals'])
        gf, gc = {}, {}
        for r in df.sort_values('date').itertuples(index=False):
            h, a = r.home_team, r.away_team
            if all(len(gf.get(e, [])) >= 3 for e in (h, a)):
                lam = (np.mean(gf[h][-MA:]) + np.mean(gc[a][-MA:])) / 2
                mu = (np.mean(gf[a][-MA:]) + np.mean(gc[h][-MA:])) / 2
                filas.append((r.date, max(lam, .1), max(mu, .1),
                              int(min(r.home_goals, MAXG)),
                              int(min(r.away_goals, MAXG))))
            for e, p, c in ((h, r.home_goals, r.away_goals),
                            (a, r.away_goals, r.home_goals)):
                gf.setdefault(e, []).append(p)
                gc.setdefault(e, []).append(c)
    filas.sort(key=lambda t: t[0])
    return filas


def _pois(l):
    return np.array([exp(-l) * l ** k / factorial(k) for k in range(MAXG + 1)])


def _matriz(lam, mu, rho):
    M = np.outer(_pois(lam), _pois(mu))
    M[0, 0] *= 1 + rho
    M[1, 0] *= 1 - rho
    M[0, 1] *= 1 - rho
    M[1, 1] *= 1 + rho
    return M / M.sum()


def main():
    filas = _muestras()
    logger.info(f"{len(filas)} partidos con tasas rolling")
    corte = int(len(filas) * 0.70)
    tr, va = filas[:corte], filas[corte:]

    def ll_media(datos, rho):
        return float(np.mean([np.log(max(_matriz(l, m, rho)[gh, ga], 1e-12))
                              for _, l, m, gh, ga in datos]))

    malla = np.round(np.arange(-0.15, 0.051, 0.01), 3)
    lls = {float(r): ll_media(tr, r) for r in malla}
    rho = max(lls, key=lls.get)
    ll_va_p = ll_media(va, 0.0)
    ll_va_dc = ll_media(va, rho)
    salida = {'rho': rho, 'generado': pd.Timestamp.today().strftime('%Y-%m-%d'),
              'n_train': len(tr), 'n_validacion': len(va),
              'll_marcador_poisson': round(-ll_va_p, 5),
              'll_marcador_dixon_coles': round(-ll_va_dc, 5),
              'mejora': round(ll_va_dc - ll_va_p, 6),
              'adoptar': bool(ll_va_dc > ll_va_p)}
    logger.info(f"rho*={rho} · ll marcador validación: poisson {-ll_va_p:.5f} "
                f"vs DC {-ll_va_dc:.5f} → "
                f"{'ADOPTAR' if salida['adoptar'] else 'descartado'}")
    if salida['adoptar']:
        with open('params_dixon_coles.json', 'w', encoding='utf-8') as f:
            json.dump(salida, f, ensure_ascii=False, indent=2)
    with open('resultados_dixon_coles_v27.json', 'w', encoding='utf-8') as f:
        json.dump({**salida, 'malla': {str(k): round(v, 5)
                                       for k, v in lls.items()}}, f, indent=2)
    return salida


if __name__ == '__main__':
    print(json.dumps(main(), indent=2))
