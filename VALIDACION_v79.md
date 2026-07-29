# VALIDACIÓN v79 — El modelo de MLB predecía 2026 con la forma de 2025, y el barrido tardaba el doble de lo necesario

Fecha: 2026-07-29 · Remotos: `origin` (HMREY) + `upstream` (HectorMontiel)

---

## 0. Resumen

Cuatro síntomas reportados desde producción. Los cuatro tenían causa concreta y
medible, y ninguna era la que parecía:

| Síntoma | Causa real |
|---|---|
| «El tenis desapareció con un AttributeError» | El código era correcto en disco y en los dos remotos. Streamlit conservaba en `sys.modules` el `calibracion_mercado` de la v77 |
| «Casi todo da 50-50» | Es **de MLB**. El estado del modelo llevaba **304 días congelado** y 3 de sus 9 features eran constantes |
| «MLB predice peor que hace unas versiones» | Además de lo anterior, `entrenar()` estaba **roto desde la v78**: el modelo no se podía reentrenar |
| «Apuestas del Día tarda mucho» | Ni la red ni los modelos: el emparejamiento difuso de nombres y el paralelismo de joblib heredado del entrenamiento |

| | Antes | Después |
|---|---|---|
| Antigüedad del estado de MLB | **304 días** (2025-09-28) | **1 día** |
| Juegos en el histórico de MLB | 24.778 (hasta 2025-09-28) | **26.395** (hasta 2026-07-28) |
| Features vivas en inferencia de MLB | 6 de 9 | **9 de 9** |
| Códigos de equipo en MLB | 31 (para 30 equipos) | **30** |
| `entrenar()` de MLB | Lanzaba `TypeError` | **Funciona** |
| Tiempo del barrido diario | **197,9 s** | **104,3 s** (−47 %) |
| Features retiradas para lograrlo | — | **cero** |

---

## 1. El AttributeError que se llevó por delante 319 partidos

```
[alpha] tenis omitido: AttributeError: module 'calibracion_mercado'
        has no attribute 'corregir_dos_vias'
```

La función existe desde la v78 y estaba en `origin` y en `upstream` (que solo
diferían en un `.joblib`). No era un despliegue a medias.

**Causa**: Streamlit no reimporta los módulos ya cargados entre ejecuciones. Al
desplegar la v78 quedó en memoria el `calibracion_mercado` de la v77 mientras
`alpha_finder` sí era el nuevo, y el `import` de dentro de la función devolvía
el módulo viejo.

**Lo grave no fue el fallo, sino el radio de daño.** El `except` que lo recogía
envolvía el barrido ENTERO de tenis, así que un problema de calibración —una
mejora de calidad— borró los 319 partidos del día. `calibracion_segura.py`
invierte esa relación: si el atributo falta, **recarga el módulo desde disco**;
si aun así no está, devuelve la probabilidad sin corregir y sigue. Perder la
corrección es un grado de calidad; perder el deporte es perderlo todo.

La misma lección se aplicó al barrido completo: las cuatro ramas ahora se
recogen por separado y una caída se anota como incidencia sin llevarse el resto.

---

## 2. El «50-50» era de MLB, y tenía tres causas a la vez

Medido con `_v79_diag_mlb.py` sobre todos los emparejamientos posibles:

```
FRACCIÓN entre 45 % y 55 %:  58,5 %
desviación típica:            0,0537        probabilidad máxima: 0,7075
```

El fútbol **no** estaba aplanado (repartía entre 20 % y 85 %). El problema era
exclusivamente de MLB, y se acumulaban tres fallos:

**a) El estado llevaba 304 días congelado.** `cargar_datos_historicos` usaba
Retrosheet, que publica los game logs **por temporada cerrada**. El último
partido que conocía el modelo era del **2025-09-28**; la temporada 2026 se
predecía con el ELO, la forma y las rachas del año anterior.

**b) Tres de las nueve features eran constantes en inferencia.**
`apuestas_dia` llamaba a `predecir(home, away)` sin abridores ni fecha:

```
DIFF_REST     media +0,0000   std 0,0000
DIFF_PIT_RA   media +0,0000   std 0,0000
MEDIA_PIT_RA  media +1,0000   std 0,0000
```

