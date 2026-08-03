# 🏆 Motor Predictivo TDA — Mundial 2026 (v4, plantilla de análisis completa)

## Novedades v91 — Un solo reloj, un solo día, y la app deja de mentir (ver [VALIDACION_v91.md](VALIDACION_v91.md))

- **🕐 Había DOS relojes.** `fixtures_espn` pedía el rango a ESPN en hora
  **local** y las fechas que ESPN devuelve son **UTC**. En Streamlit Cloud el
  servidor va en UTC y coincidían, así que el fallo era invisible en
  producción; al acotar el barrido al día apareció como «partidos evaluados:
  0» con 12 disponibles. Unificado en `hoy_utc()`, y el test de regresión
  —que recorre el AST buscando llamadas a `.today()`— **encontró dos más que
  se me habían escapado**.
- **📅 «Apuestas del Día» es el DÍA CALENDARIO**, tercer intento y el que se
  pidió: si es 3 de agosto, sólo partidos del 3 de agosto, sea cual sea la
  hora de consulta. (v88 fue rolling 24 h, v89 la semana entera: ambas
  rechazadas). El barrido pasa de **227 partidos a 11** y de **102 s a 34 s**.
  La semana completa vive ahora en la vista de cada liga, ordenada por fecha.
- **⚡ Las secciones ya no esperan.** Máximo Valor, Máxima Confianza y
  Combinadas no aparecían hasta hacer click: las dos secciones de combinadas
  —que cargan motores y corren Monte Carlo— estaban **antes** de las pestañas y
  Streamlit ejecuta de arriba abajo. Movidas al final.
- **🎯 Máxima Confianza, por fin multi-deporte.** Los favoritos de tenis y MLB
  (82-88 % a cuota 1,08-1,15) viven en la capa 2 —no pasan el filtro de élite
  por la cuota corta— y la capa 2 no entraba en el universo; además la MLB
  devolvía `capa2: []` por construcción. Medido: de **{Fútbol: 19}** a
  **{Fútbol: 7, Tenis: 7}**, con MLB ya fluyendo.
- **🩺 «Registro de incidencias» → «Estado del sistema», en verde.** De seis
  avisos que parecían fallos, ninguno lo era. Ahora cada línea trae severidad
  (✅ operativo · ℹ️ contexto · ⚠️ problema) y el filtro anti-CPBL de la v88
  deja de reportarse: es el guardarraíl trabajando. Hoy: **3 líneas, 0
  problemas**.
- **🏷️ Los partidos sin modelo tienen tarjeta con cuota.** Los 22 nombres en
  crudo eran challengers/ITF con precio real; ahora salen **45 tarjetas** con
  su cuota y la probabilidad implícita del precio, etiquetadas «sin predicción
  propia».
- **🧹 Fuera el camino muerto de la API de cuotas retirada en la v88.** El
  aviso «Sin captura de cuotas propia» salía porque el barrido seguía
  intentando leer `odds_actuales.json`: en producción ese fichero no existe, o
  sea que **ese bucle llevaba meses sin ejecutarse**. Retirado con sus cuatro
  satélites huérfanos. Y el stack de Streamlit en la vista MLB (widget con
  `index=` sobre una clave que el código ya escribe) arreglado, en MLB y NBA.

## Novedades v90 — Seis rechazos medidos, y dónde estaba el techo de verdad (ver [VALIDACION_v90.md](VALIDACION_v90.md))

- **📊 El techo real de cada competición, a la vista.** El acierto del cierre
  del mercado —el mejor predictor que existe— va del **42,4 %** en la Serie B
  italiana al **59,1 %** en la Superliga turca. Diecisiete puntos. La app
  enseñaba los 274 pronósticos con el mismo aire de autoridad; ahora cada
  partido y la tabla de pronósticos llevan el techo de su liga, porque un 55 %
  en Turquía y un 55 % en la Serie B no valen lo mismo. **Validado antes de
  publicarse**: a diferencia del ROI por liga (que la v38 midió no
  estacionario), el techo se sostiene entre mitades del ledger con correlación
  **0,72**, y el fichero sólo se publica si supera 0,50.
- **🔓 Desbloqueado el line shopping en Goles y BTTS.** `cuotas_partido`
  fusionaba los totales de todas las casas en un único dict —el over25 de ESPN
  y el de Pinnacle iban a la misma clave y el segundo pisaba al primero—, así
  que `daily_snapshots` sólo podía etiquetarlos como Pinnacle. En
  `historical_odds` había **35.606 filas con over25 y CERO partidos con dos
  casas**: el histórico necesario no podía existir. Arreglado sin cambiar nada
  de lo desplegado; medido tras una captura real: DraftKings pasa de 0 a **571**
  filas con over25 y ya hay **56 de 178** partidos con dos casas.
- **🧪 Seis palancas de edge probadas y rechazadas con números**, todas con
  elección en pliegues tempranos y juicio en tardíos sobre 26.666 partidos: w
  por liga (gana en el 54 %, una moneda al aire), mezcla en logit, w global
  reoptimizado, stacking aprendido, corrección del sesgo favorito-perdedor
  (b=1,0158 ≈ nada, y **baja** el ROI de +8,57 % a +7,15 %) y el modelo como
  filtro del line shopping (superficie dentada, 4/11 configs). **El modelo
  propio bate al mercado en 4 de 34 ligas**: el 1X2 está en un óptimo local y
  el edge vive en el line shopping, que sí valida fuera de muestra (n=643,
  ROI +8,57 %, **p5 +1,07 %**). Queda escrito para no volver a gastar ahí.
- **❌ Dos propuestas rechazadas, una con premisa falsa.** *Cuotas
  sudamericanas para medir el w por liga*: el ledger YA tiene 1.534 filas de
  Argentina con Pinnacle, 1.562 de MLS, 1.276 de Brasil — se midió sin
  scrapear nada y el w por liga sale peor en ECE, ROI y p5. *Calibrar córners
  y tarjetas*: no son mercados de la app (Máxima Confianza sólo puede contener
  1X2/Ganador/Moneyline/Goles/BTTS/Hándicap, los cuatro medibles ya medidos),
  **0 de 71** históricos traen columnas de córners, y el número que se muestra
  es una transformación determinista de los goles esperados.

## Novedades v89 — El crash de snapshots, la semana completa y la gran limpieza (ver [VALIDACION_v89.md](VALIDACION_v89.md))

- **💥 Arreglado el crash de producción** (`no such table: snapshots`): «Valor
  en Vivo» leía la tabla de la v43, cuyo único escritor se retiró con The Odds
  API en la v88. Los 3 lectores migran a la fuente viva (`historical_odds`
  fase='snapshot'), que en Cloud se **rehidrata sola** desde
  `odds_snapshots.csv`. Verificado simulando el disco efímero. Y de paso la
  vista deja de enseñar EV fantasma: **+93,9 %** que eran desacuerdo
  modelo-mercado (el patrón que la v87 midió en 33,6 % de acierto) ahora se
  encogen con el w por liga validado → +8/+16 % de line shopping real.
- **📅 Apuestas del Día cubre la SEMANA, con HOY destacado.** Dos recortes se
  sumaban: `fixtures_multi` usaba el default de **3 días** (no los 7 de
  `DIAS_SEMANA`) y la ventana de 24 h de la v88 **filtraba antes de evaluar**.
  Medido el 2026-08-02: la semana tenía 302 fixtures (78 % ya con cuota) y el
  barrido evaluaba **25**; 44/56 ligas salían «sin partidos» jugando esa
  semana. Ahora: **274 evaluados en 32 ligas**, la ventana es etiqueta
  (`es_hoy`), la UI agrupa por día y por partido (**todas** las apuestas con
  valor de un partido, no solo una), candidatos 15→40, y cuota+EV automáticos
  en todo — sin botones manuales.
- **⚡ Barrido semanal en 102 s** (antes 304 s): las cuotas por evento de todas
  las ligas se prefetchean en paralelo y la red queda escondida detrás de la
  CPU; los motores se liberan al terminar su liga (con ~32 ligas, retenerlos
  era el patrón de memoria de 1,3 GB de la v86).
- **🧨 Dos bombas del historial desactivadas**: el expander duplicado de
  Telegram que aún llamaba `construir_mensaje()` sin el barrido (el bug de
  2.172 MB de la v88 arregló un botón y este quedó vivo), y «Actualizar datos
  ahora» del Mundial, que hacía `st.cache_data.clear()` GLOBAL + un subprocess
  de 30 min (el patrón de caídas de la v86).
- **🧹 Gran limpieza (177 archivos)**: Polymarket retirado (mercados del
  Mundial cerrados con el torneo), pestaña MLB manual → automática con la
  fuente real, `data_health` reescrito sin la API retirada, 141 scratch
  `_vNN_*` y 34 módulos muertos/one-off fuera (los números de aquellos
  experimentos siguen en `resultados_*.json` y los VALIDACION). Alias nuevos
  (AGF, København, Sønderjyske, Hearts) y `nombres_sin_mapear.json` deja de
  acumular fallos ya resueltos.

## Novedades v88 — Telegram tumbaba la app, y los picks de «MLB» eran de Taiwán (ver [VALIDACION_v88.md](VALIDACION_v88.md))

- **📤 Arreglado: enviar a Telegram tumbaba la app.** `construir_mensaje()`
  llamaba a `apuestas_del_dia_universal()` por su cuenta, saltándose el guardia
  de la v86. Como el dashboard ya tenía el barrido en memoria, el botón lanzaba
  un **segundo barrido completo**: 1.297,7 MB uno, **2.172,2 MB dos**. No
  fallaba el envío, fallaba la memoria de rehacer el trabajo. Ahora se le pasa
  el barrido ya hecho: el botón provoca **0 barridos** en vez de 1.
- **⚾ Los picks de «MLB» no eran de MLB.** Lo que llegaba a la Capa 1 era
  `Rakuten Monkeys @ Uni-President Lions` — la **CPBL de Taiwán** —, y por
  duplicado. De las **80 entradas** del tablón de béisbol en Pinnacle, Bovada y
  Playdoit, sólo **16 eran MLB**; el resto, Liga Mexicana, Japón, Corea, Taiwán
  y Triple-A. Y peor: el fuzzy daba por equipos de MLB a un **10 %** de los
  ajenos (*Kia Tigers* → Detroit **Tigers**, *Chiba Lotte Marines* → Seattle
  **Mariners**, *Fubon Guardians* → Cleveland **Guardians**), así que se
  predecían con las estadísticas del equipo equivocado. Con el filtro estricto:
  **falsos positivos 10 % → 0 %**, y los 30 equipos reales siguen reconociéndose.
- **⚾ MLB ya entra en el barrido — y hoy no da picks por una razón legítima.**
  Se evalúan sus **15 partidos** reales. El modelo llega al umbral de
  probabilidad (61,3 % sobre 58 %) pero **todos los EV son negativos**, de
  −1,97 % a −6,33 %, y la vía de valor no encuentra ninguna casa descolgada.
  **No se bajan los umbrales para forzar picks**: serían apuestas de EV
  negativo. Está conectada y dará picks el día que haya valor.
- **🧵 Cazado un fallo de concurrencia que dejaba MLB fuera** (introducido en la
  v87). La reparación de modelos parchea `Booster.__setstate__`, que es **global
  al proceso**, y el barrido corre sus cuatro ramas en paralelo: el hilo de MLB
  cargaba su modelo a través del parche del hilo de fútbol y reventaba con
  `access violation` dentro de `XGBoosterPredict`. Ahora va bajo cerrojo y el
  parche sólo actúa sobre el hilo que lo puso.
- **🧹 The Odds API, retirada.** Devolvía **401 en las 25 competiciones** y sólo
  llenaba el arranque de errores. Las cuotas vienen de `cuotas_multi` (Pinnacle
  881 partidos de fútbol, 64 de tenis, 39 de MLB, 57 de NBA) y de ESPN. Se
  eliminan `odds_api.py`, `cross_arbitrage.py` y `props_scraper.py`; se
  conservan las dos piezas que **no** tocaban la red (`sharp_gap_2via`, que se
  muda a `cuotas_multi`, y la lectura de `odds_historicas.csv` que alimenta el
  entrenamiento).
