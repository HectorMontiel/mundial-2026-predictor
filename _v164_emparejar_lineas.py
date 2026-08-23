#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v164 — ¿CUÁNTOS JUGADORES SE QUEDAN SIN SU LÍNEA POR EL NOMBRE?

La casa y ESPN escriben los nombres distinto, y no como los equipos:

    ESPN      «Diego Gómez»
    Playdoit  «Diego Alexander Gomez Amarilla»

`name_mapper` está afinado para CLUBES. Sobre nombres de persona su regla de
contención no ayuda —«diego gomez» no es subcadena de «diego alexander gomez
amarilla»— y la similitud de cadenas se queda en 0,5, por debajo del umbral de
0,78. Resultado: el jugador aparece sin línea aunque la casa sí lo cotiza.

Este script mide cuántos se pierden y compara dos reglas pensadas para
PERSONAS, que es lo que son:

    actual     `name_mapper.mapear` tal cual
    apellidos  todas las palabras del nombre corto están en el largo Y la
               última (el apellido que se usa a diario) coincide

La segunda no se aplica a equipos: vive dentro de `lineas_jugador`, para no
mover ni un emparejado de clubes.

    python _v164_emparejar_lineas.py
"""
import json
import logging
import sys
import unicodedata
import warnings

warnings.filterwarnings('ignore')
logging.basicConfig(level=logging.ERROR)
for _f in (sys.stdout, sys.stderr):
    try:
        _f.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

SALIDA = '_v164_emparejar_lineas.json'


def _norm(s):
    s = unicodedata.normalize('NFKD', str(s or ''))
    s = ''.join(c for c in s if not unicodedata.combining(c)).lower()
    for ch in ".,'-":
        s = s.replace(ch, ' ')
    return ' '.join(s.split())


def por_apellidos(jugador, catalogo):
    """
    Empareja nombres de PERSONA: todas las palabras del corto en el largo, y
    el apellido coincidiendo.

    «diego gomez» contra «diego alexander gomez amarilla»
        palabras del corto: {diego, gomez} -> las dos están     OK
        apellido «gomez» presente                               OK

    «diego gomez» contra «diego alexander lopez amarilla»
        «gomez» no está                                         se descarta

    Se exige el apellido además de la inclusión porque un nombre de pila suelto
    («Diego») lo comparten varios jugadores del mismo partido, y colgarle la
    línea de otro sería peor que no enseñar ninguna.
    """
    obj = _norm(jugador)
    if not obj:
        return None
    t_obj = obj.split()
    candidatos = []
    for c in catalogo:
        t_c = _norm(c).split()
        if not t_c:
            continue
        corto, largo = (t_obj, t_c) if len(t_obj) <= len(t_c) else (t_c, t_obj)
        if not all(p in largo for p in corto):
            continue
        if corto[-1] not in largo:
            continue
        candidatos.append(c)
    # ambiguo = no se elige. Dos jugadores que casan igual de bien es
    # exactamente el caso en el que adivinar sale caro.
    return candidatos[0] if len(candidatos) == 1 else None


def main():
    import fixtures_espn as fx
    import lineas_jugador as lj
    import name_mapper as nm
    import remates_jugador as rjg
    import remates_jugadores as rj

    claves = ['premier', 'laliga', 'serie_a', 'liga_mx', 'ligue_1']
    pares = []
    for clave, lista in (fx.fixtures_multi(claves, dias=2) or {}).items():
        for f in (lista or [])[:2]:
            if f.get('home') and f.get('away'):
                pares.append((clave, f['home'], f['away']))
    pares = pares[:8]
    print('%d partidos\n' % len(pares))

    tot = {'jugadores': 0, 'actual': 0, 'apellidos': 0, 'sin_linea_real': 0}
    ganados = []
    for clave, h, a in pares:
        lineas = lj.del_partido(h, a, permitir_red=True)
        if not lineas:
            print('%-36s la casa no cotiza jugadores' % ('%s-%s' % (h, a))[:36])
            continue
        catalogo = list(lineas)
        for equipo in (h, a):
            try:
                espn = rj.resolver_equipo(clave, equipo)
                d = rj.remates_equipo(clave, espn) if espn else None
            except Exception:
                d = None
            if d is None or getattr(d, 'empty', True):
                continue
            for nombre in d['jugador'].astype(str).tolist():
                tot['jugadores'] += 1
                a1 = (nombre if nombre in lineas
                      else nm.mapear(nombre, catalogo, contexto='m'))
                a2 = a1 or por_apellidos(nombre, catalogo)
                tot['actual'] += int(bool(a1))
                tot['apellidos'] += int(bool(a2))
                if a2 and not a1:
                    ganados.append({'espn': nombre, 'casa': a2})
                if not a2:
                    tot['sin_linea_real'] += 1
        print('%-36s %d jugadores en la casa' % (('%s-%s' % (h, a))[:36],
                                                 len(catalogo)), flush=True)

    n = max(tot['jugadores'], 1)
    print()
    print('%d jugadores de ESPN revisados' % tot['jugadores'])
    print('   emparejados con la regla ACTUAL ....... %4d (%.0f %%)'
          % (tot['actual'], 100.0 * tot['actual'] / n))
    print('   emparejados añadiendo APELLIDOS ....... %4d (%.0f %%)'
          % (tot['apellidos'], 100.0 * tot['apellidos'] / n))
    print('   siguen sin línea ...................... %4d (%.0f %%)'
          % (tot['sin_linea_real'], 100.0 * tot['sin_linea_real'] / n))
    print()
    print('los que gana la regla de apellidos:')
    for g in ganados[:25]:
        print('   %-28s -> %s' % (g['espn'][:28], g['casa']))
    json.dump({'total': tot, 'ganados': ganados},
              open(SALIDA, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('\nescrito %s' % SALIDA)
    return 0


if __name__ == '__main__':
    sys.exit(main())
