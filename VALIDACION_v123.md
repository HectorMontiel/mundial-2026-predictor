# v123 — Las estadísticas que faltaban en el cruce, los tiempos con precio, y dos fallos viejos

Cuatro peticiones del usuario, y por el camino dos fallos de producción que
llevaban desde la v114 sin dar la cara.

> «Algo que no veo en los cara a cara son estadísticas como tarjetas, córners,
> etc. Agrégalo.»

> «En partidos que sean parejos deberías también evaluar en el modelo no irte
> tanto por un ganador si no ver si es mejor irte por doble oportunidad.»

> «También empezar a ver combinadas de corners, tarjetas, tiempos, etc.»

> «En tenis ver en los h2h o en las demás stats históricas ver cuántos juegos
> se jugaron para irte por ahí en la apuesta.»

---

## 1. Córners y tarjetas en el cara a cara

El dato estaba en el repositorio desde siempre. Medido sobre los 74 históricos:

```
67 de 74 ficheros traen home_corners
66 de 74 traen home_yellow / home_red / home_shots_on / home_possession
donde la columna existe, la cobertura es del 100 % (147.811 partidos)
```

Lo que faltaba no era el dato: era leerlo. `panel_equipos.h2h` devolvía sólo
goles.

Ahora devuelve, de los cruces entre los dos equipos: media de córners, de
tarjetas (amarillas + rojas, que es lo que cotizan las casas), de remates a
puerta, de posesión y de goles esperados — cada una con el reparto por equipo —
y el **porcentaje histórico por encima de cada línea de mercado** (8.5, 9.5 y
10.5 córners; 3.5, 4.5 y 5.5 tarjetas). Además, cada partido de la tabla lleva
ya sus propias cifras: un 1-1 de 16 córners y otro de 4 dejan de parecer el
mismo partido.

Medido en Pumas–Querétaro (15 cruces):

| | media | Pumas | Querétaro | rango |
|---|---|---|---|---|
| córners | 8,67 | 3,53 | 5,13 | 4 – 16 |
| tarjetas | 3,53 | — | — | 1 – 5 |
| remates a puerta | 6,27 | 2,73 | 3,53 | 3 – 11 |
| posesión | — | 51,9 | 48,1 | — |

Y las líneas: más de 8.5 córners el **53 %** de las veces, más de 3.5 tarjetas
el **60 %**.

**La posesión no publica un total** — sumaría 100 siempre y no informaría de
nada. Es un detalle, pero es la clase de cifra que llena una pantalla sin decir
nada.

**El aviso viaja con el dato**: quince partidos son quince datos. La pantalla lo
dice y añade lo que importa para decidir: **ninguna de las seis casas del tablón
publica precio de córners ni de tarjetas**, así que esto es contexto del cruce,
no una apuesta que se pueda montar desde aquí.

---

## 2. Combinadas de córners, tarjetas y tiempos: qué se puede y qué no

Se comprobó antes de construir nada. Sobre Monterrey vs Juárez, de los **148
mercados con precio** que publica Playdoit:

```
córners  ............  0
tarjetas ............  0
tiempos (mitades) ... 12
```

Así que de las tres familias que pedía el usuario, **sólo los tiempos tienen
precio**. Montar combinadas de córners con cuota justa sería inventar el
precio, y eso es justo lo que este proyecto no hace.

### Los tiempos sí entran, y con precio real

La v122 los descartaba todos por una razón buena: sus etiquetas son idénticas a
las del partido completo, así que «1ª Mitad · Más de 1.5» le habría robado el
precio al «Más de 1.5 goles» del partido entero. La solución no era tirarlos:
era ponerles el prefijo con el que la plantilla los nombra.

Resultado: **20 mercados de mitad más**, de 49 a **69** cruzados con el modelo
en ese partido.

### Pero su EV va marcado como NO FIABLE, y aquí está el porqué

Al conectarlos apareció esto:

```
1ª mitad: gana Monterrey   46,7 %      2ª mitad: gana Monterrey   46,7 %
1ª mitad: más de 0.5 goles 77,1 %      2ª mitad: más de 0.5 goles 77,1 %
1ª mitad: ambos marcan Sí  24,3 %      2ª mitad: ambos marcan Sí  24,3 %
```

**El modelo da exactamente la misma probabilidad a las dos mitades.** Medido en
4 de 4 partidos de Liga MX. El reparto de goles por mitad (`G2H_MA5`) no está
llegando, así que `f1h` y `f2h` valen 0,5.

En el fútbol real se marca alrededor del **55 %** de los goles en la segunda
parte. Esa simetría es falsa, y todo EV que salga de ella también: el «2ª mitad:
menos de 1.5 goles @ 1,95 → EV +10,4 %» no mide valor, mide lo que al modelo le
falta.

