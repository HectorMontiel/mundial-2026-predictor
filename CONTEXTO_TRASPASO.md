# CONTEXTO DE TRASPASO — mundial-2026-predictor

## 0. Identidad y entorno

- Repo REAL: `HectorMontiel/mundial-2026-predictor` (`HMREY/...` es fork viejo, NO usar)
- Local: `D:\Claude\predictor-upstream` · venv: `D:\Claude\mundial-2026-predictor\.venv` (Py 3.12)
- Git y red necesitan `dangerouslyDisableSandbox`. Usuario HMREY, responder en español.
- Deploy: Streamlit Cloud desde `main`. Último commit: v148.
- App: Streamlit de apuestas deportivas. 50 ligas fútbol + MLB + NBA + tenis + KBO + NFL.

## 1. REGLAS NO NEGOCIABLES

```
python test_catalogo_y_cuotas.py    # ~812 checks, ~3 min. SIEMPRE.
python smoke_botones.py             # 8 vistas, ~110 min. Si cambió CÓDIGO.
python smoke_botones.py --rapido    # ~15 min. Sólo si cambiaron DATOS (rebase del bot).
```
- HMREY aprueba commit+push automático a main SI TODO valida.
- **REGLA DE ORO**: nada se despliega sin p5 de bootstrap positivo en tramo de juicio.
- **VALIDA EL RENDER**: py_compile/AST no detectan UnboundLocalError. Sólo AppTest.
- Un test que no encuentra su fichero devuelve exit 0. Comprobar que CORRIÓ.
- NO solapar validaciones pesadas (se asfixian). Red/YAML sí se pueden solapar.
- NO escribir `vNNN` en cadenas visibles de dashboard_ui (`test_mensajes_sin_jerga_interna`).
- Documento que manda: `BITACORA_ARQUITECTURA.md`. Antes de añadir algo, comprobar si lo contradice.

## 2. HALLAZGOS MEDIDOS (no repetir el trabajo)

- El modelo NO bate al mercado. Apostar su probabilidad pierde −4,66 % a −6,52 % (n=37.158).
  Su EV es ANTI-indicador (corr −0,054 con CLV).
- El modelo YA está calibrado (dice 57,5 %, acierta 57,5 %). NO multiplicar por backtest.
- Comprar al mejor precio SÍ gana: +11,49 % en juicio, p5 +1,73 %.
- Canales con p5 positivo (los únicos): precio al lado LOCAL en fútbol; tenis prob ≥90 %.
- `EV_parlay = Π(1+EV_i)−1`. Combinar patas negativas multiplica la pérdida.
- Playdoit paga −4,57 % vs el mejor precio del mercado.
- MLB ponches: Poisson bien calibrada. `MARGEN_CALIBRACION_K=0,02`.
- The Odds API: 500 créditos/mes, corte a 450, lista blanca 15 ligas, reparto diario.
- **PENDIENTE DE HMREY: rotar la clave de The Odds API (la pegó en un chat).**

## 3. ARQUITECTURA (módulos clave)

| Módulo | Qué hace |
|---|---|
| `alpha_finder.py` | Barrido del día. Ramas en paralelo: futbol/mlb/tenis/nba/kbo/nfl. `_solo_hoy` = puerta de picks (CDMX). `_en_ventana` = 3 días UTC. |
| `clasificador.py` | 3 secciones. Semáforo por VENTAJA DE PRECIO vs consenso, NO por EV del modelo. `UMBRAL_VENTAJA=0.05`, `VENTAJA_IMPOSIBLE=0.30`. |
| `cuotas_multi.py` | 6 fuentes + consenso. `mercados_playdoit()` baja a childMarkets. `normalizar()` expande abreviaturas por apodo (MLB+NFL comparten ciudades). |
| `cuotas_tablon.py` | Traduce tablero de casa → vocabulario del modelo. Veto por SEÑA (evita EV inventado). |
| `league_engine.py` | `descargar_liga(clave, temporadas=N)`, `entrenar_liga`, `ClubEngine`. |
| `dashboard_ui.py` | ~8000 líneas. Menú país→liga, pestañas del día, fichas. |
| `partido_ui.py` | **v147**: 5 secciones de ficha con diferido real. |
| `corners_ui.py` | **v146**: sección de córners. |
| `nfl_datos.py` / `modelo_nfl.py` / `nfl_mercados.py` / `nfl_lineshop.py` | **v131**: NFL. |
| `horario.py` | UTC → CDMX. Sólo presentación. |

