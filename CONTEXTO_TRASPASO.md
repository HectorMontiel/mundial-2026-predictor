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
