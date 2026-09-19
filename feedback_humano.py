#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v217 — Feedback humano: qué añade de verdad, qué no, y cómo se gana su peso.

LA PREGUNTA
-----------
«Sería bueno meterle un feedback humano, que puedas refinarla manualmente. ¿Eso
añadiría o no? ¿Y si sí, cómo sería la estructura? ¿Cómo hacemos que aprenda de
los resultados?»

LA RESPUESTA HONESTA, QUE TIENE TRES PARTES DISTINTAS
-----------------------------------------------------
No todo el feedback humano vale lo mismo, y tratarlo como una sola cosa es la
forma de estropear un modelo. Se separan tres tipos, y sólo dos son útiles:

  1. CORREGIR UN DATO  (`dato_malo`) — «este no es el resultado», «esa
     alineación es de otro partido», «este pick se emparejó con el equipo
     equivocado». **Valor alto e inmediato.** El sistema no puede detectar esto
     solo: un dato mal emparejado le parece un dato. Se aplica sin esperar a
     medir nada, porque no es una opinión, es un hecho verificable.

  2. APORTAR INFORMACIÓN QUE EL SISTEMA NO TIENE  (`veto`, `apoyo`) — «sé que
     el portero titular no juega y tu scraper no lo vio». **Valor alto pero
     NO demostrado.** Es exactamente lo que este proyecto no puede medir hasta
     tener registro: se guarda, se mide contra el resultado, y sólo pesa
     cuando demuestre que acierta.

  3. OPINAR SOBRE EL PICK  (`me_gusta`, `no_me_gusta`) — «esto no me
     convence». **Valor bajo y riesgo alto.** Es la misma intuición que el
     mercado ya tiene incorporada y mejor calibrada. Se guarda igual —cuesta
     nada y puede sorprender— pero arranca sin peso ninguno.

LA REGLA QUE HACE QUE ESTO NO ESTROPEE EL MODELO
------------------------------------------------
**El feedback NUNCA toca una probabilidad directamente.** Se guarda al lado,
se liquida contra el resultado real igual que un pick, y se mide:

    ¿los picks que el humano VETÓ acertaron menos que los que dejó pasar?

Si la respuesta es sí y con muestra suficiente, el veto se ha ganado su peso y
`influencia()` deja de devolver cero. Si es que no, se queda a cero y el
registro sirve igual: sabrás que tu intuición no bate a tu modelo, que es un
resultado tan útil como el contrario.

Es la misma puerta que gobierna el resto del proyecto (`activacion_v212.json`,
`riesgo_liga`, el p5 de bootstrap). El humano no es una excepción: es otra
señal que tiene que demostrar que funciona.

