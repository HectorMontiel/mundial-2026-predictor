# 🏆 Motor Predictivo TDA — Mundial 2026 (v4, plantilla de análisis completa)

## Novedades v21 — API-Football: Champions operativa, backfill de stats y H2H (ver [VALIDACION_v21.md](VALIDACION_v21.md))

- **Gateway API-Football** ([api_football_manager.py](api_football_manager.py)):
  contador diario (plan Free: 100 req/día), caché agresiva con TTL por tipo y
  prioridades con reserva de presupuesto. La clave se lee de
  `API_FOOTBALL_KEY` (env / `st.secrets` / `.streamlit/secrets.toml`
  gitignorado) y **jamás se commitea**. En Streamlit Cloud: Settings →
  Secrets → `API_FOOTBALL_KEY = "tu_clave"`.
- **🇪🇺 Champions League OPERATIVA** (beta desde v12): 707 partidos reales
  2022-2025 vía API-Football (3 requests, cacheados), nombres canonicalizados
  por ID. Split 56.8 % / 0.955 (ELO 54.5 %); walk-forward 2024-25: 53.5 %
  vs ELO 51.6 % — supera el umbral del 50 % y se activa. Limitación honesta
  del plan Free (solo temporadas 2022-2024): la forma de los equipos queda
  congelada a 2024-25 y la UI lo avisa.
- **Backfill progresivo de estadísticas** ([backfill_stats.py](backfill_stats.py)):
  el pipeline gasta el presupuesto sobrante en posesión/remates/córners/
  tarjetas de partidos 2022-2024 (Liga MX → Primeira → Champions) para el
  reentrenamiento de v22 (~25 días de acumulación).
- **📜 Historial reciente (H2H)**: en clubes vía API-Football (bajo demanda,
  caché 24 h); en el Mundial desde el histórico local de Kaggle (gratis).
- **No posible con el plan Free** (documentado con evidencia): alineaciones
  en vivo, cuotas BTTS y lesiones — requieren la temporada en curso o odds,
  ambas bloqueadas. ESPN sigue siendo la fuente de alineaciones.

## Novedades v20 — Simetría local/visitante, SmartParlayBuilder y panel de ROI (ver [VALIDACION_v20.md](VALIDACION_v20.md))

- **Simetría del Mundial corregida** ([prediction_api.py](prediction_api.py)):
  al invertir local y visitante las probabilidades diferían en promedio 18 pp
  (hasta 47 pp). Ahora la inferencia es simétrica: en sede neutral
  `P(gana A | A vs B) = P(gana A | B vs A)` exacto, y el anfitrión
  (MEX/USA/CAN en su país) conserva su ventaja real lo listes como local o
  visitante. Validado: mejora la precisión (60.38→60.49 %) y el log-loss
  (0.8712→0.8688) sobre los 2,640 partidos de validación.
  Test permanente: [test_simetria.py](test_simetria.py).
- **SmartParlayBuilder** ([match_parlay.py](match_parlay.py)): perfiles con
  garantías reales y distintos por construcción — 🛡️ conservador ≥60 %
  conjunto (reduce picks antes que relajar), ⚖️ medio en la zona 15-60 %,
  🚀 agresivo con la cuota más alta que respete ≥5 % conjunto y ≥30 % por
  pick (adiós a los parlays del 0.2 %: ahora cuota ~18× con 5 % real).
  Diversidad mínima de categorías `min(3, N-1)`, máximo un mercado de
  córners y uno de tarjetas, y explicación de la composición en la UI.
- **Panel de rendimiento por liga + simulador de bankroll**: ROI simulado
  con cuotas de cierre reales por liga (modelo vs mercado) y simulación
  cronológica de banca con ¼ Kelly (tope 5 %) y gráfico de evolución.
- **Alineaciones automatizadas (infraestructura)**: minutos estimados desde
  los flags de ESPN, `jugadores_xg.csv` con xG/90 bayesiano
  ([player_db.py](player_db.py)) y banner informativo del xG ajustado por
  once confirmado — sin tocar el 1X2 hasta que haya backtest (v21).
- Liga MX: modelos separados regular/liguilla evaluados y descartados con
  evidencia (−0.2 pp); el mercado sigue sin batirse y así se reporta.

## Novedades v19 — Banca, alineaciones sombra y Liga MX reforzada (ver [VALIDACION_v19.md](VALIDACION_v19.md))

- **Liga MX**: cuotas + features mexicanas (altitud, distancia de viaje,
  liguilla, apertura/clausura) + beta calibration — walk-forward
  50.7→51.7 % (+1.0 pp); modelo desplegado 52.4 % / 0.998. El mercado
  (53.5 %) sigue arriba y así se reporta.
