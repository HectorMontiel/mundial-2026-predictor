# -*- coding: utf-8 -*-
"""
v315 — EL MODELO PROPIO DE TODAS LAS COMPETICIONES QUE EL MOTOR DE LIGAS NO
CUBRE (sub-21, sub-20, sub-19, ascensos, copas, femenil, ligas chicas).

El usuario: «tenemos que tener un modelo propio para cada una de esas ligas y
competiciones… quiero que le hagas su modelo a cada uno al nivel que lo
tenemos nosotros, lo valides con las simulaciones de los finalizados más
recientes, para que también pueda aceptarlas en las patas que vamos a
meter».

EL MODELO
Sobre la base propia de resultados (`resultados_fotmob.py`, todas las
competiciones de FotMob desde julio de 2025):

  · cada equipo tiene una fuerza de ATAQUE y una DEBILIDAD DEFENSIVA, y cada
    competición su nivel de goles de local y de visitante;
  · goles esperados:  λ_local  = goles_local_liga  · e^(ataque_L + debilidad_V)
                      λ_visita = goles_visita_liga · e^(ataque_V + debilidad_L)
  · después de cada partido las fuerzas se corrigen con el error (goles
    reales − esperados), que es el gradiente de la verosimilitud de Poisson:
    lo que un equipo mete de más sube su ataque y la debilidad del rival;
  · de las λ salen, con Poisson y el ajuste de Dixon-Coles para los
    marcadores bajos, el 1X2, la doble oportunidad, más/menos de goles,
    ambos marcan y los goles de cada equipo.

Es el mismo tipo de modelo que el de las ligas grandes (ataque/defensa +
Poisson), pero secuencial: se entrena solo con cada día que entra en la base
y cada predicción usa sólo lo anterior al partido, así que la simulación de
los finalizados es fuera de muestra por construcción.

Un equipo con menos de `MIN_PARTIDOS` en la base no tiene modelo: no se
adivina. Y un partido que FotMob no lista no se puede liquidar: tampoco se
recomienda (lo que dejó sub-19 «marcador pendiente» el 29-sep).

Ver `_v315_modelo_competiciones.py` para la medición.
"""
from __future__ import annotations

import logging
import math
from typing import Dict, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

ETA = 0.04            # paso de la corrección (elegido en agosto, ver la medición)
DECAIMIENTO = 0.995   # las fuerzas vuelven hacia 0 con el tiempo
ALFA_LIGA = 0.03      # memoria del nivel de goles de cada competición
RHO = -0.08           # Dixon-Coles
MIN_PARTIDOS = 6
TOPE = 2.0


class Motor:
    """El estado del modelo tras recorrer la base."""

    def __init__(self, eta: float = ETA, alfa: float = ALFA_LIGA,
                 decaimiento: float = DECAIMIENTO):
        self.eta, self.alfa, self.dec = eta, alfa, decaimiento
        self.att: Dict = {}
        self.deb: Dict = {}
        self.n: Dict = {}
        self.liga: Dict = {}          # liga_id -> [media local, media visita, n]
        self.glob = [1.45, 1.15]
        self.nombre: Dict = {}         # id -> último nombre

    def _medias(self, liga_id):
        m = self.liga.get(liga_id)
        if m is None or m[2] < 10:
            # competición nueva: lo global, mezclado con lo poco que haya
            if m is None:
                return tuple(self.glob)
            w = m[2] / 10.0
            return (w * m[0] + (1 - w) * self.glob[0],
                    w * m[1] + (1 - w) * self.glob[1])
        return m[0], m[1]

    def lambdas(self, liga_id, h, a) -> Tuple[float, float]:
        mh, ma = self._medias(liga_id)
        lh = mh * math.exp(self.att.get(h, 0.0) + self.deb.get(a, 0.0))
        la = ma * math.exp(self.att.get(a, 0.0) + self.deb.get(h, 0.0))
        return min(max(lh, 0.05), 8.0), min(max(la, 0.05), 8.0)

    def partidos(self, eq) -> int:
        return self.n.get(eq, 0)

    def actualizar(self, liga_id, h, a, gh, ga, hn=None, an=None):
        lh, la = self.lambdas(liga_id, h, a)
        eh, ea = gh - lh, ga - la
        for eq in (h, a):
            self.att[eq] = self.att.get(eq, 0.0) * self.dec
            self.deb[eq] = self.deb.get(eq, 0.0) * self.dec
        k = self.eta
        self.att[h] = float(np.clip(self.att[h] + k * eh, -TOPE, TOPE))
        self.deb[a] = float(np.clip(self.deb[a] + k * eh, -TOPE, TOPE))
        self.att[a] = float(np.clip(self.att[a] + k * ea, -TOPE, TOPE))
        self.deb[h] = float(np.clip(self.deb[h] + k * ea, -TOPE, TOPE))
        self.n[h] = self.n.get(h, 0) + 1
        self.n[a] = self.n.get(a, 0) + 1
        m = self.liga.setdefault(liga_id, [self.glob[0], self.glob[1], 0])
        m[0] += self.alfa * (gh - m[0])
        m[1] += self.alfa * (ga - m[1])
        m[2] += 1
        self.glob[0] += 0.002 * (gh - self.glob[0])
        self.glob[1] += 0.002 * (ga - self.glob[1])
        if hn:
            self.nombre[h] = hn
        if an:
            self.nombre[a] = an


