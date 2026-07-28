# VALIDACIÓN v76 — Auditoría del histórico de cuotas, backfill inmediato y Playdoit

Fecha: 2026-07-28 · Remotos: `origin` (HMREY) + `upstream` (HectorMontiel)

---

## 0. La pregunta que originó esta versión

> *"¿Por qué no podemos tener ese historial de snapshots inmediato? ¿En verdad no
> existe ninguna página en lo más recóndito de internet que tenga esa información?"*

La respuesta de la v75 —"solo cabe acumular fotos diarias"— era **medio falsa**, y
la mitad falsa era importante. Esta versión la corrige con datos.

---

## 1. La distinción que faltaba

La v75 mezcló dos cosas que se comportan de forma muy distinta:

| | ¿Se puede recuperar del pasado? |
|---|---|
| **Movimiento de línea** (cómo cambió la cuota entre que abrió y cerró) | **No, por nadie.** Es un flujo que solo existe si alguien lo fotografió mientras ocurría. Ni Pinnacle publica su propio histórico intradía. |
| **Cuota de cierre** (a cuánto pagaba el partido al empezar) | **Sí.** Está publicada en varios sitios y se puede descargar hoy. |

La v75 aplicó a la segunda la conclusión de la primera. Ahí estaba el error: se
dio por perdido un dato que llevaba años publicado.

---

## 2. Lo que estaba mal en el diagnóstico de la v71

La v71 escribió que BetExplorer era *"HTML puramente JS, cero filas de cuotas en
738 KB"*. **Es falso.** Las páginas de resultados sirven las cuotas en el propio
HTML, en atributos `data-odd`:

```
<td class="table-main__odds" data-oid="a65inxv464x0xrtqdf" data-odd="2.50"></td>
```

Lo que falla es leerlas con expresiones regulares:

- el equipo ganador viene envuelto en `<strong>`, así que el patrón de nombres no
  casa;
- los `</tr>` no siempre cierran, así que las filas se fusionan.

Con regex salían **52 de 240** partidos de Chile 2024. Con un parser de HTML de
verdad (`BeautifulSoup` + `lxml`, ambos ya en `requirements.txt`): **240 de 240**,
con marcador y fecha. El fallo era del extractor, no de la fuente.

---

## 3. Búsqueda exhaustiva de histórico — todo lo probado

| Fuente | Resultado medido | Veredicto |
|---|---|---|
| **BetExplorer** | Cuotas en HTML; sitemap oficial con 20.000 páginas de resultados y **8-20 temporadas por competición** | **ADOPTADA** |
| **The Odds API — histórico** | El archivo de snapshots **existe** (`/v4/historical/...`), pero `401 HISTORICAL_UNAVAILABLE_ON_FREE_USAGE_PLAN`. Además la cuota libre está a **0 de 500** | De pago — decisión tuya (§7) |
| **api-football** | Clave presente en `secrets.toml` pero **cuenta suspendida** (`Your account is suspended`) | Reactivable — decisión tuya |
| **Sofascore** | 403 con y sin cabeceras de navegador en `api.sofascore.com` y `www.sofascore.com` | Descartada |
| **Flashscore** | `robots.txt` permisivo, pero el feed va firmado (`x-fsign`) y la firma rota | No sin evadir su firma |
| **OddsPortal** | Responde 200 pero no publica `robots.txt` (sirve la SPA); ToS desconocido | No la toco sin tu visto bueno |
| **Betfair histórico** | 403 | Descartada |
| **Kaggle / FootyStats / OddAlerts / Footiqo / Apify** | Cubren las ligas grandes que **ya teníamos** vía football-data; ninguna añade Colombia, Perú, Bolivia… | Sin valor incremental |
| **football-data.co.uk** (`/new/` por país) | PER, URY, ECU, VEN, PRY, CRI, SLV, IND, ZAF, GRC, NED → **404: no existen** | Límite real de la fuente |

---

## 4. Resultado: 7.372 cuotas de cierre recuperadas, hoy

Módulo nuevo: `backfill_betexplorer.py`.

**Cómo se hace de forma respetuosa.** `robots.txt` de BetExplorer prohíbe `/ad/`,
`/redirect/`, `/bookmaker/` y **todas** las variantes con query-string (`?stage=`,
`?year=`, `?page=`). El módulo no toca ninguna: usa exclusivamente las páginas
`/results/` que **el propio sitemap anuncia**, con una pausa de un segundo entre
peticiones y caché en disco.

