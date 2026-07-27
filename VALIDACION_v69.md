# VALIDACIÓN v69 — Estadísticas de saque en tenis: la fuente que en v67 di por inexistente

**Fecha:** 2026-07-27 · **Entorno:** `.venv` Python 3.12

---

## 0. Resumen ejecutivo

| Qué | Antes (v68) | Después (v69) |
|---|---|---|
| Aces / puntos de saque por partido | «no existe fuente gratuita» (v67) | **54.308 partidos ATP · 79.200 WTA** |
| ELO de saque/resto | imposible | implementado y medido |
| Cobertura del enlace con el histórico | — | 4.2 % → **34.5 %** tras corregir el enlace |

**Veredicto: la fuente se INCORPORA al repositorio; las features NO se activan.**
El módulo, los datos validados y el enlace corregido se suben porque corrigen un
error de v67 y desbloquean trabajo futuro. Las tres features de saque **no pasan
la regla de oro** y por tanto el modelo de producción no cambia.

---

## 1. La búsqueda de fuentes (§7.1 del spec) — peticiones reales

En v67 concluí que no había fuente gratuita de estadísticas de saque tras la
desaparición de los repos `JeffSackmann/tennis_atp` y `tennis_wta`. **Esa
conclusión era prematura.** Resultado de probar las siete fuentes del spec:

| Fuente | Código | Veredicto |
|---|---|---|
| ATP Tour (`/en/scores/stats-centre/...`) | **403** | Bloqueada |
| ATP Tour (`/en/scores/results-archive`) | **403** | Bloqueada |
| SofaScore (`api.sofascore.com/.../statistics`) | **403** | Bloqueada |
| Flashscore | 200 | HTML renderizado por JS; sin datos en el estático |
| UltimateTennisStatistics (`/matchStats`) | 200 | Respuesta vacía (758 bytes) |
| Kaggle Challengers (`dissfya/atp-challenger-...`) | **403** | Sigue privado (igual que en v35) |
| **TennisAbstract** (`/cgi-bin/player-classic.cgi`) | **200** | ✅ **Tiene todo** |

### 1.1 El hallazgo

Las páginas de jugador de TennisAbstract embeben un array JavaScript `matchmx`
con el log completo de partidos. A partir del índice 20 aparece **exactamente el
esquema de Sackmann**:

```
[20] minutos       [21] aces           [22] dobles faltas
[23] puntos saque  [24] 1os dentro     [25] 1os ganados
[26] 2os ganados   [27] juegos saque   [28] BP salvados
[29] BP enfrentados      [30..38] los mismos nueve del RIVAL
```

**Validación del esquema** (no se dio por bueno de vista): 2.300 partidos de tres
jugadores, comprobando `1osDentro ≤ puntos`, `1osGanados ≤ 1osDentro`,
`2osGanados ≤ puntos − 1osDentro`, `bpSalvados ≤ bpEnfrentados` y
`aces ≤ 1osDentro`. **99.9 % de coherencia.** Los 3 fallos son filas del US Open
2019 con `juegos al saque = 0` — un hueco de la fuente, no del esquema. El
módulo aplica ese mismo filtro de coherencia SIEMPRE antes de usar los datos:
una fila incoherente envenena las medias rodantes sin avisar.

**Validación contra la realidad**: media de puntos ganados al saque **64.06 % en
ATP** y **60.39 % en WTA**. Los promedios reales de cada circuito son ~64 % y
~58-60 %. El dato es el bueno.

### 1.2 Ética de uso

TennisAbstract es un sitio pequeño. `tenis_saque.py` cachea en disco por jugador
de forma permanente, espera 1.2 s entre peticiones y sólo pide los jugadores que
el modelo necesita.

---

## 2. El defecto que casi hace descartar la mejora

El primer A/B dio un empate técnico. Antes de dar la mejora por inútil, medí la
**cobertura real del enlace**: sólo el **4.2 %** de los partidos ATP desde 2015
encontraban su estadística. El 96 % de las filas usaba el valor neutro, así que
las features no eran malas — es que casi nunca se rellenaban.

**Causa**: TennisAbstract fecha los partidos por el **inicio del torneo**, no por
el día en que se jugaron. Todo Wimbledon 2026 comparte la fecha `20260629`,
R128 y R64 incluidos. Enlazar por fecha exacta era imposible por construcción.

**Corrección**: el índice pasa a estar keyed por **pareja de jugadores**, y la
fecha se resuelve con una ventana de ±21 días eligiendo el cruce más cercano.
Cobertura **4.2 % → 31.7 %**. El resto del hueco son partidos entre dos
jugadores fuera de los descargados; se amplía la descarga a los 700 primeros del
ranking de cada circuito.

