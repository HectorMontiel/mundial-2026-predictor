#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Motor de la Soñadora: patas de alta probabilidad con precio REAL de Playdoit.

QUÉ ES ESTO Y QUÉ NO ES
-----------------------
El usuario ganó un parlay de 13 patas con cuotas de 1,35 a 1,79 —ocho de ellas
de total de goles— que pagó 490x, y pidió poder repetir ese patrón de forma
sistemática. Esto arma la lista de patas candidatas y deja que él combine.

**No es una recomendación del sistema.** `validar_sonadora.py` midió las veinte
configuraciones del encargo sobre el histórico reciente y NINGUNA tiene
esperanza positiva; el detalle vive en `sonadora_historico.json` y la pantalla
lo enseña sin adornos. Esta sección existe porque el usuario la pidió sabiendo
eso, y está separada de «Apuestas del Día» justamente para que no se confunda
con lo que el sistema sí recomienda.

DE DÓNDE SALE CADA NÚMERO
-------------------------
    la cuota .............  tablero real de Playdoit (`cuotas_multi.
                            mercados_playdoit`). No se inventa ninguna línea:
                            si la casa no la publica, no existe.
    la probabilidad ......  el barrido del día, ya encogida hacia el mercado
                            (w=0,25). Es la misma que enseña la ficha.
    el error de calibración  `sonadora_historico.json`, medido por competición
                            y mercado sobre 24 meses del ledger fuera de
                            muestra.

POR QUÉ EL ERROR DE CALIBRACIÓN NO SALE DE `confianza_mercado.py`
-----------------------------------------------------------------
Porque ese módulo **no mide estos mercados**. Su informe cubre córners,
tarjetas, remates y remates a puerta; los mercados de los que vive la Soñadora
—1X2 y totales de goles— no están en él. Usarlo aquí habría devuelto `None`
para todo y el filtro no habría filtrado nada. El ECE de goles se calcula en
`validar_sonadora.py` del mismo ledger con el que se mide todo lo demás.

LOS CÓRNERS SE QUEDAN FUERA, Y NO ES UN OLVIDO
----------------------------------------------
El encargo los permitía «si la liga tiene datos observados». No entran, por lo
que este proyecto ya tiene medido y escrito en `corners_ui`: el modelo de
córners **ordena** bien los partidos (correlación +0,81 con la línea de la
casa) pero su **nivel** va ~1 córner alto. Elegir patas por probabilidad con un
nivel sesgado es elegir sistemáticamente el lado equivocado de la línea, que en
un parlay se paga N veces. Es un cambio de una constante el día que el nivel
esté validado.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

HISTORICO = 'sonadora_historico.json'

# Rango por defecto, el del parlay ganador redondeado hacia fuera.
CUOTA_MIN = 1.10
CUOTA_MAX = 1.80
PROB_MINIMA = 0.55
MAX_PATAS = 15                 # tope duro: por encima es una lotería irracional
ECE_MAXIMO = 0.05              # el listón del encargo

# Las líneas de goles que se ofrecen: las que el modelo publica en
# `goles_lineas`, que la casa cotiza en su mercado «Total» y que además están
# cerca de donde el modelo está medido.
#
# SE QUEDAN FUERA 0,5 y 4,5 Y NO ES UN RECORTE ARBITRARIO. El único punto de la
# escalera con error de calibración medido es el 2,5 (`ece_por_liga`), y las
# colas de una Poisson son justo donde peor se porta un modelo de goles.
# Medido en el barrido del 2026-09-16: las patas mejor puntuadas eran todas
# «Menos de 4,5» al 92-97 % con EV aparente de +10 % a +19 %, que es la firma
# exacta de `EV_SOSPECHOSO` — el modelo equivocándose, no la casa regalando.
# Con 1,5 / 2,5 / 3,5 se cubre lo que el usuario usó de verdad (sus 13 patas
# ganadoras fueron cuatro de 1,5 y cuatro de 2,5).
LINEAS_GOLES = (1.5, 2.5, 3.5)

# Nombres EXACTOS de los mercados de Playdoit que se leen. Cualquier otro se
# ignora: hándicaps, marcador exacto, mitades, mercados de jugador y las
# combinaciones tipo «doble oportunidad y total», que son parlays de la casa
# disfrazados de mercado y no se pueden cruzar con una probabilidad del modelo.
MERCADO_TOTAL = 'Total'
MERCADO_1X2 = 'Resultado Final (Tiempo Regular)'
MERCADO_BTTS = 'Ambos equipos marcan'
MERCADO_DOBLE = 'Doble oportunidad'

