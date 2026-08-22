#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v160 — FOTOS DIARIAS DE LAS LÍNEAS DE TARJETAS.

Por qué existe
--------------
Lo mismo que `snapshots_corners.py`, y por la misma razón exacta. La
probabilidad de tarjetas ya está calibrada —0,0121 de error para el total y
0,0141 por equipo contra la frecuencia real, medido sobre 26.324 y 52.648
observaciones de juicio— y con eso se puede calcular un EV frente a la cuota de
la casa.

Lo que no se puede es saber si ese EV gana dinero: **no existe histórico de
líneas de tarjetas**. football-data no las publica y el histórico de The Odds
API es de pago. Sin líneas pasadas no hay apuestas que liquidar, y la regla de
oro del proyecto —percentil 5 positivo en el tramo de juicio— no se puede ni
aplicar. Por eso la tarjeta pinta las tarjetas en ÁMBAR y no en verde.

Esto empieza a construir ese histórico. Una foto al día por partido y línea.

QUÉ SE GUARDA Y QUÉ NO
----------------------
La casa cotiza 851 familias en un partido de Premier, y muchas son de tarjetas:
«Total de tarjetas», «Total de tarjetas <Equipo>», «Tarjetas 1x2», «Tarjetas
exactas», «Total tarjetas Impar/Par», «1ª Mitad - Total de tarjetas» y **una
familia por jugador** («Jugador recibe una tarjeta (Fulano)»).

Se guardan las de EQUIPO Y PARTIDO. Las de jugador NO, y es una decisión, no un
olvido: son ~40 familias por partido —el grueso del tablero— y no hay forma de
liquidarlas, porque este proyecto no tiene histórico de tarjetas por jugador
con el que comparar. Acumularlas engordaría el fichero diez veces con filas que
nadie va a poder medir nunca. El día que haya esa fuente, se quita el filtro.

UNA COSA QUE ESTE HISTÓRICO TENDRÁ QUE RESPONDER
------------------------------------------------
El modelo cuenta AMARILLAS, que es lo que football-data publica partido a
partido y lo que se ha calibrado. La casa rotula su mercado «Total de
tarjetas», y no dice si una roja cuenta como una tarjeta, como dos, o si una
segunda amarilla se cuenta dos veces. La diferencia no es despreciable: las
rojas van de 0,11 a 0,20 por partido según la competición.

No se resuelve suponiendo. Se resuelve con estos datos: cuando haya volumen,
comparar la frecuencia real de «Más de 4,5» contra el resultado en amarillas y
contra el resultado en amarillas+rojas dirá cuál de los dos cuenta la casa. Por
eso la interfaz dice «amarillas» donde enseña el número —para no prometer que
es la misma magnitud que la línea de la casa— y por eso este fichero guarda la
etiqueta literal del mercado.

NUNCA SE PISA UNA FOTO ANTERIOR
-------------------------------
Cada día es una fila nueva; la clave es partido+mercado+día, así que una
segunda ejecución el mismo día no duplica. Eso permite reconstruir el
movimiento de la línea, que es la mitad del valor de esto.

Uso:
    python snapshots_tarjetas.py
    python snapshots_tarjetas.py --liga premier
