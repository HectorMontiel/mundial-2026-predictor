# Filtro contextual de ponches — diagnóstico, simulación y diseño

Encargo: evitar falsos positivos como el de Detroit del 11/08/2026 añadiendo una
capa de contexto pre-partido a la regla 3 (ponches) sin tocar las cuatro reglas
de decisión.

**Resultado corto:** la capa hace falta y funciona, pero **no por el motivo que
decía el encargo**. La variable que falla no es el K% del rival —ya estaba en el
modelo y en ese partido valía 0,993, o sea nada— sino **cuántos bateadores
enfrenta el abridor**. Y el fallo tiene un culpable concreto y localizado:
los lanzadores que **alternan** abrir y relevar.

---

## 0. Tres premisas del encargo que los datos no sostienen

Antes de diseñar nada hay que corregirlas, porque una de ellas apuntaba la
solución al sitio equivocado. Todo verificado contra MLB StatsAPI, `gamePk`
824240.

| premisa del encargo | dato real |
|---|---|
| «Andrew Anderson» | **Drew Anderson**, id 623454 |
| «hizo 3 ponches» | **4 K** en 4.0 IP, 17 BF, 70 lanzamientos |
| «Cleveland es un equipo de alto contacto, K% bajo» | **K% 21,95 % frente al 22,10 % de la liga · factor 0,993 · puesto 17 de 30.** Es la media exacta |
| «Anderson promedia 5.0 IPGS» | **3,20 IP por apertura**, y sólo llevaba **3 aperturas** en 41 apariciones |

El ajuste por K% del rival **ya existe** en `beisbol_pitchers.ponches_esperados`
(acotado a ±25 %). En este partido multiplicó por 0,9932. Un filtro construido
sobre esa variable no habría cambiado la decisión.

Los equipos que de verdad son de contacto en 2026 son Tampa Bay (18,83 %),
Arizona (19,16 %) y Toronto (19,58 %). Cleveland no está entre ellos.

---

## 1. Qué falló de verdad

Drew Anderson es un **alternante**: 41 apariciones, 3 de ellas aperturas. El
modelo estima los bateadores por apertura como `BF_temporada / aperturas`:

```
289 BF / 3 aperturas = 96,3 bateadores por apertura
```

Eso dispara la guarda que el propio proyecto puso al medir este mismo problema
(tope 28,5 en `_bf_por_apertura`), y entonces **cae a la media de la liga:
23,5 bateadores**. Sus aperturas reales promediaban **14,33**. Enfrentó 17.

```
λ = K/BF × BF_apertura × ajuste_rival
  = 0,2699 × 23,50 × 0,9932 = 6,30       →  P(K > 5.5) = 60,1 %
```

Esa es la reconstrucción del número que se vio en pantalla (63 %; la diferencia
son el factor de parque y el corte de la foto de estadísticas). **No es un
modelo que ignore el contexto: es un modelo al que se le entrega la duración de
otro lanzador.**

Y no es un descubrimiento nuevo: el comentario que documenta la guarda ya lista
el caso `Zach Agnos · por defecto 24,0 · real 14,2 · gs=2`. El problema estaba
visto y la corrección se quedó a medias — se acotó el disparate, pero el
sustituto (la media de la liga) sigue siendo el ancla equivocada para quien no
es abridor.

### Lo que NO está roto

La probabilidad **no está inflada en general**. Está medido: la Poisson promete
54,2 % y se cumple el 54,9 % sobre **3.759 evaluaciones fuera de muestra**, y
los ponches por apertura están **subdispersos** (varianza/media 0,78), no
sobredispersos. Un filtro genérico contra «probabilidades infladas» atacaría un
problema que no existe. El sesgo es **condicional**, y hay que atacarlo donde
está.

---

## 2. Simulación obligatoria — el caso Anderson

Estimando **sólo con lo anterior al partido** (nada de mirar el resultado):

| | λ | BF supuestos | P(K > 5.5) | P(K > 3.5) | decisión |
|---|---|---|---|---|---|
| **desplegado** | 6,30 | 23,5 (media de liga) | **60,1 %** | 87,4 % | emite 5.5+ |
| **con filtro** | 4,32 | 16,1 (suyos + papel) | **26,6 %** | **62,6 %** | **bloquea 5.5+**, sugiere 3.5+ |

**Resultado real: 4 K en 17 BF.**

- `más de 5.5` → **pierde**. El filtro la había **bloqueado** (26,6 % < 50 %).
- `más de 3.5` → **gana**. El filtro la había **sugerido** (62,6 %).

La simulación pasa. La etiqueta que saldría en la app sería:

> **Probabilidad ajustada al contexto: 27 % (no recomendado).**
> La línea segura es 3.5+ con 63 %.

