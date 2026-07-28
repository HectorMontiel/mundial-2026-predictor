# VALIDACIÓN v75 — Histórico de cuotas, calibración medida y limpieza del catálogo

Fecha: 2026-07-28 · Rama de trabajo: `main` · Remotos: `origin` (HMREY) + `upstream` (HectorMontiel)

---

## 0. Resumen ejecutivo

El objetivo de la v75 era poblar `odds_historico.db` con cuotas históricas y usarlas
para recalibrar el modelo y los umbrales de la Capa 1. Se ha hecho, pero el trabajo
empezó desmontando **tres premisas del plan que resultaron ser falsas**, y por el
camino apareció un agujero de rentabilidad que llevaba activo desde la v68.

| Hallazgo | Estado |
|---|---|
| `data/raw/` no existe; las cuotas ya estaban en los `historico_*.csv` | Corregido: importación desde la fuente real |
| football-data **no publica BTTS** en ningún formato | Verificado y documentado; abierta la única fuente que sí lo publica |
| ESPN **borra las cuotas** al acabar el partido → no hay backfill posible | Verificado; resuelto con snapshots diarios |
| `austria`/`aut_bundesliga`, `grecia`/`gre_super_league`, `suiza`/`suiza_v48`: la misma liga con dos claves | Fusionadas; guardia automática para que no vuelva |
| **Una liga rechazada por su propio backtest estaba activa en la Capa 1** | Corregido (`aut_bundesliga` → `disponible=False`) |
| `roi_bets_*.json` no sirve para backtestear umbrales (pre-filtrado, sin `MATCH_ID`, un solo corte) | Sustituido por `pick_ledger.csv` |

---

## 1. Las tres premisas del plan que no se sostenían

### 1.1 `data/raw/` no existe

El plan pedía recorrer `data/raw/` en busca de los CSV crudos de football-data. Ese
directorio no está en el proyecto. Lo que sí hay es el resultado de que
`league_engine.descargar_liga` **ya normaliza las cuotas al descargar**: cada
`historico_{clave}.csv` lleva `odd_home/draw/away` (media de mercado de cierre con
respaldo B365), `odd_*_pin` (cierre de Pinnacle), `odd_over25/under25` y el hándicap.

Reimportar de la web habría significado descargar ~200 ficheros para reconstruir algo
que ya estaba en disco **y** reconstruir a mano el `MATCH_ID`, que es la clave con la
que se cruzan modelos y `alpha_finder`. Se importa desde los CSV del proyecto.

Cobertura medida antes de tocar nada:

| | ligas |
|---|---|
| Con cuota de cierre 1X2 (≈100 % de las filas) | 36 |
| Con cierre de Pinnacle (83-99 %) | 36 |
| Con Over/Under 2.5 de cierre | 17 |
| **Sin ninguna cuota histórica** | **28** |

### 1.2 football-data no publica BTTS — en ningún formato

El plan daba por hecho que las ligas `/mmz4281/` traen `B365BTTS Yes` / `B365BTTS No`.
Descargados los ficheros en vivo el 2026-07-28:

| Fichero | Columnas | Columnas con "btts"/"bts" |
|---|---|---|
| `/mmz4281/2526/E0.csv` (Premier) | 132 | **0** |
| `/mmz4281/2526/SC0.csv` (Scottish Premiership) | 132 | **0** |
| `/new/MEX.csv` | 25 | **0** |
| `/new/JPN.csv` | 25 | **0** |

Los únicos mercados que publica football-data son 1X2, Over/Under 2.5 y hándicap
asiático. **No existe histórico gratuito de precios BTTS.** Qué se hizo en vez de
dejarlo pendiente: §5.

### 1.3 ESPN retira las cuotas tras el pitido final

Para las 28 ligas sin cuota la esperanza era rellenar desde ESPN. Medido sobre 6
competiciones y varios horizontes:

| Liga | −120 días | −30 días | −7 días | +3 días |
|---|---|---|---|---|
| col.1 | 0/7 | — | — | **8/8** |
| bra.2 | 0/9 | 0/6 | 0/10 | — |
| chi.1 | — | — | — | **8/8** |
| mex.1 | — | — | 0/2 | **9/9** |

El bloque `odds` llega como `[null]` en todo partido ya jugado. **El backfill
histórico desde ESPN es imposible**, no difícil. La única vía es fotografiar la línea
antes del partido — de ahí `daily_snapshots.py` (§4).

