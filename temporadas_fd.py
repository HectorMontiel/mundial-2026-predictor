#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v148 — La temporada vigente de football-data, derivada de la fecha.

POR QUÉ EXISTE ESTE MÓDULO
--------------------------
El 2026-08-21 la aplicación enseñaba «sin pronóstico del modelo» en Premier,
LaLiga, Ligue 1, Ligue 2 y Primeira. No fallaba el modelo: las listas de
temporadas de las veinte ligas de football-data eran tuplas literales que
terminaban en '2526'. La temporada 2026-27 llevaba una semana jugándose y no
estaba en la configuración, así que el curso en marcha nunca se descargaba y
los ascendidos —Coventry y Hull en la Premier, Málaga, Deportivo y Racing
Santander en LaLiga, Le Mans en la Ligue 1, Nantes en la Ligue 2, Académico de
Viseu en la Primeira— no existían en el catálogo del modelo. `name_mapper` no
podía casarlos contra nada y el partido salía sin pronóstico.

Medido antes del arreglo: **35 de 326 fixtures (10,7 %) sin pronóstico**.

El arreglo no es añadir '2627' a nueve tuplas —eso se vuelve a romper en julio
de 2027—, es DERIVAR la lista de la fecha. Una temporada de football-data se
nombra 'AABB' (2627 = 2026-27) y arranca en julio.

Vive en un módulo propio, y no dentro de `config`, porque lo necesitan los dos
lados del catálogo: `config.py` y `config_ligas_espn.py`, que `config` importa.
Ponerlo en `config` habría creado un ciclo.

TOLERANCIA, NO OPTIMISMO
------------------------
Sondeo del 2026-08-21 sobre los veinte códigos: catorce ficheros de 2627 ya
estaban publicados (SP1, F2, P1, N1, T1, SP2, D2, B1, E1, E2, E3, EC, SC0,
SC1) y seis todavía no (E0, I1, I2, D1, F1, G1) porque su liga arrancaba días
después. Un fichero que aún no existe devuelve **300 Multiple Choices con una
página HTML**, no un 404: `raise_for_status()` no levanta nada y `read_csv` se
traga el HTML. Quien valida eso es `league_engine.descargar_liga`; aquí sólo
se genera la lista.
"""

import datetime as _dt


def temporada_fd_vigente(hoy=None) -> str:
    """Código football-data ('2627') de la temporada en curso."""
    d = hoy or _dt.date.today()
    anio = d.year if d.month >= 7 else d.year - 1
    return f'{anio % 100:02d}{(anio + 1) % 100:02d}'


def temporadas_fd(desde: str, hasta: str = None) -> tuple:
    """
    Temporadas desde `desde` (código, '1011') hasta la vigente, inclusive.

    `hasta` sólo se pasa desde las pruebas, para poder fijar el presente.
    """
    hasta = hasta or temporada_fd_vigente()
    a0, a1 = int(desde[:2]), int(hasta[:2])
    # El siglo se resuelve solo mientras no haya temporadas anteriores a 2000
    # en el proyecto: la más antigua es 2010-11.
    if a1 < a0:
        a1 += 100
    return tuple(f'{a % 100:02d}{(a + 1) % 100:02d}' for a in range(a0, a1 + 1))
