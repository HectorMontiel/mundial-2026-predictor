# v102 — El lazo se cierra en todos los deportes, y tres hipótesis medidas

Seis frentes pedidos. Dos se cierran con mejora desplegada, dos se cierran con
un **no** medido, y dos con un límite de datos documentado. Todo con números.

---

## 1. Próximos partidos en todas las competiciones — ARREGLADO

**El síntoma:** «la Champions y demás ligas no obtienen automáticamente los
siguientes partidos».

No era un fallo de red. Eran dos causas distintas:

**(a) Las fases previas son otra competición para ESPN.** En agosto la Champions
está en fase previa, publicada bajo un código diferente. Medido el 2026-08-06
pidiendo agosto-noviembre:

| competición | código de la fase actual | eventos | código de la previa | eventos |
|---|---|---|---|---|
| Champions | `uefa.champions` | 0 | `uefa.champions_qual` | **10** |
| Europa League | `uefa.europa` | 0 | `uefa.europa_qual` | **23** |
| Conference | `uefa.europa.conf` | 0 | `uefa.europa.conf_qual` | **57** |
| AFC Champions | `afc.champions` | 0 | `afc.champions_qual` | **4** |

**94 partidos reales** que la app no veía porque preguntaba por una fase que aún
no ha empezado.

**(b) La ventana era de 7 días fijos**, así que toda liga entre temporadas salía
vacía: Premier 0, Bundesliga 0, Serie A 0 — cuando a 30 días tenían 28, 16 y 24.

**La solución:** códigos compañeros (`ESPN_COMPANEROS`) + horizonte progresivo
(`HORIZONTES = 7, 30, 90`). Resultado:

| competición | antes | después | primer partido |
|---|---|---|---|
| Champions | 0 | **10** | 2026-08-11 |
| Europa League | 0 | **23** | 2026-08-06 |
| Conference | 0 | **57** | 2026-08-06 |
| Premier | 0 | **28** | 2026-08-21 |
| LaLiga | 8 | **35** | 2026-08-15 |
| Liga MX | 9 | **34** | 2026-08-15 |

**La ampliación es opt-in**, y eso importa: `alpha_finder._barrido_fixtures` pide
`dias=2` justamente para quedarse con los de hoy. Ampliarle el horizonte le haría
pedir 90 días a cada liga fuera de temporada en cada pase para tirarlo todo
después. Con `ampliar=None` sólo se amplía en la vista de próximos partidos.

**Efecto colateral bueno:** el barrido diario también gana. Europa League pasa de
0 a 10 partidos evaluables hoy, gracias al código compañero.

**Polonia** sigue sin próximos partidos y se declara: ESPN devuelve 400 en
`pol.1`, `pol.2` y `pol.ekstraklasa`. No hay fuente, y se dice en vez de fingir.

### Un bug de la v91 que llevaba once versiones a medio arreglar

Al mover el anclaje UTC de sitio hubo que tocar el test que lo vigilaba, y se
aprovechó para endurecerlo: en vez de comprobar que `utcnow` aparezca cerca de
`fixtures_liga`, ahora se exige que **el módulo entero no use el reloj local**.

Saltó al momento: **tres llamadas a `.today()` en `fixtures_espn.py`**.

La v91 documentó y arregló exactamente este fallo —el rango de fechas de ESPN se
construía con la hora local, y en cualquier huso por detrás de UTC empezaba un
día tarde, dejando «partidos evaluados: 0»— pero sólo lo corrigió en
`fixtures_liga`. Seguían con el reloj local:

- la ruta de **fixtures de MLB**,
- la ruta de **selecciones**,
- y el cálculo de «vuelve tal día a ver el precio», que comparaba un `hoy` local
  contra fechas de fixtures que son UTC.

En Streamlit Cloud el servidor va en UTC y por eso nunca se vio allí. Corregidas
las tres. El test lo impide en adelante.

---

## 2. La brecha de la Capa 2 — CERRADA, y no donde se creía

**El punto de partida:** Capa 2, 108 picks, 58,3 % real contra 74,5 % prometido
(−16,2 pp). La hipótesis era «extender la corrección por banda a la Capa 2».