## 4. LO HECHO EN ESTA SESIÓN

### v131 — NFL completa
- Fuente: **ESPN** (1.055 partidos 2023-2026, 25 stats/equipo, **cuotas de cierre históricas**).
- Modelo: ridge sobre estado rodante → margen + total → residuos empíricos.
  Hiperparámetros elegidos en 2024, juzgados en 2025 (v=12, arr=0,50, alpha=15).
- **Veredicto: NO bate al mercado** (63,0 % vs 66,5 %; Brier 0,2231 vs 0,2119).
  EV>5 % hunde el acierto a 45,5 %. Ningún canal con p5 positivo → Capa 2.
- Hándicap luce +5,96 % en 2025 pero −4,88 % en 2024 → ruido, NO se despliega.
- **Pretemporada: el modelo NO publica probabilidad** (corr −0,013, Brier 0,2727 = peor que 50 %).
- Canal de precio NFL: **NO MEDIBLE** (ESPN sólo guarda multi-casa en 2023).
- Bugs corregidos: «Wroclaw Panthers»→Carolina; «KC Chiefs»→«kansas city royals».
- ESPN bloquea el UA de Chrome largo y acepta `Mozilla/5.0` (al revés de lo intuitivo).

### v144 — Día en CDMX + selector por país
- 3 bugs: reparto UTC vs pantalla CDMX; ventana estrecha; `_solo_hoy` en UTC.
- Menú: 17 → **57 competiciones en 37 países**. Rusia/Escocia/League One ya existían, estaban invisibles.
- Orden de listas: local desc, luego visitante desc.
- Saudi Pro League dada de alta (`disponible: False`, se activa sola si bate ELO — **no ha pasado**).
- Sin fuente gratuita: Croacia, J2, España Primera Fed. Con fuente: 3.Liga alemana (OpenLigaDB).
- Austria 2.Liga DESCARTADA por hueco (480 de ~720, falta 2023-24).
- **Trampa**: `football-data /new/JPN2.csv` **es J1, no J2**. El `2` es numeración de fichero.

### v145 — Visibilidad de partidos
- Copia duplicada del filtro de ventana tiraba 5 partidos (Necaxa-León, Pachuca-Puebla…).
- `es_hoy` pasa a día CDMX. Partidos sin modelo se muestran con motivo.
- Resultado: fútbol 63→63 hoy, 19→19 mañana. KPI cuadra con pestañas.
- Selector de orden (hora / probabilidad) en ambas pestañas.

### v146 — Córners
- **Las 50 ligas YA tenían córners al 100 %.** No hacía falta fuente nueva.
- 5 familias de mercado de Playdoit mapeadas (19 filas/partido, 16 cruzadas).
- Líneas ENTERAS con empuje añadidas: `P(>L)/(1−P(=L))`. La casa cotiza enteras, el modelo tenía .5.
- **ERROR MÍO CORREGIDO**: medí la fórmula con xG *observado*; producción usa xG *predicho*.
  La «corrección» alejaba el modelo del mercado (+2,38 vs +1,07). Base revertida a 4,0.
- Córners salen con **precio y sin EV** (`ev_no_fiable`).

### v147 — Rendimiento, navegación, histórico
- **Ficha: 13,4 s → 0,9 s**, de 41 peticiones a 0. El coste era RED, no cálculo.
- `st.tabs` NO sirve: Streamlit renderiza todas las pestañas. `partido_ui` usa radio horizontal
  (no `segmented_control`: **AppTest no lo expone**, el smoke no podría pulsarlo).
