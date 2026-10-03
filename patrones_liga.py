# -*- coding: utf-8 -*-
"""
v302 — EL MODELO QUE APRENDE EL CARÁCTER DE CADA LIGA.

LO QUE PIDIÓ EL USUARIO
    «Sigo sin ver que haya análisis de patrones de ligas, como entender que en
     el fútbol femenil Liga MX los equipos top de tabla normalmente golean y
     los de media y baja tabla por lo regular no anotan muchos goles. Cosas así
     pero en todas las ligas... Si es posible crea un modelo de IA que aprenda
     de cada una de las ligas... que nos permita tener cada vez mayor precisión
     y entienda las tendencias de qué puede fallar en cada partido.»

LO QUE SE MIDIÓ (`_v302_patrones_liga.py`, 80.736 partidos de 61 ligas con
la predicción de goles FUERA DE MUESTRA de `pick_ledger_totales.csv`)

1. EL PATRÓN EXISTE Y EL MODELO NO LO RECOGÍA. El tercio de la tabla de cada
   equipo —calculado sólo con partidos anteriores— deja un residuo
   sistemático: el modelo se queda CORTO con los de arriba y se PASA con los
   de abajo. Algunas casillas (goles reales contra esperados):

       Bundesliga   local de arriba       2,18 contra 1,85   (+0,33)
       Grecia       local de arriba       1,87 contra 1,55   (+0,33)
       Premier      local de arriba       1,94 contra 1,70   (+0,24)
       Liga MX      local de arriba       1,88 contra 1,64   (+0,24)
       Premier      visitante de abajo    1,03 contra 1,21   (-0,18)
       Serie A      visitante de abajo    0,97 contra 1,14   (-0,17)
       Liga MX      visitante de abajo    1,06 contra 1,21   (-0,15)

   Es exactamente lo que el usuario describió: los fuertes golean más de lo
   que el modelo cree y los flojos anotan menos. El modelo encoge demasiado
   hacia la media.

2. UN MODELO SUPERVISADO LO CORRIGE, Y LO HACE EN LO QUE NO VIO. LightGBM
   con la liga como categoría, la predicción actual (en logit) y los rasgos
   de tabla y de forma de los dos equipos. Entrenado en el 70 % antiguo y
   juzgado en el 30 % reciente (desde 2025-05-08, 24.231 partidos), contra
   la línea base JUSTA —el modelo actual calibrado liga por liga, que es lo
   que ya hacen los calibradores—:

       mercado              log-loss calibrado -> aprendido    mejora (p5)
       más de 2,5           0,68225 -> 0,68029            +0,00196 (+0,00088)
       marca el local       0,52115 -> 0,51482            +0,00633 (+0,00482)
       marca el visitante   0,61234 -> 0,60669            +0,00565 (+0,00430)
       ambos marcan         0,68722 -> 0,68661            +0,00061 (-0,00028)

   Los tres primeros mejoran con el p5 del bootstrap POSITIVO. Ambos marcan
   no: su mejora es la calibración que `calibrador_btts` ya hace, así que ése
   NO se toca aquí.

LO QUE NO PROMETE
Mejor predicción no es ganarle al precio. Elegir apuestas por la media de
goles está medido en -10 % (v296): el mercado ya se sabe la media. Esto hace
más certeros los porcentajes que la pantalla enseña y que la Escalera usa para
ordenar; no convierte un «más de 2,5» en una ventaja medida.

CÓMO SIGUE APRENDIENDO
`python patrones_liga.py --entrenar` reconstruye el conjunto con el ledger y
los históricos que haya ese día, vuelve a medir contra el 30 % reciente y SÓLO
guarda los mercados que siguen ganando a la línea base con p5 positivo. Corre
cada semana en `recalibrar.yml`, detrás del ledger. Una liga nueva entra sola
en cuanto tiene histórico; un mercado que deje de ganar se apaga solo.
"""
from __future__ import annotations

import json
import logging
import math
import os
import sys
import time
from collections import defaultdict, deque
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

FICHERO = 'patrones_liga.json'
VENTANA_PPG = 15
VENTANA_GOLES = 10
ACTIVO_DIAS = 120
MIN_PARTIDOS = 5
RASGOS_V1 = ['lam_h', 'lam_a', 'pct_h', 'pct_a', 'ppg_h', 'ppg_a', 'gf_h',
             'gc_h', 'gf_a', 'gc_a', 'liga_goles', 'liga_cod', 'logit_modelo']
# v306 — LA FORMA RECIENTE, QUE ES LO QUE EL USUARIO PIDIÓ.
#
#   «que te vayas por la media y las probabilidades de acuerdo a las
#    tendencias de los equipos: si en el anterior partido estuvo goleando
#    le vas aumentando un poquito, y si ves que el equipo no es fuerte, con
#    mayor razón»
#
# Los rasgos de la v302 eran medias de 10-15 partidos: sabían quién es
# fuerte, no quién VIENE fuerte. Estos añaden:
#   · los 5 últimos (a favor y en contra) y el último partido;
#   · la media exponencial (pesa más lo reciente, alfa 0,35);
#   · lo de CASA del local y lo de FUERA del visitante, por separado;
#   · el ataque AJUSTADO AL RIVAL: goles marcados menos lo que ese rival solía
#     encajar. Meterle tres al líder no es meterle tres al colista.
#   · la diferencia de puntos por partido entre los dos (el desequilibrio).
RASGOS_NUEVOS = ['gf5_h', 'gc5_h', 'gf5_a', 'gc5_a', 'ult_gf_h', 'ult_gf_a',
                 'ew_gf_h', 'ew_gc_h', 'ew_gf_a', 'ew_gc_a',
                 'casa_gf_h', 'casa_gc_h', 'fuera_gf_a', 'fuera_gc_a',
                 'adj_h', 'adj_a', 'dif_ppg']
RASGOS = RASGOS_V1[:-2] + RASGOS_NUEVOS + ['liga_cod', 'logit_modelo']
# v316 — LO QUE PROPUSO EL USUARIO: «puntos a la zona de playoffs o descenso,
# y si el partido es decisivo para ambos», y «el % de partidos con 4 o más
# goles». Se calculan con la tabla de la TEMPORADA (una temporada nueva
# empieza cuando la liga para más de 35 días): zona de arriba = el 25 % de
# la tabla, descenso = el 15 % de abajo. Medido en `_v316_patrones_extra.py`
# contra los rasgos de siempre (juicio 24.310 partidos, bootstrap 2.000):
#     más de 1,5 ....  no añaden (p5 −0,00044)
#     más de 2,5 ....  no añaden (p5 −0,00088)
#     más de 3,5 ....  SÍ: log-loss 0,58751 → 0,58659, p5 +0,00021
# O sea, ayudan justo en la cola (4+ goles). `entrenar` los prueba en cada
# mercado y sólo los deja donde ganan con p5 > 0.
RASGOS_TEMPORADA = ['p4_h', 'p4_a', 'gap_top_h', 'gap_bot_h', 'gap_top_a',
                    'gap_bot_a', 'prog', 'decisivo_ambos', 'nada_en_juego']
