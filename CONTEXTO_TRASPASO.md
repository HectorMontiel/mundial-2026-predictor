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
2. El smoke completo quedó sin veredicto: `smoke_botones.py` muere con
   `RecursionError` dentro de `streamlit.testing.element_tree` al recorrer el
   árbol. Sospecha razonable: los ~60 `st.expander` que la v167 añadió (uno por
   tarjeta) anidados en `st.container`. `valida_render.py` sí pasa. Medir si es
   el expander y, si lo es, plegar el análisis de otra forma.
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
2. El backtest de eficacia (`_v169_goles_y_eficacia.py`) NO se ha vuelto a
   correr con la política del Score: sus cifras son de la v170. Hay que
   añadirle una `_politica_v171` antes de citar números de eficacia.
3. Remates y remates a puerta casi no tienen precio (3/22). Merece decidir si
   se siguen enseñando como Mercado Rey cuando no se pueden jugar.
4. El smoke completo sigue sin veredicto por el `RecursionError` de
   `streamlit.testing` (§20, pendiente 2).
