# v209 — La capa de auditoría del pick

**Documento técnico del encargo «Mejora integral del modelo de predicción
deportiva».** Estado: implementado y validado el 2026-09-18.

---

## 0. Resumen en una página

El encargo pedía ocho módulos como capas independientes sobre el modelo base.
**Siete de los ocho ya existían en este repositorio**, medidos y en producción.
Lo que faltaba de verdad era:

1. **el ensamblador** que junta todo en una ficha explicable por pick, y
2. **cuatro reglas** que nadie había escrito: divergencia con el mercado, cuota
   inflada, racha negativa y el tope de dos patas por partido, y
3. **una regla escrita y desconectada**: el efecto rebote por entrenador nuevo
   llevaba desde la v202 con el código puesto, probado y con su fuente lista —
   y sin una sola llamada en todo el repositorio. Estaba viva y ciega.

Todo eso es `auditoria_pick.py` (nuevo, ~560 líneas), más el enganche en la
tarjeta de «Apuestas del Día» y diez tests en la suite.

**No se tocó el núcleo predictivo.** Ni un modelo, ni una feature, ni el
reparto de secciones. La capa lee y explica.

---

## 1. Diagnóstico: qué pedía el encargo y qué había

| # | Módulo del encargo | Ya existía | Qué faltaba de verdad |
|---|---|---|---|
| 1 | Correlación con el mercado | `mercado_implicito.py` (devig), `clasificador.ventaja_de_precio()`, `cuota_justa` en cada pick | La **bandera de divergencia extrema** y su recorte de confianza |
| 2 | Contexto en tiempo real | `contexto_ampliado.py`, `contexto_mercado.alineacion()`, `filtro_contexto.py` | **Enchufar la fuente de entrenadores** y emparejar los nombres |
| 3 | Índice de volatilidad por liga | `riesgo_liga.py` — ya medido **y refutado** | Nada. Ver §4.1 |
| 4 | Correlación entre mercados | `match_parlay.py` (grupos excluyentes, contradicciones, haircut) | El **tope de 2 patas por partido** y la matriz sobre el vocabulario del barrido |
| 5 | Filtros anti-trampa | `clasificador.semaforo()` (ventaja imposible, EV sospechoso) | **Cuota inflada** y **racha negativa** |
| 6 | Calibración con backtesting | `alpha_finder.brier_liga()`, ECE por competición en `riesgo_liga`, `aprendizaje_continuo.py` | Nada nuevo; se consume |
| 7 | Explicabilidad | Disperso: motivos en `semaforo`, `riesgo_liga.explicacion()` | **El ensamblador. Éste era el hueco grande** |
| 8 | Gestión de bankroll | `bankroll_manager.py` (Kelly ¼), `montecarlo_sim.py` (ruina), `portfolio_optimizer.py` | Componerlos por pick con el ajuste por riesgo |

---

## 2. Arquitectura

La capa es **de lectura**, se llama por pick y no puede lanzar.

```
    BARRIDO (alpha_finder)          CLASIFICACIÓN            INTERFAZ
    ----------------------          -------------            --------
    pick = {partido, liga,     →    clasificador.py     →    dashboard_ui
            clave_liga,             (secciones por            _fila_apuesta()
            mercado, apuesta,        canal medido)                 │
            prob, cuota,                                           │
            cuota_justa, ev}                                       ▼
                                                        auditoria_pick.auditar()
                                                                   │
                        ┌──────────────────────────────────────────┤
                        ▼                                          ▼
                 LO QUE YA MEDÍA                            LO NUEVO (v209)
                 ---------------                            ---------------
                 riesgo_liga.nivel_liga()                   divergencia()
                 alpha_finder.brier_liga()                  cuota_inflada()
                 bankroll_manager.calcular_stake()          racha_negativa()
                 montecarlo_sim.simular_bankroll()          patas_compatibles()
                 filtro_contexto.rebote_entrenador()        asegurar_fuente_*()
                 contexto_ampliado.de_partido()             explicar()
                 name_mapper.mapear()
```

**Punto de entrada único:** `auditar(pick, bankroll=100.0, dia=None,
con_contexto=True) -> dict`.

`con_contexto=False` salta lo que toca disco o red (racha, entrenador,
aclimatación). Es lo que usa la pantalla, que llama una vez por apuesta y por
tarjeta.

---

## 3. Las ocho capas, una por una

### M1 — Correlación con el mercado

