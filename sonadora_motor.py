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

# LAS CASAS, Y POR QUE NO SE MEZCLAN.
#
# Un parlay se juega EN UNA CASA. Combinar una pata con precio de Playdoit y
# otra con precio de Novibet da un multiplicador que nadie va a pagar, porque
# no existe ningun sitio donde se puedan poner las dos juntas. Asi que la
# pantalla pide que se elija casa y toda la lista sale de ella.
#
# QUE OFRECE CADA UNA, MEDIDO EL 2026-09-16
# -----------------------------------------
# **Playdoit** entra por Altenar y su tablero trae la oferta completa: goles
# totales y por equipo, cornrs, tarjetas, remates, 1X2, doble oportunidad y
# ambos marcan.
#
# **Novibet** entra por el comparador de Flashscore, que publica por tipo de
# mercado. Sondeados 12 partidos de 12 competiciones distintas:
#
#     HOME_DRAW_AWAY (1X2) ....  12 de 12
#     DOUBLE_CHANCE ...........  12 de 12
#     BOTH_TEAMS_TO_SCORE .....   4 de 12
#     ASIAN_HANDICAP ..........   4 de 12
#     OVER_UNDER (goles) ......   0 de 12   <- NUNCA
#
# O sea que con Novibet no hay patas de goles, y no es un fallo del lector: la
# casa no las publica por esa puerta. Se dice en pantalla en vez de dejar la
# lista corta sin explicacion.
#
# **Draftea** no tiene puerta. Sondeada el 2026-09-16 (ver `cuotas_multi`):
# Flashscore no la nombra, Altenar da 400 en cinco integraciones, su web es un
# Webflow con Turnstile y `api.draftea.com` contesta «Not Found» en todas las
# rutas probadas. Aparece en el selector porque el usuario apuesta ahi, y
# cuando se elige la pantalla dice exactamente por que no hay nada.
CASAS = ('Novibet', 'Playdoit', 'Draftea')
CASA_POR_DEFECTO = 'Novibet'
# las que hoy tienen fuente; el resto se ofrece y se explica
CASAS_CON_FUENTE = ('Novibet', 'Playdoit')

DEPORTES = ('Fútbol', 'MLB', 'NBA', 'NFL', 'Tenis', 'KBO')
DEPORTES_POR_DEFECTO = ('Fútbol',)
# clave de Altenar por deporte, para pedir el tablero de Playdoit
CLAVE_PDT = {'Fútbol': 'futbol', 'Tenis': 'tenis', 'MLB': 'mlb',
             'NBA': 'nba', 'NFL': 'nfl'}

# --- EL SEMAFORO, Y POR QUE NO ES EL QUE PEDIA EL ENCARGO -------------------
#
# El encargo pedia «verde = probabilidad >= 65 % Y liga con ECE < 0,05». Medido
# sobre las 366 patas del 2026-09-16, esa regla da **CERO patas verdes y un
# 96,4 % grises** — que es exactamente el problema que venia a arreglar.
#
# La razon: solo hay error de calibracion medido para el 1X2 y la linea de 2,5
# goles (son los dos mercados con cuota de cierre guardada en el historico), o
# sea 13 de 366 patas. Y las trece estan POR ENCIMA de 0,05 (0,063 a 0,128), asi
# que la condicion no la cumple nadie. Una regla que nadie puede cumplir no
# colorea: apaga.
#
# Asi que el color lo manda la PROBABILIDAD, que todas las patas tienen, y el
# ECE solo puede BAJAR un escalon cuando esta medido y sale mal. Con los
# umbrales de abajo, ese mismo dia:
#
#     verde  52,5 %   ambar  37,4 %   rojo  10,1 %   gris  0 %
#
# que cumple el minimo del 40 % de verdes que pedia el encargo.
VERDE, AMBAR, ROJO, GRIS = '🟢', '🟡', '🔴', '⚪'
PROB_VERDE = 0.70
PROB_AMBAR = 0.58
ECE_DEGRADA = 0.12             # con el ECE medido por encima, baja un escalon


