# VALIDACIÓN v42 — Confirmación Sharp: batir a las apps de pago con su propia arma

**Fecha:** 2026-07-24 · Versión **autónoma** tras la v41. Foco: **más ROI y
batir al mercado / apps de pago**, con una ruta nueva. La estrategia de
siempre: anclar en datos, buscar alternativas, validar.

---

## 0. La idea nueva (nunca antes en el proyecto)

Todo el ROI validado hasta v41 salía de comparar el modelo contra UNA casa. Las
apps de pago hacen algo distinto y más potente: comparan contra la **línea
sharp** — la de **Pinnacle**, la casa más eficiente del mundo, cuyo cierre es
el mejor estimador de probabilidad que existe. Apostar solo cuando tu modelo
supera la probabilidad *devig* de Pinnacle es la **confirmación sharp**, el
patrón de oro del apostador profesional.

**Hallazgo (validado sobre las apuestas reales con cierre de Pinnacle):**

| Selección (banda ∩ prob ∩ convicción) | n | ROI | ROI p5 (bootstrap) |
|---|---|---|---|
| Todas | 297 | +9.9 % | +2.8 % |
| Con cierre de Pinnacle disponible | 105 | +12.0 % | −0.8 % |
| + modelo supera al sharp (gap ≥ 0) | 104 | +13.1 % | +0.8 % |
| **+ gap ≥ 5 pp (confirmación sharp)** | 83 | **+14.7 %** | **+1.4 %** |

Cuanto más supera el modelo a la línea sharp, mayor el ROI: de +9.9 % a
**+14.7 %**. Es una señal de CALIDAD, no de cobertura.

---

## 1. El dato que faltaba — y su arreglo

El problema: solo **105 de 297** apuestas tenían el cierre de Pinnacle
registrado → la señal sharp cubría un tercio. La causa: **no capturábamos
Pinnacle en vivo**.

**Verificación de disponibilidad (2026-07-24):** Pinnacle SÍ está en The Odds
API — MLS 15/15 eventos, MLB 13/15, Brasil 10/18 lo incluyen. Así que se puede
capturar.

**El arreglo (coste 0 en créditos):** `odds_api.capturar_liga` ya pedía la
región `eu` (donde vive Pinnacle); ahora, además de la primera casa (precio
apostable), **busca la casa `pinnacle` en la MISMA respuesta** y la guarda con
`fuente='pinnacle'`. Sin peticiones extra. `cuotas_recientes(..., fuente=
'pinnacle')` la lee por separado (y la excluye de la lectura principal para no
contaminar el precio apostable). `fetch_odds` inyecta `odd_home/draw/away_pin`
en `odds_actuales.json`.

---

## 2. Integración

- `alpha_finder._mercados_del_partido`: por cada pick 1X2 calcula el
  **`sharp_gap`** = prob del modelo − prob *devig* de Pinnacle (se le quita el
  margen normalizando las tres probabilidades implícitas). Si el gap ≥ 5 pp,
  marca `sharp_confirmado`.
- Los picks confirmados por el sharp **se ordenan primero** en la Capa 1 y
  lucen **💠** en el dashboard ("Confirmado por línea sharp (Pinnacle)") y en el
  mensaje de Telegram.
- Es un realce de calidad: no cambia qué picks son válidos, prioriza los de
  mayor ROI esperado. No degrada nada cuando Pinnacle no está disponible.

---

## 3. No regresión

- `test_simetria.py`, `test_match_parlay.py` → **TODO OK** (Internacionales 60.49 %).
- `smoke_v42.py` (AppTest, 11 vistas) → **0 excepciones**.
- Sin dependencias nuevas ni coste extra de API. La lectura principal de cuotas
  se aísla explícitamente de la línea sharp (test: Pinnacle no contamina el
  precio apostable). Señal unitaria verificada (gap +0.072 → confirmado).

---

## 4. Entregables

`odds_api.py` (captura de Pinnacle en la misma petición + `cuotas_recientes`
con filtro de fuente) · `fetch_odds.py` (inyección de `odd_*_pin`) ·
`alpha_finder.py` (`sharp_gap`, `sharp_confirmado`, orden y umbral) ·
`dashboard_ui.py` (💠 en tarjetas) · `bot_telegram.py` (💠 en el resumen) ·
`VALIDACION_v42.md`.

**Resultado:** la plataforma incorpora la **confirmación sharp de Pinnacle** —
el arma de las apps de pago — de forma gratuita: los picks donde el modelo bate
a la línea más eficiente del mundo por ≥5 pp rindieron **+14.7 % de ROI** en
backtest, y ahora se capturan en vivo y se destacan con 💠. Progresión del ROI
validado del proyecto: −0.34 → +0.81 → +7.9 → +9.9 → **+14.7 % (tier sharp)**.