- **⏱️ «Apuestas del Día» se acota a las próximas 24 horas** desde la consulta,
  y por eso ahora **toda la Capa 1 lleva cuota real**. Para acotarlo de verdad
  hacía falta la hora de inicio, que ESPN publica y `fixtures_espn` estaba
  **tirando** al formatear a `'%Y-%m-%d'`. Las vistas por deporte y por liga no
  cambian.

## Novedades v87 — La ficha no miraba el mercado (ver [VALIDACION_v87.md](VALIDACION_v87.md))

Las tres tareas que quedaban abiertas se cierran, y **ninguna por el camino que
se había propuesto** — eso también es resultado.

- **⚓ El caso Puebla-Chivas, cerrado: la ficha ya se ancla al mercado.**
  Pinnacle, con el margen quitado, daba **Puebla 18,8 % · Chivas 59,4 %** y la
  ficha decía **Puebla 53,6 %**. Y esas cuotas **estaban en la app**: la ficha
  no las miraba porque sólo leía `odds_actuales.json` (4 partidos) y porque el
  ancla al mercado sólo alimentaba a dos ligas. Medido sobre 28.555 filas con
  cuota, en los partidos donde el modelo se aleja del mercado más de 0,25:
  **precisión 33,6 % → 55,5 % y ECE 0,2795 → 0,0644**. La ficha pasa de errar
  0,756 a **0,188** contra Pinnacle, muestra a **Chivas** como favorito y la
  coherencia local/visitante pasa de incoherente a coherente. Los picks salen
  idénticos: `alpha_finder` sigue desactivando la corrección.
- **🚫 El `w` por liga se midió y NO funciona.** Era la propuesta para cerrar
  Puebla. Con la población correcta (Liga MX pasa de ~0 a **1.311** filas
  útiles) resulta ser **la peor política en ECE** de las cuatro probadas. Y la
  prueba que lo entierra: barajando qué `w` le toca a cada liga, el ECE de
  validación sale igual o mejor **el 80 % de las veces**; la correlación con el
  mecanismo que se suponía es **+0,022 (p=0,88)**.
- **🤝 Cuando modelo y ELO discrepan, es empate.** Sobre 7.361 partidos con
  favorito distinto: el modelo acierta 36,34 % y el ELO 34,89 % (z=+1,84).
  «Hacer caso al ELO» no habría acertado más — por eso la solución era el
  mercado y no el ELO.
- **📐 El hándicap asiático ya está medido, y sin cuotas históricas.** No hacían
  falta: para calibrar se necesita la probabilidad y si se cubrió, y las dos
  salen de la misma matriz de marcadores que ya usa `alpha_finder`. **47.794
  partidos**, con la matriz analítica comprobada contra el Monte Carlo de
  producción (peor diferencia 0,00606 frente a un ruido propio de 0,00354).
  Resulta ser **el mercado mejor calibrado**: sesgos de −0,8 % a +0,7 %, frente
  al +27,4 % del BTTS.
- **🔧 Los modelos del CI ya se abren en Windows: 43 de 43 recuperados.** La
  propuesta era migrar a `save_model` (UBJSON) — y **no habría servido**: el
  buffer YA es UBJSON en los dos casos, con cabeceras idénticas. La causa real
  es que el pickle guarda el formato de **serialización**, que XGBoost documenta
  como dependiente del entorno, y que **contiene dentro** al formato de modelo.
  `modelos_portables.py` recorta esa sección y la carga por la ruta portable.
  Sobre los modelos que ya abrían no cambia nada (diferencia **1,7e−16**), y en
  Linux ni se ejecuta.

## Novedades v86 — La app se caía con dos usuarios, y el modelo no miraba el ELO (ver [VALIDACION_v86.md](VALIDACION_v86.md))

- **🩹 Arreglada la caída con varios usuarios a la vez.** No era misterio, era
  una cadena de tres fallos medidos. Al entrar, cada visitante ejecutaba
  `st.cache_data.clear()`, que es **del proceso, no de la sesión**: le borraba
  el caché a todos los que ya estaban dentro y —esto es lo letal— también el
  diccionario de cerrojos con el que Streamlit impide calcular dos veces lo
  mismo (`cache_utils.py:162-166`). Resultado: dos barridos de `alpha_finder`
  en paralelo. Medido: **uno pica 1.297,7 MB y dos a la vez 2.172,2 MB**, y el
  contenedor muere para los dos. Además el caché de motores de liga no tenía
  techo: **59,0 MB por liga** y **3.445 MB proyectados** a las 56 disponibles.
  Ahora el refresco corre una vez por proceso, el caché de ligas tiene
  `max_entries`, y `guardia_barrido.py` garantiza **un solo barrido**: cinco
  sesiones simultáneas lo comprueban en `test_concurrencia.py`.
- **✍️ Escritura atómica donde se escribía en cada predicción.**
  `predicciones_log.json` se reescribía con `open('w')`, que trunca el archivo
  a cero: con seis hebras, **34,4 % de lecturas corruptas**. Ahora **0 %**.
- **🧭 El modelo apenas responde a la fuerza de los equipos — y la auditoría de
  la v85 lo había diagnosticado mal.** Aquella medía correlaciones sobre
  emparejamientos **inventados** entre los 14 mejores equipos de cada liga, lo
  que comprime el rango de ELO y hace que la correlación acabe midiendo la
  forma. Sobre partidos reales no hay ni una liga invertida (mediana +0,76),
  pero eso **también engaña**, porque el ELO va correlacionado con la forma. La
  medición que decide es la **dependencia parcial**: mover sólo el ELO y
  congelar el resto. **Subir 600 puntos de ELO mueve P(local) +0,0751 de
  mediana; en Liga MX, +0,0173.** El usuario que reportó lo de Puebla tenía
  razón.
- **⚖️ Encogimiento hacia un prior de ELO en la ficha de partido (w=0,90).**
  Sólo donde no hay mercado —cuando lo hay, la corrección buena sigue siendo la
  de `calibracion_mercado`, y `alpha_finder` lo desactiva para que los picks
  salgan idénticos. Elegido en los pliegues 1-2 y validado en los 3-4:
  **ECE 0,0106 → 0,0045 (−58 %)**, log-loss +0,0098, precisión +0,0026. De 17
  ligas con el modelo plano o invertido respecto al ELO, **quedan 0**.
- **🚧 Un precio imposible ya no puede entrar en la Capa 1.**
  `valor_vs_sharp` no comprobaba que la cuota fuese un precio real: calculaba
  el EV y, como la lista va ordenada por EV, un dato corrupto se colocaba
  **arriba del todo**. En el histórico de tenis **una sola apuesta a 100× el
  precio de Pinnacle aporta el 26 % del ROI de +4,57 % de la WTA**. Techo en
  2,0× el sharp: bloquea entre el 0,02 % y el 0,23 % de los picks.
- **🎯 Goles y BTTS ya llevan su acierto REAL, no «no medido».** 47.794 partidos
  fuera de muestra. Y lo que aparece no es cosmético: **el BTTS al 80 % del
  modelo acierta el 53,2 %**, y está plano entre el 51 % y el 55 % diga lo que
  diga. Un pick de BTTS ahora se muestra corregido.
- **🛑 Y el histórico ya no puede INFLAR una probabilidad.** La banda de 1X2
  0,70-0,75 subía el 71,3 % del modelo a 81,8 %… con **n=33** e intervalo
  [69,7 %, 90,9 %]. Todas las demás bandas con muestra van al revés. Ahora se
  muestra `min(modelo, histórico)`.
- **🔬 Rechazado con números** (ver la tabla final de la validación): el
  `malloc_trim` para los 417 MB huérfanos del motor del Mundial (no hay Linux
  aquí para medirlo), el `w` de encogimiento por liga (sólo 20 de 9.870 fichas
  caen en ligas planas), el filtro de overround (bloquea line shopping
  legítimo) y el saneamiento del ATP como llave de la Capa 1 (**0/15**
  configuraciones robustas antes y después: los outliers no tapaban nada).

## Novedades v81 — El Kelly dinámico no era la mejora (ver [VALIDACION_v81.md](VALIDACION_v81.md))

- **💰 La fracción de Kelly sube de ⅛ a ¼, y por primera vez está medida.** El ⅛
  venía de la v27 como decisión de prudencia y nunca se optimizó. Monte Carlo
  por **bloques de 20** sobre la secuencia real de 589 picks (el bloque importa:
  un bootstrap i.i.d. destruye las rachas, que es justo lo que la política
  dinámica dice aprovechar): **capital mediano 1,760 → 2,592 (+47 %), p5
  1,178 → 1,193 (mejor) y ruina 0,00 % en ambas.** Contrapartida real: la caída
  máxima típica pasa de 14,6 % a 27,5 %. No se sube a ½ porque ahí el p5 cae a
  0,878 —en el peor 5 % se pierde dinero— y aparece ruina.
- **🚫 El Kelly DINÁMICO se midió y NO aporta.** 2,352 de capital mediano frente
  a 2,592 del ¼ liso, con el mismo p5. Acaba siendo una forma ruidosa de
  promediar entre ⅟₁₆ y ¼. La variante inversa (subir tras rachas malas) es aún
  peor: 1,515. **La racha reciente no predice la siguiente apuesta** — que es lo
  esperable si los picks son independientes, y si hubiera ganado lo primero a
  sospechar sería una fuga.
- **🎯 «Máxima Confianza»: se estudió poner techo en 0,75 y habría sido un
  error.** La tabla de bandas sugería que por encima de 0,75 el modelo promete
  79,6 % y acierta 57,8 %. Medido sobre el ledger con el precio que producción
  toma, esa banda es **la única con edge validado** (n=605, ROI **+20,92 %**,
  p5 **+3,71 %**), mientras la banda 0,70-0,75 pierde (−7,62 %). Las dos tablas
  miden cosas distintas: las bandas se calculan sobre la probabilidad **encogida
  del 1X2** y se muestran junto a picks de **hándicap y totales**, que no se
  encogen. Error de categoría documentado; la selección no se toca.
- **↕️ Todas las capas se ordenan por probabilidad descendente.** Antes la Capa 1
  iba por EV, así que un pick al 34 % podía salir por encima de uno al 58 %.
- **🔔 Dos avisos que apuntaban al sitio equivocado, corregidos.** «Picks sin
  calibrar» señalaba precisamente los picks **mejor anclados** (los de line
  shopping, cuya probabilidad ya *es* la del mercado). Y el de combinadas decía
  que faltaban picks con prob ≥ 55 % habiendo tenis al 88 %: lo que falta es
  **edge validado en un segundo deporte**, no probabilidad.

## Novedades v80 — La Capa 1 no tenía ni un pick del modelo (ver [VALIDACION_v80.md](VALIDACION_v80.md))

- **🔎 El diagnóstico de la v79 era incorrecto, y comprobarlo evitó días de
  trabajo inútil.** La v79 cerró diciendo que el fútbol de julio salía sin
  calibrar por «falta de histórico de cuotas sudamericano». Medida la cadena
  eslabón por eslabón: `liga_mx` tiene **5.086 cuotas de cierre —más que
  ninguna otra liga—** y `argentina` **7.193**, y aun así su peso era 1,00.
  Ingerir BetExplorer habría costado días y no habría arreglado nada de los 31
  partidos que más pesaban.
- **⚖️ Una liga sin peso medido ya no cae a «sin corregir», cae al w global.**
  Devolver 1,00 no era abstenerse: era elegir la opción que la evidencia global
  descarta. Medido con el método exacto de la validación (line shopping, un
  pick por partido): la política que había daba ROI +3,65 % con p5 **−1,11 %**
  —**sin edge validado**— frente a +5,92 % con p5 +0,34 % cayendo al global.
  Era la incoherencia de fondo: **lo que se validaba no era lo que se
  desplegaba**.
- **⚓ El ancla sharp solo llegaba a los partidos que ESPN NO cubría.** Una
  línea (`if fx.get('odd_home'): continue`) que en la v71 tenía sentido —solo
  rellenaba precios— y que desde entonces mataba en silencio el ancla de
  calibración, justo en los partidos populares. **23 de 160 fixtures** la
  tenían, con Pinnacle publicando precio para el **73 %** del día.
