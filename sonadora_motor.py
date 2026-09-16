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

import datetime as _dt
import json
import logging
import math
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
LINEAS_GOLES_EQUIPO = (0.5, 1.5, 2.5)

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
# v208 — UNA SOLA CASA, Y NO ES UNA SIMPLIFICACION GRATUITA.
#
# La Sonadora ofrecia tres y solo una sirve para lo que el usuario arma:
#
#     Playdoit   tablero completo: goles totales y por equipo, cornes,
#                tarjetas, remates, 1X2, doble oportunidad, BTTS
#     Novibet    medido el 2026-09-15 barriendo 36 tipos de apuesta x 6
#                alcances sobre tres partidos grandes: publica CUATRO
#                mercados y NI UNA LINEA DE GOLES. Su propia pagina de
#                Flashscore la pinta con un guion en las 22 lineas de
#                Mas/Menos. El patron del usuario es de goles, asi que
#                Novibet no puede armarlo.
#     Draftea    sus precios viven dentro de la app movil. Re-sondeada el
#                2026-09-16: la web es Webflow de marketing y
#                `api.draftea.com` da 404 en las veinte rutas probadas.
#
# Un selector con tres opciones de las que dos no pueden hacer el trabajo no
# es una eleccion: es una forma de que el usuario se equivoque. Se queda la
# que tiene el tablero.
CASAS = ('Playdoit',)
CASA_POR_DEFECTO = 'Playdoit'
# las que hoy tienen fuente; el resto se ofrece y se explica
CASAS_CON_FUENTE = ('Playdoit',)

DEPORTES = ('Fútbol', 'MLB', 'NBA', 'NFL', 'Tenis', 'KBO')
DEPORTES_POR_DEFECTO = ('Fútbol',)
# clave de Altenar por deporte, para pedir el tablero de Playdoit
CLAVE_PDT = {'Fútbol': 'futbol', 'Tenis': 'tenis', 'MLB': 'mlb',
             'NBA': 'nba', 'NFL': 'nfl'}

# --- LA CAPA DE RIESGO, Y POR QUE ORDENA EN VEZ DE BLOQUEAR -----------------
#
# `riesgo_liga` mide el nivel de cada competicion por su error de calibracion.
# Medido sobre 16.428 patas del ledger con cuota de cierre real (24 meses):
#
#     competiciones de riesgo ALTO  ...  ROI de una pata  -7,14 %  (625 patas)
#     competiciones de riesgo MEDIO ...                   -5,24 %
#     competiciones de riesgo BAJO  ...                   -1,53 %
#
# La señal es fuerte y separa 5,6 puntos. LO QUE NO SALIO es que bloquear
# mejore el parlay: quitar el cuarto peor mueve 625 patas de 16.428 y el ROI
# proyectado sube 0,5 puntos. Y quedarse SOLO con el cuarto mejor si lo sube
# —de -14,9 % a -6,0 % en un parlay de cuatro, +8,9 puntos— pero se lleva el
# 72,4 % del catalogo, por encima del tope del 60 % que el propio encargo puso
# para que un filtro no vacie la pantalla (`validar_riesgo.py`).
#
# Asi que el nivel ORDENA y se ENSEÑA, y bloquear es una casilla que el usuario
# marca si quiere, con el numero medido al lado. Es la misma decision que el
# proyecto ya tomo con «🔒 No recomendado» en la v175: la informacion no se
# pierde, deja de decidir por el usuario.
ORDEN_RIESGO = {'baja': 0, 'sin_medir': 1, 'media': 1, 'alta': 2}

# Los topes de exposicion dentro de un parlay.
#
# NO MEJORAN EL ROI Y NO PUEDEN HACERLO: un parlay de patas independientes
# rinde (1+e)^N - 1, asi que como se repartan las patas entre ligas y mercados
# no cambia la esperanza. Medido: con el tope por liga el ROI proyectado se
# mueve 0,0 puntos. Lo que si hacen es quitar CORRELACION —dos patas de la
# misma jornada y la misma liga fallan juntas mucho mas a menudo de lo que el
# producto de sus probabilidades dice— y por eso se aplican igual, pero
# vendidos por lo que son: control de varianza, no de rendimiento.
MAX_POR_LIGA = 2
MAX_POR_MERCADO = 2
MAX_POR_DEPORTE = 3

# Registro de parlays vivos, para que un partido no entre en dos a la vez.
ACTIVOS = 'parlays_activos.json'

# --- EL PATRON DEL BOLETO QUE EL USUARIO GANO -------------------------------
#
# 13 patas, 46 pesos, 245,05x que el boost dejo en 490,10x: 22.544,60. Leido
# pata a pata del boleto, el patron no es una intuicion, es una cuenta:
#
#     10 de 13 son GOLES TOTALES     5x «Mas de 2,5» · 5x «Mas de 1,5»
#      3 de 13 son «Gana X»          las tres con Pago Anticipado
#     cuotas de 1,35 a 1,79          media 1,532 · mediana 1,50
#     probabilidad implicita         65,7 % por pata · 0,408 % el boleto
#     goles reales de esas 10 patas  3 6 8 5 3 4 3 2 6 3  ·  media 4,30
#
# O sea que no hubo ni una pata de cornes, ni de tarjetas, ni de remates, ni
# de handicap: **goles y ganador, y nada mas**. Y ninguna «Menos de»: las diez
# eran «Mas de», que es una apuesta a que el partido se abra.
#
# Esto NO dice que la estrategia gane —un boleto ganador es un boleto ganador,
# y la validacion historica de esta seccion sigue midiendo lo que mide—. Dice
# que cuando el usuario arma a mano, arma ESTO, y que la pantalla tiene que
# saber ofrecerselo en vez de encabezar la lista con «Menos de 9,5 remates a
# puerta», que es lo que hacia.
CATEGORIAS_PATRON = ('Goles', '1X2', 'Ganador')
PREFIJOS_PATRON = ('Más de', 'Gana')
CUOTA_PATRON = (1.35, 1.80)

# Los tamaños de boleto que la escalera ofrece de golpe.
TAMANOS_ESCALERA = (4, 6, 8, 10, 13)


def del_patron(q: Dict) -> bool:
    """¿Esta pata es de las que el usuario combina de verdad?"""
    if q.get('categoria') not in CATEGORIAS_PATRON:
        return False
    etq = str(q.get('etiqueta') or '')
    if not etq.startswith(PREFIJOS_PATRON):
        return False
    try:
        c = float(q.get('cuota'))
    except (TypeError, ValueError):
        return False
    return CUOTA_PATRON[0] <= c <= CUOTA_PATRON[1]


def filtrar_patron(patas: List[Dict]) -> List[Dict]:
    """Sólo las patas del patrón. Lista vacía si no hay ninguna."""
    return [q for q in (patas or []) if del_patron(q)]