def color(prob, ece=None, floja: bool = False) -> str:
    """El semáforo de una pata: probabilidad primero, calibración como freno.

    `floja` lo decide `calibracion_floja` comparando la competición contra la
    distribución de SU mercado, no contra un umbral fijo. `ece` se acepta por
    compatibilidad y como red: un error absurdamente alto baja igual.
    """
    p = _num(prob)
    if p is None:
        return GRIS
    base = VERDE if p >= PROB_VERDE else (AMBAR if p >= PROB_AMBAR else ROJO)
    e = _num(ece)
    if floja or (e is not None and e >= ECE_DEGRADA):
        base = {VERDE: AMBAR, AMBAR: ROJO, ROJO: ROJO}[base]
    return base


ORDEN_COLOR = {VERDE: 0, AMBAR: 1, GRIS: 2, ROJO: 3}

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


# A QUE MERCADO MEDIDO CORRESPONDE CADA CATEGORIA DE LA PANTALLA.
#
# v200 — ESTO MIRABA DOS MERCADOS Y HAY OCHO MEDIDOS.
#
# La version anterior solo reconocia el 1X2 y la linea de 2,5 goles, porque
# saco el ECE del conjunto de patas y ese exige cuota de cierre. Dos errores
# encadenados:
#
#   1. **El ECE no necesita cuotas.** Necesita la probabilidad del modelo y el
#      resultado real, y las dos estan en `pick_ledger_totales.csv` para 47.794
#      partidos: toda la escalera de goles y el BTTS, en 55 competiciones.
#   2. **El de cornrs, tarjetas y remates YA ESTABA MEDIDO** en
#      `_v162_calibracion_por_liga.json`, que sirve `confianza_mercado`. Se
#      descarto por «ese modulo no mide estos mercados», cierto para los goles
#      y falso para estos: 36 competiciones con el error entre 0,0027 y 0,0486.
#
# Medido el 2026-09-16, esos dos descartes dejaban **13 de 366 patas** con
# calibracion conocida, y 202 de las 366 eran justo de cornrs, tarjetas y
# remates — con su numero a mano.
ECE_DE = {
    '1X2': '1X2', 'Ganador': '1X2', 'Moneyline': '1X2',
    'Doble oportunidad': '1X2',
    'BTTS': 'BTTS', 'Tarjetas': 'Tarjetas', 'Córners': 'Córners',
    'Remates': 'Remates', 'Remates a puerta': 'Remates a puerta',
}
# las lineas de goles que tienen medicion propia
ECE_GOLES = {'1.5': 'Goles 1.5', '2.5': 'Goles 2.5', '3.5': 'Goles 3.5'}


def _mercado_medido(categoria: str, etiqueta: str = '') -> Optional[str]:
    """La clave del informe que mide esta pata, o None si no hay ninguna."""
    cat = str(categoria or '')
    # «Córners de Hibernian» o «Remates a puerta de Kilmarnock»
    base = cat.split(' de ')[0].strip() if ' de ' in cat else cat
    if cat.startswith('Remates a puerta'):
        base = 'Remates a puerta'
    if base == 'Goles' and cat.startswith('Goles de '):
        # los goles POR EQUIPO no tienen medición propia: el ledger mide el
        # total del partido, no el de cada bando. Se dice, no se presta.
        return None
    if base == 'Goles':
        for linea, clave in ECE_GOLES.items():
            if linea in str(etiqueta):
                return clave
        return None
    return ECE_DE.get(base)


