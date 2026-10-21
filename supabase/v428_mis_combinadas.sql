-- v428 — «MIS COMBINADAS»: el usuario arma las suyas con los picks de la app y,
-- si aciertan, gana unas monedillas (moderadas: el chiste es que compre).
--   · 2 a 20 patas, de partidos distintos, todas pendientes y sin empezar.
--   · sólo picks que el usuario PUEDE ver (gratis, desbloqueados o es VIP).
--   · se guarda y ya no se cambia; a lo más 10 por día (anti-spam).
--   · premio por cuota total: < 2,00 nada · 2,00-2,99 → 2 🪙 · 3,00-4,99 → 3 🪙
--     · 5,00+ → 5 🪙; a lo más UNA premiada por día; cada 5 premiadas, +5 🪙.
--   · lo liquida el servidor (service_role), nunca la página.
create table if not exists public.combinadas_usuario (
  id uuid primary key default gen_random_uuid(),
  usuario uuid not null default auth.uid() references auth.users on delete cascade,
  patas text[] not null,
  cuota numeric(10,3) not null,
  inicio timestamptz not null,
  dia date not null,
  estado text not null default 'pendiente' check (estado in ('pendiente', 'verde', 'roja', 'nula')),
  premio integer not null default 0,
  creado timestamptz not null default now()
);
create index if not exists combinadas_usuario_usuario on public.combinadas_usuario (usuario, creado desc);
create index if not exists combinadas_usuario_pendientes on public.combinadas_usuario (estado) where estado = 'pendiente';
alter table public.combinadas_usuario enable row level security;
drop policy if exists "cada quien sus combinadas propias" on public.combinadas_usuario;
create policy "cada quien sus combinadas propias" on public.combinadas_usuario for select using (auth.uid() = usuario);
revoke all on table public.combinadas_usuario from public, anon, authenticated;
grant select on public.combinadas_usuario to authenticated;

create or replace function public.crear_combinada(p_patas text[]) returns uuid
language plpgsql security definer set search_path = public as $crear_combinada$
declare
  v_usuario uuid := auth.uid();
  v_n int := coalesce(array_length(p_patas, 1), 0);
  v_ok int; v_partidos int; v_cuota numeric; v_inicio timestamptz; v_id uuid;
begin
  if v_usuario is null then raise exception 'Inicia sesión para guardar tu combinada.'; end if;
  if v_n < 2 or v_n > 20 then raise exception 'Una combinada lleva de 2 a 20 picks.'; end if;
  if (select count(distinct x) from unnest(p_patas) x) <> v_n then raise exception 'Hay un pick repetido.'; end if;
  select count(*), count(distinct lower(p.partido)), exp(sum(ln(p.cuota))), min(p.inicio)
    into v_ok, v_partidos, v_cuota, v_inicio
    from public.picks p
   where p.id = any (p_patas) and p.estado = 'pendiente' and p.cuota > 1
     and p.inicio > now() + interval '1 minute'
     and coalesce(p.tipo, 'pick') not in ('analisis', 'combinada')
     and (not coalesce(p.premium, false) or public.es_pro()
          or exists (select 1 from public.desbloqueos d where d.pick = p.id and d.usuario = v_usuario));
  if v_ok <> v_n then raise exception 'Algún pick ya empezó, no existe o no lo tienes desbloqueado.'; end if;
  if v_partidos <> v_n then raise exception 'Cada pick tiene que ser de un partido distinto.'; end if;
  if (select count(*) from public.combinadas_usuario c where c.usuario = v_usuario and c.creado > now() - interval '1 day') >= 10 then
    raise exception 'Llevas 10 combinadas hoy: vuelve mañana.';
  end if;
  insert into public.combinadas_usuario (usuario, patas, cuota, inicio, dia)
  values (v_usuario, p_patas, round(v_cuota, 3), v_inicio, (v_inicio at time zone 'America/Mexico_City')::date)
  returning id into v_id;
  return v_id;
end;
$crear_combinada$;

create or replace function public.liquidar_combinadas_usuario() returns integer
language plpgsql security definer set search_path = public as $liquidar$
declare
  c record; v_estado text; v_cuota numeric; v_premio int; v_hechas int := 0; v_total int;
begin
  for c in select * from public.combinadas_usuario where estado = 'pendiente' order by creado loop
    select case when bool_or(p.estado = 'roja') then 'roja'
                when bool_and(p.estado in ('verde', 'nula')) and bool_or(p.estado = 'verde') then 'verde'
                when bool_and(p.estado = 'nula') then 'nula'
                else 'pendiente' end,
           exp(sum(ln(case when p.estado = 'verde' then p.cuota else 1 end)))
      into v_estado, v_cuota
      from public.picks p where p.id = any (c.patas);
    if v_estado is null or v_estado = 'pendiente' then continue; end if;
    v_premio := 0;
    if v_estado = 'verde' and not exists (
         select 1 from public.combinadas_usuario o where o.usuario = c.usuario and o.dia = c.dia and o.premio > 0) then
      v_premio := case when v_cuota >= 5 then 5 when v_cuota >= 3 then 3 when v_cuota >= 2 then 2 else 0 end;
    end if;
    update public.combinadas_usuario set estado = v_estado, premio = v_premio where id = c.id;
    if v_premio > 0 then
      update public.perfiles set monedas = monedas + v_premio where id = c.usuario;
      insert into public.movimientos (usuario, cantidad, motivo) values (c.usuario, v_premio, 'combinada acertada');
      select count(*) into v_total from public.combinadas_usuario where usuario = c.usuario and premio > 0;
      if v_total % 5 = 0 then
        update public.perfiles set monedas = monedas + 5 where id = c.usuario;
        insert into public.movimientos (usuario, cantidad, motivo) values (c.usuario, 5, 'bono: 5 combinadas premiadas');
      end if;
    end if;
    v_hechas := v_hechas + 1;
  end loop;
  return v_hechas;
end;
$liquidar$;

revoke all on function public.crear_combinada(text[]) from public, anon;
grant execute on function public.crear_combinada(text[]) to authenticated;
revoke all on function public.liquidar_combinadas_usuario() from public, anon, authenticated;
grant execute on function public.liquidar_combinadas_usuario() to service_role;
notify pgrst, 'reload schema';
