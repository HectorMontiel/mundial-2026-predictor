# VALIDACIÓN v20 — Alineaciones automatizadas, panel de ROI y simulador de banca (2026-07-13)

Regla de oro de siempre; fuentes gratuitas/legales/reproducibles; Mundial
intacto (60.4 % / 0.871).

---

## M1 — Alineaciones automatizadas + base de jugadores ✅ (infraestructura)

- Sondeo ESPN: el summary NO publica minutos jugados, pero sí
  `starter/subbedIn/subbedOut` → minutos estimables (90 titular completo,
  70 titular sustituido, 25 suplente que entra). `lineup_collector` ahora
  captura esos flags. Fuentes alternativas del plan (LiveScore, SofaScore,
  WhoScored): innecesarias mientras ESPN cubra las 8 ligas + Mundial, y las
  tres están bloqueadas/JS desde esta red (verificado en v13/v14) — ESPN
  queda como fuente única con degradación limpia.
- `player_db.py`: `jugadores_xg.csv` con minutos estimados acumulados ×
  goles reales de Kaggle → `xg90_estimado` con **suavizado bayesiano**
  (prior 0.12 xG/90 con peso de 450 min; bajo 180 min se usa el prior) para
  evitar xg90 absurdos con muestras chicas. Se reconstruye a diario en
  `pipeline_total` tras recolectar alineaciones. Verificado: 136 jugadores
  desde los 4 partidos del Mundial ya recolectados.
- Ajuste por alineación (`factores_para_partido`): factor = media de xg90 de
  los titulares confirmados HOY / media de la plantilla. Se muestra como
  **banner informativo** en la Vista Rápida con el xG ajustado — **no altera
  el 1X2** (regla del proyecto: nada entra al modelo sin backtest). La
  medición en vivo (base vs ajustada en los mismos partidos) empieza con la
  temporada 2026-27; evaluación en diciembre 2026 → VALIDACION_v21.

## M2 — Liga MX: asalto al mercado (walk-forward)

Baseline v19: 51.7 % / 1.011 (mercado 53.5 %).

| Candidato | Acc WF | Log-loss WF | Veredicto |
|---|---|---|---|
| Modelo v19 (referencia) | 51.7 % | 1.011 | se mantiene |
| Modelos separados regular/liguilla | 51.5 % | 1.009 | ✗ −0.2 pp (la liguilla aporta ~300 partidos de train — insuficiente para un modelo propio) |
| Gate por overround < 0.05 | — | — | ✗ inaplicable: el margen del cierre medio (AvgC) supera 0.05 en la práctica totalidad de partidos MX, el gate vacía la feature |

**El mercado (53.5 %) sigue sin batirse en MX** — brecha honesta de ~1.8 pp.
Las vías restantes (posesión real, alineaciones) dependen de datos que hoy
no existen gratis; las alineaciones de ESPN empiezan a acumularse ahora y
son la apuesta de v21.

Posesión/tiros de Flashscore: descartado de nuevo — el HTML es JS
(verificado v14/v18); el supuesto del plan no se cumple desde esta red.

## M3 — Panel de rendimiento por liga ✅

`entrenar_liga` ahora simula apuestas sobre su validación con cuotas de
cierre reales (1 u al pick del modelo si confianza > 70 % o EV > 0),
persiste el resumen en `metadata.roi_sim` y las apuestas individuales en
`roi_bets_{liga}.json`. La UI muestra la tabla (modelo vs mercado, nº de
apuestas, aciertos, ROI) en el expander "📈 Rendimiento del modelo por liga"
disponible en todas las competiciones.

Resultado honesto de la simulación (las 8 ligas reconstruidas, métricas de
validación idénticas — el diff de metadata solo añade `roi_sim`): únicamente
la **Bundesliga da ROI positivo (+3.1 % en 151 apuestas)** — coherente con
que es la liga donde el modelo bate al mercado (56.3 vs 55.0). El resto
queda entre −1.6 % y −8.2 %: contra cuotas de cierre el mercado sigue
siendo difícil de batir, y el panel lo muestra sin maquillaje.

## M4 — Simulador de bankroll ✅

En el mismo expander: bankroll inicial configurable, simulación cronológica
con **¼ Kelly (tope 5 %)** sobre las apuestas persistidas y gráfico Plotly
de evolución + bankroll final con delta. Aviso de juego responsable.

## M5 — BTTS 📋 POSPUESTO (otra vez, con evidencia nueva)

Sondeo de hoy: la página diaria de Betexplorer publica exactamente 3 cuotas
por partido (1X2) — sin BTTS. SofaScore/WhoScored bloqueados desde esta red
(v13) y Oddsportal es JS (v14). Sin fuente gratuita legal → v21.

## M6 — Champions League 📋 SIGUE EN BETA

