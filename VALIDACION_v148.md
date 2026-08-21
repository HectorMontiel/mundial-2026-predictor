# VALIDACIÓN v148 — el curso que no estaba, el barrido que no espera y los pesos fuera de git

Fecha: 2026-08-21

Tres encargos en una tanda. Los tres se midieron antes de tocar nada, porque en
este proyecto dos diagnósticos «evidentes» ya salieron equivocados y sólo la
medición lo vio.

---

## PARTE 2 — «sin pronóstico del modelo» en Premier, LaLiga, Ligue 1/2 y Primeira

### La medición de partida

Barrido real del 2026-08-21 sobre las 49 competiciones con fixtures en ESPN:

```
fixtures en ventana (3 días)   326
con pronóstico                 291
SIN pronóstico                  35     (10,7 %)
competiciones sin motor          0
```

Las 35 no estaban repartidas al azar. Sacando los nombres que no casaban:

```
laliga           Athletic Club · Atlético Madrid · Deportivo · Málaga · Racing Santander
premier          Coventry City · Hull City
ligue_1          Le Mans · Stade Rennais
fra_ligue2       Nantes
primeira         Sporting CP · Académico de Viseu
esp_hypermotion  Mallorca · Real Sociedad II · RC Celta Fortuna · CD Sabadell · Sporting Gijón
turquia          Istanbul Basaksehir · Amed SFK · Erzurum BB · Çorum FK
…
```

### La causa raíz

No era el modelo, ni el desacople de la v147, ni los `.joblib`. Era **una tupla
literal**.

```python
'urls': [f'{FD_BASE}/mmz4281/{s}/E0.csv'
         for s in ('1011', …, '2425', '2526')],
```

Veinte competiciones declaraban su lista de temporadas a mano y **todas
terminaban en `'2526'`**. El 21 de agosto de 2026 la temporada 2026-27 llevaba
una semana jugándose y no estaba en la configuración. Consecuencias en cadena:

1. football-data nunca se descargaba para el curso en marcha.
2. Los ascendidos no existían en ningún sitio del catálogo del modelo.
3. `name_mapper` no podía casarlos contra nada.
4. El partido salía «sin pronóstico del modelo».

Y había un segundo cerrojo, éste **estructural**: `_completar_desde_espn` —la
cola que rellena lo que football-data aún no ha publicado— mapea los nombres
**contra el catálogo del propio histórico**. Un equipo recién ascendido nunca
está en ese catálogo por definición, así que `_map` devolvía `None` y la fila se
descartaba. La cola de ESPN era incapaz de incorporar a un ascendido.

Prueba directa: `historico_premier.csv` terminaba el **2026-05-24**, la última
jornada del curso anterior. Cero partidos de la temporada en curso.

### El arreglo

**1. La lista de temporadas se deriva de la fecha** (`temporadas_fd.py`, módulo
nuevo). Una temporada de football-data se llama `AABB` y arranca en julio; a
partir del 1 de julio la vigente es la del año en curso. Se sustituyeron las
**11 declaraciones literales** (9 en `config.py`, 2 en `config_ligas_espn.py`) y
se corrigió `generar_ligas_v68.py`, que era quien las congelaba al generar el
catálogo. Verificado:

```
temporada_fd_vigente()                 -> 2627
temporada_fd_vigente(2027-06-30)       -> 2627
temporada_fd_vigente(2027-07-01)       -> 2728
ligas football-data sin la vigente     -> NINGUNA (de 20)
```

**2. Una temporada que aún no existe no puede tumbar el entrenamiento.** Sondeo
de los veinte códigos el 2026-08-21:

```
2627 publicado      14   SP1 F2 P1 N1 T1 SP2 D2 B1 E1 E2 E3 EC SC0 SC1
2627 NO publicado    6   E0 I1 I2 D1 F1 G1   (su liga arrancaba días después)
```

El detalle que obligaba a validar el **contenido** y no sólo el código: cuando
el fichero no existe, football-data devuelve **300 Multiple Choices con una
página HTML**, no un 404. `raise_for_status()` no levanta nada ante un 300 y
`read_csv(..., on_bad_lines='skip')` se traga el HTML: el marco sale con
columnas inventadas y la línea siguiente (`crudo['Date']`) revienta con
`KeyError`, dejando la liga sin reentrenar sin que nadie sepa por qué.