---

## 2. El agujero que apareció por el camino: ligas duplicadas

Al validar fuentes saltó que `suiza` y `suiza_v48` eran **la misma liga con dos
claves** (idéntica URL `SWZ.csv`, idéntica ventana de 8 años). Se añadió
`config.validar_catalogo()`, que compara la HUELLA de la fuente en vez del nombre de
la clave, y destapó dos casos más — estos sí graves:

| Clave A (football-data, con cuotas) | Clave B (ESPN, sin cuotas) | Situación encontrada |
|---|---|---|
| `austria` — RECHAZADA (no bate ELO 37.3<42.5, ROI backtest −17,7 %) | `aut_bundesliga` — **ACTIVA en Capa 1** | La misma Bundesliga austriaca |
| `grecia` — RECHAZADA (42.6<44.1, ROI −24,9 %) | `gre_super_league` — **ACTIVA en Capa 1** | La misma Super League griega |

Es decir: el proyecto estaba publicando picks de competiciones que su propio backtest
había declarado deficitarias, y no se veía **porque la variante activa venía de una
fuente sin cuotas y por tanto no había con qué medirla**. La liga invisible era
precisamente la que no se podía auditar.

**Causa raíz encontrada**: `generar_ligas_v68.py` define un conjunto `YA_CUBIERTAS`
para no duplicar por ESPN las ligas que ya sirve football-data… y **nunca lo usaba**.
Además comparaba claves (`austria` ≠ `aut_bundesliga`), no competiciones.

**Corregido en tres niveles**, para que no dependa de que nadie se acuerde:

1. `config.validar_catalogo()` detecta gemelos por huella de fuente.
2. `generar_ligas_v68.escribir_config()` ahora sí cruza `YA_CUBIERTAS` con los slugs
   de ESPN (`ESPN_DE_FOOTBALL_DATA`).
3. `test_catalogo_y_cuotas.py` falla si reaparece cualquiera de las claves fusionadas.

### 2.1 Migración de fuente y veredicto de la regla de oro

Las tres competiciones se unificaron en una sola clave apuntando a football-data, se
reentrenaron y decidió la regla de oro (batir la línea base ELO):

| Liga | Fuente antes | Cuotas antes | Precisión | ELO | Mercado | Veredicto |
|---|---|---|---|---|---|---|
| `gre_super_league` | ESPN | 0 % | **0.536** | 0.506 | 0.507 | **Adoptada** (+3,0 pp sobre ELO; bate también al mercado) |
| `rus_premier` | ESPN | 0 % | **0.530** | 0.512 | 0.541 | **Adoptada** (+1,8 pp sobre ELO) |
| `aut_bundesliga` | ESPN | 0 % | 0.373 | 0.425 | 0.442 | **Retirada de Capa 1** (−5,2 pp bajo ELO) |

`gre_super_league` pasó de rechazada a adoptada porque el rechazo de la v40 se hizo
con 3 temporadas (709 partidos) y ahora tiene 5 (1.189). `aut_bundesliga` confirma
exactamente el veredicto que ya tenía `austria` en v40 (37.3 vs 42.5): era la misma
liga, y su modelo pierde contra su propia línea base.

Además, `aut_bundesliga` era **la liga peor calibrada del proyecto** según la v71
(+13,1 pp de sobreconfianza en la selección) — y estaba emitiendo picks a ciegas.

### 2.2 Verificación de fuentes: el HTTP 200 que miente

Antes de migrar nada se comprobó qué otras ligas sin cuotas podría servir
football-data. Probando por código de país, **20 de 35 respondieron HTTP 200**. Pero
al mirar el contenido:

| Petición | Lo que devuelve de verdad |
|---|---|
| `/new/COL.csv` | Ekstraklasa polaca (byte a byte igual que `/new/POL.csv`) |
| `/new/BOL.csv` | Ekstraklasa polaca (idem) |
| `/new/KOR.csv` | Eliteserien noruega (igual que `/new/NOR.csv`) |
| `/new/CHL.csv` | Superliga **china** |

Dar de alta una liga mirando el código de estado habría metido partidos polacos en la
liga colombiana. `odds_store.fuente_football_data_valida()` valida por CONTENIDO
(columna `Country` + coincidencia de equipos) y es la única puerta de entrada; el test
de no regresión comprueba que sigue rechazando `/new/COL.csv`.