**Descubrimiento por sitemap, no adivinando.** Adivinar slugs daba 11 de 22 ligas
y varios falsos negativos: Paraguay no es `division-profesional` sino
`primera-division`, Sudáfrica es `premier-league`, la Champions está en
`europe/champions-league`. El sitemap las da las 22, exactas.

**El emparejamiento va por fecha + marcador, no por nombre.** Es al revés de lo
intuitivo y la razón es empírica: BetExplorer abrevia ("U. Catolica",
"U. De Chile") y la similitud contra "Universidad Católica" se queda en 0,67,
por debajo del umbral 0,78 de `name_mapper` — Chile perdía 453 de 1.489 partidos.
Bajar el umbral a lo bruto habría abierto la puerta a emparejamientos falsos, que
en un backfill de cuotas son el peor error posible porque contaminan el backtest
sin dejar rastro. Yendo por fecha y marcador exacto, el resultado hace de
verificación y el nombre solo desempata: **912 en vez de 674, con cero
ambigüedades**.

### Cobertura obtenida

| Liga | Partidos | Con cuota | Cobertura |
|---|---|---|---|
| Eerste Divisie | 1.900 | 1.554 | **81,8 %** |
| FA Cup | 675 | 559 | **82,8 %** |
| Chile Primera | 1.280 | 912 | **71,2 %** |
| Sudáfrica Premier | 1.175 | 659 | 56,1 % |
| Bolivia | 1.526 | 853 | 55,9 % |
| Brasil Serie B | 2.020 | 1.035 | 51,2 % |
| Paraguay | 1.284 | 484 | 37,7 % |
| Europa League | 1.356 | 246 | 18,1 % |
| Libertadores / Sudamericana / Champions / Conference / AFC | | 550 | 11-22 % |
| Perú, Uruguay | | 253 | ~8 % |
| **Colombia, México Expansión, Costa Rica, El Salvador, USL, Arg. Nacional, Ecuador** | | **206** | **0,4-3 %** |
| **TOTAL** | **31.713** | **7.372** | **23,3 %** |

### Por qué las últimas siete quedan casi vacías

Son las ligas de **Apertura/Clausura**. BetExplorer sirve por defecto solo la
última fase de cada temporada; el resto está detrás de `?stage=`, que su
`robots.txt` prohíbe. **No lo he saltado** — es tu relación con ese sitio y tu
riesgo, no una decisión que me corresponda tomar. Opciones en §7.

---

## 5. Playdoit: la cuarta casa (y la que más importa)

De nada sirve detectar valor en un precio que no puedes tomar. Playdoit corre
sobre **Altenar**, cuya API de widget es pública y sin clave; la integración
(`playdoit2`) se descubrió inspeccionando las peticiones de su propia web.

| | Partidos con 1X2 | Margen medio |
|---|---|---|
| Pinnacle | 594 | 1,0715 |
| Bovada | 916 | 1,0960 |
| **Playdoit** | **952** | **1,0856** |

Márgenes verificados: **ninguna terna por debajo de 1,00** (lo contrario habría
delatado un fallo de parseo, no un chollo).

**Impacto medido en el barrido en vivo: la Capa 1 pasa de 4 picks a 8, y 5 de
los 8 salen del precio de Playdoit.**

### La quinta casa: probada y no encontrada

| Casa | Resultado medido |
|---|---|
| Kambi (Rushbet MX/CO, Unibet, 888sport) | **429 persistente**, incluso con cabeceras de navegador y espaciado: nos limita por IP |
| Matchbook, Smarkets, Betfair (exchanges) | **403 de Cloudflare** |
| Bodog (.eu/.net/.ca) | DNS/522: el dominio ya no responde |
| Betcris MX | 404 en su propia ruta de deportes |
| 1xBet LineFeed | 404 (la API cambió) |
| BetOnline, Stake | Sin API JSON localizable / 403 |
| Otras integraciones de Altenar (betano, winpot, strendus, codere, betsson, sportium…) | **400**: `playdoit2` es la única válida |
| ESPN core API | Expone **un solo** proveedor (DraftKings), no varios |

No la hay gratis y estable hoy. Prefiero decirlo a integrar algo que se caiga
en producción sin avisar.

---

## 6. Impacto en el modelo

