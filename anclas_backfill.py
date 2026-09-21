# -*- coding: utf-8 -*-
"""
v277 — La segunda puerta del ancla, contestada en días en vez de en meses.

EL PROBLEMA DE PLAZOS
`anclas.py` acumula una foto por barrido y hay que esperar. Para la primera
puerta —que la probabilidad sin margen se parezca a la de Pinnacle— eso son dos
o tres semanas. Para la SEGUNDA —que los picks generados con esa ancla HAYAN
GANADO— son meses, porque hay que esperar a que los partidos se jueguen.

LO QUE CAMBIA ESO
El feed de Flashscore sirve **los últimos 7 días** —comprobado: a 8 días ya
devuelve vacío— y esos partidos **conservan las cuotas**. El partido de prueba
estaba terminado (1-1) y las 293 casas seguían devolviendo precio. Además el
propio feed trae el marcador (`AG`/`AH`) y el estado (`AC=3`, finalizado).

O sea que se puede montar el backtest HOY, con miles de partidos, en vez de
esperar a que ocurran.

EL SESGO QUE ESTO TIENE, Y NO SE PUEDE QUITAR
La cuota que se recupera de un partido pasado es la ÚLTIMA, la de cierre. No
es la que se habría tomado horas antes, que es cuando se apuesta de verdad. Y
las discrepancias se cierran según se acerca el partido, así que el cierre
tiende a enseñar MENOS ventaja de la que hubo.

Eso hace este backtest **conservador, no optimista**: si aquí sale rentable,
en vivo debería salir igual o mejor. Pero sigue sin ser una simulación fiel, y
por eso NO abre la puerta por sí solo — la abre la acumulación en vivo de
`anclas.py`. Esto sirve para DESCARTAR rápido: una candidata que pierde aquí
no merece que la sigamos midiendo dos meses.

Esa distinción importa. En esta misma sesión se midió un «edge» de movimiento
de línea que resultó ser un artefacto de cuándo se tomaba la foto, y hubo que
retirarlo. El mismo tipo de error cabe aquí si se olvida de dónde salen estos
precios.

Uso:
    python anclas_backfill.py              # 7 días, fútbol
    python anclas_backfill.py --dias 3     # menos, para probar
"""
from __future__ import annotations

import io
import json
import logging
import os
import re
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

SALIDA = 'anclas_backfill.json'
FINALIZADO = '3'

# La casa donde el usuario apuesta de verdad. El EV se calcula SIEMPRE sobre un
# precio tomable: un EV contra una casa que no juega no es una oportunidad.
CASA_USUARIO = 632          # Novibet

# La misma regla validada de la Capa 1 (v269).
EV_MIN = 0.005
PROB_MIN = 0.30
CUOTA_MIN = 1.15


def _finalizados(sport_id: int, dia: int, sesion) -> List[Dict]:
    """Los partidos TERMINADOS de ese día, con marcador. Nunca lanza."""
    import cuotas_mx as mx
    try:
        t = sesion.get(mx.FEED % (sport_id, dia), timeout=30).text
    except Exception as e:
        logger.debug('[backfill] feed %s/%s: %s', sport_id, dia, e)
        return []
    fuera, liga = [], ''
    for trozo in re.split(r'~ZA÷', t):
        cab = trozo.split('¬')[0]
        if cab and '÷' not in cab:
            liga = cab[:80]
        for x in trozo.split('~AA÷')[1:]:
            eid = x[:8]
            c = dict(re.findall(r'([A-Z]{2})÷([^¬]*)', '¬' + x))
            if c.get('AC') != FINALIZADO:
                continue
            h, a = c.get('AE'), c.get('AF')
            gh, ga = c.get('AG'), c.get('AH')
            if not (h and a and gh not in (None, '') and ga not in (None, '')):
                continue
            try:
                gh, ga = int(gh), int(ga)
            except (TypeError, ValueError):
                continue
            fuera.append({'id': eid, 'home': h, 'away': a, 'liga': liga,
                          'goles_home': gh, 'goles_away': ga,
                          'resultado': 0 if gh > ga else (1 if gh == ga else 2)})
    return fuera


def _cuotas(sesion, eid: str, casa: int) -> Optional[tuple]:
    """(home, draw, away) de esa casa para ese partido. Nunca lanza."""
    import cuotas_mx as mx
    try:
        r = sesion.get(mx.ODDS, params={'_hash': 'ope2', 'eventId': eid,
                                        'bookmakerId': casa,
                                        'betType': 'HOME_DRAW_AWAY',
                                        'betScope': 'FULL_TIME'}, timeout=15)
        if r.status_code != 200:
            return None
        n = (((r.json().get('data') or {})
              .get('findPrematchOddsForBookmaker')) or {})
        v = [(n.get(k) or {}).get('value') for k in ('home', 'draw', 'away')]
        if all(v):
            return tuple(float(x) for x in v)
    except Exception as e:
        logger.debug('[backfill] %s/%s: %s', eid, casa, e)
    return None


def _devig(c) -> Optional[Dict]:
    try:
        s = sum(1.0 / float(x) for x in c)
    except (TypeError, ValueError, ZeroDivisionError):
        return None
    if s <= 0:
        return None
    return {'home': (1.0 / c[0]) / s, 'draw': (1.0 / c[1]) / s,
            'away': (1.0 / c[2]) / s, 'margen': s - 1.0}


