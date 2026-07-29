# VALIDACIÓN v81 — El Kelly dinámico no era la mejora; subir la fracción fija sí

Fecha: 2026-07-29 · Remotos: `origin` (HMREY) + `upstream` (HectorMontiel)

---

## 0. Resumen

| | Antes | Después |
|---|---|---|
| Fracción de Kelly | ⅛ (decisión de prudencia, sin medir) | **¼ (medida)** |
| Capital mediano simulado | 1,760 | **2,592 (+47 %)** |
| Percentil 5 del capital | 1,178 | **1,193** |
| Probabilidad de ruina | 0,00 % | **0,00 %** |
| Caída máxima típica | 14,6 % | **27,5 %** (la contrapartida) |
| Orden de las capas | Capa 1 por EV, candidatos por EV×prob | **probabilidad descendente** |
| Aviso «picks sin calibrar» | falso desde la v80 | corregido |
| Aviso de combinadas | señalaba la causa equivocada | corregido |

---

## 1. Kelly: se pedía dinámico, y la medición dice que no

El stake salía de ⅛ de Kelly con tope del 5 % por pick. El ⅛ venía de la v27
como decisión de prudencia —bajaba la caída máxima de 24,3 % a 13,0 %— y **la
fracción en sí nunca se optimizó**. La propuesta era un Kelly dinámico que
subiera y bajara con la racha y la volatilidad recientes.

Antes de implementarlo hay que separar dos preguntas que se confunden con
facilidad: cuál es la fracción **fija** óptima, y si **hacerla dinámica** aporta
algo sobre esa base.

**Método.** Se toma la secuencia REAL de los 589 picks que producción habría
emitido, en orden cronológico, y se remuestrea con **bootstrap por bloques de
20**. El detalle del bloque no es cosmético: un bootstrap i.i.d. destruye las
rachas, que son justo lo que la política dinámica dice aprovechar — medirla así
sería amañar el experimento a favor del Kelly fijo. La política dinámica solo
mira hacia atrás (acierto de las últimas 30 apuestas ya resueltas).

| política | capital mediano | p5 | p95 | caída típica | ruina |
|---|---|---|---|---|---|
| ⅟₁₆ Kelly | 1,351 | 1,105 | 1,648 | 7,5 % | 0,00 % |
| **⅛ Kelly** (lo que había) | 1,760 | 1,178 | 2,618 | 14,6 % | 0,00 % |
| **¼ Kelly** | **2,592** | **1,193** | 5,549 | 27,5 % | **0,00 %** |
| ½ Kelly | 3,117 | **0,878** | 10,604 | 44,3 % | 0,53 % |
| 1 Kelly | 2,950 | **0,300** | 15,216 | 57,0 % | 5,03 % |
| DINÁMICA (racha, ⅟₁₆-¼) | 2,352 | 1,174 | 4,892 | 23,6 % | 0,00 % |
| DINÁMICA inversa | 1,515 | 1,083 | 1,945 | 14,2 % | 0,00 % |

**La dinámica no aporta nada.** Da 2,352 de capital mediano frente a 2,592 del
¼ liso, con el mismo p5 (1,174 vs 1,193) y la misma ruina. Acaba siendo una
forma ruidosa de promediar entre ⅟₁₆ y ¼, y el ¼ constante la domina. La
lectura de fondo es tranquilizadora: **la racha reciente no predice la
siguiente apuesta**, que es exactamente lo que uno esperaría si los picks son
aproximadamente independientes. Si la dinámica hubiera ganado, lo primero que
habría que sospechar es una fuga.

_(Se probó también la variante inversa —subir la apuesta tras rachas malas, por
si hubiera reversión a la media—. Es la peor de las dinámicas: 1,515. No hay
señal en la racha en ninguna de las dos direcciones.)_

**Lo que sí mejora es la fracción fija**: de ⅛ a ¼ el capital mediano sube un
47 % y el **p5 también mejora** (1,178 → 1,193), con ruina 0,00 % en las dos.
Que mejore el percentil 5 es lo que hace la decisión defendible: no es cambiar
riesgo por rendimiento, es que la fracción anterior estaba por debajo del punto
eficiente.

**La contrapartida, dicha claramente**: la caída máxima típica pasa de 14,6 % a
27,5 %. Eso es real y se nota en la cuenta. Se para en ¼ y no en ½ porque ahí
el p5 cae por debajo de 1,0 (0,878: en el peor 5 % de escenarios se **pierde**
dinero) y aparece ruina.

---

## 2. «Máxima Confianza»: la pregunta era buena y la respuesta, incómoda

La duda era si está bien mostrar picks donde el modelo dice 80 % y la banda
histórica acierta 58 %. Los datos de `calibracion_confianza.json` parecían dar
la razón:

| banda | n | dice | acierta | ROI | p5 |
|---|---|---|---|---|---|
| 0,70-0,75 | 72 | 71,7 % | 69,4 % | +12,63 % | −2,21 % |
| 0,75+ | 45 | 79,6 % | 57,8 % | −6,47 % | −27,09 % |

