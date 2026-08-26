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

---

## 13. Remates: el tercer mercado físico, y el primero donde la métrica de siempre se equivocó

### 13.0 Qué hay y qué no

Dos mercados nuevos —**remates totales** y **remates a puerta**— por equipo y del
partido, más un bloque **por jugador** con la alineación probable cuando la hay.

Están en ámbar, como córners y tarjetas, y por lo mismo: son probabilidades bien
calibradas, **no** una ventaja de precio demostrada. No hay histórico de líneas
de remates con el que calcular un percentil 5, así que la regla de oro del §0 ni
siquiera se puede aplicar todavía. `snapshots_remates.py` lo empieza a
construir hoy, igual que hicieron `snapshots_corners.py` en la v159 y
`snapshots_tarjetas.py` en la v160 para sus mercados.

### 13.1 El estimador: el mismo que ganó en córners y en tarjetas

Sobre **41.000 equipos-partido de 17 competiciones** con remates observados
(`_v163_remates_estimadores.py`), cuatro estimadores por dos distribuciones:

| remates TOTALES por equipo | marginal | Brier | ECE |
|---|---|---|---|
| ataque/defensa v10, binomial negativa | 0,01315 | **0,19501** | **0,03132** |
| ataque/defensa v10, Poisson | 0,03323 | 0,19602 | 0,04389 |
| media del equipo, binneg | 0,02067 | 0,20441 | 0,03310 |
| media de la competición, binneg | 0,02077 | 0,21282 | 0,03200 |
| media móvil de 5, Poisson | **0,01476** | 0,22477 | 0,11418 |

| remates A PUERTA por equipo | marginal | Brier | ECE |
|---|---|---|---|
| ataque/defensa v10, binneg | 0,01287 | **0,20154** | **0,02734** |
| ataque/defensa v10, Poisson | 0,01281 | 0,20169 | 0,02907 |
| media móvil de 5, Poisson | **0,00706** | 0,22218 | 0,09824 |

Gana lo mismo que en los otros dos mercados: **(lo que TIRA él en su bando + lo
que CONCEDE el rival en el contrario) / 2, ventana 10, binomial negativa**. Tres
mercados independientes y el mismo ganador: ya no es una casualidad de córners.

### 13.2 EL HALLAZGO QUE HAY QUE LEER ANTES DE MEDIR NADA MÁS

**El error marginal, que es la métrica con la que se cerraron córners (§10) y
tarjetas (§11), aquí habría elegido el peor estimador de la tabla.**

La media móvil de 5 con Poisson gana esa columna en los DOS objetivos —0,01476 y
0,00706, los mejores números de todo el experimento— y es la última por Brier y
por ECE, con la calibración por deciles **cuatro veces peor** que la del ganador.

El motivo: `|media de la probabilidad dicha − frecuencia real|` mide que el nivel
no esté sesgado y **no mide resolución**. La media de la competición dice lo
mismo en todos los partidos y aun así puntúa 0,0208. Aquí además se juntan dos
sesgos que se cancelan: la móvil de 5 es ruidosa, lo que engorda las colas, y
Poisson las adelgaza justo lo bastante para que el promedio cuadre.

Por eso desde la v163 se miran **tres** números y se elige por ECE:

* `marginal` — que el nivel no esté sesgado (la de siempre);
* `brier` — que la probabilidad se mueva partido a partido en la dirección buena;
* `ece` — calibración por deciles, que caza los sesgos que se cancelan.

**Consecuencia para quien vuelva a córners o tarjetas:** sus decisiones se
tomaron con la primera columna sola. No están desmentidas —el estimador ganador
es el mismo en los tres mercados— pero tampoco están confirmadas por las otras
dos. Antes de mover algo allí, medir las tres.

### 13.3 El total del partido: se suma, como en tarjetas y al revés que en córners

Medido en `_v163_remates_total.py` sobre 20.000 partidos:

| total del partido (remates) | marginal | Brier | ECE |
|---|---|---|---|
| suma de las dos lambdas | **0,01511** | **0,21155** | **0,03840** |
| media de la competición | 0,03598 | 0,21724 | 0,04983 |

La correlación de la suma con el total real va de 0,10 a 0,27 según la
competición: señal de verdad. En córners era **−0,0012** y por eso allí se usa la
media de la liga (§10.7). Tres mercados, tres respuestas distintas a la misma
pregunta, cada una medida.

### 13.4 La sobredispersión es mucho mayor aquí

Razón varianza/media **por equipo**: 2,09 en remates totales y 1,36 a puerta,
contra 1,58 de córners y 1,12-1,35 de tarjetas. Con 2,09, usar Poisson multiplica
por 2,5 el error marginal. La del **total** del partido es bastante más baja
(1,35 y 1,13): el racimo ocurre dentro del ataque de un equipo y sumar los dos
bandos lo diluye, igual que en córners y al revés que en tarjetas.

### 13.5 La trampa de las dos épocas

El histórico de la Premier arranca en 2010 y **la media de remates a puerta se
parte por la mitad entre 2013 y 2014** (13,4 y 11,3 antes; 8,6 y 8,7 después):
la fuente cambió qué cuenta. Promediando las dos épocas juntas, la razón
varianza/media del total sale **1,62** cuando dentro de cada año va entre 0,90 y
1,22 — o sea que la «sobredispersión» medida sería la distancia entre dos
definiciones, y la binomial negativa engordaría las colas por un motivo
inventado.

Por eso el nivel y la dispersión se miden sobre las **últimas 6 temporadas**
(`rendimiento_equipos._recientes`). Seis y no cuatro porque con cuatro un equipo
recién ascendido se queda sin muestra y el partido entero cae al estimador de
liga; de las ocho competiciones comprobadas sólo la Premier tiene el salto, y a
seis temporadas sigue dentro de su época actual.

`media_corners_liga` ya recortaba a 3 temporadas por esta razón, pero
`dispersion_corners_liga` y `dispersion_corners_equipo` **no lo hacen**. No se
han tocado —su calibración está medida y cerrada con ese comportamiento— pero
queda anotado por si alguien las revisa.

### 13.6 Sin datos observados: la estimación, y cuánto vale

Validación **dejando una liga fuera** sobre 18 competiciones
(`_v163_remates_estimados.py`):

| remates TOTALES por equipo | marginal | ECE | corr |
|---|---|---|---|
| con datos reales (el techo) | 0,0131 | 0,0321 | 0,431 |
| nivel de liga predicho de sus goles | **0,0281** | 0,0302 | 0,235 |
| media global de las otras ligas | 0,0401 | 0,0405 | 0,235 |
| predicha × ataque, normalizada | 0,0481 | 0,1516 | 0,258 |

| remates A PUERTA por equipo | marginal | ECE | corr |
|---|---|---|---|
| con datos reales (el techo) | 0,0128 | 0,0279 | 0,334 |
| nivel de liga predicho de sus goles | **0,0168** | 0,0211 | 0,171 |
| media global de las otras ligas | 0,0376 | 0,0390 | 0,171 |
| predicha × ataque, normalizada | 0,0376 | 0,1101 | 0,239 |

Los dos por debajo del umbral de 0,05, así que llevan el aviso suave —no el
fuerte de las tarjetas estimadas (0,0539)—. Y la modulación por ataque vuelve a
perder, aquí por más distancia que en ningún otro mercado: multiplica el ECE
por cinco.

**Los goles predicen el nivel de remates de una liga mejor que el de nada más:**
correlación **+0,666** en totales y **+0,878** a puerta, contra +0,428 de córners
y −0,412 de tarjetas. Tiene sentido: el remate es el paso inmediatamente anterior
al gol y los otros dos están dos pasos más lejos.

### 13.7 Por jugador: encoger o no enseñarlo

Sobre **6.688 titulares-partido** de Premier, LaLiga y Liga MX bajados de ESPN
(`_v163_remates_jugador.py`), prediciendo P(≥1 remate) con información previa:

| estimador | marginal | Brier | ECE | corr |
|---|---|---|---|---|
| **encogido K=6** | 0,02030 | **0,18746** | **0,02870** | **0,537** |
| su media de las últimas 10 | 0,00850 | 0,19268 | 0,05606 | 0,521 |
| la media de su posición | 0,02760 | 0,19903 | 0,03571 | 0,471 |

y en P(≥1 a puerta) gana **K=12** (Brier 0,13992, ECE 0,02449, corr 0,420).

La media de un jugador sale de 4-10 apariciones: con λ≈0,78 eso son ±0,28 de
desviación típica, un tercio de ruido puro. Encogerla hacia la media de su
posición baja el ECE a la mitad **y encima sube la correlación**. El evento más
raro necesita encoger más, que es lo que dice la teoría.

**Poisson, no binomial negativa — al revés que en el equipo.** La dispersión que
se mide juntando a todos los jugadores incluye la diferencia ENTRE ellos (un
delantero no es un lateral), y ésa ya está dentro de la λ de cada uno. Volver a
meterla en la distribución la cuenta dos veces.

**El previo posicional va en CUOTA del total del equipo**, no en remates
absolutos: así es adimensional y una sola tabla vale para las 62 competiciones,
sin tener que descargar la estadística por jugador de cada una. La dispersión
relativa de la cuota entre las tres ligas medidas es 0,077 en totales, y calibra
igual que el techo (Brier 0,18798 contra 0,18746). Además engancha el jugador al
modelo de equipo: si el rival concede mucho, sube el equipo y suben sus
jugadores.

### 13.8 LA FUGA QUE CAMBIÓ EL RESULTADO, Y CÓMO SE CAZÓ

La primera medición dijo que **la media de la posición ganaba a todo**, incluido
el historial del propio jugador. Era falso.

ESPN no pone la posición real a quien sale del banquillo: le pone literalmente
`SUB` (4.580 de 10.390 filas en la Premier). Así que «la media de su posición»,
calculada con la posición de ESE partido, estaba diciendo en realidad **«este
jugador fue suplente»** — que es justo lo que no se sabe antes del partido. Con
esa información de contrabando, la referencia posicional ganaba.

