# VALIDACION v96 — El circuito ITF: la fuente existía, y casi la estropeo

Fecha: 2026-08-04 · Suites: test_catalogo_y_cuotas ✅ · test_simetria ✅ ·
test_match_parlay ✅ · smoke_botones ✅ · test_concurrencia ✅ (TODO OK las 5)

Encargo: investigación exhaustiva para obtener datos del circuito ITF y darle
modelo propio, automático como el resto. Se encontró la fuente, se ingirió el
histórico… y por el camino apareció una fuga de datos que parecía un triunfo.

---

## 1. La investigación: qué se probó y qué respondió

La v95 excluyó el ITF con un motivo medido —«no hay fuente de resultados»— y
la v67 ya había concluido lo mismo. Se reverificó todo:

| fuente | resultado |
|---|---|
| `JeffSackmann/tennis_atp` y `tennis_wta` | **404 de la API de GitHub**: borrados de verdad, no es un cambio de rama |
| perfil completo de JeffSackmann | de todos sus repos **sólo sobrevive `tennis_MatchChartingProject`** |
| web oficial de la ITF (`itftennis.com`) | página anti-bot de **848 bytes** (`NOINDEX, NOFOLLOW`) — bloqueada |
| API de calendario y livescores de la ITF | devuelven la misma página de bloqueo |
| scoreboard de tenis de ESPN | **0 partidos de ITF** (sí cubre challengers) |
| tennisabstract.com | vivo, pero enlaza al perfil de GitHub ya vacío |
| búsqueda de réplicas en GitHub | **encontrada: `Aneeshers/tennis-sackmann-archive`** |

El espejo conserva **473 ficheros**, entre ellos 36 de ATP Futures
(1991-2026), 59 de WTA ITF (1968-2026) y 49 de qualy/challenger (1978-2026).
O sea: la conclusión de la v67 era correcta sobre el original y quedó
desactualizada sobre lo que existe hoy.

## 2. Lo ingerido

```
566.860 partidos · 23.393 jugadores · 2014-12-29 .. 2026-06-02
   ITF masculino      186.802
   ITF femenino       275.916
   challenger ATP     104.806
```

Efecto sobre el histórico del modelo:

```
              antes        después
ATP  partidos  75.004      365.017
ATP  jugadores  1.380       12.897
WTA  jugadores      —       14.634
```

Y sobre los partidos que la app puede modelar: de los **336 partidos de ITF
con cuota** de hoy, **323 (96 %)** tienen ya sus dos jugadores en el histórico.

**El dato se guarda en el repositorio del proyecto** (`historico_itf.csv.gz`,
16 MB). No es una precaución teórica: el original desapareció una vez y el
espejo es una copia personal que puede desaparecer igual. Una vez ingerido, ya
no depende de que nadie lo mantenga.

## 3. La fuga que parecía un triunfo

La primera traducción del esquema fue la ingenua: Sackmann publica
`winner_name` / `loser_name`, así que el ganador fue a `Player_1` y el
perdedor a `Player_2`. El reentrenamiento devolvió esto:

```
ATP · precisión de validación   62,77 %  →  93,54 %
```

Un 93,5 % en tenis es imposible, así que se auditó antes de celebrarlo —
regla de oro nº 7, y van cinco veces que salva la versión. La comprobación
tardó un minuto:

```
Kaggle (el resto del histórico)   ganador == Player_1 en el  50,0 %
ingesta ITF, versión ingenua      ganador == Player_1 en el 100,0 %
```

El modelo no había aprendido a predecir: había aprendido **«gana el
primero»**. Y no era un problema acotado al ITF — con el 78 % del histórico
pasando a venir de esta fuente, la fuga habría contaminado también las
predicciones del circuito principal.

**Arreglado en el origen**: el ganador se asigna a `Player_1` o `Player_2` de
forma pseudoaleatoria pero **determinista** (semilla fija), para que dos
ingestas del mismo fichero den el mismo resultado. Medido tras el arreglo:
**ATP 50,2 % · WTA 49,8 %**.

