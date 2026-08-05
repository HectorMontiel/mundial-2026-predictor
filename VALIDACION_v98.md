# VALIDACIÓN v98 — El crash de producción, el edge medido y la deuda ética cerrada

**Fecha:** 2026-08-05
**Punto de partida:** v97 desplegada… y **la app caída**.

---

## 0. Lo primero: producción estaba en blanco (hotfix, ya desplegado)

```
KeyError: 'leagues_cup'
  dashboard_ui.py:1339 in render_liga_club → LEAGUES[clave].get('disponible')
```

Y `leagues_cup` **SÍ estaba** en el `config.py` publicado — comprobado en los
dos remotos (`git show upstream/main:config.py`, línea 480) y funcionando en
local. Es el patrón que la v79 documentó en `calibracion_segura`: **Streamlit
Cloud conserva módulos viejos en `sys.modules` entre despliegues**, así que
durante la recarga convive un `dashboard_ui` NUEVO —que ya ofrece la liga en el
selector— con un `config` VIEJO que todavía no la tiene.

El menú está escrito a mano y el catálogo se lee aparte: pueden
desincronizarse, y cuando lo hacen no dan un aviso, **dan un KeyError que deja
la aplicación en blanco**. Dos redes:

1. El menú se coteja contra `config.LEAGUES` al construirse y **las entradas
   huérfanas se caen del selector**, no la app. Reproducido con un `config`
   simulado sin `leagues_cup`: retira la entrada y el resto del menú sigue.
2. `render_liga_club` usa `LEAGUES.get()` y degrada a «recarga la página».
   Igual `render_kbo` con el `ImportError` del motor nuevo.

El bloque de saneamiento **no puede lanzar** (sería el mismo fallo que evita):
importa `logging` dentro del `try` y su `except` no hace nada.

> Desplegado aparte y antes que todo lo demás: `origin 032561b` ·
> `upstream 926ec19`.

---

## 1. Los dos bugs de interfaz

### 1.1 «Sin partidos programados en las próximas 48 h» en MLB

**La causa del prompt era otra.** Se apuntaba a la ventana de fechas UTC; el
log de producción dice lo que pasa de verdad:

```
[fixtures/mlb] ESPN falló: HTTPError: 403 Client Error: Forbidden for url:
https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/scoreboard?dates=20260805-20260812
```

ESPN devuelve **403 desde Streamlit Cloud** a la misma petición que en local da
200. No es el rango ni la cabecera: es la IP de centro de datos. *(De paso,
medido 3/3: ESPN también responde 403 a la cadena de Chrome completa y 200 sin
User-Agent, con `Mozilla/5.0` y con `python-requests`. El proyecto ya mandaba
la corta, así que no era eso.)*

**Arreglo: la MLB deja de depender de ESPN.** Su calendario lo publica la
propia MLB —gratis, sin clave, con hora de inicio y abridor probable— y este
proyecto ya usa esa API para entrenar. Nuevo `mlb_statsapi.proximos()`, que
`fixtures_espn.fixtures_deporte` antepone dejando ESPN de respaldo.

Medido: **111 próximos partidos en 7 días, 24 con cuota**, con instante de
inicio real (`2026-08-05 18:10:00`) — que es lo que permite decir «próximas
48 h» de verdad y no «hoy en UTC».

### 1.2 «partidos evaluados: 7» ignorando MLB y tenis

`partidos_evaluados` y `cobertura_ligas` salían de `apuestas_del_dia`, que es
el pase de **fútbol**, y se pasaban tal cual al resultado universal. La
cabecera contradecía a la lista que tenía justo debajo.

Cada rama informa ahora de lo suyo (`evaluados` + `cobertura`) y el barrido las
suma. Comprobado: `evaluados: 14 · {argentina:1, leagues_cup:2,
arg_primera_nacional:2, col_primera_a:1, uru_primera:1, bol_division:2,
KBO:5}` — antes decía 9 y sin KBO.

---

## 2. KBO — el edge, ahora MEDIDO (y no está)

### 2.1 Se encontraron cuotas de cierre históricas

| Fuente | Resultado |
|---|---|
| sportsbookreviewsonline | **0** ficheros de KBO/Corea |
| OddsPortal | las 3 rutas devuelven la MISMA página de 93.657 B (incluido `/robots.txt`): SPA sin JS |
| Flashscore · Scoreboard · Covers | 404 en las rutas de KBO |
| statiz.sporki.com | no resuelve |
| **BetExplorer** | ✅ **KBO por temporadas, 2012-2025** |

