# v227 — Los módulos sin enchufar, atacados uno a uno

La auditoría venía señalando 25 banderas rojas, y la mayoría eran la misma
frase repetida: «nadie lo importa y no es script de entrada». Eso no es un
hallazgo, es una pregunta sin contestar. Esta tanda las contesta.

**Resultado: de 25 banderas a 2.** Y las 2 que quedan son de otra familia
—`feature_engineering` y `handicap`, grandes, activos y sin medición encima—,
no huérfanos.

---

## 1. El grafo no veía los ficheros de datos

`backtest_thresholds` salía como huérfano. No lo era: produce
`umbrales_capa1.json`, que leen `alpha_finder`, `dashboard_ui`, `frescura_datos`
y `recalibrar_todo`. El acoplamiento existía, pero pasaba por disco y el grafo
sólo miraba los `import`.

Se añadió la arista de artefacto y un estado nuevo, `productor_de_artefacto`.
Un módulo que fabrica un fichero que otro consume no está muerto: está en la
otra punta de una tubería que el analizador no sabía seguir.

## 2. El triaje, y por qué una tabla curada necesita guardia

Lo que quedaba pedía leer el código, no analizarlo. `TRIAJE_MODULOS` clasifica
cada módulo en cuatro familias, con la explicación escrita:

| familia | qué significa | cuántos |
|---|---|---|
| generador | produce un catálogo o un dataset; se corre cuando hace falta | 8 |
| sondeo | contestó una pregunta concreta; la respuesta está en su JSON | 3 |
| aparcada | hipótesis medida que no llegó al listón | 8 |
| sin_enchufar | escrita, correcta y sin llamar — **aquí sí había decisión** | 2 |

Un módulo triado deja de contar como bandera roja, porque ya tiene respuesta.
Ese trato tiene un peligro obvio: en cuanto la explicación deje de ser cierta,
la tabla pasa de documentar a **tapar**. Por eso existe `triaje_rancio()`, que
falla si una ficha habla de un módulo borrado o de uno que alguien enchufó.

No es teórico. Falló en su primera ejecución, contra una ficha que acababa de
escribir yo mismo en este mismo commit.

---

## 3. `historico_agrupado`: medido dos veces, y NO se engancha

La idea era buena y venía del propio proyecto: la Champions son 907 partidos
entre equipos que juegan 34 en su liga, así que agrupar el histórico de la copa
con el de las ligas de sus participantes debería predecir mejor a quien no
tiene muestra. Es exactamente lo que ya hace `leagues_cup`.

**La medición global** (`_v184_mide_agrupado_bien.py`, que ya estaba escrita y
nunca se había corrido), sobre el mismo conjunto de evaluación para los dos:

| modelo | acc | logloss |
|---|---|---|
| solo copa | 0,5556 | 0,9517 |
| agrupado | 0,5611 | **0,9869** |

La precisión sube en UN partido de 180 —ruido— y el logloss empeora. El logloss
es la regla de puntuación propia: mira la probabilidad entera en vez de sólo el
argmax, y es la que decide.

**Pero esa medición tenía un punto ciego**, y era justo el que motivó el
módulo. Evalúa sobre partidos que el modelo de la copa ya sabe predecir, porque
el conjunto sale de su propio histórico. Los partidos que dieron origen a la
v184 —los que salen con `prob: None` porque el equipo no tiene filas— no pueden
estar ahí, por definición.

Así que se midió la pregunta buena (`_v227_agrupado_solo_huecos.py`), partiendo
la evaluación por si un equipo llega al corte con menos de 8 partidos:

| grupo | solo copa | agrupado | base tonta |
|---|---|---|---|
| conocidos (n=128) | 0,5781 | 0,6016 | 0,5156 |
| **huecos (n=52)** | **0,5000** | **0,4615** | 0,4808 |

En los huecos, que es donde tenía que servir, el agrupado acierta **menos** que
el modelo de la copa y ni siquiera gana a «predice siempre la clase mayoritaria».

