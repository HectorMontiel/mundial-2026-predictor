# VALIDACIÓN v99 — Lo que quedaba a medias, y las cuatro salidas de la KBO

**Fecha:** 2026-08-05

---

## 1. Remates por jugador: el dato estaba, y la cuenta estaba mal

### 1.1 Por qué no salían

`remates_jugadores.py` (v67) lee los remates POR JUGADOR del bloque `rosters`
de ESPN y funciona — incluida la Leagues Cup (34 jugadores de Columbus Crew,
Diego Rossi 4,67 remates/partido). Lo que no llegaba a la ficha era el puente:
`_props_rematadores` necesita el *slug* de ESPN y lo busca en
`LEAGUES[clave]['espn_liga']` o en `league_engine._ESPN_POR_LIGA`. Si no lo
encuentra devuelve lista vacía y la sección se queda con las medias de EQUIPO,
**sin decir por qué**.

Afectaba a **tres competiciones disponibles**: `rus_premier`,
`gre_super_league` y `leagues_cup` — y las tres **sí** tenían su código en
`fixtures_espn.ESPN_CODIGOS`. Eran dos listas del mismo dato mantenidas por
separado, que es lo que garantiza que acaben desincronizadas.

**Arreglo:** `_ESPN_POR_LIGA` hereda de `fixtures_espn.ESPN_CODIGOS` lo que no
tenga escrito, así que ahora es la tabla de EXCEPCIONES y no un duplicado.
Ligas disponibles sin slug: **3 → 0**.

### 1.2 Y al mirar el resultado, la cuenta no se sostenía

Los props ya salían… con números imposibles: **«Diego González — 3+ remates:
75,6 %»**. Un jugador real no remata tres veces en el 76 % de los partidos.

Medido (Atlas, Leagues Cup, 39 jugadores con datos):

| | |
|---|---|
| remates/partido del top-4 | **7,83** |
| remates/partido de TODOS | **18,25** |
| cuota real del top-4 | **42,9 %** |
| cuota que les asignaba el reparto | **85,0 %** |

La causa: la cuota se repartía sobre la suma del **top-4** (`t.head(max_jug)`)
y luego se multiplicaba por 0,85 «para dejar margen al resto de la plantilla».
Pero si el denominador ya son sólo cuatro, esas cuotas suman 1 por
construcción y el 0,85 no deja margen a nadie — le da al top-4 el 85 % de los
remates del equipo. **Cada jugador salía con el doble de remates esperados.**

Viene de la v71 y estaba en TODAS las ligas, no sólo en las nuevas. Corregido:
el denominador es la suma de todos los jugadores con datos.

| | antes | después |
|---|---|---|
| Diego González — remates esperados | 3,95 | **1,90** |
| Diego González — 3+ remates | 75,6 % | **29,6 %** |
| Uros Djurdjevic — 3+ remates | 39,4 % | **9,7 %** |

---

## 2. Leagues Cup: el histórico se dobla, el veredicto no cambia

El agrupado usaba MLS y Liga MX **a través de `descargar_liga`**, que las
recorta a `anios_ventana: 8`. Esa ventana está validada para los modelos de
esas dos ligas y no se toca — pero para la Leagues Cup sobra recorte: los CSV
de football-data llegan a **2012** (USA 6.084 partidos, MEX 4.682) y el
agrupado sólo usaba desde 2018-08.

`leagues_cup.historico()` lee ahora los CSV completos (sin alterar nada de lo
que consumen `mls` y `liga_mx`):

| | antes | después |
|---|---|---|
| partidos agrupados | 6.609 | **11.000** |
| equipos | 52 | 56 |
| MLS desde | 2018-08 | **2012-03** |

**Y el veredicto sigue siendo el mismo.** Validación por ediciones:

| | antes | después |
|---|---|---|
| modelo agrupado | 0,4352 | 0,4352 |
| ELO (línea base) | 0,4444 | 0,4352 |
| ventaja | −0,93 pp | **+0,00 pp** (p5 −4,63 %) |

Doblar el dato pasa el modelo de ir por detrás del ELO a **empatarlo**. No crea
un edge. Se conserva el histórico profundo porque es más robusto para las
ediciones que vengan, y se dice que no cambió la conclusión: **sigue en Capa 2**.

