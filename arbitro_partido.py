#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v160 — EL ÁRBITRO DESIGNADO, Y CUÁNTO MUEVE LAS TARJETAS.

Para qué
--------
El estimador de tarjetas (`rendimiento_equipos.tarjetas_equipo`) mira a los dos
equipos. Falta el tercero que reparte: el árbitro. Este módulo dice quién pita
el partido de hoy y con qué severidad, y devuelve un factor multiplicativo ya
encogido para aplicárselo a las lambdas.

DE DÓNDE SALE, Y POR QUÉ NO DE ESPN
-----------------------------------
Se sondeó ESPN primero, que es la fuente que ya alimenta el barrido. ESPN SÍ
publica el árbitro, en `summary` → `gameInfo.officials`. Pero medido el
2026-08-22 sobre 139 eventos de las 20 competiciones que publican tarjetas
observadas, en una ventana de ±6 días:

    partidos ya jugados ('post') ....  88 de 98 con árbitro   89,8 %
    partidos por jugar  ('pre')  ....   0 de 41 con árbitro    0,0 %

O sea que ESPN da el árbitro DESPUÉS, y para apostar hace falta ANTES. Cero de
cuarenta y uno no es una laguna de cobertura, es que el campo no se rellena
hasta que el partido empieza.

La fuente que sí lo da antes es FotMob, y lo da completo:

    /api/data/matches?date=YYYYMMDD   -> índice del día (405 partidos, 1 petición)
    /api/data/matchDetails?matchId=N  -> content.matchFacts.infoBox.Referee

y ese `Referee` trae, sin pedir nada más, el nombre, los partidos que lleva
arbitrados, sus amarillas por partido Y LA MEDIA DE SU COMPETICIÓN. Verificado
sobre partidos en estado `started: False` — Brighton-Aston Villa del 23/8 daba
«Peter Bankes, 45 partidos, 3,96 amarillas por partido, media de la liga
4,02» un día antes de jugarse.

Que traiga la media de la liga es lo que hace esto sólido: el ajuste es una
RAZÓN (la del árbitro dividida por la de su competición), así que no importa
que FotMob cuente las tarjetas con otro criterio que football-data, ni que la
ventana temporal de sus medias sea otra. Una razón es adimensional.

CUÁNTO APORTA, MEDIDO
---------------------
No se da por supuesto que el árbitro sea señal: se comprobó con las 7
competiciones cuyo histórico SÍ trae quién pitó cada partido (las inglesas y
escocesas de football-data; las otras 13 tienen la columna vacía). Walk-forward
causal, tramo de juicio el último 30 %, n = 11.375 partidos, sobre el total del
partido en las líneas 2,5 / 3,5 / 4,5 / 5,5:

                                Brier      correlación
    sin árbitro .............  0,20500        0,105
    con árbitro (K=60) ......  0,20357        0,139

Y mejora en las SEIS competiciones, ninguna en contra:

    premier +0,00025 · championship +0,00289 · league one +0,00110
    league two +0,00120 · national +0,00164 · sco premiership +0,00153

La ganancia de Brier es pequeña —0,0014— y conviene decirlo así en vez de
adornarlo. La de correlación no lo es tanto: 0,105 → 0,139 es un tercio más de
señal, y el techo medido para tarjetas es 0,193, así que esto se come una parte
apreciable de lo que quedaba.

POR QUÉ ENCOGER, Y POR QUÉ TANTO
--------------------------------
La razón cruda del árbitro es ruido casi puro cuando lleva pocos partidos, y
aplicarla entera EMPEORA la calibración aunque mejore la correlación. Medido,
el error de calibración según el encogimiento:

    K=0 ....  0,0407      K=20 ...  0,0202      K=60 ...  0,0120
    K=10 ...  0,0260      K=40 ...  0,0150      K=200 ..  0,0114

Con K=60 un árbitro de 45 partidos aporta 45/(45+60) = 43 % de su desviación
observada, y el resto se queda en la media de su competición. Subir más el K
sigue mejorando la calibración pero se lleva la correlación por delante
(0,139 en K=60, 0,125 en K=200); K=60 es donde el Brier toca fondo.

LO QUE ESTO **NO** ES
---------------------
No es una ventaja de precio. Mejora la probabilidad que se enseña, y por eso la
tarjeta la pinta en ÁMBAR: verde en esta aplicación significa «canal con
percentil 5 positivo medido», y para tarjetas todavía no hay histórico de
líneas con el que medirlo. `snapshots_tarjetas.py` lo empieza a acumular.