- Smoke recorre las 5 secciones Y pulsa botones dentro (si no, dejaba de probar «Proponer parlays»).
- **Desacople H2H/modelo**: CSV con 9-16 temporadas, modelo con ventana medida (`temporadas_modelo`).
  - H2H Premier: 5,0 → 17,6 cruces/pareja; parejas con ≥10: 0 % → 76 %.
  - **La ventana corta NO era descuido: está medida.** Premier con 5 temporadas bajó 49,5 %→48,9 %.
  - **CLAVE**: recortar DESPUÉS de derivar NO basta. `elo_diff` acumula desde la 1ª fila y
    `home_xg` lo genera un RNG dependiente del tamaño. `descargar_liga(temporadas=N)` recorta ANTES.
  - Memo de descarga cruda en proceso (18 peticiones → 2 en la 2ª llamada).
- **Arrow bug** (`Could not convert '—'`): era mío de v146. Columna mezclaba float y str. `None` + `column_config`.
- **403 ESPN**: NO es cambio de API. 0/14 ligas fallan desde máquina normal. Bloqueo por IP de
  centro de datos. Runner de GitHub NO bloqueado (prueba: el bot añade partidos a históricos
  formato `espn`). `precalcular_goleadores.py` + `.github/workflows/precalcular_rosters.yml` (04:30 UTC).

## 4b. LO HECHO EN LA SESIÓN v148 (2026-08-21)

Ver `VALIDACION_v148.md` para las mediciones completas.

**Bug de pronósticos — 35 de 326 partidos (10,7 %) → 7 (2,1 %).**
- Causa raíz: las listas de temporadas de las 20 ligas de football-data eran
  tuplas literales terminadas en `'2526'`. La temporada 2026-27 llevaba una
  semana jugándose y no estaba en la configuración → sin ascendidos en el
  catálogo → sin mapeo → sin pronóstico.
- `temporadas_fd.py` (nuevo): la lista se DERIVA de la fecha. Se corrigió
  también `generar_ligas_v68.py`, que era quien las congelaba.
- `_csv_temporada`: una temporada no publicada devuelve **300 Multiple Choices
  con HTML**, no 404. Hay que validar el CONTENIDO. Distingue «no publicada»
  (se salta) de fallo de red (levanta).
- `_completar_desde_espn` puede dar de alta ascendidos:
  `name_mapper.mejor_candidato` separa «alias que falta» (ratio ≥ 0,62) de
  «equipo nuevo» (< 0,62). Ante la duda NO se da de alta.
- +34 alias. Un alias puede tener VARIOS destinos: football-data escribe el
  Deportivo `Dep. A Coruna` en SP1 y `La Coruna` en SP2.
- **BUG GORDO encontrado de paso**: `Independiente Rivadavia` mapeaba a
  `Independiente` (Avellaneda) por la regla de contención. Sólo se salvaba
  porque el guardia `home == away` tiraba el partido; contra un tercero habría
  publicado la probabilidad del club EQUIVOCADO. Arreglado con `'ind'` en las
  abreviaturas y haciendo que la expansión se pruebe SIEMPRE (antes sólo si
  cambiaba el nombre de entrada, no el del catálogo).
- Los 7 que quedan son límite externo: football-data no ha publicado E0, F1,
  I2 ni G1 de 2627, y esos equipos no han jugado aún. Se resuelven solos.

**Dos incoherencias de la v147 corregidas antes de desplegarse** (el bot no
había corrido desde la v147, así que nunca llegaron a producción):
- `preparar_features_extra` recibía `df` (16 temporadas) en vez de `df_modelo`
  (la ventana medida). Todas esas features son acumulativas.
- `equipos_liga` salía de `df` con `estado` de `df_modelo` → **16 clubes
  fantasma de 41 en la Premier**, con ELO 1500 y PERF10 vacío, y mapeables.