```python
probabilidad_mercado(pick)     # prioriza cuota_justa (ya viene sin vig)
valor_esperado(prob, cuota)    # p × cuota − 1
veredicto_ev(ev)               # valor / neutro / descartar / sin_dato
divergencia(p_modelo, p_mercado)
```

Los tres tramos son los del encargo: `EV > +3 %` → valor · `−2 % … +3 %` →
neutro · `EV < −2 %` → descartar.

`probabilidad_mercado` prioriza `cuota_justa` porque es la que el barrido ya
dejó **sin margen** tras el devig del consenso. Si sólo hay `cuota`, cae a
`1/cuota`, que **sí lleva vig** — y comparar contra ella infla la divergencia
exactamente en el tamaño del margen de la casa.

**Divergencia extrema:** `|p_modelo − p_mercado| > 15 %` enciende la bandera y
recorta la confianza un 20 %.

### M2 — Contexto en tiempo real

```python
asegurar_fuente_entrenadores()   # el enchufe que faltaba
entrenador_nuevo(pick, dia)
contexto_medido(pick)            # aclimatación: lo único que corrige un número
```

**El hallazgo de esta tanda.** `filtro_contexto.py` tenía desde la v202 la
regla del rebote entera —ventana de 7 días, cuota máxima 1,85, penalización
0,15, mercados bloqueados—, sus tests con fuente inyectada, y
`conectar_buscador()` listo para enchufar Wikidata. **Nadie la llamaba nunca.**

Y al conectarla apareció un segundo filo: `cambio_reciente()` busca por
igualdad exacta, Wikidata publica `Bologna Football Club 1909` y el barrido
dice `Bologna`. Conectada pero sin emparejar, la regla habría cargado ocho
cambios reales y no habría disparado jamás — un no-op silencioso. Se resuelve
con `name_mapper.mapear()`, que es el emparejador del proyecto.

Verificado de punta a punta el 2026-09-18: Bologna cambió de entrenador el
2026-09-16; con Inter favorito a 1,55 la bandera se enciende a 2 días.

**Lo que NO se hace:** penalizar la probabilidad por lesiones. `contexto_ampliado`
ya explica por qué — nadie guardó la lista de bajas de un partido de 2024, así
que no hay contra qué medirlo. El dato se lee y se enseña con `medido: False`.

### M3 — Riesgo por competición

```python
riesgo_de_liga(clave_liga)     # nivel, factor, motivo
bloqueo_por_riesgo(pick, riesgo)
```

El factor usa la escala del encargo (1,0 · 1,3 · 1,8) pero **quién cae en cada
tramo lo decide el ECE medido**, no el nombre de la liga. Ver §4.1.

Con factor > 1,5: se exige cuota ≥ 1,80 y se bloquean `Under` y `BTTS No`.

### M4 — Correlación entre mercados

```python
senal(pick)                    # (grupo, opción) sobre el vocabulario del barrido
patas_compatibles(picks, max_por_partido=2)
```

**Por qué no se reusa `match_parlay._clasificar`:** esa función trabaja sobre
los `id` de campo de la ficha (`over25_prob`, `dc_1x`…). Los picks del barrido
sólo traen `mercado` y una etiqueta legible («Más de 1.5»). Son las mismas
reglas una capa más arriba, no una copia de la matriz.

| Par | Veredicto |
|---|---|
| Gana A + Gana B | imposible → bloquear |
| Gana A + Under 1.5 | correlación negativa → bloquear |
| BTTS No + Over 2.5 | correlación negativa → bloquear |
| BTTS Sí + Under | correlación negativa → bloquear |
| Gana A + Over 2.5 | correlación positiva → **permitir** |

Más el tope de 2 patas del mismo partido.

### M5 — Filtros anti-trampa

```python
cuota_inflada(cuota, prob)     # ratio > 1,30 → bandera y −30 % de confianza
racha_negativa(clave_liga, equipo)   # ≥ 5 sin ganar
incertidumbre(clave_liga)      # 🔴 Alta incertidumbre = Brier ≥ 0,22
```

`incertidumbre` **reutiliza la etiqueta que el proyecto ya publica**
(`alpha_finder.etiqueta_fiabilidad`) en vez de inventar una nueva: el encargo
nombra «🔴 Alta Incertidumbre» y ésa es, literalmente, la que ya existía.

`racha_negativa` lee la misma racha que la tarjeta ya pinta
(`contexto_partido.forma`), para que la pantalla y la auditoría no puedan decir
cosas distintas.

### M6 — Calibración

