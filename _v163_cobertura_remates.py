#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v163 — QUÉ COMPETICIONES TIENEN REMATES OBSERVADOS, HOY, EN ESTE CLON.

No es lo mismo que la cobertura de ESPN. Una competición puede estar cubierta
por el boxscore y aun así salir aquí como «sintética», porque
`stats_espn.inyectar` sólo rellena huecos y el histórico guardado ya traía los
remates escritos por el generador. Eso se arregla solo en el próximo `--build`
—que reconstruye el fichero desde cero—, pero hasta entonces lo que ve el
usuario es lo que dice esta tabla.

Se apoya en `rendimiento_equipos.stats_disponibles`, que no mira si la columna
existe: le pide la columna al generador sintético y la compara valor a valor.

    python _v163_cobertura_remates.py
"""
import json
import logging
import sys
import warnings

warnings.filterwarnings('ignore')
logging.basicConfig(level=logging.ERROR)
for _f in (sys.stdout, sys.stderr):
    try:
        _f.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

SALIDA = '_v163_cobertura_remates.json'


def main():
    import config
    import rendimiento_equipos as re_

    activas = [k for k, c in config.LEAGUES.items() if c.get('disponible')]
    con, sin = [], []
    for clave in sorted(activas):
        try:
            d = re_._historico(clave)
            if d is None or getattr(d, 'empty', True):
                sin.append((clave, 'sin histórico'))
                continue
            disp = re_.stats_disponibles(clave)
        except Exception as e:
            sin.append((clave, type(e).__name__))
            continue
        if disp.get('remates'):
            con.append(clave)
            print('%-24s REMATES OBSERVADOS  (%d filas)' % (clave, len(d)),
                  flush=True)
        else:
            motivo = 'sintéticos' if disp.get('goles') else 'sin datos'
            sin.append((clave, motivo))
            print('%-24s -                   (%s)' % (clave, motivo), flush=True)

    print()
    print('%d de %d competiciones activas con remates observados'
          % (len(con), len(activas)))
    json.dump({'con_remates': con,
               'sin_remates': [{'clave': k, 'motivo': m} for k, m in sin]},
              open(SALIDA, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('escrito %s' % SALIDA)
    return 0


if __name__ == '__main__':
    sys.exit(main())
