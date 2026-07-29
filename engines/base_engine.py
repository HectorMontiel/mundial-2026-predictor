#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BaseSportsEngine (v29 §2.1) — lógica universal multi-deporte (principio DRY).

El fútbol NO se refactoriza (ClubEngine/PredictionEngine quedan intactos:
regla de no regresión). Los deportes nuevos (MLB confirmado en v29; NBA/tenis
diferidos por falta de fuente gratuita viable — ver VALIDACION_v29.md)
heredan de esta clase la mecánica común: carga de artefactos, EV, Kelly
simultáneo, plantilla y barrido de Apuestas del Día. Cada deporte solo
implementa `cargar_datos_historicos()` y `construir_features()`.
"""

import json
import os
from abc import ABC, abstractmethod
from typing import Dict, List, Optional

import numpy as np


class BaseSportsEngine(ABC):
    def __init__(self, deporte: str, carpeta: str):
        self.deporte = deporte
        self.carpeta = carpeta
        self.modelo_ml = None
        self.modelo_totales = None
        self.scaler = None
        self.metadata: Dict = {}
        self.listo = False
        self.error = None

    # ----- concreto (común a todos los deportes) -------------------------
    def cargar_modelo(self):
        import joblib
        try:
            self.modelo_ml = joblib.load(os.path.join(self.carpeta, 'moneyline.joblib'))
            self.scaler = joblib.load(os.path.join(self.carpeta, 'scaler.joblib'))
            ruta_tot = os.path.join(self.carpeta, 'totales.joblib')
            if os.path.exists(ruta_tot):
                self.modelo_totales = joblib.load(ruta_tot)
            with open(os.path.join(self.carpeta, 'metadata.json'), encoding='utf-8') as f:
                self.metadata = json.load(f)
            # v79 — ver `inferencia_rapida`: el paralelismo de joblib que se
            # guardó al entrenar es puro coste cuando se predice de uno en uno.
            try:
                import inferencia_rapida
                inferencia_rapida.preparar(self.modelo_ml, self.modelo_totales)
            except Exception as e:
                import logging
                logging.getLogger(__name__).debug(
                    f"[{self.deporte}] inferencia_rapida no aplicada: {e}")
            self.listo = True
        except Exception as e:
            self.error = f"{type(e).__name__}: {e}"
        return self

    @staticmethod
    def calcular_ev(prob: float, cuota: float) -> float:
        return round(cuota * prob - 1.0, 4)

    @staticmethod
    def aplicar_kelly(prob: float, cuota: float, bankroll: float,
                      fraccion: float = 0.25, cap: float = 0.05) -> Dict:
        """
        v81 — LA FRACCIÓN SUBE DE ⅛ A ¼, y por primera vez está medida.

        El ⅛ venía de la v27 como decisión de prudencia: bajaba la caída máxima
        de 24,3 % a 13,0 %. Nunca se optimizó la fracción en sí.

        Se propuso un Kelly DINÁMICO que subiera o bajara con la racha. Medido
        con Monte Carlo sobre la secuencia real de 589 picks del ledger,
        remuestreada **por bloques de 20** para conservar las rachas (con un
        bootstrap i.i.d. no habría rachas que detectar y el experimento estaría
        amañado):

            política                 cap. mediano    p5     caída    ruina
            ⅟₁₆ Kelly                   1,351      1,105    7,5 %    0,00 %
            ⅛ Kelly (lo que había)      1,760      1,178   14,6 %    0,00 %
            ¼ Kelly                     2,592      1,193   27,5 %    0,00 %
            ½ Kelly                     3,117      0,878   44,3 %    0,53 %
            1 Kelly                     2,950      0,300   57,0 %    5,03 %
            DINÁMICA (racha, ⅟₁₆-¼)     2,352      1,174   23,6 %    0,00 %
            DINÁMICA inversa            1,515      1,083   14,2 %    0,00 %

        **La dinámica no aporta nada**: 2,352 frente a 2,592 del ¼ liso, con el
        mismo p5 y la misma ruina. Acaba siendo una forma ruidosa de promediar
        entre ⅟₁₆ y ¼, y el ¼ constante la domina. La racha reciente no predice
        la siguiente apuesta — que es justo lo que uno esperaría si los picks
        son aproximadamente independientes, y es tranquilizador que salga así.

        Lo que sí mejora es subir la fracción fija: **+47 % de capital mediano
        y un p5 MEJOR** (1,193 frente a 1,178), con ruina 0,00 % en las dos.

        La contrapartida es real y hay que decirla: la caída máxima típica pasa
        de 14,6 % a 27,5 %. Se para aquí y no en ½ porque ahí el p5 cae por
        debajo de 1,0 (0,878: en el peor 5 % de escenarios se pierde dinero) y
        aparece ruina. El cap del 5 % por pick y el 20 % por jornada siguen
        puestos.
        """
        b = max(cuota - 1.0, 1e-6)
        kelly = (b * prob - (1 - prob)) / b
        frac = float(np.clip(kelly * fraccion, 0.0, cap))
        return {'stake_pct': round(frac, 4), 'stake': round(frac * bankroll, 2)}

    def predecir(self, home: str, away: str, **ctx) -> Dict:
        if not self.listo:
            return {'error': f'{self.deporte}: modelo no cargado ({self.error}).'}
        try:
            x = self.construir_features(home, away, **ctx)
        except Exception as e:
            return {'error': f'{self.deporte}: {type(e).__name__}: {e}'}
        if x is None:
            return {'error': f'{self.deporte}: equipos desconocidos.'}
        xn = self.scaler.transform([x])
        proba = self.modelo_ml.predict_proba(xn)[0]
        # binario (sin empate): clase 1 = gana local
        idx_home = list(self.modelo_ml.classes_).index(1)
        p_home = float(proba[idx_home])
        total = None
        if self.modelo_totales is not None:
            total = float(self.modelo_totales.predict(xn)[0])
        return {'deporte': self.deporte, 'match': f'{home} vs {away}',
                'prob_home': round(p_home, 4), 'prob_away': round(1 - p_home, 4),
                'winner': home if p_home >= 0.5 else away,
                'confidence': round(max(p_home, 1 - p_home), 4),
                'total_estimado': round(total, 2) if total is not None else None,
                'accuracy_backtest': self.metadata.get('precision_validacion'),
                'mercado_ref': self.metadata.get('precision_mercado')}

    def plantilla(self, home: str, away: str, **ctx) -> Dict:
        """Plantilla de análisis unificada (v32 §8.0: SOLO mercados derivables
        con rigor de los modelos actuales — moneyline del clasificador,
        totales del regresor Poisson, y spread/totales por equipo de la
        distribución NORMAL del margen calibrada con σ histórica.
        EXCLUIDOS: cuartos NBA y primeras 5 entradas MLB — exigen datos
        play-by-play que no se ingieren)."""
        from scipy.stats import norm, poisson
        pred = self.predecir(home, away, **ctx)
        if 'error' in pred:
            return pred
        linea = ctx.get('linea_total', self.metadata.get('linea_total_tipica'))
        p_home = pred['prob_home']
        campos = [
            {'id': 'ml_home', 'etiqueta': f'Gana {home}', 'valor': p_home * 100},
            {'id': 'ml_away', 'etiqueta': f'Gana {away}', 'valor': pred['prob_away'] * 100},
        ]
        total = pred.get('total_estimado')
        if total is not None and linea:
            lam = max(total, 0.1)
            for l in self._lineas_totales(linea):
                p_under = float(poisson.cdf(int(np.floor(l)), lam))
                campos += [
                    {'id': f'over_{l}', 'etiqueta': f'Más de {l}',
                     'valor': (1 - p_under) * 100},
                    {'id': f'under_{l}', 'etiqueta': f'Menos de {l}',
                     'valor': p_under * 100},
                ]
        # --- spread y totales por equipo desde el margen ~ N(μ, σ) ---
        sigma = self.metadata.get('sigma_margen')
        if total is not None and sigma:
            # μ se deduce de la probabilidad calibrada: P(margen>0)=p_home
            mu = float(sigma) * float(norm.ppf(min(max(p_home, 1e-4), 1 - 1e-4)))
            for s in self._lineas_spread():
                # local cubre −s  ⇔  margen > s
                p_cubre = float(1 - norm.cdf((s - mu) / sigma))
                campos += [
                    {'id': f'sp_home_{s}', 'etiqueta': f'{home} −{s}',
                     'valor': p_cubre * 100},
                    {'id': f'sp_away_{s}', 'etiqueta': f'{away} +{s}',
                     'valor': (1 - p_cubre) * 100},
                ]
            # total por equipo: puntos_local = (T + margen)/2
            media_local = (total + mu) / 2
            media_visit = (total - mu) / 2
            for lado, m, nombre in (('home', media_local, home),
                                    ('away', media_visit, away)):
                l_eq = round(m * 2) / 2          # línea .0/.5 cercana
                p_under_eq = float(poisson.cdf(int(np.floor(l_eq)), max(m, 0.1)))
                campos += [
                    {'id': f'tt_{lado}_over', 'etiqueta':
                     f'{nombre}: más de {l_eq}', 'valor': (1 - p_under_eq) * 100},
                    {'id': f'tt_{lado}_under', 'etiqueta':
                     f'{nombre}: menos de {l_eq}', 'valor': p_under_eq * 100},
                ]
            pred['margen_esperado'] = round(mu, 2)
        return {'deporte': self.deporte, 'partido': f'{home} vs {away}',
                'prediccion': pred, 'campos': campos,
                'excluidos': self.metadata.get('mercados_excluidos', [])}

    def _lineas_totales(self, base: float) -> List[float]:
        """Líneas de O/U alrededor de la típica del deporte."""
        paso = 5.0 if base > 100 else (1.0 if base > 5 else 0.5)
        return [round(base + k * paso, 1) for k in (-1, 0, 1)]

    def _lineas_spread(self) -> List[float]:
        base = self.metadata.get('linea_total_tipica', 8)
        return [1.5, 3.5, 5.5] if base > 100 else [0.5, 1.5, 2.5]

    def barrido_apuestas_dia(self, cuotas: Dict, sport_key: str,
                             min_prob: float = 0.60, min_ev: float = 0.03,
                             min_cuota: float = 1.50) -> List[Dict]:
        """Picks del deporte desde odds_actuales (mercado h2h)."""
        import pandas as pd
        picks = []
        hoy = pd.Timestamp.today().normalize()
        for mid, o in cuotas.items():
            if o.get('sport') != sport_key or not o.get('odd_home'):
                continue
            partes = mid.split('_')
            if len(partes) != 3:
                continue
            home, away = partes[1].replace('-', ' '), partes[2].replace('-', ' ')
            pred = self.predecir(home, away)
            if 'error' in pred:
                continue
            for lado, prob, cuota in (('home', pred['prob_home'], o.get('odd_home')),
                                      ('away', pred['prob_away'], o.get('odd_away'))):
                if not cuota:
                    continue
                ev = self.calcular_ev(prob, float(cuota))
                if prob > min_prob and ev > min_ev and float(cuota) > min_cuota:
                    picks.append({'deporte': self.deporte,
                                  'partido': f'{home} vs {away}',
                                  'apuesta': f"Gana {home if lado=='home' else away}",
                                  'prob': round(prob, 3), 'cuota': round(float(cuota), 2),
                                  'cuota_justa': round(1/max(prob, 1e-6), 2),
                                  'ev': ev})
        return sorted(picks, key=lambda p: -p['ev'])

    # ----- abstracto (específico de cada deporte) ------------------------
    @abstractmethod
    def cargar_datos_historicos(self):
        ...

    @abstractmethod
    def construir_features(self, home: str, away: str, **ctx) -> Optional[List[float]]:
        ...
