# v114 — Un exchange en lugar de Betfair, y el emparejador que tomaba las cuotas de otro partido

## 0. Lo más importante de esta versión no estaba en la lista

Al medir las casas nuevas apareció un fallo en producción que llevaba tiempo
emitiendo picks sobre partidos inexistentes. Va primero porque cuesta dinero.

### El caso

En el tablón del 2026-08-09, el emparejador casó esto:

| | partido | competición | fecha |
|---|---|---|---|
| Pinnacle | Independiente vs Belgrano | Argentina · Primera División **femenina** | 10-ago |
| Bovada / Playdoit | Belgrano vs Independiente **Rivadavia** | Liga Profesional **masculina** | 15-ago |

Tres errores a la vez: otra categoría, otro club, otra fecha — y con los bandos
invertidos. El resultado no fue una excepción: fue un **arbitraje falso del
0,7737** y un EV inventado sobre un partido que no existe.

### Las tres causas

1. **`_sim_club` devolvía 1.0 cuando un nombre contenía al otro.** Se escribió
   para que «Gremio» casara con «Gremio FBPA», y hace bien; pero eso hacía que
   «Independiente» puntuara igual de perfecto contra «Independiente Rivadavia»,
   que es otro club de la misma liga.
2. **`normalizar` destruye la marca de categoría.** Convierte `(W)` y `(F)` en
   espacios y luego `_tokens_club` tira las palabras de una letra, así que
   «CA Independiente (W)» y «Independiente» quedan idénticos.
3. **`_buscar` no miraba la fecha.** Dos partidos separados cinco días eran
   indistinguibles.

### El arreglo

| guardia | qué hace |
|---|---|
| **similitud** | la contención pasa a 0,93 — sigue muy por encima del umbral 0,80, pero pierde contra la igualdad exacta |
| **categoría** | `fem` y `filial` se leen del nombre del equipo **y del de la competición** (`Argentina - Primera Division Women` es la única pista en ese caso) |
| **fecha** | más de 2 días de diferencia descarta el candidato; el barrido de fixtures ahora la pasa |
| **ambigüedad** | si dos partidos distintos empatan en el mejor score, se devuelve `None` en vez de elegir el primero del diccionario |

«Filial» unifica `II`, `B`, `Sub-21`, `Reserves` y `(R)` a propósito: son la
misma cosa escrita de cinco maneras. Sin eso se perdían siete emparejamientos
correctos («Benfica II» ↔ «Benfica Sub-21», «Monagas II» ↔ «Monagas SC
Reserves»). El sufijo `II`/`B` **no** se aplica al nombre de la competición:
hacerlo rompía «Primera B Metropolitana», «First Division B» y «Liga II».

### Medición A/B sobre el tablón real (1.111 emparejamientos)

| | antes | después |
|---|---|---|
| Bovada | 464 | 464 |
| Playdoit | 517 | 514 |
| Unibet | 130 | 130 |

- **3 emparejamientos corregidos**: los tres que tomaban las cuotas del partido
  equivocado, incluido el del arbitraje falso.
- **3 perdidos**, de los cuales **uno es un rechazo correcto** («CA Atlas vs
  Cañuelas» ≠ «Atlas vs Cañuelas **Reserve**»). Los otros dos son notaciones
  raras: «Sturm Graz II» ↔ «Sturm Graz **A**» y «Juan Pablo II College» ↔ «Juan
  Pablo II», donde el «II» es parte del nombre propio.

Saldo: 2 falsos negativos de 1.111 (0,18 %) a cambio de eliminar picks del
partido equivocado.

---

## 1. Betfair está cerrado desde México — se buscó sustituto y se midió

`Your IP: 187.243.200.187 · Region: MX`. Es un bloqueo por **geolocalización de
red**, no anti-scraping: no se arregla con cabeceras, y la API oficial exige
cuenta, que exige residencia admitida.

Se sondearon **41 candidatas** (`_v114_sondeo_casas.py`). Sólo tres devolvían
datos utilizables:

