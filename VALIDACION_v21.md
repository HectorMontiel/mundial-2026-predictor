# VALIDACIÓN v21 — Integración API-Football (plan Free) (2026-07-14)

Regla de oro de siempre; fuentes gratuitas/legales/reproducibles; Mundial
intacto (60.49 % / 0.8688, con la simetría v20).

## Sondeo del plan Free (base de todas las decisiones)

Verificado empíricamente con la clave del usuario (`sondeo_api_football_v21.py`,
14 requests):

| Capacidad | ¿Disponible? | Evidencia |
|---|---|---|
| Fixtures temporadas 2022-2024 | ✅ | CL 2023: 214 partidos · Liga MX 2024: 340 |
| Estadísticas por partido (remates, posesión, córners, tarjetas) | ✅ | statistics de la final CL 2023-24 completa |
| Alineaciones de partidos históricos | ✅ | lineups con formación y XI |
| H2H (sin parámetro `last`) | ✅ | se ordena y recorta en cliente |
| **Temporadas 2025/2026 (actuales)** | ❌ | «Free plans do not have access to this season, try from 2022 to 2024» |
| Cuotas (odds) | ❌ | results=0 incluso en fixtures permitidos |
| Lesiones (`/sidelined` por equipo) | ❌ | el endpoint solo acepta `player` |

**Consecuencia honesta:** las mejoras 1 (alineaciones EN VIVO), 3 (cuotas
BTTS) y 5 (lesiones de última hora) del master prompt **no son posibles con
el plan Free** — todas requieren la temporada en curso. ESPN sigue siendo la
fuente de alineaciones en vivo (v19/v20) y BTTS sigue sin cuota real. Se
documenta y se reevalúa si el usuario sube de plan.

## M0 — Gateway `api_football_manager.py` ✅

- Contador diario persistente (`api_football_state.json`), reinicio 00:00
  UTC, sincronizado con las cabeceras `x-ratelimit` del servidor.
- Caché en `api_football_cache/` con TTL por endpoint (stats/fixtures
  históricos permanentes, H2H 24 h, alineaciones 1 h); un hit de caché no
  consume request. Verificado: reconstruir la Champions dos veces costó 0
  requests extra.
- Prioridades con reserva de presupuesto (jerarquía §2 de la spec): una
  petición de prioridad baja se rechaza si invadiría la reserva de las
  críticas.
- **La clave NO se commitea** (la app es pública): se lee de
  `API_FOOTBALL_KEY` (env) → `st.secrets` → `.streamlit/secrets.toml`
  (gitignorado). Para Streamlit Cloud: Settings → Secrets →
  `API_FOOTBALL_KEY = "..."`.

## M2 — Champions League OPERATIVA ✅ (antes beta desde v12)

- `descargar_liga` acepta el formato `api_football`: 3 requests (uno por
  temporada 2022/2023/2024, cacheados) → `historico_champions.csv` con 707
  partidos reales (2022-06 → 2025-05-31), incluida la fase de clasificación.
- Nombres canonicalizados por **ID de equipo de la API** (la API renombró
  clubes entre temporadas, p. ej. 'Bayern Munich' → 'Bayern München', lo que
  partía su historial).
- Mismo pipeline validado (ensemble calibrado + entropías + relleno
  determinista condicionado a goles reales; sin cuotas: la API no las da).

| Métrica | Valor | Umbral spec §4.3 |
|---|---|---|
| Split 80/20 | **56.8 % / 0.955** (ELO 54.5 %) | — |
| Walk-forward temporada 2024-25 (n=213) | **53.5 % / 1.007** (ELO 51.6 %) | > 50 % ✅ |

La ventana 2023 no tiene train suficiente (una sola temporada previa tras el
filtro de historial); se reporta la única ventana válida. **Activada** en la
UI con aviso claro: la forma de los equipos está congelada a 2024-25 (límite
del plan Free) — referencia estructural, no estado actual.

## M4 — Backfill progresivo de estadísticas avanzadas ✅ (infraestructura)

`backfill_stats.py`: cada corrida del pipeline gasta hasta 40 requests
sobrantes (prioridad 2) en `/fixtures/statistics` de partidos 2022-2024 aún
no procesados (orden: Liga MX → Primeira → Champions), acumulando en
`historico_estadisticas_avanzadas.csv` (posesión, remates, córners,
tarjetas, faltas; xG cuando la API lo publica — en Liga MX 2024 no lo hay).
El estado ES el CSV (reanudable, sin duplicados). Verificado con lote de 5.

Cobertura necesaria antes de reentrenar Liga MX con estas features: ~1000
partidos ≈ 25 días de pipeline. El experimento walk-forward queda para v22
cuando haya cobertura — adoptarlo hoy sería imposible (regla de oro).

## M6 — H2H bajo demanda ✅

- Clubes: expander «📜 Historial reciente» — resuelve IDs (Champions: del
  propio CSV; resto: fuzzy 0.75 contra los fixtures cacheados de la liga),
  consulta `headtohead` con caché 24 h y **solo al pulsar el botón** (nunca
  en el render). Muestra requests restantes del día.
- Mundial: el H2H sale del histórico local de Kaggle (gratis y más completo
  que la API) — cero requests.

## No implementado (bloqueado por el plan, documentado)

- **M1 alineaciones en vivo / M3 BTTS / M5 lesiones**: requieren la
  temporada en curso (bloqueada) u odds (no disponibles). El colector ESPN
  (v19/v20) sigue siendo la vía de alineaciones y su evaluación sigue el
  calendario de v20 (diciembre 2026).

## No-regresión

- Mundial y las 8 ligas football-data: sin cambios de modelo ni datos.
- Tests en verde: `test_match_parlay.py`, `test_simetria.py`, AppTest del
  dashboard en vista Mundial y vista Champions (0 excepciones).
- Presupuesto API consumido en toda la v21: 21 requests de 100.
