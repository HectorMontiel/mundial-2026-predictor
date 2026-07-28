#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v75 — Recalibración del encogimiento hacia el mercado (`calibracion_mercado.json`).

Qué se corrige de la v71
------------------------
La v71 detectó la maldición del ganador (la probabilidad del lado ELEGIDO está
inflada aunque el vector completo esté calibrado) y la corrigió encogiendo
hacia Pinnacle: `p_final = w·p_modelo + (1−w)·p_mercado`. Pero `w` se dedujo de
**315 selecciones con cuota vigente, 4-11 partidos por liga**. Con 4 partidos
el propio sesgo está mal medido, y el peso que sale de él es ruido con formato
de decimal.

Ahora hay `pick_ledger.csv`: miles de predicciones fuera de muestra con el
vector completo y la cuota de cierre. Con eso `w` deja de deducirse de una
fórmula y se ELIGE MIDIENDO.

Por qué no se usa la fórmula del plan
-------------------------------------
El plan de la v75 proponía `w = 1 − |sesgo| / max(|sesgo|, 0.01)`. Esa
expresión vale 0 para cualquier sesgo ≥ 0,01 (es decir, anula el modelo entero
en cuanto hay un punto de sesgo) y se dispara a valores muy negativos por
debajo. No es utilizable. Y aun arreglada, cualquier fórmula cerrada supone una
relación entre sesgo y peso óptimo que nadie ha comprobado.

Método adoptado
---------------
1. `p_mercado` = cierre de Pinnacle devigado (método potencia/Shin, que corrige
   el sesgo favorito-perdedor mejor que el proporcional); respaldo: cierre de
   mercado.
2. Para cada liga se barre `w ∈ [0.45, 1.00]` y se mide la **log-loss** del
   vector encogido — no el sesgo. La log-loss es lo que de verdad queremos
   bajar: premia estar bien calibrado en TODO el vector, no solo en el argmax.
3. **Selección y evaluación separadas en el tiempo**: `w` se elige con los
   pliegues antiguos y se juzga en el último pliegue, que no participó.
4. **Encogimiento jerárquico**: el `w` de cada liga se mezcla con el `w` global
   con peso `n/(n+n0)`. Es la respuesta directa a la lección de `edge_engine`
   ("el mapa por liga NO es estacionario y sobreajusta"): con pocos partidos la
   liga hereda el valor global y solo se separa cuando tiene datos para
   justificarlo.
5. **Regla de adopción**: solo se guarda el `w` de una liga si en el pliegue de
   evaluación mejora la log-loss ≥ 0,005 sin empeorar la precisión, o mejora la
   precisión ≥ 0,5 pp sin empeorar la log-loss.

Uso:
    python recalibrate_from_history.py            # mide, valida y escribe
    python recalibrate_from_history.py --dry-run  # solo mide
