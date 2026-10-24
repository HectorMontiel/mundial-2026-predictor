# -*- coding: utf-8 -*-
"""
v467 — LOS ESCUDOS DE TODOS LOS PARTIDOS (Y LA FOTO DE LOS TENISTAS), VALIDADOS UNO POR UNO.

El usuario, con «Ath Madrid vs La Coruna» enseñando una «A» y una «L»: «valida uno por uno, no
quiero errores de ese estilo». Los escudos sólo salían de ESPN y sólo si ESPN encontraba el
partido; de 413 partidos, 31 se quedaban con la letra: nombres que ESPN no reconoce («Ath
Madrid», «Sp Lisbon», «QPR») y ligas donde ESPN no tiene escudo (Expansión MX, National
League, femeniles).

Aquí, para los que se quedaron sin escudo, se busca el MISMO partido en FotMob (misma hora,
los dos equipos) y el escudo sale del id de FotMob del equipo. Un escudo equivocado es peor que
ninguno (Paris FC no es el PSG): sólo se pone si el PARTIDO casa entero, nunca por un nombre
suelto.
"""
from __future__ import annotations

import datetime as dt
import logging
import re
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

LOGO = 'https://images.fotmob.com/image_resources/logo/teamlogo/{id}.png'


def _utc(x) -> Optional[dt.datetime]:
    try:
        i = dt.datetime.fromisoformat(str(x).replace(' ', 'T').replace('Z', '+00:00'))
        return i if i.tzinfo else i.replace(tzinfo=dt.timezone.utc)
    except Exception:
        return None


def _dia(fecha: str, cache: Dict) -> List[Dict]:
    if fecha not in cache:
        import fuente_bajas as fb
        doc = fb._get(fb.FOTMOB_DIA.format(fecha=fecha)) or {}
        out = []
        for L in doc.get('leagues') or []:
            for m in L.get('matches') or []:
                h, a = m.get('home') or {}, m.get('away') or {}
                ini = _utc((m.get('status') or {}).get('utcTime'))
                if ini and h.get('id') and a.get('id') and h.get('name') and a.get('name'):
                    out.append({'ini': ini, 'home': h['name'], 'away': a['name'], 'hid': h['id'], 'aid': a['id'],
                                'cat': _cat(L.get('name'), h['name'], a['name'])})
        cache[fecha] = out
    return cache[fecha]


_FEM = ('women', 'femen', 'femin', 'frauen', '(w)', 'liga f', 'nwsl', 'wsl', 'kvinn', 'vrouwen', 'dames', 'ladies')
_JUV = re.compile(r'\b(u|sub)[- ]?(1[5-9]|2[0-3])\b|juvenil|youth|primavera|reserv')


def _cat(*textos) -> tuple:
    """(femenil, juvenil): el equipo femenil o el sub-20 del Atlético NO es el Atlético."""
    t = ' '.join(str(x or '') for x in textos).lower()
    return (any(k in t for k in _FEM), bool(_JUV.search(t)))


def _lado(nuestro: str, suyo: str) -> float:
    """Parecido de un equipo. 1.0 si los alias del proyecto lo dicen, en cualquier sentido
    («QPR» = Queens Park Rangers, «Sp Lisbon» = Sporting CP, «AGF» = Aarhus); si no, el parecido
    de las letras SIN «contiene»: «Paris FC» está dentro de «Paris Saint-Germain» y NO es él."""
    import difflib
    import espn_vivo as ev
    import name_mapper as nm
    antes = set(getattr(nm, '_fallos', {}) or {})
    try:
        if nm.mapear(nuestro, [suyo]) == suyo or nm.mapear(suyo, [nuestro]) == nuestro:
            return 1.0
    except Exception:
        pass
    finally:
        for k in set(getattr(nm, '_fallos', {}) or {}) - antes:   # esto no es un «sin mapear» del modelo
            nm._fallos.pop(k, None)
    x, y = ev._norm(nuestro), ev._norm(suyo)
    return 1.0 if x and x == y else (difflib.SequenceMatcher(None, x, y).ratio() if x and y else 0.0)


