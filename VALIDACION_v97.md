# VALIDACIÓN v97 — ITF en vivo, KBO y Leagues Cup

**Fecha:** 2026-08-04
**Alcance:** tres competiciones/fuentes NUEVAS. No se toca ningún modelo ya
desplegado (fútbol, MLB, NBA, tenis ATP/WTA): las cinco suites siguen en verde
y el `diff` no entra en `mlb_engine`, `tennis_engine`, `nba_engine` ni en el
pipeline de fútbol salvo para **añadir** una rama de formato y una entrada de
catálogo.

---

## Resumen ejecutivo

| Tarea | Resultado | Estado |
|---|---|---|
| **1. Fuente viva de ITF** | **ENCONTRADA**: BetExplorer. 118 partidos en 3 días, 235 jugadores, ~275/semana, masculino **y** femenino, con fecha explícita | ✅ desplegada |
| **2. KBO** | Fuente **2008-2026** (13.009 juegos) + modelo que **bate al ELO** (+1,02 pp, P(>0)=89,1 %) | ✅ desplegada en **Capa 2** |
| **3. Leagues Cup** | Fuente, fixtures, cuotas y ficha completa. **Ningún modelo bate al ELO** | ✅ desplegada en **Capa 2** (línea base) |

**Lo que NO se consiguió, dicho claro:** el encargo pedía que los dos modelos
nuevos batieran su línea base ELO en walk-forward. La KBO lo hace; **la Leagues
Cup no**. Y ninguna de las dos bate al MERCADO — no se ha demostrado edge de
apuesta en ninguna, porque de ninguna existe histórico gratuito de cuotas de
cierre con el que medir ROI. Las dos entran en modo informativo (Capa 2) y se
dice en la propia interfaz. Detalle y números abajo.

---

## 1. ITF — la fuente viva que faltaba desde la v96

La v96 dejó el circuito ITF con 566.860 partidos de histórico y una limitación
escrita: el espejo `Aneeshers/tennis-sackmann-archive` es un **archivo**, y su
último partido es del **2026-06-01**. Para entrenar da igual; para el estado de
forma de un chico de M15 no, porque en ocho semanas juega quince torneos.

### 1.1 Todo lo que se probó (medido el 2026-08-04)

| Fuente | Resultado | Veredicto |
|---|---|---|
| `itftennis.com` web | **212 bytes**, página anti-bot | ✗ |
| `itftennis.com` API × 4 (`GetCalendar`, `GetLiveScores`, `GetResults`, `GetCompletedTournaments`) | **212 bytes** las cuatro | ✗ |
| **TennisAbstract** | `matchmx` **SÍ existe** en `/jsmatches/{Jugador}.js` | ✗ **por `robots.txt`** |
| Sofascore API | HTTP **403** | ✗ |
| Flashscore | HTTP 200 pero render por JS | ✗ |
| ESPN scoreboard tenis | **0 partidos ITF** (reconfirmado; sí cubre challengers) | ✗ |
| **TennisExplorer** | `robots.txt` permisivo. Cubre **las 11 ITF femeninas** que Pinnacle cotiza hoy… y **0 masculinas** | ✗ media fuente |
| **BetExplorer** | 55 torneos ITF de individuales, hombres **y** mujeres | ✅ **ADOPTADA** |

Dos matices que importan:

- **TennisAbstract se descarta por norma, no por falta de dato.** Su
  `robots.txt` dice literalmente `Disallow: /jsmatches/`, `/jsplayers/`,
  `/jsfrags/`, que es exactamente donde vive `matchmx`. La regla de oro del
  proyecto («sin violar robots.txt») manda sobre la comodidad.
- **TennisExplorer se descarta por cobertura.** Se comprobó con tres consultas
  distintas (`type=all`, `type=atp-single`, `type=wta-single`) y con los slugs
  directos de los 13 torneos ITF masculinos que Pinnacle cotizaba ese día
  (Londrina, Eupen, Fano, Poprad, Frankfurt, Tauste…): **ninguno tiene página
  `atp-men`**. Media fuente no sirve para media plataforma.

