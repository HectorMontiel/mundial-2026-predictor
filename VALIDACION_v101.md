# v101 — El sistema aprende de sus propios resultados

**Petición:** que la app valide sus apuestas y aprenda de los fallos —
concretamente, que cuando falle un «más de 1.5 goles» averigüe qué cambió en el
comportamiento del equipo, por ejemplo si venía de vencer a un rival más fuerte —
y que eso valga tanto para equipos como para tenis.

Se midió la hipótesis exactamente como se planteó. **No se sostiene.** Lo que sí
apareció, buscándola, fue una fuga de datos en el modelo desplegado de WTA y una
brecha de calibración de −10,8 pp en los picks publicados. La versión entrega el
aprendizaje autónomo construido sobre eso, que es lo que sí se puede medir.

---

## 1. La hipótesis del partido anterior — RECHAZADA en fútbol

`contexto_previo.py` extrae, con pase cronológico estricto, cinco circunstancias
del partido anterior de cada lado: días de descanso, escalón del rival (¿venía de
uno más fuerte?), sorpresa del resultado previo respecto al ELO, margen de ese
partido y carga de partidos en 14 días.

La pregunta correcta no es si eso predice partidos —el ELO solo ya lo hace— sino
si **aporta algo encima de lo que el modelo desplegado ya sabe**. Así que la base
del A/B es la propia probabilidad fuera de muestra del modelo, en log-odds, sobre
47.948 predicciones del `pick_ledger`.

### Primera medición, y por qué no valía

| mercado | log-loss A → B | mejora | p5 | veredicto |
|---|---|---|---|---|
| over 1.5 | 0,56566 → 0,56545 | +0,00021 | −0,00012 | RECHAZAR |
| over 2.5 | 0,68808 → 0,68774 | +0,00034 | −0,00006 | RECHAZAR |
| BTTS | 0,69011 → 0,69007 | +0,00004 | −0,00016 | RECHAZAR |
| gana local | 0,64949 → 0,64604 | +0,00345 | **+0,00214** | ADOPTAR |
| empate | 0,57289 → 0,57263 | +0,00026 | −0,00019 | RECHAZAR |
| gana visita | 0,57229 → 0,56852 | +0,00377 | **+0,00252** | ADOPTAR |

Dos ADOPTAR. Antes de creérselos, dos auditorías.

**Auditoría 1 — un bug propio.** La primera versión de este A/B asumió que el
ledger codificaba `1=local, 0=empate`. Verificado contra el marcador en las
47.948 filas, la codificación real es **`0=local, 1=empate, 2=visitante`**. Con
las etiquetas cruzadas, el «empate» salía con una mejora de +0,02825 y p5
+0,02488 — cuarenta veces cualquier feature adoptada en el proyecto. No era un
hallazgo: era `p_draw` regresada contra el resultado «gana local».

**Auditoría 2 — atribución falsa.** `DIFF_ESCALON` se desarrolla así:

```
DIFF_ESCALON = [(ELO_A − ELO_B) + (elo_rival_prev_A − elo_rival_prev_B)] / 400
                └─── fuerza de HOY ───┘   └──── rivales ANTERIORES ────┘
```

Lleva dentro la diferencia de ELO actual. Separados los dos sumandos:

| componente | mejora | p5 | veredicto |
|---|---|---|---|
| DIFF_ESCALON completo | +0,01836 | +0,01562 | — |
| sólo el ELO de HOY | +0,03607 | +0,03234 | ADOPTAR |
| sólo los rivales ANTERIORES | +0,00011 | −0,00011 | RECHAZAR |
| rivales anteriores \| ELO de hoy | **−0,00001** | −0,00006 | RECHAZAR |

El control de permutación descartó el ruido (contexto barajado: −0,00009) y el
control de liga descartó el efecto fijo. Lo que quedaba era la fuerza de hoy.

### Medición definitiva, con el ELO en la base