def ece_liga(clave_liga: Optional[str], categoria: str,
             etiqueta: str = '') -> Optional[float]:
    """Error de calibración medido de esta pata, o `None` si no lo hay."""
    if not clave_liga:
        return None
    clave = _mercado_medido(categoria, etiqueta)
    if clave is None:
        return None
    blo = (historico().get('ece_por_liga') or {}).get(str(clave_liga)) or {}
    v = (blo.get(clave) or {}).get('ece')
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def calibracion_floja(clave_liga: Optional[str], categoria: str,
                      etiqueta: str = '') -> bool:
    """¿Esta competición está en el PEOR CUARTO de su mercado?

    No se compara contra un umbral fijo, y la razón está medida: las dos
    fuentes de ECE no están en la misma escala.

        goles y BTTS (ledger) ..............  0,047 a 0,161
        córners/tarjetas/remates (informe) .  0,003 a 0,049

    Con el corte único en 0,05 que pedía el encargo, TODOS los mercados de
    goles saldrían mal calibrados y TODOS los de córners perfectos — y eso no
    describe los modelos, describe que los dos números se calculan distinto.
    Cada mercado se juzga contra su propia distribución.
    """
    clave = _mercado_medido(categoria, etiqueta)
    if clave is None:
        return False
    e = ece_liga(clave_liga, categoria, etiqueta)
    if e is None:
        return False
    corte = ((historico().get('cortes_ece') or {}).get(clave) or {}).get('p75')
    try:
        return float(e) > float(corte)
    except (TypeError, ValueError):
        return False


def prob_ajustada(prob: float, ece: Optional[float]) -> float:
    """La probabilidad con la que se puntúa la pata.

    Con error de calibración medido se usa tal cual; SIN medición se encoge un
    15 %, que es una penalización declarada por incertidumbre y no una
    corrección medida — la pantalla lo dice en cada pata.

    v200 — la condición era `ece < 0,05`, y con eso ninguna pata de goles se
    libraba: su ECE va de 0,047 a 0,161 porque se mide de otra forma que el de
    córners. Lo que decide ahora es si HAY medición; que sea buena o mala lo
    resuelve el semáforo contra la distribución de su propio mercado.
    """
    p = float(prob)
    return p if ece is not None else p * PENALIZA_SIN_MEDIR


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
    floja = calibracion_floja(clave, categoria, etiqueta)
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
        'calibracion_floja': floja,
        'score': score_segura(p, c, ece),
        'color': color(p, ece, floja),
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

    # --- 1b. goles de CADA equipo --------------------------------------
    #
    # Playdoit los cotiza en su propio mercado («Hibernian FC total de goles»)
    # y el barrido publica desde la v200 los marginales de la matriz de
    # marcador. Es la apuesta más acotada que pidió el usuario: un solo equipo
    # en vez del total del partido.
    por_equipo = partido.get('goles_equipo') or {}
    for lado, nombre_eq, casa_eq in (('local', local, casa_home),
                                     ('visitante', visitante, casa_away)):
        lineas = {str(k): _num(v) for k, v in (por_equipo.get(lado) or {}).items()}
        if not lineas or not casa_eq:
            continue

        def _p_eq(linea, es_mas, _l=lineas):
            p = _l.get(f'{linea:g}')
            return None if p is None else (p if es_mas else 1.0 - p)

        mercados_eq = []
        for nm in (f'{casa_eq} total de goles', f'{casa_eq} Total de goles',
                   f'{casa_eq} Totales'):
            mercados_eq += pn.get(nm, [])
        for etq, p, c in _lineas_del_mercado(mercados_eq, _p_eq):
            _add(f'Goles de {nombre_eq}', f'{etq} · goles', p, c)

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


def _phi(z: float) -> float:
    """Normal acumulada, sin scipy."""
    import math
    return 0.5 * (1.0 + math.erf(float(z) / math.sqrt(2.0)))


