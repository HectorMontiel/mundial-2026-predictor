# -*- coding: utf-8 -*-
"""
v319 — CÓRNERS REALES DE FOTMOB PARA LAS LIGAS CUYO HISTÓRICO NO LOS TRAE.

El usuario pidió «integrar datos reales de córners históricos por equipo» y,
para las fuentes, «usa las que ya tienes; si no, FBref / WhoScored /
Sofascore / FootyStats». Ya la teníamos: `remates_fotmob.py` guarda, desde
julio, una fila por equipo y partido con sus córners (y desde la v319 sus
tarjetas) en `remates_fotmob_equipos.csv`. Ahí hay córners reales de ~20
competiciones que en su histórico no los tienen (Expansión MX, Primera
Nacional, Uruguay, Polonia, Suiza, Finlandia, Costa Rica, El Salvador,
Paraguay, Venezuela, Irlanda, Israel, la femenil…), y hasta ahora salían
con el número estimado.

EL MODELO: el mismo estimador que ganó en producción antes de la tabla
(ataque del equipo en su papel + lo que concede el rival en el suyo, medio y
medio), con la regla del histórico real: cada equipo con 5+ partidos en esa
competición. El total es la suma de los dos.

LO MEDIDO (2026-10-01, cada partido predicho sólo con los anteriores):
    estimador tal cual ........................ 70,7 %  (no pasa)
    con encogimiento 10 y dispersión ×1,5:
        ligas con histórico (para elegir) .... 77,4 %  (1.432 partidos)
        las 20 ligas nuevas (para juzgar) .... 77,7 %  (442 partidos)

SE ACTIVA SÓLO SI PASA SU BACKTEST (`backtest()`, con cada partido predicho
sólo con los anteriores): 200+ partidos y 72 %+ de acierto en la franja
70-80 %. El resultado queda en `corners_fotmob.json` y `lambdas` no hace nada
si dice que no pasó.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Dict, Optional

logger = logging.getLogger(__name__)

FICHERO = 'remates_fotmob_equipos.csv'
MEDICION = 'corners_fotmob.json'
MIN_PARTIDOS = 5
# Elegido con las ligas que SÍ tienen histórico de córners y juzgado en las 20
# que no (`_v319` en la cabecera): cada equipo se acerca a la media de su
# competición con un peso de 10 partidos, y la dispersión se abre un 50 %.
ENCOGER = 10
FACTOR_DISPERSION = 1.5
DIAS = {'selecciones': 730}
DIAS_CLUBES = 150
_MEM: Dict = {}


def _datos():
    import pandas as pd
    if 'df' in _MEM:
        return _MEM['df']
    if not os.path.exists(FICHERO):
        return None
    d = pd.read_csv(FICHERO, low_memory=False)
    d['fecha'] = pd.to_datetime(d['fecha'], errors='coerce')
    d = d.dropna(subset=['fecha', 'corners']).drop_duplicates(['match_id', 'equipo'])
    # lo que concedió cada equipo: los córners del rival en el mismo partido
    riv = d[['match_id', 'equipo', 'corners']].rename(
        columns={'equipo': 'rival', 'corners': 'concede'})
    d = d.merge(riv, on=['match_id', 'rival'], how='inner')
    _MEM['df'] = d.sort_values('fecha').reset_index(drop=True)
    return _MEM['df']


def _dispersion(d) -> float:
    """Varianza / media de los córners por equipo de esa competición."""
    m, v = float(d['corners'].mean()), float(d['corners'].var())
    return float(min(2.5, max(1.0, v / m))) if m > 0 else 1.5


def _calcular(dl, home: str, away: str) -> Optional[Dict]:
    """Con las filas de una competición ANTERIORES al partido."""
    hr_, ar_ = dl[dl['equipo'] == home], dl[dl['equipo'] == away]
    if len(hr_) < MIN_PARTIDOS or len(ar_) < MIN_PARTIDOS:
        return None
    casa = hr_[hr_['local'] == 1]
    fuera = ar_[ar_['local'] == 0]

    def media(x, alt):
        return float(x.mean()) if len(x) >= 2 else float(alt.mean())
    w_h = len(hr_) / (len(hr_) + ENCOGER)
    w_a = len(ar_) / (len(ar_) + ENCOGER)
    lg_h = float(dl[dl['local'] == 1]['corners'].mean())
    lg_a = float(dl[dl['local'] == 0]['corners'].mean())
    lh = w_h * (media(casa['corners'], hr_['corners'])
                + media(fuera['concede'], ar_['concede'])) / 2 + (1 - w_h) * lg_h
    la = w_a * (media(fuera['corners'], ar_['corners'])
                + media(casa['concede'], hr_['concede'])) / 2 + (1 - w_a) * lg_a
    disp = _dispersion(dl) * FACTOR_DISPERSION
    return {'lambda_home': round(lh, 3), 'lambda_away': round(la, 3),
            'lambda_total': round(lh + la, 3), 'dispersion': disp,
            'dispersion_total': disp, 'origen': 'observado',
            'base': 'FotMob: córners reales de cada equipo en sus últimos partidos',
            'fuente_lambda': 'fotmob', 'historico_real': True,
            'n_local': int(len(hr_)), 'n_visita': int(len(ar_)),
            'n_local_casa': int(len(casa)), 'n_visita_fuera': int(len(fuera)),
            'prom_local_casa': round(float(casa['corners'].mean()), 2) if len(casa) else None,
            'prom_visita_fuera': round(float(fuera['corners'].mean()), 2) if len(fuera) else None,
            'total': 'suma de los dos equipos', 'clave_liga': None}


def _ventana(d, clave, fecha):
    import pandas as pd
    dias = DIAS.get(clave, DIAS_CLUBES)
    return d[(d['liga'] == clave) & (d['fecha'] < fecha)
             & (d['fecha'] >= fecha - pd.Timedelta(days=dias))]


def activo() -> bool:
    try:
        return bool(json.load(open(MEDICION, encoding='utf-8')).get('activo'))
    except Exception:
        return False


def lambdas(clave: str, home: str, away: str, fecha=None) -> Optional[Dict]:
    """Córners de FotMob del partido, o None (sin 5 partidos de cada equipo,
    o el backtest no pasó). Nunca lanza."""
    try:
        import pandas as pd
        if not activo():
            return None
        d = _datos()
        if d is None:
            return None
        try:
            import historico_real as _hr
            ref = fecha if fecha is not None else _hr.FECHA
        except Exception:
            ref = fecha
        f = pd.Timestamp(ref) if ref is not None else pd.Timestamp.now()
        dl = _ventana(d, clave, f)
        # los nombres del motor y los de FotMob no siempre coinciden
        # («Penarol» / «Peñarol»): la misma resolución que `remates_fotmob`
        try:
            import remates_fotmob as _rf
            cands = sorted(dl['equipo'].dropna().unique())
            home = _rf._resolver_equipo(home, cands) or home
            away = _rf._resolver_equipo(away, cands) or away
        except Exception:
            pass
        r = _calcular(dl, home, away)
        if r:
            r['clave_liga'] = clave
        return r
    except Exception as e:
        logger.debug('[corners_fotmob] %s %s-%s: %s', clave, home, away, e)
        return None


def backtest(guardar: bool = True) -> Dict:
    """Cada partido de la base, predicho sólo con los anteriores."""
    import numpy as np
    import pandas as pd
    import rendimiento_equipos as rq
    d = _datos()
    sin_hist = {l for l in d['liga'].unique()
                if not (rq.stats_disponibles(l) or {}).get('corners')}
    filas = []
    partidos = d[d['local'] == 1][['match_id', 'fecha', 'liga', 'equipo', 'rival',
                                   'corners', 'concede']]
    for r in partidos.itertuples(index=False):
        x = _calcular(_ventana(d, r.liga, r.fecha), r.equipo, r.rival)
        if not x:
            continue
        for tipo, lam, disp, real, lineas in (
                ('total', x['lambda_total'], x['dispersion_total'], r.corners + r.concede,
                 (7.5, 8.5, 9.5, 10.5, 11.5, 12.5)),
                ('local', x['lambda_home'], x['dispersion'], r.corners, (2.5, 3.5, 4.5, 5.5, 6.5)),
                ('visita', x['lambda_away'], x['dispersion'], r.concede, (2.5, 3.5, 4.5, 5.5, 6.5))):
            for L in lineas:
                p = rq.prob_mas_de(lam, L, disp)
                if p is None:
                    continue
                y = int(real > L)
                for pp, yy in ((p, y), (1 - p, 1 - y)):
                    filas.append({'mid': r.match_id, 'liga': r.liga, 'tipo': tipo,
                                  'p': pp, 'y': yy, 'sin_hist': r.liga in sin_hist})
    P = pd.DataFrame(filas)
    banda = P[(P.p >= .70) & (P.p <= .80)]

    def res(z):
        return {'n': int(len(z)), 'partidos': int(z['mid'].nunique()),
                'acierto': round(float(z['y'].mean()), 4) if len(z) else None}
    out = {'partidos_predichos': int(P['mid'].nunique()) if len(P) else 0,
           'franja_70_80_todas': res(banda),
           'franja_70_80_ligas_sin_historico': res(banda[banda.sin_hist]),
           'franja_70_80_ligas_con_historico': res(banda[~banda.sin_hist]),
           'ligas_sin_historico': sorted(sin_hist)}
    obj = out['franja_70_80_ligas_sin_historico']
    out['activo'] = bool(obj['partidos'] >= 200 and (obj['acierto'] or 0) >= 0.72)
    if guardar:
        json.dump(out, open(MEDICION, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    return out


if __name__ == '__main__':
    print(json.dumps(backtest(), ensure_ascii=False, indent=1))
