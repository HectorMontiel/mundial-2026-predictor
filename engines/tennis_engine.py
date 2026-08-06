#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TennisEngine (v30 §5, ampliado en v35 §1) — ATP **y WTA**.

Fuentes (Kaggle, sin credenciales, actualizadas a diario):
  · ATP → dissfya/atp-tennis-2000-2023daily-pull (68.3k partidos 2000-2026)
  · WTA → dissfya/wta-tennis-2007-2023-daily-update (45.1k partidos
    2006-2026) — MISMAS columnas que el ATP, incluidas Odd_1/Odd_2 con
    100 % de cobertura, así que el circuito femenino también se valida
    contra el MERCADO y no solo contra el ranking.
Ambos con superficie, tipo de pista (Indoor/Outdoor), ranking, puntos y
marcador. Binario: gana Player_1 sí/no.

CHALLENGERS (v35 §1.2): NO se incorporan. El dataset de Challengers del
mismo autor devuelve 403 (privado) y el único mirror gratuito con
categorías inferiores (ehallmar/a-large-tennis-dataset...) está congelado
en 2018 → serviría para inflar el volumen de entrenamiento con partidos de
hace 8 años, no para predecir los de hoy. Documentado en VALIDACION_v35.md.

Features v35 (todas cronológicas, sin fuga):
  · ELO POR SUPERFICIE, ahora con pista INDOOR como superficie propia
    (hard_indoor ≠ hard): el bote y la ausencia de viento cambian el juego.
  · ELO global, ranking (log) y PUNTOS de ranking (log).
  · Forma últimos 10 y % de victorias en la superficie a 12 meses.
  · FATIGA: días desde el último partido, partidos en 14 días y horas en
    pista en 7 días (estimadas del marcador: ~3.75 min por juego).
  · H2H acumulado.
