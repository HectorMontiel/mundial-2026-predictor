# VALIDACIÓN v73 — La Capa 2 estaba tirando las cuotas a la basura

**Fecha**: 2026-07-28 · **Entorno**: `.venv` Python 3.12.10, Windows

---

## Antes y después

| | Antes (v72) | Después (v73) |
|---|---|---|
| Aviso de cobertura | «⚠️ Solo **8** cuotas vigentes» | «✅ **934** cuotas vigentes · 898 de fuentes sin límite» |
| Picks de tenis en Capa 2 | «🎯 Sin cuota en vivo» | **Cuota real + EV + motivo** de no ser Capa 1 |
| Duplicados en Capa 2 | «Martin Damm» y «Martin Damm Jr» como dos partidos | Uno |
| Sin ODDS_API_KEY | Diagnóstico **crítico** | Informativo (es opcional desde v71) |

---

## 1. La hipótesis de partida y por qué no era la causa

El diagnóstico recibido proponía que `cuotas_multi` nunca se invocaba en el
barrido diario y que había que inyectarlo. **Se comprobó y no era eso**: v71 ya
lo conectó en `fixtures_espn._completar_cuotas` (fútbol y resto de deportes) y
v72 en `_picks_tenis`.

La prueba estaba en la propia captura del problema: los partidos de tenis
aparecían como **«Trevor Svajda vs Jakub Mensik»**, con nombres completos. Ese
es el formato de Pinnacle y Bovada — el catálogo del modelo los guarda como
«Svajda T.». Si los nombres nuevos llegaban a la pantalla, la fuente nueva ya
estaba alimentando el barrido.

Lo que fallaba estaba un paso más adelante.

## 2. La causa real: la Capa 2 descartaba la cuota

`alpha_finder._picks_tenis`, en la rama de Capa 2:

```python
elif prob > CONF_CAPA2:
    salida['capa2'].append({**base, 'cuota': None, 'ev': None, ...})
```

Un partido **con precio real** que no pasaba los filtros de élite acababa en
Capa 2 con `cuota: None`, y la UI —que decide el texto por la ausencia de
cuota— lo rotulaba «Sin cuota en vivo». Era falso: la cuota existía.

### Comprobación

Los mismos picks que se veían como «sin cuota», con su precio real:

| Pick | Prob. modelo | Cuota real | Por qué no era Capa 1 |
|---|---|---|---|
| Gana Jakub Mensik | 86 % | **1,26** | cuota < mínimo 1,50 |
| Gana Lorenzo Musetti | 83 % | **1,40** | cuota < mínimo 1,50 |
| Gana Ben Shelton | 79 % | **1,35** | cuota < mínimo 1,50 |
| Gana Learner Tien | 75 % | **1,18** | cuota < mínimo 1,50 |
| Gana Kimberly Birrell | 76 % | **1,19** | cuota < mínimo 1,50 |

**Todos** tenían cuota. Ninguno llegaba a 1,50, que es el mínimo del proyecto
para no apostar a micro-cuotas.

### Corrección

La cuota real viaja ahora a la Capa 2 junto con su EV, la casa que la paga y un
`motivo_capa2` que dice exactamente qué filtro no supera:

> Gana Jakub Mensik · Cuota **1,26** (justa 1,17) · EV +8,4 % · prob 86 %
> 🏠 Pinnacle
> ℹ️ Fuera de élite: cuota 1,26 por debajo del mínimo 1,50

Eso es información accionable: el usuario ve que si su casa le paga bastante
más de 1,26, la apuesta cambia de cara.

### Nota honesta sobre el mínimo de 1,50

Varios de estos picks tienen EV positivo con la cuota real (Musetti +16,2 %,
Mensik +8,4 %). Podría parecer que el mínimo de 1,50 está dejando valor fuera, y
conviene explicar por qué **se mantiene**: v71 midió que el modelo sobrestima la
selección que elige entre **+4 y +13 puntos** según la liga. Un 86 % declarado
puede ser un 78 % real, y a 1,26 eso pasa de +8,4 % a −1,7 %. El mínimo de
cuota es precisamente el guardarraíl contra esa sobreconfianza documentada.

Ahora, al menos, el usuario ve el precio y decide con la información delante en
vez de con un «sin cuota» que no era cierto.

## 3. HALLAZGO — partidos duplicados por doble fuente

En la Capa 2 aparecían dos veces el mismo partido:

```
Martin Damm vs Ben Shelton          /  Martin Damm Jr vs Ben Shelton
Andres Andrade vs Alexei Popyrin    /  Andrés Andrade (PAN) vs Alexei Popyrin
```

Pinnacle y Bovada escriben distinto al mismo jugador, y la deduplicación usaba
el **nombre completo normalizado** como clave, así que las dos variantes pasaban
como partidos distintos.

**Corrección**: la clave de deduplicación pasa a ser el par de **apellidos
ordenados**, que es estable entre fuentes.

## 4. HALLAZGO — el termómetro medía la fuente equivocada

El aviso «⚠️ Solo 8 cuotas vigentes» venía de `data_health`, que contaba
únicamente `odds_actuales.json`, es decir **The Odds API** — la fuente que v71
degradó a refuerzo opcional precisamente por tener la cuota agotada.

Medía el termómetro viejo mientras la app tenía cientos de partidos con precio.

**Corrección**: el diagnóstico suma las fuentes sin límite. Estado real medido:

```
✅ 898 partidos con cuota de fuentes sin límite (Pinnacle + Bovada):
   futbol 660 · tenis 199 · mlb 21 · nba 18
✅ 934 cuotas vigentes.
```

Además, la ausencia de `ODDS_API_KEY` deja de ser un diagnóstico **crítico**:
desde v71 es opcional, y marcarla como crítica era otra alarma falsa.

---

## 5. Lo que sigue siendo cierto y no es un fallo

* **119 partidos de tenis no enlazados.** Son en su mayoría ITF y challengers
  cuyos jugadores no están en el catálogo del modelo (entrenado sobre ATP/WTA
  principal). No es un fallo de cuotas: es que el modelo no conoce a esos
  jugadores y lo correcto es no predecirlos.
* **Los partidos de fútbol de Capa 2 sin cuota** (Sao Paulo-Santos,
  Botafogo-Gremio) siguen sin precio porque ninguna casa lo ha abierto: son a
  1-3 días y la jornada brasileña se cotiza más tarde.
* **Liga MX con «datos de hace 10 d»** es un caso distinto al bug de julio:
  Liga MX es formato `new` (football-data.co.uk), que publica por lotes
  semanales. No lo tocó el arreglo de v71 porque ese era del cargador de ESPN.

---

## 6. Tests

`test_simetria.py`, `test_match_parlay.py` y `smoke_botones.py` en verde.
