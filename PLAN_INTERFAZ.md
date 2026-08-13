# Rediseño de la interfaz — arquitectura, alternativas y decisiones

Encargo: que la app se pueda navegar, que en menos de diez segundos se vea qué
jugar, y que Telegram siga intacto.

---

## 0. La tensión de diseño que hay que resolver primero

El encargo pide organizar la pantalla **por deporte** (`⚽ Fútbol`, `⚾ MLB/KBO`,
`🎾 Tenis`) y, en otra pestaña aparte, `🎯 Candidatos y Secciones`.

Eso invierte la jerarquía que el proyecto acaba de construir y medir. La tesis
del §0 de la bitácora es que **el deporte no decide nada**: lo que decide es el
canal, y sólo dos tienen p5 positivo —precio al local en fútbol y tenis ≥ 90 %—.
Si el primer corte es por deporte, la pestaña `🎾 Tenis` mezcla el único canal
rentable del proyecto con los 40 favoritos de ITF que están medidos en −4,9 %, y
la distinción que costó dos versiones se diluye.

**Propuesta:** el primer nivel sigue siendo **qué jugar**; el deporte pasa a ser
un **filtro**, no una pestaña.

```
💎 APUESTAS DEL DÍA
┌──────────────────────────────────────────────────────────────┐
│  [ Todo ] [ ⚽ ] [ ⚾ ] [ 🏀 ] [ 🎾 ]      ← filtro, no pestaña │
├──────────────────────────────────────────────────────────────┤
│  ✅ PARA JUGAR (3)   🟡 SÓLO COMO PATA (28)   🧩 COMBINADAS   │
│  📋 TODOS LOS PARTIDOS (65)      ⚙️ ESTADO DEL SISTEMA        │
└──────────────────────────────────────────────────────────────┘
```

Cinco pestañas, no seis, y la primera responde la pregunta del usuario. El
filtro de deporte se aplica a **todas** a la vez y vive en `st.session_state`,
así que cambiar de pestaña no lo pierde.

Si aun así se prefiere el corte por deporte, se hace — pero quedaría dicho que
entierra la Sección 1.

---

## 1. Pestañas — tres opciones

| opción | pros | contras | veredicto |
|---|---|---|---|
| **`st.tabs` nativo** | cero dependencias; accesible; el contenido de las no visibles **no se ejecuta** hasta que se abren | el estado de pestaña no es leíble desde Python | **recomendada** |
| HTML/CSS + `st.session_state` | control total del aspecto; se sabe qué pestaña está activa | cada clic es un `rerun` completo → con el barrido detrás, segundos de espera | no |
| `st.radio` horizontal | se sabe la pestaña activa; nativo | también rerun por clic; estéticamente pobre | sólo para el filtro de deporte |

**Decisión:** `st.tabs` para las secciones, `st.pills` / `st.radio` horizontal
para el filtro de deporte (ése sí necesita ser leíble desde Python).

**Rendimiento:** el barrido ya está cacheado por `guardia_barrido` (15 min) y no
se repite por pestaña. Lo que sí hay que cachear es el **armado de la tabla**
(`st.cache_data` sobre una función pura que recibe el barrido y devuelve el
DataFrame), porque hoy se reconstruye en cada rerun.

---

## 2. Tabla interactiva — la decisión ya está tomada por los hechos

Comprobado en la versión instalada (Streamlit 1.61.1):

```
st.dataframe → on_select: SÍ · selection_mode: SÍ · key: SÍ · column_config: SÍ
column_config → ProgressColumn, LinkColumn, BarChartColumn, MarkdownColumn…
```

| opción | pros | contras | veredicto |
|---|---|---|---|
| **`st.dataframe` con `on_select="rerun"`** | filas cliqueables **nativas**; barras de probabilidad con `ProgressColumn`; ordenable y filtrable de serie; responsive | el estilo lo pone Streamlit | **recomendada** |
| `st-aggrid` | más control | **no está instalado**; dependencia de terceros que se rompe entre versiones de Streamlit; ~1 MB de JS; en Cloud es un riesgo de despliegue | no |
| `st.table` con HTML incrustado | control total del color | no ordena, no filtra, no es cliqueable; y una tabla de 65 filas en HTML pesa | no |