RASGOS_V3 = RASGOS_V1[:-2] + RASGOS_TEMPORADA + ['liga_cod', 'logit_modelo']
# v316 — LO QUE PREGUNTÓ EL USUARIO DESPUÉS: «¿por qué no se mide también la
# probabilidad de gol de cada equipo? … la tabla, la clasificación, la
# diferencia de goles, cuánto anotó». La tabla de la TEMPORADA de cada uno:
# diferencia de goles, a favor y en contra por partido y posición (0 = último,
# 1 = líder). Medido en `_v316_tabla_mercados.py` (61 ligas, juicio 24.310
# partidos, bootstrap 2.000), contra los rasgos de siempre:
#     marca el local .......... +0,00063  p5 −0,00013  no
#     marca el visitante ...... +0,00077  p5 +0,00006  sí (justo)
#     el local mete 2+ ........ +0,00200  p5 +0,00113  sí
#     el visitante mete 2+ .... +0,00099  p5 +0,00030  sí
# `entrenar` lo vuelve a probar en cada mercado y sólo lo deja donde gana.
RASGOS_TABLA = ['gdpj_h', 'gdpj_a', 'gfpj_h', 'gcpj_h', 'gfpj_a', 'gcpj_a',
                'pos_h', 'pos_a']
RASGOS_V4 = (RASGOS_V1[:-2] + RASGOS_TABLA + RASGOS_TEMPORADA
             + ['liga_cod', 'logit_modelo'])
COPAS = {'champions', 'europa_league', 'conference_league', 'libertadores',
         'sudamericana', 'leagues_cup', 'afc_champions'}
PAUSA_TEMPORADA = 35
EW_ALFA = 0.35
# objetivo: (columna real, columna de la predicción actual)
OBJETIVOS = {'mas25': ('over_2.5_real', 'p_over_2.5'),
             # v316 — la línea que la aplicación más mete. Medido: la
             # corrección de siempre le gana a la calibración (log-loss
             # 0,55916 → 0,55687, p5 +0,00127).
             'mas15': ('over_1.5_real', 'p_over_1.5'),
             'marca_local': ('marca_h', 'p_marca_h'),
             'marca_visitante': ('marca_v', 'p_marca_v'),
             'btts': ('btts_real', 'p_btts'),
             # v306 — lo que el usuario jugó con Lyon: que UN equipo meta dos
             # o más. Y el total alto, que es donde un desequilibrio se nota.
             'local_mas15': ('local_2', 'p_local_2'),
             'visit_mas15': ('visit_2', 'p_visit_2'),
             'mas35': ('over_3.5_real', 'p_over_3.5')}
PARAMS = dict(objective='binary', learning_rate=0.03, num_leaves=15,
              min_data_in_leaf=200, feature_fraction=0.8,
              bagging_fraction=0.8, bagging_freq=1, lambda_l2=5.0,
              verbose=-1, seed=302)
RONDAS = 400
# Un corrector no puede mover una probabilidad sin límite: si la liga o los
# rasgos vienen raros, mejor quedarse cerca del modelo que inventar.
MAX_DESPLAZAMIENTO_LOGIT = 1.0


# ---------------------------------------------------------------------------
# rasgos de tabla, sin fuga
# ---------------------------------------------------------------------------
def _historico(liga: str):
    import pandas as pd
    ruta = 'historico_%s.csv' % liga
    if not os.path.exists(ruta):
        return pd.DataFrame()
    try:
        df = pd.read_csv(ruta, low_memory=False,
                         usecols=lambda c: c in ('date', 'home_team',
                                                 'away_team', 'home_goals',
                                                 'away_goals', 'MATCH_ID'))
    except Exception as e:
        logger.debug('[patrones] %s: %s', ruta, e)
        return pd.DataFrame()
    df = df.dropna(subset=['date', 'home_team', 'away_team', 'home_goals',
                           'away_goals'])
    df['date'] = pd.to_datetime(df['date'], errors='coerce')
    return df.dropna(subset=['date']).sort_values('date').reset_index(drop=True)


