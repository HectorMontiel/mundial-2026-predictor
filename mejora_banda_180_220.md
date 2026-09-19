# Fase A — calibración por banda de cuota

Generado por `calibrador_bandas.py` el 2026-09-18 23:40.

## Qué puede y qué no puede hacer esto

La isotónica es **monótona**: no cambia el orden de los picks, así que **no puede descubrir apuestas buenas**. Lo que hace es arreglar el Brier y el ECE —que el número enseñado signifique lo que dice— y **impedir apuestas malas**, porque al bajar la probabilidad en la banda sobreconfiada, los picks que antes cruzaban el listón de EV dejan de cruzarlo. No crea ventaja: evita pérdidas.

## Sin fuga

Cada pliegue se calibra con la curva ajustada **sólo con los pliegues anteriores**. El pliegue 0 no tiene pasado y se queda sin calibrar; por eso `n calibrados` es menor que `n`.

## Calibración: antes y después

| banda | n | calibrados | hit real | prob. antes | prob. después | sesgo antes | sesgo después |
|---|---|---|---|---|---|---|---|
| 1.20-1.50 | 24.282 | 17.918 | 72.5% | 67.9% | 71.6% | +0.045 | +0.009 |
| 1.50-1.80 | 30.054 | 23.485 | 58.1% | 59.5% | 58.7% | -0.015 | -0.006 |
| 1.80-2.20 | 24.527 | 19.235 | 47.9% | 53.8% | 49.5% | -0.059 | -0.016 |
| 2.20-3.00 | 16.229 | 12.600 | 38.3% | 47.6% | 40.3% | -0.093 | -0.020 |
| 3.00-6.00 | 3.586 | 2.734 | 28.9% | 43.7% | 32.6% | -0.147 | -0.036 |

## Brier y ECE

| banda | Brier antes | Brier después | ECE antes | ECE después |
|---|---|---|---|---|
| 1.20-1.50 | 0.2076 | 0.2015 | 0.0696 | 0.0195 |
| 1.50-1.80 | 0.2502 | 0.2451 | 0.0592 | 0.0132 |
| 1.80-2.20 | 0.2604 | 0.2519 | 0.0757 | 0.0189 |
| 2.20-3.00 | 0.2510 | 0.2410 | 0.0930 | 0.0302 |
| 3.00-6.00 | 0.2331 | 0.2135 | 0.1475 | 0.0376 |

## Efecto sobre la selección y el ROI

Se apuesta sólo cuando la probabilidad supera el precio justo (`p > 1/cuota`). Ahí es donde la calibración cambia algo: el orden no varía, pero el umbral efectivo sí.

| banda | apostados antes | apostados después | ROI antes | ROI después | p5 antes | p5 después |
|---|---|---|---|---|---|---|
| 1.20-1.50 | 5.437 | 8.168 | -4.26 % | -3.62 % | -5.67 % | -4.84 % |
| 1.50-1.80 | 10.640 | 6.820 | -6.08 % | -5.90 % | -7.38 % | -7.56 % |
| 1.80-2.20 | 14.966 | 7.432 | -6.08 % | -5.93 % | -7.43 % | -7.84 % |
| 2.20-3.00 | 12.146 | 5.589 | -6.26 % | -6.54 % | -8.08 % | -9.33 % |
| 3.00-6.00 | 3.586 | 1.637 | -3.08 % | +0.97 % | -7.29 % | -5.58 % |

## Veredicto en la banda objetivo (1.80-2.20)

**La calibración se acepta.** mejora la calibración en la banda objetivo

La regla del encargo es dura y es la correcta: mejorar el ROI global no basta, porque podría venir de las cuotas cortas. Sólo cuenta si mueve la aguja en 1.80-2.20.

## Estado

`USAR_CALIBRACION` arranca en **False**. El interruptor vive en `calibrador_bandas.py` y lo lee `modo_seguridad.evaluar()`.
