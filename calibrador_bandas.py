#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v215 — Calibración por banda de cuota: arreglar el mapeo sin tocar el modelo.

EL DIAGNÓSTICO QUE LO MOTIVA
----------------------------
`patrones_acierto.py` midió, sobre 107.280 picks resueltos con cuota real, que
la calibración del modelo se degrada monótonamente según se alarga la cuota:

    banda        hit real   prob. del modelo   calibración
    1,20-1,50     72,5 %        68,0 %           +0,045
    1,50-1,80     58,1 %        59,6 %           −0,015
    1,80-2,20     47,9 %        53,8 %           −0,059
    2,20-3,00     38,3 %        47,6 %           −0,093
    3,00-6,00     28,9 %        43,6 %           −0,147

En los partidos parejos —los de 1,80-2,20, donde los dos equipos pagan
parecido— el modelo promete casi 54 % y acierta 48 %. No está «cerca y
fallando»: está **sistemáticamente optimista**, y siempre en el mismo sentido.

Un sesgo que va siempre en la misma dirección no se arregla prediciendo mejor:
se arregla corrigiendo el mapeo. Eso es esto.

LO QUE LA CALIBRACIÓN PUEDE Y NO PUEDE HACER — Y CONVIENE DECIRLO ANTES
-----------------------------------------------------------------------
La isotónica es MONÓTONA. Eso tiene una consecuencia que decide qué esperar:

    **no cambia el ORDEN de los picks.**

Si hoy el pick A parece mejor que el B por probabilidad, después de calibrar
sigue pareciéndolo. Así que la calibración **no puede descubrir apuestas
buenas** que antes pasaran desapercibidas. Lo que sí hace, y no es poco:

    · arregla el Brier y el ECE, que es lo que mide si el número que se
      enseña significa lo que dice;
    · **impide apuestas malas**, porque al bajar la probabilidad en la banda
      sobreconfiada, los picks que antes cruzaban el listón de EV o de
      probabilidad mínima dejan de cruzarlo.

O sea: la calibración no crea ventaja, evita pérdidas. Quien espere que esto
suba el ROI por sí solo va a leer mal el resultado.

CÓMO SE ENTRENA, SIN FUGA
-------------------------
Una isotónica por banda de cuota, y **walk-forward**: la del pliegue k se
ajusta SÓLO con los pliegues anteriores. Calibrar con el mismo tramo que se
mide es el error clásico de esta técnica — sale un ECE precioso y no significa
nada. El pliegue 0 no tiene pasado, así que se queda sin calibrar y se dice.

EL ARTEFACTO ES PORTABLE A PROPÓSITO
------------------------------------
No se guarda el objeto de sklearn con pickle: se guardan los puntos de la
función escalonada en JSON y se interpola al usarla. El repositorio ya tuvo el
problema de boosters serializados que no abrían en otra plataforma
(`modelos_portables.py` existe por eso). Un JSON de pares (x, y) se lee en
cualquier sitio y dentro de cinco años.

Uso:
    python calibrador_bandas.py            # entrena, mide y escribe el informe
    python calibrador_bandas.py --medir    # sólo mide con lo ya entrenado
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
logger = logging.getLogger('calibrador')

ARTEFACTO = 'calibracion_bandas.json'
SALIDA_MD = 'mejora_banda_180_220.md'

# Las mismas bandas que usa el diagnóstico, para poder comparar tabla a tabla.
BANDAS = ((1.20, 1.50), (1.50, 1.80), (1.80, 2.20), (2.20, 3.00), (3.00, 6.00))

# La banda que este encargo quiere arreglar.
BANDA_OBJETIVO = '1.80-2.20'

N_MINIMO_BANDA = 300        # por debajo de esto, la isotónica es ruido
N_BOOTSTRAP = 2000

# EL INTERRUPTOR. Arranca en False, como todo lo que este proyecto no ha
# medido todavía en producción.
USAR_CALIBRACION = False


def nombre_banda(cuota: Optional[float]) -> Optional[str]:
    try:
        c = float(cuota)
    except (TypeError, ValueError):
        return None
    for lo, hi in BANDAS:
        if lo <= c < hi:
            return f'{lo:.2f}-{hi:.2f}'
    return None


# ---------------------------------------------------------------------------
# El artefacto
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
        logger.warning('[calibrador] no se pudo leer %s: %s', ARTEFACTO, e)
    return _TABLA


def disponible(banda: Optional[str] = None) -> bool:
    d = (cargar().get('bandas') or {})
    return bool(d.get(banda)) if banda else bool(d)


