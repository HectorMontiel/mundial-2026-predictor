# -*- coding: utf-8 -*-
"""v243 — La segunda opinión: qué dice la casa de ESTA apuesta.

EL ENCARGO
«Lo importante para saber por cuál irnos y que muestres verde en alguno de los
dos es hacer la correlación con el histórico, con estadísticas, con el mercado
actual, con el rendimiento de cada uno de los equipos, y así puedes tomar una
decisión donde las probabilidades sean muy parejas.»

LO QUE FALTABA
`veredicto_pick.evaluar` usaba DOS cosas: la probabilidad del modelo y la
corrección por lo que ese mercado ha acertado históricamente. El precio que la
casa publica en ese mismo momento —una estimación independiente del mismo
suceso, hecha por gente que se juega dinero— no entraba en la cuenta.

LO MEDIDO
Sobre `pick_ledger.csv` (47.948 partidos) y `pick_ledger_totales.csv` (47.794),
mezclando `p = w·modelo + (1−w)·mercado` con `w` ajustado walk-forward:

    1X2 gana el local    logloss 0,64324 -> 0,62660   p5 +0,0139   100 %
    1X2 empate                   0,57632 -> 0,56895   p5 +0,0057   100 %
    1X2 gana visitante           0,57270 -> 0,55800   p5 +0,0122   100 %
    Goles Más de 2.5             0,72436 -> 0,67667   p5 +0,0436   100 %

Y por bandas, la concordancia separa muchísimo. En «Más de 2.5», banda 60-70 %:

    concordantes con el mercado   dice 64,6 %   acierta 63,7 %
    discordantes                  dice 64,6 %   acierta 49,7 %

Cuando el modelo se aparta del mercado, el que se equivoca es el modelo. La
discrepancia NO es ventaja: es error.

LO QUE ESA MEDICIÓN **NO** AUTORIZA A CONCLUIR
El ledger guarda cuotas de CIERRE (`build_pick_ledger.py`: `WHERE fase =
'cierre'`), y el cierre ya incorpora alineaciones, noticias y dinero de última
hora que el modelo no tenía. Batir al cierre es casi imposible por
construcción, así que la mejora medida es una COTA SUPERIOR.

Se intentó rehacer la medición con los `snapshot` pre-partido de
`odds_historico.db`, que es lo que la app tiene delante al publicar. No se
pudo: cubren 2026-07-28..09-06 y los ledgers acaban el 28-07, así que no
cruzan; y no hay ni un partido con snapshot Y cierre, de modo que tampoco se
puede medir cuánto se mueve la línea entre ambos momentos.

POR ESO NO SE USA EL `w` QUE DICEN LOS DATOS. El óptimo medido es w=0 —el
mercado solo, sin modelo— en los cuatro mercados. Creérselo sería creerse del
todo una medición que sabemos inflada. Se usa **w = 0,5**, que sobre esos
mismos datos captura ~76 % de la mejora disponible:

    Más de 2.5     modelo 0,72455   w=0,5: 0,68740   w=0: 0,67579
    1X2 local      modelo 0,64191   w=0,5: 0,62889   w=0: 0,62484

Es una elección deliberadamente por debajo de lo que el dato sugiere, porque el
dato exagera. Si algún día hay ledger con cuotas pre-partido, se vuelve a medir
y `PESO_MODELO` se mueve con evidencia limpia, no antes.

DÓNDE ENCAJA
`veredicto_pick.evaluar` aplica primero su corrección histórica —que arregla el
sesgo propio del modelo— y DESPUÉS mezcla con la casa. No es corregir dos
veces: lo primero endereza la estimación del modelo, lo segundo la promedia con
una estimación independiente.

QUÉ **NO** HACE
· No inventa probabilidad donde no hay precio. Si la casa no cotiza ese
  mercado, devuelve `None` y el veredicto sigue exactamente como estaba.
· No toca el motor de valor. `valor_apuesta` sigue buscando la casa que paga
  por encima del precio justo de Pinnacle, y de ahí sale el EV. Esto corrige
  con qué se DECIDE y qué se MUESTRA, no de dónde sale la ventaja.
· No cubre córners, tarjetas ni remates: de esos no hay libro de dos lados en
  `implicitas`, y de-marginar media cuota daría un número inventado.
"""
from typing import Dict, List, Optional

import logging
import re

logger = logging.getLogger(__name__)

