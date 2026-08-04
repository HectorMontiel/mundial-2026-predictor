# VALIDACION v95 — La fecha de 1970, y hablar como el que lee

Fecha: 2026-08-04 · Suites: test_catalogo_y_cuotas ✅ · test_simetria ✅ ·
test_match_parlay ✅ · smoke_botones ✅ · test_concurrencia ✅ (TODO OK las 5)

Tres cosas: un bug que ya había «arreglado» y volvió, 182 partidos que la app
no sabía clasificar, y unos mensajes que hablaban para el que los escribió.

---

## 1. La fecha de 1970 — arreglada donde debía estarlo

**Síntoma**: tarjetas de MLB con `📅 Hoy · 1970-01-01`.

**Y es el mismo bug de la v94.** Allí salió en la vista de tenis y lo corregí
**en el consumidor**; volvió a aparecer en MLB porque cada consumidor parsea la
fecha por su cuenta y hay tres formatos distintos:

```
Pinnacle  '2026-08-03T21:30:00Z'   ISO con zona
Bovada     1785781800000            milisegundos epoch
Playdoit  '2026-08-03T21:30:00'    ISO sin zona
```

`pd.to_datetime` interpreta un entero como **nanosegundos**, así que el epoch
de Bovada se leía como 1970-01-01. Con tres casas y media docena de
consumidores, parchear caso por caso es garantizar que reaparezca en el
siguiente. La lección es la que el propio proyecto aplica en otras capas: se
normaliza **donde el dato entra al sistema**.

`cuotas_multi.fecha_normalizada()` es ahora el único sitio que convierte, y los
tres índices la usan al construirse. Verificado con los cinco formatos y con
basura:

```
1785781800000        → 2026-08-03T18:30:00
1785781800           → 2026-08-03T18:30:00
'2026-08-03T21:30:00Z' → 2026-08-03T21:30:00
None / '' / 'basura' / 0 / -1 / True → None
```

Una fecha fuera de [2000, 2100] se trata como ausente: **es preferible no
mostrar fecha a mostrar 1970**. Y en la UI queda una última guardia que imprime
«Fecha no disponible» si algo se colara por una vía futura.

El test de regresión comprueba las dos mitades: que la conversión funcione y
que **ningún índice pueda volver a guardar la fecha en crudo**.

## 2. «Todo debe tener un modelo» — 41 % → 77 %, y lo que no se puede

Salían **182 partidos** de tenis como «con cuota, sin modelo propio». Medido de
dónde vienen:

```
partidos de tenis con cuota    307
  con modelo                   125   (41 %)
  sin modelo                   182   ← casi todos ITF
```

Investigado por qué, y el reparto del histórico lo explica:

```
ATP · histórico unificado   75.004 partidos
  circuito principal        58.941
  Grand Slams               14.838
  challenger_atp             1.225   ← apenas cubierto
  ITF                            0   ← nada
```

**Lo que sí se puede arreglar: los challengers.** El scoreboard de ESPN los
cubre — medido sobre 15 días: **785 partidos, 13 torneos, 488 jugadores**,
entre ellos Iasi, Praga, Memphis y VanOpen. Ese material existe y es gratis; lo
que faltaba era **guardarlo**, porque ESPN sólo sirve una ventana reciente y lo
que no se acumula se pierde. Nuevo `acumular_tenis.py`, en el workflow diario,
con la misma disciplina que las fotos de cuotas (CSV commiteado, idempotente).
Primera ejecución: **616 partidos y 488 jugadores** guardados. El catálogo
crecerá solo en cada reentrenamiento.

**Lo que NO se puede: el ITF.** Ese mismo scoreboard devuelve **0 partidos de
ITF**. Sin resultados no hay entrenamiento, y sin modelo lo único que se podía
enseñar era la probabilidad implícita del precio — o sea, repetirle al usuario
lo que ya dice la casa, con la etiqueta «no tenemos modelo» repetida 182 veces.
**Se excluye el circuito del barrido**: mejor no ofrecerlo que ofrecerlo vacío.

Y de paso, fuera las **cuotas que no son apuestas**: el tablón publica precios
de 1.00 y 1.01 en favoritos extremos, que llegaban a la interfaz como
«prob 96 %, EV +0,0 %» — parece una oportunidad y no lo es. Una cuota de 1.00
devuelve el importe y nada más.

```
                 antes    después
partidos          307         88
con modelo        125 (41 %)  68 (77 %)
sin modelo        182         20   ← challengers, se cubrirán al acumular
```

## 3. Mensajes: hablar para el que lee, no para el que escribió

El texto de la Capa 2 decía:

> «…normalmente la cuota es menor que el mínimo de 1.50, que es el guardarraíl
> contra la sobreconfianza documentada en v71…»

Tres problemas: cita una versión interna que al usuario no le dice nada, esa
referencia además quedó desactualizada, y explica el mecanismo en vez de lo que
importa. Ahora:

> «Partidos donde el modelo está muy seguro pero que **no recomendamos jugar
> sueltos**: 27 tienen una cuota tan baja que apenas compensa el riesgo, y el
> resto todavía no tiene precio. Sirven para combinar.»

Reescritos **14 mensajes** con el mismo criterio: breve, sin jerga, y
explicando la consecuencia para quien apuesta. Ejemplos:

| antes | ahora |
|---|---|
| «no entran solas en el Plan de Ataque… concentra varianza… ¼ de Kelly, v81» | «basta con fallar una pata para perderlo todo: gana menos veces de las que parece» |
| «Techo liga = cuánto acierta el CIERRE DEL MERCADO… (v90, 26.666 partidos)» | «cuánto acierta ahí la mejor casa del mundo; es el máximo que logra nadie» |
| «los EV por encima de +15 % son la zona que el backtest v32 marcó poco fiable» | «un valor esperado por encima de +15 % suele significar que la probabilidad está mal calculada, no que haya una ganga» |
| «Rentabilidad y CLV (motor v38)» | «Rentabilidad y calidad del precio» |

El test lo fija recorriendo el AST y comprobando que **ninguna cadena viva**
—excluyendo comentarios y docstrings, donde las referencias sí son útiles—
cite una versión interna. Encontró **4 que se me habían escapado** después de
la primera pasada, que es exactamente para lo que sirve.

## 4. Qué queda abierto

- **Los 20 partidos de challenger sin modelo** se irán cubriendo conforme
  `acumular_tenis` acumule y el reentrenamiento amplíe el catálogo.
- **ITF**: sin fuente gratuita de resultados. Si aparece una, el circuito
  vuelve solo (basta con quitar el filtro y acumular).
- Backtest de line shopping en Goles/BTTS y las 11 ligas sin cuotas: siguen
  esperando volumen, acumulándose solos.