Las cuotas nuevas se re-enlazaron al ledger existente **sin reentrenar**:
**+2.530 predicciones ahora medibles en 14 competiciones** que estaban a ciegas
(36.006 con cuota, frente a 33.476).

Recalibración con esos datos (pliegue de validación que no participó en la
selección, 6.775 partidos):

| | antes | después | Δ |
|---|---|---|---|
| log-loss | 1,0203 | **1,0003** | **−0,0200** |
| precisión | 0,5014 | **0,5150** | **+1,36 pp** |

Capa 1 con los umbrales de producción, ahora sobre 56 ligas:

| Precio | Calibración | picks | ROI | p5 | acierto |
|---|---|---|---|---|---|
| cierre medio | sin corrección | 995 | −3,76 % | −8,48 % | 55,2 % |
| cierre medio | **v76** | 502 | **+4,43 %** | −1,79 % | **60,4 %** |
| line shopping | sin corrección | 1.080 | −1,10 % | −5,63 % | 56,7 % |
| line shopping | **v76** | 590 | **+5,80 %** | **+0,08 %** | **61,0 %** |

Umbrales de Capa 1: se volvieron a buscar con walk-forward anidado sobre 2.400
combinaciones y **siguen sin adoptarse** (la mejor da +0,63 % con 70 apuestas y
p5 −12,3 %). Se mantienen los de `edge_engine`.

---

## 7. Lo que queda, y es decisión tuya

Para las 7 ligas de Apertura/Clausura (Colombia, México Expansión, Costa Rica,
El Salvador, USL, Argentina Primera Nacional, Ecuador) hay tres caminos:

1. **The Odds API, plan de pago** (~30 $/mes el más básico con histórico).
   Es la opción *mejor*, no solo la más cómoda: su archivo guarda **snapshots
   con hora**, o sea el movimiento de línea, que es estrictamente más que la
   cuota de cierre y es lo único que permite entrenar el CLV Predictor sin
   esperar meses. Cubre estas ligas.
2. **Reactivar api-football** (la cuenta está suspendida, la clave ya la tienes).
   Su endpoint `/odds` da histórico por temporada. Coste: revisar el dashboard.
3. **Que me autorices a usar `?stage=`** en BetExplorer. Técnicamente funciona y
   completaría las siete, pero su `robots.txt` lo desaconseja explícitamente y
   no lo hago por mi cuenta.

Mi recomendación es la 1: por 30 $/mes resuelve el hueco **y** desbloquea el CLV,
que hoy necesita meses de acumulación.

---

## 8. Arreglos de raíz de esta versión

| Fallo | Arreglo |
|---|---|
| **El backfill se habría perdido igual que las fotos**: vive en `odds_historico.db`, que está en `.gitignore`, y no es regenerable desde el repo | `odds_store` persiste ahora **todo lo no reproducible** (fotos + backfill) en `odds_snapshots.csv` (1,41 MB). Verificado apartando la base: se recuperan 7.372 cuotas de backfill + 989 fotos + 137.185 cierres derivados |
| **9 ternas con margen < 1,00** (arbitraje imposible) colándose desde el backfill — una cuota de 7,69 donde el partido pagaba 2,50 genera un EV fantasma enorme | Guardia de plausibilidad en `odds_store._limpiar`: toda terna 1X2 con margen fuera de [1,00, 1,50] se descarta. Está en el ALMACÉN, no en cada importador, para que ninguna fuente futura pueda saltársela. 30 filas purgadas |
| Nombres de Altenar con tabulaciones («RC Celta\t\t») generaban clave distinta y no emparejaban nunca | Normalización de espacios en `_indice_playdoit` |

---

## 9. Tests

| Test | Resultado |
|---|---|
| `test_catalogo_y_cuotas.py` (32 comprobaciones, 7 nuevas de la v76) | **TODO OK** |
| `test_simetria.py` · `test_match_parlay.py` · `smoke_botones.py` | **TODO OK** |
| Barrido universal en vivo | 8 en Capa 1 (5 con precio de Playdoit), 19 Capa 2, 66 pronósticos |

Las comprobaciones nuevas cierran las causas raíz de esta versión: que el
backfill tenga volumen, que **ninguna cuota importada implique arbitraje**, que
no haya cierres duplicados por partido y casa, que Playdoit cargue y dé márgenes
plausibles, y que el CSV del repositorio lleve lo no reproducible sin duplicar
lo que sí se puede regenerar.
