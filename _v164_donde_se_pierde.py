#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v164 — ¿DÓNDE SE PIERDE LA LAMBDA POR JUGADOR?

`_v164_lambda_contra_casa.py` midió que nuestra lambda por jugador va un 38 %
por debajo de la que implica la casa (mediana de la razón 0,619; el 77 % de los
jugadores por debajo de 0,80). Hay que localizar el sesgo antes de tocar nada,
porque hay tres sitios donde puede estar:

  1. **la lambda del EQUIPO**, que sí está validada (error 0,0131) y no debería;
  2. **el reparto entre jugadores**, o sea la media propia de cada uno;
  3. **la fuente de esa media**: el ROSTER DE TEMPORADA que usa la tarjeta,
     frente a los ÚLTIMOS PARTIDOS que usa la ficha y con los que se midió el
     modelo en la v163 (ECE 0,029).

La prueba que separa las tres: sumar las lambdas de los jugadores de un equipo
y compararla con la lambda del equipo. Si la suma se queda muy corta, el
problema está en el reparto o en la fuente, no en el equipo.

Y la que separa 2 de 3: para los jugadores que están en las DOS fuentes,
comparar sus dos medias.

La sospecha de partida es concreta. El roster de ESPN da `appearances`, que
cuenta también los partidos en los que el jugador entró diez minutos desde el
banquillo. Dividir los remates de la temporada entre esas apariciones da los
remates de un jugador PROMEDIO, no los de un TITULAR — y la línea de la casa
es para el que sale de inicio.

    python _v164_donde_se_pierde.py
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

SALIDA = '_v164_donde_se_pierde.json'


def main():
    import statistics as st
    import lineas_jugador as lj
    import remates_jugador as rjg
    import rendimiento_equipos as rq

    doc = lj.cargar()
    partidos = list((doc.get('partidos') or {}).items())[:14]
    if not partidos:
        print('sin precálculo del día')
        return 1

    print('=' * 78)
    print('1) LA SUMA DE LOS JUGADORES CONTRA LA LAMBDA DEL EQUIPO')
    print('=' * 78)
    razones = []
    for _, d in partidos:
        clave, h, a = d.get('clave_liga'), d.get('home'), d.get('away')
        if not (clave and h and a):
            continue
        eq = rq.remates_equipo(clave, h, a) or {}
        tot = eq.get('totales') or {}
        qr = rjg.partido(clave, h, a, en_vivo=False)
        if not qr or not tot:
            continue
        for lado, lam_eq in (('home', tot.get('lambda_home')),
                             ('away', tot.get('lambda_away'))):
            js = qr.get(lado + '_jugadores') or []
            if not js or not lam_eq:
                continue
            suma = sum(j.get('lambda_tot') or 0 for j in js)
            razones.append(suma / float(lam_eq))
            print('   %-30s %-6s %2d jugadores · suma %5.2f · equipo %5.2f '
                  '(x%.2f)'
                  % (('%s-%s' % (h, a))[:30], lado, len(js), suma,
                     float(lam_eq), suma / float(lam_eq)))
    if razones:
        print()
        print('razón suma_jugadores / lambda_equipo: mediana %.2f'
              % st.median(razones))
        print('   OJO: la lista de jugadores NO es el once —son los que hay en')
        print('   la caché— así que se espera por debajo de 1. Lo que importa')
        print('   es si se queda MUCHO por debajo.')

    print()
    print('=' * 78)
    print('2) LA MISMA MEDIA, EN LAS DOS FUENTES')
    print('=' * 78)
    print('   roster de TEMPORADA (lo que usa la tarjeta) contra')
    print('   ÚLTIMOS PARTIDOS de ESPN (lo que usa la ficha y con lo que se')
    print('   midió el modelo en la v163)')
    print()
    pares = []
    for _, d in partidos[:6]:
        clave, h, a = d.get('clave_liga'), d.get('home'), d.get('away')
        if not (clave and h and a):
            continue
        for equipo in (h, a):
            try:
                de_roster = {x['jugador']: x for x in
                             rjg._de_roster(clave, equipo, solo_cache=True)}
                de_partidos = {x['jugador']: x for x in
                               rjg._de_partidos(clave, equipo)}
            except Exception:
                continue
            for nombre, r in de_roster.items():
                p = de_partidos.get(nombre)
                if not p:
                    continue
                mr, mp = r.get('media_tot'), p.get('media_tot')
                if not mr or not mp:
                    continue
                pares.append({'jugador': nombre, 'clave': clave,
                              'roster': round(float(mr), 3),
                              'partidos': round(float(mp), 3),
                              'razon': round(float(mr) / float(mp), 3)})
    if pares:
        rz = [p['razon'] for p in pares]
        print('   %d jugadores en las dos fuentes' % len(pares))
        print('   media del ROSTER ....... %.3f' % st.mean(
            [p['roster'] for p in pares]))
        print('   media de los PARTIDOS .. %.3f' % st.mean(
            [p['partidos'] for p in pares]))
        print('   razón roster/partidos: mediana %.3f · media %.3f'
              % (st.median(rz), st.mean(rz)))
        print()
        if st.median(rz) < 0.85:
            print('   EL ROSTER SE QUEDA CORTO: la media de temporada por')
            print('   APARICIÓN es menor que la de los últimos partidos, que')
            print('   es la de los TITULARES. Es la sospecha confirmada.')
        elif st.median(rz) > 1.15:
            print('   El roster va POR ENCIMA de los últimos partidos.')
        else:
            print('   Las dos fuentes coinciden: el sesgo no está aquí.')
        print()
        print('   ejemplos:')
        for p in sorted(pares, key=lambda x: x['razon'])[:8]:
            print('      %-26s roster %.2f · partidos %.2f  (x%.2f)'
                  % (p['jugador'][:26], p['roster'], p['partidos'],
                     p['razon']))
    else:
        print('   sin jugadores en las dos fuentes (ESPN no devolvió partidos)')

    json.dump({'razon_equipo': razones, 'pares': pares},
              open(SALIDA, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('\nescrito %s' % SALIDA)
    return 0


if __name__ == '__main__':
    sys.exit(main())