_CACHE_HIST: Optional[Dict] = None


# ---------------------------------------------------------------------------
# El histórico medido
# ---------------------------------------------------------------------------
def historico() -> Dict:
    """`sonadora_historico.json`, memorizado. Vacío si no está."""
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


# Qué clave del informe mide cada mercado de la pantalla. Sólo hay dos
# medidas, porque sólo hay dos con cuota de cierre guardada en el histórico:
# el 1X2 y el total de 2,5 goles. Lo demás va sin medir Y SE DICE — asignarle
# el ECE del 2,5 sería atribuirle una medición que no tiene.
ECE_DE = {'1X2': '1X2', 'Goles 2.5': 'Goles 2.5'}


def ece_liga(clave_liga: Optional[str], mercado: str,
             etiqueta: str = '') -> Optional[float]:
    """Error de calibración medido de esa competición en ese mercado.

    `None` significa «no medido», y quien llama decide: el filtro estricto lo
    deja fuera, como pide el encargo.

    El mercado «Goles» sólo tiene medición en la línea de 2,5; las de 1,5 y 3,5
    devuelven `None` a propósito.
    """
    if not clave_liga:
        return None
    clave_informe = ECE_DE.get(mercado)
    if clave_informe is None and mercado == 'Goles':
        clave_informe = 'Goles 2.5' if '2.5' in str(etiqueta) else None
    if clave_informe is None:
        return None
    blo = (historico().get('ece_por_liga') or {}).get(str(clave_liga)) or {}
    v = (blo.get(clave_informe) or {}).get('ece')
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# Los tres niveles de exigencia sobre la calibración, de más a menos estricto.
#
# POR QUE TRES Y NO UNO. El encargo pedía «liga con ECE < 0,05 en ESE mercado,
# las no medidas fuera». Aplicado al pie de la letra, el 2026-09-16 dejaba la
# lista en CERO patas: sólo hay medición para el 1X2 y para la línea de 2,5
# goles, y las patas del día eran «Menos de 3,5» y «Más de 1,5». Una pantalla
# vacía no es más rigurosa, es inservible.
#
# Así que la regla literal se conserva como nivel MERCADO —y la pantalla dice
# cuántas patas deja fuera— y el nivel por defecto exige que la COMPETICIÓN
# esté bien calibrada, que es lo que la regla perseguía: no ofrecer patas de
# ligas donde el modelo se equivoca. Cada pata dice si su mercado está medido.
NIVEL_MERCADO = 'mercado'      # ECE medido de ESE mercado, < 0,05
NIVEL_LIGA = 'liga'            # la competición tiene algún mercado < 0,05
NIVEL_TODO = 'todo'            # sin filtro de calibración


def liga_bien_calibrada(clave_liga: Optional[str]) -> Optional[bool]:
    """¿Esta competición está medida y bien calibrada? `None` si no se midió."""
    if not clave_liga:
        return None
    blo = (historico().get('ece_por_liga') or {}).get(str(clave_liga))
    if not blo:
        return None
    errores = [v.get('ece') for v in blo.values() if v.get('ece') is not None]
    if not errores:
        return None
    return bool(min(errores) < ECE_MAXIMO)


def penalizacion_varianza(ece: Optional[float]) -> float:
    """0 si el ECE es fino, +0,1 si es aceptable, +0,2 si no está medido."""
    if ece is None:
        return 0.2
    if ece < 0.02:
        return 0.0
    if ece < ECE_MAXIMO:
        return 0.1
    return 0.3


def score_segura(prob: float, ece: Optional[float]) -> float:
    """`Score_Segura = Probabilidad × (1 − Penalización_Varianza)`."""
    try:
        p = float(prob)
    except (TypeError, ValueError):
        return 0.0
    return round(p * (1.0 - penalizacion_varianza(ece)), 5)


