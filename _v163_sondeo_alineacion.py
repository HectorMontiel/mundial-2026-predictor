#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v163 — ¿HAY ALINEACIÓN ANTES DEL PARTIDO?

El encargo dice «usar el `goleadores_cache.json` (ya precalculado) para obtener
los titulares de cada equipo». Antes de construir nada encima conviene
comprobar dos cosas que no son lo mismo:

  1. Lo que hay en `goleadores_cache.json` es el ROSTER DE TEMPORADA de ESPN
     —la plantilla entera con sus totales— no el once inicial de un partido.
     Ahí no hay alineación que sacar, ni la habrá: ese endpoint no depende del
     partido.

  2. La alineación de un partido concreto vive en el `summary` del evento,
     dentro de `rosters[].roster[].starter`. La pregunta es cuándo aparece: si
     ESPN sólo la publica al empezar el partido, «alineación probable» hay que
     construirla de otra forma o no prometerla.

Este script recorre los partidos de HOY y de los próximos días en varias
competiciones, pide el `summary` de cada uno y anota si trae once inicial,
cuántas horas faltan para el saque y si el partido ya terminó.

    python _v163_sondeo_alineacion.py
"""
import json
import logging
import sys
import warnings

import pandas as pd

warnings.filterwarnings('ignore')
logging.basicConfig(level=logging.ERROR)
for _f in (sys.stdout, sys.stderr):
    try:
        _f.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

SALIDA = '_v163_sondeo_alineacion.json'
CODIGOS = ['eng.1', 'esp.1', 'ita.1', 'ger.1', 'fra.1', 'mex.1', 'usa.1',
           'bra.1', 'arg.1', 'por.1', 'ned.1', 'tur.1']


def main():
    import remates_jugadores as rj

    hoy = pd.Timestamp.now(tz='UTC').normalize()
    ini = hoy - pd.Timedelta(days=1)
    fin = hoy + pd.Timedelta(days=4)
    filas = []
    for code in CODIGOS:
        j = rj._get(rj.BASE.format(liga=code) + '/scoreboard',
                    {'dates': '%s-%s' % (ini.strftime('%Y%m%d'),
                                         fin.strftime('%Y%m%d')),
                     'limit': 200})
        if not j:
            print('%-10s scoreboard sin respuesta' % code, flush=True)
            continue
        eventos = j.get('events') or []
        print('%-10s %d partidos en la ventana' % (code, len(eventos)),
              flush=True)
        for ev in eventos:
            est = ((ev.get('status') or {}).get('type') or {})
            cuando = pd.to_datetime(ev.get('date'), errors='coerce', utc=True)
            horas = (float((cuando - pd.Timestamp.now(tz='UTC'))
                           .total_seconds()) / 3600.0
                     if cuando is not pd.NaT else None)
            s = rj._get(rj.BASE.format(liga=code) + '/summary',
                        {'event': ev['id']})
            titulares, con_stats = 0, 0
            for ro in (s or {}).get('rosters', []):
                for a in (ro.get('roster') or []):
                    if a.get('starter'):
                        titulares += 1
                    st = {x.get('abbreviation') for x in (a.get('stats') or [])}
                    if 'SHOT' in st:
                        con_stats += 1
            filas.append({
                'code': code, 'id': ev['id'], 'nombre': ev.get('shortName'),
                'estado': est.get('name'), 'terminado': bool(est.get('completed')),
                'horas_para_el_saque': round(horas, 2) if horas is not None else None,
                'titulares': titulares, 'jugadores_con_stats': con_stats,
            })
            print('   %-22s %-22s h=%8s  titulares=%2d  con_stats=%2d'
                  % (ev.get('shortName'), est.get('name'),
                     ('%.1f' % horas) if horas is not None else '?',
                     titulares, con_stats), flush=True)

    d = pd.DataFrame(filas)
    print()
    if len(d):
        fut = d[~d['terminado']]
        pas = d[d['terminado']]
        print('TERMINADOS: %d, de los que %d traen once inicial (%.0f %%)'
              % (len(pas), int((pas['titulares'] >= 22).sum()),
                 100.0 * (pas['titulares'] >= 22).mean() if len(pas) else 0))
        print('POR JUGAR : %d, de los que %d traen once inicial (%.0f %%)'
              % (len(fut), int((fut['titulares'] >= 22).sum()),
                 100.0 * (fut['titulares'] >= 22).mean() if len(fut) else 0))
        if len(fut):
            print('\npor jugar, por antelación:')
            for lo, hi in ((0, 2), (2, 6), (6, 24), (24, 1e9)):
                sub = fut[(fut['horas_para_el_saque'] >= lo)
                          & (fut['horas_para_el_saque'] < hi)]
                if len(sub):
                    print('   %5.0f-%5.0f h antes: %2d partidos, %2d con once '
                          '(%.0f %%)'
                          % (lo, min(hi, 999), len(sub),
                             int((sub['titulares'] >= 22).sum()),
                             100.0 * (sub['titulares'] >= 22).mean()))
    json.dump(filas, open(SALIDA, 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    print('escrito %s' % SALIDA)
    return 0


if __name__ == '__main__':
    sys.exit(main())
