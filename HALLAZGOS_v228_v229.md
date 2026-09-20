# v228 · v229 — El filtro que no fallaba, y los deportes que sólo decían quién gana

Dos reportes del usuario en el mismo día. Uno resultó ser un fallo del
proveedor que llevaba días vaciando la aplicación en silencio. El otro no era
un fallo, y al ir a comprobarlo salió otra cosa que sí lo era.

---

## v228 — «Filtro la Liga MX por finalizados y no sale ninguno»

### No era el filtro

El filtro es una línea: `[p for p in con if p.get('jugado')]`. Hacía su trabajo
perfectamente sobre una lista que nadie había podido llenar.

**ESPN dejó de aceptar rangos de fechas.** Medido contra el servicio:

```
dates=20260919              ->  200, 4 eventos
dates=20260917-20260919     ->  400
```

Y no sólo en el fútbol. Probado deporte por deporte el 2026-09-19:

| deporte | rango | un día |
|---|---|---|
| fútbol | **400** | 200 (4 eventos) |
| NFL | **400** | 200 |
| MLB | **400** | 200 (15 eventos) |
| NBA | **400** | 200 |
| college football | **400** | 200 (71 eventos) |
| tenis | 200 (**2 eventos**) | 200 (**7 eventos**) |

El tenis es el peor de todos, y por eso es el que decide el diseño. No devuelve
400: devuelve 200 con menos partidos. Un error se ve en el log y tarde o
temprano alguien lo mira; una respuesta correcta a la que le faltan cinco de
siete partidos no la ve nadie. El proyecto llevaba desde el 15 de septiembre
liquidando el tenis con una fracción de los resultados.

### Lo que de verdad falló: el arreglo anterior, a medias

Esto ya se había descubierto el 2026-09-15 y se arregló… **en una sola de las
rutas**. `resultados_liga` se había quedado con su propia copia del `dates=A-B`,
y de ella cuelga toda la lista de partidos finalizados. Había una tercera copia
en `fixtures_deporte` y una cuarta en `resultados_tenis`.

Ahora hay **una sola implementación**, `eventos_por_dias`, y un test que
comprueba lo único que importa: que ninguna petición lleve un guion.

### Y troceando, no sólo por días

Probando en vez de suponiendo salió que ESPN sí acepta otras formas:

```
dates=20260919  ->  4 eventos     (día)
dates=202609    ->  34 eventos    (mes)
dates=2026      ->  100 eventos   (año)
```

Así que la granularidad va según lo ancha que sea la ventana: hasta ocho días,
día por día, que es exacto; por encima, mes por mes. Sin esa rama, arreglar
`fixtures_selecciones` —que pide 210 días por cada una de sus veinte
competiciones— habría cambiado un fallo por una tormenta de cuatro mil
peticiones. Como el mes trae partidos de fuera de la ventana, se filtran por la
fecha del evento: el contrato sigue siendo el del rango.

```
antes:  0 partidos finalizados, todos los días, en 62 competiciones
ahora:  188 · Liga MX: Atlas 1-1 Pumas, San Luis 3-1 Necaxa
```

### Lo que se comprobó y NO era un fallo

El usuario también echaba en falta dos partidos de Liga MX. Puebla-Atlante y
Juárez-Tigres empezaron a las 19:00 y 21:00 de CDMX **del día 18**. Pertenecen a
ayer, y el recorte por hora local los coloca bien. Ahí no había nada que
arreglar, y decirlo es parte del encargo.

### Un efecto secundario que hay que vigilar

Al devolver 190 partidos donde antes devolvía 0, `partidos_jugados.de_dia` pasó
de gratis a **13 segundos y 186 peticiones** — y se ejecuta AL PINTAR, no en el
precálculo. Es la función haciendo su trabajo, pero es justo el coste que la
v220 sacó del render. Queda anotado como lo siguiente a mover.

---

## v229 — «Da alta probabilidad al under y su media de goles es alta»

### La aritmética estaba bien

América-Chivas, las dos formas en 2,6 goles, «Menos de 3.5 — 72 %». Con
λ = 2,6 la Poisson da 73,6 %. El número es correcto.