Un tercio de las entradas era ruido fijo, y justo el tercio que más pesa en
béisbol: quién abre. El clasificador estaba entrenado para apoyarse en ellas y
en producción no las recibía nunca, así que se replegaba al centro.

**c) `entrenar()` estaba roto desde la v78.** El campo `filas` que añadió
aquella versión guarda `Timestamp`, que `json.dump` no sabe serializar. El
ledger llama a `_dataset` en memoria y nunca pasa por JSON, así que el único
camino roto era el reentrenamiento — y mientras no se reentrenara, no saltaba.
La huella quedó a la vista: el `estado.json` de producción tenía `filas: 0`,
o sea que se había escrito con código anterior a la v78.

### La solución: la API oficial de la MLB

`statsapi.mlb.com` es gratuita, sin clave y sin cuota. Una temporada completa
son **2.464 juegos en una sola petición de 1,6 s**, con marcador final y
**abridor probable**.

Se ingiere toda la historia desde ahí (no solo la temporada viva) por dos
razones medidas:

1. **Identidad del lanzador.** Retrosheet usa ids propios (`mizec001`) y
   StatsAPI numéricos (`684007`). Mezclarlos parte el historial de cada
   lanzador en dos personas y la media de sus últimas 5 aperturas deja de
   significar nada.
2. **La franquicia de Oakland estaba partida en dos.** Retrosheet cambió el
   código `OAK` (1.502 juegos, hasta 2024-09-29) por `ATH` (162 juegos, desde
   2025-03-27) al mudarse el equipo. Había **31 códigos para 30 equipos** y el
   ELO de los Athletics se reiniciaba a 1500 a mitad del dataset. Ahora se
   canonaliza por id de StatsAPI, que no cambia cuando cambia el nombre.

Resultado: **26.395 juegos hasta 2026-07-28**, 30 equipos, 99,9 % con ambos
abridores, y hoy 16 partidos con 15 abridores anunciados.

Además se separó el **estado** del **modelo** (`refrescar_estado()`): los pesos
del clasificador cambian poco y se reentrenan de tarde en tarde, pero el estado
tiene que ir al día y recalcularlo es un solo barrido sobre el CSV.

---

## 3. Dos fallos silenciosos más, encontrados por el camino

**`entrenar()` borraba `sigma_margen`.** Ese valor lo calcula
`calibrar_margenes_v32.py`, no el entrenamiento, y `metadata.json` se escribía
entero en cada reentrenamiento. Sin `sigma_margen`, la plantilla de
`base_engine` deja de emitir spread y totales por equipo — **en silencio**,
porque están detrás de un `if sigma`. Cada reentrenamiento amputaba mercados sin
dar ningún error. Ahora el metadata se funde en vez de sobrescribirse.

**Una escritura fallida corrompía el estado.** `json.dump` va escribiendo a
medida que serializa: al fallar a mitad dejó `estado.json` cortado en el
carácter 48.380 y el motor dejó de arrancar con `JSONDecodeError` — peor que el
fallo original, porque tumba el modelo entero. Ahora se escribe a un temporal y
se reemplaza de golpe.

---

## 4. Lo que NO funcionó: features enriquecidas para MLB

Con los datos ya frescos, la pregunta seguía abierta: ¿el 50-50 de MLB es del
deporte o del modelo? La respuesta depende de con cuántos partidos se mire, y
conviene enseñar las dos:

| Muestra | Dispersión del modelo ÷ dispersión del mercado |
|---|---|
| 15 partidos de hoy | 0,909 — parecería que el 50-50 es del deporte |
| **7.541 del ledger** | **0,558 — el modelo comprime el abanico a la mitad** |

Manda la segunda. Con 7.541 predicciones fuera de muestra y cuota de cierre
real, el mercado reparte el doble de recorrido con los mismos partidos: al
modelo le falta señal.

Así que se probaron 8 features nuevas, todas causales y sin peticiones extra:
encogimiento empírico-bayesiano del abridor con ventana de 10 aperturas, forma
de temporada encogida, factor de parque, ELO ponderado por margen de victoria y
descanso del abridor.

