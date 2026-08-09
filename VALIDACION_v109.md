# v109 — «Que rompan el mercado»: qué haría falta, medido

El usuario lo pidió así:

> «Quiero que rompan el mercado, no puede ser que solo 4 de 37 lo hagan.
> ¿Qué es lo que haría falta? Investígalo e implementa lo que funcione.»

Este documento es la investigación. La conclusión corta: **con los datos de
este proyecto, no hay ningún filtro ni modelo que bata al cierre de forma
robusta, y sé decir exactamente por qué.** Lo que sí hay es una palanca real, y
no es la que parece.

---

## 1. El problema no es la precisión. Es el precio.

`clv_tracker` sobre **3.306 apuestas** con cuota de cierre de Pinnacle:

| | valor |
|---|---|
| CLV medio | **−2,85 %** |
| Veces que batimos el cierre | **17,4 %** |
| ROI cuando SÍ lo batimos | **+0,79 %** |
| ROI cuando NO | **−4,19 %** |

Cinco puntos de ROI separan las dos poblaciones. El modelo es el mismo en las
dos: lo único que cambia es **a qué precio se entró**.

Esto reencuadra la pregunta. «Batir al mercado» no se consigue acertando más —
se consigue pagando menos. Y ahora mismo se paga de más el 82,6 % de las veces.

## 2. ¿Se puede saber al apostar si vamos a batir el cierre?

Si el CLV discrimina tanto, la pregunta útil es si es **predecible en el
momento de apostar**. Se probaron las tres señales que el sistema conoce en ese
instante (`_v109_clv_predecible.py`):

| señal | correlación con el CLV |
|---|---|
| EV declarado | **−0,0540** |
| Probabilidad | +0,1438 |
| Cuota | −0,1315 |

El EV está **anti-correlacionado**: cuanto más valor se atribuye el modelo,
peor precio se acaba consiguiendo. Es la misma conclusión que la v103 sacó por
otro camino (el EV declarado es un anti-indicador de acierto), ahora confirmada
sobre el precio y no sobre el resultado.

Por cuartiles, la única señal con algo de forma es la probabilidad:

| cuartil de probabilidad | n | CLV | bate el cierre | ROI | p5 |
|---|---|---|---|---|---|
| Q1 (menos probable) | 828 | −3,44 % | 17,5 % | −1,59 % | −9,82 % |
| Q2 | 827 | −3,41 % | 15,2 % | −7,06 % | −14,48 % |
| Q3 | 824 | −3,01 % | 14,2 % | −6,88 % | −13,13 % |
| **Q4 (favoritos)** | 827 | **−1,52 %** | **22,5 %** | **+2,20 %** | **−2,35 %** |

Los favoritos claros consiguen mejor precio relativo y son el único cuartil con
ROI positivo. Pero **su p5 sigue siendo negativo**.

## 3. Y filtrar por CLV tampoco aguanta

| filtro | n | ROI | **p5** |
|---|---|---|---|
| Batimos el cierre (CLV > 0) | 574 | +0,79 % | **−7,37 %** |
| CLV ≥ 1 % | 453 | −1,94 % | −10,93 % |
| CLV ≥ 2 % | 349 | −1,31 % | −11,89 % |
| CLV ≥ 3 % | 259 | +5,97 % | **−6,01 %** |
| CLV ≥ 5 % | 178 | +2,61 % | −13,02 % |

Ninguno pasa el bootstrap. Y el filtro es además **inaplicable en producción**:
el CLV se conoce cuando el partido ya empezó, no cuando se apuesta. Sirve para
diagnosticar, no para decidir.

## 4. Entonces, ¿qué SÍ funciona?

Una sola cosa, y ya estaba medida: **el line shopping al lado local**
(`_v90_line_shopping_por_lado.json`).

| lado | tramo de elección | tramo de juicio | robusto |
|---|---|---|---|
| **local** (piso 0,30) | ROI +5,09 % · p5 +1,09 % | ROI **+11,49 %** · p5 **+1,73 %** | **SÍ** |
| empate | +12,21 % · p5 +1,08 % | −7,09 % · p5 −38,91 % | no |
| visitante | +10,21 % · p5 +4,28 % | +7,92 % · p5 −5,10 % | no |

Es el **único** canal del proyecto con p5 positivo en el tramo que no se usó
para elegir. Y no depende de que el modelo acierte: depende de que dos casas
discrepen.

## 5. Lo que haría falta de verdad

No es un modelo nuevo. Es precio. Tres palancas, por orden de evidencia:

1. **Más casas en el tablón.** El line shopping vive de la dispersión, y hoy el
   sistema mira cuatro precios (Pinnacle, Bovada, Playdoit y DraftKings vía
   ESPN). La dispersión medida entre las que hay es del 9,76 %
   (`_v105_edge_line_shopping.json`) sobre sólo 219 partidos con precio
   múltiple. Cada casa nueva multiplica las oportunidades sin tocar el modelo.

2. **Capturar antes.** El CLV histórico es −2,85 % pero el reciente, el que sale
   de las fotos diarias, es **+0,52 %** con un 30 % positivo. La diferencia es
   *cuándo* se mira el precio. Apostar en cuanto abre la línea es la palanca que
   más mueve el número.

3. **Mercados más blandos.** El hándicap y los totales de ligas menores tienen
   líneas peor afinadas que el 1X2 de una liga grande. Ahora que la v106
   fotografía el hándicap en 29 competiciones, en unos meses habrá muestra para
   medirlo.

## 6. Lo que NO haría falta, y por qué

Añadir features o cambiar de familia de modelo. La evidencia:

- El ELO cross-competición se construyó entero, se validó, mejoraba sobre el
  modelo crudo (+0,0057) y **se rechazó** porque sobre la probabilidad que se
  publica no aportaba nada (p5 −0,000180): el mercado ya lo contenía (v105).
- El IDF mejora la calibración pero **no da edge** (v99.1, dicho allí).
- El modelo bate al mercado en 4 de 37 ligas — y en esas cuatro la ventaja es
  de +0,20 a +1,30 pp, dentro del ruido de la muestra.

El patrón se repite: cada señal que se añade ya está en el precio. Es lo
esperable contra un cierre eficiente, y no es un defecto de este proyecto.

**Prometer que «romperán el mercado» sería mentir.** Lo honesto es decir dónde
está el dinero medido —el line shopping— y trabajar esa palanca.
