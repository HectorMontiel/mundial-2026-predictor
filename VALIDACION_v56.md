# VALIDACIÓN v56 — Plantilla MLB completa + combinador + apuesta automática

**Fecha:** 2026-07-24

## 1. Plantilla MLB completa (formato secciones) ✅

`MLBEngine.plantilla_mlb()` (+ alias `plantilla_club` para reutilizar el motor
de parlay del fútbol). Todos los mercados se derivan de una **matriz de carreras**
(dos Poisson por equipo, medias del modelo de totales + margen). 6 secciones, 52
mercados:

1. **Ganador** (incl. extra innings) — moneyline del clasificador.
2. **Hándicap de carreras (run line)** — ±1.5, ±2.5 para ambos equipos.
3. **Margen de victoria** — gana por 1 / 2 / 3+ cada equipo.
4. **Totales** — 7.5/8.5/9.5/10.5 (Más y Menos) + **totales por equipo** (3.5/4.5/5.5) + par/impar.
5. **Primeros innings** — 1er inning (1X2, más/menos 0.5, cada equipo marca) y
   **F5 (primeras 5 entradas)** (1X2, más/menos 4.5). Asunción declarada: carreras
   i.i.d. por entrada.
6. **Extra innings** — ¿habrá? Sí/No (empate en la regulación).

Verificado coherente (márgenes y totales suman, extra innings 13 %).

## 2. Combinador de mercados MLB (manual + automático) ✅

Al exponer la plantilla en formato `secciones`, el motor de parlay del fútbol
funciona TAL CUAL para MLB (IDs clasificados en `match_parlay._PREFIJOS`, con
categorías «Primeros innings» y «Extra innings» añadidas):

- **🎰 Arma TU combinada** — el usuario elige mercados y ve la probabilidad
  conjunta (ajustada por correlación) y la cuota combinada.
- **Proponedor automático** — la app propone la mejor combinada (perfil súper
  seguro / conservador / medio / agresivo). Verificado: «No extra innings» +
  «SDN +2.5 carreras» → 68 %, cuota 1.40.
- **Apuesta automática (mejor)** — el proponedor con perfil súper seguro ES la
  mejor apuesta que da la app.

Integrado en la vista ⚾ MLB → pestaña «Predecir partido».

## 3. Props de jugador (bateo/pitcheo) — estado honesto

La plantilla del usuario incluye props de jugador (hits, bases, HR, ponches). La
**fuente correcta y legal existe**: la MLB Stats API (`statsapi.mlb.com`, gratis,
sin clave), ya usada en `props_model.py` para ponches de pitcher. PERO surfacear
props en la plantilla de un partido concreto exige, en vivo: (a) el schedule con
los **pitchers probables** del día, (b) mapear los nombres de equipo de la MLB
Stats API a nuestros códigos Retrosheet, y (c) que el pitcher esté en el estado
entrenado de `props_model`. Es un sub-proyecto propio; se deja el gancho
(`_props_pitchers`, gated) y se hará en una versión dedicada para no shipear algo
frágil. Los props de BATEO (hits/HR/bases) exigen además el lineup del día.

## 4. scores24.live y goleadores de fútbol — no viables ahora

- **scores24.live**: protegido por Cloudflare + SPA React (auditado en v54). No
  scrapeable de forma segura/estable. Su valor ya está en football-data/ESPN.
- **Goleadores de club (fútbol)**: la `ClubEngine` no tiene plantillas de
  jugadores; football-data no da datos por jugador. Requeriría FBref/API-Football
  (frágil / rate-limited) → sub-proyecto.

## No regresión
- `test_simetria.py` → TODO OK · `test_match_parlay.py` → TODO OK
- Smoke `dashboard_ui.py` (⚾ MLB con plantilla + combinador) → OK

---

# v57 — Categorías por deporte + GOLEADORES (fuente nueva)

## 1. Categorías del parlay, por deporte ✅
El selector mostraba SIEMPRE las categorías de fútbol (córners, tarjetas,
goles) aunque el partido fuera de MLB. Ahora `categorias_disponibles(pl)`
las deriva de la plantilla REAL del partido, y `categoria_ui` usa el
vocabulario de cada deporte (carreras vs goles):

- **MLB**: Resultado · Run line (hándicap) · Margen de victoria · Par/Impar
  carreras · Carreras por equipo · Primer inning · Primeras 5 entradas ·
  Extra innings · Más/Menos de carreras.
- **Fútbol**: las 21 de siempre + Goleadores.

## 2. GOLEADORES — fuente encontrada e integrada ✅
Tras auditar varias opciones:
- Understat → solo top-5 ligas y la temporada nueva viene vacía. ❌
- scores24.live → Cloudflare + SPA React. ❌
- FBref / API-Football → rate-limit agresivo o de pago. ❌
- **ESPN roster** (`/teams/{id}/roster`) → ✅ **gratis, sin clave, cubre TODAS
  nuestras ligas** y devuelve por jugador `totalGoals`, `goalAssists`,
  `appearances`, `totalShots`. Es el mismo JSON que ya usamos para fixtures.

`goleadores.py`:
- Descarga equipos y rosters por liga (caché 3 días en `goleadores_cache.json`).
- Si la temporada en curso tiene muestra pobre (arranque de torneo), cae a la
  **temporada anterior** automáticamente.
- Modelo: λ_jugador = xG del equipo en ESTE partido × cuota goleadora del
  jugador, con **shrinkage bayesiano** (PRIOR_CUOTA 0.06, K=12) para que con
  pocos goles de muestra un jugador no acapare el 100 %.
- Mercados: «X marca en cualquier momento» y «X marca 2 o más».
- Verificado (Atlante vs América): 7-18 % por jugador, en línea con las casas.
  Sin shrinkage daba 75 % (irreal) — el ajuste es lo que lo hace usable.

Integrado como sección «14. Goleadores» en la plantilla de TODAS las ligas de
fútbol, y clasificado en el parlay: cada jugador es su propio grupo (dos
goleadores distintos SÍ se pueden combinar; «marca» y «marca 2+» del mismo
jugador no, por redundantes).

## No regresión
- `test_simetria.py` → TODO OK · `test_match_parlay.py` → TODO OK
- Smoke `dashboard_ui.py` (⚾ MLB, 🇲🇽 Liga MX) → OK
