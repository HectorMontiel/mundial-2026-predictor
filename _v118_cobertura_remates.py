#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v118 — Vuelve a medir qué competiciones publican remates por jugador.

Por qué se rehace
-----------------
La medición de la v107 (`_v107_cobertura_remates.json`) se hizo con el mismo
fallo que ocultaba: `remates_jugadores` metía la CLAVE DEL PROYECTO en la URL
de ESPN en vez de su CÓDIGO.

    .../soccer/liga_mx/scoreboard   →  400 Bad Request
    .../soccer/mex.1/scoreboard     →  200, 13 partidos

Con la clave equivocada el catálogo de equipos salía vacío, así que la
competición se anotaba como «sin remates» aunque ESPN los publicara. Se ve al
comprobarlo a mano: `brasil` figura como SIN cobertura y devuelve **38
jugadores** con sus remates.

O sea que la tabla no sólo estaba incompleta: estaba mal, y la interfaz le
decía al usuario «ESPN no publica esto» sobre competiciones que sí cubre.

Cómo se mide
------------
Para cada competición activa con código de ESPN se coge un equipo real de su
catálogo y se le piden los remates. Cuenta como CON cobertura si vuelve al
menos un jugador. No se infiere de otra liga ni se supone por el país: se pide
y se mira.

    python _v118_cobertura_remates.py
"""
import json
import sys
import time

for _f in (sys.stdout, sys.stderr):
    try:
        _f.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

SALIDA = '_v107_cobertura_remates.json'      # mismo fichero: lo sustituye


def main() -> int:
    import config
    import remates_jugadores as rj
    from fixtures_espn import ESPN_CODIGOS

    activas = [k for k, c in config.LEAGUES.items() if c.get('disponible')]
    candidatas = [k for k in activas if k in ESPN_CODIGOS]
    print('=' * 78)
    print('v118 — COBERTURA REAL DE REMATES POR JUGADOR')
    print('=' * 78)
    print(f'{len(activas)} competiciones activas · {len(candidatas)} con '
          f'código de ESPN\n')

    con, sin, sin_equipos = [], {}, []
    for i, clave in enumerate(candidatas, 1):
        cod = rj.codigo_espn(clave)
        try:
            equipos = rj.equipos_de_liga(clave)
        except Exception as e:
            equipos = []
            print(f'  [{i:>2}/{len(candidatas)}] {clave:<22} catálogo: '
                  f'{type(e).__name__}')
        if not equipos:
            sin_equipos.append(clave)
            sin[clave] = 'sin catálogo de equipos en ESPN'
            print(f'  [{i:>2}/{len(candidatas)}] {clave:<22} ({cod:<22}) '
                  f'❌ sin equipos')
            continue
        # Se prueban VARIOS equipos antes de declarar que no hay cobertura.
        # Con uno solo la medición es frágil: en Brasil el primero del
        # catálogo (Athletico-PR) no devuelve nada y Palmeiras devuelve 38
        # jugadores. Declarar «ESPN no publica esto» por un equipo que
        # casualmente no jugó en la ventana es el mismo error que se viene a
        # corregir, sólo que más difícil de ver.
        n, eq_ok = 0, None
        for eq in equipos[:3]:
            try:
                df = rj.remates_equipo(clave, eq)
                n = 0 if df is None else len(df)
            except Exception as e:
                n = 0
                print(f'      {clave}/{eq}: {type(e).__name__}: {e}')
            if n:
                eq_ok = eq
                break
        if n:
            con.append(clave)
            print(f'  [{i:>2}/{len(candidatas)}] {clave:<22} ({cod:<22}) '
                  f'✅ {n} jugadores · «{eq_ok}»')
        else:
            sin[clave] = ('ESPN no devuelve rosters con estadística '
                          f'(probados {min(3, len(equipos))} equipos)')
            print(f'  [{i:>2}/{len(candidatas)}] {clave:<22} ({cod:<22}) '
                  f'⛔ sin estadística tras probar '
                  f'{min(3, len(equipos))} equipos')
        sys.stdout.flush()
        time.sleep(0.2)          # no machacar la fuente

    datos = {
        'medido': '2026-08-10',
        'version': 'v118',
        'nota': ('Rehecha tras corregir el uso de la clave del proyecto en '
                 'lugar del código de ESPN, que hacía figurar como «sin '
                 'cobertura» a competiciones que sí la tienen.'),
        'con_remates': sorted(con),
        'sin_remates': sin,
        'n_con': len(con), 'n_sin': len(sin),
    }
    with open(SALIDA, 'w', encoding='utf-8') as f:
        json.dump(datos, f, ensure_ascii=False, indent=2)
    print('\n' + '=' * 78)
    print(f'CON estadística por jugador: {len(con)}')
    print(f'SIN estadística por jugador: {len(sin)}')
    if sin:
        print('  ' + ', '.join(sorted(sin)))
    print(f'\nGuardado en {SALIDA}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
