# v122 — Combinadas que se pueden poner de verdad, y una interfaz rediseñada

Dos peticiones, las dos del mismo día:

> «En el mundo real no es posible hacer cuotas con diferentes casas. Quiero que
> me des cuotas también pero solo con la casa de Playdoit que es la mía. De esa
> forma sabré cuál me da una buena cuota a mí.»

> «Sigo sin ver mejoras fuertes en la interfaz de usuario, quiero una totalmente
> rediseñada, más moderna, intuitiva, fácil de usar y atractiva visualmente.»

La primera es una objeción correcta y de fondo. La segunda tenía una causa
medible dentro del propio código.

---

## 1. La combinada que la app proponía no se podía colocar

### El problema

Desde la v114 las combinadas se arman con el **mejor precio de cada mercado**,
venga de la casa que venga. Eso es correcto como medida del techo de precio —y
comprar barato es lo único que este proyecto ha medido con ROI positivo— pero
significa que una combinada de tres patas puede tener una en Pinnacle, otra en
Matchbook y otra en Playdoit.

Eso no es un ticket: son tres apuestas sueltas. La «cuota combinada» que la
pantalla anunciaba no la paga nadie, porque no existe ningún sitio donde
colocarla entera.

### El obstáculo era de datos

`GetEvents` —la llamada del catálogo de Altenar, una sola para los 800 partidos
de fútbol— devuelve **cinco mercados por partido**:

| mercado | ¿sirve para combinar? |
|---|---|
| Resultado Final (1X2) | — |
| Doble oportunidad | no: es el mismo suceso que el 1X2 |
| Empate No Acción | no: el mismo suceso otra vez |
| Total 2.5 | sí |
| Ambos equipos marcan | sí |

Con dos mercados combinables no hay material para una combinada de tres patas
en una sola casa. Por eso no se había hecho antes.

`GetEventDetails` sí lo tiene. Medido sobre Monterrey vs Juárez el 2026-08-10:

```
182 mercados y 1.239 precios en UNA petición
148 de esos mercados traen precio
```

Con el abanico entero: Total de 1.5 a 3.5 (asiáticas de cuarto incluidas),
hándicap de +0 a −1.25, totales por equipo, par/impar, marcador exacto, margen
de victoria, mitades y goleador.

### Qué se traduce y qué NO

De los 148 mercados con precio se traducen al vocabulario del modelo **41**, y
el resto se descarta a propósito. La regla: sólo entra lo que la plantilla del
modelo nombra igual. Un mercado sin probabilidad con la que cruzarse no tiene
EV que calcular, y forzarlo por parecido de texto es exactamente cómo se
inventa un número.

Fuera quedan, con precio y todo: marcador exacto XL, multigoles, goleador,
hándicap 1x2 con marcador, y **todos los mercados de media parte** (la plantilla
no tiene ni un campo de mitades, y sus etiquetas —«Monterrey o empate» del 1ª
Mitad— son idénticas a las del partido completo).

La identificación es por **nombre** de mercado, no por `typeId`. El `typeId` de
Altenar cambia de un deporte a otro: la v77 ya lo pagó fijándolo a 1, lo que
dejó MLB, NBA y tenis sin cuotas de Playdoit sin dar un solo error.

### El fallo que esto destapó: un EV de +19.603 %

Con el tablero completo aparecen mercados que la plantilla no tiene, y
`cruzar_con_plantilla` empareja por similitud de cadena con un listón de 0,80:
cuando no hay equivalente exacto, **entrega el más parecido en vez de nada**.

Medido en la primera prueba, Monterrey vs Juárez:

```
«Monterrey 3-4 Juarez» @ 251,00  →  «Monterrey o Juarez» (p 0,785)
similitud 0,89  →  EV declarado +19.603,5 %
```

No da excepción: da una apuesta. Es el mismo modo de fallo que la v114 corrigió
en el emparejador (`cuotas_multi._buscar` casando partidos distintos), entrando
por otra puerta.

