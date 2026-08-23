#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v163 — QUIÉN REMATA: probabilidad por jugador, con la alineación cuando la hay.

Qué contesta
------------
Para cada futbolista de un partido que aún no se ha jugado: cuántos remates se
le esperan y con qué probabilidad tira al menos uno, y al menos uno a puerta.

Es el mercado de jugador que va con la Parte 1 (`rendimiento_equipos`, sección
v163): allí se calcula lo que va a tirar el EQUIPO, y aquí se reparte entre
sus jugadores.


LO QUE SE MIDIÓ ANTES DE ESCRIBIR ESTO
======================================

1. LA ALINEACIÓN NO ESTÁ EN ESPN, Y ESO CIERRA UNA VÍA ENTERA
-------------------------------------------------------------
El `summary` de ESPN trae el once inicial en `rosters[].roster[].starter`.
Medido sobre 104 partidos de 12 competiciones (`_v163_sondeo_alineacion.py`):

    partidos TERMINADOS con once .....  50 de 50   (100 %)
    partidos POR JUGAR  con once .....   0 de 54   (  0 %)

incluido uno a 4,4 horas del saque. Es exactamente la misma firma que tenía el
árbitro en la v160: el dato existe, pero aparece cuando ya no sirve.

Y el `goleadores_cache.json` que precalcula el workflow **no contiene ninguna
alineación**, aunque sea fácil creerlo: lo que guarda es el ROSTER DE
TEMPORADA de ESPN —la plantilla entera con sus totales—, que no depende del
partido. De ahí no sale un once inicial ni lo saldrá.

2. FOTMOB SÍ PUBLICA UN ONCE PROBABLE
--------------------------------------
Misma fuente que resolvió el árbitro. Medido sobre 50 partidos por jugar
(`_v163_sondeo_fotmob_lineup.py`), `content.lineup` trae:

    con once publicado ..............  27 de 50   (54 %)
    tipo `predicted` ................  21   ← once probable de verdad
    tipo `lastStarting11` ...........   6   ← el once del último partido
    tipo `unavailable` o sin bloque .  23

Aparece con 24 horas y más de antelación, y en las competiciones grandes casi
siempre. Los tres casos se distinguen en pantalla: no es lo mismo un once
probable que el del partido anterior, y decir que sí lo es sería inventar.

    (Aviso a quien toque el lector: la primera versión de este sondeo devolvía
    cero SIEMPRE porque buscaba el bloque en la ruta equivocada, y parecía que
    FotMob no publicaba nada. Lo cazó `_v163_verificar_lector_lineup.py`
    pasándole el mismo lector a partidos ya jugados, donde el once tiene que
    estar. Un sondeo que no encuentra nada y un lector roto se parecen
    demasiado: si se cambia la ruta, hay que volver a pasar ese control.)

3. LA MEDIA DEL PROPIO JUGADOR NO BASTA, Y ENCOGERLA GANA
----------------------------------------------------------
Medido sobre 6.688 titulares-partido de Premier, LaLiga y Liga MX bajados de
ESPN (`_v163_remates_jugador.py`), prediciendo P(≥1 remate) con información
previa:

    estimador                        marginal    Brier      ECE     corr
      encogido K=6 ................   0,02030  0,18746  0,02870   0,537  <--
      su media de las últimas 10 ..   0,00850  0,19268  0,05606   0,521
      la media de su posición .....   0,02760  0,19903  0,03571   0,471

    P(≥1 a puerta)
      encogido K=12 ...............   0,01163  0,13992  0,02449   0,420  <--
      su media de las últimas 10 ..   0,00980  0,14622  0,05623   0,392
      la media de su posición .....   0,01362  0,14438  0,02347   0,384

La media de un jugador sale de 4-10 apariciones. Con λ≈0,78 eso son ±0,28 de
desviación típica: un tercio de ruido puro. Encogerla hacia la media de su
posición baja el ECE a la mitad y encima SUBE la correlación, que es el reparto
que casi nunca se da. K=6 en remates totales y K=12 a puerta: el evento raro
necesita encoger más, que es justo lo que dice la teoría.

La curva de K es plana entre 4 y 12, así que los valores exactos no son
críticos; lo que importa es que hay encogimiento.

4. POISSON, NO BINOMIAL NEGATIVA — AL REVÉS QUE EN EL EQUIPO
-------------------------------------------------------------
En el modelo por equipo la binomial negativa gana de calle (la dispersión por
equipo es 2,09). Por jugador pierde en los dos objetivos: 0,18746 contra
0,18969 de Brier. No es una contradicción. La dispersión que se mide juntando a
todos los jugadores incluye la diferencia ENTRE ellos —un delantero no es un
lateral—, y esa parte ya está dentro de la λ de cada uno. Volver a meterla en
la distribución la cuenta dos veces y engorda las colas sin motivo.

5. EL PREVIO POSICIONAL VA EN CUOTA, PARA QUE VALGA EN LAS 62 LIGAS
--------------------------------------------------------------------
Medir «la media de la posición» en cada competición exigiría la estadística por
jugador de esa competición entera: cientos de peticiones por liga. En cuota del
total del equipo el número es adimensional y se transporta. Medido en las tres
competiciones (`_v163_cuota_posicional.py`), la dispersión relativa entre ellas
es 0,077 en remates totales, y calibra igual que el techo:

    previo                     marginal    Brier      ECE     corr
      media de la liga .....    0,02030  0,18746  0,02870   0,537
      cuota × λ del equipo .    0,01892  0,18798  0,03172   0,533

Así que el previo es `cuota_de_su_posición × lo que se espera que tire su
equipo en ESTE partido`, con lo que el modelo por jugador queda enganchado al
de equipo: si el rival concede mucho, sube el equipo y suben sus jugadores.

6. LO QUE NO CALIBRA: SABER QUIÉN JUEGA
----------------------------------------
Cuando no hay alineación hay que estimar la titularidad con la frecuencia con
la que ha sido titular. Medido igual que lo demás:

    eng.1  n=6.928  marginal 0,0027  Brier 0,16395  ECE 0,05689
    esp.1  n=7.740  marginal 0,0056  Brier 0,17912  ECE 0,07272
    mex.1  n=7.316  marginal 0,0035  Brier 0,17264  ECE 0,06123