Se arregló tomando la posición de la MODA de sus titularidades anteriores y
evaluando sólo a los titulares. Con eso, el orden se invirtió y el encogimiento
pasó a ganar.

### 13.9 La alineación: ESPN no sirve, FotMob sí

Medido sobre 104 partidos de 12 competiciones (`_v163_sondeo_alineacion.py`):

    partidos TERMINADOS con once inicial ....  50 de 50   (100 %)
    partidos POR JUGAR  con once inicial ....   0 de 54   (  0 %)

incluido uno a **4,4 horas** del saque. Misma firma exacta que el árbitro en la
§11: el dato existe, pero aparece cuando ya no sirve.

Y **`goleadores_cache.json` no contiene ninguna alineación**, aunque sea fácil
creerlo: lo que guarda es el roster de temporada de ESPN —la plantilla entera con
sus totales—, que no depende del partido.

FotMob sí, y con antelación (`_v163_sondeo_fotmob_lineup.py`, 50 partidos por
jugar):

    con once publicado .........  27 de 50   (54 %)
    tipo `predicted` ...........  21   <- once probable de verdad
    tipo `lastStarting11` ......   6   <- el once del último partido
    `unavailable` o sin bloque .  23

Los tres casos se distinguen en pantalla: un once probable y el del partido
anterior no valen lo mismo.

> **Aviso para quien toque el lector.** La primera versión del sondeo devolvía
> CERO SIEMPRE porque buscaba el bloque en la ruta equivocada, y parecía que
> FotMob no publicaba nada. Lo cazó `_v163_verificar_lector_lineup.py` pasándole
> el mismo lector a partidos ya jugados, donde el once tiene que estar. **Un
> sondeo que no encuentra nada y un lector roto se parecen demasiado.** Si se
> cambia la ruta, hay que volver a pasar ese control.

La ruta buena es `content.lineup.homeTeam.starters`, con `content.lineup.
lineupType` diciendo de qué tipo es.

Se precalcula en el bot a `alineaciones_dia.json`, exactamente como el árbitro y
por el mismo motivo: la tarjeta se pinta sesenta veces por pantalla y un
`matchDetails` de FotMob tarda 1,7 s. En pantalla no se pide nada; en la ficha,
que se abre de una en una, sí.

### 13.10 Lo que NO calibra: saber quién juega

Sin alineación hay que estimar la titularidad con la frecuencia con la que el
jugador ha sido titular. Medido igual que todo lo demás:

    eng.1  n=6.928  marginal 0,0027  Brier 0,16395  ECE 0,05689
    esp.1  n=7.740  marginal 0,0056  Brier 0,17912  ECE 0,07272
    mex.1  n=7.316  marginal 0,0035  Brier 0,17264  ECE 0,06123

ECE de 0,057 a 0,073, **por encima** del umbral de 0,05 del proyecto. La parte
floja de esta sección no es cuánto remata un jugador: es si va a jugar. Por eso,
sin alineación publicada, la interfaz lo dice con todas las letras en vez de
ordenar la lista y callarse.

Y por tramos de muestra, dentro de los que sí juegan:

    apariciones 4-6   n=  813  marginal 0,02235 / 0,04298  (totales / a puerta)
    apariciones 7+    n=5.875  marginal 0,02009 / 0,00896

Por debajo de cuatro apariciones no hay ni medición —el tramo no llega a la
muestra mínima juntando tres competiciones—, así que esas filas salen marcadas
con un asterisco.

### 13.11 Dos agujeros que se encontraron por el camino

**El catálogo de equipos de ESPN se cacheaba incompleto.**
`remates_jugadores.equipos_de_liga` paraba el barrido en cuanto juntaba 16
nombres. A finales de agosto un tramo de 55 días no cubre una jornada entera: la
Serie A tenía 16 equipos (faltaban Roma, Lazio, Fiorentina y Bologna) y LaLiga 19
(faltaba Osasuna). Y no se veía, porque `resolver_equipo` devuelve `None` para un
equipo que no está y la sección salía VACÍA — indistinguible de «ESPN no cubre
esta competición». Ahora recorre la ventana entera y sólo corta cuando dos tramos
seguidos no aportan un nombre nuevo. Un catálogo vacío ya no se cachea.

**El 10,5 % de los equipos no encontraba su nombre en ESPN.**
`name_mapper.normalizar` quita los sufijos societarios pero no los prefijos, así
que «Roma» contra «AS Roma» se queda en 0,73 y no llega al umbral de 0,78. Se
resolvió con 21 alias verificados uno a uno contra el catálogo real de cada
competición (de 30 fallos a 9), añadiendo el nombre de ESPN **detrás** del que ya
hubiera: `mapear` se queda con el primero que exista en el catálogo que le pasan,
así que el emparejado contra el catálogo del proyecto no cambia ni un caso. Los 9
que quedan son equipos que han cambiado de división y no están en ESPN con esa
competición: ahí no hay alias que valga.

Arreglar el normalizador quitaría la familia entera de golpe, pero mueve TODOS
los emparejados del proyecto —cuotas, liquidación, fixtures— y eso es una
medición aparte que aquí no se ha hecho.

### 13.12 Emparejar el once con las estadísticas

Medido sobre 132 nombres de once en 12 partidos
(`_v163_emparejado_jugadores.py`):

    casados ......  88 de 132  (67 %)
    ausente ......  21 (16 %)  el jugador no está en los últimos partidos de
                              ESPN — fichaje nuevo, lesionado que vuelve
    filtrado .....  21 (16 %)  menos de 2 apariciones (es agosto)
    sin_casar ....   2 ( 2 %)  fallo real del emparejador

El 2 % es lo único que es un fallo; el resto son huecos de la fuente y decisiones
propias. Un nombre que no casa **no se fuerza**: se queda fuera, igual que hace
`stats_espn.inyectar` con un partido que no encuentra. Y un jugador de ESPN no
puede casar con dos del once, porque dos homónimos del mismo equipo colapsarían
en la misma fila y el once se quedaría en diez sin que se notara.

### 13.13 Cobertura

Con la caché de `stats_espn` (`informe_calibracion.py`):

    competiciones con remates OBSERVADOS ......  44 de 61
    competiciones con remates a puerta ........  44 de 61
    error de calibración medio, remates .......  0,0164
    error de calibración medio, a puerta ......  0,0173

Las 17 restantes salen con la estimación marcada. Ojo: eso es lo que dice la
CACHÉ. Los históricos guardados de este clon sólo tienen remates observados en 20
competiciones, porque `stats_espn.inyectar` **sólo rellena huecos** y no puede
pisar unos remates que el generador sintético ya escribió. Se arregla solo en el
próximo `--build`, que reconstruye el fichero desde cero.

### 13.14 v163.1 — cinco arreglos, y uno que no era del encargo

**El día de la lista era el de UTC.** `jugados_del_dia` recortaba con
`r['fecha']`, que es el día UTC, aunque el comentario de la propia función ya
decía «la fecha que pide la interfaz es de CDMX y ESPN publica en UTC». Las dos
mitades del razonamiento estaban escritas y no se tocaban. Efecto medido por el
usuario el 2026-08-23 a la 01:21 de México: 27 partidos del día 22 por la tarde
salían en «Partidos de hoy» con su ✅ Finalizado. Un Barcelona SC-Orense de las
18:00 del 22 en México son las 00:00 UTC del 23.

Y la otra mitad del mismo fallo, que no se veía: los partidos de la TARDE del 23
en México (02:00 UTC del 24) no habrían entrado nunca en «hoy».

Un día de CDMX abarca **dos días UTC** —de 06:00 del propio a 05:59 del
siguiente— así que se miran los dos y se recorta con `fixtures_espn.fecha_local`.
Verificado en vivo: a la 01:26, «hoy» pasa de 27 finalizados a **0**, y los 38
del día 22 quedan en su día. El invariante de `test_un_solo_reloj` no se toca:
el rango de descarga sigue anclado en UTC; lo que cambia es sólo el reparto de
cara a la pantalla, que tiene que hablar el mismo idioma que la hora que enseña
al lado.

**La regresión que trajo ese arreglo, y cómo se cerró.** Mirar dos días UTC hizo
que cualquier competición sin partidos acabados en uno de ellos cayera al camino
de red: `_JUGADOS` sólo tiene entrada para los días CON partidos, así que «no
está» y «no se jugó nada» eran indistinguibles. «Apuestas del Día» pasó de 194 s
a **388 s**. Se arregla anotando en `_BARRIDOS` el RANGO que cada competición ya
recorrió, para poder afirmar «no hay nada ese día» con la misma autoridad que
«aquí están». Vuelta a 160 s, y `jugados_del_dia` baja a 0,03 s.

**Los remates por equipo salen de la tarjeta.** A petición del usuario: «lo único
que me interesa saber es quién remata». Siguen enteros en la ficha. Había además
un motivo técnico que apunta igual: en las 17 competiciones sin datos observados
el bloque era idéntico en todos sus partidos —lo decía su propia etiqueta— así
que ocupaba seis líneas sin distinguir un partido de otro. El bloque de jugadores
pasa a enseñar las **dos** probabilidades, rematar y rematar a puerta; cuando el
roster cacheado todavía no trae `shotsOnTarget`, la de a puerta sale del previo
posicional y se dice.

**Goles en tres líneas.** 1,5 · 2,5 · 3,5, de la misma matriz de marcador. Van en
`goles_lineas` y **no** en el `board`: `apuesta_destacada` y el `prob` de los
partidos jugados buscan el máximo del board, y «más de 1,5» ronda el 75-85 % en
casi cualquier partido, así que metido ahí sería la apuesta destacada de la lista
entera.