Es un buen recordatorio: **antes de concluir que una feature no aporta, hay que
comprobar que llega a calcularse.**

---

## 3. Features implementadas

Las tres clásicas del tenis, todas con estado leído ANTES del partido y
actualizado después (sin fuga):

| Feature | Qué mide |
|---|---|
| `DIFF_ELO_SAQUE` | ELO alimentado por el % de puntos ganados al saque: "gana" quien defendió mejor su servicio |
| `DIFF_SPW` | % de puntos ganados con su saque, media de los últimos 20 partidos con estadística |
| `DIFF_RPW` | % de puntos ganados al resto (lo que le quitó al rival) |

Si `saque_{circuito}.csv` no existe, las tres caen a su valor neutro (0.62 /
0.38 / 1500) y el modelo se comporta exactamente como en v68 — degradación
limpia.

### 3.1 Resultado del walk-forward (ATP, 5 temporadas, mismo test)

| Rama | Precisión | Log-loss |
|---|---|---|
| base (producción v68) | **0.6557** | 0.6154 |
| datos (fuentes unificadas) | 0.6559 | 0.6154 |
| nivel (v67, descartada) | 0.6514 | 0.6146 |
| **+ saque/resto (v69)** | 0.6549 | **0.6131** |
| mercado (referencia) | 0.6817 | — |

Por ventana:

| Ventana | base | + saque |
|---|---|---|
| 2021 | 0.6478 / 0.6272 | **0.6502 / 0.6132** |
| 2022 | 0.6589 / 0.6124 | 0.6562 / 0.6123 |
| 2023 | 0.6581 / 0.6128 | **0.6599 / 0.6132** |
| 2024 | 0.6508 / 0.6180 | 0.6496 / 0.6184 |
| 2025 | 0.6631 / 0.6067 | 0.6583 / 0.6074 |

### 3.2 Decisión: NO se adoptan

La precisión queda **−0.08 pp** (plana) y el log-loss mejora **−0.0023**. La regla
del proyecto exige +0.3 pp de precisión, o que mejoren ambas. **No se cumple.**
El signo cambia de ventana a ventana (+0.24, −0.27, +0.18, −0.12, −0.48 pp): es
ruido, no señal.

### 3.3 Por qué, honestamente

Dos razones, y la primera se midió:

1. **Techo de cobertura del 34.5 %.** Aun descargando 700 jugadores por circuito
   (54.308 partidos ATP), sólo un tercio de los partidos del histórico encuentra
   su estadística: los que faltan son cruces entre jugadores fuera del top-700,
   cuyos logs no se piden. Pasar de 260 a 700 jugadores sólo movió la cobertura
   del 31.7 % al 34.5 % — rendimientos decrecientes claros. Con dos tercios de
   las filas en valor neutro, cualquier señal queda diluida.
2. **Colinealidad.** El ELO por superficie y el ranking ya codifican buena parte
   de la calidad al saque: un jugador que gana muchos puntos con su servicio ya
   tiene ELO alto. La información marginal es pequeña.

### 3.4 Qué SÍ se sube y por qué

* `tenis_saque.py` — descarga, validación de coherencia y caché.
* `saque_atp.csv` (54.308 partidos) y `saque_wta.csv` — datos ya validados, para
  no volver a raspar un sitio pequeño.
* El enlace por pareja + ventana en `tennis_engine`, con las features detrás de
  `FEATURES_V69_*` **sin activar**.

Con esto, cualquier reevaluación futura (por ejemplo, un modelo entrenado SÓLO
sobre los partidos con estadística, o features de saque por superficie) arranca
con los datos en disco y el enlace resuelto.

---

## 4. Alcance de esta sesión

Esta versión se centró en el §7 del spec (búsqueda de fuentes de saque), que era
el punto que pedía investigación explícita y el que arrastraba una conclusión
equivocada de v67. **Las otras seis mejoras del spec NO están hechas** y no se
presentan como entregadas:

| Mejora | Estado |
|---|---|
| §2 Alineaciones confirmadas | pendiente — fuente verificada (ESPN `rosters`) desde v67 |
| §3 Impacto del portero | pendiente — mismo `rosters` |
| §4 P(BTTS) como feature del 1X2 | pendiente |
| §5 Logística para ligas pequeñas | pendiente — hay 15 ligas entrenadas bajo el ELO que son el banco de pruebas natural |
| §6 MLB carreras esperadas | pendiente |
| §8 NBA fatiga/lesiones | pendiente |
