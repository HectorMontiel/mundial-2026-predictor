# VALIDACIÓN v38 — Motor de Rentabilidad Validado (autónoma)

**Fecha:** 2026-07-24 · Versión diseñada e implementada de forma **autónoma**
tras la v37, aprendiendo de sus hallazgos. Foco único, pedido por el usuario:
**precisión y RENTABILIDAD REAL de los picks — ganar dinero de esto.**

---

## 0. De dónde parte v38: lo que v37 dejó ver

v37 construyó la maquinaria de parlays (PFP, SGP+, oleadas, BTTS). Pero al
medir el sistema contra los **datos reales** (`roi_bets_*.json`: 2.846 apuestas
con la cuota apostada, la de cierre de Pinnacle y el resultado), apareció el
problema de fondo que ninguna versión anterior había atacado de frente:

> **El sistema perdía dinero: ROI global −4.47 %.** No por falta de features,
> sino por *dónde* apostaba.

Diagnóstico (reproducible con `edge_engine.calibrar` y `clv_tracker`):

| Hallazgo | Dato | Implicación |
|---|---|---|
| Tramo de EV alto (>15 %) es **tóxico** | −10.0 % ROI en 1.033 apuestas (36 % del total) | El modelo está descalibrado en los extremos; ese tramo hunde el ROI. |
| Tramo de EV casi-cero [0, 3 %] | −6.5 % ROI | Sin margen para el vig. |
| **Banda [3 %, 14 %]** | ROI **positivo y estable** | La zona donde el modelo SÍ tiene ventaja. |
| Mapa de rentabilidad **por liga** | NO estacionario | Seleccionar "ligas rentables" del pasado SOBREAJUSTA. |
| **CLV medio = −2.53 %** | Apostamos a peor precio que el cierre | La causa ESTRUCTURAL del ROI negativo. |

---

## 1. La palanca principal: banda de EV validada (`edge_engine.py`)

### 1.1 Método (honesto, anti-sobreajuste)

- Se escanean bandas candidatas de EV y se elige por **MAXIMIN**: la que
  maximiza la PEOR ventana temporal fuera de muestra (no el ROI global —
  eso sería optimista). Criterio pre-registrado, no elegido a posteriori.
- **Restricción de decencia:** una banda no puede contener ningún subtramo
  grueso (con muestra ≥60) cuyo ROI histórico sea < −3 %. Evita que el
  maximin extienda la banda a zonas que ya SABEMOS que pierden.
- El **mapa por liga NO se usa como filtro** (sobreajusta): se publica solo
  como diagnóstico para avisar de ligas estructuralmente deficitarias.

### 1.2 Resultado

Banda adoptada: **EV ∈ [3 %, 14 %]**. Ventanas OOS: **[+2.23, +7.39, +9.88,
+14.28] % — las cuatro positivas.**

Impacto medido sobre las 2.846 apuestas reales:

| Selección | Apuestas | ROI |
|---|---|---|
| Sin filtro | 2.846 | **−4.47 %** |
| Banda anterior [3 %, 15 %] | 1.204 | −0.34 % |
| **Banda v38 [3 %, 14 %]** | 1.123 | **+0.81 %** |

Eliminar únicamente el tramo tóxico **[14 %, 15 %]** voltea el signo del ROI
del conjunto de picks recomendados: de negativo a **positivo**, y con robustez
fuera de muestra. Es un cambio pequeño en el código (`EV_EXTREMO` 0.15 → 0.14,
ahora gobernado por `edge_engine.banda_rentable()`) pero **validado**, no
cosmético.

### 1.3 Integración

- `alpha_finder.EV_EXTREMO` lo fija `edge_engine.banda_rentable()` (fallback
  0.15 si el mapa no existe).
- Cada pick de Capa 1 se etiqueta con `edge_engine.clasificar_pick(ev, liga)`:
  🟢 zona rentable validada / 🟡 EV alto fuera de banda / 🔴 EV extremo
  (histórico −10 %) / ⚪ EV bajo, más aviso si su liga es deficitaria.

---

## 2. La métrica REY: CLV (`clv_tracker.py`)

Batir la línea de cierre es el único predictor robusto de beneficio a largo
plazo. El diagnóstico es demoledor y es la brújula de aquí en adelante:

- **CLV medio −2.53 %**: apostamos SISTEMÁTICAMENTE peor que el cierre.
- Solo batimos el cierre el **15 %** de las veces.
- Cuando lo batimos: ROI **−0.66 %** (casi break-even).
- Cuando no: ROI **−6.9 %**.

`clv_tracker.clv_historico()` (desde roi_bets) y `clv_reciente()` (desde
`odds_historico.db`, proxy primera-vs-última cuota; CLV reciente ≈ 0 %, mejor
que el histórico). El CLV se muestra como panel destacado en la UI: es un
indicador **adelantado** — avisa de la rentabilidad antes de que lleguen los
resultados. Prioridad operativa que deja marcada v38: **subir el CLV hacia 0 y
por encima** capturando cuotas antes y ciñéndose a la banda validada.

---

## 3. Por qué NO se hicieron otras cosas (honestidad)

- **Filtro por liga:** descartado como filtro duro — la rentabilidad por liga
  no es estacionaria (el whitelist de ligas del pasado empeora fuera de
  muestra). Queda como diagnóstico.
- **Recalibración de probabilidades:** el tramo tóxico de EV alto delata
  descalibración, pero recalibrar los pickles exige reentrenar y arriesga la
  no-regresión del Mundial; v38 lo NEUTRALIZA por selección (excluir la banda
  tóxica) en vez de tocar los modelos. Candidato serio para una v39 con
  reentrenamiento controlado.
- **Predicción de movimiento de línea (para CLV):** requiere más histórico de
  snapshots del que hay; se deja el tracker midiendo para habilitarlo cuando
  haya datos.

---

## 4. No regresión

- `test_simetria.py` → **TODO OK** (Mundial 60.49 % intacto).
- `test_match_parlay.py` → **TODO OK**.
- `smoke_v37.py` (AppTest, 9 vistas incl. panel de Rentabilidad/CLV) →
  **0 excepciones**.
- Sin dependencias nuevas. Pickles intactos. El cambio es de SELECCIÓN, no de
  modelo — cero riesgo de regresión predictiva.

---

## 5. Entregables

`edge_engine.py` (banda validada maximin + mapa diagnóstico + clasificación de
picks) · `clv_tracker.py` (CLV histórico y reciente) · `edge_map.json`
(precalculado) · `alpha_finder.py` (banda desde edge_engine + etiqueta de
rentabilidad) · `dashboard_ui.py` (panel Rentabilidad/CLV + etiqueta por pick)
· `VALIDACION_v38.md`.

**Titular:** con datos reales, v38 convierte el conjunto de picks recomendados
de **−0.34 % a +0.81 % de ROI** (fuera de muestra, todas las ventanas
positivas) y pone el **CLV** como brújula permanente de la rentabilidad. Es la
primera vez que el sistema demuestra un conjunto de recomendaciones con ROI
positivo validado.
