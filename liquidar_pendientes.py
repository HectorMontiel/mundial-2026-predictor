#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v463 — CIERRA LOS PICKS QUE SE QUEDARON PENDIENTES.

El usuario: «en Mis picks salen partidos de ayer como en juego… las combinadas ya
van varias veces que te digo que se cierren; tiene que ser en el momento en que
ya tenemos los resultados». Medido el 23-oct: 200 picks de días pasados seguían
«pendiente» en la base (fútbol, NHL, tenis; 10-30 por día). Causa: el exportador
sólo revisa los partidos de HOY y AYER con el cálculo del día; si en ese momento no
tenía el resultado (ligas que su fuente no publica a tiempo), el pick se quedaba
pendiente PARA SIEMPRE: nadie lo volvía a mirar. Y con él, cada combinada que lo
llevaba.

Aquí, en cada pasada, ANTES de subir los picks:
  1. se piden a la base los pendientes de los últimos 10 días que ya debieron terminar;
  2. el resultado final sale de ESPN (si el pick tiene su partido de ESPN) y, si no,
     del feed de terminados de Flashscore (fútbol y tenis);
  3. se califica con la MISMA regla que la IA (`ia_gemini.liquidar`), con córners y
     tarjetas reales cuando el pick los necesita; si no se puede calificar, se deja;
  4. se pone en la base y en los picks que esta pasada va a subir (para que el
     upsert no lo vuelva a dejar pendiente). Las combinadas se liquidan después.