class Tabla:
    """El estado de una liga partido a partido. `rasgos()` lee ANTES de
    `sumar()`, que es lo que garantiza que no hay fuga."""

    def __init__(self, copa: bool = False):
        # v316 — la tabla de la TEMPORADA (ver RASGOS_TEMPORADA)
        self.copa = copa
        self.temp = {}
        self.temp_fecha = None
        self.temp_n_prev = None
        self.pts = defaultdict(lambda: deque(maxlen=VENTANA_PPG))
        self.gf = defaultdict(lambda: deque(maxlen=VENTANA_GOLES))
        self.gc = defaultdict(lambda: deque(maxlen=VENTANA_GOLES))
        self.ultimo = {}
        self.goles = deque(maxlen=400)
        # v306 — la forma reciente
        self.casa_gf = defaultdict(lambda: deque(maxlen=5))
        self.casa_gc = defaultdict(lambda: deque(maxlen=5))
        self.fuera_gf = defaultdict(lambda: deque(maxlen=5))
        self.fuera_gc = defaultdict(lambda: deque(maxlen=5))
        self.ew_gf = {}
        self.ew_gc = {}
        self.adj = defaultdict(lambda: deque(maxlen=VENTANA_GOLES))

    def rasgos(self, h, a, d) -> Dict:
        import numpy as np
        activos = [t for t, f in self.ultimo.items()
                   if (d - f).days <= ACTIVO_DIAS
                   and len(self.pts[t]) >= MIN_PARTIDOS]
        ppg = {t: float(np.mean(self.pts[t])) for t in activos}
        orden = sorted(ppg.values())

        def pct(t):
            if t not in ppg or len(orden) < 6:
                return float('nan')
            return float(np.searchsorted(orden, ppg[t], side='right')) / len(orden)

        def m(dq):
            return float(np.mean(dq)) if len(dq) >= 3 else float('nan')

        def ult(dq, k=5):
            s = list(dq)[-k:]
            return float(np.mean(s)) if len(s) >= 3 else float('nan')

        def uno(dq):
            return float(dq[-1]) if len(dq) else float('nan')
        nan = float('nan')
        ph, pa = ppg.get(h, nan), ppg.get(a, nan)
        tmp = self._temporada(h, a, d)
        return {**tmp, 'pct_h': pct(h), 'pct_a': pct(a),
                'ppg_h': ph, 'ppg_a': pa,
                'gf_h': m(self.gf[h]), 'gc_h': m(self.gc[h]),
                'gf_a': m(self.gf[a]), 'gc_a': m(self.gc[a]),
                'liga_goles': (float(np.mean(self.goles))
                               if len(self.goles) >= 50 else nan),
                'gf5_h': ult(self.gf[h]), 'gc5_h': ult(self.gc[h]),
                'gf5_a': ult(self.gf[a]), 'gc5_a': ult(self.gc[a]),
                'ult_gf_h': uno(self.gf[h]), 'ult_gf_a': uno(self.gf[a]),
                'ew_gf_h': self.ew_gf.get(h, nan),
                'ew_gc_h': self.ew_gc.get(h, nan),
                'ew_gf_a': self.ew_gf.get(a, nan),
                'ew_gc_a': self.ew_gc.get(a, nan),
                'casa_gf_h': m(self.casa_gf[h]),
                'casa_gc_h': m(self.casa_gc[h]),
                'fuera_gf_a': m(self.fuera_gf[a]),
                'fuera_gc_a': m(self.fuera_gc[a]),
                'adj_h': m(self.adj[h]), 'adj_a': m(self.adj[a]),
                'dif_ppg': (ph - pa) if ph == ph and pa == pa else nan}

    def _temporada(self, h, a, d) -> Dict:
        """v316 — puntos a las zonas, avance y % de 4+ goles, con la tabla
        de la temporada ANTES del partido (lo mismo que `_v316_contexto`)."""
        nan = float('nan')
        if self.temp_fecha is not None and (d - self.temp_fecha).days > PAUSA_TEMPORADA:
            self.temp_n_prev = len(self.temp) or self.temp_n_prev
            self.temp = {}
        eh = self.temp.get(h) or {'pts': 0, 'pj': 0, 'gd': 0, 'n4': 0}
        ea = self.temp.get(a) or {'pts': 0, 'pj': 0, 'gd': 0, 'n4': 0}
        # v316 — diferencia de goles, a favor y en contra por partido, y
        # posición en la tabla de la temporada (ver RASGOS_TABLA)
        tabla = sorted(self.temp, key=lambda t: (-self.temp[t]['pts'],
                                                 -self.temp[t]['gd']))
        extra = {}
        for lado, eq, e in (('h', h, eh), ('a', a, ea)):
            if e['pj'] < 3:
                for k in ('gdpj', 'gfpj', 'gcpj', 'pos'):
                    extra['%s_%s' % (k, lado)] = nan
                continue
            extra['gdpj_' + lado] = e['gd'] / e['pj']
            extra['gfpj_' + lado] = e.get('gf', 0) / e['pj']
            extra['gcpj_' + lado] = e.get('gc', 0) / e['pj']
            extra['pos_' + lado] = 1 - tabla.index(eq) / max(1, len(tabla) - 1)
        N = max(len(set(self.temp) | {h, a}), self.temp_n_prev or 0)
        filas = dict(self.temp)
        filas.setdefault(h, eh)
        filas.setdefault(a, ea)
        orden = sorted(filas.values(), key=lambda e: (-e['pts'], -e['gd']))
        pts = [e['pts'] for e in orden]
        k_top, k_bot = max(1, round(0.25 * N)), max(1, round(0.15 * N))
        b_top = pts[min(k_top, len(pts)) - 1]
        b_bot = pts[max(0, len(pts) - k_bot)] if len(pts) >= N - k_bot + 1 else pts[-1]
        prog = ((eh['pj'] + ea['pj']) / 2) / max(1, 2 * (N - 1))
        out = {**extra, 'prog': prog,
               'p4_h': eh['n4'] / eh['pj'] if eh['pj'] >= 3 else nan,
               'p4_a': ea['n4'] / ea['pj'] if ea['pj'] >= 3 else nan}
        if self.copa:
            out.update({k: nan for k in ('gap_top_h', 'gap_bot_h', 'gap_top_a',
                                         'gap_bot_a')})
            out['decisivo_ambos'] = 0.0
            out['nada_en_juego'] = 0.0
            return out
        gt_h, gb_h = eh['pts'] - b_top, eh['pts'] - b_bot
        gt_a, gb_a = ea['pts'] - b_top, ea['pts'] - b_bot
        juega = lambda t, b: abs(t) <= 3 or abs(b) <= 3
        lejos = lambda t, b: abs(t) > 6 and abs(b) > 6
        out.update({'gap_top_h': gt_h, 'gap_bot_h': gb_h,
                    'gap_top_a': gt_a, 'gap_bot_a': gb_a,
                    'decisivo_ambos': float(prog >= 0.5 and juega(gt_h, gb_h)
                                            and juega(gt_a, gb_a)),
                    'nada_en_juego': float(prog >= 0.6 and lejos(gt_h, gb_h)
                                           and lejos(gt_a, gb_a))})
        return out

    def sumar(self, h, a, d, hg, ag) -> None:
        import numpy as np
        # v316 — la tabla de la temporada
        if self.temp_fecha is not None and (d - self.temp_fecha).days > PAUSA_TEMPORADA:
            self.temp_n_prev = len(self.temp) or self.temp_n_prev
            self.temp = {}
        self.temp_fecha = d
        for eq, f_, c_ in ((h, hg, ag), (a, ag, hg)):
            e = self.temp.setdefault(eq, {'pts': 0, 'pj': 0, 'gd': 0, 'n4': 0})
            e['pj'] += 1
            e['gd'] += f_ - c_
            e['n4'] += int(hg + ag >= 4)
            e['gf'] = e.get('gf', 0) + f_
            e['gc'] = e.get('gc', 0) + c_
            e['pts'] += 3 if f_ > c_ else (1 if f_ == c_ else 0)
        # el ataque ajustado se calcula con lo que el RIVAL encajaba ANTES
        gc_rival_h = (float(np.mean(self.gc[a])) if len(self.gc[a]) >= 3
                      else None)
        gc_rival_a = (float(np.mean(self.gc[h])) if len(self.gc[h]) >= 3
                      else None)
        if gc_rival_h is not None:
            self.adj[h].append(hg - gc_rival_h)
        if gc_rival_a is not None:
            self.adj[a].append(ag - gc_rival_a)
        self.casa_gf[h].append(hg); self.casa_gc[h].append(ag)
        self.fuera_gf[a].append(ag); self.fuera_gc[a].append(hg)
        for eq, f_, c_ in ((h, hg, ag), (a, ag, hg)):
            self.ew_gf[eq] = (f_ if eq not in self.ew_gf else
                              EW_ALFA * f_ + (1 - EW_ALFA) * self.ew_gf[eq])
            self.ew_gc[eq] = (c_ if eq not in self.ew_gc else
                              EW_ALFA * c_ + (1 - EW_ALFA) * self.ew_gc[eq])
        self.pts[h].append(3 if hg > ag else (1 if hg == ag else 0))
        self.pts[a].append(3 if ag > hg else (1 if hg == ag else 0))
        self.gf[h].append(hg); self.gc[h].append(ag)
        self.gf[a].append(ag); self.gc[a].append(hg)
        self.ultimo[h] = self.ultimo[a] = d
        self.goles.append(hg + ag)


