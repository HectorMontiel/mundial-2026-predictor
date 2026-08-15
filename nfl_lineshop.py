#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v131 · NFL — ¿tiene el canal de PRECIO su propio p5 en fútbol americano?

Por qué existe este fichero
---------------------------
`clasificador.canal_del_pick` manda a la Sección 2 todo pick de precio que no
sea fútbol, con este motivo escrito: *«canal de precio en NFL, que es el mismo
método pero SIN medir: el desglose por lado se hizo sólo sobre fútbol. Sin su
propio p5 no puede subir»*.

Eso es correcto y es la regla de oro del proyecto. Pero «sin medir» no es un
estado permanente: es una tarea. Y en la NFL **sí se puede medir**, porque
ESPN publica el cierre histórico de hasta 13 casas por partido — el mismo
hallazgo que hace posible el backtest del modelo.

Qué se mide, exactamente lo mismo que en fútbol
------------------------------------------------
    p_justa  = devig(cuotas de la casa ANCLA)      ← sin margen
    ventaja  = mejor_cuota_de_otra_casa × p_justa − 1
    se apuesta si  ventaja ≥ margen  y  p_justa ≥ 0,30

Y se juzga con la regla del proyecto: **ROI positivo Y bootstrap p5 positivo**,
con la elección de parámetros en las temporadas antiguas y el juicio en la
reciente — que es lo que la bitácora §2 exige tras el caso del empate (+12,21 %
en el tramo de elección, −7,09 % en el de juicio).

Qué NO se hace
--------------
No se elige el margen mirando el tramo de juicio. Si ninguna configuración pasa
en los dos tramos, el veredicto es «no», y la NFL se queda en la Sección 2 con
el motivo escrito. Fabricar un umbral que funcione en el tramo con el que se
eligió es exactamente el error que este módulo existe para no cometer.
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

import nfl_datos as nd

logger = logging.getLogger(__name__)

ARCHIVO_CIERRES = 'nfl_cierres_multicasa.csv'
VEREDICTO = 'nfl_canal_precio.json'
SEMILLA = 20260815

# El ancla tiene que ser la casa más eficiente disponible, porque de su devig
# sale la probabilidad justa. En producción el ancla es Pinnacle; en el
# histórico de ESPN, Pinnacle no está, así que se usa la que más se le parece
# en función: la de mayor cobertura y menor margen medido. Cuál es se DECIDE
# midiendo (`elegir_ancla`), no eligiendo.
ANCLAS_CANDIDATAS = ('Caesars Sportsbook (Colorado)', 'ESPN BET', 'DraftKings',
                     'Westgate', 'William Hill (New Jersey)', 'Bet 365',
                     'Caesars Sportsbook', 'SugarHouse', 'unibet')


def _dec(x) -> Optional[float]:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v > 1.0 else None


def cierres_multicasa(event_id: str) -> Dict[str, Dict[str, float]]:
    """{casa: {'home': cuota, 'away': cuota}} con el CIERRE de cada proveedor."""
    j = nd._get(f'{nd.CORE}/events/{event_id}/competitions/{event_id}/odds')
    out: Dict[str, Dict[str, float]] = {}
    for it in ((j or {}).get('items') or []):
        nom = ((it.get('provider') or {}).get('name') or '').strip()
        if not nom:
            continue
        h = nd._rama(it.get('homeTeamOdds') or {}, 'moneyLine')
        a = nd._rama(it.get('awayTeamOdds') or {}, 'moneyLine')
        h, a = _dec(h), _dec(a)
        if h and a:
            out[nom] = {'home': h, 'away': a}
    return out


