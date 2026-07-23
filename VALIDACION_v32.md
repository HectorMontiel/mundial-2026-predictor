# VALIDACIÓN v32 — Blindaje cuantitativo, interés compuesto y plantillas realistas

**Fecha:** 2026-07-23 · Regla de oro respetada; fútbol (Mundial 60.49 % +
10 ligas) y motores MLB/NBA/Tenis intactos.

## 1. Filtro anti-trampas de EV extremo (§3) ✅ JUSTIFICADO CON DATOS

Backtest sobre las **1,495 apuestas simuladas reales** de la validación de
todas las ligas (`roi_bets_*.json`: probabilidad prometida, cuota de cierre
y resultado):

| Tramo de EV | n | Acierto real | El modelo prometía | **Gap de calibración** | ROI |
|---|---|---|---|---|---|
| 0 % a +3 % | 228 | 52.6 % | 54.3 % | −0.017 | −2.1 % |
| **+3 % a +15 %** | 685 | 49.9 % | 53.7 % | **−0.038** | **+0.5 %** |
| **> +15 % (extremo)** | 582 | **35.2 %** | 50.6 % | **−0.154** | **−11.9 %** |

**La hipótesis del spec se confirma de forma contundente**: los picks con
EV > +15 % aciertan **15 puntos por debajo** de lo que el modelo promete
(vs 3.8 pp en el tramo moderado) y su ROI es **12.4 pp peor**. No es valor:
es el modelo ignorando información que el mercado sí tiene. Se **segregan**
a una sección propia oculta por defecto, con el aviso correspondiente — no
se borran (transparencia).

## 2. Reto Escalera (§2) ✅

`reto_escalera.py`: selecciona picks con **prob ≥ 85 % y cuota ≥ 1.05**
(suelo del §1.1), **un solo pick por partido** (protección de correlación) y
aplica el haircut empírico SGP si comparten familia de mercado. Monte Carlo
de 10.000 escaleras con reinversión diaria y stake configurable:
probabilidad de completar el día, racha media, **ruina a 10/20/30 días** y
capital mediano/p90.

**Comportamiento verificado hoy**: no hay ningún pick que supere el 85 %, y
el módulo **se niega a arrancar la escalera** con el mensaje «mejor no
forzarla» en vez de rebajar el listón. Es exactamente lo que debe hacer.

## 3. Fiabilidad histórica por mercado (§5) ✅

`fiabilidad_liga()` calcula el **Brier score REAL de los picks que el
sistema publicó** en cada liga (prob prometida vs resultado, desde
roi_bets), con la traducción UX del §5.2 (🟢 <0.15 · 🟡 <0.22 · 🔴 ≥0.22) en
cada tarjeta. Las ligas sin histórico muestran «⚪ Sin histórico» en lugar
de inventar una etiqueta.

**Pick del Día único** (§5.3) con los cuatro filtros y el desempate exacto
del §1.2 (Brier ↑ → EV ↓ → prob ↓). Verificado: **hoy devuelve “no hay Pick
del Día”** porque ningún candidato reúne confianza >80 % con EV en rango —
y la UI lo dice explícitamente («forzarlo sería el error clásico»).

## 4. Cuarentena por estado obsoleto (§4) ✅ (con etiquetado corregido)

Regla dirigida por datos: si el modelo de una liga no ve partidos nuevos
desde hace más de 45 días, sus picks **bajan a Capa 2** con aviso.

**Corrección de precisión detectada en pruebas**: la primera versión
etiquetaba esto como «pretemporada», pero al probarlo marcó partidos de la
MLS —que está en plena temporada— porque su histórico estaba 58 días sin
refrescar. El mensaje ahora dice la verdad literal: «el modelo de esta liga
no ve partidos desde hace N días (pretemporada o estado sin refrescar)».
La degradación es correcta; la etiqueta ahora también.

El **decaimiento inter-temporada** que el §4 propone como alternativa ya se
probó y descartó en v31 (peor incluso al inicio de temporada).

## 5. Rendimiento real con persistencia (§1.3/§6) ✅

`rendimiento_real.py` sobre **SQLite en modo WAL** (`rendimiento_real.db`):
registra cada pick publicado (idempotente por fecha+partido+apuesta),
permite liquidarlo con el resultado y calcula acierto y ROI real a 7 y 30
días + serie diaria para el gráfico. Ya está registrando (8 picks
pendientes de liquidar en la primera corrida).

**Límite honesto documentado**: el disco de Streamlit Cloud es efímero entre
despliegues, así que WAL protege frente a reinicios del contenedor pero no
frente a un redeploy. Por eso la BD está en `.gitignore` y el panel muestra
«sin historial» sin fingir datos.

## 6. Plantillas ampliadas con restricción matemática estricta (§8) ✅

Solo mercados **derivables con rigor**; los demás se declaran excluidos en
la propia plantilla (`excluidos`).

- **NBA y MLB** (`base_engine.plantilla`): moneyline, **totales O/U en 3
  líneas**, **spread** y **totales por equipo**, derivados del margen
  ~ N(μ, σ) donde μ se deduce de la probabilidad calibrada
  (μ = σ·Φ⁻¹(p)) y **σ se calibra con el histórico real**: NBA **15.58**,
  MLB **4.48** (`calibrar_margenes_v32.py`, sin reentrenar modelos).
  *Excluidos*: cuartos NBA y primeras 5 entradas MLB (exigen play-by-play).
- **Tenis** (`tennis_engine.plantilla`, 19 mercados): ganador, **total de
  juegos** (regresión sobre 68,207 partidos: `juegos = 23.92 − 0.67·gap +
  13.12·bo5`, σ=6.60), **hándicap de juegos** (σ margen = 2.64) y **reparto
  de sets** invirtiendo numéricamente P(partido) → P(set) bajo independencia
  entre sets (asunción **declarada** en la propia plantilla).
  *Excluidos*: marcador exacto de sets, «set a cero» y ganador del primer
  set — exigen cadenas de Markov o datos de saque que no tenemos.

## 7. Copiado al portapapeles (§7) ✅

Bloque `st.code` desplegable con el texto completo del día (botón de copia
nativo de Streamlit, sin dependencias ni hacks de JavaScript), junto a las
descargas TXT/CSV ya existentes.

## 8. No regresión ✅

test_simetria ✓ · test_match_parlay ✓ · smoke 10 ligas de fútbol ✓ · smoke
MLB/NBA/Tenis con plantillas nuevas ✓ · AppTest en ambos modos × 5 vistas ✓
· Mundial intacto.