def calibrar(prob: Optional[float], cuota: Optional[float]) -> Optional[float]:
    """La probabilidad calibrada de esa banda. Si no hay curva, devuelve la cruda.

    Nunca lanza y nunca devuelve algo fuera de (0, 1): una calibración que
    produce una probabilidad imposible es peor que no calibrar.
    """
    try:
        p = float(prob)
    except (TypeError, ValueError):
        return None
    b = nombre_banda(cuota)
    curva = ((cargar().get('bandas') or {}).get(b) or {}) if b else {}
    xs, ys = curva.get('x') or [], curva.get('y') or []
    if len(xs) < 2 or len(xs) != len(ys):
        return p
    try:
        v = float(np.interp(p, xs, ys))
    except Exception as e:
        logger.debug('[calibrador] interp: %s', e)
        return p
    return float(min(0.999, max(0.001, v)))


# ---------------------------------------------------------------------------
# Métricas (mismas definiciones que el resto del proyecto)
# ---------------------------------------------------------------------------
def _brier(p, y):
    return float(np.mean((np.asarray(p) - np.asarray(y)) ** 2)) if len(p) else None


def _ece(p, y, n_cajas: int = 10):
    p, y = np.asarray(p, dtype=float), np.asarray(y, dtype=float)
    if not len(p):
        return None
    bordes = np.linspace(0, 1, n_cajas + 1)
    tot, n = 0.0, len(p)
    for i in range(n_cajas):
        m = ((p >= bordes[i]) & (p < bordes[i + 1])) if i < n_cajas - 1 \
            else ((p >= bordes[i]) & (p <= bordes[i + 1]))
        if m.any():
            tot += m.sum() / n * abs(y[m].mean() - p[m].mean())
    return float(tot)


def _p5(g, n: int = N_BOOTSTRAP, seed: int = 13):
    g = np.asarray(g, dtype=float)
    if len(g) < 30:
        return None
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(g), size=(n, len(g)))
    return float(np.percentile(g[idx].mean(axis=1), 5))


# ---------------------------------------------------------------------------
def _datos():
    """El universo de picks resueltos, reutilizando el cargador del diagnóstico.

    Se llama a `patrones_acierto.cargar()` y no se reimplementa: si las dos
    rutas divergieran, la tabla de «antes» del informe dejaría de ser
    comparable con la del diagnóstico, que es justo lo que hay que comparar.
    """
    import patrones_acierto as pa
    d = pa.cargar()
    d = d[d['banda_cuota'].notna()].copy()
    return d


def entrenar() -> Dict:
    """Ajusta una isotónica por banda y pliegue, sin fuga, y escribe el JSON."""
    from sklearn.isotonic import IsotonicRegression

    d = _datos()
    doc = {'generado': _dt.datetime.now().strftime('%Y-%m-%d %H:%M'),
           'n_total': int(len(d)), 'bandas': {}, 'por_pliegue': {}}

    pliegues = sorted(int(x) for x in d['pliegue'].unique())

    # --- las curvas POR PLIEGUE, que son las que miden sin fuga -------------
    for k in pliegues:
        prev = d[d.pliegue < k]
        if not len(prev):
            continue
        doc['por_pliegue'][str(k)] = {}
        for b in prev['banda_cuota'].dropna().unique():
            sub = prev[prev.banda_cuota == b]
            if len(sub) < N_MINIMO_BANDA:
                continue
            iso = IsotonicRegression(out_of_bounds='clip', y_min=0.0, y_max=1.0)
            iso.fit(sub['prob'].to_numpy(), sub['acierto'].to_numpy())
            xs = np.linspace(sub['prob'].min(), sub['prob'].max(), 40)
            doc['por_pliegue'][str(k)][str(b)] = {
                'x': [round(float(v), 5) for v in xs],
                'y': [round(float(v), 5) for v in iso.predict(xs)],
                'n_train': int(len(sub))}

    # --- la curva de PRODUCCIÓN: con todo lo disponible ---------------------
    for b in d['banda_cuota'].dropna().unique():
        sub = d[d.banda_cuota == b]
        if len(sub) < N_MINIMO_BANDA:
            logger.info('  banda %s: %d picks, por debajo del mínimo',
                        b, len(sub))
            continue
        iso = IsotonicRegression(out_of_bounds='clip', y_min=0.0, y_max=1.0)
        iso.fit(sub['prob'].to_numpy(), sub['acierto'].to_numpy())
        xs = np.linspace(sub['prob'].min(), sub['prob'].max(), 40)
        doc['bandas'][str(b)] = {
            'x': [round(float(v), 5) for v in xs],
            'y': [round(float(v), 5) for v in iso.predict(xs)],
            'n_train': int(len(sub)),
            'desplazamiento_medio': round(
                float(np.mean(iso.predict(sub['prob'].to_numpy())
                              - sub['prob'].to_numpy())), 5)}
        logger.info('  banda %s: n=%d, desplaza %+.4f en media', b, len(sub),
                    doc['bandas'][str(b)]['desplazamiento_medio'])

    with open(ARTEFACTO, 'w', encoding='utf-8') as f:
        json.dump(doc, f, ensure_ascii=False)
    global _TABLA
    _TABLA = doc
    return doc