def construir_cierres(historico: Optional[pd.DataFrame] = None,
                      salida: str = ARCHIVO_CIERRES,
                      incremental: bool = True) -> pd.DataFrame:
    """Una fila por partido y casa, con el cierre de moneyline de las dos vías."""
    d = historico if historico is not None else nd.cargar_historico()
    if not len(d):
        logger.warning('[nfl-ls] sin histórico')
        return pd.DataFrame()
    previos, ya = pd.DataFrame(), set()
    if incremental and os.path.exists(salida):
        try:
            previos = pd.read_csv(salida, dtype={'event_id': str})
            ya = set(previos['event_id'].astype(str))
        except Exception as e:
            logger.warning(f'[nfl-ls] {salida} ilegible: {e}')
    pend = [r for r in d.to_dict('records')
            if str(r['event_id']) not in ya
            and r.get('tipo') in ('regular', 'playoffs')]
    filas, t0 = [], time.time()
    for i, r in enumerate(pend, 1):
        for casa, c in cierres_multicasa(str(r['event_id'])).items():
            filas.append({'event_id': str(r['event_id']),
                          'fecha': str(r['fecha'])[:10],
                          'temporada': r.get('temporada'),
                          'home': r['home'], 'away': r['away'],
                          'gana_home': int(float(r['pts_home']) > float(r['pts_away'])),
                          'empate': int(float(r['pts_home']) == float(r['pts_away'])),
                          'casa': casa, 'c_home': c['home'], 'c_away': c['away']})
        if i % 50 == 0 or i == len(pend):
            logger.info(f'[nfl-ls] {i}/{len(pend)} '
                        f'({(time.time()-t0)/max(i,1):.2f} s/partido)')
    nuevo = pd.DataFrame(filas)
    out = pd.concat([previos, nuevo], ignore_index=True) if len(previos) else nuevo
    if not len(out):
        return out
    out = out.drop_duplicates(subset=['event_id', 'casa'], keep='last')
    out.to_csv(salida, index=False)
    logger.info(f'[nfl-ls] {salida}: {len(out)} filas · '
                f'{out["event_id"].nunique()} partidos · '
                f'{out["casa"].nunique()} casas')
    return out


def _devig(ch: float, ca: float) -> Tuple[float, float]:
    p1, p2 = 1.0 / ch, 1.0 / ca
    s = p1 + p2
    return p1 / s, p2 / s


def _bootstrap_p5(pnl: np.ndarray, n: int = 2000) -> float:
    if len(pnl) < 20:
        return float('nan')
    rng = np.random.default_rng(SEMILLA)
    idx = rng.integers(0, len(pnl), size=(n, len(pnl)))
    return float(np.percentile(pnl[idx].mean(axis=1), 5))


def cobertura(d: pd.DataFrame) -> pd.DataFrame:
    """Qué casa cubre cuántos partidos y con qué margen medio (overround−1)."""
    d = d.copy()
    d['margen'] = 1.0 / d['c_home'] + 1.0 / d['c_away'] - 1.0
    g = d.groupby('casa').agg(partidos=('event_id', 'nunique'),
                              margen=('margen', 'mean')).reset_index()
    return g.sort_values(['partidos', 'margen'], ascending=[False, True])


def elegir_ancla(d: pd.DataFrame, min_cobertura: float = 0.60) -> Optional[str]:
    """
    El ancla es la casa con MENOR margen entre las que cubren lo suficiente.

    Menor margen = precio más eficiente = mejor estimación de la probabilidad
    real. Es el mismo criterio por el que Pinnacle es el ancla en producción,
    aplicado a lo que hay en el histórico en vez de dado por supuesto.
    """
    cob = cobertura(d)
    total = d['event_id'].nunique()
    aptas = cob[cob['partidos'] >= min_cobertura * total]
    if not len(aptas):
        return None
    return str(aptas.sort_values('margen').iloc[0]['casa'])


def evaluar(d: pd.DataFrame, ancla: str, margen_min: float,
            prob_min: float = 0.30,
            lados: Tuple[str, ...] = ('home', 'away')) -> Dict:
    """
    Aplica el canal y devuelve n, acierto, ROI y bootstrap p5 — por lado.

    El desglose POR LADO no es un extra: en fútbol es lo que destapó que el
    canal sólo es robusto al local (p5 +1,73 %) y no al empate (−38,91 %) ni al
    visitante (−5,10 %). Sin partirlo, la NFL heredaría un veredicto global que
    podría esconder exactamente el mismo problema.
    """
    anc = d[d['casa'] == ancla].set_index('event_id')
    otras = d[d['casa'] != ancla]
    apuestas = []
    for r in otras.itertuples(index=False):
        a = anc.loc[r.event_id] if r.event_id in anc.index else None
        if a is None:
            continue
        p_h, p_a = _devig(float(a.c_home), float(a.c_away))
        for lado, cuota, p_just, gana in (
                ('home', float(r.c_home), p_h, int(r.gana_home) == 1),
                ('away', float(r.c_away), p_a, int(r.gana_home) == 0
                 and int(r.empate) == 0)):
            if lado not in lados or p_just < prob_min:
                continue
            ventaja = cuota * p_just - 1.0
            if ventaja < margen_min:
                continue
            apuestas.append({'event_id': r.event_id, 'temporada': r.temporada,
                             'lado': lado, 'cuota': cuota, 'p_just': p_just,
                             'ventaja': ventaja, 'gana': gana,
                             'empate': int(r.empate) == 1, 'casa': r.casa})
    if not apuestas:
        return {'n': 0}
    A = pd.DataFrame(apuestas)
    # UN PARTIDO, UNA APUESTA. Sin esto, un partido donde cinco casas superan
    # el ancla entra cinco veces y el bootstrap trata como independientes cinco
    # copias del mismo resultado — que es cómo un p5 se vuelve optimista sin
    # que nadie toque una fórmula. Se queda la de mayor ventaja, que es la que
    # tomaría el line shopping de producción.
    A = A.sort_values('ventaja', ascending=False) \
         .drop_duplicates(subset=['event_id', 'lado'], keep='first')
    pnl = np.where(A['empate'], 0.0,
                   np.where(A['gana'], A['cuota'] - 1.0, -1.0))
    return {'n': int(len(A)), 'acierto': round(float(A['gana'].mean()), 4),
            'roi': round(float(pnl.mean()), 4),
            'p5': round(_bootstrap_p5(pnl), 4),
            'ventaja_media': round(float(A['ventaja'].mean()), 4),
            'cuota_media': round(float(A['cuota'].mean()), 3)}