def entrenar(df, hasta=None, motor: Optional[Motor] = None,
             registrar_desde=None):
    """Recorre la base (ordenada por hora). Si `registrar_desde`, devuelve
    también la predicción previa de cada partido desde esa fecha (para medir
    fuera de muestra)."""
    m = motor or Motor()
    pred = []
    x = df if hasta is None else df[df['ini'] < hasta]
    for r in x.itertuples(index=False):
        if registrar_desde is not None and r.ini >= registrar_desde:
            lh, la = m.lambdas(r.liga_id, r.home_id, r.away_id)
            pred.append((r.match_id, lh, la, m.partidos(r.home_id),
                         m.partidos(r.away_id)))
        m.actualizar(r.liga_id, r.home_id, r.away_id, r.gh, r.ga,
                     r.home, r.away)
    return m, pred


def matriz(lh: float, la: float, rho: float = RHO, k: int = 11) -> np.ndarray:
    i = np.arange(k)
    fac = np.array([math.factorial(x) for x in i], dtype=float)
    ph = np.exp(-lh) * lh ** i / fac
    pa = np.exp(-la) * la ** i / fac
    M = np.outer(ph, pa)
    # Dixon-Coles: corrige 0-0, 1-0, 0-1 y 1-1
    M[0, 0] *= 1 - lh * la * rho
    M[0, 1] *= 1 + lh * rho
    M[1, 0] *= 1 + la * rho
    M[1, 1] *= 1 - rho
    return M / M.sum()


def probabilidades(lh: float, la: float) -> Dict[str, float]:
    M = matriz(lh, la)
    k = M.shape[0]
    ii, jj = np.meshgrid(np.arange(k), np.arange(k), indexing='ij')
    t = ii + jj
    p = {'home': float(M[ii > jj].sum()), 'draw': float(M[ii == jj].sum()),
         'away': float(M[ii < jj].sum())}
    p['homeOrDraw'] = p['home'] + p['draw']
    p['awayOrDraw'] = p['away'] + p['draw']
    for L in (0.5, 1.5, 2.5, 3.5, 4.5):
        p['mas_%s' % L] = float(M[t > L].sum())
        p['menos_%s' % L] = 1 - p['mas_%s' % L]
    p['btts_si'] = float(M[(ii > 0) & (jj > 0)].sum())
    p['btts_no'] = 1 - p['btts_si']
    for L in (0.5, 1.5, 2.5):
        p['local_mas_%s' % L] = float(M[ii > L].sum())
        p['visita_mas_%s' % L] = float(M[jj > L].sum())
    return p


# --------------------------------------------------------------- producción
_MEM: Dict = {}


def motor_actual() -> Optional[Motor]:
    """El modelo entrenado con toda la base. Se calcula una vez por proceso
    (≈ unos segundos) y sólo en el precálculo, nunca al pintar."""
    if 'm' in _MEM:
        return _MEM['m']
    try:
        import resultados_fotmob as rf
        df = rf.cargar()
        if not len(df):
            return None
        m, _ = entrenar(df)
        _MEM['m'] = m
        logger.info('[modelo_comp] entrenado con %d partidos, %d equipos',
                    len(df), len(m.n))
        return m
    except Exception as e:
        logger.warning('[modelo_comp] no se pudo entrenar: %s', e)
        return None


