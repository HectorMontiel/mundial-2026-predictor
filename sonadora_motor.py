#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Motor de la Soñadora: patas reales de Playdoit y permutaciones para combinarlas.

QUÉ CAMBIÓ RESPECTO A LA PRIMERA VERSIÓN, Y POR QUÉ
---------------------------------------------------
La primera versión salía **vacía** en producción. La causa no estaba aquí:
`alpha_finder._barrido_fixtures` lanzaba `TypeError` con las competiciones que
tienen precálculo y un partido que el precálculo no cubre, y eso mataba la rama
de fútbol ENTERA. Sin fútbol no hay tableros de Playdoit, y sin tableros no hay
patas. Está arreglado en `alpha_finder` y vigilado con su test.

Sobre esa base, esta versión:

    · **No excluye por calibración: etiqueta.** Antes, 133 de 174 patas se
      tiraban porque su liga no tenía error de calibración medido. Ahora entran
      todas y cada una dice si está medida o no; quien decide es el usuario.
    · **Cubre siete familias de mercado** en vez de dos: goles totales,
      córners (total y por equipo), tarjetas, remates a puerta por equipo, 1X2,
      doble oportunidad y ambos marcan. Más el ganador de tenis, MLB, KBO, NBA
      y NFL.
    · **Propone permutaciones**, no una lista que el usuario tenga que ordenar.

QUÉ NO ENTRA, Y NO ES UN OLVIDO
-------------------------------
Una pata necesita **precio real de la casa Y probabilidad del modelo**. Con uno
solo de los dos no se emite:

    goles por equipo ............  Playdoit los cotiza; el barrido no publica
                                   la probabilidad por bando
    totales y hándicap de NFL/NBA  Playdoit los cotiza; el modelo da el total
                                   esperado pero no su distribución
    mercados de jugador .........  fuera por diseño (dependen de alineación
                                   no confirmada)

Inventar la probabilidad que falta sería justo lo que este proyecto no hace.

SOBRE EL ORDEN POR `Score = probabilidad × cuota`
-------------------------------------------------
Es lo que pidió el encargo y así está implementado, pero conviene saber qué
ordena: `probabilidad × cuota` es el valor esperado, y el del modelo es más
alto justo donde el modelo se equivoca más. Medido el 2026-09-16: las patas de
mayor Score eran «Menos de 4,5 goles» al 92-97 %, la firma de `EV_SOSPECHOSO`.
Por eso la permutación A ordena por **probabilidad** y no por Score, y es la
que la pantalla enseña primero.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

HISTORICO = 'sonadora_historico.json'

CUOTA_MIN = 1.10
CUOTA_MAX = 1.80
# El ensanche automático cuando no hay nada: la sección nunca se queda vacía.
CUOTA_MIN_ABS = 1.05
CUOTA_MAX_ABS = 2.50
PROB_MINIMA = 0.55             # fijo: el encargo quitó el control de la UI
MAX_PATAS = 15
ECE_MAXIMO = 0.05
PENALIZA_SIN_MEDIR = 0.85      # la probabilidad cruda se encoge un 15 %

LINEAS_GOLES = (0.5, 1.5, 2.5, 3.5, 4.5, 5.5)

_RE_LINEA = re.compile(r'^(Más|Menos) de ([0-9]+(?:\.[0-9]+)?)$')
_CACHE_HIST: Optional[Dict] = None


# ---------------------------------------------------------------------------
# El histórico medido
# ---------------------------------------------------------------------------
def historico() -> Dict:
    global _CACHE_HIST
    if _CACHE_HIST is not None:
        return _CACHE_HIST
    datos: Dict = {}
    try:
        if os.path.exists(HISTORICO):
            with open(HISTORICO, encoding='utf-8') as f:
                datos = json.load(f) or {}
    except Exception as e:
        logger.warning('[sonadora] no se pudo leer %s: %s', HISTORICO, e)
    _CACHE_HIST = datos
    return _CACHE_HIST


ECE_DE = {'1X2': '1X2', 'Goles': 'Goles 2.5'}


