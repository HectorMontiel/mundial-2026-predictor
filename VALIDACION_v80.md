# VALIDACIÓN v80 — La Capa 1 no contenía ni un pick del modelo, y nadie había medido lo que sí contenía

Fecha: 2026-07-29 · Remotos: `origin` (HMREY) + `upstream` (HectorMontiel)

---

## 0. Resumen

La v79 cerró con una alarma: «el pick de julio no es el que se validó, porque
las ligas que juegan no tienen peso de calibración; hay que ingerir histórico
sudamericano». Esta versión empezó por comprobar ese diagnóstico antes de
ingerir nada, y **el diagnóstico era incorrecto**. La causa era otra, estaba
mucho más cerca y no hacía falta ninguna fuente nueva.

| | Antes | Después |
|---|---|---|
| Picks de fútbol con encogimiento aplicado | **0 %** | Candidatos **100 %**, Capa 1 con ancla |
| Fixtures con ancla sharp (`odd_home_pin`) | 23 de 160 | **todos los que Pinnacle cubre** |
| Ligas sin peso medido | caían a **w = 1,00** | caen al **w global (0,25)** |
| Capa 1 de fútbol | 10 picks, prob 0,199-0,579 | **6 picks, prob ≥ 0,327** |
| La estrategia que llena la Capa 1 | **nunca medida** | medida: p5 **+3,91 %** fuera de muestra |

---

## 1. El diagnóstico de la v79 estaba mal, y comprobarlo costó una tarde

Medida la cadena eslabón por eslabón (`_v80_diag_cadena.py`), la premisa
«faltan cuotas sudamericanas» no se sostiene:

| liga | partidos hoy | cuotas en el almacén | filas de ledger con cuota | diagnóstico |
|---|---|---|---|---|
| argentina | 13 | **7.193** | **1.843** | medida y NO adoptada |
| liga_mx | 7 | **5.086** | **1.311** | medida y NO adoptada |
| china | 5 | 3.612 | 899 | medida y NO adoptada |
| chi_primera | 5 | 912 | 256 | medida y NO adoptada |
| suecia | 1 | 3.733 | 932 | medida y NO adoptada |

`liga_mx` tiene **más cuotas de cierre que ninguna otra liga del proyecto** y
aun así `peso_modelo('liga_mx')` devolvía 1,00. Solo 12 ligas menores tenían de
verdad un problema de cobertura de cuotas.

Lección: la v79 dedujo la causa de un síntoma correlacionado (las ligas de
verano son sudamericanas) sin comprobar el mecanismo. Ingerir BetExplorer
habría costado días y **no habría arreglado nada** de los 31 partidos que más
pesaban.

---

## 2. Tres causas reales, en cadena

### a) Una liga sin peso medido caía a «sin corregir»

`recalibrate_from_history` calcula un `w` por liga y aplica una regla de
adopción; la liga que no la pasa se quedaba en **w = 1,00**. Eso no es
abstenerse: es elegir activamente la opción que la evidencia global descarta.
El `w` global se elige sobre 75.131 partidos y se valida en un pliegue aparte
de 14.636; el `w` por liga se decide con muestras de 52 a 124 picks, y con 38
ligas evaluadas eso son 38 decisiones tomadas sobre ruido.

Replicando el método exacto de `validacion_deportes` —line shopping y **un**
pick por partido, el del argmax— sobre las 36.006 filas de fútbol del ledger:

| política | n | ROI | p5 |
|---|---|---|---|
| **A) la que había** (sin peso → w=1,00) | 1.235 | +3,65 % | **−1,11 %** |
| **B) caer al w global** (0,25) | 589 | +5,92 % | **+0,34 %** |
| C) uniforme w=0,25 | 584 | **+6,72 %** | **+1,02 %** |

**La política A no tiene edge validado**: su p5 es negativo. Y ahí estaba la
incoherencia de fondo — `validacion_deportes` valida el fútbol aplicando un `w`
**uniforme** (de ahí el +6,72 % que el sistema exhibe), mientras producción
aplicaba `w` por liga con caída a 1,00. **Lo que se validaba no era lo que se
desplegaba.**

Se adopta B (encogimiento jerárquico: sin datos propios, se usa el previo). C
midió algo mejor, pero su ventaja descansa en tres ligas que son las únicas con
`w` distinto de 0,25: tirar su medición por 5 picks de diferencia sería cambiar
evidencia por ruido.

_(Por qué la primera medición de esto dio lo contrario: la versión inicial del
script usaba la cuota base y evaluaba los tres lados. `validacion_deportes` usa
`max(cuota, pinnacle)` y solo el argmax. Con el método propio salía «no
adoptar»; con el de producción, lo contrario. Medir con una definición distinta
a la de producción produce veredictos que no corresponden a nada.)_

### b) El ancla sharp solo llegaba a los partidos que ESPN **no** cubría

Arreglado el peso, la cobertura seguía en **0 %**. La causa era una línea en
`fixtures_espn._completar_cuotas`:

```python
if fx.get('odd_home'):
    continue
```

Tenía sentido en la v71, cuando esa función solo servía para **rellenar** el
precio que ESPN no traía. Pero desde entonces esa misma llamada es la **única**
que trae `odd_home_pin`, el ancla que activa el encogimiento. Con el
`continue`, todo fixture que ESPN sí cubría se saltaba la consulta y se quedaba
sin ancla — y los que ESPN cubre son justo los partidos populares, o sea los
que acaban produciendo picks.

Medido: **23 de 160 fixtures** llevaban ancla, pese a que Pinnacle publicaba
precio para el **73 %** de los partidos del día. Ahora se consulta siempre para
obtener el ancla y el precio de ESPN no se pisa.

### c) Exigir Pinnacle era más estricto que lo que se validó

`recalibrate_from_history.cargar` construye la probabilidad de mercado usando
Pinnacle **si está** y el cierre genérico si no, y lo deja anotado en la
columna `ancla`. O sea que el +6,72 % se midió anclando también en cuotas
no-Pinnacle. Producción, en cambio, no encogía nada sin Pinnacle — y Pinnacle
no cubre Bolivia, Colombia ni la Scottish Championship. Ahora hay ancla de
respaldo, y cuál se usó viaja en el pick para poder auditarlo.

Resultado: **candidatos 15 de 15 encogidos (100 %)**, con anclas
`{pinnacle: 14, mercado: 1}`.

---

## 3. Lo más importante: la Capa 1 no contenía ni un pick del modelo

Con todo lo anterior arreglado, los candidatos salían calibrados al 100 % y la
Capa 1 seguía en **0 %**. Persiguiéndolo apareció lo de verdad importante: los
diez picks de élite **no venían del modelo**. Venían de
`cuotas_multi.valor_vs_sharp` —el «valor de mercado» de la v71— y se añadían
**directamente** a `elite_fix`:

- no pasaban por `_mercados_del_partido`, así que nunca se calibraban;
- **no pasaban por `pasa_capa1`**, así que se saltaban el umbral de
  probabilidad, la banda de EV y el filtro de convicción;
- su `prob` no era la del modelo, sino la probabilidad justa de Pinnacle.

De ahí lo que se veía en la interfaz: **«Empate · EV +9,5 % · prob 29 %»**
presentado como pick de élite, con probabilidades de 0,199 a 0,579.

Y esa estrategia **nunca se había medido**. El +6,72 % que el sistema exhibe
sale de los picks del modelo con sus filtros; no la incluye.

### Medida por fin

Sobre las **26.647** filas del ledger con precio tomable **y** cuota de
Pinnacle, reconstruyendo la estrategia tal cual:

| margen EV | n | ROI | p5 |
|---|---|---|---|
| 0 % | 7.629 | +5,54 % | +2,81 % |
| 3 % | 4.054 | +6,42 % | +2,44 % |
| 10 % | 925 | **+16,11 %** | **+6,65 %** |

Sí tiene edge —y sobre muestras siete veces mayores que las del modelo—. Pero
quedarse con ese 10 % habría sido repetir el error que este proyecto ya
corrigió dos veces. Partiendo el histórico en 70 % para elegir y 30 % para
validar:

| configuración | 70 % (elige) | 30 % (valida) |
|---|---|---|
| margen 10 %, sin piso de prob | p5 **+10,09 %** | p5 **−9,44 %** |
| margen 5 %, sin piso | p5 +4,66 % | p5 −7,57 % |
| margen 3 %, sin piso | p5 +3,88 % | p5 −5,67 % |
| margen 1 %, sin piso | p5 +4,48 % | p5 −0,29 % |
| **margen 1 % + prob ≥ 30 %** | p5 **+3,92 %** | p5 **+3,91 %** |

Dos lecciones. **Subir el margen de EV era lo intuitivo y es lo que peor
generaliza**: el máximo del barrido se hunde de +10,09 % a −9,44 %. Y **lo que
da robustez es el piso de probabilidad, no el margen** — que encaja exactamente
con lo que se veía en pantalla: los picks al 20-29 % eran los que arrastraban
el resultado.

Con margen 1 % y probabilidad ≥ 30 % el p5 sale **casi idéntico en los dos
periodos** (+3,92 % y +3,91 %) sobre 3.009 y 1.309 apuestas. Esa estabilidad es
la señal, no el máximo.

**Adoptado.** La Capa 1 de fútbol pasa de 10 picks (prob 0,199-0,579) a **6
picks, todos con prob ≥ 0,327**. Lo que no pasa el filtro baja a candidatos con
su motivo, no se tira.

---

## 4. MLB: la calidad del abridor ya es accesible, y mueve la aguja

La v79 dejó escrito que el techo de MLB era la falta de estadística real del
lanzador, y que traerla exigía un game log por lanzador (~900 por temporada).
**Era falso.** `/api/v1/stats?stats=season&group=pitching&sportId=1` devuelve
los **873 lanzadores de una temporada en 1,2 segundos**. Trece temporadas son
trece peticiones: **10.421 filas, 2.850 lanzadores, 2014-2026**, ya en
`mlb_pitchers_temporada.csv.gz`.

