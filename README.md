# 🏆 Motor Predictivo TDA — Mundial 2026 (v4, plantilla de análisis completa)

**Cualquier persona pregunta "¿quién gana?" para CUALQUIER par de las 48
selecciones y obtiene una respuesta clara — y además la Plantilla General de
Análisis Estadístico completa (9 secciones, ~85 campos: 1X2, doble oportunidad,
hándicaps asiáticos, over/under, BTTS, goleadores, córners y tarjetas),
editable y validable contra el modelo.**

## Novedades v13 — Evolución total (ver [VALIDACION_v13.md](VALIDACION_v13.md))

- **M1**: cadena en vivo del Mundial ([live_worldcup.py](live_worldcup.py)) con
  API-Football → FBref → base, dedupe por MATCH_ID y banner con la fase oficial
  del torneo. Cron cada 2 h en días de partido.
- **M2**: [distributions.py](distributions.py) — 38 líneas over/under por
  partido (incl. córners y tarjetas POR EQUIPO) con caché <1 ms tras la
  primera llamada.
- **M3**: parlay con `odds_actuales.json`, filtro `ev_min` con cuotas reales,
  **filtro de riesgo** (excluye partidos 🔴), riesgo general del parlay y
  exportación. Backtest con cuotas de cierre reales: **ROI +10.9 % en Premier**
  (209 apuestas) y **−20 % en LaLiga** — el EV positivo solo existe donde el
  modelo supera al mercado, y así se muestra.
- **M4**: riesgo compuesto (🔴 div>20 pp Y liq>30 % · 🟡 div>15 O liq>20) →
  `risk_flags.json` consumido por el parlay. Snapshots cada 10 min.
- **M5**: Liga MX ampliada a 8 años (**47.6 → 51.4 %, +3.8 pp**) y LaLiga a
  5 temporadas (**47.9 → 49.9 %, +2.0 pp**); Premier revertida a v12 (el
  candidato bajó −0.6 pp). Ratings de jugadores y FBref: bloqueados desde
  esta red — módulos listos, features descartadas por no validables.
- **M6**: no regresión verificada — walk-forward del Mundial **59.5 %/0.908
  idéntico a v12** y EGY vs AUS bit a bit intacto.

## Novedades v12 — Plataforma multi-liga con mercados completos

- **Mejora 1 (Mundial en vivo)**: flag `--live` que fuerza la re-descarga de la
  fuente ignorando cachés (cron cada 2 h en días de partido); indicador
  "🟢 Datos actualizados al {fecha}" en la UI cuando el estado incluye la fase
  actual del torneo.
- **Mejora 2 (distribuciones)**: probabilidades EXACTAS de superar cada línea
  en todos los mercados cuantitativos — goles (totales y por equipo), córners
  (6.5→10.5, totales y por equipo), tarjetas (2.5→5.5), remates (18.5→24.5) y
  remates a puerta (4.5→7.5). Nueva sección 9b en la plantilla y endpoint
  `GET /distribuciones?home=&away=`. 40 líneas verificadas monótonas.
- **Mejora 3 (parlay inteligente)** ([parlay_builder.py](parlay_builder.py)):
  mejor parlay de 8 selecciones del fixture con umbral de probabilidad ≥55 %,
  cuota ≥1.10, máx. 2 por partido, exclusión de mercados dependientes,
  haircut de correlación 0.95 por pareja del mismo partido y cuota total ≤1000.
  Con `ODDS_API_KEY` usa cuotas reales y ordena por EV; sin ellas usa cuotas
  JUSTAS del modelo (EV≈0) y se etiqueta como informativo.
- **Mejora 4 (inteligencia de mercado, EXPERIMENTAL)**
  ([market_intelligence.py](market_intelligence.py)): snapshots de Polymarket
  (API pública Gamma) cada 15 min, con alertas de movimiento de probabilidad,
  cambios de liquidez >20 %, divergencia modelo-mercado >15 pts e indicador de
  riesgo de manipulación (🟢/🟡/🔴). Panel en la UI con aviso "no es
  asesoramiento financiero". Las señales NUNCA entran al 1X2 (evita fuga).
  *Alcance honesto:* el análisis de wallets on-chain requiere nodo/indexador
  propio; se aproxima el flujo con volumen/liquidez de la propia API.
