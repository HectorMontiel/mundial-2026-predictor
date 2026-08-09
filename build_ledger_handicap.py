#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v87 — Ledger fuera de muestra para el HÁNDICAP ASIÁTICO.

Por qué faltaba
---------------
Tras la v86, «Máxima Confianza» ya da acierto real medido en 1X2, Ganador,
Goles y BTTS. El hándicap era el único mercado popular que seguía diciendo «no
medido», y la razón que se dio fue que no hay histórico de líneas asiáticas en
`odds_historico.db`.

Pero para CALIBRAR no hace falta la cuota: hace falta la probabilidad que el
modelo asigna y si se cubrió o no. Las dos se pueden reconstruir.

De dónde sale la probabilidad
-----------------------------
De la misma matriz de marcadores que usa producción. En `alpha_finder`:

    p_home_cubre = float(M[diff > -linea].sum())

y `M` sale de `PredictionEngine._monte_carlo(lam_h, lam_a, probs)`: un Poisson
bivariado con choque común, **re-ponderado para que sus marginales 1X2 cuadren
con las probabilidades calibradas del clasificador**.

Los dos ingredientes ya están fuera de muestra y con walk-forward:
  · `lam_h`, `lam_a`  -> pick_ledger_totales.csv (v86)
  · `p_home/draw/away` -> pick_ledger_total.csv
y se unen por (liga, match_id).

Diferencia con producción: aquí la matriz se calcula de forma ANALÍTICA en vez
de con 20.000 simulaciones por partido, que serían mil millones de sorteos. Es
la versión exacta de lo que el Monte Carlo aproxima; `_v87_matriz_equivale.py`
comprueba que la diferencia es ruido de muestreo.