def tercio(p) -> Optional[str]:
    if p is None or p != p:
        return None
    return 'arriba' if p > 2 / 3 else ('abajo' if p <= 1 / 3 else 'medio')


# ---------------------------------------------------------------------------
# entrenamiento
# ---------------------------------------------------------------------------
def conjunto():
    """El ledger de goles con los rasgos de tabla de cada partido."""
    import numpy as np
    import pandas as pd
    led = pd.read_csv('pick_ledger_totales.csv', low_memory=False)
    led = led[led['liga'] != 'liga']
    partes = []
    for liga in sorted(led['liga'].unique()):
        h = _historico(liga)
        if h.empty or 'MATCH_ID' not in h.columns:
            continue
        t = Tabla(copa=liga in COPAS)
        filas = []
        for r in h.itertuples(index=False):
            f = t.rasgos(r.home_team, r.away_team, r.date)
            f['MATCH_ID'] = r.MATCH_ID
            filas.append(f)
            t.sumar(r.home_team, r.away_team, r.date, float(r.home_goals),
                    float(r.away_goals))
        p = pd.DataFrame(filas)
        p['liga'] = liga
        partes.append(p)
    ras = pd.concat(partes, ignore_index=True)
    df = led.merge(ras, left_on=['liga', 'match_id'],
                   right_on=['liga', 'MATCH_ID'], how='inner')
    df['fecha'] = pd.to_datetime(df['fecha'], errors='coerce')
    df = df.dropna(subset=['fecha', 'lam_h', 'lam_a']).sort_values('fecha')
    df['marca_h'] = (df['goles_local'] >= 1).astype(int)
    df['marca_v'] = (df['goles_visit'] >= 1).astype(int)
    df['p_marca_h'] = 1 - np.exp(-df['lam_h'])
    df['p_marca_v'] = 1 - np.exp(-df['lam_a'])
    # v306 — un equipo mete dos o más
    df['local_2'] = (df['goles_local'] >= 2).astype(int)
    df['visit_2'] = (df['goles_visit'] >= 2).astype(int)
    df['p_local_2'] = 1 - np.exp(-df['lam_h']) * (1 + df['lam_h'])
    df['p_visit_2'] = 1 - np.exp(-df['lam_a']) * (1 + df['lam_a'])
    df['t_h'] = df['pct_h'].map(tercio)
    df['t_a'] = df['pct_a'].map(tercio)
    return df.reset_index(drop=True)


def _logit(p):
    import numpy as np
    p = np.clip(np.asarray(p, dtype=float), 1e-3, 1 - 1e-3)
    return np.log(p / (1 - p))


def _X(d, p_col, codigos, rasgos=None):
    rasgos = rasgos or RASGOS
    x = d[[c for c in rasgos if c not in ('liga_cod', 'logit_modelo')]].copy()
    x['liga_cod'] = d['liga'].map(codigos).fillna(-1).astype(int)
    x['logit_modelo'] = _logit(d[p_col])
    return x[rasgos]


def _ll(y, p):
    import numpy as np
    p = np.clip(p, 1e-4, 1 - 1e-4)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


def _base_calibrada(e, j, y_col, p_col):
    """El modelo actual calibrado liga por liga: la línea base justa."""
    import numpy as np
    from sklearn.linear_model import LogisticRegression
    le, lj = _logit(e[p_col]), _logit(j[p_col])
    ye = e[y_col].astype(int).to_numpy()
    p = LogisticRegression(C=1.0).fit(le.reshape(-1, 1), ye).predict_proba(
        lj.reshape(-1, 1))[:, 1]
    for liga in j['liga'].unique():
        me = (e['liga'] == liga).to_numpy()
        mj = (j['liga'] == liga).to_numpy()
        if me.sum() >= 150 and 0 < ye[me].mean() < 1:
            p[mj] = LogisticRegression(C=1.0).fit(
                le[me].reshape(-1, 1), ye[me]).predict_proba(
                lj[mj].reshape(-1, 1))[:, 1]
    return p


def patrones(df) -> Dict:
    """La tabla que se enseña: goles reales y del modelo por tercio y liga."""
    out = {}
    for liga, g in df.groupby('liga'):
        filas = {}
        for lado, t, gl, lam in (('local', 't_h', 'goles_local', 'lam_h'),
                                 ('visitante', 't_a', 'goles_visit', 'lam_a')):
            for ter in ('arriba', 'medio', 'abajo'):
                s = g[g[t] == ter]
                if len(s) < 40:
                    continue
                res = (s[gl] - s[lam])
                filas['%s_%s' % (lado, ter)] = {
                    'n': int(len(s)),
                    'goles': round(float(s[gl].mean()), 2),
                    'modelo': round(float(s[lam].mean()), 2),
                    'residuo': round(float(res.mean()), 3),
                    'significativo': bool(abs(res.mean()) >
                                          2 * res.std() / math.sqrt(len(s))),
                    'no_marca': round(float((s[gl] == 0).mean()), 3)}
        if filas:
            out[liga] = filas
    return out


