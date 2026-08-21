# VALIDACIÓN v149 — el hueco que sí tenía precio, y tres diagnósticos de velocidad (dos equivocados)

Fecha: 2026-08-21

Dos quejas del usuario sobre la v148 en producción:

1. Partidos que siguen saliendo «sin pronóstico del modelo» en Apuestas del Día.
2. La pantalla tarda ~4 minutos en cargar.

---

## 1. «Sin pronóstico» no tenía por qué significar pantalla en blanco

### Lo que yo había respondido, y por qué estaba incompleto

En la v148 medí que los 7 partidos sin pronóstico eran un **límite externo**:
Coventry, Hull, Iraklis, Kalamata, Arezzo y Le Mans acaban de ascender y no han
jugado **ni un partido** en esa competición, así que no hay historia que
aprender en ninguna fuente. Eso es cierto y sigue siéndolo.

Lo que no hice fue la pregunta siguiente: **¿de verdad no hay nada que
enseñar?** Y sí lo hay. Esos partidos **tienen precio**. Y este proyecto tiene
medido, en el §0 de su propia bitácora, que el precio sabe más que el modelo:

| Hallazgo | Medición |
|---|---|
| Apostar la probabilidad del modelo pierde dinero | −4,66 % a −6,52 % · 37.158 apuestas |
| El modelo no bate al mercado | pierde en **25 de 33** ligas con referencia |
| Comprar al mejor precio sí gana | +11,49 % · p5 +1,73 % |

O sea que dejar el hueco en blanco mientras se tiene delante la probabilidad
implícita del mercado no es prudencia: es tirar el dato mejor de los dos.

### Lo que se hace ahora

Los partidos sin modelo llevan `board_mercado`: la probabilidad 1X2 implícita
de las cuotas del fixture, **con el margen de la casa quitado**
(`p_i = (1/c_i) / Σ(1/c_j)`).

No es una invención. Es un número observable —el que cotiza la casa— y va
etiquetado como tal para que nadie lo confunda con una salida del modelo:

* la barra se pinta atenuada y con borde discontinuo (`.tp-mercado`),
* lleva un sello **«mercado»** encima,
* el título de cada tramo dice «(mercado)»,
* y bajo el nombre de la liga aparece *«precio del mercado · el modelo no puede
  predecirlo»*, porque el título de un tramo no se lee en el móvil.

Además **ordenan junto a los demás**: `prob_lados` mira también
`board_mercado`. Si no lo hiciera, la lista les pintaría su barra y el orden
seguiría mandándolos al bloque de «sin pronóstico» del final — la pantalla
diciendo una cosa y el orden, otra.

Donde hay modelo **manda el modelo**: `board_mercado` sólo se usa si `board`
está vacío.

Medido sobre el barrido real:

```
sin_modelo = 7  ·  con barra de mercado = 7
```

Los siete. Incluidos los cinco que el usuario señaló.

---

## 2. Los cuatro minutos: tres diagnósticos, dos equivocados

Esta parte se cuenta entera, con los errores, porque el valor está en cómo se
descartaron.

### Punto de partida

```
POR RAMA (en producción van en paralelo, manda la más lenta)
   fútbol       169,9 s   ← el techo
   tenis         29,1 s · mlb 5,1 · nfl 4,3 · kbo 1,2 · nba 0,0
```

### Diagnóstico 1 (equivocado): «son los modelos»

Fue mi suposición de la v148, escrita sin medir. El perfil por actividad la
desmintió: cargar los 35 motores son **45,5 s de 211**, no el grueso.

### Diagnóstico 2 (equivocado): «es el emparejador de cuotas»

El perfil por actividad decía:

```
cuotas_multi (emparejador)   293,8 s   ← ¿el 70 %?
```

Memoricé las cinco funciones puras del emparejador (`normalizar`,
`categoria_efectiva`, `_sim_club`, `_sim_tenista`, `marca_estado`) — cambio
correcto y que se conserva, porque son puras y el resultado es idéntico. Pero
sólo bajó un 6 % de esa cifra. **No era ahí.**

### Diagnóstico 3 (equivocado): «son 354 peticiones HTTP en fila india»

Un contador por función lo señalaba sin ambigüedad:

```
_get                  321 llamadas   240,1 s   0,7478 s cada una
_buscar              1770 llamadas    17,8 s
consenso.disponible   321 llamadas     7,1 s
```

`cuotas_core_espn` hace una petición HTTP por partido. Las paralelicé… y el
reloj **no se movió**: 139,5 → 139,6 s.

