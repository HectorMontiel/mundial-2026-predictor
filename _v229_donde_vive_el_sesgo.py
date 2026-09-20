#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v229 — dónde vive el 3,7 % de sesgo al Under que la v225 no se llevó.

DE DÓNDE SALE LA PREGUNTA
-------------------------
El usuario miró un América-Chivas con las dos formas en 2,6 goles y vio
«Menos de 3.5 — 72 %». La aritmética es correcta: con λ = 2,6 la Poisson da
73,6 %, y «Over 2.5» y «Under 3.5» no son opuestos —se solapan en el partido de
tres goles exactos, que es el 21,8 %—. Pero la pregunta de fondo sí tenía
fundamento, y la medición de la v225 lo dice:

    under_antes   0,5355        lo que el modelo prometía
    under_real    0,4879        lo que pasó
    sesgo         +0,0476       decía «Under» 4,8 puntos de más

La isotónica de la v225 lo bajó a +0,0375. Mejora medida y con bootstrap a
favor, pero se quedó a un cuarto del camino. Queda un sesgo de casi cuatro
puntos y este sondeo busca DÓNDE está, en vez de volver a promediarlo.

LA HIPÓTESIS, Y POR QUÉ ES ÉSTA
-------------------------------
La isotónica se ajusta UNA por línea, sobre la probabilidad. Es monótona, así
que puede estirar la escala pero no puede decir cosas distintas en sitios
distintos del espacio de λ si la probabilidad coincide. Y el motivo del sesgo
—la sobredispersión, ya diagnosticada en la v225— no es constante: la varianza
real crece más rápido que la media, así que en los partidos de λ alta la cola
pesa más de lo que la Poisson cree, y ahí el Under se sobreestima MÁS.

Si eso es cierto, el residuo no está repartido: está concentrado en la λ alta.
Y eso es justo lo que el usuario notó, porque el partido que le chirrió es de
los de media alta.

Esto no cambia nada. Mide y escribe `_v229_sesgo_por_lambda.json`.
"""
import io
import json
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8',
                              errors='replace')

import numpy as np

SALIDA = '_v229_sesgo_por_lambda.json'
# Los cortes de λ. No son redondos por gusto: 2,5 y 3,0 son las dos líneas de
# goles que más se juegan, así que partir ahí hace que los tramos signifiquen
# algo para quien apuesta y no sólo para el que mide.
CORTES = (0.0, 2.2, 2.6, 3.0, 99.0)


def main():
    import calibrador_goles as cg

    t = cg._datos()
    if 'pliegue' not in t.columns:
        print('el ledger no trae pliegues; no se puede juzgar sin fuga')
        return 1
    ultimo = int(t.pliegue.max())
    juicio = t[t.pliegue == ultimo].copy()
    print('ledger %d filas · pliegue de juicio %d con %d filas'
          % (len(t), ultimo, len(juicio)))

    # SIN FUGA, Y ESTO NO ES UN DETALLE.
    #
    # `cg.calibrar()` usa el fichero desplegado, que se entrena con TODOS los
    # pliegues —incluido el de juicio—. Medir con él es preguntarle al modelo
    # por partidos que ya vio, y el residuo saldría más pequeño de lo que es.
    # Aquí se reentrena cortando en el pliegue de juicio y se aplica a mano.
    doc = cg.entrenar(hasta_pliegue=ultimo)

    def _calibra(p, linea):
        d = (doc.get('lineas') or {}).get(cg.clave_linea(linea))
        if not d:
            return np.asarray(p, dtype=float)
        return np.interp(np.asarray(p, dtype=float), d['x'], d['y'])

    out = {'n_juicio': int(len(juicio)), 'cortes': list(CORTES),
           'sin_fuga': True, 'entrenado_hasta_pliegue': ultimo, 'lineas': {}}

    for linea in cg.LINEAS:
        col = 'over_%s_real' % str(linea)
        if col not in juicio.columns:
            continue
        m = juicio[col].notna()
        if int(m.sum()) < 200:
            continue
        sub = juicio.loc[m]
        lam = sub['lam'].to_numpy(dtype=float)
        y = sub[col].to_numpy(dtype=float)          # 1 = Over
        p_cruda = cg._p_over(lam, linea)
        p_cal = _calibra(p_cruda, linea)

        print()
        print('=== LÍNEA %s  (n=%d) ===' % (linea, len(y)))
        print('%-16s %6s %10s %10s %10s %10s'
              % ('tramo de lambda', 'n', 'under_mod', 'under_cal',
                 'under_real', 'sesgo_cal'))
        tramos = []
        for a, b in zip(CORTES[:-1], CORTES[1:]):
            g = (lam >= a) & (lam < b)
            if g.sum() < 60:
                continue
            # «under» es 1 - over, que es como lo mira quien apuesta
            u_mod = float(np.mean(1 - p_cruda[g]))
            u_cal = float(np.mean(1 - p_cal[g]))
            u_real = float(np.mean(1 - y[g]))
            fila = {'desde': a, 'hasta': b, 'n': int(g.sum()),
                    'under_modelo': round(u_mod, 4),
                    'under_calibrado': round(u_cal, 4),
                    'under_real': round(u_real, 4),
                    'sesgo_crudo': round(u_mod - u_real, 4),
                    'sesgo_calibrado': round(u_cal - u_real, 4)}
            tramos.append(fila)
            print('%-16s %6d %10.4f %10.4f %10.4f %+10.4f'
                  % ('%.1f - %.1f' % (a, b), g.sum(), u_mod, u_cal, u_real,
                     u_cal - u_real))
        out['lineas'][str(linea)] = tramos

    # El veredicto: ¿el residuo está repartido o concentrado en la lambda alta?
    print()
    todos = [f for fs in out['lineas'].values() for f in fs]
    if todos:
        bajo = [f for f in todos if f['hasta'] <= 2.6]
        alto = [f for f in todos if f['desde'] >= 2.6]

        def _pond(fs):
            n = sum(f['n'] for f in fs)
            return (sum(f['sesgo_calibrado'] * f['n'] for f in fs) / n
                    if n else float('nan'), n)

        s_bajo, n_bajo = _pond(bajo)
        s_alto, n_alto = _pond(alto)
        out['sesgo_lambda_baja'] = round(s_bajo, 4)
        out['sesgo_lambda_alta'] = round(s_alto, 4)
        out['n_baja'], out['n_alta'] = n_bajo, n_alto
        print('sesgo al Under tras calibrar, ponderado por muestra:')
        print('   lambda < 2.6   %+.4f   (n=%d)' % (s_bajo, n_bajo))
        print('   lambda >= 2.6  %+.4f   (n=%d)' % (s_alto, n_alto))
        concentrado = (s_alto - s_bajo) > 0.02
        out['veredicto'] = ('concentrado_en_lambda_alta' if concentrado
                            else 'repartido')
        print()
        print('VEREDICTO: el residuo está %s'
              % ('CONCENTRADO en la lambda alta, así que calibrar por tramo '
                 'de lambda tiene sentido' if concentrado
                 else 'REPARTIDO; partir por lambda no arreglaría nada'))

    with open(SALIDA, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print('\n-> %s' % SALIDA)
    return 0


if __name__ == '__main__':
    sys.exit(main())
