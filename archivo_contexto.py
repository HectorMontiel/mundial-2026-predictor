#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v217 — Archivo de contexto: guardar hoy lo que hará falta para medir mañana.

POR QUÉ EXISTE, Y POR QUÉ ES URGENTE AUNQUE NO HAGA NADA VISIBLE
----------------------------------------------------------------
El backtest de la v212 dejó una conclusión incómoda: la regla de escalada de
4 fuentes **no se pudo medir ni una sola vez** sobre el histórico, porque dos
de sus fuentes no existen hacia atrás. Nadie archivó las señales de contexto de
un partido de 2024, así que no hay contra qué contrastarlas. Lo mismo pasa con
las cuatro banderas de la v209 (divergencia, cuota inflada, racha, entrenador):
están escritas, avisan en pantalla y siguen con `medido: False` porque no hay
registro de qué decían EN EL MOMENTO del pick.

Ese agujero sólo se cierra hacia delante. Cada día que pasa sin archivar es un
día de datos que no se recupera, y por eso esto se construye antes que
cualquier regla nueva: **es la condición necesaria de todo lo demás.**

QUÉ GUARDA, Y LA PROPIEDAD QUE LO HACE ÚTIL
-------------------------------------------
Las señales tal y como estaban ANTES de que se jugara el partido, con su
timestamp. Es append-only y de sólo-inserción por partido: lo que se anotó no
se reescribe. Sin esa propiedad el archivo no sirve para medir nada — un
registro que se puede retocar después de ver el resultado no es evidencia.

CÓMO SE USA DESPUÉS
-------------------
Cruzando `clave` con `pronosticos_guardados` y con `fiabilidad_picks`, que ya
saben si el pick acertó. La pregunta que podrá contestarse, y hoy no:

    ¿los picks con bandera de «lesión múltiple» acertaron menos que los demás?
    ¿el rebote por entrenador nuevo existe, y de qué tamaño?
    ¿la divergencia extrema anticipa un fallo?

