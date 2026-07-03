# 🔍 Informe de Diagnóstico — Cambio de predicción Egipto vs Australia sin partidos nuevos

**Fecha de auditoría:** 2026-07-03 · **Auditor:** pipeline de validación exhaustiva (Fases 1-6)

## Resumen ejecutivo (en cristiano)

**El modelo NO está roto.** El cambio de "gana Egipto" a "gana Australia" lo causó
un **defecto de reproducibilidad en la capa de datos**, ya corregido: cada vez que
el histórico crecía con partidos de *otros* equipos, el ruido aleatorio con el que
se estiman las métricas avanzadas (xG, remates) se re-sorteaba para **todos** los
partidos ya jugados — incluidos los de Egipto y Australia, que no habían vuelto a
jugar. En un cruce tan parejo (ELO 1754 vs 1765), ese jitter bastó para voltear al
ganador. Con la corrección, las métricas de un partido quedan fijadas para siempre
en cuanto entran al sistema, y la predicción solo cambia cuando hay información
nueva de verdad.

## Fase 1-2 — Estados del sistema y cadena de actualización

| Evidencia | Resultado |
|---|---|
| `modelo_tda.joblib` D-1 vs D | **Idéntico** (mismo hash git `3fd9f60` en commit inicial, HEAD y disco) — no hubo reentrenamiento entre estados |
| `team_stats.json`, `historico_partidos.csv` | Idénticos al commit; los commits del despliegue solo tocaron `config.toml`, `packages.txt` y un log |
| Procesos entre D-1 y D | Pipeline de datos ejecutado (00:36-00:37 del 03/07); el mtime del modelo (01:37) fue git reescribiendo el archivo en el merge, no un retrain |
| Cuotas (`fetch_odds`) | Sin efecto (cobertura 0 %, feature inactiva) |

## Fase 3 — Egipto y Australia no jugaron

- Último partido de Egipto: **2026-06-26** (vs Irán). Último de Australia: **2026-06-25** (vs Paraguay).
- Los partidos añadidos entre estados (30/06-02/07: CIV-NOR, FRA-Suecia, MEX-ECU, ENG-RD Congo, BEL-SEN, USA-Bosnia, ESP-AUT, POR-CRO, SUI-ALG) **no involucran a ninguno de los dos**.
- Sus datos REALES (goles, ELO, forma) no cambiaron: ELO estable en 1754 (EGY) y 1765 (AUS).

## Fase 4 — Causa raíz demostrada (reproducción del síntoma)

Se reconstruyeron ambos estados y se predijo con **el mismo modelo**:

| Estado | P(Egipto) | P(Empate) | P(Australia) | Veredicto |
|---|---|---|---|---|
| D-1 (15,892 partidos) | 44.9 % | 26.0 % | 29.1 % | **Gana Egipto** |
| D (15,898 partidos, +6 de terceros) | 38.4 % | 21.8 % | 39.8 % | **Gana Australia** |

**Mecanismo:** `generate_advanced_metrics` usaba un flujo RNG global de longitud
`n`. Al crecer `n`, el ruido asignado a CADA fila histórica se desplazaba. Ejemplo
medido: el xG estimado del mismo partido NZL-EGY del 21/06 pasó de **1.62 a 0.46**
sin que nadie jugara; el `DIFF_AMAR_MA5` del cruce saltó de **+2.00 a −0.83**.
Además, la ordenación por fecha no era estable: los empates de fecha se procesaban
en orden distinto entre corridas, moviendo el ELO de 637 filas (hasta 16.5 puntos,
todos equipos menores).

## Fase 5 — Corrección aplicada (bug objetivable) e integridad

1. **Ruido determinista por MATCH_ID** (`correlated_synthetic_generator.py`):
   los uniformes se derivan de un hash estable del `MATCH_ID` + variable, y se
   transforman con normal/Poisson inversa. Misma metodología y distribuciones
   calibradas con StatsBomb; cero dependencia del tamaño del dataset.
2. **Orden total estable** `['date', 'MATCH_ID']` con mergesort en
   `data_fetcher.py` y `feature_engineering.py`: el ELO es reproducible.
3. **Pruebas de estabilidad** (en `PLAN_DE_PRUEBAS.md`): quitar/añadir los 6
   partidos de terceros deja **diferencia 0.0** en las 13 columnas estimadas y en
   `elo_diff` de los 15,892 partidos compartidos; dos corridas independientes
   producen rellenos idénticos; el replay del histórico reproduce exactamente
   `team_stats.json`.
4. **Reentrenamiento con datos estables** (obligatorio para consistencia
   modelo↔datos): precisión 59.5 % / log-loss 0.901 en el split principal;
   walk-forward de 5 ventanas: media **59.5 %** (rango 57.1-64.0 %) — dentro de la
   banda histórica del sistema (57-62 %). El modelo está sano.
5. `git diff` de funciones de cálculo: sin regresiones previas; los únicos
   cambios de lógica son los de esta corrección, documentados aquí.

## Fase 6 — Estado final y protocolo futuro

- Predicción actual EGY vs AUS: **Egipto 38.8 % · Empate 25.3 % · Australia 35.9 %**
  — un partido genuinamente parejo. A partir de ahora esta cifra **solo** se moverá
  si Egipto o Australia juegan, si Kaggle corrige un dato suyo, o si se reentrena
  el modelo (y el monitor lo hará visible).
- **Monitor de transparencia** añadido a la UI: en cada consulta, si el cruce ya se
  había consultado antes, se muestran las probabilidades anteriores y las **3
  features que más variaron** (con valores antes→ahora), con la fecha de los datos
  de cada consulta. Persistido en `predicciones_log.json`.

### Protocolo ante futuras fluctuaciones

1. Mirar el monitor 📊 de la UI: dice qué features cambiaron y cuánto.
2. `git diff` de `team_stats.json` / `modelos/metadata.json`: ¿cambiaron datos, modelo o ambos?
3. Si cambió el modelo: verificar en `metadata.json` que el retrain fue programado y sus métricas están en banda (55-62 %).
4. Si cambiaron los datos: confirmar en `historico_partidos.csv` qué partidos nuevos/corregidos lo explican (con el fix, SOLO partidos propios pueden mover las features de un equipo).
5. Si nada de lo anterior explica el cambio → abrir incidencia (no debería ocurrir).
