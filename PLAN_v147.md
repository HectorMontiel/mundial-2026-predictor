# Plan v147 — histórico, rendimiento y navegación

> Todo lo que sigue está **medido antes de escribirlo**. Donde hay un número,
> hay un comando detrás. Donde no lo hay, lo digo.
>
> Mediciones del 2026-08-17.

---

## Resumen, por si no lees el resto

| Frente | Lo que se suponía | Lo que mide |
|---|---|---|
| **1 · Histórico** | hace falta fuente nueva (FBref, Sportmonks, Kaggle) | la fuente que ya usamos tiene **16 temporadas**, el proyecto le pide **5**, y luego recorta a **4 años** por configuración |
| **2 · Ficha lenta** | el renderizado es pesado | la ficha calcula la plantilla **9 veces** en vez de una; ya existe un envoltorio cacheado que casi nadie usa |
| **3 · Navegación** | — | scroll único; se parte en pestañas |
| **Error Arrow** | bug del proyecto | **lo introduje yo ayer** en `corners_ui`. Corregido |
| **Error 403** | la API de ESPN cambió | la URL funciona; ESPN bloquea por **IP de centro de datos**, mitigado desde la v110 |

---

## FRENTE 1 · Profundidad del histórico

### Auditoría (hecha)

**26 de 50 ligas tienen menos de 5 temporadas completas.** Mediana: 4.

| liga | temporadas completas | desde |
|---|---|---|
| **premier** | **2** | 2023-08-11 |
| europa_league | 3 | 2019-08-01 |
| laliga, bundesliga, ligue_1, eredivisie, ita_serie_b… | 4 | 2021-08 |
| liga_mx, mls, brasil, rus_premier, polonia… | 7 | 2018-08 |
| primeira | 9 | 2016-08 |

El patrón no es aleatorio: depende del `formato` de la liga.

| formato | ligas | mediana de temporadas |
|---|---|---|
| `main` (football-data /mmz4281) | 18 | **4** |
| `espn` | 16 | 4,5 |
| `new` (football-data /new) | 14 | **7** |

### La causa: dos límites apilados, y ninguno es de la fuente

1. **La lista de URLs pide 5 temporadas.** Las ligas `main` traen
   `mmz4281/2122 … 2526`. Cinco ficheros y se acabó.
2. **`anios_ventana` recorta a 4 años.** En `league_engine`:

   ```python
   anios = cfg.get('anios_ventana', 4)
   df = df[df['date'] >= df['date'].max() - pd.DateOffset(years=anios)]
   ```

   Las ligas `main` **no declaran** `anios_ventana`, así que caen al defecto de
   4. Las `new` sí lo declaran (8) — y por eso tienen 7 temporadas.

### Lo que la fuente actual sí ofrece (verificado)

`football-data.co.uk/mmz4281/{temporada}/E0.csv` responde 200 en **16
temporadas**, de `1011` a `2526`. Y las antiguas traen lo que importa:

| temporada | columnas | córners | remates | tarjetas | cuotas |
|---|---|---|---|---|---|
| 2010-11 | 71 | HC/AC ✓ | HS/AS ✓ | HY/AY ✓ | B365 ✓ |
| 2018-19 | 62 | ✓ | ✓ | ✓ | B365 ✓ + **Pinnacle de cierre** |

### Propuesta, en este orden

**Paso 1 — agotar la fuente que ya está. Coste: cero.** Extender las listas de
URL hacia atrás y subir `anios_ventana` en las `main`. Mismo código de
normalización, mismo formato, mismo pipeline diario. Ninguna integración nueva
y ningún modo de fallo nuevo.

**Paso 2 — medir si más historia mejora, que no es obvio.** Un modelo de fútbol
con diez temporadas puede empeorar: las plantillas rotan, el estilo de liga
cambia y los equipos entran y salen por ascensos. El criterio del encargo
(≥ 2 pp de backtest o ≥ 5 % de ROI) se aplica **por liga**, y cada liga se queda
con la ventana que mejor mida. Es un barrido de un parámetro sobre un pipeline
que ya existe.

**Paso 3 — sólo si el paso 1 se queda corto, mirar fuera.** Con la evidencia ya
recogida en sesiones anteriores:

| fuente | estado medido | veredicto |
|---|---|---|
| FBref | **HTTP 403** (Cloudflare), verificado dos veces | no utilizable sin proxies |
| TheSportsDB gratuito | **5 partidos por temporada** | muestra comercial, no histórico |
| OpenLigaDB | 3. Liga alemana ✓ | útil, alcance alemán |
| OpenFootball | at.2, de.1-2, es.1-2 | huecos de temporada |
| API-Football / Sportmonks | de pago, sin sondear | pendiente si el paso 1 falla |

