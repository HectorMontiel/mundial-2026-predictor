# VALIDACIÓN v70 — Las seis mejoras pendientes (y una séptima que apareció)

**Fecha**: 2026-07-27 · **Entorno**: `.venv` Python 3.12.10, Windows

Este documento recoge los números de las seis mejoras del spec y de un hallazgo
no previsto que resultó ser el de mayor impacto de la versión. Las rechazadas se
documentan con el mismo detalle que las adoptadas (regla §2.9).

---

## Resumen ejecutivo

| Mejora | Veredicto | Efecto medido |
|---|---|---|
| **D — familia de modelo por liga** | ✅ **ADOPTADA** | 10 ligas cambian de familia; **8 pasan a batir al ELO** en walk-forward |
| **G — encogimiento de λ** *(no estaba en el spec)* | ✅ **ADOPTADA** | Desvianza de Poisson mejora en **14 de 15** ligas (−0,05 a −0,19) + MLB |
| **F — NBA** | ⚠️ **PARCIAL** | Las features propuestas fallan; el rediseño del modelo da **+1,24 pp** |
| **A — alineaciones** | ❌ No adoptada | +0,07 pp (MLS) / +0,10 pp (Liga MX): por debajo del umbral, signos inconsistentes |
| **B — portero** | ❌ No adoptada | γ = 0,000 en los 10 pliegues de ambas ligas |
| **C — P(BTTS) como feature** | ❌ No adoptada | 2 de 7 ligas superan la regla: lo esperable por azar |
| **E — MLB carreras** | ❌ No adoptada *(la parte del spec)* | El clasificador actual calibra mejor (ECE 0,0093 vs 0,0167) |

**Dos bugs de datos corregidos por el camino** (§8).

---

## 0. Fase 1 — Auditoría, antes de escribir código

Regla §2.2: verificar los datos antes de diseñar nada. Los tres specs anteriores
dieron por hechos datasets inexistentes.

### 0.1 Alineaciones de ESPN (`_v70_fase1_rosters.py`)

Muestreo de 25 partidos en cada una de 5 ventanas, de 2019 a 2026:

| Liga | rosters | 11 titulares | Stats por jugador | Portero (SV) |
|---|---|---|---|---|
| MLS · Liga MX · Premier · LaLiga · Serie A · Brasileirão | **100 %** | **100 %** | **100 %** | **100 %** |

Cobertura total en las 30 combinaciones liga × ventana. **Ningún techo de
cobertura** como el 34,5 % que hundió las features de saque en v69: si las
Mejoras A y B fallan, no será por falta de datos.

Histórico recolectado y versionado:
* `alineaciones_usa_1.csv.gz` — 153.836 filas · 3.957 partidos · 2018-03 → 2026-07
* `alineaciones_mex_1.csv.gz` — 114.116 filas · 2.836 partidos · 2018-01 → 2026-07

Tras cruzar con el histórico del proyecto (nombres normalizados con
`name_mapper` + alias explícitos para los dos equipos de Los Ángeles), la
cobertura efectiva es **92,6 % en MLS** y **77,5 % en Liga MX**.

### 0.2 Minutos de gol para BTTS de clubes

`goleadores.csv` tiene 10.354 goles con minuto, **todos de selecciones**. Para
clubes no hay minuto en ninguna fuente del proyecto. Esto condiciona el diseño
de la Mejora C (§3), no la bloquea.

### 0.3 MLB y NBA

* Retrosheet: **11.928 juegos** (2021-04-01 → 2025-09-28) con carreras por
  equipo **y abridores** (`home_pitcher`, `away_pitcher`). Suficiente.
* `nba_api` responde; `leaguegamelog` sirve FGM/FGA/FG3M/FTA/AST/TOV/OREB/DREB,
  que permiten derivar eFG, TOV%, ratio de asistencias, OREB% y tasa de tiros
  libres. **Las lesiones históricas NO existen** en fuente gratuita (§7.3).

---

## 1. Mejora D — Familia de modelo por liga ✅ ADOPTADA

### 1.1 El spec proponía una regla que los datos no sostienen

> «en `league_engine.py`, si `len(partidos) < 800`, usa `LogisticRegressionCV`»