def _sigmas_nfl() -> Dict[str, float]:
    """Las desviaciones que el propio `modelo_nfl` publica en su calibracion.

    Se usan para convertir el total y el margen ESPERADOS —que el barrido si
    trae— en probabilidades de linea. Es el mismo metodo con el que
    `modelo_nfl.backtest` convierte su margen en probabilidad de victoria, asi
    que no se inventa un modelo nuevo: se aplica el que ya hay.
    """
    try:
        with open('nfl_calibracion.json', encoding='utf-8') as f:
            d = json.load(f) or {}
        temps = d.get('temporadas') or {}
        ult = temps[sorted(temps)[-1]]
        sm_, st_ = _num(ult.get('sigma_margen')), _num(ult.get('sigma_total'))
        if sm_ and st_:
            return {'margen': sm_, 'total': st_}
    except Exception as e:
        logger.debug('[sonadora] sigmas de NFL: %s', e)
    return {}


_RE_HCP = re.compile(r'^(.+?)\s*([+-][0-9]+(?:\.[0-9]+)?)$')


def patas_otro_deporte(partido: Dict, det: Optional[Dict]) -> List[Dict]:
    """Patas de MLB, NBA, NFL, KBO y tenis desde el tablero de Playdoit.

    El GANADOR entra en todos: su probabilidad esta en el `board` del barrido y
    su precio en el tablero. En NFL entran ademas el total de puntos y el
    handicap, porque `modelo_nfl` publica el total y el margen esperados y su
    propia calibracion publica las desviaciones con las que convertirlos en
    probabilidad.

    En MLB, NBA y KBO el total NO entra: la casa lo cotiza, pero el barrido no
    trae ninguna distribucion de carreras ni de puntos con la que cruzarlo, y
    fabricarla seria inventar.
    """
    if not det:
        return []
    fuera: List[Dict] = []
    board = {str(k): _num(v) for k, v in (partido.get('board') or {}).items()}
    pn = _por_nombre(det)
    local, visitante = _lados(partido.get('partido'))
    casa_home = str(det.get('casa_home') or '')
    casa_away = str(det.get('casa_away') or '')

    def _add(cat, etq, prob, cuota):
        q = _pata(partido, cat, etq, prob, cuota)
        if q:
            fuera.append(q)

    # --- ganador: el nombre del mercado cambia de deporte a deporte --------
    for nombre, mercados in pn.items():
        if not nombre.lower().startswith('ganador'):
            continue
        if '&' in nombre or ' y ' in nombre.lower():
            continue          # «Ganador & total» es un parlay de la casa
        for m in mercados:
            for sel in (m.get('selecciones') or []):
                nom = ' '.join(str(sel.get('nombre') or '').split())
                cuota = _num(sel.get('cuota'))
                if not cuota:
                    continue
                if nom == casa_home and local:
                    _add('Ganador', f'Gana {local}',
                         board.get(f'Gana {local}'), cuota)
                elif nom == casa_away and visitante:
                    _add('Ganador', f'Gana {visitante}',
                         board.get(f'Gana {visitante}'), cuota)

    if partido.get('deporte') != 'NFL':
        return fuera

    sig = _sigmas_nfl()
    total_esp = _num(partido.get('total_esperado'))
    margen_esp = _num(partido.get('margen_esperado'))

    # --- NFL: total de puntos --------------------------------------------
    if sig.get('total') and total_esp:
        def _p_total(linea, es_mas):
            p_mas = 1.0 - _phi((linea - total_esp) / sig['total'])
            return p_mas if es_mas else 1.0 - p_mas

        for nombre, mercados in pn.items():
            if not nombre.lower().startswith('totales'):
                continue
            for etq, p, c in _lineas_del_mercado(mercados, _p_total):
                _add('Total de puntos', etq, p, c)

    # --- NFL: handicap ----------------------------------------------------
    #
    # `margen_esperado` es del LOCAL. Una seleccion «BUF Bills -3.5» cubre si
    # el margen de BUF supera 3,5; si BUF es el visitante, su margen es el
    # negativo del local. El signo se resuelve con el nombre del equipo, que es
    # el unico sitio donde esta escrito sin ambiguedad.
    if sig.get('margen') and margen_esp is not None:
        for nombre, mercados in pn.items():
            if not nombre.lower().startswith('hándicap') and                     not nombre.lower().startswith('handicap'):
                continue
            for m in mercados:
                for sel in (m.get('selecciones') or []):
                    nom = ' '.join(str(sel.get('nombre') or '').split())
                    cuota = _num(sel.get('cuota'))
                    mt = _RE_HCP.match(nom)
                    if not cuota or not mt:
                        continue
                    equipo, linea = mt.group(1).strip(), float(mt.group(2))
                    if equipo == casa_home:
                        margen, quien = margen_esp, local
                    elif equipo == casa_away:
                        margen, quien = -margen_esp, visitante
                    else:
                        continue
                    # cubre si margen_real + linea > 0
                    p = 1.0 - _phi((-linea - margen) / sig['margen'])
                    _add('Hándicap', f'{quien} {linea:+g}', p, cuota)
    return fuera


