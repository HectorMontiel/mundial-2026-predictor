# VALIDACIÓN v77 — Playdoit prioritaria, tres vistas, MLB reactivada y calibración de la confianza

Fecha: 2026-07-28 · Remotos: `origin` (HMREY) + `upstream` (HectorMontiel)

---

## 0. Resumen

Las siete mejoras están hechas. Dos de ellas **no se implementaron como pedía el
plan**, y en ambos casos porque medirlo antes demostró que la versión literal
habría empeorado la app. Va explicado con números en §2 y §4.

| | Antes | Después |
|---|---|---|
| Capa 1 (Máximo Valor) | 4 picks, sin MLB | **9 picks**, Fútbol + MLB + Tenis |
| Picks con precio de Playdoit | 0 | **5 de 9** |
| MLB en el barrido | ausente desde que se agotó la cuota de API | **operativa** |
| Playdoit por deporte | solo fútbol (950) | **fútbol 950, tenis 380, MLB 47, NBA 27** |
| Vistas | una | **tres** (Valor, Confianza, Combinadas) |
| Incidencias | invisibles | **panel en la UI** |

---

## 1. MLB: por qué había desaparecido

`MLBEngine.apuestas_dia` seguía colgando de **The Odds API**. Medido:

```
picks: 0
aviso: 'Presupuesto de API agotado hoy.'
```

La cuota mensual estaba a **0 de 500**. El motor cargaba bien y el modelo
funcionaba: simplemente se quedaba sin crédito. Y el aviso **moría dentro del
motor sin llegar a ninguna pantalla**, así que la MLB llevaba semanas fuera de
la app sin que nada lo dijera.

El fútbol se migró a la capa sin cuota en la v71 y el tenis en la v72. La MLB se
quedó atrás y arrastraba el problema desde entonces. Reescrita sobre
Pinnacle + Bovada + Playdoit: **49 partidos con cuota, 14 evaluables por el
modelo, 2 picks**. Se conserva el `sharp_gap` contra Pinnacle.

### 1.1 Tres bugs encontrados al reactivarla

**a) Playdoit devolvía 0 partidos en MLB, NBA y tenis.** El mercado de ganador
lleva un `typeId` distinto en cada deporte (1 fútbol, 186 tenis, 223 NBA, 251
MLB) y la v76 lo fijaba a 1. Fallaba **en silencio**: sin excepción, sin aviso,
el deporte simplemente no existía. Corregido identificando el mercado por
**estructura** — las selecciones apuntan a los competidores del evento y se
llaman exactamente como ellos, que es lo que distingue al ganador del hándicap
(«Orioles» vs «Orioles (+1.5)»). Así vale para cualquier deporte que añadan.

**b) Local y visitante invertidos en MLB y NBA.** El orden de `competitorIds` no
es constante: en fútbol el evento es «A vs. B» y A es local, pero en formato
estadounidense es «A @ B» y ahí A es el **visitante**. Verificado contra
Pinnacle:

| | local | visitante |
|---|---|---|
| Pinnacle | Detroit 1,7194 | Baltimore 2,28 |
| Playdoit (antes) | **Baltimore** 2,2 | **Detroit** 1,7143 |

Los precios eran correctos; el bando, no. Habría generado picks del equipo
equivocado con EV inventados de **+49 %**. Corregido leyendo el separador del
nombre del evento. El test lo comprueba contra Pinnacle en cada ejecución.

**c) El mismo partido duplicado.** Bovada dice «Baltimore Orioles» y Playdoit
«BAL Orioles»; con el nombre normalizado como clave, el partido entraba dos
veces. Ahora la clave de deduplicación es el **código Retrosheet del modelo**,
que es la identidad canónica.

---

## 2. Playdoit prioritaria — pero no a cualquier precio

El plan pedía: *«la mejor cuota para un mercado será la primera disponible en la
lista `[playdoit, pinnacle, bovada, draftkings]`»*. Antes de aplicarlo se midió
qué cuesta. Sobre **894 selecciones con dos o más casas**:

- Playdoit da el mejor precio el **41,1 %** de las veces.
- Cuando no lo da, deja un **3,34 %** de cuota de media (mediana 2,55 %, peor
  caso 23,9 %).