Así que los mercados **entran con su precio** —que es real y sirve para armar un
boleto en una sola casa, que es para lo que se pidieron— **y con el EV marcado**.
`recomendar_combinada` los penaliza igual que a un EV sospechoso, y la pantalla
lo explica con estas palabras.

---

## 3. Partidos parejos: ganador o doble oportunidad

Lo que **no** se hace: decir que la doble oportunidad tenga valor. No hay
ninguna medición en este proyecto que lo respalde.

Lo que **sí** se mide, con los precios delante y sin depender de que el modelo
acierte:

1. cuánta probabilidad más cubres al pasar de «Gana X» a «X o Empate»;
2. cuánta cuota pagas por esa cobertura;
3. **qué margen cobra la casa en cada uno de los dos mercados.**

El punto 3 es el que casi nadie mira. Y hay un detalle que, mal hecho, engaña:
cada opción de doble oportunidad cubre **dos** de los tres resultados, así que
en un libro sin margen sus probabilidades implícitas suman 2, no 1. El margen es
`suma / 2 − 1`. Sin esa corrección parecería que la doble oportunidad cobra el
doble de lo que cobra, y la pantalla estaría empujando al mercado equivocado.
Hay un test que lo fija con un libro sintético de margen cero.

Medido en Monterrey vs Juárez, con precios de Playdoit:

```
margen del 1X2 ................. 6,98 %
margen de la doble oportunidad . 7,02 %
```

Prácticamente el mismo: cubrir el empate no cuesta margen extra en esa casa, así
que la decisión es sólo de cuánto riesgo se quiere. Cuando la diferencia pasa de
1,5 puntos, la pantalla lo dice con un aviso.

El partido se declara parejo con dos criterios objetivos: que el favorito no
llegue al 45 % —donde deja de haber un resultado que gane más de la mitad de las
veces— o que los dos equipos estén a menos de 12 puntos.

---

## 4. Tenis: cuántos juegos duran los partidos

El dato estaba en el histórico unificado que ya usa el motor: la columna
`Score`, con el marcador set a set y **cobertura del 100 %**.

```
ATP  354.250 partidos leídos · 11.236 marcadores ilegibles (retiros)
WTA  319.842 partidos leídos · 10.216 ilegibles
```

Los retiros se descartan a propósito: un «6-3 2-1 RET» contado como partido
terminado bajaría la media de todo el circuito.

### Lo que casi sale mal: mezclar formatos

La primera versión daba esto:

```
Alcaraz–Sinner:  media individual 22,5 juegos  ·  cara a cara 32,8
```

La diferencia no era el emparejamiento: era que sus cruces incluyen finales de
Grand Slam **al mejor de 5**. Puesto al lado de una línea de casa —que es de un
partido al mejor de 3— habría hecho parecer baratísimo cualquier «más de 22.5».

Separado por formato, los números encajan:

| | al mejor de 3 | al mejor de 5 |
|---|---|---|
| Djokovic–Nadal, estimación individual | 21,69 | 32,67 |
| Djokovic–Nadal, cara a cara | 21,65 (37 cruces) | 36,00 (18 cruces) |
| Alcaraz–Sinner, cara a cara | 25,20 (10) | 45,50 (6) |

### Tamaño del artefacto

Se precalcula fuera de la interfaz —recorrer 365.000 marcadores en cada carga de
página es inaceptable— y lo regenera la tarea diaria.

Guardar **todas** las parejas costaba 13,0 MB por circuito; guardar sólo las que
se han cruzado dos o más veces en un mismo formato, **4,5 MB**. De las 271.877
parejas del ATP, 220.914 se han visto una sola vez. No entran, y no es por
ahorrar: **un partido no es una distribución**, y este proyecto ya pelea con el
techo de memoria de Streamlit Cloud. Cuando la pareja no llega a dos cruces se
cae en los dos perfiles individuales, que con cientos de partidos cada uno son
una estimación mejor que el único precedente.

---

## 5. Dos fallos de producción que esto destapó

### El precio del EMPATE no llegaba nunca a su mercado

El mercado más jugado que existe, roto desde la v114:

```
«Empate» @ 4,63  →  «Empate» (mv_x, margen de victoria)   similitud 1,00
             y NO →  «Empate (+365)» (draw_prob, 1X2)      similitud 0,75
```

Dos causas, las dos arregladas:

- **La cuota americana que la plantilla pega a la etiqueta contaba para el
  cotejo.** «Empate» contra «Empate (+365)» daba 0,75, por debajo del listón de
  0,80 → sin cruce. Ahora se quitan los paréntesis cuyo contenido es un número
  con signo; «(no pierde)» o «(BTTS)» siguen contando.