def _puntos(h: str, a: str, mh: str, ma: str, misma_hora: bool) -> float:
    x, y = _lado(h, mh), _lado(a, ma)
    s = min(x, y)
    # a la MISMA hora, con un equipo idéntico y el otro parecido, es ese partido («La Coruna» /
    # «Deportivo A Coruña»); la categoría (femenil, juvenil) ya se comprobó antes
    if misma_hora and max(x, y) >= 0.95 and min(x, y) >= 0.45:
        s = max(s, 0.8)
    return s


def _mejor(partido: str, inicio, cache: Dict, liga: str = '') -> Optional[tuple]:
    """(partido de FotMob, girado) que casa ENTERO con nuestro «A vs B», o None."""
    import espn_vivo as ev
    lados, ini = ev._lados(partido), _utc(inicio)
    if not lados or ini is None:
        return None
    h, a = lados
    cat = _cat(liga, h, a)
    mejor, puntos = None, 0.0
    for d in sorted({(ini + dt.timedelta(hours=k)).strftime('%Y%m%d') for k in (-12, 0, 12)}):
        for m in _dia(d, cache):
            dif = abs((m['ini'] - ini).total_seconds())
            if dif > 3 * 3600 or m['cat'] != cat:
                continue
            mh = dif <= 15 * 60
            s, s2 = _puntos(h, a, m['home'], m['away'], mh), _puntos(h, a, m['away'], m['home'], mh)
            if max(s, s2) > puntos:
                mejor, puntos = (m, s2 > s), max(s, s2)
    return mejor if mejor and puntos >= 0.6 else None


def buscar(partido: str, inicio, cache: Dict, liga: str = '') -> Optional[tuple]:
    """(logo local, logo visita) de nuestro «A vs B», o None si el partido no casa entero."""
    r = _mejor(partido, inicio, cache, liga)
    if not r:
        return None
    m, girado = r
    lh, la = LOGO.format(id=m['hid']), LOGO.format(id=m['aid'])
    return (la, lh) if girado else (lh, la)


def fixture(partido: str, inicio, cache: Dict, liga: str = '') -> Optional[tuple]:
    """v469 — (nombre de FotMob de NUESTRO local, el de nuestra visita): con él se buscan sus
    jugadores en la base de FotMob (`jugadores_prob`)."""
    r = _mejor(partido, inicio, cache, liga)
    if not r:
        return None
    m, girado = r
    return (m['away'], m['home']) if girado else (m['home'], m['away'])


# FLASHSCORE: el tercer recurso del fútbol (ligas que FotMob no tiene, como la League Two china).
# En TENIS no sirve: su «OA»/«OB» es una imagen transparente de 30×30 o un 404 (medido: 51 y 24 de
# 75), nunca la foto del jugador. Por eso todo escudo, venga de donde venga, se descarga y se
# comprueba (`valida`) antes de ponerlo.
FS_FEED = 'https://global.flashscore.ninja/2/x/feed/f_1_%d_3_es-mx_1'
FS_IMG = 'https://static.flashscore.com/res/image/data/'


def _fs(cache: Dict) -> List[Dict]:
    """Los partidos de fútbol de Flashscore de ayer a dentro de 3 días, con su escudo."""
    if 'fs' not in cache:
        import resultados_flashscore as rf
        out = []
        for off in range(-1, 4):
            t = rf._get(FS_FEED % off) or ''
            liga = ''
            for d in rf._registros(t):
                if 'ZA' in d:
                    liga = d['ZA']
                    continue
                if not d.get('AE') or not d.get('AF') or not d.get('AD'):
                    continue
                try:
                    ini = dt.datetime.fromtimestamp(int(d['AD']), dt.timezone.utc)
                except Exception:
                    continue
                oa, ob = d.get('OA') or '', d.get('OB') or ''
                out.append({'ini': ini, 'home': d['AE'], 'away': d['AF'],
                            'lh': FS_IMG + oa if oa.endswith('.png') else '', 'la': FS_IMG + ob if ob.endswith('.png') else '',
                            'cat': _cat(liga, d['AE'], d['AF'])})
        cache['fs'] = out
    return cache['fs']


