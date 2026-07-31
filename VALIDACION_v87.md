# VALIDACIÓN v87 — La ficha no miraba el mercado, y los modelos del CI ya abren

Fecha: 2026-07-31 · Remotos: `origin` (HMREY) + `upstream` (HectorMontiel)

Las tres tareas que quedaban abiertas tras la v86. Las tres se cierran, pero
**ninguna por el camino que se había propuesto** — y eso es parte del resultado.

---

## 1. Puebla vs Chivas, cerrado

### 1.1 La propuesta era un `w` por liga. Se midió y NO funciona

La idea era calibrar un peso de encogimiento hacia el ELO propio de Liga MX en
vez del `w=0,90` global. En la v86 se rechazó porque sólo había 20 fichas sin
mercado en ligas planas. Esa restricción era **innecesaria**: el ledger guarda
`p_home/p_draw/p_away` tal como salen del modelo, **antes** de cualquier
encogimiento, así que para estimar el parámetro da igual si el partido tenía
cuota. Con eso Liga MX pasa de ~0 filas útiles a **1.311**, y las 25 ligas
planas van de 429 a 1.843 cada una.

Medido en serio (`_v87_w_por_liga.py`), eligiendo en los pliegues 1-2 y
validando en los 3-4:

| política | parámetros | ECE | log-loss | precisión |
|---|---|---|---|---|
| sin encoger | 0 | 0,0083 | 1,03048 | 0,4886 |
| **w global = 0,95** | 1 | **0,0070** | 1,02414 | 0,4903 |
| w por tramo 0,90/0,95 | 2 | 0,0076 | 1,02341 | 0,4901 |
| w por liga (51 ligas) | 51 | 0,0091 | 1,02061 | 0,4912 |

**El `w` por liga es el PEOR en ECE.** Y la prueba que lo entierra: barajando
qué `w` le toca a cada liga, el ECE de validación sale igual o mejor que el
real el **80 % de las veces**. Sólo 20 de 51 ligas mejoran (menos que cara o
cruz), y la correlación entre lo plano que está el modelo respecto al ELO y el
`w` que se le elige es **+0,022 (p=0,88)**: el mecanismo que se suponía **no
existe**.

### 1.2 ¿Y si el modelo tiene razón cuando discrepa del ELO?

Antes de seguir ajustando pesos, la pregunta de fondo (`_v87_quien_acierta.py`).
Sobre 38.409 predicciones fuera de muestra, modelo y ELO eligen favorito
distinto en el **19,2 %** de los partidos:

| | acierto |
|---|---|
| el modelo | 36,34 % |
| el ELO | 34,89 % |
| diferencia | **+1,45 % (z = +1,84)** |

**Empate estadístico.** Seguir al ELO no habría acertado más. Y un `w` que
dependa del tamaño del desacuerdo tampoco mejora (ECE 0,0066 frente a 0,0065
del `w` fijo). Por ahí no había salida.

### 1.3 Lo que sí pasaba: la ficha no miraba el mercado

Pinnacle, con el margen quitado, pone el partido así:

| | Puebla | Empate | Chivas |
|---|---|---|---|
| **Pinnacle** | **18,8 %** | 21,8 % | **59,4 %** |
| la ficha decía | **53,6 %** | 24,8 % | 21,6 % |

Treinta y cinco puntos de diferencia contra la casa más eficiente del mercado.
Y **esas cuotas estaban en la app**: `cuotas_multi.cuotas_partido` devuelve
Pinnacle, Bovada y Playdoit para ese partido. La ficha no las usaba porque
`ClubEngine._cuotas_partido` sólo lee `odds_actuales.json` (que hoy trae 4
partidos) y porque, aunque las encontrara, sólo alimentaban al MESM y al
`blend_mercado` — configurado en **dos** ligas, `laliga` y `ligue_1`.

Es la misma incoherencia que la v80 encontró al revés: los picks se anclan al
mercado desde la v75 y la ficha no.

Medido sobre 28.555 filas del ledger con cuota utilizable (70 % con Pinnacle),
usando el `w` por liga ya validado de `calibracion_mercado`:

| | ECE | log-loss | precisión |
|---|---|---|---|
| modelo crudo (la ficha) | 0,0068 | 1,02579 | 0,4926 |
| **encogido al mercado** | 0,0090 | **0,99946** | **0,5054** |