def veredicto(d: Optional[pd.DataFrame] = None,
              temporadas_juicio: Tuple[int, ...] = (2025,)) -> Dict:
    """
    El informe completo: elección en las temporadas antiguas, juicio en la
    reciente, y un veredicto por lado que sólo dice «sí» con p5 positivo en
    LOS DOS tramos.
    """
    if d is None:
        d = pd.read_csv(ARCHIVO_CIERRES, dtype={'event_id': str})
    if not len(d):
        return {'error': 'sin cierres'}
    ancla = elegir_ancla(d)
    if not ancla:
        return {'error': 'ninguna casa cubre lo suficiente para ser ancla',
                'cobertura': cobertura(d).to_dict('records')}
    elige = d[~d['temporada'].isin(temporadas_juicio)]
    juzga = d[d['temporada'].isin(temporadas_juicio)]

    # ¿Cuántos partidos tienen DOS casas con las que comparar? Sin dos precios
    # no hay line shopping: no es que el canal salga mal, es que no existe.
    comparables = (d.groupby(['temporada', 'event_id'])['casa'].nunique()
                   .reset_index().rename(columns={'casa': 'n_casas'}))
    por_temporada = (comparables[comparables['n_casas'] >= 2]
                     .groupby('temporada').size().to_dict())
    out = {
        'ancla': ancla,
        'cobertura': cobertura(d).to_dict('records'),
        'n_partidos': int(d['event_id'].nunique()),
        'comparables_por_temporada': {int(k): int(v) for k, v in por_temporada.items()},
        'temporadas_eleccion': sorted(int(x) for x in elige['temporada'].dropna().unique()),
        'temporadas_juicio': list(temporadas_juicio),
        'barrido': [], 'por_lado': {},
    }

    # NO MEDIBLE NO ES LO MISMO QUE MEDIDO Y NEGATIVO, y confundirlos sería
    # exactamente el tipo de mentira que este proyecto evita.
    #
    # Medido el 2026-08-15: ESPN guarda el cierre de VARIAS casas sólo en la
    # temporada 2023 (12 casas, 207 partidos comparables). Desde 2024 conserva
    # únicamente la suya —ESPN BET— y parte de DraftKings, así que el tramo de
    # juicio se queda con 2 partidos comparables. Con eso no se mide nada.
    #
    # El efecto sobre el sistema es el mismo (la NFL no sube a Sección 1), pero
    # el MOTIVO que se escribe es distinto, y el motivo es lo que dice si esto
    # es una tarea pendiente o un callejón cerrado. Aquí es una tarea: en
    # cuanto `odds_snapshots` acumule un par de meses de fotos diarias de
    # Pinnacle, Bovada y Playdoit en NFL, el canal se podrá medir con datos
    # propios y esta función devolverá un veredicto de verdad.
    n_juicio_comparable = sum(v for k, v in por_temporada.items()
                              if k in temporadas_juicio)
    n_eleccion_comparable = sum(v for k, v in por_temporada.items()
                                if k not in temporadas_juicio)
    if n_juicio_comparable < 50 or n_eleccion_comparable < 100:
        out.update({
            'medible': False, 'edge_validado': False,
            'margen_elegido': None, 'lados_robustos': [],
            'motivo': (
                f'NO MEDIBLE con esta fuente, que no es lo mismo que medido y '
                f'negativo. ESPN conserva el cierre de varias casas sólo en la '
                f'temporada 2023 ({n_eleccion_comparable} partidos con ≥2 '
                f'casas); desde 2024 guarda casi únicamente la suya, así que el '
                f'tramo de juicio se queda en {n_juicio_comparable} partidos '
                f'comparables. Sin dos precios no hay line shopping que medir. '
                f'La NFL se queda en la Sección 2 —que es el camino por '
                f'defecto— y el canal volverá a evaluarse cuando '
                f'`odds_snapshots` acumule fotos propias de Pinnacle, Bovada y '
                f'Playdoit.'),
        })
        with open(VEREDICTO, 'w', encoding='utf-8') as f:
            json.dump(out, f, ensure_ascii=False, indent=1, default=float)
        return out
    out['medible'] = True
    for margen in (0.00, 0.01, 0.02, 0.03, 0.05):
        e = evaluar(elige, ancla, margen)
        j = evaluar(juzga, ancla, margen)
        out['barrido'].append({'margen': margen, 'eleccion': e, 'juicio': j})

    # el margen se elige SÓLO con el tramo de elección
    aptos = [b for b in out['barrido']
             if b['eleccion'].get('n', 0) >= 100
             and (b['eleccion'].get('p5') or -9) > 0]
    if aptos:
        mejor = max(aptos, key=lambda b: b['eleccion']['p5'])
        out['margen_elegido'] = mejor['margen']
        for lado in ('home', 'away'):
            e = evaluar(elige, ancla, mejor['margen'], lados=(lado,))
            j = evaluar(juzga, ancla, mejor['margen'], lados=(lado,))
            robusto = bool(e.get('n', 0) >= 100 and j.get('n', 0) >= 30
                           and (e.get('p5') or -9) > 0 and (j.get('p5') or -9) > 0)
            out['por_lado'][lado] = {'eleccion': e, 'juicio': j,
                                     'robusto': robusto}
        out['edge_validado'] = any(v['robusto'] for v in out['por_lado'].values())
        out['lados_robustos'] = [k for k, v in out['por_lado'].items()
                                 if v['robusto']]
    else:
        out['margen_elegido'] = None
        out['edge_validado'] = False
        out['lados_robustos'] = []
        out['motivo'] = ('MEDIDO Y NEGATIVO: ninguna configuración del canal '
                         'alcanza p5 positivo ni siquiera en el tramo con el '
                         'que se elige, así que no hay nada que llevar al '
                         'tramo de juicio')
    with open(VEREDICTO, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=1, default=float)
    return out


