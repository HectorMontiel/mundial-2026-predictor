# 🧪 Plan de Pruebas y Backtesting — Motor Predictivo TDA Mundial 2026

## 1. Objetivo

Garantizar que el sistema cumple las **reglas de oro**:

| Regla | Criterio | Cómo se verifica |
|---|---|---|
| Precisión > todo | ≥ 55 % de acierto en backtesting temporal para desplegar | `train_tda_model.py` marca `deploy_ready` en `modelos/metadata.json` |
| Señal del generador de respaldo | ≥ 45–50 % de precisión con datos sintéticos correlacionados | Mismo backtesting sobre histórico sintético |
| Transparencia | Aviso "Datos estimados – precisión limitada" si la fuente es sintética | `fuente_datos.json` + banner en `dashboard_ui.py` |
| Simplicidad radical | Ningún insight usa jerga técnica sin traducir | Revisión manual de la sección "Lo que dicen los números" |

## 2. Backtesting temporal (prueba principal)

**Protocolo:** entrenar solo con partidos ANTERIORES a la fecha de corte y
validar con los posteriores. Nunca se mezclan (sin fuga temporal): el
`MinMaxScaler` se ajusta solo con el tramo de entrenamiento y las medias
móviles/ELO de cada partido usan exclusivamente información previa al pitazo.

```bash
# Corte automático (percentil 80 cronológico)
python train_tda_model.py

# Corte explícito según especificación (entrenar < 2024, validar 2024-2025)
python train_tda_model.py --corte 2024-01-01
```

**Métricas reportadas:** precisión, log-loss y línea base ingenua
("siempre gana el favorito por ELO"). El modelo debe igualar o superar la
línea base; si no lo hace, las features no aportan y NO se despliega.

**Resultado de la última ejecución (ensemble v4, DATOS REALES, `--corte 2024-01-01`):**

| Métrica | Valor |
|---|---|
| Partidos de entrenamiento (reales, 2010→2023) | 12,608 (+904 sintéticos correlacionados, solo train) |
| Partidos de validación (reales, 2024→2026) | 2,616 |
| Precisión de validación | **59.4 %** ✅ (umbral 55 %) |
| Línea base "siempre el favorito" | 58.9 % |
| Log-loss | 0.892 |
| Precisión en picks con confianza > 70 % | 80.4 % (682 partidos) |
| MAE goles esperados (regresores Poisson) | local 1.061 · visitante 0.866 |
| Objetivo estricto (≥ 62 % / ≤ 0.85) | ❌ registrado en metadata como no cumplido |

Verificación adicional en `backtesting.ipynb`: curvas de calibración por clase
(guardadas en `modelos/curvas_calibracion.png`), matriz de confusión, precisión
por trimestre y precisión por nivel de confianza (debe crecer monotónicamente).

### Pruebas v11 (Cabo Verde, árbitros, cuotas, frescura)

1. **CPV** en las 49 selecciones: ELO real (1626), 5 partidos en ventana MA5,
   goleadores reales en `jugadores_clave.csv`, predicción CPV vs ITA y
   plantilla completa (91 campos) sin errores.
2. `referee_scraper.py` genera `referees.json` (respaldo pregrabado cuando
   WorldReferee no responde); `arbitros.py` lo carga al importar.
3. `fetch_odds.py` sin `ODDS_API_KEY`: termina limpio, `cargar_features_cuotas`
   devuelve NaN, el entrenamiento registra `odds_features.activas=false` y el
   modelo queda idéntico. Con cobertura ≥5 % las 4 features (probabilidades
   implícitas + overround) entran al clasificador y la inferencia en vivo
   imputa las medias de entrenamiento.
4. UI: botón "Actualizar datos ahora" (ejecuta el pipeline y recarga cachés),
   aviso de frescura si el estado tiene >24 h, fases detalladas de
   eliminatoria, CPV seleccionable.
5. **Backtesting v11**: split 2024+ → 59.5 % / 0.886; walk-forward (5
   ventanas) → media 59.8 % / 0.893. Objetivo ≥61 %/≤0.88: NO alcanzado sin
   cuotas reales; documentado como condicional a poblar `odds_historicas.csv`.

### Pruebas de estadios y aclimatación (`altitud.py`, v10)

1. 16 estadios oficiales con altitud real; sin sede especificada → MetLife (2 m).
2. Reglas verificadas al decimal: Azteca (2240 m) → local aclimatado ×1.05 y
   visitante no habituado ×0.88; local no habituado ×0.90; >2500 m → ×0.85/×0.82;
   ambos aclimatados (MEX/ECU/COL) → sin penalización.
