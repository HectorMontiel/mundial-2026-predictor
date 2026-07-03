#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Generador sintético de RESPALDO con causalidad realista.

Se usa ÚNICAMENTE si el scraping real de FBref falla. A diferencia de un
generador de ruido independiente, preserva las correlaciones genuinas del
fútbol de élite:

    Fuerza latente (ELO + forma + plantilla)
        └─> xG esperado (modulado por estilo y contexto)
              └─> Goles ~ Poisson(media = xG)
              └─> Remates al arco correlacionados con xG
    Agresividad del rival + importancia del partido
        └─> Faltas, tarjetas amarillas y rojas
    Posición + fuerza colectiva
        └─> Métricas individuales de cada jugador

Con esta cadena causal, las features pre-partido (ELO, medias móviles)
contienen señal predictiva real y el modelo puede superar el 45-50 % de
precisión en validación temporal.
"""

import numpy as np
import pandas as pd
from numpy.random import default_rng
import datetime
import random
from typing import List, Dict, Tuple
from config import TEAMS, TEAM_STYLE, STADIUMS, POSITIONS

# ---------------------------------------------------------------------------
# Nivel real aproximado de cada selección (0 = débil, 1 = élite mundial).
# Basado en rankings FIFA/ELO 2024-2025. Es la semilla de la fuerza latente.
# ---------------------------------------------------------------------------
TEAM_TIER = {
    'ARG': 0.97, 'FRA': 0.96, 'ESP': 0.95, 'BRA': 0.90, 'ENG': 0.90,
    'POR': 0.88, 'NED': 0.86, 'GER': 0.85, 'BEL': 0.82, 'ITA': 0.80,
    'CRO': 0.78, 'URU': 0.78, 'COL': 0.77, 'MAR': 0.76, 'MEX': 0.72,
    'USA': 0.71, 'JPN': 0.71, 'SEN': 0.68, 'ECU': 0.67, 'KOR': 0.66,
    'SRB': 0.65, 'AUS': 0.60, 'CAN': 0.60, 'NGA': 0.58, 'EGY': 0.57,
    'ALG': 0.57, 'IRN': 0.56, 'TUN': 0.54, 'CMR': 0.54, 'GHA': 0.52,
    'PER': 0.52, 'CHI': 0.52, 'QAT': 0.48, 'KSA': 0.48, 'CRC': 0.46,
    'JAM': 0.42, 'PAN': 0.42, 'HON': 0.38,
    'PAR': 0.58, 'NOR': 0.70, 'SUI': 0.72, 'DEN': 0.72, 'AUT': 0.68,
    'SCO': 0.58, 'CIV': 0.60, 'UZB': 0.50, 'JOR': 0.45, 'NZL': 0.42,
    'CPV': 0.50,
}

# Selecciones nativas de altura (rinden mejor por encima de 1500 msnm)
EQUIPOS_DE_ALTURA = {'MEX', 'ECU', 'COL', 'PER'}

# ---------------------------------------------------------------------------
# Planteles con nombres reales (titulares 2025) para las selecciones del
# fixture principal. Orden idéntico a config.POSITIONS:
# [POR, DFC, DFC, DFC, LI, LD, MCD, MC, MC, ED, DC]
# ---------------------------------------------------------------------------
ROSTERS = {
    'MEX': ['Luis Malagón', 'César Montes', 'Johan Vásquez', 'Israel Reyes',
            'Jesús Gallardo', 'Jorge Sánchez', 'Edson Álvarez', 'Luis Chávez',
            'Orbelín Pineda', 'Hirving Lozano', 'Santiago Giménez'],
    'ECU': ['Hernán Galíndez', 'Piero Hincapié', 'Félix Torres', 'Willian Pacho',
            'Pervis Estupiñán', 'Angelo Preciado', 'Moisés Caicedo', 'Carlos Gruezo',
            'Kendry Páez', 'Gonzalo Plata', 'Enner Valencia'],
    'USA': ['Matt Turner', 'Chris Richards', 'Cameron Carter-Vickers', 'Tim Ream',
            'Antonee Robinson', 'Sergiño Dest', 'Tyler Adams', 'Weston McKennie',
            'Yunus Musah', 'Christian Pulisic', 'Folarin Balogun'],
    'COL': ['Camilo Vargas', 'Davinson Sánchez', 'Jhon Lucumí', 'Carlos Cuesta',
            'Johan Mojica', 'Daniel Muñoz', 'Jefferson Lerma', 'Richard Ríos',
            'James Rodríguez', 'Luis Díaz', 'Rafael Santos Borré'],
    'ARG': ['Emiliano Martínez', 'Cristian Romero', 'Nicolás Otamendi', 'Lisandro Martínez',
            'Nicolás Tagliafico', 'Nahuel Molina', 'Enzo Fernández', 'Rodrigo De Paul',
            'Alexis Mac Allister', 'Lionel Messi', 'Julián Álvarez'],
    'BRA': ['Alisson Becker', 'Marquinhos', 'Gabriel Magalhães', 'Éder Militão',
            'Guilherme Arana', 'Danilo', 'Bruno Guimarães', 'Lucas Paquetá',
            'Gerson', 'Vinícius Júnior', 'Endrick'],
    'ESP': ['Unai Simón', 'Robin Le Normand', 'Aymeric Laporte', 'Dean Huijsen',
            'Marc Cucurella', 'Dani Carvajal', 'Rodri', 'Pedri',
            'Fabián Ruiz', 'Lamine Yamal', 'Álvaro Morata'],
    'GER': ['Marc-André ter Stegen', 'Antonio Rüdiger', 'Jonathan Tah', 'Nico Schlotterbeck',
            'David Raum', 'Joshua Kimmich', 'Robert Andrich', 'Jamal Musiala',
            'Florian Wirtz', 'Leroy Sané', 'Kai Havertz'],
    'FRA': ['Mike Maignan', 'William Saliba', 'Ibrahima Konaté', 'Dayot Upamecano',
            'Theo Hernandez', 'Jules Koundé', 'Aurélien Tchouaméni', 'Adrien Rabiot',
            'Antoine Griezmann', 'Ousmane Dembélé', 'Kylian Mbappé'],
    'ENG': ['Jordan Pickford', 'John Stones', 'Marc Guéhi', 'Ezri Konsa',
            'Luke Shaw', 'Kyle Walker', 'Declan Rice', 'Jude Bellingham',
            'Phil Foden', 'Bukayo Saka', 'Harry Kane'],
    'JPN': ['Zion Suzuki', 'Takehiro Tomiyasu', 'Ko Itakura', 'Shogo Taniguchi',
            'Hiroki Ito', 'Yukinari Sugawara', 'Wataru Endo', 'Hidemasa Morita',
            'Daichi Kamada', 'Kaoru Mitoma', 'Ayase Ueda'],
    'KOR': ['Jo Hyeon-woo', 'Kim Min-jae', 'Kim Young-gwon', 'Jung Seung-hyun',
            'Kim Jin-su', 'Seol Young-woo', 'Hwang In-beom', 'Lee Jae-sung',
            'Lee Kang-in', 'Son Heung-min', 'Cho Gue-sung'],
    'MAR': ['Yassine Bounou', 'Nayef Aguerd', 'Romain Saïss', 'Achraf Dari',
            'Adam Masina', 'Achraf Hakimi', 'Sofyan Amrabat', 'Azzedine Ounahi',
            'Ismael Saibari', 'Brahim Díaz', 'Youssef En-Nesyri'],
    'SEN': ['Édouard Mendy', 'Kalidou Koulibaly', 'Abdou Diallo', 'Moussa Niakhaté',
            'Ismail Jakobs', 'Krépin Diatta', 'Idrissa Gueye', 'Pape Matar Sarr',
            'Lamine Camara', 'Ismaïla Sarr', 'Nicolas Jackson'],
    'CAN': ['Maxime Crépeau', 'Moïse Bombito', 'Derek Cornelius', 'Kamal Miller',
            'Alphonso Davies', 'Alistair Johnston', 'Stephen Eustáquio', 'Ismaël Koné',
            'Jonathan Osorio', 'Tajon Buchanan', 'Jonathan David'],
    'URU': ['Sergio Rochet', 'Ronald Araújo', 'José María Giménez', 'Sebastián Cáceres',
            'Matías Viña', 'Nahitan Nández', 'Manuel Ugarte', 'Federico Valverde',
            'Giorgian de Arrascaeta', 'Facundo Pellistri', 'Darwin Núñez'],
}

# Cuota esperada del xG del equipo por posición (suma ~1.0)
XG_SHARE_POSICION = {
    'POR': 0.00, 'DFC': 0.03, 'LI': 0.04, 'LD': 0.04,
    'MCD': 0.05, 'MC': 0.09, 'ED': 0.18, 'DC': 0.35,
}
REMATES_BASE_POSICION = {
    'POR': 0.0, 'DFC': 0.5, 'LI': 0.8, 'LD': 0.8,
    'MCD': 0.9, 'MC': 1.5, 'ED': 2.6, 'DC': 3.4,
}
PASES_CLAVE_POSICION = {
    'POR': 0.1, 'DFC': 0.3, 'LI': 0.9, 'LD': 0.9,
    'MCD': 0.8, 'MC': 1.6, 'ED': 1.8, 'DC': 0.9,
}


def nombre_jugador(equipo: str, posicion: str, indice: int) -> str:
    """Nombre real si el plantel está curado; genérico si no."""
    if equipo in ROSTERS:
        return ROSTERS[equipo][indice]
    return f"{posicion} Titular {indice + 1} ({equipo})"


class CorrelatedSyntheticGenerator:
    """
    Generador de respaldo con cadena causal realista.
    Mantiene la misma interfaz pública que el generador anterior:
    weighted_ma, compute_elo_update, elo, generate_initial_history,
    generate_new_matches.
    """

    def __init__(self, seed: int = 42):
        self.rng = default_rng(seed)
        # ELO inicial anclado al nivel real de cada selección
        self.elo = {
            t: 1300.0 + 550.0 * TEAM_TIER.get(t, 0.5) + float(self.rng.normal(0, 20))
            for t in TEAMS
        }
        # Calidad de plantilla (persistente) y agresividad táctica
        self.squad_quality = {t: TEAM_TIER.get(t, 0.5) + float(self.rng.normal(0, 0.03)) for t in TEAMS}
        self.aggression = {t: float(self.rng.uniform(0.8, 1.35)) for t in TEAMS}
        # Forma reciente: resultados de los últimos 5 partidos (1/0.5/0)
        self.form = {t: [] for t in TEAMS}

    # ------------------------------------------------------------------ #
    # Utilidades compartidas con el resto del pipeline                    #
    # ------------------------------------------------------------------ #
    def weighted_ma(self, values, weights=None):
        """Media móvil ponderada: peso doble al partido más reciente."""
        if not values:
            return 0.0
        n = len(values)
        w = weights if weights else (([1.0] * (n - 1) + [2.0]) if n > 1 else [1.0])
        w_norm = np.array(w[-n:]) / np.sum(w[-n:])
        return float(np.dot(values[-n:], w_norm))

    def compute_elo_update(self, r_h, r_a, g_h, g_a, k=32):
        e_h = 1 / (1 + 10 ** ((r_a - r_h) / 400))
        s_h = 1 if g_h > g_a else (0.5 if g_h == g_a else 0)
        return r_h + k * (s_h - e_h), r_a + k * ((1 - s_h) - (1 - e_h))

    # ------------------------------------------------------------------ #
    # Núcleo causal                                                        #
    # ------------------------------------------------------------------ #
    def _forma_reciente(self, team: str) -> float:
        """Puntos promedio de los últimos 5 resultados, en [0,1]."""
        f = self.form.get(team, [])
        if not f:
            return 0.5
        return float(np.mean(f[-5:]))

    def latent_strength(self, team: str) -> float:
        """
        Fuerza latente en [0,1]: 60 % ELO dinámico + 25 % forma reciente
        + 15 % calidad de plantilla, más un ruido pequeño de día de partido.
        """
        elo_norm = (self.elo.get(team, 1500.0) - 1300.0) / 600.0
        fuerza = (0.60 * elo_norm
                  + 0.25 * self._forma_reciente(team)
                  + 0.15 * self.squad_quality.get(team, 0.5))
        fuerza += float(self.rng.normal(0, 0.02))  # variación de día de partido
        return float(np.clip(fuerza, 0.02, 0.98))

    def _style_factor(self, atacante: str, defensor: str) -> float:
        """
        Interacción de estilos: un bloque alto presionando a un bloque bajo
        genera menos ocasiones limpias; bloque alto vs bloque alto abre espacios.
        """
        est_a = TEAM_STYLE.get(atacante, 'bloque_alto')
        est_d = TEAM_STYLE.get(defensor, 'bloque_alto')
        if est_a == 'bloque_alto' and est_d == 'bloque_bajo':
            return 0.90   # cuesta romper el bloque bajo
        if est_a == 'bloque_alto' and est_d == 'bloque_alto':
            return 1.12   # ida y vuelta, más espacios
        if est_a == 'bloque_bajo' and est_d == 'bloque_alto':
            return 1.05   # contragolpes ante línea adelantada
        return 0.95       # dos bloques bajos: partido cerrado

    def _xg_esperado(self, atacante: str, defensor: str,
                     es_local: bool, altitud: int) -> float:
        """xG causal: fuerza relativa x estilo x localía x altitud."""
        s_atk = self.latent_strength(atacante)
        s_def = self.latent_strength(defensor)
        base = 1.30 * np.exp(1.55 * (s_atk - s_def))
        base *= self._style_factor(atacante, defensor)
        if es_local:
            base *= 1.18  # ventaja de localía real promedio
        # Efecto altitud: castiga al equipo no nativo por encima de 1500 msnm
        if altitud >= 1500:
            if atacante in EQUIPOS_DE_ALTURA:
                base *= 1.10
            else:
                base *= 0.88
        return float(np.clip(base, 0.15, 4.0))

    def _simular_partido(self, home: str, away: str, stadium: str,
                         fecha, tournament: str) -> Tuple[Dict, List[Dict]]:
        """Simula un partido completo respetando la cadena causal."""
        altitud = STADIUMS.get(stadium, 0)
        importancia = {'Amistoso': 0.6, 'Eliminatoria': 1.0,
                       'Copa Continental': 1.1, 'Fase de Grupos': 1.2,
                       'Eliminación Directa': 1.4}.get(tournament, 1.0)

        xg_h = self._xg_esperado(home, away, True, altitud)
        xg_a = self._xg_esperado(away, home, False, altitud)

        # Goles: Poisson cuya media es EXACTAMENTE el xG
        goles_h = int(self.rng.poisson(xg_h))
        goles_a = int(self.rng.poisson(xg_a))

        # Remates al arco correlacionados con el xG (~3.2 remates por xG + ruido)
        sot_h = max(goles_h, int(round(xg_h * 3.2 + self.rng.normal(0, 1.0))))
        sot_a = max(goles_a, int(round(xg_a * 3.2 + self.rng.normal(0, 1.0))))
        soff_h = int(max(0, self.rng.poisson(xg_h * 3.0 + 1.5)))
        soff_a = int(max(0, self.rng.poisson(xg_a * 3.0 + 1.5)))

        # Posesión ligada a la diferencia de fuerza
        dif = self.latent_strength(home) - self.latent_strength(away)
        pos_h = float(np.clip(50 + 38 * dif + self.rng.normal(0, 3), 25, 75))

        # Faltas y tarjetas: agresividad del RIVAL e importancia del partido
        faltas_h = int(self.rng.poisson(9 + 3 * self.aggression[home] * importancia))
        faltas_a = int(self.rng.poisson(9 + 3 * self.aggression[away] * importancia))
        amar_h = int(self.rng.poisson(0.6 + 0.9 * self.aggression[home] * importancia))
        amar_a = int(self.rng.poisson(0.6 + 0.9 * self.aggression[away] * importancia))
        roja_h = int(self.rng.binomial(1, min(0.25, 0.02 + 0.02 * amar_h + 0.02 * importancia)))
        roja_a = int(self.rng.binomial(1, min(0.25, 0.02 + 0.02 * amar_a + 0.02 * importancia)))

        # Córners correlacionados con volumen ofensivo
        corners_h = int(self.rng.poisson(2.0 + 0.55 * (sot_h + soff_h) * 0.5))
        corners_a = int(self.rng.poisson(2.0 + 0.55 * (sot_a + soff_a) * 0.5))

        # Actualizar ELO y forma con el resultado
        self.elo[home], self.elo[away] = self.compute_elo_update(
            self.elo[home], self.elo[away], goles_h, goles_a
        )
        pts_h = 1.0 if goles_h > goles_a else (0.5 if goles_h == goles_a else 0.0)
        self.form.setdefault(home, []).append(pts_h)
        self.form.setdefault(away, []).append(1.0 - pts_h if pts_h != 0.5 else 0.5)

        fecha_ts = pd.to_datetime(fecha)
        match_id = f"{fecha_ts.strftime('%Y%m%d')}_{home}_{away}"
        partido = {
            'MATCH_ID': match_id, 'date': fecha_ts.date(),
            'home_team': home, 'away_team': away,
            'home_goals': goles_h, 'away_goals': goles_a,
            'home_xg': round(xg_h, 2), 'away_xg': round(xg_a, 2),
            'home_shots_on': sot_h, 'away_shots_on': sot_a,
            'home_shots_off': soff_h, 'away_shots_off': soff_a,
            'home_possession': round(pos_h, 1), 'away_possession': round(100 - pos_h, 1),
            'home_fouls': faltas_h, 'away_fouls': faltas_a,
            'home_yellow': amar_h, 'away_yellow': amar_a,
            'home_red': roja_h, 'away_red': roja_a,
            'home_corners': corners_h, 'away_corners': corners_a,
            'stadium': stadium, 'tournament': tournament,
        }

        jugadores = []
        for equipo, xg_eq, sot_eq, goles_eq in [(home, xg_h, sot_h, goles_h),
                                                (away, xg_a, sot_a, goles_a)]:
            fuerza_eq = self.latent_strength(equipo)
            # Reparto de goles entre posiciones ofensivas proporcional al xG share
            shares = np.array([XG_SHARE_POSICION[p] for p in POSITIONS], dtype=float)
            probs = shares / shares.sum() if shares.sum() > 0 else np.ones(len(POSITIONS)) / len(POSITIONS)
            goles_por_puesto = self.rng.multinomial(goles_eq, probs)
            for j, pos in enumerate(POSITIONS):
                share = XG_SHARE_POSICION[pos]
                xg_ind = max(0.0, xg_eq * share * float(self.rng.uniform(0.7, 1.3)))
                remates = max(0, int(round(
                    REMATES_BASE_POSICION[pos] * (0.6 + 0.8 * fuerza_eq)
                    + self.rng.normal(0, 0.7))))
                remates_arco = min(remates, int(round(remates * float(self.rng.uniform(0.3, 0.55)))))
                jugadores.append({
                    'MATCH_ID': match_id, 'match_date': fecha_ts.date(),
                    'JUGADOR_ID': f"{equipo}_{pos}_{j+1}",
                    'NOMBRE': nombre_jugador(equipo, pos, j),
                    'EQUIPO': equipo, 'POSICION': pos,
                    'MINUTOS': int(np.clip(self.rng.normal(84, 9), 45, 90)),
                    'GOLES': int(goles_por_puesto[j]),
                    'XG': round(xg_ind, 3),
                    'REMATES': remates,
                    'REMATES_ARCO': remates_arco,
                    'PASES_CLAVE': int(max(0, self.rng.poisson(
                        PASES_CLAVE_POSICION[pos] * (0.6 + 0.8 * fuerza_eq)))),
                    'AMARILLAS': int(self.rng.binomial(1, 0.08 + 0.05 * self.aggression[equipo])),
                    'ROJAS': int(self.rng.binomial(1, 0.015)),
                })
        return partido, jugadores

    # ------------------------------------------------------------------ #
    # Relleno calibrado de métricas avanzadas para RESULTADOS REALES       #
    # ------------------------------------------------------------------ #
    @staticmethod
    def _uniformes_por_partido(match_ids: pd.Series, sal: str) -> np.ndarray:
        """
        Uniformes [0,1) DETERMINISTAS por MATCH_ID (hash estable + sal por
        variable). Garantiza que las métricas estimadas de un partido no
        cambien cuando el dataset crece con partidos de otros equipos —
        antes se usaba un flujo RNG global de longitud n y cada actualización
        diaria re-sorteaba el ruido de TODO el histórico, provocando cambios
        de predicción espurios (auditoría EGY vs AUS, 2026-07-03).
        """
        claves = pd.Index(match_ids.astype(str) + '|' + sal)
        h = pd.util.hash_pandas_object(claves.to_series().reset_index(drop=True),
                                       index=False).to_numpy(dtype=np.uint64)
        return (h >> np.uint64(11)).astype(np.float64) / float(1 << 53)

    def generate_advanced_metrics(self, df: pd.DataFrame, calibracion: Dict) -> pd.DataFrame:
        """
        Completa (vectorizado) las columnas avanzadas que el histórico real de
        resultados no trae (xG, remates, posesión, tarjetas, córners) de forma
        COHERENTE con los goles reales y la diferencia de ELO, usando las
        relaciones calibradas con StatsBomb:

            xG ~ intercept + slope * goles_reales + ruido(residual_std)
            remates_al_arco ~ xG * shots_on_por_xg     (nunca < goles)
            remates_totales ~ al_arco * shots_total_por_on
            posesión ~ 50 + f(diferencia de ELO)
            tarjetas ~ Poisson(importancia del torneo)

        El ruido es DETERMINISTA por MATCH_ID (ver _uniformes_por_partido).
        Solo rellena valores faltantes: si una columna ya trae datos reales
        (p. ej. inyectados por API-Football), esos se respetan.
        """
        from scipy.stats import norm, poisson as poisson_dist

        df = df.copy()
        n = len(df)
        mids = df['MATCH_ID']

        def z(sal):  # normal estándar determinista por partido
            u = np.clip(self._uniformes_por_partido(mids, sal), 1e-9, 1 - 1e-9)
            return norm.ppf(u)

        def pois(sal, mu):  # Poisson determinista por partido
            u = np.clip(self._uniformes_por_partido(mids, sal), 1e-9, 1 - 1e-9)
            return poisson_dist.ppf(u, mu).astype(int)

        def bern(sal, p):  # Bernoulli determinista por partido
            return (self._uniformes_por_partido(mids, sal) < p).astype(int)

        goles_h = pd.to_numeric(df['home_goals'], errors='coerce').fillna(0).to_numpy(float)
        goles_a = pd.to_numeric(df['away_goals'], errors='coerce').fillna(0).to_numpy(float)
        elo_diff = pd.to_numeric(df.get('elo_diff', 0), errors='coerce').fillna(0).to_numpy(float)

        importancia = df.get('tournament', pd.Series([''] * n)).astype(str).str.lower()
        imp = np.where(importancia.str.contains('world cup'), 1.25,
              np.where(importancia.str.contains('friendly'), 0.65, 1.0))

        a, b = calibracion['xg_intercept'], calibracion['xg_slope_goles']
        sd = calibracion['xg_residual_std']
        spx = calibracion['shots_on_por_xg']
        tpo = calibracion['shots_total_por_on']

        # xG condicionado a los goles reales + ligera señal de superioridad ELO
        xg_h = np.clip(a + b * goles_h + 0.10 * np.tanh(elo_diff / 300.0) + z('xg_h') * sd, 0.05, 4.5)
        xg_a = np.clip(a + b * goles_a - 0.10 * np.tanh(elo_diff / 300.0) + z('xg_a') * sd, 0.05, 4.5)

        sot_h = np.maximum(goles_h, np.round(xg_h * spx + z('sot_h'))).clip(0, 15)
        sot_a = np.maximum(goles_a, np.round(xg_a * spx + z('sot_a'))).clip(0, 15)
        soff_h = np.round(sot_h * (tpo - 1) + z('soff_h') * 1.2).clip(0, 20)
        soff_a = np.round(sot_a * (tpo - 1) + z('soff_a') * 1.2).clip(0, 20)

        pos_h = np.clip(50 + 12 * np.tanh(elo_diff / 300.0) + z('pos') * 4, 25, 75)

        amar_h = pois('amar_h', 1.6 * imp)
        amar_a = pois('amar_a', 1.7 * imp)
        roja_h = bern('roja_h', np.clip(0.03 * imp + 0.015 * amar_h, 0, 0.3))
        roja_a = bern('roja_a', np.clip(0.03 * imp + 0.015 * amar_a, 0, 0.3))

        corners_h = pois('ck_h', np.clip(2.0 + 0.5 * (sot_h + soff_h) * 0.5, 0.5, 12))
        corners_a = pois('ck_a', np.clip(2.0 + 0.5 * (sot_a + soff_a) * 0.5, 0.5, 12))

        rellenos = {
            'home_xg': np.round(xg_h, 2), 'away_xg': np.round(xg_a, 2),
            'home_shots_on': sot_h.astype(int), 'away_shots_on': sot_a.astype(int),
            'home_shots_off': soff_h.astype(int), 'away_shots_off': soff_a.astype(int),
            'home_possession': np.round(pos_h, 1), 'away_possession': np.round(100 - pos_h, 1),
            'home_yellow': amar_h, 'away_yellow': amar_a,
            'home_red': roja_h, 'away_red': roja_a,
            'home_corners': corners_h, 'away_corners': corners_a,
        }
        for col, valores in rellenos.items():
            if col in df.columns:
                serie = pd.to_numeric(df[col], errors='coerce')
                df[col] = serie.fillna(pd.Series(valores, index=df.index))
            else:
                df[col] = valores
        return df

    # ------------------------------------------------------------------ #
    # Interfaz pública (idéntica a la del generador anterior)             #
    # ------------------------------------------------------------------ #
    def generate_initial_history(self, days_back: int = 1825) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """Historial de 5 años (por defecto) con partidos cada 3 días."""
        start = datetime.date.today() - datetime.timedelta(days=days_back)
        end = datetime.date.today()
        matches, players = [], []
        current = start
        rnd = random.Random(42)
        while current <= end:
            teams_day = rnd.sample(TEAMS, min(6, len(TEAMS)))
            for i in range(0, len(teams_day), 2):
                home, away = teams_day[i], teams_day[i + 1]
                stadium = rnd.choice(list(STADIUMS.keys()))
                tournament = rnd.choice(['Amistoso', 'Eliminatoria', 'Copa Continental'])
                partido, jugadores = self._simular_partido(home, away, stadium, current, tournament)
                matches.append(partido)
                players.extend(jugadores)
            current += datetime.timedelta(days=3)
        return pd.DataFrame(matches), pd.DataFrame(players)

    def generate_new_matches(self, fixture_df: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """Simula partidos de un fixture pendiente usando los ELO actuales."""
        new_matches, new_players = [], []
        for _, row in fixture_df.iterrows():
            stadium = row.get('stadium', random.choice(list(STADIUMS.keys())))
            tournament = row.get('tournament', 'Amistoso')
            partido, jugadores = self._simular_partido(
                row['home'], row['away'], stadium, row['date'], tournament
            )
            new_matches.append(partido)
            new_players.extend(jugadores)
        return pd.DataFrame(new_matches), pd.DataFrame(new_players)