### 1.2 Por qué BetExplorer sí

`robots.txt` sólo prohíbe **cadenas de consulta** (`/*?year=`, `/*?month=`,
`/*?page=`, `/*?stage=`…). Las rutas planas que este módulo usa —
`/results/tennis/` y `/tennis/itf-men-singles/{torneo}/` — están permitidas.

Y el HTML trae todo lo necesario, sin JavaScript:

```
data-dt="4,8,2026,9,30"                        ← fecha y hora explícitas
<span class="…--home"><strong>Bar Biryukov P.</strong></span>   ← ganador en <strong>
<td class="table-main__result"><strong>2:1</strong>             ← sets
<td class="table-main__partial">(3:6, 6:2, 6:4)                 ← juegos por set
/tennis/itf-men-singles/m15-astana/bar-biryukov-petr-shebekin-grigory/…
                                    ↑ nombres COMPLETOS (la tabla los abrevia)
```

**Medición de la primera ejecución real:**

| | |
|---|---|
| Partidos ITF terminados | **118** |
| Ventana | **2026-08-02 → 2026-08-04** (el corte del espejo era 2026-06-01) |
| Jugadores distintos | **235** |
| Torneos | **50** |
| Reparto por circuito | 63 masculino · 56 femenino |
| Niveles | M15 (34), M25 (29), W15 (23), W75 (19), W35 (11), W50 (2), W100 (1) |
| Ritmo | **~275 partidos/semana** (criterio de éxito: >10) |

Criterio de éxito del encargo — «≥1 resultado ITF posterior al 2026-06-01»:
**cumplido con 118**.

### 1.3 La fuga de posición, otra vez, y cortada dos veces

La v96 casi despliega un modelo con el ganador siempre en la misma columna
(93,54 % de precisión imposible). Aquí el riesgo es idéntico, así que se mide
en vez de suponerse:

- **BetExplorer coloca al ganador en la primera columna el 41,5 %** de las
  veces (n=118). Está dentro de lo que el azar explica (±4,6 % de error
  típico), pero no es 50 %.
- `acumular_itf.acumular()` **lanza `ValueError` y no escribe el fichero** si el
  reparto se sale de **[40 %, 60 %]** con n≥60. Verificado en test con un lote
  fabricado al 100 %: salta y el CSV no llega a crearse.
- Al cargar al esquema del modelo, el ganador se **reasigna pseudoaleatoriamente
  pero determinista** (semilla fija, ingesta reproducible), igual que en v96 →
  **ATP 56,5 % · WTA 53,6 %**, ya sin relación con la posición de origen.
- **El marcador viaja con la columna.** Primer intento: `Player_1` ganaba y el
  `Score` decía `0-2`. Corregido reexpresando los sets desde el punto de vista
  de `Player_1`; hay test que recorre los 118 partidos y exige coherencia.

### 1.4 Integración

- `acumular_itf.py` — descarga, parseo, guardia y acumulación idempotente en
  `historico_itf_vivo.csv` (commiteado, mismo patrón que `acumular_tenis.py`).
- `tenis_fuentes.historico_unificado()` lo añade **después** del archivo: si un
  partido está en los dos manda el archivo, que trae ranking y superficie.
- `.github/workflows/retrain_leagues.yml` lo ejecuta **a diario**.

### 1.5 Limitación conocida

Queda un **hueco del 2026-06-01 al 2026-08-02** que no se puede rellenar: el
histórico por fechas de BetExplorer va detrás de `?year=`/`?month=`, que su
`robots.txt` prohíbe. Se cierra solo con la acumulación diaria. Para entrenar es
irrelevante (566.860 partidos de archivo); para el estado de forma son ocho
semanas que se recuperan en semanas.

---

## 2. KBO — béisbol coreano

### 2.1 Fuente