**Barrido (Parte 1).**
- `guardia_barrido` gana caché en disco + revalidación en segundo plano.
  `FRESCURA_S=300`, `CADUCIDAD_S=3600`. Escritura atómica.
- Medido: frío 160,1 s · memoria 0,000 s · **arranque de contenedor 0,004 s**.
  Caché de 0,33 MB.
- El resultado viaja con `_frescura` y la UI avisa de la edad ENCIMA de las
  pestañas: el pronóstico aguanta media hora, el precio NO.
- Quitados dos derroches: `odds_actuales.json` se parseaba en cada predicción
  (~650 veces por barrido) y la cola de ESPN se pedía DOS veces por liga desde
  la v147.

**Extra: el bot perdía el día entero si alguien empujaba a mitad.**
- Comprobado en la ejecución del 2026-08-21 05:58: todos los pasos en verde y
  el push rechazado (`! [rejected] main -> main (fetch first)`) porque la v147
  entró a las 06:26, dentro de la ventana de ~55 min del job. 52 minutos de
  reentrenamiento a la basura, y por eso producción sigue con los modelos del
  2026-08-20.
- Ahora reintenta con rebase (3 intentos). En conflicto de ARTEFACTOS toma la
  versión del bot (acaba de regenerarla con datos de hoy); en conflicto de
  CÓDIGO (`.py` o `.github/`) aborta con aviso en vez de pisar a nadie.

**Repo de 15 GB (Parte 3).**
- Medido: 15 GB / 23 commits del bot ≈ **650 MB por commit**.
- Descartado con números: comprimir mejor (xz ahorra 27 % y multiplica por 14
  el dump) y entrenar al arrancar (**33 min medidos** para 49 ligas).
- Hecho: los pesos pasan a ser **assets de un Release** (`modelos-latest`),
  **uno por competición** (mediana 12 MB). `modelos_remotos.py` los baja bajo
  demanda; `publicar_modelos.py` los sube. Enganchado en `ClubEngine` y en
  `engines/base_engine`.
- Verificado de extremo a extremo con una etiqueta de prueba que se borró:
  subir → bajar (1,70 s) → cargar, incluida la reparación de plataforma.
- **La transición la hace el workflow**, y sólo si la publicación se verificó
  (`continue-on-error` + `if: steps.publicar.outcome == 'success'`). Este
  commit NO borra nada.
- Esto DETIENE el crecimiento; no encoge los 15 GB que ya están.

## 4c. ESTADO REAL TRAS EL DESPLIEGUE (2026-08-21)

- `main` = `5592f41` (commit del bot) sobre `ecc7514` (v148).
- **`modelos/` YA NO ESTÁ VERSIONADO.** La transición la hizo el bot en la
  ejecución `32472153115` (59m51s, todo en verde). Release `modelos-latest`
  con **57 assets**.
- Clon nuevo: **9,3 s · 194 MB** (antes 12,89 GiB y >10 min).
- Verificado en ese clon SIN `modelos/`: laliga/premier/liga_mx/NBA cargan
  bajando del Release, con reparación de plataforma, y predicen.
- Commit diario del bot medido en objetos reales: **5,6 MB / 128 objetos**
  (antes ~650 MB). 116× menos.
- LaLiga pasa de 26 a 31 equipos: los ascendidos están dentro.

**OJO para la próxima sesión:** el clon local de trabajo TAMPOCO tiene ya
`modelos/`. Se rellena solo la primera vez que se carga cada liga (unos
segundos por competición). No hay que restaurarlo ni commitearlo.

## 4d. v148.1 — CAÍDA Y ARREGLO (mismo día)

`FileNotFoundError: './modelos/modelo_tda.joblib'` en producción.

