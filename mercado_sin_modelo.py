# -*- coding: utf-8 -*-
"""
v313 — LOS PARTIDOS SIN MODELO PROPIO TAMBIÉN DICEN «METER», CON EL PRECIO
DE PINNACLE Y UNA REGLA MEDIDA.

EL ENCARGO
El usuario, con la Capa 1 abierta: «me estás mandando juegos de Sub 21, Sub
19, Japón, entre otras ligas, y en las apuestas del día no aparecen, y en lo
que me mandas a Telegram tampoco. La idea es que esté absolutamente todo…
pero haz las simulaciones para tener un porcentaje de acierto igual de alto o
mayor que el que ya tenemos. Eso no tiene que bajar».

POR QUÉ NO APARECÍAN
La Capa 1 no usa el modelo: compara el precio justo de Pinnacle con el de
las casas mexicanas (`barrido_capa1`), así que ve TODO el tablero. Las
apuestas del día y Telegram salen del modelo, y el modelo no cubre sub-21,
sub-19, la Copa de la J.League o la liga galesa. Esos partidos llegaban a
Telegram como un renglón suelto de «MERCADOS», sin hora y sin veredicto, y a
la aplicación no llegaban.

QUÉ SE HACE
Para los partidos del tablero que el modelo NO cubre, la probabilidad es la
de Pinnacle sin margen (la casa de referencia de todo el proyecto, con el
mismo devigado «potencia» de la Capa 1) y el precio el mejor de las casas del
usuario. Se dice «meter» con esta regla:

    probabilidad de Pinnacle entre 80 % y 90 %, cuota entre 1,10 y 1,35,
    y sólo «gana el local» o «local o empate». Una por partido.

POR QUÉ MÁS ALTA QUE LA DEL MODELO (70-80 %)
Pinnacle está calibrada: si dice 75 %, acierta ~75 %, y eso está POR DEBAJO
de lo que ya acierta lo que el modelo dice «meter» (76-81 %). Con la misma
franja que el modelo, estos partidos habrían BAJADO el acierto. Para que no
baje hay que pedirles más.

LA MEDICIÓN (`_v313_sin_modelo.py`), sin mirar el resultado al elegir
Réplica real del 20 al 28 de septiembre: la última captura de Pinnacle
(`radar_capturas.csv`) y la última foto de las casas mexicanas
(`cuotas_mx.json`), las dos ANTERIORES al inicio y sacadas de git con la
hora de cada commit; liquidado con el marcador de FotMob. Mismos tramos que
la v312: elección hasta el 26, prueba 27-28.

                                              elección       prueba
    misma regla del modelo (70-80 %, todo)   79,7 % (79)    66,7 % (21)
    70-80 %, local / local o empate          78,6 % (56)    70,6 % (17)
    75-85 %, local / local o empate          83,6 % (67)    83,3 % (18)
    80-90 %, los cuatro                      83,6 % (67)    91,7 % (24)
    80-90 %, local / local o empate  ← ESTA  94,0 % (50)    88,2 % (17)

Y lo que decide, sumadas a lo que el modelo ya dice «meter» (v312):

                     sólo el modelo        con estos partidos
    elección         74,8 % (499)    →     76,5 % (549)
    prueba           80,8 % (125)    →     81,7 % (142)
    hoy (28 sep)     78,2 % (55)     →     80,0 % (60)

Con muestra grande (`pick_ledger_total.csv`, gana el local con Pinnacle
80-90 % y cuota 1,10-1,35, 2018-2026): 82,8 % (795) y 84,7 % (347).

Lo que NO se hace: en los partidos que el modelo sí cubre manda el modelo.
Y no entra el visitante (en 1X2 sólo hay 16 en la réplica: no hay con qué
juzgarlo). La cuota mínima de 1,10 deja fuera los 1,03-1,08, que no pagan
el riesgo de un rojo.

Lo que no cambia: el precio sigue teniendo margen de la casa. A cuota ~1,17,
un solo rojo se come seis verdes.
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

TABLERO = 'cuotas_mx.json'
CASAS = ('Calientemx', '1xBet', 'Winpot', 'Novibet', 'Sportium.mx', 'Playdoit')

P_MIN = 0.80
P_MAX = 0.90
CUOTA_MIN = 1.10
CUOTA_MAX = 1.35
LADOS_METER = ('home', 'homeOrDraw')

# Selecciones: la casa y el modelo no escriben igual el país.
_ALIAS = {
    'usa': 'united states', 'us': 'united states', 'eeuu': 'united states',
    'korea republic': 'south korea', 'republic of korea': 'south korea',
    'korea dpr': 'north korea', 'ir iran': 'iran', 'turkiye': 'turkey',
    'czechia': 'czech republic', "cote d'ivoire": 'ivory coast',
    'cote divoire': 'ivory coast', 'bosnia & herzegovina':
    'bosnia and herzegovina', 'china pr': 'china',
}


def _norm(nombre: str) -> str:
    t = re.sub(r'\s+', ' ', str(nombre or '').strip().lower())
    return _ALIAS.get(t, t)


def _categoria(nombre: str) -> str:
    """«U19», «U21», «W» (femenino)… lo que separa dos equipos del mismo
    país. Dos nombres con distinta categoría nunca son el mismo equipo."""
    m = re.search(r'\bu[- ]?(\d{2})\b', str(nombre or '').lower())
    return 'u' + m.group(1) if m else ''


def mismo_equipo(a: str, b: str) -> bool:
    if _categoria(a) != _categoria(b):
        return False
    na, nb = _norm(re.sub(r'\bu[- ]?\d{2}\b', '', a, flags=re.I)), \
        _norm(re.sub(r'\bu[- ]?\d{2}\b', '', b, flags=re.I))
    if na == nb:
        return True
    # «South Sudan» no es «Sudan» (ver `name_mapper.CALIFICADORES_OTRO_EQUIPO`)
    try:
        import name_mapper as nm
        sobra = set(na.split()) ^ set(nb.split())
        if sobra & nm.CALIFICADORES_OTRO_EQUIPO and frozenset((na, nb))                 not in nm.MISMO_EQUIPO_CON_CALIFICADOR:
            return False
    except Exception:
        pass
    try:
        import cuotas_multi as cm
        return cm._sim_club(na, nb) >= 0.8
    except Exception:
        return False


def _lados(partido: str) -> Optional[Tuple[str, str]]:
    txt = str(partido or '')
    if ' vs ' in txt:
        h, a = [x.strip() for x in txt.split(' vs ', 1)]
        return (h, a) if h and a else None
    if ' @ ' in txt:
        a, h = [x.strip() for x in txt.split(' @ ', 1)]
        return (h, a) if h and a else None
    return None


def mismo_partido(p1: str, p2: str) -> bool:
    l1, l2 = _lados(p1), _lados(p2)
    if not (l1 and l2):
        return False
    return mismo_equipo(l1[0], l2[0]) and mismo_equipo(l1[1], l2[1])


# ---------------------------------------------------------------------------
def _cargar(ruta: str = TABLERO) -> Dict:
    try:
        with open(ruta, encoding='utf-8') as f:
            return (json.load(f) or {}).get('partidos') or {}
    except Exception as e:
        logger.debug('[sin_modelo] tablero: %s', e)
        return {}


def _mejores(v: Dict) -> Dict[str, Tuple[float, str]]:
    """Mejor cuota de las casas del usuario, 1X2 y doble oportunidad."""
    mejor: Dict[str, Tuple[float, str]] = {}
    for casa, m in (v.get('casas') or {}).items():
        if casa not in CASAS:
            continue
        for merc, lados in (('HOME_DRAW_AWAY', ('home', 'draw', 'away')),
                            ('DOUBLE_CHANCE', ('homeOrDraw', 'awayOrDraw'))):
            x = (m or {}).get(merc) or {}
            for lado in lados:
                try:
                    q = float(x.get(lado))
                except (TypeError, ValueError):
                    continue
                if q > 1 and q > mejor.get(lado, (0.0, ''))[0]:
                    mejor[lado] = (q, casa)
    return mejor


def _pinnacle(home: str, away: str) -> Optional[Dict[str, float]]:
    try:
        import cuotas_multi as cm
        pin = (cm.cuotas_partido('futbol', home, away) or {}).get('pinnacle') or {}
        q = [float(pin.get(k) or 0) for k in ('home', 'draw', 'away')]
        if min(q) <= 1:
            return None
        return {'home': q[0], 'draw': q[1], 'away': q[2]}
    except Exception as e:
        logger.debug('[sin_modelo] pinnacle %s vs %s: %s', home, away, e)
        return None


def justas(pin: Dict[str, float]) -> Dict[str, float]:
    """Probabilidad sin margen con el devigado de todo el proyecto
    (`cuotas_multi.devig`, «potencia»: el medido mejor, y el de la Capa 1,
    para que el mismo partido no salga con dos probabilidades distintas)."""
    import cuotas_multi as cm
    f = dict(cm.devig({k: float(pin[k]) for k in ('home', 'draw', 'away')},
                      metodo='potencia'))
    f['homeOrDraw'] = f['home'] + f['draw']
    f['awayOrDraw'] = f['away'] + f['draw']
    return f


def _texto(lado: str, h: str, a: str) -> Tuple[str, str]:
    return {'home': ('1X2', 'Gana %s' % h), 'draw': ('1X2', 'Empate'),
            'away': ('1X2', 'Gana %s' % a),
            'homeOrDraw': ('Doble oportunidad', '%s o empate' % h),
            'awayOrDraw': ('Doble oportunidad', '%s o empate' % a)}[lado]


def pick_de(v: Dict, pin: Dict[str, float]) -> Dict:
    """El pronóstico «de mercado» de un partido del tablero."""
    import horario as hz
    import nombres_ligas as nl
    h, a = str(v['home']), str(v['away'])
    f = justas(pin)
    q = _mejores(v)
    mercados = []
    for lado in ('home', 'draw', 'away', 'homeOrDraw', 'awayOrDraw'):
        merc, apuesta = _texto(lado, h, a)
        cuota, casa = q.get(lado, (None, None))
        mercados.append({
            'mercado': merc, 'apuesta': apuesta, 'lado': lado,
            'prob': round(f[lado], 4), 'cuota': cuota, 'casa': casa,
            'cuota_justa': round(1 / f[lado], 3) if f[lado] > 0 else None,
            'ev': round(f[lado] * cuota - 1, 4) if cuota else None})
    ini = hz._a_utc(v.get('inicio'))
    liga = str(v.get('liga') or '')
    p = {
        'deporte': 'Fútbol', 'partido': '%s vs %s' % (h, a),
        'liga': nl.canonica(liga, liga.lower(), 'Fútbol'),
        'liga_origen': liga, 'clave_liga': liga.lower(),
        'inicio': ini.strftime('%Y-%m-%d %H:%M:%S') if ini else v.get('inicio'),
        'fecha': hz.fecha(v.get('inicio')),
        'solo_mercado': True,
        'pinnacle': pin,
        'board': {'Gana %s' % h: round(f['home'], 4),
                  'Empate': round(f['draw'], 4),
                  'Gana %s' % a: round(f['away'], 4)},
        'mercados': mercados,
        'motivo_modelo': ('Sin modelo propio para esta competición: las '
                          'probabilidades son las de Pinnacle sin margen.'),
    }
    top = max(mercados[:3], key=lambda m: m['prob'])
    p.update({'mercado': top['mercado'], 'apuesta': top['apuesta'],
              'prob': top['prob'], 'cuota': top['cuota'], 'casa': top['casa']})
    hz.anotar(p)
    return p


def recomendadas(pick: Dict) -> List[Dict]:
    """Lo que se mete en un partido sin modelo: como mucho UNA, con la regla
    medida. Misma forma que `modo_modelo.recomendadas` para que la tarjeta,
    Telegram y el archivo de finalizados la traten igual."""
    fuera = []
    for m in (pick.get('mercados') or []):
        if m.get('lado') not in LADOS_METER or not m.get('cuota'):
            continue
        p, q = float(m['prob']), float(m['cuota'])
        if not (P_MIN <= p <= P_MAX and CUOTA_MIN <= q < CUOTA_MAX):
            continue
        fuera.append({
            'apuesta': m['apuesta'], 'mercado': m['mercado'],
            'bloque': 'resultado', 'etiqueta': m['mercado'],
            'prob': p, 'prob_meter': p, 'p_mercado': p,
            'cuota': q, 'casa': m.get('casa'), 'ev': m.get('ev'),
            'veredicto_vp': 'meter', 'origen': 'pinnacle',
            'razon': ('Pinnacle, sin su margen, le da %.0f %%; regla medida '
                      'para partidos sin modelo (acertó 92 %% en la réplica '
                      'del 20-28 sep)' % (100 * p))})
    fuera.sort(key=lambda x: -x['prob'])
    return fuera[:1]


def _del_modelo(datos: Dict) -> List[Tuple[str, str]]:
    return [(str(p.get('fecha') or '')[:10], str(p.get('partido') or ''))
            for p in (datos.get('pronosticos') or [])
            if isinstance(p, dict) and str(p.get('deporte') or 'Fútbol') == 'Fútbol']


def _en_capa(datos: Dict) -> List[Tuple[str, str]]:
    fuera = []
    for lista in ('capa1', 'capa2', 'elite'):
        for p in (datos.get(lista) or []):
            if isinstance(p, dict) and str(p.get('deporte') or '').startswith('F'):
                fuera.append((str(p.get('fecha') or '')[:10], str(p.get('partido'))))
    return fuera


def construir(datos: Dict, ruta: str = TABLERO) -> List[Dict]:
    """Los partidos de fútbol del tablero que el modelo no cubre y que o bien
    tienen algo que meter con la regla medida, o bien están en la Capa 1 /
    Capa 2 (para que lo que se ve ahí aparezca también en el día). NUNCA
    lanza."""
    import time
    try:
        modelo = _del_modelo(datos)
        capa = _en_capa(datos)
        ahora = time.time()
        fuera: List[Dict] = []
        for v in _cargar(ruta).values():
            if v.get('deporte') != 'futbol' or not v.get('home'):
                continue
            try:
                if float(v.get('inicio')) <= ahora:
                    continue
            except (TypeError, ValueError):
                continue
            par = '%s vs %s' % (v['home'], v['away'])
            import horario as hz
            dia = hz.fecha(v.get('inicio'))
            if any(mismo_partido(par, x) for d, x in modelo
                   if not d or not dia or abs(_dias(d, dia)) <= 1):
                continue
            pin = _pinnacle(v['home'], v['away'])
            if not pin:
                continue
            p = pick_de(v, pin)
            en_capa = any(mismo_partido(par, x) for _d, x in capa)
            if recomendadas(p) or en_capa:
                fuera.append(p)
        logger.info('[sin_modelo] %d partidos de mercado', len(fuera))
        return fuera
    except Exception as e:
        logger.warning('[sin_modelo] no se pudo construir: %s', e)
        return []


def _dias(a: str, b: str) -> int:
    import datetime as _dt
    try:
        return (_dt.date.fromisoformat(a[:10]) - _dt.date.fromisoformat(b[:10])).days
    except Exception:
        return 0