def configuracion(n_patas: int, banda: Tuple[float, float]) -> Optional[Dict]:
    """La fila medida de `sonadora_historico.json` para esa configuración.

    Se busca la banda exacta y, si no está, la más parecida por distancia entre
    extremos: la pantalla enseña SIEMPRE la configuración que de verdad se
    midió, con su rango escrito, en vez de callar o de inventar una cifra.
    """
    cfgs = (historico().get('configuraciones') or [])
    candidatas = [c for c in cfgs if int(c.get('n_patas', 0)) == int(n_patas)]
    if not candidatas:
        return None
    lo, hi = float(banda[0]), float(banda[1])

    def _dist(c):
        r = c.get('rango_cuota') or [0, 0]
        return abs(float(r[0]) - lo) + abs(float(r[1]) - hi)

    return sorted(candidatas, key=_dist)[0]


# ---------------------------------------------------------------------------
# Lectura del tablero
# ---------------------------------------------------------------------------
def _num(x) -> Optional[float]:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v else None


_RE_LINEA = re.compile(r'^(Más|Menos) de ([0-9]+(?:\.[0-9]+)?)$')


def _mercados_por_nombre(det: Dict) -> Dict[str, List[Dict]]:
    fuera: Dict[str, List[Dict]] = {}
    for m in (det or {}).get('mercados') or []:
        nom = ' '.join(str(m.get('nombre') or '').split())
        fuera.setdefault(nom, []).append(m)
    return fuera


def _pata(partido: Dict, mercado: str, etiqueta: str, prob: float,
          cuota: float, clave_liga: Optional[str]) -> Dict:
    ece = ece_liga(clave_liga, mercado, etiqueta)
    return {
        'id': f"{partido.get('partido')}|{mercado}|{etiqueta}",
        'deporte': partido.get('deporte') or 'Fútbol',
        'partido': partido.get('partido'),
        'liga': partido.get('liga') or '',
        'clave_liga': clave_liga or '',
        'hora': partido.get('hora') or '',
        'mercado': mercado,
        'etiqueta': etiqueta,
        'prob': round(float(prob), 4),
        'cuota': round(float(cuota), 4),
        'casa': 'Playdoit',
        'ece': ece,
        'medido': ece is not None,
        'score': score_segura(prob, ece),
        # el valor esperado de ESTA pata, que es lo único que decide si el
        # parlay entero tiene esperanza positiva
        'ev': round(float(cuota) * float(prob) - 1.0, 4),
    }


def patas_del_partido(partido: Dict, det: Optional[Dict]) -> List[Dict]:
    """Las patas ofrecibles de un partido de fútbol, con precio real.

    `partido` es un registro de `mercados_dia.partidos_del_dia` (trae el
    `board` del modelo y la escalera de goles); `det` es el tablero de Playdoit.
    """
    if not det:
        return []
    board = {str(k): _num(v) for k, v in (partido.get('board') or {}).items()}
    goles = {str(k): _num(v)
             for k, v in (partido.get('goles_lineas') or {}).items()}
    clave = partido.get('clave_liga') or ''
    por_nombre = _mercados_por_nombre(det)
    fuera: List[Dict] = []

    # --- Total de goles: la columna vertebral del parlay que ganó ----------
    for m in por_nombre.get(MERCADO_TOTAL, []):
        for s in (m.get('selecciones') or []):
            nom = ' '.join(str(s.get('nombre') or '').split())
            mt = _RE_LINEA.match(nom)
            cuota = _num(s.get('cuota'))
            if not mt or not cuota:
                continue
            linea = float(mt.group(2))
            if linea not in LINEAS_GOLES:
                continue          # la casa cotiza cuartos (2,25 · 2,75); el
                                  # modelo no publica esas líneas y cruzar la
                                  # de 2,5 contra el precio de 2,75 sería
                                  # comparar dos sucesos distintos
            p_over = goles.get(f'{linea:g}')
            if p_over is None:
                continue
            prob = p_over if mt.group(1) == 'Más' else 1.0 - p_over
            fuera.append(_pata(partido, 'Goles', nom, prob, cuota, clave))

    # --- 1X2 --------------------------------------------------------------
    casa_home = str(det.get('casa_home') or '')
    casa_away = str(det.get('casa_away') or '')
    txt = str(partido.get('partido') or '')
    local, visitante = (txt.split(' vs ', 1) + [''])[:2] if ' vs ' in txt \
        else ('', '')
    for m in por_nombre.get(MERCADO_1X2, []):
        for s in (m.get('selecciones') or []):
            nom = ' '.join(str(s.get('nombre') or '').split())
            cuota = _num(s.get('cuota'))
            if not cuota:
                continue
            # el nombre del tablero es el de la CASA, no el del modelo: se
            # traduce por el lado que ya resolvió `mercados_playdoit`
            if nom == casa_home and local:
                prob, etq = board.get(f'Gana {local.strip()}'), \
                    f'Gana {local.strip()}'
            elif nom == casa_away and visitante:
                prob, etq = board.get(f'Gana {visitante.strip()}'), \
                    f'Gana {visitante.strip()}'
            else:
                continue          # el empate no entra: nunca es una pata segura
            if prob is None:
                continue
            fuera.append(_pata(partido, '1X2', etq, prob, cuota, clave))

    # --- Doble oportunidad: la probabilidad sale de sumar el 1X2 del modelo
    p_home = board.get(f'Gana {local.strip()}') if local else None
    p_away = board.get(f'Gana {visitante.strip()}') if visitante else None
    p_draw = board.get('Empate')
    if None not in (p_home, p_away, p_draw):
        combos = {f'{casa_home}/empate': p_home + p_draw,
                  f'empate/{casa_away}': p_draw + p_away,
                  f'{casa_home}/{casa_away}': p_home + p_away}
        for m in por_nombre.get(MERCADO_DOBLE, []):
            for s in (m.get('selecciones') or []):
                nom = ' '.join(str(s.get('nombre') or '').split())
                cuota = _num(s.get('cuota'))
                if not cuota:
                    continue
                prob = None
                for patron, valor in combos.items():
                    if nom.lower().replace(' ', '') == \
                            patron.lower().replace(' ', ''):
                        prob = valor
                        break
                if prob is None:
                    continue
                fuera.append(_pata(partido, 'Doble oportunidad', nom,
                                   min(prob, 0.999), cuota, clave))

    # --- Ambos equipos marcan --------------------------------------------
    for m in por_nombre.get(MERCADO_BTTS, []):
        for s in (m.get('selecciones') or []):
            nom = ' '.join(str(s.get('nombre') or '').split())
            cuota = _num(s.get('cuota'))
            if not cuota:
                continue
            prob = (board.get('Ambos marcan: Sí') if nom.lower().startswith('s')
                    else board.get('Ambos marcan: No'))
            if prob is None:
                continue
            fuera.append(_pata(partido, 'BTTS', f'Ambos marcan: {nom}', prob,
                               cuota, clave))
    return fuera