# Días distintos que puede abarcar un boleto. El encargo pide «no más de una
# semana» y es un tope sensato por otra razón: cuanto más lejos, menos
# mercados tiene abiertos la casa y más se mueve el precio antes del partido.
MAX_DIAS_RANGO = 7


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


# --- LA CALIBRACION DE LA PATA, QUE ES LO QUE DEJA DE MENTIR ----------------
#
# Simulado sobre 540 dias de jornadas ya jugadas (`simular_sonadora.py`), la
# seccion prometia el doble o el triple de lo que daba:
#
#     4 patas   promete 59,76 %   da 37,23 %   ratio 0,62
#     8 patas   promete 32,20 %   da 13,70 %   ratio 0,43
#    13 patas   promete 14,49 %   da  4,74 %   ratio 0,33
#
# El ratio cae con cada pata: es una probabilidad sobreconfiada multiplicandose
# por si misma. El mapa de `modelos/calibracion_patas.json` la lleva a la que
# se observa de verdad, y con eso el boleto de ocho pasa a dar 15,19 % contra
# un 13,35 % prometido — ratio 1,14, o sea que ya cumple.
#
# Lo que el mapa dice, y es fuerte:
#
#     «Mas de 2,5»  el modelo dice 90 % y cae el 61 %
#     «Mas de 3,5»  el modelo dice 55 % y cae el 38-43 %
#     «Ambos marcan» TODAS las cajas caen entre el 54 y el 59 %: el modelo no
#                    distingue nada en ese mercado
#     «Mas de 1,5»  la mejor portada, monotona y con el menor desvio
#
# Por eso la calibracion entra en `prob` y no en un campo decorativo: de ella
# cuelgan el semaforo, el Score y el producto del boleto. La probabilidad
# cruda se conserva en `prob_modelo` para poder comparar.
CALIBRACION = 'modelos/calibracion_patas.json'
_CAL: Optional[Dict] = None


def calibracion(ruta: str = CALIBRACION) -> Dict:
    global _CAL
    if _CAL is None:
        try:
            with open(ruta, encoding='utf-8') as f:
                _CAL = json.load(f) or {}
        except Exception as e:
            logger.debug('[sonadora] sin mapa de calibración: %s', e)
            _CAL = {}
    return _CAL


def _olvidar_calibracion() -> None:
    global _CAL
    _CAL = None


def prob_calibrada(etiqueta: str, prob) -> Tuple[float, bool]:
    """(probabilidad observada para esa etiqueta y tramo, si se corrigió).

    Sin mapa, sin la etiqueta o sin muestra suficiente en su celda, devuelve la
    probabilidad tal cual: no corregir es mejor que corregir con ruido.
    """
    try:
        p = float(prob)
    except (TypeError, ValueError):
        return prob, False
    doc = calibracion()
    celdas = (doc.get('etiquetas') or {}).get(str(etiqueta))
    if not celdas:
        return p, False
    cajas = doc.get('cajas') or []
    caja = None
    for i in range(len(cajas) - 1):
        if (p >= cajas[i] if i == 0 else p > cajas[i]) and p <= cajas[i + 1]:
            caja = i
            break
    if caja is None:
        return p, False
    celda = celdas.get(str(caja))
    if not isinstance(celda, dict) or celda.get('observado') is None:
        # LA CELDA SIN MUESTRA SE APOYA EN LA VECINA CON DATOS, Y NO SE DEJA
        # CRUDA. Es justo donde más falta hace: «Más de 2,5» al 92 % cae en un
        # tramo que el histórico casi no tiene, y dejarlo tal cual conserva el
        # número más sobreconfiado de todos. El mapa es monótono por mercado,
        # así que la celda vecina es una estimación mucho mejor que el crudo.
        # Se prefiere la de ABAJO para las probabilidades altas: extrapolar
        # hacia arriba inventaría confianza que nadie ha medido.
        cercanas = []
        for k, v in celdas.items():
            if not isinstance(v, dict) or v.get('observado') is None:
                continue
            try:
                cercanas.append((abs(int(k) - caja), int(k) > caja, int(k),
                                 float(v['observado'])))
            except (TypeError, ValueError):
                continue
        if not cercanas:
            return p, False
        cercanas.sort()
        return cercanas[0][3], True
    return float(celda['observado']), True


def _riesgo_de(clave_liga: str) -> Tuple[str, Optional[float]]:
    """Nivel de riesgo e IVL de la competición. Nunca lanza y nunca bloquea."""
    try:
        import riesgo_liga as rl
        f = rl.ficha(clave_liga)
        return rl.nivel_liga(clave_liga), f.get('ivl')
    except Exception as e:
        logger.debug('[sonadora] sin índice de riesgo: %s', e)
        return 'sin_medir', None


def _rebote_de(partido: Dict) -> bool:
    """¿Efecto rebote por entrenador nuevo? HOY SIEMPRE `False`, y a propósito.

    `filtro_contexto` no tiene fuente —ESPN no publica cuerpo técnico, medido
    el 2026-09-15— así que la regla está escrita y apagada. El campo viaja en
    la pata igualmente porque el encargo lo pide y porque el día que haya
    fuente no hay que tocar nada más.
    """
    try:
        import filtro_contexto as fc
        if not fc.hay_fuente():
            return False
        home, away = _lados(partido.get('partido'))
        info = fc.rebote_entrenador(home, away, partido.get('dia') or '',
                                    cuota_favorito=partido.get('cuota_favorito'),
                                    lado_favorito=partido.get('lado_favorito') or '')
        return bool(info.get('activo'))
    except Exception as e:
        logger.debug('[sonadora] sin filtro de contexto: %s', e)
        return False


