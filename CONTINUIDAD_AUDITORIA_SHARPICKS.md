# Continuidad compartida — auditoría de SharPicks

**Última actualización:** 2026-10-18 (CDMX)  
**Propietario:** HMREY / Héctor Montiel  
**Repositorio canónico:** https://github.com/HectorMontiel/mundial-2026-predictor  
**Producción web:** https://sharpicks.pages.dev/  
**Registro maestro:** [AUDITORIA_BUGHUNTER_SHARPICKS_2026-10-18.md](./AUDITORIA_BUGHUNTER_SHARPICKS_2026-10-18.md)  
**Rama de auditoría/trabajo:** `audit/sharpicks-bughunter-2026-10-18`  
**Política:** NO hacer cambios directos a `main` mientras falte alguna validación crítica. Abrir PR, ejecutar las pruebas, revisar el diff y verificar dependencias externas antes de fusionar.

## Instrucciones para Claude y ChatGPT

Este archivo y el informe maestro son la memoria compartida del trabajo. Antes de trabajar:
1. Lee este archivo y el informe maestro completo.
2. Revisa el estado más reciente de la rama, `main`, los commits del bot y los checks de GitHub Actions; los bots escriben a `main` de forma recurrente.
3. No des por vigente un número de línea si el archivo cambió: vuelve a consultar la fuente y actualiza el enlace al commit/archivo.
4. Usa los mismos IDs `SHP-###`. No dupliques hallazgos; añade evidencia nueva al existente.
5. No marques nada como resuelto hasta que la prueba de aceptación correspondiente se haya ejecutado y su resultado conste en el informe.
6. Distingue explícitamente: `CONFIRMADO EN CÓDIGO`, `REPRODUCIDO EN PRUEBA`, `VALIDADO EN STAGING`, `VALIDADO EN PRODUCCIÓN`. No son equivalentes.
7. No publicar secretos, claves, tokens de pago, correos de clientes ni payloads de webhook completos. Las claves del cliente Supabase con prefijo `sb_publishable_` son de naturaleza pública, pero no deben confundirse con `service_role` ni con secretos.
8. No modificar ni restaurar artefactos de datos del bot como efecto lateral. Si hace falta una prueba local, usa datos sintéticos y restaura los artefactos antes del commit.
9. Antes de tocar `main`: revisar commits recientes; ejecutar `git pull --rebase origin main` si se trabaja con el clon local y resolver artefactos de bot combinando, nunca pisando los datos automáticos.
10. Si una corrección necesita desplegar SQL o una Edge Function de Supabase, no digas que está en producción hasta tener evidencia de la migración y de la función desplegada.

## Contexto del proyecto

- SharPicks es un frontend estático en `web/`; la publicación se coordina con `.github/workflows/sitio_web.yml`.
- La lógica deportiva y precálculo viven en Python y GitHub Actions; la web consume Supabase y/o `web/datos/hoy.json`, y consulta ESPN para el marcador/estadísticas en directo.
- Supabase implementa Auth, RLS, monedas, accesos premium, combinadas, suscripciones y comentarios.
- Los pagos se gestionan por Mercado Pago y Stripe, con funciones en `supabase/functions/`.
- El antiguo `app.py` / `dashboard_ui.py` de Streamlit sigue en el repositorio; no eliminarlo sin un plan de retirada y una verificación de producción por parte del propietario.

## Estado inicial de los hallazgos (no equivale a que se hayan reparado)

| ID | Prioridad | Tema | Estado |
|---|---|---|---|
| SHP-001 | P1 | Webhooks pueden contestar éxito pese a fallos de escritura | Abierto |
| SHP-002 | P1 | Activación de VIP único no atómica con la idempotencia | Abierto |
| SHP-003 | P1/P2 | Migraciones de pago no totalmente reproducibles desde SQL versionado | Abierto |
| SHP-004 | P1 condicionado | INSERT directo a perfiles / columnas sensibles | Abierto; comprobar grants efectivos |
| SHP-005 | P1 comercial | La bandera `premium_con_cuenta` también abre el enlace VIP | Abierto |
| SHP-006 | P1/P2 | Script SQL histórico puede degradar funciones recientes | Abierto |
| SHP-007 | P2 | Reserva de precio fundador no atómica | Abierto |
| SHP-008 | P2 | Parser de fecha no reconoce offset UTC negativo | Abierto |
| SHP-009 | P2 | Sólo se consulta el primer bloque de 40 partidos en vivo | Abierto |
| SHP-010 | P2 | Fallo de lectura se presenta como lista vacía | Abierto |
| SHP-011 | P2 | El porcentaje puede mostrar NaN % | Abierto |
| SHP-012 | P2 | Workflow puede verse verde con fallos opcionales y sin tests frontend | Abierto |
| SHP-013 | P2 | Aviso de privacidad incompleto respecto a métodos/proveedores | Abierto; requiere datos legales del responsable |
| SHP-014 | P2 | Comentarios públicos sin límite de frecuencia servidor | Abierto |