def ece_liga(clave_liga: Optional[str], categoria: str,
             etiqueta: str = '') -> Optional[float]:
    """Error de calibración medido, o `None` si ese mercado no está medido.

    Sólo hay medición para el 1X2 y la línea de 2,5 goles, que son los dos
    mercados con cuota de cierre guardada en el histórico. Todo lo demás
    devuelve `None` A PROPÓSITO: prestarle el ECE del 2,5 sería atribuirle una
    medición que no tiene.
    """
    if not clave_liga:
        return None
    clave = ECE_DE.get(categoria)
    if clave is None:
        return None
    if clave == 'Goles 2.5' and '2.5' not in str(etiqueta):
        return None
    blo = (historico().get('ece_por_liga') or {}).get(str(clave_liga)) or {}
    v = (blo.get(clave) or {}).get('ece')
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def prob_ajustada(prob: float, ece: Optional[float]) -> float:
    """La probabilidad con la que se puntúa la pata.

    Con error de calibración medido y fino se usa tal cual; sin medición se
    encoge un 15 %, que es una penalización declarada por incertidumbre y no
    una corrección medida — la pantalla lo dice en cada pata.
    """
    p = float(prob)
    if ece is not None and ece < ECE_MAXIMO:
        return p
    return p * PENALIZA_SIN_MEDIR


def score_segura(prob: float, cuota: float, ece: Optional[float]) -> float:
    """`Score = Probabilidad_Ajustada × Cuota`, como pide el encargo."""
    try:
        return round(prob_ajustada(prob, ece) * float(cuota), 5)
    except (TypeError, ValueError):
        return 0.0


def configuracion(n_patas: int, banda: Tuple[float, float]) -> Optional[Dict]:
    """La fila medida del histórico para esa configuración, o la más parecida."""
    cfgs = [c for c in (historico().get('configuraciones') or [])
            if int(c.get('n_patas', 0)) == int(n_patas) and c.get('intentos')]
    if not cfgs:
        return None
    lo, hi = float(banda[0]), float(banda[1])

    def _dist(c):
        r = c.get('rango_cuota') or [0, 0]
        return abs(float(r[0]) - lo) + abs(float(r[1]) - hi)

    return sorted(cfgs, key=_dist)[0]


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------
def _num(x) -> Optional[float]:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v else None


def _lados(texto) -> Tuple[str, str]:
    t = str(texto or '')
    if ' vs ' in t:
        a, b = t.split(' vs ', 1)
        return a.strip(), b.strip()
    if ' @ ' in t:
        b, a = t.split(' @ ', 1)
        return a.strip(), b.strip()
    return '', ''


def _por_nombre(det: Dict) -> Dict[str, List[Dict]]:
    fuera: Dict[str, List[Dict]] = {}
    for m in (det or {}).get('mercados') or []:
        nom = ' '.join(str(m.get('nombre') or '').split())
        fuera.setdefault(nom, []).append(m)
    return fuera


def _pata(partido: Dict, categoria: str, etiqueta: str, prob, cuota,
          casa: str = 'Playdoit') -> Optional[Dict]:
    p, c = _num(prob), _num(cuota)
    if p is None or c is None or not (0.0 < p < 1.0) or c <= 1.0:
        return None
    clave = partido.get('clave_liga') or ''
    ece = ece_liga(clave, categoria, etiqueta)
    return {
        'id': f"{partido.get('deporte')}|{partido.get('partido')}|"
              f"{categoria}|{etiqueta}",
        'deporte': partido.get('deporte') or 'Fútbol',
        'partido': partido.get('partido'),
        'liga': partido.get('liga') or clave,
        'clave_liga': clave,
        'hora': partido.get('hora') or '',
        'categoria': categoria,
        'etiqueta': etiqueta,
        'prob': round(p, 4),
        'prob_ajustada': round(prob_ajustada(p, ece), 4),
        'cuota': round(c, 4),
        'casa': casa,
        'ece': ece,
        'medido': ece is not None,
        'score': score_segura(p, c, ece),
    }