- **Mejora 5 (ligas de clubes)** ([league_engine.py](league_engine.py)):
  **Liga MX, Premier League y LaLiga** con datos 100 % reales de
  football-data.co.uk (Premier/LaLiga incluyen remates, córners, tarjetas y
  cuotas de cierre reales) y modelos independientes por liga (misma
  arquitectura validada: ensemble calibrado + topología + regresores Poisson).
  Plantilla de clubes con 11 secciones/72 campos: 1X2 con cuota americana
  justa, doble oportunidad, over/under 0.5-5.5, BTTS, primer/último gol,
  par/impar, hándicap asiático completo, hándicap 1X2, marcador exacto (top 8),
  margen de victoria, mitades HT/2T, totales por equipo, multigoles, córners y
  tarjetas. Selector de competición en la barra lateral. **Champions en beta**
  (sin fuente CSV gratuita; requiere RAPIDAPI_KEY).

  **Backtesting por liga (temporal, datos reales):**

  | Liga | Partidos | Precisión | Línea base ELO | Favorito del mercado |
  |---|---|---|---|---|
  | Liga MX | 1,360 | **47.6 %** | 46.4 % | (sin cuotas en fuente) |
  | Premier League | 1,140 | **49.5 %** | 43.2 % | 45.9 % ✅ supera al mercado |
  | LaLiga | 1,140 | **47.9 %** | 46.1 % | 52.5 % (modelo por debajo — se reporta) |

- **No regresión verificada**: el 1X2 del Mundial es bit a bit idéntico
  (EGY vs AUS 0.388/0.253/0.359) y el benchmark walk-forward (59.5 %/0.908)
  sigue vigente — todo lo nuevo es aditivo.

## Novedades v11 — 49 selecciones, árbitros actualizables, cuotas y frescura

- **Cabo Verde (CPV)** integrado en todo el flujo: histórico real de Kaggle,
  ELO, MA5, goleadores reales (Livramento, Semedo), predicción y plantilla.
- **[referee_scraper.py](referee_scraper.py)**: actualización semanal de las
  estadísticas arbitrales desde WorldReferee (con `--scrape-arbitros`) y
  respaldo automático a la lista oficial pregrabada → `referees.json`, que
  `arbitros.py` carga al importar.
- **[fetch_odds.py](fetch_odds.py)**: cuotas 1X2 de apertura (The Odds API,
  variable `ODDS_API_KEY`) → `odds_historicas.csv`. Se usan SOLO en
  entrenamiento/backtesting como probabilidades implícitas + overround
  (4 features); en vivo se imputa la media de entrenamiento y la UI no
  muestra campos de cuotas. **Degradación limpia**: sin clave o sin cobertura
  (≥5 %), el modelo se entrena idéntico (registrado en `metadata.json`).
- **Cadena de respaldo de stats recientes**: FBref (`--fbref`, primaria) →
  API-Football (`RAPIDAPI_KEY`) → caché local. La UI muestra
  "⏰ Datos del {fecha}. Pueden no reflejar los partidos de ayer" si el
  estado tiene más de 24 h, y un botón **"🔄 Actualizar datos ahora"** que
  ejecuta el pipeline completo y recarga.
- **Fases detalladas** en la UI (grupos, dieciseisavos, octavos, cuartos,
  semifinal, final — las eliminatorias comparten el régimen de tensión).
- **Backtesting v11 (datos reales)**: split 2024+ → **59.5 % / log-loss 0.886**
  (mejor log-loss del proyecto); walk-forward 5 ventanas → **media 59.8 % /
  0.893**. El objetivo ≥61 % / ≤0.88 aún no se alcanza sin cuotas reales; con
  `odds_historicas.csv` poblado, el reentrenamiento las incorpora
  automáticamente (mejora esperada +1.0-1.5 pp según la especificación).

## Novedades v10 — Estadios oficiales, aclimatación y mejoras evaluadas

- **16 estadios oficiales** ([altitud.py](altitud.py)) con altitud real y
  selector en UI/API (`&estadio=Azteca`); sin sede se asume MetLife (2 m).
- **Capa de aclimatación** con las reglas exactas de la especificación:
  `ALT_HABITUAL` por selección (aclimatados: MEX 2240, ECU 2780, COL 2600);
  en sedes >1500 m el no habituado pierde 10 % (local) / 12 % (visitante) de
  xG (15 %/18 % sobre 2500 m); bono +5 % al local aclimatado por encima de la
  sede; el no aclimatado baja un escalón su rendimiento de 2ª mitad; córners
  +0.2 en altura. Verificado al decimal. **No toca el 1X2 calibrado** (la
  altitud ya entra al clasificador como feature entrenada ALTURA_NORM).
- **Walk-forward** (`--walkforward`): 5 ventanas de 6 meses (2024-2026),
  entrenamiento expansivo sin fuga: **precisión media 59.4 % · log-loss 0.894**
  (rango 57.4-62.5 %).
