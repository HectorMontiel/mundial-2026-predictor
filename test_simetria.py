#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test de simetría del Mundial (v20, spec 8.4).

Para cualquier par (A, B) debe cumplirse:
    P(gana A | A local vs B) == P(gana A | B local vs A)
tanto en sede neutral (predicción simetrizada) como cuando hay anfitrión
(la vista se calcula siempre con el anfitrión como local y se espeja).

Ejecutar:  .venv\\Scripts\\python test_simetria.py
"""

from prediction_api import PredictionEngine

TOL = 2e-3   # las probs del resultado van redondeadas a 3 decimales

FALLOS = []


def check(cond, msg):
    print(('OK  ' if cond else 'FALLO') + ' ' + msg)
    if not cond:
        FALLOS.append(msg)


def probar_par(motor, a, b, estadio=None):
    r1 = motor.predecir(a, b, estadio=estadio)
    r2 = motor.predecir(b, a, estadio=estadio)
    if 'error' in r1 or 'error' in r2:
        check(False, f"{a} vs {b}: error del motor")
        return
    p1, p2 = r1['prediction']['probabilities'], r2['prediction']['probabilities']
    sede = r1['stadium']
    check(abs(p1['home'] - p2['away']) < TOL and abs(p1['draw'] - p2['draw']) < TOL,
          f"{a} vs {b} ({sede}, {r1['localia']['metodo']}): "
          f"{p1['home']:.3f}/{p1['draw']:.3f}/{p1['away']:.3f} == espejo de "
          f"{p2['home']:.3f}/{p2['draw']:.3f}/{p2['away']:.3f}")
    g1, g2 = r1['prediction']['expected_goals'], r2['prediction']['expected_goals']
    check(abs(g1['home'] - g2['away']) < 0.06 and abs(g1['away'] - g2['home']) < 0.06,
          f"{a} vs {b}: goles esperados espejados "
          f"({g1['home']:.2f}-{g1['away']:.2f} vs {g2['home']:.2f}-{g2['away']:.2f})")


if __name__ == '__main__':
    motor = PredictionEngine()
    assert motor.listo, motor.error

    print("=== Sedes neutrales (simetría exacta) ===")
    for a, b in [('ARG', 'BRA'), ('ESP', 'GER'), ('FRA', 'ENG'),
                 ('JPN', 'KOR'), ('MAR', 'SEN'), ('URU', 'COL')]:
        probar_par(motor, a, b)
    probar_par(motor, 'ECU', 'COL', estadio='MetLife')

    print("\n=== Con anfitrión (la localía no depende del orden) ===")
    # México en el Azteca: el caso reportado por el usuario (MEX vs ECU)
    probar_par(motor, 'MEX', 'ECU', estadio='Azteca')
    probar_par(motor, 'USA', 'COL', estadio='AT&T')
    probar_par(motor, 'CAN', 'URU', estadio='BC_Place')

    # El anfitrión debe conservar SU ventaja aunque se le liste de visitante:
    r_dir = motor.predecir('MEX', 'ECU', estadio='Azteca')
    r_inv = motor.predecir('ECU', 'MEX', estadio='Azteca')
    check(abs(r_dir['prediction']['probabilities']['home']
              - r_inv['prediction']['probabilities']['away']) < TOL,
          "P(gana México) idéntica listándolo local o visitante en el Azteca")

    print(f"\n{'='*40}\n{'TODO OK' if not FALLOS else f'{len(FALLOS)} FALLOS'}")
    raise SystemExit(1 if FALLOS else 0)