**La guardia**: quien emite una fila puede exigir una *seña* —el marcador
«3-4», la línea «de 2.5 goles», el margen «por 3+»— que la etiqueta de la
plantilla debe contener. Si no está, la fila se cae y se registra. En el mismo
partido, el veto descarta **27 filas** y ninguna de las 41 supervivientes tiene
un EV descabellado.

Las filas sin seña se cruzan como siempre, así que **el tablón multi-casa se
comporta exactamente igual que antes**.

### El otro fallo, que llevaba desde la v114

Las patas de una combinada **nunca han llevado el `id` de su mercado**. Tanto la
interfaz (`m.get('id') == s.get('id')`) como `cuotas_tablon.recomendar_combinada`
buscan el mercado por ahí, así que ninguna pata encontraba nunca el suyo.

El síntoma visible estaba en la pantalla que el usuario mandó: la recomendación
decía «ninguna pata tiene un segundo precio con el que compararse» aunque
Pinnacle y Playdoit estuvieran cotizando esa pata. Y la anotación «N casas
comparadas» no salía jamás.

Corregido en los tres constructores de `match_parlay`. Con el arreglo, la misma
combinada del ejemplo pasa a decir:

```
antes: «Ninguna pata tiene un segundo precio con el que compararse»
ahora: «1 de 3 están comparadas entre dos o más casas»
       «Comprando al mejor precio en vez de al peor se gana un 4,0 % acumulado»
```

### Cómo se juzga una combinada de una sola casa

El criterio normal puntúa **cuántas patas están comparadas entre casas**. Con
una sola casa eso vale cero en todas, y la recomendación se decidiría sola por
probabilidad — justo el criterio que este proyecto tiene medido en negativo
(−4,66 % a −6,52 % en 37.158 apuestas).

Así que en ese caso se puntúa otra cosa, que sigue siendo precio y sigue siendo
comprobable: **cuánto paga tu casa comparada con el mejor precio del mercado en
ese mismo mercado**. Medido en Monterrey vs Juárez, 13 mercados comparables:

| mercado | Playdoit | mejor del mercado | diferencia |
|---|---|---|---|
| Juarez +1.5 | 1,5556 | 2,03 (Pinnacle) | **−23,4 %** |
| Menos de 1.5 goles | 4,75 | 5,26 (Pinnacle) | −9,7 % |
| Empate | 4,25 | 4,63 (Pinnacle) | −8,2 % |
| Menos de 2.5 goles | 2,40 | 2,54 (Pinnacle) | −5,5 % |
| Gana Juarez | 5,3334 | 5,61 (Pinnacle) | −4,9 % |
| Menos de 3.5 goles | 1,5715 | 1,625 (Pinnacle) | −3,3 % |
| Monterrey −1.5 | 2,30 | 2,35 (Pinnacle) | −2,1 % |
| Menos de 4.5 goles | 1,2223 | 1,2475 (Pinnacle) | −2,0 % |
| Más de 4.5 goles | 3,90 | 3,95 (Pinnacle) | −1,3 % |
| Más de 1.5 goles | 1,1539 | 1,1582 (Pinnacle) | −0,4 % |
| Más de 3.5 goles | 2,30 | 2,30 (Pinnacle) | 0,0 % |
| Más de 2.5 goles | 1,5264 | 1,5236 (Pinnacle) | +0,2 % |
| Monterrey −0.5 | 1,5264 | 1,5076 (Pinnacle) | **+1,3 %** |

**Media: −4,57 %.** Ése es el coste real de tener una sola cuenta en este
partido, y es la única cifra de la pantalla que no depende de que el modelo
acierte: son dos precios del mismo suceso.

La pantalla lo enseña pata a pata con un medidor bidireccional, y **no marca en
rojo un diferencial menor del 2 %**: por debajo de ahí es ruido de redondeo
entre casas, y pintarlo de rojo empujaría a abrir cuentas por nada.

### Lo que la pantalla NO promete

