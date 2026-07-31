#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v86 — ¿Cuántos modelos de liga no se pueden cargar?

Al rebasar sobre los dos commits de «reentrenamiento automático de ligas»
(24eb8c0 y fb4cdf9, ya en los dos remotos) apareció esto:

    xgboost._c_api.XGBoostError: input stream corrupted

El fichero viene limpio del commit remoto (`git status` no marca modificación) y
el blob en el repositorio coincide byte a byte con el disco, así que NO es una
conversión de saltos de línea al hacer checkout: es el contenido que el job
subió. Además `.gitattributes` ya declara `*.joblib binary`.

La versión anterior al reentrenamiento SÍ carga. O sea que el job automático
está publicando modelos que la app no puede abrir.

Esto recorre todos los modelos y dice cuáles están rotos, para saber si es un
caso aislado o si la app está tocada en producción.
"""
import glob
import os
import sys

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass


def main():
    import joblib

    rutas = sorted(glob.glob(os.path.join('modelos', '*', 'modelo.joblib')))
    print(f'{len(rutas)} modelos de liga en disco\n')

    ok, rotos = [], []
    for r in rutas:
        liga = os.path.basename(os.path.dirname(r))
        try:
            joblib.load(r)
            ok.append(liga)
        except Exception as e:
            rotos.append((liga, f'{type(e).__name__}: {str(e)[:60]}'))
            print(f'  ROTO   {liga:24s} {type(e).__name__}: {str(e)[:50]}')

    print(f'\n{len(ok)} cargan · {len(rotos)} rotos')

    if rotos:
        print('\nLigas afectadas:')
        for liga, err in rotos:
            print(f'  · {liga}')

    # ¿son las mismas que tocó el reentrenamiento?
    import subprocess
    try:
        d = subprocess.run(['git', 'diff', '--name-only', 'c017d40', 'HEAD'],
                           capture_output=True, text=True, timeout=60)
        tocadas = {p.split('/')[1] for p in d.stdout.splitlines()
                   if p.startswith('modelos/') and p.count('/') >= 2}
        print(f'\nligas tocadas por el reentrenamiento: {len(tocadas)}')
        rotas_set = {l for l, _ in rotos}
        print(f'  de ellas, rotas: {len(rotas_set & tocadas)}')
        print(f'  rotas que NO tocó el reentrenamiento: '
              f'{sorted(rotas_set - tocadas)}')
    except Exception as e:
        print(f'(no se pudo cruzar con git: {e})')

    # versión de xgboost: una causa clásica de "input stream corrupted" es
    # que el modelo se serializó con otra versión, no que el fichero esté mal
    try:
        import xgboost
        print(f'\nxgboost local: {xgboost.__version__}')
        with open('requirements.txt', encoding='utf-8') as f:
            for ln in f:
                if 'xgboost' in ln:
                    print(f'requirements : {ln.strip()}')
    except Exception:
        pass

    return 1 if rotos else 0


if __name__ == '__main__':
    sys.exit(main())