def medir(doc: Optional[Dict] = None) -> Dict:
    """Antes y después, por banda, SIN FUGA: cada pliegue con la curva previa."""
    doc = doc or cargar()
    d = _datos()
    filas = []

    for b in sorted(str(x) for x in d['banda_cuota'].dropna().unique()):
        sub = d[d.banda_cuota == b]
        p_raw = sub['prob'].to_numpy(dtype=float)
        y = sub['acierto'].to_numpy(dtype=int)
        cuota = sub['cuota'].to_numpy(dtype=float)
        pliegue = sub['pliegue'].to_numpy(dtype=int)

        # calibrar cada fila con la curva del pliegue ANTERIOR
        p_cal = p_raw.copy()
        n_cal = 0
        for k in sorted(set(pliegue.tolist())):
            curva = ((doc.get('por_pliegue') or {}).get(str(k)) or {}).get(b)
            if not curva:
                continue
            m = pliegue == k
            p_cal[m] = np.clip(np.interp(p_raw[m], curva['x'], curva['y']),
                               0.001, 0.999)
            n_cal += int(m.sum())

        # ROI: el pick sólo se juega si la probabilidad supera el precio justo.
        # Es donde la calibración puede cambiar algo, porque el ORDEN no cambia
        # pero el UMBRAL efectivo sí.
        justo = 1.0 / cuota
        gan = np.where(y == 1, cuota - 1.0, -1.0)
        sel_raw = p_raw > justo
        sel_cal = p_cal > justo

        filas.append({
            'banda': b, 'n': int(len(sub)), 'n_calibrados': n_cal,
            'hit_real': float(y.mean()),
            'prob_antes': float(p_raw.mean()),
            'prob_despues': float(p_cal.mean()),
            'calib_antes': float(y.mean() - p_raw.mean()),
            'calib_despues': float(y.mean() - p_cal.mean()),
            'brier_antes': _brier(p_raw, y), 'brier_despues': _brier(p_cal, y),
            'ece_antes': _ece(p_raw, y), 'ece_despues': _ece(p_cal, y),
            'n_apostados_antes': int(sel_raw.sum()),
            'n_apostados_despues': int(sel_cal.sum()),
            'roi_antes': float(gan[sel_raw].mean()) if sel_raw.any() else None,
            'roi_despues': float(gan[sel_cal].mean()) if sel_cal.any() else None,
            'p5_antes': _p5(gan[sel_raw]) if sel_raw.any() else None,
            'p5_despues': _p5(gan[sel_cal]) if sel_cal.any() else None,
        })
    return {'filas': filas, 'generado': doc.get('generado')}


# ---------------------------------------------------------------------------
def veredicto(med: Dict) -> Dict:
    """La regla dura del encargo: sólo cuenta si mejora en 1,80-2,20."""
    obj = next((f for f in med['filas'] if f['banda'] == BANDA_OBJETIVO), None)
    if not obj:
        return {'activa': False, 'motivo': 'no hay datos en la banda objetivo'}
    fallos = []
    if obj['brier_despues'] is None or obj['brier_antes'] is None:
        fallos.append('Brier no medible')
    elif obj['brier_despues'] > obj['brier_antes']:
        fallos.append(f"el Brier empeora en {BANDA_OBJETIVO} "
                      f"({obj['brier_despues']:.4f} vs {obj['brier_antes']:.4f})")
    if obj['ece_despues'] is not None and obj['ece_antes'] is not None \
            and obj['ece_despues'] > obj['ece_antes']:
        fallos.append(f"el ECE empeora ({obj['ece_despues']:.4f} vs "
                      f"{obj['ece_antes']:.4f})")
    if abs(obj['calib_despues']) > abs(obj['calib_antes']):
        fallos.append('la sobreconfianza no se reduce')
    return {'activa': not fallos, 'fallos': fallos,
            'banda': BANDA_OBJETIVO,
            'motivo': ('mejora la calibración en la banda objetivo'
                       if not fallos else '; '.join(fallos))}


def _f(v, dec=4, pct=False):
    if v is None:
        return '—'
    return f'{v*100:+.2f} %' if pct else f'{v:.{dec}f}'


