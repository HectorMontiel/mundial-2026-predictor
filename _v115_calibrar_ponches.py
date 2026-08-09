#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v115 — ¿Está bien calibrada la probabilidad de ponches que enseña la app?

El usuario apostó cinco líneas de ponches y acertó una. Eso no demuestra por sí
solo que el modelo esté mal —cinco apuestas no son una muestra— pero sí obliga
a comprobarlo, porque la app publica frases como «P(más de 2.5) = 71 %» y una
probabilidad publicada es una promesa que hay que poder auditar.

Qué se mide
-----------
`beisbol_pitchers.prob_over_ponches` usa una **Poisson**. Esa elección tiene una
consecuencia fuerte y comprobable: la Poisson impone varianza = media. Si los
ponches por apertura están SOBREDISPERSOS (varianza mayor que la media, que es
lo habitual en conteos con duración variable — un abridor puede irse en la 3ª
entrada o llegar a la 7ª), entonces:

  · para líneas POR ENCIMA de la media, la Poisson infravalora la cola alta y
    subestima P(over);
  · para líneas POR DEBAJO, la sobrestima.

Las líneas que la app recomienda son justo las bajas (la regla del usuario sólo
toma ponches cuando la línea es de 6 o menos), así que un sesgo ahí se traduce
en apuestas emitidas con una probabilidad inflada.

Cómo
----
Se descargan los registros por juego (`gameLog` de MLB StatsAPI, una petición
por lanzador) de los abridores con más aperturas de la temporada. De cada
apertura se toman los ponches reales. Con eso:

  1. sobredispersión: varianza/media de K por apertura, por lanzador y global;
  2. calibración: para cada apertura, se estima λ con las OTRAS aperturas de
     ese lanzador (fuera de muestra, sin mirar el resultado que se juzga), se
     calcula P(K > línea) con la Poisson y se compara con lo que pasó de
     verdad, agrupando por bandas de probabilidad.

Si la Poisson dice «71 %» y en esa banda se cumple el 55 %, está inflando, y la
cifra que se enseña en la app hay que corregirla o dejar de enseñarla.

    python _v115_calibrar_ponches.py [n_lanzadores]
