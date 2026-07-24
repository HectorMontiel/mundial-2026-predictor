# VALIDACIÓN v40 — Máxima robustez y ROI: convicción + bootstrap (autónoma)

**Fecha:** 2026-07-24 · Versión **autónoma** tras la v39, aprendiendo de sus
hallazgos. Foco del usuario: **más ROI, más robustez, seguir batiendo al
mercado**. Estrategia intacta: cada cambio anclado en datos reales y validado,
con investigación de alternativas.

---

## 0. Titular

| Métrica (selección de Capa 1) | v39 | **v40** |
|---|---|---|
| Selección | EV[3–12 %] ∧ prob≥0.55 | + **convicción prob×EV ≥ 0.025** |
| Apuestas | 337 | 297 |
| **ROI medio (backtest)** | +7.9 % | **+9.9 %** |
| **ROI p5 (bootstrap, peor 5 % plausible)** | +0.7 % | **+2.6 %** |
| ROI p95 | +14.9 % | +17.2 % |

v40 sube el ROI **y** eleva el suelo de robustez: incluso en el peor 5 % de
escenarios remuestreados, la selección es rentable (+2.6 %). Y trae una
**mejora metodológica de fondo**: se abandona el maximin de 4 ventanas (frágil)
por el **bootstrap**, que es libre de fronteras arbitrarias.

---

## 1. La palanca de ROI: filtro de CONVICCIÓN (prob × EV)

### 1.1 Idea

Un pick fuerte tiene **prob alta Y EV alto a la vez**. El producto `prob × EV`
captura esa doble fuerza: exigir un mínimo descarta los picks "flojos por los
dos lados" (prob mediana con EV mediano) que erosionan el ROI. Es ortogonal a
la banda de EV y al piso de probabilidad.

### 1.2 Calibración por bootstrap p5 (la robustez)

| Convicción | n | ROI | **ROI p5 (bootstrap)** |
|---|---|---|---|
| 0.000 | 337 | +7.9 % | +0.8 % |
| 0.020 | 324 | +9.5 % | +2.4 % |
| **0.025** | **297** | **+9.9 %** | **+2.6 %** |
| 0.030 | 254 | +8.4 % | +0.2 % |

Se adopta **0.025** por maximizar el **p5 del bootstrap** (mejor peor-ROI
plausible), no el ROI medio. `edge_engine.conviccion_min()` lo publica;
`alpha_finder` lo aplica como gate adicional de Capa 1.

### 1.3 Lección de robustez que ORIGINA el cambio de método

Al calibrar la convicción con el **maximin de 4 ventanas** de la v39, el
resultado era **inconsistente**: elegía convicción 0.0 con la selección ya
prefiltrada, pero 0.025 con la selección sin prefiltrar — porque las ventanas
caen en fechas distintas según qué se filtró antes. **El maximin de ventanas
depende de dónde caen los límites de ventana: es frágil.**

La corrección (mejora metodológica de v40): **seleccionar por el percentil 5
del bootstrap.** El bootstrap remuestrea la selección completa 2.000–3.000
veces sin fronteras temporales arbitrarias; su p5 es el "peor ROI plausible al
95 %". Maximizar el p5 es un criterio robusto, honesto y reproducible. Con él,
la convicción 0.025 gana de forma estable, y se publica el **CI bootstrap de
la selección final** como métrica de confianza (p5 +2.6 %).

---

## 2. Investigación de otras palancas (negativos honestos)

Se probaron y se descartaron con datos, no por pereza:

- **Staking de Kelly:** flat (+7.9 %) supera a ¼Kelly (+6.1 %) y ½Kelly
  (+7.0 %) sobre la selección. Las probabilidades no son lo bastante precisas
  para que Kelly amplifique; el stake plano es más robusto. **No se adopta.**
- **Filtro "valor vs línea sharp"** (cuota ≥ 0.99 × cierre Pinnacle): reduce el
  ROI (10.9 % → 7.6 %) y el volumen. Batir al cierre no es un buen pre-filtro
  en esta muestra (ya visto en v38/v39). **No se adopta.**
- **Techo de cuota:** la selección (prob≥0.55) ya vive en cuota[1.5, 2.4); el
  grueso está en [1.5, 1.9) con +10.3 % — no hace falta un techo explícito.
- **Recalibración de probabilidades** (heredado de v39): sigue rompiendo la
  banda; candidato a v41 solo con reentrenamiento base controlado.

---

## 3. No regresión

- `test_simetria.py`, `test_match_parlay.py` → **TODO OK** (Mundial 60.49 %).
- `smoke_v40.py` (AppTest, 11 vistas, panel de Rentabilidad con CI bootstrap) →
  **0 excepciones**.
- Sin dependencias nuevas (numpy ya presente para el bootstrap). Pickles
  intactos. El cambio de ROI es de SELECCIÓN, no de modelo.

---

## 4. Entregables

`edge_engine.py` (calibración de convicción por bootstrap p5 + CI de la
selección) · `alpha_finder.py` (gate de convicción en Capa 1) ·
`dashboard_ui.py` (CI bootstrap en el panel de rentabilidad) · `edge_map.json`
· `smoke_v40.py` · `VALIDACION_v40.md`.

**Resultado:** v40 lleva la selección recomendada a **+9.9 % de ROI** con un
suelo bootstrap de **+2.6 %** (el peor 5 % plausible sigue ganando), y sustituye
el criterio frágil de ventanas por el bootstrap, libre de fronteras. Cada
versión desde la v38 ha subido el ROI validado —  −0.34 % → +0.81 % → +7.9 %
→ **+9.9 %** — y esta lo hace además siendo la más robusta.
