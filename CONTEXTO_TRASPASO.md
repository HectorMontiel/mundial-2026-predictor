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

## 5. PENDIENTE

1. **Vigilar el PRIMER pase del bot con la v148.** Es el que publica los ~57 assets
   del Release y, si eso verifica, retira `modelos/` del índice. Comprobar en Actions:
   paso «Publicar los modelos como assets del Release» en verde y paso «Dejar de
   versionar los pesos» ejecutado. Si la publicación falla, la transición NO corre
   y todo sigue como antes (es el diseño).
2. **Los 15 GB de `.git` YA ESCRITOS siguen ahí.** La v148 detiene el crecimiento
   (~650 MB/día → los KB de `team_stats_*.json` e `historico_*.csv`). Encogerlos exige
   reescribir historia: destructivo, rompe todos los clones y **ni siquiera libera
   espacio en GitHub sin abrir ticket con su soporte**. Riesgo alto, beneficio incierto.
   Para un clon ligero HOY: `git clone --depth 1 --single-branch`.
3. **Vigilar el tiempo del workflow.** Añade ~57 subidas de asset (~880 MB) y quita
   ~57 peticiones a ESPN. Si se acerca a los 60 min, la optimización obvia es no
   re-subir el asset de una liga cuyos ficheros no han cambiado.
2. **Vigilar bot de esta noche**: 226 ficheros en vez de 89, CSVs 3-5× más grandes, timeout 60 min.
3. **Primera ejecución del workflow de rosters** (04:30 UTC).
4. **No probado end-to-end**: liga `main` de 9 temporadas (probé Premier 16 y liga_mx `new`).
5. **Córners**: validar el nivel del modelo con lambdas de producción → entonces semáforo y recomendaciones.
6. **Ingestor OpenLigaDB** para 3.Liga alemana (endpoint verificado, ~1.900 partidos sin huecos).
7. Mapeo de nombres: ~39 sin mapear. Medir cuántos se descartan vs cuántos casan MAL.
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