| variante | n | log-loss | precisión | ratio de dispersión |
|---|---|---|---|---|
| BASE (9 features) | 8.296 | **0,6833** | **0,5647** | 0,527 |
| RICO (17 features) | 8.296 | 0,6834 | 0,5599 | 0,527 |
| MERCADO | 8.296 | 0,6687 | 0,5932 | 1,000 |

**RECHAZADAS.** No mejoran ni la log-loss ni la precisión, y el ratio de
dispersión no se mueve ni una milésima. Ese ratio clavado en 0,527 con los dos
vectores es el dato informativo: el techo no está en cómo se combinan las
estadísticas de equipo, está en que las estadísticas de equipo no dan para más.
Lo que falta es la línea real del abridor (ERA/FIP, K/BB de sus últimas
salidas), y eso exige un game log por lanzador: StatsAPI no lo sirve a granel
sin `playerId`, y son ~900 lanzadores por temporada.

**Lo que sí aportó la frescura**, medido aparte sobre los 1.595 partidos ya
jugados de 2026, con el mismo modelo y cambiando solo el estado:

| | log-loss | precisión |
|---|---|---|
| Estado CONGELADO (lo que hacía producción) | 0,6939 | 0,5304 |
| Estado AL DÍA | **0,6912** | **0,5354** |

+0,0027 de log-loss y +0,50 pp de precisión. Real, y modesto. Conviene decir
también lo incómodo: 0,6912 está muy cerca de ln(2)=0,6931. **En MLB el modelo
apenas bate a la moneda al aire, y el mercado le saca 0,022.** Sigue fuera de la
Capa 1 por la regla de la v78, y es el veredicto correcto.

---

## 5. El barrido: 197,9 s → 104,3 s, sin quitar nada

Instrumentado con `_v79_diag_barrido.py`, el reparto inicial era:

```
TOTAL                       197,9 s
  apuestas_del_dia (fútbol)   117,4 s
    └ _barrido_fixtures       112,0 s
  _picks_tenis                 77,7 s
  _picks_mlb                    2,6 s
```

**Primer intento: paralelizar las cuatro ramas. Casi no sirvió** — 197,9 s →
188,0 s, y `_barrido_fixtures` incluso EMPEORÓ (112 s → 171,7 s) al competir con
las demás. Eso descartó la hipótesis de «está esperando a la red»: si el tiempo
fuera espera, los hilos habrían solapado. Que empeore al paralelizar significa
contención de CPU. Hubo que perfilar de verdad.

**Causa 1 — el emparejamiento de nombres, no la red.**

```
cuotas_multi.normalizar     2.845.780 llamadas    77,8 s
cuotas_multi._tokens_club   2.844.616 llamadas   128,3 s
cuotas_multi._sim_club      1.422.308 llamadas   106,9 s
difflib.ratio               1.417.516 llamadas    56,0 s
```

`_buscar` recorre el tablón entero (~976 partidos) y por cada candidato llama
cuatro veces a `_sim_club`, que normaliza dos nombres cada vez. Millones de
llamadas sobre un puñado de nombres **distintos**: se estaba recalculando
«Palmeiras» miles de veces. Son funciones puras → `lru_cache`.

Se añadió además un atajo **demostrado**, no heurístico: sin ningún token
compartido, `_sim_club` devolvería `0,5·cad`, que como `cad ≤ 1` nunca llega a
0,5 — muy por debajo del umbral 0,80 que exige `_buscar`. Calcular ahí el
`SequenceMatcher` no puede cambiar ninguna decisión, solo gastar tiempo. Y ese
es el caso mayoritario, porque casi todos los pares del tablón son partidos que
no tienen nada que ver.

→ 197,9 s → **119,0 s**

**Causa 2 — el paralelismo de joblib heredado del entrenamiento.**

```
VotingClassifier.predict_proba   370 llamadas   44,3 s   (0,12 s cada una)
joblib.parallel._get_outputs 167.240 llamadas   75,7 s
```