`_csv_temporada` valida código, cabecera HTML y presencia de columnas de
partidos. Distingue **«no publicada todavía»** (se salta con aviso) de **fallo
de red** (5xx, timeout → levanta): entrenar en silencio con menos historia de la
debida por un corte pasajero es peor que no entrenar.

Comprobado en el reentrenamiento real:

```
[ligue_1] temporadas aún no publicadas por football-data: 2627 (se entrena con las 16 que sí están)
[premier] temporadas aún no publicadas por football-data: 2627 (se entrena con las 16 que sí están)
[laliga]  6086 partidos reales (2010-08-28 → 2026-08-20)   ← antes 2026-05-24
```

**3. La cola de ESPN puede dar de alta a un ascendido.** `name_mapper` gana
`mejor_candidato(nombre, catálogo)`, que devuelve el parecido **sin decidir**.
Con eso se separan dos cosas que antes se confundían en el mismo `None`:

| ratio | qué es | qué se hace |
|---|---|---|
| ≥ 0,62 | el mismo club escrito de otra forma (`Sporting Gijón` / `Sp Gijon` = 0,71) | se descarta y se registra: falta un alias |
| < 0,62 | un club que de verdad no estaba | se da de alta |

El motivo original del descarte sigue vigente y no se toca: dar de alta un
nombre parecido **parte el historial de un club en dos**, que es peor que perder
un partido. Ante la duda, no se da de alta.

**4. Alias que faltaban** (31 nuevos en `alias_manuales.json`). Todos son huecos
de abreviatura, no de tildes —`normalizar()` ya quita tildes—:

```
Athletic Club       -> Ath Bilbao      Sporting CP         -> Sp Lisbon
Atlético Madrid     -> Ath Madrid      Stade Rennais       -> Rennes
Urawa Red Diamonds  -> Urawa Reds      Istanbul Basaksehir -> Buyuksehyr
Sporting Gijón      -> Sp Gijon        Real Sociedad II    -> Sociedad B
Racing Santander    -> Santander       Deportivo           -> La Coruna
Hellas Verona       -> Verona          Vitória de Guimaraes-> Guimaraes
Amed SFK            -> Amedspor        Erzurum BB          -> Erzurumspor
RC Celta Fortuna    -> Celta B         Deportivo           -> [Dep. A Coruna, La Coruna]
```

**5. El motivo, en vez de una sospecha de bug.** Un partido sin pronóstico decía
siempre «el nombre del equipo no casa con el catálogo del modelo», que suena a
fallo de mapeo y casi nunca lo era. Ahora distingue las dos causas y lo dice:

> «Coventry City no ha jugado todavía en esta competición (recién ascendido),
> así que el modelo no tiene historia suya.»

Esto **no se arregla inventando un número**. Un equipo que acaba de ascender no
tiene ni un partido en esta competición ni en football-data ni en ESPN, porque
todavía no lo ha jugado: el Arsenal-Coventry del 2026-08-21 era su estreno. El
hueco honesto sigue siendo la respuesta correcta; lo que cambia es que ahora se
explica.

### Dos incoherencias de la v147, corregidas antes de que se desplegasen

El bot no ha corrido desde que la v147 entró, así que **los modelos del
repositorio son todos anteriores** y estas dos nunca llegaron a producción. Se
corrigen antes del primer pase.

**(a) Las features extra se calculaban sobre el marco equivocado.** La v147
separó el CSV del entrenamiento y dejó escrito que «el modelo recibe exactamente
lo que recibía». No era así: `preparar_features_extra` seguía recibiendo `df`
—las 16 temporadas— cuando `features_extra_liga`, `features_imt`,
`features_v26`, `features_ck` y el CDI son todas **acumulativas**. Calculadas
sobre 16 años en vez de sobre la ventana medida salen con trece años de
arrastre: exactamente el mecanismo que la propia v147 midió y quiso impedir para
`elo_diff` y `home_xg`. Ahora recibe `df_modelo`.

