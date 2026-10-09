#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v343 — LO QUE LA APP DIJO «SE METE» NO DESAPARECE.

El usuario armó un parley la madrugada del 8-oct con lo que daba la tarjeta
(«Goles Flamengo: Más de 0.5», «Fluminense o empate») y a mediodía, en los
mismos partidos, la tarjeta enseñaba otras apuestas. Preguntó por qué, si
está bien o mal, y cómo hacer que lo apostado no cambie.

POR QUÉ CAMBIA (`_v343_historia.py`). El modelo no se movió: lo que se movió
fue el precio de Playdoit, una centésima, y cruzó un corte fijo:

    Santos–Flamengo   «Flamengo mete gol» 1,154 → 1,143   mínimo 1,15 (v335)
    Fluminense        la casa 87,2 % → 88,1 %              Capa 1 hasta 88 %

¿CONGELAR LA PRIMERA? NO (`_v343_estabilidad.py`, `_v343_separa.py`). Con
las decisiones guardadas del 4 al 8-oct, la tarjeta cambió de apuesta en 76
de 133 partidos de fútbol. Liquidadas las dos versiones:

                                  primera          última antes del pitido
    todos                         76,2 %           79,0 %
    sin despliegue de por medio   70,8 % (46/65)   74,6 % (50/67)
    lo que se retiró / lo que entró   63-75 %      76-82 %

La de última hora acierta algo más (no llega al p5: son cinco días), así que
fijar la primera costaría aciertos. Lo que SÍ falla es que lo ya anunciado
se esfume: quien ya apostó no sabe si su apuesta sigue valiendo. Este módulo
guarda TODO lo que se anunció, con su hora y su cuota de entonces, y la
tarjeta lo enseña con su estado; al acabar, con su resultado.

