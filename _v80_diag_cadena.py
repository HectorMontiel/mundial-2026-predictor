#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v80 — ¿Dónde se rompe la cadena que deja al fútbol de julio sin calibrar?

La v79 midió el síntoma: 0 de 41 picks de fútbol encogidos, cobertura real
30,6 %. Se atribuyó a «falta histórico de cuotas sudamericano». Antes de
ingerir nada hay que comprobar si esa es de verdad la causa, porque el almacén
dice otra cosa: `liga_mx` tiene 5.086 cuotas de cierre, MÁS que ninguna otra
liga, y aun así `peso_modelo('liga_mx')` devuelve 1,00.

La cadena tiene cuatro eslabones y el fallo puede estar en cualquiera:

    1. ¿hay cuotas de cierre en odds_historico.db?
    2. ¿hay filas de esa liga en pick_ledger.csv (el walk-forward)?
    3. ¿esas filas llevan cuota?
    4. ¿la liga supera la regla de adopción de recalibrate_from_history?

Se mira eslabón por eslabón para las ligas que REALMENTE juegan hoy.
"""
import json
import logging
import os

import pandas as pd

logging.basicConfig(level=logging.WARNING)


def main():
    import calibracion_mercado as cal
    import config
    import fixtures_espn
    import odds_store

    # --- ligas que juegan ---
    activas = [c for c in config.LEAGUES if c in fixtures_espn.ESPN_CODIGOS]
    fx = fixtures_espn.fixtures_multi(activas, dias=3)
    juegan = {c: len(v) for c, v in fx.items() if v}

    # --- eslabón 1: almacén de cuotas ---
    con = odds_store.conectar()
    cur = con.execute("SELECT league_key, COUNT(*) FROM historical_odds "
                      "WHERE fase='cierre' GROUP BY league_key")
    almacen = dict(cur.fetchall())
    con.close()

    # --- eslabones 2 y 3: ledger de fútbol ---
    led = pd.read_csv('pick_ledger.csv', low_memory=False) \
        if os.path.exists('pick_ledger.csv') else pd.DataFrame()
    if not led.empty:
        filas = led['liga'].value_counts().to_dict()
        con_cuota = (led[led['cuota_home'].notna()]['liga']
                     .value_counts().to_dict())
    else:
        filas, con_cuota = {}, {}

    # --- eslabón 4: peso adoptado ---
    print(f"{'liga':24s} {'hoy':>5} {'almacen':>8} {'ledger':>7} "
          f"{'c/cuota':>8} {'w':>6}   diagnostico")
    print('-' * 92)
    resumen = {'sin_almacen': [], 'sin_ledger': [], 'sin_cuota_ledger': [],
               'medida_no_adoptada': [], 'ok': []}
    for c, n in sorted(juegan.items(), key=lambda kv: -kv[1]):
        alm = almacen.get(c, 0)
        fl = filas.get(c, 0)
        cq = con_cuota.get(c, 0)
        w = cal.peso_modelo(c)
        if w < 1.0:
            diag = 'OK — se encoge'
            resumen['ok'].append(c)
        elif cq >= 200:
            diag = 'medida pero NO adoptada (no mejoraba)'
            resumen['medida_no_adoptada'].append(c)
        elif fl == 0:
            diag = ('SIN FILAS en el ledger'
                    + (f' (pero {alm} cuotas en el almacen)' if alm else
                       ' y SIN cuotas'))
            (resumen['sin_ledger'] if alm else
             resumen['sin_almacen']).append(c)
        else:
            diag = f'ledger sin cuota suficiente ({cq})'
            resumen['sin_cuota_ledger'].append(c)
        print(f'{c:24s} {n:5d} {alm:8d} {fl:7d} {cq:8d} {w:6.2f}   {diag}')

    print('\n' + '=' * 60)
    tot = sum(juegan.values())
    cubiertos = sum(n for c, n in juegan.items() if cal.peso_modelo(c) < 1.0)
    print(f'partidos hoy: {tot} · con peso: {cubiertos} '
          f'({cubiertos/max(tot,1):.1%})')
    for k, v in resumen.items():
        if v:
            print(f'\n{k} ({len(v)}):\n   {sorted(v)}')
    json.dump(resumen, open('_v80_diag_cadena.json', 'w', encoding='utf-8'),
              indent=1, ensure_ascii=False)


if __name__ == '__main__':
    main()
