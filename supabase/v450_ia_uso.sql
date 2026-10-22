-- v450 — LA CUENTA DEL CUPO DE GEMINI: cuántas consultas se hacen por día, a qué
-- modelo y para qué (análisis con pick, sólo análisis, búsqueda, ventana), y a
-- qué hora se acabó el cupo. Sólo la lee el servidor (y el admin con SQL).
-- Migración NUEVA: no se re-ejecuta ninguna anterior.
create table if not exists public.ia_uso (
  id text primary key,
  fecha date not null,
  modelo text not null,
  tipo text not null,
  llamadas integer not null default 0,
  ok integer not null default 0,
  cupo_agotado boolean not null default false,
  agotado_a timestamptz,
  actualizado timestamptz not null default now()
);
alter table public.ia_uso enable row level security;
revoke all on table public.ia_uso from public, anon, authenticated;
grant all on public.ia_uso to service_role;
notify pgrst, 'reload schema';
