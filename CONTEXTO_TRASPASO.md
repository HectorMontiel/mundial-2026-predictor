# CONTEXTO DE TRASPASO — mundial-2026-predictor

## 0. Identidad y entorno

- Repo REAL: `HectorMontiel/mundial-2026-predictor` (`HMREY/...` es fork viejo, NO usar)
- Local: `D:\Claude\predictor-upstream` · venv: `D:\Claude\mundial-2026-predictor\.venv` (Py 3.12)
- Git y red necesitan `dangerouslyDisableSandbox`. Usuario HMREY, responder en español.
- Deploy: Streamlit Cloud desde `main`. Último commit: v148.
- App: Streamlit de apuestas deportivas. 50 ligas fútbol + MLB + NBA + tenis + KBO + NFL.

## 1. REGLAS NO NEGOCIABLES

```
python test_catalogo_y_cuotas.py    # ~869 checks, ~4 min. SIEMPRE, sin excepción.
python smoke_botones.py --rapido    # 8 vistas sin botones caros. Si cambió la INTERFAZ.
python smoke_botones.py             # completo. SEMANAL, o si cambió el MOTOR.
```

**v152 — LA POLÍTICA DE VALIDACIÓN, DECIDIDA POR HMREY.**

El smoke completo deja de ser puerta de cada push. El motivo es medido: en esta
máquina no terminó en 55 minutos en dos intentos seguidos (EXIT 124 las dos
veces) y la vista de «Apuestas del Día» sola tarda 254 s. Con ocho vistas y una
pasada por cada botón caro, la cifra real está en horas, no en los 110 minutos
que decía esta tabla. Una puerta que cuesta media jornada deja de usarse, y una
puerta que no se usa no protege nada.

El reparto queda así:

| cambio | qué hay que pasar |
|---|---|
| cualquiera | `test_catalogo_y_cuotas.py`, siempre |
| interfaz | + `smoke_botones.py --rapido`, o AppTest dirigido a las vistas tocadas |
| **motor** (`league_engine`, `alpha_finder`, `clasificador`, motores de deporte) | + smoke completo |
| ninguno en particular | smoke completo **una vez por semana** |

Lo que NO cambia, y es la mitad que sostiene el reparto: **el render se sigue
validando siempre**. `py_compile` y el AST no ven un `UnboundLocalError`; sólo
AppTest. Lo que se sustituye es *correr las ocho vistas con todos sus botones*
por *abrir con AppTest las vistas que el cambio toca* — que es minutos y cubre
el mismo modo de fallo en el sitio donde el cambio puede provocarlo.

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
  - **v177.1 — esa última parte YA NO ES CIERTA.** AppTest sí expone
    `segmented_control` en Streamlit 1.61.1: `valida_render` lo pulsa
    para abrir la vista de mañana y el smoke recorre con él las cuatro
    vistas de «Apuestas del Día». La salvedad real es otra: `.options`
    devuelve los **rótulos ya formateados**, no los valores, así que
    hay que pulsar por índice o mandar la clave a ciegas.
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
5. ~~**Córners**: validar el nivel del modelo con lambdas de producción.~~ **HECHO
   en la v152, y el resultado cierra la línea**: el sesgo era +0,435 (no −1,3) y la
   base 4,0 estaba bien, pero la correlación con el total real es −0,0012 sobre
   11.856 partidos, 0 de 15 ligas por encima de 0,1. Se probó el modelo bueno con
   córners y remates REALES en 20 competiciones: mejora 0,005 sobre decir siempre
   la media de la liga, con p5 positivo en 2 de 20 (lo que da el azar en veinte
   pruebas). El total pasó a ser la media observada de la competición. **NO hay
   semáforo ni recomendación de córners, y para poder haberla harían falta líneas
   históricas de córners, que no existen gratis.** Ver §10 de la bitácora.
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

---

## 4h. v152 — MODO MODELO, Y LO QUE LOS DATOS DIJERON DE LOS CÓRNERS

Dos planes pedían lo mismo desde dos ángulos: ordenar por rendimiento del equipo
en vez de por error de precio, y explotar córners y ligas secundarias. Informe
completo en `VALIDACION_v152.md`; la parte que gobierna, en el §10 de la
bitácora.

### Lo que se midió ANTES de tocar nada, y cambió los dos planes

**1. El xG de este proyecto no es xG.** Lo escribe el generador sintético:
`xG = 0,776 + 0,200·goles + ruido(0,529)`. Ajustando xG contra goles en cuatro
históricos salen 0,785/0,201, 0,785/0,200, 0,776/0,203 y 0,775/0,208: la
calibración con tres decimales. La posesión igual
(`50 + 12·tanh(elo/300) + ruido(4)`, residual medido 3,97/3,95/4,00).
→ **No se entrena sobre xG y no se enseña xG ni posesión en pantalla.**

**2. La fórmula de córners no discrimina.** Con lambdas de producción y córners
100 % reales, 11.856 partidos: sesgo +0,435 (no −1,3), correlación **−0,0012**,
0 de 15 ligas por encima de 0,1 — y es una correlación *optimista*.

**3. Con datos reales tampoco hay señal.** 20 competiciones, 8.889 partidos de
juicio, split temporal: media de la liga MAE 2,6996; fórmula actual 3,0749
(peor en 19 de 20); fórmula recalibrando la base 3,0609; ridge con córners y
remates reales 2,6942. **Recalibrar el nivel recupera 0,014 de los 0,375: el
96 % del daño lo hace la parte variable, que es ruido.**

**4. Sólo 20 de las 75 competiciones tienen córners observados** — las de
football-data 'main'. En las otras 55 la columna existe y la escribió el
generador. La bitácora de la v146 decía «las 50 ligas los tienen al 100 %»:
tienen la COLUMNA al 100 %. **La J2 japonesa, la 2. Liga austriaca y la 3. Liga
alemana —los ejemplos del plan— no están.**

**5. Las ligas secundarias no son más predecibles en córners**: +0,0049 contra
+0,0062 de las principales.

**6. El tenis por superficie ya estaba hecho** (`DIFF_ELO_SUP` con indoor como
superficie propia, `DIFF_WIN_SUP_12M`, fatiga). No se tocó nada.

### Lo que se implementó

- **Pestaña «📊 Modo Modelo», primera y por defecto.** Ordena por probabilidad
  del modelo y enseña racha, goles, córners, remates, momentum y la racha del
  bando que toca jugar. Etiqueta pedida: `📊 Modelo: [Equipo] con X %`. **La
  advertencia medida (−4,66 % a −6,52 %) va DENTRO de la pantalla.** Los
  partidos sin modelo NO se rellenan con la probabilidad del mercado.
- **Filtro de ligas secundarias**, arriba junto al de deporte, afectando a todas
  las pestañas. `es_secundaria` devuelve `None` fuera del fútbol: la MLB salía
  como «MLB · MLB · secundaria», que era una afirmación que nadie hizo.
- **`rendimiento_equipos.py`**: forma, momentum y `stats_disponibles`, que
  decide qué es observado **reproduciendo el generador sintético** (determinista
  por MATCH_ID) en vez de con una lista escrita a mano. Caché en disco
  (`cache_columnas_sinteticas.json`, en .gitignore): 2,86 s → 0,20 s.
- **El total de córners pasa a ser la media observada de la competición**, y en
  las 55 sin datos la media de las comparables (9,613). Liga MX pasaba de 13,4
  córners y «Más de 9.5: 85,9 %» a 9,6 y 49,3 %. La sección devuelve
  `corners_de_datos` y `corners_procedencia`.
- **Corregido el motivo escrito en `cuotas_tablon`**, que afirmaba «la
  discriminación sí parece buena, correlación +0,81» a partir de **n=4**. Ese
  +0,81 era contra la LÍNEA de la casa, no contra el resultado.
- **7 tests nuevos** y `test_mensajes_sin_jerga_interna` ampliado a los módulos
  de vista. Suite: **866 checks, TODO OK**.

### Cobertura de ligas secundarias en el barrido

**49 de 50 competiciones disponibles entran en el barrido, 35 de ellas
secundarias.** La única fuera es **Polonia**: ESPN devuelve 400 para `pol.1`,
`pol.ekstraklasa`, `pol.2`, `pol.polska.1` y `pol.pl.1`. No es configuración
olvidada: no hay endpoint.

### El fallo que cazó la validación de render, y que llevaba versiones ahí

`dashboard_ui.py` usaba `logger.` en **seis sitios y no definía `logger` en
ninguno**. Los seis están dentro de un `except` que intenta dejar constancia
antes de degradar la pantalla, así que lo que hacían era lanzar
`NameError: name 'logger' is not defined` **encima** del error original: el
manejador se llevaba por delante la vista entera y además borraba la pista de
lo que había pasado.

Cinco llevaban versiones ahí, latentes, porque son caminos de excepción que casi
nunca se recorren. El sexto lo añadió esta misma versión y fue el que se
disparó. Lo cazó `valida_render.py` en la vista de «Apuestas del Día».

`py_compile` no lo ve: un nombre indefinido dentro de un `except` compila igual
de bien que uno definido. Ahora lo vigila `test_los_except_pueden_registrar_su_error`
con AST, en los cuatro módulos que pintan pantalla.

**Y es el argumento de por qué la validación de render no se relaja al quitar el
smoke del flujo diario**: lo que se cambia es el ALCANCE (las vistas que toca el
cambio, minutos) y no el MÉTODO (AppTest, siempre).

### Lecciones de esta tanda

- **Una medición optimista que sale a cero refuta de verdad.** La correlación de
  la fórmula de córners se calculó con fuga a favor del modelo, y aun así dio
  0,004. Cuando el límite superior es cero, no hace falta afinar el experimento.
- **Comprobar que un dato es un dato, antes de construir sobre él.** Tres de las
  cuatro mejoras propuestas se apoyaban en xG y posesión que no existen. El
  método que lo resolvió no fue leer el código: fue REPRODUCIR el generador y
  comparar valor a valor.
- **Un test que busca prosa no distingue una afirmación de su desmentido.** El
  check de «ya no se afirma que discrimine» falló porque el comentario nuevo
  CITA la frase vieja para explicar por qué era falsa. Se arregló mirando el
  texto EMITIDO, sacado del AST — donde además Python ya ha concatenado los
  literales adyacentes, que era el otro motivo del falso negativo.
- **Que un mercado esté mal cotizado y que tengamos con qué explotarlo son dos
  afirmaciones distintas.** La primera sobre los córners sigue en pie; la
  segunda está medida y es que no.

---

## 4i. v153 — POR QUÉ LA J1 NO ENSEÑABA LOS PARTIDOS DE LA SEMANA

La queja: «la J1 no muestra los partidos de la semana pasada». Cuatro hipótesis
sobre la mesa (descarga incompleta, filtro de ventana, ESPN sin resultados, bot
que no actualiza). Ninguna era la causa, y la de verdad era peor.

### Lo que NO era, medido

1. **La J1 no jugó del 16 al 20 de agosto.** ESPN da 0 partidos esos cinco días
   y 2 el día 21. La mayor parte del «hueco» no era un hueco.
2. **La descarga funciona.** `descargar_liga('jpn_j1')` devuelve 2.517 partidos
   hasta el 2026-08-21, incluidos los 2 del día 21 que football-data aún no
   publica: `_completar_desde_espn` hace exactamente su trabajo.
3. **El filtro de ventana no recorta nada reciente**, y la fuente
   (football-data `/new/JPN.csv`) también termina el 15-08, o sea que el CSV
   estaba sincronizado con ella.

### La causa raíz: el bot lleva dos días sin poder commitear

    2026-08-22  schedule  CANCELLED  1h00m21s   ← tope de 60 min
    2026-08-21  schedule  FAILURE      52m12s
    2026-08-21  dispatch  success      59m56s   (manual)

En el run cancelado (32555539614): arranca 05:54, termina de reentrenar hacia
las 06:20, y **se pasa 34 minutos subiendo assets al Release**. Lo matan en el
asset 40 de 54. El paso que commitea los CSV es el ÚLTIMO del job, detrás de
todo eso, así que **nunca se ejecuta**.

Lo demoledor: el runner tenía la J1 con sus partidos del 21 **a las 06:11**, y
no llegaron a `main`. Dos días seguidos se tiró una hora de reentrenamiento
porque lo barato y valioso —los CSV que lee la aplicación— estaba detrás de lo
caro y prescindible: re-subir 54 paquetes de pesos que en su mayoría no habían
cambiado.

Esto ya estaba anotado como pendiente («el workflow tardó 59m51s con tope de
60, va al filo»). **Ya no va al filo: se cae.**

### Alcance real, en las 49 competiciones

`_v153_auditar_frescura.py` compara, por competición, cuántos partidos da ESPN
por jugados que el CSV del repositorio no tiene:

    competiciones auditadas ..............  49
    con partidos que faltan ..............  19  (35 partidos en total)
    sin partidos jugados (parón) .........  10
    peor caso ............................  Ligue 2, 5 partidos

Todos los CSV terminan entre el 14 y el 20 de agosto y ESPN llega al 21: **el
desfase es de 1 a 3 días en todas, ninguna tiene un agujero estructural.**

### Lo corregido

1. **Un commit temprano de históricos y estado**, justo después del
   reentrenamiento y ANTES de publicar los assets. Idempotente, y no sustituye
   al commit final: lo que cambia es que un fallo posterior ya no se lleva por
   delante los datos del día.
2. **Sólo se re-suben los assets que cambiaron** (`publicar_modelos.py`). La
   firma es del CONTENIDO de la carpeta y no del `.tar.gz`, porque gzip escribe
   su marca de tiempo en la cabecera y dos paquetes del mismo contenido nunca
   son iguales byte a byte — comparando el paquete, el salto no se activaría
   nunca. El manifiesto vive como un asset más del Release y se contrasta
   ADEMÁS con los assets que existen de verdad, para que borrar uno a mano no
   deje una competición sin pesos para siempre. Queda `--forzar` como salida.
3. **`timeout-minutes` de 60 a 90.** El tope no era holgado: era el que mataba
   el job.

### La lección

**Una métrica en días miente cuando hay parones.** La primera versión de la
auditoría midió el desfase en días y sacó que la Premier llevaba 89 días de
retraso. Suena a avería y no lo es: su CSV termina el 24 de mayo porque ahí
acabó la temporada, y el 21 de agosto se jugó la primera jornada de la
siguiente. Su desfase real era **un partido**. La métrica cometía exactamente
el mismo error que la queja que venía a investigar: contar el calendario en vez
de contar los partidos.

## 4o. v160 — TARJETAS CALIBRADAS Y EL ÁRBITRO DESIGNADO

Lo pedido: aplicar a tarjetas la metodología de córners (estimador
ataque/defensa + binomial negativa), enseñarlas en la tarjeta con su apuesta
más probable en ámbar, e integrar el perfil del árbitro. El detalle medido está
en la **§11 de la bitácora**; aquí lo que hay que saber para seguir trabajando.

### Lo que cambió de lo que se esperaba

**1. Una «tarjeta» son amarillas MÁS rojas.** La primera versión contó sólo
amarillas y quedó 0,27 por debajo del centro de la línea real de la casa, con
la brecha creciendo según subía la línea — firma de contar una magnitud más
pequeña, no de discrepar con el mercado. Las rojas valen 0,25/partido. Contarlas
mejoró también la calibración contra el resultado REAL (0,0141 → 0,0117 por
equipo), así que no es un apaño para parecerse al mercado.

**2. En el total gana el estimador del partido, al revés que en córners.** La
media de la competición tiene correlación 0,003 con el total de tarjetas (en
córners era la mejor opción). El ataque/defensa llega a 0,110 y cuadruplica la
calibración (0,0119 contra 0,0488).

**3. La binomial negativa aporta, pero por las rojas.** Sólo con amarillas la
dispersión sale ≤1,0 en 19 de 20 competiciones y binneg degenera en Poisson.
Con rojas sube a 1,35 (Turquía), 1,37 (Portugal), y binneg gana a Poisson
(0,0119 contra 0,0134).

**4. ESPN NO da el árbitro antes del partido.** Medido: 89,8 % de los jugados,
**0 de 41** de los que faltan por jugar. El campo no se rellena hasta el
pitido. La fuente es **FotMob**, con dos endpoints sin clave:
`/api/data/matches?date=YYYYMMDD` (índice del día) y
`/api/data/matchDetails?matchId=N` (el árbitro y su perfil).

**5. El árbitro SÍ es señal, medido, pero hay que encogerlo mucho.** Brier
0,20500 → 0,20344 y correlación 0,103 → 0,133, mejorando en las 6 competiciones
con muestra. Con K=0 la razón cruda EMPEORA la calibración (0,0153 → 0,0371).
K=60 es donde el Brier toca fondo.

### Módulos nuevos

- `arbitro_partido.py` — el árbitro designado y su factor. Precálculo diario a
  `arbitros_dia.json`, que el bot corre **antes** del guardado temprano (un
  designado que no se guarda hoy no se recupera: FotMob lo sustituye por el que
  pitó). Cobertura medida: 48/48 fixtures emparejados, 35 con árbitro.
- `snapshots_tarjetas.py` — las líneas de la casa. 2.010 filas de 48 partidos
  en la primera captura. Es la única vía que desbloquea el p5 de tarjetas.
- `rendimiento_equipos.py` §v160 — `tarjetas_equipo`, `lambda_tarjetas_equipo`,
  `dispersion_tarjetas_liga/_equipo`.
- `modo_modelo.tarjetas_tarjeta` / `_bloque_tarjetas_html` — la sección de la
  tarjeta, en ÁMBAR.

### Lo que queda ABIERTO y hay que cerrar con datos

**Si la casa cuenta la segunda amarilla como una tarjeta o como dos.**
football-data suma la roja de la doble amarilla en `home_red` y las dos
amarillas en `home_yellow`, así que aquí cuenta como tres. Queda un residuo de
−0,10 en la línea 5,5 que puede ser eso o ruido de n=14. Lo cierra
`tarjetas_snapshots.csv` cuando haya líneas liquidadas.

### VALIDACIÓN

- `test_catalogo_y_cuotas.py`: **1.067 checks, TODO OK** (eran 987; los 5 tests
  nuevos añaden 80).
- `valida_render.py`: las 3 vistas, limpias.

---

## 4p. v160 — POR QUÉ FALTAN PARTIDOS EN LA LISTA (diagnóstico medido)

HMREY reportó 55 partidos un sábado y echó en falta al Real Madrid y al Bayern.
Sondeadas las 64 competiciones que el proyecto codifica más 38 que no, el
2026-08-22: **ESPN tenía 224 partidos de fútbol ese día.** Las causas de la
diferencia son tres, y sólo dos son corregibles.

### Causa 1 — los ya jugados se excluyen a propósito (la mayoría)

`fixtures_espn._fixtures_de_codigo` descarta todo evento con
`status.type.completed`. Es correcto: no se puede apostar un partido acabado.
De los 224 de ese día, la mayoría estaban `post` cuando HMREY miró.

**El Real Madrid entra por aquí**: jugó en Espanyol, en LaLiga, que SÍ se barre
— pero el partido ya había terminado.

### Causa 2 — 15 competiciones apagadas por no tener modelo (28 partidos ese día)

Tienen histórico y `team_stats`, pero **no tienen carpeta en `modelos/`**, así
que están con `disponible: False`. Y el workflow entrena «cada liga
disponible», o sea que nunca se entrenan: es un círculo cerrado.

| clave | partidos el 22/8 |
|---|---|
| `eng_championship` | 11 |
| `ven_primera` | 5 |
| `bel_pro_league` | 3 |
| `slv_primera` | 3 |
| `crc_fpd` | 2 |
| `aut_bundesliga` | 2 |
| `ned_eerste`, `par_division` | 1 cada una |

Las otras (`suiza`, `aus_aleague`, `eng_fa_cup`, `ind_isl`, `esp_copa_rey`,
`bra_copa`, `eng_carabao`, `ksa_pro`) no jugaban ese día.

**Medido**: entrenar `eng_championship` funciona y tarda **52,4 s**. Su
precisión de validación sale 43,89 % contra 44,81 % de la línea base de ELO — o
sea que su modelo 1X2 NO bate ni a su propio ELO. Encender las 15 son ~13 min
más en un job que ya se ha caído por timeout (v153, 60→90 min).

### Causa 3 — competiciones sin código ESPN (27 partidos ese día)

| competición | slug ESPN | partidos el 22/8 |
|---|---|---|
| Copa de Alemania (DFB Pokal) | `ger.dfb_pokal` | 11 |
| USL League One | `usa.usl.l1` | 8 |
| Liga de Arabia | `ksa.1` | 4 |
| NWSL | `usa.nwsl` | 3 |
| **Supercopa de Alemania** | `ger.super_cup` | 1 |

**El Bayern entra por aquí**: jugó contra el Dortmund la Supercopa de Alemania,
y el proyecto no tiene ese código. Añadir el código NO basta: sin histórico ni
modelo la liga se descarta igual en el bucle del barrido.

### Lo que NO es la causa

- No es la ventana temporal (`_en_ventana` cubre 3 días UTC y la interfaz
  recorta por CDMX; se comprobó).
- No es que `fixtures_multi` falle: `eng_league_one`, `eng_league_two`,
  `eng_national` y `sco_championship` devuelven 0 porque sus 39 partidos de ese
  día ya estaban jugados, no por un error.

Scripts del diagnóstico: `_v160_cobertura_hoy.py`, `_v160_donde_se_caen.py`.

## 4q. v161 — QUE SALGAN TODOS LOS PARTIDOS

Respuesta al diagnóstico de la §4p. Se atacan las dos causas corregibles; la
tercera queda pendiente y se dice por qué.

### 1. Doce competiciones encendidas (50 → 62 disponibles)

`aut_bundesliga`, `eng_championship`, `bel_pro_league`, `ned_eerste`,
`slv_primera`, `par_division`, `crc_fpd`, `ven_primera`, `aus_aleague`,
`eng_fa_cup`, `ind_isl`, `bra_copa`.

Estaban apagadas con una nota del tipo «no bate ELO (0,4422 vs 0,4496)»,
medida entre la v39 y la v106. **Esa regla ya no decide nada**, y está medido
después: el modelo bate al mercado en 1 de 34 ligas (v90), apostar su
probabilidad pierde entre −4,66 % y −6,52 % sobre 37.158 apuestas, y lo que
gana es comprar al mejor precio (+11,49 %, p5 +1,73 %). El semáforo de la
Sección 1 va por VENTAJA DE PRECIO, que no depende de lo bueno que sea el 1X2
de la liga. Filtrar por el acierto del modelo quitaba partidos sin proteger de
nada: **28 en un sábado normal**.

**La nota de cada liga se conserva** y se le añade que está encendida a pesar
de eso, para que nadie las apague dentro de un año creyendo que se coló un
descuido.

Dos de ellas son de formato `main` de football-data —`eng_championship` (11
partidos ese sábado) y `bel_pro_league`— así que además traen **córners y
tarjetas OBSERVADAS y árbitro en el histórico**, que es justo lo que la v160
necesita.

**Siguen apagadas 4, y por falta de datos, no de criterio:**

| clave | qué le falta |
|---|---|
| `esp_copa_rey`, `eng_carabao` | sin `team_stats_*.json` |
| `ksa_pro` | sin histórico y sin `team_stats` |
| `suiza` | sin código ESPN en el proyecto |

