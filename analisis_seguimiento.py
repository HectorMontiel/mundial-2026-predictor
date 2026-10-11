# -*- coding: utf-8 -*-
"""
v361 — EL SEGUIMIENTO DEL ANÁLISIS: QUÉ SE CUMPLIÓ DEL «MÉTODO CONTEXTO».

El usuario: «de todas esas estadísticas quiero saber cuál se cumplió y cuál
no —probablemente no están en las apuestas del día—, para empezar a analizar
patrones y poder meterlas, con simulaciones del histórico, lo reciente y las
últimas semanas».

Cada precálculo apunta, de los partidos de fútbol por jugar, lo que la tabla
del análisis dice (`modo_modelo.metodo_contexto`: la línea «más de» del total
que el método ve al 70 % o más, por estadística). Cuando el partido termina,
se pone lo que pasó: los goles del marcador y córners, tarjetas, tiros y a
puerta de la ficha de FotMob (`partidos_jugados._stats_de_fotmob`; ESPN no
tiene las ligas europeas después del 20-sep en este calendario). Fichero:
`analisis_seguimiento.csv`. Nunca lanza.
"""
from __future__ import annotations

import datetime as _dt
import json
import logging
import os
from typing import Dict, List, Optional

import pandas as pd

logger = logging.getLogger('analisis_seguimiento')

FICHERO = 'analisis_seguimiento.csv'
CAMPOS = ['dia', 'partido', 'clave_liga', 'inicio', 'obj', 'local', 'visita', 'total',
          'linea', 'p', 'real', 'cumple']
# la estadística de la ficha que corresponde a cada objetivo
_STAT = {'corners': ('corners_home', 'corners_away'),
         'tarjetas': ('tarjetas_home', 'tarjetas_away'),
         'tiros': ('remates_home', 'remates_away'),
         'a_puerta': ('remates_on_home', 'remates_on_away')}
MAX_FICHAS = 120          # fichas de FotMob por pasada (cada una ~0,5 s)


_CACHE: Dict = {}


def _leer(ruta: str = FICHERO) -> pd.DataFrame:
    """El fichero, recordado mientras no cambie (la tarjeta lo pide por
    partido). Siempre una copia."""
    try:
        mt = os.path.getmtime(ruta)
    except OSError:
        return pd.DataFrame(columns=CAMPOS)
    if _CACHE.get('k') != (ruta, mt):
        try:
            d = pd.read_csv(ruta)
            for c in CAMPOS:
                if c not in d:
                    d[c] = None
            _CACHE.update(k=(ruta, mt), d=d[CAMPOS])
        except Exception:
            return pd.DataFrame(columns=CAMPOS)
    return _CACHE['d'].copy()


def _dia(p: Dict) -> str:
    try:
        import partidos_jugados as pj
        return pj.dia_de_partido(p)
    except Exception:
        return str(p.get('fecha') or '')[:10]


def registrar(pronosticos: List[Dict], ruta: str = FICHERO,
              ahora: Optional[float] = None) -> int:
    """Apunta (o actualiza, mientras no empiece) la tabla del análisis de los
    partidos de fútbol por jugar. Devuelve cuántas filas puso."""
    try:
        import time
        import horario as hz
        import modo_modelo as mm
        ahora = float(ahora if ahora is not None else time.time())
        nuevas = []
        for p in pronosticos or []:
            if str(p.get('deporte') or 'Fútbol') != 'Fútbol' or p.get('jugado'):
                continue
            ini = hz._a_utc(p.get('inicio'))
            if ini is None or ini.timestamp() <= ahora:
                continue
            for obj, x in mm.metodo_contexto(p).items():
                if not x.get('metodo') or x.get('linea') is None:
                    continue
                nuevas.append({'dia': _dia(p), 'partido': p.get('partido'),
                               'clave_liga': p.get('clave_liga'), 'inicio': p.get('inicio'),
                               'obj': obj, 'local': round(x['local'], 3),
                               'visita': round(x['visita'], 3), 'total': round(x['total'], 3),
                               'linea': x['linea'], 'p': round(x['p'], 4),
                               'real': None, 'cumple': None})
        if not nuevas:
            return 0
        d = _leer(ruta)
        n = pd.DataFrame(nuevas)
        clave = lambda x: x.dia.astype(str) + '|' + x.partido.astype(str) + '|' + x.obj.astype(str)
        if len(d):
            d = d[~(clave(d).isin(set(clave(n))) & d.real.isna())]
        pd.concat([d, n], ignore_index=True)[CAMPOS].to_csv(ruta, index=False)
        return len(n)
    except Exception as e:
        logger.warning('[análisis] no se pudo registrar: %s', e)
        return 0


