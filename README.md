# 🏆 Motor Predictivo TDA — Mundial 2026 (v4, plantilla de análisis completa)

## Novedades v33 — Verano, resiliencia y bot (ver [VALIDACION_v33.md](VALIDACION_v33.md))

- **🇧🇷 Brasileirão y 🇦🇷 Primera argentina** añadidas para cubrir el parón
  europeo. **Brasil bate al mercado (52.3 % vs 52.1 %)**. Japón NO se añade:
  football-data lleva 228 días sin publicarla (verificado).
- **🛡️ Cadena de resiliencia** (`source_resilience.py`): fuentes en cascada
  con degradación elegante. **Probada con fallo forzado**: la primaria cae y
  ESPN toma el relevo; si todas fallan, no rompe nada.
- **⏱️ MLS al día**: el estado de 58 días obsoleto que detecté en v32 está
  resuelto (reentrenada con datos al 18 de julio) y sale de la cuarentena.
- **🤖 Bot de Telegram** con GitHub Actions (cron diario), credenciales solo
  desde Secrets, y `--update-only` para refrescar datos en el runner.
- **📊 Umbrales adaptativos por deporte** y **semáforo de antigüedad** de
  datos (🟢/🟡/🔴) en cada pick.
- **❌ ELO Ataque/Defensa descartado**: 4 de 6 ligas se degradan (hasta
  −2 pp); los dos "positivos" son ruido de comparaciones múltiples.
- **📐 Optimizador de cartera** (Markowitz con covarianza diagonal entre
  deportes) como módulo experimental, sin sustituir al Kelly.

## Novedades v32 — Blindaje cuantitativo y plantillas realistas (ver [VALIDACION_v32.md](VALIDACION_v32.md))

- **🚫 Filtro de EV extremo, probado con datos**: los picks con EV > +15 %
  aciertan **15 pp por debajo** de lo prometido y su ROI es **12 pp peor**
  (1,495 apuestas históricas). Se segregan a una sección oculta por defecto.
- **🪜 Reto Escalera**: picks ≥85 % con suelo de cuota 1.05, un pick por
  partido y **Monte Carlo de 10.000 escaleras** (ruina a 10/20/30 días). Si
  no hay picks del nivel, se niega a arrancar en vez de rebajar el listón.
- **🥇 Pick del Día único** con desempate Brier → EV → probabilidad, y
  **fiabilidad histórica por liga** (Brier real de los picks publicados,
  traducido a 🟢/🟡/🔴).
- **📋 Plantillas ampliadas con rigor**: NBA/MLB suman spread y totales por
  equipo desde el margen ~N(μ,σ) con σ calibrada (15.58 / 4.48); tenis pasa
  a **19 mercados** (total y hándicap de juegos con regresión sobre 68k
  partidos, reparto de sets). Lo no derivable se declara excluido.
- **📊 Rendimiento real** persistido en SQLite (WAL) y **copiado al
  portapapeles**.

## Novedades v31 — Apuestas del Día universales (ver [VALIDACION_v31.md](VALIDACION_v31.md))

- **🌐 Cobertura universal**: el barrido recorre ahora **todas** las
  competiciones (11 de fútbol + MLB + NBA + tenis ATP) instanciando cada
  motor. Barrido real: 7 picks en 3 deportes simultáneos.
- **🎯 Doble capa**: **Capa 1** (cuota real + EV + stake Kelly) y **Capa 2**
  (alta confianza sin cuota en vivo → cuota mínima sugerida, sin stake).
- **🎾 Cuotas de tenis vía Betexplorer** con fuzzy matching de nombres
  (9/10 emparejados). Los no enlazados se reportan, nunca se descartan en
  silencio. *(Ojo: las URLs `matches-today` no existen — la ruta real es
  `/next/tennis/`; verificado.)*
- **🧹 Sin deprecaciones**: 34 `use_container_width` → `width`.
- **❌ Decaimiento inter-temporada descartado** con evidencia (peor incluso
  al inicio de temporada, que era la hipótesis).