_DEP_MX = {'Fútbol': 'futbol', 'Tenis': 'tenis', 'MLB': 'mlb',
           'NBA': 'nba', 'NFL': 'nfl'}


def patas_novibet(partido: Dict) -> List[Dict]:
    """Las patas que Novibet publica de este partido, con su precio real.

    Salen de `cuotas_mx.json`, que el workflow de las casas mexicanas refresca
    cada seis horas. Novibet da 1X2 y doble oportunidad siempre, y ambos marcan
    en parte de las competiciones; goles NO da ninguno (ver la cabecera).
    """
    dep = _DEP_MX.get(partido.get('deporte'))
    local, visitante = _lados(partido.get('partido'))
    if not dep or not local:
        return []
    try:
        import cuotas_mx as mx
        reg = mx.buscar(dep, local, visitante, partido.get('inicio'))
    except Exception as e:
        logger.debug('[sonadora] cuotas_mx %s: %s', partido.get('partido'), e)
        return []
    casas = (reg or {}).get('casas') or {}
    nb = casas.get('Novibet') or {}
    if not nb:
        return []

    board = {str(k): _num(v) for k, v in (partido.get('board') or {}).items()}
    p_h = board.get(f'Gana {local}')
    p_a = board.get(f'Gana {visitante}')
    p_x = board.get('Empate')
    fuera: List[Dict] = []

    def _add(cat, etq, prob, cuota):
        q = _pata(partido, cat, etq, prob, cuota, casa='Novibet')
        if q:
            fuera.append(q)

    # --- 1X2 / ganador ---------------------------------------------------
    for clave in ('HOME_DRAW_AWAY', 'HOME_AWAY'):
        bloque = nb.get(clave)
        if not isinstance(bloque, dict):
            continue
        cat = '1X2' if clave == 'HOME_DRAW_AWAY' else 'Ganador'
        _add(cat, f'Gana {local}', p_h, bloque.get('home'))
        _add(cat, f'Gana {visitante}', p_a, bloque.get('away'))

    # --- doble oportunidad: la probabilidad es la suma del 1X2 -----------
    #
    # El comparador publica SOLO `homeOrDraw` —la doble del favorito—, no las
    # tres. Se emite lo que hay; inventar las otras dos a partir del 1X2 sería
    # dar un precio que la casa no ha puesto.
    doble = nb.get('DOUBLE_CHANCE')
    if isinstance(doble, dict) and None not in (p_h, p_a, p_x):
        for campo, prob, etq in (
                ('homeOrDraw', p_h + p_x, f'{local} o empate'),
                ('drawOrAway', p_x + p_a, f'Empate o {visitante}'),
                ('homeOrAway', p_h + p_a, f'{local} o {visitante}')):
            if doble.get(campo) is None:
                continue
            _add('Doble oportunidad', etq, min(prob, 0.999), doble[campo])

    # --- ambos marcan -----------------------------------------------------
    btts = nb.get('BOTH_TEAMS_TO_SCORE')
    if isinstance(btts, dict):
        _add('BTTS', 'Ambos marcan: Sí', board.get('Ambos marcan: Sí'),
             btts.get('yes'))
        _add('BTTS', 'Ambos marcan: No', board.get('Ambos marcan: No'),
             btts.get('no'))
    return fuera


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
            for campo in ('board', 'goles_lineas', 'goles_equipo',
                          'clave_liga', 'inicio'):
                if p.get(campo) and not reg.get(campo):
                    reg[campo] = p[campo]
    return fuera


