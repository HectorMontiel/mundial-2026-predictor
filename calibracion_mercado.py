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
W_MIN, W_MAX = 0.45, 0.90


def _tabla() -> dict:
    if 'datos' not in _CACHE:
        datos = {}
        try:
            if os.path.exists(ARCHIVO):
                with open(ARCHIVO, encoding='utf-8') as f:
                    datos = json.load(f).get('ligas') or {}
        except Exception as e:
            logger.warning(f"[calibracion] no se pudo leer {ARCHIVO}: {e}")
        _CACHE['datos'] = datos
    return _CACHE['datos']


def peso_modelo(clave_liga: str) -> float:
    """Peso `w` del modelo frente al mercado en esa liga (1.0 = sin corrección)."""
    info = _tabla().get(clave_liga)
    if not info:
        return 1.0
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
