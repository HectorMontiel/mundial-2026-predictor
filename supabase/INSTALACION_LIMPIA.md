# Instalación limpia de SharPicks

Esta guía describe cómo reconstruir el esquema de SharPicks desde una base PostgreSQL/Supabase vacía usando el SQL versionado. **No la uses como lista de reejecución sobre producción.** En la base que ya está operativa, las migraciones históricas v383–v405 están registradas; no las vuelvas a aplicar a ciegas.

## Requisitos

- Proyecto Supabase recién creado, con Supabase Auth disponible (esquema `auth`, `auth.users`, `auth.uid()`, `auth.role()`).
- Roles `anon`, `authenticated` y `service_role` proporcionados por Supabase.
- Ejecutar en el SQL Editor con permisos de administrador, respetando el orden inferior.
- Desplegar las Edge Functions y la web sólo después de preparar el esquema y las variables/secrets.

## Orden de ejecución

1. `web/supabase.sql` — crea `picks`, `perfiles` y el historial inicial.
2. `web/negocio.sql` — bootstrap histórico de cuentas, monedas, desbloqueos, precios y Telegram. **Una sola vez en una base nueva.** No lo ejecutes encima de una base que ya recibió v383 o superior.
3. `supabase/v383_usuarios_vip.sql` — perfiles, códigos y suscripciones VIP.
4. `supabase/v389_monedas.sql` — columnas de picks y ahora también las definiciones base que faltaban en el repositorio: `ia_analisis`, `paquetes`, `compras`, permisos, precios de paquetes y `acreditar_compra`.
5. `supabase/v394_ia_que_meter.sql`
6. `supabase/v395_stripe_renovacion.sql`
7. `supabase/v396_combinadas.sql`
8. `supabase/v397_desbloquear_combinada.sql`
9. `supabase/v399_ia_medicion.sql` — crea `ia_medicion` y `ia_aciertos`.
10. `supabase/v400_telegram.sql`
11. `supabase/v401_comentarios.sql`
12. `supabase/v402_bughunter_hardening.sql`
13. `supabase/v404_precios_cuota_canonico.sql`
14. Desplegar la Edge Function `comentario` y la versión de la web que la invoca.
15. `supabase/v405_comentarios_solo_edge.sql` — último paso: revoca el INSERT directo antiguo en comentarios después de comprobar la ruta nueva.

`supabase/v403_finanzas_rpc_auth.sql` se ejecuta aparte: protege un resumen del esquema externo `finanzas` y exige que ese esquema/tabla exista. No forma parte del bootstrap independiente de SharPicks.

## Comprobación obligatoria

El workflow [test_instalacion_limpia.yml](../.github/workflows/test_instalacion_limpia.yml) ejecuta los scripts 1–14 en un PostgreSQL efímero de GitHub Actions, con funciones mínimas de Auth simuladas. Comprueba:

- existencia de las tablas y vistas de IA, paquetes y compras;
- permisos de lectura/escritura y que sólo `service_role` pueda invocar `acreditar_compra`;
- bandas de precio por cuota (1.04 premium → 5 monedas; error 3.50 → 25; normal no premium → 0);
- que un pago repetido con el mismo ID sólo acredite una vez, dentro de una transacción que termina en `ROLLBACK`.

La prueba de instalación no demuestra la entrega real de webhooks de Stripe/Mercado Pago ni sustituye las pruebas con sus sandboxes.

## Regla de mantenimiento

Toda nueva tabla/función que se use desde web, exportador o Edge Functions debe estar definida en una migración versionada y cubierta por el test de instalación limpia. No se deben dejar definiciones esenciales sólo en el SQL Editor manual ni en comentarios que describan cambios que el archivo no ejecuta.
