# VALIDACIÓN v71 — Cuotas universales, datos al día y el porqué del ROI negativo

**Fecha**: 2026-07-28 · **Entorno**: `.venv` Python 3.12.10, Windows

---

## Resumen ejecutivo

| Problema reportado | Causa real | Estado |
|---|---|---|
| «Sin cuota en vivo» en casi todo | **Cuota mensual de The Odds API agotada** (0 de 500) | ✅ Resuelto con fuentes sin cuota |
| «Sin datos desde hace 68 días (pretemporada)» | **Bug: julio se saltaba** en toda liga de formato ESPN | ✅ 2.925 partidos recuperados |
| Liga MX mostraba 2 partidos | Ventana de fixtures de 3 días | ✅ Semana en curso |
| Capa 1 vacía | Horizonte del barrido a 72 h + EV inflado | ✅ Horizonte por cuotas + calibración |
| Remates por equipo en las combinadas | Mercado que ninguna casa lista | ✅ Sustituido por props de jugador |
| ROI negativo (−21,7 % / −15,6 % / −11,8 %) | **Sobreconfianza en el pick, +4 a +13 pp** | ✅ Diagnosticado y corregido |

---

## 1. Las cuotas: la cuota estaba agotada, no faltaba cobertura

`x-requests-remaining: 0` de 500. La arquitectura gastaba **una petición por
liga** y hasta 3 capturas diarias: con ~20 ligas el saldo se funde en días.

Y la premisa de partida era falsa: Liga MX, Brasil, Rusia y Argentina **sí**
están activas en The Odds API. No era cobertura, era saldo.

### 1.1 La solución: fuentes sin cuota

`cuotas_multi.py` con tres eslabones, ninguno con límite de peticiones:

1. **Pinnacle público** (`guest.api.arcadia.pinnacle.com`) — el endpoint que usa
   su propia web. Dos llamadas por deporte lo traen todo:

   | Deporte | Partidos con cuota |
   |---|---|
   | Fútbol | **610** |
   | Tenis | **297** |
   | MLB | 19 |
   | NBA | 18 |

   Además es la casa más eficiente del mercado: es el ancla *sharp* que el
   proyecto ya usaba para CLV y que hasta ahora no tenía en vivo.

2. **ESPN scoreboard** — viene en el mismo JSON que los fixtures: coste cero.
3. **ESPN core API** por evento como tercer eslabón.

### 1.2 El emparejador de nombres (sin esto no funciona nada)

Primer intento: **1 de 12** partidos emparejados. Pinnacle escribe «Jakub
Mensik» donde el proyecto usa «Mensik J.», y «Dynamo Moscow» donde usa «Dinamo
Moscow». Se implementó un emparejador **por deporte**:

* **Tenistas**: apellido + inicial, detectando el formato por la posición del
  punto. `Mensik J.` ↔ `Jakub Mensik`.
* **Clubes**: palabras significativas descartando relleno (`fc`, `cf`, `club`,
  `deportivo`…). `Gremio` ↔ `Gremio FBPA`, `Dinamo` ↔ `Dynamo`.
* Se exige que casen **los dos** participantes, para que un apellido común no
  cuele un partido equivocado.

Resultado sobre los mismos 12 casos: **5 de 12**, y los 7 restantes se
comprobaron uno a uno — no estaban en ningún tablón (§1.4).

### 1.3 Cobertura medida

Sobre los fixtures reales, por antelación:

| Antelación | Con cuota |
|---|---|
| **Hoy (D+0)** | **93,3 %** |
| D+1 | 74,2 % |
| D+2 | 60,0 % |
| D+3 | 33,3 % |
| D+7 | 3,4 % |
| **Ventana apostable (0-2 d)** | **74,2 %** |

Por liga en la semana: Liga MX 9/9, USL 14/14, Uruguay 8/8, Chile 8/8,
Sudamericana 8/8, Austria 6/6, MLS 15/16, Argentina Primera Nacional 16/18.

### 1.4 Dónde está el límite (y por qué no es 100 %)

Dos motivos, ambos reales y ninguno arreglable con más código:

* **Antelación**: a 5-7 días la cobertura cae al 3 %. **Ninguna casa ha abierto
  línea todavía** — publican 2-4 días antes. Los picks que aparecían «sin
  cuota» eran a 3-4 días vista.
* **Ligas sin operador**: Bolivia y El Salvador no las cubre Pinnacle ni ESPN.
  Verificado partido a partido, no supuesto.

Ahora la UI dice el motivo en vez de dejar un «sin cuota» mudo.

---

## 2. El bug de julio: 2.925 partidos perdidos

`MESES_SIN_UEFA = (7,)` en `uefa_scraper._rango_meses` saltaba julio entero.
Es correcto para las competiciones UEFA, pero `league_engine.descargar_liga`
usa ese cargador para **toda** liga de formato ESPN, y muchas son de año
natural y juegan en julio.

**21 ligas afectadas, 2.925 partidos recuperados, 15 con la fecha reciente
corregida:**

| Liga | Partidos | Última fecha: antes → ahora |
|---|---|---|
| arg_primera_nacional | +468 | 2026-06-23 → **2026-07-27** |
| usl_championship | +342 | 2026-06-25 → **2026-07-26** |
| bra_serie_b | +342 | 2026-06-30 → **2026-07-27** |
| bol_division | +223 | 2026-06-02 → **2026-07-27** |
| per_liga1 | +213 | 2026-05-31 → **2026-07-27** |
| col_primera_a | +167 | 2026-06-08 → **2026-07-27** |
| uru_primera | +149 | 2026-06-08 → **2026-07-26** |
| chi_primera | +136 | 2026-06-19 → **2026-07-27** |
| ecu_liga_pro | +134 | 2026-06-02 → **2026-07-28** |
| par_division | +114 | 2026-05-24 → **2026-07-26** |
| rus_premier | +92 | 2026-05-17 → **2026-07-26** |
| sudamericana | +80 | 2026-05-29 → **2026-07-24** |
| crc_fpd | +71 | 2026-05-17 → **2026-07-26** |
| mex_expansion | +68 | 2026-05-31 → **2026-07-26** |
| slv_primera | +32 | 2026-05-24 → **2026-07-26** |

### 2.1 El fix no bastaba: había que reentrenar

El aviso «🔴 sin datos nuevos desde hace N d» y la cuarentena de pretemporada
salen de `ultima_fecha_historico` en `team_stats_<liga>.json`, que **solo se
reescribe al entrenar**. Sin ese paso el código estaba bien pero la app seguía
mintiendo. Se reentrenaron las 21.

**Verificación final: 15 ligas con estado fresco; 5 siguen antiguas y están en
parón REAL** — Austria (arranca en agosto), Libertadores (entre fases), AFC
Champions, Copa de Brasil y Venezuela. Comprobado contra el scoreboard de ESPN:
tampoco ahí hay partidos recientes. Esa es justo la distinción que faltaba:
ahora «sin datos» significa parón de verdad.

---

## 3. Capa 1 vacía: dos causas encadenadas

### 3.1 El horizonte cortaba ligas enteras

El barrido cortaba a 72 h. Al ampliar los fixtures a la semana, **Liga MX
quedaba fuera**: juega el 1 de agosto y el barrido del 28 de julio la
descartaba, así que aparecía como «sin partidos evaluados» aunque sus 9
partidos ya tuvieran cuota real.

**Corrección**: el horizonte lo marca el mercado, no el calendario. Si una casa
ya abrió línea, el partido se evalúa; si no, no hay EV que calcular. Partidos
evaluados: 62 → **71**.

### 3.2 El EV estaba inflado — y esto explica el ROI negativo

Al medir el modelo contra la probabilidad justa de Pinnacle (su cuota sin
margen) sobre **315 selecciones**:

* Sesgo **global**: **0,0000**. El vector completo de probabilidades está bien
  calibrado.
* Sesgo **en la selección que el modelo elige**: positivo en 10 de 15 ligas.

