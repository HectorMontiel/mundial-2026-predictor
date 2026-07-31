#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v87 — El buffer REAL de XGBoost dentro del pickle que no abre.

Se parchea `xgboost.core.Booster.__setstate__` para que CAPTURE el buffer del
booster en vez de pasárselo al C API (que es donde salta «input stream
corrupted»). Así se puede mirar el contenido de un modelo que no se puede
cargar.

Se compara un modelo construido en Windows (que carga) con uno del runner de
Linux (que no), para ver en qué se diferencian de verdad.
"""
import glob
import os
import sys

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

CAPTURA = []


def cargar_capturando(ruta):
    import joblib
    import xgboost.core as xc

    original = xc.Booster.__setstate__
    CAPTURA.clear()

    def espia(self, state):
        CAPTURA.append(dict(state) if isinstance(state, dict) else state)
        # no se llama al original: es justo lo que revienta
        self.__dict__.update(state if isinstance(state, dict) else {})

    xc.Booster.__setstate__ = espia
    try:
        joblib.load(ruta)
        return True, None
    except Exception as e:
        return False, f'{type(e).__name__}: {str(e)[:80]}'
    finally:
        xc.Booster.__setstate__ = original


def describir(state, i):
    if not isinstance(state, dict):
        print(f'    booster {i}: estado {type(state).__name__}')
        return
    for k in sorted(state):
        v = state[k]
        if isinstance(v, (bytes, bytearray)):
            b = bytes(v)
            fmt = ('UBJSON (portable)' if b[:1] == b'{'
                   else 'binario antiguo "binf" (NO portable)' if b[:4] == b'binf'
                   else 'desconocido')
            print(f'    booster {i} · {k}: {len(b)} bytes · {fmt}')
            print(f'      primeros bytes: {b[:20]!r}')
            print(f'      hex          : {b[:20].hex(" ")}')
            j = b.find(b'"version"')
            if j < 0:
                j = b.find(b'version')
            if 0 <= j < len(b):
                print(f'      version cerca del byte {j}: {b[j:j + 48]!r}')
        else:
            print(f'    booster {i} · {k}: {type(v).__name__}')


def main():
    import joblib

    bueno = malo = None
    for f in sorted(glob.glob(os.path.join('modelos', '*', 'modelo.joblib'))):
        try:
            joblib.load(f)
            bueno = bueno or f
        except Exception:
            malo = malo or f
        if bueno and malo:
            break

    import xgboost
    print(f'xgboost local: {xgboost.__version__}')
    print(f'modelo que SÍ carga : {bueno}')
    print(f'modelo que NO carga : {malo}')

    for etq, ruta in (('CARGA (construido en Windows)', bueno),
                      ('NO CARGA (runner de Linux)', malo)):
        if not ruta:
            continue
        print('\n' + '=' * 78)
        print(f'{etq}\n{ruta}')
        print('=' * 78)
        ok, err = cargar_capturando(ruta)
        print(f'  unpickle con el espía puesto: '
              f'{"completo" if ok else "falló -> " + str(err)}')
        print(f'  boosters capturados: {len(CAPTURA)}')
        for i, st in enumerate(CAPTURA[:3]):
            describir(st, i)
        if len(CAPTURA) > 3:
            print(f'    ... y {len(CAPTURA) - 3} más')

    print('\n' + '=' * 78)
    print('LECTURA')
    print('=' * 78)
    print('  UBJSON («{» al principio) es portable entre plataformas.')
    print('  Si los dos llevan el mismo formato, el problema no es el formato')
    print('  y hay que seguir buscando antes de tocar nada.')


if __name__ == '__main__':
    main()
