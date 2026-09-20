#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v230 — «Ambos marcan», que el modelo se come en 44 de 55 ligas.

LO QUE ESTÁ MAL, MEDIDO
-----------------------
`auditoria_ligas.py` sobre los 47.794 partidos del ledger:

    mercado        infravalorado en      mediana del sesgo
    btts           44 de 55 ligas             −4,3 pp
    over_1.5       46 de 55 ligas             −2,1 pp
    over_2.5       37 de 55 ligas             −1,9 pp
    over_3.5       22 de 55 ligas             +0,5 pp

No es ruido de una liga: es el mismo signo, en casi todas, y en algunas llega a
diez puntos. La MLS —la que el usuario preguntó— promete 56,9 % de BTTS donde
ocurre el 59,6 %, sobre 1.830 partidos y con el hallazgo sobreviviendo a
Benjamini-Hochberg.

POR QUÉ PASA
------------
`p_btts` sale de multiplicar dos Poisson independientes:

    P(ambos marcan) = (1 − e^−λh) · (1 − e^−λa)

Y los goles de los dos equipos NO son independientes. El marcador cambia cómo
se juega: el que va perdiendo adelanta líneas y el que gana se estira al
contragolpe, así que un partido en el que marca uno tiene MÁS probabilidad de
que marque el otro de la que da el producto. Bajo independencia esa correlación
positiva se pierde, y lo que se pierde es exactamente lo que falta.

Es la misma raíz que deja cortos los empates (`_v230_empates.json`): el modelo
no sabe que los dos marcadores van de la mano.

POR QUÉ UNA ISOTÓNICA Y NO UNA CORRELACIÓN EN LA MATRIZ
-------------------------------------------------------
Lo correcto de libro sería meter correlación en la matriz de marcador —una
bivariada de Poisson, o el ajuste de Dixon-Coles— y arreglar de un golpe el
BTTS, el empate y el Under. Se probó la versión de un parámetro sobre la
diagonal y **no pasó el listón**: el bootstrap dio p5 negativo. Tocar la matriz
bien hecho es un modelo nuevo que hay que validar entero, y mientras tanto la
cifra publicada seguiría siendo falsa.

La isotónica es el arreglo que este proyecto ya validó para las líneas de goles
en la v225: es monótona, así que NO inventa picks nuevos —no puede reordenar
qué partido es más probable que otro—, sólo pone bien el nivel. Corrige el
número sin tocar el modelo.