**Aviso que hay que tener presente**: sus modelos NO existen todavía en
`modelos/`. El workflow entrena «cada liga disponible», así que aparecerán en
el próximo reentrenamiento (~52 s por liga medido con `eng_championship`, unos
**10 min más** de job). Hasta entonces salen en `ligas_sin_motor` de la pestaña
Estado, que es el comportamiento correcto: se ven y se dice que les falta el
modelo, en vez de desaparecer en silencio.

### 2. Los partidos ya jugados, aparte y bajo demanda

`fixtures_liga` descarta todo evento `completed`, y **eso no se ha tocado**: un
partido acabado no es un pick, y dejarlo entrar en el barrido podría convertirlo
en uno o mandarlo por Telegram. Lo que se añade es una puerta aparte:

- `fixtures_espn.jugados_del_dia(claves, dia)` — 149 partidos del 22/8 en 5,2 s.
- `modo_modelo._bloque_jugados` — un **botón** al pie de la lista. No pide nada
  hasta que se pulsa, porque son 61 peticiones y el barrido tardó de la v148 a
  la v154 en bajar de 119 s a 52.
- Salen con su marcador y **sin probabilidad**: enseñar lo que el modelo
  «habría dicho» de un partido ya jugado sólo sirve para engañarse.

### 3. Lo que NO se hizo, y por qué

Las competiciones sin código ESPN en el proyecto (Copa de Alemania 11 partidos,
Supercopa de Alemania —donde jugó el Bayern—, Arabia, NWSL, USL League One)
**siguen fuera**. Añadir el código no basta: sin histórico ni modelo, el bucle
del barrido las descarta igual. Cada una necesita su pipeline de datos, que es
una tanda propia.

### VALIDACIÓN

- `test_catalogo_y_cuotas.py`: TODO OK, con 2 tests nuevos.
- `valida_render.py`: las 3 vistas, limpias.
- `test_ligas_migradas` dejó de fijar `disponible` (fijaba `aut_bundesliga`
  apagada por la regla de la v75). Sigue fijando el **formato**, que sí es una
  propiedad de la fuente y no una decisión revisable.

## 4r. v162 — CÓRNERS Y TARJETAS EN TODAS LAS LIGAS, Y LOS JUGADOS EN LA LISTA

Dos encargos. El detalle medido está en la **§12 de la bitácora**; aquí lo que
hace falta para seguir trabajando.

### PARTE 1 — los partidos ya jugados, en la lista principal

La v161 los puso detrás de un botón. Ahora van **en la misma lista**, ordenados
por hora, con `✅ Finalizado` y su marcador, y con la tarjeta entera: barras
1X2, goles, BTTS, córners, tarjetas y rachas.

**El pronóstico NO se recalcula.** Se recupera de `predicciones_dia.json`, que
el bot escribió por la mañana cuando el partido aún no se había jugado.
Recalcularlo daría otro número —el ELO y las medias móviles ya se movieron con
el resultado— y enseñarlo como «pronóstico previo» sería mentir con precisión
decimal. Módulo: `partidos_jugados.de_dia`.

**Siguen sin poder ser un pick**: no pasan por `alpha_finder`, no tienen EV, no
se comparan con la cuota y no llegan a Telegram. `fixtures_liga` sigue
descartando los `completed` — esto es aditivo.

**Y no cuestan una petición.** La primera versión pedía 61 llamadas nuevas y
medido: la vista «Apuestas del Día» dejaba de terminar. Ahora
`_fixtures_de_codigo` **apunta al pasar** cada evento acabado del scoreboard que
ya estaba descargando, y su rango empieza un día antes (mismo número de
peticiones, JSON algo mayor) porque los partidos de hoy en CDMX caen en el día
UTC anterior. Medido: 155 acabados apuntados gratis, `jugados_del_dia` en 3,9 s
contra 10,2 s.

Cuidado con una trampa que se cerró: el día de más es **sólo para apuntar**. Un
partido de ayer que no esté `completed` —suspendido, en curso— pasaría el filtro
y entraría como apostable. Hay una guarda explícita (`if fecha.normalize() <
hoy: continue`) y un test que comprueba que salen 0 fixtures anteriores a hoy.

### PARTE 2 — córners y tarjetas calibrados en TODAS las competiciones

**El hallazgo: el `summary` de ESPN trae un `boxscore` con 28 estadísticas por
equipo** —`wonCorners`, `yellowCards`, `redCards`, `foulsCommitted`,
`possessionPct`, `totalShots`, `shotsOnTarget`…— y el proyecto lleva usando ese
endpoint desde la v35 sin abrir esa clave. 23 de 34 competiciones sondeadas lo
traen, incluidas Liga MX, Argentina, Brasil, MLS, Colombia, Chile, Perú, Japón.

**Validado contra football-data antes de construir nada**: 216 partidos, los
mismos en las dos fuentes. Córners 93-96 % idénticos con correlación 0,985;
amarillas 0,955; rojas 100 %; remates 0,988. Es fuente observada, no estimación.

**Arquitectura**:

- `stats_espn.py` — descarga y caché en `stats_espn/<liga>.csv.gz`.
- `league_engine.descargar_liga` la **inyecta ANTES** del generador sintético.
  Ese orden es todo el mecanismo: el generador sólo rellena huecos, así que lo
  real gana. NO se parchea el CSV, porque `descargar_liga` lo reconstruye cada
  noche y el parche duraría un día.
- `stats_disponibles` no se tocó: decide reproduciendo el generador, así que en
  cuanto llegan valores reales la reproducción falla y la columna pasa a
  observada sola.

**Dos arreglos que el cambio obligó a hacer, y sin los cuales no funciona**:

1. `_columnas_sinteticas` muestrea ahora `d.tail(400)` y no `d.head(400)`. La
   cobertura de ESPN arranca en 2021 y varios históricos empiezan en 2018: con
   la cabecera, la competición nunca se declararía observada.
2. `inyectar` marca cada fila con `stats_origen`, y las medias y dispersiones
   filtran por esa marca (`rendimiento_equipos._solo_reales`). Una columna
   mezclada no se puede promediar entera.

**El fallo más caro de la tanda**: ESPN devuelve el boxscore **a ceros** en el
7,0 % de los partidos —posesión 0-0, faltas 0, córners 0— y eso no es un partido
sin córners, es un partido sin datos. Colados como buenos, en la Liga MX la
dispersión salía 2,04 y el error de calibración 0,0288; quitándolos, 1,63 y
**0,0111**. El detector es la posesión, que siempre suma ~100 en un partido real.

**Lo que queda estimado**: `stats_estimadas` da el nivel de la competición
derivado de sus goles, validado dejando una liga fuera. Córners 0,0247 (por
debajo del umbral de 0,05) y tarjetas **0,0539** (por encima, y la interfaz lo
dice con un aviso más fuerte). NO se modula por el ataque del equipo: en córners
sube la correlación (0,160 → 0,234) pero empeora la calibración (0,0247 →
0,0326), y en tarjetas la correlación sale **negativa** (−0,080).

**Informe**: `python informe_calibracion.py --md INFORME_CALIBRACION.md` da la
tabla por competición. Mide sobre la caché de `stats_espn`, así que no hace
falta reconstruir los 61 históricos para tenerla.

### PENDIENTE de esta tanda

1. **El backfill histórico completo** (`python stats_espn.py --desde 2021-01-01`)
   tarda ~3-4 h para las 61 competiciones. Si se interrumpe, se relanza y sigue
   donde estaba: salta los `event_id` ya guardados.
2. **Las competiciones sin boxscore en ESPN** (Irlanda y Finlandia salieron con
   0 en la primera pasada) se quedan con la estimación. Hay que listarlas en el
   informe y decidir si merece la pena FotMob para ésas — a 1,7 s por partido
   contra 0,05 s de ESPN.
3. **El primer `--build` tras esto reescribe los 61 históricos** con las
   estadísticas inyectadas. Es cuando el usuario empieza a ver «observado» en
   vez de «estimado».

---

## 4s. v163 — REMATES POR EQUIPO Y POR JUGADOR, CON ALINEACIÓN

Tercer mercado físico, con la metodología de córners (§10) y tarjetas (§11).
Todo lo medido está en **§13 de la bitácora**; aquí queda lo que hay que saber
para seguir trabajando.

### Lo que se añadió

| pieza | dónde |
|---|---|
| λ de remates por equipo (totales y a puerta) | `rendimiento_equipos.remates_equipo` |
| estimación donde no hay datos | `stats_estimadas` (objetivos `rem` y `rem_on`) |
| probabilidad por jugador + alineación | `remates_jugador.py` (nuevo) |
| bloques 🎯 y 🥅 en la tarjeta | `modo_modelo.remates_tarjeta` |
| «Quién remata» en la tarjeta | `modo_modelo.quien_remata_tarjeta` |
| sección completa en la ficha | `dashboard_ui.render_remates_partido` |
| precálculo diario del once | `remates_jugador.py --dias 2` en el workflow |
| informe por competición | `informe_calibracion.py`, ahora con 4 mercados |
| foto diaria de las líneas | `snapshots_remates.py` (nuevo) |

### LO MÁS IMPORTANTE QUE SALIÓ DE AQUÍ, Y NO ES SOBRE REMATES

**El error marginal —la métrica con la que se cerraron córners y tarjetas—
habría elegido el PEOR estimador de la tabla.** La media móvil de 5 con Poisson
gana esa columna en los dos objetivos y es la última por Brier y por ECE, con la
calibración por deciles cuatro veces peor que la del ganador. Son dos sesgos que
se cancelan en la media.

Desde la v163 se miden **tres** números y se elige por ECE: `marginal` (que el
nivel no esté sesgado), `brier` (que la probabilidad se mueva en la dirección
correcta) y `ece` (calibración por deciles). Las decisiones de córners y
tarjetas **no están desmentidas** —el estimador ganador es el mismo en los tres
mercados— pero se tomaron con la primera columna sola. Antes de mover algo allí,
medir las tres.

### Números que fijan el comportamiento

    remates totales por equipo, observados ...  marginal 0,0131 · ECE 0,0313
    remates a puerta por equipo, observados ..  marginal 0,0129 · ECE 0,0273
    total del partido (suma de lambdas) ......  marginal 0,0151 / 0,0111
    estimados sin datos (liga fuera) .........  0,0281 totales · 0,0168 a puerta
    dispersión por equipo ....................  2,09 totales · 1,36 a puerta
    dispersión del total del partido .........  1,35 · 1,13
    por jugador, P(≥1 remate), encogido K=6 ..  Brier 0,18746 · ECE 0,0287
    por jugador, P(≥1 a puerta), K=12 ........  Brier 0,13992 · ECE 0,0245

Cobertura sobre la caché de `stats_espn`: **44 de 61** competiciones con remates
observados, error medio 0,0164 (totales) y 0,0173 (a puerta).

### Tres cosas que NO se pueden prometer, y están medidas

1. **Esto no es una ventaja de precio.** Como córners y tarjetas: no hay
   histórico de líneas de remates con el que calcular un p5. Ámbar, no verde.
2. **Saber quién juega no calibra.** La frecuencia de titularidad da ECE de
   0,057 a 0,073, por encima del umbral de 0,05. Sin alineación publicada, la
   interfaz lo dice; no ordena la lista y se calla.
3. **Por debajo de 4 apariciones no hay medición.** Esas filas salen con
   asterisco. En agosto son casi todas.

### La alineación: de dónde sale y de dónde no

- **ESPN no sirve**: once inicial en 50 de 50 partidos JUGADOS y **0 de 54** por
  jugar, uno de ellos a 4,4 h del saque. Misma firma que el árbitro en la v160.
- **`goleadores_cache.json` NO tiene alineaciones.** Tiene el roster de
  temporada, que no depende del partido. Es fácil creer lo contrario.
- **FotMob sí**: 27 de 50 partidos por jugar (54 %), de los cuales 21
  `predicted` y 6 `lastStarting11`. Los tipos se distinguen en pantalla.
- Ruta buena: `content.lineup.homeTeam.starters`, tipo en `lineupType`.
- Se precalcula en el bot a `alineaciones_dia.json`. **La tarjeta no pide nada a
  la red.**

> Si alguien toca el lector de alineación: volver a pasar
> `_v163_verificar_lector_lineup.py`. La primera versión devolvía cero SIEMPRE
> por mirar la ruta equivocada, y parecía que FotMob no publicaba nada. Un
> sondeo que no encuentra nada y un lector roto se parecen demasiado.

### DOS TRAMPAS DE RENDIMIENTO QUE YA MORDIERON

1. **`goleadores.plantilla_equipo` sale a ESPN cuando su entrada no está en la
   caché.** Enchufarlo a la tarjeta sin más llevó «Apuestas del Día» de 85-239 s
   a **383 s** medidos con AppTest. La tarjeta usa ahora
   `remates_jugador._roster_cacheado`, que lee el fichero y nada más: 0,07 s por
   partido. Lo que no esté cacheado no sale, y el workflow lo rellena a diario.
2. **`remates_jugador.alineacion` no toca la red por defecto.** Sesenta partidos
   por un `matchDetails` de 1,7 s serían dos minutos más de pantalla. Sólo la
   ficha pasa `permitir_red=True`.

### Dos agujeros arreglados por el camino (no eran del encargo)

- **El catálogo de equipos de ESPN se cacheaba incompleto.**
  `remates_jugadores.equipos_de_liga` paraba a los 16 nombres; a finales de
  agosto un tramo de 55 días no cubre una jornada. La Serie A tenía 16 equipos
  (sin Roma, Lazio, Fiorentina ni Bologna) y LaLiga 19 (sin Osasuna), y la
  sección de jugadores salía VACÍA para ellos sin un aviso.
- **El 10,5 % de los equipos no encontraba su nombre en ESPN** («Roma» contra
  «AS Roma» se queda en 0,73 y el umbral es 0,78, porque `normalizar` quita
  sufijos societarios pero no prefijos). Resuelto con **21 alias verificados uno
  a uno** contra el catálogo real de cada competición: de 30 fallos a 9. Los 9
  que quedan son equipos que cambiaron de división.
  El nombre de ESPN se añade **detrás** del destino que ya hubiera, así que el
  emparejado contra el catálogo del proyecto no cambia ni un caso.

  Arreglar `name_mapper.normalizar` para que quite también los prefijos
  liquidaría la familia entera, pero mueve TODOS los emparejados del proyecto
  —cuotas, liquidación, fixtures— y eso es una medición aparte que aquí NO se ha
  hecho.

### Emparejar el once con las estadísticas

132 nombres de once en 12 partidos: 88 casados (67 %), 21 ausentes de ESPN
(fichajes recientes), 21 filtrados por tener menos de 2 partidos, y **2 fallos
reales del emparejador (2 %)**. Un nombre que no casa no se fuerza.

### Scripts de medición (no borrar, documentan las decisiones)

    _v163_cobertura_remates.py          qué ligas tienen remates observados hoy
    _v163_remates_estimadores.py        los 4 estimadores × 2 distribuciones
    _v163_remates_total.py              ¿sumar lambdas o media de liga?
    _v163_remates_estimados.py          validación dejando una liga fuera
    _v163_remates_jugador.py            el modelo por jugador y el encogimiento
    _v163_cuota_posicional.py           la tabla de cuotas por posición
    _v163_sondeo_alineacion.py          ESPN no da el once antes del partido
    _v163_sondeo_fotmob_lineup.py       FotMob sí
    _v163_verificar_lector_lineup.py    CONTROL: ¿el lector funciona?
    _v163_emparejado_jugadores.py       ¿casan los nombres?
    _v163_resolver_equipos.py           qué equipos no encuentran su nombre

### PENDIENTE de esta tanda

1. **`snapshots_remates.py` ya captura, pero el fichero está vacío.** Sin
   volumen no hay nada que liquidar, así que los remates seguirán en ámbar
   varios meses. Es el mismo calendario que `corners_snapshots.csv` (4.200
   filas desde la v159) y `tarjetas_snapshots.csv` (v160). Cuando haya
   volumen: liquidar contra el resultado real y medir el p5. Si sale positivo,
   el ámbar puede pasar a verde; si no, se cierra con datos.

   La trampa de ese módulo, ya resuelta y con test: «Tiros de esquina» ES el
   mercado de córners y lleva «tiros» dentro. Si entrara, el fichero
   acumularía córners rotulados como remates durante meses y el fallo saldría
   a la luz cuando ya no tuviera arreglo.
2. **La tabla de cuotas por posición está ajustada con TRES competiciones**
   (Premier, LaLiga, Liga MX). La dispersión relativa entre ellas es 0,077 en
   totales pero **0,202 a puerta**, y ahí los peores son porteros y defensas
   —donde la cuota es minúscula de todos modos—. Ampliarla a 6-8 ligas es barato
   (`_v163_remates_jugador.py <code>` cachea la descarga en
   `_v163_cache_jugadores/`) y cerraría la duda.
3. **Los rosters cacheados antes de la v163 no traen `al_arco`.** El campo
   `shotsOnTarget` se añadió a `goleadores._roster_crudo`, pero las entradas ya
   guardadas no lo tienen y esos jugadores salen sin el mercado «a puerta» en la
   tarjeta. Se arregla solo cuando `precalcular_rosters.yml` refresque (TTL de 3
   días); no hace falta invalidar nada a mano.
4. **`dispersion_corners_liga` y `dispersion_corners_equipo` NO recortan a las
   últimas temporadas** y `media_corners_liga` sí. En remates ese recorte hace
   falta (la Premier cambia de definición entre 2013 y 2014 y la dispersión pasa
   de 1,07 a 1,62). No se han tocado porque su calibración está cerrada con ese
   comportamiento, pero conviene medirlo.
5. **La ventana de remates es de 6 temporadas**, así que un equipo recién
   ascendido cae al estimador de liga hasta que acumule partidos. Es correcto y
   está marcado, pero se nota en agosto.

## 4v. v165 — EL CONTROL DE CORDURA: NINGÚN PORCENTAJE SIN CONTRASTE

El detalle completo está en **BITACORA_ARQUITECTURA.md §15**. Lo esencial:

**El caso.** Parlay perdido del 2026-08-23: Celta B–Andorra con `✅ Menos de 2.5
— 80 %` (acabó 4-2), la pata de córners de Bologna–Lazio y las dos de
Brøndby–Silkeborg. El fallo no es acertar o no un partido: es que la pantalla
publicó en verde una convicción que nada sostenía.

**La causa medida.** De los 156 pronósticos de fútbol del barrido cacheado,
**ninguno** llevaba `cuota` en sus mercados: `pronosticos` lo construye
`_mercados_modelo`, que emite cuota justa a propósito. La tarjeta nunca tuvo con
qué contrastarse, y así **103 de 151 tarjetas iban en verde**.

**Lo hecho.**

* `mercado_implicito.py` — 1X2, goles (todas sus líneas) y BTTS del tablero de
  la casa, devigados con `potencia`. Precálculo diario en `mercado_dia.json`,
  en el mismo paso del workflow que las líneas de jugador (mismo tablero, caché
  de disco de 30 min: casi no descarga de más).
* `alpha_finder.implicitas_de_la_casa` — el precio viaja CON el pronóstico. Se
  adjunta ahí y no se busca desde la tarjeta por dos motivos: los nombres (desde
  la tarjeta sólo 22 de 151 encontraban su entrada, porque la llave del
  precálculo es el nombre del FIXTURE) y porque la tarjeta no pide red.
* `cordura_probabilidad.py` — los tres frenos: desvío > 15 pp contra la casa →
  recorte al 60 % y «🔴 poco fiable»; techo por media de goles de la liga (65 %
  si la línea cae por debajo de la media, 50 % si cae 0,5 o más); y **sin precio
  no hay verde**.
* `modo_modelo` — el titular se elige DESPUÉS del recorte, la tarjeta dice por
  qué bajó la cifra, pinta el precio de la casa bajo el de goles, y los bloques
  físicos sin insignia van en gris (`mm-sinsena`).
* `alpha_finder._mismo_partido` — descarta el precio cuando el 1X2 de la casa y
  el de ESPN discrepan más de 0,10. Destapó un emparejamiento roto de `_buscar`
  (Botafogo–Athletico-PR casado con Botafogo SP–Atlético del mismo día).

**Estado medido tras el cambio** (barrido del 2026-08-24, 61 partidos de fútbol
con modelo, con `mercado_dia.json` generado):

    con precio de la casa adjunto        59 de 61
    con la línea 2.5 de la casa          53
    titulares contrastables              47  (77 %)
    marcados «poco fiable»               18  (38 % de los contrastables)
    recortados por alguna regla          12
    en VERDE                             22  (antes: casi todo lo que pasaba de 60 %)

Los 18 «poco fiable» sobre 47 contrastables son el hallazgo, no un efecto
secundario: **el modelo se separa más de 15 puntos de la casa en dos de cada
cinco titulares que se pueden comprobar.**

**Lo que NO toca.** La Sección 1, el EV y `pasa_capa1`. La ventaja de precio es
el único canal con p5 positivo medido y se calcula sobre la probabilidad cruda.
Todo esto vive en la capa de presentación.

**Validación.** Suite 1.459 checks TODO OK · `valida_render.py` 3 vistas OK ·
`_v164_valida_tarjeta.py` OK · `_v163_valida_ficha_remates.py` OK.

**Pendientes que deja.**

1. La cobertura del precio es el techo del verde. Playdoit cotiza 54 de 75
   fixtures (72 %); lo que no cotiza no puede ir en verde nunca. Subirlo es
   trabajo de emparejamiento (pendiente 10), no de umbral.
2. Los 18 «poco fiable» merecen liquidarse: ¿acierta más el modelo o la casa
   cuando discrepan 15 puntos? Con `mercado_dia.json` acumulándose a diario, en
   unas semanas se puede medir y el umbral dejaría de ser una elección.
3. `_buscar` empareja partidos distintos del mismo día y la misma categoría. El
   control de `_mismo_partido` lo tapa AQUÍ, pero el resto del proyecto
   —line shopping, snapshots, líneas de jugador— sigue expuesto.
4. El techo por liga usa la media de goles de las últimas 3 temporadas. En las
   competiciones sin histórico suficiente (< 100 partidos) devuelve `None` y la
   regla no se aplica: ahí sólo protege el contraste contra la casa.

## 4w. v166 — EL UMBRAL MEDIDO CON EL HISTÓRICO QUE YA HABÍA

Detalle completo en **BITACORA_ARQUITECTURA.md §16**. Lo esencial:

**No hubo que esperar.** `_v166_umbral_cordura.py` mide sobre
`pick_ledger_totales.csv` (17.532 partidos con cuota O/U) y `pick_ledger.csv`
(36.025 con cierre 1X2), los dos walk-forward y ya en el repo.

**Tres hallazgos, en orden de importancia:**

1. **El valor absoluto escondía el problema.** Separando por dirección, el 1X2
   pasa de «brecha ≤0,008 en todos los tramos» a 0,176 cuando el modelo va por
   encima de la casa. Los dos sesgos se cancelaban — la trampa del §2b otra vez.
   El recorte es ahora de UN SOLO LADO: ir por debajo de la casa no se marca.
2. **El recorte era el síntoma.** El 1X2 se encoge hacia el mercado desde la
   v71; los goles nunca. Encogerlos con el mismo w=0,25 baja el ECE de 0,0948 a
   0,0139 y la brecha en el tramo de >15 pp de 0,2215 a 0,0211.
3. **El umbral medido es 5 pp**, no 15. Se escribe en `cordura_umbrales.json` y
   `cordura_probabilidad.umbral()` lo lee de ahí — no hay número a mano.