El patrón de exclusión decía `modelos/` cuando lo que sobraba eran
`modelos/*/`. En la RAÍZ de `modelos/` hay **11 artefactos que no son de
ninguna liga y que el bot NO regenera**: el modelo del Mundial
(`modelo_tda.joblib`, `escalador.joblib`, `reg_goles_*.joblib`,
`metadata.json`, `validacion.npz`, `curvas_calibracion.png`), el MAT
(`mat_*`), la NFL (`nfl_v131.json`) y `supervivencia_btts.json`.
`git rm -r --cached modelos/` se los llevó.

Son 64 MB estáticos, no los 712 MB diarios: **se quedan versionados**.

- `.gitignore` y el paso del workflow pasan a `modelos/*/`.
- **No vale** `modelos/` + `!modelos/*.joblib`: git no re-incluye un fichero si
  su directorio padre está excluido. Hay que excluir sólo los subdirectorios.
- Verificado con `modelos/` sin subcarpetas (estado de producción):
  `PredictionEngine OK en 2,9 s` y predice.

**REGLA:** antes de escribir un `git rm -r --cached <dir>`, enumerar lo que hay
dentro. `modelos/` mezclaba dos ciclos de vida —pesos diarios por competición y
artefactos globales quietos desde hace meses— y el patrón no los distinguía.

## 4e. v149 — LA BARRA DE MERCADO Y EL AGUJERO DE RENDIMIENTO

Ver `VALIDACION_v149.md`.

**Partidos sin modelo → ahora con precio.** Un ascendido que no ha jugado deja
al modelo sin nada que decir, pero el partido SÍ tiene precio, y el §0 de la
bitácora tiene medido que el precio sabe más que el modelo. Se pinta la
probabilidad implícita del mercado (margen quitado), atenuada, con sello
«mercado» y nota bajo la liga. Ordena junto a los demás (`prob_lados` mira
`board_mercado`). Donde hay modelo, manda el modelo.
Medido: sin_modelo = 7 · con barra de mercado = 7.

**Rendimiento: 169,9 → 129,6 s en la rama de fútbol (−24 %).** De memorizar
cinco funciones puras del emparejador y paralelizar `_completar_cuotas` a 4
hebras. Pico de memoria 654 MB (v86 midió 1.297).

**TRES DIAGNÓSTICOS EQUIVOCADOS, y la razón es la misma:**
sumar tiempo de hebras CONCURRENTES no es tiempo de reloj. `_completar_cuotas`
se llama desde `fixtures_multi`, que ya abre una hebra por liga, así que 240 s
«acumulados» cabían en 30 de reloj. **Para buscar un cuello de botella hay que
cronometrar FASES, no acumular por función.**

**EL RELOJ DICE:** `_barrido_fixtures` es el 100 % de la rama (128,8 s), y
dentro, en serie: 50 s de cargar 35 modelos + 51 s de 286 predicciones.

**NO INTENTAR OTRA VEZ:** adelantar la carga del modelo siguiente en otra hebra.
Medido: 128,8 → **160,1 s** (peor). El *unpickle* de un `.joblib` retiene el
GIL; la hebra que carga bloquea a la que predice. Está escrito en el propio
`alpha_finder`. ~46 MB por motor residente, por si hace falta el dato.

**LO QUE SÍ QUEDA POR PROBAR** para bajar de 129 s (reducir el trabajo, no
repartirlo): guardar los `.joblib` sin comprimir dentro del asset del Release
(que ya va gzipado, así que no cuesta tamaño) y cargar
`reg_local`/`reg_visit`/`mesm` sólo cuando se usen. Es su propia versión.

## 4f. v150 — EL FALLBACK DE MERCADO SE DELATA

**AVISO PARA QUIEN LEA ESTO:** si alguien reporta que «las ligas principales
dejaron de dar pronósticos», MEDIRLO ANTES de reentrenar. Se comprobó el
2026-08-21 y era falso:

```
321 fixtures · 314 con pronóstico del modelo (97,8 %) · SIN MOTOR: ninguna
   LaLiga 9/9 · Serie A 10/10 · Ligue 2 9/9 · Primeira 7/7 · Premier 8/10
```

