# v106 — El hándicap, la hora de CDMX, el EV+ multideporte y el béisbol

Cinco frentes, todos pedidos por el usuario. El primero es un **bug de
producción con impacto medido**; los otros cuatro son funcionalidad que faltaba
o que existía y no se enseñaba.

---

## 1. El hándicap asiático regalaba el push — CORREGIDO Y MEDIDO

### El síntoma

> «Ahorita lo que he visto que falla mucho es el hándicap, casi no confío en el
> hándicap porque me ha fallado constantemente.»

### La causa, exacta

`alpha_finder._mercados_del_partido` evaluaba así:

```python
if linea is not None and abs(linea * 2 - round(linea * 2)) < 1e-6:
    p_home_cubre = float(M[diff > -linea].sum())
    _add('Hándicap', etq_h, p_home_cubre,     o.get('odd_ah_home'))
    _add('Hándicap', etq_a, 1 - p_home_cubre, o.get('odd_ah_away'))
```

El comentario justo encima decía «líneas .5 → sin push». La **condición escrita
no dice eso**: `abs(L*2 − round(L*2)) < 1e-6` es verdadera para 0,5 **y para
1,0, 2,0 y 0,0**. Con línea entera:

| resultado | quién cobra |
|---|---|
| el local gana por 2+ | cubre el local |
| el local gana por 1 **exacto** | **PUSH — la casa devuelve el importe** |
| empate o gana el visitante | cubre el visitante |

`1 − P(local cubre)` mete el push entero en el lado visitante. No es un
redondeo: es la masa de «gana el favorito por exactamente un gol», el resultado
más frecuente del fútbol.

### El tamaño del error

Reconstruido el ledger sobre **47.794 partidos fuera de muestra**:

| línea del local | push | n resuelto |
|---|---|---|
| −2,0 | 5.827 | 41.967 |
| **−1,0** | **10.966 (23 %)** | 36.828 |
| 0,0 | 12.595 | 35.199 |
| +1,0 | 8.206 | 39.588 |
| +2,0 | 3.618 | 44.176 |

Sobre la matriz de un favorito típico (λ 1,75 / 1,05), línea −1,0:

| | local | visitante |
|---|---|---|
| método v65 | 0,2876 | **0,7124** |
| real (condicional) | 0,3834 | **0,6166** |

**+9,6 puntos de inflación** en el lado que se recomendaba. Con esa
probabilidad, `cuota × prob − 1` sale positivo casi siempre.

### Por qué no lo cazó la medición

`build_ledger_handicap.py` tenía `LINEAS = (-2.5, -1.5, -0.5, 0.5, 1.5, 2.5)`
con el comentario «las que evalúa `alpha_finder`». **Falso**: eran las que
*debería* haber evaluado. Al medir sólo las .5 —las únicas sin push— el
hándicap figuraba como el mercado mejor calibrado del proyecto mientras en
producción publicaba el lado contrario inflado 20-25 puntos.

Lección: cuando un test dice «esto es lo que hace producción», hay que
comprobarlo contra el código, no contra el comentario del código.

### La corrección

`handicap.py` (módulo nuevo, puro, sin dependencias de la app). Toda apuesta
asiática se descompone en **(gana, pierde, push)** y de ahí salen las tres
cifras:

```
prob. de ganar = gana / (gana + pierde)        ← condicional: el push no cuenta
cuota justa    = 1 / esa probabilidad
EV             = gana·(cuota − 1) − pierde     ← la única correcta con push
```

`cuota × prob − 1` sobreestima el EV exactamente en `1/(gana+pierde)`: con la
línea −1,0 del ejemplo, un factor de **1,33**.

Además:

- **Líneas de cuarto** (−0,25, −0,75, −1,25…): se descartaban enteras siendo
  las que más publica Pinnacle, que es justo el ancla del sistema. Ahora se
  tratan como lo que son: media apuesta en cada línea de 0,5 adyacente.
