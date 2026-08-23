# Bitácora de arquitectura — regla de oro del proyecto

> Este documento manda sobre cualquier versión nueva. Antes de añadir una
> función, se comprueba aquí si contradice algo ya medido. Si lo contradice, o
> se aporta una medición que lo desmienta, o no se añade.
>
> Última revisión: 2026-08-21 · a partir de la v148 (temporada vigente,
> caché del barrido y pesos fuera de git).

---

## 0. La regla que gobierna todas las demás

**Ninguna cifra se publica sin la medición que la respalda, y ninguna medición
se ignora porque incomode.**

Este proyecto lleva ciento y pico versiones y su historia es, en gran parte, la
de descubrir que sus propias ideas no funcionaban. Lo que sigue no son
opiniones: son mediciones sobre decenas de miles de apuestas fuera de muestra.
Están arriba del todo porque el resto del documento se apoya en ellas.

### Lo que está medido, con su tamaño de muestra

| Hallazgo | Medición |
|---|---|
| Apostar por la probabilidad del modelo **pierde dinero** | ROI de −4,66 % a −6,52 % en **todas** las bandas con muestra real · 37.158 apuestas |
| El EV que declara el modelo es **anti**-indicador del cierre | correlación −0,054 con el CLV |
| El modelo **no bate al mercado** | supera la precisión del mercado en **8 de 33** ligas con referencia (medido 2026-08-11); o sea que **pierde en 25 de 33** |
| Comprar al **mejor precio** sí gana | +11,49 % en el tramo de juicio · p5 del bootstrap +1,73 % |
| El precio importa más que el modelo | +1,37 % de ROI **sin modelo ninguno**, sólo comprando barato |
| Playdoit paga peor que el mercado | −4,57 % de media sobre 13 mercados comparables (Monterrey–Juárez, 2026-08-10) |

### Lo ÚNICO con p5 positivo medido en todo el proyecto (v126)

Medido sobre `pick_ledger_deportes.csv`, apostando el lado más probable del
modelo a la cuota registrada:

| deporte / banda | n | acierto | ROI | **p5** |
|---|---|---|---|---|
| **Tenis · prob ≥ 90 %** | **1.793** | **91,69 %** | **+5,76 %** | **+0,18 %** |
| Tenis · 80-90 % | 4.906 | 84,51 % | −1,96 % | −3,01 % |
| Tenis · global | 46.151 | 65,88 % | −4,92 % | −5,53 % |
| MLB · 60-70 % | 751 | 66,05 % | +2,75 % | −1,68 % |
| MLB · global | 7.541 | 56,45 % | −0,97 % | −2,68 % |
| Fútbol · global | 37.158 | — | −4,66 % a −6,52 % | negativo |

**El tenis con probabilidad ≥ 90 % es lo único que cruza el listón del
proyecto.** Y lo cruza por los pelos: p5 +0,18 %, o sea el aprobado más raspado
posible. Se despliega porque la regla dice p5 positivo, no porque sea una mina.

Tres cosas que hay que decir con ello:

- **El tenis GLOBAL no es rentable.** −4,92 % con p5 −5,53 %, prácticamente lo
  mismo que el fútbol. La idea de que «el tenis va bien porque el backtest es
  del 67 %» no se sostiene: ese 67 % es un mercado de dos resultados donde el
  favorito gana solo. Lo que funciona es una banda concreta, no el deporte.
- **La MLB tampoco.** −0,97 % global. Mejor que el fútbol, pero negativo.
- **Encontrarlo requirió medir justo lo que se daba por sabido.** El plan
  proponía no medir el p5 del tenis y la MLB «porque ya sabemos que son
  rentables». Medirlo es lo que encontró la única bolsa rentable del proyecto —
  y de paso desmintió la premisa.

### La NFL, medida desde cero en la v131 — y sale igual

Se integró un deporte nuevo con datos nuevos (1.055 partidos de ESPN, 2023-2026,
con estadística de equipo al 100 % y cuotas de cierre reales al 99,8 %) y su
propio modelo. El resultado **reproduce el §0 sin tocar nada de lo anterior**,
que es la confirmación independiente más fuerte que este documento tiene:

| medición (NFL, juicio = temporada 2025, n=285) | resultado |
|---|---|
| acierto del modelo vs acierto del mercado | **63,0 % contra 66,5 %** |
| Brier del modelo vs Brier del mercado | **0,2231 contra 0,2119** |
| calibración del modelo | correcta: dice 57,3 % y acierta 58,6 %; dice 62,0 % y acierta 62,5 % |
| ROI apostando el lado del modelo | **−4,32 %** (p5 −12,16 %) |
| ROI filtrando por **EV del modelo > 0** | **−1,62 %**, y el acierto **cae del 62,8 % al 48,8 %** |
| ROI filtrando por **EV del modelo > 5 %** | **−2,07 %**, acierto **45,5 %** |
| correlación margen esperado ↔ línea de cierre | +0,77 (aprende señal real, sólo que menos que el precio) |

**El EV del modelo vuelve a ser anti-indicador, y aquí se ve más claro que en
fútbol:** cuanto más valor declara, peor acierta — del 62,8 % al 45,5 %. En
fútbol esto se veía como una correlación de −0,054 con el CLV; en la NFL se ve
como una caída de 17 puntos de acierto. Es el mismo fenómeno con otra cara.

**El hándicap tentó y no pasó.** +5,96 % en 2025 (n=285), que es el canal más
cerca de la regla en todo el proyecto después del precio. Se quedó fuera
porque su otra temporada da −4,88 % y su p5 es negativo en las dos. Cara o
cruz, no ventaja.

**La pretemporada no admite modelo, y está medido.** Sobre 103 partidos de
pretemporada (2024-2025), la correlación entre el margen predicho y el real es
**−0,013** y el Brier **0,2727 — peor que decir 50 %**. Lo destapó un pick real
de 82,3 % con EV +38 %. Regla añadida: en pretemporada no se publica
probabilidad de ningún deporte cuyo modelo no se haya entrenado con ella.

### La consecuencia incómoda

**El modelo ya está bien calibrado en probabilidad, y aun así pierde.** Ésta es
la tabla completa de calibración, sobre 89.748 predicciones fuera de muestra:

| banda | n | dice el modelo | acierta de verdad | ROI | p5 |
|---|---|---|---|---|---|
| 0,50–0,55 | 13.792 | 52,5 % | 52,3 % | **−5,03 %** | −6,31 % |
| 0,55–0,60 | 13.106 | 57,5 % | 57,5 % | **−4,66 %** | −5,94 % |
| 0,60–0,65 | 8.821 | 62,1 % | 61,1 % | **−4,88 %** | −6,17 % |
| 0,65–0,70 | 1.439 | 66,3 % | 61,5 % | **−6,52 %** | −9,77 % |
| 0,70–0,75 | 33 | 71,3 % | 81,8 % | +27,76 % | +8,75 % |

Léase despacio: cuando el modelo dice 57,5 %, acierta 57,5 %. Cuando dice
52,5 %, acierta 52,3 %. **La probabilidad es correcta** — el error medio de
calibración es de décimas. Y el ROI sigue siendo −5 % en todas las bandas.

El motivo es que el precio ya incorpora esa misma probabilidad **más el margen
de la casa**. Acertar el 61 % de las veces a cuota 1,55 pierde dinero, porque
1,55 × 0,61 = 0,946.

La banda 0,70–0,75 luce +27,76 % con **33 apuestas**. Eso es ruido, no una
oportunidad, y ninguna regla del sistema puede apoyarse en ella.

**De aquí sale la tesis del sistema:** el trabajo no es predecir mejor. Es
**comprar mejor**. El modelo sirve para ordenar y para descartar, no para
decidir que algo tiene valor.

---

## 1. Arquitectura de visualización: los 2 niveles

```
┌─ NIVEL 1 · APUESTAS DEL DÍA ──────────────────────────────────┐
│  Universo: todos los partidos de HOY, todos los deportes.     │
│  Fuente:   barrido de alpha_finder (una pasada, cacheada).    │
│  Salida:   las 3 secciones aplicadas al día entero.           │
└───────────────────────────────────────────────────────────────┘
┌─ NIVEL 2 · VISTA DE COMPETICIÓN ──────────────────────────────┐
│  Universo: un partido concreto de una liga concreta.          │
│  Fuente:   tablero completo de Playdoit (GetEventDetails) +   │
│            tablón de referencia de las otras cinco casas.     │
│  Salida:   las 3 mismas secciones, con mucho más detalle:     │
│            69 mercados por partido en vez de 3.               │
└───────────────────────────────────────────────────────────────┘
```

Los dos niveles **comparten el mismo clasificador** (§3). Un pick que en el
día sale como «Máximo Valor» tiene que salir igual al abrir su partido; si no,
uno de los dos está mintiendo.

**Diferencia de coste, que condiciona el diseño:** el Nivel 1 mira cientos de
partidos y sólo puede permitirse una petición por catálogo (5 mercados por
partido). El Nivel 2 mira uno y puede permitirse una petición por partido (148
mercados). Por eso el detalle de Playdoit **nunca** entra en el barrido.

---

## 2. El clasificador: las 3 secciones

### Sección 1 — «Máximo Valor / Élite» (para jugar en solitario)

