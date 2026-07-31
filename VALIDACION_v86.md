# VALIDACIÓN v86 — La app se caía con dos usuarios, y el modelo no responde al ELO

Fecha: 2026-07-31 · Remotos: `origin` (HMREY) + `upstream` (HectorMontiel)

---

## 1. Por qué se caía la app cuando entraba una segunda persona

Era lo más grave y no era un misterio: es una cadena de tres fallos que se
suman, y todos se han medido.

### 1.1 El caché de datos NO es por sesión, y se borraba por visitante

`dashboard_ui.py` ejecutaba en cada sesión nueva:

```python
st.cache_data.clear()
for _mod in (...13 módulos...): importlib.reload(...)
```

`st.cache_data` es del **proceso**, no de la sesión. Así que cada visitante
nuevo le borraba el caché a todos los que ya estaban dentro.

Y hay un detalle que lo convierte de "ineficiente" en "letal". Streamlit ya
impide que dos sesiones calculen la misma clave a la vez, con un cerrojo por
clave — pero `clear()` **borra también ese diccionario de cerrojos**:

```
.venv/Lib/site-packages/streamlit/runtime/caching/cache_utils.py
  162    with self._value_locks_lock:
  164        self._value_locks.clear()
```

Es decir: entrar en la app desactivaba justo la protección que evitaba el
trabajo duplicado. Y el trabajo duplicado es el barrido de `alpha_finder`.
Medido sobre el barrido real (`_v86_barrido_concurrente.py`):

| | pico de RSS | duración |
|---|---|---|
| 1 barrido | **1.297,7 MB** | 95,8 s |
| 2 barridos simultáneos | **2.172,2 MB** | 91,5 s |

Ésa es la secuencia completa: usuario 1 barre → usuario 2 entra y borra el
caché y los cerrojos → los dos barren a la vez → 2,2 GB → el contenedor muere
y se les cae **a los dos**.

### 1.2 El caché de motores de liga no tenía techo

`cargar_motor_liga` está indexado **por liga** y hay 56 disponibles, sin
`max_entries`. Cada liga que alguien abriera quedaba residente para siempre
(`_v86_memoria.py`):

| | |
|---|---|
| coste medio por motor de liga | **59,0 MB** |
| RSS con 12 ligas cargadas | 847,8 MB |
| proyección a las 56 ligas | **3.445,3 MB** |

Con un usuario el techo se alcanza despacio; con dos navegando ligas distintas,
al doble de velocidad.

Antes de poner el tope se comprobó que sirviera de algo: `_v86_liberacion.py`
confirma que al desalojar se recupera el **71,1 %** del pico y que **0 de 8**
motores quedan retenidos (el resto es fragmentación del asignador, no fugas).

### 1.3 El coste fijo ya era alto de partida

`_v86_huella_total.py`, midiendo todo lo que vive en `cache_resource`:

| objeto | RSS acumulado | coste |
|---|---|---|
| streamlit importado | 62,1 MB | +47,4 |
| **motor Mundial** | 505,8 MB | **+443,7** |
| motor MLB | 540,6 MB | +34,8 |
| motor NBA | 555,0 MB | +14,4 |
| tenis ATP + WTA | 625,3 MB | +70,3 |

Los 443,7 MB del motor del Mundial son casi todos **basura del asignador**, no
datos: `modelo_tda.joblib` ocupa 62,6 MB en disco, dispara el RSS a 493 MB y
sólo deja **74,9 MB de objetos vivos** (`_v86_perfil_artefactos.py`). En Linux
se recuperarían con `malloc_trim(0)`, pero **no se ha desplegado**: esta máquina
es Windows y no hay WSL ni Docker para medirlo, y no se sube lo que no se puede
comprobar.

### 1.4 Escrituras no atómicas

`prediction_api._monitor_cambios` hacía lectura-modificación-escritura de
`predicciones_log.json` en **cada predicción**, con `open(ruta, 'w')` — que
trunca el archivo a cero antes de escribir nada. Con 6 hebras
(`_v86_verifica_concurrencia.py`):

| método | lecturas corruptas de 360 |
|---|---|
| `open('w')` directo (v85) | **124 (34,4 %)** |
| temporal + `os.replace` (v86) | **0 (0,0 %)** |

El `try/except` de fuera evitaba la caída, pero el archivo quedaba corrupto y
el monitor de deriva dejaba de funcionar en silencio para todo el mundo.

