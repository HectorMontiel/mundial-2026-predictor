# v125 + v126 + v127 — El clasificador, la regla del tenis y el consenso de 20 casas

Tres versiones que van juntas porque cada una nació de medir la anterior.

---

## 1. El clasificador (v125)

Tres secciones con un semáforo cuyo criterio **no es el EV del modelo** — ése
está medido en −4,66 % a −6,52 % sobre 37.158 apuestas — sino la ventaja de
precio contra el consenso del mercado.

### El umbral no es cero, y eso es nuevo

`ventaja > 0` parecía el filtro obvio. Medido sobre `odds_snapshots.csv`, 1.414
selecciones con dos o más casas y resultado conocido:

| ventaja sobre el consenso | n | ROI | p5 |
|---|---|---|---|
| 0 % – 5 % | 623 | **−11,48 %** | −20,18 % |
| 5 % – 100 % | 791 | **+8,22 %** | −3,12 % |

Comprobado con cuatro definiciones del consenso (media y mediana, con 2 y con 3
casas mínimas): la dirección no cambia en ninguna. **Una ventaja pequeña no es
una ventaja.** De ahí `UMBRAL_VENTAJA = 0,05`.

Ni siquiera el tramo bueno tiene p5 positivo (−3,12 %), así que la Sección 1 se
presenta como *la mejor apuesta disponible*, no como una apuesta ganadora.

### El filtro por backtest de liga queda apagado

Medido, a petición del usuario:

| | n | ROI | p5 |
|---|---|---|---|
| liga con backtest > 53,5 % | 213 | +10,71 % | **−13,06 %** |
| liga con backtest ≤ 53,5 % | 1.107 | −1,76 % | −9,69 % |

La estimación puntual favorece al filtro, pero con 213 apuestas su p5 es peor
que el del grupo al que supera. Entra como **indicador `Confianza: X/5`** y como
criterio de orden, con `exigir_backtest=False` por defecto.

---

## 2. Tres fallos que la medición de frecuencia destapó

Al comprobar **cuántas veces** encuentra algo la Sección 1 (23 partidos, 5
ligas), salió un único acierto: `Empate @ 16,00 · +392 % sobre el mercado`.

No era una mina de oro.

### 2.1 El emparejador cruzaba dos clubes distintos

Pedía `Athletico-PR vs Bragantino` y Playdoit devolvía **`Atlético-MG vs
Bragantino`** — otro club, otra competición (Copa Sudamericana), otra fecha. Con
**similitud 1,0**: el normalizador machaca los guiones, así que los dos
compartían su único token significativo (`atletico`).

Sin la medición de frecuencia, la Sección 1 habría debutado recomendando el
precio de otro partido.

**Dos defensas**, causa raíz y red independiente:
- `cuotas_multi.marca_estado`: el sufijo de estado brasileño (PR/MG/GO/RJ…) es
  la identidad del club y se trata como el sufijo de filial que ya existía.
- `clasificador.VENTAJA_IMPOSIBLE = 0,30`: dos casas reales no difieren un 40 %
  en el mismo suceso. Cualquier ventaja mayor se marca como error de datos.

### 2.2 El umbral se aplicaba a la magnitud equivocada

El 5 % se calibró comparando contra la **media** del resto de casas, pero la
implementación comparaba contra el **mejor** del resto — mucho más exigente.
Añadidos `cuota_media` y `dif_vs_consenso`.

### 2.3 El contador de casas era el equivocado

El semáforo miraba `n_casas` de la fila de Playdoit, que **siempre vale 1** por
ser una sola casa. Todo caía en Sección 2 con «una sola casa cotiza este
mercado» y la Sección 1 quedaba vacía por construcción, sin que nadie se
enterara. Ahora mira las casas del consenso.

---

## 3. La regla del tenis (v126) — la primera joya real

Medido sobre `pick_ledger_deportes.csv`, apostando el lado más probable del
modelo a la cuota registrada:

| deporte / banda | n | acierto | ROI | **p5** |
|---|---|---|---|---|
| **Tenis · prob ≥ 90 %** | **1.793** | **91,69 %** | **+5,76 %** | **+0,18 %** |
| Tenis · 80-90 % | 4.906 | 84,51 % | −1,96 % | −3,01 % |
| Tenis · global | 46.151 | 65,88 % | −4,92 % | −5,53 % |
| MLB · 60-70 % | 751 | 66,05 % | +2,75 % | −1,68 % |
| MLB · global | 7.541 | 56,45 % | −0,97 % | −2,68 % |

