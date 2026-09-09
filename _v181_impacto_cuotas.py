#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Cuantos partidos pasan a tener apuesta con precio tras guardar el respaldo.

ANTES (barrido del dia, medido sobre el pkl del guardia):

    futbol HOY                       39 partidos
      con tablero de la casa         37  (95 %)
      con apuesta recomendada        28  (72 %)
      Champions                       3 de 9

Y los tres de Champions que fallaban —PSG-Slovan, Napoli-Arsenal y
Sporting-Galatasaray— tenian modelo y tenian precio de ESPN: lo que faltaba era
que ese precio se GUARDARA en las implicitas.

Este script rehace el barrido con el codigo nuevo y vuelve a contar.
"""
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8',
                              errors='replace')

import pandas as pd

import horario
import modo_modelo as mm


def main():
    import alpha_finder
    import guardia_barrido
    r = guardia_barrido.barrido(alpha_finder.apuestas_del_dia_universal,
                                forzar=True) or {}
    hoy = horario.fecha(pd.Timestamp.now('UTC'))
    prons = [p for p in (r.get('pronosticos') or []) if isinstance(p, dict)]

    def dia(p):
        return horario.fecha(p.get('inicio')) or str(p.get('fecha') or '')[:10]

    de_hoy = [p for p in prons
              if dia(p) == hoy and str(p.get('deporte') or 'Fútbol') == 'Fútbol']
    con_impl = sum(1 for p in de_hoy if p.get('implicitas'))
    con_cuotas = sum(1 for p in de_hoy
                     if (p.get('implicitas') or {}).get('1x2_cuotas'))
    n_rec = n_cuota = n_verde = 0
    for p in de_hoy:
        rec = mm.recomendadas(p, None, n=3)
        if rec:
            n_rec += 1
            if rec[0].get('cuota'):
                n_cuota += 1
            if rec[0].get('verde'):
                n_verde += 1
    print('futbol HOY: %d partidos' % len(de_hoy))
    print('  con implicitas:                %3d (%.0f %%)'
          % (con_impl, 100 * con_impl / max(len(de_hoy), 1)))
    print('  con 1x2_cuotas (el arreglo):   %3d (%.0f %%)'
          % (con_cuotas, 100 * con_cuotas / max(len(de_hoy), 1)))
    print('  con apuesta recomendada:       %3d (%.0f %%)'
          % (n_rec, 100 * n_rec / max(len(de_hoy), 1)))
    print('  con CUOTA en la recomendada:   %3d' % n_cuota)
    print('  en VERDE:                      %3d' % n_verde)

    print()
    print('CHAMPIONS, uno por uno:')
    ch = [p for p in prons if 'Champions League' in str(p.get('liga'))]
    ok = 0
    for p in ch:
        rec = mm.recomendadas(p, None, n=3)
        cu = (p.get('implicitas') or {}).get('1x2_cuotas')
        if rec:
            ok += 1
        print('  %-42s %-4s cuotas=%-3s rec=%d %s'
              % (str(p.get('partido'))[:42], p.get('prob'),
                 'si' if cu else 'NO', len(rec),
                 (rec[0].get('apuesta', '') + ' @ ' + str(rec[0].get('cuota')))
                 if rec else ''))
    print('  -> %d de %d con apuesta' % (ok, len(ch)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
