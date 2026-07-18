# VALIDACIÓN v25 — Parlays reales, EV completo, CLV y robustez ante el fracaso

**Fecha:** 2026-07-17 · **Regla de oro:** walk-forward obligatorio
(≥ +0.3 pp sin empeorar log-loss > 0.01); los fallos se documentan igual
que los éxitos; el Mundial (60.49 %) no se toca.

---

## 1. Correlación SGP — cópula gaussiana con φ empírica (§1.1) ✅ ADOPTADO

`sgp_correlation.py`: para cada pareja de mercados, φ (correlación de los
indicadores binarios) se estima con 10,514 partidos de las 10 ligas
(últimas 3 temporadas) → 703 parejas en `sgp_correlaciones.json`. La
probabilidad conjunta de una pareja pasa a ser

    P(A∩B) = pA·pB + φ·σA·σB      →  factor f = P(A∩B)/(pA·pB)

**truncado a f ∈ [0.5, 1.0]**: la correlación positiva nunca INFLA nuestra
conjunta (el precio del parlay multiplica cuotas individuales que ninguna
casa paga en legs correlacionados — anti-falso-EV+, la calibración que pedía
la spec). Parejas sin dato → haircut legado 0.95 si comparten macro-familia.

**Validación fuera de muestra** (φ de los 2 primeros años, conjunta evaluada
en el último): error absoluto medio de la conjunta **0.049 (independencia) →
0.0034 (ajuste φ)** — mejora del 93.1 %, correlaciones estables entre
temporadas. In-sample el error es ~0 por identidad algebraica (se reporta
para validar la implementación, no como evidencia). `match_parlay.py` usa
los factores empíricos en el beam search; test de coherencia actualizado.

## 2. CLV y cobertura de EV (§1.2, §2.2) ✅ IMPLEMENTADO

- `odds_api.py`: cliente de The Odds API **agrupado por liga** (1 request =
  todos los próximos partidos de la liga; presupuesto defensivo 20/día,
  estado en `odds_api_state.json`) para h2h + totals 2.5 + btts.
- `odds_historico.db` (SQLite, local/gitignored): TODO snapshot de cuotas se
  guarda con marca de tiempo — también los gratuitos de fixtures.csv y
  Betexplorer, así que **el CLV empieza a acumularse desde hoy sin clave**.
  `cuota_mas_cercana()` (para backtesting sin mirar el futuro, con aviso de
  frescura > 6 h) y `clv_reporte()` (primera captura vs cierre).
- Sección EV de la UI: ahora cubre **1X2 + O/U 2.5 + hándicap asiático ±0.5
  + BTTS** (el mapeo de cuotas reales añadió BTTS; O/U ya llegaba de
  fixtures.csv) + aviso de frescura de cuotas.
- **Estado honesto:** no hay `ODDS_API_KEY` en secrets.toml. La vía The Odds
  API está implementada y probada en seco (degradación limpia verificada);
  para activarla: crear la clave gratuita en the-odds-api.com y añadirla a
  `.streamlit/secrets.toml` o como variable de entorno. BTTS real depende
  de esa clave; el resto funciona ya.

## 3. MLS: clima extremo + geografía (§1.3) ❌ DESCARTADO con evidencia

Backfill Open-Meteo completado: 1,801 partidos-día de 30 ciudades (2023+,
48 % del histórico de 8 años; ~100 % de las ventanas walk-forward).
`mls_features.py`: CLIMA_EXTREMO (tmax > 30 °C y humedad > 60 %) +
ALT_SEDE/DIST_VIAJE/DIFF_HUSO. Walk-forward de 3 variantes:

| Variante | acc media | ll medio |
|---|---|---|
| base (cuotas) | 47.01 % | 1.0391 |
| + geo | 46.98 % | 1.0362 |
| + geo + clima | 46.31 % | 1.0372 |

**Ninguna pasa la regla de oro** — el clima extremo incluso RESTA 0.7 pp
(la spec esperaba +0.3: no se cumplió y se descarta, como ella misma exige).
La caché climática y el módulo quedan listos (inferencia con forecast
incluida) por si el histórico más largo cambia el veredicto en el futuro.

## 4. VORP con fallback estricto (§1.4) ✅ IMPLEMENTADO (experimental)

