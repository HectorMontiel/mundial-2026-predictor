# VALIDACIÓN v85 — Auditoría de monotonía: 32 de 56 modelos de liga no responden a la fuerza

Fecha: 2026-07-29 · Remotos: `origin` (HMREY) + `upstream` (HectorMontiel)

---

## 1. El caso que lo destapó

En la ficha de Liga MX el modelo hacía favorito a **Puebla (53,6 %)** sobre
Chivas, con todas las señales en contra:

| | Puebla | Chivas |
|---|---|---|
| ELO | **1349** | **1597** |
| Goles a favor (MA5) | 0,83 | 1,17 |
| Goles en contra (MA5) | 2,17 | 1,00 |
| Forma (MA5) | 0,17 | 0,58 |
| H2H | −0,67 | — |

**Los datos NO están mal.** El vector que llega al modelo es correcto:
`DIFF_ELO −0,62`, `DIFF_FORMA −0,42`, `DIFF_GA +1,17`, `H2H −0,667`. El que no
responde es el estimador.

De las quince features, **solo dos favorecen a Puebla**: remates a puerta a
favor (`DIFF_SOTF +0,83`) y xG a favor (`DIFF_XGF +0,13`). El modelo se queda
con esas dos y descarta las ocho que dicen lo contrario. Es decir:
**sobrepondera medias móviles de 5 partidos y subpondera el ELO.**

Segunda señal, independiente: Chivas **en su propia casa** sale con 47,1 %,
por debajo del 53,6 % de Puebla en la suya. El modelo cree que Puebla es mejor
equipo, no que la localía decida.

---

## 2. No era un partido raro: es sistémico

`_v85_auditoria_monotonia.py` mide una propiedad que un modelo sano cumple
**aunque falle predicciones**: si el local es más fuerte, su probabilidad de
ganar debe ser mayor. Se usa la correlación de Spearman entre diferencia de ELO
y P(gana local) sobre todos los emparejamientos de cada liga, más una prueba de
coherencia (el fuerte en su casa debe superar al débil en la suya).

**56 ligas auditadas · 24 sanas · 32 a revisar.**

Las peores, con la correlación **invertida** (a mejor ELO, MENOR probabilidad):

| liga | rho | coherente |
|---|---|---|
| china | **−0,288** | No |
| sudamericana | **−0,283** | No |
| ita_serie_b | **−0,206** | No |
| eng_league_two | **−0,171** | No |
| eng_national | −0,011 | Sí |
| mls | −0,030 | Sí |
| laliga | 0,070 | **No** |
| argentina | 0,076 | **No** |
| **liga_mx** | **0,344** | Sí |

Sanas, para contraste: `ned_eerste` 1,00 · `slv_primera` 1,00 · `gre_super_league`
0,92 · `par_division` 0,89 · `primeira` 0,88 · `bundesliga` 0,87.

**Nueve ligas fallan la coherencia local/visitante.** Eso no es «poca
precisión»: es que el modelo ordena a los equipos al revés.

---

## 3. El matiz que evita una conclusión falsa

Sería fácil concluir «los modelos están rotos». No es exacto, y conviene
precisarlo: comparando la precisión de validación con la línea base de ELO puro,
**49 de 65 modelos SÍ baten al ELO** (típicamente +0,03). Un modelo puede batir
al ELO y a la vez tener baja correlación con él, si se apoya en la forma
reciente.

Lo que sí es defecto —y es lo que se ve en Puebla— es apoyarse en features de
**cinco partidos** hasta el punto de invertir el orden que marcan el ELO, la
forma, los goles y el historial a la vez.

Los 16 que **no** baten al ELO puro son otro problema, y están listados en el
JSON de la auditoría.

---

## 4. Lo que se midió y NO se despliega todavía

Se probó encoger la probabilidad del modelo hacia un prior neutro, que es lo que
`calibracion_mercado` ya hace cuando hay mercado — y la ficha de partido no lo
tiene, así que ahí el modelo va suelto.

| w del modelo | log-loss | ROI | p5 |
|---|---|---|---|
| 1,00 (sin encoger) | 1,02825 | +0,47 % | −2,57 % |
| 0,90 | **1,02066** | +1,02 % | −2,64 % |
| **0,80** | 1,02140 | **+4,51 %** | **−0,42 %** |

Mejora las dos dimensiones. **Y aun así no se sube**, por un motivo
metodológico: se midió encogiendo hacia la **tasa base** sobre *todas* las filas
del ledger, y lo que hay que arreglar es la ficha **sin mercado** con un prior
de **ELO**. Población distinta y prior distinto. Justificar el cambio con esta
medición sería exactamente el error que ya obligó a dos correcciones en esta
misma sesión (el ROI de +31,75 % en MLB y el máximo del barrido en
`valor_vs_sharp`).

Lo que hace falta para cerrarlo en verde: añadir el ELO de cada partido al
ledger de fútbol y medir el prior de ELO directamente sobre las filas sin ancla
de mercado. La herramienta de auditoría ya está y sirve para verificar el
resultado.

---

## 5. Fontanería: el fallo de codificación, cerrado de raíz

Cuatro análisis de esta sesión murieron por `UnicodeEncodeError` al imprimir
«Δ», «↔» o «→» en una consola cp1252 — **siempre después de calcular los
resultados**, tirando entre 10 y 50 minutos de cómputo cada vez. Los scripts
fuerzan ahora UTF-8 al arrancar.