**(b) El catálogo de equipos salía del CSV, no del estado.** `equipos_liga` se
construía de `df` mientras `estado` venía de `df_modelo`. Todo equipo que jugó
en 2011 y no en la ventana entraba en `team_stats` con lo que devuelve un
`defaultdict`: **ELO 1500, ventanas vacías, PERF10 vacío**. En la Premier son
**16 clubes fantasma de 41**. Y no se quedaban quietos: `name_mapper` los ve, así
que un Arsenal-Blackburn de copa habría salido con una probabilidad calculada
sobre un equipo del que el modelo no sabe nada. Ahora sale de `df_modelo`.

### El resultado, medido sobre el mismo barrido

Reentrenadas las 49 competiciones con el código nuevo y repetida la medición
de partida, mismo día y misma ventana de 326 fixtures:

```
                     antes        después
con pronóstico         291            319
SIN pronóstico          35              7
                    10,7 %          2,1 %
```

**Y los 7 que quedan no son un fallo: son un límite externo.** Los cuatro
ficheros que football-data todavía no publica son precisamente los de sus
ligas:

```
premier          Coventry City · Hull City        E0 2627 sin publicar
ita_serie_b      Arezzo · Hellas Verona           I2 2627 sin publicar
gre_super_league Iraklis · Kalamata               G1 2627 sin publicar
ligue_1          Le Mans                          F1 2627 sin publicar
```

Son equipos recién ascendidos que **no han jugado todavía ni un partido en esta
competición** —el Arsenal-Coventry del 2026-08-21 era el estreno de Coventry en
la Premier—, así que no hay historia que aprender en ninguna fuente. Se
resolverán solos en cuanto football-data publique el fichero, sin tocar una
línea, porque la lista de temporadas ya lo incluye. Mientras tanto la aplicación
lo dice con esas palabras en vez de sugerir un bug.

### Un bug peor, encontrado por el camino

El partido argentino que fallaba no era un ascenso: **`Independiente` e
`Independiente Rivadavia` mapeaban los dos a `Independiente` (Avellaneda)**. La
regla de contención de la v66 se lo comía —«independiente» es subcadena de
«independiente rivadavia»— y el catálogo tenía las dos entradas
(`Independiente` e `Ind. Rivadavia`).

Que ese partido se descartara era **suerte**: sólo se salvó porque el guardia
`home == away` lo tiró. En un Independiente Rivadavia contra un tercero, el
modelo habría publicado una probabilidad con toda seguridad **del club
equivocado**, que es bastante peor que no publicar ninguna. El propio docstring
de `name_mapper` avisaba de esta pareja desde la v104.

Dos arreglos, ambos generales:

* `'ind' → 'independiente'` en la tabla de abreviaturas.
* **La expansión se prueba siempre**, no sólo cuando cambia el nombre que
  llega. La condición era `if obj_exp != objetivo`, así que cuando la
  abreviatura está en el CATÁLOGO —«Ind. Rivadavia»— el bloque se saltaba
  entero y la decisión caía en la contención. Correrlo igualmente no cambia
  nada donde ya funcionaba (sin abreviaturas, `_expandir` es la identidad y la
  comparación repite la igualdad exacta que ya falló), y hace que **una
  igualdad exacta tras expandir gane a una coincidencia por subcadena** — que
  es el orden correcto: la primera es prueba, la segunda es indicio.

Verificado, incluida la demo del propio módulo para no romper lo que ya andaba:

```
'Independiente'            -> 'Independiente'
'Independiente Rivadavia'  -> 'Ind. Rivadavia'      (antes: 'Independiente')
'Inter Miami CF'           -> 'Inter Miami'
"Nott'm Forest"            -> 'Nottingham Forest'
'Bayern München'           -> 'Bayern Munich'
'Sporting KC'              -> 'Sporting Kansas City'
'Equipo Inexistente'       -> None
```

### Un alias puede tener varios destinos

football-data escribe el mismo club distinto según la división: el Deportivo es
**`Dep. A Coruna` en SP1** y **`La Coruna` en SP2**. Con un destino por alias,
arreglar LaLiga rompía la Hypermotion. Ahora el valor puede ser una lista y se
queda el primero que exista en el catálogo de esa liga.

---

## PARTE 1 — el barrido que hacía esperar dos minutos

### Lo que ya estaba bien y no se toca

