#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Motor de inferencia + API de predicción (v3, arquitectura híbrida).

Consume el estado precalculado por update_team_stats.py (team_stats.json,
carga instantánea) y los goleadores REALES (jugadores_clave.csv), de modo
que cualquier par de las 48 selecciones puede enfrentarse en tiempo real:

    GET /predict?home=ARG&away=FRA
    GET /query?q=¿quién gana el México vs Ecuador?

Si team_stats.json no existe, reconstruye el estado replayando el histórico
(mismo EstadoRodante que el entrenamiento: paridad de features garantizada).
"""

import json
import os
import unicodedata
from typing import Dict, List, Optional, Tuple

import joblib
import numpy as np
import pandas as pd

from gtda.homology import VietorisRipsPersistence
from gtda.diagrams import PersistenceEntropy

import altitud
import arbitros
import feature_engineering as fe
from config import TEAMS, TEAM_STYLE, STADIUMS, CALENDARIO_FILE, HISTORICO_FILE

DIRECTORIO_MODELOS = 'modelos'
DRIFT_LOG = 'predicciones_log.json'   # última consulta por cruce (monitor de cambios)
NOMBRES_PAIS = {
    'MEX': 'México', 'USA': 'Estados Unidos', 'CAN': 'Canadá', 'ARG': 'Argentina',
    'BRA': 'Brasil', 'URU': 'Uruguay', 'COL': 'Colombia', 'ECU': 'Ecuador',
    'PER': 'Perú', 'CHI': 'Chile', 'FRA': 'Francia', 'ENG': 'Inglaterra',
    'ESP': 'España', 'GER': 'Alemania', 'ITA': 'Italia', 'POR': 'Portugal',
    'NED': 'Países Bajos', 'BEL': 'Bélgica', 'CRO': 'Croacia', 'SRB': 'Serbia',
    'MAR': 'Marruecos', 'SEN': 'Senegal', 'CMR': 'Camerún', 'GHA': 'Ghana',
    'NGA': 'Nigeria', 'TUN': 'Túnez', 'ALG': 'Argelia', 'EGY': 'Egipto',
    'JPN': 'Japón', 'KOR': 'Corea del Sur', 'IRN': 'Irán', 'AUS': 'Australia',
    'KSA': 'Arabia Saudita', 'QAT': 'Catar', 'CRC': 'Costa Rica',
    'PAN': 'Panamá', 'HON': 'Honduras', 'JAM': 'Jamaica',
    'PAR': 'Paraguay', 'NOR': 'Noruega', 'SUI': 'Suiza', 'DEN': 'Dinamarca',
    'AUT': 'Austria', 'SCO': 'Escocia', 'CIV': 'Costa de Marfil',
    'UZB': 'Uzbekistán', 'JOR': 'Jordania', 'NZL': 'Nueva Zelanda',
    'CPV': 'Cabo Verde',
}

# Priors neutrales si una selección aún no tiene historial suficiente
STATS_NEUTRALES = {
    'ELO': 1500.0, 'GF_MA5': 1.2, 'GA_MA5': 1.2, 'XGF_MA5': 1.25,
    'XGC_MA5': 1.25, 'SOTF_MA5': 4.0, 'SOTC_MA5': 4.0, 'AMAR_MA5': 1.8,
    'ROJAS_MA5': 0.08, 'FORMA_MA5': 0.5, 'N_PARTIDOS': 0,
    'G2H_MA5': 0.5, 'ENCU15_MA5': 0.3,
    'REACCION_TRAS_GOL': 'Neutra', 'REACCION_RATE': 0.30,
    'RENDIMIENTO_2DA_MITAD': 'Estable', 'PCT_GOLES_2H': 0.5,
    'GOLES_ENC_U15_24M': 0.3, 'PARTIDOS_30D': 3,
}


def _sin_acentos(texto: str) -> str:
    return ''.join(c for c in unicodedata.normalize('NFD', texto)
                   if unicodedata.category(c) != 'Mn').lower()


def prob_over(lam: float, linea: float) -> float:
    """P(Poisson(λ) > línea) para líneas x.5 (cola superior exacta)."""
    from scipy.stats import poisson as _p
    return float(1 - _p.cdf(int(np.floor(linea)), max(lam, 1e-9)))


def cuota_americana(prob: float) -> str:
    """Cuota justa (1/p) en formato americano: -116, +266, etc."""
    p = float(np.clip(prob, 0.005, 0.995))
    decimal = 1.0 / p
    if decimal < 2.0:
        return f"-{round(100 / (decimal - 1)):.0f}".replace('--', '-')
    return f"+{round((decimal - 1) * 100):.0f}"


class PredictionEngine:
    """Carga artefactos una sola vez y responde predicciones {home, away}."""

    def __init__(self, directorio: str = '.'):
        self.dir = directorio
        self.listo = False
        self.error = None
        try:
            self._cargar()
            self.listo = True
        except Exception as e:
            self.error = f"{type(e).__name__}: {e}"

    # ------------------------------------------------------------------ #
    # Carga de artefactos                                                  #
    # ------------------------------------------------------------------ #
    def _ruta(self, *partes) -> str:
        return os.path.join(self.dir, *partes)

    def _cargar(self):
        self.modelo = joblib.load(self._ruta(DIRECTORIO_MODELOS, 'modelo_tda.joblib'))
        self.escalador = joblib.load(self._ruta(DIRECTORIO_MODELOS, 'escalador.joblib'))
        with open(self._ruta(DIRECTORIO_MODELOS, 'metadata.json'), 'r', encoding='utf-8') as f:
            self.metadata = json.load(f)

        # Regresores de goles esperados (Poisson); si faltan, hay heurística
        self.reg_goles_local = self.reg_goles_visit = None
        try:
            self.reg_goles_local = joblib.load(self._ruta(DIRECTORIO_MODELOS, 'reg_goles_local.joblib'))
            self.reg_goles_visit = joblib.load(self._ruta(DIRECTORIO_MODELOS, 'reg_goles_visit.joblib'))
        except Exception:
            pass

        # Calibración StatsBomb (relaciones xG↔remates para secciones 8 y 9)
        try:
            with open(self._ruta('calibracion_statsbomb.json'), 'r', encoding='utf-8') as f:
                self.calibracion = json.load(f)
        except Exception:
            self.calibracion = {'shots_on_por_xg': 3.1, 'shots_total_por_on': 2.6}

        # Estado precalculado (rápido) o replay del histórico (fallback)
        ruta_stats = self._ruta('team_stats.json')
        if os.path.exists(ruta_stats):
            with open(ruta_stats, 'r', encoding='utf-8') as f:
                ts = json.load(f)
            self.stats_equipos: Dict[str, Dict] = ts['equipos']
            self.h2h: Dict[str, float] = ts.get('h2h', {})
            self.fecha_estado = ts.get('ultima_fecha_historico', '?')
            self.generado = ts.get('generado', '?')
        else:
            historico = pd.read_csv(self._ruta(HISTORICO_FILE), parse_dates=['date'])
            estado = fe.construir_dataset_supervisado(historico)['estado']
            self.stats_equipos = {}
            for t in TEAMS:
                s = estado.stats_equipo(t)
                s['PERF10'] = [list(map(float, v)) for v in estado.perf10[t]]
                self.stats_equipos[t] = s
            self.h2h = {}
            for i, a in enumerate(TEAMS):
                for b in TEAMS[i + 1:]:
                    bal = estado.h2h_balance(a, b)
                    if bal != 0.0:
                        self.h2h[f"{a}|{b}"] = bal
            self.fecha_estado = str(historico['date'].max().date())
            self.generado = self.fecha_estado

        # Goleadores reales (opcional pero recomendado)
        try:
            self.jugadores_clave = pd.read_csv(self._ruta('jugadores_clave.csv'))
        except Exception:
            self.jugadores_clave = pd.DataFrame()

        try:
            self.calendario = pd.read_csv(self._ruta(CALENDARIO_FILE), parse_dates=['date'])
        except Exception:
            self.calendario = pd.DataFrame(columns=['match_id', 'home', 'away', 'stadium', 'date'])

        try:
            with open(self._ruta('fuente_datos.json'), 'r', encoding='utf-8') as f:
                fuente_info = json.load(f)
            self.fuente = fuente_info.get('source', 'synthetic')
            self.fuente_detalle = fuente_info.get('detalle', '')
        except Exception:
            self.fuente, self.fuente_detalle = 'synthetic', ''

        self.equipos = sorted(TEAMS)

    # ------------------------------------------------------------------ #
    # Estado de equipos y contexto                                         #
    # ------------------------------------------------------------------ #
    def stats_equipo(self, equipo: str) -> Dict:
        s = self.stats_equipos.get(equipo, {})
        if not s or s.get('N_PARTIDOS', 0) == 0:
            return dict(STATS_NEUTRALES)
        return s

    def h2h_balance(self, local: str, visitante: str) -> float:
        if f"{local}|{visitante}" in self.h2h:
            return float(self.h2h[f"{local}|{visitante}"])
        if f"{visitante}|{local}" in self.h2h:
            return -float(self.h2h[f"{visitante}|{local}"])
        return 0.0

    def _estadio_del_cruce(self, home: str, away: str) -> Optional[str]:
        cal = self.calendario
        for h, a in [(home, away), (away, home)]:
            fila = cal[(cal['home'] == h) & (cal['away'] == a)]
            if not fila.empty:
                return fila.iloc[0]['stadium']
        return None

    def _contexto(self, home: str, away: str, estadio: Optional[str]) -> Dict:
        altura = STADIUMS.get(estadio, 0) if estadio else 0
        return {
            'CHOQUE_ESTILOS': fe.choque_estilos(home, away),
            'ALTURA_NORM': float(altura) / fe.ALTURA_MAXIMA,
            'VENTAJA_LOCALIA': fe.VENTAJA_LOCALIA_ESTADIO.get(estadio, 0.55) if estadio else 0.55,
            'CLIMA_TEMP_NORM': (fe.CLIMA_ESTADIO_TEMP_C.get(estadio, 25) if estadio else 25) / 40.0,
            'H2H_BALANCE': self.h2h_balance(home, away),
        }

    def _entropias(self, nube: np.ndarray) -> np.ndarray:
        vr = VietorisRipsPersistence(homology_dimensions=[0, 1], n_jobs=-1)
        diag = vr.fit_transform(nube[np.newaxis, :, :])
        return PersistenceEntropy(nan_fill_value=0.0).fit_transform(diag)[0]

    def _features_topo(self, home: str, away: str, s_l: Dict, s_v: Dict,
                       ctx: Dict) -> np.ndarray:
        """Las 6 entropías del entrenamiento: par + últimos 10 de cada equipo."""
        ent_par = self._entropias(fe.nube_de_puntos(s_l, s_v, ctx))
        entropias = [ent_par]
        for equipo in (home, away):
            perf = self.stats_equipos.get(equipo, {}).get('PERF10', [])
            if perf:
                entropias.append(self._entropias(fe.nube_equipo(perf)))
            else:
                entropias.append(np.zeros(2))
        return np.concatenate(entropias)

    # ------------------------------------------------------------------ #
    # Goles esperados y Monte Carlo                                        #
    # ------------------------------------------------------------------ #
    def _lambdas_goles(self, home: str, away: str, s_l: Dict, s_v: Dict,
                       altura: float, X: Optional[np.ndarray] = None) -> Tuple[float, float]:
        """
        λ del Poisson bivariado. Fuente primaria: regresores entrenados
        (HistGradientBoosting con pérdida Poisson) sobre el mismo vector de
        features del clasificador. Fallback: heurística de medias móviles.
        """
        if X is not None and self.reg_goles_local is not None:
            lam_h = float(self.reg_goles_local.predict(X)[0])
            lam_a = float(self.reg_goles_visit.predict(X)[0])
            return float(np.clip(lam_h, 0.2, 3.5)), float(np.clip(lam_a, 0.2, 3.5))
        # Fallback heurístico (la capa de aclimatación se aplica después)
        lam_h = 0.55 * s_l['XGF_MA5'] + 0.45 * s_v['XGC_MA5']
        lam_a = 0.55 * s_v['XGF_MA5'] + 0.45 * s_l['XGC_MA5']
        lam_h *= 1.15  # localía media real
        return float(np.clip(lam_h, 0.2, 3.5)), float(np.clip(lam_a, 0.2, 3.5))

    @staticmethod
    def _monte_carlo(lam_h: float, lam_a: float, probs_modelo: np.ndarray,
                     n_sims: int = 20000, max_goles: int = 6):
        """
        Poisson bivariado (choque común) -> matriz de marcadores exactos,
        re-ponderada para que sus marginales 1X2 coincidan con las
        probabilidades CALIBRADAS del clasificador.
        """
        rng = np.random.default_rng(2026)
        lam_comun = 0.12 * min(lam_h, lam_a)
        comun = rng.poisson(lam_comun, n_sims)
        goles_h = np.clip(rng.poisson(max(0.05, lam_h - lam_comun), n_sims) + comun, 0, max_goles)
        goles_a = np.clip(rng.poisson(max(0.05, lam_a - lam_comun), n_sims) + comun, 0, max_goles)

        matriz = np.zeros((max_goles + 1, max_goles + 1))
        for gh, ga in zip(goles_h, goles_a):
            matriz[gh, ga] += 1
        matriz /= n_sims

        idx = np.arange(max_goles + 1)
        regiones = [
            (matriz * (idx[:, None] > idx[None, :]), probs_modelo[0]),
            (matriz * (idx[:, None] == idx[None, :]), probs_modelo[1]),
            (matriz * (idx[:, None] < idx[None, :]), probs_modelo[2]),
        ]
        matriz_cal = np.zeros_like(matriz)
        for region, p_obj in regiones:
            masa = region.sum()
            if masa > 1e-9:
                matriz_cal += region * (p_obj / masa)
        matriz_cal /= matriz_cal.sum()

        gh_star, ga_star = np.unravel_index(np.argmax(matriz_cal), matriz_cal.shape)
        return matriz_cal, (int(gh_star), int(ga_star)), float(matriz_cal[gh_star, ga_star])

    @staticmethod
    def _linea_de_tiempo(lam_h: float, lam_a: float,
                         pct_2h: float = 0.5, enc_u15: float = 0.3) -> List[Dict]:
        """
        Perfil minuto a minuto ajustado con los MINUTOS DE GOL REALES de ambos
        equipos: pct_2h (fracción media de goles en 2ª mitad) desplaza masa a
        la segunda parte, y enc_u15 (goles encajados en los últimos 15')
        intensifica el tramo final.
        """
        pesos = np.ones(90)
        pesos[40:45] *= 1.35
        pesos[60:75] *= 1.15
        pesos[75:90] *= 1.45
        pesos[45:] *= float(np.clip(pct_2h / 0.5, 0.85, 1.25))
        pesos[75:] *= float(np.clip(1 + 0.5 * (enc_u15 - 0.3), 0.9, 1.35))
        pesos /= pesos.sum()
        lam_total = lam_h + lam_a
        return [
            {'minuto': m + 1,
             'prob_gol': round(float(1 - np.exp(-lam_total * pesos[m])), 4),
             'goles_esperados_acumulados': round(float(lam_total * pesos[:m + 1].sum()), 3)}
            for m in range(90)
        ]

    # ------------------------------------------------------------------ #
    # Jugadores clave (goleadores REALES de Kaggle)                        #
    # ------------------------------------------------------------------ #
    def _jugadores_clave(self, equipo: str, top_n: int = 3) -> List[Dict]:
        df = self.jugadores_clave
        if df.empty:
            return []
        df = df[df['EQUIPO_NOMBRE'] == equipo].sort_values('GOLES_24M', ascending=False).head(top_n)
        return [{
            'nombre': r['JUGADOR_NOMBRE'],
            'goles_24m': int(r['GOLES_24M']),
            'penales_24m': int(r.get('PENALES_24M', 0)),
            'goles_esperados': round(float(r['XG_ESTIMADO_PARTIDO']), 2),
            'remates_totales': round(float(r['REMATES_TOTALES_ESTIMADOS']), 2),
            'remates_al_arco': round(float(r['REMATES_ARCO_ESTIMADOS']), 2),
            'partidos_marcando_de_5': int(r['PARTIDOS_MARCANDO_DE_5']),
            'prob_marcar': round(float(r['PROB_MARCAR']), 3),
        } for _, r in df.iterrows()]

    # ------------------------------------------------------------------ #
    # Insights en lenguaje natural                                          #
    # ------------------------------------------------------------------ #
    def _insights(self, home: str, away: str, s_l: Dict, s_v: Dict,
                  ctx: Dict, lam_h: float, lam_a: float,
                  clave_local: Optional[Dict], clave_visit: Optional[Dict]) -> Tuple[List[str], str]:
        n_l, n_v = NOMBRES_PAIS.get(home, home), NOMBRES_PAIS.get(away, away)
        insights, factores = [], []

        altura = ctx['ALTURA_NORM'] * fe.ALTURA_MAXIMA
        if altura >= 1500:
            if altitud.esta_aclimatado(home) and not altitud.esta_aclimatado(away):
                frase = (f"La altitud de la sede ({altura:.0f} m sobre el nivel del mar) "
                         f"juega a favor de {n_l}: {n_v} está {altitud.nivel_aclimatacion(away)}.")
                insights.append(frase)
                factores.append((0.9, frase))
            elif altitud.esta_aclimatado(away) and not altitud.esta_aclimatado(home):
                frase = (f"Sede en altura ({altura:.0f} m) y es {n_v} quien está aclimatado; "
                         f"{n_l} está {altitud.nivel_aclimatacion(home)}.")
                insights.append(frase)
                factores.append((0.6, frase))
            else:
                insights.append(f"El partido se juega a {altura:.0f} m de altitud, "
                                f"una condición exigente para ambos equipos.")

        dif_elo = s_l['ELO'] - s_v['ELO']
        if abs(dif_elo) >= 60:
            fuerte, debil = (n_l, n_v) if dif_elo > 0 else (n_v, n_l)
            frase = (f"{fuerte} llega con un nivel general claramente superior al de "
                     f"{debil} (diferencia de {abs(dif_elo):.0f} puntos de ranking dinámico).")
            insights.append(frase)
            factores.append((abs(dif_elo) / 200.0, frase))

        if s_l['GF_MA5'] > s_v['GA_MA5'] and s_l['GF_MA5'] >= 1.5:
            insights.append(
                f"{n_l} promedia {s_l['GF_MA5']:.1f} goles por partido en sus últimos 5, "
                f"más de lo que {n_v} suele recibir ({s_v['GA_MA5']:.1f}): hay buenas "
                f"opciones de que {n_l} anote al menos {max(1, round(lam_h - 0.4))} gol(es).")
        if s_v['GF_MA5'] > s_l['GA_MA5'] and s_v['GF_MA5'] >= 1.5:
            insights.append(
                f"Cuidado atrás: {n_v} promedia {s_v['GF_MA5']:.1f} goles en sus últimos "
                f"5 partidos y la defensa de {n_l} recibe {s_l['GA_MA5']:.1f}.")

        dif_forma = s_l['FORMA_MA5'] - s_v['FORMA_MA5']
        if abs(dif_forma) >= 0.25:
            caliente, frio = (n_l, n_v) if dif_forma > 0 else (n_v, n_l)
            frase = f"{caliente} atraviesa un momento mucho mejor que {frio} en sus últimos 5 partidos."
            insights.append(frase)
            factores.append((abs(dif_forma), frase))

        if s_v['ROJAS_MA5'] >= 0.3:
            insights.append(f"{n_v} viene mostrando indisciplina: promedia "
                            f"{s_v['ROJAS_MA5']:.1f} expulsiones en sus últimos partidos.")
        if s_l['ROJAS_MA5'] >= 0.3:
            insights.append(f"{n_l} debe cuidarse de las tarjetas: promedia "
                            f"{s_l['ROJAS_MA5']:.1f} expulsiones recientes.")

        if ctx['H2H_BALANCE'] >= 0.4:
            frase = f"El historial reciente entre ambos favorece claramente a {n_l}."
            insights.append(frase)
            factores.append((ctx['H2H_BALANCE'] * 0.7, frase))
        elif ctx['H2H_BALANCE'] <= -0.4:
            frase = f"El historial reciente entre ambos favorece claramente a {n_v}."
            insights.append(frase)
            factores.append((abs(ctx['H2H_BALANCE']) * 0.7, frase))

        # Carácter con minutos de gol REALES: reacción y tramos finales
        for s, propio, rival_nombre in [(s_v, n_v, n_l), (s_l, n_l, n_v)]:
            if float(s.get('ENCU15_MA5', 0.3)) >= 0.6:
                insights.append(
                    f"{propio} ha encajado {s['ENCU15_MA5']:.1f} goles por partido en los "
                    f"últimos 15 minutos: ojo al final del partido.")
                break
        reaccion_v = str(s_v.get('REACCION_TRAS_GOL', ''))
        if reaccion_v.startswith('Débil') and lam_h >= 1.2:
            insights.append(
                f"Si {n_l} golpea primero, cuidado: {n_v} se desorganiza tras recibir gol "
                f"(solo responde en el {s_v.get('REACCION_RATE', 0.3)*100:.0f} % de los casos).")
        elif str(s_l.get('REACCION_TRAS_GOL', '')).startswith('Fuerte'):
            insights.append(
                f"{n_l} reacciona bien tras encajar: responde con gol en el "
                f"{s_l.get('REACCION_RATE', 0.3)*100:.0f} % de los casos.")

        # Jugador clave con datos REALES de goleadores
        for jugador, equipo_nombre in [(clave_local, n_l), (clave_visit, n_v)]:
            if jugador and jugador.get('goles_24m', 0) >= 3:
                extra = ""
                if jugador.get('partidos_marcando_de_5', 0) >= 2:
                    extra = (f" y anotó en {jugador['partidos_marcando_de_5']} de los "
                             f"últimos 5 partidos de su selección")
                insights.append(
                    f"El jugador clave: {jugador['nombre']} ({equipo_nombre}) suma "
                    f"{jugador['goles_24m']} goles reales en los últimos 24 meses{extra} — "
                    f"probabilidad de marcar hoy: {jugador['prob_marcar']*100:.0f} %.")
                break

        factor_decisivo = (max(factores, key=lambda x: x[0])[1] if factores
                           else f"Partido muy parejo: la diferencia la harán los detalles "
                                f"(se esperan {lam_h + lam_a:.1f} goles en total).")
        if not insights:
            insights.append("Los números de ambos equipos están muy igualados; "
                            "se espera un partido cerrado.")
        return insights[:6], factor_decisivo

    # ------------------------------------------------------------------ #
    # Monitor de cambios: qué features variaron desde la consulta anterior #
    # (auditoría EGY vs AUS: da transparencia a cualquier fluctuación)     #
    # ------------------------------------------------------------------ #
    def _monitor_cambios(self, home: str, away: str,
                         features: Dict[str, float], probs: np.ndarray) -> Optional[Dict]:
        clave = f"{home}|{away}"
        try:
            log = {}
            ruta = self._ruta(DRIFT_LOG)
            if os.path.exists(ruta):
                with open(ruta, 'r', encoding='utf-8') as f:
                    log = json.load(f)
            anterior = log.get(clave)
            cambios = []
            if anterior:
                for k, v in features.items():
                    actual = round(float(v), 4)   # misma precisión que lo almacenado
                    previo = float(anterior['features'].get(k, actual))
                    if abs(actual - previo) > 5e-4:
                        cambios.append({'feature': k, 'antes': round(previo, 3),
                                        'ahora': round(actual, 3),
                                        'delta': round(actual - previo, 3)})
                cambios.sort(key=lambda c: abs(c['delta']), reverse=True)
                cambios = cambios[:3]
            log[clave] = {'fecha': pd.Timestamp.today().strftime('%Y-%m-%d %H:%M'),
                          'estado_al': self.fecha_estado,
                          'features': {k: round(float(v), 4) for k, v in features.items()},
                          'probs': [round(float(p), 4) for p in probs]}
            with open(ruta, 'w', encoding='utf-8') as f:
                json.dump(log, f, ensure_ascii=False)
            if anterior:
                return {'anterior': {'fecha': anterior['fecha'],
                                     'estado_al': anterior.get('estado_al', '?'),
                                     'probs': anterior['probs']},
                        'cambios': cambios}
            return None
        except Exception:
            return None  # el monitor nunca debe tumbar una predicción

    # ------------------------------------------------------------------ #
    # API principal                                                        #
    # ------------------------------------------------------------------ #
    def predecir(self, home: str, away: str, arbitro: Optional[str] = None,
                 fase: str = 'grupos', estadio: Optional[str] = None) -> Dict:
        """Predicción completa para CUALQUIER par de las 48 selecciones."""
        if not self.listo:
            return {'error': f"Motor no inicializado: {self.error}"}
        if home not in self.equipos or away not in self.equipos:
            return {'error': f"Equipo desconocido. Disponibles: {', '.join(self.equipos)}"}
        if home == away:
            return {'error': "Local y visitante no pueden ser el mismo equipo."}

        s_l, s_v = self.stats_equipo(home), self.stats_equipo(away)
        # Sede: explícita > fixture oficial > MetLife (2 m) por defecto
        if not estadio or estadio not in STADIUMS:
            estadio = self._estadio_del_cruce(home, away) or altitud.ESTADIO_POR_DEFECTO
        ctx = self._contexto(home, away, estadio)

        vector = np.array([fe.vector_features(s_l, s_v, ctx)])
        vector_norm = self.escalador.transform(pd.DataFrame(vector, columns=fe.FEATURES_MODELO))
        topo = self._features_topo(home, away, s_l, s_v, ctx)
        X = np.hstack([vector_norm, topo.reshape(1, -1)])
        # Si el modelo se entrenó con cuotas de apertura (backtesting), en vivo
        # no existen: se imputa la media del entrenamiento, como prevé la spec.
        odds_cfg = self.metadata.get('odds_features') or {}
        if odds_cfg.get('activas') and odds_cfg.get('medias_train'):
            X = np.hstack([X, np.array(odds_cfg['medias_train']).reshape(1, -1)])
        probs_crudas = self.modelo.predict_proba(X)[0]
        probs = np.zeros(3)
        for clase, p in zip(self.modelo.classes_, probs_crudas):
            probs[int(clase)] = p
        probs /= probs.sum()

        altura = altitud.altitud_estadio(estadio)
        lam_h, lam_a = self._lambdas_goles(home, away, s_l, s_v, altura, X)
        # Ajuste de reacción tras gol (más acentuado en eliminación directa)
        lam_h, lam_a = arbitros.ajuste_reaccion_eliminatoria(
            lam_h, lam_a,
            s_l.get('REACCION_TRAS_GOL', 'Neutra'),
            s_v.get('REACCION_TRAS_GOL', 'Neutra'), fase)
        # Capa de aclimatación: penalizaciones/bono por altitud de la sede
        lam_h, lam_a, detalle_altitud = altitud.ajustar_xg_por_altitud(
            lam_h, lam_a, home, away, altura)
        matriz, marcador, p_marcador = self._monte_carlo(lam_h, lam_a, probs)
        # 2ª mitad: el no aclimatado en altura baja un escalón su rendimiento
        pct_2h_medio = (altitud.ajuste_2da_mitad(float(s_l.get('PCT_GOLES_2H', 0.5)), home, altura) +
                        altitud.ajuste_2da_mitad(float(s_v.get('PCT_GOLES_2H', 0.5)), away, altura)) / 2
        enc_u15_medio = (float(s_l.get('ENCU15_MA5', 0.3)) + float(s_v.get('ENCU15_MA5', 0.3))) / 2
        timeline = self._linea_de_tiempo(lam_h, lam_a, pct_2h_medio, enc_u15_medio)

        clave_l = self._jugadores_clave(home)
        clave_v = self._jugadores_clave(away)
        insights, factor = self._insights(
            home, away, s_l, s_v, ctx, lam_h, lam_a,
            clave_l[0] if clave_l else None, clave_v[0] if clave_v else None)

        # Perfil arbitral (opcional): tarjetas y penaltis correlacionados
        nombre_arb, perfil_arb = arbitros.perfil_arbitro(arbitro)
        tarjetas = arbitros.modelo_tarjetas(
            perfil_arb, s_l['AMAR_MA5'], s_l['ROJAS_MA5'],
            s_v['AMAR_MA5'], s_v['ROJAS_MA5'],
            estilo_local=TEAM_STYLE.get(home, 'bloque_bajo'),
            estilo_visit=TEAM_STYLE.get(away, 'bloque_bajo'),
            fase=fase)
        penaltis = arbitros.modelo_penaltis(perfil_arb, lam_h, lam_a)
        if arbitro and arbitro in arbitros.ARBITROS:
            insights.append(arbitros.descripcion_arbitro(nombre_arb, perfil_arb))

        ganador_idx = int(np.argmax(probs))
        ganador = [NOMBRES_PAIS.get(home, home), 'Empate', NOMBRES_PAIS.get(away, away)][ganador_idx]

        monitor = self._monitor_cambios(
            home, away, dict(zip(fe.FEATURES_MODELO, vector[0])), probs)

        resultado = {
            'match': f"{home} vs {away}",
            'stadium': estadio,
            'estado_al': self.fecha_estado,
            'fase': fase,
            'altitude': detalle_altitud,
            'monitor_cambios': monitor,
            'referee': {'nombre': nombre_arb, **perfil_arb},
            'cards': tarjetas,
            'penalties': penaltis,
            'character': {
                'home': {'reaccion_tras_gol': s_l.get('REACCION_TRAS_GOL', 'Neutra'),
                         'rendimiento_2da_mitad': s_l.get('RENDIMIENTO_2DA_MITAD', 'Estable'),
                         'goles_encajados_ult15': float(s_l.get('ENCU15_MA5', 0.3)),
                         'partidos_30d': int(s_l.get('PARTIDOS_30D', 3))},
                'away': {'reaccion_tras_gol': s_v.get('REACCION_TRAS_GOL', 'Neutra'),
                         'rendimiento_2da_mitad': s_v.get('RENDIMIENTO_2DA_MITAD', 'Estable'),
                         'goles_encajados_ult15': float(s_v.get('ENCU15_MA5', 0.3)),
                         'partidos_30d': int(s_v.get('PARTIDOS_30D', 3))},
            },
            'prediction': {
                'winner': ganador,
                'confidence': round(float(probs[ganador_idx]), 3),
                'probabilities': {
                    'home': round(float(probs[0]), 3),
                    'draw': round(float(probs[1]), 3),
                    'away': round(float(probs[2]), 3),
                },
                'most_likely_score': f"{marcador[0]}-{marcador[1]}",
                'score_probability': round(p_marcador, 3),
                'total_goals_expected': round(lam_h + lam_a, 2),
                'expected_goals': {'home': round(lam_h, 2), 'away': round(lam_a, 2)},
            },
            'decisive_factor': factor,
            'insights': insights,
            'key_players': {'home': clave_l, 'away': clave_v},
            'score_matrix': matriz.round(4).tolist(),
            'timeline': timeline,
            'data_source': self.fuente,
            'data_source_detail': self.fuente_detalle,
            'model': {
                'accuracy_backtest': self.metadata.get('precision_validacion'),
                'log_loss_backtest': self.metadata.get('log_loss_validacion'),
                'deploy_ready': self.metadata.get('deploy_ready', False),
            },
        }
        if self.fuente == 'synthetic':
            resultado['warning'] = "Datos estimados – precisión limitada (fuentes reales no disponibles)."
        if not self.metadata.get('deploy_ready', False):
            resultado['warning'] = (resultado.get('warning', '') +
                                    " El modelo no superó el umbral de precisión del 55 %: úsalo solo como referencia.").strip()
        return resultado

    # ------------------------------------------------------------------ #
    # Intérprete de consultas en texto libre                               #
    # ------------------------------------------------------------------ #
    def detectar_equipos(self, texto: str) -> List[str]:
        t = _sin_acentos(texto)
        alias = {_sin_acentos(v): k for k, v in NOMBRES_PAIS.items()}
        alias.update({'eeuu': 'USA', 'estados unidos': 'USA', 'brasil': 'BRA',
                      'corea': 'KOR', 'inglaterra': 'ENG', 'alemania': 'GER',
                      'espana': 'ESP', 'mejico': 'MEX', 'holanda': 'NED'})
        encontrados = []
        for nombre, codigo in alias.items():
            if nombre in t and codigo not in [c for _, c in encontrados]:
                encontrados.append((t.index(nombre), codigo))
        for codigo in self.equipos:
            if codigo.lower() in t.split() and codigo not in [c for _, c in encontrados]:
                encontrados.append((t.index(codigo.lower()), codigo))
        return [c for _, c in sorted(encontrados)]

    def responder_consulta(self, texto: str,
                           equipos_por_defecto: Tuple[str, str] = None) -> Dict:
        t = _sin_acentos(texto)
        equipos = self.detectar_equipos(texto)

        # --- Máximo rematador / goleador (solo requiere UN equipo) ------- #
        if any(p in t for p in ['remata', 'rematador', 'remates', 'goleador',
                                'artillero', 'dispara', 'tira mas']):
            if equipos:
                objetivo = equipos[0]
            elif equipos_por_defecto:
                objetivo = equipos_por_defecto[0]
            else:
                return {'tipo': 'error',
                        'mensaje': "Dime de qué selección quieres los rematadores (p. ej. 'de México')."}
            jugadores = self._jugadores_clave(objetivo, top_n=8)
            return {'tipo': 'rematadores', 'equipo': objetivo,
                    'equipo_nombre': NOMBRES_PAIS.get(objetivo, objetivo),
                    'jugadores': jugadores}

        if len(equipos) >= 2:
            home, away = equipos[0], equipos[1]
        elif equipos_por_defecto:
            home, away = equipos_por_defecto
            if len(equipos) == 1 and equipos[0] not in (home, away):
                home = equipos[0]
        else:
            return {'tipo': 'error',
                    'mensaje': "Menciona al menos los dos equipos del partido (p. ej. 'México vs Ecuador')."}

        # --- Riesgo de expulsión (a nivel de equipo: dato disciplinario) -- #
        if any(p in t for p in ['expuls', 'roja', 'tarjeta']):
            candidatos = []
            for eq in (home, away):
                s = self.stats_equipo(eq)
                candidatos.append({
                    'equipo': NOMBRES_PAIS.get(eq, eq),
                    'rojas_ma5': round(float(s['ROJAS_MA5']), 2),
                    'amarillas_ma5': round(float(s['AMAR_MA5']), 2),
                    'prob_expulsion_partido': round(float(min(0.45, 0.05 + 0.9 * s['ROJAS_MA5'] +
                                                              0.02 * s['AMAR_MA5'])), 3),
                })
            candidatos.sort(key=lambda x: x['prob_expulsion_partido'], reverse=True)
            return {'tipo': 'expulsiones', 'candidatos': candidatos}

        # --- Goles esperados ---------------------------------------------- #
        if 'goles' in t and any(p in t for p in ['cuantos', 'esperan', 'espera', 'total', 'promedio']):
            pred = self.predecir(home, away)
            if 'error' in pred:
                return {'tipo': 'error', 'mensaje': pred['error']}
            return {'tipo': 'goles_esperados', 'match': pred['match'],
                    'total': pred['prediction']['total_goals_expected'],
                    'desglose': pred['prediction']['expected_goals'],
                    'marcador_mas_probable': pred['prediction']['most_likely_score']}

        # --- Análisis completo --------------------------------------------- #
        if any(p in t for p in ['analisis', 'completo', 'todo', 'detalle', 'reporte']):
            return {'tipo': 'analisis_completo', 'prediccion': self.predecir(home, away)}

        # --- Por defecto: ¿quién gana? -------------------------------------- #
        pred = self.predecir(home, away)
        if 'error' in pred:
            return {'tipo': 'error', 'mensaje': pred['error']}
        return {'tipo': 'ganador', 'prediccion': pred}


    # ------------------------------------------------------------------ #
    # DISTRIBUCIONES: probabilidad exacta de cada línea over/under          #
    # (Mejora 2 de la v12 — todos los mercados cuantitativos)               #
    # ------------------------------------------------------------------ #
    def distribuciones(self, home: str, away: str, arbitro: Optional[str] = None,
                       fase: str = 'grupos', estadio: Optional[str] = None) -> Dict:
        """
        Probabilidades de superar las líneas comunes de cada mercado.
        Goles: derivados de la matriz Monte Carlo calibrada (marginales).
        Córners/tarjetas/remates: colas Poisson con las λ del partido
        (mismas fuentes que la plantilla: StatsBomb + modelo arbitral v3).
        """
        pred = self.predecir(home, away, arbitro=arbitro, fase=fase, estadio=estadio)
        if 'error' in pred:
            return pred
        M = np.array(pred['score_matrix'])
        idx = np.arange(M.shape[0])
        total_idx = idx[:, None] + idx[None, :]
        lam_h = pred['prediction']['expected_goals']['home']
        lam_a = pred['prediction']['expected_goals']['away']
        spx = float(self.calibracion.get('shots_on_por_xg', 3.1))
        tpo = float(self.calibracion.get('shots_total_por_on', 2.6))
        sot_tot = (lam_h + lam_a) * spx
        shots_tot = sot_tot * tpo
        t = pred['cards']
        cards_h = t['amarillas_local'] + t['rojas_local']
        cards_a = t['amarillas_visitante'] + t['rojas_visitante']
        extra_alt = 0.2 if pred.get('altitude', {}).get('altitud_sede', 0) > 1500 else 0.0
        ck_h = 2.0 + 0.25 * lam_h * spx * tpo + extra_alt / 2
        ck_a = 2.0 + 0.25 * lam_a * spx * tpo + extra_alt / 2
        pct = lambda x: round(float(x) * 100, 1)

        def marginal_over(eje: int, linea: float) -> float:
            g = M.sum(axis=1 - eje)          # marginal de goles del equipo
            return float(g[int(np.floor(linea)) + 1:].sum())

        mercados = {
            'goles_totales': {f'over_{l}': pct(M[total_idx > l].sum())
                              for l in (0.5, 1.5, 2.5, 3.5, 4.5)},
            'goles_local': {f'over_{l}': pct(marginal_over(0, l)) for l in (0.5, 1.5, 2.5)},
            'goles_visitante': {f'over_{l}': pct(marginal_over(1, l)) for l in (0.5, 1.5, 2.5)},
            'corners_totales': {f'over_{l}': pct(prob_over(ck_h + ck_a, l))
                                for l in (6.5, 7.5, 8.5, 9.5, 10.5)},
            'corners_local': {f'over_{l}': pct(prob_over(ck_h, l)) for l in (2.5, 3.5, 4.5, 5.5)},
            'corners_visitante': {f'over_{l}': pct(prob_over(ck_a, l)) for l in (2.5, 3.5, 4.5, 5.5)},
            'tarjetas_totales': {f'over_{l}': pct(prob_over(cards_h + cards_a, l))
                                 for l in (2.5, 3.5, 4.5, 5.5)},
            'tarjetas_local': {f'over_{l}': pct(prob_over(cards_h, l)) for l in (1.5, 2.5)},
            'tarjetas_visitante': {f'over_{l}': pct(prob_over(cards_a, l)) for l in (1.5, 2.5)},
            'remates_totales': {f'over_{l}': pct(prob_over(shots_tot, l))
                                for l in (18.5, 20.5, 22.5, 24.5)},
            'remates_puerta': {f'over_{l}': pct(prob_over(sot_tot, l))
                               for l in (4.5, 5.5, 6.5, 7.5)},
        }
        return {'match': pred['match'], 'fase': fase, 'arbitro': pred['referee']['nombre'],
                'medias': {'goles': round(lam_h + lam_a, 2),
                           'corners': round(ck_h + ck_a, 1),
                           'tarjetas': round(cards_h + cards_a, 2),
                           'remates': round(shots_tot, 1), 'remates_puerta': round(sot_tot, 1)},
                'mercados': mercados}

    # ------------------------------------------------------------------ #
    # PLANTILLA GENERAL DE ANÁLISIS ESTADÍSTICO (9 secciones)              #
    # ------------------------------------------------------------------ #
    @staticmethod
    def _prob_poisson_mayor(l1: float, l2: float, max_n: int = 15) -> Tuple[float, float, float]:
        """P(X>Y), P(X=Y), P(X<Y) para dos Poisson independientes."""
        from math import exp, factorial
        p1 = np.array([exp(-l1) * l1 ** k / factorial(k) for k in range(max_n)])
        p2 = np.array([exp(-l2) * l2 ** k / factorial(k) for k in range(max_n)])
        M = np.outer(p1, p2)
        i = np.arange(max_n)
        return (float(M[i[:, None] > i[None, :]].sum()),
                float(M[i[:, None] == i[None, :]].sum()),
                float(M[i[:, None] < i[None, :]].sum()))

    @staticmethod
    def _prob_par(lam: float) -> float:
        """P(Poisson(λ) sea PAR) = (1 + e^(-2λ)) / 2."""
        return float(0.5 * (1 + np.exp(-2 * lam)))

    def plantilla(self, home: str, away: str, arbitro: Optional[str] = None,
                  fase: str = 'grupos', estadio: Optional[str] = None) -> Dict:
        """
        Rellena la Plantilla General de Análisis Estadístico de Rendimiento:
        1X2, doble oportunidad, hándicaps, over/under, BTTS, goleadores,
        multigoleadores, estadísticas de juego (con modelo arbitral de
        tarjetas y penaltis) y córners (con ajuste de altitud). Todos los
        valores derivan del ensemble calibrado + Monte Carlo + StatsBomb.
        """
        pred = self.predecir(home, away, arbitro=arbitro, fase=fase, estadio=estadio)
        if 'error' in pred:
            return pred

        n_l, n_v = NOMBRES_PAIS.get(home, home), NOMBRES_PAIS.get(away, away)
        s_l, s_v = self.stats_equipo(home), self.stats_equipo(away)
        M = np.array(pred['score_matrix'])
        idx = np.arange(M.shape[0])
        diff = idx[:, None] - idx[None, :]
        total = idx[:, None] + idx[None, :]
        lam_h = pred['prediction']['expected_goals']['home']
        lam_a = pred['prediction']['expected_goals']['away']

        pct = lambda x: round(float(x) * 100, 1)
        p1, px, p2 = M[diff > 0].sum(), M[diff == 0].sum(), M[diff < 0].sum()

        def campo(id_, etiqueta, valor, tipo='pct'):
            return {'id': id_, 'etiqueta': etiqueta, 'valor': valor, 'tipo': tipo}

        secciones = []

        # --- 1. 1X2 ------------------------------------------------------ #
        secciones.append({'titulo': '1. Probabilidad de Resultado (1X2)', 'campos': [
            campo('home_win_prob', f'Victoria {n_l}', pct(p1)),
            campo('draw_prob', 'Empate', pct(px)),
            campo('away_win_prob', f'Victoria {n_v}', pct(p2)),
        ]})

        # --- 2. Doble oportunidad ---------------------------------------- #
        secciones.append({'titulo': '2. Doble Oportunidad', 'campos': [
            campo('home_or_draw_prob', f'{n_l} o Empate', pct(p1 + px)),
            campo('home_or_away_prob', f'{n_l} o {n_v}', pct(p1 + p2)),
            campo('draw_or_away_prob', f'Empate o {n_v}', pct(px + p2)),
        ]})

        # --- 3. Hándicap asiático ----------------------------------------- #
        campos_h = [
            campo('home_plus05_prob', f'{n_l} +0.5 (no pierde)', pct(p1 + px)),
            campo('away_minus05_prob', f'{n_v} -0.5 (gana)', pct(p2)),
            campo('home_minus05_prob', f'{n_l} -0.5 (gana)', pct(p1)),
            campo('away_plus05_prob', f'{n_v} +0.5 (no pierde)', pct(p2 + px)),
        ]
        for k, linea in [(2, '15'), (3, '25'), (4, '35')]:
            p_cubre = M[diff >= k].sum()
            campos_h.append(campo(f'home_minus{linea}_prob',
                                  f'{n_l} -{k - 0.5} (gana por {k}+)', pct(p_cubre)))
            campos_h.append(campo(f'away_plus{linea}_prob',
                                  f'{n_v} +{k - 0.5}', pct(1 - p_cubre)))
        secciones.append({'titulo': '3. Margen de Goles (Hándicap Asiático)', 'campos': campos_h})

        # --- 4. Total de goles --------------------------------------------- #
        over25 = M[total >= 3].sum()
        secciones.append({'titulo': '4. Total de Goles', 'campos': [
            campo('over25_prob', 'Más de 2.5 goles', pct(over25)),
            campo('under25_prob', 'Menos de 2.5 goles', pct(1 - over25)),
        ]})

        # --- 5. BTTS -------------------------------------------------------- #
        btts = M[(idx[:, None] >= 1) & (idx[None, :] >= 1)].sum()
        secciones.append({'titulo': '5. Ambos Equipos Marcan (BTTS)', 'campos': [
            campo('btts_yes_prob', 'Sí (ambos marcan)', pct(btts)),
            campo('btts_no_prob', 'No', pct(1 - btts)),
        ]})

        # Volumen de remates por equipo (calibración StatsBomb): se calcula
        # aquí para que goleadores, rematadores y la Sección 8 compartan la
        # MISMA fuente y los top-4 por jugador sumen dentro del total.
        spx = float(self.calibracion.get('shots_on_por_xg', 3.1))
        tpo = float(self.calibracion.get('shots_total_por_on', 2.6))
        sot_h, sot_a = lam_h * spx, lam_a * spx
        shots_h, shots_a = sot_h * tpo, sot_a * tpo

        # --- 6, 7 y 7b. Goleadores, multigoleadores y rematadores ----------- #
        p_algun_gol = 1 - float(M[0, 0])
        campos_gol, campos_multi, campos_remates = [], [], []
        for equipo, nombre_eq, lam_eq, prefijo in [(home, n_l, lam_h, 'h'), (away, n_v, lam_a, 'a')]:
            jugadores = self._jugadores_clave(equipo, top_n=5)
            xgf = max(self.stats_equipo(equipo)['XGF_MA5'], 0.5)
            factor = float(np.clip(lam_eq / xgf, 0.6, 1.8))
            p_equipo_primero = (lam_eq / max(lam_h + lam_a, 1e-6)) * p_algun_gol

            # Top 4 rematadores: cuota del volumen del equipo proporcional a su
            # xG individual, con tope del 85 % del total del equipo (el resto
            # queda para el resto de la alineación) y límites físicos por
            # jugador (≤5.5 remates, ≤3.0 a puerta).
            shots_eq = shots_h if prefijo == 'h' else shots_a
            sot_eq = sot_h if prefijo == 'h' else sot_a
            top4 = jugadores[:4]
            cuotas = [j['goles_esperados'] / xgf for j in top4]
            suma_cuotas = sum(cuotas)
            if suma_cuotas > 0.85:
                cuotas = [c * 0.85 / suma_cuotas for c in cuotas]
            for i, (j, cuota_j) in enumerate(zip(top4, cuotas), start=1):
                rem_i = float(min(5.5, shots_eq * cuota_j))
                sot_i = float(min(3.0, sot_eq * cuota_j, rem_i))
                base = f'shooter_{prefijo}{i}'
                campos_remates.extend([
                    campo(f'{base}_shots', f'{j["nombre"]} ({nombre_eq}) — Remates esperados',
                          round(rem_i, 2), 'media'),
                    campo(f'{base}_shots_prob', f'{j["nombre"]} ({nombre_eq}) — Prob. de rematar (≥1)',
                          pct(1 - np.exp(-rem_i))),
                    campo(f'{base}_sot', f'{j["nombre"]} ({nombre_eq}) — Remates a puerta esperados',
                          round(sot_i, 2), 'media'),
                    campo(f'{base}_sot_prob', f'{j["nombre"]} ({nombre_eq}) — Prob. de rematar a puerta (≥1)',
                          pct(1 - np.exp(-sot_i))),
                ])

            for i, j in enumerate(jugadores, start=1):
                lam_i = max(0.01, j['goles_esperados'] * factor)
                cuota = lam_i / max(lam_eq, 1e-6)
                anytime = 1 - np.exp(-lam_i)
                primero = cuota * p_equipo_primero
                dos_mas = 1 - np.exp(-lam_i) * (1 + lam_i)
                tres_mas = 1 - np.exp(-lam_i) * (1 + lam_i + lam_i ** 2 / 2)
                base = f'player_{prefijo}{i}'
                campos_gol.extend([
                    campo(f'{base}_first', f'{j["nombre"]} ({nombre_eq}) — Primer gol', pct(primero)),
                    campo(f'{base}_last', f'{j["nombre"]} ({nombre_eq}) — Último gol', pct(primero)),
                    campo(f'{base}_anytime', f'{j["nombre"]} ({nombre_eq}) — Cualquier gol', pct(anytime)),
                ])
                if i <= 2:
                    campos_multi.extend([
                        campo(f'{base}_2plus', f'{j["nombre"]} ({nombre_eq}) — 2 goles o más', pct(dos_mas)),
                        campo(f'{base}_3plus', f'{j["nombre"]} ({nombre_eq}) — 3 goles o más', pct(tres_mas)),
                    ])
        secciones.append({'titulo': '6. Goleadores (cualquier momento)', 'campos': campos_gol})
        secciones.append({'titulo': '7. Multigoleadores', 'campos': campos_multi})
        secciones.append({'titulo': '7b. Remates por Jugador (Top 4 de cada equipo)',
                          'campos': campos_remates})

        # --- 8. Estadísticas de juego ---------------------------------------- #
        # (spx/tpo/sot/shots calculados arriba, compartidos con la sección 7b)
        # Tarjetas: modelo arbitral (perfil del árbitro × histórico de los equipos)
        tarjetas = pred['cards']
        penaltis = pred['penalties']
        cards_h = tarjetas['amarillas_local'] + tarjetas['rojas_local']
        cards_a = tarjetas['amarillas_visitante'] + tarjetas['rojas_visitante']
        pc1, pcx, pc2 = self._prob_poisson_mayor(cards_h, cards_a)
        total_cards = tarjetas['total_tarjetas']
        from math import factorial
        over45_cards = 1 - float(np.sum([np.exp(-total_cards) * total_cards ** k / factorial(k)
                                         for k in range(5)]))
        secciones.append({'titulo': '8. Estadísticas de Juego y Arbitraje', 'campos': [
            campo('total_shots', 'Remates totales del partido (media)', round(shots_h + shots_a, 1), 'media'),
            campo('total_shots_subs', 'Remates incluyendo suplentes (media)', round((shots_h + shots_a) * 1.08, 1), 'media'),
            campo('shots_on_target', 'Remates a puerta (media)', round(sot_h + sot_a, 1), 'media'),
            campo('shots_on_target_subs', 'Remates a puerta incl. suplentes (media)', round((sot_h + sot_a) * 1.08, 1), 'media'),
            campo('assists', 'Asistencias esperadas', round(0.75 * (lam_h + lam_a), 1), 'media'),
            campo('assists_subs', 'Asistencias incl. suplentes', round(0.80 * (lam_h + lam_a), 1), 'media'),
            campo('tackles', 'Entradas (alineación inicial, media)', round(24 + 4 * (cards_h + cards_a), 1), 'media'),
            campo('total_cards', 'Tarjetas totales (media)', round(total_cards, 1), 'media'),
            campo('total_cards_subs', 'Tarjetas incl. suplentes (media)', round(total_cards * 1.1, 1), 'media'),
            campo('home_goals', f'Goles {n_l} (media)', round(lam_h, 2), 'media'),
            campo('away_goals', f'Goles {n_v} (media)', round(lam_a, 2), 'media'),
            campo('cards_1x2_prob', f'Más tarjetas: {n_l} {pct(pc1)}% · Empate {pct(pcx)}% · {n_v} {pct(pc2)}%',
                  f'{n_l if pc1 >= pc2 else n_v}', 'texto'),
            campo('cards_over45_prob', 'Más de 4.5 tarjetas', pct(over45_cards)),
            campo('home_cards', f'Tarjetas {n_l} (media, ajustada al árbitro)', round(cards_h, 2), 'media'),
            campo('away_cards', f'Tarjetas {n_v} (media, ajustada al árbitro)', round(cards_a, 2), 'media'),
            campo('red_cards_expected', 'Rojas esperadas en el partido',
                  round(tarjetas['rojas_local'] + tarjetas['rojas_visitante'], 2), 'media'),
            campo('penalty_prob', 'Prob. de al menos un penalti',
                  pct(penaltis['prob_penal_en_partido'])),
            campo('penalty_home_prob', f'Prob. de penalti a favor de {n_l}',
                  pct(penaltis['prob_penal_favor_local'])),
            campo('penalty_away_prob', f'Prob. de penalti a favor de {n_v}',
                  pct(penaltis['prob_penal_favor_visitante'])),
        ]})

        # --- 9. Córners (con ajuste de altitud: +0.2 en altura) ----------------- #
        altura_sede = float(pred.get('altitude', {}).get('altitud_sede', 0))
        extra_altura = 0.1 if altura_sede > 1500 else 0.0
        ck_h = 2.0 + 0.25 * shots_h + extra_altura
        ck_a = 2.0 + 0.25 * shots_a + extra_altura
        ck_total = ck_h + ck_a
        pk1, pkx, pk2 = self._prob_poisson_mayor(ck_h, ck_a)
        pk1_1h, pkx_1h, pk2_1h = self._prob_poisson_mayor(ck_h * 0.44, ck_a * 0.44)
        cuota_primero = ck_h / max(ck_total, 1e-6)
        secciones.append({'titulo': '9. Análisis de Córners', 'campos': [
            campo('total_corners', 'Total córners del partido (media)', round(ck_total, 1), 'media'),
            campo('corners_handicap', f'Hándicap córners ({n_l} vs {n_v})',
                  f"{n_l} {'-' if ck_h >= ck_a else '+'}{abs(round(ck_h - ck_a, 1))}", 'texto'),
            campo('corners_1x2_prob', f'Más córners: {n_l} {pct(pk1)}% · Empate {pct(pkx)}% · {n_v} {pct(pk2)}%',
                  f'{n_l if pk1 >= pk2 else n_v}', 'texto'),
            campo('home_corners', f'Córners {n_l} (media)', round(ck_h, 1), 'media'),
            campo('away_corners', f'Córners {n_v} (media)', round(ck_a, 1), 'media'),
            campo('corners_par_prob', 'Total córners PAR', pct(self._prob_par(ck_total))),
            campo('first_corner_home_prob', f'Primer córner de {n_l}', pct(cuota_primero)),
            campo('last_corner_home_prob', f'Último córner de {n_l}', pct(cuota_primero)),
            campo('corners_1h', 'Córners en 1ª mitad (media)', round(ck_total * 0.44, 1), 'media'),
            campo('corners_1x2_1h_prob',
                  f'Más córners 1ª mitad: {n_l} {pct(pk1_1h)}% · Empate {pct(pkx_1h)}% · {n_v} {pct(pk2_1h)}%',
                  f'{n_l if pk1_1h >= pk2_1h else n_v}', 'texto'),
            campo('last_corner_1h_home_prob', f'Último córner 1ª mitad de {n_l}', pct(cuota_primero)),
            campo('home_corners_1h', f'Córners {n_l} 1ª mitad (media)', round(ck_h * 0.44, 1), 'media'),
            campo('away_corners_1h', f'Córners {n_v} 1ª mitad (media)', round(ck_a * 0.44, 1), 'media'),
            campo('corners_1h_par_prob', 'Córners 1ª mitad PAR', pct(self._prob_par(ck_total * 0.44))),
        ]})

        # --- 9b. Líneas Over/Under con probabilidad exacta (Mejora 2, v12) ------ #
        secciones.append({'titulo': '9b. Líneas Over/Under (probabilidad exacta)', 'campos': [
            campo('over15_goles', 'Más de 1.5 goles', pct(M[total > 1.5].sum())),
            campo('over35_goles', 'Más de 3.5 goles', pct(M[total > 3.5].sum())),
            campo('over65_corners', 'Más de 6.5 córners', pct(prob_over(ck_total, 6.5))),
            campo('over75_corners', 'Más de 7.5 córners', pct(prob_over(ck_total, 7.5))),
            campo('over85_corners', 'Más de 8.5 córners', pct(prob_over(ck_total, 8.5))),
            campo('over95_corners', 'Más de 9.5 córners', pct(prob_over(ck_total, 9.5))),
            campo('over35_tarjetas', 'Más de 3.5 tarjetas', pct(prob_over(total_cards, 3.5))),
            campo('over55_tarjetas', 'Más de 5.5 tarjetas', pct(prob_over(total_cards, 5.5))),
            campo('over205_remates', 'Más de 20.5 remates totales', pct(prob_over(shots_h + shots_a, 20.5))),
            campo('over225_remates', 'Más de 22.5 remates totales', pct(prob_over(shots_h + shots_a, 22.5))),
            campo('over55_puerta', 'Más de 5.5 remates a puerta', pct(prob_over(sot_h + sot_a, 5.5))),
            campo('over65_puerta', 'Más de 6.5 remates a puerta', pct(prob_over(sot_h + sot_a, 6.5))),
        ]})

        # ---- Observaciones automáticas (árbitro, carácter, altitud, fatiga) ----
        arb = pred['referee']
        car = pred['character']
        observaciones = [arbitros.descripcion_arbitro(arb['nombre'], arb)]
        for lado, nombre_eq in [('home', n_l), ('away', n_v)]:
            observaciones.append(
                f"{nombre_eq} tras recibir gol: {car[lado]['reaccion_tras_gol']}. "
                f"En segundas mitades: {car[lado]['rendimiento_2da_mitad']}. "
                f"Encaja {car[lado]['goles_encajados_ult15']:.1f} goles por partido "
                f"en los últimos 15 minutos.")
        # Altitud y aclimatación (v10): efecto y nivel de cada equipo
        det_alt = pred.get('altitude', {})
        observaciones.append(altitud.descripcion_efecto(home, away, pred.get('stadium'), det_alt))
        if det_alt.get('altitud_sede', 0) > 1000:
            observaciones.append(f"{n_l} está {altitud.nivel_aclimatacion(home)}.")
            observaciones.append(f"{n_v} está {altitud.nivel_aclimatacion(away)}.")
        clave = pred['key_players']['home']
        if clave:
            minutos_30d = car['home']['partidos_30d'] * 90
            observaciones.append(
                f"Jugador clave: {clave[0]['nombre']} ({n_l}) con ~{minutos_30d} minutos "
                f"del equipo en 30 días (fatiga {'alta' if minutos_30d > 450 else 'controlada'}).")
        # (sin duplicar la línea del árbitro que predecir pudo añadir a insights)
        observaciones += [i for i in pred['insights'] if not i.startswith('Árbitro ')]
        observaciones.append(f"🔥 Factor decisivo: {pred['decisive_factor']}")

        if fase == 'eliminatoria':
            observaciones.append(
                "Partido de eliminación directa: +15 % de tarjetas por tensión y "
                "reacciones tras gol acentuadas (ajuste de vida o muerte aplicado).")

        return {
            'partido': f'{n_l} vs {n_v}',
            'codigos': {'home': home, 'away': away},
            'fecha': pd.Timestamp.today().strftime('%Y-%m-%d'),
            'estadio': pred.get('stadium'),
            'altitud_sede': altura_sede,
            'fase': fase,
            'arbitro': {'nombre': arb['nombre'], 'criterio': arb['criterio'],
                        'ama_p90': arb['ama_p90'], 'roj_p90': arb['roj_p90'],
                        'pen_p90': arb['pen_p90'], 'confederacion': arb['confederacion']},
            'estado_al': self.fecha_estado,
            'secciones': secciones,
            'observaciones': observaciones,
            'prediccion_base': pred,
        }


def plantilla_a_markdown(p: Dict, valores_usuario: Optional[Dict] = None) -> str:
    """Exporta la plantilla (con valores del modelo o del usuario) a Markdown."""
    valores_usuario = valores_usuario or {}
    arb = p.get('arbitro')
    linea_arbitro = (f"**Árbitro:** {arb['nombre']} ({arb['criterio']}, "
                     f"{arb['ama_p90']:.1f} am/90, {arb['roj_p90']:.2f} roj/90, "
                     f"{arb['pen_p90']:.2f} pen/90)") if arb else ''
    linea_estadio = ''
    if p.get('estadio'):
        info_est = altitud.ESTADIOS_MUNDIAL.get(p['estadio'], {})
        nombre_est = info_est.get('nombre', p['estadio'])
        linea_estadio = f" · **Estadio:** {nombre_est} ({p.get('altitud_sede', 0):.0f} msnm)"
    lineas = [
        '# PLANTILLA GENERAL DE ANÁLISIS ESTADÍSTICO DE RENDIMIENTO',
        f"**Partido:** {p['partido']}",
        f"**Fecha:** {p['fecha']}" + linea_estadio,
        linea_arbitro,
        f"**Analista:** Usuario · **Datos al:** {p['estado_al']}",
        '',
    ]
    lineas = [l for i, l in enumerate(lineas) if l or i == len(lineas) - 1]
    for seccion in p['secciones']:
        lineas.append(f"## {seccion['titulo']}")
        lineas.append('| Concepto | Valor |')
        lineas.append('| :--- | :--- |')
        for c in seccion['campos']:
            valor = valores_usuario.get(c['id'], c['valor'])
            sufijo = ' %' if c['tipo'] == 'pct' else ''
            lineas.append(f"| {c['etiqueta']} | `[ {valor}{sufijo} ]` |")
        lineas.append('')
    lineas.append('**Observaciones adicionales:**')
    for obs in p['observaciones']:
        lineas.append(f"- {obs}")
    return '\n'.join(lineas)


# ===========================================================================
# Servicio HTTP opcional (FastAPI)
# ===========================================================================
try:
    from fastapi import FastAPI, HTTPException

    api = FastAPI(title="Motor Predictivo TDA – Mundial 2026", version="3.0")
    _engine: Optional[PredictionEngine] = None

    def _get_engine() -> PredictionEngine:
        global _engine
        if _engine is None:
            _engine = PredictionEngine()
        return _engine

    @api.get("/health")
    def health():
        eng = _get_engine()
        return {'status': 'ok' if eng.listo else 'error', 'detail': eng.error,
                'data_source': eng.fuente if eng.listo else None,
                'model': eng.metadata if eng.listo else None}

    @api.get("/predict")
    def predict(home: str, away: str, arbitro: str = None,
                fase: str = 'grupos', estadio: str = None):
        resultado = _get_engine().predecir(home.upper(), away.upper(),
                                           arbitro=arbitro, fase=fase, estadio=estadio)
        if 'error' in resultado:
            raise HTTPException(status_code=400, detail=resultado['error'])
        return resultado

    @api.get("/estadios")
    def lista_estadios():
        return {'estadios': [{'clave': k, **v} for k, v in altitud.ESTADIOS_MUNDIAL.items()]}

    @api.get("/distribuciones")
    def distribuciones(home: str, away: str, arbitro: str = None,
                       fase: str = 'grupos', estadio: str = None):
        resultado = _get_engine().distribuciones(home.upper(), away.upper(),
                                                 arbitro=arbitro, fase=fase, estadio=estadio)
        if 'error' in resultado:
            raise HTTPException(status_code=400, detail=resultado['error'])
        return resultado

    @api.get("/arbitros")
    def lista_arbitros():
        return {'arbitros': [{'nombre': n, **d} for n, d in arbitros.ARBITROS.items()],
                'promedio': arbitros.ARBITRO_PROMEDIO}

    @api.get("/query")
    def query(q: str, home: str = None, away: str = None):
        defecto = (home.upper(), away.upper()) if home and away else None
        return _get_engine().responder_consulta(q, defecto)

    @api.get("/plantilla")
    def plantilla(home: str, away: str, formato: str = 'json',
                  arbitro: str = None, fase: str = 'grupos', estadio: str = None):
        resultado = _get_engine().plantilla(home.upper(), away.upper(),
                                            arbitro=arbitro, fase=fase, estadio=estadio)
        if 'error' in resultado:
            raise HTTPException(status_code=400, detail=resultado['error'])
        if formato == 'markdown':
            return {'markdown': plantilla_a_markdown(resultado)}
        return resultado

except ImportError:
    api = None


if __name__ == '__main__':
    import uvicorn
    if api is None:
        raise SystemExit("Instala fastapi y uvicorn para levantar el servicio HTTP.")
    uvicorn.run(api, host='0.0.0.0', port=8000)
