# VALIDACIÓN v151 — el modelo sin comprimir, y por qué «< 15 s» no es alcanzable

Fecha: 2026-08-21

El encargo daba luz verde a *«guardar los `.joblib` sin comprimir y cargar los
regresores bajo demanda»* describiéndolo como *«la última pieza para que el
arranque en frío baje de 129 segundos a menos de 15»*.

Una de las dos cosas se hace. La otra se descarta con números. Y el objetivo,
tal como está planteado, **no es alcanzable** — eso también con números,
porque es lo más útil que puedo aportar aquí.

---

## 1. Dónde está el coste de construir un `ClubEngine`

Medido artefacto a artefacto sobre premier, laliga y argentina:

```
modelo.joblib       7,52 s   96 %
reg_local.joblib    0,15 s    2 %
reg_visit.joblib    0,13 s    2 %
escalador.joblib    0,00 s    0 %
```

**La carga perezosa de los regresores se descarta.** Ahorraría dos segundos de
cincuenta y añadiría un camino de código condicional que puede fallar en
producción. No compensa. Todo el coste está en un solo fichero.

---

## 2. El modelo sin comprimir

Comparación justa: se reserializa el **mismo objeto** en la misma máquina, así
que lo único que cambia entre las dos variantes es la compresión. Cuatro
modelos, tres cargas cada uno, se queda la mejor:

| variante | MB en disco | carga | **en `tar.gz`** |
|---|---|---|---|
| zlib-3 (antes) | 12,0 | 2,68 s | 11,9 MB |
| sin comprimir | 32,8 | 2,07 s | **11,2 MB** |

**1,29× más rápido**, y la última columna es la que justifica el cambio: desde
la v148 el modelo viaja al contenedor **dentro de un `.tar.gz`**, o sea ya
comprimido por fuera. Comprimirlo también por dentro no ahorraba ni un byte de
descarga —el tar sale incluso algo más pequeño sin la doble compresión— y se
pagaba `zlib` en cada arranque.

El precio es disco en el contenedor. Medido sobre los 37 modelos reales:
**712 MB → 1.239 MB (1,7×)**. Con ~20 competiciones bajadas por barrido son
~430 MB en vez de ~250.

`joblib.load` lee los dos formatos, así que los modelos comprimidos ya
publicados siguen abriendo mientras el bot no los reemplace. No hay transición
que gestionar.

### Cuánto vale de verdad, y una salvedad honesta

En el barrido local, la fase de carga pasó de **50,0 s a 25,7 s**. Pero **parte
de esa mejora es un artefacto de Windows**: aquí `modelos_portables.cargar`
repara el booster serializado en Linux, y al reserializar en local ese trabajo
desaparece. En producción (Linux) esa reparación no existe, así que la ganancia
esperada es la medida sobre objetos idénticos: **1,29×, unos 11 s de 130**.

Se deja escrito para que nadie lea «−24 s» y lo dé por bueno en producción.

---

## 3. Por qué «menos de 15 segundos» no es alcanzable

Desglose del arranque en frío de la rama de fútbol, medido cronometrando fases
secuenciales (dentro del bucle por liga acumular SÍ es tiempo de reloj, porque
no hay hebras; ése fue el error de la v149):

```
fixtures + cuotas por partido    29,8 s    red, ya paralela
cargar 35 modelos                50,0 s
286 predicciones                 51,0 s
                                --------
                                130,8 s
```

Y la aritmética de lo que se puede quitar:

| escenario | total |
|---|---|
| hoy | 130,8 s |
| con el modelo sin comprimir (1,29×) | **119,6 s** |
| si la carga fuera CERO (techo imposible) | 80,8 s |
| si además las predicciones fueran CERO | **~30 s** |
| objetivo pedido | < 15 s |

**Aunque se eliminara por completo la carga de modelos quedarían 81 segundos.**
Y aunque además se eliminaran las predicciones, quedarían ~30: esos 30 son la
red pidiendo **precios frescos** de 320 partidos, y un precio no se puede
precalcular sin mentir sobre él.

O sea: el suelo con precios reales está en **~30 s**, no en 15. Decirlo ahora
vale más que perseguirlo tres versiones.

