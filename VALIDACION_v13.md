# ✅ Reporte de Validación — v13

**Fecha:** 2026-07-12 · **Regla rectora:** ninguna modificación que degrade el
1X2 del Mundial o las métricas de backtesting se fusiona. Lo no validable se
documenta y se descarta.

## M1 — Actualización en vivo del Mundial

- `--live` fuerza la re-descarga de la fuente base ignorando cachés, y
  [live_worldcup.py](live_worldcup.py) añade la cadena API-Football →
  FBref → base, con dedupe por MATCH_ID, relleno determinista y recálculo
  inmediato de ELO/MA5. Cron cada 2 h documentado.
- Banner "🟢 Datos actualizados al {fecha} — incluyen partidos de {fase}"
  con las 6 fases oficiales del calendario FIFA 2026 mapeadas por fecha.
- **Estado de fuentes verificado**: API-Football requiere RAPIDAPI_KEY (no
  configurada); FBref responde 403 desde esta red; la fuente base (Kaggle)
  SÍ se actualiza a diario y es la vía operativa. Cadena degrada limpio (0
  errores, prueba automatizada).

## M2 — Distribuciones para todos los mercados

- Módulo [distributions.py](distributions.py) con las líneas de la
  especificación: goles totales/por equipo, córners totales (6.5-10.5) y por
  equipo (3.5-5.5), tarjetas totales (2.5-5.5) y por equipo (1.5-2.5),
  remates (18.5-24.5) y a puerta (4.5-7.5) — 38 líneas por partido.
- Goles desde la matriz Monte Carlo; resto con colas Poisson exactas.
  Monotonía verificada; sección 9b en la plantilla; `GET /distribuciones`.
- **Caché por partido**: primera llamada ~5.8 s (incluye la predicción
  completa), llamadas siguientes **<1 ms** (cumple el requisito de <500 ms).

## M3 — Parlay con cuotas reales y filtro de riesgo

- Lee `odds_actuales.json` (snapshot de The Odds API vía fetch_odds) además
  del histórico; con cuotas reales aplica filtro `ev_min` y ordena por EV.
- **Filtro de riesgo activo**: las selecciones de partidos con flag 🔴 en
  `risk_flags.json` se excluyen (verificado: parlay sin MEX-ECU cuando el
  mercado lo marca alto), y el parlay reporta su riesgo general y los
  partidos excluidos. Botón de copiar/exportar en la UI.
- **Backtest de EV con CUOTAS DE CIERRE REALES (B365)** — estrategia
  unitaria (ingrediente del parlay), apostando cuando prob×cuota−1 ≥ umbral:

  | Liga | Apuestas | ROI realizado (EV≥0 / ≥0.05 / ≥0.10) |
  |---|---|---|
  | Premier | 209/191/169 | **+10.9 % / +8.1 % / +6.1 %** ✅ |
  | LaLiga | 354/311/266 | **−20.3 % / −20.4 % / −26.6 %** ❌ |

  Lectura honesta: el EV positivo solo existe donde el modelo supera al
  mercado (Premier). En LaLiga el mercado es mejor que el modelo y apostar
  contra él pierde dinero — el parlay se etiqueta como no accionable con
  cuotas justas y la UI lo advierte.

## M4 — Inteligencia de mercado como capa de riesgo

- Riesgo compuesto según especificación: 🔴 divergencia >20 pp **y**
  liquidez >30 %; 🟡 divergencia >15 pp **o** liquidez >20 %; 🟢 resto.
  Verificado con escenario sintético (divergencia 27 pp + liquidez +50 % →
  alto) y escrito a `risk_flags.json` por cruce de equipos.
- Snapshots cada 10 min (cron documentado). Polymarket Gamma API operativa
  (snapshot real capturado). **Limitación documentada**: el rastreo de
  wallets on-chain (Polygonscan) requiere clave e indexador propio; el flujo
  se aproxima con volumen/liquidez de la propia API.

## M5 — Ligas de clubes

**Experimento adoptado — histórico ampliado** (regla: adopción si ≥ +0.5 pp):

| Liga | v12 (3 temp.) | v13 candidato | Δ | Decisión |
|---|---|---|---|---|
| Liga MX (8 años, 2,651 partidos) | 47.6 % | **51.4 %** | **+3.8 pp** | ✅ adoptado |
| LaLiga (5 temp., 1,900 partidos) | 47.9 % | **49.9 %** | **+2.0 pp** | ✅ adoptado |
| Premier (5 temp.) | 49.5 % | 48.9 % | −0.6 pp | ❌ **revertido a v12** |

**No adoptado / no viable (documentado):**
- **Ratings de jugadores (WhoScored/SofaScore)**: ambas fuentes bloquean el
  acceso automatizado desde esta red (verificado 2026-07-12). Sin datos no
  hay validación posible → feature descartada. Módulo
  [player_ratings.py](player_ratings.py) listo para cuando exista acceso.
- **FBref para Liga MX (xG) y Champions**: 403 Cloudflare verificado.
  [fbref_league_scraper.py](fbref_league_scraper.py) genérico queda listo
  (parametrizado por liga/temporada, con proxies). **Champions permanece en
  beta** — no se inventan datos.

## M6 — No regresión del Mundial

- `train_tda_model.py --corte 2024-01-01 --walkforward`:
  **59.5 % / log-loss 0.908 — idéntico al benchmark v12** (Δ 0.0 pp,
  margen exigido ±0.2 pp). Ventanas: 59.2/57.1/59.7/64.0/57.3 %.
- EGY vs AUS = 0.388/0.253/0.359 **bit a bit intacto**.
- UI verificada por AppTest: Mundial completo, Liga MX (72 campos),
  Champions beta.

## Decisión final

| Cambio | Producción |
|---|---|
| `--live` + cadena en vivo + banner de fase | ✅ |
| distributions.py + caché + 38 líneas + endpoint | ✅ |
| Parlay con odds_actuales + ev_min + filtro de riesgo + export | ✅ |
| Riesgo compuesto + risk_flags.json + exclusión automática | ✅ |
| Liga MX 8 años (+3.8 pp) y LaLiga 5 temporadas (+2.0 pp) | ✅ |
| Premier 5 temporadas | ❌ revertido (−0.6 pp) |
| Ratings de jugadores | ❌ descartado (fuentes bloqueadas, sin validación) |
| Champions con FBref | ❌ beta (403; sin fuente gratuita accesible) |
| Wallets on-chain | ❌ aproximado por volumen/liquidez (limitación documentada) |
