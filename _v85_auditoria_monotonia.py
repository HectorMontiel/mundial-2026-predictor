#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v85 — ¿Responde el modelo de cada liga a la fuerza de los equipos?

El síntoma
----------
En Liga MX el modelo hace favorito a Puebla (53,6 %) sobre Chivas, y TODAS las
señales dicen lo contrario:

    ELO         Puebla 1349   ·  Chivas 1597    (−248)
    Goles a favor (MA5)   0,83  ·  1,17
    Goles en contra (MA5) 2,17  ·  1,00
    Forma (MA5)           0,17  ·  0,58
    H2H                  −0,67 para Puebla

El vector de features que llega al modelo es correcto: DIFF_ELO −0,62,
DIFF_FORMA −0,42, DIFF_GA +1,17. O sea que los datos están bien y el que no
responde es el ESTIMADOR.

La prueba
---------
Una propiedad que cualquier modelo de fútbol tiene que cumplir, y que no
depende de acertar: **si el local es mucho más fuerte, su probabilidad de ganar
debe ser mayor que si es mucho más débil**. Es monotonía respecto a la fuerza,
no precisión.

Se mide con la correlación de Spearman entre la diferencia de ELO y la
probabilidad de victoria local, sobre todos los emparejamientos posibles de
cada liga. Un modelo sano da correlación alta y positiva. Cerca de cero
significa que el modelo ignora quién es mejor; negativa, que lo invierte.

Se comprueba además la **coherencia local/visitante**: si A es más fuerte que
B, P(A gana en casa de A) debe superar a P(B gana en casa de B). Un modelo que
falle esto está roto con independencia de su log-loss.

Esto es escalable: corre sobre TODAS las ligas, no sobre el partido que se
reportó.
"""
import json
import logging
import sys

import numpy as np

# La consola de Windows es cp1252 y ya ha tumbado CUATRO análisis de esta
# sesión al imprimir «Δ», «↔» o «→» DESPUÉS de calcular los resultados. Se
# fuerza UTF-8 al arrancar: perder diez minutos de cómputo por un carácter es
# el fallo más tonto y más caro que se puede cometer aquí.
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

logging.basicConfig(level=logging.WARNING)
log = logging.getLogger('monotonia')

MAX_EQUIPOS = 14          # 14 equipos -> 182 emparejamientos por liga


def auditar(clave):
    import league_engine
    from scipy.stats import spearmanr
    try:
        e = league_engine.ClubEngine(clave)
    except Exception as ex:
        return {'liga': clave, 'error': f'{type(ex).__name__}: {ex}'}
    if not getattr(e, 'listo', False):
        return {'liga': clave, 'error': 'motor no listo'}
    equipos = [t for t in e.stats
               if isinstance(e.stats[t], dict) and e.stats[t].get('ELO')]
    if len(equipos) < 6:
        return {'liga': clave, 'error': f'solo {len(equipos)} equipos con ELO'}
    equipos = sorted(equipos, key=lambda t: -e.stats[t]['ELO'])[:MAX_EQUIPOS]

    d_elo, p_home = [], []
    fallos_orden = 0
    comparaciones = 0
    for i, a in enumerate(equipos):
        for b in equipos:
            if a == b:
                continue
            r = e.predecir(a, b)
            if 'error' in r:
                continue
            pr = r['prediction']['probabilities']
            d_elo.append(e.stats[a]['ELO'] - e.stats[b]['ELO'])
            p_home.append(pr['home'])

    if len(d_elo) < 20:
        return {'liga': clave, 'error': 'muestra insuficiente'}
    rho, pval = spearmanr(d_elo, p_home)

    # coherencia: el fuerte en casa debe superar al débil en casa
    fuerte, debil = equipos[0], equipos[-1]
    pf = e.predecir(fuerte, debil)['prediction']['probabilities']['home']
    pd_ = e.predecir(debil, fuerte)['prediction']['probabilities']['home']
    coherente = pf > pd_

    # ¿cuánto se mueve la probabilidad? un modelo que ignora la fuerza da un
    # rango minúsculo
    rango = float(np.max(p_home) - np.min(p_home))
    return {'liga': clave, 'n': len(d_elo), 'rho_elo': round(float(rho), 4),
            'p_valor': float(pval), 'rango_p_home': round(rango, 4),
            'fuerte_en_casa': round(float(pf), 3),
            'debil_en_casa': round(float(pd_), 3),
            'coherente': bool(coherente),
            'sano': bool(rho > 0.5 and coherente and rango > 0.15)}


def main():
    import config
    claves = [c for c, cfg in config.LEAGUES.items()
              if cfg.get('disponible', True)]
    log.warning(f'auditando {len(claves)} ligas...')
    out = []
    for c in claves:
        try:
            r = auditar(c)
        except Exception as ex:
            r = {'liga': c, 'error': f'{type(ex).__name__}: {ex}'}
        out.append(r)
        est = ('ERROR' if r.get('error') else
               ('OK' if r.get('sano') else 'REVISAR'))
        print(f"{r['liga']:24s} {est:8s} "
              f"rho={r.get('rho_elo', float('nan')):>7} "
              f"rango={r.get('rango_p_home', float('nan')):>7} "
              f"coherente={r.get('coherente')} "
              f"{r.get('error', '')}")

    validos = [r for r in out if not r.get('error')]
    sanos = [r for r in validos if r.get('sano')]
    print('\n' + '=' * 78)
    print(f'{len(validos)} ligas auditadas · {len(sanos)} sanas · '
          f'{len(validos) - len(sanos)} a revisar')
    if validos:
        rhos = [r['rho_elo'] for r in validos]
        print(f'correlación ELO↔P(local): mediana {np.median(rhos):.3f} · '
              f'mínima {min(rhos):.3f} · máxima {max(rhos):.3f}')
    malas = sorted([r for r in validos if not r.get('sano')],
                   key=lambda r: r['rho_elo'])
    if malas:
        print('\nLigas que NO responden a la fuerza de los equipos:')
        for r in malas:
            print(f"  {r['liga']:22s} rho={r['rho_elo']:+.3f} "
                  f"rango={r['rango_p_home']:.3f} "
                  f"coherente={r['coherente']} "
                  f"(fuerte en casa {r['fuerte_en_casa']} vs "
                  f"débil en casa {r['debil_en_casa']})")
    json.dump(out, open('_v85_auditoria_monotonia.json', 'w', encoding='utf-8'),
              indent=1, ensure_ascii=False, default=float)


if __name__ == '__main__':
    main()
