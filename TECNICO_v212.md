# v212 — Documento técnico

Auditoría total, motor de seguridad, escalada multi-deporte, backtesting
obligatorio e innovación abierta. Todo en una tanda, sin fases.

---

## 1. Qué se entregó

| # | entregable | qué es |
|---|---|---|
| 1 | `AUDITORIA_v212.md` | inventario de los 362 módulos, **generado por script** |
| 2 | `auditar_repo.py` | el script que lo genera, con el inventario de reglas (§1.2) y las decisiones abiertas (§1.5) |
| 3 | `revision_reglas.md` | las 17 reglas revisadas: vigente / mejorable / eliminable |
| 4 | `modo_seguridad.py` | «Apuestas Seguras del Día» |
| 5 | `escalada_lineas.py` | escalada por 4 fuentes, genérica en métrica y deporte |
| 6 | `scraper_contexto.py` | señales de contexto normalizadas, con los huecos declarados |
| 7 | `backtest_v212.py` + `backtesting_v212.md` | **la puerta de activación** |
| 8 | `innovaciones_v212.md` | 7 propuestas, cada una con el dato que necesita |
| 9 | 14 tests en la suite + enganche en el dashboard + paso en el workflow semanal | |

---

## 2. Arquitectura: dónde encaja cada pieza

```
  BARRIDO (alpha_finder)
        │
        ├──► clasificador.py ──► Sección 1  «ventaja de precio»
        │                        (canal medido, p5 +1,73 % — INTACTO)
        │
        └──► auditoria_pick.auditar()          [v209]
                     │
                     ├──► modo_seguridad.evaluar()      [v212] ─┐
                     │         solidez, filtros duros           │
                     ├──► escalada_lineas.evaluar()     [v212] ─┤
                     │         4 fuentes, 3 requeridas          │
                     └──► scraper_contexto.senales()    [v212] ─┤
                               6 proveedores en fútbol          │
                                                                ▼
                                                   activacion_v212.json
                                                          ▲
                                                          │
                                              backtest_v212.py  ◄── ledgers
                                              (los 4 criterios)     walk-forward
```

**La propiedad que sostiene el diseño:** el backtest llama a
`modo_seguridad.evaluar()` y `escalada_lineas.decidir()` —las mismas funciones
que corren en producción—, no a una reimplementación. Si divergieran, el
backtest dejaría de decir nada sobre lo que el usuario ve.

---

## 3. La puerta de activación (§7)

`backtest_v212.py` escribe `activacion_v212.json`. Los dos motores lo leen y
**arrancan apagados si no existe**.

Los cuatro criterios, más el de ruina:

| criterio | umbral |
|---|---|
| Brier | ≤ baseline |
| p5 de bootstrap | ≥ 0 |
| hit rate | ≥ baseline |
| ROI | ≥ baseline |
| ruina a 30 días | ≤ 5 % |

**No medible cuenta como no aprobado.** Es la única lectura que no permite
colar una regla por falta de datos, y hay un test que lo ata
(`test_la_puerta_trata_lo_no_medible_como_no_aprobado`).

### Fuera de muestra: ya lo era

No hizo falta partir 2025/2026 a mano. Los ledgers son walk-forward por
construcción: `build_ledger_totales.py:112` recorta los índices de
entrenamiento a fechas **estrictamente anteriores** al mínimo del pliegue de
test. Se verificó leyendo el código, no asumiéndolo.

### Automatización (§7.7 y §7.8)

El paso «Puerta de activación de las reglas v212» del workflow semanal
`recalibrar.yml` corre el backtest **después** de reconstruir los ledgers y
commitea el veredicto. Una regla que empieza a cumplir los criterios se
enciende sola; una que deja de cumplirlos se apaga sola. El encargo pedía 30
días para la reauditoría; semanal es más estricto y salía gratis ahí.

---

## 4. Resultados del backtest

### Modo Seguridad

| deporte | versión | n | Brier | hit rate | ROI | p5 |
|---|---|---|---|---|---|---|
| Fútbol | A baseline | 36.006 | 0,2379 | 49,2 % | −4,82 % | −5,73 % |
| Fútbol | **B seguridad** | 1.885 | **0,2223** | **65,6 %** | **−1,80 %** | −4,55 % |
| MLB | A baseline | 7.541 | 0,2445 | 56,5 % | −0,97 % | −2,70 % |
| MLB | **B seguridad** | 384 | **0,2318** | **63,5 %** | **−0,26 %** | −6,63 % |
| Tenis | A baseline | 46.149 | 0,2117 | 65,9 % | −4,91 % | −5,53 % |
| Tenis | B seguridad | 8.048 | 0,2255 | 65,3 % | −5,67 % | −6,96 % |

**Lectura.** En fútbol y MLB el filtro mejora **las tres métricas medibles**:
calibración, acierto y ROI. En fútbol recorta la pérdida de −4,82 % a −1,80 %,
tres puntos por apuesta. Falla **sólo el p5**, que sigue negativo.

Eso no es un detalle técnico: es la diferencia entre «pierde menos» y «gana».
El p5 existe en este proyecto precisamente para no confundir las dos cosas. La
regla queda **apagada**, y es la decisión correcta.

En tenis el filtro empeora Brier y ROI. Falla por mérito propio.

