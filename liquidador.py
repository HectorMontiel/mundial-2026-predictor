#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v92 — Cierra el circuito: resuelve los picks publicados contra el resultado.

El agujero que tapa
-------------------
Desde la v32 el sistema registra cada día los picks que publica
(`rendimiento_real.registrar`) y promete en la interfaz que «el resultado se
liquida cuando termina el partido». No era verdad: **`liquidar()` no tenía un
solo llamador en todo el proyecto**. Medido el 2026-08-03: 315 picks
registrados, **0 liquidados**.

Las consecuencias no eran cosméticas. Sin liquidación:

  · el panel «Rendimiento real de las Apuestas del Día» lleva versiones vacío;
  · el informe mensual no puede existir;
  · `monitor_canales` no puede comparar producción con backtest;
  · y sobre todo: **no hay forma de saber si el edge validado se cobra**. Todo
    lo que el proyecto sabe de su propia rentabilidad viene de backtests sobre
    histórico. La retroalimentación real estaba desconectada.

Cómo funciona
-------------
Toma los picks pendientes cuyo partido ya pasó, pide a ESPN los resultados de
esas fechas (mismo scoreboard que ya se usa para los fixtures, coste cero) y
liquida cada apuesta contra el marcador.

Los mercados se resuelven con la MISMA semántica con la que se emitieron:
1X2, Goles (over/under con su línea), BTTS y Hándicap asiático con su línea.
Lo que no se sabe resolver **no se inventa**: se deja pendiente y se cuenta,
que es lo que permite saber si falta cobertura.

Uso:
    python liquidador.py            # liquida lo pendiente de los últimos días
    python liquidador.py --dias 14
