#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v114 — El panel de «cara a cara, clasificación y forma», para MLB, KBO y tenis.

Lo que faltaba
--------------
El fútbol tiene `panel_equipos` desde la v107: historial del cruce, tabla del
torneo y forma reciente, todo del histórico local, sin red y sin claves. El
usuario lo pidió para el resto: «en MLB y tenis también falta la sección de H2H
que tenga lo mismo que muestra el fútbol pero acomodado a su respectivo
deporte».

Cómo se ha hecho
----------------
BÉISBOL (MLB y KBO) — no hacía falta código nuevo de análisis. Sus históricos
tienen la misma forma que los de fútbol y sólo llamaban `home_runs`/`away_runs`
a las columnas del marcador; con que `panel_equipos._historico` las reconozca
(v114), el cara a cara, la forma y el reparto casa/fuera salen tal cual. Lo
único propio del deporte es la CLASIFICACIÓN: en béisbol no se cuentan puntos
sino porcentaje de victorias, y no hay empates. Eso se escribe aquí.

TENIS — aquí sí cambia todo, porque no hay «local», ni tabla, ni temporada
regular. El equivalente honesto de cada bloque es:

    cara a cara      → balance histórico entre los dos jugadores
    clasificación    → ranking y ELO, con el ELO POR SUPERFICIE, que es lo que
                       de verdad ordena a dos tenistas en un partido concreto
    forma            → últimos resultados, partidos en 14 días y horas en
                       pista en 7 (la fatiga, que el motor ya calcula)

El balance sale de `estado['h2h']` del propio motor (259.443 pares), y el
detalle partido a partido de `historico_tenis_espn.csv` cuando lo tiene.

