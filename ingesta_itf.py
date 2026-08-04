#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v96 — El circuito ITF entra al modelo: 345.070 partidos y 18.392 jugadores.

Por qué faltaba, y por qué ahora sí
-----------------------------------
La v95 excluyó el ITF del barrido con un motivo medido: **no había fuente de
resultados**. El scoreboard de ESPN, que alimenta el resto del tenis, devuelve
0 partidos de ITF; la web oficial de la ITF responde con una página anti-bot
de 848 bytes; y la v67 ya había concluido que los repositorios de Jeff Sackmann
—donde vivían esos datos— habían desaparecido de GitHub.

Reverificado en la v96, y las dos mitades resultaron ciertas y una tercera no:

  · Los repos `JeffSackmann/tennis_atp` y `tennis_wta` están **borrados de
    verdad** (404 de la API de GitHub, no es un cambio de rama). De todo su
    perfil sólo sobrevive `tennis_MatchChartingProject`.
  · La web de la ITF sigue bloqueada.
  · **PERO existe un espejo de archivo** que sí conserva los ficheros:
    `Aneeshers/tennis-sackmann-archive`, con 473 ficheros, entre ellos 36 de
    ATP Futures (1991-2026), 59 de WTA ITF (1968-2026) y 49 de qualy y
    challenger (1978-2026).

Volumen medido sobre 2018-2026: **345.070 partidos y 18.392 jugadores
distintos**, frente a los 2.138 que tenía el catálogo del modelo.

La limitación, dicha claramente
-------------------------------
El espejo es un ARCHIVO, no un servicio en vivo: su última actualización llegó
hasta el **2026-06-01**, unos dos meses de retraso. Eso condiciona qué se puede
esperar:

  · Para ENTRENAR es perfectamente válido: treinta y cinco años de partidos no
    cambian porque hoy sea agosto.
  · Para el ESTADO del jugador (forma reciente, ELO) el retraso sí importa, y
    por eso el histórico ingerido se marca con su fecha de corte y la interfaz
    lo dice, en vez de fingir que el dato es de hoy.

Y una precaución que este caso enseña por sí solo: **los ficheros se guardan en
el repositorio del proyecto**. El original desapareció una vez; el espejo es
una copia personal que puede desaparecer igual. Una vez ingerido, el dato ya no
depende de que nadie lo mantenga.

Uso:
    python ingesta_itf.py                 # 2015 en adelante (por defecto)
    python ingesta_itf.py --desde 2010
