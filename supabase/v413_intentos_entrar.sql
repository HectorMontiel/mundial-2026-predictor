-- v413 — LÍMITE DE INTENTOS AL ENTRAR CON USUARIO.
-- La función `entrar` inicia la sesión desde el servidor: para Supabase todos
-- los intentos llegan de la MISMA dirección (la de la función), así que su
-- límite por IP no protegía cada cuenta y, al llenarse, bloqueaba a todos.
-- Aquí se cuentan los FALLOS por usuario y por la IP real de quien intenta:
--   · 5 fallos del mismo usuario en 15 min → ese usuario espera.
--   · 20 fallos desde la misma IP en 15 min → esa IP espera.
-- Un acierto borra los fallos de ese usuario. Sólo la función (service_role)
-- puede leer o escribir esto.
create table if not exists public.intentos_entrar (
  id bigserial primary key,
  usuario text not null,
  ip text,
  cuando timestamptz not null default now()
);
create index if not exists intentos_entrar_usuario on public.intentos_entrar (usuario, cuando desc);
create index if not exists intentos_entrar_ip on public.intentos_entrar (ip, cuando desc);
alter table public.intentos_entrar enable row level security;
revoke all on table public.intentos_entrar from public, anon, authenticated;
revoke all on sequence public.intentos_entrar_id_seq from public, anon, authenticated;

create or replace function public.puede_entrar(p_usuario text, p_ip text)
returns boolean
language sql stable security definer set search_path = public as $puede_entrar$
  select (select count(*) from public.intentos_entrar
           where usuario = lower(btrim(p_usuario)) and cuando > now() - interval '15 minutes') < 5
     and (coalesce(p_ip, '') = ''
          or (select count(*) from public.intentos_entrar
               where ip = p_ip and cuando > now() - interval '15 minutes') < 20);
$puede_entrar$;

create or replace function public.anotar_entrar(p_usuario text, p_ip text, p_ok boolean)
returns void
language plpgsql security definer set search_path = public as $anotar_entrar$
begin
  if p_ok then
    delete from public.intentos_entrar where usuario = lower(btrim(p_usuario));
  else
    insert into public.intentos_entrar (usuario, ip) values (lower(btrim(p_usuario)), nullif(p_ip, ''));
  end if;
  delete from public.intentos_entrar where cuando < now() - interval '1 day';
end;
$anotar_entrar$;

revoke all on function public.puede_entrar(text, text) from public, anon, authenticated;
revoke all on function public.anotar_entrar(text, text, boolean) from public, anon, authenticated;
grant execute on function public.puede_entrar(text, text) to service_role;
grant execute on function public.anotar_entrar(text, text, boolean) to service_role;
notify pgrst, 'reload schema';
