# -*- coding: utf-8 -*-
"""
v303 — POR QUÉ ESTA APUESTA, EN UNA LÍNEA. Y EL PERFIL DE CADA EQUIPO QUE
LA SOSTIENE.

LO QUE PIDIÓ EL USUARIO
    «En la tarjeta de la apuesta también debes decir brevemente por qué es
     que estás escogiendo esa apuesta, sólo para que yo pueda checar, pero
     quiero algo corto, no un textote: si estás escogiendo over de 2.5, poner
     que la media de goles de los equipos es de X...»

    «...checar cómo juega cada equipo, cuáles son sus tendencias en goles con
     equipos chicos, cuáles con equipos grandes, qué pasa cuando juegan
     grandes con grandes, chicos con chicos... de visita y local...»

QUÉ HACE
`perfil(liga, equipo)` recorre el histórico REAL de la competición una sola
vez (con la misma `Tabla` sin fuga de `patrones_liga`) y guarda, partido a
partido, el tercio de la tabla en que estaba el RIVAL en ese momento. De ahí
salen, para cada equipo: goles a favor y en contra en casa y fuera (sus
últimos 10 de cada), cuántas veces marcó, y cómo le va contra los de arriba
y contra los de abajo. `cruce(liga, t_local, t_visita)` da la media de goles
—y de córners y tarjetas donde el histórico los trae OBSERVADOS— de ese tipo
de partido en esa liga («arriba contra abajo», «abajo contra abajo»...).

`razon(pick, apuesta)` elige de todo eso la cifra que explica la apuesta y la
dice en una línea. No decide nada: la probabilidad ya lleva dentro el modelo,
la pata histórica (v246), el H2H (v258) y los patrones de liga (v302). Esto
es para que el usuario pueda comprobarlo.

Los córners y tarjetas sólo se citan con datos observados (`stats_origen`
de ESPN o las ligas de football-data); nunca con las columnas del generador
sintético.
"""
from __future__ import annotations

import logging
import math
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

VENTANA = 10
MIN_CRUCE = 30
_CACHE: Dict[str, Dict] = {}

TERCIO = {'arriba': 'de arriba', 'medio': 'de la mitad', 'abajo': 'de abajo'}


def _f(x, d=1) -> str:
    """1,8 con coma, como el resto de la pantalla."""
    if x is None:
        return '—'
    return (('%.' + str(d) + 'f') % x).replace('.', ',')


def _num(v) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x else None


def _estadistica_real(d) -> Dict[str, bool]:
    """Qué columnas de conteo son observadas en este histórico."""
    fuera = {}
    for col in ('corners', 'yellow'):
        h = 'home_%s' % col
        if h not in d.columns:
            fuera[col] = False
            continue
        if 'stats_origen' in d.columns and d['stats_origen'].notna().any():
            fuera[col] = True           # se filtrará por fila
        else:
            try:
                import rendimiento_equipos as rq
                disp = rq.stats_disponibles(str(d.attrs.get('clave', '')))
                fuera[col] = bool(disp.get({'corners': 'corners',
                                            'yellow': 'tarjetas'}[col]))
            except Exception:
                fuera[col] = False
    return fuera


def _construir(liga: str) -> Dict:
    import pandas as pd
    import patrones_liga as pl
    ruta = 'historico_%s.csv' % liga
    try:
        d = pd.read_csv(ruta, low_memory=False)
    except Exception as e:
        logger.debug('[razon] %s: %s', ruta, e)
        return {}
    need = {'date', 'home_team', 'away_team', 'home_goals', 'away_goals'}
    if not need.issubset(d.columns):
        return {}
    d = d.dropna(subset=list(need)).copy()
    d['date'] = pd.to_datetime(d['date'], errors='coerce')
    d = d.dropna(subset=['date']).sort_values('date')
    d.attrs['clave'] = liga
    reales = _estadistica_real(d)
    tiene_origen = 'stats_origen' in d.columns
    t = pl.Tabla()
    por_equipo: Dict[str, List[Dict]] = defaultdict(list)
    cruces: Dict[Tuple[str, str], List[Tuple]] = defaultdict(list)
    for r in d.itertuples(index=False):
        h, a, f = r.home_team, r.away_team, r.date
        ras = t.rasgos(h, a, f)
        th, ta = pl.tercio(ras.get('pct_h')), pl.tercio(ras.get('pct_a'))
        gh, ga = float(r.home_goals), float(r.away_goals)
        obs = (not tiene_origen) or (getattr(r, 'stats_origen', None)
                                     == 'espn')
        ck = yl = None
        if obs and reales.get('corners'):
            ck = (_num(getattr(r, 'home_corners', None)),
                  _num(getattr(r, 'away_corners', None)))
        if obs and reales.get('yellow'):
            yl = (_num(getattr(r, 'home_yellow', None)),
                  _num(getattr(r, 'away_yellow', None)))
        por_equipo[h].append({'casa': True, 'gf': gh, 'gc': ga,
                              't_rival': ta,
                              'ck': ck[0] if ck else None,
                              'ta': yl[0] if yl else None})
        por_equipo[a].append({'casa': False, 'gf': ga, 'gc': gh,
                              't_rival': th,
                              'ck': ck[1] if ck else None,
                              'ta': yl[1] if yl else None})
        if th and ta:
            tot_ck = (ck[0] + ck[1]) if ck and None not in ck else None
            tot_ta = (yl[0] + yl[1]) if yl and None not in yl else None
            cruces[(th, ta)].append((gh + ga, tot_ck, tot_ta))
        t.sumar(h, a, f, gh, ga)
    return {'equipos': por_equipo, 'cruces': cruces, 'tabla': t}