Con `N_MINIMO_PARA_MEDIR` picks por bandera se podrá responder. Antes, no, y
`estado()` lo dice en vez de fingir que sí.
"""

import datetime as _dt
import json
import logging
import os
from typing import Dict, List, Optional

logger = logging.getLogger('archivo_contexto')

FICHERO = os.environ.get('ARCHIVO_CONTEXTO', 'archivo_contexto.json')
DIAS_MEMORIA = 400          # más de una temporada: lo que hace falta para medir
N_MINIMO_PARA_MEDIR = 200   # por bandera, antes de poder concluir

_CACHE: Optional[Dict] = None


def _leer() -> Dict:
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    _CACHE = {'partidos': {}, 'version': 1}
    try:
        if os.path.exists(FICHERO):
            with open(FICHERO, encoding='utf-8') as f:
                d = json.load(f)
            if isinstance(d, dict) and isinstance(d.get('partidos'), dict):
                _CACHE = d
    except Exception as e:
        logger.warning('[archivo] no se pudo leer %s: %s', FICHERO, e)
    return _CACHE


def _escribir(doc: Dict) -> bool:
    global _CACHE
    _CACHE = doc
    try:
        import io_atomico
        return bool(io_atomico.escribir_json(FICHERO, doc))
    except Exception as e:
        logger.warning('[archivo] no se pudo escribir %s: %s', FICHERO, e)
        return False


def recargar() -> None:
    global _CACHE
    _CACHE = None


def clave(pick: Dict) -> str:
    p = pick or {}
    return '|'.join([str(p.get('clave_liga') or ''),
                     str(p.get('partido') or ''),
                     str(p.get('fecha') or '')[:10]])


def _poda(doc: Dict) -> Dict:
    """Tira lo más viejo que `DIAS_MEMORIA`. Sin esto el fichero no para."""
    try:
        corte = (_dt.date.today()
                 - _dt.timedelta(days=DIAS_MEMORIA)).isoformat()
    except Exception:
        return doc
    partidos = {k: v for k, v in (doc.get('partidos') or {}).items()
                if str(v.get('fecha') or '')[:10] >= corte}
    return {**doc, 'partidos': partidos}


# ---------------------------------------------------------------------------
def archivar(pick: Dict, senales: Optional[List[Dict]] = None,
             banderas: Optional[List[str]] = None) -> bool:
    """Deja constancia del contexto de este partido. UNA sola vez.

    De sólo-inserción, igual que `pronosticos_guardados.guardar`, y por la
    misma razón: lo que vale es lo que se sabía ANTES. Si se pudiera
    sobreescribir, el archivo contaría la historia de después.
    """
    p = pick or {}
    if p.get('jugado'):
        return False           # de un partido acabado ya no se archiva nada
    k = clave(p)
    if not k.strip('|'):
        return False
    doc = _leer()
    if k in (doc.get('partidos') or {}):
        return False

    filas = []
    for s in (senales or []):
        if not isinstance(s, dict):
            continue
        filas.append({'tipo': s.get('tipo'), 'peso': s.get('peso'),
                      'fuente': s.get('fuente'),
                      'confianza': s.get('confianza_fuente'),
                      'detalle': str(s.get('detalle') or '')[:200]})
    if not filas and not banderas:
        return False           # nada que archivar no es un archivo vacío

    doc = dict(doc)
    doc['partidos'] = dict(doc.get('partidos') or {})
    doc['partidos'][k] = {
        'clave_liga': p.get('clave_liga'), 'partido': p.get('partido'),
        'liga': p.get('liga'), 'fecha': str(p.get('fecha') or '')[:10],
        'anotado': _dt.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'),
        'senales': filas,
        'banderas': sorted(set(banderas or [])),
    }
    return _escribir(_poda(doc))


def de_partido(pick: Dict) -> Dict:
    """Lo archivado de ese partido, o vacío."""
    return dict((_leer().get('partidos') or {}).get(clave(pick)) or {})


def archivar_del_barrido(picks: List[Dict], con_contexto: bool = True) -> Dict:
    """Archiva el contexto de una tanda de picks. Pensado para el cron.

    `con_contexto=False` archiva sólo las banderas de la auditoría, que son
    baratas; con `True` además consulta `scraper_contexto`, que sale a la red.
    """
    n = saltados = 0
    for p in list(picks or []):
        if not isinstance(p, dict):
            continue
        try:
            banderas = []
            try:
                import auditoria_pick as ap
                banderas = (ap.auditar(p, con_contexto=False)
                            .get('banderas') or [])
            except Exception as e:
                logger.debug('[archivo] banderas: %s', e)
            senales = []
            if con_contexto:
                try:
                    import scraper_contexto as sc
                    h, a = (p.get('partido') or ' vs ').split(' vs ')[:2] \
                        if ' vs ' in str(p.get('partido') or '') else ('', '')
                    senales = sc.senales({
                        'clave_liga': p.get('clave_liga'), 'home': h,
                        'away': a, 'partido': p.get('partido'),
                        'deporte': str(p.get('deporte') or 'futbol').lower(),
                        'fecha': p.get('fecha')})
                except Exception as e:
                    logger.debug('[archivo] señales: %s', e)
            if archivar(p, senales, banderas):
                n += 1
            else:
                saltados += 1
        except Exception as e:
            logger.debug('[archivo] pick saltado: %s', e)
            saltados += 1
    return {'archivados': n, 'saltados': saltados}


# ---------------------------------------------------------------------------
def estado() -> Dict:
    """Cuánto lleva acumulado y qué falta para poder medir cada bandera."""
    partidos = _leer().get('partidos') or {}
    por_bandera: Dict[str, int] = {}
    por_senal: Dict[str, int] = {}
    for v in partidos.values():
        for b in (v.get('banderas') or []):
            por_bandera[b] = por_bandera.get(b, 0) + 1
        for s in (v.get('senales') or []):
            t = str(s.get('tipo') or '?')
            por_senal[t] = por_senal.get(t, 0) + 1
    fechas = [str(v.get('fecha') or '')[:10] for v in partidos.values()]
    listas = sorted(b for b, n in por_bandera.items()
                    if n >= N_MINIMO_PARA_MEDIR)
    return {
        'partidos': len(partidos),
        'desde': min(fechas) if fechas else None,
        'hasta': max(fechas) if fechas else None,
        'por_bandera': por_bandera, 'por_senal': por_senal,
        'banderas_medibles': listas,
        'minimo_para_medir': N_MINIMO_PARA_MEDIR,
        'nota': ('todavía no hay bandera con muestra suficiente para medir'
                 if not listas else
                 'ya se puede medir: ' + ', '.join(listas)),
    }


if __name__ == '__main__':
    import sys
    print(json.dumps(estado(), ensure_ascii=False, indent=1))
    sys.exit(0)
