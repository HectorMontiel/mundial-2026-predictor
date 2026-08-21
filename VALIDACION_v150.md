# VALIDACIÓN v150 — el relleno que se delata, y dos tests que no se ejecutaban

Fecha: 2026-08-21

---

## 1. La premisa del encargo no se sostenía, y hay que decirlo antes de actuar

El encargo pedía, con prioridad alta, reentrenar porque *«muchas ligas
importantes (Premier, LaLiga, Ligue 2, Serie A) han dejado de generar
pronósticos propios»* y *«la app está usando la probabilidad implícita del
mercado como fallback para estos partidos»*.

Se midió antes de tocar nada. Estado real, partido a partido:

```
321 fixtures · 314 con pronóstico del modelo (97,8 %) · SIN MOTOR: ninguna

   LaLiga     9 / 9      Serie A   10 / 10     Ligue 2   9 / 9
   Primeira   7 / 7      Premier    8 / 10
```

Los 42 motores cargan (`listo=True`). Ninguna competición ha dejado de generar
pronósticos: son **7 partidos sueltos de 321**, repartidos por cuatro ligas
que producen pronóstico para todos los demás.

Y los 7 tienen una única causa, que no es el desacople ni los `.joblib`:

```
premier           Coventry City · Hull City
ita_serie_b       Arezzo · Hellas Verona
gre_super_league  Iraklis · Kalamata
ligue_1           Le Mans
```

**Siete equipos recién ascendidos que no han jugado ni un partido en esa
competición.** No hay historia que entrenar, ni en football-data —que todavía
no publica E0, F1, I2 ni G1 de 2026-27— ni en ESPN, que sólo tiene resultados
de partidos jugados. Un reentrenamiento forzado no cambiaría un solo dígito:
no existe el dato. Se resolverán solos cuando la fuente publique, sin tocar
código, porque la lista de temporadas ya los pide (v148).

Así que no se reentrenó. Reentrenar 42 modelos para arreglar algo que no está
roto habría costado una hora de runner y habría dejado el problema real —el de
abajo— sin tocar.

---

## 2. Lo que SÍ era un riesgo, y no estaba cubierto

La preocupación de fondo del encargo era correcta aunque el diagnóstico no lo
fuera: **el fallback de mercado puede tapar un fallo del modelo.**

Y en la v149 lo dejé peligroso sin darme cuenta. Antes, un partido sin modelo
mostraba un hueco. Ahora muestra la probabilidad implícita del mercado. Eso es
mejor para el usuario —el precio sabe más que el modelo, §0 de la bitácora—
pero cambia el modo de fallo de forma sutil y grave:

> **Un hueco se ve. Un relleno no.**

Si mañana una liga entera dejara de cargar su modelo, la pantalla se vería
**perfectamente normal**: barras llenas, números plausibles, semáforo pintado.
Y el corazón de la aplicación apagado sin que nadie lo notase. Es exactamente
el modo de fallo de la v106 —doce competiciones desaparecidas en silencio—
sólo que ahora con mejor disfraz.

### El arreglo: que el relleno se delate

`alpha_finder.avisos_sin_modelo(pronosticos)` recorre los pronósticos de fútbol
y avisa por competición cuando el mercado está TAPANDO al modelo:

```
⚠️ **premier**: 4 de 10 partidos salen con el precio del mercado porque el
   modelo no los cubre. Con esa proporción no son ascensos: revisa que su
   modelo cargue y que su catálogo de nombres esté al día.
```

Además, cada relleno deja su línea de log con liga, partido, motivo y si pudo
o no taparse con precio:

```
[alpha/fix] sin modelo · premier · Arsenal vs Coventry City ·
   Coventry City no ha jugado todavía en esta competición (recién ascendido)…
   · se enseña el precio del mercado
```

### El umbral, y por qué no es cero

Un tercio de la competición, con un mínimo de tres partidos de muestra.

