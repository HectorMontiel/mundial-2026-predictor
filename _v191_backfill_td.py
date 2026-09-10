#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v191 - RELLENA `home_td`/`away_td` EN EL HISTORICO DE NFL.

Los touchdowns no estaban: ESPN no los publica como estadistica de equipo y el
boxscore solo trae `defensiveTouchdowns`. Salen de `scoringPlays`, que viene en
el mismo `summary` que `nfl_datos.resumen_partido` ya descarga.

Se escribe con el modulo `csv`, NO con pandas: `to_csv` recorta el ultimo
digito de los flotantes y reescribe filas que no han cambiado. Aqui todas las
filas ganan dos columnas, asi que el fichero se rehace igualmente, pero los
valores que ya estaban se copian TAL CUAL.
"""
import csv
import io
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8',
                              errors='replace')

RUTA = 'historico_nfl.csv'


def main():
    import nfl_datos as nd

    with io.open(RUTA, encoding='utf-8', newline='') as f:
        filas = list(csv.reader(f))
    if not filas:
        print('historico vacio')
        return 1
    cab = filas[0]
    if 'event_id' not in cab:
        print('el historico no tiene event_id')
        return 1
    i_ev = cab.index('event_id')

    ya = ('home_td' in cab)
    if ya:
        i_th, i_ta = cab.index('home_td'), cab.index('away_td')
    else:
        cab += ['home_td', 'away_td']
        i_th, i_ta = len(cab) - 2, len(cab) - 1
        for n in range(1, len(filas)):
            filas[n] += ['', '']

    print('partidos en el historico: %d' % (len(filas) - 1))
    hechos = fallos = saltados = 0
    t0 = time.time()
    for n in range(1, len(filas)):
        fila = filas[n]
        if len(fila) <= i_ta:
            continue
        if (fila[i_th] or '').strip():
            saltados += 1
            continue
        ev = (fila[i_ev] or '').strip()
        if not ev:
            continue
        try:
            r = nd.resumen_partido(ev)
        except Exception:
            r = None
        if not r or r.get('home_td') is None:
            fallos += 1
            continue
        fila[i_th] = str(int(r['home_td']))
        fila[i_ta] = str(int(r['away_td']))
        hechos += 1
        if hechos % 100 == 0:
            print('   %d rellenados (%.1f min)' % (hechos, (time.time() - t0) / 60))

    with io.open(RUTA, 'w', encoding='utf-8', newline='') as f:
        w = csv.writer(f, lineterminator='\n')
        w.writerow(cab)
        w.writerows(filas[1:])

    print()
    print('rellenados: %d | ya tenian: %d | sin dato: %d | %.1f min'
          % (hechos, saltados, fallos, (time.time() - t0) / 60))
    return 0


if __name__ == '__main__':
    sys.exit(main())
