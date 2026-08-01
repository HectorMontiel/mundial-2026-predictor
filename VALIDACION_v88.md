# VALIDACIÓN v88 — Telegram tumbaba la app, y los picks de «MLB» eran de Taiwán

Fecha: 2026-07-31 · Remotos: `origin` (HMREY) + `upstream` (HectorMontiel)

---

## 1. La app se caía al enviar a Telegram

`bot_telegram.construir_mensaje()` llamaba a
`alpha_finder.apuestas_del_dia_universal()` por su cuenta, saltándose el
guardia de proceso de la v86. Como el dashboard ya tenía el barrido en memoria,
pulsar el botón lanzaba un **segundo barrido completo** dentro de Streamlit:

| | pico de RSS |
|---|---|
| 1 barrido | 1.297,7 MB |
| 2 barridos | **2.172,2 MB** |

No fallaba el envío: fallaba la memoria de rehacer un trabajo ya hecho.

Medido antes y después (`_v88_telegram_memoria.py`):

| | barridos que provoca el botón |
|---|---|
| antes | **1** |
| ahora | **0** |

`construir_mensaje` acepta ahora el barrido ya calculado, y el dashboard se lo
pasa. Sin argumento —el caso del runner de GitHub Actions— pasa por el guardia
en vez de llamar a `alpha_finder` a pelo: dos llamadas seguidas provocan **un**
barrido, no dos. El mensaje sale idéntico.

---

## 2. Los picks de «MLB» no eran de MLB

### 2.1 Lo que llegaba a la Capa 1

```
Rakuten Monkeys @ Uni-President 7-Eleven Lions   cuota 1.7408
Rakuten Monkeys @ Uni-President Lions            cuota 1.7408
```

Eso es la **CPBL de Taiwán**, no la MLB. Y es el mismo partido dos veces: el
nombre del rival cambia entre casas y la clave de deduplicación
—`codigo_mlb(nombre)`— devolvía el nombre crudo cuando el fuzzy no llegaba a
0,60, así que contaban como equipos distintos.

Inventario del tablón de cuotas «mlb» (`_v88_que_hay_en_el_tablon_mlb.py`):

| | |
|---|---|
| entradas en Pinnacle + Bovada + Playdoit | 80 |
| **partidos de MLB de verdad** | **16** |
| entradas que NO son MLB | **64** |

El resto es Liga Mexicana, NPB (Japón), KBO (Corea), CPBL (Taiwán) y Triple-A.
El edge de `valor_vs_sharp` en béisbol se midió sobre **27.977 juegos de MLB**;
operar esas otras ligas con él es extrapolar.

### 2.2 Y había algo peor: falsos positivos

El fuzzy con umbral 0,60 daba por equipos de MLB a un **10 %** de los equipos
de otras ligas (`_v88_falsos_positivos_mlb.py`):

| equipo | liga | se identificaba como |
|---|---|---|
| Chiba Lotte **Marines** | NPB | SEA — Seattle **Mariners** |
| Kia **Tigers** | KBO | DET — Detroit **Tigers** |
| Fubon **Guardians** | CPBL | CLE — Cleveland **Guardians** |
| Sacramento River Cats | Triple-A | OAK — Oakland Athletics |
| Tacoma **Rainiers** | Triple-A | TEX — Texas **Rangers** |

`codigo_mlb` es la puerta por la que los nombres de las casas entran al
**MOTOR**, así que un partido de la KBO se predecía con las estadísticas de
Detroit y entraba a la Capa 1 etiquetado «MLB».

### 2.3 El arreglo

Umbral del fuzzy a **0,90**, tabla de alias de casas declarada a mano, y dos
funciones que no adivinan: `es_equipo_mlb` y `es_partido_mlb`.

| | antes | después |
|---|---|---|
| equipos de otras ligas dados por MLB | **5 de 50 (10 %)** | **0** |
| equipos de MLB reales que se reconocen | 30 de 30 | **30 de 30** |

### 2.4 Y entonces MLB entró de verdad

Con el filtro puesto, el barrido evalúa **15 partidos de MLB** (los 64 ajenos se
descartan y se dice en las incidencias). Hoy no produce picks, y conviene
explicar por qué, porque no es un fallo:

| vía | resultado de hoy |
|---|---|
| valor de mercado | 15 partidos comparados con Pinnacle, **0 con precio descolgado** |
| modelo | 15 evaluados, prob máxima **61,3 %** (umbral 58 %) pero **todos los EV negativos**, de −1,97 % a −6,33 % |

Es decir: el modelo sí llega al umbral de probabilidad, pero el mercado paga
peor que su ventaja. **No se bajan los umbrales para forzar picks**: serían
apuestas de EV negativo. MLB está conectada y dará picks el día que haya valor.

---

## 3. Un bug de concurrencia que dejaba MLB fuera (introducido en v87)

Al arreglar lo anterior apareció esto en el barrido:

```
MLB omitido por error: OSError: exception: access violation reading 0x0
```

MLB funcionaba en aislamiento, y también en secuencia fútbol → MLB. Sólo
fallaba en el barrido completo.