- **🥇 Lo más importante: la Capa 1 no contenía ni un pick del modelo.** Los
  diez picks de élite venían de `valor_vs_sharp` y se añadían **directos**,
  saltándose la calibración y `pasa_capa1`. De ahí lo que se veía: «Empate ·
  EV +9,5 % · **prob 29 %**» como pick de élite. Esa estrategia **nunca se
  había medido**. Medida ahora sobre **26.647** partidos: sí tiene edge, pero
  subir el margen de EV —lo intuitivo— es lo que peor generaliza (el máximo del
  barrido pasa de p5 +10,09 % a **−9,44 %** fuera de muestra). Lo que da
  robustez es el **piso de probabilidad**: con margen 1 % y prob ≥ 30 % el p5
  sale **+3,92 % y +3,91 %** en los dos periodos. Adoptado: la Capa 1 pasa de
  10 picks (prob 0,199-0,579) a **6, todos con prob ≥ 0,327**.
- **⚾ MLB: la estadística real del abridor ya es accesible… y no sirve.** La
  v79 la dio por inviable (~900 lanzadores por temporada); son **873 en una
  petición de 1,2 s**, y ya están ingeridos (10.421 filas, 2.850 lanzadores).
  Con ella **el ratio de dispersión se mueve por primera vez** (0,527 → 0,564)
  y la precisión gana +0,32 pp. Pero la prueba de rentabilidad —rehecha con el
  emparejamiento **verificado**, porque la primera dio +31,75 % de ROI, que era
  la misma desalineación que fabricó el +37,68 % en la v78— dice lo contrario:
  **ROI +1,65 % → −2,83 %**. **Rechazadas.** Mejor probabilidad no es mejor
  negocio, con las tres métricas de calidad apuntando al revés que la caja.
- **🎲 El devigado que se usaba era el correcto, y ahora está medido.** De ese
  paso cuelga el ancla, el `valor_vs_sharp` y la validación entera, y la
  elección de `potencia` estaba escrita como argumento razonable pero sin
  comprobar. Comparados cuatro métodos —incluido el de **Shin**, el estándar
  académico— sobre 36.006 + 26.666 + 53.685 partidos: `potencia` gana en los
  tres. No cambia nada… salvo que **el valor por defecto de `devig()` era
  `proporcional`, que pierde en los tres**. Corregido.

## Novedades v79 — MLB predecía 2026 con la forma de 2025, y el barrido tardaba el doble (ver [VALIDACION_v79.md](VALIDACION_v79.md))

- **⚾ El «todo da 50-50» era de MLB, y tenía tres causas.** Medido: el 58,5 %
  de los emparejamientos caía entre 45 % y 55 %. (1) El estado del modelo
  llevaba **304 días congelado** — Retrosheet publica los game logs por
  temporada cerrada, así que la 2026 se predecía con el ELO y la forma del
  final de 2025. (2) Tres de las nueve features eran **constantes** en
  inferencia: `apuestas_dia` predecía sin abridores ni fecha, y el abridor es
  la variable que más pesa en béisbol. (3) `entrenar()` estaba **roto desde la
  v78** (`Timestamp` no serializable), así que el modelo ni siquiera se podía
  reentrenar. El fútbol nunca estuvo aplanado: repartía entre 20 % y 85 %.
- **📡 Fuente nueva: la API oficial de la MLB.** `statsapi.mlb.com` es gratuita
  y sin clave, y da una temporada completa (2.464 juegos) en **una petición de
  1,6 s**, con marcador y **abridor probable**. El histórico pasa de 24.778
  juegos (hasta 2025-09-28) a **26.395 (hasta 2026-07-28)**. De paso se
  descubrió que la franquicia de Oakland estaba **partida en dos** (`OAK` hasta
  2024, `ATH` desde 2025): había 31 códigos para 30 equipos y su ELO se
  reiniciaba a mitad del dataset.
- **⚡ Apuestas del Día: 197,9 s → 104,3 s (−47 %), sin quitar ni una feature.**
  Perfilado, no adivinado. El cuello no era la red: era el emparejamiento
  difuso de nombres (2,8 millones de llamadas a `normalizar` sobre un puñado de
  nombres distintos) y el `n_jobs=-1` heredado del entrenamiento, que gastaba
  0,12 s **por predicción de una sola fila** en coordinar procesos. La diferencia,
  fila a fila o en lote, es del orden del epsilon de máquina (~1e-16) por la no
  asociatividad de la suma en coma flotante, no por el modelo.
- **🛡️ El tenis ya no puede desaparecer por un fallo de calibración.** El
  `AttributeError` que borró los 319 partidos del día venía de Streamlit, que
  conservaba en `sys.modules` un módulo de la v77. `calibracion_segura.py`
  recarga el módulo si hace falta y, si aun así no puede, devuelve la
  probabilidad sin corregir en vez de tumbar el deporte entero.
- **🔁 `pick_ledger_total.csv` ya tiene constructor.** De él dependen el peso de
  cada liga, las bandas de confianza y **qué deportes entran en la Capa 1**, y
  no lo escribía ningún script: se había hecho a mano en la v78 y se quedaba
  obsoleto en silencio.
- **⚠️ El pick de julio NO es el que se validó (lo más importante de la
  versión).** Al exponer la calibración del fútbol salió un **0 %**: ni un solo
  pick llevaba corrección de mercado. No era falta de cuota sharp (Pinnacle
  cubre el 73 % de los partidos de hoy) sino que **`calibracion_mercado.json`
  no tiene peso para las ligas que juegan en julio**: la tabla se construye
  desde un ledger que cubre sobre todo Europa, y en julio Europa está de
  vacaciones. **18 ligas con peso medido y sin partidos; 20 ligas jugando sin
  peso; cobertura real 49 de 160 partidos = 30,6 %.** Importa porque el edge
  del fútbol se midió *en w=0,25* (+6,72 % ROI, p5 +0,92 %) y con w=1,00 —lo
  que sale hoy— el mismo histórico da +0,47 % con p5 −2,62 %, o sea **sin
  edge**. Esta versión lo deja **a la vista con una incidencia explícita** en
  la interfaz; arreglarlo exige histórico de cuotas sudamericano y es la
  prioridad de la v80.
- **🎾 Tenis: la WTA adopta 13 features, el ATP no — y la diferencia la decide
  un contraste, no un umbral a ojo.** Se remidieron las 5 variantes de vector en
  los dos circuitos. El A/B automático dijo «adoptar» en ambos, y era un
  espejismo: el umbral lo había fijado yo y las dos ganancias caían justo
  encima, con **10 combinaciones probadas**. Un **bootstrap pareado** (5.000
  remuestreos sobre la diferencia partido a partido) lo resuelve: **ATP no
  sobrevive** (IC 90 % toca el cero, p1 Bonferroni −0,00037) y **la WTA sí**
  (100 % de remuestreos positivos, p1 +0,00047). WTA reentrenada: precisión
  **0,6341 → 0,6401**. Aun así **el tenis sigue fuera de la Capa 1**: su ROI
  pasa a +1,85 % pero sobre **112 apuestas en vez de 1.971** y con p5 −9,55 %
  — eso no es edge, es una muestra más pequeña.
- **🔇 Dos fallos silenciosos que me hice yo al reconstruir.** Reconstruir un
  deporte **borraba a los demás** del ledger (64.587 filas de tenis
  desaparecieron sin aviso, y de ese fichero sale qué deportes entran en Capa
  1). Y la **caja de la clave** decidía si un deporte se calibraba:
  `peso_modelo('atp')` daba 1,00 y `peso_modelo('ATP')` 0,25, así que el tenis
  se quedaba sin encoger en silencio. Los dos corregidos y con test.
- **🔬 Lo que se midió y se rechazó.** Ocho features nuevas para MLB (abridor
  encogido, factor de parque, ELO por margen, descanso del abridor): **no
  mejoran** (log-loss 0,6834 vs 0,6833; precisión 0,5599 vs 0,5647). El ratio
  de dispersión no se mueve de 0,527 con ninguno de los dos vectores, lo que
  dice que el techo está en las estadísticas de equipo, no en cómo se combinan.

## Novedades v71 — Cuotas sin límite y el porqué del ROI negativo (ver [VALIDACION_v71.md](VALIDACION_v71.md))

- **💰 Cuotas en vivo sin cuota de API.** El «sin cuota en vivo» generalizado
  tenía una causa concreta: **The Odds API estaba a 0 de 500 peticiones
  mensuales**. La arquitectura gastaba una petición por liga y hasta 3 capturas
  al día. Ahora las cuotas salen del **endpoint público de Pinnacle** (610
  partidos de fútbol, **297 de tenis**, MLB y NBA, sin clave ni límite) más
  ESPN. Cobertura medida: **93,3 % de los partidos de hoy** y 74,2 % a dos días.
  A 5-7 días cae al 3 % porque *ninguna casa ha abierto línea todavía*.

- **📅 2.925 partidos recuperados.** `MESES_SIN_UEFA=(7,)` saltaba **julio
  entero** en toda liga de formato ESPN — correcto para las competiciones UEFA,
  desastroso para las de año natural. **21 ligas afectadas**; Bolivia se quedaba
  en el 2 de junio y Rusia en el 17 de mayo mientras ESPN tenía partidos hasta
  el 27 de julio. El aviso «sin datos nuevos (pretemporada)» era falso en 15
  ligas. Tras reentrenar, las 5 que siguen marcadas están en **parón real**.

- **🔍 Diagnóstico del ROI negativo.** Con Pinnacle como ancla se midió el
  modelo contra el mercado sharp en 315 selecciones. El sesgo **global** es
  0,0000 — pero el sesgo **en la selección que el modelo elige** es de **+4 a
  +13 pp** según la liga. Es la maldición del ganador: al tomar el argmax se
  toma justo donde el ruido fue favorable, y como el EV se calcula sobre esa
  cifra inflada, la Capa 1 se llenaba de apuestas perdedoras. Corregido
  encogiendo la probabilidad hacia el mercado, con peso por liga.

- **🎯 Capa 1 ya no se queda vacía por calendario.** El horizonte del barrido lo
  marcan las cuotas abiertas, no un corte fijo de 72 h: Liga MX juega el 1 de
  agosto y quedaba fuera pese a tener sus 9 partidos con cuota.

- **👟 Remates por JUGADOR.** Fuera los totales por equipo y de partido de la
  plantilla y de las combinadas — ninguna casa los lista. En su lugar, props de
  jugador con datos **observados** de los rosters de ESPN: 48 en un Liga MX,
  con tiros esperados y P(1+/2+/3+) y a puerta.

- **🖱️ Sin pasos manuales.** Fuera los botones de «Cargar» y «Traer cuotas»:
  elegir un partido carga sus datos y sus cuotas solo, en todos los deportes.

## Novedades v70 — Un modelo por liga y las λ recalibradas (ver [VALIDACION_v70.md](VALIDACION_v70.md))

- **🧩 La familia de modelo se elige por competición, no por un umbral de
  tamaño.** El spec proponía «logística si hay menos de 800 partidos», pero al
  medir sólo 4 de las 15 ligas que perdían contra el ELO en v68 bajan de 800: el
  EFL Championship pierde con 2.144. El problema es la relación señal/ruido, así
  que se compiten seis familias por liga en **walk-forward de 5 pliegues con
  selección secuencial** (la familia de cada pliegue se decide con los pliegues
  anteriores, nunca con el propio test). **8 competiciones pasan a batir al ELO
  y entran en Capa 1**: Brasileirão Série B, Copa Sudamericana, LaLiga
  Hypermotion, Costa Rica, EFL League Two, Bélgica, EFL Championship y Grecia.
  La logística regularizada gana en 5 de las 8.

- **📉 Las λ separaban demasiado a los dos equipos — hallazgo no previsto.**
  Validando el ajuste por alineaciones, un control detectó una correlación de
  **−0,19 (MLS) y −0,24 (Liga MX)** entre la diferencia de goles esperados y el
  residuo del margen: cuando el modelo predice una goleada, el marcador real se
  queda corto de forma sistemática. La corrección —encoger la diferencia de λ
  hacia su media conservando el total, con `s` calibrado por liga— **mejora la
  desvianza de Poisson en las 15 competiciones medidas y también en MLB**.
  Adoptada en 14 ligas + MLB. Afecta al marcador exacto y a los mercados de
  goles, no al 1X2.

