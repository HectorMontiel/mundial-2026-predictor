# VALIDACIÓN v68 — 40 competiciones nuevas, dependencia entre goles y blindaje del reentrenamiento

**Fecha:** 2026-07-27 · **Entorno:** `.venv` Python 3.12

---

## 0. Resumen ejecutivo

| Qué | Antes (v67) | Después (v68) |
|---|---|---|
| Competiciones en el catálogo | 27 | **67** |
| Competiciones desplegadas (Capa 1 / Apuestas del Día) | 23 | **45** |
| Competiciones que baten al mercado | — | **3 nuevas** (Escocia, J1, Ligue 2) |
| Modelos de liga ilegibles | 22 (sin detectar) | **0**, con verificación automática |
| Matriz conjunta de goles | independencia en clubes | 3 métodos medidos; se documenta el veredicto |

---

## 1. Fase 1 — Diagnóstico: los datos que el spec daba por hechos NO existen

Antes de escribir una línea comprobé la disponibilidad real. Tres de las tres
mejoras del spec estaban apoyadas en datos que no están:

| El spec asume | Realidad medida |
|---|---|
| Caché de FotMob «acumulada desde la v24» | **28 partidos**. Los campos son correctos (`xg_h`, `tiros_h`, `posesion_h`, `ocasiones_claras_h`) pero con 28 partidos no se puede construir una EMA de 5-10 por equipo. |
| `alineaciones_historicas.csv` «desde v19» | **204 filas** ≈ 18 alineaciones ≈ 9 partidos. Imposible calibrar β por walk-forward. |
| `odds_historico.db` con BTTS | Solo `h2h` (2.862) y `totals25` (314), sobre **212 partidos** y **9 días** de historia. **Cero cuotas de BTTS.** |
| `historico_estadisticas_avanzadas.csv` | 82 filas, solo Liga MX. |

Ese diagnóstico es el que reorienta la sesión: se prioriza lo que sí tiene datos
(la ampliación de competiciones) y se documenta con evidencia por qué las otras
dos no se pueden hacer como estaban especificadas.

---

## 2. Ampliación del catálogo de competiciones

### 2.1 Auditoría de fuentes (medida, no supuesta)