**Lo que pediste:** `EV_Playdoit > 0`, es decir, que la cuota de Playdoit supere
la cuota justa del modelo.

**Por qué eso no puede ser el filtro:** ése es exactamente el criterio que la
tabla del §0 mide en −4,66 % a −6,52 %. Cuando Playdoit paga por encima de lo
que el modelo cree justo, la explicación más probable **no** es que Playdoit sea
generosa: es que el modelo se equivoca. El propio proyecto lo tiene documentado
con un caso real —«Menos de 1.5 goles» @ 5,40 con EV declarado +118,7 % contra
un mercado sharp que daba 18,5 %— y por eso existe la constante
`EV_SOSPECHOSO`.

**El filtro que sí implementa tu intención:** tu frase era «si Playdóit está
pagando de más, es una mina de oro». Correcto — la pregunta es *de más
comparado con qué*. Comparado con el modelo, es ruido. Comparado con **el
consenso del mercado sin margen**, es la única ventaja que este proyecto ha
medido en positivo.

```
p_mercado  = devig(cuotas del ancla sharp: Pinnacle + Matchbook)
c_justa    = 1 / p_mercado
VENTAJA    = c_playdoit / c_justa − 1        ← el criterio de la Sección 1
EV_modelo  = c_playdoit × p_modelo − 1       ← se muestra, NO decide
```

**Entra en Sección 1 si `VENTAJA > 0`**, o sea si Playdoit paga por encima del
precio justo del mercado. Eso es un arbitraje parcial contra el consenso, no una
opinión.

`EV_modelo` sigue en pantalla porque es información, y porque cuando los dos
coinciden la señal es más fuerte. Pero no abre ni cierra la puerta.

### Sección 2 — «Máxima Confianza» (patas de alta probabilidad)

Picks de probabilidad alta (80–95 %) cuyo precio no compensa.

**Se mantiene**, con una corrección importante en la etiqueta. La que pediste
—«NO JUGAR EN SOLITARIO. Úsalo en parlays»— da a entender que combinarlos
arregla el problema. **No lo arregla: lo multiplica.** Ver §4.

**Etiqueta correcta:** «Alta probabilidad, precio insuficiente. Combinarlos NO
mejora el valor: multiplica el margen de la casa. Úsalos sólo si quieres una
estructura de boleto concreta y sabiendo lo que cuesta.»

### Sección 3 — «Combinadas»

**Se mantiene**, con el generador de §4, que sólo combina patas con ventaja de
precio.

### Sección 1 en el NIVEL 1 (el día entero) — qué sube y con qué medición

El criterio de arriba (`VENTAJA` contra el consenso) necesita el tablero de
Playdoit, y el barrido del día no puede pagarlo: mira cientos de partidos y
sólo se permite una petición por catálogo (§1). Así que en el Nivel 1 la
Sección 1 no se decide fila a fila, sino **por canal entero ya medido**. Y sólo
dos canales tienen p5 de bootstrap positivo en el tramo que no se usó para
elegirlos, que es el listón del §0:

| canal | qué es | tramo de elección | tramo de juicio |
|---|---|---|---|
| **Precio al lado LOCAL** (fútbol) | `valor_vs_sharp`: una casa blanda paga por encima del devig de Pinnacle, con `p ≥ 0,30` y `EV ≥ 1 %` | n=1817 · +5,09 % · **p5 +1,09 %** | n=353 · +11,49 % · **p5 +1,73 %** |
| **Tenis con `prob ≥ 90 %`** y precio publicado | §0 | — | n=1.793 · +5,76 % · **p5 +0,18 %** |

**La NFL NO añade un tercer canal, y el motivo importa (v131).** Se intentó
medir el mismo canal de precio en fútbol americano descargando el cierre de
todas las casas que publica ESPN: 2.906 cierres de 12 casas sobre 897 partidos.
Pero el reparto lo impide — **207 partidos con ≥2 casas en 2023, 2 en 2025 y
ninguno en 2024**: ESPN conserva el histórico multi-casa sólo de una temporada.
Sin dos precios no hay line shopping que medir, así que el veredicto es **«no
medible»**, no «medido y negativo», y queda escrito así en
`nfl_canal_precio.json`. La NFL se queda en la Sección 2 —el camino por
defecto— hasta que `odds_snapshots` acumule fotos propias de Pinnacle, Bovada
y Playdoit, que es la vía del §6.

**El mismo canal al empate y al visitante NO sube**, y ésa es la parte que
importa: sale de partir `_v90_line_shopping_por_lado` por lado.

| lado | tramo de elección | tramo de juicio | robusto |
|---|---|---|---|
| local | +5,09 % · p5 +1,09 % | +11,49 % · p5 **+1,73 %** | **SÍ** |
| empate | +12,21 % · p5 +1,08 % | −7,09 % · p5 **−38,91 %** | no |
| visitante | +10,21 % · p5 +4,28 % | +7,92 % · p5 **−5,10 %** | no |

El empate y el visitante lucen bien en la mitad con la que se eligió y se
hunden en la otra. Es el retrato exacto de un hallazgo que no era real, y el
motivo de que el lado viaje ahora con cada pick en vez de deducirse del texto.

**Dos cosas que esto destapó:**

1. **El mínimo de cuota de 1,50 del barrido estaba tirando la única regla
   rentable del proyecto.** La banda de tenis `≥ 90 %` tiene cuota media ~1,15,
   así que todos sus picks caían a la Capa 2 con el motivo «cuota por debajo
   del mínimo» y no llegaban a la pantalla del día. El reparto en secciones
   mira también la Capa 2 justo por esto.
2. **La MLB, la NBA y el tenis por debajo del 90 % usan el mismo método de
   precio pero no tienen su propio desglose por lado.** Sin p5 propio no
   suben: bajan a la Sección 2 con «mismo método, sin medir».

Lo que no sube **no se oculta**: baja a la Sección 2 con el motivo medido
escrito al lado. La diferencia entre «no te lo enseño» y «te lo enseño diciendo
lo que rinde» es toda la tesis de este documento.

---

## 3. Tabla de reglas — fórmulas exactas

### 3.1 Probabilidad calibrada

**Lo que pediste:** `Prob_calibrada = Prob_bruta × (Backtest / 100)`.

**Por qué no se puede aplicar así:** esa fórmula no calibra, deforma. Tres
motivos, con números:

1. **El modelo ya está calibrado.** Dice 57,5 % y acierta 57,5 % (n = 13.106).
   Multiplicar por un backtest de 0,52 lo dejaría en 29,9 %, que es un error de
   28 puntos **introducido por la corrección**.
2. **Mezcla dos magnitudes distintas.** El «backtest» de una liga es la
   precisión de acertar el 1X2, un problema de **tres** resultados donde el azar
   puro da 33 % y el techo del mejor mercado del mundo va del 42 % (Serie B) al
   59 % (Turquía). La probabilidad de un mercado binario no se corrige con eso.
3. **No es monótona en el sentido útil.** Aplicada a un pick del 20 % lo baja al
   10 %, alejándolo aún más de la realidad en la dirección contraria.

**La fórmula que sí se usa** — y que el proyecto ya tenía, sólo que enterrada:

```
Prob_publicada = acierto_real_de_la_banda(Prob_bruta)
```

Es decir: se busca la banda de calibración donde cae la probabilidad bruta y se
publica **el acierto medido en esa banda**, con su `n` al lado. Es una
calibración isotónica por tramos, hecha sobre 89.748 predicciones.

Cuando la banda tiene menos de 500 casos, no se publica número: se dice
«muestra corta». La banda 0,70–0,75 con 33 apuestas es el ejemplo de por qué.

**Y por separado, nunca multiplicando**, se enseña el backtest de la liga con su
techo de mercado, que es lo que responde a «¿cuánto se puede acertar aquí como
máximo?».

### 3.2 Semáforo

**Lo que pediste:** 🟢 verde con `Backtest > 58 %`.

**Por qué ese umbral deja la Sección 1 vacía:** medido hoy sobre las 57 ligas
con modelo, **la mejor es MLB con 54,9 %** y la mediana es 50,4 %. **Ninguna
liga del proyecto llega a 58 %.** La luz verde nunca se encendería.

Peor aún: si se bajara el umbral hasta que encendiera, seleccionaría lo
contrario de lo que se busca. La banda de mayor acierto (0,65–0,70, 61,5 %) es
la de **peor ROI** (−6,52 %).

**El semáforo que sí discrimina** pone el precio delante y el modelo detrás:

| Luz | Condición | Destino |
|---|---|---|
| 🟢 **Verde** | `VENTAJA > 0` (Playdoit paga por encima del justo del mercado) **y** ≥ 2 casas en la referencia **y** `n_banda ≥ 500` | Sección 1 · jugable en solitario |
| 🟡 **Amarillo** | `VENTAJA` entre −2 % y 0 %, **o** una sola casa de referencia, **o** `n_banda < 500`, **o** EV del modelo > 30 % con una sola casa (sospechoso), **o** mercado con EV no fiable (mitades) | Sección 2 · sólo con la advertencia |
| 🔴 **Rojo** | `VENTAJA < −2 %` (Playdoit paga claramente por debajo del mercado) | No se muestra en ninguna vista principal |