**Honestidad que hay que conservar:** por Brier y log-loss el peso óptimo de
goles es w=0,00, o sea el mercado solo. El modelo no aporta nada medible ahí.
Se usa 0,25 porque por ECE sí gana algo y porque publicar el mercado con la cara
del modelo sería la mentira contraria.

**Córners y la tarjeta:**

* Ya salían en las 62 competiciones (50 observadas + 12 estimadas en gris). Lo
  que no existía era la LÍNEA de la casa: se usaba «la media redondeada», una
  línea inventada. Ahora `mercado_implicito` saca el total de córners del
  tablero (32 de 53 partidos el 2026-08-24) y la tarjeta usa la real.
* Los remates por equipo VUELVEN a la tarjeta. Se pidió ver todos los mercados.

**Validación.** Suite 1.522 checks TODO OK · `valida_render.py` 3 vistas OK,
174 s.

**Pendiente que deja:**

1. **12 competiciones sin córners observados** (uru_primera, ven_primera,
   par_division, crc_fpd, slv_primera, finlandia, irlanda, polonia,
   mex_expansion, arg_primera_nacional, eng_national, champions). Medido: 9 de
   ellas **no tienen ni fichero `stats_espn/`** — nunca se barrieron. Y
   `champions` SÍ tiene 774 filas con córners reales en `stats_espn/` que **no
   están inyectadas** en su histórico (no tiene columna `stats_origen`): es
   dato que ya se pagó y no se está usando. Eso es lo siguiente, y no requiere
   FotMob.
2. FotMob sólo tiene ID mapeado para 8 ligas (`FOTMOB_LEAGUE_IDS`), ninguna de
   las 12. Un backfill por ahí cuesta 1,7 s por partido — unas 8 h para cinco
   temporadas de las doce. Es trabajo de workflow nocturno, no de sesión.
3. El umbral de BTTS es heredado, no medido: no hay cuota histórica de BTTS en
   ningún ledger. Si algún día se acumula, medirlo aparte.

## 4x. v167 — LA TARJETA ACCIONABLE

Detalle completo en **BITACORA_ARQUITECTURA.md §17**.

**Qué cambia en pantalla.** La tarjeta pasa de informar a recomendar:

    partido · liga · hora
    🏆 APUESTA RECOMENDADA   una, con cuota justa y botón «Jugar en Playdoit»
    📊 OTROS MERCADOS        una fila compacta por mercado, etiquetas cortas
    📊 Análisis completo     desplegable con TODO el texto técnico de antes

**`modo_modelo.apuesta_recomendada(pick, bloques)`** elige una apuesta de todo
el partido:

    1) ventaja de PRECIO: EV ≥ 3 % sobre la probabilidad YA AJUSTADA
    2) si no la hay, mayor probabilidad ajustada ≥ 60 % (el verde gana al %)
    3) si nada llega, lo mejor para combinar, en ámbar
    4) si no hay nada jugable, None — y la tarjeta lo PINTA

**El EV NO se calcula sobre la probabilidad cruda del modelo, y es deliberado.**
Ese canal está medido como anti-indicador (−4,66 % a −6,52 %) y además es máximo
justo donde la v166 midió que el número más miente. Sobre la probabilidad
ajustada, un EV positivo significa «la casa paga de más», que es el canal con p5
positivo. Si alguien lo cambia a EV crudo, reconstruye el fallo de la v165.

**Reglas que la recomendación no puede saltarse:** un mercado estimado nunca se
recomienda (v164); uno físico observado sí, pero siempre en ámbar (no tienen p5
medido); el verde exige contraste con la casa (v165).

**Dos ajustes hechos con medición delante:**

* El suelo del 50 % es sólo de la vía de probabilidad. Filtrarlo también en la
  de precio tiraba justo las apuestas de valor, que casi nunca son favoritas.
* El verde gana al porcentaje. Con esa regla, la tarjeta y el filtro «sólo alta
  probabilidad» discrepan en **0** de 40 partidos; sin ella, discrepaban.

**Medido:** 21 verdes · 18 ámbar · 1 sin apuesta, sobre 40 partidos. Ninguna por
la vía del precio todavía, porque los `pronosticos` llevan `cuota: None` por
construcción; la vía está probada y se activará al crecer la cobertura.

**Validación.** Suite 1.564 checks TODO OK · `valida_render.py` 3 vistas OK
(Apuestas del Día 115 s, antes 174) · `_v164_valida_tarjeta.py` OK ·
`_v163_valida_ficha_remates.py` OK.

**Pendiente que deja:**

1. El botón «Jugar en Playdoit» lleva a la portada de deportes, no al partido:
   `cuotas_multi` conoce el `event_id`, pero no está comprobado el formato de
   URL profunda de la casa. Medirlo y enlazar al evento exacto.
2. `apuesta_destacada` sigue existiendo y se usa para el orden de la lista
   (`_k_destacada`). Convendría unificarla con `apuesta_recomendada` cuando se
   toque el orden, para no dejar dos criterios vivos.
3. La vía del precio no se ha podido ejercitar con datos reales de producción
   (ver arriba). Cuando haya picks con cuota en `pronosticos`, medir cuántas
   recomendaciones salen por ahí y con qué ROI.

## 4y. v168 — MERCADO REY Y MODO SEGURIDAD

Detalle completo en **BITACORA_ARQUITECTURA.md §18**.

**`mercado_estabilidad.py` + `mercado_estable_por_liga.json`** miden con ECE
todo el catálogo en las 62 competiciones, sobre los tres ledgers walk-forward y
el informe físico que ya estaban en el repo.

**El hallazgo:** el mercado más fiable cambia por completo de liga a liga
—hándicap en 14, córners por equipo en 12, remates a puerta en 7, doble
oportunidad en 6, tarjetas en 8, 1X2 en 1— y **los goles salen 🔴 inestables en
todas**, con ECE de 0,086 a 0,129. Era el mercado del que salía el 64 % de los
titulares. BTTS tampoco corona ninguna: calibra 🔴 en todas.

**Dos calibraciones por fila y manda la que aplica:** `ece` (modelo crudo) y
`ece_ajustada` (encogida hacia la casa, que es lo que se enseña desde la v166).
Premier goles 2,5 pasa de 0,129 a 0,046 con el ajuste; el Brasileirão B no tiene
cuota en el ledger y se queda en 0,118 → cuarentena.

**Tres familias sin medir, marcadas y fuera del ranking:** goles por equipo,
resultado exacto y remates de jugador (este último medido pero AGREGADO, no por
liga). No se les inventa número.

**Modo seguridad — tres puertas que se apilan:**

    recorte     5 pp sobre la casa            medido v166   baja y marca 🔴
    bloqueo    10 pp sobre la casa            del encargo   no proponible
    cuarentena ECE > 0,05 o var/media > 2,0   medido v168   bloque no proponible

Un bloque en cuarentena SIGUE VIÉNDOSE con sus probabilidades y lleva
🔒 No recomendado. Mirar sí, proponer no.

**Orden de la recomendación:** precio → ranking de estabilidad (suelo 55 %) →
probabilidad → combinar. El precio va delante del ranking a propósito: el
ranking dice dónde es fiable el MODELO, el precio dónde se equivocó la CASA, y
sólo lo segundo tiene p5 positivo medido.

**Medido sobre 40 partidos:** la recomendación se reparte entre tarjetas (17),
resultado (4), goles (2), remates (2) y córners (1). Y 14 de 40 se quedan **sin
apuesta jugable**, frente a 1 de 40 antes.

**Interfaz:** tira de estabilidad de seis iconos sin leyenda, candados en los
bloques en cuarentena, desplegable `🔍 Análisis`, y ningún texto visible por
encima de 50 caracteres (hay test con regex).

**Validación.** Suite 2.268 checks TODO OK · `valida_render.py` 3 vistas OK ·
`_v164_valida_tarjeta.py` OK · `_v163_valida_ficha_remates.py` OK.
Coste medido del código nuevo: 0,27 s por 40 tarjetas.

**Pendiente que deja:**

1. `mercado_estable_por_liga.json` se genera a mano. Debería regenerarse en el
   workflow nocturno junto a `informe_calibracion.py`, o envejecerá.
2. Los seis «(ninguno)» son competiciones sin ningún mercado que pase el filtro.
   Merece mirar si es falta de muestra o de verdad no hay nada fiable.
3. El bloqueo de 10 pp lo fijó el encargo, no una medición. La v166 midió el
   corte de 5 pp; el de 10 se puede medir igual sobre los mismos ledgers.
4. La tira de estabilidad enseña seis bloques, pero el ranking tiene hasta
   catorce familias. La ficha del partido podría enseñar la tabla entera.

## 4z. v169 — LÍNEAS REALES DE LA CASA, GOLES MEDIDOS Y LA APUESTA LIQUIDADA

Detalle completo en **BITACORA_ARQUITECTURA.md §19**.

**1. El ranking deja de envejecer.** `mercado_estabilidad.py` corre ahora en
`recalibrar.yml`, justo DESPUÉS de `informe_calibracion.py` (de donde lee la
calibración física) y `mercado_estable_por_liga.json` se commitea.

**2. Las líneas de conteo se LEEN, no se suponen.**
`mercado_implicito._conteos_del_tablero` captura córners, tarjetas y remates —
del partido y de cada bando— con lo que traiga cada tablero. Cobertura medida
sobre 80 partidos: córners total 59 · tarjetas total 41 · remates 12 · a puerta
10 · **por equipo sólo 9-10**.

Se descartan, cada uno por su motivo: media parte, familias que no son
Más/Menos (exacto, escala, impar/par, 1x2, hándicap, carrera, ambos,
primer/último), **tarjetas rojas** (nuestro modelo es amarillas+rojas) y
**mercados de jugador** (se detectan por el paréntesis; excepción para clubes
con paréntesis en el nombre).

La tarjeta usa esas líneas en las tres filas —Total, Local y Visita— y las
rotula «línea de la casa».

**3. Goles: la medición dijo que NO al 0,6 del encargo.** Ajustado sobre 17.532
partidos:

    1,00 crudo      ECE 0,0948 · 20 de 20 ligas por encima de 0,05
    0,60 pedido     ECE 0,0472 · 16 de 20
    0,25 desplegado ECE 0,0139 ·  5 de 20   ← el que menos ligas deja mal
    0,09 óptimo     ECE 0,0109 ·  6 de 20

**No se cambia nada**: lo desplegado desde la v166 ya era la respuesta. Y **no
se construyó el modelo de goles enriquecido**, por tres razones medidas: el
xG/posesión de football-data son sintéticos (§NO HACER), el peso óptimo del
modelo es 0,09 —aporta el 9 % de la mezcla— y el propio encargo decía que si no
mejora se use sólo el encogimiento.

**Quedan 5 ligas por encima de 0,05**: sco_premiership 0,078, sco_championship
0,063, turquía 0,062, bundesliga 0,052, eredivisie 0,051. Sin encoger no bajaba
ninguna de las 20.

**4. La eficacia, liquidada contra el marcador** (`_v169_goles_y_eficacia.py`,
47.794 partidos):

    política  apuestas    de      acierto   anunciado    ROI      p5
    v164        47.794  47.794     56,0 %     65,2 %   −4,96 %  −6,16 %
    v169        14.665  47.794     62,3 %     61,7 %   −4,21 %  −5,35 %

La política vieja prometía 65,2 % y acertaba 56,0 % — nueve puntos de mentira
sobre 47.794 apuestas. La de hoy promete 61,7 % y acierta 62,3 %. **El ROI sigue
negativo**: esto calibra, no promete dinero.

Limitación del backtest: sólo 1X2, goles y BTTS, que son los que los ledgers
guardan con probabilidad del modelo. Córners, tarjetas y remates no se pueden
reconstruir hacia atrás.

**Validación.** Suite 2.307 checks TODO OK · `valida_render.py` 3 vistas OK ·
smoke completo (se pidió por tocar interfaz y extracción).

**Pendiente que deja:**

1. Las 5 ligas con ECE > 0,05 en goles tras encoger. La vía no es un modelo
   nuevo: es más cobertura de cuota en esas ligas, o un peso por liga en vez
   del global.
2. Las líneas por equipo sólo aparecen en 1 de cada 9 partidos. Merece medir si
   es la casa o el emparejador.
3. El backtest de eficacia no cubre córners/tarjetas/remates. Para cubrirlos
   habría que generar un ledger walk-forward de esos mercados, que hoy no
   existe.
4. `_v169_goles_y_eficacia.py` se corre a mano. Si la política de recomendación
   cambia, hay que volver a correrlo o sus cifras mienten.

## 5a. v170 — LA MÁS SEGURA, NO LA MEJOR PAGADA

Detalle en **BITACORA_ARQUITECTURA.md §20**. Va en el mismo commit que la v169.

**El cambio de filosofía (decisión del usuario).** La recomendación ya no la
elige la ventaja de precio: la elige la mayor probabilidad ajustada entre los
mercados ESTABLES de esa liga. El precio pasa a insignia «💰 Valor» (>10 %).

**El verde cambia de significado**: ya no dice «ventaja de precio medida» sino
«mercado estable y ≥60 %». La tarjeta no promete ventaja de precio en ninguna
parte. Es un cambio del contrato de §0 y está anotado.

**El intercambio, medido sobre 47.794 partidos, mismo catálogo:**

    política  apuestas    de      acierto   anunciado    ROI      p5
    v164        47.794  47.794     74,5 %     78,9 %   −8,42 %  −12,25 %
    v169        44.421  47.794     75,2 %     77,0 %   −5,00 %   −7,47 %
    v170        44.557  47.794     76,0 %     78,0 %   −6,17 %  −12,61 %

La v170 acierta más que ninguna y anuncia con holgura; paga con ROI peor que
mirar el precio. **Ninguna gana dinero.**

**La doble oportunidad entra al catálogo** (`modo_modelo.doble_oportunidad`).
Sale del 1X2 ya encogido, así que viaja con `ya_encogido=True`. Consecuencia
medida: 33 de 40 recomendaciones salen de ella y la app propone algo en el 93 %
de los partidos (17 de 40 antes de añadirla). Si molesta la monotonía, el mando
es subir el umbral del verde o sacar la doble del catálogo.

**La α por liga se probó y NO se adopta.** Fuera de muestra mejora en 13 de 20
(p≈0,13, no significativo) y las α ajustadas son inestables (0,00 a 0,60 sobre
400-1.500 partidos). Misma trampa que la v80. Se mantiene el 0,25 global y
`alfa_goles_por_liga.json` no se genera.

**Validación.** Suite 2.329 checks TODO OK · `valida_render.py` 3 vistas OK ·
`_v164_valida_tarjeta.py` OK · `_v163_valida_ficha_remates.py` OK.

**Pendiente que deja:**

1. La monotonía de la doble oportunidad (93 % de los partidos). Decidir si se
   quiere y con qué umbral.
2. ~~El smoke muere con `RecursionError`~~ — **DESCARTADO en la v171.** El
   proceso terminó con **exit 0**; el `RecursionError` que se vio era ruido de
   `streamlit.testing` al cerrar un proceso MATADO por tiempo de espera, no un
   fallo de la prueba. Los `st.expander` de la v167 no son el problema. Queda
   escrito porque la conclusión equivocada ya estaba anotada como defecto.
3. El backtest de eficacia sólo cubre 1X2, doble oportunidad, goles y BTTS —los
   que los ledgers guardan—. Córners, tarjetas y remates no se pueden
   reconstruir hacia atrás sin un ledger walk-forward propio.
4. Las cinco ligas con ECE de goles > 0,05 siguen ahí (§19.4).

## 5b. v171 — EL SCORE: PROBABILIDAD × CUOTA, LÍNEA A LÍNEA

Detalle en **BITACORA_ARQUITECTURA.md §21**.

**El cambio.** La recomendación se elige por `Score = probabilidad ajustada ×
cuota de Playdoit`, no por probabilidad absoluta. La v170 recomendaba doble
oportunidad al 79 % con cuota 1,10 en el 93 % de los partidos.

**Módulo nuevo: `valor_apuesta.py`.** Recorre TODAS las líneas que la casa
publica de cada mercado y devuelve la de mejor Score. Constantes: `PROB_MINIMA`
0,60 · `SCORE_EXCEPCION` 1,15 · `PROB_SUELO_DURO` 0,50 · `SCORE_VERDE` 1,10 ·
`SCORE_AMBAR` 0,95 · `CUOTA_MINIMA_DOBLE` 1,30.

**`mercado_dia.json` cambia de formato.** Cada línea pasa de `float` a
`{'p', 'mas', 'menos'}` y se añaden `1x2_cuotas`, `btts_cuotas`,
`doble_cuotas`. `mercado_implicito.prob_de()` y `cuota_de()` leen los dos
formatos — el fichero se regenera cada noche y durante unas horas conviven.

**`alpha_finder.lineas_de_goles` pasa de 3 líneas a 7** (0,5 a 6,5): una línea
que el modelo no calcula no se puede proponer aunque sea la de mejor valor.

**Qué publica Playdoit** (`_v171_catalogo_playdoit.py`, 22 tableros): goles y
córners 22/22 con línea · tarjetas 15/22 · remates y a puerta **3/22**. Es
decir, el Mercado Rey «Remates a puerta» de siete competiciones casi nunca tiene
precio con el que jugarse.

**Dos guardas descubiertas probando:**

1. La excepción del Score 1,15 exige suelo duro del 50 % **y** contraste con la
   casa. Sin ella se eligió «Real Sociedad o empate» al 38 % con cuota 3,10.
2. `mejor()` nunca devuelve un 🔴 (Score < 0,95). Sin la guarda salían
   recomendaciones con Score 0,872.

**Medido sobre los 117 pronósticos del día:** 23 con recomendación por Score
(7 🟢 · 16 🟡 · 0 🔴), Score mediana 1,033, máximo 1,270. Sin cuotas de la casa
se cae a la vía de la v170.

**El verde cambia de significado por tercera vez en cuatro versiones**: v168
«ventaja de precio medida» → v170 «estable y ≥60 %» → v171 «Score > 1,10».
Conviene no volver a moverlo sin motivo.

**Validación.** Suite 2.378 checks TODO OK · `valida_render.py` 3 vistas OK ·
`_v164_valida_tarjeta.py` OK · `_v163_valida_ficha_remates.py` OK.

**Pendiente que deja:**

1. La cobertura de cuotas manda sobre todo: sólo 23 de 117 partidos tienen
   recomendación por Score. Subirla es emparejamiento, no umbrales.
2. ~~El backtest no cubre la política del Score~~ — **HECHO.** Medido sobre
   los mismos 47.794 partidos: **2.947 apuestas · acierto 66,0 % · anunciado
   65,2 % · ROI −0,67 % · p5 −2,81 %**. Un orden de magnitud mejor que las
   otras tres políticas, apostando en el 6,2 % de los partidos. SIGUE SIENDO
   NEGATIVO: se acerca al equilibrio, no demuestra ventaja. Sólo evalúa goles
   2,5 y 1X2 —los únicos con cuota en el ledger—, así que mide la REGLA, no
   todo el catálogo. Detalle en BITACORA §21.9.
3. Remates y remates a puerta casi no tienen precio (3/22). Merece decidir si
   se siguen enseñando como Mercado Rey cuando no se pueden jugar.
4. ~~El smoke sigue sin veredicto~~ — descartado: ver 5a, pendiente 2. El
   smoke termina con exit 0; lo que se vio era ruido de cierre de un proceso
   matado por tiempo de espera.

## 5c. v172 — CONTEXTO H2H Y REGLAS ANTI-TRAMPA

Detalle en **BITACORA_ARQUITECTURA.md §22**.

**El caso.** «AmaZulu o empate» con Score 1,35, contra un Mamelodi que ganó 8 de
los últimos 10 cruces.

**La causa NO era el H2H.** La casa daba Mamelodi 78,85 % · empate 14,72 % ·
AmaZulu 6,43 %, o sea «AmaZulu o empate» = 21,15 % y Score real 0,63. La doble
oportunidad era **el único mercado que entraba sin contraste**
(`implicita=None`). Arreglado: su implícita se **suma del 1X2 devigado** —no se
deviga la familia de dobles, cuyas tres selecciones suman 2 y no 1—. Con
contraste, el desvío es de 24 pp y la bloquea la regla de los 10 pp.

**Un fallo hermano encontrado por el camino:** `valor_apuesta` daba el 1X2 por
ya encogido siempre, pero `alpha_finder` sólo lo encoge cuando hubo ancla. Ahora
lee `calibracion.aplicado` del pick. En el caso real, Mamelodi pasa de 0,550 a
0,729.

**Módulo nuevo: `contexto_partido.py`** — H2H (10 cruces, contados desde el
local de HOY), forma (5 partidos con puntos/partido) y diferencia de ELO.
Constantes: `N_H2H` 10 · `MIN_H2H` 4 · `DOMINIO_CLARO` 0,65 · `FACTOR_MINIMO`
0,40 · `FACTOR_MAXIMO` 1,30.

**Cómo se usa el factor** (importante, no cambiarlo sin leer §22.4):

* **modula** la probabilidad sólo donde NO hay implícita — donde hay precio, la
  casa ya conoce el H2H y multiplicar sería contarlo dos veces y descalibrar;
* **veta** lo que contradice un H2H dominante, con precio o sin él. Un veto es
  un filtro: no cambia ningún número;
* **se enseña siempre** en el bloque 📊 CONTEXTO.

**Reglas anti-trampa** (`valor_apuesta`): `PROB_TRAMPA` 0,20 y `CUOTA_TRAMPA`
2,50 — probabilidad baja con cuota alta no se recomienda nunca. En el caso real
«Gana AmaZulu» quedaba en 9,8 % con cuota 11,00 y **Score 1,08, el más alto del
partido**.

**La tarjeta** enseña el bloque de contexto antes de la recomendación, y cuando
no hay nada recomendable dice por qué («Mamelodi ha ganado 8 de los últimos 10
cruces»).

**En ese partido la respuesta honesta es que no hay apuesta:** Mamelodi encogido
queda en Score 0,897 y el mínimo es 0,95. El encargo esperaba ámbar, pero eso
exigiría bajar el umbral de valor para que dé la respuesta que se quiere oír.

**Validación.** Suite 2.409 checks TODO OK · `valida_render.py` 3 vistas OK ·
`_v164_valida_tarjeta.py` OK · `_v163_valida_ficha_remates.py` OK.

**Pendiente que deja:**

1. El factor de contexto NO está medido contra el histórico: no se sabe si
   modular sin precio mejora o empeora el ECE. Se puede medir con el ledger,
   restringiendo a partidos sin cuota.
2. El ELO sale de `elo_actual.csv` y en la prueba real dio `None` para esos dos
   equipos — el emparejamiento de nombres con ese fichero no está comprobado.
3. El veto usa contención de cadena para saber si la apuesta nombra a un
   equipo. Con nombres cortos puede fallar, igual que pasó en la v169 con las
   familias de Playdoit. Convendría la misma regla de palabras enteras.

## 5d. v173 — SIEMPRE HAY APUESTA

Detalle en **BITACORA_ARQUITECTURA.md §23**.

**El cambio.** La recomendación se elige por **probabilidad ajustada** (a
igualdad, mejor cuota) y existe SIEMPRE. Se retiran el suelo de Score, el de
probabilidad y la regla anti-trampa.

**Lo que cuesta, medido sobre 47.794 partidos:**

    por Score          2.947 apuestas · acierto 66,0 % · ROI −0,67 %
    por probabilidad  44.557 apuestas · acierto 76,0 % · ROI −6,17 %

