# -*- coding: utf-8 -*-
"""
v303 — EL HISTÓRICO REAL DE LAS SELECCIONES: RESULTADOS Y BOXSCORE DE ESPN.

POR QUÉ HACE FALTA
El motor de selecciones se entrenó con `historico_partidos.csv`: los
RESULTADOS son reales (Kaggle), pero córners, tarjetas, remates, xG y
posesión los escribió `correlated_synthetic_generator`. Medido el 2026-09-23:
las seis columnas tienen el 100 % de cobertura desde 2023, que es justo la
firma del relleno. Enseñar «Japón saca 5,2 córners de media» con eso sería
enseñar un número inventado.

El usuario lo pidió así: «si no tienes datos tienes que investigar fuentes
alternas con datos reales; en este proyecto no estará permitido no tener
datos». La fuente ya estaba en casa: el `summary` de ESPN trae el boxscore de
los partidos de selecciones igual que el de los clubes (`stats_espn`,
validado contra football-data con correlación 0,98). Sondeado el 2026-09-23:
Nations League de UEFA 4 de 4 partidos con boxscore; eliminatorias
sudamericanas, parcial; amistosos y eliminatorias africanas, casi nada.

QUÉ ESCRIBE
`historico_selecciones.csv`, con las MISMAS columnas que los históricos de
liga (`home_team`, `home_goals`, `home_corners`, `home_yellow`...) y
`stats_origen='espn'` en las filas con boxscore. Así `rendimiento_equipos`,
`contexto_partido` y `patrones_equipo` lo leen sin tocar nada, y
`rendimiento_equipos._solo_reales` usa sólo las filas observadas: un partido
sin boxscore aporta su resultado y NUNCA un córner inventado.

Los nombres son los de ESPN en inglés, que son los mismos que usa el
pronóstico de la rama de selecciones (`selecciones_dia`).

Uso:
    python historico_selecciones.py --desde 2021-01-01   # el fondo, una vez
    python historico_selecciones.py                      # los últimos 45 días
"""
from __future__ import annotations

import logging
import os
import sys
from typing import Dict, List, Optional

import pandas as pd

logger = logging.getLogger(__name__)

FICHERO = 'historico_selecciones.csv'
CLAVE = 'selecciones'

# Sólo absolutas masculinas: el motor no sabe nada de las demás (v119).
_EXCLUIR = ('.w', 'olympics', 'wwc', 'weuro')


def codigos() -> List[str]:
    import fixtures_espn as fe
    return [c for c, _ in fe.LIGAS_SELECCIONES
            if not any(x in c for x in _EXCLUIR)]


def _torneo(code: str) -> str:
    import fixtures_espn as fe
    return dict(fe.LIGAS_SELECCIONES).get(code, code)


def _eventos_con_goles(code: str, desde: str, hasta: str) -> List[Dict]:
    """Los partidos jugados del rango, CON el marcador (que `stats_espn`
    no guarda porque los históricos de liga ya lo tenían)."""
    import stats_espn as se
    ini, fin = pd.Timestamp(desde), pd.Timestamp(hasta)
    meses = pd.date_range(ini.replace(day=1), fin, freq='MS')
    if len(meses) == 0:
        meses = pd.DatetimeIndex([ini.replace(day=1)])
    fuera, vistos = [], set()
    for m in meses:
        d = se._get(se.BASE.format(code=code)
                    + '/scoreboard?dates=%s&limit=500' % m.strftime('%Y%m'))
        for ev in ((d or {}).get('events') or []):
            try:
                eid = str(ev.get('id') or '')
                if not eid or eid in vistos:
                    continue
                if not (((ev.get('status') or {}).get('type') or {})
                        .get('completed')):
                    continue
                comp = ev['competitions'][0]
                loc = next(c for c in comp['competitors']
                           if c['homeAway'] == 'home')
                vis = next(c for c in comp['competitors']
                           if c['homeAway'] == 'away')
                f = pd.to_datetime(ev.get('date'), errors='coerce')
                if f is None or pd.isna(f):
                    continue
                if getattr(f, 'tzinfo', None):
                    f = f.tz_convert(None)
                vistos.add(eid)
                fuera.append({'event_id': eid,
                              'fecha': f.strftime('%Y-%m-%d'),
                              'home': loc['team']['displayName'],
                              'away': vis['team']['displayName'],
                              'home_goals': float(loc.get('score')),
                              'away_goals': float(vis.get('score')),
                              'neutral': bool(comp.get('neutralSite')),
                              'tournament': _torneo(code), '_code': code})
            except Exception:
                continue
    return fuera


