#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v101 — El A/B honesto: contexto previo ENCIMA de la fuerza de hoy.

Por qué se rehace la medición
-----------------------------
El primer A/B dio ADOPTAR en empate y visitante. La descomposición demostró que
casi todo venía de un sumando escondido dentro de `DIFF_ESCALON`: la diferencia
de ELO ACTUAL, no la del rival anterior. Aislado, el rival anterior aporta
+0,00011 (p5 −0,00011), y condicionado al ELO de hoy, −0,00001.

Así que la base correcta no es sólo la probabilidad del modelo: es la
probabilidad del modelo **más la diferencia de ELO rodante**. Sobre esa base se
pregunta lo único que interesa de verdad: ¿queda algo en la circunstancia del
partido anterior que el modelo no tenga ya?

Se mide en los cuatro mercados y se reporta lo que salga.
"""
import json
import sys
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings('ignore')
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

import contexto_previo as cp
from _v101_auditoria_empate import medir
from _v101_descomponer_escalon import cargar_contexto_ampliado

# DIFF_ESCALON se excluye del bloque «contexto»: ya se demostró que su señal es
# la diferencia de ELO de hoy, que ahora está en la BASE. Dejarla dentro sería
# contar dos veces lo mismo y volver a atribuírselo al partido anterior.
CONTEXTO_NETO = ['DIFF_DESCANSO', 'DIFF_SORPRESA_PREV',
                 'DIFF_MARGEN_PREV', 'DIFF_CARGA']


def main():
    ctx = cargar_contexto_ampliado()
    out = {}

    def bloque(led, mercados, etiqueta):
        led = led.dropna(subset=cp.COLUMNAS + ['ELO_A'])
        print(f'\n=== {etiqueta}: {len(led)} filas con contexto')
        elo = ((led['ELO_A'] - led['ELO_B']) / cp.ESCALA_ELO).to_numpy(dtype=float)
        # el rival anterior, ya limpio de la fuerza de hoy
        rivales = led['DIFF_ESCALON'].to_numpy(dtype=float) - elo
        X = np.column_stack([led[CONTEXTO_NETO].to_numpy(dtype=float), rivales])
        fecha = pd.to_datetime(led['fecha'])
        for nombre, col_p, y in mercados(led):
            sub = ~pd.isna(led[col_p].to_numpy())
            if sub.sum() < 1000:
                continue
            base = np.column_stack([elo])[sub]
            out[f'{etiqueta}:{nombre}'] = medir(
                led[col_p].to_numpy(dtype=float)[sub], y[sub], base, X[sub],
                fecha[sub], f'{nombre} · contexto | modelo+ELO')

    tot = pd.read_csv('pick_ledger_totales.csv').join(ctx, on='match_id',
                                                      how='inner')
    bloque(tot, lambda d: [
        ('over_1.5', 'p_over_1.5', d['over_1.5_real'].to_numpy(dtype=float)),
        ('over_2.5', 'p_over_2.5', d['over_2.5_real'].to_numpy(dtype=float)),
        ('btts', 'p_btts', d['btts_real'].to_numpy(dtype=float))], 'goles')

    led = pd.read_csv('pick_ledger.csv').join(ctx, on='match_id', how='inner')
    bloque(led, lambda d: [
        ('gana local', 'p_home', (d['resultado'].to_numpy() == 0).astype(float)),
        ('empate', 'p_draw', (d['resultado'].to_numpy() == 1).astype(float)),
        ('gana visita', 'p_away', (d['resultado'].to_numpy() == 2).astype(float))],
        '1x2')

    # …y, por separado, lo que SÍ resultó ser: el ELO encima del modelo
    print('\n=== control: la diferencia de ELO encima del modelo (sin contexto)')
    led2 = led.dropna(subset=['ELO_A', 'p_draw', 'resultado'])
    elo2 = ((led2['ELO_A'] - led2['ELO_B']) / cp.ESCALA_ELO).to_numpy(dtype=float)
    out['control:elo_sobre_modelo'] = medir(
        led2['p_draw'].to_numpy(dtype=float),
        (led2['resultado'].to_numpy() == 1).astype(float), None,
        elo2.reshape(-1, 1), pd.to_datetime(led2['fecha']),
        'empate · ELO | modelo')

    json.dump(out, open('_v101_ab_contexto_neto.json', 'w'), indent=1,
              ensure_ascii=False)
    print('\n-> _v101_ab_contexto_neto.json')


if __name__ == '__main__':
    main()
