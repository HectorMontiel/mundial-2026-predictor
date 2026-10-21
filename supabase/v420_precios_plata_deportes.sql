-- v420 — PRECIOS QUE SIGUEN A LA CUOTA, PLATA A MONEDAS Y EL HISTORIAL POR DEPORTE.
--
-- Medido sobre los 1.219 picks liquidados del 9 al 21-oct:
--   💎 Diamante 86,6 % a 1,12 · 🥈 Plata 80,5 % a 1,21 · 🥇 Oro 80,1 % a 1,16
--   💰 Cuota alta 55,5 % a 2,30 (+24,8 por cada $100)
-- 1) Con la banda 1,01-1,29 = 5 🪙, el 100 % de los 💎 y 🥇 y el 97 % de los 🥈
--    costaban lo mismo. Escalones donde de verdad caen nuestras cuotas, con
--    5 🪙 de MÍNIMO (lo pidió el usuario), y si sale roja las monedas
--    regresan (No Win, No Pay).
delete from public.precios_cuota;
insert into public.precios_cuota (desde, hasta, monedas) values
  (1.00, 1.15, 5),
  (1.15, 1.30, 6),
  (1.30, 1.50, 8),
  (1.50, 1.80, 10),
  (1.80, 2.20, 14),
  (2.20, 3.00, 18),
  (3.00, 99.00, 25);

-- 2) 🥈 Plata pasa a monedas (acierta más y paga más que 🥇 Oro, que se queda
--    gratis). Las tarjetas de «sólo análisis» nunca se cobran.
create or replace function public.precio_pick(p public.picks) returns integer
language sql stable set search_path = public as $function$
  select case
    when coalesce((p).tipo, 'pick') = 'analisis' then 0
    when not coalesce((p).elige, false) and coalesce((p).tipo, 'pick') <> 'error'
         and coalesce((p).prob, 0) >= 0.80 and coalesce((p).prob, 0) < 0.85 then 0      -- 🥇 Oro: gratis
    else coalesce((
      select pc.monedas
        from public.precios_cuota pc
       where coalesce((p).cuota, 1) >= pc.desde
         and coalesce((p).cuota, 1) < pc.hasta
       order by pc.desde
       limit 1
    ), 10)
  end;
$function$;

-- 3) El historial por deporte (30 días), con la misma regla de la página.
create or replace view public.historial_deportes with (security_invoker = true) as
select coalesce(deporte, 'Otro') as deporte,
       (count(*) filter (where estado = 'verde'))::int as verdes,
       (count(*) filter (where estado = 'roja'))::int as rojas,
       round(sum(case when estado = 'verde' then cuota - 1 when estado = 'roja' then -1 else 0 end) * 100
             / nullif(count(*) filter (where estado in ('verde', 'roja')), 0), 1) as gana_por_100
  from public.picks
 where fecha >= current_date - 30 and coalesce(tipo, 'pick') not in ('analisis', 'error')
 group by 1;
grant select on public.historial_deportes to anon, authenticated;

-- 4) historial_niveles también con lo que gana cada nivel por $100 (💰 Cuota
--    alta acierta 55 % pero gana +25: es lo que de verdad presume)
create or replace view public.historial_niveles with (security_invoker = true) as
select case when tipo = 'error' then 'Cuota alta'
            when elige then 'Diamante'
            when prob >= 0.85 then 'Platino'
            when prob >= 0.80 then 'Oro'
            else 'Plata' end as nivel,
       (count(*) filter (where estado = 'verde'))::int as verdes,
       (count(*) filter (where estado = 'roja'))::int as rojas,
       min(fecha) as desde, max(fecha) as hasta,
       round(sum(case when estado = 'verde' then cuota - 1 when estado = 'roja' then -1 else 0 end) * 100
             / nullif(count(*) filter (where estado in ('verde', 'roja')), 0), 1) as gana_por_100
  from public.picks
 where fecha >= current_date - 30 and coalesce(tipo, 'pick') <> 'analisis'
 group by 1;
grant select on public.historial_niveles to anon, authenticated;
notify pgrst, 'reload schema';