def _lineas_del_mercado(mercados: List[Dict], prob_de) -> List[Tuple]:
    """(etiqueta, probabilidad, cuota) de un mercado de «Más/Menos de N».

    `prob_de(linea, es_mas)` devuelve la probabilidad del modelo o `None`. Las
    líneas que la casa cotiza y el modelo no publica —los cuartos: 2,25 · 2,75—
    se caen aquí: cruzar la probabilidad de 2,5 con el precio de 2,75 sería
    comparar dos sucesos distintos y fabricar un valor que no existe.
    """
    fuera = []
    for m in mercados:
        for s in (m.get('selecciones') or []):
            nom = ' '.join(str(s.get('nombre') or '').split())
            mt = _RE_LINEA.match(nom)
            cuota = _num(s.get('cuota'))
            if not mt or not cuota:
                continue
            p = prob_de(float(mt.group(2)), mt.group(1) == 'Más')
            if p is None:
                continue
            fuera.append((nom, p, cuota))
    return fuera


# ---------------------------------------------------------------------------
# Las patas de un partido de fútbol
# ---------------------------------------------------------------------------
def patas_del_partido(partido: Dict, det: Optional[Dict]) -> List[Dict]:
    """Todas las patas ofrecibles de un partido de fútbol.

    Las probabilidades de córners, tarjetas y remates salen de
    `rendimiento_equipos`, que son los MISMOS estimadores que usa la ficha del
    partido: si la ficha dice 9,4 córners, aquí dice 9,4. Cuestan 34 ms por
    partido (medido sobre 102), leyendo ficheros locales.
    """
    if not det:
        return []
    fuera: List[Dict] = []
    board = {str(k): _num(v) for k, v in (partido.get('board') or {}).items()}
    goles = {str(k): _num(v)
             for k, v in (partido.get('goles_lineas') or {}).items()}
    pn = _por_nombre(det)
    local, visitante = _lados(partido.get('partido'))
    casa_home = str(det.get('casa_home') or '')
    casa_away = str(det.get('casa_away') or '')

    def _add(cat, etq, prob, cuota):
        q = _pata(partido, cat, etq, prob, cuota)
        if q:
            fuera.append(q)

    # --- 1. goles totales -------------------------------------------------
    def _p_goles(linea, es_mas):
        if linea not in LINEAS_GOLES:
            return None
        p = goles.get(f'{linea:g}')
        return None if p is None else (p if es_mas else 1.0 - p)

    for etq, p, c in _lineas_del_mercado(pn.get('Total', []), _p_goles):
        _add('Goles', etq, p, c)

    # --- 2. córners, tarjetas y remates, del mismo sitio que la ficha -----
    clave = partido.get('clave_liga') or ''
    if clave and local and visitante:
        try:
            import rendimiento_equipos as rq
        except Exception as e:                    # nunca puede tumbar la lista
            rq = None
            logger.debug('[sonadora] rendimiento_equipos: %s', e)
        if rq is not None:
            _add_conteo(fuera, partido, pn, rq, clave, local, visitante,
                        casa_home, casa_away)

    # --- 3. 1X2 -----------------------------------------------------------
    for m in pn.get('Resultado Final (Tiempo Regular)', []):
        for s in (m.get('selecciones') or []):
            nom = ' '.join(str(s.get('nombre') or '').split())
            cuota = _num(s.get('cuota'))
            if not cuota:
                continue
            if nom == casa_home and local:
                _add('1X2', f'Gana {local}', board.get(f'Gana {local}'), cuota)
            elif nom == casa_away and visitante:
                _add('1X2', f'Gana {visitante}',
                     board.get(f'Gana {visitante}'), cuota)

    # --- 4. doble oportunidad --------------------------------------------
    p_h = board.get(f'Gana {local}') if local else None
    p_a = board.get(f'Gana {visitante}') if visitante else None
    p_x = board.get('Empate')
    if None not in (p_h, p_a, p_x):
        combos = {f'{casa_home}/empate': (p_h + p_x, f'{local} o empate'),
                  f'empate/{casa_away}': (p_x + p_a, f'Empate o {visitante}'),
                  f'{casa_home}/{casa_away}': (p_h + p_a,
                                               f'{local} o {visitante}')}
        for m in pn.get('Doble oportunidad', []):
            for s in (m.get('selecciones') or []):
                nom = ' '.join(str(s.get('nombre') or '').split())
                cuota = _num(s.get('cuota'))
                if not cuota:
                    continue
                llano = nom.lower().replace(' ', '')
                for patron, (prob, etq) in combos.items():
                    if llano == patron.lower().replace(' ', ''):
                        _add('Doble oportunidad', etq, min(prob, 0.999), cuota)
                        break

    # --- 5. ambos marcan --------------------------------------------------
    for m in pn.get('Ambos equipos marcan', []):
        for s in (m.get('selecciones') or []):
            nom = ' '.join(str(s.get('nombre') or '').split())
            cuota = _num(s.get('cuota'))
            if not cuota:
                continue
            prob = (board.get('Ambos marcan: Sí')
                    if nom.lower().startswith('s')
                    else board.get('Ambos marcan: No'))
            _add('BTTS', f'Ambos marcan: {nom}', prob, cuota)
    return fuera