Resultado real de la búsqueda: solo AUT y RUS eran genuinas. PER, URY, ECU, VEN, PRY,
CRI, SLV, IND, ZAF, GRC y NED dan 404 — no existen. Es una limitación de la fuente,
no del código.

---

## 3. `odds_historico.db` poblado

`odds_store.py` (almacén canónico) + `import_historical_odds.py` (importación).

Tabla `historical_odds` con dos fases:

- `fase='cierre'` — cuota de cierre de un partido jugado. Idempotente: reimportar
  actualiza, no duplica.
- `fase='snapshot'` — foto diaria de un partido futuro, una fila por día y casa.
  Nunca se pisa una foto anterior (es lo que hace calculable el CLV).

La tabla `snapshots` de la v43 se conserva intacta (la lee `clv_tracker`).

**Resultado de la importación:**

| | |
|---|---|
| Filas de cierre | **137.185** |
| Partidos distintos | **72.202** |
| Ligas con cierre de mercado | 36 |
| Ligas con cierre de Pinnacle | 36 |
| Ligas sin cuota histórica (solo snapshots a partir de hoy) | 28 |

Comprobación pedida en el plan:
`SELECT COUNT(*) FROM historical_odds WHERE league_key='premier' AND bookmaker='mercado'`
→ **1.140**, que es exactamente el número de partidos de `historico_premier.csv`.

---

## 4. Snapshots diarios (`daily_snapshots.py`)

Captura de la línea de los próximos 7 días desde Pinnacle, Bovada y ESPN, con
`dias_al_partido` para reconstruir el movimiento (base del futuro CLV Predictor).

Primera ejecución (2026-07-28):

| | |
|---|---|
| Filas nuevas | 553 |
| Partidos | 241 |
| Ligas | 26 |
| Casas | Bovada (187), Pinnacle (168), DraftKings (139) |
| **Ligas que antes tenían 0 histórico y ahora acumulan** | **14** |

Detalles que evitan que el histórico nazca torcido:

- El `match_id` se construye con `league_engine._match_id` sobre los nombres del
  **catálogo del modelo** (resueltos con `name_mapper`), no sobre los de ESPN o
  Pinnacle. Así la foto de hoy y el cierre que football-data publique mañana caen en
  el mismo identificador.
- `reconciliar()` corrige el desfase de un día entre la fecha UTC de ESPN y la fecha
  local de football-data. Sin eso, las fotos de partidos en horario americano
  quedarían huérfanas y el CLV se mediría solo sobre partidos europeos.
- Segunda ejecución el mismo día: `INSERT OR IGNORE`, no altera el histórico.

Integrado en `.github/workflows/retrain_leagues.yml`, después del reentrenamiento
(para que vea los CSV y los `team_stats` ya frescos) y sin poder tumbar el workflow.

---

## 5. BTTS: qué se puede decidir hoy y qué no

Sin precios históricos (§1.2), un backtest de ROI exigiría **inventarse un margen**, y
el margen inventado sería quien decidiese el resultado. Eso no es validar. Se hicieron
dos cosas:

**a) Abrir la fuente que sí existe.** Pinnacle publica *Both Teams To Score?* en su
endpoint público — medido: **102 partidos con precio Sí y No, sin clave y sin
límite**. No se estaba usando porque `cuotas_multi` llamaba con `withSpecials=false`.
Corregido: BTTS entra ahora en el índice de Pinnacle, en `cuotas_partido()` y en los
snapshots diarios. Desde hoy el histórico de precios BTTS crece solo.

**b) Decidir lo que sí es decidible sin precios**, con `backtest_btts.py`: si el
modelo Weibull aporta información **que el cierre real de 1X2 + O/U 2.5 no tenga ya**.
Si no bate a eso, no hay precio que lo salve.

_(resultados en §8)_

---

## 6. Ledger de predicciones: el sustrato que faltaba

Para recalibrar o backtestear umbrales hay que poder responder "¿qué decía el modelo
ANTES del partido y a qué cuota cerró?". `roi_bets_*.json` no lo permite:

- guarda solo apuestas que **ya pasaron un filtro** (`prob>0.70 o EV>0`) — medir un
  umbral más bajo que el que generó los datos es imposible;
- guarda la probabilidad del lado elegido, no el **vector completo** → no se puede
  devigar ni evaluar otro lado;
- no lleva `MATCH_ID` → no cruza con las cuotas;
- sale de un **único corte 80/20**, no de un walk-forward: 78 apuestas en Premier, 61
  en League Two. Con eso, cualquier "umbral óptimo" es ruido.