0,12 s para predecir **una fila** no es cálculo, es coordinación. Los modelos se
guardaron con `n_jobs=-1` (correcto al entrenar con miles de filas), pero esa
opción viaja dentro del `.joblib` y en producción se predice de uno en uno:
repartir 200 árboles entre todos los núcleos cuesta órdenes de magnitud más que
evaluarlos. `inferencia_rapida.py` pone `n_jobs=1` al cargar.

Verificado con una aceleración de **2,1×** y un matiz que conviene precisar,
porque el test lo destapó: prediciendo **fila a fila** —que es lo que hace
producción— la diferencia es del orden del epsilon de máquina (se observó
`0,0` en 60 predicciones, y ~1e-16 de forma esporádica: ver la corrección en
la v82). Prediciendo un **lote** aparece una diferencia de ~1e-16, y
no es del modelo: sumar los votos de los árboles en distinto orden cambia el
último bit, porque la suma en coma flotante no es asociativa. Ni siquiera es
determinista entre ejecuciones, así que el test exige epsilon de máquina y no
igualdad exacta — si no, sería intermitente.

→ 119,0 s → **104,3 s**

**No se retiró ni una feature.** Se calcula exactamente lo mismo que antes; lo
que cambió es cuántas veces se recalcula lo mismo y cómo se reparte.

---

## 6. Reproducibilidad: `pick_ledger_total.csv` no lo escribía nadie

De ese fichero dependen el peso `w` de cada liga, las bandas de «Máxima
Confianza» y **qué deportes entran en la Capa 1**. Se había creado a mano en la
v78 juntando los dos ledgers parciales, y ningún script lo regeneraba.

No es teórico: al reconstruir el ledger de MLB en esta versión,
`pick_ledger_deportes.csv` se quedó solo con MLB (el tenis se sobrescribió) y el
total siguió tan campante con los datos viejos — los tests seguían dando por
buenos los números de la v78. Ahora lo construye `build_ledger_total.py`, con
guardia de deportes perdidos y de duplicados.

---

## 7. El pick de fútbol ya dice si se le encogió

La v78 adjuntó `calibracion` a los picks de MLB y de tenis; el fútbol se quedó
sin ello (se calculaba y se tiraba). Se descubrió al instrumentar el barrido,
porque el diagnóstico daba «Fútbol: SIN encogimiento aplicado» cuando en
realidad sí se aplicaba: simplemente no había forma de saberlo desde fuera.

Importa más aquí que en los otros dos deportes, porque el fútbol es hoy el
único con edge validado —el único cuyos picks son accionables— y con `w=0,25`
tres cuartas partes de la probabilidad que ve el usuario vienen del mercado.
Eso tiene que poder auditarse.

Y en cuanto se pudo auditar, apareció lo que sigue.

---

## 7 bis. Tenis: el A/B automático dijo «adoptar» dos veces y se equivocó una

Se remidieron las cinco variantes de vector en los dos circuitos con el mismo
protocolo, el mismo estimador y los mismos pliegues
(`_v79_tenis_features.py`, 5 vectores × 2 circuitos × 5 pliegues). Las features
de nivel se habían descartado en la v67 y las de saque en la v69, pero aquellas
decisiones son anteriores al walk-forward con cuota real.

| circuito | vector | n | log-loss | precisión | ll mercado |
|---|---|---|---|---|---|
| ATP | **V30 (producción)** | 32.811 | 0,6228 | 0,6430 | 0,5844 |
| ATP | V69-WTA (V35+saque) | 32.811 | **0,6217** | **0,6443** | 0,5844 |
| WTA | **V35 (producción)** | 25.317 | 0,6289 | 0,6404 | 0,5853 |
| WTA | V67 (con nivel) | 25.317 | **0,6279** | **0,6429** | 0,5853 |

El script imprimió **ADOPTAR en los dos**, y era un espejismo: el umbral
(Δ log-loss > 0,001) lo había fijado yo a ojo y las dos ganancias caían justo
encima. Con **10 combinaciones probadas**, quedarse con la mejor de cada
circuito y llamarlo mejora es el error de comparaciones múltiples que este
proyecto ya evitó en la v33 (ELO ataque/defensa) y en la v35 (CDI en UECL).