# Mitad y mitad. Ver arriba: el óptimo medido es 0,0 y no se usa porque la
# medición está sesgada a favor del mercado.
PESO_MODELO = 0.5

# Margen admisible de un libro de dos o tres salidas. Por debajo de 1 no es un
# libro (habría arbitraje seguro y es más probable que falte un lado); por
# encima de 1,60 el margen es tan bestia que de-marginar no significa nada.
SUMA_MINIMA = 1.0
SUMA_MAXIMA = 1.60

# Hasta aquí se considera que las dos fuentes dicen lo mismo.
BRECHA_ACUERDO = 0.03
BRECHA_CHOQUE = 0.08


def _f(x) -> Optional[float]:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v else None


def demarginar(cuotas: List, salidas_por_seleccion: int = 1
               ) -> Optional[List[float]]:
    """Probabilidades implícitas de un libro, sin el margen de la casa.

    Un 1X2 a 2,05 / 3,20 / 4,00 suma 1,0503 en inversas: ese 5 % de más es la
    comisión, no probabilidad. Repartirla proporcionalmente es lo que hace
    comparable el precio con el modelo.

    `salidas_por_seleccion` vale 2 en la doble oportunidad: ahí cada resultado
    aparece en dos de las tres selecciones, así que las probabilidades suman 2
    y no 1. Comprobado con Getafe-Málaga: 1X/12/X2 a 1,231/1,333/1,733 da
    0,759/0,701/0,539, que cuadra con el 1X2 de la misma casa
    (0,471+0,295=0,766 · 0,471+0,234=0,705 · 0,295+0,234=0,529).

    Devuelve `None` si falta algún lado: media cuota no es un libro.
    """
    vals = [_f(c) for c in cuotas]
    if not vals or any(v is None or v <= 1.0 for v in vals):
        return None
    inv = [1.0 / v for v in vals]
    s = sum(inv) / float(salidas_por_seleccion)
    if not (SUMA_MINIMA <= s <= SUMA_MAXIMA):
        return None
    return [i / s for i in inv]


_RE_LINEA = re.compile(r'(\d+(?:[.,]\d+)?)')


def _linea(texto: str) -> Optional[str]:
    m = _RE_LINEA.search(str(texto or ''))
    return m.group(1).replace(',', '.') if m else None


def _equipos(pick: Dict):
    """(local, visitante). En MLB y NFL el partido se escribe «visita @ local»."""
    partido = str((pick or {}).get('partido') or '')
    if ' @ ' in partido:
        a, h = partido.split(' @ ', 1)
        return h.strip().lower(), a.strip().lower()
    for sep in (' vs ', ' - '):
        if sep in partido:
            h, a = partido.split(sep, 1)
            return h.strip().lower(), a.strip().lower()
    return '', ''


def _es_mas(etiqueta: str) -> bool:
    e = etiqueta.lower()
    return 'más de' in e or 'mas de' in e or 'over' in e


