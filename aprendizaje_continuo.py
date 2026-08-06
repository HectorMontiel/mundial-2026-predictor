#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v101 — Aprendizaje autónomo: el sistema corrige su propia confianza.

De dónde sale este diseño
-------------------------
La hipótesis original —«aprender del partido anterior: contra quién jugó, si
venía de ganar a uno más fuerte»— se midió en serio (`_v101_ab_contexto_*.py`)
y en fútbol NO se sostiene: sobre 47.948 predicciones fuera de muestra, el
contexto del partido previo no mejora ninguno de los seis mercados una vez que
se controla la diferencia de fuerza de hoy. Está documentado con números en
`VALIDACION_v101.md`, incluido el falso hallazgo que produjo por el camino.

Pero la autopsia de los picks REALES encontró otra cosa, y ésta sí es grande:

    144 picks liquidados · acierto 57,6 % · prometido 68,4 % · brecha −10,8 pp

El sistema no falla al ordenar los partidos: falla al decir CUÁNTO de seguro
está. Eso es un defecto de calibración, y la calibración es exactamente el tipo
de cosa que se puede aprender sola sin peligro, porque:

  · es una función de UN parámetro sobre la propia salida del modelo, no una
    feature nueva que pueda estar correlacionada con vaya usted a saber qué;
  · es monótona: no reordena los partidos, sólo aprieta o afloja la confianza,
    así que no puede convertir un buen pick en malo;
  · degrada a la identidad cuando no hay datos, en vez de a un valor inventado.

Cómo aprende, y por qué es seguro
---------------------------------
Escalado de Platt sobre `logit(p)`, ajustado en TRES niveles jerárquicos —
global, deporte, mercado— y encogido hacia el nivel de arriba en proporción a
la muestra:

    peso = n / (n + N0)          → con n=0 hereda al padre; con n≫N0 manda él

El prior no es plano: es el ledger histórico de más de 47.000 predicciones
fuera de muestra. Los 144 picks de producción no pueden, por construcción,
mover la corrección más que su peso — que hoy es 0,42, no 1. Ésa es la
diferencia entre aprender y sobrerreaccionar.

Además, tres topes duros:

  1. la corrección nunca desplaza una probabilidad más de `TOPE_AJUSTE`;
  2. la pendiente se limita a [0,3 ; 1,5] — fuera de ahí no es recalibrar, es
     otro modelo;
  3. si el ajuste empeora el log-loss en walk-forward, NO se despliega. Eso lo
     decide `_v101_validar_aprendizaje.py`, no este módulo.

Lo que este módulo NO hace
--------------------------
No inventa features, no reentrena modelos y no cambia qué partidos se eligen.
Un lazo autónomo que pudiera hacer eso se sobreajustaría a su propio historial
en pocas semanas. La ampliación de features sigue pasando por A/B con
walk-forward y bootstrap, con una persona mirando — que es como murió, bien
documentada, la hipótesis del contexto previo.

Uso:
    python aprendizaje_continuo.py --ajustar     # reaprende y guarda el mapa
    python aprendizaje_continuo.py               # muestra el mapa vigente