Parecía claro: poner techo en 0,75. Al medirlo sobre el ledger con el precio
que producción toma, salió **lo contrario**:

| selección | n | dice | acierta | ROI | p5 |
|---|---|---|---|---|---|
| ≥ 0,70 (actual) | 2.111 | 74,0 % | 56,0 % | +0,56 % | −5,10 % |
| 0,70-0,75 (con techo) | 1.506 | 72,1 % | 55,0 % | **−7,62 %** | −11,24 % |
| **≥ 0,75** | 605 | 78,7 % | 58,5 % | **+20,92 %** | **+3,71 %** |

La banda «mala» es la **única con edge validado**. El acierto sí es pobre
—58,5 %, el modelo sobreconfía de verdad— pero el precio lo compensa de sobra.

**Por qué las dos tablas discrepan, y por qué ninguna miente.**
`calibracion_confianza` calcula las bandas sobre la probabilidad **ya encogida**
del 1X2 (`p = w·pm + (1−w)·mk`). Los picks que aparecen en la pestaña son de
**hándicap y totales**, cuya probabilidad sale de la matriz de goles y **no se
encoge**. Son magnitudes distintas: la tabla describe una cosa y se muestra al
lado de otra.

**Conclusión: no se pone techo.** Habría eliminado la única banda rentable. Lo
que queda documentado es el error de categoría del aviso — y es la razón por la
que no se toca la selección con la tabla actual: primero hay que medir las
bandas del mercado al que se aplican.

---

## 3. Tres avisos que apuntaban al sitio equivocado

**a) «4 de 4 picks de fútbol salen SIN calibrar: sus ligas no tienen peso
medido».** Falso por partida doble desde la v80: todas las ligas tienen peso
(caen al global), y esos picks son de `valor_vs_sharp` — su probabilidad **es**
la del mercado. No es que no se calibren: es que ya son mercado puro y no hay
nada que encoger. El aviso mandaba a desconfiar precisamente de los picks mejor
anclados. Ahora los excluye del recuento.

**b) «Combinadas: hacen falta picks de dos deportes con prob ≥ 55 %».**
También apuntaba mal: hoy hay picks de tenis al 88 %, 85 % y 83 %. Lo que falta
no es probabilidad, es que **tenis y MLB no tienen edge validado** (v78) y por
eso no entran en el material de las combinadas. El aviso ahora dice el motivo
real y cuándo volverán: en cuanto el ledger valide un segundo deporte.

**c) El orden de las capas.** La Capa 1 se ordenaba por EV y los candidatos por
EV×probabilidad, así que un pick al 34 % podía salir por encima de uno al 58 %.
Ahora las tres capas van por **probabilidad descendente**, con la confirmación
sharp y el EV como desempates — no se pierde información de orden, se subordina.

---

## 4. Lo que NO se hizo, y por qué

**Modelo de dos etapas / mezcla con el mercado para tenis y MLB.** Es la
propuesta con más recorrido teórico, pero exige reescribir la arquitectura de
predicción de esos deportes y ya hay tres mediciones seguidas diciendo que el
problema de MLB no está en la forma del modelo sino en la señal disponible: las
features de equipo tocaron techo (v79), las de abridor mejoran la calidad y
**empeoran el negocio** (v80). Antes de reescribir arquitectura conviene tener
una hipótesis de qué señal nueva entra, y ahora mismo no la hay. Queda
planteado, no ejecutado — y sin fingir que está a medias.

---

---

## 5. v82 — Un bug de identidad que envenenaba cinco competiciones

Perseguir el «Combinada no disponible ahora (AttributeError)» llevó a algo
bastante peor que una combinada rota.

**Tres competiciones se llaman «Primera División»** (`argentina`,
`uru_primera`, `slv_primera`) y **dos «División Profesional»** (`bol_division`,
`par_division`). El código resolvía la liga **invirtiendo el mapa
nombre→clave**, y al invertir un diccionario gana el último:

```
reverse('Primera División') -> slv_primera   (El Salvador)
```

Así que **todo pick argentino o uruguayo se resolvía como El Salvador**, y todo
boliviano como Paraguay. Con la liga equivocada se leían:

- la **fiabilidad** (Brier histórico) de otra competición — de ahí que picks de
  River Plate salieran con «🔴 Alta incertidumbre» que era el histórico
  salvadoreño;
- la **antigüedad del estado** del modelo equivocado;
- los **umbrales de Capa 1** de otra liga;
- y en la combinada, se cargaba el motor de El Salvador y se le pedían equipos
  argentinos → `AttributeError`.

**Arreglado de raíz**: cada pick lleva ahora su `clave_liga` desde donde se
genera. El nombre visible queda solo como último recurso. Test de no regresión
que comprueba que el sistema no depende del nombre para identificar la liga.

---

## 6. v82 — El tenis vuelve a la Capa 1, y no por el modelo

Llevamos varias versiones intentando que los modelos de tenis y MLB batan al
mercado, sin conseguirlo, mientras **lo único con edge validado y estable de
todo el proyecto no usa el modelo para nada**: `valor_vs_sharp`.

