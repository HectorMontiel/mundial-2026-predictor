# VALIDACION v92 — El circuito de retroalimentación llevaba 60 versiones abierto

Fecha: 2026-08-03 · Suites: test_catalogo_y_cuotas ✅ · test_simetria ✅ ·
test_match_parlay ✅ · smoke_botones ✅ · test_concurrencia ✅ (TODO OK las 5)

Esta versión salió a construir un panel de monitorización y encontró que no
había nada que monitorizar: **el sistema nunca supo si sus picks acertaban**.

---

## 1. EL HALLAZGO — `liquidar()` no tenía un solo llamador

Desde la v32 el proyecto registra cada día los picks que publica y la interfaz
promete que «el resultado se liquida cuando termina el partido». Medido:

```
picks registrados : 315
picks liquidados  :   0
```

`rendimiento_real.liquidar()` existía, funcionaba, y **nadie la llamaba**. Las
consecuencias no eran cosméticas:

- el panel «Rendimiento real de las Apuestas del Día» llevaba versiones vacío;
- el informe mensual no podía existir;
- y sobre todo: **todo lo que el proyecto sabía de su rentabilidad venía de
  backtests**. La comprobación contra la realidad estaba desconectada.

**Arreglado** con `liquidador.py`: toma los picks pendientes cuyo partido ya
pasó, pide a ESPN los resultados de esas fechas (mismo scoreboard que ya se usa
para los fixtures, coste cero, vía `fixtures_espn.resultados_liga` — el reverso
del que descarta los `completed`) y resuelve cada apuesta contra el marcador
con la misma semántica con la que se emitió: 1X2, Goles con su línea, BTTS y
hándicap asiático con la suya. **Lo que no se sabe resolver no se inventa**: se
deja pendiente y se cuenta.

Primera ejecución real: **78 picks liquidados** de 221 pendientes; los 143
restantes son tenis y MLB, que no tienen scoreboard por liga en ESPN, y se
reportan como tales.

## 2. Y al conectarlo, el ROI mentía: −62,93 %

Con los primeros picks resueltos el panel mostró **ROI −62,93 % con un acierto
del 47,4 %**. Dos números imposibles de conciliar — regla de oro nº 7.

**Causa**: `resumen()` hacía `df['cuota'].fillna(0)`. Los picks de Capa 2 no
tienen cuota **por definición** (son «alta confianza sin precio en vivo»), así
que un pick de Capa 2 **acertado** puntuaba `1·(0−1) = −1`: un acierto
contabilizado como pérdida total. De 78 liquidados, 50 eran de Capa 2.

**Arreglado**: el ROI sale sólo de los picks con cuota real; el acierto de la
Capa 2 se reporta aparte, que es lo único que de ella se puede medir.

```
                      antes        después
ROI 30 días         −62,93 %      +3,26 %  (sobre 28 picks con cuota)
ROI 7 días               —       +11,81 %  (sobre 24)
```

Y aparece el dato honesto que importa: **el modelo promete 62,2 % y acierta
47,4 %** en producción. Es la misma brecha de sobreconfianza que la pestaña de
Máxima Confianza ya corrige por banda, ahora confirmada con dinero real.

## 3. El historial tampoco persistía

`rendimiento_real.db` está en `.gitignore`, y eso abría exactamente el mismo
agujero que `odds_store` había tapado para las fotos de cuotas: el runner de
Actions clona limpio y Streamlit Cloud tiene disco efímero, así que la base
arrancaba **vacía** en cada ejecución. Los picks se registraban, se perdían, y
al día siguiente se empezaba de cero.

Un pick publicado y su resultado son irrepetibles. Se persisten a
`picks_historico.csv` (texto plano, commiteado, 315 filas hoy) con
`exportar`/`importar` idempotentes, y el liquidador recarga antes y vuelca
después. `io_atomico.escribir_texto` (nuevo) evita que una escritura a medias
trunque el historial.