| | veredicto |
|---|---|
| **Matchbook** | exchange, 200 OK desde México. La v76 lo había descartado por un 403 que ya no da. **Se integra.** |
| Polymarket | margen 1,0000 (no cobra), pero 21 partidos y **cero coincidencias** con nuestro tablón: nombres de otro registro («Cruzeiro EC», «AFC Ajax»). Un precio que nunca casa no aporta nada. **No se integra.** |
| Kalshi | su catálogo abierto no trae fútbol y operar exige residencia en EE. UU. **Descartada.** |

El resto, con motivo medido: FanDuel/BetMGM/Betfair/Novibet/Stake → 403;
Caliente, Coolbet, Marathonbet, BetExplorer → HTML montado por JavaScript;
Betcris, 1xBet → 404; Cloudbet → exige clave; Betsson → 400; Betano, Betclic y
Caliente-api → no resuelven. Las 14 integraciones de Altenar probadas
(`strendus2`, `codere2`, `caliente2`…) → 400: **`playdoit2` sigue siendo la
única válida**, así que Altenar no da una casa más por esa vía.

### Lo que un exchange NO es

Dos diferencias que, ignoradas, habrían empeorado el sistema en vez de
mejorarlo:

**La comisión.** Un exchange no cobra margen en la cuota: cobra sobre la
ganancia neta. Las cuotas se guardan **ya netas** (una back de 3,00 al 2 % paga
2,96). Comparar el back bruto contra el precio de una casa lo habría inflado
justo en el orden de magnitud de la mejora que aporta.

**La liquidez.** El exchange enseña lo que alguien ha dejado puesto, no lo que
acepta. En el primer volcado real:

```
Los Andes vs Ferro Carril Oeste    home 98,02    away 1,1274
```

Un libro vacío con una orden residual. Si eso entra, el line shopping elige
98,02 como «mejor precio» y fabrica un EV enorme sobre una apuesta que no se
puede colocar. Dos guardias: **importe mínimo disponible** (25) y **libro
cotizado entero** (suma de implícitas ≥ 0,95). Efecto: 138 → 99 partidos, y el
margen medio pasa de un 1,0337 engañoso a un **1,0629 honesto**.

### Aporte medido, ya neto de comisión y con las guardias puestas

Sobre 68 partidos con Matchbook y al menos dos casas más:

| quién da el mejor precio | % |
|---|---|
| **Matchbook** | **36,5 %** |
| Pinnacle | 35,5 % |
| Playdoit | 10,9 % |
| Bovada | 9,0 % |
| Unibet | 8,1 % |

- margen del mejor precio **sin** Matchbook: **1,0395**
- margen del mejor precio **con** Matchbook: **1,0314** → **0,81 puntos**
- mejora al mejor de las casas en **37,7 %** de las selecciones; cuando gana,
  **+3,14 %** de media

El 36,5 % es prácticamente el 35,4 % que Betfair daba en el histórico de
football-data. Es el sustituto que la v113 pedía.

> **Lo que esto NO significa.** Sigue siendo cierto todo lo medido antes: el
> modelo no bate al mercado, su EV declarado es anti-indicador del cierre, y
> apostar por su probabilidad pierde entre −4,66 % y −6,52 %. Lo único con ROI
> positivo y robusto es **comprar al mejor precio**, y esta versión añade una
> fuente más de mejor precio. No promete ganar dinero.

---

## 2. Todas las ligas al mismo nivel

**El síntoma.** En Champions, Conference y Eredivisie la sección de cuotas
enseñaba tres precios y la línea «Mejor precio disponible». En Liga MX enseñaba
treinta mercados con su EV.

**La causa.** La vista tenía dos caminos excluyentes: si `cuotas_auto`
encontraba el `event_id` de ESPN, tabla rica; si no, el respaldo pobre. Y
`buscar_event_id` falla justo en las competiciones europeas, porque el catálogo
del motor no contiene a los equipos de fase previa. En los registros de
producción se veía tal cual:

```
[name_mapper] sin mapear: 'Kairat Almaty' (evid) — mejor candidato 'AC Milan' con 0.29
```

**El arreglo.** No hacía falta ninguna fuente nueva: `cuotas_partido` ya
devolvía totales, ambos-marcan y hándicap de todas las casas, y el respaldo los
tiraba. El módulo nuevo `cuotas_tablon.py` los traduce al vocabulario de la
plantilla y los cruza con el modelo. Ahora el tablón multi-casa se enseña
**siempre**, y la vía de ESPN se **suma** cuando existe (aporta los props de
jugador, que el tablón no publica).

Con una ventaja que la vía de ESPN no tenía: lee **seis casas** y se queda con
el mejor precio de cada mercado, no el de una sola.

**Además, 13 fixtures recuperados.** De 473 fixtures de las 50 competiciones
activas, 169 no encontraban cuota. Casi todos porque ninguna casa los cotiza
todavía —correcto—, pero nueve sí estaban en el tablón y se perdían por
ortografía. Cada equivalencia añadida corresponde a un caso real medido:

```
Union St.-Gilloise ↔ Union Saint-Gilloise      Hamburg SV      ↔ Hamburger SV
Red Bull New York  ↔ New York Red Bulls        CSKA Moscow     ↔ CSKA Moscú
Asteras Tripoli    ↔ Asteras Tripolis          Volos NFC       ↔ Volos NPS
Queen's Park       ↔ FC Queens Park
```

Resultado: **304 → 317 fixtures con precio**.

---

## 3. Las tarjetas llevan a su partido

Pedido: «si hago click me llevas a Liga MX al partido seleccionado para ver sus
estadísticas y evaluar qué parlay meter».

El rodeo es obligado: Streamlit prohíbe escribir la clave de un widget ya
instanciado (`st.session_state.competencia cannot be modified after the widget
with key competencia is instantiated`), y el selector de competición se crea
mucho antes que las tarjetas. Así que `navegacion.py` lo hace en dos tiempos:
la tarjeta apunta el destino en una clave propia y pide un rerun; al principio
del script siguiente, antes de crear el selector, se traduce a las claves de
los widgets. Funciona para fútbol (con el nombre ajustado al catálogo de la
liga de destino) y para MLB, KBO, NBA y tenis.

`smoke_botones.py` cazó un fallo de la primera versión: el mismo partido
aparece en varias listas de la página, así que la clave del botón se repetía.
Ahora es un contador determinista.

---

## 4. Combinadas con el precio real de las casas

Antes, el constructor puntuaba casi todas las patas con cuota justa
(`1/prob`) — y con cuota justa **el EV de toda pata vale 0 por construcción**,
así que sólo podía ordenar por probabilidad. Sólo unos pocos mercados tenían
precio, y de `odds_actuales.json`, que escribe la tarea diaria.

Ahora `cuotas_tablon.motor_con_tablon` envuelve el motor y le engancha el mejor
precio en vivo de las seis casas. Medido: 5 mercados con precio real en
Liga MX, 9 en Brasileirão.

Y una sección aparte, **«Combinada por EV real de las casas»**, que usa **sólo**
mercados con precio publicado. Es una distinción importante: una combinada que
mezcla cuota real y cuota justa anuncia una cuota combinada que ninguna casa va
a pagar.

Debajo, el **contexto del cruce** (historial, forma, clasificación) que el
usuario pidió tener a la vista al decidir.

---

## 5. H2H, clasificación y forma en MLB, KBO y tenis

**Béisbol** — no hizo falta lógica nueva. Sus históricos tienen la misma forma
que los de fútbol y sólo llamaban `home_runs`/`away_runs` al marcador; con que
`panel_equipos._historico` reconozca esos nombres, el cara a cara, la forma y
el reparto casa/fuera funcionan sobre **26.544 partidos de MLB y 13.009 de
KBO**. Lo único propio es la clasificación: por porcentaje de victorias, no por
puntos, porque los equipos no juegan el mismo número de partidos.

