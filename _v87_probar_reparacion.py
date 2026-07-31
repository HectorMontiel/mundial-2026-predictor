#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v87 — ¿Repara de verdad `modelos_portables.cargar` los modelos del runner?

Dos comprobaciones, y las dos tienen que pasar:

  1. Sobre un modelo que YA carga, la reparación no debe cambiar ni una
     predicción (si cambiara algo, estaría devolviendo otro modelo).
  2. Sobre los modelos del runner de Linux que hoy no abren, tienen que abrir y
     predecir.
"""
import glob
import os
import sys

import numpy as np

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass


def _ancho_entrada(modelo, ruta) -> int:
    """Cuántas columnas espera el modelo, sea cual sea su familia."""
    n = getattr(modelo, 'n_features_in_', None)
    if n:
        return int(n)
    for attr in ('calibrated_classifiers_', 'estimators_'):
        v = getattr(modelo, attr, None)
        if v:
            n = getattr(v[0], 'n_features_in_', None)
            if n:
                return int(n)
            est = getattr(v[0], 'estimator', None)
            if est is not None and getattr(est, 'n_features_in_', None):
                return int(est.n_features_in_)
    # último recurso: el metadata de la liga
    import json
    meta = os.path.join(os.path.dirname(ruta), 'metadata.json')
    if os.path.exists(meta):
        m = json.load(open(meta, encoding='utf-8'))
        import feature_engineering as fe
        extra = len(m.get('features_extra_cols') or [])
        # 15 base + extras + 6 entropías topológicas
        return len(fe.FEATURES_MODELO) + extra + 6
    raise RuntimeError('no se pudo deducir el ancho de entrada')


def main():
    import joblib
    import modelos_portables as mp

    rutas = sorted(glob.glob(os.path.join('modelos', '*', 'modelo.joblib')))
    buenos, malos = [], []
    for f in rutas:
        try:
            joblib.load(f)
            buenos.append(f)
        except Exception:
            malos.append(f)

    print('=' * 78)
    print('v87 · REPARACIÓN DE MODELOS SERIALIZADOS EN OTRA PLATAFORMA')
    print('=' * 78)
    print(f'  modelos totales : {len(rutas)}')
    print(f'  abren hoy       : {len(buenos)}')
    print(f'  NO abren hoy    : {len(malos)}')

    # ---- 1) no cambia nada donde ya funcionaba -----------------------------
    print('\n--- 1) sobre modelos que YA abren, no debe cambiar nada ---')
    iguales = 0
    for f in buenos[:3]:
        a = joblib.load(f)
        b = mp.cargar(f)
        X = np.random.RandomState(0).randn(24, _ancho_entrada(a, f))
        d = float(np.abs(a.predict_proba(X) - b.predict_proba(X)).max())
        ok = d < 1e-12
        iguales += ok
        print(f'  {os.path.basename(os.path.dirname(f)):22s} '
              f'diferencia máxima {d:.2e} {"IDÉNTICO" if ok else "DISTINTO"}')

    # ---- 2) repara los que no abrían --------------------------------------
    print(f'\n--- 2) sobre los {len(malos)} que NO abren ---')
    reparados, fallidos = [], []
    for f in malos:
        liga = os.path.basename(os.path.dirname(f))
        try:
            m = mp.cargar(f)
            # `ModeloBetaCalibrado` (familia 'beta') no expone n_features_in_;
            # se saca del metadata de la liga, que sí lo tiene.
            n = _ancho_entrada(m, f)
            X = np.random.RandomState(1).randn(8, n)
            p = m.predict_proba(X)
            if p.shape[0] == 8 and np.all(np.isfinite(p)) and \
                    np.allclose(p.sum(axis=1), 1.0, atol=1e-6):
                reparados.append(liga)
            else:
                fallidos.append((liga, 'predicción incoherente'))
        except Exception as e:
            fallidos.append((liga, f'{type(e).__name__}: {str(e)[:50]}'))

    print(f'  reparados y prediciendo bien: {len(reparados)} de {len(malos)}')
    if reparados[:8]:
        print(f'    p.ej. {", ".join(reparados[:8])}')
    if fallidos:
        print(f'  siguen sin abrir: {len(fallidos)}')
        for liga, err in fallidos[:6]:
            print(f'    {liga}: {err}')

    # ---- 3) y las predicciones tienen sentido ------------------------------
    if reparados:
        print('\n--- 3) cordura: un modelo reparado responde al ELO ---')
        import feature_engineering as fe
        liga = reparados[0]
        m = mp.cargar(os.path.join('modelos', liga, 'modelo.joblib'))
        n = m.n_features_in_
        base = np.zeros((7, n))
        base[:, 0] = np.linspace(-0.75, 0.75, 7)      # DIFF_ELO es la columna 0
        p = m.predict_proba(base)
        # la clase 0 es victoria local
        col = list(getattr(m, 'classes_', [0, 1, 2])).index(0)
        print(f'  {liga}: P(local) al subir DIFF_ELO de -0,75 a +0,75:')
        print('    ' + ' '.join(f'{x:.3f}' for x in p[:, col]))
        crece = p[-1, col] > p[0, col]
        print(f'    {"crece (coherente)" if crece else "no crece"}')

    print('\n' + '=' * 78)
    ok = (iguales == min(3, len(buenos))) and not fallidos and reparados
    print(f'VEREDICTO: {"REPARACIÓN VÁLIDA" if ok else "revisar"}')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
