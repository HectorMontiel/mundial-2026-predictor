#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v97 — KBOEngine: la liga coreana de béisbol.

Qué reutiliza y por qué
-----------------------
El béisbol coreano es béisbol: nueve entradas, sin empate salvo reglamento de
liga, y las variables que mandan son las mismas (ELO, carreras anotadas y
concedidas recientes, racha, descanso y sobre todo el ABRIDOR). Así que este
motor **no reimplementa nada**: usa `MLBEngine._dataset` tal cual —es un
`staticmethod` puro sobre un DataFrame— y `kbo_naver` entrega exactamente el
mismo esquema que `mlb_statsapi`.

Eso no es pereza, es la regla de no regresión: cualquier arreglo que se haga
en la construcción de features de béisbol vale para las dos ligas a la vez, y
no hay una segunda copia que se quede atrás en silencio. **No se toca ni una
línea de `mlb_engine`**: el filtro anti-KBO que la v88 puso en
`MLBEngine.apuestas_dia` sigue exactamente igual, y debe seguir — lo que antes
se descartaba por no ser MLB ahora lo recoge este motor por su cuenta.

Diferencias reales de la KBO, y qué se hace con ellas
----------------------------------------------------
  · **Hay empates.** La KBO corta a las 12 entradas en temporada regular, así
    que un 4 % de los juegos acaba en tablas. El clasificador es binario
    («gana el local»), así que los empates **se excluyen del entrenamiento**
    (no se pueden etiquetar) pero se avisa en la ficha: la probabilidad que se
    publica es condicional a que haya ganador, y a cuota de moneyline coreano
    el empate suele devolver la apuesta.
  · **10 equipos, no 30.** Se enfrentan mucho más entre sí, así que el ELO
    converge antes y con menos ruido.
  · **Menos historia de abridores antes de 2017.** Naver empieza a publicar el
    abridor de forma consistente en 2017 y masiva desde 2020. El `_dataset` de
    la MLB ya ignora al abridor sin identificar (v79), así que degrada solo.
