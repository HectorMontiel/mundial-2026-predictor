-- v404 — fuente canónica del precio por cuota.
-- La función en producción ya usaba esta regla; este archivo vuelve reproducible
-- su definición y evita que una instalación nueva cobre por categoría antigua.
-- No cambia los precios ya configurados: los valores iniciales sólo se insertan
-- cuando falta la banda correspondiente.

create table if not exists public.precios_cuota (
  desde numeric(6,2) primary key,
  hasta numeric(6,2) not null,
  monedas integer not null check (monedas >= 0),
  check (desde < hasta)
);

insert into public.precios_cuota (desde, hasta, monedas) values
  (1.00, 1.30, 5),
  (1.30, 1.60, 8),
  (1.60, 2.00, 12),
  (2.00, 3.00, 18),
  (3.00, 99.00, 25)
on conflict (desde) do nothing;

alter table public.precios_cuota enable row level security;
drop policy if exists "precios_cuota_public_read" on public.precios_cuota;
create policy "precios_cuota_public_read" on public.precios_cuota
  for select to anon, authenticated using (true);
grant select on public.precios_cuota to anon, authenticated;

create or replace function public.precio_pick(p public.picks) returns integer
language sql stable set search_path = public as $function$
  select case
    when not (
      coalesce((p).elige, false)
      or coalesce((p).tipo, 'pick') = 'error'
      or coalesce((p).prob, 0) >= 0.85
    ) then 0
    else coalesce((
      select pc.monedas
        from public.precios_cuota pc
       where coalesce((p).cuota, 1) >= pc.desde
         and coalesce(p.cuota, 1) < pc.hasta
       order by pc.desde
       limit 1
    ), 10)
  end;
$function$;

notify pgrst, 'reload schema';