- **🏀 El motor NBA ya bate a su propia línea base.** Las features de fatiga y
  estadística avanzada que pedía el spec **no aportan** (todas bajan la
  precisión), pero el experimento destapó que el ensemble de 9 features
  sobreajustaba: no superaba al argmax del ELO. Una mezcla con una logística de
  **un solo grado de libertad sobre el ELO** sube el moneyline de 0,6544 a
  **0,6721** y ahora sí supera al ELO (0,6664).

- **🐛 1.225 juegos NBA duplicados, corregidos.** `nba_scraper` deduplicaba por
  `GAME_ID`, pero la API lo sirve como cadena con ceros a la izquierda y el CSV
  lo relee como entero: cada actualización volvía a duplicar la temporada en
  curso. **7.365 filas → 6.140 reales.**

- **📋 Medido y rechazado, con los números publicados**: ajuste por alineaciones
  confirmadas (+0,07 pp, signos que se invierten entre ligas — y eso con
  cobertura del 92,6 % y 268.000 filas de alineaciones reales recolectadas de
  ESPN), impacto del portero (γ = 0 en los 10 pliegues), P(BTTS) como feature
  del 1X2 (2 de 7 ligas, lo esperable por azar) y el modelo de carreras de MLB
  (el clasificador actual calibra mejor: ECE 0,0093 vs 0,0167).

## Novedades v69 — Estadísticas de saque en tenis (ver [VALIDACION_v69.md](VALIDACION_v69.md))

- **🎾 Encontrada la fuente que v67 dio por inexistente.** ATP Tour y SofaScore
  devuelven 403, pero **TennisAbstract publica el esquema Sackmann completo**
  (aces, dobles faltas, puntos al saque, 1os dentro/ganados, break points) en el
  array `matchmx` de cada página de jugador. **54.308 partidos ATP y 220.500
  WTA** descargados y validados.
- **✅ Datos verificados, no supuestos**: 99.9 % de coherencia interna sobre
  2.300 partidos, y las medias coinciden con la realidad de cada circuito
  (64.06 % de puntos ganados al saque en ATP, 60.39 % en WTA).
- **🐛 Defecto que casi tira la mejora**: TennisAbstract fecha por el INICIO DEL
  TORNEO, no por el día del partido — todo Wimbledon comparte una fecha. El
  enlace por fecha exacta casaba solo el **4.2 %**; corregido a pareja de
  jugadores + ventana, sube al **34.5 %**.
- **❌ Features NO adoptadas**: `DIFF_ELO_SAQUE`, `DIFF_SPW` y `DIFF_RPW` dan
  −0.08 pp de precisión y −0.0023 de log-loss. No pasan la regla de oro; el
  signo cambia en cada ventana (ruido). Causa medida: techo de cobertura del
  34.5 % y colinealidad con el ELO por superficie.
- **📦 Lo que sí se sube**: `tenis_saque.py`, los datos comprimidos
  (`saque_*.csv.gz`, 34 MB → 3.3 MB) y el enlace corregido, para que cualquier
  reevaluación futura arranque sin volver a raspar.

## Novedades v68 — 40 competiciones nuevas (ver [VALIDACION_v68.md](VALIDACION_v68.md))

- **⚽ De 27 a 67 competiciones** en el catálogo y de 23 a **45 desplegadas**.
  Cada una desde la mejor fuente que la sirva: 11 de football-data `/mmz4281/`
  (con remates, córners y cuotas), 1 de `/new/` y 28 de ESPN.
- **✅ 37 entrenadas · 22 adoptadas** (baten al ELO, regla del proyecto desde
  v39) · **3 baten también al mercado**: Scottish Premiership, J1 League y
  Ligue 2. Las 15 que no lo superan quedan documentadas con su número.
- **🔍 Trampas de las fuentes**: football-data devuelve HTTP 200 para códigos
  inexistentes (60 países falsos → 16 reales al validar el contenido) y dejó de
  servir `/new/` por HTTP plano. El dropdown de ESPN está curado: 11 ligas que
  no aparecen ahí sí las sirve la API.
- **🚨 22 modelos de liga ilegibles** detectados por el smoke test y reparados.
  El workflow de reentrenamiento ahora **verifica que cada modelo se pueda
  cargar** antes de publicarlo; antes solo miraba el código de salida.
- **❌ Cópula bivariante NO adoptada**: parecía ganar en 1X2 pero el ρ óptimo
  huye al borde de la malla sin óptimo interior — es absorción de sesgo, no
  dependencia. Mismo modo de fallo que Dixon-Coles en v27.
- **📋 Diagnóstico honesto del spec v68**: la caché de FotMob tiene 28 partidos,
  el histórico de alineaciones 204 filas y no hay ni una cuota de BTTS. Las tres
  mejoras se replantearon sobre datos que sí existen.

## Novedades v67 — Tenis multicompetición y remates reales por jugador (ver [VALIDACION_v67.md](VALIDACION_v67.md))

- **🎾 Tenis por competición**: selector con Grand Slams (M/F), ATP, WTA,
  WTA 125, Challenger e ITF. ATP 66.570→**72.891** partidos, WTA
  43.821→**56.213**; jugadores cubiertos 1.820→**2.136** (ATP) y
  1.319→**2.000** (WTA).
- **✅ Sin degradar**: sobre el circuito principal (métrica comparable),
  ATP 0.6522→**0.6555** y WTA 0.6486→**0.6574**.
- **📅 Próximos partidos de tenis desde ESPN** a 10 días, refresco automático
  cada 20 min. **Se eliminó el botón «Cargar»**: al elegir el partido se ven las
  estadísticas directamente, con superficie y formato (bo3/bo5) deducidos.
- **🎲 El tenis ya tiene parlays combinados** y envío a Telegram, como el resto
  de deportes. Antes no tenía: su plantilla no publicaba `secciones` y el
  generador no veía ninguno de sus 33 mercados.
- **🎯 Remates y remates a puerta REALES por jugador** (`remates_jugadores.py`),
  desde la estadística por jugador de ESPN. Antes eran un estimado derivado de
  los goles y solo salían los goleadores. Disponible en la vista internacional
  **y** en cada liga.
- **🔍 Auditoría de fuentes**: los repos `JeffSackmann/tennis_atp` y
  `tennis_wta` —la fuente estándar del tenis— **ya no existen**. Documentado
  con qué se sustituyen y qué queda sin cubrir (ITF masculino y UTR: sin fuente
  gratuita; la API de UTR solo expone eventos amateur).
- **❌ Features de nivel de competición NO adoptadas**: degradan el ATP 0.49 pp
  y en la WTA mejoran +0.01 pp (ruido).

## Novedades v66 — El modelo internacional pasa de 49 a 200 selecciones (ver [VALIDACION_v66.md](VALIDACION_v66.md))

- **🌍 De 49 a 200 selecciones** seleccionables. Criterio reproducible (≥100
  partidos en el histórico desde 1990) generado por
  `generar_universo_selecciones.py` → `config_selecciones.py`.
- **📅 Fixtures internacionales: de 30 a 163 de 163** partidos programados de
  ESPN enlazan con el modelo. **Cero nombres sin mapear.**
- **🔍 Hallazgo**: `TEAMS` nunca filtró los datos de entrenamiento — el modelo
  llevaba versiones entrenándose con las 326 selecciones del histórico (sólo el
  17 % de las filas tiene a los dos equipos entre las 49). El límite era de
  **superficie**: `team_stats.json`, el selector y el mapeo de fixtures.
- **📊 Hallazgo 2**: el «60 % de precisión» está dominado por partidos
  desnivelados. Entre las 49 del Mundial el modelo acierta **~50 %**. Ahora
  `metadata.json` publica los tres números por separado para que las
  comparaciones entre versiones sean válidas.
- **✅ Sin degradación**: precisión 0.5986→**0.6008**, log-loss
  0.8756→**0.8697**, y sobre las 49 originales 0.5000→**0.5023** /
  0.9863→**0.9824**. Walk-forward 0.5960/0.8716→**0.5967/0.8683**.
- **🔁 Interruptor de rollback**: `MUNDIAL_UNIVERSO=v65` devuelve todo el
  proyecto a las 49 selecciones sin tocar código.
- **⚡ Escala**: `team_stats.json` 85→385 KB (irrelevante para Streamlit);
  el H2H O(n²) (19.900 parejas) pasa a recorrido lineal sobre cruces reales.
- **❌ Feature «nivel de datos» NO adoptada**: mejora el log-loss en los tres
  protocolos pero la precisión va en direcciones distintas — ruido de
  comparaciones múltiples. Queda tras `MUNDIAL_NIVEL_DATOS=1`.

## Novedades v34 — Cobertura universal (ver [VALIDACION_v34.md](VALIDACION_v34.md))

- **📈 Cobertura ×4.4: de 11 a 48 partidos evaluados** al día, en 10 ligas y
  3 deportes, con **0 partidos sin mapear**. Tres palancas: 5 ligas de verano
  nuevas (Noruega, Suecia, Finlandia, Rumanía, Irlanda), horizonte 48→72 h y
  `name_mapper.py` (alias + normalización + fuzzy con registro de fallos).
- **🔍 Hallazgo mayor**: sobre 480 días reales, **el filtro de EV extremo de
  la v32 convierte un −94.8 % de ROI en −8.1 %** (87 pp). La validación más
  fuerte que ha tenido una decisión del proyecto.
- **❌ Markowitz descartado**: concentra peso en los picks peor calibrados;
  volatilidad 4× la de Kelly y ruina total incluso con filtro.
- **📡 Valor en Vivo**: evolución del EV y tendencia de la línea leyendo solo
  los snapshots ya guardados — **cero peticiones a la API**.
- **🏀 NBA se activará sola** en octubre (ventana de temporada integrada), y
  el presupuesto de la API se adapta al saldo mensual.
- ⚠️ *Nota honesta*: ninguna variante histórica da ROI positivo todavía; el
  panel de Rendimiento Real es el que dará el veredicto con los picks nuevos.

## Novedades v33 — Verano, resiliencia y bot (ver [VALIDACION_v33.md](VALIDACION_v33.md))

- **🇧🇷 Brasileirão y 🇦🇷 Primera argentina** añadidas para cubrir el parón
  europeo. **Brasil bate al mercado (52.3 % vs 52.1 %)**. Japón NO se añade:
  football-data lleva 228 días sin publicarla (verificado).
- **🛡️ Cadena de resiliencia** (`source_resilience.py`): fuentes en cascada
  con degradación elegante. **Probada con fallo forzado**: la primaria cae y
  ESPN toma el relevo; si todas fallan, no rompe nada.
- **⏱️ MLS al día**: el estado de 58 días obsoleto que detecté en v32 está
  resuelto (reentrenada con datos al 18 de julio) y sale de la cuarentena.
- **🤖 Bot de Telegram** con GitHub Actions (cron diario), credenciales solo
  desde Secrets, y `--update-only` para refrescar datos en el runner.
- **📊 Umbrales adaptativos por deporte** y **semáforo de antigüedad** de
  datos (🟢/🟡/🔴) en cada pick.
- **❌ ELO Ataque/Defensa descartado**: 4 de 6 ligas se degradan (hasta
  −2 pp); los dos "positivos" son ruido de comparaciones múltiples.
- **📐 Optimizador de cartera** (Markowitz con covarianza diagonal entre
  deportes) como módulo experimental, sin sustituir al Kelly.

## Novedades v32 — Blindaje cuantitativo y plantillas realistas (ver [VALIDACION_v32.md](VALIDACION_v32.md))

- **🚫 Filtro de EV extremo, probado con datos**: los picks con EV > +15 %
  aciertan **15 pp por debajo** de lo prometido y su ROI es **12 pp peor**
  (1,495 apuestas históricas). Se segregan a una sección oculta por defecto.
- **🪜 Reto Escalera**: picks ≥85 % con suelo de cuota 1.05, un pick por
  partido y **Monte Carlo de 10.000 escaleras** (ruina a 10/20/30 días). Si
  no hay picks del nivel, se niega a arrancar en vez de rebajar el listón.
- **🥇 Pick del Día único** con desempate Brier → EV → probabilidad, y
  **fiabilidad histórica por liga** (Brier real de los picks publicados,
  traducido a 🟢/🟡/🔴).
