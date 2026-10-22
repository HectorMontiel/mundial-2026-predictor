-- v447 — «QUIÉN ANOTA PRIMERO» Y EL ANÁLISIS EN VARIAS HORAS (sólo para medir).
--   1) La IA también dice qué equipo anota primero (o «nadie») con su probabilidad,
--      y al terminar se le pone ✅/❌ con el primer gol real (ESPN).
--   2) `ia_ventanas`: el MISMO partido analizado otra vez ~12 h, ~6 h y ~2 h antes,
--      con noticias de la web. NO lo ve el usuario (sólo el servidor): sirve para
--      saber a qué hora acierta más la IA en cada deporte y en cada predicción;
--      cuando se sepa, la app enseña el de la mejor hora.
-- Migración NUEVA: no se re-ejecuta ninguna anterior.
alter table public.ia_analisis add column if not exists primero_anota text;
alter table public.ia_analisis add column if not exists prob_primero numeric;
alter table public.ia_analisis add column if not exists ok_primero boolean;

create table if not exists public.ia_ventanas (like public.ia_analisis including all);
alter table public.ia_ventanas add column if not exists ventana text;
alter table public.ia_ventanas add column if not exists base text;
create index if not exists ia_ventanas_base on public.ia_ventanas (base);
alter table public.ia_ventanas enable row level security;
revoke all on table public.ia_ventanas from public, anon, authenticated;
grant all on public.ia_ventanas to service_role;

notify pgrst, 'reload schema';
