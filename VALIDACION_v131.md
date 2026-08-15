# v131 — NFL: integración completa y su medición

> Fecha: 2026-08-15 · Alcance: fuentes de datos, modelo, mercados de Playdoit,
> interfaz y validación.
>
> **Resumen en una línea:** la NFL entra entera —datos, modelo, 12 mercados de
> la casa, vista propia, H2H, filtro y parlays— y el modelo se despliega como
> **pronóstico, no como apuesta**, porque su ROI al precio de cierre real no
> cruza el listón del proyecto. Es el mismo veredicto que el fútbol, la MLB y
> el tenis, obtenido esta vez con datos nuevos y en un deporte nuevo.

---

## 0. La regla que se ha aplicado

La de siempre (BITÁCORA §0): **nada se despliega sin p5 de bootstrap positivo
en el tramo de juicio.** La tentación con un deporte de masas que arranca esta
semana era saltársela «porque hay que tener NFL». No se ha hecho, y este
documento existe para dejar por escrito qué se midió, con qué muestra y qué
salió.

---

## 1. Informe de viabilidad de fuentes (PARTE 1 del encargo)

### Veredicto: **ESPN basta, y con holgura.** No hace falta PFR ni nflfastR.

Se midió antes de decidir. Lo que ESPN entrega, verificado el 2026-08-15:

| endpoint | qué da | coste medido |
|---|---|---|
| `site.../football/nfl/scoreboard?dates=YYYY` | el **año natural entero** en una petición (335 eventos en 2024) | 1 petición · 2,8 MB · 0,9 s |
| `site.../football/nfl/summary?event=ID` | **25 estadísticas de equipo por bando** | 1 petición/partido · 1,7 s |
| `sports.core.../events/{id}/competitions/{id}/odds` | **cuotas de CIERRE históricas** de hasta 13 casas | 1 petición/partido |
| `site.../football/nfl/teams` | los 32 equipos con id y abreviatura | 1 petición |

Las 25 estadísticas por equipo y partido son: primeros downs (total, de pase,
de carrera, por penalización), 3.º y 4.º down convertidos/intentados, jugadas
totales, yardas totales, yardas por jugada, drives, yardas netas de pase,
completos/intentos, yardas por pase, intercepciones, sacks y yardas perdidas,
yardas de carrera, acarreos, yardas por acarreo, zona roja
convertida/intentada, penalizaciones y sus yardas, pérdidas de balón, balones
sueltos perdidos, touchdowns defensivos y tiempo de posesión.

**El hallazgo que cambia el proyecto es el tercero.** No se esperaba que ESPN
sirviera cuotas de cierre históricas, y sin ellas sólo habría habido backtest
de ACIERTO — que según la bitácora §0 no decide nada. Con precios de cierre
reales se puede medir lo único que importa: si comprar a ese precio gana.

### Tabla comparativa de alternativas

| fuente | pros | contras | coste | estabilidad | veredicto |
|---|---|---|---|---|---|
| **ESPN** | ya integrada (`fixtures_espn`), sin clave, trae stats **y** cuotas, un solo espacio de identificadores para calendario y estadística | 403 desde IP de centro de datos (conocido, v98) | 0 € | alta (4 meses en uso para MLB/NBA) | **ELEGIDA** |
| Pro-Football-Reference | la referencia histórica, muy profunda | HTML con tablas dentro de comentarios; `robots.txt` limita a 1 petición/3 s y bloquea por ráfaga; **no trae cuotas**; obliga a un segundo espacio de nombres que casar con el de ESPN | 0 € | media-baja | descartada |
| nflfastR / `nfl_data_py` | play-by-play con EPA ya calculado | parquets de cientos de MB por temporada contra el techo de memoria de Streamlit Cloud (bitácora §8); **no trae cuotas de casa**; para 1X2/hándicap/total su información agregada ya está en el boxscore de ESPN | 0 € | alta pero pesada | descartada por memoria |
| APIs públicas de terceros | — | las 27 sondeadas en la v126 o piden clave de pago o no cubren NFL | — | — | descartada |
| ESPN (fixture) + PFR (stats) | — | resuelve un problema inexistente: ESPN da las dos cosas **con el mismo `event_id`**, que es justo lo que evita el desemparejamiento | — | — | innecesaria |