def escribir_md(med: Dict, ver: Dict, ruta: str = SALIDA_MD) -> None:
    L = ['# Fase A — calibración por banda de cuota\n',
         f"Generado por `calibrador_bandas.py` el {med.get('generado')}.\n",
         '## Qué puede y qué no puede hacer esto\n',
         'La isotónica es **monótona**: no cambia el orden de los picks, así '
         'que **no puede descubrir apuestas buenas**. Lo que hace es arreglar '
         'el Brier y el ECE —que el número enseñado signifique lo que dice— y '
         '**impedir apuestas malas**, porque al bajar la probabilidad en la '
         'banda sobreconfiada, los picks que antes cruzaban el listón de EV '
         'dejan de cruzarlo. No crea ventaja: evita pérdidas.\n',
         '## Sin fuga\n',
         'Cada pliegue se calibra con la curva ajustada **sólo con los '
         'pliegues anteriores**. El pliegue 0 no tiene pasado y se queda sin '
         'calibrar; por eso `n calibrados` es menor que `n`.\n',
         '## Calibración: antes y después\n',
         '| banda | n | calibrados | hit real | prob. antes | prob. después | '
         'sesgo antes | sesgo después |',
         '|---|---|---|---|---|---|---|---|']
    for f in med['filas']:
        L.append(f"| {f['banda']} | {f['n']:,} | {f['n_calibrados']:,} | "
                 f"{f['hit_real']:.1%} | {f['prob_antes']:.1%} | "
                 f"{f['prob_despues']:.1%} | {f['calib_antes']:+.3f} | "
                 f"{f['calib_despues']:+.3f} |".replace(',', '.'))

    L += ['', '## Brier y ECE\n',
          '| banda | Brier antes | Brier después | ECE antes | ECE después |',
          '|---|---|---|---|---|']
    for f in med['filas']:
        L.append(f"| {f['banda']} | {_f(f['brier_antes'])} | "
                 f"{_f(f['brier_despues'])} | {_f(f['ece_antes'])} | "
                 f"{_f(f['ece_despues'])} |")

    L += ['', '## Efecto sobre la selección y el ROI\n',
          'Se apuesta sólo cuando la probabilidad supera el precio justo '
          '(`p > 1/cuota`). Ahí es donde la calibración cambia algo: el orden '
          'no varía, pero el umbral efectivo sí.\n',
          '| banda | apostados antes | apostados después | ROI antes | '
          'ROI después | p5 antes | p5 después |',
          '|---|---|---|---|---|---|---|']
    for f in med['filas']:
        L.append(f"| {f['banda']} | {f['n_apostados_antes']:,} | "
                 f"{f['n_apostados_despues']:,} | "
                 f"{_f(f['roi_antes'], pct=True)} | "
                 f"{_f(f['roi_despues'], pct=True)} | "
                 f"{_f(f['p5_antes'], pct=True)} | "
                 f"{_f(f['p5_despues'], pct=True)} |".replace(',', '.'))

    L += ['', f'## Veredicto en la banda objetivo ({BANDA_OBJETIVO})\n',
          ('**La calibración se acepta.** ' + ver['motivo'] if ver['activa']
           else '**La calibración NO se acepta.** ' + ver['motivo']) + '\n',
          'La regla del encargo es dura y es la correcta: mejorar el ROI '
          'global no basta, porque podría venir de las cuotas cortas. Sólo '
          f'cuenta si mueve la aguja en {BANDA_OBJETIVO}.\n',
          '## Estado\n',
          f'`USAR_CALIBRACION` arranca en **False**. El interruptor vive en '
          f'`calibrador_bandas.py` y lo lee `modo_seguridad.evaluar()`.\n']
    with open(ruta, 'w', encoding='utf-8') as f:
        f.write('\n'.join(L))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--medir', action='store_true')
    a = ap.parse_args()

    doc = cargar() if a.medir else entrenar()
    if not doc.get('bandas'):
        print('sin artefacto: corre sin --medir para entrenar')
        return 1

    med = medir(doc)
    ver = veredicto(med)

    print('\n=== CALIBRACIÓN POR BANDA (sin fuga) ===')
    print('%-12s %8s %8s  %8s %8s  %9s %9s' % (
        'banda', 'n', 'calibr', 'sesgo→', 'sesgo←', 'ECE→', 'ECE←'))
    for f in med['filas']:
        print('%-12s %8d %8d  %+8.3f %+8.3f  %9.4f %9.4f' % (
            f['banda'], f['n'], f['n_calibrados'], f['calib_antes'],
            f['calib_despues'], f['ece_antes'] or 0, f['ece_despues'] or 0))

    print('\n=== SELECCIÓN Y ROI ===')
    for f in med['filas']:
        print('%-12s apostados %6d -> %6d   ROI %s -> %s' % (
            f['banda'], f['n_apostados_antes'], f['n_apostados_despues'],
            _f(f['roi_antes'], pct=True), _f(f['roi_despues'], pct=True)))

    print(f'\n=== VEREDICTO EN {BANDA_OBJETIVO} ===')
    print(' ', 'ACEPTADA' if ver['activa'] else 'RECHAZADA', '·', ver['motivo'])

    escribir_md(med, ver)
    print(f'\n-> {ARTEFACTO}\n-> {SALIDA_MD}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
