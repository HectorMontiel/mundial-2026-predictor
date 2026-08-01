#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v88 — ¿Dónde se pierden los picks de MLB antes de llegar a Apuestas del Día?

Las incidencias que ve el usuario dicen:

    MLB · valor de mercado: 57 partidos comparados contra Pinnacle, 2 con
    precio descolgado por encima del 2%.
    MLB: 57 partidos con cuota, 16 evaluados por el modelo, 2 superaron los
    filtros.

O sea que `_picks_mlb` SÍ produce picks. Y el veto de `validacion_deportes`
exime explícitamente a los de `valor_vs_sharp` (`_exento` mira
`p['valor_mercado']`), así que tampoco debería ser eso.

Este script sigue la pista paso a paso en vez de suponer: qué devuelve
`_picks_mlb`, qué sobrevive al veto y qué acaba en la Capa 1 final.
"""
import sys

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass


def main():
    import alpha_finder as af

    print('=' * 78)
    print('v88 · RASTREO DE LOS PICKS DE MLB')
    print('=' * 78)

    # ---- 1) lo que produce _picks_mlb -------------------------------------
    print('\n[1] _picks_mlb() directo')
    r = af._picks_mlb()
    c1 = r.get('capa1') or []
    print(f'    capa1 devuelta: {len(c1)}')
    for p in c1:
        print(f'      · {p.get("partido")} | {p.get("apuesta")} | '
              f'prob {p.get("prob")} | cuota {p.get("cuota")} | '
              f'ev {p.get("ev")} | valor_mercado={p.get("valor_mercado")} | '
              f'deporte={p.get("deporte")}')
    for i in (r.get('incidencias') or []):
        print(f'    inc: {i[:120]}')

    # ---- 2) ¿los exime el veto por deporte? --------------------------------
    print('\n[2] veto de validacion_deportes')
    import validacion_deportes as vd
    print(f'    tiene_edge("MLB") = {vd.tiene_edge("MLB")}')
    print(f'    motivo            = {(vd.motivo("MLB") or "")[:110]}')
    for p in c1:
        exento = bool(p.get('valor_mercado'))
        sobrevive = exento or vd.tiene_edge(p.get('deporte'))
        print(f'      · {p.get("apuesta")}: exento={exento} '
              f'-> {"SOBREVIVE" if sobrevive else "SE CAE"}')

    # ---- 3) el barrido completo -------------------------------------------
    print('\n[3] barrido universal completo')
    u = af.apuestas_del_dia_universal()
    capa1 = u.get('capa1') or []
    print(f'    capa1 total: {len(capa1)}')
    por_dep = {}
    for p in capa1:
        por_dep[p.get('deporte')] = por_dep.get(p.get('deporte'), 0) + 1
    print(f'    por deporte: {por_dep}')
    mlb = [p for p in capa1 if p.get('deporte') == 'MLB']
    print(f'    MLB en capa1: {len(mlb)}')
    for p in mlb:
        print(f'      · {p.get("partido")} | {p.get("apuesta")} | '
              f'cuota {p.get("cuota")}')

    # ¿y en candidatos?
    cand = u.get('candidatos') or []
    mlb_c = [p for p in cand if p.get('deporte') == 'MLB']
    print(f'    MLB en candidatos: {len(mlb_c)}')
    for p in mlb_c[:5]:
        print(f'      · {p.get("apuesta")} | sin_edge={p.get("sin_edge_deporte")} '
              f'| valor_mercado={p.get("valor_mercado")}')

    # ¿en la selección del día / máxima confianza?
    for clave in ('seleccion_dia', 'capa1_prob', 'pronosticos', 'capa2'):
        v = u.get(clave) or []
        n = sum(1 for p in v if p.get('deporte') == 'MLB')
        print(f'    MLB en {clave}: {n} de {len(v)}')

    print(f'\n    deportes_cubiertos: {u.get("deportes_cubiertos")}')
    print('\n    incidencias con MLB:')
    for i in (u.get('incidencias') or []):
        if 'MLB' in i or 'Mexicana' in i:
            print(f'      - {i[:150]}')


if __name__ == '__main__':
    main()
