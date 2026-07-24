# VALIDACIÓN v46 — Universalización del edge: line shopping + sharp en todos los deportes (autónoma)

**Fecha:** 2026-07-24 · Versión **autónoma** tras la v45. La v45 cerró puertas
con rigor (props sin edge, O/U y hándicap no rentables, CLV sin datos). v46
abre valor real: **llevar los edges VALIDADOS del fútbol — line shopping
(+8.6 % de precio) y confirmación sharp de Pinnacle — a TODOS los deportes**,
empezando por MLB (que juega ~15 partidos DIARIOS en verano).

---

## 0. La idea y el hallazgo

Line shopping y confirmación sharp son **market-agnósticos**: el mejor precio
entre casas y "el modelo supera la devig de Pinnacle" valen en cualquier
deporte. Hasta v45 solo el fútbol los usaba. v46 los hace **universales** con
un helper reutilizable y los aplica a MLB.

**Hallazgo durante el trabajo (que cambió el diseño):** al aplicar la
confirmación sharp a MLB sin filtrar, saltaba en **underdogs** — «Gana Colorado
Rockies EV +50 %, prob 46 %, gap +0.15». Eso NO es valor: es la **sobreconfianza
del modelo en no-favoritos** (la trampa de EV extremo). Un gap sharp positivo
solo significa valor si el modelo está calibrado; en underdogs no lo está.
**Guardarraíl añadido:** la confirmación sharp solo cuenta con **prob ≥ 0.52**
(y el motor MLB ya exige prob ≥ 0.58), de modo que solo se marcan favoritos con
valor real, nunca longshots sobrevalorados.

---

## 1. Helper reutilizable (odds_api)

- `extraer_precios(ev, mercado)`: de un evento de The Odds API devuelve, por
  selección, la **mejor cuota entre casas** (line shopping), la **casa** que la
  ofrece, y el precio de **Pinnacle** (referencia sharp). Un solo sitio, para
  cualquier deporte.
- `sharp_gap_2via(prob, pin_a, pin_b)`: gap del modelo sobre la devig de
  Pinnacle en mercados a **2 vías** (sin empate: MLB, tenis, NBA) —
  `devig = (1/pin_a) / (1/pin_a + 1/pin_b)`.

## 2. MLB con line shopping + confirmación sharp (cobertura diaria de verano)

`engines/mlb_engine.apuestas_dia` ahora:
- pide `regions=us,eu` (incluye Pinnacle + más casas),
- toma el **mejor precio** por selección y guarda la **casa**,
- calcula el **sharp gap** vs Pinnacle y marca `sharp_confirmado` (gap ≥ 3 pp
  **y prob ≥ 0.52** — guardarraíl anti-underdog),
- ordena los confirmados por sharp primero.

Así, cuando el modelo MLB encuentra un favorito con valor, el pick llega con el
mejor precio y el sello 💠, como el fútbol. El piso de prob 0.58 del motor MLB
**excluye los picks de underdog sobreconfiados** (hoy: 0 picks — el modelo no ve
favoritos de valor claro, y no se fuerza nada). MLB aporta cobertura diaria los
días que sí los encuentra.

**Honestidad sobre MLB:** el moneyline de béisbol es alta varianza y su mercado
es eficiente; el modelo MLB (≈55 %) NO está ROI-validado (no hay cuotas
históricas gratis para backtest). Por eso MLB NO se trata como edge validado:
se apoya en las señales **market-agnósticas** (line shopping + confirmación
sharp con guardarraíl) y se registra en `rendimiento_real` para validación
FORWARD. Nunca se fuerza un pick.

## 3. Generalización

El helper deja a **tenis y NBA** listos para el mismo tratamiento (2 vías con
Pinnacle) en cuanto sus torneos/temporada estén activos — la NBA en octubre
entrará con line shopping + confirmación sharp desde el primer día.

---

## 4. No regresión

- `test_simetria.py`, `test_match_parlay.py` → **TODO OK** (Internacionales 60.49 %).
- `smoke_v46.py` (AppTest, 11 vistas) → **0 excepciones**.
- Cambios contenidos en `odds_api` (helpers nuevos) y `mlb_engine` (uso de los
  helpers). El fútbol y su edge validado no se tocan.
- Coste: MLB pasa a `us,eu` (1 crédito más por llamada; MLB es 1 llamada/día).

## 5. Entregables

`odds_api.py` (`extraer_precios`, `sharp_gap_2via`) · `engines/mlb_engine.py`
(line shopping + confirmación sharp + guardarraíl) · `VALIDACION_v46.md`.

**Resultado:** los dos edges universales del proyecto — **line shopping y
confirmación sharp** — dejan de ser exclusivos del fútbol y se aplican a MLB (y
quedan listos para tenis/NBA). El trabajo reveló y corrigió un riesgo real: la
confirmación sharp en underdogs es espuria por la sobreconfianza del modelo, y
ahora un guardarraíl lo impide. Mejora universal y segura, con MLB honestamente
tratado como cobertura forward-validada, no como edge que no tenemos.