"""
import argparse
import logging
import re
import sqlite3
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

DB = 'rendimiento_real.db'
# margen para que ESPN publique el resultado final (y para partidos largos)
HORAS_GRACIA = 6
# v93 — los picks de tenis y MLB se sellan con la fecha de PUBLICACIÓN, no con
# la del partido (el feed de cuotas no da una fecha fiable), así que hay que
# emparejar con holgura. Dos días: un partido anunciado hoy se juega hoy o
# mañana, y estirar más arriesgaría casar el enfrentamiento equivocado.
TOLERANCIA_DIAS = 2


# ---------------------------------------------------------------------------
# Resolución de cada mercado contra el marcador
# ---------------------------------------------------------------------------
def _num(txt: str) -> Optional[float]:
    m = re.search(r'(\d+(?:[.,]\d+)?)', str(txt).replace('−', '-'))
    return float(m.group(1).replace(',', '.')) if m else None


def resolver(mercado: str, apuesta: str, home: str, away: str,
             gl: int, gv: int) -> Optional[bool]:
    """
    ¿Ganó esta apuesta? None si el mercado no se sabe resolver.

    Devolver None a propósito —en vez de adivinar— es lo que hace fiable el
    ROI: una apuesta mal liquidada contamina la métrica para siempre y no deja
    rastro. Preferible contarla como pendiente.
    """
    a = str(apuesta or '').strip()
    m = str(mercado or '').strip().lower()
    al = a.lower()

    if m in ('1x2', 'ganador', 'moneyline'):
        if al.startswith('gana '):
            eq = a[5:].strip().lower()
            if eq == str(home).strip().lower():
                return gl > gv
            if eq == str(away).strip().lower():
                return gv > gl
            return None
        if al in ('empate', 'draw'):
            return gl == gv
        return None

    if m == 'goles':
        linea = _num(a)
        if linea is None:
            return None
        total = gl + gv
        if al.startswith('más') or al.startswith('mas') or al.startswith('over'):
            return total > linea
        if al.startswith('menos') or al.startswith('under'):
            return total < linea
        return None

    if m == 'btts':
        ambos = gl >= 1 and gv >= 1
        if 'sí' in al or 'si' in al.split(':')[-1] or al.endswith('yes'):
            return ambos
        if 'no' in al:
            return not ambos
        return None

    if m in ('hándicap', 'handicap'):
        # formato «Equipo +1.5» / «Equipo −1.5» (el signo puede ser − o -)
        mm = re.search(r'^(.*?)\s*([+\-−])\s*(\d+(?:[.,]\d+)?)\s*$', a)
        if not mm:
            return None
        eq, signo, val = mm.group(1).strip().lower(), mm.group(2), \
            float(mm.group(3).replace(',', '.'))
        linea = val if signo == '+' else -val
        if eq == str(home).strip().lower():
            margen = gl - gv
        elif eq == str(away).strip().lower():
            margen = gv - gl
        else:
            return None
        # líneas .5 → nunca hay empate (push); las enteras se dejan pendientes
        if abs(linea * 2 - round(linea * 2)) > 1e-9 or float(linea).is_integer():
            if float(linea).is_integer():
                return None            # push posible: no se liquida a ciegas
        return (margen + linea) > 0

    return None


# ---------------------------------------------------------------------------
# Búsqueda del resultado
# ---------------------------------------------------------------------------
def _resultados(claves: List[str], desde: str, hasta: str) -> Dict[Tuple, dict]:
    """{(fecha, home_norm, away_norm): resultado} de las ligas pedidas."""
    import fixtures_espn
    import name_mapper
    out: Dict[Tuple, dict] = {}
    for clave in claves:
        try:
            for r in fixtures_espn.resultados_liga(clave, desde, hasta):
                k = (r['fecha'], name_mapper.normalizar(r['home']),
                     name_mapper.normalizar(r['away']))
                out[k] = r
        except Exception as e:
            logger.debug(f'[liquidador] {clave}: {e}')
    return out


def _resultados_mlb(desde: str, hasta: str) -> Dict[Tuple, dict]:
    """
    v93 — {(fecha, home_norm, away_norm): resultado} de la MLB Stats API.

    Los picks de MLB se emiten con el nombre visible («Athletics @ Houston
    Astros») y la API devuelve códigos Retrosheet, así que se indexa por AMBOS:
    el código y el nombre normalizado. Sin esto los 143 picks pendientes de la
    v92 no habrían encontrado su partido.
    """
    out: Dict[Tuple, dict] = {}
    try:
        import mlb_statsapi
        import name_mapper
        from engines.mlb_engine import CODIGO_A_NOMBRE
    except Exception as e:
        logger.warning(f'[liquidador/mlb] no disponible: {e}')
        return out
    try:
        juegos = mlb_statsapi.resultados_entre(desde, hasta)
    except Exception as e:
        logger.warning(f'[liquidador/mlb] {type(e).__name__}: {e}')
        return out
    # v93: igual que el tenis, indexado por PAREJA y no por fecha exacta — los
    # picks de MLB también llevan la fecha del barrido, no la del juego.
    for g in juegos:
        r = {'goles_home': g['carreras_home'], 'goles_away': g['carreras_away']}
        for h in {g['home'], CODIGO_A_NOMBRE.get(g['home'], g['home'])}:
            for a in {g['away'], CODIGO_A_NOMBRE.get(g['away'], g['away'])}:
                out.setdefault((name_mapper.normalizar(h),
                                name_mapper.normalizar(a)), []).append(
                                    (g['fecha'], r))
    return out


def _resultados_tenis(desde: str, hasta: str) -> Dict[Tuple, list]:
    """
    v93 — {(jugador1_norm, jugador2_norm): [(fecha, ganador_norm), …]}.

    NO se indexa por fecha exacta, y ése es el punto. Los picks de tenis y MLB
    se sellan con la fecha de PUBLICACIÓN —el feed de cuotas no da una fecha de
    partido fiable, así que `_picks_tenis` usa el día del barrido—, mientras
    que ESPN fecha el partido cuando se jugó. Medido: «Anastasia Potapova vs
    Venus Williams» está registrado el 28 y se jugó el 29, y por ese día de
    diferencia sólo cerraba el 24 % de los picks de tenis antiguos.

    La pareja de jugadores es identificador suficiente: dos tenistas concretos
    no se enfrentan dos veces en la misma semana. Se empareja por pareja y se
    exige que el partido caiga dentro de `TOLERANCIA_DIAS` del pick.

    La clave usa el APELLIDO, no el nombre completo: las casas escriben
    «Bublik A.» y ESPN «Alexander Bublik».
    """
    out: Dict[Tuple, list] = {}
    try:
        import fixtures_espn
    except Exception as e:
        logger.warning(f'[liquidador/tenis] no disponible: {e}')
        return out
    for p in fixtures_espn.resultados_tenis(desde, hasta):
        j1, j2 = p['jugadores']
        k1, k2, kg = _clave_tenista(j1), _clave_tenista(j2), \
            _clave_tenista(p['ganador'])
        if not (k1 and k2 and kg):
            continue
        par = tuple(sorted((k1, k2)))
        out.setdefault(par, []).append((p['fecha'], kg))
    return out


def _buscar_con_tolerancia(indice: dict, clave, fecha: str,
                           dias: int = None):
    """
    Busca en el índice la entrada más cercana a `fecha`, dentro de la
    tolerancia. Devuelve None si no hay ninguna — nunca la más lejana «por si
    acaso»: liquidar el partido equivocado contamina el ROI en silencio.
    """
    import pandas as pd
    dias = TOLERANCIA_DIAS if dias is None else dias
    cands = indice.get(clave)
    if not cands:
        return None
    try:
        f0 = pd.Timestamp(fecha)
    except (ValueError, TypeError):
        return None
    mejor, mejor_d = None, None
    for f, valor in cands:
        try:
            d = abs((pd.Timestamp(f) - f0).days)
        except (ValueError, TypeError):
            continue
        if d <= dias and (mejor_d is None or d < mejor_d):
            mejor, mejor_d = valor, d
    return mejor


def _gano_tenis(apuesta: str, ganador_clave: str) -> Optional[bool]:
    """
    ¿Ganó este pick de tenis? None si no se sabe leer la apuesta.

    Sólo se resuelve «Gana X», que es el único mercado de tenis que el sistema
    emite como pick. Los 19 mercados derivados de la plantilla (sets, juegos,
    hándicaps) son informativos y se dejan pendientes a propósito: liquidarlos
    exigiría el marcador por sets, que ESPN no da en el scoreboard.
    """
    a = str(apuesta or '').strip()
    if not a.lower().startswith('gana '):
        return None
    elegido = _clave_tenista(a[5:].strip())
    if not elegido:
        return None
    return elegido == ganador_clave


def _clave_tenista(nombre: str) -> str:
    """Apellido normalizado — el único trozo estable entre fuentes."""
    try:
        import cuotas_multi
        return cuotas_multi._clave_tenista(nombre)[0]
    except Exception:
        import name_mapper
        partes = name_mapper.normalizar(nombre).split()
        return partes[-1] if partes else ''


def liquidar_pendientes(dias: int = 10) -> Dict:
    """Resuelve los picks pendientes cuyo partido ya terminó."""
    import os
    if not os.path.exists(DB):
        return {'liquidados': 0, 'aviso': 'Sin rendimiento_real.db.'}
    import pandas as pd
    import name_mapper
    import rendimiento_real
    from config import LEAGUES

    corte = (pd.Timestamp.utcnow().tz_localize(None)
             - pd.Timedelta(hours=HORAS_GRACIA))
    desde = (corte - pd.Timedelta(days=dias)).strftime('%Y-%m-%d')
    hasta = corte.strftime('%Y-%m-%d')

    # v92: recargar primero lo que haya en el repositorio — en el runner de
    # Actions y en Streamlit Cloud la base arranca vacía (está en .gitignore),
    # así que sin esto no habría nada que liquidar y el historial no crecería.
    try:
        rendimiento_real.importar()
    except Exception as e:
        logger.warning(f'[liquidador] no se pudo recargar el histórico: {e}')

    con = sqlite3.connect(DB)
    try:
        pend = pd.read_sql_query(
            "SELECT fecha, deporte, liga, partido, mercado, apuesta "
            "FROM picks WHERE resultado IS NULL AND fecha BETWEEN ? AND ?",
            con, params=[desde, hasta])
    finally:
        con.close()
    if pend.empty:
        return {'liquidados': 0, 'pendientes': 0,
                'aviso': f'Sin picks pendientes entre {desde} y {hasta}.'}

    # v93 — TRES FUENTES, una por deporte. La v92 sólo miraba el scoreboard
    # de fútbol por liga, así que los picks de tenis y MLB se quedaban
    # pendientes para siempre (143 el día que se conectó el circuito).
    claves = [c for c, cfg in LEAGUES.items() if cfg.get('disponible')]
    res = _resultados(claves, desde, hasta)                  # fútbol (ESPN)
    res_mlb = _resultados_mlb(desde, hasta)                  # MLB Stats API
    res_tenis = _resultados_tenis(desde, hasta)              # ATP/WTA (ESPN)
    logger.info(f'[liquidador] resultados disponibles — fútbol {len(res)} · '
                f'MLB {len(res_mlb)} · tenis {len(res_tenis)} · '
                f'{len(pend)} picks pendientes')

    n_ok, n_sin_partido, n_sin_mercado = 0, 0, 0
    for _, p in pend.iterrows():
        dep = str(p.get('deporte') or 'Fútbol')
        # el tenis separa con « vs » igual que el fútbol; la MLB usa « @ »
        # con el visitante DELANTE, así que se voltea al leerlo
        crudo = str(p['partido'])
        if dep == 'MLB' and ' @ ' in crudo:
            visit, local = [x.strip() for x in crudo.split(' @ ', 1)]
            home, away = local, visit
        else:
            partes = crudo.split(' vs ')
            if len(partes) != 2:
                n_sin_partido += 1
                continue
            home, away = partes[0].strip(), partes[1].strip()

        if dep == 'Tenis':
            par = tuple(sorted((_clave_tenista(home), _clave_tenista(away))))
            ganador = _buscar_con_tolerancia(res_tenis, par, str(p['fecha']))
            if not ganador:
                n_sin_partido += 1
                continue
            gano = _gano_tenis(str(p['apuesta']), ganador)
            if gano is None:
                n_sin_mercado += 1
                continue
        elif dep == 'MLB':
            r = _buscar_con_tolerancia(
                res_mlb, (name_mapper.normalizar(home),
                          name_mapper.normalizar(away)), str(p['fecha']))
            if r is None:
                n_sin_partido += 1
                continue
            gano = resolver(p['mercado'], p['apuesta'], home, away,
                            r['goles_home'], r['goles_away'])
            if gano is None:
                n_sin_mercado += 1
                continue
        else:
            r = res.get((str(p['fecha']), name_mapper.normalizar(home),
                         name_mapper.normalizar(away)))
            if r is None:
                n_sin_partido += 1
                continue
            gano = resolver(p['mercado'], p['apuesta'], home, away,
                            r['goles_home'], r['goles_away'])
            if gano is None:
                n_sin_mercado += 1
                continue
        if rendimiento_real.liquidar(str(p['fecha']), str(p['partido']),
                                     str(p['apuesta']), bool(gano)):
            n_ok += 1

    # …y volcarlo de vuelta, que es lo que el workflow commitea.
    try:
        rendimiento_real.exportar()
    except Exception as e:
        logger.warning(f'[liquidador] no se pudo exportar el histórico: {e}')

    salida = {'liquidados': n_ok, 'pendientes': int(len(pend)),
              'sin_resultado': n_sin_partido,
              'mercado_no_resuelto': n_sin_mercado,
              'ventana': f'{desde}..{hasta}'}
    logger.info(f'[liquidador] {n_ok} picks liquidados · '
                f'{n_sin_partido} sin resultado todavía · '
                f'{n_sin_mercado} con mercado no resoluble')
    return salida


if __name__ == '__main__':
    import json
    import sys
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    sys.stdout.reconfigure(encoding='utf-8')
    ap = argparse.ArgumentParser()
    ap.add_argument('--dias', type=int, default=10)
    a = ap.parse_args()
    print(json.dumps(liquidar_pendientes(a.dias), ensure_ascii=False, indent=1))