De las 15 competiciones que perdieron contra el ELO en v68, **sólo 4 tienen
menos de 800 partidos** de entrenamiento (FA Cup 305, Sudamericana 333, ISL 476,
A-League 650). El EFL Championship pierde contra el ELO con **2.144**. El
problema no es el tamaño de la muestra sino la relación señal/ruido, así que la
familia se elige **por liga**, no por un umbral de tamaño.

### 1.2 Protocolo

Dos cambios sobre lo que hacía v68, ambos necesarios:

1. **Walk-forward expandente de 5 pliegues** sobre el 40 % final, en vez del
   split único 80/20. El split único dejaba 79 partidos de validación en la FA
   Cup: ±5,5 pp de error típico, indistinguible de ruido. Con pliegues se valida
   sobre 384–2.680 partidos según la liga.

2. **Selección secuencial de familia.** Quedarse con el mejor de seis
   candidatos mirando el propio test infla el resultado: el máximo de seis
   estimaciones ruidosas es optimista aunque ninguna familia sea mejor. Aquí la
   familia de cada pliegue se elige con el log-loss **de los pliegues
   anteriores**; el primero usa `ensemble`, el modelo ya desplegado. Es
   exactamente lo que podría hacerse en producción.

Candidatos: `ensemble` (actual) · `logistica` · `logistica_base` · `elo_logit`
(logística sobre DIFF_ELO a secas) · `blend_elo` (mezcla convexa con el peso
ajustado en un tramo interno del train) · `gbm_regular`.

### 1.3 Resultados (`_v70_wf_modelos.json`)

Precisión con selección secuencial, frente a la línea base ELO y al ensemble:

| Liga | n | ELO | ensemble | **secuencial** | Δ vs ELO | Familia |
|---|---|---|---|---|---|---|
| bra_serie_b | 1.579 | 0,4066 | 0,4668 | **0,4778** | **+0,0712** | blend_elo |
| sudamericana | 417 | 0,4311 | 0,4671 | **0,4850** | **+0,0539** | logistica |
| esp_hypermotion | 2.230 | 0,4283 | 0,4720 | **0,4821** | **+0,0538** | logistica |
| crc_fpd | 1.178 | 0,4619 | 0,5064 | **0,5064** | **+0,0445** | ensemble |
| eng_league_two | 2.670 | 0,4373 | 0,4522 | **0,4794** | **+0,0421** | logistica |
| bel_pro_league | 1.508 | 0,4818 | 0,4884 | **0,5066** | **+0,0248** | logistica |
| eng_championship | 2.680 | 0,4478 | 0,4590 | **0,4683** | **+0,0205** | logistica |
| gre_super_league | 1.156 | 0,4946 | 0,4860 | **0,5032** | **+0,0086** | blend_elo |
| ned_eerste | 1.849 | 0,4865 | 0,4541 | 0,4892 | +0,0027 | elo_logit |
| ven_primera | 1.081 | 0,4758 | 0,4642 | 0,4711 | −0,0047 | elo_logit |
| par_division | 1.126 | 0,4102 | 0,3925 | 0,4035 | −0,0067 | logistica |
| slv_primera | 1.264 | 0,4881 | 0,4506 | 0,4644 | −0,0237 | elo_logit |
| aus_aleague | 813 | 0,4356 | 0,4110 | 0,4018 | −0,0338 | blend_elo |
| ind_isl | 595 | 0,4706 | 0,4538 | 0,4328 | −0,0378 | elo_logit |
| eng_fa_cup | 384 | 0,5325 | 0,4740 | 0,4740 | −0,0585 | blend_elo |

**8 de 15 baten al ELO** con el margen de 0,005 que exige el proyecto.
`logistica` es la familia ganadora en 5 de las 8.

### 1.4 Dos matices de honestidad

* **`crc_fpd` ya batía al ELO con el ensemble** (0,5064 vs 0,4619). No cambia de
  familia: lo que falló en v68 fue el estimador, no el modelo. Lo mismo vale en
  parte para `eng_championship` (0,4590 vs 0,4478 con el ensemble). **Parte de
  la mejora de esta versión no es un modelo mejor, es una medición mejor**, y
  conviene decirlo.
* Queda un efecto de selección residual: se decide **qué ligas promover** con
  los mismos pliegues. Se mitiga exigiendo margen sobre el ELO y validando sobre
  384–2.680 partidos, pero no desaparece.

### 1.5 Implementación

