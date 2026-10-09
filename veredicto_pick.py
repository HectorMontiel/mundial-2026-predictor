#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v218 — METER o NO METER: un veredicto visual, sin párrafos que leer.

LA PETICIÓN
-----------
«Que la app entienda: ésta tiene un 80 % pero no se puede dar por esto; o al
revés, ésta tiene 60 % y sí es probable porque el otro equipo viene de mala
racha. Que fácilmente se vea cuáles sí debo meter y cuáles no, y que se
identifique VISUALMENTE, porque hay mucho texto.»

LO QUE HACE QUE ESTO NO SEA UN ADORNO
--------------------------------------
Un 55 % no vale lo mismo en todos los mercados, y está MEDIDO sobre los picks
que esta aplicación publicó y se resolvieron:

    Goles              50-60 %   dijo 55,3 %   acertó 47,0 %   ← engaña
    Doble oportunidad  50-60 %   dijo 55,3 %   acertó 63,0 %   ← vale más

Ocho puntos de diferencia entre dos picks que la pantalla enseñaba idénticos.
Eso es lo que corrige este módulo: la probabilidad que se enseña deja de ser la
del modelo y pasa a ser **la del modelo corregida por lo que ese mercado y esa
banda han acertado de verdad**.

LA SEPARACIÓN QUE LO MANTIENE HONESTO
-------------------------------------
Hay dos cosas distintas y se pintan distinto:

    LO MEDIDO      la corrección por fiabilidad. Tiene muestra, tiene
                   intervalo, y es lo único que mueve el veredicto.
    EL CONTEXTO    bajas, racha, entrenador nuevo. Se ENSEÑA con su flecha
                   —es lo que el usuario pidió ver— pero NO decide, porque
                   ninguna de esas reglas está medida contra ROI todavía
                   (ver `archivo_contexto`, que existe para poder medirlas).

Si el contexto decidiera, esto sería otra capa de intuición con pinta de dato.
Enseñarlo al lado del veredicto y dejar claro cuál manda es la diferencia.

