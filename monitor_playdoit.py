#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v78 — Monitor de cobertura de Playdoit (Altenar).

Para qué
--------
Playdoit es la casa donde apuesta el usuario, así que su cobertura decide qué
picks son *tomables*. Pero el catálogo de Altenar cambia solo: aparecen
competiciones nuevas, desaparecen otras al acabar la temporada, y nadie avisa.
Sin vigilancia, una liga puede pasar meses emitiendo picks que solo existen en
Pinnacle o Bovada — es decir, EV que el usuario no puede cobrar.

Qué hace
--------
1. Vuelca el catálogo de competiciones de Playdoit por deporte.
2. Lo cruza con las ligas activas del proyecto (vía el nombre que publica
   Altenar y el que usa `config.LEAGUES`), y marca cuáles quedan descubiertas.
3. Compara con la ejecución anterior y reporta ALTAS y BAJAS, que es lo
   accionable: una competición nueva puede incorporarse, y una que desaparece
   explica por qué sus picks dejaron de tener precio tomable.

Se ejecuta en el workflow diario y deja el resultado en `playdoit_cobertura.json`
para que la UI lo muestre en el registro de incidencias.

Uso:
    python monitor_playdoit.py
"""

import datetime as dt
import json
import logging
import os
import sys
from typing import Dict, List

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

logger = logging.getLogger(__name__)

ARCHIVO = 'playdoit_cobertura.json'
DEPORTES = ('futbol', 'tenis', 'mlb', 'nba')


def _ahora() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')


def catalogo() -> Dict[str, Dict[str, int]]:
    """{deporte: {competición: nº de partidos}} tal y como lo publica Playdoit."""
    import cuotas_multi as cm
    out: Dict[str, Dict[str, int]] = {}
    for dep in DEPORTES:
        comp: Dict[str, int] = {}
        try:
            idx = cm._indice_pdt(dep)
        except Exception as e:
            logger.warning(f"[playdoit] {dep}: {type(e).__name__}: {e}")
            out[dep] = {}
            continue
        for v in idx.values():
            liga = (v.get('liga') or '?').strip()
            comp[liga] = comp.get(liga, 0) + 1
        out[dep] = dict(sorted(comp.items(), key=lambda kv: -kv[1]))
    return out


def ligas_descubiertas(cat: Dict[str, Dict[str, int]]) -> List[str]:
    """
    Ligas ACTIVAS del proyecto cuyos partidos de hoy no tienen precio en
    Playdoit. Se mide sobre los fixtures reales, no sobre nombres: comparar
    cadenas entre catálogos distintos da falsos positivos sin parar.
    """
    import cuotas_multi as cm
    import fixtures_espn
    import name_mapper
    from config import LEAGUES
    from league_engine import ClubEngine

    claves = [c for c, cfg in LEAGUES.items()
              if cfg.get('disponible') and c in fixtures_espn.ESPN_CODIGOS]
    try:
        fixtures = fixtures_espn.fixtures_multi(claves)
    except Exception as e:
        logger.warning(f"fixtures no disponibles: {e}")
        return []
    idx = cm._indice_pdt('futbol')
    fuera = []
    for clave in claves:
        fx = fixtures.get(clave) or []
        if not fx:
            continue
        try:
            eng = ClubEngine(clave)
            catalogo_eq = list(eng.stats.keys()) if getattr(eng, 'listo', False) else []
        except Exception:
            catalogo_eq = []
        con, total = 0, 0
        for f in fx:
            h = name_mapper.mapear(f['home'], catalogo_eq) if catalogo_eq else f['home']
            a = name_mapper.mapear(f['away'], catalogo_eq) if catalogo_eq else f['away']
            if not (h and a):
                continue
            total += 1
            if cm._buscar(idx, str(h), str(a), 'futbol'):
                con += 1
        if total and con == 0:
            fuera.append(f'{clave} ({total} partidos hoy, 0 con precio en Playdoit)')
    return fuera


def main() -> dict:
    previo = {}
    if os.path.exists(ARCHIVO):
        try:
            with open(ARCHIVO, encoding='utf-8') as f:
                previo = json.load(f)
        except Exception:
            previo = {}

    cat = catalogo()
    antes = {d: set((previo.get('catalogo') or {}).get(d, {}).keys()) for d in DEPORTES}
    altas = {d: sorted(set(cat[d]) - antes.get(d, set())) for d in DEPORTES}
    bajas = {d: sorted(antes.get(d, set()) - set(cat[d])) for d in DEPORTES}

    salida = {
        'generado': _ahora(),
        'catalogo': cat,
        'totales': {d: sum(cat[d].values()) for d in DEPORTES},
        'competiciones': {d: len(cat[d]) for d in DEPORTES},
        'altas': {d: v for d, v in altas.items() if v and previo},
        'bajas': {d: v for d, v in bajas.items() if v and previo},
        'ligas_sin_precio': ligas_descubiertas(cat),
        'nota': 'Playdoit es la casa del usuario: una liga sin precio aquí '
                'produce EV que no se puede cobrar. Las altas son candidatas '
                'a incorporar; las bajas explican por qué unos picks dejaron '
                'de tener precio tomable.',
    }
    with open(ARCHIVO, 'w', encoding='utf-8') as f:
        json.dump(salida, f, ensure_ascii=False, indent=1)
    return salida


def incidencias() -> List[str]:
    """Líneas para el registro de incidencias de la UI."""
    if not os.path.exists(ARCHIVO):
        return []
    try:
        with open(ARCHIVO, encoding='utf-8') as f:
            d = json.load(f)
    except Exception:
        return []
    # v91: con severidad. Que Playdoit no cotice una liga chica NO es un fallo
    # del sistema (Pinnacle/Bovada la cubren): es información, y así se marca.
    out = []
    for dep, v in (d.get('altas') or {}).items():
        if v:
            out.append(f'ℹ️ Playdoit ({dep}): {len(v)} competiciones nuevas — '
                       f'{", ".join(v[:5])}{"…" if len(v) > 5 else ""}')
    for dep, v in (d.get('bajas') or {}).items():
        if v:
            out.append(f'ℹ️ Playdoit ({dep}): {len(v)} competiciones ya no '
                       f'cotizan — {", ".join(v[:5])}{"…" if len(v) > 5 else ""}')
    sin = d.get('ligas_sin_precio') or []
    if sin:
        out.append(f'ℹ️ Playdoit no cotiza hoy {len(sin)} ligas activas '
                   f'({"; ".join(sin[:4])}{"…" if len(sin) > 4 else ""}); sus '
                   f'picks llevan precio de Pinnacle/Bovada — cubierto.')
    return out


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    s = main()
    print('Cobertura de Playdoit:')
    for d in DEPORTES:
        print(f"  {d:7s} {s['competiciones'][d]:4d} competiciones · "
              f"{s['totales'][d]:5d} partidos")
    if s['ligas_sin_precio']:
        print(f"\nLigas activas SIN precio en Playdoit ({len(s['ligas_sin_precio'])}):")
        for x in s['ligas_sin_precio']:
            print('   ·', x)
    for x in incidencias():
        print('\n>', x)
