# VALIDACIÓN v99.2 — El IDF entra en producción (tenis), y dónde NO entra

**Fecha:** 2026-08-05

---

## 1. El A/B que de verdad decidía

La v99.1 midió el IDF contra una base de **dos** features (ELO global y de
superficie) y salió claramente positivo. Pero el motor desplegado no usa esa
base: usa **6 features en ATP y 13 en WTA**, y una de ellas **ya es
`DIFF_FORMA10`**. La pregunta dura era si el IDF aporta algo ENCIMA de la forma
en bruto, o si ésta ya lo contenía.

Se repitió el A/B con el `_dataset` **del propio motor**, o sea exactamente lo
que se despliega:

| ATP · 352.679 partidos | log-loss | precisión | Brier |
|---|---:|---:|---:|
| A — desplegado (6 feat.) | 0,60296 | 0,6680 | 0,2082 |
| **B — + IDF (7 feat.)** | **0,60199** | **0,6690** | **0,2078** |

| WTA · 315.657 partidos | log-loss | precisión | Brier |
|---|---:|---:|---:|
| A — desplegado (13 feat.) | 0,50653 | 0,7475 | 0,1689 |
| **B — + IDF (14 feat.)** | **0,50624** | **0,7476** | **0,1688** |

Bootstrap **pareado** (diferencia partido a partido, no dos medias sueltas):

| | n | mejora | p5 | P(mejora > 0) |
|---|---:|---:|---:|---:|
| ATP | 105.804 | +0,00097 | **+0,00072** | **100,0 %** |
| WTA | 94.698 | +0,00030 | **+0,00015** | **100,0 %** |

**p5 positivo en los dos circuitos por separado y la precisión no baja en
ninguno** — las dos condiciones que el proyecto exige desde la v26. **ADOPTADO
en producción.**

La ganancia de la WTA es tres veces menor que la de la ATP, lo cual encaja: su
vector ya tenía 13 features (incluidas las de nivel de la v67), así que quedaba
menos por explicar.

### Cómo se integró sin romper nada

`DIFF_IDF` va **al final** de la lista `FEATURES`. No es un detalle de estilo:
`FEATURES_V30 = FEATURES[:6]` y `FEATURES_V67 = FEATURES[:13]` son *slices*, y
meter la feature en medio habría desplazado los índices de todos los modelos ya
guardados — exactamente el aviso que dejó escrito la v67.

Estado nuevo por jugador (`estado['jugadores'][p]['idf']`) para poder
reproducir la feature en inferencia; **0,0 es el valor neutro** y significa
literalmente «rinde como su ELO predice», que es lo correcto cuando no hay
historial: no se inventa ni crisis ni pico de forma.

Reentrenados los dos circuitos y verificado que cargan y predicen:
ATP precisión 0,6745 · log-loss 0,5975; WTA 0,7593 · 0,4821.

---

## 2. Dónde NO entra: la MLB

Mismo protocolo, mismo `_dataset` del motor desplegado (26.396 juegos):

| | log-loss | precisión | Brier |
|---|---:|---:|---:|
| A — desplegado | 0,68559 | 0,5464 | 0,2463 |
| B — + IDF (ventana 15) | 0,68510 | 0,5492 | 0,2460 |

| n | mejora | p5 | P(mejora > 0) |
|---:|---:|---:|---:|
| 5.280 | +0,00049 | **−0,00050** | 79,7 % |

La mejora va en la dirección correcta pero **el p5 es negativo**: con 5.280
juegos de juicio no se distingue de cero. **RECHAZADO** — se aplica la misma
regla que en tenis, no una más blanda porque el signo guste.

Que en tenis salga y en la MLB no tiene una lectura razonable: el tenis es
individual y un jugador en crisis arrastra su forma partido a partido, mientras
que un equipo de béisbol rota nueve bateadores y un abridor distinto cada día —
la «forma» del equipo es un objeto mucho más ruidoso, y el modelo ya tiene el
abridor por separado.

---

## 3. Factor de parque de la KBO: capturando lo que faltaba

La v99.1 midió que el factor de parque **no ayuda al moneyline**, y con razón:
describe cuántas **carreras** se anotan, no quién gana. Donde debería servir es
en el mercado de **totales**… y ahí no se podía medir nada porque no se estaba
guardando ni una línea.

`daily_snapshots.capturar_kbo()` guarda ahora también over/under. Comprobado el
2026-08-05: **los partidos de KBO de Pinnacle traen sólo `home`/`away`, sin
totales**. Puede ser la hora (las casas publican el total más tarde) o que ese
feed no los dé nunca. La captura queda puesta de forma defensiva: el día que
aparezcan se guardan, y mientras tanto no cuesta nada.

**No se adopta el factor de parque mientras no se pueda medir.** Sigue fuera
del modelo.

---

## 4. Resumen

| | decisión | evidencia |
|---|---|---|
| IDF en ATP | **ADOPTADO en producción** | p5 +0,00072 · P(>0)=100 % · n=105.804 |
| IDF en WTA | **ADOPTADO en producción** | p5 +0,00015 · P(>0)=100 % · n=94.698 |
| IDF en KBO | **ADOPTADO** (v99.1) | Brier contra cierre 0,2492 → 0,2476 |
| IDF en MLB | **RECHAZADO** | p5 −0,00050, no se distingue de cero |
| Factor de parque | **sin adoptar**, captura activada | Pinnacle no publica totales de KBO hoy |

**Lo que el IDF no hace, otra vez:** mejora la probabilidad que se publica —que
es la que ve el usuario en la ficha— pero **no crea un edge de apuesta**. El
ROI del tenis sigue negativo y el mercado sigue mejor calibrado. Ninguna de
estas competiciones cambia de capa.

---

## 5. Lo que queda

1. **IDF en fútbol y NBA.** `indice_forma.py` es genérico; falta el A/B de cada
   uno con su propio `_dataset`. En fútbol hay el matiz del empate (el IDF
   binario no lo contempla) y habrá que decidir si se puntúa 0,5.
2. **Statiz y bullpen para la KBO.** El `w = 0,00` de la v99 sigue diciendo que
   las features actuales no tienen información marginal sobre el precio; el IDF
   cerró un quinto de la brecha y el resto necesita información que hoy no
   está.
3. **Totales de KBO**: en cuanto alguna casa los publique, medir el factor de
   parque donde de verdad debería notarse.