**El aviso de «sin modelo» decía qué hacer, y estaba mal.** Mandaba siempre
«revisa que su modelo cargue y que su catálogo de nombres esté al día». Sobre la
Champions las dos cosas estaban bien: en agosto son rondas previas y su histórico
—1.174 partidos, 174 equipos— cubre la fase de grupos, así que el LASK o el
Hapoel Be'er Sheva no han jugado nunca en ella. Ahora agrupa por
`motivo_sin_modelo` y distingue tres causas: motor caído (avería), nombre sin
alias (arreglable) y equipo sin historia en esa competición (normal, y lo dice).

### 13.15 LA CONTENCIÓN EMPAREJABA CLUBES DISTINTOS

Buscando lo anterior apareció algo peor que un hueco:

    name_mapper.mapear('Viking FK', catalogo_champions)  ->  'Vikingur Reykjavik'

El Viking FK es de Stavanger y el Víkingur Reykjavík de Islandia. **El emparejado
no fallaba: acertaba con confianza**, el modelo predecía el partido con la fuerza
del equipo equivocado y publicaba una probabilidad de aspecto normal. Un hueco se
ve; esto no.

`normalizar` deja «Viking FK» en «viking», y la regla de contención aceptaba
cualquier candidato que lo contuviera como subcadena —«**viking**ur reykjavik»—
sin mirar el parecido (0,50, muy por debajo del umbral de 0,78) porque se aplica
antes.

La regla hace falta: es la que casa «Roma» con «AS Roma» y «Man City» con
«Manchester City». Dos reglas obvias fallaron antes de dar con la buena:

* **palabra completa** tumbaba «Man City» y «West Brom», donde la abreviatura
  trunca una palabra, y truncar es legítimo;
* **exigir parecido** tampoco vale: «Ajax» contra «Ajax Amsterdam» tiene 0,44 de
  similitud, **menos** que el 0,50 del Viking, y es correcto.

Lo que los separa es cuántas palabras le **sobran** al nombre largo:

    man     contra manchester           no sobra ninguna      -> truncado
    viking  contra vikingur reykjavik   sobra «reykjavik» y
                                        ninguna casa entera   -> OTRO club
    ajax    contra ajax amsterdam       sobra «amsterdam» pero
                                        «ajax» casa entera    -> vale

Regla final: cada palabra del corto casa con una del largo —entera o como prefijo
de tres letras o más— y, si al largo le sobran palabras, al menos una tiene que
casar **entera**.

Medido antes de tocarlo (`_v163_contencion_enganosa.py`) sobre **1.779
emparejados reales** del proyecto —cada equipo de cada competición activa contra
el catálogo de su motor y contra el de ESPN—: cambia **exactamente uno**, y es el
Viking. Ojo con `normalizar`, que borra « city»: por eso «Man City» queda en «man»
y ahí no sobrevive ninguna palabra entera — es el caso que descartó la primera
regla.

---

## 14. La insignia, la línea de la casa, y una lambda que no era la que se midió

### 14.1 Un bloque estimado no puede llevar «destacado»

Auditado sobre el barrido del 2026-08-23 (`_v164_auditar_destacada.py`), hay
**dos cosas distintas** que se llamaban «destacado» y sólo una estaba mal:

* **el titular de la tarjeta** (`apuesta_destacada`) — los 151 del día salían de
  Goles (96), BTTS (45) y 1X2 (10), todos derivados de la matriz de marcador,
  que se entrena con goles reales en las 62 competiciones. **No estaba
  afectado.** Se le pone la guarda igualmente, porque el día que alguien meta un
  mercado físico en `mercados` se llenaría de estimaciones sin que nada lo
  denunciara — el modo de fallo de la v106 otra vez.
* **la insignia de cada bloque físico** — de 624 bloques pintados, **232 eran
  estimados y todos la llevaban**, anunciando hasta un 68 %. Y en **58 partidos
  lo eran todos** (Danubio-Racing de Montevideo, Sonderjyske-Nordsjaelland).

Un bloque estimado es el nivel de la competición repartido por bando, idéntico
en todos los partidos de esa liga: su propia etiqueta lo dice. Anunciarlo como
destacado le da forma de recomendación a un número que no distingue un partido
de otro.

`confianza_mercado.py` decide, con el error de calibración por liga que mide
`informe_calibracion.py`:

| nivel | condición | insignia | tras el cambio |
|---|---|---|---|
| 1 | observado, error < 0,02 | sí | 289 bloques |
| 2 | observado, 0,02-0,05 o sin medir | sí, con el error al lado | 103 |
| 3 | **estimado** | **no** | 232 |

Ninguna competición observada pasa de 0,05, así que el nivel 3 es exactamente
«lo estimado». Las filas y la etiqueta `📐 Estimado` **no se tocan**: desaparece
la insignia, no la información. Tampoco se resalta ya una fila en negrita, que
es la misma afirmación con otra tipografía.

**Y sigue siendo ámbar en los tres niveles.** El verde de esta aplicación
significa «canal con percentil 5 de bootstrap positivo medido» (§0), y córners,
tarjetas y remates no lo tienen. Estar bien calibrado y estar bien pagado son
ejes distintos; subir el nivel 1 a verde diría lo segundo enseñando lo primero.

### 14.2 La línea de la casa estaba ahí y se estaba tirando

El encargo daba libertad para buscar APIs de pago. No hizo falta. Sondeado el
tablero real (`_v164_sondeo_mercados_jugador.py`), de 13.769 familias distintas
en 8 partidos:

    Remates - <Jugador> (<COD>) ............  317
    Remates a Puerta - <Jugador> (<COD>) ...  317

unas 80 por partido, con tres líneas cada una. Se sabía que Playdoit servía
mercados de jugador —`snapshots_tarjetas` los descarta a propósito— pero nadie
había mirado si entre ellos estaban los de remates.

**`sv` NO es la línea principal, y eso se midió.** Parecía serlo: llega como
`'2.5|ws:player:6312'`. Sobre 432 mercados, `sv` cae en cualquier punto de la
escalera y la cuota de esa línea tiene **mediana 2,60**, con casos de 20,00. Con
ella se enseñaban cosas como «José Manuel López 5 % de +4.5»: cierto y sin
interés. Se elige la línea de cuota más cercana a 2,00 —donde la casa parte su
opinión por la mitad— y la mediana pasa a **1,95** con máximo 4,00. Se elige
**sin mirar nuestro modelo**: coger la línea más parecida a nuestra lambda sería
enseñar el número que mejor nos deja.

**El coste manda dónde vive cada cosa**, que es la lección que ya costó dos
regresiones en la v163: la tarjeta lee de `lineas_jugador_dia.json` y no hace ni
una petición (0,08-0,28 s por tarjeta); la ficha sí pide en vivo; el bot
precalcula. El fichero se guarda sin sangrado y sólo con la línea principal y su
cuota: de 968 KB a 425 KB, porque se commitea todos los días.

**Emparejar nombres de PERSONA no es emparejar clubes.** «Diego Gómez» contra
«Diego Alexander Gomez Amarilla» no es subcadena y su similitud es 0,50, por
debajo del umbral de 0,78. La regla —todas las palabras del corto en el largo y
el apellido coincidiendo, y si casan dos candidatos no se elige ninguno— sube el
emparejado de 224 a 243 sobre 422 jugadores, y los 19 que gana son todos
correctos (incluido «Lee Kang-In» contra «Kang-in Lee», que va invertido). Vive
en `lineas_jugador`, no en `name_mapper`: aplicarla a clubes movería emparejados
medidos y cerrados. El 42 % que sigue sin línea **no es un fallo**: la casa
cotiza ~40 jugadores por partido y ESPN devuelve ~55.

### 14.3 LA LAMBDA QUE SE ENSEÑABA NO ERA LA QUE SE MIDIÓ

Con la línea de la casa delante apareció un patrón: varios delanteros salían con
14-16 % sobre su línea. Comparando nuestra lambda con la que implica la casa
(`_v164_lambda_contra_casa.py`, 1.094 jugadores), la razón salía **0,619**.

Buscándolo se encontró un defecto real y de la v163:

> El modelo por jugador se validó sobre remates **por titularidad** (§13.7).
> Producción dividía entre **apariciones**, que incluyen entrar diez minutos
> desde el banquillo. Son dos magnitudes distintas y la segunda es menor.

Medido sobre 24.059 apariciones (`_v163_cache_jugadores/`):

    remates totales   titular 0,9888 · suplente 0,4741   razón 0,4795
    a puerta          titular 0,3334 · suplente 0,1631   razón 0,4890
    y el 29 % de las apariciones son suplencias

Con `subIns` —que ESPN ya publicaba en el roster y no se guardaba— se despejan
las titularidades y la media sale exacta: `m = total / (T + 0,4795·S)`. La razón
contra la casa sube a 0,668.

**El resto del hueco no se persiguió, y está razonado.** Este patrón de medida no
puede zanjarlo: Playdoit publica **sólo el lado «Más de»** de estos mercados
—comprobado, 0 pares Más/Menos en cinco partidos— así que el margen no se puede
quitar y la lambda implícita sale inflada; y la población no está emparejada,
porque la casa cotiza a los que espera que jueguen y nuestra lista es la
plantilla entera.

En cambio hay dos comprobaciones **contra la realidad** que dicen que el nivel
está bien:

* el modelo por jugador dio ECE 0,029 contra el resultado real sobre 6.688
  titulares-partido (§13.7);
* la cuota posicional está exactamente escalada: un once 4-4-2 suma **0,857** de
  los remates del equipo, y la fracción real que se llevan los titulares es
  **0,857** de mediana sobre 1.515 equipos-partido.

Lo que zanja esto es liquidar `remates_snapshots.csv` cuando haya volumen, que
es lo único que mide dinero en vez de opiniones.

### 14.4 Dos cosas que cambiaron solas mientras tanto

**El `--build` llegó.** El bot reescribió los históricos con el boxscore de ESPN
inyectado: las competiciones con remates observados pasan de **20 a 50 de 62**, y
la posesión de la Premier deja de ser sintética (1.613 filas marcadas). Es el
pendiente número 6 del traspaso de la v163, cumplido.

