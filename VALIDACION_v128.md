# Validación — la barra lateral en el móvil y la Sección 1 del día

Dos peticiones del usuario, medidas y cerradas por separado.

> 1. «La barra lateral no me sale en dispositivos móviles»
> 2. «Me sale que sólo 6 casas, ya quiero empezar a ver apuestas en capa 1 que
>    sí pueda ganar»

---

## 1. La barra lateral en el móvil

### No era la barra lateral

Era el CSS que oculta la marca de Streamlit. Decía, desde hace muchas
versiones:

```css
footer, [data-testid="stHeader"] { display: none !important; }
```

Streamlit 1.61 mete el botón de **abrir** la barra lateral dentro de esa
cabecera. Medido en el navegador, a 375 px de ancho, con el CSS anterior:

```
header[stHeader]                        -> display:none / visibility:hidden
  └ div[stToolbar]
      └ button[stExpandSidebarButton]   -> visibility:hidden · 0x0
```

En escritorio no se nota: la barra arranca desplegada y nadie la cierra. En el
teléfono la barra se abre **encima** del contenido, así que lo primero que hace
cualquiera es cerrarla para poder leer — y a partir de ahí no queda ningún
control en pantalla que la devuelva. Se pierden el modo Principiante/Pro, el
bankroll, el panel de créditos y la navegación entera hasta recargar la página.

### La comprobación, en el navegador de verdad

Repro mínimo a 375 px que inyecta **el mismo texto CSS** que la aplicación
(extraído del fichero, no copiado), abriendo y cerrando la barra:

| estado | antes | después |
|---|---|---|
| cabecera | `display:none / hidden` | `block`, fondo transparente, `pointer-events:none` |
| botón de abrir | `visibility:hidden` · **0x0** | `visible` · **28x28** en (18,16) |
| ¿recibe el toque? (`elementFromPoint`) | no existe | **sí, el botón** |
| ciclo abrir → cerrar → **volver a abrir** | imposible | `aria-expanded` true → false → **true** |
| menú, «Deploy» y widget de estado de Streamlit | ocultos | **siguen ocultos** |
| pie de página | oculto | **sigue oculto** |
| desplazamiento del contenido (`top` del `h1`) | 112 px | **112 px** |

La cabecera no se restaura: se hunde. Fondo transparente, sin sombra y sin
capturar toques, y está en `position: absolute`, así que no empuja nada — de
ahí que el contenido siga empezando exactamente donde empezaba. Lo único que
vuelve a existir es el botón de abrir la barra. La marca de Streamlit se oculta
ahora una por una (`stMainMenu`, `stAppDeployButton`, `stStatusWidget`,
`stToolbarActions`), que es lo que la regla quería hacer desde el principio.

En pantallas de menos de 768 px ese botón recibe fondo, borde y sombra propios,
porque flota sobre el contenido y como icono suelto no se lee como un control.

---

## 2. «Capa 1 que sí pueda ganar»

### El diagnóstico

«Apuestas del Día» repartía sus picks por el **EV del modelo**. Es exactamente
el criterio que la bitácora mide en **−4,66 % a −6,52 % sobre 37.158 apuestas**,
y cuyo EV declarado es anti-indicador del cierre (correlación −0,054). O sea:
la pantalla que se mira primero estaba ordenada por el peor criterio disponible,
mientras la vista de partido ya usaba el clasificador de tres secciones. El
mismo partido podía salir «de élite» en una pantalla y amarillo en la otra.

### Qué sube ahora a la Sección 1, y por qué sólo eso

El barrido del día no puede pagar un tablero por partido, así que no tiene
`dif_vs_consenso` fila a fila. Lo que sí tiene son **canales enteros ya
medidos**. Sólo dos cruzan el listón del proyecto —p5 de bootstrap positivo en
el tramo que no se usó para elegir—:

| canal | tramo de elección | tramo de juicio |
|---|---|---|
| **Precio al lado LOCAL** (fútbol) | n=1817 · +5,09 % · p5 **+1,09 %** | n=353 · +11,49 % · p5 **+1,73 %** |
| **Tenis con `prob ≥ 90 %`** y precio | — | n=1.793 · +5,76 % · p5 **+0,18 %** |

