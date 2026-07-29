#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v80 — ¿Qué método de devigado reproduce mejor la probabilidad real?

Por qué importa
---------------
Quitarle el margen a las cuotas es el paso del que cuelga TODO lo demás: el
ancla del encogimiento, el `valor_vs_sharp` que hoy llena la Capa 1 y el
`m_*` con el que se valida. Si el devigado sesga, sesga todo a la vez.

El proyecto usa dos métodos y elige `potencia` en los puntos críticos, con este
argumento en el docstring: «castiga más al favorito, que es lo que mejor
reproduce el sesgo favorito-perdedor». Es una afirmación razonable **y nunca se
midió**.

Se comparan cuatro sobre las cuotas de cierre del ledger, que traen el
resultado real:

  · proporcional — reparte el margen en proporción a la implícita
  · potencia     — busca k tal que Σ pᵏ = 1  (el que se usa hoy)
  · aditivo      — resta el margen a partes iguales
  · Shin         — modelo de insiders (Shin 1993), el estándar académico

La métrica es la log-loss de la probabilidad resultante contra el resultado.
No hay ambigüedad: la mejor es la que predice mejor.
"""
import json
import logging

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
log = logging.getLogger('devig')

LEDGER = 'pick_ledger_total.csv'


def proporcional(cu):
    inv = 1.0 / cu
    return inv / inv.sum(axis=1, keepdims=True)


def potencia(cu):
    inv = 1.0 / cu
    k = np.ones(len(cu))
    lo, hi = np.full(len(cu), 0.5), np.full(len(cu), 1.5)
    for _ in range(60):
        k = (lo + hi) / 2
        tot = (inv ** k[:, None]).sum(axis=1)
        mayor = tot > 1
        lo = np.where(mayor, k, lo)
        hi = np.where(mayor, hi, k)
    p = inv ** k[:, None]
    return p / p.sum(axis=1, keepdims=True)


def aditivo(cu):
    inv = 1.0 / cu
    n = cu.shape[1]
    exceso = (inv.sum(axis=1, keepdims=True) - 1.0) / n
    p = np.clip(inv - exceso, 1e-6, None)
    return p / p.sum(axis=1, keepdims=True)


def shin(cu):
    """
    Modelo de Shin: el margen viene de que la casa se protege de apostadores
    informados. Se resuelve z (proporción de dinero informado) por bisección.

        p_i = (sqrt(z² + 4(1-z)·π_i²/Σπ) - z) / (2(1-z))
    """
    inv = 1.0 / cu
    s = inv.sum(axis=1, keepdims=True)
    lo = np.zeros(len(cu))
    hi = np.full(len(cu), 0.5)
    for _ in range(60):
        z = (lo + hi) / 2
        zz = z[:, None]
        p = (np.sqrt(zz ** 2 + 4 * (1 - zz) * inv ** 2 / s) - zz) / \
            (2 * (1 - zz))
        tot = p.sum(axis=1)
        mayor = tot > 1
        lo = np.where(mayor, z, lo)
        hi = np.where(mayor, hi, z)
    zz = ((lo + hi) / 2)[:, None]
    p = (np.sqrt(zz ** 2 + 4 * (1 - zz) * inv ** 2 / s) - zz) / (2 * (1 - zz))
    return p / p.sum(axis=1, keepdims=True)


METODOS = {'proporcional': proporcional, 'potencia (actual)': potencia,
           'aditivo': aditivo, 'Shin': shin}


def evaluar(cu, res, etiqueta):
    out = {}
    for nombre, fn in METODOS.items():
        p = np.clip(fn(cu), 1e-9, 1 - 1e-9)
        p = p / p.sum(axis=1, keepdims=True)
        elegida = p[np.arange(len(res)), res]
        ll = float(-np.log(np.clip(elegida, 1e-9, None)).mean())
        acc = float((p.argmax(axis=1) == res).mean())
        # error de calibración: |frecuencia observada − probabilidad| por decil
        bins = np.clip((p.ravel() * 10).astype(int), 0, 9)
        real = np.zeros_like(p, dtype=float)
        real[np.arange(len(res)), res] = 1.0
        ece = 0.0
        for b in range(10):
            m = bins == b
            if m.sum() > 30:
                ece += m.sum() / len(bins) * abs(
                    p.ravel()[m].mean() - real.ravel()[m].mean())
        out[nombre] = {'log_loss': round(ll, 5), 'precision': round(acc, 4),
                       'ece': round(float(ece), 5)}
    print(f'\n{etiqueta}  (n={len(res)})')
    print(f"  {'método':22s} {'log-loss':>10} {'precisión':>10} {'ECE':>9}")
    print('  ' + '-' * 54)
    mejor = min(out, key=lambda k: out[k]['log_loss'])
    for k, v in sorted(out.items(), key=lambda kv: kv[1]['log_loss']):
        marca = '  <-- mejor' if k == mejor else ''
        print(f"  {k:22s} {v['log_loss']:10.5f} {v['precision']:10.4f} "
              f"{v['ece']:9.5f}{marca}")
    return out, mejor


def main():
    d = pd.read_csv(LEDGER, low_memory=False)
    salida = {}

    # --- fútbol: 3 vías, con la cuota de cierre genérica ---
    f = d[(d['deporte'] == 'Fútbol') &
          d[['cuota_home', 'cuota_draw', 'cuota_away']].notna().all(axis=1)]
    cu = f[['cuota_home', 'cuota_draw', 'cuota_away']].values.astype(float)
    ok = (cu > 1).all(axis=1)
    salida['futbol_cierre'], m1 = evaluar(cu[ok],
                                          f['resultado'].values[ok].astype(int),
                                          'FÚTBOL · cierre genérico (3 vías)')

    # --- fútbol: 3 vías, con Pinnacle ---
    g = d[(d['deporte'] == 'Fútbol') &
          d[['pin_home', 'pin_draw', 'pin_away']].notna().all(axis=1)]
    if len(g) > 1000:
        cu = g[['pin_home', 'pin_draw', 'pin_away']].values.astype(float)
        ok = (cu > 1).all(axis=1)
        salida['futbol_pinnacle'], m2 = evaluar(
            cu[ok], g['resultado'].values[ok].astype(int),
            'FÚTBOL · Pinnacle (3 vías)')

    # --- dos vías (tenis y MLB) ---
    h = d[(d['deporte'] != 'Fútbol') &
          d[['cuota_home', 'cuota_away']].notna().all(axis=1)]
    if len(h) > 1000:
        cu = h[['cuota_home', 'cuota_away']].values.astype(float)
        ok = (cu > 1).all(axis=1)
        # resultado 0 = gana el primero, 2 = gana el segundo -> a 0/1
        r = (h['resultado'].values[ok] == 2).astype(int)
        salida['dos_vias'], m3 = evaluar(cu[ok], r, 'TENIS y MLB (2 vías)')

    print('\n' + '=' * 60)
    print('Lectura: en mercados de 2 vías todos los métodos convergen (con dos')
    print('salidas apenas hay margen que repartir de forma distinta). La')
    print('diferencia, si la hay, está en el 1X2.')
    json.dump(salida, open('_v80_devig.json', 'w', encoding='utf-8'),
              indent=1, ensure_ascii=False)


if __name__ == '__main__':
    main()
