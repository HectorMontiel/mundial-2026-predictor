#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v126 — Barrido de las 57 ligas: cuáles merecen un reentrenamiento y cuáles no.

Por qué existe
--------------
La alternativa era elegir a ojo las ligas «que parecen malas». Eso ya se
demostró que engaña: la Premier acierta un 45,5 % y parece la peor de todas,
pero el techo del mercado en esa liga es 45,9 % — está a cuatro décimas de la
mejor casa del mundo y no hay nada que rascar. La MLS acierta más (47,5 %) y
sin embargo tiene tres puntos de margen.

Lo que decide no es el acierto: es la DISTANCIA AL TECHO de cada liga.

Los tres filtros
----------------
Una liga entra en la cola de reentrenamiento sólo si pasa los tres:

  1. MARGEN  · `techo_mercado − precision_validacion > 1,5 pts`
     Si el modelo ya está pegado al mercado, no hay hueco que ganar.

  2. VOLUMEN · más de 1.500 partidos en el histórico
     Por debajo, una mejora de dos puntos es indistinguible de una racha.

  3. p5 DEL ROI · el percentil 5 del bootstrap sobre el ROI simulado
     Es la regla de oro del proyecto: nada se despliega sin p5 positivo en un
     tramo que no se usó para elegir los parámetros. Aquí se usa como filtro
     de PRIORIDAD, no de despliegue: una liga cuyo p5 está muy lejos de cero
     no va a cruzarlo por reentrenar un poco.

CÓMO SE CALCULA EL p5, Y QUÉ SUPONE
-----------------------------------
El metadata guarda `n_apuestas`, `aciertos` y `roi_pct`, pero no el retorno de
cada apuesta. De esas tres cifras se reconstruye la cuota media:

    roi = (aciertos·(c̄−1) − (n−aciertos)) / n   →   c̄ = n·(1+roi) / aciertos

y se remuestrea un Bernoulli con p = aciertos/n. Eso captura la variabilidad
del acierto, que es la fuente dominante.

**Lo que NO captura**: la dispersión de las cuotas. Todas las apuestas se
tratan como si tuvieran la misma cuota media, así que el intervalo sale algo
más ESTRECHO de lo real — o sea, el p5 calculado aquí es ligeramente
OPTIMISTA. Se dice porque una liga que no pasa el filtro con un p5 optimista,
mucho menos lo pasaría con el real.

Uso:
    python barrido_ligas.py              # tabla por pantalla
    python barrido_ligas.py --json       # además escribe barrido_ligas.json
