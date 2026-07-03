#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gestión de históricos, actualización incremental y construcción de datasets.

Fuente primaria: scraping real de FBref (fbref_scraper_v2).
Respaldo: CorrelatedSyntheticGenerator (con causalidad realista).
La procedencia se registra en fuente_datos.json para que la UI pueda
mostrar el aviso "Datos estimados – precisión limitada" cuando corresponda.
"""

import pandas as pd
import numpy as np
import os
import json
import datetime
import logging
from typing import Tuple, Optional, List, Dict
from config import *
from correlated_synthetic_generator import CorrelatedSyntheticGenerator, nombre_jugador

logger = logging.getLogger(__name__)

FUENTE_FILE = 'fuente_datos.json'


def registrar_fuente(source: str):
    """Persiste la procedencia de los datos: 'real' o 'synthetic'."""
    with open(FUENTE_FILE, 'w', encoding='utf-8') as f:
        json.dump({'source': source,
                   'updated': datetime.date.today().isoformat()}, f)


class DataManager:
    def __init__(self, use_real: bool = True):
        self.use_real = use_real
        self.synthetic = CorrelatedSyntheticGenerator()
        self.scraper = None
        if use_real:
            try:
                from fbref_scraper_v2 import FBrefScraperV2
                self.scraper = FBrefScraperV2()
            except Exception as e:
                logger.warning(f"Scraper v2 no disponible ({e}). Se usará el generador correlacionado.")
                self.use_real = False
        self.matches_df = pd.DataFrame()
        self.players_df = pd.DataFrame()
        self.elo = {}

    # ------------------------------------------------------------------ #
    # Carga / inicialización                                              #
    # ------------------------------------------------------------------ #
    def load_or_initialize_data(self) -> None:
        """Carga históricos si existen; si no, scraping real con fallback sintético."""
        if os.path.exists(HISTORICO_FILE) and os.path.exists(HISTORICO_JUGADORES_FILE):
            self.matches_df = pd.read_csv(HISTORICO_FILE, parse_dates=['date'])
            self.players_df = pd.read_csv(HISTORICO_JUGADORES_FILE, parse_dates=['match_date'])
            logger.info(f"Cargados {len(self.matches_df)} partidos históricos.")
            if os.path.exists(ELO_FILE):
                self.elo = pd.read_csv(ELO_FILE, index_col=0).squeeze().to_dict()
            else:
                self._initialize_elo_from_results()
                self._save_elo()
            return

        logger.info("No se encontraron históricos. Generando datos iniciales...")
        if self.use_real and self.scraper:
            try:
                if self.scraper.load_nation_links():
                    historical = self.scraper.build_full_historical_dataset(years_back=5)
                    if not historical.empty and len(historical) >= 200:
                        self.matches_df = historical
                        self._generate_synthetic_players_for_existing_matches()
                        self.matches_df.to_csv(HISTORICO_FILE, index=False)
                        self.players_df.to_csv(HISTORICO_JUGADORES_FILE, index=False)
                        self._initialize_elo_from_results()
                        self._save_elo()
                        registrar_fuente('real')
                        logger.info("Históricos reales construidos desde FBref (5 años).")
                        return
            except Exception as e:
                logger.warning(f"Scraping falló: {e}. Usando generador correlacionado.")

        # Respaldo: generador sintético con causalidad realista (5 años)
        self.matches_df, self.players_df = self.synthetic.generate_initial_history(days_back=1825)
        self.matches_df.to_csv(HISTORICO_FILE, index=False)
        self.players_df.to_csv(HISTORICO_JUGADORES_FILE, index=False)
        self.matches_df['date'] = pd.to_datetime(self.matches_df['date'])
        self.players_df['match_date'] = pd.to_datetime(self.players_df['match_date'])
        self.elo = dict(self.synthetic.elo)
        self._save_elo()
        registrar_fuente('synthetic')
        logger.info(f"Histórico sintético correlacionado generado: {len(self.matches_df)} partidos.")

    def _initialize_elo_from_results(self):
        """Reconstruye el ELO recorriendo cronológicamente el histórico."""
        self.elo = {t: 1500.0 for t in TEAMS}
        if 'home_team' not in self.matches_df.columns:
            return
        for _, row in self.matches_df.sort_values('date').iterrows():
            h, a = row['home_team'], row['away_team']
            self.elo[h], self.elo[a] = self.synthetic.compute_elo_update(
                self.elo.get(h, 1500.0), self.elo.get(a, 1500.0),
                row['home_goals'], row['away_goals']
            )

    def _save_elo(self):
        pd.Series(self.elo, name='ELO').to_csv(ELO_FILE)

    def _generate_synthetic_players_for_existing_matches(self):
        """
        Jugadores para partidos scrapeados (FBref no expone alineaciones en el
        matchlog): rendimiento individual coherente con las estadísticas
        colectivas reales de ese partido.
        """
        from correlated_synthetic_generator import (
            XG_SHARE_POSICION, REMATES_BASE_POSICION, PASES_CLAVE_POSICION)
        rng = np.random.default_rng(42)
        all_players = []
        for _, match in self.matches_df.iterrows():
            for lado, equipo in [('home', match['home_team']), ('away', match['away_team'])]:
                xg_eq = float(match.get(f'{lado}_xg', 1.0) or 1.0)
                goles_eq = int(match.get(f'{lado}_goals', 0) or 0)
                shares = np.array([XG_SHARE_POSICION[p] for p in POSITIONS])
                probs = shares / shares.sum()
                goles_pos = rng.multinomial(goles_eq, probs)
                for i, pos in enumerate(POSITIONS):
                    remates = max(0, int(round(REMATES_BASE_POSICION[pos] + rng.normal(0, 0.7))))
                    all_players.append({
                        'MATCH_ID': match['MATCH_ID'], 'match_date': match['date'],
                        'JUGADOR_ID': f"{equipo}_{pos}_{i+1}",
                        'NOMBRE': nombre_jugador(equipo, pos, i),
                        'EQUIPO': equipo, 'POSICION': pos,
                        'MINUTOS': int(np.clip(rng.normal(84, 9), 45, 90)),
                        'GOLES': int(goles_pos[i]),
                        'XG': round(max(0.0, xg_eq * XG_SHARE_POSICION[pos] * rng.uniform(0.7, 1.3)), 3),
                        'REMATES': remates,
                        'REMATES_ARCO': min(remates, int(round(remates * rng.uniform(0.3, 0.55)))),
                        'PASES_CLAVE': int(max(0, rng.poisson(PASES_CLAVE_POSICION[pos]))),
                        'AMARILLAS': int(rng.binomial(1, 0.1)),
                        'ROJAS': int(rng.binomial(1, 0.015)),
                    })
        self.players_df = pd.DataFrame(all_players)

    # ------------------------------------------------------------------ #
    # Actualización incremental diaria                                    #
    # ------------------------------------------------------------------ #
    def update_to_date(self, target_date: datetime.date):
        """Scrapea/simula partidos desde la última fecha registrada hasta target_date."""
        if not self.matches_df.empty:
            last_date = pd.to_datetime(self.matches_df['date']).max().date()
        else:
            last_date = datetime.date(2020, 1, 1)

        if last_date >= target_date:
            logger.info("Histórico ya actualizado hasta la fecha objetivo.")
            return

        if self.use_real and self.scraper:
            try:
                new_data = self.scraper.build_full_historical_dataset(years_back=1)
                if not new_data.empty:
                    new_data['date'] = pd.to_datetime(new_data['date'])
                    new_data = new_data[new_data['date'].dt.date > last_date]
                    if not new_data.empty:
                        self.matches_df = pd.concat([self.matches_df, new_data], ignore_index=True)
                        self.matches_df = self.matches_df.drop_duplicates(subset='MATCH_ID', keep='last')
                        self.matches_df.to_csv(HISTORICO_FILE, index=False)
                        self._generate_synthetic_players_for_existing_matches()
                        self.players_df.to_csv(HISTORICO_JUGADORES_FILE, index=False)
                        self._initialize_elo_from_results()
                        self._save_elo()
                        registrar_fuente('real')
                        logger.info(f"Añadidos {len(new_data)} partidos reales nuevos.")
                        return
            except Exception as e:
                logger.warning(f"Actualización real falló: {e}")

        # Respaldo sintético correlacionado
        dates = pd.date_range(last_date + datetime.timedelta(days=1), target_date, freq='3D')
        if len(dates) == 0:
            return
        rng = np.random.default_rng(int(target_date.strftime('%Y%m%d')))
        fixture_rows = []
        for d in dates:
            teams_day = rng.choice(TEAMS, size=min(4, len(TEAMS)), replace=False)
            for i in range(0, len(teams_day), 2):
                fixture_rows.append({
                    'date': d, 'home': teams_day[i], 'away': teams_day[i + 1],
                    'stadium': str(rng.choice(list(STADIUMS.keys()))),
                    'tournament': 'Amistoso',
                })
        new_m, new_p = self.synthetic.generate_new_matches(pd.DataFrame(fixture_rows))
        self.matches_df = pd.concat([self.matches_df, new_m], ignore_index=True)
        self.players_df = pd.concat([self.players_df, new_p], ignore_index=True)
        self.matches_df.to_csv(HISTORICO_FILE, index=False)
        self.players_df.to_csv(HISTORICO_JUGADORES_FILE, index=False)
        self.matches_df['date'] = pd.to_datetime(self.matches_df['date'])
        self.players_df['match_date'] = pd.to_datetime(self.players_df['match_date'])
        self.elo = dict(self.synthetic.elo)
        self._save_elo()
        logger.info(f"Añadidos {len(new_m)} partidos sintéticos correlacionados.")

    # ------------------------------------------------------------------ #
    # Datasets de contexto para el fixture                                 #
    # ------------------------------------------------------------------ #
    def _stats_jugador_ma5(self, jugador_id: str, ref_date: datetime.date) -> Dict:
        """MA5 real del jugador a partir de su propio historial (sin aleatoriedad)."""
        hist = self.players_df[
            (self.players_df['JUGADOR_ID'] == jugador_id) &
            (self.players_df['match_date'] <= pd.Timestamp(ref_date))
        ].sort_values('match_date').tail(5)
        if hist.empty:
            return {'REMATES_TOTALES_MA5': 0.0, 'REMATES_ARCO_MA5': 0.0,
                    'XG_INDIVIDUAL_MA5': 0.0, 'PASES_CLAVE_MA5': 0.0,
                    'GOLES_ULTIMOS_5': 0, 'PARTIDOS_MARCANDO_DE_5': 0}
        col = lambda c: pd.to_numeric(hist[c], errors='coerce').fillna(0) if c in hist.columns else pd.Series([0.0] * len(hist))
        return {
            'REMATES_TOTALES_MA5': round(float(col('REMATES').mean()), 2),
            'REMATES_ARCO_MA5': round(float(col('REMATES_ARCO').mean()), 2),
            'XG_INDIVIDUAL_MA5': round(float(col('XG').mean()), 3),
            'PASES_CLAVE_MA5': round(float(col('PASES_CLAVE').mean()), 2),
            'GOLES_ULTIMOS_5': int(col('GOLES').sum()),
            'PARTIDOS_MARCANDO_DE_5': int((col('GOLES') > 0).sum()),
        }

    def build_context_datasets(self, upcoming_matches: List[Dict]) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """
        upcoming_matches: lista de dicts con match_id, home, away, stadium, date.
        Construye las tablas de contexto macro (equipos) y micro (jugadores)
        con medias móviles ponderadas de los últimos 5 partidos.
        """
        import feature_engineering as fe

        ref_date = min(pd.to_datetime(m['date']).date() for m in upcoming_matches) - datetime.timedelta(days=1)
        hoy = datetime.date.today()
        self.update_to_date(min(ref_date, hoy) if ref_date > hoy else ref_date)

        self.matches_df['date'] = pd.to_datetime(self.matches_df['date'])
        self.players_df['match_date'] = pd.to_datetime(self.players_df['match_date'])

        equipos_rows, jugadores_rows = [], []
        rng = np.random.default_rng(7)

        for match in upcoming_matches:
            match_id = match['match_id']
            home, away = match['home'], match['away']
            stadium = match['stadium']
            for equipo, rival, cond in [(home, away, 'Anfitrión'), (away, home, 'Visitante')]:
                team_matches = self.matches_df[
                    (self.matches_df['home_team'] == equipo) | (self.matches_df['away_team'] == equipo)
                ]
                team_matches = team_matches[team_matches['date'].dt.date <= ref_date] \
                    .sort_values('date', ascending=False).head(5)

                def stat(row, s_home, s_away):
                    return row[s_home] if row['home_team'] == equipo else row[s_away]

                if not team_matches.empty:
                    gf = [stat(r, 'home_goals', 'away_goals') for _, r in team_matches.iterrows()]
                    gc = [stat(r, 'away_goals', 'home_goals') for _, r in team_matches.iterrows()]
                    rf = [stat(r, 'home_shots_on', 'away_shots_on') for _, r in team_matches.iterrows()]
                    rc = [stat(r, 'away_shots_on', 'home_shots_on') for _, r in team_matches.iterrows()]
                    xf = [stat(r, 'home_xg', 'away_xg') for _, r in team_matches.iterrows()]
                    xc = [stat(r, 'away_xg', 'home_xg') for _, r in team_matches.iterrows()]
                    am = [stat(r, 'home_yellow', 'away_yellow') for _, r in team_matches.iterrows()]
                    rj = [stat(r, 'home_red', 'away_red') for _, r in team_matches.iterrows()]
                    # weighted_ma pondera el último de la lista: invertir a cronológico
                    gf_ma5 = self.synthetic.weighted_ma(gf[::-1])
                    gc_ma5 = self.synthetic.weighted_ma(gc[::-1])
                    rf_ma5 = self.synthetic.weighted_ma(rf[::-1])
                    rc_ma5 = self.synthetic.weighted_ma(rc[::-1])
                    xf_ma5 = self.synthetic.weighted_ma(xf[::-1])
                    xc_ma5 = self.synthetic.weighted_ma(xc[::-1])
                    am_ma5 = self.synthetic.weighted_ma(am[::-1])
                    rj_ma5 = self.synthetic.weighted_ma(rj[::-1])
                else:
                    gf_ma5 = gc_ma5 = rf_ma5 = rc_ma5 = xf_ma5 = xc_ma5 = am_ma5 = rj_ma5 = 0.0

                elo = self.elo.get(equipo, 1500.0)
                altitud = STADIUMS.get(stadium, 0)
                distancia = float(rng.uniform(100, 5000)) if cond == 'Visitante' else 0.0
                pct_europa = float(rng.beta(6, 2)) if equipo in ['ARG', 'BRA', 'FRA', 'ENG', 'ESP', 'GER', 'POR'] else float(rng.beta(2, 3))
                indice_polemica = float(rng.uniform(0.3, 0.95))

                rival_style = TEAM_STYLE.get(rival, 'bloque_alto')
                if rival_style == 'bloque_bajo':
                    goles_vs_estilo, rem_permitidos = gc_ma5 * 0.9, rc_ma5 * 0.85
                else:
                    goles_vs_estilo, rem_permitidos = gc_ma5 * 1.15, rc_ma5 * 1.25

                # ---- Jugadores: última alineación + MA5 real por jugador ----
                ultima_fecha = self.players_df[self.players_df['EQUIPO'] == equipo]['match_date'].max()
                alineacion = self.players_df[
                    (self.players_df['EQUIPO'] == equipo) &
                    (self.players_df['match_date'] == ultima_fecha)
                ] if pd.notna(ultima_fecha) else pd.DataFrame()

                jugadores_equipo = []
                for _, row_j in alineacion.iterrows():
                    minutos_30d = self.players_df[
                        (self.players_df['JUGADOR_ID'] == row_j['JUGADOR_ID']) &
                        (self.players_df['match_date'] >= pd.Timestamp(ref_date - datetime.timedelta(days=30))) &
                        (self.players_df['match_date'] <= pd.Timestamp(ref_date))
                    ]['MINUTOS'].sum()
                    ma5 = self._stats_jugador_ma5(row_j['JUGADOR_ID'], ref_date)
                    jugadores_equipo.append({
                        'MATCH_ID': match_id,
                        'JUGADOR_ID': row_j['JUGADOR_ID'],
                        'JUGADOR_NOMBRE': row_j.get('NOMBRE', row_j['JUGADOR_ID']),
                        'EQUIPO_NOMBRE': equipo,
                        'POSICION': row_j['POSICION'],
                        'PROBABILIDAD_TITULARIDAD': round(min(0.99, 0.5 + 0.5 * float(rng.beta(8, 2))), 2),
                        'ESTADO_MEDICO': 'Disponible' if rng.random() < 0.85 else 'Duda',
                        **ma5,
                        'MINUTOS_JUGADOS_30D': int(minutos_30d),
                        'EXPULSIONES_ACUMULADAS': int(pd.to_numeric(
                            self.players_df[self.players_df['JUGADOR_ID'] == row_j['JUGADOR_ID']]['ROJAS'],
                            errors='coerce').fillna(0).sum()) if 'ROJAS' in self.players_df.columns else 0,
                    })
                jugadores_rows.extend(jugadores_equipo)

                # ---- Agregación inteligente jugadores -> equipo (Bloque 1.3) ----
                agregados = fe.agregar_jugadores_a_equipo(pd.DataFrame(jugadores_equipo))

                equipos_rows.append({
                    'MATCH_ID': match_id,
                    'EQUIPO_ID': equipo,
                    'EQUIPO_NOMBRE': equipo,
                    'RIVAL_NOMBRE': rival,
                    'CONDICION': cond,
                    'ELO_DINAMICO': round(elo, 2),
                    'GOLES_ANOTADOS_MA5': round(gf_ma5, 2),
                    'GOLES_CONCEDIDOS_MA5': round(gc_ma5, 2),
                    'REMATES_ARCO_FAVOR_MA5': round(rf_ma5, 2),
                    'REMATES_ARCO_CONTRA_MA5': round(rc_ma5, 2),
                    'XG_FAVOR_MA5': round(xf_ma5, 2),
                    'XG_CONTRA_MA5': round(xc_ma5, 2),
                    'TARJETAS_AMARILLAS_MA5': round(am_ma5, 2),
                    'TARJETAS_ROJAS_MA5': round(rj_ma5, 2),
                    'ALTURA_SEDE_MSNM': altitud,
                    'DISTANCIA_VIAJE_KM': round(distancia, 2),
                    'PCT_JUGADORES_EUROPA': round(pct_europa, 2),
                    'INDICE_POLEMICA_LOCAL': round(indice_polemica, 2),
                    'GOLES_CONCEDIDOS_VS_ESTILO_RIVAL': round(goles_vs_estilo, 2),
                    'REMATES_PERMITIDOS_POR_BLOQUE': round(rem_permitidos, 2),
                    **agregados,
                })

        return pd.DataFrame(equipos_rows), pd.DataFrame(jugadores_rows)