El umbral de −2 % no es redondo por gusto: por debajo de esa diferencia lo que
hay es ruido de redondeo entre casas, y marcarlo en rojo empujaría a abrir
cuentas por nada.

**Nota sobre 🔴:** se retira de las vistas principales, **no se borra**. Queda
accesible en un desplegable, porque un usuario tiene derecho a ver por qué algo
se descartó.

### 3.3 Separación de boletos (seguros vs bombazos)

```
SEGURO   = prob_conjunta ≥ 0,50  y  cuota_combinada ≤ 3,00
BOMBAZO  = prob_conjunta < 0,25  o   cuota_combinada > 6,00
```

Nunca se mezclan en un mismo boleto. Cuando el sistema encuentra los dos, sugiere
dos tickets separados con el reparto que pediste (**70 % al seguro, 30 % al
bombazo**), y sobre el bankroll ya limitado por ¼ de Kelly con tope del 5 % por
apuesta, que es la política vigente del proyecto.

---

## 4. El generador de parlays

### 4.1 La aritmética, primero

Para patas independientes:

```
EV_parlay = Π (p_i × c_i) − 1 = Π (1 + EV_i) − 1
```

**Consecuencia:** si todas las patas tienen EV negativo, el parlay tiene un EV
**más** negativo. No hay forma de que la multiplicación de números menores que 1
dé un número mayor que 1.

Con patas del tipo que describe la Sección 2 (probabilidad alta, margen de casa
del 5 %, EV individual −4,76 %):

| patas | prob. conjunta | cuota | EV del parlay |
|---|---|---|---|
| 2 | 72,2 % | 1,26 | **−9,30 %** |
| 3 | 61,4 % | 1,41 | **−13,62 %** |
| 4 | 52,2 % | 1,58 | **−17,73 %** |
| 5 | 44,4 % | 1,77 | **−21,65 %** |

La cuota sube, sí. Pero la probabilidad baja exactamente en la misma proporción
más el margen, que se cobra una vez por pata.

**Por eso la Sección 3 no puede alimentarse de la Sección 2.** Ese era el punto
que había que corregir, y es el más caro de todos los del prompt: es la creencia
que convierte una pérdida del 5 % en una del 22 %.

### 4.2 Cómo sí funciona

Con patas que tienen ventaja de precio real (Sección 1), el mismo efecto
multiplicador juega **a favor**:

| patas con EV +4,50 % | EV del parlay |
|---|---|
| 2 | **+9,20 %** |
| 3 | **+14,12 %** |
| 4 | **+19,25 %** |

**Regla del generador: sólo combina patas de Sección 1 (🟢).** Una sola pata
amarilla contamina el boleto entero.

### 4.3 Redundancia y correlación

Dos guardias, en este orden:

1. **Exclusión por suceso** — no se combinan mercados que describen el mismo
   suceso o uno contenido en otro. El proyecto ya tiene el mapa en
   `match_parlay._ids_en` y `sgp_correlation`. Ejemplos que se rechazan:
   `Gana A` con `A +0.5`; `Gana A` con `A o Empate`; `Más de 2.5` con
   `Más de 1.5`; `1X2` con `Marcador exacto` del mismo lado.
2. **Corrección por correlación** — la probabilidad conjunta **no** es el
   producto. `sgp_correlation.factor_par` ya aplica el ajuste entre mercados del
   mismo partido. Entre partidos distintos se supone independencia, y se
   **declara** que es un supuesto: dos partidos de la misma liga y hora
   correlacionan más de lo que sugiere multiplicar.

**Preferencia de diversificación:** a igualdad de ventaja, el generador prefiere
patas de **partidos distintos y deportes distintos**, que es lo que rompe la
correlación de verdad.

---

## 5. Obtención de las cuotas de Playdoit

**Ya está resuelto, y sin scraping.** Playdoit corre sobre **Altenar**, cuya API
de widget es pública, sin clave y sin coste. La integración se descubrió
inspeccionando las peticiones de su propia web (`integration=playdoit2`).

| Vía | Coste | Frecuencia | Riesgo de bloqueo | Cobertura | Veredicto |
|---|---|---|---|---|---|
| **API de widget de Altenar** *(en uso)* | 0 € | sin límite observado en 4 meses | bajo: es el mismo endpoint que sirve a su web | catálogo: 918-1.027 partidos de fútbol · detalle: 148 mercados/partido | **ELEGIDA** |
| Web scraping con proxies | 20-200 €/mes en proxies | minutos | alto: su front es SPA y cambia sin avisar | la misma | descartada: coste y fragilidad sin ganancia |
| Feeds de terceros (OddsAPI y similares) | 30-500 €/mes | segundos | ninguno | **no cubren Playdoit**, que es una casa mexicana pequeña | descartada: no sirve para el objetivo |
| API oficial de afiliados | requiere alta comercial | — | — | desconocida | no explorada: sin contrato no hay acceso |

**Justificación de la elección:** cuesta cero, se actualiza al ritmo que haga
falta, y el riesgo de bloqueo es el más bajo de las cuatro porque no estamos
imitando a un navegador — estamos llamando al mismo servicio que llama su
página. Las otras tres o cuestan dinero, o no cubren la casa, o ambas.

**Plan si Altenar cierra el widget:** el sistema degrada solo a las cinco casas
de referencia y la sección de Playdoit dice por qué falta. Ya está construido
así (`mercados_playdoit` devuelve `None` y la vista lo explica). Es la misma
política de la v114 con Betfair, que quedó geobloqueada y se sustituyó por
Matchbook sin tocar la interfaz.

**Dos límites que no se ocultan:**
- El catálogo trae 5 mercados por partido; el detalle, 148, a coste de **una
  petición por partido**. Por eso el detalle es de Nivel 2 y no del barrido.
- La API **no dice** si un mercado admite combinada del mismo partido
  (`isParlay` viene a `false` en los 918 eventos, así que no discrimina). La
  interfaz lo advierte en vez de darlo por hecho.

---

## 5b. Barrido exhaustivo de casas (v126) — el resultado y el techo

`sondeo_casas.py` prueba **27 fuentes** por todas las vías de acceso conocidas:
APIs de widget que usan sus propias webs (Altenar, Kambi, Digitain), casas con
API propia, exchanges, mercados de predicción y agregadores.

```
con cuotas utilizables ......... 7 de 27
nuevas integrables ............. 0
```

Las siete son las cinco ya integradas (Playdoit, Pinnacle, Bovada, Unibet,
Matchbook) más football-data (histórico) y los dos mercados de predicción ya
descartados en la v114 por no casar nombres.

**Los fallos no son aleatorios, y eso es lo informativo:**

| patrón | casas | qué significa |
|---|---|---|
| Altenar responde 400 salvo `playdoit2` | Betano, Strendus, Codere | la plataforma valida la integración: no se puede colar otra marca |
| Kambi devuelve 400/429 | 888sport, Betsson, Rushbet | limita por IP, y el proyecto ya prohíbe una segunda marca de Kambi por correlación |
| 403 de bot/geo | DraftKings directa, FanDuel, Smarkets, Betfair | bloqueo por origen, no por cabeceras |
| DNS o 404 | Caliente, Betcris, Betsson MX, 1xBet | sin endpoint público conocido |
| sólo HTML | OddsPortal, FlashScore | exigiría scraping del front: frágil y en terreno de términos de uso |
| 401 con clave | The Odds API | **es la única vía real, y es de pago** |

**Conclusión honesta**: el techo del consenso gratuito está alcanzado en cinco
casas. No es que no se haya buscado: es que las vías gratuitas restantes o
bloquean por origen, o exigen scraping con riesgo de términos de uso, o no
existen.

**La única palanca que queda es de pago**, y está cuantificada abajo.

## 5c. The Odds API — la vía de pago, con números

| plan | coste | créditos/mes | histórico |
|---|---|---|---|
| Starter | 0 $ | 500 | sí |
| 20K | **30 $/mes** | 20.000 | sí |
| 100K | **59 $/mes** | 100.000 | sí |
| 5M | 119 $/mes | 5.000.000 | sí |

Cubre **más de 40 casas** (DraftKings, FanDuel, BetMGM, Caesars, Bovada,
Pinnacle, Betfair, William Hill, 1xBet, Unibet…) y sirve **histórico desde
junio de 2020**, con fotos cada 10 minutos (cada 5 desde septiembre de 2022).

**Lo que resolvería, de las dos cosas que hoy bloquean el sistema:**

1. **El consenso** (Tarea 1). Pasar de 5 casas a 40+ multiplica los mercados
   con testigo. Hoy sólo 13 de 50 mercados de un partido tienen con qué
   compararse; ése es el motivo real de que la Sección 1 salga vacía.
2. **Las 24 ligas sin cuotas** (Tarea 5). Su histórico tiene las columnas de
   cuota con **cero filas rellenas** — no es un cálculo que falte, es el dato.
   El histórico de esta API es la vía directa para rellenarlas.

**Advertencia sobre la cobertura, que hay que verificar antes de pagar**: la
documentación es explícita en que las ligas pequeñas tienen ventanas históricas
más cortas. Nuestras 24 huérfanas son justamente de ese perfil (Primera
Nacional argentina, Bolivia, Chile, Colombia, Copa de Brasil). **Antes de
contratar nada hay que comprobar con el plan gratuito de 500 créditos si esas
ligas concretas están cubiertas.** Pagar 30 $/mes para descubrir que la
Primera Nacional no está sería el error evitable.

