# -*- coding: utf-8 -*-
"""
v295 — La forma reciente de un equipo, para que la vea quien apuesta.

DE DONDE SALE ESTO
El usuario lo pidió dos veces, y la segunda con un caso concreto: la app le
recomendó «Gana Spaeri» y el Spaeri perdió 1-4 en casa. Su argumento:

    «El error de cuota no basta. Tiene que coincidir con que el equipo también
     es fuerte e históricamente y estadísticamente puede ganar.»

SE MIDIO, Y NO SOBREVIVE COMO FILTRO
Sobre 1.803 picks de Capa 1, con la forma real del local (victorias en sus 10
partidos anteriores, sin mirar el resultado del propio partido):

    forma del local          n     acierta      ROI        p5
    0-2 de cada 10 (malo)   204     49,0 %   +23,25 %   +7,59 %   <- el MEJOR
    2-3 de cada 10          316     43,7 %    +0,89 %  -10,45 %
    3-4 de cada 10          375     47,2 %    +4,67 %   -4,84 %
    4-5 de cada 10          373     48,5 %    +4,25 %   -5,13 %
    5-6 de cada 10          268     56,0 %   +11,44 %   +0,51 %
    6+ de cada 10 (fuerte)  280     65,4 %   +11,78 %   +3,05 %

El usuario tiene razón en que los fuertes ACIERTAN más: 65,4 % contra 49,0 %.
Pero rinden la MITAD, porque cuando un equipo es bueno el precio ya lo sabe.
La curva es una U: el dinero está en los extremos.

Y filtrando, en los dos tramos:

                          ELECCION              JUICIO
    forma >= 30 %     +7,01 % (p5 +0,96)    +8,55 % (p5 -0,49)
    forma >= 40 %     +9,81 % (p5 +3,38)    +6,06 % (p5 -4,23)
    forma >= 50 %    +15,59 % (p5 +7,52)    +3,55 % (p5 -8,70)
    SIN filtrar       +6,89 % (p5 +1,80)   +10,94 % (p5 +2,27)  <- el unico

Cuanto mas se exige, mejor se ve en el pasado y peor sale en el juicio. Es la
firma del sobreajuste, y pasa igual dentro del rango de la Escalera.

POR QUE ESTE MODULO EXISTE DE TODOS MODOS
Porque «no sirve como filtro automatico» no es lo mismo que «no vale nada».
El usuario mira los partidos y tiene criterio; lo que no puede es adivinar la
forma de un equipo de la segunda de Georgia. Asi que el dato se ENSEÑA y la
decision es suya — que es distinto de que el sistema decida por el con una
regla que no ha pasado la puerta.
"""
from __future__ import annotations

import glob
import logging
import unicodedata
from typing import Dict, Optional

logger = logging.getLogger(__name__)

VENTANA = 10          # partidos hacia atras
MIN_PARTIDOS = 5      # menos que esto no se enseña: no dice nada

_CACHE: Optional[Dict[str, Dict]] = None


def _clave(nombre) -> str:
    t = unicodedata.normalize('NFKD', str(nombre or '').lower())
    t = t.encode('ascii', 'ignore').decode('ascii')
    return ''.join(c for c in t if c.isalnum())


def _construir() -> Dict[str, Dict]:
    """{equipo: {'gana': n, 'de': n, 'goles': media, ...}} de los ultimos."""
    import pandas as pd

    por_equipo: Dict[str, list] = {}
    for f in glob.glob('historico_*.csv'):
        try:
            h = pd.read_csv(f, low_memory=False)
        except Exception:
            continue
        c = {x.lower(): x for x in h.columns}
        gh, ga = c.get('home_goals'), c.get('away_goals')
        hm = c.get('home_team') or c.get('home')
        aw = c.get('away_team') or c.get('away')
        fe = c.get('date') or c.get('fecha')
        if not all([gh, ga, hm, aw, fe]):
            continue
        t = h[[fe, hm, aw, gh, ga]].dropna()
        for fecha, loc, vis, g1, g2 in t.itertuples(index=False):
            try:
                g1, g2 = float(g1), float(g2)
            except (TypeError, ValueError):
                continue
            fecha = str(fecha)[:10]
            tot = g1 + g2
            por_equipo.setdefault(_clave(loc), []).append(
                (fecha, 1 if g1 > g2 else (0 if g1 == g2 else -1), tot))
            por_equipo.setdefault(_clave(vis), []).append(
                (fecha, 1 if g2 > g1 else (0 if g1 == g2 else -1), tot))

    fuera = {}
    for eq, partidos in por_equipo.items():
        partidos.sort()
        ult = partidos[-VENTANA:]
        if len(ult) < MIN_PARTIDOS:
            continue
        fuera[eq] = {
            'gana': sum(1 for _, r, _g in ult if r == 1),
            'empata': sum(1 for _, r, _g in ult if r == 0),
            'pierde': sum(1 for _, r, _g in ult if r == -1),
            'de': len(ult),
            'racha': [r for _, r, _g in ult],
            # La media de goles TOTALES de sus partidos, que es lo que predice
            # un mas/menos: a un equipo de partidos locos le da igual meterlos
            # o recibirlos. Se enseña, NO se usa para elegir (ver la cabecera).
            'goles': round(sum(g for _, _r, g in ult) / len(ult), 2),
            'hasta': ult[-1][0],
        }
    return fuera