def _lista_fotmob(dia_utc: str):
    if dia_utc in _MEM:
        return _MEM[dia_utc]
    import fuente_bajas as fb
    import horario as hz
    doc = fb._get(fb.FOTMOB_DIA.format(fecha=dia_utc.replace('-', ''))) or {}
    out = []
    for L in doc.get('leagues') or []:
        for x in L.get('matches') or []:
            h, a = x.get('home') or {}, x.get('away') or {}
            ini = hz._a_utc((x.get('status') or {}).get('utcTime'))
            if ini is None:
                continue
            out.append({'ini': ini, 'match_id': x.get('id'),
                        'liga_id': L.get('primaryId') or L.get('id'),
                        'liga': L.get('name'), 'home_id': h.get('id'),
                        'home': h.get('name'), 'away_id': a.get('id'),
                        'away': a.get('name')})
    _MEM[dia_utc] = out
    return out


def partido_fotmob(home: str, away: str, inicio) -> Optional[Dict]:
    """El partido en FotMob (ids de liga y equipos): misma hora (±3 h) y los
    dos nombres. None si FotMob no lo lista: entonces no hay con qué predecir
    ni con qué liquidar."""
    import cuotas_multi as cm
    import horario as hz
    import partidos_jugados as pj
    ini = hz._a_utc(inicio)
    if ini is None:
        return None
    mejor, ms = None, 0.0
    for d in {ini.strftime('%Y-%m-%d'),
              (ini - __import__('datetime').timedelta(hours=3)).strftime('%Y-%m-%d'),
              (ini + __import__('datetime').timedelta(hours=3)).strftime('%Y-%m-%d')}:
        for f in _lista_fotmob(d):
            dt_ = abs((f['ini'] - ini).total_seconds())
            if dt_ > 3 * 3600:
                continue
            sh = cm._sim_club(pj._sin_femenino(home), pj._sin_femenino(f['home']))
            sa = cm._sim_club(pj._sin_femenino(away), pj._sin_femenino(f['away']))
            # la categoría (U19, U21, W) tiene que coincidir
            import mercado_sin_modelo as msm
            if msm._categoria(home) != msm._categoria(f['home'] or '') or \
                    msm._categoria(away) != msm._categoria(f['away'] or ''):
                continue
            s = min(sh, sa) if dt_ <= 1200 else (min(sh, sa) if min(sh, sa) >= .85 else 0)
            if s > ms:
                mejor, ms = f, s
    return mejor if ms >= 0.6 else None


def _indice_equipos() -> Dict:
    """nombre normalizado -> [(id, nombre, categoría, n, última liga)] de los
    equipos que jugaron en los últimos 200 días."""
    if 'idx' in _MEM:
        return _MEM['idx']
    import mercado_sin_modelo as msm
    import partidos_jugados as pj
    import resultados_fotmob as rf
    df = rf.cargar()
    rec = df[df['ini'] >= df['ini'].max() - __import__('pandas').Timedelta(days=400)]
    info: Dict = {}
    for r in rec.itertuples(index=False):
        for eid, nom in ((r.home_id, r.home), (r.away_id, r.away)):
            e = info.setdefault(eid, [nom, 0, r.liga_id])
            e[0], e[1], e[2] = nom, e[1] + 1, r.liga_id
    idx: Dict = {}
    for eid, (nom, n, liga) in info.items():
        base = pj._sin_femenino(str(nom))
        ent = (eid, str(nom), msm._categoria(str(nom)), n, liga)
        for tok in set(msm._norm(base).replace('-', ' ').split()):
            if len(tok) >= 3:
                idx.setdefault(tok, []).append(ent)
    _MEM['idx'] = idx
    return idx


def buscar_equipo(nombre: str) -> Optional[tuple]:
    """El equipo de la base con ese nombre (misma categoría: U21, U20, W…).
    Pide parecido alto (≥ 0,85): un equipo equivocado es peor que ninguno."""
    import cuotas_multi as cm
    import mercado_sin_modelo as msm
    import partidos_jugados as pj
    cat = msm._categoria(nombre)
    limpio = msm._norm(pj._sin_femenino(str(nombre)))
    import re as _re
    limpio = _re.sub(r'\bu[- ]?\d{2}\b', '', limpio, flags=_re.I).strip()
    idx = _indice_equipos()
    cands = []
    vistos = set()
    toks = [t for t in msm._norm(limpio).replace('-', ' ').split() if len(t) >= 3]
    for lista in [idx.get(t, []) for t in toks]:
        for eid, nom, c, n, liga in lista:
            if eid in vistos:
                continue
            vistos.add(eid)
            if c != cat:
                continue
            nb = _re.sub(r'\bu[- ]?\d{2}\b', '', pj._sin_femenino(nom),
                         flags=_re.I).strip()
            if msm._norm(nb) == msm._norm(limpio):
                s = 1.0
            else:
                s = cm._sim_club(limpio, nb)
            if s >= 0.85:
                cands.append((s, n, eid, nom, liga))
    if not cands:
        return None
    cands.sort(key=lambda x: (-x[0], -x[1]))
    return cands[0]