def _contexto_del_partido(partido: Dict, lado: str) -> Dict:
    """Movimiento de línea y alineación de este partido, si los hay.

    Se consulta UNA vez por partido y se copia a sus patas: por pata serían
    cientos de consultas para el mismo dato.
    """
    try:
        import contexto_mercado as cx
        local, visitante = _lados(partido.get('partido'))
        if not local:
            return {}
        return cx.contexto(local, visitante, lado,
                           str(partido.get('inicio') or ''))
    except Exception as e:
        logger.debug('[sonadora] contexto de mercado: %s', e)
        return {}


def _pegar_contexto(patas: List[Dict], partido: Dict) -> None:
    """Anota el contexto en las patas a las que de verdad les aplica.

    El MOVIMIENTO de la línea 1X2 habla del ganador, no de los córners: se pega
    sólo a las patas de ganador, y del lado correcto. La ALINEACIÓN habla del
    partido entero, así que va en todas.

    Va marcado como informativo y no toca el Score ni el color: no está medido
    que el movimiento prediga nada en este proyecto, y no puede estarlo hasta
    que el ledger vuelva a tener cuotas.
    """
    if not patas:
        return
    local, visitante = _lados(partido.get('partido'))
    ctx_home = _contexto_del_partido(partido, 'home')
    ali = (ctx_home or {}).get('alineacion')
    ctx_away = None
    for q in patas:
        if ali:
            q['alineacion'] = ali.get('nivel')
            q['nota_alineacion'] = ali.get('texto')
        if q['categoria'] not in ('1X2', 'Ganador', 'Moneyline'):
            continue
        etq = str(q.get('etiqueta') or '')
        if visitante and etq.endswith(visitante):
            if ctx_away is None:
                ctx_away = _contexto_del_partido(partido, 'away')
            ctx = ctx_away
        elif local and etq.endswith(local):
            ctx = ctx_home
        else:
            continue
        mov = (ctx or {}).get('movimiento')
        if mov:
            q['movimiento'] = mov.get('sentido')
            q['nota_movimiento'] = mov.get('texto')
        if (ctx or {}).get('lectura'):
            q['lectura_mercado'] = ctx['lectura']


