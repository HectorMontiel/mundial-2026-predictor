# v112 — El histórico multi-casa ya existía, y responde la pregunta

El usuario pidió comprobar si ya había histórico de precios de varias casas
antes de esperar semanas a que las fotos diarias acumularan muestra. **Lo
había**, y estaba en la fuente que el proyecto descarga todos los días desde la
v68 sin usar esas columnas.

---

## 1. Dónde estaba

`football-data.co.uk` publica, por partido, **18 casas** más dos agregados:

```
B365  PS(Pinnacle)  WH  BW  1XB  BFE(Betfair Exchange)  ... y sus versiones
de CIERRE (B365C, PSC, WHC, 1XBC, BFEC...)
MaxC  = el MEJOR precio de cierre del mercado
AvgC  = la MEDIA del mercado
```

**20.325 partidos** en 12 ligas × 5 temporadas (2021-07 a 2026-05). El proyecto
ya baja estos CSV a diario para entrenar; `league_engine` lee `AvgCAHH` y
compañía, pero **`MaxC` y `AvgC` no los usaba nadie**.

No hacía falta esperar. El histórico llevaba ahí todo el tiempo.

## 2. La hipótesis de la v111 — FALSADA

La v111 dejó planteado que la señal de forma (+4,5 puntos de ROI) más el line
shopping (+3,64 % de precio) podrían cerrar la brecha. Medido con el protocolo
del proyecto —elegir umbral en la primera mitad cronológica, juzgar en la
segunda, p5 por bootstrap— sobre 19.425 partidos con señal calculable:

| precio | elección (umbral 1,0) | **juicio** | veredicto |
|---|---|---|---|
| media del mercado | −0,57 % · p5 −3,91 % | **−5,17 % · p5 −8,46 %** | RECHAZAR |
| casas tomables | +0,84 % · p5 −2,56 % | **−2,53 % · p5 −5,93 %** | RECHAZAR |
| MaxC (18 casas) | **+3,36 % · p5 −0,13 %** | **−2,21 % · p5 −5,61 %** | RECHAZAR |

Lo instructivo está en la última fila: en la mitad de ELECCIÓN el mejor precio
daba +3,36 % con el p5 casi en cero. Parecía la respuesta. En la mitad de
JUICIO —que no participó en elegir el umbral— da −2,21 %.

**Esa brecha es la firma del sobreajuste**, y es exactamente para lo que existe
el protocolo de dos mitades. Sin él, esto se habría desplegado como un hallazgo.

El line shopping sí ayuda —mueve el ROI de −5,17 % a −2,21 %, **casi tres
puntos**— pero la señal de forma no llega ni con ayuda.

## 3. Y la medición que sí importa: el precio, solo

Quitando el modelo y la señal, la pregunta limpia: **¿cuánto margen le queda a
la casa si compras al mejor precio?** Sobre los 20.325 partidos:

| precio | margen (suma de probabilidades implícitas) |
|---|---|
| media del mercado (AvgC) | **1,0550** — la casa se queda el 5,5 % |
| Pinnacle (la más eficiente) | 1,0311 — el 3,1 % |
| **mejor precio de las 18 (MaxC)** | **1,0034 — el 0,34 %** |

Y apostando al favorito del mercado, sin modelo ni señal:

| precio | ROI |
|---|---|
| media del mercado | **−2,65 %** |
| Pinnacle | −0,73 % |
| **mejor precio** | **+1,37 %** |

**Comprar al mejor precio convierte una propuesta perdedora en una ganadora, sin
predecir nada.** Recupera **5,16 puntos** de margen.

Y el dato que lo remata: **en el 39,99 % de los partidos (8.128 de 20.325) el
mejor precio deja el margen POR DEBAJO de 1** — arbitraje puro, cubriendo los
tres resultados.

## 4. Qué significa esto para el proyecto

Confirma sobre **20.325 partidos** lo que la v90 había medido sobre 219: el
edge está en el precio, no en la predicción. Y lo cuantifica.

**El techo y lo que capturamos.** MaxC es el mejor de 18 casas, muchas
inaccesibles a peticiones automáticas (ver el sondeo de la v111: FanDuel,
BetMGM y Betfair devuelven 403). Con las que sí podemos tomar la dispersión
medida es **+3,96 % frente al +5,61 % del techo**: capturamos alrededor de
**siete décimas del edge disponible**. Cada casa nueva que se integre acerca lo
uno a lo otro — y por eso la v111 metió Unibet.

**Lo que NO se hace.** Desplegar la señal de forma. Su juicio es −2,21 % con p5
−5,61 % incluso al mejor precio del mercado. La regla de oro no se negocia
porque el resultado sea decepcionante.

## 5. Lo que queda abierto, con su número

1. **Más casas accesibles.** Cada una acerca el precio real al techo. El salto
   de +3,96 % a +5,61 % son 1,65 puntos de ROI que hoy se dejan sobre la mesa.
2. **El arbitraje del 40 %.** Requiere poder tomar los tres lados en casas
   distintas y con límites suficientes. Es una operativa distinta a la de este
   proyecto, pero el dato está medido y ahí está.
3. **`MaxC`/`AvgC` como referencia permanente.** Ahora que se sabe que están,
   sirven para medir el canal de line shopping contra un patrón histórico real
   en vez de esperar a acumular fotos.