- **Cada fila se comparaba contra los ~85 campos del modelo a la vez.** Ahora
  una fila de familia «1X2» sólo puede casar con campos de la sección del 1X2.
  Si la familia no se reconoce o ninguna sección encaja, se cruza contra la
  plantilla entera como antes: ninguna competición pierde mercados por esto.

Los dos campos describen el mismo suceso, así que la probabilidad y el EV
salían bien y **nada fallaba a la vista**. Lo que pasaba es que `draw_prob` se
quedaba sin precio real y toda combinada con empate iba con cuota justa —un
precio inventado— teniendo el real delante.

Con el arreglo, en Monterrey vs Juárez:

```
antes:  draw_prob → None          ahora:  draw_prob → «Empate (+365)» @ 4,25
```

Y de paso entran los tres mercados de doble oportunidad, que también se estaban
perdiendo.

### La pestaña de ranking del tenis desaparecía entera

Lo cazó `smoke_botones.py`, que es exactamente para lo que está:

```
ArrowInvalid: Could not convert '—' with type str: tried to convert to double
              columna «Puntos»
```

`Puntos` era la única columna de esa tabla que salía **sin formatear**. Cuando
un jugador tenía puntos (un número) y el otro no («—»), la columna mezclaba
tipos, Arrow no la podía convertir y `st.dataframe` lanzaba. El `try` del
llamador lo recogía y la pestaña «Ranking y ELO» se sustituía por un
«Panel de jugadores no disponible (ArrowInvalid)».

Es la clase de fallo que no aparece en ningún log de errores porque está
*capturado*: la aplicación no se cae, sólo deja de enseñar una pestaña.

### «🔄 Actualizar» en MLB tumbaba la vista

También del humo de botones, y éste no degradaba: reventaba.

```
ValueError: '2026-08-12 11:40 · Baltimore Orioles @ Minnesota Twins'
            is not in list
```

Los dos selectores de próximos partidos —el de deportes y el de ligas—
construían la opción así:

```python
_etq = f"{_cuando} · {f['away']} @ {f['home']}"
if id(f) not in _con:
    _etq += "  · sin cuota aún"
_ops[_etq] = (h, a)          # ← la etiqueta ES la clave
```

«· sin cuota aún» depende de si las casas han abierto línea, o sea que **cambia
entre una recarga y la siguiente**. Como la etiqueta era además la clave, al
pulsar «Actualizar» el valor guardado en la sesión dejaba de existir en la lista
nueva y `st.selectbox` lanzaba.

Dos arreglos, porque son dos problemas distintos:

- **La clave se separa del texto.** La clave es estable (hora + equipos) y lo
  volátil vive en `format_func`, que puede cambiar todo lo que quiera.
- **Y una guardia para lo que las claves estables no cubren**: un partido que
  termina desaparece del calendario, así que la selección guardada puede dejar
  de existir igualmente. `_olvidar_seleccion_muerta` la borra antes de
  instanciar el selector.

### El acento que se comía los tiempos

`«1ª Mitad»` lleva el indicador ordinal femenino (U+00AA), que la normalización
NFD **no descompone** por no ser un acento. Con NFD, «1ª mitad» nunca empezaba
por «1a mitad» y los doce mercados de tiempos se perdían sin dar un solo error.
Corregido a NFKD.

Es el mismo modo de fallo silencioso que este proyecto ya ha pagado tres veces
(el `typeId` de la v77, el código de liga de los remates, el `isAlternate` de
Pinnacle): no da excepción, simplemente no encuentra nada.

---

## 6. Tests añadidos

| test | qué protege |
|---|---|
| `test_empate_recibe_su_precio` | que el precio del empate llegue al 1X2 y no al margen de victoria |
| `test_tiempos_con_precio_pero_sin_ev` | que los tiempos se traduzcan, que los totales por equipo de una mitad NO, y que su EV vaya marcado |
| `test_h2h_trae_corners_y_tarjetas` | córners, tarjetas y remates en el cruce, y que la posesión no publique un total |
| `test_juegos_de_tenis` | el parseo del marcador, el descarte de retiros y la separación por formato |
| `test_partido_parejo` | el margen de la doble oportunidad con un libro sintético de margen cero |
| `test_selectores_de_partido_con_clave_estable` | que la etiqueta volátil no vuelva a ser la clave de un selector, y que exista la guardia contra la selección muerta |

---

## 7. Lo que esto NO cambia

- **Ni una probabilidad, ni un filtro, ni un peso del modelo.** Todo lo de aquí
  es leer datos que ya estaban y enseñar precios que ya se descargaban.
- **El edge sigue estando en el precio.** La doble oportunidad se presenta como
  gestión de riesgo, no como ventaja; los tiempos, como precio real con EV no
  fiable; los córners, como histórico sin mercado donde jugarlo.
- **Sigue sin haber ninguna promesa de ganar.**
