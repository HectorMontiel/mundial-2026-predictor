#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Mapeo centralizado de nombres entre fuentes (v34 §4).

The Odds API, Betexplorer y football-data escriben los mismos equipos de
formas distintas ("Inter Miami CF" / "Inter Miami", "Nott'm Forest" /
"Nottingham Forest"). Cada mapeo suelto por módulo provocaba pérdidas
SILENCIOSAS de partidos. Aquí se unifica:

  1. alias manuales (diccionario editable, `alias_manuales.json`),
  2. normalización (minúsculas, sin tildes, sin sufijos societarios),
  3. fuzzy con umbral configurable,
  4. registro de TODO fallo en `nombres_sin_mapear.json` para poder añadir
     el alias y llevar los "sin mapear" a cero.

Se usa desde cuotas_multi, betexplorer_scraper y alpha_finder.
"""

import json
import logging
import os
import unicodedata
from difflib import SequenceMatcher
from typing import Dict, Iterable, List, Optional

logger = logging.getLogger(__name__)

ARCHIVO_ALIAS = 'alias_manuales.json'
ARCHIVO_FALLOS = 'nombres_sin_mapear.json'
UMBRAL = 0.78

# sufijos societarios y ruido que estorban al comparar
_RUIDO = (' fc', ' cf', ' sc', ' ac', ' afc', ' cd', ' ud', ' if', ' bk',
          ' fk', ' sk', ' kk', ' club', ' cfr', ' fsv', ' vfl', ' vfb',
          ' calcio', ' futbol', ' football', ' city', ' w')

_alias: Optional[Dict[str, str]] = None
_fallos: Dict[str, str] = {}

# v115 — pares (nombre, contexto) de los que ya se ha avisado una vez. Ver el
# comentario de `mapear`: el fallo se registra siempre, pero sólo se grita la
# primera vez.
_AVISADOS_MAPEO: set = set()


def _cargar_alias() -> Dict[str, str]:
    global _alias
    if _alias is None:
        try:
            with open(ARCHIVO_ALIAS, encoding='utf-8') as f:
                # v148 — un alias puede tener VARIOS destinos, y se queda el
                # primero que exista en el catálogo de esta liga.
                #
                # Lo obliga football-data, que escribe el mismo club distinto
                # según la división: el Deportivo es «Dep. A Coruna» en SP1 y
                # «La Coruna» en SP2. Con un solo destino, arreglar LaLiga
                # rompía la Hypermotion. Se guarda siempre como lista para que
                # el resto del código no tenga que distinguir los dos casos.
                _alias = {normalizar(k): ([v] if isinstance(v, str) else list(v))
                          for k, v in json.load(f).items()}
        except Exception:
            _alias = {}
    return _alias


def normalizar(nombre: str) -> str:
    """minúsculas, sin tildes/puntuación y sin sufijos societarios."""
    n = unicodedata.normalize('NFKD', str(nombre))
    n = ''.join(c for c in n if not unicodedata.combining(c)).lower()
    for ch in ".,'-/()":
        n = n.replace(ch, ' ')
    n = ' '.join(n.split())
    cambiado = True
    while cambiado:                      # quita sufijos repetidos ("x fc sc")
        cambiado = False
        for suf in _RUIDO:
            if n.endswith(suf) and len(n) > len(suf) + 2:
                n = n[: -len(suf)].strip()
                cambiado = True
    return n


# v104 — ABREVIATURAS QUE LAS CASAS USAN Y LAS FUENTES NO.
#
# Las casas de apuestas escriben «Atl. San Luis», «Dep. Cali», «Atlanta Utd»;
# ESPN publica «Atlético de San Luis», «Deportivo Cali», «Atlanta United FC».
# Tras normalizar quedan «atl san luis» contra «atletico de san luis», que ni
# son iguales, ni uno contiene al otro, ni llegan al umbral de similitud de
# 0,78 — así que el mapeo devolvía None.
#
# Medido en el liquidador: era el modo de fallo de la mayoría de los picks de
# fútbol que se quedaban sin resultado, y cada uno es una lección que el
# aprendizaje continuo no llega a ver. Se resuelve con una tabla de expansión
# en vez de un alias por club, porque el patrón se repite en decenas de
# equipos de media docena de ligas.
#
# NO se incluye nada ambiguo: «Independiente» no se expande, porque
# «Independiente» (Avellaneda) e «Independiente Rivadavia» son clubes
# distintos y adivinar ahí liquidaría el partido equivocado.
_ABREVIATURAS = {
    'atl': 'atletico', 'atlet': 'atletico', 'dep': 'deportivo',
    'depor': 'deportivo', 'utd': 'united', 'univ': 'universidad',
    'nac': 'nacional', 'rac': 'racing', 'spt': 'sporting',
    'st': 'saint', 'gto': 'guanajuato', 'sd': 'sociedad',
    # v148 — 'ind'. Lo destapó un Independiente vs Independiente Rivadavia del
    # 2026-08-21: los DOS nombres acababan en `Independiente` (Avellaneda) y el
    # partido se descartaba por resolverse al mismo equipo. Ese descarte era
    # suerte — en un Independiente Rivadavia contra un tercero, la regla de
    # contención habría devuelto Avellaneda y el modelo habría publicado una
    # probabilidad segura del club EQUIVOCADO, que es peor que no publicar
    # ninguna. Con la expansión, «Ind. Rivadavia» del catálogo se despliega a
    # «independiente rivadavia» y casa exacto ANTES de que la contención opine.
    'ind': 'independiente',
}


def _expandir(n: str) -> str:
    """Versión del nombre normalizado con las abreviaturas desplegadas."""
    palabras = [_ABREVIATURAS.get(p, p) for p in n.split()]
    return ' '.join(palabras)


MIN_PREFIJO_CONTENCION = 3


def _contencion_fiable(objetivo: str, candidato: str) -> bool:
    """
    v163.1 — LA CONTENCIÓN EMPAREJABA CLUBES DISTINTOS, Y SIN AVISAR.

        mapear('Viking FK', catalogo_champions)  ->  'Vikingur Reykjavik'

    El Viking FK es de Stavanger y el Víkingur Reykjavík de Islandia. El
    emparejado no fallaba: acertaba con confianza, el modelo predecía el
    partido con la fuerza del equipo equivocado y publicaba una probabilidad
    de aspecto normal. Un hueco se ve; esto no.

    Pasaba porque `normalizar` deja «Viking FK» en «viking», y la regla de
    contención aceptaba cualquier candidato que lo contuviera como subcadena
    —«**viking**ur reykjavik»— sin mirar el parecido (0,50, muy por debajo del
    umbral de 0,78) porque se aplica antes.

    La regla hace falta: es la que casa «Roma» con «AS Roma», «Betis» con
    «Real Betis» y «Man City» con «Manchester City». Lo que se le añade es la
    condición que separa esas tres del Viking, y no es la que parece:

      · exigir PALABRA COMPLETA tumbaba «Man City» y «West Brom», donde la
        abreviatura trunca una palabra («man» por «manchester»), y truncar es
        legítimo;
      · exigir PARECIDO tampoco vale: «Ajax» contra «Ajax Amsterdam» tiene
        0,44 de similitud, MENOS que el 0,50 del Viking, y es correcto.

    Lo que los separa es cuántas palabras le SOBRAN al nombre largo:

        man     contra manchester           no sobra ninguna    -> truncado
        viking  contra vikingur reykjavik   sobra «reykjavik»
                                            y ninguna casa entera -> OTRO club
        ajax    contra ajax amsterdam       sobra «amsterdam» pero
                                            «ajax» casa entera  -> vale

    Así que: cada palabra del corto tiene que casar con una del largo —entera o
    como prefijo de tres letras o más— y, si al largo le sobran palabras, al
    menos una tiene que casar ENTERA.

    MEDIDO ANTES DE TOCARLO (`_v163_contencion_enganosa.py`): sobre 1.779
    emparejados reales del proyecto —cada equipo de cada competición activa
    contra el catálogo de su motor y contra el de ESPN— cambia **exactamente
    uno**, y es el Viking. El resto no se mueve.
    """
    corto, largo = sorted((objetivo, candidato), key=len)
    if corto not in largo:
        return False
    t_corto, restantes = corto.split(), list(largo.split())
    if not t_corto or not restantes:
        return False
    exactas = 0
    for p in t_corto:
        if p in restantes:
            restantes.remove(p)
            exactas += 1
            continue
        cand = [q for q in restantes
                if len(p) >= MIN_PREFIJO_CONTENCION and q.startswith(p)]
        if not cand:
            return False
        restantes.remove(cand[0])
    return exactas >= 1 or not restantes


def mapear(nombre: str, catalogo: Iterable[str], umbral: float = UMBRAL,
           contexto: str = '') -> Optional[str]:
    """Devuelve el nombre del catálogo que corresponde, o None (y lo
    registra para que se pueda añadir un alias)."""
    catalogo = list(catalogo)
    if not catalogo:
        return None
    if nombre in catalogo:
        return nombre
    objetivo = normalizar(nombre)
    alias = _cargar_alias()
    for _destino in alias.get(objetivo, ()):
        if _destino in catalogo:
            return _destino
    normalizados = {c: normalizar(c) for c in catalogo}
    for c, n in normalizados.items():            # coincidencia exacta tras normalizar
        if n == objetivo:
            return c
    # v104: y otra vez con las abreviaturas desplegadas por los dos lados
    # («atl san luis» → «atletico san luis» contra «atletico de san luis»).
    # Va DESPUÉS de la coincidencia exacta para no cambiar ningún resultado
    # que ya funcionaba: sólo se activa donde antes se devolvía None.
    # v148 — la expansión se prueba SIEMPRE, no sólo cuando el objetivo cambia.
    #
    # La condición era `if obj_exp != objetivo`, o sea que sólo entraba aquí si
    # las abreviaturas estaban en el nombre que llega. Cuando están en el
    # CATÁLOGO —«Ind. Rivadavia» contra el «Independiente Rivadavia» de ESPN—
    # el objetivo no cambia, el bloque se saltaba entero y la comparación caía
    # en la regla de contención, que devolvía «Independiente» (Avellaneda).
    #
    # Correr el bucle igualmente no cambia nada donde ya funcionaba: si no hay
    # abreviaturas por ningún lado, `_expandir` es la identidad y esta
    # comparación repite la de igualdad exacta que ya falló dos líneas arriba.
    # Lo que sí hace es que una igualdad EXACTA tras expandir gane a una
    # coincidencia por subcadena, que es el orden correcto: la primera es
    # prueba, la segunda es indicio.
    obj_exp = _expandir(objetivo)
    for c, n in normalizados.items():
        if _expandir(n) == obj_exp:
            return c
    # y con el conector suelto que suele sobrar («de», «del»)
    sin_conector = ' '.join(w for w in obj_exp.split() if w not in ('de', 'del', 'la', 'el'))
    for c, n in normalizados.items():
        if ' '.join(w for w in _expandir(n).split()
                    if w not in ('de', 'del', 'la', 'el')) == sin_conector:
            return c
    # Contención (subcadena). v66: antes devolvía el PRIMER candidato que
    # contuviera al objetivo, lo que con catálogos grandes es una lotería —
    # "Congo" entra en "DR Congo", "Guinea" en "Equatorial Guinea" y
    # "Guinea-Bissau", "Sudan" en "South Sudan", "Ireland" en "Northern
    # Ireland". Ahora se recogen TODOS los candidatos por contención y se
    # devuelve el más parecido (mayor ratio y, a igualdad, el de longitud más
    # próxima), que es siempre el correcto en esos pares.
    contenidos = [c for c, n in normalizados.items()
                  if len(objetivo) >= 5 and _contencion_fiable(objetivo, n)]
    if contenidos:
        return max(contenidos,
                   key=lambda c: (SequenceMatcher(None, objetivo, normalizados[c]).ratio(),
                                  -abs(len(normalizados[c]) - len(objetivo))))
    mejor, ratio = None, 0.0
    for c, n in normalizados.items():
        s = SequenceMatcher(None, objetivo, n).ratio()
        if s > ratio:
            mejor, ratio = c, s
    if ratio >= umbral:
        return mejor
    _fallos[nombre] = contexto or '?'
    # v115 — UN FALLO QUE SE REPITE CIEN VECES DEJA DE SER INFORMACIÓN.
    #
    # Esto emitía una línea POR INTENTO, y `buscar_event_id` compara cada
    # fixture contra el catálogo entero de su liga: en el registro de
    # producción que mandó el usuario salían más de doscientas líneas
    # seguidas de «sin mapear», todas del mismo puñado de nombres, tapando los
    # errores de verdad que había debajo.
    #
    # El fallo se sigue registrando entero —en `_fallos`, que es lo que se
    # vuelca a `nombres_sin_mapear.json` para poder añadir el alias— y se
    # avisa la PRIMERA vez que aparece cada par (nombre, contexto). Las
    # repeticiones bajan a debug. Es el mismo criterio que la v110 aplicó a
    # los 403 de ESPN.
    _k_aviso = (nombre, contexto or '?')
    if _k_aviso in _AVISADOS_MAPEO:
        logger.debug(f"[name_mapper] sin mapear: '{nombre}' ({contexto}) "
                     f"(repetido)")
    else:
        _AVISADOS_MAPEO.add(_k_aviso)
        logger.info(f"[name_mapper] sin mapear: '{nombre}' ({contexto}) — "
                    f"mejor candidato '{mejor}' con {ratio:.2f}")
    return None


def mejor_candidato(nombre: str, catalogo: Iterable[str]):
    """
    El candidato más parecido del catálogo y su ratio, SIN decidir nada.

    v148 — lo pide `league_engine._completar_desde_espn`, que necesita
    distinguir dos cosas que `mapear` mete en el mismo None:

      · «Sporting Gijón» contra un catálogo que dice «Sp Gijon» — es el MISMO
        club escrito de otra forma, y darlo de alta partiría su historial en
        dos. Ratio alto.
      · «Coventry City» contra el catálogo de la Premier — es un club que
        ACABA de ascender y de verdad no está. Ratio bajo.

    Hasta la v148 las dos se descartaban igual, y por eso la cola de ESPN era
    estructuralmente incapaz de incorporar a un ascendido: el catálogo con el
    que compara sale del propio histórico, así que un equipo nuevo nunca
    estaba en él por definición. Cada agosto, hasta que football-data
    publicaba el curso, los recién ascendidos salían «sin pronóstico».
    """
    catalogo = list(catalogo)
    if not catalogo:
        return None, 0.0
    objetivo = normalizar(nombre)
    mejor, ratio = None, 0.0
    for c in catalogo:
        s = SequenceMatcher(None, objetivo, normalizar(c)).ratio()
        if s > ratio:
            mejor, ratio = c, s
    return mejor, ratio


def volcar_fallos() -> int:
    """Persiste los nombres no mapeados (para crear alias y llegar a 0).

    v89 — el fichero acumulaba fallos PARA SIEMPRE: seguía listando las 38
    selecciones que dejaron de fallar cuando la v66 amplió el catálogo a 200
    (verificado: hoy todas mapean). Una lista de pendientes con entradas ya
    resueltas deja de servir para llegar a 0. Ahora cada entrada guarda cuándo
    se vio por última vez y las que llevan >30 días sin reaparecer se retiran
    solas; las del formato antiguo (sin fecha) se conservan solo si vuelven a
    fallar hoy.
    """
    if not _fallos:
        return 0
    import datetime as _dt
    hoy = _dt.date.today().isoformat()
    limite = (_dt.date.today() - _dt.timedelta(days=30)).isoformat()
    previos = {}
    if os.path.exists(ARCHIVO_FALLOS):
        try:
            with open(ARCHIVO_FALLOS, encoding='utf-8') as f:
                bruto = json.load(f)
            for k, v in bruto.items():
                if isinstance(v, dict) and v.get('visto', '') >= limite:
                    previos[k] = v
        except Exception:
            pass
    for k, ctx in _fallos.items():
        previos[k] = {'contexto': ctx, 'visto': hoy}
    with open(ARCHIVO_FALLOS, 'w', encoding='utf-8') as f:
        json.dump(previos, f, ensure_ascii=False, indent=2)
    return len(_fallos)


def añadir_alias(origen: str, destino: str):
    """Registra un alias manual permanente."""
    alias = {}
    if os.path.exists(ARCHIVO_ALIAS):
        with open(ARCHIVO_ALIAS, encoding='utf-8') as f:
            alias = json.load(f)
    previo = alias.get(origen)
    if previo is None:
        alias[origen] = destino
    else:
        lista = [previo] if isinstance(previo, str) else list(previo)
        if destino not in lista:
            lista.append(destino)
        alias[origen] = lista if len(lista) > 1 else lista[0]
    with open(ARCHIVO_ALIAS, 'w', encoding='utf-8') as f:
        json.dump(alias, f, ensure_ascii=False, indent=2)
    global _alias
    _alias = None


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    catalogo = ['Inter Miami', 'Nottingham Forest', 'Bayern Munich',
                'Atlético Madrid', 'Sporting Kansas City']
    for prueba in ('Inter Miami CF', "Nott'm Forest", 'Bayern München',
                   'Atletico Madrid', 'Sporting KC', 'Equipo Inexistente'):
        print(f"  {prueba!r:<28} -> {mapear(prueba, catalogo, contexto='demo')}")