**Plan de incorporación propuesto:**

| paso | esfuerzo | coste |
|---|---|---|
| 1. Alta gratuita y sondeo de cobertura de las 24 ligas | 1 sesión | 0 $ |
| 2. Si cubre ≥ 10 de las 24: contratar el plan de 30 $ | — | 30 $/mes |
| 3. Backfill histórico a `odds_snapshots.csv` (el esquema ya existe) | 1 sesión | — |
| 4. Añadir sus casas al consenso en vivo de `cuotas_partido` | 1 sesión | — |
| 5. Volver a correr `barrido_ligas.py` con los p5 ya calculables | automático | — |

El paso 1 no cuesta nada y decide todos los demás. Es lo siguiente que haría.

**Otras fuentes evaluadas** para el histórico: Apify (odds de 9+ casas, 25+
ligas, temporadas 2000/01-2025/26) y TheStatsAPI (10 años, profundo en las
cinco grandes europeas y competiciones sudamericanas principales). Las dos
tienen el mismo riesgo de cobertura en las ligas menores y ninguna es más
barata que los 30 $ del plan básico, así que The Odds API es la primera a
probar por tener el plan gratuito con el que verificar antes de pagar.

## 6. Almacenamiento: aprender de los errores de precio de Playdoit

**No se construye una base nueva.** El proyecto ya tiene la infraestructura y
está probada:

- `odds_snapshots.csv` — una foto al día por partido y **por casa**, con
  `dias_al_partido`, `fase` (foto/cierre) y las columnas de 1X2, over/under,
  BTTS y hándicap.
- `daily_snapshots.py` — la escribe la tarea diaria. Nunca pisa una foto
  anterior (`INSERT OR IGNORE` sobre `snapshot_key`), así que el movimiento de
  la línea queda reconstruible.
- `import_historical_odds.py` — el cierre desde football-data, que es contra lo
  que se calcula el CLV.

**Lo que hay que añadir (v124):**

1. **Playdoit entra en el snapshot con su tablero completo**, no sólo con el
   1X2. Hoy se guarda su 1X2; con el detalle disponible se pueden guardar
   también totales, hándicaps y mitades.
2. **Una columna `ventaja_vs_ancla`** por fila: el diferencial contra el precio
   justo del mercado en el momento de la foto. Es el dato que permite responder
   la pregunta que de verdad importa: *¿cuándo se equivoca Playdoit, y en qué
   mercados?*
3. **El CLV contra el cierre de Playdoit**, no sólo contra el cierre del
   mercado. Si Playdoit mueve su línea hacia donde apostamos, la ventaja era
   real; si la mueve en contra, era ruido.

**Lo que se podrá contestar en unas semanas y hoy no:** en qué ligas y en qué
mercados Playdoit es sistemáticamente cara o barata. Eso sí es una ventaja
explotable y medible, y es el único camino que este documento considera
prometedor a medio plazo.

---

## 7. Las 8 mejoras: estado y veredicto

| # | Mejora | Veredicto | Estado |
|---|---|---|---|
| 1 | Modelo independiente por liga | **Ya existe.** 57 modelos, uno por competición, cada uno con su backtest y su techo de mercado. Lo que falta no es separarlos: es aceptar que ninguno llega a 58 % | hecho antes de la v122 |
| 2 | Lesiones y árbitros en vivo | **Parcial y honesto.** Árbitros sí (`arbitros.py`, en la plantilla). Lesiones: hay `lineup_impact.py` pero **sin feed en vivo**. Requiere fuente nueva; se evaluará con la misma vara: si no mejora el p5 en juicio, no entra | pendiente · v125 |
| 3 | Probabilidad calibrada | **Reformulada.** La fórmula propuesta deforma en vez de calibrar (§3.1). Se usa la calibración isotónica por bandas que ya está medida | por aplicar · v124 |
| 4 | Semáforo | **Recalibrado.** El umbral de 58 % dejaría la Sección 1 vacía: ninguna liga llega. Se sustituye por el criterio de precio (§3.2) | por aplicar · v124 |
| 5 | Line shopping «exclusivo Playdoit» | **Matizado.** Line shopping requiere ≥2 casas por definición. Playdoit es la única casa **accionable**; las otras cinco se conservan como **ancla de referencia**, que es lo que hace posible medir si Playdoit paga bien | hecho en v122 (`comparar_con_el_mercado`) |
| 6 | Separación de boletos | **Aceptada tal cual.** Sin conflicto con nada medido | por aplicar · v124 |
| 7 | EV+ de MLB y tenis a Telegram | **Aceptada tal cual** | **en la v124** |
| 8 | Ponches a Telegram | **Aceptada tal cual** | **en la v124** |

---

## 8. Stack tecnológico

**Recomendación: no cambiar casi nada.** El stack actual es adecuado y migrar
costaría meses sin ganar precisión.

| Capa | Hoy | Veredicto |
|---|---|---|
| Interfaz | Streamlit 1.61 | **Se conserva.** Con la capa de diseño propia de la v122 el techo visual ya no es el problema. Migrar a React costaría rehacer 6.000 líneas para ganar estética |
| Modelos | scikit-learn + XGBoost, artefactos `joblib` por liga | **Se conserva.** El cuello de botella no es el estimador: es que el mercado ya sabe lo que sabe el modelo |
| Datos | pandas + CSV por competición + SQLite para cuotas | **Se conserva.** A este volumen (147.811 partidos, 365.486 de tenis) no hace falta más |
| Cuotas | `requests` contra APIs públicas, caché de 30 min en disco | **Se conserva** (§5) |
| Orquestación | GitHub Actions diario | **Se conserva.** Gratis y ya hace el reentrenamiento, la calibración y la liquidación |
| Despliegue | Streamlit Cloud | **Se conserva**, con la vigilancia de memoria de siempre (`MAX_LIGAS_EN_MEMORIA`) |

**Lo único que merecería inversión:** un `polars` o `duckdb` para el histórico de
cuotas cuando el snapshot diario pase de unos millones de filas. Hoy no lo es.

---

## 8b. Dónde vive cada cosa (v148)

Tres decisiones que se toman una vez y luego mandan.

### La temporada vigente NO se escribe a mano

Las veinte competiciones de football-data declaraban su lista de temporadas
como tuplas literales. El 2026-08-21 todas terminaban en `'2526'` mientras el
curso 2026-27 llevaba una semana jugándose, y el efecto visible eran **35 de
326 partidos (10,7 %) sin pronóstico**: sin descarga del curso en marcha no hay
ascendidos en el catálogo, y sin catálogo no hay mapeo ni predicción.

La lista se deriva de la fecha (`temporadas_fd.py`). Y la descarga TOLERA que
la temporada vigente no esté publicada todavía: football-data devuelve **300
Multiple Choices con HTML**, no 404, así que hay que validar el contenido —
`raise_for_status()` no ve nada raro en un 300.

Corolario que se aplica a todo el proyecto: **una lista de periodos escrita a
mano es una bomba de relojería con fecha conocida.** Si algo depende del
calendario, se deriva del calendario.

### Un equipo nuevo no es un nombre mal escrito

`_completar_desde_espn` mapea contra el catálogo del propio histórico, así que
un ascendido nunca está en él por definición: la cola de ESPN era
estructuralmente incapaz de incorporarlo. Se separan con
`name_mapper.mejor_candidato`, que da el parecido sin decidir: ratio ≥ 0,62 es
el mismo club escrito de otra forma (se descarta, falta un alias); por debajo
es un club que de verdad no estaba (se da de alta). **Ante la duda no se da de
alta**, porque partir el historial de un club en dos es peor que perder un
partido.

Y cuando no hay historia que aprender —un ascendido que aún no ha jugado su
primer partido— **el hueco sigue siendo la respuesta correcta**. Lo que cambia
es que se explica: «no ha jugado todavía en esta competición» en vez de «el
nombre no casa con el catálogo», que sonaba a bug y no lo era.

### El pronóstico se puede servir de caché; el precio, no

El guardia del barrido persiste en disco y sirve resultados de hasta una hora
para que la pantalla aparezca al instante, revalidando por detrás. Eso es
correcto para el 1X2 del modelo, que sale de un entrenamiento de madrugada, y
sería **deshonesto en la dirección peligrosa** para una cuota. Por eso el
resultado viaja siempre con su edad (`_frescura`) y la interfaz avisa **encima
de las pestañas**, antes de que nadie mire un precio.

### El peso de un modelo es un artefacto, no historia

`.git` = 15 GB; 23 commits del bot; 712 MB de `.joblib` reescritos cada
madrugada = ~650 MB por commit, porque git no delta-comprime un binario ya
comprimido. Se midió lo obvio y no servía: comprimir mejor ahorra un 27 %
(xz-6: 5,16 MB frente a 7,07) multiplicando por catorce el tiempo de guardado,
y entrenar al arrancar son ~20 minutos de pantalla en blanco en cada despertar
del contenedor.

