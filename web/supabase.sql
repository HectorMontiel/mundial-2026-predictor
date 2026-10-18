-- v377 — La base de datos del sitio web (Supabase, plan gratis).
-- Se pega una sola vez en Supabase → SQL Editor → Run.
--
-- picks: cada apuesta «se mete» con su resultado. La escribe el cálculo de
-- GitHub (`exportar_web.py`, con la clave de servicio, que se salta las
-- reglas); la página sólo puede LEER (clave pública «anon»).

create table if not exists public.picks (
  id            text primary key,           -- fecha|partido|apuesta (sha1)
  fecha         date not null,              -- día del partido (hora de CDMX)
  inicio        timestamptz,
  deporte       text,
  liga          text,
  partido       text not null,
  apuesta       text not null,
  cuota         numeric(6,3),
  prob          numeric(5,3),               -- lo que acierta de verdad (medido)
  elige         boolean default false,      -- ⭐ ELIGE
  porque        text,
  estado        text default 'pendiente'    -- pendiente | vivo | verde | roja | nula
                check (estado in ('pendiente','vivo','verde','roja','nula')),
  resultado_c1  text,
  marcador      text,
  premium       boolean default false,      -- para más adelante (modelo de negocio)
  actualizado   timestamptz default now()
);
-- v378 — lo en vivo: el partido de ESPN (`espn_vivo`) y los escudos
alter table public.picks add column if not exists espn text;
alter table public.picks add column if not exists logo_h text;
alter table public.picks add column if not exists logo_a text;
alter table public.picks add column if not exists girado boolean default false;
create index if not exists picks_fecha on public.picks (fecha);

alter table public.picks enable row level security;
drop policy if exists "todos leen los picks" on public.picks;
create policy "todos leen los picks" on public.picks for select using (true);
grant select on public.picks to anon, authenticated;
grant all on public.picks to service_role;

-- El historial público: verdes y rojas por día (y de las ⭐).
create or replace view public.historial with (security_invoker = true) as
select fecha,
       count(*) filter (where estado = 'verde')               as verdes,
       count(*) filter (where estado = 'roja')                as rojas,
       count(*) filter (where estado = 'verde' and elige)     as verdes_elige,
       count(*) filter (where estado = 'roja'  and elige)     as rojas_elige,
       round(sum(case when estado = 'verde' then cuota - 1
                      when estado = 'roja'  then -1 else 0 end) * 100, 1) as gana_por_100
from public.picks
group by fecha
order by fecha desc;
grant select on public.historial to anon, authenticated;

-- Usuarios (inicio de sesión de Supabase): un perfil por cuenta.
create table if not exists public.perfiles (
  id         uuid primary key references auth.users on delete cascade,
  nombre     text,
  creado     timestamptz default now()
);
alter table public.perfiles enable row level security;
drop policy if exists "cada quien su perfil" on public.perfiles;
create policy "cada quien su perfil" on public.perfiles
  for all using (auth.uid() = id) with check (auth.uid() = id);
revoke insert on public.perfiles from anon, authenticated;
revoke update on public.perfiles from authenticated;
grant select on public.perfiles to authenticated;
grant update (nombre) on public.perfiles to authenticated;
notify pgrst, 'reload schema';