BetExplorer sirve `/baseball/south-korea/kbo-2024/results/` — ruta plana, que
su `robots.txt` permite (sólo prohíbe cadenas de consulta) — con ganador en
`<strong>`, marcador, fecha y **las dos cuotas de cierre** en `data-odd`.

**Límite honesto:** esa página sólo da los **playoffs**. La temporada regular
está detrás de `?stage=`, justo lo que el `robots.txt` prohíbe. Mismo tipo de
límite que la v92 documentó con las cuotas sudamericanas: superficie
permitida, no bug. Resultado: **201 partidos con cierre real** (14 temporadas),
no ~10.000.

Cotejo contra el histórico de Naver, que es lo que impide un desastre
silencioso: **196 cruzan en el mismo orden y 195 con marcador idéntico; sólo 5
al revés**. Las cuotas están del lado correcto.

### 2.2 El backtest: el modelo NO bate al mercado

113 partidos con predicción **fuera de muestra** (walk-forward) y cierre real.
El ganador coincide **113/113 (100 %)** entre las dos fuentes.

| estrategia | n | ROI | p5 | p95 |
|---|---:|---:|---:|---:|
| modelo, lado favorito | 113 | **−9,10 %** | −23,17 % | +4,59 % |
| modelo, EV > 0 | 84 | **−11,67 %** | −31,60 % | +8,61 % |
| modelo, EV > +2 % | 77 | **−13,52 %** | −34,22 % | +8,01 % |
| modelo, EV > +5 % | 69 | **−12,46 %** | −34,65 % | +10,42 % |

| | modelo | mercado |
|---|---|---|
| Brier | 0,2492 | **0,2411** |
| precisión | 51,33 % | **57,52 %** |

**Veredicto: la KBO no entra en Capa 1 por la vía del modelo.** Y esto ya no es
«no hay datos para saberlo», que es donde lo dejó la v97: se midió contra cuota
de cierre real y el modelo pierde dinero en las cuatro variantes, con p5 muy
negativo en todas. Batir al ELO (lo que sí hace, +1,02 pp) no es batir al
mercado.

*Se conserva el aviso de sesgo: 113 playoffs no son la temporada regular. Pero
el sesgo tendría que ser enorme y en la dirección justa para convertir un
−13 % en positivo.*

### 2.3 Plan B: line shopping, y una corrección a la v97

Se activa la vía **que no usa el modelo**: probabilidad justa de Pinnacle
(quitado el margen) y buscar quién paga por encima. Mismos umbrales que la MLB
(`prob_justa ≥ 0,30`, `EV ≥ +2 %`), sin reajustar nada.

**Y aquí hay que corregir a la v97.** Aquel documento presentó como material de
line shopping esto:

> «Doosan Bears 2,29 en Pinnacle y 2,40 en Playdoit = **4,8 %**»

**Es falso, y la máquina lo dice.** Ese 4,8 % es la diferencia BRUTA entre dos
precios, no el edge. Quitado el margen de Pinnacle (overround medio medido:
1,0615), la probabilidad justa del local es 0,4100 y **la cuota justa es
2,439** — o sea que Playdoit a 2,40 paga **menos** que el precio justo:

```
EV = 0,4100 × 2,40 − 1 = −1,6 %
```

Un spread entre casas no es un edge; el edge es pagar por encima de la
probabilidad justa. Lo dicho en la v97 estaba mal y queda rectificado.

Ejecutado hoy: **5 partidos de KBO comparados contra Pinnacle → 0 por encima
del precio justo**. Con dos casas (Pinnacle y Playdoit; Bovada no cotiza KBO)
las oportunidades son raras. La infraestructura queda puesta y los picks que
salgan van marcados `edge_extrapolado`: el mecanismo está validado en fútbol,
MLB y WTA, **en KBO todavía no tiene ROI propio**.

---

## 3. Leagues Cup — modelo de dos etapas

### 3.1 El sesgo existe, es grande y tiene explicación

Ajustado con 2023+2024 (154 partidos, 90 cruces entre ligas):

| | P(local) predicha | observada | sesgo |
|---|---|---|---|
| todos | 0,5205 | 0,4091 | **−11,1 pp** |
| local de MLS | 0,5125 | 0,3846 | −12,8 pp |
| **local de Liga MX** | 0,5304 | **0,2745** | **−25,6 pp** |

Y tiene una explicación física, no estadística: **la Leagues Cup se juega casi
entera en Estados Unidos**, así que un equipo de la Liga MX marcado como
«local» no está en casa. El modelo, entrenado con ligas domésticas, le aplica
una ventaja de campo que ahí no existe.

Desplazamiento estimado en log-odds: local MLS **−0,530**, local Liga MX
**−1,120**.

