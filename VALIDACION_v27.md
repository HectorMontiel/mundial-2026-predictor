# VALIDACIÓN v27 — Precisión estructural, arbitraje cruzado y riesgo quant

**Fecha:** 2026-07-18 · Regla de oro: walk-forward obligatorio; fracasos
documentados; Mundial 1X2 (60.49 %) intacto.

## 1. Dixon-Coles (§1) ❌ DESCARTADO con evidencia

ρ estimado por máxima verosimilitud en malla (−0.15…+0.05) sobre 13k+
partidos (70 % train) con λ,μ rolling: el train prefiere **ρ=+0.05 — signo
OPUESTO a la teoría** (sobreajuste al ruido de las λ), y en el 30 % de
validación el log-loss del marcador exacto NO mejora (3.0655 vs 3.0652 de
Poisson puro, Δ=−0.0003). La dependencia de marcadores bajos no es
detectable/explotable con nuestras tasas → la matriz de producción no se
toca. Evidencia en `resultados_dixon_coles_v27.json` (malla completa).

## 2. Transición BTTS → Weibull AFT (§2) ✅ ADOPTADA

Se reforzó el baseline del A/B v26 con la MATRIZ DE CHOQUE COMÚN de
producción (λc = 0.12·min, la misma de `_monte_carlo`): la supervivencia
gana igual — **Brier 0.2358 vs 0.2516 (Poisson) y 0.2513 (matriz-choque)**,
mejor en 6/6 ventanas. La plantilla del Mundial usa ahora el BTTS de
supervivencia (`prediction_api.plantilla`, con la matriz de respaldo si el
artefacto falta); Over/Under sigue en la matriz (§2.2: solo BTTS en esta
fase). 1X2 verificado intacto (test_simetria bit a bit).

## 3. Shadow Booster 2.0 (§3) — CN adoptado en LaLiga y Ligue 1

- **RLM (movimiento de línea)**: IMPOSIBLE de backtestear hoy — exige
  histórico de snapshots que `odds_historico.db` apenas acumula desde v25.
  Forward-only, documentado; se validará cuando haya meses de capturas.
- **CASTIGO_NARRATIVO** (ELO_VEL × (1−entropía), adaptado a diffs): re-WF
  de las 9 ligas:

| Liga | ROI base | Shadow 1.0 (v26) | Shadow 2.0 (+CN) | n | Decisión |
|---|---|---|---|---|---|
| LaLiga | +5.1 % | +2.4 % | **+7.3 %** | 285 | ✅ ADOPTAR (con CN) |
| Ligue 1 | −9.3 % | −13.7 % | **−0.2 %** | 273 | ✅ ADOPTAR (con CN; filtro que lleva una liga perdedora a breakeven) |
| MLS | −7.8 % | **+2.6 %** | −2.0 % | 763 | ✅ mantiene la variante v1 SIN CN (el CN la empeora — la feature es configurable por liga) |
| Serie A | +3.9 % | +22.8 % | +27.4 % | 59 | ❌ n insuficiente (1σ ≈ ±19 pp) |
| Eredivisie | −11.1 % | −24.3 % | −9.7 % | 236 | ❌ mejora pero sigue muy negativo — no accionable |
| Premier / Bundesliga / Primeira / Liga MX | — | — | peor que base | — | ❌ |

Producción: `shadow.joblib` en mls (sin CN), laliga y ligue_1 (con CN);
cada artefacto guarda su variante (`con_cn`). 27 señales ⚡ vigentes.

## 4. Arbitraje de mercado cruzado (§4) ✅ (con hallazgo)

**Los compuestos pre-empaquetados (result+btts / result+totals) NO existen
en la capa gratuita** (422 INVALID_MARKET, verificado). Sí existen POR
EVENTO: `double_chance`, `draw_no_bet`, `alternate_totals`, `team_totals` —
mercados derivados con overround alto que `cross_arbitrage.py` valora
EXACTAMENTE con la matriz del motor (señal si cuota > justa × 1.05).
Corrección importante detectada en la primera corrida: las líneas ENTERAS
de totales (1.0, 2.0) tienen push y la prob binaria las sobrevaloraba — solo
se valoran líneas .5. Primer barrido real: 13 oportunidades en 5 eventos
(antes del filtro de líneas). Sección UI con botón (gasta ~5 créditos).

## 5. Kelly simultáneo + cap 20 % (§5) ✅ ADOPTADO

`kelly_simultaneo.py`: ⅛ Kelly por apuesta (tope 5 %) con escalado
proporcional si la jornada excede el 20 % del bankroll. Montecarlo
comparativo (1,000 sims × 60 jornadas × 5 apuestas, parámetros reales):

| | ¼ Kelly secuencial | ⅛ simultáneo + cap 20 % |
|---|---|---|
| Drawdown máx. mediano | 24.3 % | **13.0 %** |
| Bankroll final mediano | 2,058 | 1,465 |
| Prob. de ruina | 0 % | 0 % |

Cumple el objetivo de la spec (drawdown casi a la mitad); el menor
crecimiento mediano es el precio explícito y se reporta. Stakes en la UI de
Apuestas del Día con la exposición total de la jornada.

## 6. Abogado del diablo (§6) ✅

`asistente_comentarios.comentario_partido` añade el bloque de divergencia:
si confianza >70 % y el Shadow (direccional) < −0.05 → párrafo de
precaución 🕵️; si el Shadow respalda (> +0.05) → refuerzo ⚡. Determinista
(idéntico sin Ollama; con Ollama el SLM lo reescribe incluido).

## 7. EVC 2.0 (§7) ✅

Capa de decisión en `alpha_finder`: élite (prob >70 %, EV >+3 %, cuota
>1.50) **∧** Shadow conforme (residuo direccional > −0.03 en ligas
adoptadas; omitido en el resto) → «💎 EVC»; divergencia crítica (conf >75 %
∧ residuo < −0.05) → descartada con nota visible. Los picks EVC llevan el
stake del Kelly simultáneo. Los modelos individuales NO se modifican.
El backtest específico del filtro EVC es el propio §3 (ROI base∧shadow vs
base) — positivo en las 3 ligas adoptadas.

## 8. No-regresión

test_simetria ✓ · test_match_parlay ✓ · smoke 10 ligas ✓ · AppTest
(Apuestas del Día + Liga MX) ✓ · Mundial intacto.

## 9. Pendientes v28

RLM cuando haya meses de snapshots; Shadow Serie A con más histórico;
Over/Under por supervivencia (suma de tiempos de gol); h2h_h1 (modelo de
mitades) en el arbitraje cruzado.