- Ese 3 % en un pick de cuota 2,00 y probabilidad 0,55 baja el EV de **+13,3 % a
  +10,0 %** — un tercio del margen.

Es decir: «siempre Playdoit» habría devuelto buena parte del ROI que la v75 y la
v76 acababan de conseguir. Pero un precio de Bovada que no puedes tomar tampoco
sirve de nada. **No se elige: se devuelven las dos.**

- `preferida` → el precio de Playdoit. **Con este se calcula el EV**, porque es
  el que se puede cobrar.
- `mejor` → el mejor del mercado, con su casa y el diferencial, para que decidas
  si te compensa usar otra cuenta.

`cuotas_multi.precio_accionable()` es la única puerta, y `valor_vs_sharp` la usa,
así que los picks de line shopping son ahora picks **tomables**.

Resultado del barrido: **5 de los 9 picks de Capa 1 salen del precio de
Playdoit** (Pinnacle 3, Bovada 1).

---

## 3. Duplicado de tenis: eran tres bugs, no uno

El plan señalaba `Andrés Andrade (PAN)` vs `Andres Andrade`. Al reproducirlo
aparecieron tres causas distintas, todas generando partidos duplicados:

| Entrada | Clave (antes) | Causa |
|---|---|---|
| `Andrés Andrade (PAN)` | `('pan','a')` | el código de país hacía de apellido |
| `Martin Damm Jr` | `('jr','m')` | el sufijo hacía de apellido |
| `Félix Auger-Aliassime` vs `Auger-Aliassime F.` | `('aliassime','f')` vs `('auger','f')` | apellido compuesto partido distinto en cada formato |
| `Juan Martín del Potro` vs `Del Potro J.` | `('potro','j')` vs `('del','j')` | partícula del apellido |
| `Botic van de Zandschulp` | `('zandschulp','b')` vs `('vande','b')` | partícula doble |

Las tildes, que era la sospecha del plan, **nunca fueron el problema**:
`normalizar()` ya las quitaba. Corregidos los cinco casos: **11/11 emparejan** y
ninguno colapsa jugadores distintos (`Zverev A.` ≠ `Zverev M.`).

---

## 4. «Máxima Confianza»: el hallazgo más importante de la versión

El plan pedía la pestaña con **prob > 80 %**. Medido sobre **36.006 predicciones
fuera de muestra** con cuota real:

| banda | n | dice el modelo | acierta de verdad | sesgo | ROI |
|---|---|---|---|---|---|
| 0,50–0,55 | 4.791 | 52,3 % | 51,6 % | +0,7 pp | −3,72 % |
| 0,55–0,60 | 3.325 | 57,3 % | 57,1 % | +0,2 pp | −1,19 % |
| 0,60–0,65 | 1.761 | 62,1 % | 62,9 % | −0,9 pp | +1,63 % |
| 0,65–0,70 | 426 | 66,8 % | 62,7 % | +4,1 pp | −1,19 % |
| 0,70–0,75 | 68 | 71,7 % | 67,7 % | +4,1 pp | **+10,38 %** |
| **0,75+** | **45** | **79,6 %** | **57,8 %** | **+21,8 pp** | **−6,47 %** |

Dos conclusiones que hay que decir sin rodeos:

1. **El acierto no crece con la probabilidad.** Se estanca en ~63 % y por encima
   de 0,75 **empeora**. Los picks que la app presentaría como los más seguros
   son los peor calibrados: el modelo dice 79,6 % y entrega 57,8 %.
2. Con umbral 0,80 la pestaña estaría **vacía casi todos los días** (solo el
   2,03 % de los partidos llega; el máximo del barrido de hoy era 0,796).

Una pestaña llamada «Máxima Confianza» mostrando «78 %» donde el histórico dice
58 % sería, sencillamente, engañar al usuario. **La pestaña se construye igual —
la pediste— pero honesta**:

- Umbral **0,70**, que es el que mejor rindió de los medidos (+3,67 % de ROI,
  63,7 % de acierto).
- Cada pick lleva **el acierto real de su banda** junto al del modelo, y un
  aviso explícito cuando difieren más de 5 puntos.