**Causa**: `modelos_portables.cargar` parchea `Booster.__setstate__`, que es
**global al proceso**, y `apuestas_del_dia_universal` corre sus cuatro ramas en
un `ThreadPoolExecutor(max_workers=4)`. Mientras el hilo de fútbol tenía el
parche puesto para reparar un modelo de liga, el hilo de MLB cargaba **su**
modelo a través del parche ajeno. La violación de acceso saltaba después,
dentro de `XGBoosterPredict`.

Dos arreglos:

1. **Cerrojo** alrededor de la reparación, para que dos hilos no se pisen el
   parche ni su restauración.
2. El parche **comprueba la identidad del hilo** y delega en el original si la
   llamada viene de otro. Así, aunque esté puesto, sólo afecta al `joblib.load`
   que lo pidió.

De paso se corrigieron dos cosas más del mismo módulo:

- El espía dejaba `handle` con los **bytes** del buffer en vez de `None`, y
  `Booster.__del__` intentaba liberarlos como puntero
  (`ArgumentError: Don't know how to convert parameter 1`), en un momento
  impredecible.
- La reconstrucción **trasplantaba handles** entre objetos
  (`self.handle = tmp.handle; tmp.handle = None`). Ahora cada Booster crea y
  conserva el suyo, usando sólo la API pública.

Regresión permanente en `test_concurrencia.py`: ocho modelos reparándose en
paralelo y, después, MLB prediciendo.

---

## 4. The Odds API, retirada

La clave devolvía **401 en las 25 competiciones**, así que no traía nada: sólo
llenaba el arranque de cada sesión con un error por liga.

Y no hace falta. Las cuotas vienen desde la v71/v72 de `cuotas_multi`
(Pinnacle + Bovada + Playdoit) y de los fixtures de ESPN. Medido el mismo día
de la retirada: **Pinnacle 881 partidos de fútbol, 64 de tenis, 39 de MLB y 57
de NBA**; The Odds API, 0.

Se eliminan `odds_api.py`, `cross_arbitrage.py` (colgaba entera de esa API, y
su botón decía «usa ~5 créditos» cuando ya no había créditos) y
`props_scraper.py` (sin ningún llamador).

Lo que se **conserva**, porque no toca la red:

- `sharp_gap_2via` se muda a `cuotas_multi`, junto a `devig`, que es lo mismo
  generalizado a tres vías. Mismo resultado.
- `fetch_odds.cargar_features_cuotas` sigue leyendo `odds_historicas.csv` para
  las features de cuotas del entrenamiento. Borrarla habría cambiado el modelo
  entrenado.

El eslabón de NBA se sustituye por `cuotas_multi`, y la ventana de temporada
(octubre-junio), que vivía en `odds_api`, se declara en `alpha_finder`.

---

## 5. «Apuestas del Día»: sólo las próximas 24 horas

El corte era de 72 h **desde medianoche**, así que entraban partidos de pasado
mañana que todavía no cotizaban — de ahí que la pestaña mezclara picks con
cuota real y picks con cuota sólo justa.

Para acotarlo de verdad hacía falta la **hora de inicio**, y resultó que ESPN
la publica y `fixtures_espn` la estaba **tirando** al formatear a `'%Y-%m-%d'`.
Con la fecha a secas no se puede distinguir un partido de dentro de una hora de
otro de mañana por la noche. Ahora se conserva en `inicio` (UTC), sin tocar
`fecha`.

La ventana se cuenta desde el momento de la consulta, con un margen de 3 h
hacia atrás para que un partido recién empezado —apostable en vivo— no
desaparezca de golpe.

Resultado del barrido tras el cambio (`_v88_verifica_barrido.py`):

| | |
|---|---|
| picks con fecha a más de 1 día vista | **0** |
| Capa 1 con cuota real | **todos** |
| rastro de The Odds API en los logs | **0 líneas** |
| partidos de MLB duplicados | **0** |

Las vistas por deporte y por liga **no cambian**: siguen con su ventana amplia,
que es donde tiene sentido mirar la semana.

---

## 6. Resumen

| cambio | evidencia |
|---|---|
| Telegram reutiliza el barrido | el botón provocaba 1 barrido extra (+1,3 GB), ahora 0 |
| Filtro estricto de MLB | 64 de 80 entradas del tablón no eran MLB; falsos positivos 10 % → 0 % |
| Reparación de modelos segura entre hilos | reproducía `access violation` y dejaba MLB fuera del barrido |
| The Odds API retirada | 401 en 25 ligas; 0 líneas de error tras la retirada |
| Ventana de 24 h con hora real de inicio | 0 picks a más de un día vista; toda la Capa 1 con cuota |

| **no se hizo, y por qué** |
|---|
| Bajar los umbrales de MLB para que salgan picks hoy: los EV de hoy van de −1,97 % a −6,33 %. Forzarlos sería desplegar apuestas de EV negativo. |
| Operar LMB, NPB, KBO o CPBL con la vía de valor: su edge se midió sobre 27.977 juegos **de MLB**. Extrapolarlo no está validado. |

Las cinco suites en verde: `test_catalogo_y_cuotas.py`, `test_simetria.py`,
`test_match_parlay.py`, `smoke_botones.py` y `test_concurrencia.py`.
