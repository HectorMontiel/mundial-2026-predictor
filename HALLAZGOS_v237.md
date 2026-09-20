# v237 — La app llevaba seis horas congelada, y el culpable era un `git add`

Siete peticiones en un mensaje. Al ir a por la primera apareció algo que no
estaba en la lista y que las dejaba a todas en segundo plano.

---

## 0. Lo que nadie había pedido: el precálculo no se publicaba

El usuario preguntó por qué el aviso decía *«precios de hace 6 h 18 min»* si el
cron corre cada 3 h. La pregunta era correcta y la respuesta, peor de lo que
parecía.

El cron **sí corría**. Calculaba 164 pronósticos, escribía el fichero… y no lo
publicaba. En las anotaciones de la ejecución:

```
! git add del precalculo fallo
```

`git add a.json b.csv` falla **entero** si UNO de los paths no existe —*pathspec
did not match any files*— y no añade ninguno de los demás. Con el
`|| echo "::warning::…"` detrás, el workflow termina en verde sin haber
commiteado nada.

`ponches_snapshots.csv` sólo se crea los días que Pinnacle tiene props de
ponches abiertos. El día que no los hay, el `add` fallaba y **el precálculo
entero se quedaba sin publicar**. Lo añadí yo a esa lista en la v227.

**El arreglo** es un bucle que añade lo que existe y se salta lo que no, sin
tragarse un fallo real en los ficheros que sí están.

### Y el test que debía haberlo cazado

Existe `test_ningun_git_add_de_los_workflows_puede_fallar_callado`, nacido
porque esta familia de bugs ya había mordido dos veces. Cubría tres casos:

1. ningún path está en `.gitignore`
2. ningún `git add` termina en `|| true`
3. ninguna orden lleva un `\n` literal

Y se saltaba explícitamente el mío: `if not os.path.exists(p): continue`. Un
fichero que simplemente **no está ese día** no era ninguna de las tres.

Ahora hay una cuarta comprobación: si un `git add` lista varios paths, todos
tienen que estar versionados. Los que pueden faltar se añaden de uno en uno.
**Verificado devolviendo el workflow al estado roto**: el test falla y señala
`precalculo_dia.yml:121 -> ponches_snapshots.csv`.

---

## 1. El 16 % recomendado en tenis

La captura: **«GANA LORENA SCHAEDEL — 16 %»** como *apuesta recomendada*, con
la bolita en rojo, mientras la rival iba al 84 %.

No era un fallo de cálculo. Las dos candidatas fallaban el filtro —una por
probabilidad (16 % < 50 %), la otra por cuota corta (1,10 < 1,20)— así que se
entraba al **respaldo**, que ordenaba por `score`, o sea por EV:

```
Gana Lorena Schaedel   0,16 × 5,80 = 0,928   ← ganaba
Gana Gaia Maduzzi      0,84 × 1,10 = 0,924
```

El EV premia al que paga mucho, y el que paga mucho es el que casi nunca gana.
Ordenar por EV está bien **entre candidatas que ya pasaron el filtro**; en el
respaldo es una trampa, porque la pregunta ya no es «cuál paga mejor» sino
«cuál es más probable que ocurra».

Ahora el respaldo ordena por probabilidad. Ese mismo partido recomienda
**Gaia Maduzzi al 84 %**.

---

## 2. La MLB no daba ni una tarjeta

«Sin apuestas jugables» en los siete partidos del día. No era que no llegaran al
mínimo: **no había ni una candidata que juzgar**.

Los picks de MLB salen de comparar precios contra Pinnacle, y ese camino deja la
cuota en el propio pick (`apuesta` + `cuota`) sin rellenar `implicitas`. Y
`_de_dos_vias` se iba en su primera línea porque miraba sólo `implicitas`.

El precio existe y se conoce: es el del lado que el barrido eligió. Del otro no
se sabe nada y no se inventa, así que sale **una** candidata.

```
antes:  0 de 10 partidos con tarjeta
ahora:  10 de 10
```

---

## 3. Los totales, de dato a apuesta

La v229 llevó los totales al pick, pero `valor_apuesta` descarta toda candidata
sin cuota —y con razón: *«una probabilidad sobre algo que la casa no ofrece no
es una apuesta»*—. Así que carreras y puntos se quedaban dentro del desplegable
de análisis en vez de ser una tarjeta con la que armar un parlay.

Faltaba el precio. Y estaba en el mismo endpoint que el barrido ya consulta
para el moneyline:

```
mlb -> 24 partidos con escalera de totales
nfl -> 15 partidos
```

**Un detalle que podía salir muy caro:** en un `matchup` de partido los
participantes son los EQUIPOS, no Over/Under, así que la primera versión
devolvía cero. La tentación era usar el orden de `prices`. Pinnacle marca cada
lado con `designation: "over"/"under"`, y eso es lo que se usa: fiarse de la
posición es la lección del « @ » de la v77, que etiquetaba al visitante como
local y habría publicado el lado contrario con un EV inventado.

Resultado, con datos reales:

```
MLB   Carreras: Más de 7.5    65,0 %  cuota 1.787   score 1,16
NFL   Puntos: Menos de 50.5   62,5 %  cuota 1.98    score 1,24
```

---

## 4. Los textos que sólo ocupaban sitio

```
antes:  «Cuotas actualizadas: 2026-09-20 · partidos evaluados: 342 · ligas:
         liga_mx:5, mls:10, brasil:6, argentina:9, noruega:5, suecia:5,
         turquia:4, dinamarca:4, aut_bundesliga:3, gre_super_league:5,
         premier:4, laliga:5, serie_a:5, …»   (media pantalla)

ahora:  «Último refresco: 18:24 CDMX»
```

Y el bloque azul de tres renglones que explicaba por qué hoy no hay Pick del
Día. Salía casi todos los días, y un aviso que sale siempre deja de informar y
pasa a ser decorado. Cuando **sí** hay pick, el bloque verde sigue igual.

---

## 5. El smoke vuelve a ser usable

Costaba **horas**: el 2026-08-22 no terminó en 55 minutos en dos intentos, y en
esta tanda llevaba 1 h 43 min sin haber pulsado un solo botón. Eso lo sacó de la
puerta del push, y una puerta que no se usa no protege nada.

**Lo que se queda** —lo único que sólo él puede hacer, que es PULSAR:

| botón | por qué es imprescindible |
|---|---|
| NFL «Cargar» | el único que hace `st.rerun()` y reescribe `session_state`: el camino exacto del `KeyError: parlay_base` |
| Liga MX «Traer cuotas reales» | la única llamada a red bajo un botón |
| MLB «Proponer parlays» | el botón que dio origen al fichero. En UNA vista, no en cinco: es el mismo código |

**Lo que se va:**

- **«Enviar estos parlays»** ×3. Sin `TELEGRAM_BOT_TOKEN` —y no lo hay—
  `enviar()` devuelve `False` en su primera línea sin tocar la red: probaba un
  `if` que siempre toma la misma rama. Y con token puesto, **mandaría mensajes
  de verdad en cada pasada**. Coste sin cobertura y con riesgo.
- **Tenis, Internacionales, KBO y Leagues Cup**, que sólo CARGABAN la vista.
  Eso es literalmente lo que hace `valida_render`, y allí cuesta ~20 s.

```
smoke_botones    8 vistas → 3   (las que pulsan)
valida_render    4 vistas → 8   (las que cargan)
valida_render    TODO OK en 4 min 50 s
```

La cobertura no baja: un test comprueba que ninguna vista se haya caído de los
dos ficheros.