Cinco puntos y medio de ROI a cambio de jugar todos los días. Está escrito en
el docstring de `valor_apuesta.mejor` para que no se pierda.

**Lo que NO se quitó:** el ajuste de la probabilidad. Una línea que se separa
más de 10 pp del precio sigue viniendo encogida y recortada — se quita el
BLOQUEO, no la corrección. Por eso «AmaZulu o empate» puede volver a la lista y
no gana: entra con 0,27, no con 0,45. **La v172 es lo que hace segura a la
v173.**

**Tres arreglos para que «siempre» fuera cierto** (medidos, no supuestos):

1. Las líneas sin cuota se descartaban (`score is not None`). Ahora entran.
2. La cuarentena vaciaba ligas enteras sin medir — 26 partidos de 117. Ahora
   aparta si queda algo y se hace a un lado si no queda nada.
3. Un `return None` heredado de la v167 cortaba ANTES del motor de valor — 22
   partidos de 113. El motor va primero.

Resultado: **113 de 113 con recomendación**, 96 en verde.

**«Cuota decente»** (`CUOTA_DECENTE` 1,20 · `PROB_MAXIMA_RECO` 0,90): sin estos
cortes, 53 de 113 recomendaciones eran «Menos de 6,5 al 100 %» con cuota 1,01.
Si no queda ninguna digna, se propone la mejor que haya.

**`contexto_partido.factor_lambda`**: compara la media reciente del equipo con
la SUYA larga (no con la de la liga), recortado a [0,80 · 1,20]. Se aplica a la
λ de córners, tarjetas y remates.

**El verde, por cuarta vez**: v168 ventaja de precio → v170 estable y ≥60 % →
v171 Score > 1,10 → **v173 probabilidad ≥ 60 %**. No moverlo más sin motivo.

**Validación.** Suite 2.429 checks TODO OK · `valida_render.py` 3 vistas OK ·
`_v164_valida_tarjeta.py` OK · `_v163_valida_ficha_remates.py` OK.

**Pendiente que deja:**

1. La política de la v173 NO se ha vuelto a liquidar contra el marcador. Las
   cifras de arriba son las de la v170, que es la misma regla de selección pero
   sin la escalera de líneas ni el factor de λ. Añadir `_politica_v173` a
   `_v169_goles_y_eficacia.py` antes de citar eficacia.
2. El factor de λ no está medido: no se sabe si mejora o empeora el ECE de
   córners y tarjetas. Se puede medir con `informe_calibracion`.
3. El smoke quedó sin veredicto otra vez (se colgó 3 h en la fase de red y se
   paró a mano). El de la v169 sí terminó con exit 0.

## 5e. v174 — EL HISTÓRICO ES EL MOTOR, EL TABLERO ES EL FILTRO

Detalle en **BITACORA_ARQUITECTURA.md §24**.

**El defecto que arregla, y lo introdujo la v173.** Para cumplir «siempre hay
apuesta», la v173 recorría las líneas DEL MODELO en vez de las de la casa:
**218 de 773 candidatas de goles eran fantasma (28 %)**. Rapid Vienna–Hearts
tenía sólo 2,5 en Playdoit y la app ofrecía 0,5 · 1,5 · 3,5 · 4,5 · 5,5 · 6,5.

**La regla, ahora escrita en el módulo y en un test:** el histórico dice cuántos
goles esperar; el tablero dice qué se puede jugar. **Toda candidata tiene precio
real.** Fantasmas: 0.

**Lo que cuesta:** 3 partidos de 113 se quedan sin recomendación desde
`valor_apuesta` (los que no tienen tablero). Los otros 110 la conservan — 86 con
cuota real y 24 por el camino heredado de `modo_modelo`, que usa los mercados
estándar del barrido. Retroceso pequeño frente al 113/113 de la v173, y el
precio correcto.

**El H2H entra en la λ** (`factor_lambda(..., rival=...)`), con **la mitad de
peso que la forma reciente** y sólo con `MIN_H2H` cruces. Medido:

    Mamelodi, sólo forma ....  1,200 (techo)
    Mamelodi, con H2H .......  1,069
    goles medios del cruce ..  1,7

**El bloque de contexto** enseña ahora la media de goles del H2H además del
recuento y las dos rachas con puntos y goles por partido.

**Validación.** Suite 2.446 checks TODO OK · `valida_render.py` 3 vistas OK ·
`_v164_valida_tarjeta.py` OK · `_v163_valida_ficha_remates.py` OK.

**Pendiente que deja:**

1. Ni la política de la v173 ni la de la v174 se han liquidado contra el
   marcador. Las cifras de eficacia que hay son de la v170/v171. Añadir
   `_politica_v174` a `_v169_goles_y_eficacia.py` antes de citar números.
2. El factor de λ (forma + H2H) no está medido contra el ECE: no se sabe si
   mejora o empeora la calibración de córners y tarjetas. Es medible con
   `informe_calibracion`.
3. Los 24 partidos que se recomiendan por el camino heredado llevan mercados
   sin cuota. No son líneas fantasma —son las estándar del barrido— pero
   convendría marcarlos en la tarjeta como «sin precio de la casa».

## 5f. v175 — SIN BLOQUEOS, MÁXIMO SCORE, Y LA λ QUE ESCUCHA AL HISTÓRICO

Detalle en **BITACORA_ARQUITECTURA.md §25**.

**El caso que lo provoca: la tarjeta de Toluca – Austin.** Dos defectos:

1. 1X2, BTTS, Córners, Tarjetas y Remates salían con `🔒 No recomendado`.
   Cinco mercados que Playdoit cotiza y ninguno con nada que jugar.
2. **La tarjeta se contradecía**: recomendaba Score 0,95 y tres líneas más
   abajo, en «💰 MEJOR VALOR», enseñaba Score 0,98. Dos secciones ordenadas por
   criterios distintos (v173 por probabilidad, v171 por Score).

### Lo que cambia

**`🔒 No recomendado` desaparece del proyecto.** En su lugar `⚠️ Alta
incertidumbre` en gris. Un mercado en cuarentena, o sin insignia de confianza,
**propone igual**; lo único que sigue sin enseñarse es el mercado que Playdoit
no cotiza. Un mercado marcado no puede ir en verde.

**La recomendación es la de máximo Score** entre las que cumplen prob ≥ 50 % y
cuota ≥ 1,20 (y ≤ 90 %). Si ninguna cumple, la de mejor Score con aviso «Baja
probabilidad». La sección «MEJOR VALOR» se retira: en su sitio, «📊 Otras
opciones de valor», que son **las siguientes de la misma lista** y por eso ya no
pueden contradecir a la principal.

**Los mínimos se aplican en los tres sitios** (`mejor`, `por_mercado`,
`_otras_opciones`). Sin eso, la primera prueba contra un tablero real puso
«Gana AmaZulu» al 10 % —Score 1,08 por cuota 11,00— como recomendación del 1X2
y como primera alternativa. Es la trampa de la v172 por la puerta de al lado.

**El verde, por quinta vez:** prob ≥ 60 % **Y** Score ≥ 0,97 **y** sin aviso.
Un 70 % a cuota 1,05 (Score 0,735) ya no va en verde. El ámbar no lo levanta el
Score solo: un 30 % a cuota 4,00 da 1,20 y sigue siendo un volado.

### Parte 3: dos hipótesis, una entró

**Binomial negativa para los goles — NO entró, y está medido.** La
sobredispersión es real (`_v175_goles_binomial_negativa.py`, 47.794 partidos):
**φ de Pearson = 1,179 global, 53 de 55 competiciones por encima de 1,02**. Pero
sobre la cifra que se PUBLICA —encogida hacia el precio con w=0,25— empeora:

    matriz (producción)  ECE 0,0097  ·  binomial negativa  0,0117  (−21 %)

Cuatro cortes de dispersión probados, los cuatro empeoran. En crudo mejora la
cola (2,5 +4,9 % · 3,5 +7,3 %) y empeora el centro (1,5 −1,1 %), pero el
encogimiento diluye el cambio cuatro veces. Hay test para que no se reproponga.

**Sí entró el techo de alta varianza** que usa el mismo diagnóstico: liga de más
de 3,0 goles ⇒ las líneas centrales (±0,5 de la media) topan en 60 % el «Menos»
y 75 % el «Más». Es techo de presentación: sólo baja.

**El H2H en la λ de goles — SÍ entró, y es el pendiente nº 2 cerrado.**
Regresión sobre el residuo con el H2H previo a cada fecha
(`_v175_h2h_en_la_lambda.py`, 47.794 partidos):

    señal      n        β        error est.   t
    h2h      31.473   0,3401      0,0097     35,1
    forma    47.781   0,3768      0,0082     45,7
    juntas             0,186 y 0,255        ← los que se usan

    ECE cruda, 3 líneas ....  0,0795 → 0,0460   (−42 %)
    ECE PUBLICADA, 2,5 .....  0,0111 → 0,0083   (−25 %)
    sin precio de la casa ..  0,0891 → 0,0496   (−44 %)

Medido con la MISMA ventana que aplica el código (10 cruces · 5 partidos). La
primera pasada usó todos los cruces previos y daba 0,204/0,244; se rehízo.

El agujero estaba en que `factor_lambda(..., rival=...)` de la v174 sólo lo
llamaban córners, tarjetas y remates: la escalera de **goles** salía de sumar la
matriz y el historial no la tocaba. Ahora `alpha_finder.lineas_de_goles` recibe
liga y equipos. Se recalcula con Poisson sobre la λ corregida porque el marginal
de la matriz **es** Poisson(λ_h+λ_a) hasta el cuarto decimal; sin señal, ese
camino ni se toma.

### Eficacia, liquidada — pendiente nº 1 cerrado

`_v169_goles_y_eficacia.py`, 47.794 partidos:

    política  apuestas    de      acierto  anunciado   ROI %    p5 %
    v164        47.794   47.794    74,5 %    78,9 %    −8,42   −12,25
    v169        44.421   47.794    75,2 %    77,0 %    −5,00    −7,47
    v170        44.557   47.794    76,0 %    78,0 %    −6,17   −12,61
    v171         2.947   47.794    66,0 %    65,2 %    −0,67    −2,81
    v174        35.954   47.794    52,7 %    52,5 %    −4,72    −5,57
    v175        21.837   47.794    58,3 %    58,2 %    −4,64    −5,62

La v175 mejora a la v174 poco en ROI y mucho en acierto, y las dos anuncian lo
que pasa (0,1-0,2 puntos de distancia). **Ninguna gana dinero.** La v171 sigue
siendo la mejor por ROI y cubría el 6 % de los partidos: levantar la cuarentena
y el suelo de Score cuesta cuatro puntos de ROI y multiplica por siete la
cobertura. Es el intercambio que se pidió.

**Limitación:** el ledger sólo tiene cuota de goles 2,5 y del 1X2. La tabla mide
**la regla**, no todo el catálogo.

**Rendimiento.** El techo del encargo era 0,5 s en el barrido. La primera
versión costaba 19,4 ms/partido (2,9 s en 150). Con un índice de goles por
competición y la Poisson vectorizada: **0,11 ms/partido, 17 ms en 150.**

**Pendiente que deja:**

1. Las líneas de la cola (3,5 · 4,5 · 5,5) no se pueden medir ya encogidas:
   nadie guardó su cuota en el ledger. Es donde la binomial negativa más
   cambiaría, así que el «no entró» está medido sólo en 2,5.
2. La corrección de λ por H2H y forma se aplica a los GOLES. Los conteos
   (córners, tarjetas, remates) siguen con el `factor_lambda` multiplicativo de
   la v173/v174, que sigue sin medir contra el ECE.
3. Sigue sin resolverse: `cuotas_multi._buscar` empareja partidos distintos del
   mismo día (Botafogo ↔ Botafogo SP), tapado sólo en `alpha_finder`.
4. 12 ligas sin córners observados; `champions` tiene 774 filas con córners
   reales sin inyectar en su histórico.
5. HMREY debe rotar la clave de The Odds API.

## 5g. v176 — LO QUE LA APLICACIÓN DIJO, Y SI ACERTÓ

Detalle en **BITACORA_ARQUITECTURA.md §26**.

### Módulos nuevos

| | |
|---|---|
| `pronosticos_guardados.py` | el registro inmutable de lo recomendado + su liquidación contra el marcador. Tiene CLI: `python pronosticos_guardados.py` |
| `patrones_equipo.py` | patrones observados de los últimos 5 partidos (4 de 5 mínimo) |
| `preferencias_usuario.py` | los filtros de la pantalla, entre sesiones |

### 1. Pronóstico previo en finalizados, con validación

**No va en `predicciones_dia.json`, aunque el encargo lo pidiera ahí**: ese
fichero lo REGENERA el bot entero cada noche, así que una copia «inmutable»
guardada ahí se borraría en la primera pasada. Va en
`pronosticos_emitidos.json`, de **sólo inserción** y podado a 21 días **por
fecha de anotación** (los registros del bot no traen fecha del partido; podando
por ella no se borrarían nunca).

**Lo escriben los dos, y hace falta que sean los dos:**

- la **aplicación**, al pintar la tarjeta (con córners, tarjetas y remates
  dentro, que es la versión buena) y con un barrido posterior para los que un
  filtro apartó;
- el **bot**, en `retrain_leagues.yml`, justo después de `monitor_playdoit.py`.
  Sin este paso el registro no sobreviviría al reinicio del contenedor de
  Streamlit Cloud. Medido: **298 evaluados · 96 anotados · 48 s**. Los otros
  202 son partidos que Playdoit no cotiza.

**Colores:** 🟢 acertó · 🔴 falló · 🟡 acertó con prob < 50 % **o** falló por
menos de una unidad de la línea. Y «sin pronóstico previo» ≠ «falló»: sale esa
frase, no una fila roja.

**Los conteos salen de `stats_espn.leer`** —la caché en disco del backfill
nocturno—, cero red desde la tarjeta. Un partido recién acabado sale
⏳ Pendiente en esos mercados en vez de con un veredicto inventado.

### 2. Mañana, con el detalle entero

`con_apuesta` ya sólo decide la ETIQUETA (`📅 Análisis previo (no jugable aún)`).
Contexto, recomendadas, mercados y estabilidad se pintan igual que en hoy. Y la
casilla de «sólo alta probabilidad» se enciende también allí.

### 3. Tres recomendadas, una por mercado

`valor_apuesta.mejores` filtra por los mínimos (prob ≥ 50 %, cuota ≥ 1,20,
≤ 90 %) y ordena por Score; `apuesta_recomendada` devuelve su primera fila. Una
sola definición del orden. **Una por mercado**: sin eso la escalera de goles se
lleva las tres plazas con apuestas correlacionadas al 90 %. No se rellena a la
fuerza. La sección «Otras opciones de valor» de la v175 se retira.

### 4. Filtros, y qué estaba roto de verdad

| | estado real |
|---|---|
| Deporte entre pestañas | **ya persistía** (clave global en `dashboard_ui`) |
| Orden entre pestañas | **roto** → una sola `CLAVE_ORDEN` |
| Cualquiera entre sesiones | **roto** → `preferencias_usuario.json` (gitignorado) |

`leer_opcion` descarta la preferencia huérfana: sin esa guarda, renombrar un
criterio de orden reventaría la pantalla entera al arrancar.

### 5. Orden «Apuesta recomendada»

verde → ámbar por Score → sin apuesta. El verde manda sobre el Score: ordenar
sólo por Score haría un ranking de lo peor medido (v164).

### 6. Autoaprendizaje

**La parte 4.1 YA EXISTÍA y se comprobó antes de tocar nada.**
`retrain_leagues.yml` corre cada noche: añade los partidos al histórico,
recalcula ELO y medias móviles, reentrena. Los commits `chore(datos): …` son
diarios. No se reimplementó.

**Los patrones (4.2) son nuevos**, con **4 de 5** y no 3 de 5: tres de cinco
pasa el 50 % de las veces por azar y no es un patrón. Van en CONTEXTO y **no
tocan ninguna probabilidad** — la λ ya escucha al histórico desde la v175 con un
peso medido (β 0,186 / 0,255).

### Rendimiento

    índice de patrones por liga ....  10 ms  (una vez)
    patrones por partido ...........  0,014 ms
    anotar el pronóstico ...........  consulta a un diccionario

**Nota operativa que costó una hora de diagnóstico.** El paso nuevo del bot
llama a `remates_tarjeta` para 298 partidos, y ése necesita los ROSTERS de
ESPN. Corriéndolo en local, ESPN empieza a rechazar peticiones a mitad de la
pasada y `goleadores_cache.json` **guarda los fallos** —lo hace a propósito, hay
un test que lo comprueba—, así que durante un rato la aplicación se queda sin el
bloque de «Quién remata». Se vio como un `_v164_valida_tarjeta` en rojo con «0
jugadores llevan la línea de la casa», y se descartó que fuera una regresión
comparando contra HEAD **en un worktree aparte**: HEAD fallaba igual con esa
caché envenenada y volvía a pasar al restaurarla.

En CI no ocurre: `precalcular_rosters.yml` corre a las 04:30 y deja la caché
caliente una hora antes de `retrain_leagues.yml`. **En local, conviene restaurar
`goleadores_cache.json` desde git después de correr `pronosticos_guardados.py` a
mano.**

**Pendiente que deja:**

1. La validación de córners, tarjetas y remates depende de que el backfill
   nocturno de `stats_espn` haya pasado. Los partidos del propio día salen
   ⏳ Pendiente hasta la mañana siguiente.
2. `predicciones_dia.json` no guarda la fecha del partido, así que los registros
   del bot van sin ella y la búsqueda cae en la pasada tolerante (mismo par, sin
   mirar fecha). Dos cruces del mismo par en 21 días podrían confundirse; se
   acota eligiendo el de fecha más cercana. Lo limpio sería que
   `predicciones_dia.generar` guardara la fecha.
3. Los patrones no están medidos contra nada: son un recuento honesto, pero
   nadie ha comprobado que un equipo con «Over 9,5 en 4 de 5» repita más que el
   resto. Es medible con el ledger y no se ha hecho.
4. Sigue sin resolverse: `cuotas_multi._buscar` empareja partidos distintos del
   mismo día (Botafogo ↔ Botafogo SP), tapado sólo en `alpha_finder`.
5. `smoke_botones.py` volvió a colgarse en la fase de red sin veredicto, como en
   la v173 y la v174.
6. HMREY debe rotar la clave de The Odds API.

## 5h. v177 — CUATRO FALLOS, Y EL QUE NO LO ERA

Detalle en **BITACORA_ARQUITECTURA.md §27**.

### 1. «Sin pronóstico previo» — TRES vías, no una

La v176 sólo leía el REGISTRO, y el registro sólo existe si alguien vio el
partido antes de que se jugara. Y había un segundo agujero: `partidos_jugados`
cambiaba los nombres del fixture por los del catálogo del modelo y con eso
**perdía la llave** de `predicciones_dia.json` y `mercado_dia.json` (se indexan
por el nombre crudo de ESPN, v165). Ahora viaja en `_home_crudo`/`_away_crudo`.

| vía | fuente | qué enseña |
|---|---|---|
| guardado | `pronosticos_emitidos.json` | la recomendación tal cual se anunció |
| precálculo | `predicciones_dia` + `mercado_dia` | la misma, del estado de esa mañana |
| modelo | matriz de marcador | goles, BTTS, 1X2 · **sin cuota ni Score** |

La tercera cierra el caso del usuario: Playdoit casi no cotiza la Superliga
china, así que por las dos primeras esos partidos seguirían vacíos. Medido:
**25 de 25 partidos del precálculo recuperan su pronóstico.**

### 2. Visual: la validación se mira

    1 – 3   🟢🟢🔴                       2 de 3 · sin precio de la casa
    🟢 Goles: Más de 2.5    ▓▓▓▓▓▓░░░░   62 %        4
    🔴 Gana Qingdao Hainiu  ▓▓▓░░░░░░░   39 %   visita

La barra es cuánto se mojó el modelo. Roja y llena = error grave; roja y corta =
dudó y acertó al dudar.

### 3. Botón de Playdoit: retirado. `URL_PLAYDOIT` se conserva.

### 4. Filtros: la causa NO era el filtro

**`st.tabs` no tiene estado de servidor.** La pestaña vive en el navegador y
cualquier interacción la devuelve a la primera. La v176 arreglaba la mitad
correcta del problema equivocado. Ahora `st.segmented_control` con clave, y:

- **las opciones son claves, no rótulos** — el rótulo lleva el contador dentro
  («Hoy (247)») y mañana dejaría de ser una opción válida;
- **las vistas no elegidas se descartan al final del render** (`_slot.empty()`),
  no se envuelven en un `if`: el cuerpo de «hoy» está repartido en seis sitios
  de `render_alpha_finder`.

Consecuencia: los widgets de la vista oculta ya no llegan vivos al cierre, así
que su `session_state` se recoge. Lo que conserva la elección es
`preferencias_usuario`, en disco. `valida_render` prueba ahora **la vista de
mañana**, que no ejercitaba nadie.

### 5. Goles: diagnóstico bueno, remedio distinto

Medido (`_v177_sesgo_goles_por_liga.py`, 47.794 partidos): el modelo encoge
hacia la media global.

    sesgo (goles reales − λ)     nivel <2,4  −0,180   ·  nivel >3,0  +0,213

×1,05 sólo en las ligas altas baja el ECE un 2 %: arregla media curva. Entra un
**desplazamiento** simétrico, `λ + 0,35·(media_liga − 2,61)`, que deja el sesgo
en ±0,04 en los dos extremos y NO comprime la dispersión entre partidos.

**Hallazgo incómodo, medido y NO desplegado:** encoger hacia la media de liga
(`λ + g·(nivel − λ)`) tiene su óptimo por Brier y log-loss en **g ≈ 0,8**. O sea
que la λ de goles apenas discrimina entre partidos de la misma liga. Los tres
indicadores mejoran a la vez, así que no es el aplanamiento de siempre. Pero
desplegarlo dejaría los diez partidos de la jornada con la misma probabilidad —
lo mismo que hace a los córners no recomendables (§10). Merece su propia
versión, no colarse en un arreglo de interfaz.

### Lo que NO entró, con el criterio del propio encargo

- **w=0,30**: la regla era condicional a «ECE > 0,08». El ECE publicado es
  **0,0083**, así que no se dispara. Medido igualmente: w=0,30 da 0,0086 contra
  0,0083. Peor.
- **Techo del 50 % en ligas de >3,0 goles**: ya se cumplía desde la v165. El
  65 % es el techo de las ligas de 2,5 a 3,0, no de las de 3,2. Hay test.

### v177.2 — ocultar no es borrar

El selector de vista de la v177 escondía las vistas no elegidas **vaciando** su
`st.empty()` al final del render. Pinta bien y rompe el estado: un widget que no
llega vivo al final de la pasada desaparece de `st.session_state`. En la
aplicación real, estando en «Mañana» o «Estado», pulsar «🔄 Actualizar ahora»
tiraba la página con `KeyError: parlay_base` — el `selectbox` de la combinada,
que vive en la vista de hoy.

Con `st.tabs` no pasaba porque renderiza las cuatro pestañas y todas quedan en
el árbol. El arreglo devuelve esa propiedad: contenedores con `key` y
`display:none` por CSS para las que no tocan.

**Lo cazó el smoke**, y sólo porque la v177.1 le devolvió la capacidad de abrir
las otras vistas y pulsar un botón estando en ellas. Ni la suite ni
`valida_render` podían verlo.