Los 7 sin modelo son **partidos sueltos**, no ligas: 6 ascendidos que no han
jugado ni un partido en su competición (Coventry y Hull, Iraklis y Kalamata,
Arezzo y Hellas Verona, Le Mans). No hay dato que entrenar; un reentrenamiento
forzado no cambia nada. Se resuelven solos cuando football-data publique E0,
F1, I2 y G1 de 2026-27.

**LO QUE SÍ ERA UN RIESGO REAL, y de ahí esta versión:** desde la v149 el
partido sin modelo sale con el precio del mercado en vez de con un hueco. **Un
hueco se ve; un relleno no.** Si una liga entera dejara de cargar su modelo, la
pantalla se vería perfectamente normal —barras llenas, números plausibles— con
el corazón de la app apagado. Es el modo de fallo de la v106 (doce
competiciones en silencio) con mejor disfraz.

`alpha_finder.avisos_sin_modelo()` avisa cuando el mercado tapa **un tercio o
más** de una competición (mínimo 3 partidos de muestra). No avisa por debajo, y
eso es deliberado: dos ascendidos de diez es lo normal en agosto, y una alarma
que salta todos los días deja de leerse. Cada relleno deja además su línea de
log con liga, partido y motivo.

Cubierto por `test_el_fallback_de_mercado_se_delata` (5 casos, incluidos los
dos en que debe CALLAR).

## 4g. v151 — MODELO SIN COMPRIMIR, Y EL TECHO DE VELOCIDAD

Ver `VALIDACION_v151.md`.

**`modelo.joblib` se guarda con `compress=0`.** Es el 96 % del coste de
construir un `ClubEngine` (7,52 s de 7,80 sobre tres ligas). Desde la v148
viaja dentro de un `.tar.gz`, así que comprimirlo también por dentro era
trabajo puro: el tar sale incluso algo MÁS pequeño sin la doble compresión
(11,2 vs 11,9 MB) y se pagaba `zlib` en cada arranque. Medido sobre el mismo
objeto: **1,29× más rápido**. Disco 712 MB → 1.239 MB (1,7×).

**OJO CON EL NÚMERO:** en local la fase de carga bajó 50,0 → 25,7 s, pero eso
está inflado por Windows —`modelos_portables.cargar` repara el booster de Linux
y al reserializar en local ese trabajo desaparece—. En producción (Linux) la
ganancia esperada es la de objetos idénticos: **~11 s de 130**.

**CARGA PEREZOSA DE REGRESORES: DESCARTADA.** `reg_local` y `reg_visit` son un
2 % cada uno. Ahorraría 2 s de 50 a cambio de un camino condicional que puede
fallar.

**«< 15 s» NO ES ALCANZABLE, y conviene no volver a prometerlo:**

```
fixtures + cuotas   29,8 s   (red, precios frescos de 320 partidos)
cargar modelos      50,0 s
predicciones        51,0 s
                   -------
                   130,8 s

sin comprimir          119,6 s
carga = 0 (techo)       80,8 s
carga y predicción = 0  ~30 s   <- el SUELO con precios reales
objetivo pedido        < 15 s
```

**LO QUE SÍ LLEVARÍA A ~30 s:** precalcular las predicciones en el bot. El 1X2
es función de `team_stats` y del modelo, y los dos sólo cambian cuando corre el
bot. Mismo principio que la v148, movido a donde es gratis.
**ANTES HAY QUE COMPROBAR UNA COSA:** `ClubEngine.predecir` consulta
`odds_actuales.json` para el MESM y el blend de mercado. Hoy ese fichero NO
existe ni está versionado (verificado), así que ninguna rama se activa — pero
si en producción existiera, precalcular congelaría una predicción que se
suponía viva. Comprobarlo primero.

## 5. PENDIENTE