- **Optuna adoptado**: 12 trials TPE sobre XGB/LGBM → log-loss 0.8988→0.8974.
- **Mejoras evaluadas y RECHAZADAS con evidencia** (mismo split temporal):
  aumento sintético a 3000 (0.9001, peor que 904), distancia de Wasserstein
  H0 local-visitante (0.8992, sin ganancia), aclimatación como feature del
  clasificador (0.8994, solo 79 partidos de altura con desnivel), stacking
  con modelo binario de empate (log-loss 1.22, mucho peor). UMAP descartado
  técnicamente: las nubes tienen 6-10 puntos, insuficientes para UMAP (el
  camino PCA >50 dims ya existe). Los agregados de jugadores no entran al
  1X2 porque no existen datos individuales pre-partido reales del histórico.

## Novedades v6 — Lista arbitral ampliada y modelo de interacción

- **51 árbitros centrales oficiales** (lista actualizada FIFA + WorldReferee:
  10 CONMEBOL, 21 UEFA, 9 CONCACAF, 6 CAF, 5 AFC; nuevos: Piero Maza,
  Lamolina, Haro, Schärer, Eskås, Nyberg, Stieler, Peljto, Bastien, Hațegan,
  Soares Dias, J.M. Sánchez, Al-Hakim, Keylor Herrera, Buttimer).
- **Modelo de tarjetas v2 (interacción árbitro-equipo)**: el ancla es el p90
  REAL del árbitro, modulado por la desviación disciplinaria MA5 del equipo
  (+5 % por amarilla sobre 2.0), su estilo (+8 % bloque alto), la fase
  (+15 % eliminatoria / +5 % grupos) y el sesgo local (55 % ⇒ local ×0.90,
  visitante ×1.10). Se prefiere el ancla arbitral porque es la señal más real
  disponible para tarjetas.
- **Ajuste de reacción en eliminatorias**: la regla "+10 % de xG durante los
  15 minutos tras encajar" se integra a nivel de partido
  (Δλ ≈ λ×0.10×(15/90)×λ_rival) para equipos de reacción Fuerte, y castiga a
  los de reacción Débil; en grupos el efecto es la mitad. El 1X2 calibrado
  permanece intacto (verificado por prueba).
- **Selector de fase** (grupos / eliminación directa) en UI y API
  (`&fase=eliminatoria`).

## Novedades v5 — Arbitraje y carácter de los equipos

- **Módulo de árbitros** ([arbitros.py](arbitros.py)): árbitros centrales
  oficiales del Mundial 2026 (FIFA + WorldReferee 2022-2025, incl. Katia García,
  Frappart, Mukansanga) con amarillas/rojas/penaltis por 90', criterio y sesgo
  local. Penaltis repartidos por volumen ofensivo. El 1X2 calibrado NO se toca
  (el árbitro solo afecta tarjetas, penaltis, timeline e insights).
- **Carácter con minutos de gol REALES** (Kaggle goalscorers): por selección se
  calcula `REACCION_TRAS_GOL` (¿responde tras encajar?), `RENDIMIENTO_2DA_MITAD`
  (% de goles en la 2ª parte) y goles encajados en los últimos 15 minutos. Se
  usan en la línea de tiempo, los insights y las observaciones de la plantilla.
  *Nota de rigor:* se probaron como features del clasificador y NO mejoraron el
  backtesting (solo hay minutos desde 2018), así que se excluyeron del 1X2
  siguiendo la regla "solo features con poder predictivo demostrado".
- **UI**: selector de árbitro designado; la vista rápida muestra tarjetas/rojas/
  penalti esperados y la plantilla añade la línea del árbitro + 6 campos nuevos
  (tarjetas por equipo, rojas esperadas, probabilidades de penalti).
- **API**: `GET /predict?home=&away=&arbitro=`, ídem `/plantilla`, y `GET /arbitros`.

## Novedades v4

- **Ensemble calibrado**: XGBoost + Random Forest + LightGBM (voto suave) con
  `CalibratedClassifierCV(method='isotonic')`. La calibración se verifica en
  `backtesting.ipynb`: en picks de confianza > 70 %, el acierto real es ~80 %.
- **Topología por equipo**: entropías de persistencia H0/H1 de la nube de los
  **últimos 10 partidos de cada selección** + la nube combinada del par
  (6 features topológicas en total).
- **Regresores de goles esperados**: `HistGradientBoostingRegressor` con
  pérdida de Poisson para λ local y λ visitante — alimentan el Monte Carlo.
- **Aumento sintético**: ~1,000 partidos del generador correlacionado se suman
  SOLO al entrenamiento (nunca a la validación real).
- **Plantilla editable en la UI** (pestaña "📋 Plantilla de Análisis"):
  todos los campos pre-rellenados por el modelo, botón **"Validar mis
  estimaciones"** (diferencias, cuota justa 1/p y detección de valor) y
  exportación a Markdown (valores del modelo o los tuyos).
- **Endpoint** `GET /plantilla?home=MEX&away=ECU` (`&formato=markdown` opcional).
- **Notebook de backtesting** (`backtesting.ipynb`): precisión, log-loss,
  matriz de confusión, curvas de calibración y estabilidad por trimestre.

