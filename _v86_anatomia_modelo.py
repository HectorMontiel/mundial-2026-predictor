#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v86 — ¿Qué hay dentro de modelo_tda.joblib (62 MB en disco, 493 MB de RSS)?

Antes de intentar adelgazarlo hay que saber de qué está hecho. Si son árboles,
sus arrays internos son float64 y se pueden pasar a float32 sin cambiar de
modelo... pero eso hay que DEMOSTRARLO comparando predicciones, no suponerlo.
"""
import os
import sys

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

import joblib
import numpy as np


def describir(obj, prefijo='', nivel=0, salida=None):
    if salida is None:
        salida = []
    if nivel > 3:
        return salida
    tipo = type(obj).__name__
    salida.append((prefijo, tipo, nivel))
    if hasattr(obj, 'estimators_'):
        ests = obj.estimators_
        salida.append((f'{prefijo}.estimators_',
                       f'lista de {len(ests)}', nivel + 1))
        if len(ests):
            describir(ests[0], f'{prefijo}.estimators_[0]', nivel + 2, salida)
    elif hasattr(obj, 'calibrated_classifiers_'):
        cc = obj.calibrated_classifiers_
        salida.append((f'{prefijo}.calibrated_classifiers_',
                       f'lista de {len(cc)}', nivel + 1))
        describir(cc[0], f'{prefijo}.calibrated_classifiers_[0]', nivel + 2, salida)
    elif hasattr(obj, 'estimator'):
        describir(obj.estimator, f'{prefijo}.estimator', nivel + 1, salida)
    return salida


def contar_arrays(obj, visto=None, acc=None):
    """Suma los bytes de todos los ndarray alcanzables, por dtype."""
    if visto is None:
        visto, acc = set(), {}
    if id(obj) in visto:
        return acc
    visto.add(id(obj))
    if isinstance(obj, np.ndarray):
        k = str(obj.dtype)
        acc[k] = acc.get(k, 0) + obj.nbytes
        return acc
    if isinstance(obj, dict):
        for v in obj.values():
            contar_arrays(v, visto, acc)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            contar_arrays(v, visto, acc)
    elif hasattr(obj, '__dict__'):
        contar_arrays(vars(obj), visto, acc)
        # los árboles de sklearn esconden sus arrays tras un objeto C
        if hasattr(obj, 'tree_'):
            t = obj.tree_
            for attr in ('value', 'threshold', 'feature', 'children_left',
                         'children_right', 'impurity', 'n_node_samples',
                         'weighted_n_node_samples'):
                a = getattr(t, attr, None)
                if isinstance(a, np.ndarray):
                    k = str(a.dtype)
                    acc[k] = acc.get(k, 0) + a.nbytes
    return acc


def main():
    print('=' * 78)
    print('v86 · ANATOMÍA DE modelo_tda.joblib')
    print('=' * 78)

    ruta = os.path.join('modelos', 'modelo_tda.joblib')
    print(f'\ndisco: {os.path.getsize(ruta) / 1024 / 1024:.2f} MB')
    m = joblib.load(ruta)

    print(f'\ntipo raíz: {type(m).__name__}')
    print('\nestructura:')
    for pref, tipo, niv in describir(m, 'modelo'):
        print(f'  {"  " * niv}{pref}: {tipo}')

    print('\narrays numpy alcanzables, por dtype:')
    acc = contar_arrays(m)
    total = sum(acc.values())
    for dt, b in sorted(acc.items(), key=lambda kv: -kv[1]):
        print(f'  {dt:12s} {b / 1024 / 1024:9.2f} MB '
              f'({b / max(total, 1) * 100:5.1f} %)')
    print(f'  {"TOTAL":12s} {total / 1024 / 1024:9.2f} MB')

    f64 = acc.get('float64', 0)
    print(f'\nsi los float64 pasaran a float32 se ahorrarían '
          f'{f64 / 2 / 1024 / 1024:.1f} MB de datos vivos')

    # ¿cuántos árboles y de qué profundidad?
    def arboles(o):
        if hasattr(o, 'estimators_'):
            e = o.estimators_
            return e if not hasattr(e[0], '__len__') else [x for r in e for x in np.ravel(r)]
        if hasattr(o, 'calibrated_classifiers_'):
            base = getattr(o.calibrated_classifiers_[0], 'estimator', None)
            return arboles(base) if base is not None else []
        return []

    ar = arboles(m)
    ar = [a for a in ar if hasattr(a, 'tree_')]
    if ar:
        nodos = [a.tree_.node_count for a in ar]
        print(f'\nárboles: {len(ar)} · nodos por árbol: '
              f'media {np.mean(nodos):.0f}, máx {max(nodos)}')
        print(f'nodos totales: {sum(nodos):,}')

    print('\nfeatures esperadas:', getattr(m, 'n_features_in_', '?'))


if __name__ == '__main__':
    main()
