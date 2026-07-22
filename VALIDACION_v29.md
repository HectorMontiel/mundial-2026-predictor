# VALIDACIÓN v29 — Ecosistema multi-deporte

**Fecha:** 2026-07-21 · Regla de oro respetada; fútbol (Mundial 60.49 % +
10 ligas) intacto y aislado.

## 1. Correcciones v28.1 ✅

- **§1.1 Exportar Apuestas del Día**: `download_button` en TXT y CSV
  (`alpha_finder.exportar_txt/exportar_csv`).
- **§1.2 Cobertura Liga MX**: causa raíz encontrada — el barrido descartaba
  EN SILENCIO los partidos cuyo nombre de equipo no mapeaba exacto a
  `team_stats` (Betexplorer/Odds API usan grafías distintas). Fix:
  respaldo fuzzy nombre→liga (`_liga_fuzzy`, ≥0.82) + logging de cobertura
  por liga y de partidos sin mapear. Verificado: el barrido pasó de
  `{mls:15}` a `{mls:15, liga_mx:2}`, 0 sin mapear.

## 2. Verificación de fuentes (empírica, lección Soccer24 v24)

| Deporte | Fuente histórica | Odds en vivo (gratis) | Veredicto |
|---|---|---|---|
| **MLB** | Retrosheet gl{año}.zip ✅ (11.9k juegos 2021-25, con abridores) | The Odds API `baseball_mlb` ✅ (en temporada, 5 casas) | **VIABLE — adoptado** |
| NBA | basketball-reference ❌ 403 Cloudflare; nba_api no instalado | The Odds API: solo futures (fuera de temporada jul) | **DIFERIDO** |
| Tenis | Jeff Sackmann GitHub ❌ 404 en todos los años probados | The Odds API: `tennis*` inexistente en free tier | **DIFERIDO** |

NBA y tenis se documentan como diferidos con evidencia: sin fuente
histórica accesible NI mercado en vivo gratuito, un motor no sería ni
validable ni accionable. Se reevaluarán si cambia el acceso (NBA vuelve en
octubre; para basketball-reference haría falta el navegador integrado, como
FBref en v22).

## 3. Arquitectura DRY (§2) ✅

`engines/base_engine.py` — `BaseSportsEngine` (ABC) con la mecánica común
(cargar_modelo, calcular_ev, aplicar_kelly, predecir, plantilla,
barrido_apuestas_dia) y dos métodos abstractos (cargar_datos_historicos,
construir_features). El **fútbol NO se refactoriza** (ClubEngine/
PredictionEngine intactos — no regresión); los deportes nuevos heredan.

## 4. MLB — motor validado (§4) ✅ ADOPTADO

- `retrosheet_scraper.py`: game logs → `historico_mlb.csv` (fecha, equipos,
  carreras y **abridor de cada lado** — la variable crítica del béisbol).
- `engines/mlb_engine.py`: features pre-partido sin fuga (ELO, carreras
  anotadas/permitidas MA10, racha, descanso, **carreras/apertura recientes
  del abridor**); ensemble XGB+LGBM+RF con calibración isotónica (binario,
  sin empate) + regresor Poisson de carreras totales.
- **Split 80/20: 55.3 % vs ELO 54.3 %** (+0.97 pp), log-loss 0.686.
- **Walk-forward (2 ventanas de temporada): 55.0 % vs ELO 54.2 %**
  (+0.79 pp), supera ELO en AMBAS — pasa la regla de oro. El béisbol tiene
  techo ~57 % (deporte de alta varianza); +0.8 pp sostenido es edge real.
- **Baseline honesto**: no hay cuotas MLB históricas gratuitas, así que la
  línea base es el favorito por ELO (no por cierre de mercado) — documentado.
- **En vivo**: `apuestas_dia()` consume The Odds API baseball_mlb, mapea
  nombres→códigos Retrosheet (fuzzy) y filtra prob>58 %/EV>3 %/cuota>1.50.
  Primer barrido real: 4 picks EV+ (Blue Jays +17.1 %, Royals +14.9 %,…).
- **Limitación**: el estado de equipos queda congelado al cierre de 2025
  hasta que Retrosheet publique 2026 (los zip anuales salen a fin de año) —
  avisado en la UI, igual que la forma congelada de Champions (v21).

## 5. UI (§6) ✅

Nueva competición ⚾ MLB en el selector: pestaña de predicción (moneyline +
total + plantilla) y pestaña de Apuestas del Día MLB en vivo. Sin dependencias
nuevas (xgboost/lightgbm/sklearn ya pinneadas).

## 6. No regresión ✅

test_simetria ✓ · test_match_parlay ✓ · smoke 10 ligas de fútbol ✓ ·
AppTest dashboard incl. vista MLB ✓ · Mundial intacto.

## 7. Diferido a v30

NBA con el navegador integrado (bypass Cloudflare de basketball-reference,
como FBref v22) cuando arranque la temporada; tenis si aparece una fuente
histórica accesible (mirror de Sackmann) — recordar que sin mercado en vivo
gratuito solo daría análisis, no apuestas.