Lo que confunde es que **«Over 2.5» y «Under 3.5» parecen contrarios y no lo
son**: se solapan en el partido de tres goles exactos, que con esa media es el
21,8 % de los casos. Por eso la misma tarjeta podía decir «Over 2.5 en 4 de 5»
arriba y «Menos de 3.5 al 72 %» abajo sin contradecirse una sola vez.

| con λ = 2,6 | |
|---|---|
| Over 2.5 (3 o más goles) | 48 % |
| Under 3.5 (3 o menos) | 74 % |
| el opuesto real de Under 3.5 es Over **3.5** | 26 % |

### Pero la pregunta de fondo sí tenía fundamento

Medido sin fuga sobre el pliegue de juicio (9.584 partidos), reentrenando la
calibración con los pliegues anteriores:

| línea 2.5 | modelo crudo | real | error |
|---|---|---|---|
| λ < 2.2 (partidos cerrados) | Under 71,7 % | 56,0 % | **+15,7 pp** |
| λ 2.2–2.6 | Under 57,0 % | 50,9 % | +6,1 pp |
| λ 2.6–3.0 | Under 47,1 % | 48,2 % | −1,1 pp |
| λ ≥ 3.0 (partidos abiertos) | Under 33,0 % | 41,2 % | **−8,2 pp** |

La Poisson cruda se pasa de confiada **en los dos extremos y en direcciones
opuestas**, que es la firma de la sobredispersión. La calibración isotónica que
ya había se come casi todo y deja entre 0,2 y 3,5 pp según la celda.

### Una hipótesis que se probó y se descartó

Si el residuo se concentrara en la λ alta, calibrar por tramo de λ lo
arreglaría. Medido:

```
lambda < 2.6    +0,0101  (n=14.163)
lambda >= 2.6   +0,0193  (n=14.589)
```

Casi el doble, sí, pero la diferencia son 0,9 pp sobre media muestra: menos de
medio punto en total. **No se implementa.** Está en
`_v229_sesgo_por_lambda.json` para que nadie tenga que volver a preguntarlo.

### Lo que sí se hizo: enseñar la λ

El porcentaje se veía y el número del que sale, no. Ahora la tarjeta dice:

> ⚽ 2,6 goles esperados · Over 2.5 (48 %) y Under 3.5 (74 %) se solapan en el
> partido de 3 goles (22 %)

---

## v229 — «No sólo el del gane»

Medido sobre el precálculo del 2026-09-19, con 340 picks:

| | antes |
|---|---|
| Fútbol | 1X2 (con empate), goles 0.5–6.5, BTTS |
| NFL | sólo `Gana X` |
| MLB | sólo `Gana X` |
| Tenis | sólo `Gana X` |

**Y no faltaba el modelo en ninguno.** Los tres lo tenían, medido y desplegado:

- `plantilla_mlb` arma la matriz de carreras y saca over/under de 7.5 a 10.5.
- `TennisEngine.plantilla` tiene una regresión de juegos calibrada sobre 68.000
  partidos, con su sigma.
- `nfl_mercados.plantilla_nfl` cubre el total del partido y el de cada equipo.

Sólo alimentaban la ficha de detalle, la que hay que abrir partido a partido.
`totales_deporte` es el puente, y devuelve **una sola forma** para los tres
—`{línea: P(over)}` más la unidad y el centro— que es la misma que el fútbol ya
usa para los goles. Así los tres heredan la pantalla sin tocarla, en vez de
tres bloques que divergen a la tercera versión.

```
⚾ Carreras   Más 8.5  52 % · Menos 8.5  48 %
             Más 7.5 65 % · Más 9.5 38 % · Más 10.5 27 %
🎾 Juegos     Más 24.0 48 % · Menos 24.0 52 %
🏈 Puntos     Más 47.5 49 % · Menos 47.5 51 %
```

### Lo que esto NO hace

No recomienda. Publica la probabilidad del modelo, igual que `goles_lineas`.
Convertir un total en pick exige comparar contra el precio de ESE mercado, y esa
tubería hoy sólo está montada para el moneyline en estos tres deportes.
Publicar un pick sin ese lado sería inventarse el EV.