"""
import glob
import json
import os
import sys

import numpy as np

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

MARGEN_MINIMO = 0.015        # 1,5 puntos contra el techo del mercado
PARTIDOS_MINIMO = 1500
N_BOOTSTRAP = 4000
ARCHIVO = 'barrido_ligas.json'


def p5_bootstrap(n_apuestas, aciertos, roi_pct, semilla: int = 7):
    """
    Percentil 5 del ROI, remuestreando el acierto. None si no hay con qué.

    Ver el encabezado para el supuesto de cuota media constante y por qué el
    resultado es ligeramente optimista.
    """
    try:
        n = int(n_apuestas)
        a = int(aciertos)
        roi = float(roi_pct) / 100.0
    except (TypeError, ValueError):
        return None
    if n < 30 or a <= 0 or a > n:
        return None
    cuota_media = n * (1.0 + roi) / a
    if not (1.0 < cuota_media < 100.0):
        return None
    rng = np.random.default_rng(semilla)
    p = a / n
    exitos = rng.binomial(n, p, N_BOOTSTRAP)
    rois = (exitos * (cuota_media - 1.0) - (n - exitos)) / n
    return float(np.percentile(rois, 5))


def n_partidos(liga: str, meta: dict) -> int:
    """Partidos del histórico. El metadata es la fuente rápida; el CSV, la real."""
    ruta = f'historico_{liga}.csv'
    if os.path.exists(ruta):
        try:
            with open(ruta, encoding='utf-8', errors='replace') as f:
                return max(sum(1 for _ in f) - 1, 0)
        except Exception:
            pass
    try:
        return int(meta.get('n_train', 0)) + int(meta.get('n_validacion', 0))
    except (TypeError, ValueError):
        return 0


def barrer() -> list:
    """Una fila por liga con modelo, con sus tres filtros resueltos."""
    filas = []
    for f in sorted(glob.glob(os.path.join('modelos', '*', 'metadata.json'))):
        liga = os.path.basename(os.path.dirname(f))
        try:
            m = json.load(open(f, encoding='utf-8'))
        except Exception:
            continue
        pv = m.get('precision_validacion')
        if not pv:
            continue
        mk = m.get('precision_mercado_cuotas')
        roi = m.get('roi_sim') or {}
        margen = (float(mk) - float(pv)) if mk else None
        n_p = n_partidos(liga, m)
        p5 = p5_bootstrap(roi.get('n_apuestas'), roi.get('aciertos'),
                          roi.get('roi_pct'))
        # Los tres filtros, cada uno con su motivo cuando falla
        motivos = []
        if margen is None:
            motivos.append('sin referencia de mercado para medir el margen')
        elif margen <= MARGEN_MINIMO:
            motivos.append(f'margen {margen*100:+.1f} pts, por debajo de '
                           f'{MARGEN_MINIMO*100:.1f}')
        if n_p <= PARTIDOS_MINIMO:
            motivos.append(f'{n_p} partidos, por debajo de {PARTIDOS_MINIMO}')
        if p5 is None:
            motivos.append('sin ROI simulado con el que estimar el p5')
        elif p5 <= 0:
            motivos.append(f'p5 {p5*100:+.1f} %, no llega a positivo')
        filas.append({
            'liga': liga,
            'precision': round(float(pv), 4),
            'techo_mercado': round(float(mk), 4) if mk else None,
            'margen': round(margen, 4) if margen is not None else None,
            'partidos': n_p,
            'roi_sim': roi.get('roi_pct'),
            'n_apuestas': roi.get('n_apuestas'),
            'p5': round(p5, 4) if p5 is not None else None,
            'pasa': not motivos,
            'motivos': motivos,
        })
    # Prioridad: primero las que pasan, y dentro de ellas por p5 (que es el
    # filtro que de verdad decide) y luego por margen.
    filas.sort(key=lambda r: (not r['pasa'],
                              -(r['p5'] if r['p5'] is not None else -9),
                              -(r['margen'] or -9)))
    return filas


def main() -> int:
    filas = barrer()
    if not filas:
        print('No hay modelos con metadata que barrer.')
        return 1

    print(f'{len(filas)} ligas con modelo entrenado\n')
    print(f"{'liga':22} {'prec':>6} {'techo':>6} {'margen':>7} "
          f"{'partidos':>9} {'ROI sim':>8} {'p5':>8}  filtros")
    print('-' * 100)
    for r in filas:
        marca = '✅' if r['pasa'] else '  '
        print(f"{marca} {r['liga']:20} {r['precision']*100:5.1f} "
              f"{(r['techo_mercado'] or 0)*100:5.1f} "
              f"{(r['margen'] or 0)*100:+6.1f} {r['partidos']:9,} "
              f"{(r['roi_sim'] if r['roi_sim'] is not None else float('nan')):+7.2f} "
              f"{(r['p5']*100 if r['p5'] is not None else float('nan')):+7.2f}  "
              f"{'; '.join(r['motivos'])[:44]}".replace(',', '.'))

    cola = [r for r in filas if r['pasa']]
    print()
    print('=' * 100)
    print(f'EN LA COLA DE REENTRENAMIENTO: {len(cola)} de {len(filas)}')
    for r in cola:
        print(f"   {r['liga']:20} margen {r['margen']*100:+.1f} pts · "
              f"{r['partidos']:,} partidos · p5 {r['p5']*100:+.2f} %"
              .replace(',', '.'))
    if not cola:
        print('   Ninguna liga pasa los tres filtros.')
        # El filtro pedía «p5 > 0 o lo más cercano posible». Si nadie llega a
        # positivo, se dice y se enseña quién queda más cerca — pero sin
        # ascenderlo a «apto», que sería justo el atajo que este filtro existe
        # para impedir.
        cerca = [r for r in filas if r['p5'] is not None]
        cerca.sort(key=lambda r: -r['p5'])
        if cerca:
            print()
            print('   Las más cercanas a un p5 positivo (NINGUNA lo alcanza):')
            for r in cerca[:5]:
                print(f"      {r['liga']:20} p5 {r['p5']*100:+7.2f} % · "
                      f"margen {(r['margen'] or 0)*100:+.1f} pts · "
                      f"{r['partidos']:,} partidos".replace(',', '.'))

    # LA RELACIÓN QUE DECIDE SI ESTE PLAN TIENE SENTIDO.
    #
    # Si las ligas con más margen fueran las de mejor p5, especializarlas sería
    # el camino evidente. Medido, la relación es la CONTRARIA: el margen mide
    # lo malo que es el modelo en esa liga, y apostar un modelo malo pierde
    # más. Mejorarlo dos puntos no lo vuelve rentable: lo vuelve menos malo.
    import numpy as _np
    _m = [r['margen'] for r in filas
          if r['margen'] is not None and r['p5'] is not None]
    _q = [r['p5'] for r in filas
          if r['margen'] is not None and r['p5'] is not None]
    if len(_m) > 5:
        print()
        print(f'Correlación entre margen y p5 sobre {len(_m)} ligas: '
              f'{_np.corrcoef(_m, _q)[0, 1]:+.3f}')
        print('   Negativa = donde más margen hay para mejorar el modelo, peor '
              'se comporta apostarlo.')

    # cuántas caen por cada motivo, que es lo que dice si el filtro es útil
    print()
    print('Por qué caen las demás:')
    for clave, etq in (('margen', 'margen insuficiente contra el mercado'),
                       ('partidos', 'muestra por debajo de 1.500 partidos'),
                       ('p5', 'sin ROI simulado para estimar el p5')):
        n = sum(1 for r in filas if not r['pasa']
                and any(clave in mo or etq.split()[0] in mo
                        for mo in r['motivos']))
        print(f'   {etq:45} {n:3}')

    if '--json' in sys.argv:
        with open(ARCHIVO, 'w', encoding='utf-8') as f:
            json.dump({'filtros': {'margen_minimo': MARGEN_MINIMO,
                                   'partidos_minimo': PARTIDOS_MINIMO,
                                   'p5_minimo': 0.0},
                       'ligas': filas}, f, ensure_ascii=False, indent=1)
        print(f'\n{ARCHIVO} escrito ({len(cola)} en cola).')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