**Por qué me equivoqué las tres veces: mi instrumento sumaba tiempo de hebras
que corren a la vez, y esa suma no es tiempo de reloj.** `_completar_cuotas` se
llama desde dentro de `fixtures_multi`, que ya abre una hebra por liga: esas
321 peticiones ya iban solapadas. 240 segundos «acumulados» cabían en 30 de
reloj.

### El diagnóstico bueno: medir el RELOJ por fases

```
RAMA FUTBOL (reloj): 128,8 s
   _barrido_fixtures (bucle por liga)   128,8 s   (100 %)
   fixtures_multi (incl. cuotas)         29,8 s   ( 23 %)
```

El bucle por liga es el **100 %** de la rama, y dentro de él, en serie:

```
carga de modelos    50,0 s   (35 motores, 0,5-3,5 s cada uno)
predicciones        51,0 s   (286 predicciones)
```

### Y el intento de arreglarlo, que también falló — con su medición

Cargar el modelo de las tres ligas siguientes mientras se predice la actual,
con el adelanto **acotado** para no repetir el problema de memoria de la v86.
Se midió antes el precio: **~46 MB por motor residente** (marginal; el primero
suma 215 MB porque arrastra numpy, sklearn y xgboost), así que cuatro vivos en
vez de uno son +140 MB sobre los 1.297 MB medidos en la v86 — un 11 %,
asumible.

Resultado:

```
bucle secuencial (referencia)   128,8 s
con adelanto de 3 motores       160,1 s   · pico 902 MB
```

**Peor.** Descomprimir y deserializar un `.joblib` es trabajo **con el GIL
tomado**: `zlib` lo suelta, pero el *unpickle* que reconstruye el ensemble no.
La hebra que carga no se solapa con la que predice — la bloquea, y encima se
pagan los cambios de contexto.

Revertido, y la medición queda escrita en el propio `alpha_finder` para que
nadie vuelva a intentarlo.

### Lo que sí quedó

```
                        antes     después
rama de fútbol         169,9 s    129,6 s     (−24 %)
fixtures_multi          41,3 s     29,8 s
pico de memoria            —      654 MB      (v86 midió 1.297)
```

De la memorización de funciones puras y de paralelizar `_completar_cuotas`
(a **cuatro** hebras, no ocho: `fixtures_multi` ya abre una por liga, así que
el multiplicador real es 49 × N).

### Lo que NO se consiguió, y qué haría falta

**No hay «segundos» en el arranque en frío.** Quedan ~129 s que son 50 s de
cargar modelos más 51 s de predecir, en serie, y está demostrado que repartirlo
con hilos empeora. Para bajar de ahí hay que **reducir el trabajo**, no
repartirlo:

* guardar los `.joblib` **sin comprimir** dentro del asset del Release, que ya
  va gzipado — mismo tamaño de descarga, sin el coste de `zlib` en cada carga;
* cargar `reg_local`/`reg_visit`/`mesm` **sólo cuando se usen**, en vez de en
  el `__init__` de `ClubEngine`.

Las dos cambian artefactos y rutas de carga, así que son su propia versión con
su propia tanda de validación, no un parche.

**Lo que sí cambia la experiencia real** es la caché de la v148: ese minuto y
medio ocurre **una vez por contenedor** y sólo si la caché pasa de una hora. El
resto de las veces la pantalla aparece en 0,004 s.

---

## Lecciones

* **Sumar tiempo de hebras concurrentes no es medir tiempo de reloj.** Tres
  diagnósticos seguidos salieron mal por eso. Para encontrar un cuello de
  botella hay que cronometrar FASES, no acumular por función.
* **Un hueco honesto puede seguir siendo un desperdicio.** «El modelo no puede
  predecirlo» era verdad y aun así la pantalla estaba tirando el dato que sí
  tenía y que, además, está medido como mejor que el modelo.
* **Los hilos no arreglan lo que retiene el GIL.** Descomprimir un modelo no se
  solapa con predecir; hay que reducir el trabajo, no repartirlo.
* **Una optimización sin medición posterior es una apuesta.** Dos de los tres
  cambios de rendimiento que probé hoy no sirvieron, y sólo el reloj lo dijo.

---

## Ficheros tocados

| fichero | qué |
|---|---|
| `alpha_finder.py` | `board_mercado` en los partidos sin modelo · la medición del adelanto de motores, escrita para no repetirlo |
| `render_todos_partidos.py` | barra de mercado con sello y nota · el orden mira `board_mercado` |
| `cuotas_multi.py` | cinco funciones puras memorizadas |
| `fixtures_espn.py` | `_completar_cuotas` en cuatro hebras |
| `_v149_perfil_barrido.py` | **nuevo** — perfil por rama y por actividad |
| `_v149_perfil_cuotas.py` | **nuevo** — cProfile dentro de `cuotas_partido` |