Y donde de verdad importa — los partidos en que el modelo se aleja del mercado
más de 0,25, que es el caso Puebla (0,4 % de los partidos):

| | ECE | log-loss | precisión |
|---|---|---|---|
| modelo crudo | **0,2795** | 1,32849 | **33,6 %** |
| encogido al mercado | **0,0644** | 0,99931 | **55,5 %** |

**+22 puntos de precisión y el error de calibración dividido por cuatro.** El
ECE global sube 0,002, que es el precio de arreglar un 0,28 en la cola.

### 1.4 Resultado sobre el partido

| | Puebla | Empate | Chivas | error vs Pinnacle |
|---|---|---|---|---|
| Pinnacle | 18,8 % | 21,8 % | 59,4 % | — |
| ficha antes | **53,6 %** | 24,8 % | 21,6 % | 0,756 |
| **ficha ahora** | 27,5 % | 22,5 % | **50,0 %** | **0,188** |

El favorito mostrado pasa de Puebla a **Chivas**, y la coherencia
local/visitante pasa de INCOHERENTE a COHERENTE.

Orden de preferencia en `predecir`: **MESM > blend > mercado (v87) > prior de
ELO (v86)**. El prior de ELO queda para cuando no hay mercado en ninguna
fuente, que es donde se midió. `alpha_finder` sigue desactivando todo esto
(`prior_elo=False`), así que **los picks salen idénticos**.

Detalle de robustez: la búsqueda de cuotas tiene **presupuesto de tiempo**. El
tablón está cacheado por deporte (30 min), pero en frío `cuotas_multi._get`
puede llegar a 40 s con 3 intentos, y una ficha bloqueada dos minutos es peor
que una ficha sin anclar. Si no vuelve a tiempo se sigue sin mercado y el hilo
deja el tablón caliente para el siguiente render.

---

## 2. Hándicap asiático: ya está medido, y sin cuotas históricas

La propuesta era «construir un ledger si se consiguen cuotas históricas». **No
hacían falta.** Para calibrar se necesita la probabilidad que asigna el modelo
y si se cubrió — no la cuota.

Las dos se reconstruyen de la MISMA matriz de marcadores que usa producción. En
`alpha_finder`:

```python
p_home_cubre = float(M[diff > -linea].sum())
```

y `M` sale de `_monte_carlo(lam_h, lam_a, probs)`: un Poisson bivariado con
choque común re-ponderado para que sus marginales 1X2 cuadren con las
probabilidades calibradas. Los dos ingredientes ya estaban fuera de muestra y
con walk-forward: los λ en `pick_ledger_totales.csv` (v86) y las 1X2 en
`pick_ledger_total.csv`. Se unen por `(liga, match_id)`.

**47.794 partidos.** `build_ledger_handicap.py` calcula la matriz de forma
analítica en vez de con 20.000 simulaciones por partido (serían mil millones de
sorteos). Sustituir un método por otro sin comprobarlo invalidaría la medición,
así que se comprobó (`_v87_matriz_equivale.py`): la peor diferencia en
P(el local cubre) es **0,00606**, frente a un ruido de muestreo propio del
Monte Carlo de ~0,00354. Equivalentes.

Bandas de acierto real:

| banda | n | modelo | acierto real | sesgo |
|---|---|---|---|---|
| 0,50-0,55 | 18.269 | 52,5 % | 53,0 % | −0,5 % |
| 0,60-0,65 | 17.360 | 62,5 % | 63,3 % | −0,8 % |
| 0,70-0,75 | 20.360 | 72,6 % | 73,2 % | −0,6 % |
| ≥ 0,75 | 194.425 | 90,2 % | 89,5 % | +0,7 % |

**Es el mercado mejor calibrado de los cuatro** — tiene sentido, porque hereda
la calibración del 1X2 a través de la re-ponderación de la matriz. Para
contrastar, el BTTS tiene un sesgo de +27,4 % en la banda alta.

Estado de «Máxima Confianza» tras esto: **1X2, Ganador, Goles, BTTS y Hándicap
con medición propia**. Lo que no tiene ledger (córners, tarjetas) lo sigue
diciendo.