Los pesos pasan a ser **assets de un Release de etiqueta fija**, que no viven
en la historia del repositorio, **uno por competición** (mediana 12 MB) para
que la aplicación baje sólo lo que va a usar. La transición la hace el propio
workflow y sólo tras un viaje de ida y vuelta verificado — misma disciplina que
la v68: nunca se publica un artefacto que no se haya vuelto a abrir.

Esto **detiene el crecimiento; no encoge los 15 GB que ya están**. Reescribir la
historia es destructivo, rompe todos los clones y ni siquiera libera espacio en
GitHub sin pasar por su soporte: queda como operación aparte y deliberada. Para
un clon ligero hoy basta `git clone --depth 1 --single-branch`.

---

## 9. Qué NO se va a construir, y por qué

Se deja escrito para no volver a discutirlo cada versión:

- **Una Sección 1 que filtre por EV del modelo.** Es el criterio medido en
  −4,66 % a −6,52 %.
- **Parlays hechos con patas de EV negativo.** Multiplican la pérdida (§4.1).
- **Una probabilidad «calibrada» multiplicando por el backtest.** Deforma una
  probabilidad que ya está bien calibrada (§3.1).
- **Un semáforo basado en la precisión del modelo.** La banda más precisa es la
  de peor ROI.
- **Prometer que el sistema bate al mercado.** No lo bate: pierde en 25 de las
  33 ligas donde hay con qué comparar.

Lo que sí se promete, porque está medido: **el sistema compara precios y dice
cuándo tu casa paga bien**. Eso es lo único con ROI positivo y robusto en todo
el histórico del proyecto.

---

## 10. Córners: por qué el mercado está abierto y el modelo no puede entrar

Es la sección que faltaba, y se escribe con números porque la propuesta de
explotar los córners vuelve cada pocas versiones.

### 10.1 Qué se midió, y cómo

La fórmula de producción era `ck = 4,0 + 0,25·(lam_h+lam_a)·spx·tpo`. La v146
midió su sesgo alimentándola con el xG **observado** del histórico, concluyó que
faltaban 1,3 córners, subió la base a 5,3 y tuvo que revertirlo. Producción la
alimenta con `lam_h`/`lam_a`, que son el xG **predicho**: otra magnitud.

Medido con los lambdas de producción, **11.856 partidos con córners 100 % reales
en 15 competiciones**:

| | valor |
|---|---|
| sesgo ponderado | **+0,435** (no −1,3) |
| base que calibraría el nivel | 3,565 (no 5,3) |
| **correlación con el total real** | **−0,0012** |
| ligas con \|correlación\| > 0,1 | **0 de 15** |

La correlación es además **optimista**: el motor predice cada partido pasado con
el estado ACTUAL de los equipos, o sea con información del futuro. Un límite
superior de 0,004 no deja margen.

### 10.2 Se intentó el modelo bueno, con datos reales

football-data publica córners y remates REALES. Se construyó el modelo con
medias móviles de córners a favor y en contra de los últimos 5, separando la
serie de local y la de visitante, más remates como medida de ritmo. Split
temporal, sin fuga. **20 competiciones, 8.889 partidos de juicio:**

| modelo | MAE |
|---|---|
| media de la competición | **2,6996** |
| fórmula actual | 3,0749 |
| fórmula recalibrando la base por liga | 3,0609 |
| córners y remates reales (ridge) | 2,6942 |
| gradient boosting | 2,7624 |

Dos lecturas que cierran el asunto:

- **La constante nunca fue el problema.** Recalibrar el nivel recupera 0,014 de
  los 0,375 que la fórmula pierde. El 96 % del daño lo hace la parte variable.
- **Con datos reales tampoco hay señal.** La mejora es de 0,005 córners sobre
  una desviación típica de 3,3, y el p5 del bootstrap cruza cero en 2 de 20
  ligas — lo que da el azar al hacer veinte pruebas.

Y las ligas secundarias **no son más predecibles**: +0,0049 contra +0,0062 de
las principales.

### 10.3 Qué hace hoy el sistema

El total de córners es **la media observada de la competición**, en las 20 que
publican córners de verdad. En las otras 55, la media de las comparables (9,613;
rango observado 8,81-10,54), declarada como suposición. Antes esas competiciones
recibían la fórmula, que en Liga MX daba 13,4 córners y un «Más de 9.5: 85,9 %».

### 10.4 Por qué el EV sigue bloqueado

Dos motivos, y ninguno se arregla afinando la fórmula:

1. **El modelo no discrimina.** Predice la media de la competición para todos
   sus partidos. Contra una casa que mueve su línea, el EV que sale mide que el
   modelo no distingue, no que haya valor.
2. **No existe histórico de LÍNEAS de córners.** football-data no las publica y
   el de The Odds API es de pago (§9). Sin líneas no hay apuesta que liquidar,
   así que la regla de oro del §0 —p5 positivo en el tramo de juicio— **no se
   puede ni aplicar** a este mercado.

Que el mercado de córners esté peor cotizado que el 1X2 es plausible y este
proyecto no lo ha refutado. Lo que ha medido es que **no tiene con qué
explotarlo**, y ésas son dos afirmaciones distintas.

### 10.5 Y el xG de este proyecto no es xG

Relacionado, porque es de donde salía la fórmula de córners. Las columnas
`home_xg`/`away_xg` las escribe `CorrelatedSyntheticGenerator`:

    xG = 0,776 + 0,200 · goles_reales + ruido(0,529)

Ajustando xG contra goles en los históricos guardados, los coeficientes salen
0,785/0,201/0,519 en Bundesliga, 0,785/0,200/0,498 en Argentina, 0,776/0,203 en
Liga MX y 0,775/0,208 en Brasileirão: **la calibración del generador con tres
decimales**. La posesión igual: `50 + 12·tanh(elo_diff/300) + ruido(4)`.

Por eso **no se entrena ningún modelo sobre el xG de estos ficheros** (sería
entrenar sobre los goles con ruido añadido) y **no se enseña xG ni posesión en
ninguna pantalla**. Sólo salen goles, córners, remates y tarjetas, que sí son
observados — y sólo en las competiciones donde lo son.

### 10.6 El intento serio de predecir córners, y el suelo que lo cierra

Se pidió bajar el MAE de ~2,70 a menos de 2,00 usando remates y remates a
puerta en vez del xG, y probando XGBoost o un Poisson compuesto. Se hizo, con
32 features y cuatro modelos, sobre las 20 competiciones con córners
observados: **7.890 partidos en el tramo de juicio**, split temporal, sin fuga.

Features: córners a favor y en contra en ventanas de 5 y 10, córners del bando
que toca jugar, remates totales y **remates a puerta por separado**, precisión
de remate (a puerta / totales) como proxy de presión, faltas, córners del H2H y
`elo_diff`.

| modelo | MAE |
|---|---|
| constante de la competición | **2,7067** |
| ridge, 32 features | 2,6977 |
| Poisson | 2,7085 |
| XGBoost (`count:poisson`) | 2,7293 |
| LightGBM (`poisson`) | 2,7365 |
| **oráculo que conociera la media exacta** | **2,4835** |

**Ni XGBoost, ni LightGBM, ni el Poisson baten a decir siempre la media.** Los
tres salen PEOR. El ridge mejora 0,009 córners, con percentil 5 positivo en 3
de 20 ligas — lo que produce el azar al hacer veinte pruebas.

#### El suelo, que es lo que cierra la línea

Antes de perseguir un número hay que saber si existe. El total de córners es un
conteo con razón varianza/media **1,17**: un proceso Poisson casi puro,
ligeramente sobredispersado. Con esa distribución, **un oráculo que conociera la
media exacta de cada partido cometería 2,4835 de error medio**. No por
ignorancia: por la dispersión del propio fenómeno.

    margen teórico total .....  2,7067 − 2,4835 = 0,223 córners
    lo que captura el mejor ..  0,009  (un 4 % de ese margen)

**Un MAE de 2,0 no es un modelo mejor: es un modelo imposible.** Está medio
córner por debajo de lo que puede conseguir quien lo sepa todo.

#### Los otros dos caminos, y por qué tampoco

- **Cuotas de córners de la casa como variable.** Es el mejor estimador
  disponible, pero no hay histórico de líneas de córners con el que entrenar ni
  validar (§10.4). Y aunque lo hubiera: un modelo que copia la línea de la casa
  baja su MAE porque mide al mercado, no porque lo bata. Para tener ventaja hay
  que separarse de la línea y acertar más, que es justo lo que estos números
  dicen que no se puede.
- **FotMob para posesión y ataques por banda.** La fuente existe y publica xG
  real, posesión y ocasiones claras. Hoy hay **28 partidos cacheados**. Con esa
  cobertura no se valida nada; haría falta un backfill de miles antes de poder
  siquiera plantear el experimento.

#### Qué queda en pie

El total de córners que enseña la app sigue siendo **la media observada de la
competición**, que es el mejor estimador medido. Las medias por equipo —lo que
saca y recibe cada uno— sí son suyas y se enseñan como datos. El EV de córners
sigue bloqueado, y ahora con un motivo más fuerte que antes: no es que falte
afinar el modelo, es que el margen entre la constante y la perfección son
0,22 córners y nadie ha capturado más del 4 %.

### 10.7 CORRECCIÓN a la §10.6: el MAE ocultaba la señal