def prob_mercado(pick: Dict, apuesta: str,
                 mercado: str = '') -> Optional[float]:
    """Lo que la casa dice de ESTA apuesta, sin su margen. `None` si no cotiza.

    Se parte siempre de las CUOTAS y no de los campos ya calculados, para que
    haya una sola definición de «probabilidad de mercado» en todos los
    deportes.
    """
    imp = (pick or {}).get('implicitas') or {}
    et = str(apuesta or '').strip()
    etb = et.lower()
    merc = str(mercado or '').strip().lower()
    home, away = _equipos(pick)

    # ---- doble oportunidad (antes que el 1X2: «X o empate» lleva «o empate»)
    cdo = imp.get('doble_cuotas') or {}
    if cdo and (' o empate' in etb or etb.startswith('empate o ')):
        probs = demarginar([cdo.get('1X'), cdo.get('12'), cdo.get('X2')],
                           salidas_por_seleccion=2)
        if probs:
            nombre = etb.replace(' o empate', '').replace('empate o ', '')
            nombre = nombre.strip()
            if home and nombre == home:
                return min(0.99, probs[0])
            if away and nombre == away:
                return min(0.99, probs[2])

    # ---- 1X2 -------------------------------------------------------------
    c1x2 = imp.get('1x2_cuotas') or {}
    if c1x2 and (etb in ('empate', 'x') or etb.startswith('gana ')):
        probs = demarginar([c1x2.get('home'), c1x2.get('draw'),
                            c1x2.get('away')])
        if probs:
            if etb in ('empate', 'x'):
                return probs[1]
            nombre = et[5:].strip().lower()
            if home and nombre == home:
                return probs[0]
            if away and nombre == away:
                return probs[2]

    # ---- ambos marcan ----------------------------------------------------
    cb = imp.get('btts_cuotas') or {}
    if cb and 'ambos marcan' in etb:
        probs = demarginar([cb.get('si'), cb.get('no')])
        if probs:
            return probs[0] if etb.rstrip('.').endswith(('sí', 'si')) \
                else probs[1]

    # ---- goles (fútbol) --------------------------------------------------
    if 'goles' in merc or etb.startswith('goles'):
        lin = _linea(et)
        g = (imp.get('goles') or {}).get(lin) if lin else None
        if isinstance(g, dict):
            probs = demarginar([g.get('mas'), g.get('menos')])
            if probs:
                return probs[0] if _es_mas(etb) else probs[1]

    # ---- totales de MLB / NFL -------------------------------------------
    ct = imp.get('totales_cuotas') or {}
    if ct and ('total' in merc or 'puntos' in etb or 'carreras' in etb):
        lin = _linea(et)
        t = ct.get(lin) if lin else None
        if isinstance(t, dict):
            probs = demarginar([t.get('mas'), t.get('menos')])
            if probs:
                return probs[0] if _es_mas(etb) else probs[1]

    # ---- moneyline de dos vías (MLB, NFL, tenis) -------------------------
    cm2 = imp.get('ml_cuotas') or imp.get('moneyline_cuotas') or {}
    if cm2 and etb.startswith('gana '):
        probs = demarginar([cm2.get('home'), cm2.get('away')])
        if probs:
            nombre = et[5:].strip().lower()
            if home and nombre == home:
                return probs[0]
            if away and nombre == away:
                return probs[1]
    return None


def mezclar(p_modelo, p_mercado) -> Optional[float]:
    """La probabilidad con la que hay que decidir. `None` si falta una."""
    a, b = _f(p_modelo), _f(p_mercado)
    if a is None or b is None:
        return None
    return max(0.01, min(0.99, PESO_MODELO * a + (1.0 - PESO_MODELO) * b))


def evaluar(pick: Dict, apuesta: str, mercado: str = '',
            prob_modelo=None) -> Dict:
    """La segunda opinión, lista para decidir y para pintar.

    `brecha` es cuánto se separan las dos fuentes. Es lo que el usuario pidió
    para los partidos parejos: si dicen lo mismo, el número es de fiar; si se
    separan, lo medido es que el que falla es el modelo.
    """
    pm = _f(prob_modelo)
    if pm is None:
        pm = _f((pick or {}).get('prob'))
    # La fila de recomendación que le llega a `veredicto_pick` NO lleva
    # `implicitas` ni `partido` —son del partido, no de la apuesta—, así que
    # `modo_modelo._enriquece` deja aquí el precio ya resuelto. Si no está, se
    # busca por el camino largo, que es el que sirve cuando lo que llega es el
    # pick entero (MLB, tenis).
    pmer = _f((pick or {}).get('p_mercado'))
    if pmer is None:
        pmer = prob_mercado(pick, apuesta, mercado)
    if pm is None or pmer is None:
        return {'hay': False, 'p_modelo': pm, 'p_mercado': None,
                'p_mezcla': pm, 'brecha': None, 'razon': ''}
    mez = mezclar(pm, pmer)
    brecha = abs(pm - pmer)
    if brecha <= BRECHA_ACUERDO:
        razon = ('modelo y casa coinciden (%.0f %% y %.0f %%): el número es '
                 'de fiar' % (100 * pm, 100 * pmer))
    elif brecha <= BRECHA_CHOQUE:
        razon = ('el modelo dice %.0f %% y la casa %.0f %%: se decide con el '
                 'promedio' % (100 * pm, 100 * pmer))
    else:
        razon = ('el modelo dice %.0f %% y la casa %.0f %% — cuando se separan '
                 'tanto, lo medido es que falla el modelo'
                 % (100 * pm, 100 * pmer))
    return {'hay': True, 'p_modelo': round(pm, 4),
            'p_mercado': round(pmer, 4), 'p_mezcla': round(mez, 4),
            'brecha': round(brecha, 4), 'razon': razon}
