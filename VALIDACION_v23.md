# VALIDACIÓN v23 — Anulación táctica (MAT), meta-ensemble de mercado (MESM), clima y móvil (2026-07-15)

Regla de oro de siempre. El 1X2 del Mundial (60.49 % / 0.8688) no se tocó —
el MAT solo actúa en la capa de goles y el Monte Carlo preserva los
marginales del clasificador por construcción.

## M1 — Modelo de Anulación Táctica (MAT) ✅ formalizado y validado

**Reformulación honesta del fenómeno.** El prompt pedía predecir que una
estrella concreta acabe con 0 remates a puerta; ese dato por jugador-partido
no existe gratis a escala (FBref = miles de match reports tras Cloudflare;
API-Football lo cobra por fixture). El fenómeno observable y masivo es el
**apagón ofensivo del equipo** (ataque fuerte que termina en 0 goles), y la
estrella hereda el ajuste vía la probabilidad de gol del equipo.

**El modelo.** Para cada (equipo, rival, partido): y = 1{goles = 0};
clasificador XGBoost calibrado (isotónica) con features pre-partido sin fuga
(21,012 observaciones 2015-2026): ataque propio, presión/solidez del rival
(SOTC/GA/amarillas MA5), fatiga (días de descanso, partidos en 14 días),
contexto (torneo final vs amistoso/eliminatorias), clima (Open-Meteo) y el
baseline Poisson P(0)=exp(−λ) como feature — el MAT aprende el **residuo
táctico** que Poisson no ve. La señal nueva es el factor de supresión

    τ = log(P_MAT(0) / exp(−λ)),   λ' = (1−w)·λ + w·(−ln P_MAT(0))

y λ' se traslada a la λ del regresor por cociente (λ'/λ_heur), afectando
over/under, marcador, BTTS y goleadores estrella
(`prob_marcar' = 1−(1−prob)^{λ'/λ}`) — nunca al 1X2.

**Validación walk-forward (ventanas de 6 meses, 2024+):**

| Métrica de P(0 goles) | MAT | Poisson exp(−λ) |
|---|---|---|
| Brier medio | **0.1935** | 0.2119 |
| Log-loss medio | **0.5695** | 0.6135 |

El MAT bate al baseline de Poisson en TODAS las ventanas (−8.7 % de Brier).
NLL de los goles observados con λ'(w): 1.606 (w=0) → 1.501 (w=0.5) → 1.473
(w=1, saturado). **w de producción = 0.5 (capado, conservador)**: la NLL se
validó sobre la λ heurística y en el motor el cociente se aplica a la λ del
regresor (más fuerte); la ganancia 0.5→1.0 es ~2 % y no justifica
sobrecorregir. Validar sobre la λ del regresor queda para v24.

**Ablación del clima (honesta):** con la cobertura actual del backfill
(14.2 % de las 21,012 observaciones — la cuota horaria de Open-Meteo limitó
la primera pasada), añadir clima mejora el Brier solo 0.0003 (0.19319 vs
0.19347): **hoy el clima no aporta señal medible**; la potencia del MAT está
en presión del rival, fatiga, contexto y ELO. Las columnas de clima quedan en
el modelo (el pipeline completa la caché día a día y el reentrenamiento
mensual las aprovechará cuando la cobertura crezca); se reevalúa en v24.

**Simetría preservada:** el ajuste es idéntico bajo intercambio
local/visitante (verificado: los factores se espejan exactos) y el clima se
consulta UNA vez por partido — mismo estadio para ambos equipos —
(`test_simetria.py` en verde con el MAT activo).

**Integración:** `anulacion_tactica.py` + gancho en `prediction_api.predecir`
(solo si existe el artefacto validado `modelos/mat_mundial.joblib`);
`apagon_tactico` en la respuesta, insight "⚡ Alerta de anulación táctica"
cuando P(0) ≥ 45 %, y ajuste visible en los goleadores clave.

## M2 — Meta-Ensemble de Superación de Mercado (MESM)