def entrenar(guardar: bool = True) -> Dict:
    """Mide en dos tramos y entrena con todo lo que siga ganando."""
    import lightgbm as lgb
    import numpy as np
    df = conjunto()
    ligas = sorted(df['liga'].unique())
    codigos = {l: i for i, l in enumerate(ligas)}
    corte = df['fecha'].iloc[int(len(df) * 0.70)]
    ele, jui = df[df['fecha'] < corte], df[df['fecha'] >= corte]
    rng = np.random.default_rng(302)
    doc = {'version': 2,
           'generado': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
           'corte_juicio': str(corte.date()), 'n': int(len(df)),
           'n_juicio': int(len(jui)), 'codigos': codigos, 'rasgos': RASGOS,
           'medicion': {}, 'modelos': {}, 'patrones': patrones(df)}
    oos = {}       # v326 — lo que predijo cada corrector en el juicio
    for nombre, (y_col, p_col) in OBJETIVOS.items():
        e = ele.dropna(subset=[y_col, p_col])
        j = jui.dropna(subset=[y_col, p_col])
        bst = lgb.train(PARAMS, lgb.Dataset(
            _X(e, p_col, codigos), label=e[y_col].astype(int),
            categorical_feature=['liga_cod']), num_boost_round=RONDAS)
        y = j[y_col].astype(int).to_numpy()
        p_new = bst.predict(_X(j, p_col, codigos))
        p_cal = _base_calibrada(e, j, y_col, p_col)
        dif = _ll(y, p_cal) - _ll(y, p_new)
        idx = rng.integers(0, len(dif), size=(2000, len(dif)))
        p5 = float(np.percentile(dif[idx].mean(axis=1), 5))
        activo = bool(dif.mean() > 0 and p5 > 0)
        # v306 — ¿la forma reciente AÑADE algo a los rasgos de la v302? Se
        # entrena la versión vieja sobre lo mismo y se compara en el juicio.
        v1 = lgb.train(PARAMS, lgb.Dataset(
            _X(e, p_col, codigos, RASGOS_V1), label=e[y_col].astype(int),
            categorical_feature=['liga_cod']), num_boost_round=RONDAS)
        p_v1 = v1.predict(_X(j, p_col, codigos, RASGOS_V1))
        dif1 = _ll(y, p_v1) - _ll(y, p_new)
        p5_1 = float(np.percentile(dif1[idx].mean(axis=1), 5))
        # LOS RASGOS NUEVOS SÓLO SI LE GANAN A LOS VIEJOS CON p5 > 0. Medido
        # el 2026-09-23: la forma reciente no añade nada en seis de los siete
        # mercados (±0,0005 de log-loss, p5 negativo); sólo en «el local mete
        # dos o más». Donde no gana, se queda el modelo de la v302.
        nuevos = bool(dif1.mean() > 0 and p5_1 > 0)
        if not nuevos:
            dif0 = _ll(y, p_cal) - _ll(y, p_v1)
            p5 = float(np.percentile(dif0[idx].mean(axis=1), 5))
            activo = bool(dif0.mean() > 0 and p5 > 0)
            dif = dif0
        rasgos_ok = RASGOS if nuevos else RASGOS_V1
        # v316 — y los rasgos de la temporada (zonas, 4+ goles), si le ganan
        # al de siempre con p5 > 0 y más que la forma reciente
        v3 = lgb.train(PARAMS, lgb.Dataset(
            _X(e, p_col, codigos, RASGOS_V3), label=e[y_col].astype(int),
            categorical_feature=['liga_cod']), num_boost_round=RONDAS)
        p_v3 = v3.predict(_X(j, p_col, codigos, RASGOS_V3))
        dif3 = _ll(y, p_v1) - _ll(y, p_v3)
        p5_3 = float(np.percentile(dif3[idx].mean(axis=1), 5))
        temporada = bool(dif3.mean() > 0 and p5_3 > 0
                         and (not nuevos or dif3.mean() > dif1.mean()))
        if temporada:
            nuevos = False
            rasgos_ok = RASGOS_V3
            dif_t = _ll(y, p_cal) - _ll(y, p_v3)
            p5 = float(np.percentile(dif_t[idx].mean(axis=1), 5))
            activo = bool(dif_t.mean() > 0 and p5 > 0)
            dif = dif_t
        # v316 — y la tabla de la temporada (diferencia de goles, a favor y
        # en contra por partido, posición), si le gana al de siempre con
        # p5 > 0 y más que lo elegido hasta aquí
        v4 = lgb.train(PARAMS, lgb.Dataset(
            _X(e, p_col, codigos, RASGOS_V4), label=e[y_col].astype(int),
            categorical_feature=['liga_cod']), num_boost_round=RONDAS)
        p_v4 = v4.predict(_X(j, p_col, codigos, RASGOS_V4))
        dif4 = _ll(y, p_v1) - _ll(y, p_v4)
        p5_4 = float(np.percentile(dif4[idx].mean(axis=1), 5))
        mejor = (dif3.mean() if temporada else dif1.mean() if nuevos else 0.0)
        tabla_t = bool(dif4.mean() > 0 and p5_4 > 0 and dif4.mean() > mejor)
        if tabla_t:
            nuevos = temporada = False
            rasgos_ok = RASGOS_V4
            dif_t = _ll(y, p_cal) - _ll(y, p_v4)
            p5 = float(np.percentile(dif_t[idx].mean(axis=1), 5))
            activo = bool(dif_t.mean() > 0 and p5 > 0)
            dif = dif_t
        doc['medicion'][nombre] = {
            'll_base_calibrada': round(float(_ll(y, p_cal).mean()), 5),
            'll_rasgos_v1': round(float(_ll(y, p_v1).mean()), 5),
            'll_rasgos_v2': round(float(_ll(y, p_new).mean()), 5),
            'mejora': round(float(dif.mean()), 5), 'p5': round(p5, 5),
            'mejora_v2_vs_v1': round(float(dif1.mean()), 5),
            'p5_v2_vs_v1': round(p5_1, 5),
            'll_rasgos_v3': round(float(_ll(y, p_v3).mean()), 5),
            'mejora_v3_vs_v1': round(float(dif3.mean()), 5),
            'p5_v3_vs_v1': round(p5_3, 5),
            'll_rasgos_v4': round(float(_ll(y, p_v4).mean()), 5),
            'mejora_v4_vs_v1': round(float(dif4.mean()), 5),
            'p5_v4_vs_v1': round(p5_4, 5),
            'rasgos': ('tabla de la temporada (diferencia de goles, posición)'
                       if tabla_t else
                       'temporada (zonas y 4+ goles)' if temporada else
                       'forma reciente' if nuevos else 'tabla y medias'),
            'activo': activo}
        if activo:
            import pandas as _pd
            oos[nombre] = _pd.Series(
                p_v4 if tabla_t else p_v3 if temporada else
                p_new if nuevos else p_v1, index=j.index)
        logger.info('[patrones] %-16s mejora %+.5f p5 %+.5f (%s) -> %s',
                    nombre, dif.mean(), p5,
                    'v2' if nuevos else 'v1', 'ACTIVO' if activo else 'apagado')
        if activo:
            # validado: se entrena con TODO, que es lo que se usa en vivo
            d = df.dropna(subset=[y_col, p_col])
            final = lgb.train(PARAMS, lgb.Dataset(
                _X(d, p_col, codigos, rasgos_ok), label=d[y_col].astype(int),
                categorical_feature=['liga_cod']), num_boost_round=RONDAS)
            doc['modelos'][nombre] = final.model_to_string()
            doc.setdefault('rasgos_modelo', {})[nombre] = list(rasgos_ok)
    try:
        doc['btts_derivada'] = _btts_derivada(ele, jui, oos, rng)
        logger.info('[patrones] ambos marcan derivado: mejora %+.5f p5 %+.5f -> %s',
                    doc['btts_derivada'].get('mejora', 0),
                    doc['btts_derivada'].get('p5', 0),
                    'ACTIVO' if doc['btts_derivada'].get('activo') else 'apagado')
    except Exception as e:
        logger.warning('[patrones] ambos marcan derivado: %s', e)
    if guardar:
        tmp = FICHERO + '.nuevo'
        with open(tmp, 'w', encoding='utf-8', newline='\n') as f:
            json.dump(doc, f, ensure_ascii=False)
        os.replace(tmp, FICHERO)
        olvidar()
    return doc


