#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v71 — Corrección de la sobreconfianza del pick contra el mercado sharp.

El hallazgo
-----------
Medido el 2026-07-28 sobre 315 selecciones con cuota de Pinnacle vigente
(`_v71_calibracion_vs_pinnacle.py`):

  · El sesgo GLOBAL del modelo es **0,0000**. Sus probabilidades, en conjunto,
    no están infladas.
  · Pero el sesgo **en la selección que el modelo elige** es positivo en 10 de
    15 ligas, y grande en varias:
        aut_bundesliga  +13,1 pp     usl_championship +5,3 pp
        brasil           +9,6 pp     liga_mx          +4,1 pp
        chi_primera      +6,7 pp
  · La correlación con Pinnacle es 0,70: el modelo lleva señal real, lo que
    falla es el NIVEL del lado que escoge.

Es la maldición del ganador de manual: al quedarte con el argmax te quedas con
la selección donde tu ruido fue más favorable, así que su probabilidad está
sesgada al alza aunque el vector completo esté bien calibrado.

Por qué importa
---------------
El EV se calcula como `cuota × p_modelo − 1`. Con el pick inflado 4-13 puntos,
el EV sale positivo en apuestas que en realidad son negativas, y la Capa 1 se
llena de picks perdedores. Encaja con los ROI observados: Liga MX −11,8 % con
+4,1 pp de sobreconfianza, EFL League One −21,7 %.

La corrección
-------------
Cuando hay cuota de Pinnacle se encoge la probabilidad del modelo hacia la
probabilidad justa del mercado:

    p_final = w · p_modelo + (1 − w) · p_pinnacle

`w` se fija por liga a partir del sesgo medido: cuanto más sobreconfía la liga,
menos peso se le da al modelo. Sin cuota de Pinnacle no hay nada que encoger y
la probabilidad se queda como está (degradación limpia).

