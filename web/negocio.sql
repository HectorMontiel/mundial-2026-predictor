-- ATENCIÓN v402: bootstrap histórico. No lo vuelvas a ejecutar sobre una base que ya recibió
-- v383 o migraciones posteriores: algunas funciones son versiones antiguas y podrían
-- reemplazar comportamiento de usuario/admin. En bases existentes, aplica las migraciones
-- versionadas en orden; v402_bughunter_hardening.sql endurece los permisos actuales.
-- v379 — SharPicks: cuentas, «Mis picks», monedas y «No Win, No Pay».
-- Se puede correr las veces que haga falta (todo es «si no existe»).
--
-- LANZAMIENTO: todo GRATIS (precio 0 y ningún pick premium), como hace
-- BetFlipAi. El día que se decida cobrar sólo se cambia `ajustes`:
--   update public.ajustes set valor = '10' where clave = 'precio_diamante';
-- y `exportar_web.py` marca premium las 💎 (PREMIUM_DESDE en el entorno).
--
-- SEGURIDAD: el texto de una apuesta premium NO va en `picks` (que lee
-- todo el mundo) sino en `picks_premium`, y la base sólo lo deja leer a
-- quien la desbloqueó, a quien tiene plan Pro, o cuando el partido ya
-- terminó y quedó liquidado. Esconderlo en la página no serviría: cualquiera mira el código.

-- ---------- ajustes (precios) ----------
create table if not exists public.ajustes (clave text primary key, valor text not null);
insert into public.ajustes (clave, valor) values
  ('precio_diamante', '0'), ('precio_platino', '0'), ('precio_oro', '0'), ('precio_plata', '0'),
  ('monedas_bienvenida', '50')
on conflict (clave) do nothing;
alter table public.ajustes enable row level security;
drop policy if exists "todos leen ajustes" on public.ajustes;
create policy "todos leen ajustes" on public.ajustes for select using (true);
grant select on public.ajustes to anon, authenticated;

-- ---------- perfil de cada usuario ----------
alter table public.perfiles add column if not exists monedas integer not null default 0;
alter table public.perfiles add column if not exists plan text not null default 'gratis';
alter table public.perfiles add column if not exists plan_hasta timestamptz;
alter table public.perfiles add column if not exists deportes text[];
-- el usuario puede cambiar su nombre y deportes, NUNCA sus monedas ni su plan
revoke update on public.perfiles from authenticated;
revoke insert on public.perfiles from anon, authenticated;
grant update (nombre, deportes) on public.perfiles to authenticated;

create or replace function public.nuevo_usuario() returns trigger
language plpgsql security definer set search_path = public as $$
declare bienvenida int := coalesce((select valor::int from public.ajustes where clave = 'monedas_bienvenida'), 0);
begin
  insert into public.perfiles (id, nombre, monedas)
  values (new.id, coalesce(new.raw_user_meta_data->>'nombre', split_part(new.email, '@', 1)), bienvenida)
  on conflict (id) do nothing;
  if bienvenida > 0 then
    insert into public.movimientos (usuario, cantidad, motivo) values (new.id, bienvenida, 'bienvenida');
  end if;
  return new;
end $;
revoke execute on function public.nuevo_usuario() from public, anon, authenticated;

-- ---------- movimientos de monedas (todo queda apuntado) ----------
create table if not exists public.movimientos (
  id bigserial primary key,
  usuario uuid not null references auth.users on delete cascade,
  cantidad integer not null,
  motivo text not null,            -- bienvenida | desbloqueo | devolucion | compra
  pick text,
  creado timestamptz default now()
);
alter table public.movimientos enable row level security;
drop policy if exists "cada quien sus movimientos" on public.movimientos;
create policy "cada quien sus movimientos" on public.movimientos for select using (auth.uid() = usuario);
grant select on public.movimientos to authenticated;

drop trigger if exists al_registrarse on auth.users;
create trigger al_registrarse after insert on auth.users
  for each row execute function public.nuevo_usuario();

-- ---------- «Mis picks»: los que sigue cada usuario ----------
create table if not exists public.seguidos (
  usuario uuid not null default auth.uid() references auth.users on delete cascade,
  pick text not null references public.picks (id) on delete cascade,
  creado timestamptz default now(),
  primary key (usuario, pick)
);
alter table public.seguidos enable row level security;
drop policy if exists "cada quien sus seguidos" on public.seguidos;
create policy "cada quien sus seguidos" on public.seguidos for all
  using (auth.uid() = usuario) with check (auth.uid() = usuario);
grant select, insert, delete on public.seguidos to authenticated;

-- ---------- picks premium (el texto, protegido) ----------
create table if not exists public.picks_premium (
  id text primary key references public.picks (id) on delete cascade,
  apuesta text not null
);
create table if not exists public.desbloqueos (
  usuario uuid not null references auth.users on delete cascade,
  pick text not null references public.picks (id) on delete cascade,
  monedas integer not null,
  devuelto boolean not null default false,
  creado timestamptz default now(),
  primary key (usuario, pick)
);
alter table public.picks_premium enable row level security;
alter table public.desbloqueos enable row level security;
drop policy if exists "cada quien sus desbloqueos" on public.desbloqueos;
create policy "cada quien sus desbloqueos" on public.desbloqueos for select using (auth.uid() = usuario);
grant select on public.desbloqueos to authenticated;

