#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v88 — El barrido de Apuestas del Día, después de los cuatro cambios.

Se comprueba de una vez:
  1. Ningún error 401 de The Odds API (el módulo ya no existe).
  2. Los picks de MLB son de la MLB de verdad, no de Taiwán ni de la LMB.
  3. Todo lo que sale empieza dentro de las próximas 24 horas.
  4. Y por eso casi todo lleva cuota real en vez de cuota justa.
"""
import io
import logging
import sys

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass


def main():
    import pandas as pd

    # se capturan los logs para buscar rastros de The Odds API
    buffer = io.StringIO()
    h = logging.StreamHandler(buffer)
    h.setLevel(logging.DEBUG)
    logging.getLogger().addHandler(h)
    logging.getLogger().setLevel(logging.INFO)

    import alpha_finder as af
    from engines.mlb_engine import es_partido_mlb

    print('=' * 78)
    print('v88 · BARRIDO DE APUESTAS DEL DÍA')
    print('=' * 78)
    print(f'  ventana configurada: {af.VENTANA_APUESTAS_H} h')

    r = af.apuestas_del_dia_universal()
    logs = buffer.getvalue()

    # ---- 1) The Odds API ---------------------------------------------------
    print('\n[1] rastro de The Odds API')
    rastros = [l for l in logs.splitlines()
               if 'the-odds-api' in l.lower() or 'The Odds API' in l
               or '401' in l]
    print(f'    líneas con 401 / the-odds-api: {len(rastros)}')
    for l in rastros[:5]:
        print(f'      {l[:110]}')
    import importlib.util
    print(f'    módulo odds_api presente: '
          f'{importlib.util.find_spec("odds_api") is not None}')

    # ---- 2) MLB ------------------------------------------------------------
    print('\n[2] picks de MLB')
    capa1 = r.get('capa1') or []
    mlb = [p for p in capa1 if p.get('deporte') == 'MLB']
    print(f'    capa1 total: {len(capa1)} · MLB: {len(mlb)}')
    malos = []
    for p in mlb:
        # 'Away @ Home'
        partes = str(p.get('partido', '')).split(' @ ')
        ok = len(partes) == 2 and es_partido_mlb(partes[1], partes[0])
        print(f'      {"OK " if ok else "MAL"} {p.get("partido")} | '
              f'{p.get("apuesta")} | cuota {p.get("cuota")}')
        if not ok:
            malos.append(p.get('partido'))
    # duplicados
    firmas = [p.get('partido') for p in mlb]
    dups = len(firmas) - len(set(firmas))
    print(f'    partidos MLB duplicados: {dups}')

    # ---- 3) ventana de 24 h ------------------------------------------------
    print('\n[3] ¿todo dentro de las próximas 24 h?')
    ahora = pd.Timestamp.utcnow().tz_localize(None)
    fuera = []
    for p in capa1:
        f = p.get('fecha')
        if not f:
            continue
        try:
            d = pd.Timestamp(f).normalize()
        except (ValueError, TypeError):
            continue
        dias = (d - ahora.normalize()).days
        if dias > 1:
            fuera.append((p.get('partido'), f, dias))
    print(f'    picks con fecha a más de 1 día vista: {len(fuera)}')
    for nombre, f, dd in fuera[:6]:
        print(f'      {nombre} ({f}, +{dd} días)')

    # ---- 4) cuotas ---------------------------------------------------------
    print('\n[4] ¿llevan cuota real?')
    con_cuota = sum(1 for p in capa1 if p.get('cuota'))
    print(f'    capa1 con cuota real: {con_cuota} de {len(capa1)}')
    c2 = r.get('capa2') or []
    print(f'    capa2 (sin cuota en vivo): {len(c2)}')
    pron = r.get('pronosticos') or []
    print(f'    pronosticos: {len(pron)}')

    print(f'\n    deportes cubiertos: {r.get("deportes_cubiertos")}')
    print('\n    incidencias de MLB:')
    for i in (r.get('incidencias') or []):
        if 'MLB' in i:
            print(f'      - {i[:160]}')

    # ---- veredicto ---------------------------------------------------------
    ok = (not rastros and not malos and dups == 0 and not fuera
          and con_cuota == len(capa1))
    print('\n' + '=' * 78)
    print(f'  sin rastro de The Odds API : {"SÍ" if not rastros else "NO"}')
    print(f'  MLB sólo con equipos MLB   : {"SÍ" if not malos else "NO " + str(malos)}')
    print(f'  sin duplicados             : {"SÍ" if dups == 0 else "NO"}')
    print(f'  todo dentro de 24 h        : {"SÍ" if not fuera else "NO"}')
    print(f'  toda la capa1 con cuota    : '
          f'{"SÍ" if con_cuota == len(capa1) else f"{con_cuota}/{len(capa1)}"}')
    print(f'\nVEREDICTO: {"TODO OK" if ok else "revisar"}')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