**Un test se cayó por mirar texto en vez de comportamiento.** Comprobaba el ámbar
recortando 900 caracteres del fichero desde `def _bloque_corners_html`, que es una
línea que delega en la de al lado; al crecer el docstring vecino, el 🟡 se salió
de la ventana y falló sin que nada hubiera cambiado. Ahora se comprueba sobre el
HTML pintado.


## 15. El control de cordura: ningún porcentaje sin algo contra lo que medirlo

### 15.1 El caso, con nombre y resultado

Parlay del 2026-08-23, tres patas y las tres de esta pantalla:

| partido | lo que decía la tarjeta | lo que pasó |
|---|---|---|
| Celta B – Andorra (`esp_hypermotion`) | ✅ Menos de 2.5 — 80 % | 4-2 |
| Bologna – Lazio (`serie_a`) | 🟡 destacado: Local Menos de 5.5 60 % (córners) | pasó la línea |
| Brøndby – Silkeborg (`dinamarca`) | Menos de 2.5 53 % · tarjetas Menos de 4.5 51 % | ninguna |

El fallo **no es acertar o no acertar un partido**: eso pasa y no se arregla. El
fallo es que la pantalla publicó una convicción que nada sostenía, y la publicó
en verde. Un 80 % de «menos de 2,5» sale de una λ de partido de 1,35 goles.

### 15.2 Lo que estaba roto: el pronóstico no llevaba el precio encima

Medido sobre el barrido cacheado del 2026-08-23 (`_v165_medir_cordura.py`):

    156 pronósticos de fútbol
      0  llevaban `cuota` en NINGÚN mercado

No era un fallo del barrido. `pronosticos` se construye por el camino del
MODELO (`alpha_finder._mercados_modelo`), que emite cuota justa y `cuota: None`
a propósito. Los precios reales existían, pero vivían en `candidatos`/`capa1`,
que son otra lista y sólo cubren lo que pasó los filtros de élite. O sea que la
tarjeta **nunca tuvo con qué contrastarse**, y el verde salía sólo de que el
número fuera grande. Resultado: **103 de 151 tarjetas en verde**.

De las 11 que se pudieron contrastar a posteriori contra el tablero cacheado de
la casa, **4 se separaban más de 15 puntos y 3 de esas 4 estaban en verde**:

    Sport – América Mineiro       Más de 2.5     modelo 70 %  casa 46 %   ← verde
    Deportivo Madryn – Godoy Cruz Menos de 2.5   modelo 87 %  casa 67 %   ← verde
    2 de Mayo – Guaraní           Menos de 2.5   modelo 81 %  casa 63 %   ← verde
    Tigre – Central Córdoba       Ambos marcan   modelo 59 %  casa 34 %

### 15.3 Los tres frenos, y por qué son tres y no uno

`cordura_probabilidad.py`. Son distintos y sus consecuencias también:

1. **Contra el precio de la casa.** Más de 15 puntos de separación contra la
   implícita SIN MARGEN → la cifra se recorta al 60 % y se rotula «🔴
   Probabilidad poco fiable». No es que la casa tenga razón por serlo: es que
   este proyecto tiene MEDIDO que guiarse por su probabilidad rinde −4,66 % a
   −6,52 % sobre 37.158 apuestas, y que su EV correlaciona −0,054 con el cierre.
2. **Contra el nivel de la competición.** Techo del 65 % cuando la línea cae por
   debajo de la media de goles de la liga, y del 50 % cuando cae 0,5 goles o más
   por debajo. Con la línea de 2,5 eso es exactamente lo que se pidió: «λ > 2,5
   → 65 %» y «λ > 3,0 → 50 %».
3. **Sin precio, sin verde.** Cuando no hay con qué contrastar, la cifra se
   enseña entera —no se recorta— pero se queda en ámbar y la tarjeta dice por
   qué. El ✅ es la única marca de esta pantalla que se lee como «juega esto».

**El techo sólo BAJA.** Un modelo tímido no se sube nunca hacia la casa: eso
sería publicar la opinión de la casa con la cara del modelo, que es el error que
la v149 ya evitó con las barras de mercado.

**El generalizado importa.** La regla 2 no se aplica a cualquier «menos de»:
sólo cuando la línea está en el lado equivocado de la media. «Menos de 3,5» en
una liga de 2,7 goles es un favorito legítimo al 75 % y recortarlo sería el
error contrario. Medido: 55 de 151 titulares caen bajo la regla, 31 se recortan,
6 pierden el verde por ella.

### 15.4 De dónde sale la implícita, y por qué se adjunta en el barrido

`mercado_implicito.py` saca del tablero de la casa 1X2, goles (todas sus líneas)
y ambos marcan, devigados con `potencia` (el método que la v80 midió mejor por
log-loss en las tres familias). El bot lo precalcula en `mercado_dia.json`, en el
MISMO paso del workflow que las líneas de jugador y a continuación: las dos
cosas salen del mismo tablero por evento, que `cuotas_multi` acaba de dejar en la
caché de disco con TTL de 30 min, así que el segundo precálculo casi no descarga.

El precio se adjunta al pronóstico **en `alpha_finder`**, no se busca desde la
tarjeta, y por dos motivos:

* **Por los nombres.** El precálculo se indexa con los del FIXTURE y el
  pronóstico lleva los del catálogo del modelo, ya pasados por `name_mapper`.
  Buscando desde la tarjeta con los segundos, sólo **22 de 151** partidos
  encontraban su entrada. En `alpha_finder` todavía está `fx` con el nombre
  crudo y la llave es exacta.
* **Porque la tarjeta no pide red.** Esa regla ya costó tres regresiones al
  proyecto (383 s y 388 s de barrido).

Como respaldo, `implicitas_de_la_casa` completa con las cuotas que el barrido ya
tenía descargadas de ESPN y Pinnacle. Ninguna petición nueva.

### 15.5 Lo que esto NO toca

La Sección 1 y el EV. La ventaja de precio es el único canal con percentil 5
positivo medido del proyecto (+11,49 %, p5 +1,73 %), y se calcula sobre la
probabilidad cruda en `alpha_finder`. Meter un techo ahí cambiaría el canal
validado por uno sin validar. **Todo esto vive en la capa de presentación.**

### 15.6 Y los bloques físicos: quitar la insignia no bastaba

La v164 dejó de pintar «destacado» en los bloques estimados (§14.1). Pero el
bloque seguía teniendo el mismo peso visual que uno medido: tres filas en negro
con sus porcentajes. Eso es lo que se leyó como recomendación en la pata de
córners de Bologna–Lazio. Desde la v165, sin insignia el bloque entero va en
gris (`mm-sinsena`): se ve, se puede consultar, y no compite con lo que sí está
medido. Es la misma disciplina que la barra de mercado de la v149 — otro origen,
otro tono.

### 15.7 Lo que cambia en pantalla, sin adornarlo

De las 151 tarjetas del día, **103 iban en verde**. Con las tres reglas y la
cobertura de precio que hay hoy, el verde cae a un puñado. **No es un efecto
secundario: es el cambio.** Una pantalla donde dos de cada tres tarjetas gritan
«✅» no está informando, está decorando. La cobertura de la casa (Playdoit cotiza
unos 76 de los fixtures del día, ~49 %) es el techo de cuántas tarjetas pueden
llevar verde, y subirla es trabajo de emparejamiento, no de umbral.

### 15.8 Y una cosa que apareció al construirlo: emparejamientos rotos

Al generar el primer `mercado_dia.json` (54 partidos de 75 fixtures, 72 % de
cobertura), un partido salía con el favorito del revés: **Botafogo – Athletico-PR**
del Brasileirão, con el local a 3,80 cuando ESPN lo pagaba a 2,40.
`cuotas_multi._buscar` lo había casado con el **«Botafogo SP – Atlético»** que la
casa cotizaba **ese mismo día**. Pasar `fecha` y `liga` —las dos guardias de la
v114— **no lo arregla**: los dos partidos comparten día y categoría.

Un precio de otro partido no produce un hueco, que sería honesto: produce un
**contraste falso**, que es lo contrario de para lo que existe todo esto.

La solución no es tocar el emparejador —eso mueve todos los emparejados del
proyecto y es una medición aparte (pendiente 10)— sino usar la segunda opinión
que ya está ahí: el 1X2 que ESPN publica del mismo fixture. Medido sobre los 54
partidos con las dos fuentes (`_v165_emparejado_casa.py`):

    |dif| > 0,10    1 partido    ← el emparejamiento roto, y sólo él
    |dif| > 0,20    0 partidos
    los otros 53 discrepan 0,02 o menos

La separación entre lo correcto y lo roto es de un orden de magnitud, así que el
umbral (0,10) no es una elección fina. `alpha_finder._mismo_partido` sólo
DESCARTA: nunca inventa un precio ni corrige uno, y su modo de fallo es un
hueco.

Dos correcciones más del mismo día de construcción:

* **El 1X2 salía en 22 de 54.** `mercados_playdoit` devuelve `home`/`away` con
  los nombres del LLAMADOR y `casa_home`/`casa_away` con los de la casa; se
  comparaban las selecciones contra los primeros («Athletico-PR» contra
  «Athletico Paranaense»). Ahora manda el `tipo` de la selección (1/2/3), con el
  nombre de respaldo — y con el cambio de lado cuando el emparejador marcó
  `invertido`, porque el tipo 1 de la casa es nuestro visitante en ese caso.
* **Los cuartos se rotulaban mal.** `'%.1f'` convertía «Más de 1.25» en la clave
  `1.2` y «Más de 1.75» en `1.8`. Emparejaban bien entre sí, pero el rótulo
  mentía. `mercado_implicito.clave_linea` es ahora el único sitio donde se
  fabrica esa etiqueta, y por ahí pasan tanto quien escribe como quien lee —
  incluido el respaldo de `alpha_finder`, que si no habría escrito `2.5` donde
  el otro esperaba `2.50`.

### 15.9 El estado tras el cambio, medido