Las seis ramas de deporte **ya corrían en paralelo** desde la v79
(`ThreadPoolExecutor`), los fixtures de ESPN ya se prefetchean concurrentemente
y las cuotas por evento ya van con cuatro hilos. El guardia de la v86 ya impedía
dos barridos simultáneos (1.297 MB → 2.172 MB de pico).

Lo que **no** estaba resuelto era la **espera**, y ése era el síntoma del
usuario. El estado del guardia vivía sólo en memoria del proceso, así que el
primer visitante después de cada arranque de contenedor pagaba el barrido
entero. Y en Streamlit Cloud el contenedor se duerme y despierta
constantemente: el caso «frío» no es el raro, es el habitual.

### El arreglo: memoria → disco → calcular

`guardia_barrido` gana persistencia en disco y **revalidación en segundo plano**
(*stale-while-revalidate*), con dos umbrales:

* `FRESCURA_S = 300` (5 min): por debajo se sirve tal cual.
* `CADUCIDAD_S = 3600` (1 h): entre una y otra **se devuelve lo que hay al
  instante** y se lanza la revalidación por detrás. Por encima, se calcula.

Primero contra un barrido simulado de 1,2 s, para comprobar la máquina de
estados sin pagar dos minutos por prueba:

```
1er (frío)                    1,20 s
2do (memoria)                 0,000 s
3ro (disco, proceso nuevo)    0,001 s
4to (rancio)                  0,001 s  -> devuelve al instante y revalida detrás
5to                           trae ya el resultado revalidado
6to (caducado)                1,20 s   -> recalcula, como debe
barridos reales: 3 para 6 peticiones
```

Y después contra el **barrido de verdad**, con las 49 competiciones
reentrenadas y la red real:

```
BARRIDO FRÍO (sin caché)      : 160,1 s     424 pronósticos, 420 evaluados
RECARGA (memoria)             :   0,000 s
ARRANQUE DE CONTENEDOR (disco):   0,004 s
tamaño de la caché            :   0,33 MB
```

Contra los objetivos del encargo:

| objetivo | pedido | medido |
|---|---|---|
| recarga (caché caliente) | < 2 s | **0,004 s** |
| carga inicial con caché en disco | < 15 s | **0,004 s** |
| carga inicial sin ninguna caché | < 15 s | **160 s — no se cumple** |

**El último hay que decirlo tal cual.** Sin ninguna caché no hay atajo: el
barrido tiene que bajar los fixtures de 49 competiciones, las cuotas por evento
de seis casas y cargar los modelos. Lo que cambia es *cuándo* ocurre eso: antes
era **cada vez que el contenedor se despertaba**, y ahora es una vez por
contenedor y sólo si la caché de disco está caducada (más de una hora). El resto
de las veces —que son casi todas— la pantalla aparece en cuatro milésimas.

La caché ocupa **0,33 MB**, así que persistirla no cuesta nada.

La escritura es **atómica** (`os.replace` sobre un temporal): un contenedor que
muera a mitad del volcado no deja una caché truncada que el siguiente arranque
leería como válida.

### La parte honesta, que es la que importa

No todo el barrido envejece igual, y meterlo todo en el mismo saco sería
deshonesto **en la dirección peligrosa**:

* el **pronóstico** del modelo no cambia en media hora — sale de un modelo
  entrenado de madrugada. Servirlo de caché es correcto.
* el **precio** sí cambia, y enseñar una cuota de hace media hora como si fuera
  la de ahora es justo lo que este proyecto no hace.

Por eso el resultado servido de caché viaja siempre con `_frescura` y la
interfaz avisa **encima de las pestañas, antes de que nadie mire una cuota**:

> ⏱️ Estas cuotas se bajaron hace **N min**. Se están actualizando en segundo
> plano: los pronósticos del modelo son válidos, pero **confirma el precio en la
> casa antes de apostar**.

### Dos derroches quitados por el camino

* `ClubEngine._cuotas_partido` abría y parseaba `odds_actuales.json` **entero en
  cada llamada**, y `predecir` la llama hasta dos veces. En un barrido de 326
  fixtures son ~650 aperturas del mismo fichero para obtener siempre lo mismo —
  y cuando el fichero no existe, 650 `FileNotFoundError` construidas y tragadas.
  Ahora se memoriza con comprobación de `mtime`: si el fichero cambia, la
  siguiente lectura lo ve.