- Bugs corregidos: serialización Arrow del panel de rendimiento y tarjetas
  defensivas para picks sin cuota.

## Novedades v30 — Tres deportes nuevos, CDI y fix crítico (ver [VALIDACION_v30.md](VALIDACION_v30.md))

- **🔧 Fix crítico de exportación**: el `AttributeError` al exportar las
  Apuestas del Día está resuelto de raíz y **blindado** (try/except +
  firma opcional) — nunca vuelve a romper la página.
- **🏀 NBA — motor nuevo** (nba_api, 6.1k juegos): OFF/DEF rating, pace,
  back-to-back + **CDI**; 65.4 % ≈ ELO, modo analítico hasta octubre.
- **🎾 Tenis ATP — motor nuevo** (Kaggle, 68k partidos con superficie y
  cuotas): **ELO por superficie**, 64.9 % vs ranking 63.3 % (+1.6 pp). El
  mercado (68.3 %) es más afilado → modo analítico honesto.
- **🧬 CDI (Índice de Desincronización Circadiana)**: husos cruzados por el
  visitante. **Adoptado en NBA** (ll 0.644→0.629) y **descartado en MLB**
  con evidencia — la señal circadiana existe en baloncesto, no en béisbol.
- **⚾ MLB** consolidado (motor v29 intacto); umpire y live-API diferidos.

## Novedades v29 — Ecosistema multi-deporte (ver [VALIDACION_v29.md](VALIDACION_v29.md))

- **⚾ MLB (béisbol) — motor nuevo validado**: Retrosheet (11.9k juegos
  2021-25, con abridores) + ensemble XGB+LGBM+RF calibrado. Walk-forward
  **55.0 % vs ELO 54.2 %** (supera en ambas ventanas). Cuotas en vivo de
  The Odds API (`baseball_mlb`) y Apuestas del Día MLB propias.
- **🏗️ Arquitectura DRY**: `engines/BaseSportsEngine` (clase base abstracta)
  para deportes nuevos; el fútbol queda intacto y aislado (no regresión).
- **🔎 NBA y tenis diferidos con evidencia**: basketball-reference bloqueado
  (Cloudflare) + NBA fuera de temporada; el repo de tenis de Sackmann da 404
  y The Odds API no tiene mercado de tenis en la capa gratuita — sin fuente
  viable no hay motor validable ni accionable (se reevalúan en v30).
- **📋 Exportar Apuestas del Día** (TXT/CSV) y **cobertura Liga MX
  corregida** (fuzzy nombre→liga; el barrido descartaba en silencio los
  partidos que no mapeaban exacto).

## Novedades v28 — Dos carriles y traductor cognitivo (ver [VALIDACION_v28.md](VALIDACION_v28.md))

- **⏳ Auto-cuotas nativas**: la app se actualiza sola cada 6 h
  (`st.cache_data`, sin subprocesos) con presupuesto real de The Odds API
  (~16 req/día; salta si quedan <50 créditos, con aviso).
- **📈 Acelerador RLM**: snapshots tier-1 (5 ligas, hasta 3/día) alimentando
  `odds_historico.db` — el Shadow con RLM para Bundesliga/Eredivisie queda
  calendarizado a +60 días de acumulación.
- **⚖️ Índice VACA** en el arbitraje cruzado (EV/volatilidad, escala
  adaptada y documentada): solo oportunidades estables (ν>1).
- **⭐ EVC Platino**: triple validación (EVC ∧ arbitraje ν>1 ∧ sin
  divergencia) con stake ×1.5 pre-cap en el Kelly simultáneo.
- **❌ Weibull Over 2.5 descartado con evidencia** (Brier 0.268 vs 0.250 de
  la matriz): para totales, el conteo Poisson gana; el Weibull se queda
  donde demostró valor (BTTS).
- **🧠 Traductor Quant**: el modo Principiante traduce toda la jerga
  (glosario + tooltips deterministas, sin depender de ningún LLM).
- **🧪 Carril B** (rama `experimento/bottom-up`, sin fusionar): PFI por
  ratings FotMob (787 ratings acumulados) + índice de cohesión Jaccard;
  el VORP-PFI espera cobertura de datos (brecha documentada).

