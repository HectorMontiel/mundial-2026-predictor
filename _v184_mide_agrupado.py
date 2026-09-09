#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
¿Mejora el modelo de una copa si se entrena con las ligas de sus participantes?

EL PRECEDENTE es la Leagues Cup, que ya lo hace: su historico agrupado (MLS +
Liga MX + Leagues Cup) tiene 6.759 filas y su motor conoce a todos sus equipos.

LA DUDA es si eso escala. La Leagues Cup agrupa DOS ligas de nivel parecido; la
Champions agruparia dieciocho, de la Premier a la noruega, y el modelo tendria
que separar el nivel por su cuenta.

QUE SE COMPARA. `entrenar_liga` mide siempre su precision contra una linea base
ELO sobre el mismo conjunto de validacion. Se entrena la copa de las dos formas
y se mira:

    acc          precision del modelo
    elo          la linea base de ese mismo conjunto
    margen       acc - elo   <- lo unico que decide si el modelo aporta

Un modelo que sube su `acc` porque el conjunto de validacion es mas facil no ha
mejorado: por eso se compara el MARGEN, no la precision suelta.

CUIDADO, Y COSTO UN SUSTO: `entrenar_liga` NO SOLO ESCRIBE EL MODELO.
Tambien reescribe `historico_<clave>.csv` con lo que le devuelva
`descargar_liga`. Al parchear esa funcion para que devuelva el agrupado, este
script dejo `historico_champions.csv` con **53.264 filas en vez de 895** — el
agrupado entero, encima del historico de produccion. La guarda de la v178.9 no
lo impidio porque solo vigila que un historico no ENCOJA, y este crecio.

Por eso ahora se respalda y se restaura tambien el CSV, no solo la carpeta de
modelos. Y por eso este script avisa: cualquier medicion que llame a
`entrenar_liga` escribe en produccion.
"""
import io
import json
import os
import shutil
import sys
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8',
                              errors='replace')

COPAS = sys.argv[1:] or ['champions']


def entrena(clave, agrupado, destino):
    import league_engine as le
    import historico_agrupado as ha
    original = le.descargar_liga
    if agrupado:
        def parche(c, temporadas=None, *a, **k):
            if c == clave:
                return ha.construir(c)
            return original(c, temporadas, *a, **k) if temporadas is not None \
                else original(c, *a, **k)
        le.descargar_liga = parche
    try:
        os.environ['FORZAR_REENTRENO'] = '1'
        le.FORZAR_REENTRENO = True
        md = le.entrenar_liga(clave)
        return md or {}
    except Exception as e:
        return {'error': '%s: %s' % (type(e).__name__, str(e)[:120])}
    finally:
        le.descargar_liga = original


def main():
    for clave in COPAS:
        print('=' * 70)
        print('  %s' % clave.upper())
        print('=' * 70)
        # se guarda el modelo actual para poder restaurarlo
        carpeta = os.path.join('modelos', clave)
        respaldo = tempfile.mkdtemp(prefix='modelo_%s_' % clave)
        if os.path.isdir(carpeta):
            shutil.copytree(carpeta, os.path.join(respaldo, clave))
        # Y EL CSV, que `entrenar_liga` tambien reescribe.
        csv = 'historico_%s.csv' % clave
        csv_respaldo = os.path.join(respaldo, os.path.basename(csv))
        if os.path.exists(csv):
            shutil.copy2(csv, csv_respaldo)
        filas = []
        for etiqueta, agrupado in (('actual', False), ('agrupado', True)):
            md = entrena(clave, agrupado, None)
            if md.get('error'):
                print('  %-10s %s' % (etiqueta, md['error']))
                filas.append((etiqueta, None, None, None, None))
                continue
            acc = md.get('precision_validacion')
            elo = md.get('precision_linea_base_elo')
            n = md.get('n_train')
            margen = (acc - elo) if (acc is not None and elo is not None) else None
            filas.append((etiqueta, n, acc, elo, margen))
            print('  %-10s n_train %6s · acc %.4f · ELO %.4f · margen %+.4f'
                  % (etiqueta, n, acc or 0, elo or 0, margen or 0))
        # restaurar el modelo de produccion
        if os.path.isdir(os.path.join(respaldo, clave)):
            if os.path.isdir(carpeta):
                shutil.rmtree(carpeta)
            shutil.copytree(os.path.join(respaldo, clave), carpeta)
            print('  (modelo de produccion restaurado)')
        if os.path.exists(csv_respaldo):
            shutil.copy2(csv_respaldo, csv)
            print('  (historico de produccion restaurado)')
        if len(filas) == 2 and filas[0][4] is not None and filas[1][4] is not None:
            d = filas[1][4] - filas[0][4]
            print()
            print('  VEREDICTO: el agrupado %s el margen sobre el ELO (%+.4f)'
                  % ('MEJORA' if d > 0 else 'EMPEORA', d))
    return 0


if __name__ == '__main__':
    sys.exit(main())
