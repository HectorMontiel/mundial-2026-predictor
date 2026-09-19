# Backtesting v212 — la puerta de activación

Generado por `backtest_v212.py` el 2026-09-18 22:48.

## Criterios de activación (§7.3)

Una regla se activa **sola** si y sólo si cumple los cuatro. **No medible cuenta como no aprobado.**

| criterio | umbral |
|---|---|
| brier | <= baseline |
| p5 | >= 0 |
| hit_rate | >= baseline |
| roi | >= baseline |
| ruina_30d | <= 5% |

## Fuera de muestra (§7.4)

Los ledgers son walk-forward por construcción: `build_ledger_totales.py` recorta el entrenamiento a fechas estrictamente anteriores al pliegue de test. Reparto por pliegue:

| pliegue | picks |
|---|---|
| 0 | 21.874 |
| 1 | 19.902 |
| 2 | 17.930 |
| 3 | 15.363 |
| 4 | 14.627 |

## Modo Seguridad — A (baseline) vs B

| deporte | versión | n | Brier | ECE | hit rate | ROI | p5 | ruina 30d |
|---|---|---|---|---|---|---|---|---|
| Fútbol | A baseline | 36.006 | 0.2379 | 0.0072 | 0.4917 | -4.82 % | -5.73 % | +0.00 % |
| Fútbol | B seguridad | 1.885 | 0.2223 | 0.0129 | 0.6562 | -1.80 % | -4.55 % | +0.00 % |
| MLB | A baseline | 7.541 | 0.2445 | 0.0153 | 0.5645 | -0.97 % | -2.70 % | +0.00 % |
| MLB | B seguridad | 384 | 0.2318 | 0.0157 | 0.6354 | -0.26 % | -6.63 % | +0.00 % |
| Tenis | A baseline | 46.149 | 0.2117 | 0.0125 | 0.6588 | -4.91 % | -5.53 % | +0.00 % |
| Tenis | B seguridad | 8.048 | 0.2255 | 0.0326 | 0.6525 | -5.67 % | -6.96 % | +0.00 % |

## Escalada de líneas 1,5 → 2,5 (la única con precio real)

| versión | n | Brier | ECE | hit rate | ROI | p5 |
|---|---|---|---|---|---|---|
| A baseline (todo Más de 2.5) | 17.532 | 0.2628 | 0.0942 | 0.5142 | -4.88 % | -6.10 % |
| C escalada (ref. superior) | 1.028 | 0.2492 | 0.0769 | 0.6148 | -2.89 % | -6.78 % |
| C escalada (ref. base) | 1.028 | 0.2492 | 0.0769 | 0.6148 | -2.89 % | -6.78 % |

## Decisión por regla (§7.6, §7.7)

| regla | estado | por qué |
|---|---|---|
| `modo_seguridad` | 🔴 apagada | no supera los criterios en ningún deporte con muestra suficiente |
| `escalada_lineas` | 🔴 apagada | la regla de 3 de 4 fuentes no se dispara ni una vez sobre el histórico: dos de sus cuatro fuentes no existen ahí (el xG del repositorio es sintético, y las señales de contexto de partidos pasados no se archivaron). No es que falle los criterios: es que no hay con qué evaluarla, y no medible cuenta como no aprobado. |
| `escalada_2_5_a_3_5` | 🔴 apagada | no existe cuota histórica de Más de 3,5 en ninguna fuente del proyecto (odds_historico.db sólo guarda la línea 2,5), así que el ROI de la línea que se apostaría no se puede medir. No medible cuenta como no aprobado. |
| `modo_seguridad_nfl` | 🔴 apagada | no existe ledger walk-forward de NFL: `historico_nfl.csv` tiene 1.095 partidos con resultado pero sin predicciones fuera de muestra ni cuota de ganador |
| `modo_seguridad_kbo` | 🔴 apagada | no existe ledger walk-forward de KBO y `historico_kbo.csv` (13.149 partidos) NO tiene ninguna columna de cuotas, así que el ROI es inmedible por construcción |

## Justificación escrita

### `modo_seguridad` — apagada

no supera los criterios en ningún deporte con muestra suficiente

- **Fútbol**: p5 de bootstrap negativo (-4.55%)
- **MLB**: p5 de bootstrap negativo (-6.63%)
- **Tenis**: brier empeora (0.2255 contra 0.2117); hit_rate empeora (0.6525 contra 0.6588); roi empeora (-0.0567 contra -0.0491); p5 de bootstrap negativo (-6.96%)

### `escalada_lineas` — apagada

la regla de 3 de 4 fuentes no se dispara ni una vez sobre el histórico: dos de sus cuatro fuentes no existen ahí (el xG del repositorio es sintético, y las señales de contexto de partidos pasados no se archivaron). No es que falle los criterios: es que no hay con qué evaluarla, y no medible cuenta como no aprobado.

**Qué haría falta para poder decidirlo:** xG observado (FotMob cubre hoy 28 partidos) y un archivo de señales de contexto por partido, que sólo se puede construir hacia delante


### `escalada_2_5_a_3_5` — apagada

no existe cuota histórica de Más de 3,5 en ninguna fuente del proyecto (odds_historico.db sólo guarda la línea 2,5), así que el ROI de la línea que se apostaría no se puede medir. No medible cuenta como no aprobado.

**Qué haría falta para poder decidirlo:** cuotas de cierre de Más de 3,5, por partido, en al menos 1.000 partidos por competición


### `modo_seguridad_nfl` — apagada

no existe ledger walk-forward de NFL: `historico_nfl.csv` tiene 1.095 partidos con resultado pero sin predicciones fuera de muestra ni cuota de ganador

**Qué haría falta para poder decidirlo:** construir un ledger walk-forward de NFL, como `build_ledger_totales.py` hace con el fútbol


### `modo_seguridad_kbo` — apagada

no existe ledger walk-forward de KBO y `historico_kbo.csv` (13.149 partidos) NO tiene ninguna columna de cuotas, así que el ROI es inmedible por construcción

**Qué haría falta para poder decidirlo:** una fuente de cuotas históricas de KBO

