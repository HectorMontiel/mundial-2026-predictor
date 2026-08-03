# VALIDACION v94 — El tenis usaba media fuente, y ya nada se entrena a mano

Fecha: 2026-08-03 · Suites: test_catalogo_y_cuotas ✅ · test_simetria ✅ ·
test_match_parlay ✅ · smoke_botones ✅ · test_concurrencia ✅ (TODO OK las 5)

Cuatro encargos. Dos eran bugs reales con la misma raíz —se estaba usando media
fuente en tenis—, uno se cierra con la última pieza de automatización, y el
cuarto se **rechaza con números** tras comprobar que su premisa era falsa.

---

## 1. La vista de tenis mostraba 1 partido de los 41 que hay

**Síntoma**: al elegir la competición Tenis salía un único próximo partido,
con decenas jugándose ese mismo día.

**Causa, rastreada hasta el dato**: el calendario sólo miraba el scoreboard de
ESPN, que sirve el cuadro principal de ATP/WTA. Y ahí la mayoría de los
partidos futuros son **TBD vs TBD** — rondas cuyo emparejamiento aún no
existe. Medido en ATP a 10 días vista:

```
competiciones de individuales no jugadas   128
   con los dos jugadores definidos           1
   TBD vs TBD                              127
```

El filtro que las descartaba era **correcto** (no se puede mostrar un partido
entre dos desconocidos). Lo que faltaba era la segunda fuente: el tablón de
cuotas, que trae challengers e ITF y sólo lista partidos con los dos jugadores
puestos — una casa no cotiza un TBD. Medido el mismo día: **96 partidos, 74 con
los dos jugadores en el catálogo del modelo**.

Es exactamente el patrón que el fútbol usa desde la v71 (ESPN para el
calendario, `cuotas_multi` para completar), aplicado al tenis.

```
                antes    después
ATP jugables        1         41
WTA jugables        —         33
```

Y un bug de paso: **Bovada fecha en milisegundos epoch** y Pinnacle en ISO. Sin
distinguirlos, `pd.to_datetime` interpretaba el epoch como nanosegundos y todos
los partidos de Bovada caían en **1970-01-01**. Corregido: hoy queda repartido
en 2026-08-03 (14 ATP + 15 WTA), 08-04 y 08-05.

## 2. El marcador por sets ya estaba ahí

Se propuso «investigar una fuente complementaria (p. ej. TennisAbstract)» para
poder liquidar los mercados derivados. No hace falta: **ESPN ya publica el
marcador set a set** en `linescores` de cada competidor, y sólo faltaba
leerlo. Medido: **188 de 189 partidos (99 %)** lo traen.

```
['Bernard Tomic', 'Miguel Tobon'] → ganó Tomic · sets [2,1] · 35 juegos
    [[5,6,7],[7,4,6]]
```

`resultados_tenis` devuelve ahora `sets` y `juegos_totales`, y el liquidador
resuelve total de juegos y marcador por sets además del ganador. Sólo cuando
los dos jugadores tienen el mismo número de sets: un abandono deja las listas
descuadradas y liquidar con eso daría un total falso.

## 3. Ya nada se entrena a mano

El workflow diario sólo hacía `league_engine --build`, que es **fútbol**. MLB,
tenis (ATP y WTA) y NBA se reentrenaban a mano y sus modelos llevaban **5-7
días** de retraso: el sistema predecía la MLB de agosto con el estado de julio.

Los tres motores ya traían su CLI de entrenamiento; sólo faltaba llamarla.
Verificado de punta a punta antes de automatizar:

```
NBA    OK · precisión 0,6664 (línea base ELO) · log-loss 0,6128
MLB    OK
Tenis  OK · precisión 0,6277 · log-loss 0,6425
```

Con el mismo blindaje que el fútbol tiene desde la v68: si un modelo no vuelve
a cargar después de reentrenar, se restaura su versión anterior desde git y el
resto sigue. **Nunca se commitea un artefacto que no abre.**

Con esto la autonomía es completa: modelos (diario) + calibraciones (semanal,
v93) + liquidación (diario, v92) sin intervención manual.

## 4. RECHAZADO con números — bajar el `w` de tenis y MLB

Se propuso «calcular un peso de calibración w para tenis y MLB, similar al
fútbol», dando por hecho que no se aplica ninguno.

**La premisa es falsa.** El encogimiento SÍ se aplica: `alpha_finder` encoge el
tenis con `calibracion_segura.encoger_dos_vias` (línea 1136) y `mlb_engine`
hace lo propio (línea 580), los dos con w=0,25. Y la MLB además tiene su peso
**medido** en `calibracion_mercado.json` (n=7.541, Δlog-loss +0,0136,
Δprecisión +0,0152).

Lo que sí faltaba era un w medido para ATP/WTA, que caen al global. Y había
motivo para mirarlo: la medición de producción de la v93 dice que el tenis
sigue sobreconfiando (promete 77,2 %, acierta 70,7 %). Así que se midió, con
elección en los pliegues 0-2 y juicio en los 3-4:

```
ATP (30.279 partidos)        logloss   precisión      ECE     ROI       p5
  PRODUCCIÓN w=0,25          0,59157     68,23 %   0,0154  −4,28 %  −5,46 %
  medido      w=0,00         0,58952     68,05 %   0,0077  −4,15 %  −5,38 %

WTA (15.865 partidos)
  PRODUCCIÓN w=0,25          0,58736     67,94 %   0,0237  −3,55 %  −5,24 %
  medido      w=0,00         0,58446     68,33 %   0,0176  −3,85 %  −5,61 %
```

El óptimo medido es **w=0,00** en los dos circuitos: «usa sólo el mercado, el
modelo no aporta». Y ahí está el punto — `calibracion_mercado` tiene un **suelo
de diseño `W_MIN = 0,25`**, puesto a propósito y ya medido en la v75, porque
por debajo «la app sería un espejo de Pinnacle y no aportaría nada».

O sea: **el peso que se aplica hoy ya es el más bajo que el diseño permite**, y
lo que se ganaría bajando más es +0,002/+0,003 de log-loss, precisión que se
queda igual (−0,18 pp en ATP, +0,39 pp en WTA) y ROI que **no mejora** (ATP
+0,13 pp, WTA −0,30 pp). No se adopta.

La sobreconfianza que sí se ve en producción se corrige donde corresponde y ya
está hecho: `calibracion_confianza` ajusta por banda lo que se muestra, y la
v93 lo llevó también al Pick del Día.

## 5. Qué queda abierto

- **Backtest de line shopping en Goles/BTTS**: el dato se acumula desde la v90;
  el protocolo 70/30 con bootstrap necesita miles de apuestas.
- **Las 11 ligas sin cuotas**: vía prospectiva a 28 partidos/día (~4 meses).
- Liquidación de fútbol al 38 %: el resto son partidos de hoy sin jugar y
  ligas cuyo scoreboard de ESPN no cubre el histórico completo.