- Los picks con **EV negativo** se marcan en rojo: se acierta mucho y se pierde
  igual, porque la cuota no paga el riesgo.
- Stake ¼ de Kelly, como pedía el plan.

`calibracion_confianza.py` regenera la tabla cuando cambie el ledger.

---

## 5. Combinadas multi-deporte

`cross_sport_parlay.py` genera tres perfiles (conservadora 2 patas, media 3,
agresiva 4) exigiendo **al menos dos deportes distintos**.

No es un adorno: el riesgo real de una combinada es la **correlación entre
patas**. Dos picks de la misma liga fallan juntos mucho más de lo que sugiere
multiplicar sus probabilidades — comparten contexto y, sobre todo, comparten el
sesgo del modelo que los generó. Cruzar deportes es la forma más barata de
romperla, así que se exige y nunca se ponen dos patas del mismo partido.

El supuesto de independencia **se declara en la salida** (`supuesto`) en vez de
venderse como exacto. Y las combinadas **no entran solas en el Plan de Ataque**:
se muestra el stake sugerido (⅛ de Kelly) y decide el usuario, porque una
combinada concentra varianza.

Barrido de hoy: 3 combinadas, todas cruzando MLB + Tenis o Fútbol + Tenis.

---

## 6. Incidencias y auditoría

**Panel de incidencias** (`🔍 Registro de incidencias`) en la UI. Existe
exactamente por el caso de la MLB: un fallo que no se ve es un fallo que no se
arregla. Hoy muestra, por ejemplo, que 35 partidos de béisbol tienen cuota pero
son de la Liga Mexicana, que el modelo no cubre.

**`v77_auditar_capa1.py`** — por qué un candidato no llegó a Capa 1, filtro por
filtro y con el margen por el que falló.

**`v77_auditar_no_evaluados.py`** — por qué un partido no llegó siquiera a ser
candidato, separando las tres causas (la liga no juega, el nombre no se resolvió,
nadie publica cuota). Su primera ejecución encontró **tres nombres sin resolver**
y dos eran arreglos reales, ya aplicados en `alias_manuales.json`:

- `Pumas UNAM` → `UNAM Pumas` (Liga MX — un equipo grande que se perdía)
- `Hamarkameratene` → `Ham-Kam` (Eliteserien)
- `MLS All-Stars` → **no se mapea a propósito**: es el partido de las estrellas,
  no un equipo de liga, así que lo correcto es que quede fuera.

Tras el arreglo, «Juárez vs UNAM Pumas» aparece en la Capa 1 del barrido.

---

## 7. Tests

| Test | Resultado |
|---|---|
| `test_catalogo_y_cuotas.py` (57 comprobaciones, 25 nuevas de la v77) | **TODO OK** |
| `test_simetria.py` · `test_match_parlay.py` · `smoke_botones.py` | **TODO OK** |
| Barrido en vivo | 9 Valor · 14 Confianza · 3 Combinadas · 20 Capa 2 · 67 pronósticos |

Las comprobaciones nuevas fijan cada causa raíz de esta versión: las claves de
tenista en los siete casos que fallaban, que Playdoit y Pinnacle **coincidan en
el bando local en MLB** (0 invertidos de 14 comparables), que Playdoit cubra los
cuatro deportes, que el precio accionable sea el de Playdoit informando de lo que
se deja, que la banda ≥0,75 quede registrada como sobreconfiada, y que una
combinada nunca repita partido ni se quede en un solo deporte.

---

## 8. Lo que queda pendiente y por qué

- **La calibración de mercado no se aplica a MLB, NBA ni tenis.**
  `calibracion_mercado.json` está indexado por clave de liga de fútbol, así que
  el encogimiento hacia el precio sharp —que en fútbol convirtió un ROI de
  −3,8 % en +5,8 %— no toca a los otros deportes. Se ve en los EV de MLB, que
  salen altos (+11 %) justo donde el fútbol ya está corregido. Es la mejora con
  más recorrido para la próxima versión, y necesita construir el ledger de esos
  deportes primero.
- **La banda ≥0,80 sigue sin muestra** (17 casos históricos). No se puede
  afirmar nada de ella; por eso el umbral está en 0,70 y no más arriba.