| Fuente | Resultado | Veredicto |
|---|---|---|
| `statsapi.mlb.com` | La KBO **está registrada** (`sportId=32`, `leagueId=161`, los 10 equipos con sus ids) pero devuelve **0 juegos** en 2022, 2023, 2024, 2025 y 2026 | ✗ catálogo sin datos |
| ESPN (`kor.1`, `kbo`, `kor.kbo`, `korea.kbo`) | HTTP **400** | ✗ |
| **Naver Sports** (`api-gw.sports.naver.com`) | JSON público, sin clave | ✅ **ADOPTADA** |

`api-gw.sports.naver.com` no publica `robots.txt` (404 = sin restricciones); no
se toca `m.sports.naver.com`, que sí tiene uno restrictivo, ni se parsea su
HTML. Coste: ~220 peticiones una vez, después **una al día**.

**Histórico ingerido:**

| | |
|---|---|
| Juegos | **13.009** |
| Rango | **2008-03-29 → 2026-08-04** (18 temporadas; llega a HOY) |
| Equipos | 10 |
| Abridores | nombre de los dos lados; masivo desde 2020 (2023: 800 de 801) |
| **El local gana** | **52,1 %** ← dentro de [45 %, 62 %] |

Ese 52,1 % es la comprobación que importa: Naver publica un campo
`reversedHomeAway` (su interfaz pinta al visitante a la izquierda) y si
`homeTeamCode`/`awayTeamCode` estuvieran cruzados el fichero saldría igual de
bonito y el modelo aprendería la ventaja de campo **con el signo cambiado**.
`kbo_naver.actualizar()` lanza `ValueError` antes de escribir si se sale de esa
banda.

*Detalle de paginación:* la API corta en 500 juegos por respuesta y una
temporada son ~720 — pedir el año entero devuelve un truncamiento **silencioso**
(medido: 2025 completo → exactamente 500). Se pide mes a mes.

### 2.2 El modelo: el ensemble de la MLB NO servía

Primer intento, reutilizar entero el ensemble de `mlb_engine`. Con un corte
80/20 daba **54,35 %** frente a un ELO de 53,68 % y parecía correcto.

El walk-forward de 5 pliegues lo desmintió (`_v97_wf_kbo.py`):

| | |
|---|---|
| modelo | **0,5426** |
| ELO (línea base) | **0,5452** ← gana el ELO |
| «siempre local» | 0,5240 |
| ventaja modelo−ELO | **−0,27 pp** · bootstrap **p5 −1,31 %** · P(>0)=32,6 % |
| pliegues ganados | **2 de 5** · y peor log-loss que el ELO en **4 de 5** |

Con 10 equipos enfrentándose sin descanso, el ELO ya captura casi todo y el
ensemble sólo añadía varianza. Mismo diagnóstico que la v70 con las ligas de
fútbol pequeñas.

### 2.3 Barrido de familias — elección temprana, juicio tardío

`_v97_familias_kbo.py`: 6 familias, **elegida por log-loss en los pliegues 1-3**,
**juzgada en el 4-5**, que no se miraron para decidir (regla de oro 3).

Elección (pliegues 1-3, log-loss medio):

| familia | log-loss | precisión |
|---|---|---|
| **elo_pitcher_logit** | **0,6844** | 0,5502 |
| base_logit | 0,6850 | 0,5510 |
| elo_logit | 0,6852 | 0,5533 |
| logistica | 0,6857 | 0,5478 |
| ensemble | 0,6887 | 0,5423 |
| gbm_regular | 0,6888 | 0,5434 |

Juicio (pliegues 4-5, **no mirados para elegir**):

| | |
|---|---|
| **elo_pitcher_logit** | **0,5469** · log-loss **0,6862** (la mejor de las 6) |
| ELO (línea base) | 0,5366 |
| **ventaja** | **+1,02 pp** · p5 −0,28 % · mediana +0,99 % · **P(>0) = 89,1 %** |

