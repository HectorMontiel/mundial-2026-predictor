#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v213 — Dónde acierta de verdad el modelo: patrones por liga, mercado y cuota.

DE DÓNDE SALE EL ENCARGO
------------------------
«Checa los patrones, checa si hay ligas donde acierta más, si hay mercados
donde acierta más, si hay equipos donde acierta más.» Y la condición que lo
gobierna todo: **no sirve una cuota 1,10**. Hacen falta cuotas buenas porque
las apuestas van en varias patas y el multiplicador importa.

LA TRAMPA QUE ESTE MÓDULO EXISTE PARA EVITAR
--------------------------------------------
Si se barren 500 segmentos buscando el que más ROI da, **siempre sale uno
bueno**, aunque los datos sean ruido puro. Con 500 pruebas al 5 %, salen 25
«hallazgos» falsos por pura aritmética. Ése es el modo de fallo que convierte
un análisis de patrones en una máquina de perder dinero con convicción.

Así que aquí NO se busca el mejor segmento. Se hace lo que el proyecto ya hace
con sus canales:

    DESCUBRIMIENTO   pliegues 0-3 del ledger. Aquí se eligen los candidatos.
    JUICIO           pliegue 4, que NO se usó para elegir. Aquí se decide.

Un segmento sólo se declara si sobrevive a los dos, y en juicio se exige lo
mismo que a cualquier canal: **percentil 5 de bootstrap positivo**. Un ROI
positivo con p5 negativo es un segmento que ganó en la muestra y no se sabe si
gana fuera de ella — que es exactamente lo que este documento no puede decir.

LA CORRECCIÓN POR MÚLTIPLES PRUEBAS
-----------------------------------
Además del juicio fuera de muestra se aplica Benjamini-Hochberg sobre los
p-valores del descubrimiento. No es redundante: el juicio protege contra el
sobreajuste al tramo, y BH protege contra el número de preguntas hechas.

Uso:
    python patrones_acierto.py                 # informe completo
    python patrones_acierto.py --min-cuota 1.5 # sólo cuotas decentes
