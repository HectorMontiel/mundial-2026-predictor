-- v397 — DESBLOQUEAR UNA COMBINADA ENTERA CON MONEDAS, con «No Win, No Pay».
-- Precio: la tabla de siempre (precios_cuota) con la CUOTA TOTAL de la
-- combinada. Si ya tenías alguna pata desbloqueada, pagas lo menor entre ese
-- precio y lo que costarían las patas que te faltan. Si la combinada sale roja
-- (o nula), las monedas se devuelven solas.

create table if not exists public.desbloqueos_combinada (
  usuario uuid not null references auth.users on delete cascade,
  combinada text not null references public.combinadas (id) on delete cascade,
  monedas integer not null,
  devuelto boolean not null default false,
  creado timestamptz default now(),
  primary key (usuario, combinada)
);
alter table public.desbloqueos_combinada enable row level security;
drop policy if exists "cada quien sus combinadas" on public.desbloqueos_combinada;
create policy "cada quien sus combinadas" on public.desbloqueos_combinada for select using (auth.uid() = usuario);
grant select on public.desbloqueos_combinada to authenticated;
grant all on public.desbloqueos_combinada to service_role;

create or replace function public.precio_por_cuota(c numeric) returns integer
language sql stable set search_path = public as $$
  select coalesce((select monedas::int from public.precios_cuota where c >= desde and c < hasta order by desde limit 1), 10);
$$;

create or replace function public.desbloquear_combinada(comb_id text) returns text
language plpgsql security definer set search_path = public as $$
declare c public.combinadas; faltan text[]; precio int; suelto int; saldo int; es_admin boolean;
begin
  if auth.uid() is null then return 'inicia sesión'; end if;
  select * into c from public.combinadas where id = comb_id;
  if not found then return 'no existe'; end if;
  if exists (select 1 from jsonb_array_elements(c.patas) x where (x->>'inicio')::timestamptz <= now()) then
    return 'ya empezó';
  end if;
  if exists (select 1 from public.desbloqueos_combinada where usuario = auth.uid() and combinada = comb_id) then return 'ok'; end if;
  -- las patas premium que aún no tienes
  select coalesce(array_agg(p.id), '{}') into faltan
    from jsonb_array_elements(c.patas) x join public.picks p on p.id = x->>'id'
   where p.premium and not exists (select 1 from public.desbloqueos d where d.usuario = auth.uid() and d.pick = p.id);
  if array_length(faltan, 1) is null then return 'ok'; end if;
  select monedas, admin into saldo, es_admin from public.perfiles where id = auth.uid() for update;
  select coalesce(sum(public.precio_por_cuota(p.cuota)), 0) into suelto from public.picks p where p.id = any(faltan);
  precio := case when es_admin then 0 else least(public.precio_por_cuota(c.cuota), suelto) end;
  if coalesce(saldo, 0) < precio then return 'sin monedas'; end if;
  update public.perfiles set monedas = monedas - precio where id = auth.uid() and precio > 0;
  insert into public.desbloqueos_combinada (usuario, combinada, monedas) values (auth.uid(), comb_id, precio);
  -- las patas quedan abiertas (con 0 monedas: la devolución va por la combinada)
  insert into public.desbloqueos (usuario, pick, monedas)
    select auth.uid(), unnest(faltan), 0 on conflict do nothing;
  if precio > 0 then
    insert into public.movimientos (usuario, cantidad, motivo, pick) values (auth.uid(), -precio, 'desbloqueo combinada', comb_id);
  end if;
  return 'ok';
end $$;
revoke execute on function public.desbloquear_combinada(text) from anon, public;
grant execute on function public.desbloquear_combinada(text) to authenticated;

-- NO WIN, NO PAY de la combinada: roja o nula → se devuelven las monedas
create or replace function public.devolver_combinada_si_falla() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  if new.estado in ('roja', 'nula') and coalesce(old.estado, '') not in ('roja', 'nula') then
    update public.perfiles pf set monedas = pf.monedas + d.monedas
      from public.desbloqueos_combinada d
     where d.combinada = new.id and not d.devuelto and d.monedas > 0 and pf.id = d.usuario;
    insert into public.movimientos (usuario, cantidad, motivo, pick)
      select usuario, monedas, 'devolucion combinada', new.id from public.desbloqueos_combinada
       where combinada = new.id and not devuelto and monedas > 0;
    update public.desbloqueos_combinada set devuelto = true where combinada = new.id and not devuelto;
  end if;
  return new;
end $$;
drop trigger if exists no_win_no_pay_combinada on public.combinadas;
create trigger no_win_no_pay_combinada after update of estado on public.combinadas
  for each row execute function public.devolver_combinada_si_falla();
notify pgrst, 'reload schema';
