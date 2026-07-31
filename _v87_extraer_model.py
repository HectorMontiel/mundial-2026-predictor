#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v87 — ¿Se puede sacar la sección «Model» del buffer de serialización?

El buffer que guarda el pickle es el formato de SERIALIZACIÓN de XGBoost
(`XGBoosterSerializeToBuffer`), que la propia librería documenta como no
portable. En el volcado hexadecimal se ve que es un objeto UBJSON con dos
claves de primer nivel:

    {L..\\x06Config{ ... }L..\\x05Model{ ... }

La sección «Model» es justo lo que escribe `save_model`, que SÍ es portable. Si
se puede extraer y volver a envolver, se repararían incluso los modelos que ya
están publicados y no abren en Windows.

Se comprueba primero sobre un modelo que SÍ carga, donde hay referencia contra
la que comparar: el `save_raw(raw_format='ubj')` del booster ya cargado.
"""
import glob
import os
import sys

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass


def buffers_de(ruta):
    import joblib
    import xgboost.core as xc
    cap = []
    orig = xc.Booster.__setstate__

    def espia(self, state):
        if isinstance(state, dict) and isinstance(state.get('handle'),
                                                  (bytes, bytearray)):
            cap.append(bytes(state['handle']))
        self.__dict__.update(state if isinstance(state, dict) else {})

    xc.Booster.__setstate__ = espia
    try:
        joblib.load(ruta)
    except Exception:
        pass
    finally:
        xc.Booster.__setstate__ = orig
    return cap


def boosters_cargados(ruta):
    """Boosters de verdad, de un modelo que sí carga."""
    import joblib
    m = joblib.load(ruta)
    out = []

    def recorrer(o, prof=0):
        if prof > 5:
            return
        if hasattr(o, 'get_booster'):
            try:
                out.append(o.get_booster())
                return
            except Exception:
                pass
        for attr in ('calibrated_classifiers_', 'estimators_'):
            v = getattr(o, attr, None)
            if v is not None:
                for x in (v if isinstance(v, (list, tuple)) else []):
                    recorrer(x, prof + 1)
        for attr in ('estimator', 'base_estimator'):
            v = getattr(o, attr, None)
            if v is not None:
                recorrer(v, prof + 1)

    recorrer(m)
    return out


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
    print('v87 · ¿EL FORMATO DE SERIALIZACIÓN CONTIENE EL DE MODELO?')
    print('=' * 78)
    print(f'  bueno: {bueno}')
    print(f'  malo : {malo}\n')

    # referencia: el mismo booster, exportado en formato de MODELO
    bs = boosters_cargados(bueno)
    print(f'  boosters cargados del modelo bueno: {len(bs)}')
    if not bs:
        print('  no se pudieron extraer boosters; se aborta')
        return
    ref = bytes(bs[0].save_raw(raw_format='ubj'))
    print(f'  save_raw(ubj) del primero: {len(ref)} bytes · '
          f'empieza {ref[:16]!r}')

    ser = buffers_de(bueno)
    print(f'  buffer de SERIALIZACIÓN   : {len(ser[0])} bytes · '
          f'empieza {ser[0][:16]!r}')
    print(f'  diferencia de tamaño      : {len(ser[0]) - len(ref)} bytes')

    # ¿está el buffer de modelo contenido dentro del de serialización?
    i = ser[0].find(ref[:200])
    print(f'\n  ¿los primeros 200 bytes del modelo aparecen dentro del '
          f'buffer de serialización? {"sí, en el byte %d" % i if i >= 0 else "NO"}')

    if i < 0:
        # buscar la etiqueta "Model"
        j = ser[0].find(b'Model')
        print(f'  posición de la etiqueta "Model": {j}')
        if j >= 0:
            print(f'    contexto: {ser[0][j - 12:j + 30]!r}')
        print('\n  -> las dos codificaciones NO comparten bytes literales: el')
        print('     formato de serialización no envuelve al de modelo tal cual,')
        print('     así que no se puede recortar. Reparar los modelos ya')
        print('     publicados por esta vía no es posible.')
    else:
        print('\n  -> se puede recortar: hay reparación posible para los '
              'modelos ya publicados.')

    # lo que SÍ se puede garantizar hacia delante
    print('\n' + '-' * 78)
    print('COMPROBACIÓN DEL CAMINO PORTABLE (hacia delante)')
    print('-' * 78)
    tmp = '_tmp_ref.ubj'
    try:
        with open(tmp, 'wb') as f:
            f.write(ref)
        b2 = xgb.Booster()
        b2.load_model(tmp)
        print(f'  save_raw(ubj) -> load_model: OK '
              f'({b2.num_boosted_rounds()} rondas)')
        # y las predicciones deben coincidir
        import numpy as np
        X = np.random.RandomState(0).randn(16, bs[0].num_features())
        d = xgb.DMatrix(X)
        p1 = bs[0].predict(d)
        p2 = b2.predict(d)
        dif = float(np.abs(p1 - p2).max())
        print(f'  diferencia máxima de predicción: {dif:.2e} '
              f'{"(idénticas)" if dif < 1e-9 else ""}')
    except Exception as e:
        print(f'  FALLA: {type(e).__name__}: {str(e)[:120]}')
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


if __name__ == '__main__':
    main()
