#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v152 — QUÉ COMPETICIONES TIENEN CÓRNERS DE VERDAD.

Por qué hace falta
------------------
La bitácora de la v146 dejó escrito que «las 50 ligas disponibles tienen
home_corners/away_corners al 100 % en 2023-2026». Tienen la COLUMNA al 100 %.
Lo que no dice —y decide todo— es quién la escribió: `generate_advanced_metrics`
rellena los huecos con `fillna`, así que un córner de football-data y un córner
inventado por el generador llegan al dataframe indistinguibles.

`rendimiento_equipos._columnas_sinteticas` los distingue reproduciendo el
generador (es determinista por MATCH_ID). Este script pasa esa prueba por todas
las competiciones del proyecto y publica la lista.

Para qué sirve la lista
-----------------------
El plan de negocio es explotar los córners en ligas secundarias. Eso sólo se
puede intentar donde los córners son observados: en el resto, un «modelo de
córners» estaría aprendiendo de la fórmula del propio generador y su backtest
saldría estupendo por construcción.
"""
import glob
import json
import os
import warnings

warnings.filterwarnings('ignore')

import rendimiento_equipos as rq

# Las 20 de football-data 'main' son las que publican HC/AC. El resto del
# catálogo entra igual: la prueba responde por el fichero, no por la etiqueta.
try:
    from config import LEAGUES
except Exception:
    LEAGUES = {}


def main():
    filas = []
    for ruta in sorted(glob.glob('historico_*.csv')):
        clave = os.path.basename(ruta)[len('historico_'):-len('.csv')]
        try:
            d = rq._historico(clave)
            if d is None or d.empty:
                filas.append({'liga': clave, 'n': 0, 'motivo': 'sin histórico usable'})
                continue
            disp = rq.stats_disponibles(clave)
        except Exception as e:
            filas.append({'liga': clave, 'error': '%s: %s' % (type(e).__name__, e)})
            continue
        cfg = LEAGUES.get(clave) or {}
        filas.append({
            'liga': clave, 'n': int(len(d)),
            'formato': cfg.get('formato', '?'),
            'nombre': cfg.get('nombre', clave),
            'pais': cfg.get('pais', ''),
            **{k: bool(v) for k, v in disp.items()},
        })
        print(json.dumps(filas[-1], ensure_ascii=False), flush=True)

    con_ck = [f for f in filas if f.get('corners')]
    print('\n=== CON CÓRNERS OBSERVADOS: %d de %d competiciones ==='
          % (len(con_ck), len(filas)))
    for f in sorted(con_ck, key=lambda x: -x['n']):
        print('  %-22s %-28s %6d partidos  remates=%s tarjetas=%s'
              % (f['liga'], f.get('nombre', '')[:28], f['n'],
                 f.get('remates'), f.get('tarjetas')))
    json.dump(filas, open('_v152_cobertura_stats.json', 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)


if __name__ == '__main__':
    main()