**Justificación de la elección:** cuesta cero, ya está integrada, y —lo
decisivo— usa **un solo identificador** para calendario, estadística y cuota.
La lección del tenis (Altenar `dst:player:NNN` ≠ StatsAPI) dice que mezclar
espacios de nombres es donde se pierde el dinero; combinar ESPN con PFR habría
introducido exactamente ese riesgo a cambio de nada.

### Dato descargado

```
historico_nfl.csv     1.055 partidos · 2023-01-01 → 2026-08-14 · 369 KB
  2022  regular 30 · playoffs 13
  2023  pretemporada 49 · regular 272 · playoffs 13
  2024  pretemporada 49 · regular 272 · playoffs 13
  2025  pretemporada 49 · regular 272 · playoffs 13
  2026  pretemporada 10

cobertura de estadísticas de equipo ...... 100,0 %
cobertura de moneyline de cierre .........  99,8 %
cobertura de total de cierre .............  99,9 %
cobertura de hándicap de cierre ..........  98,9 %
```

Coste de construirlo: 1.059 partidos × 1,7 s ≈ **30 minutos, una sola vez**.
Se refresca en incremental (sólo pide lo que falta), así que la actualización
semanal cuesta ~30 segundos.

### Un hallazgo operativo que costará tiempo a quien no lo sepa

ESPN **bloquea el User-Agent de Chrome completo y acepta el corto.** Medido,
tres peticiones al mismo evento:

```
'Mozilla/5.0'                                  → 200 · 467 KB
'Mozilla/5.0 (Windows NT 10.0…Chrome/126.0…)'  → 403 ·  442 B
sin cabecera                                   → 200 · 467 KB
```

Es al revés de lo intuitivo: imitar mejor a un navegador es lo que activa el
filtro. Copiar el UA de `cuotas_multi` (que va contra otras casas) habría
dejado el histórico entero sin descargar, con un 403 por partido y ningún
error visible más allá de un CSV vacío.

---

## 2. El modelo (PARTE 2 del encargo)

### Arquitectura

```
estado rodante por equipo (12 partidos, sin fuga)
    → dos regresiones ridge: MARGEN y TOTAL
        → distribución de residuos MEDIDA
            → 1X2 · hándicap · total · totales de equipo · margen por tramos
```

Se modela **margen y total**, no los dos marcadores por separado: los
marcadores de un partido comparten ritmo y modelarlos independientes infla la
varianza del total. Margen y total, en cambio, salen **casi ortogonales**
—correlación medida **−0,015** en 2025— y eso es lo que justifica la fórmula
del total por equipo:

```
Var(pts_home) = (Var(total) + Var(margen)) / 4      →   σ_equipo = 8,4
```

Con `σ_total/2` la dispersión habría salido un tercio corta.

### Los hiperparámetros se eligieron midiendo, y midiendo bien

Barrido de 48 combinaciones (ventana × arrastre × alpha) **sobre la temporada
2024 sola**, y el ganador juzgado después en **2025, que no participó en la
elección**:

| tramo | ventana | arrastre | alpha | log-loss |
|---|---|---|---|---|
| elección (2024) | 12 | 0,50 | 15 | 0,64355 ← ganador |
| **juicio (2025)** | **12** | **0,50** | **15** | **0,63514** |
| juicio (2025) | 8 | 0,35 | 5 | 0,64039 (defecto anterior) |

El ajuste elegido a ciegas **también gana en la temporada que no vio**. Eso es
una mejora real, no el artefacto de haber mirado el examen — que es lo que
pasó con el empate del fútbol (+12,21 % eligiendo, −7,09 % juzgando).

Dos hallazgos laterales:

- **`arrastre = 0` queda ÚLTIMO de las 48.** Empezar cada temporada de cero es
  la peor opción: la NFL regresa a la media con fuerza, pero no tanto como
  para tirar el año anterior entero.
- **La distribución empírica de residuos gana a la normal en las 48
  combinaciones**, sin una sola excepción (log-loss 0,63514 contra 0,64176 en
  la configuración final). Los números clave del fútbol americano —3 y 7— son
  reales y una normal no los ve.

### Calibración: el modelo está bien calibrado

Temporada 2025, fuera de muestra, n=285:

| banda | n | dice | acierta |
|---|---|---|---|
| 0,50-0,55 | 87 | 52,3 % | **54,0 %** |
| 0,55-0,60 | 58 | 57,3 % | **58,6 %** |
| 0,60-0,65 | 48 | 62,0 % | **62,5 %** |
| 0,65-0,70 | 39 | 67,6 % | **69,2 %** |
| 0,70-0,80 | 40 | 73,6 % | **72,5 %** |
| 0,80-1,00 | 12 | 83,8 % | 100 % (muestra corta) |

El error de calibración es de uno a dos puntos en todas las bandas con
muestra. **Y aun así pierde dinero**, que es exactamente el §0 de la bitácora
reproducido en un deporte nuevo con datos nuevos.

### Contra el mercado: pierde

| métrica | modelo | mercado (cierre devigado) |
|---|---|---|
| acierto del ganador | **63,0 %** | **66,5 %** |
| Brier | **0,2231** | **0,2119** |

Correlación entre el margen esperado del modelo y la línea de cierre:
**+0,77**. O sea que el modelo aprende señal real — sólo que menos de la que
ya está en el precio.

### ROI al precio de cierre real — ningún canal cruza el listón

Temporada 2025 (n=285 partidos), con las cuotas de cierre que publica ESPN:

| canal | n | acierto | ROI | **p5** |
|---|---|---|---|---|
| moneyline · lado del modelo | 285 | 62,8 % | −4,32 % | −12,16 % |
| moneyline · **EV del modelo > 0** | 86 | 48,8 % | **−1,62 %** | −20,52 % |
| moneyline · **EV del modelo > 5 %** | 66 | 45,5 % | **−2,07 %** | −24,98 % |
| moneyline · prob > 65 % | 91 | 74,7 % | −2,46 % | −12,93 % |
| moneyline · favorito del MERCADO | 285 | 66,3 % | −4,81 % | −12,01 % |
| hándicap · lado del modelo | 285 | 55,4 % | +5,96 % | **−3,36 %** |
| total · lado del modelo | 285 | 51,2 % | −2,21 % | −11,58 % |

**Ninguno tiene p5 positivo. El modelo va a Capa 2.**

Dos lecturas que hay que hacer explícitas:

1. **El EV del modelo es anti-indicador, otra vez.** Filtrar por EV>0 baja el
   acierto del 62,8 % al 48,8 %, y por EV>5 % al 45,5 %. Cuanto más valor
   declara el modelo, peor acierta. Es la misma firma que el fútbol
   (correlación −0,054 con el CLV) medida aquí de forma independiente.

2. **El hándicap luce +5,96 % y NO se despliega.** Es el canal que más cerca
   queda, y por eso hay que decir por qué se queda fuera:

   | temporada | n | acierto | ROI | p5 |
   |---|---|---|---|---|
   | 2024 | 285 | 50,2 % | **−4,88 %** | −14,66 % |
   | 2025 | 285 | 55,4 % | **+5,96 %** | −3,36 % |
   | ambas | 570 | 52,8 % | **+0,54 %** | −6,25 % |

   Una temporada gana, la otra pierde casi lo mismo, y el bootstrap dice que
   no se distingue del ruido. Es cara o cruz, no una ventaja.

### En PRETEMPORADA el modelo no publica probabilidad

Lo destapó el primer barrido real: **82,3 % a un Seattle–Dallas de
pretemporada**, que contra la cuota de la casa daba un EV de **+38 %** — la
firma exacta de `EV_SOSPECHOSO`. Medido sobre las pretemporadas de 2024 y
2025, entrenando sólo con temporadas anteriores:

| | n | acierto | Brier | corr(predicho, real) |
|---|---|---|---|---|
| liga regular 2025 | 271 | 62,7 % | 0,2239 | **+0,410** |
| **PRETEMPORADA** | 103 | 52,4 % | **0,2727** | **−0,013** |
| decir siempre 50 % | — | 50,0 % | 0,2500 | — |

No es que sea peor: **no tiene ninguna información**, y su Brier es PEOR que
el de una moneda. Así que en pretemporada las probabilidades se **borran** del
diccionario de salida (no se marcan y ya: bastaba con que uno de los seis
sitios que lo leen ignorara la bandera para que la cifra saliera a pantalla).
El partido sigue apareciendo con su precio y su comparación entre casas, que
no usan el modelo y funcionan igual.

---

## 3. Mercados de Playdoit (PARTE 3 del encargo)