**Columnas propuestas:**

| columna | tipo | qué muestra |
|---|---|---|
| Hora | texto | ya en CDMX |
| Liga | texto | |
| Partido | texto | favorito del modelo **en negrita** |
| Prob. | `ProgressColumn` | barra de la probabilidad del lado recomendado |
| Recomendación | `MarkdownColumn` | `✅ Gana X @ 1.95` / `🟡 sólo pata` / `❌ sin precio` |
| Sección | texto | `1`, `2` o `—` |

`on_select` devuelve el índice de la fila; con él se guarda el partido elegido
en `st.session_state` y se abre su ficha. **Sin dependencias nuevas.**

---

## 3. Colapsables

`st.expander` nativo, con una regla: **plegado por defecto todo lo que sea
contexto, desplegado lo que sea decisión.** El análisis H2H, las estadísticas de
los últimos ocho partidos y el comentario del analista van plegados; la
recomendación y su motivo, no.

Descartado `st.checkbox` a mano: reimplementa el expander con peor
accesibilidad y un rerun por clic.

---

## 4. El color deja de describir y pasa a mandar

Hoy el color dice **quién es local**. Eso es descriptivo y no ayuda a decidir.

| color | significa | icono |
|---|---|---|
| **verde** | esto es lo que se juega (Sección 1) | ✅ |
| **ámbar** | alta probabilidad, precio insuficiente; sólo como pata | 🟡 |
| **rojo atenuado** | EV negativo o sin precio con el que comparar | ❌ |

Un solo verde por fila como mucho. La paleta ya existe en `estilo_ui`
(`--ok`, `--mira`, `--no`), así que esto es reutilizar, no inventar.

**Accesibilidad:** el color nunca va solo — siempre lleva icono y texto, porque
un daltónico no distingue el verde del ámbar y porque en el móvil, a pleno sol,
tampoco lo distingue nadie.

---

## 5. Navegación al partido

`on_select` sobre la tabla → se guarda `(clave_liga, home, away)` en
`st.session_state` → la app cambia el selector de competición y preselecciona el
partido. No se recarga la sesión ni se pierde el barrido, que está en el guardia
de proceso y no en el estado de sesión.

Alternativa evaluada y descartada: `st.dialog` (modal). Cabe poco, y la ficha de
partido tiene tablón de casas, secciones y combinadas — en un modal, y en un
móvil, no se lee.

---

## 6. Telegram

**No se toca.** `bot_telegram.construir_mensaje(r)` recibe el barrido ya
calculado y no depende de la interfaz. El botón sigue donde está, arriba y fijo.
La validación consiste en comprobar que el botón sigue existiendo y que su
pulsación no lanza excepción — que es justo lo que hace `smoke_botones.py`, y
por eso esta reestructuración no se sube sin pasarlo.

---

## 7. Riesgo principal, y cómo se mide

El riesgo no es estético: es que **la reorganización rompa un botón** que hoy
funciona. La vista de Apuestas del Día tiene 67 botones contados por el smoke.

Plan de validación:

1. `smoke_botones.py` — que las 7 vistas carguen y sus botones respondan.
2. Render con AppTest — buscar **el texto** de cada pestaña nueva en pantalla,
   no que la función devuelva algo.
3. Comprobación explícita de que «📤 Enviar a Telegram ahora» sigue presente y
   pulsable.
4. Navegador real a 375 px: que las pestañas no desborden y la tabla haga
   scroll horizontal dentro de su caja, no la página entera.

---

## 8. Orden de implementación

1. Filtro de deporte + las cinco pestañas (esqueleto, sin tocar contenidos).
2. Mover cada bloque existente a su pestaña, sin cambiarlo.
3. Tabla interactiva con `on_select` y color prescriptivo.
4. Navegación al partido desde la tabla.
5. Colapsar los bloques de contexto.

Cada paso se valida antes del siguiente. Lo que no pase, no se sube.