- **Gestión de banca** ([bankroll_manager.py](bankroll_manager.py)):
  bankroll configurable en la barra lateral y stake por **¼ de Kelly** (tope
  5 %) en la tabla de EV y en el parlay con cuotas reales. Solo informativo,
  con aviso de juego responsable.
- **Hándicap asiático ±0.5** con cuota real y EV en la plantilla (línea y
  cuotas B365 de fixtures.csv — sin scraping). BTTS pospuesto: sin fuente
  gratuita legal.
- **Alineaciones confirmadas en modo sombra**
  ([lineup_collector.py](lineup_collector.py)): el JSON de ESPN publica el
  once titular de las 8 ligas + Mundial; se acumulan a diario en
  `alineaciones_historicas.csv` sin tocar las predicciones, para evaluar su
  impacto al cierre de la temporada 2026-27. Verificado con 4 partidos
  reales del Mundial.
- **Poisson puro para 1X2**: evaluado en Serie A, Bundesliga y Liga MX —
  inferior al ensemble calibrado en las tres; descartado con evidencia.

## Novedades v18 — Serie A recuperada, Liga MX con cuotas y EV en la UI (ver [VALIDACION_v18.md](VALIDACION_v18.md))

- **Serie A**: la ganancia de las cuotas de cierre (+4.4 pp que v17 rechazó
  por log-loss) se recuperó con **beta calibration**
  (`ModeloBetaCalibrado`): walk-forward 49.0→52.2 % con log-loss 1.047→0.998.
- **Liga MX**: `MEX.csv` siempre tuvo cuotas de CIERRE (`AvgC*`, 100 % de
  cobertura) — el parser leía las de apertura, inexistentes. Con el fix:
  cuotas como features (walk-forward +1.7 pp / −0.028) y primera línea base
  de mercado para MX (53.5 %). En vivo, las cuotas del día llegan de la
  página diaria de Betexplorer (`cuotas_clubes_hoy`, única fuente gratuita
  MX).
- **EV en la plantilla**: nueva sección "💰 Cuotas reales y valor" en el
  Mundial y las 8 ligas — cuota real (decimal y americana), EV % e indicador
  🟢/🟡/⚪/🔴 por mercado, con N/D honesto cuando no hay cuotas vigentes.
- Alineaciones confirmadas: pospuesta otra vez con evidencia (sin histórico
  gratuito backtesteable; xG/90 por jugador no computable con Kaggle).

## Novedades v17 — Ligas de clubes más precisas (ver [VALIDACION_v17.md](VALIDACION_v17.md))

- **Ciclo de experimentos por liga** ([run_league_experiments.py](run_league_experiments.py)):
  screening de 10 ideas × 8 ligas + walk-forward de confirmación. Adopciones
  (todas confirmadas fuera de muestra): **cuotas de cierre B365 como
  features** (LaLiga +1.5 pp, Eredivisie +0.4, Ligue 1 log-loss −0.057),
  **extras de contexto** — H2H, descanso, rachas, clasificación viva —
  (Premier +1.2 pp con cuotas, Bundesliga +0.5) e **histórico de 10
  temporadas** en Primeira (+0.4 pp). Serie A y Liga MX sin cambios (nada
  pasó la regla de oro; el caso Serie A +4.4 pp quedó fuera por log-loss).
- **Bundesliga ahora supera al favorito del mercado** (56.3 % vs 55.0 % del
  cierre B365) — segunda liga tras Premier donde el modelo bate al mercado.
- En inferencia, las cuotas usan el snapshot vigente de `odds_actuales.json`
  o la media del train (imputación v11); el estado de contexto viaja en
  `team_stats_{liga}.json → estado_extra`.
- **Fix crítico**: `ClubEngine.predecir` aún importaba giotto-tda (residuo
  de v14) — en el cloud habría fallado toda predicción de clubes. Migrado a
  ripser.

## Novedades v16 — Parlay dinámico + barrera del 60 % superada (ver [VALIDACION_v16.md](VALIDACION_v16.md))

- **Modelo del Mundial: 59.4 → 60.4 % / 0.871** (walk-forward 60.0 % / 0.870,
  +0.5 pp y −0.038 vs v13). La mejora ganadora del ciclo de 12 experimentos
  gratuitos ([run_experiments.py](run_experiments.py)) fue ampliar el
  histórico de Kaggle de 2010 a **1990** (32,386 partidos): cero features
  nuevas, cero cambios de inferencia. Stacking, H2H rico, importancia del
  torneo y blend Poisson pasaron el screening sobre la base 2010 pero NO
  aportan sobre la base 1990 — documentado con evidencia.