"""

import argparse
import datetime as _dt
import json
import logging
import sys
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
logger = logging.getLogger('patrones')

SALIDA_JSON = 'patrones_acierto.json'
SALIDA_MD = 'PATRONES_ACIERTO.md'

LEDGER_1X2 = 'pick_ledger_total.csv'
LEDGER_TOTALES = 'pick_ledger_totales.csv'

PLIEGUES_DESCUBRIMIENTO = (0, 1, 2, 3)
PLIEGUE_JUICIO = 4

N_MINIMO = 150          # por segmento, en descubrimiento
N_MINIMO_JUICIO = 50    # en juicio se admite menos: es un tramo más corto
N_BOOTSTRAP = 2000

# La condición del encargo: nada por debajo de esto es una apuesta útil.
CUOTA_MINIMA_UTIL = 1.50

BANDAS_CUOTA = ((1.20, 1.50), (1.50, 1.80), (1.80, 2.20),
                (2.20, 3.00), (3.00, 6.00))
BANDAS_PROB = ((0.30, 0.45), (0.45, 0.55), (0.55, 0.65),
               (0.65, 0.75), (0.75, 1.00))


# ---------------------------------------------------------------------------
def _p5(g: np.ndarray, n: int = N_BOOTSTRAP, seed: int = 11) -> Optional[float]:
    if len(g) < 30:
        return None
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(g), size=(n, len(g)))
    return float(np.percentile(g[idx].mean(axis=1), 5))


def _p_valor(g: np.ndarray) -> Optional[float]:
    """p-valor de una cola: ¿el ROI medio es > 0 por azar?

    t de Student sobre la media de las ganancias. Aproximado —las ganancias no
    son normales— pero suficiente para ORDENAR candidatos, que es para lo que
    se usa aquí.
    """
    if len(g) < 30:
        return None
    m, s = float(np.mean(g)), float(np.std(g, ddof=1))
    if s <= 0:
        return None
    from math import erf, sqrt
    t = m / (s / sqrt(len(g)))
    return float(0.5 * (1.0 - erf(t / sqrt(2.0))))


def benjamini_hochberg(pvals: List[float], q: float = 0.10) -> List[bool]:
    """Qué p-valores sobreviven controlando la tasa de falsos hallazgos."""
    n = len(pvals)
    if not n:
        return []
    orden = sorted(range(n), key=lambda i: pvals[i])
    corte = -1
    for rango, i in enumerate(orden, start=1):
        if pvals[i] <= q * rango / n:
            corte = rango
    fuera = [False] * n
    for rango, i in enumerate(orden, start=1):
        if rango <= corte:
            fuera[i] = True
    return fuera


def metricas(sub: pd.DataFrame) -> Dict:
    """Las métricas de un segmento. `g` es la ganancia neta por unidad."""
    if not len(sub):
        return {'n': 0}
    g = sub['ganancia'].to_numpy()
    p = sub['prob'].to_numpy()
    y = sub['acierto'].to_numpy()
    return {
        'n': int(len(sub)),
        'hit_rate': float(y.mean()),
        'prob_media': float(p.mean()),
        'calibracion': float(y.mean() - p.mean()),   # >0: acierta MÁS de lo que dice
        'cuota_media': float(sub['cuota'].mean()),
        'roi': float(g.mean()),
        'p5': _p5(g),
        'brier': float(np.mean((p - y) ** 2)),
        'p_valor': _p_valor(g),
    }


# ---------------------------------------------------------------------------
def cargar() -> pd.DataFrame:
    """Un solo cuadro con TODOS los picks resueltos y con cuota real.

    Junta dos ledgers que no tienen el mismo esquema:
      · el de ganador (1X2 / moneyline), con su cuota por lado
      · el de goles, con la línea de 2,5 y su cuota
    y los normaliza a: deporte, liga, mercado, prob, cuota, acierto, ganancia.
    """
    filas = []

    # ---- ganador ---------------------------------------------------------
    d = pd.read_csv(LEDGER_1X2)
    d = d[d.cuota_home.notna() & d.cuota_away.notna()].copy()
    probs = d[['p_home', 'p_draw', 'p_away']].fillna(0.0).to_numpy()
    cuotas = d[['cuota_home', 'cuota_draw', 'cuota_away']].to_numpy(dtype=float)
    elegido = probs.argmax(axis=1)
    fila = np.arange(len(d))
    g1 = pd.DataFrame({
        'deporte': d['deporte'].values,
        'liga': d['liga'].values,
        'fecha': d['fecha'].values,
        'pliegue': d['pliegue'].values,
        'equipo': d['match_id'].astype(str).values,
        'mercado': np.where(elegido == 1, 'Empate', 'Ganador'),
        'prob': probs[fila, elegido],
        'cuota': cuotas[fila, elegido],
        'acierto': (d['resultado'].astype(int).values == elegido).astype(int),
    })
    filas.append(g1)

    # ---- goles (línea 2,5, que es la que tiene precio) -------------------
    t = pd.read_csv(LEDGER_TOTALES)
    t = t[t.cuota_over25.notna() & (t.cuota_over25 > 1.0)].copy()
    t = t[t['p_over_2.5'].notna() & t['over_2.5_real'].notna()].copy()
    # el modelo elige lado: over si p>=0,5, under si no
    p_over = t['p_over_2.5'].to_numpy()
    lado_over = p_over >= 0.5
    cuota_u = t['cuota_under25'].to_numpy(dtype=float)
    real_over = t['over_2.5_real'].to_numpy().astype(int)
    g2 = pd.DataFrame({
        'deporte': 'Fútbol',
        'liga': t['liga'].values,
        'fecha': t['fecha'].values,
        'pliegue': t['pliegue'].values,
        'equipo': t['match_id'].astype(str).values,
        'mercado': np.where(lado_over, 'Más de 2.5', 'Menos de 2.5'),
        'prob': np.where(lado_over, p_over, 1.0 - p_over),
        'cuota': np.where(lado_over, t['cuota_over25'].to_numpy(dtype=float),
                          cuota_u),
        'acierto': np.where(lado_over, real_over, 1 - real_over),
    })
    g2 = g2[g2.cuota.notna() & (g2.cuota > 1.0)]
    filas.append(g2)

    d = pd.concat(filas, ignore_index=True)
    d = d[d.prob.notna() & (d.prob > 0)].copy()
    d['ganancia'] = np.where(d['acierto'] == 1, d['cuota'] - 1.0, -1.0)
    d['banda_cuota'] = pd.cut(
        d['cuota'], bins=[b[0] for b in BANDAS_CUOTA] + [BANDAS_CUOTA[-1][1]],
        labels=[f'{a:.2f}-{b:.2f}' for a, b in BANDAS_CUOTA], right=False)
    d['banda_prob'] = pd.cut(
        d['prob'], bins=[b[0] for b in BANDAS_PROB] + [BANDAS_PROB[-1][1]],
        labels=[f'{a:.0%}-{b:.0%}' for a, b in BANDAS_PROB], right=False)
    return d


# ---------------------------------------------------------------------------
def barrer(d: pd.DataFrame, por: List[str], min_cuota: float) -> List[Dict]:
    """Descubre en los pliegues 0-3 y juzga en el 4. Devuelve los candidatos."""
    util = d[d.cuota >= min_cuota]
    desc = util[util.pliegue.isin(PLIEGUES_DESCUBRIMIENTO)]
    juic = util[util.pliegue == PLIEGUE_JUICIO]

    fuera = []
    for llave, sub in desc.groupby(por, observed=True):
        if len(sub) < N_MINIMO:
            continue
        m = metricas(sub)
        if m.get('roi') is None or m['roi'] <= 0:
            continue                      # en descubrimiento ya pierde: fuera
        llave_t = llave if isinstance(llave, tuple) else (llave,)
        mask = np.ones(len(juic), dtype=bool)
        for col, val in zip(por, llave_t):
            mask &= (juic[col] == val).to_numpy()
        sj = juic[mask]
        fuera.append({
            'segmento': dict(zip(por, [str(x) for x in llave_t])),
            'descubrimiento': m,
            'juicio': metricas(sj),
        })

    # Benjamini-Hochberg sobre el descubrimiento
    pv = [c['descubrimiento'].get('p_valor') for c in fuera]
    validos = [i for i, v in enumerate(pv) if v is not None]
    if validos:
        marcas = benjamini_hochberg([pv[i] for i in validos])
        for i, ok in zip(validos, marcas):
            fuera[i]['bh_sobrevive'] = bool(ok)
    for c in fuera:
        c.setdefault('bh_sobrevive', False)
        j = c['juicio']
        c['confirmado'] = bool(
            c['bh_sobrevive']
            and j.get('n', 0) >= N_MINIMO_JUICIO
            and j.get('roi') is not None and j['roi'] > 0
            and j.get('p5') is not None and j['p5'] > 0)
    return sorted(fuera, key=lambda c: -(c['juicio'].get('roi') or -9))


def ventaja_por_banda(min_ventaja: float = 0.05) -> Dict:
    """LA PREGUNTA QUE DE VERDAD IMPORTA: ¿se puede tener buena cuota Y ventaja?

    El modelo se desordena en cuanto la cuota se alarga (ver el panorama por
    banda). Pero la ventaja de PRECIO no depende de que el modelo acierte: es
    comparar dos precios del mismo suceso, el de tu casa contra el de Pinnacle
    sin margen. Si esa ventaja sigue funcionando en las bandas de cuota buena,
    entonces «cuotas altas» y «edge medido» no son incompatibles, que es justo
    lo que hay que averiguar.

    Se mide sobre las 26.647 filas del ledger que traen las dos cosas: el
    precio de la casa y el de Pinnacle. Sólo fútbol — es donde hay ancla.
    """
    d = pd.read_csv(LEDGER_1X2)
    d = d[d.cuota_home.notna() & d.pin_home.notna()].copy()

    cuotas = d[['cuota_home', 'cuota_draw', 'cuota_away']].to_numpy(dtype=float)
    pines = d[['pin_home', 'pin_draw', 'pin_away']].to_numpy(dtype=float)

    # precio justo del ancla: implícitas de Pinnacle normalizadas a sumar 1
    with np.errstate(invalid='ignore', divide='ignore'):
        inv = np.where(np.isfinite(pines) & (pines > 1.0), 1.0 / pines, np.nan)
    suma = np.nansum(inv, axis=1)
    justo = np.where(suma[:, None] > 0, inv / suma[:, None], np.nan)
    cuota_justa = np.where(justo > 0, 1.0 / justo, np.nan)

    with np.errstate(invalid='ignore', divide='ignore'):
        ventaja = cuotas / cuota_justa - 1.0

    # una fila por LADO: cada lado es una apuesta posible con su ventaja
    filas = []
    resultado = d['resultado'].astype(int).to_numpy()
    for j, nombre in enumerate(('home', 'draw', 'away')):
        filas.append(pd.DataFrame({
            'liga': d['liga'].values, 'pliegue': d['pliegue'].values,
            'lado': nombre, 'cuota': cuotas[:, j], 'ventaja': ventaja[:, j],
            'acierto': (resultado == j).astype(int),
        }))
    v = pd.concat(filas, ignore_index=True)
    v = v[v.cuota.notna() & (v.cuota > 1.0) & v.ventaja.notna()].copy()
    # el guardia de datos del proyecto: una ventaja imposible es otro partido
    v = v[v.ventaja <= 0.30]
    v['ganancia'] = np.where(v['acierto'] == 1, v['cuota'] - 1.0, -1.0)
    v['prob'] = 1.0 / v['cuota']          # sólo para que `metricas` no rompa
    v['banda_cuota'] = pd.cut(
        v['cuota'], bins=[b[0] for b in BANDAS_CUOTA] + [BANDAS_CUOTA[-1][1]],
        labels=[f'{a:.2f}-{b:.2f}' for a, b in BANDAS_CUOTA], right=False)

    con = v[v.ventaja >= min_ventaja]
    fuera = {'n_total': int(len(v)), 'n_con_ventaja': int(len(con)),
             'min_ventaja': min_ventaja, 'bandas': [], 'juicio': {}}

    for llave, sub in con.groupby('banda_cuota', observed=True):
        m = metricas(sub)
        m['segmento'] = str(llave)
        m['ventaja_media'] = float(sub['ventaja'].mean())
        # y el mismo tramo SIN ventaja, para tener con qué comparar
        sin = v[(v.banda_cuota == llave) & (v.ventaja < min_ventaja)]
        m['roi_sin_ventaja'] = (float(sin['ganancia'].mean())
                                if len(sin) else None)
        fuera['bandas'].append(m)

    # juicio fuera de muestra: el pliegue 4, que no se usó para nada de esto
    juic = con[con.pliegue == PLIEGUE_JUICIO]
    if len(juic) >= 30:
        fuera['juicio'] = metricas(juic)
    return fuera


def panorama(d: pd.DataFrame) -> Dict:
    """El mapa general, sin buscar ganadores: por banda de cuota y de prob."""
    fuera = {}
    for eje in ('banda_cuota', 'banda_prob'):
        filas = []
        for llave, sub in d.groupby(eje, observed=True):
            m = metricas(sub)
            m['segmento'] = str(llave)
            filas.append(m)
        fuera[eje] = filas
    por_dep = []
    for llave, sub in d.groupby('deporte', observed=True):
        m = metricas(sub)
        m['segmento'] = str(llave)
        por_dep.append(m)
    fuera['deporte'] = por_dep
    return fuera


# ---------------------------------------------------------------------------
def _fmt(v, pct=False):
    if v is None:
        return '—'
    return f'{v*100:+.2f} %' if pct else f'{v:.4f}'


def escribir_md(doc: Dict, ruta: str = SALIDA_MD) -> None:
    L = ['# Patrones de acierto — dónde predice bien el modelo\n',
         f"Generado por `patrones_acierto.py` el {doc['generado']}.\n",
         f"Universo: **{doc['n_total']:,} picks resueltos con cuota real**, "
         f"cuota mínima {doc['min_cuota']:.2f}.\n".replace(',', '.'),
         '## Cómo leer esto, antes de los números\n',
         'Se **descubre** en los pliegues 0-3 y se **juzga** en el pliegue 4, '
         'que no se usó para elegir. Un segmento se declara `confirmado` sólo '
         'si sobrevive a Benjamini-Hochberg en descubrimiento **y** tiene ROI '
         'y percentil 5 positivos en juicio. Con 500 preguntas al 5 %, salen '
         '25 hallazgos falsos por aritmética pura: por eso el listón es ése y '
         'no «tiene buen ROI».\n']

    L += ['## 1. El panorama por banda de cuota\n',
          'Responde directamente a «no me sirve una cuota 1,10».\n',
          '| banda | n | cuota media | hit rate | prob. del modelo | '
          'calibración | ROI | p5 |', '|---|---|---|---|---|---|---|---|']
    for m in doc['panorama']['banda_cuota']:
        L.append(f"| {m['segmento']} | {m['n']:,} | {m['cuota_media']:.2f} | "
                 f"{m['hit_rate']:.1%} | {m['prob_media']:.1%} | "
                 f"{m['calibracion']:+.3f} | {_fmt(m['roi'], True)} | "
                 f"{_fmt(m['p5'], True)} |".replace(',', '.'))

    L += ['', '## 2. El panorama por banda de probabilidad\n',
          '| banda | n | cuota media | hit rate | calibración | ROI | p5 |',
          '|---|---|---|---|---|---|---|']
    for m in doc['panorama']['banda_prob']:
        L.append(f"| {m['segmento']} | {m['n']:,} | {m['cuota_media']:.2f} | "
                 f"{m['hit_rate']:.1%} | {m['calibracion']:+.3f} | "
                 f"{_fmt(m['roi'], True)} | {_fmt(m['p5'], True)} |"
                 .replace(',', '.'))

    L += ['', '## 3. Por deporte\n',
          '| deporte | n | cuota media | hit rate | calibración | ROI | p5 |',
          '|---|---|---|---|---|---|---|']
    for m in doc['panorama']['deporte']:
        L.append(f"| {m['segmento']} | {m['n']:,} | {m['cuota_media']:.2f} | "
                 f"{m['hit_rate']:.1%} | {m['calibracion']:+.3f} | "
                 f"{_fmt(m['roi'], True)} | {_fmt(m['p5'], True)} |"
                 .replace(',', '.'))

    for titulo, clave in (('4. Por liga', 'liga'),
                          ('5. Por mercado', 'mercado'),
                          ('6. Por liga y mercado', 'liga_mercado')):
        cands = doc['barridos'].get(clave) or []
        conf = [c for c in cands if c['confirmado']]
        L += ['', f'## {titulo}\n',
              f'{len(cands)} segmentos con ROI positivo en descubrimiento · '
              f'**{len(conf)} confirmados en juicio**.\n']
        if not cands:
            L.append('_Ninguno._\n')
            continue
        L += ['| segmento | n desc. | ROI desc. | BH | n juicio | ROI juicio '
              '| p5 juicio | ¿confirmado? |',
              '|---|---|---|---|---|---|---|---|']
        for c in cands[:25]:
            seg = ' · '.join(c['segmento'].values())
            de, ju = c['descubrimiento'], c['juicio']
            L.append(f"| {seg} | {de['n']:,} | {_fmt(de['roi'], True)} | "
                     f"{'sí' if c['bh_sobrevive'] else 'no'} | "
                     f"{ju.get('n', 0):,} | {_fmt(ju.get('roi'), True)} | "
                     f"{_fmt(ju.get('p5'), True)} | "
                     f"{'**SÍ**' if c['confirmado'] else 'no'} |"
                     .replace(',', '.'))

    total_conf = sum(len([c for c in v if c['confirmado']])
                     for v in doc['barridos'].values())
    L += ['', '## Veredicto\n']
    if total_conf:
        L.append(f'**{total_conf} segmentos confirmados** fuera de muestra. '
                 f'Son los candidatos a convertirse en canal propio, con el '
                 f'mismo trámite que cualquier otro: medición y puerta.\n')
    else:
        L.append('**Ningún segmento sobrevive al juicio fuera de muestra.**\n\n'
                 'Es un resultado, no un fallo del análisis. Significa que los '
                 'segmentos que ganan en los pliegues 0-3 no repiten en el 4, '
                 'que es la firma del sobreajuste: el patrón estaba en la '
                 'muestra, no en el mundo. Un buscador de patrones que no '
                 'puede devolver «no hay» no sirve para nada, porque siempre '
                 'devolvería algo.\n')

    with open(ruta, 'w', encoding='utf-8') as f:
        f.write('\n'.join(L))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--min-cuota', type=float, default=CUOTA_MINIMA_UTIL)
    a = ap.parse_args()

    d = cargar()
    logger.info('universo: %d picks resueltos con cuota', len(d))
    logger.info('con cuota >= %.2f: %d', a.min_cuota,
                int((d.cuota >= a.min_cuota).sum()))

    doc = {'generado': _dt.datetime.now().strftime('%Y-%m-%d %H:%M'),
           'n_total': int(len(d)), 'min_cuota': a.min_cuota,
           'panorama': panorama(d[d.cuota >= a.min_cuota]),
           'barridos': {}}

    for clave, por in (('liga', ['liga']), ('mercado', ['mercado']),
                       ('liga_mercado', ['liga', 'mercado'])):
        doc['barridos'][clave] = barrer(d, por, a.min_cuota)
        conf = [c for c in doc['barridos'][clave] if c['confirmado']]
        logger.info('  %-14s %3d candidatos, %d confirmados en juicio',
                    clave, len(doc['barridos'][clave]), len(conf))

    print('\n=== PANORAMA POR BANDA DE CUOTA ===')
    for m in doc['panorama']['banda_cuota']:
        print(f"  {m['segmento']:>12s}  n={m['n']:6,}  hit={m['hit_rate']:.1%}  "
              f"calib={m['calibracion']:+.3f}  ROI={m['roi']*100:+.2f}%  "
              f"p5={(m['p5'] or 0)*100:+.2f}%".replace(',', '.'))

    doc['ventaja'] = ventaja_por_banda()
    print('\n=== VENTAJA DE PRECIO (>= 5 %) POR BANDA DE CUOTA ===')
    print('  %d apuestas con ventaja de %d posibles'
          % (doc['ventaja']['n_con_ventaja'], doc['ventaja']['n_total']))
    for m in doc['ventaja']['bandas']:
        sv = m.get('roi_sin_ventaja')
        print(f"  {m['segmento']:>12s}  n={m['n']:6,}  hit={m['hit_rate']:.1%}  "
              f"ROI={m['roi']*100:+.2f}%  p5={(m['p5'] or 0)*100:+.2f}%  "
              f"(sin ventaja: {sv*100:+.2f}%)".replace(',', '.')
              if sv is not None else '')
    ju = doc['ventaja'].get('juicio') or {}
    if ju:
        print(f"  JUICIO (pliegue 4): n={ju['n']}  ROI={ju['roi']*100:+.2f}%  "
              f"p5={(ju['p5'] or 0)*100:+.2f}%")

    print('\n=== CONFIRMADOS FUERA DE MUESTRA ===')
    total = 0
    for clave, cands in doc['barridos'].items():
        for c in cands:
            if c['confirmado']:
                total += 1
                print(f"  [{clave}] {' · '.join(c['segmento'].values())}  "
                      f"juicio ROI={c['juicio']['roi']*100:+.2f}%  "
                      f"p5={c['juicio']['p5']*100:+.2f}%  n={c['juicio']['n']}")
    if not total:
        print('  ninguno')

    with open(SALIDA_JSON, 'w', encoding='utf-8') as f:
        json.dump(doc, f, ensure_ascii=False, indent=1, default=str)
    escribir_md(doc)
    print(f'\n-> {SALIDA_JSON}\n-> {SALIDA_MD}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