* `league_engine.familia_de_liga()` lee `modelos_familia.json`. Liga ausente →
  `ensemble` de siempre: **el cambio no puede degradar nada que ya funcionase**.
* `ModeloSubconjunto` — envuelve estimadores que sólo usan algunas columnas
  (`logistica_base`, `elo_logit`), llevando el recorte DENTRO del artefacto. Sin
  esto, en inferencia habría que saber qué columnas quitar: la desalineación
  silenciosa que casi rompe el modelo WTA en v67.
* `ModeloBlendElo` — mezcla convexa, peso ajustado en un tramo del train.
* `metadata.json` guarda `familia_modelo` y ahora también `walk_forward_v70`
  (precisión, log-loss, ELO y n de validación de los 5 pliegues).
* La UI muestra la familia cuando no es el ensemble.

**Decisión de despliegue**: `disponible: True` se decide con el **walk-forward**,
no con el split único de `entrenar_liga` — que es justamente el estimador que
esta versión demostró poco fiable.

---

## 2. Mejora G — Encogimiento de λ ✅ ADOPTADA *(hallazgo, no estaba en el spec)*

### 2.1 Cómo apareció

Validando la Mejora A, el diagnóstico incluía un control: la correlación entre
(λ_local − λ_visitante) y el residuo de Pearson del margen, que debería ser ~0
si las λ estuviesen bien calibradas. Salió:

| Liga | r | p |
|---|---|---|
| MLS | **−0,193** | < 0,001 |
| Liga MX | **−0,238** | < 0,001 |

Un efecto **diez veces mayor** que el de las alineaciones y con el mismo signo
en las dos ligas. Traducido: cuando el modelo predice un margen grande, el
margen real se queda corto de forma sistemática. Los regresores Poisson
**separan demasiado** las dos λ.

### 2.2 La corrección

Encoger la diferencia hacia la media conservando el total:

```
m = (λ_h + λ_a)/2 ;  d = (λ_h − λ_a)/2
λ_h' = m + s·d    ;  λ_a' = m − s·d
```

`s` se calibra por liga en walk-forward minimizando la desvianza de Poisson
**sólo con datos de train** (con modelos ajustados en el 75 % previo, para que
`s` no se ajuste a predicciones in-sample, que lo dejarían en 1 por
construcción). `s = 1` es no tocar nada, así que la parametrización **contiene
al modelo actual**.

### 2.3 Resultados (`_v70_wf_shrink.json`)

| Liga | s | Δ desvianza | Δ precisión | Δ log-loss |
|---|---|---|---|---|
| bra_serie_b | 0,44 | **−0,19074** | −0,0221 | −0,0362 |
| crc_fpd | 0,50 | **−0,13751** | −0,0063 | −0,0335 |
| gre_super_league | 0,58 | **−0,11296** | −0,0065 | −0,0374 |
| bundesliga | 0,52 | −0,10570 | +0,0000 | −0,0181 |
| ned_eerste | 0,46 | −0,08676 | +0,0000 | −0,0255 |
| serie_a | 0,64 | −0,08731 | −0,0114 | −0,0114 |
| eng_championship | 0,54 | −0,07710 | −0,0019 | −0,0194 |
| laliga | 0,64 | −0,07551 | −0,0081 | −0,0039 |
| mls | 0,54 | −0,06959 | +0,0007 | −0,0149 |
| liga_mx | 0,60 | −0,06318 | −0,0038 | −0,0115 |
| premier | 0,50 | −0,06168 | +0,0114 | −0,0096 |
| eredivisie | 0,70 | −0,05626 | −0,0017 | −0,0060 |
| argentina | 0,50 | −0,05552 | −0,0054 | −0,0183 |
| ligue_1 | 0,68 | −0,04958 | +0,0000 | −0,0107 |
| brasil | 0,50 | −0,05549 | +0,0000 | **+0,0048** ❌ |
| **MLB** | 0,58 | **−0,00877** | — | MAE −0,0009 |

**La desvianza mejora en las 15 ligas y en MLB.** Se adoptan 14 de 15 (Brasil
queda fuera: mejora la desvianza pero empeora el log-loss derivado).
`s` cae entre 0,44 y 0,70 en todas partes — es decir, **las λ había que
acercarlas entre un 30 % y un 56 %**.

### 2.4 Criterio de adopción

