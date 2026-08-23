#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v163 — FOTOS DIARIAS DE LAS LÍNEAS DE REMATES.

Por qué existe
--------------
Lo mismo que `snapshots_corners.py` (v159) y `snapshots_tarjetas.py` (v160), y
por la razón exacta. La probabilidad de remates ya está calibrada —0,0131 de
error por equipo en remates totales y 0,0129 a puerta contra la frecuencia
real, medido sobre 41.000 equipos-partido (§13 de la bitácora)— y con eso se
puede calcular un EV frente a la cuota de la casa.

Lo que no se puede es saber si ese EV gana dinero: **no existe histórico de
líneas de remates**. football-data no las publica y el histórico de The Odds
API es de pago. Sin líneas pasadas no hay apuestas que liquidar, y la regla de
oro del proyecto —percentil 5 positivo en el tramo de juicio— no se puede ni
aplicar. Por eso la tarjeta pinta los remates en ÁMBAR y no en verde, y por eso
sin este fichero **nunca podrían salir de ahí**.

Esto empieza a construir ese histórico. Una foto al día por partido y línea.

DOS MERCADOS, Y HAY QUE DISTINGUIRLOS
--------------------------------------
La casa cotiza «Total de remates» y «Total de remates a puerta» por separado, y
el modelo también los calcula por separado —tienen dispersiones distintas (2,09
contra 1,36 por equipo) y niveles distintos—. Guardar los dos revueltos haría
inservible el histórico, así que cada fila lleva su `objetivo`: `tot` o `on`.

La distinción se hace por la etiqueta de la familia, con las palabras que la
casa usa de verdad. Cuando dice «a puerta», «a portería», «on target» o «al
arco» es el mercado corto; si no, el total.

QUÉ SE GUARDA Y QUÉ NO
----------------------
Las de EQUIPO Y PARTIDO. Las de JUGADOR no, por el mismo motivo que en
tarjetas y con un matiz: aquí sí existe la estadística por jugador (ESPN la
publica y `remates_jugadores` la lee), pero no hay HISTÓRICO propio con el que
liquidar una línea pasada — la fuente da los últimos partidos, no un archivo.
El día que lo haya, se quita el filtro y estas familias entran.

NUNCA SE PISA UNA FOTO ANTERIOR
-------------------------------
Cada día es una fila nueva; la clave es partido+mercado+día, así que una
segunda ejecución el mismo día no duplica. Eso permite reconstruir el
movimiento de la línea, que es la mitad del valor de esto.

Uso:
    python snapshots_remates.py
    python snapshots_remates.py --liga premier