Esto NO es rendirse ante el mercado: con w≈0,6 el modelo sigue mandando, pero
deja de cobrar EV por una diferencia que la evidencia dice que es suya, no del
mercado.
"""
import json
import logging
import os
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)

ARCHIVO = 'calibracion_mercado.json'
_CACHE: Dict[str, dict] = {}

# Peso mínimo del modelo: por muy sesgada que salga una liga nunca se anula del
# todo (si no, la app sería un espejo de Pinnacle y no aportaría nada).
#
# v75 — EL SUELO BAJA DE 0.45 A 0.25, y no por gusto.
#
# El 0.45 de la v71 fue una decisión de producto, no una medida: se eligió para
# que el modelo siguiera mandando. Con `pick_ledger.csv` (33.476 predicciones
# fuera de muestra con cuota de cierre real) se pudo medir por primera vez qué
# rinde cada peso, y el 0.45 cae de lleno en la zona de pérdidas:
#
#     w      picks   ROI (cierre medio)   ROI (mejor precio)   p5 bootstrap
#     1.00     951        −3,93 %              −1,15 %            −5,72 %
#     0.80     816        −1,78 %              −1,28 %            −5,92 %
#     0.60     622        −3,11 %              −0,38 %            −5,08 %
#     0.45     451        −3,27 %              −2,71 %            −8,01 %
#     0.40     427        +3,16 %              +1,02 %            −4,64 %
#     0.30     339        +5,03 %              +6,41 %            **+0,24 %**
#     0.20     252        +8,65 %              +6,57 %            −0,73 %
#
# La selección solo pasa a rentable por debajo de 0.40, y el único punto donde
# el peor 5 % plausible también gana es w≈0.30. La log-loss y la precisión
# apuntan en la misma dirección y de forma monótona (log-loss 1.0294 → 0.9996 y
# precisión 0.4904 → 0.5039 al bajar w de 1 a 0), así que no hay conflicto
# entre calibrar bien y ganar dinero: las dos piden más peso al mercado.
#
# Con el suelo en 0.45 la corrección de la v71 no podía llegar a donde estaba
# la mejora. Se baja a 0.25 — el modelo sigue aportando un cuarto de la señal y
# no se convierte en un espejo — y el valor concreto de cada liga lo elige
# `recalibrate_from_history.py` fuera de muestra, no esta constante.
W_MIN, W_MAX = 0.25, 0.90


def _tabla() -> dict:
    """
    Tabla de pesos, indexada en MINÚSCULAS.

    v79 — la clave venía con la caja que le tocara según quién construyera el
    ledger: `build_ledger_deportes.ledger_tenis` escribe `liga` como
    `circuito.upper()` («ATP», «WTA») y `ledger_mlb` la escribe en minúsculas
    («mlb»). `recalibrate_from_history` usa esa columna tal cual como clave del
    JSON, así que el fichero acababa con «ATP» y «WTA» en mayúsculas.

    Producción, en cambio, pregunta en minúsculas: `alpha_finder._picks_tenis`
    llama con `eng.circuito.lower()`. Resultado medido:

        peso_modelo('atp') -> 1.00      peso_modelo('ATP') -> 0.25
        peso_modelo('wta') -> 1.00      peso_modelo('WTA') -> 0.25

    O sea: el tenis se quedaba **sin encoger, en silencio**, justo después de
    que la v78 midiera que encoger le mejora la precisión +2,6 pp (ATP) y
    +2,4 pp (WTA). Ningún error, ninguna traza: solo w=1 y picks más
    sobreconfiados.

    Se normaliza al leer, que arregla el fichero actual y cualquier otro que
    escriba un constructor futuro con otra convención de caja.
    """
    if 'datos' not in _CACHE:
        datos = {}
        w_glob = None
        try:
            if os.path.exists(ARCHIVO):
                with open(ARCHIVO, encoding='utf-8') as f:
                    doc = json.load(f)
                crudo = doc.get('ligas') or {}
                for k, v in crudo.items():
                    datos[str(k).strip().lower()] = v
                if len(datos) != len(crudo):
                    logger.warning(
                        f"[calibracion] {len(crudo) - len(datos)} claves de "
                        f"{ARCHIVO} colisionan al normalizar la caja")
                try:
                    w_glob = float(doc.get('w_global'))
                except (TypeError, ValueError):
                    w_glob = None
        except Exception as e:
            logger.warning(f"[calibracion] no se pudo leer {ARCHIVO}: {e}")
        _CACHE['datos'] = datos
        _CACHE['w_global'] = w_glob
    return _CACHE['datos']


def w_global() -> Optional[float]:
    """Peso elegido sobre TODO el histórico, no sobre una liga suelta."""
    _tabla()
    w = _CACHE.get('w_global')
    if w is None:
        return None
    return max(W_MIN, min(W_MAX, float(w)))


def peso_modelo(clave_liga: str) -> float:
    """Peso `w` del modelo frente al mercado en esa liga (1.0 = sin corrección).

    La búsqueda es INSENSIBLE A MAYÚSCULAS a propósito: ver `_tabla`.
    """
    if not clave_liga:
        return 1.0
    info = _tabla().get(str(clave_liga).strip().lower())
    if not info:
        # v80 — UNA LIGA SIN PESO MEDIDO CAE AL GLOBAL, NO A «SIN CORREGIR».
        #
        # Hasta ahora devolvía 1,00, y eso no era abstenerse: era elegir
        # activamente la opción que la evidencia global descarta. El w global
        # se elige sobre 75.131 partidos y se valida en un pliegue aparte de
        # 14.636 (log-loss 0,8056 → 0,7855); el w por liga se decide con
        # muestras de 52 a 124 picks, y con 38 ligas evaluadas eso son 38
        # decisiones tomadas sobre ruido.
        #
        # El coste de la caída a 1,00 estaba medido y era grave. Replicando el
        # método exacto de `validacion_deportes` (line shopping y un pick por
        # partido, el del argmax) sobre las 36.006 filas de fútbol del ledger:
        #
        #     política                          n     ROI      p5
        #     A) actual   (sin peso → w=1,00)  1235   +3,65 %  −1,11 %
        #     B) caer al global (w=0,25)        589   +5,92 %  +0,34 %
        #     C) uniforme w=0,25                584   +6,72 %  +1,02 %
        #
        # La política A **no tiene edge validado**: su p5 es negativo. Y ahí
        # está la incoherencia que esto arregla — `validacion_deportes` valida
        # el fútbol aplicando un w UNIFORME (de ahí el +6,72 % que luce el
        # sistema), mientras producción aplicaba w por liga con caída a 1,00.
        # Lo que se validaba no era lo que se desplegaba.
        #
        # Se adopta B: la liga medida conserva su w, y la que no tiene medición
        # hereda el global. Es encogimiento jerárquico de manual — sin datos
        # propios, se usa el previo — y es lo que ya prometía la nota de método
        # del propio `recalibrate_from_history`.
        #
        # C midió algo mejor todavía, pero su ventaja sobre B descansa en tres
        # ligas (turquia, eng_national, eng_league_two) que son las únicas con
        # w distinto de 0,25: tirar su medición por 5 picks de diferencia sería
        # cambiar evidencia por ruido.
        g = w_global()
        return max(W_MIN, min(W_MAX, g)) if g is not None else 1.0
    try:
        w = float(info.get('w', 1.0))
    except (TypeError, ValueError):
        return 1.0
    return max(W_MIN, min(W_MAX, w))


def w_desde_sesgo(sesgo_pick: float, n: int) -> float:
    """
    Convierte el sesgo medido en un peso.

    Un sesgo de +10 pp sobre una probabilidad típica de 0,55 significa que casi
    una quinta parte de la ventaja declarada es ruido. Se traduce linealmente y
    se modera cuando la muestra es pequeña (con 4 partidos no se toca nada
    agresivo: el propio sesgo está mal medido).
    """
    if sesgo_pick is None or n < 4:
        return 1.0
    s = max(0.0, float(sesgo_pick))
    w = 1.0 - min(0.5, s * 4.0)           # +12.5 pp de sesgo → w = 0.5
    confianza = min(1.0, n / 20.0)        # con n<20 se aplica solo en parte
    return round(1.0 - (1.0 - w) * confianza, 3)


def encoger_dos_vias(p_home: float, cuota_home: Optional[float],
                     cuota_away: Optional[float],
                     clave_liga: str) -> Tuple[float, dict]:
    """
    v79 — punto de entrada RESILIENTE para el encogimiento a dos vías.

    En producción se vio esto:

        [alpha] tenis omitido: AttributeError: module 'calibracion_mercado'
                has no attribute 'corregir_dos_vias'

    ...con la función presente en el fichero y en los dos remotos. La causa es
    de Streamlit, no del código: los módulos importados sobreviven entre
    ejecuciones en `sys.modules`, así que al desplegar la v78 quedó un
    `calibracion_mercado` de la v77 ya cargado en memoria mientras
    `alpha_finder` sí era el nuevo. El import de dentro de la función devolvía
    el módulo viejo y el atributo no existía.

    Lo grave no fue el fallo, sino el radio de daño: el `except` que lo
    recogía envolvía el barrido ENTERO de tenis, así que un problema de
    calibración borró los 319 partidos del día. Aquí se invierte esa relación
    — si el encogimiento no se puede aplicar, se devuelve la probabilidad sin
    corregir y se sigue. Perder la corrección es un grado de calidad; perder
    el deporte es perderlo todo.
    """
    try:
        return corregir_dos_vias(p_home, cuota_home, cuota_away, clave_liga)
    except Exception as e:                       # nunca tumbar un deporte
        logger.warning(f"[calibracion] encogimiento no aplicado en "
                       f"{clave_liga}: {type(e).__name__}: {e}")
        return p_home, {'aplicado': False, 'w': 1.0, 'liga': clave_liga,
                        'error': f'{type(e).__name__}: {e}'}


def corregir_dos_vias(p_home: float, cuota_home: Optional[float],
                      cuota_away: Optional[float],
                      clave_liga: str) -> Tuple[float, dict]:
    """
    Encogimiento hacia el mercado en deportes SIN empate (tenis, MLB, NBA).

    v78 — hasta ahora la corrección solo llegaba al fútbol, porque
    `calibracion_mercado.json` se indexaba por clave de liga de fútbol y
    `corregir()` espera un vector home/draw/away. Los otros deportes emitían
    EV sin corregir, que es justo donde aparecían los +49 % y +11 % que
    delataban sobreconfianza.

    Medido sobre 46.210 partidos de tenis fuera de muestra con cuota real,
    encoger con w=0.25 mejora la log-loss de 0,6105 a 0,5842 y la precisión de
    65,9 % a 68,3 %. ATP y WTA superan la regla de adopción con muestras de
    30.327 y 15.883 partidos.

    Devuelve (probabilidad corregida del primer lado, info).
    """
    info = {'aplicado': False, 'w': 1.0, 'liga': clave_liga}
    try:
        ch, ca = float(cuota_home or 0), float(cuota_away or 0)
    except (TypeError, ValueError):
        return p_home, info
    if ch <= 1 or ca <= 1:
        return p_home, info          # sin precio no hay hacia dónde encoger
    w = peso_modelo(clave_liga)
    if w >= 1.0:
        return p_home, info
    # probabilidad justa del mercado a dos vías (proporcional: con solo dos
    # salidas el método de potencia y el proporcional coinciden en la práctica)
    ih, ia = 1.0 / ch, 1.0 / ca
    p_mkt = ih / (ih + ia)
    out = w * float(p_home) + (1 - w) * p_mkt
    out = min(max(out, 1e-6), 1 - 1e-6)
    info.update({'aplicado': True, 'w': w, 'p_mercado': round(p_mkt, 4),
                 'desplazamiento': round(out - float(p_home), 4)})
    return out, info


def corregir(probs: Dict[str, float], p_mercado: Optional[Dict[str, float]],
             clave_liga: str) -> Tuple[Dict[str, float], dict]:
    """
    Encoge las probabilidades del modelo hacia el mercado.

    `probs` y `p_mercado` son dicts con 'home'/'draw'/'away'. Devuelve
    (probabilidades corregidas, info) e informa de si se aplicó.
    """
    info = {'aplicado': False, 'w': 1.0, 'liga': clave_liga}
    if not p_mercado:
        return probs, info
    faltan = [k for k in probs if k not in p_mercado or not p_mercado[k]]
    if faltan:
        return probs, info
    w = peso_modelo(clave_liga)
    if w >= 1.0:
        return probs, info
    out = {k: w * probs[k] + (1 - w) * p_mercado[k] for k in probs}
    s = sum(out.values())
    if s <= 0:
        return probs, info
    out = {k: v / s for k, v in out.items()}
    info.update({'aplicado': True, 'w': w,
                 'desplazamiento': round(max(abs(out[k] - probs[k])
                                             for k in probs), 4)})
    return out, info


def generar(ruta_diag: str = '_v71_calibracion_vs_pinnacle.json') -> dict:
    """Construye `calibracion_mercado.json` a partir del diagnóstico medido."""
    with open(ruta_diag, encoding='utf-8') as f:
        diag = json.load(f)
    ligas = {}
    for r in diag.get('por_liga', []):
        w = w_desde_sesgo(r.get('sesgo_pick'), r.get('n_partidos') or 0)
        if w >= 1.0:
            continue
        ligas[r['clave']] = {
            'w': w, 'sesgo_pick': r.get('sesgo_pick'),
            'n_partidos': r.get('n_partidos'), 'mae': r.get('mae'),
            'corr': r.get('corr')}
    salida = {
        'generado': diag.get('generado'),
        'nota': 'v71. Peso del modelo frente a la probabilidad justa de '
                'Pinnacle, por liga. Sale del sesgo medido en la selección que '
                'el modelo elige (maldición del ganador). Liga ausente = w=1 = '
                'sin corrección.',
        'global': diag.get('global'), 'ligas': ligas}
    with open(ARCHIVO, 'w', encoding='utf-8') as f:
        json.dump(salida, f, ensure_ascii=False, indent=1)
    _CACHE.pop('datos', None)
    return salida


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    s = generar()
    print(f"{len(s['ligas'])} ligas con corrección:")
    for k, v in sorted(s['ligas'].items(), key=lambda kv: kv[1]['w']):
        print(f"   {k:20s} w={v['w']:.3f}  (sesgo del pick "
              f"{v['sesgo_pick']:+.4f}, n={v['n_partidos']})")
