-- v383 — corrido en Supabase (SQL Editor) el 17-oct-2026.
-- Usuarios con nombre, administrador, códigos de regalo, suscripciones de
-- Mercado Pago, lugares de fundador y el enlace del VIP sólo para quien le toca.

alter table public.perfiles add column if not exists usuario text;
alter table public.perfiles add column if not exists admin boolean not null default false;
do $$ begin
  alter table public.perfiles add constraint usuario_valido check (usuario is null or usuario ~ '^[A-Za-z0-9_.]{3,20}$');
exception when duplicate_object then null; end $$;
create unique index if not exists perfiles_usuario on public.perfiles (lower(usuario));
revoke insert on public.perfiles from anon, authenticated;
revoke update on public.perfiles from authenticated;
grant update (nombre, deportes, usuario) on public.perfiles to authenticated;

-- al registrarse: el usuario elegido (si es válido y está libre)
create or replace function public.nuevo_usuario() returns trigger
language plpgsql security definer set search_path = public as $$
declare bienvenida int := coalesce((select valor::int from public.ajustes where clave = 'monedas_bienvenida'), 0);
        u text := nullif(new.raw_user_meta_data->>'usuario', '');
begin
  if u is not null and (u !~ '^[A-Za-z0-9_.]{3,20}$' or exists (select 1 from public.perfiles where lower(usuario) = lower(u))) then
    u := null;
  end if;
  insert into public.perfiles (id, nombre, usuario, monedas)
  values (new.id, coalesce(u, new.raw_user_meta_data->>'full_name', new.raw_user_meta_data->>'nombre', split_part(new.email, '@', 1)), u, bienvenida)
  on conflict (id) do nothing;
  if bienvenida > 0 then
    insert into public.movimientos (usuario, cantidad, motivo) values (new.id, bienvenida, 'bienvenida');
  end if;
  return new;
end $$;

create or replace function public.usuario_libre(u text) returns boolean
language sql stable security definer set search_path = public as $$
  select u ~ '^[A-Za-z0-9_.]{3,20}$' and not exists (select 1 from public.perfiles where lower(usuario) = lower(u));
$$;
grant execute on function public.usuario_libre(text) to anon, authenticated;

-- sólo para la función del servidor «entrar» (el correo nunca llega a la página)
create or replace function public.id_de_usuario(u text) returns uuid
language sql stable security definer set search_path = public as $$
  select id from public.perfiles where lower(usuario) = lower(trim(u)) limit 1;
$$;
revoke execute on function public.id_de_usuario(text) from public, anon, authenticated;
grant execute on function public.id_de_usuario(text) to service_role;

-- el administrador es VIP siempre y desbloquea sin gastar monedas
create or replace function public.es_pro() returns boolean
language sql stable security definer set search_path = public as $$
  select exists (select 1 from public.perfiles where id = auth.uid()
                 and (admin or (plan = 'pro' and (plan_hasta is null or plan_hasta > now()))));
$$;
create or replace function public.desbloquear(pick_id text) returns text
language plpgsql security definer set search_path = public as $$
declare p public.picks; precio int; saldo int; es_admin boolean;
begin
  if auth.uid() is null then return 'inicia sesión'; end if;
  select * into p from public.picks where id = pick_id;
  if not found then return 'no existe'; end if;
  if p.inicio <= now() then return 'ya empezó'; end if;
  if exists (select 1 from public.desbloqueos where usuario = auth.uid() and pick = pick_id) then return 'ok'; end if;
  select monedas, admin into saldo, es_admin from public.perfiles where id = auth.uid() for update;
  precio := case when es_admin then 0 else public.precio_pick(p) end;
  if coalesce(saldo, 0) < precio then return 'sin monedas'; end if;
  update public.perfiles set monedas = monedas - precio where id = auth.uid();
  insert into public.desbloqueos (usuario, pick, monedas) values (auth.uid(), pick_id, precio);
  if precio > 0 then
    insert into public.movimientos (usuario, cantidad, motivo, pick) values (auth.uid(), -precio, 'desbloqueo', pick_id);
  end if;
  return 'ok';
end $$;
revoke execute on function public.desbloquear(text) from public, anon;
grant execute on function public.desbloquear(text) to authenticated;

-- códigos de regalo: 1 mes de VIP, un solo uso (los 20 se generaron al correr esto)
create table if not exists public.codigos_regalo (
  codigo text primary key, dias integer not null default 30,
  creado timestamptz default now(), usado_por uuid references auth.users on delete set null, usado timestamptz
);
alter table public.codigos_regalo enable row level security;
create or replace function public.canjear_codigo(c text) returns text
language plpgsql security definer set search_path = public as $$
declare r public.codigos_regalo;
begin
  if auth.uid() is null then return 'inicia sesión'; end if;
  select * into r from public.codigos_regalo where codigo = upper(trim(c)) for update;
  if not found then return 'no existe'; end if;
  if r.usado_por is not null then return 'ya usado'; end if;
  update public.codigos_regalo set usado_por = auth.uid(), usado = now() where codigo = r.codigo;
  update public.perfiles set plan = 'pro',
         plan_hasta = greatest(coalesce(plan_hasta, now()), now()) + make_interval(days => r.dias)
   where id = auth.uid();
  insert into public.movimientos (usuario, cantidad, motivo) values (auth.uid(), 0, 'codigo ' || r.codigo);
  return 'ok';
end $$;
revoke execute on function public.canjear_codigo(text) from public, anon;
grant execute on function public.canjear_codigo(text) to authenticated;

-- suscripciones de Mercado Pago (las escriben las funciones `vip` y `mp-webhook`)
create table if not exists public.suscripciones (
  id text primary key, usuario uuid not null references auth.users on delete cascade,
  tipo text not null, precio numeric(8,2) not null, fundador boolean not null default false,
  estado text not null default 'pending', proximo_cobro timestamptz,
  creado timestamptz default now(), actualizado timestamptz default now()
);
alter table public.suscripciones enable row level security;
drop policy if exists "cada quien sus suscripciones" on public.suscripciones;
create policy "cada quien sus suscripciones" on public.suscripciones for select using (auth.uid() = usuario);
grant select on public.suscripciones to authenticated;
grant all on public.suscripciones to service_role;
create or replace function public.lugares_fundador() returns integer
language sql stable security definer set search_path = public as $$
  select greatest(0, 50 - (select count(distinct usuario)::int from public.suscripciones where fundador and estado = 'authorized'));
$$;
grant execute on function public.lugares_fundador() to anon, authenticated;
insert into public.ajustes (clave, valor) values ('precio_mensual', '149'), ('precio_fundador', '99'),
  ('precio_semestral', '749'), ('lugares_fundador', '50') on conflict (clave) do nothing;

-- el enlace del grupo VIP: sólo al VIP (o, en el lanzamiento, a quien tiene cuenta)
create table if not exists public.privados (clave text primary key, valor text not null);
alter table public.privados enable row level security;
create or replace function public.enlace_vip() returns text
language sql stable security definer set search_path = public as $$
  select valor from public.privados where clave = 'telegram_vip'
     and (public.es_pro() or (auth.uid() is not null and exists (select 1 from public.ajustes where clave = 'telegram_vip_abierto' and valor = '1')));
$$;
revoke execute on function public.enlace_vip() from public, anon;
grant execute on function public.enlace_vip() to authenticated;

-- (el registro del administrador: cuando el dueño cree su cuenta «HMREY»)
-- update public.perfiles set admin = true where lower(usuario) = 'hmrey';
notify pgrst, 'reload schema';