def buscar_fs(partido: str, inicio, cache: Dict, liga: str = '') -> Optional[tuple]:
    import espn_vivo as ev
    lados, ini = ev._lados(partido), _utc(inicio)
    if not lados or ini is None:
        return None
    h, a = lados
    cat = _cat(liga, h, a)
    mejor, puntos = None, 0.0
    for m in _fs(cache):
        dif = abs((m['ini'] - ini).total_seconds())
        if dif > 3 * 3600 or m['cat'] != cat:
            continue
        mh = dif <= 15 * 60
        s1, s2 = _puntos(h, a, m['home'], m['away'], mh), _puntos(h, a, m['away'], m['home'], mh)
        if max(s1, s2) > puntos:
            mejor, puntos = (m, s2 > s1), max(s1, s2)
    if not mejor or puntos < 0.6:
        return None
    m, gir = mejor
    return (m['la'], m['lh']) if gir else (m['lh'], m['la'])


def _pal(t: str) -> List[str]:
    import espn_vivo as ev
    return ev._norm(t).split()


def _jugador(nuestro: str, suyo: str) -> bool:
    """«Liudmila Samsonova» = «Samsonova L.»; «Ane Mintegi Del Olmo» = «Mintegi Del Olmo A.»;
    «Adolfo Daniel Vallejo» = «Vallejo D.»; «Darwin Blanch» = «Blanch Dar.». El apellido entero
    dentro del nombre y la inicial (lo que acaba en punto) en alguno de los nombres."""
    a, b = _pal(nuestro), _pal(suyo)
    if not a or not b:
        return False
    if a == b or sorted(a) == sorted(b):
        return True
    crudo = str(suyo or '').replace('/', ' ').split()
    ini = [_pal(w)[0] for w in crudo if w.endswith('.') and _pal(w)]
    ape = [w for w in b if w not in ini]
    if not ape or not all(w in a for w in ape):
        return False
    resto = [w for w in a if w not in ape]
    return not ini or not resto or any(r.startswith(ini[0]) for r in resto)


# 365SCORES: la foto de los tenistas. Un tercio no tiene y la imagen que da entonces es un cuadro
# en blanco (~700 bytes): `valida` lo descarta (mejor la silueta que un cuadro vacío).
API365 = ('https://webws.365scores.com/web/games/allscores/?appTypeId=5&langId=1&timezoneName=UTC'
          '&userCountryId=31&sports=3&showOdds=false&startDate={d}&endDate={d}')
IMG365 = ('https://imagecache.365scores.com/image/upload/f_png,w_68,h_68,c_limit,q_auto:eco,'
          'd_Competitors:default1.png/v{v}/Competitors/{id}')


def _365(fecha: dt.date, cache: Dict) -> List[Dict]:
    k = ('365', fecha)
    if k not in cache:
        import requests
        out = []
        try:
            r = requests.get(API365.format(d=fecha.strftime('%d/%m/%Y')), timeout=20, headers={'User-Agent': 'Mozilla/5.0'})
            for g in (r.json().get('games') or []) if r.ok else []:
                h, a = g.get('homeCompetitor') or {}, g.get('awayCompetitor') or {}
                ini = _utc(g.get('startTime'))
                if ini and h.get('name') and a.get('name') and h.get('id') and a.get('id'):
                    out.append({'ini': ini, 'home': h['name'], 'away': a['name'],
                                'lh': IMG365.format(v=h.get('imageVersion') or 1, id=h['id']),
                                'la': IMG365.format(v=a.get('imageVersion') or 1, id=a['id'])})
        except Exception as e:
            logger.debug('[escudos] 365 %s: %s', fecha, e)
        cache[k] = out
    return cache[k]


def buscar_365(partido: str, inicio, cache: Dict) -> Optional[tuple]:
    import espn_vivo as ev
    lados, ini = ev._lados(partido), _utc(inicio)
    if not lados or ini is None:
        return None
    h, a = lados
    for d in (ini.date(), ini.date() - dt.timedelta(days=1), ini.date() + dt.timedelta(days=1)):
        for m in _365(d, cache):
            # el orden de juego mueve la hora: los DOS jugadores casando el mismo día bastan
            if abs((m['ini'] - ini).total_seconds()) > 18 * 3600:
                continue
            if _jugador(h, m['home']) and _jugador(a, m['away']):
                return (m['lh'], m['la'])
            if _jugador(h, m['away']) and _jugador(a, m['home']):
                return (m['la'], m['lh'])
    return None