**Consecuencia para `valida_render`:** con las cuatro vistas en el árbol,
`AppTest` ve el texto de todas —no sabe nada de CSS—, así que su check de la
vista de mañana pasó a llamarse «se genera». La comprobación fuerte es la de
`session_state`. Detalle en **BITACORA §27.9**.

**Pendiente que deja:**

1. **El g=0,8.** La medición dice que la λ de goles casi no discrimina dentro de
   una liga. O el motor de goles mejora, o hay que decidir a cara descubierta
   cuánto encoger. Es el pendiente más importante que deja esta versión.
2. La vía 2 (reconstruir del precálculo) sólo funciona **el mismo día**:
   `predicciones_dia.json` y `mercado_dia.json` se regeneran cada noche. Para
   partidos de días anteriores manda el registro guardado, que sí persiste.
3. `predicciones_dia.json` sigue sin guardar la fecha del partido.
4. Los patrones (v176) siguen sin medir contra el ledger.
5. `cuotas_multi._buscar` empareja partidos distintos del mismo día.
6. HMREY debe rotar la clave de The Odds API.

---

## 5i. v178 — LA VISTA QUE NO CAMBIABA, Y LOS DOS MINUTOS QUE NADIE MIRABA

Detalle en **BITACORA_ARQUITECTURA.md §28**.

El encargo fueron dos frases del usuario:

> «los partidos de mañana ya no me aparecen cuando aplico el filtro, no cambia
> nada, me mantiene los de hoy y no me permite analizar los de mañana»
>
> «cuando dejo de usar la app y quiero volver a usarla tarda muchísimo en
> cargar todo. ¿Hay forma de mudar a algo que igual sea gratis?»

Y resultaron ser **el mismo defecto por dos caras**.

### 1. La vista sí cambiaba; el navegador no se enteraba

Todo lo que la v177 comprobaba estaba bien: `_vista_principal` valía `manana`
en todas las pasadas, el cuerpo de mañana se generaba, `preferencias_usuario`
lo recordaba entre sesiones. Los dos checks que había —`session_state` y «el
texto se genera»— pasaban en verde con la pantalla enseñando lo que no era.

Lo que estaba roto era **el orden de lo que se manda al navegador**. Streamlit
sustituye los elementos por su posición y a medida que llegan, así que la hoja
de estilo que esconde las vistas —emitida al final de `render_alpha_finder`—
llegaba la última. Hasta entonces seguía aplicada **la del render anterior**.

Medido en el navegador, contra la aplicación real:

| | v177.2.1 | v178 |
|---|---|---|
| pulsar una pestaña y que la pantalla obedezca | **nunca en 153 s** | **1,7 s** |

Ciento cincuenta y tres segundos con la vista equivocada delante. Con eso,
«no cambia nada, me mantiene los de hoy» es la descripción exacta.

**El arreglo son cuatro líneas movidas**: el `<style>` se emite justo después
de conocer la vista y antes de crear los contenedores. El motivo que tenía
escrito para ir al final —«el cuerpo de hoy se pinta en seis sitios
distintos»— era el motivo equivocado: eso obliga a que el CONTENEDOR se cree
antes que su contenido, no a que la hoja de estilo se emita después. El CSS es
global y se aplica a lo que llegue luego.

### 2. Los dos minutos: el 97 % se iba en pintar lo que estaba escondido

`_v178_perfil_pantalla.py` y `_v178_perfil_primera.py`, con el barrido ya
cacheado en disco y la revalidación en segundo plano neutralizada:

| | v177.2.1 | v178 |
|---|---|---|
| primera carga de «Apuestas del Día» | **213,2 s** | **39,1 s** |
| rerun al cambiar de vista | **60,4 s** | **14,7 s** |
| texto de la página | 155 KB | 27 KB |

De dónde salían, y qué se hizo con cada trozo:

| coste | qué era | arreglo |
|---|---|---|
| 67,3 s | `_render_combinadas_dia` cargaba cuatro motores de liga y pedía los remates por jugador a ESPN **para llenar un desplegable cerrado**, y lo hacía también estando en «Mañana» | va dentro de la vista de hoy y detrás de una casilla que se recuerda |
| 40,2 s | las tarjetas de las cuatro vistas se dibujaban siempre, incluidas las que están detrás de un `display:none` | `modo_modelo.render(pintar=False)` en la vista que no se mira |
| 14,7 s | `clv_historico` releía el CSV de apuestas en cada pasada | `st.cache_data(ttl=1800)` |

**Lo que NO cambia, y es la parte delicada:** los cuatro cuerpos de vista
siguen ejecutándose y sus CONTROLES se siguen creando. Es el invariante de
§27.9 —un widget que no llega vivo al final de la pasada desaparece de
`st.session_state` y tira la página con `KeyError: parlay_base`—. Lo que se
salta es sólo el bucle de tarjetas, que no crea estado que nadie lea.

### 3. Y el filtro que dejaba «Mañana» en cero sin decir por qué

Medido sobre el barrido del día:

    HOY     261 partidos · 222 con cuota · 28 con recomendada · 3 en VERDE
    MAÑANA   35 partidos ·  18 con cuota · 15 con recomendada · 0 en VERDE

«Sólo alta probabilidad» pide verde, y el verde exige probabilidad **y** que la
cuota publicada lo sostenga. Los partidos de mañana casi no tienen precio —las
casas abren línea durante la noche—, así que esa casilla deja la vista de
mañana vacía muchos días sin que haya nada roto. La pantalla decía «No hay
partidos que cumplan el filtro» y eso se lee como que la lista desapareció.
Ahora dice cuántos había y qué casilla se los llevó.

### Sobre mudar de plataforma

La pregunta era razonable y la respuesta la dan los números de arriba: **lo que
hacía lenta la aplicación era la propia pantalla, no el servidor.** Mudar a un
contenedor más rápido habría dado quizá un 2× sobre 213 s; recortar lo que se
pinta dio 5,5×, y el cambio de pestaña 90×.

Lo único que NO se arregla desde el código es el arranque en frío de Streamlit
Community Cloud: cuando la aplicación lleva horas sin visitas el contenedor se
apaga, y al volver **reinstala el entorno pip entero** (numpy, scipy,
scikit-learn, xgboost, lightgbm, ripser, matplotlib, plotly, pyarrow). Eso son
minutos y no depende de esta pantalla. La alternativa que se propuso aquí
—Hugging Face Spaces con Docker— **resultó no ser gratuita ya**: ver la §5k,
que trae la comparativa completa con los números de septiembre de 2026.

### 4. Y el smoke cazó una segunda vía del `KeyError: parlay_base`

Con todo lo demás en verde, el smoke rápido salió rojo pulsando «🔄 Actualizar
ahora» estando en «Estado» — el mismo error que la v177.2 dice haber cerrado.
Sobre `a8a49c3`, en un worktree, el smoke sale TODO OK: no venía de antes.

La causa que se encontró: el botón hacía `st.rerun()`, que **corta la pasada en
seco**, y está arriba de las cuatro vistas. Al cortar ahí no se registra ni uno
de los widgets de abajo, y un widget que no se registra deja de estar vivo. El
rerun no hacía falta: la bandera la consume la misma pasada en
`barrido_universal(forzar=...)`. Quitarlo deja el script llegando entero al
final **y** ahorra una pasada completa.

**Salvedad honesta, la misma que dejó la v177.2:** el `KeyError` no se pudo
reproducir a voluntad. Cuatro variantes de reproductor —Sección 1 inyectada,
Sección 1 que desaparece a mitad, recorrido completo de las cuatro vistas, y
pulsar el objeto botón capturado en la carga inicial como hace el smoke— y
ninguna lo levantó, ni aquí ni en `a8a49c3`. `parlay_base` sólo existe los días
que hay Sección 1, y el barrido se revalida solo: el propio smoke contó 503,
558 y 365 botones en tres pasadas del mismo día. Lo que se afirma es que el
smoke está verde y que esa vía está cerrada; no que fuera la única.

### Checks nuevos, y por qué los anteriores no podían fallar

- `test_la_vista_elegida_no_se_pierde` comprueba ahora **el ORDEN**: el
  `<style>` tiene que emitirse antes de `st.container(key='vista_%s')`. Si
  alguien lo devuelve al final, se pone rojo.
- y que las dos listas reciben `pintar=(_vista == ...)`.
- `valida_render` comprueba lo mismo sobre la pantalla real, y además que la
  vista escondida **no dibuja sus tarjetas** (sus botones «Ver ficha» no
  existen).
- y que el botón de refresco no vuelve a llamar a `st.rerun()` antes de que el
  barrido consuma su bandera.

Los cuatro se comprobaron en un worktree con el `dashboard_ui.py` de la
v177.2.1: los cuatro se ponen rojos.

Los dos que había miraban `session_state` y el texto generado, y los dos
estaban en verde mientras el usuario veía la pantalla equivocada. Es §27.9 otra
vez: un check que no puede fallar es peor que no tenerlo.

**Pendiente que deja:**

1. Todo lo de la v177 sigue vigente (g=0,8 el primero).
2. La primera carga son todavía **39 s**, y 28,8 de ellos son las 200 tarjetas
   de hoy. Bajarlo pide paginar la lista, que es decisión de producto.
3. `partidos_jugados.de_dia` cuesta 5,8 s en 61 peticiones a ESPN cada vez que
   se abre la vista de hoy.
4. Mudar de plataforma: comparado en la §5k. Hugging Face dejó de ser
   gratuito para lo que hace falta aquí, y ninguna alternativa gratis gana
   claramente. Sin hacer y sin urgencia.

---

## 5j. v178.9 — UNA FUENTE CAÍDA VACIÓ UN HISTÓRICO, Y NADIE SE ENTERÓ EN TRES DÍAS

Detalle en **BITACORA_ARQUITECTURA.md §29**. Salió tirando del hilo de los dos
fallos que la suite arrastraba, y resultaron ser **el mismo problema**.

    historico_leagues_cup.csv   2026-09-03  6.758 filas
                                2026-09-06    291 filas   (−95,7 %)

Ese histórico es agrupado a propósito: la competición sola tiene 290 partidos,
así que `leagues_cup.historico()` le junta MLS y Liga MX bajando
`/new/USA.csv` y `/new/MEX.csv` de football-data.co.uk. **Esas dos URL devuelven
503** (comprobado el 2026-09-09, y sigue así). Sin ellas la función devuelve
sólo la competición, y `entrenar_liga` lo escribía encima del bueno sin mirar.

El modelo se salvó de casualidad —`entrenar_liga` exige 300 partidos
utilizables y 291 no llegan, así que reventó antes de entrenar—; lo que quedó
roto tres días fueron el H2H, la forma, el ELO y el panel de equipos de esa
competición.

**Barrido sobre los 75 históricos** (`_v178_historicos_encogidos.py`): siete
encogieron y no hay nada en medio — seis entre 0,1 % y 0,4 % (la ventana móvil
de años, que es correcta) y uno el 95,7 %. Esa separación tan limpia es lo que
hace que un corte por porcentaje sea una guarda y no una lotería.

**Lo que entra:**

- `league_engine._guardar_historico` sustituye al `to_csv` pelado: si el nuevo
  tiene menos del 70 % de las filas del que hay en disco, levanta
  `RuntimeError` — ni escribe ni deja entrenar con datos degradados.
  `PERMITIR_HISTORICO_MENOR=1` para el recorte intencionado.
- El fichero restaurado a 6.759 filas: el último bueno más los dos partidos
  nuevos que sí traía el degradado, deduplicando por fecha y equipos.
- `odds_store.fuente_football_data_valida` devuelve `accesible` además de
  `valida`, que son cosas distintas: «no responde» y «responde y miente». Con
  la fuente caída, el check de COL **aprobaba por el motivo equivocado** —se le
  pide que rechace por CONTENIDO y rechazaba por red— y el de AUT se ponía rojo
  sin que hubiera nada roto. Ahora, si no hay fuente, se avisa en voz alta y no
  cuenta como fallo del código.

**La suite queda en 2.675 checks y CERO fallos.**

**Pendiente que deja:**

1. football-data.co.uk sigue caído. Mientras lo esté, la Leagues Cup no
   incorpora partidos nuevos de MLS ni Liga MX a su agrupado — la guarda impide
   que empeore, no puede arreglar la fuente.
2. Nadie vigila los históricos entre commits nocturnos.
   `_v178_historicos_encogidos.py` lo hace a mano; podría ser un paso del
   workflow de reentrenamiento.

---

## 5k. ALOJAMIENTO — LA COMPARATIVA, CON LOS NÚMEROS DE SEPTIEMBRE DE 2026

**Esto corrige lo que decía la §5i.** Allí se recomendó Hugging Face Spaces
como alternativa gratuita; al comprobarlo resultó estar **desactualizado**, y
por eso esta sección existe. El aviso vale para la próxima vez: los planes
gratuitos de 2026 se han recortado casi todos, y una recomendación de
alojamiento caduca en meses.

**El requisito que manda, y sale de la propia bitácora:**
`_v86_barrido_concurrente.py` midió **1.297,7 MB de pico con un solo barrido**
y 2.172,2 MB con dos. Streamlit Community Cloud da **~1 GB**. O sea que la
aplicación vive por encima del techo de su plataforma, y ése es el «se cae
cuando entran dos personas» del §8b, no una casualidad.

| plataforma | RAM | duerme | arranque en frío | veredicto |
|---|---|---|---|---|
| Streamlit Community Cloud | ~1 GB | 12 h sin visitas | reinstala el entorno pip entero | donde está hoy; **por debajo del pico medido** |
| Hugging Face Spaces | 2 vCPU / 16 GB | 48 h | 30-90 s | **ya NO es gratis**: la doc del Hub dice que Gradio y Docker exigen plan de pago (PRO) para cuentas personales; sólo los Static siguen libres, y Streamlit ya ni figura como SDK |
| Render free | **512 MB** / 0,1 CPU | 15 min | 30-60 s | inviable: menos de la mitad del pico medido |
| Fly.io | — | — | — | sin plan gratuito desde 2024 (prueba de 2 h de VM) |
| Railway | según plan | no | — | $1/mes de crédito no da para nada; el Hobby son $5/mes |
| Google Cloud Run | hasta 32 GB | escala a cero | arranca la imagen, no reinstala pip | gratis 180.000 vCPU-s y 360.000 GiB-s al mes ≈ 50 h de instancia con 2 GiB; pide tarjeta |
| Oracle Cloud Always Free | 2 OCPU ARM / **12 GB** | **no duerme** | — | la única máquina permanente gratis; recortada a la mitad en junio de 2026 y con «Out of Capacity» habitual; es **ARM**, y este proyecto ya sabe que los `.joblib` son sensibles a la plataforma (17 de 61 no cargan en Windows por estar serializados en Linux) |

**Lo que se concluye, y lo que no.** Ninguna alternativa gratuita es
claramente mejor hoy. La única que resuelve de verdad los dos problemas —RAM de
sobra y no dormir nunca— es Oracle, y trae dos riesgos que hay que probar antes
de prometer nada: la capacidad ARM y que los modelos entrenados en x86_64
carguen bien en aarch64. Lo que **sí** está medido es que la v178 bajó la
primera carga de 213,2 s a 39,1 s y el cambio de pestaña de más de 153 s a
1,7 s, así que la urgencia de mudarse es mucho menor que antes de mirarlo.

---

## 5l. v178.10 — LA APP NO ARRANCABA, Y NO ERA EL CÓDIGO

Detalle en **BITACORA_ARQUITECTURA.md §30**.

Streamlit Cloud daba «Oh no. Error running app.». El log:

    [06:35:49] 📦 Apt dependencies were installed from .../packages.txt using apt-get.
               E: Release file for .../bullseye-security/InRelease is expired
    [06:35:50] ❗️ installer returned a non-zero exit code
    [06:35:50] ❗️ Error during processing dependencies!

El Cloud ejecuta `apt-get` **sólo si el repositorio trae un `packages.txt`**. El
índice de `bullseye-security` está caducado —Debian 11 archivado— así que
`apt-get update` devuelve código distinto de cero y el Cloud aborta la
instalación entera. Es de su imagen, no del `requirements.txt`.

**No lo provocó ningún cambio nuestro:** el primer fallo es de las 06:26 UTC y
los dos commits de la v178 se subieron después.

`packages.txt` pedía `libxslt1-dev` y `libxml2-dev`, las cabeceras de
compilación de `lxml`, y venían del commit inicial de la v11. Hoy **nada compila
desde fuente**: comprobado en PyPI que lxml 6.1.3, ripser 0.6.15, xgboost 3.3.0,
lightgbm 4.6.0, scipy, scikit-learn y pyarrow traen rueda binaria para Linux
x86_64. Se borra el fichero y el paso que fallaba deja de ejecutarse.

**Lo que hay que recordar:** un fichero de configuración heredado puede tumbar
la aplicación años después sin que nadie lo toque, y el diff no lo enseña. **El
log de la plataforma, primero** — la app arrancaba sin un error en local con el
mismo commit desplegado, así que sin el log se habría revertido un cambio
correcto.

**Pendiente que deja:**

1. Si Streamlit Cloud vuelve a necesitar `packages.txt` algún día, hay que mirar
   antes si el paquete hace falta de verdad: hoy ninguno de los del
   `requirements.txt` compila desde fuente.

---

## 5m. v179 — LA CHAMPIONS ESTABA CONGELADA DESDE JULIO, Y SUS CÓRNERS ERAN INVENTADOS

Detalle en **BITACORA_ARQUITECTURA.md §31**.

El encargo empezó así: «ya empezó la Champions y el único partido que veo es el
de Barcelona de hoy cuando hay más». El barrido **sí** los traía —7 de hoy y 6
de mañana, comprobado sobre el pkl del guardia— y `fixtures_liga('champions')`
devolvía los 12. Lo que estaba parado era el **histórico**, y con él todo lo que
se calcula encima.

### Lo que estaba roto, medido

    fuente          partidos  hasta        estadísticas REALES
    api_football       1.174  2026-07-14     0     (0,0 %)
    ESPN                 895  2026-09-08   774    (86,5 %)

`historico_champions.csv` no se tocaba desde el **14 de julio**. Es la única
competición UEFA con `formato: api_football` —Europa League y Conference League
usan `espn`— y era la única de las tres **sin `stats_origen`**: sus córners,
tarjetas, remates y posesión eran los que inventa el generador sintético.

Y las **774 filas de `stats_espn/champions.csv.gz`** llevaban en el repositorio
sin usarse desde la v162. Es el pendiente nº 6 del traspaso, cerrado.

### El cambio

`champions` pasa a `formato: 'espn', 'espn_liga': 'uefa.champions'`. Con eso:

| | antes | ahora |
|---|---|---|
| histórico hasta | 2026-07-14 | **2026-09-08** |
| córners / tarjetas / remates / posesión | ❌ sintéticos | ✅ **observados** |
| partidos con estadística real | 0 | **774** de 895 |
| aprovechamiento de `stats_espn/` | 0 % | **100 %** |

`stats_disponibles('champions')` pasa de `corners: False, remates: False,
tarjetas: False` a **True en las tres**, que es lo que decide si la tarjeta
enseña un número medido o uno estimado.

**Lo que se pierde, dicho a las claras:** API-Football traía 736 partidos que
ESPN no tiene, y son casi todos **rondas previas** (2022: 212 filas contra 125,
y una fase liga son 125). Para un partido de la fase principal, el historial de
las previas —equipos de otro nivel que en su mayoría no vuelven— aporta poco, y
a cambio costaba tener la competición dos meses parada y con los nombres
desalineados con los del barrido.

**El 1X2 no mejora y no se vende como que sí:** reentrenada, la Champions da
`acc 0,524` contra una línea base ELO de `0,579`. No bate al ELO, igual que
antes. Lo que cambia son las ESTADÍSTICAS FÍSICAS, que pasan de inventadas a
observadas. No se pudo comparar el 1X2 contra el modelo anterior porque
`modelos/` no está versionado desde la v148 y el metadata previo se sobrescribió
al reentrenar.

### La correlación con la liga local: MEDIDA y NO desplegada

El encargo pedía además cruzar el histórico de Champions con el de cada equipo
en su liga local, ponderando por el nivel de la liga. Se midió el puente
(`_v179_champions_vs_liga.py`), y hace falta: aun con las 774 filas, la muestra
**por equipo** es corta —mediana 16 partidos, 37 % por debajo de 10, y Viking
FK, Sabah FK y Como con **cero**—.

**Factor de competición** (Champions ÷ liga local), sobre los 30 equipos que
casan:

    córners      0,861      remates a puerta   0,833
    tarjetas     1,076      remates fuera      0,879

O sea: en Champions se sacan un 14 % menos de córners y un 8 % más de tarjetas
que en la liga de origen. Pero el dato que decide el diseño es otro:

    dispersión del factor ENTRE LIGAS   sd 0,102 (córners)
    dispersión del factor ENTRE EQUIPOS sd 0,232

**El nivel de la liga de origen explica menos que el propio equipo.** La
intuición de que «no es lo mismo el Barcelona que un equipo de una liga menor»
es cierta para la FUERZA, y no se traslada al ajuste de las estadísticas
físicas: separar el factor por liga con 4-5 equipos por liga añadiría ruido.

**Y por qué NO se despliega todavía.** Sólo 30 de los 73 equipos casan con su
liga por nombre. Al intentar cerrar el hueco con `name_mapper.mapear` contra las
46 ligas, el emparejador difuso inventa:

    Internazionale → brasil  Internacional
    Juventus       → brasil  Juventude
    Atalanta       → liga_mx Atlante
    Arsenal        → rus     Arsenal Tula
    Lille          → noruega Lillestrom

`name_mapper` está hecho para buscar dentro del catálogo de UNA liga conocida,
no para adivinar en cuál de 46 juega un club. Desplegar la mezcla así le daría a
la Juventus los córners del Juventude brasileño — mucho peor que no hacerla, y
justo el fallo que el traspaso ya tiene anotado con `Botafogo ↔ Botafogo SP`.

**Lo que falta y es la vía limpia:** un mapa equipo → liga construido con el
dato de ESPN (cada liga publica sus equipos), no adivinado. Con él, los 73
equipos casan por construcción y la mezcla se puede medir contra el ledger antes
de encenderla.

**Pendiente que deja:**

1. El mapa equipo → liga desde los equipos que publica ESPN por competición. Es
   lo que desbloquea la mezcla con la liga local, y sin él no debe encenderse.
2. Medida la mezcla, decidir el peso por tamaño de muestra (el proyecto ya tiene
   el patrón del encogimiento hacia la casa, w=0,25).
3. Europa League y Conference League tienen el mismo problema de muestra corta y
   la misma solución.

---

## 5n. v180 — EL DICCIONARIO EQUIPO → LIGA, QUE ES LA PIEZA QUE FALTABA

Detalle en **BITACORA_ARQUITECTURA.md §32**. La idea es del usuario y es la
correcta: **un equipo pertenece a una liga, y eso se mira, no se adivina.**

### Por qué hacía falta

La v179 dejó medido que para estimar los córners de un Como o un Viking FK en
Champions hace falta su histórico de liga local —en Champions tienen cero
partidos—, y que buscar la liga con emparejamiento difuso contra las 46
producía esto:

    Internazionale -> brasil  Internacional      Juventus -> brasil  Juventude
    Atalanta       -> liga_mx Atlante            Arsenal  -> rus     Arsenal Tula
    Lille          -> noruega Lillestrom         Braga    -> suecia  Brage

