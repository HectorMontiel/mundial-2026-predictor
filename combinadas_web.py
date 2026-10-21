# -*- coding: utf-8 -*-
"""
v396 — COMBINADAS DEL DÍA PARA LA PÁGINA: de cada deporte y mezcladas.

El usuario: «quiero que hagas combinadas tanto de varios deportes como de los
deportes por separado, de acuerdo a lo que tenemos en el modelo y lo que esté
diciendo la IA».

CÓMO SE ARMAN
  · patas: picks pendientes que empiezan en 20 min a 30 h, de partidos
    distintos, con cuota ≥ 1,10 y probabilidad ≥ PROB_MIN; sin errores de cuota
    (son de riesgo alto a propósito).
  · la IA hace de FRENO: una pata que la IA ve «en contra» no entra. NO se usa
    para subir patas: el 17-oct sólo tenía 7 veredictos «a favor» calificados,
    muy poca muestra para fiarse (cuando la haya, se mide y se decide).
  · se elige la combinación de MAYOR probabilidad conjunta (producto: partidos
    distintos son independientes) dentro del rango de cuota de cada tipo:
        combinada ............ 2 patas, cuota total 1,30 - 1,60
        combinada cuota alta . 3 patas, cuota total 1,80 - 2,60
  · una por deporte con patas suficientes y una «Mixta» (2+ deportes).

LO QUE YA EMPEZÓ (O YA SE PAGÓ) NO SE TOCA: una combinada con alguna pata ya
empezada, o que alguien desbloqueó con monedas, queda fija (su verde o roja sale de sus patas); las que aún no empiezan se rehacen en
cada pasada con lo último del modelo. Así el historial mide lo que se enseñó.

Ojo, lo medido (v332): combinar no mejora el resultado; la probabilidad
conjunta siempre es MENOR que la de cada pata, y la página la enseña tal cual.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import logging
from itertools import combinations
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

PROB_MIN = 0.78
# v420 — «las de 2 patas están siendo poco eficientes (6-6, 50 %); deberían
# acertar más que las de 3». La causa: la cuota total mínima de 1,30 dejaba
# FUERA a los mejores picks (dos 💎 a ~1,12 dan 1,25) y obligaba a armarla con
# patas más flojas. Simulado sobre los 1.219 picks liquidados del 9 al 21-oct
# (cada día con lo de ese día y la calibración sólo de los días ANTERIORES):
#     actual (prob ≥ 0,78, cuota 1,30-1,60) ...... 44,8 % (mitades 67 / 29)
#     sólo 💎/🔷, por acierto REAL, 1,20-1,60 ..... 82,1 % (mitades 83 / 81),
#                                     ROI +3,5 por $100, p5 frente a la actual +10,7 pts
#     (por la prob. del modelo en vez del acierto real: 67,9 %; no se usa)
# Las de 3 patas no mejoraron con ningún cambio (siguen igual).
TIPOS = {
    'combinada': {'patas': 2, 'cuota': (1.20, 1.60), 'solo_altos': True, 'por_acierto': True},
    'alta': {'patas': 3, 'cuota': (1.80, 2.60)},
}


def nivel(p: Dict) -> str:
    """El mismo nivel que la página (`web/app.js`)."""
    if p.get('elige'):
        return 'Diamante'
    pr = float(p.get('prob') or 0)
    return 'Platino' if pr >= 0.85 else ('Oro' if pr >= 0.80 else 'Plata')


def calibracion(liquidados: List[Dict]) -> Dict:
    """v420 — el acierto REAL por (nivel, deporte) y por nivel, con un empuje
    hacia el 80 % para que poca muestra no mande (como en la simulación)."""
    g: Dict = {}
    for p in liquidados:
        if p.get('tipo') in ('error', 'analisis') or p.get('estado') not in ('verde', 'roja'):
            continue
        for k in ((nivel(p), p.get('deporte')), nivel(p)):
            a = g.setdefault(k, [0, 0])
            a[0] += p.get('estado') == 'verde'
            a[1] += 1
    return {k: (a + 8) / (n + 10) for k, (a, n) in g.items()}
CDMX = dt.timezone(dt.timedelta(hours=-6))
POZO = 40            # las mejores patas por alcance (C(40,3) ≈ 10 mil: instantáneo)


def _utc(s) -> Optional[dt.datetime]:
    try:
        d = dt.datetime.fromisoformat(str(s).replace(' ', 'T').replace('Z', '+00:00')[:25])
        return d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)
    except Exception:
        return None


def _en_contra(p: Dict, ia: Dict) -> bool:
    a = ia.get(p.get('partido')) or {}
    for v in a.get('veredictos') or []:
        if str(v.get('apuesta') or '').strip() == str(p.get('_real') or p.get('apuesta') or '').strip():
            return v.get('opinion') == 'en_contra'
    return False


def _a_favor(p: Dict, ia: Dict) -> bool:
    a = ia.get(p.get('partido')) or {}
    return any(str(v.get('apuesta') or '').strip() == str(p.get('_real') or p.get('apuesta') or '').strip()
               and v.get('opinion') == 'a_favor' for v in a.get('veredictos') or [])


def patas(picks: List[Dict], ia: Dict, ahora: dt.datetime) -> List[Dict]:
    out = []
    for p in picks:
        ini = _utc(p.get('inicio'))
        if (p.get('estado') != 'pendiente' or p.get('tipo') == 'error' or ini is None
                or not (ahora + dt.timedelta(minutes=20) < ini <= ahora + dt.timedelta(hours=30))):
            continue
        try:
            c, pr = float(p.get('cuota') or 0), float(p.get('prob') or 0)
        except (TypeError, ValueError):
            continue
        if c < 1.10 or pr < PROB_MIN or _en_contra(p, ia):
            continue
        out.append(p)
    return out


def _mejor(cands: List[Dict], n: int, cmin: float, cmax: float, mixta: bool,
           puntaje=None) -> Optional[List[Dict]]:
    puntaje = puntaje or (lambda p: float(p['prob']))
    cands = sorted(cands, key=lambda p: -puntaje(p))[:POZO]
    mejor, pm = None, 0.0
    for combo in combinations(cands, n):
        if len({p['partido'] for p in combo}) < n:
            continue
        if mixta and len({p.get('deporte') for p in combo}) < 2:
            continue
        c = 1.0
        for p in combo:
            c *= float(p['cuota'])
        if not (cmin <= c <= cmax):
            continue
        pj = 1.0
        for p in combo:
            pj *= puntaje(p)
        if pj > pm:
            mejor, pm = list(combo), pj
    return mejor


def _fila(fecha: str, alcance: str, tipo: str, combo: List[Dict], ia: Dict) -> Dict:
    combo = sorted(combo, key=lambda p: str(p.get('inicio')))
    cuota, prob = 1.0, 1.0
    for p in combo:
        cuota *= float(p['cuota'])
        prob *= float(p['prob'])
    return {
        'id': hashlib.sha1(('%s|%s|%s' % (fecha, alcance, tipo)).encode('utf-8')).hexdigest()[:20],
        'fecha': fecha, 'alcance': alcance, 'tipo': tipo,
        'cuota': round(cuota, 3), 'prob': round(prob, 3),
        'premium': any(p.get('premium') for p in combo),
        'inicio': str(combo[0].get('inicio')),
        'patas': [{'id': p['id'], 'partido': p.get('partido'), 'deporte': p.get('deporte'), 'liga': p.get('liga'),
                   'apuesta': p.get('apuesta'), 'cuota': p.get('cuota'), 'prob': p.get('prob'),
                   'inicio': p.get('inicio'), 'ia': 'a_favor' if _a_favor(p, ia) else None} for p in combo],
        'estado': 'pendiente',
    }


def armar(picks: List[Dict], ia: Dict, ahora: Optional[dt.datetime] = None,
          cal: Optional[Dict] = None) -> List[Dict]:
    """Las combinadas nuevas de esta pasada (ver la cabecera)."""
    ahora = ahora or dt.datetime.now(dt.timezone.utc)
    cal = cal if cal is not None else calibracion(picks)
    acierto = lambda p: cal.get((nivel(p), p.get('deporte')), cal.get(nivel(p), 0.8))
    out = []
    por_dia: Dict[str, List[Dict]] = {}
    for p in patas(picks, ia, ahora):       # cada día con sus partidos: no se mezclan hoy y mañana
        por_dia.setdefault(_utc(p['inicio']).astimezone(CDMX).date().isoformat(), []).append(p)
    for fecha, pool in sorted(por_dia.items()):
        deportes = sorted({p.get('deporte') for p in pool if p.get('deporte')})
        for alcance in deportes + ['Mixta']:
            cands = pool if alcance == 'Mixta' else [p for p in pool if p.get('deporte') == alcance]
            for tipo, t in TIPOS.items():
                cc = [p for p in cands if p.get('elige') or float(p.get('prob') or 0) >= 0.85] if t.get('solo_altos') else cands
                combo = _mejor(cc, t['patas'], t['cuota'][0], t['cuota'][1], alcance == 'Mixta',
                               acierto if t.get('por_acierto') else None)
                if combo:
                    out.append(_fila(fecha, alcance, tipo, combo, ia))
    return out


def estado_de(patas_: List[Dict], estados: Dict[str, str]) -> str:
    """Verde si todas verde; roja si alguna roja; nula si alguna nula y el resto
    verde (se paga como si esa pata no estuviera, pero aquí no se cuenta)."""
    es = [estados.get(p['id'], 'pendiente') for p in patas_]
    if any(e == 'roja' for e in es):
        return 'roja'
    if all(e in ('verde', 'nula') for e in es):
        return 'nula' if any(e == 'nula' for e in es) else 'verde'
    return 'vivo' if any(e in ('verde', 'vivo') for e in es) else 'pendiente'


def subir(picks: List[Dict], url: str, key: str, ahora: Optional[dt.datetime] = None) -> int:
    """Lee la IA y lo ya publicado, arma las nuevas, congela las empezadas y
    pone el estado de cada una a partir de sus patas."""
    if not picks:
        logger.warning('[combinadas] no se recibieron picks; se conserva lo publicado')
        return 0
    import requests
    ahora = ahora or dt.datetime.now(dt.timezone.utc)
    base = url.rstrip('/') + '/rest/v1/'
    hdr = {'apikey': key, 'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'}
    hoy = ahora.astimezone(CDMX).date()
    desde = (hoy - dt.timedelta(days=2)).isoformat()
    ia = {}
    r = requests.get(base + 'ia_analisis', headers=hdr, timeout=30,
                     params={'select': 'partido,veredictos', 'fecha': 'gte.' + desde, 'limit': 5000})
    if not r.ok:
        raise RuntimeError('No se pudo leer ia_analisis para validar las combinadas: HTTP %s' % r.status_code)
    ia = {x['partido']: x for x in r.json()}
    r = requests.get(base + 'combinadas', headers=hdr, timeout=30,
                     params={'select': '*', 'fecha': 'gte.' + desde, 'limit': 2000})
    if not r.ok:
        logger.error('[combinadas] no se pudo leer la tabla: %s %s', r.status_code, r.text[:200])
        raise RuntimeError('No se pudo leer combinadas; no se puede publicar un estado consistente')
    viejas = r.json()
    # el estado de cada pata: de esta pasada o de la base
    estados = {p['id']: p.get('estado') for p in picks}
    faltan = sorted({x['id'] for c in viejas for x in (c.get('patas') or []) if x['id'] not in estados})
    for i in range(0, len(faltan), 150):
        rr = requests.get(base + 'picks', headers=hdr, timeout=30,
                          params={'select': 'id,estado', 'id': 'in.(%s)' % ','.join(faltan[i:i + 150])})
        if not rr.ok:
            raise RuntimeError('No se pudieron leer las patas de combinadas desde picks: HTTP %s' % rr.status_code)
        estados.update({x['id']: x.get('estado') for x in rr.json()})
    empezo = lambda c: any((_utc(x.get('inicio')) or ahora) <= ahora for x in c.get('patas') or [])
    # v397 — lo que alguien ya PAGÓ con monedas tampoco se rehace ni se borra
    # (perdería lo que compró); queda fijo igual que lo ya empezado
    rr = requests.get(base + 'desbloqueos_combinada', headers=hdr, timeout=30,
                      params={'select': 'combinada', 'limit': 10000})
    pagadas = {x['combinada'] for x in rr.json()} if rr.ok else None
    if pagadas is None:
        logger.warning('[combinadas] no se pudieron consultar los desbloqueos; se conservarán las combinadas existentes')
    if pagadas is None:                 # sin poder saberlo, no se toca nada que no haya empezado
        pagadas = {c['id'] for c in viejas}
    filas, fijas = [], set()
    for c in viejas:
        if c['id'] in pagadas and not empezo(c):
            fijas.add(c['id'])
            continue
        if empezo(c):
            fijas.add(c['id'])
            nuevo = estado_de(c.get('patas') or [], estados)
            if nuevo != c.get('estado'):
                filas.append({'id': c['id'], 'fecha': c['fecha'], 'alcance': c['alcance'], 'tipo': c['tipo'],
                              'estado': nuevo, 'actualizado': ahora.isoformat()})
    # v420 — el acierto real de los últimos 30 días (para elegir las patas de las de 2)
    cal = None
    try:
        rr = requests.get(base + 'picks', headers=hdr, timeout=30,
                          params={'select': 'elige,prob,tipo,deporte,estado', 'estado': 'in.(verde,roja)',
                                  'fecha': 'gte.' + (hoy - dt.timedelta(days=30)).isoformat(), 'limit': 20000})
        if rr.ok:
            cal = calibracion(rr.json())
    except Exception as e:
        logger.warning('[combinadas] sin calibración de la base (%s): se usa la de esta pasada', e)
    nuevas = [c for c in armar(picks, ia, ahora, cal) if c['id'] not in fijas]
    for c in nuevas:
        c['actualizado'] = ahora.isoformat()
    # lo que hoy ya no tiene combinada (sin patas suficientes) y aún no empezó, se quita
    quitar = [c['id'] for c in viejas if c['id'] not in fijas and c['fecha'] >= hoy.isoformat()
              and c['id'] not in {x['id'] for x in nuevas}]
    n = 0
    up = dict(hdr, Prefer='resolution=merge-duplicates,return=minimal')
    if nuevas:
        rr = requests.post(base + 'combinadas', headers=up, json=nuevas, timeout=30)
        n += len(nuevas) if rr.ok else 0
        if not rr.ok:
            logger.error('[combinadas] %s %s', rr.status_code, rr.text[:200])
            raise RuntimeError('No se pudieron guardar combinadas nuevas: HTTP %s' % rr.status_code)
    for f in filas:
        rr = requests.patch(base + 'combinadas', headers=up, params={'id': 'eq.' + f['id']},
                            json={'estado': f['estado'], 'actualizado': f['actualizado']}, timeout=30)
        if not rr.ok:
            raise RuntimeError('No se pudo actualizar el estado de una combinada: HTTP %s' % rr.status_code)
        n += 1
    if quitar:
        rr = requests.delete(base + 'combinadas', headers=hdr, timeout=30,
                             params={'id': 'in.(%s)' % ','.join(quitar)})
        if not rr.ok:
            raise RuntimeError('No se pudieron retirar combinadas pendientes obsoletas: HTTP %s' % rr.status_code)
    return n