def leer() -> pd.DataFrame:
    if not os.path.exists(FICHERO):
        return pd.DataFrame()
    try:
        return pd.read_csv(FICHERO, low_memory=False)
    except Exception as e:
        logger.warning('[selecciones] %s ilegible: %s', FICHERO, e)
        return pd.DataFrame()


def actualizar(desde: Optional[str] = None, hasta: Optional[str] = None,
               hilos: int = 8) -> Dict:
    """Añade los partidos nuevos del rango. Los que ya están no se piden."""
    from concurrent.futures import ThreadPoolExecutor
    import stats_espn as se
    hoy = pd.Timestamp.now('UTC').tz_localize(None).normalize()
    desde = desde or (hoy - pd.Timedelta(days=45)).strftime('%Y-%m-%d')
    hasta = hasta or hoy.strftime('%Y-%m-%d')
    previo = leer()
    ya = set(previo['event_id'].astype(str)) if 'event_id' in previo else set()
    nuevos = []
    for code in codigos():
        evs = [e for e in _eventos_con_goles(code, desde, hasta)
               if e['event_id'] not in ya]
        if not evs:
            continue

        def _uno(ev, code=code):
            try:
                return se._fila_de_evento(code, ev)
            except Exception:
                return None
        with ThreadPoolExecutor(max_workers=hilos) as ex:
            box = list(ex.map(_uno, evs))
        for ev, b in zip(evs, box):
            fila = {'date': ev['fecha'], 'home_team': ev['home'],
                    'away_team': ev['away'],
                    'home_goals': ev['home_goals'],
                    'away_goals': ev['away_goals'],
                    'tournament': ev['tournament'], 'neutral': ev['neutral'],
                    'event_id': ev['event_id'],
                    'MATCH_ID': '%s_%s_%s' % (ev['fecha'].replace('-', ''),
                                              ev['home'].replace(' ', '-'),
                                              ev['away'].replace(' ', '-')),
                    'stats_origen': None}
            if b:
                for col in se.DERIVADAS:
                    for lado in ('home', 'away'):
                        k = '%s_%s' % (lado, col)
                        if b.get(k) is not None:
                            fila[k] = b[k]
                fila['stats_origen'] = 'espn'
            nuevos.append(fila)
        logger.info('[selecciones] %-26s %3d partidos nuevos, %3d con boxscore',
                    code, len(evs), sum(1 for b in box if b))
    if nuevos:
        d = pd.concat([previo, pd.DataFrame(nuevos)], ignore_index=True)
        d = d.drop_duplicates(subset=['event_id'], keep='last')
        d = d.sort_values('date').reset_index(drop=True)
        tmp = FICHERO + '.nuevo'
        d.to_csv(tmp, index=False)
        os.replace(tmp, FICHERO)
    else:
        d = previo
    con = int((d.get('stats_origen') == 'espn').sum()) if len(d) else 0
    return {'partidos': int(len(d)), 'nuevos': len(nuevos),
            'con_boxscore': con}


def main() -> int:
    sys.stdout.reconfigure(encoding='utf-8')
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    desde = None
    if '--desde' in sys.argv:
        desde = sys.argv[sys.argv.index('--desde') + 1]
    r = actualizar(desde=desde)
    print('historico de selecciones: %(partidos)d partidos, %(nuevos)d nuevos, '
          '%(con_boxscore)d con boxscore real' % r)
    return 0


if __name__ == '__main__':
    sys.exit(main())