**Primer A/B — RECHAZADO.** Sobre `pick_ledger_total.csv` (120.077 predicciones
en 1X2 y moneyline), corregir empeora en los cuatro umbrales:

| umbral | brecha cruda | brecha corregida | p5 | veredicto |
|---|---|---|---|---|
| ≥0,65 | +0,0013 | +0,0104 | −0,0149 | RECHAZAR |
| ≥0,70 | −0,0011 | +0,0062 | −0,0123 | RECHAZAR |
| ≥0,75 | −0,0099 | −0,0018 | −0,0081 | RECHAZAR |
| ≥0,80 | −0,0116 | −0,0044 | −0,0118 | RECHAZAR |

Ahí el modelo **ya está calibrado**. Pero entonces, ¿de dónde salía el −16,2 pp?

**Se estaba midiendo el mercado equivocado.** Los 108 picks de Capa 2, abiertos:

| deporte | mercado | n | acierto |
|---|---|---|---|
| Fútbol | **Goles** | 29 | 0,517 |
| Fútbol | **BTTS** | 22 | 0,500 |
| Fútbol | 1X2 | 6 | 0,167 |
| Tenis | Ganador | 51 | 0,706 |

La Capa 2 de fútbol **no es 1X2**: son Goles y BTTS. Y ésos viven en otro ledger.

**Segundo A/B, sobre los mercados correctos — ADOPTAR en los cuatro umbrales.**
Sobre 143.382 predicciones fuera de muestra, simulando LAS DOS SELECCIONES (no
sólo la etiqueta, porque la Capa 2 se selecciona por probabilidad):

| umbral | A · cruda | B · corregida | p5 |
|---|---|---|---|
| ≥0,65 | n=26.181 · promete 75,4 % · entrega 66,3 % (**−9,1**) | n=13.718 · promete 71,3 % · entrega **71,8 %** (+0,5) | +0,0780 |
| ≥0,70 | n=18.436 · promete 78,8 % · entrega 69,3 % (**−9,5**) | n=7.225 · promete 74,9 % · entrega **75,1 %** (+0,3) | +0,0820 |
| ≥0,75 | n=12.172 · promete 82,1 % · entrega 71,5 % (**−10,6**) | n=2.933 · promete 78,7 % · entrega **77,8 %** (−0,9) | +0,0831 |
| ≥0,80 | n=7.194 · promete 85,3 % · entrega 74,1 % (**−11,2**) | n=837 · promete 82,7 % · entrega **78,9 %** (−3,8) | +0,0484 |

Dos cosas a la vez: la brecha casi desaparece **y el acierto real de lo
seleccionado sube** (69,3 % → 75,1 % a umbral 0,70), porque la corrección deja
fuera justo los picks sobreconfiados.

**Desplegado:** la corrección entra en `alpha_finder` **antes** del filtro de
confianza, no al enseñar. Corregir sólo la etiqueta dejaría entrando a los mismos
picks con un número más bonito. Y se añade una guarda contra la doble corrección:
un pick ya recalibrado no vuelve a pasar por la tabla por banda.

---

## 3. Aprendizaje autónomo en todos los deportes — DESPLEGADO

**Lo pedido:** que el aprendizaje sea automático con los resultados que van
llegando, y que valga para todos los deportes.

**El problema de la lista a mano:** `MERCADOS_VALIDADOS = {Goles, BTTS}` se fijó
con el A/B de arriba, pero congelarla no escala: la NBA y la KBO todavía no
tienen ledger, y el día que lo tengan alguien tendría que acordarse de volver a
editarla.

**La solución:** `validar_segmentos()` rehace el mismo A/B —walk-forward,
aprender sólo con el pasado, bootstrap pareado— para **cada par (deporte,
mercado) que tenga muestra**, en cada recalibración. El listón no se relaja: un
segmento entra si su p5 es positivo con al menos 1.000 casos, y sale en cuanto
deje de serlo.

Veredicto actual, decidido por el propio sistema:

| deporte y mercado | n | brecha antes | brecha después | p5 | veredicto |
|---|---|---|---|---|---|
| Fútbol · Goles | 95.617 | 0,0502 | **0,0054** | +0,00941 | **ADOPTAR** |
| Fútbol · BTTS | 47.816 | 0,0834 | **0,0216** | +0,02442 | **ADOPTAR** |
| MLB · Ganador | 7.547 | 0,0170 | **0,0127** | +0,00005 | **ADOPTAR** |
| Tenis · Ganador | 64.577 | 0,0053 | 0,0151 | −0,00081 | RECHAZAR |
| Fútbol · 1X2 | 47.971 | 0,0032 | 0,0018 | −0,00011 | RECHAZAR |

**La MLB entró sola.** Nadie la añadió: pasó el listón y el sistema la autorizó.
NBA y KBO se incorporarán el día que tengan historial suficiente, sin tocar
código.

**Un fallo silencioso corregido por el camino:** el ledger de MLB etiqueta el
mercado como `Ganador` y los picks publicados como `Moneyline`. Con nombres
distintos, la validación autorizaba `MLB|Ganador` y `aplicar_a_pick` buscaba
`MLB|Moneyline`, no lo encontraba y no corregía nada. Se añade `ALIAS_MERCADO`.
No se unifican 1X2 y Ganador: tres vías y dos vías tienen calibraciones
distintas, y promediarlas no describiría a ninguna.

### «Que un equipo sea inferior no significa que pierda» — MEDIDO, y sale al revés

La intuición es correcta como principio y vacía como instrucción: hay que decir
**en qué casos** pasa más de lo que el modelo cree. `autopsia_underdogs()` lo
mide sobre 36.006 partidos con cuota real, tomando el lado que el mercado paga
más caro.

**El modelo no infravalora al desfavorecido: lo SOBREVALORA.** En los 19
segmentos con brecha estadísticamente firme, las 19 son negativas:

| segmento | n | consigue | el modelo le da | brecha |
|---|---|---|---|---|
| juega en casa | 10.572 | 25,9 % | 30,1 % | **−4,2 pp** |
| lo dan de menos por mucho (>8) | 2.203 | 6,4 % | 10,8 % | **−4,4 pp** |
| lo dan de menos (5-8) | 5.863 | 13,9 % | 17,2 % | **−3,4 pp** |
| Europa League | 101 | 17,8 % | 32,3 % | **−14,5 pp** |
| Bundesliga | 741 | 20,8 % | 25,9 % | −5,1 pp |

Apostar más al desfavorecido porque «puede ganar» perdería dinero de forma
sistemática. La lección medida es la contraria: el modelo ya es demasiado
generoso con él, sobre todo cuando juega en casa y cuando la diferencia es
grande.

---

## 4. El IDF en fútbol y NBA — RECHAZADO en los dos

### Fútbol: 27 combinaciones, 27 rechazos

Se midieron las tres formas de puntuar el empate (3-1-0 normalizado, 1-0,5-0 del
ELO, y sólo victorias) × tres ventanas (5, 10, 15) × tres mercados, sobre 47.948
predicciones fuera de muestra con la probabilidad del modelo desplegado en la
base. **Ninguna combinación alcanza p5 > 0.** Las mejoras oscilan entre −0,00009
y +0,00024, con p5 siempre negativo.

La forma descontada por dificultad de calendario no aporta nada al fútbol por
encima de lo que el modelo ya tiene.

### NBA: positivo contra el ELO, rechazado contra el motor

| base | ventana 5 | ventana 10 | ventana 15 |
|---|---|---|---|
| contra el ELO rodante | p5 **+0,00038** | p5 **+0,00058** | p5 **+0,00014** |
| **contra el vector desplegado (9 features)** | p5 **−0,00074** | p5 **−0,00098** | p5 **−0,00037** |

El motor de la NBA ya lleva `DIFF_STREAK`, `DIFF_REST` y `DIFF_B2B`. La ganancia
aparente sobre el ELO era información de forma que el modelo **ya tenía**.

Es exactamente la lección de la v99.2: la v99.1 midió el IDF de tenis contra una
base de dos features y salió muy positivo; repetido contra el vector real la
mejora cayó a una décima parte. Aquí, medido bien, desaparece del todo.

**Si se hubiera adoptado por el primer resultado, se habría desplegado ruido.**