def _add_conteo(fuera, partido, pn, rq, clave, local, visitante,
                casa_home, casa_away) -> None:
    """Córners, tarjetas y remates a puerta: total y por equipo."""
    def _prob_de(media, dispersion):
        def _f(linea, es_mas):
            p = rq.prob_mas_de(media, linea, dispersion)
            if p is None:
                return None
            return p if es_mas else 1.0 - p
        return _f

    def _emitir(cat, nombres, media, dispersion):
        if not media:
            return
        mercados = []
        for nm in nombres:
            mercados += pn.get(nm, [])
        for etq, p, c in _lineas_del_mercado(mercados,
                                             _prob_de(media, dispersion)):
            q = _pata(partido, cat, f'{etq} · {cat.lower()}', p, c)
            if q:
                fuera.append(q)

    try:
        ck = rq.corners_equipo(clave, local, visitante) or {}
    except Exception:
        ck = {}
    _emitir('Córners', ['Total Tiros De Esquina'],
            ck.get('lambda_total'), ck.get('dispersion_total'))
    for eq, casa_eq, lam in ((local, casa_home, ck.get('lambda_home')),
                             (visitante, casa_away, ck.get('lambda_away'))):
        _emitir(f'Córners de {eq}',
                [f'{casa_eq} Tiros de esquina totales',
                 f'{casa_eq} tiros de esquina',
                 f'{casa_eq} Total Tiros De Esquina'],
                lam, ck.get('dispersion'))

    try:
        tj = rq.tarjetas_equipo(clave, local, visitante) or {}
    except Exception:
        tj = {}
    _emitir('Tarjetas', ['Total de tarjetas'],
            tj.get('lambda_total'), tj.get('dispersion_total'))

    try:
        rm = rq.remates_equipo(clave, local, visitante) or {}
    except Exception:
        rm = {}
    ap = rm.get('a_puerta') or {}
    for eq, casa_eq, lam in ((local, casa_home, ap.get('lambda_home')),
                             (visitante, casa_away, ap.get('lambda_away'))):
        _emitir(f'Remates a puerta de {eq}',
                [f'{casa_eq} Remates a Puerta totales'],
                lam, ap.get('dispersion'))


def patas_de_fila(partido: Dict) -> List[Dict]:
    """Patas de los deportes sin tablero de goles: tenis, MLB, KBO, NBA, NFL.

    Su precio viene del barrido con el guardia de casas ya aplicado: si lleva
    cuota y casa, es una de las casas del usuario y se puede tomar.
    """
    fuera = []
    for m in (partido.get('mercados') or []):
        if m.get('informativo') or not m.get('cuota') or not m.get('casa'):
            continue
        if m.get('categoria') not in ('Ganador', 'Moneyline', '1X2',
                                      'Primer set'):
            continue
        q = _pata(partido, m['categoria'], m['etiqueta'], m.get('prob'),
                  m['cuota'], casa=m['casa'])
        if q:
            fuera.append(q)
    return fuera


# ---------------------------------------------------------------------------
# El día entero
# ---------------------------------------------------------------------------
def _board_por_partido(r: Dict, dia: str) -> Dict:
    import mercados_dia as md
    fuera: Dict[tuple, Dict] = {}
    for nombre in md.LISTAS:
        for p in (r.get(nombre) or []):
            if not isinstance(p, dict) or not p.get('partido'):
                continue
            if md._dia_de(p) != dia:
                continue
            k = (str(p.get('deporte') or 'Fútbol'), str(p['partido']))
            reg = fuera.setdefault(k, {})
            for campo in ('board', 'goles_lineas', 'clave_liga', 'inicio'):
                if p.get(campo) and not reg.get(campo):
                    reg[campo] = p[campo]
    return fuera


