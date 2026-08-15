#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v131 · NFL — traductor de mercados y plantilla del modelo.

El problema que resuelve
-----------------------
`cuotas_tablon.filas_playdoit` traduce el tablero de la casa al vocabulario del
modelo, y ese vocabulario es de FÚTBOL: habla de goles, de empate y de «ambos
equipos marcan». Aplicado a un partido de NFL no daría un error — daría cero
filas, o peor: el «Totales» de 35.5 PUNTOS casaría por parecido con el «Más de
2.5 goles» de la plantilla y saldría un EV inventado. Es el mismo modo de fallo
que la v122 documentó con «Monterrey 3-4 Juarez» → EV +19.603 %.

Así que la NFL tiene su propio traductor, con dos mitades que hablan igual:

    filas_playdoit_nfl(det)   → lo que PAGA la casa
    plantilla_nfl(pred)       → lo que CREE el modelo

Las dos escriben la misma etiqueta para el mismo suceso, y el cruce lo hace
`cuotas_tablon.mercados_de_filas`, que ya está probado y trae el line shopping,
el veto por seña y la criba de EV sospechoso.

Los diez mercados del encargo, y cuál se cruza
----------------------------------------------
Medido sobre los cuatro partidos de pretemporada del 2026-08-15 (los cuatro con
tablero completo), Playdoit publica 12 mercados por partido de NFL:

| # | mercado de la casa | typeId | ¿el modelo lo cubre? |
|---|---|---|---|
| 1 | Ganador (incl. prórroga) | 219 | **sí** — 1X2 a dos vías |
| 2 | Hándicap (incl. prórroga) | 223 | **sí** — con empuje en línea entera |
| 3 | Totales (incl. prórroga) | 225 | **sí** |
| 4 | Total de equipo (incl. prórroga) | 227/228 | **sí** — varianza propia |
| 5 | 1ª Mitad · Apuesta sin empate | 64 | precio sí, EV **no fiable** |
| 6 | 1ª Mitad · Hándicap | 66 | precio sí, EV **no fiable** |
| 7 | 1ª Mitad · Total | 68 | precio sí, EV **no fiable** |
| 8 | Primer cuarto · Apuesta sin empate | 302 | precio sí, EV **no fiable** |
| 9 | Primer equipo en marcar | 11074 | precio sí, **sin modelo** |
| 10 | Margen de victoria (incl. prórroga) | 290 | **sí** — por tramos |
| — | Mitad/final | 47 | precio sí, **sin modelo** |

Por qué los tiempos llevan el EV marcado como no fiable
--------------------------------------------------------
El modelo predice el partido completo. Repartir su margen y su total entre
mitades y cuartos exigiría una proporción medida, y **no la hay**: la NFL no
reparte 50/50 (el segundo cuarto y el cuarto llevan más puntos por el reloj de
dos minutos). Inventar la proporción es exactamente el fallo que la v123
encontró en el fútbol, donde el modelo daba la MISMA probabilidad a las dos
mitades y de esa simetría falsa salía un EV que no medía valor.