Sólo con el partido TERMINADO según la fuente. Nunca lanza.
"""
import datetime as dt
import json
import logging
import os
import re
import unicodedata
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger('liquidar_pendientes')
ESPN = 'https://site.api.espn.com/apis/site/v2/sports/%s/summary'
FS_DIA = 'https://global.flashscore.ninja/2/x/feed/f_%d_%d_3_es-mx_1'
FS_DEP = {'Fútbol': 1, 'Tenis': 2}
DIAS = 10
# horas desde el inicio para darlo por terminado (si la fuente no dice lo contrario)
DURA = {'Fútbol': 2.5, 'NHL': 3.5, 'NBA': 3.0, 'NFL': 4.0, 'MLB': 4.0, 'Tenis': 4.0}


def _norm(s) -> set:
    t = unicodedata.normalize('NFKD', str(s or '')).encode('ascii', 'ignore').decode().lower()
    return {w for w in re.split(r'[^a-z0-9]+', t) if w and w not in ('fc', 'cf', 'sc', 'cd', 'ud', 'club', 'de', 'the', 'afc', 'fk', 'sk', 'ac')}


def _parecido(a, b) -> float:
    x, y = _norm(a), _norm(b)
    return len(x & y) / min(len(x), len(y)) if x and y else 0.0


def _orden(home: str, away: str, a: str, b: str, gh, ga) -> Optional[Tuple]:
    """(goles de A, goles de B) según qué equipo de la fuente es cuál de nuestro «A vs B»."""
    directo, vuelta = _parecido(a, home) + _parecido(b, away), _parecido(a, away) + _parecido(b, home)
    if max(directo, vuelta) < 1.0:
        return None
    return (gh, ga) if directo >= vuelta else (ga, gh)


def _espn(ruta_id: str, a: str, b: str, sesion) -> Optional[Dict]:
    """{g, corners, tarjetas} del partido de ESPN si ya terminó; None si no."""
    try:
        ruta, eid = str(ruta_id).split(':', 1)
        d = sesion.get(ESPN % ruta, params={'event': eid}, timeout=20).json()
        comp = ((d.get('header') or {}).get('competitions') or [{}])[0]
        tipo = (comp.get('status') or {}).get('type') or {}
        if not (tipo.get('completed') or tipo.get('state') == 'post'):
            return None
        cs = comp.get('competitors') or []
        h = next((c for c in cs if c.get('homeAway') == 'home'), None)
        w = next((c for c in cs if c.get('homeAway') == 'away'), None)
        if not h or not w:
            return None
        g = _orden(h['team'].get('displayName'), w['team'].get('displayName'), a, b, int(float(h.get('score') or 0)), int(float(w.get('score') or 0)))
        if g is None:
            return None
        cor, tar = [], []
        for t in ((d.get('boxscore') or {}).get('teams') or []):
            st = {s.get('name'): s.get('displayValue') for s in t.get('statistics') or []}
            try:
                if st.get('wonCorners') is not None:
                    cor.append(int(float(st['wonCorners'])))
                if st.get('yellowCards') is not None:
                    tar.append(int(float(st['yellowCards'])) + int(float(st.get('redCards') or 0)))
            except Exception:
                pass
        return {'g': g, 'corners': sum(cor) if len(cor) == 2 else None, 'tarjetas': sum(tar) if len(tar) == 2 else None, 'fuente': 'espn'}
    except Exception as e:
        logger.debug('[liquidar] espn %s: %s', ruta_id, e)
        return None


_FS: Dict = {}


def _flashscore(deporte: str, ini: dt.datetime, a: str, b: str, sesion) -> Optional[Dict]:
    dep = FS_DEP.get(deporte)
    if not dep:
        return None
    try:
        import resultados_flashscore as rf
        hoy = dt.datetime.now(dt.timezone.utc).date()
        off = (ini.date() - hoy).days
        mejor, puntos = None, 0.0
        for o in (off, off - 1, off + 1):
            if o > 0 or o < -7:
                continue
            k = (dep, o)
            if k not in _FS:
                r = sesion.get(FS_DIA % (dep, o), headers={'x-fsign': 'SW9D1eZo', 'Referer': 'https://www.flashscore.com/', 'User-Agent': 'Mozilla/5.0'}, timeout=25)
                _FS[k] = rf._partidos(r.text, '', '') if r.ok else []
            for m in _FS[k]:
                p = max(_parecido(a, m['home']) + _parecido(b, m['away']), _parecido(a, m['away']) + _parecido(b, m['home']))
                if p > puntos:
                    puntos, mejor = p, m
        if not mejor or puntos < 1.5:
            return None
        g = _orden(mejor['home'], mejor['away'], a, b, mejor['gh'], mejor['ga'])
        return {'g': g, 'corners': None, 'tarjetas': None, 'fuente': 'flashscore'} if g else None
    except Exception as e:
        logger.debug('[liquidar] flashscore %s vs %s: %s', a, b, e)
        return None


def _utc(s) -> Optional[dt.datetime]:
    try:
        x = dt.datetime.fromisoformat(str(s).replace(' ', 'T').replace('Z', '+00:00'))
        return x if x.tzinfo else x.replace(tzinfo=dt.timezone.utc)
    except Exception:
        return None


def calificar(p: Dict, res: Dict) -> Optional[str]:
    """'verde' / 'roja' con el resultado final; None si la regla no lo puede calificar."""
    import ia_gemini
    a, _, b = str(p.get('partido') or '').partition(' vs ')
    ok = ia_gemini.liquidar(p.get('apuesta'), a.strip(), b.strip(), res['g'], res.get('corners'), res.get('tarjetas'))
    return None if ok is None else ('verde' if ok else 'roja')


def cerrar(locales: List[Dict], url: Optional[str] = None, key: Optional[str] = None, sesion=None) -> int:
    """Cierra los pendientes que ya terminaron. Pone el resultado en la base y en
    `locales` (los picks que esta pasada va a subir). Devuelve cuántos cerró."""
    url, key = url or os.environ.get('SUPABASE_URL'), key or os.environ.get('SUPABASE_SERVICE_KEY')
    if not url or not key:
        return 0
    try:
        import requests
        sesion = sesion or requests.Session()
        H = {'apikey': key, 'Authorization': 'Bearer ' + key}
        ahora = dt.datetime.now(dt.timezone.utc)
        r = sesion.get(url.rstrip('/') + '/rest/v1/picks', headers=H, timeout=30, params={
            'select': 'id,partido,apuesta,deporte,inicio,espn,tipo', 'estado': 'eq.pendiente',
            'inicio': 'gte.' + (ahora - dt.timedelta(days=DIAS)).isoformat(), 'limit': 2000})
        pend = r.json() if r.ok else []
        pend = [p for p in pend if isinstance(p, dict) and p.get('tipo') not in ('analisis', 'combinada') and ' vs ' in str(p.get('partido') or '')
                and _utc(p.get('inicio')) and ahora - _utc(p['inicio']) > dt.timedelta(hours=DURA.get(p.get('deporte'), 3.0))]
        if not pend:
            return 0
        # el texto real de los premium (el público va tapado)
        ids = [p['id'] for p in pend]
        reales = {}
        for i in range(0, len(ids), 150):
            rp = sesion.get(url.rstrip('/') + '/rest/v1/picks_premium', headers=H, timeout=30,
                            params={'select': 'id,apuesta', 'id': 'in.(%s)' % ','.join(ids[i:i + 150])})
            for x in (rp.json() if rp.ok else []):
                reales[x['id']] = x['apuesta']
        por_partido: Dict = {}
        cerrados = {}
        for p in pend:
            p = dict(p, apuesta=reales.get(p['id']) or p.get('apuesta'))
            a, _, b = p['partido'].partition(' vs ')
            k = (p.get('espn') or '', p['partido'], str(p['inicio'])[:10])
            if k not in por_partido:
                res = _espn(p['espn'], a.strip(), b.strip(), sesion) if p.get('espn') else None
                if res is None:
                    res = _flashscore(p.get('deporte'), _utc(p['inicio']), a.strip(), b.strip(), sesion)
                por_partido[k] = res
            res = por_partido[k]
            if not res:
                continue
            e = calificar(p, res)
            if e:
                cerrados[p['id']] = (e, '%d-%d' % tuple(res['g']))
        n = 0
        cuando = ahora.isoformat()
        for pid, (e, marc) in cerrados.items():
            u = sesion.patch(url.rstrip('/') + '/rest/v1/picks', headers=dict(H, Prefer='return=minimal'), timeout=30,
                             params={'id': 'eq.' + pid, 'estado': 'eq.pendiente'}, json={'estado': e, 'marcador': marc, 'actualizado': cuando})
            n += bool(u.ok)
        for f in locales or []:                # que el upsert de esta pasada no lo vuelva a dejar pendiente
            if f.get('id') in cerrados and f.get('estado') in ('pendiente', 'vivo', None):
                f['estado'], f['marcador'] = cerrados[f['id']]
        logger.info('[liquidar] %d pendientes revisados, %d cerrados', len(pend), n)
        return n
    except Exception as e:
        logger.warning('[liquidar] no se cerraron los pendientes: %s', e)
        return 0


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    print('cerrados:', cerrar([]))
