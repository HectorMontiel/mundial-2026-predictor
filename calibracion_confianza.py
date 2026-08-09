#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v77 — Qué acierta DE VERDAD cada banda de probabilidad.

El hallazgo que obliga a este módulo
------------------------------------
La pestaña «Máxima Confianza» se pidió con umbral prob ≥ 0,80. Medido sobre
36.006 predicciones fuera de muestra con cuota real (`pick_ledger.csv`), esa
promesa no se sostiene:

    umbral   n      acierto real   ROI      p5 bootstrap
    ≥ 0,60   2.300     62,9 %      +1,20 %   −1,48 %
    ≥ 0,65     539     62,9 %      −0,17 %   −5,53 %
    ≥ 0,70     113     63,7 %      +3,67 %   −8,50 %
    ≥ 0,75      45     57,8 %      −6,47 %  −26,69 %
    ≥ 0,80      17     (muestra insuficiente)

Dos cosas que hay que decir sin adornos:

1. **El acierto NO sube con el umbral.** Se estanca en torno al 63 % y por
   encima de 0,75 empeora. El modelo dice 75 % y entrega 58 %: en la cola alta
   está sobreconfiado, que es el mismo fenómeno que la v71 detectó en el pick
   elegido y la v75 corrigió encogiendo hacia el mercado — pero el
   encogimiento reduce el sesgo medio, no arregla la cola.
2. Con 0,80 la pestaña estaría **vacía casi todos los días**: solo el 2,03 %
   de los partidos llega ahí, y el máximo del barrido de hoy era 0,796.

Qué se hace con eso
-------------------
No se esconde y no se infla. La pestaña usa el umbral 0,70, que es el que mejor
rinde de los medidos, y **cada pick lleva el acierto REAL de su banda** para
que la interfaz pueda poner, junto al «78 %» del modelo, el «esta banda acierta
históricamente un 64 %». Un usuario que ve las dos cifras puede decidir; uno
que solo ve la primera, no.

