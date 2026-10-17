-- v386-v389 — corrido en Supabase (SQL Editor) el 17-oct-2026.
-- Errores de cuota como picks, historial con los 💰 aparte, la IA medida,
-- fin del «gratis con cuenta», precio por cuota, paquetes y compras.
alter table public.picks add column if not exists tipo text default 'pick';
alter table public.picks add column if not exists casa text;
alter table public.picks add column if not exists ventaja numeric(6,3);
alter table public.picks add column if not exists gratis boolean default false;
alter table public.picks add column if not exists ctx jsonb;
-- (ver el historial, ia_analisis/ia_aciertos, precios_cuota, paquetes, compras y
--  acreditar_compra en el historial de la sesión v386-v389; resumen:)
--   historial: verdes/rojas sin 💰 + verdes_error/rojas_error
--   ia_analisis: lo que la IA predice; ia_aciertos: sus ✅/❌ contra el favorito
--   ajustes: premium_con_cuenta = 0; precio_diamante 10, platino 5, error 10
--   precios_cuota: 1,00-1,30 → 5 · 1,30-1,60 → 8 · 1,60-2,00 → 12 · 2,00-3,00 → 18 · 3,00+ → 25
--   paquetes: prueba 50/$29 · popular 100/$49 · pro 220/$99 · mega 500/$199
--   acreditar_compra(id, usuario, paquete, precio): una vez por pago (sólo service_role)
--   picks_premium: se abre al TERMINAR el partido (verde/roja/nula), no al empezar
--   perfiles: el usuario sólo puede cambiar nombre, usuario y deportes (sin insert)