SAQUE Y RESTO (v69): RESUELTO. La fuente de Kaggle sigue sin publicar aces
ni puntos de saque, pero `tenis_saque.py` los obtiene de los logs de
TennisAbstract (esquema Sackmann verificado al 99.9 %). Eso habilita
DIFF_ELO_SAQUE, DIFF_SPW y DIFF_RPW. Si el CSV de saque no está, las tres
features caen a su valor neutro y el modelo se comporta como en v68.
"""

import json
import logging
import os
import re
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from engines.base_engine import BaseSportsEngine

logger = logging.getLogger(__name__)

CIRCUITOS = {
    # 'features': conjunto ADOPTADO tras el walk-forward de 5 temporadas
    # (run_wf_tenis_v35.py). En el ATP las features nuevas suben +0.25 pp
    # (64.98→65.23) — por debajo del umbral de 0.3 pp y con el log-loss
    # plano (+0.0005) → NO se adoptan y el circuito masculino conserva su
    # vector v30. En la WTA mejoran precisión Y log-loss (65.34→65.57,
    # 0.6164→0.6137) → adoptadas.
    'atp': {'carpeta': os.path.join('modelos', 'tennis'),
            'dataset': 'dissfya/atp-tennis-2000-2023daily-pull',
            'archivo': 'atp_tennis.csv', 'etiqueta': 'Tenis (ATP)',
            'features': None},          # None → FEATURES_V30 (ver abajo)
    # La WTA sí adoptó el vector completo de v35 (10 features).
    # v67: se declara EXPLÍCITAMENTE. Antes se derivaba de "si la clave
    # 'features' no está, usa FEATURES", y al ampliar FEATURES con las de nivel
    # el circuito femenino habría pasado de 10 a 13 columnas sin reentrenar —
    # el modelo guardado habría reventado en el primer arranque.
    'wta': {'carpeta': os.path.join('modelos', 'tennis_wta'),
            'dataset': 'dissfya/wta-tennis-2007-2023-daily-update',
            'archivo': 'wta.csv', 'etiqueta': 'Tenis (WTA)',
            'features': None},          # None → se resuelve más abajo
}
# Vector por defecto de cada circuito cuando `metadata.json` no dice otra cosa.
#
# v79 — LA WTA PASA A FEATURES_V67 (13 features, con contexto de nivel).
#
# Las features de nivel se midieron en la v67 y se DESCARTARON, y las de saque
# en la v69 también. Aquellas decisiones se tomaron antes de que existiera el
# walk-forward con cuota real, así que se volvieron a medir las cinco variantes
# en los dos circuitos con el mismo protocolo y el mismo estimador
# (`_v79_tenis_features.py`, 5 vectores × 2 circuitos × 5 pliegues).
#
# El primer A/B dijo «adoptar» en los dos circuitos, y era un espejismo: el
# umbral (Δ log-loss > 0,001) lo había fijado yo a ojo y las dos ganancias
# caían justo encima. Con 10 combinaciones probadas, quedarse con la mejor y
# llamarlo mejora es el error de comparaciones múltiples que este proyecto ya
# evitó en la v33 (ELO ataque/defensa) y en la v35 (CDI en UECL).
#
# Lo que decide es un BOOTSTRAP PAREADO sobre la diferencia de log-loss partido
# a partido (`_v79_tenis_significancia.py`, 5.000 remuestreos), pareado porque
# los dos vectores predicen los MISMOS partidos y así se cancela la varianza
# compartida:
#
#     ATP  V30 -> V69-WTA   Δ +0,00088   IC90 [+0,00000, +0,00180]
#                            95,1 % positivo   p1 Bonferroni −0,00037  -> NO
#     WTA  V35 -> V67       Δ +0,00108   IC90 [+0,00066, +0,00149]
#                           100,0 % positivo   p1 Bonferroni +0,00047  -> SÍ
#
# El ATP no sobrevive: su intervalo toca el cero y tras corregir por las cinco
# variantes queda en negativo. La WTA sí: 5.000 de 5.000 remuestreos positivos.
# Precisión WTA 0,6390 -> 0,6428 (+0,38 pp).
#
# OJO: cambiar esto OBLIGA a reentrenar la WTA. El modelo guardado espera 10
# columnas y pasaría a recibir 13 — es exactamente el aviso que dejó la v67.
# v99.2 — el vector de producción incorpora el IDF en los DOS circuitos.
#
# Medido con el `_dataset` del propio motor, o sea exactamente lo que se
# despliega, y ENCIMA del vector que ya llevaba `DIFF_FORMA10`:
#
#   ATP (352.679 partidos)  log-loss 0,60296 -> 0,60199 · acc 0,6680 -> 0,6690
#                           n=105.804 · p5 +0,00072 · P(mejora>0) 100,0 %
#   WTA (315.657 partidos)  log-loss 0,50653 -> 0,50624 · acc 0,7475 -> 0,7476
#                           n=94.698  · p5 +0,00015 · P(mejora>0) 100,0 %
#
# Bootstrap PAREADO sobre la diferencia partido a partido. Las ganancias son
# pequeñas pero el p5 es POSITIVO en los dos circuitos por separado, y la
# precisión no baja en ninguno — que son las dos condiciones que el proyecto
# exige desde la v26 para adoptar una feature.
# v101: WTA pasa a `FEATURES_V101_WTA` — el mismo vector sin las tres features
# de fatiga, que con el archivo ITF (fecha única por torneo) filtraban el avance
# en el propio torneo. El porqué y los números, junto a su definición más abajo.
FEATURES_POR_DEFECTO = {'atp': 'FEATURES_V992_ATP', 'wta': 'FEATURES_V101_WTA'}
CARPETA = CIRCUITOS['atp']['carpeta']          # compatibilidad v30-v34
DATASET = CIRCUITOS['atp']['dataset']
FEATURES = ['DIFF_ELO_SUP', 'DIFF_ELO_GLOBAL', 'DIFF_RANK_LOG',
            'DIFF_FORMA10', 'DIFF_WIN_SUP_12M', 'H2H',
            'DIFF_PTS_LOG', 'DIFF_DIAS_DESCANSO', 'DIFF_PARTIDOS_14D',
            'DIFF_HORAS_7D',
            # --- v67: contexto de NIVEL de competición -----------------
            # El universo pasa de "circuito principal" a incluir previas,
            # Challenger, WTA 125 e ITF. Un jugador no rinde igual en un
            # Grand Slam que en un ITF, y el ELO global no lo distingue.
            'DIFF_ELO_NIVEL',      # ELO específico del nivel del partido
            'NIVEL_PARTIDO',       # nivel absoluto (contexto, no diferencia)
            'DIFF_EXP_NIVEL',      # experiencia previa en ese nivel
            # --- v69: SAQUE Y RESTO ------------------------------------
            # Hasta v68 esto era imposible: ninguna fuente gratuita publicaba
            # aces ni puntos de saque desde que desaparecieron los repos de
            # Sackmann. `tenis_saque.py` lo resuelve con los logs de
            # TennisAbstract. Son las tres señales clásicas del tenis:
            'DIFF_ELO_SAQUE',      # ELO calculado sobre % de puntos ganados al saque
            'DIFF_SPW',            # % de puntos ganados con su saque (rolling)
            'DIFF_RPW',            # % de puntos ganados al resto (rolling)
            # --- v99.2: INDICE DE DISPERSION DE FORMA -------------------
            # `DIFF_FORMA10` ya dice cuantos gano de los ultimos 10. Lo que
            # NO decia es contra QUIEN: ganar 6 de 10 a rivales flojos no es
            # estar en forma. El IDF descuenta la dificultad del calendario —
            # es la media de (resultado - lo que el ELO esperaba). Validado en
            # la v99.1 sobre 108.657 partidos con cuota de cierre: p5 +0,00064
            # (ATP) y +0,00091 (WTA) de mejora de log-loss, P(>0)=100 % en los
            # dos, y la ganancia se TRIPLICA en el decil de forma extrema.
            # VA AL FINAL A PROPOSITO: los `FEATURES[:n]` de arriba son slices
            # y anadir en medio desplazaria los indices de todos los modelos
            # ya guardados (el aviso que dejo la v67).
            'DIFF_IDF']
FEATURES_V30 = FEATURES[:6]                    # para el A/B de la v35
FEATURES_V35 = FEATURES[:10]                   # producción hasta v66
FEATURES_V67 = FEATURES[:13]                   # candidato v67 (descartado)
FEATURES_SAQUE = FEATURES[13:16]               # las tres de v69
FEATURES_IDF = ['DIFF_IDF']                    # v99.2
# Ventana elegida en walk-forward en la v99.1 (5, 10 y 15 medidas; gana 5
# en los DOS circuitos por separado, que es lo que da confianza).
VENTANA_IDF = 5
# Candidato v69: el vector de producción de cada circuito + saque/resto. NO
# incluye las de nivel (v67), que se midieron y degradaban.
FEATURES_V69_ATP = FEATURES_V30 + FEATURES_SAQUE
FEATURES_V69_WTA = FEATURES_V35 + FEATURES_SAQUE
# v99.2: lo desplegado hasta ahora + el IDF (ver FEATURES_POR_DEFECTO).
FEATURES_V992_ATP = FEATURES_V30 + FEATURES_IDF
FEATURES_V992_WTA = FEATURES_V67 + FEATURES_IDF

# --- v101: LAS FEATURES DE FATIGA SALEN DEL VECTOR DE WTA -------------------
#
# `DIFF_DIAS_DESCANSO`, `DIFF_PARTIDOS_14D` y `DIFF_HORAS_7D` se calculan a
# partir de las FECHAS de los partidos anteriores. Desde la v96/v97 el histórico
# incorpora el archivo ITF, que hoy es el 82 % de las filas — y ese archivo
# guarda todos los partidos de un torneo con UNA SOLA FECHA (mediana: 1,0
# fechas distintas por torneo; el 35,9 % de los pares jugadora-fecha tienen dos
# o más partidos ese día).
#
# Con fecha única, «partidos en los últimos 14 días» deja de medir calendario y
# pasa a medir cuánto avanzó en ESE MISMO torneo, que es el resultado que se
# está prediciendo. Medido con las tres features SOLAS, sin modelo:
#
#     filas kaggle (fechas reales) → log-loss 0,6936 · acierto 53,7 %
#     filas ITF   (fecha única)    → log-loss 0,5412 · acierto 73,6 %
#
# Mismo código, misma feature: la diferencia es la granularidad de la fecha.
#
# El coste no era sólo un backtest inflado. Evaluando el vector desplegado sólo
# sobre filas con fecha real —lo que se parece a producción— QUITARLAS mejora:
#
#     log-loss 0,67515 → 0,63262   (IC90 [−0,0473, −0,0378], entero negativo)
#     acierto  62,18 % → 64,26 %
#
# Es decir: inflaban el backtest en +7,7 pp de acierto y restaban 2,1 pp de
# acierto real. ATP no está afectado — su vector es FEATURES[:6] + IDF y nunca
# las llevó. Medido en `_v101_fuga_fatiga_wta.py`.
FEATURES_FATIGA = ('DIFF_DIAS_DESCANSO', 'DIFF_PARTIDOS_14D', 'DIFF_HORAS_7D')
FEATURES_V101_WTA = [f for f in FEATURES_V67
                     if f not in FEATURES_FATIGA] + FEATURES_IDF

# Nivel numérico de competición (0 = más bajo). Se usa como contexto y para el
# ELO por nivel. Las claves son las de `Series`/`Tier` de la fuente y las
# categorías de `tenis_fuentes`.
NIVELES = {
    'itf_w': 0.0, 'itf_m': 0.0,
    'challenger_atp': 1.0, 'wta_125': 1.0, 'wta125': 1.0,
    'atp250': 3.0, 'international': 3.0, 'wta250': 3.0,
    'atp500': 4.0, 'international gold': 4.0, 'wta500': 4.0,
    'masters 1000': 5.0, 'masters': 5.0, 'masters cup': 5.5, 'wta1000': 5.0,
    'premier': 4.0, 'premier 5': 5.0, 'premier mandatory': 5.0,
    'grand slam': 6.0,
}
NIVEL_POR_DEFECTO = 3.0
NIVEL_CLASIFICACION = 2.0      # la previa está entre Challenger y ATP250


def nivel_partido(series=None, categoria=None, fase=None) -> float:
    """Nivel numérico del partido. `Fase` manda: una previa de Grand Slam se
    juega entre jugadores de rango Challenger, no de Grand Slam."""
    if str(fase) == 'clasificacion':
        return NIVEL_CLASIFICACION
    for clave in (str(series or '').strip().lower(), str(categoria or '').strip().lower()):
        if clave in NIVELES:
            return NIVELES[clave]
        if clave.startswith('gs_'):
            return NIVELES['grand slam']
        if clave in ('atp_tour', 'wta_tour'):
            return NIVEL_POR_DEFECTO
    return NIVEL_POR_DEFECTO
SUP = {'Clay': 'clay', 'Hard': 'hard', 'Grass': 'grass',
       'Carpet': 'hard', 'Indoor': 'hard', 'Greenset': 'hard'}
MIN_POR_JUEGO = 3.75 / 60.0                    # horas por juego disputado


_CACHE_SAQUE: Dict[str, dict] = {}


def _ck(nombre: str) -> str:
    try:
        import tenis_fuentes as tf
        return tf.clave_jugador(nombre)
    except Exception:
        return str(nombre).lower()


# TennisAbstract fecha los partidos por el INICIO DEL TORNEO, no por el día en
# que se jugaron: todo Wimbledon comparte una sola fecha. Enlazar por fecha
# exacta hacía casar apenas el 4.2 % de los partidos y dejaba las features de
# saque en su valor neutro el 96 % de las veces —parecían no aportar nada
# cuando en realidad casi nunca se rellenaban—. Se enlaza por PAREJA de
# jugadores y se resuelve la fecha con una ventana.
VENTANA_SAQUE_DIAS = 21


def _clave_pareja(p1: str, p2: str) -> str:
    """Clave simétrica SOLO de la pareja, con los nombres normalizados."""
    try:
        import tenis_fuentes as tf
        a, b = tf.clave_jugador(p1), tf.clave_jugador(p2)
    except Exception:
        a, b = str(p1).lower(), str(p2).lower()
    return '|'.join(sorted((a, b)))


def _buscar_saque(indice, fecha, p1: str, p2: str):
    """Estadística del cruce más cercano en el tiempo dentro de la ventana."""
    entradas = indice.get(_clave_pareja(p1, p2))
    if not entradas:
        return None
    objetivo = pd.Timestamp(fecha)
    mejor, dmin = None, None
    for f, stats in entradas:
        d = abs((objetivo - f).days)
        if d <= VENTANA_SAQUE_DIAS and (dmin is None or d < dmin):
            mejor, dmin = stats, d
    return mejor


def _indice_saque(df: pd.DataFrame) -> Dict[str, list]:
    """
    Estadística de saque por partido, indexada por clave simétrica.

    Se lee de `saque_{circuito}.csv` (lo genera `tenis_saque.py` desde
    TennisAbstract). Si el fichero no existe, devuelve {} y las features de
    saque se quedan en su valor neutro — degradación limpia, el modelo sigue
    funcionando exactamente como antes.
    """
    import os
    salida: Dict[str, dict] = {}
    for circuito in ('atp', 'wta'):
        # Se prefiere el .gz (1.9 MB vs 6.9 MB en ATP, 1.4 vs 27.3 en WTA);
        # pandas lo lee igual. El .csv plano sigue valiendo si está.
        ruta = next((r for r in (f'saque_{circuito}.csv.gz', f'saque_{circuito}.csv')
                     if os.path.exists(r)), f'saque_{circuito}.csv')
        if ruta in _CACHE_SAQUE:
            salida.update(_CACHE_SAQUE[ruta])
            continue
        if not os.path.exists(ruta):
            _CACHE_SAQUE[ruta] = {}
            continue
        try:
            import tenis_fuentes as tf
            d = pd.read_csv(ruta, parse_dates=['fecha'])
        except Exception:
            _CACHE_SAQUE[ruta] = {}
            continue
        idx: Dict[str, list] = {}
        for r in d.itertuples(index=False):
            k = _clave_pareja(r.jugador, r.rival)
            # OJO: la clave interna es `clave_jugador` (sin tildes, guiones ni
            # mayúsculas). TennisAbstract escribe "Auger Aliassime" y Kaggle
            # "Auger-Aliassime": indexar por el nombre tal cual perdería esos
            # partidos en silencio.
            idx.setdefault(k, []).append((pd.Timestamp(r.fecha), {
                tf.clave_jugador(r.jugador): {
                    'svpt': int(r.svpt or 0),
                    'primeros_gan': int(r.primeros_gan or 0),
                    'segundos_gan': int(r.segundos_gan or 0)},
                tf.clave_jugador(r.rival): {
                    'svpt': int(getattr(r, 'riv_svpt', 0) or 0),
                    'primeros_gan': int(getattr(r, 'riv_primeros_gan', 0) or 0),
                    'segundos_gan': int(getattr(r, 'riv_segundos_gan', 0) or 0)},
            }))
        _CACHE_SAQUE[ruta] = idx
        salida.update(idx)
        logger.info(f"[tenis] estadística de saque: {len(idx)} partidos de {ruta}")
    return salida


def _juegos_del_marcador(score) -> float:
    """Juegos totales del partido a partir del marcador ('6-4 7-6(3)' → 23).
    Si no es parseable, se asume un partido medio (21 juegos)."""
    if not isinstance(score, str) or not score.strip():
        return 21.0
    total = 0
    for a, b in re.findall(r'(\d+)-(\d+)', score.replace('(', ' (')):
        ja, jb = int(a), int(b)
        if ja <= 7 and jb <= 7:                # descarta tie-breaks (7-3 sí, 10-8 no)
            total += ja + jb
    return float(total) if total else 21.0


class TennisEngine(BaseSportsEngine):
    def __init__(self, circuito: str = 'atp'):
        cfg = CIRCUITOS[circuito]
        self.circuito = circuito
        self.cfg = cfg
        super().__init__(cfg['etiqueta'], cfg['carpeta'])
        # Conjunto de features ADOPTADO por circuito (run_wf_tenis_v35.py);
        # se fija tras la validación walk-forward, no por defecto.
        self.features = list(cfg.get('features')
                             or globals()[FEATURES_POR_DEFECTO.get(circuito, 'FEATURES_V30')])
        self.estado = {}
        ruta = os.path.join(cfg['carpeta'], 'estado.json')
        if os.path.exists(ruta):
            with open(ruta, encoding='utf-8') as f:
                self.estado = json.load(f)
        self.jugadores = sorted((self.estado.get('jugadores') or {}).keys())

    def cargar_datos_historicos(self, unificado: Optional[bool] = None) -> pd.DataFrame:
        """
        `unificado=True` (v67) usa `tenis_fuentes.historico_unificado`: Kaggle
        + tennis-data.co.uk (nivel de la WTA y cuotas de más casas) + ESPN
        (fases previas y las categorías inferiores que publica). `False`
        conserva exactamente el camino de v35-v66 (solo Kaggle).
        Por defecto se lee de `MUNDIAL_TENIS_UNIFICADO` para poder hacer el A/B
        sin tocar código.
        """
        # v67: el histórico unificado pasa a ser el DEFECTO. Walk-forward de 5
        # temporadas con el mismo conjunto de test (run_wf_tenis_v67.py):
        #   ATP  base 0.6557/0.6154 → datos 0.6559/0.6154  (empate técnico)
        #   WTA  base 0.6585/0.6129 → datos 0.6597/0.6121  (mejora ambas)
        # No degrada y añade cobertura que antes no existía (previas,
        # Challenger, WTA 125, ITF). Con MUNDIAL_TENIS_UNIFICADO=0 se vuelve al
        # comportamiento de v66 (solo Kaggle) sin tocar código.
        if unificado is None:
            unificado = os.getenv('MUNDIAL_TENIS_UNIFICADO', '1') != '0'
        if unificado:
            try:
                import tenis_fuentes
                df = tenis_fuentes.historico_unificado(self.circuito)
                return self._preparar(df)
            except Exception as e:
                logger.warning(f"[tenis/{self.circuito}] histórico unificado no "
                               f"disponible ({type(e).__name__}: {e}); se usa Kaggle.")
        import kagglehub
        p = kagglehub.dataset_download(self.cfg['dataset'])
        df = pd.read_csv(os.path.join(p, self.cfg['archivo']),
                         parse_dates=['Date'], low_memory=False)
        return self._preparar(df)

    @staticmethod
    def _preparar(df: pd.DataFrame) -> pd.DataFrame:
        for c in ('Rank_1', 'Rank_2', 'Pts_1', 'Pts_2', 'Odd_1', 'Odd_2'):
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors='coerce')
        base = df['Surface'].map(lambda s: SUP.get(str(s), 'hard'))
        indoor = df.get('Court', pd.Series(['Outdoor'] * len(df))).astype(str) \
            .str.lower().eq('indoor')
        # v35: la pista cubierta es una superficie propia (ELO_INDOOR)
        df['sup'] = np.where(indoor, base + '_indoor', base)
        df['juegos'] = df.get('Score', pd.Series([None] * len(df))).map(_juegos_del_marcador)
        if 'Best of' in df.columns:
            df['bo'] = pd.to_numeric(df['Best of'], errors='coerce').fillna(3)
        else:
            df['bo'] = 3
        df = df.dropna(subset=['Date', 'Player_1', 'Player_2', 'Winner'])
        return df.sort_values('Date')

    @staticmethod
    def _dataset(df: pd.DataFrame, features: Optional[List[str]] = None):
        elo_g: Dict[str, float] = {}
        elo_s: Dict[str, Dict[str, float]] = {}
        forma: Dict[str, list] = {}
        win_sup: Dict[str, list] = {}     # (fecha, ganó) por superficie
        h2h: Dict[tuple, int] = {}
        agenda: Dict[str, list] = {}      # v35: (fecha, juegos) por jugador
        elo_n: Dict[str, Dict[float, float]] = {}   # v67: ELO por nivel
        exp_n: Dict[str, Dict[float, int]] = {}     # v67: partidos por nivel
        # v69: saque/resto. `spw`/`rpw` son ventanas de los últimos 20 partidos
        # con estadística; `elo_sv` es un ELO alimentado por el % de puntos
        # ganados al saque frente al % que el rival concede al resto.
        spw: Dict[str, list] = {}
        rpw: Dict[str, list] = {}
        elo_sv: Dict[str, float] = {}
        # v99.2: desviaciones (resultado - esperado por ELO) por jugador
        idf_h: Dict[str, list] = {}
        saque = _indice_saque(df)
        features = features or FEATURES
        idx = [FEATURES.index(f) for f in features]
        tiene_nivel = ('Series' in df.columns or 'Categoria' in df.columns
                       or 'Fase' in df.columns)
        X, y, fechas, odds = [], [], [], []
        # v67: procedencia y contexto de CADA fila utilizable. Va dentro de
        # `estado` para no cambiar la firma de retorno (run_wf_tenis_v35.py la
        # desempaqueta como 5-tupla).
        filas_meta: List[tuple] = []
        for r in df.itertuples(index=False):
            p1, p2, sup = r.Player_1, r.Player_2, r.sup
            eg1, eg2 = elo_g.get(p1, 1500.0), elo_g.get(p2, 1500.0)
            es1 = elo_s.get(p1, {}).get(sup, 1500.0)
            es2 = elo_s.get(p2, {}).get(sup, 1500.0)
            f1 = np.mean(forma.get(p1, [])[-10:]) if forma.get(p1) else 0.5
            f2 = np.mean(forma.get(p2, [])[-10:]) if forma.get(p2) else 0.5
            def _ws(p):
                v = [g for (d, s, g) in win_sup.get(p, [])
                     if s == sup and (r.Date - d).days <= 365]
                return np.mean(v) if v else 0.5
            ws1, ws2 = _ws(p1), _ws(p2)
            hk = tuple(sorted((p1, p2)))
            hb = h2h.get(hk, 0) * (1 if hk[0] == p1 else -1)
            r1 = float(r.Rank_1) if np.isfinite(r.Rank_1 or np.nan) and r.Rank_1 > 0 else 500
            r2 = float(r.Rank_2) if np.isfinite(r.Rank_2 or np.nan) and r.Rank_2 > 0 else 500
            pt1 = float(getattr(r, 'Pts_1', np.nan) or np.nan)
            pt2 = float(getattr(r, 'Pts_2', np.nan) or np.nan)
            pt1 = pt1 if np.isfinite(pt1) and pt1 > 0 else 100.0
            pt2 = pt2 if np.isfinite(pt2) and pt2 > 0 else 100.0

            # --- fatiga (v35 §1.3), estrictamente con partidos ANTERIORES ---
            def _fatiga(p):
                hist = agenda.get(p)
                if not hist:
                    return 21.0, 0.0, 0.0
                dias = min((r.Date - hist[-1][0]).days, 21)
                p14 = sum(1 for d, _ in hist if 0 <= (r.Date - d).days <= 14)
                h7 = sum(j for d, j in hist if 0 <= (r.Date - d).days <= 7) * MIN_POR_JUEGO
                return float(dias), float(p14), float(h7)

            d1, n1, h1 = _fatiga(p1)
            d2, n2, h2_ = _fatiga(p2)
            gano1 = int(r.Winner == p1)

            # --- v67: nivel de competición (contexto y ELO por nivel) -------
            niv = nivel_partido(getattr(r, 'Series', None),
                                getattr(r, 'Categoria', None),
                                getattr(r, 'Fase', None)) if tiene_nivel else NIVEL_POR_DEFECTO
            en1 = elo_n.get(p1, {}).get(niv, eg1)   # sin historia en el nivel
            en2 = elo_n.get(p2, {}).get(niv, eg2)   # -> arranca del ELO global
            ex1 = exp_n.get(p1, {}).get(niv, 0)
            ex2 = exp_n.get(p2, {}).get(niv, 0)

            # --- v69: saque y resto (estado PREVIO al partido) --------------
            sv1 = float(np.mean(spw.get(p1, [])[-20:])) if spw.get(p1) else 0.62
            sv2 = float(np.mean(spw.get(p2, [])[-20:])) if spw.get(p2) else 0.62
            rt1 = float(np.mean(rpw.get(p1, [])[-20:])) if rpw.get(p1) else 0.38
            rt2 = float(np.mean(rpw.get(p2, [])[-20:])) if rpw.get(p2) else 0.38
            ev1, ev2 = elo_sv.get(p1, 1500.0), elo_sv.get(p2, 1500.0)

            # --- v99.2: IDF (estado PREVIO; se actualiza mas abajo) ---
            i1 = float(np.mean(idf_h.get(p1, [])[-VENTANA_IDF:])) if idf_h.get(p1) else 0.0
            i2 = float(np.mean(idf_h.get(p2, [])[-VENTANA_IDF:])) if idf_h.get(p2) else 0.0

            if p1 in elo_g and p2 in elo_g:   # ambos con historial
                completo = [(es1 - es2) / 100.0, (eg1 - eg2) / 100.0,
                            (np.log(r2) - np.log(r1)) / 3.0, f1 - f2,
                            ws1 - ws2, float(np.clip(hb, -5, 5)) / 5.0,
                            (np.log(pt1) - np.log(pt2)) / 5.0,
                            (d1 - d2) / 21.0, (n1 - n2) / 8.0, (h1 - h2_) / 10.0,
                            (en1 - en2) / 100.0, niv / 6.0,
                            (np.log1p(ex1) - np.log1p(ex2)) / 5.0,
                            (ev1 - ev2) / 100.0, (sv1 - sv2) * 5.0, (rt1 - rt2) * 5.0,
                            # v99.2: DIFF_IDF, escalado como el resto
                            (i1 - i2) * 2.0]
                X.append([completo[i] for i in idx])
                y.append(gano1)
                fechas.append(r.Date)
                odds.append((getattr(r, 'Odd_1', None), getattr(r, 'Odd_2', None)))
                filas_meta.append((getattr(r, 'Fuente', 'kaggle'),
                                   getattr(r, 'Categoria', None),
                                   getattr(r, 'Fase', 'cuadro_principal'), niv))
            # actualizar (sin fuga)
            exp1 = 1 / (1 + 10 ** ((eg2 - eg1) / 400))
            # v99.2: la desviacion de ESTE partido respecto a lo esperado.
            # Se registra DESPUES de haber emitido la fila: sin fuga.
            idf_h.setdefault(p1, []).append(gano1 - exp1)
            idf_h.setdefault(p2, []).append((1 - gano1) - (1 - exp1))
            for _p in (p1, p2):
                if len(idf_h[_p]) > VENTANA_IDF * 3:
                    idf_h[_p] = idf_h[_p][-VENTANA_IDF * 3:]
            elo_g[p1] = eg1 + 32 * (gano1 - exp1)
            elo_g[p2] = eg2 + 32 * ((1 - gano1) - (1 - exp1))
            exps = 1 / (1 + 10 ** ((es2 - es1) / 400))
            elo_s.setdefault(p1, {})[sup] = es1 + 32 * (gano1 - exps)
            elo_s.setdefault(p2, {})[sup] = es2 + 32 * ((1 - gano1) - (1 - exps))
            # v67: ELO y experiencia por NIVEL de competición
            expn = 1 / (1 + 10 ** ((en2 - en1) / 400))
            elo_n.setdefault(p1, {})[niv] = en1 + 32 * (gano1 - expn)
            elo_n.setdefault(p2, {})[niv] = en2 + 32 * ((1 - gano1) - (1 - expn))
            exp_n.setdefault(p1, {})[niv] = ex1 + 1
            exp_n.setdefault(p2, {})[niv] = ex2 + 1

            # v69: actualizar saque/resto con la estadística REAL del partido,
            # si TennisAbstract la tiene. Se hace DESPUÉS de haber leído el
            # estado previo, así que no hay fuga.
            est = _buscar_saque(saque, r.Date, p1, p2)
            if est:
                s1, s2 = est.get(_ck(p1)), est.get(_ck(p2))
                if s1 and s2 and s1['svpt'] > 0 and s2['svpt'] > 0:
                    g1 = (s1['primeros_gan'] + s1['segundos_gan']) / s1['svpt']
                    g2 = (s2['primeros_gan'] + s2['segundos_gan']) / s2['svpt']
                    spw.setdefault(p1, []).append(g1)
                    spw.setdefault(p2, []).append(g2)
                    rpw.setdefault(p1, []).append(1.0 - g2)   # lo que le quitó al rival
                    rpw.setdefault(p2, []).append(1.0 - g1)
                    for lista in (spw, rpw):
                        for p in (p1, p2):
                            if len(lista.get(p, [])) > 40:
                                lista[p] = lista[p][-40:]
                    # ELO de saque: "gana" quien defendió mejor su servicio
                    esp = 1 / (1 + 10 ** ((ev2 - ev1) / 400))
                    real = 1.0 if g1 > g2 else (0.5 if abs(g1 - g2) < 1e-9 else 0.0)
                    elo_sv[p1] = ev1 + 24 * (real - esp)
                    elo_sv[p2] = ev2 + 24 * ((1 - real) - (1 - esp))
            forma.setdefault(p1, []).append(gano1)
            forma.setdefault(p2, []).append(1 - gano1)
            win_sup.setdefault(p1, []).append((r.Date, sup, gano1))
            win_sup.setdefault(p2, []).append((r.Date, sup, 1 - gano1))
            h2h[hk] = h2h.get(hk, 0) + (1 if r.Winner == hk[0] else -1)
            juegos = float(getattr(r, 'juegos', 21.0) or 21.0)
            for p in (p1, p2):
                agenda.setdefault(p, []).append((r.Date, juegos))
                if len(agenda[p]) > 30:
                    agenda[p] = agenda[p][-30:]
        estado = {'jugadores': {}, 'filas_meta': filas_meta}
        ultima = pd.Timestamp(df['Date'].max())
        for p in elo_g:
            hist = agenda.get(p, [])
            estado['jugadores'][p] = {
                'elo': round(elo_g[p], 1),
                'elo_sup': {k: round(v, 1) for k, v in elo_s.get(p, {}).items()},
                # v67: ELO y partidos por nivel de competición
                'elo_nivel': {str(k): round(v, 1) for k, v in elo_n.get(p, {}).items()},
                'exp_nivel': {str(k): int(v) for k, v in exp_n.get(p, {}).items()},
                # v69: estado de saque/resto a la fecha de corte
                'elo_saque': round(elo_sv.get(p, 1500.0), 1),
                'spw': round(float(np.mean(spw.get(p, [])[-20:])), 4) if spw.get(p) else None,
                'rpw': round(float(np.mean(rpw.get(p, [])[-20:])), 4) if rpw.get(p) else None,
                'n_saque': len(spw.get(p, [])),
                'forma': [int(x) for x in forma.get(p, [])[-10:]],
                # v99.2: IDF a la fecha de corte (para la inferencia)
                'idf': round(float(np.mean(idf_h.get(p, [])[-VENTANA_IDF:])), 5)
                        if idf_h.get(p) else 0.0,
                'rank': None, 'pts': None,
                # v35: estado de fatiga a la fecha de corte del dataset
                'ultimo_partido': hist[-1][0].strftime('%Y-%m-%d') if hist else None,
                'partidos_14d': sum(1 for d, _ in hist if (ultima - d).days <= 14),
                'horas_7d': round(sum(j for d, j in hist
                                      if (ultima - d).days <= 7) * MIN_POR_JUEGO, 2),
            }
        # ranking más reciente por jugador
        for r in df.itertuples(index=False):
            for jugador, rank, pts in ((r.Player_1, r.Rank_1, getattr(r, 'Pts_1', None)),
                                       (r.Player_2, r.Rank_2, getattr(r, 'Pts_2', None))):
                e = estado['jugadores'].get(jugador)
                if e is None:
                    continue
                if rank and np.isfinite(rank):
                    e['rank'] = float(rank)
                if pts and np.isfinite(pts):
                    e['pts'] = float(pts)
        estado['h2h'] = {f'{a}|{b}': v for (a, b), v in h2h.items() if v != 0}
        return (np.array(X), np.array(y), pd.Series(fechas),
                np.array(odds, dtype=float), estado)

    def entrenar(self) -> Dict:
        from sklearn.calibration import CalibratedClassifierCV
        from sklearn.ensemble import RandomForestClassifier, VotingClassifier
        from sklearn.metrics import accuracy_score, log_loss
        from sklearn.preprocessing import StandardScaler
        from lightgbm import LGBMClassifier
        from xgboost import XGBClassifier

        df = self.cargar_datos_historicos()
        cols = self.features
        X, y, fechas, odds, estado = self._dataset(df, cols)
        logger.info(f"[tenis] dataset: {len(X)} partidos")
        corte = fechas.quantile(0.80)
        m_tr = (fechas < corte).values
        sc = StandardScaler().fit(X[m_tr])
        vc = VotingClassifier([
            ('xgb', XGBClassifier(n_estimators=200, max_depth=4, learning_rate=0.05, verbosity=0)),
            ('lgbm', LGBMClassifier(n_estimators=200, max_depth=4, learning_rate=0.05, verbose=-1)),
            ('rf', RandomForestClassifier(n_estimators=200, max_depth=8, random_state=42))],
            voting='soft')
        modelo = CalibratedClassifierCV(vc, method='isotonic', cv=3).fit(
            sc.transform(X[m_tr]), y[m_tr])
        proba = modelo.predict_proba(sc.transform(X[~m_tr]))[:, list(modelo.classes_).index(1)]
        acc = accuracy_score(y[~m_tr], (proba >= 0.5).astype(int))
        ll = log_loss(y[~m_tr], np.column_stack([1 - proba, proba]))
        # baseline mercado: favorito por cuota (menor odd)
        o = odds[~m_tr]
        mask = np.isfinite(o).all(axis=1)
        acc_mkt = accuracy_score(y[~m_tr][mask],
                                 (o[mask][:, 0] < o[mask][:, 1]).astype(int)) \
            if mask.sum() > 50 else None
        base = accuracy_score(y[~m_tr], (X[~m_tr][:, 0] > 0).astype(int))

        # v67 — MÉTRICA COMPARABLE. Al unificar fuentes, la validación pasa a
        # incluir previas, Challenger, WTA 125 e ITF, que son intrínsecamente
        # menos predecibles. La precisión GLOBAL deja de ser comparable con la
        # de v66 (mismo problema que el universo de selecciones en fútbol), así
        # que se reporta también restringida al CIRCUITO PRINCIPAL, que es el
        # universo con el que se validó hasta ahora.
        meta = estado.get('filas_meta') or []
        sub = {}
        if len(meta) == len(y):
            fuente_fila = np.array([m[0] for m in meta])
            for etiqueta, mascara in (
                    ('circuito_principal', fuente_fila == 'kaggle'),
                    ('categorias_nuevas', fuente_fila != 'kaggle')):
                m = mascara & ~m_tr
                if m.sum() < 50:
                    sub[etiqueta] = {'n': int(m.sum())}
                    continue
                p_s = modelo.predict_proba(sc.transform(X[m]))[:, list(modelo.classes_).index(1)]
                sub[etiqueta] = {
                    'n': int(m.sum()),
                    'precision': round(float(accuracy_score(y[m], (p_s >= 0.5).astype(int))), 4),
                    'log_loss': round(float(log_loss(y[m], np.column_stack([1 - p_s, p_s]),
                                                     labels=[0, 1])), 4)}
            logger.info(f"[tenis/{self.circuito}] desglose: " +
                        ' · '.join(f"{k} n={v['n']} acc={v.get('precision')}"
                                   for k, v in sub.items()))

        carpeta = self.cfg['carpeta']
        os.makedirs(carpeta, exist_ok=True)
        import joblib
        joblib.dump(modelo, os.path.join(carpeta, 'moneyline.joblib'), compress=3)
        joblib.dump(sc, os.path.join(carpeta, 'scaler.joblib'), compress=3)
        # `filas_meta` es un diagnóstico del A/B (una entrada por partido): no
        # se persiste, engordaría estado.json en decenas de miles de filas.
        estado_persistente = {k: v for k, v in estado.items() if k != 'filas_meta'}
        with open(os.path.join(carpeta, 'estado.json'), 'w', encoding='utf-8') as f:
            json.dump(estado_persistente, f)
        previa = {}
        ruta_meta = os.path.join(carpeta, 'metadata.json')
        if os.path.exists(ruta_meta):
            with open(ruta_meta, encoding='utf-8') as f:
                previa = json.load(f)          # conserva coef_juegos/sigmas v32
        meta = {**previa,
                'deporte': self.cfg['etiqueta'], 'circuito': self.circuito,
                'features': cols, 'n_partidos': len(X),
                'precision_validacion': round(float(acc), 4),
                'validacion_por_universo': sub,
                'fuente_datos': ('unificado (Kaggle + tennis-data + ESPN)'
                                 if 'Fuente' in df.columns and
                                 (df['Fuente'] != 'kaggle').any() else 'kaggle'),
                'precision_linea_base_elo': round(float(base), 4),
                'precision_mercado': round(float(acc_mkt), 4) if acc_mkt else None,
                'log_loss_validacion': round(float(ll), 4),
                'modo': 'analitico (sin cuotas en vivo gratis)',
                'fecha_entrenamiento': pd.Timestamp.today().strftime('%Y-%m-%d')}
        with open(ruta_meta, 'w', encoding='utf-8') as f:
            json.dump(meta, f, indent=2)
        logger.info(f"[tenis/{self.circuito}] acc={acc:.4f} "
                    f"(ELO {base:.4f}, mercado {acc_mkt}) ll={ll:.4f}")
        return meta

    def construir_features(self, home: str, away: str, surface: str = 'hard',
                           indoor: bool = False, categoria: Optional[str] = None,
                           fase: Optional[str] = None, **ctx) -> Optional[List[float]]:
        jug = self.estado.get('jugadores', {})
        if home not in jug or away not in jug:
            return None
        p1, p2 = jug[home], jug[away]
        sup = SUP.get(str(surface).capitalize(), str(surface).lower())
        clave_sup = f'{sup}_indoor' if indoor else sup

        def _elo_sup(e):
            # ELO de la superficie exacta → de la misma superficie al aire
            # libre → ELO global (cadena de fallback explícita)
            return e['elo_sup'].get(clave_sup, e['elo_sup'].get(sup, e['elo']))

        es1, es2 = _elo_sup(p1), _elo_sup(p2)
        f1 = np.mean(p1['forma']) if p1['forma'] else 0.5
        f2 = np.mean(p2['forma']) if p2['forma'] else 0.5
        r1 = p1.get('rank') or 500
        r2 = p2.get('rank') or 500
        hk = '|'.join(sorted((home, away)))
        hb = self.estado.get('h2h', {}).get(hk, 0)
        hb = hb if hk.split('|')[0] == home else -hb
        def _pts(e):
            v = e.get('pts')
            # OJO: NaN es "truthy" → un `or` no lo filtra (bug cazado en v35)
            return float(v) if v is not None and np.isfinite(v) and v > 0 else 100.0

        pt1, pt2 = _pts(p1), _pts(p2)

        # fatiga: el estado guarda la foto a la fecha de corte del dataset; los
        # días de descanso se recalculan contra HOY (lo único que sí avanza).
        hoy = pd.Timestamp.today().normalize()

        def _dias(e):
            f = e.get('ultimo_partido')
            return min((hoy - pd.Timestamp(f)).days, 21) if f else 21.0

        # v67: nivel del partido para el ELO por nivel (mismo cálculo que en
        # entrenamiento: `Fase` manda sobre la categoría).
        niv = nivel_partido(None, categoria, fase)

        def _elo_niv(e, elo_global):
            return (e.get('elo_nivel') or {}).get(str(niv), elo_global)

        def _exp_niv(e):
            return (e.get('exp_nivel') or {}).get(str(niv), 0)

        en1, en2 = _elo_niv(p1, p1['elo']), _elo_niv(p2, p2['elo'])

        cols = (self.metadata.get('features')
                or globals()[FEATURES_POR_DEFECTO.get(self.circuito, 'FEATURES_V30')])
        completo = {
            'DIFF_ELO_SUP': (es1 - es2) / 100.0,
            'DIFF_ELO_GLOBAL': (p1['elo'] - p2['elo']) / 100.0,
            'DIFF_RANK_LOG': (np.log(r2) - np.log(r1)) / 3.0,
            'DIFF_FORMA10': f1 - f2,
            'DIFF_WIN_SUP_12M': 0.0,
            'H2H': float(np.clip(hb, -5, 5)) / 5.0,
            'DIFF_PTS_LOG': (np.log(pt1) - np.log(pt2)) / 5.0,
            'DIFF_DIAS_DESCANSO': (_dias(p1) - _dias(p2)) / 21.0,
            'DIFF_PARTIDOS_14D': (p1.get('partidos_14d', 0)
                                  - p2.get('partidos_14d', 0)) / 8.0,
            'DIFF_HORAS_7D': (p1.get('horas_7d', 0.0)
                              - p2.get('horas_7d', 0.0)) / 10.0,
            'DIFF_ELO_NIVEL': (en1 - en2) / 100.0,
            'NIVEL_PARTIDO': niv / 6.0,
            'DIFF_EXP_NIVEL': (np.log1p(_exp_niv(p1)) - np.log1p(_exp_niv(p2))) / 5.0,
            # v69 — saque y resto. Mismos valores neutros que en entrenamiento
            # (0.62 al saque, 0.38 al resto) cuando no hay datos del jugador.
            'DIFF_ELO_SAQUE': ((p1.get('elo_saque') or 1500.0)
                               - (p2.get('elo_saque') or 1500.0)) / 100.0,
            'DIFF_SPW': ((p1.get('spw') or 0.62) - (p2.get('spw') or 0.62)) * 5.0,
            'DIFF_RPW': ((p1.get('rpw') or 0.38) - (p2.get('rpw') or 0.38)) * 5.0,
            # v99.2 — IDF. 0.0 es el valor NEUTRO y significa exactamente
            # «rinde como su ELO predice», que es lo correcto cuando no hay
            # historial: no se inventa ni crisis ni pico de forma.
            'DIFF_IDF': ((p1.get('idf') or 0.0) - (p2.get('idf') or 0.0)) * 2.0,
        }
        return [completo[c] for c in cols]


    def con_contexto(self, surface: str = 'Hard', best_of: int = 3,
                     indoor: bool = False, categoria: Optional[str] = None,
                     fase: Optional[str] = None):
        """
        Devuelve una vista del motor con el contexto del partido YA FIJADO.

        `match_parlay` llama a `motor.plantilla(home, away)` sin más argumentos
        (es agnóstico del deporte), así que sin esto el parlay de tenis se
        calculaba siempre sobre pista dura y al mejor de 3 — aunque el usuario
        hubiese elegido hierba y cinco sets. Con la vista, las combinadas usan
        exactamente el mismo contexto que la tabla de mercados.
        """
        motor = self

        class _VistaConContexto:
            def __init__(self):
                # se delega todo lo demás en el motor real
                self.__dict__['_motor'] = motor

            def __getattr__(self, nombre):
                return getattr(motor, nombre)

            def plantilla(self, home, away, **kw):
                kw.setdefault('surface', surface)
                kw.setdefault('best_of', best_of)
                kw.setdefault('indoor', indoor)
                kw.setdefault('categoria', categoria)
                kw.setdefault('fase', fase)
                return motor.plantilla(home, away, **kw)

            def predecir(self, home, away, **kw):
                kw.setdefault('surface', surface)
                kw.setdefault('indoor', indoor)
                kw.setdefault('categoria', categoria)
                kw.setdefault('fase', fase)
                return motor.predecir(home, away, **kw)

        return _VistaConContexto()

    # ------------------------------------------------------------------
    # v32 (§8.1): plantilla de tenis con RESTRICCIÓN MATEMÁTICA ESTRICTA.
    # Solo lo derivable: ganador (clasificador), total de juegos y hándicap
    # (regresión de juegos calibrada sobre 68k partidos) y reparto de sets
    # bajo independencia condicional (asunción declarada, no inventada).
    # EXCLUIDOS: marcador exacto de sets, «set a cero» y ganador del primer
    # set — exigen cadenas de Markov / datos de saque que NO tenemos.
    # ------------------------------------------------------------------
    def plantilla(self, home: str, away: str, surface: str = 'Hard',
                  best_of: int = 3, **ctx) -> Dict:
        from scipy.stats import norm
        pred = self.predecir(home, away, surface=surface,
                             indoor=ctx.get('indoor', False),
                             categoria=ctx.get('categoria'),
                             fase=ctx.get('fase'))
        if 'error' in pred:
            return pred
        p = pred['prob_home']
        md = self.metadata
        campos = [
            {'id': 'ml_home', 'etiqueta': f'Gana {home}', 'valor': p * 100},
            {'id': 'ml_away', 'etiqueta': f'Gana {away}', 'valor': (1 - p) * 100},
        ]
        # --- total de juegos ---
        coef = md.get('coef_juegos')
        sigma_j = md.get('sigma_juegos')
        total_juegos = None
        if coef and sigma_j:
            jug = self.estado.get('jugadores', {})
            r1 = (jug.get(home, {}).get('rank') or 100)
            r2 = (jug.get(away, {}).get('rank') or 100)
            gap = abs(np.log(max(r1, 1)) - np.log(max(r2, 1)))
            total_juegos = float(coef[0] + coef[1] * gap
                                 + coef[2] * (1.0 if best_of == 5 else 0.0))
            for l in (total_juegos - 2.5, total_juegos + 0.5, total_juegos + 3.5):
                l = round(l * 2) / 2
                p_over = float(1 - norm.cdf((l - total_juegos) / sigma_j))
                campos += [
                    {'id': f'juegos_over_{l}', 'etiqueta': f'Más de {l} juegos',
                     'valor': p_over * 100},
                    {'id': f'juegos_under_{l}', 'etiqueta': f'Menos de {l} juegos',
                     'valor': (1 - p_over) * 100},
                ]
        # --- hándicap de juegos (margen ~ N(μ, σ) con μ del favorito) ---
        sm = md.get('sigma_margen_juegos')
        mm = md.get('margen_juegos_medio')
        if sm and mm:
            # el favorito gana por mm de media; μ con signo según quién es
            mu = mm * (1 if p >= 0.5 else -1) * (2 * abs(p - 0.5) * 2)
            for h in (2.5, 4.5, 6.5):
                p_cubre = float(1 - norm.cdf((h - mu) / sm))
                campos += [
                    {'id': f'hand_home_{h}', 'etiqueta': f'{home} −{h} juegos',
                     'valor': p_cubre * 100},
                    {'id': f'hand_away_{h}', 'etiqueta': f'{away} +{h} juegos',
                     'valor': (1 - p_cubre) * 100},
                ]
        # --- sets: se invierte p → prob de ganar UN set (independencia) ---
        # v51: se amplía a TODOS los mercados de sets derivables bajo la
        # asunción de independencia entre sets (declarada). Cubre la plantilla
        # del usuario salvo lo que exige datos de saque/Markov (par/impar de
        # juegos, marcador exacto de juegos), que sigue en 'excluidos'.
        s = _prob_set_desde_partido(p, best_of)
        if best_of == 3:
            # marcador exacto de sets (ambas direcciones)
            h20, h21 = s ** 2, 2 * s ** 2 * (1 - s)          # home 2-0, 2-1
            a20, a21 = (1 - s) ** 2, 2 * (1 - s) ** 2 * s     # away 2-0, 2-1
            p_ambos = 1 - s ** 2 - (1 - s) ** 2
            # primer set (≈ prob de ganar UN set, sets i.i.d.)
            # doble resultado 1er set / partido (independencia entre sets)
            dr_hh = s * (1 - (1 - s) ** 2)      # gana set1 y gana partido
            dr_ha = s * (1 - s) ** 2            # gana set1 y pierde partido
            dr_ah = (1 - s) * s ** 2            # pierde set1 y gana partido
            dr_aa = (1 - s) * (1 - s ** 2)      # pierde set1 y pierde partido
            campos += [
                {'id': 'set_2_0', 'etiqueta': f'{home} gana 2-0', 'valor': h20 * 100},
                {'id': 'set_2_1', 'etiqueta': f'{home} gana 2-1', 'valor': h21 * 100},
                {'id': 'set_0_2', 'etiqueta': f'{away} gana 2-0', 'valor': a20 * 100},
                {'id': 'set_1_2', 'etiqueta': f'{away} gana 2-1', 'valor': a21 * 100},
                {'id': 'ambos_set', 'etiqueta': 'Ambos ganan al menos un set',
                 'valor': p_ambos * 100},
                {'id': 'set_home', 'etiqueta': f'{home} gana al menos un set',
                 'valor': (1 - (1 - s) ** 2) * 100},
                {'id': 'set_away', 'etiqueta': f'{away} gana al menos un set',
                 'valor': (1 - s ** 2) * 100},
                # gana EXACTAMENTE 1 set = el rival gana 2-1
                {'id': 'exact1_home', 'etiqueta': f'{home} gana exactamente 1 set',
                 'valor': a21 * 100},
                {'id': 'exact1_away', 'etiqueta': f'{away} gana exactamente 1 set',
                 'valor': h21 * 100},
                # primer set - ganador
                {'id': 'set1_home', 'etiqueta': f'Gana 1er set: {home}',
                 'valor': s * 100},
                {'id': 'set1_away', 'etiqueta': f'Gana 1er set: {away}',
                 'valor': (1 - s) * 100},
                # hándicap de sets (±1.5 en bo3 = ganar/perder 2-0)
                {'id': 'hset_home_-1.5', 'etiqueta': f'{home} −1.5 sets (gana 2-0)',
                 'valor': h20 * 100},
                {'id': 'hset_home_+1.5', 'etiqueta': f'{home} +1.5 sets (gana ≥1 set)',
                 'valor': (1 - (1 - s) ** 2) * 100},
                {'id': 'hset_away_-1.5', 'etiqueta': f'{away} −1.5 sets (gana 2-0)',
                 'valor': a20 * 100},
                {'id': 'hset_away_+1.5', 'etiqueta': f'{away} +1.5 sets (gana ≥1 set)',
                 'valor': (1 - s ** 2) * 100},
                # doble resultado (1er set / partido)
                {'id': 'dr_hh', 'etiqueta': f'Doble: {home} 1er set y {home} partido',
                 'valor': dr_hh * 100},
                {'id': 'dr_ha', 'etiqueta': f'Doble: {home} 1er set y {away} partido',
                 'valor': dr_ha * 100},
                {'id': 'dr_ah', 'etiqueta': f'Doble: {away} 1er set y {home} partido',
                 'valor': dr_ah * 100},
                {'id': 'dr_aa', 'etiqueta': f'Doble: {away} 1er set y {away} partido',
                 'valor': dr_aa * 100},
            ]
        else:
            # v67 — AL MEJOR DE 5. Los Grand Slam masculinos se juegan a cinco
            # sets y la plantilla solo tenía ahí los mercados de juegos: el
            # parlay de un Grand Slam salía casi vacío frente a los 20 mercados
            # de un bo3. Mismo supuesto declarado de independencia entre sets.
            q = 1 - s
            h30, h31, h32 = s ** 3, 3 * s ** 3 * q, 6 * s ** 3 * q ** 2
            a30, a31, a32 = q ** 3, 3 * q ** 3 * s, 6 * q ** 3 * s ** 2
            campos += [
                {'id': 'set_3_0', 'etiqueta': f'{home} gana 3-0', 'valor': h30 * 100},
                {'id': 'set_3_1', 'etiqueta': f'{home} gana 3-1', 'valor': h31 * 100},
                {'id': 'set_3_2', 'etiqueta': f'{home} gana 3-2', 'valor': h32 * 100},
                {'id': 'set_0_3', 'etiqueta': f'{away} gana 3-0', 'valor': a30 * 100},
                {'id': 'set_1_3', 'etiqueta': f'{away} gana 3-1', 'valor': a31 * 100},
                {'id': 'set_2_3', 'etiqueta': f'{away} gana 3-2', 'valor': a32 * 100},
                {'id': 'set1_home', 'etiqueta': f'Gana 1er set: {home}', 'valor': s * 100},
                {'id': 'set1_away', 'etiqueta': f'Gana 1er set: {away}', 'valor': q * 100},
                {'id': 'set_home', 'etiqueta': f'{home} gana al menos un set',
                 'valor': (1 - a30) * 100},
                {'id': 'set_away', 'etiqueta': f'{away} gana al menos un set',
                 'valor': (1 - h30) * 100},
                {'id': 'ambos_set', 'etiqueta': 'Ambos ganan al menos un set',
                 'valor': (1 - h30 - a30) * 100},
                {'id': 'hset_home_-1.5', 'etiqueta': f'{home} −1.5 sets (gana 3-0 o 3-1)',
                 'valor': (h30 + h31) * 100},
                {'id': 'hset_away_-1.5', 'etiqueta': f'{away} −1.5 sets (gana 3-0 o 3-1)',
                 'valor': (a30 + a31) * 100},
                {'id': 'hset_home_+1.5', 'etiqueta': f'{home} +1.5 sets (gana ≥2 sets)',
                 'valor': (1 - a30 - a31) * 100},
                {'id': 'hset_away_+1.5', 'etiqueta': f'{away} +1.5 sets (gana ≥2 sets)',
                 'valor': (1 - h30 - h31) * 100},
                {'id': 'dr_hh', 'etiqueta': f'Doble: {home} 1er set y {home} partido',
                 'valor': s * (h30 + h31 + h32) * 100},
                {'id': 'dr_aa', 'etiqueta': f'Doble: {away} 1er set y {away} partido',
                 'valor': q * (a30 + a31 + a32) * 100},
            ]
        # v67: además de `campos` (que consume la tabla de la UI desde v51), se
        # publica `secciones` en el MISMO formato que fútbol y MLB. Es lo que
        # lee `match_parlay.obtener_selecciones`, y sin ello el tenis era el
        # único deporte de la app sin combinadas: la plantilla tenía 33
        # mercados y el generador de parlays no veía ninguno.
        secciones = _agrupar_en_secciones(campos)
        return {'deporte': self.deporte, 'partido': f'{home} vs {away}',
                'superficie': surface, 'prediccion': pred,
                'total_juegos_estimado': (round(total_juegos, 1)
                                          if total_juegos else None),
                'campos': campos, 'secciones': secciones,
                'codigos': {'home': home, 'away': away},
                'excluidos': md.get('mercados_excluidos', []),
                'nota': ('Sets bajo independencia condicional entre sets '
                         '(asunción declarada). Sin cuotas en vivo, las '
                         'cuotas son justas = 1/probabilidad.')}


SECCIONES_TENIS = [
    ('🏆 Ganador', ('ml_',)),
    ('1️⃣ Primer set', ('set1_',)),
    ('📐 Sets (marcador y especiales)', ('set_', 'ambos_set', 'exact1_')),
    ('➕ Hándicap de sets', ('hset_',)),
    ('🎾 Total de juegos', ('juegos_',)),
    ('➕ Hándicap de juegos', ('hand_',)),
    ('🔗 Doble resultado (1er set / partido)', ('dr_',)),
]


# Un mercado por encima de este listón tiene cuota justa < 1.03: no paga nada y
# solo alarga el boleto. El hándicap de juegos de un partido parejo (+6.5
# juegos) llega al 99 %: informativo sí, apostable no. Se queda en `campos` (la
# tabla) pero fuera de `secciones` (el parlay).
PROB_MAX_APOSTABLE = 97.0


def _agrupar_en_secciones(campos: List[Dict]) -> List[Dict]:
    """Convierte la lista plana de mercados al formato `secciones`/`campos`
    con `tipo='pct'` que espera el motor de parlays del proyecto."""
    usados = set()
    secciones = []
    for titulo, prefijos in SECCIONES_TENIS:
        dentro = []
        for c in campos:
            cid = c.get('id', '')
            if cid in usados or not cid.startswith(prefijos):
                continue
            usados.add(cid)
            try:
                if float(c.get('valor', 0)) >= PROB_MAX_APOSTABLE:
                    continue
            except (TypeError, ValueError):
                pass
            dentro.append({**c, 'tipo': 'pct'})
        if dentro:
            secciones.append({'titulo': titulo, 'campos': dentro})
    sobrantes = [{**c, 'tipo': 'pct'} for c in campos if c.get('id') not in usados]
    if sobrantes:
        secciones.append({'titulo': '📊 Otros mercados', 'campos': sobrantes})
    return secciones


def _prob_set_desde_partido(p_partido: float, best_of: int = 3) -> float:
    """Invierte numéricamente P(partido) → P(set) suponiendo sets i.i.d.
    bo3: P = s²(3−2s). Búsqueda binaria (monótona en s)."""
    p_partido = min(max(p_partido, 1e-4), 1 - 1e-4)
    lo, hi = 0.0, 1.0
    for _ in range(60):
        s = (lo + hi) / 2
        if best_of == 5:
            pm = s ** 3 * (1 + 3 * (1 - s) + 6 * (1 - s) ** 2)
        else:
            pm = s ** 2 * (3 - 2 * s)
        if pm < p_partido:
            lo = s
        else:
            hi = s
    return (lo + hi) / 2


if __name__ == '__main__':
    import sys
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    circuitos = [a for a in sys.argv[1:] if a in CIRCUITOS] or ['atp']
    for c in circuitos:
        print(json.dumps(TennisEngine(c).entrenar(), indent=2, ensure_ascii=False))
