# VALIDACIÓN v67 — Tenis multicompetición, parlays de tenis y remates reales por jugador

**Fecha:** 2026-07-27 · **Entorno:** `.venv` Python 3.12

---

## 0. Resumen ejecutivo

| Qué | Antes (v66) | Después (v67) |
|---|---|---|
| Competiciones de tenis en la UI | 1 selector ATP/WTA, sin categorías | **10 grupos / 14 categorías** filtrables |
| Partidos de tenis en el modelo (ATP) | 66.570 | **72.891** |
| Partidos de tenis en el modelo (WTA) | 43.821 | **56.213** |
| Jugadores cubiertos (ATP / WTA) | 1.820 / 1.319 | **2.136 / 2.000** |
| Precisión ATP (circuito principal) | 0.6522 | **0.6555** |
| Precisión WTA (circuito principal) | 0.6486 | **0.6574** |
| Próximos partidos de tenis | solo los de hoy con cuota en Betexplorer | **calendario ESPN a 10 días, auto-refresco 20 min** |
| Botón «Cargar» para ver un partido | sí | **eliminado** (al seleccionar, se ve) |
| Parlays combinados en tenis | **no existían** | sí, con envío a Telegram |
| Remates por jugador (fútbol) | estimados desde los goles | **reales, observados partido a partido** |

---

## 1. Auditoría de fuentes (lo que se pidió validar)

Todo verificado con peticiones reales el 2026-07-27, no por documentación.

### 1.1 ESPN — ¿tiene lo que pedía la lista?

| Comprobación | Resultado |
|---|---|
| Ligas de tenis publicadas | **exactamente 2**: `atp` y `wta` (`/v2/sports/tennis/leagues` → count 2) |
| ¿Endpoint de Challenger / ITF / UTR? | **No existe** |
| Grand Slams | Sí, dentro de los feeds atp/wta con `major: true` |
| WTA 125 e ITF femenino | Sí, mezclados en el feed `wta` (VanOpen, Axeria Open, Tolentino…) |
| Challengers ATP | Solo algunos, con su nombre comercial |
| Rondas de clasificación | **Sí** — y son la aportación más grande |
| Estadísticas de saque (aces, dobles faltas, puntos de saque) | **No**: `.../competitors/{id}/statistics` devuelve **404** |
| Rango de fechas | Acepta `dates=AAAAMMDD-AAAAMMDD`, pero **revienta con 500** en tramos con Grand Slam → hay que trocear |

### 1.2 Fuentes evaluadas, una por una

| Fuente | ¿Sirve? | Qué aporta / por qué no |
|---|---|---|
| **Kaggle `dissfya/atp` y `/wta`** | ✅ Adoptada (ya estaba) | 68k + 45k partidos, fresco a ayer, cuotas 100 %. **Hallazgo: el ATP ya traía la columna `Series` (nivel del torneo) y el motor nunca la había usado.** |
| **tennis-data.co.uk** | ✅ Adoptada | Es el origen real del mirror de Kaggle. Aporta el `Tier` de la WTA (que Kaggle NO trae) y cuotas de Pinnacle/máxima/media. Enlaza con Kaggle al **100 %** por fecha + jugadores. Ojo: dejó de publicar `.zip`, ahora solo `.xlsx`. |
| **ESPN** | ✅ Adoptada | +6.555 partidos ATP y +12.986 WTA que Kaggle no tiene (previas, Challenger, WTA 125, ITF W). Y el calendario de próximos partidos. |
| **JeffSackmann/tennis_atp y tennis_wta** | ❌ **Ya no existen** | Era LA fuente estándar (con aces, dobles faltas, puntos de saque, Challengers e ITF). La cuenta de GitHub sigue viva pero **solo conserva `tennis_MatchChartingProject`**; los dos repos de datos devuelven 404. Por eso el ELO de saque/resto sigue sin poder calcularse. |
| **Kaggle Challengers (`dissfya/atp-challenger-…`)** | ❌ 403 | Sigue privado, igual que en v35. |
| **API de UTR (`api.utrsports.net`)** | ❌ | Responde **sin credenciales**, pero `search/events` solo devuelve eventos amateur y locales ("ProWorld Series" de Delray Beach). Los endpoints de resultados devuelven 400. **No hay UTR Pro Match Series.** |
| **TennisAbstract** | ⚠️ Parcial | El sitio sigue en pie y publica páginas `/current/{año}{Ciudad}Challenger.html` con resultados parseables. Pero solo del torneo **en curso**: no hay índice histórico, así que no sirve como fuente de entrenamiento. Queda documentada como candidata para resultados de Challenger en vivo. |
| **Sofascore** | ❌ 403 | API bloqueada. |
| **UltimateTennisStatistics** | ❌ 400 | Sin API pública utilizable. |