"""
import argparse
import logging
import os
import time
from typing import Dict, List, Optional

import pandas as pd

# Los dos ayudantes son idénticos a los de córners y se reutilizan en vez de
# copiarse: si algún día la casa cambia el formato del número de una línea,
# tiene que cambiar en un solo sitio.
from snapshots_corners import _hoy, _linea_de

logger = logging.getLogger('snapshots_tarjetas')

FICHERO = os.environ.get('TARJETAS_SNAPSHOTS', 'tarjetas_snapshots.csv')
COLUMNAS = ['snapshot_key', 'capturado_en', 'clave_liga', 'fecha_partido',
            'home', 'away', 'casa', 'familia', 'mercado', 'linea', 'cuota',
            'dias_al_partido']

import re as _re

# LAS PALABRAS SE BUSCAN CON LÍMITE DE PALABRA, Y HAY DOS CLASES.
#
# El tablero real obligó a separarlas. Buscando subcadenas sueltas, «card»
# entraba dentro de «Cardona» y «amarilla» ES el apellido de un jugador del
# Villarreal («Diego Alexander Gomez Amarilla»), así que cuatro familias de
# GOLEADORES pasaban por mercados de tarjetas.
#
#   · FUERTES: la palabra no puede ser un apellido ni parte de otro. Basta con
#     que aparezca para que la familia sea de tarjetas.
#   · DÉBILES: pueden ser un apellido, así que además exigen que la familia
#     tenga FORMA de mercado de conteo («total», «ambos», «exacto», «impar»…).
#     Se conservan en vez de borrarlas porque el día que la casa rotule «Total
#     de amarillas» hay que seguir capturándolo, y una lista que sólo mira
#     «tarjeta» dejaría de hacerlo sin avisar.
_PALABRAS_FUERTES = _re.compile(
    r'\b(tarjetas?|amonestaci[oó]n(?:es)?|amonestad[oa]s?|bookings?)\b')
_PALABRAS_DEBILES = _re.compile(r'\b(amarillas?|cards?)\b')
_FORMA_MERCADO = _re.compile(
    r'\b(total|ambos|mitad|tiempo|exact[oa]s?|impar|par|h[áa]ndicap|1x2|'
    r'm[áa]s de|menos de)\b')

# Se mantiene para quien quiera la lista suelta (y para los tests, que
# comprueban que ninguna palabra se pierde por el camino).
_PALABRAS = ('tarjeta', 'amonesta', 'amarilla', 'booking', 'card')
# Las familias por jugador llevan el nombre entre paréntesis y empiezan por
# «Jugador». Se reconocen por eso y no por una lista de nombres, que sería
# imposible de mantener.
_DE_JUGADOR = ('jugador', 'player')


def _sin_parentesis(texto: str) -> str:
    """El nombre de la familia sin lo que va entre paréntesis.

    HAY QUE QUITARLO ANTES DE BUSCAR PALABRAS, Y LO DESTAPÓ LA PRIMERA CAPTURA.
    Entre paréntesis va el nombre del jugador, y un apellido puede ser
    cualquier cosa: «Primer goleador y marcador exacto (Diego Alexander Gomez
    Amarilla)» contiene «amarilla» y entró como mercado de tarjetas. Con él
    entraron 409 familias distintas donde debía haber unas diez, y el fichero
    que esto existe para acumular se habría llenado de goleadores.

    Se quita a mano y no con `re` con paréntesis anidados porque los hay:
    «Jugador recibe una tarjeta (Abdelhamid Sabiri (EYU))». Contar profundidad
    los cubre; una expresión regular ingenua, no.
    """
    salida, prof = [], 0
    for ch in str(texto or ''):
        if ch == '(':
            prof += 1
        elif ch == ')':
            prof = max(prof - 1, 0)
        elif prof == 0:
            salida.append(ch)
    return ''.join(salida)


# El marcador inequívoco de que una familia es de un JUGADOR: el código de su
# equipo entre paréntesis — «(BHA)», «(EYU)», «(MNC)». La casa lo pone siempre
# que el mercado va sobre una persona, y no lo pone nunca en los mercados de
# equipo o de partido.
_CODIGO_EQUIPO = _re.compile(r'\([A-ZÁÉÍÓÚÑ]{2,4}\)')


def _es_tarjeta(texto: str) -> bool:
    """
    ¿Esta familia de la casa es de tarjetas de equipo o de partido?

    Cuatro filtros, y los cuatro los pidió el tablero real —4.105 familias
    distintas en tres partidos—, ninguno se inventó por adelantado:

      1. **quitar los paréntesis antes de buscar la palabra.** Si no, «Primer
         goleador y marcador exacto (Diego Alexander Gomez Amarilla)» entra por
         el APELLIDO del jugador. Sin este filtro pasaban 358 familias.
      2. **descartar lo que lleve un código de equipo entre paréntesis.** El
         apellido no siempre va entre paréntesis: «Tackleadas - Diego Alexander
         Gomez Amarilla (BHA) (alineación inicial)» sobrevivía al filtro 1 y
         volvía a entrar por lo mismo.
      3. **límite de palabra, y palabras débiles con forma de mercado.** Aún
         pasaban cuatro: «Multigoleadores Sergi Cardona Bermadez» entraba
         porque «card» está dentro de «Cardona», y «Goleador O el sustituto
         anotará - Diego Alexander Gomez Amarilla» porque «Amarilla» es
         literalmente su apellido. Ver el comentario de `_PALABRAS_FUERTES`.
      4. **descartar lo que diga «jugador» o «player».** «Jugador recibe una
         tarjeta» sí es de tarjetas, pero es por persona, y este proyecto no
         tiene histórico de tarjetas por jugador con el que liquidarla nunca.

    Con los cuatro quedan las ~40 familias de equipo y partido que son las que
    se pueden liquidar el día que haya volumen.
    """
    crudo = str(texto or '')
    if _CODIGO_EQUIPO.search(crudo):
        return False
    t = _sin_parentesis(crudo).lower()
    if any(p in t for p in _DE_JUGADOR):
        return False
    if _PALABRAS_FUERTES.search(t):
        return True
    return bool(_PALABRAS_DEBILES.search(t) and _FORMA_MERCADO.search(t))


def lineas_de_tarjetas(deporte: str, home: str, away: str) -> List[Dict]:
    """
    Todas las líneas de tarjetas de equipo y partido que cotiza la casa.

    Se filtra por el NOMBRE de la familia y no por una lista de mercados
    conocidos, por el mismo motivo que en córners: la casa renombra y añade
    familias cada temporada, y una lista fija dejaría de capturar en silencio
    justo lo que esto existe para acumular.
    """
    try:
        import cuotas_multi as cm
        tablero = cm.mercados_playdoit(deporte, home, away) or {}
    except Exception as e:
        logger.debug('[tarjetas/snap] tablero %s-%s: %s', home, away, e)
        return []
    filas = []
    for fam in (tablero.get('mercados') or []):
        if not isinstance(fam, dict):
            continue
        nombre_fam = str(fam.get('nombre') or '')
        if not _es_tarjeta(nombre_fam):
            continue
        # La línea sale de la ETIQUETA, con `sv` de respaldo. Misma lección que
        # en córners: «Total de tarjetas» llega con sv=5.5 y sus selecciones
        # dicen «Más de 4.5», «Más de 5.5» y «Más de 6.5». Guardar 5,5 en las
        # tres haría inservible el histórico entero.
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
                'familia': nombre_fam, 'mercado': etq,
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
    Recorre los partidos próximos de las competiciones CON tarjetas observadas
    y guarda lo que cotice la casa.

    Sólo esas 20: en las demás la columna de amarillas la escribió el generador
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
              if (rq.stats_disponibles(c) or {}).get('tarjetas')]
    logger.info('competiciones con tarjetas observadas: %d', len(claves))

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
            for fila in lineas_de_tarjetas('futbol', h, a):
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
                    'familia': fila['familia'], 'mercado': fila['mercado'],
                    'linea': fila['linea'], 'cuota': fila['cuota'],
                    'dias_al_partido': d_al})

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
            total = len(pd.read_csv(FICHERO, usecols=['snapshot_key']))
            print('acumulado en %s: %d filas' % (FICHERO, total))
        except Exception:
            pass


if __name__ == '__main__':
    main()
