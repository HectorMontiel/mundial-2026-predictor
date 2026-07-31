#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v86 — Encogimiento hacia un prior de ELO para la FICHA de partido.

El problema que resuelve
------------------------
El usuario reportó que la ficha de Liga MX hacía favorito a Puebla (54 %) sobre
Chivas teniendo TODO en contra: ELO 1349 vs 1597, forma 0,17 vs 0,58, encaja
2,17 vs 1,00, H2H −0,67.

Se midió por tres vías y sólo la tercera es válida:

  · v85, correlación sobre emparejamientos SINTÉTICOS de los 14 mejores equipos
    de cada liga: 32 ligas "rotas", 4 invertidas. Es un artefacto: al quedarse
    con los 14 mejores se comprime el rango de ELO mientras la forma sigue
    variando a rango completo, así que la correlación mide la forma.

  · v86, correlación sobre el ledger REAL: mediana rho +0,76, ninguna liga
    invertida. Engañoso al revés: en partidos reales el ELO va correlacionado
    con la forma y los goles, así que P(local) parece seguir al ELO aunque el
    modelo no lo esté usando.

  · v86, DEPENDENCIA PARCIAL: se mueve SÓLO el ELO y se congela el resto. Es
    causal dentro del modelo y no la falsea ni el rango ni la colinealidad:

        subir 600 puntos de ELO mueve P(local) +0,0751 de MEDIANA
        15 ligas planas (|salto| <= 0,02) · 2 invertidas
        liga_mx +0,0173   <- el caso Puebla

    El modelo apenas responde a la fuerza. El usuario tenía razón.

La corrección
-------------
    p_final = w · p_modelo + (1 − w) · p_elo

`p_elo` sale de una logística multinomial con una ÚNICA variable, DIFF_ELO. Con
una sola variable el orden local/visitante es monótono por construcción, que es
justo la propiedad que le falta al modelo grande.

Dónde se aplica y dónde NO
--------------------------
SÓLO en la ficha de partido, que es donde el modelo va suelto. Cuando hay
mercado, `calibracion_mercado` ya encoge hacia él y ésa es la corrección buena;
`alpha_finder` desactiva ésta explícitamente (`prior_elo=False`) para que los
picks de Capa 1 y Capa 2 salgan idénticos a antes.

Cómo se eligió w = 0,90
-----------------------
Sobre las 9.870 filas del ledger SIN ancla de mercado (la población de la
ficha), eligiendo en los pliegues 1-2 y validando en los 3-4:

                       elección        VALIDACIÓN
    w=1,00 (hoy)   ll 1,04189 ECE 0,0111   ll 1,04769 ECE 0,0106  prec 0,4771
    w=0,90         ll 1,03692 ECE 0,0090   ll 1,03789 ECE 0,0045  prec 0,4797

    mejora en validación: log-loss +0,00979 · ECE +0,0061 · precisión +0,0026

