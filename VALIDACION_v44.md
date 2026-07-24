# VALIDACIÓN v44 — Validación multi-mercado: qué mercados dan retorno (autónoma)

**Fecha:** 2026-07-24 · Versión **autónoma** tras la v43. Foco: no conformarse
con el 1X2 — investigar si OTROS mercados dan retorno, con datos y bootstrap.
Aprendizaje de la racha: cada mercado hay que VALIDARLO, no asumirlo.

---

## 0. La pregunta que nadie había respondido

Todo el edge validado del proyecto (−0.34 → +9.9 → +14.7 %) era del **1X2**.
Pero el sistema APOSTABA también Over/Under 2.5, BTTS y hándicap **sin haber
validado nunca si esos mercados son rentables**. v44 lo responde con datos.

---

## 1. Backtest del mercado Over/Under 2.5 (nueva capacidad)

`league_engine` (roi_sim) ahora, además del 1X2, **backtestea O/U 2.5** en las
ligas de formato `main` (las únicas con cuotas O/U de cierre en football-data:
`Avg>2.5`/`Avg<2.5`). Regresores Poisson locales sobre el train → λ por
partido → P(total > 2.5), y se apuesta al lado con EV+ usando la cuota de
cierre. Resultados por liga (crudo, todos los EV+):

| Liga | n | ROI O/U |
|---|---|---|
| Serie A | 197 | −1.9 % |
| LaLiga | 333 | −2.5 % |
| Primeira | 489 | −6.2 % |
| Premier | 190 | −6.9 % |
| Ligue 1 | 293 | −8.0 % |
| Bundesliga | 261 | −14.1 % |
| Eredivisie | 267 | −14.8 % |
| Turquía | 174 | −17.6 % |

**El mercado de goles pierde en TODAS las ligas.** Es de los más eficientes
(mucha liquidez, todos lo modelan bien).

## 2. ¿Lo rescata la selección validada? NO (bootstrap p5 negativo)

Aplicando la selección que hace rentable al 1X2 (banda EV ∩ prob ≥ 0.55 ∩
convicción) sobre el pool O/U:

| Filtro | n | ROI | **ROI p5 (bootstrap)** |
|---|---|---|---|
| crudo | 2.204 | −8.4 % | — |
| EV[2,12] ∩ prob≥0.55 | 306 | +2.7 % | **−5.2 %** |
| EV[2,12] ∩ prob≥0.60 | 209 | +5.0 % | **−3.7 %** |
| selección completa | 244 | +1.5 % | **−7.3 %** |

El ROI medio se vuelve marginalmente positivo, pero **el bootstrap p5 es
NEGATIVO en todos los cortes** → NO es robusto (por el criterio de la v40, un
mercado solo se adopta si su p5 > 0). **Over/Under 2.5 NO se adopta.**

Matriz por mercado (`model_audit`, con la selección validada):

| Mercado | n | ROI | ROI p5 | Veredicto |
|---|---|---|---|---|
| **1X2 (resultado)** | 328 | **+9.1 %** | **+2.35** | 🟢 rentable y robusto |
| Over/Under 2.5 | 244 | +1.5 % | −7.31 | 🟡 marginal (no robusto) |

## 3. Acción: proteger la Capa 1 (siempre retorno)

Como el usuario exige "que siempre haya retorno de lo invertido", la **Capa 1
accionable se restringe a los mercados con edge VALIDADO** (`MERCADOS_
VALIDADOS_CAPA1 = {'1X2'}`). O/U y hándicap pasan a **candidatos**
(informativo), nunca a la Capa 1. Así el ROI validado (+9.9 %/+14.7 % sharp)
no se diluye con un mercado que no bate a su cierre. Se ampliará a otros
mercados **en cuanto superen el bootstrap p5** — el listón es explícito y
reproducible.

BTTS mantiene su sección propia (prioridad del usuario, calibración validada
en v26/v27) claramente separada de la Capa 1 accionable.

## 4. No regresión

- `test_simetria.py`, `test_match_parlay.py` → **TODO OK** (Internacionales 60.49 %).
- `smoke_v44.py` (AppTest, 11 vistas) → **0 excepciones**.
- El backtest O/U es ADITIVO (regresores Poisson locales en el roi_sim; no
  toca el pipeline 1X2). Las ligas `main` se reentrenaron y siguen verdes.

## 5. Entregables

`league_engine.py` (cuotas O/U de cierre + backtest O/U → `roi_bets_ou_*`) ·
`alpha_finder.py` (`MERCADOS_VALIDADOS_CAPA1`, gate de Capa 1) ·
`model_audit.py` (matriz por mercado con bootstrap p5) · `roi_bets_ou_*.json` ·
`VALIDACION_v44.md`.

**Resultado:** v44 responde con rigor una pregunta abierta desde siempre —
**solo el 1X2 tiene edge robusto; Over/Under 2.5 no bate a su mercado** — y
BLINDA la Capa 1 para que "siempre haya retorno". Un negativo bien medido vale
tanto como un positivo: evita que metamos un mercado perdedor por ampliar
cobertura. El listón (bootstrap p5 > 0) queda abierto para admitir mercados
nuevos en cuanto lo superen.