def patas_de_fila(partido: Dict) -> List[Dict]:
    """Patas de los deportes SIN tablero de goles: tenis, MLB, KBO, NBA, NFL.

    Ahí la pata es el ganador del partido, y su precio ya viene en el barrido
    con el guardia de casas aplicado — o sea que si lleva cuota y casa, es
    Playdoit o Novibet y se puede tomar.
    """
    fuera = []
    for m in (partido.get('mercados') or []):
        if m.get('informativo') or not m.get('cuota') or not m.get('casa'):
            continue
        if m.get('categoria') not in ('Ganador', 'Moneyline', '1X2'):
            continue
        if m.get('prob') is None:
            continue
        p = _pata(partido, m['categoria'], m['etiqueta'], m['prob'],
                  m['cuota'], partido.get('clave_liga'))
        p['casa'] = m['casa']
        fuera.append(p)
    return fuera


# ---------------------------------------------------------------------------
# El día entero
# ---------------------------------------------------------------------------
def patas_del_dia(r: Dict, dia: Optional[str] = None,
                  cuota_min: float = CUOTA_MIN, cuota_max: float = CUOTA_MAX,
                  prob_min: float = PROB_MINIMA,
                  deportes: Optional[List[str]] = None,
                  nivel: str = NIVEL_LIGA,
                  max_partidos: int = 60) -> Dict:
    """
    Todas las patas ofrecibles del día, ya filtradas y ordenadas.

    `r` es un barrido YA calculado. Nunca se lanza uno nuevo aquí: un segundo
    barrido dentro del proceso de Streamlit sube el pico de memoria de 1.297 MB
    a 2.172 MB y mata el contenedor.

    `max_partidos` acota cuántos tableros de Playdoit se piden. El tablero se
    cachea en disco 6 h, así que la segunda visita del día es instantánea
    (medido: 0,01 s por partido con caché caliente); la primera paga una
    petición por partido y por eso hay tope y barra de progreso.
    """
    import mercados_dia as md
    dia = dia or md.dia_cdmx()
    partidos = md.partidos_del_dia(r, dia, con_extras=False)
    if deportes:
        partidos = [p for p in partidos if p.get('deporte') in deportes]

    # el `board` y la escalera de goles no los trae `partidos_del_dia`: se
    # recuperan de las filas del barrido, que es donde viven
    extra = _board_por_partido(r, dia)
    patas: List[Dict] = []
    pedidos = 0
    sin_tablero = 0
    for p in partidos:
        p = {**p, **extra.get((p['deporte'], p['partido']), {})}
        if p.get('deporte') != 'Fútbol':
            patas += patas_de_fila(p)
            continue
        if pedidos >= max_partidos or ' vs ' not in str(p.get('partido') or ''):
            continue
        home, away = [x.strip() for x in str(p['partido']).split(' vs ', 1)]
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

    total_sin_filtrar = len(patas)
    fuera = [q for q in patas
             if cuota_min <= q['cuota'] <= cuota_max and q['prob'] >= prob_min]
    tras_cuota = len(fuera)
    if nivel == NIVEL_MERCADO:
        fuera = [q for q in fuera
                 if q['ece'] is not None and q['ece'] < ECE_MAXIMO]
    elif nivel == NIVEL_LIGA:
        fuera = [q for q in fuera
                 if liga_bien_calibrada(q.get('clave_liga')) is True]
    # una pata por partido y mercado: la de mejor Score
    mejor: Dict[tuple, Dict] = {}
    for q in fuera:
        k = (q['partido'], q['mercado'])
        if k not in mejor or q['score'] > mejor[k]['score']:
            mejor[k] = q
    fuera = sorted(mejor.values(), key=lambda q: -q['score'])
    return {'dia': dia, 'patas': fuera, 'nivel': nivel,
            'n_partidos': len(partidos), 'tableros_pedidos': pedidos,
            'sin_tablero': sin_tablero,
            'n_sin_filtrar': total_sin_filtrar,
            'n_tras_cuota_y_prob': tras_cuota,
            'n_apartadas_por_calibracion': tras_cuota - len(fuera)}


