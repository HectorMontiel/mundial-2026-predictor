# Auditoría del proyecto — agosto 2026

Escrita después de recorrer el código a fondo en las v114-v115 (emparejador de
cuotas, tablón multi-casa, combinadas, paneles de equipo, selecciones, MLB).
No es una lista de buenas intenciones: cada punto lleva o una medición o una
línea de código concreta detrás, y está ordenada por **impacto ÷ riesgo**, que
es el único orden que sirve cuando hay más ideas que tiempo.

---

## Lo primero: qué es este proyecto de verdad

Conviene decirlo antes de proponer nada, porque cambia todas las prioridades.

El repo ha medido, con protocolo de elegir/juzgar y bootstrap, que:

| hallazgo | cifra |
|---|---|
| el modelo bate al mercado | **4 de 37 ligas** |
| apostar por su probabilidad | **−4,66 % a −6,52 %** (37.158 apuestas) |
| el EV que declara, contra el CLV | correlación **−0,054** (anti-indicador) |
| comprar al mejor precio, sin modelo | **+1,37 %** |
| line shopping en tramo de juicio | **+11,49 %**, p5 **+1,73 %** |

**La única ventaja demostrada del proyecto es el precio, no la predicción.** Y
sin embargo la mayor parte de la superficie de la app —y de estas propuestas,
si uno se descuida— gira alrededor del modelo.

Eso no significa tirar el modelo: significa que las mejoras de *precio* valen
más que las de *precisión*, y que cualquier pantalla que ordene por EV está
ordenando por el error del modelo.

---

## A. Aplicado en la v115

Lo que ya está hecho y medido, para no repetirlo abajo.

| | efecto medido |
|---|---|
| `bf_apertura` de MLB dejaba de contar relevos | sesgo +2,43 → +1,40 bateadores, error −41 % |
| líneas alternativas de Pinnacle, que se tiraban | 5 → 16-18 mercados con precio por partido |
| caché de `cuotas_partido` | 6,02 s → 0,000 s en 40 partidos |
| `name_mapper` deja de repetir el mismo aviso | de 200+ líneas de registro a una por caso |
| fixtures de selecciones desde el tablón | sobrevive al 403 de ESPN en producción |

---

## B. Alto impacto, riesgo bajo — hacer a continuación

### B1. Liquidar lo que se recomienda, y enseñarlo

**El agujero más grande del proyecto.** La app emite picks, combinadas,
veredictos de MLB y líneas de ponches, y **no cierra el círculo** salvo en el
ledger de fútbol. `liquidador.py` cubre fútbol, MLB y tenis, pero:

- las recomendaciones de **ponches** no se registran ni se liquidan;
- las **combinadas** propuestas tampoco;
- el usuario no tiene una pantalla que diga «de lo que te propuse el mes
  pasado, esto acertó».

Sin eso, ninguna afirmación sobre precisión se puede sostener, y el usuario
tiene razón cuando dice «solo uno de 5 se cumplió»: no hay forma de saber si
eso fue mala suerte o un sesgo, salvo auditando a mano como se hizo en la v115.

*Coste*: medio. *Riesgo*: bajo (sólo añade registro).
*Valor*: es la condición previa de todo lo demás.

### B2. Más casas, que es donde está el edge medido

Matchbook subió el mejor precio del 35,5 % al 36,5 % y bajó el margen 0,81
puntos. Cada casa nueva multiplica las oportunidades **sin tocar el modelo**.

Del sondeo de 41 candidatas quedaron pistas sin agotar:

- **Betfair vía API oficial** — el bloqueo es de red, no de cuenta. Con una IP
  no mexicana (o una cuenta en un país admitido) vuelve a estar disponible, y
  es el que más veces da el mejor precio en el histórico (35,4 %).
- **Polymarket** — margen 1,0000, pero sus nombres no casan con el tablón
  («Cruzeiro EC», «AFC Ajax»). Un mapa de alias específico lo abriría; el
  problema no es el acceso, es el emparejado.
- **Casas mexicanas con web JS** (Caliente, Codere, Strendus) — necesitan
  navegador headless. Coste alto y mantenimiento frágil; sólo si el usuario
  apuesta ahí de verdad.

*Coste*: bajo por casa. *Riesgo*: bajo. *Valor*: directo sobre lo único medido.

### B3. Un precio que no se puede tomar no es un precio

`CASA_PRIORITARIA = 'Playdoit'` existe, pero el tablón sigue enseñando como
«mejor precio» cuotas de casas donde el usuario quizá no tenga cuenta —
incluido un exchange con requisitos propios.

Propuesta: que el usuario marque **en qué casas tiene cuenta**, y que el line
shopping distinga «mejor precio del mercado» (referencia) de «mejor precio que
TÚ puedes tomar» (accionable). Es un cambio pequeño con efecto directo sobre la
utilidad de cada recomendación.

*Coste*: bajo. *Riesgo*: nulo. *Valor*: alto.

### B4. Ordenar por line shopping, no por EV

