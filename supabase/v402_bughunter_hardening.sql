-- v402 — hardening de perfiles, separación del VIP y comentarios con rate limit.
-- Ejecutar en Supabase SQL Editor antes de desplegar las Edge Functions v402.
-- No contiene secretos. Repetible sin resetear saldo ni suscripciones.

-- SHP-004: los perfiles los crea el trigger/servidor, no el cliente.
revoke insert on public.perfiles from anon, authenticated;
revoke update on public.perfiles from authenticated;
grant update (nombre, deportes, usuario) on public.perfiles to authenticated;

-- SHP-005: el acceso al contenido premium y el enlace del grupo VIP son permisos distintos.
insert into public.ajustes (clave, valor)
values ('telegram_vip_abierto', '0')
on conflict (clave) do nothing;

create or replace function public.enlace_vip() returns text
language sql stable security definer set search_path = public as $$
  select valor
    from public.privados
   where clave = 'telegram_vip'
     and (
       public.es_pro()
       or (
         auth.uid() is not null
         and exists (
           select 1 from public.ajustes
            where clave = 'telegram_vip_abierto' and valor = '1'
         )
       )
     );
$$;
revoke execute on function public.enlace_vip() from public, anon;
grant execute on function public.enlace_vip() to authenticated;

-- SHP-001/002: pago VIP único, idempotente y transaccional.
-- Si se inserta el asiento pero falla la concesión de VIP, PostgreSQL revierte
-- toda la función; un reintento puede intentarlo otra vez. Un pago ya aplicado
-- no vuelve a sumar meses porque la clave externa ya existe.
create or replace function public.procesar_vip_unico(
  p_id text,
  p_usuario uuid,
  p_meses integer,
  p_precio numeric,
  p_fundador boolean
) returns boolean
language plpgsql security definer set search_path = public as $$
declare
  v_insertado text;
begin
  if p_id is null or length(p_id) < 6 or length(p_id) > 200
     or p_usuario is null
     or p_meses not in (1, 6)
     or p_precio is null or p_precio < 0 then
    raise exception 'Parámetros de pago inválidos';
  end if;

  insert into public.suscripciones
    (id, usuario, tipo, precio, fundador, estado, renueva, actualizado)
  values
    (p_id, p_usuario, case when p_meses = 6 then 'semestral' else 'mensual' end,
     p_precio, coalesce(p_fundador, false), 'pagado', false, now())
  on conflict (id) do nothing
  returning id into v_insertado;

  if v_insertado is null then
    return false; -- ese pago ya se procesó por completo anteriormente
  end if;

  update public.perfiles
     set plan = 'pro',
         plan_hasta = greatest(coalesce(plan_hasta, now()), now())
                      + make_interval(months => p_meses)
   where id = p_usuario;

  if not found then
    raise exception 'No existe el perfil al que corresponde el pago';
  end if;

  return true;
end;
$$;
revoke all on function public.procesar_vip_unico(text, uuid, integer, numeric, boolean) from public, anon, authenticated;
grant execute on function public.procesar_vip_unico(text, uuid, integer, numeric, boolean) to service_role;

-- SHP-014: límite de 5 comentarios por huella de origen en una ventana de una hora.
create table if not exists public.comentarios_rate_limit (
  fingerprint text primary key check (fingerprint ~ '^[0-9a-f]{64}$'),
  window_start timestamptz not null default now(),
  requests integer not null default 0 check (requests >= 0),
  updated_at timestamptz not null default now()
);
alter table public.comentarios_rate_limit enable row level security;
revoke all on public.comentarios_rate_limit from public, anon, authenticated;
grant all on public.comentarios_rate_limit to service_role;

-- Sólo la Edge Function (service_role) puede invocarla. Las cuentas anónimas
-- ya no insertan directamente en comentarios desde PostgREST.
create or replace function public.registrar_comentario(
  p_fingerprint text,
  p_tipo text,
  p_texto text,
  p_correo text,
  p_pagina text,
  p_usuario uuid
) returns jsonb
language plpgsql security definer set search_path = public as $$
declare
  v_intentos integer;
  v_id bigint;
begin
  if p_fingerprint is null or p_fingerprint !~ '^[0-9a-f]{64}$'
     or p_tipo is null or p_tipo not in ('idea', 'falla', 'otro')
     or p_texto is null or char_length(btrim(p_texto)) < 3 or char_length(p_texto) > 2000
     or (p_correo is not null and char_length(p_correo) > 200)
     or (p_pagina is not null and char_length(p_pagina) > 300) then
    return jsonb_build_object('ok', false, 'reason', 'invalid');
  end if;

  insert into public.comentarios_rate_limit as cr
    (fingerprint, window_start, requests, updated_at)
  values (p_fingerprint, now(), 1, now())
  on conflict (fingerprint) do update
    set requests = case
          when cr.window_start <= now() - interval '1 hour' then 1
          else cr.requests + 1
        end,
        window_start = case
          when cr.window_start <= now() - interval '1 hour' then now()
          else cr.window_start
        end,
        updated_at = now()
  returning requests into v_intentos;

  if v_intentos > 5 then
    return jsonb_build_object('ok', false, 'reason', 'rate_limit');
  end if;

  insert into public.comentarios (tipo, texto, correo, pagina, usuario)
  values (p_tipo, btrim(p_texto), nullif(btrim(p_correo), ''), nullif(btrim(p_pagina), ''), p_usuario)
  returning id into v_id;

  return jsonb_build_object('ok', true, 'id', v_id);
end;
$$;
revoke all on function public.registrar_comentario(text, text, text, text, text, uuid) from public, anon, authenticated;
grant execute on function public.registrar_comentario(text, text, text, text, text, uuid) to service_role;

-- Los comentarios se reciben por la Edge Function v402, no con INSERT directo.
alter table public.comentarios enable row level security;
drop policy if exists "cualquiera deja comentario" on public.comentarios;
revoke insert on public.comentarios from anon, authenticated;
grant all on public.comentarios to service_role;
grant all on sequence public.comentarios_id_seq to service_role;

notify pgrst, 'reload schema';