---

## 3. Portabilidad de los modelos: resuelto, pero no como se proponía

### 3.1 La propuesta no habría servido

«Migrar de pickle a `save_model` (UBJSON)». Medido el buffer real
(`_v87_buffer_xgb.py`, parcheando `Booster.__setstate__` para capturarlo en vez
de dárselo a la librería): **los dos modelos, el que carga y el que no, ya
están enmarcados en UBJSON**, con cabeceras idénticas byte a byte.

Así que el formato no era el problema, y cambiarlo no habría arreglado nada.

### 3.2 La causa real

Lo que guarda el pickle es el formato de **serialización**
(`XGBoosterSerializeToBuffer`), que XGBoost documenta como dependiente del
entorno. El formato de **modelo** —el de `save_model` / `save_raw('ubj')`— sí
es portable. Los dos van en UBJSON; lo que cambia es el contenido.

Medido (`_v87_extraer_model.py`):

```
save_raw(ubj)            1.209.040 bytes, empieza por {L..\x07learner
buffer de serialización  1.217.311 bytes, empieza por {L..\x06Config
```

y el segundo **contiene** al primero a partir del byte 8270. El objeto UBJSON
exterior tiene dos claves: `Config` y `Model`. `Model` es el modelo portable.

### 3.3 La reparación

`modelos_portables.py` recorta la sección `Model` y la carga con
`Booster.load_model`, que sí funciona entre plataformas.

Un detalle que costó el primer intento: **no vale buscar «learner»**. La
sección `Config` también tiene una clave con ese nombre y aparece antes (byte
16), así que el recorte salía mal. Hay que buscar la clave `Model`.

Resultado sobre los 61 modelos del repositorio:

| | |
|---|---|
| abrían antes | 18 |
| no abrían | 43 |
| **reparados y prediciendo bien** | **43 de 43** |

Y sobre los que ya abrían, la reparación **no cambia nada**: diferencia máxima
de predicción **1,7e−16**, el épsilon de la máquina.

En Linux no cambia absolutamente nada: el `joblib.load` abre a la primera y no
se llega a tocar el camino de reparación.

La prueba práctica: `smoke_botones.py` ahora pasa **con los modelos del runner
de Linux**, que es lo que no se podía hacer antes.

### 3.4 Lo que queda apuntado

El paso «Verificar que todos los modelos se pueden cargar» del workflow **no
puede** detectar esto, porque valida en el mismo entorno que acaba de escribir
los ficheros. Con la reparación en el camino de carga el problema deja de doler
en local, pero la verificación sigue sin poder afirmar lo que dice su nombre.

---

## 4. Resumen

| cambio | evidencia |
|---|---|
| La ficha se ancla al mercado | +22 pp de precisión y ECE ÷4 donde el modelo se alejaba; Puebla pasa a mostrar a Chivas |
| Presupuesto de tiempo en la búsqueda de cuotas | el tablón en frío puede tardar 120 s; la ficha no puede quedarse colgada |
| Bandas del hándicap asiático | 47.794 partidos; sesgos de −0,8 % a +0,7 % |
| `modelos_portables.py` | 43 de 43 modelos recuperados; 1,7e−16 de diferencia donde ya funcionaban |

| **rechazado** | **por qué** |
|---|---|
| `w` de encogimiento por liga | barajar qué `w` toca a cada liga da un ECE igual o mejor el 80 % de las veces; correlación con el mecanismo +0,022 (p=0,88) |
| `w` condicional al desacuerdo con el ELO | no mejora sobre el fijo (ECE 0,0066 vs 0,0065) |
| «hacer caso al ELO» cuando discrepa del modelo | empate estadístico sobre 7.361 partidos (36,34 % vs 34,89 %, z=+1,84) |
| Migrar a `save_model` para la portabilidad | el buffer YA es UBJSON; el problema era el envoltorio de serialización, no el formato |
| Esperar a tener cuotas históricas de hándicap | no hacen falta: la probabilidad sale de la matriz de goles que ya se calcula |

Las cinco suites en verde: `test_catalogo_y_cuotas.py`, `test_simetria.py`,
`test_match_parlay.py`, `smoke_botones.py` y `test_concurrencia.py`.