Así que el precio de los tiempos **sí** se publica —sirve para armar un boleto
en una sola casa, que es para lo que el usuario los pidió— y su EV va marcado
`ev_no_fiable`, igual que en el fútbol. Cuando haya medición del reparto por
cuarto, se quita la marca; hasta entonces no se finge tenerla.
"""
from __future__ import annotations

import logging
import re
import unicodedata
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


def _norm(t) -> str:
    """Misma normalización que `cuotas_tablon._norm` (NFKD por el «1ª»)."""
    t = unicodedata.normalize('NFKD', str(t or ''))
    t = ''.join(c for c in t if unicodedata.category(c) != 'Mn')
    return ' '.join(t.lower().split())


def _f(x) -> Optional[float]:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v > 1.0 else None


def _num(t) -> Optional[float]:
    try:
        return float(str(t).replace(',', '.').replace('+', ''))
    except (TypeError, ValueError):
        return None


_LINEA = re.compile(r'^(m[áa]s|menos)\s+de\s+([0-9]+(?:[.,][0-9]+)?)$', re.I)
_LINEA_HCP = re.compile(r'^(.+?)\s*\(([+-]?[0-9]+(?:[.,][0-9]+)?)\)\s*$')
# «KC Chiefs by 13-18», «KC Chiefs 43+», y sus variantes en español
_MARGEN = re.compile(r'^(.+?)\s+(?:by\s+|por\s+)?([0-9]+\s*-\s*[0-9]+|[0-9]+\s*\+)$',
                     re.I)

FAMILIA_1X2 = '1X2'
FAMILIA_HCP = 'Hándicap NFL'
FAMILIA_TOTAL = 'Total de puntos'
FAMILIA_TOTAL_EQ = 'Puntos por equipo'
FAMILIA_MARGEN = 'Margen de victoria'
FAMILIA_TIEMPOS = 'Mitades'
FAMILIA_OTROS = 'Otros NFL'

# Familias cuyo EV no se puede creer porque el modelo no cubre el suceso.
SIN_MODELO_FIABLE = (FAMILIA_TIEMPOS, FAMILIA_OTROS)


def filas_playdoit_nfl(det: Dict, home: str, away: str) -> List[Dict]:
    """
    El tablero de Playdoit de un partido de NFL, en el vocabulario del modelo.

    `home`/`away` son los nombres LARGOS que ve el usuario; `det['casa_home']`
    y `casa_away` son como los escribe la casa («KC Chiefs»), ya enderezados
    por el emparejador. Se identifica por NOMBRE de mercado, no por `typeId`,
    por la misma razón que en el fútbol: el typeId cambia entre deportes y ya
    costó una versión entera (v77).
    """
    filas: List[Dict] = []
    if not isinstance(det, dict):
        return filas
    ch = det.get('casa_home') or home
    ca = det.get('casa_away') or away
    n_ch, n_ca = _norm(ch), _norm(ca)

    def _add(etiqueta, cuota, familia, sena=None):
        c = _f(cuota)
        if c is not None:
            filas.append({'etiqueta': etiqueta, 'cuota': round(c, 4),
                          'casa': det.get('casa', 'Playdoit'),
                          'familia': familia, 'sena': sena,
                          'ev_no_fiable': familia in SIN_MODELO_FIABLE})

    def _lado(texto) -> Optional[str]:
        n = _norm(texto)
        if n == n_ch:
            return 'home'
        if n == n_ca:
            return 'away'
        return None

    for m in (det.get('mercados') or []):
        nombre = _norm(m.get('nombre'))
        sels = m.get('selecciones') or []
        if not sels:
            continue
        # el sufijo «(incl. prorroga)» no distingue nada: TODOS los mercados
        # principales de la NFL lo llevan, porque en la NFL la prórroga es
        # parte del partido. Se quita para comparar.
        base = nombre.replace('(incl. prorroga)', '').strip()

        # ---- 1ª mitad y primer cuarto: precio sí, EV no ---------------------
        if base.startswith('1a mitad') or base.startswith('primer cuarto') \
                or base.startswith('2a mitad') or 'cuarto' in base:
            periodo = ('1ª mitad' if base.startswith('1a mitad')
                       else '2ª mitad' if base.startswith('2a mitad')
                       else 'primer cuarto')
            _mercado_periodo(_add, periodo, base, sels, home, away, _lado)
            continue

        # ---- ganador (dos vías, sin empate en el tablero de la casa) --------
        if base in ('ganador', 'apuesta sin empate', 'ganador del partido'):
            for s in sels:
                l = _lado(s.get('nombre'))
                if l == 'home':
                    _add(f'Gana {home}', s['cuota'], FAMILIA_1X2, f'gana {home}')
                elif l == 'away':
                    _add(f'Gana {away}', s['cuota'], FAMILIA_1X2, f'gana {away}')
                elif _norm(s.get('nombre')) == 'empate':
                    _add('Empate', s['cuota'], FAMILIA_1X2, 'empate')
            continue

        # ---- hándicap del partido -------------------------------------------
        if base == 'handicap':
            for s in sels:
                mt = _LINEA_HCP.match(str(s.get('nombre') or '').strip())
                if not mt:
                    continue
                l = _lado(mt.group(1))
                L = _num(mt.group(2))
                if l is None or L is None:
                    continue
                equipo = home if l == 'home' else away
                _add(f'{equipo} {L:+g}', s['cuota'], FAMILIA_HCP,
                     f'{equipo} {L:+g}')
            continue

        # ---- total del partido ----------------------------------------------
        if base in ('totales', 'total'):
            for s in sels:
                mt = _LINEA.match(str(s.get('nombre') or '').strip())
                if not mt:
                    continue
                L = _num(mt.group(2))
                if L is None:
                    continue
                lado = 'Más' if _norm(mt.group(1)).startswith('mas') else 'Menos'
                _add(f'{lado} de {L:g} puntos', s['cuota'], FAMILIA_TOTAL,
                     f'{lado} de {L:g} puntos')
            continue

        # ---- total de UN equipo ----------------------------------------------
        # La casa lo escribe de dos formas en el mismo tablero: «KC Chiefs total»
        # y «LA Rams Totales». Se aceptan las dos.
        if base.endswith(' total') or base.endswith(' totales'):
            quien = base.rsplit(' ', 1)[0].strip()
            l = _lado(quien)
            if l is None:
                continue
            equipo = home if l == 'home' else away
            for s in sels:
                mt = _LINEA.match(str(s.get('nombre') or '').strip())
                if not mt:
                    continue
                L = _num(mt.group(2))
                if L is None:
                    continue
                lado = 'Más' if _norm(mt.group(1)).startswith('mas') else 'Menos'
                _add(f'{equipo}: {lado.lower()} de {L:g} puntos', s['cuota'],
                     FAMILIA_TOTAL_EQ, f'{equipo}: {lado.lower()} de {L:g}')
            continue

        # ---- margen de victoria por tramos -----------------------------------
        if base.startswith('margen de victoria'):
            for s in sels:
                txt = ' '.join(str(s.get('nombre') or '').split())
                mt = _MARGEN.match(txt)
                if not mt:
                    continue
                l = _lado(mt.group(1))
                if l is None:
                    continue
                equipo = home if l == 'home' else away
                tramo = mt.group(2).replace(' ', '')
                _add(f'{equipo} por {tramo}', s['cuota'], FAMILIA_MARGEN,
                     f'{equipo} por {tramo}')
            continue

        # ---- lo que la casa paga y el modelo NO cubre --------------------------
        # Se publica el precio con el EV marcado. La alternativa —tirarlo— deja
        # al usuario sin la mitad del tablero de su propia casa.
        if base in ('primer equipo en marcar', 'ultimo equipo en marcar'):
            etq = ('Primer equipo en marcar' if base.startswith('primer')
                   else 'Último equipo en marcar')
            for s in sels:
                l = _lado(s.get('nombre'))
                if l is not None:
                    equipo = home if l == 'home' else away
                    _add(f'{etq}: {equipo}', s['cuota'], FAMILIA_OTROS,
                         f'{etq}: {equipo}')
            continue
        if base == 'mitad/final':
            for s in sels:
                txt = ' '.join(str(s.get('nombre') or '').split())
                _add(f'Mitad/final: {txt}', s['cuota'], FAMILIA_OTROS,
                     f'mitad/final {_norm(txt)}')
            continue

    return filas


def _mercado_periodo(_add, periodo: str, base: str, sels, home, away, _lado):
    """Mercados de mitad o cuarto: el precio se conserva, el EV se marca."""
    if 'handicap' in base:
        for s in sels:
            mt = _LINEA_HCP.match(str(s.get('nombre') or '').strip())
            if not mt:
                continue
            l = _lado(mt.group(1))
            L = _num(mt.group(2))
            if l is None or L is None:
                continue
            equipo = home if l == 'home' else away
            _add(f'{periodo}: {equipo} {L:+g}', s['cuota'], FAMILIA_TIEMPOS,
                 f'{periodo}: {equipo} {L:+g}')
        return
    if 'total' in base:
        for s in sels:
            mt = _LINEA.match(str(s.get('nombre') or '').strip())
            if not mt:
                continue
            L = _num(mt.group(2))
            if L is None:
                continue
            lado = 'Más' if _norm(mt.group(1)).startswith('mas') else 'Menos'
            _add(f'{periodo}: {lado.lower()} de {L:g} puntos', s['cuota'],
                 FAMILIA_TIEMPOS, f'{periodo}: {lado.lower()} de {L:g}')
        return
    # ganador del periodo
    for s in sels:
        l = _lado(s.get('nombre'))
        if l == 'home':
            _add(f'{periodo}: gana {home}', s['cuota'], FAMILIA_TIEMPOS,
                 f'{periodo}: gana {home}')
        elif l == 'away':
            _add(f'{periodo}: gana {away}', s['cuota'], FAMILIA_TIEMPOS,
                 f'{periodo}: gana {away}')
        elif _norm(s.get('nombre')) == 'empate':
            _add(f'{periodo}: empate', s['cuota'], FAMILIA_TIEMPOS,
                 f'{periodo}: empate')


# ---------------------------------------------------------------------------
# La otra mitad: la plantilla del modelo, con las MISMAS etiquetas
# ---------------------------------------------------------------------------
# Los títulos de sección tienen que contener los fragmentos que
# `cuotas_tablon.FAMILIA_SECCION` busca para acotar el cruce por familia. Si no
# encajan, la plantilla se cruza entera y vuelve el fallo del parecido de
# texto — que aquí sería un «Más de 44.5 puntos» cobrando la probabilidad de
# «Más de 4.5 puntos» de otra sección.
SECCIONES_NFL = {
    FAMILIA_1X2: '1. Ganador (1X2)',
    FAMILIA_HCP: '2. Hándicap asiático (NFL)',
    FAMILIA_TOTAL: '3. Total de puntos (Over/Under)',
    FAMILIA_TOTAL_EQ: '4. Puntos por equipo',
    FAMILIA_MARGEN: '5. Margen de victoria',
}


def plantilla_nfl(pred: Dict, home: str, away: str,
                  lineas: Optional[Dict] = None) -> Dict:
    """
    La predicción del modelo con la forma que espera `cruzar_con_plantilla`:
    `{'secciones': [{'titulo', 'campos': [{'id','etiqueta','valor','tipo'}]}]}`.

    `valor` va en PORCENTAJE porque es lo que el cruzador espera (divide entre
    100). `lineas` permite pedir las líneas concretas que publica la casa, que
    es lo que evita calcular cien líneas que nadie cotiza.
    """
    lineas = lineas or {}
    secs = []

    def _campos(*pares):
        return [{'id': i, 'etiqueta': e, 'valor': round(float(p) * 100, 2),
                 'tipo': 'pct'} for i, e, p in pares if p is not None]

    # --- 1X2 ---------------------------------------------------------------
    ph = pred.get('prob_home_sin_empate', pred.get('prob_home'))
    pa = pred.get('prob_away_sin_empate', pred.get('prob_away'))
    c = _campos(('nfl_home', f'Gana {home}', ph),
                ('nfl_away', f'Gana {away}', pa))
    if pred.get('prob_empate'):
        c += _campos(('nfl_empate', 'Empate', pred['prob_empate']))
    if c:
        secs.append({'titulo': SECCIONES_NFL[FAMILIA_1X2], 'campos': c})

    # --- hándicap -----------------------------------------------------------
    # Sólo se emiten las líneas que la casa publica. Emitir un abanico entero
    # daría campos que nadie cotiza y multiplicaría las ocasiones de que el
    # comparador de texto case «−3.5» con «−3».
    campos = []
    for L in sorted(set(lineas.get('handicap') or [])):
        p = _prob_hcp(pred, L)
        if p is None:
            continue
        campos += _campos((f'nfl_ah_h_{L:g}', f'{home} {L:+g}', p['home']),
                          (f'nfl_ah_a_{-L:g}', f'{away} {-L:+g}', p['away']))
    if campos:
        secs.append({'titulo': SECCIONES_NFL[FAMILIA_HCP], 'campos': campos})

    # --- total del partido ---------------------------------------------------
    campos = []
    for L in sorted(set(lineas.get('total') or [])):
        p = _prob_total(pred, L)
        if p is None:
            continue
        campos += _campos((f'nfl_ov_{L:g}', f'Más de {L:g} puntos', p['over']),
                          (f'nfl_un_{L:g}', f'Menos de {L:g} puntos', p['under']))
    if campos:
        secs.append({'titulo': SECCIONES_NFL[FAMILIA_TOTAL], 'campos': campos})

    # --- total por equipo -----------------------------------------------------
    campos = []
    for lado, equipo in (('home', home), ('away', away)):
        media = pred.get(f'pts_{lado}_esperado')
        sigma = pred.get('sigma_equipo')
        for L in sorted(set((lineas.get(f'total_{lado}') or []))):
            p = _prob_normal(media, sigma, L)
            if p is None:
                continue
            campos += _campos(
                (f'nfl_teq_{lado}_ov_{L:g}',
                 f'{equipo}: más de {L:g} puntos', p),
                (f'nfl_teq_{lado}_un_{L:g}',
                 f'{equipo}: menos de {L:g} puntos', 1 - p))
    if campos:
        secs.append({'titulo': SECCIONES_NFL[FAMILIA_TOTAL_EQ], 'campos': campos})

    # --- margen de victoria por tramos ----------------------------------------
    campos = []
    for lado, equipo in (('home', home), ('away', away)):
        for tramo in (lineas.get(f'margen_{lado}') or []):
            p = _prob_margen_tramo(pred, lado, tramo)
            if p is None:
                continue
            campos += _campos((f'nfl_mv_{lado}_{tramo}',
                               f'{equipo} por {tramo}', p))
    if campos:
        secs.append({'titulo': SECCIONES_NFL[FAMILIA_MARGEN], 'campos': campos})

    return {'secciones': secs}


def _prob_normal(media, sigma, L) -> Optional[float]:
    import math
    if media is None or sigma is None:
        return None
    try:
        z = (float(L) - float(media)) / max(float(sigma), 1e-6)
    except (TypeError, ValueError):
        return None
    return 1.0 - 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def _prob_hcp(pred: Dict, L: float) -> Optional[Dict[str, float]]:
    """P(el local cubre L) y su complementaria, repartiendo el empuje."""
    p = _prob_normal(pred.get('margen_esperado'), pred.get('sigma_margen'), -float(L))
    if p is None:
        return None
    return {'home': p, 'away': 1.0 - p}


def _prob_total(pred: Dict, L: float) -> Optional[Dict[str, float]]:
    p = _prob_normal(pred.get('total_esperado'), pred.get('sigma_total'), float(L))
    if p is None:
        return None
    return {'over': p, 'under': 1.0 - p}


def _prob_margen_tramo(pred: Dict, lado: str, tramo: str) -> Optional[float]:
    """
    «7-12» o «43+» → probabilidad de que ese equipo gane por ese margen.

    Se calcula como diferencia de dos colas sobre el margen, con el signo del
    lado. Es la única forma consistente con el resto: el margen ya tiene su
    media y su sigma medidas, y trocearlo no introduce ningún supuesto nuevo.
    """
    media, sigma = pred.get('margen_esperado'), pred.get('sigma_margen')
    if media is None or sigma is None:
        return None
    t = str(tramo).strip()
    if t.endswith('+'):
        lo, hi = _num(t[:-1]), None
    elif '-' in t:
        a, _, b = t.partition('-')
        lo, hi = _num(a), _num(b)
    else:
        return None
    if lo is None:
        return None
    # para el visitante el margen es negativo: se voltea el eje
    signo = 1.0 if lado == 'home' else -1.0
    m = float(media) * signo
    p_lo = _prob_normal(m, sigma, float(lo) - 0.5)
    p_hi = _prob_normal(m, sigma, float(hi) + 0.5) if hi is not None else 0.0
    if p_lo is None or p_hi is None:
        return None
    return max(0.0, p_lo - p_hi)


def lineas_del_tablero(det: Dict, home: str, away: str) -> Dict[str, List]:
    """
    Qué líneas publica la casa, para pedirle al modelo sólo ésas.

    Devuelve `{'handicap': [-3.5], 'total': [44.5], 'total_home': [18.5],
    'total_away': [16.5], 'margen_home': ['7-12', '43+'], ...}`.
    """
    out: Dict[str, List] = {'handicap': [], 'total': [], 'total_home': [],
                            'total_away': [], 'margen_home': [], 'margen_away': []}
    if not isinstance(det, dict):
        return out
    ch = _norm(det.get('casa_home') or home)
    ca = _norm(det.get('casa_away') or away)
    for m in (det.get('mercados') or []):
        base = _norm(m.get('nombre')).replace('(incl. prorroga)', '').strip()
        if base.startswith(('1a mitad', '2a mitad', 'primer cuarto')) \
                or 'cuarto' in base:
            continue
        sels = m.get('selecciones') or []
        if base == 'handicap':
            for s in sels:
                mt = _LINEA_HCP.match(str(s.get('nombre') or '').strip())
                if mt and _norm(mt.group(1)) == ch:
                    v = _num(mt.group(2))
                    if v is not None:
                        out['handicap'].append(v)
        elif base in ('totales', 'total'):
            for s in sels:
                mt = _LINEA.match(str(s.get('nombre') or '').strip())
                if mt:
                    v = _num(mt.group(2))
                    if v is not None:
                        out['total'].append(v)
        elif base.endswith(' total') or base.endswith(' totales'):
            quien = _norm(base.rsplit(' ', 1)[0])
            clave = 'total_home' if quien == ch else 'total_away' if quien == ca else None
            if not clave:
                continue
            for s in sels:
                mt = _LINEA.match(str(s.get('nombre') or '').strip())
                if mt:
                    v = _num(mt.group(2))
                    if v is not None:
                        out[clave].append(v)
        elif base.startswith('margen de victoria'):
            for s in sels:
                mt = _MARGEN.match(' '.join(str(s.get('nombre') or '').split()))
                if not mt:
                    continue
                quien = _norm(mt.group(1))
                clave = ('margen_home' if quien == ch
                         else 'margen_away' if quien == ca else None)
                if clave:
                    out[clave].append(mt.group(2).replace(' ', ''))
    for k in out:
        out[k] = sorted(set(out[k]), key=str)
    return out


def mercados_con_ev_nfl(det: Dict, pred: Dict, home: str, away: str) -> List[Dict]:
    """
    El tablero de la NFL cruzado con el modelo, listo para la interfaz.

    Reutiliza `cuotas_tablon.mercados_de_filas`, que trae el line shopping, el
    veto por seña y la deduplicación ya probados. Lo único propio de la NFL es
    el vocabulario de las dos entradas.
    """
    try:
        import cuotas_tablon as ct
    except Exception as e:
        logger.warning(f'[nfl] cuotas_tablon no disponible: {e}')
        return []
    filas = filas_playdoit_nfl(det, home, away)
    if not filas:
        return []
    pl = plantilla_nfl(pred, home, away, lineas_del_tablero(det, home, away))
    sin_ev = {f['etiqueta'] for f in filas if f.get('ev_no_fiable')}
    salida = ct.mercados_de_filas(filas, pl)
    for r in salida:
        if r.get('texto_pegado') in sin_ev:
            r['ev_no_fiable'] = True
            r['motivo_no_fiable'] = (
                'el modelo predice el partido completo; no tiene medido el '
                'reparto por mitad ni por cuarto, así que este EV no mide valor')
    # las filas SIN cruce con el modelo también se enseñan: son precio real de
    # la casa del usuario, y ocultarlas dejaría medio tablero invisible
    cruzadas = {r.get('texto_pegado') for r in salida}
    for f in filas:
        if f['etiqueta'] in cruzadas:
            continue
        salida.append({'mercado': f.get('familia', ''), 'apuesta': f['etiqueta'],
                       'prob': None, 'cuota_casa': f['cuota'],
                       'casa': f.get('casa'), 'cuota_justa': None, 'ev': None,
                       'n_casas': 1, 'familia': f.get('familia'),
                       'texto_pegado': f['etiqueta'],
                       'sin_modelo': True,
                       'motivo_no_fiable': 'el modelo no cubre este mercado'})
    return salida