"""

import argparse
import datetime as dt
import json
import logging
import sys
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

# La consola de Windows es cp1252 y reventaba al imprimir flechas y
# vistos. Se fuerza UTF-8 en la salida en vez de mutilar los mensajes.
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

logger = logging.getLogger(__name__)

LEDGER = 'pick_ledger.csv'
ARCHIVO = 'calibracion_mercado.json'
SALIDA_DIAG = '_v75_recalibracion.json'

# v75: el suelo lo fija `calibracion_mercado` (0.25 tras medir el ROI por
# peso; ver su comentario). Se importa para que no puedan divergir.
import calibracion_mercado as _cm
W_MIN, W_MAX = _cm.W_MIN, 1.00
REJILLA_W = np.round(np.arange(W_MIN, W_MAX + 1e-9, 0.05), 2)
N0_ENCOGIMIENTO = 150      # partidos a los que la liga pesa igual que el global
MIN_PARTIDOS = 60
# Regla de oro del proyecto
MEJORA_LOGLOSS = 0.005
MEJORA_ACC = 0.005


def _ahora() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')


def devig_potencia(cuotas: np.ndarray) -> np.ndarray:
    """
    Probabilidades justas por el método de potencia (Shin simplificado):
    busca k tal que Σ (1/cuota)^k = 1. Vectorizado sobre filas.

    Se prefiere al proporcional porque reparte el margen castigando más al
    favorito, que es el sesgo real de los mercados a 3 vías — usar
    proporcional infla al favorito y contaminaría el `w` de las ligas con
    favoritos muy marcados.
    """
    imp = 1.0 / np.clip(cuotas, 1.0001, None)
    lo = np.full(len(imp), 0.5)
    hi = np.full(len(imp), 1.5)
    for _ in range(40):
        mid = (lo + hi) / 2
        tot = (imp ** mid[:, None]).sum(axis=1)
        subir = tot > 1
        lo = np.where(subir, mid, lo)
        hi = np.where(subir, hi, mid)
    k = ((lo + hi) / 2)[:, None]
    out = imp ** k
    return out / out.sum(axis=1, keepdims=True)


def cargar(ledger: str = LEDGER) -> pd.DataFrame:
    d = pd.read_csv(ledger)
    tiene_pin = d[['pin_home', 'pin_draw', 'pin_away']].notna().all(axis=1)
    tiene_mer = d[['cuota_home', 'cuota_draw', 'cuota_away']].notna().all(axis=1)
    d = d[tiene_pin | tiene_mer].copy()
    cuotas = np.where(
        tiene_pin[tiene_pin | tiene_mer].values[:, None],
        d[['pin_home', 'pin_draw', 'pin_away']].fillna(2.0).values,
        d[['cuota_home', 'cuota_draw', 'cuota_away']].fillna(2.0).values)
    p_mkt = devig_potencia(cuotas.astype(float))
    d['m_home'], d['m_draw'], d['m_away'] = p_mkt[:, 0], p_mkt[:, 1], p_mkt[:, 2]
    d['ancla'] = np.where(tiene_pin[tiene_pin | tiene_mer].values,
                          'pinnacle', 'mercado')
    return d


def _metricas(d: pd.DataFrame, w: float) -> Tuple[float, float, float]:
    """(log-loss, precisión, sesgo del pick) del vector encogido con peso w."""
    pm = d[['p_home', 'p_draw', 'p_away']].values
    mk = d[['m_home', 'm_draw', 'm_away']].values
    p = w * pm + (1 - w) * mk
    p = np.clip(p, 1e-9, None)
    p = p / p.sum(axis=1, keepdims=True)
    y = d['resultado'].values.astype(int)
    ll = float(-np.log(p[np.arange(len(y)), y]).mean())
    pick = p.argmax(axis=1)
    acc = float((pick == y).mean())
    sesgo = float((p[np.arange(len(p)), pick] - mk[np.arange(len(mk)), pick]).mean())
    return ll, acc, sesgo


def _mejor_w(d: pd.DataFrame) -> Tuple[float, float]:
    """w que minimiza la log-loss en `d`, y esa log-loss."""
    mejor, mejor_ll = 1.0, float('inf')
    for w in REJILLA_W:
        ll, _, _ = _metricas(d, float(w))
        if ll < mejor_ll - 1e-12:
            mejor, mejor_ll = float(w), ll
    return mejor, mejor_ll


def analizar(ledger: str = LEDGER) -> dict:
    d = cargar(ledger)
    pliegues = sorted(d['pliegue'].unique())
    if len(pliegues) < 2:
        raise RuntimeError('el ledger necesita al menos 2 pliegues')
    ultimo = pliegues[-1]
    sel = d[d['pliegue'] < ultimo]            # selección de w
    val = d[d['pliegue'] == ultimo]           # evaluación honesta

    w_global, _ = _mejor_w(sel)
    logger.info(f"w GLOBAL elegido en {len(sel)} partidos de selección: {w_global}")

    ligas, adoptadas = {}, []
    for clave, g_sel in sel.groupby('liga'):
        g_val = val[val['liga'] == clave]
        n = len(g_sel)
        if n < MIN_PARTIDOS or len(g_val) < 25:
            continue
        w_liga, _ = _mejor_w(g_sel)
        # encogimiento jerárquico hacia el global
        lam = n / (n + N0_ENCOGIMIENTO)
        w = float(np.clip(round(lam * w_liga + (1 - lam) * w_global, 3), W_MIN, W_MAX))

        ll0, acc0, sesgo0 = _metricas(g_val, 1.0)     # sin corregir
        ll1, acc1, sesgo1 = _metricas(g_val, w)       # con w
        mejora_ll = ll0 - ll1
        mejora_acc = acc1 - acc0
        adopta = (w < 1.0) and (
            (mejora_ll >= MEJORA_LOGLOSS and mejora_acc >= -1e-9) or
            (mejora_acc >= MEJORA_ACC and mejora_ll >= -1e-9))
        info = {
            'w': w, 'w_crudo_liga': w_liga, 'lambda': round(lam, 3),
            'n_seleccion': int(n), 'n_validacion': int(len(g_val)),
            'sesgo_pick_sin_w': round(sesgo0, 4),
            'sesgo_pick_con_w': round(sesgo1, 4),
            'logloss_sin_w': round(ll0, 4), 'logloss_con_w': round(ll1, 4),
            'delta_logloss': round(mejora_ll, 4),
            'acc_sin_w': round(acc0, 4), 'acc_con_w': round(acc1, 4),
            'delta_acc': round(mejora_acc, 4),
            'adoptada': bool(adopta),
            'ancla': g_sel['ancla'].mode().iat[0] if len(g_sel) else None,
        }
        ligas[clave] = info
        if adopta:
            adoptadas.append(clave)

    # métricas globales en el pliegue de validación con los w adoptados
    def _global(usar_w: bool) -> Tuple[float, float]:
        lls, accs, pesos = [], [], []
        for clave, g in val.groupby('liga'):
            w = ligas.get(clave, {}).get('w', 1.0) if usar_w else 1.0
            if usar_w and not ligas.get(clave, {}).get('adoptada'):
                w = 1.0
            ll, acc, _ = _metricas(g, float(w))
            lls.append(ll * len(g)); accs.append(acc * len(g)); pesos.append(len(g))
        t = sum(pesos)
        return sum(lls) / t, sum(accs) / t

    ll_antes, acc_antes = _global(False)
    ll_despues, acc_despues = _global(True)

    diag = {
        'generado': _ahora(),
        'metodo': 'w por log-loss fuera de muestra + encogimiento jerárquico '
                  'hacia el w global; validado en el último pliegue, que no '
                  'participa en la selección.',
        'w_global': w_global,
        'n_total': int(len(d)), 'n_seleccion': int(len(sel)),
        'n_validacion': int(len(val)),
        'ligas_evaluadas': len(ligas), 'ligas_adoptadas': len(adoptadas),
        'validacion': {
            'logloss_antes': round(ll_antes, 4),
            'logloss_despues': round(ll_despues, 4),
            'delta_logloss': round(ll_antes - ll_despues, 4),
            'acc_antes': round(acc_antes, 4),
            'acc_despues': round(acc_despues, 4),
            'delta_acc': round(acc_despues - acc_antes, 4),
        },
        'por_liga': ligas,
    }
    with open(SALIDA_DIAG, 'w', encoding='utf-8') as f:
        json.dump(diag, f, ensure_ascii=False, indent=1)
    return diag


def escribir(diag: dict, archivo: str = ARCHIVO) -> dict:
    """Vuelca a `calibracion_mercado.json` SOLO las ligas que pasaron la regla."""
    ligas = {k: {'w': v['w'], 'sesgo_pick': v['sesgo_pick_sin_w'],
                 'n_partidos': v['n_seleccion'] + v['n_validacion'],
                 'delta_logloss': v['delta_logloss'],
                 'delta_acc': v['delta_acc'], 'ancla': v['ancla']}
             for k, v in diag['por_liga'].items() if v['adoptada']}
    salida = {
        'generado': diag['generado'],
        'nota': 'v75. Peso del modelo frente al cierre devigado (Pinnacle, '
                'método potencia). Elegido por log-loss fuera de muestra con '
                'encogimiento jerárquico hacia el w global y validado en un '
                'pliegue que no participó en la selección. Liga ausente = w=1 '
                '= sin corrección. Sustituye a los w de la v71, que salían de '
                '4-11 partidos por liga.',
        'w_global': diag['w_global'],
        'global': diag['validacion'],
        'ligas': ligas,
    }
    with open(archivo, 'w', encoding='utf-8') as f:
        json.dump(salida, f, ensure_ascii=False, indent=1)
    try:
        import calibracion_mercado
        calibracion_mercado._CACHE.pop('datos', None)
    except Exception:
        pass
    return salida


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--ledger', default=LEDGER)
    args = ap.parse_args()
    diag = analizar(args.ledger)
    v = diag['validacion']
    print(f"\nw global: {diag['w_global']}   ligas evaluadas: "
          f"{diag['ligas_evaluadas']}   adoptadas: {diag['ligas_adoptadas']}")
    print(f"Validación (pliegue no usado en la selección, {diag['n_validacion']} partidos):")
    print(f"   log-loss {v['logloss_antes']} → {v['logloss_despues']} "
          f"(Δ {v['delta_logloss']:+.4f})")
    print(f"   precisión {v['acc_antes']} → {v['acc_despues']} "
          f"(Δ {v['delta_acc']:+.4f})")
    print("\n  liga                    w     n     Δlogloss  Δacc    sesgo→")
    for k, x in sorted(diag['por_liga'].items(),
                       key=lambda kv: -kv[1]['delta_logloss']):
        marca = '✔' if x['adoptada'] else ' '
        print(f" {marca} {k:22s} {x['w']:.2f} {x['n_seleccion']:5d} "
              f"{x['delta_logloss']:+9.4f} {x['delta_acc']:+7.4f}  "
              f"{x['sesgo_pick_sin_w']:+.3f}→{x['sesgo_pick_con_w']:+.3f}")
    if not args.dry_run:
        s = escribir(diag)
        print(f"\n{ARCHIVO} actualizado con {len(s['ligas'])} ligas.")