def _pata(partido: Dict, categoria: str, etiqueta: str, prob, cuota,
          casa: str = 'Playdoit') -> Optional[Dict]:
    p, c = _num(prob), _num(cuota)
    if p is None or c is None or not (0.0 < p < 1.0) or c <= 1.0:
        return None
    clave = partido.get('clave_liga') or ''
    ece = ece_liga(clave, categoria, etiqueta)
    floja = calibracion_floja(clave, categoria, etiqueta)
    riesgo, ivl = _riesgo_de(clave)
    # LA CALIBRACION ENTRA AQUI, ANTES QUE NADA. De `p` cuelgan el semaforo, el
    # Score y el producto del boleto; corregirla despues seria maquillar el
    # numero que se ensena dejando intacto el que decide.
    p_crudo = p
    p, corregida = prob_calibrada(etiqueta, p)
    if not (0.0 < p < 1.0):
        p = p_crudo
        corregida = False
    return {
        'prob_modelo': round(p_crudo, 4),
        'prob_calibrada': bool(corregida),
        'nivel_riesgo': riesgo,
        # el IVL del encargo, PUBLICADO COMO DESCRIPTOR y no como puerta: mide
        # el ritmo goleador de la liga (vale 1/raiz(media de goles)) y medido
        # contra el ROI real da Spearman -0,113. Quien lo mire sabra que en esa
        # liga se marcan pocos goles, que es informacion util para una pata de
        # «Mas de 2,5» y no un motivo para bloquear nada.
        'ivl_liga': ivl,
        'rebote_entrenador': _rebote_de(partido),
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


def _probs_handicap(partido: Dict, local: str, visitante: str) -> Dict:
    """P(cubrir) de cada línea de hándicap, desde la matriz de marcador.

    La clave es el hándicap CON SIGNO tal y como lo ve el equipo que lo lleva:
    −1,5 para el favorito que debe ganar por dos, +1,5 para el que puede
    perder por uno. Se calcula sobre la diferencia de goles.

    LAS LÍNEAS ENTERAS Y LAS MEDIAS NO SE TRATAN IGUAL, y es la trampa clásica
    del hándicap asiático: con −1 exacto un triunfo por uno es EMPATE TÉCNICO y
    devuelven la apuesta, así que su probabilidad de GANAR no incluye ese caso.
    Aquí se publica la probabilidad de cubrir sin contar el nulo, que es la que
    corresponde al precio que la casa paga. Los cuartos (−0,25, −0,75) parten
    la apuesta en dos mitades y se descartan: dar una sola probabilidad a una
    apuesta que son dos sería inventar un suceso que no existe.
    """
    fuera: Dict[Tuple[str, float], float] = {}
    try:
        import numpy as np
        M = np.asarray(partido.get('score_matrix'), dtype=float)
        if M.ndim != 2 or not M.size:
            return fuera
    except Exception:
        return fuera
    idx = np.arange(M.shape[0])
    dif = idx[:, None] - idx[None, :]          # goles locales − visitantes
    # de medio en medio gol: los cuartos (−0,25, −0,75) parten la apuesta en
    # dos mitades y no tienen UNA probabilidad de ganar
    paso = [x / 2.0 for x in range(-24, 25)]
    for h in paso:
        for lado, propio in (('home', dif), ('away', -dif)):
            gana = float(M[(propio + h) > 0].sum())
            nulo = float(M[(propio + h) == 0].sum())
            resto = 1.0 - nulo
            if resto <= 1e-9:
                continue
            fuera[(lado, round(h, 2))] = round(min(gana / resto, 0.9999), 4)
    return fuera


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
    # v204 — LAS TRES, NO UNA. El comentario anterior decía que «el comparador
    # publica SÓLO `homeOrDraw`», y era falso: publica las tres y este lector
    # preguntaba por dos nombres que el servicio no usa (`drawOrAway` y
    # `homeOrAway` en vez de `awayOrDraw` y `noDraw`). Se arregló en
    # `cuotas_mx.cuotas_evento`; aquí se leen con los nombres buenos y se
    # aceptan los viejos por si queda un fichero de antes.
    doble = nb.get('DOUBLE_CHANCE')
    if isinstance(doble, dict) and None not in (p_h, p_a, p_x):
        for campos, prob, etq in (
                (('homeOrDraw',), p_h + p_x, f'{local} o empate'),
                (('awayOrDraw', 'drawOrAway'), p_x + p_a,
                 f'Empate o {visitante}'),
                (('noDraw', 'homeOrAway'), p_h + p_a,
                 f'{local} o {visitante}')):
            cuota = next((doble[c] for c in campos
                          if doble.get(c) is not None), None)
            if cuota is None:
                continue
            _add('Doble oportunidad', etq, min(prob, 0.999), cuota)

    # --- HANDICAP ASIATICO, QUE ES LO QUE NOVIBET SI DA EN VOLUMEN --------
    #
    # MEDIDO EL 2026-09-15, barriendo 36 tipos de apuesta x 6 alcances sobre
    # tres partidos grandes: en el comparador **Novibet publica exactamente
    # cuatro mercados** —1X2, doble oportunidad, ambos marcan y handicap
    # asiatico— y ni una linea de goles. No es que el lector las tire: la
    # propia pagina de Flashscore pinta a Novibet en la tabla de Mas/Menos con
    # un guion en todas las lineas, y la casa no alimenta ese mercado al
    # comparador.
    #
    # Pero el handicap trae 14-22 lineas por partido y NO SE ESTABA USANDO,
    # porque el barrido no publica probabilidad de handicap. Ahora si se
    # puede: sale de la matriz de marcador, que es la misma fuente de la que
    # sale la escalera de goles.
    hcp = nb.get('ASIAN_HANDICAP')
    lineas_h = (hcp or {}).get('lineas') if isinstance(hcp, dict) else None
    if lineas_h:
        probs = _probs_handicap(partido, local, visitante)
        for fila in lineas_h:
            if not isinstance(fila, dict):
                continue
            linea = _num(fila.get('linea'))
            if linea is None:
                continue
            # LA LINEA VIENE DESDE EL LADO DEL LOCAL. «−1,5» es el local dando
            # goles, y en esa misma fila el precio del visitante es el de «+1,5».
            for lado, equipo, h in (('home', local, linea),
                                    ('away', visitante, -linea)):
                cuota = _num(fila.get(lado))
                if cuota is None:
                    continue
                p = probs.get((lado, round(h, 2)))
                if p is None:
                    continue                   # cuartos y líneas fuera de rango
                _add('Hándicap', f'{equipo} {h:+g}', p, cuota)

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


# ---------------------------------------------------------------------------
# EL UNIVERSO DE PARTIDOS, Y POR QUE NO PUEDE SALIR DEL BARRIDO
# ---------------------------------------------------------------------------
#
# LO QUE PASABA. La Sonadora tomaba sus partidos de `mercados_dia.
# partidos_del_dia(r, dia)`, que recorre las doce listas del barrido. Y esas
# listas son listas de PICKS: capa1, capa2, candidatos, elite… o sea, partidos
# que pasaron los filtros de probabilidad y EV del sistema. Un dia en que el
# futbol no produce ni un pick deja a la Sonadora sin un solo partido de
# futbol, aunque haya doscientos en el catalogo con precio en la casa.
#
# MEDIDO el 2026-09-15 sobre el barrido real de las 20:01:
#
#     deportes_cubiertos del barrido ....  KBO, MLB, NFL, Tenis  (futbol NO)
#     cobertura_ligas ...................  MLB 12 · ATP 173 · WTA 159 ·
#                                          KBO 4 · NFL 16   (ni una de futbol)
#     patas de futbol en la Sonadora ....  0
#
#     y en el mismo momento, en disco:
#     predicciones_dia.json .............  147 partidos de futbol de 45
#                                          competiciones, con matriz de
#                                          marcador
#     cuotas_mx.json ....................  290 partidos de futbol con precio
#                                          de cinco casas mexicanas
#
# Las dos mitades de una pata —probabilidad del modelo y precio de la casa—
# estaban en disco y la seccion ensenaba cero. El barrido no fallaba: hacia lo
# suyo, que es elegir picks. Lo que estaba mal era pedirle el catalogo.
#
# ASI QUE EL UNIVERSO SE CONSTRUYE APARTE: todo partido que tenga probabilidad
# del modelo Y precio de la casa elegida entra, haya producido pick o no. El
# barrido sigue usandose para los demas deportes y para el contexto.
def board_de_prediccion(pred: Dict, home: str, away: str,
                        clave_liga: str = '') -> Dict[str, float]:
    """Todas las probabilidades del partido, desde la matriz de marcador.

    Es la misma cuenta que hacen `partidos_jugados._board_de_matriz` y el
    barrido —1X2 por triangulos, la escalera de goles sumando por diagonales y
    «ambos marcan» quitando fila y columna cero— extendida a lo que la
    Sonadora necesita: las seis lineas de goles totales, las tres por equipo y
    la doble oportunidad.

    Se calcula aqui y no se importa de `alpha_finder` porque alli vive dentro
    de `_mercados_del_partido`, que exige cuotas; el universo de la Sonadora
    empieza justo antes de tener precio.
    """
    fuera: Dict[str, float] = {}
    try:
        import numpy as np
        M = np.asarray(pred.get('score_matrix'), dtype=float)
        if M.ndim != 2 or not M.size:
            return fuera
    except Exception as e:
        logger.debug('[sonadora] matriz ilegible: %s', e)
        return fuera
    pr = pred.get('probabilities') or {}
    idx = np.arange(M.shape[0])
    total = idx[:, None] + idx[None, :]
    try:
        pl, px, pv = float(pr['home']), float(pr['draw']), float(pr['away'])
    except (KeyError, TypeError, ValueError):
        pl = float(np.tril(M, -1).sum())
        px = float(np.trace(M))
        pv = float(np.triu(M, 1).sum())

    # LA ACLIMATACION, QUE ES LA UNICA CORRECCION DE CONTEXTO MEDIDA.
    #
    # Cuando el visitante sube 1.000 m o mas a una sede por encima de 2.200, el
    # modelo se queda corto con el local. Medido fuera de muestra sobre 376
    # partidos (`validar_contexto.py`): el log-loss baja un 1,54 % y el error
    # de calibracion un 34 %.
    #
    # NO se aplica por estar la sede alta —eso se midio y es ruido— sino por el
    # DESNIVEL: en la Liga MX los dos equipos llegan aclimatados y ahi no hay
    # nada que corregir. Y si el JSON de medicion dice que la prueba no mejora,
    # `ajustar_1x2` devuelve las probabilidades intactas: el motor lee el
    # veredicto, no lo presupone.
    aclimatacion = False
    if clave_liga:
        try:
            import contexto_ampliado as ca
            ficha = ca.de_partido(clave_liga, home, away)
            sube = bool((ficha.get('altitud') or {}).get('sube_visitante'))
            pl, px, pv, aclimatacion = ca.ajustar_1x2(pl, px, pv, sube)
        except Exception as e:
            logger.debug('[sonadora] contexto ampliado: %s', e)
    fuera['_aclimatacion'] = 1.0 if aclimatacion else 0.0
    fuera[f'Gana {home}'] = pl
    fuera['Empate'] = px
    fuera[f'Gana {away}'] = pv
    fuera[f'{home} o empate'] = pl + px
    fuera[f'Empate o {away}'] = px + pv
    fuera[f'{home} o {away}'] = pl + pv
    for ln in LINEAS_GOLES:
        over = float(M[total > ln].sum())
        fuera[f'Más de {ln}'] = over
        fuera[f'Menos de {ln}'] = 1.0 - over
    # POR EQUIPO, DESDE LAS MARGINALES de la matriz. Es lo mismo que hace
    # `alpha_finder.lineas_por_equipo`, y va con el mismo aviso: no esta
    # calibrado contra resultados reales (§3 de lo que queda del traspaso).
    mh, ma = M.sum(axis=1), M.sum(axis=0)
    for ln in LINEAS_GOLES_EQUIPO:
        oh, oa = float(mh[idx > ln].sum()), float(ma[idx > ln].sum())
        fuera[f'{home}: más de {ln}'] = oh
        fuera[f'{home}: menos de {ln}'] = 1.0 - oh
        fuera[f'{away}: más de {ln}'] = oa
        fuera[f'{away}: menos de {ln}'] = 1.0 - oa
    btts = float(M[1:, 1:].sum())
    fuera['Ambos marcan: Sí'] = btts
    fuera['Ambos marcan: No'] = 1.0 - btts
    return {k: (round(v, 4) if not k.startswith('_') else v)
            for k, v in fuera.items() if 0.0 <= v <= 1.0}


def lineas_de_prediccion(pred: Dict) -> Dict:
    """La escalera de goles del partido, en el formato que espera el motor.

    `patas_del_partido` NO lee los goles del `board`: los lee de
    `goles_lineas` —«0.5» → P(más de 0,5)— y los de cada equipo de
    `goles_equipo`, porque así los publica el barrido. Sin esto, un partido
    del catálogo llega con el 1X2 y el «ambos marcan» y **sin una sola pata de
    goles**, que es la columna vertebral del parlay que el usuario ganó: ocho
    de sus trece patas eran Total de Goles.
    """
    vacio = {'goles_lineas': {}, 'goles_equipo': {}}
    try:
        import numpy as np
        M = np.asarray(pred.get('score_matrix'), dtype=float)
        if M.ndim != 2 or not M.size:
            return vacio
    except Exception:
        return vacio
    idx = np.arange(M.shape[0])
    total = idx[:, None] + idx[None, :]
    lineas = {f'{ln:g}': round(float(M[total > ln].sum()), 4)
              for ln in LINEAS_GOLES}
    mh, ma = M.sum(axis=1), M.sum(axis=0)
    equipo = {
        'local': {f'{ln:g}': round(float(mh[idx > ln].sum()), 4)
                  for ln in LINEAS_GOLES_EQUIPO},
        'visitante': {f'{ln:g}': round(float(ma[idx > ln].sum()), 4)
                      for ln in LINEAS_GOLES_EQUIPO},
    }
    return {'goles_lineas': lineas, 'goles_equipo': equipo}


def _dia_y_hora(inicio) -> Tuple[str, str]:
    """(día CDMX, 'HH:MM') de un inicio, en cualquiera de sus formatos."""
    if inicio is None or inicio == '':
        return '', ''
    try:
        import horario
        d = horario.fecha(inicio)
        h = horario.hora(inicio) if hasattr(horario, 'hora') else ''
        if d:
            return str(d)[:10], str(h or '')[:5]
    except Exception:
        pass
    # respaldo: marca de tiempo Unix como la que trae `cuotas_mx.json`
    try:
        t = _dt.datetime.fromtimestamp(
            int(float(inicio)), _dt.timezone(_dt.timedelta(hours=-6)))
        return t.date().isoformat(), t.strftime('%H:%M')
    except (TypeError, ValueError, OSError, OverflowError):
        pass
    try:
        t = _dt.datetime.fromisoformat(str(inicio))
        return t.date().isoformat(), t.strftime('%H:%M')
    except (TypeError, ValueError):
        return str(inicio)[:10], ''


def partidos_de_predicciones(dia: str, casa: str = CASA_POR_DEFECTO,
                             limite: int = 400) -> List[Dict]:
    """Los partidos de fútbol de ese día con probabilidad del modelo.

    La fecha del partido sale, por este orden:

    1. Del propio `predicciones_dia.json`, si lo lleva. Desde la v203 lo
       lleva: `predicciones_dia.generar` guardaba el resultado del modelo y
       tiraba la hora del fixture, y sin hora no se puede saber de qué día es
       un partido.
    2. Del fichero de las casas mexicanas, que sí guarda `inicio`. Es el
       respaldo para un `predicciones_dia.json` generado antes de ese cambio,
       y es lo que hace que esto funcione HOY sin esperar al workflow.

    Un partido sin fecha por ninguna de las dos vías se descarta: meterlo
    «por si acaso» sería enseñar el partido de mañana como si fuera de hoy.
    """
    try:
        import predicciones_dia as pd_
        doc = pd_._leer() or {}
    except Exception as e:
        logger.debug('[sonadora] sin predicciones precalculadas: %s', e)
        return []
    preds = (doc.get('predicciones') or {})
    if not preds:
        return []
    try:
        import cuotas_mx as mx
    except Exception:
        mx = None

    fuera: List[Dict] = []
    for clave, pred in preds.items():
        if len(fuera) >= limite:
            break
        if not isinstance(pred, dict):
            continue
        partes = str(clave).split('|', 2)
        liga = pred.get('clave_liga') or (partes[0] if partes else '')
        home = pred.get('home') or (partes[1] if len(partes) > 1 else '')
        away = pred.get('away') or (partes[2] if len(partes) > 2 else '')
        if not (home and away):
            continue
        d, hora = _dia_y_hora(pred.get('inicio') or pred.get('fecha'))
        inicio = pred.get('inicio')
        if d != dia and mx is not None:
            try:
                reg = mx.buscar('futbol', home, away)
            except Exception:
                reg = None
            if reg:
                inicio = reg.get('inicio')
                d, hora = _dia_y_hora(inicio)
        if d != dia:
            continue
        board = board_de_prediccion(pred, home, away, liga)
        if not board:
            continue
        fuera.append({
            'deporte': 'Fútbol', 'partido': f'{home} vs {away}',
            'liga': liga, 'clave_liga': liga, 'hora': hora,
            'inicio': inicio, 'board': board,
            'origen': 'predicciones precalculadas',
            # la matriz viaja con el partido: de ella salen las
            # probabilidades del hándicap, que no están en el tablero
            'score_matrix': pred.get('score_matrix'),
            **lineas_de_prediccion(pred),
        })
    return fuera


def _con_dia(patas: List[Dict], dia: str) -> List[Dict]:
    """Marca cada pata con el día del que salió y hace único su `id`.

    Sin el día dentro del `id`, dos partidos del mismo cruce en días distintos
    —una eliminatoria de ida y vuelta, una serie de béisbol— colisionan en el
    selector manual y la pantalla enseña uno donde el usuario eligió el otro.
    """
    fuera = []
    for q in patas:
        q = dict(q)
        q['dia'] = dia
        q['id'] = f"{dia}|{q.get('id')}"
        fuera.append(q)
    return fuera


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
    # EL CATALOGO DE FUTBOL NO SALE DEL BARRIDO (ver el bloque de arriba): se
    # anaden los partidos con probabilidad del modelo que el barrido no trajo
    # porque no produjeron pick. Se deduplica por nombre de partido, asi que
    # el que SI venia del barrido conserva su fila —con su contexto y su casa
    # elegida por el guardia— y solo se suman los que faltaban.
    del_barrido = 0
    if 'Fútbol' in quiero:
        del_barrido = sum(1 for p in partidos if p.get('deporte') == 'Fútbol')
        vistos = {str(p.get('partido')) for p in partidos
                  if p.get('deporte') == 'Fútbol'}
        for p in partidos_de_predicciones(dia, casa):
            if str(p.get('partido')) not in vistos:
                vistos.add(str(p.get('partido')))
                partidos.append(p)
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
            'futbol_del_barrido': del_barrido,
            'futbol_del_catalogo': sum(
                1 for p in partidos
                if p.get('origen') == 'predicciones precalculadas'),
            'sin_tablero': sin_tablero}


