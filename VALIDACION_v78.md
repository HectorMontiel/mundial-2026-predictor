# VALIDACIÓN v78 — Calibración multideporte, y el edge que no estaba donde se creía

Fecha: 2026-07-29 · Remotos: `origin` (HMREY) + `upstream` (HectorMontiel)

---

## 0. Resumen

Las tres áreas del plan están hechas. La primera —extender la calibración a
tenis, MLB y NBA— era «la mejora con mayor impacto potencial en la rentabilidad
global», y lo ha sido, pero **no en la dirección que se esperaba**: al poder
medir por fin esos deportes, resultó que su Capa 1 no era rentable con ningún
peso de calibración. El impacto no ha sido ganar más, sino **dejar de perder**.

Por el camino se encontró y corrigió un fallo mío que habría sido grave: un
ledger desalineado que **fabricaba** un ROI de +37,68 % con bootstrap p5 de
+31,7 %. Está en §3, con la guardia que ahora impide que vuelva.

| | Antes | Después |
|---|---|---|
| Deportes con calibración de mercado | 1 (fútbol) | **3** (fútbol, tenis, MLB) |
| Predicciones fuera de muestra | 47.948 | **120.076** |
| Con cuota de cierre real | 36.006 | **89.758** |
| Deportes en Capa 1 | 3, sin validar | **1 validado**; los otros a candidatos |
| Log-loss global (pliegue de validación) | 0,8055 | **0,7855** |
| Precisión global | 58,01 % | **59,92 %** |

---

## 1. De dónde salieron las cuotas

| Deporte | Fuente | Resultado |
|---|---|---|
| **Tenis** | Ya las teníamos. `tenis_fuentes` ingiere tennis-data.co.uk desde la v67, incluidas `Odd_PS/Max/Avg` | ATP 30.326 y WTA 15.885 predicciones con cuota. **Cero fuentes nuevas** |
| **MLB** | `sportsbookreviewsonline.com`, un `.xlsx` por temporada con el moneyline de cierre (2010-2021) | 15.160 juegos enlazados. Hubo que ampliar Retrosheet de 2021-2025 a **2015-2025** (24.778 juegos) para tener pasado antes del periodo con cuota |
| **NBA** | No encontrada | sportsbookreviewsonline tiene página de temporada pero **sin fichero descargable** (200 OK, cero enlaces, cero tablas); BetExplorer solo sirve los playoffs (84 de 1.230 juegos). Queda pendiente y documentado |

---

## 2. Tres fallos silenciosos que impedían medir

Ninguno daba error. Los tres descartaban datos en silencio:

**a) `recalibrate_from_history.cargar` exigía las tres cuotas.** Con
`cuota_draw` a nulo —tenis, MLB y NBA no tienen empate— `notna().all()` daba
False y **descartaba el deporte entero**. Generalizada para admitir mercados de
dos vías, decidiendo por fila (un mismo ledger mezcla 1X2 y dos vías).

**b) `calibracion_confianza` tenía el mismo `dropna`.** Sus bandas se estaban
calculando solo con fútbol (36.006) en vez de con los tres deportes (89.756).

**c) `backfill_mlb_odds.ABREV` estaba definido y no se usaba.** La fuente
escribe «CUB», «LAD», «SFO» y `codigo_mlb` compara contra nombres completos, así
que **1.537 de 2.462 juegos no enlazaban**. Es exactamente el mismo descuido que
`YA_CUBIERTAS` en la v76: un diccionario escrito y olvidado. Con la tabla
conectada: **2.361 de 2.462 (96 %)**, y solo 63 descartados por marcador.

---

## 3. El fallo grave: un ledger que fabricaba un edge

La primera versión de `ledger_mlb` reconstruía la identidad de cada partido
**replicando el bucle de emisión de `_dataset`**. Pero `_dataset` ordena con
`sort_values('date')`, cuyo desempate no está garantizado, y con ~15 juegos al
día bastaba una permutación dentro del mismo día para pegarle a cada predicción
**la cuota de otro partido**.

No dio ningún error. Al contrario: produjo justo lo que uno querría ver.