La regla de oro del proyecto (§2.1) está escrita para la precisión del 1X2, y el
1X2 de producción **no sale de λ** sino del clasificador: λ gobierna la matriz de
marcadores, el marcador exacto y los mercados de goles. Lo que hay que exigirle a
λ es que describa mejor los goles, y se piden las dos cosas: **menos desvianza de
Poisson** (el ajuste directo) y **que no empeore el log-loss del 1X2 derivado**
(que no se degrade nada aguas abajo). La precisión se reporta pero no decide.

### 2.5 Implementación

`distributions.encoger_lambdas()`, leyendo `lambda_shrink.json`. Se aplica en
`ClubEngine.predecir()` y en `MLBEngine.plantilla_mlb()`. Liga ausente → `s=1` →
λ intactas. La UI avisa cuando el encogimiento está activo.

---

## 3. Mejora C — P(BTTS) como feature del 1X2 ❌ NO ADOPTADA

### 3.1 El obstáculo y cómo se rodeó

El AFT de v26 se ajusta con el **minuto** del primer gol recibido, y ese dato
sólo existe para selecciones (§0.2). Pero con todas las observaciones censuradas
en t=90, el Weibull AFT evaluado en 90 es exactamente

```
P(encajar) = 1 − exp(−exp(β·x))
```

es decir, una regresión binomial con enlace **complementary log-log**: la misma
familia de valor extremo y la misma asimetría que le daba ventaja de calibración
sobre Poisson en v27 (Brier 0,2358 vs 0,2516). Sólo se pierde la forma temporal
`k`, que no interviene en la probabilidad a 90 minutos.

### 3.2 Un bug que habría invalidado la medición

El atajo evidente —reutilizar `WeibullAFT.fit` con `t=90` y `k=1`— **no es
equivalente y da un modelo mal calibrado**. La verosimilitud censurada carga
`H(90)` completo también a las filas con evento (les está diciendo que encajaron
exactamente en el minuto 90), y eso la convierte en una verosimilitud de
**Poisson**: el estimador iguala `E[exp(η)]` a la tasa de eventos en vez de
igualar `E[P]` a esa tasa.

| | P(BTTS) media | BTTS real |
|---|---|---|
| Atajo (verosimilitud censurada) | 0,2517 | 0,5208 |
| **Verosimilitud binomial correcta** | **0,4848** | 0,5208 |

Cazado antes de juzgar la feature, en aplicación de la regla §2.4. Documentado
en el código para que no se repita.

### 3.3 Resultados (`_v70_wf_btts.json`)

Cobertura de la columna: **85–91 %**. Walk-forward de 5 pliegues, misma rama
salvo la columna:

| Liga | sin BTTS | con BTTS | Δ precisión | Δ log-loss | Regla |
|---|---|---|---|---|---|
| laliga | 0,5371 / 1,0256 | 0,5412 / 1,0235 | +0,0041 | −0,0021 | ✅ |
| mls | 0,4681 / 1,0412 | 0,4743 / 1,0411 | +0,0062 | −0,0001 | ✅ |
| premier | 0,4817 / 1,0961 | 0,4817 / 1,0970 | +0,0000 | +0,0009 | ❌ |
| serie_a | 0,5342 / 1,0898 | 0,5342 / 1,0909 | +0,0000 | +0,0011 | ❌ |
| liga_mx | 0,5162 / 1,0408 | 0,5153 / 1,0077 | −0,0009 | −0,0331 | ❌ |
| bundesliga | 0,5177 / 1,0181 | 0,5076 / 1,0194 | −0,0101 | +0,0013 | ❌ |
| ligue_1 | 0,5283 / 1,0522 | 0,5283 / 1,0451 | +0,0000 | −0,0071 | ❌ |

**2 de 7 superan la regla.** Con siete comparaciones y una regla que exige que
ambas métricas mejoren, eso es aproximadamente lo esperable por azar. El
proyecto tiene precedente de adopción por liga (CASTIGO_NARRATIVO en v27), pero
aquí la evidencia no lo justifica: **no se adopta**, ni siquiera en LaLiga y MLS.

Es además el resultado razonable a priori: P(BTTS) es una transformación de
covariables (ataque rival, defensa propia, ΔELO, localía) que el ensemble ya
tiene, y un modelo de árboles aproxima transformaciones no lineales sin ayuda.

El código queda en `supervivencia_btts.py` (`prob_btts`, `ajustar_cloglog`,
`serie_btts_sin_fuga`) y es directamente reutilizable para el **mercado** BTTS
de clubes, que es donde la calibración del cloglog sí puede aportar.