Puesta la diferencia de ELO rodante en la base junto a la probabilidad del
modelo, el contexto del partido anterior aporta:

| mercado | mejora | p5 | veredicto |
|---|---|---|---|
| over 1.5 | +0,00001 | −0,00010 | RECHAZAR |
| over 2.5 | +0,00002 | −0,00012 | RECHAZAR |
| BTTS | +0,00000 | −0,00014 | RECHAZAR |
| gana local | −0,00010 | −0,00035 | RECHAZAR |
| empate | −0,00007 | −0,00025 | RECHAZAR |
| gana visita | −0,00007 | −0,00029 | RECHAZAR |

**Seis de seis. En fútbol, la circunstancia del partido anterior no contiene
información que el modelo no tenga ya.** La intuición es buena y muy extendida;
los datos, sobre 47.948 predicciones fuera de muestra, no la respaldan.

El módulo `contexto_previo.py` se conserva —está validado, es genérico y no tiene
fuga— pero **no entra en producción en fútbol**.

---

## 2. Tenis — la medición encontró otra cosa: una fuga en producción

En tenis, el mismo A/B sobre el vector desplegado dio números imposibles:

| circuito · bloque | log-loss A → B | mejora | p5 |
|---|---|---|---|
| ATP · descanso+carga | 0,60200 → 0,51041 | **+0,09159** | +0,08957 |
| ATP · todo el contexto | 0,60200 → 0,49717 | **+0,10484** | +0,10268 |

Para comparar: el IDF, la última feature adoptada (v99.2), mejoró **+0,00064**.
Esto es 160 veces más. Por la regla de la casa, eso es fuga o bug hasta que se
demuestre lo contrario.

**Lo era.** El descanso y la carga, **solos y sin modelo**, predicen el 71,05 %
de los partidos con log-loss 0,56255. Ninguna información de calendario hace eso.

### El mecanismo

El archivo ITF —**290.027 de 365.185 filas, el 79 %**— guarda todos los partidos
de un torneo con **una sola fecha**:

| fuente | torneos | fechas distintas por torneo (mediana) |
|---|---|---|
| `archivo_itf` | 7.111 | **1,0** |
| `itf_vivo` | 29 | **1,0** |
| `kaggle` | 1.712 | 7,0 |
| `espn` | 239 | 6,0 |

El 35,9 % de los pares (jugador, fecha) tienen dos o más partidos ese día, hasta
ocho. Con fecha única el orden cronológico desaparece, y «partidos en los últimos
14 días» deja de medir calendario: mide **cuánto avanzó en ese mismo torneo**, o
sea el resultado de los partidos que se están prediciendo.

### Y estaba en el modelo desplegado de WTA

`DIFF_DIAS_DESCANSO`, `DIFF_PARTIDOS_14D` y `DIFF_HORAS_7D` entraron en la v35,
cuando el histórico era sólo Kaggle (7 fechas por torneo: limpio). El archivo ITF
llegó en la v96/v97 y nadie volvió a mirar esas tres features. Medidas **solas**:

| subconjunto | log-loss | acierto |
|---|---|---|
| filas kaggle (fechas reales) | 0,69362 | **53,7 %** |
| filas ITF (fecha única) | 0,54115 | **73,6 %** |

Mismo código, misma feature. La diferencia es la granularidad de la fecha.

**El coste, evaluando el vector desplegado por subconjunto:**

| subconjunto | log-loss con → sin | acierto con → sin | IC90 de la diferencia |
|---|---|---|---|
| todas las filas | 0,50608 → 0,58070 | 74,94 % → 69,06 % | [+0,0725, +0,0766] |
| sólo ITF (sucio) | 0,46663 → 0,56859 | 77,92 % → 70,18 % | [+0,0996, +0,1043] |
| **sólo fechas reales (limpio)** | **0,67515 → 0,63262** | **62,18 % → 64,26 %** | **[−0,0473, −0,0378]** |

