# VALIDACION v93 — El modelo mejoraba a diario; sus calibraciones, nunca

Fecha: 2026-08-03 · Suites: test_catalogo_y_cuotas ✅ · test_simetria ✅ ·
test_match_parlay ✅ · smoke_botones ✅ · test_concurrencia ✅ (TODO OK las 5)

Tres encargos: liquidar tenis y MLB, mantener todo calibrado solo, y que el
pick recomendado sea el más probable de acertar. Los tres cerrados — y el
segundo destapó una inconsistencia de fondo.

---

## 1. EL HALLAZGO — el modelo se reentrenaba a diario, sus calibraciones no

Auditado artefacto por artefacto contra el workflow:

| artefacto | edad | ¿lo regeneraba el workflow? |
|---|---|---|
| modelos de fútbol | 1 día | ✅ SÍ |
| `team_stats_*.json` | 1 día | ✅ SÍ |
| `calibracion_mercado.json` | 1 día | ✅ SÍ |
| **`pick_ledger_total.csv`** | 5 días | ❌ **NUNCA** |
| **`calibracion_confianza.json`** | 3 días | ❌ **NUNCA** |
| **`umbrales_capa1.json`** | 6 días | ❌ **NUNCA** |
| **`edge_map.json`** | 11 días | ❌ **NUNCA** |
| **`precision_ligas.json`** | 1 día | ❌ **NUNCA** |
| **`deportes_capa1.json`** | — | ❌ **NUNCA** |

La antigüedad es lo de menos. Lo grave es la **inconsistencia**:
`calibracion_confianza` mide cuánto acierta de verdad cada banda de
probabilidad del modelo. Si el modelo se reentrena cada día y esa medición no,
**se está corrigiendo el modelo de hoy con la huella de un modelo que ya no
existe**. Lo mismo con la banda de EV rentable y los umbrales de Capa 1.

Y todo cuelga del ledger — que el propio proyecto había identificado como
problema en la v79 («colgaba de un fichero que nadie sabía reproducir»),
resolvió escribiendo `build_ledger_total.py`… y nunca puso en el workflow.

**Arreglado** con `recalibrar_todo.py` (cadena secuencial, cada paso falla de
forma independiente y el que no se regenera conserva el anterior) y un
workflow semanal `recalibrar.yml`. Semanal y no diario a propósito: el paso 1
re-predice decenas de miles de partidos (~40 min) y las calibraciones se mueven
despacio. Verificado de punta a punta: **5/5 pasos OK en 16 s** sin el ledger.

```
2. calibración de confianza   89.748 predicciones medidas · umbral 0,70
3. techo de acierto por liga  34 ligas · correlación 0,7184 · publicado
4. banda de EV rentable       EV [0,030, 0,130] · piso 0,55
5. deportes con edge          ['Fútbol']
6. peso del encogimiento      w global 0,25 · 29 ligas adoptadas
```

## 2. Tenis y MLB liquidados (y una causa raíz por el camino)

**MLB** — `mlb_statsapi.resultados_entre()`: la API oficial ya se usaba para
entrenar; sólo faltaba pedirle el rango con estado final. 164 juegos.

**Tenis** — investigado y resuelto: ESPN **sí** publica resultados de tenis,
pero con otra forma. Cada `event` es un TORNEO y los partidos cuelgan de
`groupings[*].competitions[*]`, cada uno con su `winner`. Por eso el parser
genérico no servía. Medido: **664 partidos con ganador** en 12 días.

Y al conectarlo sólo cerraba el **24 %** de los picks de tenis antiguos. La
causa, rastreada hasta un caso concreto: **los picks de tenis y MLB se sellan
con la fecha de PUBLICACIÓN, no con la del partido** (el feed de cuotas no da
una fecha fiable, así que se usa el día del barrido). «Anastasia Potapova vs
Venus Williams» está registrado el 28 y se jugó el 29 — por un día de
diferencia no cruzaba.

Arreglado emparejando por **pareja de jugadores/equipos** dentro de
`TOLERANCIA_DIAS = 2`, y tomando siempre el más cercano, nunca el más lejano
«por si acaso»: liquidar el partido equivocado contamina el ROI en silencio.

```
                  antes v93   después
Tenis                  23 %      57 %
MLB                    55 %      55 %
Fútbol                 39 %      39 %
TOTAL           107 picks    142 picks (45 %)
```

Lo que queda pendiente son partidos de hoy sin jugar y mercados de tenis
derivados (sets, juegos) que exigirían el marcador por sets, que ESPN no da en
el scoreboard — se dejan pendientes a propósito.

## 3. ADOPTADO — el Pick del Día es el MÁS PROBABLE, no el de más EV

Con 142 picks liquidados hay por fin medición de producción, y confirma el
backtest con dinero real:

| mercado | n | promete | **acierta** | brecha |
|---|---|---|---|---|
| Ganador (tenis) | 58 | 77,2 % | **70,7 %** | −6,5 pp |
| 1X2 | 27 | 48,1 % | **40,7 %** | −7,4 pp |
| Goles | 29 | 69,7 % | **51,7 %** | −18,0 pp |
| BTTS | 22 | 69,7 % | **50,0 %** | −19,7 pp |

Coincide con lo que el backtest ya decía sobre 89.748 predicciones (v86: el
BTTS promete 80 % y acierta 53 %). Dos mediciones independientes apuntando a lo
mismo: **no es ruido de muestra pequeña**.

La consecuencia práctica es directa. `pick_del_dia` ordenaba por Brier de la
liga y EV, así que un BTTS «al 84 %» —que acierta el 53 %— salía por delante de
un 1X2 al 82 % que acierta el 82 %. Ahora manda `prob_calibrada()`: la
probabilidad que el mercado acierta DE VERDAD en esa banda. Los filtros no
cambian (EV positivo y dentro de la banda validada siguen siendo obligatorios);
cambia el criterio de ordenación, que es lo que el usuario pidió.

La UI muestra **«X % de acertar»** en vez de la probabilidad del modelo, y
cuando ambas difieren lo dice explícitamente.

## 4. Qué queda abierto

- **Mercados derivados de tenis** (sets, juegos): sin marcador por sets en el
  scoreboard de ESPN. Sólo se liquida el ganador, que es el único que se emite
  como pick.
- **Backtest de line shopping en Goles/BTTS**: el dato se acumula desde la v90;
  el protocolo 70/30 con bootstrap necesita miles de apuestas.
- **Las 11 ligas sin cuotas**: vía prospectiva a 28 partidos/día (~4 meses),
  confirmada en la v92. La retrospectiva quedó descartada con números.
- **Reentrenar MLB, tenis y NBA en el CI**: hoy sólo se reentrena fútbol
  (`league_engine --build`). Sus modelos tienen 5-7 días y se regeneran a mano.
  Es el siguiente hueco de automatización.