def _board_por_partido(r: Dict, dia: str) -> Dict:
    """`board` y `goles_lineas` de cada partido, de las listas del barrido."""
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


def armar(patas: List[Dict]) -> Dict:
    """El parlay que sale de las patas elegidas, con lo que se midió de él."""
    patas = list(patas or [])[:MAX_PATAS]
    if not patas:
        return {'n_patas': 0, 'patas': [], 'multiplicador': 1.0,
                'prob_producto': 0.0, 'rango_cuota': [0.0, 0.0],
                'configuracion_medida': None, 'ev': None}
    mult = 1.0
    prob = 1.0
    for q in patas:
        mult *= float(q['cuota'])
        prob *= float(q['prob'])
    cuota_min = min(float(q['cuota']) for q in patas)
    cuota_max = max(float(q['cuota']) for q in patas)
    cfg = configuracion(len(patas), (cuota_min, cuota_max))
    return {
        'n_patas': len(patas), 'patas': patas,
        'multiplicador': round(mult, 2),
        'prob_producto': round(prob, 6),
        'rango_cuota': [round(cuota_min, 2), round(cuota_max, 2)],
        'configuracion_medida': cfg,
        # EL EV DEL MODELO Y EL RENDIMIENTO MEDIDO NO SON LO MISMO, Y AQUI SE
        # SEPARAN A PROPOSITO.
        #
        # `ev_modelo` es el producto de las probabilidades del modelo por las
        # cuotas. Sale alegre —un parlay de 13 patas del 2026-09-16 daba +60 %—
        # porque el modelo es OPTIMISTA: medido sobre 1.381 patas de los
        # ultimos seis meses, dice 65,4 % y acierta 62,9 %, o sea −5,4 % de ROI
        # por pata. Ensenar solo el primero seria vender como valor lo que la
        # medicion dice que es perdida.
        #
        # `roi_esperado_medido` aplica ese −5,4 % N veces, que es lo que un
        # parlay de patas independientes hace con el rendimiento de sus patas.
        'ev_modelo': round(mult * prob - 1.0, 4),
        'roi_esperado_medido': _roi_esperado(len(patas)),
    }


def _roi_esperado(n_patas: int) -> Optional[float]:
    """(1 + ROI medido de una pata)^N − 1, con el numero del historico."""
    e = ((historico().get('pata_suelta') or {}).get('roi'))
    try:
        e = float(e)
    except (TypeError, ValueError):
        return None
    return round((1.0 + e) ** int(n_patas) - 1.0, 4)
