# VALIDACIÓN v152 — Modo Modelo, y qué dicen los datos sobre los córners

Dos planes de trabajo pedían lo mismo desde dos ángulos: **ordenar por
rendimiento del equipo en vez de por error de precio**, y **explotar los
córners y las ligas secundarias**. Este documento recoge lo que se midió antes
de tocar nada, lo que se implementó, y lo que se descartó con su número al lado.

Resumen en una línea: **la interfaz pedida está entregada; de las cuatro
mejoras de modelo propuestas, tres estaban construidas sobre datos que no
existen y la cuarta ya estaba hecha.**

---

## 1. EL HALLAZGO QUE CAMBIA LOS DOS PLANES: EL xG DE ESTE PROYECTO NO ES xG

El plan pedía «explorar un modelo basado en xG, que es más estable que los
goles» y «mostrar xG a favor y en contra de los últimos 5» en cada tarjeta.

Las columnas `home_xg`/`away_xg` existen en casi todos los históricos. Las
escribe `CorrelatedSyntheticGenerator.generate_advanced_metrics`, no una fuente:

```
xG = xg_intercept + xg_slope_goles · goles_reales + ruido(xg_residual_std)
```

Ajustando xG contra goles en los ficheros guardados:

| liga | n | intercepto | pendiente | sd residual |
|---|---|---|---|---|
| Bundesliga | 9.792 | 0,785 | 0,201 | 0,519 |
| Argentina | 7.610 | 0,785 | 0,200 | 0,498 |
| Liga MX | 5.302 | 0,776 | 0,203 | 0,509 |
| Brasileirão | 6.174 | 0,775 | 0,208 | 0,505 |
| **calibración del generador** | | **0,776** | **0,200** | **0,529** |

Los cuatro reproducen la calibración con tres decimales. **El xG es una función
afín de los goles con ruido encima**: no lleva ni un gramo de información que
los goles no tengan ya, y sí lleva ruido que los goles no tienen.

Lo mismo con la posesión, que el plan pedía como variable de córners:
`posesión = 50 + 12·tanh(elo_diff/300) + ruido`, residual medido 3,97 / 3,95 /
4,00 contra el 4,0 del generador.

**Consecuencias, y las dos son decisiones:**

1. **No se implementa el modelo de fútbol basado en xG.** Entrenar sobre esas
   columnas es entrenar sobre los goles degradados. Ya está medido en el
   proyecto, además, por otra vía: la v14 probó el xG REAL de Understat como
   feature y empeoró el log-loss en LaLiga (1,014 → 1,108).
2. **No se enseña xG ni posesión en las tarjetas.** Decirle al usuario «xG 1,8
   vs 0,9» cuando está viendo el marcador multiplicado por 0,2 es el modo de
   fallo que la v150 dejó escrito: *un hueco se ve, un relleno no*.

Lo que sí se enseña, porque sí es observado: **goles, córners, remates y
tarjetas**.

### 1.1 Cómo se sabe, y por qué no es una lista escrita a mano

`rendimiento_equipos._columnas_sinteticas` no infiere: **reproduce**. El
generador es determinista por `MATCH_ID`, así que se le vuelve a pedir la
columna sobre una muestra del propio fichero y se compara valor a valor. Si
coincide, la columna no se parece a la fórmula: **es** la fórmula.

Cada columna se prueba sola —se borra esa y se dejan las demás— porque el
generador encadena (los remates salen del xG y los córners de los remates).
Borrando todas a la vez, una columna real se recalcularía desde entradas
sintéticas, saldría distinta, y se declararía «observada»: el error peligroso.

Una lista escrita a mano habría envejecido en silencio. Esto responde por el
fichero que tiene delante, así que el día que FotMob cubra el xG real, la
interfaz empieza a enseñarlo sola.

---

## 2. CÓRNERS: LA MEDICIÓN QUE FALTABA, Y LO QUE DESTAPÓ

### 2.1 El sesgo, medido como había que medirlo

La v146 midió el sesgo alimentando la fórmula con el xG **observado** del
histórico y concluyó que faltaban 1,3 córners; subió la base de 4,0 a 5,3 y
tuvo que revertirlo. Producción alimenta la fórmula con `lam_h`/`lam_a`, que
son el xG **predicho**. No son la misma magnitud.

Medido ahora con los lambdas de producción, sobre **11.856 partidos con córners
100 % reales** en 15 competiciones:

| liga | n | real | predicho | sesgo | correlación | base que calibra |
|---|---|---|---|---|---|---|
| premier | 760 | 10,15 | 10,47 | +0,32 | +0,0039 | 3,68 |
| laliga | 768 | 9,58 | 10,14 | +0,56 | −0,0410 | 3,44 |
| serie_a | 1.140 | 9,25 | 9,24 | −0,01 | −0,0468 | 4,01 |
| bundesliga | 918 | 9,77 | 11,20 | +1,43 | +0,0403 | 2,57 |
| ligue_1 | 613 | 9,48 | 10,17 | +0,69 | +0,0502 | 3,31 |
| eredivisie | 630 | 10,21 | 10,25 | +0,04 | +0,0847 | 3,96 |
| primeira | 629 | 9,44 | 10,05 | +0,61 | +0,0403 | 3,39 |
| turquia | 657 | 9,58 | 9,75 | +0,17 | −0,0534 | 3,83 |
| gre_super_league | 709 | 8,81 | 10,34 | +1,53 | +0,0227 | 2,47 |
| eng_league_one | 1.117 | 9,89 | 10,50 | +0,61 | −0,0723 | 3,39 |
| eng_league_two | 1.116 | 9,77 | 10,22 | +0,45 | −0,0049 | 3,56 |
| sco_premiership | 468 | 10,54 | 10,94 | +0,40 | −0,0507 | 3,60 |
| esp_hypermotion | 936 | 9,38 | 8,58 | −0,79 | +0,0790 | 4,79 |
| ita_serie_b | 761 | 9,29 | 9,71 | +0,42 | −0,0254 | 3,58 |
| fra_ligue2 | 634 | 9,35 | 9,69 | +0,34 | −0,0446 | 3,66 |
| **ponderado** | **11.856** | **9,613** | **10,048** | **+0,435** | **−0,0012** | **3,565** |

**Dos conclusiones, y la segunda es la importante:**

1. **La base 4,0 estaba bien y la corrección a 5,3 iba en dirección
   contraria.** Lo que calibra el nivel es 3,57, no 5,3. La reversión de la
   v146 fue correcta por el motivo correcto.
2. **La correlación es cero.** Media −0,0012, rango [−0,072, +0,085], **0 de 15
   ligas** con |correlación| > 0,1. Y es una correlación *optimista*: el motor
   predice cada partido pasado con el estado ACTUAL de los equipos, o sea con
   información del futuro. Un límite superior de 0,004 no deja margen para
   discutir. **La fórmula predice el mismo total siempre.**

Eso invalida cualquier EV de córners calculado con ella, y lo invalida en la
dirección peligrosa: un modelo que siempre dice ~10,1 produce EV enormes en
cuanto la casa mueve su línea a 8,5 u 11,5, y ese EV es íntegramente error del
modelo. Es la firma exacta de `EV_SOSPECHOSO`.

### 2.2 ¿Se puede construir el modelo bueno? Se intentó, con datos reales

football-data publica córners y remates REALES. La fórmula actual no los usa:
deriva los córners del xG, que es sintético. Así que se construyó el modelo que
el plan pedía —medias móviles de córners a favor y en contra de los últimos 5,
separando la serie de local y la de visitante, más remates como medida de
ritmo— y se validó con split temporal, sin `predecir` de por medio y sin fuga.

**20 competiciones, 8.889 partidos en el tramo de juicio:**

| modelo | MAE | correlación | ligas que baten a la constante |
|---|---|---|---|
| constante (media de la liga) | 2,6996 | — | — |
| **fórmula actual** | **3,0749** | 0,031 | **1 de 20** |
| fórmula con la base recalibrada por liga | 3,0609 | — | p5 > 0 en 1 de 20 |
| ridge con córners y remates reales | 2,6942 | 0,051 | p5 > 0 en 2 de 20 |
| gradient boosting | 2,7624 | 0,024 | 0 de 20 |

**La fórmula actual es peor que decir siempre la media de la competición**, por
0,375 córners de MAE, en 19 de 20 ligas.

Y aquí está la respuesta a la pregunta que los dos planes hacían —«¿la constante
óptima es 4,0 o 5,3?»—: **ninguna de las dos, porque la constante no era el
problema.** Recalibrar la base con la que calibra cada liga en su tramo de
entrenamiento recupera **0,014 de los 0,375** que la fórmula pierde. El 96 % del
daño lo hace la parte variable, que es ruido: sumar ruido a una media añade
varianza sin añadir señal.

Y el modelo construido con datos reales mejora la constante en **0,005 córners**
sobre una desviación típica de 3,3. El percentil 5 del bootstrap cruza cero en
2 de 20 ligas (Turquía +0,0019, Scottish Championship +0,0232), que es lo que
produce el azar al hacer veinte pruebas.

### 2.3 ¿Y en ligas secundarias?

La tesis era que la casa tiene más margen de error donde hay menos volumen. En
la parte que este experimento puede medir —la predictibilidad, no el precio— no
hay diferencia:

| grupo | ligas | n juicio | mejora del ridge sobre la constante |
|---|---|---|---|
| principales | 10 | 4.065 | +0,0062 |
| secundarias | 10 | 4.824 | +0,0049 |