def motor_flashscore() -> Optional[Motor]:
    """v316 — el mismo modelo sobre la base de Flashscore
    (`resultados_flashscore`), que cubre TODAS las competiciones del tablero
    con los nombres exactos del tablero: reservas, sub-20, femenil, amateur."""
    if 'mfs' in _MEM:
        return _MEM['mfs']
    try:
        import pandas as pd
        import resultados_flashscore as rf
        df = rf.cargar()
        if not len(df):
            _MEM['mfs'] = None
            return None
        x = pd.DataFrame({
            'match_id': df['match_id'], 'ini': df['ini'], 'liga_id': df['ruta'],
            'home_id': [rf.clave_equipo(r, h) for r, h in zip(df['ruta'], df['home'])],
            'away_id': [rf.clave_equipo(r, a) for r, a in zip(df['ruta'], df['away'])],
            'home': df['home'], 'away': df['away'], 'gh': df['gh'], 'ga': df['ga']})
        m, _ = entrenar(x)
        _MEM['mfs'] = m
        logger.info('[modelo_comp] Flashscore: %d partidos, %d equipos, %d '
                    'competiciones', len(x), len(m.n), x['liga_id'].nunique())
        return m
    except Exception as e:
        logger.warning('[modelo_comp] Flashscore: %s', e)
        _MEM['mfs'] = None
        return None


def predecir_flashscore(home: str, away: str, liga: str) -> Optional[Dict]:
    """Con la base de Flashscore: la competición por su nombre del tablero y
    los equipos por su nombre exacto. None si la competición no está."""
    import json
    import resultados_flashscore as rf
    m = motor_flashscore()
    if m is None or not liga:
        return None
    try:
        rutas = json.load(open(rf.RUTAS, encoding='utf-8'))
    except Exception:
        rutas = {}
    ruta = rutas.get(liga)
    if not ruta:
        return None
    kh, ka = rf.clave_equipo(ruta, home), rf.clave_equipo(ruta, away)
    nh, na = m.partidos(kh), m.partidos(ka)
    if min(nh, na) < MIN_PARTIDOS:
        return {'sin_historia': True, 'n': (nh, na), 'fuente': 'flashscore'}
    lh, la = m.lambdas(ruta, kh, ka)
    return {'lambdas': (round(lh, 3), round(la, 3)), 'n': (nh, na),
            'fuente': 'flashscore', 'fotmob': None,
            'p': probabilidades(lh, la)}


def predecir(home: str, away: str, inicio, liga: str = None) -> Optional[Dict]:
    """v316 — primero la base de Flashscore (nombres exactos del tablero);
    si la competición no está, la de FotMob."""
    if liga:
        r = predecir_flashscore(home, away, liga)
        if r and r.get('p'):
            return r
    return predecir_fotmob(home, away, inicio)


def predecir_fotmob(home: str, away: str, inicio) -> Optional[Dict]:
    """Probabilidades del modelo propio para un partido del tablero, o None
    si FotMob no lo lista o algún equipo tiene poca historia."""
    m = motor_actual()
    if m is None:
        return None
    eh, ea = buscar_equipo(home), buscar_equipo(away)
    if not (eh and ea) or eh[2] == ea[2]:
        return None
    f = {'home_id': eh[2], 'away_id': ea[2], 'home': eh[3], 'away': ea[3],
         'liga_id': eh[4], 'match_id': None, 'liga': None}
    nh, na = m.partidos(f['home_id']), m.partidos(f['away_id'])
    if min(nh, na) < MIN_PARTIDOS:
        return {'sin_historia': True, 'fotmob': f, 'n': (nh, na)}
    lh, la = m.lambdas(f['liga_id'], f['home_id'], f['away_id'])
    return {'lambdas': (round(lh, 3), round(la, 3)), 'n': (nh, na),
            'fotmob': {k: f[k] for k in ('match_id', 'liga_id', 'liga',
                                         'home_id', 'away_id')},
            'p': probabilidades(lh, la)}
