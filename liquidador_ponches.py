#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v115 — Liquidación de las recomendaciones de PONCHES y de las COMBINADAS.

Por qué existe
--------------
Es la propuesta nº 1 de la auditoría, y la que motivó todo: el usuario apostó
cinco líneas de ponches, acertó una, y **no había forma de saber si eso fue
mala suerte o un sesgo del modelo** salvo auditando a mano. Lo fue: la v115
encontró que `bf_apertura` inflaba el λ medio ponche. Pero esa auditoría duró
horas y sólo se hizo porque el usuario lo reportó.

`liquidador.py` ya cierra el círculo del 1X2, los goles, el BTTS y el hándicap.
Lo que quedaba fuera es justo lo que la app recomienda con más énfasis:

  · **ponches del abridor** — el mercado de la regla de MLB;
  · **combinadas** — se proponen varias por partido y ninguna se comprobaba.

Cómo se resuelve un ponche
--------------------------
Con el registro por juego del propio lanzador (`gameLog` de MLB StatsAPI, la
misma fuente oficial que ya usa el proyecto): una petición por lanzador
devuelve todas sus salidas de la temporada con sus ponches. Se busca la del día
del partido y se compara con la línea.

Si no se encuentra —el nombre no casa, el lanzador no abrió, la fecha no
aparece— **no se inventa un resultado**: queda pendiente y se cuenta como tal.
Un pick sin liquidar es información; un pick liquidado a ciegas es basura que
además contamina la tasa de acierto.

Cómo se resuelve una combinada
------------------------------
Una combinada acierta si aciertan TODAS sus patas. Cada pata se registra como
un pick normal con `canal='combinada:<id>'`, así que se liquidan solas con el
resto del sistema; aquí sólo se agrega el veredicto conjunto.

Uso:
    python liquidador_ponches.py              # liquida lo pendiente
    python liquidador_ponches.py --dias 21