`sportId = 75` en Altenar es fútbol americano entero: 78 eventos repartidos en
NCAAF (49), **NFL (17)**, **NFL Pretemporada (4)**, CFL (4), AFLE (2), IFL (1)
y EFA (1). Se filtra por nombre de campeonato (`ALTENAR_CAMPEONATOS`), porque
sin filtro el índice de la NFL contendría partidos universitarios y canadienses.

Los **10 mercados de la plantilla del usuario están los 10**, más uno:

| # | mercado de la casa | typeId | ¿cruza con el modelo? |
|---|---|---|---|
| 1 | Ganador (incl. prórroga) | 219 | **sí** |
| 2 | Hándicap (incl. prórroga) | 223 | **sí**, con empuje en línea entera |
| 3 | Totales (incl. prórroga) | 225 | **sí** |
| 4 | Totales individuales de equipo | 227/228 | **sí**, con varianza propia |
| 5 | 1ª Mitad · Apuesta sin empate | 64 | precio sí, EV **no fiable** |
| 6 | 1ª Mitad · Hándicap | 66 | precio sí, EV **no fiable** |
| 7 | 1ª Mitad · Total | 68 | precio sí, EV **no fiable** |
| 8 | Primer cuarto · Apuesta sin empate | 302 | precio sí, EV **no fiable** |
| 9 | Primer equipo en marcar | 11074 | precio sí, **sin modelo** |
| 10 | Margen de victoria (incl. prórroga) | 290 | **sí**, por tramos |
| — | Mitad/final | 47 | precio sí, **sin modelo** |

Medido sobre los cuatro partidos de pretemporada del 2026-08-15: **12 mercados
por partido** con el tablero completo, **43 filas** tras traducir (24 con
probabilidad del modelo, 19 con precio y sin EV).

**Por qué los tiempos van con el EV marcado:** el modelo predice el partido
completo, y repartir su margen y su total entre mitades y cuartos exigiría una
proporción medida que **no existe** (la NFL no reparte 50/50; el reloj de dos
minutos carga el segundo y el cuarto periodo). Inventarla es el fallo que la
v123 encontró en el fútbol. El precio sí se publica —sirve para armar un boleto
en una sola casa— y el EV va marcado `ev_no_fiable`.

Los partidos de liga regular a semanas vista traen sólo 3 mercados en el
catálogo (ganador, hándicap, total); los 12 aparecen conforme se acerca el
partido. Es comportamiento de la casa, no del extractor.

### Consenso: 3 casas en liga regular

| casa | partidos NFL | vía |
|---|---|---|
| Pinnacle | 55 (sport 15, filtrado por nombre) | API de widget |
| Playdoit | 21 (sport 75, campeonatos NFL) | Altenar |
| Bovada | 16 (`football/nfl`) | API pública |
| Matchbook | 0 | sport 1 declarado; sin eventos NFL en agosto |

Con tres casas se cumple el mínimo de dos que exige el semáforo verde.
Matchbook queda declarado y se medirá su frecuencia en temporada.

---

## 4. Mapeo de nombres — la parte crítica

Playdoit escribe los equipos abreviados y con basura de tabulación:
`NE  Patriots`, `SF 49ers\t\t`, `ARZ Cardinals`, `WAS Commanders\t\t`. Tres
trampas concretas que un emparejador por parecido resuelve MAL:

- `LA Rams` y `LA Chargers` comparten prefijo de ciudad.
- `NY Jets` y `NY Giants`, lo mismo.
- `ARZ Cardinals` — Playdoit usa **ARZ** donde ESPN usa **ARI**. Ninguna
  abreviatura estándar dice ARZ, así que casar por abreviatura falla en
  silencio.

### Fallo real encontrado y corregido: «Wroclaw Panthers» → Carolina

La primera versión aceptaba «el apodo aparece entre las palabras», con el
argumento de que los 32 apodos son únicos **entre sí**. Y lo son — pero no en
el mundo. El propio catálogo de Altenar, en el mismo `sportId=75`, trae la liga
europea:

```
«Wroclaw Panthers»  →  CAR  (Carolina Panthers)   ← MAL
«London Warriors», «Rhein Fire», «Paris Musketeers»…
```