- **Anclaje al mercado.** Desde la v71 el 1X2 se encoge hacia el mercado para
  corregir la maldición del ganador (+4 a +13 pp según liga). El hándicap salía
  de la matriz **cruda** y arrastraba el sesgo entero. Ahora la distribución de
  margen se re-pondera a las probabilidades ya corregidas — es la misma
  operación con la que nace la matriz (`prediction_api._monte_carlo`) y con la
  que se validó el hándicap (`build_ledger_handicap.matriz_marcadores`), no un
  método nuevo.

### Resultado, sobre las 19 líneas que producción evalúa de verdad

| línea | predicho | real | sesgo | n | push |
|---|---|---|---|---|---|
| −2,50 | 0,090 | 0,094 | −0,004 | 47.794 | 0 |
| −2,00 | 0,103 | 0,107 | −0,004 | 41.967 | 5.827 |
| −1,75 | 0,163 | 0,165 | −0,002 | 47.794 | 0 |
| −1,50 | 0,215 | 0,216 | −0,000 | 47.794 | 0 |
| −1,25 | 0,242 | 0,244 | −0,002 | 47.794 | 0 |
| −1,00 | 0,276 | 0,280 | −0,004 | 36.828 | 10.966 |
| −0,75 | 0,373 | 0,373 | −0,000 | 47.794 | 0 |
| −0,50 | 0,446 | 0,445 | +0,001 | 47.794 | 0 |
| −0,25 | 0,514 | 0,513 | +0,001 | 47.794 | 0 |
| 0,00 | 0,607 | 0,604 | +0,003 | 35.199 | 12.595 |
| +0,25 | 0,667 | 0,664 | +0,002 | 47.794 | 0 |
| +0,50 | 0,710 | 0,709 | +0,001 | 47.794 | 0 |
| +0,75 | 0,777 | 0,775 | +0,002 | 47.794 | 0 |
| +1,00 | 0,859 | 0,856 | +0,003 | 39.588 | 8.206 |
| +1,25 | 0,872 | 0,869 | +0,003 | 47.794 | 0 |
| +1,50 | 0,882 | 0,880 | +0,002 | 47.794 | 0 |
| +1,75 | 0,917 | 0,915 | +0,002 | 47.794 | 0 |
| +2,00 | 0,955 | 0,952 | +0,003 | 44.176 | 3.618 |
| +2,50 | 0,959 | 0,956 | +0,003 | 47.794 | 0 |

**Peor sesgo: 0,004.** Las líneas .5 no se mueven ni un 1e-9 respecto a la v87
(comprobado en el test): la corrección no toca lo que ya estaba bien.

Un detalle que costó una iteración: en las **líneas de cuarto** la media hay que
ponderarla por el importe que realmente se arriesga. Sin el peso, −1,75 salía
con un sesgo aparente de −0,051 que no existía — mezclaba apuestas de importe
entero con apuestas a medias. Por eso el ledger guarda ahora también
`res_ah_*`, la fracción resuelta.

### Y la calibración ya no cuenta un push como acierto

`calibracion_confianza` hacía `h[real].values.astype(bool)`. **`np.nan`
convertido a bool es `True`**: con el ledger ampliado, los 10.966 push de la
línea −1,0 habrían entrado como aciertos y la tabla habría quedado optimista
justo en el mercado que se estaba arreglando. Ahora se descartan los push y se
exige importe entero.

Bandas resultantes (Hándicap, 6 de 6 con muestra, **peor sesgo 0,018**, y en
dirección conservadora — el modelo promete menos de lo que entrega):

| banda | n | modelo | real | sesgo |
|---|---|---|---|---|
| 0,50-0,55 | 50.227 | 0,525 | 0,529 | −0,004 |
| 0,55-0,60 | 50.741 | 0,575 | 0,588 | −0,013 |
| 0,60-0,65 | 51.847 | 0,625 | 0,643 | −0,018 |
| 0,65-0,70 | 55.564 | 0,675 | 0,693 | −0,018 |
| 0,70-0,75 | 61.088 | 0,726 | 0,740 | −0,015 |
| 0,75-1,01 | 524.428 | 0,896 | 0,897 | −0,001 |