`base_logit` sacó 0,5508 en el juicio, un pelo más — **y no se adopta**:
quedarse con eso sería elegir por el pliegue de juicio, la trampa que la v90
documentó seis veces. La familia elegida en los pliegues tempranos gana también
el log-loss en los tardíos, que es la coherencia que se buscaba.

**Adoptado:** `elo_pitcher_logit` (DIFF_ELO + diferencial de carreras del
abridor, logística). Reentrenado: **54,63 %** frente a ELO 53,68 %, log-loss
0,6864 (el ensemble daba 0,6902).

### 2.4 Por qué Capa 2 y no Capa 1

Batir al ELO habilita el modelo. **No demuestra un edge de apuesta**, que exige
ROI validado contra cuota de cierre — y de la KBO no existe histórico gratuito
de cierre. Se acumulará con los snapshots diarios, igual que las 11 ligas de
fútbol de la v90. Hasta entonces: informativa, y **dicho en la propia vista**.

### 2.5 Estado en producción hoy

Cuotas: Pinnacle **«Korea Professional Baseball»** (5 partidos, con nombres en
inglés) y Playdoit **«Liga KBO»** (5). Barrido real del 2026-08-04: **5 eventos,
5 evaluados, 3 con abridor anunciado, 0 picks** — las probabilidades ancladas al
mercado no llegan al umbral. Es el sistema no forzando apuestas.

Modelo contra mercado en esos 5 partidos (diferencia de −7,1 a +18,2 pp): el
modelo se separa bastante del precio, que es otra razón para no darle Capa 1
todavía. La ficha aplica el mismo encogimiento hacia el mercado que la MLB.

**El filtro anti-KBO de la v88 en `MLBEngine.apuestas_dia` sigue intacto** — y
debe seguir: son ligas distintas y el edge de la MLB se midió sólo con partidos
de MLB. `KBOEngine` recoge por su cuenta lo que aquel filtro descarta, sin una
sola petición extra.

---

## 3. Leagues Cup

### 3.1 Fuente

ESPN sirve la competición entera en `concacaf.leagues.cup`:

| Edición | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 |
|---|---|---|---|---|---|---|---|---|
| terminados | 7 | 0 | 7 | 0 | **77** | **77** | **62** | 0 (54 por jugar) |

**230 partidos terminados** en total. Cuotas: **cuatro casas** — Pinnacle,
Bovada («North America — Leagues Cup»), Playdoit («Leagues Cup») y DraftKings
vía ESPN. La edición 2026 **arranca hoy**, con 54 partidos y los dos equipos ya
definidos.

### 3.2 El problema real y cómo se resuelve

230 partidos entre 47 equipos son ~5 por equipo: ahí no se entrena nada. Pero
**los equipos no son nuevos** — todos son de la MLS o de la Liga MX, de las que
el proyecto ya tiene **3.719 y 2.660** partidos. Lo que falta no es historia de
los clubes: es la **escala entre las dos ligas**, y eso es justo lo que miden
los 230 cruces.

`leagues_cup.historico()` devuelve las tres fuentes en un solo hilo cronológico:
**6.609 partidos, 52 equipos** (mls 3.719 + liga_mx 2.660 + leagues_cup 230), de
modo que el ELO se calcula sobre el conjunto.

### 3.3 El fallo que casi entra: dos clubes de Nueva York

El emparejamiento difuso de `name_mapper` acertó 46 de los 47 equipos y falló
justo donde más caro sale: mandó **«Red Bull New York» → «New York City»**.
Fundir los historiales de dos clubes distintos de la misma ciudad les habría
dado a ambos un ELO promediado, **y nadie lo habría notado mirando la
precisión**. Con un universo cerrado de 47 equipos la tabla explícita cuesta
media hora y no puede fallar en silencio: `leagues_cup.ALIAS` es manual,
`historico()` avisa de cualquier nombre que no esté, y hay test de regresión.

### 3.3-bis El mismo choque, otra vez, por la puerta de los goleadores

El smoke de la interfaz lo destapó ya con todo montado:

