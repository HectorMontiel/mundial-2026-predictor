#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v189 - CUANTO CUESTA REGENERAR EL LEDGER DE FUTBOL, Y CUANTO GANA.

No escribe encima del ledger bueno. La leccion de la Champions: un script de
medicion que llama a codigo de produccion escribe donde el codigo de produccion
escribe, y ahi se perdieron 895 filas.
"""
import io
import logging
import os
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8',
                              errors='replace')
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s %(levelname)s %(message)s')

DESTINO = os.environ.get('DESTINO_MEDICION') or '_v189_ledger_nuevo.csv'


def main():
    import pandas as pd
    import build_pick_ledger as bpl

    viejo = pd.read_csv('pick_ledger.csv', low_memory=False)
    print('LEDGER ACTUAL')
    print('  filas          %d' % len(viejo))
    print('  ligas          %d' % viejo['liga'].nunique())
    print('  rango          %s  ->  %s' % (viejo['fecha'].min(),
                                           viejo['fecha'].max()))
    print('  con cuota      %d (%.1f%%)'
          % (viejo['cuota_home'].notna().sum(),
             100.0 * viejo['cuota_home'].notna().sum() / len(viejo)))
    print()

    # NO PISAR EL BUENO.
    bpl.SALIDA_CSV = DESTINO
    bpl.SALIDA_META = DESTINO.replace('.csv', '.json')
    print('escribiendo en %s (el bueno no se toca)' % bpl.SALIDA_CSV)
    print()

    t0 = time.time()
    nuevo = bpl.construir()
    tardo = time.time() - t0

    print()
    print('LEDGER REGENERADO   (%.1f min)' % (tardo / 60.0))
    print('  filas          %d   (%+d)' % (len(nuevo), len(nuevo) - len(viejo)))
    print('  ligas          %d   (%+d)' % (nuevo['liga'].nunique(),
                                           nuevo['liga'].nunique()
                                           - viejo['liga'].nunique()))
    print('  rango          %s  ->  %s' % (nuevo['fecha'].min(),
                                           nuevo['fecha'].max()))
    print('  con cuota      %d (%.1f%%)'
          % (nuevo['cuota_home'].notna().sum(),
             100.0 * nuevo['cuota_home'].notna().sum() / len(nuevo)))
    print()

    # Cuantos partidos NUEVOS, o sea posteriores al corte del ledger viejo.
    tope = str(viejo['fecha'].max())
    frescos = nuevo[nuevo['fecha'].astype(str) > tope]
    print('PARTIDOS QUE EL MODELO NO HABIA VISTO NUNCA (> %s)' % tope)
    print('  filas          %d' % len(frescos))
    if len(frescos):
        print('  ligas          %d' % frescos['liga'].nunique())
        print('  con cuota      %d (%.1f%%)'
              % (frescos['cuota_home'].notna().sum(),
                 100.0 * frescos['cuota_home'].notna().sum() / len(frescos)))
        print('  top ligas:')
        for liga, n in frescos['liga'].value_counts().head(10).items():
            print('     %-24s %4d' % (liga, n))
    return 0


if __name__ == '__main__':
    sys.exit(main())
