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
        # Formato «Equipo +1.5» / «Equipo −1.5» (el signo puede ser − o -).
        #
        # v106 — EL SIGNO ES OPCIONAL. La línea 0 (el «empate no cuenta») se
        # etiqueta «Equipo 0», sin signo, porque «Equipo +0» no significa nada
        # para quien lo lee. Con el signo obligatorio esa apuesta no se
        # parseaba y quedaba pendiente para siempre.
        mm = re.search(r'^(.*?)\s*([+\-−]?)\s*(\d+(?:[.,]\d+)?)\s*$', a)
        if not mm:
            return None
        eq, signo, val = mm.group(1).strip().lower(), mm.group(2), \
            float(mm.group(3).replace(',', '.'))
        linea = -val if signo in ('-', '−') else val
        if eq == str(home).strip().lower():
            margen = gl - gv
        elif eq == str(away).strip().lower():
            margen = gv - gl
        else:
            return None
        # -------------------------------------------------------------------
        # v106 — SE LIQUIDA CON LA MISMA DESCOMPOSICIÓN QUE PUBLICA EL PICK.
        #
        # Antes: las líneas ENTERAS se devolvían como `None` («push posible: no
        # se liquida a ciegas») y las de CUARTO caían al `(margen + linea) > 0`
        # del final, que para ellas es incorrecto — en −0,75 el margen +1 gana
        # media apuesta y empata la otra, no es un «gana» ni un «pierde» sin
        # más. Con la v106 el barrido publica las dos familias de verdad, así
        # que dejarlas sin resolver significaría que sus picks se acumulan
        # eternamente pendientes y el ROI del hándicap nunca se mide.
        #
        # `handicap.desglose` aplicado al margen ya conocido da exactamente la
        # fracción que se cobra y la que se pierde:
        #   · push completo            -> None (no es acierto ni fallo, y
        #                                 contarlo de cualquier lado
        #                                 contaminaría el ROI para siempre)
        #   · cualquier otro caso      -> bool
        # En una línea de cuarto las dos mitades están a 0,5 de distancia, así
        # que jamás una gana y la otra pierde: o se cobra todo lo resuelto o se
        # pierde todo lo resuelto. Por eso el bool es exacto y no un redondeo.
        # (Se pierde el matiz de que en el medio punto sólo se arriesgó la
        # mitad del importe; el ledger de rendimiento es binario y ese matiz
        # no cabe en él. La dirección es la correcta.)
        # -------------------------------------------------------------------
        try:
            import handicap as _hcp
            d = _hcp.desglose({int(margen): 1.0}, linea)
        except Exception:
            d = None
        if not d:
            return None
        resuelve = d['gana'] + d['pierde']
        if resuelve <= 1e-12:
            return None                    # push completo: se devuelve, no se juega
        return (d['gana'] / resuelve) > 0.5

    return None


# ---------------------------------------------------------------------------
# Búsqueda del resultado
# ---------------------------------------------------------------------------
def _resultados(claves: List[str], desde: str, hasta: str) -> Dict[Tuple, list]:
    """
    {(home_norm, away_norm): [(fecha, resultado), …]} de las ligas pedidas.

    v103 — INDEXADO POR PAREJA, NO POR FECHA EXACTA. La v93 le dio tolerancia
    de fecha al tenis y a la MLB porque sus picks se sellan con el día de
    publicación, y dejó el fútbol emparejando por fecha exacta. Resultado
    medido el 2026-08-06: **254 picks sin resultado**, los más antiguos del 23
    de julio, la mayoría de Goles y BTTS — mercados que el liquidador sí sabe
    resolver. No fallaba la resolución: fallaba encontrar el partido.

    Un partido publicado hoy puede jugarse hoy o mañana (y ESPN lo fecha en
    UTC, que ya desplaza a media Europa). Dos equipos concretos no se
    enfrentan dos veces en la misma semana, así que la pareja identifica el
    partido y la fecha sólo tiene que caer dentro de `TOLERANCIA_DIAS`.

    Importa más de lo que parece: un pick sin liquidar no entra en la autopsia
    ni en la calibración adaptativa. Cada uno que se queda colgado es una
    lección que el sistema no aprende.
    """
    import fixtures_espn
    import name_mapper
    out: Dict[Tuple, list] = {}
    for clave in claves:
        try:
            for r in fixtures_espn.resultados_liga(clave, desde, hasta):
                k = (name_mapper.normalizar(r['home']),
                     name_mapper.normalizar(r['away']))
                out.setdefault(k, []).append((r['fecha'], r))
                # v104: además, indexado POR LIGA. El mapeo difuso sobre el
                # catálogo global cruza competiciones y produce falsos
                # positivos: «Atlanta Utd» (MLS) casaba con «Atlanta», el club
                # argentino de Primera Nacional. Medido: 93 de los 103 picks de
                # fútbol colgados caían en ese modo de fallo.
                out.setdefault(('__liga__', clave), []).append((r['fecha'], k))
        except Exception as e:
            logger.debug(f'[liquidador] {clave}: {e}')
    return out


