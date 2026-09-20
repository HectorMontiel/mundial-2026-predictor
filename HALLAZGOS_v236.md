# v236 — Menos texto, filtros que siguen al día, y alias que se descubren solos

Seis peticiones en un mensaje. Cinco eran cambios; una resultó ser una
comprobación que terminó en «está bien, no se toca», y esa es la que más
merecía medirse.

---

## 1. El botón de «Actualizar ahora» se va

Tres versiones seguidas hablando del mismo botón:

- **v226** — no actualizaba. Se arregló que `forzar` no intentara recalcular
  1,3 GB en un servidor de 1 GB.
- **v233** — seguía sin actualizar. La causa real: releía un fichero del disco
  del contenedor, y ese fichero **no cambia nunca** entre despliegues porque el
  cron commitea a GitHub, no escribe ahí. Se cambió para que bajara el
  publicado, y se le añadió un aviso de si había traído algo nuevo.
- **v236** — y con ese aviso puesto quedó a la vista lo que el botón era en
  realidad: la mayoría de las veces sólo podía contestar *«ya tenías lo
  último»*.

Un botón que casi siempre responde «no hay nada que hacer» no es una acción: es
un recordatorio de la cadencia. Y para eso basta un renglón.

**Lo que había, y lo que queda:**

```
antes:  🔄 [Actualizar ahora]
        «SOLO los partidos de HOY: todas las ligas con jornada este día
         (ESPN + Pinnacle + Bovada + Playdoit + Unibet + Matchbook) + MLB,
         NBA, tenis ATP/WTA y NFL, con cuota y EV automáticos. Todas las
         horas están en hora de Ciudad de México. Capa 1 = cuota real con
         EV; Capa 2 = alta confianza sin cuota en vivo; Pronósticos = todos
         los partidos de hoy. La semana completa vive en la vista de cada
         liga («Próximos partidos»).»
        «⏱️ Los precios que se ven se bajaron hace 5 h 50 min y se están
         actualizando en segundo plano. Los pronósticos del modelo siguen
         siendo válidos —sólo cambian cuando reentrena el bot—, pero
         confirma el precio en la casa antes de apostar. «Actualizar ahora»
         recoge el último pronóstico publicado.»

ahora:  Partidos de hoy, hora de CDMX. Se actualiza solo cada 3 h.
        ⏱️ Precios de hace 5 h 50 min — confirma en la casa antes de apostar.
```

Todo lo que se fue era cierto. Ninguno era **accionable**: son datos de
arquitectura que se aprenden en la primera visita y luego estorban cada vez.

**Los otros dos botones de refresco se quedan.** El de cuotas por deporte y el
del panel de béisbol limpian caché y vuelven a bajar de la red: hacen trabajo de
verdad. Sólo se fue el que no podía hacerlo.

---

## 2. Un deporte sin partidos no tiene botón

`_SIEMPRE = {'Todo', 'Fútbol', 'MLB', 'Tenis', 'NFL'}` forzaba a los cinco
principales a salir con partidos o sin ellos. La NBA en septiembre y la KBO
fuera de temporada ocupaban su sitio para no enseñar nada: pulsarlos daba una
lista vacía, que es peor que no estar.

Ahora sólo `Todo` es fijo —es el estado por defecto y tiene que existir aunque
el día venga vacío— y el resto aparece cuando hay juego. Sin lista de
temporadas que mantener.

---

## 3. Los insights siguen al filtro

Enseñaban siempre el total de los cinco deportes, así que con ⚽ puesto las
cuatro cifras seguían contando tenis, MLB y NFL.

El problema de fontanería: el selector se construye **más abajo** que los KPIs,
porque necesita el conteo por deporte que sale del mismo barrido. Así que los
KPIs leen su estado de sesión en vez de su variable. Streamlit rehace la pasada
entera al cambiar un widget, de modo que lo que hay en sesión es la elección
vigente y no la anterior.

| filtro | pronósticos | capa 1 | capa 2 |
|---|---|---|---|
| ⚽ Fútbol | 169 | 2 | 0 |
| 🎾 Tenis | 142 | 3 | 6 |
| ⚾ MLB | 10 | 0 | 1 |
| Todo | 340 | 5 | 10 |

Y el rótulo dice de qué deporte habla: un «3» a secas se leería como el total
del día.

---

## 4. Los partidos en rojo: medido, correcto, no se toca

La pregunta era buena: *«¿de verdad no hay nada probable que mostrar?»*.

