#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v157 — CUÁNTA SEÑAL HAY DE VERDAD EN LOS CÓRNERS (y por qué el MAE engañaba).

CORRECCIÓN A LA v156. Aquel experimento midió el suelo del MAE —2,4835 con un
oráculo— y concluyó que la línea estaba cerrada. El suelo es correcto y sigue en
pie: un MAE de 2,0 es imposible. Pero de ahí NO se sigue que no haya nada que
capturar, y esa parte estaba mal razonada.

LA DESCOMPOSICIÓN QUE FALTABA
-----------------------------
Si el total de córners de cada partido es Poisson con su propia media λ_i, la
ley de la varianza total dice:

    Var(X) = E[λ] + Var(λ)
             \___/   \____/
             ruido    SEÑAL

El ruido de Poisson es irreducible y es lo que fija el suelo del MAE. Pero
`Var(λ)` es la parte que SÍ varía de partido a partido y que un modelo mejor
podría explicar. Medir `Var(λ) = Var(X) − E[X]` sale gratis con los datos que
ya hay.

POR QUÉ EL MAE ERA LA MÉTRICA EQUIVOCADA
-----------------------------------------
Con un ruido de desviación ~3,2 encima, capturar señal de desviación ~1,3 mueve
el MAE unas centésimas: queda sepultado. Pero para APOSTAR el MAE no es lo que
importa — importa distinguir los partidos que van por encima de la línea de los
que van por debajo, y eso lo mide la CORRELACIÓN.

    correlación máxima alcanzable = sd(λ) / sd(X)

Ese es el techo real de esta línea de trabajo, y es el número contra el que hay
que comparar cualquier modelo nuevo. Un modelo con correlación 0,06 sobre un
techo de 0,38 no está «casi en el límite»: ha capturado la sexta parte.
"""
import json
import logging
import sys
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings('ignore')
logging.basicConfig(level=logging.ERROR)

import league_engine as le

LIGAS = ['premier', 'laliga', 'serie_a', 'bundesliga', 'ligue_1', 'eredivisie',
         'primeira', 'turquia', 'sco_premiership', 'bel_pro_league',
         'eng_championship', 'eng_league_one', 'eng_league_two',
         'eng_national', 'esp_hypermotion', 'ita_serie_b', 'fra_ligue2',
         'ger_bundesliga2', 'sco_championship', 'gre_super_league']


def analiza(clave):
    df = le.descargar_liga(clave, temporadas=8)
    df = df.dropna(subset=['home_corners', 'away_corners'])
    if len(df) < 600:
        return None
    x = (pd.to_numeric(df['home_corners'], errors='coerce')
         + pd.to_numeric(df['away_corners'], errors='coerce')).dropna()
    if len(x) < 600:
        return None
    media = float(x.mean())
    var = float(x.var())
    var_lambda = max(var - media, 0.0)       # Var(λ) = Var(X) − E[λ]
    sd_lambda = float(np.sqrt(var_lambda))
    sd_x = float(np.sqrt(var))
    return {
        'liga': clave, 'n': int(len(x)),
        'media': round(media, 3), 'sd_total': round(sd_x, 3),
        'sd_lambda': round(sd_lambda, 3),
        # La correlación que tendría un modelo PERFECTO: cuánto de la
        # variación observada es media condicional y no ruido de Poisson.
        'corr_maxima': round(sd_lambda / sd_x, 4) if sd_x else 0.0,
        # Y cuánta varianza es explicable en principio.
        'varianza_explicable_pct': round(100 * var_lambda / var, 2) if var else 0.0,
    }


def main():
    claves = sys.argv[1:] or LIGAS
    filas = []
    print('%-20s %6s %7s %8s %9s %8s' % ('liga', 'n', 'media', 'sd_tot',
                                         'sd_lambda', 'corr_max'))
    print('-' * 62)
    for c in claves:
        try:
            r = analiza(c)
        except Exception as e:
            print('%-20s ERROR %s' % (c, type(e).__name__))
            continue
        if not r:
            continue
        filas.append(r)
        print('%-20s %6d %7.2f %8.2f %9.2f %8.3f'
              % (r['liga'], r['n'], r['media'], r['sd_total'],
                 r['sd_lambda'], r['corr_maxima']), flush=True)

    if not filas:
        return
    n = sum(f['n'] for f in filas)
    def pond(k):
        return round(sum(f[k] * f['n'] for f in filas) / n, 4)
    resumen = {
        'ligas': len(filas), 'n': n,
        'media': pond('media'), 'sd_total': pond('sd_total'),
        'sd_lambda': pond('sd_lambda'),
        'corr_maxima': pond('corr_maxima'),
        'varianza_explicable_pct': pond('varianza_explicable_pct'),
        'corr_lograda_v156': 0.0609,
    }
    resumen['fraccion_capturada'] = round(
        resumen['corr_lograda_v156'] / resumen['corr_maxima'], 4) \
        if resumen['corr_maxima'] else 0.0
    print()
    print(json.dumps(resumen, ensure_ascii=False, indent=1))
    print()
    print('LECTURA: el techo de correlación es %.3f y el mejor modelo de la '
          'v156 llegó a %.3f — un %.0f %% del margen.'
          % (resumen['corr_maxima'], resumen['corr_lograda_v156'],
             100 * resumen['fraccion_capturada']))
    json.dump({'ligas': filas, 'resumen': resumen},
              open('_v157_techo_senal.json', 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)


if __name__ == '__main__':
    main()