POR QUÉ NO SE REENTRENA EL MODELO CON ESTO
------------------------------------------
Porque sería irreversible y no medible. Si el feedback entra como feature de
entrenamiento, deja de poderse contestar «¿acertaba más el modelo antes o
después?». Entra como CAPA, encima, apagable — igual que todo lo demás desde la
v209.
"""

import datetime as _dt
import json
import logging
import os
from typing import Dict, List, Optional

logger = logging.getLogger('feedback_humano')

FICHERO = os.environ.get('FEEDBACK_HUMANO', 'feedback_humano.json')

# Los tres tipos, con su peso INICIAL. Los dos primeros son hechos o
# información; el tercero es opinión y arranca en cero.
TIPOS = {
    'dato_malo':   {'peso_inicial': 1.0, 'clase': 'correccion'},
    'veto':        {'peso_inicial': 0.0, 'clase': 'informacion'},
    'apoyo':       {'peso_inicial': 0.0, 'clase': 'informacion'},
    'me_gusta':    {'peso_inicial': 0.0, 'clase': 'opinion'},
    'no_me_gusta': {'peso_inicial': 0.0, 'clase': 'opinion'},
}

N_MINIMO_PARA_PESAR = 40    # vetos resueltos antes de poder concluir nada
VENTAJA_MINIMA = 0.08       # cuánto tiene que separar el veto para ganar peso

_CACHE: Optional[Dict] = None


# ---------------------------------------------------------------------------
def _leer() -> Dict:
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    _CACHE = {'entradas': [], 'version': 1}
    try:
        if os.path.exists(FICHERO):
            with open(FICHERO, encoding='utf-8') as f:
                d = json.load(f)
            if isinstance(d, dict) and isinstance(d.get('entradas'), list):
                _CACHE = d
    except Exception as e:
        logger.warning('[feedback] no se pudo leer %s: %s', FICHERO, e)
    return _CACHE


def _escribir(doc: Dict) -> bool:
    global _CACHE
    _CACHE = doc
    try:
        import io_atomico
        return bool(io_atomico.escribir_json(FICHERO, doc))
    except Exception as e:
        logger.warning('[feedback] no se pudo escribir %s: %s', FICHERO, e)
        return False


def recargar() -> None:
    global _CACHE
    _CACHE = None


def clave(pick: Dict) -> str:
    """La misma identidad que usa `pronosticos_guardados`, para poder cruzar."""
    p = pick or {}
    return '|'.join([str(p.get('clave_liga') or ''),
                     str(p.get('partido') or ''),
                     str(p.get('fecha') or '')[:10],
                     str(p.get('apuesta') or '')])


# ---------------------------------------------------------------------------
def anotar(pick: Dict, tipo: str, nota: str = '',
           autor: str = 'usuario') -> bool:
    """Registra una intervención humana. NO cambia ninguna probabilidad.

    Es append-only a propósito: el valor de esto está en poder preguntar
    después «¿qué dijo el humano ANTES de saber el resultado?», y eso se
    pierde si las entradas se pueden editar.
    """
    if tipo not in TIPOS:
        logger.warning('[feedback] tipo desconocido: %s', tipo)
        return False
    p = pick or {}
    doc = _leer()
    entrada = {
        'clave': clave(p),
        'tipo': tipo,
        'clase': TIPOS[tipo]['clase'],
        'nota': str(nota or '')[:400],
        'autor': autor,
        'anotado': _dt.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'),
        # la foto del pick EN EL MOMENTO de opinar, para poder liquidarlo
        'partido': p.get('partido'), 'liga': p.get('liga'),
        'clave_liga': p.get('clave_liga'), 'fecha': str(p.get('fecha') or '')[:10],
        'apuesta': p.get('apuesta'), 'mercado': p.get('mercado'),
        'prob': p.get('prob'), 'cuota': p.get('cuota'),
        'resuelto': None,          # lo rellena `liquidar()`
    }
    doc = dict(doc)
    doc['entradas'] = list(doc.get('entradas') or []) + [entrada]
    return _escribir(doc)


def de_pick(pick: Dict) -> List[Dict]:
    """Lo que el humano haya dicho de este pick concreto."""
    k = clave(pick)
    return [e for e in (_leer().get('entradas') or []) if e.get('clave') == k]


def hay_veto(pick: Dict) -> bool:
    return any(e['tipo'] == 'veto' for e in de_pick(pick))


def hay_dato_malo(pick: Dict) -> bool:
    """Los datos marcados como malos SÍ se respetan desde el primer día.

    No es una opinión sobre el pick: es «este dato está mal». Nada que medir.
    """
    return any(e['tipo'] == 'dato_malo' for e in de_pick(pick))


# ---------------------------------------------------------------------------
def liquidar() -> Dict:
    """Cruza cada intervención con lo que acabó pasando.

    Reutiliza el juicio de `fiabilidad_picks`, que a su vez usa la misma
    función que pinta el punto verde o rojo. Tres caminos al mismo veredicto
    acabarían divergiendo.
    """
    try:
        import fiabilidad_picks as fp
    except Exception as e:
        logger.warning('[feedback] sin fiabilidad_picks: %s', e)
        return {'n': 0}

    juzgadas = {}
    for f in fp.juzgar():
        k = '|'.join([str(f.get('clave_liga') or ''),
                      str(f.get('partido') or ''),
                      str(f.get('fecha') or '')[:10],
                      str(f.get('apuesta') or '')])
        juzgadas[k] = f['acierto']

    doc = dict(_leer())
    entradas = []
    n = 0
    for e in (doc.get('entradas') or []):
        e = dict(e)
        acierto = juzgadas.get(e.get('clave'))
        if acierto is not None:
            e['resuelto'] = int(acierto)
            n += 1
        entradas.append(e)
    doc['entradas'] = entradas
    doc['liquidado'] = _dt.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')
    _escribir(doc)
    return {'n': n, 'total': len(entradas)}


def medir() -> Dict:
    """¿El veto humano separa ganadores de perdedores? Con su muestra.

    La comparación correcta NO es «cuánto aciertan los vetados» a secas: hay
    que compararlo contra lo que acertaron los picks equivalentes que el humano
    dejó pasar. Un veto que acierta el 40 % no dice nada si el resto también
    ronda el 40 %.
    """
    try:
        import fiabilidad_picks as fp
    except Exception:
        return {'medible': False, 'motivo': 'falta fiabilidad_picks'}

    todos = fp.juzgar()
    if not todos:
        return {'medible': False, 'motivo': 'no hay picks resueltos todavía'}

    vetados = {e['clave'] for e in (_leer().get('entradas') or [])
               if e.get('tipo') == 'veto'}
    if not vetados:
        return {'medible': False, 'n_vetos': 0,
                'motivo': 'todavía no se ha vetado ningún pick'}

    con, sin = [], []
    for f in todos:
        k = '|'.join([str(f.get('clave_liga') or ''),
                      str(f.get('partido') or ''),
                      str(f.get('fecha') or '')[:10],
                      str(f.get('apuesta') or '')])
        (con if k in vetados else sin).append(f['acierto'])

    if len(con) < N_MINIMO_PARA_PESAR:
        return {'medible': False, 'n_vetos': len(con),
                'motivo': f'hacen falta {N_MINIMO_PARA_PESAR} vetos resueltos '
                          f'y hay {len(con)}'}

    acierto_vetados = sum(con) / len(con)
    acierto_resto = sum(sin) / len(sin) if sin else None
    lo, hi = fp.wilson(sum(con), len(con))
    ventaja = (acierto_resto - acierto_vetados) if acierto_resto is not None else None
    gana = bool(ventaja is not None and ventaja >= VENTAJA_MINIMA
                and hi < acierto_resto)
    return {
        'medible': True,
        'n_vetos': len(con), 'n_resto': len(sin),
        'acierto_vetados': acierto_vetados, 'acierto_resto': acierto_resto,
        'ventaja_del_veto': ventaja,
        'ic90_vetados': [lo, hi],
        'el_veto_se_gana_su_peso': gana,
        'motivo': ('el veto humano separa: lo vetado acierta bastante menos'
                   if gana else
                   'el veto todavía no demuestra separar mejor que el azar'),
    }


def influencia() -> float:
    """Cuánto pesa hoy el veto humano. Cero mientras no se lo gane.

    Devuelve un factor multiplicativo sobre la confianza del pick, NO sobre su
    probabilidad. La probabilidad del modelo no se toca nunca desde aquí.
    """
    m = medir()
    return 0.5 if m.get('el_veto_se_gana_su_peso') else 0.0


def resumen() -> Dict:
    """Para la pantalla: qué hay anotado y en qué estado está."""
    entradas = _leer().get('entradas') or []
    por_tipo: Dict[str, int] = {}
    for e in entradas:
        por_tipo[e.get('tipo', '?')] = por_tipo.get(e.get('tipo', '?'), 0) + 1
    resueltas = sum(1 for e in entradas if e.get('resuelto') is not None)
    return {'total': len(entradas), 'por_tipo': por_tipo,
            'resueltas': resueltas, 'medicion': medir(),
            'influencia': influencia()}


if __name__ == '__main__':
    import sys
    print(json.dumps(resumen(), ensure_ascii=False, indent=1))
    sys.exit(0)