## Arquitectura híbrida de 3 fuentes abiertas (sin scraping frágil)

| Fuente | Aporte | Cómo |
|---|---|---|
| **Kaggle** – International Football Results | +15,800 resultados REALES desde 2010, actualizados al día (incluye goleadores con nombre) | `kagglehub`, sin credenciales |
| **API-Football** (RapidAPI, gratuita) | Estadísticas reales de los últimos partidos (remates, posesión, tarjetas) | Opcional: variable `RAPIDAPI_KEY` |
| **StatsBomb Open Data** | Calibra las relaciones goles↔xG↔remates del Mundial 2022 | Descarga única, caché en `calibracion_statsbomb.json` |

Las métricas avanzadas que las fuentes no traen se completan con el
**generador correlacionado calibrado** (coherentes con los goles reales y el
ELO — señal causal, no ruido).

```
Kaggle results ──► ELO cronológico ──► relleno calibrado (StatsBomb)
      │                                        │
      ▼                                        ▼
goleadores.csv                      historico_partidos.csv
      │                                        │
      ▼                                        ▼
jugadores_clave.csv ◄── update_team_stats ──► team_stats.json
                                               │
                            train_tda_model (backtesting temporal)
                                               │
                    prediction_api ──► dashboard_ui / GET /predict
```

## Archivos

```
├── data_fetcher.py                    # Kaggle + API-Football + unificación
├── statsbomb_calibration.py           # Calibración xG↔goles↔remates (con priors fallback)
├── correlated_synthetic_generator.py  # Relleno causal + generador de respaldo
├── update_team_stats.py               # ELO + MA5 -> team_stats.json · goleadores reales
├── feature_engineering.py             # Features pre-partido sin fuga + nubes TDA
├── train_tda_model.py                 # Vietoris-Rips + entropías + RF calibrado
├── prediction_api.py                  # Motor {home,away} -> JSON · FastAPI opcional
├── dashboard_ui.py                    # ⭐ "¿Quién gana?" (Streamlit)
├── fbref_scraper_v2.py                # (opcional, ya no es la fuente primaria)
├── pipeline_mundial.py                # Orquestador diario
└── PLAN_DE_PRUEBAS.md
```

## Puesta en marcha

```bash
# Entorno: Python 3.10–3.12 (giotto-tda no soporta 3.13)
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt

# 1. Datos reales + estado por selección (diario)
.venv\Scripts\python pipeline_mundial.py

# 2. Entrenamiento con backtesting temporal
.venv\Scripts\python train_tda_model.py --corte 2024-01-01

# 3. Dashboard (http://localhost:8501)
.venv\Scripts\python -m streamlit run dashboard_ui.py

# 4. (opcional) API HTTP (http://localhost:8000)
.venv\Scripts\python prediction_api.py
#    GET /predict?home=ARG&away=FRA · GET /query?q=... · GET /health
```

## Resultados de backtesting (datos REALES, ensemble v4)

| Métrica | Valor |
|---|---|
| Entrenamiento | 12,608 partidos reales (2010 → 2023) + 904 sintéticos correlacionados |
| Validación temporal | 2,616 partidos reales (2024 → 2026) |
| **Precisión** | **59.4 %** ✅ (regla de oro: ≥ 55 %) |
| Línea base "siempre el favorito por ELO" | 58.9 % |
| Log-loss | 0.892 |
| Precisión en picks con confianza > 70 % | **80.4 %** (682 partidos) |
| Objetivo estricto (≥ 62 % / ≤ 0.85) | ❌ no alcanzado — se reporta con transparencia |

> El techo empírico del 1X2 internacional (incluyendo empates) ronda el
> 60-65 % incluso para modelos comerciales. La calibración isotónica hace que
> las probabilidades sean confiables para detectar valor, que es lo que
> realmente importa en la plantilla.

## Reglas de oro

- **Precisión > todo**: si el backtesting temporal baja de 55 %, `deploy_ready`
  se apaga y la UI muestra "Modelo en modo referencia".
- **Transparencia**: `fuente_datos.json` registra la procedencia. Con fuentes
  reales la UI muestra "✅ Resultados reales actualizados al AAAA-MM-DD"; si
  todo falla y se usa el generador de respaldo: "⚠️ Datos estimados –
  precisión limitada".
- **Simplicidad radical**: insights en lenguaje llano; los goleadores del
  tablero "¿Quién remata?" son reales (Kaggle goalscorers, últimos 24 meses).

## Ejecución diaria automática (Windows)

```powershell
schtasks /create /tn "PipelineMundial2026" `
  /tr "C:\ruta\proyecto\.venv\Scripts\python.exe C:\ruta\proyecto\pipeline_mundial.py --train" `
  /sc daily /st 06:00
```
