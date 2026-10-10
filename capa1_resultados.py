# -*- coding: utf-8 -*-
"""
v351 — CADA COSA DE LA CAPA 1, CON SI SE GANÓ, Y SU TASA DE CONVERSIÓN.

El usuario: «que la Capa 1 muestre si se dio lo que dices que se mete, pero
también los errores de cuota, la buena cuota con buena probabilidad y el de
mayor riesgo. Todo debe tener si se ganó o no, de acuerdo al semáforo, y cada
uno un indicador súper breve de la tasa de conversión verdes contra rojas».

HASTA AQUÍ sólo 🏆 y 🔷 se quedaban al acabar el partido, en verde o rojo
(v342). Los 💰 errores de precio y las 🎯 probables desaparecían al empezar,
y de ninguno de los cuatro se llevaba la cuenta de días anteriores.

AHORA:
  · `anunciadas` guarda en cada precálculo TODO lo que enseña la Capa 1
    (los cuatro grupos), con su hora, su cuota, su deporte y su liga.
  · `liquidar` (en el cron, que sale a la red) busca el marcador de cada
    partido ya terminado — FotMob para el fútbol de cualquier liga y el feed
    diario de Flashscore para el fútbol, el tenis, el básquet y el béisbol —
    y lo resuelve con la MISMA semántica del liquidador (`liquidador.resolver`).
    Lo que no se sabe resolver no se inventa: se queda sin resultado.
  · El resultado se guarda en la propia entrada (para pintar la fila en verde
    o rojo) y en `capa1_historial.json`, que dura 60 días y es de donde sale
    la tasa de conversión de cada grupo.
La app sólo lee: nunca sale a la red para esto.
"""
from __future__ import annotations

import datetime as _dt
import json
import logging
import os
import re
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger('capa1_resultados')

FICHERO = 'capa1_historial.json'
DIAS_MEMORIA = 60
DIAS_TASA = 7
NIVELES = ('🏆', '🔷', '💰', '🎯')
# el feed diario de Flashscore por deporte (f_<deporte>_<día>_…)
FLASH = {'Fútbol': 1, 'Tenis': 2, 'Baloncesto': 3, 'NBA': 3, 'NFL': 5,
         'MLB': 6, 'KBO': 6, 'Béisbol': 6}
FEED = 'https://global.flashscore.ninja/2/x/feed/f_%d_%d_3_es-mx_1'
# horas desde el inicio hasta dar el partido por acabado
DURACION_H = {'Fútbol': 2.25, 'Tenis': 3.0, 'Baloncesto': 2.75, 'NBA': 2.75,
              'NFL': 3.5, 'MLB': 3.5, 'KBO': 3.5, 'Béisbol': 3.5}
_CACHE: Dict = {}


def _ruta() -> str:
    return os.environ.get('CAPA1_HISTORIAL') or FICHERO


def _utc(s) -> Optional[_dt.datetime]:
    try:
        import horario as hz
        return hz._a_utc(s)
    except Exception:
        return None


def _dia_cdmx(s) -> str:
    try:
        import horario as hz
        return hz.fecha(s) or ''
    except Exception:
        return ''


# ---------------------------------------------------------------------------
# los marcadores (sólo en el cron)
# ---------------------------------------------------------------------------
def _flashscore(sport: int, dia: str, hoy: _dt.date) -> List[Dict]:
    """Los terminados del feed de Flashscore del día CDMX `dia` (y el
    siguiente, que es parte de la noche en UTC). Sólo la última semana."""
    try:
        import resultados_flashscore as rf
        d0 = _dt.date.fromisoformat(dia)
    except Exception:
        return []
    out = []
    for off in sorted({(d0 - hoy).days, (d0 - hoy).days + 1}):
        if not -7 <= off <= 0:
            continue
        t = rf._get(FEED % (sport, off))
        for p in rf._partidos(t or '', '', ''):
            out.append({'ini': _utc(p['ini']), 'home': p['home'], 'away': p['away'],
                        'gh': float(p['gh']), 'ga': float(p['ga']), 'liga': p['liga']})
    return [x for x in out if x['ini'] is not None]


def _lista(deporte: str, dia: str, hoy: _dt.date, cache: Dict) -> List[Dict]:
    k = (deporte, dia)
    if k not in cache:
        lst = []
        if deporte == 'Fútbol':
            try:
                import partidos_jugados as pj
                lst += pj.marcadores_fotmob(dia)
            except Exception as e:
                logger.debug('[capa1_res] fotmob %s: %s', dia, e)
        sp = FLASH.get(deporte)
        if sp:
            lst += _flashscore(sp, dia, hoy)
        cache[k] = [x for x in lst if x.get('gh') is not None]
    return cache[k]