**No propongo pagar nada todavía.** Sería pagar por lo que la fuente gratuita ya
tiene y no le estamos pidiendo.

### El H2H y el modelo NO comparten ventana — corrección del usuario, aceptada

El usuario señala, con razón, que mi cautela sobre «más historia no siempre
mejora» aplica al **modelo general** (1X2, goles) y **no al H2H**:

> En una liga de 20 equipos dos rivales se ven 2 veces por temporada. Con 4
> años son 8 partidos de muestra; con 16 son 32. Eso no es «más ruido»: es
> menos.

Y es correcto. El H2H no estima parámetros ni sufre por la rotación de
plantillas del mismo modo: describe un historial concreto entre dos clubes, y
ahí la muestra manda.

**Lo importante es que no hay que elegir.** Comprobado en el código:

- La verdad en disco es `historico_{clave}.csv`, y es lo que lee el H2H
  (`corners_ui.h2h_corners`, `panel_equipos.forma_global`).
- El recorte por `anios_ventana` vive en la rama del formato `new`
  (`league_engine`, línea ~789) y se aplica **antes** de escribir el CSV.
- Las ligas `main` —las 18 con menos historia, incluida la Premier— **no pasan
  por ese recorte**: su límite es sólo la lista de URLs.

Así que el plan pasa a ser:

1. **Ampliar el CSV al máximo que dé la fuente**, para todas. Beneficia al H2H
   de forma directa e inmediata, sin medir nada y sin riesgo: son partidos que
   ocurrieron.
2. **La ventana del MODELO se decide aparte**, filtrando en el momento de
   entrenar y no al escribir el fichero. Si medir dice que al modelo le sientan
   mejor 4 años, se entrena con 4 — y el H2H sigue viendo los 16.

Con eso, la salvedad del usuario y mi cautela dejan de estar en conflicto: cada
consumidor usa la ventana que le conviene.

### Un hallazgo que sale de mirar la configuración

La lista de URLs es inconsistente entre ligas sin ningún motivo:

```
premier : mmz4281/2324, 2425, 2526              -> 3 ficheros
laliga  : mmz4281/2122, 2223, 2324, 2425, 2526  -> 5 ficheros
```

Por eso la Premier tiene 2 temporadas completas y LaLiga 4. No es una decisión:
es que a una se le escribieron tres líneas y a la otra cinco.

### Riesgo declarado

Más historia **no garantiza** mejor modelo. Si el paso 2 sale plano o negativo,
se documenta y la ventana se queda como está. La regla de oro no se suspende
por este frente.

---

## FRENTE 2 · Rendimiento

### Línea base (medida)

```
APUESTAS DEL DÍA
  fixtures_multi (50 ligas, 3 días) en frío .......  73,7 s
  fixtures_multi cacheado .........................   0,0 s
  barrido completo en frío ........................ 234,2 s
  barrido completo en caliente .................... 122,5 s

FICHA DEL PARTIDO
  ClubEngine('liga_mx') ...........................   0,9 s
  plantilla_club, 1.ª vez ......................... 12,3 s
  plantilla_club, 2.ª vez .........................   0,4 s
  h2h_corners .....................................   0,03 s
  mercados_playdoit (tablero) .....................   0,02 s
```

### El cuello de la ficha: se calcula nueve veces lo mismo

Existe `plantilla_club_cacheada` con `@st.cache_data`… y sólo se usa en **2**
sitios. La ficha llama a `motor.plantilla_club(home, away)` **directamente en
ocho puntos más**, cada uno recalculando:

```
dashboard_ui.py:2970, 3011, 3166, 3430, 3482, 3515, 3561, 3672
```

Ocho recálculos son los 12,3 s medidos. **No es renderizado pesado: es el mismo
cálculo repetido.** La segunda llamada tarda 0,4 s, así que el trabajo ya es
cacheable; lo que falta es usar la caché.

**Arreglo:** enrutar los ocho por el envoltorio. Cambio mecánico, riesgo bajo.
Objetivo: **12,3 s → menos de 1 s**.

### El cuello del barrido: 122 s en caliente

Con los fixtures ya cacheados (0,0 s) quedan 122 s, así que el tiempo está en el
trabajo por partido. Propuestas, por relación beneficio/riesgo:

1. **Cachear el barrido con TTL.** Un TTL de 10-15 min alinea el coste con la
   frescura real de las cuotas (30 min). *Riesgo: bajo.*
2. **Carga diferida de la lista**: pintar los primeros 30 y un botón «cargar
   más». No toca el barrido, sólo el render. *Riesgo: bajo.*
3. **Paralelizar el trabajo por partido** dentro de la rama de fútbol, como ya
   se hace entre deportes. *Riesgo: medio* — hay estado compartido
   (`evaluados_pares`) que habría que revisar.

Se implementan 1 y 2; la 3 se mide antes de decidir.

### Validación

Repetir el mismo guion de medición y publicar antes/después. Si una
optimización no da lo prometido, se retira — no se deja «porque no estorba».

---

## FRENTE 3 · Navegación de la ficha

### Pestañas, y por qué no expanders

| | pestañas (`st.tabs`) | plegables (`st.expander`) |
|---|---|---|
| coste de navegación | 1 clic, sin scroll | scroll + clic por sección |
| estado | se mantiene | se mantiene |
| **coste de render** | **Streamlit renderiza TODAS** aunque se vea una | sólo lo abierto |
| descubrimiento | todo visible arriba | hay que bajar para saber qué hay |

**Elijo pestañas**, con un matiz que importa por el Frente 2: como Streamlit
renderiza el contenido de todas, meter la ficha en pestañas **no ahorra tiempo
por sí solo**. El ahorro viene de arreglar los nueve recálculos. Hacer sólo las
pestañas dejaría la app igual de lenta y más bonita, que es la peor
combinación.

Estructura, uniforme para todos los deportes:

```
📊 Resumen        pronóstico 1X2, marcador probable, semáforo
📈 Mercados       tabla completa con probabilidades y EV
🤝 H2H y forma    gráfico H2H, forma reciente, estadísticas
🚩 Específicos    córners (fútbol) · yardas (NFL) · abridores (MLB) · saque (tenis)
🧩 Combinadas     parlays de ese partido
```

El contenido varía por deporte; la estructura no.

---

## Errores reportados

### 1 · Arrow: `Could not convert '—' with type str` — **CORREGIDO**

Era **mío**, de ayer, en `corners_ui.py`. La columna «Cuota justa» ponía
`round(...)` cuando había probabilidad y `'—'` cuando no. Arrow infiere el tipo
por los primeros valores y revienta al encontrar texto en una columna numérica.

Y revienta **al pintar**, no al calcular: por eso ni los 813 tests ni el smoke
lo vieron. Hace falta un partido con alguna línea sin probabilidad.

Corregido con `None` (pandas lo convierte en NaN) y el formato declarado en
`column_config`. Barrido el resto del proyecto buscando el mismo patrón:
**no hay más casos**.

### 2 · ESPN 403 en `mex.1/teams/232/roster` — no es lo que parece

Verificado desde esta máquina, con y sin User-Agent:

```
roster mex.1 ......... 200 · 215.872 b
teams mex.1 .......... 200 ·  21.609 b
core athletes ........ 200 ·   3.088 b
roster eng.1 ......... 200 · 131.414 b
```

**La URL no ha cambiado y el endpoint funciona.** El 403 viene de la IP: ESPN
bloquea `/teams` y `/roster` desde centros de datos, que es donde corre
Streamlit Cloud. Está documentado en el propio módulo desde la v110, con caché
negativa para no repetir la petición en cada rerun.

No hay nada que «arreglar» en el código: hay que **decidir**.

- **(a)** dejarlo — degrada limpio, sin goleadores en la nube;
- **(b)** buscar fuente alternativa de goleadores que no bloquee por IP;
- **(c)** precalcular los rosters en el runner de GitHub Actions —que **no**
  está bloqueado— y commitearlos como dato, igual que ya se hace con los
  modelos.

**Recomiendo (c)**: reutiliza una tubería que existe, no añade fuente y
resuelve el problema donde está — en quién hace la petición, no en la URL.

---

## Orden de ejecución propuesto

1. **Frente 2, los nueve recálculos.** Mayor impacto, menor riesgo, y requisito
   para que el Frente 3 no sea maquillaje.
2. **Frente 3, pestañas.** Encima de una ficha ya rápida.
3. **Error 403 por la vía (c).**
4. **Frente 1, pasos 1 y 2.** El más largo: reentrenar y medir liga por liga.

El Frente 1 va al final a propósito: es el que más tiempo de máquina consume y
el único cuyo resultado puede ser «no se despliega nada».