Con la pertenencia fijada, el emparejamiento deja de buscar entre 1.069 equipos
de 61 competiciones y busca entre los 18 o 20 de UNA liga, que es donde
`name_mapper` acierta y para lo que está hecho.

### De dónde sale, y no cuesta ni una petición en producción

Dos fuentes que ya están en el repositorio:

- `goleadores_cache.json` guarda `teams:<liga>` con los equipos que ESPN publica
  de cada competición. Tenía 47 ligas; **faltaban 16, entre ellas la
  Bundesliga**, y por eso el Bayern y el Dortmund no casaban. Se completaron
  desde local (ESPN bloquea `/teams` desde IPs de centro de datos, v147): ahora
  son **61 ligas**.
- Los propios `historico_<liga>.csv`, que dan **el nombre tal y como está
  escrito en el histórico** — que es el que hace falta para leer sus córners.

Resultado: `catalogo_equipos.json` con **1.707 equipos**, y de los 83 que
aparecen en el histórico de Champions, **67 (81 %)** tienen liga y nombre
resueltos.

### Las tres trampas que aparecieron, y cómo se cierran

**1. El Liverpool uruguayo.** 91 equipos figuran en más de una competición.
Reglas, en orden: las copas no otorgan pertenencia; si quedan varias, gana la
liga donde el equipo tiene más partidos; si hay empate, **se deja sin asignar**.
Un mapa que se calla es mucho mejor que uno que se inventa.

**2. El Manchester City en la Carabao Cup.** La lista fija de copas se quedaba
corta —`eng_carabao` no estaba— y el City acabó asignado a una copa. Ahora las
copas se reconocen por el NOMBRE de la competición en `config`, no por una lista
que hay que acordarse de ampliar.

**3. El PSG y el Paris FC.** `name_mapper` manda «Paris Saint-Germain» a
«Paris FC» **con confianza alta**, y son dos clubes distintos de la misma liga.
Subir el umbral no lo arregla: con 0,95 sigue dando «Paris FC». Se fija con un
alias explícito al nombre bueno, «Paris SG», revisado a mano y con test.

Se buscaron además **colisiones** (dos equipos distintos al mismo nombre de
histórico): hay 220, y al filtrarlas quedan 48 sin raíz común — revisadas, todas
legítimas («agf»/«aarhus», «ath madrid»/«atletico madrid»,
«fc københavn»/«fc copenhagen»). Tras el alias del PSG **no queda ninguna
peligrosa**.

### Lo que este cambio NO hace todavía

`catalogo_equipos` es **infraestructura**: nadie lo consume aún. Conectarlo al
cálculo de córners, tarjetas y remates —mezclar el perfil de Champions con el de
la liga local usando el factor medido en la v179 (córners 0,861, tarjetas
1,076)— es el paso siguiente, y tiene que medirse contra el ledger antes de
encenderse. Se sube ahora porque es la pieza que faltaba y porque tiene test
propio: sin ella, cualquier mezcla habría sido adivinada.

**Pendiente que deja:**

1. Consumir el catálogo en `rendimiento_equipos` para la mezcla, con peso por
   tamaño de muestra, y medirlo.
2. Los 16 equipos de Champions sin liga resuelta son de ligas que el catálogo no
   cubre (Shakhtar, Slovan Bratislava, Qarabag, Ferencvaros, Pafos…). Para ésos
   no hay liga local que mirar, y el mapa lo dice en vez de inventarla.
3. `Como -> ita_serie_b` es correcto por histórico y **obsoleto por realidad**:
   ascendió a la Serie A. El mapa refleja dónde tiene más partidos, no la
   temporada en curso.

---

## 5o. v181 — EL PRECIO ESTABA DESCARGADO Y SE TIRABA A LA BASURA

Detalle en **BITACORA_ARQUITECTURA.md §33**.

El encargo era «que sí haya cuota, que no haya nada de que no llegó la cuota».
Y la primera medición apuntaba a que no llegaba ninguna — **era un error de
medición mío**: se miró `pick['cuota']`, que es un campo de cabecera y está a
`None` a propósito desde la v49, en vez de las apuestas que produce
`valor_apuesta`. La aplicación sí tenía cuotas.

Pero al medir bien apareció un agujero de verdad.

### Lo que estaba roto, medido en los 12 partidos de Champions

    Barcelona vs Feyenoord       implicitas COMPLETAS (Playdoit)  13 candidatas
    PSG vs Slovan Bratislava     implicitas {1x2, goles}            0 candidatas
    Napoli vs Arsenal            implicitas {1x2, goles}            0 candidatas
    Sporting CP vs Galatasaray   implicitas {1x2, goles}            0 candidatas

Los tres de abajo tenían modelo **y tenían precio**: ESPN publica `odd_home`,
`odd_draw` y `odd_away` para los doce. Lo que fallaba es que cuando el tablero
de Playdoit no cubre el partido, el respaldo de `implicitas_de_la_casa`
calculaba las probabilidades sin margen y **descartaba las cuotas de las que
salían**. Y `valor_apuesta._1x2` corta en seco sin ellas:

    cuota = cu.get(lado)
    if not cuota:
        continue

Lo mismo en goles: el respaldo guardaba un `float` con la probabilidad cuando el
formato de la v171 es `{'p':…, 'mas':…, 'menos':…}`, y `_de_goles` lee las dos
cuotas de ahí.

**Esto no es inventar líneas (§24).** Aquella regla prohibía proponer líneas que
ninguna casa publica, sacadas del modelo — y costó el 28 % de las de goles. Aquí
el precio existe, viene de una casa real y ya estaba descargado por el propio
barrido: lo único que se hacía con él era tirarlo.

### El resultado

|  | antes | ahora |
|---|---|---|
| fútbol de hoy con apuesta recomendada | 28 de 39 (72 %) | **37 de 39 (95 %)** |
| con cuota en la recomendada | 28 | **37** |
| con `1x2_cuotas` en las implícitas | — | **37 (95 %)** |
| Champions con apuesta | 3 de 9 | **9 de 12** |

Los tres que fallaban pasan a proponer: `Gana PSG @ 1,029`,
`Gana Sporting CP @ 1,685`, `Goles: Más de 2.5 @ 1,909`.

`mercado_implicito.prob_de` entiende los dos formatos desde la v171, así que
pasar el respaldo a dict no rompe a ningún lector.

### Los tres que siguen sin apuesta, y por qué

    VfB Stuttgart vs Viking FK      prob None · sin cuotas
    Fenerbahce vs AS Roma           prob None · sin cuotas
    Como vs RB Leipzig              prob None · sin cuotas

No es el precio: es que **el modelo no predice**. Son los equipos sin histórico
de Champions —Viking FK, Sabah FK y Como tienen cero partidos, medido en la
v179—. Ésos son exactamente los que arregla conectar el catálogo equipo → liga
de la v180 al cálculo, que es el pendiente nº 1 del proyecto ahora mismo.

**Pendiente que deja:**

1. Conectar `catalogo_equipos` al cálculo para los equipos sin histórico de la
   competición. Sin eso, esos tres partidos seguirán sin pronóstico.
2. Alguna recomendada sale con cuota por debajo del mínimo declarado de 1,20
   (`Gana PSG @ 1,029`). No llega a verde —el Score la deja en ámbar— pero
   convendría revisar si `recomendadas` debe aplicar el mismo suelo que
   `mejores`.

---

## 5p. v182 — EL ENCHUFE: UN EQUIPO SIN PASADO EN LA COMPETICIÓN USA EL DE SU LIGA

Detalle en **BITACORA_ARQUITECTURA.md §34**. Es la conexión que la v180 dejó
preparada y la v179 dejó medida.

Módulo nuevo: **`perfil_liga_local.py`**, enganchado en las tres lambdas por
equipo de `rendimiento_equipos` (córners, tarjetas y remates).

### El agujero que se cierra

En Champions la muestra por equipo es corta —mediana 16 partidos, el 37 % por
debajo de 10, y **Viking FK, Sabah FK y Como con cero**—. Con menos de
`MIN_PARTIDOS`, `lambda_corners_equipo` y sus dos hermanas devolvían `None`, y
el partido caía a `_estimado`, que reparte el nivel medio de la competición
entre los dos bandos: **los dos equipos salían con el mismo número**.

Y sí había con qué: el Viking juega en Noruega y allí tiene cientos de partidos
con córners contados.

### Lo que se midió ANTES de enchufarlo

`_v182_mide_mezcla.py`, walk-forward sobre los 774 partidos de Champions con
estadísticas observadas (1.548 equipos-partido), error absoluto medio:

                          córners   tarjetas   remates
    sólo Champions         2,4429    1,1362    2,2973
    mezcla con su liga     2,3618    1,1027    2,2187

Y donde de verdad importa, los que llegan con menos de 5 partidos previos en la
competición (362 casos):

    córners  −6,20 %   ·   tarjetas  −5,11 %   ·   remates  −7,79 %

**Por eso sólo actúa cuando falta muestra.** Con el equipo ya visto en la
competición, lo suyo manda: la mejora está en la cola, y el estimador actual
está validado sobre 30.454 equipos-partido. Cambiar lo que ya funciona por una
corazonada sería exactamente lo que este proyecto no hace.

### El factor de competición, re-medido

`_v182_factor_competicion.py`, 55 equipos (la v179 tenía 30), en
`factor_competicion.json`:

    córners 0,8157 · tarjetas 0,9981 · remates a puerta 0,8510 · fuera 0,8873

En Champions se sacan un 18 % menos de córners y **las mismas tarjetas**. Eso
último **corrige a la v179**, que con 30 equipos midió 1,076: con casi el doble
de muestra el efecto desaparece.

**Un factor único, no uno por liga**, y sigue medido: la dispersión entre ligas
(sd 0,10 en córners) es menor que entre equipos (sd 0,22). El nivel de la liga
de origen explica menos que el propio equipo.

### El resultado

Sobre los próximos partidos de las tres competiciones UEFA:

    casos (partido × estadística)   186
    observado   SIN enchufe  42  ->  CON enchufe 118
    estimado    SIN enchufe 144  ->  CON enchufe  68

**76 casos pasan de un número inventado a uno calculado con partidos reales**, y
cada equipo con el suyo:

    Como vs RB Leipzig          estimado -> observado   5,01 / 3,45
    VfB Stuttgart vs Viking FK  estimado -> observado   4,62 / 3,94
    Braga vs KuPS Kuopio        estimado -> observado   6,73 / 3,08

### Y un fallo del catálogo que apareció por el camino

El Como seguía sin datos, y no era el enchufe: **el catálogo lo mandaba a la
Serie B**.

    Serie B   114 partidos, último 2024-05-10   <- el catálogo elegía ésta
    Serie A    79 partidos, último 2026-09-04   <- donde juega AHORA

El desempate por volumen premiaba el pasado. Ahora primero se filtra por las
ligas donde el equipo ha jugado **en el último año**, y sólo si ninguna lo es
—o si hay varias— se recurre al número de partidos. Un ascenso o un descenso se
refleja en cuanto hay una jornada nueva. Con eso el Como pasa a `serie_a` y su
partido tiene estadísticas observadas.

**Pendiente que deja:**

1. Los equipos sin liga en el catálogo (Sabah FK, Slovan Bratislava, Shakhtar,
   Qarabag…) siguen sin respaldo: sus ligas no están en el catálogo del
   proyecto. El mapa lo dice en vez de inventarlo.
2. El enchufe cubre córners, tarjetas y remates. El **1X2 sigue sin predecirse**
   para los equipos que el motor de la competición no conoce: eso es el modelo
   entrenado, no las estadísticas, y es otro trabajo.
3. El factor está medido sólo para `champions`. Las otras cinco competiciones
   de la lista usan 1,0 —no corregir— hasta que se mida cada una.

---

## 5q. v183 — LA MISMA CORRELACIÓN, EN LAS NUEVE COPAS

La v182 enchufó el respaldo de liga local sólo en la Champions. Es el mismo
problema en todas las copas: los equipos vienen de ligas distintas y juegan
pocos partidos.

### El factor, medido copa por copa

`_v182_factor_competicion.py` recorre ahora todas las competiciones que
`catalogo_equipos._es_copa` reconoce y que publican estadísticas observadas:

    competición          córners  tarjetas  sh_on  sh_off   n equipos
    champions             0,8195   0,9990  0,8434  0,8836      56
    europa_league         0,8798   1,0781  0,9056  0,9080      77
    conference_league     0,8907   1,0349  1,0113  0,9663      54
    libertadores          0,8889   1,0615  0,9428  0,9753      67
    sudamericana          0,9368   1,0515  1,0125  1,0003      98
    leagues_cup           0,9297   0,9047  1,0474  0,9368      48
    bra_copa              1,0237   1,0321  1,0617  1,0623      23
    eng_fa_cup            1,1489   0,7153  1,1414  1,0616      14  ← no se usa
    afc_champions         0,8994   1,1311  0,7591  0,8368      17  ← no se usa

**El patrón se repite en las cinco copas continentales**: menos córners
(0,88-0,94) y más tarjetas (1,03-1,08) que en la liga de origen. Partidos más
cerrados y más tensos, medido.

**Y una guarda nueva:** `MIN_EQUIPOS_FACTOR = 20`. Con menos, el factor es ruido
y se deja en 1,0. La FA Cup lo midió con 14 equipos y dio justo el patrón
invertido —0,7153 en tarjetas, 1,1489 en córners—, que es lo que produce una
muestra corta llena de cruces entre categorías distintas. Prefiere no corregir a
corregir mal.

### La lista dejó de escribirse a mano

`perfil_liga_local.aplica()` ya no consulta una tupla fija: **son las
competiciones que tienen factor medido**, y eso se cumple exactamente cuando la
copa publica estadísticas observadas — que es también la condición para que el
estimador por equipo pueda usarse. Una lista escrita a mano se queda corta sola,
y ya pasó con `eng_carabao` en el catálogo.

### El resultado

Sobre los próximos partidos de las nueve copas:

    casos (partido × estadística)   240
    observado   SIN enchufe  76  ->  CON enchufe 158
    estimado    SIN enchufe 164  ->  CON enchufe  82

    Sunderland vs AZ Alkmaar    estimado -> observado   3,84 / 5,26
    CSKA Sofia vs Trabzonspor   estimado -> observado   6,86 / 5,68
    Braga vs KuPS Kuopio        estimado -> observado   6,46 / 2,94

### La cobertura, y dónde están los huecos

De los 1.197 equipos que aparecen en los históricos de las nueve copas, **436
(36 %) no tienen liga local resuelta**, y no están repartidos por igual:

    libertadores        0 sin liga     leagues_cup     0 sin liga
    sudamericana        0 sin liga     champions      16 sin liga
    afc_champions      60              eng_fa_cup     53
    conference_league  68              europa_league  99
    bra_copa          140

Las tres copas americanas están **al 100 %** —el proyecto tiene muchas ligas de
allí—. Los huecos son: el Golfo (Al Hilal, Al Nassr, Al Sadd… en la AFC), las
ligas europeas menores (Chipre, Israel, Serbia, Croacia, Eslovaquia, Kazajistán,
Azerbaiyán) y los equipos de categorías inferiores de la FA Cup y la Copa do
Brasil, que juegan un partido y desaparecen.

---

## 5r. v184 — DOS LIGAS NUEVAS, Y EL HISTÓRICO AGRUPADO MEDIDO Y **NO** ENCENDIDO

Las dos cosas que quedaban pendientes de la v183. Una entra y la otra no, y las
dos por lo mismo: lo que dice la medición.

### (b) La cobertura — el techo era mucho más bajo de lo estimado

Se propuso añadir «unas diez ligas» (el Golfo y las europeas menores). Al
comprobarlo contra ESPN, **sólo dos son viables**:

    ksa.1  Saudi Pro League        66 eventos   ✅  1.211 partidos, 27 equipos
    isr.1  Israeli Premier League  56 eventos   ✅    720 partidos, 17 equipos
    cyp.1  Cypriot First Division   0 eventos   ❌  responde 200 y está vacío
    cze.1  Gambrinus Liga           0 eventos   ❌  igual
    qat · uae · srb · cro · ukr · aze · kaz · hun · svk · bul   HTTP 400

**Y esto ya estaba investigado en la v144**, que dejó escrito que ESPN publica
218 competiciones y que ninguna de las pedidas está en su catálogo. `ksa_pro`
incluso estaba ya definida, apagada y sin histórico. La propuesta de las diez
ligas se hizo sin leer esa sección: la lección es que este repositorio ya sabe
muchas cosas, y re-derivarlas cuesta tiempo y produce estimaciones infladas.

**Lo que entra:** las dos ligas, con `disponible: False` — no entran en el
barrido ni necesitan modelo. Su trabajo es alimentar el catálogo equipo → liga y
el respaldo de estadísticas.

    ksa_pro      1.211 partidos · 664 con estadísticas reales inyectadas
    isr_premier    720 partidos · 0 con estadísticas (ESPN no publica su
                                    boxscore: da liga, no da córners)

Resultado sobre las copas:

    afc_champions   60 -> 50 equipos sin liga
    europa_league   99 -> 96
    conference      68 -> 65

Al Hilal, Al Nassr, Al Ittihad, Al Ahli y Al Shabab pasan a tener liga local, y
`Al Hilal vs Al Nassr` en la AFC Champions da ya **4,50 / 5,30 observado**.

### (a) El histórico agrupado — medido, y NO se enciende

`historico_agrupado.py` construye, para una copa, su histórico más los partidos
de liga de sus participantes. Es el patrón que `leagues_cup` ya usa. La
cobertura es total:

    champions        895 -> 51.345 partidos    83/83 equipos
    europa_league  1.356 -> 66.245            214/214
    libertadores     791 -> 25.904            107/107

**La primera medición dijo que mejoraba, y no valía.** Comparaba el margen sobre
la línea base ELO de los dos modelos:

    actual     n_train    566 · acc 0,5274 · ELO 0,5822 · margen −0,0548
    agrupado   n_train 41.725 · acc 0,5213 · ELO 0,5082 · margen +0,0131

El margen sube porque **la línea base baja**, y baja porque cada modelo se
valida sobre un conjunto distinto: el agrupado valida sobre partidos de liga,
donde el ELO acierta menos que en Champions. La precisión, de hecho, **bajaba**.
Comparar márgenes calculados sobre conjuntos distintos no dice nada.

**La medición buena**, los dos entrenados con lo anterior a un corte y evaluados
sobre **los mismos 179 partidos de Champions**:

    solo copa      acc 0,5419   logloss 0,9526
    agrupado       acc 0,5810   logloss 1,0002
                   acc +0,0391  logloss +0,0476

**Señales cruzadas: acierta un 3,9 % más y calibra peor.** Y en este proyecto la
calibración no es un detalle secundario — todo lo que se enseña se apoya en que
«cuando dice 62 %, es un 62 %». Un modelo que acierta más el ganador pero cuyas
probabilidades son peores no sirve para decidir una apuesta.

Así que **no se enciende**. Queda el módulo, medido y documentado.

### Lo que sí propondría hacer con él, y por qué no se ha hecho ya

La vía que las mediciones sostienen es la misma que funcionó con las
estadísticas: **usarlo sólo donde ahora no hay nada**. Un segundo modelo por
copa, entrenado con el agrupado, que se consulte únicamente cuando el motor de
la competición no conoce a un equipo —los `prob: None`— y no toque el resto.

No se ha hecho en esta tanda porque significa entrenar y almacenar un modelo más
por copa, y tocar el workflow de reentrenamiento y la publicación de pesos al
Release. Es una versión propia, no el final de ésta.

**Pendiente que deja:**

1. El modelo de respaldo por copa para los `prob: None`. Es lo que cierra el
   caso de Stuttgart-Viking, Fenerbahce-Roma y Como-Leipzig.
2. `isr_premier` da liga pero no estadísticas: ESPN no publica su boxscore.
3. Los 193 equipos sin liga de `bra_copa` y `eng_fa_cup` son de categorías
   inferiores que juegan un partido y desaparecen; el coste por equipo cubierto
   es mucho peor que el de las demás.


---

## 5s. v185 — LA SAUDI PRO LEAGUE, ENCENDIDA

Pedido: «si vas a agregar la liga de Arabia Saudí, que también aparezca en
Apuestas del Día».

La v144 la dejó apagada con un motivo escrito y un test que lo vigilaba: «no
tiene ni histórico ni team_stats». La v184 le bajó el histórico —1.211 partidos,
664 con córners y tarjetas observados de ESPN— para alimentar el catálogo
equipo→liga, así que ya sólo faltaba entrenarla.

    modelo    n_train 924 · acc 0,5517 · ELO 0,5560 · log-loss 0,9518
    proximos  11 partidos con cuota en los 7 dias siguientes

**Su modelo no bate al ELO** (0,5517 contra 0,5560) y eso no la deja fuera:
desde la v161 el acierto del 1X2 dejó de decidir qué competiciones salen. El
modelo bate al mercado en 1 de 34 y el valor medido está en el precio, no en el
pronóstico. La nota de la liga lo dice con esas palabras para que nadie lo lea
como una promesa.

El check de la suite cambia de sentido: antes comprobaba que seguía apagada
**porque le faltaban las dos cosas**; ahora comprueba que las tiene y que está
encendida. Son 63 competiciones disponibles.

**`isr_premier` se queda apagada**, y por un motivo distinto: ESPN no publica su
boxscore —0 partidos con estadísticas— y su histórico se corta en mayo de 2025.
Da liga local a Maccabi Haifa y Hapoel para el catálogo, que es para lo que
entró, pero no tiene con qué aparecer en la pantalla.

---

## 5t. v186 — SEIS SEMANAS SIN MEDIR SI LOS PRONÓSTICOS ACIERTAN, CON EL WORKFLOW EN VERDE

Salió de una pregunta del usuario: «¿qué has hecho con los resultados de los
partidos que ya han acabado?». La respuesta corta era buena —los históricos sí
los llevan— y al comprobarla apareció lo que no.

### Lo que sí estaba entrando

Los resultados recientes llegan a los históricos todas las noches:

    champions       hasta 2026-09-08   (los de la jornada de ayer)
    libertadores    hasta 2026-09-08
    ksa_pro         hasta 2026-09-09
    laliga · premier · serie_a · ligue_1   hasta 2026-09-04 (parón de selecciones)
    liga_mx · mls   hasta 2026-09-05
    bundesliga      hasta 2026-08-30
    europa_league   hasta 2026-05-20   ← ésta no

### Lo que NO estaba entrando

    pick_ledger_total.csv        último commit 2026-07-29
    umbrales_capa1.json          último commit 2026-07-28
    calibracion_confianza.json   último commit 2026-08-08
    edge_map.json                último commit 2026-08-17
    calibracion_mercado.json     último commit 2026-09-09   ← al día

`pick_ledger_total.csv` es **el fichero que mide si los pronósticos aciertan**.
Seis semanas sin actualizarse. Y `umbrales_capa1.json`, que es lo que decide qué
entra en la Capa 1, otras seis.

Y no es que el workflow no corriera: `recalibrar.yml` se ejecutó el 2026-08-31 y
el 2026-09-07, y sus dos commits tocaron **un solo fichero**,
`_v162_calibracion_por_liga.json`, con un cambio de una línea.

### La causa: dos fallos en el mismo paso, los dos callados

```
git add -A historico_itf.csv.gz modelos/tennis modelos/tennis_wta \
           pick_ledger_total.csv calibracion_confianza.json \
           ... 2>/dev/null || true
```

