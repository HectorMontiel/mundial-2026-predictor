#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v378 — EL NÚMERO DE ESPN DE CADA PICK, PARA LO EN VIVO DEL SITIO WEB.

El usuario: «quiero que todo sea en vivo… estadísticas tipo SofaScore de
cuando el partido está en vivo, cuántos tiros van». ESPN da marcador, minuto,
tiros, a puerta, córners, posesión, tarjetas y goles con su minuto, y deja
leerlo DESDE LA PÁGINA (responde con «Access-Control-Allow-Origin: *»): el
sitio no necesita servidor para lo en vivo. Lo único difícil es saber qué
partido de ESPN es cada pick (los nombres no siempre coinciden); eso se hace
aquí, en Python, una vez por pasada: por hora de inicio (±3 h) y parecido de
los dos nombres. También deja los escudos.

Una consulta por deporte y día (`dates=AAAAMMDD`, NUNCA un rango con guion:
ESPN devuelve 0 eventos sin error). Nunca lanza.
"""
import datetime as dt
import difflib
import logging
import re
import unicodedata
from typing import Dict, List, Optional

logger = logging.getLogger('espn_vivo')
BASE = 'https://site.api.espn.com/apis/site/v2/sports/'
RUTAS = {'Fútbol': 'soccer/all', 'NFL': 'football/nfl', 'NBA': 'basketball/nba',
         'NHL': 'hockey/nhl', 'MLB': 'baseball/mlb'}
_RUIDO = {'fc', 'cf', 'sc', 'ac', 'afc', 'cd', 'club', 'de', 'the', 'fk', 'sk', 'if', 'bk',
          'ud', 'sd', 'ca', 'cs', 'sv', 'vfb', 'vfl', 'tsg', 'rc', 'rcd', 'us', 'as', 'ss', 'sl'}


def _norm(t: str) -> str:
    t = unicodedata.normalize('NFKD', str(t or '')).encode('ascii', 'ignore').decode().lower()
    pal = [p for p in re.split(r'[^a-z0-9]+', t) if p and p not in _RUIDO]
    return ' '.join(pal)


def _parecido(a: str, b: str) -> float:
    a, b = _norm(a), _norm(b)
    if not a or not b:
        return 0.0
    if a == b or a in b or b in a:
        return 1.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def _par(h: str, a: str, eh: str, ea: str, misma_hora: bool) -> float:
    """Parecido de los dos equipos. Con la MISMA hora de inicio basta que uno
    case de lleno y el otro empiece igual («Wolves» / «Wolverhampton»,
    «Ein Frankfurt» / «Eintracht Frankfurt»)."""
    x, y = _parecido(h, eh), _parecido(a, ea)
    s = min(x, y)
    if misma_hora and max(x, y) >= 0.9:
        otro = (a, ea) if x >= y else (h, eh)
        n1, n2 = _norm(otro[0]), _norm(otro[1])
        if n1[:3] and n1[:3] == n2[:3] or min(x, y) >= 0.35:
            s = max(s, 0.65)
    return s


def _utc(s) -> Optional[dt.datetime]:
    try:
        s = str(s).replace(' ', 'T').replace('Z', '')
        d = dt.datetime.fromisoformat(s[:19])
        return d.replace(tzinfo=dt.timezone.utc)
    except Exception:
        return None


def eventos(ruta: str, dia: str, _memo: Dict = {}) -> List[Dict]:
    """Los partidos de ESPN de un deporte y día (AAAAMMDD), ya resumidos."""
    k = (ruta, dia)
    if k in _memo:
        return _memo[k]
    out = []
    try:
        import requests
        r = requests.get(BASE + ruta + '/scoreboard', params={'dates': dia, 'limit': 1000}, timeout=20)
        for ev in (r.json().get('events') or []) if r.ok else []:
            comp = (ev.get('competitions') or [{}])[0]
            eq = {c.get('homeAway'): c.get('team') or {} for c in comp.get('competitors') or []}
            if 'home' not in eq or 'away' not in eq:
                continue
            # v410 — la liga viene en los enlaces («…/league/mex.w.1»); antes se
            # tomaba el final del primer enlace, que es el nombre del partido
            liga = ''
            for l in ev.get('links') or []:
                m = re.search(r'/league/([a-z0-9._]+)', str((l or {}).get('href') or ''))
                if m:
                    liga = m.group(1)
                    break
            out.append({'id': str(ev.get('id')), 'inicio': _utc(ev.get('date')), 'liga': liga,
                        'home': eq['home'].get('displayName') or '', 'away': eq['away'].get('displayName') or '',
                        'logo_h': _escudo(liga, eq['home']), 'logo_a': _escudo(liga, eq['away'])})
    except Exception as e:
        logger.debug('[espn_vivo] %s %s: %s', ruta, dia, e)
    _memo[k] = out
    return out


# v410 — LOS ESCUDOS DE LAS FEMENILES, DEL MISMO CLUB EN LA VARONIL.
#
# El usuario: «ya jugó Toluca contra Santos Laguna de la Liga MX y me estabas
# mostrando el Santos pero de Brasil». El partido era el correcto (Liga MX
# Femenil, evento 401924383); el ESCUDO lo manda mal ESPN: su equipo «Santos»
# de la Femenil (id 133985) trae el escudo del Santos FC de Brasil. Los clubes
# de estas ligas son los mismos que los de la varonil de su país y llevan el
# mismo escudo, así que se toma el de la varonil cuando el nombre coincide
# EXACTO (si no coincide, se deja el de ESPN).
VARONIL = {'mex.w.1': 'mex.1', 'eng.w.1': 'eng.1', 'esp.w.1': 'esp.1', 'fra.w.1': 'fra.1'}
_ESCUDOS: Dict[str, Dict[str, str]] = {}


def _escudos_varonil(liga: str) -> Dict[str, str]:
    if liga not in _ESCUDOS:
        out = {}
        try:
            import requests
            r = requests.get(BASE + 'soccer/%s/teams' % liga, timeout=20)
            for x in ((((r.json().get('sports') or [{}])[0].get('leagues') or [{}])[0].get('teams') or [])
                      if r.ok else []):
                t = x.get('team') or {}
                logo = ((t.get('logos') or [{}])[0] or {}).get('href')
                if t.get('displayName') and logo:
                    out[_norm(t['displayName'])] = logo
        except Exception as e:
            logger.debug('[espn_vivo] escudos de %s: %s', liga, e)
        _ESCUDOS[liga] = out
    return _ESCUDOS[liga]


def _escudo(liga: str, equipo: Dict) -> str:
    logo = (equipo or {}).get('logo') or ''
    var = VARONIL.get(str(liga or ''))
    if var:
        return _escudos_varonil(var).get(_norm(equipo.get('displayName'))) or logo
    return logo


def _lados(partido: str):
    p = str(partido or '')
    for sep in (' vs ', ' vs. ', ' - ', ' @ ', ' at '):
        if sep in p:
            a, b = p.split(sep, 1)
            return (b, a) if sep in (' @ ', ' at ') else (a, b)
    return None


def emparejar(picks: List[Dict]) -> int:
    """Pone en cada pick `espn` («ruta:id») y los escudos. Devuelve cuántos."""
    n, hecho = 0, {}
    for p in picks:
        try:
            ruta = RUTAS.get(str(p.get('deporte') or ''))
            ini = _utc(p.get('inicio'))
            lados = _lados(p.get('partido'))
            if not ruta or ini is None or not lados:
                continue
            clave = (ruta, p.get('partido'), str(ini))
            if clave not in hecho:
                mejor, puntos = None, 0.0
                for d in {ini.strftime('%Y%m%d'), (ini - dt.timedelta(hours=6)).strftime('%Y%m%d')}:
                    for ev in eventos(ruta, d):
                        if ev['inicio'] is None or abs((ev['inicio'] - ini).total_seconds()) > 3 * 3600:
                            continue
                        h, a = lados
                        mh = abs((ev['inicio'] - ini).total_seconds()) <= 15 * 60
                        s = _par(h, a, ev['home'], ev['away'], mh)
                        s2 = _par(h, a, ev['away'], ev['home'], mh)
                        if max(s, s2) > puntos:
                            mejor, puntos = dict(ev, girado=s2 > s), max(s, s2)
                hecho[clave] = mejor if puntos >= 0.6 else None
            ev = hecho[clave]
            if ev:
                p['espn'] = '%s:%s' % (ruta, ev['id'])
                p['girado'] = bool(ev.get('girado'))      # nuestro «A vs B» al revés que ESPN
                p['logo_h'], p['logo_a'] = ((ev['logo_a'], ev['logo_h']) if ev.get('girado')
                                            else (ev['logo_h'], ev['logo_a']))
                n += 1
        except Exception as e:
            logger.debug('[espn_vivo] %s: %s', p.get('partido'), e)
    return n