Lo que decide es un **bootstrap pareado** sobre la diferencia de log-loss
partido a partido (`_v79_tenis_significancia.py`, 5.000 remuestreos). Pareado
porque los dos vectores predicen **los mismos partidos**, así que la varianza
compartida se cancela y el contraste es mucho más sensible que comparar dos
medias sueltas:

| circuito | Δ log-loss | IC 90 % pareado | remuestreos > 0 | p1 Bonferroni | veredicto |
|---|---|---|---|---|---|
| **ATP** | +0,00088 | [**+0,00000**, +0,00180] | 95,1 % | **−0,00037** | **NO adoptar** |
| **WTA** | +0,00108 | [+0,00066, +0,00149] | **100,0 %** | **+0,00047** | **ADOPTAR** |

El ATP no sobrevive: su intervalo **toca el cero** y, tras corregir por las
cinco variantes probadas, queda en negativo. La WTA sí: 5.000 de 5.000
remuestreos positivos y el percentil 1 aún por encima de cero. Precisión WTA
**0,6390 → 0,6428 (+0,38 pp)**.

Se adopta **solo la WTA** (`FEATURES_POR_DEFECTO['wta'] = FEATURES_V67`), con
el reentrenamiento que exige el cambio de 10 a 13 columnas — el aviso que dejó
escrito la propia v67.

Dos cosas que conviene no perder de vista:

- **Esto no rescata al tenis.** El mercado está en 0,584 (ATP) y 0,585 (WTA)
  frente a 0,622-0,628 del modelo: la brecha es de ~0,037, unas **treinta
  veces** la mejora medida. El tenis sigue fuera de la Capa 1 salvo que el
  ledger diga otra cosa, y se comprueba en vez de suponerlo.
- **Coherencia entre circuitos.** Los mismos dos vectores de 13 features ganan
  en ATP y en WTA. Eso es evidencia débil pero real de que hay señal en las
  features de nivel; lo que dice el contraste es que en el ATP esa señal es
  demasiado pequeña para distinguirla del ruido con la muestra disponible.

_(De paso, una lección de fontanería que costó 50 minutos: la primera ejecución
del contraste murió por un `UnicodeEncodeError` al imprimir «Δ» en una consola
cp1252, **con los resultados ya calculados y perdidos**. Ahora el script fuerza
UTF-8 y **cachea las predicciones en disco**, para que reanalizar no obligue a
reentrenar.)_

### Resultado del reentrenamiento y del ledger

La WTA reentrenada con 13 features confirma lo que predijo el walk-forward:

| | antes (V35) | después (V67) |
|---|---|---|
| precisión de validación | 0,6341 | **0,6401** (+0,60 pp) |
| log-loss de validación | 0,6317 | **0,6296** |
| features | 10 | 13 |

Y ahora la pregunta que de verdad importa, que es si eso mueve la rentabilidad.
Reconstruido el ledger de tenis (28.132 predicciones WTA nuevas, guardia de
alineación en verde en los dos circuitos):

| | v78 | v79 |
|---|---|---|
| mejor ROI | −0,54 % | **+1,85 %** |
| n | 1.971 | **112** |
| bootstrap p5 | −6,14 % | **−9,55 %** |

**El tenis sigue fuera de la Capa 1, y hay que leer bien por qué.** El ROI ha
cambiado de signo, pero sobre **112 apuestas en vez de 1.971** y con un p5 que
empeora. Eso no es edge que aparece: es una selección más pequeña y más
ruidosa. La regla de la v44 —ROI **y** p5 positivos— lo deja fuera, y es el
veredicto correcto. Mejor probabilidad no es lo mismo que mejor negocio; es la
misma lección de la v78, ahora en la dirección contraria.

---

## 7 ter. Dos fallos que me hice yo mismo al reconstruir

Los dos son del tipo que este proyecto persigue: **no dan ningún error**.

