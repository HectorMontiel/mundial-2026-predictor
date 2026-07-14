#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Sondeo v21: qué permite realmente el plan Free de API-Football.

Consume ~6 requests (una sola vez: todo queda cacheado). Determina:
temporadas accesibles, cuotas, alineaciones, lesiones y H2H.
"""

import json
import logging

import api_football_manager as afm

logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')


def resumen(nombre, data, muestra=1):
    if data is None:
        print(f"\n== {nombre}: SIN RESPUESTA (sin clave/crédito/red)")
        return None
    err = data.get('errors')
    n = data.get('results', 0)
    print(f"\n== {nombre}: results={n} errors={err if err else 'ninguno'}")
    resp = data.get('response') or []
    for item in (resp[:muestra] if isinstance(resp, list) else [resp]):
        print(json.dumps(item, ensure_ascii=True)[:600])
    return resp


print(afm.resumen_estado())

# 0. Estado de la cuenta (no consume cuota)
resumen('status', afm.api_call('status', prioridad=1))

# 1. Champions 2023 (histórico permitido en plan Free: 2021-2023)
r23 = resumen('fixtures CL season=2023', afm.api_call(
    'fixtures', {'league': 2, 'season': 2023}, prioridad=1, ttl=None), muestra=0)
if r23:
    print(f"   partidos: {len(r23)} · ejemplo: "
          f"{r23[0]['teams']['home']['name']} vs {r23[0]['teams']['away']['name']} "
          f"({r23[0]['fixture']['date'][:10]}) id={r23[0]['fixture']['id']}")

# 2. Temporada actual (¿bloqueada en plan Free?)
resumen('fixtures CL season=2025', afm.api_call(
    'fixtures', {'league': 2, 'season': 2025}, prioridad=1, ttl=None), muestra=0)

# 3. Mundial 2026 (league=1): ¿accesible?
resumen('fixtures WC season=2026', afm.api_call(
    'fixtures', {'league': 1, 'season': 2026}, prioridad=1, ttl=None), muestra=0)

if r23:
    fid = r23[-1]['fixture']['id']   # la final de 2023-24
    # 4. Alineaciones de un partido histórico
    resumen(f'lineups fixture={fid}', afm.api_call(
        'fixtures/lineups', {'fixture': fid}, prioridad=1, ttl=None))
    # 5. Estadísticas de ese partido (xG/posesión)
    resumen(f'statistics fixture={fid}', afm.api_call(
        'fixtures/statistics', {'fixture': fid}, prioridad=1))
    # 6. Cuotas (históricas suelen estar fuera del Free; probamos)
    r_odds = resumen(f'odds fixture={fid}', afm.api_call(
        'odds', {'fixture': fid, 'bookmaker': 8}, prioridad=1), muestra=0)
    if r_odds:
        mercados = [b['name'] for b in r_odds[0]['bookmakers'][0]['bets']]
        print('   mercados:', mercados[:12])

# 7. Lesiones/sanciones actuales de un equipo (Real Madrid id=541)
resumen('sidelined team=541', afm.api_call(
    'sidelined', {'team': 541}, prioridad=1), muestra=2)

# 8. H2H bajo demanda (Man United 33 vs Liverpool 40)
rh = resumen('headtohead 33-40 last=5', afm.api_call(
    'fixtures/headtohead', {'h2h': '33-40', 'last': 5}, prioridad=1), muestra=0)
if rh:
    for p in rh:
        print(f"   {p['fixture']['date'][:10]} {p['teams']['home']['name']} "
              f"{p['goals']['home']}-{p['goals']['away']} {p['teams']['away']['name']}")

# 9. Liga MX 2024: ¿cuántos partidos y trae estadísticas por fixture?
rmx = resumen('fixtures Liga MX season=2024', afm.api_call(
    'fixtures', {'league': 262, 'season': 2024}, prioridad=1, ttl=None), muestra=0)
if rmx:
    print(f"   partidos Liga MX 2024: {len(rmx)}")

print('\n', afm.resumen_estado())