Combinar dos mercados del mismo partido en un boleto es lo que las casas llaman
«crea tu apuesta», y no todas lo admiten en todos los mercados. La API del
widget no lo dice —`isParlay` viene a `false` en los 800 eventos, así que no
discrimina nada— y por eso la sección lo advierte en vez de darlo por hecho:
el precio de cada pata es real en cualquier caso, y si la casa no deja
combinarlas habrá que jugarlas por separado.

### Coste operativo

Una petición **por partido** (frente a una por catálogo entero), sólo en la
vista de un partido y nunca en el barrido de `alpha_finder`. Se cachea 30 min.

Se guarda lo **normalizado**, no la respuesta cruda: 321 KB → 94 KB por partido.
Y como éstos son ficheros de caché *uno por partido* —a diferencia del resto,
que son uno por casa y deporte y se sobrescriben—, se purgan a las 6 h. Sin eso
se acumulan para siempre: `_leer_cache` los ignora cuando caducan, pero no los
borra, y un disco lleno en Streamlit Cloud no da un aviso, mata el proceso.

---

## 2. La interfaz: por qué no se notaba el rediseño anterior

La v117 creó `estilo_ui` con seis componentes y CSS. El usuario volvió a pedir
lo mismo por cuarta vez, y la razón estaba en el código:

```
componentes públicos que creó la v117 ... 7
llamadas desde la aplicación ............ 3
líneas de interfaz ...................... 5.884
```

El resto seguía siendo `st.markdown` con asteriscos y `st.metric` por defecto.
Un módulo de estilo que nadie llama no cambia nada.

Y faltaba la palanca más grande: **`.streamlit/config.toml` no tenía tema**.
Sólo `toolbarMode`. Así que todo el CSS afinaba bordes y sombras sobre la
paleta de fábrica de Streamlit — fondo blanco, azul corporativo y gris.

### Qué se ha hecho

**El tema, que no existía.** Oscuro, con el verde de «puedes actuar» como color
primario — el mismo `--ok` del sistema de componentes, para que el botón
principal y la píldora de al lado no digan cosas distintas.

**El sistema de diseño, rehecho.** Escala tipográfica real (una cifra principal
es 2,05 rem y su etiqueta 0,67 rem, no las dos en negrita del mismo tamaño),
superficies con elevación, cifras en tipografía tabular, y veinte componentes
públicos: cabecera de pantalla y de sección, rejilla de KPIs, ticket de
combinada, pata y lista de patas, medidor de precio bidireccional, estado
vacío, nota, tabla, cabecera de partido, píldora, barra, barra 1X2, anillo,
chip de cuota y los dos criterios de color (`tono_por_ev`,
`tono_por_diferencia`).

**Y usado de verdad**: de **3** llamadas a **109**, repartidas por todas las vistas —
cabecera de marca, las siete cabeceras de vista, tarjetas de partido, filas de
apuesta, tablón de cuotas, tabla de mercados, las tres secciones de combinadas,
combinadas multi-deporte, tarjetas de EV+ automático, resumen de predicción,
barra lateral y estados vacíos.

### Dos decisiones técnicas que no son de gusto

**El anillo de probabilidad ya no adivina el color del fondo.** La v117 lo hacía
con `conic-gradient` más un círculo interior pintado del color de la página —y
hay tres posibles (tema claro, oscuro y el propio del despliegue), así que en
cuanto uno no coincidía aparecía un disco de otro color en mitad del anillo.
Ahora el hueco se hace con `mask`: es transparente de verdad.

**Todo texto que entra en un componente se escapa.** Un `&` o un `<` sin escapar
rompe el componente entero y deja media tarjeta en blanco. La única excepción
documentada es `nota()`, que lleva `<b>` a propósito y sólo recibe literales.

**Y si la capa visual falla, la aplicación sigue entera.** Cada componente tiene
su camino alternativo con el render de siempre, y el test
`test_capa_visual_no_rompe` los prueba contra `None`, `NaN`, listas y
diccionarios: ninguno lanza, todos devuelven cadena.

