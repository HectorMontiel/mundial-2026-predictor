# -*- coding: utf-8 -*-
"""
v316 — LOS CÓRNERS DE CADA EQUIPO, CON LA TABLA.

El usuario: «¿córners? … para eso también ayuda la tabla, la clasificación,
ver la diferencia de goles, cuánto anotó, y analizar el patrón, no sólo en
esa liga sino en todas».

LO QUE SE MIDIÓ (`_v316_tabla_mercados.py`, 67 ligas con córners reales,
juicio = el 30 % más reciente, 47.450 partidos, bootstrap 2.000)
Con sólo los córners de cada equipo (a favor y en contra, casa y fuera, media
exponencial) contra eso MÁS la tabla de goles de la temporada (diferencia de
goles, a favor/en contra por partido, posición, zonas, puntos por partido):

                          log-loss        mejora    p5       ofrecidas 70 % (acierto)
    local más de 4,5   0,67614→0,67086   +0,00528  +0,00451  2.603 (73,4 %) → 3.579 (74,1 %)
    visita más de 3,5  0,66437→0,65930   +0,00507  +0,00425  4.367 (73,1 %) → 6.577 (73,2 %)
    total más de 9,5   0,68886→0,68828   +0,00058  +0,00022

En los de cada EQUIPO la tabla pesa diez veces más que en el total: quién es
el fuerte decide quién pisa el área rival y saca los córners, y eso la forma
de córners sola no lo ve (un equipo que viene de jugar con los grandes saca
pocos córners aunque sea bueno). En el TOTAL casi no mueve nada, que es lo
mismo que ya estaba medido (§10.7: el total real apenas depende de quién
juega), así que el total sigue siendo la media de la competición.

QUÉ HACE
Dos regresiones LightGBM de Poisson (córners del local y del visitante) con
esos rasgos, entrenadas con el histórico de todas las ligas con córners
reales. `rendimiento_equipos.corners_equipo` usa estas λ en lugar del
estimador ataque/defensa SÓLO si `corners_tabla.json` dice que ganaron a
producción en `_v316_corners_tabla.py` (con las predicciones reales de
producción, fuera de muestra).

Uso: python corners_tabla.py      (entrena y escribe corners_tabla.json)
"""
from __future__ import annotations

import glob
import json
import logging
import os
import time
from collections import defaultdict, deque
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)

FICHERO = 'corners_tabla.json'
FUERA = {'partidos', 'leagues_cup', 'estadisticas_avanzadas'}          # agregados, no una liga
CORNERS = ['ck_f_h', 'ck_c_h', 'ck_f_a', 'ck_c_a', 'ck_casa_f_h',
           'ck_casa_c_h', 'ck_fuera_f_a', 'ck_fuera_c_a', 'ck_ew_f_h',
           'ck_ew_c_h', 'ck_ew_f_a', 'ck_ew_c_a', 'liga_ck_h', 'liga_ck_a']
GOLES = ['ppg_h', 'ppg_a', 'gf_h', 'gc_h', 'gf_a', 'gc_a', 'pct_h', 'pct_a']
PARAMS = dict(objective='poisson', learning_rate=0.03, num_leaves=15,
              min_data_in_leaf=200, feature_fraction=0.8,
              bagging_fraction=0.8, bagging_freq=1, lambda_l2=5.0,
              verbose=-1, seed=316)
RONDAS = 400


def rasgos_modelo():
    import patrones_liga as pl
    return CORNERS + GOLES + pl.RASGOS_TABLA + pl.RASGOS_TEMPORADA + ['liga_cod']