* La **cola de ESPN se pedía dos veces por liga**. Desde que `entrenar_liga` pide
  dos marcos (v147), `descargar_liga` corre entera dos veces; la v147 memorizó
  la descarga cruda de football-data pero no ésta. Sobre 57 competiciones son
  ~57 peticiones de más en cada pase del bot, que ya roza su límite de 60 min.

---

## PARTE 3 — el repositorio de 15 GB

### La medición

```
.git                          15 GB
modelos/ (árbol de trabajo)  712 MB · 246 ficheros .joblib
commits del bot                 23
15 GB / 23                  ≈ 650 MB por commit
```

Cada madrugada el bot reentrena y commitea los 246 `.joblib`. Un `RandomForest`
reentrenado con diez partidos nuevos sobre seis mil predice prácticamente lo
mismo, pero sus 20 MB de bytes cambian **enteros**: git no puede
delta-comprimir un binario ya comprimido, así que guarda una copia nueva
completa. 650 MB diarios de historia para casi ninguna información; ~19 GB al
mes.

### Lo que se descartó, y por qué (medido)

**Comprimir mejor.** Sobre `modelos/liga_mx/modelo.joblib`:

| compresión | tamaño | dump | load |
|---|---|---|---|
| zlib-3 (actual) | 7,07 MB | 0,7 s | 0,35 s |
| zlib-9 | 6,62 MB | 4,9 s | 0,30 s |
| lzma-3 | 5,62 MB | 7,6 s | 0,56 s |
| xz-6 | 5,16 MB | 9,7 s | 0,53 s |

El mejor caso ahorra un 27 % multiplicando por catorce el tiempo de guardado, y
**no toca el problema**: 650 MB diarios pasarían a 475 MB diarios.

**Adelgazar el modelo.** El 65 % del fichero es el `RandomForest` del ensemble
(4,56 de 7,07 MB). Recortarlo cambia el modelo, y las ventanas y familias de
este proyecto están medidas liga por liga. No se toca un modelo para ahorrar
disco.

**Opción 1 del encargo — entrenar al arrancar.** Medido en esta máquina, con
`python league_engine.py --build` cronometrado de punta a punta:

```
33 minutos · 49 competiciones entrenadas · 1 fallo (champions, causa local)
```

Y eso es **sólo el fútbol**: MLB, tenis ATP/WTA, NBA y KBO son otro paso del
workflow. Streamlit Cloud duerme y despierta el contenedor constantemente, así
que serían más de media hora de pantalla en blanco en cada arranque: lo
contrario exacto de lo que pide la Parte 1. Descartada con números.

**Opción 2 del encargo tal cual — un tarball de 712 MB en un Release.** Correcta
en el diagnóstico y cara en el arranque: 712 MB antes de pintar nada.

### Lo que se hizo

La idea de la Opción 2, **con un asset por competición**. El peso de un modelo
no es historia: es un artefacto, y el sitio de un artefacto no es el árbol de
git.

* Los `.joblib` se publican como **assets de un Release de etiqueta fija**
  (`modelos-latest`), que el bot reemplaza cada día. **Los assets de un Release
  no viven en la historia del repositorio**: reemplazarlos no añade un byte al
  `.git`. Gratis (2 GB por asset), sin servicios externos, sin nada que limpiar
  —etiqueta fija, no una por día—.
* **Uno por competición** (mediana 12 MB, máximo 22 MB). Ésa es la diferencia
  entre un arranque de minutos y uno de segundos: la aplicación baja sólo el
  modelo de la liga que va a usar, cuando la va a usar. En un barrido típico hay
  fixtures en ~16 de las 57.
* `modelos_remotos.asegurar(clave)` mira **primero el disco**. En un clon de
  desarrollo, o en un contenedor que ya la bajó, no toca la red. Está enganchado
  en `ClubEngine` (fútbol) y en `engines/base_engine` (MLB, NBA, tenis, KBO).

Verificado de extremo a extremo contra el repositorio real, con una etiqueta de
prueba que se borró después:

