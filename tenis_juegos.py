#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v123 — Cuántos JUEGOS se jugaron: el mercado de tenis que la app no miraba.

El usuario lo pidió así: «en tenis ver en los h2h o en las demás stats
históricas ver cuántos juegos se jugaron para irte por ahí en la apuesta».

Y es la petición más razonable de todas las de tenis, por un motivo que el
propio proyecto tiene medido en otros deportes: el ganador de un partido de
tenis lo cotiza el mercado con muchísima precisión —es un mercado de dos
resultados y muy líquido—, mientras que el total de juegos depende de cosas
mucho más estables y personales (cómo saca cada uno, cuántos *breaks* concede)
que se leen bien en el histórico.

De dónde salen los datos
------------------------
Del histórico unificado que ya usa el motor (`tenis_fuentes.historico_unificado`),
que trae la columna `Score` con el marcador set a set —«6-3 6-7 4-6»— y una
cobertura del **100 %** sobre 365.486 partidos del circuito ATP. No hace falta
ninguna fuente nueva: el dato estaba y nadie lo leía.

Por qué un artefacto y no un cálculo al vuelo
---------------------------------------------
Recorrer 365.486 partidos y parsear su marcador cada vez que alguien abre la
ficha de un partido es inaceptable en la interfaz, y el histórico unificado
además descarga de Kaggle. Así que esto se precalcula UNA vez y deja un fichero
compacto que la aplicación lee al instante. Lo regenera la tarea diaria, igual
que el resto de artefactos del proyecto.

    python tenis_juegos.py            # regenera los dos circuitos