Salida: `pick_ledger_handicap.csv`
"""
import sys

import numpy as np
import pandas as pd

import handicap as hcp

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

SALIDA = 'pick_ledger_handicap.csv'
MAX_GOLES = 6
# v106 — LA MEDICIÓN AHORA CUBRE LAS LÍNEAS QUE PRODUCCIÓN EVALÚA DE VERDAD.
#
# Hasta aquí sólo se medían las .5, con el argumento de que eran «las que
# evalúa alpha_finder». Era falso: la condición de allí
# (`abs(linea*2 - round(linea*2)) < 1e-6`) dejaba pasar también las ENTERAS, y
# en las enteras hay push. Al no medirlas, el hándicap figuraba como el
# mercado mejor calibrado del proyecto mientras en producción publicaba el
# lado contrario inflado 20-25 puntos (ver `handicap.py`).
#
# Ahora se miden las tres familias con la MISMA función que usa producción
# (`handicap.desglose`), y el acierto se registra de forma tri-estado para no
# volver a contar un push como derrota:
#     ah_{L}_real = 1 (se cobra) · 0 (se pierde) · vacío (push, se devuelve)
# Las de cuarto se resuelven a medias, así que su «acierto» es 0.0/0.5/1.0.
LINEAS = (-2.5, -2.0, -1.75, -1.5, -1.25, -1.0, -0.75, -0.5, -0.25, 0.0,
          0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0, 2.5)


def _clave(L: float) -> str:
    """Nombre de columna estable para una línea (evita '−0.0' y los signos)."""
    return f'{L:+.2f}'.replace('.', 'p')


def _resultado(margen: int, L: float):
    """
    (acierto, fracción_resuelta) con margen real `margen` y línea `L`:

      · acierto = 1.0 si se cobra, 0.0 si se pierde, None si es push completo.
        Nunca vale 0,5: en una línea de cuarto las dos mitades están a 0,5 de
        distancia, así que jamás una gana y la otra pierde — como mucho una
        gana y la otra empata (se cobra todo lo resuelto) o una pierde y la
        otra empata (se pierde todo lo resuelto).
      · fracción_resuelta = parte del importe que NO se devuelve. Vale 1 en
        las líneas .0/.5 que se resuelven y 0,5 en las de cuarto que caen
        justo en el medio punto.

    Hace falta guardar las dos. Con sólo el acierto, el promedio de una línea
    de cuarto mezcla observaciones que arriesgaron todo el importe con otras
    que arriesgaron la mitad, y el «real» deja de ser comparable con la
    probabilidad condicional que se publica. Así salía −1,75 con un sesgo
    aparente de −0,051 que no existe.

    Se calcula con la MISMA descomposición que usa producción, aplicada a una
    distribución degenerada en el margen observado: medición y publicación no
    pueden divergir.
    """
    d = hcp.desglose({int(margen): 1.0}, L)
    if d is None:
        return None, None
    resuelve = d['gana'] + d['pierde']
    if resuelve <= 1e-12:
        return None, 0.0                # push completo: no hay apuesta
    return d['gana'] / resuelve, resuelve


def matriz_marcadores(lam_h: float, lam_a: float,
                      probs: np.ndarray) -> np.ndarray:
    """
    Poisson bivariado con choque común, re-ponderado a las marginales 1X2.

    Réplica analítica de `PredictionEngine._monte_carlo`, con los mismos
    parámetros: lam_comun = 0,12·min(λ), truncado a MAX_GOLES.
    """
    from scipy.stats import poisson

    lam_c = 0.12 * min(lam_h, lam_a)
    a = max(0.05, lam_h - lam_c)
    b = max(0.05, lam_a - lam_c)

    n = MAX_GOLES + 1
    # se calcula sobre un rango amplio y luego se acumula la cola en MAX_GOLES,
    # que es lo que hace el np.clip del Monte Carlo
    ancho = 40
    pc = poisson.pmf(np.arange(ancho), lam_c)
    pa = poisson.pmf(np.arange(ancho), a)
    pb = poisson.pmf(np.arange(ancho), b)

    M = np.zeros((n, n))
    for k in range(ancho):
        if pc[k] < 1e-12:
            continue
        # goles = k + independiente, truncado a MAX_GOLES
        ha = np.zeros(n)
        hb = np.zeros(n)
        for i in range(ancho):
            gh = min(k + i, MAX_GOLES)
            ha[gh] += pa[i]
            gb = min(k + i, MAX_GOLES)
            hb[gb] += pb[i]
        M += pc[k] * np.outer(ha, hb)

    s = M.sum()
    if s > 0:
        M /= s

    idx = np.arange(n)
    regiones = [(M * (idx[:, None] > idx[None, :]), probs[0]),
                (M * (idx[:, None] == idx[None, :]), probs[1]),
                (M * (idx[:, None] < idx[None, :]), probs[2])]
    cal = np.zeros_like(M)
    for reg, obj in regiones:
        masa = reg.sum()
        if masa > 1e-9:
            cal += reg * (obj / masa)
    t = cal.sum()
    return cal / t if t > 0 else cal


def construir() -> pd.DataFrame:
    tot = pd.read_csv('pick_ledger_totales.csv')
    uno = pd.read_csv('pick_ledger_total.csv')
    uno = uno[uno['deporte'] == 'Fútbol'][
        ['liga', 'match_id', 'p_home', 'p_draw', 'p_away']]
    d = tot.merge(uno, on=['liga', 'match_id'], how='inner')
    print(f'  partidos con λ y probabilidades 1X2: {len(d)}')

    n = MAX_GOLES + 1
    idx = np.arange(n)
    diff = idx[:, None] - idx[None, :]

    filas = []
    lam_h = d['lam_h'].values
    lam_a = d['lam_a'].values
    P = d[['p_home', 'p_draw', 'p_away']].values
    gl = d['goles_local'].values
    gv = d['goles_visit'].values

    for i in range(len(d)):
        M = matriz_marcadores(float(lam_h[i]), float(lam_a[i]), P[i])
        margen = int(gl[i]) - int(gv[i])
        fila = {'liga': d['liga'].iat[i], 'match_id': d['match_id'].iat[i],
                'fecha': d['fecha'].iat[i], 'pliegue': int(d['pliegue'].iat[i]),
                'margen': margen}
        dist = hcp.distribucion_margen(M)
        for L in LINEAS:
            # probabilidad CONDICIONAL de cobrar (el push no cuenta): es la
            # misma cifra que se publica en la tarjeta y contra la que se
            # compara la cuota.
            p = hcp.probabilidad(dist, L)
            acierto, resuelto = _resultado(margen, L)
            k = _clave(L)
            fila[f'p_ah_{k}'] = None if p is None else round(p, 5)
            fila[f'ah_{k}_real'] = acierto
            fila[f'res_ah_{k}'] = resuelto
        filas.append(fila)
        if (i + 1) % 5000 == 0:
            print(f'    {i + 1}/{len(d)}')

    out = pd.DataFrame(filas)
    out.to_csv(SALIDA, index=False)
    return out


if __name__ == '__main__':
    print('construyendo ledger de hándicap asiático...')
    d = construir()
    print(f'\n{len(d)} partidos -> {SALIDA}')
    print('\ncordura (predicho medio frente a cobertura real):')
    print('  los push quedan FUERA de ambas columnas — no son ni acierto ni '
          'fallo, y contarlos era justo el error de la v65.')
    for L in LINEAS:
        k = _clave(L)
        col_p, col_r, col_s = f'p_ah_{k}', f'ah_{k}_real', f'res_ah_{k}'
        sub = d[[col_p, col_r, col_s]].dropna()
        if sub.empty:
            print(f'  local {L:+.2f}: sin muestra resuelta')
            continue
        # medias PONDERADAS por el importe que realmente se arriesga. Sin el
        # peso, una línea de cuarto mezcla apuestas de importe entero con
        # apuestas a medias y el sesgo que sale no es real.
        w = sub[col_s].values
        pred = float((sub[col_p].values * w).sum() / w.sum())
        real = float((sub[col_r].values * w).sum() / w.sum())
        n_push = int(d[col_r].isna().sum())
        print(f'  local {L:+.2f}: predicho {pred:.3f} · real {real:.3f} · '
              f'sesgo {pred - real:+.3f} · n {len(sub)} '
              f'(push {n_push})')
