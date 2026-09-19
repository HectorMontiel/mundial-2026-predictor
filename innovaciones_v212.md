# Innovaciones v212 — propuestas, con el dato que cada una necesita

**Contrato de toda innovación de esta lista** (§8 del encargo): módulo
separado · test propio · doc propia · `medido: False` inicial · apagable sin
tocar el resto · pasa la **misma** puerta de activación del §7 antes de salir a
pantalla.

Cada propuesta lleva una línea que suele faltar en los documentos de ideas:
**qué dato hace falta y si existe hoy.** Una idea que no se puede medir con lo
que hay no es una idea mala, pero es un proyecto distinto y más largo, y
conviene saberlo antes de empezar.

---

## Resumen: cuáles son construibles hoy

| # | propuesta | dato necesario | ¿existe? | prioridad |
|---|---|---|---|---|
| 1 | Movimiento de línea (CLV) | snapshots multi-día | **sí, 613 partidos** | **alta** |
| 2 | Desacuerdo entre casas | cuotas multi-casa | **sí, 7 casas, 155k filas** | **alta** |
| 3 | Partido trampa | ledger + cuotas | **sí** | media |
| 4 | Rachas de mercado | snapshots + cierre | parcial (613) | media |
| 5 | Scoring de contexto positivo | señales archivadas | **no** (hacia delante) | baja |
| 6 | Value oculto | tablero completo por partido | parcial | baja |
| 7 | Medir el rebote de entrenador | fechas de destitución | **sí, Wikidata** | **alta** |

---

## 1. Motor de movimiento de línea (CLV predictivo) — **la mejor apuesta**

**Qué es.** El proyecto ya guarda fotos de la cuota de partidos futuros
(`odds_store`, fase `snapshot`). Si la cuota de un lado se acorta entre la foto
de hace tres días y la de hoy, alguien con información está empujando ese lado.
Eso es *closing line value* medido antes del cierre, no después.

**Por qué encaja aquí y no es una idea genérica.** La tesis entera del
repositorio es que el precio sabe más que el modelo. El movimiento de línea es
el precio *cambiando de opinión*, que es la señal más pura de esa misma tesis.
Y no depende de que el modelo acierte, igual que la ventaja de precio.

**Dato.** `odds_historico.db`: 10.504 snapshots y **613 partidos con dos o más
fotos**. Es poco para concluir, pero suficiente para un piloto, y **crece solo**
con cada barrido: no hay que construir nada, sólo esperar.

**Cómo se mide.** Deriva = `cuota_foto_antigua / cuota_cierre − 1` por lado.
Contrastar contra el resultado real. La pregunta concreta: ¿los lados que se
acortan ganan más de lo que su cuota de apertura implicaba?

**Módulo:** `movimiento_linea.py`. **Riesgo:** muestra chica hoy; la puerta del
§7 lo dejará apagado hasta que crezca, y eso es correcto.

---

## 2. Desacuerdo entre casas como señal de riesgo

**Qué es.** Cuando 7 casas cotizan el mismo partido, la **dispersión** de sus
precios dice algo que el consenso promedio borra: un mercado donde todas
coinciden es un mercado resuelto; uno donde discrepan es un mercado con duda.

**Hipótesis medible.** La dispersión entre casas predice el error del modelo
mejor que la propia probabilidad del modelo. Si se confirma, es un sustituto
del ECE que funciona **por partido** en vez de por competición — que es la
granularidad que hoy falta: `riesgo_liga` sólo sabe decir «esta liga calibra
mal», no «este partido es raro».

**Dato.** 155.364 filas con `bookmaker`, 7 casas. Existe ya.

**Módulo:** `desacuerdo_casas.py`. **Por qué es de prioridad alta:** usa datos
que ya están, no depende de scrapers, y ataca un hueco real.

---

## 3. Detección de «partido trampa»

**Qué es.** Un partido donde el favorito es claro, la cuota es corta y aun así
el resultado sorprende más de lo normal. El encargo lo pide por nombre.

**El problema de definirlo, que hay que resolver antes de codificar.** «Trampa»
no puede definirse por el resultado —eso es mirar la respuesta—. Tiene que
definirse por rasgos observables ANTES: favorito a cuota corta + alguna de
{rival con entrenador nuevo, favorito en racha larga, competición con ECE alto,
partido intersemanal}.