**Las ligas secundarias no son más predecibles en córners.** Esto no refuta que
sus líneas estén peor puestas: refuta que este modelo pueda saberlo.

### 2.4 Lo que se cambia en producción

**El total de córners pasa a ser la media observada de la competición.** Es el
mejor estimador de los cuatro probados, y el cambio vale un 12 % de MAE (3,075
→ 2,700) en las 20 competiciones con córners reales.

No se adopta el ridge: 0,005 córners de mejora sobre una desviación típica de
3,3 no justifica meter un modelo entrenado en el camino de predicción.

**Y en las 55 competiciones sin córners observados, tampoco se deja la
fórmula.** Lo que producía era peor que no saber: en Liga MX daba **13,4
córners** de total, contra un rango observado de [8,81 – 10,54] en las 20
competiciones que sí los publican. Ese 13,4 generaba «Más de 9.5 córners:
85,9 %» — un porcentaje que era íntegramente el desfase del modelo.

Ahora esas competiciones usan la media de las comparables (9,613, ponderada
sobre 11.856 partidos). **Es una suposición y va declarada como tal**: que una
liga sin datos se parece a las que los tienen. Lo que la sostiene es que el
rango observado entre 20 competiciones es estrecho, así que su error de nivel
está acotado en ~1 córner, contra los ~3,8 de antes.

Medido tras el cambio: Liga MX pasa de 13,4 a 9,6 y su «Más de 9.5» de 85,9 % a
49,3 %.

La sección devuelve además `corners_de_datos` y `corners_procedencia`, para que
la interfaz pueda distinguir las dos ramas. Sin ese campo las enseñaría igual,
que es el modo de fallo de siempre: *un hueco se ve, un relleno no*.

### 2.5 Lo que NO se hace: activar el EV

**El EV de córners sigue marcado como no fiable.** Hay dos motivos y ninguno lo
arregla afinar la fórmula:

1. **El modelo no discrimina.** Ahora predice explícitamente la media de la
   competición, la misma para todos sus partidos. Contra una casa que mueve su
   línea partido a partido, eso produce EV grandes cuya causa entera es que el
   modelo no distingue.
2. **No existe histórico de LÍNEAS de córners.** football-data no las publica y
   el de The Odds API es de pago (prohibido en el §7). Sin líneas no hay apuesta
   que liquidar, así que la regla de oro —p5 positivo en el tramo de juicio— no
   se puede ni aplicar a este mercado.

De paso se corrigió el motivo escrito en `cuotas_tablon`, que afirmaba que «la
discriminación sí parece buena, correlación +0,81». Ese +0,81 era contra la
LÍNEA de la casa y salía de **n=4 partidos**: mide que las dos rondan la misma
media, no que el modelo ordene los partidos. Contra el resultado real, la
correlación es −0,0012 sobre 11.856.

---

## 3. QUÉ COMPETICIONES TIENEN CÓRNERS DE VERDAD

La bitácora de la v146 dejó escrito que «las 50 ligas disponibles tienen
`home_corners`/`away_corners` al 100 % en 2023-2026». Tienen la **columna** al
100 %. Pasando la prueba de reproducción por las 75 competiciones del proyecto:

**20 de 75 tienen córners observados**, y son exactamente las 20 de
football-data formato 'main'. En las otras 55 la columna la escribió el
generador.

| | competiciones | partidos |
|---|---|---|
| principales con córners reales | 10 | ~41.000 |
| **secundarias con córners reales** | **10** | **~48.000** |
| sin córners observados | 55 | — |

Las secundarias con datos reales son: EFL Championship, League One, League Two,
National League, LaLiga Hypermotion, Serie B, Ligue 2, 2. Bundesliga, Scottish
Championship y Super League Greece.

**Las que el plan citaba como ejemplo no están**: la J2 japonesa, la 2. Liga
austriaca y la 3. Liga alemana no publican córners por esta vía, así que un
modelo de córners para ellas no tendría con qué entrenarse ni con qué validarse.

---

## 4. LIGAS SECUNDARIAS EN EL BARRIDO

El plan pedía «asegurar que el barrido incluya todas las ligas secundarias».
Comprobado:

- **49 de 50 competiciones disponibles entran en el barrido**, y **35 de ellas
  son secundarias**.
- La única fuera es **Polonia (Ekstraklasa)**: ESPN devuelve 400 para `pol.1`, y
  también para `pol.ekstraklasa`, `pol.2`, `pol.polska.1` y `pol.pl.1`. No es un
  olvido de configuración: no hay endpoint. Queda pendiente con otra fuente.
- La 3. Liga alemana y la Saudi Pro League **no están en el catálogo**. La
  primera sigue como pendiente con ingestor OpenLigaDB.

---

