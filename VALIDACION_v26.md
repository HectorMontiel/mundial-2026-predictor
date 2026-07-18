# VALIDACIÓN v26 — Arquitectura de tercera generación

**Fecha:** 2026-07-18 · **Regla de oro:** walk-forward obligatorio
(≥ +0.3 pp sin empeorar log-loss > 0.01, o mejora en ambos); fracasos
documentados igual que éxitos; el 1X2 del Mundial (60.49 %) no se toca.

---

## 1. The Odds API activada (§5.1) ✅

Clave gratuita añadida a `.streamlit/secrets.toml` (gitignored — verificado
con `git check-ignore`; **jamás se commitea**). Hallazgos empíricos:

- `markets=h2h,totals` por LIGA funciona (1 request = todos los próximos
  partidos); **`btts` en el endpoint de liga devuelve 422** — solo existe en
  el endpoint POR EVENTO. `odds_api.py` captura BTTS de los eventos que
  arrancan en <36 h con tope de 6 requests/día.
- Los nombres de la API difieren de football-data ("Inter Miami CF" vs
  "Inter Miami"): normalización fuzzy ≥0.75 contra team_stats para que los
  MATCH_ID crucen con fixtures.csv/odds_actuales.
- Primera captura real: **337 cuotas de 8 ligas** (496/500 créditos
  restantes) → `odds_historico.db` sembrada y `odds_actuales.json` con
  **100 partidos** (semifinal FRA-ENG + jornada Liga MX incluida) — fuera de
  temporada europea fixtures.csv llega vacío, así que la API es ahora la
  fuente viva de Liga MX/MLS: **MESM y blending operan en vivo desde hoy**.

## 2. Features ortogonales (§1.2-§1.4) — walk-forward por liga

Variantes: base (config adoptada) · `ent` (volatilidad xG/GC + entropía de
resultados, últimos 6) · `elo_d` (velocidad y aceleración del ELO) · `urg`
(urgencia asimétrica con tabla dinámica por temporada; en ligas sin descenso
la cola de la tabla actúa de proxy — documentado). Sanidad previa: sin NaN,
rangos [−1,1], invariancia al truncar el futuro (fuga = 0.0 exacto).

| Liga | base | ent | elo_d | urg | Adopción |
|---|---|---|---|---|---|
| Liga MX | 51.26 / 1.0235 | 50.66 | 50.92 | 50.23 | ❌ ninguna |
| MLS | 47.01 / 1.0391 | **47.66 / 1.0343** | 46.97 | 46.82 | ✅ **ent** (+0.65 pp) |
| Premier | 51.27 / 1.0121 | 49.91 | 51.34 / 1.0118 | 50.26 | ❌ (+0.07 pp = ruido, bajo el umbral v16 — mismo criterio que MLS/imt en v24) |
| LaLiga | 53.33 / 0.9908 | 53.31 | 53.43 | **54.30 / 0.9840** | ✅ **urg** (+0.97 pp) |
| Serie A | 53.81 / 1.0022 | 53.38 | **54.35 / 1.0074** | 53.81 | ✅ **elo_d** (+0.54 pp) |
| Bundesliga | 48.85 / 1.0226 | 49.61* | **49.25 / 1.0202** | 49.11 | ✅ **elo_d** (+0.40 pp, mejora ambos; *ent subía acc pero empeoraba ll) |
| Ligue 1 | 51.65 / 1.0873 | 51.37 | 50.68 | 51.23 | ❌ ninguna |
| Eredivisie | 51.74 / 1.0339 | 51.27 | **52.93 / 1.0299** | 52.01 | ✅ **elo_d** (+1.19 pp) |
| Primeira | 57.16 / 0.9655 | 55.97 | 56.81 | 56.21 | ❌ (urg mejora ll −0.033 pero acc −0.95 pp) |
| Champions | 57.99 / 0.9258 | 57.65 | 57.65 | **59.67 / 0.9341** | ✅ **urg** (+1.68 pp, ll +0.008 dentro de regla) |

**6 de 10 ligas adoptan una feature ortogonal.** Lecturas: las derivadas del
ELO brillan en ligas de ritmo alto (Serie A/Eredivisie/Bundesliga); la
urgencia manda donde la presión clasificatoria es máxima (LaLiga, Champions
— su mayor salto: +1.68 pp); la entropía solo aporta en la MLS (la liga más
volátil del proyecto). Nada se apiló sin validar: cada grupo se midió sobre
la config adoptada previa.

## 3. Producción reentrenada (split 80/20; MESM validado contra producción)

| Liga | Modelo | Mercado | MESM | Nota |
|---|---|---|---|---|
| Serie A (+elo_d) | 54.8 / 0.986 | 57.1 | **57.1 / 0.948 ADOPTADO** | 🏆 **EMPATA al mercado** (v23: 56.6) |
| Bundesliga (+elo_d) | **55.0 / 0.994** | 55.0 | descartado | 🏆 **empata al mercado a modelo puro** (v24: 53.3) |
| Eredivisie (+elo_d) | 51.3 / 1.113 | 53.4 | **53.0 / 0.980 ADOPTADO** | a 0.4 pp |
| LaLiga (+urg) | 52.8 / 1.068 | 55.0 | descartado (blending 70/30 sigue activo en vivo) | |
| MLS (+ent) | 46.6 / 1.040 | 50.1 | **49.2 / 1.037 ADOPTADO** | |
| Champions (+urg) | 53.8 / 1.000 | — | sin cuotas | forma congelada conocida |

(El split es UNA ventana; la evidencia de adopción es el walk-forward de §2.)

## 4. Supervivencia BTTS (§2) ✅ ADOPTADO como señal complementaria