Sobre los 168 partidos de fútbol del día: **128 tienen al menos una verde
(76 %)** y 40 salen todo rojo. De esos 40, casi todos son EV **negativo** —la
casa paga menos que el precio justo—:

```
Emelec vs Libertad       Gana Emelec        57,5 %  cuota 1.645   EV −5,4 %
Minnesota vs LA Galaxy   Gana Minnesota     57,5 %  cuota 1.667   EV −4,1 %
```

Sólo uno tenía EV positivo (+2,3 % al 59,7 %) y salía rojo igual. No es un
fallo: el veredicto **no mira EV, mira probabilidad**, y el listón está escrito
en el propio módulo:

```python
UMBRAL_METER = 0.65
# «por debajo de aquí no compensa meterla en una combinada de varias patas,
#  porque el producto de probabilidades se desploma. Con cuatro patas al 65 %
#  el boleto entero está al 17,9 %.»
```

O sea que un 59,7 % con valor sale rojo por ser **mala pata de parley**, no por
ser mal precio. Para quien arma boletos de diez patas, eso es exactamente
«precisión y no arriesgar». **Se mantiene sin tocar.**

---

## 5. Los alias de nombre dejan de escribirse a mano

La v235 arregló 19 partidos que salían sin tablero porque cada fuente escribe el
nombre en su idioma: «Napoli» contra «Nápoles», «Genoa» contra «Génova»,
«F.C. København» contra «FC Copenhagen». Pero esa tabla la escribí **leyendo los
fallos de un solo día**, y ahí estaba su ruina: mañana juega otra liga, salen
otros seis nombres y la tabla se queda corta sin que nadie se entere.

`alias_equipos` los descubre en cada pasada del cron. Lo delicado no es
encontrarlos: es **no inventarlos**. Bajar el umbral de parecido y dejar que el
emparejador ligue lo que pueda es exactamente como se sirve la cuota de otro
partido — el fallo de la v114, un partido femenino emparejado con uno masculino
cinco días después y con los bandos al revés.

Un alias sólo se acepta con las tres condiciones a la vez:

1. **Un lado casa EXACTO.** Si «Fiorentina» es idéntico en las dos fuentes, el
   partido ya está casi identificado y sólo queda un nombre por resolver. Eso
   convierte una adivinanza en una deducción.
2. **El otro se parece más de 0,82** sobre la cadena entera. «napoli» contra
   «napoles» pasa; «psg» contra «paris saint germain» no, y por eso ése sigue
   escrito a mano.
3. **Misma fecha y misma categoría**, que lo valida el propio emparejador.

Y un veto duro: nada que lleve marca de filial o juvenil —«sub 19», «U19»,
«II», «B», «women»— aunque cumpla las tres. Son partidos distintos que se juegan
el mismo día en la misma sede con nombres casi iguales: el terreno más fértil
que hay para un emparejamiento falso.

**Primera pasada: 145 fixtures revisados, 132 ya casaban, 1 alias nuevo**
(`Sint Truiden` → `Sint Truidense`, parecido 0,923) y **ninguna falsedad**.

La tabla escrita a mano **manda** sobre la automática: lo verificado uno a uno
no puede quedar pisado por un descubrimiento con el parecido raspado.

Se ejecuta **antes** del barrido, no después: `construir()` empareja cada
fixture con el tablero de la casa, así que descubrir los alias después serviría
para el barrido de dentro de tres horas, no para éste.

---

## Lo que la suite cazó, y que conviene contar

Al retirar el botón, **cinco tests se pusieron en rojo**: eran los que yo mismo
había escrito dos versiones antes para blindarlo. Exigían que existiera.

Se retiraron con su motivo escrito, no se aflojaron. Y uno de ellos dejó nota,
porque su lección no dependía del botón: vigilaba que no llamara a `st.rerun()`
por encima de los widgets, que provocaba `KeyError: parlay_base`. Esa trampa
sigue existiendo para cualquier otro botón, y de ella se ocupa
`test_los_widgets_no_dependen_de_que_haya_datos`, que sigue vivo.

También hubo que ajustar un test propio que era **demasiado literal**: prohibía
la cadena «Actualizar ahora» en todo el fichero, lo que impedía hasta una nota
histórica que explica por qué un widget se crea siempre. Un test no puede
obligar a contorsionar la documentación: ahora comprueba que el **botón** no se
crea, mirando su clave.