class Estado:
    """Córners y tabla de una liga partido a partido. `rasgos` lee ANTES de
    `sumar`: no hay fuga."""

    def __init__(self, copa: bool = False):
        import patrones_liga as pl
        self.t = pl.Tabla(copa=copa)
        self.f8 = defaultdict(lambda: deque(maxlen=8))
        self.c8 = defaultdict(lambda: deque(maxlen=8))
        self.cf = defaultdict(lambda: deque(maxlen=5))
        self.cc = defaultdict(lambda: deque(maxlen=5))
        self.ff = defaultdict(lambda: deque(maxlen=5))
        self.fc = defaultdict(lambda: deque(maxlen=5))
        self.ewf, self.ewc = {}, {}
        self.lh, self.la = deque(maxlen=300), deque(maxlen=300)

    def listo(self, h, a) -> bool:
        return len(self.lh) >= 50 and len(self.f8[h]) >= 3 and len(self.f8[a]) >= 3

    def rasgos(self, h, a, d) -> Dict:
        import numpy as np
        m = lambda q: float(np.mean(q)) if len(q) >= 3 else float('nan')
        nan = float('nan')
        f = self.t.rasgos(h, a, d)
        f.update({'ck_f_h': m(self.f8[h]), 'ck_c_h': m(self.c8[h]),
                  'ck_f_a': m(self.f8[a]), 'ck_c_a': m(self.c8[a]),
                  'ck_casa_f_h': m(self.cf[h]), 'ck_casa_c_h': m(self.cc[h]),
                  'ck_fuera_f_a': m(self.ff[a]), 'ck_fuera_c_a': m(self.fc[a]),
                  'ck_ew_f_h': self.ewf.get(h, nan), 'ck_ew_c_h': self.ewc.get(h, nan),
                  'ck_ew_f_a': self.ewf.get(a, nan), 'ck_ew_c_a': self.ewc.get(a, nan),
                  'liga_ck_h': float(np.mean(self.lh)) if self.lh else nan,
                  'liga_ck_a': float(np.mean(self.la)) if self.la else nan})
        return f

    def sumar(self, h, a, d, hg, ag, ch, ca) -> None:
        self.t.sumar(h, a, d, hg, ag)
        if ch != ch or ca != ca or ch is None or ca is None:
            return
        for eq, x, y, fq, cq in ((h, ch, ca, self.cf, self.cc),
                                 (a, ca, ch, self.ff, self.fc)):
            self.f8[eq].append(x)
            self.c8[eq].append(y)
            fq[eq].append(x)
            cq[eq].append(y)
            self.ewf[eq] = x if eq not in self.ewf else .25 * x + .75 * self.ewf[eq]
            self.ewc[eq] = y if eq not in self.ewc else .25 * y + .75 * self.ewc[eq]
        self.lh.append(ch)
        self.la.append(ca)


def _historico(liga: str):
    import pandas as pd
    ruta = 'historico_%s.csv' % liga
    if not os.path.exists(ruta):
        return pd.DataFrame()
    d = pd.read_csv(ruta, low_memory=False, usecols=lambda c: c in (
        'date', 'home_team', 'away_team', 'home_goals', 'away_goals',
        'home_corners', 'away_corners'))
    if 'home_corners' not in d.columns:
        return pd.DataFrame()
    d['date'] = pd.to_datetime(d['date'], errors='coerce')
    return d.dropna(subset=['date', 'home_team', 'away_team', 'home_goals',
                            'away_goals']).sort_values('date').reset_index(drop=True)


def recorrer(liga: str, hasta=None, registrar: bool = True):
    """(estado al final, filas con rasgos y córners reales de cada partido)."""
    import pandas as pd
    import patrones_liga as pl
    d = _historico(liga)
    e = Estado(copa=liga in pl.COPAS)
    filas = []
    if d.empty:
        return e, pd.DataFrame()
    if hasta is not None:
        d = d[d['date'] < hasta]
    for r in d.itertuples(index=False):
        h, a = r.home_team, r.away_team
        ch, ca = r.home_corners, r.away_corners
        if registrar and ch == ch and ca == ca and e.listo(h, a):
            f = e.rasgos(h, a, r.date)
            f.update({'fecha': r.date, 'home': h, 'away': a, 'ch': ch, 'ca': ca})
            filas.append(f)
        e.sumar(h, a, r.date, float(r.home_goals), float(r.away_goals), ch, ca)
    x = pd.DataFrame(filas)
    if len(x):
        x['liga'] = liga
    return e, x


def ligas():
    return sorted(r[len('historico_'):-4] for r in glob.glob('historico_*.csv')
                  if r[len('historico_'):-4] not in FUERA)


