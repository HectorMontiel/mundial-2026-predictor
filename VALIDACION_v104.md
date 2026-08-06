# v104 — El liquidador, el sesgo que ocultaba, y el abridor de la KBO

Cuatro frentes. Dos cierran con mejora desplegada, uno con un **no** medido y
otro con infraestructura desplegada y la feature **no adoptada**.

---

## 1. El liquidador: de 144 a 318 picks cerrados

De 545 picks registrados sólo 144 tenían resultado. Cada pick sin liquidar es
una lección que el aprendizaje continuo no llega a ver, así que esto no era
cosmético: era el cuello de botella del lazo entero.

Cuatro causas, encontradas y cerradas:

| # | causa | efecto |
|---|---|---|
| 1 | El fútbol emparejaba por **fecha exacta**; tenis y MLB tenían tolerancia desde la v93 | picks de un día de desfase, colgados |
| 2 | Los **nombres** no se reconciliaban: los picks llevan el de la casa («Atlanta Utd»), ESPN publica el suyo («Atlanta United FC») | la pareja nunca casaba |
| 3 | El mapeo difuso **cruzaba competiciones**: «Atlanta Utd» (MLS) casaba con «Atlanta», el club argentino de Primera Nacional | 93 de 103 picks de fútbol |
| 4 | **206 picks de tenis** (89 % de lo pendiente) eran de challenger e ITF, que el scoreboard de ESPN no cubre | y el proyecto YA los acumulaba en sus propios CSV |

Además, expansión de abreviaturas en `name_mapper`: tras normalizar, «atl san
luis» y «atletico de san luis» no son iguales, ni uno contiene al otro, ni
llegan al umbral 0,78. Se expanden `atl→atletico`, `utd→united`,
`dep→deportivo`… **y nada ambiguo**: «Independiente» no toca «Independiente
Rivadavia», que son clubes distintos y adivinar ahí liquidaría el partido
equivocado.

### Lo que eso destapó: sesgo de liquidación

| picks liquidados | acierto | brecha |
|---|---|---|
| 144 | 57,6 % | −10,8 pp |
| 228 | 64,9 % | −4,0 pp |
| **318** | **69,2 %** | **−2,5 pp** |

**Los números alarmantes de la v101 eran sesgo de muestreo.** Los picks fáciles
de emparejar —circuito principal, nombres limpios— eran sistemáticamente
distintos de los que se quedaban colgados. Con la muestra completa, ningún
segmento sobrevive ya a la corrección por comparaciones múltiples.

Es la corrección más importante de esta versión, y va contra lo que yo mismo
reporté hace dos versiones.

---

## 2. Aprendizaje con histórico profundo — DESPLEGADO, con un límite medido

El universo del lazo pasa a **263.702 predicciones** y la competición viaja
ahora con cada fila.

Se midió si conviene aprender también **por liga** (global → deporte → mercado
→ liga), y se **RECHAZA**:

| | log-loss | brecha |
|---|---|---|
| sin nivel de liga | **0,65913** | 0,0002 |
| con nivel de liga | 0,66053 | 0,0048 |

mejora −0,001398 · p5 −0,001718 · **RECHAZAR**

Con 76 competiciones, trocear más la muestra aprende ruido. El encogimiento
jerárquico no basta para salvarlo.

---

## 3. El modelo no bate al mercado en 1X2 — y una nota obsoleta costó un diagnóstico

Se formuló un método nuevo para el proyecto: encoger hacia el mercado en
proporción a lo que el modelo sabe de los dos equipos, `w(n) = w_max·n/(n+K)`.

| variante | log-loss | acierto | ROI |
|---|---|---|---|
| modelo solo | 1,02395 | 49,37 % | −5,11 % |
| **mercado solo** | **0,99971** | **50,78 %** | −5,46 % |
| w adaptativo | 0,99978 | 50,60 % | −5,93 % |

**ADOPTA** frente al modelo solo (p5 +0,020) y **RECHAZA** frente al mercado
solo (p5 −0,00025). En 1X2 de fútbol la probabilidad del modelo no aporta nada
sobre el precio.