"""
import argparse
import logging
import re
import sqlite3
import unicodedata
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

DB = 'rendimiento_real.db'
API = 'https://statsapi.mlb.com/api/v1'
MERCADO_PONCHES = 'Ponches del abridor'
# Una apertura de verdad. Por debajo el lanzador se fue temprano, pero la
# apuesta se liquida igual: lo que cuenta son los ponches que hizo.
_TIMEOUT = 25


def _norm(nombre: str) -> str:
    """Clave de comparación de nombres de lanzador."""
    s = unicodedata.normalize('NFKD', str(nombre or ''))
    s = ''.join(c for c in s if not unicodedata.combining(c)).lower()
    for basura in (' jr.', ' jr', ' sr.', ' sr', ' iii', ' ii', '.'):
        s = s.replace(basura, ' ')
    return ' '.join(s.split())


def _get(url: str, params: dict) -> dict:
    import requests
    try:
        r = requests.get(url, params=params, timeout=_TIMEOUT)
        return r.json() if r.status_code == 200 else {}
    except Exception as e:
        logger.debug(f'[liq/ponches] {url}: {type(e).__name__}: {e}')
        return {}


_IDS: Dict[str, int] = {}


def _indice_lanzadores(temporada: int) -> Dict[str, int]:
    """{nombre normalizado: id} de todos los lanzadores de la temporada."""
    clave = f'ids_{temporada}'
    if clave in _IDS:
        return _IDS[clave]
    j = _get(f'{API}/sports/1/players', {'season': temporada})
    idx = {}
    for p in (j.get('people') or []):
        if (p.get('primaryPosition') or {}).get('abbreviation') != 'P':
            continue
        idx[_norm(p.get('fullName'))] = p.get('id')
        # muchas casas escriben «R. Vásquez» o sólo el apellido
        _ape = _norm(p.get('lastName') or '')
        if _ape and _ape not in idx:
            idx[_ape] = p.get('id')
    _IDS[clave] = idx
    logger.info(f'[liq/ponches] {len(idx)} lanzadores indexados de {temporada}')
    return idx


def ponches_reales(nombre: str, fecha: str,
                   temporada: Optional[int] = None) -> Optional[int]:
    """
    Ponches que hizo ese lanzador ese día, o None si no se puede saber.

    None no es un fallo: es la respuesta correcta cuando el lanzador no abrió,
    el nombre no casa o la fecha no aparece en su registro. Lo que no se puede
    hacer es devolver un número inventado.
    """
    try:
        anio = int(temporada or str(fecha)[:4])
    except (TypeError, ValueError):
        return None
    idx = _indice_lanzadores(anio)
    pid = idx.get(_norm(nombre))
    if pid is None:
        # último intento por apellido, que es como lo publican algunas casas
        pid = idx.get(_norm(str(nombre).split()[-1])) if nombre else None
    if pid is None:
        logger.info(f'[liq/ponches] lanzador no identificado: «{nombre}»')
        return None
    j = _get(f'{API}/people/{pid}/stats',
             {'stats': 'gameLog', 'season': anio, 'group': 'pitching'})
    dia = str(fecha)[:10]
    for s in ((j.get('stats') or [{}])[0].get('splits') or []):
        if str(s.get('date'))[:10] != dia:
            continue
        try:
            return int((s.get('stat') or {}).get('strikeOuts'))
        except (TypeError, ValueError):
            return None
    return None


def _linea_y_lado(apuesta: str):
    """
    De «Randy Vásquez: más de 2.5 ponches» → ('Randy Vásquez', 'over', 2.5).

    Devuelve (None, None, None) si el texto no tiene la forma esperada: es
    preferible dejar el pick pendiente a adivinar el lado de la apuesta.
    """
    t = str(apuesta or '')
    m = re.search(r'(m[áa]s|menos|over|under)\s+de\s+(\d+(?:[.,]\d+)?)', t, re.I)
    if not m:
        return None, None, None
    lado = 'over' if m.group(1).lower() in ('más', 'mas', 'over') else 'under'
    try:
        linea = float(m.group(2).replace(',', '.'))
    except ValueError:
        return None, None, None
    pitcher = t.split(':')[0].strip() if ':' in t else t[:m.start()].strip()
    return (pitcher or None), lado, linea


def resolver_ponches(apuesta: str, fecha: str) -> Optional[bool]:
    """¿Acertó esta apuesta de ponches? None = todavía no se puede saber."""
    pitcher, lado, linea = _linea_y_lado(apuesta)
    if not pitcher or linea is None:
        return None
    k = ponches_reales(pitcher, fecha)
    if k is None:
        return None
    return (k > linea) if lado == 'over' else (k < linea)


# ---------------------------------------------------------------------------
def liquidar_ponches(dias: int = 21) -> Dict:
    """Resuelve los picks de ponches pendientes cuyo partido ya terminó."""
    import os

    import pandas as pd
    if not os.path.exists(DB):
        return {'liquidados': 0, 'aviso': f'Sin {DB}.'}
    import rendimiento_real
    con = sqlite3.connect(DB)
    desde = (pd.Timestamp.today() - pd.Timedelta(days=dias)).strftime('%Y-%m-%d')
    try:
        pend = pd.read_sql_query(
            "SELECT fecha, partido, apuesta FROM picks "
            "WHERE resultado IS NULL AND fecha >= ? AND mercado = ?",
            con, params=[desde, MERCADO_PONCHES])
    except Exception as e:
        con.close()
        return {'liquidados': 0, 'aviso': f'{type(e).__name__}: {e}'}
    con.close()
    if pend.empty:
        return {'liquidados': 0, 'pendientes': 0,
                'aviso': 'No hay picks de ponches pendientes.'}

    # Los de HOY también se intentan: el registro oficial sólo publica la
    # línea del lanzador cuando el juego ha terminado, así que la propia
    # fuente hace de guardia. Saltárselos por fecha retrasaba un día entero la
    # liquidación de los partidos de la tarde sin ganar nada a cambio.
    mañana = pd.Timestamp.today().normalize() + pd.Timedelta(days=1)
    liquidados = sin_dato = 0
    for _, p in pend.iterrows():
        try:
            if pd.Timestamp(str(p['fecha'])) >= mañana:
                continue                    # todavía no se ha jugado
        except Exception:
            pass
        acerto = resolver_ponches(str(p['apuesta']), str(p['fecha']))
        if acerto is None:
            sin_dato += 1
            continue
        if rendimiento_real.liquidar(str(p['fecha']), str(p['partido']),
                                     str(p['apuesta']), bool(acerto)):
            liquidados += 1
    logger.info(f'[liq/ponches] {liquidados} liquidados · {sin_dato} sin dato')
    return {'liquidados': liquidados, 'sin_dato': sin_dato,
            'pendientes': int(len(pend))}


def registrar_ponches(veredictos: List[Dict], fecha: Optional[str] = None) -> int:
    """
    Registra como picks las recomendaciones de ponches que la app emite.

    Se guardan con el mismo esquema que el resto (`rendimiento_real.picks`),
    con `canal='regla_usuario'` para que se puedan medir aparte: la regla de
    MLB es del usuario, no una estrategia validada del proyecto, y mezclarlas
    en la misma tasa de acierto sería confundir dos cosas distintas.
    """
    import pandas as pd
    import rendimiento_real
    fecha = fecha or pd.Timestamp.today().strftime('%Y-%m-%d')
    picks = []
    for v in (veredictos or []):
        if not v.get('entra') or not v.get('apuesta'):
            continue
        if 'ponche' not in str(v.get('mercado', '')).lower():
            continue
        picks.append({
            'fecha': fecha, 'deporte': 'MLB', 'liga': 'MLB',
            'partido': v.get('partido') or '',
            'mercado': MERCADO_PONCHES,
            'apuesta': v.get('apuesta'),
            'prob': v.get('prob'), 'cuota': v.get('cuota'),
            'ev': v.get('ev'), 'canal': 'regla_usuario',
        })
    if not picks:
        return 0
    n = rendimiento_real.registrar(picks, capa='regla_mlb')
    logger.info(f'[liq/ponches] {n} recomendaciones de ponches registradas')
    return n


def resumen_ponches(dias: int = 60) -> Dict:
    """
    Cómo van las recomendaciones de ponches: cuántas cerradas, cuántas
    acertadas y qué ROI habrían dado a stake plano.

    Se cuentan APARTE del resto de picks, por `canal='regla_usuario'`. La regla
    de MLB la fijó el usuario y no está validada contra el histórico del
    proyecto; meterla en la tasa global la disfrazaría de estrategia medida.
    """
    import os

    import pandas as pd
    if not os.path.exists(DB):
        return {'n': 0, 'aviso': f'Sin {DB}.'}
    con = sqlite3.connect(DB)
    desde = (pd.Timestamp.today() - pd.Timedelta(days=dias)).strftime('%Y-%m-%d')
    try:
        df = pd.read_sql_query(
            "SELECT cuota, resultado FROM picks "
            "WHERE fecha >= ? AND mercado = ?", con, params=[desde,
                                                             MERCADO_PONCHES])
    except Exception as e:
        con.close()
        return {'n': 0, 'aviso': f'{type(e).__name__}: {e}'}
    con.close()
    if df.empty:
        return {'n': 0, 'pendientes': 0}
    pend = int(df['resultado'].isna().sum())
    cerr = df.dropna(subset=['resultado'])
    if cerr.empty:
        return {'n': 0, 'pendientes': pend}
    aciertos = int((cerr['resultado'] == 1).sum())
    # ROI a stake plano de 1 unidad: se gana (cuota − 1) al acertar y se pierde
    # 1 al fallar. Sin cuota no se puede calcular y esa fila no entra.
    con_cuota = cerr.dropna(subset=['cuota'])
    roi = None
    if not con_cuota.empty:
        ganancia = sum((float(r['cuota']) - 1.0) if r['resultado'] == 1 else -1.0
                       for _, r in con_cuota.iterrows())
        roi = round(ganancia / len(con_cuota), 4)
    return {'n': int(len(cerr)), 'aciertos': aciertos,
            'tasa': round(aciertos / len(cerr), 3),
            'roi': roi, 'pendientes': pend}


# ---------------------------------------------------------------------------
def registrar_combinada(partido: str, opcion: Dict, liga: str = '',
                        deporte: str = 'Fútbol',
                        fecha: Optional[str] = None) -> int:
    """
    Registra las patas de una combinada propuesta, para poder liquidarla.

    Cada pata va como un pick normal —así la resuelve el liquidador de siempre,
    sin código nuevo— con `canal='combinada'`. La combinada acierta si aciertan
    todas, y eso se calcula al leer, no al escribir: guardar el veredicto
    conjunto sería duplicar un dato que ya está en sus partes.
    """
    import pandas as pd
    import rendimiento_real
    fecha = fecha or pd.Timestamp.today().strftime('%Y-%m-%d')
    sels = (opcion or {}).get('selecciones') or []
    if not sels:
        return 0
    etiqueta = str((opcion or {}).get('etiqueta_opcion') or 'combinada')
    picks = [{
        'fecha': fecha, 'deporte': deporte, 'liga': liga, 'partido': partido,
        'mercado': s.get('mercado') or '', 'apuesta': s.get('apuesta') or '',
        'prob': s.get('prob'), 'cuota': s.get('cuota'),
        'ev': s.get('ev'), 'canal': f'combinada:{etiqueta}',
    } for s in sels if s.get('apuesta')]
    return rendimiento_real.registrar(picks, capa='combinada')


def resumen_combinadas(dias: int = 60) -> Dict:
    """
    Cuántas combinadas propuestas habrían entrado.

    Una combinada cuenta como acertada sólo si TODAS sus patas están
    liquidadas y todas acertaron. Las que tienen alguna pata pendiente no se
    cuentan en ningún lado — ni como acierto ni como fallo — porque todavía no
    se sabe.
    """
    import os

    import pandas as pd
    if not os.path.exists(DB):
        return {'n': 0, 'aviso': f'Sin {DB}.'}
    con = sqlite3.connect(DB)
    desde = (pd.Timestamp.today() - pd.Timedelta(days=dias)).strftime('%Y-%m-%d')
    try:
        df = pd.read_sql_query(
            "SELECT fecha, partido, canal, apuesta, cuota, resultado FROM picks "
            "WHERE fecha >= ? AND canal LIKE 'combinada%'", con,
            params=[desde])
    except Exception as e:
        con.close()
        return {'n': 0, 'aviso': f'{type(e).__name__}: {e}'}
    con.close()
    if df.empty:
        return {'n': 0, 'aviso': 'Todavía no se ha registrado ninguna combinada.'}
    acertadas = fallidas = pendientes = 0
    cuotas_ok = []
    for (_f, _p, _c), g in df.groupby(['fecha', 'partido', 'canal']):
        if g['resultado'].isna().any():
            pendientes += 1
            continue
        if (g['resultado'] == 1).all():
            acertadas += 1
            try:
                cuotas_ok.append(float(g['cuota'].astype(float).prod()))
            except Exception:
                pass
        else:
            fallidas += 1
    cerradas = acertadas + fallidas
    return {'n': cerradas, 'acertadas': acertadas, 'fallidas': fallidas,
            'pendientes': pendientes,
            'tasa': round(acertadas / cerradas, 3) if cerradas else None,
            'cuota_media_acertada': (round(sum(cuotas_ok) / len(cuotas_ok), 2)
                                     if cuotas_ok else None)}


def main() -> int:
    import sys
    for f in (sys.stdout, sys.stderr):
        try:
            f.reconfigure(encoding='utf-8', errors='replace')
        except Exception:
            pass
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--dias', type=int, default=21)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    r = liquidar_ponches(args.dias)
    print('ponches:', r)
    print('combinadas:', resumen_combinadas(args.dias * 3))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
