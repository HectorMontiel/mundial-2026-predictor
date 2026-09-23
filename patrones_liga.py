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
RASGOS = ['lam_h', 'lam_a', 'pct_h', 'pct_a', 'ppg_h', 'ppg_a', 'gf_h',
          'gc_h', 'gf_a', 'gc_a', 'liga_goles', 'liga_cod', 'logit_modelo']
# objetivo: (columna real, columna de la predicción actual)
OBJETIVOS = {'mas25': ('over_2.5_real', 'p_over_2.5'),
             'marca_local': ('marca_h', 'p_marca_h'),
             'marca_visitante': ('marca_v', 'p_marca_v'),
             'btts': ('btts_real', 'p_btts')}
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

    def __init__(self):
        self.pts = defaultdict(lambda: deque(maxlen=VENTANA_PPG))
        self.gf = defaultdict(lambda: deque(maxlen=VENTANA_GOLES))
        self.gc = defaultdict(lambda: deque(maxlen=VENTANA_GOLES))
        self.ultimo = {}
        self.goles = deque(maxlen=400)

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

        return {'pct_h': pct(h), 'pct_a': pct(a),
                'ppg_h': ppg.get(h, float('nan')),
                'ppg_a': ppg.get(a, float('nan')),
                'gf_h': m(self.gf[h]), 'gc_h': m(self.gc[h]),
                'gf_a': m(self.gf[a]), 'gc_a': m(self.gc[a]),
                'liga_goles': (float(np.mean(self.goles))
                               if len(self.goles) >= 50 else float('nan'))}

    def sumar(self, h, a, d, hg, ag) -> None:
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
        t = Tabla()
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
    df['t_h'] = df['pct_h'].map(tercio)
    df['t_a'] = df['pct_a'].map(tercio)
    return df.reset_index(drop=True)


def _logit(p):
    import numpy as np
    p = np.clip(np.asarray(p, dtype=float), 1e-3, 1 - 1e-3)
    return np.log(p / (1 - p))


def _X(d, p_col, codigos):
    x = d[[c for c in RASGOS if c not in ('liga_cod', 'logit_modelo')]].copy()
    x['liga_cod'] = d['liga'].map(codigos).fillna(-1).astype(int)
    x['logit_modelo'] = _logit(d[p_col])
    return x[RASGOS]


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
    doc = {'version': 1,
           'generado': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
           'corte_juicio': str(corte.date()), 'n': int(len(df)),
           'n_juicio': int(len(jui)), 'codigos': codigos, 'rasgos': RASGOS,
           'medicion': {}, 'modelos': {}, 'patrones': patrones(df)}
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
        doc['medicion'][nombre] = {
            'll_base_calibrada': round(float(_ll(y, p_cal).mean()), 5),
            'll_aprendido': round(float(_ll(y, p_new).mean()), 5),
            'mejora': round(float(dif.mean()), 5), 'p5': round(p5, 5),
            'activo': activo}
        logger.info('[patrones] %-16s mejora %+.5f p5 %+.5f -> %s', nombre,
                    dif.mean(), p5, 'ACTIVO' if activo else 'apagado')
        if activo:
            # validado: se entrena con TODO, que es lo que se usa en vivo
            d = df.dropna(subset=[y_col, p_col])
            final = lgb.train(PARAMS, lgb.Dataset(
                _X(d, p_col, codigos), label=d[y_col].astype(int),
                categorical_feature=['liga_cod']), num_boost_round=RONDAS)
            doc['modelos'][nombre] = final.model_to_string()
    if guardar:
        tmp = FICHERO + '.nuevo'
        with open(tmp, 'w', encoding='utf-8', newline='\n') as f:
            json.dump(doc, f, ensure_ascii=False)
        os.replace(tmp, FICHERO)
        olvidar()
    return doc


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
        t = Tabla()
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
        for nombre, p_in, p_old in (('mas25', p25_cruda, p25),
                                    ('marca_local', pin_h, p_h),
                                    ('marca_visitante', pin_a, p_a)):
            b = _booster(nombre)
            if b is None:
                continue
            fila = dict(base)
            fila['logit_modelo'] = float(_logit([p_in])[0])
            x = np.array([[fila[c] for c in RASGOS]], dtype=float)
            p_new = float(b.predict(x)[0])
            p_new = min(max(p_new, 1e-4), 1 - 1e-4)
            delta = math.log(p_new / (1 - p_new)) - math.log(p_old / (1 - p_old))
            delta = max(-MAX_DESPLAZAMIENTO_LOGIT,
                        min(MAX_DESPLAZAMIENTO_LOGIT, delta))
            cambios[nombre] = delta
        if not cambios:
            return False
        if 'mas25' in cambios:
            nuevas = {}
            for k, v in gl.items():
                pv = _p(v)
                nuevas[k] = round(_mover(pv, cambios['mas25']), 4) \
                    if pv is not None else v
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
        for lado, nombre in (('local', 'marca_local'),
                             ('visitante', 'marca_visitante')):
            if nombre not in cambios or not isinstance(ge.get(lado), dict):
                continue
            ge[lado] = {k: (round(_mover(_p(v), cambios[nombre]), 4)
                            if _p(v) is not None else v)
                        for k, v in ge[lado].items()}
        pick['goles_equipo'] = ge
        pick['patron_liga'] = {
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
                  % (k, v['ll_base_calibrada'], v['ll_aprendido'], v['mejora'],
                     v['p5'], 'ACTIVO' if v['activo'] else 'apagado'))
        return 0
    doc = cargar()
    print('modelos activos:', sorted((doc.get('modelos') or {}).keys()))
    return 0


if __name__ == '__main__':
    sys.exit(main())