def medicion_para_clasificador() -> Optional[Dict]:
    """
    Lo que `clasificador` necesita para decidir si la NFL sube a Sección 1.

    Devuelve `None` cuando no hay veredicto o cuando el veredicto es que no:
    con `None`, el clasificador sigue mandando la NFL a la Sección 2 con su
    motivo, que es el comportamiento correcto por defecto.
    """
    try:
        with open(VEREDICTO, encoding='utf-8') as f:
            v = json.load(f)
    except Exception:
        return None
    if not v.get('edge_validado'):
        return None
    return {'lados': v.get('lados_robustos') or [],
            'margen': v.get('margen_elegido'),
            'por_lado': {k: {'n_juicio': (d.get('juicio') or {}).get('n'),
                             'roi_juicio': (d.get('juicio') or {}).get('roi'),
                             'p5_juicio': (d.get('juicio') or {}).get('p5')}
                         for k, d in (v.get('por_lado') or {}).items()
                         if d.get('robusto')}}


if __name__ == '__main__':
    import argparse
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    ap = argparse.ArgumentParser()
    ap.add_argument('--descargar', action='store_true')
    ap.add_argument('--juicio', default='2025')
    a = ap.parse_args()
    if a.descargar or not os.path.exists(ARCHIVO_CIERRES):
        construir_cierres()
    d = pd.read_csv(ARCHIVO_CIERRES, dtype={'event_id': str})
    print(f'{len(d)} filas · {d["event_id"].nunique()} partidos · '
          f'{d["casa"].nunique()} casas\n')
    print(cobertura(d).to_string(index=False))
    v = veredicto(d, tuple(int(x) for x in a.juicio.split(',')))
    print('\nancla:', v.get('ancla'))
    print(f'\n{"margen":>7} | {"ELECCIÓN n/ROI/p5":>28} | {"JUICIO n/ROI/p5":>28}')
    for b in v.get('barrido', []):
        e, j = b['eleccion'], b['juicio']
        print(f"{b['margen']:7.2f} | "
              f"{e.get('n',0):6d} {e.get('roi',0)*100:+7.2f} % "
              f"{e.get('p5',0)*100:+7.2f} % | "
              f"{j.get('n',0):6d} {j.get('roi',0)*100:+7.2f} % "
              f"{j.get('p5',0)*100:+7.2f} %")
    print('\npor lado:', json.dumps(v.get('por_lado'), ensure_ascii=False,
                                    indent=1, default=float))
    print('\nEDGE VALIDADO:', v.get('edge_validado'),
          '· lados:', v.get('lados_robustos'))
