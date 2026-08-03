# VALIDACION v90 — Seis rechazos medidos, y dónde estaba el techo de verdad

Fecha: 2026-08-02 · Suites: test_catalogo_y_cuotas ✅ · test_simetria ✅ ·
test_match_parlay ✅ · smoke_botones ✅ · test_concurrencia ✅ (TODO OK las 5)

Esta versión nace de dos propuestas de mejora y de un encargo: subir el edge y
la precisión. Las dos propuestas se **rechazan con números** —y una de ellas
partía de una premisa falsa— y el encargo termina en un sitio distinto al
esperado: el techo del 1X2 ya estaba tocado, y lo que sí faltaba era poder
medirlo y poder validar los mercados donde nadie había mirado.

---

## 1. PROPUESTA RECHAZADA — «ingerir cuotas sudamericanas para medir el w por liga»

**La premisa era falsa.** Se afirmaba que no se puede medir un peso propio
para Argentina o Liga MX «por falta de cuotas de cierre en el ledger». El
ledger ya tiene, con ancla de Pinnacle:

| liga | filas con Pinnacle |
|---|---|
| argentina | 1.534 |
| mls | 1.562 |
| brasil | 1.276 |
| liga_mx | 1.090 |

Once ligas de verano son medibles **hoy, sin scrapear nada**. Así que en vez
de discutir el remedio se midió directamente (`_v90_w_verano.py`, w elegido en
los pliegues 0-2 y juzgado en los 3-4, 28 ligas con muestra suficiente):

```
el w por liga gana en 15 de 28 ligas (54 %)   ← una moneda al aire
log-loss   w por liga 1.00371 · w global 1.00499
ECE        w por liga 0.05551 · w global 0.05472   ← PEOR
precisión  w por liga 0.4980  · w global 0.4981   ← igual
ROI medio  w por liga −5,91 % · w global −5,78 %  ← PEOR
p5 medio   w por liga −17,75 %· w global −17,56 % ← PEOR
```

Confirma lo que la v87 ya midió con otro método y otra población. El w por
liga **no se adopta**, y por tanto ingerir cuotas sudamericanas *para eso* no
tiene sentido.

**Lo que sí queda abierto y es distinto**: 11 ligas del catálogo tienen ~0 %
de cobertura de cuotas en el ledger (arg_primera_nacional 0/1.676,
col_primera_a 5/1.089, mex_expansion 3/675, usl_championship 36/1.094…) y
**sí producen picks**. De esas no se puede validar nada — ni el w, ni el edge,
ni los umbrales. Ése es el hueco real, y no es el que decía la propuesta.

## 2. PROPUESTA RECHAZADA — «calibrar córners y tarjetas»

Se afirmaba que son «los únicos mercados de Máxima Confianza sin medición de
acierto real». Comprobado, **no son mercados de la app en absoluto**:

- Los únicos mercados que el barrido puede emitir, y por tanto los únicos que
  pueden llegar a Máxima Confianza, son **1X2, Ganador, Moneyline, Goles,
  BTTS y Hándicap**. Los cuatro medibles ya están medidos (v86/v87).
- **0 de 71** ficheros `historico_*.csv` tienen columnas de córners. El dato
  no existe en lo que se ingiere.
- Los córners aparecen sólo en la plantilla por partido y salen de una
  fórmula **determinista sobre los goles esperados**
  (`ck = 4 + 0,25·(λh+λa)·spx·tpo`, league_engine.py:2110). No llevan
  información propia: «calibrarlos» sería recalibrar el modelo de goles, que
  ya se calibró en la v86 sobre 47.794 partidos.

Construir ese ledger habría sido trabajo sobre un mercado que el usuario no
puede apostar desde la app y sobre un número que no es una predicción
independiente.

## 3. EL EDGE DEL 1X2: seis palancas probadas, seis rechazadas

Todas con el mismo método (elección en pliegues 0-2, juicio en 3-4, 26.666
partidos de fútbol con cierre de Pinnacle). Punto de partida:

```
modelo solo    log-loss 1,02811 · precisión 48,96 %
mercado solo   log-loss 1,00120 · precisión 50,04 %   ← el mercado gana
producción     log-loss 1,00204 · precisión 50,05 %   (lineal w=0,25)
```

| # | palanca | resultado fuera de muestra | veredicto |
|---|---|---|---|
| 1 | w por liga | gana en 54 % de ligas, ECE y ROI peores | RECHAZADA |
| 2 | mezcla en logit | log-loss 1,00331 vs 1,00204; ROI −2,46 % vs +3,24 % | RECHAZADA |
| 3 | w global reoptimizado (w*=0) | ROI −12,60 %, p5 −34,57 % | RECHAZADA |
| 4 | stacking aprendido (3 cestas) | precisión 50,10 % vs 50,05 %; ROI peor | RECHAZADA |
| 5 | corregir el sesgo favorito-perdedor | b=1,0158 (≈1); ROI +8,57 %→+7,15 % | RECHAZADA |
| 6 | el modelo como FILTRO del line shopping | superficie dentada, 4/11 configs | RECHAZADA |
| 7 | bajar el piso de prob. para incluir empates | empate 0/5 configs robustas | RECHAZADA |