### 1.5 Lo que se ha cambiado

| cambio | efecto medido |
|---|---|
| El refresco de arranque pasa a `@st.cache_resource` | se ejecuta **una vez por proceso**, no por visitante |
| `max_entries=6` en `cargar_motor_liga` | RSS se estabiliza en ~700 MB en vez de proyectar 3.445 MB; deriva +9,4 MB en 8 ligas extra |
| `guardia_barrido.py` (doble comprobación con cerrojo) | 5 sesiones simultáneas → **1 solo barrido**; ni forzando hay dos a la vez |
| El botón «Actualizar ahora» ya no hace `clear()` global | un usuario no le borra el caché a los demás |
| `io_atomico.py` + techo del log de deriva | 34,4 % → **0 %** de lecturas corruptas |

También se quitó `importlib.reload` del camino por-visitante. Estaba dejando
huérfanos los objetos cacheados: tras la recarga, el `ClubEngine` que guarda
`cache_resource` **deja de ser instancia** de `league_engine.ClubEngine`
(`isinstance` → `False`, verificado en `_v86_repro_concurrencia.py`). El
propósito original —que un despliegue se vea sin reiniciar— se conserva, porque
Streamlit Cloud reinicia el contenedor en cada push y el bloque sigue
ejecutándose al arrancar.

Regresión permanente: **`test_concurrencia.py`**, que reproduce el escenario de
dos usuarios y falla si vuelve a aparecer.

---

## 2. Puebla contra Chivas: el usuario tenía razón, pero por otro motivo

### 2.1 Tres mediciones, y sólo la tercera vale

**(a) v85, correlación sobre emparejamientos sintéticos** — 32 ligas "rotas",
4 invertidas. **Es un artefacto.** La auditoría cruzaba a los 14 mejores
equipos de cada liga entre sí: al quedarse con los 14 mejores se **comprime el
rango de ELO** mientras la forma sigue variando a rango completo, así que la
correlación acaba midiendo la forma. Y son partidos inventados con el estado de
hoy, fuera de la nube en la que se entrenó el modelo.

**(b) v86, correlación sobre el ledger real** (`_v86_monotonia_real.py`) —
47.948 partidos fuera de muestra. Mediana rho **+0,7639**, **ninguna** liga
invertida, 55 de 56 sanas. Las cuatro "invertidas" de v85 salen así:

| liga | rho sintético (v85) | rho real (v86) | n |
|---|---|---|---|
| china | −0,288 | **+0,8087** | 906 |
| sudamericana | −0,283 | **+0,6082** | 238 |
| ita_serie_b | −0,206 | **+0,5505** | 903 |
| eng_league_two | −0,171 | **+0,8274** | 1.335 |

Pero esta medición **también engaña**, al revés: en partidos reales el ELO va
correlacionado con la forma y los goles, así que P(local) parece seguir al ELO
aunque el modelo no lo esté usando.

**(c) v86, DEPENDENCIA PARCIAL** (`_v86_dependencia_elo.py`) — se llama al
camino real (`ClubEngine.predecir`) moviendo **sólo** el ELO del local y
congelando todo lo demás. Es causal dentro del modelo y no la falsea ni el
rango ni la colinealidad:

| | |
|---|---|
| subir **600 puntos** de ELO mueve P(local) | **+0,0751 de mediana** |
| ligas planas (\|salto\| ≤ 0,02) | **15** |
| ligas invertidas | **2** |
| **liga_mx** | **+0,0173** ← el caso Puebla |

O sea: el modelo apenas responde a la fuerza de los equipos. **El usuario tenía
razón**, aunque el diagnóstico de v85 estuviera mal montado.

### 2.2 La corrección, medida en la población correcta

v85 dejó pendiente lo importante: medir con un prior de **ELO** sobre las fichas
**sin ancla de mercado**. Ahora el ledger lleva el ELO de cada partido
(`elo_por_partido.csv`, 95.950 partidos, **cobertura del 100 %**).

Sobre las **9.870 fichas sin mercado**, eligiendo `w` en los pliegues 1-2 y
validando en los 3-4:

| | elección ll | elección ECE | **VALIDACIÓN ll** | **VALIDACIÓN ECE** | precisión |
|---|---|---|---|---|---|
| w=1,00 (antes) | 1,04189 | 0,0111 | 1,04769 | 0,0106 | 0,4771 |
| **w=0,90 (v86)** | 1,03692 | 0,0090 | **1,03789** | **0,0045** | 0,4797 |

