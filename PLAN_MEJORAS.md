# Plan de mejoras — seis frentes, con las premisas comprobadas primero

Antes de diseñar nada se ha ido a mirar qué publican de verdad las fuentes.
Tres de las seis secciones cambian de forma al hacerlo, y una se desbloquea.

| sección | veredicto | por qué |
|---|---|---|
| 1 · línea alternativa de ponches | **imposible como se pidió** | Playdoit no cotiza ponches por jugador |
| 2 · KBO al nivel de MLB | **medir antes de construir** | lo de MLB no tiene ROI demostrado |
| 3 · todos los mercados de Playdoit | **ya está hecho** | 148-172 mercados por partido desde hace versiones |
| 4 · recomendación de córners | **DESBLOQUEADA** | sí hay precio, al contrario de lo que creía el proyecto |
| 5 · visual del H2H | **viable, sin dependencias nuevas** | con SVG en la capa visual que ya existe |
| 6 · Sección 2 y parlays | **viable a medias** | el parlay «de EV positivo» que se pide es imposible |

---

## 1. MLB — la línea alternativa de ponches

### Lo que dicen los datos, no el plan

Tablero de Playdoit para MLB (`GetEventDetails`, DET vs CLE del 13/08/2026):
**86 mercados, cero por jugador.** Todo lo de ponches es de equipo:

```
Strikeouts por lanzadores               14.5   ← el partido entero, los dos equipos
DET Tigers Ponches de los Lanzadores     6.5   ← TODOS los lanzadores de Detroit
CLE Guardians Ponches de los Lanzadores  8.5
```

Los identificadores apuntan a equipos (`sa:competitor:mlb-114/116`) y **ningún
nombre de lanzador aparece** en los 86 mercados.

### Y esto es más grave que la línea alternativa

La regla 3 recomienda **el prop del abridor**, que sale de Pinnacle. En
Playdoit ese mercado **no existe**. O sea que el sistema lleva versiones
proponiendo una apuesta que el usuario no puede colocar donde apuesta. No es
que falte el 3.5+: es que tampoco estaba el 5.5+.

Es la lección de «valida el render» por otra puerta: se validó la
probabilidad, no si la apuesta se puede poner.

### Las tres salidas, con sus costes

| opción | qué implica | veredicto |
|---|---|---|
| **A · modelar ponches de EQUIPO** | Playdoit sí los paga (partido y por equipo). Exige un modelo nuevo: abridor + bullpen, con su propia validación en dos tramos | **la única que da una apuesta colocable.** Es trabajo de modelo, no de scraping |
| **B · buscar un endpoint de props de jugador en Playdoit** | Algunas casas Altenar sirven los props por una llamada aparte que `GetEventDetails` no trae. Coste: una tarde de inspección de red | **barato de comprobar, y hay que hacerlo antes que A** |
| **C · marcar la regla 3 como no colocable** | Un aviso en la ficha: «este mercado no existe en tu casa» | **inmediato, y honesto mientras se decide** |

Descartadas: scraping con Selenium (la ruta estructurada ya existe y es la
misma que usa el proyecto; añadir un navegador es fragilidad sin ganancia) y
The Odds API (**sus props de jugador son de pago y cuestan más créditos por
llamada**; con 450 al mes y 23 al día no caben, y el usuario ha pedido
explícitamente no quemar la cuota).

### Recomendación

**C ahora, B esta semana, A sólo si B falla.** Y nada de A sin el protocolo de
siempre: dos tramos, bootstrap, y congelar si el p5 sale negativo.

---

## 2. KBO al nivel de MLB

### La pregunta previa que el encargo no hace

Antes de llevar el sistema de ponches a la KBO conviene mirar qué se estaría
llevando. De MLB está medido:

- ROI global de la MLB: **−0,97 %**, p5 −2,68 % sobre 7.541 apuestas.
- La banda 60-70 % es la única en positivo (+2,75 %) y su p5 es **−1,68 %**.
- Del filtro de ponches **no hay ROI**, porque no existe histórico de precios
  de props. Lo que está medido es que predice mejor, no que gane dinero.

**Portar a la KBO un sistema cuyo rendimiento en dinero es desconocido es
multiplicar la incertidumbre, no la cobertura.**

### Datos