ECE de 0,057 a 0,073, POR ENCIMA del umbral de 0,05 del proyecto. O sea: la
parte floja de esta sección no es cuánto remata un jugador, es si va a jugar.
Por eso, sin alineación publicada, la sección se marca como tal y sus números
llevan el aviso fuerte.


POR QUÉ ESTO NUNCA SALE EN VERDE
================================
Verde en esta aplicación significa «canal con percentil 5 de bootstrap positivo
medido en tramo de juicio». Aquí no hay ni eso ni histórico de líneas de
jugador con el que empezar a medirlo. Lo que hay es una probabilidad calibrada
—que no es lo mismo que una ventaja de precio— sobre un evento de baja
frecuencia. Se enseña en gris/ámbar y como información, igual que córners y
tarjetas, y con más motivo.
"""
import json
import logging
import os
from typing import Dict, List, Optional

logger = logging.getLogger('remates_jugador')

AJUSTE = 'calibracion_remates_jugador.json'
_CAL: Optional[Dict] = None

# Los dos mercados, con el encogimiento que ganó cada uno.
OBJETIVOS = ('tot', 'on')
K_POR_DEFECTO = {'tot': 6.0, 'on': 12.0}

# Cuotas de respaldo por si el fichero de ajuste no está: son las medidas en
# `_v163_cuota_posicional.py` y valen para que la sección degrade a algo
# razonable, no para sustituir al ajuste.
CUOTAS_GRUESAS_RESPALDO = {
    'tot': {'G': 0.0002, 'D': 0.0426, 'M': 0.0927, 'F': 0.1577},
    'on': {'G': 0.0001, 'D': 0.0333, 'M': 0.0905, 'F': 0.1835},
}

# La ventana con la que se lee la forma del jugador, igual que en el equipo.
VENTANA = 10

# DOS UMBRALES, PORQUE HAY DOS COSAS DISTINTAS QUE DECIDIR.
#
# `MIN_APARICIONES` es el suelo para salir en la tabla. Por debajo de dos
# apariciones el encogimiento devuelve la fila casi entera al previo
# posicional, o sea la media de su puesto con el nombre de alguien encima.
#
# `MIN_APARICIONES_FIABLE` es el suelo para que la fila cuente como medida.
# Toda la validación de la cabecera se hizo con cuatro apariciones previas o
# más, y por tramos se ve que por debajo empeora — en remates a puerta el
# error marginal pasa de 0,009 con siete o más a 0,043 con cuatro a seis:
#
#     apariciones 4-6   n=  813  marginal 0,02235 / 0,04298  (tot / on)
#     apariciones 7+    n=5.875  marginal 0,02009 / 0,00896
#
# Con menos de cuatro no hay ni medición: el tramo no llega a la muestra
# mínima ni siquiera juntando tres competiciones, y las probabilidades salen
# tan pegadas unas a otras que la calibración por deciles no se puede calcular.
# Así que esas filas salen marcadas `muestra_corta` y la interfaz lo dice, en
# vez de extrapolar hasta donde no se ha mirado. A principio de temporada son
# casi todas, que es justo cuando más se notaría el disimulo.
MIN_APARICIONES = 2
MIN_APARICIONES_FIABLE = 4

# ESPN da la posición fina en el `summary` y la gruesa en el roster de
# temporada. Se traduce para poder usar la tabla gruesa con las dos.
A_GRUESA = {
    'G': 'G',
    'CD': 'D', 'CD-L': 'D', 'CD-R': 'D', 'LB': 'D', 'RB': 'D', 'SW': 'D',
    'LWB': 'D', 'RWB': 'D', 'D': 'D',
    'DM': 'M', 'CM': 'M', 'CM-L': 'M', 'CM-R': 'M', 'LM': 'M', 'RM': 'M',
    'M': 'M', 'AM': 'M', 'AM-L': 'M', 'AM-R': 'M',
    'F': 'F', 'CF': 'F', 'CF-L': 'F', 'CF-R': 'F', 'LF': 'F', 'RF': 'F',
    'RCF': 'F', 'LCF': 'F', 'SS': 'F',
}


# ---------------------------------------------------------------------------
# el ajuste medido
# ---------------------------------------------------------------------------
def calibracion() -> Dict:
    global _CAL
    if _CAL is None:
        try:
            with open(AJUSTE, encoding='utf-8') as f:
                _CAL = json.load(f) or {}
        except Exception as e:
            logger.debug('[remates_jugador] sin %s: %s', AJUSTE, e)
            _CAL = {}
    return _CAL


def _k(objetivo: str) -> float:
    try:
        return float((calibracion().get('K') or {}).get(
            objetivo, K_POR_DEFECTO[objetivo]))
    except (TypeError, ValueError, KeyError):
        return K_POR_DEFECTO[objetivo]


def cuota_posicion(posicion: str, objetivo: str) -> Optional[float]:
    """
    Qué parte de los remates de su equipo le corresponde a esa posición.

    Se prueba primero la tabla FINA (la del `summary`: «AM-L», «CD-R») y luego
    la GRUESA (la del roster de temporada: «M», «D»). Una posición que no está
    en ninguna devuelve `None` y el jugador se queda fuera en vez de recibir
    una cuota inventada.
    """
    if not posicion:
        return None
    cal = calibracion()
    fina = (cal.get('cuotas') or {}).get(objetivo) or {}
    if posicion in fina:
        return float(fina[posicion])
    gruesa = ((cal.get('cuotas_gruesas') or {}).get(objetivo)
              or CUOTAS_GRUESAS_RESPALDO.get(objetivo) or {})
    g = A_GRUESA.get(posicion, posicion)
    if g in gruesa:
        return float(gruesa[g])
    return None


def lambda_jugador(media_propia: Optional[float], apariciones: float,
                   posicion: str, lambda_equipo: Optional[float],
                   objetivo: str = 'tot') -> Optional[float]:
    """
    Los remates esperados de un jugador, encogidos hacia su posición.

        λ = (n · media_propia + K · cuota_posición · λ_equipo) / (n + K)

    con `n` sus apariciones (tope: la ventana de 10) y K medido: 6 en remates
    totales, 12 a puerta. Ver el punto 3 de la cabecera para el porqué y para
    lo que se gana.

    Devuelve `None` cuando no hay ni previo posicional ni λ del equipo con los
    que anclar: sin eso lo único que quedaría es la media cruda de un puñado de
    partidos, que es justo lo que la medición descartó.
    """
    cuota = cuota_posicion(posicion, objetivo)
    if cuota is None or lambda_equipo is None:
        return None
    try:
        previo = float(cuota) * float(lambda_equipo)
        n = max(0.0, min(float(apariciones or 0.0), float(VENTANA)))
    except (TypeError, ValueError):
        return None
    if media_propia is None:
        return round(previo, 3)
    try:
        propia = float(media_propia)
    except (TypeError, ValueError):
        return round(previo, 3)
    k = _k(objetivo)
    return round((n * propia + k * previo) / (n + k), 3)


def p_al_menos_uno(lam: Optional[float]) -> Optional[float]:
    """
    P(≥1) con Poisson, que es la que ganó la medición por jugador.

    Poisson y no binomial negativa a propósito: ver el punto 4 de la cabecera.
    La sobredispersión que se mide juntando jugadores es en buena parte la
    diferencia entre ellos, y ésa ya está dentro de cada λ.
    """
    if lam is None:
        return None
    try:
        import math
        x = float(lam)
    except (TypeError, ValueError):
        return None
    if x <= 0:
        return 0.0
    return float(1.0 - math.exp(-x))


# v164 — LO QUE REMATA UN SUPLENTE FRENTE A UN TITULAR, MEDIDO.
#
# Sobre 24.059 apariciones de Premier, LaLiga y Liga MX
# (`_v163_cache_jugadores/`):
#
#     remates totales   titular 0,9888 · suplente 0,4741   razón 0,4795
#     a puerta          titular 0,3334 · suplente 0,1631   razón 0,4890
#
# Un suplente remata menos de la mitad que un titular, y no es una sorpresa:
# entra a falta de veinte minutos.
RATIO_SUPLENTE = {'tot': 0.4795, 'on': 0.4890}
# Y el factor de rescate cuando no se sabe cuántas de sus apariciones fueron
# titularidades: la media de titular dividida por la media de aparición.
FACTOR_APARICION = {'tot': 1.1754, 'on': 1.1717}


def media_por_titularidad(total: Optional[float], apariciones: Optional[float],
                          titularidades: Optional[float] = None,
                          objetivo: str = 'tot') -> Optional[float]:
    """
    Los remates que se le esperan CUANDO ES TITULAR, no cuando aparece.

    EL DESAJUSTE QUE ARREGLA, Y QUE ESTUVO EN PRODUCCIÓN DESDE LA v163. El
    modelo por jugador se validó sobre TITULARES y con su historia como
    titulares (§13.7, ECE 0,029). Producción, en cambio, dividía los remates
    entre las APARICIONES —que incluyen entrar diez minutos desde el
    banquillo—, así que la lambda que se enseñaba era una magnitud distinta de
    la que se había medido, y más baja.

    No es un detalle: el 29 % de las apariciones son suplencias, y de suplente
    se remata el 48 % de lo que se remata de titular.

    Con las titularidades conocidas se despeja exacto. Si `total` son los
    remates de T titularidades y S suplencias, y un suplente remata `r` veces
    lo que un titular:

        total = m_tit · T + m_tit · r · S      ->      m_tit = total / (T + r·S)

    Sin ellas se aplica el factor global medido, que es peor pero honesto: la
    media de titular partido por la media de aparición.
    """
    try:
        tot = float(total)
        ap = float(apariciones or 0)
    except (TypeError, ValueError):
        return None
    if ap <= 0:
        return None
    r = RATIO_SUPLENTE.get(objetivo, RATIO_SUPLENTE['tot'])
    if titularidades is None:
        return (tot / ap) * FACTOR_APARICION.get(
            objetivo, FACTOR_APARICION['tot'])
    try:
        t = float(titularidades)
    except (TypeError, ValueError):
        return (tot / ap) * FACTOR_APARICION.get(
            objetivo, FACTOR_APARICION['tot'])
    t = max(0.0, min(t, ap))
    den = t + r * (ap - t)
    if den <= 0:
        # nunca fue titular: su media como titular no se puede despejar de aquí
        # sin dividir por cero. Se devuelve la de aparición escalada, que es lo
        # mejor disponible, y el encogimiento hacia su posición hará el resto.
        return (tot / ap) * FACTOR_APARICION.get(
            objetivo, FACTOR_APARICION['tot'])
    return tot / den


def buscar_linea(lineas: Optional[Dict], jugador: str) -> Optional[Dict]:
    """La ficha de líneas de un jugador, o `None` si la casa no lo cotiza."""
    if not lineas or not jugador:
        return None
    try:
        import lineas_jugador
        return lineas_jugador.buscar(lineas, jugador)
    except Exception as e:
        logger.debug('[remates_jugador] línea de %s: %s', jugador, e)
        return None


def p_mas_de(lam: Optional[float], linea: Optional[float]) -> Optional[float]:
    """
    P(X > linea) con Poisson, para la línea que cotiza la casa.

    Las líneas de jugador son siempre de medio punto —«Más de 1,5 remates»— así
    que esto es P(X >= 2) y no hay empate posible. Se calcula con la misma
    Poisson que ganó la medición por jugador (§13.7): la binomial negativa
    perdía porque la sobredispersión que se mide juntando jugadores es en buena
    parte la diferencia ENTRE ellos, y ésa ya está dentro de cada lambda.

    `None` si falta cualquiera de los dos. Eso NO es un cero, y quien llama
    tiene que enseñarlo como «línea no disponible»: decir 0 % de un mercado que
    la casa no cotiza sería inventarse una afirmación.
    """
    if lam is None or linea is None:
        return None
    try:
        import math
        x = float(lam)
        L = float(linea)
    except (TypeError, ValueError):
        return None
    if x <= 0:
        return 0.0
    # P(X > L) = 1 - P(X <= floor(L)); con L de medio punto, floor(L) = L - 0,5
    k = int(math.floor(L))
    if k < 0:
        return 1.0
    acum, termino = 0.0, math.exp(-x)
    for i in range(0, k + 1):
        if i:
            termino *= x / i
        acum += termino
    return float(max(0.0, min(1.0, 1.0 - acum)))


# ---------------------------------------------------------------------------
# la alineación probable (FotMob)
# ---------------------------------------------------------------------------
_ALINEACIONES: Dict[str, Optional[Dict]] = {}

# Cómo se llama en pantalla cada tipo que publica FotMob. El texto importa: un
# once probable y el del partido anterior no valen lo mismo.
TIPOS = {
    'predicted': ('probable', 'Alineación probable según FotMob'),
    'lastStarting11': ('último once',
                       'No hay alineación todavía: es el once del último '
                       'partido'),
    'confirmed': ('confirmada', 'Alineación confirmada'),
    'standard': ('confirmada', 'Alineación confirmada'),
}


FICHERO_ALINEACIONES = 'alineaciones_dia.json'
_DISCO: Optional[Dict] = None


def cargar(ruta: str = FICHERO_ALINEACIONES, recargar: bool = False) -> Dict:
    """
    Lo que dejó el precálculo diario. `{}` si no está, sin protestar.

    Que falte es normal y no es un error: significa que el bot no ha corrido
    todavía, y entonces la sección de jugadores sale sin alineación y lo dice.
    Es el mismo contrato que `arbitro_partido.cargar` con `arbitros_dia.json`.
    """
    global _DISCO
    if _DISCO is not None and not recargar:
        return _DISCO
    datos: Dict = {}
    try:
        if os.path.exists(ruta):
            with open(ruta, encoding='utf-8') as f:
                datos = json.load(f) or {}
    except Exception as e:
        logger.debug('[remates_jugador] no se pudo leer %s: %s', ruta, e)
    _DISCO = datos
    return datos


def alineacion(fecha: str, home: str, away: str,
               permitir_red: bool = False) -> Optional[Dict]:
    """
    El once probable de los dos equipos, si FotMob lo ha publicado.

    POR DEFECTO NO PIDE NADA A LA RED, Y ESO NO ES UNA OPTIMIZACIÓN: es un
    requisito. La tarjeta de «Apuestas del Día» se pinta una vez por partido y
    hay sesenta; a un `matchDetails` de FotMob por partido —1,7 segundos cada
    uno— la pantalla tardaría dos minutos más de lo que ya tarda. Así que lee
    del precálculo que deja el bot en `alineaciones_dia.json`, exactamente como
    hace `arbitro_partido` con `arbitros_dia.json` y por el mismo motivo.

    `permitir_red=True` sí pregunta a FotMob. Es para la FICHA, que se abre de
    una en una, y para el propio precálculo.

    Devuelve `{'home': [...], 'away': [...], 'tipo': 'predicted', ...}` o
    `None`. `None` no significa que el partido no exista: significa que todavía
    no hay alineación, que es el 46 % de los casos medidos. Quien llame debe
    decirlo en pantalla, no rellenarlo.
    """
    ck = '%s|%s|%s|%s' % (fecha, home, away, permitir_red)
    if ck in _ALINEACIONES:
        return _ALINEACIONES[ck]
    salida = _de_disco(fecha, home, away)
    if salida is None and permitir_red:
        try:
            mid = _buscar_match_id(fecha, home, away)
            if mid:
                salida = _lineup(mid)
        except Exception as e:
            logger.debug('[remates_jugador] alineación de %s-%s: %s',
                         home, away, e)
    _ALINEACIONES[ck] = salida
    return salida


def _de_disco(fecha: str, home: str, away: str) -> Optional[Dict]:
    """
    La alineación precalculada de este partido.

    Se busca igual que el árbitro y por el mismo motivo: el precálculo guarda
    los nombres tal y como los escribe FotMob y quien pregunta usa los del
    catálogo del proyecto, así que la igualdad de cadena falla en silencio.
    Primero la llave exacta, y si no está, por parecido ENTRE LOS PARTIDOS DE
    ESE DÍA con `arbitro_partido._empareja`, que exige que casen los DOS
    equipos y con margen sobre el segundo candidato. Una alineación puesta en
    el partido equivocado sería peor que ninguna.
    """
    d = (cargar().get('alineaciones') or {})
    if not d:
        return None
    try:
        import arbitro_partido as ap
    except Exception:
        return None
    exacta = d.get(ap.clave_partido(fecha, home, away))
    if exacta is not None:
        return exacta
    dia = str(fecha)[:10]
    candidatos = []
    for llave, p in d.items():
        if not llave.startswith(dia + '|'):
            continue
        candidatos.append({'home': p.get('equipo_home') or '',
                           'away': p.get('equipo_away') or '', '_al': p})
    m = ap._empareja(home, away, candidatos)
    return m['_al'] if m else None


def _buscar_match_id(fecha: str, home: str, away: str) -> Optional[str]:
    """El partido en el índice del día de FotMob, emparejando por nombre."""
    import arbitro_partido as ap
    idx = ap.indice_dia(fecha)
    if not idx:
        return None
    return (lambda m: m['match_id'] if m else None)(
        ap._empareja(home, away, idx))


def _lineup(match_id: str) -> Optional[Dict]:
    """
    El bloque de alineación de FotMob, leído por la ruta COMPROBADA.

        content.lineup = {matchId, lineupType, source, homeTeam, awayTeam}
        content.lineup.homeTeam.starters = [{id, name, positionId, ...}]

    Si FotMob mueve el bloque, esto devuelve `None` y la sección desaparece en
    vez de enseñar medias tablas — pero antes de cambiar la ruta hay que volver
    a pasar `_v163_verificar_lector_lineup.py`, que es lo que distingue «no hay
    alineación» de «el lector está roto».
    """
    import arbitro_partido as ap
    d = ap._get('%s/matchDetails?matchId=%s' % (ap.BASE, match_id))
    if not d:
        return None
    lu = ((d.get('content') or {}).get('lineup')) or {}
    if not isinstance(lu, dict):
        return None
    tipo = lu.get('lineupType')
    if tipo in ('unavailable', None):
        return None
    salida = {'tipo': tipo, 'match_id': str(match_id),
              'etiqueta': TIPOS.get(tipo, ('probable', 'Alineación probable'))[0],
              'aviso': TIPOS.get(tipo, ('probable', 'Alineación probable'))[1]}
    for lado, clave in (('homeTeam', 'home'), ('awayTeam', 'away')):
        eq = lu.get(lado) or {}
        nombres = [str(j.get('name')) for j in (eq.get('starters') or [])
                   if j.get('name')]
        salida[clave] = nombres
        salida[clave + '_formacion'] = eq.get('formation')
        # el nombre del equipo según FotMob: es lo que necesita `_de_disco`
        # para volver a encontrar el partido cuando se lee del precálculo
        salida['equipo_' + clave] = eq.get('name')
    if len(salida.get('home') or []) < 11 or len(salida.get('away') or []) < 11:
        return None
    return salida


# ---------------------------------------------------------------------------
# los jugadores de un equipo
# ---------------------------------------------------------------------------
def _de_roster(clave_liga: str, equipo: str,
               solo_cache: bool = True) -> List[Dict]:
    """
    La plantilla con sus totales de temporada, del fichero YA PRECALCULADO.

    `solo_cache=True` (lo que usa la tarjeta) LEE EL FICHERO Y NADA MÁS. No es
    una optimización opcional: `goleadores.plantilla_equipo` y
    `goleadores.equipos_liga` salen a ESPN cuando su entrada no está cacheada,
    y en la tarjeta eso son ciento veinte equipos pidiendo a la vez. Medido: la
    pantalla de «Apuestas del Día» pasó de 85-239 s a **383 s** la primera vez
    que este bloque se enchufó llamando a `plantilla_equipo` sin más. Con la
    lectura directa vuelve a su rango.

    Lo que no esté en la caché simplemente no sale, y eso es correcto: el
    workflow `precalcular_rosters.yml` la rellena todos los días, y un equipo
    que falte hoy aparece mañana. Un hueco se ve; una pantalla que tarda seis
    minutos, también, pero tarde.

    A cambio son totales de TEMPORADA, no forma reciente. Cada fila sale
    marcada con `base: 'temporada'` para que la interfaz pueda decirlo.
    """
    try:
        import goleadores
        if solo_cache:
            plantilla = _roster_cacheado(clave_liga, equipo)
        else:
            tid = goleadores._buscar_team_id(clave_liga, equipo)
            plantilla = (goleadores.plantilla_equipo(clave_liga, tid) or []
                         if tid else [])
    except Exception as e:
        logger.debug('[remates_jugador] roster de %s: %s', equipo, e)
        return []
    if not plantilla:
        return []
    salida = []
    for j in plantilla:
        apar = float(j.get('apariciones') or 0)
        if apar < MIN_APARICIONES:
            continue
        # v164 — LA MEDIA ES POR TITULARIDAD, NO POR APARICIÓN.
        #
        # `subIns` dice cuántas de sus apariciones fueron desde el banquillo,
        # así que las titularidades se despejan y con ellas la media que el
        # modelo tiene medida. En los rosters cacheados antes de la v164 el
        # campo no está: entonces se aplica el factor global, que es peor pero
        # sigue siendo la magnitud correcta.
        subs = j.get('suplencias')
        tit = None if subs is None else max(0.0, apar - float(subs))
        fila = {'jugador': j.get('nombre'), 'posicion': j.get('posicion') or '',
                'apariciones': apar, 'base': 'temporada',
                'titularidades': tit,
                'media_tot': media_por_titularidad(j.get('remates'), apar,
                                                   tit, 'tot')}
        # `al_arco` sólo está en los rosters refrescados desde la v163. En los
        # cacheados antes vale `None` y el mercado «a puerta» de este jugador
        # simplemente no se pinta, en vez de salir a cero.
        if j.get('al_arco') is not None:
            fila['media_on'] = media_por_titularidad(j['al_arco'], apar, tit,
                                                     'on')
        salida.append(fila)
    return salida


def _roster_cacheado(clave_liga: str, equipo: str) -> List[Dict]:
    """
    El roster de un equipo leyendo `goleadores_cache.json` y NADA MÁS.

    Se salta a propósito `goleadores.equipos_liga` y `plantilla_equipo`, que
    son los que saben pedirle a ESPN lo que falta. Aquí no se pide nada: si la
    entrada no está, se devuelve vacío.

    El nombre del equipo se traduce contra el catálogo CACHEADO con el mismo
    `name_mapper` del resto del proyecto, porque el histórico escribe «Man
    City» y ESPN «Manchester City» — los alias de la v163 son justo para esto.
    """
    try:
        import goleadores
        cache = goleadores._cache_cargar()
    except Exception:
        return []
    equipos = ((cache.get('teams:%s' % clave_liga) or {}).get('data')) or []
    if not equipos:
        return []
    por_nombre = {str(e.get('nombre')): str(e.get('id')) for e in equipos
                  if e.get('nombre') and e.get('id')}
    tid = por_nombre.get(equipo)
    if tid is None:
        try:
            import name_mapper
            m = name_mapper.mapear(equipo, list(por_nombre),
                                   contexto='remates_jugador/roster')
        except Exception:
            m = None
        tid = por_nombre.get(m) if m else None
    if tid is None:
        return []
    return ((cache.get('roster:%s:%s' % (clave_liga, tid)) or {}).get('data')
            or [])


def _de_partidos(clave_liga: str, equipo: str) -> List[Dict]:
    """
    Los remates por jugador de los ÚLTIMOS PARTIDOS, pedidos a ESPN en vivo.

    Mejor dato que el roster —es forma reciente y trae los remates a puerta y
    la frecuencia de titularidad— pero cuesta una decena de peticiones por
    equipo, así que sólo se usa en la ficha, que se abre de una en una.

    `remates_jugadores` cachea seis horas en disco y devuelve vacío cuando ESPN
    no publica la competición o cuando nos bloquea con un 403 (pasa en
    Streamlit Cloud). En los dos casos quien llama cae al roster.
    """
    try:
        import remates_jugadores as rj
        espn = rj.resolver_equipo(clave_liga, equipo)
        if not espn:
            return []
        d = rj.remates_equipo(clave_liga, espn)
    except Exception as e:
        logger.debug('[remates_jugador] remates de %s: %s', equipo, e)
        return []
    if d is None or getattr(d, 'empty', True):
        return []
    salida = []
    for _, r in d.iterrows():
        apar = float(r.get('partidos') or 0)
        if apar < MIN_APARICIONES:
            continue
        muestra = float(r.get('n_partidos_muestra') or 0)
        # v164 — igual que en el roster: la media que el modelo tiene medida
        # es la del TITULAR, y `remates_pp` viene dividido entre apariciones.
        # Aquí las titularidades sí llegan siempre, así que se despeja exacto.
        tit = float(r.get('titularidades') or 0)
        salida.append({
            'jugador': r.get('jugador'), 'posicion': r.get('posicion') or '',
            'apariciones': apar, 'base': 'últimos partidos',
            'media_tot': media_por_titularidad(r.get('remates'), apar, tit,
                                               'tot'),
            'media_on': media_por_titularidad(r.get('al_arco'), apar, tit,
                                              'on'),
            'titularidades': tit,
            'p_titular': (tit / muestra if muestra > 0 else None),
        })
    return salida


def jugadores_equipo(clave_liga: str, equipo: str,
                     lambda_tot: Optional[float] = None,
                     lambda_on: Optional[float] = None,
                     once: Optional[List[str]] = None,
                     en_vivo: bool = False,
                     lineas: Optional[Dict] = None) -> List[Dict]:
    """
    Los jugadores de un equipo con su probabilidad de rematar.

    `lambda_tot` y `lambda_on` son lo que se espera que tire el EQUIPO en este
    partido — lo que devuelve `rendimiento_equipos.remates_equipo` para su
    bando. Es lo que engancha esta sección al modelo de la Parte 1: contra una
    defensa que concede mucho suben los dos a la vez.

    `once` es la lista de titulares si FotMob la ha publicado. Cuando está, los
    de la lista salen marcados como titulares y el resto se descarta; cuando no
    está, se ordenan por su probabilidad de rematar SI JUEGAN.

    OJO CON LO QUE NO SE DEVUELVE. Cuando no hay once, cada jugador lleva
    `titularidades` y `p_titular` —las veces que ha sido titular en la muestra—
    pero eso es un DATO OBSERVADO, no una prediccion, y la interfaz lo enseña
    como tal («titular en 8 de 10»). Usarlo como probabilidad de que juegue
    calibra a 0,057-0,073 de ECE, por encima del umbral de 0,05 del proyecto
    (punto 6 de la cabecera), así que ni se multiplica por la lambda ni se
    presenta como porcentaje. La lista no está ordenada por quién va a jugar y
    la pantalla lo dice.

    `en_vivo=True` pide los últimos partidos a ESPN (ficha); si no, se sirve
    del roster precalculado (tarjeta), que no cuesta peticiones.
    """
    filas = _de_partidos(clave_liga, equipo) if en_vivo else []
    origen = 'últimos partidos'
    if not filas:
        # `solo_cache=not en_vivo`: la tarjeta lee el fichero y punto; la ficha,
        # que se abre de una en una, sí puede pedir lo que falte.
        filas = _de_roster(clave_liga, equipo, solo_cache=not en_vivo)
        origen = 'temporada'
    if not filas:
        return []

    titulares, casados_de = None, None
    if once:
        pares = casar_once_detalle(once, filas)
        titulares = set(pares.values())
        # CUÁNTOS DEL ONCE SE HAN ENCONTRADO, PARA PODER DECIRLO.
        #
        # Medido sobre 132 nombres de once: casan 88 (67 %). Los que faltan son
        # sobre todo fichajes que ESPN todavía no tiene en sus últimos partidos
        # (16 %) y jugadores con menos de dos apariciones (16 %); sólo el 2 %
        # es un fallo del emparejador. Da igual la causa: una tabla de seis
        # nombres rotulada «once probable» dice que el once son esos seis, y no
        # lo es. La interfaz enseña «6 de 11» y deja de prometer una lista
        # completa.
        casados_de = (len(pares), len(once))

    salida = []
    for f in filas:
        lt = lambda_jugador(f.get('media_tot'), f.get('apariciones'),
                            f.get('posicion'), lambda_tot, 'tot')
        # v163.1 — «A PUERTA» SALE AUNQUE NO HAYA MEDIA PROPIA DEL JUGADOR.
        #
        # Antes se omitía cuando faltaba `media_on`, y falta en todos los
        # rosters cacheados antes de la v163 —el campo `shotsOnTarget` se
        # empezó a guardar entonces y la caché dura tres días—, así que en la
        # tarjeta la columna salía vacía justo donde se pidió verla.
        #
        # Con `media_propia=None`, `lambda_jugador` devuelve el previo
        # posicional puro: la cuota de su puesto por lo que se espera que tire
        # su equipo a puerta. No es un invento — es el estimador `posicion_ref`
        # de la medición, que en «al menos un remate a puerta» dio el MEJOR ECE
        # de la tabla (0,02347) aunque con menos resolución que el encogido.
        # Se marca con `on_del_previo` para que la interfaz no lo presente como
        # si viniera de la forma del jugador.
        lo = lambda_jugador(f.get('media_on'), f.get('apariciones'),
                            f.get('posicion'), lambda_on, 'on')
        if lt is None and lo is None:
            continue
        fila = dict(f)
        fila.update({'lambda_tot': lt, 'lambda_on': lo,
                     'p_remata': p_al_menos_uno(lt),
                     'p_al_arco': p_al_menos_uno(lo),
                     'origen': origen,
                     'on_del_previo': f.get('media_on') is None,
                     'muestra_corta': bool(float(f.get('apariciones') or 0)
                                           < MIN_APARICIONES_FIABLE)})
        # v164 — LA LÍNEA DE LA CASA, SI LA COTIZA.
        #
        # Es la que el usuario va a ver en el boleto, así que la probabilidad
        # que se enseña tiene que ser la de ESA línea y no la de una elegida
        # por nosotros. Cuando la casa no cotiza a este jugador, los cuatro
        # campos se quedan en `None` y la interfaz dice «línea no disponible»:
        # un 0 % sería una afirmación que nadie ha hecho.
        ficha = buscar_linea(lineas, f.get('jugador'))
        for obj, lam, cl, cp in (('tot', lt, 'linea_tot', 'p_linea_tot'),
                                 ('on', lo, 'linea_on', 'p_linea_on')):
            bloque = (ficha or {}).get(obj) or {}
            L = bloque.get('principal')
            fila[cl] = L
            fila[cp] = p_mas_de(lam, L)
            # La cuota de esa línea. El precálculo del día guarda `cuota`
            # directamente —se le quita la escalera entera para que el fichero
            # no pese 968 KB— y el tablero en vivo la trae dentro de `lineas`.
            # Se miran los dos: fiarlo sólo a la escalera dejaba la cuota en
            # `None` en todo lo que viene del fichero, que es la tarjeta.
            fila['cuota_' + obj] = bloque.get('cuota') or (
                (bloque.get('lineas') or {}).get(
                    ('%s' % L) if L is not None else ''))
        if titulares is not None:
            if f['jugador'] not in titulares:
                continue
            fila['titular'] = True
            fila['p_titular'] = 1.0
            fila['casados_de'] = casados_de
        salida.append(fila)
    salida.sort(key=lambda x: (x.get('p_remata') or 0.0), reverse=True)
    return salida


def _casar_once(once: List[str], filas: List[Dict]) -> set:
    """
    Empareja los nombres del once de FotMob con los de ESPN.

    Los dos escriben distinto («Bruno Guimarães» contra «Bruno Guimaraes»,
    «H. Kane» contra «Harry Kane»), así que se pasa por el `name_mapper` del
    proyecto, que es el mismo que empareja equipos y que ya lleva el registro
    de los que no casan. **Un nombre que no casa no se fuerza**: se queda
    fuera, igual que hace `stats_espn.inyectar` con un partido que no encuentra.
    Meter los remates del jugador equivocado sería peor que enseñar diez.
    """
    return set(casar_once_detalle(once, filas).values())


def casar_once_detalle(once: List[str], filas: List[Dict]) -> Dict[str, str]:
    """
    Lo mismo pero diciendo QUÉ nombre casó con cuál.

    Existe aparte porque el conjunto de nombres casados no permite auditar el
    emparejado: si FotMob dice «Bruno Guimarães» y ESPN «Bruno Guimaraes», el
    nombre que entra en el conjunto es el de ESPN, así que comprobar «¿está el
    nombre de FotMob en el conjunto?» da NO para un emparejado que sí funcionó.
    `_v163_emparejado_jugadores.py` se equivocaba justo en eso y contaba nueve
    fallos que no lo eran.
    """
    catalogo = [f['jugador'] for f in filas if f.get('jugador')]
    pares: Dict[str, str] = {}
    usados = set()
    for n in once:
        if n in catalogo:
            pares[n] = n
            usados.add(n)
            continue
        try:
            import name_mapper
            m = name_mapper.mapear(n, catalogo, contexto='remates_jugador')
        except Exception:
            m = None
        # UN JUGADOR DE ESPN NO PUEDE CASAR CON DOS DEL ONCE. Sin esto, dos
        # hermanos o dos homónimos del mismo equipo colapsan en la misma fila y
        # el once se queda en diez sin que se note.
        if m and m not in usados:
            pares[n] = m
            usados.add(m)
    return pares


# ---------------------------------------------------------------------------
# la entrada que consume la interfaz
# ---------------------------------------------------------------------------
def _once_del_partido(home: str, away: str, fecha: str,
                      en_vivo: bool) -> Optional[Dict]:
    """
    El once, con la fecha si se conoce y probando hoy y mañana si no.

    La ficha del partido no lleva la fecha en el ámbito donde se pinta esto, y
    el índice de FotMob se pide POR DÍA. Probar dos días cuesta dos peticiones
    al índice —que además quedan cacheadas en memoria para el resto de la
    sesión— y evita que la sección dependa de refactorizar la ficha entera para
    hacer bajar un dato.
    """
    if fecha:
        return alineacion(fecha, home, away, permitir_red=en_vivo)
    try:
        import pandas as pd
        hoy = pd.Timestamp.now(tz='UTC')
        dias = [(hoy + pd.Timedelta(days=k)).strftime('%Y-%m-%d')
                for k in (0, 1)]
    except Exception:
        return None
    for d in dias:
        al = alineacion(d, home, away, permitir_red=en_vivo)
        if al:
            return al
    return None


def partido(clave_liga: str, home: str, away: str, fecha: str = '',
            en_vivo: bool = False, tope: Optional[int] = None) -> Optional[Dict]:
    """
    Los dos equipos con sus jugadores, listos para pintar.

    Devuelve `None` cuando no hay nada honesto que enseñar —ni roster, ni
    remates, ni λ de equipo con la que anclar—, que es lo que la interfaz
    necesita para no pintar un bloque vacío.

    `tope` recorta cada lista a los N más probables (la tarjeta pide 3, la
    ficha ninguno).
    """
    try:
        import rendimiento_equipos as rq
        eq = rq.remates_equipo(clave_liga, home, away)
    except Exception as e:
        logger.debug('[remates_jugador] remates de equipo: %s', e)
        return None
    if not eq:
        return None
    tot = eq.get('totales') or {}
    on = eq.get('a_puerta') or {}

    once = _once_del_partido(home, away, fecha, en_vivo)
    # Las líneas de la casa, UNA vez por partido y repartidas a los dos lados:
    # el tablero trae a los 22 jugadores juntos. Sin red en la tarjeta.
    try:
        import lineas_jugador
        lineas = lineas_jugador.del_partido(home, away, permitir_red=en_vivo)
    except Exception as e:
        logger.debug('[remates_jugador] líneas de %s-%s: %s', home, away, e)
        lineas = {}

    salida = {'clave_liga': clave_liga, 'home': home, 'away': away,
              'alineacion': once, 'con_lineas': bool(lineas),
              'origen_equipo': tot.get('origen') or 'observado'}
    algo = False
    for lado, equipo in (('home', home), ('away', away)):
        js = jugadores_equipo(
            clave_liga, equipo,
            lambda_tot=tot.get('lambda_' + lado),
            lambda_on=on.get('lambda_' + lado),
            once=(once or {}).get(lado) if once else None,
            en_vivo=en_vivo, lineas=lineas)
        if js:
            algo = True
            # cuántos del once se encontraron, para que la interfaz no rotule
            # «once probable» encima de una lista incompleta
            salida[lado + '_casados_de'] = js[0].get('casados_de')
        salida[lado + '_jugadores'] = js[:tope] if tope else js
    return salida if algo else None


# ---------------------------------------------------------------------------
# el precálculo diario
# ---------------------------------------------------------------------------
def precalcular(dias: int = 2, max_hilos: int = 6) -> Dict[str, Dict]:
    """
    Las alineaciones de los próximos fixtures, listas para guardar en disco.

    Coste: una petición al índice de FotMob por día, más un `matchDetails` por
    partido NUESTRO —no por los 405 del día—, exactamente igual que
    `arbitro_partido.construir`. Con sesenta partidos son sesenta peticiones
    una vez al día, en el bot y no en la pantalla del usuario.

    Sólo se piden las competiciones que publican REMATES, observados o
    estimados: en el resto la sección de jugadores no se pinta y pedir su
    alineación sería gastar red para nada.
    """
    from concurrent.futures import ThreadPoolExecutor
    import arbitro_partido as ap
    import fixtures_espn
    from config import LEAGUES

    claves = [c for c, cfg in LEAGUES.items()
              if cfg.get('disponible') and c in fixtures_espn.ESPN_CODIGOS]
    por_liga = fixtures_espn.fixtures_multi(claves, dias=dias)
    fixtures = []
    for clave, fx in (por_liga or {}).items():
        for f in (fx or []):
            f = dict(f)
            f['clave_liga'] = clave
            fixtures.append(f)

    # índices de los días implicados: una petición por día
    indices: Dict[str, List[Dict]] = {}
    for f in fixtures:
        dia = str(f.get('fecha'))[:10]
        if dia and dia not in indices:
            indices[dia] = ap.indice_dia(dia)

    pendientes = []
    for f in fixtures:
        dia = str(f.get('fecha'))[:10]
        m = ap._empareja(f.get('home'), f.get('away'), indices.get(dia) or [])
        if m:
            pendientes.append((ap.clave_partido(dia, f.get('home'),
                                                f.get('away')), m, f))

    salida: Dict[str, Dict] = {}

    def _uno(par):
        llave, m, f = par
        al = _lineup(m['match_id'])
        if not al:
            return None
        al['partido'] = '%s vs %s' % (f.get('home'), f.get('away'))
        al['fecha'] = str(f.get('fecha'))[:10]
        al['clave_liga'] = f.get('clave_liga')
        return (llave, al)

    with ThreadPoolExecutor(max_workers=max_hilos) as ex:
        for r in ex.map(_uno, pendientes):
            if r:
                salida[r[0]] = r[1]
    logger.info('[remates_jugador] %d fixtures · %d emparejados · %d con once',
                len(fixtures), len(pendientes), len(salida))
    return salida


def guardar(datos: Dict[str, Dict],
            ruta: str = FICHERO_ALINEACIONES) -> None:
    import time
    envoltorio = {'generado': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                  'alineaciones': datos}
    try:
        import io_atomico
        io_atomico.escribir_json(ruta, envoltorio)
    except Exception:
        with open(ruta, 'w', encoding='utf-8') as f:
            json.dump(envoltorio, f, ensure_ascii=False, indent=1)


def main() -> int:
    """Precálculo diario. Lo llama el bot, igual que `arbitro_partido`."""
    import argparse
    p = argparse.ArgumentParser(description='Alineaciones probables del día')
    p.add_argument('--dias', type=int, default=2,
                   help='hoy y cuántos más (por defecto hoy y mañana)')
    p.add_argument('--salida', default=FICHERO_ALINEACIONES)
    p.add_argument('--probar', nargs='+', default=None,
                   metavar=('LIGA HOME AWAY'),
                   help='clave_liga home away [fecha] — imprime el bloque')
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO,
                        format='%(levelname)s:%(name)s:%(message)s')

    if args.probar:
        v = args.probar
        r = partido(v[0], v[1], v[2], v[3] if len(v) > 3 else '', en_vivo=True)
        print(json.dumps(r, ensure_ascii=False, indent=1))
        return 0

    datos = precalcular(dias=args.dias)
    guardar(datos, args.salida)
    tipos: Dict[str, int] = {}
    for a in datos.values():
        tipos[a.get('tipo') or '?'] = tipos.get(a.get('tipo') or '?', 0) + 1
    print('alineaciones resueltas: %d  %s' % (len(datos), tipos))
    for llave, a in list(datos.items())[:8]:
        print('   %-46s %-14s %s'
              % (a.get('partido'), a.get('tipo'),
                 ', '.join((a.get('home') or [])[:3])))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