Tampoco es `arbitros.py`, que es otra cosa y se queda donde está: aquél modela
los árbitros del Mundial 2026 con una tabla FIFA pregrabada y un modelo de
fase de torneo. Éste es el árbitro real de la liga de hoy, sacado de una fuente
en vivo. Comparten tema y no comparten ni datos ni código a propósito.
"""
import argparse
import json
import logging
import os
import time
from typing import Dict, List, Optional, Tuple

import requests

logger = logging.getLogger(__name__)

UA = {'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                     'AppleWebKit/537.36 (KHTML, like Gecko) '
                     'Chrome/126.0.0.0 Safari/537.36'),
      'Referer': 'https://www.fotmob.com/'}
BASE = 'https://www.fotmob.com/api/data'
TIMEOUT = 20
FICHERO = 'arbitros_dia.json'

# Encogimiento hacia la media de la competición. 60 es el valor con el que el
# Brier toca fondo en la medición de arriba; no es un número redondo elegido a
# ojo. Si alguien lo cambia, que sea volviendo a correr
# `_v160_tarjetas_arbitro.py`, que imprime la rejilla entera.
K_ENCOGIMIENTO = 60.0

# Fuera de esta banda el factor no se aplica. Un árbitro no dobla las tarjetas
# de un partido, y un valor así sólo puede venir de una media mal leída.
FACTOR_MIN, FACTOR_MAX = 0.70, 1.40


# ---------------------------------------------------------------------------
# el factor
# ---------------------------------------------------------------------------
def factor(perfil: Optional[Dict], k: float = K_ENCOGIMIENTO) -> float:
    """
    El multiplicador que le corresponde a este árbitro, ya encogido.

    Devuelve 1,0 —o sea, «no tocar nada»— cuando falta cualquier pieza: sin
    árbitro designado, sin media de la competición con la que comparar, o sin
    saber cuántos partidos lleva. Eso es deliberado: la alternativa sería
    suponer una de las tres, y un supuesto invisible aquí se convierte en una
    probabilidad que nadie puede auditar.
    """
    if not perfil:
        return 1.0
    try:
        prop = float(perfil.get('amarillas_por_partido'))
        media = float(perfil.get('media_competicion'))
        n = float(perfil.get('partidos') or 0.0)
    except (TypeError, ValueError):
        return 1.0
    if not (prop > 0 and media > 0) or n <= 0:
        return 1.0
    razon = prop / media
    f = (n * razon + k) / (n + k)
    if not (FACTOR_MIN <= f <= FACTOR_MAX):
        logger.debug('[arbitro] factor fuera de banda (%.3f) para %s: se ignora',
                     f, perfil.get('nombre'))
        return 1.0
    return round(float(f), 4)


# ---------------------------------------------------------------------------
# FotMob
# ---------------------------------------------------------------------------
def _get(url: str, intentos: int = 2) -> Optional[Dict]:
    for i in range(intentos):
        try:
            r = requests.get(url, headers=UA, timeout=TIMEOUT)
            if r.status_code == 200:
                return r.json()
            logger.debug('[arbitro] %s -> HTTP %s', url, r.status_code)
        except Exception as e:
            logger.debug('[arbitro] %s: %s: %s', url, type(e).__name__, e)
        if i + 1 < intentos:
            time.sleep(1.0)
    return None


def indice_dia(fecha: str) -> List[Dict]:
    """
    Todos los partidos que FotMob tiene para un día. UNA petición.

    `fecha` en 'YYYY-MM-DD'. Devuelve lista de dicts con id, equipos y hora.
    """
    d = _get('%s/matches?date=%s' % (BASE, fecha.replace('-', '')))
    if not d:
        return []
    salida = []
    for liga in (d.get('leagues') or []):
        nombre_liga = liga.get('name')
        for m in (liga.get('matches') or []):
            h, a = (m.get('home') or {}), (m.get('away') or {})
            salida.append({
                'match_id': str(m.get('id')),
                'liga': nombre_liga,
                'liga_id': liga.get('id'),
                'home': h.get('longName') or h.get('name'),
                'away': a.get('longName') or a.get('name'),
                'utc': ((m.get('status') or {}).get('utcTime') or ''),
            })
    return salida


def _stat(stats: List[Dict], tipo: str) -> Tuple[Optional[float], Optional[float],
                                                 Optional[float]]:
    """(valor, media de la competición, total) de una estadística del árbitro."""
    for s in (stats or []):
        if s.get('type') == tipo:
            return (s.get('value'), s.get('average'), s.get('total'))
    return (None, None, None)


def perfil_de_partido(match_id: str) -> Optional[Dict]:
    """
    El árbitro designado de un partido y su perfil disciplinario.

    `None` si FotMob no lo ha publicado todavía —pasa con partidos a más de
    unos días vista— o si el bloque no trae la media de su competición, que es
    la mitad imprescindible: sin ella no hay razón que calcular.
    """
    d = _get('%s/matchDetails?matchId=%s' % (BASE, match_id))
    if not d:
        return None
    try:
        ref = (((d.get('content') or {}).get('matchFacts') or {})
               .get('infoBox') or {}).get('Referee')
    except Exception:
        ref = None
    if not isinstance(ref, dict) or not ref.get('text'):
        return None
    stats = ref.get('stats') or []
    partidos, _, _ = _stat(stats, 'matches')
    amar, media, tot_amar = _stat(stats, 'yellowCards')
    _, _, rojas = _stat(stats, 'redCards')
    if amar is None or media is None:
        return None
    return {
        'nombre': ref.get('text'),
        'pais': ref.get('country'),
        'competicion': ref.get('leagueName'),
        'partidos': partidos,
        'amarillas_por_partido': amar,
        'media_competicion': media,
        'amarillas_totales': tot_amar,
        'rojas_totales': rojas,
        'match_id': str(match_id),
        'fuente': 'fotmob',
    }


# ---------------------------------------------------------------------------
# emparejado con nuestros fixtures
# ---------------------------------------------------------------------------
def _norm(nombre: str) -> str:
    try:
        import name_mapper
        return name_mapper.normalizar(nombre or '')
    except Exception:
        return (nombre or '').strip().lower()


# Palabras que no distinguen a un club de otro. `name_mapper.normalizar` ya
# quita los sufijos societarios, pero sólo AL FINAL: «AC Milan» y «AS Roma» los
# llevan delante, y con ellos puestos «AS Roma» contra «Roma» puntúa 0,73 y se
# descarta un emparejado que es obviamente correcto. Aquí se comparan conjuntos
# de palabras, así que da igual dónde estén.
#
# La lista NO incluye nada que separe a dos clubes reales: 'sporting' se queda
# (Sporting CP y Sporting Gijón), 'real' se queda, 'atletico' se queda.
_VACIAS = {
    'fc', 'cf', 'sc', 'ac', 'afc', 'cd', 'ud', 'if', 'bk', 'fk', 'sk', 'kk',
    'club', 'cfr', 'fsv', 'vfl', 'vfb', 'calcio', 'futbol', 'football', 'futebol',
    'as', 'ss', 'ssc', 'rc', 'sv', 'us', 'sd', 'ogc', 'losc', 'rcd', 'sad',
    'de', 'do', 'da', 'del', 'di', 'the', 'stade', 'sporting1', 'nfc', 'sfk',
}


def _tokens(nombre: str) -> frozenset:
    return frozenset(p for p in _norm(nombre).split() if p not in _VACIAS)


def _similitud(a: str, b: str) -> float:
    """
    Cuánto se parecen dos nombres de club, de 0 a 1.

    Compara CONJUNTOS de palabras significativas antes que cadenas, porque las
    fuentes discrepan en el adorno y no en el nombre: «SC Cambuur»/«Cambuur»,
    «Feyenoord Rotterdam»/«Feyenoord», «Volos NFC»/«NFC Volos». Cuando los
    conjuntos no se tocan —«PAOK» contra «Palermo»— cae a la comparación de
    cadenas, que ahí devuelve el 0,36 que corresponde y el emparejado se
    descarta, que es lo que debe pasar.
    """
    from difflib import SequenceMatcher
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return SequenceMatcher(None, _norm(a), _norm(b)).ratio()
    if ta == tb:
        return 1.0
    if ta <= tb or tb <= ta:          # uno contiene al otro entero
        return 0.95
    cadena = SequenceMatcher(None, ' '.join(sorted(ta)),
                             ' '.join(sorted(tb))).ratio()
    comunes = ta & tb
    if comunes:
        jac = len(comunes) / float(len(ta | tb))
        return max(cadena, 0.60 + 0.40 * jac)
    return cadena


def clave_partido(fecha: str, home: str, away: str) -> str:
    """La llave con la que se guarda y se busca un partido."""
    return '%s|%s|%s' % (str(fecha)[:10], _norm(home), _norm(away))


UMBRAL_EMPAREJADO = 0.62
MARGEN_EMPAREJADO = 0.05


def _empareja(fx_home: str, fx_away: str, indice: List[Dict],
              umbral: float = UMBRAL_EMPAREJADO) -> Optional[Dict]:
    """
    El partido de FotMob que corresponde a este fixture, o `None`.

    Tres reglas, y las tres hacen falta:

      · **casan LOS DOS equipos** — manda el peor de los dos parecidos. Que un
        local se parezca mucho no vale nada si el visitante no cuadra.
      · **con margen sobre el segundo** — si el mejor y el siguiente están a
        menos de 0,05, no se elige: se devuelve `None`. Un árbitro puesto en el
        partido equivocado es peor que ningún árbitro, porque el primero mueve
        la probabilidad y no deja rastro de que se movió mal.
      · **umbral bajo pero sobre parecido de PALABRAS** (ver `_similitud`). El
        umbral de 0,82 sobre cadenas dejaba fuera 12 de 48 fixtures que eran
        emparejados correctos escritos de otra forma. Con 0,62 sobre conjuntos
        de palabras entran esos doce y el único candidato falso que había
        —«PAOK vs Levadiakos» contra «Palermo vs Juve Stabia», 0,38— sigue
        fuera por bastante.
    """
    try:
        puntuados = []
        for m in indice:
            p = min(_similitud(fx_home, m['home']),
                    _similitud(fx_away, m['away']))
            if p >= umbral:
                puntuados.append((p, m))
        if not puntuados:
            return None
        puntuados.sort(key=lambda t: -t[0])
        if len(puntuados) > 1 and (puntuados[0][0] - puntuados[1][0]) < MARGEN_EMPAREJADO:
            logger.info('[arbitro] «%s vs %s»: %.3f contra %.3f del siguiente '
                        '— se descarta por ambiguo', fx_home, fx_away,
                        puntuados[0][0], puntuados[1][0])
            return None
        return puntuados[0][1]
    except Exception as e:
        logger.debug('[arbitro] emparejado: %s', e)
        return None


def construir(fixtures: List[Dict], max_hilos: int = 6) -> Dict[str, Dict]:
    """
    El árbitro de cada fixture de la lista, listo para guardar en disco.

    `fixtures` son dicts con al menos 'fecha', 'home' y 'away' — el formato que
    devuelve `fixtures_espn`. Se piden los índices de los días implicados (una
    petición por día) y luego el detalle SÓLO de los partidos emparejados, así
    que el coste es «número de partidos nuestros», no los 405 del día.
    """
    from concurrent.futures import ThreadPoolExecutor

    fechas = sorted({str(f.get('fecha'))[:10] for f in fixtures
                     if f.get('fecha')})
    indices: Dict[str, List[Dict]] = {}
    for fecha in fechas:
        indices[fecha] = indice_dia(fecha)
        logger.info('[arbitro] índice de %s: %d partidos en FotMob',
                    fecha, len(indices[fecha]))

    pendientes = []
    for f in fixtures:
        fecha = str(f.get('fecha'))[:10]
        home, away = f.get('home'), f.get('away')
        if not (fecha and home and away):
            continue
        m = _empareja(home, away, indices.get(fecha) or [])
        if m:
            pendientes.append((clave_partido(fecha, home, away), m, f))

    salida: Dict[str, Dict] = {}

    def _uno(par):
        llave, m, f = par
        p = perfil_de_partido(m['match_id'])
        if not p:
            return None
        p['partido'] = '%s vs %s' % (f.get('home'), f.get('away'))
        p['fecha'] = str(f.get('fecha'))[:10]
        p['clave_liga'] = f.get('clave_liga')
        p['factor'] = factor(p)
        return (llave, p)

    with ThreadPoolExecutor(max_workers=max_hilos) as ex:
        for r in ex.map(_uno, pendientes):
            if r:
                salida[r[0]] = r[1]
    logger.info('[arbitro] %d fixtures · %d emparejados · %d con árbitro',
                len(fixtures), len(pendientes), len(salida))
    return salida


# ---------------------------------------------------------------------------
# disco
# ---------------------------------------------------------------------------
_CACHE_DISCO: Optional[Dict] = None


def guardar(datos: Dict[str, Dict], ruta: str = FICHERO) -> None:
    envoltorio = {'generado': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                  'k_encogimiento': K_ENCOGIMIENTO,
                  'arbitros': datos}
    try:
        import io_atomico
        io_atomico.escribir_json(ruta, envoltorio)
    except Exception:
        with open(ruta, 'w', encoding='utf-8') as f:
            json.dump(envoltorio, f, ensure_ascii=False, indent=1)


def cargar(ruta: str = FICHERO, recargar: bool = False) -> Dict:
    """
    Lo que dejó el precálculo del bot. `{}` si no está, sin protestar.

    Que falte es normal y no es un error: significa que el bot no ha corrido
    todavía hoy, y entonces las tarjetas salen sin ajuste de árbitro. La
    tarjeta lo dice; no se inventa un factor.
    """
    global _CACHE_DISCO
    if _CACHE_DISCO is not None and not recargar:
        return _CACHE_DISCO
    datos: Dict = {}
    try:
        if os.path.exists(ruta):
            with open(ruta, encoding='utf-8') as f:
                datos = json.load(f) or {}
    except Exception as e:
        logger.debug('[arbitro] no se pudo leer %s: %s', ruta, e)
        datos = {}
    _CACHE_DISCO = datos
    return datos


def buscar(fecha: str, home: str, away: str) -> Optional[Dict]:
    """
    El perfil del árbitro de este partido, si el precálculo lo tiene.

    LA LLAVE EXACTA NO BASTA, Y SABERLO COSTÓ UNA PASADA. El precálculo guarda
    los nombres tal y como los publica ESPN («Brighton & Hove Albion»), y la
    tarjeta pregunta con los nombres del CATÁLOGO, que son los del histórico y
    pasan por `name_mapper` («Brighton»). Son el mismo partido con dos rótulos,
    así que una búsqueda por igualdad de cadena falla en silencio: no revienta,
    simplemente devuelve `None` y todas las tarjetas salen sin árbitro sin que
    nada lo denuncie.

    Así que primero se prueba la llave exacta —que es la vía rápida y la que
    acierta cuando los dos rótulos coinciden— y si no está se busca por
    parecido ENTRE LOS PARTIDOS DE ESE MISMO DÍA, que son unas decenas. Se
    reutiliza `_empareja`, o sea la misma regla de dos equipos con margen sobre
    el segundo: aquí también un árbitro mal asignado sería peor que ninguno.
    """
    d = (cargar().get('arbitros') or {})
    if not d:
        return None
    exacta = d.get(clave_partido(fecha, home, away))
    if exacta is not None:
        return exacta
    dia = str(fecha)[:10]
    candidatos = []
    for llave, p in d.items():
        if not llave.startswith(dia + '|'):
            continue
        partido = str(p.get('partido') or '')
        for sep in (' vs ', ' vs. ', ' @ ', ' - '):
            if sep in partido:
                ph, pa = partido.split(sep, 1)
                candidatos.append({'home': ph.strip(), 'away': pa.strip(),
                                   '_perfil': p})
                break
    m = _empareja(home, away, candidatos)
    return m['_perfil'] if m else None


def factor_de(fecha: str, home: str, away: str) -> float:
    """Atajo: el factor que hay que aplicar, o 1,0 si no se sabe."""
    p = buscar(fecha, home, away)
    if not p:
        return 1.0
    f = p.get('factor')
    try:
        f = float(f)
    except (TypeError, ValueError):
        return factor(p)
    return f if FACTOR_MIN <= f <= FACTOR_MAX else 1.0


# ---------------------------------------------------------------------------
def main() -> int:
    """Precálculo diario. Lo llama el bot, igual que `predicciones_dia`."""
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--dias', type=int, default=2,
                    help='hoy y cuántos más (por defecto hoy y mañana)')
    ap.add_argument('--salida', default=FICHERO)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO,
                        format='%(levelname)s:%(name)s:%(message)s')

    import fixtures_espn
    from config import LEAGUES
    import rendimiento_equipos as rq

    # Sólo las competiciones que publican tarjetas OBSERVADAS: en las demás el
    # ajuste no tendría a qué aplicarse, y pedir su árbitro sería gastar red
    # para nada.
    claves = [c for c, cfg in LEAGUES.items()
              if cfg.get('disponible') and c in fixtures_espn.ESPN_CODIGOS
              and rq.stats_disponibles(c).get('tarjetas')]
    print('competiciones con tarjetas observadas y fixtures: %d' % len(claves))
    por_liga = fixtures_espn.fixtures_multi(claves, dias=args.dias)
    fixtures = []
    for clave, fx in (por_liga or {}).items():
        for f in (fx or []):
            f = dict(f)
            f['clave_liga'] = clave
            fixtures.append(f)
    print('fixtures a resolver: %d' % len(fixtures))
    datos = construir(fixtures)
    guardar(datos, args.salida)
    con = sum(1 for p in datos.values() if p.get('factor') != 1.0)
    print('árbitros resueltos: %d (con ajuste distinto de 1: %d)'
          % (len(datos), con))
    for llave, p in list(datos.items())[:10]:
        print('   %-46s %-22s %.2f/%.2f n=%s  factor %.3f'
              % (p.get('partido'), p.get('nombre'),
                 p.get('amarillas_por_partido') or 0,
                 p.get('media_competicion') or 0,
                 p.get('partidos'), p.get('factor') or 1.0))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