El precálculo lo acumula en cada pasada (`acumular`) y el workflow lo publica
(`anunciadas_dia.json`). La app sólo lo lee.
"""
import datetime as _dt
import json
import logging
import os
from typing import Dict, List, Optional

logger = logging.getLogger('anunciadas')

FICHERO = 'anunciadas_dia.json'
VERSION = 1
# se olvidan los partidos que empezaron hace más de esto
HORAS_MEMORIA = 48
CAMPOS = ('apuesta', 'mercado', 'bloque', 'linea', 'etiqueta', 'cuota',
          'prob', 'prob_meter', 'p_mercado', 'elite')
_CACHE: Dict = {}


def _ruta() -> str:
    return os.environ.get('ANUNCIADAS_FICHERO') or FICHERO


def clave(partido, clave_liga) -> str:
    """El partido, sin la hora: un cambio de horario no es otro partido."""
    return '%s|%s' % (str(partido or ''), str(clave_liga or ''))


def _utc(s) -> Optional[_dt.datetime]:
    try:
        t = _dt.datetime.fromisoformat(str(s).replace('Z', '+00:00'))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=_dt.timezone.utc)


def cargar(ruta: str = '') -> Dict:
    ruta = ruta or _ruta()
    try:
        mt = os.path.getmtime(ruta)
    except OSError:
        return {}
    if _CACHE.get('ruta') == ruta and _CACHE.get('mt') == mt:
        return _CACHE['doc']
    try:
        with open(ruta, encoding='utf-8') as f:
            doc = json.load(f) or {}
    except Exception as e:
        logger.debug('[anunciadas] ilegible: %s', e)
        doc = {}
    _CACHE.update(ruta=ruta, mt=mt, doc=doc)
    return doc


def acumular(doc_pronostico: Dict, ruta: str = '',
             ahora: Optional[_dt.datetime] = None) -> int:
    """Añade al fichero las «meter» de la tarjeta de este precálculo que aún
    no estaban. Lo ya anunciado no se reescribe: se queda con la hora y la
    cuota de la PRIMERA vez. Devuelve cuántas añadió. Nunca lanza."""
    ruta = ruta or _ruta()
    ahora = ahora or _dt.datetime.now(_dt.timezone.utc)
    try:
        viejo = {}
        if os.path.exists(ruta):
            with open(ruta, encoding='utf-8') as f:
                viejo = json.load(f) or {}
        partidos = dict(viejo.get('partidos') or {})
        listas = (((doc_pronostico or {}).get('decisiones') or {})
                  .get('listas') or {})
        n = 0
        for lista in ('pronosticos', 'solo_mercado'):
            for x in listas.get(lista) or []:
                if not isinstance(x, dict):
                    continue
                llave = x.get('llave') or []
                if len(llave) < 3:
                    continue
                ini = _utc(llave[1])
                if ini is not None and ini <= ahora:
                    continue           # lo que se anuncia ya empezado no cuenta
                recos = x.get('recomendadas_tarjeta') or x.get('recomendadas') or []
                met = [r for r in recos if r.get('veredicto_vp') == 'meter'][:2]
                if not met:
                    continue
                k = clave(llave[0], llave[2])
                ent = partidos.setdefault(k, {'inicio': llave[1], 'apuestas': []})
                ent['inicio'] = llave[1]
                ya = {a.get('apuesta') for a in ent['apuestas']}
                for r in met:
                    if r.get('apuesta') in ya:
                        continue
                    ent['apuestas'].append(dict(
                        {c: r.get(c) for c in CAMPOS},
                        desde=ahora.strftime('%Y-%m-%dT%H:%M:%SZ')))
                    n += 1
        # v346 — Y LA CAPA 1 (🏆 lo mejor del modelo y 🔷 más riesgo), que
        # también cambia con las cuotas: el usuario armó una pata de 🔷
        # (Millonarios @1,76) que al pitido ya no estaba en la lista.
        n += _acumular_capa1(doc_pronostico, partidos, ahora)
        # se olvida lo que empezó hace más de dos días
        limite = ahora - _dt.timedelta(hours=HORAS_MEMORIA)
        partidos = {k: v for k, v in partidos.items()
                    if (_utc(v.get('inicio')) or ahora) >= limite}
        with open(ruta, 'w', encoding='utf-8') as f:
            json.dump({'version': VERSION,
                       'actualizado': ahora.strftime('%Y-%m-%dT%H:%M:%SZ'),
                       'partidos': partidos}, f, ensure_ascii=False)
        logger.info('[anunciadas] %d nuevas; %d partidos en memoria', n,
                    len(partidos))
        return n
    except Exception as e:
        logger.warning('[anunciadas] no se pudo acumular: %s', e)
        return 0


def _acumular_capa1(doc: Dict, partidos: Dict, ahora: _dt.datetime) -> int:
    """Lo que la Capa 1 enseñaba en esta pasada, con su hora y su cuota.

    v351 — los CUATRO grupos y no sólo 🏆 y 🔷: también 💰 los errores de
    precio contra Pinnacle (`datos.capa1`, los que la app da por buenos) y 🎯
    las probables con buena cuota (`probables.barrer`). El usuario: «todo lo
    que está en Capa 1 debe tener si se ganó o no». Los errores son casi
    siempre de ligas sin modelo propio (Etiopía, Malta, básquet islandés), que
    no pasan por el archivo de partidos: por eso cada entrada lleva su
    deporte, su liga y su hora, para que `capa1_resultados` la liquide sola.
    """
    try:
        import lo_mejor as lm
    except Exception:
        return 0
    datos = (doc or {}).get('datos') or {}
    n = 0

    def _poner(p: Dict, e: Dict, nivel: str) -> int:
        ini = _utc(p.get('inicio'))
        if ini is not None and ini <= ahora:
            return 0
        k = clave(p.get('partido'), p.get('clave_liga'))
        ent = partidos.setdefault(k, {'inicio': p.get('inicio'), 'apuestas': []})
        ent.setdefault('inicio', p.get('inicio'))
        ent.setdefault('partido', p.get('partido'))
        ent.setdefault('deporte', str(p.get('deporte') or 'Fútbol'))
        ent.setdefault('liga', p.get('liga'))
        c1 = ent.setdefault('capa1', [])
        if any(x.get('apuesta') == e['apuesta'] and x.get('nivel') == nivel
               for x in c1):
            return 0
        c1.append({'apuesta': e['apuesta'], 'mercado': e.get('mercado'),
                   'bloque': e.get('bloque') or 'resultado',
                   'etiqueta': e.get('etiqueta') or 'Resultado',
                   'cuota': e.get('cuota'), 'prob': e.get('prob'),
                   'p_mercado': e.get('p_mercado'), 'nivel': nivel,
                   'desde': ahora.strftime('%Y-%m-%dT%H:%M:%SZ')})
        return 1

    for p in (datos.get('pronosticos') or []):
        if not isinstance(p, dict) or p.get('jugado'):
            continue
        for nivel, fn in (('🏆', lm.del_pick), ('🔷', lm.del_pick_riesgo)):
            e = fn(p)
            if e:
                n += _poner(p, e, nivel)
    # 💰 los errores de precio que la app enseña (los «sin validar» no)
    for p in (datos.get('capa1') or []):
        if not isinstance(p, dict) or p.get('validado') is False                 or not p.get('apuesta') or not p.get('partido'):
            continue
        n += _poner(p, {'apuesta': p['apuesta'], 'mercado': p.get('mercado'),
                        'cuota': p.get('cuota'), 'prob': p.get('prob')}, '💰')
    # 🎯 las probables con buena cuota, del mismo tablero que la app (sólo
    # con un precálculo de verdad: sin pronósticos no hay de qué día hablar)
    try:
        import probables as _pb
        for p in (_pb.barrer(datos.get('pronosticos')) or []
                  if datos.get('pronosticos') else []):
            if isinstance(p, dict) and p.get('apuesta') and p.get('partido'):
                n += _poner(p, {'apuesta': p['apuesta'],
                                'mercado': p.get('mercado') or '1X2',
                                'cuota': p.get('cuota'), 'prob': p.get('prob')},
                            '🎯')
    except Exception as e:
        logger.debug('[anunciadas] probables: %s', e)
    return n


def capa1_del_partido(pick: Dict, ruta: str = '') -> List[Dict]:
    """Lo que la Capa 1 anunció de este partido (🏆 y 🔷), por orden."""
    ent = ((cargar(ruta).get('partidos') or {})
           .get(clave((pick or {}).get('partido'), (pick or {}).get('clave_liga')))
           or {})
    return [dict(x) for x in ent.get('capa1') or []]


def del_partido(pick: Dict, ruta: str = '') -> List[Dict]:
    """Todo lo que se anunció «se mete» de este partido, por orden."""
    ent = ((cargar(ruta).get('partidos') or {})
           .get(clave((pick or {}).get('partido'), (pick or {}).get('clave_liga')))
           or {})
    return [dict(a) for a in ent.get('apuestas') or []]


def hora_cdmx(desde: str) -> str:
    """'08/10 01:24' en hora de CDMX."""
    t = _utc(desde)
    if t is None:
        return ''
    try:
        import horario
        txt = horario.hora(t)
        dia = horario.fecha(t)
        if txt and dia:
            return '%s/%s %s' % (dia[8:10], dia[5:7], txt)
    except Exception:
        pass
    t = t - _dt.timedelta(hours=6)
    return t.strftime('%d/%m %H:%M')


# v346 — LAS QUE LLEVAN RATO SIN CAMBIAR ACIERTAN MÁS (`_v346_estable.py`,
# 210 «meter» de fútbol del 4 al 9-oct, la versión que había al pitido):
#
#     recién aparecida (1 foto)          22   72,7 %
#     2-3 fotos                          27   77,8 %
#     4 fotos o más (≈ 6 h o más)       161   80,1 %   en las dos mitades
#
# +4,5 pts, todavía sin p5 > 0 (son pocas las recientes). No cambia QUÉ se
# mete: sólo lo dice, para quien apuesta con tiempo (y la v346 midió que
# fijar la primera versión acierta MENOS que esperar a la última:
# `_v346_fijada.py`, 77,5 contra 79,7 %).
HORAS_ESTABLE = 6.0


def horas_anunciada(pick: Dict, apuesta: str, ruta: str = '',
                    ahora: Optional[_dt.datetime] = None) -> Optional[float]:
    """Horas desde que esta apuesta se anunció por primera vez, o None."""
    for a_ in del_partido(pick, ruta):
        if a_.get('apuesta') == apuesta:
            t = _utc(a_.get('desde'))
            if t is None:
                return None
            ahora = ahora or _dt.datetime.now(_dt.timezone.utc)
            return max(0.0, (ahora - t).total_seconds() / 3600.0)
    return None


def estado(anunciada: Dict, recos: List[Dict]) -> Dict:
    """Cómo está AHORA una apuesta que se anunció antes y ya no se enseña.

    `recos`: todas las recomendadas de la tarjeta de ahora, con su veredicto.
    Devuelve {'tono': 'ok'|'aviso', 'texto': ...}."""
    ap = anunciada.get('apuesta')
    cur = next((r for r in (recos or []) if r.get('apuesta') == ap), None)
    if cur is not None and cur.get('veredicto_vp') == 'meter':
        return {'tono': 'ok', 'texto': 'sigue entrando; quedó detrás de las de arriba'}
    trozos = []
    if cur is not None:
        c0, c1 = anunciada.get('cuota'), cur.get('cuota')
        p0 = anunciada.get('prob_meter') or anunciada.get('prob')
        p1 = cur.get('prob_meter') or cur.get('prob')
        if c0 and c1 and abs(float(c1) - float(c0)) >= 0.005:
            trozos.append('cuota %.2f → %.2f' % (float(c0), float(c1)))
        if p0 and p1 and abs(float(p1) - float(p0)) >= 0.005:
            trozos.append('%.0f %% → %.0f %%' % (100 * float(p0), 100 * float(p1)))
    return {'tono': 'aviso',
            'texto': 'ya no entra' + ((': ' + ', '.join(trozos)) if trozos
                                      else ': con los datos de ahora ya no la '
                                      'recomienda')}
