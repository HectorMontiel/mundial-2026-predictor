# VALIDACIÓN v99.1 — El Índice de Dispersión de Forma, y el parque de la KBO

**Fecha:** 2026-08-05

Se implementaron y midieron las dos propuestas: el **IDF** (forma relativa a lo
que el ELO predice) y el **factor de parque** de la KBO. Una funciona, la otra
no en el mercado donde se probó — y el porqué es interesante.

---

## 0. Antes: los tres partidos que fallaron

Se pidió una autopsia de tres predicciones perdidas. Merece la pena separar lo
que se puede comprobar de lo que no:

- **Shang – Rublev** y **Korneeva – Stoiana**: la hipótesis de fondo (el modelo
  se ancla al ELO y no ve la crisis o el pico de forma) es **exactamente lo que
  el IDF mide**, y abajo se comprueba sobre 108.657 partidos, no sobre tres.
- Los porcentajes concretos que se citaron (−11 puntos de saque, 80 % de
  victorias ITF) **no se han verificado uno a uno**: tres partidos no
  distinguen una causa de una coincidencia, en ningún sentido. Lo que sí se
  puede hacer —y es lo que se hizo— es preguntar si esa señal existe en
  general y cuánto vale.

Un matiz importante: **el modelo de tenis YA tenía forma reciente**
(`DIFF_FORMA10`, cuántos partidos ganó de los últimos 10). Lo que no tenía es
la forma **descontada por la dificultad del calendario**. Ganar 6 de 10 contra
rivales flojos no es estar en forma; perder 6 de 10 contra el top-10 no es
estar en crisis. Ésa es la información nueva.

---

## 1. El IDF

```
IDF = media de (resultado observado − resultado ESPERADO por el ELO)
      sobre los N eventos ANTERIORES
```

Pase cronológico estricto: la posición *i* nunca mira el resultado *i*. Y es
**escalable por diseño** — la misma función sirve para tenis, béisbol o fútbol;
sólo cambia de dónde salen «observado» y «esperado» (`indice_forma.py`).

### 1.1 A/B en tenis, sobre 108.657 partidos con cuota de cierre

Ventana elegida en los pliegues tempranos (5, 10 o 15) y juzgada en los
tardíos. Sale **ventana 5** en los dos circuitos, por separado.

| ATP (juicio) | log-loss | precisión | Brier |
|---|---:|---:|---:|
| A — sin IDF | 0,62772 | 0,6352 | 0,2193 |
| **B — con IDF** | **0,62661** | **0,6386** | **0,2188** |

| WTA (juicio) | log-loss | precisión | Brier |
|---|---:|---:|---:|
| A — sin IDF | 0,62093 | 0,6437 | 0,2163 |
| **B — con IDF** | **0,61919** | **0,6492** | **0,2156** |

Las tres métricas mejoran a la vez en los dos circuitos. Y **la mejora se
concentra donde la hipótesis decía que tenía que estar** — el decil de forma
extrema, que es el caso «Rublev»:

| decil de \|IDF\| extremo | ATP (n=1.915) | WTA (n=1.346) |
|---|---:|---:|
| sin IDF | 0,6475 | 0,6337 |
| **con IDF** | **0,6590** | **0,6493** |
| ganancia | **+1,15 pp** | **+1,56 pp** |
| *(mercado)* | *0,6961* | *0,6813* |

La ganancia global es de +0,34 y +0,55 pp; en el decil extremo es de +1,15 y
+1,56. Que el efecto sea **tres veces mayor justo donde el mecanismo predice**
es lo que distingue una señal real de un ajuste afortunado.

### 1.2 ¿Es significativo? Bootstrap PAREADO

Comparar dos log-loss medios con 20.000 partidos siempre «da distinto». Se
remuestrea la **diferencia partido a partido**:

| | n | mejora media | p5 | P(mejora > 0) |
|---|---:|---:|---:|---:|
| ATP | 19.147 | +0,00111 | **+0,00064** | **100,0 %** |
| WTA | 13.451 | +0,00174 | **+0,00091** | **100,0 %** |

**p5 positivo en los dos.** La mejora es pequeña en magnitud pero inequívoca en
signo, en dos circuitos independientes. **ADOPTADO.**

