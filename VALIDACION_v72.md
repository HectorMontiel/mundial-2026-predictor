# VALIDACIÓN v72 — Por qué Capa 1 seguía vacía, y el orden de los candidatos

**Fecha**: 2026-07-28 · **Entorno**: `.venv` Python 3.12.10, Windows

Esta versión responde a cuatro preguntas concretas con evidencia, y arregla lo
que las causaba. Incluye dos hallazgos que no estaban en el guion.

---

## Resumen: antes y después

| | Antes (v71) | Después (v72) |
|---|---|---|
| Picks de tenis en Capa 1 | **0** (todo a Capa 2 «sin cuota») | **6** con cuota real |
| Partidos de tenis enlazados | 1 de 250 | **113 de 250** |
| Primer candidato de la lista | Lillestrom EV **+169,6 %** (prob 34 %) | Henan EV +15,2 % (prob **75 %**) |
| Vista de liga | 8 partidos, la mitad sin precio | Solo los que tienen cuota + fecha de vuelta |
| Props de remates en parlays | 0 | **40 seleccionables** |

---

## 1. «¿Por qué el tenis sigue en Capa 2 sin cuota?»

Era el fallo más visible y tenía dos causas encadenadas.

### 1.1 Las fuentes de cuotas de tenis estaban muertas

`_picks_tenis` usaba una cadena de resiliencia de dos eslabones:

```
The Odds API  →  Betexplorer
```

**Los dos están caídos**: The Odds API con la cuota mensual agotada (el hallazgo
de v71) y Betexplorer sirviendo HTML puramente JS. La cadena agotaba los dos y
todo el tenis caía a Capa 2 con la etiqueta «sin cuota en vivo» — aunque desde
v71 hubiera **205 partidos de tenis en Pinnacle y 138 en Bovada**.

**Corrección**: `cuotas_multi` se antepone como primer eslabón.

### 1.2 Y aun así se enlazaba 1 de 250

Con las cuotas ya disponibles, el resultado fue: **250 partidos con cuota, 249
no enlazados**. El emparejador de jugadores (`emparejar_jugador`) comparaba
cadenas con `SequenceMatcher`, y entre «Mensik J.» (como lo guarda el catálogo
del modelo) y «Jakub Mensik» (como lo publican las casas) la similitud es ~0,55,
por debajo del umbral de 0,75.

**Corrección**: se antepone la comparación por **apellido + inicial** que ya se
había escrito en v71 para `cuotas_multi`. Enlazados: 1 → **113**.

### 1.3 HALLAZGO — partidos de DOBLES colándose como individuales

Al conectar las cuotas aparecieron picks como:

```
Sara Errani / Nicole Melichar vs ...  →  Gana Katie Boulter   EV +210 %
Janice Tjen / Shuai Zhang vs ...      →  Gana Kamilla Rakhi   EV +158 %
```

Las casas publican los dobles con los dos nombres separados por `/`, y el
emparejado difuso casaba **una pareja de dobles con un jugador de individuales**.
El modelo del proyecto es de individuales: esas predicciones no significaban
nada, y su EV absurdo las habría puesto arriba del todo.

**Corrección**: se descartan los partidos cuyo nombre contiene `/`. Capa 1 de
tenis pasa de 10 (con basura) a **6 limpios**, con EV entre +12,9 % y +26,1 %:

```
Xiyu Wang vs Caty Mcnally          Gana Caty Mcnally    p=0.79  c=1.61  EV +26.1 %
Alex De Minaur vs Stefanos Tsitsipas Gana De Minaur     p=0.73  c=1.69  EV +23.9 %
Harriet Dart vs Kayla Cross        Gana Harriet Dart    p=0.70  c=1.75  EV +21.5 %
```

---

## 2. «El hándicap con EV +59 % y prob 82 % está en candidatos, no en Capa 1. ¿Por qué?»

Respuesta: **es deliberado y está bien**, aunque no se explicaba.

```python
MERCADOS_VALIDADOS_CAPA1 = {'1X2'}
```

Capa 1 solo admite mercados con **edge validado por bootstrap**. El backtest
multi-mercado del proyecto (v44) probó que Over/Under 2.5 y el hándicap asiático
**no son rentables de forma robusta**: su p5 bootstrap sale negativo, es decir,
el ROI positivo observado no se distingue de la suerte. Por eso quedaron fuera
de la capa accionable y solo aparecen como candidatos informativos.

Dicho de otro modo: ese «EV +59,3 %» del hándicap de Lillestrom no es una
oportunidad que el sistema esté desaprovechando, es un mercado donde el modelo
ya demostró no ganar dinero. Meterlo en Capa 1 sería repetir el error que causó
los ROI negativos.

---

## 3. HALLAZGO — el orden de los candidatos era exactamente el peor posible