Dos merecen detalle porque son trampas que este proyecto ya ha pisado:

**El sesgo favorito-perdedor.** La tabla por bandas invitaba a corregir: en la
banda 0,70–0,80 el mercado decía 74,24 % y pasaba el 76,80 % (−2,56 pp),
monótono en las seis bandas. Ajustado de verdad (Platt en log-odds sobre
60.195 puntos de calibración), el coeficiente sale **b = 1,0158** — o sea,
nada — y aplicarlo **baja** el ROI del canal de valor de +8,57 % a +7,15 % y
el p5 de +0,82 % a −0,07 %. Era ruido de muestreo con forma de patrón.

**El modelo como filtro.** El mejor umbral en los pliegues de elección
(p_modelo ≥ p_mercado − 5 pp) daba p5 **+6,68 %**… y −0,22 % en los de juicio.
La única región contigua robusta (u = −0,15/−0,13/−0,11) da p5 **+1,04 %**
frente al **+1,07 %** de no filtrar: pierde el 14 % del volumen para quedarse
igual. Y la superficie es dentada (4 de 11 configuraciones, no contiguas),
que según la lección de la v83 es la firma del ruido, no de un edge.

**Conclusión honesta:** el 1X2 modelo+mercado está en un óptimo local y el
modelo propio no aporta sobre un cierre eficiente — bate al mercado en **4 de
34 ligas** y por márgenes de 0,2 a 1,3 pp. No es un fallo del proyecto: es la
razón por la que la Capa 1 se apoya en el line shopping, que **sí** valida
fuera de muestra (n=643, ROI +8,57 %, **p5 +1,07 %**). Esto queda escrito para
que nadie vuelva a gastar aquí.

## 4. ADOPTADO — El techo real de cada competición (`precision_ligas.py`)

El hallazgo aprovechable de la auditoría: el acierto del mercado —el mejor
predictor que existe, y por tanto el techo práctico— **no es igual en todas
partes**. Va del **42,41 %** en la Serie B italiana al **59,06 %** en la
Superliga turca. Diecisiete puntos.

Eso cambia la decisión del usuario: un pronóstico al 55 % en Turquía y otro al
55 % en la Serie B no valen lo mismo, porque en uno queda margen y en el otro
se está prometiendo más de lo que consigue nadie. La app mostraba los 274
pronósticos con el mismo aire de autoridad.

**Validado antes de publicarse, y ésta es la diferencia con la v38**: aquella
midió que el ROI por liga NO es estacionario y por eso se rechazó elegir ligas
por rentabilidad pasada. El acierto es otra cosa —refleja el equilibrio
competitivo, que es estructural— pero eso hay que comprobarlo: `generar()`
mide la correlación entre el acierto de los pliegues tempranos y el de los
tardíos y **sólo publica el fichero si supera 0,50**. Medido: **0,7184**. El
techo se sostiene; el ROI no lo hacía.

No filtra picks ni toca ninguna probabilidad: informa. Aparece en la cabecera
de cada partido y como columna «Techo liga» en la tabla de pronósticos.

## 5. ADOPTADO — Los totales dejan de perder su casa (el desbloqueo)

Al intentar validar el line shopping sobre **Goles** —el rechazo de la v44/v45
fue sobre el MODELO, y este canal no usa el modelo, así que la extensión era
legítima— apareció que no se podía medir. Y el motivo no era falta de tiempo:

`cuotas_partido` devolvía un único dict `totales` con las casas ya
**fusionadas**: el over25 de ESPN y el de Pinnacle se escribían en la misma
clave y el segundo pisaba al primero. `daily_snapshots` sólo podía etiquetar
los totales como Pinnacle. Resultado en `historical_odds`: **35.606 filas con
over25 y CERO partidos con dos casas**. El dato se fusionaba antes de
guardarse, así que el histórico necesario no podía existir nunca.

Arreglado con `totales_por_casa` (nuevo, en paralelo) conservando `totales`
byte a byte para no cambiar ningún comportamiento actual. Verificado en vivo
tras una captura real:

```
                        antes        después
DraftKings con over25       0            571
Pinnacle con over25       197            197
partidos con over25 de 2+ casas:   0  →  56 de 178
```

El histórico de dos casas ya está creciendo. Dentro de unas semanas habrá
muestra para validar el canal de valor sobre Goles y BTTS con el mismo método
que validó el 1X2 — y si no la hay, se sabrá por qué.

Test de regresión añadido (`test_totales_conservan_su_casa`) que fija las dos
mitades del contrato: que se distinga la casa y que `totales` no cambie.

## 6. Qué queda abierto

- **Las 11 ligas sin cuotas en el ledger** (arg_primera_nacional, col_primera_a,
  mex_expansion, usl_championship, slv_primera, ecu_liga_pro, per_liga1,
  uru_primera, par_division, bol_division, chi_primera) producen picks que no
  se pueden validar. Éste es el hueco real de cobertura, distinto del que
  planteaba la propuesta 1. BetExplorer (v76) sigue siendo el candidato.
- **Line shopping en Goles/BTTS**: el dato ya se captura; falta que se acumule.
- Monitorización producción-vs-backtest de valor_vs_sharp (WTA, MLB), heredada.