# ---------------------------------------------------------------------------
# v326 — AMBOS MARCAN, DERIVADO DE «MARCA EL LOCAL» Y «MARCA EL VISITANTE».
#
# El usuario: «si hay ligas donde hay ambos marcan y los dos equipos en su
# histórico reciente tienen buena cantidad de goles, podríamos poner ambos
# marcan». Medido en `_v326_patrones.py` (80.830 partidos): en esos partidos
# ambos marcan pasa el 60-63 % y el modelo crudo decía 54-55 %; pero el
# corrector directo de «ambos marcan» no le gana al calibrador por liga (p5
# negativo, igual que en la v302). Lo que SÍ funciona es construirlo con los
# dos correctores que ya ganan —«marca el local» y «marca el visitante»—:
# ambos marcan es que marquen los dos.
#
# La mezcla (una logística sobre el producto, las dos marginales y el ambos
# marcan de siempre) se ajusta con la primera mitad del juicio y se juzga en
# la segunda, contra el calibrador por liga. Se activa sólo con p5 > 0, y se
# vuelve a decidir cada semana con `recalibrar.yml`.
# ---------------------------------------------------------------------------
def _z_btts(ph, pa, pb):
    import numpy as np
    ph, pa, pb = (np.clip(np.asarray(x, dtype=float), 1e-3, 1 - 1e-3)
                  for x in (ph, pa, pb))
    return np.column_stack([_logit(ph * pa), _logit(ph), _logit(pa), _logit(pb)])


def _btts_derivada(ele, jui, oos, rng) -> Dict:
    import numpy as np
    from sklearn.linear_model import LogisticRegression
    if 'marca_local' not in oos or 'marca_visitante' not in oos:
        return {'activo': False, 'motivo': 'falta un corrector de «marca»'}
    j = jui.loc[oos['marca_local'].index.intersection(oos['marca_visitante'].index)]
    j = j.dropna(subset=['btts_real', 'p_btts'])
    pb = _base_calibrada(ele.dropna(subset=['btts_real', 'p_btts']), j,
                         'btts_real', 'p_btts')
    Z = _z_btts(oos['marca_local'].loc[j.index], oos['marca_visitante'].loc[j.index], pb)
    y = j['btts_real'].astype(int).to_numpy()
    mitad = len(j) // 2               # el juicio va en orden de fecha
    mez = LogisticRegression(C=10.0, max_iter=2000).fit(Z[:mitad], y[:mitad])
    p2 = mez.predict_proba(Z[mitad:])[:, 1]
    dif = _ll(y[mitad:], pb[mitad:]) - _ll(y[mitad:], p2)
    idx = rng.integers(0, len(dif), size=(2000, len(dif)))
    p5 = float(np.percentile(dif[idx].mean(axis=1), 5))
    activo = bool(dif.mean() > 0 and p5 > 0)
    final = LogisticRegression(C=10.0, max_iter=2000).fit(Z, y)
    tabla = {}
    for nom, pr in (('calibrador', pb[mitad:]), ('derivada', p2)):
        s = pr >= 0.60
        tabla[nom] = {'n': int(s.sum()),
                      'prometido': round(float(pr[s].mean()), 3) if s.any() else None,
                      'real': round(float(y[mitad:][s].mean()), 3) if s.any() else None}
    return {'activo': activo, 'mejora': round(float(dif.mean()), 5),
            'p5': round(p5, 5), 'n_juicio': int(len(dif)),
            'coef': [float(c) for c in final.coef_[0]],
            'intercepto': float(final.intercept_[0]),
            'si_60_o_mas': tabla}


def btts_derivada(ph: float, pa: float, p_btts: float) -> Optional[float]:
    """Ambos marcan con lo aprendido, o None si no está activo. Nunca lanza."""
    try:
        b = (cargar() or {}).get('btts_derivada') or {}
        if not b.get('activo') or not b.get('coef'):
            return None
        z = _z_btts([ph], [pa], [p_btts])[0]
        v = b['intercepto'] + sum(c * x for c, x in zip(b['coef'], z))
        return 1.0 / (1.0 + math.exp(-v))
    except Exception as e:
        logger.debug('[patrones] ambos marcan derivado: %s', e)
        return None


# ---------------------------------------------------------------------------
# uso en vivo
# ---------------------------------------------------------------------------
_DOC: Dict = {}
_BST: Dict = {}
_TABLAS: Dict = {}


def olvidar() -> None:
    _DOC.clear()
    _BST.clear()
    _TABLAS.clear()


def cargar() -> Dict:
    """El fichero entrenado, o {} si no hay. Nunca lanza."""
    if _DOC:
        return _DOC
    try:
        if os.path.exists(FICHERO):
            with open(FICHERO, encoding='utf-8') as f:
                _DOC.update(json.load(f) or {})
    except Exception as e:
        logger.warning('[patrones] no se pudo leer %s: %s', FICHERO, e)
    return _DOC


def _booster(nombre: str):
    if nombre in _BST:
        return _BST[nombre]
    txt = (cargar().get('modelos') or {}).get(nombre)
    b = None
    if txt:
        try:
            import lightgbm as lgb
            b = lgb.Booster(model_str=txt)
        except Exception as e:
            logger.warning('[patrones] modelo %s ilegible: %s', nombre, e)
    _BST[nombre] = b
    return b


def tabla_liga(liga: str) -> Optional[Tabla]:
    """El estado de la liga con TODO su histórico, para el próximo partido."""
    if liga in _TABLAS:
        return _TABLAS[liga]
    t = None
    h = _historico(liga)
    if not h.empty:
        t = Tabla(copa=liga in COPAS)
        for r in h.itertuples(index=False):
            t.sumar(r.home_team, r.away_team, r.date, float(r.home_goals),
                    float(r.away_goals))
    _TABLAS[liga] = t
    return t


def _p(x) -> Optional[float]:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if 0.0 < v < 1.0 else None


def _num(x) -> Optional[float]:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v and v > 0 else None


