# v105 — El ELO de copas, el techo del line shopping y el abridor de la KBO

Tres frentes. Uno **valida y se adopta**, uno **se rechaza con la cadena entera
de evidencia**, y uno queda medido con su techo y su límite de muestra.

---

## 1. ELO cross-competición — RECHAZADO, y la cadena que lo demuestra

### Lo que se construyó

`elo_global.py`: un ELO único por equipo sobre las **66 competiciones** y
**147.608 partidos**, con tres piezas:

1. **Un solo ELO por equipo**, no uno por competición. Un club no cambia de
   fuerza al pasar de su liga a la copa.
2. **Unificación de nombres con comprobación de país.** El mapeo difuso a secas
   sube la cobertura del 30 % al 78 % pero funde «AEK Larnaca» (Chipre) con
   «AEK» (Atenas). Aquí dos nombres sólo se funden si además comparten país
   inferido de `sede_pais`. Resultado: 78 fusiones, y el Nordsjælland pasa de
   **6 partidos a 263** al unirse su entrada de copa con la de la liga danesa.
3. **Encogimiento hacia la media del país**, no hacia 1500: un club islandés con
   tres partidos no es «media europea», es «islandés desconocido».

Un fallo encontrado por el camino: `pd.to_datetime` infiere UN formato del
primer valor y convierte a NaT el resto. Los históricos de ESPN traen
`2024-03-06 19:00:00` y los de football-data `2023-08-11`, así que al concatenar
**se perdían 37 de las 66 competiciones enteras**. Se detectó porque salían 29
donde debían salir 66.

### Y por qué no se despliega

| prueba | mejora | p5 | veredicto |
|---|---|---|---|
| sobre el modelo crudo (gana local) | +0,005715 | +0,004171 | ADOPTAR |
| ídem, sólo copas | +0,015557 | +0,006492 | ADOPTAR |
| control de permutación | +0,000048 | −0,000034 | (la señal es real) |
| **sobre el ELO por competición que YA existe** | +0,000784 | +0,000327 | marginal |
| **ídem, sólo copas** | +0,002815 | **−0,001157** | **RECHAZAR** |
| **sobre la probabilidad QUE SE PUBLICA (modelo+mercado)** | +0,000003 | **−0,000180** | **RECHAZAR** |

La lectura, en orden:

- El ELO cross-competición mejora mucho sobre el modelo crudo, y **el triple en
  copas**. Tentador.
- Pero el ELO por competición que el proyecto ya tiene aporta casi lo mismo
  (+0,005111): lo que el primer test medía no era «cross-competición», era «el
  modelo infrautiliza el ELO».
- **En copas —donde debía brillar— rechaza**, y el acierto incluso baja
  (0,6253 → 0,6206).
- Y sobre lo que de verdad se publica, que lleva la mezcla con el mercado a
  w=0,25, **no aporta absolutamente nada**: el precio ya contiene esa
  información.

Es la tercera vez esta semana que la conclusión es la misma: en fútbol, el
mercado ya sabe lo que el modelo podría aportar. El módulo se conserva
—está validado, no tiene fuga y su unificación de nombres es reutilizable— pero
**no entra en producción**.

---

## 2. Line shopping — el techo, medido por primera vez

El edge validado del proyecto está aquí, pero nunca se había cuantificado
cuánto hay disponible.

**Cobertura actual:** 4 casas reales — Bovada (1.723 fotos), Pinnacle (1.623),
DraftKings (1.453), Playdoit (1.320). El 96 % de los partidos con precio tienen
2 o más casas, y 147 de 219 tienen las cuatro.

**Dispersión entre la mejor y la peor casa:**

| corte | spread medio | p50 | p90 |
|---|---|---|---|
| todas las comparaciones | 13,03 % | 7,31 % | — |
| **casas fotografiadas con ≤0,5 días de diferencia** | **9,76 %** | 3,77 % | **27,01 %** |

El segundo corte es el que importa: comparar la apertura de una casa con el
cierre de otra no es line shopping, es comparar días distintos. Aun con ese
control, la dispersión sigue siendo del 9,76 % de media y llega al 27 % en el
decil alto. **Ahí hay dinero real.**

**Lo que no se puede afirmar todavía:** el ROI realizado. Sólo 219 partidos
cruzan precio con resultado conocido, y con esa muestra el mejor precio da
+0,61 % con p5 −10,90 %: ruido. El cuello de botella no es el método, es el
histórico de fotos, que crece a diario.

---

## 3. KBO: las features del abridor — ADOPTADAS (y no integradas todavía)

Se triplicó la muestra ingiriendo 2021-2023: **2.720 partidos con preview**,
2.640 cruzados con el histórico, 792 en el tramo de juicio.

Con el protocolo limpio —elección en pliegues 0-2, juicio en 3-5, que no
participan en la decisión—:

| | log-loss | acierto |
|---|---|---|
| base (ELO) | 0,68811 | 54,67 % |
| base + elegidas (K9, BB9, tamaño de bullpen) | **0,68261** | **56,19 %** |

mejora **+0,005500** · **p5 +0,000923** · **ADOPTAR**

**Auditoría:**

| control | mejora | p5 |
|---|---|---|
| features reales | +0,005500 | **+0,000923** |
| features PERMUTADAS | +0,000724 | −0,001313 |
| sólo K9 | +0,003679 | −0,000400 |
| sólo tamaño de bullpen | −0,001308 | −0,002325 |

La permutación descarta el artefacto, y ninguna señal aguanta sola: es el
bloque el que aporta. Con la muestra pequeña (403 juzgados) esto salía
RECHAZAR; con 792, adopta. La diferencia la hizo ingerir tres temporadas más.

### Por qué NO se integra en el motor todavía

`KBOEngine._dataset` delega en `MLBEngine._dataset`, y meter estas columnas
exige además resolverlas **en inferencia**: pedir el preview del partido que
aún no se ha jugado, por su `gameId`, en el momento de predecir. Sin ese paso,
el modelo se entrenaría con features que en producción no existen — exactamente
el desajuste entre entrenamiento e inferencia que la guarda de la v101 se puso
a detectar, y que dejaría la KBO sin predicciones.

Integrar a medias es peor que no integrar. Queda especificado:

1. `KBOEngine.cargar_datos_historicos` funde `kbo_preview.csv` por
   (fecha, home_team, away_team).
2. `_dataset` añade las tres columnas al vector y `COLS_MODELO_IDF` sus índices.
3. `construir_features` pide el preview del `gameId` del partido próximo
   (`kbo_preview.preview`, ya cacheado) y degrada a la media de la liga si la
   fuente no responde — nunca a ceros.
4. Reentrenar y verificar con la guarda de features de `base_engine`.

---

## Resumen

| pieza | estado |
|---|---|
| `elo_global.py` (ELO cross-competición, 66 competiciones) | **VALIDADO, NO DESPLEGADO** — el mercado ya lo contiene |
| Unificación de nombres con país (78 fusiones) | dentro de `elo_global`, reutilizable |
| Techo del line shopping (9,76 % de dispersión real) | **MEDIDO** — ROI pendiente de más fotos |
| Features de abridor KBO (K9, BB9, bullpen) | **ADOPTADAS** — p5 +0,000923, integración especificada |
| Ingesta de 2021-2023 (2.720 partidos) | **DESPLEGADA** |

## Scripts

```
elo_global.py                        el ELO cross-competición
_v105_ab_elo_global.py               A/B sobre el modelo crudo
_v105_edge_line_shopping.py          dispersión y ROI por casa
_v104_ab_abridor_kbo_limpio.py       el que decide en KBO
```
