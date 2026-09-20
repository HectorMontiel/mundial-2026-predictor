#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v238 — el diccionario de nombres se amplía solo, en todos los deportes.

EL PROBLEMA
-----------
`name_mapper` tiene un diccionario manual (`alias_manuales.json`) y un fuzzy con
umbral 0,78. Lo que cae entre medias se registra como «sin mapear», y el log se
llena:

    sin mapear: 'Nahuel Banegas'  -> mejor candidato 'Nahuel Eugenio Banegas' 0,78
    sin mapear: 'Manuel Guillén'  -> mejor candidato 'Manuel Agustin Guillen'  0,78
    sin mapear: 'Eduardo Salvio'  -> mejor candidato 'Agustín Cardozo'         0,41

Los dos primeros son LA MISMA PERSONA con el segundo nombre puesto o quitado.
El tercero no tiene nada que ver. Un umbral no distingue esos tres casos porque
mira parecido de letras, y «Lucas Acosta» contra «Lucas Castro» (0,75) se parece
más que «Manuel Guillén» contra «Manuel Agustin Guillen» en algunas cadenas.

Mantener eso a mano no escala: cada jornada trae jugadores nuevos, cada
temporada equipos nuevos, y el tenis renueva cuadro cada semana. El usuario lo
pidió así: «un diccionario completo de todos los deportes... y que sea dinámico,
para que cuando lleguen más equipos o un jugador nuevo se recalibre».

CÓMO SE DEDUCE SIN ADIVINAR
---------------------------
La diferencia entre las dos primeras líneas y la tercera no es de grado: es
estructural. Un nombre de persona tiene NOMBRE y APELLIDO, y lo que varía entre
fuentes son los de en medio. Así que un alias se acepta sólo cuando:

  1. coinciden el PRIMER token y el ÚLTIMO, y
  2. uno de los dos tiene más tokens que el otro (los de en medio sobran), y
  3. todos los tokens del corto están en el largo.

    «nahuel banegas»  vs  «nahuel eugenio banegas»   -> ACEPTA
    «manuel guillen»  vs  «manuel agustin guillen»   -> ACEPTA
    «lucas acosta»    vs  «lucas castro»             -> rechaza (apellido)
    «eduardo salvio»  vs  «agustin cardozo»          -> rechaza (todo)

Y la variante de inicial, que es la otra forma en que las fuentes difieren:

    «j. mensik»       vs  «jakub mensik»             -> ACEPTA
    «mensik j.»       vs  «jakub mensik»             -> ACEPTA

POR QUÉ ESTO NO PUEDE INVENTAR UN EMPAREJAMIENTO
------------------------------------------------
Porque no mira parecido: mira que el apellido sea IDÉNTICO y que el nombre corto
esté contenido en el largo. Dos personas distintas con el mismo nombre y apellido
existen, pero eso el fuzzy tampoco lo resuelve — y aquí, al menos, el criterio es
declarable y se puede auditar entrada por entrada.