def _lam_de(p_marca: Optional[float]) -> Optional[float]:
    """La lambda de Poisson que da esa probabilidad de marcar al menos uno."""
    return -math.log(1 - p_marca) if p_marca else None


def _mover(p: float, delta: float) -> float:
    lp = math.log(p / (1 - p)) + delta
    return 1.0 / (1.0 + math.exp(-lp))


def ajustar(pick: Dict, ahora=None) -> bool:
    """Corrige los goles del pronóstico con lo aprendido de su liga.

    Mueve en LOGIT —igual que el entrenamiento— y mueve la escalera ENTERA
    por el mismo desplazamiento que la línea de 2,5, para que la línea de 1,5
    siga siendo más probable que la de 2,5 y ésta más que la de 3,5. Con los
    goles de cada equipo, lo mismo. Devuelve True si tocó algo. NUNCA lanza.
    """
    try:
        import numpy as np
        import pandas as pd
        doc = cargar()
        liga = str(pick.get('clave_liga') or '')
        if not doc or liga not in (doc.get('codigos') or {}):
            return False
        if str(pick.get('deporte') or 'Fútbol') != 'Fútbol':
            return False
        par = str(pick.get('partido') or '')
        if ' vs ' not in par:
            return False
        h, a = par.split(' vs ', 1)
        ge = pick.get('goles_equipo') or {}
        p_h = _p((ge.get('local') or {}).get('0.5'))
        p_a = _p((ge.get('visitante') or {}).get('0.5'))
        gl = pick.get('goles_lineas') or {}
        p25 = _p(gl.get('2.5'))
        if p_h is None or p_a is None or p25 is None:
            return False
        t = tabla_liga(liga)
        if t is None or (h not in t.ultimo and a not in t.ultimo):
            return False
        d = pd.Timestamp(ahora) if ahora is not None else pd.Timestamp.now()
        f = t.rasgos(h, a, d)
        base = dict(f)
        # La lambda de cada equipo que produjo el regresor es EXACTAMENTE la
        # del ledger (`goles_xg`, desde esta versión). Los goles por equipo
        # que se enseñan salen de la matriz de marcador, re-ponderada al 1X2,
        # y no son la misma cantidad: medido sobre los 23 partidos del
        # 2026-09-22, darle la marginal de la matriz movía «marca el local»
        # hasta el tope en dos de ellos. Sin `goles_xg` (un precálculo viejo)
        # se aproxima desde la marginal, que es lo mejor que hay.
        gx = pick.get('goles_xg') or {}
        lam_h = _num(gx.get('local')) or _lam_de(p_h)
        lam_a = _num(gx.get('visitante')) or _lam_de(p_a)
        base['lam_h'], base['lam_a'] = lam_h, lam_a
        base['liga_cod'] = int(doc['codigos'][liga])
        pin_h = 1 - math.exp(-lam_h)
        pin_a = 1 - math.exp(-lam_a)
        # LO QUE ENTRA AL CORRECTOR ES LO QUE VIO AL ENTRENAR. El ledger guarda
        # la Poisson de la lambda de producción SIN `calibrador_goles`; la
        # escalera que se enseña puede llevar esa curva encima. Dársela ya
        # calibrada sería corregir dos veces lo mismo, así que se reconstruye
        # la cruda desde `goles_lambda`. Lo que se DESPLAZA, en cambio, es lo
        # que se enseña: se lleva hasta donde dice el corrector.
        p25_cruda = p25
        # el total del ledger es la SUMA de las dos lambdas del regresor
        # (`encoger_lambdas` reparte pero conserva la suma), encogida hacia la
        # media de su liga
        lam_tot = (_num(gx.get('local')) or 0) + (_num(gx.get('visitante')) or 0)
        if lam_tot:
            # la del ledger: el total del regresor encogido hacia su liga
            try:
                import calibrador_lambda as _clam
                lam_tot = float(_clam.encoger(lam_tot, liga))
            except Exception:
                pass
        else:
            lam_tot = _num(pick.get('goles_lambda'))
        if lam_tot and lam_tot > 0:
            try:
                from scipy.stats import poisson as _po
                p25_cruda = _p(1 - float(_po.cdf(2, lam_tot))) or p25
            except Exception:
                pass
        cambios = {}
        # v306 — y los objetivos nuevos: un equipo mete dos o más, y el total
        # de más de 3,5. Cada modelo lee SUS rasgos (los de la v302 o los de
        # forma reciente, según cuál ganó en el juicio).
        try:
            from scipy.stats import poisson as _po2
            p35_cruda = (_p(1 - float(_po2.cdf(3, lam_tot)))
                         if lam_tot else None)
        except Exception:
            p35_cruda = None
        p35 = _p(gl.get('3.5'))
        # v316 — y la de 1,5
        try:
            p15_cruda = (_p(1 - float(_po2.cdf(1, lam_tot))) if lam_tot else None)
        except Exception:
            p15_cruda = None
        p15 = _p(gl.get('1.5'))
        p_h15 = _p((ge.get('local') or {}).get('1.5'))
        p_a15 = _p((ge.get('visitante') or {}).get('1.5'))
        pin_h15 = 1 - math.exp(-lam_h) * (1 + lam_h)
        pin_a15 = 1 - math.exp(-lam_a) * (1 + lam_a)
        por_modelo = doc.get('rasgos_modelo') or {}
        rasgos_def = doc.get('rasgos') or RASGOS_V1
        for nombre, p_in, p_old in (('mas25', p25_cruda, p25),
                                    ('marca_local', pin_h, p_h),
                                    ('marca_visitante', pin_a, p_a),
                                    ('local_mas15', pin_h15, p_h15),
                                    ('visit_mas15', pin_a15, p_a15),
                                    ('mas35', p35_cruda, p35),
                                    ('mas15', p15_cruda, p15)):
            if p_in is None or p_old is None:
                continue
            b = _booster(nombre)
            if b is None:
                continue
            fila = dict(base)
            fila['logit_modelo'] = float(_logit([p_in])[0])
            cols = por_modelo.get(nombre) or rasgos_def
            x = np.array([[fila.get(c, float('nan')) for c in cols]],
                         dtype=float)
            p_new = float(b.predict(x)[0])
            p_new = min(max(p_new, 1e-4), 1 - 1e-4)
            delta = math.log(p_new / (1 - p_new)) - math.log(p_old / (1 - p_old))
            delta = max(-MAX_DESPLAZAMIENTO_LOGIT,
                        min(MAX_DESPLAZAMIENTO_LOGIT, delta))
            cambios[nombre] = delta
        if not cambios:
            return False

        def _ordenada(lineas: Dict) -> Dict:
            """Más de 1,5 >= más de 2,5 >= más de 3,5...: si dos correcciones
            distintas la desordenan, se recorta hacia abajo."""
            fuera, techo = {}, 1.0
            for k in sorted(lineas, key=lambda z: float(z)):
                v = _p(lineas[k])
                if v is None:
                    fuera[k] = lineas[k]
                    continue
                techo = min(techo, v)
                fuera[k] = round(techo, 4)
            return fuera

        if 'mas25' in cambios or 'mas35' in cambios or 'mas15' in cambios:
            nuevas = {}
            for k, v in gl.items():
                pv = _p(v)
                if pv is None:
                    nuevas[k] = v
                    continue
                # v316 — cada tramo de la escalera con su corrector: 1,5 (y
                # menos) con el suyo, 2,5 con el de 2,5, 3,5 y más con el de
                # 3,5; si falta alguno, el de 2,5
                if float(k) >= 3.5:
                    d_ = cambios.get('mas35', cambios.get('mas25', 0.0))
                elif float(k) < 2:
                    d_ = cambios.get('mas15', cambios.get('mas25', 0.0))
                else:
                    d_ = cambios.get('mas25', 0.0)
                nuevas[k] = round(_mover(pv, d_), 4)
            nuevas = _ordenada(nuevas)
            pick['goles_lineas'] = nuevas
            b = pick.get('board') or {}
            if 'Más de 2.5' in b and _p(nuevas.get('2.5')):
                b['Más de 2.5'] = round(nuevas['2.5'], 3)
                b['Menos de 2.5'] = round(1 - nuevas['2.5'], 3)
            for m in (pick.get('mercados') or []):
                if m.get('apuesta') == 'Más de 2.5' and _p(nuevas.get('2.5')):
                    m['prob'] = round(nuevas['2.5'], 3)
                elif m.get('apuesta') == 'Menos de 2.5' and _p(nuevas.get('2.5')):
                    m['prob'] = round(1 - nuevas['2.5'], 3)
        for lado, n05, n15 in (('local', 'marca_local', 'local_mas15'),
                               ('visitante', 'marca_visitante', 'visit_mas15')):
            if not isinstance(ge.get(lado), dict):
                continue
            if n05 not in cambios and n15 not in cambios:
                continue
            nuevo_lado = {}
            for k, v in ge[lado].items():
                pv = _p(v)
                if pv is None:
                    nuevo_lado[k] = v
                    continue
                d_ = (cambios.get(n05, 0.0) if float(k) < 1 else
                      cambios.get(n15, cambios.get(n05, 0.0)))
                nuevo_lado[k] = round(_mover(pv, d_), 4)
            ge[lado] = _ordenada(nuevo_lado)
        pick['goles_equipo'] = ge
        # v326 — ambos marcan, con los dos «marca» ya corregidos
        btts_info = None
        try:
            ph_n = _p((ge.get('local') or {}).get('0.5'))
            pa_n = _p((ge.get('visitante') or {}).get('0.5'))
            b_ = pick.get('board') or {}
            pb_v = _p(b_.get('Ambos marcan: Sí'))
            if ph_n is not None and pa_n is not None and pb_v is not None:
                nuevo = btts_derivada(ph_n, pa_n, pb_v)
                if nuevo is not None:
                    nuevo = round(min(0.99, max(0.01, nuevo)), 3)
                    b_['Ambos marcan: Sí'] = nuevo
                    b_['Ambos marcan: No'] = round(1 - nuevo, 3)
                    for m in (pick.get('mercados') or []):
                        if m.get('apuesta') == 'Ambos marcan: Sí':
                            m['prob'] = nuevo
                        elif m.get('apuesta') == 'Ambos marcan: No':
                            m['prob'] = round(1 - nuevo, 3)
                    btts_info = {'antes': round(pb_v, 3), 'despues': nuevo}
        except Exception as _e_b:
            logger.debug('[patrones] ambos marcan %s: %s', pick.get('partido'), _e_b)
        pick['patron_liga'] = {
            'btts': btts_info,
            'tercio_local': tercio(f.get('pct_h')),
            'tercio_visitante': tercio(f.get('pct_a')),
            'desplazamiento': {k: round(v, 3) for k, v in cambios.items()},
            'texto': texto(liga, tercio(f.get('pct_h')),
                           tercio(f.get('pct_a')), h, a)}
        return True
    except Exception as e:
        logger.debug('[patrones] ajustar %s: %s', pick.get('partido'), e)
        return False