def conjunto():
    import pandas as pd
    partes = []
    for liga in ligas():
        try:
            _, x = recorrer(liga)
        except Exception as e:
            logger.warning('[corners_tabla] %s: %s', liga, e)
            continue
        if len(x) >= 250:
            partes.append(x)
    return pd.concat(partes, ignore_index=True).sort_values('fecha').reset_index(drop=True)


def _X(d, codigos, rasgos):
    x = d[[c for c in rasgos if c != 'liga_cod']].astype(float).copy()
    x['liga_cod'] = d['liga'].map(codigos).fillna(-1).astype(int)
    return x[rasgos]


def ajustar_modelos(df, codigos, rasgos):
    import lightgbm as lgb
    out = {}
    for lado, col in (('local', 'ch'), ('visita', 'ca')):
        out[lado] = lgb.train(PARAMS, lgb.Dataset(
            _X(df, codigos, rasgos), label=df[col].astype(float),
            categorical_feature=['liga_cod']), num_boost_round=RONDAS)
    return out


def entrenar(guardar: bool = True, medicion: Optional[Dict] = None) -> Dict:
    """Entrena con TODO el histórico. `medicion` es lo que midió
    `_v316_corners_tabla.py` contra producción; sin que haya ganado ahí, el
    fichero queda con `activo: False` y producción no cambia."""
    df = conjunto()
    lg = sorted(df['liga'].unique())
    codigos = {l: i for i, l in enumerate(lg)}
    rasgos = rasgos_modelo()
    m = ajustar_modelos(df, codigos, rasgos)
    doc = {'generado': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
           'n': int(len(df)), 'codigos': codigos, 'rasgos': rasgos,
           'medicion': medicion or {},
           'activo': bool((medicion or {}).get('adopta')),
           'modelos': {k: v.model_to_string() for k, v in m.items()}}
    if guardar:
        tmp = FICHERO + '.nuevo'
        with open(tmp, 'w', encoding='utf-8', newline='\n') as f:
            json.dump(doc, f, ensure_ascii=False)
        os.replace(tmp, FICHERO)
        olvidar()
    return doc


# ---------------------------------------------------------------- en vivo
_DOC: Dict = {}
_BST: Dict = {}
_EST: Dict = {}


def olvidar() -> None:
    _DOC.clear()
    _BST.clear()
    _EST.clear()


def cargar() -> Dict:
    if not _DOC:
        try:
            if os.path.exists(FICHERO):
                with open(FICHERO, encoding='utf-8') as f:
                    _DOC.update(json.load(f) or {})
        except Exception as e:
            logger.warning('[corners_tabla] no se pudo leer %s: %s', FICHERO, e)
    return _DOC


def lambdas(clave: str, home: str, away: str, fecha=None) -> Optional[Tuple[float, float]]:
    """(λ local, λ visitante) de córners, o None si no está activo, la liga
    no se entrenó o alguno de los dos no tiene tres partidos con córners.
    Nunca lanza."""
    try:
        import lightgbm as lgb
        import pandas as pd
        doc = cargar()
        if not doc.get('activo') or clave not in (doc.get('codigos') or {}):
            return None
        if clave not in _EST:
            _EST[clave] = recorrer(clave, registrar=False)[0]
        e = _EST[clave]
        if not e.listo(home, away):
            return None
        d = pd.Timestamp(fecha) if fecha is not None else pd.Timestamp.now()
        f = pd.DataFrame([e.rasgos(home, away, d)])
        f['liga'] = clave
        x = _X(f, doc['codigos'], doc['rasgos'])
        out = []
        for lado in ('local', 'visita'):
            if lado not in _BST:
                _BST[lado] = lgb.Booster(model_str=doc['modelos'][lado])
            out.append(float(_BST[lado].predict(x)[0]))
        if not all(0.3 < v < 20 for v in out):
            return None
        return round(out[0], 3), round(out[1], 3)
    except Exception as ex:
        logger.debug('[corners_tabla] %s %s-%s: %s', clave, home, away, ex)
        return None


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    try:
        med = json.load(open('_v316_corners_tabla.json', encoding='utf-8'))
    except Exception:
        med = None
    d = entrenar(medicion=med)
    print('n', d['n'], 'activo', d['activo'])