## Novedades v27 — Precisión estructural y riesgo quant (ver [VALIDACION_v27.md](VALIDACION_v27.md))

- **⏱️ BTTS oficial por supervivencia**: el Weibull AFT venció también al
  baseline de matriz con choque común (Brier 0.236 vs 0.251, 6/6 ventanas)
  — transición completada en la plantilla del Mundial; 1X2 intacto.
- **❌ Dixon-Coles descartado con evidencia**: el ρ óptimo en train sale
  POSITIVO (sobreajuste) y no mejora el log-loss del marcador en validación.
- **👤 Shadow 2.0**: castigo narrativo (ELO_VEL × entropía) adoptado en
  **LaLiga (+5.1→+7.3 % ROI)** y **Ligue 1 (−9.3→−0.2 %)**; la MLS conserva
  su variante v1 (+2.6 %) porque el CN la empeoraba — feature por liga.
  RLM documentado como forward-only (falta histórico de snapshots).
- **💎 EVC 2.0**: doble validación (élite ∧ Shadow conforme) con descarte
  por divergencia crítica y stake del **Kelly simultáneo ⅛ + cap 20 %**
  (drawdown máximo 24 %→13 % en Montecarlo comparativo).
- **💹 Arbitraje cruzado** ([cross_arbitrage.py](cross_arbitrage.py)):
  valora double chance / DNB / totales alternativos (.5) con la matriz
  exacta vs cuotas por evento (los SGP pre-empaquetados no existen en la
  capa gratuita — verificado). Con corrección de push en líneas enteras.
- **🕵️ Abogado del diablo** en el comentario del analista cuando el modelo
  y el Shadow divergen (determinista, con o sin Ollama).

## Novedades v26 — Arquitectura de tercera generación (ver [VALIDACION_v26.md](VALIDACION_v26.md))

- **🧮 Features ortogonales adoptadas en 6 de 10 ligas** tras walk-forward
  ([features_v26.py](features_v26.py)): derivadas del ELO (Serie A +0.5,
  Bundesliga +0.4, Eredivisie +1.2 pp), urgencia asimétrica (LaLiga +1.0,
  **Champions +1.7 pp**) y entropía/volatilidad (MLS +0.65 pp). Con ello
  **Serie A alcanza al mercado (57.1 % vs 57.1) y Bundesliga lo iguala a
  modelo puro (55.0 vs 55.0)**.
- **👤 Shadow Booster** ([shadow_booster.py](shadow_booster.py)): XGB sobre
  el residuo del cierre (Pinnacle) con OOF leak-free. **El mercado resultó
  eficiente en 7/9 ligas (documentado); ADOPTADO en MLS** (ROI +2.6 % vs
  −7.8 % del base, 747 apuestas): señales ⚡ en Apuestas del Día.
- **⏱️ Supervivencia BTTS** ([supervivencia_btts.py](supervivencia_btts.py)):
  Weibull AFT censurado en numpy puro (lifelines rechazado: rompía el pin de
  pandas). Brier 0.236 vs 0.252 del baseline en 6/6 ventanas — segunda
  opinión visible en la vista del Mundial.
- **💎 Apuestas del Día + 📈 Montecarlo** ([alpha_finder.py](alpha_finder.py),
  [montecarlo_sim.py](montecarlo_sim.py)): barrido multi-liga con filtros de
  élite (prob >70 %, EV >+3 %, cuota >1.50) y simulador de bankroll con
  percentiles y probabilidad de ruina.
- **🔑 The Odds API activa**: 337 cuotas/día agrupadas por liga + BTTS por
  evento; `odds_historico.db` acumulando CLV; fuera de temporada europea la
  API es la fuente viva de Liga MX/MLS (MESM y blending operan hoy).
- **🎯 Calibración verificada**: ECE local 0.0138 sobre 7,364 OOF — sin
  sesgo de localía; VENTAJA_LOCALIA intacta.
- **CLV Pinnacle**: `roi_sim` reporta ROI con cierre Pinnacle junto a B365.

