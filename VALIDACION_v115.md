# v115 — El sesgo que inflaba las líneas de ponches, y el material que faltaba para las combinadas

## 1. MLB: por qué acertaste 1 de 5

Reportaste dos cosas y sólo una era un fallo.

### Lo que NO era un fallo: «1 de 15 partidos entran»

En la versión anterior entraban 13 de 15 y ahora 1. La causa está medida: en ese
momento **Pinnacle sólo tenía dos props de ponches abiertos**, y los dos eran del
mismo partido (HOU @ SDN) — justo el único que entró. La regla necesita la línea
de ponches para decidir, y sin línea el partido no puede entrar.

```
[beisbol] 2 props de ponches en Pinnacle
  Cristian Javier   línea 3.5   (Houston Astros @ San Diego Padres)
  Randy Vasquez     línea 2.5   (Houston Astros @ San Diego Padres)
```

Las casas abren esos props el mismo día del partido y en tandas. No hay
regresión en el código; hay una fuente que todavía no había publicado.

### Lo que SÍ era un fallo: la probabilidad estaba inflada

«Solo uno de 5 se cumplió» no demuestra nada por sí solo —con cinco apuestas al
65 %, acertar una o menos pasa el 5 % de las veces— pero obliga a auditar,
porque la app publica frases como «P(más de 2.5) = 71 %» y una probabilidad
publicada es una promesa auditable.

Se descargaron los registros por juego de MLB StatsAPI (60 abridores, 1.071
aperturas de 3+ entradas) y se midieron las dos piezas por separado.

**La distribución está bien.** `prob_over_ponches` usa una Poisson, y la
sospecha razonable era que subestimara la varianza. Medido fuera de muestra —el
λ de cada apertura estimado con las *otras* aperturas del mismo lanzador—:

| banda | promete | cumple | n |
|---|---|---|---|
| 20-30 % | 25,7 % | 30,4 % | 552 |
| 40-50 % | 45,1 % | 44,6 % | 772 |
| 60-70 % | 64,4 % | 61,1 % | 653 |
| 70-80 % | 75,7 % | 75,6 % | 694 |
| 80-90 % | 85,9 % | 88,3 % | 721 |
| **global** | **54,4 %** | **54,8 %** | **5.118** |

Sesgo medio **+0,45 puntos**. La Poisson describe bien estas líneas — de hecho
los ponches están *infra*dispersos (varianza/media = 0,79), no sobredispersos.

**El λ, no.** Sobreestimaba **+0,50 ponches** de media. Y la causa no era la
tasa de ponche: encoger `k_bf` hacia la media de la liga mejoraba un 0,9 %, o
sea nada. Era `bf_apertura`:

```
bf_apertura = bf / gs        ← bf cuenta TODOS los bateadores, también de relevo
                               gs cuenta sólo las aperturas
```

En cuanto un lanzador alterna los dos papeles, esa división es un disparate:

| lanzador | modelo | real | aperturas |
|---|---|---|---|
| Andrew Álvarez | 30,0 *(topado)* | 18,6 | 7 |
| Javier Assad | 30,0 *(topado)* | 19,3 | 8 |
| Zach Agnos | 24,0 *(por defecto)* | 14,2 | 2 |

Sesgo medido: **+2,43 bateadores**. Con un k/BF de liga de 0,2213 son **+0,54
ponches** — exactamente el sesgo del λ. Causa confirmada, no inferida.

**El arreglo**, con la medición delante:

1. el tope baja de 30 a 28,5 — la media real más alta de la muestra es 27,0
   (Alcántara), así que 30 no acotaba nada;
2. un `bf/gs` por encima de lo posible para una apertura se descarta: son
   relevos contando de más, y manda la media de la liga;
3. con pocas aperturas se encoge hacia esa media, porque tres salidas no
   definen cuánto dura un abridor.

| | antes | después |
|---|---|---|
| sesgo de `bf_apertura` | +2,43 | **+1,40** |
| error absoluto medio | 2,85 | **1,69** |

Un 41 % menos de error. En ponches: el λ deja de inflarse medio ponche, que en
una línea de 2.5 es la diferencia entre publicar un 71 % y un 63 %.

> Lo que esto **no** arregla: que sólo Pinnacle publique estos props. Mientras
> sea la única fuente, habrá días con dos líneas abiertas y días con treinta.

---

## 2. Las combinadas no tenían con qué construirse

Reportaste que sólo salía **una** combinada con cuota real, y que marcar «Solo
mercados con cuota REAL vigente» respondía que no había suficientes mercados.

Las dos cosas tenían la misma causa, y estaba a la vista:

```python
if mk.get('period') != 0 or mk.get('isAlternate'):
    continue                       # ← se tiraban TODAS las líneas alternativas
```

Pinnacle manda el abanico entero de líneas en la misma respuesta (`primaryOnly`
ya estaba en `false`), y se descartaba. Medido: **1,0 líneas de totales y 2,0 de
hándicap por partido**. Con cinco mercados cotizados no hay de dónde sacar
varias combinadas distintas.