Se consume, no se reimplementa: Brier real por competición sobre los picks
publicados (`roi_bets_*.json`, mínimo 30) y ECE por competición sobre 47.794
partidos y 55 competiciones (`riesgo_liga`).

### M7 — Explicabilidad

```python
auditar(pick) -> ficha     # el JSON del encargo
explicar(ficha) -> str     # la frase que se lee antes de decidir
texto(ficha) -> str        # el bloque del ejemplo del encargo
```

La ficha trae los campos que el encargo fija: `partido`, `liga`,
`factor_riesgo_liga`, `apuesta`, `cuota`, `probabilidad_modelo`,
`probabilidad_mercado`, `EV`, `confianza`, `razones`, `banderas`,
`stake_sugerido`, `explicabilidad` — más `bloqueo`, `brier`, `prob_ruina_10d`
y `apto_combinada`.

**La confianza** parte del semáforo, sólo puede bajar, y se multiplica por los
recortes: divergencia (−20 %), cuota inflada (−30 %), alta incertidumbre
(×0,5), liga de alto riesgo (×0,8) y veredicto de descarte (×0,6).

### M8 — Banca

```python
stake_sugerido(prob, cuota, bankroll, confianza, alta_incertidumbre)
probabilidad_de_ruina(prob, cuota, apuestas_por_dia=3, dias=10)
```

Kelly ¼ (`bankroll_manager`), stake partido a la mitad con alta incertidumbre
o confianza BAJA, y tope duro del 5 % de la banca.

---

## 4. Las dos desviaciones del encargo, con su evidencia

### 4.1 La tabla de riesgo por liga está invertida

El encargo fija:

> Ligas Top (Premier, LaLiga, Bundesliga…): 1,0
> Ligas Volátiles (Brasileirão B, Liga BetPlay, Primera Nacional…): 1,8

`riesgo_liga.py` ya había implementado **exactamente ese índice** (IVL =
desviación de goles / media de goles) y lo midió sobre las 69 competiciones
con histórico:

```
IVL   mínimo 0,5408   mediana 0,6082   máximo 0,7237
```

Ninguna llega a 1,2, así que con los cortes del encargo **las 69 salen
«varianza baja» y el filtro no bloquea nada nunca**. Y no es que el umbral esté
alto: el total de goles se parece a una Poisson, donde el coeficiente de
variación es 1/√media, así que con medias de 1,8 a 3,3 el IVL está condenado al
rango 0,55–0,74. **El IVL no mide caos: mide cuántos goles se marcan.**

Cruzado con el ROI real (ledger con cuota de cierre, 34 competiciones, 14.647
patas):

| Índice | Pearson vs ROI | Spearman | ROI peor cuartil | ROI mejor cuartil |
|---|---|---|---|---|
| IVL (el del encargo) | −0,031 | −0,113 | −4,65 % | −3,69 % |
| **ECE de calibración** | **−0,460** | **−0,563** | **−6,20 %** | **−1,01 %** |

El IVL no separa nada (un punto de diferencia). El ECE separa **5,19 puntos por
pata**, que en un parlay de cuatro son −22,5 % contra −4,0 %.

Y ordena al revés que la intuición del encargo. Peor cuartil medido:
Conference League, Libertadores, AFC Champions, Sudamericana, Champions y la
**Premier League**. Mejor mitad: **Brasileirão B, Argentina y Primera
Nacional** — las tres que el encargo quería bloquear.

**Decisión:** el `factor_riesgo_liga` se publica con los números del encargo,
pero lo asigna el ECE medido. La tabla literal queda en
`auditoria_pick.TABLA_DEL_ENCARGO` marcada como refutada, con el porqué al
lado, para que no se reintroduzca sin volver a medir.

### 4.2 «Nunca recomendar una apuesta con EV negativo»

La regla de oro del encargo choca de frente con la tesis medida del proyecto:

> El modelo NO bate al mercado (apostar su probabilidad pierde entre 4,66 % y
> 6,52 % sobre 37.158 apuestas), pero comprar al mejor precio SÍ gana.
> — `ARQUITECTURA.txt`, §0

Seleccionar por EV positivo sobre la probabilidad del modelo **es** ese canal
perdedor. Además, casi todo lo que se publica tiene EV negativo por
construcción: la casa cobra margen, y en un mercado de dos vías con 5 % de vig
la apuesta perfectamente valorada da EV ≈ −5 %. Aplicar la regla literalmente
dejaría la pantalla vacía casi todos los días, y lo poco que pasara el filtro
sería justo lo peor medido.

**Decisión — la capa hace las dos cosas que sí son compatibles:**

