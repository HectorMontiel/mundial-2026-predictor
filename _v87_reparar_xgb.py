#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v87 — El buffer YA es UBJSON. Entonces, ¿por qué falla `__setstate__`?

Lo que se descartó
------------------
El buffer del booster de los modelos del runner de Linux **ya está en UBJSON**,
byte a byte con la misma cabecera que los que sí cargan:

    {L\\x00...\\x06Config{L...        (7b 4c 00 ... 43 6f 6e 66 69 67)

O sea que la propuesta de «migrar de pickle a save_model (UBJSON)» **no habría
arreglado nada**: ya se guarda en UBJSON. El problema está en cómo XGBoost lo
vuelve a meter en memoria, no en el formato.

Lo que se prueba aquí
---------------------
`Booster.__setstate__` usa `XGBoosterUnserializeFromBuffer`, que espera el
formato de *serialización* (modelo + estado interno). `Booster.load_model`
usa otra ruta que lee el formato de *modelo*. Si el buffer se carga bien por la
segunda, hay reparación posible: reconstruir el booster desde el mismo buffer
por la vía que sí funciona.

Si eso vale, se puede arreglar de verdad y en local, sin depender de un Linux
para comprobarlo.
"""
import glob
import os
import sys

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

CAPTURA = []


def capturar(ruta):
    """Devuelve los buffers de booster de un joblib, aunque no se pueda cargar."""
    import joblib
    import xgboost.core as xc

    original = xc.Booster.__setstate__
    CAPTURA.clear()

    def espia(self, state):
        if isinstance(state, dict) and isinstance(state.get('handle'),
                                                  (bytes, bytearray)):
            CAPTURA.append(bytes(state['handle']))
        self.__dict__.update(state if isinstance(state, dict) else {})

    xc.Booster.__setstate__ = espia
    try:
        joblib.load(ruta)
    except Exception:
        pass
    finally:
        xc.Booster.__setstate__ = original
    return list(CAPTURA)


def probar_rutas(buf: bytes, etiqueta: str):
    import xgboost as xgb

    print(f'\n  --- {etiqueta}: buffer de {len(buf)} bytes ---')

    # ruta 1: la que usa el pickle (necesita bytearray MUTABLE)
    try:
        b = xgb.Booster()
        b.__setstate__({'handle': bytearray(buf)})
        print(f'    __setstate__            OK  '
              f'({b.num_boosted_rounds()} rondas)')
        r1 = True
    except Exception as e:
        print(f'    __setstate__            FALLA {type(e).__name__}: '
              f'{str(e)[:120]}')
        r1 = False

    # ruta 2: load_model desde bytearray (formato de MODELO)
    try:
        b2 = xgb.Booster()
        b2.load_model(bytearray(buf))
        print(f'    load_model(bytearray)   OK  '
              f'({b2.num_boosted_rounds()} rondas)')
        r2 = True
    except Exception as e:
        print(f'    load_model(bytearray)   FALLA {type(e).__name__}: '
              f'{str(e)[:120]}')
        r2 = False

    # ruta 3: escribir a fichero .ubj y cargar
    r3 = False
    tmp = '_tmp_booster.ubj'
    try:
        with open(tmp, 'wb') as f:
            f.write(buf)
        b3 = xgb.Booster()
        b3.load_model(tmp)
        print(f'    load_model(fichero.ubj) OK  '
              f'({b3.num_boosted_rounds()} rondas)')
        r3 = True
    except Exception as e:
        print(f'    load_model(fichero.ubj) FALLA {type(e).__name__}: '
              f'{str(e)[:200]}')
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)

    return r1, r2, r3


def main():
    import joblib
    import xgboost as xgb

    bueno = malo = None
    for f in sorted(glob.glob(os.path.join('modelos', '*', 'modelo.joblib'))):
        try:
            joblib.load(f)
            bueno = bueno or f
        except Exception:
            malo = malo or f
        if bueno and malo:
            break

    print('=' * 78)
    print('v87 · ¿SE PUEDE RECUPERAR EL BOOSTER POR OTRA RUTA?')
    print('=' * 78)
    print(f'  xgboost local: {xgb.__version__}')
    print(f'  modelo que SÍ carga: {bueno}')
    print(f'  modelo que NO carga: {malo}')

    resultados = {}
    for etq, ruta in (('WINDOWS (carga)', bueno), ('LINUX (no carga)', malo)):
        if not ruta:
            continue
        bufs = capturar(ruta)
        print(f'\n{"=" * 78}\n{etq}: {ruta}\n{"=" * 78}')
        print(f'  buffers recuperados: {len(bufs)}')
        if bufs:
            resultados[etq] = probar_rutas(bufs[0], etq)

    print('\n' + '=' * 78)
    print('RESUMEN')
    print('=' * 78)
    print(f'  {"modelo":<20} {"__setstate__":>13} {"load_model(bytes)":>19} '
          f'{"load_model(fichero)":>21}')
    for etq, (r1, r2, r3) in resultados.items():
        print(f'  {etq:<20} {("OK" if r1 else "falla"):>13} '
              f'{("OK" if r2 else "falla"):>19} '
              f'{("OK" if r3 else "falla"):>21}')

    linux = resultados.get('LINUX (no carga)')
    if linux and not linux[0] and (linux[1] or linux[2]):
        print('\n  -> HAY REPARACIÓN: el buffer es bueno y `load_model` lo lee.')
        print('     Basta con reconstruir el booster por esa ruta al cargar.')
    elif linux and not any(linux):
        print('\n  -> NO hay reparación por esta vía: ninguna ruta lee el')
        print('     buffer en esta plataforma.')


if __name__ == '__main__':
    main()