Un partido de la AFLE habría entrado al índice de la NFL con el equipo
equivocado y producido un EV inventado. **Se quitó la relajación entera**: los
32 apodos sueltos ya están en la tabla de alias como claves exactas, así que lo
único que se pierde es la capacidad de adivinar. Lo que no está mapeado se
descarta y se registra en `nombres_sin_mapear.json`.

### Fallo real encontrado y corregido: colisión MLB/NFL

`normalizar` expandía abreviaturas con un diccionario **plano** de MLB. Catorce
ciudades tienen equipo en los dos deportes (KC, SF, TB, SEA, PIT, PHI, MIN,
MIA, DET, CLE, CIN, BAL, ATL, HOU, WSH), así que «KC Chiefs» habría salido como
**«kansas city royals»** — un equipo de otro deporte, sin dar el menor error.

Se resolvió **por apodo**: la abreviatura propone candidatos y gana aquel cuyo
nombre completo contiene el resto del texto. Verificado en las dos direcciones:

```
KC Chiefs      → kansas city chiefs      KC Royals     → kansas city royals
SF 49ers       → san francisco 49ers     SF Giants     → san francisco giants
TB Buccaneers  → tampa bay buccaneers    TB Rays       → tampa bay rays
DET Lions      → detroit lions           DET Tigers    → detroit tigers
```

### Fallo real encontrado y corregido: el registro que se borraba solo

`nombres_sin_mapear.json` tiene formato `{nombre: {contexto, visto}}` y
`name_mapper.volcar_fallos` purga cada 30 días leyendo `visto`. La primera
versión metía un sub-diccionario con contadores: no rompía nada, pero al no
tener `visto` la purga lo daba por caducado y **lo borraba en el siguiente
vuelco**. Un registro que parece funcionar y desaparece solo es peor que no
registrar, porque da la falsa impresión de que se está vigilando.

`VENTAJA_IMPOSIBLE` (0,30) está activa para la NFL desde el primer día, como
segunda red.

---

## 5. Interfaz (PARTE 4 del encargo)

- **Filtro global**: `[Todo] [⚽] [⚾] [🏀] [🎾] [🏈]` — y como el resto, filtra
  en el punto de pintado, **no** el barrido: Telegram y la exportación siguen
  llevando todo.
- **Pestañas «Partidos de hoy» y «de mañana»**: la NFL publica `pronosticos`
  con **todos** los partidos del día (no sólo los que pasan umbral), así que
  aparecen con su barra visual. En pretemporada la barra dice «sin pronóstico
  del modelo», que es exactamente lo que hay.
- **Vista propia `🏈 NFL (fútbol americano)`** con tres pestañas: predicción +
  tablero de la casa cruzado, forma y H2H, y EV+ automático.
- **H2H visual**: `h2h_visual` pasa a tener perfiles por deporte. El de NFL
  dibuja **puntos a favor/en contra, yardas, yardas por jugada y pérdidas**; el
  de fútbol conserva goles, córners, tarjetas y tiros — su ficha no cambia ni
  un píxel. Se corrigió de paso el tope fijo de las barras (6,0, heredado de
  los córners), que con yardas de 400 habría salido siempre llena.
- **Secciones y parlays**: los picks de NFL llevan `deporte: 'NFL'` y pasan por
  `clasificador.secciones_del_dia`, `parlay_ev` y `cross_sport_parlay` sin
  cambios — ese último es agnóstico del deporte por diseño.

---

## 6. Coste y validación (PARTE 5 del encargo)

### Coste del barrido

```
_picks_nfl  ....... 1,2 s   (7 partidos, 4 con dos casas para comparar)
```

Corre **en paralelo** con las otras cinco ramas (`ThreadPoolExecutor`), así que
no suma al total: el techo sigue siendo la rama más lenta, que es el fútbol.
Aceptable con mucho margen.

### Validación ejecutada

| prueba | resultado |
|---|---|
| `test_catalogo_y_cuotas.py` (~760 checks + 7 bloques nuevos de NFL) | ver §7 |
| `smoke_botones.py` (8 vistas, NFL incluida) | ver §7 |
| AppTest de la vista NFL, con y sin histórico | **OK** — degrada con aviso cuando falta el CSV |
| AppTest pulsando «Cargar» sobre un partido de pretemporada | **OK** — probabilidades a «—» y el motivo medido en pantalla |