### Lo que sí llevaría de 130 s a ~30 s

Precalcular las predicciones del modelo en el bot. Los 50 s de cargar y los 51
de predecir existen porque la aplicación recalcula en cada arranque algo que
**no cambia en todo el día**: el 1X2 de un partido es función del `team_stats`
y del modelo, y los dos sólo cambian cuando corre el bot. Es el mismo principio
de la v148 —«el pronóstico se puede servir de caché; el precio, no»— movido a
donde es gratis.

**No se hace en esta versión**, y por una razón concreta que hay que resolver
antes: `ClubEngine.predecir` consulta `odds_actuales.json` para el MESM y el
blend de mercado, así que su salida **puede** depender de cuotas intradía. Hoy
ese fichero no existe ni está versionado —verificado— y por eso ninguna de las
dos ramas se activa, pero precalcular sin comprobar primero si eso es cierto
también en producción sería congelar una predicción que se suponía viva.

Es su propia versión, con esa comprobación por delante.

---

## 4. Un test que fallaba por comparar lo que no debía

La suite cazó un fallo durante esta tanda:

```
1 FALLOS
  - Playdoit y Pinnacle coinciden en el bando local en MLB (1 invertidos de 16)
```

`test_orientacion_local_visitante` protege un bug real y caro de la v77: en MLB
el evento se llama «VISITANTE @ LOCAL», al revés que en fútbol, y fiarse del
orden invertía **todos** los partidos de béisbol generando picks del equipo
equivocado con un EV inventado del +49 %.

Pero lo comprobaba mirando los **precios**: si el `home` de una casa se parecía
más al `away` de la otra, lo contaba como invertido. Y esa heurística no sabe
distinguir «los bandos están al revés» de «las dos casas discrepan sobre quién
es favorito». El caso que lo tumbó:

```
baltimore orioles|tampa bay rays
   pinnacle  home 2,16  away 1,78    (favorito: Tampa Bay)
   playdoit  home 1,83  away 2,00    (favorito: Baltimore)
   nombres   Baltimore Orioles / BAL Orioles  →  el MISMO bando local
```

Los bandos estaban bien. Las casas simplemente no coincidían en el favorito,
que en la MLB pasa constantemente porque el moneyline se mueve fuerte con el
abridor.

**El nombre es la verdad; el precio es un indicio, y encima uno sobre el que
las casas tienen derecho a discrepar.** Ahora se comprueba que el equipo que
cada casa declara como local sea el mismo.

Y se verificó que el cambio **no debilita** el test, que era el riesgo:

| escenario | esperado | resultado |
|---|---|---|
| bandos invertidos (el bug de la v77, simulado) | falla | ✅ 1 fallo |
| bandos correctos con precios discrepantes | pasa | ✅ 0 fallos |

---

## Lecciones

* **El 96 % del coste estaba en un fichero de cuatro.** Medir antes de repartir
  esfuerzo evitó añadir carga perezosa a tres artefactos que no costaban nada.
* **Comprimir dentro de algo que ya va comprimido es trabajo puro.** El
  `tar.gz` de la v148 convirtió el `compress=3` en un coste sin
  contrapartida, y nadie lo revisó al cambiar el transporte.
* **Un objetivo hay que comprobar que es alcanzable antes de aceptarlo.**
  «< 15 s» no lo era, y decirlo con la aritmética delante ahorra más tiempo que
  cualquier optimización.
* **Una mejora medida en Windows puede no serlo en Linux.** La reparación de
  plataforma de la v87 infla aquí la ganancia; el número que vale es el de
  objetos idénticos.
* **Un test que infiere de un indicio acaba dando falsos positivos.** El de la
  orientación miraba precios para deducir bandos, y las casas tienen derecho a
  discrepar de precio. Al comprobar el nombre —que es el dato— el test queda
  más fuerte, no más débil: se verificó que sigue cazando la inversión real.

---

## Ficheros tocados

| fichero | qué |
|---|---|
| `league_engine.py` | `modelo.joblib` se guarda con `compress=0` |
| `test_catalogo_y_cuotas.py` | la orientación local/visitante se comprueba por NOMBRE, no por precio |