---

## 2. El hándicap existía en 20 ligas de 57 — ahora en todas las que lo cotizan

### Lo que se midió

| artefacto | ligas activas con él |
|---|---|
| histórico | 57 / 57 |
| `team_stats` | 57 / 57 |
| modelo entrenado | 45 / 57 |
| backtest 1X2 (`roi_bets_*`) | 35 / 57 |
| **backtest de hándicap (`roi_bets_ah_*`)** | **20 / 57** |

Las 20 son **exactamente** las de formato `main` (football-data `/mmz4281/`),
las únicas cuyo CSV trae columnas asiáticas (`AHCh`, `AvgCAHH`, `AvgCAHA`).
**Liga MX no está entre ellas.** Ni las 21 que sólo cubre ESPN, ni las 14 de
formato `new`.

### Y no era falta de tiempo: el dato no se guardaba

Dos agujeros, los dos con la solución delante:

1. **El scoreboard de ESPN traía el hándicap y nadie lo leía.**
   `_odds_de_evento` extraía moneyline y over/under del bloque `odds`, pero
   ignoraba `pointSpread` — que está en el **mismo JSON ya descargado**. Sondeo
   del 2026-08-08 sobre `mex.1`, `usa.1`, `bra.1`, `arg.1` y `eng.1`:
   **33 de 33** partidos con cuotas lo publicaban. El hándicap sólo llegaba por
   el core API, que es una petición **por partido** y no se hace para todas las
   ligas.

2. **`daily_snapshots` nunca lo fotografiaba.** Guardaba 1X2, totales y BTTS.
   `odds_store` tiene `ah_linea`, `odds_ah_home` y `odds_ah_away` **desde la
   v75**, vacías. Es el mismo razonamiento con el que la v75 empezó a guardar
   BTTS: si no se empieza hoy, dentro de un año sigue sin haber histórico.

### Resultado, medido en vivo

Sobre los fixtures de 7 días de las 56 ligas con código ESPN:

```
fixtures totales: 709 · con 1X2: 438 · CON HÁNDICAP: 325
ligas con al menos un hándicap: 43 de 52
```

Y con **line shopping**, que antes era imposible en este mercado:

```
[liga_mx] Atlante vs Toluca:
   DraftKings {linea: +1.5,  home 1.571, away 2.15}
   Pinnacle   {linea: +1.25, home 1.833, away 2.03}
[brasil]  Grêmio vs São Paulo:
   DraftKings {linea: -0.5,  home 2.30,  away 1.556}
   Pinnacle   {linea: -0.25, home 2.07,  away 1.833}
```

Las líneas de cuarto de Pinnacle son precisamente las que la v65 tiraba.

Las 9 ligas que siguen a cero (Serie B italiana, Conference League, Grecia…)
son una limitación real del mercado: ninguna casa del panel las cotiza a
hándicap. Se dice, no se rellena.

### La foto diaria ya lo persiste — comprobado de punta a punta

Ejecutado `daily_snapshots.capturar()` contra la base real:

```
fotos con hándicap: 328 filas en 29 competiciones
  DraftKings (vía ESPN)  170
  Pinnacle               158
```

328 filas en un solo día donde antes había **cero**, y de dos casas a la vez —
que es lo que permitirá medir el mercado y comparar precios cuando haya
muestra.

### Y una trampa que apareció justo al empezar a usar la columna

La primera cuenta dio **10.158 filas con hándicap en 52 competiciones**, que
era demasiado bueno. Lo era: `importar_snapshots` recarga el CSV con
`csv.DictReader`, que devuelve `''` para toda celda vacía. Las cuotas ya se
saneaban en `odds_store._limpiar`, pero `ah_linea` no, así que **17.202 filas
antiguas guardaban la cadena vacía en una columna REAL** — y
`WHERE ah_linea IS NOT NULL` las cuenta como si tuvieran línea.

