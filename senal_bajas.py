# -*- coding: utf-8 -*-
"""
v338 — ¿LAS BAJAS AVISAN ANTES QUE LA CUOTA? SE MIDE SOLO, CADA PRECÁLCULO.

EL ENCARGO, con las palabras del usuario: «sí, quiero que dejes funcionando
eso». La v336 midió con football-data (3.506 partidos, Pinnacle de apertura
y cierre) que las bajas NO mejoran el pronóstico de la apertura, pero SÍ
anticipan hacia dónde se mueve el más de 2,5 (correlación 0,15; −1,22 pts
cuando dicen −2), y que apostando a la apertura con esa señal se ganó al
cierre un 4,2 % — en sólo 70 apuestas. Falta muestra, y sólo la da el tiempo.

DOS PIEZAS, LAS DOS AUTOMÁTICAS
  · `registrar(pronosticos)` — lo llama `alpha_finder` en cada barrido, justo
    después de aplicar las bajas (`bajas_modelo`). Por cada partido de fútbol
    con bajas que muevan sus goles, apunta en `senal_bajas.csv` la hora, las
    λ sin y con bajas, lo que eso mueve el más de 2,5, y la cuota de Playdoit
    del más/menos 2,5 EN ESE MOMENTO. Sólo escribe si algo cambió desde la
    última fila de ese partido (que el fichero no crezca por repetir lo mismo).
    Sólo en GitHub Actions: la app en Streamlit no escribe.
  · `medir()` — en cada precálculo. Para cada partido ya jugado con señal
    (las bajas mueven el más de 2,5 al menos 2 pts): la cuota del PRIMER aviso
    frente a la última antes del inicio («le gana al cierre», CLV) y frente
    al resultado (rendimiento), con bootstrap por día. Deja `senal_bajas.json`.

NO APUESTA NADA. El informe dice «listo para decidir» sólo con ≥ 300 señales
y p5 > 0 en el CLV y en el rendimiento; entonces se mide la regla como todas.

Uso:  python senal_bajas.py --medir
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import logging
import math
import os
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

FICHERO = 'senal_bajas.csv'
INFORME = 'senal_bajas.json'
UMBRAL_SENAL = 0.02          # lo que tienen que mover el más de 2,5
MINIMO_DECIDIR = 300
CAMPOS = ['capturado', 'fecha', 'clave_liga', 'partido', 'inicio', 'f_local',
          'f_visita', 'lam0', 'lam1', 'p25_0', 'p25_1', 'c_mas25', 'c_menos25']


def _p_mas25(lam: float) -> float:
    acc, term = 0.0, math.exp(-lam)
    for i in range(3):
        acc += term
        term *= lam / (i + 1)
    return 1.0 - acc


def _f(x) -> Optional[float]:
    try:
        v = float(x)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def _ultimas() -> Dict[str, Dict]:
    ult = {}
    if not os.path.exists(FICHERO):
        return ult
    try:
        with open(FICHERO, encoding='utf-8', newline='') as fh:
            for r in csv.DictReader(fh):
                ult[(r.get('fecha'), r.get('partido'))] = r
    except Exception as e:
        logger.debug('[senal_bajas] lectura: %s', e)
    return ult


def fila(p: Dict, ahora: str) -> Optional[Dict]:
    """La fila de un pronóstico con bajas, o None si no hay nada que apuntar."""
    if str(p.get('deporte') or 'Fútbol') != 'Fútbol' or not p.get('ajuste_bajas'):
        return None
    ab = p['ajuste_bajas']
    gx = p.get('goles_xg') or {}
    lh1, la1 = _f(gx.get('local')), _f(gx.get('visitante'))
    fl, fv = _f((ab.get('local') or {}).get('factor')), _f((ab.get('visitante') or {}).get('factor'))
    if None in (lh1, la1, fl, fv) or fl <= 0 or fv <= 0:
        return None
    lam1 = lh1 + la1
    lam0 = lh1 / fl + la1 / fv
    g25 = ((p.get('implicitas') or {}).get('goles') or {}).get('2.5') or {}
    return {'capturado': ahora, 'fecha': p.get('fecha'), 'clave_liga': p.get('clave_liga'),
            'partido': p.get('partido'), 'inicio': p.get('inicio'),
            'f_local': round(fl, 4), 'f_visita': round(fv, 4),
            'lam0': round(lam0, 3), 'lam1': round(lam1, 3),
            'p25_0': round(_p_mas25(lam0), 4), 'p25_1': round(_p_mas25(lam1), 4),
            'c_mas25': g25.get('mas'), 'c_menos25': g25.get('menos')}


def registrar(pronosticos: List[Dict], forzar: bool = False) -> int:
    """Apunta las señales nuevas o cambiadas. Devuelve cuántas filas escribe."""
    if not forzar and not os.environ.get('GITHUB_ACTIONS'):
        return 0
    ahora = dt.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')
    ult = _ultimas()
    nuevas = []
    for p in pronosticos or []:
        try:
            r = fila(p, ahora)
        except Exception as e:
            logger.debug('[senal_bajas] %s: %s', p.get('partido'), e)
            continue
        if not r:
            continue
        prev = ult.get((r['fecha'], r['partido']))
        # se compara como número: en el CSV una cuota vacía es '' y aquí None
        if prev and all(_f(prev.get(k)) == _f(r[k]) for k in
                        ('f_local', 'f_visita', 'c_mas25', 'c_menos25')):
            continue
        nuevas.append(r)
    if not nuevas:
        return 0
    nuevo = not os.path.exists(FICHERO)
    with open(FICHERO, 'a', encoding='utf-8', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=CAMPOS)
        if nuevo:
            w.writeheader()
        w.writerows(nuevas)
    logger.info('[senal_bajas] %d filas nuevas', len(nuevas))
    return len(nuevas)


def _resultados() -> Dict:
    """(fecha, partido) -> (goles local, goles visita), de lo ya liquidado."""
    out = {}
    try:
        d = json.load(open('pronosticos_emitidos.json', encoding='utf-8'))
    except Exception:
        return out
    for v in (d or {}).values():
        gh, ga = v.get('goles_home'), v.get('goles_away')
        if gh is None or ga is None:
            continue
        out[(str(v.get('fecha'))[:10], v.get('partido'))] = (int(gh), int(ga))
    return out


def medir() -> Dict:
    import numpy as np
    import pandas as pd
    if not os.path.exists(FICHERO):
        doc = {'senales': 0, 'listo_para_decidir': False, 'motivo': 'todavía no hay registro'}
        json.dump(doc, open(INFORME, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        return doc
    d = pd.read_csv(FICHERO)
    d['cap'] = pd.to_datetime(d.capturado, utc=True, errors='coerce')
    d['ini'] = pd.to_datetime(d.inicio, utc=True, errors='coerce')
    d = d[d.cap.notna() & d.ini.notna() & (d.cap < d.ini)]
    res = _resultados()
    filas = []
    for (fecha, partido), g in d.sort_values('cap').groupby(['fecha', 'partido']):
        primera = g.iloc[0]
        mov = primera.p25_1 - primera.p25_0
        if abs(mov) < UMBRAL_SENAL:
            continue
        mas = mov > 0
        col = 'c_mas25' if mas else 'c_menos25'
        c0 = _f(primera[col])
        cierre = g[g[col].notna()]
        c1 = _f(cierre.iloc[-1][col]) if len(cierre) else None
        r = res.get((str(fecha)[:10], partido))
        filas.append({'fecha': str(fecha)[:10], 'partido': partido, 'mas': mas,
                      'mov': mov, 'c0': c0, 'c1': c1,
                      'gana': None if r is None else int(((r[0] + r[1]) > 2.5) == mas)})
    s = pd.DataFrame(filas)
    doc = {'generado': dt.datetime.utcnow().strftime('%Y-%m-%dT%H:%MZ'),
           'partidos_registrados': int(d.groupby(['fecha', 'partido']).ngroups),
           'senales': int(len(s)), 'umbral': UMBRAL_SENAL, 'minimo': MINIMO_DECIDIR}
    rng = np.random.default_rng(338)

    def boot(x: pd.DataFrame, col: str):
        g = x.groupby('fecha')[col].agg(['sum', 'size']).values
        if len(g) < 3:
            return None
        b = [g[rng.integers(0, len(g), len(g))].sum(axis=0) for _ in range(2000)]
        b = [q[0] / q[1] for q in b]
        return float(np.percentile(b, 5))
    if len(s):
        c = s[s.c0.notna() & s.c1.notna()].copy()
        c['clv'] = c.c0 / c.c1 - 1
        j = s[s.c0.notna() & s.gana.notna()].copy()
        j['dev'] = j.gana * j.c0 - 1
        doc.update({'con_cierre': int(len(c)),
                    'clv_medio': float(c.clv.mean()) if len(c) else None,
                    'clv_p5': boot(c, 'clv') if len(c) else None,
                    'liquidadas': int(len(j)),
                    'acierto': float(j.gana.mean()) if len(j) else None,
                    'rinde': float(j.dev.mean()) if len(j) else None,
                    'rinde_p5': boot(j, 'dev') if len(j) else None})
    listo = (doc.get('liquidadas', 0) >= MINIMO_DECIDIR
             and (doc.get('clv_p5') or -1) > 0 and (doc.get('rinde_p5') or -1) > 0)
    doc['listo_para_decidir'] = bool(listo)
    doc['motivo'] = ('pasa: medir la regla como todas antes de activarla' if listo else
                     'faltan señales (%d de %d liquidadas)' % (doc.get('liquidadas', 0), MINIMO_DECIDIR)
                     if doc.get('liquidadas', 0) < MINIMO_DECIDIR else
                     'hay muestra pero no gana al cierre o no rinde (p5 ≤ 0)')
    json.dump(doc, open(INFORME, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    return doc


if __name__ == '__main__':
    import sys
    logging.basicConfig(level=logging.INFO)
    if '--medir' in sys.argv:
        print(json.dumps(medir(), ensure_ascii=False, indent=1))
