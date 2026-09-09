#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Devuelve a `historico_leagues_cup.csv` las 6.467 filas que perdio.

El 2026-09-06 el bot nocturno lo dejo en 291 filas: `football-data.co.uk`
devuelve 503 y `leagues_cup.historico()` se quedo sin MLS ni Liga MX, que son
las dos ligas con las que este historico se agrupa a proposito (la competicion
sola tiene 290 partidos, con eso no se entrena nada).

No basta con recuperar la version del 2026-09-03: el fichero degradado traia
partidos de Leagues Cup MAS NUEVOS —esos si llegaron, vienen de ESPN— y
perderlos seria cambiar un agujero por otro. Se juntan los dos y se deduplica
por (fecha, local, visitante), que es la misma llave que usa
`leagues_cup.historico`.
"""
import io
import subprocess
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8',
                              errors='replace')

import pandas as pd

FICHERO = 'historico_leagues_cup.csv'
BUENA = '04e48e4'          # ultimo commit con el agrupado entero


def main():
    actual = pd.read_csv(FICHERO)
    crudo = subprocess.run(['git', 'show', '%s:%s' % (BUENA, FICHERO)],
                           capture_output=True)
    if crudo.returncode != 0:
        print('no se pudo leer %s de %s' % (FICHERO, BUENA))
        return 1
    previo = pd.read_csv(io.BytesIO(crudo.stdout))
    print('en disco ahora: %d filas %s'
          % (len(actual), actual['competicion'].value_counts().to_dict()))
    print('en %s:      %d filas %s'
          % (BUENA, len(previo), previo['competicion'].value_counts().to_dict()))

    # El previo manda en los duplicados: trae las columnas de estadisticas
    # completas. Lo que aporta el actual son los partidos NUEVOS.
    junto = pd.concat([previo, actual], ignore_index=True, sort=False)
    junto['date'] = pd.to_datetime(junto['date'], errors='coerce')
    junto = junto.dropna(subset=['date', 'home_team', 'away_team'])
    junto = (junto.sort_values('date')
                  .drop_duplicates(subset=['date', 'home_team', 'away_team'],
                                   keep='first')
                  .reset_index(drop=True))
    print('resultado:      %d filas %s'
          % (len(junto), junto['competicion'].value_counts().to_dict()))
    nuevos = len(junto) - len(previo)
    print('partidos que aporta el fichero degradado y se conservan: %d'
          % nuevos)
    if len(junto) < len(previo):
        print('ABORTA: el resultado tiene menos filas que el punto bueno')
        return 1
    junto.to_csv(FICHERO, index=False)
    comprobar = pd.read_csv(FICHERO)
    ok = len(comprobar) == len(junto) and len(comprobar) > 6000
    print('escrito y verificado: %d filas' % len(comprobar) if ok
          else 'FALLO al escribir')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