La §10.6 midió el suelo del MAE (2,4835) y cerró la línea. **El suelo es
correcto y un MAE de 2,0 sigue siendo imposible, pero la conclusión de que no
había nada que capturar estaba mal razonada.** Faltaba una descomposición.

Si el total de córners de cada partido es Poisson con su propia media λᵢ, la ley
de la varianza total dice:

    Var(X) = E[λ] + Var(λ)
             ruido   SEÑAL

El ruido de Poisson fija el suelo del MAE y es irreducible. `Var(λ)` es lo que
un modelo mejor podría explicar, y se mide gratis: `Var(λ) = Var(X) − E[X]`.

Medido sobre **49.986 partidos** de las 20 competiciones:

| | |
|---|---|
| media de córners | 9,76 |
| desviación total | 3,387 |
| **desviación de λ (señal real)** | **1,288** |
| **correlación máxima alcanzable** | **0,378** |
| varianza explicable en principio | 14,7 % |

**La media condicional varía 1,29 córners entre partidos: hay señal.** Lo que
pasa es que con un ruido de desviación 3,2 encima, capturarla mueve el MAE unas
centésimas y queda sepultada. Por eso el MAE era la métrica equivocada — y para
apostar tampoco es la que importa: importa distinguir los partidos que van por
encima de la línea, y eso lo mide la correlación.

#### Dónde estamos contra ese techo

| modelo | correlación |
|---|---|
| **techo alcanzable** | **0,378** |
| ridge, 32 features del histórico | 0,0609 |
| XGBoost / LightGBM / Poisson | peores que la constante |
| multiplicativo ataque/defensa con decaimiento | 0,0634 |

El multiplicativo —la estructura de Dixon-Coles aplicada a córners, que nunca se
había probado aquí— sale mejor que la regresión y, sobre todo, **más
consistente: 16 de las 20 ligas dan correlación positiva** (con moneda justa
eso ocurre el 0,6 % de las veces). La señal es real; el tamaño, pequeño.

**Cinco estructuras distintas dan lo mismo, así que el cuello no es el modelo:
son los datos.** Queda el 83 % del margen sin capturar.

#### Lo que se sabe de las fuentes nuevas

- **FBref**: devuelve **403** a un `requests` con User-Agent de navegador. Sin
  una vía que sortee eso —y sortearla no es una decisión técnica— no hay
  pases progresivos, SCA ni PPDA.
- **FotMob**: accesible, y **con temporadas pasadas**: `allAvailableSeasons`
  llega a 2012/13 y la URL admite `?season=2024/2025`. Publica lo que
  football-data no tiene: posesión real, xG real, ocasiones claras y tiros
  bloqueados. Coste medido: **1,69 s por partido**, o sea 11 minutos por
  liga-temporada y ~18 horas para 20 ligas × 5 años.

### 10.8 Lo que SÍ mejoró: las colas, no la media

De las cuatro vías propuestas, tres se cerraron con medición y una funcionó.

| vía | resultado |
|---|---|
| FBref (soccerdata) | **403** a un `requests` con User-Agent de navegador. Inaccesible. |
| Backfill de FotMob | Probado con **1.520 partidos reales** (4 temporadas de Premier, xG real, posesión, ocasiones claras): ganancia de correlación **−0,005** sobre n=663. Con ese tamaño el error estándar es 0,039, así que hay potencia para decir que no aporta. |
| Cross-market | Sigue sin haber histórico de líneas de córners con el que entrenar ni validar. |
| **Poisson compuesto** | **Funcionó** — ver abajo. |

#### La sobredispersión sí se podía aprovechar

Los córners llegan en racimo: un ataque genera el córner, el saque se desvía o
rebota en la barrera, y sale otro. Eso infla la varianza sin mover la media, y
la binomial negativa lo modela; Poisson no.

    ajuste de la distribución (Premier, n=2.666)
        Poisson ............  error total 0,1021
        binomial negativa ..  error total 0,0787

Y donde de verdad importa —las líneas que cotiza la casa—, comparando la
probabilidad calculada contra la **frecuencia real** en 24 líneas de 6
competiciones:

    Poisson ..............  error medio 0,0093
    binomial negativa ....  error medio 0,0043     ← la mitad

Implementado: `rendimiento_equipos.dispersion_corners_liga` mide la razón
varianza/media de cada competición y `prob_mas_de` la usa. Donde no hay córners
observados devuelve `None` y el cálculo es exactamente el de antes.

**Qué mejora y qué no.** No mejora la predicción de la media —eso sigue tan
difícil como dice el §10.7— sino la conversión de esa media en probabilidades.
Es una mejora de calibración, no de acierto.

#### El techo de otros mercados, para orientar el esfuerzo

Aplicando `sd(λ)/sd(X)` a los demás conteos de las mismas competiciones:

| mercado | media | sd(λ) | correlación máxima |
|---|---|---|---|
| córners | 9,84 | 1,31 | 0,386 |
| remates a puerta | 8,44 | 1,12 | 0,357 |
| tarjetas | 4,20 | 0,41 | 0,193 |
| **goles** | 2,65 | **0,04** | **0,025** |

**El total de goles es casi Poisson puro.** Su techo de correlación es 0,025:
predecir si un partido tendrá más o menos de 2,5 goles es, en el límite, casi
imposible — y eso encaja con lo que el proyecto ya sabía por otra vía (el modelo
no bate al mercado en ninguna liga). Sirve además de control: si este método
hubiera dicho que los goles son muy predecibles, habría que desconfiar de él.

#### Una salvedad honesta sobre el techo

`sd(λ) = Var(X) − E[X]` supone que la distribución condicional de cada partido
es **exactamente** Poisson. Si parte de la sobredispersión es agrupamiento
intrínseco —y el ajuste de la binomial negativa dice que la hay—, entonces ese
0,386 es un límite SUPERIOR y el techo real es más bajo. Eso explicaría por qué
seis enfoques distintos, incluyendo datos avanzados reales, se quedan todos
en 0,06.

### 10.9 Córners por equipo: el estimador que ganó

Para el TOTAL, la mejor media es la de la competición (§10.8). Para cada
EQUIPO no, y la diferencia es grande. Medido sobre **30.454 equipos-partido** en
6 competiciones, con el error de calibración contra la frecuencia real en las
líneas que cotiza la casa (3,5 / 4,5 / 5,5 / 6,5):

| estimador de la media | distribución | error |
|---|---|---|
| **ataque + defensa del rival** | **binomial negativa** | **0,0056** |
| media móvil de 5 | Poisson | 0,0093 |
| media de la competición | binomial negativa | 0,0101 |
| media del equipo | binomial negativa | 0,0121 |
| media móvil de 5 | binomial negativa | 0,0149 |
| ataque + defensa | Poisson | 0,0237 |
| media de la competición | Poisson | 0,0369 |

**Seis veces mejor que la referencia**, y hacen falta las dos mitades: cambiar
sólo la media o sólo la distribución se queda a medio camino.

Dos cosas que no se veían de antemano:

- **La dispersión de UN EQUIPO es 1,58, no la del total (1,16).** El racimo —un
  córner que genera otro— ocurre dentro del ataque del mismo equipo; al sumar
  los dos, las rachas de uno rellenan los huecos del otro y la sobredispersión
  se diluye. Usar la del total para las líneas por equipo se quedaría corto
  justo en las colas.
- **La media móvil de 5 es PEOR que la ventana larga**, y con binomial negativa
  peor todavía (0,0149). Cinco partidos son una muestra de cinco: su propio
  ruido de Poisson supera a la señal que se busca, y la binomial negativa lo
  amplifica al tratar ese ruido como dispersión real.

#### El bug que delató la simetría

La primera implementación daba **las dos lambdas idénticas** en todos los
partidos (6,10 y 6,10 en Man City-Arsenal, 5,50 y 5,50 en Liverpool-Everton).
La causa: «lo que saca el equipo en su bando» y «lo que el rival recibe en el
bando contrario» son la MISMA columna del histórico —lo que cambia es por quién
se filtra— y estaban puestas al revés. Con las columnas bien, ese partido da
5,60 y 4,40.

Que dos números que deberían diferir salgan iguales es la clase de señal que
conviene mirar antes de integrar nada.

#### El total y la suma por equipo no cuadran, y se dice

Son dos estimadores distintos y cada uno es el mejor medido para su mercado
(0,0043 el total, 0,0056 por equipo). Forzar que sumaran exacto obligaría a
empeorar uno para que cuadrase con el otro. La ficha lo declara en
`corners_nota` en vez de disimularlo.

#### El EV de córners

Se calcula y se muestra, marcado. El motivo cambió: ya no es que el modelo
prediga la media de la competición —ahora la probabilidad está calibrada a
0,4-0,6 puntos de la frecuencia real— sino que **sigue sin haber histórico de
LÍNEAS de córners** con el que comprobar si ese EV gana dinero. Es una señal
inmediata, no una apuesta validada, y así se etiqueta.

## 11. Tarjetas: la misma metodología, y por qué aquí sí cambia el total

Los córners cerraron en la v159 con dos estimadores calibrados y un techo
medido. Esta sección aplica lo mismo a tarjetas, y el resultado NO es el mismo
en tres puntos que conviene tener presentes antes de tocar nada.

### 11.1 Qué cuenta una «tarjeta»: amarillas MÁS rojas