EL VEREDICTO ES BINARIO, A PROPÓSITO
------------------------------------
«Es sí o no.» Un tercer estado invita a apostar lo dudoso. Lo que sí hay es
FUERZA: cuánto margen le sobra al sí, o cuánto le falta al no.
"""

import logging
import re
from typing import Dict, List, Optional

logger = logging.getLogger('veredicto_pick')

METER, NO_METER = 'meter', 'no_meter'

# El listón, que es una decisión de producto y no una medición: por debajo de
# aquí no compensa meterla en una combinada de varias patas, porque el
# producto de probabilidades se desploma. Con cuatro patas al 65 % el boleto
# entero está al 17,9 %.
UMBRAL_METER = 0.65

# v310 — Y UNA CUOTA QUE MEREZCA LA PENA, EN FÚTBOL.
#
# El usuario: «tiene que haber una probabilidad alta, pero no abras tanto
# los rangos; la cosa es tener buenas cuotas». Simulado sobre los ledgers
# fuera de muestra con cuota (`_v310_simulacion.py`, 1X2 y más/menos 2,5,
# probabilidad calibrada contra la casa; elección / juicio):
#
#     p ≥ 65 % y cuota ≥ 1,20   prometido 70,9/70,8 %   real 72,0/71,6 %
#                               cuota media 1,38        ROI −1,1 / −2,4 %
#     p ≥ 65 % y cuota ≥ 1,40   prometido 67,4/67,1 %   real 69,5/67,6 %
#                               cuota media 1,45        ROI +0,4 / −2,7 %
#
# Las dos cumplen lo que prometen CON CUOTAS DE CIERRE. Pero la prueba que
# manda es la de las apuestas que da la tarjeta con los precios de Playdoit
# (`_v310_replay_semana.py`, 276 partidos de la última semana, cada uno con
# la última foto previa a su inicio):
#
#     meter ≥ 65 %                 709 apuestas  prometido 73,6  real 71,4
#                                  cuota 1,32    ROI −6,5 %
#     meter ≥ 65 % y cuota ≥ 1,40  165 apuestas  prometido 70,0  real 63,6
#                                  cuota 1,47    ROI −6,7 %
#
# RECHAZADA. En Playdoit, un «65 % o más» que paga 1,40 o más es justo el caso
# en que el modelo dice más que la casa, y ahí es donde falla (ya se había
# visto en el registro de apuestas: dijo 68 % con la casa en 65 % y pasó el
# 61 %). No paga más y cumple peor. Queda desactivada (None) y documentada
# para que no se vuelva a proponer sin datos nuevos.
CUOTA_METER_FUTBOL = None

# v310 — LOS CONTEOS NO SE CORRIGEN POR BANDA.
#
# `correccion` (abajo) trae la curva por banda de cuota que se midió sobre
# 1X2 y goles, y se aplicaba a todo. En córners, tarjetas y remates SUBÍA la
# probabilidad hasta 10 puntos. En la semana reproducida (apuestas «meter»):
#
#                        modelo  corregida  real     n
#     Tarjetas            66,8     71,4     62,0    50
#     Remates a puerta    69,1     72,4     69,1    81
#     Córners             75,2     73,5     74,6   134
#
# Y fuera de muestra, con años de partidos (`_v310_conteos.py`), estos modelos
# ya salen calibrados solos (ECE ≤ 0,03 en Liga MX, selecciones y UEFA). En
# tarjetas y remates la corrección los empujaba a «meter» cuando no tocaba
# (Monterrey–Cruz Azul, «Más de 3,5 tarjetas»: 58 % → 68 %).
#
# Los CÓRNERS se quedan con la corrección: ahí BAJA la cifra y acierta. Probado
# quitándosela también: 119 apuestas, prometido 76,9 %, real 73,9 %; con ella,
# 134, prometido 73,5 %, real 74,6 %.
MERCADOS_SIN_CORRECCION = ('Tarjetas', 'Remates', 'Remates a puerta')

# v312 — LO QUE SE DICE «METER» EN FÚTBOL, DONDE SALEN MENOS ROJOS.
#
# El usuario: «lo que quiero evitar es tener muchos rojos; que me muestre más
# verdes… las validaciones las harás con simulaciones de los partidos de hoy».
# `_v312_patrones.py` reprodujo las 2.017 apuestas candidatas de 425
# partidos (20-28 sep, última foto previa a cada partido, precios de
# Playdoit, históricos recortados) y las liquidó. Los patrones de los rojos,
# sacados SÓLO con los días 20-26:
#
#     «Doble y goles»            prometía 77,7 %  → pasó 70,3 %  (111)
#     probabilidad 80-85 %       prometía 81,8 %  → pasó 67,0 %  ( 97)
#     probabilidad 65-70 %       prometía 67,7 %  → pasó 63,4 %  (194)
#     cuota ≥ 1,35               prometía 70,5 %  → pasó 64,8 %  (230)
#     remates a puerta           ~72 %            → pasó 62 %    ( 77)
#     hándicap                   71 %             → pasó 25 %    (  8)
#
# La regla que los quita (meter = 70-80 %, cuota < 1,35, sin esos mercados),
# frente a la de antes, con el acierto de lo que se dice «meter»:
#
#                      antes                 ahora
#     20-26 (elige)    71,7 % (895)          75,7 % (465)
#     27-28 (juzga)    73,1 % (227)          80,2 % (101)   ROI −4,9 → +0,7 %
#     hoy 28           72,3 % ( 83)          75,6 % ( 41)
#
# Bootstrap por partido de la mejora: +4,0 pts (p5 +2,0) al elegir y +7,0
# (p5 +2,4) al juzgar. Menos apuestas —1,6 por partido en vez de 2,9— y
# más verdes, que es lo que se pidió. Sólo fútbol: es lo medido.
METER_FUTBOL_MIN = 0.70
METER_FUTBOL_MAX = 0.80
CUOTA_METER_FUTBOL_MAX = 1.35
MERCADOS_NO_METER_FUTBOL = ('Doble y goles', 'Remates', 'Remates a puerta',
                            'Handicap')


def franja_futbol(v: Dict) -> Optional[str]:
    """v312 — `None` si un «meter» de FÚTBOL de la tarjeta está en la franja
    medida; si no, el motivo corto. Se aplica en `modo_modelo.recomendadas`
    (la tarjeta, el documento de Telegram y el archivo de finalizados), NO en
    `evaluar`: la Soñadora y las patas de combinada también usan el veredicto
    y allí esta regla no está medida (y su cuota mínima por pata, 1,30, casi
    no dejaría sitio bajo el tope de 1,35)."""
    # v345 — la regla de tiros, ya activada, decide sola (ver `evaluar`)
    if (v.get('pick') or {}).get('tiros_regla') and v.get('medido') \
            and v.get('veredicto') == METER:
        try:
            import tiros_seguimiento as _ts
            if _ts.activo():
                return None
        except Exception:
            pass
    pick = v.get('pick') or {}
    if str(pick.get('deporte') or 'Fútbol') != 'Fútbol':
        return None
    mercado = str(v.get('mercado') or pick.get('mercado') or '')
    if mercado in MERCADOS_NO_METER_FUTBOL:
        return '«%s» falla más de lo que promete' % mercado
    if mercado == 'Goles' and _LINEA_25.search(
            str(v.get('apuesta') or pick.get('apuesta') or '')):
        return 'la línea 2,5 de goles acierta menos de lo que promete'
    p = _f(v.get('prob_ajustada'))
    c = _f(v.get('cuota') if v.get('cuota') is not None else pick.get('cuota'))
    if mercado in MERCADOS_CON_PRECIO:
        # v335 — donde la casa cotiza, decide su precio (ver abajo)
        pm = _f(v.get('p_mercado') if v.get('p_mercado') is not None
                else pick.get('p_mercado'))
        if pm is None or c is None:
            return 'sin precio de la casa para comprobarla'
        if p is None or p < METER_CASA_MODELO_MIN:
            return 'el modelo no llega al %.0f %%' % (100 * METER_CASA_MODELO_MIN)
        if pm < METER_CASA_MIN:
            return 'la casa la ve al %.0f %%: por debajo del %.0f %%' % (
                100 * pm, 100 * METER_CASA_MIN)
        if c < METER_CASA_CUOTA_MIN:
            return 'cuota %.2f: por debajo de %.2f paga muy poco' % (
                c, METER_CASA_CUOTA_MIN)
        if c >= CUOTA_METER_FUTBOL_MAX:
            return 'cuota %.2f: a partir de %.2f salen más rojos' % (
                c, CUOTA_METER_FUTBOL_MAX)
        return None
    if p is None or not (METER_FUTBOL_MIN <= p <= METER_FUTBOL_MAX):
        return 'fuera de la franja 70-80 %, donde se cumple lo prometido'
    if c is not None and c >= CUOTA_METER_FUTBOL_MAX:
        return 'cuota %.2f: a partir de %.2f salen más rojos' % (
            c, CUOTA_METER_FUTBOL_MAX)
    return None


# v335 — DONDE LA CASA COTIZA, «METER» LO DECIDE SU PRECIO, NO SÓLO EL MODELO.
#
# El usuario: «no entiendo cómo es que mejora pero no nos da más verdes»;
# después eligió «ambas» (esta es la A). La v334 (`_v334_avanzado.py`) midió
# que, a IGUAL número de apuestas, la probabilidad de la casa sin margen
# elige mejores partidos que el modelo (+1,5 a +2,4 pts, p5 > 0) y que un
# apilado le da peso ≈ 1 al precio y ≈ 0 al modelo. El modelo no sabe nada que
# el precio no sepa; donde hay precio, el precio manda.
#
# LA REGLA, elegida con los días de mirar de la simulación de la tarjeta
# (`_v335_meter_casa.py`: la que más verdes da manteniendo el volumen de hoy
# ±5 % y la cuota media ≥ 1,20, lo acordado con el usuario): casa sin margen
# ≥ 74 %, modelo ≥ 70 % (las dos de acuerdo) y cuota entre 1,15 y 1,35. Si la
# casa no da precio de ESA apuesta, no se mete: no hay con qué comprobarla.
#
#                         ANTES                       DESPUÉS
#   simulación, mirar     78,7 % · 611 · 130 rojos    81,4 % · 581 · 108 rojos
#   (Playdoit, 20-30 sep) cuota 1,246 · −2,1 %        cuota 1,213 · −1,4 %
#   simulación, juzgar    76,2 % · 344 ·  82 rojos    78,5 % · 340 ·  73 rojos
#   (1-6 oct)             cuota 1,238 · −5,7 %        cuota 1,214 · −4,9 %
#   histórico, juzgar     77,3 % · 2.119 rojos        79,0 % · 1.407 rojos
#   (2024-08 a 2026-10)   cuota 1,228 · −5,3 %        cuota 1,204 · −5,0 %
#
# Histórico: +1,63 pts con p5 +0,92 en 664 días, mejor en las dos mitades y
# en 8 de 9 años (2021 igual). En la simulación el p5 de los 6 días de juicio
# es −1,00: pocos días, no peor. LO QUE CUESTA: la cuota media baja de ~1,24 a
# ~1,21; el rendimiento por peso queda igual o un poco mejor. Córners y
# tarjetas, sin precio, siguen con la franja 70-80 % del modelo.
MERCADOS_CON_PRECIO = ('Goles', 'Goles equipo', '1X2', 'Doble oportunidad', 'BTTS')
METER_CASA_MIN = 0.74
METER_CASA_MODELO_MIN = 0.70
METER_CASA_CUOTA_MIN = 1.15


# v331 — LA LÍNEA 2,5 DEL TOTAL DE GOLES NO SE «METE».
#
# El usuario: «quiero que analices los patrones de las rojas… haz hipótesis,
# método científico y simulaciones; tiene que haber algo mejor, sin bajar las
# cuotas a 1,20». Se probaron diez hipótesis (`_v331_hipotesis.py`) contra el
# control «quitar el mismo número de apuestas de menor probabilidad» —que es
# subir el mínimo, lo fácil—: volatilidad, sesgo del modelo con el equipo,
# inicio de temporada, descanso, Pinnacle, casa contra Pinnacle, corrector de
# λ, calibración reciente de la liga, favorito, empate. NINGUNA gana sola, y
# todas juntas en un LightGBM ganan 0,0-0,5 pts según el año: el modelo ya
# lleva dentro lo que dicen los equipos. Tampoco avisa un rojo del equipo
# (tras rojo 73,7 % vs tras verde 74,0 %, 62 mil apuestas de goles).
#
# Lo que SÍ aparece, mirando lo prometido contra lo acertado por tipo de
# apuesta en la franja 70-80 % (`_v331_linea_25.py`):
#
#                        prometía   acertó
#   histórico Más de 2,5    72 %     66 %    (344; mirar y juzgar iguales)
#   histórico Menos de 2,5  73 %     68-70 % (1.736)
#   histórico 2,5 por año   73 %     66 / 68 / 68 / 69 %  (2023 a 2026)
#   reales de la app        73 %     61 %    (18 «meter», 26-sep a 6-oct)
#   simulación tarjeta      72 %     71 %    (21, frente a 78 % del resto)
#   Más de 1,5 / Menos 3,5  75 / 74  75 / 74 (cumplen)
#
# Quitarla, con la regla de hoy ya aplicada: histórico juzgar 74,2 → 74,5 %
# (p5 +0,19; frente al control +0,18, p5 +0,07); reales 75,4 → 76,0 % al
# mirar y 74,8 → 75,0 % al juzgar. Simulación de la tarjeta REHECHA con este
# código (`_v324_nada.py --rehacer`, 765 partidos, 20-sep a 6-oct, la tarjeta
# sube otra apuesta cuando quita la 2,5): mirar 78,4 → 78,7 %, juzgar 76,2 →
# 76,2 %, total 77,6 % (982, 220 rojos) → 77,8 % (955, 212 rojos). Salen 31
# que acertaban 71,0 %; entran 4 que aciertan 75 %.
# Es poco —son el 2-3 % de las «meter»— pero es lo único de las once
# hipótesis que cumple las tres pruebas. Sólo el TOTAL de goles: los goles
# por equipo a 2,5 no están medidos.
_LINEA_25 = re.compile(r'(Más|Menos) de 2\.5$')

# v342 — EL TENIS SE DECIDE CON EL PRECIO DE LA CASA, SIN LA CURVA DEL FÚTBOL.
#
# El usuario mandó cinco «Ganador» de tenis perdidos a 1,38-1,45 y pidió
# calibrar mejor el tenis. Lo que pasaba: al tenis se le aplicaba
# `correccion`, y su curva por banda de cuota (`calibrador_bandas`, 21.779
# picks) está medida en el FÚTBOL. En 1,40-1,50 sube el número hasta 9 puntos:
# un 65 % de la app salía como 72 % y pasaba a «meter».
#
# Medido en `_v342_tenis.py` sobre el ledger de tenis (ATP y WTA 2019-2026,
# fuera de muestra, cuota de cierre; el «modelo» es el de la app, que ya va
# encogido hacia la casa con w=0,25), elegido con el 70 % viejo y juzgado
# en el 30 % reciente (desde 2025-02-09):
#
#   en 1,35-1,50 (4.287)     promete   acierta
#     modelo + curva fútbol   72,5 %    68,4 %   ← lo de hoy: sobrado
#     modelo de la app        67,3 %    68,4 %
#     casa sin margen         67,5 %    68,4 %   y el pago pide 71 %
#
#                              elige               juzga
#     hoy (curva, ≥65 %)     10.303  77,4 %   4.476  76,9 %  ROI −3,3 %
#     casa ≥70 y modelo ≥70   6.963  81,9 %   2.989  80,8 %  ROI −3,4 %
#
# Elegida entre 15 combinaciones casa/modelo con el criterio fijado antes de
# mirar el juicio (mejor ROI con al menos la mitad de apuestas). Bootstrap
# por día de la mejora del acierto al juzgar: +3,9 pts, p5 +3,2. Rojos 1.034
# → 574. El ROI no cambia: el tenis no le gana al cierre con ninguna regla.
#
# Y con las apuestas REALES de la app, la tarjeta rehecha con este código
# (`_v342_tenis_tarjeta.py`, 4-7 oct, 461 «meter» liquidadas, ya con los
# resultados de Flashscore —antes de la v342 más de la mitad del tenis no se
# liquidaba—): hoy 352 verdes y 109 rojas (76,4 %, ROI −5,7 %); con la regla
# 259 y 59 (81,5 %, ROI −4,6 %). Las 143 que quita acertaban el 65,0 % a
# cuota media 1,41. Bootstrap por partido (442): +5,1 pts, p5 +2,8.
#
# El número que se enseña es el de la casa (`concordancia.PESO_MODELO_TENIS`).
# Sin precio de la casa no se mete: lo medido es la casa.
METER_TENIS_CASA_MIN = 0.70
METER_TENIS_MODELO_MIN = 0.70


def tenis_mete(prob_modelo, prob_casa) -> bool:
    """La regla medida del «Gana X» de tenis (v342). `False` si falta algo."""
    pm, pc = _f(prob_modelo), _f(prob_casa)
    return (pm is not None and pc is not None
            and pm >= METER_TENIS_MODELO_MIN and pc >= METER_TENIS_CASA_MIN)

# Cuánto puede corregir la fiabilidad medida. Topado porque una banda con
# muestra corta puede tener una brecha grande por azar, y sin tope esa brecha
# se convertiría en una corrección enorme.
CORRECCION_MAXIMA = 0.10

# Señales de contexto: se enseñan, no deciden. El signo es el que entiende
# `ajuste_contexto.PESOS`.
_A_FAVOR = ('regreso_clave', 'racha_positiva', 'invicto_local',
            'h2h_favorable', 'descanso_extra')
_EN_CONTRA = ('lesion_clave', 'lesion_multiple', 'baja_defensiva',
              'entrenador_nuevo_rival', 'racha_negativa', 'fatiga')

_ETIQUETA = {
    'lesion_clave': 'baja importante', 'lesion_multiple': 'varias bajas',
    'baja_defensiva': 'baja en defensa', 'entrenador_nuevo_rival': 'rival con técnico nuevo',
    'racha_negativa': 'mala racha', 'fatiga': 'poco descanso',
    'regreso_clave': 'vuelve un titular', 'racha_positiva': 'en racha',
    'invicto_local': 'invicto en casa', 'h2h_favorable': 'historial a favor',
    'descanso_extra': 'más descanso',
}


def _f(x) -> Optional[float]:
    try:
        return None if x is None else float(x)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
def correccion(prob: Optional[float], mercado: str = '',
               cuota: Optional[float] = None) -> Dict:
    """Cuánto hay que mover ese porcentaje según lo que ha acertado de verdad.

    Devuelve la brecha medida (acierto real − prometido) topada, y de dónde
    sale. Si no hay muestra, la corrección es CERO y se dice: no medir no es
    lo mismo que medir cero, pero corregir sin medir es peor que no corregir.
    """
    p = _f(prob)
    vacio = {'delta': 0.0, 'medido': False, 'n': 0, 'fuente': '',
             'veredicto_banda': 'sin_medir'}
    if p is None:
        return vacio
    if str(mercado or '') in MERCADOS_SIN_CORRECCION:
        # v310 — ver MERCADOS_SIN_CORRECCION: calibrados solos, medido
        return dict(vacio, fuente='conteo_calibrado')
    try:
        import fiabilidad_picks as fp
        fi = fp.fiabilidad(p, str(mercado or ''))
    except Exception as e:
        logger.debug('[veredicto] fiabilidad: %s', e)
        return vacio
    # v224 — DOS MEDICIONES, Y SE USA LA QUE TIENE MÁS EVIDENCIA DETRÁS.
    #
    # Hay dos formas medidas de corregir el mismo número, y no siempre
    # coinciden:
    #
    #   `fiabilidad_picks`   por MERCADO y banda de probabilidad, sobre los
    #                        picks que esta app publicó. Muy pertinente, pero
    #                        con muestras pequeñas: `1X2|70-80 %` tiene n=31.
    #   `calibrador_bandas`  por BANDA DE CUOTA, isotónica walk-forward sobre
    #                        el ledger. `1,20-1,50` tiene n=24.282.
    #
    # El caso que lo destapó: «Gana Milan» a 1,25. El mercado lo ve al 80 %, el
    # modelo dice 72 %, y la medición por banda de cuota dice que ahí el
    # modelo se queda CORTO +4,5 puntos. Con sólo la corrección por mercado
    # (n=31, −2,4) el pick bajaba a 70 % y se pintaba rojo — se estaba
    # escondiendo un favorito claro por la medición más débil de las dos.
    #
    # Se elige por tamaño de muestra, que es lo único defendible cuando dos
    # mediciones honestas discrepan.
    # v225 — NO SE CORRIGE DOS VECES EL MISMO ERROR.
    #
    # Las dos correcciones de abajo se midieron sobre las probabilidades TAL Y
    # COMO SALÍAN DEL MODELO, sin calibrar. Si `calibrador_goles` está activo,
    # la escalera de goles ya llega arreglada en origen: aplicar encima la
    # corrección por fiabilidad —ajustada sobre los picks viejos, los que sí
    # iban descalibrados— empujaría el número una segunda vez en el mismo
    # sentido.
    #
    # Sólo afecta a los mercados de goles, que son los que el calibrador toca.
    # El 1X2, la doble oportunidad y el BTTS siguen corrigiéndose igual.
    try:
        import calibrador_goles as _cgol
        if (_cgol.USAR_CALIBRACION_GOLES
                and str(mercado or '').strip().lower().startswith('goles')):
            return {'delta': 0.0, 'medido': True, 'n': 0,
                    'veredicto_banda': 'de_fiar',
                    'real': p, 'prometido': p,
                    'fuente': 'la escalera de goles ya viene calibrada en '
                              'origen (calibrador_goles)'}
    except Exception as e:
        logger.debug('[veredicto] calibrador de goles: %s', e)

    cand = []
    if fi.get('veredicto') != 'sin_medir' and fi.get('real') is not None:
        cand.append({
            'delta': float(fi['real']) - float(fi['prometido']),
            'n': int(fi.get('n') or 0),
            'veredicto_banda': fi.get('veredicto', ''),
            'real': fi.get('real'), 'prometido': fi.get('prometido'),
            'fuente': f"{fi.get('n')} picks publicados de este mercado"})

    c = _f(cuota)
    if c is not None:
        try:
            import calibrador_bandas as cb
            banda = cb.nombre_banda(c)
            curva = ((cb.cargar().get('bandas') or {}).get(banda) or {})
            calibrada = cb.calibrar(p, c)
            if curva.get('n_train') and calibrada is not None:
                cand.append({
                    'delta': float(calibrada) - p,
                    'n': int(curva['n_train']),
                    'veredicto_banda': ('conservador' if calibrada > p
                                        else 'optimista' if calibrada < p
                                        else 'de_fiar'),
                    'real': calibrada, 'prometido': p,
                    'fuente': f"{curva['n_train']:,} picks en la banda de "
                              f"cuota {banda}".replace(',', '.')})
        except Exception as e:
            logger.debug('[veredicto] calibrador de bandas: %s', e)

    if not cand:
        return vacio
    mejor = max(cand, key=lambda x: x['n'])
    delta = max(-CORRECCION_MAXIMA, min(CORRECCION_MAXIMA, mejor['delta']))
    return {'delta': round(delta, 4), 'medido': True, 'n': mejor['n'],
            'veredicto_banda': mejor['veredicto_banda'],
            'real': mejor['real'], 'prometido': mejor['prometido'],
            'fuente': mejor['fuente']}


def senales_visibles(pick: Dict, con_contexto: bool = False) -> List[Dict]:
    """Las señales de contexto, con su signo. Se ENSEÑAN, no deciden.

    `con_contexto=False` por defecto: consultar bajas sale a la red y esto se
    llama una vez por tarjeta. La vista de un partido concreto sí lo pide.
    """
    if not con_contexto:
        return []
    try:
        import scraper_contexto as sc
        p = pick or {}
        partido = str(p.get('partido') or '')
        h, a = (partido.split(' vs ') + ['', ''])[:2]
        crudas = sc.senales({'clave_liga': p.get('clave_liga'),
                             'home': h.strip(), 'away': a.strip(),
                             'partido': partido,
                             'deporte': str(p.get('deporte') or 'futbol').lower(),
                             'fecha': p.get('fecha')})
    except Exception as e:
        logger.debug('[veredicto] señales: %s', e)
        return []

    fuera = []
    for s in crudas:
        tipo = str(s.get('tipo') or '')
        # `scraper_contexto` emite tipos genéricos; el detalle trae el matiz
        detalle = str(s.get('detalle') or '')
        signo = 0
        if tipo in _EN_CONTRA or 'baja' in detalle.lower() or 'lesión' in detalle.lower():
            signo = -1
        elif tipo in _A_FAVOR or 'ganó' in detalle.lower():
            signo = +1
        if signo == 0:
            continue
        fuera.append({'signo': signo,
                      'texto': _ETIQUETA.get(tipo, tipo.replace('_', ' ')),
                      'detalle': detalle[:90]})
    return fuera[:4]


# ---------------------------------------------------------------------------
def evaluar(pick: Dict, con_contexto: bool = False) -> Dict:
    """El veredicto: meter o no, con su fuerza y su porqué en una línea.

    Barato por defecto: sin `con_contexto` no toca red ni disco pesado, para
    poder llamarse una vez por tarjeta sin repetir lo de la v216.
    """
    p = dict(pick or {})
    prob = _f(p.get('prob'))
    mercado = str(p.get('mercado') or '')
    cuota = _f(p.get('cuota'))

    base = {'veredicto': NO_METER, 'fuerza': 0.0, 'prob_modelo': prob,
            'prob_ajustada': prob, 'correccion': 0.0, 'medido': False,
            'razones': [], 'senales': [], 'mercado': mercado}
    if prob is None:
        return {**base, 'razones': ['sin probabilidad']}
    # v317 — LO MEJOR DEL MODELO (`lo_mejor.py`) YA VIENE MEDIDO: modelo y
    # casa de acuerdo acierta ~85 % a cuota 1,10-1,20. No pasa por la franja
    # ni por la cuota mínima de las demás, que son las que dejaban esta
    # apuesta fuera.
    if p.get('elite'):
        return {**base, 'veredicto': METER, 'fuerza': 1.0, 'medido': True,
                'razones': [str(p.get('razon') or 'Capa 1: modelo y casa de acuerdo')]}
    # v345 — LOS TIROS POR EQUIPO SÓLO SE METEN CUANDO SU REGLA SE GANÓ EL
    # PUESTO: `tiros_seguimiento` la mide sola desde que quedó fijada y la
    # activa con p5 > 0 y 150 apuestas. Mientras no, «no meter» (como todos los
    # remates del fútbol, `MERCADOS_NO_METER_FUTBOL`).
    if p.get('tiros_regla'):
        try:
            import tiros_seguimiento as _ts
            if _ts.activo():
                return {**base, 'veredicto': METER, 'fuerza': 0.6, 'medido': True,
                        'razones': ['tiros: el modelo %.0f %% y la casa %.0f %% '
                                    '(regla medida en su seguimiento)'
                                    % (100 * float(p.get('p_mod_tiros') or prob),
                                       100 * float(p.get('p_casa_tiros') or 0))]}
        except Exception as e:
            logger.debug('[veredicto] tiros: %s', e)

    # v325 — LA NFL NO SE CORRIGE CON LAS BANDAS DEL FÚTBOL. Su «1X2» se llama
    # igual que el del fútbol y recibía la curva medida en el fútbol, que la
    # subía hasta 10 puntos (Colts el 2026-10-04: modelo 59,8 % → 69,8 % →
    # «meter»). En la NFL lo medido es la mezcla con la casa que se hace justo
    # debajo (`PESO_MODELO_NFL`), y esa sí cumple lo que promete.
    # v330 — y la NBA igual: decide la mezcla medida (`PESO_MODELO_NBA`).
    _dep = str(p.get('deporte') or '')
    es_nfl = _dep in ('NFL', 'NBA')
    # v342 — y el tenis tampoco: su curva era la del fútbol (ver
    # `METER_TENIS_CASA_MIN`)
    es_tenis = _dep == 'Tenis'
    if es_nfl or es_tenis:
        c = {'delta': 0.0, 'medido': False, 'veredicto_banda': None, 'n': 0}
    else:
        c = correccion(prob, mercado, cuota)
    ajustada = max(0.01, min(0.99, prob + c['delta']))

    # v243 — LA SEGUNDA OPINIÓN: LO QUE LA CASA DICE DE ESTA MISMA APUESTA.
    #
    # Va DESPUÉS de `correccion` a propósito, y no en su lugar. No es corregir
    # dos veces: `correccion` endereza el sesgo propio del modelo, y esto
    # promedia el resultado con una estimación INDEPENDIENTE del mismo suceso,
    # hecha por gente que se juega dinero.
    #
    # Medido sobre 47.948 partidos de `pick_ledger.csv` y 47.794 de
    # `pick_ledger_totales.csv`, la mezcla con el mercado baja el log-loss en
    # los cuatro mercados con p5 positivo y el 100 % de los remuestreos a
    # favor. Y por bandas separa muchísimo: en «Más de 2.5», banda 60-70 %,
    # los picks que concuerdan con la casa aciertan el 63,7 % (prometen 64,6)
    # y los que discrepan, el 49,7 %. La discrepancia no es ventaja: es error.
    #
    # El peso es 0,5 y NO el 0,0 que dicen los datos, porque el ledger guarda
    # cuotas de CIERRE y batir al cierre es casi imposible por construcción.
    # Todo el razonamiento y lo que se intentó para medirlo mejor está en
    # `concordancia.py`.
    conc = {'hay': False}
    try:
        import concordancia as _conc
        conc = _conc.evaluar(p, str(p.get('apuesta') or ''), mercado,
                             prob_modelo=ajustada)
        if conc.get('hay') and conc.get('p_mezcla') is not None:
            ajustada = float(conc['p_mezcla'])
    except Exception as e:
        logger.debug('[veredicto] concordancia: %s', e)

    razones = []
    if c['medido']:
        if c['veredicto_banda'] == 'optimista':
            razones.append(
                f"este {prob:.0%} en «{mercado}» históricamente acierta "
                f"{c['real']:.0%} ({c['n']} picks): va sobrado")
        elif c['veredicto_banda'] == 'conservador':
            razones.append(
                f"este {prob:.0%} en «{mercado}» históricamente acierta "
                f"{c['real']:.0%} ({c['n']} picks): se queda corto")
        else:
            razones.append(
                f"el {prob:.0%} se sostiene: {c['real']:.0%} real en "
                f"{c['n']} picks de este mercado")
    elif es_nfl and _dep == 'NBA':
        razones.append('en la NBA decide la casa con un 10 % del modelo '
                       '(medido en 19 temporadas)')
    elif es_nfl:
        razones.append('en la NFL decide el modelo junto con la casa '
                       '(medido en 27 temporadas)')
    elif es_tenis:
        razones.append('en el tenis decide el precio de la casa '
                       '(medido en 2019-2026)')
    else:
        razones.append('sin histórico de este mercado y banda todavía')

    # v243 — la segunda opinión va la PRIMERA de las razones cuando las dos
    # fuentes se separan, porque entonces es lo más importante que hay que
    # saber de ese número.
    if conc.get('hay') and conc.get('razon'):
        if (conc.get('brecha') or 0) > 0.03:
            razones.insert(0, conc['razon'])
        else:
            razones.append(conc['razon'])

    mete = ajustada >= UMBRAL_METER
    # v330 — la pretemporada de la NBA no se recomienda: no hay un solo
    # partido suyo en el histórico de cierres con el que medirla, y los
    # titulares juegan poco.
    if mete and _dep == 'NBA' and p.get('pretemporada'):
        mete = False
        razones.insert(0, 'pretemporada: no se mide ni se recomienda')
    # y sin el precio de la casa no se mete: lo medido es la MEZCLA, y el
    # modelo solo (0,6187 de log-loss contra 0,6027 de la casa) no basta
    if mete and _dep == 'NBA' and not conc.get('hay'):
        mete = False
        razones.insert(0, 'sin el precio de la casa para mezclar: no se recomienda')
    # v342 — el tenis, con su regla medida y no con el 65 % de las combinadas
    if es_tenis:
        _pc = conc.get('p_mercado') if conc.get('hay') else None
        mete = tenis_mete(prob, _pc)
        if _pc is None:
            razones.insert(0, 'sin el precio de la casa: no se recomienda')
        elif not mete:
            razones.insert(0, 'la casa lo ve al %.0f %% y el modelo al %.0f %%: '
                           'en el tenis se mete con las dos en el %.0f %% o más'
                           % (100 * _pc, 100 * prob, 100 * METER_TENIS_CASA_MIN))
    if not mete and c['medido'] and c['veredicto_banda'] != 'optimista':
        razones.append(f'queda por debajo del {UMBRAL_METER:.0%} que pide '
                       f'una pata de combinada')
    # v310 — la cuota mínima está MEDIDA Y RECHAZADA (CUOTA_METER_FUTBOL
    # es None); la comprobación se deja para poder volver a medirla
    if (mete and CUOTA_METER_FUTBOL and cuota is not None
            and cuota < CUOTA_METER_FUTBOL
            and str(p.get('deporte') or 'Fútbol') == 'Fútbol'):
        mete = False
        razones.append('cuota %.2f: por debajo de %.2f no compensa'
                       % (cuota, CUOTA_METER_FUTBOL))

    # La fuerza es cuánto margen sobra (o falta) respecto al listón, llevada
    # a 0-1 sobre una ventana de 20 puntos. No es una probabilidad: es cuánto
    # de claro está el sí o el no.
    fuerza = max(0.0, min(1.0, abs(ajustada - UMBRAL_METER) / 0.20))

    senales = senales_visibles(p, con_contexto)
    return {**base,
            'veredicto': METER if mete else NO_METER,
            'fuerza': round(fuerza, 3),
            'prob_ajustada': round(ajustada, 4),
            'correccion': c['delta'],
            'medido': c['medido'],
            'n_muestra': c.get('n', 0),
            'veredicto_banda': c['veredicto_banda'],
            'concordancia': conc,          # v243: para pintar y para auditar
            'cuota': cuota,
            'razones': razones[:2],
            'senales': senales}


def evaluar_lista(picks, con_contexto: bool = False) -> List[Dict]:
    """Ordena por lo que hay que meter primero. Nunca lanza."""
    fuera = []
    for p in list(picks or []):
        if not isinstance(p, dict):
            continue
        try:
            v = evaluar(p, con_contexto)
            fuera.append({**v, 'pick': p})
        except Exception as e:
            logger.debug('[veredicto] pick saltado: %s', e)
    fuera.sort(key=lambda v: (v['veredicto'] != METER, -v['prob_ajustada']))
    return fuera


# ---------------------------------------------------------------------------
# La parte visual: poco texto, mucho color
# ---------------------------------------------------------------------------
CSS = """
<style>
.vp{display:flex;align-items:center;gap:.6rem;margin:.15rem 0;
    padding:.28rem .6rem;border-radius:.5rem;
    background:color-mix(in srgb, var(--fondo,#111) 92%, transparent);
    border-left:4px solid var(--vp-c)}
.vp-ic{font-size:1.15rem;line-height:1}
.vp-ap{flex:1;min-width:0;font-size:.86rem;
       overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.vp-pb{position:relative;width:78px;height:7px;border-radius:4px;
       background:rgba(255,255,255,.12);overflow:hidden;flex:none}
.vp-pb>i{position:absolute;inset:0 auto 0 0;background:var(--vp-c)}
.vp-pb>u{position:absolute;top:-3px;bottom:-3px;width:2px;
         background:rgba(255,255,255,.55)}
.vp-n{font-variant-numeric:tabular-nums;font-weight:600;font-size:.86rem;
      color:var(--vp-c);min-width:3.1rem;text-align:right;flex:none}
.vp-d{font-size:.7rem;opacity:.72;min-width:3.2rem;text-align:right;flex:none}
.vp-s{display:flex;gap:.25rem;flex:none}
.vp-s span{font-size:.72rem;padding:.05rem .32rem;border-radius:.3rem;
           background:rgba(255,255,255,.08);white-space:nowrap}
.vp-up{color:var(--ok,#3ddc84)} .vp-dn{color:var(--no,#ff5c5c)}
</style>
"""


def html(v: Dict, etiqueta: str = '') -> str:
    """Una fila visual: icono, apuesta, barra con el listón, % y señales.

    El LISTÓN dibujado dentro de la barra es lo que hace la fila legible de un
    vistazo: no hay que comparar números contra un umbral que el usuario tiene
    que recordar — se ve si la barra lo pasa o no.
    """
    color = 'var(--ok,#3ddc84)' if v.get('veredicto') == METER \
        else 'var(--no,#ff5c5c)'
    icono = '🟢' if v.get('veredicto') == METER else '🔴'
    p = float(v.get('prob_ajustada') or 0.0)
    d = float(v.get('correccion') or 0.0)

    chips = []
    for s in (v.get('senales') or [])[:3]:
        clase = 'vp-up' if s['signo'] > 0 else 'vp-dn'
        flecha = '▲' if s['signo'] > 0 else '▼'
        chips.append('<span class="%s" title="%s">%s %s</span>'
                     % (clase, _esc(s.get('detalle', '')), flecha,
                        _esc(s['texto'])))

    delta = ''
    if v.get('medido') and abs(d) >= 0.005:
        delta = '<span class="vp-d">%s%.0f pp</span>' % (
            '+' if d > 0 else '−', abs(d) * 100)

    return (
        '<div class="vp" style="--vp-c:%s">'
        '<span class="vp-ic">%s</span>'
        '<span class="vp-ap">%s</span>'
        '<span class="vp-s">%s</span>'
        '%s'
        '<span class="vp-pb"><i style="width:%.0f%%"></i>'
        '<u style="left:%.0f%%"></u></span>'
        '<span class="vp-n">%.0f %%</span>'
        '</div>'
        % (color, icono,
           _esc(etiqueta or v.get('pick', {}).get('apuesta', '') or ''),
           ''.join(chips), delta,
           max(2.0, min(100.0, p * 100)), UMBRAL_METER * 100, p * 100))


def _esc(t) -> str:
    return (str(t).replace('&', '&amp;').replace('<', '&lt;')
            .replace('>', '&gt;').replace('"', '&quot;'))


def estilos(st) -> None:
    """Inyecta el CSS UNA vez. Lo llama quien pinta la lista, no cada fila.

    EL CSS NO PUEDE IR POR TARJETA. Medido con AppTest sobre la vista real: se
    inyectaba 138 veces, una por llamada a `pintar`, o sea 138 bloques
    `<style>` idénticos. No rompe nada —el navegador los colapsa— pero es peso
    muerto en cada render y en cada reenvío por websocket.

    Y NO PUEDE MEMORIZARSE EN `session_state`: ese diccionario sobrevive entre
    pasadas, pero Streamlit reconstruye la página entera en cada una. Marcarlo
    como «ya inyectado» dejaría la segunda pasada SIN estilos. Por eso lo
    controla el llamador, que sabe dónde empieza y acaba un render.
    """
    try:
        st.markdown(CSS, unsafe_allow_html=True)
    except Exception as e:
        logger.debug('[veredicto] estilos: %s', e)


def pintar(st, veredictos: List[Dict], titulo: str = '',
           con_estilos: bool = False) -> None:
    """Pinta la lista entera. Un solo `markdown`, que es lo barato."""
    if not veredictos:
        return
    trozos = [CSS] if con_estilos else []
    # v339 — envuelto en `vp-lista` para que la capa visual pueda plegarlo
    # cuando la misma tarjeta ya enseña esas apuestas en su bloque grande
    # (`mm-rec-si`, con cuota y lo que devuelve): eran la misma apuesta dos
    # veces seguidas.
    trozos.append('<div class="vp-lista">')
    if titulo:
        trozos.append('<div style="font-size:.8rem;opacity:.7;'
                      'margin:.4rem 0 .2rem">%s</div>' % _esc(titulo))
    for v in veredictos:
        trozos.append(html(v, (v.get('pick') or {}).get('apuesta', '')))
    trozos.append('</div>')
    st.markdown(''.join(trozos), unsafe_allow_html=True)


if __name__ == '__main__':
    ejemplos = [
        {'apuesta': 'Goles: Menos de 3.5', 'mercado': 'Goles', 'prob': 0.80,
         'cuota': 1.45},
        {'apuesta': 'Goles: Más de 2.5', 'mercado': 'Goles', 'prob': 0.55,
         'cuota': 1.90},
        {'apuesta': 'Boulogne o empate', 'mercado': 'Doble oportunidad',
         'prob': 0.55, 'cuota': 1.75},
        {'apuesta': 'Ambos marcan: No', 'mercado': 'BTTS', 'prob': 0.53,
         'cuota': 1.80},
    ]
    for v in evaluar_lista(ejemplos):
        print('%-8s %-26s modelo %3.0f%% -> ajustada %3.0f%%  fuerza %.2f'
              % (v['veredicto'].upper(), v['pick']['apuesta'][:26],
                 v['prob_modelo'] * 100, v['prob_ajustada'] * 100,
                 v['fuerza']))
        for r in v['razones']:
            print('        · ' + r)
