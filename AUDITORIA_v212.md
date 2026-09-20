# AUDITORÍA v212 — inventario del repositorio

Generado automáticamente por `auditar_repo.py` el 2026-09-19 19:10. **Se vuelve a correr y se actualiza solo.**

- Módulos Python: **378**
- Líneas totales: **145.040**

## 1.0 Reparto por estado

| estado | módulos | qué significa |
|---|---|---|
| sondeo_historico | 156 | sondeo `_vNNN_*`: cuaderno de laboratorio |
| activo_medido | 132 | lo importa producción y lleva su medición encima |
| script_de_entrada | 25 | se ejecuta solo (build, train, validación) |
| activo_sin_medir | 24 | lo importa producción y no declara medición |
| sin_importadores | 22 | **nadie lo importa** — pregunta abierta |
| refutado_o_apagado | 18 | contiene marca de refutado o apagado |
| productor_de_artefacto | 1 |  |

## 1.1 Inventario — módulos de producción

Ordenado por número de módulos que dependen de él. Se listan los que tienen al menos un importador de producción.

| módulo | líneas | usado por | último commit | estado | qué es |
|---|---|---|---|---|---|
| config | 687 | 47 | 2026-09-09 | refutado_o_apagado | Configuración central del pipeline. |
| fixtures_espn | 1608 | 25 | 2026-09-16 | activo_medido | Fixtures ESPN (v49) — PRÓXIMOS partidos por liga, SIN clave y SIN cost |
| cuotas_multi | 2699 | 21 | 2026-09-15 | activo_medido | v71 — Capa de cuotas UNIVERSAL, sin cuota de peticiones. |
| rendimiento_equipos | 1565 | 17 | 2026-09-19 | activo_medido | v152 — CÓMO LLEGA CADA EQUIPO, CON DATOS OBSERVADOS Y NADA MÁS. |
| name_mapper | 372 | 26 | 2026-08-23 | activo_medido | Mapeo centralizado de nombres entre fuentes (v34 §4). |
| league_engine | 3106 | 12 | 2026-09-09 | refutado_o_apagado | Motor multi-liga de clubes (Mejora 5, v12): Liga MX, Premier League, L |
| io_atomico | 136 | 21 | 2026-08-02 | activo_medido | v86 — Escritura atómica de JSON, para archivos que se tocan durante un |
| alpha_finder | 4555 | 9 | 2026-09-19 | refutado_o_apagado | Alpha Finder — panel «Apuestas del Día» (v26, spec §4.2). |
| feature_engineering | 411 | 9 | 2026-07-25 | activo_sin_medir | Feature engineering táctico-topológico. |
| contexto_previo | 251 | 1 | 2026-08-05 | activo_medido | v101 — Contexto del partido ANTERIOR: qué traía cada equipo encima al  |
| modo_modelo | 3179 | 4 | 2026-09-19 | refutado_o_apagado | v152 — MODO MODELO: la pantalla que ordena por probabilidad, no por pr |
| arbitro_partido | 561 | 3 | 2026-09-19 | activo_medido | v160 — EL ÁRBITRO DESIGNADO, Y CUÁNTO MUEVE LAS TARJETAS. |
| remates_jugadores | 464 | 3 | 2026-08-23 | activo_medido | v67 — Remates y remates a puerta REALES por jugador. |
| guardia_barrido | 345 | 3 | 2026-09-19 | activo_medido | v86 — Un solo barrido de alpha_finder a la vez en todo el proceso. |
| horario | 213 | 7 | 2026-08-08 | activo_medido | v106 — LA HORA DEL PARTIDO, EN HORA DE CIUDAD DE MÉXICO. |
| odds_store | 409 | 8 | 2026-09-09 | activo_medido | v75 — Almacén canónico de cuotas históricas (`odds_historico.db`). |
| calibracion_mercado | 350 | 8 | 2026-07-29 | activo_medido | v71 — Corrección de la sobreconfianza del pick contra el mercado sharp |
| remates_jugador | 1080 | 2 | 2026-08-23 | activo_medido | v163 — QUIÉN REMATA: probabilidad por jugador, con la alineación cuand |
| mercado_implicito | 660 | 4 | 2026-08-25 | activo_medido | v165 — LO QUE LA CASA CREE, AL LADO DE LO QUE CREE EL MODELO. |
| leagues_cup | 285 | 3 | 2026-08-04 | activo_sin_medir | v97 — Leagues Cup (MLS vs Liga MX). |
| nfl_datos | 851 | 5 | 2026-09-10 | activo_medido | v131 · NFL — capa de datos. |
| aprendizaje_continuo | 550 | 3 | 2026-08-05 | activo_medido | v101 — Aprendizaje autónomo: el sistema corrige su propia confianza. |
| train_tda_model | 433 | 5 | 2026-07-25 | activo_medido | Entrenamiento v4: ensemble calibrado + topología por equipo + regresor |
| statsbomb_calibration | 133 | 5 | 2026-07-03 | activo_sin_medir | Calibración con StatsBomb Open Data. |
| cuotas_tablon | 1414 | 3 | 2026-08-22 | refutado_o_apagado | v114 — El tablón multi-casa, cruzado con el modelo: mercados con EV RE |
| auditoria_pick | 795 | 5 | 2026-09-18 | refutado_o_apagado | v209 — LA CAPA DE AUDITORÍA: cada pick del día, explicado y con su rie |
| contexto_partido | 598 | 5 | 2026-09-19 | activo_medido | v172 — EL CONTEXTO DEL PARTIDO: H2H, FORMA Y NIVEL. |
| correlated_synthetic_generator | 516 | 6 | 2026-07-25 | activo_medido | Generador sintético de RESPALDO con causalidad realista. |
| riesgo_liga | 445 | 5 | 2026-09-15 | refutado_o_apagado | Índice de riesgo por competición: qué liga hace daño a un parlay y cuá |
| lineas_jugador | 435 | 1 | 2026-08-23 | activo_medido | v164 — LA LÍNEA DE LA CASA PARA LOS REMATES DE CADA JUGADOR. |
| mercados_dia | 420 | 5 | 2026-09-15 | activo_medido | Todos los mercados de todos los partidos de un día, en una sola estruc |
| catalogo_equipos | 367 | 3 | 2026-09-09 | activo_medido | v180 — EL DICCIONARIO EQUIPO -> LIGA LOCAL. Construido con dato, no ad |
| _v101_ab_contexto_futbol | 178 | 1 | 2026-08-05 | sondeo_historico | v101 — ¿El contexto del partido anterior explica el error del modelo d |
| modelo_nfl | 1030 | 3 | 2026-09-10 | activo_medido | v131 · NFL — modelo predictivo de 1X2, hándicap, total y totales de eq |
| tenis_fuentes | 1010 | 3 | 2026-08-04 | activo_medido | v67 — Capa de datos MULTIFUENTE de tenis. |
| stats_espn | 634 | 3 | 2026-08-22 | activo_medido | v162 — LAS ESTADÍSTICAS REALES DE ESPN, PARA TODAS LAS COMPETICIONES. |
| mlb_statsapi | 496 | 4 | 2026-08-04 | activo_medido | v79 — MLB StatsAPI: la fuente que faltaba para la TEMPORADA EN CURSO. |
| fiabilidad_picks | 424 | 4 | 2026-09-19 | activo_medido | v217 — Cuándo fiarse de un verde: qué acierta DE VERDAD cada probabili |
| scraper_contexto | 392 | 4 | 2026-09-18 | activo_medido | v212 — Contexto y noticias, normalizado, multideporte y con el hueco a |
| recalibrate_from_history | 350 | 5 | 2026-08-05 | activo_medido | v75 — Recalibración del encogimiento hacia el mercado (`calibracion_me |
| predicciones_dia | 340 | 4 | 2026-09-15 | activo_medido | v153 — LAS PREDICCIONES DEL DÍA, CALCULADAS UNA VEZ AL DÍA Y NO EN CAD |
| goleadores | 334 | 4 | 2026-08-23 | activo_medido | Goleadores (v57) — mercados de jugador para fútbol, en TODAS las ligas |
| rendimiento_real | 259 | 4 | 2026-08-02 | activo_medido | Rendimiento REAL de las Apuestas del Día (v32 §6) — persistencia SQLit |
| api_football_manager | 256 | 5 | 2026-07-14 | activo_medido | Gateway centralizado hacia API-Football (v21) — plan Free: 100 request |
| modelos_portables | 251 | 3 | 2026-07-31 | activo_medido | v87 — Cargar modelos de XGBoost serializados en otra plataforma. |
| filtro_contexto | 229 | 4 | 2026-09-15 | refutado_o_apagado | Efecto rebote por entrenador nuevo. LA REGLA ESTÁ ESCRITA Y NO ESTÁ EN |
| prediction_api | 1403 | 2 | 2026-08-08 | activo_medido | Motor de inferencia + API de predicción (v3, arquitectura híbrida). |
| match_parlay | 1364 | 1 | 2026-08-11 | activo_medido | Asistente de Parlay POR PARTIDO (v15) — agnóstico de competición. |
| beisbol_pitchers | 949 | 2 | 2026-08-12 | activo_medido | v106 — BÉISBOL: ABRIDOR, ESTADIO Y PONCHES, TODO AUTOMÁTICO. |
| pronosticos_guardados | 864 | 3 | 2026-09-19 | activo_medido | v176 — LO QUE LA APLICACIÓN DIJO ANTES DEL PITIDO, GUARDADO Y LIQUIDAD |
| cuotas_mx | 810 | 3 | 2026-09-15 | activo_medido | v192 — CINCO CASAS MEXICANAS POR UNA PUERTA ABIERTA. |
| panel_equipos | 791 | 3 | 2026-08-11 | activo_medido | v107 — EL PANEL DE EQUIPOS: H2H, clasificación y forma, en un solo sit |
| config_ligas_espn | 557 | 2 | 2026-09-09 | activo_medido | v68 — Competiciones de fútbol añadidas al catálogo. |
| mercado_estabilidad | 525 | 2 | 2026-08-24 | activo_medido | v168 — EL MERCADO REY DE CADA COMPETICIÓN. |
| sgp_correlation | 457 | 3 | 2026-07-24 | activo_medido | Correlación empírica para Same Game Parlays — SGP (v25, spec §1.1). |
| veredicto_pick | 432 | 3 | 2026-09-19 | activo_medido | v218 — METER o NO METER: un veredicto visual, sin párrafos que leer. |
| cordura_probabilidad | 388 | 2 | 2026-08-26 | activo_medido | v165 — CONTROL DE CORDURA: NINGÚN PORCENTAJE SIN ALGO CONTRA LO QUE ME |
| edge_engine | 341 | 4 | 2026-07-23 | activo_medido | Motor de Rentabilidad (v38) — selección de apuestas VALIDADA con datos |
| handicap | 321 | 3 | 2026-08-08 | activo_sin_medir | v106 — HÁNDICAP ASIÁTICO: el mercado que fallaba, y por qué. |
| contexto_ampliado | 293 | 3 | 2026-09-15 | activo_medido | Todo el contexto de un partido en un sitio, diciendo qué está medido y |
| clima | 264 | 4 | 2026-07-15 | activo_sin_medir | Clima histórico y futuro con Open-Meteo (v23) — gratuito, sin clave. |
| cuotas_manual | 227 | 3 | 2026-08-11 | activo_medido | Cuotas manuales (v63) — el usuario PEGA las cuotas de su casa y la app |
| distributions | 227 | 4 | 2026-07-27 | activo_medido | Distribuciones probabilísticas de mercados cuantitativos (M2, v13). |
| modelos_remotos | 200 | 3 | 2026-08-21 | activo_medido | v148 — Los pesos entrenados dejan de vivir en la historia de git. |
| sonadora_motor | 2152 | 2 | 2026-09-16 | activo_medido | Motor de la Soñadora: patas reales de Playdoit y permutaciones para co |
| bot_telegram | 659 | 2 | 2026-09-15 | activo_medido | Bot de Telegram — resumen diario de las Apuestas del Día (v33 §4). |
| clasificador | 607 | 2 | 2026-08-15 | refutado_o_apagado | v125 — El clasificador: semáforo, tres secciones y material para parla |
| supervivencia_btts | 560 | 3 | 2026-07-27 | activo_medido | Supervivencia del primer gol RECIBIDO → BTTS (v26, spec §2). |
| consenso_api | 435 | 2 | 2026-08-12 | activo_medido | v127 — The Odds API dentro del presupuesto gratuito: 23 casas por 0 €. |
| calibrador_bandas | 431 | 2 | 2026-09-18 | activo_medido | v215 — Calibración por banda de cuota: arreglar el mapeo sin tocar el  |

_Se muestran 70 de 170._

## 1.2 Inventario de reglas de negocio

Una regla es una decisión con evidencia detrás. Esta tabla no sale del AST: se mantiene a mano en `auditar_repo.REGLAS` porque el documento se regenera entero.

| regla | módulo | versión | evidencia medida | estado |
|---|---|---|---|---|
| Ventaja de precio al lado local (Sección 1) | `clasificador.canal_del_pick` | v128 | p5 de bootstrap +1,73 % en el tramo de juicio; ROI +8,22 % entre 5 % y 100 % de ventaja contra −11,48 % entre 0 y 5 % | VIGENTE — medida y positiva |
| EV del modelo como criterio de selección | `alpha_finder / valor_apuesta` | v128 | −4,66 % a −6,52 % de ROI sobre 37.158 apuestas; anti-indicador del cierre | REFUTADA — se publica, no asciende |
| ECE por competición como índice de riesgo | `riesgo_liga` | v202 | Pearson −0,460 y Spearman −0,563 contra ROI real; 5,19 puntos entre mejor y peor cuartil (14.647 patas) | VIGENTE — medida |
| IVL (volatilidad de goles) por liga | `riesgo_liga` | v202 | Pearson −0,031 contra ROI. Rango 0,54-0,72 en 69 ligas: ningún umbral del encargo original era alcanzable | REFUTADA — se publica como descriptor, no bloquea |
| Brier por competición → «🔴 Alta incertidumbre» | `alpha_finder.etiqueta_fiabilidad` | v32 | Brier real de los picks publicados (mínimo 30 por liga); corte en 0,22 | VIGENTE — medida |
| Aclimatación por desnivel sobre el 1X2 | `contexto_ampliado` | v205 | fuera de muestra: log-loss −1,54 %, ECE −34 % en 376 partidos con subida ≥ 1.000 m | VIGENTE — la única señal de contexto que corrige un número |
| Altura bruta de la sede | `contexto_ampliado` | v205 | +0,10 % en 1X2 y +0,49 % en goles: ruido. Se cayó al incluir la Liga MX | REFUTADA — se publica, no corrige |
| Rebote por entrenador nuevo (7 días, cuota < 1,85, −0,15) | `filtro_contexto` | v202, enchufada en v209 | NINGUNA. El efecto nunca se ha medido; la fuente (Wikidata) sí funciona desde la v209 | ACTIVA SIN MEDIR — avisa, no corrige probabilidad |
| Tope de 2 patas por partido en combinada | `auditoria_pick.patas_compatibles` | v209 | ninguna; es una regla de sentido común sobre correlación | ACTIVA SIN MEDIR |
| Divergencia extrema > 15 pp → −20 % de confianza | `auditoria_pick.divergencia` | v209 | ninguna | ACTIVA SIN MEDIR — sólo recorta confianza |
| Cuota inflada ratio > 1,30 → −30 % de confianza | `auditoria_pick.cuota_inflada` | v209 | ninguna directa; emparentada con `EV_SOSPECHOSO`, que sí está medido | ACTIVA SIN MEDIR |
| Racha negativa ≥ 5 sin ganar | `auditoria_pick.racha_negativa` | v209 | ninguna | ACTIVA SIN MEDIR — sólo avisa |
| Kelly fraccional ¼ con tope del 5 % | `bankroll_manager` | v19 | teoría estándar; el ¼ es práctica de oficio, no una medición de este proyecto | VIGENTE — informativa |
| Excepción del tenis: prob ≥ 90 % con precio → verde | `clasificador.semaforo` | v128 | p5 +0,18 %: aprueba raspando | VIGENTE — medida, al límite |
| Ventaja > 30 % es error de datos, no ventaja | `clasificador.semaforo` | v128 | entre dos casas reales es imposible; detecta partidos desemparejados | VIGENTE |
| Modo Seguridad (prob ≥ 60 %, cuota 1,30-1,90, |Δ| ≤ 8 pp) | `modo_seguridad` | v212 | ver `backtesting_v212.md`: mejora Brier, hit rate y ROI en fútbol y MLB, pero el p5 sigue negativo | APAGADA por la puerta de activación |
| Escalada de líneas por 3 de 4 fuentes | `escalada_lineas` | v212 | NO MEDIBLE: dos de las cuatro fuentes no existen en el histórico (xG sintético, contexto no archivado) | APAGADA por no medible |

**17 reglas: 7 vigentes y medidas · 3 refutadas por datos propios · 5 activas sin medir · 2 apagadas por la puerta de activación.**

## 1.3 Banderas rojas

| módulo | líneas | último commit | tipo | qué decidir |
|---|---|---|---|---|
| feature_engineering | 411 | 2026-07-25 | grande_activo_sin_medicion | 9 módulos dependen de él y no lleva medición encima |
| handicap | 321 | 2026-08-08 | grande_activo_sin_medicion | 3 módulos dependen de él y no lleva medición encima |

_2 banderas en total._

## 1.4 Cobertura por deporte

Módulos de producción que mencionan cada deporte. Es una cota SUPERIOR: mencionar no es cubrir.

| deporte | módulos | algunos |
|---|---|---|
| futbol | 48 | ajuste_contexto, alpha_finder, altitud, arbitro_partido, archivo_contexto, auditar_repo, autopsia, backtest_v212… |
| nfl | 50 | alpha_finder, arbitros, archivo_contexto, auditar_repo, auditoria_pick, backtest_v212, beisbol_pitchers, build_ledger_handicap… |
| mlb | 59 | alpha_finder, aprendizaje_continuo, auditar_repo, ayuda, backfill_mlb_odds, beisbol_pitchers, bot_telegram, build_ledger_deportes… |
| tenis | 56 | acumular_itf, acumular_tenis, alpha_finder, aprendizaje_continuo, auditar_repo, auditoria_pick, ayuda, betexplorer_scraper… |
| kbo | 29 | alpha_finder, aprendizaje_continuo, auditar_repo, backtest_v212, config, config_ligas_espn, daily_snapshots, dashboard_ui… |
| nba | 34 | alpha_finder, aprendizaje_continuo, auditar_repo, betexplorer_scraper, build_ledger_deportes, calibracion_confianza, calibracion_mercado, cdi… |

## 1.6 Triaje de los modulos sin importadores

La clasificacion automatica sabe quien importa a quien y quien comparte fichero de datos, pero no sabe PARA QUE se escribio un modulo. Esto es la lectura, uno a uno.

### Aparcadas — medidas, no llegaron al liston

| modulo | que es y que se decide |
|---|---|
| elo_global | v105. ELO cross-competicion para las copas, donde el ELO por competicion no converge (68 de 135 equipos de la Conference tienen 8 partidos o menos). Medido en `_v105_ab_elo_global.json`. |
| historico_agrupado | v184, CERRADO en v227. Agrupaba el historico de una copa con el de las ligas de sus equipos para predecir a los que no tienen muestra. Medido dos veces y NO se engancha: en global el logloss empeora (`_v184`), y en los huecos —los partidos que motivaron el modulo— acierta 0,4615 contra 0,5000 del modelo de la copa y ni gana a la base tonta (0,4808). Ver `_v227_agrupado_huecos.json`. |
| indice_forma | v99.1. Indice de Dispersion de Forma y factor de parque de la KBO. Medido en `_v102_ab_idf_*.json`. |
| kbo_preview | v104. Calidad del abridor y bullpen de la KBO desde Naver. Produce `kbo_preview.csv`, que hoy no lee nadie. |
| nba_features | v70 Mejora F. Fatiga, viajes y avanzadas de NBA. El motor ya llevaba descanso y back-to-back; esto añadia densidad de calendario y millas. |
| portfolio_optimizer | v33. Optimizador de Markowitz, marcado EXPERIMENTAL por su propio autor. |
| props_model | v45. Modelo de props de ponches. Lo sustituyo `beisbol_pitchers`, que si esta enchufado. |
| tenis_saque | v69. Estadisticas de saque y resto desde TennisAbstract, que v67 dio por imposible. La fuente FUNCIONA; lo que falta es medir si el ELO de saque mejora algo. |

### Sondeos — la pregunta ya tiene respuesta

| modulo | que es y que se decide |
|---|---|
| backtest_btts | v75. Contesto si el mercado BTTS merecia entrar en la Capa 1. La respuesta quedo en `_v75_btts.json`. |
| sondeo_casas | v126. Barrio las casas de apuestas para ver cuales se pueden integrar. La respuesta gobierna `cuotas_multi` desde entonces. |
| sondeo_odds_api | v127. Contesto si The Odds API cubre las 24 ligas sin historico de cuotas. |

### Generadores e ingesta — se corren cuando hace falta

| modulo | que es y que se decide |
|---|---|
| entrenar_ligas_v68 | v68. Entrena las competiciones nuevas y decide cuales se despliegan. Lo sustituyo el workflow de reentrenamiento diario. |
| generar_ligas_v68 | v68. Genera el catalogo de ligas de futbol. Mismo caso. |
| generar_universo_selecciones | v66. Genera el universo de selecciones del modelo internacional. Se corre al ampliar el catalogo, no en cada barrido. |
| ingesta_cuotas_leagues_cup | v100. Cuotas de cierre historicas de la Leagues Cup desde BetExplorer. Ingesta de una vez. |
| nba_scraper | v30. Game logs de NBA via nba_api. Ingesta. |
| pipeline_mundial | Pipeline diario del Mundial con tres fuentes abiertas. |
| precalcular_goleadores | v147. Precalcula la cache de goleadores EN EL RUNNER y no en el navegador. Es la misma idea que la v220 generalizo: calcular fuera del render. |
| retrosheet_scraper | v29. Game logs historicos de MLB. Ingesta. |

## 1.5 Decisiones abiertas

Lo que necesita una decisión antes de tocar código. Ninguna se ha tomado por cuenta propia en la v212.

**1. `ventaja_ponches` (267 líneas, v132) está escrito y nadie lo importa**

decide la escalera de ponches por VENTAJA DE PRECIO, que es el único criterio con p5 positivo del proyecto. Es el mismo patrón que `filtro_contexto`: escrito, correcto y sin enchufar.

→ _engancharlo a la vista de MLB o retirarlo con test de regresión. NO se ha tocado en la v212: enchufarlo cambia qué picks salen, y eso pide su propia medición._

**2. `historico_agrupado` (144 líneas, v184) está escrito y nadie lo importa**

arregla el 1X2 de equipos de copa que no están en el catálogo de su competición y salen con `prob: None`. Medido en su día: 3 de 12 partidos de Champions.

→ _engancharlo TOCA EL NÚCLEO PREDICTIVO, así que queda fuera de esta tanda por la regla del propio encargo._

**3. `feature_engineering` (411 líneas) y `handicap` (321) son grandes, activos y sin medición declarada**

dos o más módulos de producción dependen de cada uno y ninguno lleva ROI, p5 ni ECE encima.

→ _no es una avería: es deuda de medición. Ordenar por cuánto deciden._

**4. NFL y KBO no tienen ledger fuera de muestra**

sin él, ninguna regla nueva puede activarse ahí: la puerta del §7 exige ROI y p5, y no hay con qué calcularlos. KBO además no tiene NINGUNA cuota histórica.

→ _construir `build_ledger_nfl.py` y conseguir cuotas de KBO, o aceptar que esos deportes se quedan sin reglas nuevas._

**5. El umbral 0,22 del Brier («Alta incertidumbre») no está optimizado**

es una convención heredada de la v32 y hoy gobierna exclusiones de combinada y recortes de stake.

→ _barrer el umbral contra ROI real y fijarlo con dato._