```
publicar_modelos.py kbo nba  ->  kbo 0,1 MB · nba 3,5 MB subidos
asegurar('nba')              ->  True en 1,70 s (5 ficheros)
   [modelos] nba: descargado del Release
   moneyline.joblib: booster de otra plataforma, se repara por la ruta portable
NBAEngine listo: True
```

El último detalle no es menor: el modelo bajado venía del runner de Linux y se
abrió en Windows por la ruta portable de la v87. La cadena entera funciona,
incluida la reparación de plataforma.

### La transición, que es donde estaba el riesgo

Dejar de versionar `modelos/` **en el mismo commit** que introduce la descarga
sería apostar la aplicación a que la primera publicación sale bien: si fallara,
Streamlit Cloud desplegaría un clon sin modelos y sin assets de los que
bajarlos. Sería una caída de producción.

Por eso la transición la hace el propio workflow, **y sólo después de un viaje
de ida y vuelta verificado**:

```
Reentrenar ligas → verificar que cargan
Reentrenar MLB/tenis/NBA/KBO → verificar que cargan
Publicar los modelos como assets del Release   (publicar_modelos.py --verificar)
Dejar de versionar los pesos (idempotente)     ← sólo si lo anterior salió en verde
Commitear
```

`--verificar` se baja del Release lo que acaba de subir y lo vuelve a cargar —
la misma disciplina que la v68 impuso al commit de modelos: nunca se publica un
artefacto que no se haya abierto después. El paso de transición es idempotente:
en cuanto `modelos/` deja de estar versionado, `git ls-files` sale vacío y no
vuelve a hacer nada.

**Este commit no borra nada.** Los pesos siguen en el repositorio hasta que el
bot confirme que los assets existen y se pueden abrir.

### Lo que este cambio NO hace, y hay que decirlo

Detiene el crecimiento (de ~650 MB/día a lo que ocupen `team_stats_*.json` y
`historico_*.csv`, que son 3,2 MB y 33 MB de texto y git sí delta-comprime).
**No encoge los 15 GB que ya están.** Para eso hay que reescribir la historia,
y eso:

1. es destructivo e irreversible sobre `main`,
2. rompe todos los clones existentes,
3. **y ni siquiera libera el espacio en GitHub por sí solo**: los objetos
   quedan hasta que GitHub recoge basura, lo que normalmente exige abrir un
   ticket con su soporte.

O sea: riesgo alto, beneficio incierto y ninguna urgencia una vez detenida la
sangría. Queda como operación aparte y deliberada. Mientras tanto, quien quiera
un clon ligero hoy tiene la vía barata y sin riesgo:

```bash
git clone --depth 1 --single-branch https://github.com/HectorMontiel/mundial-2026-predictor.git
```

---

## Verificación DESPUÉS del despliegue (2026-08-21, sobre producción)

Todo lo anterior se midió antes de empujar. Esto es lo que pasó de verdad.

**El bot corrió con la v148 y la transición se hizo sola.** Ejecución
`32472153115`, 59m51s, todos los pasos en verde, incluidos «Publicar los
modelos como assets del Release» y «Dejar de versionar los pesos». El Release
`modelos-latest` quedó con **57 assets** y `modelos/` desapareció de `main`.

**Un clon nuevo, que es lo que hace Streamlit Cloud en cada despliegue:**

```
git clone --depth 1 --single-branch …
    9,3 s · 194 MB          (antes: 12,89 GiB y más de diez minutos)
```

**Y funciona sin la carpeta de modelos**, que era el único riesgo real de todo
esto. En ese clon, con `modelos/` inexistente:

```
laliga     listo=True en 5,4 s · 31 equipos · predice OK
premier    listo=True en 3,2 s · 25 equipos · predice OK
liga_mx    listo=True en 2,4 s · 22 equipos · predice OK
NBA        listo=True en 2,0 s
   [modelos] laliga: descargado del Release (6 ficheros)
   modelo.joblib: booster de otra plataforma, se repara por la ruta portable
```

La última línea importa: el modelo venía del runner de Linux y se abrió en
Windows por la ruta portable de la v87. Descarga bajo demanda, extracción,
reparación de plataforma y predicción, en cadena y sin intervención.

LaLiga pasa de 26 a **31 equipos**: los ascendidos ya están dentro.

**El commit diario del bot, medido en objetos reales:**

