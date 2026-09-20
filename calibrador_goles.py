#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v225 — El sesgo al Under: sobredispersión de los lambdas, corregida donde duele.

EL DIAGNÓSTICO, SOBRE 47.794 PARTIDOS WALK-FORWARD
---------------------------------------------------
El usuario lo vio en pantalla: «siento que hay más opciones para Menos de».
Medido: el modelo se inclina a Under 2,5 en el **54,5 %** de los partidos y el
Under ocurre de verdad el **50,5 %**.

Lo primero que hay que descartar es un sesgo global, y no lo es — la media de
λ total es 2,6372 contra 2,6394 de goles reales, un +0,1 %. El problema es
**SOBREDISPERSIÓN**: los lambdas varían mucho más que la realidad.

    λ predicho   goles reales   ratio
      1,67           2,35       1,41   ← se queda muy corto
      2,45           2,55       1,04
      3,73           3,01       0,81   ← se pasa mucho

Cuando el modelo predice pocos goles se equivoca a lo grande, y como la línea
de 2,5 cae justo en esa zona, el resultado es un exceso de Unders.

POR QUÉ NO LO ARREGLABA EL ENCOGIMIENTO QUE YA EXISTÍA
------------------------------------------------------
`distributions.encoger_lambdas` **conserva λ_h + λ_a a propósito** — su
docstring lo dice: «el total esperado de goles no cambia; sólo se reparte de
forma menos extrema». Arregla la dispersión del RESULTADO (1X2, hándicap) y no
toca la del TOTAL, que es justo ésta.

DOS ARREGLOS POSIBLES, Y POR QUÉ SE ELIGIÓ ÉSTE
------------------------------------------------
Medido en el pliegue de juicio (n=9.584), con todo ajustado sólo en 0-3:

    opción                      log-loss   Brier    Under%
    hoy (sin tocar)              0,63539   0,22007   53,5 %
    encoger λ hacia la media     0,61306   0,21178   58,9 %   ← EMPEORA el sesgo
    isotónica sobre la prob.     0,61397   0,21198   52,2 %   ← lo mejora
    (la realidad)                                    48,8 %

Encoger el lambda da la mejor log-loss por poco, pero **empuja más
predicciones al lado Under**: al arrastrar todo hacia 2,63 —justo por debajo
del punto donde P(over 2,5) cruza el 50 %— más partidos acaban del lado corto.
Arreglaría la calibración y agravaría justo lo que el usuario reportó.

La isotónica consigue prácticamente la misma mejora, **reduce** el sesgo, y
tiene dos ventajas que deciden:

  · **No toca los lambdas.** El 1X2, el hándicap, los goles por equipo y la
    matriz de marcador siguen exactamente igual. El radio de daño es una sola
    familia de mercados en vez de todo el motor.
  · **Es monótona**, así que conserva el orden de los partidos: el que más
    goles promete sigue siendo el que más promete.

UN HALLAZGO INCÓMODO QUE CONVIENE NO ENTERRAR
---------------------------------------------
En la rejilla completa, **k = 0,00 —ignorar el lambda y predecir siempre la
media de la liga— ya bate al modelo de hoy** (0,62083 contra 0,64393). El
óptimo, k = 0,30, apenas mejora eso. O sea que el lambda aporta muy poca
información sobre el TOTAL de goles por encima de saber en qué liga se juega.

Esto no lo arregla una calibración: es el estimador. Queda escrito aquí porque
es el dato que debería gobernar la próxima tanda del modelo de goles.

Uso:
    python calibrador_goles.py            # entrena, mide y escribe el JSON
    python calibrador_goles.py --medir    # sólo mide
