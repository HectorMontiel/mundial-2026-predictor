# v111 — La quinta casa, y los patrones de comportamiento medidos

Dos frentes que el usuario pidió: **más casas** (la palanca con retorno medido)
y **patrones de comportamiento** que ayuden a predecir el resultado. Uno se
adopta con números buenos; el otro se rechaza con números claros, y explico por
qué el rechazo es informativo.

---

## 1. Unibet (Kambi) entra al tablón — ADOPTADA

### El sondeo

El line shopping es la única vía del proyecto con ROI positivo **y robusto**
(+11,49 % en el tramo de juicio, p5 +1,73 %), y vive de la dispersión entre
casas: cada precio nuevo multiplica las oportunidades sin tocar el modelo.

Se sondearon quince candidatas comprobando `robots.txt` antes de nada:

| resultado | casas |
|---|---|
| **JSON abierto con cuotas** | **Kambi (Unibet)** |
| 403 a peticiones automáticas | FanDuel, BetMGM, Betfair, Stake, Winamax |
| no resuelve / timeout | DraftKings, Betsson, Betclic, Betano MX, Bodog |
| HTML montado por JavaScript | Caliente, Codere, OddsPortal, Flashscore, BetOnline, Coolbet |
| exige clave | Cloudbet (401) |

Las que la v71 ya había descartado (Smarkets, Betano, 1xBet, Betsson,
Marathonbet) no se volvieron a probar: está documentado.

**La v71 había descartado Kambi** con el argumento de «200 pero sólo 185
eventos, mayoría esports y amistosos». Miraba otro endpoint. El bueno es
`listView/{deporte}.json`: **380 eventos de fútbol en 126 competiciones**, más
tenis (90), béisbol (15) y baloncesto (16).

### Lo que aporta, medido

Sobre 33 partidos con dos o más casas en el tablón:

| | |
|---|---|
| partidos donde Unibet aparece | 33 de 33 |
| donde da **el mejor precio** | **17 (52 %)** |
| ventaja media sobre la segunda mejor | **+3,64 %** |
| mediana | +1,69 % |
| mejor caso | **+11,43 %** |

Un ejemplo real del tablón:

```
FC Metaloglobus Bucureşti vs Chindia Târgovişte
  Pinnacle   home 1.90   draw 3.32   away 3.67
  Bovada     home 1.72   draw 3.50   away 4.10
  Unibet     home 2.15   draw 3.15   away 3.00   <- +13 % sobre Pinnacle
  Playdoit   home 2.13   draw 3.20   away 3.25
```

### UNA sola marca, y no es una preferencia

Kambi es una plataforma compartida: Unibet, 888sport, LeoVegas, Rizk, Casumo y
ATG cuelgan del **mismo motor de precios**. Comprobado sobre los 272 partidos
que `ub` y `atg` publican a la vez:

| | |
|---|---|
| precio **idéntico** | **248 (91 %)** |
| distinto | 24 (9 %), y por céntimos (2,90 contra 2,95) |

Esos 24 son ruido de captura entre dos peticiones separadas por segundos, no
dos opiniones sobre el partido. **Añadir una segunda marca de Kambi fabricaría
dispersión falsa**: el sistema vería «una casa paga más que otra» donde hay un
único precio y emitiría picks de line shopping inexistentes. Es la trampa del
EV+ ilusorio que la v25 documentó, y sería invisible en la interfaz.

Queda fijado con un test que falla si alguien añade otra marca.

### Y los esports fuera

El feed de «football» de Kambi mezcla **Esports Battle (2x4min)** y **Cyber
Live Arena**: partidas de consola con nombres como «Barcelona (dm1trena)». Son
38 de los 308. Sin filtrar, el emparejado difuso las casaría con el Barcelona
de verdad y el line shopping compararía el precio de un partido real contra el
de una partida de cuatro minutos. Filtradas: **0 de 270**.

---

## 2. Patrones de comportamiento — SEÑAL REAL, pero NO paga la comisión