- **Publica** el EV y su veredicto con los tres tramos del encargo, en cada
  pick, siempre. Eso es transparencia y es gratis.
- **No asciende** por EV. El reparto de secciones lo sigue decidiendo
  `clasificador`, por ventaja de precio, que es el único criterio con
  percentil 5 de bootstrap positivo (+1,73 %).
- **Sí manda en la combinada**: `apto_para_combinada()` deja fuera lo que el
  encargo dice que hay que dejar fuera — alta incertidumbre, bloqueo de liga y
  EV de descarte.

Un detalle menor pero que conviene registrar: el ejemplo del propio encargo da
`prob 68 %`, `cuota 1,42` y `EV −2,4 %`. La aritmética da **−3,44 %**
(0,68 × 1,42 − 1). La capa devuelve −3,4 y hay un test que lo ata.

---

## 5. Qué está medido y qué no

Se mantiene la separación que ya usa `contexto_ampliado`, y por la misma razón:
un número sin etiqueta de si está medido acaba tratándose como si lo estuviera.

| Regla | Estado | Efecto |
|---|---|---|
| Ventaja de precio (canal de Sección 1) | **medido**, p5 +1,73 % | decide sección |
| ECE por competición | **medido**, 47.794 partidos | fija el factor de riesgo |
| Brier por competición | **medido**, ≥ 30 picks publicados | fija «alta incertidumbre» |
| Aclimatación (desnivel) | **medido** fuera de muestra, −34 % ECE | **corrige el 1X2** |
| Divergencia extrema | **sin medir** | avisa y recorta confianza |
| Cuota inflada | **sin medir** | avisa y recorta confianza |
| Racha negativa | **sin medir** | avisa |
| Rebote por entrenador | **sin medir** (el efecto, no la fuente) | avisa |
| Lesiones y alineaciones | **no medible hoy** | se lee, no corrige |

Las cuatro reglas nuevas viajan con `medido: False` y **no tocan ninguna
probabilidad**: recortan confianza y encienden banderas. El día que haya
ledger suficiente para medirlas, el sitio donde hacerlo ya está.

---

## 6. Validación

| Puerta | Resultado |
|---|---|
| `test_catalogo_y_cuotas.py` (suite principal) | **3.581 OK · 1 fallo preexistente** |
| Bloque v209 (10 tests nuevos) | **0 fallos** |
| `valida_render.py "Apuestas del Día"` | **TODO OK**, exit 0, 234,5 s |
| Prueba contra picks reales del barrido cacheado | 40 picks, 0 errores |

**El fallo preexistente** es `TODOS los partidos evaluados tienen pronostico
recuperable` (v177). Se comprobó ejecutando ese mismo test sobre la copia de
`HEAD`, sin ninguno de estos cambios: falla igual (13 de 25 con red, 0 de 25
sin ella). **No es una regresión de esta tanda.**

### Dos bugs que sólo aparecieron con datos reales

Los tests sintéticos pasaban los dos. Salieron al auditar el barrido cacheado:

1. **`EV −550 %`.** El campo `EV` de la ficha va en **puntos de porcentaje**
   (−5,5), y el motivo lo formateaba con `:%`, que multiplica otra vez por
   cien.
2. **Confianza ALTA en el canal anti-indicador.** La confianza subía con
   *cualquier* `canal` presente, y el barrido etiqueta `ev_del_modelo` — el
   canal medido en −4,66 %/−6,52 %. Un pick con EV −5,5 % se leía ALTA. Ahora
   sólo suben los tres canales con p5 positivo (`CANALES_MEDIDOS`).

---

## 7. Qué queda fuera, y por qué

- **Lesiones que penalizan la probabilidad.** No hay histórico de bajas contra
  el que medir el tamaño del efecto. Se lee y se enseña; no corrige.
- **Reentrenamiento cada 7 días.** Ya existe (`aprendizaje_continuo.py` y el
  workflow nocturno). No se tocó.
- **Backtesting sobre 50.000 partidos del encargo.** El proyecto ya mide sobre
  47.794 partidos (ECE) y 37.158 apuestas (ROI por canal). No se reabre.
- **APIs de Bet365 y Novibet.** El pipeline usa Pinnacle (ancla sharp), ESPN,
  Playdoit, Bovada, Matchbook y The Odds API. Añadir casas es una tanda propia,
  con su emparejador y su medición.
- **Medir las cuatro reglas nuevas contra ROI.** Es el siguiente paso natural:
  hace falta acumular ledger con la bandera escrita en el momento del pick.
