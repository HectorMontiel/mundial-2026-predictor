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
