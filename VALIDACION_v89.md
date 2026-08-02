# VALIDACION v89 — El crash de snapshots, la semana completa y la gran limpieza

Fecha: 2026-08-02 · Suites: test_catalogo_y_cuotas ✅ · test_simetria ✅ ·
test_match_parlay ✅ · smoke_botones ✅ · test_concurrencia ✅ (TODO OK las 5)

## 1. Crash de producción: `no such table: snapshots` (ADOPTADO)

**Síntoma.** La página de Apuestas del Día moría con `DatabaseError … no such
table: snapshots` al llegar al expander «Valor en Vivo».

**Causa raíz.** `valor_en_vivo._snapshots()` leía la tabla `snapshots` de la
v43, cuyo ÚNICO escritor era el acelerador RLM de The Odds API — retirado en
la v88. En local la tabla sobrevivía con 726 filas viejas (última captura
2026-07-31); en Streamlit Cloud el `odds_historico.db` es efímero y se crea
con el esquema de `odds_store` (solo `historical_odds`), así que el
`os.path.exists()` pasaba y el `SELECT` reventaba. No era un fallo de datos:
era un lector apuntando a una tabla muerta.

**Arreglo (de raíz, no try/except).** Los 3 lectores de la tabla muerta se
migraron a la fuente VIVA, `historical_odds` fase='snapshot' (las fotos de
`daily_snapshots.py`, persistidas en `odds_snapshots.csv` con 2.322 fotos
commiteadas):

- `valor_en_vivo.py` — reescrito. En Cloud, si no hay fotos, rehidrata desde
  el CSV commiteado (sin red). Verificado simulando Cloud (renombrando el
  .db): la vista carga, rehidrata y muestra 88 partidos. Bonus estructural:
  la tabla viva trae `league_key` y nombres del catálogo, así que desaparecen
  el parseo de `match_id` y el mapeo fuzzy que necesitaba la versión vieja.
- `clv_tracker.clv_reciente()` — migrado (n=1.482 pares entrada/cierre con la
  fuente viva, comparando SIEMPRE dentro de la misma casa).
- `data_health._ultima_captura()` — migrado a `MAX(ingested_at)` de las fotos.

## 2. «Valor en Vivo» mostraba EV fantasma (ADOPTADO)

Con el crash arreglado, la vista mostraba EV de **+93,9 %** (Newells a 4.10) —
regla de oro nº 7: demasiado bueno. Era el patrón que la v87 ya midió: EV
calculado con la probabilidad CRUDA del modelo contra el mercado, y cuando el
modelo discrepa fuerte del mercado acierta el **33,6 %** (encogido: 55,5 %).
Ahora la probabilidad se encoge hacia el mercado **de la propia foto**
(Pinnacle si está, devig proporcional) con el w por liga ya validado de
`calibracion_mercado`. Los EV pasan a +8/+16 % — line shopping real, no
desacuerdo. De paso: la vista llamaba `predecir()` con anclaje por red,
violando su propio spec de «nunca hace HTTP» — ahora `anclar=False` y ancla
local.

## 3. Cobertura: de 25 partidos a la semana completa (ADOPTADO)

**Pedidos del usuario:** partidos del día de consulta con cuota y EV
automáticos; si un partido tiene varias apuestas buenas, mostrarlas todas; la
selección de ligas/partidos de toda la semana.

**Causas medidas de la cobertura pobre (2026-08-02):**

| Causa | Efecto |
|---|---|
| `fixtures_multi()` sin `dias` → default **3** (DIAS_SEMANA=7 existía desde v71 pero no se usaba aquí) | el barrido nunca veía el fin de semana |
| `_dentro_de_la_ventana` (24 h, v88) filtraba ANTES de evaluar | 44/56 ligas «sin partidos», 25/302 fixtures evaluados |
| `candidatos[:15]` | apuestas con EV positivo tiradas |

La semana real tenía **302 fixtures en 32/55 ligas, 235 (78 %) ya con cuota**
— la jornada grande es el sábado (118+88).

**Diseño v89:** se evalúa la semana completa; la ventana de 24 h pasa de
filtro a **etiqueta `es_hoy`**. La UI agrupa por día (Hoy → Mañana → fecha) y
por PARTIDO (todas las apuestas con valor de un partido juntas). Selección del
Día: hasta 3 mercados por partido de los 8 mejores partidos. Candidatos
15→40. Telegram y Máxima Confianza ordenan HOY primero. Resultado medido:
**274 partidos evaluados en 32 ligas** (antes 25 en 12), las 24 ligas «sin
partidos» restantes son parones reales (Premier, LaLiga… pretemporada), y
apareció **1 pick de Capa 1** que el filtro de 24 h estaba dejando fuera.

**Rendimiento del barrido semanal (medido):**

- Predicción unitaria en caliente: 0,19 s/partido (perfilada: 85 % es
  `VotingClassifier.predict_proba`).
- Barrido completo: **304 s** con el bucle serial → **102 s** con el prefetch
  de cuotas por evento de todas las ligas en paralelo (la red queda escondida
  detrás de la CPU). Las cuotas ricas solo se piden para fixtures apostables
  (cuota abierta o ≤72 h): a 5-7 días el endpoint casi nunca trae nada.
- Memoria: los motores que carga el pase de fixtures se LIBERAN al terminar su
  liga (con la semana entran ~32 ligas; retener 32 motores era el patrón de
  1,3 GB de la v86). Pico Python medido: 300 MB.