| fuente | cubre KBO | pegas |
|---|---|---|
| MLB StatsAPI | **no** | sólo organizaciones MLB |
| Baseball Savant / Statcast | **no** | Statcast no instrumenta la KBO |
| Baseball Reference | parcial | totales por temporada, no `gameLog` con `gamesStarted` |
| **Naver Sports** (`kbo_naver.py`, ya en el repo) | **sí** | raspado; hay que comprobar si trae aperturas partido a partido |
| Pinnacle (`props_ponches`) | comprobar | si no publica props de KBO, no hay ni línea que evaluar |

**La pieza que decide es si existe el equivalente del `gameLog`**: sin
`gamesStarted` por partido, el módulo `contexto_ponches` no se puede replicar y
la KBO se queda con el agregado, que es justo el fallo que acabamos de corregir.

### Metodología propuesta

1. Comprobar que Naver da salidas individuales con BF y K. **Si no, parar aquí.**
2. Reconstruir dos temporadas y repetir el backtest cronológico: sesgo, MAE y
   calibración, con el mismo código.
3. **No reutilizar el descuento de 2 puntos.** Es de MLB y de dos temporadas
   concretas; aplicarlo a la KBO sin medirlo sería repetir el error del ancla
   de 17,0. Se mide su propio descuento con el mismo barrido de 8 celdas.
4. Criterio: **p5 positivo en el tramo de juicio o la KBO se congela** para
   ponches. Es exactamente lo que pide el encargo y coincide con la regla del
   proyecto.

---

## 3. Todos los mercados de Playdoit — ya está construido

`cuotas_multi.mercados_playdoit()` devuelve **el tablero completo**: medido hoy,
**170 mercados** en Liga MX y **86** en MLB, con una sola petición por partido y
caché normalizada. `cuotas_tablon` los traduce al vocabulario del modelo con
veto por seña y cruce acotado por familia.

Lo que hay en un tablero de fútbol, comprobado: hándicap asiático (7 mercados),
totales de goles (46), córners (varios, ver §4), marcador exacto, mitades,
par/impar, «equipo X marcará», margen de victoria.

**Lo que falta no es el extractor: es que el modelo tenga probabilidad para
esos mercados.** Un mercado sin probabilidad propia no se puede cruzar, y hoy
la plantilla cubre 1X2, goles, BTTS y hándicap. Ése es el trabajo real de esta
sección, y es de modelo.

Sobre el ahorro de API: esto **no gasta créditos**. Es el endpoint propio de la
casa, sin clave ni cuota. Los 450 del mes son sólo de The Odds API.

---

## 4. Córners — la sección que se desbloquea

### El proyecto creía que no había mercado, y sí lo hay

La ficha dice hoy, con estas palabras: *«ninguna de las seis casas del tablón
publica precio de córners ni de tarjetas»*. **Es falso.** Muestreados 14
partidos de Liga MX y LaLiga 2:

| | con precio en Playdoit |
|---|---|
| **totales de córners con línea** | **13 de 14** |
| tarjetas | **0 de 14** |

En un partido cualquiera aparecen `Total Tiros De Esquina`, el total por cada
equipo, `Escala de tiros de esquina` (0-4 / 5-6 / 7+), `Carrera a 3/5/7/9` y las
variantes de primera mitad. **Seis totales con línea y precio.**

Corregir ese texto es lo primero que hay que hacer: está impidiendo activamente
usar un mercado que existe.

### Lo que ya está hecho y lo que falta

Hecho: la app ya calcula la frecuencia empírica por línea del cruce
(`_ex['corners']['lineas']`) y enseña la cuota mínima que la pagaría (1/p).

Falta: cruzar esa probabilidad con **el precio real de Playdoit**, calcular EV
y marcar la recomendada.

### El problema serio: el tamaño de muestra

La tabla se calcula sobre **18 partidos**. La propia ficha ya avisa de que un
porcentaje sobre esa cantidad se mueve mucho. **Escribir «juega esta línea»
sobre 18 partidos sería exactamente lo que este proyecto lleva veinte versiones
desmontando.**

Propuesta, en este orden:

1. **Ampliar la muestra** como sugiere el encargo: H2H + últimos 5-10 de cada
   equipo en competiciones comparables. Objetivo mínimo 40-60 partidos.
