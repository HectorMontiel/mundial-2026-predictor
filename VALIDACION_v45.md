# VALIDACIÓN v45 — Validación exhaustiva de mercados y props (autónoma en decisiones)

**Fecha:** 2026-07-24 · El usuario pidió: validar **todos** los mercados (no
solo dos) y meter los rentables; y hacer el **modelo de props** de verdad,
probando vías alternas y desplegándolo **si funciona**. La consigna best-in-
class se cumple con rigor: se valida todo y **solo se despliega lo que gana**.

---

## 0. Resumen ejecutivo (decisiones, no promesas)

| Frente | Resultado |
|---|---|
| Mercados de fútbol (1X2, O/U 2.5, Hándicap) | **Solo el 1X2 es rentable y robusto.** O/U 2.5 y Hándicap: bootstrap p5 negativo → NO se adoptan. |
| Props MLB (ponches) | Modelo construido con **MLB Stats API** (vía alterna a pybaseball). Probadas 4 formulaciones — **ninguna bate al baseline** → NO se despliega como apuesta (sería −EV). |
| CLV predictor | **574 series** con ≥2 snapshots (igual que v39): insuficiente para un modelo sin sobreajuste. Diferido. |
| NBA | Motor listo; se activará en octubre y su 1X2 pasará el mismo bootstrap p5 antes de ser accionable. |

**La disciplina es el producto:** un equipo de élite no despliega un mercado o
un modelo que pierde dinero. v45 lo demuestra con números.

---

## 1. Validación EXHAUSTIVA de mercados (§3, ampliada)

Se backtestearon **todos** los mercados con cuotas de cierre reales en
football-data, con el mismo protocolo de la v44 (selección validada + bootstrap
p5). El hándicap asiático se liquida en su **línea de cierre real** (`AHCh`)
con reparto de margen por convolución de dos Poisson y liquidación de cuartos/
push (`_liquidar_ah`):

| Mercado | n | ROI | **ROI p5 (bootstrap)** | Veredicto |
|---|---|---|---|---|
| **1X2 (resultado)** | 328 | **+9.10 %** | **+2.35** | 🟢 rentable y robusto |
| Over/Under 2.5 | 244 | +1.52 % | −7.31 | 🟡 marginal |
| Hándicap asiático | 383 | −9.39 % | −16.70 | 🔴 no rentable |

**Conclusión:** los mercados de fútbol derivados del reparto de goles (O/U,
hándicap) son demasiado eficientes; el modelo no los bate. Solo el **1X2**
mantiene edge robusto. `MERCADOS_VALIDADOS_CAPA1 = {'1X2'}` se confirma; O/U y
hándicap quedan como informativos. BTTS y otros mercados **no tienen cuotas de
cierre históricas** para backtestear → no se pueden validar con este método
(se mantienen en su sección, calibración validada, sin ROI-validar).

Nueva capacidad reutilizable: `league_engine` genera `roi_bets_ou_*` y
`roi_bets_ah_*`; `model_audit` muestra la **matriz por mercado** con su
veredicto.

---

## 2. Modelo de PROPS de jugadores (§1) — construido, validado, NO desplegado

### 2.1 La vía de datos (alterna, contundente)

`pybaseball` no está instalado y `historico_mlb.csv` no trae ponches por
pitcher. **Solución: la MLB Stats API pública** (`statsapi.mlb.com`, gratis,
sin instalar) — da game logs de pitcheo con ponches, batters faced e innings.
`props_model.py` la usa para el modelo sabermétrico
`K_esp = (K/BF del pitcher) · (K% rival / K% liga) · BF_esperados`.

### 2.2 La validación (y por qué NO se despliega)

Sin cuotas HISTÓRICAS de props no se puede backtestear el ROI; se valida la
**predicción** (¿acierta los ponches mejor que un baseline?). Probadas **cuatro
formulaciones** sobre 211-261 aperturas reales:

| Modelo | MAE | vs baseline |
|---|---|---|
| baseline (media del pitcher) | 1.90 | — |
| tasa de temporada × BF | 1.85 | **+2.3 %** (marginal) |
| forma reciente (últimas 5) | 2.02 | −6.3 % |
| reciente + ajuste de rival | 2.00 | −5.4 % |
| reciente-3 × BF reciente | 2.11 | −11.1 % |

**Ninguna formulación bate significativamente al baseline.** Los ponches están
dominados por la tasa estable del pitcher; la forma reciente y el ajuste de
rival **meten ruido**. Como nuestra predicción ≈ la del mercado (ambos usan la
tasa del pitcher), no hay hueco de EV explotable con datos públicos. **Decisión
best-in-class: NO se despliega apuesta de props (sería −EV).** `props_model.py`
queda como infraestructura validada, lista si aparecen datos con más señal
(pitch-level, splits L/R, framing del catcher — lo que usan las apps de pago).

---

## 3. CLV predictor (§2) — diferido con dato

`odds_historico.db` tiene **574 series** con ≥2 snapshots (v39 tenía 589): el
workflow captura 1×/día, así que las series multi-snapshot no crecen. Entrenar
un predictor de movimiento sobre 574 series sobreajustaría. Se difiere hasta
subir la frecuencia de captura (candidato a v46, ponderando el coste de la API).

---

## 4. NBA (§4)

Motor v30 listo, CDI adoptado, claves y ventana de temporada (oct-jun)
configuradas. En cuanto The Odds API devuelva cuotas de NBA (octubre), su 1X2
entra en el barrido; **pasará el mismo bootstrap p5 antes de ser accionable en
Capa 1** (la misma vara que tumbó O/U y hándicap).

---

## 5. No regresión

- `test_simetria.py`, `test_match_parlay.py` → **TODO OK** (Internacionales 60.49 %).
- `smoke_v45.py` (AppTest, 11 vistas) → **0 excepciones**.
- Backtests O/U y hándicap ADITIVOS (regresores Poisson locales; no tocan el
  1X2). Ligas `main` reentrenadas y verdes. `props_model` es standalone.

---

## 6. Entregables

`league_engine.py` (cuotas + backtest de hándicap asiático, `_liquidar_ah`) ·
`model_audit.py` (matriz por mercado 1X2/O-U/Hándicap con pnl) ·
`props_model.py` (modelo de ponches vía MLB Stats API + validación) ·
`roi_bets_ah_*.json` · `VALIDACION_v45.md`.

**Resultado:** v45 responde con rigor la pregunta del usuario — **de todos los
mercados backtesteables, solo el 1X2 da retorno robusto** — y aborda el modelo
de props con una vía alterna real (MLB Stats API), demostrando con datos que
**no ofrece edge con información pública** y, por tanto, no se despliega como
apuesta. El valor de esta versión es la disciplina: proteger el capital del
usuario no metiendo mercados ni modelos que pierden.