Barrido del 2026-08-24, 61 partidos de futbol con modelo y el fichero
`mercado_dia.json` generado:

    con precio de la casa adjunto        59 de 61
    con la linea 2.5 de la casa          53
    titulares contrastables              47  (77 %)
    marcados poco fiable                 18  (38 % de los contrastables)
    recortados por alguna regla          12
    en VERDE                             22

Los 18 sobre 47 son el hallazgo y no un efecto secundario: el modelo se separa
mas de 15 puntos de la casa en dos de cada cinco titulares que se pueden
comprobar. Lo que zanja quien tiene razon es liquidar esos casos cuando haya
volumen, igual que con los snapshots de cornrs y tarjetas — y ahora
`mercado_dia.json` se commitea a diario, asi que ese historico empieza hoy.

## 16. El umbral medido con lo que ya había, y la causa raíz que destapó

### 16.1 No hacía falta esperar seis semanas. Los datos estaban en el repo

El umbral de 15 puntos de la v165 era una intuición y estaba escrito como tal.
El proyecto ya tenía dos ledgers **walk-forward** con la probabilidad que el
modelo dio de verdad, el resultado real y la cuota de CIERRE:

    pick_ledger_totales.csv   17.532 partidos con cuota O/U 2,5 · 20 ligas
    pick_ledger.csv           36.025 partidos con cierre 1X2   · 56 ligas
                              (26.666 con Pinnacle de ancla)

`_v166_umbral_cordura.py` los recorre y mide dos cosas que no son la misma: el
**ROI** de respaldar el lado que el modelo prefiere a la cuota de cierre, con su
percentil 5 de bootstrap, y la **brecha de calibración** — |media(p) − frecuencia
real| — que es lo que el usuario ve.

### 16.2 Lo primero que dijo la medición: el valor absoluto escondía el problema

Con el desvío en valor absoluto, la brecha del 1X2 salía ≤ 0,008 en TODOS los
tramos. Parecía que el 1X2 no mentía nunca. Separando por dirección:

    1X2, modelo POR ENCIMA de la casa      1X2, en valor absoluto
      0-3 pp   0,018                         0-3 pp   0,004
      5-7 pp   0,050                         5-7 pp   ~0
     15-20 pp  0,176                        15-20 pp  0,006

Los dos sesgos se cancelaban. Es exactamente la trampa que el §2b del traspaso
dejó escrita para remates —«el error marginal no mide resolución»— reapareciendo
en otro sitio. **La regla de la v165 usaba el valor absoluto**, y eso sólo se
sostiene si las dos direcciones mienten igual. No lo hacen.

Cuando el modelo va por DEBAJO de la casa (4.207 partidos de goles) dice 55 % y
pasa el 63-73 %: se queda corto, que es la dirección inofensiva. Marcar eso en
rojo señalaba como sospechoso un número prudente. Desde la v166 el recorte es de
un solo lado.

### 16.3 Y lo segundo, que era lo importante: el recorte era el síntoma

    GOLES, modelo por encima de la casa
    desvío      n      brecha
    0-3 pp    1661     0,002
    3-5 pp    1295     0,044
    5-7 pp    1317     0,065   ← cruza el 0,05 del proyecto
   11-13 pp   1254     0,124
   15-20 pp   2227     0,169   ← donde recortaba la v165
    > 20 pp   2745     0,281   dice 73 %, pasa el 45 %

El 15 dejaba pasar una banda entera en la que el número ya mentía por diez
puntos. Pero la pregunta buena no era dónde cortar, sino **por qué el 1X2 y los
goles se comportan tan distinto siendo el mismo modelo, los mismos partidos y el
mismo día**. La respuesta: el 1X2 se encoge hacia el mercado desde la v71
(`calibracion_mercado`, w con suelo 0,25) y **los goles nunca recibieron ese
tratamiento**.

    goles sin encoger (w=1,00)   ECE 0,0948 · brecha en >15 pp  0,2215
    goles con w=0,25             ECE 0,0139 · brecha           0,0211
    óptimo por ECE   (w=0,15)    ECE 0,0110 · brecha           0,0066

Un orden de magnitud, con maquinaria que ya existía y estaba validada. Se adopta
el suelo de 0,25 y no el óptimo de 0,15 porque bajar `W_MIN` sería re-litigar
para goles una decisión medida para otro mercado (v75), y con 0,25 la mejora ya
está hecha.

**Y una honestidad incómoda:** por Brier y por log-loss el mejor peso es
**w=0,00** — el mercado solo. El modelo no aporta nada medible a los goles por
encima del precio de la casa. Se queda en 0,25 porque por ECE sí gana algo y
porque publicar el mercado puro con la cara del modelo sería la mentira
contraria. Es coherente con el hallazgo central del proyecto: el modelo no bate
al mercado.

### 16.4 El umbral resultante, y de dónde se lee

Con el encogimiento puesto, el residuo se mide otra vez y el corte queda en
**5 pp** para los tres mercados. Se escribe en `cordura_umbrales.json` y
`cordura_probabilidad.umbral()` lo lee de ahí: si alguien repite la medición con
más partidos y el corte se mueve, se mueve solo. Un número copiado a mano en el
código es exactamente el que hubo que arreglar hoy.

BTTS hereda el umbral de goles: sale de la misma matriz de marcador y no hay
cuota histórica de BTTS con la que medirlo por separado. Queda anotado en el
propio fichero.

### 16.5 Córners: ya salían en las 62, pero contra una línea inventada

Comprobado: `stats_disponibles` da córners observados en **50 de 62**
competiciones, y en las otras 12 el bloque sale igual con el estimador de
respaldo y su «📐 Estimado» (v162) — en gris desde la v165. O sea que «que se
vean en todas» ya estaba.

Lo que no estaba era la LÍNEA. La tarjeta usaba «la de medio punto más cercana a
la media», que es una línea inventada: podía anunciar «Más de 9.5 57 %» mientras
la casa cotizaba 8,5, y entonces ese porcentaje no era el de ninguna apuesta que
se pudiera hacer. `mercado_implicito` saca ahora también el total de córners del
tablero, línea a línea y devigado, y la tarjeta usa la real más cercana a la
media, rotulada «línea de la casa». Cobertura el 2026-08-24: 32 de 53 partidos
con precio.

Dos trampas al leerlo, las dos evitadas: las familias por EQUIPO («Brighton
Total de Tiros de Esquina») y las de media parte llevan la misma palabra. Y el
filtro por nombre de equipo se hace por **palabras enteras**, no por subcadena:
con `equipo in nombre` bastaba un club corto —«Ajax», «Roma»— para casar dentro
de otra palabra y tirar el mercado del partido entero. Misma lección que la
v163.1 con `name_mapper`.

### 16.6 Y la tarjeta deja de esconder nada

Los remates por equipo vuelven. La v163.1 los quitó a petición del usuario («lo
único que me interesa saber es quién remata»); ahora se pide lo contrario y
explícitamente. Las dos peticiones no se contradicen tanto como parece: lo que
hacía ruido no era el bloque, era que un bloque estimado —idéntico en todos los
partidos de su liga— tuviera el mismo peso visual que uno medido. Eso se
arregló en la v165 con el gris, así que la información vuelve y la jerarquía se
queda.

El test `test_la_tarjeta_no_pinta_remates_por_equipo` se invierte pero
**conserva su nombre**: renombrarlo borraría el rastro de que esto se decidió,
se midió y se revirtió.

## 17. La tarjeta deja de informar y pasa a recomendar

### 17.1 El encargo, con sus palabras

«No quiero leer, quiero apostar.» La tarjeta enseñaba seis bloques, cuatro
párrafos técnicos y ninguna instrucción: *«Estimado · esta competición no
publica esta estadística: el nivel sale de sus goles…»*, el perfil del árbitro,
*«Sergio Rodelas 32 % de +1.5 · 42 % de +0.5 a puerta»*, el aviso de cordura. Lo
que no había en ninguna parte era **qué meter en el boleto**.

Lo que hay ahora, de arriba abajo:

    partido · liga · hora
    🏆 APUESTA RECOMENDADA        una, con su cuota y su botón
    📊 OTROS MERCADOS             una fila por mercado, sin párrafos
    📊 Análisis completo          desplegable, cerrado

**Nada se ha borrado.** Todo el texto técnico vive dentro del desplegable. Es la
diferencia entre esconder y ordenar: lo segundo se puede abrir.

### 17.2 El orden de prioridad, y la parte que no se pudo seguir al pie de la letra

Lo pedido: (1) mejor EV, (2) si ninguno es positivo, la de mayor probabilidad
calibrada por encima del 60 % en verde o ámbar, (3) si no hay nada, decirlo.

El paso (1) **tal cual estaba escrito** —EV sobre la probabilidad CRUDA del
modelo— es exactamente el canal que este proyecto tiene medido como
ANTI-INDICADOR: −4,66 % a −6,52 % sobre 37.158 apuestas, correlación −0,054 con
el cierre (§2 del traspaso). Y peor: el EV crudo es máximo justo donde el modelo
más se separa de la casa, que es donde la v166 midió que su número más miente
(brecha 0,281 por encima de los 20 puntos de desvío). Ordenar por ahí habría
reconstruido, con otro nombre, el fallo que la v165 y la v166 acaban de cerrar.

Así que **el orden se respeta y el EV se calcula sobre la probabilidad ya
ajustada** por `cordura_probabilidad` (encogida hacia el mercado, recortada si
hace falta). Con esa probabilidad, un EV positivo ya no significa «el modelo
discrepa mucho» sino «esta casa paga por encima de lo que vale» — que es la
ventaja de PRECIO, el único canal con percentil 5 positivo medido del proyecto
(+11,49 %, p5 +1,73 %). Es la misma apuesta que pedía el encargo, calculada
sobre el número que la v166 dejó honesto.

### 17.3 Tres reglas que la recomendación no puede saltarse