"""
import argparse
import logging
import os
import re as _re
import time
from typing import Dict, List, Optional

import pandas as pd

# Los dos ayudantes son los mismos que usan córners y tarjetas, y se reutilizan
# en vez de copiarse: si algún día la casa cambia el formato del número de una
# línea, tiene que cambiar en un solo sitio.
from snapshots_corners import _hoy, _linea_de
from snapshots_tarjetas import _CODIGO_EQUIPO, _sin_parentesis

logger = logging.getLogger('snapshots_remates')

FICHERO = os.environ.get('REMATES_SNAPSHOTS', 'remates_snapshots.csv')
COLUMNAS = ['snapshot_key', 'capturado_en', 'clave_liga', 'fecha_partido',
            'home', 'away', 'casa', 'objetivo', 'familia', 'mercado', 'linea',
            'cuota', 'dias_al_partido']

# LAS PALABRAS, CON LÍMITE DE PALABRA Y POR LA MISMA LECCIÓN QUE EN TARJETAS.
#
# Allí «card» entraba dentro de «Cardona» y «Amarilla» es literalmente el
# apellido de un jugador del Villarreal. Aquí el riesgo es el mismo con «tiro»
# y «remate», que son apellidos posibles, y peor: «Tiros de esquina» ES el
# mercado de CÓRNERS y lleva la palabra «tiros» dentro. Si entrara aquí, este
# fichero acumularía córners rotulados como remates y la liquidación futura
# saldría mal sin que nada lo denunciara.
_PALABRAS = _re.compile(r'\b(remates?|disparos?|tiros?|shots?)\b')
# Lo que lleva estas palabras NO es un remate aunque lo parezca.
#
# EL PLURAL NO ES UN DETALLE. La primera versión escribía `libre` y `falta` en
# singular, y con `\b` a los lados «Total de tiros libres» NO casaba: entraba
# como mercado de remates. Un tiro libre no es un remate, y ese fichero se
# acumula durante meses antes de que nadie lo liquide, así que el error habría
# salido a la luz cuando ya no tuviera arreglo. Todas llevan `s?`.
_NO_ES = _re.compile(
    r'\b(esquinas?|c[oó]rner(?:s|es)?|saques?|libres?|penal(?:ti|ty)(?:s|es)?|'
    r'faltas?)\b')
# El mercado corto. «a puerta», «a portería», «al arco» y «on target» son las
# cuatro formas que usa la casa en español y en inglés.
_A_PUERTA = _re.compile(
    r'(a\s+puerta|a\s+porter[ií]a|al\s+arco|on\s+target|a\s+gol)')
# Forma de mercado de conteo: sin esto, «Primer jugador en rematar» entraría.
_FORMA_MERCADO = _re.compile(
    r'\b(total|totales|ambos|mitad|tiempo|exact[oa]s?|impar|par|'
    r'h[áa]ndicap|1x2|m[áa]s de|menos de|over|under)\b')
_DE_JUGADOR = ('jugador', 'player')


def objetivo_de(texto: str) -> Optional[str]:
    """
    Qué mercado de remates es esta familia: 'tot', 'on', o `None` si no lo es.

    Cuatro filtros, heredados de la experiencia de tarjetas más uno propio:

      1. **quitar los paréntesis antes de buscar la palabra**, para que un
         apellido dentro de «(...)» no meta una familia de goleadores.
      2. **descartar lo que lleve un código de equipo entre paréntesis**, que
         es como se cuela el apellido cuando no va entre paréntesis solo.
      3. **descartar «jugador» o «player»**: son por persona y no hay
         histórico propio con el que liquidarlas.
      4. **descartar los TIROS QUE NO SON REMATES** — y éste es el nuevo. «Tiros
         de esquina» es el mercado de CÓRNERS y contiene la palabra «tiros»;
         sin este filtro, este fichero acumularía córners rotulados como
         remates. También caen tiros libres y penaltis.

    Y además se exige forma de mercado de conteo, para que «Primer jugador en
    rematar» no entre por la puerta de atrás.
    """
    crudo = str(texto or '')
    if _CODIGO_EQUIPO.search(crudo):
        return None
    t = _sin_parentesis(crudo).lower()
    if any(p in t for p in _DE_JUGADOR):
        return None
    if _NO_ES.search(t):
        return None
    if not _PALABRAS.search(t):
        return None
    if not _FORMA_MERCADO.search(t):
        return None
    return 'on' if _A_PUERTA.search(t) else 'tot'


def lineas_de_remates(deporte: str, home: str, away: str) -> List[Dict]:
    """
    Todas las líneas de remates de equipo y partido que cotiza la casa.

    Se filtra por el NOMBRE de la familia y no por una lista de mercados
    conocidos, por el mismo motivo que en córners y tarjetas: la casa renombra
    y añade familias cada temporada, y una lista fija dejaría de capturar en
    silencio justo lo que esto existe para acumular.
    """
    try:
        import cuotas_multi as cm
        tablero = cm.mercados_playdoit(deporte, home, away) or {}
    except Exception as e:
        logger.debug('[remates/snap] tablero %s-%s: %s', home, away, e)
        return []
    filas = []
    for fam in (tablero.get('mercados') or []):
        if not isinstance(fam, dict):
            continue
        nombre_fam = str(fam.get('nombre') or '')
        obj = objetivo_de(nombre_fam)
        if not obj:
            continue
        # La línea sale de la ETIQUETA, con `sv` de respaldo. Misma lección que
        # en córners: «Total de remates» llega con un `sv` y sus selecciones
        # dicen «Más de 22.5», «Más de 24.5» y «Más de 26.5». Guardar el mismo
        # número en las tres haría inservible el histórico entero.
        linea_fam = _linea_de(fam.get('sv'))
        for sel in (fam.get('selecciones') or []):
            if not isinstance(sel, dict):
                continue
            etq = str(sel.get('nombre') or '')
            try:
                cuota = float(sel.get('cuota'))
            except (TypeError, ValueError):
                continue
            if cuota <= 1.0:
                continue
            linea_etq = _linea_de(etq)
            filas.append({
                'objetivo': obj, 'familia': nombre_fam, 'mercado': etq,
                'linea': linea_etq if linea_etq is not None else linea_fam,
                'cuota': round(cuota, 3)})
    return filas


def _existentes() -> set:
    if not os.path.exists(FICHERO):
        return set()
    try:
        d = pd.read_csv(FICHERO, usecols=['snapshot_key'])
        return set(d['snapshot_key'].astype(str))
    except Exception:
        return set()


def capturar(dias: int = 2, solo: Optional[str] = None) -> Dict:
    """
    Recorre los partidos próximos de las competiciones CON remates observados
    y guarda lo que cotice la casa.

    Sólo ésas: en las demás la columna de remates la escribió el generador
    sintético, así que nunca se podrá liquidar la línea contra un resultado
    real, y guardarla sería acumular un dato muerto.
    """
    import fixtures_espn
    from config import LEAGUES

    try:
        import rendimiento_equipos as rq
    except Exception as e:
        logger.error('sin rendimiento_equipos: %s', e)
        return {'filas': 0}

    claves = [c for c, cfg in LEAGUES.items()
              if cfg.get('disponible') and c in fixtures_espn.ESPN_CODIGOS]
    if solo:
        claves = [c for c in claves if c == solo]
    claves = [c for c in claves
              if (rq.stats_disponibles(c) or {}).get('remates')]
    logger.info('competiciones con remates observados: %d', len(claves))

    fixtures = fixtures_espn.fixtures_multi(claves, dias=dias)
    vistos = _existentes()
    hoy, ahora = _hoy(), pd.Timestamp.now('UTC').isoformat()
    nuevas, partidos, t0 = [], 0, time.time()

    for clave in claves:
        for fx in (fixtures.get(clave) or []):
            h, a = fx.get('home'), fx.get('away')
            if not h or not a:
                continue
            partidos += 1
            for fila in lineas_de_remates('futbol', h, a):
                clave_snap = '%s|%s|%s|%s|%s|%s' % (
                    clave, h, a, fila['familia'], fila['mercado'], hoy)
                if clave_snap in vistos:
                    continue
                vistos.add(clave_snap)
                try:
                    d_al = int((pd.Timestamp(fx.get('fecha')).normalize()
                                - pd.Timestamp(hoy)).days)
                except Exception:
                    d_al = None
                nuevas.append({
                    'snapshot_key': clave_snap, 'capturado_en': ahora,
                    'clave_liga': clave,
                    'fecha_partido': str(fx.get('fecha') or '')[:10],
                    'home': h, 'away': a, 'casa': 'playdoit',
                    'objetivo': fila['objetivo'], 'familia': fila['familia'],
                    'mercado': fila['mercado'], 'linea': fila['linea'],
                    'cuota': fila['cuota'], 'dias_al_partido': d_al})

    if nuevas:
        df = pd.DataFrame(nuevas, columns=COLUMNAS)
        cabecera = not os.path.exists(FICHERO)
        df.to_csv(FICHERO, mode='a', header=cabecera, index=False,
                  encoding='utf-8')
    logger.info('%d filas nuevas de %d partidos en %.0f s',
                len(nuevas), partidos, time.time() - t0)
    return {'filas': len(nuevas), 'partidos': partidos,
            'competiciones': len(claves),
            'segundos': round(time.time() - t0, 1)}


def main():
    logging.basicConfig(level=logging.INFO,
                        format='%(asctime)s %(levelname)s %(message)s')
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--liga', default=None)
    ap.add_argument('--dias', type=int, default=2)
    args = ap.parse_args()
    r = capturar(dias=args.dias, solo=args.liga)
    print('%d filas nuevas · %d partidos · %d competiciones · %.0f s'
          % (r.get('filas', 0), r.get('partidos', 0),
             r.get('competiciones', 0), r.get('segundos', 0)))
    if os.path.exists(FICHERO):
        try:
            d = pd.read_csv(FICHERO, usecols=['snapshot_key', 'objetivo'])
            print('acumulado en %s: %d filas (%s)'
                  % (FICHERO, len(d),
                     ', '.join('%s %d' % (k, v) for k, v
                               in d['objetivo'].value_counts().items())))
        except Exception:
            pass


if __name__ == '__main__':
    main()