def _recoger(r: Dict, dia: str, max_partidos: int,
             deportes: Optional[List[str]] = None,
             casa: str = CASA_POR_DEFECTO) -> Dict:
    """Todas las patas del día de los deportes pedidos, sin filtrar por cuota.

    El tablero de Playdoit se pide SOLO para los deportes seleccionados, así
    que el coste lo acota el propio selector: con «Fútbol» son ~35 peticiones,
    y marcar tenis —que hoy trae 185 partidos, casi todos de circuitos que
    Playdoit no cotiza— no arrastra a los demás.
    """
    import mercados_dia as md
    quiero = set(deportes or DEPORTES_POR_DEFECTO)
    partidos = [p for p in md.partidos_del_dia(r, dia, con_extras=False)
                if p.get('deporte') in quiero]
    extra = _board_por_partido(r, dia)
    patas: List[Dict] = []
    # EL PRESUPUESTO DE TABLEROS ES POR DEPORTE, no global. Con uno solo, el
    # fútbol se comía los 60 y una selección mixta se quedaba con dos patas de
    # tenis en vez de catorce: medido el 2026-09-16 comparando «Tenis» a solas
    # (14 patas) contra «todos» (2).
    pedidos: Dict[str, int] = {}
    sin_tablero = 0
    for p in partidos:
        p = {**p, **extra.get((p['deporte'], p['partido']), {})}
        dep = p.get('deporte')
        if casa == 'Novibet':
            # Novibet no pasa por el tablero de Altenar: sale del fichero de
            # las casas mexicanas, que ya está en disco. Cero peticiones.
            patas += patas_novibet(p)
            continue
        if casa not in CASAS_CON_FUENTE:
            continue                    # Draftea: no hay de dónde sacarlo
        clave_pdt = CLAVE_PDT.get(dep)
        det = None
        if clave_pdt and pedidos.get(dep, 0) < max_partidos \
                and _lados(p.get('partido'))[0]:
            home, away = _lados(p.get('partido'))
            pedidos[dep] = pedidos.get(dep, 0) + 1
            try:
                import cuotas_multi as cm
                det = cm.mercados_playdoit(clave_pdt, home, away,
                                           fecha=p.get('inicio'))
            except Exception as e:
                logger.debug('[sonadora] tablero %s: %s', p.get('partido'), e)
                det = None
            if not det:
                sin_tablero += 1
        if dep == 'Fútbol':
            nuevas = patas_del_partido(p, det)
        else:
            nuevas = patas_otro_deporte(p, det)
            # y lo que el barrido ya trajo con precio: si Playdoit no cotiza
            # ese partido, la fila del barrido puede llevar precio de Novibet.
            # Se deduplica por (partido, etiqueta) y NO por categoría: la misma
            # apuesta llega como «Ganador» desde el tablero y como «Moneyline»
            # desde el barrido, y con la categoría dentro de la clave salía dos
            # veces en la lista (medido en MLB el 2026-09-16).
            vistos = {(q['partido'], q['etiqueta']) for q in nuevas}
            for q in patas_de_fila(p):
                if (q['partido'], q['etiqueta']) not in vistos:
                    nuevas.append(q)
        _pegar_contexto(nuevas, p)
        patas += nuevas
    return {'patas': patas, 'n_partidos': len(partidos),
            'tableros_pedidos': sum(pedidos.values()),
            'tableros_por_deporte': dict(pedidos),
            'sin_tablero': sin_tablero}


