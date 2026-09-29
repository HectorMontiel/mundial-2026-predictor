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

v314 — GOLES EN ESTOS PARTIDOS, Y LOS PATRONES DE CADA LIGA
El usuario: «para los otros modelos también arma Over/Under de goles, global
y por equipo, córners y tarjetas; analiza los patrones de cada liga chica
(equipos muy fuertes, local grande, muchos o pocos goles, muchas tarjetas) y
simula con los partidos finalizados». Medido en `_v314_ligas_chicas.py` con
753 partidos sin modelo de 140 ligas (19-28 sep) y dos meses de resultados
de FotMob para los patrones (15.464 partidos, 298 ligas):

  · LOS PATRONES DE LIGA NO SUMAN A LA CUOTA. Las ligas son muy distintas
    (Irán 1,75 goles por partido, 3.ª noruega casi 5; el local gana el 64 %
    en Nigeria), pero las casas ya lo tienen en el precio: mezclar el patrón
    de la liga con la probabilidad de la casa EMPEORA el Brier en 1X2 y en
    goles, y en ambos marcan no pasa la prueba (p5 −0,00199). No se usan.
  · MÁS DE 1,5 GOLES SÍ SE METE: probabilidad de las casas (media de las del
    usuario sin margen) entre 80 % y 90 %, cuota 1,10-1,35. Elegida en los
    días de elección entre 15 reglas: 86,6 % (232); en prueba 93,9 % (33);
    el 28 de septiembre 9 de 9. Sumada a todo lo que ya se dice «meter»:
    elección 76,5 → 79,5 %, prueba 81,7 → 84,0 %, 28-sep 80,0 → 82,6 %.
  · MENOS DE 3,5 y AMBOS MARCAN no entran: menos de 3,5 al 80-90 % se quedó
    en 75,5 % en elección, y ambos marcan casi no tiene muestra (4-21).
  · GOLES POR EQUIPO: las casas del usuario no los cotizan en estas ligas.
    Se enseñan como DATO (de las λ que reproducen el 1X2 y el más/menos de
    las casas): «más de 0,5» sale bien calibrado (80-90 % → 87,7 % real);
    «más de 1,5» promete un poco de más (80-90 % → 81,2 %).
  · CÓRNERS Y TARJETAS: en estas ligas ni FotMob publica la estadística
    (National League, Liga de Expansión, Primera Nacional, Uruguay: 0 de
    33 fichas) ni las casas del usuario la cotizan. Sin datos no hay regla:
    no se ofrecen.
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
# v314 — goles en partidos sin modelo (ver el docstring)
GOLES_METER = ('mas_1.5',)
GOLES_P_MIN, GOLES_P_MAX = 0.80, 0.90
LINEAS_GOLES = (1.5, 2.5, 3.5)

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


def goles_casas(v: Dict) -> Dict[str, Tuple[float, float, str]]:
    """v314 — más/menos 1,5/2,5/3,5 y ambos marcan: la media de las casas del
    usuario, cada una sin su margen, y la mejor cuota. {sel: (prob, cuota,
    casa)}."""
    import cuotas_multi as cm
    probs: Dict[str, list] = {}
    mejor: Dict[str, Tuple[float, str]] = {}

    def _add(sel, p, q, casa):
        probs.setdefault(sel, []).append(p)
        if q and q > mejor.get(sel, (0.0, ''))[0]:
            mejor[sel] = (float(q), casa)
    for casa, m in (v.get('casas') or {}).items():
        if casa not in CASAS:
            continue
        bt = (m or {}).get('BOTH_TEAMS_TO_SCORE') or {}
        try:
            if bt.get('yes') and bt.get('no'):
                f = cm.devig({'s': float(bt['yes']), 'n': float(bt['no'])},
                             metodo='potencia')
                _add('btts_si', f['s'], bt['yes'], casa)
                _add('btts_no', f['n'], bt['no'], casa)
        except Exception:
            pass
        for ln in (((m or {}).get('OVER_UNDER') or {}).get('lineas') or []):
            L = ln.get('linea')
            if L not in LINEAS_GOLES or not (ln.get('over') and ln.get('under')):
                continue
            try:
                f = cm.devig({'o': float(ln['over']), 'u': float(ln['under'])},
                             metodo='potencia')
            except Exception:
                continue
            _add('mas_%s' % L, f['o'], ln['over'], casa)
            _add('menos_%s' % L, f['u'], ln['under'], casa)
    return {k: (sum(v) / len(v),) + mejor.get(k, (None, None))
            for k, v in probs.items()}


def lambdas_mercado(p_home: float, p_away: float,
                    p_mas25: Optional[float]) -> Optional[Tuple[float, float]]:
    """v314 — λ de Poisson de cada equipo que reproducen el 1X2 y el más de
    2,5 del mercado: de ahí salen los goles por equipo, que no se cotizan."""
    try:
        import numpy as np
        lh, la, PH, PA, PO = _rejilla()
        e = (PH - p_home) ** 2 + (PA - p_away) ** 2
        if p_mas25 is not None:
            e = e + (PO - p_mas25) ** 2
        i, j = np.unravel_index(np.argmin(e), e.shape)
        return round(float(lh[i]), 2), round(float(la[j]), 2)
    except Exception:
        return None


_REJ = None