def recoger(dias: int = 7, max_por_dia: int = 300,
            sport_id: int = 1) -> List[Dict]:
    """Los partidos de los últimos días con marcador y cuotas. Nunca lanza."""
    import requests
    from concurrent.futures import ThreadPoolExecutor

    import anclas

    ses = requests.Session()
    ad = requests.adapters.HTTPAdapter(pool_connections=20, pool_maxsize=20)
    ses.mount('https://', ad)
    import cuotas_mx as mx
    ses.headers.update(mx.CABEZ)

    partidos = []
    for d in range(-1, -(dias + 1), -1):
        trozo = _finalizados(sport_id, d, ses)[:max_por_dia]
        logger.info('[backfill] día %+d: %d partidos terminados', d, len(trozo))
        partidos.extend(trozo)
    if not partidos:
        return []

    casas = list(anclas.CANDIDATAS) + [CASA_USUARIO]
    tareas = [(p, c) for p in partidos for c in casas]
    logger.info('[backfill] %d partidos · %d peticiones',
                len(partidos), len(tareas))

    def _una(t):
        p, c = t
        return (p['id'], c, _cuotas(ses, p['id'], c))

    precios: Dict[str, Dict[int, tuple]] = {}
    with ThreadPoolExecutor(max_workers=16) as pool:
        for eid, c, cu in pool.map(_una, tareas):
            if cu:
                precios.setdefault(eid, {})[c] = cu
    for p in partidos:
        p['precios'] = precios.get(p['id'], {})
    return [p for p in partidos if p['precios'].get(CASA_USUARIO)]


def medir(partidos: List[Dict]) -> Dict:
    """¿Habrían ganado los picks generados con cada candidata de ancla?"""
    import numpy as np

    import anclas

    fuera = {'n_partidos': len(partidos), 'candidatas': {}}
    if not partidos:
        return fuera
    rng = np.random.default_rng(17)
    for ancla in anclas.CANDIDATAS:
        rets, aciertos, margenes = [], 0, []
        for p in partidos:
            ca = p['precios'].get(ancla)
            cu = p['precios'].get(CASA_USUARIO)
            if not (ca and cu):
                continue
            q = _devig(ca)
            if not q:
                continue
            margenes.append(q['margen'])
            for i, lado in enumerate(('home', 'draw', 'away')):
                if lado == 'draw':
                    continue            # la regla validada no juega el empate
                if lado == 'away':
                    continue            # ni el visitante: ver la BITACORA
                precio = cu[i]
                if precio < CUOTA_MIN or q[lado] < PROB_MIN:
                    continue
                ev = q[lado] * precio - 1.0
                if ev < EV_MIN:
                    continue
                gano = (p['resultado'] == i)
                rets.append(precio - 1.0 if gano else -1.0)
                aciertos += int(gano)
        ficha = {'n_picks': len(rets),
                 'margen_mediano': round(100 * float(np.median(margenes)), 3)
                 if margenes else None}
        if len(rets) >= 40:
            r = np.array(rets)
            xs = np.array([r[rng.integers(0, len(r), len(r))].mean()
                           for _ in range(1500)])
            ficha.update({
                'aciertos': round(100.0 * aciertos / len(rets), 2),
                'roi': round(100 * float(r.mean()), 2),
                'p5': round(100 * float(np.percentile(xs, 5)), 2),
            })
        fuera['candidatas'][str(ancla)] = ficha
    return fuera


def main() -> int:
    import argparse
    import datetime as dt
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    ap = argparse.ArgumentParser(description='Backfill de anclas (7 días)')
    ap.add_argument('--dias', type=int, default=7)
    ap.add_argument('--max', type=int, default=300)
    args = ap.parse_args()

    partidos = recoger(dias=args.dias, max_por_dia=args.max)
    print('partidos con marcador Y precio de tu casa: %s'
          % format(len(partidos), ',d'))
    d = medir(partidos)
    d['generado'] = dt.datetime.now(dt.timezone.utc).strftime(
        '%Y-%m-%dT%H:%M:%SZ')
    d['aviso'] = ('Cuotas de CIERRE, no las que se habrian tomado horas antes. '
                  'El sesgo va en contra: las discrepancias se cierran segun '
                  'se acerca el partido, asi que esto enseña MENOS ventaja de '
                  'la que hubo. Sirve para DESCARTAR, no para aprobar.')
    print()
    print('%-8s %8s %9s %9s %9s %9s'
          % ('ancla', 'picks', 'margen', 'acierta', 'ROI', 'p5'))
    for b, f in sorted(d['candidatas'].items()):
        print('%-8s %8s %8s %% %8s %% %8s %% %8s %%'
              % (b, f.get('n_picks'), f.get('margen_mediano'),
                 f.get('aciertos', '-'), f.get('roi', '-'), f.get('p5', '-')))
    try:
        with io.open(SALIDA, 'w', encoding='utf-8', newline='\n') as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
        print('\nguardado en %s' % SALIDA)
    except Exception as e:
        print('no se pudo guardar: %s' % e)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