**Y con guardia**, porque un fallo así no puede depender de que alguien mire
la métrica: `ingerir()` calcula el reparto antes de escribir y **se niega a
guardar el fichero** si se sale de [45 %, 55 %]. Con esta muestra, salirse de
ahí por azar es imposible.

## 4. Qué mejoró de verdad (y qué no)

Con los datos ya limpios, el reentrenamiento devuelve:

```
                 antes              después
ATP   n=72.963  precisión 62,98 %   n=352.654  precisión 67,36 %
WTA   n=56.359  precisión 64,00 %   n=315.648  precisión 75,72 %
```

Y ese 75,72 % **tampoco hay que creérselo tal cual**. Es la segunda vez en
esta versión que un número sube demasiado, así que se auditó igual:

- El ITF **no es intrínsecamente más fácil**: la predictibilidad base (¿gana
  el mejor clasificado?) es 64-66 % en los dos circuitos.
- Pero el ITF trae muchos emparejamientos **desiguales de forma obvia**: en la
  WTA, el **48,5 %** de sus partidos tienen a un jugador sin ranking, y cuando
  sólo uno lo tiene, ese gana el **76,1 %** — prácticamente el 75,72 % del
  modelo.

O sea: la métrica global sube porque **la población cambió**, no porque el
modelo prediga mejor los partidos de siempre. Comparar 75,72 % con el 64 %
anterior sería comparar dos cosas distintas. Medido por separado sobre
partidos posteriores al 2025-06-01 (400 por grupo):

```
                       circuito principal    ITF/challenger
ATP                          67,0 %              70,8 %
WTA                          64,5 %              72,8 %
```

Contra la referencia previa (ATP 62,98 %, WTA 64,00 %, ambas sólo circuito
principal), lo honesto es:

- **ATP mejora de verdad en el circuito principal: 62,98 % → 67,0 %** (+4 pp).
  Cinco veces más datos hacen que el ELO de cada jugador esté mucho mejor
  estimado, y el ELO es la señal más fuerte del modelo.
- **WTA se queda igual: 64,00 % → 64,5 %** (+0,5 pp, dentro del ruido).
- **Los dos cubren ahora ITF y challenger**, donde antes no había nada, con
  70,8 % y 72,8 % de acierto.

Y el catálogo, que es lo que motivó todo esto:

```
ATP   2.138 → 12.897 jugadores
WTA       — → 14.634 jugadores
```

## 5. Automatización

- `ingesta_itf.py` refresca el histórico **semanalmente** en el workflow de
  recalibración, y el resultado se commitea.
- El reentrenamiento de tenis ya era automático desde la v94, así que el
  catálogo se amplía solo en cada ciclo.
- Retirado el filtro que excluía el ITF del barrido (v95): ya tiene modelo
  detrás.

## 6. La limitación, dicha claramente

El espejo es un **archivo**, no un servicio en vivo: su última actualización
llega al **2026-06-01**, unos dos meses de retraso. Eso condiciona qué se
puede esperar:

- Para **entrenar** es perfectamente válido: treinta y cinco años de partidos
  no cambian porque hoy sea agosto.
- Para el **estado** del jugador (forma reciente, ELO) el retraso sí importa.
  Los partidos de ITF de los últimos dos meses no están, así que un jugador
  que haya cambiado de nivel en ese tiempo se predice con datos algo viejos.

No hay forma de arreglarlo con fuentes gratuitas: la ITF bloquea y ESPN no
cubre el circuito. Si el espejo se actualiza, el retraso baja solo.

## 7. Qué queda abierto

- **Fuente viva de ITF**: si aparece, el retraso de dos meses desaparece. Hoy
  no existe ninguna gratuita.
- Backtest de line shopping en Goles/BTTS y las 11 ligas sin cuotas: siguen
  acumulando muestra.