* **Un mercado ESTIMADO no se recomienda nunca**, ni al 93 %. Es el nivel de la
  competición repartido por bando, idéntico en todos sus partidos (v164).
* **Un mercado físico observado sí puede ser la apuesta, pero siempre en
  ÁMBAR.** Verde significa «canal con p5 de bootstrap positivo medido», y
  córners, tarjetas y remates no lo tienen. La puerta de entrada es la MISMA
  que la de la insignia del bloque (`confianza_mercado`), para que no puedan
  decir cosas distintas la insignia de abajo y la recomendación de arriba.
* **El verde exige precio de la casa con el que contrastar** (v165).

### 17.4 Dos decisiones de diseño que se tomaron con la medición delante

**El suelo del 50 % es de la vía de probabilidad, no de la de precio.** La
primera versión filtraba TODO por debajo del 50 % y con eso tiraba justo las
apuestas de valor: una ventaja de precio real casi nunca es favorita — el canal
medido vive en comprar barato, no en comprar seguro. Ahora una apuesta con EV
positivo entra aunque esté al 41 %, y su coletilla lo dice: «la casa la paga por
encima de su valor», no «sólo para combinar», que la describiría mal.

**El verde gana al porcentaje.** Un bloque de córners al 78 % es ámbar porque su
ventaja de precio no está medida; proponerlo por delante de un 64 % que sí pasó
el contraste sería premiar la cifra grande sobre la comprobada. Medido sobre 40
partidos del barrido: con esta regla, la tarjeta y el filtro «sólo alta
probabilidad» de la lista **discrepan en 0**. Sin ella discrepaban, y eso es una
aplicación diciendo dos cosas de la misma pregunta.

### 17.5 El filtro de la lista habla ahora el mismo idioma

El recuento y la casilla de «sólo alta probabilidad» miraban `_destacada` y la
tarjeta enseña la recomendada. Dos criterios para la misma pregunta acaban
divergiendo. Ahora los dos salen de `apuesta_recomendada`.

Se calcula sin los bloques físicos a propósito: como nunca pueden ir en verde,
no cambian la respuesta a «cuántas hay jugables en solitario», y pedirlos ahí
serían tres consultas por partido en una pantalla que ya tarda.

### 17.6 Lo que se midió del resultado

Sobre 40 partidos del barrido del 2026-08-24: **21 en verde · 18 en ámbar · 1
sin apuesta jugable**. Ninguna recomendación salió por la vía del precio, y eso
tiene explicación: los `pronosticos` se construyen por el camino del modelo, que
emite `cuota: None` a propósito, así que hoy sólo hay EV cuando el pick trae
precio real. La vía existe y está probada; se activará sola según crezca la
cobertura de cuotas.

Render: 3 vistas OK, la de Apuestas del Día en 115 s (antes 174 s).

## 18. El Mercado Rey: cada competición tiene el suyo, y casi nunca son los goles

### 18.1 El caso, y la pregunta que abrió

«Menos de 2.5 — 82 %» en el Brasileirão B. Terminó **1-4**. La pregunta que se
hizo el usuario no fue «¿por qué falló?» sino la buena: **¿por qué la aplicación
recomienda siempre desde el mismo sitio?** La respuesta era que nadie había
medido si ese sitio es el mejor de esa liga. Y no lo es.

### 18.2 Lo medido: todo el catálogo, en las 62 competiciones

`mercado_estabilidad.py` mide con **ECE** —error de calibración por deciles,
la métrica con la que este proyecto decide desde la v163— sobre las cuatro
fuentes que ya estaban en el repo:

    1X2, doble oportunidad ....  pick_ledger.csv          47.948 · 56 ligas
    goles 1,5/2,5/3,5 y BTTS ..  pick_ledger_totales.csv  47.794 · 55 ligas
    hándicap asiático .........  pick_ledger_handicap.csv 47.794 · 55 ligas
    córners/tarjetas/remates ..  _v162_calibracion_por_liga.json    61 ligas

Los tres ledgers son WALK-FORWARD. Sin eso, todo esto sería una medición de
memoria.

**Se mide con ECE y no con la razón varianza/media** porque hay que ordenar
juntos un mercado binario (1X2) y uno de conteo (córners), y una razón
varianza/media no se puede comparar con la de un mercado de dos vías. La razón
varianza/media sí se usa, para lo que sirve: la **cuarentena** de los conteos.

### 18.3 El resultado: el rey cambia por completo de liga a liga

    Hándicap             14 competiciones
    Córners por equipo   12
    Remates a puerta      7
    Doble oportunidad     6
    Tarjetas por equipo   5
    Remates por equipo    5
    Tarjetas              3
    Remates               2
    1X2                   1
    Córners               1
    (ninguno)             6

O sea que el rey sale de las tres familias del catálogo —resultado, goles y
estadísticos—, que era justo lo que había que comprobar.

**Y los goles salen 🔴 INESTABLES en todas las ligas medidas** — ECE de 0,086 a
0,129 en crudo. Era el mercado del que salía el **64 % de los titulares** de la
aplicación (96 de 151, auditado en la v164). Estábamos recomendando desde el
peor sitio del catálogo.

**BTTS no corona ninguna liga**, y eso no es un hueco: calibra 🔴 en todas.
Un catálogo completo también sirve para descartar.

### 18.4 Dos calibraciones por mercado, y la diferencia decide

`ece` es la del modelo crudo; `ece_ajustada` es la de la probabilidad que la
aplicación **enseña de verdad**, encogida hacia el precio de la casa como hace
`cordura_probabilidad` desde la v166. La diferencia no es académica:

    Premier, goles 2,5   crudo 0,129  ->  ajustado 0,046   🔴 pasa a 🟡
    bra_serie_b, goles   crudo 0,118  ->  sin cuota        🔴 se queda 🔴

Clasificar sólo por el crudo pondría en cuarentena un mercado que en pantalla
calibra bien. Clasificar sólo por el ajustado mentiría en los partidos que la
casa no cotiza, donde no hay hacia dónde encoger y lo que se ve es el crudo.
Manda la ajustada **cuando existe**, que es la regla de «qué está viendo el
usuario».

### 18.5 Lo que no se puede medir no se inventa

Tres familias del catálogo pedido salen con `origen: 'sin medir'`, fuera del
ranking y sin poder coronar nada:

* **goles por equipo** — ningún ledger guarda la probabilidad del modelo por
  bando, sólo el total y el BTTS;
* **resultado exacto** — el propio encargo lo marcó de baja prioridad y no hay
  columna que lo recoja;
* **remates de jugador** — `calibracion_remates_jugador.json` mide ECE 0,029 y
  0,024, pero AGREGADO sobre todas las competiciones. Un número global no puede
  coronar a una liga concreta.

Aparecen en el fichero, marcadas. Decir «no medido» es más útil que colarlas con
un número prestado: el Mercado Rey existe justo para no recomendar a ciegas.

### 18.6 Modo seguridad: tres puertas, y las tres son distintas

| puerta | umbral | de dónde sale | qué hace |
|---|---|---|---|
| recorte | 5 pp sobre la casa | medido, v166 | baja la cifra y la marca 🔴 |
| bloqueo | 10 pp sobre la casa | lo fijó el encargo | no se puede proponer |
| cuarentena | ECE > 0,05 o var/media > 2,0 | medido, v168 | el bloque no se propone |

Se aplican **encima** unas de otras, no en lugar de. Una decide cómo se ENSEÑA
la cifra y las otras si se puede PROPONER. Y un bloque en cuarentena **sigue
viéndose** con sus probabilidades: es la misma línea que la v165 trazó con el
gris — mirar sí, proponer no.

Un detalle que apareció midiendo: seis competiciones tenían «Remates por equipo»
con la varianza doblando a la media pero sin muestra para calibrarlo, y salían
`sin medir`. La cuarentena por varianza va ahora **primero y también sin ECE**:
son dos preguntas distintas, y etiquetarlo «no sabemos nada» cuando sabemos lo
peor es el error contrario.

### 18.7 El precio sigue mandando sobre el ranking, y no es un descuido

El ranking dice DÓNDE es fiable el modelo. La ventaja de precio dice dónde la
CASA se ha equivocado. Son cosas distintas, y la segunda es la única con
percentil 5 positivo medido en este proyecto (+11,49 %, p5 +1,73 %). Así que el
orden es: precio → ranking de estabilidad (con suelo del 55 %) → probabilidad →
combinar. Si el rey no llega al 55 % o no pasa el control de cordura, se busca
el siguiente, que es lo que se pidió.

### 18.8 Lo que cambia en pantalla, medido

Sobre 40 partidos del barrido: la recomendación pasa a repartirse entre
**tarjetas (17), resultado (4), goles (2), remates (2) y córners (1)** en vez de
salir casi siempre de goles. Y **14 de 40 se quedan sin apuesta jugable**, frente
a 1 de 40 antes. No es un efecto secundario: es el modo seguridad haciendo su
trabajo. Una aplicación que recomienda algo en el 97 % de los partidos no está
seleccionando.

La tarjeta suma una **tira de estabilidad** de seis iconos —🟢🟡🔴⚪, sin
leyenda— y los bloques en cuarentena llevan **🔒 No recomendado**, tres palabras.
El desplegable pasa a llamarse **🔍 Análisis**. Ningún texto visible de la
tarjeta pasa de 50 caracteres, y hay un test con regex que lo comprueba.

Coste medido: `apuesta_recomendada` 0,27 s por 40 tarjetas y la tira 0,000 s.
Los 296 s del render fueron barrido en frío, no esto.

## 19. Las líneas que la casa publica de verdad, y la apuesta liquidada

### 19.1 La pregunta del usuario, contestada mirando el tablero

«¿Se están mostrando las líneas de Playdoit para córners, tarjetas y remates?»
**No.** La v166 sacaba sólo el TOTAL de córners y descartaba a propósito las
familias por equipo; tarjetas y remates no se leían en absoluto. Con la
recomendación moviéndose a esos mercados (v168), los más estables estaban sin su
línea real.