```
[name_mapper] sin mapear: 'Atlanta Utd' (goleadores→leagues_cup)
              — mejor candidato 'Atlante' con 0.67
```

`goleadores._buscar_team_id` mapea en sentido **inverso** (del nombre canónico
del proyecto al de ESPN) y contra un catálogo que sólo tiene los **36
participantes de la edición en curso** — los equipos del histórico que este año
no juegan sencillamente no están. Y cuando el nombre buscado no está, el
emparejamiento difuso **no se queda callado: elige el más parecido**. Medido:

| se busca | el difuso devolvía | debería |
|---|---|---|
| **New York Red Bulls** | **New York City FC** ❌ | no está en el cuadro |
| Atlanta Utd | (0,67, por debajo del umbral → None) | Atlanta United FC |

O sea que los goleadores de un partido habrían salido de **la plantilla de otro
club de la misma ciudad**, sin un solo error por pantalla. En la Leagues Cup el
universo es cerrado (47 equipos) y hay tabla explícita, así que ahí **se quita
el respaldo difuso**: se traduce por la tabla y, si el equipo no está en el
cuadro de este año, se devuelve `None`. Sin goleadores es peor que con
goleadores; con los del rival equivocado es mucho peor que las dos cosas.

Resultado tras el arreglo, sobre los 49 nombres de la tabla: **36 correctos, 13
`None` (no juegan esta edición), 0 incorrectos**. Se añadieron además los 23
alias inversos que faltaban (`Atlanta Utd → Atlanta United FC`, `LAFC`,
`Guadalajara Chivas → Guadalajara`…).

### 3.4 Validación — el modelo NO bate al ELO

Se juzga sólo sobre partidos de Leagues Cup (que es lo que se va a predecir),
por ediciones: entrenar con todo lo anterior, juzgar la edición entera.

| Edición | n | agrupado | solo-LC | ELO |
|---|---|---|---|---|
| 2023 | 77 | 0,3896 | — | **0,4805** |
| 2024 | 77 | **0,4416** | 0,3506 | 0,4026 |
| 2025 | 62 | **0,4839** | 0,4032 | 0,4516 |
| **agregado** | **216** | **0,4352** | **0,3741** | **0,4444** |

- ventaja agrupado−ELO: **−0,93 pp** · bootstrap **p5 −5,56 %** · P(>0)=34,3 %
- **«solo Leagues Cup» es mucho peor (0,3741)**: confirma que agrupar era lo
  correcto, aunque no baste.

**Segunda vuelta, con hipótesis concreta** (`_v97_familias_leagues_cup.py`): el
ELO «agrupado» no lo está de verdad, porque MLS y Liga MX apenas se cruzan y sus
escalas evolucionan en burbujas separadas. Se estimó un **desplazamiento por
liga** con los cruces anteriores a cada corte:

| corte | cruces previos | offset estimado |
|---|---|---|
| 2023 | 14 | **−95** puntos de ELO |
| 2024 | 91 | **+10** |
| 2025 | 168 | **+35** |

Elección en 2023-2024, juicio en 2025:

| | |
|---|---|
| variante elegida (`cruce`) | **0,4516** |
| ELO crudo | **0,4516** → ventaja **+0,0000** (p5 −9,68 %, P(>0)=44,5 %) |
| ELO + offset | **0,4839** → la variante aprendida **pierde** |

**El offset también se RECHAZA**: gana en 2025 pero pierde en 2023 y 2024, y en
el agregado de las tres ediciones da **0,4306 frente a 0,4444 del ELO crudo**.
El 2025 era ruido — con 62 partidos el intervalo del bootstrap es de **±10 pp**.

### 3.5 Qué se despliega, entonces

