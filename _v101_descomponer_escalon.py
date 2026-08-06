#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v101 — Descomponer DIFF_ESCALON: ¿rival anterior, o fuerza de hoy?

El control de permutación demostró que la mejora del empate (+0,028) es señal
real y no ruido, y que no es identidad de liga. Pero al desarrollar la fórmula
aparece un problema de atribución:

    DIFF_ESCALON = (elo_rival_prev_A − ELO_B)/400 − (elo_rival_prev_B − ELO_A)/400
                 = [(ELO_A − ELO_B) + (elo_rival_prev_A − elo_rival_prev_B)] / 400
                   └──── fuerza de HOY ────┘   └──── rivales ANTERIORES ────┘

Es decir: la feature lleva dentro la diferencia de ELO actual. Si la mejora
viene de ahí, el hallazgo NO es «venía de un rival más fuerte» sino «la
probabilidad de empate del modelo está mal calibrada contra la diferencia de
fuerza», que es una conclusión completamente distinta y mucho menos novedosa.

Se separan los dos sumandos y se mide cada uno por su cuenta. Contar esto como
«la IA aprendió del partido anterior» sin hacer esta resta sería exactamente el
autoengaño que el proyecto lleva versiones evitando.
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
from _v101_ab_contexto_futbol import cargar_contexto
from _v101_auditoria_empate import medir

ESCALA = cp.ESCALA_ELO


def cargar_contexto_ampliado() -> pd.DataFrame:
    """Como `cargar_contexto`, pero conservando los ELO y los lados sueltos."""
    import os
    trozos = []
    extra = ['ELO_A', 'ELO_B', 'ESCALON_A', 'ESCALON_B']
    for f in sorted(os.listdir('.')):
        if not (f.startswith('historico_') and f.endswith('.csv')):
            continue
        try:
            d = pd.read_csv(f, low_memory=False)
        except Exception:
            continue
        if not {'date', 'home_team', 'away_team', 'home_goals',
                'away_goals', 'MATCH_ID'}.issubset(d.columns):
            continue
        try:
            ctx = cp.contexto_futbol(d)
        except Exception:
            continue
        trozos.append(ctx[['MATCH_ID'] + cp.COLUMNAS + extra])
    todo = pd.concat(trozos, ignore_index=True).drop_duplicates('MATCH_ID')
    return todo.set_index('MATCH_ID')


def main():
    ctx = cargar_contexto_ampliado()
    led = pd.read_csv('pick_ledger.csv').join(ctx, on='match_id', how='inner')
    led = led.dropna(subset=cp.COLUMNAS + ['p_draw', 'resultado', 'ELO_A'])
    fecha = pd.to_datetime(led['fecha'])
    y = (led['resultado'].to_numpy() == 1).astype(float)
    p = led['p_draw'].to_numpy(dtype=float)

    # los dos sumandos, por separado
    dif_elo_hoy = ((led['ELO_A'] - led['ELO_B']) / ESCALA).to_numpy(dtype=float)
    escalon = led['DIFF_ESCALON'].to_numpy(dtype=float)
    rivales_prev = escalon - dif_elo_hoy          # el residuo: sólo lo anterior

    out = {}
    print('\nEmpate — qué parte de DIFF_ESCALON carga con la mejora')
    out['escalon_completo'] = medir(p, y, None, escalon.reshape(-1, 1), fecha,
                                    'DIFF_ESCALON (completo)')
    out['solo_elo_hoy'] = medir(p, y, None, dif_elo_hoy.reshape(-1, 1), fecha,
                                'sólo |ELO_A − ELO_B| de HOY')
    out['solo_rivales_prev'] = medir(p, y, None, rivales_prev.reshape(-1, 1),
                                     fecha, 'sólo rivales ANTERIORES')
    print('\n  …y el rival anterior ENCIMA de la fuerza de hoy:')
    out['prev_sobre_elo'] = medir(p, y, dif_elo_hoy.reshape(-1, 1),
                                  rivales_prev.reshape(-1, 1), fecha,
                                  'rivales anteriores | ELO de hoy')

    # el ELO de hoy en valor absoluto: el empate es más probable en partidos
    # parejos, y ésa es una relación en U que una logística lineal no capta
    print('\n  control: el empate depende de |diferencia|, no de su signo')
    out['abs_elo'] = medir(p, y, None,
                           np.abs(dif_elo_hoy).reshape(-1, 1), fecha,
                           '|ELO_A − ELO_B| (valor absoluto)')

    json.dump(out, open('_v101_descomponer_escalon.json', 'w'), indent=1)
    print('\n-> _v101_descomponer_escalon.json')


if __name__ == '__main__':
    main()