"""
import json
import math
import statistics
import sys
from typing import Dict, List

import requests

for _f in (sys.stdout, sys.stderr):
    try:
        _f.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

API = 'https://statsapi.mlb.com/api/v1'
TEMPORADA = 2026
# Una apertura de verdad: por debajo de 3 entradas es un relevo largo o una
# salida temprana, y mezclarlos con las aperturas contamina la media.
IP_MINIMA = 3.0


def _get(url, params):
    try:
        r = requests.get(url, params=params, timeout=30)
        if r.status_code != 200:
            return {}
        return r.json()
    except Exception:
        return {}


def _ip(txt) -> float:
    """«6.2» en béisbol son 6 entradas y 2 outs, no 6,2."""
    try:
        entero, _, tercios = str(txt).partition('.')
        return float(entero) + (float(tercios or 0) / 3.0)
    except Exception:
        return 0.0


def aperturas_de(pid: int) -> List[Dict]:
    j = _get(f'{API}/people/{pid}/stats',
             {'stats': 'gameLog', 'season': TEMPORADA, 'group': 'pitching'})
    fuera = []
    for s in ((j.get('stats') or [{}])[0].get('splits') or []):
        st = s.get('stat') or {}
        ip = _ip(st.get('inningsPitched'))
        if ip < IP_MINIMA:
            continue
        try:
            k = int(st.get('strikeOuts'))
            bf = int(st.get('battersFaced') or 0)
        except (TypeError, ValueError):
            continue
        fuera.append({'fecha': s.get('date'), 'k': k, 'ip': ip, 'bf': bf})
    return fuera


def poisson_mayor_que(lam: float, linea: float) -> float:
    """P(K > línea) con Poisson; la línea es de .5, así que no hay empate."""
    if lam <= 0:
        return 0.0
    techo = int(math.floor(linea))
    acum, termino = 0.0, math.exp(-lam)
    for k in range(0, techo + 1):
        if k:
            termino *= lam / k
        acum += termino
    return max(0.0, min(1.0, 1.0 - acum))


def main() -> int:
    n_lanzadores = int(sys.argv[1]) if len(sys.argv) > 1 else 60
    print('=' * 78)
    print('v115 — CALIBRACIÓN DE LA PROBABILIDAD DE PONCHES')
    print('=' * 78)

    j = _get(f'{API}/sports/1/players', {'season': TEMPORADA})
    gente = [p for p in (j.get('people') or [])
             if (p.get('primaryPosition') or {}).get('abbreviation') == 'P']
    print(f'lanzadores en la temporada {TEMPORADA}: {len(gente)}')

    datos: Dict[str, List[Dict]] = {}
    ids: Dict[str, int] = {}
    for p in gente:
        if len(datos) >= n_lanzadores:
            break
        ap = aperturas_de(p['id'])
        if len(ap) >= 8:            # muestra mínima para estimar su media
            datos[p['fullName']] = ap
            ids[p['fullName']] = p['id']
            sys.stdout.write(f'\r  descargando… {len(datos)}/{n_lanzadores}')
            sys.stdout.flush()
    print()
    if not datos:
        print('sin datos suficientes')
        return 1
    total_ap = sum(len(v) for v in datos.values())
    print(f'{len(datos)} abridores · {total_ap} aperturas de {IP_MINIMA}+ entradas')

    # ---- 1. sobredispersión ---------------------------------------------
    print('\n' + '-' * 78)
    print('1. ¿VARIANZA = MEDIA? (lo que la Poisson da por supuesto)')
    print('-' * 78)
    ratios = []
    for nombre, ap in datos.items():
        ks = [a['k'] for a in ap]
        if len(ks) < 8 or statistics.mean(ks) <= 0:
            continue
        ratios.append(statistics.variance(ks) / statistics.mean(ks))
    if ratios:
        print(f'  ratio varianza/media por lanzador: '
              f'mediana {statistics.median(ratios):.3f} · '
              f'media {statistics.mean(ratios):.3f} '
              f'(n={len(ratios)})')
        print(f'  lanzadores con sobredispersión (>1): '
              f'{sum(1 for r in ratios if r > 1)}/{len(ratios)}')
        print('  → 1,00 sería Poisson exacta. Por encima, la Poisson estrecha '
              'de más\n    la distribución y se equivoca en las dos colas.')

    # ---- 2. calibración fuera de muestra --------------------------------
    print('\n' + '-' * 78)
    print('2. CALIBRACIÓN: lo que promete la Poisson contra lo que pasó')
    print('-' * 78)
    print('  λ de cada apertura estimado con las OTRAS aperturas del mismo')
    print('  lanzador (nunca con la que se juzga).')
    bandas = {}
    lineas_probadas = (2.5, 3.5, 4.5, 5.5, 6.5)
    for nombre, ap in datos.items():
        ks = [a['k'] for a in ap]
        for i, a in enumerate(ap):
            otros = ks[:i] + ks[i + 1:]
            if len(otros) < 6:
                continue
            lam = statistics.mean(otros)
            for linea in lineas_probadas:
                p = poisson_mayor_que(lam, linea)
                if p < 0.05 or p > 0.95:
                    continue                # extremos: no informan
                banda = int(p * 10) * 10
                d = bandas.setdefault(banda, {'n': 0, 'aciertos': 0,
                                              'suma_p': 0.0})
                d['n'] += 1
                d['suma_p'] += p
                d['aciertos'] += 1 if a['k'] > linea else 0
    print(f"\n  {'banda':<12}{'promete':>10}{'cumple':>10}{'n':>8}   sesgo")
    total_n = total_prom = total_ac = 0
    for banda in sorted(bandas):
        d = bandas[banda]
        if d['n'] < 25:
            continue
        prom = d['suma_p'] / d['n']
        real = d['aciertos'] / d['n']
        total_n += d['n']
        total_prom += d['suma_p']
        total_ac += d['aciertos']
        print(f"  {banda:>3}-{banda+10:<8}{prom*100:>9.1f}%{real*100:>9.1f}%"
              f"{d['n']:>8}   {(real-prom)*100:+.1f} pts")
    if total_n:
        prom = total_prom / total_n
        real = total_ac / total_n
        print(f"\n  GLOBAL: promete {prom*100:.1f} %, cumple {real*100:.1f} % "
              f"({total_n} evaluaciones)")
        print(f"  → sesgo medio: {(real-prom)*100:+.2f} puntos")
        if real < prom - 0.02:
            print('  ⚠️ La Poisson INFLA la probabilidad: lo que la app enseña')
            print('     como «71 % de acertar» se cumple menos.')
        elif real > prom + 0.02:
            print('  La Poisson se queda CORTA.')
        else:
            print('  ✅ Dentro de ±2 puntos: la Poisson describe bien estas '
                  'líneas.')

    # ---- 3. el λ del modelo contra la realidad ---------------------------
    #
    # El apartado 2 valida la DISTRIBUCIÓN dado un λ correcto. Pero la app no
    # usa la media real del lanzador: la estima con `ponches_esperados` (K por
    # bateador × bateadores enfrentados, ajustado por rival y parque). Si ese
    # λ está sesgado, la probabilidad sale mal aunque la Poisson sea perfecta —
    # y es el λ, no la Poisson, lo que decide la apuesta.
    print('\n' + '-' * 78)
    print('3. EL λ DEL MODELO CONTRA LA MEDIA REAL DE CADA ABRIDOR')
    print('-' * 78)
    try:
        import beisbol_pitchers as bp
        perfiles = True
    except Exception as e:
        perfiles = None
        print(f'  no se pudo cargar el modelo de abridores ({type(e).__name__}: {e})')
    if perfiles:
        difs = []
        for nombre, ap in datos.items():
            real = statistics.mean([a['k'] for a in ap])
            try:
                perfil = bp.perfil_pitcher(ids.get(nombre))
                if not perfil:
                    continue
                # rival neutro: se compara la CAPACIDAD del abridor, no el
                # cruce concreto, que es lo que aquí toca aislar
                lam = bp.ponches_esperados(perfil, rival='__neutro__')
            except Exception:
                continue
            if not lam:
                continue
            difs.append((lam - real, lam, real, nombre))
        if difs:
            solo = [d[0] for d in difs]
            print(f'  abridores comparables: {len(difs)}')
            print(f'  sesgo medio del λ: {statistics.mean(solo):+.3f} ponches '
                  f'(mediana {statistics.median(solo):+.3f})')
            print(f'  error absoluto medio: '
                  f'{statistics.mean([abs(x) for x in solo]):.3f} ponches')
            difs.sort()
            print('  los más desviados:')
            for d, lam, real, nombre in difs[:3] + difs[-3:]:
                print(f'    {nombre:<24} modelo {lam:.2f} · real {real:.2f} '
                      f'({d:+.2f})')
            if abs(statistics.mean(solo)) > 0.4:
                print('  ⚠️ El λ del modelo está sesgado más de 0,4 ponches: '
                      'eso sí\n     mueve la probabilidad publicada.')
            else:
                print('  ✅ El λ del modelo no muestra un sesgo relevante.')
        else:
            print('  ningún abridor de la muestra casa con el perfil del modelo')

    salida = {'lanzadores': len(datos), 'aperturas': total_ap,
              'dispersion_mediana': (statistics.median(ratios)
                                     if ratios else None),
              'bandas': {str(k): v for k, v in bandas.items()},
              'global': {'promete': (total_prom / total_n) if total_n else None,
                         'cumple': (total_ac / total_n) if total_n else None,
                         'n': total_n}}
    with open('_v115_calibracion_ponches.json', 'w', encoding='utf-8') as f:
        json.dump(salida, f, ensure_ascii=False, indent=2)
    print('\nDetalle en _v115_calibracion_ponches.json')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