NOMBRE_TERCIO = {'arriba': 'de arriba', 'medio': 'de la mitad',
                 'abajo': 'de abajo'}


def texto(liga: str, t_h: Optional[str], t_a: Optional[str],
          h: str = '', a: str = '') -> str:
    """Una línea: el patrón de la liga para ESTE cruce, con su número."""
    pat = (cargar().get('patrones') or {}).get(liga) or {}
    trozos = []
    for lado, ter, eq in (('local', t_h, h), ('visitante', t_a, a)):
        c = pat.get('%s_%s' % (lado, ter)) if ter else None
        if not c or not c.get('significativo'):
            continue
        trozos.append('%s (%s de la tabla) mete %.2f %s; el modelo solía decir '
                      '%.2f' % (eq or lado, NOMBRE_TERCIO.get(ter, ter),
                                c['goles'],
                                'en casa' if lado == 'local' else 'de visita',
                                c['modelo']))
    return ('📈 Patrón de la liga: ' + ' · '.join(trozos) + '. Ya va corregido.'
            ) if trozos else ''


def ajustar_lista(pronosticos: List[Dict]) -> int:
    """Aplica `ajustar` a una lista. Devuelve cuántos tocó. NUNCA lanza."""
    n = 0
    for p in (pronosticos or []):
        if isinstance(p, dict) and ajustar(p):
            n += 1
    return n


def main() -> int:
    sys.stdout.reconfigure(encoding='utf-8')
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    if '--entrenar' in sys.argv:
        doc = entrenar()
        print('entrenado sobre %d partidos (juicio desde %s, n=%d)'
              % (doc['n'], doc['corte_juicio'], doc['n_juicio']))
        for k, v in doc['medicion'].items():
            print('  %-16s %.5f -> %.5f  mejora %+.5f (p5 %+.5f)  %s'
                  % (k, v['ll_base_calibrada'], v.get('ll_rasgos_v2', v.get('ll_aprendido', 0)), v['mejora'],
                     v['p5'], 'ACTIVO' if v['activo'] else 'apagado'))
        return 0
    doc = cargar()
    print('modelos activos:', sorted((doc.get('modelos') or {}).keys()))
    return 0


if __name__ == '__main__':
    sys.exit(main())