## 5. TENIS POR SUPERFICIE: YA ESTABA HECHO

El plan pedía «modelos que distingan el rendimiento en tierra, césped y pista
dura» y «desgaste físico». `engines/tennis_engine.py` ya lo tiene, y desde hace
versiones:

- `DIFF_ELO_SUP` — ELO por superficie, con la pista **indoor** como superficie
  propia (`hard_indoor` ≠ `hard`).
- `DIFF_WIN_SUP_12M` — porcentaje de victorias en esa superficie a 12 meses.
- Fatiga: días desde el último partido, partidos en 14 días y horas en pista en
  7 días.
- `DIFF_FORMA10`, H2H acumulado, y saque/resto desde TennisAbstract.

No se toca nada. Se documenta para que no se vuelva a pedir.

---

## 6. LO QUE SÍ SE IMPLEMENTA

### 6.1 Pestaña «📊 Modo Modelo», primera y por defecto

Ordena por **probabilidad del modelo** y enseña, por cada partido, el
rendimiento reciente observado de los dos equipos:

- racha de los últimos 5 (G/E/P) y puntos por partido,
- goles a favor y en contra,
- **córners a favor y en contra**, sólo donde son observados,
- remates a favor y en contra,
- **momentum**: últimos 5 contra los 5 anteriores,
- la racha del bando que toca jugar (local en casa, visitante fuera).

La etiqueta principal es la pedida: `📊 Modelo: [Equipo] con X % de
probabilidad`. No dice EV, y lo dice a propósito.

**Los córners salen destacados**, con la media de la competición y lo que saca y
recibe cada equipo en sus últimos 5. Lo que no sale es la **línea recomendada**
que el plan pedía: recomendar «más de 9,5» a partir de un número que es idéntico
en los diez partidos de la jornada sería vender la media de la liga como lectura
del partido. Las medias de cada equipo sí son suyas, y ésas se enseñan.

**La advertencia va dentro de la pantalla, no debajo.** Ordenar por probabilidad
del modelo está medido en −4,66 % a −6,52 % de ROI sobre 37.158 apuestas, y su
EV es anti-indicador del cierre. La pantalla lo dice con esas palabras y remite
a «💎 Modo Valor» para decidir. Cambiar qué se mira primero es una decisión del
usuario; dejar de decir lo que ese orden rinde, no.

**Sin modelo no es con mercado.** La v149 rellena los partidos sin pronóstico
con la probabilidad implícita del mercado. Aquí no: salen agrupados aparte con
`Sin datos de modelo`. Un número del mercado en una fila del modelo haría
imposible distinguir uno de otro, que es justo lo que la pantalla venía a
arreglar.

### 6.2 Filtro de ligas secundarias

Va **arriba, junto al filtro de deporte**, y afecta a todas las pestañas a la
vez. No se puso dentro del Modo Modelo a propósito: dos controles del mismo eje
en dos sitios acaban divergiendo, y entonces el mismo partido sale en una
pantalla y no en la otra.

El eje **no aplica fuera del fútbol**, y `es_secundaria` devuelve `None` para
decirlo. Lo destapó el render: la MLB salía como «MLB · MLB · secundaria». La
MLB no es una liga de fútbol secundaria, es otro deporte.

La pantalla no promete que las secundarias rindan más: dice que es una
hipótesis razonable que todavía no tiene su propio percentil 5.

---

## 7. TESTS AÑADIDOS

Seis tests nuevos en `test_catalogo_y_cuotas.py`, más la ampliación de uno:

| test | qué fija |
|---|---|
| `test_no_se_ensena_estadistica_sintetica` | que el xG y la posesión no salgan como observados, y que los córners de la Premier sí y los de la Liga MX no |
| `test_rendimiento_no_rellena_lo_que_falta` | que un campo sin dato vuelva `None` y un equipo desconocido devuelva `n=0`, no una fila de ceros |
| `test_modo_modelo_no_tapa_los_huecos_con_el_mercado` | que la pantalla no lea el relleno de mercado y que lleve la advertencia medida |
| `test_modo_modelo_separa_ligas_secundarias` | el reparto, que el eje no aplique fuera del fútbol y que el filtro no esté duplicado |
| `test_modo_modelo_esta_enrutado_en_la_interfaz` | que la pestaña sea la primera y que la de precio siga estando |
| `test_corners_no_suben_a_seccion1_sin_medicion` | que la base siga en 4,0 y que ningún pick de córners llegue a la Sección 1 |
| `test_mensajes_sin_jerga_interna` (ampliado) | ahora cubre los módulos de vista, no sólo `dashboard_ui.py` |

El guardia de jerga saltó nada más ampliarlo, con un comentario `/* ... */`
dentro de una hoja de estilos. Se calibró para que calle en ese caso: **una
alarma que salta en el caso normal deja de ser una alarma.**