(No 41 % / 78 % como decía el encargo: ésos eran números de ejemplo. Los reales
son 27 % y 63 %.)

### El caso honesto: su salida anterior

El mismo filtro, aplicado a su apertura del **05/08/2026**:

| | λ | P(K > 5.5) | P(K > 3.5) | real |
|---|---|---|---|---|
| desplegado | 6,88 | 68,4 % | — | **0 K** |
| con filtro | 4,83 | 35,4 % | 71,0 % | **0 K** |

El filtro **también** habría bloqueado el 5.5+ (bien: el desplegado prometía
68 % y salieron cero ponches). Pero su alternativa 3.5+ **también habría
perdido**. De dos aperturas, la línea alternativa gana una y pierde otra. Un
caso no demuestra nada; por eso está la sección siguiente.

---

## 3. Backtest — 2.970 aperturas fuera de muestra

Temporada 2026 completa, ~220 lanzadores con 3+ aperturas. Cada apertura se
estima **en orden cronológico y sólo con lo anterior a ella**. Tres estimadores
del BF por apertura:

- **A · DESPLEGADO** — `BF_temporada/GS` con tope y caída a la media de la liga.
- **B · APERTURAS** — media de sus aperturas reales, encogida hacia la liga.
- **C · APERTURAS + PAPEL** — igual, pero encogida hacia el ancla de su papel
  (17,0 bateadores si alterna, 23,5 si es abridor puro).

### Sesgo y error

| grupo | método | sesgo λ−K | MAE λ | sesgo BF |
|---|---|---|---|---|
| **alternantes** (n=159) | DESPLEGADO | **+1,365** | 2,312 | **+5,80** |
| | aperturas | +0,750 | 1,968 | +2,97 |
| | **ap.+papel** | **−0,036** | **1,744** | **−0,68** |
| **abridores puros** (n=2.811) | DESPLEGADO | +0,212 | 1,864 | +0,52 |
| | **ap.+papel** | +0,171 | 1,858 | +0,31 |
| **todas** (n=2.970) | DESPLEGADO | +0,274 | 1,888 | +0,80 |
| | **ap.+papel** | +0,160 | 1,851 | +0,25 |

**Es cirugía, no reforma.** En los 2.811 abridores puros el cambio es
irrelevante (+0,212 → +0,171). Todo el efecto está en los 159 alternantes,
donde el sesgo de bateadores pasa de **+5,80 a −0,68** y el MAE cae un 24,6 %.

### ¿Aguanta el bootstrap?

Es la regla de oro del proyecto, así que se aplica aquí también:

| grupo | mejora de MAE (A−C) | p5 bootstrap |
|---|---|---|
| alternantes (n=159) | +0,568 K | **+0,389** |
| todas (n=2.970) | +0,037 K | **+0,026** |

Positivo en el percentil 5 en los dos casos. La mejora no es una racha.

### Calibración

Brecha entre lo que promete P(over) y lo que se cumple:

| línea | DESPLEGADO | ap.+papel |
|---|---|---|
| 3.5 | +2,5 pp | **+0,7 pp** |
| 4.5 | +3,1 pp | **+1,2 pp** |
| 5.5 | +3,6 pp | **+1,9 pp** |
| 6.5 | +3,3 pp | **+2,0 pp** |

Mejora en las cuatro. Sigue sobrando algo de optimismo (+1,9 pp en 5.5), o sea
que queda trabajo — pero menos de la mitad del que había.

### Lo que decide: las apuestas bloqueadas

«Bloqueada» = el sistema actual la emite (P ≥ 50 %) y el filtro no.

| línea | emite hoy | acierta | emite con filtro | acierta | **bloqueadas** | **acertaban** |
|---|---|---|---|---|---|---|
| 3.5 | 2.620 | 71,9 % | 2.524 | **73,1 %** | 96 | **39,6 %** |
| 4.5 | 1.898 | 62,2 % | 1.778 | **63,7 %** | 121 | **38,8 %** |
| 5.5 | 1.011 | 54,3 % | 937 | **56,4 %** | 74 | **28,4 %** |
| 6.5 | 345 | 47,2 % | 325 | 48,0 % | 20 | 35,0 % |

**Lo que el filtro tira acertaba el 28,4 % en la línea de 5.5, contra el 54,3 %
del conjunto.** Está quitando perdedoras, no recortando al azar. Y añade
prácticamente nada (1 apuesta nueva en total): es un filtro, no un generador.

### Advertencia sobre el ROI