# ------------------------------------------------------------------ validar
MINIMO = {'imagecache.365scores.com': 800}      # su cuadro en blanco pesa ~700 bytes
MINIMO_GENERAL = 200                             # el transparente de Flashscore pesa 120


def valida(url: Optional[str], cache: Dict) -> Optional[str]:
    """La URL si es una imagen DE VERDAD (200, de tipo imagen y con más bytes que los
    marcadores de «sin imagen»); None si no. Un fallo de red no la tira: no se sabe."""
    if not url:
        return None
    k = ('ok', url)
    if k not in cache:
        import requests
        u = str(url)
        if 'default' in u.rsplit('/', 1)[-1].lower():
            cache[k] = None                      # el escudo genérico de ESPN
        else:
            minimo = next((v for d, v in MINIMO.items() if d in u), MINIMO_GENERAL)
            try:
                with requests.get(u, timeout=10, stream=True, headers={'User-Agent': 'Mozilla/5.0'}) as r:
                    tipo = r.headers.get('content-type', '')
                    leido = 0
                    for trozo in r.iter_content(4096):
                        leido += len(trozo)
                        if leido >= minimo:
                            break
                    cache[k] = u if r.status_code == 200 and tipo.startswith('image') and leido >= minimo else None
            except Exception:
                cache[k] = u
    return cache[k]


def _validar_todas(urls, cache: Dict) -> None:
    from concurrent.futures import ThreadPoolExecutor
    pend = [u for u in set(urls) if u and ('ok', u) not in cache]
    with ThreadPoolExecutor(16) as ex:
        list(ex.map(lambda u: valida(u, cache), pend))


def poner(filas: List[Dict]) -> Dict[str, int]:
    """v467 — CADA escudo de cada tarjeta, validado uno por uno.

    1. Los que ya trae (ESPN) se descargan y se comprueban; el que no es imagen de verdad se quita.
    2. Los que faltan: fútbol de FotMob y luego de Flashscore; tenis (la foto) de 365Scores.
       Cada candidato también se comprueba.
    Lo que quede sin imagen lo pinta la página con su silueta, nunca una letra suelta."""
    cache, hecho = {}, {}
    st = {'quitados': 0, 'completados': 0, 'sin': 0}
    _validar_todas([f.get(c) for f in filas for c in ('logo_h', 'logo_a')], cache)
    for f in filas:
        for c in ('logo_h', 'logo_a'):
            if f.get(c) and not valida(f[c], cache):
                f[c] = None
                st['quitados'] += 1
    for f in filas:
        dep = f.get('deporte')
        if dep not in ('Fútbol', 'Tenis') or (f.get('logo_h') and f.get('logo_a')):
            continue
        k = (f.get('partido'), str(f.get('inicio')))
        if k not in hecho:
            par = [None, None]
            try:
                fuentes = ((lambda: buscar(f.get('partido'), f.get('inicio'), cache, f.get('liga') or '')),
                           (lambda: buscar_fs(f.get('partido'), f.get('inicio'), cache, f.get('liga') or ''))) \
                    if dep == 'Fútbol' else ((lambda: buscar_365(f.get('partido'), f.get('inicio'), cache)),)
                for fuente in fuentes:
                    cand = fuente() or (None, None)
                    _validar_todas(cand, cache)
                    par = [par[0] or valida(cand[0], cache), par[1] or valida(cand[1], cache)]
                    if par[0] and par[1]:
                        break
            except Exception as e:
                logger.debug('[escudos] %s: %s', f.get('partido'), e)
            hecho[k] = par
        antes = bool(f.get('logo_h')) + bool(f.get('logo_a'))
        f['logo_h'], f['logo_a'] = f.get('logo_h') or hecho[k][0], f.get('logo_a') or hecho[k][1]
        st['completados'] += bool(f.get('logo_h')) + bool(f.get('logo_a')) - antes
    st['sin'] = sum((not f.get('logo_h')) + (not f.get('logo_a')) for f in filas if f.get('deporte') in ('Fútbol', 'Tenis'))
    return st
