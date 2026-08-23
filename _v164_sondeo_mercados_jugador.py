#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v164 — ¿COTIZA PLAYDOIT LOS REMATES POR JUGADOR?

El encargo pide la línea de la casa para «Más de 1,5 remates (Fulano)» y deja
libertad para buscar otra fuente si Playdoit no la publica. Antes de irse a
buscar APIs de pago conviene mirar lo que ya se tiene: Playdoit SÍ publica
familias por jugador —`snapshots_tarjetas` las descarta a propósito, con el
filtro `_DE_JUGADOR`, porque no hay con qué liquidarlas— así que la pregunta no
es si existen mercados de jugador, sino si entre ellos están los de remates.

Este script vuelca el tablero REAL de varios partidos y clasifica sus familias:

    · cuántas son de jugador
    · de ésas, cuántas son de remates / tiros a puerta
    · qué rótulo exacto usan y qué líneas cotizan

No se supone nada del formato: se imprime lo que llega.

    python _v164_sondeo_mercados_jugador.py [n_partidos]
"""
import json
import logging
import re
import sys
import warnings
from collections import Counter

warnings.filterwarnings('ignore')
logging.basicConfig(level=logging.ERROR)
for _f in (sys.stdout, sys.stderr):
    try:
        _f.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

SALIDA = '_v164_sondeo_mercados_jugador.json'

_DE_JUGADOR = re.compile(r'\b(jugador|player|jugadores)\b', re.I)
_REMATE = re.compile(r'\b(remates?|disparos?|tiros?|shots?)\b', re.I)
_NO_ES = re.compile(r'\b(esquinas?|c[oó]rner(?:s|es)?|saques?|libres?|'
                    r'penal(?:ti|ty)(?:s|es)?|faltas?)\b', re.I)


def main():
    import cuotas_multi as cm
    import fixtures_espn as fx

    tope = int(sys.argv[1]) if len(sys.argv) > 1 else 8
    claves = ['premier', 'laliga', 'serie_a', 'liga_mx', 'ligue_1',
              'bundesliga', 'mls', 'brasil']
    fixtures = []
    por_liga = fx.fixtures_multi(claves, dias=2)
    for clave, lista in (por_liga or {}).items():
        for f in (lista or [])[:3]:
            fixtures.append((clave, f.get('home'), f.get('away')))
    fixtures = fixtures[:tope]
    print('%d partidos a sondear\n' % len(fixtures))

    total_fam, con_jugador, con_remate = Counter(), [], []
    detalle = []
    for clave, h, a in fixtures:
        try:
            tab = cm.mercados_playdoit('futbol', h, a) or {}
        except Exception as e:
            print('%-34s ERROR %s' % ('%s-%s' % (h, a), type(e).__name__))
            continue
        fams = tab.get('mercados') or []
        if not fams:
            print('%-34s sin tablero' % ('%s-%s' % (h, a))[:34])
            continue
        nj = nr = 0
        for fam in fams:
            nombre = str((fam or {}).get('nombre') or '')
            total_fam[nombre] += 1
            es_jug = bool(_DE_JUGADOR.search(nombre)) or '(' in nombre
            if es_jug:
                nj += 1
                con_jugador.append(nombre)
            if (_REMATE.search(nombre) and not _NO_ES.search(nombre)):
                nr += 1
                con_remate.append(nombre)
                sel = [(str(s.get('nombre')), s.get('cuota'))
                       for s in (fam.get('selecciones') or [])[:4]]
                detalle.append({'clave': clave, 'partido': '%s-%s' % (h, a),
                                'familia': nombre, 'sv': fam.get('sv'),
                                'selecciones': sel,
                                'de_jugador': bool(es_jug)})
        print('%-34s %4d familias · %3d de jugador · %2d de remates'
              % (('%s-%s' % (h, a))[:34], len(fams), nj, nr), flush=True)

    print()
    print('=' * 78)
    print('FAMILIAS DE REMATES ENCONTRADAS')
    print('=' * 78)
    if not con_remate:
        print('NINGUNA. Playdoit no cotiza remates en estos partidos.')
    for nombre, n in Counter(con_remate).most_common(30):
        print('   %-58s x%d' % (nombre[:58], n))

    print()
    print('=' * 78)
    print('MUESTRA DE LÍNEAS')
    print('=' * 78)
    for d in detalle[:14]:
        print('   %-46s sv=%-6s %s'
              % (d['familia'][:46], d['sv'],
                 ', '.join('%s@%s' % (n, c) for n, c in d['selecciones'][:3])))

    print()
    print('=' * 78)
    print('LAS 25 FAMILIAS MÁS FRECUENTES (para ver qué SÍ publica)')
    print('=' * 78)
    for nombre, n in total_fam.most_common(25):
        print('   %-62s x%d' % (nombre[:62], n))

    # Se guarda el RESUMEN, no el volcado. El diccionario entero de familias
    # son 13.769 nombres y 2 MB, y este fichero se commitea para documentar la
    # decisión: lo que hay que poder releer es cuántas familias de remates hay
    # y qué pinta tienen, no el catálogo de la casa — que además cambia cada
    # temporada y se regenera corriendo el script.
    json.dump({'n_familias_distintas': len(total_fam),
               'n_de_jugador': len(set(con_jugador)),
               'familias_de_remates': dict(Counter(con_remate).most_common(60)),
               'muestra_de_lineas': detalle[:40],
               'top_familias': dict(total_fam.most_common(30))},
              open(SALIDA, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('\nescrito %s' % SALIDA)
    return 0


if __name__ == '__main__':
    sys.exit(main())
