#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v131 · NFL — modelo predictivo de 1X2, hándicap, total y totales de equipo.

Qué hace y por qué así
----------------------
El encargo pedía «el mismo enfoque que el módulo B de la MLB»: ajustar por
CONTEXTO REAL medido en vez de por un ancla de papel. En la MLB eso significó
usar los bateadores que enfrenta de verdad cada abridor (`contexto_ponches`)
en vez del 17,0 teórico, y bajó el sesgo de +1,38 a +0,76. Aquí el equivalente
es no describir a un equipo por su marcador —que es ruidoso y ya está en el
precio— sino por **cómo genera ese marcador**: yardas por jugada propias y
concedidas, conversión de terceros downs, eficiencia en zona roja, pérdidas de
balón y ritmo de juego.

La cadena es:

    estado rodante por equipo (sin fuga)
        → dos regresiones ridge: MARGEN y TOTAL
            → distribución de residuos MEDIDA (no supuesta)
                → probabilidad de cada mercado

Dos decisiones que no son de gusto, y su medición
-------------------------------------------------
1. **Se modelan margen y total, no «puntos del local» y «puntos del
   visitante» por separado.** Los dos marcadores de un partido están
   correlacionados (ritmo compartido: las mismas jugadas alimentan a los dos),
   así que modelarlos como independientes y sumarlos infla la varianza del
   total. Margen y total, en cambio, son casi ortogonales — medido sobre el
   histórico, y se imprime en el informe.

2. **La distribución del margen NO es normal, y en la NFL eso tiene nombre:
   los números clave.** Un margen de 3 y uno de 7 son mucho más frecuentes que
   sus vecinos porque un gol de campo vale 3 y un touchdown convertido 7. Una
   normal reparte esa masa de forma lisa y se equivoca justo en las líneas más
   cotizadas (-3, -7). Por eso se calculan las dos —normal y empírica por
   residuos— y **se elige la que mida mejor**, no la que suene mejor. El
   veredicto queda escrito en `nfl_calibracion.json`.