- **Parlay por partido DINÁMICO**: los perfiles ahora generan combinaciones
  distintas (conservador ≥70 % maximiza probabilidad y reduce picks antes que
  relajar; medio ≥55 % balancea `prob × cuota^0.3`; agresivo ≥30 % maximiza
  cuota/EV — paga 120-350× vs ~2× del conservador). Slider **2-8** picks y
  regla estricta de UNA línea por mercado (nunca "más de 6.5" y "más de 7.5"
  córners juntos).

## Novedades v15 — Parlay por partido en todas las competiciones

**🎯 Parlay de ESTE partido** ([match_parlay.py](match_parlay.py)): en la vista
de cualquier partido (Mundial y las 8 ligas de clubes) hay un asistente que
combina mercados DEL MISMO encuentro:

- **Número de apuestas**: slider de 4 a 8 (por defecto 6).
- **Perfil de riesgo**: 🛡️ Conservador (prob ≥65 % por selección) ·
  ⚖️ Medio (≥55 %) · 🚀 Agresivo (≥50 %). Si no hay suficientes mercados,
  relaja el umbral solo lo necesario y lo avisa.
- **Reglas de compatibilidad**: nunca combina opciones excluyentes (1X2,
  over/under de la misma línea, BTTS vs 0-0…), elimina apuestas equivalentes
  (hándicap ±0.5 = 1X2/doble oportunidad) y aplica **haircut de correlación
  0.95** por cada pareja de la misma familia (resultado/goles/córners/tarjetas).
- **Cuotas reales** de `odds_actuales.json` cuando existen (fixtures.csv /
  Betexplorer): el parlay maximiza EV; sin ellas usa cuotas justas y avisa
  "EV teórico — no accionable".
- **Riesgo de mercado**: si el partido está 🔴 en `risk_flags.json`, el
  asistente lo excluye por defecto (desactivable).
- Exportación en texto plano + bloque copiable. El parlay multi-partido del
  fixture del Mundial sigue disponible e intacto.
- Tests: [test_match_parlay.py](test_match_parlay.py) (unitarios, ambos
  motores) + AppTest de integración en Mundial y Serie A.

**Cualquier persona pregunta "¿quién gana?" para CUALQUIER par de las 48
selecciones y obtiene una respuesta clara — y además la Plantilla General de
Análisis Estadístico completa (9 secciones, ~85 campos: 1X2, doble oportunidad,
hándicaps asiáticos, over/under, BTTS, goleadores, córners y tarjetas),
editable y validable contra el modelo.**

## Novedades v14 — "Solo gratis, solo real" (ver [VALIDACION_v14.md](VALIDACION_v14.md))

- **M7 (en vivo gratis)**: ESPN (JSON público, sin clave) como fuente en vivo
  del Mundial — sustituye a Flashscore (JS frágil). Dedupe robusto por par de
  equipos ±1 día y mapeo de nombres ESPN→Kaggle. +19 partidos reales del
  Mundial el día de la corrida.
- **M8 (xG real)**: [understat_scraper.py](understat_scraper.py) funcional
  (5 grandes ligas, 98 % de emparejamiento) pero **descartado como feature**:
  el A/B controlado empeoró el log-loss (LaLiga 1.014→1.108). Documentado.
- **M9 (ratings)**: [transfermarkt_scraper.py](transfermarkt_scraper.py)
  (1 petición/liga, caché 24 h) + flag `--ratings` en league_engine. Premier
  +1.8 pp en el A/B pero **no adoptado**: sesgo de anticipación (valores
  actuales aplicados a partidos pasados).
- **M10 (cuotas gratis)**: `fixtures.csv` de football-data (clubes, B365 sin
  clave) + [betexplorer_scraper.py](betexplorer_scraper.py) (Mundial, días de
  partido, robots.txt respetado) → `odds_actuales.json` → parlay.
- **M11 (UI apostador)**: modo **Principiante/Pro**, Asistente de Parlay en
  3 pasos con perfil de riesgo (conservador/medio/agresivo), tooltips de
  EV/cuotas y aviso de juego responsable.
- **M12 (5 ligas nuevas)**: Serie A, Bundesliga, Ligue 1, Eredivisie y
  Primeira Liga — todas superan su línea base ELO (ventana de temporadas
  elegida por backtest, regla ≥0.5 pp).
- **M13 (orquestador)**: [pipeline_total.py](pipeline_total.py) — un comando
  actualiza Mundial + 8 ligas + cuotas + Polymarket, con aislamiento de
  errores por paso.
- **Infra**: giotto-tda → **ripser** (segfault de giotto en Streamlit Cloud);
  Mundial reentrenado sin cambio material (59.4 % / 0.902).

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
