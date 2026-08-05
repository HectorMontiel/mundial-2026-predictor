# VALIDACIÓN v100 — La localía de la Leagues Cup, medida contra el mercado

**Fecha:** 2026-08-05

Se probaron las mejoras propuestas para Leagues Cup y KBO. Este documento dice
cuáles se midieron, con qué números, y por qué **ninguna de las dos
competiciones entra en Capa 1**.

---

## 1. Leagues Cup — las cuatro formas de matar la localía

### 1.1 Un matiz sobre «quitar la localía»

La propuesta era «forzar `is_home = 0`». **El modelo no tiene esa feature**: la
ventaja de campo está IMPLÍCITA en el conjunto de entrenamiento (11.000
partidos de liga doméstica donde el local gana más). Quitarla no es poner una
variable a cero, es darle a los partidos de Leagues Cup su **propio
intercepto**. Se hizo de cuatro maneras:

| variante | qué hace |
|---|---|
| `base` | lo desplegado |
| `neutral` | + indicador de cancha neutral (intercepto propio para la LC) |
| `completo` | + neutral + cruce entre ligas + qué liga hace de local |
| `sin_local` | se promedia la predicción con la del partido ESPEJO — la forma más pura de anular la localía, sin estimar nada |

### 1.2 Contra el ELO (precisión por edición)

| variante | 2023 | 2024 | 2025 | global |
|---|---:|---:|---:|---:|
| base | 0,3896 | 0,4545 | 0,4677 | 0,4352 |
| neutral | **0,4935** | 0,4026 | 0,4516 | **0,4491** |
| completo | 0,4026 | 0,4416 | 0,4677 | 0,4352 |
| sin_local | 0,3506 | 0,4026 | 0,4516 | 0,3981 |
| ELO | 0,4675 | 0,3896 | 0,4516 | 0,4352 |

En el juicio (2025, no mirado para elegir) el log-loss **sí mejora** con la
corrección: `base` 1,0466 → `sin_local` **1,0269**. Pero la precisión no bate
al ELO con significancia en ninguna variante (p5 negativo en todas).

### 1.3 Y entonces se midió lo que de verdad decide la Capa 1

Validar por precisión contra el ELO sobre 62 partidos no sirve para nada: el
intervalo es de ±10 pp. **El criterio de Capa 1 es batir al MERCADO.** Así que
se reunieron las cuotas de cierre de la competición
(`ingesta_cuotas_leagues_cup.py`, BetExplorer, rutas planas permitidas):
**90 partidos con 1X2 de cierre**, 86 de ellos cruzables.

#### ⚠️ Y ahí el guardia de la regla de oro 7 paró el backtest

La primera comprobación —que ESPN y BetExplorer dieran el mismo resultado—
falló: coincidían en **60 de 86 (69,8 %)**. El motivo importa mucho:

| | empates |
|---|---|
| BetExplorer | **0,0 %** |
| ESPN | **29,5 %** |

La Leagues Cup decide **todos** sus partidos por penaltis: BetExplorer guarda
al ganador del desempate y ESPN el marcador reglamentario. ¿Y para qué se pagan
las cuotas? Para los 90 minutos — la columna X tiene una probabilidad implícita
media del **25,3 %**, coherente con el 30,2 % de empates observados en esta
muestra. Si no hubiera empate en ese mercado, esa columna no valdría 1/4.

**Liquidar con el `res` de BetExplorer habría resuelto apuestas de 90 minutos
con el ganador tras penaltis: un ROI inventado y sin un solo error en
pantalla.** El precio se toma de BetExplorer; el resultado, de ESPN.

#### El resultado, con las fuentes ya bien puestas (n=86)

| variante | Brier | log-loss | precisión | apuestas EV>2 % | ROI | p5 |
|---|---:|---:|---:|---:|---:|---:|
| base | 0,4121 | 1,0599 | 0,4651 | 73 | −22,01 % | −48,55 % |
| neutral | 0,4450 | 1,2147 | 0,3953 | 120 | −9,18 % | −33,85 % |
| completo | 0,4429 | 1,4269 | 0,3837 | 106 | +1,98 % | −24,46 % |
| sin_local | 0,4411 | 1,2309 | 0,4070 | 110 | −5,65 % | −30,55 % |
| **MERCADO** | **0,3970** | **1,0184** | **0,4884** | — | — | — |

**El mercado gana en las tres métricas.** Y las correcciones de localía, que
mejoraban el log-loss frente al ELO, lo **empeoran** frente al mercado (base
1,0599 → completo 1,4269). El único ROI positivo (+1,98 % de `completo`) tiene
p5 −24,46 %: es ruido.

**Veredicto: la Leagues Cup NO entra en Capa 1.** La hipótesis de la localía
era correcta como diagnóstico —el sesgo existe y es de −25,6 pp— pero
corregirlo no produce un modelo que bata al precio.

---

## 2. KBO — las cuatro salidas ya estaban medidas (v99)

| | resultado |
|---|---|
| mezcla modelo + mercado | peso óptimo del modelo **w = 0,00** |
| banda de discrepancia | sólo «gana» donde casi no discrepa (ahí copia) |
| favoritos claros | ROI −10,4 %, p5 −32,6 % |
| apostar al revés | también pierde (−2,96 %) |

El `w = 0,00` es el que cierra la discusión: las features actuales **no tienen
información marginal sobre el precio**. Por eso las mejoras propuestas para la
KBO (Statiz, bullpen, parque, clima) son la vía correcta —son información que
hoy no está— pero son **ingesta nueva**, no un ajuste de modelado como el de la
Leagues Cup. No se han implementado en esta versión y no se finge lo contrario.

---

## 3. Lo que esta versión sí deja hecho

- `ingesta_cuotas_leagues_cup.py` — 90 cierres 1X2 de la competición, con el
  aviso de penaltis documentado en el código para que nadie los liquide mal.
- Los cuatro experimentos de localía, reproducibles
  (`_v100_localia_leagues_cup.py`, `_v100_backtest_leagues_cup.py`).
- La constatación de que **el criterio correcto para estas dos competiciones es
  el mercado, no el ELO**, y que medido así ninguna de las dos pasa.

## 4. Qué queda, y en qué orden

1. **KBO — bullpen y OPS/FIP recientes** desde los *box scores* de Naver (que
   ya se descargan) y Statiz. Es la única palanca que ataca el `w = 0,00`:
   meter información que el precio tiene y el modelo no.
2. **KBO — factor de parque**: el campo `stadium` ya viene en la respuesta de
   Naver y hoy se descarta al construir el histórico. Es lo más barato de los
   cuatro.
3. **Leagues Cup**: sin más ediciones no hay nada que hacer. Corregir la
   localía no bastó; el problema es que el mercado de esta competición está
   bien hecho y la muestra es corta.
