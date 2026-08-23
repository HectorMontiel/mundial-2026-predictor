#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v163 — QUÉ EQUIPOS NO ENCUENTRAN SU NOMBRE EN ESPN.

`remates_jugadores.resolver_equipo` traduce el nombre del proyecto («Roma») al
que usa ESPN («AS Roma»). Cuando falla devuelve `None` y la sección de
jugadores sale VACÍA para ese equipo, sin aviso y sin error: indistinguible de
«esta competición no la cubre ESPN».

La causa habitual está medida: `name_mapper.normalizar` quita los sufijos
societarios («Roma FC» -> «roma») pero NO los prefijos, así que «Roma» contra
«AS Roma» se queda en 0,73 de similitud y no llega al umbral de 0,78. Tocar el
normalizador arreglaría la familia entera de golpe, pero mueve TODOS los
emparejados del proyecto —cuotas, liquidación, fixtures— y eso es una medición
aparte. Aquí se listan los fallos para resolverlos por alias, que no tiene
efecto fuera de los nombres que se nombran.

    python _v163_resolver_equipos.py
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

SALIDA = '_v163_resolver_equipos.json'
LIGAS = ['premier', 'laliga', 'serie_a', 'bundesliga', 'ligue_1', 'primeira',
         'eredivisie', 'liga_mx', 'turquia', 'gre_super_league',
         'esp_hypermotion', 'ita_serie_b', 'eng_championship']


def main():
    import name_mapper
    import pandas as pd
    import rendimiento_equipos as rq
    import remates_jugadores as rj

    total, fallan = 0, []
    for clave in LIGAS:
        d = rq._historico(clave)
        if d is None or getattr(d, 'empty', True):
            continue
        # los equipos de la última temporada, que son los que juegan hoy
        corte = d['date'].max() - pd.Timedelta(days=400)
        rec = d[d['date'] >= corte]
        equipos = sorted(set(rec['home_team'].astype(str))
                         | set(rec['away_team'].astype(str)))
        catalogo = rj.equipos_de_liga(clave)
        if not catalogo:
            print('%-18s ESPN no devuelve catálogo' % clave)
            continue
        malos = []
        for e in equipos:
            total += 1
            if rj.resolver_equipo(clave, e):
                continue
            mejor, ratio = name_mapper.mejor_candidato(e, catalogo)
            malos.append({'clave': clave, 'proyecto': e, 'mejor_espn': mejor,
                          'ratio': round(float(ratio), 3)})
        fallan.extend(malos)
        print('%-18s %2d equipos, %2d sin resolver%s'
              % (clave, len(equipos), len(malos),
                 ('  ->  ' + ', '.join('%s~%s(%.2f)' % (m['proyecto'],
                                                        m['mejor_espn'],
                                                        m['ratio'])
                                       for m in malos)) if malos else ''),
              flush=True)

    print()
    print('%d equipos revisados, %d sin resolver (%.1f %%)'
          % (total, len(fallan), 100.0 * len(fallan) / max(total, 1)))
    # los que tienen un candidato claro pero se quedan cortos del umbral
    cerca = [m for m in fallan if m['ratio'] >= 0.55]
    print('%d con un candidato de ESPN por encima de 0,55 de similitud'
          % len(cerca))
    json.dump({'total': total, 'fallan': fallan, 'cerca': cerca},
              open(SALIDA, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('escrito %s' % SALIDA)
    return 0


if __name__ == '__main__':
    sys.exit(main())