Los candidatos se ordenaban por **EV descendente**:

```
orden = lambda t: (..., -t['ev'])
```

Y eso pone primero justo los peores picks. Lo que se veía arriba del todo:

| Pick | Cuota | Prob. modelo | EV |
|---|---|---|---|
| Gana Lillestrom | 8,00 | 34 % | **+169,6 %** |
| Gana Estudiantes Río Cuarto | 9,50 | 28 % | **+166,0 %** |
| Gana Dundee United | 5,25 | 44 % | +133,1 % |

Un EV del +169 % **no es una oportunidad, es una probabilidad rota**. Es
precisamente la firma de descalibración que v71 documentó (§3.2 de
VALIDACION_v71): el modelo cree que Lillestrom gana el 34 % de las veces cuando
el mercado le da ~12 %. Ordenar por EV bruto equivale a ordenar por *cuánto se
equivoca el modelo*, de mayor a menor.

**Corrección** — puntuación de calidad que premia el EV **dentro de la banda
creíble** y penaliza el exceso:

```
calidad = prob · min(EV, EV_EXTREMO) − 0.25 · prob · min(EV − EV_EXTREMO, 1)
```

Se pondera por probabilidad para que un 80 % al +4 % gane a un 25 % al +12 %.

**Resultado — mismos datos, orden nuevo:**

| Pick | Cuota | Prob. | EV |
|---|---|---|---|
| Henan Songshan — Menos de 3.5 | 1,54 | **75 %** | +15,2 % |
| Louisville — Menos de 3.5 | 1,53 | **78 %** | +18,8 % |
| Pittsburgh — Menos de 2.5 | 1,61 | **70 %** | +13,3 % |
| Independiente — Más de 1.5 | 1,61 | **73 %** | +17,5 % |

---

## 4. «Quiero solo los partidos que ya tengan cuota, y que me diga cuándo volver»

Implementado en `fixtures_espn.con_cuota()` y aplicado a **fútbol y al resto de
deportes**.

* Si hay partidos con cuota → se muestran **solo esos**, con un pie que dice
  cuántos de la jornada siguen sin precio.
* Si no hay ninguno → aviso con la fecha exacta de vuelta:

  > 📅 **Ninguna casa ha abierto línea todavía en Liga MX.** El próximo partido
  > es el **2026-08-05** y las casas suelen publicar 2-4 días antes: vuelve el
  > **2026-08-02** (en 5 días). Hay 9 partidos programados esperando precio.

La fecha de vuelta es `próximo_partido − 3 días`, acotada para no caer en el
pasado ni pasarse del propio partido.

Estado medido hoy: Liga MX 9/9 con cuota, MLS 16/16, Brasil 6/10.

---

## 5. «¿Los parlays incluyen remates y remates a puerta?»

**Sí.** Sobre la plantilla de un Liga MX: **179 selecciones combinables, de las
cuales 40 son props de remates por jugador** (1+/2+/3+ remates y 1+/2+ a
puerta), con su probabilidad Poisson derivada de los remates observados en los
rosters de ESPN.

Lo que **no** entra —ni debe— son los totales de remates por equipo y de
partido: ninguna casa los lista, así que se quedaron fuera en v71 tanto de las
combinadas como de la plantilla.

---

## 6. Lo que queda pendiente, con su porqué

Las tres áreas propuestas para v72+ siguen abiertas, y conviene decir por qué no
se han cerrado en esta versión en lugar de aparentar que sí:

**Recalibración semanal automática.** El diagnóstico
(`_v71_calibracion_vs_pinnacle.py`) es reejecutable y los pesos se recalculan
solos con `calibracion_mercado.py`. Falta el disparador semanal. Es trabajo
pequeño, pero sin histórico acumulado no cambiaría nada todavía: hoy las
muestras siguen siendo de 4 a 11 partidos por liga.

**Backtest de umbrales por liga.** Depende de tener histórico de cuotas, no de
código. Con las cuotas de cierre de football-data se puede hacer para las ligas
'main', pero no para las que más lo necesitan (las latinoamericanas), que es
donde están los ROI negativos.

**Histórico de cuotas.** Es el cuello de botella de los dos anteriores. Ni
Pinnacle ni Bovada exponen fechas pasadas en sus endpoints públicos —
comprobado. La vía realista es **empezar a acumular snapshots diarios ahora**
que la fuente es ilimitada: `odds_historico.db` puede reactivarse sin gastar
créditos. En dos o tres semanas habría muestra suficiente para que la
recalibración y el backtest de umbrales signifiquen algo.

Es decir: el orden correcto es acumular primero y optimizar después. Hacerlo al
revés produciría umbrales ajustados a 8 partidos.

---

## 7. Tests

`test_simetria.py`, `test_match_parlay.py` y `smoke_botones.py` en verde.