def _datos(liga: str) -> Dict:
    if liga not in _CACHE:
        try:
            _CACHE[liga] = _construir(liga)
        except Exception as e:
            logger.debug('[razon] %s: %s', liga, e)
            _CACHE[liga] = {}
    return _CACHE[liga]


def olvidar() -> None:
    _CACHE.clear()


def _media(xs: List[float]) -> Optional[float]:
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def perfil(liga: str, equipo: str) -> Optional[Dict]:
    """El perfil reciente de un equipo en su competición. None si no hay."""
    d = _datos(liga)
    ps = (d.get('equipos') or {}).get(equipo) or []
    if len(ps) < 5:
        return None
    casa = [p for p in ps if p['casa']][-VENTANA:]
    fuera = [p for p in ps if not p['casa']][-VENTANA:]
    ult = ps[-2 * VENTANA:]
    vs = {}
    for ter in ('arriba', 'abajo'):
        s = [p for p in ps[-30:] if p['t_rival'] == ter]
        if len(s) >= 3:
            vs[ter] = {'n': len(s), 'gf': _media([p['gf'] for p in s]),
                       'gc': _media([p['gc'] for p in s])}
    t = d.get('tabla')
    ter = None
    try:
        import pandas as pd
        import patrones_liga as pl
        ras = t.rasgos(equipo, equipo, pd.Timestamp.now())
        ter = pl.tercio(ras.get('pct_h'))
    except Exception:
        pass

    def bloque(s):
        if not s:
            return None
        return {'n': len(s), 'gf': _media([p['gf'] for p in s]),
                'gc': _media([p['gc'] for p in s]),
                'marca': sum(1 for p in s if p['gf'] > 0),
                'recibe': sum(1 for p in s if p['gc'] > 0),
                'ck': _media([p['ck'] for p in s]),
                'ta': _media([p['ta'] for p in s]),
                'g': sum(1 for p in s if p['gf'] > p['gc']),
                'e': sum(1 for p in s if p['gf'] == p['gc']),
                'p': sum(1 for p in s if p['gf'] < p['gc'])}
    return {'casa': bloque(casa), 'fuera': bloque(fuera),
            'ultimos': bloque(ult), 'vs': vs, 'tercio': ter}


def cruce(liga: str, t_local: Optional[str],
          t_visita: Optional[str]) -> Optional[Dict]:
    """Cómo suele ir ese tipo de partido en la liga (goles, córners...)."""
    if not (t_local and t_visita):
        return None
    xs = (_datos(liga).get('cruces') or {}).get((t_local, t_visita)) or []
    if len(xs) < MIN_CRUCE:
        return None
    goles = [x[0] for x in xs]
    ck = [x[1] for x in xs if x[1] is not None]
    ta = [x[2] for x in xs if x[2] is not None]
    return {'n': len(xs), 'goles': _media(goles),
            'mas25': sum(1 for g in goles if g > 2.5) / len(goles),
            'corners': _media(ck) if len(ck) >= MIN_CRUCE else None,
            'tarjetas': _media(ta) if len(ta) >= MIN_CRUCE else None}


# ---------------------------------------------------------------------------
# la línea
# ---------------------------------------------------------------------------
def _equipos(pick: Dict) -> Tuple[str, str]:
    par = str(pick.get('partido') or '')
    if ' vs ' not in par:
        return '', ''
    h, a = par.split(' vs ', 1)
    return h.strip(), a.strip()


def _corto(nombre: str) -> str:
    return nombre if len(nombre) <= 16 else nombre[:15] + '.'