**Formalización.** Stacking logístico multinomial sobre
z = [ln p_base, ln p_mercado, overround] con la pérdida asimétrica de la
spec implementada como pesos de muestra exactos (×2 si el mercado acierta y
el modelo falla; ×0.5 al revés). Protocolo sin fuga: base con el mismo
config de la liga entrenado en el primer 75 % del train, meta ajustado con
el 25 % final, aplicado en validación a las probs del modelo de PRODUCCIÓN.

**Experimento exploratorio** (`run_mesm_v23.py`, base genérico): mejoró las
8 ligas y el ROI simulado pasó de negativo-en-todas a positivo en 5 — pero
ese base era débil. La decisión se tomó con la validación de PRODUCCIÓN:

| Liga | Producción | MESM | Veredicto |
|---|---|---|---|
| **Liga MX** | 52.4 % / 0.998 | **54.9 % / 0.976** | ✅ ADOPTADO — **bate al mercado (53.5 %) por primera vez** |
| Serie A | 54.8 % / 0.981 | **56.6 % / 0.949** | ✅ ADOPTADO |
| Eredivisie | 52.0 % / 1.113 | **53.7 % / 0.981** | ✅ ADOPTADO |
| Primeira | 53.7 % / 0.971 | **56.1 % / 0.936** | ✅ ADOPTADO |
| Premier | 47.3 % / 1.058 | 44.5 % / 1.105 | ❌ descartado |
| LaLiga | 51.5 % / 0.989 | 50.4 % / 0.975 | ❌ (precisión cae) |
| Bundesliga | 56.3 % / 0.993 | 52.3 % / 0.973 | ❌ (precisión cae 4 pp) |
| Ligue 1 | 51.7 % / 1.019 | 50.2 % / 1.032 | ❌ descartado |

En inferencia el meta SOLO se aplica cuando hay cuotas reales vigentes del
partido (odds_actuales.json); sin cuotas, probs del modelo base — degradación
limpia, marcada en la UI ("🧠 MESM") y en el panel de rendimiento.

**Ablación científica (pedida por el usuario):** ¿aporta la asimetría o
basta el stacking? Con el mismo protocolo, pesos simétricos dan de media
53.1 %/0.978 vs asimétricos 53.7 %/0.983 (8 ligas, base genérico). Lectura
honesta: **el grueso de la ganancia es el stacking modelo+mercado**; la
asimetría añade ~+0.5 pp de precisión con ~+0.005 de log-loss — dentro del
ruido entre sí. Se mantiene la asimétrica (mejor precisión y es la validada
contra producción), documentando que no es la salsa mágica: la receta es
aprender del mercado sin rendirse a él.

## M3 — Clima (Open-Meteo) ✅ infraestructura

`clima.py`: geocoding + archivo ERA5 diarios, gratuito y sin clave, con caché
persistente (`clima_cache.json`) y descarga por LOTES de 15 ciudades por
request. Se aprendió a golpes: la cuota HORARIA de Open-Meteo existe y el
primer intento la agotó con el geocoding masivo (error ahora detectado
explícitamente, no silenciado). Pronóstico a 16 días para partidos futuros
(`obtener_clima_futuro`). Enganchado al pipeline diario (incremental).

## M4 — Interfaz móvil ✅

El selector de competición vive ahora ARRIBA del área principal
(st.selectbox) — en el teléfono la barra lateral llega colapsada y las ligas
eran indescubribles. Los controles finos siguen en la barra lateral. Las
columnas de Streamlit ya se apilan solas en pantallas estrechas.

## No implementado (documentado)

- **MLS vía Playwright**: pospuesto — sin demanda del usuario y FBref sigue
  tras Cloudflare desde esta red (v22); la vía navegador usada para la
  Champions es manual y la MLS no la justifica aún.
- **Cuotas de remates de la estrella / PSxG del portero**: no existen gratis
  (documentado en §1.2 del prompt como sustituibles; el volumen de Polymarket
  ya alimenta `risk_flags`, no features).

## No-regresión

- Mundial 1X2: intacto (el MAT no toca los marginales por construcción).
- Premier/LaLiga/Bundesliga/Ligue 1: sin MESM (descartado) → modelos idénticos.
- Tests en verde: `test_match_parlay.py`, `test_simetria.py`, AppTest en
  Mundial y Liga MX (0 excepciones), inferencia MESM verificada con y sin
  cuotas vigentes.