## Novedades v25 — Parlays reales, EV completo y CLV (ver [VALIDACION_v25.md](VALIDACION_v25.md))

- **🎲 Correlación SGP empírica** ([sgp_correlation.py](sgp_correlation.py)):
  el haircut fijo 0.95 se reemplaza por factores por PAREJA de mercados
  (cópula gaussiana simplificada, φ de 10,514 partidos). Validado FUERA de
  muestra: el error de la probabilidad conjunta cae de 0.049 a 0.0034
  (−93 %). Truncado a f ≤ 1 para no fabricar EV+ ilusorio.
- **📈 CLV** ([odds_api.py](odds_api.py)): The Odds API agrupada por liga
  (h2h + O/U 2.5 + BTTS) + almacén SQLite `odds_historico.db` con marca de
  tiempo — también captura las fuentes gratuitas, así que el CLV acumula
  desde hoy sin clave. Sección EV ampliada: 1X2, O/U 2.5, BTTS y AH ±0.5,
  con aviso de frescura (>6 h).
- **⚖️ Blending 70/30 ADOPTADO en LaLiga y Ligue 1** (walk-forward:
  53.33→54.09 y 51.65→52.17 con log-loss mejorando en ambas).
- **🧪 VORP experimental** ([alineacion_vorp.py](alineacion_vorp.py)):
  ajuste de λ por alineación confirmada (ESPN) con fallback ESTRICTO
  (aborta si <10 titulares parseados con fuzzy >0.85). El 1X2 no se toca.
  Evaluación en 2026-27 con vorp_log.json.
- **🇺🇸 MLS clima extremo: DESCARTADO con evidencia** — backfill Open-Meteo
  completo (1,801 partidos-día) y walk-forward: la feature resta 0.7 pp.
  Documentado; la caché queda acumulando.
- **🎯 SmartParlayBuilder**: lista blanca dinámica (solo mercados con cuota
  real) + control de categorías por el usuario.
- **🆚 Comparador rápido** de dos partidos en todas las competiciones.
- Champions IMT reintentado: sin partidos nuevos, sigue fuera por 0.003 de
  log-loss — se reintenta cuando arranque la 2026-27.

## Novedades v24 — FotMob, MLS y el Índice de Momentum Táctico (ver [VALIDACION_v24.md](VALIDACION_v24.md))

- **📈 Índice de Momentum Táctico (IMT)** ([momentum_tactico.py](momentum_tactico.py)):
  IMT = α·M + β·ΔxG + γ·F + δ·P — momentum exponencial de resultados,
  tendencia de xG, fatiga por congestión y subidón/bajón tras resultados
  extremos, en pase cronológico SIN fuga. A/B de tres variantes en
  walk-forward por liga: **adoptado en 5 de 10 ligas** (Liga MX +0.4 pp,
  Eredivisie +0.6, Primeira +0.6, LaLiga ll −0.042, Bundesliga +0.3);
  descartado con evidencia en Premier/Serie A/Ligue 1/MLS/Champions.
- **🏆 Liga MX cruza el objetivo: 55.4 % vs mercado 53.5 %** (IMT compuesto
  + MESM revalidado). Primeira también bate al mercado (56.2 % vs 56.1 %).
- **🇺🇸 MLS operativa** (fuente estable USA.csv de football-data con cuotas
  de cierre, 6,000+ partidos): 47.2 % de modelo puro y **50.0 % con MESM**
  (mercado 50.1) — empata al mercado desde el día uno.
- **🔎 FotMob desbloqueado** ([fotmob_scraper.py](fotmob_scraper.py)): su API
  está blindada (header firmado x-mas), pero el JSON `__NEXT_DATA__` de cada
  página expone xG real, remates por JUGADOR con xG por tiro, defensivas
  (entradas/intercepciones/despejes), ratings y clima. Caché incremental
  commiteable + paso en el pipeline; las features llegarán cuando la
  cobertura permita validarlas (protocolo clima v23).