def _jugados() -> Dict[tuple, Dict]:
    out = {}
    for ruta in ('jugados_ayer.json', 'jugados_dia.json'):
        try:
            doc = json.load(open(ruta, encoding='utf-8'))
        except Exception:
            continue
        for p in doc.get('partidos') or []:
            out[(str(doc.get('dia')), str(p.get('partido')))] = p
    return out


def liquidar(ruta: str = FICHERO, maximo: int = MAX_FICHAS) -> int:
    """Pone lo que pasó a lo ya jugado. Devuelve cuántas filas liquidó."""
    try:
        import partidos_jugados as pj
        d = _leer(ruta)
        if d.empty:
            return 0
        pend = d[d.real.isna()]
        if pend.empty:
            return 0
        jug = _jugados()
        fichas: Dict[str, Optional[Dict]] = {}
        lista_fm: Dict[str, list] = {}
        n = 0
        pedidas = 0
        for i, r in pend.iterrows():
            p = jug.get((str(r.dia), str(r.partido)))
            if not p or p.get('goles_home') is None:
                continue
            if r.obj == 'goles':
                real = float(p['goles_home']) + float(p['goles_away'])
            else:
                k = str(r.partido) + '|' + str(r.dia)
                if k not in fichas:
                    st = p.get('stats_partido')
                    if not st and pedidas < maximo:
                        pedidas += 1
                        mid = p.get('fotmob_id')
                        if not mid:
                            if str(r.dia) not in lista_fm:
                                lista_fm[str(r.dia)] = pj.marcadores_fotmob(str(r.dia))
                            f = pj._casar_fotmob(p, lista_fm[str(r.dia)])
                            mid = f.get('id') if f else None
                        st = pj._stats_de_fotmob(mid) if mid else None
                    fichas[k] = st
                st = fichas.get(k)
                a, b = _STAT[r.obj]
                if not st or st.get(a) is None or st.get(b) is None:
                    continue
                real = float(st[a]) + float(st[b])
            d.loc[i, 'real'] = real
            d.loc[i, 'cumple'] = int(real > float(r.linea))
            n += 1
        d[CAMPOS].to_csv(ruta, index=False)
        return n
    except Exception as e:
        logger.warning('[análisis] no se pudo liquidar: %s', e)
        return 0


def resumen(ruta: str = FICHERO, dias: int = 14, hoy: Optional[str] = None) -> Dict:
    """{obj: {'n', 'verdes', 'acierto', 'promete'}} de los últimos `dias`."""
    d = _leer(ruta)
    d = d[d.cumple.notna()]
    if d.empty:
        return {}
    hoy = hoy or _dt.date.today().isoformat()
    desde = (_dt.date.fromisoformat(hoy) - _dt.timedelta(days=dias)).isoformat()
    d = d[d.dia.astype(str) >= desde]
    out = {}
    for obj, g in d.groupby('obj'):
        out[obj] = {'n': int(len(g)), 'verdes': int(g.cumple.astype(float).sum()),
                    'acierto': round(float(g.cumple.astype(float).mean()), 4),
                    'promete': round(float(g.p.astype(float).mean()), 4)}
    return out


def del_partido(pick: Dict, ruta: str = FICHERO) -> Dict:
    """{obj: fila} de un partido ya jugado (para pintar ✅/❌ en su análisis)."""
    try:
        d = _leer(ruta)
        g = d[(d.partido.astype(str) == str(pick.get('partido')))
              & (d.dia.astype(str) == _dia(pick))]
        return {r.obj: r._asdict() for r in g.itertuples(index=False)}
    except Exception:
        return {}
