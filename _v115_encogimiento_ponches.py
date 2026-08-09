#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v115 — Cuánto hay que encoger el λ de ponches, medido.

`_v115_calibrar_ponches.py` dejó el diagnóstico: la Poisson está BIEN calibrada
(sesgo +0,45 puntos sobre 5.118 evaluaciones), pero el λ que le entrega el
modelo **sobreestima +0,50 ponches de media**, con casos de +2,77. Y un λ
inflado infla la probabilidad publicada: es lo que hace que la app recomiende
«más de X ponches» con un 71 % que no se cumple.

La causa es de manual y tiene arreglo de manual:

    k_bf = ponches / bateadores enfrentados      ← sin regresión a la media

Un abridor con 80 bateadores enfrentados puede tener un k_bf altísimo por azar.
Multiplicado por los ~24 bateadores de una apertura, ese ruido se convierte en
dos ponches de más. Los tres peores casos medidos —Andrew Álvarez, Ben Brown,
Shane Drohan— son exactamente lanzadores de muestra corta.

Aquí se busca el ENCOGIMIENTO que minimiza el error, con la fórmula estándar:

    k_bf_ajustado = (ponches + k_liga · m) / (bateadores + m)

`m` son «bateadores previos»: cuánta evidencia hace falta para creerse el dato
propio en vez de la media de la liga. Se prueba una rejilla y se elige por
error absoluto medio, no por sesgo — bajar el sesgo compensando errores en
direcciones opuestas no mejora ninguna apuesta concreta.

Se valida FUERA DE MUESTRA: el λ se compara contra la media real de aperturas
que no intervienen en el ajuste.

    python _v115_encogimiento_ponches.py [n_lanzadores]
"""
import json
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
IP_MINIMA = 3.0
REJILLA_M = (0, 50, 100, 150, 200, 300, 400, 600, 900)


def _get(url, params):
    try:
        r = requests.get(url, params=params, timeout=30)
        return r.json() if r.status_code == 200 else {}
    except Exception:
        return {}


def _ip(txt) -> float:
    try:
        e, _, t = str(txt).partition('.')
        return float(e) + (float(t or 0) / 3.0)
    except Exception:
        return 0.0


def aperturas_de(pid: int) -> List[Dict]:
    j = _get(f'{API}/people/{pid}/stats',
             {'stats': 'gameLog', 'season': TEMPORADA, 'group': 'pitching'})
    fuera = []
    for s in ((j.get('stats') or [{}])[0].get('splits') or []):
        st = s.get('stat') or {}
        if _ip(st.get('inningsPitched')) < IP_MINIMA:
            continue
        try:
            fuera.append({'k': int(st.get('strikeOuts')),
                          'bf': int(st.get('battersFaced') or 0)})
        except (TypeError, ValueError):
            continue
    return fuera


def main() -> int:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 60
    print('=' * 78)
    print('v115 — ENCOGIMIENTO DEL λ DE PONCHES')
    print('=' * 78)
    j = _get(f'{API}/sports/1/players', {'season': TEMPORADA})
    gente = [p for p in (j.get('people') or [])
             if (p.get('primaryPosition') or {}).get('abbreviation') == 'P']
    datos: Dict[str, List[Dict]] = {}
    for p in gente:
        if len(datos) >= n:
            break
        ap = aperturas_de(p['id'])
        if len(ap) >= 10:          # hacen falta dos mitades con muestra
            datos[p['fullName']] = ap
            sys.stdout.write(f'\r  descargando… {len(datos)}/{n}')
            sys.stdout.flush()
    print()
    if len(datos) < 10:
        print('muestra insuficiente')
        return 1

    # media de la liga de ponches por bateador enfrentado, sobre la muestra
    tot_k = sum(a['k'] for ap in datos.values() for a in ap)
    tot_bf = sum(a['bf'] for ap in datos.values() for a in ap)
    k_liga = tot_k / max(tot_bf, 1)
    print(f'{len(datos)} abridores · {sum(len(v) for v in datos.values())} '
          f'aperturas · k/BF de la liga = {k_liga:.4f}')

    # PRIMERA mitad para estimar, SEGUNDA para juzgar. Es el mismo protocolo
    # de elegir/juzgar que el proyecto usa en todo lo demás: si se estima y se
    # juzga con las mismas aperturas, cualquier encogimiento parece bueno.
    print('\n  protocolo: se estima con la primera mitad de aperturas de cada')
    print('  lanzador y se juzga con la segunda, que no interviene en el ajuste.')
    print(f"\n  {'m':>6}{'sesgo':>12}{'error abs.':>13}{'peor caso':>12}")
    mejor_m, mejor_err = None, 1e9
    resultados = {}
    for m in REJILLA_M:
        errores = []
        for nombre, ap in datos.items():
            corte = len(ap) // 2
            estima, juzga = ap[:corte], ap[corte:]
            if len(estima) < 4 or len(juzga) < 4:
                continue
            k_e = sum(a['k'] for a in estima)
            bf_e = sum(a['bf'] for a in estima)
            bf_ap = bf_e / len(estima)
            if bf_e <= 0:
                continue
            k_bf = (k_e + k_liga * m) / (bf_e + m)
            lam = k_bf * bf_ap
            real = statistics.mean([a['k'] for a in juzga])
            errores.append(lam - real)
        if not errores:
            continue
        err_abs = statistics.mean([abs(x) for x in errores])
        sesgo = statistics.mean(errores)
        peor = max(abs(x) for x in errores)
        resultados[m] = {'sesgo': sesgo, 'error_abs': err_abs, 'peor': peor,
                         'n': len(errores)}
        marca = ''
        if err_abs < mejor_err:
            mejor_err, mejor_m, marca = err_abs, m, '  ←'
        print(f'  {m:>6}{sesgo:>+11.3f}{err_abs:>13.3f}{peor:>12.3f}{marca}')

    print(f'\n  → mejor encogimiento: m = {mejor_m} bateadores previos')
    if 0 in resultados and mejor_m:
        base, opt = resultados[0], resultados[mejor_m]
        print(f"     sin encoger : sesgo {base['sesgo']:+.3f} · "
              f"error {base['error_abs']:.3f} · peor {base['peor']:.2f}")
        print(f"     con m={mejor_m:<4}: sesgo {opt['sesgo']:+.3f} · "
              f"error {opt['error_abs']:.3f} · peor {opt['peor']:.2f}")
        mejora = (base['error_abs'] - opt['error_abs']) / base['error_abs'] * 100
        print(f"     mejora del error absoluto: {mejora:.1f} %")
        if mejora < 3:
            print('     ⚠️ La mejora es marginal: no justifica tocar el modelo.')
        else:
            print('     ✅ Mejora suficiente para aplicarlo.')

    with open('_v115_encogimiento_ponches.json', 'w', encoding='utf-8') as f:
        json.dump({'k_liga': k_liga, 'mejor_m': mejor_m,
                   'resultados': {str(k): v for k, v in resultados.items()}},
                  f, ensure_ascii=False, indent=2)
    print('\nDetalle en _v115_encogimiento_ponches.json')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