`alineacion_vorp.py`: once esperado = 11 con más titularidades en la base
sombra (ESPN, v19+); valor = xg90 de jugadores_xg.csv; reemplazo = mediana
de los suplentes; factor λ = Σxg90 once real / Σxg90 once esperado, acotado
[0.85, 1.15]. **Aborta y deja el modelo base intacto** si: alineación no
publicada, <10 titulares con fuzzy > 0.85, o <3 partidos de historial del
equipo — con «Ajuste por alineación no disponible» en la UI. Solo toca las
tasas de goles (λ): el 1X2 calibrado NO se modifica (filosofía v10/v23).
Expander experimental en la vista de clubes; cada aplicación se registra en
`vorp_log.json` para la evaluación 2026-27 (adopción si mejora ≥1 pp).

## 5. Blending 70/30 LaLiga y Ligue 1 (§2.3) ✅ ADOPTADO en ambas

p_final = 0.7·modelo + 0.3·mercado, solo con cuotas vigentes del partido
(sin parámetros ajustados sobre el test: el 70/30 es el de la spec; el
barrido 50-90 se reporta como informativo en resultados_blend_v25.json).

| Liga | base | blend 70/30 | mercado | Veredicto |
|---|---|---|---|---|
| LaLiga | 53.33 / 0.9908 | **54.09 / 0.9747** | 54.83 | ADOPTADO (+0.76 pp) |
| Ligue 1 | 51.65 / 1.0873 | **52.17 / 0.9998** | 53.43 | ADOPTADO (+0.52 pp, ll −0.09) |

Implementado en `ClubEngine.predecir` (config `blend_mercado`), con insight
⚖️ y excluyente con el MESM (que ninguna de las dos tiene). Sin reentrenos:
es un ajuste de inferencia puro.

## 6. Champions: reintento del IMT compuesto (§2.5) ❌ SIN CAMBIO

Mismo histórico que en v24 (no hay partidos nuevos de FBref/API-Football en
pretemporada): imt_c 58.97/0.9385 vs base 57.99/0.9258 — +0.98 pp pero el
log-loss sigue excediendo la regla por 0.003. Se reintentará cuando la
2026-27 aporte partidos (el arnés queda listo: `run_wf_imt_v24.py champions`).

## 6b. SmartParlayBuilder: lista blanca y categorías (§2.1) ✅ / ⚠️

- **Lista blanca dinámica** ✅: checkbox «Solo mercados con cuota REAL
  vigente» — el parlay se limita a los mercados de odds_actuales.json
  (1X2, O/U 2.5, BTTS, AH ±0.5) y su EV es 100 % accionable. Con aviso
  honesto cuando no hay cuotas vigentes (p. ej. receso veraniego).
- **Control de categorías** ✅: multiselect Resultado/Goles/Córners/Tarjetas
  (la degradación con aviso de diversidad ya existía y aplica igual).
- **Puntuación dinámica por xG/ELO** ⚠️ NO implementada a propósito: el
  sistema de zonas v20 ya garantiza variabilidad entre perfiles, y alterar
  la función de puntuación validada sin un arnés de backtesting de parlays
  violaría la regla de oro (cambio no validable hoy). Documentado como
  candidato v26 si se construye ese arnés.

## 7. Panel de comparación rápida (§2.4) ✅

`render_comparador`: dos partidos lado a lado (favorito, 1X2, marcador
probable, goles esperados y qué partido ve más claro el modelo), disponible
en el Mundial y en todas las ligas de clubes.

## 8. No-regresión

- `test_simetria.py` ✓ (Mundial intacto, bit a bit)
- `test_match_parlay.py` ✓ (actualizado al factor φ; perfiles siguen
  diferenciados y las zonas se respetan)
- AppTest del dashboard (Mundial/MLS/Liga MX/LaLiga) ✓
- ClubEngine smoke (predicción + plantilla en ligas modificadas) ✓

## 9. Áreas de mejora (v26)

1. **Activar ODDS_API_KEY** (500 créditos/mes gratis) → BTTS real, capturas
   1 h antes del inicio y CLV completo con `clv_reporte()`.
2. **SGP con cuotas reales de Bet365** si alguna fuente gratuita las expone:
   permitiría calibrar el truncado [0.5, 1.0] contra precios verdaderos.
3. **MLS**: el modelo puro sigue 3 pp bajo el mercado; probar MESM con más
   historial de cuotas y el blending 70/30 (no se probó aquí para no
   apilar dos cambios sin validación independiente).
4. **VORP**: evaluar en 2026-27 con el log acumulado; extender el colector
   sombra a MLS (ESPN código `usa.1`, hoy no está en LIGAS_ESPN).
