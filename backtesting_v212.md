# Backtesting v212 — la puerta de activación

Generado por `backtest_v212.py` el 2026-10-12 15:26.

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
| 0 | 18.650 |
| 1 | 17.660 |
| 2 | 17.071 |
| 3 | 17.136 |
| 4 | 18.602 |

## Modo Seguridad — A (baseline) vs B

| deporte | versión | n | Brier | ECE | hit rate | ROI | p5 | ruina 30d |
|---|---|---|---|---|---|---|---|---|
| Fútbol | A baseline | 60.825 | 0.2367 | 0.0101 | 0.4944 | -4.88 % | -5.54 % | +0.00 % |
| Fútbol | B seguridad | 3.575 | 0.2185 | 0.0053 | 0.6699 | -0.67 % | -2.63 % | +0.00 % |
| KBO | A baseline | 251 | 0.2394 | 0.0442 | 0.5817 | +2.92 % | -6.51 % | +0.00 % |
| KBO | B seguridad | 8 | 0.1671 | 0.2514 | 0.8750 | +34.50 % | — | — |
| NFL | A baseline | 539 | 0.2397 | 0.0153 | 0.5900 | +7.00 % | -0.10 % | +0.00 % |
| NFL | B seguridad | 34 | 0.1981 | 0.1010 | 0.7353 | +15.74 % | -4.22 % | +0.00 % |
| Tenis | A baseline | 27.504 | 0.2146 | 0.0343 | 0.6531 | -4.62 % | -5.46 % | +0.00 % |
| Tenis | B seguridad | 5.327 | 0.2269 | 0.0373 | 0.6480 | -5.64 % | -7.23 % | +0.00 % |

## Escalada de líneas 1,5 → 2,5 (la única con precio real)

| versión | n | Brier | ECE | hit rate | ROI | p5 |
|---|---|---|---|---|---|---|
| A baseline (todo Más de 2.5) | 40.579 | 0.2471 | 0.0090 | 0.5119 | -4.78 % | -5.53 % |
| C escalada (ref. superior) | 1.009 | 0.2371 | 0.0129 | 0.6184 | -2.83 % | -6.90 % |
| C escalada (ref. base) | 1.009 | 0.2371 | 0.0129 | 0.6184 | -2.83 % | -6.90 % |

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

- **Fútbol**: p5 de bootstrap negativo (-2.63%)
- **KBO**: muestra vacía o mínima
- **NFL**: p5 de bootstrap negativo (-4.22%)
- **Tenis**: brier empeora (0.2269 contra 0.2146); hit_rate empeora (0.6480 contra 0.6531); roi empeora (-0.0564 contra -0.0462); p5 de bootstrap negativo (-7.23%)

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