**Cómo se mide.** Etiquetar partidos pasados con esos rasgos y comparar el hit
rate del favorito dentro y fuera de la etiqueta. Si no hay diferencia, la
etiqueta no existe y se descarta — que es un resultado igual de válido.

**Dato.** Ledger + cuotas: existe. **Módulo:** `partido_trampa.py`.

---

## 4. Motor de rachas de mercado

**Qué es.** No rachas de equipos: rachas **del mercado**. Si en una competición
el favorito lleva seis jornadas fallando, ¿hay información en eso o es ruido?

**Aviso honesto.** Esto es candidato claro a no encontrar nada. Las rachas de
resultados en mercados eficientes suelen ser exactamente lo que parecen:
ruido. Merece la pena medirlo justo por eso — para poder cerrar la pregunta con
un número en vez de con una opinión, como se hizo con el IVL.

**Dato.** Ledger con fecha y competición: existe. **Módulo:** `rachas_mercado.py`.

---

## 5. Scoring de «contexto positivo»

**Qué es.** Hoy `scraper_contexto.agregar` devuelve tres tramos discretos
(`respalda_escalada` / `contexto_positivo` / `insuficiente`). La propuesta es
un score continuo, ponderado por `confianza_fuente`, que pueda entrar como
feature.

**Por qué es de prioridad BAJA pese a ser fácil de programar.** No se puede
medir hacia atrás: nadie archivó las señales de contexto de un partido de 2024.
La única vía es **empezar a archivarlas hoy** y medir dentro de meses. Es
exactamente el motivo por el que la escalada de líneas salió `no_medible` en el
backtest de esta tanda.

**Lo que sí se puede hacer YA, y debería hacerse:** empezar a guardar las
señales por partido en cada barrido. Cuesta poco y es la condición necesaria
para todo lo demás. **Módulo:** `archivo_contexto.py`.

---

## 6. Value oculto

**Qué es.** Mercados secundarios (córners, tarjetas, goles por equipo, mitades)
donde las casas ajustan menos el precio porque mueven menos dinero.

**Dificultad real.** El proyecto ya sabe que ahí el EV no es fiable: `ev_no_fiable`
existe precisamente para los mercados de mitades y córners. Y el histórico de
precios de esos mercados es casi inexistente —`odds_historico.db` sólo guarda
1X2, over/under 2,5, BTTS y hándicap—.

**Veredicto:** buena idea, sin sustrato. Requiere empezar a guardar tableros
completos. **Módulo:** `value_oculto.py`, después de `archivo_contexto`.

---

## 7. Medir el rebote por entrenador — **la fruta madura**

**Qué es.** No una regla nueva: **medir la que ya existe**. `filtro_contexto`
lleva desde la v202 con la regla escrita y desde la v209 disparando de verdad,
y el efecto nunca se ha medido. El 0,15 de penalización es un número puesto a
mano.

**Por qué es la propuesta con mejor relación valor/esfuerzo de esta lista:**
- la fuente (Wikidata) da **fechas históricas** de destitución, no sólo
  actuales, así que **se puede reconstruir hacia atrás**;
- el ledger ya tiene los resultados y las cuotas de cierre;
- la regla ya está escrita, probada y enchufada.

No hay que construir infraestructura: hay que cruzar dos tablas que ya existen.

**Qué contestaría.** Si el rebote existe, cuánto vale, y si 7 días y 1,85 son
los umbrales correctos o números heredados de una intuición.

**Módulo:** `medir_rebote.py` (script de medición, no de producción).

---

## Recomendación de orden

1. **`medir_rebote.py`** — cierra una deuda abierta, datos completos, sin
   infraestructura nueva.
2. **`desacuerdo_casas.py`** — datos completos, ataca un hueco real
   (granularidad por partido).
3. **`archivo_contexto.py`** — barato, y desbloquea las propuestas 5 y 6. Cada
   día que pasa sin él es un día de datos perdido.
4. **`movimiento_linea.py`** — la mejor hipótesis conceptual, pendiente de que
   la muestra crezca.
5. `partido_trampa.py` y `rachas_mercado.py` — legítimas, y con probabilidad
   alta de cerrarse en negativo. Eso también es valor.

Ninguna sale a pantalla sin pasar los cuatro criterios del §7.
