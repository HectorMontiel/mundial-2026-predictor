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


def _cargar_alias() -> Dict[str, str]:
    global _alias
    if _alias is None:
        try:
            with open(ARCHIVO_ALIAS, encoding='utf-8') as f:
                _alias = {normalizar(k): v for k, v in json.load(f).items()}
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
}


def _expandir(n: str) -> str:
    """Versión del nombre normalizado con las abreviaturas desplegadas."""
    palabras = [_ABREVIATURAS.get(p, p) for p in n.split()]
    return ' '.join(palabras)


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
    if objetivo in alias and alias[objetivo] in catalogo:
        return alias[objetivo]
    normalizados = {c: normalizar(c) for c in catalogo}
    for c, n in normalizados.items():            # coincidencia exacta tras normalizar
        if n == objetivo:
            return c
    # v104: y otra vez con las abreviaturas desplegadas por los dos lados
    # («atl san luis» → «atletico san luis» contra «atletico de san luis»).
    # Va DESPUÉS de la coincidencia exacta para no cambiar ningún resultado
    # que ya funcionaba: sólo se activa donde antes se devolvía None.
    obj_exp = _expandir(objetivo)
    if obj_exp != objetivo:
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
                  if len(objetivo) >= 5 and (objetivo in n or n in objetivo)]
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
    logger.info(f"[name_mapper] sin mapear: '{nombre}' ({contexto}) — "
                f"mejor candidato '{mejor}' con {ratio:.2f}")
    return None


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
    alias[origen] = destino
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
