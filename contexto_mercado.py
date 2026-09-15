#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Qué dice el MERCADO y qué dicen las NOTICIAS de un partido, en un solo sitio.

QUÉ ES ESTO
-----------
El usuario pidió «que se analice el mercado y las noticias en conjunto para
saber cómo proceder». Esto junta las dos señales que el proyecto YA tiene
guardadas y que hasta ahora no leía nadie:

  1. **El movimiento de línea.** `cuotas_mx.py` guarda, además del precio
     actual, el de APERTURA de las cinco casas mexicanas — 2.502 entradas en
     646 partidos el 2026-09-16. Estaba en el fichero y sin leer desde la v192;
     la bitácora lo tiene apuntado como pendiente de alto valor. La diferencia
     entre apertura y precio actual es hacia dónde se movió el dinero.

  2. **La alineación.** `alineaciones_dia.json`, que regenera el bot cada
     madrugada, distingue una alineación CONFIRMADA del «once del último
     partido» —su propio campo lo dice: `tipo: lastStarting11`, «No hay
     alineación todavía»—. Es la parte accionable de lo que en apuestas se
     llama «noticias»: quién juega.

LO QUE ESTO **NO** ES, Y CONVIENE QUE QUEDE ESCRITO
---------------------------------------------------
No es una señal validada. **No está medido que el movimiento de línea prediga
nada en este proyecto**, y hay una razón concreta por la que todavía no puede
medirse: para cruzar el movimiento con el resultado hace falta un ledger con
cuotas, y el ledger de este proyecto se quedó sin ellas (bitácora §6i/§6j). Con
eso arreglado, la medición es directa y está descrita en el §5 de esta
cabecera.

Así que esto informa y se etiqueta como informativo. Lo que NO hace es entrar
en el Score, en el EV ni en ninguna recomendación.