def patas_del_dia(r: Dict, dia: Optional[str] = None,
                  cuota_min: float = CUOTA_MIN, cuota_max: float = CUOTA_MAX,
                  max_partidos: int = 60,
                  deportes: Optional[List[str]] = None,
                  con_rojas: bool = False,
                  casa: str = CASA_POR_DEFECTO,
                  solo_riesgo_bajo: bool = False,
                  dias: Optional[List[str]] = None,
                  garantizar: int = 0,
                  solo_patron: bool = False) -> Dict:
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

    # EL RANGO DE FECHAS. Un parlay se puede armar con partidos de varios días
    # —las casas lo permiten— y con seis partidos de fútbol en toda la jornada
    # de un martes de septiembre es la única forma de llegar a trece patas.
    #
    # Lo que NO se hace es esconderlo: cada pata lleva su día, y `armar` dice
    # cuántos días distintos abarca el boleto. La validación histórica mide
    # parlays de un solo día a propósito —los partidos de una misma jornada
    # comparten contexto— así que un boleto repartido en cinco días NO está
    # cubierto por esa medición, y la pantalla lo avisa.
    lista_dias = [d for d in (dias or [dia]) if d]
    lista_dias = sorted(dict.fromkeys(lista_dias))[:MAX_DIAS_RANGO]
    if len(lista_dias) > 1:
        trozos = [_recoger(r, d, max_partidos, deportes, casa)
                  for d in lista_dias]
        bruto = {
            'patas': [q for i, t in enumerate(trozos)
                      for q in _con_dia(t['patas'], lista_dias[i])],
            'n_partidos': sum(t['n_partidos'] for t in trozos),
            'tableros_pedidos': sum(t['tableros_pedidos'] for t in trozos),
            'tableros_por_deporte': {},
            'futbol_del_barrido': sum(t.get('futbol_del_barrido', 0)
                                      for t in trozos),
            'futbol_del_catalogo': sum(t.get('futbol_del_catalogo', 0)
                                       for t in trozos),
            'sin_tablero': sum(t['sin_tablero'] for t in trozos),
        }
    else:
        bruto = _recoger(r, lista_dias[0], max_partidos, deportes, casa)
        bruto['patas'] = _con_dia(bruto['patas'], lista_dias[0])
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
        #
        # EL NIVEL DE RIESGO ENTRA DETRAS DEL COLOR Y DELANTE DE «MEDIDO».
        # Es la señal mas fuerte de las dos: el cuarto peor de competiciones
        # rinde -7,14 % por pata y el mejor -1,53 %, medido sobre 16.428 patas
        # con cuota de cierre real.
        return sorted((q for q in todas
                       if lo <= q['cuota'] <= hi and q['prob'] >= PROB_MINIMA),
                      key=lambda q: (ORDEN_COLOR.get(q['color'], 9),
                                     ORDEN_RIESGO.get(q.get('nivel_riesgo'), 1),
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

    # EL FILTRO DE RIESGO, QUE ES OPCIONAL Y LO ENCIENDE EL USUARIO.
    #
    # Se aplica ANTES de ensanchar el rango de cuota a propósito: si el usuario
    # pide sólo competiciones bien calibradas, la respuesta correcta a «no hay»
    # es ensanchar la cuota, no colar de vuelta las competiciones que acaba de
    # descartar. Y si con el filtro no queda NADA, se apaga solo y se dice —la
    # pantalla vacía es el fallo que el rediseño de la Soñadora vino a quitar.
    riesgo_apagado = False
    if solo_riesgo_bajo:
        _bajas = [q for q in todas if q.get('nivel_riesgo') == 'baja']
        if _bajas:
            todas = _bajas
        else:
            riesgo_apagado = True

    if solo_patron:
        _pat = filtrar_patron(todas)
        if _pat:
            todas = _pat

    patas = _filtra(cuota_min, cuota_max)
    ensanchado = False
    if not patas and todas:
        patas = _filtra(CUOTA_MIN_ABS, CUOTA_MAX_ABS)
        ensanchado = bool(patas)

    # --- QUE SALGAN LAS PATAS QUE SE PIDEN, Y DECIR QUÉ COSTÓ --------------
    #
    # «Sí o sí debe de haber el número de patas que se pidan en el filtro».
    # Un boleto necesita N PARTIDOS DISTINTOS —una pata por encuentro, que es
    # la regla que evita combinar sucesos correlacionados—, así que cuando no
    # llegan se ensancha por pasos, del más barato al más caro, y se para en
    # cuanto alcanza. Cada paso que se da se apunta: un boleto armado con el
    # rango ensanchado y las rojas dentro no es el mismo que uno armado con lo
    # que se pidió, y la pantalla tiene que poder decirlo.
    relajado: List[str] = []

    def _n_partidos(lista):
        return len({q['partido'] for q in lista})

    if garantizar and _n_partidos(patas) < garantizar:
        pasos = [
            ('el rango de cuota', lambda: _filtra(CUOTA_MIN_ABS,
                                                  CUOTA_MAX_ABS)),
        ]
        if solo_patron:
            # se sale del patrón antes que dejar el boleto corto
            def _fuera_del_patron():
                base = bruto['patas']
                base = [q for q in base if q.get('casa') == casa]
                _v, _u = set(), []
                for q in base:
                    k = (q['partido'], q['etiqueta'])
                    if k in _v:
                        continue
                    _v.add(k)
                    _u.append(q)
                return sorted(
                    (q for q in _u if CUOTA_MIN_ABS <= q['cuota']
                     <= CUOTA_MAX_ABS and q['prob'] >= PROB_MINIMA),
                    key=lambda q: (ORDEN_COLOR.get(q['color'], 9),
                                   ORDEN_RIESGO.get(q.get('nivel_riesgo'), 1),
                                   not q.get('medido'), -q['score']))
            pasos.append(('el patrón del boleto', _fuera_del_patron))
        for nombre, intento in pasos:
            if _n_partidos(patas) >= garantizar:
                break
            nuevas = intento()
            if _n_partidos(nuevas) > _n_partidos(patas):
                patas = nuevas
                relajado.append(nombre)
        if relajado and 'el rango de cuota' in relajado:
            ensanchado = True

    # LA CASCADA: si hay algo mejor que rojo, las rojas se esconden. Si NO hay
    # nada mejor, se enseñan igual — la sección no se queda vacía por esconder
    # lo único que hay.
    conteo = {c: sum(1 for q in patas if q['color'] == c)
              for c in (VERDE, AMBAR, ROJO, GRIS)}
    visibles = patas
    if not con_rojas:
        sin_rojas = [q for q in patas if q['color'] != ROJO]
        # LAS ROJAS ENTRAN SI SIN ELLAS NO SE LLEGA AL NÚMERO PEDIDO. Es el
        # último paso del ensanchado y el más caro, por eso va aquí y no
        # antes: esconder una pata de alto riesgo es preferible, pero dejar el
        # boleto corto cuando el usuario pidió trece no lo es.
        if sin_rojas and (not garantizar
                          or len({q['partido'] for q in sin_rojas})
                          >= garantizar):
            visibles = sin_rojas
        elif sin_rojas:
            relajado.append('se incluyen patas de alto riesgo')
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
        'futbol_del_barrido': bruto.get('futbol_del_barrido', 0),
        'futbol_del_catalogo': bruto.get('futbol_del_catalogo', 0),
        'sin_tablero': bruto['sin_tablero'],
        'n_sin_filtrar': len(todas),
        'n_medidas': sum(1 for q in visibles if q['medido']),
        'partidos_con_pata': len({q['partido'] for q in visibles}),
        'conteo_color': conteo,
        'conteo_riesgo': {n: sum(1 for q in visibles
                                 if q.get('nivel_riesgo') == n)
                          for n in ('baja', 'media', 'alta', 'sin_medir')},
        'solo_riesgo_bajo': bool(solo_riesgo_bajo and not riesgo_apagado),
        'riesgo_apagado': riesgo_apagado,
        'garantizar': int(garantizar or 0),
        'relajado': relajado,
        'alcanza_garantia': (not garantizar
                             or len({q['partido'] for q in visibles})
                             >= garantizar),
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


def topes_efectivos(patas: List[Dict], n: int) -> Dict:
    """Los topes que de verdad se pueden aplicar para armar `n` patas.

    POR QUE UN TOPE SE PUEDE LEVANTAR, Y POR QUE ESO NO ES HACER TRAMPA. Un
    tope de «maximo 2 por mercado» pone un techo duro al parlay: 2 x (numero
    de mercados distintos). Medido en el backtest, con los tres mercados que
    el historico cubre, ese tope deja el parlay de 8 patas en CERO parlays
    armados — no en peores, en ninguno. Y el tope de «maximo 3 por deporte»
    haria imposible cualquier parlay de mas de tres patas de futbol, que es la
    configuracion por defecto de la pantalla.

    Asi que cuando un tope hace inalcanzable el numero de patas PEDIDO, se
    levanta ese tope y se dice cual. La alternativa es una pantalla que no
    arma nada y no explica por que, que es justo el fallo que el rediseño de
    la Soñadora vino a quitar.
    """
    n = max(1, int(n or 0))
    campos = (('liga', 'liga', MAX_POR_LIGA),
              ('mercado', 'categoria', MAX_POR_MERCADO),
              ('deporte', 'deporte', MAX_POR_DEPORTE))
    # EL TOPE POR DEPORTE SOLO EXISTE SI EL PARLAY ES MIXTO, y lo dice el
    # encargo con esas palabras. Con un solo deporte no es que el tope se
    # levante —es que no aplica—: la configuracion por defecto de la pantalla
    # es «solo futbol», asi que tratarlo como levantado ponia el aviso «hubo
    # que levantar el tope por deporte» en TODOS los parlays normales, y un
    # aviso que sale siempre no avisa de nada.
    mixto = len({q.get('deporte') or '' for q in patas}) > 1
    # LOS TRES LIMITES SE PUBLICAN SIEMPRE, con `None` cuando no se aplican.
    # Omitir una clave no es lo mismo que ponerla a `None`: `_elegir` cae en su
    # valor por defecto y acaba aplicando un tope que esta funcion habia
    # decidido no aplicar. Paso, y dejo la Soñadora sin armar ni un parlay.
    limites: Dict[str, Optional[int]] = {}
    levantados: List[str] = []
    for nombre, campo, tope in campos:
        if nombre == 'deporte' and not mixto:
            limites[nombre] = None          # no aplica; no es un levantamiento
            continue
        # una pata por PARTIDO, asi que el techo lo pone el numero de partidos
        # distintos que aporta cada grupo, no el numero de patas
        grupos: Dict[str, set] = {}
        for q in patas:
            grupos.setdefault(q.get(campo) or '', set()).add(q.get('partido'))
        techo = sum(min(len(v), tope) for v in grupos.values())
        if techo < n:
            limites[nombre] = None
            levantados.append(nombre)
        else:
            limites[nombre] = tope
    return {'limites': limites, 'levantados': levantados, 'mixto': mixto}


def _elegir(patas: List[Dict], n: int, clave,
            por_liga: bool = False, topes: bool = True,
            bloqueados: Optional[set] = None,
            limites: Optional[Dict] = None) -> List[Dict]:
    """Elige `n` patas sin repetir partido y respetando los topes.

    Dos patas del mismo encuentro están correlacionadas de forma brutal y la
    casa normalmente ni las deja combinar: el multiplicador que saldría no es
    el que se paga. Ésa es la regla vieja.

    LO QUE AÑADEN LOS TOPES (`MAX_POR_LIGA`, `MAX_POR_MERCADO`,
    `MAX_POR_DEPORTE`) es cortar la falsa diversificación: cuatro patas de la
    misma jornada de la misma liga no son cuatro apuestas independientes. No
    suben el ROI —medido, 0,0 puntos, y la aritmética dice que no pueden— pero
    quitan el riesgo compartido, que es lo que hunde un boleto entero de
    golpe.

    `bloqueados` son los partidos que ya están en otro parlay vivo.
    """
    vistos_p, vistos_l, fuera = set(), set(), []
    por_liga_n: Dict[str, int] = {}
    por_mercado: Dict[str, int] = {}
    por_deporte: Dict[str, int] = {}
    bloqueados = bloqueados or set()
    lim = (limites or {}) if topes else {}
    t_liga = lim.get('liga', MAX_POR_LIGA if topes else None)
    t_merc = lim.get('mercado', MAX_POR_MERCADO if topes else None)
    t_dep = lim.get('deporte', MAX_POR_DEPORTE if topes else None)
    for q in sorted(patas, key=clave):
        if q['partido'] in vistos_p or q['partido'] in bloqueados:
            continue
        if por_liga and q['liga'] in vistos_l:
            continue
        lg, mc, dp = q.get('liga') or '', q.get('categoria') or '', \
            q.get('deporte') or ''
        if topes:
            if t_liga is not None and por_liga_n.get(lg, 0) >= t_liga:
                continue
            if t_merc is not None and por_mercado.get(mc, 0) >= t_merc:
                continue
            if t_dep is not None and por_deporte.get(dp, 0) >= t_dep:
                continue
        vistos_p.add(q['partido'])
        vistos_l.add(q['liga'])
        por_liga_n[lg] = por_liga_n.get(lg, 0) + 1
        por_mercado[mc] = por_mercado.get(mc, 0) + 1
        por_deporte[dp] = por_deporte.get(dp, 0) + 1
        fuera.append(q)
        if len(fuera) >= n:
            break
    return fuera


def parlays_activos(ruta: str = ACTIVOS) -> List[Dict]:
    """Los parlays que el usuario dio por vivos. Lista vacía si no hay fichero."""
    try:
        with open(ruta, encoding='utf-8') as f:
            d = json.load(f) or {}
        return list(d.get('parlays') or [])
    except Exception:
        return []


def partidos_comprometidos(ruta: str = ACTIVOS,
                           dia: Optional[str] = None) -> set:
    """Partidos que ya están en un parlay vivo, y por tanto no se repiten.

    EL CASO QUE LO MOTIVA lo trajo el usuario: Boyacá Chicó apareció en dos
    parlays a la vez. Eso no es diversificar —es doblar la apuesta al mismo
    resultado mientras la pantalla dice que son dos boletos distintos.

    Sólo cuentan los del MISMO día: un parlay de la semana pasada ya se
    resolvió y no compromete nada.
    """
    fuera = set()
    for p in parlays_activos(ruta):
        if dia and str(p.get('dia')) != str(dia):
            continue
        for q in (p.get('partidos') or []):
            fuera.add(str(q))
    return fuera


def registrar_parlay(parlay: Dict, dia: str, ruta: str = ACTIVOS) -> Dict:
    """Apunta un parlay como vivo. Devuelve el registro entero.

    No se llama solo: lo dispara el usuario desde la pantalla cuando da un
    boleto por jugado. Apuntar automáticamente cada parlay que se propone
    bloquearía el catálogo entero a la primera permutación que se mire.
    """
    doc = {'parlays': parlays_activos(ruta)}
    doc['parlays'].append({
        'dia': str(dia),
        'registrado': _dt.datetime.now().isoformat(timespec='seconds'),
        'n_patas': int(parlay.get('n_patas') or 0),
        'multiplicador': parlay.get('multiplicador'),
        'letra': parlay.get('letra') or '',
        'partidos': sorted({str(q.get('partido'))
                            for q in (parlay.get('patas') or [])}),
        'patas': [q.get('id') for q in (parlay.get('patas') or [])],
    })
    with open(ruta, 'w', encoding='utf-8') as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    return doc


def olvidar_parlays(ruta: str = ACTIVOS) -> None:
    """Vacía el registro. Lo usa la pantalla y lo usan los tests."""
    with open(ruta, 'w', encoding='utf-8') as f:
        json.dump({'parlays': []}, f, ensure_ascii=False, indent=1)


def permutaciones(patas: List[Dict], n_patas: int,
                  bloqueados: Optional[set] = None) -> List[Dict]:
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

    bloqueados = bloqueados or set()

    # LAS ROJAS NO ENTRAN EN UNA COMBINADA AUTOMATICA, aunque el usuario las
    # haya hecho visibles con la casilla. Verlas es una cosa —puede quererlas
    # para armar la suya a mano— y que la pantalla se las PROPONGA metidas en
    # un parlay es otra.
    #
    # Con el respaldo de siempre: si sin rojas no se llega a `n` patas, se usan
    # todas y se dice. La alternativa es no proponer nada los dias flojos, que
    # es el fallo que el rediseño de la Soñadora vino a quitar.
    #
    # OJO CON LA OTRA BANDERA ROJA. La de `alpha_finder.etiqueta_fiabilidad`
    # —el Brier de los picks publicados— dispara en 70 de las 77 competiciones
    # medidas, porque el Brier de un binario cerca del 50 % vale ~0,25 por
    # construccion. Bloquear por esa habria vaciado el generador entero. La que
    # se usa aqui es el color del semaforo de la pata, que si reparte.
    sin_rojas = [q for q in patas if q.get('color') != ROJO]
    rojas_forzadas = len(
        {q['partido'] for q in sin_rojas if q['partido'] not in bloqueados}) < n
    fuente = patas if rojas_forzadas else sin_rojas

    tp = topes_efectivos([q for q in fuente
                          if q['partido'] not in bloqueados], n)
    lim = tp['limites']
    patas = fuente

    def _el(fuente, k, clave, por_liga=False):
        return _elegir(fuente, k, clave, por_liga=por_liga,
                       bloqueados=bloqueados, limites=lim)

    mitad = n // 2
    seguras = _el(patas, mitad, _por_color(lambda q: -q['prob']))
    usados = {q['partido'] for q in seguras}
    altas = _el([q for q in patas if q['partido'] not in usados],
                n - mitad, lambda q: -q['cuota'])
    # LA MIXTA SE ARMA EN DOS TANDAS, y cada tanda cuenta sus topes por
    # separado: sin esta pasada final, dos patas de una liga en la mitad segura
    # y dos mas en la de cuota alta dan cuatro de la misma liga respetando el
    # tope «dos veces». Se vuelve a filtrar el resultado conservando el orden.
    _orden = {id(q): i for i, q in enumerate(seguras + altas)}
    mixta = _el(seguras + altas, n, lambda q: _orden.get(id(q), 99))
    candidatas = {
        'A': _el(patas, n, _por_color(lambda q: -q['prob'])),
        'B': _el(patas, n, lambda q: -q['cuota']),
        'C': _el(patas, n, _por_color(lambda q: -q['score'])),
        'D': _el(patas, n, _por_color(lambda q: -q['score']), por_liga=True),
        'E': mixta,
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
                  'descripcion': descripcion,
                  'topes_levantados': list(tp['levantados']),
                  'rojas_forzadas': rojas_forzadas})
        fuera.append(p)
    return fuera


def escalera_de_parlays(patas: List[Dict],
                        tamanos=TAMANOS_ESCALERA,
                        bloqueados: Optional[set] = None) -> List[Dict]:
    """Todas las combinadas que salen del mismo montón, por tamaño.

    El usuario pidió «todas las permutaciones posibles con las diferentes
    cantidades de patas». Esto devuelve, para cada tamaño que quepa, las cinco
    recetas de `permutaciones` — y no las que no quepan.

    POR QUÉ NO SE DEVUELVEN TODAS LAS COMBINACIONES DE VERDAD. Con 18 patas y
    13 huecos son 8.568 boletos, y con 40 patas y 8 huecos son 76 millones:
    una lista así no se lee, no se elige de ella y tarda. Las cinco recetas
    cubren los extremos que importan —la más probable, la de mayor
    multiplicador, la de mejor Score, la más repartida y la mixta— y cada una
    es la ÓPTIMA de su criterio, que es lo que uno buscaría a mano en esos
    ocho mil.
    """
    fuera = []
    partidos = len({q['partido'] for q in (patas or [])
                    if q['partido'] not in (bloqueados or set())})
    for n in sorted(set(int(t) for t in (tamanos or ()))):
        if n < 2 or n > partidos:
            continue
        for p in permutaciones(patas, n, bloqueados=bloqueados):
            p['n_pedidas'] = n
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
        'conteo_riesgo': {n: sum(1 for q in patas
                                 if q.get('nivel_riesgo') == n)
                          for n in ('baja', 'media', 'alta', 'sin_medir')},
        'exposicion': _exposicion(patas),
        'dias': sorted({str(q.get('dia')) for q in patas if q.get('dia')}),
    })
    return base