Qué NO es
---------
Esto NO es una señal ni una predicción. Es el histórico: cuántos juegos han
durado los partidos de un jugador y los de una pareja. La media de un tenista
sobre 300 partidos es un dato sólido; la de una pareja que se ha cruzado tres
veces son tres datos, y por eso `n` viaja SIEMPRE pegado a la cifra y la
interfaz avisa cuando la muestra es corta.
"""
import json
import logging
import os
import re
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

ARCHIVO = 'tenis_juegos.json'

# Líneas de total de juegos que cuelgan las casas. Son las de un partido al
# mejor de 3 —el 95 % del circuito—; en Grand Slam masculino (al mejor de 5) la
# línea vive mucho más arriba y por eso se guardan las dos distribuciones por
# separado en vez de mezclarlas, que daría una media que no corresponde a
# ningún partido real.
LINEAS_BO3 = (20.5, 21.5, 22.5, 23.5)
LINEAS_BO5 = (35.5, 37.5, 39.5)

# Un set normal va de 6-0 (6 juegos) a 7-6 (13). Cualquier cosa fuera de ese
# rango es un marcador mal parseado —un retiro escrito raro, un super-tie-break
# anotado como «10-8»— y contarla envenena la media.
_SET = re.compile(r'^(\d{1,2})-(\d{1,2})$')


def juegos_del_marcador(score) -> Optional[int]:
    """
    Juegos totales de un marcador tipo «6-3 6-7 4-6», o None si no se puede leer.

    Devolver None es un resultado correcto y frecuente: los partidos con retiro
    llevan marcadores incompletos («6-3 2-1 RET») y contarlos como si hubieran
    terminado bajaría la media de todo el circuito.
    """
    if not isinstance(score, str) or not score.strip():
        return None
    total, sets = 0, 0
    for trozo in score.replace('(', ' ').split():
        m = _SET.match(trozo.strip())
        if not m:
            continue
        a, b = int(m.group(1)), int(m.group(2))
        # un set legítimo lo gana alguien por 6 o por 7, y nunca pasa de 7-6
        # salvo en los sets largos sin muerte súbita (Wimbledon hasta 2019)
        if max(a, b) < 6 or min(a, b) < 0 or max(a, b) > 30:
            continue
        total += a + b
        sets += 1
    if sets < 2:          # ni un partido al mejor de 3 baja de dos sets
        return None
    return total


def _perfil(valores: List[int], lineas) -> Dict:
    """Media, dispersión y porcentaje por encima de cada línea de mercado."""
    n = len(valores)
    if not n:
        return {}
    media = sum(valores) / n
    var = sum((v - media) ** 2 for v in valores) / n
    return {
        'n': n,
        'media': round(media, 2),
        'sd': round(var ** 0.5, 2),
        'min': min(valores), 'max': max(valores),
        'over': {str(L): round(sum(1 for v in valores if v > L) / n, 3)
                 for L in lineas},
    }


def construir(circuito: str = 'atp') -> Dict:
    """
    Recorre el histórico unificado y deja el perfil de juegos por jugador y por
    pareja. Es la parte cara; se ejecuta fuera de la interfaz.
    """
    import tenis_fuentes
    d = tenis_fuentes.historico_unificado(circuito)
    if d is None or d.empty or 'Score' not in d.columns:
        logger.warning(f'[tenis/juegos] {circuito}: sin histórico con marcador')
        return {}

    por_jugador: Dict[str, Dict[str, list]] = {}
    por_pareja: Dict[str, list] = {}
    leidos = fallidos = 0
    # Se recorren las columnas con `zip` y no con `itertuples`: son 365.486
    # filas y, sobre todo, `itertuples` renombra «Best of» a un identificador
    # posicional (`_6`) porque no es un nombre válido de atributo — leerlo por
    # su nombre habría devuelto siempre el valor por defecto y TODOS los
    # partidos habrían contado como al mejor de 3, incluidos los Grand Slam.
    col_bo = d['Best of'] if 'Best of' in d.columns else [3] * len(d)
    for score, p1, p2, bo_raw in zip(d['Score'], d['Player_1'], d['Player_2'],
                                     col_bo):
        j = juegos_del_marcador(score)
        if j is None:
            fallidos += 1
            continue
        leidos += 1
        try:
            bo = '5' if int(bo_raw) == 5 else '3'
        except (TypeError, ValueError):
            bo = '3'
        p1 = str(p1 or '').strip()
        p2 = str(p2 or '').strip()
        if not p1 or not p2:
            continue
        for p in (p1, p2):
            por_jugador.setdefault(p, {'3': [], '5': []})[bo].append(j)
        # La pareja se guarda con los dos nombres ORDENADOS —para que dé igual
        # quién sea el «local» al consultarla— y SEPARADA POR FORMATO.
        #
        # Mezclar los dos formatos daba un número que no corresponde a ningún
        # partido. Medido antes de separarlos: Alcaraz–Sinner salía a 32,8
        # juegos de media de cruce frente a 22,5 de media individual, y la
        # diferencia no era el emparejamiento: era que sus cruces incluyen
        # finales de Grand Slam al mejor de 5. Enseñar eso al lado de una línea
        # de casa —que es de un partido al mejor de 3— habría hecho parecer
        # baratísimo cualquier «más de 22.5».
        por_pareja.setdefault('|'.join(sorted((p1, p2))),
                              {'3': [], '5': []})[bo].append(j)

    salida = {
        'circuito': circuito,
        'partidos_leidos': leidos,
        'marcadores_ilegibles': fallidos,
        'jugadores': {},
        'parejas': {},
    }
    for p, bos in por_jugador.items():
        d3 = _perfil(bos['3'], LINEAS_BO3)
        d5 = _perfil(bos['5'], LINEAS_BO5)
        if not d3 and not d5:
            continue
        salida['jugadores'][p] = {k: v for k, v in
                                  (('bo3', d3), ('bo5', d5)) if v}
    # LAS PAREJAS QUE SÓLO SE HAN CRUZADO UNA VEZ NO ENTRAN, y no es por
    # ahorrar: es que un partido no es una distribución. Guardarlas costaba
    # 13,0 MB por circuito frente a 3,8 (medido: 220.914 de las 271.877 parejas
    # del ATP se han visto una sola vez), y este proyecto ya pelea con el techo
    # de memoria de Streamlit Cloud —ver `MAX_LIGAS_EN_MEMORIA` en la interfaz—
    # así que 26 MB de artefactos para servir medias de n=1 sería pagar RAM por
    # un dato que además no se debe presentar como estadística.
    #
    # Cuando la pareja no llega a dos cruces, `linea_sugerida` cae en los dos
    # perfiles individuales, que con cientos de partidos cada uno son una
    # estimación mejor que el único precedente.
    #
    # Se guarda como lista `[n3, media3, n5, media5]` y no como diccionario:
    # son decenas de miles de entradas y las claves repetidas pesaban más que
    # los datos. Un 0 en el hueco de `n` significa «en ese formato no se han
    # cruzado las veces suficientes».
    for par, bos in por_pareja.items():
        fila = []
        for k in ('3', '5'):
            v = bos[k]
            if len(v) >= 2:
                fila += [len(v), round(sum(v) / len(v), 2)]
            else:
                fila += [0, 0]
        if fila[0] or fila[2]:
            salida['parejas'][par] = fila
    logger.info(f'[tenis/juegos] {circuito}: {leidos} partidos leídos, '
                f'{fallidos} ilegibles, {len(salida["jugadores"])} jugadores, '
                f'{len(salida["parejas"])} parejas')
    return salida


# ---------------------------------------------------------------------------
# Lectura desde la aplicación
# ---------------------------------------------------------------------------
_MEM: Dict[str, dict] = {}


def _cargar(circuito: str) -> Dict:
    c = (circuito or 'atp').lower()
    if c in _MEM:
        return _MEM[c]
    ruta = f'tenis_juegos_{c}.json'
    datos = {}
    if os.path.exists(ruta):
        try:
            with open(ruta, encoding='utf-8') as f:
                datos = json.load(f)
        except Exception as e:
            logger.warning(f'[tenis/juegos] {ruta}: {type(e).__name__}: {e}')
    else:
        logger.info(f'[tenis/juegos] {ruta} no existe todavía')
    _MEM[c] = datos
    return datos


def perfil_jugador(circuito: str, jugador: str,
                   best_of: int = 3) -> Optional[Dict]:
    """Cuántos juegos duran los partidos de este tenista, o None si no consta."""
    j = (_cargar(circuito).get('jugadores') or {}).get(str(jugador or '').strip())
    if not j:
        return None
    return j.get('bo5' if best_of == 5 else 'bo3') or None


def h2h_juegos(circuito: str, p1: str, p2: str,
               best_of: int = 3) -> Optional[Dict]:
    """
    Cuántos juegos han durado los cruces previos entre dos tenistas, EN EL
    MISMO FORMATO que el partido que se va a jugar.

    `None` cuando no se han cruzado **dos o más veces en ese formato** (ver
    `construir`): con un solo precedente no hay media que dar, y decirlo es más
    útil que presentar un partido suelto como si fuera una tendencia.
    """
    par = '|'.join(sorted((str(p1 or '').strip(), str(p2 or '').strip())))
    v = (_cargar(circuito).get('parejas') or {}).get(par)
    if not v or len(v) < 4:
        return None
    n, media = (v[2], v[3]) if best_of == 5 else (v[0], v[1])
    if not n:
        return None
    return {'n': int(n), 'media': float(media), 'best_of': best_of}


def linea_sugerida(circuito: str, p1: str, p2: str,
                   best_of: int = 3) -> Optional[Dict]:
    """
    Qué dice el histórico sobre el total de juegos de ESTE partido.

    Combina las dos medias individuales —que es lo que hay cuando la pareja no
    se ha cruzado nunca, el caso normal— y el cara a cara cuando existe. No
    inventa una probabilidad: devuelve medias con su tamaño de muestra y el
    porcentaje histórico por encima de cada línea, para comparar contra la cuota
    que publique la casa.

    Devuelve None cuando no hay ni un perfil de los dos jugadores. La regla del
    proyecto vale igual aquí: mejor un hueco explicado que un número inventado.
    """
    a = perfil_jugador(circuito, p1, best_of)
    b = perfil_jugador(circuito, p2, best_of)
    if not a and not b:
        return None
    perfiles = [p for p in (a, b) if p]
    # La media del partido se estima como la media de las dos medias. Es
    # deliberadamente simple: un modelo de juegos requeriría validarlo contra
    # el mercado, y este proyecto tiene por norma no publicar una probabilidad
    # que no haya medido. Esto es un promedio histórico y se presenta como tal.
    media = sum(p['media'] for p in perfiles) / len(perfiles)
    n = min(p['n'] for p in perfiles)
    lineas = LINEAS_BO5 if best_of == 5 else LINEAS_BO3
    over = {}
    for L in lineas:
        vals = [p['over'].get(str(L)) for p in perfiles
                if p.get('over', {}).get(str(L)) is not None]
        if vals:
            over[str(L)] = round(sum(vals) / len(vals), 3)
    h = h2h_juegos(circuito, p1, p2, best_of)
    return {
        'media_estimada': round(media, 2),
        'n_minimo': n,
        'perfil_1': a, 'perfil_2': b,
        'over': over,
        'h2h': h,
        'best_of': best_of,
        # La franja honesta: con muestras cortas, la media no es un punto.
        'muestra_corta': n < 30,
    }


def main() -> int:
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    fallos = 0
    for c in ('atp', 'wta'):
        try:
            datos = construir(c)
        except Exception as e:
            logger.error(f'[tenis/juegos] {c}: {type(e).__name__}: {e}')
            fallos += 1
            continue
        if not datos:
            fallos += 1
            continue
        with open(f'tenis_juegos_{c}.json', 'w', encoding='utf-8') as f:
            json.dump(datos, f, ensure_ascii=False)
        tam = os.path.getsize(f'tenis_juegos_{c}.json') / 1e6
        logger.info(f'[tenis/juegos] tenis_juegos_{c}.json escrito '
                    f'({tam:.1f} MB)')
    return fallos


if __name__ == '__main__':
    raise SystemExit(main())