**Tenis** — aquí sí cambia todo, porque no hay local, ni tabla, ni temporada
regular. La traducción honesta de cada bloque:

| fútbol | tenis |
|---|---|
| cara a cara | balance histórico (259.443 parejas en el estado del motor) |
| clasificación | ranking y **ELO por superficie** — el general mezcla tierra y pista rápida, que no se transfieren |
| forma | últimos resultados, partidos en 14 días y horas en pista en 7 |

---

## 6. Selecciones nacionales completas

La lista tenía **siete** competiciones, todas masculinas absolutas: amistosos,
Nations League de UEFA y cinco clasificatorias. Ni un torneo continental, ni
una femenina, ni una olímpica.

Se probaron 28 identificadores de ESPN uno a uno; **22 responden** y son las que
entran: Mundial, las seis eliminatorias, Eurocopa y su clasificación, ambas
Nations League, Copa América, Copa Oro, Copa África, Copa Asia,
Confederaciones, Juegos Olímpicos, y las femeninas (amistosos, Mundial,
Eurocopa y Olímpicos). Cuatro no existen con ese nombre y dan 400
(`uefa.euro.u21`, `conmebol.america.fem`, `concacaf.gold.w`, `ofc.nations`):
quedan anotadas para no reintentarlas a ciegas.

Efecto: de 3 competiciones con partidos a **200 partidos** de 22 competiciones,
con la CONCACAF Nations League (73) entrando entera por primera vez.

El nombre del torneo no es decorativo: viaja al emparejador y de ahí sale la
marca que impide que un amistoso femenino tome el precio del masculino entre
los mismos dos países. Por eso los femeninos lo llevan en el nombre.

Y la vista gana **cuotas reales + EV**, que era lo que le faltaba para estar al
nivel de Liga MX. Se consulta con el nombre en inglés de cada selección, que es
como lo publican las casas.

---

## 7. La vista de tenis ya no espera a las cuotas para pintar

Síntoma del usuario: «cuando selecciono tenis no me carga todo el contenido
hasta que hago click en cuota automática».

Un expander **cerrado no ahorra trabajo**: Streamlit ejecuta su cuerpo siempre y
sólo decide si lo enseña. El panel de EV+ estaba arriba del todo, así que el
barrido de cuotas de tenis —ATP + WTA + challengers + ITF, la lista más larga
de los cuatro deportes— corría antes del calendario, de los selectores y de los
19 mercados. El click no arreglaba nada: disparaba un rerun que ya encontraba
el caché de 15 minutos caliente.

Es la misma causa que la v91 corrigió en Apuestas del Día. El panel se ha
movido al final de la vista. El trabajo total es el mismo; lo que cambia es que
lo que se viene a ver sale sin esperar a la red.

---

## 8. Validación

```
python test_catalogo_y_cuotas.py     TODO OK
python smoke_botones.py              7 vistas
```

Tests nuevos: `test_guardias_del_emparejador`, `test_exchange_matchbook`,
`test_tablon_a_mercados`, `test_selecciones_completas`.

Un test viejo se ha **cambiado a propósito**: `test_memoizacion_no_cambia_el_emparejamiento`
exigía `_sim_club('Gremio', 'Gremio FBPA') >= 0.99`, es decir, que la contención
puntuara igual que la igualdad exacta. Eso es exactamente lo que causaba el
fallo del apartado 0. Ahora exige que siga emparejando (≥ 0,80) y que pierda
contra el exacto.

### Sobre la regla de oro

La regla del proyecto —nada se despliega sin p5 de bootstrap positivo en un
tramo de juicio no usado para elegir parámetros— **aplica a señales**, y esta
versión no añade ninguna. Añade una fuente de precio al line shopping (que ya
está validado: +11,49 % en juicio, p5 +1,73 %), corrige un emparejador que
producía datos falsos, y el resto son cambios de presentación. No se ha tocado
ningún modelo ni ningún criterio de selección de picks.
