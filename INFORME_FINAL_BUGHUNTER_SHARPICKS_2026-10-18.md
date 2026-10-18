# SharPicks — Informe final Bug Hunter
**Corte:** 18 de octubre de 2026, 15:52 CDMX  
**Repositorio:** [HectorMontiel/mundial-2026-predictor](https://github.com/HectorMontiel/mundial-2026-predictor)  
**Producción:** [https://sharpicks.pages.dev/](https://sharpicks.pages.dev/)  
**Propósito:** fuente compartida de verdad para que Claude y ChatGPT continúen sin repetir arreglos, confundir notas históricas con estado actual ni dar por validado algo que no se probó.

## Veredicto

**Las correcciones de seguridad y reproducibilidad enumeradas aquí están fusionadas en `main` y pasan las validaciones declaradas. La auditoría global no equivale a una certificación completa de pagos: falta una prueba de checkout/webhook end-to-end usando las cuentas sandbox de Stripe y Mercado Pago.** No se creó un cobro real ni se envió un comentario real de prueba al correo de producción.

No se midió una mejora de velocidad o un porcentaje global de rendimiento; no hay medición antes/después que permita dar ese número. La mejora demostrada es de corrección, control de acceso, manejo de errores y reproducibilidad de base de datos.

## Entregas fusionadas

| PR | Resultado | Evidencia |
|---|---|---|
| [#2 — correcciones de seguridad y consistencia](https://github.com/HectorMontiel/mundial-2026-predictor/pull/2) | Fusionada. Incluye correcciones de errores en la sincronización del sitio, endurecimiento de RPC y reserva de plazas fundador, además de pruebas de regresión. | [CI sin despliegue](https://github.com/HectorMontiel/mundial-2026-predictor/actions/runs/39144109592), [tests seguros](https://github.com/HectorMontiel/mundial-2026-predictor/actions/runs/39144109604) |
| [#3 — documentación post-despliegue](https://github.com/HectorMontiel/mundial-2026-predictor/pull/3) | Fusionada. Actualiza el estado compartido y los pasos de continuidad. | [Run de tests](https://github.com/HectorMontiel/mundial-2026-predictor/actions/runs/39152124264) |
| [#4 — delimitadores de `precio_pick`](https://github.com/HectorMontiel/mundial-2026-predictor/pull/4) | Fusionada. Corrige `as $ / $;` a un cuerpo SQL delimitado correctamente y agrega una prueba que detecta el defecto. | [Validación](https://github.com/HectorMontiel/mundial-2026-predictor/actions/runs/39160589633), [tests seguros](https://github.com/HectorMontiel/mundial-2026-predictor/actions/runs/39160589503) |
| [#5 — instalación desde cero](https://github.com/HectorMontiel/mundial-2026-predictor/pull/5) | Fusionada. Versiona las tablas de IA, paquetes y compras que faltaban en el repositorio, añade la vista `ia_aciertos`, crea `picks.tipo` antes de compilar `precio_pick` y añade CI real con PostgreSQL 16. | [Instalación limpia PASS](https://github.com/HectorMontiel/mundial-2026-predictor/actions/runs/39169368102), [tests seguros PASS](https://github.com/HectorMontiel/mundial-2026-predictor/actions/runs/39169368107), [validación PASS](https://github.com/HectorMontiel/mundial-2026-predictor/actions/runs/39169368099) |

Después de la fusión de #5, el workflow del sitio terminó en verde: [publicación web PASS](https://github.com/HectorMontiel/mundial-2026-predictor/actions/runs/39169534836).

## Correcciones activas y validación en producción

### SHP-018 — Resumen mensual financiero sin guarda de propiedad
**Estado: RESUELTO en producción mediante `v403_finanzas_rpc_auth`.**

La función `public.monthly_category_summary(p_user_id, p_year, p_month)` era `SECURITY DEFINER` y permitía ejecución anónima sin comprobar que `p_user_id` fuera la persona que consultaba. La función ahora permite la consulta sólo si `auth.uid() = p_user_id` o la petición usa `service_role`. Después de aplicar la migración se verificó: `anon_execute=false`, `authenticated_execute=true`, y la guarda de propiedad está presente. La prueba no leyó ni exportó movimientos financieros personales.

### SHP-004/005/007/014 — Acceso a perfiles, enlace VIP, reserva fundador y comentarios
**Estado: migración `v402_bughunter_hardening` aplicada y comprobada; `v405_comentarios_solo_edge` aplicada.**

- `anon` y `authenticated` no pueden insertar perfiles directamente.
- La RPC `desbloquear(text)` no es ejecutable por `anon`; permanece ejecutable por `authenticated`.
- El enlace VIP no es ejecutable por `anon`; permanece habilitado para sesión autenticada con la regla de negocio.
- `comentarios_rate_limit` y `registrar_comentario` existen en la base. La inserción directa antigua en `comentarios` está cerrada; la ruta pública pasa por la Edge Function.
- El smoke test después de v405 verificó homepage HTTP 200 y que una solicitud de comentario inválida devuelve 400, sin crear registros. [Run de smoke test, intento 2](https://github.com/HectorMontiel/mundial-2026-predictor/actions/runs/39147099500).

### SHP-016 — Consistencia de precios por cuota
**Estado: la migración `v404_precios_cuota_canonico` está aplicada.**

Se consultó la tabla de precios en producción y se probó `precio_pick` con datos sintéticos: cuota 1.04 de selección premium → 5 monedas; mercado de error a cuota 3.50 → 25; selección normal no premium a cuota 1.50 → 0. Las cinco bandas presentes en producción son 5/8/12/18/25 monedas: 1.00–1.30, 1.30–1.60, 1.60–2.00, 2.00–3.00 y 3.00–99.00, respectivamente. La política de `picks_premium` sólo expone el texto públicamente cuando el pick está liquidado (`verde`, `roja`, `nula`), además de sus reglas de VIP/desbloqueo.

### SHP-001/002/006 — Errores de pago e idempotencia
**Estado: las rutas de código fueron endurecidas; comprobada la idempotencia de las operaciones de base, no el checkout externo completo.**

- Los webhooks deben fallar con un HTTP reintentable si la persistencia no se completa; no se debe contestar éxito cuando una escritura de pago falla.
- `procesar_vip_unico` fue probado en una transacción: primera llamada aplicada, segunda llamada duplicada no extendió el periodo y quedó una sola fila.
- La reserva de fundador fue probada en una transacción: la segunda solicitud reutilizó la reserva pendiente y no creó otra fila.
- `acreditar_compra` se probó contra la base productiva dentro de una transacción reversible: primera llamada `ok`, duplicado `ya`, incremento de 50 monedas, una fila en `compras` y un movimiento. **La transacción terminó en `ROLLBACK`; no quedó una compra, saldo ni movimiento de prueba.**
- La prueba de instalación limpia repite el escenario de compra duplicada en PostgreSQL 16 efímero y comprueba que sólo una acreditación se confirma.

### SHP-019 — El repositorio no reconstruía el esquema desde cero
**Estado: RESUELTO en los scripts versionados; instalación limpia PASS.**

Los archivos del repositorio no creaban tres objetos que sí estaban presentes en el proyecto activo: `ia_analisis`, `paquetes`, `compras`; tampoco reproducían `acreditar_compra` ni la vista agregada `ia_aciertos`. La instalación limpia también detectó el orden incorrecto de compilación de `precio_pick`: `picks.tipo` se añadía después del bootstrap que ya la referenciaba.

Correcciones:
- `supabase/v389_monedas.sql` versiona las tablas faltantes, el catálogo inicial de paquetes y `acreditar_compra`.
- `supabase/v399_ia_medicion.sql` versiona `ia_aciertos`.
- `web/negocio.sql` corrige delimitadores SQL y crea `picks.tipo` antes de compilar `precio_pick`.
- `supabase/v404_precios_cuota_canonico.sql` usa referencias de campos compuestos compatibles con PostgreSQL.
- `tests/test_instalacion_limpia.sql` y `.github/workflows/test_instalacion_limpia.yml` levantan PostgreSQL 16 efímero, aplican todos los scripts en orden y validan tablas, vistas, permisos, precios e idempotencia.
- Guía de ejecución: [supabase/INSTALACION_LIMPIA.md](https://github.com/HectorMontiel/mundial-2026-predictor/blob/main/supabase/INSTALACION_LIMPIA.md).

No se volvió a ejecutar el bootstrap en la base productiva. La reparación de reproducibilidad modifica los scripts versionados; no exige reconstruir la base que ya estaba operativa.

## Pruebas sintéticas transaccionales ejecutadas en la base conectada

Cada prueba terminó en `ROLLBACK` para no persistir las operaciones.

| Prueba | Resultado comprobado |
|---|---|
| Pago VIP de un solo uso | Primer procesamiento aplicado; repetición ignorada; no extendió el periodo otra vez; una fila. |
| Reserva fundador | Segunda petición reutilizó la reserva existente; una fila pendiente para esa cuenta. |
| Rate limit de comentarios | Cinco comentarios sintéticos aceptados; el sexto bloqueado; contador 6. |
| Compra de monedas | `ok` y luego `ya`; delta de 50 monedas, una fila de compra y un movimiento. |
| Precio por cuota | 1.04 premium → 5; error 3.50 → 25; normal no premium 1.50 → 0. |

La prueba transaccional no reemplaza un flujo real de checkout ni prueba el envío de correo de un comentario válido desde el navegador.

## Métricas del trabajo

- **Instalación limpia:** PASS; conjunto bootstrap/migraciones compilado y comprobado en PostgreSQL 16.
- **Pruebas de CI de la PR #5:** 3/3 verdes.
- **Workflow de publicación del sitio posterior a la fusión:** PASS.
- **Edge Functions revisadas en la comprobación post-despliegue:** 5/5 activas y con fuente coincidente con `main`: `comentario`, `vip`, `stripe`, `mp-webhook`, `stripe-webhook`.
- **Comprobaciones de permisos posteriores a migraciones:** resultados coincidentes con la política diseñada.
- **Velocidad/latencia:** sin medición antes/después; no se declara mejora cuantitativa.
- **Checkout externo end-to-end:** no ejecutado; sin una prueba sandbox de ambas pasarelas no se debe marcar como aceptado.

## Lo que sigue sin estar certificado

1. **Checkout y webhook E2E de Stripe y Mercado Pago en sandbox.** Requiere secretos de prueba y cuentas sandbox configuradas. No se hicieron compras reales. No hay que probar cobros productivos para cerrar esta validación.
2. **Comentario válido end-to-end en entorno de staging.** Se validó la ruta pública con una solicitud inválida y se probó la RPC/rate limit dentro de una transacción. No se envió un mensaje válido al correo de producción para no generar datos reales ni notificaciones sin necesidad.
3. **Prueba manual de navegador con una cuenta de usuario de prueba.** El smoke test de Actions cubre disponibilidad de página y ruta de comentarios; no sustituye un recorrido visual completo de iniciar sesión, ver saldo, comprar, desbloquear y cancelar VIP.

No bloquean la corrección del bootstrap ni la publicación del sitio; sí bloquean una declaración honesta de “pagos certificados de punta a punta”.

## Instrucciones para Claude y ChatGPT

1. Leer primero este archivo y después [la auditoría detallada](https://github.com/HectorMontiel/mundial-2026-predictor/blob/main/AUDITORIA_BUGHUNTER_SHARPICKS_2026-10-18.md) y [la continuidad compartida](https://github.com/HectorMontiel/mundial-2026-predictor/blob/main/CONTINUIDAD_AUDITORIA_SHARPICKS.md).
2. No volver a aplicar v402–v405 a producción a ciegas: constan en el historial de migraciones activo.
3. Para modificar el esquema, preparar una migración nueva, no reejecutar `web/negocio.sql` sobre una base ya migrada.
4. No declarar pagos validados si sólo pasó CI o una prueba de RPC. La prueba final debe usar sandboxes de los proveedores y debe comprobar el resultado recibido en SharPicks.
5. Si se corrige un hallazgo, actualizar este informe, la continuidad compartida y la prueba de aceptación correspondiente en el mismo PR.

## Historial importante

- Estado de producción, permisos y funciones tras v405: [smoke test](https://github.com/HectorMontiel/mundial-2026-predictor/actions/runs/39147099500).
- Corrección de bootstrap: [PR #4](https://github.com/HectorMontiel/mundial-2026-predictor/pull/4).
- Instalación limpia y DDL faltante: [PR #5](https://github.com/HectorMontiel/mundial-2026-predictor/pull/5).
- Publicación final después de PR #5: [workflow de sitio](https://github.com/HectorMontiel/mundial-2026-predictor/actions/runs/39169534836).

**Estado final del corte:** correcciones de seguridad y reproducibilidad fusionadas; migraciones de producción aplicadas y comprobadas; sitio publicado; pruebas automatizadas en verde. La prueba con proveedores de pago sandbox permanece explícitamente no certificada.