- **📋 Plantillas ampliadas con rigor**: NBA/MLB suman spread y totales por
  equipo desde el margen ~N(μ,σ) con σ calibrada (15.58 / 4.48); tenis pasa
  a **19 mercados** (total y hándicap de juegos con regresión sobre 68k
  partidos, reparto de sets). Lo no derivable se declara excluido.
- **📊 Rendimiento real** persistido en SQLite (WAL) y **copiado al
  portapapeles**.

## Novedades v31 — Apuestas del Día universales (ver [VALIDACION_v31.md](VALIDACION_v31.md))

- **🌐 Cobertura universal**: el barrido recorre ahora **todas** las
  competiciones (11 de fútbol + MLB + NBA + tenis ATP) instanciando cada
  motor. Barrido real: 7 picks en 3 deportes simultáneos.
- **🎯 Doble capa**: **Capa 1** (cuota real + EV + stake Kelly) y **Capa 2**
  (alta confianza sin cuota en vivo → cuota mínima sugerida, sin stake).
- **🎾 Cuotas de tenis vía Betexplorer** con fuzzy matching de nombres
  (9/10 emparejados). Los no enlazados se reportan, nunca se descartan en
  silencio. *(Ojo: las URLs `matches-today` no existen — la ruta real es
  `/next/tennis/`; verificado.)*
- **🧹 Sin deprecaciones**: 34 `use_container_width` → `width`.
- **❌ Decaimiento inter-temporada descartado** con evidencia (peor incluso
  al inicio de temporada, que era la hipótesis).
- Bugs corregidos: serialización Arrow del panel de rendimiento y tarjetas
  defensivas para picks sin cuota.

## Novedades v30 — Tres deportes nuevos, CDI y fix crítico (ver [VALIDACION_v30.md](VALIDACION_v30.md))

- **🔧 Fix crítico de exportación**: el `AttributeError` al exportar las
  Apuestas del Día está resuelto de raíz y **blindado** (try/except +
  firma opcional) — nunca vuelve a romper la página.
- **🏀 NBA — motor nuevo** (nba_api, 6.1k juegos): OFF/DEF rating, pace,
  back-to-back + **CDI**; 65.4 % ≈ ELO, modo analítico hasta octubre.
- **🎾 Tenis ATP — motor nuevo** (Kaggle, 68k partidos con superficie y
  cuotas): **ELO por superficie**, 64.9 % vs ranking 63.3 % (+1.6 pp). El
  mercado (68.3 %) es más afilado → modo analítico honesto.
- **🧬 CDI (Índice de Desincronización Circadiana)**: husos cruzados por el
  visitante. **Adoptado en NBA** (ll 0.644→0.629) y **descartado en MLB**
  con evidencia — la señal circadiana existe en baloncesto, no en béisbol.
- **⚾ MLB** consolidado (motor v29 intacto); umpire y live-API diferidos.

## Novedades v29 — Ecosistema multi-deporte (ver [VALIDACION_v29.md](VALIDACION_v29.md))

- **⚾ MLB (béisbol) — motor nuevo validado**: Retrosheet (11.9k juegos
  2021-25, con abridores) + ensemble XGB+LGBM+RF calibrado. Walk-forward
  **55.0 % vs ELO 54.2 %** (supera en ambas ventanas). Cuotas en vivo de
  The Odds API (`baseball_mlb`) y Apuestas del Día MLB propias.
- **🏗️ Arquitectura DRY**: `engines/BaseSportsEngine` (clase base abstracta)
  para deportes nuevos; el fútbol queda intacto y aislado (no regresión).
- **🔎 NBA y tenis diferidos con evidencia**: basketball-reference bloqueado
  (Cloudflare) + NBA fuera de temporada; el repo de tenis de Sackmann da 404
  y The Odds API no tiene mercado de tenis en la capa gratuita — sin fuente
  viable no hay motor validable ni accionable (se reevalúan en v30).
- **📋 Exportar Apuestas del Día** (TXT/CSV) y **cobertura Liga MX
  corregida** (fuzzy nombre→liga; el barrido descartaba en silencio los
  partidos que no mapeaban exacto).

## Novedades v28 — Dos carriles y traductor cognitivo (ver [VALIDACION_v28.md](VALIDACION_v28.md))

- **⏳ Auto-cuotas nativas**: la app se actualiza sola cada 6 h
  (`st.cache_data`, sin subprocesos) con presupuesto real de The Odds API
  (~16 req/día; salta si quedan <50 créditos, con aviso).
- **📈 Acelerador RLM**: snapshots tier-1 (5 ligas, hasta 3/día) alimentando
  `odds_historico.db` — el Shadow con RLM para Bundesliga/Eredivisie queda
  calendarizado a +60 días de acumulación.
- **⚖️ Índice VACA** en el arbitraje cruzado (EV/volatilidad, escala
  adaptada y documentada): solo oportunidades estables (ν>1).
- **⭐ EVC Platino**: triple validación (EVC ∧ arbitraje ν>1 ∧ sin
  divergencia) con stake ×1.5 pre-cap en el Kelly simultáneo.
- **❌ Weibull Over 2.5 descartado con evidencia** (Brier 0.268 vs 0.250 de
  la matriz): para totales, el conteo Poisson gana; el Weibull se queda
  donde demostró valor (BTTS).
- **🧠 Traductor Quant**: el modo Principiante traduce toda la jerga
  (glosario + tooltips deterministas, sin depender de ningún LLM).
- **🧪 Carril B** (rama `experimento/bottom-up`, sin fusionar): PFI por
  ratings FotMob (787 ratings acumulados) + índice de cohesión Jaccard;
  el VORP-PFI espera cobertura de datos (brecha documentada).

## Novedades v27 — Precisión estructural y riesgo quant (ver [VALIDACION_v27.md](VALIDACION_v27.md))

- **⏱️ BTTS oficial por supervivencia**: el Weibull AFT venció también al
  baseline de matriz con choque común (Brier 0.236 vs 0.251, 6/6 ventanas)
  — transición completada en la plantilla del Mundial; 1X2 intacto.
- **❌ Dixon-Coles descartado con evidencia**: el ρ óptimo en train sale
  POSITIVO (sobreajuste) y no mejora el log-loss del marcador en validación.
- **👤 Shadow 2.0**: castigo narrativo (ELO_VEL × entropía) adoptado en
  **LaLiga (+5.1→+7.3 % ROI)** y **Ligue 1 (−9.3→−0.2 %)**; la MLS conserva
  su variante v1 (+2.6 %) porque el CN la empeoraba — feature por liga.
  RLM documentado como forward-only (falta histórico de snapshots).
- **💎 EVC 2.0**: doble validación (élite ∧ Shadow conforme) con descarte
  por divergencia crítica y stake del **Kelly simultáneo ⅛ + cap 20 %**
  (drawdown máximo 24 %→13 % en Montecarlo comparativo).
- **💹 Arbitraje cruzado** ([cross_arbitrage.py](cross_arbitrage.py)):
  valora double chance / DNB / totales alternativos (.5) con la matriz
  exacta vs cuotas por evento (los SGP pre-empaquetados no existen en la
  capa gratuita — verificado). Con corrección de push en líneas enteras.
- **🕵️ Abogado del diablo** en el comentario del analista cuando el modelo
  y el Shadow divergen (determinista, con o sin Ollama).

## Novedades v26 — Arquitectura de tercera generación (ver [VALIDACION_v26.md](VALIDACION_v26.md))

- **🧮 Features ortogonales adoptadas en 6 de 10 ligas** tras walk-forward
  ([features_v26.py](features_v26.py)): derivadas del ELO (Serie A +0.5,
  Bundesliga +0.4, Eredivisie +1.2 pp), urgencia asimétrica (LaLiga +1.0,
  **Champions +1.7 pp**) y entropía/volatilidad (MLS +0.65 pp). Con ello
  **Serie A alcanza al mercado (57.1 % vs 57.1) y Bundesliga lo iguala a
  modelo puro (55.0 vs 55.0)**.
- **👤 Shadow Booster** ([shadow_booster.py](shadow_booster.py)): XGB sobre
  el residuo del cierre (Pinnacle) con OOF leak-free. **El mercado resultó
  eficiente en 7/9 ligas (documentado); ADOPTADO en MLS** (ROI +2.6 % vs
  −7.8 % del base, 747 apuestas): señales ⚡ en Apuestas del Día.
- **⏱️ Supervivencia BTTS** ([supervivencia_btts.py](supervivencia_btts.py)):
  Weibull AFT censurado en numpy puro (lifelines rechazado: rompía el pin de
  pandas). Brier 0.236 vs 0.252 del baseline en 6/6 ventanas — segunda
  opinión visible en la vista del Mundial.
- **💎 Apuestas del Día + 📈 Montecarlo** ([alpha_finder.py](alpha_finder.py),
  [montecarlo_sim.py](montecarlo_sim.py)): barrido multi-liga con filtros de
  élite (prob >70 %, EV >+3 %, cuota >1.50) y simulador de bankroll con
  percentiles y probabilidad de ruina.
- **🔑 The Odds API activa**: 337 cuotas/día agrupadas por liga + BTTS por
  evento; `odds_historico.db` acumulando CLV; fuera de temporada europea la
  API es la fuente viva de Liga MX/MLS (MESM y blending operan hoy).
- **🎯 Calibración verificada**: ECE local 0.0138 sobre 7,364 OOF — sin
  sesgo de localía; VENTAJA_LOCALIA intacta.
- **CLV Pinnacle**: `roi_sim` reporta ROI con cierre Pinnacle junto a B365.

## Novedades v25 — Parlays reales, EV completo y CLV (ver [VALIDACION_v25.md](VALIDACION_v25.md))

- **🎲 Correlación SGP empírica** ([sgp_correlation.py](sgp_correlation.py)):
  el haircut fijo 0.95 se reemplaza por factores por PAREJA de mercados
  (cópula gaussiana simplificada, φ de 10,514 partidos). Validado FUERA de
  muestra: el error de la probabilidad conjunta cae de 0.049 a 0.0034
  (−93 %). Truncado a f ≤ 1 para no fabricar EV+ ilusorio.
- **📈 CLV** ([odds_api.py](odds_api.py)): The Odds API agrupada por liga
  (h2h + O/U 2.5 + BTTS) + almacén SQLite `odds_historico.db` con marca de
  tiempo — también captura las fuentes gratuitas, así que el CLV acumula
  desde hoy sin clave. Sección EV ampliada: 1X2, O/U 2.5, BTTS y AH ±0.5,
  con aviso de frescura (>6 h).
- **⚖️ Blending 70/30 ADOPTADO en LaLiga y Ligue 1** (walk-forward:
  53.33→54.09 y 51.65→52.17 con log-loss mejorando en ambas).
- **🧪 VORP experimental** ([alineacion_vorp.py](alineacion_vorp.py)):
  ajuste de λ por alineación confirmada (ESPN) con fallback ESTRICTO
  (aborta si <10 titulares parseados con fuzzy >0.85). El 1X2 no se toca.
  Evaluación en 2026-27 con vorp_log.json.
- **🇺🇸 MLS clima extremo: DESCARTADO con evidencia** — backfill Open-Meteo
  completo (1,801 partidos-día) y walk-forward: la feature resta 0.7 pp.
  Documentado; la caché queda acumulando.
- **🎯 SmartParlayBuilder**: lista blanca dinámica (solo mercados con cuota
  real) + control de categorías por el usuario.
- **🆚 Comparador rápido** de dos partidos en todas las competiciones.
- Champions IMT reintentado: sin partidos nuevos, sigue fuera por 0.003 de
  log-loss — se reintenta cuando arranque la 2026-27.

## Novedades v24 — FotMob, MLS y el Índice de Momentum Táctico (ver [VALIDACION_v24.md](VALIDACION_v24.md))

- **📈 Índice de Momentum Táctico (IMT)** ([momentum_tactico.py](momentum_tactico.py)):
  IMT = α·M + β·ΔxG + γ·F + δ·P — momentum exponencial de resultados,
  tendencia de xG, fatiga por congestión y subidón/bajón tras resultados
  extremos, en pase cronológico SIN fuga. A/B de tres variantes en
  walk-forward por liga: **adoptado en 5 de 10 ligas** (Liga MX +0.4 pp,
  Eredivisie +0.6, Primeira +0.6, LaLiga ll −0.042, Bundesliga +0.3);
  descartado con evidencia en Premier/Serie A/Ligue 1/MLS/Champions.