def _clave_de_liga(nombre_liga: str) -> Optional[str]:
    """Clave interna a partir del nombre visible que llevan los picks."""
    if not nombre_liga:
        return None
    from config import LEAGUES
    objetivo = str(nombre_liga).strip().lower()
    for clave, cfg in LEAGUES.items():
        if str(cfg.get('nombre', '')).strip().lower() == objetivo:
            return clave
        if clave.lower() == objetivo:
            return clave
    return None


def _catalogo_de_liga(res: dict, clave: Optional[str]) -> Optional[list]:
    """Nombres normalizados que ESPN publicó en ESA competición."""
    if not clave:
        return None
    pares = res.get(('__liga__', clave))
    if not pares:
        return None
    nombres = set()
    for _f, k in pares:
        nombres.update(k)
    return sorted(nombres)


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
        # v94: se guarda el partido ENTERO (ganador + sets + juegos) para
        # poder liquidar también los mercados derivados
        out.setdefault(par, []).append((p['fecha'], {**p, '_ganador': kg}))

    # v104 — LOS RESULTADOS QUE EL PROPIO PROYECTO YA ACUMULA.
    #
    # El scoreboard de ESPN sólo cubre el circuito principal, y el feed de
    # cuotas publica también challengers e ITF. Resultado medido: **206 picks
    # de tenis sin liquidar**, TODOS con el diagnóstico «la pareja no está» —
    # Bicknell, Quevedo, Poljicak y compañía no salen en ESPN. Eran el 89 % de
    # todo lo que quedaba pendiente en la plataforma.
    #
    # Pero el proyecto ya los tiene: `acumular_tenis.py` alimenta
    # `historico_tenis_espn.csv` e `ingesta_itf.py` alimenta
    # `historico_itf_vivo.csv`. Faltaba mirarlos.
    _sumar_csv_tenis(out, desde, hasta)
    return out


def _sumar_csv_tenis(out: Dict[Tuple, list], desde: str, hasta: str) -> None:
    """Añade al índice los resultados de los CSV que acumula el proyecto."""
    import os
    import pandas as pd
    for ruta, invertido in (('historico_tenis_espn.csv', False),
                            ('historico_itf_vivo.csv', True)):
        if not os.path.exists(ruta):
            continue
        try:
            d = pd.read_csv(ruta)
        except Exception as e:
            logger.warning(f'[liquidador/tenis] {ruta}: {type(e).__name__}: {e}')
            continue
        if not {'fecha', 'jugador_1', 'jugador_2', 'ganador'}.issubset(d.columns):
            continue
        f = pd.to_datetime(d['fecha'], errors='coerce')
        d = d[(f >= pd.Timestamp(desde)) & (f <= pd.Timestamp(hasta) +
                                            pd.Timedelta(days=1))]
        n = 0
        for r in d.itertuples(index=False):
            j1, j2, g = str(r.jugador_1), str(r.jugador_2), str(r.ganador)
            # El fichero del ITF escribe «Apellido Nombre» y el de ESPN
            # «Nombre Apellido». En vez de adivinar el orden se indexa bajo
            # las DOS lecturas posibles; que además el rival caiga en el otro
            # lado del mismo partido es lo que descarta el falso positivo.
            claves1 = _claves_posibles(j1, invertido)
            claves2 = _claves_posibles(j2, invertido)
            kg = _claves_posibles(g, invertido)
            info = {'fecha': str(r.fecha)[:10],
                    'sets': [getattr(r, 'sets_1', None), getattr(r, 'sets_2', None)],
                    'juegos_totales': getattr(r, 'juegos_totales', None)}
            for k1 in claves1:
                for k2 in claves2:
                    if not k1 or not k2 or k1 == k2:
                        continue
                    par = tuple(sorted((k1, k2)))
                    ganador = k1 if k1 in kg else (k2 if k2 in kg else None)
                    if ganador is None:
                        continue
                    out.setdefault(par, []).append(
                        (info['fecha'], {**info, '_ganador': ganador}))
                    n += 1
        if n:
            logger.info(f'[liquidador/tenis] {n} resultados desde {ruta}')


def _claves_posibles(nombre: str, invertido: bool) -> set:
    """Claves de apellido plausibles: la última palabra y la primera."""
    import name_mapper
    partes = name_mapper.normalizar(nombre).split()
    if not partes:
        return set()
    caps = {partes[-1], partes[0]}
    if invertido and len(partes) >= 2:
        caps.add(' '.join(partes[:-1]))     # «bar biryukov» de «Bar Biryukov Petr»
    return {c for c in caps if c}


