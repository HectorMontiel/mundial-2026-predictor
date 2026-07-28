#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v77 — ¿Qué partidos NO llegó siquiera a evaluar el barrido, y por qué?

Complementa a `v77_auditar_capa1.py`: aquel explica por qué un candidato no
pasó los filtros; este explica por qué un partido ni siquiera llegó a ser
candidato. Son causas distintas y se confunden con facilidad.

Las tres razones reales, en orden de frecuencia:
  1. **La liga no juega hoy** (parón, pretemporada). No es un fallo.
  2. **El nombre del equipo no se resolvió** contra el catálogo del modelo.
     Esto sí es un fallo, y se puede arreglar añadiendo un alias.
  3. **Ninguna casa publica cuota** para ese partido todavía.

Uso:
    python v77_auditar_no_evaluados.py
    python v77_auditar_no_evaluados.py --solo-nombres   # solo el caso 2
"""
import argparse
import collections
import json
import logging
import os
import sys

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass


def main(solo_nombres=False):
    logging.basicConfig(level=logging.WARNING)
    import fixtures_espn
    import name_mapper
    from config import LEAGUES
    from league_engine import ClubEngine

    claves = [c for c, cfg in LEAGUES.items()
              if cfg.get('disponible') and c in fixtures_espn.ESPN_CODIGOS]
    fixtures = fixtures_espn.fixtures_multi(claves)

    sin_partidos, sin_nombre, ok = [], collections.defaultdict(list), {}
    for clave in claves:
        fx = fixtures.get(clave) or []
        if not fx:
            sin_partidos.append(clave)
            continue
        try:
            eng = ClubEngine(clave)
            catalogo = list(eng.stats.keys()) if getattr(eng, 'listo', False) else []
        except Exception as e:
            sin_nombre[clave].append(f'(motor no carga: {type(e).__name__})')
            continue
        if not catalogo:
            sin_nombre[clave].append('(catálogo del modelo vacío)')
            continue
        n_ok = 0
        for f in fx:
            h = name_mapper.mapear(f['home'], catalogo, contexto=f'audit→{clave}')
            a = name_mapper.mapear(f['away'], catalogo, contexto=f'audit→{clave}')
            if h and a:
                n_ok += 1
            else:
                falla = f['home'] if not h else f['away']
                sin_nombre[clave].append(falla)
        ok[clave] = (n_ok, len(fx))

    if not solo_nombres:
        print(f"=== LIGAS SIN PARTIDOS HOY ({len(sin_partidos)}) ===")
        print("   (parón de temporada o jornada en otro día — no es un fallo)")
        print('   ' + ', '.join(sorted(sin_partidos)) + '\n')
        print(f"=== LIGAS CON PARTIDOS ({len(ok)}) ===")
        for c, (n, t) in sorted(ok.items(), key=lambda x: x[1][0] - x[1][1]):
            marca = '  ' if n == t else '⚠ '
            print(f" {marca}{c:24s} {n}/{t} partidos con los dos equipos resueltos")

    total_fallos = sum(len(v) for v in sin_nombre.values())
    print(f"\n=== NOMBRES SIN RESOLVER ({total_fallos}) ===")
    if not total_fallos:
        print("   Ninguno. Todos los equipos del día se enlazaron con el modelo.")
    for c, nombres in sorted(sin_nombre.items(), key=lambda x: -len(x[1])):
        print(f"\n  {c} ({len(nombres)}):")
        for n in sorted(set(nombres)):
            print(f"     · {n}")
    if total_fallos:
        print("\n  Cómo arreglarlo: añade el alias en `alias_manuales.json` "
              "(nombre de ESPN -> nombre del catálogo del modelo) y vuelve a "
              "ejecutar. `name_mapper.volcar_fallos()` deja el registro completo.")


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--solo-nombres', action='store_true')
    a = ap.parse_args()
    main(a.solo_nombres)
