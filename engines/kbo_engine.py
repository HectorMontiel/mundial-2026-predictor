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

        corte = fechas.quantile(0.80)
        m_tr = (fechas < corte).values
        sc = StandardScaler().fit(X[m_tr])
        Xtr, Xva = sc.transform(X[m_tr]), sc.transform(X[~m_tr])

        modelo = ModeloSubconjunto(LogisticRegression(max_iter=2000),
                                   COLS_MODELO).fit(Xtr, y[m_tr])
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
                     'columnas_modelo': COLS_MODELO,
                     'precision_validacion': round(float(acc), 4),
                     'precision_linea_base_elo': round(float(base), 4),
                     'precision_linea_base_local': round(float(base_local), 4),
                     'log_loss_validacion': round(float(ll), 4),
                     'linea_total_tipica': float(np.median(tot)),
                     'validacion_desde': str(pd.Timestamp(corte).date()),
                     # Lo que de verdad autoriza a desplegar: walk-forward de 5
                     # pliegues, elección en 1-3 y juicio en 4-5.
                     'walk_forward': {
                         'precision': 0.5469, 'precision_elo': 0.5366,
                         'ventaja': 0.0102, 'bootstrap_p5': -0.0028,
                         'prob_ventaja_positiva': 0.891,
                         'pliegues_juicio': [4, 5]},
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
        """Idéntica a la de la MLB: mismo vector, mismo orden, mismo estado."""
        return MLBEngine.construir_features(
            self, home, away, home_pitcher=home_pitcher,
            away_pitcher=away_pitcher, fecha=fecha, **ctx)

    def refrescar_estado(self, df: Optional[pd.DataFrame] = None) -> Dict:
        """Recalcula `estado.json` sin reentrenar (mismo motivo que en v79)."""
        if df is None:
            df = self.cargar_datos_historicos()
        if df is None or df.empty:
            return {'error': 'sin datos históricos'}
        _X, _y, _t, _f, estado = self._dataset(df)
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