**`modelos/` está en .gitignore desde la v161** (2026-08-22): sus pesos viajan
por el GitHub Release, no por el repositorio. Y `git add` con un path ignorado
**falla entero y no añade ninguno de los demás**. Comprobado aquí:

    con modelos/tennis y modelos/tennis_wta ....  exit 1
    sin ellos ..................................  exit 0

El `2>/dev/null || true` convertía ese fallo en silencio, y el `git add` de
`_v162_calibracion_por_liga.json` —que va aparte, con un solo fichero— seguía
funcionando. De ahí que el commit semanal existiera y no llevara nada dentro.

El segundo fallo, en la línea de al lado:

```
git add -A stats_espn/ calibracion_stats_liga.json \n                     INFORME_CALIBRACION.md
```

Un **`\n` literal** en medio del comando en vez de un salto de línea. El shell
lo pasaba como argumento y el `git add` se rompía. Mismo `|| true`, mismo
silencio.

### El arreglo

- Fuera `modelos/tennis` y `modelos/tennis_wta` del `git add`.
- El `\n` literal pasa a ser una continuación de línea de verdad.
- Y los dos `git add` **avisan si fallan** (`::warning::`) en vez de callarlo.

### Lo que esto enseña, que es lo de siempre en este proyecto

Un workflow en verde no es un workflow que funciona. Éste corría cada lunes,
terminaba bien, publicaba su commit y no estaba haciendo su trabajo desde hacía
seis semanas. Lo que lo tapaba no era un bug raro: era `2>/dev/null || true`
puesto para que un fallo no tumbara la pasada.

Es exactamente el §27.9 con otra ropa —un check que no puede fallar es peor que
no tenerlo— aplicado a un paso de CI: **un comando que no puede fallar visible
es peor que uno que rompe el workflow**.

**Pendiente que deja:**

1. `europa_league` sigue con el histórico en mayo de 2025. No se ha investigado
   por qué no se regenera; es formato `espn` y debería.
2. El ledger no se recupera solo: hay que dejar correr la recalibración del
   lunes (o lanzarla a mano) para que vuelva a medir. Hasta entonces, los
   números de eficacia que la app enseña son los de julio.
3. Nadie vigila la frescura de estos ficheros. Un check que compare su fecha
   contra la del último commit de datos lo habría cazado en agosto.

---

## 5u. v187 — LOS SNAPSHOTS SÍ SIRVEN, Y ESTABAN ESPERANDO A UN `git add` ROTO

Pregunta del usuario: «los snapshots llevan tiempo tomándose y no sé si han
servido de algo; si sí, aplícalo, y si no, bórralos».

**Respuesta: sirven, no se borran, y ya se han liquidado por primera vez.**

### Para qué se crearon

La v159 los empezó porque **no existe histórico de líneas de córners**:
football-data no las publica y el de The Odds API es de pago. Sin líneas pasadas
no hay apuestas que liquidar, así que la regla de oro del proyecto —percentil 5
positivo— no se podía ni aplicar a ese mercado, y su EV sale marcado. El plan
escrito era: «en unos meses habrá con qué medir».

    corners_snapshots.csv    167.700 fotos · 2026-08-22 -> 2026-09-09
    tarjetas_snapshots.csv    50.577
    remates_snapshots.csv     22.680

### Por qué no habían servido: dos causas, y ninguna era el fichero

**1. El emparejamiento.** Las fotos vienen de Playdoit («Eyupspor», «Gaziantep
FK») y los resultados de football-data («Ath Bilbao», «Ath Madrid»). Comparando
los nombres tal cual casaban **0 de 167.700**. Pero cada foto trae su
`clave_liga`, así que se empareja DENTRO de esa liga con `name_mapper`, que es
para lo que está hecho. Es la misma lección de la v180 aplicada aquí.

**2. El fondo de estadísticas estaba congelado, por el bug de la v186.** Los
snapshots fotografían partidos del 23-08 en adelante, y las estadísticas
observadas de todas las ligas se paraban el **2026-08-22** — exactamente la
fecha del último commit de `stats_espn/`. La causa es el `\n` literal que rompía
su `git add`:

    el \n literal rompe el git add de stats_espn/
      -> el fondo de estadísticas se congela el 22 de agosto
      -> los históricos no reciben córners nuevos
      -> los snapshots no tienen con qué liquidarse

Puesto al día el fondo (backfill de 10 ligas, 2 s cada una) y reinyectado en los
históricos, aparecen los resultados y se puede liquidar.

### La primera liquidación

Sólo las familias de **total del partido** con mercado Más/Menos. Y en tarjetas
se cuentan **amarillas más rojas**, que es lo que cuenta la casa:

    CÓRNERS   378 apuestas · 50,0 % aciertos · ROI  −9,91 % · p5 −18,46 %
    TARJETAS  180 apuestas · 50,0 % aciertos · ROI −10,17 % · p5 −21,98 %
    REMATES   118 apuestas · 50,0 % aciertos · ROI  −7,07 % · p5 −21,74 %

Los tres clavados en **50,0 % de acierto**, que es exactamente lo que se espera
de apostar contra el margen de la casa: la línea está donde la probabilidad es
50/50 y el margen se lo queda ella.

**Ninguno supera la regla de oro.** Con esta muestra, el EV que el proyecto
calcula para córners, tarjetas y remates **no gana dinero**.

**Y la salvedad, que es grande:** son 18 días y menos de 400 apuestas por
mercado. El p5 tan negativo lo dice — con esta muestra no se puede afirmar mucho
más que «no hay evidencia de que gane». Lo que sí queda es la máquina montada:
`_v187_liquida_snapshots.py` se puede volver a correr cada semana, y con el
`git add` arreglado la muestra crecerá sola.

### Un ROI del +76,93 % que era mío, no del mercado

La primera pasada dio **+76,93 % en tarjetas con p5 +60,22 %**. No era un
hallazgo: metía en el mismo saco «Total de tarjetas», «1ª mitad - tarjetas
exacto», «15 minutos - total tarjetas», «Impar/Par» y «Ambos equipos 2+», y las
comparaba todas contra el total del partido. Una línea de media parte contra el
marcador final da un número con aspecto de ROI.

Queda escrito porque es el error más fácil de cometer aquí y el más difícil de
ver: **el número salía bonito**.

**Qué NO se borra:** nada. Los tres CSV se quedan y el workflow sigue
tomándolos.

**Pendiente que deja:**

1. Repetir la liquidación con más muestra. Un mes más y son ~1.500 apuestas por
   mercado, que ya empieza a decir algo.
2. Las familias que no se liquidan —exactas, rangos, 1x2, impar/par, ventanas
   de 15 minutos, por equipo— necesitan cada una su regla. Son el 89 % de las
   fotos de córners.
3. `odds_snapshots.csv` sí se consume (cinco módulos) y alimenta el CLV, que ya
   da una medición sobre 2.504 apuestas: CLV medio **−2,78 %** y sólo batimos el
   cierre el **15,2 %** de las veces. Y un dato que contradice la teoría y
   merece su propia mirada: el ROI **cuando batimos** el cierre (−6,62 %) es
   PEOR que cuando no (−3,70 %).

---

## 5v. v188 — UN VIGILANTE DE FRESCURA, Y LA GUARDA QUE FALTABA POR ARRIBA

Los cuatro puntos que quedaban de la tanda anterior. Tres entran; el cuarto se
explica.

### 1. `europa_league` NO estaba rota: está en receso

Salió en la auditoría con el histórico parado en mayo de 2025, y no le pasa
nada. ESPN devuelve para la Europa League **exactamente hasta el 2026-05-20**,
que es su final —SC Freiburg 0-3 Aston Villa—. Su fase liga nueva empieza el 24
de septiembre. Igual la Conference League, la FA Cup, la A-League australiana y
la ISL india: las cinco terminan en mayo.

**No hay nada que arreglar**, y eso también es un resultado.

### 2. El vigilante: `frescura_datos.py`

Tres fallos del mismo día, todos silenciosos y con el workflow en verde:

    historico_champions.csv    parado 2 meses    (fuente de pago caducada)
    pick_ledger_total.csv      parado 6 semanas  (`git add` con path ignorado)
    stats_espn/                parado 3 semanas  (un `\n` literal)

Lo que tienen en común no es la causa, sino que **nada miraba la fecha**. Un
fichero que deja de actualizarse no da error: se queda quieto y todo lo que se
calcula encima sigue devolviendo lo de antes. Los tres salieron porque el
usuario preguntó, no porque algo avisara.

El vigilante mira, para cada pieza que debería refrescarse sola, cuántos días
lleva sin cambiar —por la fecha del último COMMIT, no por el `mtime`, que un
`git clone` pone todo a la hora del clon— contra un plazo generoso: 3 días para
lo del bot nocturno, 10 para lo semanal y para los históricos. No está para
avisar de un 503 de anoche, sino de que algo lleva semanas quieto.

**Y distingue receso de avería, que es lo que lo hace usable.** La primera
versión marcaba las cinco competiciones de arriba como paradas: cinco falsos
positivos, y un check con falsos positivos se ignora a la tercera semana. La
segunda preguntaba «¿tiene partidos próximos?», y eso tampoco valía —la Europa
League los tiene y su histórico está completo—. La pregunta correcta es **¿le
falta algún partido ya jugado?**, y con ella el resultado queda limpio:

    al día:      64
    PARADOS:      4   <- pick_ledger, umbrales_capa1, calibracion_confianza, edge_map
    en receso:    5   <- las cinco de arriba, correctamente descartadas
    sin evaluar:  0

Los cuatro que quedan son exactamente los del bug de la v186. Cero falsos
positivos.

Entra en `recalibrar.yml` **después** de recalibrar y **antes** de commitear,
que es el único momento en que se sabe si la pasada movió algo. Avisa, no rompe.

### 3. La guarda de históricos, ahora también por arriba

La de la v178.9 sólo vigilaba que un histórico no **encogiera**. Por ese hueco
se coló lo contrario: un script de medición parcheó `descargar_liga` y
`_guardar_historico` escribió **53.264 filas encima de las 895** de la
Champions, sin un solo aviso. Se restauró porque alguien miró el `git status`.

Ahora hay techo por arriba: **×2 en una sola pasada** aborta. Una liga suma unos
diez partidos por semana sobre miles; duplicarse no es una temporada nueva.
El fichero que no existía se escribe sin mirar —ésa es la primera descarga— y
`PERMITIR_HISTORICO_MENOR=1` sigue siendo la salida para lo intencionado.

Probado en la suite: escribe la primera vez, deja pasar +1 %, **frena un ×52** y
el fichero bueno queda intacto.

### 4. El modelo de respaldo por copa: sigue sin hacerse, y por qué

Es lo único del encargo original que queda abierto: Stuttgart-Viking,
Fenerbahce-Roma y Como-Leipzig siguen sin pronóstico 1X2 porque el motor no
conoce a esos equipos.

El histórico agrupado que lo resolvería está construido y medido (§5r): acierta
un 3,9 % más y **calibra peor** (log-loss +0,0476), así que encenderlo tal cual
degradaría lo único en lo que este proyecto se apoya. La vía que las mediciones
sostienen —un segundo modelo por copa consultado sólo donde hoy no hay nada—
obliga a entrenar y publicar un modelo más por copa, y a tocar el workflow de
reentrenamiento y la subida al Release. Es una versión propia, no el final de
ésta.

---

## 5w. v189 — EL PASO QUE DECÍA RE-PREDECIR Y SÓLO CONCATENABA

Los cuatro ficheros que la v188 dejó marcados como parados no eran cuatro
fallos. Eran uno.

### 1. La recalibración semanal nunca reconstruyó el ledger

`recalibrar_todo.py` describe su paso 1 como «re-predice el histórico con los
modelos de HOY» y calcula que cuesta unos 40 minutos. Por ese coste se decidió
que el workflow fuera semanal y no diario.

**Ese coste no se pagaba nunca.** El paso llamaba a
`build_ledger_total.construir()`, que no re-predice nada: junta
`pick_ledger.csv` y `pick_ledger_deportes.csv` en un segundo. Los dos módulos
que sí re-predicen —`build_pick_ledger` y `build_ledger_deportes`— no los
llamaba nadie; `retrain_leagues.yml` los documenta como «a mano».

Lo dice el propio fichero de metadatos del ledger:

    _v75_pick_ledger.json    generado: 2026-07-28T18:48:47Z

Desde la v93 (2026-08-03), **cada lunes la cadena entera —bandas de confianza,
umbrales de Capa 1, mapa de EV, precisión por liga— se recalibró sobre partidos
de julio**. Y como el ledger salía idéntico byte a byte, no había diff, no había
commit, y el workflow terminaba en verde. Los cuatro ficheros «parados» eran
la sombra de esto.

**Medido antes de desplegar**, regenerando en un fichero aparte para no pisar el
bueno:

    reconstrucción completa            42,4 min   (la estimación decía ~40)
    filas          47.948 -> 80.635    (+32.687)
    ligas              56 -> 63        (+7)
    rango       2021-08-16 -> 2026-07-28  pasa a  2018-02-17 -> 2026-09-09
    partidos que el modelo no había visto nunca:  2.357, en 57 ligas

Sobre los **mismos 46.518 partidos**, el acierto cambia +0,0002 y el log-loss
−0,0023. Casi idéntico, que es lo que debe salir al re-predecir con modelos
apenas más nuevos: un salto grande habría sido la señal de que algo estaba mal.
Los 2.357 partidos nuevos rinden en línea (0,4820 de acierto frente a 0,4903
global), sin anomalías.

**Qué mejora esto y qué no.** No hace mejores las predicciones. Hace que las
*correcciones* se calculen sobre lo que de verdad ha pasado en vez de sobre
julio. Y hay una limitación honesta: de esos 2.357 partidos nuevos **sólo el
6,0 % trae cuota de cierre**, porque football-data.co.uk lleva caído (503 en
todo el sitio). Sirven para calibrar el acierto; no para medir ROI.

La cobertura global de cuota baja del 75,1 % al 64,8 %, y **no se perdió
ninguna**: en las mismas 56 ligas y el mismo tramo pasa de 36.006 a 48.448
cuotas. El porcentaje cae porque crece el denominador.

**El arreglo** reconstruye los dos ledgers de origen y después concatena, cada
uno con su fallo independiente. Y con guarda: un ledger que sale con menos del
70 % de las filas que tenía no pisa al anterior —se construye en un temporal y
sólo sustituye si sale sano—. Es la misma lección de
`league_engine._guardar_historico`, y aquí hacía falta porque una liga cuyo
histórico no se descargue desaparece del ledger sin decir nada.

El job pasa de 120 a 180 minutos. Y el paso del fondo ESPN, que pedía 240
dentro de un job de 120, baja a 100: un paso con permiso para tardar más que su
job lo mata **antes de commitear**, y entonces se pierde todo lo demás.

También baja `mercado_estabilidad.py` detrás de la recalibración. Lee los tres
ledgers walk-forward y corría antes de que se reconstruyeran: coronaba el
mercado de cada liga con la foto de la semana pasada.

### 2. El vigilante de la v188 no podía fallar donde tenía que avisar

Medía la edad por la fecha del último commit. En el runner,
`actions/checkout@v4` clona con `fetch-depth: 1`: con un solo commit en el
historial, `git log -1 -- <lo que sea>` devuelve ese commit para todo. Cero días
para todo.

Informó **«PARADOS: 0 / al día: 73»** la misma semana en que cuatro ficheros
llevaban seis semanas congelados. Un check que no puede fallar en el único
sitio donde importa.

Subir el `fetch-depth` no era la salida: este `.git` pesa **16 GB** —años de
CSV grandes commiteados a diario—, así que un clon completo no cabe en el
runner. La salida es no depender de git: **cada fichero lleva dentro la fecha de
su dato más reciente**, y esa fecha es además la que importa. Un ledger
recommiteado con las filas de julio no está fresco por mucho que su commit sea
de hoy —que es exactamente lo que pasaba—.

Donde un fichero no lleva fecha dentro se cae a la de commit, y si el clon es
superficial se declara **«sin evaluar»**. No saber no se informa nunca como «al
día»: ése fue el fallo. Simulado el clon superficial, caza 3 de los 4 parados
por contenido y declara el resto; **nada se juzga por commit**.

Entran al vigilante `_v75_pick_ledger.json` y `_v78_ledger_deportes.json` —que
dicen CUÁL de los dos ledgers se paró— y `goleadores_cache.json`, cuyo bot
diario `precalcular_rosters.yml` **no ha commiteado nunca, ni una vez**.

### 3. Los `git add` que se callaban, y la tercera pata del mismo bug

Un test nuevo barre los `git add` de los cuatro workflows y comprueba tres
cosas: que ningún path esté en `.gitignore` (falla entero y no añade ninguno),
que ninguno termine en `|| true`, y que ninguna orden lleve un `\n` LITERAL.

Encontró **17 en el workflow diario** tragándose su fallo, incluido el que
mantiene frescos los históricos. Ya avisan.

Y la tercera comprobación existe porque **el `\n` literal volvió a colarse
mientras se escribía esta versión**, parcheando el YAML desde un script — el
mismo bug de la v186, dos veces en seis semanas. El test no lo veía; ahora sí.

### 4. El aviso mandaba a escribir un alias que no puede existir

Sobre la Champions decía: «sus nombres no casan con el catálogo del modelo,
falta un alias en `alias_manuales.json`». Los equipos eran **Fenerbahce, AS Roma
y Como, y sus nombres estaban perfectos**: el histórico de la Champions va de
2020-08-07 a hoy y en esa ventana ninguno de los tres la ha jugado. Ese alias no
existe y no puede existir.

El código ya intentaba separar «alias que falta» de «equipo sin historia» por
parecido con el catálogo (≥ 0,62), y ahí falla: «AS Roma» se parece a «AS
Monaco». La pregunta que sí lo separa es otra: **¿este equipo es conocido en
alguna otra competición?** Si lo es, su nombre está bien. Y eso lo responde el
diccionario equipo → liga de la v180.

    AS Roma -> serie_a      Fenerbahce -> turquia      Como -> serie_a
    Sabah FK -> None        (equipo inventado) -> None

El aviso pasa de ⚠️ «falta un alias» a ℹ️ «no han jugado nunca esta competición
y no hay nada que arreglar», y sigue distinguiendo los otros dos casos: un
nombre que no conoce ningún catálogo sí pide alias, y un motor que no carga
sigue siendo avería.

**Esto arregla el diagnóstico, no la cobertura.** Esos partidos siguen saliendo
con el precio del mercado; cubrirlos es el modelo de respaldo por copa que la
v188 dejó medido y sin encender.

### 5. Los «411 nombres sin mapear»: uno era real

`nombres_sin_mapear.json` es un registro acumulativo que no se poda. De sus 375
entradas:

    233   nombres de JUGADOR (líneas y remates), no equipos
     39   marcadores de cuadro («3rd Place Group A»), no mapearán jamás
     71   equipos de verdad
           42  ya mapean hoy: entradas caducadas
           28  son de COPA: el equipo existe, no tiene historia ahí
            1  bug real

El mensaje «añade alias para llegar a 0» pide algo imposible por construcción.

La pregunta correcta es otra: de los nombres que ESPN manda **ahora**, cuáles no
casan. Barridos **988 nombres reales de 55 competiciones** contra el catálogo
que usa el motor (`eng.stats.keys()`, no el conjunto crudo del histórico — la
primera medición usó el equivocado y hubo que rehacerla). Salieron **10**, y uno
sorprende: **`Manchester United` no casaba en la Premier**, cuyo histórico dice
«Man United». No canta a diario porque el camino normal usa el precálculo
nocturno, donde los nombres ya vienen mapeados; sólo se cae en partidos que
aparecen después.

Los diez llevan **doble destino**, porque el fichero es global y las
competiciones no comparten universo de nombres: la Premier viene de
football-data y la Champions de ESPN. El mapeador se queda con el primero que
exista en el catálogo de esa liga (mecanismo de la v148, por el Deportivo).
Verificado que arregla una sin romper la otra:

    premier    Manchester United -> Man United
    champions  Manchester United -> Manchester United

Rebarrido: **988 nombres, 0 sin casar en ligas normales.** Los 33 que quedan son
todos de copa.

### 6. La Saudi Pro League ya estaba encendida; le faltaba una vuelta del bot

    la Saudi se encendió (v185)   2026-09-09 19:23 UTC
    el precálculo que había       2026-09-09 10:44 UTC

Nueve horas antes. No aparecía en `predicciones_dia.json` ni como fallo: no
estaba en la lista porque cuando el bot corrió no existía. Regenerado a mano,
entra completa —6 de 6 partidos—, con cuota, motor de 28 equipos y cero nombres
sin mapear.

Y el efecto de los alias se mide aquí:

    antes:  49 ligas · 42 completas · 301 partidos · 7 incompletas
    ahora:  50 ligas · 49 completas · 304 partidos · 1 incompleta

Las seis ligas con alias rotos pasan a completas. La única que queda es la
Champions, que es el caso legítimo del punto 4.

### 7. Usar la última foto como línea de cierre: medido y descartado

football-data sigue devolviendo 503 en todo el sitio, así que no entran cuotas
de cierre nuevas. Hay 683 partidos con foto y sin cierre, 267 de ellos con una
foto a **≤12 h del pitido**, y la tentación era promoverlas.

Medido contra los 80 partidos donde están las dos, en probabilidad implícita:

    foto <=12h, cruda          error medio 0,0356    p90 0,1121
    foto <=12h, normalizada    error medio 0,0234    p90 0,0602

Las fotos vienen de casas con unos 4 puntos más de margen (sobreredondeo 1,138
frente a 1,095), y normalizarlo arregla la mitad. Pero el error que queda **es
del mismo tamaño que la señal**: el CLV medio del proyecto es −2,78 %. Sería
medir con una regla más gruesa que la cosa medida, y el CLV es la métrica rey.

**No se promueve nada.** Es un «no» medido, no una corazonada.

### Lo que esta versión deja abierto

1. El modelo de respaldo por copa, que sigue siendo lo único del encargo
   original sin cerrar.
2. `precalcular_rosters.yml` no ha commiteado nunca. Ya está vigilado, pero la
   causa no se ha buscado.
3. El `.git` de 16 GB. Es lo que impide medir la frescura por commit en el
   runner y lo que hará lento cualquier clon nuevo.
4. Las cuotas de cierre siguen dependiendo de una fuente caída, sin sustituto
   que aguante la medición.

---

## 5x. v190 — LO QUE YA VENÍA EN EL `summary` DE ESPN Y NADIE HABÍA ABIERTO

La v189 dejó tres cosas apuntadas y sin hacer. Las tres se cierran aquí, y dos
de ellas con la misma llave.

### 1. El Manchester United que no se veía

Lo reportó el usuario: el 10 de septiembre no aparecía `Manchester United vs
Sabah FK` en la lista de mañana.

**El partido sí estaba en el barrido**, con su hora, con cuota 1,111 y con el
motivo escrito: «Sabah FK no ha jugado todavía en esta competición». Eso no es
una avería —le pasa a medio cuadro de una Champions recién empezada— pero el
reparto de `modo_modelo` lo mandaba a una lista secundaria:

    elif p.get('sin_modelo') or p.get('prob') is None:
        sin.append(p)
    ...
    if sin:
        with st.expander('Sin datos de modelo (%d)'):     # plegado
            st.markdown('· **%s** — %s')                  # una línea de texto

