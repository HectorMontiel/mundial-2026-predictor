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
            self.listo = True
        except Exception as e:
            self.error = f"{type(e).__name__}: {e}"
        return self

    @staticmethod
    def calcular_ev(prob: float, cuota: float) -> float:
        return round(cuota * prob - 1.0, 4)

    @staticmethod
    def aplicar_kelly(prob: float, cuota: float, bankroll: float,
                      fraccion: float = 0.125, cap: float = 0.05) -> Dict:
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
        """Plantilla de análisis unificada (Moneyline + Totales + línea)."""
        pred = self.predecir(home, away, **ctx)
        if 'error' in pred:
            return pred
        linea = ctx.get('linea_total', self.metadata.get('linea_total_tipica'))
        campos = [
            {'id': 'ml_home', 'etiqueta': f'Gana {home}', 'valor': pred['prob_home'] * 100},
            {'id': 'ml_away', 'etiqueta': f'Gana {away}', 'valor': pred['prob_away'] * 100},
        ]
        if pred.get('total_estimado') is not None and linea:
            # Poisson sobre el total estimado para O/U de la línea de mercado.
            # scipy.poisson.cdf es estable para λ pequeño (MLB ~8) y grande
            # (NBA ~228, donde el manual con factorial se desbordaba).
            from scipy.stats import poisson
            lam = max(pred['total_estimado'], 0.1)
            p_under = float(poisson.cdf(int(np.floor(linea)), lam))
            campos += [
                {'id': 'over', 'etiqueta': f'Más de {linea}', 'valor': (1 - p_under) * 100},
                {'id': 'under', 'etiqueta': f'Menos de {linea}', 'valor': p_under * 100},
            ]
        return {'deporte': self.deporte, 'partido': f'{home} vs {away}',
                'prediccion': pred, 'campos': campos}

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