La tabla se regenera con `python calibracion_confianza.py` cada vez que cambie
el ledger.
"""

import json
import logging
import os
import sys
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

ARCHIVO = 'calibracion_confianza.json'
# v78: el ledger TOTAL incluye los tres deportes, así que las bandas se
# calculan sobre 120.076 predicciones en vez de 36.006.
LEDGER = 'pick_ledger_total.csv'
# Bordes de banda. Se paran en 0,80 porque por encima no hay muestra suficiente
# para afirmar nada (17 casos en todo el histórico).
BANDAS = [(0.50, 0.55), (0.55, 0.60), (0.60, 0.65), (0.65, 0.70),
          (0.70, 0.75), (0.75, 1.01)]
MIN_MUESTRA = 30
_CACHE: Dict[str, dict] = {}


def _tabla() -> dict:
    if 'datos' not in _CACHE:
        datos = {}
        try:
            if os.path.exists(ARCHIVO):
                with open(ARCHIVO, encoding='utf-8') as f:
                    datos = json.load(f)
        except Exception as e:
            logger.warning(f"[confianza] no se pudo leer {ARCHIVO}: {e}")
        _CACHE['datos'] = datos
    return _CACHE['datos']


def acierto_real(prob: Optional[float],
                 mercado: Optional[str] = None) -> Optional[float]:
    """
    Acierto histórico medido de la banda a la que pertenece `prob`.

    v86 — la banda se busca en la tabla DEL MERCADO. Antes sólo existía una
    tabla (la de 1X2) y era la que se devolvía para todo.

    None si no hay muestra suficiente para esa banda — que es una respuesta
    mejor que inventar un número.
    """
    if prob is None:
        return None
    m = _mercado_normalizado(mercado)
    if m == '1X2':
        bandas = _tabla().get('bandas') or []
    else:
        bandas = (_tabla().get('bandas_por_mercado') or {}).get(m) or []
    for b in bandas:
        if b['desde'] <= prob < b['hasta'] and b.get('n', 0) >= MIN_MUESTRA:
            return b.get('acierto')
    return None


# v84 — LAS BANDAS SOLO VALEN PARA EL MERCADO CON EL QUE SE MIDIERON.
#
# `calcular()` construye las bandas desde `pick_ledger_total.csv`, y ese ledger
# contiene **1X2 y ganador de tenis/MLB**: nada de hándicaps, totales ni BTTS.
# Sin embargo el aviso se mostraba junto a picks de «Menos de 3.5» o «+0.5», que
# son otro mercado y otra distribución. Se estaba importando el acierto de un
# sitio para describir otro.
#
# Se declara explícitamente para qué mercados hay medición. Para el resto la
# respuesta honesta no es un número prestado, es «no medido».
#
# v86 — GOLES Y BTTS YA TIENEN MEDICIÓN PROPIA. `build_ledger_totales.py`
# construye P(over) y P(BTTS) fuera de muestra con walk-forward de los
# regresores de Poisson, así que estos mercados dejan de decir «no medido» y
# pasan a llevar su propio acierto real. El que sigue sin medición es el
# hándicap asiático, y ahí se sigue diciendo que no la hay.
MERCADOS_BASE = {'1X2', 'Ganador', 'Moneyline'}


def _mercado_normalizado(mercado: Optional[str]) -> str:
    m = (mercado or '1X2').strip()
    if m in MERCADOS_BASE:
        return '1X2'
    if m.upper() == 'BTTS':
        return 'BTTS'
    if m.lower().startswith('gol'):
        return 'Goles'
    # v87: «Hándicap», «Handicap», «Hándicap asiático»... todo al mismo cajón
    b = m.lower().replace('á', 'a')
    if b.startswith('handicap') or b.startswith('ah '):
        return 'Hándicap'
    return m


def hay_medicion(mercado: Optional[str]) -> bool:
    m = _mercado_normalizado(mercado)
    if m == '1X2':
        return True
    por_mercado = (_tabla().get('bandas_por_mercado') or {})
    bandas = por_mercado.get(m) or []
    return any(b.get('n', 0) >= MIN_MUESTRA for b in bandas)


def probabilidad_real(prob: Optional[float],
                      mercado: Optional[str] = None) -> Optional[float]:
    """
    v84 — LA probabilidad de ganar la apuesta, ya corregida con el histórico.

    Es lo único que hace falta saber para decidir: si el modelo dice 80 % y esa
    banda acierta el 58 %, la probabilidad de ganar es **58 %**. Enseñar el 80 %
    con una nota al pie obliga al usuario a hacer la corrección mentalmente, y
    la mayoría de las veces no la hace.

    Devuelve None cuando no hay medición para ese mercado — y entonces hay que
    decir que no la hay, no rellenar con el número de otro mercado.

    v86 — LA CORRECCIÓN NUNCA INFLA. Se devuelve `min(modelo, histórico)`.

    Motivo, medido: en 1X2 la banda 0,70-0,75 dice que el acierto real es del
    81,8 % frente al 71,3 % del modelo, o sea que "corregiría" hacia ARRIBA.
    Pero esa banda tiene **n=33** y su intervalo bootstrap del 90 % es
    [69,7 %, 90,9 %] — veintiún puntos de ancho. El 81,8 % no se sostiene.

    Y hay un patrón que lo confirma: TODAS las bandas con muestra decente van
    en la otra dirección (sesgo +0,2 % · 0,0 % · +0,9 % · +4,8 % en 1X2;
    de +0,9 % a +8,6 % en Goles; de +1,1 % a +27,4 % en BTTS). El fenómeno
    medido es la SOBRECONFIANZA. La única banda que parece rendir de más es
    justo la de 33 casos.

    Subir una probabilidad mostrada apoyándose en 33 partidos es el único
    error de los dos que no tiene ninguna ventaja para el usuario: le haría
    apostar más sobre una cifra que no está respaldada.
    """
    if prob is None or not hay_medicion(mercado):
        return None
    real = acierto_real(prob, mercado)
    if real is None:
        return None
    return min(float(prob), float(real))


def aviso_calibracion(prob: Optional[float],
                      mercado: Optional[str] = None) -> Optional[str]:
    """Texto para la UI. Distingue «medido y corregido» de «sin medir»."""
    if prob is None:
        return None
    if not hay_medicion(mercado):
        return (f"Sin histórico propio para «{mercado}»: la probabilidad que se "
                f"muestra es la del modelo, sin corregir. Las bandas de acierto "
                f"del proyecto se midieron sobre otros mercados, y usarlas aquí "
                f"sería importar el dato de otro sitio.")
    real = acierto_real(prob, mercado)
    if real is None:
        return None
    if prob - real >= 0.05:
        return (f"Probabilidad corregida con el histórico: {real:.0%} "
                f"(el modelo sin corregir decía {prob:.0%}).")
    return None


LEDGER_TOTALES = 'pick_ledger_totales.csv'
LEDGER_HANDICAP = 'pick_ledger_handicap.csv'


def bandas_de_totales(ledger: str = LEDGER_TOTALES) -> dict:
    """
    v86 — bandas de acierto real para GOLES y BTTS.

    Hasta v85 estos mercados no tenían medición propia y la pestaña «Máxima
    Confianza» decía «no medido» (que era honesto: v84 quitó el número prestado
    de 1X2). `build_ledger_totales.py` genera el sustrato que faltaba —
    P(over 1.5/2.5/3.5) y P(BTTS) fuera de muestra, con walk-forward de los
    regresores de Poisson y paridad exacta con `ClubEngine.predecir`.

    Se calibra el LADO QUE EL MODELO FAVORECE, que es el único que llega a
    mostrarse: si el modelo da 30 % al «Más de 2.5», el pick que aparece es
    «Menos de 2.5» al 70 %. Por eso se toma max(p, 1−p) y si acertó ESE lado.
    """
    import os

    import numpy as np
    import pandas as pd

    if not os.path.exists(ledger):
        logger.info(f'[confianza] {ledger} no existe: Goles y BTTS sin medir')
        return {}
    d = pd.read_csv(ledger)
    rng = np.random.default_rng(20260731)
    out: Dict[str, List[dict]] = {}

    def calibrar(prob, gano, etiqueta):
        prob = np.asarray(prob, dtype=float)
        gano = np.asarray(gano).astype(bool)
        # lado favorecido por el modelo
        lado_alto = prob >= 0.5
        p = np.where(lado_alto, prob, 1 - prob)
        g = np.where(lado_alto, gano, ~gano)
        filas = []
        for lo, hi in BANDAS:
            sel = (p >= lo) & (p < hi)
            n = int(sel.sum())
            fila = {'desde': lo, 'hasta': hi, 'n': n}
            if n >= MIN_MUESTRA:
                ac = float(g[sel].mean())
                idx = rng.integers(0, n, size=(2000, n))
                boot = g[sel][idx].mean(axis=1)
                fila.update({
                    'acierto': round(ac, 4),
                    'prob_media_modelo': round(float(p[sel].mean()), 4),
                    'sesgo': round(float(p[sel].mean() - ac), 4),
                    'acierto_p5': round(float(np.percentile(boot, 5)), 4)})
            filas.append(fila)
        out[etiqueta] = filas
        return filas

    # GOLES: se juntan las tres líneas, porque el mercado que se muestra usa
    # cualquiera de ellas y la banda describe la probabilidad, no la línea.
    probs, ganos = [], []
    for L in (1.5, 2.5, 3.5):
        cp, cg = f'p_over_{L}', f'over_{L}_real'
        if cp in d.columns and cg in d.columns:
            probs.append(d[cp].values)
            ganos.append(d[cg].values.astype(bool))
    if probs:
        calibrar(np.concatenate(probs), np.concatenate(ganos), 'Goles')
    if 'p_btts' in d.columns and 'btts_real' in d.columns:
        calibrar(d['p_btts'].values, d['btts_real'].values.astype(bool), 'BTTS')

    # v87 — HÁNDICAP ASIÁTICO. Era el último mercado popular sin medición.
    # `build_ledger_handicap.py` reconstruye P(el local cubre la línea) desde la
    # MISMA matriz de marcadores que usa `alpha_finder`, con los λ y las
    # probabilidades 1X2 fuera de muestra que ya estaban en los ledgers. No hizo
    # falta histórico de líneas asiáticas: para calibrar hace falta la
    # probabilidad y si se cubrió, no la cuota.
    #
    # v106 — SE EXCLUYEN LOS PUSH, QUE ANTES CONTABAN COMO ACIERTO.
    #
    # La v87 sólo medía líneas .5, donde no hay push, y `astype(bool)` bastaba.
    # Ahora el ledger cubre también las enteras y las de cuarto (que son las
    # que producción evalúa de verdad, ver `handicap.py`) y en ellas el
    # resultado es NaN cuando el partido acaba justo en la línea. `np.nan`
    # convertido a bool es **True**: sin este filtro, los 10.966 push de la
    # línea −1,0 entrarían en la tabla como aciertos y la calibración quedaría
    # optimista justo en el mercado que se está arreglando.
    #
    # Se exige además `res_ah_* == 1`: sólo entran las observaciones en las que
    # se arriesgó el importe ENTERO. En una línea de cuarto que cae en el medio
    # punto sólo se resuelve la mitad, y mezclar esas con las de importe
    # completo desequilibra la banda. Son pocas y su probabilidad sale de la
    # misma distribución de margen que las .5, así que no se pierde cobertura.
    if os.path.exists(LEDGER_HANDICAP):
        h = pd.read_csv(LEDGER_HANDICAP)
        probs, ganos = [], []
        for col in h.columns:
            if col.startswith('p_ah_'):
                L = col[len('p_ah_'):]
                real, res = f'ah_{L}_real', f'res_ah_{L}'
                if real not in h.columns:
                    continue
                ok = h[col].notna() & h[real].notna()
                if res in h.columns:
                    ok &= (h[res] - 1.0).abs() < 1e-9
                if not ok.any():
                    continue
                probs.append(h.loc[ok, col].values)
                ganos.append(h.loc[ok, real].values.astype(float) > 0.5)
        if probs:
            calibrar(np.concatenate(probs), np.concatenate(ganos), 'Hándicap')
    return out


def calcular(ledger: str = LEDGER) -> dict:
    import numpy as np
    import pandas as pd
    import calibracion_mercado as cm
    import recalibrate_from_history as rec

    # v78: NO se exige `cuota_draw`. Es nula en tenis, MLB y NBA —no tienen
    # empate— y pedirla descartaba los tres deportes en silencio, dejando las
    # bandas calculadas solo con fútbol. Es el mismo descuido que tenía
    # `recalibrate_from_history.cargar` antes de generalizarla.
    d = rec.cargar(ledger).dropna(subset=['cuota_home', 'cuota_away'])
    pm = d[['p_home', 'p_draw', 'p_away']].values
    mk = d[['m_home', 'm_draw', 'm_away']].values
    cu = d[['cuota_home', 'cuota_draw', 'cuota_away']].values.astype(float)
    cp = d[['pin_home', 'pin_draw', 'pin_away']].values.astype(float)
    mejor = np.fmax(cu, np.nan_to_num(cp, nan=0.0))
    w = d['liga'].map(lambda k: cm.peso_modelo(k)).values[:, None]
    p = w * pm + (1 - w) * mk
    p = p / p.sum(axis=1, keepdims=True)
    y = d['resultado'].values.astype(int)
    f = np.arange(len(d))
    k = p.argmax(axis=1)
    prob, cuota, gano = p[f, k], mejor[f, k], (k == y)

    rng = np.random.default_rng(20260728)
    bandas = []
    for lo, hi in BANDAS:
        sel = (prob >= lo) & (prob < hi) & (cuota >= 1.5)
        n = int(sel.sum())
        fila = {'desde': lo, 'hasta': hi, 'n': n}
        if n >= MIN_MUESTRA:
            pnl = np.where(gano[sel], cuota[sel] - 1, -1.0)
            idx = rng.integers(0, len(pnl), size=(2000, len(pnl)))
            # v86: intervalo del ACIERTO, no sólo del ROI. Hace falta para saber
            # si una banda con muestra corta sostiene lo que dice.
            ac_boot = gano[sel].astype(float)[
                rng.integers(0, n, size=(2000, n))].mean(axis=1)
            fila.update({
                'acierto': round(float(gano[sel].mean()), 4),
                'acierto_p5': round(float(np.percentile(ac_boot, 5)), 4),
                'acierto_p95': round(float(np.percentile(ac_boot, 95)), 4),
                'prob_media_modelo': round(float(prob[sel].mean()), 4),
                'sesgo': round(float(prob[sel].mean() - gano[sel].mean()), 4),
                'roi': round(float(pnl.mean()), 4),
                'p5': round(float(np.percentile(pnl[idx].mean(axis=1), 5)), 4),
                'cuota_media': round(float(cuota[sel].mean()), 3)})
        bandas.append(fila)

    # y los umbrales acumulados, que es lo que decide la pestaña
    umbrales = []
    for u in (0.60, 0.65, 0.70, 0.75, 0.80):
        sel = (prob >= u) & (cuota >= 1.5)
        n = int(sel.sum())
        fila = {'umbral': u, 'n': n, 'pct_partidos': round(float(sel.mean()), 4)}
        if n >= MIN_MUESTRA:
            pnl = np.where(gano[sel], cuota[sel] - 1, -1.0)
            idx = rng.integers(0, len(pnl), size=(2000, len(pnl)))
            fila.update({'acierto': round(float(gano[sel].mean()), 4),
                         'roi': round(float(pnl.mean()), 4),
                         'p5': round(float(np.percentile(pnl[idx].mean(axis=1), 5)), 4)})
        umbrales.append(fila)

    validos = [u for u in umbrales if u.get('roi') is not None]
    recomendado = max(validos, key=lambda u: u['roi'])['umbral'] if validos else 0.70

    salida = {
        'generado_de': ledger, 'n_total': int(len(d)),
        'bandas': bandas, 'umbrales': umbrales,
        'bandas_por_mercado': bandas_de_totales(),
        'umbral_recomendado': recomendado,
        'nota': 'Acierto REAL por banda de probabilidad, medido fuera de '
                'muestra. El acierto no crece con el umbral: se estanca en '
                '~63 % y por encima de 0,75 baja (el modelo sobreconfía en la '
                'cola). La pestaña de Máxima Confianza lo muestra junto a la '
                'probabilidad del modelo para no prometer lo que no cumple.',
    }
    with open(ARCHIVO, 'w', encoding='utf-8') as fh:
        json.dump(salida, fh, ensure_ascii=False, indent=1)
    _CACHE.pop('datos', None)
    return salida


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    s = calcular()
    print(f"{s['n_total']} predicciones fuera de muestra\n")
    print(f"{'banda':>14s} {'n':>6s} {'modelo':>8s} {'real':>8s} {'sesgo':>8s} {'ROI':>8s}")
    for b in s['bandas']:
        if b.get('acierto') is None:
            print(f"{b['desde']:.2f}-{b['hasta']:.2f}   {b['n']:6d}   (muestra insuficiente)")
            continue
        print(f"  {b['desde']:.2f}-{b['hasta']:.2f} {b['n']:6d} "
              f"{b['prob_media_modelo']:8.1%} {b['acierto']:8.1%} "
              f"{b['sesgo']:+8.1%} {b['roi']:+8.2%}")
    print(f"\numbral recomendado para «Máxima Confianza»: {s['umbral_recomendado']:.2f}")