**Es lo único de todo el proyecto con p5 positivo.** Y lo cruza por los pelos
(+0,18 %).

Tres cosas que la interfaz dice con ello:

1. La cuota media de esa banda es **~1,15**. Son apuestas de cuota baja: hace
   falta volumen y un solo precio malo se come varias apuestas buenas.
2. **El tenis global pierde −4,92 %**, casi lo mismo que el fútbol. El 67 % de
   backtest no es señal de élite: es un mercado de dos resultados donde el
   favorito gana solo.
3. **La MLB tampoco es rentable** en el moneyline (−0,97 %).

La premisa del plan era «tenis y MLB ya sabemos que son rentables, no hace falta
medirles el p5». Medirlo es lo que encontró la única bolsa rentable — y de paso
desmintió la premisa.

---

## 4. El barrido de casas (v126) — el techo del consenso gratuito

`sondeo_casas.py`, **27 fuentes** por todas las vías de acceso conocidas:

```
con cuotas utilizables ......... 7 de 27
nuevas integrables ............. 0
```

Los fallos no son aleatorios: Altenar valida la integración (sólo `playdoit2`),
Kambi limita por IP, las casas de EE. UU. bloquean por origen, las mexicanas no
tienen endpoint público, y los agregadores sólo dan HTML.

**El techo del consenso gratuito está alcanzado en cinco casas.** La única
palanca que queda es de pago: The Odds API, 30 $/mes por 20.000 créditos, 40+
casas e histórico desde 2020. Plan de incorporación y advertencia sobre la
cobertura de las ligas pequeñas, en `BITACORA_ARQUITECTURA.md` §5c.

**Y una casa que estaba desperdiciada dentro del propio código**: DraftKings
(vía el core de ESPN) entraba sólo `if not casas`, o sea que se descartaba en
cuanto cualquier otra casa cotizaba el partido. Ahora entra siempre al consenso.

---

## 4b. El consenso pasa de 5 a 20 casas (v127)

Con el plan **gratuito** de The Odds API: 500 créditos al mes que se renuevan.

```
Consenso ANTES:  5 casas
Consenso AHORA: 20 casas
Pinnacle · Betfair · William Hill · 1xBet · Marathon · Unibet (NL/SE) ·
888sport · Betsson · Coolbet · Nordic Bet · LeoVegas · Tipico · Betclic ·
PMU · BetOnline · GTbets · Matchbook · Bovada · Playdoit
```

**Y la Sección 1 tiene su primer pick real:**

```
Gana Juárez · Playdoit 5.75 · consenso de 20 casas 5.359 → +7,3 %
```

Con 4 casas ese +7,3 % caía en amarillo por falta de testigos. Con 20 cruza el
umbral del 5 %.

### El presupuesto, calculado antes de escribir una línea

El coste es `mercados × regiones` **por liga** (una llamada trae todos sus
partidos). Con 500 al mes son 16,7 al día:

| configuración | créditos/mes | ¿cabe? |
|---|---|---|
| 5 ligas × 2 mercados × 4 veces/día | 1.200 | **no** |
| 5 ligas × 2 mercados × 3 veces/día | 900 | **no** |
| 5 ligas × 1 mercado × 3 veces/día | 450 | justo |
| **bajo demanda**, 10 partidos/día | **300** | sí ← elegido |

Se eligió bajo demanda por dos razones: la llamada trae **toda la liga**, así
que mirar diez partidos de la misma jornada cuesta **un** crédito con caché de
30 min; y el dato llega de hace minutos en vez de la foto de las 18:00.

**Corte duro a los 450 créditos** en el código. Por encima, el módulo deja de
llamar y el tablón vuelve solo a sus cinco casas.

### El fallo que cazó el indicador de consenso

Al añadir el indicador que muestra «Consenso: X casas», la ficha decía
**«Consenso: 4 casas · modo de respaldo»** teniendo veinte disponibles.

Causa: `_mostrar_cuotas_multi` llamaba a `cuotas_partido` **sin pasar `liga`**,
y ese argumento decide si la competición está en la lista blanca. Medido:

```
CASAS con liga=liga_mx : 20
CASAS sin liga         :  4
```

