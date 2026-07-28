# VALIDACIÓN v74 — Datos al día, y una corrección a mi propio diagnóstico

**Fecha**: 2026-07-28 · **Entorno**: `.venv` Python 3.12.10, Windows

---

## Resumen: antes y después

| | Antes (v73) | Después (v74) |
|---|---|---|
| Frecuencia de refresco | **2 veces/semana** (lunes y jueves) | **Diario** (05:30 UTC) |
| Ligas con estado atrasado | **14** (hasta 182 días) | **0** |
| Ligas mapeadas a ESPN | 39 de 57 | **57 de 57** |
| Duplicados en candidatos | 4 | **0** |
| Red de seguridad si la fuente falla | ninguna | cola diaria desde ESPN |

---

## 1. CORRECCIÓN — la premisa de la que partíamos era falsa

En v73 escribí, y quedó como área de mejora, que Liga MX iba atrasada porque
football-data.co.uk «publica por lotes semanales». **Lo comprobé y no es
cierto.** Descargando la fuente en vivo el 2026-07-28:

| Liga | football-data **en vivo** | CSV en el repo |
|---|---|---|
| dinamarca | **2026-07-27** | 2026-05-17 |
| liga_mx | **2026-07-27** | 2026-07-22 |
| suecia | **2026-07-27** | 2026-07-20 |
| china | **2026-07-26** | 2026-07-18 |

La fuente estaba al día de ayer en todas. **Lo que iba atrasado eran los
ficheros del repositorio**, que solo se reescriben cuando corre el workflow de
reentrenamiento.

Y ese workflow corría:

```yaml
- cron: '0 6 * * 1,4'   # lunes y jueves
```

Dos veces por semana. Un partido del viernes tardaba hasta cuatro días en
entrar en el estado del modelo, y cualquier fallo del lunes dejaba la app una
semana atrás. Ahí estaba el problema, no en la fuente.

## 2. La corrección principal: refresco diario

```yaml
- cron: '30 5 * * *'    # todos los días 05:30 UTC
```

Después de que football-data cierre la jornada europea y antes de la hora punta
de uso.

## 3. Efecto inmediato: 14 ligas puestas al día

`_v74_refrescar.py` compara el estado guardado con la fuente y reentrena solo
lo que se haya movido, para no gastar cómputo en ligas en receso.

**14 reentrenadas · 42 ya al día · 0 errores.**

| Liga | Estado previo | Ahora | Recuperado |
|---|---|---|---|
| **jpn_j1** | 2025-12-06 | 2026-06-06 | **+182 d** |
| **dinamarca** | 2026-05-17 | 2026-07-27 | **+71 d** |
| **polonia** | 2026-05-23 | 2026-07-27 | **+65 d** |
| esp_hypermotion | 2026-05-31 | 2026-06-20 | +20 d |
| irlanda | 2026-07-11 | 2026-07-25 | +14 d |
| china | 2026-07-18 | 2026-07-26 | +8 d |
| suecia | 2026-07-20 | 2026-07-27 | +7 d |
| rumania | 2026-07-20 | 2026-07-27 | +7 d |
| finlandia | 2026-07-20 | 2026-07-26 | +6 d |
| liga_mx | 2026-07-22 | 2026-07-27 | +5 d |
| noruega | 2026-07-22 | 2026-07-27 | +5 d |
| mls | 2026-07-23 | 2026-07-26 | +3 d |
| brasil | 2026-07-23 | 2026-07-26 | +3 d |
| argentina | 2026-07-24 | 2026-07-26 | +2 d |

## 4. Red de seguridad: cola diaria desde ESPN

El cron diario resuelve el caso normal, pero no protege de que football-data se
retrase de verdad algún día. `league_engine._completar_desde_espn()` añade al
histórico los partidos posteriores a la última fecha publicada por la fuente,
tomándolos de ESPN.

Diseño deliberado:

* **football-data sigue siendo la base.** Es la única que trae **cuotas de
  cierre**, y sin ellas no hay CLV ni backtest de EV. ESPN solo aporta la cola.
* Las filas nuevas entran sin cuotas (el pipeline ya imputa) y con las
  estadísticas del `CorrelatedSyntheticGenerator`, igual que cualquier partido
  de formato `new`.
* Los nombres se traducen con `name_mapper` contra el catálogo del propio
  histórico. **Si un equipo no se puede mapear con confianza, la fila se
  descarta**: mejor perder un partido que partir el historial de un club en dos
  entidades distintas (la trampa §4.2.4 del proyecto).

## 5. HALLAZGO — 18 competiciones no tenían mapeo a ESPN

La primera auditoría solo pudo evaluar 39 de las 57 desplegadas: las otras 18
no tenían código de ESPN, así que ni se podía medir su retraso ni refrescarlas
por la vía alternativa. Entre ellas estaban Dinamarca, Polonia, Suecia, China,
Japón, Turquía y las divisiones inglesas y escocesas.

Completado `_ESPN_POR_LIGA` con las 18. Al repetir la auditoría, las ligas con
retraso detectado pasaron de 5 a 9 — y el refresco encontró 14.

## 6. HALLAZGO — duplicados en fútbol, con line shopping de regalo

Confirmado el problema que se sospechaba por analogía con el tenis: **4
candidatos duplicados**, todos «Menos de 2.5».

Causa: el mismo mercado se emitía dos veces cuando dos fuentes lo cubrían — una
desde `odd_over25` (scoreboard de ESPN) y otra desde `odd_over` cuando la línea
del core API también era 2,5.

En vez de descartar el segundo sin más, `_add` conserva ahora **la mejor
cuota**: es la misma apuesta y lo que interesa es el precio más alto. El
duplicado deja de ser ruido y pasa a ser line shopping.

**Duplicados: 4 → 0** en las tres secciones (élite, candidatos, Capa 2).

---

## 7. Lo que queda pendiente

**Recalibración del mínimo de cuota (1,50).** Sigue abierta a propósito. Deja
fuera picks con EV positivo (Musetti +16,2 % a 1,40), pero es el guardarraíl
contra la sobreconfianza de +4 a +13 pp que midió v71. Para moverlo hace falta
acotar mejor ese sesgo, y eso exige histórico de cuotas acumulado — no se puede
decidir con las muestras de 4 a 11 partidos de hoy.

**Ligas genuinamente en receso.** `esp_hypermotion` se quedó en 2026-06-20 y
`gre_super_league` en 2026-05-21 porque su temporada terminó, no por un fallo.
El aviso «sin datos nuevos» en esas es correcto.

---

## 8. Tests

`test_simetria.py`, `test_match_parlay.py` y `smoke_botones.py` en verde.