```
MLB   n=927   ROI +37,68 %   p5 bootstrap +31,70 %   acierto 63,9 %
```

El mecanismo es perverso: con cuotas aleatorias respecto a la dificultad real,
el filtro `EV > 3 %` se queda precisamente con las filas donde la cuota ajena
salió alta por azar, mientras el acierto sigue al modelo. El resultado es un
edge inventado y espectacular.

**Cómo se detectó**: el log-loss del MERCADO salía **0,7142**, peor que una
moneda al aire (0,693). Unas cuotas de cierre reales, por malas que sean,
siempre baten al azar. Si no lo hacen, están mal cruzadas.

**Cómo se corrigió**:
1. `MLBEngine._dataset` devuelve ahora la identidad de cada fila emitida
   (`estado['filas']`), así que nadie tiene que adivinar el orden.
2. `build_ledger_deportes.verificar_alineacion()` es una **guardia bloqueante**:
   si el log-loss del mercado supera ln(2) —o ln(3) en 1X2— el ledger se
   descarta y no se calibra con él. Corre en cada construcción.
3. Un test de no regresión la ejecuta sobre los tres deportes.

Tras el arreglo: mercado 0,6689 en MLB, 0,5831 en tenis, 1,0001 en fútbol.
Todos por debajo del azar, como debe ser.

_(La guardia se estrenó rechazando WTA por un `NaN` —había filas con
`cuota_home` pero sin `cuota_away`—. Era un fallo del verificador, no del
ledger; corregido, y ahora un log-loss no finito se reporta como tal en vez de
tratarse como «peor que el azar».)_

---

## 4. Resultado de la calibración

Peso elegido por log-loss fuera de muestra, validado en un pliegue que no
participa en la selección:

| Liga | w | n | Δ log-loss | Δ precisión | Adoptada |
|---|---|---|---|---|---|
| ATP | 0,25 | 25.943 + 4.383 | +0,0210 | **+2,60 pp** | Sí |
| WTA | 0,25 | 13.912 + 1.971 | +0,0235 | **+2,38 pp** | Sí |
| MLB | 0,25 | 6.032 + 1.509 | +0,0127 | **+1,79 pp** | Sí |

Global sobre 14.638 partidos de validación: log-loss **0,8055 → 0,7855**,
precisión **58,01 % → 59,92 %**. Las probabilidades que ve el usuario son
mejores en los tres deportes.

`calibracion_mercado.corregir_dos_vias()` aplica el encogimiento en tenis
(`alpha_finder._picks_tenis`) y en MLB (`MLBEngine.apuestas_dia`), con la misma
función para que no puedan divergir.

---

## 5. Lo incómodo: mejor probabilidad no es lo mismo que edge

Con la calibración funcionando se pudo medir, por primera vez, la rentabilidad
de cada deporte barriendo el peso de 1,00 a 0,25 con los umbrales de producción
y el precio que producción toma (el mejor entre Playdoit, Pinnacle y Bovada):

| Deporte | Mejor ROI | w | n | p5 bootstrap | Veredicto |
|---|---|---|---|---|---|
| **Fútbol** | **+6,72 %** | 0,25 | 584 | **+0,92 %** | **Edge validado** |
| MLB | +3,46 % | 1,00 | 394 | −3,98 % | Sin edge validado |
| Tenis | −0,54 % | 0,70 | 1.971 | −6,29 % | Sin edge validado |

El detalle del tenis es el que más importa: **su ROI es negativo con TODOS los
pesos entre 1,00 y 0,30**, y llevaba emitiendo picks que perdían un 5,03 %
sostenido sobre 3.666 apuestas. Solo se vuelve positivo en w=0,25, y ahí quedan
44 picks con p5 −4,66 %: no es un edge, es una muestra pequeña.

**Decisión**: `validacion_deportes.py` aplica la misma regla que dejó el
Over/Under 2.5 fuera de la Capa 1 en la v44 — ROI positivo **y** bootstrap p5
positivo, o fuera. Tenis y MLB pasan a **candidatos** con su motivo visible; no
desaparecen, dejan de venderse como élite. En cuanto pasen la regla —el fichero
se recalcula con el ledger— vuelven solos.