"""

import argparse
import datetime as _dt
import json
import logging
import os
import sys
from typing import Dict, List, Optional

import numpy as np

logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
logger = logging.getLogger('calibrador_goles')

ARTEFACTO = 'calibracion_goles.json'
LEDGER = 'pick_ledger_totales.csv'

# Las líneas que el ledger cubre en todas las competiciones. Son las mismas
# tres de `riesgo_liga.LINEAS_ECE`, y por el mismo motivo: son las únicas con
# resultado real en las 55 competiciones.
LINEAS = (1.5, 2.5, 3.5)

PLIEGUE_JUICIO = 4
N_MINIMO = 2000            # por línea, para ajustar una isotónica
N_PUNTOS = 60              # resolución de la curva guardada

# EL INTERRUPTOR, y por qué éste SÍ viene encendido cuando los de las v212 y
# v215 vienen apagados. La diferencia es qué se está arreglando:
#
#   · Modo Seguridad y la escalada son REGLAS DE SELECCIÓN nuevas: proponen
#     apostar de otra forma, y sin ROI medido no salen a pantalla.
#   · Esto no propone nada. Corrige un número que está MAL: el modelo dice
#     14,7 % de Over 2,5 en 2.034 partidos donde ocurre el 40,8 %. Dejar eso
#     apagado no es prudencia, es seguir enseñando una cifra falsa.
#
# Validado fuera de muestra (pliegue 4, n=9.584, ajustado sólo en 0-3):
# log-loss −3,37 %, Brier −3,67 %, y mejora en el 100 % de 1.000 remuestreos.
USAR_CALIBRACION_GOLES = True


def _f(x) -> Optional[float]:
    try:
        return None if x is None else float(x)
    except (TypeError, ValueError):
        return None


def clave_linea(linea) -> Optional[str]:
    v = _f(linea)
    return None if v is None else ('%.1f' % v)


# ---------------------------------------------------------------------------
_TABLA: Optional[Dict] = None


def cargar(recargar: bool = False) -> Dict:
    global _TABLA
    if _TABLA is not None and not recargar:
        return _TABLA
    _TABLA = {}
    try:
        if os.path.exists(ARTEFACTO):
            with open(ARTEFACTO, encoding='utf-8') as f:
                _TABLA = json.load(f) or {}
    except Exception as e:
        logger.warning('[goles] no se pudo leer %s: %s', ARTEFACTO, e)
    return _TABLA


def disponible(linea=None) -> bool:
    d = (cargar().get('lineas') or {})
    k = clave_linea(linea)
    return bool(d.get(k)) if k else bool(d)


def calibrar(prob: Optional[float], linea) -> Optional[float]:
    """La probabilidad de Over calibrada para esa línea.

    Sin curva devuelve la cruda: no corregir es mejor que corregir a ciegas.
    Nunca lanza y nunca sale de (0, 1).
    """
    p = _f(prob)
    if p is None:
        return None
    k = clave_linea(linea)
    curva = ((cargar().get('lineas') or {}).get(k) or {}) if k else {}
    xs, ys = curva.get('x') or [], curva.get('y') or []
    if len(xs) < 2 or len(xs) != len(ys):
        return p
    try:
        return float(min(0.999, max(0.001, np.interp(p, xs, ys))))
    except Exception as e:
        logger.debug('[goles] interp: %s', e)
        return p


def calibrar_si_activo(prob, linea):
    """Lo que llama el motor: respeta el interruptor."""
    if not USAR_CALIBRACION_GOLES:
        return prob
    v = calibrar(prob, linea)
    return prob if v is None else v


# ---------------------------------------------------------------------------
def _datos():
    import pandas as pd
    t = pd.read_csv(LEDGER)
    t = t[t.lam_h.notna() & t.lam_a.notna()].copy()
    t['lam'] = t.lam_h + t.lam_a
    return t


def _p_over(lam, linea):
    from scipy.stats import poisson
    return 1.0 - poisson.cdf(int(np.floor(float(linea))),
                             np.maximum(lam, 1e-9))


def _metricas(df, probs: Dict):
    ll, br, n = 0.0, 0.0, 0
    for linea in LINEAS:
        col = 'over_%s_real' % str(linea)
        if col not in df.columns:
            continue
        m = df[col].notna()
        if not m.any():
            continue
        y = df.loc[m, col].to_numpy(dtype=float)
        p = np.clip(probs[linea][m.to_numpy()], 1e-6, 1 - 1e-6)
        ll += -float(np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))
        br += float(np.mean((p - y) ** 2))
        n += 1
    return (ll / n, br / n) if n else (float('nan'), float('nan'))


def entrenar(hasta_pliegue: Optional[int] = None) -> Dict:
    """Ajusta una isotónica por línea. Sin fuga: sólo con pliegues previos."""
    from sklearn.isotonic import IsotonicRegression
    t = _datos()
    if hasta_pliegue is not None:
        t = t[t.pliegue < hasta_pliegue]

    doc = {'generado': _dt.datetime.now(_dt.timezone.utc)
                          .strftime('%Y-%m-%dT%H:%M:%SZ'),
           'n_total': int(len(t)), 'lineas': {}}
    for linea in LINEAS:
        col = 'over_%s_real' % str(linea)
        if col not in t.columns:
            continue
        m = t[col].notna()
        if int(m.sum()) < N_MINIMO:
            logger.info('  línea %s: %d filas, por debajo del mínimo',
                        linea, int(m.sum()))
            continue
        p = _p_over(t.loc[m, 'lam'].to_numpy(), linea)
        y = t.loc[m, col].to_numpy(dtype=float)
        iso = IsotonicRegression(out_of_bounds='clip', y_min=0.0, y_max=1.0)
        iso.fit(p, y)
        xs = np.linspace(float(p.min()), float(p.max()), N_PUNTOS)
        doc['lineas'][clave_linea(linea)] = {
            'x': [round(float(v), 5) for v in xs],
            'y': [round(float(v), 5) for v in iso.predict(xs)],
            'n_train': int(m.sum()),
            'desplazamiento_medio': round(
                float(np.mean(iso.predict(p) - p)), 5)}
        logger.info('  línea %s: n=%d, desplaza %+.4f en media',
                    linea, int(m.sum()),
                    doc['lineas'][clave_linea(linea)]['desplazamiento_medio'])
    return doc


def medir(doc: Dict) -> Dict:
    """Juicio en el pliegue que NO se usó para ajustar, con bootstrap."""
    t = _datos()
    jui = t[t.pliegue == PLIEGUE_JUICIO]
    lam = jui['lam'].to_numpy()

    crudas = {L: _p_over(lam, L) for L in LINEAS}
    cal = {}
    for L in LINEAS:
        k = clave_linea(L)
        curva = (doc.get('lineas') or {}).get(k)
        if not curva:
            cal[L] = crudas[L]
            continue
        cal[L] = np.clip(np.interp(crudas[L], curva['x'], curva['y']),
                         1e-6, 1 - 1e-6)

    ll0, br0 = _metricas(jui, crudas)
    ll1, br1 = _metricas(jui, cal)

    # el lado que el modelo elige, contra el que ocurre de verdad
    m = jui['over_2.5_real'].notna()
    real_under = float(1 - jui.loc[m, 'over_2.5_real'].mean())
    u0 = float((crudas[2.5][m.to_numpy()] < 0.5).mean())
    u1 = float((cal[2.5][m.to_numpy()] < 0.5).mean())

    # bootstrap de la mejora
    rng = np.random.default_rng(29)
    jr = jui.reset_index(drop=True)
    n = len(jr)
    difs = []
    for _ in range(1000):
        idx = rng.integers(0, n, n)
        s = jr.iloc[idx]
        l = s['lam'].to_numpy()
        c_ = {L: _p_over(l, L) for L in LINEAS}
        k_ = {}
        for L in LINEAS:
            curva = (doc.get('lineas') or {}).get(clave_linea(L))
            k_[L] = (np.clip(np.interp(c_[L], curva['x'], curva['y']),
                             1e-6, 1 - 1e-6) if curva else c_[L])
        a, _ = _metricas(s, c_)
        b, _ = _metricas(s, k_)
        difs.append(a - b)
    difs = np.array(difs)

    return {
        'n_juicio': int(len(jui)),
        'log_loss_antes': ll0, 'log_loss_despues': ll1,
        'brier_antes': br0, 'brier_despues': br1,
        'mejora_ll_pct': 100.0 * (ll1 / ll0 - 1) if ll0 else None,
        'mejora_brier_pct': 100.0 * (br1 / br0 - 1) if br0 else None,
        'under_antes': u0, 'under_despues': u1, 'under_real': real_under,
        'sesgo_under_antes': u0 - real_under,
        'sesgo_under_despues': u1 - real_under,
        'bootstrap_p5': float(np.percentile(difs, 5)),
        'bootstrap_media': float(difs.mean()),
        'bootstrap_veces_mejora': float((difs > 0).mean()),
    }


def veredicto(m: Dict) -> Dict:
    """Los criterios de siempre: mejora medible y que aguante el remuestreo."""
    fallos = []
    if not (m.get('mejora_ll_pct') or 0) < 0:
        fallos.append('la log-loss no mejora')
    if not (m.get('mejora_brier_pct') or 0) < 0:
        fallos.append('el Brier no mejora')
    if (m.get('bootstrap_p5') or -1) <= 0:
        fallos.append('el percentil 5 del bootstrap no es positivo')
    if abs(m.get('sesgo_under_despues', 1)) > abs(m.get('sesgo_under_antes', 0)):
        fallos.append('el sesgo hacia el Under empeora')
    return {'activa': not fallos, 'fallos': fallos,
            'motivo': ('mejora calibración y reduce el sesgo, y aguanta el '
                       'bootstrap' if not fallos else '; '.join(fallos))}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--medir', action='store_true')
    a = ap.parse_args()

    # Se ajusta SÓLO con los pliegues anteriores al de juicio.
    doc = entrenar(hasta_pliegue=PLIEGUE_JUICIO)
    if not doc.get('lineas'):
        print('sin datos suficientes para ajustar')
        return 1

    m = medir(doc)
    v = veredicto(m)

    print('\n=== JUICIO (pliegue %d, n=%d) ===' % (PLIEGUE_JUICIO, m['n_juicio']))
    print('  log-loss  %.5f -> %.5f  (%+.2f %%)'
          % (m['log_loss_antes'], m['log_loss_despues'], m['mejora_ll_pct']))
    print('  Brier     %.5f -> %.5f  (%+.2f %%)'
          % (m['brier_antes'], m['brier_despues'], m['mejora_brier_pct']))
    print('  se inclina a UNDER  %.1f%% -> %.1f%%   (la realidad: %.1f%%)'
          % (100 * m['under_antes'], 100 * m['under_despues'],
             100 * m['under_real']))
    print('  sesgo del lado UNDER  %+.1f pp -> %+.1f pp'
          % (100 * m['sesgo_under_antes'], 100 * m['sesgo_under_despues']))
    print('\n  bootstrap: mejora %.1f %% de las veces, p5 %+.5f'
          % (100 * m['bootstrap_veces_mejora'], m['bootstrap_p5']))
    print('\n=== VEREDICTO: %s ===' % ('ACEPTADA' if v['activa'] else 'RECHAZADA'))
    print('  ' + v['motivo'])

    if not a.medir:
        # El artefacto de PRODUCCIÓN se ajusta con TODO, que es lo correcto
        # una vez el método está validado con el juicio de arriba.
        final = entrenar()
        final['juicio'] = m
        final['veredicto'] = v
        with open(ARTEFACTO, 'w', encoding='utf-8') as f:
            json.dump(final, f, ensure_ascii=False)
        print('\n-> %s' % ARTEFACTO)
    return 0


if __name__ == '__main__':
    sys.exit(main())