"""
import argparse
import io
import logging
import os
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

BASE = ('https://raw.githubusercontent.com/Aneeshers/'
        'tennis-sackmann-archive/main')
SALIDA = 'historico_itf.csv.gz'
DESDE_POR_DEFECTO = 2015

# fichero del archivo -> (circuito del proyecto, categoría)
FUENTES = {
    'atp': [('atp/atp_matches_futures_{a}.csv', 'itf_atp'),
            ('atp/atp_matches_qual_chall_{a}.csv', 'challenger_atp')],
    'wta': [('wta/wta_matches_qual_itf_{a}.csv', 'itf_wta')],
}

# esquema canónico del proyecto (`tenis_fuentes.COLUMNAS`)
COLUMNAS = ['Tournament', 'Date', 'Series', 'Court', 'Surface', 'Round',
            'Best of', 'Player_1', 'Player_2', 'Winner', 'Rank_1', 'Rank_2',
            'Pts_1', 'Pts_2', 'Odd_1', 'Odd_2', 'Score', 'Comment',
            'Categoria', 'Fuente']

# rondas de Sackmann -> las del proyecto
RONDAS = {'F': 'The Final', 'SF': 'Semifinals', 'QF': 'Quarterfinals',
          'R16': '4th Round', 'R32': '3rd Round', 'R64': '2nd Round',
          'R128': '1st Round', 'RR': 'Round Robin', 'Q1': 'Qualifying',
          'Q2': 'Qualifying', 'Q3': 'Qualifying', 'BR': 'Bronze'}


def _descargar(ruta: str, reintentos: int = 2):
    """Baja un CSV del archivo. Devuelve None si no existe (año sin fichero)."""
    import pandas as pd
    import requests
    url = f'{BASE}/{ruta}'
    for intento in range(reintentos + 1):
        try:
            r = requests.get(url, timeout=90)
            if r.status_code == 404:
                return None                    # ese año no está: es normal
            r.raise_for_status()
            return pd.read_csv(io.StringIO(r.text), low_memory=False)
        except Exception as e:
            if intento == reintentos:
                logger.warning(f'[itf] {ruta}: {type(e).__name__}: {e}')
                return None
    return None


def _a_esquema(df, categoria: str, semilla: int = 96):
    """
    Traduce el esquema de Sackmann (ganador/perdedor) al del proyecto
    (jugador_1/jugador_2 + ganador).

    EL ORDEN SE ALTERNA, y no es un detalle
    ---------------------------------------
    Sackmann publica `winner_name` / `loser_name`, así que la traducción
    ingenua —ganador siempre a `Player_1`— mete al modelo la respuesta en la
    propia posición de la columna. Se probó y el resultado lo delató al
    instante: el ATP pasó de **62,77 % a 93,54 % de precisión de validación**,
    que es imposible en tenis. Comprobado en el acto:

        Kaggle (el resto del histórico)  ganador == Player_1 en el  50,0 %
        ingesta ITF, versión ingenua     ganador == Player_1 en el 100,0 %

    El modelo no había aprendido a predecir: había aprendido «gana el
    primero». Con el 78 % del histórico viniendo ya de aquí, esa fuga habría
    contaminado también las predicciones del circuito principal.

    Se asigna el ganador a `Player_1` o a `Player_2` de forma pseudoaleatoria
    pero DETERMINISTA (semilla fija), para que dos ingestas del mismo fichero
    den exactamente el mismo resultado y el histórico sea reproducible.
    """
    import numpy as np
    import pandas as pd

    rng = np.random.default_rng(semilla + len(df))
    primero_gana = rng.random(len(df)) < 0.5      # ~50 %, como en Kaggle

    gan = df.get('winner_name').to_numpy()
    per = df.get('loser_name').to_numpy()
    r_gan = pd.to_numeric(df.get('winner_rank'), errors='coerce').to_numpy()
    r_per = pd.to_numeric(df.get('loser_rank'), errors='coerce').to_numpy()
    p_gan = pd.to_numeric(df.get('winner_rank_points'), errors='coerce').to_numpy()
    p_per = pd.to_numeric(df.get('loser_rank_points'), errors='coerce').to_numpy()

    out = pd.DataFrame(index=df.index)
    out['Tournament'] = df.get('tourney_name')
    out['Date'] = pd.to_datetime(df.get('tourney_date').astype('Int64')
                                 .astype(str), format='%Y%m%d', errors='coerce')
    out['Series'] = df.get('tourney_level')
    out['Court'] = 'Outdoor'          # el archivo no lo publica; el valor
                                      # mayoritario en ITF es al aire libre
    out['Surface'] = df.get('surface')
    out['Round'] = df.get('round').map(RONDAS).fillna(df.get('round'))
    out['Best of'] = pd.to_numeric(df.get('best_of'), errors='coerce').fillna(3)
    out['Player_1'] = np.where(primero_gana, gan, per)
    out['Player_2'] = np.where(primero_gana, per, gan)
    out['Winner'] = gan               # el ganador, esté en la posición que esté
    out['Rank_1'] = np.where(primero_gana, r_gan, r_per)
    out['Rank_2'] = np.where(primero_gana, r_per, r_gan)
    out['Pts_1'] = np.where(primero_gana, p_gan, p_per)
    out['Pts_2'] = np.where(primero_gana, p_per, p_gan)
    out['Odd_1'] = np.nan             # el ITF no tiene cuotas históricas
    out['Odd_2'] = np.nan
    out['Score'] = df.get('score')
    # retiradas y walkovers vienen dentro del marcador
    sc = df.get('score').astype(str).str.upper()
    out['Comment'] = np.where(sc.str.contains('RET', na=False), 'Retired',
                              np.where(sc.str.contains('W/O|DEF', na=False),
                                       'Walkover', 'Completed'))
    out['Categoria'] = categoria
    out['Fuente'] = 'archivo_itf'
    return out.dropna(subset=['Date', 'Player_1', 'Player_2'])


def ingerir(desde: int = DESDE_POR_DEFECTO, hasta: Optional[int] = None,
            salida: str = SALIDA) -> Dict:
    """Descarga, normaliza y guarda el histórico de ITF y challenger."""
    import pandas as pd

    hasta = hasta or pd.Timestamp.utcnow().year
    marcos: List = []
    detalle: Dict[str, int] = {}
    for circuito, fuentes in FUENTES.items():
        for plantilla, categoria in fuentes:
            n_cat = 0
            for anio in range(desde, hasta + 1):
                d = _descargar(plantilla.format(a=anio))
                if d is None or d.empty:
                    continue
                m = _a_esquema(d, categoria)
                m['Circuito'] = circuito
                marcos.append(m)
                n_cat += len(m)
            detalle[categoria] = n_cat
            logger.info(f'[itf] {categoria}: {n_cat} partidos')

    if not marcos:
        return {'partidos': 0, 'aviso': 'El archivo no devolvió ningún fichero.'}

    df = pd.concat(marcos, ignore_index=True).sort_values('Date')
    # un mismo partido no puede estar dos veces (los ficheros no se solapan,
    # pero el archivo puede reeditarse y esto lo hace idempotente)
    df = df.drop_duplicates(subset=['Date', 'Player_1', 'Player_2', 'Tournament'])

    # GUARDIA CONTRA LA FUGA DE POSICIÓN.
    #
    # Si el ganador acabara sistemáticamente en la misma columna, el modelo
    # aprendería «gana el primero» en vez de a predecir — y el síntoma es un
    # salto de precisión que parece un triunfo (62,77 % → 93,54 % en la
    # primera versión de este módulo). Aquí se comprueba antes de escribir:
    # con ~50 % esperado, salirse de [45 %, 55 %] con esta muestra es
    # imposible por azar.
    equilibrio = float((df['Winner'] == df['Player_1']).mean())
    if not (0.45 <= equilibrio <= 0.55):
        raise ValueError(
            f'El ganador aparece como Player_1 en el {equilibrio:.1%} de los '
            f'partidos (se espera ~50 %). Eso es fuga de posición: el modelo '
            f'aprendería a leer la columna en vez de a predecir. No se escribe '
            f'el fichero.')
    logger.info(f'[itf] equilibrio de posición del ganador: {equilibrio:.1%} '
                f'(sano)')
    df.to_csv(salida, index=False, compression='gzip')

    jug = set(df['Player_1'].dropna()) | set(df['Player_2'].dropna())
    r = {'partidos': int(len(df)), 'jugadores': len(jug),
         'por_categoria': detalle,
         'desde': str(df['Date'].min().date()),
         'hasta': str(df['Date'].max().date()),
         'dias_de_retraso': int((pd.Timestamp.utcnow().tz_localize(None)
                                 - df['Date'].max()).days),
         'archivo': salida}
    logger.info(f"[itf] {r['partidos']} partidos · {r['jugadores']} jugadores · "
                f"{r['desde']}..{r['hasta']} ({r['dias_de_retraso']} días de "
                f"retraso) → {salida}")
    return r


def cargar(circuito: str, salida: str = SALIDA):
    """
    Histórico de ITF/challenger del circuito, en el esquema del proyecto.

    Devuelve un DataFrame vacío si aún no se ha ingerido, para que
    `tenis_fuentes` pueda llamarlo sin condicionales.
    """
    import pandas as pd
    if not os.path.exists(salida):
        return pd.DataFrame(columns=COLUMNAS)
    try:
        df = pd.read_csv(salida, compression='gzip', low_memory=False)
    except Exception as e:
        logger.warning(f'[itf] {salida} ilegible: {e}')
        return pd.DataFrame(columns=COLUMNAS)
    df['Date'] = pd.to_datetime(df['Date'], errors='coerce')
    if 'Circuito' in df.columns:
        df = df[df['Circuito'].astype(str).str.lower() == circuito.lower()]
    return df[[c for c in COLUMNAS if c in df.columns]].dropna(subset=['Date'])


if __name__ == '__main__':
    import json
    import sys
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    sys.stdout.reconfigure(encoding='utf-8')
    ap = argparse.ArgumentParser()
    ap.add_argument('--desde', type=int, default=DESDE_POR_DEFECTO)
    ap.add_argument('--hasta', type=int)
    a = ap.parse_args()
    print(json.dumps(ingerir(a.desde, a.hasta), ensure_ascii=False, indent=1))