`build_pick_ledger.py` genera walk-forward de origen móvil (5 pliegues sobre el último
50 % del calendario), sin filtrar, con vector completo, `MATCH_ID` y cuotas de cierre.
Solo en Premier: **547 predicciones fuera de muestra frente a 78 apuestas filtradas**.

Para que el backtest no mida un modelo distinto del desplegado, el bloque de
construcción de features se extrajo de `entrenar_liga` a
`league_engine.preparar_features_extra()` y lo usan **los dos**. Verificado que el
refactor no cambia nada: `gre_super_league` da exactamente `acc=0.536 / ELO 0.506 /
mercado 0.507` antes y después.

---

## 7. Recalibración del encogimiento al mercado

_(resultados en §8)_

La fórmula que proponía el plan, `w = 1 − |sesgo| / max(|sesgo|, 0.01)`, es
degenerada: vale 0 para cualquier sesgo ≥ 0,01 (anula el modelo entero en cuanto hay
un punto de sesgo) y se dispara a valores muy negativos por debajo. No se usó.

Método adoptado, que además deja de suponer una relación sesgo→peso que nadie ha
comprobado:

1. `p_mercado` = cierre de Pinnacle **devigado por el método de potencia** (Shin
   simplificado), que corrige el sesgo favorito-perdedor mejor que el proporcional.
2. `w` se elige **minimizando la log-loss** del vector encogido, no el sesgo: es lo
   que de verdad queremos bajar, y premia estar calibrado en todo el vector.
3. Selección y evaluación **separadas en el tiempo**: `w` se elige con los pliegues
   antiguos y se juzga en el último, que no participó.
4. **Encogimiento jerárquico** hacia el `w` global con peso `n/(n+150)` — respuesta
   directa a la lección de `edge_engine` (el mapa por liga no es estacionario): con
   pocos partidos la liga hereda el global y solo se separa si tiene datos.
5. **Regla de adopción**: log-loss ≥ 0,005 mejor sin empeorar precisión, o precisión
   ≥ 0,5 pp mejor sin empeorar log-loss.

---

## 8. Resultados medidos

### 8.1 El ledger

| | |
|---|---|
| Predicciones fuera de muestra | **47.948** |
| Ligas | 56 |
| Con cuota de cierre de mercado | **33.476** |
| Con cierre de Pinnacle | 26.666 |
| Rango | 2021-08-16 → 2026-07-28 |
| Pliegues | 5 (origen móvil, sobre el último 50 % del calendario) |

Tres ligas (`bundesliga`, `eredivisie`, `liga_mx`) fallaron en la primera pasada
por un fallo del propio refactor (`corte_imt` no llegaba a la función extraída).
Se corrigió — el parámetro es ahora **obligatorio**, porque
`optimizar_coeficientes` interpreta `None` como "usa todo el histórico", que
dentro de un backtest sería fuga temporal pura — y se reincorporaron.

Comprobación de que el refactor no alteró producción: `modelos/liga_mx`,
`modelos/laliga` y `modelos/primeira` producen `metadata.json` **byte a byte
idéntico** al de `HEAD`.

### 8.2 Recalibración: el resultado principal de la versión

Peso elegido con los pliegues 0-3 y **juzgado en el pliegue 4, que no participó**:

| | antes | después | Δ |
|---|---|---|---|
| log-loss | 1.0226 | **1.0030** | **−0.0196** |
| precisión | 0.4986 | **0.5120** | **+1,34 pp** |

Ambas superan la regla de adopción (≥0,005 de log-loss **o** ≥0,5 pp de
precisión sin degradar la otra) con margen amplio. 25 de 34 ligas adoptan peso
propio.

**Efecto en la Capa 1** (umbrales de producción sin tocar, los 5 pliegues del
walk-forward, 33.476 candidatos):

| Calibración | picks | ROI | p5 bootstrap | acierto |
|---|---|---|---|---|
| _sin corrección_ (w=1) | 951 | −3,93 % | −8,49 % | 55,1 % |
| v71 (4-11 partidos/liga) | 937 | −4,07 % | −8,81 % | 55,1 % |
| **v75** | 464 | **+4,99 %** | −1,53 % | **60,8 %** |

Con **line shopping** (mejor precio entre media de mercado y Pinnacle), que es
lo que hace producción de verdad:

| Calibración | picks | ROI | p5 bootstrap | acierto | ventanas |
|---|---|---|---|---|---|
| _sin corrección_ (w=1) | 1.036 | −1,15 % | −5,66 % | 56,7 % | −2,0 / 8,4 / −2,2 / −6,5 / −5,1 |
| v71 | 1.029 | −1,85 % | −5,93 % | 56,3 % | — |
| **v75** | 552 | **+6,37 %** | **+0,55 %** | **61,4 %** | 11,0 / 11,2 / 4,9 / −3,7 / 3,8 |

Y solo sobre el pliegue 4 (el único que no intervino en elegir `w`):

| Calibración | picks | ROI (cierre medio) | ROI (line shopping) |
|---|---|---|---|
| sin corrección | 164 / 172 | −2,73 % | −5,10 % |
| **v75** | 45 / 50 | **+7,29 %** | **+3,80 %** |

Tres cosas que conviene decir sin adornos:

1. **La configuración que estaba en producción perdía dinero fuera de muestra**
   (−3,93 % con 951 apuestas). No se sabía porque nunca se había medido con un
   walk-forward sin pre-filtrar.
2. **La calibración de la v71 no ayudaba**: −4,07 %, ligeramente peor que no
   corregir nada. Es lo esperable de unos pesos ajustados con 4-11 partidos por
   liga; el problema no era el método, era la muestra.
3. El p5 solo pasa a positivo con line shopping (+0,55 %) y con n=45-50 en el
   pliegue aislado los intervalos son anchos. La adopción se sostiene sobre la
   mejora de log-loss y precisión, que sí tiene 33.476 observaciones detrás y es
   monótona y consistente, más un ROI que mejora en las dos definiciones de
   precio y en 4 de 5 ventanas.

### 8.3 Umbrales de Capa 1: **no se adopta nada**

Walk-forward anidado sobre 2.400 combinaciones (la combinación se elige con los
pliegues anteriores y se juzga en el siguiente):

| | n | ROI | p5 | ventanas |
|---|---|---|---|---|
| Umbrales vigentes | 253 | +1,64 % | −7,03 % | 4,1 / −5,9 / 10,0 |
| Mejor combinación hallada | 61 | +11,70 % | **−2,49 %** | 12,4 / 17,5 / −6,9 |

La combinación optimizada (`prob≥0.70, EV∈[0.08,0.15], cuota≥1.30`) rinde más,
pero con 61 apuestas su bootstrap p5 es negativo: **no supera la regla y no se
adopta**. Ninguna de las 34 ligas consigue umbrales propios (muestras de 16-107
apuestas y p5 muy negativos).

`umbrales_capa1.json` se escribe igualmente con `global: null` y `ligas: {}`,
para que quede registrado que se buscó y no se encontró, en vez de dejar un
hueco que dentro de un año nadie sepa interpretar. `alpha_finder` lo lee y cae
limpiamente a los umbrales de `edge_engine`.

### 8.4 BTTS: veredicto decisivo, sin esperar meses

Sobre **15.950 partidos fuera de muestra de 20 ligas**:

| | Brier | log-loss |
|---|---|---|
| Modelo Weibull | 0.24880 | 0.69077 |
| Tasa base de la liga | 0.24891 | 0.69096 |
| Implícito en el cierre 1X2 + O/U 2.5 | **0.24559** | **0.68427** |
| Mercado + modelo combinados | 0.24561 | 0.68430 |

El modelo es **indistinguible de contestar siempre la tasa base** (0,0001 de
Brier) y peor que lo que el cierre ya implica. Combinarlo con el mercado no
mejora al mercado solo: **no aporta información**. Ningún precio arregla eso.

Consecuencias aplicadas:

- BTTS sigue **fuera de la Capa 1** (ya lo estaba).
- **Se retira su listón rebajado en los parlays** (entraba con prob>60 % y
  EV>+1 % frente al prob≥55 % y EV>+2 % del resto). Era una preferencia de
  producto de la v43, nunca una medida, y las patas de un parlay multiplican
  sus errores.
- La sección destacada de BTTS **se mantiene** (la pidió el usuario) pero deja
  de anunciarse como "uno de los mercados mejor calibrados del sistema" —
  afirmación que la medición desmiente — y se marca con `sin_edge_modelo`.
