# v113 — Por qué el ROI sigue negativo, y qué falta exactamente

El usuario pidió buscar la variable que falta para que el ROI se vuelva
positivo. La respuesta no es una variable del modelo. Es **una casa**, y tiene
nombre.

---

## 1. El arbitraje del 40 % no es alcanzable con nuestras casas

La v112 midió que con las 18 casas de football-data el mejor precio deja el
margen en 1,0034 y **el 40 % de los partidos permite arbitraje**. Medido en
vivo sobre el tablón de hoy con **nuestras cinco casas** (Pinnacle, Bovada,
Playdoit, Unibet y DraftKings vía ESPN):

| | |
|---|---|
| partidos evaluados con 2+ casas | 108 |
| **arbitrajes (margen < 1,00)** | **0 (0,0 %)** |
| casi (margen < 1,02) | 2 (1,9 %) |
| **margen con el mejor precio de las nuestras** | **1,0574** |

Es decir: **el mejor precio de nuestras cinco casas no es mejor que la media
del mercado** (1,0550 histórico). La dispersión existe —Unibet gana el 52 % de
los lados— pero se compensa: cuando una casa es generosa en un lado es tacaña
en los otros, así que la suma no baja.

## 2. Quién genera de verdad el mejor precio

Sobre 16.210 partidos con cierre de 15 casas:

| casa | da el mejor precio | acceso |
|---|---|---|
| **Betfair Exchange (BFE)** | **35,4 %** | **no — 403** |
| Pinnacle | 27,3 % | sí, integrada |
| V (VC/Ladbrokes) | 12,1 % | no probada |
| Bet365 | 7,2 % | no |
| 1xBet | 5,0 % | no (404 en v71) |

Y el experimento que lo demuestra:

| escenario | margen medio | arbitrajes |
|---|---|---|
| todas las casas | 1,0071 | **22,88 %** |
| **sin Betfair Exchange** | 1,0168 | 12,12 % |
| sin BFE ni 1xBet | 1,0190 | 11,49 % |
| sólo Pinnacle | 1,0319 | 0,01 % |
| sólo Pinnacle + Bet365 | 1,0339 | 0,56 % |

**Quitar una sola casa —Betfair Exchange— reduce los arbitrajes a la mitad.**

## 3. Y esto tiene una explicación estructural, no es casualidad

Betfair Exchange **no es una casa de apuestas**: es un mercado donde los
usuarios apuestan entre sí. No tiene margen incorporado — cobra comisión sobre
las ganancias netas (2-5 % según el volumen). Por construcción, sus precios son
los más cercanos al justo, y por eso gana el 35 % de los lados.

Las casas tradicionales ganan cuando el apostante pierde, así que su precio
lleva margen. Un exchange gana igual pase lo que pase, así que no lo necesita.

**Esa es la variable que faltaba.** No está en los datos del partido: está en
dónde compras.

## 4. Qué hacer, concretamente

**Betfair Exchange tiene API oficial y documentada** (Betfair Exchange API),
con acceso por clave de aplicación. El 403 de nuestro sondeo es del endpoint
web, no de la API — que exige cuenta y `app key`.

Es una acción del usuario, no del proyecto: hay que **abrir la cuenta y
solicitar la clave**. Con ella:

* entra la casa que da el mejor precio en el **35 %** de los lados,
* el margen esperado baja de **1,0574 a ~1,02**,
* y los arbitrajes pasan de **0 %** a un orden del **12 %** (el escenario «sin
  BFE» al revés: con ella y sin las otras inaccesibles).

Sin esa cuenta, el resto es marginal: integrar más casas retail no mueve el
margen, porque todas llevan el suyo.

## 5. Lo que este documento NO dice

No dice que con Betfair el ROI sea positivo garantizado. Dice que:

1. el edge medido está en el precio, no en la predicción (v112: +1,37 % de ROI
   comprando al mejor precio, sin modelo);
2. ese mejor precio lo produce mayoritariamente **una casa concreta** que hoy
   no tenemos;
3. y con las que tenemos, el margen no mejora sobre la media del mercado.

Cualquier trabajo de modelo por delante de conseguir ese acceso es optimizar
la parte que ya se midió que no decide.
