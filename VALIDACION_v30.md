# VALIDACIÓN v30 — Consolidación multi-deporte, CDI y corrección crítica

**Fecha:** 2026-07-21 · Regla de oro respetada; fútbol (Mundial 60.49 % +
10 ligas) intacto y aislado.

## 1. Corrección crítica de exportación (§1) ✅

El `AttributeError` de producción al pulsar «Exportar (texto)» se resolvió de
raíz Y con blindaje:
- `exportar_txt()`/`exportar_csv()` ahora aceptan **argumento opcional**
  (si es `None` usan `_ULTIMO_RESULTADO`, el último barrido guardado a nivel
  de módulo) y leen todos los campos con `.get()` (robustos ante cualquier
  forma de los picks).
- `apuestas_del_dia()` devuelve un dict siempre (bug latente: la refactor
  dejó el return sin valor — corregido).
- Los `download_button` del dashboard **pre-generan el contenido dentro de un
  try/except**: un fallo aquí nunca vuelve a romper la página (muestra un
  aviso). Verificado con AppTest de la vista de Apuestas del Día.

## 2. CDI — Índice de Desincronización Circadiana (§2)

`cdi.py`: husos cruzados por el visitante (con signo; + = viaje al este, el
desfase más duro), husos por sede de MLB y NBA. A/B walk-forward por deporte:

| Deporte | acc base | acc +CDI | ll base | ll +CDI | Veredicto |
|---|---|---|---|---|---|
| MLB | 0.5498 | 0.5489 | 0.6874 | 0.6877 | ❌ **descartado** (el béisbol no se desincroniza así) |
| **NBA** | 0.6510 | **0.6541** | 0.6438 | **0.6293** | ✅ **ADOPTADO** (+0.31 pp, ll −0.015) |

**Hallazgo limpio:** la hipótesis circadiana se cumple en BALONCESTO
(back-to-backs + viajes costa a costa de 3 husos) pero NO en béisbol — el
CDI queda en el motor NBA y fuera del de MLB, cada uno con su evidencia.

## 3. MLB — refinamiento (§3)

- Motor v29 intacto (55.0 % WF vs ELO 54.2 %). CDI probado y descartado (§2).
- **MLB-StatsAPI (live) y umpire DIFERIDOS**: el umpire exige los *event
  files* de Retrosheet (no los game logs), un parser mucho mayor para señal
  incierta; la actualización diaria por StatsAPI aporta poco mientras
  Retrosheet no publique 2026. Documentado; el motor ya opera con cuotas en
  vivo de The Odds API.

## 4. NBA — motor nuevo (§4) ✅

- `nba_scraper.py` (nba_api, verificado funcional desde esta red): 6,140
  juegos 2021-26, emparejados local/visitante con posesiones para OFF/DEF
  rating.
- `engines/nba_engine.py`: ELO, OFF/DEF/NET rating (pts por 100 pos., MA5),
  pace, descanso, back-to-back, racha + **CDI**; ensemble XGB+LGBM+RF
  calibrado + Poisson de puntos totales.
- **Walk-forward 65.4 % (con CDI) ≈ ELO 65.5 %**, log-loss 0.629 — en la NBA
  el resultado está muy dominado por el ELO; el modelo lo iguala y el CDI
  mejora la calibración. **Modo analítico** hasta que The Odds API reactive
  la NBA (octubre 2026); sin cuotas en vivo, no hay EV real (avisado).

## 5. Tenis — motor nuevo (§5) ✅

- Dataset Kaggle `dissfya/atp-tennis-...` (68k partidos 2000-2026, **con
  superficie y cuotas de cierre** — permite línea base de MERCADO).
- `engines/tennis_engine.py`: **ELO POR SUPERFICIE** (clay/hard/grass,
  cronológico) + ELO global + ranking + forma + H2H; ensemble calibrado.
- Backtest: **64.9 % vs ranking/ELO 63.3 %** (+1.6 pp, supera la línea base
  del spec) pero **mercado 68.3 %** — las cuotas de tenis están entre las más
  afiladas del mundo; nuestro modelo NO las bate. **Modo analítico** honesto:
  herramienta de análisis (cuota justa), no de EV. Sin cuotas de tenis en la
  capa gratuita de The Odds API de todos modos.

## 6. Fútbol — Carril B (§6.1) — sigue bloqueado por datos

Re-verificado: el VORP-PFI sobre Champions 2022-25 exige ratings históricos
de FotMob que NO existen gratis para esas temporadas (la caché nació en v24;
`ratings_historicos.csv` tiene 787 ratings de ~28 partidos, 3 jugadores
cruzables con xG). Un walk-forward con eso sería ruido. La infraestructura
(bottom_up_engine, jaccard_index) queda lista en la rama
`experimento/bottom-up`; se activará cuando la cobertura de ratings crezca.
El CDI en fútbol (MLS/Liga MX) se pospone: primero necesita el histórico de
sedes por partido que el pipeline no almacena aún — documentado, no forzado.

## 7. Apuestas del Día multi-deporte (§7) ✅

- Cobertura Liga MX corregida en v29 (fuzzy nombre→liga) — verificada.
- Exportación TXT/CSV blindada (§1).
- MLB con su propio panel de Apuestas del Día en vivo; NBA/tenis en modo
  analítico (predicción + cuota justa, sin EV — avisado).

## 8. No regresión ✅

test_simetria ✓ · test_match_parlay ✓ · smoke 10 ligas de fútbol ✓ · smoke
motores MLB/NBA/Tenis ✓ · AppTest dashboard en las 4 vistas nuevas
(Apuestas del Día, MLB, NBA, Tenis) ✓ · Mundial intacto. Sin dependencias
nuevas en runtime (nba_api/kagglehub/retrosheet solo se usan al ENTRENAR,
en local; el cloud solo hace inferencia sobre artefactos).

## 9. Diferido a v31

Umpire MLB (event files Retrosheet); NBA con EV real (octubre); Carril B
cuando haya ratings FotMob acumulados; CDI en fútbol con histórico de sedes.