- **lifelines RECHAZADO con evidencia**: 0.30.3 exige pandas<3 y su
  instalación degradó pandas 3.0.3→2.3.3 (el pin es crítico para los pickles
  del cloud — lección v14). Se desinstaló y restauró el entorno.
- Implementación propia: **Weibull AFT censurado en numpy/scipy puro**
  (`supervivencia_btts.py`): T = minuto del primer gol RECIBIDO (censura 90),
  covariables pre-partido (ataque rival, defensa propia, ΔELO, localía),
  MLE de la verosimilitud censurada. k≈1.32 (>1: el riesgo de gol crece con
  el minuto — coherente con el fútbol).
- Walk-forward (3,934 registros equipo-partido de internacionales con
  minuto real): **Brier 0.2358 vs 0.2516 del baseline Poisson con las mismas
  covariables — mejor en las 6/6 ventanas.**
- **Alcance honesto:** venció al baseline de covariables, NO al BTTS de la
  matriz Monte Carlo de producción (reconstruir sus λ históricas por ventana
  es un arnés pendiente → v27). Por eso se integra como **segunda opinión
  visible** en la vista del Mundial (⏱️ caption), sin tocar la plantilla.
  Artefacto en `modelos/supervivencia_btts.json`.

## 5. Shadow Booster (§1.1) — negativo en 7/9 ligas; ADOPTADO en MLS

XGBRegressor sobre `residuo = 1{gana local} − p_mercado` (cierre Pinnacle
preferido, de-vig proporcional), con features base + ortogonales v26 +
predicciones OOF del base (protocolo §3.2, `predicciones_oof.csv`: 7,364
predicciones leak-free) + severidad arbitral rolling (§1.5, solo Shadow).
Señal: apostar local si residuo_pred > 0.05, visitante si < −0.05. ROI
walk-forward vs apostar a ciegas el pick del base (mismas ventanas):

| Liga | ROI base | ROI shadow | n bets | Veredicto |
|---|---|---|---|---|
| Premier | +7.7 % | −7.0 % | 58 | ❌ |
| LaLiga | +5.1 % | +2.4 % | 284 | ❌ |
| Serie A | +3.9 % | **+22.8 %** | **62** | ❌ prometedor pero INSUFICIENTE: con 62 apuestas el ruido 1σ del ROI es ~±19 pp — reevaluar con más histórico (v27) |
| Bundesliga | +0.6 % | −11.0 % | 240 | ❌ |
| Ligue 1 | −9.3 % | −13.7 % | 280 | ❌ |
| Eredivisie | −11.1 % | −24.3 % | 221 | ❌ |
| Primeira | −5.8 % | −12.6 % | 693 | ❌ |
| Liga MX | −2.6 % | −15.5 % | 571 | ❌ |
| **MLS** | **−7.8 %** | **+2.6 %** | **747** | ✅ **ADOPTADO** (+10.4 pp con n grande ≈ 2σ; ROI absoluto positivo; la ablación sin severidad da +0.2 % — la severidad en MLS es casi constante por falta de árbitro en USA.csv, se documenta) |

**Lección honesta:** en 7 ligas el "error del mercado" no es explotable con
estas features — el mercado es eficiente y así se reporta. La MLS (mercado
más blando, spread de 10 pp con 747 apuestas) es la excepción adoptada.
Producción: `modelos/mls/shadow.joblib` (1,519 obs OOF) + señales ⚡ en
`shadow_senales.json` (12 señales vigentes) regeneradas por el pipeline y
consumidas por Apuestas del Día. El Shadow NO altera las probabilidades del
modelo base (spec §1.1.4).

## 6. Calibración por localía (§3.3) ✅ SIN SESGO

Sobre las 7,364 OOF: **ECE local global = 0.0138** (brecha media de 1.4 pp
entre prob predicha y frecuencia real) y ΔECE local−visitante = 0.0034 →
**no hay sobrestimación de la localía**; VENTAJA_LOCALIA se queda como está.
Nota metodológica: comparar el BRIER entre clases (local 0.219 vs visitante
0.189) confunde calibración con tasa base (la clase local ronda el 45 % y
su Brier máximo teórico es mayor) — el veredicto usa ECE por clase.
Curvas por liga en `calibracion_v26.json`; peor caso: empate de Serie A
(ECE 0.065), dentro de lo tolerable.

## 7. CLV Pinnacle (§3.1) ✅

`descargar_liga` conserva ahora `odd_*_pin` (PSC*, cierre Pinnacle, con
respaldo PS*) y `referee`; `entrenar_liga` reporta `roi_pct_pinnacle` junto
al ROI B365 en `roi_sim` cuando hay ≥30 apuestas con precio Pinnacle.

## 8. UI (§4) ✅

- **💎 Apuestas del Día** (`alpha_finder.py`): barrido de todas las ligas
  con cuotas vigentes (48 h); élite = prob >70 % ∧ EV >+3 % ∧ cuota >1.50;
  prioridad ⚡ si el Shadow está adoptado; degradación honesta (candidatos
  EV+ cuando no hay élite). Primer barrido real: 1 pick de élite
  (Liga MX: Chivas-Toluca, under 2.5).
- **📈 Montecarlo de bankroll** (`montecarlo_sim.py`): 1,000 trayectorias
  con win-rate y cuotas REALES de la liga elegida (roi_bets_*.json),
  percentiles 5/50/95, probabilidad de ruina y aviso educativo.

## 9. MLS geografía (§5.3) — descartada DEFINITIVAMENTE

Ya se validó en v25 (geo: acc −0.03 pp) y la spec v26 pedía cerrar el caso:
descartada definitivamente; el clima sigue solo en observación con caché.
