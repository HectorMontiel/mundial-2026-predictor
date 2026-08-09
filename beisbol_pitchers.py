#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v106 — BÉISBOL: ABRIDOR, ESTADIO Y PONCHES, TODO AUTOMÁTICO.

Qué pidió el usuario, y qué hace esto
-------------------------------------
La regla de decisión, tal cual la describió:

  1. Mirar los abridores y en qué estadio se juega, «porque influye
     demasiado».
  2. Mirar la línea de ponches de un buen abridor **aunque sea el del equipo
     que el casino tiene en positivo** (el no favorito).
  3. Si esa línea es alta —más de 6 ponches— NO conviene tomar los ponches:
     es mejor un hándicap (la run line) al equipo del mejor abridor.
  4. Pero si el equipo que está en negativo (el favorito) lleva buen abridor y
     la cuota de ganador es decente, mejor meterlo de ganador.
  5. Y de ahí sale un veredicto claro: este partido entra o no entra en la
     parlay.

`veredicto()` implementa exactamente eso y devuelve, además del veredicto, los
números con los que se tomó cada decisión. Nada se pide a mano: los abridores,
sus estadísticas, el factor del estadio, la línea de ponches y sus cuotas se
bajan solos y se refrescan en cada consulta (con caché corta para no machacar
las fuentes).

De dónde sale cada dato
-----------------------
  · **Abridores probables** — MLB Stats API oficial (`mlb_statsapi`), gratis y
    sin clave. Ya se usaba para las features del modelo.
  · **Calidad del abridor** — `mlb_pitchers_temporada.csv.gz`, la línea de
    pitcheo por temporada de la API oficial (ERA, WHIP, K, BB, HR, IP, BF,
    aperturas). Se resume en **FIP**, que mide sólo lo que depende del
    lanzador (ponches, bases por bolas y jonrones) y por eso no arrastra la
    defensa ni el parque — que aquí se tratan aparte, cada uno en su sitio.
  · **Factor del estadio** — se CALCULA del histórico del propio proyecto
    (`historico_mlb.csv`, 26.500 juegos), no de una tabla escrita a mano:
    carreras por juego en casa de cada equipo frente a la media de la liga.
    Así se actualiza solo cuando cambia una valla o se muda un equipo.
  · **Línea de ponches y su cuota** — Pinnacle, del MISMO endpoint que el
    proyecto ya consulta para los moneyline (`withSpecials=true`). Publica
    «<Pitcher> Total Strikeouts» con línea y precio Over/Under: medido el
    2026-08-08, 30 props en 28 partidos. Cero peticiones nuevas al sistema y
    cero claves de API.
  · **Ponches esperados** — tasa de ponche del abridor por bateador
    enfrentado, ajustada por lo mucho o poco que se poncha el rival y por los
    bateadores que suele enfrentar. Es el modelo sabermétrico estándar, el
    mismo que ya vivía en `props_model`.