Mientras la columna no se usaba, daba igual. Desde esta versión no: el primer
backtest de hándicap sobre las fotos habría arrancado con 17.000 filas
fantasma, que es exactamente la contaminación silenciosa que ese módulo existe
para impedir. Saneado en `_limpiar` (donde ya estaba el resto, para que ningún
importador futuro pueda saltárselo), limpiadas las 17.202 y fijado con un test
que exige cero.

---

## 3. La hora de los partidos, en hora de Ciudad de México

El dato ya se capturaba —`inicio`, en UTC, desde la v88— y **no llegaba a
pantalla**. Ahora sale en:

- las tarjetas de Apuestas del Día, con «empieza en 2 h 15 min» al lado,
- los selectores de próximos partidos de **todos** los deportes,
- el panel de EV+ de MLB, NBA, KBO y tenis,
- el mensaje de Telegram,
- las exportaciones a texto y CSV (columnas nuevas al final, para no romper a
  quien ya lea el CSV por posición).

### Lo que este cambio NO hace, a propósito

El proyecto razona en **UTC de punta a punta** porque mezclar relojes ya costó
un día entero de partidos descartados (v91) y un test lo vigila
(`test_un_solo_reloj`). `horario.py` es **exclusivamente de presentación**: la
anotación se hace en el borde de salida del barrido y los campos `fecha` e
`inicio` que usa la lógica quedan intactos.

### El detalle que importa: la fecha también cambia

CDMX va 6 horas por detrás de UTC, así que un partido de las **01:00 UTC del
sábado** se juega el **viernes a las 19:00** en México. Enseñar la hora local
junto a la fecha UTC sería peor que no enseñar nada, así que se muestran las
dos y la tarjeta escribe la fecha local cuando difiere.

La zona sale de la base de datos de zonas (`America/Mexico_City`), no de un
`UTC−6` escrito a mano: México eliminó el horario de verano en 2022, pero la
base sabe qué pasó antes y se actualizará sola si la regla vuelve a cambiar. Se
declara `tzdata` en `requirements.txt` porque en Windows `zoneinfo` no trae base
propia; sin ella el módulo cae a −6 fijo **y lo dice en el log**.

---

## 4. EV+ automático en los cuatro deportes

> «En deportes que no son fútbol no tienes la opción de EV+ automático, y ese
> me ayuda mucho a ver qué apostar casi casi en vivo antes de iniciar.»

Cierto a medias, y por eso costaba verlo: `alpha_finder` **ya** calculaba picks
con cuota y EV de MLB, NBA, KBO y tenis —están en «Apuestas del Día»— pero la
vista propia de cada deporte no los enseñaba. Sólo la MLB tenía su pestaña; los
otros tres obligaban a salir a la pantalla general y buscar entre todos los
deportes.

Ahora hay **un solo panel** (`render_ev_automatico`) en las cuatro vistas, con
la misma lógica, los mismos filtros y las mismas fuentes. Cambios de paso:

- la **MLB gana la Capa 2** que su motor calculaba desde la v91 y su pestaña
  tiraba (favoritos claros con cuota real que no pasan los filtros de élite),
- el pie de la **NBA** decía «sin EV real hasta que The Odds API reactive la NBA
  en octubre»: esa API se retiró en la v88 y desde entonces las cuotas salen de
  Pinnacle y Bovada. El EV existía; faltaba enseñarlo.
- la **KBO** sigue marcada como lo que es: su modelo bate al ELO pero **no al
  mercado** (medido sobre 204 cierres reales), así que sus picks con valor
  vienen de la diferencia entre casas, no del modelo.

---

## 4-bis. Dos motores que no cargaban, y uno de ellos tampoco en producción

Cablear el EV+ de cada deporte destapó por qué esos paneles decían «motor no
disponible». Eran dos fallos distintos, los dos escondidos detrás de que la NBA
está fuera de temporada y de que el desarrollo local no se probaba.

### MLB, ATP y WTA — `XGBoostError: input stream corrupted`

Es el fallo que la **v87 ya había diagnosticado y resuelto**: el pickle guarda
el formato de SERIALIZACIÓN de XGBoost, que la propia documentación declara
dependiente del entorno, así que un modelo entrenado en el runner de Linux no
abre en Windows con la misma versión de la librería. Para eso se escribió
`modelos_portables.cargar`.

