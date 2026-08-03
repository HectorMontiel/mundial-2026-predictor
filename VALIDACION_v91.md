# VALIDACION v91 — Un solo reloj, un solo día, y la app deja de mentir

Fecha: 2026-08-03 · Suites: test_catalogo_y_cuotas ✅ · test_simetria ✅ ·
test_match_parlay ✅ · smoke_botones ✅ · test_concurrencia ✅ (TODO OK las 5)

Ocho síntomas reportados, todos cerrados. Dos tenían la misma causa raíz —una
que llevaba escondida desde siempre porque en Streamlit Cloud es invisible.

---

## 1. LA CAUSA RAÍZ: había dos relojes

Al acotar el barrido al día calendario apareció `partidos evaluados: 0` con
12 partidos disponibles. El motivo:

```
pd.Timestamp.today()  (local) → 2026-08-02
pd.Timestamp.utcnow()          → 2026-08-03
```

`fixtures_espn` pedía a ESPN el rango desde la fecha LOCAL, y las fechas que
ESPN devuelve son UTC. Convivían los dos relojes según el punto del código. En
Streamlit Cloud el servidor va en UTC y coincidían, así que **el bug era
invisible en producción y sólo se manifestaba al desarrollar** — pero estaba
ahí, y cualquier despliegue en un huso distinto lo habría destapado.

Arreglado con `alpha_finder.hoy_utc()` como única fuente de verdad, usada en
todo el barrido, y anclando en UTC el rango que se le pide a ESPN. El test de
regresión `test_un_solo_reloj` recorre el ÁRBOL del módulo buscando llamadas a
`.today()` — y encontró **dos que se me habían escapado** (la ventana de
temporada de la NBA y las oleadas), que también se corrigieron. Ese es
exactamente el trabajo que tiene que hacer un test.

## 2. «Apuestas del Día» es el DÍA, y punto

Tercer intento, y esta vez es el que pidió el usuario:

| versión | criterio | por qué falló |
|---|---|---|
| v88 | próximas 24 h (rolling) | a las 20:00 metía partidos de mañana |
| v89 | semana entera etiquetada | mezclaba picks del sábado con los de hoy |
| **v91** | **día calendario (00:00–23:59)** | — |

Medido: el barrido pasa de **227 partidos de 7 días a 11 del día**, y de
**102 s a 34 s**. La semana completa vive ahora donde el usuario la pidió: en
la vista de cada liga.

## 3. Las secciones ya no esperan a las combinadas

**Síntoma**: «no me abre Máxima Confianza, EV y las demás hasta que clickee en
Combinadas del día».

**Causa**: Streamlit ejecuta el script de arriba abajo, y las dos secciones de
combinadas —que cargan motores de liga y corren Monte Carlo— estaban ANTES de
las pestañas. Todo lo importante esperaba a que terminaran; el click forzaba
un rerun con los cachés ya calientes, y por eso «funcionaba al clickear».

**Arreglo**: las combinadas se mueven al FINAL de la página. Cuestan lo mismo
pero ya no retrasan nada.

## 4. El stack de Streamlit en la vista MLB

`st.selectbox(..., index=1, key='mlb_a')` creaba el widget con un default
mientras `selector_proximos` escribe esa misma clave por Session State API:
Streamlit lo avisa con un stack de 30 líneas. Arreglado sembrando el valor
en `session_state` ANTES de crear el widget, sin `index=`. Mismo patrón
aplicado a la NBA (idéntico problema, aún sin reportar).

## 5. Fuera el camino muerto de la API de cuotas retirada

El aviso «Sin captura de cuotas propia (The Odds API caída…)» salía porque
`apuestas_del_dia` seguía intentando leer `odds_actuales.json` — el volcado de
la API dada de baja en la v88. En producción ese fichero no existe, así que
**ese bucle entero llevaba meses sin ejecutarse**: todo lo que se ve sale del
pase de fixtures.

Retirado el bucle y sus cuatro satélites sin otro llamador
(`_mapa_equipo_liga`, `_liga_fuzzy`, `_senales_shadow`, `_filtro_evc`), más
`HORIZONTE_HORAS` y la bandera `sin_captura_odds` que consumía Telegram. El
test lo fija recorriendo el AST y comprobando que **ninguna cadena viva**
—excluyendo comentarios y docstrings, que sí deben explicar por qué se retiró—
menciona esa API.

## 6. Incidencias → «Estado del sistema», en verde

De seis avisos que parecían fallos, **ninguno lo era**. Se les da severidad en
el origen:

- ✅ **operativo**: la línea de MLB pasa a ser un resumen único
  («8 partidos con cuota, 8 evaluados, 8 comparados contra Pinnacle → 0 picks»)
  en vez de cuatro mensajes solapados.
- ℹ️ **contexto**: que Playdoit no cotice una liga chica cubierta por
  Pinnacle/Bovada, o que no haya combinada cruzada hoy.
- ⚠️ **problema real**: sólo lo que de verdad falla.

Y el filtro anti-CPBL de la v88 (descartar LMB/NPB/KBO/Taiwán/Triple-A) **deja
de reportarse como incidencia**: es el guardarraíl trabajando, no un fallo.
Baja al log. Resultado medido hoy: **3 líneas, 0 problemas**, titular en verde.

## 7. Máxima Confianza, por fin multi-deporte

**Causa medida**: los favoritos claros de tenis y MLB (82-88 % a cuota
1,08-1,15) viven en la **capa 2** —no pasan los filtros de élite justamente
por la cuota corta— y la capa 2 no entraba en el universo de esa pestaña.
Además la MLB devolvía `capa2: []` por construcción: sus 8 partidos evaluados
al día se descartaban dentro del motor.

Dos arreglos: la capa 2 entra al universo, y el motor de MLB expone su
`confianza`. El piso de cuota baja de 1,50 a 1,05 **sólo en esta pestaña** —el
1,50 es un guardarraíl de apuesta simple (v71) y aquí lo que se prioriza es
acertar, con el acierto real por banda y la bandera `ev_negativo` diciendo la
verdad. Medido: de **{Fútbol: 19}** a **{Fútbol: 7, Tenis: 7}** con la MLB ya
fluyendo (hoy su favorito no llega al umbral, lo cual es honesto).

## 8. Los partidos sin modelo ya tienen tarjeta

Los 22 nombres en crudo («Duncan Chan vs Thiago Agustin Tirante»…) eran
partidos de challenger/ITF con **precio real** cuyos jugadores no están en el
catálogo. Ahora salen como tarjeta con su cuota y la probabilidad implícita
del precio (devigada), etiquetados 🏷️ «sin predicción propia». Medido hoy:
**45 tarjetas** donde antes había una lista inútil.

## 9. Vistas por liga: la semana entera, ordenada

El selector escondía los partidos sin cuota (v72). Ahora muestra la semana
completa ordenada por fecha —el más próximo primero— y marca «· sin cuota aún»
lo que no cotiza todavía, en vez de hacerlo desaparecer. Aplicado a la vez a
las ligas de fútbol y a `selector_proximos` (MLB/NBA), que es el mismo
componente: una solución, todos los deportes.

## 10. Qué queda para la v92

- Panel de monitorización producción-vs-backtest de los canales
  `valor_vs_sharp` (Fútbol, WTA, MLB).
- Las 11 ligas sin cuotas en el ledger (BetExplorer).
- Backtest de line shopping en Goles/BTTS: el dato ya se captura desde la v90
  (56 de 178 partidos con dos casas y creciendo), falta muestra suficiente.