El backtest calcula también un ROI a **cuota fija 1,90**, y sale muy bonito
(+7,07 % en la línea 5.5, +38,96 % en la 3.5). **Ese número no es una promesa y
no debe citarse.** Nadie paga 1,90 por un «más de 3.5» que el mercado también ve
al 73 % — lo pagaría a ~1,25. El proyecto **no tiene histórico de precios de
props**, así que el ROI real de esta capa es desconocido. Lo que sí está medido
y sí se sostiene es lo de arriba: sesgo, MAE, calibración y acierto.

---

## 4. Método elegido, y por qué no es XGBoost

**Elegido: corregir la entrada y anclar por papel. Sin modelo aprendido.**

```
aperturas_previas = gameLog filtrado a gamesStarted == 1     (fuera de muestra)
bf_propio         = media de BF en esas aperturas
alternante        = aperturas < 50 % de sus apariciones
ancla             = 17,0 si alternante · 23,5 si abridor puro
bf_apertura       = (bf_propio × n + ancla × 6) / (n + 6)      ← encogimiento
λ                 = K/BF × bf_apertura × (K%_rival / K%_liga, acotado ±25 %)
P(K > línea)      = Poisson.sf(⌊línea⌋, λ)
```

Justificación frente a las alternativas que pedías evaluar:

| opción | veredicto |
|---|---|
| **heurística sobre la entrada** (ésta) | El sesgo se explica **por una sola variable**: `bf_apertura`, +5,80 bateadores en el subgrupo. Corregirlo lo lleva a −0,68. Coste: cero entrenamiento, cero peticiones nuevas, cero artefactos que versionar. **Recomendada.** |
| **regresión logística ligera** | Tiene sentido **después**, sobre lo que quede. Hoy el residuo en alternantes es −0,036 K: no hay casi nada que aprender ahí. En abridores puros queda +0,171 K, y ése sí es un objetivo razonable para una logística sobre BB% y carga de trabajo. **Segunda fase, y sólo si la medición lo justifica.** |
| **XGBoost / ensemble** | 2.970 filas y 4 variables no piden un ensemble; piden una entrada correcta. Y este proyecto ya tiene la lección cara: el máximo de un barrido de configuraciones (+10,09 % de p5) se hundió a −9,44 % fuera de muestra. Añadir capacidad donde el error es de entrada es la forma más fiable de sobreajustar. **Descartado por ahora.** |

**La Poisson se queda.** Está medida como bien calibrada y los ponches están
subdispersos, así que cambiarla por una binomial negativa —que añade varianza—
iría en el sentido contrario al dato.

### Sobre BB% y carga de trabajo

No las he medido por separado, y no voy a afirmar que aporten. Lo que sé es que
**una vez corregido el BF, el sesgo en alternantes es −0,036 K**, o sea que
apenas queda hueco donde puedan entrar. Su sitio natural es el residuo de los
abridores puros (+0,171 K). Es la siguiente medición, no una conclusión.

---

## 5. Arquitectura — dónde encaja sin tocar las cuatro reglas

Las reglas 1-4 de `beisbol_pitchers.veredicto()` **no se tocan**. El filtro vive
más abajo, en el cálculo de λ, así que la cascada de decisión sigue siendo
idéntica: lo único que cambia es que la regla 3 recibe una probabilidad que no
miente.

```
   veredicto()                        ← INTACTA (reglas 1,2,3,4)
       │
       ├─ perfil_pitcher(pid)         ← aquí entra el módulo nuevo
       │      └─ contexto_ponches.bf_por_apertura(pid)
       │             · gameLog → sólo gamesStarted == 1
       │             · ancla por papel (alternante / abridor puro)
       │             · encogimiento con n aperturas
       │             · si no hay gameLog → cae a _bf_por_apertura de siempre
       │
       ├─ ponches_esperados()         ← sin cambios (ya aplica K% del rival)
       └─ prob_over_ponches()         ← sin cambios (Poisson calibrada)
```

Módulo nuevo: **`contexto_ponches.py`**, independiente y con caída limpia. Si
StatsAPI no responde, devuelve `None` y el sistema se comporta exactamente como
hoy. Ninguna regla puede romperse por esto.

### La decisión de bloqueo

En la regla 3, con la probabilidad ya ajustada:

1. Si `P_ajustada(línea ofrecida) < umbral` → **bloquear** y buscar la línea
   alternativa más baja que sí lo supere (3.5, 2.5…), enseñando las dos cifras.
2. Si ninguna línea lo supera → el partido no entra por ponches, y sigue la
   cascada normal (regla 2, run line).

**El umbral no debe ser un 50 % fijo, y el backtest lo demuestra:** en la línea
de 6.5, exigir P ≥ 50 % emite 325 apuestas que aciertan el **48,0 %** — o sea,
perdedoras aunque pasen el umbral. El umbral correcto es **contra el precio**:

```
exigir   P_ajustada > (1 / cuota_ofrecida) + margen
```

y `props_ponches()` ya baja esas cuotas de Pinnacle sin coste ni clave, así que
el dato está disponible en el mismo sitio donde se decide. El 50 % del encargo
sirve como suelo mínimo adicional, no como criterio único.

---

## 6. Fuentes de datos evaluadas

| fuente | qué aporta | coste / frecuencia | pegas | veredicto |
|---|---|---|---|---|
| **MLB StatsAPI** (`statsapi.mlb.com`) | `gameLog` con `gamesStarted`, `battersFaced`, `strikeOuts`, `baseOnBalls` **por partido** — exactamente la variable que falta | **gratis, sin clave**, en vivo | el `gameLog` no trae lanzamientos (llegan a 0); hay que ir al boxscore del partido si se quiere carga de trabajo | **RECOMENDADA.** Ya la usan cuatro módulos del proyecto |
| **Baseball Savant / Statcast** | pitch-level: velocidad, whiff%, movimiento | gratis, CSV, actualización con horas de retraso | descargas grandes; **no aporta la variable que falla**; añade una dependencia nueva para nada | descartada de momento |
| **Fangraphs** (scraping) | métricas derivadas ya calculadas | gratis pero por raspado | sus condiciones de uso prohíben el scraping automatizado; y el proyecto ya arrastra la fragilidad de otros raspados | **no** |
| **Feeds de pago** (Sportradar y similares) | cobertura y SLA | de cientos a miles al mes | pagar por un dato que la API oficial publica gratis | **no** |

**Coste operativo real de la recomendación:** una petición de `gameLog` por
abridor y día (~30 al día en temporada completa), cacheable 6 h como el resto
del módulo. Cero euros y cero claves nuevas.

---

## 7. Plan de validación antes de desplegar

Lo de arriba ya cubre la mitad. Lo que falta para poder ponerlo en producción
con las reglas de este proyecto:

1. **Repetir el backtest sobre 2025 completo.** 2026 es el tramo con el que se
   ha elegido el ancla de 17,0; hace falta un tramo de juicio que no se haya
   usado para elegir. Sin p5 positivo ahí, no se despliega.
2. **Barrer el ancla del papel** (14, 16, 17, 18, 20) y comprobar que la mejora
   es una **superficie estable**, no un pico. Si sólo funciona en 17,0, es
   sobreajuste.
3. **Barrer el corte de «alternante»** (hoy: aperturas < 50 % de apariciones).
   Mismo criterio de estabilidad.
4. **Medir el umbral contra precio de verdad.** Empezar a fotografiar las cuotas
   de `props_ponches()` a diario: hoy no existe histórico de precios de props y
   sin él no se puede calcular ROI ni CLV de esta capa. Es la pieza que faltará
   más tiempo, y hasta tenerla no se puede prometer rentabilidad.
5. **Contraste en la app, no sólo en la función.** Comprobar que la etiqueta
   con la probabilidad ajustada y la línea alternativa aparece **en pantalla**,
   con AppTest o navegador. La lección más cara del proyecto es exactamente ésa.

### Métricas del plan, con los valores de referencia ya obtenidos

| métrica | hoy | con filtro | listón para desplegar |
|---|---|---|---|
| sesgo λ en alternantes | +1,365 K | −0,036 K | \|sesgo\| < 0,25 en el tramo de juicio |
| MAE λ en alternantes | 2,312 | 1,744 | mejora con p5 bootstrap > 0 |
| brecha de calibración en 5.5 | +3,6 pp | +1,9 pp | < +2,5 pp |
| acierto de lo emitido en 5.5 | 54,3 % | 56,4 % | por encima del punto muerto del precio real |
| daño a abridores puros | — | +0,212 → +0,171 | que no empeore |

---

## 8. Qué NO se ha demostrado

Por la regla del §0 de la bitácora, esto va escrito igual de grande que lo demás:

- **No se ha demostrado que esta capa gane dinero.** Se ha demostrado que
  predice mejor y que lo que bloquea eran perdedoras. Sin histórico de precios
  de props no hay ROI ni p5 de rentabilidad, y prometerlo sería exactamente lo
  que este proyecto lleva veinte versiones desmontando.
- **El ancla de 17,0 se eligió con los datos de 2026**, que son los mismos con
  los que se midió. Hasta repetirlo en 2025 es una estimación, no una
  validación.
- **La muestra de alternantes es pequeña**: 159 aperturas. La dirección es
  clara y el bootstrap aguanta, pero es un subgrupo, no una temporada.
- **La línea alternativa no es un salvavidas.** En las dos aperturas de Anderson
  del backtest, el 3.5+ gana una y pierde otra.