Dos consecuencias honestas que conviene decir:

- El barrido de hoy deja la Capa 1 **solo con fútbol** (10 picks, todos a precio
  de Playdoit), donde antes había 3 de tenis y 1 de MLB.
- Las **combinadas quedan vacías**, porque exigen cruzar deportes. Es el
  resultado correcto: si tenis y MLB no tienen edge como apuesta simple, usarlos
  como patas es peor, no mejor — los errores se multiplican.

---

## 6. Umbral de «Máxima Confianza»

Recalculado sobre 89.756 predicciones (antes 36.006, solo fútbol):

| banda | n | dice el modelo | acierta | sesgo | ROI |
|---|---|---|---|---|---|
| 0,50–0,55 | 13.777 | 52,5 % | 52,0 % | +0,4 pp | −5,13 % |
| 0,55–0,60 | 12.747 | 57,5 % | 56,9 % | +0,5 pp | −4,94 % |
| 0,60–0,65 | 8.696 | 62,1 % | 61,1 % | +1,0 pp | −4,47 % |
| 0,65–0,70 | 1.490 | 66,3 % | 61,6 % | +4,7 pp | −5,77 % |
| 0,70–0,75 | 72 | 71,7 % | 69,4 % | +2,2 pp | **+12,63 %** |
| 0,75+ | 45 | 79,6 % | 57,8 % | **+21,8 pp** | −6,47 % |

El umbral recomendado **sigue siendo 0,70** con 2,5 veces más muestra, y el
diagnóstico de la v77 se confirma: el modelo sobreconfía en la cola alta. No se
adoptan umbrales por deporte porque ninguna banda tiene muestra suficiente por
deporte para justificarlo (la de 0,70+ tiene 117 casos en total).

---

## 7. Monitor de cobertura de Playdoit

`monitor_playdoit.py` vuelca el catálogo de Altenar, detecta **altas y bajas**
frente a la ejecución anterior, y cruza los fixtures del día para ver qué ligas
activas se quedan sin precio tomable.

Estado hoy: fútbol **148 competiciones / 976 partidos**, tenis 72/421, MLB 4/23,
NBA 9/19. Una liga activa sin precio: `bol_division` (5 partidos, 0 con precio
en Playdoit). Las incidencias suben al registro de la UI.

---

## 8. Tests

| Test | Resultado |
|---|---|
| `test_catalogo_y_cuotas.py` (76 comprobaciones, 19 nuevas de la v78) | **TODO OK** |
| `test_simetria.py` · `test_match_parlay.py` · `smoke_botones.py` | **TODO OK** |
| Barrido en vivo | 10 Capa 1 (fútbol, todos con precio de Playdoit) · 10 Confianza · 15 candidatos |

Las comprobaciones nuevas fijan las causas raíz de esta versión: que los tres
deportes tengan peso propio, que el encogimiento a dos vías mueva la
probabilidad hacia el mercado y degrade limpio sin cuota, que **las cuotas estén
alineadas con las predicciones en los tres ledgers**, que el veredicto de edge
coincida con la regla, y que un deporte sin medición no se castigue.

---

## 9. Pendiente

- **NBA sin cuotas históricas.** Es el único deporte que sigue sin poder
  medirse. Las opciones son las mismas de la v76: The Odds API de pago
  (~30 $/mes, cubre NBA y además da snapshots), reactivar api-football, o un
  dataset de Kaggle si aparece uno con licencia clara. Mientras tanto la NBA
  entra en Capa 1 por defecto —no se castiga la falta de datos— pero eso
  significa que es el deporte del que menos sabemos.
- **Tenis y MLB fuera de Capa 1.** No es un final, es un estado: el fichero
  `deportes_capa1.json` se recalcula con cada ledger. Lo que haría falta para
  que volvieran es un modelo que bata al cierre en esos mercados, no un umbral
  más permisivo — hoy el mercado les gana en log-loss (tenis 0,5831 vs 0,6109
  del modelo; MLB 0,6689 vs 0,6817).