## 4. Dos bombas de relojería del historial, desactivadas (ADOPTADO)

- **Expander «Enviar estas apuestas a Telegram» duplicado**: llamaba a
  `construir_mensaje()` SIN el barrido — exactamente el bug que tumbaba la app
  en v88 (2º barrido = 2.172 MB). La v88 arregló el botón de arriba y este
  duplicado quedó con el código viejo. Eliminado (el de arriba ya lo hace bien).
- **Botón «Actualizar datos ahora» (vista Mundial)**: subprocess de hasta 30
  minutos dentro del proceso de Streamlit + `st.cache_data.clear()` y
  `st.cache_resource.clear()` GLOBALES — el patrón exacto de las caídas de la
  v86, sobrevivió a aquella limpieza. Eliminado; la actualización vive en la
  tarea diaria (bat local / workflow CI), donde siempre debió estar.

## 5. Secciones muertas retiradas (ADOPTADO)

- **Polymarket** (sección + `market_intelligence.py` + paso de
  `pipeline_total`): consultaba mercados del Mundial 2026, cerrados al
  terminar el torneo — bucle perpetuo de «sin mercados abiertos» con botón
  manual. El workflow de CI usa `--update-only`, que nunca pasaba por ahí.
- **Pestaña MLB «Buscar picks (usa 1 crédito de API)»**: la API citada se
  retiró en v88 y el motor ya usa Pinnacle/Bovada — ahora automática (cacheada
  30 min) y con la fuente real en el texto.
- **`data_health`** giraba alrededor de `ODDS_API_KEY` y `odds_actuales.json`
  (retirados): contar un fichero que nada escribe podía inflar el número con
  cuotas rancias y diagnosticar «falta la clave» de una API que ya no existe.
  Reescrito para medir lo real: cuotas_multi + frescura de las fotos.
- **Combinadas del Día**: el botón «Generar» se retira — se calculan solas
  (cacheadas 30 min), con los partidos de HOY primero.
- **Limpieza del repo**: 141 ficheros scratch `_vNN_*` commiteados + 34
  módulos muertos o one-off retirados (177 archivos): los 26 `run_*` de
  experimentos v16-v69 (sus números viven en `resultados_*.json` y en los
  VALIDACION_vXX.md, que se conservan ÍNTEGROS), `app_legacy_v1`, `smoke_v46`
  (superseded por `smoke_botones`), `tda_preprocessing` (era del pipeline
  giotto-tda retirado en v17), `soccer24_scraper` (fuente verificada
  inexistente), `player_ratings` (fuente bloqueada, NO ADOPTADO documentado),
  `understat_scraper` (0 consumidores; FotMob lo superó en v24),
  `market_intelligence`. Se conservan los 10 JSON `_v*` que son insumo/salida
  de código vivo (p. ej. `_v71_calibracion_vs_pinnacle.json`, que lee
  `calibracion_mercado.generar`). Verificado: 0 importadores de todo lo
  retirado.

## 6. Nombres sin mapear (ADOPTADO)

- Alias nuevos: AGF→Aarhus, F.C. København→FC Copenhagen, Sønderjyske
  Fodbold→Sonderjyske, Heart of Midlothian→Hearts (verificados contra el
  catálogo de su liga).
- `nombres_sin_mapear.json` acumulaba fallos PARA SIEMPRE: 38 selecciones
  listadas seguían ahí aunque mapean desde que la v66 amplió el catálogo a 200
  (verificado hoy: todas resuelven). Ahora cada entrada guarda cuándo se vio y
  las que llevan >30 días sin reaparecer se retiran solas.

## 7. Investigado y CERRADO SIN CAMBIO (con evidencia)

- **«[bovada] mlb: sin respuesta»**: endpoint verificado VIVO (HTTP 200, 9
  eventos MLB). Fue un fallo transitorio de red en Cloud; la cadena degrada a
  Pinnacle como está diseñado. No se toca.
- **Stenhousemuir, Milford FC, Kruger United sin mapear**: ascendidos sin
  histórico en el catálogo de su liga — no hay a qué mapearlos; correcto que
  queden fuera y así lo dice la UI.
- **`fbref_league_scraper` se conserva**: bloqueado (403) desde esta red pero
  es la infraestructura documentada para redes sin bloqueo/proxies.
- **`tenis_saque` se conserva**: `engines/tennis_engine.py` lee
  `saque_{circuito}.csv.gz`, que este módulo genera.
- **`cuotas_manual` se conserva**: es la herramienta de pegar cuotas propias
  en la vista de partido — no forma parte del flujo automático de Apuestas del
  Día, que ya no tiene pasos manuales.
- **`registrar` de rendimiento_real con barrido semanal**: verificado
  idempotente por (fecha del PARTIDO, partido, apuesta) — un pick del sábado
  visto 6 días seguidos se registra UNA vez.

## 8. Qué queda abierto

- Validar en producción que el barrido semanal en frío queda en ~2 min (aquí
  102 s con caché parcial; el peor caso local fue 304 s pre-optimización).
- Monitorización producción-vs-backtest de valor_vs_sharp (WTA, MLB) — sigue
  pendiente de la v88.
- Histórico de cuotas sudamericano (BetExplorer, v76) para dar peso medido de
  calibración a las ligas que juegan en verano — sigue pendiente de la v79.
