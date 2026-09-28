# Backtesting v212 — la puerta de activación

Generado por `backtest_v212.py` el 2026-09-28 13:30.

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
| 0 | 18.640 |
| 1 | 17.294 |
| 2 | 17.313 |
| 3 | 17.127 |
| 4 | 18.885 |

## Modo Seguridad — A (baseline) vs B

| deporte | versión | n | Brier | ECE | hit rate | ROI | p5 | ruina 30d |
|---|---|---|---|---|---|---|---|---|
| Fútbol | A baseline | 60.796 | 0.2365 | 0.0103 | 0.4931 | -5.19 % | -5.86 % | +0.00 % |
| Fútbol | B seguridad | 3.532 | 0.2167 | 0.0102 | 0.6750 | +0.26 % | -1.75 % | +0.00 % |
| KBO | A baseline | 224 | 0.2428 | 0.0241 | 0.5714 | +2.42 % | -7.79 % | +0.00 % |
| KBO | B seguridad | 8 | 0.2040 | 0.1293 | 0.7500 | +17.00 % | — | — |
| NFL | A baseline | 539 | 0.2228 | 0.0775 | 0.6753 | +24.01 % | +16.64 % | +0.00 % |
| NFL | B seguridad | 54 | 0.1918 | 0.1166 | 0.7593 | +14.62 % | +0.58 % | +0.00 % |
| Tenis | A baseline | 27.700 | 0.2172 | 0.0421 | 0.6501 | -4.70 % | -5.55 % | +0.00 % |
| Tenis | B seguridad | 5.072 | 0.2219 | 0.0257 | 0.6611 | -3.75 % | -5.34 % | +0.00 % |

## Escalada de líneas 1,5 → 2,5 (la única con precio real)

| versión | n | Brier | ECE | hit rate | ROI | p5 |
|---|---|---|---|---|---|---|
| A baseline (todo Más de 2.5) | 40.504 | 0.2472 | 0.0103 | 0.5119 | -4.76 % | -5.55 % |
| C escalada (ref. superior) | 1.024 | 0.2391 | 0.0220 | 0.6104 | -4.00 % | -8.02 % |
| C escalada (ref. base) | 1.024 | 0.2391 | 0.0220 | 0.6104 | -4.00 % | -8.02 % |

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

- **Fútbol**: p5 de bootstrap negativo (-1.75%)
- **KBO**: muestra vacía o mínima
- **NFL**: roi empeora (0.1462 contra 0.2401)
- **Tenis**: brier empeora (0.2219 contra 0.2172); p5 de bootstrap negativo (-5.34%)

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

