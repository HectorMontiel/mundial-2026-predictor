-- v396 — combinadas del día (de cada deporte y mixtas) y probabilidades de la IA
create table if not exists public.combinadas (
  id text primary key,
  fecha date not null,
  alcance text not null,          -- el deporte, o «Mixta»
  tipo text not null,             -- combinada (2 patas, 1,30-1,60) | alta (3 patas, 1,80-2,60)
  cuota numeric, prob numeric,
  premium boolean not null default false,
  inicio timestamptz,
  patas jsonb not null default '[]'::jsonb,
  estado text not null default 'pendiente',
  actualizado timestamptz default now()
);
alter table public.combinadas enable row level security;
drop policy if exists "combinadas públicas" on public.combinadas;
create policy "combinadas públicas" on public.combinadas for select using (true);
grant select on public.combinadas to anon, authenticated;
grant all on public.combinadas to service_role;

-- la probabilidad de cada predicción de la IA
alter table public.ia_analisis
  add column if not exists prob_goles numeric,
  add column if not exists prob_ambos numeric,
  add column if not exists prob_corners numeric,
  add column if not exists prob_tarjetas numeric,
  add column if not exists prob_marcador numeric;
notify pgrst, 'reload schema';
