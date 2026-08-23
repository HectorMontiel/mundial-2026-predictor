#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v164 — ¿DE DÓNDE SALE LA APUESTA DESTACADA, Y CUÁNTAS SON ESTIMADAS?

El encargo dice que la destacada no puede salir de un mercado estimado. Antes
de cambiar la regla hay que saber DÓNDE está el problema, porque en la tarjeta
hay **dos cosas distintas** que se llaman «destacado» y no se arreglan igual:

  1. **El titular de la tarjeta** (`### ✅ Menos de 2.5 — 72 %`), que sale de
     `modo_modelo.apuesta_destacada` recorriendo `pick['mercados']`. Ésos los
     escribe `alpha_finder` y son 1X2, Goles, BTTS y hándicap: todos derivados
     de la matriz de marcador, o sea del modelo de GOLES, que se entrena con
     goles reales en todas las competiciones.

  2. **La insignia dentro de cada bloque físico**
     (`⛳ Córners estimado 🟡 destacado: Local Menos de 5.5 57 %`), que la pinta
     `_bloque_seccion_html` con el máximo de las filas de ESE bloque. Aquí sí
     puede haber estimación: en las competiciones sin datos observados,
     córners, tarjetas y remates salen del nivel de la liga derivado de sus
     goles.

Este script cuenta las dos sobre el barrido REAL del día y dice cuál de las dos
es la que el usuario está viendo, en vez de suponerlo.

    python _v164_auditar_destacada.py
"""
import json
import logging
import sys
import warnings
from collections import Counter

warnings.filterwarnings('ignore')
logging.basicConfig(level=logging.ERROR)
for _f in (sys.stdout, sys.stderr):
    try:
        _f.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

SALIDA = '_v164_auditar_destacada.json'


def main():
    import modo_modelo as mm

    try:
        import guardia_barrido
        r = guardia_barrido.resultado()
    except Exception:
        r = None
    if not r:
        import alpha_finder as af
        r = af.apuestas_del_dia_universal()

    pron = [p for p in (r.get('pronosticos') or [])
            if p.get('deporte') == 'Fútbol']
    print('%d pronósticos de fútbol en el barrido\n' % len(pron))

    # ---- 1) el titular de la tarjeta -------------------------------------
    print('=' * 78)
    print('1) EL TITULAR DE LA TARJETA (apuesta_destacada)')
    print('=' * 78)
    de_mercado = Counter()
    con_dest = 0
    for p in pron:
        d = mm.apuesta_destacada(p)
        if not d:
            continue
        con_dest += 1
        de_mercado[d.get('mercado') or '(del board)'] += 1
    print('%d de %d partidos tienen titular' % (con_dest, len(pron)))
    for k, v in de_mercado.most_common():
        print('   %-18s %3d' % (k, v))
    print('\nNinguno de esos mercados es de córners, tarjetas ni remates: los '
          'escribe\n`alpha_finder` desde la matriz de marcador, que se entrena '
          'con goles REALES.')

    # ---- 2) las insignias de los bloques físicos -------------------------
    print()
    print('=' * 78)
    print('2) LAS INSIGNIAS DE LOS BLOQUES FÍSICOS')
    print('=' * 78)
    filas, por_liga = [], {}
    for p in pron:
        clave = p.get('clave_liga')
        bloques = {}
        try:
            bloques['corners'] = mm.corners_tarjeta(p)
            bloques['tarjetas'] = mm.tarjetas_tarjeta(p)
            rem = mm.remates_tarjeta(p) or {}
            bloques['remates'] = rem.get('totales')
            bloques['remates_on'] = rem.get('a_puerta')
        except Exception as e:
            logging.debug('%s: %s', clave, e)
        for nombre, b in bloques.items():
            if not b:
                continue
            origen = b.get('origen') or 'observado'
            mejor = b.get('mejor') or {}
            conf = b.get('confianza') or {}
            filas.append({'clave_liga': clave, 'partido': p.get('partido'),
                          'bloque': nombre, 'origen': origen,
                          'error': b.get('error_calibracion'),
                          'nivel': conf.get('nivel'),
                          'insignia': bool(conf.get('insignia')),
                          'destacado': mejor.get('texto'),
                          'prob': mejor.get('prob')})
            d = por_liga.setdefault(clave, Counter())
            d[origen] += 1

    con_ins = [f for f in filas if f.get('insignia')]
    sin_ins = [f for f in filas if not f.get('insignia')]
    print('CON insignia tras la regla nueva ... %4d' % len(con_ins))
    print('SIN insignia (nivel 3) ............. %4d' % len(sin_ins))
    niveles = Counter(f.get('nivel') for f in filas)
    for n_, c in sorted(niveles.items(), key=lambda kv: (kv[0] or 9)):
        print('   nivel %-4s %4d' % (n_, c))
    print()
    est = [f for f in filas if f['origen'] == 'estimado']
    obs = [f for f in filas if f['origen'] != 'estimado']
    print('%d bloques físicos pintados en total' % len(filas))
    print('   observados ... %4d' % len(obs))
    print('   ESTIMADOS .... %4d  <- antes de la v164 TODOS llevaban su '
          '«🟡 destacado:»' % len(est))
    if est:
        pmax = max(f['prob'] or 0 for f in est)
        print('   probabilidad más alta anunciada por un bloque estimado: '
              '%.0f %%' % (pmax * 100))
    print()
    print('competiciones con MÁS bloques estimados:')
    orden = sorted(por_liga.items(), key=lambda kv: -kv[1]['estimado'])
    for clave, c in orden[:12]:
        if not c['estimado']:
            continue
        print('   %-20s estimados %2d · observados %2d'
              % (clave, c['estimado'], c['observado']))

    # partidos donde TODOS los bloques físicos son estimados
    por_partido = {}
    for f in filas:
        por_partido.setdefault(f['partido'], []).append(f['origen'])
    todos_est = [k for k, v in por_partido.items()
                 if v and all(o == 'estimado' for o in v)]
    print()
    print('%d partidos en los que TODOS sus bloques físicos son estimados'
          % len(todos_est))
    for k in todos_est[:8]:
        print('   %s' % k)

    json.dump({'titular': dict(de_mercado), 'con_titular': con_dest,
               'partidos': len(pron), 'bloques': filas,
               'todos_estimados': todos_est},
              open(SALIDA, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('\nescrito %s' % SALIDA)
    return 0


if __name__ == '__main__':
    sys.exit(main())