## Orden de corrección recomendado

### Bloque A — integridad y seguridad (antes de activar o expandir cobros)
- SHP-001 y SHP-002: diseñar el procesamiento de webhook para que sea reintentable e idempotente de extremo a extremo; implementar acreditación/activación de pago en una RPC transaccional.
- SHP-003: comprobar que cada función, tabla e índice que usa la operación comercial se crea desde migraciones SQL versionadas; no reconstruir funciones a ciegas desde comentarios.
- SHP-004: revocar INSERT de `anon`/ `authenticated` en `perfiles`; mantener solo las operaciones de perfil explícitamente permitidas; verificar en staging y producción.
- SHP-005: separar configuración de acceso a picks premium de configuración de acceso a Telegram VIP.
- SHP-006: consolidar las definiciones de esquema, marcar scripts históricos como no volver a ejecutar y prevenir degradaciones.
- SHP-007: definir con el propietario si un puesto fundador se libera o queda reservado cuando cancela y hacer reserva atómica.

### Bloque B — fiabilidad visible
- SHP-008: parser ISO compatible con `Z`, offsets positivos/negativos y fechas sin zona.
- SHP-009: agenda rotatoria con un límite por pasada que garantice que todos los partidos elegibles se consultan.
- SHP-010: estados separados `cargando`, `vacío`, `error` para picks, combinadas, historial y comentarios.
- SHP-011: porcentajes protegidos contra denominador cero.
- SHP-012: tests obligatorios previos al despliegue; fallos opcionales visibles en summary/alerta, y fallo de publicación canónica de Cloudflare no silencioso.

### Bloque C — protección y cumplimiento
- SHP-013: actualizar privacidad con datos reales de responsable y proveedores; no inventar nombre legal, domicilio, correo o plazos. Requiere validación del propietario y revisión legal.
- SHP-014: endpoint server-side con límite de frecuencia y validación antiabuso para comentarios; la página no debe poder leer comentarios de otros usuarios.

## Evidencia y validaciones