Se usan sin fuga: para un partido de la temporada Y se toma el acumulado de
**todas las temporadas anteriores**, encogido hacia la media de la liga por
entradas lanzadas. (Detalle que arruina el cálculo si se pasa por alto:
`inningsPitched` viene en notación de béisbol — «198.1» son 198 entradas Y UN
OUT, no 198,1.)

| variante | n | log-loss | precisión | **ratio de dispersión** |
|---|---|---|---|---|
| BASE (9, equipo) | 8.296 | 0,6833 | 0,5647 | 0,527 |
| **CON ABRIDOR (15)** | 8.296 | 0,6828 | **0,5679** | **0,564** |
| MERCADO | 8.296 | 0,6687 | 0,5932 | 1,000 |

**El ratio de dispersión se mueve por primera vez.** La v79 probó ocho features
de equipo y ese ratio no se despegó de 0,527 con ninguna; era la señal de que
el techo estaba en las estadísticas de equipo. Con el abridor real sube a
0,564, y la precisión gana +0,32 pp.

El bootstrap pareado del log-loss da +0,00047 con IC 90 % [−0,00034, +0,00125]
— 82,8 % de remuestreos a favor, pero **toca el cero**. Por el criterio estricto
no basta.

**Lo que NO se reporta, y por qué**: la prueba de rentabilidad que escribí para
desempatar dio ROI **+31,75 %** con p5 +26,43 %. Eso es imposible en un mercado
como el de MLB, y la causa es un fallo mío: la reconstrucción emparejaba
`P[i]` con la fila `i` de las cuotas, pero `walk_forward` solo emite
predicciones desde `bordes[k]`, no desde el índice 0. **Es exactamente la misma
desalineación que fabricó el +37,68 % en la v78.** El número queda descartado.
La guardia que lo cazó fue la de siempre: desconfiar de un resultado demasiado
bueno antes que celebrarlo.

### Cerrado: la prueba de rentabilidad con el emparejamiento verificado

Rehecha recogiendo la cuota **dentro del mismo bucle que emite la predicción**
—así no hay orden que adivinar—, con la guardia de alineación de la v78 activa:

| variante | n | ROI | p5 | acierto |
|---|---|---|---|---|
| BASE (9, equipo) | 451 | **+1,65 %** | −5,82 % | 52,8 % |
| CON ABRIDOR (15) | 417 | **−2,83 %** | −10,79 % | 50,8 % |

**RECHAZADAS.** Las features de abridor **empeoran la rentabilidad**, y el
+31,75 % anterior era íntegramente el artefacto de desalineación.

Lo interesante es lo incómodo del resultado: las features mejoran la precisión
(+0,32 pp), mejoran el log-loss (aunque no de forma significativa) y son las
primeras que mueven el ratio de dispersión (0,527 → 0,564) — y aun así el
negocio empeora. **Mejor probabilidad no es mejor negocio**, que es la misma
lección que dejó el tenis en la v79, ahora con las tres métricas de calidad
apuntando en la dirección contraria a la caja.

Los datos quedan ingeridos y el experimento reproducible: si el modelo cambia,
volver a medirlo cuesta una ejecución.

---

## 4 bis. El devigado: el método que se usaba era el correcto, y ahora está medido

De este paso cuelga todo lo demás —el ancla del encogimiento, el
`valor_vs_sharp` que llena la Capa 1 y el `m_*` con el que se valida—, y la
preferencia por `potencia` estaba escrita como argumento razonable pero nunca
comprobada. Comparados cuatro métodos por log-loss contra el resultado real,
incluido el de **Shin** (el estándar académico):

| método | fútbol, cierre (n=36.006) | fútbol, Pinnacle (n=26.666) | 2 vías (n=53.685) |
|---|---|---|---|
| **potencia** (el que se usa) | **0,99926** | **0,99910** | **0,59430** |
| aditivo | 0,99930 | 0,99912 | 0,59434 |
| Shin | 0,99943 | 0,99917 | 0,59434 |
| proporcional | 1,00011 | 0,99946 | 0,59500 |

`potencia` gana en los tres. No se cambia nada... salvo una trampa: **el valor
por defecto de `devig()` era `proporcional`**, que pierde en los tres. Hoy
ningún llamador lo usa (todos pasan el método explícitamente), así que el
cambio no mueve ningún número — quita el pie del que se resbalaría el
siguiente.

---

## 5. Corrección del pie de la pestaña MLB

Decía «Retrosheet 2021-2025 · estado de equipos congelado al cierre de 2025
hasta que Retrosheet publique 2026». Desde la v79 eso es **falso en las tres
afirmaciones**: la fuente es la API oficial, el histórico llega a la temporada
en curso y el estado se refresca. Un pie que miente sobre la frescura del
modelo es peor que no tenerlo, porque el usuario decide con él. Ahora se
calcula de los datos, con semáforo de antigüedad.

---