El usuario pidió buscar «correlaciones que evalúen patrones de comportamiento:
partidos pasados, rendimiento, desgaste». Se construyeron sobre **147.516
partidos de 66 competiciones (1990-2026)**, todas calculadas con lo conocido
ANTES del partido.

### ¿Predicen el resultado?

| señal | n | correlación con «gana el local» |
|---|---|---|
| diferencia de forma (pts últimos 5) | 145.675 | **+0,198** |
| diferencia de defensa | 145.675 | **+0,178** |
| diferencia de ataque | 145.675 | **+0,169** |
| diferencia de descanso | 145.675 | −0,027 |
| sólo el local cansado | 147.516 | +0,021 |

### ¿Aportan sobre la CUOTA DE CIERRE? (que es lo que decide)

Correlación con el **residuo** del mercado — lo que la cuota no explicó — sobre
72.171 partidos:

| señal | correlación | z | veredicto |
|---|---|---|---|
| **diferencia de forma** | +0,0320 | **8,6** | **SEÑAL** |
| **diferencia de defensa** | +0,0261 | **7,0** | **SEÑAL** |
| **diferencia de ataque** | +0,0199 | **5,3** | **SEÑAL** |
| sólo el local cansado | +0,0110 | 3,0 | marginal |
| diferencia de descanso | +0,0006 | 0,1 | nada |
| sólo el visitante cansado | −0,0050 | 1,3 | nada |

**El desgaste no aporta nada**: el mercado ya lo tiene en el precio. Y el dato
va en contra de la intuición — cuando el local llega con ≤3 días de descanso y
el visitante con más, el local gana el **51,5 %** y el mercado decía 48,8 %
(n=3.401). El equipo «cansado» rinde POR ENCIMA de lo que la cuota espera.

### Pero correlación no es dinero

Con el protocolo del proyecto —elegir umbral en la primera mitad del histórico,
juzgar en la segunda, que no participa en la decisión—:

**Elección** (34.624 partidos, hasta 2023-08-19):

| umbral | n | acierto | decía el mercado | ROI | p5 |
|---|---|---|---|---|---|
| 0,5 | 9.755 | 56,7 % | 54,6 % | −2,95 % | −4,49 % |
| 1,0 | 4.571 | 60,9 % | 59,2 % | −4,34 % | −6,34 % |
| **2,0** | 491 | **73,7 %** | 69,5 % | **−1,14 %** | −5,99 % |

**Juicio** (34.623 partidos nunca usados para elegir), umbral 2,0:

> n=463 · acierto **71,7 %** contra el **68,8 %** que decía el mercado ·
> ROI **−2,90 %** · p5 **−8,01 %**

**VEREDICTO: RECHAZAR.**

Y fíjese en lo interesante: la señal **bate al mercado en las seis bandas**
(52,2 vs 50,7 · 56,7 vs 54,6 · 60,9 vs 59,2 · 66,2 vs 64,1 · 73,7 vs 69,5 ·
78,9 vs 76,5). No es ruido. Lo que pasa es que **2,9 puntos de ventaja no
cubren la comisión de la casa**, que ronda el 5-7 % en el 1X2.

Como control: apostar al local sin mirar nada da **−7,40 %**. La señal lo
mejora a −2,90 %, o sea que vale **4,5 puntos de ROI**. Sencillamente, no los
suficientes.

### La hipótesis que sí queda viva

Aquí está lo que estos dos frentes tienen en común, y es la única vía que veo
con aritmética a favor:

* la señal de forma aporta **+4,5 puntos** de ROI sobre apostar a ciegas,
* el line shopping con Unibet aporta **+3,64 %** de precio cuando gana.

Sumadas, la brecha con el break-even se cierra. **No está validado** —para
medirlo hace falta histórico de precios de VARIAS casas simultáneas, y hoy sólo
hay 219 partidos con precio múltiple— pero es una hipótesis con números
concretos detrás, y las fotos diarias la harán medible.

Lo que NO se hace: desplegar la señal ahora «porque tiene sentido». Su p5 es
−8,01 % y la regla de oro no se negocia.