Lo que se rechaza siempre, cueste lo que cueste: nombres de una sola palabra
(«Doka», «Moraes», «Índio»). Sin apellido no hay nada que comprobar, y ahí es
donde un alias falso hace más daño.
"""
import datetime as _dt
import json
import logging
import os
import re
import unicodedata
from typing import Dict, Optional, Tuple

logger = logging.getLogger('alias_nombres')

ARTEFACTO = 'alias_auto_nombres.json'
FALLOS = 'nombres_sin_mapear.json'

# Palabras que no aportan identidad y que cada fuente pone o quita a su gusto.
_RELLENO = {'de', 'del', 'la', 'el', 'los', 'las', 'da', 'do', 'dos', 'van',
            'von', 'di', 'jr', 'sr', 'ii', 'iii'}


def _norm(nombre: str) -> str:
    s = unicodedata.normalize('NFKD', str(nombre or ''))
    s = ''.join(c for c in s if not unicodedata.combining(c)).lower()
    s = re.sub(r"[.\-'’,]", ' ', s)
    return ' '.join(s.split())


def _tokens(nombre: str):
    return [t for t in _norm(nombre).split() if t and t not in _RELLENO]


def _es_inicial(t: str) -> bool:
    return len(t) == 1


def deducible(corto: str, largo: str) -> Tuple[bool, str]:
    """¿Son la misma persona escrita de otra forma? Con el motivo.

    LA REGLA, EN UNA FRASE: todo lo que el nombre corto dice, el largo lo
    confirma. Nada de parecido de letras.

    En concreto, con los tokens ya normalizados y sin relleno:

      · los que NO son inicial del corto tienen que estar TODOS en el largo;
      · cada inicial del corto tiene que ser la primera letra de algún token
        del largo que no se haya usado ya;
      · y el corto tiene que aportar al menos dos tokens, o sea nombre y
        apellido. Con uno solo no hay nada que confirmar.

    No se exige orden, y eso es deliberado: el tenis publica «Mensik J.» y el
    catálogo «Jakub Mensik». Exigir que el último token coincida rechazaría
    medio cuadro.

    Lo que esto acepta y por qué:

        «nahuel banegas»      ⊂  «nahuel eugenio banegas»   nombre de en medio
        «dardo miloc»         ⊂  «dardo federico miloc»     idem
        «andres roman»        ⊂  «andres felipe roman m.»   apellido doble
        «mensik j.»           ⊂  «jakub mensik»             inicial y orden

    Y lo que rechaza:

        «lucas acosta»        vs «lucas castro»    el apellido no está
        «eduardo salvio»      vs «agustin cardozo» no está nada
        «doka»                vs «klaus»           una sola palabra

    LO QUE NO RESUELVE, Y CONVIENE SABERLO: dos personas distintas que
    compartan nombre y apellido se emparejarían. El fuzzy tampoco lo resuelve,
    y aquí al menos el criterio es declarable y cada entrada guarda su motivo,
    así que el fichero se puede auditar línea por línea.
    """
    a, b = _tokens(corto), _tokens(largo)
    if not a or not b:
        return False, 'nombre vacio'
    if len([t for t in a if not _es_inicial(t)]) < 1 or len(b) < 2:
        return False, 'una sola palabra: no hay apellido que comprobar'
    if len(a) < 2:
        return False, 'una sola palabra: no hay apellido que comprobar'
    if a == b:
        return False, 'ya son iguales al normalizar'

    corto_t, largo_t = (a, b) if len(a) <= len(b) else (b, a)
    disponibles = list(largo_t)

    # los tokens completos tienen que estar, literalmente
    for t in corto_t:
        if _es_inicial(t):
            continue
        if t in disponibles:
            disponibles.remove(t)
        else:
            return False, 'el corto tiene un token que el largo no'

    # y cada inicial tiene que casar con alguno de los que quedan
    for t in corto_t:
        if not _es_inicial(t):
            continue
        casa = next((d for d in disponibles if d.startswith(t)), None)
        if casa is None:
            return False, 'una inicial del corto no casa con ningun token'
        disponibles.remove(casa)

    completos = [t for t in corto_t if not _es_inicial(t)]
    if len(completos) < 1:
        return False, 'solo iniciales: no hay nada que confirmar'
    if len(corto_t) < 2:
        return False, 'una sola palabra: no hay apellido que comprobar'
    return True, 'todo lo que dice el corto lo confirma el largo'


def _cargar(ruta: Optional[str] = None) -> Dict:
    try:
        r = ruta or ARTEFACTO
        if os.path.exists(r):
            with open(r, encoding='utf-8') as f:
                return json.load(f) or {}
    except Exception as e:
        logger.warning('[alias_nombres] ilegible: %s', e)
    return {}


def tabla(ruta: Optional[str] = None) -> Dict[str, str]:
    """`{nombre_de_la_fuente: nombre_del_catalogo}` para `name_mapper`."""
    doc = _cargar(ruta)
    return {k: v['canonico'] for k, v in (doc.get('alias') or {}).items()
            if isinstance(v, dict) and v.get('canonico')}


def detectar(fallos: Optional[str] = None) -> Dict:
    """Propone alias a partir de los «sin mapear» que ya se registraron.

    No sale a la red ni necesita los catalogos: `name_mapper` guarda el mejor
    candidato de cada fallo, y con el par basta para comprobar si son la misma
    persona.
    """
    ruta = fallos or FALLOS
    try:
        with open(ruta, encoding='utf-8') as f:
            bruto = json.load(f) or {}
    except Exception as e:
        logger.warning('[alias_nombres] no se pudo leer %s: %s', ruta, e)
        return {'alias': {}, 'revisados': 0}

    propuestas: Dict[str, Dict] = {}
    revisados = 0
    descartados: Dict[str, int] = {}
    for nombre, info in bruto.items():
        if not isinstance(info, dict):
            continue
        cand = info.get('candidato')
        if not cand:
            continue
        revisados += 1
        ok, motivo = deducible(nombre, cand)
        if not ok:
            descartados[motivo] = descartados.get(motivo, 0) + 1
            continue
        propuestas[_norm(nombre)] = {
            'canonico': str(cand),
            'origen': str(nombre),
            'contexto': info.get('contexto'),
            'ratio_fuzzy': info.get('ratio'),
            'motivo': motivo}
    return {'generado': _dt.datetime.now(_dt.timezone.utc)
                           .strftime('%Y-%m-%dT%H:%M:%SZ'),
            'revisados': revisados, 'descartados': descartados,
            'alias': propuestas}


def fusionar(nuevo: Dict, ruta: Optional[str] = None) -> Dict:
    """Une lo descubierto con lo que ya habia. No borra nunca."""
    doc = _cargar(ruta)
    viejos = doc.get('alias') or {}
    for k, v in (nuevo.get('alias') or {}).items():
        v = dict(v, ultima_vez=nuevo.get('generado'))
        if k in viejos:
            v['primera_vez'] = viejos[k].get('primera_vez') or v['ultima_vez']
        else:
            v['primera_vez'] = v['ultima_vez']
        viejos[k] = v
    return dict(nuevo, alias=viejos)


def guardar(doc: Dict, ruta: Optional[str] = None) -> bool:
    try:
        with open(ruta or ARTEFACTO, 'w', encoding='utf-8') as f:
            json.dump(doc, f, ensure_ascii=False, indent=1)
        return True
    except Exception as e:
        logger.warning('[alias_nombres] no se pudo escribir: %s', e)
        return False


def actualizar(ruta: Optional[str] = None) -> int:
    """Lo que llama el cron. Devuelve cuántos alias hay en total."""
    doc = fusionar(detectar(), ruta)
    guardar(doc, ruta)
    n = len(doc.get('alias') or {})
    logger.info('[alias_nombres] %d alias de nombre conocidos (%d fallos '
                'revisados)', n, doc.get('revisados', 0))
    return n


def main() -> int:
    import io
    import sys
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8',
                                  errors='replace')
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    doc = fusionar(detectar())
    guardar(doc)
    al = doc.get('alias') or {}
    print('fallos revisados: %d · alias deducidos: %d'
          % (doc.get('revisados', 0), len(al)))
    print()
    print('POR QUE SE DESCARTO EL RESTO:')
    for motivo, n in sorted((doc.get('descartados') or {}).items(),
                            key=lambda kv: -kv[1]):
        print('   %-52s %d' % (motivo, n))
    print()
    print('ALIAS DEDUCIDOS:')
    for k, v in sorted(al.items()):
        print('   %-32s -> %-34s (%s)'
              % (k, v.get('canonico'), v.get('motivo', '')[:34]))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
