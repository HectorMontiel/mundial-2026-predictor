#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Mide por que «Solo alta probabilidad» deja la vista de MANANA en cero.

Lee el barrido que el guardia dejo en disco —no vuelve a barrer— y cuenta,
para hoy y para manana por separado:

    partidos · con cuota · con recomendada · en VERDE

Si en manana el verde es estructuralmente cero, la casilla de esa vista es un
filtro que nunca puede dejar nada, y eso hay que decirlo en la pantalla.
"""
import io
import pickle
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8',
                              errors='replace')

import pandas as pd

import horario
import modo_modelo

ARCHIVO = '.cache_barrido.pkl'


def fecha_local(p):
    return horario.fecha(p.get('inicio')) or str(p.get('fecha') or '')[:10]


def main():
    with open(ARCHIVO, 'rb') as f:
        sobre = pickle.load(f)
    r = sobre.get('datos') or {}
    prons = [p for p in (r.get('pronosticos') or []) if isinstance(p, dict)]
    hoy = horario.fecha(pd.Timestamp.now('UTC'))
    man = str(pd.Timestamp(hoy).date() + pd.Timedelta(days=1))
    print('barrido de %s · %d pronosticos' % (
        pd.Timestamp(sobre.get('ts'), unit='s'), len(prons)))
    for etiqueta, dia in (('HOY', hoy), ('MANANA', man)):
        lote = [p for p in prons if fecha_local(p) == dia]
        con_cuota = sum(1 for p in lote if p.get('cuota'))
        recs = [modo_modelo.recomendadas(p, None,
                                         n=modo_modelo.MAX_RECOMENDADAS)
                for p in lote]
        con_rec = sum(1 for rr in recs if rr)
        verdes = sum(1 for rr in recs if (rr or [{}])[0].get('verde'))
        print('  %-7s %s · %3d partidos · %3d con cuota · %3d con '
              'recomendada · %3d en VERDE'
              % (etiqueta, dia, len(lote), con_cuota, con_rec, verdes))
    return 0


if __name__ == '__main__':
    sys.exit(main())