CÓMO SE LEE EL MOVIMIENTO
-------------------------
Una cuota que BAJA es dinero entrando en ese lado: la casa se protege
acortando el precio. Una que SUBE es lo contrario. Se mide en porcentaje sobre
la apertura y se promedia entre las casas que publican las dos cifras, porque
una sola casa moviéndose puede ser un ajuste suyo y no mercado.
"""

from __future__ import annotations

import json
import logging
import os
import unicodedata
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

FICHERO_MX = 'cuotas_mx.json'
FICHERO_ALINEACIONES = 'alineaciones_dia.json'

# Cuánto tiene que moverse un precio para que se cuente como movimiento. Por
# debajo de esto es ruido de redondeo de la casa: con cuotas de 1,10 a 2,50, un
# 2 % es un paso de una sola posición en su rejilla.
UMBRAL_MOVIMIENTO = 0.02
# Y cuántas casas tienen que estar de acuerdo. Una sola moviéndose es su ajuste;
# tres moviéndose en la misma dirección es el mercado.
CASAS_MINIMAS = 2

# TRES NIVELES, NO DOS. El fichero distingue cuatro tipos y sólo uno es una
# alineación de verdad:
#
#     standard        «confirmada»   -> la publicó el club
#     predicted       «probable»     -> el pronóstico de FotMob
#     simple          «probable»
#     lastStarting11  «último once»  -> el XI del partido anterior, o sea nada
#
# La primera versión de este módulo trataba todo lo que no fuera
# `lastStarting11` como confirmado, y eso hacía que la lectura conjunta dijera
# «con la alineación ya confirmada» de un once que FotMob sólo había
# pronosticado. Es una frase falsa sobre un dato que el propio fichero
# etiquetaba bien.
NIVEL_ALINEACION = {'standard': 'confirmada', 'predicted': 'probable',
                    'simple': 'probable', 'lastStarting11': 'ultimo_once'}
TEXTO_ALINEACION = {
    'confirmada': 'alineación confirmada por el club',
    'probable': 'alineación probable, todavía no confirmada',
    'ultimo_once': ('no hay alineación todavía: es el once del último '
                    'partido'),
    'desconocida': 'no se sabe quién juega',
}

_MEMO: Dict[str, Dict] = {}


def _leer(ruta: str) -> Dict:
    if ruta in _MEMO:
        return _MEMO[ruta]
    datos: Dict = {}
    try:
        if os.path.exists(ruta):
            with open(ruta, encoding='utf-8') as f:
                datos = json.load(f) or {}
    except Exception as e:
        logger.debug('[contexto_mercado] %s ilegible: %s', ruta, e)
    _MEMO[ruta] = datos
    return datos


_INDICE: Optional[Dict] = None


def _indice_mx() -> Dict:
    """Los partidos de `cuotas_mx.json` indexados por (local, visitante).

    Recorrer los 646 partidos por cada pata costaba 431 × 646 comparaciones en
    una pantalla con 431 patas. Es el mismo patrón que la bitácora §4 documenta
    tres veces: la consulta barata repetida muchas veces es la cara.
    """
    global _INDICE
    if _INDICE is not None:
        return _INDICE
    fuera: Dict = {}
    for v in (_leer(FICHERO_MX).get('partidos') or {}).values():
        clave = (_llano(v.get('home')), _llano(v.get('away')))
        fuera.setdefault(clave, v)
    _INDICE = fuera
    return fuera


def _llano(t) -> str:
    """Un nombre comparable: sin tildes, sin puntuación, en minúsculas."""
    s = unicodedata.normalize('NFKD', str(t or ''))
    s = ''.join(c for c in s if not unicodedata.combining(c))
    return ''.join(c for c in s.lower() if c.isalnum())


# ---------------------------------------------------------------------------
# 1. El movimiento de línea
# ---------------------------------------------------------------------------
def movimiento(home: str, away: str, lado: str = 'home') -> Optional[Dict]:
    """
    Cuánto se movió el precio de ese lado entre la apertura y ahora.

    `lado` es 'home', 'draw' o 'away'. Devuelve `None` cuando el partido no
    está en el fichero o ninguna casa publica las dos cifras — que es un
    resultado legítimo y frecuente, no un fallo.
    """
    reg = _indice_mx().get((_llano(home), _llano(away)))
    if not reg:
        return None

    derivas: List[float] = []
    detalle: Dict[str, float] = {}
    for casa, mercados in (reg.get('casas') or {}).items():
        bloque = (mercados or {}).get('HOME_DRAW_AWAY')
        if not isinstance(bloque, dict):
            continue
        ahora = bloque.get(lado)
        ap = (bloque.get('apertura') or {}).get(lado)
        try:
            ahora, ap = float(ahora), float(ap)
        except (TypeError, ValueError):
            continue
        if ap <= 0:
            continue
        deriva = (ahora - ap) / ap
        derivas.append(deriva)
        detalle[casa] = round(deriva, 4)
    if len(derivas) < CASAS_MINIMAS:
        return None

    media = sum(derivas) / len(derivas)
    de_acuerdo = sum(1 for d in derivas if (d > 0) == (media > 0))
    if abs(media) < UMBRAL_MOVIMIENTO or de_acuerdo < CASAS_MINIMAS:
        sentido, texto = 'estable', 'el precio no se ha movido'
    elif media < 0:
        sentido = 'a_favor'
        texto = (f'el precio se ha acortado un {abs(media)*100:.1f} % desde la '
                 f'apertura en {de_acuerdo} de {len(derivas)} casas: está '
                 f'entrando dinero en este lado')
    else:
        sentido = 'en_contra'
        texto = (f'el precio se ha alargado un {media*100:.1f} % desde la '
                 f'apertura en {de_acuerdo} de {len(derivas)} casas: el dinero '
                 f'va al otro lado')
    return {'sentido': sentido, 'deriva': round(media, 4),
            'n_casas': len(derivas), 'de_acuerdo': de_acuerdo,
            'por_casa': detalle, 'texto': texto}


# ---------------------------------------------------------------------------
# 2. Las noticias que sí son un dato: quién juega
# ---------------------------------------------------------------------------
def alineacion(home: str, away: str, fecha: str = '') -> Optional[Dict]:
    """
    Si hay alineación CONFIRMADA de este partido, o sólo el once del último.

    La distinción la hace el propio fichero (`tipo: lastStarting11` y su
    `aviso`), y es la que importa: un once probable copiado del partido
    anterior no es una noticia, es una suposición.
    """
    datos = _leer(FICHERO_ALINEACIONES).get('alineaciones') or {}
    h, a = _llano(home), _llano(away)
    for clave, v in datos.items():
        trozos = str(clave).split('|')
        if len(trozos) < 3:
            continue
        if _llano(trozos[1]) != h or _llano(trozos[2]) != a:
            continue
        if fecha and trozos[0] and trozos[0] != fecha[:10]:
            continue
        tipo = str(v.get('tipo') or '')
        nivel = NIVEL_ALINEACION.get(tipo, 'desconocida')
        return {
            'nivel': nivel,
            'confirmada': nivel == 'confirmada',
            'tipo': tipo,
            'etiqueta': v.get('etiqueta') or '',
            'aviso': v.get('aviso') or '',
            'n_home': len(v.get('home') or []),
            'n_away': len(v.get('away') or []),
            'texto': TEXTO_ALINEACION.get(nivel, TEXTO_ALINEACION['desconocida']),
        }
    return None


# ---------------------------------------------------------------------------
# 3. Las dos juntas
# ---------------------------------------------------------------------------
def contexto(home: str, away: str, lado: str = 'home',
             fecha: str = '') -> Dict:
    """
    El mercado y las noticias de un partido, y una lectura conjunta.

    La lectura conjunta NO es una recomendación: es una frase que resume dos
    hechos. Lo dice su propio campo `medido: False`.
    """
    mov = movimiento(home, away, lado)
    ali = alineacion(home, away, fecha)
    partes = []
    if mov:
        partes.append(mov['texto'])
    if ali:
        partes.append(ali['texto'])

    # la lectura: sólo hay cuatro combinaciones que dicen algo
    lectura = ''
    if mov and ali and mov['sentido'] != 'estable':
        firme = ali['nivel'] == 'confirmada'
        if mov['sentido'] == 'a_favor' and firme:
            lectura = ('el mercado se mueve a favor y la alineación está '
                       'confirmada: lo que sabe el dinero ya incluye quién '
                       'juega')
        elif mov['sentido'] == 'a_favor':
            lectura = (f'el mercado se mueve a favor, pero {ali["texto"]}: el '
                       f'movimiento puede deshacerse cuando se publique')
        elif firme:
            lectura = ('el mercado se mueve en contra con la alineación ya '
                       'confirmada: el dinero ha visto algo que el modelo no')
        else:
            lectura = (f'el mercado se mueve en contra y {ali["texto"]}: '
                       f'conviene esperar a que salga')
    return {'movimiento': mov, 'alineacion': ali,
            'resumen': ' · '.join(partes), 'lectura': lectura,
            # NUNCA se presenta como señal validada: no lo está, y no puede
            # estarlo hasta que el ledger vuelva a tener cuotas (§6i/§6j).
            'medido': False}