def razon(pick: Dict, apuesta: Dict) -> str:
    """Una línea que explica la apuesta. Cadena vacía si no hay con qué."""
    try:
        return _razon(pick, apuesta or {})
    except Exception as e:
        logger.debug('[razon] %s: %s', pick.get('partido'), e)
        return ''


def _razon(pick: Dict, ap: Dict) -> str:
    liga = str(pick.get('clave_liga') or '')
    h, a = _equipos(pick)
    if not (liga and h and a):
        return ''
    ph, pa = perfil(liga, h), perfil(liga, a)
    ch = (ph or {}).get('casa') or {}
    fv = (pa or {}).get('fuera') or {}
    mk = str(ap.get('mercado') or '')
    texto = str(ap.get('apuesta') or '')
    trozos: List[str] = []
    th, ta = (ph or {}).get('tercio'), (pa or {}).get('tercio')
    cr = cruce(liga, th, ta)
    if mk in ('Goles', 'Doble y goles', 'BTTS', 'Goles equipo'):
        if mk == 'Goles equipo':
            quien = h if h in texto else a
            b = ch if quien == h else fv
            donde = 'en casa' if quien == h else 'fuera'
            if b.get('n'):
                trozos.append('%s marcó en %d de sus últimos %d %s (%s de '
                              'media)' % (_corto(quien), b['marca'], b['n'],
                                          donde, _f(b['gf'])))
            rival = pa if quien == h else ph
            rb = (rival or {}).get('fuera' if quien == h else 'casa') or {}
            if rb.get('n'):
                trozos.append('%s recibe %s' % (_corto(a if quien == h else h),
                                               _f(rb['gc'])))
        elif mk == 'BTTS':
            if ch.get('n') and fv.get('n'):
                trozos.append('%s marca en %d/%d y encaja en %d/%d en casa; '
                              '%s marca en %d/%d fuera'
                              % (_corto(h), ch['marca'], ch['n'],
                                 ch['recibe'], ch['n'], _corto(a),
                                 fv['marca'], fv['n']))
        else:
            if ch.get('n') and fv.get('n'):
                trozos.append('%s mete %s y recibe %s en casa; %s %s/%s fuera'
                              % (_corto(h), _f(ch['gf']), _f(ch['gc']),
                                 _corto(a), _f(fv['gf']), _f(fv['gc'])))
            lam = _num(pick.get('goles_lambda'))
            if lam:
                trozos.append('%s goles esperados' % _f(lam))
        if cr and mk != 'Goles equipo':
            trozos.append('%s vs %s aquí: %s goles de media'
                          % (TERCIO.get(th, th), TERCIO.get(ta, ta),
                             _f(cr['goles'])))
        # contra los grandes o contra los chicos: cómo le va al local ante
        # rivales del tercio en el que está hoy el de enfrente
        vs = ((ph or {}).get('vs') or {}).get(ta or '')
        if vs and len(trozos) < 3:
            trozos.append('%s ante rivales %s: %s-%s' % (
                _corto(h), TERCIO.get(ta, ta), _f(vs['gf']), _f(vs['gc'])))
    elif mk in ('1X2', 'Doble oportunidad', 'Handicap'):
        if ch.get('n') and fv.get('n'):
            trozos.append('%s %d-%d-%d en casa; %s %d-%d-%d fuera'
                          % (_corto(h), ch['g'], ch['e'], ch['p'], _corto(a),
                             fv['g'], fv['e'], fv['p']))
        if th and ta:
            trozos.append('tabla: %s %s, %s %s' % (_corto(h), TERCIO[th],
                                                    _corto(a), TERCIO[ta]))
    elif mk == 'Córners':
        med = _num(ap.get('media'))
        if ch.get('ck') is not None and fv.get('ck') is not None:
            trozos.append('%s saca %s en casa; %s %s fuera'
                          % (_corto(h), _f(ch['ck']), _corto(a),
                             _f(fv['ck'])))
        if med:
            trozos.append('%s esperados' % _f(med))
        if cr and cr.get('corners'):
            trozos.append('este cruce aquí: %s de media' % _f(cr['corners']))
    elif mk == 'Tarjetas':
        med = _num(ap.get('media'))
        if ch.get('ta') is not None and fv.get('ta') is not None:
            trozos.append('%s ve %s en casa; %s %s fuera'
                          % (_corto(h), _f(ch['ta']), _corto(a),
                             _f(fv['ta'])))
        if med:
            trozos.append('%s esperadas' % _f(med))
        if cr and cr.get('tarjetas'):
            trozos.append('este cruce aquí: %s de media' % _f(cr['tarjetas']))
    if not trozos:
        return ''
    # dos datos como mucho: «algo corto, no un textote»
    return ' · '.join(trozos[:2])