---

## 4. Mejora A — Ajuste por alineaciones confirmadas ❌ NO ADOPTADA

### 4.1 Lo implementado

`lineup_impact.py`: recolección incremental desde ESPN, rating rodante por
jugador (`goles + 0,5·asistencias + 0,3·remates a puerta` en sus últimas 5
titularidades, imputando con la mediana de su posición), fuerza de alineación,
y `adjust_lambda()` con topes de seguridad (±30 % sobre λ).

### 4.2 Resultados (`_v70_wf_lineup.json`)

Walk-forward de 5 pliegues; β calibrado por desvianza de Poisson sólo con train:

| Liga | Cobertura | β | Δ desvianza | Δ precisión | Δ log-loss |
|---|---|---|---|---|---|
| MLS | 92,6 % | +0,02…+0,04 | −0,0013 | +0,0007 | −0,0003 |
| Liga MX | 77,5 % | +0,02 | **+0,0007** | +0,0010 | −0,0001 |

La mejora es de **+0,07 pp en MLS y +0,10 pp en Liga MX**: un orden de magnitud
por debajo del umbral de +0,3 pp de la regla de oro. Sólo pasa por la segunda
rama («mejorar ambas métricas»), y en Liga MX **la desvianza empeora** mientras
la precisión sube el equivalente a 2 partidos de 1.048.

### 4.3 La variante que probé por si el problema era la parametrización

Hipótesis: `lineup_diff` mide calidad **absoluta**, que el modelo ya conoce por
el ELO y la forma. La señal ortogonal sería la **rotación**: cuánto se desvía el
once de hoy del once habitual de ese mismo equipo (`lineup_delta`, media móvil
de los 10 onces anteriores del propio equipo).

No funciona: **−0,21 pp en MLS**, neutro en Liga MX.

### 4.4 El diagnóstico que cierra la cuestión (`_v70_diag_lineup.json`)

Correlación de Pearson de cada señal con el residuo del margen (lo que el modelo
de goles **no** explica ya), sobre el 40 % final:

| Señal | MLS | Liga MX |
|---|---|---|
| `lineup_diff` | +0,0611 (p=0,024) | **−0,0397** (p=0,257) |
| `gk_diff` | −0,0571 (p=0,042) | **+0,0438** (p=0,233) |
| `lineup_delta` | +0,0406 (p=0,135) | −0,0520 (p=0,137) |

**Los signos se invierten entre las dos ligas y nada es significativo en Liga
MX.** Es la misma firma que llevó a descartar la cópula gaussiana en v68 (ρ que
huye al borde de la malla) y Dixon-Coles en v27 (ρ con signo opuesto a la
teoría): parámetro óptimo con signo inconsistente = absorción de ruido.

Con cobertura del 92,6 % y 153.836 filas de datos reales, **no se puede alegar
falta de datos**. La conclusión es que el aporte ofensivo observado de los 11
titulares, agregado así, no lleva información sobre los goles que el modelo no
tenga ya por el ELO y las medias móviles.

**Qué quedaría por probar** (honestamente, no como excusa): ESPN publica el
roster **del partido jugado**. Una fuente de alineaciones **previas** al partido
—las que se anuncian una hora antes— permitiría además medir el efecto de la
*ausencia anunciada*, que es una señal distinta. No la hay gratuita hoy.

`lineup_coef.json` deja los coeficientes con `adoptado: false`;
`adjust_lambda()` lo comprueba y devuelve las λ originales sin tocar.

---

## 5. Mejora B — Impacto del portero ❌ NO ADOPTADA

`GK_index = (paradas_esperadas − goles_encajados) / partidos`, con las paradas
esperadas estimadas desde los tiros a puerta enfrentados y la conversión de la
liga. Cobertura: **66,2 % MLS · 50,6 % Liga MX**.

**γ = 0,000 en los 5 pliegues de las dos ligas**, con la malla libre entre −0,20
y +0,20. El optimizador, pudiendo elegir cualquier valor, elige exactamente
cero: no hay nada que extraer. La correlación con el residuo además cambia de
signo entre ligas (−0,057 vs +0,044) y no es significativa en Liga MX.

Rechazo inequívoco. El índice queda implementado y calculado en
`lineup_impact.construir_ratings()`.