Y POR LIGA CUANDO HAY CON QUÉ
-----------------------------
El sesgo no es igual en todas: −10 pp en Bolivia y −2,7 en la MLS. Una curva
global dejaría a media tabla corregida de menos y a la otra media de más. Se
ajusta una curva por liga cuando la liga tiene al menos `MIN_LIGA` partidos, y
las demás heredan la global. Sin ese respaldo, una liga pequeña se calibraría
con su propio ruido, que es peor que no calibrarla.
"""
import datetime as _dt
import json
import logging
import os
from typing import Dict, List, Optional

import numpy as np

logger = logging.getLogger('calibrador_btts')

ARTEFACTO = 'calibracion_btts.json'
LEDGER = 'pick_ledger_totales.csv'
N_PUNTOS = 60
# Mínimo para ajustar una curva GLOBAL. Por debajo no hay isotónica que valga.
N_MINIMO = 2000
# Mínimo para que una liga tenga curva PROPIA. 600 partidos dan un intervalo de
# Wilson de ±4 puntos sobre una base del 50 %, que es la escala del sesgo que se
# quiere corregir: con menos, la curva estaría persiguiendo su propio ruido.
MIN_LIGA = 600

# EL INTERRUPTOR. Viene encendido por el mismo motivo que el de los goles: esto
# no propone una forma nueva de apostar, corrige un número que está MAL. Dejar
# apagado un 57 % donde ocurre el 60 % no es prudencia, es seguir publicando una
# cifra falsa. Lo que decide de verdad es `medir()`: si no supera el bootstrap,
# `main` no escribe el artefacto y `calibrar` devuelve la cruda.
USAR_CALIBRACION_BTTS = True


def _f(x) -> Optional[float]:
    try:
        return None if x is None else float(x)
    except (TypeError, ValueError):
        return None


def clave_liga(liga) -> str:
    return str(liga or '').strip().lower()


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
        logger.warning('[btts] no se pudo leer %s: %s', ARTEFACTO, e)
    return _TABLA


def disponible(liga=None) -> bool:
    d = cargar()
    if not d.get('global'):
        return False
    if liga is None:
        return True
    return bool((d.get('ligas') or {}).get(clave_liga(liga)) or d.get('global'))


def _curva(liga) -> Dict:
    """La curva de esa liga, y si no tiene, la global.

    El respaldo a la global es deliberado: una liga sin muestra propia sigue
    teniendo el sesgo del conjunto —44 de 55 van en el mismo sentido—, así que
    heredarla corrige más de lo que estropea.
    """
    d = cargar()
    propia = (d.get('ligas') or {}).get(clave_liga(liga))
    return propia or d.get('global') or {}


def calibrar(prob: Optional[float], liga=None) -> Optional[float]:
    """La P(ambos marcan) calibrada. Sin curva devuelve la cruda.

    No corregir es mejor que corregir a ciegas. Nunca lanza y nunca sale de
    (0, 1).
    """
    p = _f(prob)
    if p is None:
        return None
    curva = _curva(liga)
    xs, ys = curva.get('x') or [], curva.get('y') or []
    if len(xs) < 2 or len(xs) != len(ys):
        return p
    try:
        return float(min(0.999, max(0.001, np.interp(p, xs, ys))))
    except Exception as e:
        logger.debug('[btts] interp: %s', e)
        return p


def calibrar_si_activo(prob, liga=None):
    """Lo que llama el motor: respeta el interruptor."""
    if not USAR_CALIBRACION_BTTS:
        return prob
    v = calibrar(prob, liga)
    return prob if v is None else v


# ---------------------------------------------------------------------------
def _datos():
    import pandas as pd
    t = pd.read_csv(LEDGER)
    t = t[t.p_btts.notna() & t.btts_real.notna()].copy()
    return t


def _isotonica(p, y) -> Optional[Dict]:
    """Ajusta y devuelve la curva muestreada, o `None` si no hay con qué."""
    from sklearn.isotonic import IsotonicRegression
    if len(p) < 50:
        return None
    iso = IsotonicRegression(out_of_bounds='clip', y_min=0.0, y_max=1.0)
    iso.fit(p, y)
    lo, hi = float(np.min(p)), float(np.max(p))
    if not (hi > lo):
        return None
    xs = np.linspace(lo, hi, N_PUNTOS)
    return {'x': [round(float(v), 5) for v in xs],
            'y': [round(float(v), 5) for v in iso.predict(xs)],
            'n_train': int(len(p)),
            'desplazamiento_medio': round(float(np.mean(iso.predict(p) - p)), 5)}


def entrenar(hasta_pliegue: Optional[int] = None) -> Dict:
    """Una isotónica global y una por liga con muestra. Sin fuga."""
    t = _datos()
    if hasta_pliegue is not None and 'pliegue' in t.columns:
        t = t[t.pliegue < hasta_pliegue]

    doc = {'generado': _dt.datetime.now(_dt.timezone.utc)
                          .strftime('%Y-%m-%dT%H:%M:%SZ'),
           'n_total': int(len(t)), 'min_liga': MIN_LIGA, 'ligas': {}}
    if len(t) < N_MINIMO:
        logger.info('[btts] %d filas, por debajo del mínimo global', len(t))
        return doc

    p = t.p_btts.to_numpy(dtype=float)
    y = t.btts_real.to_numpy(dtype=float)
    doc['global'] = _isotonica(p, y)
    if doc['global']:
        logger.info('[btts] global: n=%d, desplaza %+.4f en media',
                    len(p), doc['global']['desplazamiento_medio'])

    for liga, sub in t.groupby('liga'):
        if len(sub) < MIN_LIGA:
            continue
        curva = _isotonica(sub.p_btts.to_numpy(dtype=float),
                           sub.btts_real.to_numpy(dtype=float))
        if curva:
            doc['ligas'][clave_liga(liga)] = curva
    logger.info('[btts] %d ligas con curva propia (>= %d partidos)',
                len(doc['ligas']), MIN_LIGA)
    return doc


def _aplicar(doc: Dict, p, ligas):
    """Aplica `doc` a mano, sin tocar el artefacto en disco."""
    fuera = np.asarray(p, dtype=float).copy()
    glob = doc.get('global') or {}
    porliga = doc.get('ligas') or {}
    for i, (pi, li) in enumerate(zip(p, ligas)):
        curva = porliga.get(clave_liga(li)) or glob
        xs, ys = curva.get('x') or [], curva.get('y') or []
        if len(xs) >= 2 and len(xs) == len(ys):
            fuera[i] = float(np.interp(pi, xs, ys))
    return np.clip(fuera, 1e-6, 1 - 1e-6)


def medir(doc: Dict) -> Dict:
    """Juzga la calibración en el ÚLTIMO pliegue, que no se usó para ajustar."""
    t = _datos()
    if 'pliegue' not in t.columns:
        return {'error': 'el ledger no trae pliegues'}
    ultimo = int(t.pliegue.max())
    ju = t[t.pliegue == ultimo]
    p = ju.p_btts.to_numpy(dtype=float)
    y = ju.btts_real.to_numpy(dtype=float)
    ligas = ju.liga.astype(str).to_numpy()
    q = _aplicar(doc, p, ligas)

    def _ll(pp):
        pp = np.clip(pp, 1e-6, 1 - 1e-6)
        return float(-np.mean(y * np.log(pp) + (1 - y) * np.log(1 - pp)))

    def _br(pp):
        return float(np.mean((pp - y) ** 2))

    real = float(np.mean(y))
    m = {'n_juicio': int(len(y)),
         'log_loss_antes': _ll(p), 'log_loss_despues': _ll(q),
         'brier_antes': _br(p), 'brier_despues': _br(q),
         'btts_antes': float(np.mean(p)), 'btts_despues': float(np.mean(q)),
         'btts_real': real,
         'sesgo_antes': float(np.mean(p) - real),
         'sesgo_despues': float(np.mean(q) - real)}

    rng = np.random.default_rng(11)
    n = len(y)
    dif = []
    for _ in range(1000):
        s = rng.integers(0, n, n)
        pp, qq, yy = p[s], q[s], y[s]

        def _ll2(z):
            z = np.clip(z, 1e-6, 1 - 1e-6)
            return float(-np.mean(yy * np.log(z) + (1 - yy) * np.log(1 - z)))

        dif.append(_ll2(pp) - _ll2(qq))
    dif = np.array(dif)
    m['bootstrap_p5'] = float(np.percentile(dif, 5))
    m['bootstrap_media'] = float(dif.mean())
    m['bootstrap_veces_mejora'] = float((dif > 0).mean())
    return m


def veredicto(m: Dict) -> Dict:
    """El listón: mejora el log-loss, reduce el sesgo y aguanta el bootstrap."""
    fallos: List[str] = []
    if m.get('error'):
        return {'activa': False, 'fallos': [m['error']], 'motivo': m['error']}
    if not (m['log_loss_despues'] < m['log_loss_antes']):
        fallos.append('el log-loss no mejora')
    if not (abs(m['sesgo_despues']) < abs(m['sesgo_antes'])):
        fallos.append('el sesgo no se reduce')
    if not (m.get('bootstrap_p5', -1) > 0):
        fallos.append('el p5 del bootstrap no es positivo')
    return {'activa': not fallos, 'fallos': fallos,
            'motivo': ('mejora calibración y reduce el sesgo, y aguanta el '
                       'bootstrap' if not fallos else '; '.join(fallos))}


def main() -> int:
    import argparse
    import io
    import sys
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8',
                                  errors='replace')
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    ap = argparse.ArgumentParser()
    ap.add_argument('--escribir', action='store_true',
                    help='escribe el artefacto si el veredicto es favorable')
    a = ap.parse_args()

    t = _datos()
    ultimo = int(t.pliegue.max()) if 'pliegue' in t.columns else None
    if ultimo is None:
        print('el ledger no trae pliegues; no se puede juzgar sin fuga')
        return 1

    # SIN FUGA: se ajusta con los pliegues anteriores y se juzga con el último.
    sin_fuga = entrenar(hasta_pliegue=ultimo)
    m = medir(sin_fuga)
    v = veredicto(m)

    print()
    print('%-22s %12s %12s' % ('', 'antes', 'después'))
    for etq, a_, b_ in (('log-loss', 'log_loss_antes', 'log_loss_despues'),
                        ('Brier', 'brier_antes', 'brier_despues'),
                        ('P(BTTS) media', 'btts_antes', 'btts_despues')):
        print('%-22s %12.5f %12.5f' % (etq, m[a_], m[b_]))
    print('%-22s %12.5f %12s' % ('BTTS real', m['btts_real'], ''))
    print('%-22s %+12.5f %+12.5f' % ('sesgo', m['sesgo_antes'],
                                     m['sesgo_despues']))
    print()
    print('bootstrap: media %+.5f · p5 %+.5f · mejora en %.1f %% de 1.000'
          % (m['bootstrap_media'], m['bootstrap_p5'],
             100 * m['bootstrap_veces_mejora']))
    print()
    print('VEREDICTO: %s — %s' % ('SE ACTIVA' if v['activa'] else 'NO se activa',
                                  v['motivo']))

    if a.escribir and v['activa']:
        # El artefacto que se despliega se entrena con TODO, que es correcto:
        # el juicio ya se hizo arriba sin fuga, y desplegar con menos datos de
        # los disponibles sería tirar muestra por nada.
        doc = entrenar()
        doc['medicion'] = m
        doc['veredicto'] = v
        with open(ARTEFACTO, 'w', encoding='utf-8') as f:
            json.dump(doc, f, ensure_ascii=False, indent=1)
        print('\n-> %s' % ARTEFACTO)
    elif a.escribir:
        print('\nNO se escribe el artefacto: el veredicto no es favorable.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