def cargar(recargar: bool = False) -> Dict[str, Dict]:
    """El mapa entero, cacheado. NUNCA lanza."""
    global _CACHE
    if _CACHE is not None and not recargar:
        return _CACHE
    try:
        _CACHE = _construir()
    except Exception as e:
        logger.warning('[forma] no se pudo construir: %s', e)
        _CACHE = {}
    return _CACHE


def olvidar() -> None:
    global _CACHE
    _CACHE = None


def de(equipo: str) -> Optional[Dict]:
    """La forma de ese equipo, o None si no hay bastantes partidos."""
    try:
        return cargar().get(_clave(equipo))
    except Exception:
        return None


def resumen(equipo: str) -> str:
    """«ganó 6 de sus últimos 10» — o cadena vacía si no se sabe.

    Deliberadamente en palabras y sin porcentaje: el porcentaje invita a
    compararlo con la probabilidad del pick, y NO son la misma cosa. Una es la
    forma reciente; la otra, lo que el precio dice de ESTE partido.
    """
    f = de(equipo)
    if not f:
        return ''
    try:
        return 'ganó %d de sus últimos %d' % (f['gana'], f['de'])
    except (KeyError, TypeError):
        return ''


def del_pick(pick) -> str:
    """El equipo al que apunta un pick: «Gana Nueva Chicago» -> el local."""
    if not isinstance(pick, dict):
        return ''
    # v297.1 — en una combinada la apuesta es «Gana Santos  +  Más de 2.5
    # goles», y quitarle el «Gana» dejaba «Santos + Más de 2.5 goles», que no
    # es el nombre de ningún equipo: la tarjeta se quedaba muda. La primera
    # pata SÍ es el equipo.
    patas = pick.get('patas') or []
    ap = (str((patas[0] or {}).get('texto') or '') if patas
          else str(pick.get('apuesta') or '')).strip()
    for pre in ('Gana ', 'Ganador ', 'Victoria '):
        if ap.startswith(pre):
            return ap[len(pre):].strip()
    par = str(pick.get('partido') or '')
    return par.split(' vs ')[0].strip() if ' vs ' in par else ''


def resumen_pick(pick) -> str:
    """La forma del equipo al que apunta el pick, o cadena vacía."""
    eq = del_pick(pick)
    return resumen(eq) if eq else ''


def goles_del_partido(pick) -> Optional[float]:
    """La media de goles de los dos equipos, o None si falta alguno.

    v296 — El usuario la pidió para la Escalera: «el histórico, la cantidad de
    goles, la media». SE ENSEÑA Y NO SE FILTRA POR ELLA, y esta vez la razón
    está medida sobre 15.411 partidos con cuota real de más/menos 2,5:

        la media del par     overs reales   lo que le da el mercado
        menos de 2,0            41,3 %             40,4 %
        2,0 - 2,4               47,1 %             44,5 %
        2,4 - 2,8               49,7 %             49,2 %
        2,8 - 3,2               55,3 %             54,5 %
        3,2 o más               59,5 %             61,0 %

    O sea que la media ACIERTA —de 41 % a 59 %, monotona— y el precio la
    clava igual de bien. Apostar cuando ambas discrepan pierde entre el 9 % y
    el 14 %, igual en los dos tramos, porque el margen medio de la pareja
    over/under es del 6,51 % y no hay ventaja con la que pagarlo.

    Sirve para que el usuario entienda la apuesta, no para elegirla.
    """
    par = str((pick or {}).get('partido') or '') if isinstance(pick, dict) \
        else ''
    if ' vs ' not in par:
        return None
    loc, _, vis = par.partition(' vs ')
    a, b = de(loc.strip()), de(vis.strip())
    if not a or not b:
        return None
    try:
        return round((float(a['goles']) + float(b['goles'])) / 2.0, 2)
    except (KeyError, TypeError, ValueError):
        return None


def main() -> int:
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    m = cargar()
    print('equipos con forma medida: %s' % format(len(m), ',d'))
    for eq in ('Spaeri', 'Dila Gori', 'Dobrudzha', 'CSKA Sofia II',
               'Petrolul', 'Nueva Chicago'):
        print('   %-18s %s' % (eq, resumen(eq) or '(sin datos)'))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