Sin tarjeta, sin hora y sin precio. Y no le tocaba sólo al United: Fenerbahce-
Roma y Como-Leipzig estaban en el mismo saco.

**Lo que más duele es que el dato ya estaba calculado.** `alpha_finder` produce
`board_mercado` para exactamente estos partidos —la probabilidad implícita de
la casa, ya sin su margen— y lo documenta con un «SIN MODELO NO ES SIN
INFORMACIÓN». La pantalla lo ignoraba y pintaba un `**· Sin datos de modelo**`
mudo.

Ahora: **con precio, a la lista principal con su tarjeta**; sin nada que
enseñar, al desplegable. La tarjeta dice **por qué** no hay modelo en vez de un
«Sin datos de modelo» mudo.

**Y NO se rellena el hueco con el precio, que fue el primer intento y estaba
mal.** La v152 lo prohíbe con un argumento mejor que el mío: en una pantalla
cuyo único propósito es leer al MODELO, un número del mercado en una fila del
modelo hace imposible distinguir uno del otro. Su test lo paró en seco. El
precio sigue en Apuestas del Día, que es su sitio.

El reparto mira `sin_cuota` —la bandera que el barrido ya pone— y no
`board_mercado`, así que la cadena prohibida no aparece ni una vez en
`modo_modelo.py` y el invariante de la v152 queda intacto al pie de la letra.

**Y el primer intento tenía algo peor que un criterio discutible.** La variable
local se llamaba `_board`, igual que la función `_board` de arriba, así que
Python la marcaba como local en TODA `tarjeta` y reventaba en su primera línea:

    UnboundLocalError: cannot access local variable '_board'
      modo_modelo.py:2343   b = _board(pick)

Eso es la página entera caída, en las dos vistas y para todos los partidos, no
sólo los que no tienen modelo. Lo cazó `valida_render` antes de que llegara a
producción — y es la respuesta a si vale la pena correr la validación de
interfaz cuando se toca la interfaz.

Lo otro que había que comprobar: esos picks pasan ahora por funciones que nunca
los habían visto. `apuesta_destacada` devuelve None, `recomendadas` devuelve
`[]` y los seis criterios de orden aguantan con `prob=None`.

### 2. Las cuotas de cierre: el agujero era mayor que la caída

`football-data.co.uk` lleva caído —503 en todo el sitio— y de ahí salían las
columnas `odd_*`, que son las que `odds_store` importa como fase «cierre». Pero
al medirlo, el problema no era sólo el 503:

    partidos posteriores al 2026-08-01     2.405
    sin precio                             1.225   (51 %)

Y la mayoría de esos 1.225 son de ligas que football-data **nunca** cubrió: la
Saudi, la Leagues Cup, la Libertadores, la Champions, Colombia, Perú, Ecuador,
Bolivia. Sin precio se puede medir si el modelo acierta, pero no si gana
dinero: el EV de esas competiciones no se liquida nunca.

La fuente estaba delante desde la v162. El `summary` de ESPN —el que
`stats_espn` ya descarga para cada partido, todos los días, sin un fallo— trae
`pickcenter` con la línea de una casa. Coste de red adicional: cero peticiones
nuevas por partido.

**Medido contra 60 cierres conocidos de LaLiga**, en probabilidad implícita:

                        football-data   ESPN/DraftKings   foto Playdoit
    sobreredondeo          1,0555           1,0482           1,1377
    error normalizado         —             0,0162           0,0234
    p90                       —             0,0343           0,0602
    mismo favorito            —             97 %                —
    cobertura                 —             60 de 60            —

ESPN trae **menos margen que la propia football-data**, o sea que es una línea
más ajustada que la referencia que se venía usando. Y la columna de la derecha
es la foto de Playdoit que la v189 descartó por tener un error del tamaño de la
señal: ESPN mejora un 30 % la media y un 43 % el p90.

Queda dicho lo que es y no se disfraza: la línea de UNA casa para un partido ya
jugado, no un cierre de consenso.

**Sólo rellena huecos.** Si football-data vuelve, su cierre manda y esto no pisa
nada. El emparejamiento va por fecha y marcador, no por nombre —football-data
escribe «Ath Bilbao» y ESPN «Athletic Club»—, y si dos partidos del mismo día
comparten marcador no se adivina: se deja vacío.

### 3. El bot de plantillas, por la misma puerta

`precalcular_rosters.yml` corre a diario desde hace meses y **no ha commiteado
nunca, ni una vez**. La última pasada se comió **1.130 errores 403**: ESPN
bloquea `/teams` y `/roster` desde IPs de centro de datos, y ese workflow
existía justamente para rodear ese bloqueo desde Streamlit Cloud. Ahora bloquea
también las de GitHub Actions. Como la caché no cambiaba, el paso de commit
decía «la caché no cambió» y todo terminaba en verde.

El mismo `summary` trae `rosters`: las dos alineaciones con sus jugadores, sus
identificadores y sus estadísticas del partido. Misma caché, mismo formato, por
una puerta que no está cerrada.

**Se fusiona, no se sustituye.** La caché lleva la temporada entera y esto es
una ventana de días: reemplazarla dejaría el panel de máximos goleadores
contando desde el lunes. Un equipo que no jugó esta semana conserva lo suyo.

Lo que NO se puede verificar desde una máquina de casa: qué endpoints bloquea
ESPN en el runner. Una IP residencial responde a todo. Lo único que se sabe con
certeza es que `summary` funciona allí, porque `stats_espn` lo usa a diario y
acierta — y por eso se construye sobre eso y sobre nada más.

### 4. Los widgets que se iban con los datos

Tercera vía de una avería con dos vías ya cerradas. Un widget que no llega vivo
al final de la pasada desaparece de `session_state`:

    st.empty() vaciando los slots     -> cerrada en la v177.2 (ocultar por CSS)
    st.rerun() cortando la pasada     -> cerrada en la v178
    creación condicionada por DATOS   -> ésta

`ev_extremo_tog` vivía dentro de `if extremo:` y `parlay_base` dentro de
`if _s1:`. Basta con que un «Actualizar ahora» devuelva un barrido sin picks de
EV extremo para que la clave se vaya. El smoke lo cazó con `KeyError:
ev_extremo_tog`; antes había cazado `KeyError: parlay_base`, que la v177.2 dio
por cerrado y que ya tiró la página una vez.

Se arregla como las vistas: el widget se queda **en el árbol** y lo que se
esconde es su contenedor, con la misma clase `st-key-…`.

### Lo que esta versión deja abierto

1. El modelo de respaldo por copa. Sigue siendo lo único del encargo original
   sin cerrar, y ahora molesta menos: esos partidos ya se ven con el precio de
   la casa en vez de esconderse.
2. El `.git` de 16 GB.
3. Las estadísticas de las plantillas se acumulan sobre la ventana que se
   recorre, no sobre la temporada. El que ya estaba conserva sus totales; el
   nuevo empieza en cero. Es correcto para saber QUIÉN está en el equipo, que
   es para lo que se usa, pero no reconstruye una temporada perdida.

---

## 5y. v191 — LA NFL ESTABA CONSTRUIDA Y MIRABA POR UNA RENDIJA DE DOS DÍAS

Encargo: que la NFL aparezca en las categorías y en Apuestas del Día, con
modelo propio, y con dos mercados —ganador y total de touchdowns—.

Lo primero que había que averiguar era cuánto de eso ya existía, y existía casi
todo: `nfl_datos.py`, `modelo_nfl.py` (estado rodante por equipo y dos
regresiones ridge) y la rama `_picks_nfl` enchufada al barrido desde la v131.
El modelo funciona: Rams-49ers de la jornada 1 sale con margen +5,71, total
53,2 y 66 % al local, con 59 y 61 partidos de historia por equipo.

Los datos también: **1.055 partidos, temporadas 2022-2026, 52 de playoffs**, 71
columnas de estadística avanzada por equipo y las cuotas de cierre dentro.

### 1. La rendija

    fixtures = nd.fixtures_nfl(dias=2)

Dos días es la ventana del fútbol, que juega a diario y con ella no pierde
nada. **La NFL juega el domingo.** Medido el jueves 2026-09-10, semana 1: ESPN
devolvía 15 partidos y el barrido evaluaba **uno**. Los catorce del domingo no
existían para la aplicación — ni en su pestaña ni en Apuestas del Día cuando
llegara su día, porque el precálculo tampoco los veía.

Con ocho días: **de 1 a 16 partidos**, todos con probabilidad del modelo y 15
con precio real.

### 2. Y el histórico llevaba cuatro semanas congelado

`historico_nfl.csv` sólo lo construía `construir_historico()` llamada **a
mano**. Se quedó en el **2026-08-14**: pretemporada. La temporada arrancó el 7
de septiembre y sus resultados no entraban, así que el modelo predecía la
jornada 1 con lo aprendido en febrero.

Es el mismo patrón que el ledger de la v189 y el bot de plantillas de la v190:
una pieza que alguien tenía que ejecutar y nadie ejecutaba. Ahora entra en
`retrain_leagues.yml` (diario) y en el vigilante de frescura. Actualizado:
**1.095 partidos, hasta hoy**.

### 3. Los touchdowns, del mismo `summary`

ESPN no publica el touchdown como estadística de equipo —el boxscore trae
`defensiveTouchdowns` y nada más— pero sí la lista de anotaciones, con su tipo
y su equipo. Se cuentan de ahí, sin una petición más, porque `resumen_partido`
ya descargaba ese `summary`.

Rellenados **1.095 de 1.095, cero fallos**, en 7,8 minutos. Y queda enganchado
a la ingesta: las filas nuevas los traen solas.

Comprobación de cordura: media 4,99 por partido, mediana 5, rango 0-12, y
correlación con los puntos de **0,934**. Un partido de 13-10 sale como 1-1
touchdowns, que cuadra exactamente (13 = 1 TD + 2 FG).

Y con la guarda de siempre: **sin lista de anotaciones no se devuelve cero**.
Un partido sin dato no es un partido sin touchdowns, y meter ceros hunde la
media de todo lo que se calcule encima.

### 4. El EV que había que NO publicar

Playdoit publica «Total de Touchdowns (incl. prórroga)» con líneas en 4,5, 5,5
y 6,5. La primera versión derivaba los touchdowns de NUESTRO total y salía
esto:

    Más de 4.5  EV +11 %     Más de 5.5  EV +26 %     Más de 6.5  EV +40 %

Tres líneas, tres veces «más», siempre el mismo lado. Un EV que apunta siempre
en la misma dirección no es una ventaja. Medido contra la línea de cierre, que
el histórico ya traía:

    error absoluto contra el total real:  modelo 10,58  ·  casa 10,30
    sesgo del modelo: +1,19 puntos de más, sistemático

**La casa acierta más que nosotros, y nosotros predecimos alto.** Ese EV era el
sesgo con otro nombre.

Anclado a la línea de PUNTOS de la casa en vez de a nuestro total:

                          nuestro total    línea de la casa
    correlación TD             0,165            0,328
    MAE                        1,649            1,612
    peor desvío de calibración 0,007            0,011

La correlación se duplica, y lo que se mide pasa a ser otra cosa más
defendible: si la línea de touchdowns de una casa es **coherente con su propia
línea de puntos**. Esa discrepancia es suya, no nuestra. Los números quedan
creíbles: +0,0 %, +5,1 % y +5,7 % en vez de +11, +26 y +40.

**Y no va a Capa 1.** No existe histórico de líneas de touchdowns con el que
liquidarlo, así que su percentil 5 no está medido y la regla de oro no se le
puede aplicar. Sale como información con su precio al lado, igual que los
córners antes de que hubiera fotos con las que medirlos.

Sobre la sigma, que es donde estaba la trampa: ajustar la recta sobre los
puntos REALES da un residuo de 0,73 y una calibración casi perfecta, y esa
cifra es mentira — a la hora de apostar no se conocen los puntos. Las dos
fuentes de error se suman en cuadratura y la sigma buena sale ~2,0, que
coincide con la medida fuera de muestra (2,002). Con ella el peor desvío entre
las líneas de 3,5 y 7,5 es de **0,011**.

### 5. Novibet: no entra, y el motivo no es técnico

Pedido en la misma tanda. No se puede, y ya estaba medido:

    Novibet-MX (API propia)  403  pagina de Cloudflare; hasta robots.txt da 403
    Altenar:novibet2         400  no corre sobre Altenar como Playdoit
    The Odds API (23 casas)  ---  no esta en su catalogo

La v114 lo sondeó y midió lo mismo. Comprobado otra vez desde una IP
residencial, que no está bloqueada por ser centro de datos: el bloqueo es a
todo acceso automático.

Playdoit funciona porque corre sobre **Altenar**, cuya API de widget es pública
y sin clave. Novibet tiene motor propio detrás de Cloudflare. Automatizarlo
exigiría un sistema que resuelva ese desafío anti-bot, y eso no se construye.

Las alternativas tampoco sirven y conviene dejarlo escrito para que nadie las
vuelva a proponer: The Odds API tiene Betano y Codere, pero son `betano_uk` y
`codere_it` —la operación británica y la italiana—, precios que el usuario no
puede tomar. Caliente no está.

### Lo que esta versión deja abierto

1. Fotografiar las líneas de touchdowns de Playdoit, como se hace con los
   córners desde la v159. Con unas semanas de fotos ese mercado se podría
   liquidar y dejaría de ser «sin p5 medido».
2. El modelo de NFL predice el total peor que la casa (10,58 contra 10,30).
   No es raro ni deshonroso, pero mientras siga así su total no debe usarse
   para apostar contra ella, sólo para describir el partido.
3. Sólo hay 847 partidos de temporada regular. Para la NFL son tres
   temporadas, y es poco: cada equipo aporta ~60 partidos.

---

## 5z. v192 — NOVIBET NO SE PUDO POR SU PUERTA, ASÍ QUE ENTRARON CINCO POR OTRA

Encargo: meter Novibet, en fútbol y en todos los deportes, automatizado.

### 1. Por su puerta no se entra, y no por falta de intentarlo

    Novibet-MX (API propia)   403   pagina de Cloudflare «Just a moment...»
                                    hasta robots.txt devuelve 403
    Altenar:novibet2          400   no corre sobre Altenar como Playdoit
    The Odds API (23 casas)   ---   no esta en su catalogo
    novibet.gr                200   pero es el armazon de una SPA, no JSON

La v114 ya lo había sondeado y midió lo mismo. Comprobado otra vez desde una IP
residencial —que no está bloqueada por ser centro de datos—: el bloqueo es a
**todo acceso automático, sin distinguir**.

Automatizarlo por ahí exigiría un sistema que resuelva el desafío anti-bot.
Eso no se construye, y la respuesta no cambia porque se insista.

### 2. Pero sus cuotas están publicadas en otro sitio

El comparador de **Flashscore** las publica, y responde 200 a una petición
normal de Python: sin navegador, sin resolver nada. Es la misma categoría que
el scraping de BetExplorer que el proyecto ya hacía.

Se encontró abriendo Flashscore en el navegador y leyendo **qué petición hace
su propia web** para pintar las cuotas:

    https://global.ds.lsapp.eu/odds/pq_graphql
        ?_hash=ope2&eventId=<id>&bookmakerId=632&betType=HOME_DRAW_AWAY

`632` es Novibet, y la lista de casas del propio Flashscore la marca con
`geo_ip: "MX"`: **precios mexicanos**, los que el usuario puede tomar.

### 3. Y por esa puerta no entra una casa: entran cinco

    Calientemx 631 · 1xBet 417 · Winpot 1113 · Novibet 632 · Sportium.mx 1041

Todas mexicanas. El proyecto tenía cinco casas en el consenso (Pinnacle,
Bovada, Unibet, Matchbook, Playdoit) y pasa a **diez**.

Eso no es un adorno: la dispersión entre casas es la **única señal que este
proyecto tiene medida con ROI positivo**, y con pocas casas apenas se ve.
Medido en Pumas-León de la Liga MX:

    1xBet        2.05     <- mejor precio al local
    Novibet      2.09
    Winpot       2.12  (= Pinnacle)
    Calientemx   2.16
    Sportium     2.16

Y el mejor precio del partido pasó de Playdoit (2,14) a **Sportium (2,16)**.

**Cobertura medida** sobre 211 partidos de fútbol barridos de verdad:

    1xBet 209 · Winpot 206 · Novibet 200 (95 %) · Caliente 179 · Sportium 177

Por deporte (12 partidos por deporte, 1.040 peticiones):

                  Caliente  1xBet  Winpot  Novibet  Sportium
    futbol          10/12   10/12   10/12   10/12     9/12
    tenis           11/12   12/12   12/12   12/12    11/12
    baloncesto       4/12    9/12    4/12   10/12     0/12
    americano        3/4     0/4     0/4     0/4      3/4
    beisbol          1/12   11/12    0/12    0/12    11/12

**Novibet no cotiza NFL ni MLB**, y eso hay que decirlo aunque el encargo
pidiera «todos los deportes»: es fuerte en fútbol, tenis y baloncesto —ahí es
la mejor de las cinco— y ausente en los otros dos. Los cubren Caliente, 1xBet
y Sportium. Las cinco juntas sí llegan a los cinco deportes.

Un regalo inesperado: el feed trae el **precio de apertura** junto al actual y
la dirección del movimiento. Ninguna de las casas que ya había lo publica, y es
materia prima directa para el CLV.

### 4. Lo que costó, que es la parte que se aprendió por las malas

Tres veces en la misma tanda se metió trabajo caro en el camino caliente. Las
tres las cazó la medición, ninguna la intuición.

**Primera: el tablero de touchdowns.** `mercados_playdoit` baja 600 mercados
por partido y se pedía para los 16 de la NFL: **+14,2 s por barrido**. El smoke
se quedó 33 minutos sin escribir y hubo que matarlo. Arreglado limitándolo a
los partidos a tres días o menos: **0,6 s**, y siguen apareciendo 13 de 16.

**Segunda: el emparejado difuso.** `cuotas_mx.buscar` comparaba cada nombre
contra los 1.900 del catálogo, dos veces por partido —«Pumas» contra equipos de
Kazajistán, 260 veces por barrido—:

    barrido CON casas mexicanas   114,8 s
    barrido SIN ellas              92,1 s
                                 --------
    coste                          22,7 s

Arreglado con un índice por palabra: lo difuso sólo se prueba contra los que
comparten alguna, de 1.900 candidatos a una veintena.

    por consulta:  0,0313 s -> 0,0003 s   (100x)
    barrido:       114,8 s  ->  86,3 s

Queda por debajo de la línea base sin las casas, o sea que **la aportación es
gratis**.

**Tercera** fue en la v190 y se cuenta allí: escribir 863 cuotas producía
325.130 líneas de diff.

### 5. Cómo queda montado

`barrer()` corre en `cuotas_mx.yml` **cada seis horas** y deja `cuotas_mx.json`;
la pantalla sólo lo lee. Seis horas y no un día porque son PRECIOS: el módulo
descarta el fichero si tiene más de ocho, y con una pasada diaria estaría
caducado dos tercios del tiempo.

El barrido está paralelizado a ocho hilos —**381 s → 97 s** para las mismas
1.830 peticiones— y ocho es cortesía, no una carrera: la medición dio 0,19 s
por petición sin ningún límite de ritmo, y no hace falta averiguar dónde está
el límite para que nos lo pongan.

### Lo que esta versión deja abierto

1. Los mercados de totales y hándicap de estas casas se recogen pero **no se
   usan todavía**: sólo entra el 1X2 al consenso. Enchufar los otros dos es
   trabajo directo y con datos ya en el fichero.
2. El precio de apertura se guarda y **nadie lo lee aún**. Es la pieza que
   permitiría medir CLV contra el movimiento real de cinco casas en vez de
   contra un cierre que football-data ya no publica.
3. El barrido tarda 16 minutos si no se le pone tope. Con `--max 400` baja a
   unos 6, y habría que medir si 400 deja fuera ligas que importan.

---

## 6a. v193 — «SIN APUESTAS JUGABLES» CUANDO LO QUE PASABA ES QUE NO SE MIRABA

Tres cosas de un mismo encargo.

### 1. Dos casas prioritarias, y eso cambia el EV

El usuario apuesta en **Playdoit y en Novibet**. `CASA_PRIORITARIA` era una sola
cadena, y no es un detalle de presentación: `preferida` es el precio que el
sistema considera TOMABLE, y de ahí sale el EV que decide si una apuesta entra
en la Sección 1.

Con una sola casa se calculaba el EV con el peor de los dos precios y se
perdían apuestas jugables en la otra cuenta. Medido en Pumas-León:

    visitante:  Playdoit 3,20  ·  Novibet 3,35   ->  ahora toma Novibet

Ahora `preferida` toma el mejor de las dos y dice cuál es. `CASA_PRIORITARIA`
se conserva apuntando a la primera, porque hay código y tests que la leen.

### 2. Los deportes sin empate no proponían NADA

Reportado con dos capturas:

    Los Angeles Rams vs San Francisco 49ers
    🚫 Sin apuestas jugables — ninguna apuesta llega al valor minimo

    Dabin Kim vs Seo Yun Choi
    🚫 Sin apuestas jugables

El primero con el modelo dando **68,6 %** al local y la casa pagando **1,5155**.
El segundo con un **84,5 %** y precio publicado.

**No era que no llegaran al mínimo: es que nunca se evaluaban.**
`modo_modelo.probabilidades_1x2` exige las TRES selecciones y devuelve `None`
cuando no hay empate, así que `valor_apuesta._de_resultado` no producía ni una
fila para NFL, tenis, MLB ni NBA. El mensaje decía «ninguna llega al mínimo»
cuando la verdad era «no se miró ninguna».

Se añade `_de_dos_vias`, que construye la candidata de cada lado con la cuota
de la casa y la implícita devigada a DOS vías —no a tres: sus dos selecciones
suman 1, no 2—. Y las ramas de NFL y tenis publican ahora las cuotas de los dos
lados, no sólo la del favorito.

    NFL:    0 -> 15 de 15 partidos con candidatas
    Tenis:  0 -> 119 de 119

    Dabin Kim vs Seo Yun Choi  ->  Gana Dabin Kim · 70,7 % · cuota 1,376

**NO SE BAJÓ NINGÚN UMBRAL.** Las candidatas pasan por el mismo filtro de
siempre, con la probabilidad encogida hacia el mercado igual que en el fútbol
—en la NFL, 0,589 crudo pasa a 0,6325 calibrado—. Lo que cambió es que ahora
hay algo que filtrar.

Y no se mete donde no toca: un partido CON empate sigue yendo por
`_de_resultado`, y el test lo fija.

### 3. El workflow de cuotas, corriendo en el runner

Lanzado a mano para comprobar que funciona fuera de una máquina de casa:

    540 partidos con cuota · 15.215 peticiones en 410 s
    Novibet en 424 partidos
    commit a82602c

### Lo que esta versión deja abierto

1. **Tenis: primer set y total de sets.** Se pidieron y no se pueden dar: el
   histórico guarda el resultado del partido, no el marcador por sets. ESPN
   publica el detalle, así que es trabajo de ingesta —como fue el de los
   touchdowns— y no de modelo. Inventar una probabilidad sobre sets sin ese
   dato sería exactamente lo que este proyecto no hace.
2. Al tomar el mejor precio de las dos casas, algunas apuestas que antes no
   llegaban al mínimo ahora sí van a llegar. No es que baje el listón: es que
   el precio real que el usuario puede tomar es mejor de lo que el sistema
   creía.