def _partes(partido: str) -> Optional[Tuple[str, str]]:
    """(local, visitante) con nuestros nombres. La MLB escribe «visita @ local»."""
    par = str(partido or '')
    if ' @ ' in par:
        a, h = (x.strip() for x in par.split(' @ ', 1))
        return h, a
    if ' vs ' in par:
        h, a = (x.strip() for x in par.split(' vs ', 1))
        return h, a
    return None


def resolver(mercado: str, apuesta: str, home: str, away: str,
             gh: float, ga: float) -> Optional[str]:
    """'verde', 'rojo', 'nula' (se devuelve) o None si no se sabe."""
    a = str(apuesta or '')
    m = str(mercado or '').lower()
    # la doble oportunidad (lo más común en 🏆), que el liquidador no conoce:
    # «X o empate» y «X o Y»
    al = a.strip().lower()
    hl, awl = str(home).strip().lower(), str(away).strip().lower()
    if al == '%s o empate' % hl:
        return 'verde' if gh >= ga else 'rojo'
    if al == '%s o empate' % awl:
        return 'verde' if ga >= gh else 'rojo'
    if al in ('%s o %s' % (hl, awl), '%s o %s' % (awl, hl)):
        return 'verde' if gh != ga else 'rojo'
    # v354 — el hándicap de la NBA llega como «Handicap: Equipo +7.5»
    if a.startswith('Handicap: '):
        a, m = a[len('Handicap: '):].strip(), 'handicap'
    # «Más de 3.0 goles» con 3 goles se devuelve: el liquidador lo da perdido
    if m == 'goles' or 'goles' in a.lower():
        mm = re.search(r'(\d+(?:[.,]\d+)?)', a)
        if mm:
            lin = float(mm.group(1).replace(',', '.'))
            if lin == int(lin) and gh + ga == lin:
                return 'nula'
            m = 'goles'
    try:
        import liquidador as lq
        g = lq.resolver(m if m else 'goles', a, home, away, int(gh), int(ga))
    except Exception:
        g = None
    if g is None:
        return None
    return 'verde' if g else 'rojo'


def liquidar(ruta_anunciadas: str = '', ruta: str = '',
             ahora: Optional[_dt.datetime] = None) -> int:
    """Pone resultado a lo que la Capa 1 enseñó y ya terminó, y lo apunta en
    el historial. Devuelve cuántas liquidó. Nunca lanza."""
    try:
        import anunciadas as an
        import partidos_jugados as pj
    except Exception:
        return 0
    ruta_an = ruta_anunciadas or an._ruta()
    ahora = ahora or _dt.datetime.now(_dt.timezone.utc)
    hoy = ahora.date()
    try:
        with open(ruta_an, encoding='utf-8') as f:
            doc = json.load(f) or {}
    except Exception:
        return 0
    cache: Dict = {}
    nuevas = []
    for k, ent in (doc.get('partidos') or {}).items():
        c1 = ent.get('capa1') or []
        if not c1 or all(x.get('resultado') for x in c1):
            continue
        partido = ent.get('partido') or k.split('|')[0]
        dep = str(ent.get('deporte') or 'Fútbol')
        ini = _utc(ent.get('inicio'))
        if ini is None or ahora < ini + _dt.timedelta(hours=DURACION_H.get(dep, 3.0)):
            continue
        par = _partes(partido)
        if not par:
            continue
        dia = _dia_cdmx(ini)
        lista = _lista(dep, dia, hoy, cache)
        q = {'inicio': ent.get('inicio'), 'partido': '%s vs %s' % par}
        f = pj._casar_fotmob(q, lista) if lista else None
        if not f:
            continue
        for x in c1:
            if x.get('resultado'):
                continue
            r = resolver(x.get('mercado'), x.get('apuesta'), par[0], par[1],
                         f['gh'], f['ga'])
            if r is None:
                continue
            x['resultado'] = r
            x['marcador'] = '%d-%d' % (int(f['gh']), int(f['ga']))
            nuevas.append({'dia': dia, 'nivel': x.get('nivel'), 'deporte': dep,
                           'partido': partido, 'apuesta': x.get('apuesta'),
                           'cuota': x.get('cuota'), 'resultado': r,
                           'marcador': x['marcador']})
    if not nuevas:
        return 0
    try:
        with open(ruta_an, 'w', encoding='utf-8') as f:
            json.dump(doc, f, ensure_ascii=False)
    except Exception as e:
        logger.warning('[capa1_res] no se pudo escribir %s: %s', ruta_an, e)
    return apuntar(nuevas, ruta, ahora)