1. **El workflow tardó 59m51s con tope de 60.** Va al filo. Ahora sube ~57 assets
   (~880 MB) y a cambio se ahorró ~57 peticiones a ESPN. Si empieza a caerse por
   timeout, la optimización obvia es no re-subir el asset de una competición cuyos
   ficheros no han cambiado (hash del contenido, no del tar: gzip mete el mtime).
   La otra palanca: subir `timeout-minutes` a 90.
2. **Los 15 GB de `.git` YA ESCRITOS siguen ahí.** La v148 detiene el crecimiento
   —medido: 5,6 MB en el primer commit del bot bajo el régimen nuevo, frente a
   ~650 MB— pero no encoge lo pasado. Reescribir historia es destructivo, rompe
   todos los clones y **ni siquiera libera espacio en GitHub sin abrir ticket con
   su soporte**. Riesgo alto, beneficio incierto. Decisión pendiente de HMREY.
   Para un clon ligero HOY: `git clone --depth 1 --single-branch` (9,3 s, 194 MB).
3. **Los 7 partidos sin pronóstico se resuelven solos** cuando football-data publique
   E0, F1, I2 y G1 de 2627. No hay que tocar nada: la lista de temporadas ya los pide.
   Vale la pena volver a correr `_v148_medir_pronosticos.py` dentro de unos días.
4. **Primera ejecución del workflow de rosters** (04:30 UTC).
5. **Córners**: validar el nivel del modelo con lambdas de producción → entonces
   semáforo y recomendaciones.
6. **Ingestor OpenLigaDB** para 3.Liga alemana (endpoint verificado, ~1.900 partidos).
7. Mapeo de nombres: quedan ~100 en `nombres_sin_mapear.json`. La v148 cerró los
   que costaban partidos hoy; medir cuántos de los demás casan MAL (que es el daño
   caro, como enseñó Independiente Rivadavia) en vez de simplemente descartarse.
8. Bovada falla en MLB a veces. Medir frecuencia.

## 6. NO HACER

- Prometer que se bate al mercado o ROI garantizado.
- Filtrar Sección 1 por EV del modelo.
- Combinar patas de Sección 2 esperando EV positivo.
- Usar histórico de The Odds API (de pago).
- Reentrenar ligas sin p5 positivo.
- Añadir dependencias pesadas de UI (st-aggrid, Plotly) — `st.dataframe` nativo basta.
- Commitear modelos entrenados en Windows (hay diferencia de plataforma medida; el bot entrena en Linux).

## 7. LECCIONES CARAS DE ESTA SESIÓN

- **Medir antes de aplicar.** Dos veces di un diagnóstico equivocado (los «9 recálculos» de la
  ficha; el sesgo de córners) y sólo la medición lo corrigió.
- **Simular antes de escribir.** El script de ampliación iba a pisar la ventana medida de la Premier.
- **Una inconsistencia puede ser una decisión.** Premier con 3 URLs y LaLiga con 5 parecía descuido;
  era un experimento registrado.
- **Un nombre de fichero no es su contenido.** `JPN2.csv` contiene J1.
- **Testabilidad > estética.** `segmented_control` se ve mejor pero AppTest no lo ve.
- **Restaurar artefactos locales** antes de commitear: hay diferencia de plataforma.
- **Una lista de periodos escrita a mano es una bomba con fecha conocida.** Si algo
  depende del calendario, se deriva del calendario. El bug de la v148 llevaba una
  semana activo y nadie lo vio venir porque «funcionaba» desde 2010.
- **Un 300 no es un 404.** `raise_for_status()` no levanta ante un 300 y `read_csv`
  se traga una página HTML sin quejarse. Validar el contenido, no sólo el código.
- **Un equipo nuevo no es un nombre mal escrito**, y confundirlos tiene coste en las
  dos direcciones: descartar al ascendido, o partir el historial de un club en dos.
- **Verificar no puede poner en riesgo lo que se verifica.** La primera versión de
  `verificacion_ida_y_vuelta` movía la carpeta real de modelos y la devolvía en un
  `finally`; un timeout del workflow la habría dejado fuera de sitio y el `git add -A`
  la habría borrado del repositorio.