La hipótesis era directa: si el edge vive en la **discrepancia entre casas** y
no en nuestra predicción, debería existir también en tenis.

**Y los datos ya estaban ahí.** tennis-data.co.uk publica en el mismo fichero
`Odd_PS` (Pinnacle) y `Odd_Max` (la mejor del mercado): 26.397 partidos ATP y
24.594 WTA. Ninguna fuente nueva.

Con el protocolo de la v80 —elegir en el 70 % antiguo, validar en el 30 %
reciente, ROI **y** p5 positivos en LOS DOS periodos—:

| circuito | configuración | elección (70 %) | validación (30 %) |
|---|---|---|---|
| **WTA** | margen 1 % + prob ≥ 30 % | n=7.909 · ROI +4,68 % · p5 **+1,70 %** | n=2.436 · ROI **+4,22 %** · p5 **+0,61 %** |
| ATP | ninguna robusta | varias positivas | **todas se hunden** |

**WTA entra. ATP no**, y no se fuerza. Hay además un motivo independiente para
desconfiar de la fuente del ATP: su `Odd_Max` supera a Pinnacle un **26,45 % de
media** con mediana 1,72 %, o sea que tiene valores atípicos extremos. Antes de
habilitarlo hay que limpiar esa columna, no bajar el listón.

**Consecuencia arquitectónica.** El veto de `validacion_deportes` es un juicio
sobre el **modelo** de un deporte. Aplicarlo a un pick que no usa el modelo lo
expulsaba por un defecto que no es suyo — y era justo lo que mantenía la Capa 1
sin tenis teniendo edge validado. Los picks de `valor_vs_sharp` quedan exentos.

Resultado en vivo: Capa 1 pasa de 4 picks (solo fútbol) a **5, con tenis WTA
incluido**.

---

## 7. v82 — Las combinadas: por qué siguen vacías, dicho con precisión

El aviso ha cambiado dos veces en dos versiones porque **la causa cambió**:
primero faltaban deportes, luego faltaba edge validado, y ahora que el tenis
vuelve a la Capa 1 lo que falta es otra cosa. Ahora el aviso lo **comprueba**
en vez de suponerlo:

> *Deportes en Capa 1: ['Fútbol', 'Tenis']. Solo Fútbol tiene picks con prob
> ≥ 55 % (11); los de los demás deportes se quedan por debajo de ese mínimo por
> pata, que existe porque una pata floja arrastra a toda la combinada.*

El pick de WTA de hoy tiene probabilidad 0,398 — es un pick de **precio**, no de
probabilidad, y como pata de combinada sería malo. Que las combinadas sigan
vacías es el comportamiento correcto, y ahora se entiende por qué sin tener que
leer el código.


---

## 8. v83 — MLB entra por la misma puerta que el tenis

El ledger no guarda ancla de Pinnacle para MLB, así que la estrategia que
devolvió el tenis a la Capa 1 no se podía medir ahí. **Pero la fuente sí tenía
con qué**: `sportsbookreviewsonline` publica el moneyline de **apertura** y el
de **cierre**, y solo se ingería el cierre.

Con los dos se reconstruye la misma estructura —precio tomable temprano contra
referencia eficiente— que es CLV puro, y es lo que la app hace de forma natural
al tomar precios con días de antelación.

**27.977 juegos**, con el cierre alineado (log-loss 0,6738 < ln 2):

| configuración | elección (70 %) | validación (30 %) |
|---|---|---|
| margen 1 % | n=7.114 · ROI +6,64 % · p5 +4,63 % | n=3.426 · ROI +4,40 % · p5 **+1,52 %** |
| **margen 2 % + prob ≥ 30 %** | n=5.474 · ROI +7,27 % · p5 **+5,05 %** | n=2.658 · ROI **+5,01 %** · p5 **+1,67 %** |
| margen 5 % | n=2.261 · ROI +9,70 % · p5 +6,00 % | n=1.209 · ROI **+10,15 %** · p5 +4,84 % |

Lo que da confianza no es ese punto concreto sino **la forma de la tabla: 16 de
las 20 configuraciones probadas son positivas en LOS DOS periodos**. En tenis
solo lo fueron 2 de 15. Eso no es un máximo afortunado, es una superficie
estable — y es la diferencia entre una regla y una casualidad.

**Matiz honesto**: la medición usa el CIERRE como referencia sharp y producción
usa a Pinnacle AHORA. No son idénticos. Lo que queda validado es el mecanismo
—el precio temprano bate al precio eficiente en MLB— y la implementación es la
misma que ya está validada en fútbol con Pinnacle como ancla.

**Estado en vivo**: hoy la vía comparó 43 partidos de MLB contra Pinnacle y
encontró **cero** con precio descolgado por encima del 2 %. Eso no es un fallo:
Pinnacle publica 26 partidos y Playdoit 38, y hoy coinciden. Para que no
parezca que la función está apagada, el barrido emite ahora una incidencia con
el recuento — «43 comparados, 0 descolgados» dice algo muy distinto de un
silencio.

