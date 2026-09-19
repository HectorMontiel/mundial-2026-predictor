# Revisión de reglas heredadas — v212

**Regla de oro del encargo:** nada se cambia sin evidencia, pero nada se
conserva sólo por antigüedad.

Este documento revisa las 17 reglas del inventario (`AUDITORIA_v212.md` §1.2)
con tres preguntas: ¿sigue vigente? ¿se puede mejorar? ¿se puede eliminar?

**Resumen de la revisión: 0 reglas eliminadas, 2 generalizadas, 4 marcadas para
medición, 1 corregida.** Ninguna regla medida y positiva se ha tocado.

---

## A. Las tres intocables — confirmadas

El encargo las declara fuera de discusión sin nueva evidencia. Se ha
comprobado que la evidencia sigue ahí y que **se siguen llamando**, que es la
mitad que suele fallar.

### A.1 Ventaja de precio al lado local — VIGENTE, sin cambios

- **Evidencia:** p5 +1,73 % en el tramo de juicio. ROI +8,22 % en el tramo de
  ventaja 5-100 % contra −11,48 % en el tramo 0-5 %.
- **¿Se sigue llamando?** Sí: `clasificador.canal_del_pick` la aplica en cada
  barrido y es lo que puebla la Sección 1.
- **¿Umbrales medidos o arbitrarios?** Medidos. El 5 % no es cero y está
  justificado por el corte de ROI de arriba.
- **Veredicto:** no se toca. El Modo Seguridad v212 se construyó **en una
  sección aparte** precisamente para no contaminar este canal.

### A.2 EV del modelo como anti-indicador — VIGENTE, reforzada

- **Evidencia:** −4,66 % a −6,52 % sobre 37.158 apuestas.
- **Confirmación independiente en esta tanda:** el backtest v212 vuelve a
  verlo desde otro ángulo. La línea base de fútbol —apostar la selección de
  máxima probabilidad del modelo— da **ROI −4,82 % sobre 36.006 picks**, que
  cae de lleno en la banda medida hace versiones. La regla no ha caducado.
- **Veredicto:** no se toca.

### A.3 ECE por competición — VIGENTE

- **Evidencia:** Pearson −0,460 / Spearman −0,563 contra ROI real; 5,19 puntos
  de ROI entre el mejor y el peor cuartil sobre 14.647 patas.
- **¿Se sigue llamando?** Sí, y ahora **más**: la v209 lo enchufó a
  `auditoria_pick.riesgo_de_liga` y la v212 lo usa en el score de solidez del
  Modo Seguridad.
- **Veredicto:** no se toca.

---

## B. Reglas candidatas a cambio — revisadas una por una

### B.1 Tabla de riesgo por liga (IVL) — YA RESUELTA en la v209

- **Estado:** refutada por datos propios (Pearson −0,031 contra ROI). El orden
  que produce está invertido respecto a la intuición: la Premier League cae en
  el peor cuartil, Brasileirão B y Primera Nacional en la mejor mitad.
- **¿Eliminar?** No. Se **conserva como descriptor** («en esta liga se marcan
  pocos goles»), que es información real para una pata de Más de 2,5, y con la
  refutación viajando al lado en `auditoria_pick.TABLA_DEL_ENCARGO`.
- **Veredicto:** sin cambios en la v212. Ya está donde debe.

### B.2 Rebote por entrenador nuevo — VERIFICADA: dispara de verdad

El encargo pide explícitamente «verificar que dispara de verdad». Se ha hecho,
y el resultado tiene dos mitades:

- **La fuente funciona.** Wikidata devuelve cambios reales: 8 en la ventana de
  7 días del 2026-09-18 (Bologna, Lens, Hannover 96, Ecuador…).
- **La regla dispara de punta a punta.** Verificado con un caso real: Bologna
  cambió de entrenador el 2026-09-16; con Inter favorito a 1,55 (< 1,85) la
  bandera se enciende a 2 días. Hay test en la suite.
- **Pero el efecto sigue sin medirse.** Que el rebote EXISTA es una creencia
  razonable que este proyecto no ha medido nunca. El 0,15 de penalización es
  un número puesto a mano.
- **Veredicto:** se mantiene **como aviso, sin tocar probabilidad**, que es
  como está. Pasa a la lista de medición (sección D).

### B.3 Acumulación de reglas con `medido: False`

El encargo señala esto como categoría de riesgo, y con razón: la v209 añadió
cuatro de golpe. El recuento tras esta revisión:

| regla | efecto real hoy | riesgo de acumulación |
|---|---|---|
| Divergencia extrema | recorta confianza 20 % | bajo: no toca probabilidad |
| Cuota inflada | recorta confianza 30 % | bajo |
| Racha negativa | sólo avisa | ninguno |
| Rebote entrenador | sólo avisa | ninguno |
| Tope 2 patas/partido | bloquea patas | medio: sí cambia el boleto |

