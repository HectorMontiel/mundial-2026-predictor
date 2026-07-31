#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v86 — ¿Qué ocupa los 443 MB del motor del Mundial?

_v86_huella_total.py midió que PredictionEngine es, con diferencia, el objeto
más caro de la app: 443,7 MB de un coste fijo de 625,3 MB. Y dashboard_ui.py lo
instancia a NIVEL DE MÓDULO (`MOTOR = cargar_motor()`), o sea que se paga
entero aunque nadie abra la pestaña del Mundial.

Antes de tocar nada hay que saber qué parte concreta pesa.
"""
import gc
import os
import sys

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

import psutil


def rss():
    return psutil.Process(os.getpid()).memory_info().rss / 1024 / 1024


def tam(obj, visto=None):
    """Tamaño recursivo aproximado en MB."""
    import numpy as np
    import pandas as pd
    if visto is None:
        visto = set()
    if id(obj) in visto:
        return 0
    visto.add(id(obj))
    try:
        if isinstance(obj, pd.DataFrame):
            return obj.memory_usage(deep=True).sum() / 1024 / 1024
        if isinstance(obj, pd.Series):
            return obj.memory_usage(deep=True) / 1024 / 1024
        if isinstance(obj, np.ndarray):
            return obj.nbytes / 1024 / 1024
        total = sys.getsizeof(obj) / 1024 / 1024
        if isinstance(obj, dict):
            for k, v in list(obj.items())[:5000]:
                total += tam(k, visto) + tam(v, visto)
        elif isinstance(obj, (list, tuple, set)):
            for v in list(obj)[:5000]:
                total += tam(v, visto)
        elif hasattr(obj, '__dict__'):
            total += tam(vars(obj), visto)
        return total
    except Exception:
        return 0


def main():
    print('=' * 78)
    print('v86 · PERFIL DE MEMORIA DEL MOTOR DEL MUNDIAL')
    print('=' * 78)

    gc.collect()
    antes = rss()

    from prediction_api import PredictionEngine
    tras_import = rss()
    print(f'\nimportar prediction_api : {tras_import:7.1f} MB '
          f'(+{tras_import - antes:.1f})')

    motor = PredictionEngine()
    gc.collect()
    tras_init = rss()
    print(f'instanciar el motor     : {tras_init:7.1f} MB '
          f'(+{tras_init - tras_import:.1f})')

    print('\nAtributos del motor por tamaño aproximado:')
    filas = []
    for nombre, valor in vars(motor).items():
        filas.append((tam(valor), nombre, type(valor).__name__))
    filas.sort(reverse=True)
    for mb, nombre, tipo in filas[:15]:
        extra = ''
        try:
            import pandas as pd
            if isinstance(getattr(motor, nombre), pd.DataFrame):
                df = getattr(motor, nombre)
                extra = f'  [{len(df)} filas x {len(df.columns)} col]'
            elif hasattr(getattr(motor, nombre), '__len__'):
                extra = f'  [{len(getattr(motor, nombre))} elem]'
        except Exception:
            pass
        print(f'  {mb:8.1f} MB  {nombre:24s} {tipo:16s}{extra}')

    suma = sum(f[0] for f in filas)
    print(f'\n  suma de atributos: {suma:.1f} MB '
          f'(el resto es el propio import: ripser, sklearn, xgboost...)')

    print('\n' + '-' * 78)
    print('¿Cuánto cuesta SOLO importar el módulo, sin instanciar?')
    print(f'  import  : +{tras_import - antes:.1f} MB')
    print(f'  instancia: +{tras_init - tras_import:.1f} MB')
    print('\nSi el peso está en el import, hacerlo perezoso no ahorra nada '
          'mientras el módulo se importe arriba del todo en dashboard_ui.')


if __name__ == '__main__':
    main()