| Liga | Sesgo del pick | MAE | corr | ROI reportado |
|---|---|---|---|---|
| aut_bundesliga | **+13,1 pp** | 0,113 | 0,47 | — |
| brasil | **+9,6 pp** | 0,097 | 0,37 | — |
| chi_primera | **+6,7 pp** | 0,081 | 0,32 | — |
| usl_championship | **+5,3 pp** | 0,081 | 0,69 | — |
| liga_mx | +4,1 pp | 0,125 | 0,51 | **−11,8 %** |
| mls | −2,4 pp | 0,069 | 0,79 | −15,6 % |
| uru_primera | −7,5 pp | 0,058 | 0,95 | — |

**Correlación global con Pinnacle: 0,70.** El modelo lleva señal real; lo que
falla es el **nivel del lado que escoge**.

Es la maldición del ganador de manual: al quedarte con el argmax te quedas con
la selección donde tu ruido fue más favorable. Como el EV se calcula
`cuota × p_modelo − 1`, con el pick inflado 4-13 puntos **el EV sale positivo
en apuestas que en realidad son negativas**. Encaja con los ROI observados.

**Corrección** (`calibracion_mercado.py`): cuando hay cuota de Pinnacle, la
probabilidad se encoge hacia el mercado, `p = w·p_modelo + (1−w)·p_pinnacle`,
con `w` por liga derivado del sesgo medido y moderado por el tamaño de muestra
(`min(1, n/20)`), y con suelo en 0,45 para que el modelo nunca desaparezca.

Los `w` actuales son conservadores (0,885-0,993) porque las muestras son de 4 a
11 partidos. **Es deliberado**: con esa n el propio sesgo está mal medido. El
diagnóstico es reejecutable y el peso se afinará solo según se acumulen días.

### 3.3 Lo que NO funcionó: line shopping con dos casas

Se implementó `valor_vs_sharp()` para buscar dónde una casa blanda paga por
encima del justo de Pinnacle. Resultado sobre 47 partidos con 2+ casas:
**0 selecciones con valor ≥2 %**.

Es esperable y conviene decirlo: con solo Pinnacle y DraftKings no hay line
shopping posible — DraftKings es retail y su margen es mayor. **El line shopping
necesita más casas**, y esa es la razón real por la que conseguir un tercer
operador gratuito sigue siendo la palanca pendiente (§6).

---

## 4. Remates: props de jugador en vez de totales de equipo

Los totales por equipo y de partido («Más de 9.5 remates a puerta») **ninguna
casa los lista**. Se han quitado del generador de combinadas **y de la
plantilla**; quedan solo las medias como contexto.

En su lugar, props de jugador con datos **observados** de los rosters de ESPN
(no estimados desde el xG): reparto del volumen del equipo según los remates
por partido reales de cada jugador, y probabilidades Poisson.

Ejemplo real (Puebla vs Guadalajara Chivas, 54 campos, **48 props**):

```
Remates totales (media)                        18.9
Puebla remates (media)                         10.0
Emiliano Gomez (Puebla) — remates esperados     3.89
Emiliano Gomez (Puebla) — 1+ remate            98.0 %
Emiliano Gomez (Puebla) — 2+ remates           90.0 %
Emiliano Gomez (Puebla) — 3+ remates           74.6 %
Emiliano Gomez (Puebla) — 1+ remate a puerta   64.9 %
Emiliano Gomez (Puebla) — 2+ remates a puerta  28.2 %
```

Aplicado a todas las ligas con mapeo a ESPN.

---

## 5. UI: fuera los pasos manuales

* Sin botón «⬇️ Cargar»: elegir el partido carga equipos y datos (todos los
  deportes y ligas).
* Sin botón «💰 Traer cuotas reales ahora»: se descargan al abrir el
  desplegable, con caché de 30 minutos.
* Tabla comparativa por casa y **mejor precio** por selección.
* Aviso de familia de modelo y de encogimiento de λ (v70).

---

## 5.bis La tercera casa: investigación y resultado

El §3.3 dejaba claro que con dos casas el line shopping era imposible. Se
investigaron **nueve** fuentes gratuitas de cuotas en tiempo real:

| Fuente | Resultado | Detalle |
|---|---|---|
| **Bovada** | ✅ **ADOPTADA** | 200 · **904 partidos de fútbol** en 126 competiciones y **312 de tenis**, con cuota DECIMAL directa |
| Kambi (Unibet/888) | ❌ | 200 pero solo 185 eventos, mayoría esports y amistosos; catálogo filtrado al mercado británico |
| Smarkets | ❌ | 403 |
| Betfair | ❌ | 403 en el árbol de navegación y en el endpoint de precios |
| Betano | ❌ | 403 |
| 1xBet | ❌ | 404 en el feed de líneas |
| Betsson | ❌ | 200 pero devuelve HTML, no JSON |
| Marathonbet | ❌ | 200 pero devuelve HTML |
| BetExplorer | ❌ | HTML puramente JS: **0 filas de cuotas en 738 KB** |

### Por qué Bovada era la que encajaba

No es solo que responda: es que cubre **justo lo que a Pinnacle le faltaba**,
que es el criterio que importa para este proyecto (fuerte en Latinoamérica):

| Liga | Pinnacle | Bovada |
|---|---|---|
| El Salvador | **nada** | ✓ |
| Costa Rica | — | ✓ |
| Paraguay | — | ✓ (Primera y Segunda) |
| Ecuador | — | ✓ |
| Perú | — | ✓ |
| Chile | — | ✓ |
| Rusia Premier | 6 eventos | **15 eventos** |

### Efecto medido

**Cobertura global: 56,6 % → 65,4 %.**

| Liga | Antes | Después |
|---|---|---|
| argentina | 44,4 % | **96,3 %** |
| rus_premier | 62,5 % | **100 %** |
| mls | 93,8 % | **100 %** |
| chi_primera | 100 % | 100 % |
| ecu_liga_pro | 75,0 % | 87,5 % |

**Line shopping: de 0 a 2 oportunidades reales.** Sobre 92 partidos con 2+
casas aparecen dos selecciones con valor ≥2 % (ambas +3,0 %: DraftKings pagando
1,80 donde el justo de Pinnacle es 1,75, y 1,54 donde el justo es 1,50). Son
pocas, pero son **edge de verdad y de baja varianza**: no dependen de que el
modelo acierte más que el mercado, solo de que dos casas discrepen. Entran en
Capa 1 marcadas como `valor_mercado`.

Capa 1 pasa de 1 a **3 picks**, uno de ellos line shopping puro.

### Lo que sigue sin cubrir

**Bolivia y Venezuela: ninguna de las nueve fuentes les pone precio.** No es un
límite del código sino del mercado — son ligas que ningún operador internacional
cotiza. Se documenta como tal y la UI lo dice.

El Salvador queda en 1 de 10 no por fallo de emparejado (ese único partido casó
bien) sino porque Bovada aún no ha publicado los otros nueve.

---

## 6. Qué queda pendiente y por qué

**Umbrales de Capa 1 por liga.** El diagnóstico de §3.2 dice que el problema
principal era la calibración, no los umbrales; tocarlos antes de corregir el
sesgo habría sido optimizar sobre una métrica inflada. Con la corrección puesta,
el backtest de umbrales por liga es el siguiente paso natural y ahora sí
significativo.

**Validación del ROI corregido.** El efecto de la calibración sobre el ROI real
no se puede medir hoy: hace falta acumular apuestas cerradas con las
probabilidades ya corregidas. El diagnóstico es reejecutable a diario.

---

## 7. Tests

`test_simetria.py`, `test_match_parlay.py` y `smoke_botones.py` en verde.

## 8. Reproducir

```bash
.venv\Scripts\python.exe _v71_cobertura_combinada.py       # cobertura de cuotas
.venv\Scripts\python.exe _v71_calibracion_vs_pinnacle.py   # diagnóstico del ROI
.venv\Scripts\python.exe calibracion_mercado.py            # tabla de pesos
.venv\Scripts\python.exe _v71_reentrenar_julio.py          # ligas afectadas
```