"""
import argparse
import json
import logging
import os
import sys
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

ARCHIVO = 'calibracion_adaptativa.json'
# Fuerza del prior: con `N0` observaciones un nivel pesa la mitad que su padre.
# 200 es el orden de magnitud en el que una tasa de acierto deja de ser ruido
# (error estándar ~3,5 pp cerca de 0,5).
N0 = 200
# Mínimo absoluto para que un nivel tenga voz propia.
MIN_N = 50
# La corrección no puede desplazar una probabilidad más que esto.
TOPE_AJUSTE = 0.15
# La pendiente de Platt se limita: fuera de este rango ya no es recalibrar.
PENDIENTE_MIN, PENDIENTE_MAX = 0.3, 1.5


def _logit(p):
    p = np.clip(np.asarray(p, dtype=float), 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


def _sigmoide(z):
    return 1.0 / (1.0 + np.exp(-np.clip(z, -30, 30)))


def ajustar_platt(p: np.ndarray, y: np.ndarray) -> Tuple[float, float]:
    """
    Pendiente y sesgo que mejor recalibran `p` contra `y`.

    Se ajusta con una logística de una sola variable sobre `logit(p)`. Devuelve
    (a, b) tal que p' = sigmoide(a·logit(p) + b). La identidad es (1, 0).
    """
    from sklearn.linear_model import LogisticRegression
    z = _logit(p).reshape(-1, 1)
    if len(np.unique(y)) < 2 or len(y) < 10:
        return 1.0, 0.0
    m = LogisticRegression(max_iter=1000, C=1e6).fit(z, y)
    a = float(np.clip(m.coef_[0][0], PENDIENTE_MIN, PENDIENTE_MAX))
    return a, float(m.intercept_[0])


def _encoger(hijo: Tuple[float, float], padre: Tuple[float, float],
             n: int, n0: int = N0) -> Tuple[float, float]:
    """Mezcla los parámetros del hijo con los del padre según la muestra."""
    w = n / (n + n0)
    return (w * hijo[0] + (1 - w) * padre[0],
            w * hijo[1] + (1 - w) * padre[1])


def aprender(df: pd.DataFrame, col_p: str, col_y: str,
             niveles: List[str],
             prior: Optional[Tuple[float, float]] = None) -> Dict:
    """
    Mapa de calibración jerárquico.

    `niveles` son las columnas que definen la jerarquía, de más general a más
    específica (p.ej. ['deporte', 'mercado']). El nivel raíz es siempre global.
    Cada nodo hereda de su padre y se separa de él sólo en la medida en que su
    propia muestra lo justifique.

    `prior` es el punto al que se encoge la RAÍZ. Sin él, el nodo global se
    ajusta a pelo con lo que haya —y con 144 picks de producción eso es
    exactamente la sobrerreacción que el encogimiento existe para evitar: los
    nodos hijos se encogían hacia su padre, pero el padre no se encogía hacia
    nada. Cuando se aprende de producción se le pasa la raíz del ledger, que
    son decenas de miles de predicciones. La identidad (1, 0) es el prior por
    defecto: sin datos, no se corrige.
    """
    d = df.dropna(subset=[col_p, col_y]).copy()
    p = pd.to_numeric(d[col_p], errors='coerce').to_numpy(dtype=float)
    y = pd.to_numeric(d[col_y], errors='coerce').to_numpy(dtype=float)
    ok = ~np.isnan(p) & ~np.isnan(y) & (p > 0) & (p < 1)
    p, y, d = p[ok], y[ok], d[ok]

    raiz = _encoger(ajustar_platt(p, y), prior or (1.0, 0.0), len(y))
    mapa = {'global': {'a': raiz[0], 'b': raiz[1], 'n': int(len(y)),
                       'peso_propio': round(len(y) / (len(y) + N0), 3)}}

    def _rama(sub_d, sub_p, sub_y, padre, camino):
        if len(sub_y) < MIN_N:
            return
        prop = ajustar_platt(sub_p, sub_y)
        a, b = _encoger(prop, padre, len(sub_y))
        mapa['|'.join(camino)] = {'a': float(a), 'b': float(b),
                                  'n': int(len(sub_y)),
                                  'peso_propio': round(len(sub_y) /
                                                       (len(sub_y) + N0), 3)}
        return (a, b)

    for i, nivel in enumerate(niveles):
        if nivel not in d.columns:
            continue
        for valor, idx in d.groupby(d[nivel].astype(str)).groups.items():
            m = d.index.isin(idx)
            camino = [nivel, str(valor)]
            padre = raiz
            if i > 0:
                # hereda del nivel inmediatamente superior si ese nodo existe
                sup = niveles[i - 1]
                if sup in d.columns:
                    v_sup = str(d.loc[m, sup].mode().iloc[0]) \
                        if d.loc[m, sup].notna().any() else None
                    nodo = mapa.get(f'{sup}|{v_sup}')
                    if nodo:
                        padre = (nodo['a'], nodo['b'])
            _rama(d[m], p[m], y[m], padre, camino)

    return mapa


def aplicar(prob: float, mapa: Dict, contexto: Optional[Dict] = None) -> float:
    """
    Probabilidad recalibrada. Devuelve `prob` intacta si no hay nada aprendido.

    Busca el nodo más específico que exista para el contexto dado (p.ej.
    {'deporte': 'Tenis', 'mercado': 'Ganador'}) y, si no lo encuentra, sube
    hasta el global. Nunca extrapola a un nodo que no se aprendió.
    """
    if not mapa or prob is None or not (0 < float(prob) < 1):
        return prob
    nodo = mapa.get('global')
    for clave, valor in (contexto or {}).items():
        cand = mapa.get(f'{clave}|{valor}')
        if cand:
            nodo = cand
    if not nodo:
        return prob
    p2 = float(_sigmoide(nodo['a'] * _logit(prob) + nodo['b']))
    # tope duro: la recalibración ajusta la confianza, no reescribe el pronóstico
    return float(np.clip(p2, prob - TOPE_AJUSTE, prob + TOPE_AJUSTE))


def cargar(ruta: str = ARCHIVO) -> Dict:
    if not os.path.exists(ruta):
        return {}
    try:
        return json.load(open(ruta, encoding='utf-8')).get('mapa', {})
    except Exception as e:
        logger.warning(f'[aprendizaje] no se pudo leer {ruta}: {e}')
        return {}


def reaprender(ruta: str = ARCHIVO) -> Dict:
    """
    Reaprende el mapa desde las dos fuentes y lo guarda.

    El ledger histórico da el prior por mercado; los picks publicados aportan
    la corrección de producción, con el peso que les corresponda por muestra.
    """
    fuentes = {}

    # --- prior: predicciones fuera de muestra del ledger de goles ---
    if os.path.exists('pick_ledger_totales.csv'):
        t = pd.read_csv('pick_ledger_totales.csv')
        largo = []
        for mercado, cp_, cy in (('Goles over 1.5', 'p_over_1.5', 'over_1.5_real'),
                                 ('Goles over 2.5', 'p_over_2.5', 'over_2.5_real'),
                                 ('BTTS', 'p_btts', 'btts_real')):
            s = t.dropna(subset=[cp_, cy])[[cp_, cy, 'liga']].copy()
            s.columns = ['p', 'y', 'liga']
            s['mercado'] = mercado
            s['deporte'] = 'Fútbol'
            largo.append(s)
        hist = pd.concat(largo, ignore_index=True)
        fuentes['ledger_goles'] = aprender(hist, 'p', 'y',
                                           ['deporte', 'mercado'])

    # --- producción: lo que se publicó y ya se liquidó ---
    if os.path.exists('picks_historico.csv'):
        d = pd.read_csv('picks_historico.csv')
        d = d[d['resultado'].notna()]
        if len(d) >= MIN_N:
            # la raíz del ledger es el prior de producción: 47.794 predicciones
            # contra 144 picks, y el peso lo decide la muestra, no el optimismo
            raiz_ledger = fuentes.get('ledger_goles', {}).get('global')
            prior = ((raiz_ledger['a'], raiz_ledger['b'])
                     if raiz_ledger else (1.0, 0.0))
            fuentes['produccion'] = aprender(d, 'prob', 'resultado',
                                             ['deporte', 'mercado'],
                                             prior=prior)

    # El mapa vigente es el de PRODUCCIÓN si tiene muestra, con el del ledger
    # de respaldo para los nodos que producción todavía no cubre. Es la única
    # combinación honesta: el ledger mide el modelo, producción mide lo que de
    # verdad se publicó (que incluye Capa 2, line shopping y filtros).
    mapa = dict(fuentes.get('ledger_goles', {}))
    mapa.update(fuentes.get('produccion', {}))

    salida = {'mapa': mapa, 'fuentes': {k: len(v) for k, v in fuentes.items()},
              'n_total': mapa.get('global', {}).get('n', 0),
              'tope_ajuste': TOPE_AJUSTE, 'n0': N0,
              'generado': pd.Timestamp.now('UTC').strftime('%Y-%m-%dT%H:%M:%SZ')}
    from io_atomico import escribir_texto
    escribir_texto(ruta, json.dumps(salida, indent=1, ensure_ascii=False))
    logger.info(f'[aprendizaje] mapa con {len(mapa)} nodos -> {ruta}')
    return salida


def resumen(mapa: Optional[Dict] = None) -> str:
    """Qué está corrigiendo el sistema, en una tabla legible."""
    mapa = mapa if mapa is not None else cargar()
    if not mapa:
        return 'Sin calibración adaptativa aprendida todavía.'
    filas = []
    for clave, nodo in sorted(mapa.items(), key=lambda kv: -kv[1]['n']):
        for p0 in (0.55, 0.65, 0.75):
            pass
        muestras = {p0: aplicar(p0, {'global': nodo}) for p0 in (0.55, 0.65, 0.75)}
        filas.append(f'  {clave:<28} n={nodo["n"]:>6} · a={nodo["a"]:.3f} '
                     f'b={nodo["b"]:+.3f} · '
                     + ' '.join(f'{k:.0%}→{v:.0%}' for k, v in muestras.items()))
    return '\n'.join(filas)


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument('--ajustar', action='store_true',
                    help='reaprende el mapa desde ledger + producción')
    a = ap.parse_args()
    if a.ajustar:
        s = reaprender()
        print(f'nodos: {len(s["mapa"])} · fuentes: {s["fuentes"]}')
    print(resumen())