La primera versión contó sólo amarillas, que es lo que football-data publica
con más limpieza y lo que ya leía `forma()`. Al cruzarla contra las líneas
REALES de la casa —36 partidos capturados por `snapshots_tarjetas.py`, 14 con
nombres que casan con el histórico— apareció un sesgo sistemático:

| línea de la casa | P(más) del modelo | P(más) del mercado | diferencia |
|---|---|---|---|
| 3,5 | 0,565 | 0,622 | −0,056 |
| 4,5 | 0,406 | 0,489 | −0,083 |
| 5,5 | 0,232 | 0,368 | −0,136 |
| 6,5 | 0,134 | 0,242 | −0,108 |

El modelo veía **menos** tarjetas que la casa, y **cada vez menos según subía
la línea**. Eso no es desacuerdo con el mercado: es la firma de estar contando
una magnitud más pequeña. Un desacuerdo real sería ruidoso y sin pendiente.

Las rojas valen **0,25 tarjetas por partido** de media (0,13 en la Premier,
0,27 en Portugal), o sea casi exactamente los 0,27 que separaban el centro del
modelo (4,16) del centro de la casa (4,43). Sumándolas, el centro pasó a 4,36
y el sesgo medio de −0,080 a −0,049.

**Y no es un apaño para parecerse al mercado.** Contra el resultado REAL, que
es contra lo que se calibra en este proyecto, contar rojas mejora todo:

| | sólo amarillas | amarillas + rojas |
|---|---|---|
| calibración por equipo | 0,0141 | **0,0117** |
| correlación por equipo | 0,146 | **0,150** |
| calibración del total | 0,0121 | **0,0119** |
| correlación del total | 0,107 | **0,110** |

Queda una pregunta abierta que estos datos no cierran: **si la casa cuenta una
segunda amarilla como una tarjeta o como dos**. football-data suma la roja de
la doble amarilla en `home_red` y las dos amarillas en `home_yellow`, así que
aquí cuenta como tres. El residuo de −0,10 que sigue habiendo en la línea 5,5
puede ser eso, o puede ser ruido de n=14. `tarjetas_snapshots.csv` lo cerrará
cuando haya líneas liquidadas contra resultados; hasta entonces se dice.

### 11.2 El estimador: el mismo que ganó en córners

Medido sobre **52.648 equipos-partido** y **26.324 partidos** de juicio en 20
competiciones, split temporal y medias móviles desplazadas un partido:

**Por equipo** (líneas 0,5 / 1,5 / 2,5 / 3,5)

| estimador | error de calibración | correlación |
|---|---|---|
| **ataque + defensa del rival, ventana 10** | **0,0117** | **0,150** |
| sólo lo que recibe el equipo, ventana 10 | 0,0155 | 0,112 |
| media móvil de 5 del equipo | 0,0227 | 0,098 |
| media de la competición en ese bando | 0,0312 | 0,101 |

**Total del partido** (líneas 2,5 / 3,5 / 4,5 / 5,5)

| estimador | distribución | error | correlación |
|---|---|---|---|
| **ataque + defensa del rival** | **binomial negativa** | **0,0119** | **0,110** |
| ataque + defensa del rival | Poisson | 0,0134 | 0,110 |
| media de la competición | binomial negativa | 0,0488 | 0,003 |

### 11.3 Las dos diferencias con córners

**1. En el TOTAL, aquí sí gana el estimador del partido.** En córners la media
de la competición era imbatible: su parte variable tenía correlación −0,0012
con el total real (§10.7), y por eso `corners_tarjeta` la usa para el total. En
tarjetas la media de la liga tiene correlación **0,003** —o sea ninguna— y el
estimador ataque/defensa llega a 0,110 y **cuadruplica su calibración**. La
razón: la indisciplina es un rasgo estable del equipo; sacar córners depende
del rival tanto como de uno mismo.

**2. La binomial negativa aporta, pero por las ROJAS.** Contando sólo amarillas
la razón varianza/media salía 1,0 o por debajo en **19 de las 20**
competiciones: un conteo sin sobredispersión, donde la binomial negativa
degenera en Poisson y no cambia nada. Sumando las rojas sube a 1,35 en Turquía,
1,37 en Portugal, 1,28 en la Eredivisie — una roja es un suceso raro que
arrastra más tarjetas detrás, y eso engorda la cola justo donde están las
líneas altas. Con eso, binneg gana a Poisson en el total (0,0119 contra
0,0134).

Y al revés que en córners: **la dispersión por equipo es MENOR que la del
total** (1,12 contra 1,35 en Turquía), cuando en córners era mayor (1,58
contra 1,16). Tiene explicación: el racimo de córners ocurre dentro del ataque
de un equipo, y el de tarjetas ocurre ENTRE los dos —una entrada dura trae la
represalia—, así que sumar los bandos concentra el efecto en vez de diluirlo.

### 11.4 El árbitro: sí es señal, pero sólo encogido

#### ESPN no sirve, y se comprobó antes de buscar otra fuente

ESPN publica el árbitro en `summary` → `gameInfo.officials`. Medido el
2026-08-22 sobre 139 eventos de las 20 competiciones con tarjetas observadas,
en una ventana de ±6 días:

| estado | eventos | con árbitro | |
|---|---|---|---|
| ya jugados (`post`) | 98 | 88 | 89,8 % |
| por jugar (`pre`) | 41 | **0** | **0,0 %** |

Cero de cuarenta y uno no es cobertura floja: **el campo no se rellena hasta que
el partido empieza**. Sirve para reconstruir el histórico de las 13
competiciones cuya columna `referee` viene vacía; no sirve para apostar.

#### FotMob sí, y con el perfil puesto

    /api/data/matches?date=YYYYMMDD   → índice del día (405 partidos, 1 petición)
    /api/data/matchDetails?matchId=N  → content.matchFacts.infoBox.Referee

Verificado sobre partidos con `started: False`. El bloque `Referee` trae nombre,
partidos arbitrados, amarillas por partido **y la media de su competición** —
que es lo que hace esto sólido: el ajuste es una RAZÓN, adimensional, así que
da igual que FotMob cuente con otro criterio o con otra ventana temporal.

#### Cuánto aporta

No se dio por supuesto. Se midió con las **7 competiciones cuyo histórico trae
quién pitó** (las inglesas y escocesas de football-data; las otras 13 tienen la
columna vacía). Walk-forward causal, n = 11.375 partidos de juicio:

| | Brier | correlación |
|---|---|---|
| sin árbitro | 0,20500 | 0,103 |
| **con árbitro, K = 60** | **0,20344** | **0,133** |

Y mejora en **las seis** competiciones con muestra suficiente, ninguna en
contra: premier +0,00011 · championship +0,00295 · league one +0,00141 ·
league two +0,00165 · national +0,00194 · sco premiership +0,00146.

La ganancia de Brier es pequeña —0,0016— y conviene decirlo así. La de
correlación no lo es: 0,103 → 0,133 es casi un tercio más de señal, y el techo
medido para tarjetas es 0,193 (§10.7), así que se come una parte apreciable de
lo que quedaba.

#### Por qué encoger, y por qué tanto

La razón cruda del árbitro es ruido casi puro cuando lleva pocos partidos, y
aplicarla entera **empeora** la calibración aunque mejore la correlación:

| K | error de calibración | correlación |
|---|---|---|
| 0 | 0,0371 | 0,140 |
| 10 | 0,0214 | 0,150 |
| 20 | 0,0161 | 0,147 |
| 40 | 0,0131 | 0,141 |
| **60** | **0,0120** | **0,133** |
| 200 | 0,0114 | 0,125 |

Con K=60 un árbitro de 45 partidos aporta 45/(45+60) = 43 % de su desviación
observada. Subir más el K sigue mejorando la calibración pero se lleva la
correlación por delante; 60 es donde el Brier toca fondo.

### 11.5 Qué hace hoy el sistema

- `rendimiento_equipos.tarjetas_equipo` devuelve las dos lambdas y el total,
  con las dos dispersiones medidas de la competición.
- `arbitro_partido` precalcula el árbitro designado del día en
  `arbitros_dia.json` (lo corre el bot, **antes** del guardado temprano: un
  designado que no se guarda hoy no se recupera mañana, porque FotMob lo
  sustituye por el que efectivamente pitó).
- La tarjeta del Modo Modelo pinta total, local y visitante con su apuesta más
  probable y su probabilidad, más la línea del árbitro. **En ámbar.**
- `snapshots_tarjetas.py` acumula las líneas de la casa.

Cobertura medida el 2026-08-22: 48 fixtures, **48 emparejados** con FotMob y
**35 con árbitro publicado**. Los 13 restantes son partidos a dos días vista
sin designar todavía; ésos salen sin ajuste y la tarjeta lo dice.

### 11.6 Por qué sigue en ÁMBAR

Verde en esta aplicación significa «canal con percentil 5 positivo medido». La
probabilidad de tarjetas está calibrada contra la frecuencia real, pero **no
hay histórico de líneas** con el que saber si su EV gana dinero — exactamente
la misma situación que los córners en la v159. `tarjetas_snapshots.csv` lo
empieza a acumular hoy: 2.010 filas de 48 partidos en la primera captura.
Cuando haya volumen para liquidar, se mide el p5 y entonces —y sólo entonces—
podrá dejar de estar marcado.