**Y una corrección a mi propio diagnóstico.** Investigando por qué un pick de la
Conference mostraba 18 %, la nota de `calibracion_mercado.json` decía «Liga
ausente = w=1 = sin corrección» y llevó a concluir que esa competición publicaba
el modelo crudo. **Era falso**: la v80 ya hace caer las ligas sin peso propio al
w global. Verificado: `peso_modelo('conference_league') = 0,25`, y
`0,25·46 % + 0,75·10,5 % = 19,4 %` — **el 18 % que se mostraba ERA la
probabilidad ya corregida**. Se arregla la nota en su origen, con el respaldo
medido: sobre las 30 competiciones sin peso propio, w=0,25 mejora frente a w=1
en **+0,01729** de log-loss (p5 +0,01362) y sube el acierto del 48,85 % al
49,23 %.

---

## 4. KBO: infraestructura DESPLEGADA, feature NO adoptada

### La vía que se abrió

Statiz quedó descartado en la v102 (su `robots.txt` prohíbe la recolección
automatizada y nombra a los agentes de Anthropic). La alternativa estaba más
cerca de lo previsto: **el `gameId` ya venía en la respuesta de Naver y se
tiraba** al construir la fila. Con él, el endpoint
`/schedule/games/{gameId}/preview` de la misma API que el proyecto ya usa
devuelve, por partido y **a fecha del partido** (`gday`, sin fuga):

- ERA, WHIP, entradas, K, BB y HR del abridor de cada equipo;
- la lista de relevistas disponibles (tamaño del bullpen, no su carga).

Cobertura comprobada **hasta 2023**. Ingeridos **1.379 partidos**, 1.342 cruzados
con el histórico.

### Y el veredicto, que es un no

Primer pase, midiendo las seis señales sobre el mismo tramo en el que después se
juzgaba: WHIP (p5 +0,00086) y BB9 (p5 +0,00058) pasaban, y la pareja daba
+0,0067 con p5 +0,0012 y **+4,5 pp de acierto**.

**Eso no valía.** Elegir dos de seis señales mirando el resultado y juzgarlas en
ese mismo resultado es pesca: con seis pruebas al 5 %, que una o dos «pasen» es
lo esperable por azar.

Rehecho con la elección separada del juicio —pliegues 0-2 eligen, 3-5 juzgan y
no participan en la decisión—:

| | log-loss | acierto |
|---|---|---|
| base (ELO) | 0,68788 | 53,35 % |
| base + elegidas (WHIP, K9, BB9) | 0,68402 | **58,06 %** |

mejora +0,003868 · **p5 −0,004971** · **RECHAZAR** (n juzgados = 403)

El acierto sigue subiendo casi 5 pp, y eso es lo que hace tentador desplegarlo.
Pero el p5 no lo confirma con 403 casos, y el proyecto no despliega por
tentación.

**Qué SÍ se despliega:** `kbo_preview.py`, la ingesta cacheada. Es
infraestructura correcta y barata, no cambia ninguna predicción, y hace que el
veredicto se pueda repetir con más muestra sin volver a pedir nada a la fuente.

**Qué cambiaría el veredicto:** más temporadas. Con 1.342 partidos cruzados el
tramo de juicio son 403; la cobertura llega a 2023 y el histórico tiene 13.009
partidos, así que hay margen para triplicar la muestra ingiriendo 2021-2023.

---

## Resumen

| pieza | estado |
|---|---|
| Tolerancia de fecha en fútbol (liquidador) | **DESPLEGADO** |
| Reconciliación de nombres con catálogo por competición | **DESPLEGADO** |
| Fuentes propias de tenis (challenger/ITF) en el liquidador | **DESPLEGADO** — 89 % de lo pendiente |
| Expansión de abreviaturas en `name_mapper` | **DESPLEGADO** |
| `gameId` de KBO persistido + `kbo_preview.py` | **DESPLEGADO** |
| Histórico profundo del lazo (263.702 predicciones) | **DESPLEGADO** |
| Nota de `calibracion_mercado` corregida | **DESPLEGADO** |
| Nivel de liga en el lazo | **RECHAZADO** — p5 −0,0017 |
| `w` adaptativo por conocimiento | **RECHAZADO** frente al mercado |
| Features de abridor en el modelo KBO | **NO ADOPTADO** — p5 −0,0050 con protocolo limpio |

## Scripts

```
_v104_ab_w_adaptativo.py          encogimiento por conocimiento
_v104_ab_w_por_defecto.py         el w de las 30 competiciones sin calibrar
_v104_ab_nivel_liga.py            ¿aprender por competición?
_v104_ab_abridor_kbo.py           primer pase (elección y juicio mezclados)
_v104_ab_abridor_kbo_limpio.py    el que decide: elección separada del juicio
kbo_preview.py                    ingesta cacheada de Naver
```