**a) Reconstruir un deporte borraba a los demás.** `build_ledger_deportes
.construir(deporte='mlb')` escribía el CSV entero con solo MLB, y las 64.587
filas de tenis desaparecían sin un aviso. Pasó de verdad: el ledger total
siguió con datos viejos y los tests continuaron dando por buenos los números de
la v78 un buen rato. Es grave porque de ese fichero sale **qué deportes entran
en la Capa 1**. Ahora, al reconstruir un subconjunto, los deportes que no se
tocan se conservan del fichero anterior, y se dice cuántas filas se conservan.

**b) La caja de la clave decidía si un deporte se calibraba.** `ledger_tenis`
escribe `liga` como `circuito.upper()` («ATP», «WTA») y `ledger_mlb` en
minúsculas («mlb»). `recalibrate_from_history` usa esa columna tal cual como
clave del JSON, así que la tabla quedó con «ATP» y «WTA» en mayúsculas —
mientras producción pregunta en minúsculas (`eng.circuito.lower()`):

```
peso_modelo('atp') -> 1.00        peso_modelo('ATP') -> 0.25
peso_modelo('wta') -> 1.00        peso_modelo('WTA') -> 0.25
```

El tenis se quedaba **sin encoger, en silencio**, justo después de que la v78
midiera que encoger le da +2,6 pp (ATP) y +2,4 pp (WTA) de precisión. Ni un
error, ni una traza: solo w=1 y picks más sobreconfiados. La búsqueda es ahora
insensible a mayúsculas, lo que arregla el fichero actual y cualquiera que
escriba un constructor futuro con otra convención.

---

## 8. Lo más importante de esta versión: el pick de julio no es el que se validó

Al exponer la calibración salió un **0 %**. Ni un solo pick de fútbol llevaba
corrección de mercado. Se persiguió hasta el final, descartando explicaciones
con datos:

| Hipótesis | Medición | Veredicto |
|---|---|---|
| No hay cuota sharp | Pinnacle publica 634 partidos y cubre el **73 %** de los de hoy | Descartada |
| No llega a la rama de calibración | **21 de 129** evaluaciones sí entran con cuota de Pinnacle | Descartada |
| El peso no existe para esas ligas | `peso_modelo('argentina')` → **1,00** | **Confirmada** |

`calibracion_mercado.json` se construye desde el ledger, y el ledger de fútbol
viene de fuentes que cubren sobre todo **Europa**. En julio Europa está de
vacaciones y lo que juega es Sudamérica:

```
18 ligas CON peso medido y SIN partidos hoy   (laliga, serie_a, premier...)
20 ligas jugando hoy SIN peso medido          (argentina, liga_mx, sudamericana...)
cobertura real: 49 de 160 partidos = 30,6 %
```

**Por qué esto importa más que todo lo demás de la versión.** El edge del
fútbol —lo único que el sistema vende como accionable— se midió *en w = 0,25*:

| | ROI | bootstrap p5 |
|---|---|---|
| w = 0,25 (validado) | **+6,72 %** | **+0,92 %** |
| w = 1,00 (lo que sale hoy) | +0,47 % | −2,62 % |

Con w=1,00 el mismo histórico **no muestra edge**. Es decir: la Capa 1 de julio
está emitiendo picks que no son los que pasaron la validación, y hasta ahora
nada lo decía.

**Lo que se hace en esta versión**: dejarlo a la vista. El barrido emite ahora
una incidencia explícita en la interfaz:

> *16 de 16 picks de fútbol salen SIN calibrar contra el mercado: sus ligas no
> tienen peso medido (Brasileirão Serie A, Categoría Primera A, División
> Profesional, Liga MX…). El edge del fútbol se validó con encogimiento
> (w=0,25); sin él, el mismo histórico no muestra edge. Trátalos con más
> cautela.*

**Lo que NO se hace, y por qué**: arreglarlo de verdad significa conseguir
histórico de cuotas de las ligas sudamericanas para poder medirles un peso. Es
perfectamente factible —BetExplorer ya demostró servir 7.372 cuotas de 22 ligas
en la v76— pero es un trabajo de ingesta y validación completo, no un parche de
última hora. Meter un peso «por analogía» con otra liga sería inventarse la
medición, que es justo lo que este proyecto no hace. Queda como la prioridad
número uno de la v80, ahora con el tamaño del problema cuantificado.

---