**No avisar por debajo es deliberado.** Que falten dos de diez en la Premier es
lo normal en agosto: son los ascendidos. Si la alarma saltara por eso, saltaría
todos los días de agosto y nadie volvería a leerla — y entonces el día que una
liga caiga de verdad, tampoco. Una alarma que salta siempre no es una alarma.

El mínimo de tres partidos existe porque en una competición con dos, uno sin
modelo ya es el 50 % y no significa nada.

### Verificado por los dos lados

Una alarma sólo sirve si además **calla cuando debe**:

| caso | esperado | resultado |
|---|---|---|
| premier 2 de 10 (los ascendidos reales de hoy) | calla | ✅ 0 avisos |
| muestra de 2 partidos, 1 sin modelo | calla | ✅ 0 avisos |
| premier 4 de 10 | avisa | ✅ 1 aviso, con nombre |
| laliga 9 de 9 (liga entera caída) | avisa | ✅ 1 aviso, con cifra |
| sin partidos | calla | ✅ 0 avisos |

Y contra el barrido real de hoy: 293 partidos de fútbol, 7 sin modelo,
**0 incidencias** — que es lo correcto.

La lógica se extrajo a una función de módulo precisamente para poder probarla
**sin pagar un barrido de dos minutos** ni depender de la red.

---

## 3. Dos tests que llevaban sin ejecutarse

Al enganchar el test nuevo apareció que este fichero **no descubre los tests:
los llama a mano** en el bloque de arranque. Añadir una función `test_*` y
olvidar la línea de llamada produce un test que existe, se lee, y **nunca
corre**. La suite termina en «TODO OK» y nadie se entera.

Auditado con AST:

```
tests definidos: 109 · llamados: 107
NO SE EJECUTAN: test_el_fallback_de_mercado_se_delata   (el mío, recién añadido)
                test_metricas_con_procedencia           (preexistente)
```

`test_metricas_con_procedencia` llevaba definido y sin llamar. Los dos quedan
enganchados.

Y para que no vuelva a pasar, `test_ningun_test_se_queda_sin_ejecutar` audita
el propio fichero con AST y falla si aparece un huérfano. Es la misma familia
de trampa que ya está escrita en la bitácora —«un test que no encuentra su
fichero devuelve exit 0, comprobar que CORRIÓ»— sólo que aquí el que no corre
es el test mismo.

Tras el arreglo: **110 definidos, 0 huérfanos.**

---

## 4. Qué se enseña, y de dónde sale

Queda documentado en el código, porque es la pregunta que un usuario se hará
mirando la pantalla:

| situación | qué se pinta | cómo se distingue |
|---|---|---|
| el modelo predice | barra normal | sin marca |
| el modelo no puede | barra del **mercado** | atenuada, borde discontinuo, sello «mercado», «(mercado)» en el título de cada tramo, y nota bajo la liga |
| ni modelo ni precio | hueco | «sin pronóstico del modelo» |

**Donde hay modelo, manda el modelo.** `board_mercado` sólo se usa si `board`
está vacío; nunca lo sustituye.

---

## Lecciones

* **Medir antes de reentrenar.** El encargo pedía con prioridad alta arreglar
  algo que no estaba roto. Una hora de runner y el problema real intacto.
* **Un relleno honesto puede ser más peligroso que un hueco**, porque el hueco
  se ve y el relleno no. Cada vez que se sustituye un «no sé» por una
  estimación razonable, hay que preguntarse quién se dará cuenta si la
  estimación empieza a taparlo todo.
* **Una alarma que salta siempre no es una alarma.** El umbral se elige para
  que calle en el caso normal medido, no para que no se escape nada.
* **Un test que no se llama pasa siempre.** Peor que no tenerlo, porque da
  confianza falsa.

---

## Ficheros tocados

| fichero | qué |
|---|---|
| `alpha_finder.py` | `avisos_sin_modelo()` · log por partido con motivo |
| `test_catalogo_y_cuotas.py` | test del aviso (5 casos) · guardia de tests huérfanos · engancha los dos huérfanos |
| `CONTEXTO_TRASPASO.md` | el aviso de «medirlo antes de reentrenar» |