Y hay una guardia contra que esto vuelva a pasar: `test_la_interfaz_usa_la_capa_visual`
exige un mínimo de llamadas, que **ningún componente público se quede sin
llamador** —fue la que detectó que `anillo` no lo tenía— y que el color
primario del tema sea exactamente el mismo `--ok` del sistema de componentes.

---

## 3. Validado en el RENDER, no en la función

La lección más cara de este proyecto: probar `funcion()` en local, verla dar
bien, y que en la pantalla no salga nada. Así que la comprobación se hizo
levantando la aplicación de verdad y leyendo el DOM del navegador.

Liga MX → Monterrey vs Juárez → «Proponer parlays con cuotas»:

```
COMBINADAS 5 · EN TU CASA 41 · EN EL MERCADO 16

💚 En TU casa — Playdoit · un solo ticket, colocable tal cual
⭐ Recomendada — 🛡️ Ancla
   CUOTA COMBINADA 1.35 · PROB. DE ACERTARLO TODO 65% · 100 U PAGAN 135
   Monterrey o Empate   2. Doble oportunidad · acierta 84 %
                        [sin precio con el que comparar]        1.17
   Más de 1.5 goles     3. Total de goles · acierta 78 %
                        [-0.4 % vs Pinnacle]                    1.15
                        Playdoit paga -0.4 % frente a Pinnacle

💰 Al mejor precio del mercado · reparte patas entre varias casas
⭐ Recomendada — 🥅 Con resultado
   CUOTA COMBINADA 3.91 · PROB. DE ACERTARLO TODO 31%
   Gana Monterrey  1. Resultado (1X2) · acierta 62 %
                   [3 casas comparadas] [Playdoit]              1.55
```

Ese `[3 casas comparadas]` es la prueba de que el arreglo del `id` funciona:
antes de esta versión esa etiqueta no aparecía **nunca**.

Y el tablón de cuotas, con la casa del usuario señalada:

| Casa | Monterrey | Empate | Juarez |
|---|---|---|---|
| Pinnacle | **1.51** | **4.63** | **5.61** |
| Bovada | 1.49 | 4.45 | 5.40 |
| Playdoit *(tu casa)* | **1.55** | 4.25 | 5.33 |

Conteo de componentes en la página, medido en el DOM: 13 tickets, 38 patas,
4 medidores de precio, 6 cabeceras de sección, 70 píldoras, 39 chips de cuota,
2 tablas propias. Y el tema aplicado: `background-color: rgb(13, 17, 23)`,
`color: rgb(230, 237, 243)`.

La barra 1X2 comprobada tramo a tramo: `54.8 % verde · 26.4 % gris · 18.8 %
azul`, que son las tres probabilidades del modelo en ese partido.

---

## 4. Tests añadidos

| test | qué protege |
|---|---|
| `test_tablero_playdoit` | que el detalle traiga el tablero entero y no los 5 del catálogo, y que el índice guarde el `event_id` |
| `test_playdoit_no_inventa_mercados` | el veto de la seña, con el caso real del EV de +19.603 % |
| `test_patas_llevan_su_id` | que los tres constructores emitan el `id` del mercado |
| `test_combinada_de_una_sola_casa` | que con una casa gane la mejor comprada, no la más probable |
| `test_capa_visual_no_rompe` | que ningún componente visual lance, y que escape el texto |

---

## 5. Lo que esto NO cambia

- **El modelo sigue sin batir al mercado.** Nada de esta versión toca una
  probabilidad, un filtro ni un peso.
- **El edge sigue estando en el precio.** Lo que cambia es a qué se compara
  cuando sólo se puede jugar en un sitio: el line shopping deja de ser una
  decisión y pasa a ser una medición de lo que cuesta no tenerlo.
- **Sigue sin haber ninguna promesa de ganar.** La sección de una sola casa dice
  que es colocable, no que sea rentable.