---

## 5. Factor de parque de la KBO en totales — BLOQUEADO POR DATOS

No hay cuotas de totales de KBO, y no es por falta de intentarlo:

- `cuotas_kbo_cierre.csv` tiene 207 filas y **ninguna columna de over/under**:
  sólo `odd_home` y `odd_away`.
- La ruta plana de over/under en BetExplorer devuelve **404**
  (`/baseball/south-korea/kbo-2025/ou/`).
- Su `robots.txt` (leído hoy) prohíbe todas las cadenas de consulta —`?stage=`,
  `?page=`, `?year=`…— que es donde vive el resto.

El techo sigue siendo el que documentó la v98: ~16 partidos de playoff por
temporada, 207 en total, y sólo a moneyline. **Sin línea de totales no hay nada
que backtestear**, y con esa muestra tampoco habría potencia para concluir.

Queda pendiente de que aparezca una fuente con over/under de KBO en superficie
permitida. No se fuerza.

---

## 6. Estadísticas avanzadas de KBO — UNA VÍA CERRADA, OTRA ABIERTA

**Statiz: descartado por su propia política.** El dominio que la v98 dio por
muerto (`statiz.sporki.com`) sigue sin resolver, pero **`www.statiz.co.kr`
responde HTTP 200**. Su `robots.txt`, sin embargo, es explícito:

```
User-agent: *            → Disallow: /
User-agent: ClaudeBot    → Disallow: /
User-agent: anthropic-ai → Disallow: /
User-agent: Claude-Web   → Disallow: /
Content-Signal: search=yes, ai-train=no, use=reference
```

El sitio prohíbe la recolección automatizada y nombra específicamente a los
agentes de Anthropic. **No se scrapea.** OPS y FIP tendrán que venir de otro
sitio o de ninguno.

**Naver (bullpen): viable, pero falta un paso previo.** La API que el proyecto ya
usa (`api-gw.sports.naver.com`) no publica `robots.txt` (404), que es la
situación que `kbo_naver.py` documentó y bajo la que ya opera. El obstáculo es
otro: **`historico_kbo.csv` no guarda el id de partido** (sus columnas son
`date, home_team, away_team, estadio, home_runs, away_runs, home_pitcher,
away_pitcher`), y sin él no se puede pedir el box score.

El camino concreto, en orden: (1) ampliar `kbo_naver.py` para que persista el
`gameId` al construir el histórico; (2) recorrer los box scores de esos ids;
(3) derivar carga y efectividad del bullpen; (4) A/B con el protocolo de siempre.
Sin el paso 1 los demás no existen.

---

## Resumen de lo desplegado y lo rechazado

| pieza | estado |
|---|---|
| Códigos de fase previa + horizonte progresivo | **DESPLEGADO** — 94 partidos que no se veían |
| Corrección de calibración en Capa 2 (Goles/BTTS) | **DESPLEGADO** — brecha −9,5 pp → +0,3 pp |
| Autovalidación por segmento (todos los deportes) | **DESPLEGADO** — MLB entró sola |
| `ALIAS_MERCADO` (Moneyline ≡ Ganador) | **DESPLEGADO** — corregía a nadie sin esto |
| Corrección en 1X2 / Ganador / Tenis | **RECHAZADO** — ya están calibrados |
| IDF en fútbol | **RECHAZADO** — 27 de 27 combinaciones |
| IDF en NBA | **RECHAZADO** — contra el motor real, p5 negativo |
| Apostar más al desfavorecido | **RECHAZADO** — el modelo ya lo sobrevalora |
| Factor de parque KBO en totales | **BLOQUEADO** — no existe la cuota |
| Statiz (OPS/FIP) | **DESCARTADO** — su robots.txt lo prohíbe |
| Bullpen desde Naver | **PENDIENTE** — falta persistir el `gameId` |

## Scripts de esta versión

```
_v102_ab_capa2.py             las dos selecciones, cruda contra corregida
_v102_ab_idf_futbol_nba.py    IDF en fútbol (3 puntuaciones × 3 ventanas) y NBA
_v102_ab_idf_nba_motor.py     el IDF de NBA contra el vector desplegado
```
