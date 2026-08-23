#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v163 — ¿CASAN LOS NOMBRES DEL ONCE DE FOTMOB CON LOS DE ESPN?

Por qué hace falta medirlo
--------------------------
Las dos fuentes son distintas y escriben distinto: FotMob dice «Bruno
Guimarães» donde ESPN dice «Bruno Guimaraes», y a veces recorta el nombre de
pila. Si el emparejado falla, el once se queda a medias y la tabla enseña seis
jugadores diciendo que son los titulares — que es peor que no enseñar nada,
porque parece completo.

En la primera prueba de `remates_jugador` casaron 6 de 11 en los dos equipos de
Fulham-Chelsea. Este script separa las tres causas posibles, que exigen
arreglos distintos:

    ausente     el jugador NO está en los últimos partidos de ESPN (fichaje
                nuevo, lesionado que vuelve, canterano que debuta). No hay nada
                que emparejar: es un hueco real de datos.
    filtrado    está, pero con menos apariciones de las que pide
                `MIN_APARICIONES`. Decisión nuestra, no un fallo.
    sin_casar   está y con muestra suficiente, y aun así el `name_mapper` no lo
                encuentra. Esto SÍ es un fallo y es el único que hay que
                arreglar.

    python _v163_emparejado_jugadores.py [fecha]
"""
import json
import logging
import sys
import unicodedata
import warnings

import pandas as pd

warnings.filterwarnings('ignore')
logging.basicConfig(level=logging.ERROR)
for _f in (sys.stdout, sys.stderr):
    try:
        _f.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

SALIDA = '_v163_emparejado_jugadores.json'
# competiciones donde FotMob publica once probable y ESPN publica jugadores
LIGAS = [('premier', 'Premier League'), ('laliga', 'LaLiga'),
         ('serie_a', 'Serie A'), ('liga_mx', 'Liga MX'),
         ('ligue_1', 'Ligue 1'), ('primeira', 'Primeira Liga')]
MAX_PARTIDOS = 14


def _norm(s):
    s = unicodedata.normalize('NFKD', str(s or ''))
    return ''.join(c for c in s if not unicodedata.combining(c)).lower().strip()


def main():
    import remates_jugador as rjg
    import remates_jugadores as rj
    import arbitro_partido as ap

    fecha = sys.argv[1] if len(sys.argv) > 1 else (
        pd.Timestamp.now(tz='UTC') + pd.Timedelta(days=1)).strftime('%Y-%m-%d')
    idx = ap.indice_dia(fecha)
    print('%s: %d partidos en FotMob' % (fecha, len(idx)))
    nombres_liga = {n: k for k, n in LIGAS}
    cand = [m for m in idx if m.get('liga') in nombres_liga][:MAX_PARTIDOS]
    print('%d en competiciones con once probable y jugadores de ESPN\n'
          % len(cand))

    total = {'once': 0, 'casados': 0, 'ausente': 0, 'filtrado': 0,
             'sin_casar': 0}
    detalle = []
    for m in cand:
        clave = nombres_liga[m['liga']]
        al = rjg.alineacion(fecha, m['home'], m['away'], permitir_red=True)
        if not al:
            print('%-38s sin once publicado' % ('%s-%s' % (m['home'], m['away'])))
            continue
        for lado, equipo in (('home', m['home']), ('away', m['away'])):
            once = al.get(lado) or []
            espn = rj.resolver_equipo(clave, equipo)
            crudo = rj.remates_equipo(clave, espn) if espn else None
            if crudo is None or getattr(crudo, 'empty', True):
                print('%-30s %-6s ESPN no devuelve jugadores' % (equipo, lado))
                continue
            catalogo = [str(x) for x in crudo['jugador'].tolist()]
            normal = {_norm(x): x for x in catalogo}
            apar = dict(zip(crudo['jugador'].astype(str),
                            crudo['partidos'].astype(float)))
            usables = [x for x in catalogo
                       if apar.get(x, 0) >= rjg.MIN_APARICIONES]
            pares = rjg.casar_once_detalle(
                once, [{'jugador': x} for x in usables])
            casados = pares
            fila = {'partido': '%s-%s' % (m['home'], m['away']),
                    'equipo': equipo, 'lado': lado, 'once': len(once),
                    'casados': len(casados), 'problemas': []}
            for n in once:
                if n in casados:
                    continue
                # ¿existe en ESPN aunque el mapeador no lo haya encontrado?
                en_espn = normal.get(_norm(n))
                if en_espn is None:
                    # último recurso: por apellido, que es como difieren
                    ape = _norm(n).split()[-1] if _norm(n).split() else ''
                    hits = [c for c in catalogo
                            if ape and _norm(c).split()
                            and _norm(c).split()[-1] == ape]
                    en_espn = hits[0] if len(hits) == 1 else None
                if en_espn is None:
                    causa = 'ausente'
                elif apar.get(en_espn, 0) < rjg.MIN_APARICIONES:
                    causa = 'filtrado'
                else:
                    causa = 'sin_casar'
                total[causa] += 1
                fila['problemas'].append({'nombre': n, 'causa': causa,
                                          'en_espn': en_espn})
            total['once'] += len(once)
            total['casados'] += len(casados)
            detalle.append(fila)
            print('%-30s %-5s once=%2d casados=%2d  %s'
                  % (equipo[:30], lado, len(once), len(casados),
                     ', '.join('%s[%s]' % (p['nombre'], p['causa'])
                               for p in fila['problemas'])[:70]), flush=True)

    print()
    if total['once']:
        print('TOTAL: %d nombres de once, %d casados (%.0f %%)'
              % (total['once'], total['casados'],
                 100.0 * total['casados'] / total['once']))
        for c in ('ausente', 'filtrado', 'sin_casar'):
            print('   %-10s %3d (%.0f %%)'
                  % (c, total[c], 100.0 * total[c] / total['once']))
        print()
        if total['sin_casar']:
            print('HAY %d FALLOS DE EMPAREJADO QUE ARREGLAR.' % total['sin_casar'])
        else:
            print('Ningún fallo de emparejado: lo que falta, falta en la '
                  'fuente.')
    json.dump({'fecha': fecha, 'total': total, 'detalle': detalle},
              open(SALIDA, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('escrito %s' % SALIDA)
    return 0


if __name__ == '__main__':
    sys.exit(main())