create or replace function public.es_pro() returns boolean
language sql stable security definer set search_path = public as $$
  select exists (select 1 from public.perfiles where id = auth.uid() and plan = 'pro'
                 and (plan_hasta is null or plan_hasta > now()));
$$;
drop policy if exists "premium a quien le toca" on public.picks_premium;
create policy "premium a quien le toca" on public.picks_premium for select using (
  public.es_pro()
  or exists (select 1 from public.desbloqueos d where d.pick = picks_premium.id and d.usuario = auth.uid())
  or exists (select 1 from public.picks p where p.id = picks_premium.id and p.estado in ('verde','roja','nula'))
);
grant select on public.picks_premium to anon, authenticated;
grant all on public.picks_premium to service_role;

-- precio de un pick según su nivel (💎 = ⭐ ELIGE; 🔷 ≥ 85 %; 🥇 ≥ 80 %)
create or replace function public.precio_pick(p public.picks) returns integer
language sql stable set search_path = public as $$
  select coalesce((select valor::int from public.ajustes where clave =
    case when p.elige then 'precio_diamante' when p.prob >= 0.85 then 'precio_platino'
         when p.prob >= 0.80 then 'precio_oro' else 'precio_plata' end), 0);
$$;

-- desbloquear: cobra las monedas (si alcanzan) y lo apunta. Sólo antes del partido.
create or replace function public.desbloquear(pick_id text) returns text
language plpgsql security definer set search_path = public as $$
declare p public.picks; precio int; saldo int;
begin
  if auth.uid() is null then return 'inicia sesión'; end if;
  select * into p from public.picks where id = pick_id;
  if not found then return 'no existe'; end if;
  if p.inicio <= now() then return 'ya empezó'; end if;
  if exists (select 1 from public.desbloqueos where usuario = auth.uid() and pick = pick_id) then return 'ok'; end if;
  precio := public.precio_pick(p);
  select monedas into saldo from public.perfiles where id = auth.uid() for update;
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

-- NO WIN, NO PAY: cuando un pick sale rojo (o nulo), se devuelven solas las
-- monedas a todos los que lo desbloquearon. Lo hace la base, no la página.
create or replace function public.devolver_si_falla() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  if new.estado in ('roja', 'nula') and coalesce(old.estado, '') not in ('roja', 'nula') then
    update public.perfiles pf set monedas = pf.monedas + d.monedas
      from public.desbloqueos d
     where d.pick = new.id and not d.devuelto and d.monedas > 0 and pf.id = d.usuario;
    insert into public.movimientos (usuario, cantidad, motivo, pick)
      select usuario, monedas, 'devolucion', new.id from public.desbloqueos
       where pick = new.id and not devuelto and monedas > 0;
    update public.desbloqueos set devuelto = true where pick = new.id and not devuelto;
  end if;
  return new;
end $;
revoke execute on function public.devolver_si_falla() from public, anon, authenticated;
drop trigger if exists no_win_no_pay on public.picks;
create trigger no_win_no_pay after update of estado on public.picks
  for each row execute function public.devolver_si_falla();

-- cuántos siguen cada pick (como los «Miembros» de BetFlipAi), sin decir quiénes
create or replace view public.seguidores with (security_invoker = false) as
  select pick, count(*)::int as n from public.seguidos group by pick;
grant select on public.seguidores to anon, authenticated;

-- lo ya mandado a cada canal de Telegram (`telegram_canales.py`, clave de servicio)
create table if not exists public.telegram_enviados (
  pick text not null, canal text not null, tipo text not null default 'pick',
  enviado timestamptz default now(), primary key (pick, canal, tipo)
);
alter table public.telegram_enviados enable row level security;
grant all on public.telegram_enviados to service_role;

notify pgrst, 'reload schema';

-- v380 — lo que se mandó a Telegram (gratis y VIP), para el historial público
create or replace view public.telegram_publicados with (security_invoker = false) as
  select canal, pick as clave, min(enviado) as enviado
    from public.telegram_enviados where tipo = 'pick' group by canal, pick;
grant select on public.telegram_publicados to anon, authenticated;

-- v381 — el acceso premium con cuenta queda cerrado por defecto.
-- Sólo abrirlo mediante un ajuste explícito cuando esa política comercial esté aprobada.
insert into public.ajustes (clave, valor) values ('premium_con_cuenta', '0') on conflict (clave) do nothing;
drop policy if exists "premium a quien le toca" on public.picks_premium;
create policy "premium a quien le toca" on public.picks_premium for select using (
  public.es_pro()
  or exists (select 1 from public.desbloqueos d where d.pick = picks_premium.id and d.usuario = auth.uid())
  or exists (select 1 from public.picks p where p.id = picks_premium.id and p.estado in ('verde','roja','nula'))
  or (auth.uid() is not null and exists (select 1 from public.ajustes a where a.clave = 'premium_con_cuenta' and a.valor = '1'))
);
notify pgrst, 'reload schema';