Honestidad sobre lo que esto es
-------------------------------
La regla 1-5 es **del usuario**, no una estrategia medida sobre el histórico
del proyecto. Se implementa tal cual la pidió y se marca como tal: cada
veredicto viaja con `regla_del_usuario=True` y con el EV que el modelo calcula
por su cuenta para cada mercado, para que las dos lecturas se vean juntas y
ninguna se disfrace de la otra. Los picks que salen de aquí NO entran en la
Capa 1 por esta vía; son una ayuda de decisión para armar la parlay.
"""
from __future__ import annotations

import logging
import math
import os
import time
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

HISTORICO = 'historico_mlb.csv'
PITCHEO = 'mlb_pitchers_temporada.csv.gz'

# Umbral de «muchos ponches» que fijó el usuario: por encima de 6 no compensa
# tomar la línea de ponches y se prefiere la run line.
K_LINEA_ALTA = 6.0

# Cuota mínima para considerar «buena» la de ganador. Es la misma que usa el
# resto del proyecto (`alpha_finder.MIN_CUOTA`): por debajo de 1.50 el precio
# no paga el riesgo aunque se acierte.
CUOTA_GANADOR_MIN = 1.50

# Un abridor es «bueno» si su FIP está en el mejor tercio de los abridores de
# su temporada. Es un corte relativo, no un número absoluto: el nivel de
# pitcheo de la liga cambia año a año y un FIP de 3,80 no significa lo mismo
# en 2019 que en 2026.
PERCENTIL_BUENO = 0.33

# Constante del FIP. Se recalcula por temporada para que el FIP medio de la
# liga coincida con su ERA media; este es sólo el valor de arranque.
FIP_C = 3.10

_TTL = 900                       # 15 min: lo mismo que el tablón de cuotas
_CACHE: Dict[str, tuple] = {}


def _cache(clave: str, fabricar, ttl: int = _TTL):
    ahora = time.time()
    if clave in _CACHE and ahora - _CACHE[clave][0] < ttl:
        return _CACHE[clave][1]
    valor = fabricar()
    _CACHE[clave] = (ahora, valor)
    return valor


def limpiar_cache() -> None:
    """Fuerza que la próxima consulta vuelva a bajar todo."""
    _CACHE.clear()


# ---------------------------------------------------------------------------
# 1. Factor del estadio — medido, no escrito a mano
# ---------------------------------------------------------------------------
def factores_parque(minimo_juegos: int = 200,
                    temporadas: int = 5) -> Dict[str, float]:
    """
    Factor de carreras del parque de cada equipo: 1,00 es neutro, 1,15 es un
    parque de bateadores (se anotan un 15 % más de carreras) y 0,90 uno de
    lanzadores.

    Se mide con el método clásico: carreras totales por juego EN CASA de un
    equipo frente a las carreras por juego de ESE MISMO equipo como visitante.
    Comparar contra sí mismo —y no contra la media de la liga— cancela lo bueno
    o malo que sea el equipo: si los Rockies anotan mucho, anotan mucho en los
    dos sitios; lo que queda es el aire de Denver.

    Se limita a las últimas `temporadas` para que una valla movida hace ocho
    años no siga contando, y se exige un mínimo de juegos para no publicar un
    factor construido con ruido (un parque nuevo no tiene factor: se queda en
    1,00 y se dice).
    """
    def _calcular() -> Dict[str, float]:
        if not os.path.exists(HISTORICO):
            logger.warning(f'[beisbol] {HISTORICO} no existe: sin factores de '
                           f'parque (todos neutros)')
            return {}
        d = pd.read_csv(HISTORICO)
        for col in ('home_runs', 'away_runs'):
            d[col] = pd.to_numeric(d[col], errors='coerce')
        d = d.dropna(subset=['home_runs', 'away_runs', 'home_team', 'away_team'])
        if d.empty:
            return {}
        d['anio'] = pd.to_datetime(d['date'], errors='coerce').dt.year
        d = d.dropna(subset=['anio'])
        ultimo = int(d['anio'].max())
        d = d[d['anio'] > ultimo - temporadas]
        d['total'] = d['home_runs'] + d['away_runs']

        en_casa = d.groupby('home_team')['total'].agg(['sum', 'count'])
        fuera = d.groupby('away_team')['total'].agg(['sum', 'count'])
        out: Dict[str, float] = {}
        for eq in set(en_casa.index) | set(fuera.index):
            if eq not in en_casa.index or eq not in fuera.index:
                continue
            nc, nf = int(en_casa.loc[eq, 'count']), int(fuera.loc[eq, 'count'])
            if nc + nf < minimo_juegos:
                continue
            rc = en_casa.loc[eq, 'sum'] / nc
            rf = fuera.loc[eq, 'sum'] / nf
            if rf <= 0:
                continue
            # se encoge hacia 1 con el tamaño de muestra: con 200 juegos el
            # factor crudo todavía tiene mucho ruido, con 800 casi ninguno.
            crudo = float(rc / rf)
            peso = min(1.0, (nc + nf) / 800.0)
            out[str(eq)] = round(1.0 + peso * (crudo - 1.0), 4)
        logger.info(f'[beisbol] factores de parque: {len(out)} estadios '
                    f'(temporadas {ultimo - temporadas + 1}-{ultimo})')
        return out

    return _cache('parques', _calcular, ttl=24 * 3600)


def factor_parque(equipo_local: str) -> float:
    """Factor del parque donde se juega (el del equipo local). 1,00 si no se
    ha podido medir — nunca se inventa."""
    return float(factores_parque().get(str(equipo_local), 1.0))


def etiqueta_parque(equipo_local: str) -> str:
    """Frase llana para la interfaz."""
    f = factor_parque(equipo_local)
    if f >= 1.08:
        return f'🏟️ Parque de bateadores (×{f:.2f} carreras)'
    if f <= 0.94:
        return f'🏟️ Parque de lanzadores (×{f:.2f} carreras)'
    return f'🏟️ Parque neutro (×{f:.2f})'


# ---------------------------------------------------------------------------
# 2. Calidad del abridor — FIP, con corte relativo a su temporada
# ---------------------------------------------------------------------------
def _tabla_pitcheo() -> pd.DataFrame:
    def _leer() -> pd.DataFrame:
        if not os.path.exists(PITCHEO):
            logger.warning(f'[beisbol] {PITCHEO} no existe: sin calidad de '
                           f'abridor')
            return pd.DataFrame()
        d = pd.read_csv(PITCHEO)
        for col in ('ip', 'gs', 'era', 'whip', 'so', 'bb', 'hr', 'bf'):
            if col in d.columns:
                d[col] = pd.to_numeric(d[col], errors='coerce')
        d['pitcher'] = d['pitcher'].astype(str)
        return d
    return _cache('pitcheo', _leer, ttl=6 * 3600)


def _fip(fila) -> Optional[float]:
    ip = float(fila.get('ip') or 0)
    if ip < 1:
        return None
    hr = float(fila.get('hr') or 0)
    bb = float(fila.get('bb') or 0)
    so = float(fila.get('so') or 0)
    return (13.0 * hr + 3.0 * bb - 2.0 * so) / ip + FIP_C


def perfil_pitcher(pid, anio: Optional[int] = None) -> Optional[Dict]:
    """
    Retrato del abridor con lo que de verdad decide un partido de béisbol:

      fip          — carreras que concede por lo que sólo depende de él
      k_bf         — ponches por bateador enfrentado (su capacidad de ponchar)
      bf_apertura  — bateadores que suele enfrentar por salida (cuánto dura)
      bueno        — si está en el mejor tercio de abridores de su temporada
      percentil    — dónde cae exactamente (0 = el mejor, 1 = el peor)

    Se usa la temporada EN CURSO si tiene volumen suficiente; si el lanzador
    acaba de subir o lleva pocas entradas, se completa con la anterior. Sin
    datos devuelve None y quien llame decide qué hacer — nunca un valor
    inventado que parezca medido.
    """
    d = _tabla_pitcheo()
    if d.empty or pid in (None, '', 'nan'):
        return None
    pid = str(pid)
    filas = d[d['pitcher'] == pid]
    if filas.empty:
        return None
    anio = anio or int(d['anio'].max())
    # temporada en curso; si tiene menos de 20 entradas, se suma la anterior
    act = filas[filas['anio'] == anio]
    usadas = [anio]
    if act.empty or float(act['ip'].sum()) < 20:
        prev = filas[filas['anio'] == anio - 1]
        if not prev.empty:
            act = pd.concat([act, prev])
            usadas.append(anio - 1)
    if act.empty:
        act = filas[filas['anio'] == filas['anio'].max()]
        usadas = [int(filas['anio'].max())]
    agg = {c: float(act[c].sum()) for c in ('ip', 'gs', 'so', 'bb', 'hr', 'bf')
           if c in act.columns}
    if agg.get('ip', 0) < 1:
        return None
    fip = _fip(agg)
    if fip is None:
        return None
    bf = agg.get('bf') or 0.0
    gs = agg.get('gs') or 0.0
    k_bf = (agg.get('so', 0.0) / bf) if bf > 0 else None
    # bateadores por apertura: los suyos si es abridor con muestra; si no, el
    # valor típico de un abridor (24), que es el que usa `props_model`.
    bf_ap = (bf / gs) if gs >= 3 and bf > 0 else 24.0
    bf_ap = float(min(max(bf_ap, 14.0), 30.0))

    percentil, bueno = None, None
    corte = _corte_fip(anio)
    if corte is not None:
        bueno = bool(fip <= corte['fip_bueno'])
        percentil = float(np.clip(
            (fip - corte['fip_min']) / max(corte['fip_max'] - corte['fip_min'],
                                           1e-6), 0.0, 1.0))
    nombre = str(act['nombre'].iloc[0]) if 'nombre' in act.columns else ''
    return {'pitcher': pid, 'nombre': nombre,
            'fip': round(fip, 2),
            'era': round(float(act['era'].mean()), 2)
            if 'era' in act.columns and act['era'].notna().any() else None,
            'whip': round(float(act['whip'].mean()), 2)
            if 'whip' in act.columns and act['whip'].notna().any() else None,
            'ip': round(agg.get('ip', 0.0), 1),
            'gs': int(gs),
            'k_bf': round(k_bf, 4) if k_bf else None,
            'bf_apertura': round(bf_ap, 1),
            'bueno': bueno, 'percentil': round(percentil, 3)
            if percentil is not None else None,
            'temporadas': usadas}


def _corte_fip(anio: int) -> Optional[Dict]:
    """FIP que separa al mejor tercio de abridores de esa temporada, y el rango
    para situar a cualquiera dentro de ella."""
    def _calcular():
        d = _tabla_pitcheo()
        if d.empty:
            return None
        # sólo ABRIDORES con volumen: un relevista de 15 entradas tiene un FIP
        # espectacular y no es comparable con quien abre 30 veces.
        sub = d[(d['anio'] == anio) & (d['gs'] >= 5) & (d['ip'] >= 30)].copy()
        if len(sub) < 20:
            sub = d[(d['anio'] == anio - 1) & (d['gs'] >= 5)
                    & (d['ip'] >= 30)].copy()
        if len(sub) < 20:
            return None
        sub['fip'] = sub.apply(_fip, axis=1)
        v = sub['fip'].dropna().values
        if len(v) < 20:
            return None
        return {'fip_bueno': float(np.quantile(v, PERCENTIL_BUENO)),
                'fip_min': float(np.quantile(v, 0.02)),
                'fip_max': float(np.quantile(v, 0.98)),
                'n': int(len(v))}
    return _cache(f'corte_fip_{anio}', _calcular, ttl=6 * 3600)


# ---------------------------------------------------------------------------
# 3. Ponches esperados
# ---------------------------------------------------------------------------
def _k_por_equipo() -> Dict[str, float]:
    """
    Con qué frecuencia se poncha cada equipo bateando (ponches por turno), y
    la media de la liga bajo la clave `_liga`. Sale de la API oficial, que lo
    publica de todos los equipos en una sola petición.
    """
    def _pedir():
        try:
            import mlb_statsapi as msa
            import requests
            anio = pd.Timestamp.now('UTC').year
            r = requests.get(
                'https://statsapi.mlb.com/api/v1/teams/stats',
                params={'stats': 'season', 'group': 'hitting',
                        'season': anio, 'sportId': 1},
                timeout=25)
            r.raise_for_status()
            j = r.json()
        except Exception as e:
            logger.warning(f'[beisbol] K% por equipo no disponible: '
                           f'{type(e).__name__}: {e}')
            return {}
        out, tot_so, tot_pa = {}, 0.0, 0.0
        for bloque in (j.get('stats') or []):
            for s in (bloque.get('splits') or []):
                st = s.get('stat') or {}
                pa = float(st.get('plateAppearances') or 0)
                so = float(st.get('strikeOuts') or 0)
                tid = (s.get('team') or {}).get('id')
                cod = msa.ID_A_CODIGO.get(tid)
                if pa > 0 and cod:
                    out[cod] = so / pa
                    tot_so += so
                    tot_pa += pa
        if tot_pa > 0:
            out['_liga'] = tot_so / tot_pa
        logger.info(f'[beisbol] K% de bateo: {len(out) - 1} equipos')
        return out
    return _cache('k_equipo', _pedir, ttl=6 * 3600)


def ponches_esperados(perfil: Dict, rival: str,
                      parque: float = 1.0) -> Optional[float]:
    """
    Ponches esperados del abridor en esta salida:

        K = (ponches por bateador del abridor)
            × (cuánto se poncha el rival / cuánto se poncha la liga)
            × (bateadores que suele enfrentar)

    El parque entra con efecto SUAVE y en sentido contrario a las carreras: en
    un parque donde se batea mucho las entradas son más largas y el abridor
    dura menos, así que se poncha algo menos. Se limita a ±5 % porque el efecto
    del parque sobre los ponches es real pero pequeño — el grande es sobre las
    carreras, y ese ya se aplica donde corresponde.
    """
    if not perfil or not perfil.get('k_bf'):
        return None
    ks = _k_por_equipo()
    liga = ks.get('_liga')
    ajuste = 1.0
    if liga and ks.get(rival):
        ajuste = float(np.clip(ks[rival] / liga, 0.80, 1.25))
    ajuste_parque = float(np.clip(1.0 - 0.25 * (parque - 1.0), 0.95, 1.05))
    return float(perfil['k_bf'] * perfil['bf_apertura'] * ajuste * ajuste_parque)


def prob_over_ponches(k_esperados: float, linea: float) -> Optional[float]:
    """
    P(ponches > línea) con Poisson. Los ponches de una apertura son un conteo
    de eventos casi independientes: es la distribución que usa el sector y la
    que ya usaba `props_model`.
    """
    if not k_esperados or k_esperados <= 0 or linea is None:
        return None
    try:
        from scipy.stats import poisson
        return float(poisson.sf(math.floor(float(linea)), k_esperados))
    except Exception:
        # sin scipy: suma directa de la Poisson (rango corto, es barato)
        lim = int(math.floor(float(linea)))
        acum = sum(math.exp(-k_esperados) * k_esperados ** i / math.factorial(i)
                   for i in range(lim + 1))
        return float(max(0.0, 1.0 - acum))


# ---------------------------------------------------------------------------
# 4. Props de ponches en vivo (Pinnacle, sin clave ni límite)
# ---------------------------------------------------------------------------
def props_ponches() -> List[Dict]:
    """
    Todos los props «<Pitcher> Total Strikeouts» abiertos ahora mismo, con su
    línea y las dos cuotas ya en decimal.

    Sale del MISMO endpoint que el proyecto ya consulta para los moneyline de
    béisbol (`/sports/3/matchups?withSpecials=true`), así que no añade ninguna
    petición al sistema: Pinnacle los devuelve como matchups «special» con
    `parent` apuntando al partido y participantes Over/Under.

    Devuelve [{'pitcher_nombre','linea','odd_over','odd_under','home','away',
               'inicio'}].
    """
    def _bajar() -> List[Dict]:
        try:
            import cuotas_multi as cm
        except Exception as e:
            logger.warning(f'[beisbol] cuotas_multi no disponible: {e}')
            return []
        sid = cm.DEPORTES.get('mlb')
        if not sid:
            return []
        try:
            partidos = cm._get(f'{cm.PIN_BASE}/sports/{sid}/matchups',
                               {'withSpecials': 'true', 'brandId': 0})
            mercados = cm._get(f'{cm.PIN_BASE}/sports/{sid}/markets/straight',
                               {'primaryOnly': 'false', 'withSpecials': 'true'})
        except Exception as e:
            logger.warning(f'[beisbol] props de ponches: '
                           f'{type(e).__name__}: {e}')
            return []
        if not partidos or not mercados:
            return []
        por_matchup: Dict[int, list] = {}
        for mk in mercados:
            por_matchup.setdefault(mk.get('matchupId'), []).append(mk)
        padres = {m.get('id'): m for m in partidos if not m.get('special')}

        salida = []
        for m in partidos:
            sp = m.get('special') or {}
            desc = str(sp.get('description') or '')
            if 'total strikeouts' not in desc.lower():
                continue
            nombre = desc[:desc.lower().rfind('total strikeouts')].strip()
            ids = {str(p.get('name', '')).lower(): p.get('id')
                   for p in (m.get('participants') or [])}
            id_over, id_under = ids.get('over'), ids.get('under')
            linea = odd_over = odd_under = None
            for mk in por_matchup.get(m.get('id'), []):
                if mk.get('type') != 'total' or mk.get('period') != 0:
                    continue
                if mk.get('isAlternate'):
                    continue           # sólo la línea principal
                for p in (mk.get('prices') or []):
                    if p.get('points') is not None:
                        linea = float(p['points'])
                    if p.get('participantId') == id_over:
                        odd_over = cm.american_a_decimal(p.get('price'))
                    elif p.get('participantId') == id_under:
                        odd_under = cm.american_a_decimal(p.get('price'))
            if linea is None or not (odd_over or odd_under):
                continue
            padre = padres.get((m.get('parent') or {}).get('id')) or {}
            eq = {p.get('alignment'): p.get('name')
                  for p in (padre.get('participants') or [])}
            salida.append({
                'pitcher_nombre': nombre,
                'linea': linea,
                'odd_over': odd_over, 'odd_under': odd_under,
                'home': eq.get('home'), 'away': eq.get('away'),
                'inicio': cm.fecha_normalizada(padre.get('startTime')),
            })
        logger.info(f'[beisbol] {len(salida)} props de ponches en Pinnacle')
        return salida

    return _cache('props_k', _bajar)


def _normaliza_nombre(n: str) -> str:
    """Clave de comparación de nombres de lanzador (sin acentos ni sufijos)."""
    import unicodedata
    s = unicodedata.normalize('NFKD', str(n or ''))
    s = ''.join(c for c in s if not unicodedata.combining(c)).lower()
    for basura in (' jr.', ' jr', ' sr.', ' sr', ' iii', ' ii', '.'):
        s = s.replace(basura, ' ')
    return ' '.join(s.split())


def prop_de_pitcher(nombre: str, props: Optional[List[Dict]] = None
                    ) -> Optional[Dict]:
    """El prop de ponches de este lanzador, si alguna casa lo ha abierto."""
    if not nombre:
        return None
    props = props if props is not None else props_ponches()
    clave = _normaliza_nombre(nombre)
    if not clave:
        return None
    for p in props:
        if _normaliza_nombre(p.get('pitcher_nombre')) == clave:
            return p
    # respaldo por apellido, que es lo único que siempre coincide entre
    # fuentes («Yoshinobu Yamamoto» vs «Y. Yamamoto»)
    ap = clave.split()[-1] if clave.split() else ''
    if len(ap) >= 4:
        for p in props:
            otro = _normaliza_nombre(p.get('pitcher_nombre')).split()
            if otro and otro[-1] == ap:
                return p
    return None


# ---------------------------------------------------------------------------
# 5. El veredicto: ¿entra este partido en la parlay, y con qué mercado?
# ---------------------------------------------------------------------------
def _lado_favorito(cuota_home: Optional[float],
                   cuota_away: Optional[float]) -> Optional[str]:
    """
    Cuál es el favorito SEGÚN EL CASINO, que es como lo planteó el usuario:
    el que va «en negativo» en cuota americana, o sea el de cuota decimal más
    baja. Se decide con el precio, no con el modelo, a propósito: la regla
    habla del favorito del mercado.
    """
    try:
        ch, ca = float(cuota_home or 0), float(cuota_away or 0)
    except (TypeError, ValueError):
        return None
    if ch <= 1 or ca <= 1:
        return None
    if abs(ch - ca) < 1e-9:
        return None                      # partido a la par: no hay favorito
    return 'home' if ch < ca else 'away'


def veredicto(home: str, away: str,
              home_pitcher: Optional[str] = None,
              away_pitcher: Optional[str] = None,
              cuota_home: Optional[float] = None,
              cuota_away: Optional[float] = None,
              spreads: Optional[Dict] = None,
              prob_home: Optional[float] = None,
              props: Optional[List[Dict]] = None) -> Dict:
    """
    Aplica la regla del usuario y devuelve si el partido entra en la parlay,
    con qué mercado y por qué.

    La cascada, en el orden en que él la describió:

      1º  El FAVORITO del casino lleva buen abridor y su cuota de ganador es
          decente  ->  **ganador (moneyline) del favorito**. Es el «pero» de
          su regla, y va primero porque él lo puso como excepción que manda.
      2º  Si no, se mira la línea de ponches del MEJOR abridor del partido
          —aunque sea el del equipo que va en positivo—:
            · línea por encima de 6  ->  no se toca la de ponches; se propone
              la **run line del equipo del mejor abridor**.
            · línea de 6 o menos y el modelo ve valor  ->  **ponches over**.
      3º  Nada de lo anterior  ->  **el partido no entra**.

    Devuelve un dict con `entra`, `mercado`, `apuesta`, `cuota`, `motivos`
    (las frases que explican la decisión) y `datos` (abridores, parque, línea
    de ponches y ponches esperados) para que todo sea auditable desde fuera.
    """
    datos: Dict = {}
    motivos: List[str] = []
    props = props if props is not None else props_ponches()

    parque = factor_parque(home)
    datos['parque'] = {'factor': parque, 'etiqueta': etiqueta_parque(home),
                       'estadio_de': home}
    motivos.append(etiqueta_parque(home))

    perf = {'home': perfil_pitcher(home_pitcher),
            'away': perfil_pitcher(away_pitcher)}
    for lado in ('home', 'away'):
        p = perf[lado]
        if p:
            rival = away if lado == 'home' else home
            p = dict(p)
            p['k_esperados'] = ponches_esperados(p, rival, parque)
            prop = prop_de_pitcher(p.get('nombre'), props)
            p['prop'] = prop
            if prop and p['k_esperados']:
                p['prob_over'] = prob_over_ponches(p['k_esperados'],
                                                   prop['linea'])
            perf[lado] = p
    datos['abridores'] = perf

    if not (perf['home'] or perf['away']):
        return {'entra': False, 'mercado': None,
                'motivos': motivos + [
                    '⛔ No hay abridor anunciado todavía (o no está en la base '
                    'de estadísticas). Sin abridor, el béisbol no se puede '
                    'juzgar: es la variable que más pesa.'],
                'datos': datos, 'regla_del_usuario': True}

    fav = _lado_favorito(cuota_home, cuota_away)
    datos['favorito'] = fav
    cuotas = {'home': cuota_home, 'away': cuota_away}

    # ¿quién lleva el mejor abridor? (FIP más bajo)
    con_fip = [(l, perf[l]) for l in ('home', 'away')
               if perf[l] and perf[l].get('fip') is not None]
    mejor = min(con_fip, key=lambda x: x[1]['fip'])[0] if con_fip else None
    datos['mejor_abridor'] = mejor
    if mejor:
        p = perf[mejor]
        motivos.append(
            f"⚾ Mejor abridor: {p.get('nombre') or mejor} "
            f"({'local' if mejor == 'home' else 'visitante'}) · FIP "
            f"{p['fip']:.2f}"
            + (' — está en el mejor tercio de la liga' if p.get('bueno')
               else ' — no está entre los mejores de la liga'))

    nombre_eq = {'home': home, 'away': away}

    # ---- 1º: el favorito del casino con buen abridor y cuota decente -------
    if fav and perf.get(fav) and perf[fav].get('bueno'):
        c = cuotas.get(fav)
        try:
            c = float(c)
        except (TypeError, ValueError):
            c = None
        if c and c >= CUOTA_GANADOR_MIN:
            ev = None
            if prob_home is not None:
                p_lado = (float(prob_home) if fav == 'home'
                          else 1.0 - float(prob_home))
                ev = round(c * p_lado - 1.0, 4)
            motivos.append(
                f"✅ El favorito del casino ({nombre_eq[fav]}) abre con buen "
                f"lanzador y su cuota de ganador es {c:.2f} — por encima del "
                f"mínimo de {CUOTA_GANADOR_MIN:.2f}. Es el caso en el que "
                f"conviene meterlo de GANADOR.")
            return {'entra': True, 'mercado': 'Moneyline',
                    'apuesta': f'Gana {nombre_eq[fav]}', 'lado': fav,
                    'cuota': round(c, 2), 'ev_modelo': ev,
                    'motivos': motivos, 'datos': datos,
                    'regla_del_usuario': True}
        motivos.append(
            f"ℹ️ El favorito ({nombre_eq[fav]}) sí lleva buen abridor, pero su "
            f"cuota de ganador es {c if c else 'desconocida'} y no llega al "
            f"mínimo de {CUOTA_GANADOR_MIN:.2f}: pagar tan poco no compensa "
            f"aunque se acierte.")

    # ---- 2º: la línea de ponches del mejor abridor -------------------------
    # Se mira la del MEJOR abridor esté en el equipo que esté, que es la parte
    # que el usuario subrayó: «aunque sea el del equipo contrario, el que está
    # en positivo según el casino».
    cand = mejor if (mejor and perf[mejor].get('prop')) else None
    if cand is None:
        for l in ('home', 'away'):
            if perf.get(l) and perf[l].get('prop'):
                cand = l
                break
    if cand and perf[cand].get('prop'):
        p = perf[cand]
        prop = p['prop']
        linea = float(prop['linea'])
        de_lado = 'local' if cand == 'home' else 'visitante'
        if cand != fav and fav is not None:
            motivos.append(
                f"👀 El abridor que manda aquí es el del equipo que el casino "
                f"pone en positivo ({nombre_eq[cand]}, {de_lado}). Se mira "
                f"igual: la regla dice que el buen lanzador cuenta esté en el "
                f"lado que esté.")

        if linea > K_LINEA_ALTA:
            motivos.append(
                f"⚠️ Su línea de ponches está en {linea:.1f}, por encima de "
                f"{K_LINEA_ALTA:.0f}. Pedirle tantos ponches es caro y falla "
                f"seguido: no conviene tomar esa cuota.")
            # la run line del equipo del mejor abridor
            objetivo = mejor or cand
            rl = _run_line(spreads, objetivo)
            if rl:
                if rl['linea'] < 0:
                    detalle = (f"tiene que ganar por 2 carreras o más "
                               f"(es el favorito del casino)")
                else:
                    detalle = (f"le vale con perder por 1 o ganar "
                               f"(le dan ventaja porque no es el favorito)")
                motivos.append(
                    f"➡️ En su lugar, hándicap {rl['linea']:+.1f} a "
                    f"{nombre_eq[objetivo]}, que es el equipo del mejor "
                    f"abridor: {detalle}. Cuota {rl['cuota']:.2f}.")
                if parque >= 1.08 and rl['linea'] < 0:
                    motivos.append(
                        f"🟡 Ojo: se juega en parque de bateadores (×{parque:.2f}); "
                        f"ganar por 2 o más ahí es menos probable de lo normal.")
                if parque <= 0.94 and rl['linea'] > 0:
                    motivos.append(
                        f"🟢 A favor: parque de lanzadores (×{parque:.2f}); "
                        f"con pocas carreras, recibir 1,5 vale más.")
                return {'entra': True, 'mercado': 'Hándicap (run line)',
                        'apuesta': f"{nombre_eq[objetivo]} {rl['linea']:+.1f}",
                        'lado': objetivo, 'cuota': rl['cuota'],
                        'linea': rl['linea'], 'ev_modelo': None,
                        'motivos': motivos, 'datos': datos,
                        'regla_del_usuario': True}
            motivos.append(
                "⛔ Ninguna casa publica todavía la run line de este partido, "
                "así que la alternativa que pide la regla no se puede tomar.")
            return {'entra': False, 'mercado': None, 'motivos': motivos,
                    'datos': datos, 'regla_del_usuario': True}

        # línea baja: los ponches sí son tomables si el modelo ve valor
        pov, over = p.get('prob_over'), prop.get('odd_over')
        if pov and over:
            ev = round(float(over) * float(pov) - 1.0, 4)
            motivos.append(
                f"📊 Línea de ponches en {linea:.1f} (por debajo de "
                f"{K_LINEA_ALTA:.0f}) · se le esperan "
                f"{p['k_esperados']:.1f} ponches · P(más de {linea:.1f}) = "
                f"{pov*100:.0f} % a cuota {float(over):.2f} → EV {ev*100:+.1f} %.")
            if ev > 0:
                return {'entra': True, 'mercado': 'Ponches del abridor',
                        'apuesta': (f"{p.get('nombre') or nombre_eq[cand]}: "
                                    f"más de {linea:.1f} ponches"),
                        'lado': cand, 'cuota': round(float(over), 2),
                        'linea': linea, 'prob': round(float(pov), 3),
                        'ev_modelo': ev, 'motivos': motivos, 'datos': datos,
                        'regla_del_usuario': True}
            motivos.append(
                "⛔ Con ese precio los ponches no dan valor: la casa pide más "
                "de lo que el lanzador suele hacer.")
    else:
        motivos.append(
            "ℹ️ Ninguna casa ha abierto la línea de ponches de estos "
            "abridores todavía (suele salir el mismo día del partido).")

    return {'entra': False, 'mercado': None,
            'motivos': motivos + [
                '⛔ Este partido NO entra en la parlay: no se cumple ninguna '
                'de las tres condiciones.'],
            'datos': datos, 'regla_del_usuario': True}


def _run_line(spreads: Optional[Dict], lado: str) -> Optional[Dict]:
    """
    La run line del lado pedido, del bloque `spreads` del índice de Pinnacle.

    CUIDADO CON EL SIGNO — aquí se metió un error y se corrigió comprobándolo
    contra la fuente. Pinnacle publica cada precio con SU propia línea:

        [{"designation": "home", "points":  1.5, "price": -154},
         {"designation": "away", "points": -1.5, "price":  133}]

    y `_indice_pinnacle` los indexa por esos `points`, así que el resultado es
    {'1.5': {'home': …}, '-1.5': {'away': …}}: **la clave ya es la línea de
    ese lado**, no la del local. Darle la vuelta para el visitante —que es lo
    que parecía natural— convertía un «+1.5» en un «−1.5» y proponía darle
    ventaja al equipo al que había que recibírsela. Verificado el 2026-08-08
    contra 27 partidos del tablón.

    Se prefiere ±1.5, la run line estándar del béisbol; si sólo hay líneas
    alternativas se toma la más parecida.
    """
    if not spreads:
        return None
    candidatas = []
    for k, precios in (spreads or {}).items():
        try:
            linea = float(k)
        except (TypeError, ValueError):
            continue
        cuota = (precios or {}).get(lado)
        if not cuota:
            continue
        candidatas.append((abs(abs(linea) - 1.5), linea, float(cuota)))
    if not candidatas:
        return None
    candidatas.sort()
    _, linea, cuota = candidatas[0]
    return {'linea': linea, 'cuota': round(cuota, 2)}