def apuntar(filas: List[Dict], ruta: str = '',
            ahora: Optional[_dt.datetime] = None) -> int:
    """Añade al historial lo liquidado (sin repetir) y olvida lo de hace más
    de `DIAS_MEMORIA` días. Devuelve cuántas añadió."""
    ruta = ruta or _ruta()
    ahora = ahora or _dt.datetime.now(_dt.timezone.utc)
    viejo = cargar(ruta)
    hist = list(viejo.get('filas') or [])
    vistos = {(h.get('dia'), h.get('nivel'), h.get('partido'), h.get('apuesta'))
              for h in hist}
    n = 0
    for x in filas:
        k = (x.get('dia'), x.get('nivel'), x.get('partido'), x.get('apuesta'))
        if k in vistos:
            continue
        vistos.add(k)
        hist.append(x)
        n += 1
    limite = (ahora.date() - _dt.timedelta(days=DIAS_MEMORIA)).isoformat()
    hist = [h for h in hist if str(h.get('dia') or '') >= limite]
    hist.sort(key=lambda h: (str(h.get('dia')), str(h.get('partido'))))
    try:
        with open(ruta, 'w', encoding='utf-8') as f:
            json.dump({'version': 1, 'actualizado': ahora.strftime('%Y-%m-%dT%H:%M:%SZ'),
                       'filas': hist}, f, ensure_ascii=False, indent=0)
        _CACHE.clear()
    except Exception as e:
        logger.warning('[capa1_res] no se pudo escribir %s: %s', ruta, e)
    logger.info('[capa1_res] %d liquidadas nuevas; %d en el historial', n, len(hist))
    return n


# ---------------------------------------------------------------------------
# lo que lee la app
# ---------------------------------------------------------------------------
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
    except Exception:
        doc = {}
    _CACHE.update(ruta=ruta, mt=mt, doc=doc)
    return doc


def cuenta(nivel: str, desde: str, hasta: str, ruta: str = '',
           deportes=None) -> Tuple[int, int]:
    """(verdes, rojas) del grupo entre dos días CDMX, ambos incluidos."""
    v = r = 0
    for h in cargar(ruta).get('filas') or []:
        if h.get('nivel') != nivel or not (desde <= str(h.get('dia') or '') <= hasta):
            continue
        if deportes and str(h.get('deporte') or 'Fútbol') not in deportes:
            continue
        if h.get('resultado') == 'verde':
            v += 1
        elif h.get('resultado') == 'rojo':
            r += 1
    return v, r


def tasa(nivel: str, hoy: str, ruta: str = '', deportes=None) -> str:
    """La línea breve del grupo: '📈 7 días 80 % (✅12 ❌3)', o ''."""
    try:
        d1 = _dt.date.fromisoformat(hoy)
    except Exception:
        return ''
    desde = (d1 - _dt.timedelta(days=DIAS_TASA - 1)).isoformat()
    v, r = cuenta(nivel, desde, hoy, ruta, deportes)
    if v + r == 0:
        return ''
    return '📈 %d días %.0f %% (✅%d ❌%d)' % (DIAS_TASA, 100.0 * v / (v + r), v, r)


def finalizadas(nivel: str, dia: str, ruta_anunciadas: str = '',
                ahora: Optional[_dt.datetime] = None) -> List[Dict]:
    """Lo que el grupo enseñó de partidos de `dia` (CDMX) que ya empezaron,
    con su resultado, listo para `vista_compacta`. Para 💰 y 🎯, que no se
    rehacen del pick archivado como 🏆 y 🔷. Nunca lanza."""
    try:
        import anunciadas as an
        doc = an.cargar(ruta_anunciadas)
    except Exception:
        return []
    ahora = ahora or _dt.datetime.now(_dt.timezone.utc)
    out = []
    for k, ent in (doc.get('partidos') or {}).items():
        ini = _utc(ent.get('inicio'))
        if ini is None or ini > ahora or _dia_cdmx(ini) != dia:
            continue
        for x in ent.get('capa1') or []:
            if x.get('nivel') != nivel:
                continue
            res = x.get('resultado')
            out.append({
                'partido': ent.get('partido') or k.split('|')[0],
                'liga': ent.get('liga'), 'deporte': ent.get('deporte') or 'Fútbol',
                'inicio': ent.get('inicio'), 'apuesta': x.get('apuesta'),
                'mercado': x.get('mercado'), 'cuota': x.get('cuota'),
                'prob': x.get('prob'),
                'resultado_c1': res if res in ('verde', 'rojo', 'nula') else 'vivo',
                'marcador': x.get('marcador') or '',
                'semaforo': {'nivel': 'verde', 'etiqueta': 'anunciada a las %s'
                             % an.hora_cdmx(x.get('desde'))}})
    out.sort(key=lambda z: str(z.get('inicio') or ''))
    return out