Con n=52 la diferencia son dos partidos, así que lo honesto es decir *no hay
ninguna evidencia a favor*, no *está demostrado que dañe*. Da igual: la carga de
la prueba la tiene quien enciende, y aquí no hay nada que la levante. **Queda
aparcado, con la respuesta escrita para que nadie tenga que volver a preguntarlo.**

---

## 4. `ventaja_ponches`: no le faltaba lógica, le faltaba quien lo llamara

Este módulo llevaba desde la v132 escrito y correcto, y su propio docstring
explicaba el bloqueo: no existe histórico de precios de props —cero filas entre
las 155.364 de 1X2—, así que no hay ROI ni p5 que medir, y sin eso el proyecto
no publica una recomendación. Es la regla y no se salta.

Traía `fotografiar()` para empezar a acumular esa muestra. Nadie le pasaba
nunca las filas.

Se escribió `snapshot_diario()`, que las fabrica, y se enganchó a
`precalculo_dia` —el mismo sitio donde vive el archivo de contexto, y por el
mismo motivo: sale a la red, y el precio de hoy no se recupera mañana—. Cada
pasada añade una foto con su hora, así que las ocho del día capturan además el
movimiento de línea, que era gratis y no se miraba.

**Esto no publica ningún pick ni toca uno existente: escribe un CSV.** Es lo
único que puede levantar el bloqueo algún día, porque es lo que fabrica la
muestra que hoy no existe.

---

## 5. El fallo que salió de camino: la ciudad abreviada

Al probar la foto salieron 5 anclas de Pinnacle y **0 escaleras de Playdoit**.
No era que Playdoit no cotizara: los partidos estaban ahí. Los escribe con la
ciudad abreviada.

```
Pinnacle:  Los Angeles Dodgers      →  'los angeles dodgers'
Playdoit:  LA Dodgers               →  'la dodgers'        ← sin expandir
similitud: 0,435   ·   umbral del emparejador: 0,80
```

`ABREV_MLB` trae las canónicas de ESPN (LAD, LAA, NYM, CWS), no las de ciudad
corta. Y lo más engañoso: `la`, `ny` y `chi` **ya existían** como claves,
registradas por la NFL (Rams, Chargers, Giants, Jets, Bears). La abreviatura sí
se buscaba y simplemente no encontraba ningún candidato de béisbol.

El efecto no era un error visible sino un silencio: esos partidos salían «sin
cuota de Playdoit» —la casa del usuario— y por tanto sin comparación de precio,
que es el único criterio con p5 positivo del proyecto. Afectaba a Dodgers,
Angels, Mets, Yankees, White Sox y Cubs, todos los días.

Se arregla como ya se había hecho con la NFL, colgando las de ciudad corta de
la tabla existente. No crea ambigüedad porque la desambiguación no la hace la
ciudad sino el apodo: «la dodgers» sólo encaja con «los angeles dodgers», y
«chi bears» sigue yendo a los Bears. Hay test de las dos cosas.

**Medido: de 0 escaleras a 21.**

---

## Validación

- `test_catalogo_y_cuotas.py` — TODO OK (14 comprobaciones nuevas de la v227)
- `test_match_parlay.py` — TODO OK
- `test_simetria.py` — TODO OK
- `valida_render.py` — TODO OK
- `smoke_botones.py` — **pendiente**, ver abajo.

### Sobre el smoke, y por qué esta línea dice «pendiente»

La primera vez que se corrió fue con `| tail -8`, y en una tubería el código de
salida es el del ÚLTIMO comando. O sea que el `exit 0` que se leyó era el de
`tail`, no el de la prueba, y el veredicto se lo había comido el recorte. Dar
eso por bueno habría sido firmar una validación que nadie hizo.

Al repetirlo sin tubería, la prueba se queda colgada. Está en investigación con
un vigía que vuelca las pilas, y **no se da por validada hasta que se sepa**.
Lo que sí está medido es que el camino de MLB donde parecía atascarse responde
en 0,9 s, así que la primera sospecha ya está descartada.