- **🏆 Liga MX cruza el objetivo: 55.4 % vs mercado 53.5 %** (IMT compuesto
  + MESM revalidado). Primeira también bate al mercado (56.2 % vs 56.1 %).
- **🇺🇸 MLS operativa** (fuente estable USA.csv de football-data con cuotas
  de cierre, 6,000+ partidos): 47.2 % de modelo puro y **50.0 % con MESM**
  (mercado 50.1) — empata al mercado desde el día uno.
- **🔎 FotMob desbloqueado** ([fotmob_scraper.py](fotmob_scraper.py)): su API
  está blindada (header firmado x-mas), pero el JSON `__NEXT_DATA__` de cada
  página expone xG real, remates por JUGADOR con xG por tiro, defensivas
  (entradas/intercepciones/despejes), ratings y clima. Caché incremental
  commiteable + paso en el pipeline; las features llegarán cuando la
  cobertura permita validarlas (protocolo clima v23).
- **❌ Soccer24 inviable, documentado** (`soccer24_scraper.py` (retirado en v89)):
  el endpoint `/api/matches/{id}/statistics` del plan NO existe (404); sus
  feeds reales exigen firma `x-fsign` generada en cliente. FotMob cubre lo
  que se esperaba de él.
- **🧪 Estrategia E (IMT dentro del meta MESM): descartada en TODAS las
  ligas** — donde el momentum es señal, ya entró por el modelo base.

## Novedades v23 — Anulación táctica, meta-ensemble de mercado y móvil (ver [VALIDACION_v23.md](VALIDACION_v23.md))

