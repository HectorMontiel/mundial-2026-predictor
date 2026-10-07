# -*- coding: utf-8 -*-
"""
v331 — LAS «METER» REALES DE LA APP, YA LIQUIDADAS, DÍA POR DÍA.

Junta la última foto de `jugados_dia.json` de cada día que hay en git y pasa
cada partido por `pronosticos_guardados.validar` —lo mismo que la pestaña de
finalizados y que «Así le fue a la app»—. Se queda con lo que la app dijo
«meter» y salió verde o rojo, con todo lo necesario para buscar patrones.

Salida: _v331_meter_app.csv

LO QUE SE MIDIÓ CON ESTO (2026-10-06) — NADA SE ACTIVA EN LA APP
------------------------------------------------------------------
El usuario: «quiero que veas qué patrones hay en las apuestas rojas para que
en los siguientes partidos de esos equipos no nos vuelva a pasar».

  · 867 «meter» reales liquidadas (26-sep a 6-oct): 74,3 % verdes. Con la
    regla de hoy (70-80 %, cuota < 1,35, sin doble y goles ni remates): 605,
    prometían 75,1 % y acertaron 75,2 %. Los rojos que quedan son los que el
    propio porcentaje anuncia: una apuesta al 75 % sale roja 1 de cada 4.

  · LA MEMORIA DEL EQUIPO NO AVISA (`_v331_memoria_equipos.py`). En los
    históricos fuera de muestra, con la «meter» simulada en la franja 70-80 %:
        goles      tras rojo 73,7 % (27.731) · tras verde 74,0 % (34.194)
        resultado  tras rojo 74,3 % (29.613) · tras verde 74,6 % (37.310)
    En las reales, al revés: tras rojo 76,0 % (204), tras verde 70,9 % (134).
    De cinco reglas «saltar al equipo que…», sólo R4 (≥ 2 rojos en sus 4
    últimas) pasa el p5 en goles: +0,1 pts al mirar, +0,8 al juzgar, peor en
    3 de 9 temporadas y a cambio de quitar el 45 % de las apuestas. Con diez
    pruebas, una así se espera por azar. No se adopta.

  · EL MODELO POR ENCIMA DE LA CASA (`_v331_desacuerdo_casa.py`): sin la
    regla de hoy, en resultado, falla mucho más (modelo 6+ pts por encima:
    65,9 %; casa 5+ pts por encima: 83,8 %). Pero ENCIMA de la regla de hoy
    (`_v331_encima_regla.py`) ya no aporta: +0,2 pts en el histórico, +0,2 en
    las reales, −0,1 en la simulación. El tope de cuota 1,35 ya lo recoge.

  · EXIGIR LA CASA 5 PTS MÁS SEGURA QUE EL MODELO, sólo en resultado: el
    histórico pasa (77,1 → 78,8 %, p5 +1,23) y las reales también (74,8 →
    78,2 %, p5 +1,55), pero la simulación de la tarjeta EMPEORA al juzgar
    (72,5 → 69,8 %) y las reales al mirar quedan igual (75,4 → 75,3). No
    cumple «la simulación igual o mejor». No se adopta.
"""
from __future__ import annotations

import io
import json
import subprocess
import sys

import pandas as pd

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8',
                              errors='replace')


def fotos_por_dia():
    hashes = subprocess.run(
        ['git', 'log', '--format=%H', '--', 'jugados_dia.json'],
        capture_output=True, check=True).stdout.decode().split()
    por_dia = {}
    for h in hashes:                      # del más nuevo al más viejo
        try:
            raw = subprocess.run(['git', 'show', '%s:jugados_dia.json' % h],
                                 capture_output=True, check=True).stdout
            d = json.loads(raw.decode('utf-8'))
        except Exception:
            continue
        dia = d.get('dia')
        if dia and dia not in por_dia:
            por_dia[dia] = d
    return por_dia


def main():
    import formato_ia as fi
    import partidos_jugados as pj
    import pronosticos_guardados as pg
    filas = []
    por_dia = fotos_por_dia()
    for dia in sorted(por_dia):
        partidos = pj._para_la_vista(por_dia[dia].get('partidos') or [])
        n0 = len(filas)
        for p in partidos:
            if p.get('solo_mercado') or p.get('sin_modelo') or p.get('aplazado'):
                continue
            dep = str(p.get('deporte') or 'Fútbol')
            try:
                vs = pg.validar(p)
            except Exception:
                continue
            for fl in vs:
                if fl.get('veredicto') != 'meter' or fl.get('estado') not in (
                        pg.CUMPLIDO, pg.FALLADO):
                    continue
                filas.append({
                    'dia': dia, 'deporte': dep,
                    'clave_liga': p.get('clave_liga'), 'liga': p.get('liga'),
                    'partido': p.get('partido'),
                    'home': p.get('home') or (str(p.get('partido')).split(' vs ')[0]),
                    'away': p.get('away') or (str(p.get('partido')).split(' vs ')[-1]),
                    'goles_home': p.get('goles_home'),
                    'goles_away': p.get('goles_away'),
                    'categoria': fi.categoria(fl, dep),
                    'mercado': fl.get('mercado'), 'apuesta': fl.get('apuesta'),
                    'prob': fl.get('prob_meter', fl.get('prob')),
                    'prob_modelo': fl.get('prob'),
                    'cuota': fl.get('cuota'), 'casa': fl.get('casa'),
                    'verde': int(fl['estado'] == pg.CUMPLIDO),
                })
        print(dia, 'partidos', len(partidos), 'meter liquidadas', len(filas) - n0)
    df = pd.DataFrame(filas)
    df.to_csv('_v331_meter_app.csv', index=False)
    print('TOTAL', len(df), 'verdes', int(df.verde.sum()) if len(df) else 0)


if __name__ == '__main__':
    main()