### 1.3 Veredicto honesto sobre la lista pedida

| Categoría pedida | Estado |
|---|---|
| Wimbledon M/F | ✅ completo (+ previas) |
| Open de Australia M/F | ✅ completo (+ previas) |
| Roland Garros M/F | ✅ completo (+ previas) |
| US Open M/F | ✅ completo (+ previas) |
| ATP Torneos y Masters | ✅ completo |
| WTA Torneos y Premier | ✅ completo |
| WTA 125 / Challenge Femenino | ⚠️ **parcial** — 296 partidos históricos; en el calendario en vivo sí aparecen (VanOpen, Axeria…) |
| Challenger Masculino ATP | ⚠️ **parcial** — 1.184 partidos históricos |
| ITF W-World | ⚠️ **parcial** — 6.429 partidos históricos |
| ITF M-World | ❌ **sin fuente gratuita** |
| UTR Pro Match Series M/F | ❌ **sin fuente** (la API de UTR solo tiene eventos amateur) |

La causa de las tres últimas filas es la misma: **la desaparición de los repos de
Sackmann**. No es una limitación de diseño de la app; es que la fuente que
cubría el circuito inferior dejó de existir. Se deja el hueco documentado y el
código preparado (las categorías `itf_m` y las de UTR existen en `CATEGORIAS`),
de modo que el día que aparezca un mirror basta con añadir un cargador.

---

## 2. El modelo de tenis — A/B con el mismo conjunto de test

`run_wf_tenis_v67.py`. Walk-forward de 5 temporadas. Las tres ramas se evalúan
sobre **exactamente el mismo test** (el circuito principal de cada ventana), que
es el universo con el que se validó hasta v66 — así la comparación es válida.

| Rama | Qué cambia |
|---|---|
| `base` | producción v66: entrena solo con Kaggle |
| `datos` | mismas features, entrena con el histórico unificado |
| `nivel` | `datos` + 3 features de nivel de competición (ELO por nivel, nivel del partido, experiencia en el nivel) |

### 2.1 ATP

| Rama | Precisión | Log-loss |
|---|---|---|
| base | 0.6557 | 0.6154 |
| **datos** | **0.6559** | 0.6154 |
| nivel | 0.6508 ❌ | 0.6147 |
| *categorías nuevas* | *0.5856* | *0.6646* |
| mercado (referencia) | 0.6817 | — |

### 2.2 WTA

| Rama | Precisión | Log-loss |
|---|---|---|
| base | 0.6585 | 0.6129 |
| **datos** | **0.6597** | **0.6121** |
| nivel | 0.6586 | 0.6118 |
| *categorías nuevas* | *0.6231* | *0.6458* |
| mercado (referencia) | 0.6814 | — |

### 2.3 Decisión

**Se adoptan los datos unificados. Se DESCARTAN las features de nivel.**

* `datos` no degrada en ATP (+0.02 pp, empate técnico) y mejora en WTA
  (+0.12 pp con mejor log-loss), y sobre todo **abre categorías que antes no
  tenían modelo**: 316 jugadores ATP y 681 WTA nuevos.
* `nivel` **degrada el ATP en 0.49 pp**. En la WTA "pasa" la regla de oro por
  +0.01 pp de precisión, que es ruido puro — y de hecho es **peor que `datos`**
  (0.6586 < 0.6597). Adoptarlas sería optimizar contra el azar. El código queda
  en el repo (`FEATURES_V67`) para reevaluarlas con más temporadas.

### 2.4 Aviso metodológico: la precisión global ya no es comparable

Al reentrenar con el histórico unificado, la precisión global cae
(ATP 0.6522 → 0.6290; WTA 0.6486 → 0.6341). **Eso no es una regresión**: el
conjunto de validación ahora incluye previas, Challenger, WTA 125 e ITF, que son
intrínsecamente menos predecibles (0.59 y 0.62 respectivamente). Sobre el
circuito principal —métrica comparable— el modelo **mejora**:

| Circuito | v66 | v67 (circuito principal) |
|---|---|---|
| ATP | 0.6522 | **0.6555** |
| WTA | 0.6486 | **0.6574** |

`metadata.json` publica ahora `validacion_por_universo` con los dos números,
igual que se hizo en v66 con el universo de selecciones. Es el mismo error de
lectura, y por eso se instrumenta igual.

---

## 3. Defectos encontrados y corregidos en el camino

Todos verificados con datos, no supuestos:

1. **Nombres incompatibles entre fuentes.** ESPN escribe «Carlos Alcaraz» y
   Kaggle «Alcaraz C.». Sin normalizar, ESPN duplicaba los partidos del
   circuito principal **y partía el historial de cada jugador en dos personas
   distintas** — lo que habría arruinado el ELO. Se añadió `canonico()`, con
   manejo de partículas ("Alex de Minaur" → "de Minaur A."). Verificado sobre 10
   casos límite.
2. **Kaggle YA excluye las retiradas.** Una de las mejoras previstas era filtrar
   partidos decididos por abandono. Al medirlo: de las 1.095 filas de
   tennis-data que no enlazan con Kaggle, **1.023 son exactamente
   Retired/Walkover/Awarded/Disqualified**. El entrenamiento nunca estuvo
   contaminado; la mejora era innecesaria y se descartó.
3. **`Series`/`Tier` compartido entre circuitos.** «International» es un nivel
   que usaron los dos circuitos (ATP hasta 2008, WTA hasta 2020). Clasificar por
   el nombre del nivel metía **5.232 partidos de la WTA en la categoría ATP**.
4. **Caché de torneos sin circuito.** `es_principal()` cacheaba por nombre de
   torneo; procesar ATP y luego WTA en el mismo proceso reutilizaba el veredicto
   masculino para el femenino y vaciaba las categorías ITF/125.
5. **Catálogo histórico demasiado ancho.** Al comparar contra los 200+ nombres
   de torneos de toda la historia, el fuzzy ascendía torneos ITF a «WTA Tour».
   Se limitó a los 3 últimos años.
6. **Los patrocinadores rompen el reconocimiento por nombre.** «Mubadala DC
   Open» es el «Citi Open»; «Mifel Tennis Open by Telcel Oppo» es «Los Cabos
   Open». Para el calendario en vivo, la categoría se decide por la **mediana
   del ranking del cuadro**, no por el nombre — y se consolida por torneo, no
   partido a partido (si no, el mismo cuadro salía repartido entre «ATP Tour» y
   «Challenger» según a quién le tocara jugar).
7. **El tenis no tenía parlays.** Su plantilla publicaba `campos` pero no
   `secciones`, que es lo que lee `match_parlay`: el generador **no veía ni uno**
   de sus 33 mercados. Era el único deporte de la app sin combinadas.
8. **Patas sin valor en el parlay.** El hándicap de juegos de un partido parejo
   (+6.5 juegos) sale al 99 % → cuota justa 1.00. Se quedan en la tabla
   informativa pero fuera del parlay (`PROB_MAX_APOSTABLE = 97 %`).
9. **El parlay ignoraba la superficie elegida.** `match_parlay` llama a
   `motor.plantilla(home, away)` sin contexto (es agnóstico del deporte), así
   que las combinadas se calculaban siempre en pista dura y al mejor de 3. Se
   añadió `TennisEngine.con_contexto()`.
10. **Al mejor de 5 sets casi no había mercados.** Los Grand Slam masculinos se
    juegan a cinco sets y la plantilla solo tenía ahí los de juegos (14 campos
    frente a 33 en bo3). Se añadieron los 17 mercados de sets para bo5.
    Verificado: los marcadores exactos suman 100 % y coinciden con el ganador.
11. **Ampliar `FEATURES` habría reventado la WTA.** El vector del circuito
    femenino se derivaba de «si no hay clave `features`, usa `FEATURES`»; al
    añadir las 3 features nuevas habría pasado de 10 a 13 columnas contra un
    modelo entrenado con 10. Ahora se declara explícitamente por circuito.