def _recoger(r: Dict, dia: str, max_partidos: int) -> Dict:
    """Todas las patas del día, sin filtrar por cuota."""
    import mercados_dia as md
    partidos = md.partidos_del_dia(r, dia, con_extras=False)
    extra = _board_por_partido(r, dia)
    patas: List[Dict] = []
    pedidos = sin_tablero = 0
    for p in partidos:
        p = {**p, **extra.get((p['deporte'], p['partido']), {})}
        if p.get('deporte') != 'Fútbol':
            patas += patas_de_fila(p)
            continue
        if pedidos >= max_partidos or ' vs ' not in str(p.get('partido') or ''):
            continue
        home, away = _lados(p.get('partido'))
        pedidos += 1
        try:
            import cuotas_multi as cm
            det = cm.mercados_playdoit('futbol', home, away,
                                       fecha=p.get('inicio'))
        except Exception as e:
            logger.debug('[sonadora] tablero %s: %s', p.get('partido'), e)
            det = None
        if not det:
            sin_tablero += 1
            continue
        patas += patas_del_partido(p, det)
    return {'patas': patas, 'n_partidos': len(partidos),
            'tableros_pedidos': pedidos, 'sin_tablero': sin_tablero}


def patas_del_dia(r: Dict, dia: Optional[str] = None,
                  cuota_min: float = CUOTA_MIN, cuota_max: float = CUOTA_MAX,
                  max_partidos: int = 60) -> Dict:
    """
    Las patas del día dentro del rango, y NUNCA una lista vacía si hay partidos.

    Si el rango pedido no deja nada, se ensancha solo hasta el máximo (1,05 –
    2,50) y se dice. La pantalla vacía era el motivo principal del rediseño:
    una sección que no enseña nada no es más prudente, es inservible.

    `r` es un barrido YA calculado. Nunca se lanza uno aquí: un segundo barrido
    dentro del proceso de Streamlit sube el pico de memoria de 1.297 MB a
    2.172 MB y mata el contenedor.
    """
    import mercados_dia as md
    dia = dia or md.dia_cdmx()
    bruto = _recoger(r, dia, max_partidos)
    todas = bruto['patas']

    def _filtra(lo, hi):
        return sorted((q for q in todas
                       if lo <= q['cuota'] <= hi and q['prob'] >= PROB_MINIMA),
                      key=lambda q: -q['score'])

    patas = _filtra(cuota_min, cuota_max)
    ensanchado = False
    if not patas and todas:
        patas = _filtra(CUOTA_MIN_ABS, CUOTA_MAX_ABS)
        ensanchado = bool(patas)
    return {
        'dia': dia, 'patas': patas, 'ensanchado': ensanchado,
        'rango': ([CUOTA_MIN_ABS, CUOTA_MAX_ABS] if ensanchado
                  else [cuota_min, cuota_max]),
        'n_partidos': bruto['n_partidos'],
        'tableros_pedidos': bruto['tableros_pedidos'],
        'sin_tablero': bruto['sin_tablero'],
        'n_sin_filtrar': len(todas),
        'n_medidas': sum(1 for q in patas if q['medido']),
        'partidos_con_pata': len({q['partido'] for q in patas}),
    }


# ---------------------------------------------------------------------------
# Permutaciones
# ---------------------------------------------------------------------------
PERMUTACIONES = (
    ('A', '🅰️ Alta probabilidad', 'Las patas más seguras del día.'),
    ('B', '🅱️ Alto multiplicador', 'Las cuotas más altas dentro del rango.'),
    ('C', '🅲 Equilibrada', 'Mejor Score: probabilidad × cuota.'),
    ('D', '🅳 Diversificada', 'Una por competición: menos riesgo compartido.'),
    ('E', '🅴 Mixta', 'Mitad seguras, mitad de cuota alta.'),
)