Ahora se guardan en un cajón aparte (`totales_alt`, `spreads_alt`) — `totales` y
`spreads` siguen conteniendo sólo la principal, así que ningún consumidor
existente cambia de significado.

| | antes | después |
|---|---|---|
| Champions (Bodø/Glimt) | 0 mercados | **18** |
| Eredivisie (Telstar) | 0 | **14** |
| Liga MX | 5 | **16** |
| combinadas 100 % con cuota real | 1 | **3** |

Sólo se publican las líneas que la plantilla del modelo **tiene**: las de `.5`.
Las asiáticas de cuarto (2.25, 2.75) no existen ahí y el cruce es por similitud
de texto — «Más de 2.25 goles» se parece demasiado a «Más de 2.5 goles» y
acabaría poniéndole a un mercado el precio de otro.

### Y la recomendación que pediste

Ahora se marca **cuál conviene y por qué**, con datos. El criterio **no es el EV
más alto**, y esto importa: ordenar por EV pone arriba justo los peores errores
del modelo. Ejemplo real del tablón:

```
Bodø/Glimt vs Union Saint-Gilloise
  «Menos de 1.5 goles» @ 5,40 · el modelo dice justa 2,47 → EV +118,7 %
```

Pinnacle da un 18,5 % implícito y el modelo un 40 %. Eso no es una oportunidad
del +118 %: es el modelo equivocándose en un mercado sharp. Se marca con
`⚠️ EV demasiado alto para ser real` y se penaliza al recomendar.

El orden de la recomendación es: cuántas patas tienen el precio **comparado
entre varias casas** (la única ventaja con ROI medido positivo), luego la
probabilidad conjunta, y la cuota con peso bajo. Si el EV conjunto sale
disparado, se dice con el número delante en vez de venderlo como valor.

---

## 3. Selecciones: ESPN no funciona en producción

Los registros que mandaste son inequívocos: las **22** competiciones devuelven
403 desde Streamlit Cloud. No es intermitente — ESPN bloquea las IPs de centro
de datos, y la v110 ya lo había documentado para otras rutas. En producción la
vista se quedaba sin calendario entero.

**La solución es no depender de ESPN.** El tablón de cuotas ya se descarga para
todo lo demás, no lo bloquea nadie, y por construcción todo lo que hay ahí tiene
precio. Ahora es la fuente propia y ESPN pasa a refuerzo: en local suman los
dos, en producción salva la vista el tablón.

Reconocer una competición de selecciones por su nombre tiene trampa, y se
resolvió con la medición delante (19/19 casos correctos):

| | |
|---|---|
| `FIFA World Cup Qualifying - UEFA` | ✅ selecciones |
| `UEFA Nations League` | ✅ |
| `Campeonato Sub-20 CONCACAF` | ✅ |
| `Club Friendlies` | ❌ clubes |
| `CONMEBOL - Copa Libertadores` | ❌ (lleva «CONMEBOL») |
| `UEFA - Champions League Qualifiers` | ❌ (lleva «Qualifiers») |
| `Paulista Sub-20`, `Myanmar — Championship U20` | ❌ (falsos positivos reales) |

Lo que separa un sub-20 de selecciones de uno de clubes no es la edad: es que el
de selecciones **siempre** nombra su confederación o se declara internacional.

Y la vista gana el **selector de competición** que pediste. Las opciones salen
de los partidos que hay, no de una lista fija: así no promete una Copa Oro que
no se juega hasta dentro de un año.

---

## 4. Últimos partidos con estadísticas

Pediste que, además del H2H, se vieran los partidos recientes de cada equipo con
sus estadísticas. El histórico ya las traía —tiros a puerta, tiros fuera,
córners, tarjetas, posesión, xG— y la tabla sólo enseñaba el marcador.

Ahora cada partido reciente sale con sus estadísticas en formato
`propio - rival`, para leer de un vistazo si el equipo dominó o resistió:

```
2026-05-24  @ Crystal Palace   2-1  Ganó
            Tiros a puerta 7-3 · Tiros fuera 10-5 · Córners 4-3 · Posesión 56.8-43.2
```

Se devuelve lo que cada competición publica de verdad: los históricos de
football-data «main» traen tiros y tarjetas, los de formato «new» sólo goles, y
Liga MX añade xG y posesión. Un partido sin una estadística no la inventa.

---

## 5. Validación

```
python test_catalogo_y_cuotas.py     TODO OK
python smoke_botones.py              7 vistas
```

Tests nuevos: `test_bf_por_apertura`, `test_lineas_alternativas`, y la
ampliación de `test_selecciones_completas` con el clasificador del tablón.

### Qué NO se ha tocado

- **La regla de MLB sigue siendo tuya**, no una estrategia medida. Lo que ha
  cambiado es que el λ que alimenta su paso 3 está menos sesgado.
- **Ningún criterio de selección de picks.** La corrección de `bf_apertura` es
  un arreglo de estimación, no una señal nueva; no aplica la regla de oro del
  p5 en tramo de juicio porque no hay señal que validar.
- **El EV del modelo sigue siendo anti-indicador del cierre.** Nada de esta
  versión lo contradice, y por eso las combinadas se recomiendan por line
  shopping y no por EV.