| Fuente | Cobertura real | Qué aporta |
|---|---|---|
| **football-data /mmz4281/** | 22 códigos verificados, 5 temporadas cada uno, frescos a mayo 2026 | La MEJOR: remates (HS/AS), remates a puerta, córners, faltas, tarjetas **y** cuotas de cierre de varias casas |
| **football-data /new/** | **16 países reales** | Goles + cuotas de cierre |
| **ESPN** | **220 competiciones** | Resultados sin cuotas ni estadística, pero es la única con Latinoamérica, copas y competiciones continentales |

Dos trampas que costó detectar y conviene dejar escritas:

1. **football-data devuelve HTTP 200 para códigos inexistentes.** Un `HEAD` a
   `/new/CRO.csv` responde 200 y `/new/KOR.csv` devuelve *el mismo fichero* que
   `/new/MEX.csv`. Validar por código de estado daba 60 países falsos; validando
   el CONTENIDO quedan 16. También dejó de servir `/new/` por HTTP plano: hay
   que pedirlo por HTTPS.
2. **El dropdown de ESPN está curado.** 11 competiciones que no aparecen en él
   (Bélgica, Rusia, Indonesia, Chipre, Colombia B…) **sí las sirve** el
   scoreboard. Quedarse en el dropdown habría dejado fuera cobertura real.

### 2.2 Resultado

De las 85 competiciones pedidas:

* **40 entran al catálogo**, cada una desde la fuente de más calidad que la
  sirva: 11 de football-data `/mmz4281/` (con estadística y cuotas), 1 de
  `/new/` y 28 de ESPN.
* **57 se descartan** por falta de volumen y quedan documentadas en
  `config_ligas_espn.SIN_VOLUMEN` con el motivo y el número de partidos.

### 2.3 Entrenamiento y regla de adopción

Se aplicó la regla del proyecto desde v39: **una liga entra en Capa 1 sólo si su
modelo bate a la línea base ELO**. Si no, queda entrenada (sirve en la ficha de
partido) pero fuera del barrido de Apuestas del Día.

**37 de 40 entrenadas · 22 adoptadas · 3 baten también al mercado.**

| Δ vs ELO | Liga | Precisión | ELO | Fuente |
|---|---|---|---|---|
| +0.107 | División Profesional (Bolivia) | 0.5657 | 0.4582 | espn |
| +0.081 | Liga de Expansión MX | 0.4672 | 0.3861 | espn |
| +0.077 | Primera Nacional (ARG) | 0.4527 | 0.3752 | espn |
| +0.067 | Primera División (Uruguay) | 0.4607 | 0.3933 | espn |
| +0.065 | Liga 1 (Perú) | 0.5271 | 0.4621 | espn |
| +0.053 | AFC Champions League | 0.5395 | 0.4868 | espn |
| +0.038 | Copa Libertadores | 0.5048 | 0.4667 | espn |
| +0.035 | South African Premier | 0.4802 | 0.4449 | espn |
| +0.035 | Scottish Championship | 0.4360 | 0.4012 | main |
| +0.034 | 2. Bundesliga | 0.4710 | 0.4369 | main |
| +0.032 | Austrian Bundesliga | 0.4086 | 0.3763 | espn |
| +0.030 | Serie B | 0.4588 | 0.4286 | main |
| +0.030 | USL Championship | 0.4526 | 0.4228 | espn |
| +0.028 | EFL League One | 0.4598 | 0.4318 | main |
| +0.023 | Russian Premier League | 0.5302 | 0.5070 | espn |
| +0.018 | **Scottish Premiership** | 0.5333 | 0.5156 | main | ★ bate al mercado |
| +0.014 | Campeonato Nacional (Chile) | 0.4932 | 0.4795 | espn |
| +0.013 | Categoría Primera A (COL) | 0.4876 | 0.4751 | espn |
| +0.011 | National League | 0.5207 | 0.5094 | main |
| +0.009 | LigaPro Serie A (Ecuador) | 0.4549 | 0.4464 | espn |
| +0.007 | **J1 League (Japón)** | 0.4564 | 0.4489 | new | ★ bate al mercado |
| +0.006 | **Ligue 2** | 0.4248 | 0.4189 | main | ★ bate al mercado |

**No adoptadas (15)** — entrenadas pero por debajo del ELO, documentadas con su
número: FA Cup (−0.165), Sudamericana (−0.048), Indian Super League (−0.042),
Paraguay (−0.035), Eerste Divisie (−0.033), A-League (−0.031), **EFL
Championship (−0.021)**, Grecia (−0.017), El Salvador (−0.016), Bélgica
(−0.010), League Two (−0.009), Brasil Série B (−0.006), Venezuela (−0.005),
Costa Rica (−0.004), LaLiga Hypermotion (+0.002, por debajo del margen exigido).

**3 fallaron por volumen**: Copa del Rey (207 partidos utilizables), Copa do
Brasil (276) y Carabao Cup (288). Las copas tienen pocos partidos por
definición; no se fuerza un modelo sobre 200 partidos.

> Nota sobre Japón: v34 la había dado por perdida («football-data lleva 228 días
> sin publicarla»). Se volvió a comprobar: hoy tiene 5 temporadas y datos
> frescos. Entra, y además bate al mercado.

### 2.4 Que lleguen a Apuestas del Día

`alpha_finder` sólo barre las ligas presentes en `fixtures_espn.ESPN_CODIGOS`.
Una liga entrenada y `disponible` pero ausente de ese mapa nunca habría llegado
a Apuestas del Día. Se generan y se inyectan los 40 slugs — **incluidos los de
las ligas que se entrenan con football-data**, porque su histórico viene del CSV
pero sus próximos partidos y cuotas salen de ESPN. Verificado: 63 códigos, 0
ligas nuevas sin código.

El selector de la UI también se rellena solo desde el catálogo, con bandera por
país y **sólo con las `disponible`**, para no ofrecer competiciones que no
superaron el listón.

---

## 3. Dependencia entre goles local y visitante (§3c del spec)

### 3.1 Lo que ya estaba resuelto y lo que no

El spec parte de que «el 1X2 asume independencia». Es cierto **a medias**:

* El motor INTERNACIONAL ya usaba una matriz de **choque común**
  (λ₀ = 0.12·min(λh,λa)) en `prediction_api._monte_carlo`.
* Las ligas de CLUBES sí usaban `np.outer`: independencia pura. **Ahí estaba el
  hueco.**

Y una parte ya se había respondido: **Dixon-Coles se probó en v27 sobre 13k+
partidos y se descartó** (el ρ óptimo salía con signo opuesto a la teoría y el
log-loss del marcador exacto no mejoraba). No se reimplementa.

### 3.2 Qué se midió

`run_bivariante_v68.py`, mismo protocolo que v27 (tasas rolling sin fuga, corte
cronológico 70/30). **56.748 partidos de 31 ligas**; train 39.723, validación
17.025. Tres matrices, tres métricas:

| Método | log-loss marcador | **log-loss 1X2** | Brier BTTS |
|---|---|---|---|
| independiente (actual) | 3.15726 | 1.10570 | 0.27198 |
| choque común | 3.15906 | 1.11365 ❌ | **0.26995** ✅ |
| cópula gaussiana (ρ=−0.20) | 3.18747 ❌ | **1.09364** ✅ | 0.27686 ❌ |

### 3.3 Veredicto: NO se adopta ninguna, y la razón es sólida

La cópula parecía ganar en 1X2 (−0.012). Al ampliar la malla de ρ aparece el
problema:

| ρ | −0.60 | −0.50 | −0.40 | −0.30 | −0.20 | −0.10 | 0.00 | +0.10 | +0.20 |
|---|---|---|---|---|---|---|---|---|---|
| log-loss 1X2 (train) | **1.09735** | 1.09803 | 1.09968 | 1.10250 | 1.10674 | 1.11275 | 1.12100 | 1.13212 | 1.14707 |

**El óptimo huye al borde de la malla y la curva es monótona: no hay óptimo
interior.** Eso no es un parámetro de dependencia, es la cópula absorbiendo un
sesgo de calibración de las λ (que producen demasiados empates). Un ρ de
correlación real tendría un mínimo interior y signo POSITIVO (el fútbol tiene
choques comunes). Es exactamente el mismo modo de fallo que v27 documentó para
Dixon-Coles.

Además, cada método gana en una métrica y pierde en otra: el choque común mejora
el BTTS pero empeora el 1X2, y la cópula al revés. Y para BTTS ya hay algo mejor
que las dos: el modelo de supervivencia Weibull AFT de v27 (Brier 0.2358).

**Lo que sí queda como mejora de infraestructura**: `distributions.py` gana una
API unificada y **analítica** (`matriz_goles`, `probabilidades_1x2`,
`prob_btts`) con los tres métodos, determinista y sin Monte Carlo. El
comportamiento por defecto no cambia. Verificado: las tres matrices suman 1,
preservan las marginales (λ exactas) e inducen la correlación esperada
(0.000 / +0.104 / ±0.088).

---

## 4. Mejora 1 (stats de juego) — por qué no procede como estaba especificada

La fuente que pedía el spec (FotMob) tiene 28 partidos. Su sustituta natural con
volumen real es **Understat** (~3.000 partidos con xG real, ya integrado en
`understat_scraper.py`). Pero al revisar el código aparece esto en
`league_engine.py`:

> «v14/M8: el xG real de Understat se evaluó como feature y **EMPEORÓ** el
> log-loss en LaLiga (1.014→1.108) y Premier (también la precisión): el relleno
> sintético condicionado a goles reales lleva más señal. `inyectar_xg` queda
> disponible pero DESACTIVADO.»

Es decir: la mejora ya se probó con la mejor fuente disponible y se rechazó con
números. **No se repite.** Queda una variante sin medir —EMA del xG real frente
a EMA del xG sintético, en vez de inyección partido a partido— que es lo único
nuevo que aportaría el spec; se deja anotada como candidata con su justificación,
no implementada.

---

## 5. Mejora 2 (alineaciones) — bloqueada por datos, con camino verificado

`alineaciones_historicas.csv` tiene 204 filas: no da para calibrar β.

La alternativa **verificada en esta sesión** es ESPN: el bloque `rosters` de cada
partido publica la alineación con marca de titular **y** las estadísticas de cada
jugador (se comprobó en v67 al construir `remates_jugadores.py`, con cobertura en
Premier, LaLiga, Serie A, Liga MX, MLS, Brasileirão, Nations League y
amistosos). Con eso se puede reconstruir un histórico de alineaciones real y
suficiente. No se implementó en esta sesión: la ampliación del catálogo consumió
el tiempo. Queda como el siguiente paso, ya desbloqueado.

---

## 6. Hallazgo no buscado: 22 modelos de liga ilegibles

Al correr el smoke test aparecieron los botones de Liga MX «no encontrados». La
causa: `modelos/liga_mx/modelo.joblib` lanzaba `XGBoostError: input stream
corrupted`. **22 de los modelos de liga estaban en el mismo estado**, todos
introducidos por el commit del bot de reentrenamiento de hoy
(`chore(datos): reentrenamiento automático`).

Lo que se comprobó antes de dar la alarma:

* No es desajuste de versiones: mi entorno coincide **exactamente** con los pines
  de `requirements.txt` (xgboost 3.3.0, sklearn 1.3.2, numpy 1.26.4…).
* No es truncamiento: los tamaños son normales (±0.1 %) y el workflow terminó
  con éxito en 9 m 57 s.
* No es conversión de saltos de línea: el blob de Git y el fichero local son
  byte a byte idénticos.
* Sólo fallan los artefactos que contienen un *booster* de XGBoost; los
  `escalador`, `reg_local` y `mesm` de la misma tanda cargan bien.
* La versión anterior (commit v66) carga sin problema.

**Conclusión honesta:** la hipótesis más probable es una incompatibilidad de
serialización de XGBoost entre el runner (Linux) y Windows. **No puedo demostrar
que producción (Linux) esté afectada**, así que no se afirma que lo esté.

**Lo que sí se hizo:**

1. **Reentrenar localmente las 22 ligas** con los mismos datos frescos. Las 275
   piezas `.joblib` del proyecto cargan ahora sin error (verificado una a una) y
   el smoke test vuelve a encontrar todos los botones.
2. **Blindar el workflow**: antes de commitear, ahora se intenta cargar cada
   modelo; los ilegibles se restauran a su versión anterior y, si hay más de 10,
   el workflow falla en vez de publicar. El agujero era que el workflow sólo
   comprobaba el código de salida del proceso, no que el artefacto sirviera.
3. **`.gitattributes`**: `*.joblib`, `*.npz`, `*.db`, `*.parquet` marcados como
   binarios (`core.autocrlf` está en `true` en esta máquina y no había
   `.gitattributes`), y texto normalizado a LF para que el diff sea estable
   entre el runner y las máquinas locales.

---

## 7. Tests de no regresión

| Test | Resultado |
|---|---|
| `test_simetria.py` | ✅ TODO OK |
| `test_match_parlay.py` | ✅ TODO OK |
| `smoke_botones.py` | ✅ TODO OK — botones de las 5 vistas |

El smoke test fue quien destapó lo del §6: los botones de Liga MX pasaron a «no
encontrado» y eso llevó al modelo ilegible. Es la segunda vez que ese test evita
que un fallo llegue a producción.

Comprobaciones adicionales:

* 275/275 artefactos `.joblib` cargan.
* 63 códigos ESPN; 0 ligas nuevas sin código de fixtures.
* Las tres matrices de goles suman 1 y preservan las marginales.

---

## 8. Lo que queda pendiente (con su camino)

* **Alineaciones (§5)**: fuente verificada (ESPN `rosters`), sin implementar.
* **BTTS accionable**: sigue sin cuotas históricas. `odds_historico.db` acumula
  desde el 18 de julio; con unos meses habrá muestra para el bootstrap sin
  scrapear nada.
* **EMA de xG real vs sintético (§4)**: única variante del spec que v14 no cubrió.
* **15 ligas entrenadas pero no adoptadas**: se re-evalúan cuando tengan otra
  temporada; el catálogo ya las tiene, sólo hay que volver a entrenarlas.