Igual que en fútbol, esto es INFORMACIÓN PARA JUZGAR, no una señal de apuesta:
el ELO ya absorbe el historial y la forma, así que ver aquí que alguien domina
no significa que haya valor — lo normal es que la cuota ya lo refleje.
"""
import logging
import os
from typing import Dict, List, Optional

import pandas as pd

logger = logging.getLogger(__name__)

CSV_TENIS = 'historico_tenis_espn.csv'
_CACHE_TENIS: Dict[str, pd.DataFrame] = {}


# ===========================================================================
# BÉISBOL (MLB y KBO)
# ===========================================================================
def clasificacion_beisbol(clave: str, minimo_partidos: int = 10) -> List[Dict]:
    """
    Tabla del año en curso por PORCENTAJE DE VICTORIAS, que es como se ordena
    el béisbol. No se reutiliza `panel_equipos.clasificacion` porque aquella
    reparte 3 puntos por victoria y 1 por empate: en béisbol no hay empates y
    los equipos no juegan el mismo número de partidos, así que los puntos
    absolutos ordenarían mal.
    """
    import panel_equipos as pe
    d = pe._historico(clave)
    if d.empty:
        return []
    temporada = d[d['date'].dt.year == d['date'].dt.year.max()]
    if temporada.empty:
        return []
    tabla: Dict[str, Dict] = {}

    def _fila(eq):
        return tabla.setdefault(eq, {'equipo': eq, 'g': 0, 'p': 0,
                                     'cf': 0, 'cc': 0})
    for r in temporada.itertuples():
        hl, al = _fila(r.home_team), _fila(r.away_team)
        hl['cf'] += r.home_goals; hl['cc'] += r.away_goals
        al['cf'] += r.away_goals; al['cc'] += r.home_goals
        if r.home_goals > r.away_goals:
            hl['g'] += 1; al['p'] += 1
        elif r.away_goals > r.home_goals:
            al['g'] += 1; hl['p'] += 1
    filas = []
    for eq, f in tabla.items():
        pj = f['g'] + f['p']
        if pj < minimo_partidos:
            continue
        filas.append({**f, 'pj': pj, 'pct': round(f['g'] / pj, 3),
                      'dif': f['cf'] - f['cc'],
                      'cf_media': round(f['cf'] / pj, 2),
                      'cc_media': round(f['cc'] / pj, 2)})
    filas.sort(key=lambda x: (-x['pct'], -x['dif']))
    for i, f in enumerate(filas, 1):
        f['pos'] = i
    return filas


def posicion_beisbol(clasif: List[Dict], equipo: str) -> Optional[Dict]:
    return next((f for f in clasif if f['equipo'] == equipo), None)


def resumen_beisbol(clave: str, home: str, away: str) -> Dict:
    """Todo el panel de un partido de béisbol, en una sola llamada."""
    import panel_equipos as pe
    clasif = clasificacion_beisbol(clave)
    return {
        'h2h': pe.h2h(clave, home, away),
        'clasificacion': clasif,
        'posicion_local': posicion_beisbol(clasif, home),
        'posicion_visitante': posicion_beisbol(clasif, away),
        'forma_local': pe.forma(clave, home),
        'forma_visitante': pe.forma(clave, away),
        'casa_fuera_local': pe.rendimiento_casa_fuera(clave, home),
        'casa_fuera_visitante': pe.rendimiento_casa_fuera(clave, away),
    }


def lectura_beisbol(clave: str, home: str, away: str,
                    nombres: Optional[Dict] = None) -> List[str]:
    """Las tres o cuatro frases que resumen el cruce, en español llano."""
    nombres = nombres or {}
    def _n(x):
        return nombres.get(x, x)
    r = resumen_beisbol(clave, home, away)
    frases: List[str] = []
    h = r['h2h']
    if h.get('n'):
        dom = (_n(home) if h['gana_a'] > h['gana_b']
               else _n(away) if h['gana_b'] > h['gana_a'] else None)
        if dom:
            frases.append(
                f"📜 {dom} domina la serie: {h['gana_a']}-{h['gana_b']} en "
                f"{h['n']} partidos desde {h['desde']}.")
        else:
            frases.append(f"📜 Serie igualada: {h['gana_a']}-{h['gana_b']} en "
                          f"{h['n']} partidos desde {h['desde']}.")
        frases.append(f"⚾ Se anotan {h['media_goles']} carreras por partido "
                      f"entre los dos.")
    pl, pv = r['posicion_local'], r['posicion_visitante']
    if pl and pv:
        frases.append(
            f"🏆 En la temporada: {_n(home)} {pl['pos']}º ({pl['g']}-{pl['p']}, "
            f"{pl['pct']*100:.1f} %) · {_n(away)} {pv['pos']}º "
            f"({pv['g']}-{pv['p']}, {pv['pct']*100:.1f} %).")
    fl, fv = r['forma_local'], r['forma_visitante']
    if fl.get('n') and fv.get('n'):
        frases.append(
            f"📈 Forma (últimos {fl['n']}): {_n(home)} `{fl['racha']}` "
            f"({fl['gf_media']} carreras a favor, {fl['gc_media']} en contra) · "
            f"{_n(away)} `{fv['racha']}` ({fv['gf_media']} / {fv['gc_media']}).")
    return frases


# ===========================================================================
# TENIS
# ===========================================================================
def _historico_tenis() -> pd.DataFrame:
    """Los partidos con detalle (torneo, sets, juegos). Vacío si no hay."""
    if 'd' in _CACHE_TENIS:
        return _CACHE_TENIS['d']
    if not os.path.exists(CSV_TENIS):
        _CACHE_TENIS['d'] = pd.DataFrame()
        return _CACHE_TENIS['d']
    try:
        d = pd.read_csv(CSV_TENIS)
        d['fecha'] = pd.to_datetime(d['fecha'], errors='coerce', format='mixed')
        d = d.dropna(subset=['fecha', 'jugador_1', 'jugador_2'])
        d = d.sort_values('fecha').reset_index(drop=True)
    except Exception as e:
        logger.warning(f'[panel/tenis] {CSV_TENIS}: {type(e).__name__}: {e}')
        d = pd.DataFrame()
    _CACHE_TENIS['d'] = d
    return d


def h2h_tenis(engine, p1: str, p2: str, maximo: int = 10) -> Dict:
    """
    Cara a cara entre dos tenistas.

    El BALANCE sale del estado del motor, que lo lleva calculado sobre todo su
    histórico (259.443 pares) y por eso cubre a cualquier pareja del circuito.
    El DETALLE partido a partido sale del CSV de ESPN, que es mucho más corto:
    puede haber balance sin ningún partido detallado, y es correcto — se dice
    cuántos hay de cada cosa en vez de fingir que no existe el historial.
    """
    salida = {'balance': None, 'gana_1': 0, 'gana_2': 0, 'n': 0,
              'partidos': [], 'motivo': ''}
    try:
        h2h = (getattr(engine, 'estado', {}) or {}).get('h2h') or {}
        # el estado guarda el par ordenado con el signo referido al PRIMERO
        b = h2h.get(f'{p1}|{p2}')
        if b is None:
            b = h2h.get(f'{p2}|{p1}')
            b = -b if b is not None else None
        salida['balance'] = b
    except Exception as e:
        logger.debug(f'[panel/tenis] balance: {e}')

    d = _historico_tenis()
    if not d.empty:
        m = d[((d['jugador_1'] == p1) & (d['jugador_2'] == p2))
              | ((d['jugador_1'] == p2) & (d['jugador_2'] == p1))]
        for r in m.sort_values('fecha', ascending=False).head(maximo).itertuples():
            gan = str(getattr(r, 'ganador', '') or '')
            if gan == p1:
                salida['gana_1'] += 1
            elif gan == p2:
                salida['gana_2'] += 1
            salida['partidos'].append({
                'fecha': r.fecha.strftime('%Y-%m-%d'),
                'torneo': getattr(r, 'torneo', ''),
                'ganador': gan,
                'sets': f"{getattr(r, 'sets_1', '')}-{getattr(r, 'sets_2', '')}",
                'juegos': getattr(r, 'juegos_totales', None),
            })
        salida['n'] = len(salida['partidos'])
    if salida['balance'] is None and not salida['n']:
        salida['motivo'] = 'Sin cruces previos registrados entre los dos.'
    return salida


def perfil_tenista(engine, jugador: str) -> Dict:
    """Ranking, ELO general y por superficie, forma y carga reciente."""
    jug = ((getattr(engine, 'estado', {}) or {}).get('jugadores') or {})
    d = jug.get(jugador) or {}
    forma = d.get('forma') or []
    return {
        'jugador': jugador,
        'rank': d.get('rank'),
        'puntos': d.get('pts'),
        'elo': d.get('elo'),
        'elo_superficie': d.get('elo_sup') or {},
        'ultimo_partido': d.get('ultimo_partido'),
        'partidos_14d': d.get('partidos_14d'),
        'horas_7d': d.get('horas_7d'),
        'ganados_recientes': int(sum(1 for x in forma if x)),
        'jugados_recientes': len(forma),
        'racha': ''.join('G' if x else 'P' for x in reversed(forma[-8:])),
    }


def forma_tenis(jugador: str, n: int = 8) -> List[Dict]:
    """Últimos partidos con detalle, del histórico de ESPN."""
    d = _historico_tenis()
    if d.empty:
        return []
    m = d[(d['jugador_1'] == jugador) | (d['jugador_2'] == jugador)]
    out = []
    for r in m.sort_values('fecha', ascending=False).head(n).itertuples():
        rival = (r.jugador_2 if r.jugador_1 == jugador else r.jugador_1)
        gan = str(getattr(r, 'ganador', '') or '')
        out.append({'fecha': r.fecha.strftime('%Y-%m-%d'),
                    'torneo': getattr(r, 'torneo', ''),
                    'rival': rival,
                    'resultado': 'Ganó' if gan == jugador else 'Perdió',
                    'sets': f"{getattr(r, 'sets_1', '')}-{getattr(r, 'sets_2', '')}"})
    return out


def lectura_tenis(engine, p1: str, p2: str,
                  superficie: Optional[str] = None) -> List[str]:
    """Las frases que resumen el cruce de tenis."""
    frases: List[str] = []
    h = h2h_tenis(engine, p1, p2)
    b = h.get('balance')
    if b:
        quien, otro = (p1, p2) if b > 0 else (p2, p1)
        frases.append(f"📜 {quien} va por delante en el cara a cara "
                      f"(balance {abs(int(b))} a favor sobre {otro}).")
    elif b == 0:
        frases.append("📜 Cara a cara igualado en el historial.")
    elif h.get('motivo'):
        frases.append(f"📜 {h['motivo']}")

    a, c = perfil_tenista(engine, p1), perfil_tenista(engine, p2)
    if a.get('rank') and c.get('rank'):
        frases.append(f"🏆 Ranking: {p1} nº {a['rank']:.0f} · "
                      f"{p2} nº {c['rank']:.0f}.")
    sup = (superficie or '').lower()
    ea = (a.get('elo_superficie') or {}).get(sup)
    ec = (c.get('elo_superficie') or {}).get(sup)
    if ea and ec:
        mejor = p1 if ea > ec else p2
        frases.append(f"🎾 En {sup}, el ELO de superficie favorece a "
                      f"**{mejor}**: {p1} {ea:.0f} · {p2} {ec:.0f}. Es el dato "
                      f"que más pesa: un especialista en tierra y uno en pista "
                      f"rápida no se ordenan igual según dónde jueguen.")
    elif a.get('elo') and c.get('elo'):
        frases.append(f"🎾 ELO general: {p1} {a['elo']:.0f} · {p2} "
                      f"{c['elo']:.0f} (ninguno tiene ELO medido en esta "
                      f"superficie todavía).")
    for p in (a, c):
        if (p.get('partidos_14d') or 0) >= 5 or (p.get('horas_7d') or 0) >= 8:
            frases.append(
                f"🥵 Carga de {p['jugador']}: {p['partidos_14d']} partidos en "
                f"14 días y {p['horas_7d']:.1f} h en pista en 7. La fatiga ya "
                f"está dentro del modelo, pero conviene verla.")
    return frases