def _exposicion(patas: List[Dict]) -> Dict:
    """Cuánto se repite el parlay en liga, mercado y deporte.

    Es lo que convierte «ocho patas» en «ocho patas que son en realidad tres
    apuestas»: la falsa diversificación que el usuario trajo de sus boletos
    perdidos. Se publica el máximo de cada eje y si respeta el tope.
    """
    def _max(campo):
        cuenta: Dict[str, int] = {}
        for q in patas:
            k = q.get(campo) or ''
            cuenta[k] = cuenta.get(k, 0) + 1
        if not cuenta:
            return 0, ''
        k = max(cuenta, key=lambda x: cuenta[x])
        return cuenta[k], k

    n_liga, liga = _max('liga')
    n_merc, merc = _max('categoria')
    n_dep, dep = _max('deporte')
    # el tope por deporte solo cuenta en un parlay MIXTO, igual que en
    # `topes_efectivos`: con un solo deporte no aplica
    mixto = len({q.get('deporte') or '' for q in patas}) > 1
    return {
        'max_por_liga': n_liga, 'liga_mas_repetida': liga,
        'max_por_mercado': n_merc, 'mercado_mas_repetido': merc,
        'max_por_deporte': n_dep, 'deporte_mas_repetido': dep,
        'mixto': mixto,
        'respeta_topes': (n_liga <= MAX_POR_LIGA
                          and n_merc <= MAX_POR_MERCADO
                          and (not mixto or n_dep <= MAX_POR_DEPORTE)),
    }


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