**La línea base, no un modelo que no aporta.** Familia `elo_logit` registrada en
`modelos_familia.json` con la razón escrita. Sobre el conjunto agrupado (que es
lo que alimenta las predicciones) el entrenamiento da **50,8 % frente a un ELO
de 46,8 %** y un mercado de 51,4 %, log-loss 1,0241 sobre 1.305 partidos de
validación — o sea que **el modelo sí es bueno prediciendo MLS y Liga MX**, que
es de donde sale el nivel de cada club; lo que no está demostrado es que aporte
algo **en el cruce concreto** de la Leagues Cup.

Capa 2, informativa. La ficha sale completa igual que cualquier otra liga:
**13 secciones y 137 campos** (1X2, doble oportunidad, totales, BTTS, hándicap
asiático, marcador exacto, mitades, córners, tarjetas, remates).

Barrido real del 2026-08-04: la Leagues Cup aparece en **pronósticos** con 2
partidos (Columbus Crew vs Atlas, FC Cincinnati vs Pachuca). 42 fixtures en 7
días, **0 sin mapear**.

---

## 3-bis. «El mercado se tiene que batir» — qué se puede y qué no, hoy

El encargo lo pide explícitamente, así que conviene ser preciso sobre por qué
hoy no se puede afirmar y qué se ha puesto en marcha para poder afirmarlo.

**Batir al mercado no se demuestra con precisión, se demuestra con ROI contra
la cuota de cierre.** Es la disciplina del proyecto desde la v13 y la razón por
la que la v90 rechazó seis palancas del 1X2 que «parecían» mejores. Para
medirlo hace falta una serie de cierres históricos, y de la KBO y de la Leagues
Cup **no existe ninguna gratuita**: ni football-data, ni
sportsbookreviewsonline, ni BetExplorer en la superficie que su `robots.txt`
permite. Afirmar hoy un edge sería inventarlo.

**Lo que sí se ha hecho es arrancar el reloj.** La única vía a esa serie es
guardarla desde hoy, que es exactamente lo que la v90 dejó en marcha para las
11 ligas sin cuotas (n≈300 por liga en ~4 meses):

- **Leagues Cup**: entra sola en `daily_snapshots.capturar()` por estar
  `disponible` y tener código ESPN. Primera captura real: **70 filas de 42
  partidos con CUATRO casas** — Pinnacle (18), Bovada (18), Playdoit (18) y
  DraftKings (16). Son más de las dos que se vieron en el primer sondeo del
  tablón, y cuatro precios sobre el mismo partido es justo lo que el canal de
  line shopping necesita.
- **KBO**: **no entraba**, porque `capturar()` recorre el catálogo de fútbol.
  Sin fotos no hay cierre, sin cierre no hay ROI y sin ROI la competición no
  puede salir de Capa 2 **por mucho que mejorase su modelo**. Nuevo
  `daily_snapshots.capturar_kbo()`, con el mismo almacén y la misma clave de
  foto, así que `clv_tracker`, `monitor_canales` y el exportador a CSV lo ven
  sin cambios. Primera ejecución real: **10 filas, 5 partidos, 2 casas cada
  uno**.

Y ya en esa primera foto se ve el material del canal que **sí** está validado
(line shopping, v90: n=643, ROI +8,57 %, p5 +1,07 %):

| partido | Pinnacle | Playdoit | diferencia |
|---|---|---|---|
| Doosan Bears (local) | 2,29 | **2,40** | **+4,8 %** |
| SSG Landers (local) | **2,26** | 2,25 | +0,4 % |
| Lotte Giants (local) | **1,9524** | 1,9091 | +2,3 % |

Un 4,8 % de diferencia entre dos casas sobre el mismo lado es precisamente lo
que ese canal explota, y **no necesita que el modelo acierte**. Lo que no se
hace todavía es operarlo: el edge del line shopping se midió en fútbol y el de
`valor_vs_sharp` en MLB sobre 27.977 juegos, y la propia v88 dejó escrito que
«operar otras ligas con él es extrapolar». Con las fotos acumulando, en unos
meses habrá muestra para medirlo **en la KBO** en vez de suponerlo.

---

## 4. Lo que se rechazó, con números