def _par_mapeado(home: str, away: str, res: dict,
                 catalogo: Optional[list] = None) -> Optional[Tuple]:
    """
    La pareja del pick traducida a los nombres con los que ESPN la publica.

    Se exige que **los dos** lados mapeen y que la pareja resultante exista en
    el índice. Esa doble condición es la que hace seguro el mapeo difuso: un
    «Nacional» suelto podría casar con el club equivocado de otro país, pero
    que ADEMÁS su rival mapee al otro lado del mismo partido ya no es
    casualidad. Si no se cumple, se devuelve None y el pick sigue pendiente —
    liquidar el partido equivocado contamina el ROI en silencio y no deja
    rastro, que es peor que no liquidar.
    """
    import name_mapper
    if not res:
        return None
    # v104: se prefiere el catálogo de LA COMPETICIÓN del pick. El global sólo
    # entra si no se conoce la liga, y entonces con el riesgo asumido de cruzar
    # nombres entre países.
    if catalogo is None:
        catalogo = sorted({n for par in res for n in par
                           if not str(par[0]).startswith('__liga__')})
    try:
        h = name_mapper.mapear(name_mapper.normalizar(home), catalogo,
                               contexto='liquidador')
        a = name_mapper.mapear(name_mapper.normalizar(away), catalogo,
                               contexto='liquidador')
    except Exception:
        return None
    if not h or not a or h == a:
        return None
    par = (h, a)
    return par if par in res else None


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


def _gano_tenis(apuesta: str, res) -> Optional[bool]:
    """
    ¿Ganó este pick de tenis? None si no se sabe resolver.

    v94 — se amplía a los mercados DERIVADOS. Se propuso buscar una fuente
    complementaria (TennisAbstract) para el marcador detallado; no hizo falta:
    ESPN ya lo publica en `linescores` de cada competidor y sólo faltaba
    leerlo. Medido: **188 de 189 partidos (99 %)** traen el marcador set a set.

    `res` puede ser la clave del ganador (compatibilidad) o el dict completo
    del partido, que además trae `sets` y `juegos_totales`.

    Sigue devolviendo None —en vez de adivinar— para lo que no se sabe leer:
    una apuesta mal liquidada contamina el ROI y no deja rastro.
    """
    a = str(apuesta or '').strip()
    al = a.lower()
    if isinstance(res, dict):
        ganador_clave = res.get('_ganador')
        sets = res.get('sets')
        juegos = res.get('juegos_totales')
    else:
        ganador_clave, sets, juegos = res, None, None

    if al.startswith('gana '):
        elegido = _clave_tenista(a[5:].strip())
        return (elegido == ganador_clave) if elegido else None

    # total de JUEGOS del partido («Más de 22.5 juegos»)
    if 'juego' in al and juegos is not None:
        linea = _num(a)
        if linea is None:
            return None
        if al.startswith('más') or al.startswith('mas') or al.startswith('over'):
            return juegos > linea
        if al.startswith('menos') or al.startswith('under'):
            return juegos < linea
        return None

    # resultado por SETS («2-0», «2-1»); `sets` viene en el orden en que ESPN
    # listó a los jugadores, así que se compara el marcador ordenado
    if 'set' in al and sets:
        m = re.search(r'(\d)\s*[-–]\s*(\d)', a)
        if m:
            pedido = sorted((int(m.group(1)), int(m.group(2))), reverse=True)
            real = sorted(sets, reverse=True)
            return pedido == real
        return None

    return None


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
            info = _buscar_con_tolerancia(res_tenis, par, str(p['fecha']))
            if not info:
                n_sin_partido += 1
                continue
            gano = _gano_tenis(str(p['apuesta']), info)
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
            # v103: con tolerancia de fecha, igual que tenis y MLB desde la v93
            r = _buscar_con_tolerancia(
                res, (name_mapper.normalizar(home),
                      name_mapper.normalizar(away)), str(p['fecha']))
            if r is None:
                # …y si no, reconciliando los NOMBRES. Los picks llevan el
                # nombre de la casa de apuestas («Atlanta Utd», «Racing Club»)
                # y ESPN publica el suyo («Atlanta United FC»); `normalizar`
                # sólo baja a minúsculas, así que la pareja no casaba nunca.
                # Medido: 254 picks colgados, los más viejos del 23 de julio.
                _cat = _catalogo_de_liga(res, _clave_de_liga(p.get('liga')))
                r = _buscar_con_tolerancia(
                    res, _par_mapeado(home, away, res, _cat), str(p['fecha']))
                if r is None and _cat:
                    # y sólo si con su liga no aparece, se prueba el global
                    r = _buscar_con_tolerancia(
                        res, _par_mapeado(home, away, res), str(p['fecha']))
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
    # v115 — los PONCHES se resuelven con otra fuente (el registro por juego
    # del lanzador en MLB StatsAPI), así que van en su propio módulo. Se
    # llaman aquí para que la tarea diaria siga teniendo UN solo punto de
    # entrada y no haya que acordarse de dos.
    try:
        import liquidador_ponches
        print(json.dumps(liquidador_ponches.liquidar_ponches(max(a.dias, 21)),
                         ensure_ascii=False, indent=1))
        print(json.dumps(liquidador_ponches.resumen_combinadas(),
                         ensure_ascii=False, indent=1))
    except Exception as e:
        print(f'{{"ponches": "no disponible: {type(e).__name__}: {e}"}}')