La integración estaba bien; la llamada no. Sin el indicador habría ido a
producción usando 4 casas mientras el contador marcaba consumo.

### Por qué el módulo NO se llama `odds_api`

La v88 retiró un módulo con ese nombre porque «la clave devolvía 401 en TODAS
las ligas y sólo llenaba el arranque de errores, uno por competición», y dejó
`test_sin_the_odds_api` para que no volviera. **Ese guardián sigue intacto y
pasando.**

El módulo nuevo se llama `consenso_api` porque hace otra cosa: aquél era la
fuente de cuotas con clave de pago, éste ensancha el consenso con clave
gratuita, tope de gasto y caída limpia. Verificado el modo de fallo exacto de
la v88, con la clave quitada:

```
casas: 4 · avisos/errores emitidos: 0
```

Cubierto por `test_consenso_api_degrada_en_silencio`.

### Lo que la cobertura NO resuelve

De las 19 ligas huérfanas de fútbol, este proveedor cubre **8**, y su histórico
—que es lo que necesitarían— **no existe en el plan gratuito**
(`HISTORICAL_UNAVAILABLE_ON_FREE_USAGE_PLAN`, coste 0 averiguarlo). Las 24
quedan congeladas.

Coste total de todo el sondeo y las pruebas: **4 créditos de 500**.

## 5. Por qué la Sección 1 salía vacía antes del consenso ampliado

Sobre 23 partidos de 5 ligas, con todos los arreglos: **cero picks verdes**.

Dos razones medidas:

- De 50 mercados de un partido, sólo **13 tienen otra casa** con la que
  compararse. Las líneas alternativas las publica casi siempre Pinnacle.
- En los mercados líquidos (1X2, con 4 casas), Playdoit está a **±0,5 %** del
  consenso. La mediana de su diferencia es **−2,07 %**.

La Sección 1 no está rota: está diciendo que hoy no hay nada que valga la pena.

---

## 6. El barrido de prioridad por liga

`barrido_ligas.py` con tres filtros (margen > 1,5 pts, > 1.500 partidos, p5 > 0).
**Cero ligas de 57 pasan.** Y hay un motivo estructural:

```
correlación margen vs p5           −0,669
correlación margen vs ROI simulado −0,738
```

El margen mide **lo malo que es el modelo** en esa liga, no la oportunidad.
Donde más margen hay, peor se comporta apostarlo. Integrado en
`retrain_leagues.yml` con ejecución diaria.

Las 24 ligas sin ROI simulado tienen las columnas de cuota con **cero filas
rellenas**: no es un cálculo que falte, es el dato.

---

## 7. Tests añadidos

| test | qué protege |
|---|---|
| `test_clasificador_tres_secciones` | el semáforo, el devig y que el parlay parta de la Sección 1 |
| `test_sufijo_de_estado_no_confunde_clubes` | que `Athletico-PR` no vuelva a emparejar con `Atlético-MG` |
| `test_consenso_de_varias_casas` | que la ventaja se mida contra el consenso y no contra el mejor precio |
| `test_regla_tenis_90` | la regla del tenis, y que NO se extienda a otras bandas ni a otros deportes |
| `test_sondeo_de_casas` | que el barrido siga cubriendo las vías conocidas y vigilando las cinco integradas |
| `test_telegram_envia_picks_y_ponches` | el envío de EV+ y de ponches, con el aviso dentro del mensaje |
| `test_bitacora_de_arquitectura` | que las cifras que gobiernan el sistema no se borren sin medir de nuevo |
| `test_consenso_api_respeta_el_presupuesto` | que nadie suba los mercados por defecto ni meta las huérfanas en la lista blanca |
| `test_consenso_api_degrada_en_silencio` | el modo de fallo por el que la v88 retiró su predecesor |
| `test_la_ficha_pide_las_cuotas_con_liga` | que toda llamada lleve la liga: sin ella el consenso cae a 4 casas en silencio |

---

## 8. Lo que sigue sin cambiar

- **Ni una probabilidad, ni un filtro, ni un peso del modelo.**
- **El edge sigue estando en el precio**, y hoy el precio no da señal porque
  faltan testigos, no porque falte modelo.
- **Sigue sin haber ninguna promesa de ganar.** La única regla con p5 positivo
  lo tiene en +0,18 %.
