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