API-Football capa gratuita requiere registrarse y configurar
`RAPIDAPI_KEY` (decisión del usuario, no automatizable); FBref sigue 403; el
European Soccer Database de Kaggle llega solo hasta 2016. Si el usuario
configura la clave, `league_engine` ya tiene el hueco (`formato: 'api'`).

## M7 — Simetría local/visitante en el Mundial ✅ ADOPTADO

**Diagnóstico cuantificado** (`run_simetria_v20.py`, resultados en
`resultados_simetria_v20.json`): al intercambiar local y visitante, la
predicción del modelo difería en promedio **18.0 pp** (p90 24.8 pp, máximo
46.9 pp) — el "efecto látigo" que reportó el usuario con México vs Ecuador.
Las 15 features son antisimétricas o constantes de la sede; la asimetría
viene del propio ensemble (aprendió la localía de partidos históricos con
local real) y del punto cruzado de la nube topológica.

**Corrección** (`prediction_api.predecir`): inferencia simétrica con localía
consciente del anfitrión.
- Sede neutral: promedio de la vista (A,B) y la espejada (B,A) →
  `P(gana A | A vs B) = P(gana A | B vs A)` exacto, también en las λ de goles.
- Anfitrión (MEX/USA/CAN en estadio de su país): la vista se calcula SIEMPRE
  con el anfitrión como local y se espeja si hace falta → México conserva su
  ventaja en el Azteca lo listes como local o visitante.
- El resultado expone `localia.metodo` y un insight lo explica sin jerga.

**Validación (regla de oro: mantener o mejorar 60.4 % / 0.871)** — sobre los
2,640 partidos de validación oficiales (971 con `neutral=True`), aplicando la
simetrización solo a los neutrales:

| Métrica | Antes | Después |
|---|---|---|
| Precisión global | 60.38 % | **60.49 %** |
| Log-loss global | 0.8712 | **0.8688** |
| Precisión (solo neutrales) | 56.75 % | **57.05 %** |
| Log-loss (solo neutrales) | 0.9263 | **0.9198** |
| MAE goles (suma L+V) | 1.912 | **1.900** |

Mejora en ambas métricas → adoptado. Sin reentrenar: es una regla de
inferencia; los pickles no cambian. `test_simetria.py` queda como test
permanente (spec 8.4): simetría exacta en 7 cruces neutrales + 3 con anfitrión.

## M8 — SmartParlayBuilder: perfiles con zonas y diversidad ✅

Los tres defectos reportados y su causa raíz:
1. **Conservador ≡ medio**: con cuotas justas (cuota = 1/prob) todo score
   `prob·cuota^α` es monótono en la probabilidad → ambos greedy elegían lo
   mismo. Fix: **zonas disjuntas de probabilidad conjunta** por perfil.
2. **Agresivo imposible (~0.2-18 %)**: maximizaba cuota sin piso conjunto.
   Fix: piso del 5 % conjunto + 30 % individual.
3. **Monotonía (siempre córners/remates)**: sin tope por categoría. Fix:
   máx. 1 mercado de córners y 1 de tarjetas + diversidad mínima
   `min(3, N-1)` categorías.

Nuevo algoritmo en `match_parlay.py`: búsqueda combinatoria por haz
(prácticamente exhaustiva: ~10-20k estados tras podas) con lookahead de
factibilidad del piso ajustado a grupos/topes, enumeración ascendente de
probabilidad para el perfil agresivo (arranca por cuotas altas y se rescata
con picks seguros) y trayectoria hacia el centro de zona para el medio.
Degradación honesta en 3 niveles (zona+diversidad → zona → la combinación
más segura posible), siempre con aviso.

| Perfil | Garantía | MEX-ECU n=6 (antes → ahora) |
|---|---|---|
| 🛡️ Conservador | conjunto ≥ 60 % (reduce picks si no llega) | mismos picks que medio → 80.5 % con 3 picks |
| ⚖️ Medio | zona 15-60 %, max prob·cuota^0.3 | idéntico al conservador → 18.1 % / cuota 5.2 |
| 🚀 Agresivo | conjunto ≥ 5 %, individual ≥ 30 %, max cuota | 18 % con cuota 4.5 → **5.0 % con cuota 18.3** |

La UI muestra la categoría de cada pick, la composición del parlay y el
ancla de cada categoría. `test_match_parlay.py` ampliado: pisos/zonas por
perfil, diversidad, topes de familia y firmas distintas entre los TRES
perfiles (Mundial y Premier) — TODO OK. Rendimiento: ≤2.4 s el caso más
pesado (agresivo n=8, incluida la plantilla).

## No-regresión

- Modelos del Mundial sin reentrenar (M7 es regla de inferencia; mejora
  ambas métricas de validación). Todas las ligas reconstruidas para poblar
  `roi_sim`/`roi_bets` (mismas configs adoptadas; métricas equivalentes).
- Tests en verde tras todos los cambios: `test_match_parlay.py` (Mundial +
  Premier), `test_simetria.py` (nuevo) y AppTest del dashboard (0 excepciones).