- **⚡ Modelo de Anulación Táctica (MAT)** ([anulacion_tactica.py](anulacion_tactica.py)):
  predice el *apagón ofensivo* (equipo fuerte que acaba en 0 goles) con
  presión del rival, fatiga, contexto y clima; su **factor de supresión
  táctica** τ = log(P_MAT(0)/e^(−λ)) corrige la tasa de goles (λ' con w=0.5)
  y se propaga a los goleadores estrella. Validado walk-forward: Brier de
  P(0) **0.193 vs 0.212** del baseline Poisson (−8.7 %), NLL de goles
  1.61→1.50. El 1X2 queda intacto por construcción. Insight "⚡ Alerta de
  anulación táctica" cuando P(0) ≥ 45 %.
- **🧠 Meta-Ensemble de Superación de Mercado (MESM)**
  ([meta_ensemble.py](meta_ensemble.py)): stacking modelo+cuotas con pérdida
  asimétrica (castiga fallar donde el mercado acierta). Adoptado tras
  validación contra los modelos de producción en **4 ligas** — y con él la
  **Liga MX bate al mercado por primera vez (54.9 % vs 53.5 %)**; Serie A
  56.6 %, Primeira 56.1 %, Eredivisie 53.7 %. Descartado con evidencia en
  Premier/LaLiga/Bundesliga/Ligue 1. Solo actúa con cuotas vigentes del
  partido. Ablación incluida: el grueso es el stacking; la asimetría suma
  ~+0.5 pp.
- **🌤️ Clima** ([clima.py](clima.py)): Open-Meteo (gratis, sin clave) con
  caché y backfill incremental en el pipeline. Con la cobertura actual
  (14 %) el clima aún no aporta señal — dicho sin maquillaje.
- **📱 Móvil**: el selector de competición ahora está arriba del área
  principal (la barra lateral llega colapsada en el teléfono).

## Novedades v22 — FBref, Champions al día y asistente IA local (ver [VALIDACION_v22.md](VALIDACION_v22.md))

- **Champions con forma ACTUALIZADA**: FBref aporta los resultados que el
  plan Free de API-Football bloquea (2025-26 completa + fases previas
  2026-27). Fusión con mapeo de nombres aprendido + 25 alias verificados
  ([fbref_scraper_v3.py](fbref_scraper_v3.py), caché sembrada con navegador
  porque cloudscraper NO supera el 403 — documentado). Profundidad de
  historia validada en walk-forward de 3 variantes: desde 2020 (mejor
  log-loss, regla de oro superada). 1,174 partidos al día de hoy.
- **Honestidad radical sobre FBref**: sus calendarios YA NO publican xG —
  el reentrenamiento de Liga MX/Eredivisie/Primeira con "xG masivo" del
  plan v22 es imposible hoy y así se documenta. Sin cambios en esas ligas.
- **🎙️ Comentario del analista con IA local**
  ([asistente_comentarios.py](asistente_comentarios.py)): comentario natural
  inline en cada partido, compuesto desde las cifras reales del modelo.
  Con Ollama corriendo (checkbox en la barra lateral) un SLM gratuito
  (Phi-3/Llama 3.2) lo reescribe — marcado como tal. Nunca inventa cifras.
- **Panel ampliado**: barras Modelo vs ELO vs Mercado por liga + evolución
  de la precisión por ventanas walk-forward de 6 meses
  (`run_wf_panel_v22.py` (retirado en v89)), con las ventanas malas a la
  vista — la variación entre ventanas es la incertidumbre real.

## Novedades v21 — API-Football: Champions operativa, backfill de stats y H2H (ver [VALIDACION_v21.md](VALIDACION_v21.md))

- **Gateway API-Football** ([api_football_manager.py](api_football_manager.py)):
  contador diario (plan Free: 100 req/día), caché agresiva con TTL por tipo y
  prioridades con reserva de presupuesto. La clave se lee de
  `API_FOOTBALL_KEY` (env / `st.secrets` / `.streamlit/secrets.toml`
  gitignorado) y **jamás se commitea**. En Streamlit Cloud: Settings →
  Secrets → `API_FOOTBALL_KEY = "tu_clave"`.
- **🇪🇺 Champions League OPERATIVA** (beta desde v12): 707 partidos reales
  2022-2025 vía API-Football (3 requests, cacheados), nombres canonicalizados
  por ID. Split 56.8 % / 0.955 (ELO 54.5 %); walk-forward 2024-25: 53.5 %
  vs ELO 51.6 % — supera el umbral del 50 % y se activa. Limitación honesta
  del plan Free (solo temporadas 2022-2024): la forma de los equipos queda
  congelada a 2024-25 y la UI lo avisa.
- **Backfill progresivo de estadísticas** ([backfill_stats.py](backfill_stats.py)):
  el pipeline gasta el presupuesto sobrante en posesión/remates/córners/
  tarjetas de partidos 2022-2024 (Liga MX → Primeira → Champions) para el
  reentrenamiento de v22 (~25 días de acumulación).
- **📜 Historial reciente (H2H)**: en clubes vía API-Football (bajo demanda,
  caché 24 h); en el Mundial desde el histórico local de Kaggle (gratis).
- **No posible con el plan Free** (documentado con evidencia): alineaciones
  en vivo, cuotas BTTS y lesiones — requieren la temporada en curso o odds,
  ambas bloqueadas. ESPN sigue siendo la fuente de alineaciones.

## Novedades v20 — Simetría local/visitante, SmartParlayBuilder y panel de ROI (ver [VALIDACION_v20.md](VALIDACION_v20.md))

- **Simetría del Mundial corregida** ([prediction_api.py](prediction_api.py)):
  al invertir local y visitante las probabilidades diferían en promedio 18 pp
  (hasta 47 pp). Ahora la inferencia es simétrica: en sede neutral
  `P(gana A | A vs B) = P(gana A | B vs A)` exacto, y el anfitrión
  (MEX/USA/CAN en su país) conserva su ventaja real lo listes como local o
  visitante. Validado: mejora la precisión (60.38→60.49 %) y el log-loss
  (0.8712→0.8688) sobre los 2,640 partidos de validación.
  Test permanente: [test_simetria.py](test_simetria.py).
- **SmartParlayBuilder** ([match_parlay.py](match_parlay.py)): perfiles con
  garantías reales y distintos por construcción — 🛡️ conservador ≥60 %
  conjunto (reduce picks antes que relajar), ⚖️ medio en la zona 15-60 %,
  🚀 agresivo con la cuota más alta que respete ≥5 % conjunto y ≥30 % por
  pick (adiós a los parlays del 0.2 %: ahora cuota ~18× con 5 % real).
  Diversidad mínima de categorías `min(3, N-1)`, máximo un mercado de
  córners y uno de tarjetas, y explicación de la composición en la UI.
- **Panel de rendimiento por liga + simulador de bankroll**: ROI simulado
  con cuotas de cierre reales por liga (modelo vs mercado) y simulación
  cronológica de banca con ¼ Kelly (tope 5 %) y gráfico de evolución.
- **Alineaciones automatizadas (infraestructura)**: minutos estimados desde
  los flags de ESPN, `jugadores_xg.csv` con xG/90 bayesiano
  ([player_db.py](player_db.py)) y banner informativo del xG ajustado por
  once confirmado — sin tocar el 1X2 hasta que haya backtest (v21).
- Liga MX: modelos separados regular/liguilla evaluados y descartados con
  evidencia (−0.2 pp); el mercado sigue sin batirse y así se reporta.

## Novedades v19 — Banca, alineaciones sombra y Liga MX reforzada (ver [VALIDACION_v19.md](VALIDACION_v19.md))

- **Liga MX**: cuotas + features mexicanas (altitud, distancia de viaje,
  liguilla, apertura/clausura) + beta calibration — walk-forward
  50.7→51.7 % (+1.0 pp); modelo desplegado 52.4 % / 0.998. El mercado
  (53.5 %) sigue arriba y así se reporta.
- **Gestión de banca** ([bankroll_manager.py](bankroll_manager.py)):
  bankroll configurable en la barra lateral y stake por **¼ de Kelly** (tope
  5 %) en la tabla de EV y en el parlay con cuotas reales. Solo informativo,
  con aviso de juego responsable.
- **Hándicap asiático ±0.5** con cuota real y EV en la plantilla (línea y
  cuotas B365 de fixtures.csv — sin scraping). BTTS pospuesto: sin fuente
  gratuita legal.
- **Alineaciones confirmadas en modo sombra**
  ([lineup_collector.py](lineup_collector.py)): el JSON de ESPN publica el
  once titular de las 8 ligas + Mundial; se acumulan a diario en
  `alineaciones_historicas.csv` sin tocar las predicciones, para evaluar su
  impacto al cierre de la temporada 2026-27. Verificado con 4 partidos
  reales del Mundial.
- **Poisson puro para 1X2**: evaluado en Serie A, Bundesliga y Liga MX —
  inferior al ensemble calibrado en las tres; descartado con evidencia.

## Novedades v18 — Serie A recuperada, Liga MX con cuotas y EV en la UI (ver [VALIDACION_v18.md](VALIDACION_v18.md))

- **Serie A**: la ganancia de las cuotas de cierre (+4.4 pp que v17 rechazó
  por log-loss) se recuperó con **beta calibration**
  (`ModeloBetaCalibrado`): walk-forward 49.0→52.2 % con log-loss 1.047→0.998.
- **Liga MX**: `MEX.csv` siempre tuvo cuotas de CIERRE (`AvgC*`, 100 % de
  cobertura) — el parser leía las de apertura, inexistentes. Con el fix:
  cuotas como features (walk-forward +1.7 pp / −0.028) y primera línea base
  de mercado para MX (53.5 %). En vivo, las cuotas del día llegan de la
  página diaria de Betexplorer (`cuotas_clubes_hoy`, única fuente gratuita
  MX).
- **EV en la plantilla**: nueva sección "💰 Cuotas reales y valor" en el
  Mundial y las 8 ligas — cuota real (decimal y americana), EV % e indicador
  🟢/🟡/⚪/🔴 por mercado, con N/D honesto cuando no hay cuotas vigentes.
- Alineaciones confirmadas: pospuesta otra vez con evidencia (sin histórico
  gratuito backtesteable; xG/90 por jugador no computable con Kaggle).

## Novedades v17 — Ligas de clubes más precisas (ver [VALIDACION_v17.md](VALIDACION_v17.md))

- **Ciclo de experimentos por liga** (`run_league_experiments.py` (retirado en v89)):
  screening de 10 ideas × 8 ligas + walk-forward de confirmación. Adopciones
  (todas confirmadas fuera de muestra): **cuotas de cierre B365 como
  features** (LaLiga +1.5 pp, Eredivisie +0.4, Ligue 1 log-loss −0.057),
  **extras de contexto** — H2H, descanso, rachas, clasificación viva —
  (Premier +1.2 pp con cuotas, Bundesliga +0.5) e **histórico de 10
  temporadas** en Primeira (+0.4 pp). Serie A y Liga MX sin cambios (nada
  pasó la regla de oro; el caso Serie A +4.4 pp quedó fuera por log-loss).
- **Bundesliga ahora supera al favorito del mercado** (56.3 % vs 55.0 % del
  cierre B365) — segunda liga tras Premier donde el modelo bate al mercado.
- En inferencia, las cuotas usan el snapshot vigente de `odds_actuales.json`
  o la media del train (imputación v11); el estado de contexto viaja en
  `team_stats_{liga}.json → estado_extra`.
- **Fix crítico**: `ClubEngine.predecir` aún importaba giotto-tda (residuo
  de v14) — en el cloud habría fallado toda predicción de clubes. Migrado a
  ripser.

## Novedades v16 — Parlay dinámico + barrera del 60 % superada (ver [VALIDACION_v16.md](VALIDACION_v16.md))

- **Modelo del Mundial: 59.4 → 60.4 % / 0.871** (walk-forward 60.0 % / 0.870,
  +0.5 pp y −0.038 vs v13). La mejora ganadora del ciclo de 12 experimentos
  gratuitos (`run_experiments.py` (retirado en v89)) fue ampliar el
  histórico de Kaggle de 2010 a **1990** (32,386 partidos): cero features
  nuevas, cero cambios de inferencia. Stacking, H2H rico, importancia del
  torneo y blend Poisson pasaron el screening sobre la base 2010 pero NO
  aportan sobre la base 1990 — documentado con evidencia.
- **Parlay por partido DINÁMICO**: los perfiles ahora generan combinaciones
  distintas (conservador ≥70 % maximiza probabilidad y reduce picks antes que
  relajar; medio ≥55 % balancea `prob × cuota^0.3`; agresivo ≥30 % maximiza
  cuota/EV — paga 120-350× vs ~2× del conservador). Slider **2-8** picks y
  regla estricta de UNA línea por mercado (nunca "más de 6.5" y "más de 7.5"
  córners juntos).

## Novedades v15 — Parlay por partido en todas las competiciones

**🎯 Parlay de ESTE partido** ([match_parlay.py](match_parlay.py)): en la vista
de cualquier partido (Mundial y las 8 ligas de clubes) hay un asistente que
combina mercados DEL MISMO encuentro:

- **Número de apuestas**: slider de 4 a 8 (por defecto 6).
- **Perfil de riesgo**: 🛡️ Conservador (prob ≥65 % por selección) ·
  ⚖️ Medio (≥55 %) · 🚀 Agresivo (≥50 %). Si no hay suficientes mercados,
  relaja el umbral solo lo necesario y lo avisa.
- **Reglas de compatibilidad**: nunca combina opciones excluyentes (1X2,
  over/under de la misma línea, BTTS vs 0-0…), elimina apuestas equivalentes
  (hándicap ±0.5 = 1X2/doble oportunidad) y aplica **haircut de correlación
  0.95** por cada pareja de la misma familia (resultado/goles/córners/tarjetas).
- **Cuotas reales** de `odds_actuales.json` cuando existen (fixtures.csv /
  Betexplorer): el parlay maximiza EV; sin ellas usa cuotas justas y avisa
  "EV teórico — no accionable".
- **Riesgo de mercado**: si el partido está 🔴 en `risk_flags.json`, el
  asistente lo excluye por defecto (desactivable).
- Exportación en texto plano + bloque copiable. El parlay multi-partido del
  fixture del Mundial sigue disponible e intacto.
- Tests: [test_match_parlay.py](test_match_parlay.py) (unitarios, ambos
  motores) + AppTest de integración en Mundial y Serie A.

**Cualquier persona pregunta "¿quién gana?" para CUALQUIER par de las 48
selecciones y obtiene una respuesta clara — y además la Plantilla General de
Análisis Estadístico completa (9 secciones, ~85 campos: 1X2, doble oportunidad,
hándicaps asiáticos, over/under, BTTS, goleadores, córners y tarjetas),
editable y validable contra el modelo.**

## Novedades v14 — "Solo gratis, solo real" (ver [VALIDACION_v14.md](VALIDACION_v14.md))

- **M7 (en vivo gratis)**: ESPN (JSON público, sin clave) como fuente en vivo
  del Mundial — sustituye a Flashscore (JS frágil). Dedupe robusto por par de
  equipos ±1 día y mapeo de nombres ESPN→Kaggle. +19 partidos reales del
  Mundial el día de la corrida.
- **M8 (xG real)**: `understat_scraper.py` (retirado en v89) funcional
  (5 grandes ligas, 98 % de emparejamiento) pero **descartado como feature**:
  el A/B controlado empeoró el log-loss (LaLiga 1.014→1.108). Documentado.
- **M9 (ratings)**: [transfermarkt_scraper.py](transfermarkt_scraper.py)
  (1 petición/liga, caché 24 h) + flag `--ratings` en league_engine. Premier
  +1.8 pp en el A/B pero **no adoptado**: sesgo de anticipación (valores
  actuales aplicados a partidos pasados).
- **M10 (cuotas gratis)**: `fixtures.csv` de football-data (clubes, B365 sin
  clave) + [betexplorer_scraper.py](betexplorer_scraper.py) (Mundial, días de
  partido, robots.txt respetado) → `odds_actuales.json` → parlay.
- **M11 (UI apostador)**: modo **Principiante/Pro**, Asistente de Parlay en
  3 pasos con perfil de riesgo (conservador/medio/agresivo), tooltips de
  EV/cuotas y aviso de juego responsable.
- **M12 (5 ligas nuevas)**: Serie A, Bundesliga, Ligue 1, Eredivisie y
  Primeira Liga — todas superan su línea base ELO (ventana de temporadas
  elegida por backtest, regla ≥0.5 pp).
- **M13 (orquestador)**: [pipeline_total.py](pipeline_total.py) — un comando
  actualiza Mundial + 8 ligas + cuotas + Polymarket, con aislamiento de
  errores por paso.
- **Infra**: giotto-tda → **ripser** (segfault de giotto en Streamlit Cloud);
  Mundial reentrenado sin cambio material (59.4 % / 0.902).

## Novedades v13 — Evolución total (ver [VALIDACION_v13.md](VALIDACION_v13.md))

- **M1**: cadena en vivo del Mundial ([live_worldcup.py](live_worldcup.py)) con
  API-Football → FBref → base, dedupe por MATCH_ID y banner con la fase oficial
  del torneo. Cron cada 2 h en días de partido.
- **M2**: [distributions.py](distributions.py) — 38 líneas over/under por
  partido (incl. córners y tarjetas POR EQUIPO) con caché <1 ms tras la
  primera llamada.
- **M3**: parlay con `odds_actuales.json`, filtro `ev_min` con cuotas reales,
  **filtro de riesgo** (excluye partidos 🔴), riesgo general del parlay y
  exportación. Backtest con cuotas de cierre reales: **ROI +10.9 % en Premier**
  (209 apuestas) y **−20 % en LaLiga** — el EV positivo solo existe donde el
  modelo supera al mercado, y así se muestra.
- **M4**: riesgo compuesto (🔴 div>20 pp Y liq>30 % · 🟡 div>15 O liq>20) →
  `risk_flags.json` consumido por el parlay. Snapshots cada 10 min.
- **M5**: Liga MX ampliada a 8 años (**47.6 → 51.4 %, +3.8 pp**) y LaLiga a
  5 temporadas (**47.9 → 49.9 %, +2.0 pp**); Premier revertida a v12 (el
  candidato bajó −0.6 pp). Ratings de jugadores y FBref: bloqueados desde
  esta red — módulos listos, features descartadas por no validables.
- **M6**: no regresión verificada — walk-forward del Mundial **59.5 %/0.908
  idéntico a v12** y EGY vs AUS bit a bit intacto.

## Novedades v12 — Plataforma multi-liga con mercados completos

- **Mejora 1 (Mundial en vivo)**: flag `--live` que fuerza la re-descarga de la
  fuente ignorando cachés (cron cada 2 h en días de partido); indicador
  "🟢 Datos actualizados al {fecha}" en la UI cuando el estado incluye la fase
  actual del torneo.
- **Mejora 2 (distribuciones)**: probabilidades EXACTAS de superar cada línea
  en todos los mercados cuantitativos — goles (totales y por equipo), córners
  (6.5→10.5, totales y por equipo), tarjetas (2.5→5.5), remates (18.5→24.5) y
  remates a puerta (4.5→7.5). Nueva sección 9b en la plantilla y endpoint
  `GET /distribuciones?home=&away=`. 40 líneas verificadas monótonas.
- **Mejora 3 (parlay inteligente)** ([parlay_builder.py](parlay_builder.py)):
  mejor parlay de 8 selecciones del fixture con umbral de probabilidad ≥55 %,
  cuota ≥1.10, máx. 2 por partido, exclusión de mercados dependientes,
  haircut de correlación 0.95 por pareja del mismo partido y cuota total ≤1000.
  Con `ODDS_API_KEY` usa cuotas reales y ordena por EV; sin ellas usa cuotas
  JUSTAS del modelo (EV≈0) y se etiqueta como informativo.
- **Mejora 4 (inteligencia de mercado, EXPERIMENTAL)**
  (`market_intelligence.py` (retirado en v89)): snapshots de Polymarket
  (API pública Gamma) cada 15 min, con alertas de movimiento de probabilidad,
  cambios de liquidez >20 %, divergencia modelo-mercado >15 pts e indicador de
  riesgo de manipulación (🟢/🟡/🔴). Panel en la UI con aviso "no es
  asesoramiento financiero". Las señales NUNCA entran al 1X2 (evita fuga).
  *Alcance honesto:* el análisis de wallets on-chain requiere nodo/indexador
  propio; se aproxima el flujo con volumen/liquidez de la propia API.
- **Mejora 5 (ligas de clubes)** ([league_engine.py](league_engine.py)):
  **Liga MX, Premier League y LaLiga** con datos 100 % reales de
  football-data.co.uk (Premier/LaLiga incluyen remates, córners, tarjetas y
  cuotas de cierre reales) y modelos independientes por liga (misma
  arquitectura validada: ensemble calibrado + topología + regresores Poisson).
  Plantilla de clubes con 11 secciones/72 campos: 1X2 con cuota americana
  justa, doble oportunidad, over/under 0.5-5.5, BTTS, primer/último gol,
  par/impar, hándicap asiático completo, hándicap 1X2, marcador exacto (top 8),
  margen de victoria, mitades HT/2T, totales por equipo, multigoles, córners y
  tarjetas. Selector de competición en la barra lateral. **Champions en beta**
  (sin fuente CSV gratuita; requiere RAPIDAPI_KEY).

  **Backtesting por liga (temporal, datos reales):**

  | Liga | Partidos | Precisión | Línea base ELO | Favorito del mercado |
  |---|---|---|---|---|
  | Liga MX | 1,360 | **47.6 %** | 46.4 % | (sin cuotas en fuente) |
  | Premier League | 1,140 | **49.5 %** | 43.2 % | 45.9 % ✅ supera al mercado |
  | LaLiga | 1,140 | **47.9 %** | 46.1 % | 52.5 % (modelo por debajo — se reporta) |

- **No regresión verificada**: el 1X2 del Mundial es bit a bit idéntico
  (EGY vs AUS 0.388/0.253/0.359) y el benchmark walk-forward (59.5 %/0.908)
  sigue vigente — todo lo nuevo es aditivo.

## Novedades v11 — 49 selecciones, árbitros actualizables, cuotas y frescura

- **Cabo Verde (CPV)** integrado en todo el flujo: histórico real de Kaggle,
  ELO, MA5, goleadores reales (Livramento, Semedo), predicción y plantilla.
- **[referee_scraper.py](referee_scraper.py)**: actualización semanal de las
  estadísticas arbitrales desde WorldReferee (con `--scrape-arbitros`) y
  respaldo automático a la lista oficial pregrabada → `referees.json`, que
  `arbitros.py` carga al importar.
- **[fetch_odds.py](fetch_odds.py)**: cuotas 1X2 de apertura (The Odds API,
  variable `ODDS_API_KEY`) → `odds_historicas.csv`. Se usan SOLO en
  entrenamiento/backtesting como probabilidades implícitas + overround
  (4 features); en vivo se imputa la media de entrenamiento y la UI no
  muestra campos de cuotas. **Degradación limpia**: sin clave o sin cobertura
  (≥5 %), el modelo se entrena idéntico (registrado en `metadata.json`).
- **Cadena de respaldo de stats recientes**: FBref (`--fbref`, primaria) →
  API-Football (`RAPIDAPI_KEY`) → caché local. La UI muestra
  "⏰ Datos del {fecha}. Pueden no reflejar los partidos de ayer" si el
  estado tiene más de 24 h, y un botón **"🔄 Actualizar datos ahora"** que
  ejecuta el pipeline completo y recarga.
- **Fases detalladas** en la UI (grupos, dieciseisavos, octavos, cuartos,
  semifinal, final — las eliminatorias comparten el régimen de tensión).
- **Backtesting v11 (datos reales)**: split 2024+ → **59.5 % / log-loss 0.886**
  (mejor log-loss del proyecto); walk-forward 5 ventanas → **media 59.8 % /
  0.893**. El objetivo ≥61 % / ≤0.88 aún no se alcanza sin cuotas reales; con
  `odds_historicas.csv` poblado, el reentrenamiento las incorpora
  automáticamente (mejora esperada +1.0-1.5 pp según la especificación).

## Novedades v10 — Estadios oficiales, aclimatación y mejoras evaluadas

- **16 estadios oficiales** ([altitud.py](altitud.py)) con altitud real y
  selector en UI/API (`&estadio=Azteca`); sin sede se asume MetLife (2 m).
- **Capa de aclimatación** con las reglas exactas de la especificación:
  `ALT_HABITUAL` por selección (aclimatados: MEX 2240, ECU 2780, COL 2600);
  en sedes >1500 m el no habituado pierde 10 % (local) / 12 % (visitante) de
  xG (15 %/18 % sobre 2500 m); bono +5 % al local aclimatado por encima de la
  sede; el no aclimatado baja un escalón su rendimiento de 2ª mitad; córners
  +0.2 en altura. Verificado al decimal. **No toca el 1X2 calibrado** (la
  altitud ya entra al clasificador como feature entrenada ALTURA_NORM).
- **Walk-forward** (`--walkforward`): 5 ventanas de 6 meses (2024-2026),
  entrenamiento expansivo sin fuga: **precisión media 59.4 % · log-loss 0.894**
  (rango 57.4-62.5 %).
- **Optuna adoptado**: 12 trials TPE sobre XGB/LGBM → log-loss 0.8988→0.8974.
- **Mejoras evaluadas y RECHAZADAS con evidencia** (mismo split temporal):
  aumento sintético a 3000 (0.9001, peor que 904), distancia de Wasserstein
  H0 local-visitante (0.8992, sin ganancia), aclimatación como feature del
  clasificador (0.8994, solo 79 partidos de altura con desnivel), stacking
  con modelo binario de empate (log-loss 1.22, mucho peor). UMAP descartado
  técnicamente: las nubes tienen 6-10 puntos, insuficientes para UMAP (el
  camino PCA >50 dims ya existe). Los agregados de jugadores no entran al
  1X2 porque no existen datos individuales pre-partido reales del histórico.

## Novedades v6 — Lista arbitral ampliada y modelo de interacción

- **51 árbitros centrales oficiales** (lista actualizada FIFA + WorldReferee:
  10 CONMEBOL, 21 UEFA, 9 CONCACAF, 6 CAF, 5 AFC; nuevos: Piero Maza,
  Lamolina, Haro, Schärer, Eskås, Nyberg, Stieler, Peljto, Bastien, Hațegan,
  Soares Dias, J.M. Sánchez, Al-Hakim, Keylor Herrera, Buttimer).
- **Modelo de tarjetas v2 (interacción árbitro-equipo)**: el ancla es el p90
  REAL del árbitro, modulado por la desviación disciplinaria MA5 del equipo
  (+5 % por amarilla sobre 2.0), su estilo (+8 % bloque alto), la fase
  (+15 % eliminatoria / +5 % grupos) y el sesgo local (55 % ⇒ local ×0.90,
  visitante ×1.10). Se prefiere el ancla arbitral porque es la señal más real
  disponible para tarjetas.
- **Ajuste de reacción en eliminatorias**: la regla "+10 % de xG durante los
  15 minutos tras encajar" se integra a nivel de partido
  (Δλ ≈ λ×0.10×(15/90)×λ_rival) para equipos de reacción Fuerte, y castiga a
  los de reacción Débil; en grupos el efecto es la mitad. El 1X2 calibrado
  permanece intacto (verificado por prueba).
- **Selector de fase** (grupos / eliminación directa) en UI y API
  (`&fase=eliminatoria`).

## Novedades v5 — Arbitraje y carácter de los equipos

- **Módulo de árbitros** ([arbitros.py](arbitros.py)): árbitros centrales
  oficiales del Mundial 2026 (FIFA + WorldReferee 2022-2025, incl. Katia García,
  Frappart, Mukansanga) con amarillas/rojas/penaltis por 90', criterio y sesgo
  local. Penaltis repartidos por volumen ofensivo. El 1X2 calibrado NO se toca
  (el árbitro solo afecta tarjetas, penaltis, timeline e insights).
- **Carácter con minutos de gol REALES** (Kaggle goalscorers): por selección se
  calcula `REACCION_TRAS_GOL` (¿responde tras encajar?), `RENDIMIENTO_2DA_MITAD`
  (% de goles en la 2ª parte) y goles encajados en los últimos 15 minutos. Se
  usan en la línea de tiempo, los insights y las observaciones de la plantilla.
  *Nota de rigor:* se probaron como features del clasificador y NO mejoraron el
  backtesting (solo hay minutos desde 2018), así que se excluyeron del 1X2
  siguiendo la regla "solo features con poder predictivo demostrado".
- **UI**: selector de árbitro designado; la vista rápida muestra tarjetas/rojas/
  penalti esperados y la plantilla añade la línea del árbitro + 6 campos nuevos
  (tarjetas por equipo, rojas esperadas, probabilidades de penalti).
- **API**: `GET /predict?home=&away=&arbitro=`, ídem `/plantilla`, y `GET /arbitros`.

## Novedades v4

- **Ensemble calibrado**: XGBoost + Random Forest + LightGBM (voto suave) con
  `CalibratedClassifierCV(method='isotonic')`. La calibración se verifica en
  `backtesting.ipynb`: en picks de confianza > 70 %, el acierto real es ~80 %.
- **Topología por equipo**: entropías de persistencia H0/H1 de la nube de los
  **últimos 10 partidos de cada selección** + la nube combinada del par
  (6 features topológicas en total).
- **Regresores de goles esperados**: `HistGradientBoostingRegressor` con
  pérdida de Poisson para λ local y λ visitante — alimentan el Monte Carlo.
- **Aumento sintético**: ~1,000 partidos del generador correlacionado se suman
  SOLO al entrenamiento (nunca a la validación real).
- **Plantilla editable en la UI** (pestaña "📋 Plantilla de Análisis"):
  todos los campos pre-rellenados por el modelo, botón **"Validar mis
  estimaciones"** (diferencias, cuota justa 1/p y detección de valor) y
  exportación a Markdown (valores del modelo o los tuyos).
- **Endpoint** `GET /plantilla?home=MEX&away=ECU` (`&formato=markdown` opcional).
- **Notebook de backtesting** (`backtesting.ipynb`): precisión, log-loss,
  matriz de confusión, curvas de calibración y estabilidad por trimestre.

## Arquitectura híbrida de 3 fuentes abiertas (sin scraping frágil)

| Fuente | Aporte | Cómo |
|---|---|---|
| **Kaggle** – International Football Results | +15,800 resultados REALES desde 2010, actualizados al día (incluye goleadores con nombre) | `kagglehub`, sin credenciales |
| **API-Football** (RapidAPI, gratuita) | Estadísticas reales de los últimos partidos (remates, posesión, tarjetas) | Opcional: variable `RAPIDAPI_KEY` |
| **StatsBomb Open Data** | Calibra las relaciones goles↔xG↔remates del Mundial 2022 | Descarga única, caché en `calibracion_statsbomb.json` |

Las métricas avanzadas que las fuentes no traen se completan con el
**generador correlacionado calibrado** (coherentes con los goles reales y el
ELO — señal causal, no ruido).

```
Kaggle results ──► ELO cronológico ──► relleno calibrado (StatsBomb)
      │                                        │
      ▼                                        ▼
goleadores.csv                      historico_partidos.csv
      │                                        │
      ▼                                        ▼
jugadores_clave.csv ◄── update_team_stats ──► team_stats.json
                                               │
                            train_tda_model (backtesting temporal)
                                               │
                    prediction_api ──► dashboard_ui / GET /predict
```

## Archivos

```
├── data_fetcher.py                    # Kaggle + API-Football + unificación
├── statsbomb_calibration.py           # Calibración xG↔goles↔remates (con priors fallback)
├── correlated_synthetic_generator.py  # Relleno causal + generador de respaldo
├── update_team_stats.py               # ELO + MA5 -> team_stats.json · goleadores reales
├── feature_engineering.py             # Features pre-partido sin fuga + nubes TDA
├── train_tda_model.py                 # Vietoris-Rips + entropías + RF calibrado
├── prediction_api.py                  # Motor {home,away} -> JSON · FastAPI opcional
├── dashboard_ui.py                    # ⭐ "¿Quién gana?" (Streamlit)
├── fbref_scraper_v2.py                # (opcional, ya no es la fuente primaria)
├── pipeline_mundial.py                # Orquestador diario
└── PLAN_DE_PRUEBAS.md
```

## Puesta en marcha

```bash
# Entorno: Python 3.10–3.12 (giotto-tda no soporta 3.13)
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt

# 1. Datos reales + estado por selección (diario)
.venv\Scripts\python pipeline_mundial.py

# 2. Entrenamiento con backtesting temporal
.venv\Scripts\python train_tda_model.py --corte 2024-01-01

# 3. Dashboard (http://localhost:8501)
.venv\Scripts\python -m streamlit run dashboard_ui.py

# 4. (opcional) API HTTP (http://localhost:8000)
.venv\Scripts\python prediction_api.py
#    GET /predict?home=ARG&away=FRA · GET /query?q=... · GET /health
```

## Resultados de backtesting (datos REALES, ensemble v4)

| Métrica | Valor |
|---|---|
| Entrenamiento | 12,608 partidos reales (2010 → 2023) + 904 sintéticos correlacionados |
| Validación temporal | 2,616 partidos reales (2024 → 2026) |
| **Precisión** | **59.4 %** ✅ (regla de oro: ≥ 55 %) |
| Línea base "siempre el favorito por ELO" | 58.9 % |
| Log-loss | 0.892 |
| Precisión en picks con confianza > 70 % | **80.4 %** (682 partidos) |
| Objetivo estricto (≥ 62 % / ≤ 0.85) | ❌ no alcanzado — se reporta con transparencia |

> El techo empírico del 1X2 internacional (incluyendo empates) ronda el
> 60-65 % incluso para modelos comerciales. La calibración isotónica hace que
> las probabilidades sean confiables para detectar valor, que es lo que
> realmente importa en la plantilla.

## Reglas de oro

- **Precisión > todo**: si el backtesting temporal baja de 55 %, `deploy_ready`
  se apaga y la UI muestra "Modelo en modo referencia".
- **Transparencia**: `fuente_datos.json` registra la procedencia. Con fuentes
  reales la UI muestra "✅ Resultados reales actualizados al AAAA-MM-DD"; si
  todo falla y se usa el generador de respaldo: "⚠️ Datos estimados –
  precisión limitada".
- **Simplicidad radical**: insights en lenguaje llano; los goleadores del
  tablero "¿Quién remata?" son reales (Kaggle goalscorers, últimos 24 meses).

## Ejecución diaria automática (Windows)

```powershell
schtasks /create /tn "PipelineMundial2026" `
  /tr "C:\ruta\proyecto\.venv\Scripts\python.exe C:\ruta\proyecto\pipeline_mundial.py --train" `
  /sc daily /st 06:00
```