- Se abre la única fuente que sí existe: **Pinnacle publica _Both Teams To
  Score?_** en su endpoint público (102 partidos con precio Sí y No, sin clave
  ni límite). No se usaba porque `cuotas_multi` llamaba con
  `withSpecials=false`. Ya entra en el índice, en `cuotas_partido()` y en los
  snapshots: el histórico de precios BTTS crece desde hoy por si el modelo
  mejora algún día.

---

## 9. Otros arreglos de raíz

| Fallo | Arreglo de raíz |
|---|---|
| Clave de snapshot DIARIA: al añadir BTTS a media mañana, el día ya estaba escrito y `INSERT OR IGNORE` impedía recuperarlo | Cubo **horario**: el workflow diario sigue dando una foto por casa, pero un reintento aporta una foto nueva en vez de chocar, y nunca se pisa nada |
| `optimizar_coeficientes(hasta_fecha=None)` = "usa todo el histórico" = fuga silenciosa en cualquier backtest | `corte_imt` es **obligatorio**; sin él se lanza `ValueError` con el motivo |
| El filtro de élite estaba **copiado en dos sitios** de `alpha_finder` | Un único `pasa_capa1()`, con umbrales por liga |
| `sys.stdout` en cp1252: imprimir una flecha abortaba el script **después** de haber hecho todo el trabajo | UTF-8 forzado en los cinco módulos nuevos |
| `datetime.utcnow()` deprecado | `datetime.now(timezone.utc)` |
| **El histórico de fotos nunca habría crecido**: `odds_historico.db` está en `.gitignore` (49 MB), el runner de Actions clona limpio, así que cada día habría capturado 500 filas, no habría commiteado nada y al siguiente habría empezado de cero — durante meses, en silencio | Se separa lo reproducible de lo que no lo es: los **cierres** se derivan de los `historico_*.csv` del repo, y las **fotos** — irrepetibles: si no se capturó la línea antes del partido, no existe en ninguna parte — se vuelcan a `odds_snapshots.csv` (0,19 MB), que sí se commitea. `odds_store.rehidratar()` reconstruye la base entera desde el repositorio; verificado apartando la base y recuperando 137.185 cierres + 989 fotos + 39 precios BTTS |

---

## 10. Tests de no regresión

| Test | Resultado |
|---|---|
| `test_catalogo_y_cuotas.py` (nuevo, 21 comprobaciones) | **TODO OK** |
| `test_simetria.py` | **TODO OK** |
| `test_match_parlay.py` | **TODO OK** |
| `smoke_botones.py` | **TODO OK** |
| Barrido universal en vivo | 4 en Capa 1, 22 en Capa 2, 15 candidatos, 33 patas, 67 pronósticos |

El test nuevo bloquea, una por una, todas las causas raíz de esta versión:
gemelos en el catálogo, el HTTP 200 engañoso de football-data, duplicación al
reimportar cierres, sobrescritura de fotos, fuga temporal o pre-filtrado en el
ledger, y umbrales publicados sin bootstrap p5 positivo.

---

## 11. Entregables

| Fichero | Qué es |
|---|---|
| `odds_store.py` | Almacén canónico + verificador de fuentes por contenido |
| `import_historical_odds.py` | Importación de cierres (137.185 filas) |
| `daily_snapshots.py` | Fotos diarias + reconciliación de identidad |
| `build_pick_ledger.py` | Walk-forward de origen móvil sin filtrar |
| `recalibrate_from_history.py` | `w` por log-loss fuera de muestra |
| `backtest_thresholds.py` | Umbrales con walk-forward anidado + bootstrap |
| `backtest_btts.py` | Veredicto de BTTS sin suponer margen |
| `test_catalogo_y_cuotas.py` | No regresión de todo lo anterior |
| `pick_ledger.csv` | 47.948 predicciones fuera de muestra |
| `calibracion_mercado.json` | 25 ligas recalibradas |
| `umbrales_capa1.json` | Sin adopción, documentado |

## 12. Qué NO se hizo, y por qué

- **CLV Predictor**: solo hay una foto (la de hoy). Necesita semanas de
  acumulación; la infraestructura queda corriendo a diario, que era el objetivo
  de esta fase.
- **Backfill de cuotas para las 28 ligas de ESPN**: imposible, no difícil (§1.3).
- **Histórico de BTTS**: no existe gratis (§1.2). Empieza a acumularse hoy.
- **Umbrales por liga**: se buscaron y ninguno superó la regla (§8.3). No
  mejorar y decirlo también es un resultado.