---

## 6. Mejora E — MLB, carreras esperadas ❌ NO ADOPTADA *(la parte del spec)*

### 6.1 Sustituir el clasificador de moneyline: no

Walk-forward de 5 pliegues sobre **11.844 juegos** (`_v70_wf_mlb.json`).
Línea base ELO: 0,5426.

| Modelo | Precisión | Log-loss | **ECE** |
|---|---|---|---|
| **clasificador (actual)** | 0,5498 | 0,6871 | **0,0093** |
| carreras (2 Poisson) | 0,5458 | 0,7039 | 0,0676 |
| carreras + isotónica | 0,5475 | 0,6891 | 0,0167 |
| mixto | 0,5515 | 0,6867 | 0,0114 |

El modelo de carreras **pierde** en las tres métricas. El mixto gana +0,17 pp de
precisión —por debajo del umbral— y empeora la calibración, que es justo la
métrica que el spec permitía usar para adoptar. La independencia entre las
carreras de ambos equipos es falsa (sobredispersión y contexto común: parque,
clima, árbitro), y por eso la probabilidad cruda queda descalibrada aunque
ordene razonablemente.

### 6.2 Alimentar la matriz de carreras con regresores directos: tampoco

Hoy `plantilla_mlb` reconstruye las λ invirtiendo una normal, mezclando tres
modelos. Parece un apaño, pero mide mejor que la alternativa «principista»:

| Rama | Desvianza | MAE | λ medias | Reales |
|---|---|---|---|---|
| **actual (inversión σ)** | **4,6906** | 2,4912 | (4,62 · 4,29) | (4,43 · 4,38) |
| regresores directos | 4,6943 | 2,4937 | (4,47 · 4,43) | (4,43 · 4,38) |
| **actual + encogimiento** | **4,6819** | **2,4903** | (4,56 · 4,36) | (4,43 · 4,38) |

Los regresores directos son **menos sesgados en media** pero más ruidosos, y la
desvianza empeora. Lo que sí funciona es el encogimiento (§2): la inversión
normal separaba a los dos equipos **seis veces más** de lo que la realidad
justifica (0,33 de diferencia media contra 0,05 real). **Adoptado, s = 0,58.**

Es decir: la Mejora E no se adopta como la planteaba el spec, pero la
investigación mejoró la matriz de carreras por otra vía.

---

## 7. Mejora F — NBA ⚠️ PARCIAL: features no, rediseño del modelo sí

### 7.1 Las features propuestas no aportan (`_v70_wf_nba.json`)

`nba_features.py` implementa todo lo pedido que es medible: fatiga (juegos en
5/7 días, 3-en-4, road trip), viajes (haversine entre los 30 pabellones, cruces
de huso) y avanzadas (eFG, TOV%, ratio de asistencias, OREB%, tasa de tiros
libres). **Cobertura de las avanzadas: 99,8 %.**

Walk-forward de 5 pliegues sobre 6.062 juegos limpios:

| Bloque | Precisión | Δ | Log-loss | Δ | ECE |
|---|---|---|---|---|---|
| actual (9 features) | 0,6544 | — | 0,6214 | — | 0,0205 |
| + fatiga | 0,6495 | −0,0049 | 0,6201 | −0,0013 | 0,0266 |
| + avanzadas | 0,6528 | −0,0016 | 0,6209 | −0,0005 | 0,0236 |
| + todo | 0,6499 | −0,0045 | 0,6202 | −0,0012 | 0,0172 |

Ninguno llega al +0,5 pp que exige el spec; todos **bajan** la precisión.

### 7.2 Lo que sí encontró la investigación

El mismo experimento dejó a la vista algo más grave: **el motor NBA no batía a
su propia línea base ELO** (0,6544 contra 0,6627). Es el cuadro de las ligas de
fútbol pequeñas, así que se probó la solución que allí funcionó:

| Modelo | Precisión | Δ | Log-loss | Δ | ECE |
|---|---|---|---|---|---|
| actual | 0,6544 | — | 0,6214 | — | 0,0205 |
| **elo_logit** (1 grado de libertad) | **0,6668** | **+0,0124** | 0,6163 | −0,0051 | **0,0170** |
| **blend_elo** | 0,6664 | **+0,0120** | **0,6157** | **−0,0057** | 0,0185 |

