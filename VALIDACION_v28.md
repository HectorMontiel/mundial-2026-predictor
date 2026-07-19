# VALIDACIÓN v28 — Dos carriles y traductor cognitivo

**Fecha:** 2026-07-19 · Regla de oro respetada; Mundial intacto.

## Carril A

### §1 Auto-cuotas nativas ✅
`cargar_cuotas_actualizadas()` con `@st.cache_data(ttl=21600)` en el
dashboard: importa fetch_odds como módulo (sin subprocesos), spinner nativo,
y salta la actualización si quedan <50 créditos (aviso «Cuotas sin
actualizar por límite de API»). El contador real viene del header
`x-requests-remaining` y se persiste en odds_api_state.json.

### §2.1 Acelerador RLM ✅ (con presupuesto corregido)
La aritmética del spec (450/mes solo para tier-1) ignoraba que
odds_actuales también consume. Presupuesto REAL implementado en
`odds_api.capturar_auto()`: tier-1 (Premier/LaLiga/Serie A/Bundesliga/MLS,
h2h+totals) hasta 3 snapshots/día espaciados ≥3 h — el TTL de 6 h de la app
produce 2-4 naturales —; resto de ligas 1×/día (solo si restantes >150);
BTTS por evento en el paso de pipeline. ≈16 req/día ≈ 480/mes ✓. Estado con
merges atómicos (bug de relectura destructiva detectado y corregido en las
pruebas de idempotencia). Los snapshots alimentan `odds_historico.db`; el
RLM y el Shadow de Bundesliga/Eredivisie (§2.4) quedan CALENDARIZADOS a
+60 días de acumulación (imposibles hoy — documentado).

### §2.2 VACA ✅ (escala adaptada)
Con la fórmula literal (entropías en bits, EV fraccional) ν jamás superaría
1.0 — se normaliza la entropía a [0,1] (÷log₂3) y el EV a %:
ν = EV% / (entH + entA + 0.1). Umbral 1.0 discrimina como pretende el spec
(EV 5 % con entropías medias → ν≈2.9 pasa; EV 1.5 % con equipos caóticos →
0.7 filtrado). Integrado en cross_arbitrage con orden por ν, contador de
descartadas y caché (`arbitraje_cache.json`) para el Platino.

### §2.3 Weibull Over 2.5 ❌ DESCARTADO con evidencia
T₃ (minuto del 3er gol, censura 90) con covariables de tasas: Brier medio
**0.2676 vs 0.2495 de la matriz choque-común** — peor. Coherente con la
teoría: para TOTALES el modelo de conteo Poisson es el natural; la ventaja
del Weibull estaba en el timing del PRIMER gol (BTTS, v27). El Over 2.5 de
la plantilla sigue en la matriz. `resultados_over25_v28.json`.

### §2.5 EVC Platino ✅
Triple validación: EVC (conf >75 %) ∧ mismo partido con arbitraje ν>1 (del
último barrido cacheado) ∧ sin divergencia crítica. Sección destacada ⭐ con
tooltip y **stake ×1.5 pre-cap** en el Kelly simultáneo.

### §2.6 Fallback BTTS ✅ mínimo honesto
fixtures.csv NO trae BTTS (el propio spec lo admite); sin The Odds API la
sección muestra N/D con aviso — comportamiento ya existente, documentado.

## Carril B (rama `experimento/bottom-up`, commit 8cd0e29 — NO fusionada)

- `bottom_up_engine.py`: acumulador de ratings POR JUGADOR desde las páginas
  FotMob (el extracto compacto solo tenía la media de equipo) →
  `ratings_historicos.csv` (787 filas, 528 jugadores, 28 partidos) + PFI
  EMA(α=0.3). Valores sensatos (Messi 8.9).
- `jaccard_index.py`: J(A,H) once de hoy vs once histórico 30 días
  (umbral de fractura 0.7).
- **Validación intermedia (§3.1): solo 3 jugadores cruzables PFI↔xG/90**
  (FotMob=clubes, xG=internacionales) — insuficiente. **El VORP-PFI sobre
  Champions 2022-25 es IMPOSIBLE hoy**: no existen ratings históricos
  masivos gratuitos de esas temporadas; la caché nació en v24. El carril
  queda incubando con acumulación diaria; criterio de fusión intacto
  (mejora ≥1 pp en WF cuando haya cobertura).

## Traductor Quant ✅
`traductor_quant.py` (glosario completo del spec + plantillas deterministas)
ligado al modo Principiante/Pro que existe desde v14 — sin radio duplicado.
Etiquetas y tooltips en Apuestas del Día y arbitraje; base 100 % sin LLM
(Ollama solo reescribe encima, como desde v22).

## No-regresión
test_simetria ✓ · test_match_parlay ✓ · smoke 10 ligas ✓ · AppTest en
**ambos modos** con auto-carga de cuotas activa ✓ · Mundial intacto.

## Calendarizado
RLM + Shadow Bundesliga/Eredivisie (~2026-09-17, 60 días de snapshots);
correlación PFI↔xG y VORP-PFI cuando la cobertura de ratings lo permita.
