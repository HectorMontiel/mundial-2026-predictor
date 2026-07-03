@echo off
REM ============================================================
REM Actualización diaria del Motor Predictivo TDA - Mundial 2026
REM   1. Descarga resultados reales nuevos (Kaggle / API-Football)
REM   2. Recalcula ELO, medias móviles y entropías (team_stats.json)
REM   3. Actualiza goleadores reales (jugadores_clave.csv)
REM   4. Reentrena el ensemble si hay partidos nuevos (--train)
REM
REM Programar con:
REM   schtasks /create /tn "PipelineMundial2026" /tr "%~dp0actualizacion_diaria.bat" /sc daily /st 06:00
REM ============================================================
cd /d "%~dp0"
".venv\Scripts\python.exe" pipeline_mundial.py --train >> actualizacion_diaria.log 2>&1