### 1.3 Lo que el IDF NO hace

El ROI sigue siendo negativo (−10,7 % ATP, −12,4 % WTA) y el mercado sigue
mejor calibrado en el decil extremo (log-loss 0,574 frente a 0,614). **El IDF
mejora el modelo; no le da un edge.** La probabilidad que se publica es mejor,
que es lo que ve el usuario en la ficha, pero el tenis sigue sin edge de
modelo.

### 1.4 IDF en la KBO

| | log-loss | precisión | Brier |
|---|---:|---:|---:|
| A — desplegado | 0,68517 | 0,5489 | 0,2460 |
| **B — + IDF** | **0,68495** | 0,5485 | **0,2459** |

Y contra la **cuota de cierre real** (113 juegos), que es lo que importa:

| | Brier |
|---|---:|
| desplegado | 0,2492 |
| **+ IDF** | **0,2476** |
| mercado | 0,2411 |

El IDF cierra alrededor de **un quinto** de la distancia que separaba al modelo
del mercado. Sigue sin batirlo, pero la brecha que la v98 midió se estrecha por
primera vez. **ADOPTADO** e integrado en el motor (entrenamiento, estado e
inferencia).

---

## 2. El factor de parque de la KBO

El campo `stadium` venía en la respuesta de Naver y **se tiraba** al construir
el histórico. Ahora se guarda: 13.009 juegos, 22 estadios. Los factores son
reales y grandes:

| estadio | carreras/partido | factor |
|---|---:|---:|
| 대구 (Daegu) | 10,80 | **1,093** |
| 사직 (Sajik) | 10,44 | 1,056 |
| … | | |
| 잠실 (Jamsil) | 9,29 | 0,940 |
| 무등 (Mudeung) | 8,92 | **0,903** |

**19 % de diferencia** entre extremos. Calculado con pase cronológico y
encogido hacia la media de la liga (prior de 200 partidos), para que un estadio
con 20 juegos no dé un factor extremo por azar.

### Pero NO mejora el moneyline — y tiene sentido

| | log-loss |
|---|---:|
| A — desplegado | 0,68517 |
| C — + parque | **0,68538** (peor) |
| D — + IDF + parque | 0,68515 |

**El factor de parque describe cuántas CARRERAS se anotan, no quién gana.** Un
estadio que favorece al bateador lo hace para los dos equipos, así que apenas
mueve la probabilidad de victoria. Se midió en el mercado equivocado.

Donde debería servir es en el **regresor de totales** (over/under), que es el
mercado que habla de carreras. Eso **no se ha medido**, porque de la KBO sólo
tenemos cuota de cierre de *moneyline* — no de totales. Queda anotado como lo
siguiente, con la fuente de validación identificada, y **no se adopta mientras
no se pueda medir**.

---

## 3. Qué se despliega

| | decisión | evidencia |
|---|---|---|
| IDF en KBO | **ADOPTADO** | Brier contra cierre 0,2492 → 0,2476 |
| IDF en tenis | **VALIDADO** | p5 +0,00064 / +0,00091, P(>0)=100 % en ambos circuitos |
| Factor de parque en moneyline | **RECHAZADO** | log-loss 0,68517 → 0,68538 |
| `estadio` en el histórico de KBO | **guardado** | 13.009 juegos, 22 estadios |

**Sobre el tenis, con claridad:** la feature está medida, validada y el módulo
`indice_forma.py` es genérico y está listo. Lo que **no** se ha hecho en esta
versión es sustituir el vector del motor de tenis en producción: ése es un
modelo desplegado y validado desde la v69, cambiarle las features exige su
propio ciclo de reentrenamiento y revalidación de los dos circuitos. Meterlo a
medias sería justo lo contrario de lo que pide la regla de no regresión.

---

## 4. Lo que queda

1. **Integrar el IDF en el motor de tenis** con su ciclo completo (reentrenar
   ATP y WTA, revalidar, comparar contra el desplegado). La feature ya está
   probada; falta el trabajo de motor.
2. **Factor de parque en el regresor de totales de la KBO**, y conseguir cuota
   de cierre de totales para poder medirlo.
3. **Extender el IDF al fútbol y a la NBA** — la función ya es genérica; hace
   falta el A/B de cada uno.