Sobre filas limpias —lo que se parece a producción— el intervalo entero es
negativo: **quitarlas mejora**. Inflaban el backtest en +7,7 pp de acierto y
restaban **2,1 pp de acierto real**.

**ADOPTADO:** WTA pasa de `FEATURES_V992_WTA` (14) a `FEATURES_V101_WTA` (11).
ATP no está afectado — su vector nunca llevó las de fatiga.

**Guarda añadida** (`engines/base_engine.py`): si el `metadata.json` del modelo
guardado no coincide en features con el vector del motor, `cargar_modelo` falla
con un mensaje explícito en vez de con un error de forma de sklearn a mitad de
una predicción. El CI reentrena ATP/WTA a diario, así que el vector nuevo entra
en la siguiente ejecución.

---

## 3. Lo que SÍ se puede aprender: la autopsia

`autopsia.py` parte las predicciones en segmentos y mide la **brecha de
calibración** = acierto real − probabilidad prometida. Un segmento sólo se
declara lección si tiene muestra suficiente **y** su intervalo bootstrap no toca
el cero, con corrección de Šidák por el número total de segmentos mirados — sin
eso, con 75 segmentos y ruido puro, siempre «destacan» tres.

### Sobre los picks publicados (144 liquidados)

```
GLOBAL · 144 picks · acierto 57,6 % vs prometido 68,4 % · brecha −10,8 %
```

| corte | segmento | n | real | prometido | brecha | IC |
|---|---|---|---|---|---|---|
| banda | 70-80 % | 51 | 0,588 | 0,761 | **−0,173** | [−0,368, −0,001] |
| capa | capa2 | 108 | 0,583 | 0,745 | **−0,162** | [−0,299, −0,037] |
| canal | sin clasificar | 144 | 0,576 | 0,684 | **−0,108** | [−0,205, −0,000] |

La Capa 2 es el problema, y tiene explicación estructural: la corrección por
banda de `calibracion_confianza` (v84/v86) **sólo se aplicaba a la pestaña de
Máxima Confianza**. Lo que se registra en `rendimiento_real` —`capa1` y `capa2`—
llevaba la probabilidad cruda del modelo. 108 de los 144 picks son capa2.

### Sobre el ledger histórico (47.794 predicciones fuera de muestra)

La sobreconfianza en la cola alta es masiva y consistente:

| mercado | banda | n | real | prometido | brecha |
|---|---|---|---|---|---|
| over 2.5 | >80 % | 705 | 0,620 | 0,834 | **−0,214** |
| BTTS | >80 % | 107 | 0,598 | 0,818 | **−0,220** |
| BTTS | 70-80 % | 1.883 | 0,576 | 0,734 | **−0,158** |
| over 2.5 | 70-80 % | 3.380 | 0,594 | 0,742 | **−0,147** |
| over 1.5 | >80 % | 13.654 | 0,783 | 0,856 | −0,073 |

---

## 4. El lazo de aprendizaje — ADOPTADO donde se valida

`aprendizaje_continuo.py`: escalado de Platt sobre `logit(p)`, jerárquico
(global → deporte → mercado), con encogimiento hacia el padre según muestra
(`peso = n/(n+200)`) y **la raíz encogida hacia el prior del ledger**. Sin eso
último, los 144 picks de producción determinaban solos la corrección global — el
propio defecto que el encogimiento existe para evitar; se detectó revisando el
primer mapa generado y se corrigió.

Tres topes duros: la corrección no desplaza una probabilidad más de **±0,15**, la
pendiente se limita a [0,3 ; 1,5], y sin nodo aprendido devuelve la probabilidad
intacta.

**Es seguro porque es monótono:** no reordena partidos ni cambia qué se apuesta,
sólo con cuánta seguridad se dice.

### Validación walk-forward — el mapa se aprende sólo con el pasado

