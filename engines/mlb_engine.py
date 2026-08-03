#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MLBEngine (v29 §4) — béisbol, hereda de BaseSportsEngine.

Fuente: Retrosheet game logs (histórico gratuito, 2021-2025, 11.9k juegos)
para entrenar; The Odds API (baseball_mlb, en temporada) para cuotas en vivo.
Sin empates → clasificador binario (gana local sí/no).

Features pre-partido SIN fuga (pase cronológico):
  DIFF_ELO · DIFF_RUNS_SCORED_MA10 · DIFF_RUNS_ALLOWED_MA10 · DIFF_STREAK ·
  DIFF_REST · DIFF_PITCHER_RA (carreras/apertura recientes del abridor —
  la variable más crítica del béisbol) + absolutos para el regresor de total.

Estado por equipo/pitcher persistido en modelos/mlb/estado.json para
reproducir las features en inferencia (mismo patrón que las ligas de fútbol).
"""

import datetime
import json
import logging
import os
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from engines.base_engine import BaseSportsEngine

logger = logging.getLogger(__name__)

MA = 10
FEATURES = ['DIFF_ELO', 'DIFF_RS_MA', 'DIFF_RA_MA', 'DIFF_STREAK',
            'DIFF_REST', 'DIFF_PIT_RA', 'SUMA_RS_MA', 'SUMA_RA_MA',
            'MEDIA_PIT_RA']
CARPETA = os.path.join('modelos', 'mlb')

# nombre The Odds API/ESPN -> código Retrosheet (para cruzar cuotas en vivo)
NOMBRES_MLB = {
    'Los Angeles Angels': 'ANA', 'Arizona Diamondbacks': 'ARI',
    'Atlanta Braves': 'ATL', 'Baltimore Orioles': 'BAL', 'Boston Red Sox': 'BOS',
    'Chicago White Sox': 'CHA', 'Chicago Cubs': 'CHN', 'Cincinnati Reds': 'CIN',
    'Cleveland Guardians': 'CLE', 'Colorado Rockies': 'COL',
    'Detroit Tigers': 'DET', 'Houston Astros': 'HOU', 'Kansas City Royals': 'KCA',
    'Los Angeles Dodgers': 'LAN', 'Miami Marlins': 'MIA',
    'Milwaukee Brewers': 'MIL', 'Minnesota Twins': 'MIN',
    'New York Yankees': 'NYA', 'New York Mets': 'NYN', 'Oakland Athletics': 'OAK',
    'Athletics': 'ATH', 'Philadelphia Phillies': 'PHI', 'Pittsburgh Pirates': 'PIT',
    'San Diego Padres': 'SDN', 'Seattle Mariners': 'SEA',
    'San Francisco Giants': 'SFN', 'St. Louis Cardinals': 'SLN',
    'Tampa Bay Rays': 'TBA', 'Texas Rangers': 'TEX', 'Toronto Blue Jays': 'TOR',
    'Washington Nationals': 'WAS',
}
# v79 — «Athletics» y «Oakland Athletics» son el MISMO equipo. Retrosheet
# cambió el código OAK (1.502 juegos, hasta 2024-09-29) por ATH (162 juegos,
# desde 2025-03-27) cuando la franquicia se mudó, y el histórico acabó con 31
# códigos para 30 equipos: el ELO de los Athletics se reiniciaba a 1500 a
# mitad del dataset. Se canonaliza en OAK, que es donde está la historia larga.
NOMBRES_MLB['Athletics'] = 'OAK'
NOMBRES_MLB['Oakland Athletics'] = 'OAK'
NOMBRES_MLB['Sacramento Athletics'] = 'OAK'

CODIGO_A_NOMBRE = {v: k for k, v in NOMBRES_MLB.items()}
CODIGO_A_NOMBRE['OAK'] = 'Athletics'


def _json_seguro(o):
    """
    v79 — `estado['filas']` guarda (Timestamp, local, visitante) y `json.dump`
    no sabe serializar un Timestamp.

    Esto rompía `entrenar()` **desde la v78**, que fue quien añadió `filas` para
    poder alinear el ledger. No se notó porque el ledger llama a `_dataset` en
    memoria y nunca pasa por JSON: el único camino roto era el reentrenamiento,
    y mientras no se reentrenara no saltaba. La huella quedó en el
    `estado.json` de producción, que tenía `filas: 0` — se había escrito con
    código anterior a la v78.
    """
    if isinstance(o, (pd.Timestamp, datetime.date, datetime.datetime)):
        return str(pd.Timestamp(o).date())
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    raise TypeError(f'no serializable: {type(o).__name__}')


def _escribir_json(ruta: str, datos) -> None:
    """
    v79 — escritura ATÓMICA del estado.

    `json.dump` va escribiendo a medida que serializa, así que si falla a mitad
    (por ejemplo con un tipo no serializable) deja el fichero TRUNCADO. Pasó al
    reparar esto: `estado.json` quedó cortado en el carácter 48.380 y el motor
    dejó de arrancar con `JSONDecodeError`, que es peor que el fallo original —
    el modelo entero se cae en producción por un error de escritura.

    Se escribe a un temporal y se reemplaza de golpe: o está el fichero viejo
    entero, o el nuevo entero. Nunca medio.
    """
    tmp = f'{ruta}.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(datos, f, default=_json_seguro)
    os.replace(tmp, ruta)


# v88 — ALIAS DECLARADOS de las casas. Se ponen a mano a propósito: la
# alternativa (fuzzy permisivo) resultó ser una fuente de errores graves.
ALIAS_MLB = {
    'la dodgers': 'LAN', 'l a dodgers': 'LAN', 'los angeles dodgers': 'LAN',
    'la angels': 'ANA', 'l a angels': 'ANA', 'los angeles angels of anaheim': 'ANA',
    'ny yankees': 'NYA', 'n y yankees': 'NYA',
    'ny mets': 'NYN', 'n y mets': 'NYN',
    'sf giants': 'SFN', 'san francisco giants': 'SFN',
    'sd padres': 'SDN', 'san diego padres': 'SDN',
    'st louis cardinals': 'SLN', 'saint louis cardinals': 'SLN',
    'tampa bay devil rays': 'TBA',
    'cleveland indians': 'CLE',
    'florida marlins': 'MIA',
    'montreal expos': 'WAS',
    'chicago cubs': 'CHN', 'chicago white sox': 'CHA',
    'oakland as': 'OAK', 'oakland a s': 'OAK', 'las vegas athletics': 'OAK',
}

# Umbral del respaldo difuso. 0,60 —el valor anterior— daba un 10 % de FALSOS
# POSITIVOS sobre equipos de otras ligas de béisbol que sí están en el mismo
# tablón de cuotas (medido en _v88_falsos_positivos_mlb.py):
#
#     Chiba Lotte Marines (NPB)      -> SEA  Seattle Mariners
#     Kia Tigers (KBO)               -> DET  Detroit Tigers
#     Fubon Guardians (CPBL)         -> CLE  Cleveland Guardians
#     Sacramento River Cats (AAA)    -> OAK  Oakland Athletics
#     Tacoma Rainiers (AAA)          -> TEX  Texas Rangers
#
# Y eso importa porque `codigo_mlb` es la puerta por la que los nombres de las
# casas entran al MOTOR: un partido de la KBO acababa prediciéndose con las
# estadísticas de Detroit y colándose en la Capa 1 etiquetado como «MLB».
UMBRAL_FUZZY_MLB = 0.90


def _norm_mlb(nombre: str) -> str:
    import re
    import unicodedata
    s = unicodedata.normalize('NFKD', str(nombre or ''))
    s = ''.join(c for c in s if not unicodedata.combining(c)).lower()
    s = re.sub(r"[.\-'’,]", ' ', s)
    return ' '.join(s.split())


_NORM_A_CODIGO = {_norm_mlb(n): c for n, c in NOMBRES_MLB.items()}
_NORM_A_CODIGO.update(ALIAS_MLB)
CODIGOS_MLB = set(NOMBRES_MLB.values())


def codigo_mlb(nombre: str) -> str:
    """
    Nombre de casa → código Retrosheet.

    Devuelve el nombre CRUDO si no lo reconoce, igual que antes, para no romper
    a quien lo use como identificador. Para decidir si un partido es de la MLB
    hay que usar `es_equipo_mlb`, que no adivina.
    """
    n = _norm_mlb(nombre)
    if n in _NORM_A_CODIGO:
        return _NORM_A_CODIGO[n]
    from difflib import SequenceMatcher
    mejor, ratio = nombre, 0.0
    for clave, c in _NORM_A_CODIGO.items():
        s = SequenceMatcher(None, n, clave).ratio()
        if s > ratio:
            mejor, ratio = c, s
    return mejor if ratio >= UMBRAL_FUZZY_MLB else nombre


def es_equipo_mlb(nombre: str) -> bool:
    """¿Es este nombre un equipo de la MLB? Sin adivinar."""
    return codigo_mlb(nombre) in CODIGOS_MLB


def es_partido_mlb(home: str, away: str) -> bool:
    """
    ¿Es este partido de la MLB?

    Los tablones de cuotas de «mlb» traen también LMB (México), NPB (Japón),
    KBO (Corea), CPBL (Taiwán) y Triple-A. Medido el 2026-07-31: de 80 entradas
    en Pinnacle/Bovada/Playdoit, sólo **16 partidos** eran MLB de verdad.
    """
    return es_equipo_mlb(home) and es_equipo_mlb(away)


class MLBEngine(BaseSportsEngine):
    def __init__(self):
        super().__init__('MLB', CARPETA)
        self.estado = {}
        ruta = os.path.join(CARPETA, 'estado.json')
        if os.path.exists(ruta):
            with open(ruta, encoding='utf-8') as f:
                self.estado = json.load(f)
        self.equipos = sorted((self.estado.get('equipos') or {}).keys())

    def cargar_datos_historicos(self) -> pd.DataFrame:
        """
        v79 — se cambia Retrosheet por la API oficial de la MLB.

        Retrosheet publica los game logs **por temporada cerrada**, así que la
        temporada en curso no existía para el modelo. Medido el 2026-07-29: el
        último partido conocido era de **2025-09-28**, 304 días atrás, y la
        2026 se predecía con la forma del año anterior.

        `mlb_statsapi` es la API oficial (gratuita, sin clave), trae la
        temporada viva y además el abridor probable. Se ingieren 11 años para
        tener pasado largo con un solo espacio de nombres de lanzadores.
        """
        import datetime
        import mlb_statsapi
        y = datetime.date.today().year
        return mlb_statsapi.actualizar(list(range(y - 11, y + 1)))

    # ---- construcción de features sin fuga (train + estado final) -------
    @staticmethod
    def _dataset(df: pd.DataFrame):
        df = df.sort_values('date').reset_index(drop=True)
        elo: Dict[str, float] = {}
        rs: Dict[str, list] = {}      # runs scored recientes
        ra: Dict[str, list] = {}      # runs allowed recientes
        streak: Dict[str, int] = {}
        ult_fecha: Dict[str, pd.Timestamp] = {}
        pit_ra: Dict[str, list] = {}  # carreras permitidas por apertura
        X, y, tot, fechas = [], [], [], []
        filas_id = []                      # v78: (fecha, local, visitante)
        for r in df.itertuples(index=False):
            h, a = r.home_team, r.away_team
            eh, ea = elo.get(h, 1500.0), elo.get(a, 1500.0)
            def _m(d, k, dv):
                v = d.get(k, [])
                return np.mean(v[-MA:]) if v else dv
            rs_h, rs_a = _m(rs, h, 4.5), _m(rs, a, 4.5)
            ra_h, ra_a = _m(ra, h, 4.5), _m(ra, a, 4.5)
            rest_h = min((r.date - ult_fecha[h]).days, 7) if h in ult_fecha else 3
            rest_a = min((r.date - ult_fecha[a]).days, 7) if a in ult_fecha else 3
            pr_h = np.mean(pit_ra.get(r.home_pitcher, [])[-5:]) \
                if pit_ra.get(r.home_pitcher) else 4.5
            pr_a = np.mean(pit_ra.get(r.away_pitcher, [])[-5:]) \
                if pit_ra.get(r.away_pitcher) else 4.5
            if all(len(rs.get(t, [])) >= 5 for t in (h, a)):
                X.append([(eh - ea) / 100.0, (rs_h - rs_a) / 3.0,
                          (ra_h - ra_a) / 3.0,
                          (streak.get(h, 0) - streak.get(a, 0)) / 5.0,
                          (rest_h - rest_a) / 5.0, (pr_h - pr_a) / 3.0,
                          (rs_h + rs_a) / 9.0, (ra_h + ra_a) / 9.0,
                          (pr_h + pr_a) / 9.0])
                y.append(int(r.home_runs > r.away_runs))
                tot.append(r.home_runs + r.away_runs)
                fechas.append(r.date)
                filas_id.append((r.date, str(h), str(a)))
            # actualizar estado (sin fuga: después de emitir)
            gh, ga = float(r.home_runs), float(r.away_runs)
            rs.setdefault(h, []).append(gh); ra.setdefault(h, []).append(ga)
            rs.setdefault(a, []).append(ga); ra.setdefault(a, []).append(gh)
            # v79: un abridor sin identificar ('' o NaN) NO puede acumularse.
            # Si se deja, todos los partidos sin abridor anunciado caen en el
            # mismo cubo y ese cubo se convierte en un «lanzador» con miles de
            # aperturas cuya media es la de la liga entera — ruido disfrazado
            # de señal. Se ignora: el partido sigue entrenando, solo no aporta
            # historial de lanzador.
            if isinstance(r.home_pitcher, str) and r.home_pitcher:
                pit_ra.setdefault(r.home_pitcher, []).append(ga)
            if isinstance(r.away_pitcher, str) and r.away_pitcher:
                pit_ra.setdefault(r.away_pitcher, []).append(gh)
            for eq, gano in ((h, gh > ga), (a, ga > gh)):
                streak[eq] = max(streak.get(eq, 0), 0) + 1 if gano else \
                    min(streak.get(eq, 0), 0) - 1
            e_h = 1 / (1 + 10 ** ((ea - eh) / 400))
            s_h = 1.0 if gh > ga else 0.0
            elo[h] = eh + 20 * (s_h - e_h)
            elo[a] = ea + 20 * ((1 - s_h) - (1 - e_h))
            ult_fecha[h] = ult_fecha[a] = r.date
        # v78: identidad de CADA fila emitida, en el mismo orden que X e y.
        # Sin esto, quien quiera cruzar las predicciones con cuotas externas
        # tiene que adivinar el orden replicando este bucle, y basta con que el
        # desempate de `sort_values('date')` difiera para que las cuotas se
        # peguen al partido equivocado. Eso no da error: FABRICA un edge falso,
        # porque el filtro de EV se queda justo con las filas donde la cuota
        # ajena salió alta. Se detectó porque el log-loss del mercado salía
        # 0,7142 — peor que una moneda al aire, imposible en cuotas reales.
        estado = {'equipos': {}, 'pitchers': {}, 'filas': filas_id}
        for t in set(list(rs) + list(ra)):
            estado['equipos'][t] = {
                'elo': round(elo.get(t, 1500), 1),
                'rs': [round(x, 2) for x in rs.get(t, [])[-MA:]],
                'ra': [round(x, 2) for x in ra.get(t, [])[-MA:]],
                'streak': int(streak.get(t, 0)),
                'ult_fecha': ult_fecha[t].strftime('%Y-%m-%d') if t in ult_fecha else None}
        for p, v in pit_ra.items():
            estado['pitchers'][p] = [round(x, 2) for x in v[-5:]]
        return (np.array(X), np.array(y), np.array(tot),
                pd.Series(fechas), estado)

    def entrenar(self) -> Dict:
        from sklearn.calibration import CalibratedClassifierCV
        from sklearn.ensemble import (HistGradientBoostingRegressor,
                                      RandomForestClassifier, VotingClassifier)
        from sklearn.linear_model import LogisticRegression
        from sklearn.metrics import accuracy_score, log_loss
        from sklearn.preprocessing import StandardScaler
        from lightgbm import LGBMClassifier
        from xgboost import XGBClassifier

        df = self.cargar_datos_historicos()
        X, y, tot, fechas, estado = self._dataset(df)
        logger.info(f"[mlb] dataset: {len(X)} juegos utilizables")
        corte = fechas.quantile(0.80)
        m_tr = (fechas < corte).values
        sc = StandardScaler().fit(X[m_tr])
        Xtr, Xva = sc.transform(X[m_tr]), sc.transform(X[~m_tr])

        def _ens():
            vc = VotingClassifier([
                ('xgb', XGBClassifier(n_estimators=200, max_depth=4,
                                      learning_rate=0.05, verbosity=0)),
                ('lgbm', LGBMClassifier(n_estimators=200, max_depth=4,
                                        learning_rate=0.05, verbose=-1)),
                ('rf', RandomForestClassifier(n_estimators=200, max_depth=8,
                                              random_state=42))], voting='soft')
            return CalibratedClassifierCV(vc, method='isotonic', cv=3)
        modelo = _ens().fit(Xtr, y[m_tr])
        proba = modelo.predict_proba(Xva)[:, list(modelo.classes_).index(1)]
        pred = (proba >= 0.5).astype(int)
        acc = accuracy_score(y[~m_tr], pred)
        ll = log_loss(y[~m_tr], np.column_stack([1 - proba, proba]))
        base = accuracy_score(y[~m_tr], (X[~m_tr][:, 0] > 0).astype(int))  # ELO

        reg = HistGradientBoostingRegressor(loss='poisson', max_iter=300,
                                            learning_rate=0.05, max_depth=5,
                                            random_state=42).fit(Xtr, tot[m_tr])

        os.makedirs(CARPETA, exist_ok=True)
        import joblib
        joblib.dump(modelo, os.path.join(CARPETA, 'moneyline.joblib'), compress=3)
        joblib.dump(sc, os.path.join(CARPETA, 'scaler.joblib'), compress=3)
        joblib.dump(reg, os.path.join(CARPETA, 'totales.joblib'), compress=3)
        _escribir_json(os.path.join(CARPETA, 'estado.json'), estado)
        # v79 — el metadata se FUNDE, no se sobrescribe.
        #
        # `sigma_margen` lo calcula `calibrar_margenes_v32.py`, no el
        # entrenamiento, y `mercados_excluidos` se anota a mano. Al escribir el
        # dict entero se borraban los dos, y sin `sigma_margen` la plantilla de
        # `base_engine` deja de emitir spread y totales por equipo — en
        # silencio, porque están detrás de un `if sigma`. Cada reentrenamiento
        # amputaba mercados sin que saltara ningún error.
        ruta_meta = os.path.join(CARPETA, 'metadata.json')
        meta = {}
        if os.path.exists(ruta_meta):
            try:
                with open(ruta_meta, encoding='utf-8') as f:
                    meta = json.load(f)
            except Exception:
                meta = {}
        meta.update({'deporte': 'MLB', 'n_juegos': len(X),
                     'precision_validacion': round(float(acc), 4),
                     'precision_linea_base_elo': round(float(base), 4),
                     'log_loss_validacion': round(float(ll), 4),
                     'linea_total_tipica': float(np.median(tot)),
                     'fecha_entrenamiento':
                         pd.Timestamp.today().strftime('%Y-%m-%d')})
        with open(ruta_meta, 'w', encoding='utf-8') as f:
            json.dump(meta, f, indent=2)
        logger.info(f"[mlb] acc={acc:.4f} (ELO {base:.4f}) ll={ll:.4f}")
        return meta

    def construir_features(self, home: str, away: str,
                           home_pitcher: str = None,
                           away_pitcher: str = None,
                           fecha=None, **ctx) -> Optional[List[float]]:
        """
        v79 — se reparan las TRES features que estaban muertas en inferencia.

        El entrenamiento usa 9 features, pero en producción `apuestas_dia`
        llamaba a `predecir(home, away)` sin abridores ni fecha, así que tres
        de ellas salían con el mismo valor en todos los partidos. Medido sobre
        todos los emparejamientos posibles:

            DIFF_REST     media +0,0000   std 0,0000   <- constante
            DIFF_PIT_RA   media +0,0000   std 0,0000   <- constante
            MEDIA_PIT_RA  media +1,0000   std 0,0000   <- constante

        Un tercio de las entradas del modelo era ruido fijo, y justo el tercio
        que más pesa en béisbol: quién abre. El clasificador estaba entrenado
        para apoyarse en ellas y en producción no las recibía nunca, así que
        se replegaba al centro. De ahí que el 58,5 % de los partidos saliera
        entre 45 % y 55 %.

        Ahora el descanso se calcula contra la fecha real del partido y los
        abridores llegan desde `mlb_statsapi`. Si un abridor no está anunciado
        se degrada al valor neutro 4,5 (igual que en entrenamiento cuando no
        había historial), pero eso ahora es la excepción, no la norma.
        """
        eq = self.estado.get('equipos', {})
        if home not in eq or away not in eq:
            return None
        pit = self.estado.get('pitchers', {})
        h, a = eq[home], eq[away]
        rs_h = np.mean(h['rs']) if h['rs'] else 4.5
        rs_a = np.mean(a['rs']) if a['rs'] else 4.5
        ra_h = np.mean(h['ra']) if h['ra'] else 4.5
        ra_a = np.mean(a['ra']) if a['ra'] else 4.5
        pr_h = np.mean(pit.get(home_pitcher, [])[-5:]) if pit.get(home_pitcher) else 4.5
        pr_a = np.mean(pit.get(away_pitcher, [])[-5:]) if pit.get(away_pitcher) else 4.5

        # DIFF_REST con la misma fórmula del entrenamiento: días desde el
        # último partido, tope 7, y 3 por defecto si no consta.
        ref = pd.to_datetime(fecha) if fecha is not None else pd.Timestamp.today()
        ref = pd.Timestamp(ref).normalize()

        def _descanso(info):
            u = info.get('ult_fecha')
            if not u:
                return 3.0
            try:
                d = (ref - pd.Timestamp(u).normalize()).days
            except Exception:
                return 3.0
            return float(min(max(d, 0), 7)) if d >= 0 else 3.0

        rest_h, rest_a = _descanso(h), _descanso(a)
        return [(h['elo'] - a['elo']) / 100.0, (rs_h - rs_a) / 3.0,
                (ra_h - ra_a) / 3.0, (h['streak'] - a['streak']) / 5.0,
                (rest_h - rest_a) / 5.0, (pr_h - pr_a) / 3.0,
                (rs_h + rs_a) / 9.0, (ra_h + ra_a) / 9.0,
                (pr_h + pr_a) / 9.0]

    # ------------------------------------------------------------------
    def refrescar_estado(self, df: Optional[pd.DataFrame] = None) -> Dict:
        """
        v79 — recalcula `estado.json` SIN reentrenar el modelo.

        El estado (ELO, forma de 10 partidos, racha, última fecha, aperturas de
        cada lanzador) sólo se escribía al entrenar. Entrenar es caro, así que
        se hacía de tarde en tarde y el estado envejecía con la temporada: el
        modelo del 2026-07-29 miraba el mundo del 2025-09-28.

        Separar las dos cosas es lo que arregla el problema de raíz: los pesos
        del clasificador cambian poco y pueden reentrenarse de vez en cuando,
        pero el estado tiene que ir al día — y recalcularlo es un solo barrido
        sobre el CSV, sin sklearn de por medio.
        """
        if df is None:
            df = self.cargar_datos_historicos()
        if df is None or df.empty:
            return {'error': 'sin datos históricos'}
        _X, _y, _t, _f, estado = self._dataset(df)
        os.makedirs(CARPETA, exist_ok=True)
        ruta = os.path.join(CARPETA, 'estado.json')
        _escribir_json(ruta, estado)
        self.estado = estado
        self.equipos = sorted((estado.get('equipos') or {}).keys())
        fechas = [v.get('ult_fecha') for v in estado['equipos'].values()
                  if v.get('ult_fecha')]
        ultima = max(fechas) if fechas else None
        logger.info(f"[mlb] estado refrescado: {len(estado['equipos'])} equipos, "
                    f"{len(estado['pitchers'])} lanzadores, último {ultima}")
        return {'equipos': len(estado['equipos']),
                'pitchers': len(estado['pitchers']),
                'ultimo_partido': ultima, 'juegos': int(len(_X))}


    def apuestas_dia(self, min_prob: float = 0.58, min_ev: float = 0.03,
                     min_cuota: float = 1.50, max_req: int = 1) -> Dict:
        """
        Picks de MLB con la capa de cuotas UNIVERSAL (Pinnacle + Bovada +
        Playdoit).

        v77 — POR QUÉ SE REESCRIBE. Esta función seguía colgando de The Odds
        API, que tiene cuota mensual. Medido el 2026-07-28: la cuota estaba a
        **0 de 500**, así que devolvía `{'picks': [], 'aviso': 'Presupuesto de
        API agotado hoy.'}` y **la MLB desaparecía del barrido entero**. No era
        que no hubiera partidos ni que el modelo fallase: el motor cargaba
        bien, simplemente se quedaba sin crédito y nadie lo veía porque el
        aviso no llegaba a la interfaz.

        El fútbol y el tenis se migraron a la capa sin cuota en la v71 y la
        v72; la MLB se quedó atrás y arrastraba el problema desde entonces.
        Ahora usa las mismas fuentes gratuitas e ilimitadas — medido el mismo
        día: Pinnacle 32 partidos, Bovada 14, Playdoit 47.

        Se conserva el `sharp_gap` contra Pinnacle, que era lo valioso de la
        implementación anterior: sigue siendo la referencia eficiente.
        """
        if not self.listo:
            return {'picks': [], 'aviso': 'Modelo MLB no disponible.',
                    'incidencias': ['MLB: el modelo no está entrenado.']}
        try:
            import cuotas_multi as cm
        except Exception as e:
            return {'picks': [], 'aviso': f'Capa de cuotas no disponible: {e}',
                    'incidencias': [f'MLB: capa de cuotas no disponible ({e}).']}

        incidencias = []
        confianza = []          # v91: alta prob sin filtros de élite
        try:
            cm.precargar('mlb')
        except Exception as e:
            incidencias.append(f'MLB: precarga de cuotas con avisos ({e}).')

        # Universo de partidos: la unión de las tres casas, porque cada una
        # cubre ligas distintas (Pinnacle trae también la Liga Mexicana).
        #
        # v77: la clave de deduplicación es el CÓDIGO DEL MODELO, no el nombre
        # que use la casa. Con el nombre normalizado, «Baltimore Orioles»
        # (Bovada) y «BAL Orioles» (Playdoit) son claves distintas y el mismo
        # partido entraba dos veces, saliendo duplicado en la Capa 1 con dos
        # cuotas distintas. Los códigos Retrosheet son la identidad canónica
        # del partido para el modelo, así que dos fuentes que hablen del mismo
        # encuentro colapsan sí o sí.
        #
        # v88 — SE FILTRA A LA MLB DE VERDAD. El tablón de «mlb» trae también
        # LMB (México), NPB (Japón), KBO (Corea), CPBL (Taiwán) y Triple-A.
        # Medido el 2026-07-31: de 80 entradas en las tres casas, sólo **16
        # partidos** eran MLB. Sin este filtro, la deduplicación por código no
        # colapsaba nada (los nombres desconocidos se devuelven crudos, así que
        # «Uni-President Lions» y «Uni-President 7-Eleven Lions» contaban como
        # equipos distintos) y esos partidos llegaban a la Capa 1 etiquetados
        # como MLB.
        universo = {}
        fuera_mlb = 0
        for idx in (cm._indice('mlb'), cm._indice_bov('mlb'), cm._indice_pdt('mlb')):
            for v in (idx or {}).values():
                if not (v.get('home') and v.get('away')):
                    continue
                if not es_partido_mlb(v['home'], v['away']):
                    fuera_mlb += 1
                    continue
                clave = (codigo_mlb(v['home']), codigo_mlb(v['away']))
                universo.setdefault(clave, v)
        if fuera_mlb:
            # v91: filtrar las ligas ajenas (LMB/NPB/KBO/CPBL/AAA) es la
            # OPERACIÓN NORMAL del guardarraíl de la v88, no una incidencia —
            # mostrarlo como aviso hacía parecer un fallo lo que es el sistema
            # funcionando. Queda en el log para auditoría.
            logger.info(f'[mlb] {fuera_mlb} entradas del tablón no-MLB '
                        f'filtradas (LMB/NPB/KBO/CPBL/AAA) — normal.')

        # v79 — ABRIDORES PROBABLES. El modelo se entrena con las carreras que
        # concede cada abridor en sus últimas 5 salidas, pero aquí se le
        # llamaba sin pasarlos, así que en producción esa señal era una
        # constante. Es la variable más predictiva del béisbol y era justo la
        # que faltaba. La API oficial los publica el mismo día.
        abridores = {}
        try:
            import mlb_statsapi
            abridores = mlb_statsapi.indice_abridores()
        except Exception as e:
            incidencias.append(f'MLB: abridores probables no disponibles ({e}); '
                               f'se predice sin ellos.')

        picks, evaluados, sin_modelo, con_abridor = [], 0, 0, 0
        for v in universo.values():
            hc = codigo_mlb(v['home'])
            ac = codigo_mlb(v['away'])
            hp, ap = abridores.get((hc, ac), ('', ''))
            if hp and ap:
                con_abridor += 1
            pred = self.predecir(hc, ac, home_pitcher=hp, away_pitcher=ap,
                                 fecha=v.get('fecha'))
            if 'error' in pred:
                sin_modelo += 1
                continue
            evaluados += 1
            c = cm.cuotas_partido('mlb', v['home'], v['away'])
            mejor = c.get('mejor') or {}
            pin = c.get('pinnacle') or {}
            if not mejor:
                continue
            # v78 — ENCOGIMIENTO HACIA EL MERCADO. La corrección del sesgo de
            # selección solo llegaba al fútbol, y se notaba: los picks de MLB
            # salían con EV de +11 % justo donde el fútbol ya estaba corregido.
            # Se aplica el mismo método (misma función, para que no diverja).
            # v79 — vía `calibracion_segura` (ver su docstring: un módulo
            # obsoleto en `sys.modules` tumbaba el deporte entero).
            import calibracion_segura as _cal
            _ph, _info_cal = _cal.encoger_dos_vias(
                pred['prob_home'],
                (mejor.get('home') or {}).get('cuota'),
                (mejor.get('away') or {}).get('cuota'), 'mlb')
            for lado, cod, prob in (('home', hc, _ph),
                                    ('away', ac, 1.0 - _ph)):
                info = mejor.get(lado)
                if not info or not info.get('cuota'):
                    continue
                cuota = float(info['cuota'])
                ev_val = self.calcular_ev(prob, cuota)
                if not (prob > min_prob and ev_val > min_ev and cuota > min_cuota):
                    # v91 — LO QUE NO PASA LOS FILTROS DE ÉLITE NO SE TIRA.
                    #
                    # La MLB no aparecía JAMÁS en «Máxima Confianza» aunque
                    # evaluara 8 partidos al día: `apuestas_dia` sólo devolvía
                    # lo que superaba prob+EV+cuota y `capa2` iba vacía por
                    # construcción. Un favorito de MLB al 68 % con cuota real
                    # es exactamente el material de esa pestaña (acertar por
                    # encima de cobrar caro, v77) y se estaba descartando.
                    #
                    # Se guarda aparte, con su EV real —negativo si lo es— para
                    # que la pestaña pueda marcarlo. No entra en Capa 1: los
                    # filtros de élite siguen mandando ahí.
                    if prob >= 0.60 and cuota > 1.0:
                        confianza.append({
                            'deporte': 'MLB', 'liga': 'MLB',
                            'clave_liga': 'mlb',
                            'partido': f"{CODIGO_A_NOMBRE.get(ac, v['away'])} @ "
                                       f"{CODIGO_A_NOMBRE.get(hc, v['home'])}",
                            'fecha': (str(pd.to_datetime(v.get('fecha')).date())
                                      if v.get('fecha')
                                      else str(pd.Timestamp.utcnow().date())),
                            'mercado': 'Moneyline',
                            'apuesta': f"Gana {v['home'] if lado == 'home' else v['away']}",
                            'prob': round(prob, 3), 'cuota': round(cuota, 2),
                            'cuota_justa': round(1 / max(prob, 1e-6), 2),
                            'ev': ev_val, 'casa': info.get('casa'),
                            'valor': '🎯',
                            'motivo_capa2': (
                                f'cuota {cuota:.2f} por debajo del mínimo '
                                f'{min_cuota:.2f}' if cuota <= min_cuota else
                                f'EV {ev_val:+.1%} por debajo del mínimo')})
                    continue
                otro = 'away' if lado == 'home' else 'home'
                nombre = v['home'] if lado == 'home' else v['away']
                gap = None
                try:
                    # v88: `sharp_gap_2via` se mudó de `odds_api` (retirado) a
                    # `cuotas_multi`, junto a `devig`. Es una función pura.
                    gap = cm.sharp_gap_2via(prob, pin.get(lado), pin.get(otro))
                except Exception:
                    pass
                pick = {
                    'deporte': 'MLB',
                    'partido': f"{CODIGO_A_NOMBRE.get(ac, v['away'])} @ "
                               f"{CODIGO_A_NOMBRE.get(hc, v['home'])}",
                    'fecha': str(pd.to_datetime(v.get('fecha')).date())
                             if v.get('fecha') else str(pd.Timestamp.today().date()),
                    'apuesta': f"Gana {nombre}", 'prob': round(prob, 3),
                    'cuota': round(cuota, 2),
                    'cuota_justa': round(1 / max(prob, 1e-6), 2),
                    'ev': ev_val, 'casa': info.get('casa'),
                    'n_casas': c.get('n_casas'),
                    'calibracion': _info_cal,          # v78

                    'valor': '🟢' if ev_val > 0.05 else '🟡'}
                if gap is not None:
                    pick['sharp_gap'] = round(gap, 4)
                    # v46 GUARDARRAÍL: la confirmación sharp solo cuenta en
                    # picks razonablemente probables (prob≥0.52). En underdogs
                    # el modelo tiende a sobreconfiar y el gap es espurio.
                    pick['sharp_confirmado'] = bool(gap >= 0.03 and prob >= 0.52)
                picks.append(pick)

        if sin_modelo:
            # v84 — se deja de decir «probablemente». Se comprueba.
            #
            # Este aviso llevaba versiones diciendo «probablemente ligas no MLB,
            # como la Liga Mexicana» sobre 33-45 partidos al día. Era una
            # suposición, y descartar a ciegas un tercio de los partidos con
            # precio es tirar información. Comprobado: la API oficial SÍ cubre
            # la Liga Mexicana (leagueId 125, sportId 23, 20 equipos, ~1.000
            # juegos por temporada). Ahora se cuentan por separado.
            _lmb = 0
            try:
                import mlb_statsapi as _msa
                for v in universo.values():
                    if _msa.es_lmb(v.get('home')) or _msa.es_lmb(v.get('away')):
                        _lmb += 1
            except Exception:
                _lmb = 0
            if _lmb:
                incidencias.append(
                    f'Liga Mexicana de Béisbol: {_lmb} partidos con cuota, '
                    f'identificados como LMB (no son un error de mapeo). El '
                    f'modelo de MLB no los cubre —es otra liga— pero la vía de '
                    f'valor de mercado sí puede operarlos, porque no usa modelo.')
            _otros = sin_modelo - _lmb
            if _otros > 0:
                incidencias.append(
                    f'MLB: {_otros} partidos con cuota cuyos equipos no se '
                    f'reconocen ni como MLB ni como Liga Mexicana. Si son '
                    f'recurrentes, hay una liga que falta por mapear.')
        if not universo:
            incidencias.append('ℹ️ MLB: ninguna casa publica partidos ahora mismo '
                               '(fuera de temporada o sin jornada).')

        if evaluados and con_abridor < evaluados:
            incidencias.append(
                f'ℹ️ MLB: {evaluados - con_abridor} de {evaluados} partidos sin '
                f'abridor anunciado todavía; esos se predicen con el lanzador '
                f'neutro y su probabilidad es menos fiable.')

        picks.sort(key=lambda p: (-int(p.get('sharp_confirmado', False)), -p['ev']))
        confianza.sort(key=lambda p: -p['prob'])
        return {'picks': picks, 'eventos': len(universo),
                'confianza': confianza,          # v91
                'evaluados': evaluados, 'con_abridor': con_abridor,
                'incidencias': incidencias,
                'aviso': None if picks else
                'Sin picks MLB con EV suficiente hoy (o fuera de horario de juego).'}

    # ------------------------------------------------------------------
    # v56: PLANTILLA MLB COMPLETA en formato 'secciones' (como fútbol) →
    # habilita el combinador de mercados y el proponedor automático. Todos los
    # mercados se derivan de una MATRIZ DE CARRERAS (dos Poisson por equipo),
    # con la asunción declarada de carreras i.i.d. por entrada para 1er inning
    # y F5 (primeras 5). Los props de jugador se añaden aparte (MLB Stats API).
    # ------------------------------------------------------------------
    def plantilla_club(self, home: str, away: str, **ctx) -> Dict:
        """Alias para reutilizar el motor de parlay del fútbol (que busca
        `plantilla_club`). Devuelve la plantilla MLB en formato 'secciones'."""
        return self.plantilla_mlb(home, away, **ctx)

    def plantilla_mlb(self, home: str, away: str, **ctx) -> Dict:
        from scipy.stats import poisson
        pred = self.predecir(home, away, **ctx)
        if 'error' in pred:
            return pred
        p_home = pred['prob_home']
        total = pred.get('total_estimado') or self.metadata.get('linea_total_tipica', 8.0)
        sigma = float(self.metadata.get('sigma_margen', 4.4))
        from scipy.stats import norm
        mu = sigma * float(norm.ppf(min(max(p_home, 1e-4), 1 - 1e-4)))
        media_h = max((total + mu) / 2, 0.15)          # carreras local
        media_a = max((total - mu) / 2, 0.15)          # carreras visitante
        # v70 (Mejora G): la inversión normal separa demasiado a los dos equipos
        # —λ medias (4.62, 4.29) contra unas carreras reales de (4.43, 4.38)—,
        # el mismo defecto medido en las ligas de fútbol. El encogimiento acerca
        # las dos λ conservando el total; s=0.58 calibrado en walk-forward de 5
        # pliegues sobre 11.844 juegos (desvianza −0.0088, MAE −0.0009).
        # Sin entrada en lambda_shrink.json -> s=1 -> nada cambia.
        try:
            import distributions as _dist
            media_h, media_a = _dist.encoger_lambdas(media_h, media_a, 'mlb')
        except Exception as e:
            logger.debug(f"[mlb] encogimiento omitido: {type(e).__name__}: {e}")
        N = 26
        kk = np.arange(N)
        ph, pa = poisson.pmf(kk, media_h), poisson.pmf(kk, media_a)
        M = np.outer(ph, pa)                            # matriz de carreras
        idx = np.arange(N)
        diff = idx[:, None] - idx[None, :]
        tot = idx[:, None] + idx[None, :]
        pct = lambda x: round(float(x) * 100, 1)

        def campo(id_, etiqueta, valor, tipo='pct'):
            return {'id': id_, 'etiqueta': etiqueta, 'valor': valor, 'tipo': tipo}

        secciones = []
        # 1. Ganador (moneyline, incl. extra innings — sin empates)
        secciones.append({'titulo': '1. Ganador (incl. extra innings)', 'campos': [
            campo('ml_home', f'Gana {home}', pct(p_home)),
            campo('ml_away', f'Gana {away}', pct(1 - p_home)),
        ]})
        # 2. Hándicap de carreras (run line)
        campos_rl = []
        for l in (1.5, 2.5):
            n = int(l + 0.5)
            campos_rl += [
                campo(f'rl_home_-{l}', f'{home} −{l} carreras', pct(M[diff >= n].sum())),
                campo(f'rl_away_+{l}', f'{away} +{l} carreras', pct(M[diff < n].sum())),
                campo(f'rl_away_-{l}', f'{away} −{l} carreras', pct(M[diff <= -n].sum())),
                campo(f'rl_home_+{l}', f'{home} +{l} carreras', pct(M[diff > -n].sum())),
            ]
        secciones.append({'titulo': '2. Hándicap de carreras (run line)', 'campos': campos_rl})
        # 3. Margen de victoria
        secciones.append({'titulo': '3. Margen de victoria', 'campos': [
            campo('mv_home_1', f'{home} gana por 1', pct(M[diff == 1].sum())),
            campo('mv_home_2', f'{home} gana por 2', pct(M[diff == 2].sum())),
            campo('mv_home_3', f'{home} gana por 3+', pct(M[diff >= 3].sum())),
            campo('mv_away_1', f'{away} gana por 1', pct(M[diff == -1].sum())),
            campo('mv_away_2', f'{away} gana por 2', pct(M[diff == -2].sum())),
            campo('mv_away_3', f'{away} gana por 3+', pct(M[diff <= -3].sum())),
        ]})
        # 4. Totales de carreras (partido) + por equipo + par/impar
        campos_t = []
        for l in (7.5, 8.5, 9.5, 10.5):
            po = float(M[tot > l].sum())
            campos_t += [campo(f'over_{l}', f'Más de {l} carreras', pct(po)),
                         campo(f'under_{l}', f'Menos de {l} carreras', pct(1 - po))]
        for lado, m, nombre, pref in (('home', media_h, home, 'tt_home'),
                                      ('away', media_a, away, 'tt_away')):
            for l in (3.5, 4.5, 5.5):
                po = float(1 - poisson.cdf(int(np.floor(l)), m))
                campos_t += [campo(f'{pref}_over_{l}', f'{nombre}: más de {l} carreras', pct(po)),
                             campo(f'{pref}_under_{l}', f'{nombre}: menos de {l} carreras', pct(1 - po))]
        par = float(M[(tot % 2) == 0].sum())
        campos_t += [campo('tot_par', 'Carreras totales PAR', pct(par)),
                     campo('tot_impar', 'Carreras totales IMPAR', pct(1 - par))]
        secciones.append({'titulo': '4. Totales de carreras', 'campos': campos_t})
        # 5. Primeros innings (1er inning y F5) — reparto i.i.d. de carreras
        def _mat(frac):
            lh, la = media_h * frac, media_a * frac
            return np.outer(poisson.pmf(kk, lh), poisson.pmf(kk, la))
        M1 = _mat(1 / 9.0)                 # 1er inning
        M5 = _mat(5 / 9.0)                 # primeras 5 entradas
        d1, t1 = diff, tot
        secciones.append({'titulo': '5. Primeros innings (1er inning y F5)', 'campos': [
            campo('inn1_home', f'1er inning: {home} anota más', pct(M1[d1 > 0].sum())),
            campo('inn1_empate', '1er inning: empate (o 0)', pct(M1[d1 == 0].sum())),
            campo('inn1_away', f'1er inning: {away} anota más', pct(M1[d1 < 0].sum())),
            campo('inn1_over05', '1er inning: más de 0.5 carreras', pct(M1[t1 > 0.5].sum())),
            campo('inn1_under05', '1er inning: menos de 0.5 carreras', pct(M1[t1 <= 0.5].sum())),
            campo('inn1_home_si', f'1er inning: {home} marca', pct(1 - poisson.pmf(0, media_h / 9))),
            campo('inn1_away_si', f'1er inning: {away} marca', pct(1 - poisson.pmf(0, media_a / 9))),
            campo('f5_home', f'F5: gana {home}', pct(M5[diff > 0].sum())),
            campo('f5_empate', 'F5: empate', pct(M5[diff == 0].sum())),
            campo('f5_away', f'F5: gana {away}', pct(M5[diff < 0].sum())),
            campo('f5_over45', 'F5: más de 4.5 carreras', pct(M5[tot > 4.5].sum())),
            campo('f5_under45', 'F5: menos de 4.5 carreras', pct(M5[tot <= 4.5].sum())),
        ]})
        # 6. Extra innings (empate en la regulación de 9)
        p_extra = float(M[diff == 0].sum())
        secciones.append({'titulo': '6. Eventos y extras', 'campos': [
            campo('extra_si', '¿Habrá extra innings?: Sí', pct(p_extra)),
            campo('extra_no', '¿Habrá extra innings?: No', pct(1 - p_extra)),
        ]})
        # 7. Props de pitcher (ponches) — MLB Stats API, bajo demanda/opcional
        if ctx.get('con_props'):
            props = self._props_pitchers(home, away, ctx)
            if props:
                secciones.append({'titulo': '7. Props de jugadores (ponches)',
                                  'campos': props})

        return {
            'partido': f'{home} vs {away}',
            'codigos': {'home': home, 'away': away},
            'liga': 'MLB', 'deporte': 'MLB',
            'fecha': pd.Timestamp.today().strftime('%Y-%m-%d'),
            'secciones': secciones,
            'prediccion_base': pred,
            'observaciones': [
                f"Modelo MLB: precisión de backtesting "
                f"{(self.metadata.get('precision_validacion') or 0)*100:.1f} %.",
                "Mercados derivados de la matriz de carreras (dos Poisson por "
                "equipo). 1er inning y F5 asumen carreras i.i.d. por entrada.",
                "Cuotas mostradas = JUSTAS del modelo (sin margen de casa).",
            ],
        }

    def _props_pitchers(self, home: str, away: str, ctx: Dict) -> list:
        """v56: ponches esperados de los pitchers probables vía MLB Stats API
        (statsapi, gratis, sin clave). On-demand para no ralentizar la vista."""
        try:
            import props_model
            from scipy.stats import poisson
            filas = []
            for pid, nombre in (ctx.get('pitchers') or []):
                k_esp = props_model.strikeouts_esperados(pid) if hasattr(
                    props_model, 'strikeouts_esperados') else None
                if not k_esp:
                    continue
                for l in (4.5, 5.5, 6.5):
                    po = float(1 - poisson.cdf(int(l), k_esp))
                    filas.append({'id': f'k_{pid}_{l}',
                                  'etiqueta': f'{nombre}: más de {l} ponches',
                                  'valor': round(po * 100, 1), 'tipo': 'pct'})
            return filas
        except Exception as e:
            logger.warning(f"[mlb] props pitchers no disponibles: {e}")
            return []


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    print(json.dumps(MLBEngine().entrenar(), indent=2))