**El ECE baja un 58 %.** Se elige por ECE y no por log-loss a propósito: la
ficha *muestra* una probabilidad, así que lo que importa es que ese número sea
fiel. El máximo del barrido era w=0,50, que da mejor log-loss en validación
(1,03022) pero **peor ECE** (0,0090) — la trampa de quedarse con el extremo de
la rejilla, que este proyecto ya ha pagado tres veces.

Cordura: el prior de ELO **solo** da log-loss 1,02522 frente a 1,03079 del
modelo completo. Una logística de una sola variable bate al ensemble, que es
otra forma de ver el mismo sobreajuste a la forma reciente.

### 2.3 Efecto sobre la monotonía

Repitiendo la dependencia parcial en las 17 ligas peores
(`_v86_verifica_puebla.py`):

| | antes | después |
|---|---|---|
| salto mediano | +0,0097 | **+0,0655** |
| ligas planas (≤0,02) | 13 de 17 | **0** |
| ligas con salto negativo | 6 | **0** |

### 2.4 El partido concreto: honestidad

| | Puebla | Empate | Chivas |
|---|---|---|---|
| antes | **53,6 %** | 24,8 % | 21,6 % |
| después | **50,0 %** | 25,0 % | 24,9 % |

Y el espejo (el fuerte en su propio campo):

| | Puebla en casa | Chivas en casa | brecha |
|---|---|---|---|
| antes | 53,6 % | 47,1 % | 6,5 pp al revés |
| después | 50,0 % | 49,6 % | **0,4 pp** |

**Puebla sigue apareciendo como favorito.** No se disimula: w=0,90 mueve 3,6
puntos y este partido necesitaba más. Se probó un `w` por liga (más
encogimiento donde el modelo ignora más el ELO) y **se rechazó**: de las 9.870
fichas sin mercado, sólo **20** caen en ligas planas, así que la supuesta
mejora (ECE 0,0038 frente a 0,0045) se apoya en 20 filas. Es ruido, y adoptarlo
sería repetir el error que este documento denuncia dos secciones más arriba.

Lo que hace falta para cerrarlo del todo: histórico de cuotas de Liga MX para
tener fichas sin mercado en cantidad suficiente y poder medir su `w` de verdad.

### 2.5 Dónde se aplica y dónde no

Sólo en la ficha. `alpha_finder` pasa `prior_elo=False` en sus dos barridos de
fútbol, así que **los picks de Capa 1 y Capa 2 salen idénticos a v85**. Cuando
hay mercado, la corrección buena sigue siendo la de `calibracion_mercado`.

---

## 3. Tenis: el saneamiento del ATP no era la llave (y qué sí lo era)

### 3.1 Lo que se buscaba

El Odd_Max del ATP tenía media +26,45 % contra mediana +1,72 %. Caracterizado
(`_v86_atp_outliers.py`), la contaminación está concentrada:

| año | mejora mediana | mejora **media** |
|---|---|---|
| 2015 | 3,85 % | **+140,36 %** |
| 2016 | 3,52 % | **+360,25 %** |
| 2017-2026 | 2,3-5,8 % | 3,5-7,9 % |

Máximo absoluto: **+892.688 %** — una cuota de 42.586.

### 3.2 Se saneó, y el ATP sigue sin edge

Con tres filtros estructurales (Odd_Max ≥ Pinnacle, overround ≥ 0,95, ratio
≤ 1,5), quedándose con el 96,03 % de las filas:

| | antes | saneado |
|---|---|---|
| ATP | sin edge (0/15 configs) | **sin edge (0/15 configs)** |
| WTA | EDGE (2/15) | **EDGE (2/15)** |

**La hipótesis era falsa**: los outliers no tapaban ningún edge del ATP. Todas
las configuraciones se hunden fuera de muestra igual con datos limpios.

Sí se obtuvo un control valioso: **el edge de la WTA, que está desplegado, NO
dependía de las filas corruptas** — con datos saneados la validación fuera de
muestra incluso mejora (p5 +0,57 % → **+0,84 %**).

### 3.3 El hallazgo que sí importaba