## 4. Panel: producción contra backtest, por canal

`monitor_canales.py` compara el ROI real de cada vía con el peor caso plausible
de su validación fuera de muestra (line shopping p5 +1,07 %, modelo p5
+0,92 %). Hasta ahora ni siquiera se podía separar: la tabla de picks guardaba
todos juntos. La columna `canal` (con migración `ALTER TABLE`; las filas
antiguas quedan como «sin clasificar» en vez de atribuirse a una vía que no se
sabe cuál fue) lo hace posible.

Tres estados, y el tercero es el importante:

- ✅ **en rango** — ROI real por encima del p5 del backtest.
- ⚠️ **por debajo** — hay que mirar (no prueba que el edge se rompiera: tocar
  el p5 entra dentro de lo esperado).
- ⏳ **sin muestra** — menos de 30 picks resueltos. **Se dice, en vez de
  enseñar un ROI de tres apuestas como si significara algo.** Es el estado que
  más se va a ver al principio, y enseñar «+40 %» sobre 5 picks sería
  exactamente el error que este proyecto lleva siete versiones documentando.

## 5. RECHAZADO con números — BetExplorer para las 11 ligas sin cuotas

Ejecutado el backfill para las 11 competiciones que la v90 identificó sin
cobertura. Resultado: **2.695 cuotas nuevas en el almacén y CERO partidos del
ledger que ganen una cuota de cierre**.

| liga | ledger | ya tenía cuota | BetExplorer | **cruzan** |
|---|---|---|---|---|
| chi_primera | 615 | 256 | 912 | **256** |
| bol_division | 740 | 275 | 853 | **275** |
| par_division | 621 | 132 | 484 | **132** |
| arg_primera_nacional | 1.676 | 1 | 49 | **1** |
| col_primera_a | 1.089 | 5 | 8 | **5** |

Los que cruzan son **exactamente** los que ya tenían cuota: la ingesta no
aporta ni un partido nuevo.

**Y no es un problema de alineación** —lo primero que se comprobó—: los
identificadores casan perfectamente
(`20251217_Deportes-Tolima_Atlético-Junior` cruza con el «Deportes Tolima vs
Atlético Junior» de BetExplorer). Es un problema de **rango**: BetExplorer
sirve 2021-2024 y el ledger es 2024-2026. Las temporadas recientes SÍ se
descargan (están en caché: `..._2025_results.html`, `..._2027_results.html`)
pero las páginas permitidas por `robots.txt` no sirven las fases de
Apertura/Clausura — y saltárselo exigiría las URLs con query-string que el
propio `robots.txt` prohíbe. Es un límite de la superficie permitida, no un
fallo del código ni algo que se arregle insistiendo.

**La alternativa que SÍ funciona** ya está en marcha: las fotos diarias
(`daily_snapshots`) capturan estas ligas desde la v75. Medido hoy: **138
partidos únicos capturados a un ritmo de 28/día**, lo que proyecta muestra
validable (n≈300 por liga) en **~4 meses**. La cobertura no se puede comprar
retroactivamente, pero se está construyendo.

## 6. Diferido con motivo — line shopping en Goles y BTTS

El dato que la v90 desbloqueó ya se acumula (**56 de 178 partidos con dos
casas** el día de la medición), pero sigue siendo muestra insuficiente para un
backtest con bootstrap: el protocolo 70/30 que validó el 1X2 necesita miles de
apuestas. Se mide de nuevo cuando haya volumen; forzarlo ahora daría el tipo de
número que este proyecto ha aprendido a no creerse.

## 7. Qué queda abierto

- **Liquidar tenis y MLB**: 143 picks pendientes por no tener scoreboard por
  liga en ESPN. La MLB Stats API (ya integrada, `mlb_statsapi.py`) puede dar
  sus resultados; el tenis necesita fuente.
- El backtest de Goles/BTTS, cuando haya muestra.
- Las 11 ligas, vía acumulación diaria (~4 meses).