```
git rev-list --objects <commit del bot> --not <v148> | cat-file --batch-check
    5,6 MB  ·  128 objetos
```

Frente a los ~650 MB por commit de antes. **116 veces menos**, y no es una
proyección: es el primer commit del bot ya bajo el régimen nuevo.

**Y el bug de pronósticos, remedido en ese mismo clon**, con los modelos que
sirve producción y bajados del Release:

```
FIXTURES TOTALES: 326
CON pronóstico  : 319
SIN pronóstico  :   7   (2,1 %)
SIN MOTOR       : ninguna

   premier           Coventry City · Hull City      E0 2627 sin publicar
   ita_serie_b       Arezzo · Hellas Verona         I2 2627 sin publicar
   gre_super_league  Iraklis · Kalamata             G1 2627 sin publicar
   ligue_1           Le Mans                        F1 2627 sin publicar
```

Idéntico a la medición local: el camino de producción —modelo bajado del
Release, reparado de plataforma y cargado— da exactamente el mismo resultado
que el camino de desarrollo. Que es lo que había que demostrar.

---

## v148.1 — la transición se llevó once ficheros que no debía

**Producción cayó** poco después del despliegue:

```
El motor de predicción no pudo inicializarse.
FileNotFoundError: './modelos/modelo_tda.joblib'
```

Causa mía, y del tipo más evitable: escribí el patrón `modelos/` cuando lo que
sobraba eran `modelos/*/`. En la RAÍZ de `modelos/` viven once artefactos que
**no pertenecen a ninguna liga** y que el bot diario **no regenera**:

```
modelo_tda.joblib · escalador.joblib · reg_goles_local.joblib
reg_goles_visit.joblib · metadata.json · validacion.npz
curvas_calibracion.png            (el modelo del Mundial)
mat_mundial.joblib · mat_metadata.json          (MAT)
nfl_v131.json                                   (NFL)
supervivencia_btts.json
```

`git rm -r --cached modelos/` se los llevó con las subcarpetas y `prediction_api`
se quedó sin motor. Verificado que fueron **exactamente esos once y ninguno
más**: `git diff --name-status ecc7514 5592f41 | grep '^D'` da 314 borrados,
303 de subcarpetas y 11 de la raíz.

Son **64 MB que sólo cambian cuando alguien reentrena el Mundial a mano**, no
los 712 MB reescritos cada madrugada. Nunca fueron el problema, así que se
quedan versionados.

El patrón pasa a `modelos/*/`, en el `.gitignore` y en el paso del workflow. Y
hay una razón por la que no vale el arreglo perezoso —`modelos/` más
`!modelos/*.joblib`—: **git no permite re-incluir un fichero si su directorio
padre está excluido.** Hay que excluir sólo los subdirectorios desde el
principio.

Comprobado tras el arreglo, con `modelos/` sin una sola subcarpeta —que es
exactamente el estado de producción—:

```
subcarpetas en modelos/: []
PredictionEngine OK en 2,9 s
predice MEX vs USA: OK
```

**La lección**, para que no vuelva a pasar: un `git rm -r --cached` sobre un
directorio borra TODO lo que hay dentro, y «lo que hay dentro» hay que
enumerarlo antes de escribir el patrón, no deducirlo del nombre. Aquí el
directorio se llamaba `modelos/` y contenía dos cosas con ciclos de vida
distintos: pesos por competición que se reescriben a diario y artefactos
globales que llevan meses quietos. El patrón tenía que distinguirlas y no lo
hacía.

---

## Extra no pedido: el bot perdió hoy 52 minutos de trabajo, y volvería a pasar

Al ir a lanzar el reentrenamiento se miró el estado del bot y la ejecución de
**hoy mismo estaba en rojo**:

```
2026-08-21T05:58  retrain_leagues  failure  52m12s
```

Todos los pasos en verde menos el último:

```
[main 1f503df] chore(datos): reentrenamiento automático de ligas (2026-08-21)
 200 files changed, 19011 insertions(+), 17584 deletions(-)
 ! [rejected]        main -> main (fetch first)
```