Lo que este módulo NO promete
-----------------------------
No promete batir al mercado, porque la bitácora §0 ya midió qué pasa cuando se
promete: el modelo de fútbol está perfectamente calibrado y aun así pierde
−4,66 % apostando su propia probabilidad. La probabilidad de aquí sirve para
**ordenar y descartar**; quien decide si algo tiene valor es la ventaja de
precio contra el consenso (§2), y eso vive en `clasificador.py`, no aquí.
"""
from __future__ import annotations

import json
import logging
import math
import os
from collections import deque
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

ARTEFACTO = os.path.join('modelos', 'nfl_v131.json')
CALIBRACION = 'nfl_calibracion.json'

# Ventana del estado rodante, ARRASTRE entre temporadas y regularización: los
# tres se ELIGIERON MIDIENDO, y midiendo bien.
#
# El barrido de 48 combinaciones (`barrer_ajustes`) se corrió sobre la
# temporada 2024 SOLA, y el ganador se juzgó después en 2025, que no participó
# en la elección. Hacerlo al revés —barrer sobre las dos y presumir del
# resultado— es el error que la bitácora §2 retrata con el empate del fútbol:
# +12,21 % en el tramo con el que se eligió, −7,09 % en el otro.
#
#     elección (2024)  v=12 arr=0,50 alpha=15  log-loss 0,64355  ← ganador
#     juicio   (2025)  v=12 arr=0,50 alpha=15  log-loss 0,63514
#                      v= 8 arr=0,35 alpha= 5  log-loss 0,64039  (defecto viejo)
#
# O sea: el ajuste elegido a ciegas también gana en la temporada que no vio.
# Eso es una mejora real, no un artefacto de haber mirado el examen.
#
# Y un hallazgo lateral que sí sorprende: `arrastre = 0` (empezar cada
# temporada de cero) queda ÚLTIMO en las 48 combinaciones. La NFL regresa a la
# media con fuerza, pero no tanto como para tirar el año anterior entero.
VENTANA = 12

# Cuánto sobrevive el estado de una temporada a la siguiente (ver arriba).
ARRASTRE = 0.50
ALPHA = 15.0

# Sólo liga regular y playoffs entrenan. La PRETEMPORADA se excluye a
# propósito: los titulares juegan un cuarto, el resultado no describe al equipo
# y meterla ensuciaría las medias justo antes de la jornada 1, que es cuando
# más se apuesta. Se predice igual (hay mercado), pero con el aviso puesto.
TIPOS_ENTRENAMIENTO = ('regular', 'playoffs')

# Magnitudes del estado rodante. Cada una se guarda en versión OFENSIVA (lo que
# hace el equipo) y DEFENSIVA (lo que le hacen), que es la del rival en ese
# mismo partido. Sin la mitad defensiva, un ataque bueno y una defensa mala
# serían indistinguibles.
CAMPOS = ('pts', 'yardas_jugada', 'yardas_acarreo', 'yardas_pase_int',
          'tasa3', 'tasa_rz', 'perdidas', 'jugadas')

# Valores de arranque: la media de la liga. Un equipo sin historial no vale
# cero, vale «lo normal» — que es lo que dice la información disponible.
BASE_LIGA = {'pts': 22.0, 'yardas_jugada': 5.4, 'yardas_acarreo': 4.3,
             'yardas_pase_int': 6.6, 'tasa3': 0.39, 'tasa_rz': 0.55,
             'perdidas': 1.3, 'jugadas': 63.0}


def _tasa(conv, intentos, defecto):
    """Conversión / intentos, con el valor de liga cuando no hubo intentos."""
    try:
        c, i = float(conv), float(intentos)
    except (TypeError, ValueError):
        return defecto
    if not (i > 0) or c != c or i != i:
        return defecto
    return c / i


def _lado(fila, lado: str) -> Dict[str, float]:
    """Las ocho magnitudes de un bando en un partido concreto."""
    g = lambda c: fila.get(f'{lado}_{c}')
    v = {
        'pts': fila.get(f'pts_{lado}'),
        'yardas_jugada': g('yardas_jugada'),
        'yardas_acarreo': g('yardas_acarreo'),
        'yardas_pase_int': g('yardas_pase_int'),
        'tasa3': _tasa(g('conv3'), g('int3'), BASE_LIGA['tasa3']),
        'tasa_rz': _tasa(g('rz_conv'), g('rz_int'), BASE_LIGA['tasa_rz']),
        'perdidas': g('perdidas'),
        'jugadas': g('jugadas'),
    }
    return {k: (float(x) if x is not None and x == x else BASE_LIGA[k])
            for k, x in v.items()}


class EstadoEquipos:
    """
    Memoria rodante por equipo, actualizada SIEMPRE después de emitir la fila.

    Ése es el orden que impide la fuga, y es el mismo que ya usan
    `nba_features.construir_features` y `NBAEngine._dataset`. Escrito como
    clase y no como bucle porque en producción hace falta consultar el estado
    de dos equipos concretos sin volver a recorrer el histórico.
    """

    def __init__(self, ventana: int = VENTANA, arrastre: float = ARRASTRE):
        self.ventana = ventana
        self.arrastre = arrastre
        self.of: Dict[str, Dict[str, deque]] = {}
        self.de: Dict[str, Dict[str, deque]] = {}
        self.ult_fecha: Dict[str, pd.Timestamp] = {}
        self.temporada: Optional[int] = None
        self.jugados: Dict[str, int] = {}

    # -- consulta ---------------------------------------------------------
    def _media(self, banco, equipo, campo) -> float:
        v = (banco.get(equipo) or {}).get(campo)
        return float(np.mean(v)) if v else BASE_LIGA[campo]

    def perfil(self, equipo: str) -> Dict[str, float]:
        """Las 16 medias (8 ofensivas + 8 defensivas) del equipo, ahora mismo."""
        d = {f'of_{c}': self._media(self.of, equipo, c) for c in CAMPOS}
        d.update({f'de_{c}': self._media(self.de, equipo, c) for c in CAMPOS})
        d['n'] = float(self.jugados.get(equipo, 0))
        return d

    def descanso(self, equipo: str, fecha) -> float:
        """Días desde su último partido, topado a 14 (la semana de descanso)."""
        prev = self.ult_fecha.get(equipo)
        if prev is None:
            return 7.0
        return float(min((pd.Timestamp(fecha) - prev).days, 14))

    # -- actualización ----------------------------------------------------
    def _nueva_temporada(self, temporada) -> None:
        """
        Encoge el estado hacia la media de liga al cambiar de año.

        No se BORRA, que sería tirar información buena: los Chiefs de enero
        siguen informando sobre los Chiefs de septiembre. Pero tampoco se
        arrastra entero, porque entre medias hay draft, agencia libre y tope
        salarial. Se encoge con `arrastre`, y el valor se elige midiendo.
        """
        for banco in (self.of, self.de):
            for equipo, campos in banco.items():
                for c, cola in campos.items():
                    base = BASE_LIGA[c]
                    encogido = [base + self.arrastre * (x - base) for x in cola]
                    campos[c] = deque(encogido, maxlen=self.ventana)
        self.temporada = temporada

    def registrar(self, fila) -> None:
        """Mete un partido YA JUGADO en la memoria de los dos equipos."""
        t = fila.get('temporada')
        if t is not None and t == t and self.temporada is not None and t != self.temporada:
            self._nueva_temporada(t)
        elif self.temporada is None:
            self.temporada = t
        h, a = fila['home'], fila['away']
        vh, va = _lado(fila, 'home'), _lado(fila, 'away')
        for equipo, propio, ajeno in ((h, vh, va), (a, va, vh)):
            for c in CAMPOS:
                self.of.setdefault(equipo, {}).setdefault(
                    c, deque(maxlen=self.ventana)).append(propio[c])
                self.de.setdefault(equipo, {}).setdefault(
                    c, deque(maxlen=self.ventana)).append(ajeno[c])
            self.jugados[equipo] = self.jugados.get(equipo, 0) + 1
        f = pd.Timestamp(fila['fecha'])
        self.ult_fecha[h] = self.ult_fecha[a] = f


# ---------------------------------------------------------------------------
# Features
# ---------------------------------------------------------------------------
# El MARGEN se explica con DIFERENCIAS (lo que el local tiene de más), el TOTAL
# con SUMAS (lo que los dos aportan). Separarlos así no es cosmético: mete en
# cada regresión sólo la parte de la señal que puede explicar su objetivo, y
# evita que el ritmo de juego —que sube el total y no toca el margen— entre
# como ruido en la ecuación del margen.
COLS_MARGEN = ['d_ataque', 'd_defensa', 'd_ypj', 'd_ypj_def', 'd_carrera',
               'd_pase', 'd_tasa3', 'd_tasa3_def', 'd_rz', 'd_rz_def',
               'd_perdidas', 'd_robos', 'd_descanso', 'local', 'd_n']
COLS_TOTAL = ['s_ataque', 's_defensa', 's_ypj', 's_ypj_def', 's_jugadas',
              's_tasa3', 's_rz', 's_perdidas', 'neutral']


def _fila_features(est: EstadoEquipos, fila) -> Dict[str, float]:
    h, a = fila['home'], fila['away']
    ph, pa = est.perfil(h), est.perfil(a)
    local = 0.0 if fila.get('neutral') else 1.0
    f = {
        # --- margen (diferencias) ---
        'd_ataque': ph['of_pts'] - pa['of_pts'],
        'd_defensa': pa['de_pts'] - ph['de_pts'],
        'd_ypj': ph['of_yardas_jugada'] - pa['of_yardas_jugada'],
        'd_ypj_def': pa['de_yardas_jugada'] - ph['de_yardas_jugada'],
        'd_carrera': ph['of_yardas_acarreo'] - pa['of_yardas_acarreo'],
        'd_pase': ph['of_yardas_pase_int'] - pa['of_yardas_pase_int'],
        'd_tasa3': ph['of_tasa3'] - pa['of_tasa3'],
        'd_tasa3_def': pa['de_tasa3'] - ph['de_tasa3'],
        'd_rz': ph['of_tasa_rz'] - pa['of_tasa_rz'],
        'd_rz_def': pa['de_tasa_rz'] - ph['de_tasa_rz'],
        'd_perdidas': pa['of_perdidas'] - ph['of_perdidas'],
        'd_robos': ph['de_perdidas'] - pa['de_perdidas'],
        'd_descanso': (est.descanso(h, fila['fecha'])
                       - est.descanso(a, fila['fecha'])) / 7.0,
        'local': local,
        # cuánta memoria hay detrás de las medias. Sin esto, un partido de la
        # jornada 1 (medias = liga entera) pesa igual que uno de la jornada 15.
        'd_n': (min(ph['n'], 8) - min(pa['n'], 8)) / 8.0,
        # --- total (sumas) ---
        's_ataque': ph['of_pts'] + pa['of_pts'],
        's_defensa': ph['de_pts'] + pa['de_pts'],
        's_ypj': ph['of_yardas_jugada'] + pa['of_yardas_jugada'],
        's_ypj_def': ph['de_yardas_jugada'] + pa['de_yardas_jugada'],
        's_jugadas': ph['of_jugadas'] + pa['of_jugadas'],
        's_tasa3': ph['of_tasa3'] + pa['of_tasa3'],
        's_rz': ph['of_tasa_rz'] + pa['of_tasa_rz'],
        's_perdidas': ph['of_perdidas'] + pa['of_perdidas'],
        'neutral': 1.0 - local,
    }
    return f


def construir_dataset(d: pd.DataFrame, ventana: int = VENTANA,
                      arrastre: float = ARRASTRE) -> pd.DataFrame:
    """
    Una fila por partido con sus features y sus dos objetivos.

    Recorre en orden estricto de fecha y actualiza el estado DESPUÉS de emitir,
    así que ninguna feature ve el partido que intenta predecir.
    """
    d = d.sort_values(['fecha', 'event_id']).reset_index(drop=True)
    est = EstadoEquipos(ventana, arrastre)
    filas = []
    for r in d.to_dict('records'):
        if not r.get('home') or not r.get('away'):
            continue
        if r.get('pts_home') is None or r.get('pts_away') is None:
            continue
        if not (r['pts_home'] == r['pts_home'] and r['pts_away'] == r['pts_away']):
            continue
        f = _fila_features(est, r)
        f.update({
            'event_id': r['event_id'], 'fecha': r['fecha'],
            'temporada': r.get('temporada'), 'tipo': r.get('tipo'),
            'home': r['home'], 'away': r['away'],
            'margen': float(r['pts_home']) - float(r['pts_away']),
            'total': float(r['pts_home']) + float(r['pts_away']),
            'n_home': est.jugados.get(r['home'], 0),
            'n_away': est.jugados.get(r['away'], 0),
        })
        for c in ('ml_home', 'ml_away', 'hcp_home', 'hcp_cuota_home',
                  'hcp_cuota_away', 'total_cierre'):
            f[c] = r.get(c if c != 'total_cierre' else 'total')
        filas.append(f)
        if r.get('tipo') in TIPOS_ENTRENAMIENTO:
            est.registrar(r)
    return pd.DataFrame(filas)


# ---------------------------------------------------------------------------
# Regresión
# ---------------------------------------------------------------------------
class _Ridge:
    """
    Ridge con estandarización, resuelto en forma cerrada.

    Se escribe a mano y no se importa `sklearn.Ridge` por una razón concreta:
    el artefacto que viaja a producción es un JSON de veinte números en vez de
    un `joblib` con la versión de scikit-learn dentro. La bitácora §8 vigila la
    memoria del contenedor de Streamlit Cloud, y un modelo que se carga con
    `json.load` no arrastra nada. La fórmula es la misma.
    """

    def __init__(self, alpha: float = ALPHA):
        self.alpha = alpha
        self.mu = None
        self.sigma = None
        self.coef = None
        self.b0 = 0.0

    def ajustar(self, X: np.ndarray, y: np.ndarray) -> '_Ridge':
        X = np.asarray(X, dtype=float)
        y = np.asarray(y, dtype=float)
        self.mu = X.mean(axis=0)
        self.sigma = X.std(axis=0)
        self.sigma[self.sigma < 1e-9] = 1.0
        Z = (X - self.mu) / self.sigma
        n, k = Z.shape
        A = Z.T @ Z + self.alpha * np.eye(k)
        self.coef = np.linalg.solve(A, Z.T @ (y - y.mean()))
        self.b0 = float(y.mean())
        return self

    def predecir(self, X: np.ndarray) -> np.ndarray:
        Z = (np.asarray(X, dtype=float) - self.mu) / self.sigma
        return Z @ self.coef + self.b0

    def a_dict(self) -> Dict:
        return {'alpha': self.alpha, 'mu': list(map(float, self.mu)),
                'sigma': list(map(float, self.sigma)),
                'coef': list(map(float, self.coef)), 'b0': self.b0}

    @staticmethod
    def de_dict(d: Dict) -> '_Ridge':
        m = _Ridge(d.get('alpha', 5.0))
        m.mu = np.array(d['mu'], dtype=float)
        m.sigma = np.array(d['sigma'], dtype=float)
        m.coef = np.array(d['coef'], dtype=float)
        m.b0 = float(d['b0'])
        return m


def _phi(z):
    """Normal acumulada, vectorizada, sin traerse scipy."""
    z = np.asarray(z, dtype=float)
    return 0.5 * (1.0 + np.vectorize(math.erf)(z / math.sqrt(2.0)))


class NFLModelo:
    """
    El modelo desplegable: dos ridge, dos dispersiones y la bolsa de residuos.

    `predecir_partido` devuelve las probabilidades de los cuatro mercados que
    pedía el encargo (1X2, hándicap, total y totales de equipo) más el margen y
    el total esperados, que es lo que la interfaz pinta en barras.
    """

    def __init__(self, ventana: int = VENTANA, arrastre: float = ARRASTRE):
        self.ventana = ventana
        self.arrastre = arrastre
        self.m_margen: Optional[_Ridge] = None
        self.m_total: Optional[_Ridge] = None
        self.sigma_margen = 13.5
        self.sigma_total = 10.0
        self.res_margen: np.ndarray = np.array([])
        self.res_total: np.ndarray = np.array([])
        self.metodo_margen = 'normal'     # lo decide la medición, no el gusto
        self.estado: Optional[EstadoEquipos] = None
        self.entrenado_hasta: Optional[str] = None
        self.n_entrenamiento = 0

    # -- entrenamiento ----------------------------------------------------
    def entrenar(self, ds: pd.DataFrame, alpha: float = ALPHA) -> 'NFLModelo':
        ent = ds[ds['tipo'].isin(TIPOS_ENTRENAMIENTO)]
        if len(ent) < 60:
            raise ValueError(f'muestra insuficiente para entrenar: {len(ent)}')
        Xm = ent[COLS_MARGEN].values
        Xt = ent[COLS_TOTAL].values
        self.m_margen = _Ridge(alpha).ajustar(Xm, ent['margen'].values)
        self.m_total = _Ridge(alpha).ajustar(Xt, ent['total'].values)
        rm = ent['margen'].values - self.m_margen.predecir(Xm)
        rt = ent['total'].values - self.m_total.predecir(Xt)
        self.sigma_margen = float(np.std(rm, ddof=len(COLS_MARGEN) + 1))
        self.sigma_total = float(np.std(rt, ddof=len(COLS_TOTAL) + 1))
        self.res_margen = np.sort(rm)
        self.res_total = np.sort(rt)
        self.n_entrenamiento = int(len(ent))
        self.entrenado_hasta = str(pd.to_datetime(ent['fecha']).max().date())
        return self

    def construir_estado(self, historico: pd.DataFrame) -> 'NFLModelo':
        """Rehace la memoria rodante recorriendo el histórico completo."""
        est = EstadoEquipos(self.ventana, self.arrastre)
        h = historico.sort_values(['fecha', 'event_id'])
        for r in h.to_dict('records'):
            if r.get('tipo') in TIPOS_ENTRENAMIENTO and r.get('home') and r.get('away'):
                if r.get('pts_home') == r.get('pts_home'):
                    est.registrar(r)
        self.estado = est
        return self

    # -- probabilidades ---------------------------------------------------
    def _p_mayor(self, media, umbral, cual: str) -> float:
        """
        P(variable > umbral), por normal o por residuos empíricos.

        El método lo fija `metodo_margen`, que se elige comparando las dos con
        log-loss fuera de muestra en `backtest`. No se decide aquí.
        """
        if cual == 'margen':
            sigma, res = self.sigma_margen, self.res_margen
            empirico = self.metodo_margen == 'empirico'
        else:
            sigma, res = self.sigma_total, self.res_total
            empirico = False
        if empirico and len(res) >= 200:
            return float(np.mean(media + res > umbral))
        return float(1.0 - _phi((umbral - media) / max(sigma, 1e-6)))

    def probabilidades(self, margen_esp: float, total_esp: float,
                       linea_hcp: Optional[float] = None,
                       linea_total: Optional[float] = None,
                       lineas_equipo: Optional[Tuple[float, float]] = None) -> Dict:
        """
        Del par (margen esperado, total esperado) a los mercados publicables.

        Convención de signo del hándicap, que es donde se cometen los errores:
        `linea_hcp` es la línea DEL LOCAL tal y como la escribe la casa. −3,5
        significa que el local da 3,5 puntos, y cubre si `margen > 3,5`.
        """
        # TOTAL DE UN EQUIPO = (total ± margen) / 2, y su dispersión NO es
        # σ_total/2.
        #
        # Margen y total son casi independientes (correlación medida ~0, se
        # imprime en el informe), así que
        #     Var(pts_home) = (Var(total) + Var(margen)) / 4
        # Con σ_total/2 la dispersión saldría un tercio corta y los dos lados
        # del total de equipo parecerían mucho más seguros de lo que son.
        #
        # Se calcula SIEMPRE y no sólo cuando llegan líneas de equipo: es una
        # propiedad del modelo, no de la pregunta. Cuando dependía de la
        # pregunta, `nfl_mercados.plantilla_nfl` recibía `sigma_equipo=None` y
        # los cuatro mercados de total por equipo se caían del cruce sin dar
        # error — aparecían en pantalla con precio y sin probabilidad.
        s_eq = math.sqrt(self.sigma_total ** 2 + self.sigma_margen ** 2) / 2.0
        out = {
            'margen_esperado': round(float(margen_esp), 2),
            'total_esperado': round(float(total_esp), 2),
            'pts_home_esperado': round(float((total_esp + margen_esp) / 2), 2),
            'pts_away_esperado': round(float((total_esp - margen_esp) / 2), 2),
            'sigma_margen': round(self.sigma_margen, 2),
            'sigma_total': round(self.sigma_total, 2),
            'sigma_equipo': round(s_eq, 2),
        }
        # 1X2. El empate existe en la NFL pero es rarísimo: 0,25 % del histórico
        # (medido). Se declara y se reparte, en vez de fingir que no existe:
        # el mercado «Ganador (incl. prórroga)» de la casa es a dos vías y ahí
        # el empate devuelve la apuesta, así que la probabilidad que importa es
        # la condicionada a que no haya empate.
        p_home = self._p_mayor(margen_esp, 0.5, 'margen')
        p_away = 1.0 - self._p_mayor(margen_esp, -0.5, 'margen')
        p_empate = max(0.0, 1.0 - p_home - p_away)
        out['prob_home'] = round(p_home, 4)
        out['prob_away'] = round(p_away, 4)
        out['prob_empate'] = round(p_empate, 4)
        vivo = p_home + p_away
        out['prob_home_sin_empate'] = round(p_home / vivo, 4) if vivo > 0 else 0.5
        out['prob_away_sin_empate'] = round(p_away / vivo, 4) if vivo > 0 else 0.5

        if linea_hcp is not None:
            L = float(linea_hcp)
            # con línea entera hay EMPUJE (push): el margen puede caer justo
            # ahí y la apuesta se devuelve. Ignorarlo infla las dos patas.
            if abs(L - round(L)) < 1e-6:
                p_cubre = self._p_mayor(margen_esp, -L + 0.5, 'margen')
                p_no = 1.0 - self._p_mayor(margen_esp, -L - 0.5, 'margen')
                p_push = max(0.0, 1.0 - p_cubre - p_no)
            else:
                p_cubre = self._p_mayor(margen_esp, -L, 'margen')
                p_no, p_push = 1.0 - p_cubre, 0.0
            out['linea_hcp'] = L
            out['prob_hcp_home'] = round(p_cubre, 4)
            out['prob_hcp_away'] = round(p_no, 4)
            out['prob_hcp_push'] = round(p_push, 4)

        if linea_total is not None:
            L = float(linea_total)
            if abs(L - round(L)) < 1e-6:
                p_over = self._p_mayor(total_esp, L + 0.5, 'total')
                p_under = 1.0 - self._p_mayor(total_esp, L - 0.5, 'total')
            else:
                p_over = self._p_mayor(total_esp, L, 'total')
                p_under = 1.0 - p_over
            out['linea_total'] = L
            out['prob_over'] = round(p_over, 4)
            out['prob_under'] = round(p_under, 4)

        if lineas_equipo:
            for lado, linea, media in (
                    ('home', lineas_equipo[0], (total_esp + margen_esp) / 2),
                    ('away', lineas_equipo[1], (total_esp - margen_esp) / 2)):
                if linea is None:
                    continue
                L = float(linea)
                p = float(1.0 - _phi((L - media) / max(s_eq, 1e-6)))
                out[f'prob_over_{lado}'] = round(p, 4)
                out[f'prob_under_{lado}'] = round(1.0 - p, 4)
                out[f'linea_total_{lado}'] = L
        return out

    # EN PRETEMPORADA EL MODELO NO PUBLICA PROBABILIDAD, Y ESTÁ MEDIDO.
    #
    # Se entrena sólo con liga regular y playoffs (`TIPOS_ENTRENAMIENTO`), pero
    # nada impedía pedirle una predicción de un partido de agosto — y la daba,
    # muy segura. El primer barrido real lo destapó: 82,3 % a un Seattle–Dallas
    # de pretemporada, que contra la cuota de la casa producía un EV de +38 %,
    # o sea la firma exacta de `EV_SOSPECHOSO`.
    #
    # Medido sobre las pretemporadas de 2024 y 2025 (n=103, entrenando sólo con
    # temporadas anteriores):
    #
    #                          acierto   Brier    corr(predicho, real)
    #     liga regular 2025      62,7 %  0,2239        +0,410
    #     PRETEMPORADA           52,4 %  0,2727        −0,013
    #     decir siempre 50 %     50,0 %  0,2500            —
    #
    # No es que sea peor: es que **no tiene ninguna información** (correlación
    # −0,013 con el margen real) y su Brier es PEOR que el de una moneda. Una
    # probabilidad así no informa, desinforma — y encima fabrica EV.
    #
    # El partido no se oculta: sigue en la lista, con su precio y con la
    # comparación entre casas, que no usa el modelo y funciona igual. Lo que se
    # retira es la cifra que no significa nada.
    MOTIVO_PRETEMPORADA = (
        'En pretemporada el modelo no publica probabilidad: medido sobre 103 '
        'partidos de 2024-2025, su correlación con el margen real es −0,013 '
        '(o sea, ninguna) y su Brier 0,2727, peor que decir 50 %. Los '
        'titulares juegan un cuarto y el resultado no describe al equipo. El '
        'precio y la comparación entre casas sí siguen valiendo.')

    def predecir_partido(self, home: str, away: str, fecha=None,
                         neutral: bool = False, tipo: str = 'regular',
                         **lineas) -> Dict:
        """Entrada de PRODUCCIÓN: dos abreviaturas y, si se tienen, las líneas."""
        if self.estado is None or self.m_margen is None:
            return {'error': 'modelo sin entrenar o sin estado'}
        if home not in self.estado.jugados or away not in self.estado.jugados:
            faltan = [e for e in (home, away) if e not in self.estado.jugados]
            return {'error': f'sin historial para {", ".join(faltan)}'}
        # SIN ZONA HORARIA, A PROPÓSITO. `est.descanso` resta esta fecha de la
        # última guardada, que viene del CSV y es naive. Mezclar una tz-aware
        # con una naive no da un número raro: lanza TypeError, y lo haría sólo
        # en producción (cuando no se pasa fecha), nunca en el backtest.
        fila = {'home': home, 'away': away,
                'fecha': fecha or pd.Timestamp.now('UTC').tz_localize(None).normalize(),
                'neutral': neutral}
        f = _fila_features(self.estado, fila)
        Xm = np.array([[f[c] for c in COLS_MARGEN]], dtype=float)
        Xt = np.array([[f[c] for c in COLS_TOTAL]], dtype=float)
        margen = float(self.m_margen.predecir(Xm)[0])
        total = float(self.m_total.predecir(Xt)[0])
        r = self.probabilidades(margen, total, **lineas)
        r['home'], r['away'] = home, away
        r['n_home'] = int(self.estado.jugados.get(home, 0))
        r['n_away'] = int(self.estado.jugados.get(away, 0))
        r['entrenado_hasta'] = self.entrenado_hasta
        r['tipo'] = tipo
        r['probabilidades_publicables'] = tipo != 'pretemporada'
        if not r['probabilidades_publicables']:
            r['motivo_sin_probabilidad'] = self.MOTIVO_PRETEMPORADA
            # Se BORRAN, no se marcan y ya. Dejarlas dentro con una bandera al
            # lado es confiar en que los seis sitios que leen este diccionario
            # miren la bandera, y basta con que uno no la mire para que la cifra
            # salga a pantalla con un EV detrás. El marcador esperado sí se
            # conserva: es una estimación descriptiva, no una apuesta.
            for k in [k for k in r if k.startswith('prob_')]:
                r.pop(k)
        return r

    # -- persistencia -----------------------------------------------------
    def guardar(self, ruta: str = ARTEFACTO) -> str:
        os.makedirs(os.path.dirname(ruta) or '.', exist_ok=True)
        doc = {
            'version': 'v131', 'ventana': self.ventana, 'arrastre': self.arrastre,
            'margen': self.m_margen.a_dict(), 'total': self.m_total.a_dict(),
            'cols_margen': COLS_MARGEN, 'cols_total': COLS_TOTAL,
            'sigma_margen': self.sigma_margen, 'sigma_total': self.sigma_total,
            'metodo_margen': self.metodo_margen,
            'entrenado_hasta': self.entrenado_hasta,
            'n_entrenamiento': self.n_entrenamiento,
            # La bolsa de residuos se guarda en PERCENTILES y no entera: 201
            # números describen la forma igual de bien que 900 y el artefacto
            # se queda en 30 KB.
            'res_margen_pct': [float(x) for x in
                               np.percentile(self.res_margen, np.linspace(0, 100, 201))]
                              if len(self.res_margen) else [],
            'res_total_pct': [float(x) for x in
                              np.percentile(self.res_total, np.linspace(0, 100, 201))]
                             if len(self.res_total) else [],
        }
        with open(ruta, 'w', encoding='utf-8') as f:
            json.dump(doc, f, ensure_ascii=False, indent=1)
        return ruta

    @staticmethod
    def cargar(ruta: str = ARTEFACTO,
               historico: Optional[pd.DataFrame] = None) -> Optional['NFLModelo']:
        if not os.path.exists(ruta):
            return None
        try:
            with open(ruta, encoding='utf-8') as f:
                d = json.load(f)
        except Exception as e:
            logger.warning(f'[nfl] artefacto ilegible: {e}')
            return None
        m = NFLModelo(d.get('ventana', VENTANA), d.get('arrastre', ARRASTRE))
        m.m_margen = _Ridge.de_dict(d['margen'])
        m.m_total = _Ridge.de_dict(d['total'])
        m.sigma_margen = float(d.get('sigma_margen', 13.5))
        m.sigma_total = float(d.get('sigma_total', 10.0))
        m.metodo_margen = d.get('metodo_margen', 'normal')
        m.res_margen = np.array(d.get('res_margen_pct') or [], dtype=float)
        m.res_total = np.array(d.get('res_total_pct') or [], dtype=float)
        m.entrenado_hasta = d.get('entrenado_hasta')
        m.n_entrenamiento = int(d.get('n_entrenamiento') or 0)
        if historico is not None and len(historico):
            m.construir_estado(historico)
        return m


# ---------------------------------------------------------------------------
# Validación
# ---------------------------------------------------------------------------
def _devig_dos_vias(c1, c2) -> Tuple[Optional[float], Optional[float]]:
    """Quita el margen de un mercado de dos salidas, proporcionalmente."""
    try:
        p1, p2 = 1.0 / float(c1), 1.0 / float(c2)
    except (TypeError, ValueError, ZeroDivisionError):
        return None, None
    s = p1 + p2
    if not (s > 0):
        return None, None
    return p1 / s, p2 / s


def _bootstrap_p5(pnl: np.ndarray, n: int = 2000, semilla: int = 20260815) -> float:
    if len(pnl) < 20:
        return float('nan')
    rng = np.random.default_rng(semilla)
    idx = rng.integers(0, len(pnl), size=(n, len(pnl)))
    return float(np.percentile(pnl[idx].mean(axis=1), 5))


def backtest(d: pd.DataFrame, temporadas_juicio: List[int],
             ventana: int = VENTANA, arrastre: float = ARRASTRE,
             alpha: float = ALPHA) -> Dict:
    """
    Walk-forward: se entrena con lo anterior y se juzga la temporada siguiente.

    Mide tres cosas distintas que el proyecto ha aprendido a no confundir:
      1. **Acierto** — cuántas veces acierta el lado. No decide nada.
      2. **Calibración** — si dice 60 % acierta 60 %. Es lo que se publica.
      3. **ROI al precio de cierre real**, con su bootstrap p5. Es lo único
         que decide si algo se despliega (bitácora, regla de oro).
    """
    ds = construir_dataset(d, ventana, arrastre)
    ds = ds[ds['tipo'].isin(TIPOS_ENTRENAMIENTO)].reset_index(drop=True)
    resultados = {'ventana': ventana, 'arrastre': arrastre, 'alpha': alpha,
                  'temporadas': {}, 'metodo': {}}
    filas_juicio = []

    for T in sorted(temporadas_juicio):
        ent = ds[ds['temporada'] < T]
        jui = ds[ds['temporada'] == T]
        if len(ent) < 150 or not len(jui):
            resultados['temporadas'][T] = {'omitida': True, 'n_entrena': len(ent),
                                           'n_juicio': len(jui)}
            continue
        m = NFLModelo(ventana, arrastre).entrenar(ent, alpha=alpha)
        Xm = jui[COLS_MARGEN].values
        Xt = jui[COLS_TOTAL].values
        pm = m.m_margen.predecir(Xm)
        pt = m.m_total.predecir(Xt)
        g = jui.copy()
        g['pred_margen'] = pm
        g['pred_total'] = pt
        g['temporada_juicio'] = T
        # las dos formas de convertir margen esperado en probabilidad
        g['p_home_normal'] = 1.0 - _phi((0.5 - pm) / m.sigma_margen)
        g['p_home_emp'] = [float(np.mean(x + m.res_margen > 0.5)) for x in pm]
        filas_juicio.append(g)
        resultados['temporadas'][T] = {
            'n_entrena': int(len(ent)), 'n_juicio': int(len(jui)),
            'mae_margen': round(float(np.mean(np.abs(g['margen'] - pm))), 3),
            'mae_total': round(float(np.mean(np.abs(g['total'] - pt))), 3),
            'sigma_margen': round(m.sigma_margen, 2),
            'sigma_total': round(m.sigma_total, 2),
        }

    if not filas_juicio:
        return resultados
    J = pd.concat(filas_juicio, ignore_index=True)
    resultados['n_juicio_total'] = int(len(J))

    # --- 1. método de probabilidad: normal contra residuos empíricos -------
    y = (J['margen'] > 0).astype(int).values
    vivos = J['margen'] != 0
    for nombre, col in (('normal', 'p_home_normal'), ('empirico', 'p_home_emp')):
        p = np.clip(J[col].values, 1e-6, 1 - 1e-6)
        ll = float(-np.mean(y[vivos.values] * np.log(p[vivos.values])
                            + (1 - y[vivos.values]) * np.log(1 - p[vivos.values])))
        br = float(np.mean((p[vivos.values] - y[vivos.values]) ** 2))
        resultados['metodo'][nombre] = {'log_loss': round(ll, 5),
                                        'brier': round(br, 5)}
    mejor = min(resultados['metodo'], key=lambda k: resultados['metodo'][k]['log_loss'])
    resultados['metodo_elegido'] = mejor
    col_p = 'p_home_normal' if mejor == 'normal' else 'p_home_emp'

    # --- 2. contra el mercado, que es la única vara que importa ------------
    con_ml = J.dropna(subset=['ml_home', 'ml_away'])
    if len(con_ml):
        pmk = np.array([_devig_dos_vias(a, b)[0] for a, b in
                        zip(con_ml['ml_home'], con_ml['ml_away'])], dtype=float)
        ok = np.isfinite(pmk)
        sub = con_ml[ok]
        pmk = pmk[ok]
        ymk = (sub['margen'] > 0).astype(int).values
        pmod = np.clip(sub[col_p].values, 1e-6, 1 - 1e-6)
        vivo = sub['margen'].values != 0
        resultados['contra_mercado'] = {
            'n': int(vivo.sum()),
            'brier_modelo': round(float(np.mean((pmod[vivo] - ymk[vivo]) ** 2)), 5),
            'brier_mercado': round(float(np.mean((pmk[vivo] - ymk[vivo]) ** 2)), 5),
            'acierto_modelo': round(float(np.mean((pmod[vivo] > 0.5) == ymk[vivo].astype(bool))), 4),
            'acierto_mercado': round(float(np.mean((pmk[vivo] > 0.5) == ymk[vivo].astype(bool))), 4),
            'corr_margen_vs_linea': (
                round(float(np.corrcoef(sub['pred_margen'],
                                        -sub['hcp_home'].astype(float))[0, 1]), 4)
                if sub['hcp_home'].notna().sum() > 30 else None),
        }

    # --- 3. ROI al precio de cierre, por mercado ---------------------------
    resultados['roi'] = {}

    def _apostar(nombre, sel, cuota, gana, empuje=None):
        """Registra un canal: n, acierto, ROI y bootstrap p5."""
        sel = np.asarray(sel, dtype=bool)
        if sel.sum() < 20:
            resultados['roi'][nombre] = {'n': int(sel.sum()),
                                         'motivo': 'muestra corta'}
            return
        c = np.asarray(cuota, dtype=float)[sel]
        g = np.asarray(gana, dtype=bool)[sel]
        pnl = np.where(g, c - 1.0, -1.0)
        if empuje is not None:
            e = np.asarray(empuje, dtype=bool)[sel]
            pnl = np.where(e, 0.0, pnl)
        resultados['roi'][nombre] = {
            'n': int(sel.sum()), 'acierto': round(float(g.mean()), 4),
            'roi': round(float(pnl.mean()), 4),
            'p5': round(_bootstrap_p5(pnl), 4),
        }

    # 3a. moneyline al lado que el modelo prefiere
    if len(con_ml):
        cm = con_ml.reset_index(drop=True)
        p = cm[col_p].values
        elige_home = p > 0.5
        cuota = np.where(elige_home, cm['ml_home'].values.astype(float),
                         cm['ml_away'].values.astype(float))
        gana = np.where(elige_home, cm['margen'].values > 0, cm['margen'].values < 0)
        prob = np.where(elige_home, p, 1 - p)
        ev = cuota * prob - 1
        _apostar('moneyline_lado_del_modelo', np.ones(len(cm), bool), cuota, gana)
        _apostar('moneyline_ev_positivo', ev > 0, cuota, gana)
        _apostar('moneyline_ev_mayor_5pct', ev > 0.05, cuota, gana)
        _apostar('moneyline_prob_mayor_65pct', prob > 0.65, cuota, gana)
        # el contraste que exige la bitácora: comprar el favorito del MERCADO
        pm2 = np.array([_devig_dos_vias(a, b)[0] for a, b in
                        zip(cm['ml_home'], cm['ml_away'])], dtype=float)
        fav = pm2 > 0.5
        _apostar('moneyline_favorito_del_mercado', np.isfinite(pm2),
                 np.where(fav, cm['ml_home'].values.astype(float),
                          cm['ml_away'].values.astype(float)),
                 np.where(fav, cm['margen'].values > 0, cm['margen'].values < 0))

    # 3b. hándicap contra la línea de cierre
    ah = J.dropna(subset=['hcp_home']).reset_index(drop=True)
    if len(ah) >= 20:
        L = ah['hcp_home'].values.astype(float)
        margen = ah['margen'].values.astype(float)
        # el modelo elige el lado en el que su margen supera la línea
        elige_home = ah['pred_margen'].values > -L
        cubre_home = margen > -L
        push = np.abs(margen + L) < 1e-9
        gana = np.where(elige_home, cubre_home, ~cubre_home)
        ch = ah['hcp_cuota_home'].astype(float).fillna(1.91).values
        ca = ah['hcp_cuota_away'].astype(float).fillna(1.91).values
        cuota = np.where(elige_home, ch, ca)
        borde = np.abs(ah['pred_margen'].values + L)
        _apostar('handicap_lado_del_modelo', np.ones(len(ah), bool), cuota, gana, push)
        _apostar('handicap_discrepancia_mayor_3', borde > 3.0, cuota, gana, push)
        _apostar('handicap_discrepancia_mayor_6', borde > 6.0, cuota, gana, push)
        resultados['roi']['_linea_media'] = round(float(np.mean(np.abs(L))), 2)

    # 3c. total contra la línea de cierre
    at = J.dropna(subset=['total_cierre']).reset_index(drop=True)
    if len(at) >= 20:
        L = at['total_cierre'].values.astype(float)
        tot = at['total'].values.astype(float)
        over = at['pred_total'].values > L
        gana = np.where(over, tot > L, tot < L)
        push = np.abs(tot - L) < 1e-9
        # sin cuota publicada se usa la estándar del mercado (−110 = 1,909),
        # y se dice: es un supuesto, no un dato
        cuota = np.full(len(at), 1.909)
        borde = np.abs(at['pred_total'].values - L)
        _apostar('total_lado_del_modelo', np.ones(len(at), bool), cuota, gana, push)
        _apostar('total_discrepancia_mayor_3', borde > 3.0, cuota, gana, push)
        _apostar('total_discrepancia_mayor_6', borde > 6.0, cuota, gana, push)
        resultados['roi']['_cuota_total_supuesta'] = 1.909

    # --- 4. calibración por bandas (lo que se PUBLICA) ---------------------
    bandas = []
    p = J[col_p].values
    vivo = J['margen'].values != 0
    for lo, hi in ((0.5, 0.55), (0.55, 0.6), (0.6, 0.65), (0.65, 0.7),
                   (0.7, 0.8), (0.8, 1.0)):
        # se mira el lado favorito, sea el local o el visitante
        pf = np.where(p >= 0.5, p, 1 - p)
        acierta = np.where(p >= 0.5, J['margen'].values > 0, J['margen'].values < 0)
        sel = (pf >= lo) & (pf < hi) & vivo
        if sel.sum() < 10:
            continue
        bandas.append({'banda': f'{lo:.2f}-{hi:.2f}', 'n': int(sel.sum()),
                       'dice': round(float(pf[sel].mean()), 4),
                       'acierta': round(float(acierta[sel].mean()), 4)})
    resultados['calibracion'] = bandas
    # correlación margen/total: la que justifica la fórmula del total de equipo
    resultados['corr_margen_total'] = round(
        float(np.corrcoef(J['margen'], J['total'])[0, 1]), 4)
    return resultados


def barrer_ajustes(d: pd.DataFrame, temporadas_juicio: List[int]) -> List[Dict]:
    """
    Elige `ventana`, `arrastre` y `alpha` MIDIENDO, no suponiendo.

    Se ordena por log-loss fuera de muestra y no por ROI a propósito: elegir
    hiperparámetros por ROI sobre el mismo tramo con el que después se juzga es
    la forma más rápida de fabricar un hallazgo falso, y este proyecto ya tiene
    el retrato de uno (bitácora §2: el empate lucía +12,21 % en el tramo de
    elección y −7,09 % en el de juicio).
    """
    out = []
    for ventana in (6, 8, 10, 12):
        for arrastre in (0.0, 0.25, 0.35, 0.5):
            for alpha in (2.0, 5.0, 15.0):
                try:
                    r = backtest(d, temporadas_juicio, ventana, arrastre, alpha)
                except Exception as e:
                    logger.debug(f'[nfl] barrido {ventana}/{arrastre}/{alpha}: {e}')
                    continue
                met = r.get('metodo', {})
                if not met:
                    continue
                mejor = min(met.values(), key=lambda v: v['log_loss'])
                out.append({'ventana': ventana, 'arrastre': arrastre,
                            'alpha': alpha, 'log_loss': mejor['log_loss'],
                            'brier': mejor['brier'],
                            'metodo': r.get('metodo_elegido'),
                            'mae_margen': np.mean([t.get('mae_margen', np.nan)
                                                   for t in r['temporadas'].values()
                                                   if isinstance(t, dict)
                                                   and 'mae_margen' in t])})
    return sorted(out, key=lambda x: x['log_loss'])


if __name__ == '__main__':
    import argparse
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    ap = argparse.ArgumentParser()
    ap.add_argument('--barrer', action='store_true')
    ap.add_argument('--juicio', default='2024,2025')
    ap.add_argument('--entrenar', action='store_true')
    a = ap.parse_args()

    import nfl_datos as nd
    d = nd.cargar_historico()
    print(f'histórico: {len(d)} partidos '
          f'({d["fecha"].min().date()} → {d["fecha"].max().date()})')
    juicio = [int(x) for x in a.juicio.split(',')]

    if a.barrer:
        tabla = barrer_ajustes(d, juicio)
        print(f'\n{"vent":>5} {"arr":>5} {"alpha":>6} {"log-loss":>9} '
              f'{"brier":>8} {"MAE margen":>11} método')
        for r in tabla[:15]:
            print(f'{r["ventana"]:5d} {r["arrastre"]:5.2f} {r["alpha"]:6.1f} '
                  f'{r["log_loss"]:9.5f} {r["brier"]:8.5f} '
                  f'{r["mae_margen"]:11.3f} {r["metodo"]}')
        with open('nfl_barrido.json', 'w', encoding='utf-8') as f:
            json.dump(tabla, f, ensure_ascii=False, indent=1, default=float)

    r = backtest(d, juicio)
    print(json.dumps(r, ensure_ascii=False, indent=1, default=float))
    with open(CALIBRACION, 'w', encoding='utf-8') as f:
        json.dump(r, f, ensure_ascii=False, indent=1, default=float)

    if a.entrenar:
        ds = construir_dataset(d)
        m = NFLModelo().entrenar(ds)
        m.metodo_margen = r.get('metodo_elegido', 'normal')
        m.construir_estado(d)
        print('guardado en', m.guardar())
