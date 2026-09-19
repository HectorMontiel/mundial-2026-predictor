# Patrones de acierto — dónde predice bien el modelo

Generado por `patrones_acierto.py` el 2026-09-18 23:11.

Universo: **107.280 picks resueltos con cuota real**. cuota mínima 1.20.

## Cómo leer esto, antes de los números

Se **descubre** en los pliegues 0-3 y se **juzga** en el pliegue 4, que no se usó para elegir. Un segmento se declara `confirmado` sólo si sobrevive a Benjamini-Hochberg en descubrimiento **y** tiene ROI y percentil 5 positivos en juicio. Con 500 preguntas al 5 %, salen 25 hallazgos falsos por aritmética pura: por eso el listón es ése y no «tiene buen ROI».

## 1. El panorama por banda de cuota

Responde directamente a «no me sirve una cuota 1,10».

| banda | n | cuota media | hit rate | prob. del modelo | calibración | ROI | p5 |
|---|---|---|---|---|---|---|---|
| 1.20-1.50 | 24.282 | 1.34 | 72.5% | 67.9% | +0.045 | -2.95 % | -3.60 % |
| 1.50-1.80 | 30.054 | 1.63 | 58.1% | 59.5% | -0.015 | -5.68 % | -6.49 % |
| 1.80-2.20 | 24.527 | 1.96 | 47.9% | 53.8% | -0.059 | -6.25 % | -7.31 % |
| 2.20-3.00 | 16.229 | 2.45 | 38.3% | 47.6% | -0.093 | -6.69 % | -8.19 % |
| 3.00-6.00 | 3.586 | 3.39 | 28.9% | 43.7% | -0.147 | -3.08 % | -7.23 % |

## 2. El panorama por banda de probabilidad

| banda | n | cuota media | hit rate | calibración | ROI | p5 |
|---|---|---|---|---|---|---|
| 30%-45% | 15.261 | 2.46 | 40.0% | -0.004 | -5.97 % | -7.49 % |
| 45%-55% | 27.458 | 1.95 | 50.2% | -0.010 | -5.88 % | -6.84 % |
| 55%-65% | 30.621 | 1.72 | 57.1% | -0.022 | -4.79 % | -5.65 % |
| 65%-75% | 17.460 | 1.54 | 64.0% | -0.057 | -4.65 % | -5.56 % |
| 75%-100% | 7.919 | 1.42 | 69.4% | -0.104 | -3.20 % | -4.83 % |

## 3. Por deporte

| deporte | n | cuota media | hit rate | calibración | ROI | p5 |
|---|---|---|---|---|---|---|
| Fútbol | 52.900 | 2.01 | 49.9% | -0.035 | -5.32 % | -6.02 % |
| MLB | 7.539 | 1.81 | 56.4% | +0.010 | -0.98 % | -2.63 % |
| Tenis | 38.284 | 1.62 | 61.2% | -0.028 | -5.53 % | -6.22 % |

## 4. Por liga

6 segmentos con ROI positivo en descubrimiento · **0 confirmados en juicio**.

| segmento | n desc. | ROI desc. | BH | n juicio | ROI juicio | p5 juicio | ¿confirmado? |
|---|---|---|---|---|---|---|---|
| rus_premier | 738 | +0.99 % | no | 186 | -3.10 % | -15.35 % | no |
| rumania | 954 | +0.34 % | no | 234 | -6.59 % | -17.22 % | no |
| brasil | 1.206 | +0.52 % | no | 301 | -6.69 % | -15.77 % | no |
| china | 658 | +2.15 % | no | 179 | -10.30 % | -22.33 % | no |
| finlandia | 510 | +2.91 % | no | 129 | -14.68 % | -29.33 % | no |
| bra_serie_b | 352 | +8.77 % | no | 0 | — | — | no |

## 5. Por mercado

0 segmentos con ROI positivo en descubrimiento · **0 confirmados en juicio**.

_Ninguno._


## 6. Por liga y mercado

10 segmentos con ROI positivo en descubrimiento · **0 confirmados en juicio**.

| segmento | n desc. | ROI desc. | BH | n juicio | ROI juicio | p5 juicio | ¿confirmado? |
|---|---|---|---|---|---|---|---|
| esp_hypermotion · Más de 2.5 | 313 | +9.52 % | no | 97 | +11.14 % | -3.99 % | no |
| ita_serie_b · Empate | 248 | +8.84 % | no | 44 | +10.61 % | -24.20 % | no |
| rus_premier · Ganador | 731 | +1.50 % | no | 185 | -2.58 % | -14.44 % | no |
| fra_ligue2 · Más de 2.5 | 252 | +2.08 % | no | 54 | -13.11 % | -34.78 % | no |
| eng_national · Menos de 2.5 | 442 | +0.03 % | no | 106 | -13.92 % | -30.04 % | no |
| finlandia · Ganador | 492 | +3.28 % | no | 129 | -14.68 % | -29.33 % | no |
| bel_pro_league · Menos de 2.5 | 233 | +1.92 % | no | 75 | -15.77 % | -34.56 % | no |
| eredivisie · Menos de 2.5 | 198 | +1.40 % | no | 43 | -22.02 % | -47.89 % | no |
| gre_super_league · Ganador | 389 | +0.05 % | no | 100 | -27.43 % | -42.25 % | no |
| bra_serie_b · Ganador | 352 | +8.77 % | no | 0 | — | — | no |

## Veredicto

**Ningún segmento sobrevive al juicio fuera de muestra.**

Es un resultado, no un fallo del análisis. Significa que los segmentos que ganan en los pliegues 0-3 no repiten en el 4, que es la firma del sobreajuste: el patrón estaba en la muestra, no en el mundo. Un buscador de patrones que no puede devolver «no hay» no sirve para nada, porque siempre devolvería algo.