3. 2ª mitad: el no aclimatado en altura baja un escalón (−7 pp); córners +0.2.
4. El estadio mueve el λ base solo vía la feature ENTRENADA (ALTURA_NORM) y la
   capa explícita de aclimatación; el 1X2 calibrado no recibe multiplicadores
   post-hoc.
5. Endpoints `&estadio=` y `GET /estadios` en 200; plantilla y Markdown con
   "**Estadio:** Estadio Azteca (2240 msnm)".

### Backtesting walk-forward (v10)

`python train_tda_model.py --corte 2024-01-01 --walkforward`: 5 ventanas de
6 meses (2024-01 → 2026-07), entrenamiento expansivo, escalador reajustado por
ventana. Resultado: **precisión media 59.4 % · log-loss medio 0.894**
(ventanas: 59.2/57.4/60.4/62.5/57.6 %). Guardado en `modelos/metadata.json`.

### Mejoras evaluadas y descartadas (registro de evidencia, mismo split)

| Variante | Precisión | Log-loss | Veredicto |
|---|---|---|---|
| Baseline (aug 904, Optuna) | 59.3 % | 0.8974 | ✅ producción |
| Sin aumento sintético | 59.3 % | 0.8993 | — |
| Aumento 3000 | 59.4 % | 0.9001 | ❌ log-loss peor |
| + Wasserstein H0 local-visit | 59.3 % | 0.8992 | ❌ sin ganancia |
| + Aclimatación como feature 1X2 | 59.1 % | 0.8994 | ❌ (79 partidos de altura) |
| Stacking binario de empate | 58.5 % | 1.2203 | ❌ degrada calibración |

### Pruebas del módulo de arbitraje (`arbitros.py`, v6)

1. **51 árbitros oficiales** cargados (10 CONMEBOL, 21 UEFA, 9 CONCACAF,
   6 CAF, 5 AFC) con perfil completo (am/90, roj/90, pen/90, criterio,
   sesgo local, edad).
2. Modelo v2 de interacción árbitro-equipo verificado:
   - Mismo árbitro: el equipo indisciplinado (MA5 3.0) recibe más amarillas
     que el disciplinado (MA5 1.0).
   - Estilo bloque alto: exactamente +8 % de amarillas.
   - Fase: eliminatoria (+15 %) > grupos (+5 %).
   - Sesgo local 55 % (Tello): local ×0.90, visitante ×1.10 exactos.
   - Un árbitro muy estricto (Valenzuela) produce más tarjetas que el promedio
     y éste más que uno permisivo (Oliver).
3. Ajuste de reacción: en eliminatoria, un equipo de reacción "Fuerte" sube su
   λ (Δλ = λ×0.10×15/90×λ_rival) más que en grupos (coef 0.05); la reacción
   "Débil" sube el λ del RIVAL. Magnitudes acotadas (~1-3 % del xG total).
4. Los penaltis esperados escalan con el PEN_P90 del árbitro y se reparten por
   volumen ofensivo.
5. **El 1X2 calibrado no cambia con el árbitro NI con la fase** (solo tarjetas,
   penaltis, goles esperados del Monte Carlo, timeline e insights).
6. Métricas de carácter con minutos reales: reacción tras gol, % de goles en
   2ª mitad y encajados en últimos 15' presentes en `team_stats.json` y en las
   observaciones de la plantilla.
7. Regla de features: las variables de minutos se probaron en el clasificador
   y empeoraron el log-loss (0.892→0.899) → excluidas del 1X2, documentado en
   `feature_engineering.py`.

### Pruebas de la plantilla de análisis (motor `plantilla()`)

1. Genera 9 secciones y ~85 campos para cualquier par de las 48 selecciones.
2. Coherencia interna verificada: 1X2 suma 100 %; over+under = 100 %;
   BTTS sí+no = 100 %; doble oportunidad = suma de sus componentes;
   hándicaps monótonos (P(-0.5) ≥ P(-1.5) ≥ P(-2.5) ≥ P(-3.5));
   multigoleadores 2+ ≥ 3+.
3. Goleadores con nombres reales y probabilidades ajustadas al rival del día.
4. Export a Markdown (con valores del modelo o del usuario) y endpoint
   `GET /plantilla?home=X&away=Y` en 200.