- **❌ Soccer24 inviable, documentado** ([soccer24_scraper.py](soccer24_scraper.py)):
  el endpoint `/api/matches/{id}/statistics` del plan NO existe (404); sus
  feeds reales exigen firma `x-fsign` generada en cliente. FotMob cubre lo
  que se esperaba de él.
- **🧪 Estrategia E (IMT dentro del meta MESM): descartada en TODAS las
  ligas** — donde el momentum es señal, ya entró por el modelo base.

## Novedades v23 — Anulación táctica, meta-ensemble de mercado y móvil (ver [VALIDACION_v23.md](VALIDACION_v23.md))

- **⚡ Modelo de Anulación Táctica (MAT)** ([anulacion_tactica.py](anulacion_tactica.py)):
  predice el *apagón ofensivo* (equipo fuerte que acaba en 0 goles) con
  presión del rival, fatiga, contexto y clima; su **factor de supresión
  táctica** τ = log(P_MAT(0)/e^(−λ)) corrige la tasa de goles (λ' con w=0.5)
  y se propaga a los goleadores estrella. Validado walk-forward: Brier de
  P(0) **0.193 vs 0.212** del baseline Poisson (−8.7 %), NLL de goles
  1.61→1.50. El 1X2 queda intacto por construcción. Insight "⚡ Alerta de
  anulación táctica" cuando P(0) ≥ 45 %.
- **🧠 Meta-Ensemble de Superación de Mercado (MESM)**
  ([meta_ensemble.py](meta_ensemble.py)): stacking modelo+cuotas con pérdida
  asimétrica (castiga fallar donde el mercado acierta). Adoptado tras
  validación contra los modelos de producción en **4 ligas** — y con él la
  **Liga MX bate al mercado por primera vez (54.9 % vs 53.5 %)**; Serie A
  56.6 %, Primeira 56.1 %, Eredivisie 53.7 %. Descartado con evidencia en
  Premier/LaLiga/Bundesliga/Ligue 1. Solo actúa con cuotas vigentes del
  partido. Ablación incluida: el grueso es el stacking; la asimetría suma
  ~+0.5 pp.
- **🌤️ Clima** ([clima.py](clima.py)): Open-Meteo (gratis, sin clave) con
  caché y backfill incremental en el pipeline. Con la cobertura actual
  (14 %) el clima aún no aporta señal — dicho sin maquillaje.
- **📱 Móvil**: el selector de competición ahora está arriba del área
  principal (la barra lateral llega colapsada en el teléfono).

## Novedades v22 — FBref, Champions al día y asistente IA local (ver [VALIDACION_v22.md](VALIDACION_v22.md))

- **Champions con forma ACTUALIZADA**: FBref aporta los resultados que el
  plan Free de API-Football bloquea (2025-26 completa + fases previas
  2026-27). Fusión con mapeo de nombres aprendido + 25 alias verificados
  ([fbref_scraper_v3.py](fbref_scraper_v3.py), caché sembrada con navegador
  porque cloudscraper NO supera el 403 — documentado). Profundidad de
  historia validada en walk-forward de 3 variantes: desde 2020 (mejor
  log-loss, regla de oro superada). 1,174 partidos al día de hoy.
- **Honestidad radical sobre FBref**: sus calendarios YA NO publican xG —
  el reentrenamiento de Liga MX/Eredivisie/Primeira con "xG masivo" del
  plan v22 es imposible hoy y así se documenta. Sin cambios en esas ligas.
- **🎙️ Comentario del analista con IA local**
  ([asistente_comentarios.py](asistente_comentarios.py)): comentario natural
  inline en cada partido, compuesto desde las cifras reales del modelo.
  Con Ollama corriendo (checkbox en la barra lateral) un SLM gratuito
  (Phi-3/Llama 3.2) lo reescribe — marcado como tal. Nunca inventa cifras.
- **Panel ampliado**: barras Modelo vs ELO vs Mercado por liga + evolución
  de la precisión por ventanas walk-forward de 6 meses
  ([run_wf_panel_v22.py](run_wf_panel_v22.py)), con las ventanas malas a la
  vista — la variación entre ventanas es la incertidumbre real.

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