def _elegir(patas: List[Dict], n: int, clave,
            por_liga: bool = False) -> List[Dict]:
    """Elige `n` patas sin repetir partido (ni competición, si se pide).

    Dos patas del mismo encuentro están correlacionadas de forma brutal y la
    casa normalmente ni las deja combinar: el multiplicador que saldría no es
    el que se paga.
    """
    vistos_p, vistos_l, fuera = set(), set(), []
    for q in sorted(patas, key=clave):
        if q['partido'] in vistos_p:
            continue
        if por_liga and q['liga'] in vistos_l:
            continue
        vistos_p.add(q['partido'])
        vistos_l.add(q['liga'])
        fuera.append(q)
        if len(fuera) >= n:
            break
    return fuera


def permutaciones(patas: List[Dict], n_patas: int) -> List[Dict]:
    """Hasta cinco formas distintas de armar el parlay con las patas del día.

    Las que no llegan a `n_patas` no se enseñan a medias, y dos recetas que dan
    exactamente la misma combinación se enseñan una sola vez: repetirla con
    otro nombre sería fingir que hay más opciones de las que hay.
    """
    n = max(1, min(int(n_patas or 0), MAX_PATAS))
    if not patas:
        return []
    mitad = n // 2
    seguras = _elegir(patas, mitad, lambda q: -q['prob'])
    usados = {q['partido'] for q in seguras}
    altas = _elegir([q for q in patas if q['partido'] not in usados],
                    n - mitad, lambda q: -q['cuota'])
    candidatas = {
        'A': _elegir(patas, n, lambda q: -q['prob']),
        'B': _elegir(patas, n, lambda q: -q['cuota']),
        'C': _elegir(patas, n, lambda q: -q['score']),
        'D': _elegir(patas, n, lambda q: -q['score'], por_liga=True),
        'E': seguras + altas,
    }
    fuera, vistas = [], set()
    for letra, nombre, descripcion in PERMUTACIONES:
        sel = candidatas.get(letra) or []
        if len(sel) < n:
            continue
        firma = tuple(sorted(q['id'] for q in sel))
        if firma in vistas:
            continue
        vistas.add(firma)
        p = armar(sel)
        p.update({'letra': letra, 'nombre': nombre,
                  'descripcion': descripcion})
        fuera.append(p)
    return fuera


def armar(patas: List[Dict]) -> Dict:
    """El parlay de esas patas, con el premio Y con lo que se espera de él."""
    patas = list(patas or [])[:MAX_PATAS]
    base = {'n_patas': len(patas), 'patas': patas, 'multiplicador': 1.0,
            'prob_producto': 0.0, 'rango_cuota': [0.0, 0.0],
            'configuracion_medida': None, 'roi_esperado_medido': None,
            'n_sin_medir': 0, 'ligas': 0, 'letra': '', 'nombre': '',
            'descripcion': ''}
    if not patas:
        return base
    mult = prob = 1.0
    for q in patas:
        mult *= float(q['cuota'])
        prob *= float(q['prob'])
    lo = min(float(q['cuota']) for q in patas)
    hi = max(float(q['cuota']) for q in patas)
    base.update({
        'multiplicador': round(mult, 2),
        'prob_producto': round(prob, 6),
        'rango_cuota': [round(lo, 2), round(hi, 2)],
        'configuracion_medida': configuracion(len(patas), (lo, hi)),
        'roi_esperado_medido': roi_esperado(len(patas)),
        'n_sin_medir': sum(1 for q in patas if not q['medido']),
        'ligas': len({q['liga'] for q in patas}),
    })
    return base


def roi_esperado(n_patas: int) -> Optional[float]:
    """(1 + ROI medido de una pata)^N − 1.

    Un parlay de patas independientes multiplica el rendimiento de sus patas, y
    el ROI de una pata suelta está medido en el histórico. Es la cifra que la
    pantalla enseña al lado del premio: no para asustar, para que el número
    esté.
    """
    e = (historico().get('pata_suelta') or {}).get('roi')
    try:
        e = float(e)
    except (TypeError, ValueError):
        return None
    return round((1.0 + e) ** int(n_patas) - 1.0, 4)