---

## 3. KBO: cuatro salidas, medidas sobre la cuota de cierre real

La v98 midió que el modelo no bate al mercado. Antes de cerrarlo se prueban
cuatro alternativas que **no son «entrenar otra vez»**, todas sobre los 113
partidos con predicción fuera de muestra y cierre real.

### A. Mezclar modelo y mercado — ¿cuánto peso merece el modelo?

Es la pregunta correcta: si el precio sabe más, quizá el modelo aporte *algo*
en la mezcla. Se busca el `w` que minimiza el Brier de
`w·modelo + (1−w)·mercado`.

| | Brier |
|---|---|
| mercado solo | **0,2411** |
| modelo solo | 0,2492 |
| mejor mezcla | **0,2411 con w = 0,00** |

**El peso óptimo del modelo es CERO.** No es que aporte poco: no aporta nada
que el precio no tenga ya. Éste es el resultado que cierra la vía del modelo.

### B. ¿Hay una banda de discrepancia donde el modelo acierte?

| \|modelo−mercado\| | n | acierta modelo | acierta mercado |
|---|---:|---:|---:|
| [0,00 · 0,05) | 44 | 0,545 | 0,477 |
| [0,05 · 0,10) | 42 | 0,452 | **0,643** |
| [0,10 · 0,20) | 27 | 0,556 | **0,630** |

El único tramo donde el modelo «gana» es aquel en el que **casi no discrepa**
del precio (n=44, diferencia <5 pp): ahí no está aportando, está copiando. En
cuanto se separa de verdad, pierde. Es la confirmación de lo que la v87 ya
había medido en fútbol.

### C. Sólo favoritos claros del mercado

| piso de prob. implícita | n | ROI | p5 |
|---|---:|---:|---:|
| ≥ 0,55 | 57 | −3,24 % | −20,53 % |
| ≥ 0,58 (piso de MLB) | 30 | −10,41 % | −32,64 % |

### D. Contraste: apostar AL REVÉS que el modelo

n=113 · ROI **−2,96 %** · p5 −18,69 %.

Esto es lo que descarta la última esperanza: si el modelo estuviese
sistemáticamente equivocado, invertirlo daría dinero. **También pierde.** O
sea que no hay señal explotable en ningún sentido — el modelo no está al
revés, es que no sabe nada que el precio no sepa.

### Conclusión y qué queda vivo

Las cuatro salidas están medidas y ninguna funciona. La KBO **no entra en Capa
1 por la vía del modelo**, y ya no por falta de datos sino por exceso de
evidencia. Lo que sigue en pie:

1. **Line shopping** (activo): no necesita que el modelo acierte, sólo que dos
   casas discrepen. Se comprueba en cada barrido.
2. **Features nuevas**: el `w=0,00` dice que las features ACTUALES (ELO +
   carreras del abridor) no tienen información marginal sobre el precio. La
   única palanca real que queda es meter información que hoy no está —
   *bullpen*, alineación, parque, OPS reciente— desde Statiz o los *box scores*
   de Naver. Es la vía honesta, y es trabajo de ingesta nueva, no de
   reentrenar.
3. **Acumulación de cierres de temporada regular** (activa desde la v99): los
   201 de los que se parte son playoffs, población sesgada. Con regular de
   verdad la medición será más justa — en cualquiera de los dos sentidos.

---

## 4. Resumen

| | decisión | evidencia |
|---|---|---|
| Props de remates en 3 ligas | **arreglado** | `_ESPN_POR_LIGA` hereda de `fixtures_espn`; 3 → 0 sin slug |
| Reparto de remates por jugador | **corregido** | daba el 85 % del volumen al top-4 cuando su cuota real es 42,9 % |
| Histórico de Leagues Cup | **ampliado** (6.609 → 11.000) | pero la ventaja sobre el ELO sigue siendo +0,00 pp |
| Modelo de KBO en Capa 1 | **RECHAZADO** | peso óptimo en la mezcla **w = 0,00**; invertirlo también pierde |
| Line shopping de KBO | **activo** | única vía que no depende del modelo |