"""

import json
import logging
import os
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from engines.base_engine import BaseSportsEngine
from engines.mlb_engine import MLBEngine, _escribir_json

logger = logging.getLogger(__name__)

CARPETA = os.path.join('modelos', 'kbo')
# Primera temporada que se usa para entrenar. 2008 es donde arranca Naver, pero
# la liga tenía 8 equipos hasta 2012 (NC entra en 2013 y KT en 2015): el ELO de
# esos años describe una competición distinta. Se conserva igualmente porque el
# pase cronológico lo absorbe y aporta 3.000 juegos de pasado.
DESDE = 2008

# Cómo llaman a cada equipo las casas. Pinnacle usa el nombre completo en
# inglés; Playdoit abrevia. Se mapea a la forma canónica de `kbo_naver`.
ALIAS_KBO = {
    'hanwha': 'Hanwha Eagles', 'hanwha eagles': 'Hanwha Eagles',
    'kia': 'Kia Tigers', 'kia tigers': 'Kia Tigers', 'kia t': 'Kia Tigers',
    'haitai tigers': 'Kia Tigers',
    'kt': 'KT Wiz', 'kt wiz': 'KT Wiz',
    'lg': 'LG Twins', 'lg twins': 'LG Twins',
    'lotte': 'Lotte Giants', 'lotte giants': 'Lotte Giants',
    'nc': 'NC Dinos', 'nc dinos': 'NC Dinos',
    'doosan': 'Doosan Bears', 'doosan bears': 'Doosan Bears',
    'ssg': 'SSG Landers', 'ssg landers': 'SSG Landers',
    'sk wyverns': 'SSG Landers', 'sk': 'SSG Landers',
    'samsung': 'Samsung Lions', 'samsung lions': 'Samsung Lions',
    'kiwoom': 'Kiwoom Heroes', 'kiwoom heroes': 'Kiwoom Heroes',
    'nexen heroes': 'Kiwoom Heroes', 'woori heroes': 'Kiwoom Heroes',
}


# Columnas de FEATURES que usa el modelo desplegado: DIFF_ELO (0) y
# DIFF_PIT_RA (5), el diferencial de carreras del abridor. Ver el bloque de
# familias en `entrenar` para por qué son sólo dos.
COLS_MODELO = [0, 5]
# v99.1 — el IDF se anade como columna 9 (el vector base tiene 9: 0..8).
# Ventana elegida en walk-forward, no a ojo.
VENTANA_IDF = 10
IDX_IDF = 9
COLS_MODELO_IDF = COLS_MODELO + [IDX_IDF]

# ---------------------------------------------------------------------------
# v116 — LAS FEATURES DEL ABRIDOR, POR FIN INTEGRADAS.
#
# La v105 las adoptó y dejó la integración especificada pero SIN hacer, con un
# motivo que sigue siendo bueno: entrenar con columnas que en producción no
# existen deja el motor sin predicciones, y eso es peor que no tenerlas.
#
# Revalidado antes de tocar nada (`_v104_ab_abridor_kbo_limpio.py`, 2.640
# partidos cruzados, elección en pliegues 0-2 y juicio en 3-5, que no
# participan en la decisión):
#
#     base (ELO)                       log-loss 0,68811 · acierto 54,67 %
#     base + sp_k9, sp_bb9, bullpen_n  log-loss 0,68261 · acierto 56,19 %
#     mejora +0,005500 · p5 +0,000923 · ADOPTAR
#
# Reproduce exactamente la medición de la v105. La auditoría de entonces ya
# descartó el artefacto: con las features PERMUTADAS el p5 es −0,001313, y
# ninguna señal aguanta sola (sólo K9 da p5 −0,000400). Es el bloque el que
# aporta, y por eso entran las tres o ninguna.
#
# Son DIFERENCIALES (local − visitante), así que su valor neutro es 0,0: no
# significa «no sé nada», significa «los dos abridores están igual». Por eso
# rellenar con cero es correcto aquí, y no contradice la nota de la v105 sobre
# no degradar a ceros — esa nota vale para features absolutas.
SENALES_ABRIDOR = ('sp_k9', 'sp_bb9', 'bullpen_n')
# En BB9 menos es mejor, así que se invierte para que «más alto» signifique
# siempre «mejor el local», igual que en el experimento que las validó.
INVERTIR_ABRIDOR = {'sp_bb9'}
IDX_ABRIDOR = [10, 11, 12]
COLS_MODELO_ABR = COLS_MODELO_IDF + IDX_ABRIDOR
CSV_PREVIEW = 'kbo_preview.csv'


def _dif_abridor(fila: Dict) -> List[float]:
    """
    Las tres features del abridor a partir de una fila de preview.

    `fila` puede venir del CSV histórico o del preview en vivo: los dos usan
    los mismos nombres (`home_sp_k9`, `away_bullpen_n`…). Lo que falte sale 0,0
    — el diferencial neutro.
    """
    fuera = []
    for s in SENALES_ABRIDOR:
        try:
            h = float(fila.get(f'home_{s}'))
            a = float(fila.get(f'away_{s}'))
        except (TypeError, ValueError):
            fuera.append(0.0)
            continue
        if h != h or a != a:                     # NaN
            fuera.append(0.0)
            continue
        fuera.append((a - h) if s in INVERTIR_ABRIDOR else (h - a))
    return fuera


class ModeloSubconjunto:
    """
    Envuelve un clasificador para que sólo vea algunas columnas del vector.

    Existe para que `construir_features` siga devolviendo las 9 features de
    siempre —el regresor de totales las usa todas— mientras el clasificador se
    queda con las dos que el walk-forward validó. Está a nivel de módulo, y no
    como lambda o closure, porque tiene que poder serializarse con joblib.
    """

    def __init__(self, base, indices):
        self.base = base
        self.indices = list(indices)

    @property
    def classes_(self):
        return self.base.classes_

    def fit(self, X, y):
        self.base.fit(np.asarray(X)[:, self.indices], y)
        return self

    def predict_proba(self, X):
        return self.base.predict_proba(np.asarray(X)[:, self.indices])

    def predict(self, X):
        return self.base.predict(np.asarray(X)[:, self.indices])


def _norm(nombre: str) -> str:
    import re
    return re.sub(r'[^a-z0-9 ]+', '', str(nombre or '').lower()).strip()


def equipo_kbo(nombre: str) -> str:
    """Nombre de casa -> nombre canónico. Devuelve el crudo si no lo reconoce."""
    n = _norm(nombre)
    if n in ALIAS_KBO:
        return ALIAS_KBO[n]
    for alias, canon in ALIAS_KBO.items():
        # 'ssg landers' contiene 'ssg'; se exige palabra completa para que
        # 'sk' no case dentro de cualquier cosa.
        if alias in n.split() or n.startswith(alias + ' ') or n.endswith(' ' + alias):
            return canon
    return str(nombre or '').strip()


def es_equipo_kbo(nombre: str) -> bool:
    import kbo_naver
    return equipo_kbo(nombre) in kbo_naver.EQUIPOS


def es_partido_kbo(home: str, away: str) -> bool:
    return es_equipo_kbo(home) and es_equipo_kbo(away)


class KBOEngine(BaseSportsEngine):
    def __init__(self):
        super().__init__('KBO', CARPETA)
        self.estado = {}
        ruta = os.path.join(CARPETA, 'estado.json')
        if os.path.exists(ruta):
            with open(ruta, encoding='utf-8') as f:
                self.estado = json.load(f)
        self.equipos = sorted((self.estado.get('equipos') or {}).keys())

    # ---- datos ---------------------------------------------------------
    def cargar_datos_historicos(self) -> pd.DataFrame:
        import kbo_naver
        y = pd.Timestamp.today().year
        return kbo_naver.actualizar(list(range(DESDE, y + 1)))

    @staticmethod
    def _con_idf(X, estado, y):
        """
        v99.1 — añade el Índice de Dispersión de Forma al vector.

        El modelo llevaba ELO y carreras del abridor: poderío de fondo. Lo que
        no tenía es **cuánto se está desviando cada equipo de lo que su propio
        ELO predice**, que es distinto de la forma en bruto — ganar cinco
        seguidos contra los últimos de la liga no es estar en forma.

        Medido contra la cuota de cierre real (113 juegos): el Brier del modelo
        baja de **0,2492 a 0,2476**, o sea que cierra alrededor de un quinto de
        la distancia que le separaba del mercado (0,2411). No le da un edge —
        eso sigue sin estar— pero la probabilidad que se publica es mejor, y es
        la que ve el usuario en la ficha.
        """
        import indice_forma
        ident = pd.DataFrame(estado['filas'], columns=['date', 'home', 'away'])
        ident['date'] = pd.to_datetime(ident['date'])
        # X[:,0] es (elo_local − elo_visitante)/100; basta con recentrarlo,
        # porque el esperado del ELO sólo depende de la diferencia.
        ident['ELO_A'] = 1500.0 + X[:, 0] * 50.0
        ident['ELO_B'] = 1500.0 - X[:, 0] * 50.0
        ident['y'] = y
        tabla = indice_forma.idf_por_participante(
            ident, 'home', 'away', 'ELO_A', 'ELO_B', 'y', ventana=VENTANA_IDF)
        return np.column_stack([X, tabla['DIFF_IDF'].to_numpy()]),             tabla.attrs.get('estado', {})

    @staticmethod
    def _con_abridor(X, estado):
        """
        v116 — añade las tres columnas del abridor, alineadas con las filas.

        Mismo patrón que `_con_idf`: se cruza `estado['filas']` (fecha, local,
        visitante) con `kbo_preview.csv`. Un partido sin preview queda en 0,0,
        que en un diferencial es «los dos abridores igual» — y eso es lo que
        pasa de verdad cuando la fuente no publicó el previo.

        Si el CSV no existe se devuelven ceros y se avisa: el modelo se
        entrenaría con tres columnas constantes, que es inofensivo, pero hay
        que saberlo en vez de descubrirlo por una precisión que no sube.
        """
        ceros = np.zeros((len(X), len(SENALES_ABRIDOR)))
        if not os.path.exists(CSV_PREVIEW):
            logger.warning(f'[kbo] {CSV_PREVIEW} no existe: las features del '
                           f'abridor entran a cero (sin efecto)')
            return np.column_stack([X, ceros]), 0
        try:
            pv = pd.read_csv(CSV_PREVIEW)
        except Exception as e:
            logger.warning(f'[kbo] {CSV_PREVIEW}: {type(e).__name__}: {e}')
            return np.column_stack([X, ceros]), 0
        idx = {}
        for r in pv.to_dict('records'):
            idx[(str(r.get('fecha'))[:10], str(r.get('home_team')),
                 str(r.get('away_team')))] = r
        filas = estado.get('filas') or []
        cols, encontrados = [], 0
        for f in filas:
            clave = (str(pd.Timestamp(f[0]).date()), str(f[1]), str(f[2]))
            r = idx.get(clave)
            if r is None:
                cols.append([0.0] * len(SENALES_ABRIDOR))
                continue
            encontrados += 1
            cols.append(_dif_abridor(r))
        if len(cols) != len(X):
            logger.warning(f'[kbo] abridor: {len(cols)} filas contra {len(X)} '
                           f'del vector; se omite para no desalinear')
            return np.column_stack([X, ceros]), 0
        logger.info(f'[kbo] features de abridor: {encontrados}/{len(X)} '
                    f'partidos con preview')
        return np.column_stack([X, np.asarray(cols, dtype=float)]), encontrados

    @staticmethod
    def _dataset(df: pd.DataFrame):
        """
        Mismo constructor de features que la MLB, con los empates fuera.

        La MLB no tiene empates y la KBO sí: corta a las 12 entradas, así que
        alrededor del 4 % de los juegos acaba en tablas. `MLBEngine._dataset`
        etiqueta `y = home_runs > away_runs`, de modo que un empate entraría
        como 0 — es decir, contado como **derrota del local**, que es falso.
        Sobre 13.009 juegos son ~320 etiquetas mal puestas, y todas en el
        mismo sentido: el modelo aprendería que el local gana menos de lo que
        gana.

        Se filtran antes del pase cronológico. La contrapartida, dicha: el ELO
        tampoco los ve, cuando lo suyo sería sumarlos como medio punto. Se
        acepta porque son el 4 % y porque la alternativa es duplicar el pase
        para que el estado y las etiquetas usen poblaciones distintas —más
        superficie para que las dos versiones diverjan en silencio que error
        corrige. La probabilidad que se publica es, por tanto, **condicional a
        que haya ganador**, y así se dice en la ficha.
        """
        df = df[df['home_runs'] != df['away_runs']].copy()
        return MLBEngine._dataset(df)

    # ---- entrenamiento -------------------------------------------------
    def entrenar(self) -> Dict:
        """
        Entrena el clasificador de la familia que el walk-forward eligió.

        POR QUÉ NO ES EL ENSEMBLE DE LA MLB
        -----------------------------------
        Se probó primero, porque reutilizarlo entero era lo natural. Con un
        corte 80/20 daba 54,35 % frente a un ELO de 53,68 % y parecía bien.
        El walk-forward de 5 pliegues (`_v97_wf_kbo.py`) lo desmintió:

            modelo 0,5426 · ELO 0,5452 · siempre local 0,5240
            ventaja −0,27 pp · bootstrap p5 −1,31 % · gana 2 pliegues de 5
            y peor log-loss que el ELO en 4 de los 5

        O sea que el ensemble **no batía a la línea base**: con 10 equipos que
        se enfrentan sin descanso, el ELO ya captura casi todo y el ensemble
        sólo añadía varianza. Es el mismo diagnóstico que la v70 hizo con las
        ligas de fútbol pequeñas.

        Se barrieron 6 familias (`_v97_familias_kbo.py`) ELIGIENDO por log-loss
        en los pliegues 1-3 y JUZGANDO en el 4-5, que no se miraron para
        decidir (regla de oro 3). Sale **ELO + abridor, logística**:

            juicio (pliegues 4-5)   elo_pitcher_logit  ELO
            precisión                    0,5469        0,5366   (+1,02 pp)
            log-loss                     0,6862          —      (la mejor de las 6)
            bootstrap pareado       p5 −0,28 % · mediana +0,99 % · P(>0) 89,1 %

        `base_logit` sacó 0,5508 en el juicio, un pelo más, pero quedarse con
        ella sería elegir por el pliegue de juicio — la trampa que la v90
        documentó seis veces. La elegida en los pliegues tempranos también
        gana el log-loss en los tardíos, que es la coherencia que se busca.

        El p5 sigue rozando el cero, así que la KBO entra en **Capa 2
        (informativa)**, no en Capa 1: batir al ELO habilita el modelo, pero
        un edge de APUESTA exige ROI validado contra cuota de cierre y de la
        KBO no hay histórico de cierre. Se acumulará con los snapshots
        diarios, igual que las 11 ligas de fútbol de la v90.
        """
        from sklearn.ensemble import HistGradientBoostingRegressor
        from sklearn.linear_model import LogisticRegression
        from sklearn.metrics import accuracy_score, log_loss
        from sklearn.preprocessing import StandardScaler
        import joblib

        df = self.cargar_datos_historicos()
        X, y, tot, fechas, estado = self._dataset(df)
        logger.info(f'[kbo] dataset: {len(X)} juegos utilizables')
        if len(X) < 500:
            return {'error': f'KBO: sólo {len(X)} juegos utilizables.'}

        # v99.1: el vector crece con el IDF (ver `_con_idf`), y el estado por
        # equipo se guarda para poder reproducirlo en inferencia.
        X, estado_idf = self._con_idf(X, estado, y)
        # v116: y las tres del abridor (ver `_con_abridor` para la validación)
        X, n_prev = self._con_abridor(X, estado)
        estado['abridor_previews'] = int(n_prev)
        estado['idf'] = estado_idf

        corte = fechas.quantile(0.80)
        m_tr = (fechas < corte).values
        sc = StandardScaler().fit(X[m_tr])
        Xtr, Xva = sc.transform(X[m_tr]), sc.transform(X[~m_tr])

        modelo = ModeloSubconjunto(LogisticRegression(max_iter=2000),
                                   COLS_MODELO_ABR).fit(Xtr, y[m_tr])
        proba = modelo.predict_proba(Xva)[:, list(modelo.classes_).index(1)]
        acc = accuracy_score(y[~m_tr], (proba >= 0.5).astype(int))
        ll = log_loss(y[~m_tr], np.column_stack([1 - proba, proba]))
        # Línea base: el ELO a secas (columna 0), que es el criterio con el que
        # el proyecto decide si una competición nueva merece desplegarse.
        base = accuracy_score(y[~m_tr], (X[~m_tr][:, 0] > 0).astype(int))
        # Segunda línea base, más honesta todavía: «gana siempre el local».
        base_local = float(y[~m_tr].mean())

        reg = HistGradientBoostingRegressor(loss='poisson', max_iter=300,
                                            learning_rate=0.05, max_depth=5,
                                            random_state=42).fit(Xtr, tot[m_tr])

        os.makedirs(CARPETA, exist_ok=True)
        joblib.dump(modelo, os.path.join(CARPETA, 'moneyline.joblib'), compress=3)
        joblib.dump(sc, os.path.join(CARPETA, 'scaler.joblib'), compress=3)
        joblib.dump(reg, os.path.join(CARPETA, 'totales.joblib'), compress=3)
        _escribir_json(os.path.join(CARPETA, 'estado.json'), estado)

        ruta_meta = os.path.join(CARPETA, 'metadata.json')
        meta = {}
        if os.path.exists(ruta_meta):
            try:
                with open(ruta_meta, encoding='utf-8') as f:
                    meta = json.load(f)
            except Exception:
                meta = {}
        # σ del margen de carreras, MEDIDA en la KBO y no heredada.
        # `plantilla_mlb` cae a 4,4 si falta, que es el valor de la MLB; el
        # béisbol coreano anota más (total típico 9,9 frente a 8,5), así que
        # heredar el de la MLB estrecharía hándicaps y totales por equipo.
        # Sólo con juegos ANTERIORES al corte de validación: medirla con todo
        # el histórico metería el futuro en un parámetro de la ficha.
        antes = df[(df['date'] < corte) & (df['home_runs'] != df['away_runs'])]
        sigma_margen = float((antes['home_runs'] - antes['away_runs']).std())

        meta.update({'deporte': 'KBO', 'n_juegos': int(len(X)),
                     'sigma_margen': round(sigma_margen, 3),
                     'familia': 'elo_pitcher_logit',
                     'columnas_modelo': COLS_MODELO_ABR,
                     'ventana_idf': VENTANA_IDF,
                     'precision_validacion': round(float(acc), 4),
                     'precision_linea_base_elo': round(float(base), 4),
                     'precision_linea_base_local': round(float(base_local), 4),
                     'log_loss_validacion': round(float(ll), 4),
                     'linea_total_tipica': float(np.median(tot)),
                     'validacion_desde': str(pd.Timestamp(corte).date()),
                     # v116 — ESTOS NÚMEROS SON DE LA v97, NO DE ESTE MODELO.
                     #
                     # Están escritos a mano desde entonces y el entrenamiento
                     # NO los recalcula, así que el metadata venía diciendo
                     # «lo que de verdad autoriza a desplegar» sobre una
                     # medición de otra versión del modelo. Se detectó al
                     # integrar las features del abridor: el bloque salió
                     # idéntico al del modelo anterior, cifra por cifra, con
                     # las columnas ya cambiadas.
                     #
                     # No se borra —la medición existió y es la del ELO contra
                     # el clasificador base— pero se etiqueta con su origen
                     # para que nadie la lea como si fuera de hoy.
                     'walk_forward': {
                         'precision': 0.5469, 'precision_elo': 0.5366,
                         'ventaja': 0.0102, 'bootstrap_p5': -0.0028,
                         'prob_ventaja_positiva': 0.891,
                         'pliegues_juicio': [4, 5],
                         'medido_en': 'v97 (_v97_wf_kbo.py)',
                         'corresponde_a': 'el clasificador SIN IDF ni abridor',
                         'aviso': ('valor histórico fijo: el entrenamiento no '
                                   'lo recalcula. No describe al modelo '
                                   'actual.')},
                     # v116 — la validación que SÍ corresponde a las features
                     # del abridor, con protocolo de elegir/juzgar separados
                     # (`_v104_ab_abridor_kbo_limpio.py`, 2.640 partidos, 792
                     # en juicio). Permutando las features el p5 cae a
                     # −0,001313, así que no es un artefacto.
                     'validacion_abridor': {
                         'features': list(SENALES_ABRIDOR),
                         'log_loss_base': 0.68811, 'log_loss_con': 0.68261,
                         'acierto_base': 0.5467, 'acierto_con': 0.5619,
                         'mejora': 0.005500, 'bootstrap_p5': 0.000923,
                         'juzgados': 792,
                         'partidos_con_preview': int(n_prev)},
                     'capa': 2,
                     'motivo_capa2': ('bate al ELO pero no hay cuota de cierre '
                                      'histórica de KBO con la que validar ROI'),
                     'fecha_entrenamiento':
                         pd.Timestamp.today().strftime('%Y-%m-%d')})
        with open(ruta_meta, 'w', encoding='utf-8') as f:
            json.dump(meta, f, indent=2, ensure_ascii=False)
        logger.info(f'[kbo] acc={acc:.4f} (ELO {base:.4f} · local {base_local:.4f}) '
                    f'll={ll:.4f}')
        return meta

    # ---- inferencia ----------------------------------------------------
    def construir_features(self, home: str, away: str,
                           home_pitcher: str = None,
                           away_pitcher: str = None,
                           fecha=None, **ctx) -> Optional[List[float]]:
        """
        El vector de la MLB, MÁS el IDF (v99.1).

        El clasificador desplegado mira las columnas [0, 5, 9]; si aquí se
        devolvieran sólo las 9 de la MLB (índices 0-8), pediría una que no
        existe. El IDF se reconstruye del estado que dejó el entrenamiento —
        las últimas desviaciones de cada equipo respecto a lo que su ELO
        predecía— y cae a 0 (neutro, «rinde como se espera») si un equipo no
        tiene historial, que es exactamente lo que significa no saber nada.
        """
        base = MLBEngine.construir_features(
            self, home, away, home_pitcher=home_pitcher,
            away_pitcher=away_pitcher, fecha=fecha, **ctx)
        if base is None:
            return None
        idf = self.estado.get('idf') or {}
        ih = idf.get(home) or []
        ia = idf.get(away) or []
        v_h = float(np.mean(ih[-VENTANA_IDF:])) if ih else 0.0
        v_a = float(np.mean(ia[-VENTANA_IDF:])) if ia else 0.0
        # v116 — LAS TRES DEL ABRIDOR, RESUELTAS EN INFERENCIA.
        #
        # Éste es el paso que la v105 identificó como imprescindible y por el
        # que no integró: si el modelo se entrena con estas columnas y aquí no
        # se devuelven, el vector tiene 10 posiciones y el clasificador pide la
        # 12 — `IndexError`, y la KBO se queda sin predicciones enteras.
        #
        # Se piden al preview del partido, que `kbo_preview` ya cachea en
        # disco. Si la fuente no responde, o el partido aún no tiene abridores
        # anunciados (lo normal hasta unas horas antes), quedan en 0,0: en un
        # diferencial eso es «los dos abridores igual», que es exactamente lo
        # que significa no saber quién abre. Nunca lanza: una fuente caída deja
        # el motor prediciendo como antes de la v116, no lo tumba.
        return list(base) + [v_h - v_a] + self._abridor_en_vivo(
            home, away, fecha, ctx.get('game_id'))

    def _abridor_en_vivo(self, home: str, away: str, fecha=None,
                         game_id: Optional[str] = None) -> List[float]:
        """Features del abridor para un partido que aún no se ha jugado."""
        neutro = [0.0] * len(SENALES_ABRIDOR)
        try:
            import kbo_preview
        except Exception:
            return neutro
        try:
            gid = game_id
            if not gid:
                import kbo_naver
                dia = (pd.Timestamp(fecha).strftime('%Y-%m-%d') if fecha
                       else pd.Timestamp.today().strftime('%Y-%m-%d'))
                for p in (kbo_naver.partidos_del_dia(dia) or []):
                    if (equipo_kbo(p.get('home')) == home
                            and equipo_kbo(p.get('away')) == away):
                        gid = p.get('game_id')
                        break
            if not gid:
                return neutro
            pv = kbo_preview.preview(str(gid))
            if not pv:
                return neutro
            # `preview` devuelve el JSON crudo de la fuente; `fila` es la que
            # lo aplana a las mismas columnas que tiene el CSV histórico, que
            # es lo que `_dif_abridor` sabe leer. Usar el crudo daría 0,0
            # siempre y la integración no serviría de nada — en silencio.
            return _dif_abridor(kbo_preview.fila(str(gid), pv))
        except Exception as e:
            logger.debug(f'[kbo] abridor en vivo no disponible: '
                         f'{type(e).__name__}: {e}')
            return neutro

    def refrescar_estado(self, df: Optional[pd.DataFrame] = None) -> Dict:
        """Recalcula `estado.json` sin reentrenar (mismo motivo que en v79)."""
        if df is None:
            df = self.cargar_datos_historicos()
        if df is None or df.empty:
            return {'error': 'sin datos históricos'}
        _X, _y, _t, _f, estado = self._dataset(df)
        # v99.1: el estado del IDF se refresca junto al resto. Si no, el
        # `estado.json` de producción tendría ELO al día y un IDF congelado
        # en el último entrenamiento — que es peor que no tenerlo, porque no
        # se nota.
        try:
            _X, estado['idf'] = self._con_idf(_X, estado, _y)
            _X, _np = self._con_abridor(_X, estado)
            estado['abridor_previews'] = int(_np)
        except Exception as e:
            logger.warning(f'[kbo] IDF no recalculado: {type(e).__name__}: {e}')
        os.makedirs(CARPETA, exist_ok=True)
        _escribir_json(os.path.join(CARPETA, 'estado.json'), estado)
        self.estado = estado
        self.equipos = sorted((estado.get('equipos') or {}).keys())
        fechas = [v.get('ult_fecha') for v in estado['equipos'].values()
                  if v.get('ult_fecha')]
        ultima = max(fechas) if fechas else None
        logger.info(f"[kbo] estado refrescado: {len(estado['equipos'])} equipos, "
                    f"{len(estado['pitchers'])} lanzadores, último {ultima}")
        return {'equipos': len(estado['equipos']),
                'pitchers': len(estado['pitchers']),
                'ultimo_partido': ultima, 'juegos': int(len(_X))}

    # ---- barrido del día -----------------------------------------------
    def apuestas_dia(self, min_prob: float = 0.58, min_ev: float = 0.03,
                     min_cuota: float = 1.50, max_req: int = 1) -> Dict:
        """
        Picks de KBO sobre el MISMO tablón de béisbol que ya se descarga.

        No cuesta ni una petición extra: `cuotas_multi` ya trae el tablón de
        «mlb» entero —donde vienen MLB, NPB, KBO, CPBL y Triple-A— y la v88 lo
        filtraba a MLB. Aquí se recoge justo la parte que aquel filtro
        descarta. Medido el 2026-08-04: Pinnacle publica 5 partidos de KBO
        («Korea Professional Baseball») y Playdoit otros 5 («Liga KBO»).
        """
        if not self.listo:
            return {'picks': [], 'aviso': 'Modelo KBO no disponible.',
                    'incidencias': ['KBO: el modelo no está entrenado.']}
        try:
            import cuotas_multi as cm
        except Exception as e:
            return {'picks': [], 'aviso': f'Capa de cuotas no disponible: {e}',
                    'incidencias': [f'KBO: capa de cuotas no disponible ({e}).']}

        from engines.mlb_engine import _fecha_dia
        incidencias, confianza = [], []
        try:
            cm.precargar('mlb')
        except Exception as e:
            incidencias.append(f'KBO: precarga de cuotas con avisos ({e}).')

        universo = {}
        for idx in (cm._indice('mlb'), cm._indice_bov('mlb'), cm._indice_pdt('mlb')):
            for v in (idx or {}).values():
                if not (v.get('home') and v.get('away')):
                    continue
                if not es_partido_kbo(v['home'], v['away']):
                    continue
                clave = (equipo_kbo(v['home']), equipo_kbo(v['away']))
                universo.setdefault(clave, v)

        # Abridores anunciados de hoy (la variable más predictiva del béisbol).
        abridores = {}
        try:
            import kbo_naver
            for p in kbo_naver.partidos_del_dia():
                abridores[(p['home'], p['away'])] = (p['home_pitcher'],
                                                     p['away_pitcher'])
        except Exception as e:
            incidencias.append(f'KBO: abridores del día no disponibles ({e}); '
                               f'se predice sin ellos.')

        picks, evaluados, sin_modelo, con_abridor = [], 0, 0, 0
        for (hc, ac), v in universo.items():
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
            # Mismo encogimiento hacia el mercado que la MLB (v78/v79). Se pasa
            # 'mlb' como clave de calibración a propósito: la KBO todavía no
            # tiene peso medido propio y `calibracion_segura` cae al w por
            # defecto; usar el de béisbol es más honesto que inventar uno.
            import calibracion_segura as _cal
            _ph, _info_cal = _cal.encoger_dos_vias(
                pred['prob_home'],
                (mejor.get('home') or {}).get('cuota'),
                (mejor.get('away') or {}).get('cuota'), 'mlb')
            for lado, prob in (('home', _ph), ('away', 1.0 - _ph)):
                info = mejor.get(lado)
                if not info or not info.get('cuota'):
                    continue
                cuota = float(info['cuota'])
                ev_val = self.calcular_ev(prob, cuota)
                nombre = hc if lado == 'home' else ac
                if not (prob > min_prob and ev_val > min_ev and cuota > min_cuota):
                    if prob >= 0.60 and cuota > 1.0:
                        confianza.append({
                            'deporte': 'KBO', 'liga': 'KBO', 'clave_liga': 'kbo',
                            'partido': f'{ac} @ {hc}',
                            'fecha': _fecha_dia(v.get('fecha')),
                            # v106: el ISO entero, con hora, en UTC. La
                            # conversión a CDMX es de presentación.
                            'inicio': v.get('fecha'),
                            'mercado': 'Moneyline',
                            'apuesta': f'Gana {nombre}',
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
                gap = None
                try:
                    gap = cm.sharp_gap_2via(prob, pin.get(lado), pin.get(otro))
                except Exception:
                    pass
                pick = {
                    'deporte': 'KBO', 'liga': 'KBO', 'clave_liga': 'kbo',
                    'partido': f'{ac} @ {hc}',
                    'fecha': _fecha_dia(v.get('fecha')),
                    'inicio': v.get('fecha'),          # v106: ISO con hora, UTC
                    'apuesta': f'Gana {nombre}', 'prob': round(prob, 3),
                    'cuota': round(cuota, 2),
                    'cuota_justa': round(1 / max(prob, 1e-6), 2),
                    'ev': ev_val, 'casa': info.get('casa'),
                    'n_casas': c.get('n_casas'), 'calibracion': _info_cal,
                    'valor': '🟢' if ev_val > 0.05 else '🟡'}
                if gap is not None:
                    pick['sharp_gap'] = round(gap, 4)
                    pick['sharp_confirmado'] = bool(gap >= 0.03 and prob >= 0.52)
                picks.append(pick)

        if not universo:
            incidencias.append('ℹ️ KBO: ninguna casa publica partidos ahora mismo '
                               '(la temporada va de marzo a octubre).')
        if sin_modelo:
            incidencias.append(
                f'KBO: {sin_modelo} partidos con cuota cuyos equipos no están '
                f'en el estado del modelo.')
        if evaluados and con_abridor < evaluados:
            incidencias.append(
                f'ℹ️ KBO: {evaluados - con_abridor} de {evaluados} partidos sin '
                f'abridor anunciado todavía; se predicen con el lanzador neutro.')

        picks.sort(key=lambda p: (-int(p.get('sharp_confirmado', False)), -p['ev']))
        confianza.sort(key=lambda p: -p['prob'])
        return {'picks': picks, 'eventos': len(universo),
                'confianza': confianza, 'evaluados': evaluados,
                'con_abridor': con_abridor, 'incidencias': incidencias,
                'aviso': None if picks else
                'Sin picks KBO con EV suficiente hoy.'}

    # ---- ficha de partido ----------------------------------------------
    def plantilla_club(self, home: str, away: str, **ctx) -> Dict:
        return self.plantilla_kbo(home, away, **ctx)

    def plantilla_kbo(self, home: str, away: str, **ctx) -> Dict:
        """
        Ficha en formato 'secciones', reutilizando la de la MLB.

        La matriz de carreras, los mercados derivados (moneyline, total,
        hándicap de carreras, F5, primera entrada) y su semántica son
        idénticos; lo único que cambia es la liga que se anuncia y el aviso del
        empate, que en la MLB no existe.
        """
        pl = MLBEngine.plantilla_mlb(self, home, away, **ctx)
        if isinstance(pl, dict) and 'error' not in pl:
            pl['deporte'] = 'KBO'
            pl['liga'] = 'KBO League'
            pl['nota_empate'] = (
                'La KBO corta a las 12 entradas: alrededor del 4 % de los '
                'juegos acaba en empate. La probabilidad que se muestra es la '
                'de ganar A CONDICIÓN de que haya ganador; en el moneyline '
                'coreano el empate suele devolver la apuesta.')
        return pl


if __name__ == '__main__':
    import argparse
    import sys
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    sys.stdout.reconfigure(encoding='utf-8')
    ap = argparse.ArgumentParser()
    ap.add_argument('--solo-estado', action='store_true')
    a = ap.parse_args()
    # Se entrena con la clase IMPORTADA, no con la de `__main__`.
    #
    # `ModeloSubconjunto` viaja dentro del pickle por su ruta completa. Si se
    # entrena ejecutando este fichero, joblib la sella como
    # `__main__.ModeloSubconjunto` y al cargarla desde la app —donde `__main__`
    # es Streamlit— salta `AttributeError` y el motor queda «no cargado» sin
    # más explicación. Pasó de verdad la primera vez que se entrenó.
    from engines.kbo_engine import KBOEngine as _KBOEngine
    m = _KBOEngine()
    if a.solo_estado:
        print(json.dumps(m.refrescar_estado(), ensure_ascii=False, indent=1))
    else:
        print(json.dumps(m.entrenar(), ensure_ascii=False, indent=1))