Y se cableó **sólo en `ClubEngine`** (fútbol). `BaseSportsEngine` —del que
cuelgan MLB, tenis, NBA y KBO— se quedó con `joblib.load` a secas. En Streamlit
Cloud no se nota porque corre en Linux, igual que el runner; en Windows los tres
motores están caídos, lo que significa que **el proyecto no se puede depurar en
local** y que el smoke de botones no puede probar esas vistas (cargan, ven el
motor caído y salen por el `st.error`, así que pasan en verde sin probar nada).

Una línea: usar el cargador que ya existía.

### NBA — `Can't get attribute '_BlendEloNBA' on <module '__main__'>`

Éste **no es de plataforma y rompía también en producción**. El entrenamiento se
lanza con `python -m engines.nba_engine` —así lo hace el workflow diario—, y en
esa ejecución el fichero ES `__main__`. Pickle guarda las clases por su módulo,
de modo que el artefacto publicado apunta a `__main__._BlendEloNBA`. Al cargarlo
desde la app, `__main__` es Streamlit y allí esa clase no existe: **el modelo de
NBA no se podía abrir desde ningún sitio**, ni en Linux ni en Windows.

Arreglado por los dos lados, porque uno solo no basta:

* se registra la clase en `__main__` antes de deserializar, lo que repara el
  artefacto **ya publicado** sin reentrenar (el reentrenamiento depende de
  `nba_api`, que fuera de temporada no aporta nada nuevo);
* y el bloque `__main__` reimporta la clase del paquete, para que el próximo
  entrenamiento la serialice como `engines.nba_engine._BlendEloNBA`. Sin esto,
  el parche de compatibilidad taparía el problema para siempre en vez de
  resolverlo.

### Estado tras el arreglo

```
MLB   listo=True   30 equipos
ATP   listo=True   13.031 jugadores
WTA   listo=True   14.332 jugadores
KBO   listo=True   10 equipos
NBA   listo=True   30 equipos · predice (prob local 0,833 · total 225,9)
```

Los cinco. Y con ellos, el smoke de botones pasa por fin por las vistas de MLB y
de tenis en vez de rebotar en su mensaje de error.

## 5. Béisbol: abridor, estadio y ponches

La regla de decisión que pidió el usuario, implementada tal cual:

1. Favorito del casino con **buen abridor** y cuota de ganador ≥ 1.50 →
   **ganador**.
2. Si no, la **línea de ponches del mejor abridor** —aunque sea el del equipo
   que el casino pone en positivo— y si pide **más de 6**, no se toca:
   **run line** al equipo de ese lanzador.
3. Línea de 6 o menos y precio que pague → **ponches**.
4. Si no se cumple nada → **el partido no entra en la parlay**.

### Todo automático, y de fuentes que ya se usaban

| dato | fuente | coste |
|---|---|---|
| abridores probables | MLB Stats API oficial | ya se usaba para entrenar |
| calidad del abridor | `mlb_pitchers_temporada.csv.gz` (misma API) | ya se descargaba |
| **factor del parque** | **medido de `historico_mlb.csv`** | cero |
| **línea de ponches + cuota** | **Pinnacle, `withSpecials=true`** | **cero peticiones nuevas** |

Los props de ponches salen del **mismo endpoint** que el proyecto ya consulta
para los moneyline de béisbol: Pinnacle los publica como matchups «special» con
`parent` apuntando al partido. Medido el 2026-08-08: **30 props en 28
partidos**, con línea y precio Over/Under.

### El factor de parque se mide, no se escribe

Carreras por juego **en casa** frente a las de **ese mismo equipo como
visitante**, últimas 5 temporadas, encogido hacia 1 por tamaño de muestra.
Compararlo contra sí mismo cancela lo bueno o malo que sea el equipo; lo que
queda es el estadio.

Cordura del resultado (30 estadios, 2022-2026):