### 11.7 El filtro de familias, y las tres pasadas que costó

La casa cotiza **4.105 familias distintas** en tres partidos, y las de JUGADOR
entran por el apellido. Sin filtros suficientes pasaban 358 donde debían pasar
40:

1. **Paréntesis fuera antes de buscar la palabra** — «Primer goleador y
   marcador exacto (Diego Alexander Gomez **Amarilla**)».
2. **Código de equipo entre paréntesis = jugador** — el apellido no siempre va
   entre paréntesis: «Tackleadas - Diego Alexander Gomez Amarilla **(BHA)**».
3. **Límite de palabra, y palabras débiles con forma de mercado** —
   «Multigoleadores Sergi **Card**ona Bermadez» entraba porque «card» está
   dentro de «Cardona».
4. **Nada que diga «jugador»** — «Jugador recibe una tarjeta» sí es de
   tarjetas, pero no hay histórico por jugador con el que liquidarla nunca.

La lección es la de siempre en este proyecto: un filtro no se valida con los
casos que a uno se le ocurren, se valida pidiendo el tablero entero y mirando
qué pasa y qué no.

## 12. El boxscore de ESPN: córners y tarjetas reales en todas las competiciones

Las §10 y §11 cerraron córners y tarjetas **en 20 competiciones**, las de
formato `main` de football-data. En las otras 55 esas columnas las escribía
`CorrelatedSyntheticGenerator` y por eso no se enseñaban. Esta sección cuenta
cómo dejaron de faltar, y la respuesta es incómoda: los datos llevaban años
delante.

### 12.1 Estaba en una clave del `summary` que nadie había abierto

El proyecto usa ESPN desde la v35 para fixtures, resultados y cuotas. Su
endpoint `summary` devuelve, entre otras cosas, una clave `boxscore` que
ninguna versión había mirado. Dentro hay **28 estadísticas por equipo y
partido**:

    wonCorners · yellowCards · redCards · foulsCommitted · possessionPct
    totalShots · shotsOnTarget · offsides · saves · totalPasses · passPct
    accurateCrosses · accurateLongBalls · interceptions · totalTackles
    effectiveClearance · blockedShots · penaltyKickGoals …

Sondeadas 34 competiciones el 2026-08-22, **23 las traían** — entre ellas Liga
MX, Argentina, Brasil, MLS, Colombia, Chile, Perú, Japón, China, Suecia,
Noruega, Dinamarca, Rusia, Sudáfrica, USL y Austria. Las 11 restantes no tenían
partidos jugados en la ventana de prueba o devolvieron el boxscore vacío.

### 12.2 No es otro relleno, y se comprobó antes de construir nada

La lección de la v152 —el xG del proyecto resultó ser una función afín de los
goles— obliga a desconfiar de cualquier columna nueva. Así que antes de tocar
producción se cruzaron **216 partidos de 6 competiciones grandes**, los mismos
en ESPN y en football-data:

| variable | n | idénticos | media ESPN | media FD | correlación |
|---|---|---|---|---|---|
| córners local | 216 | 93,1 % | 5,76 | 5,74 | **0,985** |
| córners visitante | 216 | 96,3 % | 4,34 | 4,33 | **0,981** |
| amarillas local | 216 | 95,4 % | 1,71 | 1,76 | 0,955 |
| amarillas visitante | 216 | 94,4 % | 1,72 | 1,78 | 0,957 |
| rojas local | 216 | 100,0 % | 0,07 | 0,07 | 1,000 |
| remates local | 216 | 95,4 % | 14,80 | 14,73 | 0,988 |

Los desacuerdos son de ±1 —criterio de conteo— y dos de ellos resultaron ser un
emparejado mal hecho por el propio script de comprobación. Con correlaciones de
0,98 y medias que coinciden en la segunda cifra, esto es **fuente observada**.

### 12.3 Un boxscore a ceros no es un partido sin córners

El fallo más caro de esta tanda, y el que más se parece a los de siempre.

En el **7,0 %** de los partidos de la Liga MX, ESPN devolvía el boxscore con
todo a cero a la vez: posesión 0-0, faltas 0, córners 0, remates 0. Eso no es un
partido raro, es un partido sin datos publicado igual. Colados como buenos:

| | con las filas vacías | sin ellas |
|---|---|---|
| razón varianza/media, córners por equipo | 2,04 | **1,63** |
| media de córners del local | 5,01 | **5,38** |
| error de calibración por equipo | 0,0288 | **0,0111** |

La misma competición, el mismo día, sin tocar nada más. **El error de
calibración se dividió por 2,6 sólo tirando el 7 % de las filas.**

El detector es la posesión: la suma de las dos siempre ronda 100 en un partido
de verdad —1.777 de 1.911 caen entre 95 y 105— y vale exactamente 0 cuando el
boxscore viene vacío. Se descarta la fila entera y no sólo la posesión, porque
lo que falta es el boxscore completo.

### 12.4 Dónde viven, y por qué no en el histórico

`descargar_liga` **reconstruye** el histórico entero desde su fuente en cada
`--build`. Escribir los córners reales en `historico_liga_mx.csv` los habría
borrado la noche siguiente.

Así que viven en `stats_espn/<liga>.csv.gz` y se **inyectan** durante la
descarga, justo antes del generador sintético. Ese orden es todo el mecanismo:
el generador ya prometía —y cumplía— que «sólo rellena valores faltantes», así
que lo real gana y lo sintético se queda para los huecos.

El efecto secundario es el que se buscaba: `stats_disponibles` decide si una
columna es sintética **reproduciéndola** con el generador, así que en cuanto
llegan los valores de ESPN la reproducción falla y la columna pasa a contar como
observada. No hubo que tocar esa función ni mantener ninguna lista.

### 12.5 Dos arreglos que el cambio obligó a hacer

**La muestra de síntesis sale ahora de la COLA.** `_columnas_sinteticas`
probaba sobre `d.head(400)`, o sea los partidos más antiguos. La cobertura de
ESPN arranca en 2021 y varios históricos empiezan en 2018, así que la cabecera
seguiría siendo sintética para siempre y la competición nunca se declararía
observada. La cola es además lo correcto por lo que se usa: los estimadores
miran `.tail(10)` de cada equipo. Comprobado que el generador reproduce igual
sobre un trozo (1,000 de coincidencia en la cola de la Liga MX), porque su ruido
es un hash por `MATCH_ID` y no depende de qué filas se le pasen.

**Una columna mezclada no se puede promediar entera.** Con ESPN desde 2021 y
relleno sintético antes, media columna es de cada tipo. `inyectar` marca cada
fila que rellena con `stats_origen`, y las medias y dispersiones filtran por esa
marca (`_solo_reales`). En las 20 competiciones de football-data la columna no
existe y se usa el histórico entero, que es lo correcto ahí.

### 12.6 Lo que queda estimado, y cuánto vale

Para las competiciones que ESPN no cubre, `stats_estimadas` da el nivel
derivado de sus goles. Validado **dejando una liga fuera** —se ajusta con 19 y
se predice la vigésima como si no tuviera datos, que es la situación real:

| CÓRNERS por equipo | error | corr |
|---|---|---|
| con datos reales (techo) | 0,0076 | 0,257 |
| **media de liga predicha de sus goles** | **0,0247** | **0,160** |
| media global de las otras ligas | 0,0264 | 0,160 |
| predicha × ataque, normalizada | 0,0326 | 0,234 |
| predicha × ataque, sin normalizar | 0,0410 | 0,250 |

| TARJETAS por equipo | error | corr |
|---|---|---|
| con datos reales (techo) | 0,0123 | 0,150 |
| **media de liga predicha de sus goles** | **0,0539** | **0,100** |
| media global de las otras ligas | 0,0549 | 0,100 |
| predicha × ataque | 0,0556 | **−0,080** |

**No se modula por el ataque aunque suba la correlación.** En córners la lleva
de 0,160 a 0,234 —casi el techo de 0,257— pero empeora la calibración de 0,0247
a 0,0326, y aquí manda la calibración (§10.7-10.8). En tarjetas la correlación
sale **negativa**: un equipo que ataca más se lleva MENOS tarjetas, así que el
modulador empuja al revés.

Lo que sí aportan los goles es el NIVEL de la competición: correlación **+0,428**
con la media de córners y **−0,412** con la de tarjetas, entre las 20 ligas con
datos. Y el rango entre ligas es grande (córners de 8,70 a 10,59; tarjetas de
3,17 a 5,44), así que acertar el nivel importa.

**Sin un solo córner observado de una competición no hay forma de saber qué
equipo saca más.** Lo que se enseña es el nivel de la liga repartido por bando,
igual para todos sus partidos. Por eso va marcado, y por eso las tarjetas
estimadas —0,0539, por encima del umbral de 0,05 que se fijó— llevan un aviso
más fuerte que los córners estimados.

### 12.7 Coste

**0,05 s por partido con 8 hilos**, 0,18 s con uno. Dos órdenes de magnitud más
barato que FotMob (~1,7 s por partido), que era la otra vía. El bot lo corre a
diario con ventana de 10 días, antes del reentrenamiento para que lo descargado
entre en el `--build` del mismo día.