El job clonó a las 05:58, la **v147 se empujó a `main` a las 06:26** —mientras
corría— y a las 06:50 el push del bot se rechazó. Cincuenta y dos minutos de
reentrenamiento a la basura, porque el commit se queda en el runner y el runner
se destruye. La ventana de colisión son los ~55 minutos que dura el job, todos
los días: **cualquier push humano dentro de ella tira el día entero.**

Ahora se reintenta con rebase, hasta tres veces. En un conflicto la versión
buena es la del bot —acaba de regenerar esos ficheros con los datos de hoy, así
que lo que hubiera en `main` es más viejo por construcción—, pero eso vale para
los ARTEFACTOS y no para el código: si lo que choca es un `.py` o algo de
`.github/`, no hay criterio para decidir y **se aborta con un aviso en vez de
pisar el trabajo de alguien**.

Sintaxis del paso verificada con `bash -n`.

También explica por qué producción sigue con los modelos del 2026-08-20: no es
que el reentrenamiento fallara, es que no llegó a publicarse.

---

## Lo que NO se hizo de la Parte 1, y por qué

El encargo pedía cinco cosas y aquí van tres enteras y dos a medias. Se dice
cuáles:

**Hecho.** Caché con TTL (y además persistente), paralelización de red
—**ya existía** desde la v79 y se verificó: seis ramas de deporte en hilos,
prefetch concurrente de fixtures y cuatro hilos para las cuotas por evento; lo
que se hizo fue quitar dos llamadas repetidas—, e indicador de estado (el aviso
de frescura).

**No hecho: el renderizado progresivo por deportes y la barra «analizando
liga 1/57».** No por falta de tiempo, por un conflicto real:

* Streamlit no puede actualizar el texto de un `st.spinner` mientras la función
  que envuelve está corriendo. Enseñar «1/57» exige convertir el barrido en algo
  que se lanza al fondo y una pantalla que se repinta sola.
* Y ahí está el problema: si la página pinta lo que hay **en el momento en que
  se pinta**, su contenido pasa a depender del reloj. `smoke_botones` recorre
  las 8 vistas con `AppTest` y comprueba qué botones existen; con pintado
  parcial, dos ejecuciones del smoke ven páginas distintas y deja de servir
  como red de seguridad. Es la misma lección de la v147 con
  `segmented_control`: **testabilidad > estética**.
* Y para el usuario el resultado sería una pantalla que cambia debajo del ratón
  mientras decide sobre precios.

El caché ya lleva el caso frecuente a 4 milésimas. El pintado progresivo sólo
ganaría algo en el único caso que queda —contenedor recién despierto **y** caché
caducada— y a cambio de perder determinismo en la validación. Si se quiere, es
una versión aparte con su propia tanda de smoke, no un añadido a ésta.

---

## Ficheros tocados

| fichero | qué |
|---|---|
| `temporadas_fd.py` | **nuevo** — la temporada vigente se deriva de la fecha |
| `_v148_medir_pronosticos.py` | **nuevo** — la medición del 35 → 7 |
| `_v148_perf_barrido.py` | **nuevo** — la medición de frío/caliente/disco |
| `modelos_remotos.py` | **nuevo** — descarga bajo demanda de los pesos |
| `publicar_modelos.py` | **nuevo** — publica los pesos como assets del Release |
| `config.py` | 9 listas de temporadas derivadas |
| `config_ligas_espn.py` | 2 listas derivadas |
| `generar_ligas_v68.py` | deja de congelar la lista al generar |
| `league_engine.py` | descarga tolerante · features extra y catálogo desde `df_modelo` · altas desde ESPN · memo de `odds_actuales` y de la cola de ESPN · enganche de modelos remotos |
| `name_mapper.py` | `mejor_candidato()` · alias con varios destinos · `'ind'` y expansión siempre |
| `alias_manuales.json` | +31 alias, y el valor puede ser una lista de destinos |
| `alpha_finder.py` | motivo preciso en los partidos sin pronóstico · prefetch paralelo de modelos |
| `guardia_barrido.py` | caché en disco + revalidación en segundo plano + `_frescura` |
| `dashboard_ui.py` | aviso de la edad de las cuotas |
| `engines/base_engine.py` | enganche de modelos remotos |
| `.github/workflows/retrain_leagues.yml` | publicar + verificar + transición · reintento del push con rebase |
| `.gitignore` | caché del barrido |