Una logística **sobre DIFF_ELO a secas** bate al ensemble de 9 features en las
tres métricas y además supera al argmax del ELO, que el ensemble no superaba. El
ensemble estaba sobreajustando.

**Adoptado `blend_elo`** (`_BlendEloNBA` en `engines/nba_engine.py`): tiene el
mejor log-loss —que es lo que gobierna EV y Kelly— y se autocorrige, porque si
el ensemble mejora con los datos de 2026-27 el peso se desplazará solo. Los
pesos elegidos en validación interna fueron 0,00 · 0,20 · 0,40 · 0,20 · 0,20:
el modelo se apoya mayoritariamente en el ELO calibrado.

### 7.3 Lesiones — por qué no están (regla §2.9)

El spec pide `missing_starters` y `missing_win_shares`. Medido: `nba_api` y ESPN
publican el parte de lesiones **del día** y **ninguno lo archiva**. Un backtest
necesita saber quién estaba lesionado el 14 de noviembre de 2023, y ese dato no
es recuperable de fuente gratuita. Reconstruirlo por ausencia en el boxscore
confunde lesión, descanso y decisión técnica, **y además mete fuga**: quién jugó
se sabe después del partido.

Lo honesto es lo implementado: `titulares_ausentes_en_vivo()` consulta el parte
del día para producción, donde sí llega a tiempo, y las features de lesión
quedan fuera del entrenamiento. Se documenta como pendiente en vez de fabricar
un backtest que no significaría nada.

---

## 8. Bugs encontrados y corregidos

### 8.1 `historico_nba.csv` tenía 1.225 juegos duplicados

`nba_scraper.actualizar()` deduplicaba con
`drop_duplicates(subset='GAME_ID')`, pero `leaguegamelog` devuelve el GAME_ID
como cadena con ceros a la izquierda (`'0022500001'`) y al releerlo del CSV
vuelve como entero (`22500001`). Al concatenar quedaban los dos tipos en la
misma columna y **la deduplicación no los veía iguales**, así que cada
actualización volvía a duplicar la temporada en curso.

**7.365 filas → 6.140 reales.** Corregido con una clave canónica
(`_clave_gid`), que además limpia el fichero existente. Todos los números NBA de
este documento están medidos sobre los datos limpios.

### 8.2 Orientación de la matriz de marcadores

En los scripts de validación nuevos, `M[i,j] = P(local=i, visitante=j)`, así que
el local gana en el triángulo **inferior**. Tenerlo al revés daba una precisión
del 29 % —por debajo del azar— que es como se detectó. No afectaba a producción,
pero sí habría invalidado las Mejoras A, B y E.

---

## 9. Qué se despliega

**Adoptado:**
1. Familia de modelo por liga (10 ligas) · `modelos_familia.json`
2. Encogimiento de λ (14 ligas + MLB) · `lambda_shrink.json`
3. `blend_elo` en el motor NBA
4. Corrección del duplicado de datos NBA
5. Métricas de walk-forward en `metadata.json` de cada liga
6. Avisos en la UI de familia de modelo y encogimiento

**Detrás de flag, apagado:** ajuste por alineaciones y por portero
(`lineup_coef.json` con `adoptado: false`), P(BTTS) como feature, modelo de
carreras MLB, features de fatiga/avanzadas NBA.

**Nada de lo rechazado se ha borrado**: el código, los datos recolectados y los
números quedan disponibles para cuando cambien las fuentes o los umbrales.

---

## 10. Reproducir

```bash
.venv\Scripts\python.exe _v70_fase1_rosters.py       # auditoría de cobertura
.venv\Scripts\python.exe _v70_wf_modelos.py          # Mejora D
.venv\Scripts\python.exe _v70_wf_shrink.py           # Mejora G
.venv\Scripts\python.exe _v70_wf_lineup.py           # Mejoras A y B
.venv\Scripts\python.exe _v70_diag_lineup.py         # diagnóstico A/B
.venv\Scripts\python.exe _v70_wf_btts.py             # Mejora C
.venv\Scripts\python.exe _v70_wf_mlb.py              # Mejora E (moneyline)
.venv\Scripts\python.exe _v70_wf_mlb_matriz.py       # Mejora E (matriz)
.venv\Scripts\python.exe _v70_wf_nba.py              # Mejora F
.venv\Scripts\python.exe _v70_reentrenar.py          # despliegue de D
```