`valor_vs_sharp` **no comprobaba que la cuota fuese un precio posible**.
Calculaba el EV y, si superaba el umbral, el pick entraba en la Capa 1 — y la
lista va ordenada por EV descendente, así que un dato corrupto se coloca
**arriba del todo**.

Cuánto pesa eso (`_v86_filtros_uno_a_uno.py`), sobre los picks reales:

| WTA, filtro | n | ROI | p5 | bloquea |
|---|---|---|---|---|
| sin filtro | 10.345 | +4,57 % | +2,13 % | — |
| ratio ≤ 3,0 | 10.343 | +3,37 % | +1,55 % | **2 (0,02 %)** |

**Quitar DOS apuestas de 10.345 cambia el ROI en 1,2 puntos.** Una sola, a
**100× el precio de Pinnacle**, aporta el 26 % del titular de +4,57 %. Es dinero
que nadie pudo cobrar jamás.

Y la prueba de que el mecanismo del canal es el precio y no la selección
(`_v86_es_real_ese_roi.py`):

| grupo | acierto real | acierto que implica Pinnacle | z |
|---|---|---|---|
| WTA sanos | 51,31 % | 51,40 % | −0,16 |
| WTA imposibles | 52,95 % | 53,90 % | −0,48 |
| ATP imposibles | 55,91 % | 54,21 % | +0,81 |

**Ningún grupo gana más veces de lo que Pinnacle implica.** Pagando al precio
de Pinnacle el ROI es negativo (WTA sanos −3,34 %). El edge de `valor_vs_sharp`
es *cobrar mejor*, exactamente como está diseñado — y por eso un precio falso
lo falsifica entero.

### 3.4 Lo que se despliega y lo que NO

**Se despliega** el techo `RATIO_MAX_SOBRE_SHARP = 2.0`: bloquea entre el
0,02 % y el 0,23 % de los picks. El corte es de principio, no de barrido —
doblar el precio del sharp implica un EV de más del 100 %, que no existe en un
mercado de dos vías. Se midieron 1,5 · 2,0 · 2,5 · 3,0 y dan prácticamente lo
mismo, así que el valor concreto **no está ajustado a los datos**.

**NO se despliega** el filtro de overround < 0,95, aunque estaba en el saneado
del histórico: bloquea entre el 3,6 % y el 4,8 % de los picks y cuesta hasta
1,54 puntos de ROI. Un overround bajo es justo lo que el line shopping busca
—dos casas discrepando— y no una señal de dato corrupto. Meterlo en el mismo
saco que el detector de corrupción era elegir el corte más agresivo sin
justificarlo.

Nota de honestidad: el guardia **baja** el ROI del backtest (WTA +4,57 % →
+3,37 %). No es un coste real: es que el número anterior estaba inflado por
precios inexistentes. Lo que sube es la fidelidad de la cifra.

---

## 4. Estado de las tareas abiertas

| tarea | estado |
|---|---|
| Caída con dos usuarios | **RESUELTA** y con prueba de regresión |
| Monotonía / caso Puebla | **CORREGIDA** (ECE −58 %, 13 ligas planas → 0); el partido concreto mejora pero no cambia de favorito, y se explica por qué |
| Saneamiento del ATP | **CERRADA en negativo**: no era la llave. En su lugar se desplegó el guardia de precio, que sí protege picks reales |
| Monitorización producción-vs-backtest | pendiente |
| Calibración de hándicap/totales | ver sección 5 |

---

## 5. Calibración de totales y BTTS: el número real, y lo que revela

### 5.1 El sustrato que faltaba

`build_ledger_totales.py` construye P(over 1.5/2.5/3.5) y P(BTTS) **fuera de
muestra** para 47.794 partidos. No reentrena los clasificadores 1X2 —los
mercados de goles no salen de ahí— sino sólo los dos regresores de Poisson, con
el mismo esquema de pliegues cronológicos y paridad exacta con la cadena de
`ClubEngine.predecir` (clip 0,2-3,8 → `encoger_lambdas` → cola de Poisson).

Cordura del ledger:

| mercado | tasa real | predicho medio | sesgo |
|---|---|---|---|
| over 1.5 | 0,733 | 0,713 | −0,019 |
| over 2.5 | 0,495 | 0,478 | −0,016 |
| over 3.5 | 0,274 | 0,279 | +0,004 |
| BTTS | 0,520 | 0,480 | −0,040 |

### 5.2 Goles: bien calibrado, sobreconfiado en la cola