- La ejecución de “Sitio web” que se comprobó, run [39102584649](https://github.com/HectorMontiel/mundial-2026-predictor/actions/runs/39102584649), finalizó correctamente y el paso de Cloudflare Pages fue exitoso en esa ejecución.
- Esta señal solo valida ese despliegue concreto; no certifica RLS, pagos, navegación ni contenido real de producción.
- El navegador/herramienta de lectura usada durante esta sesión no pudo recuperar `https://sharpicks.pages.dev/` (error de caché/conectividad de herramienta). No debe registrarse como fallo comprobado del sitio ni como validación del mismo.
- La auditoría es de código estático; los hallazgos dependientes de secretos, permisos reales, configuración de Supabase, proveedor de pagos o cuenta real no se pueden dar por reproducidos sin pruebas controladas.

## Registro de cambios de esta auditoría

| Fecha CDMX | Cambio | Evidencia |
|---|---|---|
| 2026-10-18 | Creación de la rama de auditoría y del informe maestro | Ver commits de `audit/sharpicks-bughunter-2026-10-18` |
| 2026-10-18 | Revisión estática de frontend, SQL, Edge Functions y workflow del sitio | Evidencia enlazada en el informe maestro |

## Formato obligatorio al resolver un hallazgo

Añade un registro en el informe maestro:
- ID y descripción.
- Commit/PR con el cambio.
- Archivos afectados.
- Prueba exacta ejecutada y resultado (comando o enlace a CI).
- Validación en staging (si aplica).
- Validación en producción (si aplica).
- Riesgos restantes.
- Estado: `ABIERTO`, `CORREGIDO EN CÓDIGO`, `PASÓ TESTS`, `VALIDADO EN STAGING`, `VALIDADO EN PRODUCCIÓN`, o `BLOQUEADO POR ACCESO`.

Nunca usar simplemente “listo” como evidencia.


## Inventario y revisión cruzada adicional — 18-oct-2026

- Un árbol recursivo de la rama principal arrojó 1.733 paths y 97 archivos de prueba con nombre tipo test*.py; 62 paths están directamente relacionados con la web, hosting, funciones Supabase y workflows.
- Leídos parcialmente para revisar cobertura: test_v379.py, test_v383.py, test_v389.py, test_v390.py, test_v394.py, test_v395.py, test_v396.py y test_v400.py. Son en gran parte pruebas de estructura/código fuente; no equivalen a validación de Postgres real, APIs de pago o navegador.
- Se agregaron tres hallazgos nuevos al informe maestro: SHP-015 (RLS de picks premium permite lectura desde el inicio del partido pese a que la nota de v389 dice al terminar), SHP-016 (precio de la interfaz calculado por precios_cuota, pero la función SQL canónica public.precio_pick usa ajustes por categoría y no contempla tipo error), SHP-017 (fallos al subir datos premium/combinadas pueden quedar como warning mientras exportar_web.py devuelve éxito).
- Estos hallazgos están confirmados como discrepancias en el código fuente; el estado efectivo de Supabase y la intención de negocio donde los documentos se contradicen aún necesitan validación antes de corregir.
- Último commit de main observado después de crear la rama: 1e077067cf18afb2ad548c9fa859908200a7bd48 (precálculo automático del 18-oct-2026 a las 06:55:32 UTC). Antes de realizar cambios funcionales, volver a consultar main y rebasar con cuidado.
- El sitio sharpicks.pages.dev no pudo recuperarse con el navegador disponible en esta sesión; no confundir esa limitación de herramienta con un fallo de producción.
- Aún no se han ejecutado aquí los 97 tests, no se ha leído cada archivo del repositorio y no hay verificación directa de la base desplegada. No anunciar la auditoría como completa.


## Estado de la rama compartida y PR #2 — 18-oct-2026

La rama y la PR evolucionaron durante la revisión. La PR [#2](https://github.com/HectorMontiel/mundial-2026-predictor/pull/2) sigue en **borrador, sin merge**. No representa una aprobación de producción. En la misma rama aparecieron commits candidatos v402 para fechas/feed en vivo, estados de error, historial, permisos de perfiles, enlace VIP, webhooks de pagos, comentarios con rate limit y validaciones de build. Estos commits aparecen con autor GitHub HMREY; no se debe inferir qué agente los escribió.

### Hallazgos con una corrección candidata presente en la rama, pendiente de validar
- SHP-001/002: los webhooks propagan algunos errores y los pagos VIP únicos usan la RPC transaccional procesar_vip_unico.
- SHP-004: se revoca INSERT directo a perfiles y se limitan actualizaciones a columnas permitidas.
- SHP-005: enlace de Telegram VIP usa telegram_vip_abierto, separada de premium_con_cuenta.
- SHP-008: parser ISO pasa a web/fechas.js y test_web_v402.cjs cubre offsets con Z, + y -.
- SHP-009: el bucle en vivo usa vivoCursor para rotar el grupo de hasta 40 partidos por pasada.
- SHP-010/011: se separan algunos estados de error de los estados vacíos; se protegen porcentajes contra denominador cero.
- SHP-012: sitio_web.yml incluye validaciones previas y un resumen de integraciones/despliegue.
- SHP-014: los comentarios pasan por Edge Function y RPC con límite por huella.

**Todo lo anterior es “CORRECCIÓN CANDIDATA EN RAMA”, no “validado”.** Faltan pruebas ejecutadas y, para SQL/Edge Functions, aplicar la migración y desplegar la función en staging antes de darlo por corregido.

### Hallazgos que siguen abiertos en la rama consultada
- SHP-003: la historia de migraciones de pagos sigue sin reproducir todo el esquema/funciones.
- SHP-006: web/negocio.sql sigue conteniendo definiciones históricas que pueden degradar funciones; el comentario preventivo no reemplaza una migración canónica segura.
- SHP-007: cupo fundador sigue calculado por lectura separada del checkout; pagos únicos con estado pagado tampoco entran en el conteo de estado authorized.
- SHP-015: la política premium sigue permitiendo lectura desde p.inicio <= now() en los scripts inspeccionados, mientras v389 documenta que debe abrirse al terminar. Requiere decidir y aplicar la regla actual.
- SHP-016: el precio mostrado en cuenta.js sigue calculado por precios_cuota, mientras precio_pick en negocio.sql usa ajustes por nivel y no contempla tipo error de forma explícita.
- SHP-017: exportar_web.py aún puede devolver 0 después de fallos al subir contenido premium/combinadas.

### Validación bloqueada
Intenté clonar la rama de forma superficial para ejecutar Node/Python tests; la terminal no pudo resolver github.com. Por tanto no se ha ejecutado test_web_v402.cjs, test_v400.py ni el resto de la suite desde este entorno. La PR no debe fusionarse hasta ejecutar esos tests en el clon local/CI y revisar logs reales.


---

## Estado verificable actualizado — 18 de octubre de 2026, 10:16 CDMX

Esta sección sustituye cualquier frase anterior que dijera que no se tenía acceso a Supabase. La auditoría pasó de revisar fuentes a comprobar parte del esquema activo. **No equivale todavía a una prueba E2E de navegador ni a una validación completa de pagos.**

### Qué sí se ejecutó y se comprobó

1. **Corrección de privacidad financiera v403 desplegada.** Se aplicó la migración `v403_finanzas_rpc_auth` al proyecto Supabase que usa SharPicks. La migración aparece en el historial como versión `20261018150201`. Después de aplicarla, una consulta de permisos confirmó: `anon_execute=false`, `authenticated_execute=true`, `security_definer=true` y la guarda `auth.uid() = p_user_id` presente en `public.monthly_category_summary(uuid,integer,integer)`. No se consultó ni se exportó ninguna transacción de usuario.
2. **Migración v402 y v404 validadas contra el esquema real sin persistir cambios.** Se ejecutó el contenido completo de ambas migraciones dentro de una transacción de comprobación seguida de `ROLLBACK`. El SQL compiló; las comprobaciones de firmas de funciones, permisos de RPC, política premium, comentarios y cálculo de precios finalizaron. Eso acredita compatibilidad sintáctica/estructural con el esquema actual; no significa que v402/v404 estén desplegadas.
3. **Precio real de producción cotejado.** `public.precio_pick` ya consulta `public.precios_cuota` en producción. Las 5 bandas son 1.00–1.30 = 5 monedas; 1.30–1.60 = 8; 1.60–2.00 = 12; 2.00–3.00 = 18; 3.00–99.00 = 25. En la prueba dentro de la transacción: cuota 1.04, premium = 5; error de cuota 3.50 = 25; pick no premium con cuota 1.50 = 0. Por eso SHP-016 no era un fallo de cobro activo: era una discrepancia del SQL de instalación/versionado, corregida en esta rama.
4. **Política premium de producción cotejada.** La política desplegada sólo habilita lectura pública cuando `p.estado` es `verde`, `roja` o `nula`; VIP/desbloqueos se contemplan por separado. SHP-015 tampoco era un fallo activo de la política en producción: la discrepancia estaba en los SQL históricos/versionados, que ahora usan la misma condición.
5. **Pruebas de la rama aprobadas en el SHA `3f8ed123e9fdb6ecb17a5ca9ee56c2943b0621cb`.** [Validación sin despliegue](https://github.com/HectorMontiel/mundial-2026-predictor/actions/runs/39144109592) y [tests seguros](https://github.com/HectorMontiel/mundial-2026-predictor/actions/runs/39144109604) terminaron en verde. Incluyen pruebas de fechas, guardas de interfaz, 5 pruebas de fallos de sincronización premium/combinadas y las pruebas existentes `test_v383.py`, `test_v389.py`, `test_v390.py`, `test_v394.py`, `test_v395.py`, `test_v396.py`, `test_v400.py`. La validación añadida de Deno comprobó sintaxis/tipos de las cinco Edge Functions candidatas (`comentario`, `vip`, `stripe`, `mp-webhook`, `stripe-webhook`).

### Qué sigue sin estar desplegado en producción

- La migración `supabase/v402_bughunter_hardening.sql` (perfiles, enlace VIP, reserva de fundador, rate limit de comentarios y RPC de pago único).
- La migración `supabase/v404_precios_cuota_canonico.sql` (hace reproducible el cálculo de precio que ya coincide con producción).
- Las versiones candidatas de las Edge Functions y la interfaz nueva de comentarios.
- Las correcciones de interfaz/exportador están probadas en CI, pero aún dependen de fusionar la PR y de que el workflow de sitio termine correctamente para considerarse desplegadas.

### Historial de fallos y cómo quedó

Los fallos que se ven en las capturas correspondían a revisiones previas de la rama. Se detectó una versión de `v402_bughunter_hardening.sql` con contenido duplicado/truncado; fue reconstruida, y la migración completa se volvió a ejecutar en una transacción de comprobación. Después, una aserción nueva de la suite dio un falso positivo por usar un regex demasiado amplio; se corrigió y la suite volvió a ejecutarse en verde. Los logs de los fallos anteriores no se ocultan: demuestran por qué no se debe equiparar un run antiguo en verde con el estado actual.

### SHP-018 — RPC financiera SECURITY DEFINER permitía consultar el ID de otro usuario

**Estado:** RESUELTO EN PRODUCCIÓN (v403, 18-oct-2026).  
**Hallazgo:** `public.monthly_category_summary(p_user_id, p_year, p_month)` tenía ejecución permitida a `anon` y no verificaba la propiedad de `p_user_id`.  
**Corrección:** la función ahora filtra por `auth.uid() = p_user_id` o `auth.role() = 'service_role'`; se revocó EXECUTE a `public/anon` y se concedió a `authenticated/service_role`.  
**Verificación posterior:** `anon_execute=false`, `authenticated_execute=true`, guarda de propiedad presente. No se usaron datos financieros reales en la prueba.  
**Registro versionado:** [supabase/v403_finanzas_rpc_auth.sql](https://github.com/HectorMontiel/mundial-2026-predictor/blob/audit/sharpicks-bughunter-2026-10-18/supabase/v403_finanzas_rpc_auth.sql).

### Criterio de publicación vigente

La PR sigue siendo el vehículo de los cambios de SharPicks. No se fusionará hasta que el CI más reciente siga en verde, se actualice el informe con el orden de despliegue, y las migraciones v402/v404 y las Edge Functions se desplieguen en una secuencia que no deje a la página apuntando a endpoints inexistentes. El sitio no se declara validado hasta comprobar el resultado de la ejecución posterior a la fusión y hacer smoke tests del frontend publicado.


## Actualización de despliegue — 18 de octubre de 2026, 10:35 CDMX

### Cambios ya aplicados a producción (Supabase)
- Migración `20261018150201 / v403_finanzas_rpc_auth`: se restringió `monthly_category_summary` para impedir consultas de otros usuarios. Verificación posterior: `anon_execute=false`, `authenticated_execute=true`, guarda de propiedad presente.
- Migración `20261018163026 / v402_bughunter_hardening`: aplicada correctamente. Verificación posterior: existen `comentarios_rate_limit`, `registrar_comentario`, `procesar_vip_unico` y `reservar_lugar_fundador`; `anon` no puede ejecutar `enlace_vip` ni `desbloquear`; `anon`/autenticados no pueden insertar perfiles. `telegram_vip_abierto=0`.
- Migración `20261018163111 / v404_precios_cuota_canonico`: aplicada correctamente. Las bandas activas quedan iguales a las que ya usaba la base: 5 / 8 / 12 / 18 / 25 monedas. Prueba de función: cuota 1.04 premium → 5; error de cuota 3.50 → 25; pick 1.50 no premium → 0.
- Edge Functions desplegadas, todas `ACTIVE`: `comentario` v1; `vip` v5; `stripe` v2; `mp-webhook` v6; `stripe-webhook` v2. Las cinco versiones de esta rama pasaron `deno check` en CI.

### Secuencia segura de comentarios
La migración v402 crea la RPC/table de rate limit pero deja temporalmente el INSERT directo de comentarios para evitar cortar la web antigua. La nueva Edge Function ya está desplegada. Tras fusionar esta PR y confirmar el despliegue de la web nueva, se debe probar el formulario de comentarios; después ejecutar `supabase/v405_comentarios_solo_edge.sql` para revocar el INSERT directo. **v405 aún no se ha ejecutado en producción.**

### CI actual de la rama
En el SHA `1f5984e2cf444b0d044b88e6facb712800ba2f6b`:
- [Validar SharPicks sin desplegar](https://github.com/HectorMontiel/mundial-2026-predictor/actions/runs/39145101203): success.
- [Tests seguros SharPicks v402](https://github.com/HectorMontiel/mundial-2026-predictor/actions/runs/39145101110): success.
La rama pasó validación de JS, fechas, controles estáticos, Deno check y las pruebas Python de exportador/combinadas y regresión. Los fallos anteriores eran de commits más antiguos y quedaron superados; sus referencias siguen en el historial, no se borraron.

### Aún no se ha desplegado la web estática nueva
El frontend modificado todavía necesita que esta PR se fusione y que el workflow canónico de Cloudflare Pages termine exitosamente. Después se debe verificar el sitio servido y probar el formulario de comentarios desde la página. Sólo tras esa comprobación se aplicará v405 y se comprobará que INSERT directo en comentarios ya no está permitido.


---

## Estado final de despliegue — 18-oct-2026

**Correcciones principales desplegadas.** La PR #2 está fusionada en `main`; commit de publicación `68d8f139834fce15a6867a5bad6ff1912bf05b02`. El workflow de sitio [39146143725](https://github.com/HectorMontiel/mundial-2026-predictor/actions/runs/39146143725) terminó en verde, con validación pre-publicación y Cloudflare Pages exitoso. La prueba HTTP desde GitHub Actions [39147099500](https://github.com/HectorMontiel/mundial-2026-predictor/actions/runs/39147099500) confirmó homepage/cuenta HTTP 200 y validación esperada 400 del endpoint de comentarios sin insertar datos.

**Migraciones aplicadas a Supabase:** v403_finanzas_rpc_auth, v402_bughunter_hardening, v404_precios_cuota_canonico y v405_comentarios_solo_edge. Los permisos posteriores muestran: `anon/authenticated INSERT comentarios=false`, `service_role INSERT comentarios=true`, tabla de rate limit y RPC de comentarios presentes, y RPC financiera no ejecutable por anon. Las funciones `comentario`, `vip`, `stripe`, `mp-webhook` y `stripe-webhook` coinciden exactamente con los archivos de `main`.

Detalles, porqués, pruebas, limitaciones y enlaces: [DESPLIEGUE_SHARPICKS_2026-10-18.md](./DESPLIEGUE_SHARPICKS_2026-10-18.md).

**Aún abierto:** SHP-003/SHP-006 (instalación desde cero/migraciones históricas), pagos E2E con sandbox y un comentario válido con correo en staging. No declarar auditoría total certificada ni haber validado pagos reales.


## Pruebas transaccionales adicionales — finalización del 18-oct-2026

Además de los workflows, se ejecutaron tres comprobaciones directas en Supabase dentro de transacciones que terminaron en `ROLLBACK`; no se dejaron suscripciones, modificaciones de perfil, reservas ni comentarios sintéticos persistidos:

- **Pago VIP único/idempotencia:** la primera llamada a `procesar_vip_unico` insertó una sola suscripción de prueba; la segunda con el mismo ID devolvió el resultado de duplicado; `plan_hasta` no volvió a extenderse y el conteo de filas quedó en uno durante la prueba. PASS.
- **Reserva fundador:** dos llamadas para la misma cuenta sintética/reversible produjeron una sola reserva pendiente activa; no se duplicó la plaza. PASS.
- **Límite de comentarios:** cinco llamadas sintéticas se aceptaron y la sexta devolvió `rate_limit`; la transacción se revirtió. PASS.

Estas pruebas validan la lógica PostgreSQL desplegada, no sustituyen una compra real/sandbox ni validan la entrega del webhook por Stripe/Mercado Pago. El smoke HTTP de producción sigue siendo no destructivo: comprueba el endpoint con un body inválido y no crea comentarios.