### 19.2 Lo que se encontró al mirar, que no era lo que se suponía

El encargo decía que Playdoit publica sólo el total de tarjetas y **no** las de
equipo. Medido sobre ocho tableros del día, es al revés — y es muy desigual:

    Botafogo–Athletico-PR   16 familias de tarjetas: «Total de tarjetas»
                            (4,5/5,5/6,5) Y «Total de tarjetas Atlético» (2,5)
    Valencia–Betis          22 familias
    Real Madrid–Real Soc.    0 familias de tarjetas

Así que no se puede codificar «la casa publica esto». `_conteos_del_tablero` LEE
cada tablero y guarda lo que traiga. Cobertura medida sobre los 80 partidos del
precálculo:

    córners total 59 · tarjetas total 41 · remates 12 · a puerta 10
    córners por equipo 9 · tarjetas por equipo 10

O sea que las líneas por equipo existen, pero sólo en uno de cada nueve
partidos. Decirlo es parte de la respuesta.

### 19.3 Cuatro cosas que se descartan, cada una por su motivo

* **media parte** — es otro partido;
* **exacto, escala, impar/par, 1x2, hándicap, carrera, ambos, primer/último** —
  no son Más-Menos sobre una línea, así que no se pueden comparar con una
  binomial negativa;
* **tarjetas ROJAS** — nuestro modelo cuenta amarillas MÁS rojas (v160), y la
  familia de rojas sola es otro mercado. Mezclarlas no se vería;
* **mercados de JUGADOR** — Playdoit los rotula «Remates a Puerta - Vinicius
  Jr. (RMA)». Sin guarda, la línea de 1,5 remates de un extremo se archivaría
  junto a la de 24,5 del partido. Se detectan por el paréntesis, con excepción
  para los clubes que llevan uno en su nombre («Racing (Montevideo)»): si el
  rótulo casa con un equipo, es suyo.

Y el bando se resuelve con `casa_home`/`casa_away`, que `mercados_playdoit` ya
entrega orientados — el tablero de Botafogo llega `invertido` y aun así cada
línea acaba en su lado.

### 19.4 Goles: la medición dijo que no al 0,6 del encargo

El encargo proponía `0,6·modelo + 0,4·casa` y pedía calibrar los pesos con el
histórico. Ajustado sobre 17.532 partidos con las dos cuotas de cierre:

    peso del modelo      ECE      ligas con ECE > 0,05 (de 20)
    1,00 (crudo)       0,0948            20
    0,60 (pedido)      0,0472            16
    0,40               0,0230             9
    0,25 (desplegado)  0,0139             5
    0,09 (óptimo)      0,0109             6
    0,00 (sólo casa)   0,0123             6

El **0,60 es 4,3 veces peor que el óptimo** y dejaría 16 de 20 ligas por encima
del umbral. Y lo que ya estaba desplegado —0,25, el suelo de `calibracion_mercado`
fijado en la v75— es **el que menos ligas deja mal**. Así que no se cambia, y
eso también es un resultado: la solución inmediata que pedía el encargo ya
estaba puesta desde la v166.

**El objetivo de «ninguna liga por encima de 0,05» NO se alcanza.** Quedan cinco:
sco_premiership 0,078 · sco_championship 0,063 · turquía 0,062 · bundesliga
0,052 · eredivisie 0,051. Sin encoger no bajaba **ninguna** de las veinte;
encogiendo bajan quince.

**No se construyó el modelo de goles enriquecido**, y hay tres razones medidas
para no hacerlo: el xG y la posesión de football-data son SINTÉTICOS y el
proyecto tiene prohibido entrenar sobre ellos (§NO HACER); el peso óptimo del
modelo es 0,09, o sea que **el modelo aporta un 9 % de la mezcla** y el margen
de mejora por ahí es el que es; y el propio encargo decía «si el nuevo modelo no
mejora, usar sólo el encogimiento hacia la casa». La medición contesta antes de
construirlo.

### 19.5 La eficacia, liquidada contra el marcador

Lo que el usuario pidió: reconstruir sobre el histórico qué habría propuesto la
aplicación y comprobar si la apuesta se cumple. Sobre **47.794 partidos** con
1X2 y goles del mismo encuentro:

    política  apuestas    de      acierto   anunciado    ROI      p5
    v164        47.794  47.794     56,0 %     65,2 %   −4,96 %  −6,16 %
    v169        14.665  47.794     62,3 %     61,7 %   −4,21 %  −5,35 %

Lo importante no es el ROI. Es la distancia entre lo **anunciado** y lo
**ocurrido**: la política vieja prometía 65,2 % y acertaba 56,0 % — **nueve
puntos de mentira, sostenidos sobre 47.794 apuestas**. La de hoy promete 61,7 %
y acierta 62,3 %: se queda corta, que es el lado correcto del error.

Y apuesta en **14.665 de 47.794** partidos en vez de en todos. Una aplicación
que recomienda algo en el 100 % de los partidos no está seleccionando.

**El ROI sigue siendo negativo (−4,21 %) y el p5 también.** Esto calibra, no
promete dinero. Es exactamente lo que el proyecto lleva midiendo desde el
principio: el modelo no bate al mercado, y lo que ha mejorado es que ya no
finge lo contrario.

Una limitación honesta del backtest: los candidatos son 1X2, goles y BTTS,
porque son los que los ledgers guardan con probabilidad del modelo. En
producción entran además córners, tarjetas y remates, que no se pueden
reconstruir hacia atrás. Así que esta tabla mide la política, no todo el
catálogo.

### 19.6 Y el ranking deja de envejecer

`mercado_estable_por_liga.json` se generaba a mano. Ahora lo regenera
`recalibrar.yml` justo DESPUÉS de `informe_calibracion.py` —de donde lee la
calibración física— y se commitea. Al revés coronaría a los mercados con la
foto de ayer.

## 20. La apuesta más segura, no la mejor pagada

### 20.1 El cambio de filosofía, y es del usuario

Hasta la v168 la recomendación la decidía la **ventaja de precio**: la casa paga
de más. Es el único canal con percentil 5 positivo medido de este proyecto
(+11,49 %, p5 +1,73 %). Pero obliga a esperar a que Playdoit se equivoque, y lo
que se pidió es otra cosa:

> «No quiero depender del line shopping. Recomiéndame la apuesta con más
> probabilidad de acierto, aunque el momio sea 1,20.»

Son dos objetivos legítimos y distintos. Lo que no se puede es mezclarlos y
llamar «ventaja» a los dos. Desde la v170:

    la recomendación se elige por PROBABILIDAD entre los mercados estables de
    esa liga; el precio deja de decidir y pasa a ser una insignia, «💰 Valor»,
    cuando la casa se ha pasado de largo más de un 10 %.

**Y el verde cambia de significado.** Ya no dice «ventaja de precio medida»:
dice «mercado estable en esta liga y por encima del 60 %». La tarjeta no promete
ventaja de precio en ninguna parte, así que la marca no miente — pero es un
cambio del contrato que fijaba §0, y queda anotado aquí.

### 20.2 El intercambio, medido sobre 47.794 partidos

Las tres políticas sobre los MISMOS partidos y el MISMO catálogo:

    política  apuestas    de      acierto   anunciado    ROI      p5
    v164        47.794  47.794     74,5 %     78,9 %   −8,42 %  −12,25 %
    v169        44.421  47.794     75,2 %     77,0 %   −5,00 %   −7,47 %
    v170        44.557  47.794     76,0 %     78,0 %   −6,17 %  −12,61 %

La v170 **acierta más que ninguna** (76,0 %) y anuncia con dos puntos de holgura
—se queda corta, que es el lado correcto del error—. Y **paga por ello**:
−6,17 % de ROI contra el −5,00 % de mirar el precio.

Eso es exactamente el intercambio que se pidió, con números delante: se cambia
rentabilidad por tasa de acierto. **Ninguna de las tres gana dinero.** Esta
pantalla calibra; no promete beneficio, y no debe empezar a hacerlo.

### 20.3 La doble oportunidad entra, y se come la pantalla

`P(1X) = P(1) + P(X)`: no es un modelo nuevo, son sumas de la matriz de marcador
que ya estaba. Entra porque la medición la puso ahí — es el Mercado Rey de seis
competiciones — y porque por su forma es donde viven las probabilidades altas
que esta pantalla busca desde ahora.

**Consecuencia medida, y hay que saberla:** con la doble oportunidad dentro, 33
de 40 recomendaciones salen de ella y la aplicación propone algo en el **93 %**
de los partidos (antes de añadirla eran 17 de 40). Es lo que «la apuesta más
segura» significa matemáticamente: cubrir dos de tres resultados. Si esa
monotonía molesta, el mando está en subir el umbral del verde o dejar la doble
fuera del catálogo — las dos son una línea.

### 20.4 La α por liga: se probó y NO se adopta

El encargo pedía `α` por competición (0,7 si el modelo es bueno, 0,3 si es
malo). Se ajustó sobre el histórico de cada liga con validación fuera de
muestra, y el resultado no da para adoptarla:

    en muestra    α por liga deja 13 ligas bajo 0,05 · el 0,25 fijo deja 15
    fuera de muestra, ambas sobre el MISMO tramo:
        la α por liga mejora o iguala en 13 de 20 (p ≈ 0,13, no significativo)
        ECE medio: α 0,0933 · 0,25 fijo 0,0994

Y las α ajustadas son inestables — 0,00 en Premier, LaLiga y Eredivisie; 0,60 en
Ligue 2; 0,55 en Turquía — sobre muestras de 400 a 1.500 partidos. Es la misma
trampa que `calibracion_mercado` documentó en la v80: pesos por liga ajustados
sobre muestras cortas son decisiones sobre ruido. **Se mantiene el 0,25 global**
y `alfa_goles_por_liga.json` NO se genera, para que nadie lo confunda con algo
que producción lee.