El ECE cae un 58 %. Se elige por ECE y no por log-loss a propósito: la ficha
MUESTRA una probabilidad, así que lo que importa es que ese número sea fiel.
El máximo del barrido era w=0,50, que da mejor log-loss en validación (1,03022)
pero PEOR ECE (0,0090): es justo la trampa de quedarse con el extremo de la
rejilla que este proyecto ya ha pagado tres veces.
"""
import json
import logging
import os
from typing import Dict, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

ARCHIVO = 'calibracion_elo.json'

# Peso del modelo frente al prior de ELO. 1.0 = sin corrección.
W_FICHA = 0.90

_CACHE: dict = {}


def _tabla() -> dict:
    if _CACHE.get('cargado'):
        return _CACHE
    _CACHE['cargado'] = True
    _CACHE['coef'] = None
    try:
        if os.path.exists(ARCHIVO):
            with open(ARCHIVO, encoding='utf-8') as f:
                _CACHE['coef'] = json.load(f)
    except Exception as e:
        logger.warning(f'calibracion_elo: no se pudo leer {ARCHIVO}: {e}')
    return _CACHE


def hay_prior() -> bool:
    """¿Está disponible el prior? Si no, no se toca nada."""
    c = _tabla().get('coef')
    return bool(c and c.get('coeficientes') and c.get('intercepto'))


def prior(diff_elo: float) -> Optional[Dict[str, float]]:
    """
    P(local/empate/visitante) que implica SOLO la diferencia de ELO.

    `diff_elo` es (ELO_local − ELO_visitante)/400, la misma escala que usa
    `feature_engineering.vector_features`.
    """
    c = _tabla().get('coef')
    if not hay_prior():
        return None
    try:
        b = np.array(c['coeficientes'], dtype=float)     # (3,)
        a = np.array(c['intercepto'], dtype=float)       # (3,)
        z = a + b * float(diff_elo)
        z = z - z.max()
        e = np.exp(z)
        p = e / e.sum()
        return {'home': float(p[0]), 'draw': float(p[1]), 'away': float(p[2])}
    except Exception as e:
        logger.warning(f'calibracion_elo.prior: {e}')
        return None


def corregir(probs: Dict[str, float], diff_elo: Optional[float],
             w: float = W_FICHA) -> Tuple[Dict[str, float], dict]:
    """
    Encoge las probabilidades del modelo hacia el prior de ELO.

    Devuelve (probabilidades, info). Si no hay prior o no hay ELO, devuelve las
    de entrada intactas y `aplicado=False`: esta corrección nunca debe tumbar
    una predicción ni inventarse un número.
    """
    info = {'aplicado': False, 'w': w, 'motivo': None}
    if diff_elo is None or not np.isfinite(diff_elo):
        info['motivo'] = 'sin ELO'
        return probs, info
    if w >= 1.0:
        info['motivo'] = 'w=1 (desactivado)'
        return probs, info
    pe = prior(diff_elo)
    if not pe:
        info['motivo'] = 'sin tabla de prior'
        return probs, info
    try:
        out = {k: w * float(probs.get(k, 0.0)) + (1 - w) * pe[k]
               for k in ('home', 'draw', 'away')}
        s = sum(out.values())
        if s <= 0:
            info['motivo'] = 'suma nula'
            return probs, info
        out = {k: v / s for k, v in out.items()}
        info.update(aplicado=True, prior=pe, diff_elo=float(diff_elo),
                    antes=dict(probs))
        return out, info
    except Exception as e:
        info['motivo'] = f'{type(e).__name__}: {e}'
        return probs, info


# ---------------------------------------------------------------------------
# Generación de la tabla (offline, desde el ledger)
# ---------------------------------------------------------------------------
def generar(ledger: str = 'pick_ledger_total.csv',
            elo: str = 'elo_por_partido.csv') -> dict:
    """Ajusta el prior de ELO sobre el ledger completo y lo guarda."""
    import pandas as pd
    from sklearn.linear_model import LogisticRegression

    led = pd.read_csv(ledger)
    e = pd.read_csv(elo)
    d = (led[led['deporte'] == 'Fútbol']
         .merge(e, on=['liga', 'match_id'], how='inner')
         .dropna(subset=['diff_elo', 'resultado']))
    if len(d) < 1000:
        raise RuntimeError(f'muestra insuficiente: {len(d)}')

    X = d['diff_elo'].values.reshape(-1, 1)
    y = d['resultado'].values.astype(int)
    m = LogisticRegression(max_iter=1000)
    m.fit(X, y)

    # se ordenan los coeficientes a 0=local, 1=empate, 2=visitante
    coef = np.zeros(3)
    inter = np.zeros(3)
    for i, k in enumerate(m.classes_):
        coef[int(k)] = m.coef_[i, 0]
        inter[int(k)] = m.intercept_[i]

    salida = {
        'generado': pd.Timestamp.today().strftime('%Y-%m-%d'),
        'n_partidos': int(len(d)),
        'w_ficha': W_FICHA,
        'coeficientes': [float(x) for x in coef],
        'intercepto': [float(x) for x in inter],
        'nota': ('logística multinomial con una única variable (DIFF_ELO), '
                 'monótona por construcción; w elegido en los pliegues 1-2 y '
                 'validado en los 3-4 sobre las filas SIN ancla de mercado'),
    }
    with open(ARCHIVO, 'w', encoding='utf-8') as f:
        json.dump(salida, f, ensure_ascii=False, indent=1)
    _CACHE.clear()
    return salida


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    r = generar()
    print(json.dumps(r, ensure_ascii=False, indent=1))
    print('\ncomprobación de monotonía del prior:')
    for de in (-0.75, -0.50, -0.25, 0.0, 0.25, 0.50, 0.75):
        p = prior(de)
        print(f'  DIFF_ELO {de:+.2f} ({de * 400:+.0f} pts) -> '
              f"local {p['home']:.3f} · empate {p['draw']:.3f} · "
              f"visitante {p['away']:.3f}")