Los siete bloques nuevos del test cubren, cada uno, un fallo **real** de esta
sesión: el mapeo de nombres, la colisión MLB/NFL, la invención de mercados, la
coherencia de probabilidades, la fuga temporal, la regla de Sección 1 y el
cableado.

**La comprobación de fuga temporal** construye el dataset dos veces —con el
histórico entero y truncado justo tras el partido de control— y exige que sus
features sean idénticas. Un backtest con fuga da un número bonito y una apuesta
perdedora.

---

## 7. El canal de PRECIO en NFL: no medible todavía, y eso no es lo mismo que negativo

`clasificador.canal_del_pick` manda a la Sección 2 todo pick de precio que no
sea fútbol, con el motivo «el mismo método pero SIN medir». «Sin medir» no es
un estado permanente, es una tarea — así que se intentó hacerla
(`nfl_lineshop.py`): descargar el cierre de **todas** las casas por partido y
medir el canal igual que en fútbol, con elección en las temporadas antiguas y
juicio en la reciente.

Se descargaron **2.906 cierres de 12 casas sobre 897 partidos**. Y el reparto
es el que decide el asunto:

| casa | 2022 | 2023 | 2024 | 2025 | margen medio |
|---|---|---|---|---|---|
| ESPN BET | 43 | 285 | 284 | 193 | 4,17 % |
| DraftKings | — | 206 | — | 94 | 4,32 % |
| Titanbets | — | 207 | — | — | 3,56 % |
| Caesars (CO / NJ / TN) | — | 207 c/u | — | — | 4,25 / 4,26 / 7,79 % |
| MGM · SugarHouse · Unibet · accuscore · PointsBet | — | 145-207 | — | — | 3,88-5,37 % |

**Partidos con dos o más casas: 207 en 2023, 2 en 2025, ninguno en 2024.**

ESPN conserva el histórico multi-casa **sólo de la temporada 2023**; desde 2024
guarda casi únicamente la suya. Sin dos precios no hay line shopping, así que
no hay tramo de juicio y **no hay nada que medir**.

El veredicto que escribe `nfl_canal_precio.json` lo dice con esas palabras:
`medible: false`, y `clasificador` lo trata igual que si no existiera — la NFL
se queda en la Sección 2, que es el camino por defecto. Lo que cambia es el
**motivo**, y el motivo es lo que distingue una tarea pendiente de un callejón
cerrado.

Se resistió la tentación de publicar el número que sí salía (63 apuestas,
−21,05 % de ROI, todas dentro de 2023 y sin tramo de juicio). Con esa muestra
y sin partición, ese número no dice ni que sí ni que no.

**Cómo se desbloquea:** `daily_snapshots.py` ya guarda una foto diaria por
partido y por casa. En cuanto acumule un par de meses de NFL con Pinnacle,
Bovada y Playdoit dentro, el canal se mide con datos propios y este mismo
script devuelve un veredicto de verdad. Es la vía que la bitácora §6 ya
señalaba como la única prometedora a medio plazo.

---

## 8. Qué queda pendiente y por qué

1. **Matchbook no devuelve eventos NFL** (sport id 1 declarado, 0 partidos en
   agosto). Hay que medir su cobertura en temporada regular antes de decir si
   sirve como cuarta casa.
2. **El canal de precio** — ver §7. Se desbloquea con fotos propias, no con
   una fuente nueva.
3. **El reparto por cuarto** no está medido, y hasta que lo esté el EV de
   mitades y cuartos seguirá marcado como no fiable. El dato está en el
   `scoringPlays` de ESPN, así que es medible; no se ha hecho en esta versión.

---

## 9. Lo que NO se ha hecho, y por qué

- **No se ha metido la NFL en la Sección 1 por EV del modelo.** Es el criterio
  medido aquí en −1,62 % y −2,07 % de ROI, con acierto por debajo del 50 %.
- **No se ha desplegado el canal de hándicap** pese a su +5,96 % en 2025: su
  otra temporada da −4,88 % y su p5 es negativo en las dos.
- **No se ha prometido que el modelo bata al mercado.** No lo bate: 63,0 %
  contra 66,5 % de acierto, Brier 0,2231 contra 0,2119.
- **No se ha añadido ninguna dependencia nueva.** Ni pyarrow, ni scikit-learn
  extra: la ridge está escrita a mano y el artefacto del modelo es un JSON de
  **11,9 KB** que se carga con `json.load`.