12. **ESPN devuelve 400/500 con rangos de fechas largos.** En tenis revienta con
    tramos que contienen un Grand Slam; en fútbol, con más de ~2 meses. Ambos
    casos se trocean automáticamente (meses → semanas).

---

## 4. Remates y remates a puerta POR JUGADOR (fútbol)

### 4.1 El problema

La sección «¿Quién remata?» mostraba un remates/partido **estimado**: se partía
de los goles de los últimos 24 meses y se multiplicaba por la calibración de
StatsBomb. Dos consecuencias: el número no era un remate observado, y **solo
aparecían jugadores que habían marcado** — el delantero que remata ocho veces
por partido sin acertar no existía en la tabla.

### 4.2 La solución

ESPN publica, en el `summary` de cada partido, un bloque `rosters` con
estadísticas **por jugador**, incluidos `totalShots` (SHOT) y `shotsOnTarget`
(SOG). Cobertura verificada partido a partido:

| Liga | ¿Publica remates por jugador? |
|---|---|
| Premier, LaLiga, Serie A, Liga MX, MLS, Brasileirão | ✅ |
| Nations League, amistosos de selecciones | ✅ |

`remates_jugadores.py` agrega los últimos partidos de un equipo y devuelve, por
jugador: partidos, remates, remates a puerta, goles, medias por partido y
puntería. Ejemplo real (Aston Villa, últimos 10):

| Jugador | PJ | Remates | Rem/PJ | A puerta | AP/PJ | Puntería |
|---|---|---|---|---|---|---|
| Ollie Watkins | 10 | 28 | 2.80 | 15 | 1.50 | 54 % |
| Morgan Rogers | 9 | 21 | 2.33 | 6 | 0.67 | 29 % |
| Ross Barkley | 10 | 11 | 1.10 | 6 | 0.60 | 55 % |

Se muestra en la vista internacional **y** en la de cada liga (antes esa sección
solo existía en la internacional). La tabla estimada se conserva, renombrada a
«Goleadores» y con las columnas marcadas como `(est.)`, para no perder nada.

---

## 5. Cambios en la interfaz de tenis

* **Selector de competición** con los 10 grupos pedidos; solo aparecen las
  categorías que de verdad tienen partidos.
* **Próximos partidos desde ESPN** (10 días, refresco automático cada 20 min).
  Antes solo salían los de hoy que además tuvieran cuota en Betexplorer.
* **Sin botón «Cargar»**: al elegir un partido del calendario, los jugadores, la
  superficie (deducida del torneo), el formato (bo3/bo5 según ESPN) y todas las
  estadísticas aparecen directamente.
* **Parlays combinados + Telegram**, con el mismo componente que fútbol y MLB.
* La cabecera indica la precisión del circuito principal y la de las categorías
  inferiores por separado, y cuántos jugadores cubre el modelo.

---

## 6. Tests de no regresión

| Test | Resultado |
|---|---|
| `test_simetria.py` | ✅ TODO OK |
| `test_match_parlay.py` | ✅ TODO OK |
| `smoke_botones.py` | ✅ TODO OK — **incluidos los botones nuevos de tenis** |

`smoke_botones.py` se amplió: la vista de tenis tenía la lista de botones vacía
porque no tenía ninguno. Ahora pulsa «Proponer parlays» y «Enviar estos parlays»,
que es exactamente el tipo de fallo para el que existe ese test.

Comprobaciones adicionales:

* Coherencia matemática de la plantilla en bo3 **y** bo5: los marcadores exactos
  suman 100 % y coinciden con la probabilidad del ganador.
* 0 patas con cuota < 1.03 en los parlays generados.
* Los pares ambiguos de nombres resuelven bien (10 casos límite de `canonico`).

---

## 7. Lo que NO se hizo, y por qué

* **ITF masculino y UTR Pro Match Series**: sin fuente gratuita. Documentado en
  §1.2 y §1.3. No se inventa cobertura.
* **ELO de saque/resto**: exige aces, dobles faltas y puntos ganados al saque.
  Ninguna fuente accesible los publica desde que desaparecieron los repos de
  Sackmann (ESPN devuelve 404 en `statistics`).
* **Features de nivel de competición**: implementadas y medidas; degradan el ATP
  y son ruido en la WTA (§2.3). Quedan tras `FEATURES_V67` sin activar.