2. **Encoger hacia la media de la liga**, igual que se hace con `bf_apertura`:
   con 18 partidos, la frecuencia cruda es ruido; encogida, es una estimación.
3. **Validar antes de recomendar.** Backtest sobre el histórico de córners que
   ya se descarga: ¿la frecuencia empírica predice mejor que la media de la
   liga? ¿El EV contra el precio de Playdoit sale positivo con p5 positivo?
4. **Sólo entonces** poner el «✅ Juega esta línea». Si el p5 sale negativo, la
   tabla se queda como está: informativa y honesta.

Tarjetas: sin precio en Playdoit, la tabla se queda descriptiva y se dice.

---

## 5. Interfaz — el H2H visual

`estilo_ui` ya tiene 20 componentes y 109 llamadas. **No hace falta ninguna
librería nueva**, y añadirla tendría coste real:

| opción | veredicto |
|---|---|
| **SVG en línea en `estilo_ui`** | **recomendada.** Cero dependencias, control total del tema oscuro, responsive con `viewBox`, y coherente con lo que ya hay |
| Altair | viene con Streamlit, pero su tema no casa con el propio y en móvil deja mucho aire |
| Plotly | dependencia nueva y pesada, ~3 MB de JS por página. Para cuatro barras no compensa |
| Chart.js | exige `components.html`, que rompe el tema y el ancho |

Componentes a añadir, todos en SVG:

- **Barra apilada** de victorias/empates/derrotas del cruce.
- **Línea de tiempo** de los últimos resultados como puntos de color (V/E/D),
  el más reciente a la derecha.
- **Barras comparadas** por equipo: goles, córners y remates por partido.
- **Indicador de racha**, sólo cuando es inequívoca (3 de los últimos 5).

Móvil: una columna por debajo de 768 px, y las etiquetas por dentro de la barra
para no depender del ancho.

Métrica de éxito: que la ficha responda «¿quién llega mejor?» sin leer una
tabla. Se comprueba con el mismo método de siempre — buscar el texto en el
render, no sólo que la función devuelva algo.

---

## 6. Secciones y parlays

### Lo que se puede hacer ya

- **Renombrar la Sección 2** a algo que se entienda: «No jugar en solitario —
  sólo como pata», con icono de aviso. Barato y claro.
- **Texto educativo** en la sección, con el porqué medido.

### Lo que se pide y no se puede dar

> «Cuando el usuario seleccione varios picks de la Sección 2, la app debe
> sugerir un parlay con un EV positivo calculado».

**Aritméticamente imposible.** `EV_parlay = Π(1 + EVᵢ) − 1`, y todos los picks
de la Sección 2 tienen EV negativo o no medido por definición — es lo que los
puso ahí. Tres patas al −4,76 % dan **−13,62 %**. Combinar no arregla el
problema: lo multiplica.

Lo que sí se puede hacer, y es lo que ya dice la bitácora:

- El parlay **parte siempre de la Sección 1**.
- Se admite **como mucho una** pata de la Sección 2, y sólo por encima del
  85 % de probabilidad, para inflar la cuota sin hundir la conjunta.
- Al añadirla, la app enseña **cuánto empeora** el EV del boleto, no un número
  positivo inventado.

El selector de patas y el EV conjunto en vivo sí son útiles y se pueden
construir sobre `clasificador.ids_para_parlay`, que ya implementa esa regla.

---

## Prioridad propuesta

1. **Corregir el texto falso de córners** (§4). La app está impidiendo usar un
   mercado que existe. Es una línea.
2. **Avisar de que el prop del abridor no existe en Playdoit** (§1, opción C).
   Afecta a apuestas que se están recomendando hoy.
3. **Comprobar si Playdoit sirve props de jugador aparte** (§1, opción B).
   Media tarde, y decide si §1 vive o muere.
4. **Renombrar la Sección 2 y el texto educativo** (§6). Barato.
5. **Córners: ampliar muestra, encoger y validar** (§4). El primero con trabajo
   de medición de verdad.
6. **H2H visual** (§5).
7. **KBO: comprobar si Naver da salidas individuales** (§2). Si no las da, se
   cierra la sección con eso.

Lo que **no** entra hasta que haya medición: recomendar líneas de córners,
llevar el descuento de 2 puntos a la KBO, y cualquier parlay que prometa EV
positivo con patas de la Sección 2.
