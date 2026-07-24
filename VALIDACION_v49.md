# VALIDACIÓN v49 + v50

**Fecha:** 2026-07-24
**Objetivo:** reparar el barrido universal (que colapsaba a "0 partidos
evaluados"), restaurar la visibilidad del botón de Telegram, y maximizar
"todas las apuestas posibles" sin relajar los filtros de la Capa 1.

---

## Diagnóstico de raíz (v49)

El barrido `apuestas_del_dia()` evaluaba **únicamente los partidos presentes
en `odds_actuales.json`**. Cuando la captura de The Odds API fallaba o se
quedaba corta, el archivo quedaba casi vacío → "partidos evaluados: 0" y solo
1-2 ligas. La cobertura de fútbol dependía al 100 % de que llegaran cuotas.

## Solución v49 — pase de FIXTURES independiente de las cuotas

- **`fixtures_espn.py`** (nuevo): próximos partidos por liga desde el
  scoreboard JSON público de ESPN (sin clave, sin coste). Verificado
  2026-07-24: Liga MX 7, MLS 15, Brasil 10, Argentina 16 fixtures.
- **`alpha_finder._barrido_fixtures()`**: para cada liga disponible, mapea los
  fixtures a los equipos del motor (name_mapper) y predice **todo** partido:
  - con cuota real → Capa 1 (ruta existente, intacta);
  - sin cuota → **Capa 2** (cuota justa) + **pronóstico** informativo.
- `_mercados_modelo()`: 1X2 + O/U 2.5 + BTTS del modelo con cuota justa.
- Nuevos alias Liga MX (León, Atlético de San Luis).

**Resultado (barrido real 2026-07-24):**

| Métrica | Antes (v48) | Después (v49) |
|---------|-------------|----------------|
| Partidos evaluados | 0 | **70** |
| Capa 2 | 1 | **19-21** |
| Pronósticos | 0 | **30** |
| Ligas cubiertas | 1 | **13** (Liga MX, MLS, Brasil, Argentina, China, Dinamarca, Noruega, Suecia, Finlandia, ...) |

## UI (v49) — sin quitar funciones

- **Botón "📤 Enviar a Telegram ahora" SIEMPRE visible** arriba de la sección
  (antes estaba en un expander colapsado → "no se veía"). Usa la misma
  `bot_telegram.construir_mensaje()` que el envío diario.
- **Botón de copiar al portapapeles CONSERVADO** (el usuario pidió NO eliminar
  funciones y el propio brief lo marca como necesario). Export TXT/CSV se
  muestra ahora también con Capa 2 / pronósticos.
- Nueva sección **"📋 Todos los pronósticos del día"** con el board 1X2 + O/U +
  BTTS de cada partido.

---

## v50 — más cobertura de CUOTAS REALES (Capa 1) + board completo

**Hallazgo:** `fetch_odds` sí usa Betexplorer como fallback, pero
`cuotas_clubes_hoy()` solo cubría 8 ligas europeas → las ligas EN TEMPORADA de
verano (Brasil, Argentina, MLS, China, nórdicas) no recibían cuotas reales y
solo salían en Capa 2.

- **`betexplorer_scraper.cuotas_clubes_hoy()`** ahora cubre **todas** las ligas
  disponibles (20). Verificado: captura Argentina, Dinamarca, Finlandia (antes
  0). Efecto: esos partidos pasan de Capa 2 (sin cuota) a **Capa 1 con EV**.
- **Board completo por partido** (`board` en cada pronóstico): 1X2 + O/U + BTTS
  del modelo, mostrado en una tabla ancha para armar cualquier parlay.

---

## No regresión
- `test_simetria.py` → TODO OK
- `test_match_parlay.py` → TODO OK
- Smoke `dashboard_ui.py` (Apuestas del Día, Tenis, Liga MX) → OK
- `bot_telegram.py --dry-run` → mensaje con Capa 1, Capa 2 (21, multi-liga),
  BTTS (8), parlay de tenis → OK

## Reglas de oro respetadas
- Capa 1 conserva sus filtros (prob >70 %, EV >+3 %, cuota >1.50). Los partidos
  sin cuota validada van a Capa 2 / pronósticos (informativos), nunca a Capa 1.
- Modelos existentes intactos. Ninguna función eliminada.