def patas_del_dia(r: Dict, dia: Optional[str] = None,
                  cuota_min: float = CUOTA_MIN, cuota_max: float = CUOTA_MAX,
                  max_partidos: int = 60,
                  deportes: Optional[List[str]] = None,
                  con_rojas: bool = False,
                  casa: str = CASA_POR_DEFECTO) -> Dict:
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
    bruto = _recoger(r, dia, max_partidos, deportes, casa)
    todas = bruto['patas']

    def _filtra(lo, hi):
        # Verdes primero, luego ámbar, luego grises y las rojas al final. A
        # igualdad de color mandan las MEDIDAS, y sólo después el Score.
        #
        # POR QUÉ LAS MEDIDAS DELANTE. Sin ese criterio la lista la encabezaban
        # «Menos de 4,5 al 98 % a 1,10» y «Menos de 5,5 al 95 %»: son las
        # líneas de la cola de la Poisson, las únicas de la escalera SIN error
        # de calibración medido y justo donde este proyecto tiene documentado
        # que el modelo se equivoca (la firma de `EV_SOSPECHOSO`). Siguen
        # estando —quitarlas sería decidir por el usuario— pero detrás de las
        # que sí se han medido.
        return sorted((q for q in todas
                       if lo <= q['cuota'] <= hi and q['prob'] >= PROB_MINIMA),
                      key=lambda q: (ORDEN_COLOR.get(q['color'], 9),
                                     not q.get('medido'),
                                     -q['score']))

    # LA RED QUE GARANTIZA QUE NO SE MEZCLAN CASAS. `_recoger` ya elige la
    # fuente, pero las filas del barrido traen la casa que eligió el guardia
    # (Playdoit o Novibet, la que pagara mejor), así que sin esto se colaría
    # alguna del otro sitio y el multiplicador sería de un parlay que nadie
    # acepta.
    todas = [q for q in todas if q.get('casa') == casa]

    # red final contra duplicados: misma apuesta del mismo partido una vez
    _vistas, _unicas = set(), []
    for q in todas:
        k = (q['partido'], q['etiqueta'])
        if k in _vistas:
            continue
        _vistas.add(k)
        _unicas.append(q)
    todas = _unicas

    patas = _filtra(cuota_min, cuota_max)
    ensanchado = False
    if not patas and todas:
        patas = _filtra(CUOTA_MIN_ABS, CUOTA_MAX_ABS)
        ensanchado = bool(patas)

    # LA CASCADA: si hay algo mejor que rojo, las rojas se esconden. Si NO hay
    # nada mejor, se enseñan igual — la sección no se queda vacía por esconder
    # lo único que hay.
    conteo = {c: sum(1 for q in patas if q['color'] == c)
              for c in (VERDE, AMBAR, ROJO, GRIS)}
    visibles = patas
    if not con_rojas:
        sin_rojas = [q for q in patas if q['color'] != ROJO]
        if sin_rojas:
            visibles = sin_rojas
    n_verde = conteo[VERDE]
    total_col = max(len(patas), 1)
    return {
        'dia': dia, 'patas': visibles, 'todas': patas,
        'ensanchado': ensanchado,
        'rango': ([CUOTA_MIN_ABS, CUOTA_MAX_ABS] if ensanchado
                  else [cuota_min, cuota_max]),
        'deportes': sorted(set(deportes or DEPORTES_POR_DEFECTO)),
        'casa': casa,
        'casa_con_fuente': casa in CASAS_CON_FUENTE,
        'n_partidos': bruto['n_partidos'],
        'tableros_pedidos': bruto['tableros_pedidos'],
        'tableros_por_deporte': bruto.get('tableros_por_deporte', {}),
        'sin_tablero': bruto['sin_tablero'],
        'n_sin_filtrar': len(todas),
        'n_medidas': sum(1 for q in visibles if q['medido']),
        'partidos_con_pata': len({q['partido'] for q in visibles}),
        'conteo_color': conteo,
        'rojas_ocultas': len(patas) - len(visibles),
        # «sólida» y «débil» son los dos avisos que pidió el encargo
        'solidez': ('solida' if n_verde / total_col >= 0.60
                    else ('debil' if n_verde / total_col < 0.30 else 'normal')),
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
    # A y C PRIORIZAN EL COLOR, que es lo que el encargo pide: «alta
    # probabilidad» y «equilibrada» deben salir verdes mientras haya verdes.
    # B ordena por cuota a secas —es su razón de ser— y D reparte por
    # competición. El color entra como primera clave, no como filtro: si un día
    # no hay verdes suficientes, se completan con ámbar en vez de devolver
    # menos patas de las pedidas.
    def _por_color(clave):
        return lambda q: (ORDEN_COLOR.get(q['color'], 9),
                          not q.get('medido'), clave(q))

    mitad = n // 2
    seguras = _elegir(patas, mitad, _por_color(lambda q: -q['prob']))
    usados = {q['partido'] for q in seguras}
    altas = _elegir([q for q in patas if q['partido'] not in usados],
                    n - mitad, lambda q: -q['cuota'])
    candidatas = {
        'A': _elegir(patas, n, _por_color(lambda q: -q['prob'])),
        'B': _elegir(patas, n, lambda q: -q['cuota']),
        'C': _elegir(patas, n, _por_color(lambda q: -q['score'])),
        'D': _elegir(patas, n, _por_color(lambda q: -q['score']),
                     por_liga=True),
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
            'descripcion': '', 'deportes': [], 'conteo_color': {}}
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
        'deportes': sorted({q['deporte'] for q in patas}),
        'conteo_color': {c: sum(1 for q in patas if q.get('color') == c)
                         for c in (VERDE, AMBAR, ROJO, GRIS)},
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