| Propuesta | Medición | Veredicto |
|---|---|---|
| Ensemble de MLB para la KBO | 0,5426 vs ELO 0,5452; p5 −1,31 %; 2/5 pliegues | ✗ |
| `base_logit` para la KBO | 0,5508 en el juicio, pero elegirla sería usar el pliegue de juicio | ✗ |
| Modelo propio de Leagues Cup (solo 230 partidos) | **0,3741** vs ELO 0,4444 | ✗ |
| Modelo agrupado para Leagues Cup | 0,4352 vs ELO 0,4444; p5 −5,56 % | ✗ |
| Offset de escala entre MLS y Liga MX | agregado 0,4306 vs 0,4444; sólo gana en 2025 (n=62, ±10 pp) | ✗ |
| TennisAbstract como fuente ITF | tiene el dato, pero `Disallow: /jsmatches/` | ✗ por norma |
| TennisExplorer como fuente ITF | 11/11 torneos femeninos, **0 masculinos** | ✗ media fuente |
| `statsapi.mlb.com` para KBO | liga registrada, **0 juegos** en 5 temporadas | ✗ |

---

## 5. Hallazgo abierto (regla de oro 6)

El test nuevo de `robots.txt` que se escribió para la tarea de ITF **encontró
una infracción preexistente y ajena a esta versión**:

> `tenis_saque.py:88` pide
> `https://www.tennisabstract.com/jsplayers/curr_rank_{circuito}.js`,
> y el `robots.txt` de tennisabstract.com incluye `Disallow: /jsplayers/`.

Viene de la v69 y alimenta el ranking del motor de tenis, que funciona. Esta
versión **no lo toca** (el encargo es explícito: no modificar lo que ya
funciona), pero queda anotado aquí con su localización exacta para decidirlo
por separado. La alternativa natural es el ranking que ya trae el histórico
unificado.

---

## 6. Tests

Cinco suites en **TODO OK**. Nuevas comprobaciones en
`test_catalogo_y_cuotas.py` (27 asserts) y dos vistas más en `smoke_botones.py`:

- ITF: el medidor detecta el 100 % de ganadores en una columna · la guardia
  **lanza `ValueError` y no escribe el fichero** · marcador coherente con el
  ganador en los 118 partidos · el ganador se reparte (56,5 % / 53,6 %) · **no
  se piden las rutas que `robots.txt` prohíbe** (sobre el AST, no sobre el
  texto: el docstring las cita para explicar por qué no se usan).
- KBO: umbral declarado · 10 equipos sin colisiones · 13.009 juegos · **local y
  visitante no cruzados (52,1 %)** · fuente al día · **un partido de KBO no se
  cuela como MLB y viceversa** · el dataset no etiqueta empates como derrota
  local.
- Leagues Cup: en el catálogo y en Capa 2 · código ESPN presente · **«Red Bull
  New York» ≠ «New York City»** · alias sin colisiones y presentes en
  `alias_manuales.json` · histórico agrupado (6.609, no 230).
- Genérico nuevo: **todo formato del catálogo tiene rama en `descargar_liga`**
  (sin esto, añadir un formato y olvidar la rama no falla hasta el
  reentrenamiento nocturno, que es donde peor se ve).

---

## 7. Autonomía

- `retrain_leagues.yml` (diario): entrena **KBO** junto a MLB/tenis/NBA, con el
  mismo blindaje (si el modelo no vuelve a cargar se restaura el anterior), y
  ejecuta **`acumular_itf.py`**. La Leagues Cup entra sola en
  `league_engine --build` por estar `disponible` en el catálogo.
- `recalibrar.yml` (semanal): sigue trayendo el archivo de ITF.
- Los ficheros nuevos (`historico_kbo.csv`, `historico_itf_vivo.csv`,
  `historico_leagues_cup.csv`, `modelos/kbo/`, `modelos/leagues_cup/`) los
  recogen los `git add` ya existentes y ninguno está en `.gitignore`.
