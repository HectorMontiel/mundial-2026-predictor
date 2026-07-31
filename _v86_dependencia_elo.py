#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v86 — ¿Responde el modelo al ELO? Dependencia parcial por el camino REAL.

Por qué esta prueba y no la de v85
----------------------------------
v85 midió la correlación ELO↔P(local) sobre todos los emparejamientos posibles
de los 14 mejores equipos de cada liga. Eso tiene dos defectos que fabrican el
resultado:

  1. Al quedarse con los 14 mejores, el rango de ELO se COMPRIME mientras que
     las features de forma siguen variando a rango completo. La correlación
     mide entonces sobre todo la forma, por construcción.
  2. Son partidos inventados con el estado de HOY: puntos fuera de la nube en
     la que se entrenó el modelo.

Sobre el ledger real (_v86_monotonia_real.py) no hay ni una liga invertida y la
mediana de rho es +0,76. Las dos mediciones se contradicen, así que hace falta
un desempate que no dependa de correlaciones.

La prueba
---------
Se coge un par de equipos y se llama a `ClubEngine.predecir` —el camino EXACTO
que alimenta la ficha que ve el usuario— varias veces, cambiando ÚNICAMENTE el
ELO del local y dejando congelado todo lo demás (forma, goles, xG, H2H...).

Si P(local) sube al subir el ELO, el modelo responde a la fuerza. Es una
medición causal dentro del modelo: no la puede falsear ni el rango de la
muestra ni la colinealidad entre features.
"""
import copy
import json
import sys

import numpy as np

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

# Puntos de ELO que se suman al local respecto a su valor real.
DELTAS = np.array([-300.0, -200.0, -100.0, 0.0, 100.0, 200.0, 300.0])
N_PARES = 25


def dependencia(clave: str) -> dict:
    import league_engine as le

    try:
        e = le.ClubEngine(clave)
    except Exception as ex:
        return {'liga': clave, 'error': f'{type(ex).__name__}: {ex}'}
    if not getattr(e, 'listo', False):
        return {'liga': clave, 'error': 'motor no listo'}

    equipos = [t for t in e.stats
               if isinstance(e.stats[t], dict) and e.stats[t].get('ELO')]
    if len(equipos) < 6:
        return {'liga': clave, 'error': f'solo {len(equipos)} equipos'}

    rng = np.random.default_rng(86)
    pares = [(a, b) for a in equipos for b in equipos if a != b]
    if len(pares) > N_PARES:
        pares = [pares[i] for i in
                 rng.choice(len(pares), N_PARES, replace=False)]

    curvas = []
    for home, away in pares:
        original = e.stats[home]['ELO']
        fila = []
        try:
            for d in DELTAS:
                e.stats[home] = dict(e.stats[home], ELO=original + d)
                r = e.predecir(home, away)
                if 'error' in r:
                    fila = None
                    break
                fila.append(float(r['prediction']['probabilities']['home']))
        finally:
            e.stats[home] = dict(e.stats[home], ELO=original)
        if fila and not any(np.isnan(fila)):
            curvas.append(fila)

    if len(curvas) < 5:
        return {'liga': clave, 'error': f'solo {len(curvas)} curvas'}

    C = np.array(curvas)
    media = C.mean(axis=0)
    salto = float(media[-1] - media[0])
    dif = np.diff(C, axis=1)
    crecientes = int(np.sum(np.all(dif >= -1e-9, axis=1)))
    decrecientes = int(np.sum(np.all(dif <= 1e-9, axis=1)))
    # salto individual por curva, para ver la dispersión
    saltos_ind = (C[:, -1] - C[:, 0])
    return {'liga': clave, 'n_curvas': len(C),
            'curva_media': [round(float(x), 4) for x in media],
            'salto': round(salto, 4),
            'salto_min': round(float(saltos_ind.min()), 4),
            'salto_max': round(float(saltos_ind.max()), 4),
            'pct_crecientes': round(crecientes / len(C) * 100, 1),
            'pct_decrecientes': round(decrecientes / len(C) * 100, 1),
            'pct_salto_negativo': round(float((saltos_ind < 0).mean() * 100), 1)}


def main():
    import config
    claves = [c for c, cfg in config.LEAGUES.items() if cfg.get('disponible', True)]

    print('=' * 96)
    print('v86 · DEPENDENCIA PARCIAL DE P(local) RESPECTO AL ELO')
    print('   camino real (ClubEngine.predecir); se mueve SOLO el ELO del local')
    print('   rejilla: -300 -200 -100  0  +100 +200 +300 puntos de ELO')
    print('=' * 96)
    print(f'{"liga":22s} {"n":>4} {"curva media de P(local)":>36} '
          f'{"salto":>8} {"%crec":>7} {"%neg":>6}')
    print('-' * 96)

    out = []
    for c in claves:
        try:
            r = dependencia(c)
        except Exception as ex:
            r = {'liga': c, 'error': f'{type(ex).__name__}: {ex}'}
        out.append(r)
        if r.get('error'):
            print(f'{c:22s} {"":>4} ERROR {r["error"][:56]}')
            continue
        txt = ' '.join(f'{x:.2f}' for x in r['curva_media'])
        if r['salto'] < -0.02:
            marca = '  <-- INVERTIDO'
        elif r['salto'] <= 0.02:
            marca = '  <-- NO RESPONDE'
        else:
            marca = ''
        print(f'{r["liga"]:22s} {r["n_curvas"]:4d} {txt:>36} '
              f'{r["salto"]:+8.3f} {r["pct_crecientes"]:6.1f}% '
              f'{r["pct_salto_negativo"]:5.1f}%{marca}')

    validos = [r for r in out if not r.get('error')]
    if not validos:
        print('sin ligas medidas')
        return
    saltos = np.array([r['salto'] for r in validos])
    print('-' * 96)
    print(f'{len(validos)} ligas medidas')
    print(f'salto mediano de P(local) al subir 600 pts de ELO: '
          f'{np.median(saltos):+.4f}')
    print(f'ligas que responden bien (salto > +0,02) : '
          f'{int((saltos > 0.02).sum())} de {len(saltos)}')
    print(f'ligas planas (|salto| <= 0,02)           : '
          f'{int((np.abs(saltos) <= 0.02).sum())}')
    print(f'ligas INVERTIDAS (salto < -0,02)         : '
          f'{int((saltos < -0.02).sum())}')
    pc = np.array([r['pct_crecientes'] for r in validos])
    print(f'% medio de curvas monótonas crecientes   : {pc.mean():.1f} %')

    malas = sorted([r for r in validos if r['salto'] <= 0.02],
                   key=lambda r: r['salto'])
    if malas:
        print('\nLigas cuyo modelo NO responde al ELO:')
        for r in malas:
            print(f'  {r["liga"]:22s} salto {r["salto"]:+.4f} '
                  f'(curvas crecientes {r["pct_crecientes"]}%, '
                  f'rango individual {r["salto_min"]:+.3f}..{r["salto_max"]:+.3f})')

    json.dump(out, open('_v86_dependencia_elo.json', 'w', encoding='utf-8'),
              indent=1, ensure_ascii=False, default=float)
    print('\nGuardado en _v86_dependencia_elo.json')


if __name__ == '__main__':
    main()
