# VALIDACIÓN v41 — Salud de datos, parlays inteligentes y cierre de brechas

**Fecha:** 2026-07-24 · Prioridad #1 del usuario: **que NO vuelva a pasar que
no llegan datos y no nos demos cuenta.** Además, implementa la spec v41
(transición a Partidos Internacionales, mejores patas, cierre de brechas),
con la estrategia de siempre: validar con datos, buscar alternativas.

---

## 0. LA INCIDENCIA QUE ORIGINA v41 (y su arreglo)

El run del bot del 2026-07-24 05:32 produjo un mensaje **vacío** ("Hoy no hay
Pick del Día") sin avisar de que la causa era que **no llegaban datos**:
`ODDS_API_KEY no configurada` + Betexplorer `429`.

**Diagnóstico (verificado):**
1. Los 4 Secrets del repo de despliegue existen (`ODDS_API_KEY`, etc.), puestos
   a las 00:27. El run fallido corrió **antes** de que existieran.
2. **Se disparó un run nuevo** (`workflow_dispatch`) y funcionó de extremo a
   extremo: The Odds API capturó **MLS 47 · Liga MX 62 · Brasil 78 ·
   Argentina 85 · Premier 36** cuotas → `capa1=1 capa2=2` → **"Mensaje enviado
   a Telegram"**. Los datos SÍ llegan.
3. El Betexplorer 429 venía de que, sin la clave, TODO caía a Betexplorer y lo
   martilleaba. Con la clave, no se sobrecarga.

**El arreglo de fondo — que el sistema lo NOTE (`data_health.py`):**
distingue "no llegaron datos" (PROBLEMA) de "llegaron pero hoy no hay picks"
(NORMAL, disciplina). Niveles ok / degradado / **crítico**:
- Crítico si falta la clave, o 0 cuotas + última captura > 18 h (fuente caída).
- `bot_telegram` antepone una **🚨 ALERTA DE DATOS** al resumen cuando es
  crítico; el dashboard muestra un **banner rojo**. Nunca más un vacío mudo.

**Resiliencia Betexplorer (`_get` con backoff):** reintento ×3 con espera
creciente (2/4/6 s) y **rotación de User-Agent** ante 429/5xx, antes de
degradar a la siguiente fuente de la cadena.

---

## 1. Transición «Mundial 2026» → «Partidos Internacionales» (§1)

- Renombrada la competición a **🌍 Partidos Internacionales** (selector, título
  y `page_title`). El motor (`PredictionEngine`) es el mismo — el histórico de
  Kaggle ya incluye amistosos y clasificatorias, así que el modelo (60.49 %)
  sigue operando sin cambios de arquitectura.
- Las features de torneo (estadio/árbitro/fase) permanecen en el código para
  reactivarse cuando haya un torneo con sedes/árbitros/fases; no se eliminan.

---

## 2. Parlays inteligentes (§3)

### 2.1 Sección «🧩 Mejores Patas para Parlay» + constructor integrado

- `alpha_finder._mejores_patas`: recoge los picks de **alta probabilidad
  (≥ 55 %) y EV > +2 %** de todo el pool, con **BTTS prioritario** (prob > 60 %,
  EV > +1 %, marcado ⚽). Son ladrillos para combinar, no apuestas simples.
- `match_parlay.combinar_patas`: el usuario elige 2–6 patas y obtiene el **PFP
  real** (aplicando el factor de correlación empírico a los pares del mismo
  partido), cuota combinada, EV, riesgo por PFP (🟢≥45 % / 🟡≥30 % / 🔴<30 %),
  avisos de exclusividad y **stake por ¼ Kelly**. UI integrada en Apuestas del Día.

### 2.2 Umbral de Capa 1: **se mantiene 0.55** (el 0.52 del spec, PROBADO y
rechazado)

El spec §3.3 proponía bajar el piso de prob a 0.52 "para más cobertura". Se
validó con bootstrap:

| Piso | n | ROI | ROI p5 (bootstrap) |
|---|---|---|---|
| 0.52 | 354 | +7.6 % | +0.6 % |
| **0.55** | **297** | **+9.9 %** | **+2.8 %** |

0.52 **reduce el ROI y la robustez** → se mantiene 0.55 (validado en v40). La
cobertura extra que buscaba el spec la aporta la sección «Mejores Patas»
(umbral 0.55/EV>2 %, más amplio que Capa 1) sin tocar la calidad de Capa 1.

---

## 3. Cierre de brechas (§2)

### 3.1 Props de jugadores — **feed PARCIALMENTE disponible** (`props_scraper.py`)

Corrige la conclusión de v37 ("props no disponibles"):
- **MLB `pitcher_strikeouts`: 5 casas** lo ofrecen ahora en The Odds API
  (regiones us,eu). En v37 daba 0 → dependía de región/hora, no de la capa.
- Fútbol: existen mercados (player_shots_on_target…); algunos nombres inválidos
  (player_cards → 422). Cobertura variable por evento.
- `props_scraper.auditar()` descubre qué props hay disponibles hoy. El
  **modelo** de props queda diferido (exige histórico por jugador: pybaseball /
  FotMob / StatsBomb) — es un lift mayor, candidato a v42.

### 3.2 Telegram — **verificado y funcionando** (§2.3)

Run manual disparado: mensaje **enviado** al chat. Cron diario 10:00 UTC
operativo. (Antes fallaba solo por los Secrets aún no creados.)

### 3.3 NBA (§2.4) / CLV (§2.1)

- NBA: auto-activable en octubre (SPORT_KEYS + TEMPORADA). Sin cambios.
- CLV: la mejora estructural (capturar más cerca del cierre) requiere más
  snapshots; `clv_tracker` sigue midiendo. Es infraestructura, no un parche.

---

## 4. No regresión

- `test_simetria.py`, `test_match_parlay.py` → **TODO OK** (Internacionales 60.49 %).
- `smoke_v41.py` (AppTest, 11 vistas incl. «Partidos Internacionales» y banner
  de salud) → **0 excepciones**.
- Sin dependencias nuevas. El cambio de selección/ROI es el validado en v40.

---

## 5. Entregables

`data_health.py` (monitor + alarma) · `betexplorer_scraper.py` (`_get` con
backoff/rotación) · `bot_telegram.py` (alarma antepuesta) · `dashboard_ui.py`
(banner de salud, «Partidos Internacionales», Mejores Patas + constructor) ·
`alpha_finder.py` (`_mejores_patas`) · `match_parlay.py` (`combinar_patas`) ·
`props_scraper.py` (descubrimiento de props) · `VALIDACION_v41.md`.

**Resultado:** la incidencia de datos está diagnosticada, **arreglada y ahora
VIGILADA** (nunca más un mensaje vacío sin avisar del porqué); el bot envía; la
plataforma gana un constructor de parlays con PFP en tiempo real; y se
confirma que los props de MLB ya tienen feed gratuito para una futura v42.