5. UI: 81 campos editables, botón "Validar mis estimaciones" muestra
   diferencias, cuota justa del modelo (1/p) y mensajes de valor.

> Los datos provienen de la arquitectura híbrida (Kaggle + StatsBomb +
> API-Football opcional). Si el pipeline degrada al generador sintético de
> respaldo, `fuente_datos.json` lo registra y la UI muestra el aviso
> "Datos estimados – precisión limitada".

## 3. Pruebas funcionales del motor (`prediction_api.py`)

Ejecutadas en cada entrega (script de humo):

1. **Carga**: el motor inicializa con los artefactos de `modelos/` y reporta fuente de datos.
2. **Contrato JSON**: la salida de `predecir(home, away)` es 100 % serializable
   y contiene `winner`, `confidence`, `probabilities` (suman 1.0 ± 0.01),
   `most_likely_score`, `score_probability`, `total_goals_expected`, `insights`,
   `key_players`, `decisive_factor`, `timeline` (90 minutos) y `score_matrix`.
3. **Coherencia probabilística**: las marginales 1X2 de la matriz Monte Carlo
   de marcadores coinciden con las probabilidades calibradas (± 0.02).
4. **Coherencia física**: los goles esperados acumulados del minuto 90 igualan
   `total_goals_expected` (± 0.05).
5. **Sensibilidad**: invertir localía cambia las probabilidades; un cruce
   élite vs débil (ARG vs HON) da favorito claro (> 55 %).
6. **Manejo de errores**: equipo desconocido, local == visitante y motor sin
   artefactos devuelven mensajes claros (nunca traceback).
7. **Intérprete de texto libre**: las 5 intenciones (ganador, goles esperados,
   rematadores, expulsiones, análisis completo) se resuelven con y sin
   equipos por defecto.
8. **Endpoint HTTP**: `GET /predict?home=MEX&away=ECU` responde 200 con el
   mismo contrato; `GET /health` expone las métricas del modelo.

## 4. Pruebas de UI (`dashboard_ui.py`, vía `streamlit.testing.v1.AppTest`)

1. Render completo sin excepciones ni `st.error`.
2. Las 4 salidas de una sola línea presentes (🏆 ⚽ 📊 🔥).
3. Banner de transparencia visible cuando `fuente_datos.json` = synthetic.
4. Selección de partido del fixture re-ejecuta la predicción sin errores.
5. Consultas de texto libre renderizan respuesta (rematadores, goles esperados).

## 5. Pruebas del pipeline de datos

1. `python pipeline_mundial.py` en un directorio limpio genera los 6 CSVs +
   `fuente_datos.json` sin intervención manual.
2. Segunda ejecución el mismo día: incremental, no duplica partidos
   (dedupe por `MATCH_ID`).
3. Con `--real`, si FBref falla (red caída, Cloudflare), el pipeline degrada
   al generador correlacionado y registra `source: synthetic`.
4. Las medias móviles ponderadas usan los últimos 5 partidos con peso doble
   al más reciente, en orden cronológico.

## 6. Ejecución diaria programada (Windows)

```powershell
schtasks /create /tn "PipelineMundial2026" `
  /tr "C:\Users\HMREY\proyecto_mundial_2026\.venv\Scripts\python.exe C:\Users\HMREY\proyecto_mundial_2026\pipeline_mundial.py --real --train" `
  /sc daily /st 06:00
```

## 7. Pruebas de la capa de datos híbrida

1. `python data_fetcher.py` en limpio descarga Kaggle (caché kagglehub),
   recalcula ELO sobre los ≥ 15,000 partidos reales y registra
   `fuente_datos.json → "source": "real_hybrid"`.
2. La calibración StatsBomb produce `calibracion_statsbomb.json` con
   `fuente: statsbomb_wc2022`; sin red, cae a `priors_literatura` sin romper.
3. Con `RAPIDAPI_KEY` definida, API-Football inyecta los últimos 5 partidos
   por selección y sus estadísticas reales pisan a las estimadas
   (mismo `MATCH_ID`, `keep='last'`).
4. `update_team_stats.py` genera `team_stats.json` con las 48 selecciones y
   `jugadores_clave.csv` con goleadores REALES (verificar nombres conocidos:
   Messi, Haaland, Mbappé).
5. Criterio de despliegue: `python train_tda_model.py --corte 2024-01-01`
   con `precision_validacion ≥ 0.55` sobre validación exclusivamente real.
