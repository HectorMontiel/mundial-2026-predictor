# VALIDACIÓN v17 — Precisión de las ligas de clubes (2026-07-12)

Ciclo completo de experimentación sobre las 8 ligas activas con fuentes
gratuitas. Motor: `run_league_experiments.py` (screening con el mismo split
80/20 de league_engine) + walk-forward de confirmación (ventanas de 6 meses,
train expansivo, sobre el último 40 % de cada liga). Regla de oro: adoptar
solo con **≥ +0.3 pp de precisión sin empeorar log-loss > 0.01**, o mejora en
ambas métricas con mejor calibración (regla 2).

---

## 1. Experimentos ejecutados (Fase 1 + modelado con datos existentes)

Por liga: H2H rico (GD últimos 3 cruces), días de descanso, rachas,
clasificación viva (posición + puntos por partido), **cuotas de cierre B365
como features** (probabilidades implícitas + overround; disponibles en el
CSV de football-data para las 7 ligas europeas), combinaciones, forma
exponencial e histórico ampliado a ~10 temporadas.

## 2. Walk-forward de confirmación (la prueba que decide)

| Liga | Baseline WF | Mejor candidato | Δacc | Δll | Decisión |
|---|---|---|---|---|---|
| LaLiga | 51.5 % / 1.048 | **cuotas** 53.0 % / 0.993 | +1.5 | −0.055 | ✅ ADOPTADO |
| Premier | 47.9 % / 1.042 | **extras + cuotas** 49.1 % / 1.031 | +1.2 | −0.011 | ✅ ADOPTADO |
| Bundesliga | 49.8 % / 1.024 | **extras** 50.3 % / 1.027 | +0.5 | +0.003 | ✅ ADOPTADO |
| Eredivisie | 50.3 % / 1.080 | **cuotas** 50.7 % / 1.057 | +0.4 | −0.023 | ✅ ADOPTADO |
| Primeira | 55.6 % / 0.990 | **histórico 10 temporadas** 56.0 % / 0.947 | +0.4 | −0.043 | ✅ ADOPTADO |
| Ligue 1 | 54.3 % / 1.043 | **cuotas** 54.4 % / 0.986 | +0.1 | −0.057 | ✅ regla 2 (ambas mejoran; ll −0.057) |
| Serie A | 49.0 % / 1.047 | cuotas 53.4 % / 1.062 | **+4.4** | **+0.015** | ❌ NO adoptado: el log-loss excede el límite (0.01) por 0.005. Borderline documentado — candidato a revisión en v18 con calibración específica. |
| Liga MX | 52.2 % / 1.017 (split) | ningún candidato pasó | — | — | Sin cambios (v16) |

Candidatos descartados en walk-forward pese a buen screening: H2H rico solo
(Premier +3.6 pp en screening → −0.8 pp en WF: era ruido del split corto),
descanso en Primeira (+1.7 → −0.2). El screening con ~220-750 partidos de
validación es ruidoso: NINGUNA adopción se hizo sin walk-forward.

Descartados de plano en screening (planos o negativos en la mayoría de
ligas): rachas, tabla sola, forma exponencial, histórico ampliado en las
demás ligas (solo Primeira se benefició — dinámica opuesta al Mundial v16,
consistente con que las plantillas de clubes rotan más rápido).

## 3. Qué es cada grupo de features adoptado

- **cuotas** (`PROB_IMP_H/D/A`, `OVERROUND`): probabilidades implícitas del
  cierre B365 sin margen. En entrenamiento vienen del CSV histórico; en
  inferencia se usan las cuotas vigentes de `odds_actuales.json`
  (fixtures.csv en temporada) y, si no hay, la MEDIA del train (imputación
  idéntica a la v11 del Mundial; medias guardadas en metadata).
- **extras** (`H2H_GD3`, `DIFF_DESCANSO`, `DIFF_RACHA_V`, `DIFF_SIN_PERDER`,
  `DIFF_PPG`, `DIFF_POSICION`): estado por equipo/pareja calculado en pase
  cronológico sin fuga; el estado final se guarda en
  `team_stats_{liga}.json → estado_extra` para reproducirlo en inferencia.

## 4. Fase 2 (scraping) — decisiones honestas

- **Alineaciones confirmadas (Flashscore/LiveScore)**: NO backtesteable (no
  existen alineaciones históricas gratuitas leak-free). Cualquier número de
  backtest sería inventado. Se pospone a "medición en producción durante la
  temporada 2026-27" como propone la especificación — pendiente de v18.
- **Transfermarkt histórico vía Wayback Machine**: la Wayback no archiva de
  forma fiable las páginas de resumen de liga por fecha (cobertura irregular
  por temporada). Sin snapshots fechados completos, la feature reintroduce el
  sesgo de anticipación de v14/M9. Descartado por ahora.
- **Cuotas históricas para Liga MX (Betexplorer)**: football-data no trae
  cuotas MX; Betexplorer solo sirve la lista del día en HTML estático (v14).
  Sin cuotas históricas MX no hay ni feature ni línea base de mercado.
  Documentado como límite conocido.
- **SofaScore/WhoScored**: bloqueados desde esta red (v13). Sin cambios.

## 5. Reparación crítica encontrada de paso

`ClubEngine.predecir` aún importaba **giotto-tda** (se nos escapó en la
migración v14 a ripser): en local funcionaba porque giotto sigue instalado
en el venv, pero en Streamlit Cloud (sin giotto desde v14) cualquier
predicción de clubes habría fallado con ModuleNotFoundError. Migrado a
`_entropias_ripser` (mismo cálculo que el motor del Mundial).

## 6. Resultados finales de los modelos desplegados (split 80/20)

(ver metadata.json por liga tras el rebuild; el walk-forward de la tabla §2
es la referencia de no-regresión)

## 7. Mundial

Sin cambios (v16 intacto: 60.4 % / 0.871, walk-forward 60.0 % / 0.870).
