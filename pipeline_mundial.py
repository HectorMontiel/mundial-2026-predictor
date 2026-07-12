#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Pipeline diario — arquitectura híbrida de 3 fuentes abiertas.

Flujo (sin scraping frágil):
  1. Kaggle: base histórica de resultados REALES (descarga/caché kagglehub).
  2. API-Football (opcional, RAPIDAPI_KEY): estadísticas recientes reales.
  3. StatsBomb: calibración de las relaciones goles↔xG↔remates con las que
     el generador correlacionado completa las métricas faltantes.
  4. Recalcula ELO + medias móviles ponderadas -> team_stats.json.
  5. Goleadores reales -> jugadores_clave.csv.
  6. (--train) Reentrena el modelo TDA con validación temporal.

Si las fuentes reales fallan (sin red), degrada al generador sintético
correlacionado y lo registra en fuente_datos.json para que la UI avise.

Uso:
    python pipeline_mundial.py                  # actualización diaria híbrida
    python pipeline_mundial.py --train          # además reentrena el modelo
    python pipeline_mundial.py --synthetic      # fuerza el generador de respaldo
"""

import json
import logging
import sys
import datetime

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def flujo_sintetico_de_respaldo():
    """Genera un histórico sintético correlacionado (solo si no hay fuentes reales)."""
    from data_manager import DataManager, registrar_fuente
    logger.warning("Usando el generador sintético correlacionado de RESPALDO.")
    dm = DataManager(use_real=False)
    dm.load_or_initialize_data()
    dm.update_to_date(datetime.date.today())
    registrar_fuente('synthetic')


def main():
    forzar_sintetico = '--synthetic' in sys.argv

    # ------------------------------------------------------------------ 1-3
    if forzar_sintetico:
        flujo_sintetico_de_respaldo()
    else:
        try:
            import data_fetcher
            # --live: modo Mundial en curso — fuerza re-descarga de la fuente
            # ignorando cachés, para incorporar la jornada recién terminada.
            # Programar cada 2 h en días de partido:
            #   schtasks /create /tn "MundialLive" /tr "...pipeline_mundial.py --live" /sc hourly /mo 2
            data_fetcher.build_unified_history(usar_fbref='--fbref' in sys.argv,
                                               live='--live' in sys.argv)
            if '--live' in sys.argv:
                # Cadena en vivo adicional (API-Football/FBref) para capturar
                # partidos terminados hace minutos que la base aún no refleje
                import live_worldcup
                live_worldcup.actualizar_en_vivo()
        except Exception as e:
            logger.error(f"Capa de datos híbrida falló ({type(e).__name__}: {e}).")
            flujo_sintetico_de_respaldo()

    # ------------------------------------------------------------------ 4-5
    import update_team_stats
    update_team_stats.build_team_stats()
    update_team_stats.build_key_players()

    # ------------------------------------------------------------------ 5b
    # Árbitros (WorldReferee con respaldo pregrabado) y cuotas de apertura
    # (opcionales, solo entrenamiento). Ningún fallo aquí detiene el pipeline.
    try:
        import referee_scraper
        referee_scraper.actualizar_arbitros(intentar_scraping='--scrape-arbitros' in sys.argv)
    except Exception as e:
        logger.warning(f"Actualización de árbitros omitida: {e}")
    try:
        import fetch_odds
        fetch_odds.actualizar_odds()
    except Exception as e:
        logger.warning(f"Cuotas de apertura omitidas: {e}")

    # ------------------------------------------------------------------ 6
    if '--train' in sys.argv:
        logger.info("Reentrenando el modelo TDA (--train)...")
        from train_tda_model import entrenar
        entrenar()

    logger.info("Pipeline completado exitosamente.")


if __name__ == "__main__":
    main()