| más de bateadores | | más de lanzadores | |
|---|---|---|---|
| COL (Coors) | **×1,284** | SEA | ×0,853 |
| PHI | ×1,065 | SDN | ×0,900 |
| BOS | ×1,061 | SFN | ×0,929 |

Coors Field el más alto de la liga y por un margen enorme; Seattle, San Diego y
San Francisco al fondo. Es exactamente lo que tiene que salir, y salió de los
datos.

### La calidad del abridor: FIP con corte relativo

**FIP** mide sólo lo que depende del lanzador (ponches, bases por bolas,
jonrones), así que no arrastra la defensa ni el parque — que aquí se tratan
aparte, cada uno en su sitio. El corte de «bueno» es el **mejor tercio de los
abridores de su temporada**, no un número absoluto: un FIP de 3,80 no significa
lo mismo en 2019 que en 2026.

### Un error de signo cazado antes de publicarlo

Pinnacle indexa cada precio de hándicap por **su propia línea**, no por la del
local:

```json
[{"designation":"home","points": 1.5,"price":-154},
 {"designation":"away","points":-1.5,"price": 133}]
```

«Darle la vuelta para el visitante» —que parecía lo natural— convertía un
**+1.5 en un −1.5**: proponía que ganara por 2 el equipo al que había que
recibirle ventaja. Verificado contra 27 partidos del tablón y fijado con un test
que comprueba el signo **contra quién es el favorito**, no contra un valor
escrito a mano.

### Honestidad sobre lo que esto es

La regla 1-4 es **del usuario**, no una estrategia medida contra el histórico
del proyecto. Se aplica tal cual la pidió, cada veredicto viaja marcado con
`regla_del_usuario=True`, y al lado va el **EV que el modelo calcula por su
cuenta** para que las dos lecturas se vean juntas y ninguna se disfrace de la
otra. Estos picks **no entran en la Capa 1** por esta vía.

Ejecución en vivo del 2026-08-08 (8 partidos): 4 entran — 3 como ganador
(Chris Sale, Andrew Alvarez y Clay Holmes abriendo para el favorito) y 1 como
run line (Taj Bradley con línea de ponches en 6,5, por encima del corte).

---

## Estado de la validación

`test_catalogo_y_cuotas.py`: **464 comprobaciones, 0 fallos.** Partía de 353
antes de esta versión.

Los **seis tests nuevos** son `test_handicap_con_push`, `test_hora_cdmx`,
`test_ev_automatico_en_todos_los_deportes`, `test_motores_de_deporte_cargan`,
`test_beisbol_pitchers` y `test_handicap_en_todas_las_ligas`. Cada uno fija un
fallo que se encontró con datos reales en esta sesión, no una hipótesis.

También en verde:

| prueba | qué cubre |
|---|---|
| `test_match_parlay.py` | combinador de parlays |
| `test_simetria.py` | simetría local/visitante del Mundial |
| `smoke_botones.py` | las 7 vistas cargan y sus botones se pulsan |

### Dos cosas sobre el entorno, para que no se malinterpreten

1. **La primera pasada dio dos fallos de clon limpio**, no regresiones:
   `odds_historico.db` está en `.gitignore` (49 MB) y se regenera con
   `import_historical_odds.py` (**137.081 filas en 36 ligas**) y
   `backfill_betexplorer.py` (**7.779 cuotas en 22 competiciones**). Con la
   base reconstruida, los dos pasan.

2. **El smoke de botones estaba pasando sin probar dos vistas.** `at.button`
   sólo devolvía los botones del nivel superior, así que la vista de MLB salía
   con «0 botones» y sus «no encontrado (¿condicional?)» parecían normales.
   Ahora recorre pestañas y desplegables, y con los motores arreglados
   (§4-bis) MLB y tenis pasan de 0 a **6 botones cada una**, pulsados de
   verdad. Se pulsa **un** botón de refresco por vista a propósito: cada uno
   vacía la caché y relanza el barrido del deporte, y pulsarlos todos llevaba
   el smoke de minutos a más de veinte.