### 3.2 Pero no bate al ELO fuera de muestra

Juicio en la edición **2025** (62 partidos, no mirada para ajustar):

| | precisión | log-loss |
|---|---|---|
| etapa 1 (sin corregir) | **0,4839** | 1,0447 |
| **dos etapas (corregido)** | 0,4516 | **1,0253** |
| ELO (línea base) | 0,4516 | — |

- ventaja dos-etapas − ELO: **+0,0000** · p5 −0,1129 · P(>0)=45,1 %
- la corrección **mejora el log-loss** (1,0447 → 1,0253) y **empeora la
  precisión** (0,4839 → 0,4516)

**NO se adopta.** Mejorar la calibración y empeorar el argmax, empatando con la
línea base y con un intervalo de ±11 pp sobre 62 partidos, no es evidencia
suficiente para cambiar lo desplegado. Es la misma disciplina que tumbó el
offset en espacio de ELO en la v97 y las seis palancas del 1X2 en la v90.

**Lo que sí importa del hallazgo, y ya está cubierto:** el caso vivo —enseñar
«Toluca 53 %» cuando gana el 27 %— no llega al usuario, porque desde la v87 la
ficha se ancla al mercado cuando hay precio, y la Leagues Cup tiene **cuatro
casas**. El sesgo queda documentado por si en un par de ediciones hay muestra
para corregirlo con fundamento.

### 3.3 Line shopping

La Leagues Cup es una liga de fútbol más, así que ya pasa por
`valor_vs_sharp` con el resto del fútbol. Hoy: **0 picks** — ninguna de las
cuatro casas paga por encima del precio justo de Pinnacle.

---

## 4. `tenis_saque.py` — deuda ética cerrada

`tenis_saque.py:88` pedía `tennisabstract.com/jsplayers/curr_rank_{circuito}.js`
y ese `robots.txt` dice `Disallow: /jsplayers/`. Venía de la v69 y lo encontró
el test que la v97 escribió para otra cosa.

**Migrado**: el ranking sale ahora del **histórico unificado del propio
proyecto** (`Rank_1`/`Rank_2`, columnas que la v96 incorporó), quedándose con
el más reciente de cada jugador. Las páginas de jugador
(`/cgi-bin/player-classic.cgi`) **no** están en el Disallow y se siguen usando:
se retira sólo la ruta prohibida.

El puente de nombres —el histórico guarda «Alcaraz C.» y las URL piden
«CarlosAlcaraz»— sale del archivo de la v96, que trae el nombre completo. Sin
eso el universo habría caído a los 357 jugadores ya cacheados.

| | ATP | WTA |
|---|---|---|
| jugadores con ranking | 927 | 844 |
| Spearman vs el ranking anterior | 0,7721 | 0,7998 |
| solape del **top-100** | **84 %** | **79 %** |
| solape del top-250 | 56 % | 59 % |

**Se dice lo que no se cumplió:** el objetivo era una correlación >0,95 y sale
0,77-0,80. La razón es estructural — el histórico da «el ranking cuando jugó su
último partido», no «el ranking de hoy», así que un jugador parado meses
arrastra un puesto viejo. Lo que esta función decide es **a qué jugadores
descargar estadística de saque**, y ahí el top-10 es casi idéntico y el top-100
coincide en un 84 %. Se adopta con esa limitación escrita, porque la
alternativa era seguir incumpliendo `robots.txt`.

El test de robots incluye ya `tenis_saque.py` y pasa.

---

## 5. Resumen de decisiones

| | decisión | por qué |
|---|---|---|
| Crash de `leagues_cup` | **arreglado y desplegado aparte** | la app estaba en blanco |
| Fixtures de MLB | **migrados a MLB StatsAPI** | ESPN da 403 desde Cloud |
| Contador multideporte | **arreglado** | la cabecera contradecía a la lista |
| Modelo de KBO a Capa 1 | **RECHAZADO** | ROI −9 % a −13,5 %, p5 hasta −34,7 % sobre cierre real |
| Line shopping de KBO | **activado, marcado extrapolado** | mecanismo validado en otras ligas, sin ROI propio aún |
| Offset de la v97 («4,8 %») | **RECTIFICADO** | el EV real de ese ejemplo es −1,6 % |
| Dos etapas en Leagues Cup | **RECHAZADO** | empata al ELO y empeora la precisión (n=62, ±11 pp) |
| Ranking de `tenis_saque` | **migrado** | cierra la infracción de `robots.txt` |

**Ninguna de las dos competiciones nuevas bate al mercado.** Se midió, con
cuotas de cierre reales en la KBO, y no está. Siguen en Capa 2.