def _rejilla():
    """P(local), P(visita) y P(más de 2,5) de Poisson para cada par de λ."""
    global _REJ
    if _REJ is None:
        import math
        import numpy as np
        lh = np.arange(0.2, 4.01, 0.05)
        la = np.arange(0.2, 3.51, 0.05)
        k = np.arange(11)
        fac = np.array([math.factorial(i) for i in k], dtype=float)
        ph = np.exp(-lh)[:, None] * lh[:, None] ** k / fac
        pa = np.exp(-la)[:, None] * la[:, None] ** k / fac
        M = ph[:, None, :, None] * pa[None, :, None, :]
        ti, tj = np.meshgrid(k, k, indexing='ij')
        _REJ = (lh, la, (M * (ti > tj)).sum(axis=(2, 3)),
                (M * (ti < tj)).sum(axis=(2, 3)),
                (M * ((ti + tj) >= 3)).sum(axis=(2, 3)))
    return _REJ


def goles_equipo(lam: Optional[Tuple[float, float]]) -> Dict[str, float]:
    """P(más de 0,5 / 1,5) de cada equipo con esas λ."""
    import math
    if not lam:
        return {}
    out = {}
    for lado, l in (('local', lam[0]), ('visita', lam[1])):
        p0 = math.exp(-l)
        out['%s_0.5' % lado] = 1 - p0
        out['%s_1.5' % lado] = 1 - p0 - l * p0
    return out


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


def unox2_casas(v: Dict) -> Optional[Dict[str, float]]:
    """v314 — el 1X2 sin margen de las casas del usuario (media), para los
    partidos que Pinnacle no cotiza."""
    import cuotas_multi as cm
    acc = {'home': [], 'draw': [], 'away': []}
    for casa, m in (v.get('casas') or {}).items():
        x = ((m or {}).get('HOME_DRAW_AWAY') or {}) if casa in CASAS else {}
        try:
            f = cm.devig({k: float(x[k]) for k in acc}, metodo='potencia')
        except Exception:
            continue
        for k in acc:
            acc[k].append(f[k])
    if not acc['home']:
        return None
    f = {k: sum(v_) / len(v_) for k, v_ in acc.items()}
    f['homeOrDraw'] = f['home'] + f['draw']
    f['awayOrDraw'] = f['away'] + f['draw']
    return f


def pick_de(v: Dict, pin: Optional[Dict[str, float]]) -> Dict:
    """El pronóstico «de mercado» de un partido del tablero. Con Pinnacle, su
    1X2 sin margen; sin él (v314), el de las casas del usuario."""
    import horario as hz
    import nombres_ligas as nl
    h, a = str(v['home']), str(v['away'])
    f = justas(pin) if pin else unox2_casas(v)
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
    # v314 — goles y ambos marcan de las casas del usuario
    textos = {'btts_si': 'Ambos marcan: Sí', 'btts_no': 'Ambos marcan: No'}
    for L in LINEAS_GOLES:
        textos['mas_%s' % L] = 'Goles: Más de %s' % L
        textos['menos_%s' % L] = 'Goles: Menos de %s' % L
    gc = goles_casas(v)
    for sel in sorted(gc, key=lambda s: list(textos).index(s)):
        pr, cuota, casa = gc[sel]
        mercados.append({
            'mercado': 'BTTS' if sel.startswith('btts') else 'Goles',
            'apuesta': textos[sel], 'lado': sel, 'prob': round(pr, 4),
            'cuota': cuota, 'casa': casa, 'fuente': 'casas',
            'cuota_justa': round(1 / pr, 3) if pr > 0 else None,
            'ev': round(pr * cuota - 1, 4) if cuota else None})
    lam = lambdas_mercado(f['home'], f['away'],
                          (gc.get('mas_2.5') or (None,))[0])
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
        'lambdas_mercado': lam,
        'motivo_modelo': ('Sin modelo propio para esta competición: las '
                          'probabilidades son las de %s sin margen.'
                          % ('Pinnacle' if pin else 'las casas')),
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
    fuera, goles = [], []
    for m in (pick.get('mercados') or []):
        if m.get('lado') in GOLES_METER and m.get('cuota'):
            p, q = float(m['prob']), float(m['cuota'])
            if GOLES_P_MIN <= p <= GOLES_P_MAX and CUOTA_MIN <= q < CUOTA_MAX:
                goles.append({
                    'apuesta': m['apuesta'], 'mercado': 'Goles',
                    'bloque': 'goles', 'etiqueta': 'Total',
                    'linea': 1.5, 'prob': p, 'prob_meter': p, 'p_mercado': p,
                    'cuota': q, 'casa': m.get('casa'), 'ev': m.get('ev'),
                    'veredicto_vp': 'meter', 'origen': 'casas',
                    'razon': ('las casas, sin su margen, le dan %.0f %%; regla '
                              'medida en ligas sin modelo (86,6 %% y 93,9 %% en '
                              'los dos tramos)' % (100 * p))})
            continue
        if m.get('lado') not in LADOS_METER or not m.get('cuota') \
                or not pick.get('pinnacle'):
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
    # una de resultado (Pinnacle) y una de goles (casas), como la tarjeta
    return fuera[:1] + goles[:1]


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
            if not pin and not unox2_casas(v):
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
