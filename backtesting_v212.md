# Backtesting v212 — la puerta de activación

Generado por `backtest_v212.py` el 2026-10-05 13:47.

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
| 0 | 18.576 |
| 1 | 17.686 |
| 2 | 17.110 |
| 3 | 17.083 |
| 4 | 18.614 |

## Modo Seguridad — A (baseline) vs B

| deporte | versión | n | Brier | ECE | hit rate | ROI | p5 | ruina 30d |
|---|---|---|---|---|---|---|---|---|
| Fútbol | A baseline | 60.837 | 0.2366 | 0.0098 | 0.4937 | -5.02 % | -5.68 % | +0.00 % |
| Fútbol | B seguridad | 3.571 | 0.2175 | 0.0083 | 0.6729 | -0.22 % | -2.13 % | +0.00 % |
| KBO | A baseline | 237 | 0.2420 | 0.0258 | 0.5570 | -1.04 % | -10.87 % | +0.00 % |
| KBO | B seguridad | 13 | 0.1985 | 0.1492 | 0.7692 | +20.31 % | — | — |
| NFL | A baseline | 539 | 0.2336 | 0.0303 | 0.6289 | +14.71 % | +7.07 % | +0.00 % |
| NFL | B seguridad | 68 | 0.1699 | 0.1682 | 0.8235 | +25.36 % | +13.76 % | +0.00 % |
| Tenis | A baseline | 27.456 | 0.2146 | 0.0337 | 0.6538 | -4.49 % | -5.32 % | +0.00 % |
| Tenis | B seguridad | 5.295 | 0.2273 | 0.0404 | 0.6451 | -6.18 % | -7.73 % | +0.00 % |

## Escalada de líneas 1,5 → 2,5 (la única con precio real)

| versión | n | Brier | ECE | hit rate | ROI | p5 |
|---|---|---|---|---|---|---|
| A baseline (todo Más de 2.5) | 40.550 | 0.2470 | 0.0100 | 0.5118 | -4.78 % | -5.55 % |
| C escalada (ref. superior) | 999 | 0.2370 | 0.0119 | 0.6196 | -2.64 % | -6.40 % |
| C escalada (ref. base) | 999 | 0.2370 | 0.0119 | 0.6196 | -2.64 % | -6.40 % |

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

- **Fútbol**: p5 de bootstrap negativo (-2.13%)
- **KBO**: muestra vacía o mínima
- **NFL**: pasa los cuatro criterios
- **Tenis**: brier empeora (0.2273 contra 0.2146); hit_rate empeora (0.6451 contra 0.6538); roi empeora (-0.0618 contra -0.0449); p5 de bootstrap negativo (-7.73%)

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