### Escalada de líneas

**La regla completa (3 de 4 fuentes) no se disparó ni una vez** sobre 17.532
partidos. No es que fallara: **dos de sus cuatro fuentes no existen en el
histórico**.

- El xG de este repositorio lo escribe `correlated_synthetic_generator`
  (ARQUITECTURA §5.3), así que la fuente de forma no puede llegar a FUERTE.
- Nadie archivó las señales de contexto de un partido de 2024.

Se midió aparte una **variante degradada** de las dos fuentes que sí existen
(modelo + mercado): 1.028 escaladas, ROI −2,89 % contra −4,88 % de la línea
base, p5 −6,78 %. Mejora, pero no pasa. **No valida la regla del encargo** y se
etiqueta como tal.

### Lo que no se pudo medir, y por qué

| regla | motivo |
|---|---|
| escalada 2,5 → 3,5 | `odds_historico.db` (155.364 filas) **sólo guarda la línea 2,5**. Sin precio de la línea que se apostaría, el ROI no existe. Inventarle una cuota «justa más margen típico» sería fabricar el número del que depende la conclusión. |
| Modo Seguridad NFL | no hay ledger walk-forward de NFL. `historico_nfl.csv` tiene 1.095 partidos con resultado, sin predicciones fuera de muestra ni cuota de ganador. |
| Modo Seguridad KBO | no hay ledger, y `historico_kbo.csv` (13.149 partidos) **no tiene ninguna columna de cuotas**: el ROI es inmedible por construcción. |

---

## 5. Cobertura por deporte — el estado real

El encargo pide los cinco deportes «sin excepciones». Lo que se puede hacer hoy:

| deporte | motor evalúa | contexto | backtest | activable |
|---|---|---|---|---|
| Fútbol | sí | 6 proveedores | sí (36.006) | sí, si pasa |
| Tenis | sí | 3 | sí (46.149) | sí, si pasa |
| MLB | sí | 3 | sí (7.541, hasta 2021) | sí, si pasa |
| NFL | sí | 3 | **no** | **no** |
| KBO | sí | 3 | **no** | **no** |

Los motores (`modo_seguridad`, `escalada_lineas`, `scraper_contexto`) son
agnósticos del deporte y funcionan en los cinco. Lo que falta en NFL y KBO no
es código: es **ledger y cuotas**. Sin ellos la puerta del §7 no puede
aprobarlos, y desactivar la puerta para esos dos sería saltarse la regla que
el propio encargo pone.

---

## 6. Dos errores de especificación encontrados

Ambos del mismo tipo que el `EV −2,4 %` de la v209: el enunciado y su ejemplo
no cuadran.

**1. La Fuente 3 de la escalada.** La regla dice comparar contra
`linea_superior`; el ejemplo Barcelona-Getafe sólo cuadra comparando contra la
línea **base** (con `linea_superior = 3,5` la regla pide media ≥ 4,0 y xG ≥ 3,5,
y el ejemplo tiene 3,4 y 3,1). No se eligió a ojo:
`escalada_lineas.REFERENCIA_FORMA` admite las dos y el backtest mide ambas. Por
defecto manda la regla escrita.

**2. La tabla de riesgo por liga** seguía siendo la refutada en la v209. Se
mantiene el tratamiento: escala del encargo, asignación por ECE medido.

---

## 7. Validación

| puerta | resultado |
|---|---|
| `test_catalogo_y_cuotas.py` | **3.672 OK · 0 fallos · exit 0** |
| Bloque v212 (14 tests) | 0 fallos |
| `valida_render.py "Apuestas del Día"` | TODO OK, exit 0 |
| `backtest_v212.py` | corre entero sobre 89.696 picks con cuota |
| `auditar_repo.py` | 362 módulos, 4 banderas rojas |

Dos bugs que sólo aparecieron con datos reales, no con los sintéticos:

1. **ROI −100 % en las tres versiones.** `resultado` en el ledger es el índice
   entero de la columna acertada (0/1/2), no la cadena `'home'/'draw'/'away'`.
   La comparación daba cero aciertos siempre — y −100 % parece un resultado.
2. **La escalada no se disparaba nunca**, lo que llevó al hallazgo estructural
   de las dos fuentes inexistentes en el histórico.

---

## 8. Lo que queda abierto

En `AUDITORIA_v212.md` §1.5, sin tomar por cuenta propia:

- **`ventaja_ponches`** (267 líneas, v132) y **`historico_agrupado`** (144
  líneas, v184): escritos, correctos y **sin un solo importador**. Mismo patrón
  que `filtro_contexto` de la v202 a la v209. No se han enchufado porque los
  dos cambian qué picks salen o qué probabilidad se emite.
- **NFL y KBO**: construir `build_ledger_nfl.py` y conseguir cuotas de KBO, o
  aceptar que esos deportes se quedan sin reglas nuevas.
- **El umbral 0,22 del Brier**: convención de la v32 que hoy gobierna
  exclusiones de combinada y recortes de stake, sin estar optimizada.

Y la recomendación de `innovaciones_v212.md`: **medir el rebote por entrenador**
es la fruta madura. Wikidata da fechas históricas de destitución, el ledger
tiene resultados y cuotas de cierre, y la regla ya está escrita y enchufada.
Se puede medir sin construir infraestructura.