**La decisión de diseño que contiene el riesgo:** ninguna de las cuatro
primeras toca una probabilidad. Recortan un escalar de confianza y encienden
una bandera. El único que decide algo es el tope de patas, y es una restricción
de sentido común sobre correlación, no una predicción.

**Veredicto:** se mantienen, con la condición de que sigan sin tocar
probabilidad hasta que haya medición. Se añade un test que lo ata (ver §C.2).

---

## C. Lo que sí ha cambiado en esta revisión

### C.1 Generalización a más deportes (2 reglas)

| regla | antes | ahora |
|---|---|---|
| Correlación de patas | sólo fútbol, vía `match_parlay` sobre ids de campo | `auditoria_pick.patas_compatibles` trabaja sobre el vocabulario del barrido: vale para los 5 deportes |
| Contexto de partido | disperso y sólo fútbol | `scraper_contexto` registra proveedores **por deporte**: 6 en fútbol, 3 en NFL/MLB/tenis/KBO |

### C.2 Una corrección: el umbral de la confianza por canal

Encontrada al auditar picks reales, no por revisión de código. La confianza de
`auditoria_pick` subía con **cualquier** `canal` presente en el pick, incluido
`ev_del_modelo` — que es precisamente el canal refutado de A.2. Un pick con EV
−5,5 % se leía con confianza ALTA.

Corregido en la v209: sólo suben los tres canales con p5 positivo medido
(`CANALES_MEDIDOS`). Es un caso de libro de regla heredada aplicada más allá de
su evidencia.

### C.3 Un error de especificación del encargo, parametrizado en vez de elegido

La Fuente 3 del motor de escalada dice: «si `media_5 >= linea_superior + 0.5` y
`xG_5 >= linea_superior` → fuerte». Su propio ejemplo (Barcelona-Getafe) escala
a Más de 3,5 con media 3,4 y xG 3,1 y lo llama fuerte, pero con
`linea_superior = 3,5` la regla exige 4,0 y 3,5: **el ejemplo no cumple su
propia regla**. Con la línea BASE como referencia sí cuadra.

No se ha elegido a ojo: `escalada_lineas.REFERENCIA_FORMA` admite las dos
lecturas y el backtest mide ambas. (En esta tanda dan el mismo conjunto de
picks, porque la fuente de forma queda tapada por la falta de xG observado.)

---

## D. Reglas que no se pueden eliminar todavía, y qué falta para decidirlo

El encargo dice: «si nadie la llama y nadie la mide, se elimina con test de
regresión». Ninguna de las reglas activas cumple las dos condiciones —todas se
llaman— así que **no se ha eliminado ninguna**. Lo que sí se puede hacer es
decir exactamente qué falta para poder decidir:

| regla | qué falta para medirla |
|---|---|
| Divergencia extrema > 15 pp | ledger que guarde la bandera EN EL MOMENTO del pick, y ~1.000 picks con ella |
| Cuota inflada ratio > 1,30 | lo mismo |
| Racha negativa ≥ 5 | lo mismo; es la más barata, la racha es reconstruible hacia atrás |
| Rebote por entrenador | histórico de destituciones cruzado con resultados posteriores. Wikidata da la fecha, así que **esto sí es reconstruible hacia atrás** y es la primera que debería medirse |
| Umbral 0,22 del Brier | barrido del umbral contra ROI real; hoy es una convención de la v32 |

**Nota sobre el orden:** el rebote por entrenador es el candidato más maduro.
La fuente da fechas históricas, el ledger tiene resultados, y la regla ya está
escrita y enchufada. Es medible sin construir nada nuevo.

---

## E. Módulos escritos y sin enchufar — NO se han tocado

La auditoría encontró dos casos del mismo patrón que la v209 resolvió con
`filtro_contexto`:

- **`ventaja_ponches`** (267 líneas, v132) — decide la escalera de ponches por
  ventaja de precio, el criterio A.1. Correcto y desconectado.
- **`historico_agrupado`** (144 líneas, v184) — arregla el 1X2 de equipos de
  copa que salen con `prob: None`.

**No se han enchufado en esta tanda**, y es deliberado: los dos cambian qué
picks salen o qué probabilidad se emite, y el encargo prohíbe tocar el núcleo
predictivo sin su propia medición. Quedan como decisión abierta en
`AUDITORIA_v212.md` §1.5, documentados y con test de regresión pendiente —que
es lo que el §10.1 del encargo pide: «se documenta, se decide, no se borra sin
test de regresión».