El desglose por lado del canal de precio, reproducido el 2026-08-12 sobre
`pick_ledger_total.csv` (`_v90_line_shopping_por_lado.py`, mismos números que
el JSON guardado):

| lado | pliegues 0-2 (elige) | pliegues 3-4 (juzga) | robusto |
|---|---|---|---|
| **local** | n=1817 · +5,09 % · p5 **+1,09 %** | n=353 · +11,49 % · p5 **+1,73 %** | **SÍ** |
| empate | n=546 · +12,21 % · p5 +1,08 % | n=56 · −7,09 % · p5 **−38,91 %** | no |
| visitante | n=1168 · +10,21 % · p5 +4,28 % | n=234 · +7,92 % · p5 **−5,10 %** | no |

El empate y el visitante lucen bien en la mitad con la que se eligió y se
hunden en la otra. Es el retrato de un hallazgo que no era real, así que **el
mismo canal, a otro lado, no sube**.

### Dos cosas que esto destapó

1. **El mínimo de cuota de 1,50 estaba tirando la única regla rentable del
   proyecto.** La banda de tenis `≥ 90 %` tiene cuota media ~1,15: todos sus
   picks caían a la Capa 2 con el motivo «cuota por debajo del mínimo» y no
   llegaban nunca a la pantalla del día. La regla existía en `clasificador.py`
   desde hace tres versiones y **sólo se aplicaba en la vista de partido**.
   Por eso el reparto en secciones mira también la Capa 2.
2. **La MLB, la NBA y el tenis por debajo del 90 % usan el mismo método de
   precio, pero sin desglose por lado propio.** El de fútbol se midió
   excluyendo ATP, WTA, MLB y NBA. Sin p5 propio no suben.

### Lo que NO se ha hecho

- **No se ha borrado nada.** `capa1`, `elite`, `capa1_prob` y compañía siguen
  intactas, y con ellas Telegram, la exportación y el registro de rendimiento.
  La lista de siempre sigue en la misma pestaña, justo debajo. Lo que cambia es
  qué se enseña primero y con qué etiqueta.
- **No se ha subido nada sin p5 medido** para que la sección no se viera vacía.
  Cuando no hay nada, la pantalla dice que no hay nada y por qué.
- **No se promete ROI.** Los dos canales aprueban raspando (p5 +1,73 % y
  +0,18 %); una racha mala los pone en negativo, y el texto lo dice con esas
  palabras.

### Comprobación del reparto

Con picks fabricados que imitan los ocho casos que produce el barrido:

| pick | sección | por qué |
|---|---|---|
| fútbol · canal de precio · **local** | **1** | p5 +1,73 % en juicio |
| tenis 93 % @ **1,14** | **1** | p5 +0,18 %; la cuota corta ya no lo aparta |
| fútbol · canal de precio · empate | 2 | p5 −38,91 % en juicio |
| fútbol · canal de precio · visitante | 2 | p5 −5,10 % en juicio |
| MLB · canal de precio | 2 | mismo método, sin medición propia |
| fútbol · EV del modelo | 2 | −4,66 % a −6,52 % medido |
| tenis 84 % | 2 | la banda 80-90 % da p5 −3,01 % |
| tenis 94 % **sin precio** | 2 | sin cuota no hay apuesta que medir |

Las 12 comprobaciones pasan, incluido el orden (primero el canal mejor medido)
y que **todo pick de las dos secciones lleva su motivo escrito**.

---

## 3. «Sólo 6 casas»

El chip de la cabecera era un literal escrito a mano: decía «6 casas» tanto con
el consenso ampliado activo (hasta ~20 casas) como sin él. El usuario lo leyó
como un tope del sistema; es el tablón base.

Ahora el chip dice el estado real —`6 casas + consenso (~20)`,
`6 casas · sin ODDS_API_KEY` o `6 casas · créditos agotados`— y, cuando está en
modo de respaldo, explica debajo que **no es un tope: es una clave que falta**,
y que con más casas la Sección 1 detecta ventajas de precio que con seis no se
distinguen del ruido.

**Sigue pendiente del usuario, y bloquea esto:** añadir `ODDS_API_KEY` a los
Secrets de Streamlit Cloud, y rotar la clave anterior.
