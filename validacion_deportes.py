#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v78 — Qué DEPORTES tienen edge validado para la Capa 1.

El hallazgo
-----------
Extender la calibración a tenis y MLB (v78) permitió medir por primera vez su
rentabilidad fuera de muestra. El resultado obliga a separar dos cosas que
hasta ahora iban juntas:

  1. **Calidad de la probabilidad.** El encogimiento hacia el mercado mejora la
     log-loss y la precisión en los TRES deportes, de forma monótona:
         Tenis  log-loss 0,6109 → 0,5842 · precisión 65,86 % → 68,31 %
         MLB    log-loss 0,6817 → 0,6692 · precisión 56,03 % → 59,38 %
     Eso es real y se adopta: las probabilidades que ve el usuario mejoran.

  2. **Rentabilidad de la SELECCIÓN.** Es otra pregunta, y la respuesta es
     distinta según el deporte. Barriendo el peso de 1,00 a 0,25 con los
     umbrales de producción:

         Fútbol  mejor ROI +3,93 % (n=1.001, p5 −1,44 %)  → edge
         Tenis   NEGATIVO de w=1,00 a w=0,30 (−5,03 % con 3.666 apuestas);
                 solo +12,91 % en w=0,25, pero con 44 picks y p5 −4,66 %
         MLB     mejor +3,46 % en w=1,00 (n=394, p5 −4,14 %), y empeora al
                 encoger

     Ni el tenis ni la MLB alcanzan un ROI robusto con NINGÚN peso. El tenis
     llevaba emitiendo picks que perdían un 5 % sostenido sobre 3.666 apuestas.

Qué se hace
-----------
Lo mismo que la v44 hizo con Over/Under 2.5 cuando su bootstrap p5 salió
negativo: **fuera de la Capa 1 accionable**. Los picks siguen calculándose y
mostrándose como candidatos, con la etiqueta honesta de que ese deporte no
tiene edge validado — pero dejan de presentarse como apuestas de élite.