Ya se hace en la recomendación de combinadas (v115), pero **no** en la tabla de
mercados ni en Apuestas del Día, que siguen ordenando por EV — es decir, por el
error del modelo. El ejemplo real: «Menos de 1.5 goles @ 5,40, EV +118,7 %»
aparecía arriba del todo, y no es una oportunidad: es el modelo equivocándose
contra Pinnacle.

Propuesta: ordenar por **ventaja sobre las otras casas** y dejar el EV como
columna informativa, marcada cuando sea implausible.

*Coste*: bajo. *Riesgo*: bajo. *Valor*: alto — cambia qué se apuesta.

---

## C. UX/UI — lo que el usuario ve

La app es funcionalmente rica y visualmente plana: Streamlit por defecto,
mucho texto, muchos desplegables anidados. Cinco cambios que cambiarían la
experiencia sin tocar la lógica.

### C1. Un encabezado que responda «¿qué hago hoy?»

Hoy hay que leer mucho antes de saber si merece la pena abrir la app. Propuesta:
una franja fija arriba con cuatro cifras — partidos con cuota hoy, picks que
pasan el filtro, mejor diferencia de precio detectada, y estado de las fuentes.

### C2. Jerarquía visual y tema propio

Tarjetas con color según la acción (verde = accionable, ámbar = mirar, gris =
informativo), tipografía y espaciado consistentes, y CSS propio en
`.streamlit/config.toml` + un bloque de estilos. La app tiene cinco años de
funciones amontonadas y ninguna gramática visual.

### C3. Los avisos, una vez

El aviso de «el EV es anti-indicador» aparece ya en cuatro sitios distintos. Un
aviso que se repite se deja de leer. Propuesta: un banner de contexto que se
pueda plegar, y en las tarjetas sólo el icono con tooltip.

### C4. Buscador global de partido/equipo

Con 50 competiciones, llegar a un partido concreto exige saber en qué liga
está. Un buscador único («Monterrey») que lleve directo es probablemente la
mejora de navegación más grande por línea de código.

### C5. Móvil de verdad

Se ha trabajado (v23), pero las tablas de 8-10 columnas —las de mercados, la
clasificación— siguen sin caber. Propuesta: en móvil, tarjetas apiladas en vez
de tablas, y las tablas anchas en un contenedor con scroll horizontal propio.

---

## D. Modelo y precisión — con la advertencia de arriba

### D1. Calibrar antes que complicar

La v115 encontró que la Poisson de ponches estaba **bien** calibrada y el sesgo
venía de un dato de entrada. Es muy probable que pase lo mismo en otros sitios:
antes de cambiar familias de modelo, medir la calibración de lo que ya hay.

Concretamente, sin medir todavía: la probabilidad de córners y tarjetas (que
alimenta muchas patas de combinada), y el marcador exacto.

### D2. El encogimiento hacia el mercado, donde falta

El proyecto ya encoge hacia Pinnacle en fútbol y midió que sin eso el edge
desaparece (p5 −1,11 % contra +1,02 %). MLB, NBA, KBO y tenis **no** lo hacen
de forma sistemática. Es la corrección con más respaldo empírico del repo.

### D3. Dejar de prometer EV donde no lo hay

Con cuota justa, el EV de toda pata vale 0 por construcción, y la app lo enseña
igual. Propuesta: no mostrar EV cuando la cuota es justa — mostrar sólo
probabilidad. Un cero disfrazado de dato es peor que un hueco.

---

## E. Deuda técnica

| | |
|---|---|
| `dashboard_ui.py` pasa de 5.000 líneas | partirlo por vista; hoy cualquier cambio arriesga todo |
| 190 scripts `_vNNN_*.py` en la raíz | mover a `estudios/`; son el historial de mediciones y valen, pero estorban |
| Los tests son un script de 3.400 líneas con `check()` | funciona y es honesto, pero sin pytest no hay ejecución selectiva ni CI por partes |
| `alias_manuales.json` se llena a mano | `nombres_sin_mapear.json` ya registra los fallos; falta el paso que proponga los alias |

---

## Orden sugerido

1. **B1** (liquidar y enseñar) — sin esto, lo demás se decide a ciegas.
2. **B4 + B3** (ordenar por precio, y por precio accionable) — barato y cambia qué se apuesta.
3. **C1 + C3** (encabezado y avisos) — la app se vuelve usable de un vistazo.
4. **B2** (más casas) — el edge medido, una casa cada vez.
5. **D2** (encogimiento en los otros deportes) — la corrección con más respaldo.
6. **C2/C4/C5**, **D1**, **E** — cuando lo anterior esté cerrado.

## Lo que NO propongo

- **Más features del modelo.** La v112 rechazó una señal que batía al mercado
  con z=8,6 porque el ROI en juicio era −2,21 %. Añadir variables a un modelo
  que ya se sabe que no decide bien es optimizar lo que se midió que no importa.
- **Prometer que se romperá el mercado.** No hay nada en estos datos que lo
  sostenga, y la app no debe insinuarlo.