La primera versión de esta medición comparaba la α **fuera de muestra** contra
el 0,25 **dentro**, y daba «0 de 20». Era una comparación injusta: el 0,25 ya
había visto esos partidos. Corregida, es 13 de 20. Queda escrito porque el error
es fácil de repetir.

### 20.5 Lo que el catálogo cubre hoy, y lo que no

Entran como candidatos: 1X2, doble oportunidad, goles, BTTS, hándicap, córners
(total y bando), tarjetas (total y bando), remates y remates a puerta. Las
líneas de conteo salen del tablero real (§19).

No entran, y se dice: **goles por equipo** (ningún ledger guarda la probabilidad
del modelo por bando), **resultado exacto** y **remates de jugador como
recomendación** — estos últimos sí se enseñan en la fila «🎯 Remata», con la
línea principal de la casa desde la v164, pero su calibración está medida
AGREGADA sobre todas las ligas y no por liga, así que no pueden coronar a
ninguna.

### 20.6 El caso original, cerrado por tres sitios

«Menos de 2.5 — 82 %» en el Brasileirão B, terminó 1-4. Hoy no puede volver, y
no por una regla sino por tres apiladas: los goles de esa liga están en
**cuarentena** (ECE 0,118); si hubiera cuota, el **encogimiento** bajaría el
82 % hacia la casa; y el **techo por media de goles** lo recortaría igual. Hay un
test por cada una.

## 21. El Score: la mejor relación probabilidad/cuota, línea a línea

### 21.1 Lo que la v170 hizo mal, con sus propias consecuencias

La v170 eligió por probabilidad absoluta y acabó recomendando doble oportunidad
al 79 % con cuota **1,10** en el 93 % de los partidos. Era literalmente «la
apuesta más segura», y era inservible. Desde la v171:

    Score = probabilidad ajustada × cuota de Playdoit

que es el valor esperado más uno. Un Score de 1,20 significa que, si la
probabilidad es correcta, cada peso devuelve 1,20.

### 21.2 Sin cuota no hay Score, así que la cuota se guarda

Hasta aquí `mercado_dia.json` guardaba sólo la probabilidad SIN MARGEN. Para el
Score hace falta el **precio que el usuario cobra**, que no es `1/implícita` —
la implícita ya no lleva margen y la cuota sí. Cada línea pasa a guardarse como

    {'p': 0.5447, 'mas': 1.741, 'menos': 2.05}

y se añaden `1x2_cuotas`, `btts_cuotas` y `doble_cuotas`. `prob_de()` y
`cuota_de()` entienden también el formato viejo: el fichero se regenera cada
noche y durante unas horas conviven los dos — sin esa compatibilidad la tarjeta
se quedaría sin líneas hasta que corriera el bot.

### 21.3 La escalera entera, que es la mitad del encargo

El ejemplo que se dio es exacto y ahora se cumple: «Más de 2,5» al 80 % con
cuota 1,40 da Score 1,12; «Más de 3,5» al 67 % con cuota 1,80 da **1,21**. La
segunda es mejor apuesta y hasta la v171 la aplicación **ni la calculaba**,
porque sólo miraba la línea más cercana a la media.

`valor_apuesta` recorre todas las líneas que la casa publica de cada mercado. El
modelo sabe dar probabilidad a cualquiera —la binomial negativa de córners,
tarjetas y remates acepta cualquier línea, y la matriz de marcador también—, así
que no hay que elegir una: se evalúan todas. `alpha_finder.lineas_de_goles` pasa
de tres peldaños (1,5/2,5/3,5) a siete (0,5 a 6,5), porque una línea que el
modelo no calcula es una que no se puede proponer aunque sea la de mejor valor.

Medido sobre los partidos del día: **327 líneas candidatas** en 117 partidos.

### 21.4 Qué publica Playdoit, medido antes de construir

`_v171_catalogo_playdoit.py` contesta la pregunta «para saber qué otros mercados
podemos meter». Sobre 22 tableros:

    familia        publica   con línea    ¿lo modelamos?
    goles            22/22      22/22     sí
    corners          22/22      22/22     sí
    tarjetas         15/22      15/22     sí
    remates           3/22       3/22     sí
    remates_on        3/22       3/22     sí
    marcador exacto  22/22       0/22     no
    jugador_goles    15/22       0/22     no
    jugador_tarjetas 15/22       0/22     no

Goles y córners están en el 100 % de los tableros. Remates y remates a puerta,
en el 14 % — así que el Mercado Rey «Remates a puerta» de siete competiciones
casi nunca tiene precio con el que jugarse. Eso no se sabía y cambia la lista de
la compra.

### 21.5 Dos guardas que aparecieron probando contra tableros reales

**La excepción del 1,15 no es una puerta para un volado.** Sin suelo duro, la
primera prueba contra el tablero de Real Madrid–Real Sociedad eligió «Real
Sociedad o empate» al **38 %** con cuota 3,10 (Score 1,178) — justo la apuesta
que el encargo dice no querer. Ahora hay suelo del 50 % pase lo que pase, y la
excepción exige además **contraste con la casa**: un EV alto calculado sobre una
probabilidad que nadie ha contradicho es el canal que este proyecto tiene medido
como anti-indicador.

**Nunca se propone un 🔴.** El propio encargo define el rojo como «no
recomendado» (Score < 0,95); devolver el máximo de una lista donde todo es rojo
sería recomendar lo menos malo. Medido: sin esa guarda salían recomendaciones
con Score 0,872.

### 21.6 La doble oportunidad, degradada a mercado normal

Entra al catálogo con su cuota, y por debajo de **1,30** ni se evalúa — a ese
precio el Score no puede competir aunque la probabilidad sea del 80 %, que es
exactamente lo que llenaba la pantalla en la v170. Medido en un tablero real:
1X a 1,091 y 12 a 1,111 quedan fuera; X2 a 3,10 se evalúa.

### 21.7 El resultado en pantalla, medido

Sobre los 117 pronósticos del día con el precio nuevo adjunto:

    23 partidos con recomendación por Score (7 🟢 · 16 🟡 · 0 🔴)
    Score mediana 1,033 · mínimo 0,961 · máximo 1,270
    reparto: doble oportunidad 19 · córners 3 · goles 1

Y cuando no hay cuotas de la casa no hay Score que calcular: ahí se cae a la vía
de la v170, que elige por probabilidad entre lo estable. La tarjeta añade una
tabla **💰 MEJOR VALOR** con las cuatro mejores líneas del partido, cada una con
su probabilidad, su cuota y su Score, para que la comparación se vea.

**El verde cambia de significado otra vez, y hay que decirlo:** en la v168 era
«ventaja de precio medida», en la v170 «estable y ≥60 %», y ahora es **Score >
1,10**. Es la tercera acepción en cuatro versiones. La coletilla de la tarjeta lo
dice en cuatro palabras («Mejor valor del partido»), pero conviene no volver a
moverlo sin motivo.

### 21.8 Un validador que medía el orden de un diccionario

`_v164_valida_tarjeta.py` falló el 2026-08-25 sin que nada se hubiera roto:
cogía los seis primeros partidos del fichero a ciegas, la ventana de fixtures se
movió y esos seis eran de ligas sin roster cacheado. Ocho de los diecisiete sí
servían. Ahora busca hasta encontrar cuatro. Un validador que depende del orden
de un diccionario mide el orden, no lo que dice medir.

### 21.9 La eficacia del Score, liquidada contra el marcador

Quedaba pendiente y es lo que decide si el cambio valió la pena. Reconstruida
la política del Score sobre los mismos 47.794 partidos del histórico:

    política  apuestas    de      acierto   anunciado    ROI      p5
    v164        47.794  47.794     74,5 %     78,9 %   −8,42 %  −12,25 %
    v169        44.421  47.794     75,2 %     77,0 %   −5,00 %   −7,47 %
    v170        44.557  47.794     76,0 %     78,0 %   −6,17 %  −12,61 %
    v171         2.947  47.794     66,0 %     65,2 %   **−0,67 %**  −2,81 %

**Un orden de magnitud mejor en ROI**, y apostando en el **6,2 %** de los
partidos en vez del 93 %. La tasa de acierto baja —66 % contra 76 %— y eso es
exactamente lo esperado: se cambian favoritos baratos por apuestas bien
pagadas. Lo que importa es que el dinero mejora al hacerlo.

Y la honestidad se mantiene: anuncia 65,2 % y acierta 66,0 %, se queda corta.

**SIGUE SIENDO NEGATIVO, Y ESO NO SE PUEDE ADORNAR.** −0,67 % con percentil 5 de
bootstrap en −2,81 % no demuestra ventaja: demuestra que el sistema se acercó al
punto de equilibrio. La regla de oro del proyecto sigue en pie — nada en verde
sin p5 positivo medido — y este canal no lo tiene. Lo que sí se puede decir es
que de las cuatro políticas medidas, ésta es la única que se aproxima a no
perder.

**Dos limitaciones del backtest, dichas:**

* Sólo evalúa **goles 2,5 y 1X2**, que son los únicos mercados con cuota en el
  ledger. En producción la regla mira además córners, tarjetas, la escalera
  entera de goles y la doble oportunidad, que no se pueden reconstruir hacia
  atrás porque su precio no está guardado. Esta tabla mide la REGLA, no todo el
  catálogo.
* n = 2.947 frente a los 44.000 de las otras políticas: el intervalo es más
  ancho, y por eso se mira el p5 de bootstrap y no la media a secas.

### 21.10 Y un defecto que se anotó sin serlo

En la v170 quedó escrito que el smoke «muere con `RecursionError` dentro de
`streamlit.testing`». **No es cierto.** El proceso terminó con **exit 0**; lo que
se vio eran mensajes de cierre de un proceso MATADO por tiempo de espera —
«Exception ignored in: WeakSet…»— y no un fallo de la prueba. Los ~60
`st.expander` de la v167 no son el problema.

Queda escrito porque la conclusión equivocada llegó a anotarse como pendiente, y
un pendiente falso cuesta tiempo al siguiente que lo lea.