No es una decisión de producto, es la regla de oro del proyecto aplicada sin
excepciones: solo se despliega lo que supera la validación. Y el criterio se
recalcula con `python validacion_deportes.py` cada vez que crezca el ledger,
así que en cuanto el tenis o la MLB pasen la regla, vuelven solos.
"""

import datetime as dt
import json
import logging
import os
import sys
from typing import Dict, Optional

import numpy as np

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

logger = logging.getLogger(__name__)

ARCHIVO = 'deportes_capa1.json'
LEDGER = 'pick_ledger_total.csv'
MIN_APUESTAS = 100
SEMILLA = 20260728
_CACHE: Dict[str, dict] = {}


def _tabla() -> dict:
    if 'datos' not in _CACHE:
        datos = {}
        try:
            if os.path.exists(ARCHIVO):
                with open(ARCHIVO, encoding='utf-8') as f:
                    datos = json.load(f)
        except Exception as e:
            logger.warning(f"[deportes] no se pudo leer {ARCHIVO}: {e}")
        _CACHE['datos'] = datos
    return _CACHE['datos']


def tiene_edge(deporte: Optional[str]) -> bool:
    """
    ¿Ese deporte puede entrar en la Capa 1 accionable?

    Si no hay medición (deporte nuevo, NBA sin cuotas históricas) devuelve
    True: no se castiga por falta de datos, se castiga por evidencia en contra.
    Lo que NO se hace es dar por bueno lo que se midió y salió mal.
    """
    if not deporte:
        return True
    info = (_tabla().get('deportes') or {}).get(deporte)
    if not info:
        return True
    return bool(info.get('edge_validado', True))


def motivo(deporte: Optional[str]) -> Optional[str]:
    """Texto para la UI cuando un deporte queda fuera de la Capa 1."""
    info = (_tabla().get('deportes') or {}).get(deporte or '')
    if not info or info.get('edge_validado', True):
        return None
    # v99 — para el tenis ya no se cita el ledger de producción.
    #
    # Ese mensaje decía «el mejor ROI fue +1,85 % sobre **112 apuestas**», que
    # es la muestra que el propio sistema había acumulado. Con 112 apuestas el
    # intervalo se come cualquier conclusión, así que la frase no informaba de
    # nada. El proyecto tenía el dato bueno sin usar: el histórico unificado
    # trae **63.821 partidos de ATP y 44.836 de WTA con cuota de cierre**
    # (2001-2026). Medido ahí, con elección en pliegues tempranos y juicio en
    # los tardíos (`_v99_edge_tenis.py`), el veredicto es mucho más firme —y
    # peor—: ninguna regla del barrido sale positiva.
    if (deporte or '').lower() in ('tenis', 'atp', 'wta'):
        return ("Tenis: sin edge de modelo, y medido a lo grande. Sobre "
                "108.657 partidos con cuota de cierre real (2001-2026), la "
                "probabilidad del modelo está PEOR calibrada que la de la casa "
                "(Brier 0,212 frente a 0,198 en ATP), y la mejor regla del "
                "barrido pierde −9,7 % de ROI fuera de muestra (p5 −11,6 %). "
                "No es falta de muestra: es que el precio ya sabe más. Se "
                "muestran como candidatos, nunca como apuestas de élite.")
    return (f"{deporte}: sin edge validado. Con los umbrales actuales, el mejor "
            f"ROI fuera de muestra fue {info['mejor_roi']:+.2%} sobre "
            f"{info['n_mejor']} apuestas (bootstrap p5 {info['p5_mejor']:+.2%}). "
            f"Se muestran como candidatos, no como apuestas de élite.")


def calcular(ledger: str = LEDGER) -> dict:
    import pandas as pd
    import alpha_finder as af
    import recalibrate_from_history as rec

    d = rec.cargar(ledger)
    rng = np.random.default_rng(SEMILLA)
    umbral = {'Fútbol': 0.55, 'Tenis': af.UMBRAL_CONF.get('Tenis', 0.65),
              'MLB': af.UMBRAL_CONF.get('MLB', 0.58),
              'NBA': af.UMBRAL_CONF.get('NBA', 0.70)}

    salida = {}
    for dep, g in d.groupby('deporte'):
        pmin = umbral.get(dep, 0.55)
        sub = g.dropna(subset=['cuota_home'])
        pm = sub[['p_home', 'p_draw', 'p_away']].values
        mk = sub[['m_home', 'm_draw', 'm_away']].values
        # PRECIO: el mejor disponible, que es lo que hace producción (toma la
        # mejor cuota entre Playdoit, Pinnacle y Bovada). Medir con la media de
        # mercado subestima el ROI real — en la v76 se vio la diferencia:
        # +4,43 % con la media frente a +5,80 % con line shopping. Usar una
        # definición de precio distinta de la de producción haría que el
        # veredicto no correspondiera a lo que el usuario puede tomar.
        cu = np.fmax(
            sub[['cuota_home', 'cuota_draw', 'cuota_away']].fillna(0).values.astype(float),
            np.nan_to_num(sub[['pin_home', 'pin_draw', 'pin_away']].values.astype(float),
                          nan=0.0))
        y = sub['resultado'].values.astype(int)
        f = np.arange(len(sub))
        mejor = None
        curva = []
        for w in (1.0, 0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.25):
            p = w * pm + (1 - w) * mk
            p = p / p.sum(axis=1, keepdims=True)
            k = p.argmax(axis=1)
            prob, cuota = p[f, k], cu[f, k]
            e = cuota * prob - 1
            sel = (prob > pmin) & (e > af.MIN_EV) & (cuota > af.MIN_CUOTA)
            if sel.sum() < MIN_APUESTAS:
                curva.append({'w': w, 'n': int(sel.sum())})
                continue
            pnl = np.where(k[sel] == y[sel], cuota[sel] - 1, -1.0)
            idx = rng.integers(0, len(pnl), size=(2000, len(pnl)))
            p5 = float(np.percentile(pnl[idx].mean(axis=1), 5))
            fila = {'w': w, 'n': int(sel.sum()), 'roi': round(float(pnl.mean()), 4),
                    'p5': round(p5, 4),
                    'hit': round(float((k[sel] == y[sel]).mean()), 4)}
            curva.append(fila)
            if mejor is None or fila['roi'] > mejor['roi']:
                mejor = fila
        if mejor is None:
            salida[dep] = {'edge_validado': True, 'motivo': 'sin muestra suficiente',
                           'curva': curva}
            continue
        # regla de oro: ROI positivo Y bootstrap p5 positivo
        edge = bool(mejor['roi'] > 0 and mejor['p5'] > 0)
        salida[dep] = {
            'edge_validado': edge, 'mejor_w': mejor['w'],
            'mejor_roi': mejor['roi'], 'p5_mejor': mejor['p5'],
            'n_mejor': mejor['n'], 'hit_mejor': mejor['hit'],
            'umbral_prob': pmin, 'curva': curva}

    doc = {
        'generado': dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')
                      .replace('+00:00', 'Z'),
        'regla': 'Un deporte entra en la Capa 1 accionable solo si, con ALGÚN '
                 'peso de calibración, su ROI fuera de muestra es positivo Y su '
                 'bootstrap p5 también. Es la misma regla que dejó fuera el '
                 'Over/Under 2.5 en la v44.',
        'nota': 'Sin medición = se permite. No se castiga la falta de datos, se '
                'castiga la evidencia en contra.',
        'deportes': salida,
    }
    with open(ARCHIVO, 'w', encoding='utf-8') as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    _CACHE.pop('datos', None)
    return doc


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    d = calcular()
    print(f"{'deporte':10s} {'edge':>6s} {'mejor w':>8s} {'ROI':>8s} {'p5':>8s} {'n':>6s}")
    for dep, v in sorted(d['deportes'].items()):
        if 'mejor_roi' not in v:
            print(f"{dep:10s} {'—':>6s}   (muestra insuficiente)")
            continue
        print(f"{dep:10s} {'SÍ' if v['edge_validado'] else 'NO':>6s} "
              f"{v['mejor_w']:8.2f} {v['mejor_roi']:+7.2%} {v['p5_mejor']:+7.2%} "
              f"{v['n_mejor']:6d}")
    fuera = [k for k, v in d['deportes'].items() if not v.get('edge_validado', True)]
    if fuera:
        print(f"\nFuera de la Capa 1 accionable: {', '.join(fuera)}")
        for k in fuera:
            print(f"  · {motivo(k)}")