| banda | n | modelo | acierto real | sesgo |
|---|---|---|---|---|
| 0,50-0,55 | 18.629 | 52,5 % | 51,6 % | +0,9 % |
| 0,60-0,65 | 18.857 | 62,5 % | 60,3 % | +2,2 % |
| 0,70-0,75 | 18.306 | 72,5 % | 68,2 % | +4,3 % |
| **≥ 0,75** | 49.664 | **83,1 %** | **74,5 %** | **+8,6 %** |

### 5.3 BTTS: es una moneda al aire vendida como confianza

| banda | n | modelo | acierto real | sesgo |
|---|---|---|---|---|
| 0,50-0,55 | 13.625 | 52,5 % | 51,4 % | +1,1 % |
| 0,60-0,65 | 9.236 | 62,3 % | 53,2 % | +9,2 % |
| 0,70-0,75 | 3.559 | 72,3 % | 54,8 % | **+17,5 %** |
| **≥ 0,75** | 3.289 | **80,6 %** | **53,2 %** | **+27,4 %** |

**El acierto es PLANO entre el 51 % y el 55 % diga lo que diga el modelo.** Es
la confirmación medida de lo que la v75 sospechaba por otra vía. A partir de
ahora, un pick de BTTS que el modelo pone al 80 % se muestra al **53 %**.

### 5.4 Y de paso: el histórico ya no puede inflar

Al añadir el intervalo bootstrap del acierto salió un problema que llevaba
tiempo ahí. La banda de 1X2 0,70-0,75 dice que se acierta el **81,8 %** frente
al 71,3 % del modelo — o sea que corregía hacia **arriba**. Pero tiene **n=33**
y su intervalo del 90 % es **[69,7 %, 90,9 %]**: veintiún puntos de ancho.

Todas las demás bandas con muestra decente van en la dirección contraria
(sesgo +0,2 % · 0,0 % · +0,9 % · +4,8 % en 1X2; hasta +8,6 % en Goles; hasta
+27,4 % en BTTS). El fenómeno medido es la sobreconfianza; la única banda que
parece rendir de más es justo la de 33 casos.

`probabilidad_real` devuelve ahora `min(modelo, histórico)`. Subir una
probabilidad mostrada apoyándose en 33 partidos es el único de los dos errores
posibles que no tiene ninguna ventaja para el usuario.

### 5.5 Qué sigue sin medición

El **hándicap asiático**. No hay ledger para ese mercado y se sigue diciendo que
no lo hay, en vez de prestarle el número de Goles. Construirlo requiere
histórico de líneas asiáticas, que hoy no está en `odds_historico.db`.

---

## 6. Resumen de lo desplegado

| cambio | justificación medida |
|---|---|
| Refresco de arranque una vez por proceso | quitaba el caché y los cerrojos a los demás usuarios |
| `max_entries=6` en el caché de ligas | 59,0 MB por liga · proyección de 3.445 MB a 56 ligas |
| `guardia_barrido.py` | 1 barrido pica 1.297,7 MB; dos a la vez, 2.172,2 MB |
| `io_atomico.py` + techo del log de deriva | 34,4 % → 0 % de lecturas corruptas |
| Prior de ELO en la ficha (w=0,90) | ECE 0,0106 → 0,0045 en validación; 13 ligas planas → 0 |
| `RATIO_MAX_SOBRE_SHARP = 2.0` | una apuesta a 100× Pinnacle aportaba el 26 % del ROI de la WTA |
| Bandas de Goles y BTTS | el BTTS al 80 % acierta el 53,2 % |
| La corrección histórica no infla | la banda que subía tenía n=33 e IC de 21 puntos |

| **rechazado** | **por qué** |
|---|---|
| `malloc_trim` para los 417 MB huérfanos | no hay Linux aquí para medirlo |
| `w` de encogimiento por liga | sólo 20 de 9.870 fichas caen en ligas planas |
| Filtro de overround < 0,95 | bloquea 3,6-4,8 % de picks y cuesta 1,54 pp de ROI: es line shopping legítimo |
| Saneamiento del ATP como llave de la Capa 1 | 0/15 configuraciones robustas antes y después |

Pruebas: `test_catalogo_y_cuotas.py`, `test_simetria.py`,
`test_match_parlay.py`, `smoke_botones.py` y el nuevo `test_concurrencia.py` —
las cinco en verde.
