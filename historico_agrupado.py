#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v184 — el histórico de una COPA, con los partidos de liga de sus participantes.

DE DÓNDE SALE LA IDEA: DE ESTE MISMO PROYECTO
---------------------------------------------
`leagues_cup.historico(con_ligas=True)` ya lo hace, y por un motivo que está
escrito allí: «la competición sola son 230 partidos entre 47 equipos: ~5 por
equipo. Lo que hace predecible un México-Seattle no es la historia de la Leagues
Cup, es la de la MLS y la Liga MX». Su histórico agrupado tiene 6.759 filas y su
motor conoce a todos sus equipos.

QUÉ RESUELVE QUE EL RESPALDO DE LA v182 NO
------------------------------------------
Son dos cosas distintas y conviene no confundirlas:

  · `perfil_liga_local` arregla las ESTADÍSTICAS de un equipo con poca muestra
    —córners, tarjetas, remates— y lo hace de forma quirúrgica, sólo donde
    falta.
  · Esto arregla el **1X2**: un equipo que no está en el histórico de la
    competición no está en el catálogo del modelo, así que el motor no lo
    predice y el partido sale con `prob: None`. Medido en la Champions del día:
    Stuttgart-Viking, Fenerbahce-Roma y Como-Leipzig, tres de doce.

CÓMO SE ELIGEN LAS LIGAS QUE ENTRAN
-----------------------------------
Con `catalogo_equipos`: las ligas de los equipos que han jugado la copa, y sólo
ésas. No se mete el catálogo entero — un partido de Champions no se explica
mejor por la segunda de Bolivia.

LO QUE HAY QUE MEDIR ANTES DE ENCENDERLO, Y POR QUÉ NO ES OBVIO
---------------------------------------------------------------
La Leagues Cup agrupa DOS ligas de nivel parecido. La Champions agruparía
dieciocho, de la Premier a la liga noruega, y el modelo tendría que separar el
nivel por su cuenta. El proyecto tiene con qué —el ELO por liga y el término de
nivel de competición de la λ— pero eso es una hipótesis hasta que se mida.

Por eso este módulo **construye el histórico y no lo enciende**: quien decide es
`_v184_mide_agrupado.py`, comparando la precisión del modelo contra su línea
base ELO con y sin agrupar.
"""
import logging
import os
from typing import List, Optional

logger = logging.getLogger('historico_agrupado')

# Cuántas ligas distintas se admiten como mucho. Con más, lo que se entrena ya
# no es «esta copa y las ligas de sus equipos» sino medio catálogo.
MAX_LIGAS = 24
# Una liga con menos partidos del equipo que la copa no aporta contexto.
MIN_PARTIDOS_LIGA = 200


def ligas_de_la_copa(clave: str, minimo_equipos: int = 2) -> List[str]:
    """
    Las ligas locales de los equipos que han jugado esta copa.

    `minimo_equipos` evita arrastrar una liga entera por un solo club que pasó
    una eliminatoria hace tres años.
    """
    import collections
    import pandas as pd
    import catalogo_equipos as ce

    ruta = 'historico_%s.csv' % clave
    if not os.path.exists(ruta):
        return []
    try:
        df = pd.read_csv(ruta, usecols=['home_team', 'away_team'])
    except Exception as e:
        logger.warning('[agrupado] no se pudo leer %s: %s', ruta, e)
        return []
    equipos = set(pd.concat([df['home_team'], df['away_team']]).dropna())
    cuenta = collections.Counter()
    for e in equipos:
        liga = ce.liga_de(e)
        if liga and liga != clave:
            cuenta[liga] += 1
    salida = [liga for liga, n in cuenta.most_common()
              if n >= minimo_equipos]
    return salida[:MAX_LIGAS]


def construir(clave: str, ligas: Optional[List[str]] = None):
    """
    `DataFrame` con la copa y los partidos de liga de sus participantes.

    La copa manda en los duplicados: si un partido aparece en las dos fuentes,
    se queda el de la copa, que es el que trae su contexto.
    """
    import pandas as pd

    ruta = 'historico_%s.csv' % clave
    if not os.path.exists(ruta):
        raise RuntimeError('%s: no hay histórico de la copa' % clave)
    copa = pd.read_csv(ruta)
    copa['date'] = pd.to_datetime(copa['date'], errors='coerce')
    copa['competicion'] = clave

    ligas = ligas_de_la_copa(clave) if ligas is None else list(ligas)
    marcos = [copa]
    usadas = []
    for liga in ligas:
        r = 'historico_%s.csv' % liga
        if not os.path.exists(r):
            continue
        try:
            d = pd.read_csv(r)
        except Exception:
            continue
        if len(d) < MIN_PARTIDOS_LIGA:
            continue
        d['date'] = pd.to_datetime(d['date'], errors='coerce')
        d['competicion'] = liga
        marcos.append(d)
        usadas.append(liga)

    junto = pd.concat(marcos, ignore_index=True, sort=False)
    junto = junto.dropna(subset=['date', 'home_goals', 'away_goals'])
    junto = (junto.sort_values('date')
                  .drop_duplicates(subset=['date', 'home_team', 'away_team'],
                                   keep='first')
                  .reset_index(drop=True))
    logger.info('[agrupado] %s: %d partidos (%d de la copa + %d ligas: %s)',
                clave, len(junto), len(copa), len(usadas), usadas)
    return junto


def cobertura(clave: str) -> dict:
    """Cuántos equipos de la copa quedan dentro del histórico agrupado."""
    import pandas as pd
    ruta = 'historico_%s.csv' % clave
    copa = pd.read_csv(ruta, usecols=['home_team', 'away_team'])
    de_copa = set(pd.concat([copa['home_team'], copa['away_team']]).dropna())
    junto = construir(clave)
    dentro = set(pd.concat([junto['home_team'], junto['away_team']]).dropna())
    faltan = sorted(de_copa - dentro)
    return {'equipos_copa': len(de_copa), 'partidos_copa': len(copa),
            'partidos_agrupado': len(junto),
            'equipos_cubiertos': len(de_copa) - len(faltan),
            'faltan': faltan}