| mercado | log-loss | p5 | Brier | acierto | brecha | veredicto |
|---|---|---|---|---|---|---|
| **over 1.5** | 0,59086 → **0,57005** | **+0,01862** | 0,1995 → 0,1914 | 0,7189 → **0,7370** | 0,0247 → 0,0131 | **ADOPTAR** |
| **over 2.5** | 0,71667 → **0,68904** | **+0,02500** | 0,2590 → 0,2479 | 0,5413 → 0,5395 | 0,0213 → 0,0127 | **ADOPTAR** |
| **BTTS** | 0,72204 → **0,69335** | **+0,02643** | 0,2622 → 0,2500 | 0,5233 → 0,5301 | 0,0465 → 0,0216 | **ADOPTAR** |
| 1x2 gana local | 0,64898 → 0,64899 | −0,00019 | — | — | — | RECHAZAR |
| 1x2 empate | 0,57645 → 0,57457 | +0,00107 | — | — | — | ADOPTAR |
| 1x2 gana visita | 0,57639 → 0,57613 | −0,00006 | — | — | — | RECHAZAR |

Que el 1X2 rechace es la señal de que el listón funciona: **el lazo sólo mejora
donde hay defecto**, y el 1X2 ya estaba bien calibrado (brecha 0,003).

Ganancias en los mercados de goles: log-loss −0,021 a −0,029, brecha de
calibración **partida por la mitad**, y en over 1,5 el acierto **sube 1,8 pp**
(71,89 % → 73,70 %).

---

## 5. Qué queda en producción

| pieza | estado |
|---|---|
| `contexto_previo.py` | Validado y sin fuga, **NO desplegado** — la hipótesis se midió y no aporta |
| WTA sin features de fatiga | **DESPLEGADO** — +2,1 pp de acierto real |
| Guarda de features del modelo | **DESPLEGADO** — `engines/base_engine.py` |
| `autopsia.py` | **DESPLEGADO** — paso 7 de `recalibrar_todo` |
| `aprendizaje_continuo.py` | **DESPLEGADO** — paso 8, y aplicado en `alpha_finder` |
| Panel «Lo que el sistema ha aprendido» | **DESPLEGADO** — `dashboard_ui.py` |

### Lo que este lazo NO hace, a propósito

No inventa features, no reentrena modelos y no cambia qué partidos se eligen. Un
lazo autónomo con esas atribuciones se sobreajusta a su propio historial en pocas
semanas. La ampliación de features sigue pasando por A/B con walk-forward y
bootstrap, con una persona mirando — que es como murió, bien documentada, la
hipótesis que originó esta versión.

---

## 6. Próximos pasos

- **La brecha de la Capa 2 tiene una causa identificada y sin cerrar:** la
  corrección por banda no se aplica a lo que se registra. Aplicarla también ahí
  toca EV, Kelly y filtros de selección, así que necesita su propio A/B antes de
  desplegarse. Es la mejora pendiente de mayor tamaño (−16,2 pp sobre 108 picks).
- Reauditar las features de fatiga de **cualquier** motor que use fechas cuando
  se incorpore una fuente con granularidad distinta. La fuga de la v96 vivió
  cinco versiones sin que nadie la mirara.
- Con más picks liquidados, reevaluar la corrección de producción: hoy pesa un
  42 % frente al prior del ledger.

## Scripts de esta versión

```
_v101_ab_contexto_futbol.py      A/B del contexto sobre el ledger de fútbol
_v101_auditoria_empate.py        permutación, control de liga, feature a feature
_v101_descomponer_escalon.py     separa la fuerza de hoy del rival anterior
_v101_ab_contexto_neto.py        el A/B honesto, con el ELO en la base
_v101_ab_contexto_tenis.py       A/B sobre el vector desplegado de tenis
_v101_auditoria_tenis.py         controles del resultado imposible
_v101_fuga_fatiga_wta.py         mide el coste real de la fuga
_v101_validar_aprendizaje.py     walk-forward del lazo de aprendizaje
```
